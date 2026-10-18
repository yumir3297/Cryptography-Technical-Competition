"""Fresh controlled three-profile corpus, real enrollment/control/source/signatures."""
import copy
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from competition.support.schema import COMPETITION_PROTO
from competition.support.wire import Identity, WINDOW, b64, keyid, canonical, digest, rec_ref, msgref, require, sortset, action_hash
from competition.support.enrollment import EnrollmentLab
from competition.support.scene_base import SceneReadMixin
from competition.support.scene_contract import _rec
from competition.core.trusted_state import TrustedState, ROLES, TYPES, PROFILE_SCOPES, prefix, enc
from competition.core.signing import ClockClient
from competition.core.signer_broker import ScopedSignerBroker
from competition.core.authorization import AuthorizationService
from competition.profiles.scene_seed import build_scene
from competition.profiles.pay_seed import build_pay

class FreshActor(Identity):
    def __init__(self,profile,alias,name=None):
        self.name=name or ('auth-'+PROFILE_SCOPES[profile]['scenario']+'-'+alias.lower())
        self.key=Ed25519PrivateKey.generate(); self.pub=self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        self.kid=keyid(self.pub); self.roles=frozenset([ROLES[profile][alias]])
        self.purposes=frozenset(TYPES[alias]+('READ',))

@dataclass
class AuthorizationRun:
    folder: Path
    root: object
    actors: dict
    clock: object
    store: object
    service: object
    broker: object
    operations: dict
    # Optional remote signer: (profile, role, domain, claim) -> base64 signature.
    # When unset, the controlled demonstration signs locally with its own keys.
    signer: object = None

    def close(self): self.clock.close()
    def clone(self,profile): return json.loads(json.dumps(self.operations[profile]))
    def signature(self,profile,role,domain,claim):
        if self.signer is not None:return self.signer(profile,role,domain,claim)
        return b64(self.actors[profile][role].key.sign(canonical([domain,claim])))
    def identity_proof(self,profile,op,stage='GUARD'):
        cl=self.store.challenge(profile,op,stage)
        return {'claim':cl,'signature':self.signature(profile,'H','COMP-APP-AUTHZ-IDENTITY-v1',cl)}

    def publish(self,profile,ns,key,record,active=True,enrollment=None):
        with self.store.db() as c:
            row=c.execute('SELECT revision FROM a_current WHERE profile=? AND namespace=? AND key=?',(profile,ns,enc(key))).fetchone()
        cl={'profile':profile,'scope':PROFILE_SCOPES[profile],'namespace':ns,'key':key,'previous_revision':str(row[0] if row else 0),'record':record,'active':active,'enrollment':enrollment or {}}
        cert={'claim':cl,'signature':b64(self.root.sign(canonical(['COMP-APP-C-PUBLISH-v1',cl])))}
        return self.store.publish(cert)

    def update_role(self,profile,alias,active=True):
        who=self.actors[profile][alias]; role=ROLES[profile][alias]; key=prefix(profile)+[who.name,role]
        with self.store.db() as c: row=c.execute('SELECT * FROM a_current WHERE profile=? AND namespace=? AND key=?',(profile,'ROLE',enc(key))).fetchone()
        record=json.loads(row['record']); record['value']['epoch']=str(row['revision']+1)
        return self.publish(profile,'ROLE',key,record,active)

    def sign(self,profile,alias,typ,payload,*,refs=(),deps=(),aud=('H','G','X'),iat=None,exp=None):
        op=self.operations[profile]; now=int(op['basis']['value']['iat']) if iat is None else iat
        who=self.actors[profile][alias]; end=now+WINDOW if exp is None else exp
        unsigned={'protected':{'proto':COMPETITION_PROTO,'version':'2.6','profile':profile,'alg':'Ed25519','type':typ,'issuer':who.name,'kid':who.kid},'body':{'id':b64(os.urandom(16)),'scope':PROFILE_SCOPES[profile],'iat':str(now),'exp':str(end),'aud':sortset([self.actors[profile][a].name for a in aud]),'refs':sortset(list(refs)),'deps':sortset(list(deps)),'payload':copy.deepcopy(payload)}}
        claim=self.broker.challenge(profile,alias,unsigned,op['action'])
        # The caller proof goes through the same remote-signature seam as the
        # rest of the chain: an external role client answers it, and the local
        # seeded actors only sign when no signer is configured.
        proof={'claim':claim,'signature':self.signature(profile,alias,'COMP-APP-SIGN-CALL-v1',claim)}
        return self.broker.sign(profile,alias,unsigned,op['action'],caller_proof=proof)

    def resign_chain(self,profile,op,*,keep_permit_deps=True):
        # Construct genuine downstream signatures after a legitimate signer
        # omits approval/dependencies; no unsigned expected-success fixtures.
        ctx=op['ctx']; deps=op['deps']; rr=sortset([msgref(r) for r in op['reviews']])
        op['authorization']=self.sign(profile,'U','Authorization',{'ctx':ctx,'review_refs':rr,'purpose':'EXECUTE','verdict':'APPROVE'},refs=rr,deps=deps)
        ar=msgref(op['authorization']); refs=sortset(rr+[ar])
        op['issue']=self.sign(profile,'H','IssueRequest',{'ctx':ctx,'review_refs':rr,'authorization_ref':ar},refs=refs,deps=deps,aud=('G',))
        declared=op.get('permit',{}).get('body',{}).get('deps',deps) if keep_permit_deps else deps
        # The COMMIT trio used to be dated thirty seconds out -- fine for a script
        # placing them back to back, impossible for a person driving a page.  The
        # chain is assembled before anybody answers, so these three have to be
        # good for as long as the rest of it.
        exp=int(op['basis']['value']['exp']); short_exp=exp
        op['permit']=self.sign(profile,'G','Permit',{'ctx':ctx,'review_refs':rr,'authorization_ref':ar,'max_uses':'1','dispatch_before':str(exp)},refs=refs,deps=declared,aud=('H','X'),exp=exp)
        pr=msgref(op['permit']); attempt=b64(os.urandom(16)); session=b64(os.urandom(16)); nonce=b64(os.urandom(32))
        op['challenge_request']=self.sign(profile,'H','ChallengeRequest',{'purpose':'COMMIT','operation_id':ctx['operation_id'],'permit_ref':pr,'action_hash':ctx['action_hash'],'attempt_id':attempt},refs=[pr],deps=deps,aud=('X',),exp=short_exp)
        qr=msgref(op['challenge_request'])
        op['challenge']=self.sign(profile,'X','Challenge',{'purpose':'COMMIT','operation_id':ctx['operation_id'],'permit_ref':pr,'action_hash':ctx['action_hash'],'holder':ctx['holder'],'holder_kid':ctx['holder_kid'],'session_id':session,'nonce':nonce,'request_ref':qr},refs=[pr,qr],deps=deps,aud=('H',),exp=short_exp)
        op['proof']=self.sign(profile,'H','CommitProof',{'ctx':ctx,'permit_ref':pr,'challenge_ref':msgref(op['challenge']),'session_id':session,'nonce':nonce,'attempt_id':attempt},refs=[pr,msgref(op['challenge'])],deps=deps,aud=('X',),exp=short_exp)
        return op

    def deny(self,profile,op,purpose=None,verdict='DENY'):
        required=op['required']; purpose=purpose or (required[0] if required else 'EXECUTE')
        alias='U' if purpose=='EXECUTE' else 'V'; typ='Authorization' if alias=='U' else 'Review'
        payload={'ctx':op['ctx'],'purpose':purpose,'verdict':verdict}
        if alias=='V': payload['reason']='authenticated review decision'
        else: payload['review_refs']=sortset([msgref(x) for x in op['reviews']])
        msg=self.sign(profile,alias,typ,payload,deps=op['deps'],refs=payload.get('review_refs',[]))
        return msg,self.service.publish_review(profile,msg)

    def coverage(self,profile,op):
        cl={'profile':profile,'scope':PROFILE_SCOPES[profile],'operation_id':op['action']['operation_id'],'ctx':op['ctx'],'action':op['action'],'purposes':sortset(['EXECUTE']+op['required']),'revision':'1','complete':True,'refs':[]}
        self.store.initialize_coverage({'claim':cl,'signature':b64(self.root.sign(canonical(['COMP-APP-DENY-COVERAGE-v1',cl])))})

