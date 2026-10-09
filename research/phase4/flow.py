"""PAY-1 v2.6-R2 signed in-memory end-to-end study flow.

Uses the existing full PAY-1 history validator and trusted-grant dependency
calculator. The C/E publication and W transaction substrate are *fixtures*,
NOT production authenticated services. When supplied the actual upstream
schema directory, each constructed record/envelope is additionally validated
against the unmodified JSON Schema Draft 2020-12 contract.
"""
from __future__ import annotations
import copy
from research.reference_executor.engine import ReferenceW, Operation
from research.reference_executor.wire import (Identity, ProtocolError, require, b64, canonical,
    digest, rec_ref, msgref, action_hash, sid, sortset, envelope)
from research.strict_v26.test_pay_history import bundle, case
from research.strict_v26.test_pay_dependencies import setup, ACTORS
from research.strict_v26.pay_history import (verify_pay_authoritative, verify_assessment)
from research.strict_v26.pay_dependencies import (required_pay_deps, verify_claimed_dependencies, TrustedStore)
from research.strict_v26.upstream_schema import UpstreamSchema

PAY_FIELDS={
 'ASSESSMENT':{'action_hash','policy_ref','task_ref','evidence_refs','snapshot_ref','cutoff','feature',
               'selected_cases','support','different','result','method','iat','exp'},
 'BASIS':{'scope','operation_id','action','action_hash','policy_ref','task_ref','evidence_refs',
          'assessment_ref','required_reviews','deps','iat','exp'},
 'COMMIT':{'ctx','action','permit_ref','proof_ref','authorization_ref','review_refs','accept_seq',
           'accepted_at','trusted_time','checked_deps','reservation_plan','reservation_ids',
           'behavior_before','behavior_after','taskflight','dispatch_before',
           'frozen_tool_request','signing_public_key','credential_witnesses'},
}
RES_FIELDS={'reservation_id','key','unit','amount','capacity_before','reserved_before',
            'spent_before','reserved_after','spent_after','revision_before','revision_after'}
BEHAV_FIELDS={'key','revision','ref','row'}
CREDFIELDS={'subject','kid','public_key','key_grant_ref','role','role_grant_ref',
            'key_revision','role_revision','verified_at_seq'}

def check_record_contract(r,kind,scope):
    """Local shape + semantic bindings, NOT a substitute for upstream Schema."""
    require(set(r)=={'version','profile','kind','scope','value'},'RECORD_FIELDS')
    require((r['version'],r['profile'],r['kind'],r['scope'])==('2.6','PAY-1',kind,scope),'OBJECT_KIND')
    require(set(r['value'])==PAY_FIELDS[kind],'RECORD_FIELDS')
    v=r['value']
    if kind=='BASIS':
        require(v['action_hash']==action_hash('PAY-1',v['action']) and
                v['operation_id']==v['action']['operation_id'] and v['scope']==scope,'BINDING')
        require(v['deps']==sortset(v['deps']),'DEP_CONFLICT')
    if kind=='COMMIT':
        require(v['action']==v['frozen_tool_request'],'TOOL_BINDING')
        require(len(v['reservation_plan'])==1 and set(v['reservation_plan'][0])==RES_FIELDS,'RESOURCE_WITNESS')
        require(v['reservation_ids']==[v['reservation_plan'][0]['reservation_id']],'RESOURCE_WITNESS')
        require(set(v['behavior_before'])==BEHAV_FIELDS and set(v['behavior_after'])==BEHAV_FIELDS,'BEHAVIOR_WITNESS')
        require(all(set(c)==CREDFIELDS for c in v['credential_witnesses']),'CREDENTIAL_WITNESS')
        require(v['credential_witnesses']==sortset(v['credential_witnesses']),'CREDENTIAL_WITNESS')
        require(v['checked_deps']==sortset(v['checked_deps']),'DEP_CONFLICT')
        require(v['ctx']['action_hash']==action_hash('PAY-1',v['action']),'BINDING')
        require(v['trusted_time']=={'lo':v['accepted_at'],'hi':v['accepted_at']},'TIME_WITNESS')
    return True

