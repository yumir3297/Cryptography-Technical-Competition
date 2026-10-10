"""Regression marker for documented security gap, not a conformance PASS."""
import tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase5.run_phase5 import prepare_cases
from research.phase6.trusted_final import Controller,ToolLedger,FinalW,_pub
from research.reference_executor.wire import b64,keyid,sid
from research.phase7.test_official_contract import ROOT

class DisclosedProtocolGap(unittest.TestCase):
    def test_reference_dispatch_fails_to_observe_post_accept_revocation(self):
        # This test PASSES if the known gap can be reproduced; it DOES NOT mean
        # dispatch revocation safety passed. The security assertion should fail.
        with tempfile.TemporaryDirectory() as d:
            f,op=prepare_cases(None,ROOT)
            ctrl=Controller.fixture();ledger=ToolLedger(Path(d)/'tool.sqlite')
            w=FinalW(Path(d)/'w.sqlite',ctrl.public_key)
            key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
            reg={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
                'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
                'public_key':b64(_pub(key)),'kid':keyid(_pub(key)),
                'epoch':'1','iat':'90','exp':'2000'}
            w.activate(ctrl.certify(f.scope,reg,1,ledger.head(),ledger.origin),ledger)
            w.accept(f,op)
            f.trusted.remove('POLICY', ['lab','tenant-1','payment'])
            self.assertFalse(f.trusted._rows[('POLICY',('lab','tenant-1','payment'))].active)
            # Known unsafe behavior: ClaimDispatch is not wired to C current-state changes.
            self.assertEqual(w.claim_bound(op.action['operation_id'],sid(501)), 'CLAIMED')
            self.assertEqual(w.accepted_operation(op.action['operation_id'])['state'],'EFFECT_UNKNOWN')

if __name__=='__main__':unittest.main()
