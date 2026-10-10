"""Phase 11 experimental strict IND/MED authority, dispatch and tool-final integration.

Single SQLite W authority serializes C control mutations, acceptance, dispatch and
settlement. An independent durable tool SQLite simulator supplies immutable facts.
The separate databases DO NOT model a distributed atomic commit or real equipment.
"""
from __future__ import annotations
import json, os, sqlite3
from research.phase8.scene_authority import (SceneAuthority, PROFILES, ROLES, PURPOSES, DEST,
                                              _rec, _json, _clone)
from research.phase6.trusted_final import (Controller, ToolLedger, verify_certificate,
                                           final_fact, final_fact_id, final_sign_bytes, BASE_FIELDS)
from .trusted_clock import prepare_table,checked_clock,consume_clock
from research.reference_executor.wire import (require, ProtocolError, canonical, b64, raw, keyid,
                                                strict_verify, rec_ref, action_hash, sortset, digest,
                                                is_id, number, good_point)


def interval(now_lo, now_hi, starts, ends):
    """Treat both endpoints as possible trusted times; never use local wall clock."""
    require(all(type(x) is int and x>=0 for x in (now_lo,now_hi,starts,ends)) and now_lo<=now_hi,'TIME_INTERVAL')
    if now_lo>=ends or now_hi<starts:return 'EXPIRED'
    if now_lo<starts or now_hi>=ends:return 'UNKNOWN_TIME'
    return 'VALID'


