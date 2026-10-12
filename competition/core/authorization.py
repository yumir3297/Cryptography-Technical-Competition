"""One authorization guard for all profiles; T is not a protocol Acceptance."""
import copy
import json
from jsonschema import ValidationError
from competition.support.wire import require, ProtocolError, envelope, msgref, rec_ref, action_hash, sortset, digest
from competition.core.event_clock import require_window
from competition.core.trusted_state import ROLES, TYPES, PROFILE_SCOPES, prefix, enc

class CommonGuard:
    def __init__(self, store):
        self.store = store
        from competition.profiles.authorization_scene import SceneAuthorizationAdapter
        from competition.profiles.authorization_pay import PayAuthorizationAdapter
        self.adapters = {p: (PayAuthorizationAdapter if p == 'PAY-1' else SceneAuthorizationAdapter)(store,p,actors) for p,actors in store.actors.items()}

    def message(self,c,profile,alias,typ,msg,action,event):
        require(msg is not None, 'MISSING_APPROVAL')
        who = self.store.actors[profile][alias]
        self.store.schemas[profile].validate(msg,typ)
        require((msg['protected']['profile'],msg['protected']['type'],msg['protected']['issuer'],msg['protected']['kid'],msg['body']['scope']) == (profile,typ,who.name,who.kid,PROFILE_SCOPES[profile]),'MESSAGE_BINDING')
        require(typ in TYPES[alias], 'NO_ROLE')
        envelope(msg,{who.kid:who},now=event['lo']); require_window(msg['body'],event)
        self.store.credential(c,profile,alias,ROLES[profile][alias],typ,action,event)
        self.store.read_permission(c,profile,alias,action,event)
        return msg['body']['payload']

    def verify(self,c,profile,op,event):
        try:
            return self._verify(c,profile,op,event)
        except ValidationError as exc:
            raise ProtocolError('SCHEMA_INVALID') from exc
        except (KeyError,TypeError,ValueError) as exc:
            if isinstance(exc,ProtocolError): raise
            raise ProtocolError('INPUT_FIELDS') from exc

    def _verify(self,c,profile,op,event):
        require(c.in_transaction, 'AUTH_TRANSACTION_REQUIRED')
        require(profile in self.adapters and op['action']['scope']==PROFILE_SCOPES[profile], 'BINDING')
        action = op['action']; actors=self.store.actors[profile]
        self.store.read_permission(c,profile,'H',action,event)
        require(actors['U'].name not in (actors['G'].name,actors['X'].name), 'SUBJECT_SEPARATION')
        derived = self.adapters[profile].derive(c,op,event)
        required=derived['required_reviews']; deps=derived['deps']
        require(not required or actors['V'].name not in (actors['U'].name,actors['G'].name,actors['X'].name), 'SUBJECT_SEPARATION')
        ctx={k:copy.deepcopy(action[k]) for k in ('scope','operation_id','principal','holder','holder_kid','executor')}
        ctx.update({'action_hash':action_hash(profile,action),'policy_ref':derived['policy_ref'],'basis_ref':rec_ref(op['basis'])})
        require(op['ctx']==ctx,'BINDING')
        require((action['holder'],action['holder_kid'],action['executor'])==(actors['H'].name,actors['H'].kid,actors['X'].name),'SUBJECT_BINDING')
        for name,kind in [('basis','Record_BASIS'),('assessment','Record_ASSESSMENT')]:
            self.store.schemas[profile].validate(op[name],kind); require_window(op[name]['value'],event)
        av=op['assessment']['value']; bv=op['basis']['value']
        require(av==derived['assessment_value'],'ASSESSMENT_MISMATCH')
        expected={'scope':PROFILE_SCOPES[profile],'operation_id':action['operation_id'],'action':action,'action_hash':ctx['action_hash'],'policy_ref':derived['policy_ref'],'task_ref':derived['task_ref'],'evidence_refs':derived['evidence_refs'],'assessment_ref':rec_ref(op['assessment']),'required_reviews':required,'deps':derived['basis_deps'],'iat':bv['iat'],'exp':bv['exp']}
        require(bv==expected and bv['iat']==av['iat'] and int(bv['exp'])<=int(av['exp']), 'BASIS_BINDING')
        require(op.get('required',required)==required and op.get('deps',deps)==deps,'DEP_CONFLICT')
        reviews=op['reviews']; require(type(reviews) is list and len(reviews)==len(required),'REVIEW_REQUIRED')
        require(sorted(r['body']['payload']['purpose'] for r in reviews)==sorted(required),'REVIEW_REQUIRED')
        for r in reviews:
            payload=self.message(c,profile,'V','Review',r,action,event)
            require(payload['ctx']==ctx and payload['verdict']=='APPROVE','REVIEW_DENY')
        rr=sortset([msgref(r) for r in reviews]); auth=op['authorization']; permit=op['permit']; qr=op['challenge_request']; ch=op['challenge']; proof=op['proof']; issue=op['issue']
        for alias,typ,msg in [('U','Authorization',auth),('H','IssueRequest',issue),('G','Permit',permit),('H','ChallengeRequest',qr),('X','Challenge',ch),('H','CommitProof',proof)]:
            self.message(c,profile,alias,typ,msg,action,event)
        ar=msgref(auth); pr=msgref(permit)
        require(auth['body']['payload']=={'ctx':ctx,'review_refs':rr,'purpose':'EXECUTE','verdict':'APPROVE'} and auth['body']['refs']==rr,'AUTH_DENY')
        require(issue['body']['payload']=={'ctx':ctx,'review_refs':rr,'authorization_ref':ar} and issue['body']['refs']==sortset(rr+[ar]),'BINDING')
        require(permit['body']['payload']=={'ctx':ctx,'review_refs':rr,'authorization_ref':ar,'max_uses':'1','dispatch_before':permit['body']['exp']} and permit['body']['refs']==sortset(rr+[ar]),'BINDING')
        require(permit['body']['deps']==deps,'DEP_CONFLICT')
        # Each new competition input declares the derived finite graph. This is
        # stronger than parser-only checks; the original wire shape is unchanged.
        for msg in reviews+[auth,issue,permit,qr,ch,proof]:
            require(msg['body']['deps']==deps,'DEP_CONFLICT')
        q=qr['body']['payload']; h=ch['body']['payload']; f=proof['body']['payload']
        require(q['purpose']=='COMMIT' and q['operation_id']==ctx['operation_id'] and q['permit_ref']==pr and q['action_hash']==ctx['action_hash'] and qr['body']['refs']==[pr], 'BINDING')
        require(h=={'purpose':'COMMIT','operation_id':ctx['operation_id'],'permit_ref':pr,'action_hash':ctx['action_hash'],'holder':ctx['holder'],'holder_kid':ctx['holder_kid'],'session_id':h['session_id'],'nonce':h['nonce'],'request_ref':msgref(qr)} and ch['body']['refs']==sortset([pr,msgref(qr)]),'BINDING')
        require(f=={'ctx':ctx,'permit_ref':pr,'challenge_ref':msgref(ch),'session_id':h['session_id'],'nonce':h['nonce'],'attempt_id':q['attempt_id']} and proof['body']['refs']==sortset([pr,msgref(ch)]) and int(proof['body']['iat'])>=int(ch['body']['iat']) and int(proof['body']['exp'])<=min(int(ch['body']['exp']),int(permit['body']['exp'])),'BINDING')
        audiences=[(issue,['G']),(permit,['H','X']),(qr,['X']),(ch,['H']),(proof,['X']),(auth,['H','G','X'])]+[(r,['H','G','X']) for r in reviews]
        require(all(m['body']['aud']==sortset([actors[a].name for a in recipients]) for m,recipients in audiences),'AUDIENCE_BINDING')
        witness=self.store.deny_witness(c,profile,ctx,required)
        require(not witness['refs'],'REVIEW_DENY')
        return {'decision':'T','status':'AUTHORIZED_GUARD','profile':profile,'scope':PROFILE_SCOPES[profile],'operation_id':action['operation_id'],'required_reviews':required,'deps':deps,'deny_witness':witness,'chain_refs':sortset([msgref(m) for m in reviews+[auth,issue,permit,qr,ch,proof]]),'time_witness':event,'checks':{'identity':'T','signatures':'T','current_credentials':'T','subject_separation':'T','source_binding':'T','required_reviews':'T','required_dependencies':'T','deny_coverage':'T'},'protocol_acceptance':False}