def initialize(folder,*,pay_mode='FLAG',ind_label=None,names=None,roster=None):
    """Create one fresh authenticated three-profile corpus.

    Two ways to get the role keys, and they differ only in **who made them**:

    * no ``roster`` -- the local fallback.  The controlled bootstrap generates
      every role key here, writes it beside the trusted state as its own 0600
      file, and signs with it.  This is the default path and nothing about it
      changed.
    * ``roster`` -- the endpoints made their own keys and published only the
      public halves (``competition.server.roster``).  Nothing is generated and
      **no role key file is written**: every chain message, source attestation
      and possession proof in the corpus is signed by asking the endpoint that
      owns the key.  All endpoints must therefore be reachable while this runs.

    ``C.key`` (the root) stays with the trusted side either way.
    """
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    if (folder/'auth-w.sqlite').exists(): raise ValueError('New initialization must never reset an existing W')
    require(roster is None or names is None,'INIT_ROSTER_NAMES')
    root=Ed25519PrivateKey.generate()
    if roster is None:
        # Local fallback (default path): the trusted side generates every role key
        # and keeps it.  Left exactly as it was.
        actors={p:{a:FreshActor(p,a,(names or {}).get((p,a))) for a in TYPES} for p in PROFILE_SCOPES}
        for p,r in actors.items():
            for alias,who in r.items():
                f=folder/(p+'-'+alias+'.key');f.write_bytes(who.key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()));os.chmod(f,0o600)
    else:
        # External mode: every role key lives at its own endpoint, so there is
        # nothing to generate and nothing to write here.
        actors=roster
    cfile=folder/'C.key';cfile.write_bytes(root.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()));os.chmod(cfile,0o600)
    clock=ClockClient(cfile,folder/'c-clock.sqlite')
    store=TrustedState(folder/'auth-w.sqlite',root.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),actors,clock)
    run=AuthorizationRun(folder,root,actors,clock,store,AuthorizationService(store),ScopedSignerBroker(store,actors),{})
    try:
        now=int(time.time()); exp=now+WINDOW
        for p,roster in actors.items():
            for alias,who in roster.items():
                tup={'scope':PROFILE_SCOPES[p],'subject':who.name,'public_key':b64(who.pub),'kid':who.kid,'purposes':sortset(list(who.purposes)),'key_not_before':str(now),'key_not_after':str(exp),'root_generation':'1'}
                pending={'tuple':tup,'enrollment_id':b64(os.urandom(16)),'nonce':b64(os.urandom(32))}
                pop=EnrollmentLab.possession(who,pending,iat=now,exp=now+WINDOW)
                kv={'subject':who.name,'public_key':b64(who.pub),'kid':who.kid,'epoch':'1','purposes':tup['purposes'],'iat':str(now),'exp':str(exp),'root_generation':'1','enrollment_ref':digest(['COMP-APP-POP-v1',pop])}
                run.publish(p,'KEY',[who.kid],_rec(p,'KEY_GRANT',PROFILE_SCOPES[p],kv),enrollment=pop)
                for role in [ROLES[p][alias]]+(['READER'] if p!='PAY-1' and alias!='E' else []):
                    key=prefix(p)+[who.name,role]
                    with store.db() as c: old=c.execute('SELECT revision FROM a_current WHERE profile=? AND namespace=? AND key=?',(p,'ROLE',enc(key))).fetchone()
                    constraints={'payer_set':['payer'],'max_amount_minor':'100000'} if p=='PAY-1' else SceneReadMixin._role_constraints(type('RoleView',(),{'profile':p})(),alias,role)
                    rv={'subject':who.name,'role':role,'epoch':str(old[0]+1 if old else 1),'scope_set':[PROFILE_SCOPES[p]],'tool_set':['pay-sim' if p=='PAY-1' else 'line-sort-sim' if p=='IND-DEMO-1' else 'med-order-sim'],'destination_set':['pay-sim-dest'] if p=='PAY-1' else ['med-demo-ledger'] if p=='MED-DEMO-1' else sortset(['ind-release-bin','ind-quarantine-bin','ind-inspection-bay']),'constraints':constraints,'iat':str(now),'exp':str(exp)}
                    run.publish(p,'ROLE',key,_rec(p,'ROLE_GRANT',PROFILE_SCOPES[p],rv))
            corpus=build_pay(roster,PROFILE_SCOPES[p],now,mode=pay_mode) if p=='PAY-1' else build_scene(p,roster,PROFILE_SCOPES[p],now,label=ind_label if p=='IND-DEMO-1' else None)
            for row in corpus['rows']:run.publish(p,row['namespace'],row['key'],row['record'])
            op={k:corpus[k] for k in ('action','task_id','scene_key')}
            op['assessment']={'value':{'cutoff':str(now),'iat':str(now),'exp':str(now+WINDOW)}}
            with store.tx() as c:
                event=store.event(c,p,op['action']['operation_id'],'AUTHZ_GUARD','')
                derived=run.service.verifier.adapters[p].derive(c,op,event)
            av=derived['assessment_value']; op['assessment']=_rec(p,'ASSESSMENT',PROFILE_SCOPES[p],av)
            op['required']=derived['required_reviews'];op['deps']=derived['deps']
            bv={'scope':PROFILE_SCOPES[p],'operation_id':op['action']['operation_id'],'action':op['action'],'action_hash':action_hash(p,op['action']),'policy_ref':derived['policy_ref'],'task_ref':derived['task_ref'],'evidence_refs':derived['evidence_refs'],'assessment_ref':rec_ref(op['assessment']),'required_reviews':op['required'],'deps':derived['basis_deps'],'iat':av['iat'],'exp':av['exp']}
            op['basis']=_rec(p,'BASIS',PROFILE_SCOPES[p],bv)
            op['ctx']={k:copy.deepcopy(op['action'][k]) for k in ('scope','operation_id','principal','holder','holder_kid','executor')}
            op['ctx'].update({'action_hash':bv['action_hash'],'policy_ref':bv['policy_ref'],'basis_ref':rec_ref(op['basis'])})
            run.operations[p]=op
            op['reviews']=[run.sign(p,'V','Review',{'ctx':op['ctx'],'purpose':purpose,'verdict':'APPROVE','reason':'authenticated required review'},deps=op['deps'],exp=int(av['exp'])) for purpose in op['required']]
            run.resign_chain(p,op,keep_permit_deps=False); run.coverage(p,op)
        return run
    except BaseException:
        run.close();raise
