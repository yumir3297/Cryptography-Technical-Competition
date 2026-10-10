from __future__ import annotations
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase5.test_durable_w import ready
from research.phase6.trusted_final import (Controller,ToolLedger,FinalW,final_fact_id,final_sign_bytes,_pub)
from research.reference_executor.wire import ProtocolError,b64,keyid,sid,canonical,rec_ref


class FinalTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();d=Path(self.tmp.name)
    self.ctrl=Controller.fixture();self.tool=ToolLedger(d/'tool.sqlite');self.w=FinalW(d/'w.sqlite',self.ctrl.public_key)
    self.k1=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
    self.k2=Ed25519PrivateKey.from_private_bytes(b'\x52'*32)
    self.scope={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
    self.install(self.k1,1,1)
    self.f,self.op=ready();self.accepted=self.w.accept(self.f,self.op)
    self.attempt=sid(501)
    self.assertEqual(self.w.claim_bound(self.op.action['operation_id'],self.attempt), 'CLAIMED')
 def tearDown(self):self.tmp.cleanup()
 def install(self,key,epoch,revision,ledger=None,head=None):
    ledger=ledger or self.tool
    v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
       'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
       'public_key':b64(_pub(key)),'kid':keyid(_pub(key)),'epoch':str(epoch),'iat':'90','exp':'2000'}
    cert=self.ctrl.certify(self.scope,v,revision,head or ledger.head(),ledger.origin)
    return self.w.activate(cert,ledger,now=100)
 def record(self,key=None,outcome='SUCCEEDED',effect_id='effect1',at=105,issue_at=108):
    fact=self.tool.freeze(self.scope,self.op.action,self.attempt,outcome=outcome,effect_id=effect_id,at=at)
    return self.tool.reattest(self.scope,fact,key or self.k1,'tool-issuer',issue_at,'2000')
 def resign(self,r,key,issue_at=None):
    r=copy.deepcopy(r)
    if issue_at is not None:
        r['value']['iat']=str(issue_at);r['value']['exp']=str(issue_at+120)
    r['value']['attestation']['kid']=keyid(_pub(key))
    r['value']['attestation']['sig']=b64(key.sign(final_sign_bytes(r)))
    return r
 def assert_untouched(self,reserved=2000):
    self.assertEqual(self.w.snapshot()['reserved'],reserved)
    self.assertEqual(self.w.snapshot()['spent'],0)
    self.assertEqual(self.w.snapshot()['flight_rows'],1)
 def test_success_and_persistent_settlement(self):
    r=self.record();v=self.w.settle(r,now=110)
    self.assertEqual(v['status'],'SUCCEEDED');self.assertEqual(self.w.snapshot()['spent'],2000)
    self.assertEqual(self.w.snapshot()['reserved'],0);self.assertEqual(self.w.snapshot()['flight_rows'],0)
    self.assertEqual(self.w.accepted_operation(self.op.action['operation_id'])['state'],'SUCCEEDED')
    self.assertEqual(FinalW(self.w.db_path,self.ctrl.public_key).settle(r,now=1500)['historical'],True)
 def test_failed_confirmed_no_late_effect(self):
    r=self.record(outcome='FAILED_CONFIRMED',effect_id='');self.assertEqual(self.w.settle(r,now=110)['status'],'FAILED_CONFIRMED')
    self.assertEqual(self.w.snapshot()['reserved'],0);self.assertEqual(self.w.snapshot()['spent'],0)
    self.assertEqual(self.w.snapshot()['accepted_count'],1)
 def test_missing_fact_never_implies_failed(self):
    self.assertIsNone(self.tool.lookup(self.op.action['operation_id'],self.attempt))
    self.assert_untouched()
 def test_same_fact_fresh_attestation_new_ref_no_second_settlement(self):
    r=self.record();self.w.settle(r,now=110)
    r2=self.tool.reattest(self.scope,self.tool.lookup(self.op.action['operation_id'],self.attempt),self.k1,'tool-issuer',130,'2000')
    self.assertNotEqual(rec_ref(r),rec_ref(r2))
    self.assertEqual(final_fact_id(r),final_fact_id(r2))
    result=self.w.settle(r2,now=140)
    self.assertTrue(result['idempotent']);self.assertEqual(self.w.snapshot()['spent'],2000)
    self.assertEqual(self.w.snapshot()['accepted_count'],1)
 def test_expired_first_proof_requires_fresh_reattest(self):
    r=self.record(issue_at=105)
    with self.assertRaisesRegex(ProtocolError,'FINAL_EXPIRED'):self.w.settle(r,now=300)
    self.assert_untouched()
    r2=self.tool.reattest(self.scope,self.tool.lookup(self.op.action['operation_id'],self.attempt),self.k1,'tool-issuer',305,'2000')
    self.assertEqual(self.w.settle(r2,now=310)['status'],'SUCCEEDED')
 def test_rotation_recovery_same_ledger(self):
    old=self.record(issue_at=105)
    self.install(self.k2,2,2)
    with self.assertRaisesRegex(ProtocolError,'FINAL_SIGNER'):self.w.settle(old,now=110)
    self.assert_untouched()
    fresh=self.tool.reattest(self.scope,self.tool.lookup(self.op.action['operation_id'],self.attempt),self.k2,'tool-issuer',150,'2000')
    self.assertEqual(final_fact_id(fresh),final_fact_id(old))
    self.assertEqual(self.w.settle(fresh,now=160)['status'],'SUCCEEDED')
 def test_rotation_to_different_ledger_reject(self):
    rogue=ToolLedger(Path(self.tmp.name)/'other.sqlite','other-ledger')
    with self.assertRaisesRegex(ProtocolError,'LEDGER_MISMATCH'):
        self.install(self.k2,2,2,ledger=rogue)
    self.assert_untouched()
 def test_rotation_bad_controller_signature_rejected(self):
    v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
       'ledger_id':self.tool.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(self.k2)),
       'kid':keyid(_pub(self.k2)),'epoch':'2','iat':'90','exp':'2000'}
    cert=self.ctrl.certify(self.scope,v,2,self.tool.head(),self.tool.origin);cert['signature']='A'*86
    with self.assertRaises(ProtocolError):self.w.activate(cert,self.tool)
 def test_rotation_replay_epoch_reject(self):
    with self.assertRaisesRegex(ProtocolError,'EPOCH_REPLAY'):self.install(self.k2,1,2)
 def test_rotation_ledger_head_mismatch(self):
    with self.assertRaisesRegex(ProtocolError,'CONTINUITY_UNKNOWN'):
        self.install(self.k2,2,2,head='tampered')
 def test_binding_wrong_attempt_rejected_unchanged(self):
    r=self.record();r['value']['dispatch_attempt']=sid(999);r=self.resign(r,self.k1)
    with self.assertRaisesRegex(ProtocolError,'FINAL_BINDING'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_binding_wrong_ledger_rejected_unchanged(self):
    r=self.record();r['value']['ledger_id']='another-ledger';r=self.resign(r,self.k1)
    with self.assertRaisesRegex(ProtocolError,'LEDGER_MISMATCH'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_bad_signature_cannot_halt(self):
    r=self.record();self.w.settle(r,now=110)
    rogue=copy.deepcopy(r);rogue['value']['outcome']='FAILED_CONFIRMED';rogue['value']['effect_id']='';rogue['value']['no_late_effect']=True
    with self.assertRaisesRegex(ProtocolError,'BAD_SIGNATURE'):self.w.settle(rogue,now=110)
    self.assertEqual(self.w.accepted_operation(self.op.action['operation_id'])['state'],'SUCCEEDED')
 def test_trusted_conflicting_fact_halts_without_reverse_settlement(self):
    r=self.record();self.w.settle(r,now=110)
    different=copy.deepcopy(r);different['value']['final_seq']='2';different['value']['effect_id']='effect-conflict'
    different=self.resign(different,self.k1)
    out=self.w.settle(different,now=110)
    self.assertEqual(out['status'],'HALTED');self.assertEqual(self.w.snapshot()['spent'],2000)
    self.assertEqual(self.w.snapshot()['reserved'],0)
    self.assertEqual(self.w.accepted_operation(self.op.action['operation_id'])['state'],'HALTED')
 def test_halted_not_unhalted_by_good_replay(self):
    r=self.record();self.w.settle(r,now=110)
    b=copy.deepcopy(r);b['value']['final_seq']='3';b=self.resign(b,self.k1);self.w.settle(b,now=110)
    self.assertEqual(self.w.settle(r,now=140)['status'],'HALTED')
 def test_idempotent_historical_exact_bytes_after_expiry(self):
    r=self.record();self.w.settle(r,now=110)
    self.assertTrue(self.w.settle(r,now=1600)['historical'])
 def test_forged_effect_semantics_fail(self):
    r=self.record();r['value']['no_late_effect']=True;r=self.resign(r,self.k1)
    with self.assertRaisesRegex(ProtocolError,'FINAL_OUTCOME'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_claim_is_one_shot_no_arbitrary_witness_bool(self):
    self.assertEqual(self.w.claim_bound(self.op.action['operation_id'],self.attempt),'EXISTING')
    with self.assertRaisesRegex(ProtocolError,'NO_REDISPATCH'):
        self.w.claim_bound(self.op.action['operation_id'],sid(700))
 def test_unsigned_fake_final_rejected(self):
    r=self.record();r['value']['attestation']['issuer']='stranger'
    with self.assertRaisesRegex(ProtocolError,'FINAL_SIGNER'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_tool_ledger_freeze_is_immutable(self):
    r=self.record()
    with self.assertRaisesRegex(ProtocolError,'ATTEMPT_CONFLICT'):
        self.tool.freeze(self.scope,self.op.action,sid(800),outcome='FAILED_CONFIRMED',effect_id='')
    self.assertEqual(self.tool.all_facts(),[self.tool.lookup(self.op.action['operation_id'],self.attempt)])
 def test_final_ledger_restart_query_only(self):
    r=self.record();self.assertEqual(self.tool.all_facts(),ToolLedger(self.tool.path).all_facts())
    self.assert_untouched();self.assertEqual(self.w.snapshot()['accepted_count'],1)
 def test_unknown_key_not_authorized_even_if_signature_valid(self):
    r=self.record();r=self.resign(r,self.k2)
    with self.assertRaisesRegex(ProtocolError,'FINAL_SIGNER'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_bound_tool_version_reject(self):
    r=self.record();r['value']['tool_version']='2';r=self.resign(r,self.k1)
    with self.assertRaisesRegex(ProtocolError,'LEDGER_MISMATCH'):self.w.settle(r,now=110)
    self.assert_untouched()
 def test_bad_freshness_before_origin(self):
    r=self.record();r['value']['finalized_at']='200';r=self.resign(r,self.k1)
    with self.assertRaisesRegex(ProtocolError,'FINAL_TIME'):self.w.settle(r,now=110)
    self.assert_untouched()

if __name__=='__main__':unittest.main()

class CrashBoundaryTests(unittest.TestCase):
 def test_two_crash_boundaries_recovery(self):
    import subprocess,sys
    for name,final in [('after_tool_final',False),('after_w_settlement',True)]:
        with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
            runner=[sys.executable,'-m','research.phase6.crash_worker',tmp,name]
            p=subprocess.run(runner,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,79,p.stderr)
            d=Path(tmp);ctrl=Controller.fixture();ledger=ToolLedger(d/'tool.sqlite')
            w=FinalW(d/'w.sqlite',ctrl.public_key)
            f,op=ready();attempt=sid(501)
            fact=ledger.lookup(op.action['operation_id'],attempt)
            self.assertIsNotNone(fact)
            key=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
            rec=ledger.reattest(f.scope,fact,key,'tool-issuer',130,'2000')
            before=w.snapshot();self.assertEqual(before['spent'],2000 if final else 0)
            outcome=w.settle(rec,now=140)
            self.assertEqual(outcome['status'],'SUCCEEDED')
            self.assertEqual(w.snapshot()['spent'],2000)
            self.assertEqual(w.snapshot()['reserved'],0)
            self.assertEqual(w.snapshot()['accepted_count'],1)
            self.assertEqual(len(ledger.all_facts()),1)
            self.assertEqual(w.integrity_check()['integrity'],'ok')

class DispatchGuardTests(unittest.TestCase):
 def test_claim_after_permit_deadline_reject_without_dispatch(self):
    with tempfile.TemporaryDirectory() as d:
        root=Controller.fixture();t=ToolLedger(Path(d)/'tool.sqlite')
        w=FinalW(Path(d)/'w.sqlite',root.public_key)
        k=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
        f,op=ready();v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1',
            'destination':'pay-sim-dest','ledger_id':t.ledger_id,'evidence_method':'tool-final-v2',
            'public_key':b64(_pub(k)),'kid':keyid(_pub(k)),'epoch':'1','iat':'90','exp':'2000'}
        w.activate(root.certify(f.scope,v,1,t.head(),t.origin),t)
        r=w.accept(f,op)
        expiry=int(r['commit']['value']['dispatch_before'])
        with self.assertRaisesRegex(ProtocolError,'DISPATCH_EXPIRED'):
            w.claim_bound(op.action['operation_id'],sid(501),now=expiry)
        self.assertEqual(w.accepted_operation(op.action['operation_id'])['state'],'ACCEPTED')
        self.assertEqual(w.snapshot()['reserved'],2000)

class LedgerOriginTests(unittest.TestCase):
 def test_same_ledger_id_separate_storage_origin_rejected(self):
    # A ledger name alone must not prove continuity across physical stores.
    with tempfile.TemporaryDirectory() as d:
        c=Controller.fixture();scope={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
        first=ToolLedger(Path(d)/'ledger_a.sqlite','ledger1')
        other=ToolLedger(Path(d)/'ledger_b.sqlite','ledger1')
        self.assertNotEqual(first.origin,other.origin)
        w=FinalW(Path(d)/'w.sqlite',c.public_key)
        k1=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
        k2=Ed25519PrivateKey.from_private_bytes(b'\x52'*32)
        def certificate(led,key,epoch):
            v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
                'ledger_id':'ledger1','evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
                'kid':keyid(_pub(key)),'epoch':str(epoch),'iat':'90','exp':'2000'}
            return c.certify(scope,v,epoch,led.head(),led.origin)
        w.activate(certificate(first,k1,1),first)
        with self.assertRaisesRegex(ProtocolError,'CONTINUITY_UNKNOWN'):
            w.activate(certificate(other,k2,2),other)
 def test_storage_origin_persists_across_restart(self):
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'ledger.sqlite';a=ToolLedger(path);b=ToolLedger(path)
        self.assertEqual(a.origin,b.origin)