class AuthorizationService:
    def __init__(self, store, *, consumer=None):
        self.store=store; self.verifier=CommonGuard(store); self._consumer=consumer

    def guard(self,profile,op,proof):
        # Consumer is injected at trusted server startup, never a wire input.
        with self.store.tx() as c:
            event=self.store.event(c,profile,op['action']['operation_id'],'AUTHZ_GUARD',digest(op))
            self.store.authenticate(c,profile,op,proof,'GUARD',event)
            result=self.verifier.verify(c,profile,op,event)
            final=self.store.event(c,profile,op['action']['operation_id'],'AUTHZ_GUARD',digest(op))
            result=self.verifier.verify(c,profile,op,final)
            request_ref=digest(['COMP-APP-CALL-v1',profile,op])
            old=c.execute('SELECT * FROM a_guard_fact WHERE profile=? AND operation_id=?',(profile,result['operation_id'])).fetchone()
            if old:
                require(old['request_ref']==request_ref,'ID_CONFLICT')
                return json.loads(old['blob'])
            if self._consumer is not None:
                result['consumer_result']=self._consumer(c,result)
            seq=c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',('AUTHORIZED_GUARD',profile,result['operation_id'],enc({'op':op,'result':result}))).lastrowid
            result['w_seq']=seq
            c.execute('INSERT INTO a_guard_fact VALUES(?,?,?,?,?)',(profile,result['operation_id'],request_ref,seq,enc(result)))
        return result

    def publish_review(self,profile,message):
        p=message['body']['payload']; ctx=p['ctx']; alias='V' if message['protected']['type']=='Review' else 'U'; typ='Review' if alias=='V' else 'Authorization'
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM a_deny_range WHERE profile=? AND operation_id=? AND basis_ref=?',(profile,ctx['operation_id'],ctx['basis_ref'])).fetchone()
            require(row is not None,'DENY_COVERAGE_UNKNOWN')
            event=self.store.event(c,profile,ctx['operation_id'],'DENY_PUBLISH',msgref(message))
            require(ctx==json.loads(row['context']) and p['purpose'] in json.loads(row['purposes']) and p['verdict'] in ('APPROVE','DENY'),'BINDING')
            # Recover action from the C-certified registration, not a caller hint.
            cert=json.loads(row['root_certificate']); action=cert['claim'].get('action')
            self.verifier.message(c,profile,alias,typ,message,action,event)
            final=self.store.event(c,profile,ctx['operation_id'],'DENY_PUBLISH',msgref(message))
            self.verifier.message(c,profile,alias,typ,message,action,final)
            event=final
            credentials=self.store.credential(c,profile,alias,ROLES[profile][alias],typ,action,event)
            old=c.execute('SELECT seq FROM a_publication WHERE profile=? AND ref=?',(profile,msgref(message))).fetchone()
            if old:return {'seq':old[0],'existing':True}
            seq=c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',('PUBLICATION',profile,ctx['operation_id'],enc({'message':message,'event':event,'previous_revision':row['revision'],'credential_witnesses':credentials}))).lastrowid
            c.execute('INSERT INTO a_publication VALUES(?,?,?,?,?,?,?,?)',(profile,ctx['operation_id'],ctx['basis_ref'],p['purpose'],msgref(message),enc(message),p['verdict'],seq))
            require(c.execute('UPDATE a_deny_range SET revision=revision+1 WHERE profile=? AND operation_id=? AND basis_ref=? AND revision=?',(profile,ctx['operation_id'],ctx['basis_ref'],row['revision'])).rowcount==1,'COVERAGE_RACE')
            return {'seq':seq,'revision':row['revision']+1,'ref':msgref(message)}

    def read(self,profile,op,proof,*,stage='DETAIL',candidate=None):
        require(stage in ('CANDIDATE','DETAIL'),'IDENTITY_STAGE')
        with self.store.tx() as c:
            event=self.store.event(c,profile,op['action']['operation_id'],'AUTHZ_READ',digest(op))
            self.store.authenticate(c,profile,op,proof,stage,event)
            # No candidate callback or source payload access before current ACL.
            derived=self.verifier.adapters[profile].derive(c,op,event)
            records=derived.get('evidence_records',[])
            projection={'profile':profile,'scope':PROFILE_SCOPES[profile],'view_kind':'CROPPED_APPLICATION_PROJECTION','original_envelope':False,'evidence_refs':derived['evidence_refs'],'records':[r['value'].get('data',r['value'].get('source_envelope',{}).get('body',{}).get('payload',{})) for r in records]}
            if candidate is not None:
                require(stage=='CANDIDATE','IDENTITY_STAGE')
                return candidate(copy.deepcopy(projection))
            return projection

    def counts(self):
        with self.store.db() as c:
            return {'guard_commits':c.execute('SELECT COUNT(*) FROM a_guard_fact').fetchone()[0], 'publications':c.execute('SELECT COUNT(*) FROM a_publication').fetchone()[0]}
