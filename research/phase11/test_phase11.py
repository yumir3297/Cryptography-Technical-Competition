"""Phase11 integrated *facets*; these tests do not individually earn official PASS."""
import copy, tempfile, unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.reference_executor.wire import ProtocolError,b64,keyid,sid,rec_ref,envelope,canonical
from research.phase6.trusted_final import ToolLedger,Controller,_pub,final_fact_id,final_sign_bytes
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase8.scene_authority import _json,ROLES
from research.phase5.run_phase5 import prepare_cases
from research.phase7.guarded_dispatch import _make_cert
from research.phase11.scene_r2 import SceneR2W
from research.phase11.pay_r2 import StrictPayW, sign_window
from research.phase11.trusted_clock import seal
from research.strict_v26.upstream_schema import UpstreamSchema

ROOT=Path(__file__).resolve().parents[2]

class Phase11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)
    def expect(self,code,fn):
        with self.assertRaises(ProtocolError) as caught:fn()
        self.assertEqual(caught.exception.code,code)
    def clock(self,a,op,purpose,lo,hi):
        with a.db() as c:
            seq=c.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
        return seal(Controller(a.controller),a.profile,a.scope,op,purpose,seq,lo,hi)
    def claim(self,a,op,att,lo=107,hi=107):
        return a.claim_r2(op,att,clock=self.clock(a,op,'DISPATCH',lo,hi))
    def settle(self,a,rec,ledger,lo=110,hi=110):
        op=rec['value']['operation_id']
        return a.settle_r2(rec,ledger,clock=self.clock(a,op,'SETTLE',lo,hi))
    def payclaim(self,w,c,scope,op,att,lo=107,hi=107):
        with w._read() as con:
            seq=con.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
        proof=seal(c,'PAY-1',scope,op,'DISPATCH',seq,lo,hi)
        return w.claim_r2(op,att,clock=proof)
    def scene(self,profile='IND-DEMO-1',label=None,accept=True):
        a,act,tid,sk,ev=build_scene(self.d/'w.sqlite',profile,label,authority_class=SceneR2W)
        op=prepare_approved(a,act,tid,sk)
        if accept:a.accept(op)
        return a,act,tid,sk,ev,op
    def tool(self,a,act,*,seed=b'Q',epoch=1,revision=1,ledger=None,at=107):
        ledger=ledger or ToolLedger(self.d/'ledger.sqlite',profile=a.profile)
        signer=Ed25519PrivateKey.from_private_bytes(seed*32)
        v={'issuer':'tool-issuer','tool':act['tool'],'tool_version':'1','destination':act['destination'],
           'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(signer)),
           'kid':keyid(_pub(signer)),'epoch':str(epoch),'iat':'90','exp':'2000'}
        cert=Controller(a.controller).certify(a.scope,v,revision,ledger.head(),ledger.origin,profile=a.profile)
        a.activate_tool(cert,ledger,now=at)
        return ledger,signer,cert
    def test_ind_and_med_complete_local_final_chain_and_schema(self):
        for prof in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=prof):
                with tempfile.TemporaryDirectory() as td:
                    d=Path(td);a,act,tid,sk,ev=build_scene(d/'w.sqlite',prof,authority_class=SceneR2W)
                    op=prepare_approved(a,act,tid,sk);a.accept(op)
                    l=ToolLedger(d/'ledger.sqlite',profile=prof)
                    signer=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
                    v={'issuer':'tool-issuer','tool':act['tool'],'tool_version':'1','destination':act['destination'],
                      'ledger_id':l.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(signer)),
                      'kid':keyid(_pub(signer)),'epoch':'1','iat':'90','exp':'2000'}
                    cert=Controller(a.controller).certify(a.scope,v,1,l.head(),l.origin,profile=prof)
                    a.activate_tool(cert,l)
                    att=sid(900)
                    a2=SceneR2W(d/'w.sqlite',prof,controller=a.controller,actors=a.actors)
                    self.assertEqual(self.claim(a2,act['operation_id'],att)['status'],'CLAIMED')
                    f=l.freeze(a.scope,act,att,effect_id='effect1')
                    r=l.reattest(a.scope,f,signer,'tool-issuer',110,2000)
                    u=UpstreamSchema(ROOT,prof)
                    for name,obj in [('Record_COMMIT',op['commit_record']),('Acceptance',op['acceptance']),
                                     ('Record_TOOL_TRUST',cert['claim']['record']),('Record_TOOL_FINAL',r)]:
                        u.validate(obj,name)
                    self.assertEqual(self.settle(a2,r,l,111,111)['status'],'SUCCEEDED')
                    fresh=a2.snapshot()
                    self.assertEqual(self.settle(a2,r,l,500,500)['idempotent'],True)
                    self.assertEqual(a2.snapshot(),fresh)
                    self.assertEqual((fresh['calls'],fresh['settlements'],fresh['spent']), (1,1,1))
    def test_validly_resigned_permit_missing_dep_fails(self):
        a,act,tid,sk,ev,op=self.scene(accept=False)
        reduced=op['deps'][:-1]
        forged=copy.deepcopy(op)
        original=op['permit']
        forged['permit']=a._env('G','Permit',original['body']['payload'],refs=original['body']['refs'],
                             deps=reduced,aud=('H','X'),at=104,nonce=4,ttl=116)
        envelope(forged['permit'],{a.actors['G'].kid:a.actors['G']},now=106)
        self.expect('DEP_CONFLICT',lambda:a.accept(forged))
        self.assertEqual(a.snapshot()['accepts'],0)
        forged['deps']=reduced
        self.expect('BINDING',lambda:a.accept(forged))
        self.assertEqual(a.snapshot()['reserved'],0)
    def test_enrolment_pop_and_replay(self):
        a,act,tid,sk,ev,op=self.scene(accept=False)
        who=a.actors['H']
        rows=a.audit_r2();self.assertTrue(any(x['kind']=='ENROLL' for x in rows))
        with a.db() as c:
            row=c.execute('SELECT proof FROM verified_enrollment WHERE kid=?',(who.kid,)).fetchone()
        import json
        proof=json.loads(row['proof'])
        self.expect('ENROLL_REPLAY',lambda:a.complete_enrollment('H',proof))
        # Root-epoch changes invalidate outstanding, previously approved challenges.
        pending=a.begin_enrollment('H',now=13,not_before=13,not_after=2000)
        from research.conformance39.enrollment_lab import EnrollmentLab
        pop=EnrollmentLab.possession(who,pending,iat=14,exp=40)
        a.rotate_root_epoch()
        self.expect('ROOT_GENERATION',lambda:a.complete_enrollment('H',pop,now=15))
    def test_revocation_cancels_atomically_before_claim(self):
        a,act,tid,sk,ev,op=self.scene()
        self.tool(a,act)
        actor=a.actors['H'];key=a.role_key(actor,ROLES[a.profile]['H'])
        current=a.current_record('ROLE',key)
        cert=a.certify('ROLE',key,current,active=False)
        a.publish_cert(cert)
        state=self.claim(a,act['operation_id'],sid(903))
        self.assertEqual((state['status'],state['reason']),('CANCELLED','REVOKED'))
        self.assertEqual((a.snapshot()['calls'],a.snapshot()['reserved']), (0,0))
        self.expect('NO_DISPATCH',lambda:self.claim(a,act['operation_id'],sid(904)))
        with a.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM flight').fetchone()[0],0)
    def test_interval_crossing_unknown_preserves_escrow(self):
        a,act,tid,sk,ev,op=self.scene()
        self.tool(a,act)
        self.expect('UNKNOWN_TIME',lambda:self.claim(a,act['operation_id'],sid(901),219,220))
        self.assertEqual((a.snapshot()['reserved'],a.snapshot()['calls']), (1,0))
        self.assertEqual(self.claim(a,act['operation_id'],sid(901),221,221)['status'],'CANCELLED')
        self.assertEqual((a.snapshot()['reserved'],a.snapshot()['calls']), (0,0))
    def test_expired_first_tool_final_reattest_same_fact(self):
        for prof in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=prof):
                with tempfile.TemporaryDirectory() as td:
                    a,act,tid,sk,ev=build_scene(Path(td)/'w.sqlite',prof,authority_class=SceneR2W)
                    op=prepare_approved(a,act,tid,sk);a.accept(op)
                    ledger=ToolLedger(Path(td)/'ledger.sqlite',profile=prof)
                    key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
                    val={'issuer':'tool-issuer','tool':act['tool'],'tool_version':'1','destination':act['destination'],
                         'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
                         'kid':keyid(_pub(key)),'epoch':'1','iat':'90','exp':'2000'}
                    a.activate_tool(Controller(a.controller).certify(a.scope,val,1,ledger.head(),ledger.origin,profile=prof),ledger)
                    att=sid(908);self.claim(a,act['operation_id'],att)
                    fact=ledger.freeze(a.scope,act,att,at=110)
                    stale=ledger.reattest(a.scope,fact,key,'tool-issuer',111,2000)
                    self.expect('FINAL_EXPIRED',lambda:self.settle(a,stale,ledger,240,240))
                    self.assertEqual(a.snapshot()['reserved'],1)
                    current=ledger.reattest(a.scope,fact,key,'tool-issuer',240,2000)
                    self.assertNotEqual(rec_ref(current),rec_ref(stale))
                    self.assertEqual(final_fact_id(current),final_fact_id(stale))
                    self.assertEqual(self.settle(a,current,ledger,241,241)['status'],'SUCCEEDED')
                    self.assertEqual((a.snapshot()['calls'],a.snapshot()['settlements']), (1,1))
    def test_rotation_same_ledger_continuity_different_record_ref(self):
        for prof in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=prof):
                with tempfile.TemporaryDirectory() as td:
                    self.d=Path(td)
                    a,act,tid,sk,ev,op=self.scene(prof)
                    ledger,old_key,_=self.tool(a,act)
                    att=sid(905);self.claim(a,act['operation_id'],att)
                    fact=ledger.freeze(a.scope,act,att)
                    old=ledger.reattest(a.scope,fact,old_key,'tool-issuer',110,2000)
                    _,new_key,_=self.tool(a,act,seed=b'R',epoch=2,revision=2,ledger=ledger,at=111)
                    self.expect('FINAL_SIGNER',lambda:self.settle(a,old,ledger,112,112))
                    new=ledger.reattest(a.scope,fact,new_key,'tool-issuer',111,2000)
                    self.assertNotEqual(rec_ref(new),rec_ref(old))
                    self.assertEqual(final_fact_id(new),final_fact_id(old))
                    self.assertEqual(self.settle(a,new,ledger,112,112)['status'],'SUCCEEDED')
                    again=ledger.reattest(a.scope,fact,new_key,'tool-issuer',113,2000)
                    self.assertTrue(self.settle(a,again,ledger,114,114)['idempotent'])
                    self.assertEqual(a.snapshot()['settlements'],1)
    def test_tool_ledger_continuity_rejects_split_storage(self):
        a,act,tid,sk,ev,op=self.scene()
        ledger,key,cert=self.tool(a,act)
        rogue=ToolLedger(self.d/'rogue.sqlite',ledger_id=ledger.ledger_id,profile=a.profile)
        val=copy.deepcopy(cert['claim']['record']['value']);val['epoch']='2'
        alt=Controller(a.controller).certify(a.scope,val,2,rogue.head(),rogue.origin,profile=a.profile)
        self.expect('CONTINUITY_UNKNOWN',lambda:a.activate_tool(alt,rogue,now=108))
    def test_bad_final_signature_no_halt(self):
        a,act,tid,sk,ev,op=self.scene();ledger,key,_=self.tool(a,act)
        att=sid(902);self.claim(a,act['operation_id'],att)
        fact=ledger.freeze(a.scope,act,att)
        rec=ledger.reattest(a.scope,fact,key,'tool-issuer',110,2000)
        corrupt=copy.deepcopy(rec);corrupt['value']['effect_id']='wrong-effect'
        self.expect('BAD_SIGNATURE',lambda:self.settle(a,corrupt,ledger,111,111))
        self.assertEqual((a.snapshot()['reserved'],a.snapshot()['settlements']), (1,0))
    def test_authenticated_signed_contradiction_halts_without_reversal(self):
        for prof in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=prof):
                with tempfile.TemporaryDirectory() as td:
                    self.d=Path(td)
                    a,act,tid,sk,ev,op=self.scene(prof)
                    ledger,key,_=self.tool(a,act)
                    att=sid(933);self.claim(a,act['operation_id'],att)
                    fact=ledger.freeze(a.scope,act,att,at=110)
                    original=ledger.reattest(a.scope,fact,key,'tool-issuer',111,2000)
                    self.settle(a,original,ledger,112,112)
                    baseline=a.snapshot()
                    conflict=copy.deepcopy(original)
                    conflict['value']['effect_id']='contradiction-effect'
                    conflict['value']['attestation']['sig']=b64(key.sign(final_sign_bytes(conflict)))
                    result=self.settle(a,conflict,ledger,113,113)
                    self.assertEqual(result['status'],'HALTED')
                    snap=a.snapshot()
                    self.assertEqual((snap['spent'],snap['reserved'],snap['settlements']),
                                     (baseline['spent'],baseline['reserved'],baseline['settlements']))
                    self.assertEqual(ledger.lookup(act['operation_id'],att),fact)
                    self.assertTrue(any(x['kind']=='CONTRADICTION' for x in a.audit_r2()))
    def pay(self):
        c=Controller.fixture();ledger=ToolLedger(self.d/'pay-tool.sqlite')
        w=StrictPayW(self.d/'w.sqlite',c.public_key)
        flow,op=prepare_cases(None,ROOT)
        signer=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
           'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
           'public_key':b64(_pub(signer)),'kid':keyid(_pub(signer)),
           'epoch':'1','iat':'90','exp':'2000'}
        w.activate(c.certify(flow.scope,v,1,ledger.head(),ledger.origin),ledger)
        w.accept(flow,op)
        cl=w.initial_claim(flow,op);w.certified_publish(_make_cert(c,cl))
        for d in cl['changes']:
            x={'scope':flow.scope,'dep':{k:d[k] for k in ('namespace','key','revision','ref')},
               'seq':'1','iat':'90','exp':'2000'}
            w.publish_window(sign_window(c,x))
        return c,w,flow,op,ledger,signer
    def paysettle(self,w,c,flow,record,lo,hi):
        with w._read() as con:
            seq=con.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
        time=seal(c,'PAY-1',flow.scope,record['value']['operation_id'],'SETTLE',seq,lo,hi)
        return w.settle_r2(record,clock=time)
    def test_pay_full_resigned_permit_missing_dep_w_independently_rejects(self):
        flow,op=prepare_cases(None,ROOT)
        forged=copy.deepcopy(op.permit)
        forged['body']['deps']=forged['body']['deps'][:-1]
        forged['sig']=b64(flow.actors['G'].key.sign(canonical(['ZJJ-SIG-v1',forged['protected'],forged['body']])))
        envelope(forged,{flow.actors['G'].kid:flow.actors['G']},now=flow.now)
        UpstreamSchema(ROOT,'PAY-1').validate(forged,'Permit')
        op.permit=forged
        flow.challenge(op)  # X, H re-bind references to the newly signed Permit
        with tempfile.TemporaryDirectory() as td:
            w=StrictPayW(Path(td)/'w.sqlite',Controller.fixture().public_key)
            self.expect('DEP_CONFLICT',lambda:w.accept(flow,op))
            self.assertEqual((w.snapshot()['accepted_rows'],w.snapshot()['reserved']), (0,0))
    def test_pay_current_reattest_and_same_fact_twice(self):
        c,w,f,op,ledger,signer=self.pay()
        self.expect('STRICT_CLOCKED_CLAIM_ONLY',lambda:w.claim_bound(op.action['operation_id'],sid(982)))
        self.expect('STRICT_CLOCKED_CLAIM_ONLY',lambda:w.claim(op.action['operation_id'],sid(982),witness_ok=True))
        att=sid(981)
        self.assertEqual(self.payclaim(w,c,f.scope,op.action['operation_id'],att)['status'],'CLAIMED')
        fact=ledger.freeze(f.scope,op.action,att,at=110)
        stale=ledger.reattest(f.scope,fact,signer,'tool-issuer',111,2000)
        self.expect('STRICT_CLOCKED_SETTLEMENT_ONLY',lambda:w.settle(stale,now=111))
        self.expect('FINAL_EXPIRED',lambda:self.paysettle(w,c,f,stale,240,240))
        self.assertEqual(w.snapshot()['reserved'],2000)
        fresh=ledger.reattest(f.scope,fact,signer,'tool-issuer',240,2000)
        self.assertEqual(self.paysettle(w,c,f,fresh,241,241)['status'],'SUCCEEDED')
        snapshot=w.snapshot()
        self.assertTrue(self.paysettle(w,c,f,fresh,400,400)['idempotent'])
        self.assertEqual(w.snapshot(),snapshot)
        self.assertEqual(snapshot['spent'],2000)
    def test_pay_rotation_contradiction_halt_without_rollback(self):
        c,w,f,op,ledger,signer=self.pay()
        attempt=sid(980);self.payclaim(w,c,f.scope,op.action['operation_id'],attempt)
        fact=ledger.freeze(f.scope,op.action,attempt,at=110)
        old=ledger.reattest(f.scope,fact,signer,'tool-issuer',111,2000)
        newkey=Ed25519PrivateKey.from_private_bytes(b'R'*32)
        value=copy.deepcopy(c.certify(f.scope,{'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1',
                'destination':'pay-sim-dest','ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
                'public_key':b64(_pub(newkey)),'kid':keyid(_pub(newkey)),
                'epoch':'2','iat':'90','exp':'2000'},2,ledger.head(),ledger.origin))
        w.activate(value,ledger,now=112)
        self.expect('FINAL_SIGNER',lambda:self.paysettle(w,c,f,old,112,112))
        new=ledger.reattest(f.scope,fact,newkey,'tool-issuer',113,2000)
        self.assertEqual(final_fact_id(old),final_fact_id(new))
        self.assertEqual(self.paysettle(w,c,f,new,114,114)['status'],'SUCCEEDED')
        spent=w.snapshot()['spent']
        wrong=copy.deepcopy(new);wrong['value']['effect_id']='signed-contradiction'
        wrong['value']['attestation']['sig']=b64(newkey.sign(final_sign_bytes(wrong)))
        self.assertEqual(self.paysettle(w,c,f,wrong,115,115)['status'],'HALTED')
        self.assertEqual((w.snapshot()['spent'],w.snapshot()['reserved']), (spent,0))
    def test_scene_legacy_dispatch_api_cannot_bypass_clock(self):
        a,act,tid,sk,ev,op=self.scene()
        ledger,key,_=self.tool(a,act)
        self.expect('STRICT_CLOCKED_CLAIM_ONLY',lambda:a.claim(op))
        self.assertEqual(a.snapshot()['calls'],0)
    def test_concurrent_scene_claim_single_attempt(self):
        import concurrent.futures
        a,act,tid,sk,ev,op=self.scene()
        ledger,key,_=self.tool(a,act)
        at=sid(984);cert=self.clock(a,act['operation_id'],'DISPATCH',107,107)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result=list(pool.map(lambda _:a.claim_r2(act['operation_id'],at,clock=cert),range(8)))
        self.assertEqual(sum(x['status']=='CLAIMED' for x in result),1)
        self.assertEqual(sum(x['status']=='EXISTING' for x in result),7)
        self.assertEqual(a.snapshot()['calls'],1)
    def test_pay_controlled_time_cross_boundary_and_cancel(self):
        c=Controller.fixture();ledger=ToolLedger(self.d/'pay-tool.sqlite')
        w=StrictPayW(self.d/'w.sqlite',c.public_key)
        f,op=prepare_cases(None,ROOT)
        signer=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        val={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
             'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
             'public_key':b64(_pub(signer)),'kid':keyid(_pub(signer)),'epoch':'1','iat':'90','exp':'2000'}
        w.activate(c.certify(f.scope,val,1,ledger.head(),ledger.origin),ledger)
        w.accept(f,op)
        cl=w.initial_claim(f,op);w.certified_publish(_make_cert(c,cl))
        for d in cl['changes']:
            x={'scope':f.scope,'dep':{k:d[k] for k in ('namespace','key','revision','ref')},
               'seq':'1','iat':'90','exp':'108'}
            w.publish_window(sign_window(c,x))
        self.expect('UNKNOWN_TIME',lambda:self.payclaim(w,c,f.scope,op.action['operation_id'],sid(911),107,108))
        self.assertEqual(w.snapshot()['reserved'],2000)
        self.assertEqual(self.payclaim(w,c,f.scope,op.action['operation_id'],sid(912),109,109)['status'],'CANCELLED')
        self.assertEqual((w.snapshot()['reserved'],w.snapshot()['flight_rows']), (0,0))
    def test_pay_new_claim_normal_and_same_attempt_only(self):
        c=Controller.fixture();ledger=ToolLedger(self.d/'pay-tool.sqlite')
        w=StrictPayW(self.d/'w.sqlite',c.public_key);f,op=prepare_cases(None,ROOT)
        signer=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        val={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
             'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(signer)),
             'kid':keyid(_pub(signer)),'epoch':'1','iat':'90','exp':'2000'}
        w.activate(c.certify(f.scope,val,1,ledger.head(),ledger.origin),ledger)
        w.accept(f,op);cl=w.initial_claim(f,op);w.certified_publish(_make_cert(c,cl))
        for d in cl['changes']:
            x={'scope':f.scope,'dep':{k:d[k] for k in ('namespace','key','revision','ref')},
               'seq':'1','iat':'90','exp':'2000'}
            w.publish_window(sign_window(c,x))
        att=sid(913)
        self.assertEqual(self.payclaim(w,c,f.scope,op.action['operation_id'],att)['status'],'CLAIMED')
        self.assertEqual(self.payclaim(w,c,f.scope,op.action['operation_id'],att)['status'],'EXISTING')
        self.expect('NO_REDISPATCH',lambda:self.payclaim(w,c,f.scope,op.action['operation_id'],sid(914)))
        self.assertEqual(w.snapshot()['reserved'],2000)

if __name__=='__main__':unittest.main()
