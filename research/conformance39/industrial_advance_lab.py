"""IND-04 local cycle transition with a signed R2 tool fact and atomic SQLite W.

The tool key is a *pinned laboratory actor*: it is NOT a certified external TOOL_TRUST
service or a source of physical truth. No official full-case claim should be based
only on this module. It explicitly refuses advance without an authenticated final.
"""
import json
from research.reference_executor.wire import Identity,ProtocolError,b64,raw,strict_verify,canonical,require,rec_ref,action_hash,keyid,sortset
from research.phase6.trusted_final import FACT_FIELDS,final_fact,final_fact_id,final_sign_bytes
from research.phase8.scene_authority import _rec, _json

class IndustrialAdvanceLab:
 def __init__(self,authority):
  require(authority.profile=='IND-DEMO-1','PROFILE')
  self.a=authority
  self.tool=Identity('fixture-industrial-tool',219)
  with self.a.db() as c:
   c.executescript('''CREATE TABLE IF NOT EXISTS ind_final(operation_id TEXT PRIMARY KEY,
      final_fact_id TEXT NOT NULL,final_json TEXT NOT NULL,final_seq INTEGER NOT NULL UNIQUE,effect_id TEXT UNIQUE);
      CREATE TABLE IF NOT EXISTS ind_transition(operation_id TEXT PRIMARY KEY,after_state TEXT NOT NULL);
   ''')
 def signed_final(self,op,attempt,seq=1,outcome='SUCCEEDED',now=110):
  action=op['action']
  fact={'ledger_id':'ind-ledger-1','operation_id':action['operation_id'],
        'action_hash':action_hash(self.a.profile,action),'dispatch_attempt':attempt,
        'tool':action['tool'],'tool_version':action['tool_version'],'destination':action['destination'],
        'outcome':outcome,'effect_id':('ind-effect-'+str(seq)) if outcome=='SUCCEEDED' else '',
        'no_late_effect':outcome!='SUCCEEDED','final_seq':str(seq),'finalized_at':str(now)}
  record=_rec(self.a.profile,'TOOL_FINAL',self.a.scope,
              {'method':'tool-final-v2',**fact,'iat':str(now),'exp':str(now+30),
               'attestation':{'issuer':self.tool.name,'kid':self.tool.kid,'sig':''}})
  record['value']['attestation']['sig']=b64(self.tool.key.sign(final_sign_bytes(record)))
  return record
 def _verify(self,record,op,attempt,now=111):
  require(type(record) is dict and set(record)=={'version','profile','kind','scope','value'},'FINAL_FIELDS')
  require(record['kind']=='TOOL_FINAL' and record['profile']==self.a.profile and record['scope']==self.a.scope,'FINAL_KIND')
  v=record['value']
  require(set(v)==set(FACT_FIELDS)|{'method','iat','exp','attestation'},'FINAL_FIELDS')
  require(set(v['attestation'])=={'issuer','kid','sig'},'FINAL_FIELDS')
  require(v['method']=='tool-final-v2' and v['ledger_id']=='ind-ledger-1' and
          v['tool']=='line-sort-sim' and v['tool_version']=='1' and
          v['operation_id']==op['action']['operation_id'] and
          v['action_hash']==action_hash(self.a.profile,op['action']) and v['dispatch_attempt']==attempt and
          v['destination']==op['action']['destination'],'FINAL_BINDING')
  require(v['attestation']['issuer']==self.tool.name and v['attestation']['kid']==self.tool.kid,'FINAL_SIGNER')
  require(int(v['finalized_at'])<=int(v['iat'])<=now<int(v['exp']) and int(v['exp'])-int(v['iat'])<=900,'FINAL_TIME')
  require((v['outcome']=='SUCCEEDED' and bool(v['effect_id']) and v['no_late_effect'] is False) or
          (v['outcome']=='FAILED_CONFIRMED' and v['effect_id']=='' and v['no_late_effect'] is True),'FINAL_OUTCOME')
  strict_verify(self.tool.pub,raw(v['attestation']['sig'],64),final_sign_bytes(record))
  return final_fact_id(record)
 def settle(self,op,record,now=111):
  oid=op['action']['operation_id']
  with self.a.tx() as c:
   accepted=c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
   require(accepted is not None and accepted['calls']==1,'NOT_STARTED')
   self._verify(record,op,accepted['attempt'],now)
   fid=final_fact_id(record)
   prior=c.execute('SELECT * FROM ind_final WHERE operation_id=?',(oid,)).fetchone()
   if prior:
    require(prior['final_fact_id']==fid and final_fact(json.loads(prior['final_json']))==final_fact(record),'CONTRADICTORY_FINAL')
    return c.execute('SELECT after_state FROM ind_transition WHERE operation_id=?',(oid,)).fetchone()[0]
   require(accepted['state']=='EFFECT_UNKNOWN','FINAL_STATE')
   frozen=json.loads(accepted['accepted_blob']);p=frozen['action']['payload']
   require(p['route']=='INSPECT' and p['inspection_cycle'] in ('1','2'),'ROUTE')
   scene=self.a._scene_current(c,op['scene_key']);r=scene['record']['value']
   require(r['state']=='ACCEPTED' and r['operation_id']==oid,'STALE_SCENE')
   res=c.execute('SELECT * FROM resource WHERE destination=?',(op['action']['destination'],)).fetchone()
   require(res is not None and res['reserved']>=1 and res['reserved']+res['spent']<=res['capacity'],'RESOURCE_INTEGRITY')
   behavior=c.execute('SELECT * FROM behavior WHERE principal=?',(op['action']['principal'],)).fetchone()
   require(behavior is not None and oid in json.loads(behavior['inflight']),'BEHAVIOR_INTEGRITY')
   task=c.execute('SELECT operation_id FROM flight WHERE task_id=?',(op['task_id'],)).fetchone()
   require(task is not None and task[0]==oid,'FLIGHT_INTEGRITY')
   outcome=record['value']['outcome']
   newstate=('AWAITING_REINSPECT' if p['inspection_cycle']=='1' else 'MANUAL_HOLD') if outcome=='SUCCEEDED' else 'STOPPED'
   new=dict(r);new['state']=newstate
   self.a._scene_update(c,op['scene_key'],scene['revision'],new)
   c.execute('UPDATE resource SET reserved=reserved-1,spent=spent+?,revision=revision+1 WHERE destination=?',
             (1 if outcome=='SUCCEEDED' else 0,op['action']['destination']))
   c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(op['task_id'],oid))
   next_inflight=sortset([x for x in json.loads(behavior['inflight']) if x!=oid])
   c.execute('UPDATE behavior SET inflight=?,revision=revision+1 WHERE principal=?',(_json(next_inflight),op['action']['principal']))
   bv=self.a.current(c,'BEHAVIOR',self.a.scope_key()+[op['action']['principal']])
   behavior_row=dict(bv['record']['value']);behavior_row['inflight']=next_inflight
   self.a._behavior_update(c,op['action']['principal'],bv['revision'],behavior_row)
   c.execute('UPDATE accept_intent SET state=?,settlements=1 WHERE operation_id=?',(outcome,oid))
   c.execute('INSERT INTO ind_final VALUES(?,?,?,?,?)',
             (oid,fid,_json(record),int(record['value']['final_seq']),record['value']['effect_id'] or None))
   c.execute('INSERT INTO ind_transition VALUES(?,?)',(oid,newstate))
  return newstate
 def advance_cycle2(self,op,controller_approved=False):
  """Privileged lab command; production needs C authentication + audit proofs."""
  require(controller_approved is True,'CONTROLLER_REQUIRED')
  oid=op['action']['operation_id']
  with self.a.tx() as c:
   prior=c.execute('SELECT * FROM ind_final WHERE operation_id=?',(oid,)).fetchone()
   require(prior is not None,'FINAL_MISSING')
   v=json.loads(prior['final_json'])['value']
   require(v['outcome']=='SUCCEEDED' and op['action']['payload']['route']=='INSPECT' and
           op['action']['payload']['inspection_cycle']=='1','FIRST_CYCLE_REQUIRED')
   scene=self.a._scene_current(c,op['scene_key']);r=scene['record']['value']
   require(r['state']=='AWAITING_REINSPECT' and r['inspection_cycle']=='1' and r['operation_id']==oid,'PHASE_GUARD')
   accepted=c.execute('SELECT accepted_blob FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
   require(accepted is not None,'MISSING_ACCEPTANCE')
   freeze=json.loads(accepted['accepted_blob'])
   new=dict(r);new.update({'inspection_cycle':'2','phase':'REINSPECT','state':'READY',
                           'evidence_ref':'','operation_id':'',
                           'predecessor_operation_id':oid,'predecessor_commit_ref':rec_ref(freeze['commit_record'])})
   self.a._scene_update(c,op['scene_key'],scene['revision'],new)
  return new