class SignedPayFlow(ReferenceW):
    """A strict PAY-1 contract slice that plugs Phase 3 into Phase 2 signed core.

    The test W still uses an in-process RLock. SQLite/real CAS and clock
    uncertainty are NOT implemented; the reported coverage must reflect this.
    """
    def __init__(self, cases=None, schema_root=None):
        super().__init__('PAY-1',cap=30000)
        b,seed_store,actors,signers=setup()
        if cases is not None:
            b=bundle(cases)
        # Align fixed PAY publication/read rights: an actual V reviewer is an
        # authorized reader of the source and POLICY before the grants go live.
        b['policy_record']['value']['readers']=sortset(b['policy_record']['value']['readers']+[actors['V'].name])
        b['task_record']['value']['policy_ref']=rec_ref(b['policy_record'])
        ev=b['evidence_record']['value']
        source=ev['source_envelope']
        source['body']['aud']=sortset(source['body']['aud']+[actors['V'].name])
        source['sig']=b64(actors['E'].key.sign(canonical(['ZJJ-SIG-v1',source['protected'],source['body']])))
        ev['source_ref']=msgref(source)
        store=TrustedStore(b['scope'])
        prefix=list(self.basekey())
        for ns,key,r,kind in (
            ('POLICY',prefix,b['policy_record'],'POLICY'),
            ('TASK',prefix+[b['task_record']['value']['task_id']],b['task_record'],'PAY_TASK'),
            ('ORDER',prefix+['ord','pay'],b['evidence_record'],'PAY_EVIDENCE'),
            ('EXPERIENCE',prefix+['main'],b['history_record'],'PAY_HISTORY')):
            store.publish_record(ns,key,1,r,kind)
        # Mirror the independently prepared KEY/ROLE & initial BEHAVIOR rows.
        for (ns,key),entry in seed_store._rows.items():
            if ns in ('KEY','ROLE','BEHAVIOR'):
                store._set(ns,list(key),entry.revision,entry.ref,entry.value,entry.record)
        self.source=b
        self.trusted=store
        self.actors=actors
        for alias,(name,seed,role,purposes) in ACTORS.items():
            who=actors[alias]
            who.roles=frozenset([role]);who.purposes=frozenset(purposes)
        self.idents.update(actors)
        self.keys={who.kid:who for who in self.idents.values()}
        self.signers={k:(v.name,v.kid) for k,v in actors.items()}
        self.accept_record=None
        self.assessment_record=None
        self.basis_record=None
        self.schema=None
        self.schema_status='UNAVAILABLE'
        if schema_root is not None:
            self.schema=UpstreamSchema(schema_root,'PAY-1')
            self.schema_status='INSTALLED'
        self.evidence_verified=False
        self.authenticated_control_fixture=True
        self.cap=30000
        self.resource_revision=1
        self.taskflight={}
        self.commit_record=None
        self.initial_deps=None
        self.issue_result=None
        self.commit_result=None

    def _validate(self,obj,kind):
        if kind.startswith('Record_'):
            check_record_contract(obj,kind[7:],self.scope)
        if self.schema is not None:
            self.schema.validate(obj,kind)

    def basedeps(self,op):
        d=[];s=self.trusted;p=list(self.basekey());a=self.source['action']['payload']
        for ns,key in [('POLICY',p),('TASK',p+[self.source['task_record']['value']['task_id']]),
             ('ORDER',p+[a['order_id'],a['stage']]),('EXPERIENCE',p+['main']),
             ('BEHAVIOR',p+['payer'])]:d.append(s.dep(ns,key))
        return sortset(d+self.issuerdeps(['H','E']))

    def issuerdeps(self,aliases):
        out=[];p=list(self.basekey());s=self.trusted
        for alias in aliases:
            if alias=='V2':alias='V'
            who=self.idents[alias];role=next(iter(who.roles))
            out.extend((s.dep('KEY',[who.kid]),s.dep('ROLE',p+[who.name,role])))
        return sortset({(x['namespace'],tuple(x['key'])):x for x in out}.values())

    def fulldeps(self,op):
        return required_pay_deps(self.trusted,op.action,op.task_id,self.signers,bool(op.required),self.now)

    def _bind_current_records(self):
        b=self.source;prefix=list(self.basekey());a=b['action']['payload']
        for ns,key,r in (
            ('POLICY',prefix,b['policy_record']),
            ('TASK',prefix+[b['task_record']['value']['task_id']],b['task_record']),
            ('ORDER',prefix+[a['order_id'],a['stage']],b['evidence_record']),
            ('EXPERIENCE',prefix+[b['history_record']['value']['partition']],b['history_record'])):
            current=self.trusted.current(ns,key)
            require(current.record is not None and current.record==r and current.ref==rec_ref(r),'STALE_AUTHORITY')
        return True

    def _trusted_verify(self,op):
        self._bind_current_records()
        b=copy.deepcopy(self.source)
        b['action']=op.action
        b['claimed_assessment']=self.assessment_record['value']
        # NOTE: test fixture's authenticated publication witness is an explicit trust assumption.
        risk,ass=verify_pay_authoritative(**b)
        require(self.assessment_record['value']==ass,'ASSESSMENT_MISMATCH')
        require(tuple(risk.required_reviews)==op.required,'RISK_BINDING')
        expected=required_pay_deps(self.trusted,op.action,op.task_id,self.signers,bool(op.required),self.now)
        verify_claimed_dependencies(op.permit['body']['deps'],expected)
        require(op.basis['value']['deps']==self.basedeps(op),'DEP_CONFLICT')
        require(op.basis['value']['assessment_ref']==rec_ref(self.assessment_record),'ASSESSMENT_REF')
        require(op.ctx['basis_ref']==rec_ref(op.basis),'BASIS_REF')
        require(op.basis['value']['required_reviews']==list(op.required),'REVIEW_REQUIRED')
        require(tuple(sorted(x['body']['payload']['purpose'] for x in op.reviews))==tuple(sorted(op.required)), 'REVIEW_PURPOSE')
        require(op.ctx['action_hash']==action_hash('PAY-1',op.action),'BINDING')
        self._validate(op.basis,'Record_BASIS')
        self._validate(self.assessment_record,'Record_ASSESSMENT')
        return True

    def prepare(self):
        b=self.source
        self._bind_current_records()
        # Ensure the fixed reference Action is the one W registers.
        old=self.action_for
        try:
            self.action_for=lambda payload,task_id=None,principal='payer':copy.deepcopy(b['action'])
            op=super().prepare(copy.deepcopy(b['action']['payload']),{'risk':'CLEAR'},
                               task_id=b['task_record']['value']['task_id'])
        finally:self.action_for=old
        risk,ass=verify_pay_authoritative(**b)
        op.required=tuple(risk.required_reviews)
        self.initial_deps=self.basedeps(op)
        self.assessment_record={'version':'2.6','profile':'PAY-1','kind':'ASSESSMENT',
                                'scope':copy.deepcopy(self.scope),'value':ass}
        self._validate(self.assessment_record,'Record_ASSESSMENT')
        polref=rec_ref(b['policy_record']);taskref=rec_ref(b['task_record'])
        evref=rec_ref(b['evidence_record'])
        bv={'scope':copy.deepcopy(self.scope),'operation_id':op.action['operation_id'],
            'action':op.action,'action_hash':action_hash('PAY-1',op.action),
            'policy_ref':polref,'task_ref':taskref,'evidence_refs':[evref],
            'assessment_ref':rec_ref(self.assessment_record),'required_reviews':list(op.required),
            'deps':copy.deepcopy(self.initial_deps),'iat':'100','exp':ass['exp']}
        self.basis_record={'version':'2.6','profile':'PAY-1','kind':'BASIS','scope':copy.deepcopy(self.scope),'value':bv}
        self._validate(self.basis_record,'Record_BASIS')
        op.basis=self.basis_record
        op.ctx={'scope':copy.deepcopy(self.scope),'operation_id':op.action['operation_id'],
           'principal':'payer','holder':self.idents['H'].name,'holder_kid':self.idents['H'].kid,
           'executor':self.idents['X'].name,'action_hash':bv['action_hash'],
           'policy_ref':polref,'basis_ref':rec_ref(self.basis_record)}
        op.snap=tuple(self.fulldeps(op))
        return op

    def review(self,op,verdict='APPROVE',purpose=None,alias='V'):
        # Core §3 requires expiry <= all bearing sources (task exp=300).
        with self.lock:
            use=purpose or (op.required[0] if op.required else 'ANOMALY')
            deps=sortset(self.basedeps(op)+self.issuerdeps([alias]))
            signer=self.idents[alias]
            env=signer.sign('PAY-1','Review',self.scope,
                {'ctx':op.ctx,'purpose':use,'verdict':verdict,'reason':'trusted review'},
                deps=deps,aud=[self.idents[a].name for a in ['H','G','X','U']],at=self.now,
                ttl=int(op.basis['value']['exp'])-self.now,iid=self.newid())
            self._verified(env,'Review',alias)
            if verdict=='DENY':
                self.published_denials[(op.ctx['basis_ref'],use)].append(msgref(env))
                self.review_range_rev[(op.ctx['basis_ref'],use)]+=1
            else:op.reviews.append(env)
            return env

    def authorize(self,op,verdict='APPROVE'):
        with self.lock:
            rr=sortset([msgref(r) for r in op.reviews]);require(len(rr)==len(op.required),'REVIEW_REQUIRED')
            deps=sortset({(d['namespace'],tuple(d['key'])):d for d in
                  (self.basedeps(op)+self.issuerdeps(['U']+(['V'] if op.required else [])))}.values())
            env=self.idents['U'].sign('PAY-1','Authorization',self.scope,
                {'ctx':op.ctx,'review_refs':rr,'purpose':'EXECUTE','verdict':verdict},
                refs=rr,deps=deps,aud=[self.idents[a].name for a in ['H','G','X']],at=self.now,
                ttl=int(op.basis['value']['exp'])-self.now,iid=self.newid())
            self._verified(env,'Authorization','U');op.authorization=env
            self._validate(env,'Authorization')
            return env

    def issue(self,op):
        res=super().issue(op)
        self._validate(op.issue,'IssueRequest')
        self._validate(res,'Permit')
        self._trusted_verify(op)
        req_ref=msgref(op.issue);permit_ref=msgref(res)
        reply=self.idents['G'].sign('PAY-1','Result',self.scope,
            {'request_ref':req_ref,'attempt_id':'','result':'ISSUED',
             'reasons':[{'check':'result','code':'OK'}], 'operation_id':op.action['operation_id'],
             'permit_ref':permit_ref,'acceptance_ref':'','status':'NONE','status_seq':'0',
             'retry_after':''},refs=[req_ref,permit_ref],deps=self.issuerdeps(['G']),
            aud=[self.idents['H'].name],at=self.now,iid=self.newid())
        self._verified(reply,'Result','G')
        self.issue_result=reply
        return res

    def challenge(self,op):
        ret=super().challenge(op)
        self._validate(op.challenge_request,'ChallengeRequest');self._validate(ret,'Challenge')
        return ret

    def _verified(self,e,kind,alias):
        ret=super()._verified(e,kind,alias)
        self._validate(e,kind)
        return ret

    def _resource_witness(self,op):
        amount=int(op.action['payload']['amount_minor'])
        require(self.reserved+self.spent+amount<=self.cap,'RESOURCE_LIMIT')
        v={'reservation_id':self.newid(), 'key':list(self.basekey())+['payer','CNY'],
           'unit':'CNY_MINOR','amount':str(amount),'capacity_before':str(self.cap),
           'reserved_before':str(self.reserved),'spent_before':str(self.spent),
           'reserved_after':str(self.reserved+amount),'spent_after':str(self.spent),
           'revision_before':str(self.resource_revision),'revision_after':str(self.resource_revision+1)}
        return v

    def _behavior_witness(self):
        row=self.trusted.current('BEHAVIOR',list(self.basekey())+['payer'])
        return {'key':list(self.basekey())+['payer'],'revision':str(row.revision),
                'ref':row.ref,'row':copy.deepcopy(row.value)}

    def _credential_witnesses(self,seq,op):
        uses=['H','E','G','X','U']+(['V'] if op.required else [])
        out=[]
        for alias in uses:
            who=self.idents[alias];role=next(iter(who.roles));
            k=self.trusted.current('KEY',[who.kid]);r=self.trusted.current('ROLE',list(self.basekey())+[who.name,role])
            out.append({'subject':who.name,'kid':who.kid,'public_key':b64(who.pub),
                'key_grant_ref':k.ref,'role':role,'role_grant_ref':r.ref,
                'key_revision':str(k.revision),'role_revision':str(r.revision),'verified_at_seq':str(seq)})
        return sortset(out)

    def commit(self,op,proof=None):
        with self.lock:
            proof=proof if proof is not None else (op.proof if op.nonce_consumed else self.make_proof(op))
            # Protocol-specific idempotency: byte-identical proof retransmission
            # returns the frozen historical Acceptance. A different proof that
            # reuses the consumed nonce is REPLAY even if properly signed.
            if op.nonce_consumed:
                require(op.proof is not None and canonical(op.proof)==canonical(proof),'REPLAY')
                return op.acceptance
            p=self._verified(proof,'CommitProof','H')
            require(op.challenge is not None and op.permit is not None and op.challenge_request is not None,'MISSING_CHALLENGE')
            self._verified(op.challenge,'Challenge','X')
            ch=op.challenge['body']['payload']
            qr=self._verified(op.challenge_request,'ChallengeRequest','H')
            self._verified(op.permit,'Permit','G')
            pref=msgref(op.permit);cref=msgref(op.challenge)
            require(p['ctx']==op.ctx and p['permit_ref']==pref and p['challenge_ref']==cref
                    and p['session_id']==ch['session_id'] and p['nonce']==ch['nonce']
                    and p['attempt_id']==qr['attempt_id'],'BINDING')
            pp=op.permit['body']['payload']
            require(pp['ctx']==op.ctx and pp['max_uses']=='1' and int(pp['dispatch_before'])>self.now,'PERMIT')
            self._check_authorization_chain(op,pp['review_refs'],pp['authorization_ref'])
            self._trusted_verify(op)
            self._guard(op)
            before=self._behavior_witness()
            require(before['row']['accepted_count']=='0' and before['row']['inflight']==[],'BEHAVIOR_LIMIT')
            res=self._resource_witness(op)
            after_row=copy.deepcopy(before['row'])
            after_row['accepted_count']=str(int(after_row['accepted_count'])+1)
            after_row['inflight']=[op.action['operation_id']]
            after_ref=digest(['ZJJ-STATE-v1','BEHAVIOR',before['key'],str(int(before['revision'])+1),after_row])
            after={'key':before['key'],'revision':str(int(before['revision'])+1),'ref':after_ref,'row':after_row}
            seq=self.sequence+1
            cv={'ctx':copy.deepcopy(op.ctx),'action':copy.deepcopy(op.action), 'permit_ref':pref,
                'proof_ref':msgref(proof),'authorization_ref':pp['authorization_ref'],
                'review_refs':pp['review_refs'],'accept_seq':str(seq),'accepted_at':str(self.now),
                'trusted_time':{'lo':str(self.now),'hi':str(self.now)},
                'checked_deps':list(op.snap),'reservation_plan':[res],
                'reservation_ids':[res['reservation_id']],'behavior_before':before,'behavior_after':after,
                'taskflight':{'key':list(self.basekey())+[op.task_id],'operation_id':op.action['operation_id']},
                'dispatch_before':pp['dispatch_before'],'frozen_tool_request':copy.deepcopy(op.action),
                'signing_public_key':b64(self.idents['X'].pub),
                'credential_witnesses':self._credential_witnesses(seq,op)}
            record={'version':'2.6','profile':'PAY-1','kind':'COMMIT','scope':copy.deepcopy(self.scope),'value':cv}
            self._validate(record,'Record_COMMIT')
            acc=self.idents['X'].sign('PAY-1','Acceptance',self.scope,
              {'ctx':op.ctx,'permit_ref':pref,'proof_ref':msgref(proof),
               'authorization_ref':pp['authorization_ref'],'review_refs':pp['review_refs'],
               'accept_seq':str(seq),'accepted_at':str(self.now),
               'commit_record_ref':rec_ref(record),'dispatch_before':pp['dispatch_before']},
              refs=sortset([pref,msgref(proof),pp['authorization_ref']]+pp['review_refs']),
              deps=self.issuerdeps(['X']),aud=[self.idents[a].name for a in ['H','G','U']],
              at=self.now,iid=self.newid())
            self._verified(acc,'Acceptance','X')
            # Only after all validation do we update test W atomically under one lock.
            self.trusted.publish_state('BEHAVIOR',before['key'],int(after['revision']),after_row)
            self.reserved+=int(res['amount']);self.resource_revision+=1
            self.intent_accepted.add(op.intent);self.sequence=seq
            self.taskflight[op.task_id]=op.action['operation_id']
            op.nonce_consumed=True;op.proof=proof;op.status='ACCEPTED';op.reservation=True
            op.acceptance=acc;self.commit_record=record
            proof_ref=msgref(proof);acc_ref=msgref(acc)
            reply=self.idents['X'].sign('PAY-1','Result',self.scope,
               {'request_ref':proof_ref,'attempt_id':p['attempt_id'],'result':'ACCEPTED',
                'reasons':[{'check':'result','code':'OK'}], 'operation_id':op.action['operation_id'],
                'permit_ref':'','acceptance_ref':acc_ref,'status':'ACCEPTED',
                'status_seq':str(seq),'retry_after':''},
                refs=[proof_ref,acc_ref],deps=self.issuerdeps(['X']),
                aud=[self.idents['H'].name],at=self.now,iid=self.newid())
            self._verified(reply,'Result','X')
            self.commit_result=reply
            return acc

    def claim(self,op):
        with self.lock:
            require(op.status=='ACCEPTED' and op.calls==0,'NO_REDISPATCH')
            require(op.reservation and self.taskflight.get(op.task_id)==op.action['operation_id'],'RESERVATION')
            require(self.now<int(op.permit['body']['payload']['dispatch_before']),'EXPIRED')
            for dep in self.commit_record['value']['checked_deps']:
                if dep['namespace']=='BEHAVIOR':continue
                require(self.trusted.dep(dep['namespace'],dep['key'])==dep,'STALE')
            current=self._behavior_witness()
            require(current==self.commit_record['value']['behavior_after'],'BEHAVIOR_WITNESS')
            op.dispatch_attempt=self.newid();op.calls=1;op.status='EFFECT_UNKNOWN'
            return op.dispatch_attempt

    def make_proof(self,op):
        ret=super().make_proof(op);self._validate(ret,'CommitProof');return ret

    def verify_archive(self,op):
        require(op.acceptance is not None and self.commit_record is not None,'NO_ACCEPTANCE')
        self._validate(self.commit_record,'Record_COMMIT')
        self._validate(op.acceptance,'Acceptance')
        require(op.acceptance['body']['payload']['commit_record_ref']==rec_ref(self.commit_record),'COMMIT_REF')
        require(op.acceptance['body']['payload']['ctx']==self.commit_record['value']['ctx'],'BINDING')
        # Historical signature verification uses stored public key, not today\'s role freshness.
        from research.reference_executor.wire import raw, strict_verify
        e=op.acceptance
        strict_verify(raw(self.commit_record['value']['signing_public_key'],32),raw(e['sig'],64),
                      canonical(['ZJJ-SIG-v1',e['protected'],e['body']]))
        return True

    def receive_final(self,op,record):
        with self.lock:
            amount=int(op.action['payload']['amount_minor'])
            result=super().receive_final(op,record)
            if result=='SETTLED':
                # ReferenceW uses quantity=1; PAY's real ledger unit is CNY_MINOR.
                self.reserved-=amount-1
                if record['value']['outcome']=='SUCCEEDED':self.spent+=amount-1
                self.taskflight.pop(op.task_id,None)
            return result

    def cancel_pending(self,op):
        with self.lock:
            amount=int(op.action['payload']['amount_minor'])
            super().cancel_pending(op)
            self.reserved-=amount-1
            self.taskflight.pop(op.task_id,None)
