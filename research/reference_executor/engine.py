"""ZJJ v2.6 R2 OFFLINE reference slice.

Uses signed real core Envelopes and domain-separated digests; trusted mock W
rows and in-memory transactions. This is NOT a full Profile implementation:
PAY history-int-v2, exact full COMMIT witness, C/E enrollment, persisted
ledger, all Schema rules, and transport are deliberately outside scope.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from threading import RLock
from collections import defaultdict
import copy
from .wire import (Identity,ProtocolError,require,digest,rec_ref,msgref,action_hash,
                   strict_verify,raw,b64,canonical,envelope,sortset,sid,PROFILE_SCENARIO)

ROLES={
 'PAY-1':{'H':'HOLDER','G':'ISSUER','X':'EXECUTOR','U':'FINANCE','V':'ANOMALY','E':'SOURCE'},
 'IND-DEMO-1':{'H':'HOLDER','G':'ISSUER','X':'EXECUTOR','U':'LINE_OPERATOR','V':'QUALITY_REVIEWER','E':'SOURCE'},
 'MED-DEMO-1':{'H':'HOLDER','G':'ISSUER','X':'EXECUTOR','U':'MEDICAL_AUTHORIZER','V':'CLINICAL_REVIEWER','E':'SOURCE'},
}
PROFILE_TOOL={'PAY-1':('pay-sim','pay-destination'),'IND-DEMO-1':('line-sort-sim','ind-inspection-bay'),'MED-DEMO-1':('med-order-sim','med-demo-ledger')}

@dataclass
class Row:
 rev:int
 value:dict
 ref:str

@dataclass
class Operation:
 profile:str
 action:dict
 ctx:dict
 intent:tuple
 task_id:str
 required:tuple
 basis:dict
 snap:tuple
 evidence:dict
 reviews:list=field(default_factory=list)
 authorization:dict|None=None
 permit:dict|None=None
 issue:dict|None=None
 challenge:dict|None=None
 challenge_request:dict|None=None
 proof:dict|None=None
 acceptance:dict|None=None
 status:str='PENDING'
 reservation:bool=False
 dispatch_attempt:str=''
 calls:int=0
 settlements:int=0
 finalfact:dict|None=None
 finalfact_id:str=''
 receipts:list=field(default_factory=list)
 nonce_consumed:bool=False

class ReferenceW:
 def __init__(self,profile,*,cap=8):
  require(profile in PROFILE_SCENARIO,'PROFILE')
  self.profile=profile;self.scope={'domain':'lab','tenant':'tenant-1','scenario':PROFILE_SCENARIO[profile]}
  self.lock=RLock();self.rows={};self.ops={};self.intent_accepted=set();self.keys={};self.idents={}
  self.now=100;self.nextid=1;self.cap=cap;self.reserved=0;self.spent=0
  self.published_denials=defaultdict(list);self.review_range_rev=defaultdict(int)
  self.effect_ids=set();self.final_sequences=set();self.seq_index=set();self.tool_facts={};self.tool_final_seq=0;self.tool_ledger_id='tool-ledger-1'
  self.tool_epoch=1;self.continuity=True
  roles=ROLES[profile]
  for i,alias in enumerate(('H','G','X','U','V','E','T','V2')):
   kind={'H':['IssueRequest','ChallengeRequest','CommitProof','StatusQuery'],
         'G':['Permit','Result'], 'X':['Challenge','Acceptance','Result'],
         'U':['Authorization'], 'V':['Review'], 'V2':['Review'],
         'E':[], 'T':[]}[alias]
   role=roles.get(alias,roles.get('V') if alias=='V2' else 'TOOL')
   who=Identity('fixture-'+alias.lower(),i+1,roles=[role],purposes=kind)
   self.idents[alias]=who;self.keys[who.kid]=who
  self.tool=self.idents['T'];self.sequence=0
  # Trusted C registration is a fixture, not a completed C/KEY_GRANT protocol.
  for alias,who in self.idents.items():
   self.publish('KEY',[who.kid],{'subject':who.name,'kid':who.kid,'purposes':sortset(list(who.purposes))})
   self.publish('ROLE',list(self.basekey())+[who.name,next(iter(who.roles))],{'subject':who.name,'role':next(iter(who.roles))})
  self.publish('POLICY',list(self.basekey()),{'revision':'1','profile':profile,'gateway':self.idents['G'].name,'executor':self.idents['X'].name,'source':self.idents['E'].name})

 def basekey(self):return (self.scope['domain'],self.scope['tenant'],self.scope['scenario'])
 def newid(self):
  k=sid(self.nextid);self.nextid+=1;return k
 def publish(self,namespace,key,value):
  """Fixture current authoritative row mutation. Not an authenticated C entrypoint."""
  with self.lock:
   k=(namespace,tuple(key));old=self.rows.get(k);revision=(old.rev+1 if old else 1)
   val=copy.deepcopy(value);ref=digest(['ZJJ-STATE-v1',namespace,list(key),str(revision),val])
   self.rows[k]=Row(revision,val,ref)
   return self.rows[k]
 def dep(self,namespace,key):
  r=self.rows.get((namespace,tuple(key)));require(r is not None,'STATE_UNAVAILABLE')
  return {'namespace':namespace,'key':list(key),'revision':str(r.rev),'ref':r.ref}
 def issuerdeps(self,aliases):
  out=[]
  for alias in aliases:
   who=self.idents[alias];role=next(iter(who.roles))
   out.extend([self.dep('KEY',[who.kid]),self.dep('ROLE',list(self.basekey())+[who.name,role])])
  return out
 def basedeps(self,op):
  key=list(self.basekey());p=op.action['payload'];o=[self.dep('POLICY',key),self.dep('TASK',key+[op.task_id])]
  if self.profile=='PAY-1':
   o.extend([self.dep('ORDER',key+[p['order_id'],p['stage']]),self.dep('EXPERIENCE',key+['fixed-partition'])])
  elif self.profile=='IND-DEMO-1':o.append(self.dep('UNIT',key+[p['line_id'],p['unit_id']]))
  else:o.append(self.dep('ENCOUNTER',key+[p['synthetic_patient_id'],p['encounter_id']]))
  o.append(self.dep('BEHAVIOR',key+[op.action['principal']]))
  o.extend(self.issuerdeps(['H','E']))
  return sortset(o)
 def fulldeps(self,op):
  deps=self.basedeps(op)+self.issuerdeps(['V','U','G','X'] if op.required else ['U','G','X'])
  return sortset({(d['namespace'],tuple(d['key'])):d for d in deps}.values())
 def action_for(self,payload,task_id=None,principal='principal'):
  tool,dest=PROFILE_TOOL[self.profile]
  if self.profile=='IND-DEMO-1':
   dest={'RELEASE':'ind-release-bin','QUARANTINE':'ind-quarantine-bin','INSPECT':'ind-inspection-bay'}[payload['route']]
  return {'scope':copy.deepcopy(self.scope),'operation_id':self.newid(),'principal':principal,
          'holder':self.idents['H'].name,'holder_kid':self.idents['H'].kid,
          'executor':self.idents['X'].name,'tool':tool,'tool_version':'1','destination':dest,'payload':copy.deepcopy(payload)}
 def fixed_decision(self,action,evidence):
  p=action['payload'];who=self.profile
  if who=='PAY-1':
   require(set(p)=={'order_id','stage','payer','payee','amount_minor','currency','purpose'},'PAY_FIELDS')
   require(p['currency']=='CNY' and p['purpose']=='order-settlement','PAY_POLICY')
   require(p['amount_minor'].isdigit() and int(p['amount_minor'])>0,'PAY_POLICY')
   # Risk scores/history-int-v2 NOT evaluated; caller fixture risk label is trusted.
   status=evidence.get('risk','CLEAR');require(status in ('CLEAR','ANOMALY','LOW_EVIDENCE'),'PAY_RISK_UNKNOWN')
   return tuple([] if status=='CLEAR' else [status])
  if who=='IND-DEMO-1':
   require(set(p)=={'line_id','unit_id','station_id','inspection_cycle','phase','route'},'IND_FIELDS')
   mapping={'DEMO_NORMAL':'RELEASE','DEMO_DEFECT':'QUARANTINE','DEMO_UNCERTAIN':'INSPECT'}
   label=evidence.get('label');require(label in mapping,'IND_LABEL')
   require(mapping[label]==p['route'],'CLAIM_FALSE')
   require(p['phase'] in ('INITIAL','REINSPECT'),'IND_PHASE')
   return tuple(['QUALITY_REVIEW'] if label=='DEMO_UNCERTAIN' else [])
  require(set(p)=={'synthetic_patient_id','encounter_id','order_group_id','phase','template_id','record_ref','destination_system'},'MED_FIELDS')
  require(evidence.get('available',False) and evidence.get('complete',False),'CLAIM_FALSE')
  mapping={'DEMO_A':'DEMO-ORDER-A','DEMO_B':'DEMO-ORDER-B'}
  require(p['template_id']==mapping.get(evidence.get('label')) and p['phase']=='SUBMIT','CLAIM_FALSE')
  require(p['destination_system']=='med-demo-ledger','CLAIM_FALSE')
  return ('CLINICAL_REVIEW',)
 def intent_for(self,action):
  p=action['payload'];x=list(self.basekey())
  if self.profile=='PAY-1':return tuple(x+[p['payer'],p['order_id'],p['stage']])
  if self.profile=='IND-DEMO-1':return tuple(x+[p['line_id'],p['unit_id'],p['inspection_cycle'],p['phase']])
  return tuple(x+[p['synthetic_patient_id'],p['encounter_id'],p['order_group_id'],'SUBMIT'])
 def prepare(self,payload,evidence,*,task_id=None):
  with self.lock:
   act=self.action_for(payload);needed=self.fixed_decision(act,evidence)
   tid=task_id or self.newid();key=list(self.basekey())
   self.publish('TASK',key+[tid],{'scope':self.scope,'operation_id':act['operation_id']})
   self.publish('BEHAVIOR',key+[act['principal']],{'accepted_count':'0','count_cap':'32','inflight':[]}) if ('BEHAVIOR',tuple(key+[act['principal']])) not in self.rows else None
   if self.profile=='PAY-1':
    self.publish('ORDER',key+[payload['order_id'],payload['stage']],{'payer':payload['payer'],'payee':payload['payee'],'amount_minor':payload['amount_minor']}) if ('ORDER',tuple(key+[payload['order_id'],payload['stage']])) not in self.rows else None
    self.publish('EXPERIENCE',key+['fixed-partition'],{'history_mode':'FIXTURE'}) if ('EXPERIENCE',tuple(key+['fixed-partition'])) not in self.rows else None
   elif self.profile=='IND-DEMO-1':
    uk=key+[payload['line_id'],payload['unit_id']]
    self.publish('UNIT',uk,{'state':'READY','inspection_cycle':payload['inspection_cycle'],'phase':payload['phase']}) if ('UNIT',tuple(uk)) not in self.rows else None
   else:
    ek=key+[payload['synthetic_patient_id'],payload['encounter_id']]
    self.publish('ENCOUNTER',ek,{'state':'READY','order_group_id':payload['order_group_id']}) if ('ENCOUNTER',tuple(ek)) not in self.rows else None
   intent=self.intent_for(act)
   ev={'version':'2.6','profile':self.profile,'kind':'FIXTURE_EVIDENCE','scope':self.scope,'value':copy.deepcopy(evidence)}
   ah=action_hash(self.profile,act)
   op=Operation(self.profile,act,{},intent,tid,needed,{},(),ev)
   base_deps=self.basedeps(op)
   assessment={'version':'2.6','profile':self.profile,'kind':'ASSESSMENT','scope':self.scope,
               'value':{'action_hash':ah,'method':'REFERENCE-SLICE','required_reviews':list(needed)}}
   basis={'version':'2.6','profile':self.profile,'kind':'BASIS','scope':self.scope,
          'value':{'scope':self.scope,'operation_id':act['operation_id'],'action':act,'action_hash':ah,
                   'policy_ref':self.dep('POLICY',key)['ref'],'task_ref':self.dep('TASK',key+[tid])['ref'],
                   'evidence_refs':[rec_ref(ev)],'assessment_ref':rec_ref(assessment),
                   'required_reviews':list(needed),'deps':base_deps,'iat':str(self.now),'exp':str(self.now+900)}}
   ctx={'scope':self.scope,'operation_id':act['operation_id'],'principal':act['principal'],'holder':act['holder'],
        'holder_kid':act['holder_kid'],'executor':act['executor'],'action_hash':ah,
        'policy_ref':basis['value']['policy_ref'],'basis_ref':rec_ref(basis)}
   op.ctx=ctx;op.basis=basis;op.snap=tuple(self.fulldeps(op));self.ops[act['operation_id']]=op
   return op
 def _verified(self,env,kind,alias):
  who=envelope(env,self.keys,self.now)
  require(env['protected']['type']==kind and who.kid==self.idents[alias].kid,'WRONG_ISSUER')
  require(env['body']['scope']==self.scope,'WRONG_SCOPE')
  require(ROLES[self.profile].get(alias, ROLES[self.profile]['V'] if alias=='V2' else '') in who.roles,'NO_ROLE')
  return env['body']['payload']
 def _guard(self,op):
  require(tuple(self.fulldeps(op))==op.snap,'STALE')
  require(op.action['holder_kid']==self.idents['H'].kid,'WRONG_HOLDER')
  require(op.action['executor']==self.idents['X'].name,'WRONG_ISSUER')
  require(op.action['holder']==self.idents['H'].name,'WRONG_HOLDER')
  require(self.idents['U'].name!=self.idents['G'].name and self.idents['U'].name!=self.idents['X'].name,'SUBJECT_SEPARATION')
  for purpose in op.required:
   require(not self.published_denials[(op.ctx['basis_ref'],purpose)],'REVIEW_DENY')
  require(op.intent not in self.intent_accepted,'DUPLICATE_INTENT')
  require(self.reserved+self.spent<self.cap,'RESOURCE_LIMIT')
  require(op.status=='PENDING','OPERATION_CONFLICT')
 def review(self,op,verdict='APPROVE',purpose=None,alias='V'):
  with self.lock:
   use=purpose or (op.required[0] if op.required else 'ANOMALY')
   # V2 tests alternate valid independent reviewer, only V participates in required closure.
   signer=self.idents[alias]
   deps=sortset(self.basedeps(op)+self.issuerdeps([alias]))
   env=signer.sign(self.profile,'Review',self.scope,
      {'ctx':op.ctx,'purpose':use,'verdict':verdict,'reason':'verified review'},
      deps=deps,aud=[self.idents[a].name for a in ['H','G','X','U']],at=self.now,iid=self.newid())
   p=self._verified(env,'Review',alias)
   require(p['ctx']==op.ctx,'BINDING')
   require(use in ('ANOMALY','LOW_EVIDENCE','QUALITY_REVIEW','CLINICAL_REVIEW') and verdict in ('APPROVE','DENY'),'REVIEW_PURPOSE')
   if verdict=='DENY':
    self.published_denials[(op.ctx['basis_ref'],use)].append(msgref(env));self.review_range_rev[(op.ctx['basis_ref'],use)]+=1
   else:op.reviews.append(env)
   return env
 def authorize(self,op,verdict='APPROVE'):
  with self.lock:
   require(len(op.reviews)==len(op.required),'REVIEW_REQUIRED')
   rr=sortset([msgref(r) for r in op.reviews]);require(tuple(sorted(r['body']['payload']['purpose'] for r in op.reviews))==tuple(sorted(op.required)),'REVIEW_PURPOSE')
   deps=sortset(self.basedeps(op)+self.issuerdeps(['U']+(['V'] if op.required else [])))
   env=self.idents['U'].sign(self.profile,'Authorization',self.scope,
         {'ctx':op.ctx,'review_refs':rr,'purpose':'EXECUTE','verdict':verdict},
         refs=rr,deps=deps,aud=[self.idents[a].name for a in ['H','G','X']],at=self.now,iid=self.newid())
   self._verified(env,'Authorization','U');op.authorization=env;return env
 def issue(self,op):
  with self.lock:
   require(op.authorization is not None,'MISSING_AUTH')
   reqrefs=sortset([msgref(r) for r in op.reviews]);authref=msgref(op.authorization)
   req=self.idents['H'].sign(self.profile,'IssueRequest',self.scope,
        {'ctx':op.ctx,'review_refs':reqrefs,'authorization_ref':authref},
        refs=reqrefs+[authref],deps=self.issuerdeps(['H']),aud=[self.idents['G'].name],at=self.now,iid=self.newid())
   self._verified(req,'IssueRequest','H')
   require(tuple(self.fulldeps(op))==op.snap,'STALE')
   self._check_authorization_chain(op,reqrefs,authref)
   require(tuple(self.fulldeps(op))==op.snap,'STALE')
   for purpose in op.required:require(not self.published_denials[(op.ctx['basis_ref'],purpose)],'REVIEW_DENY')
   permit=self.idents['G'].sign(self.profile,'Permit',self.scope,
        {'ctx':op.ctx,'review_refs':reqrefs,'authorization_ref':authref,'max_uses':'1','dispatch_before':str(self.now+120)},
        refs=reqrefs+[authref],deps=op.snap,aud=[self.idents['H'].name,self.idents['X'].name],at=self.now,iid=self.newid())
   self._verified(permit,'Permit','G');op.issue=req;op.permit=permit;return permit
 def _check_authorization_chain(self,op,reqrefs,authref):
  seen=[]
  for r in op.reviews:
   p=self._verified(r,'Review','V')
   require(p['ctx']==op.ctx and p['verdict']=='APPROVE','REVIEW_REQUIRED')
   expect=sortset(self.basedeps(op)+self.issuerdeps(['V']))
   require(r['body']['deps']==expect,'DEP_CONFLICT')
   seen.append(msgref(r))
  require(sortset(seen)==reqrefs and len(reqrefs)==len(op.required),'REVIEW_REQUIRED')
  a=self._verified(op.authorization,'Authorization','U')
  require(msgref(op.authorization)==authref and a['ctx']==op.ctx and a['verdict']=='APPROVE' and a['purpose']=='EXECUTE' and a['review_refs']==reqrefs,'AUTH_DENY')
  ad=sortset(self.basedeps(op)+self.issuerdeps(['U']+(['V'] if op.required else [])))
  require(op.authorization['body']['deps']==ad,'DEP_CONFLICT')
  require(self.idents['U'].name not in [r['protected']['issuer'] for r in op.reviews],'SUBJECT_SEPARATION')
 def challenge(self,op):
  with self.lock:
   require(op.permit is not None,'MISSING_PERMIT')
   pref=msgref(op.permit);rid=self.newid()
   rq=self.idents['H'].sign(self.profile,'ChallengeRequest',self.scope,
      {'purpose':'COMMIT','operation_id':op.action['operation_id'],'permit_ref':pref,'action_hash':op.ctx['action_hash'],'attempt_id':rid},
      refs=[pref],deps=self.issuerdeps(['H']),aud=[self.idents['X'].name],at=self.now,iid=self.newid(),ttl=30)
   self._verified(rq,'ChallengeRequest','H')
   ch=self.idents['X'].sign(self.profile,'Challenge',self.scope,
      {'purpose':'COMMIT','operation_id':op.action['operation_id'],'permit_ref':pref,'action_hash':op.ctx['action_hash'],
       'holder':op.action['holder'],'holder_kid':op.action['holder_kid'],
       'session_id':self.newid(),'nonce':digest(['nonce-v1',rid]),'request_ref':msgref(rq)},
      refs=[pref,msgref(rq)],deps=self.issuerdeps(['H','X']),aud=[self.idents['H'].name],at=self.now,iid=self.newid(),ttl=30)
   self._verified(ch,'Challenge','X');op.challenge_request=rq;op.challenge=ch;return ch
 def make_proof(self,op):
  with self.lock:
   require(op.challenge is not None,'MISSING_CHALLENGE')
   ch=op.challenge['body']['payload'];pref=msgref(op.permit);cref=msgref(op.challenge)
   proof=self.idents['H'].sign(self.profile,'CommitProof',self.scope,
     {'ctx':op.ctx,'permit_ref':pref,'challenge_ref':cref,'session_id':ch['session_id'],'nonce':ch['nonce'],
      'attempt_id':op.challenge_request['body']['payload']['attempt_id']},
     refs=[pref,cref],deps=self.issuerdeps(['H']),aud=[self.idents['X'].name],at=self.now,iid=self.newid())
   self._verified(proof,'CommitProof','H');return proof
 def commit(self,op,proof=None):
  with self.lock:
   proof=proof or self.make_proof(op)
   p=self._verified(proof,'CommitProof','H')
   pref=msgref(op.permit) if op.permit else None
   require(not op.nonce_consumed,'REPLAY')
   require(op.challenge is not None and op.challenge_request is not None,'MISSING_CHALLENGE')
   ch=self._verified(op.challenge,'Challenge','X')
   qr=self._verified(op.challenge_request,'ChallengeRequest','H')
   self._verified(op.permit,'Permit','G')
   require(p['ctx']==op.ctx and p['permit_ref']==pref and p['challenge_ref']==msgref(op.challenge)
           and p['session_id']==ch['session_id'] and p['nonce']==ch['nonce']
           and p['attempt_id']==qr['attempt_id'],'BINDING')
   require(tuple(self.fulldeps(op))==op.snap,'STALE')
   pp=op.permit['body']['payload'];require(pp['ctx']==op.ctx and pp['max_uses']=='1' and int(pp['dispatch_before'])>self.now,'PERMIT')
   self._check_authorization_chain(op,pp['review_refs'],pp['authorization_ref'])
   require(op.permit['body']['deps']==list(op.snap),'DEP_CONFLICT')
   self._guard(op)
   # Single lock stands for the *abstract* W linearization, not durable DB atomicity.
   op.nonce_consumed=True;op.proof=proof;op.status='ACCEPTED';op.reservation=True
   self.reserved+=1;self.intent_accepted.add(op.intent);self.sequence+=1
   commit_record={'version':'2.6','profile':self.profile,'kind':'COMMIT','scope':self.scope,
      'value':{'ctx':op.ctx,'action':op.action,'permit_ref':pref,'proof_ref':msgref(proof),
               'authorization_ref':pp['authorization_ref'],'review_refs':pp['review_refs'],
               'accept_seq':str(self.sequence),'accepted_at':str(self.now),
               'reference_slice_warning':'NOT_FULL_COMMIT_WITNESS'}}
   a=self.idents['X'].sign(self.profile,'Acceptance',self.scope,
       {'ctx':op.ctx,'permit_ref':pref,'proof_ref':msgref(proof),'authorization_ref':pp['authorization_ref'],
        'review_refs':pp['review_refs'],'accept_seq':str(self.sequence),'accepted_at':str(self.now),
        'commit_record_ref':rec_ref(commit_record),'dispatch_before':pp['dispatch_before']},
       refs=sortset([pref,msgref(proof),pp['authorization_ref']]+pp['review_refs']),
       deps=self.issuerdeps(['X']),aud=[self.idents[a].name for a in ('H','G','U')],at=self.now,iid=self.newid())
   self._verified(a,'Acceptance','X');op.acceptance=a;return a
 def claim(self,op):
  with self.lock:
   require(op.status=='ACCEPTED' and op.calls==0,'NO_REDISPATCH')
   require(tuple(self.fulldeps(op))==op.snap,'STALE')
   require(op.reservation and self.reserved>=1,'RESERVATION')
   require(self.now<int(op.permit['body']['payload']['dispatch_before']),'EXPIRED')
   op.dispatch_attempt=self.newid();op.calls=1;op.status='EFFECT_UNKNOWN'
   return op.dispatch_attempt
 def cancel_pending(self,op):
  with self.lock:
   require(op.status=='ACCEPTED' and op.calls==0 and op.reservation,'CANCEL_FORBIDDEN')
   self.reserved-=1;op.reservation=False;op.status='FAILED_CONFIRMED'
 def tool_fact(self,op,outcome='SUCCEEDED',effect_id=None):
  require(op.calls==1 and op.dispatch_attempt,'NO_DISPATCH')
  key=(op.action['operation_id'],op.dispatch_attempt)
  if key in self.tool_facts:
   return copy.deepcopy(self.tool_facts[key])
  if outcome=='SUCCEEDED':effect_id=effect_id or ('effect-'+op.action['operation_id'][:12]);late=False
  else:require(outcome=='FAILED_CONFIRMED','OUTCOME');effect_id='';late=True
  self.tool_final_seq+=1
  fact={'ledger_id':self.tool_ledger_id,'operation_id':op.action['operation_id'],
     'action_hash':op.ctx['action_hash'],'dispatch_attempt':op.dispatch_attempt,'tool':op.action['tool'],
     'tool_version':'1','destination':op.action['destination'],'outcome':outcome,
     'effect_id':effect_id,'no_late_effect':late,'final_seq':str(self.tool_final_seq),
     'finalized_at':str(self.now)}
  self.tool_facts[key]=copy.deepcopy(fact)
  return fact
 def certify_fact(self,op,fact,signer=None):
  signer=signer or self.tool
  value={**copy.deepcopy(fact),'method':'tool-final-v2','iat':str(self.now),'exp':str(self.now+900),
         'attestation':{'issuer':signer.name,'kid':signer.kid,'sig':''}}
  record={'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':self.scope,'value':value}
  unsigned={k:v for k,v in value.items() if k!='attestation'}
  message=canonical(['ZJJ-TOOL-FINAL-v2','2.6',self.profile,self.scope,unsigned,{'issuer':signer.name,'kid':signer.kid}])
  value['attestation']['sig']=b64(signer.key.sign(message))
  return record
 def receive_final(self,op,record):
  with self.lock:
   require(self.continuity,'LEDGER_UNKNOWN')
   require(op.calls==1 and op.status in ('EFFECT_UNKNOWN','SUCCEEDED','FAILED_CONFIRMED','HALTED'),'NO_DISPATCH')
   require(record['version']=='2.6' and record['profile']==self.profile and record['scope']==self.scope and record['kind']=='TOOL_FINAL','WRONG_SCOPE')
   v=record['value'];assert_f={'ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version','destination','outcome','effect_id','no_late_effect','final_seq','finalized_at'}
   require(set(v)==assert_f|{'method','iat','exp','attestation'} and v['method']=='tool-final-v2','FIELDS')
   a=v['attestation'];require(set(a)=={'issuer','kid','sig'},'FIELDS')
   # Invalid packets do NOT HALT, even if they claim contradictory facts.
   require(a['issuer']==self.tool.name and a['kid']==self.tool.kid,'TOOL_TRUST')
   require(int(v['iat'])<=self.now<int(v['exp']) and 0<int(v['exp'])-int(v['iat'])<=900,'EXPIRED')
   require(int(v['finalized_at'])<=int(v['iat']),'TIME_BINDING')
   unsigned={k:x for k,x in v.items() if k!='attestation'}
   sig_bytes=canonical(['ZJJ-TOOL-FINAL-v2','2.6',self.profile,self.scope,unsigned,{'issuer':a['issuer'],'kid':a['kid']}])
   strict_verify(self.tool.pub,raw(a['sig'],64),sig_bytes)
   f={k:v[k] for k in assert_f}
   required={'ledger_id':self.tool_ledger_id,'operation_id':op.action['operation_id'],'action_hash':op.ctx['action_hash'],
     'dispatch_attempt':op.dispatch_attempt,'tool':op.action['tool'],'tool_version':op.action['tool_version'],
     'destination':op.action['destination']}
   require(all(f[k]==x for k,x in required.items()),'TOOL_BINDING')
   require((v['outcome']=='SUCCEEDED' and bool(v['effect_id']) and v['no_late_effect'] is False)
           or (v['outcome']=='FAILED_CONFIRMED' and v['effect_id']=='' and v['no_late_effect'] is True),'OUTCOME')
   fact_id=digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',self.profile,self.scope,f])
   if op.finalfact is not None:
    if op.finalfact!=f:
     op.status='HALTED';raise ProtocolError('TRUSTED_CONTRADICTION')
    op.receipts.append(rec_ref(record));return 'EXISTING'
   require(fact_id not in self.final_sequences,'DUPLICATE_FINAL_FACT')
   require((self.tool_ledger_id,f['final_seq']) not in self.seq_index,'DUPLICATE_FINAL_SEQ')
   if f['outcome']=='SUCCEEDED':
    require((self.tool_ledger_id,f['effect_id']) not in self.effect_ids,'DUPLICATE_EFFECT')
    self.effect_ids.add((self.tool_ledger_id,f['effect_id']))
   self.seq_index.add((self.tool_ledger_id,f['final_seq']));self.final_sequences.add(fact_id);op.finalfact=f;op.finalfact_id=fact_id;op.receipts.append(rec_ref(record))
   op.settlements+=1;require(op.reservation,'RESERVATION');self.reserved-=1;op.reservation=False
   if f['outcome']=='SUCCEEDED':self.spent+=1
   op.status=f['outcome'];return 'SETTLED'
 def rotate_tool(self,newseed,continuity_verified=True):
  with self.lock:
   self.continuity=continuity_verified
   if continuity_verified:
    self.tool=Identity('fixture-t',newseed,roles=('TOOL',),purposes=())
    self.tool_epoch+=1
 def status_query(self,op):
  with self.lock:
   # Fresh challenge for STATUS, independent of historical COMMIT/PERMIT TTL.
   rid=self.newid();opid=op.action['operation_id']
   req=self.idents['H'].sign(self.profile,'ChallengeRequest',self.scope,
      {'purpose':'STATUS','operation_id':opid,'permit_ref':'','action_hash':'','attempt_id':rid},
      refs=[],deps=self.issuerdeps(['H']),aud=[self.idents['X'].name],iid=self.newid(),at=self.now)
   self._verified(req,'ChallengeRequest','H')
   ch=self.idents['X'].sign(self.profile,'Challenge',self.scope,
      {'purpose':'STATUS','operation_id':opid,'permit_ref':'','action_hash':'',
       'holder':self.idents['H'].name,'holder_kid':self.idents['H'].kid,'session_id':self.newid(),
       'nonce':digest(['status-nonce',rid]),'request_ref':msgref(req)},
      refs=[msgref(req)],deps=self.issuerdeps(['H','X']),aud=[self.idents['H'].name],iid=self.newid(),at=self.now)
   self._verified(ch,'Challenge','X')
   query=self.idents['H'].sign(self.profile,'StatusQuery',self.scope,
     {'operation_id':opid,'challenge_ref':msgref(ch),'session_id':ch['body']['payload']['session_id'],
      'nonce':ch['body']['payload']['nonce'],'attempt_id':rid},
     refs=[msgref(ch)],deps=self.issuerdeps(['H']),aud=[self.idents['X'].name],iid=self.newid(),at=self.now)
   self._verified(query,'StatusQuery','H')
   return op.status