class SceneR2W(SceneAuthority):
    """No API that can dispatch with a caller-supplied boolean witness."""
    def __init__(self,db_path,profile,**kw):
        super().__init__(db_path,profile,**kw)
        with self.db() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS enroll_pending(
                enrollment_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE,
                actor TEXT NOT NULL,kid TEXT NOT NULL,tuple_blob TEXT NOT NULL,
                created_at INTEGER NOT NULL,expires INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS c_root_epoch(
                id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL);
              INSERT OR IGNORE INTO c_root_epoch VALUES(1,1);
              CREATE TABLE IF NOT EXISTS verified_enrollment(
                kid TEXT PRIMARY KEY, claim TEXT NOT NULL, proof TEXT NOT NULL,grant TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS r2_tool_trust(
                id INTEGER PRIMARY KEY CHECK(id=1), cert TEXT NOT NULL,
                revision INTEGER NOT NULL,epoch INTEGER NOT NULL,origin TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS r2_dispatch(
                operation_id TEXT PRIMARY KEY, attempt TEXT NOT NULL UNIQUE,ledger_id TEXT NOT NULL,
                scope TEXT NOT NULL,hash TEXT NOT NULL, trust_ref TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS r2_settled(
                operation_id TEXT PRIMARY KEY, fact_id TEXT NOT NULL,fact TEXT NOT NULL,
                first_record TEXT NOT NULL, ledger_id TEXT NOT NULL,
                UNIQUE(ledger_id,fact_id));
              CREATE TABLE IF NOT EXISTS r2_seen(
                record_ref TEXT PRIMARY KEY,operation_id TEXT NOT NULL,record TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS r2_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,
                operation_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
        with self.db() as c:prepare_table(c)
        # Recreate derived fixture state only by explicit caller-controlled enrolment.

    def begin_enrollment(self,alias,*,now=10,not_before=10,not_after=2000):
        """C issues one-use nonce and an exact CORE-19-style tuple (lab authority)."""
        actor=self.actors[alias]
        require(0<=now<=not_before<not_after and not_after-not_before<=31536000,'KEY_LIFETIME')
        with self.tx() as c:
            gen=c.execute('SELECT generation FROM c_root_epoch WHERE id=1').fetchone()['generation']
            tup={'scope':self.scope,'subject':actor.name,'public_key':b64(actor.pub),
                 'kid':actor.kid,'purposes':sorted(actor.purposes),
                 'key_not_before':str(not_before),'key_not_after':str(not_after),
                 'root_generation':str(gen)}
            enrollment_id=b64(os.urandom(16));nonce=b64(os.urandom(32))
            c.execute('INSERT INTO enroll_pending VALUES(?,?,?,?,?,?,?,0)',
                      (enrollment_id,nonce,actor.name,actor.kid,_json(tup),now,now+60))
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                      ('ENROLL_CHALLENGE',actor.name,_json({'enrollment_id':enrollment_id,'nonce':nonce,
                                                          'tuple_hash':digest(tup),'expires':str(now+60)})))
        return {'tuple':tup,'enrollment_id':enrollment_id,'nonce':nonce,'pending_expires':str(now+60)}

    def enroll_actor(self,alias,*,now=10,exp=2000):
        """Convenience for deterministic fixture bootstrap; proof is real Ed25519."""
        pending=self.begin_enrollment(alias,now=now,not_before=now,not_after=exp)
        from research.conformance39.enrollment_lab import EnrollmentLab
        proof=EnrollmentLab.possession(self.actors[alias],pending,iat=now+1,exp=now+40)
        return self.complete_enrollment(alias,proof,now=now+2)

    def complete_enrollment(self,alias,proof,*,now=12):
        actor=self.actors[alias]
        require(type(proof) is dict and set(proof)=={'tuple','enrollment_id','nonce','iat','exp','signature'},'ENROLL_FIELDS')
        raw(proof['enrollment_id'],16);raw(proof['nonce'],32);sig=raw(proof['signature'],64)
        require(number(proof['iat']) and number(proof['exp']),'PROOF_TIME')
        with self.tx() as c:
            pending=c.execute('SELECT * FROM enroll_pending WHERE enrollment_id=?',(proof['enrollment_id'],)).fetchone()
            require(pending is not None and pending['used']==0,'ENROLL_REPLAY')
            tup=json.loads(pending['tuple_blob'])
            require(proof['nonce']==pending['nonce'],'NONCE_BINDING')
            require(proof['tuple']==tup,'TUPLE_BINDING')
            require(tup['subject']==actor.name and tup['kid']==actor.kid and
                    tup['public_key']==b64(actor.pub) and tup['scope']==self.scope,'ENROLL_BINDING')
            require(int(tup['root_generation'])==c.execute('SELECT generation FROM c_root_epoch WHERE id=1').fetchone()['generation'],'ROOT_GENERATION')
            require(pending['created_at']<=int(proof['iat'])<int(proof['exp']) and
                    int(proof['exp'])-int(proof['iat'])<=60 and int(proof['exp'])<=pending['expires']
                    and int(proof['iat'])<=now<int(proof['exp']),'PROOF_TIME')
            require(int(tup['key_not_before'])<=now<int(tup['key_not_after']) and good_point(actor.pub),'ENROLL_TIME')
            strict_verify(actor.pub,sig,canonical(['ZJJ-ENROLL-v1','2.6',tup,proof['enrollment_id'],
                                                  proof['nonce'],proof['iat'],proof['exp']]))
            require(c.execute('SELECT 1 FROM verified_enrollment WHERE kid=?',(actor.kid,)).fetchone() is None,'ENROLL_REPLAY')
            enr=digest(['ZJJ-ENROLL-RECORD-v1','2.6',tup,proof['enrollment_id'],
                        proof['nonce'],proof['iat'],proof['exp'],proof['signature']])
            grant=_rec(self.profile,'KEY_GRANT',self.scope,
                 {'subject':actor.name,'public_key':b64(actor.pub),'kid':actor.kid,'epoch':'1',
                  'purposes':tup['purposes'],'root_generation':tup['root_generation'],
                  'enrollment_ref':enr,'iat':tup['key_not_before'],'exp':tup['key_not_after']})
            c.execute('INSERT INTO verified_enrollment VALUES(?,?,?,?)',
                      (actor.kid,_json(tup),_json(proof),_json(grant)))
            c.execute('UPDATE enroll_pending SET used=1 WHERE enrollment_id=?',(proof['enrollment_id'],))
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                      ('ENROLL',actor.name,_json({'enrollment_id':proof['enrollment_id'],
                                               'nonce':proof['nonce'],'kid':actor.kid,'grant_ref':rec_ref(grant)})))
        return grant

    def rotate_root_epoch(self):
        """Local C fixture rotates generation, invalidating all pending PoP."""
        with self.tx() as c:
            c.execute('UPDATE c_root_epoch SET generation=generation+1 WHERE id=1')
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                      ('ROOT_ROTATE','-',_json({'new_generation':str(c.execute('SELECT generation FROM c_root_epoch WHERE id=1').fetchone()['generation'])})))

    def grant(self,alias,roles=None):
        actor=self.actors[alias]
        with self.db() as c:
            row=c.execute('SELECT grant FROM verified_enrollment WHERE kid=?',(actor.kid,)).fetchone()
        require(row is not None,'POP_REQUIRED')
        grant=json.loads(row['grant']);self.publish('KEY',[actor.kid],grant)
        tool='line-sort-sim' if self.profile=='IND-DEMO-1' else 'med-order-sim'
        dest=sortset(list(DEST.values()) if self.profile=='IND-DEMO-1' else ['med-demo-ledger'])
        for role in roles or [ROLES[self.profile][alias]]:
            record=_rec(self.profile,'ROLE_GRANT',self.scope,
              {'subject':actor.name,'role':role,'epoch':'1','scope_set':[self.scope],
               'tool_set':[tool],'destination_set':dest,
               'constraints':self._role_constraints(alias,role),'iat':'1','exp':'2000'})
            self.publish('ROLE',self.role_key(actor,role),record)

    def publish_cert(self,certificate):
        claim=certificate.get('claim',{}) if type(certificate) is dict else {}
        if claim.get('namespace')=='KEY' and claim.get('active') is True:
            rec=claim.get('record',{})
            kid=rec.get('value',{}).get('kid')
            with self.db() as c:
                row=c.execute('SELECT grant FROM verified_enrollment WHERE kid=?',(kid,)).fetchone()
            require(row is not None and json.loads(row['grant'])==rec,'POP_REQUIRED')
        return super().publish_cert(certificate)

    def _credential(self,c,alias,role,purpose,action=None):
        k,r=super()._credential(c,alias,role,purpose,action)
        # Current local-check capability: explicit expiry plus PoP match; parent
        # verifies current role/constraints/scope, but not certificate lifecycle.
        actor=self.actors[alias]
        enr=c.execute('SELECT grant FROM verified_enrollment WHERE kid=?',(actor.kid,)).fetchone()
        require(enr is not None and k['record']==json.loads(enr['grant']),'POP_REQUIRED')
        for rec in (k['record'],r['record']):
            v=rec['value'];require(int(v['iat'])<=106<int(v['exp']),'CREDENTIAL_EXPIRED')
        return k,r

    def activate_tool(self,cert,ledger:ToolLedger,*,now=107):
        rec=verify_certificate(cert,self.root_public,self.profile)
        v=rec['value'];cl=cert['claim']
        require(rec['scope']==self.scope and v['tool']==('line-sort-sim' if self.profile=='IND-DEMO-1' else 'med-order-sim')
                and v['tool_version']=='1' and v['ledger_id']==ledger.ledger_id
                and ledger.profile==self.profile,'TRUST_BINDING')
        require(v['destination'] in (list(DEST.values()) if self.profile=='IND-DEMO-1' else ['med-demo-ledger']),'TRUST_BINDING')
        require(interval(now,now,int(v['iat']),int(v['exp']))=='VALID','TRUST_EXPIRED')
        require(cl['ledger_origin']==ledger.origin and cl['ledger_head']==ledger.head(),'CONTINUITY_UNKNOWN')
        with self.tx() as c:
            old=c.execute('SELECT * FROM r2_tool_trust WHERE id=1').fetchone()
            if old:
                previous=verify_certificate(json.loads(old['cert']),self.root_public,self.profile)['value']
                require(v['ledger_id']==previous['ledger_id'] and v['destination']==previous['destination']
                        and old['origin']==ledger.origin,'CONTINUITY_UNKNOWN')
                require(int(v['epoch'])>old['epoch'] and int(cl['revision'])>old['revision'],'EPOCH_REPLAY')
                facts=ledger.all_facts()
                for saved in c.execute('SELECT fact FROM r2_settled WHERE ledger_id=?',(v['ledger_id'],)):
                    require(json.loads(saved['fact']) in facts,'CONTINUITY_UNKNOWN')
                # Preserve proofs of finalized operations, even if not settled yet.
                for d in c.execute('SELECT operation_id,attempt FROM r2_dispatch'):
                    f=ledger.lookup(d['operation_id'],d['attempt'])
                    # A dispatched operation might not yet have completed. It
                    # must not be invented as FAILED_CONFIRMED by a missing row.
                    if f is not None:require(f['ledger_id']==v['ledger_id'],'CONTINUITY_UNKNOWN')
            c.execute('INSERT INTO r2_tool_trust VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET cert=excluded.cert,revision=excluded.revision,epoch=excluded.epoch,origin=excluded.origin',
                      (_json(cert),int(cl['revision']),int(v['epoch']),ledger.origin))
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                      ('TOOL_TRUST','-',_json({'trust_ref':rec_ref(rec),'head':ledger.head(),'epoch':v['epoch']})))
        return rec_ref(rec)

    def _trust(self,c,lo,hi):
        r=c.execute('SELECT cert FROM r2_tool_trust WHERE id=1').fetchone();require(r is not None,'TRUST_MISSING')
        rec=verify_certificate(json.loads(r['cert']),self.root_public,self.profile)
        v=rec['value'];state=interval(lo,hi,int(v['iat']),int(v['exp']))
        require(state=='VALID',state)
        return rec

    @staticmethod
    def _required_aliases(action,profile):
        out=['H','E','G','X','U']
        if profile=='MED-DEMO-1' or action['payload']['route']=='INSPECT':out.append('V')
        return out

    def _reconstruct(self,c,freeze):
        """W reconstruction uses archived action plus current registry, never signed G deps."""
        a=freeze['action'];prefix=self.scope_key();task=freeze['task_id']
        key=freeze['commit_record']['value']['scene_before']['key']
        ns=PROFILES[self.profile][2]
        deps=[self._depend(c,'POLICY',prefix),self._depend(c,'TASK',prefix+[task])]
        # The scene and behavior have been changed by W itself at Acceptance;
        # their before-images are checked against archived signed COMMIT below.
        for alias in self._required_aliases(a,self.profile):
            actor=self.actors[alias]
            deps.extend([self._depend(c,'KEY',[actor.kid]),
                         self._depend(c,'ROLE',self.role_key(actor,ROLES[self.profile][alias]))])
        for alias in ('H','G','X','U')+(('V',) if 'V' in self._required_aliases(a,self.profile) else ()):
            actor=self.actors[alias]
            deps.append(self._depend(c,'ROLE',self.role_key(actor,'READER')))
        before_scene=freeze['commit_record']['value']['scene_before']
        before_behavior=freeze['commit_record']['value']['behavior_before']
        deps.append({k:before_scene[k] for k in ('namespace','key','revision','ref')})
        deps.append({'namespace':'BEHAVIOR',**{k:before_behavior[k] for k in ('key','revision','ref')}})
        rebuilt=sortset({(x['namespace'],tuple(x['key'])):x for x in deps}.values())
        require(rebuilt==freeze['pre_deps'] and rebuilt==freeze['commit_record']['value']['checked_deps'],'DEP_CONFLICT')
        scene=self.current(c,ns,key)
        # Non-wire transitive references are checked directly, not serialized
        # as unsupported Dep namespaces in official IND/MED envelopes.
        sv=scene['record']['value'];policy=self.current(c,'POLICY',prefix)['record']['value']
        if self.profile=='IND-DEMO-1':
            identity=self.current(c,'IDENTITY',prefix+[a['payload']['unit_id']])
            require(rec_ref(identity['record'])==sv['unit_ref'],'IDENTITY_BINDING')
            package=self.current(c,'PACKAGE',prefix)
            require(package['ref']==policy['decision_package_ref'],'PACKAGE_BINDING')
        else:
            identity=self.current(c,'IDENTITY',prefix+[a['payload']['synthetic_patient_id'],a['payload']['encounter_id']])
            require(rec_ref(identity['record'])==sv['encounter_ref'],'IDENTITY_BINDING')
        require(scene['ref']==freeze['scene_after_ref'] and scene['revision']==freeze['scene_after_revision']
                and scene['record']['value']['operation_id']==a['operation_id'],'STALE_SCENE')
        br=self.current(c,'BEHAVIOR',prefix+[a['principal']]);brv=br['record']['value']
        require(int(brv['accepted_count'])>=int(freeze['behavior_after']['row']['accepted_count'])
                and a['operation_id'] in brv['inflight'],'BEHAVIOR_INTEGRITY')
        for alias in self._required_aliases(a,self.profile):
            self._credential(c,alias,ROLES[self.profile][alias],
                             {'H':'CommitProof','G':'Permit','X':'Acceptance','U':'Authorization',
                              'V':'Review','E':'SOURCE'}[alias],a)
        policy=self.current(c,'POLICY',prefix)['record']['value']
        for alias in ('H','G','X','U')+(('V',) if 'V' in self._required_aliases(a,self.profile) else ()):
            self._read_permission(c,alias,a,policy)
        ev=self.current(c,'EVIDENCE',key)['record']
        require(rec_ref(ev)==scene['record']['value']['evidence_ref'],'STALE_EVIDENCE')
        require(c.execute('SELECT operation_id FROM flight WHERE task_id=?',(task,)).fetchone()['operation_id']==a['operation_id'],'TASK_BUSY')
        res=c.execute('SELECT * FROM resource WHERE destination=?',(a['destination'],)).fetchone()
        require(res is not None and res['reserved']>0 and res['reserved']+res['spent']<=res['capacity'],'RESOURCE_LIMIT')
        return policy,ev

    def _validity(self,c,freeze,lo,hi):
        if lo>=int(freeze['commit_record']['value']['dispatch_before']):return 'EXPIRED'
        if hi>=int(freeze['commit_record']['value']['dispatch_before']):return 'UNKNOWN_TIME'
        action=freeze['action'];prefix=self.scope_key()
        for ns,key in (('POLICY',prefix),('TASK',prefix+[freeze['task_id']])):
            row=self.current(c,ns,key);v=row['record']['value']
            state=interval(lo,hi,int(v['iat']),int(v['exp']))
            if state!='VALID':return state
        for alias in self._required_aliases(action,self.profile):
            actor=self.actors[alias]
            for ns,k in (('KEY',[actor.kid]),('ROLE',self.role_key(actor,ROLES[self.profile][alias]))):
                v=self.current(c,ns,k)['record']['value'];state=interval(lo,hi,int(v['iat']),int(v['exp']))
                if state!='VALID':return state
        for alias in ('H','G','X','U')+(('V',) if 'V' in self._required_aliases(action,self.profile) else ()):
            actor=self.actors[alias]
            rv=self.current(c,'ROLE',self.role_key(actor,'READER'))['record']['value']
            state=interval(lo,hi,int(rv['iat']),int(rv['exp']))
            if state!='VALID':return state
        key=freeze['commit_record']['value']['scene_before']['key']
        ev=self.current(c,'EVIDENCE',key)['record']['value']['attestation']
        state=interval(lo,hi,int(ev['iat']),int(ev['exp']))
        return state

    def _cancel(self,c,row,freeze,reason):
        # Never cancel an effect that has been claimed. Keep stable intent tombstone.
        require(row['state']=='ACCEPTED' and row['calls']==0,'CANCEL_TOO_LATE')
        a=freeze['action'];oid=a['operation_id']
        resource=c.execute('UPDATE resource SET reserved=reserved-1,revision=revision+1 WHERE destination=? AND reserved>=1',(a['destination'],))
        require(resource.rowcount==1,'RESOURCE_LIMIT')
        require(c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(freeze['task_id'],oid)).rowcount==1,'TASK_BUSY')
        br=c.execute('SELECT * FROM behavior WHERE principal=?',(a['principal'],)).fetchone()
        require(br is not None,'BEHAVIOR_INTEGRITY')
        inf=json.loads(br['inflight']);require(oid in inf,'BEHAVIOR_INTEGRITY')
        new=sortset([x for x in inf if x!=oid]);c.execute('UPDATE behavior SET inflight=?,revision=revision+1 WHERE principal=?',(_json(new),a['principal']))
        beh=self.current(c,'BEHAVIOR',self.scope_key()+[a['principal']]);value=_clone(beh['record']['value']);value['inflight']=new
        self._behavior_update(c,a['principal'],beh['revision'],value)
        c.execute("UPDATE accept_intent SET state='CANCELLED' WHERE operation_id=? AND calls=0",(oid,))
        c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',('CANCEL',oid,_json({'reason':reason})))
        return {'status':'CANCELLED','reason':reason,'calls':0}

    def claim_r2(self,operation_id,attempt,*,clock):
        raw(attempt,16)
        with self.tx() as c:
            row=c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None,'NOT_ACCEPTED')
            if row['calls']:
                require(row['attempt']==attempt,'NO_REDISPATCH')
                return {'status':'EXISTING','attempt':attempt}
            require(row['state']=='ACCEPTED','NO_DISPATCH')
            lo,hi,clock_seq=checked_clock(c,clock,self.root_public,self.profile,self.scope,operation_id,'DISPATCH')
            freeze=json.loads(row['accepted_blob']);act=freeze['action']
            require(act['operation_id']==operation_id,'BINDING')
            try:
                trust=self._trust(c,lo,hi)
            except ProtocolError as e:
                if e.code=='EXPIRED':
                    result=self._cancel(c,row,freeze,'TRUST_EXPIRED');consume_clock(c,clock_seq);return result
                raise
            tv=trust['value'];require(act['tool']==tv['tool'] and act['tool_version']==tv['tool_version']
                and act['destination']==tv['destination'],'TOOL_BINDING')
            try:
                self._reconstruct(c,freeze)
                state=self._validity(c,freeze,lo,hi)
            except ProtocolError as e:
                if e.code in ('REVOKED','STALE','STALE_EVIDENCE','STALE_SCENE','CREDENTIAL_EXPIRED','PACKAGE_BINDING','IDENTITY_BINDING'):
                    result=self._cancel(c,row,freeze,e.code);consume_clock(c,clock_seq);return result
                raise
            if state=='EXPIRED':
                result=self._cancel(c,row,freeze,'EXPIRED');consume_clock(c,clock_seq);return result
            require(state=='VALID',state)
            updated=c.execute("UPDATE accept_intent SET calls=1,attempt=?,state='EFFECT_UNKNOWN' WHERE operation_id=? AND calls=0 AND state='ACCEPTED'",(attempt,operation_id))
            require(updated.rowcount==1,'NO_REDISPATCH')
            c.execute('INSERT INTO r2_dispatch VALUES(?,?,?,?,?,?)',
                      (operation_id,attempt,tv['ledger_id'],_json(self.scope),action_hash(self.profile,act),rec_ref(trust)))
            consume_clock(c,clock_seq)
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',('DISPATCH',operation_id,_json({'attempt':attempt,'ledger':tv['ledger_id'],'clock':clock})))
        return {'status':'CLAIMED','attempt':attempt}

    def _verify_final(self,c,r,lo,hi,ledger):
        require(type(r) is dict and set(r)=={'version','profile','kind','scope','value'},'FINAL_FIELDS')
        require((r['version'],r['profile'],r['kind'],r['scope'])==('2.6',self.profile,'TOOL_FINAL',self.scope),'FINAL_KIND')
        v=r['value'];require(set(v)==BASE_FIELDS|{'attestation'} and v['method']=='tool-final-v2','FINAL_FIELDS')
        a=v['attestation'];require(type(a) is dict and set(a)=={'issuer','kid','sig'},'FINAL_FIELDS')
        require(v['outcome'] in ('SUCCEEDED','FAILED_CONFIRMED') and
            ((v['outcome']=='SUCCEEDED' and is_id(v['effect_id']) and v['no_late_effect'] is False) or
             (v['outcome']=='FAILED_CONFIRMED' and v['effect_id']=='' and v['no_late_effect'] is True)),'FINAL_OUTCOME')
        require(number(v['iat']) and number(v['exp']) and number(v['finalized_at']) and number(v['final_seq'],True),'FINAL_TIME')
        require(int(v['iat'])>=int(v['finalized_at']) and 0<int(v['exp'])-int(v['iat'])<=900,'FINAL_TIME')
        trust=self._trust(c,lo,hi);tv=trust['value']
        require(interval(lo,hi,int(v['iat']),int(v['exp']))=='VALID','FINAL_EXPIRED')
        require(int(v['exp'])<=int(tv['exp']) and a['issuer']==tv['issuer'] and a['kid']==tv['kid'],'FINAL_SIGNER')
        require(v['ledger_id']==tv['ledger_id']==ledger.ledger_id and ledger.profile==self.profile
                and ledger.origin==c.execute('SELECT origin FROM r2_tool_trust WHERE id=1').fetchone()[0], 'LEDGER_MISMATCH')
        require(all(v[k]==tv[k] for k in ('tool','tool_version','destination')),'FINAL_BINDING')
        strict_verify(raw(tv['public_key'],32),raw(a['sig'],64),final_sign_bytes(r))
        op=v['operation_id'];w=c.execute('SELECT * FROM r2_dispatch WHERE operation_id=?',(op,)).fetchone()
        row=c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(op,)).fetchone()
        require(w is not None and row is not None,'DISPATCH_MISSING')
        frozen=json.loads(row['accepted_blob']);act=frozen['action']
        require(w['attempt']==v['dispatch_attempt'] and w['scope']==_json(self.scope)
                and w['hash']==v['action_hash']==action_hash(self.profile,act) and
                w['ledger_id']==v['ledger_id'],'FINAL_BINDING')
        # Signed and bound reattestations are valid cryptographic claims.
        # Check the independent tool ledger before *first* settlement. A
        # contradictory later signed claim HALTs W without reversing the first.
        return row,frozen,final_fact_id(r)

    def settle_r2(self,record,ledger,*,clock=None):
        with self.tx() as c:
            rr=rec_ref(record)
            old=c.execute('SELECT * FROM r2_seen WHERE record_ref=?',(rr,)).fetchone()
            if old:
                require(json.loads(old['record'])==record,'RECORD_COLLISION')
                settle=c.execute('SELECT fact_id FROM r2_settled WHERE operation_id=?',(old['operation_id'],)).fetchone()
                require(settle is not None,'FINAL_STATE')
                return {'status':c.execute('SELECT state FROM accept_intent WHERE operation_id=?',(old['operation_id'],)).fetchone()[0],
                        'fact_id':settle['fact_id'],'idempotent':True,'historical':True}
            op_id=record['value']['operation_id']
            lo,hi,clock_seq=checked_clock(c,clock,self.root_public,self.profile,self.scope,op_id,'SETTLE')
            row,freeze,fid=self._verify_final(c,record,lo,hi,ledger)
            v=record['value'];op=v['operation_id']
            prior=c.execute('SELECT * FROM r2_settled WHERE operation_id=?',(op,)).fetchone()
            if prior:
                if prior['fact_id']!=fid or json.loads(prior['fact'])!=final_fact(record):
                    c.execute("UPDATE accept_intent SET state='HALTED' WHERE operation_id=?",(op,))
                    c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                              ('CONTRADICTION',op,_json({'old':prior['fact_id'],'new':fid})))
                    consume_clock(c,clock_seq)
                    return {'status':'HALTED','fact_id':prior['fact_id'],'conflict':True}
                c.execute('INSERT INTO r2_seen VALUES(?,?,?)',(rr,op,_json(record)))
                consume_clock(c,clock_seq)
                return {'status':row['state'],'fact_id':fid,'idempotent':True,'historical':False}
            require(row['state']=='EFFECT_UNKNOWN' and row['calls']==1 and row['settlements']==0,'FINAL_STATE')
            original=ledger.lookup(op,v['dispatch_attempt'])
            require(original is not None and original==final_fact(record),'LEDGER_FACT_NOT_FOUND')
            act=freeze['action'];dest=act['destination'];oid=op
            resource=c.execute('UPDATE resource SET reserved=reserved-1, spent=spent+?,revision=revision+1 WHERE destination=? AND reserved>=1',
                               (1 if v['outcome']=='SUCCEEDED' else 0,dest))
            require(resource.rowcount==1,'RESOURCE_LIMIT')
            require(c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(freeze['task_id'],oid)).rowcount==1,'TASK_BUSY')
            nextstate='SUCCEEDED' if v['outcome']=='SUCCEEDED' else 'FAILED_CONFIRMED'
            c.execute('UPDATE accept_intent SET state=?,settlements=1 WHERE operation_id=?',(nextstate,op))
            c.execute('INSERT INTO r2_settled VALUES(?,?,?,?,?)',(op,fid,_json(final_fact(record)),_json(record),v['ledger_id']))
            c.execute('INSERT INTO r2_seen VALUES(?,?,?)',(rr,op,_json(record)))
            consume_clock(c,clock_seq)
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',('SETTLE',op,_json({'fact_id':fid,'result':nextstate,'clock':clock})))
            return {'status':nextstate,'fact_id':fid,'idempotent':False,'historical':False}

    def claim(self,op):
        raise ProtocolError('STRICT_CLOCKED_CLAIM_ONLY')

    def audit_r2(self):
        with self.db() as c:
            return [{'id':x['id'],'kind':x['kind'],'operation_id':x['operation_id'],'payload':json.loads(x['payload'])}
                    for x in c.execute('SELECT * FROM r2_audit ORDER BY id')]
