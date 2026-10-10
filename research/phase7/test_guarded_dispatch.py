from __future__ import annotations
import copy,tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase5.run_phase5 import prepare_cases
from research.phase6.trusted_final import Controller,ToolLedger,_pub
from research.reference_executor.wire import ProtocolError,b64,keyid,sid
from research.phase7.guarded_dispatch import GuardedFinalW,_make_cert
from research.phase7.test_official_contract import ROOT

class GuardedDispatchTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();d=Path(self.tmp.name)
    self.c=Controller.fixture();self.tool=ToolLedger(d/'tool.sqlite')
    self.w=GuardedFinalW(d/'w.sqlite',self.c.public_key)
    self.f,self.op=prepare_cases(None,ROOT)
    key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
    val={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
       'ledger_id':self.tool.ledger_id,'evidence_method':'tool-final-v2',
       'public_key':b64(_pub(key)),'kid':keyid(_pub(key)),
       'epoch':'1','iat':'90','exp':'2000'}
    self.w.activate(self.c.certify(self.f.scope,val,1,self.tool.head(),self.tool.origin),self.tool)
    self.w.accept(self.f,self.op)
    self.attempt=sid(501)
 def tearDown(self):self.tmp.cleanup()
 def provision(self):
    claim=GuardedFinalW.initial_claim(self.f,self.op)
    self.w.certified_publish(_make_cert(self.c,claim))
 def change(self,ns,key,ref=None,active=True):
    dep=next(d for d in GuardedFinalW.initial_claim(self.f,self.op)['changes'] if d['namespace']==ns)
    update={**dep,'revision':str(int(dep['revision'])+1),'active':active}
    if ref is not None:update['ref']=ref
    self.w.certified_publish(_make_cert(self.c,{'operation_id':self.op.action['operation_id'],
        'scope':self.f.scope,'changes':[update]}))
 def test_default_denies_unprovisioned_current_state(self):
    with self.assertRaisesRegex(ProtocolError,'STATE_UNAVAILABLE'):
        self.w.claim_bound(self.op.action['operation_id'],self.attempt)
    self.assertEqual(self.w.snapshot()['reserved'],2000)
 def test_original_current_certified_allows_one_dispatch(self):
    self.provision()
    self.assertEqual(self.w.claim_bound(self.op.action['operation_id'],self.attempt),'CLAIMED')
    self.assertEqual(self.w.claim_bound(self.op.action['operation_id'],self.attempt),'EXISTING')
 def test_policy_revocation_before_claim_blocks(self):
    self.provision();self.change('POLICY',None,active=False)
    with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.w.claim_bound(self.op.action['operation_id'],self.attempt)
    self.assertEqual(self.w.accepted_operation(self.op.action['operation_id'])['state'],'ACCEPTED')
 def test_role_revocation_before_claim_blocks(self):
    self.provision();self.change('ROLE',None,active=False)
    with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.w.claim_bound(self.op.action['operation_id'],self.attempt)
 def test_aba_revision_change_even_same_ref_blocks(self):
    self.provision();self.change('POLICY',None)
    with self.assertRaisesRegex(ProtocolError,'STALE'):self.w.claim_bound(self.op.action['operation_id'],self.attempt)
 def test_missing_row_blocks_even_if_valid_permission(self):
    self.provision()
    with self.w._tx() as c:
        c.execute("DELETE FROM authority WHERE namespace='POLICY'")
    with self.assertRaisesRegex(ProtocolError,'STATE_UNAVAILABLE'):self.w.claim_bound(self.op.action['operation_id'],self.attempt)
 def test_forged_control_signature_rejected(self):
    claim=GuardedFinalW.initial_claim(self.f,self.op)
    cert=_make_cert(self.c,claim);cert['signature']='A'*86
    with self.assertRaises(ProtocolError):self.w.certified_publish(cert)
 def test_publication_replay_rejected(self):
    claim=GuardedFinalW.initial_claim(self.f,self.op);cert=_make_cert(self.c,claim)
    self.w.certified_publish(cert)
    with self.assertRaisesRegex(ProtocolError,'NONMONOTONIC'):self.w.certified_publish(cert)
 def test_revocation_persists_through_process_restart(self):
    self.provision();self.change('POLICY',None,active=False)
    reopened=GuardedFinalW(self.w.db_path,self.c.public_key)
    with self.assertRaisesRegex(ProtocolError,'REVOKED'):
        reopened.claim_bound(self.op.action['operation_id'],self.attempt)
    self.assertEqual(reopened.snapshot()['reserved'],2000)
 def test_restarted_valid_controller_snapshot_claims_once(self):
    self.provision()
    reopened=GuardedFinalW(self.w.db_path,self.c.public_key)
    self.assertEqual(reopened.claim_bound(self.op.action['operation_id'],self.attempt),'CLAIMED')
    self.assertEqual(reopened.claim_bound(self.op.action['operation_id'],self.attempt),'EXISTING')
 def test_revocation_rollback_on_injected_failure(self):
    self.provision()
    try:
        with self.w._tx() as c:
            c.execute("UPDATE authority SET active=0 WHERE namespace='POLICY'")
            raise RuntimeError('injected rollback')
    except RuntimeError:pass
    self.assertEqual(self.w.claim_bound(self.op.action['operation_id'],self.attempt),'CLAIMED')

if __name__=='__main__':unittest.main()
