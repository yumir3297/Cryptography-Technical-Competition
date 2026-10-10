"""Phase17 independently generated IND minimal closed-loop regression tests."""
from __future__ import annotations
import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase17.process_flow import orchestrate,verifier,key,manifest,db,tool_path
from research.phase11.trusted_clock import checked_clock
from research.reference_executor.wire import ProtocolError,b64

class MinimumLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.dir=Path(cls.tmp.name)/'minimum';cls.report=orchestrate(cls.dir)
        cls.witness=json.loads(manifest(cls.dir).read_text())

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_ind_evidence_through_settlement(self):
        a=self.report['readonly_audit']
        self.assertEqual(self.report['stage_count'],25)
        self.assertEqual(a['W_accept_count'],1)
        self.assertEqual(a['W_call_count'],1)
        self.assertEqual(a['W_settlement_count'],1)
        self.assertEqual(a['W_reserved_after'],0)
        self.assertEqual(a['W_spent_after'],1)
        self.assertEqual(a['durable_effects'],1)

    def test_e_x_w_negative_signatures_fail_closed(self):
        a=self.report['readonly_audit']
        self.assertTrue(a['forged_E_rejected'])
        self.assertTrue(a['forged_X_rejected'])
        self.assertTrue(a['forged_W_rejected'])
        self.assertTrue(a['recovery_no_second_effect'])
        self.assertTrue(self.witness['replay']['unchanged'])

    def test_real_random_role_keys_but_no_separate_os_id(self):
        pubs=[self.witness['fixture_root_public'],self.witness['w_delivery_public'],
              self.witness['tool_public']]+[x['pub'] for x in self.witness['fixture_actor_public'].values()]
        self.assertEqual(len(pubs),len(set(pubs)))
        self.assertFalse(self.report['readonly_audit']['real_independent_OS_identity_custody'])
        for name in ('C','E','H','G','X','U','V','TOOL','WTOOL'):
            self.assertEqual(len(key(self.dir,name).private_bytes_raw()),32)
            if os.name=='posix':
                self.assertEqual((self.dir/'signers'/f'{name}.key').stat().st_mode&0o777,0o600)

    def test_w_runtime_owns_no_controller_source_or_x_signer(self):
        w=verifier(self.dir,self.witness)
        self.assertFalse(hasattr(w.controller,'sign'))
        self.assertTrue(all(not hasattr(a,'key') for a in w.actors.values()))
        with self.assertRaises(ProtocolError):w.sign_evidence({},at=100)
        with self.assertRaises(ProtocolError):w.certify('POLICY',[],{})

    def test_tool_state_one_original_simulated_effect(self):
        with sqlite3.connect(tool_path(self.dir)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM finalized').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM p16_authenticated_delivery').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT seq FROM meta WHERE id=1').fetchone()[0],1)
        with sqlite3.connect(db(self.dir)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM p16_outbox').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM r2_settled').fetchone()[0],1)

    def test_wrong_clock_issuer_denied(self):
        from research.phase11.trusted_clock import seal
        from research.phase6.trusted_final import Controller
        w=verifier(self.dir,self.witness)
        other=Controller(Ed25519PrivateKey.generate())
        cert=seal(other,'IND-DEMO-1',self.witness['scope'],
                  self.witness['operation_id'],'INDEPENDENT-TEST',100,115,115)
        with w.db() as c:
            with self.assertRaises(ProtocolError) as cm:
                checked_clock(c,cert,w.root_public,'IND-DEMO-1',w.scope,
                              self.witness['operation_id'],'INDEPENDENT-TEST')
        self.assertEqual(cm.exception.code,'BAD_SIGNATURE')

if __name__=='__main__':unittest.main()
