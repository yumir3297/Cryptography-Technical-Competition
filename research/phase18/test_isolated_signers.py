"""Phase18 Linux-user DAC signer/key-isolation acceptance tests.

Supply PHASE18_LAB_PATH, the successfully completed run directory. These
tests do NOT re-provision keys, nor do they use signer private key bytes.
"""
import os,sqlite3,unittest
from pathlib import Path
from research.phase18.process_flow import (
  ROLE_USERS,RemoteEd25519,check_permissions,manifest,load,db,tool_path,public_for,
)
from research.reference_executor.wire import canonical,ProtocolError,require

class LinuxSignerBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=Path(os.environ['PHASE18_LAB_PATH']).resolve()
        cls.r=load(cls.base/'phase18_process_report.json')
        cls.witness=load(manifest(cls.base))

    def test_signer_key_os_dac_and_sibling_isolation(self):
        evidence=check_permissions(self.base)
        self.assertTrue(evidence['unprivileged_W_cannot_read'])
        self.assertTrue(evidence['other_roles_cannot_read'])
        self.assertEqual(evidence['roles_verified'],8)

    def test_w_can_not_replace_key_and_cannot_read_privileged_key(self):
        directory=self.base/'signers'
        self.assertEqual(directory.stat().st_uid,0)
        self.assertEqual(directory.stat().st_mode&0o777,0o711)
        for role in ROLE_USERS:
            with self.assertRaises(PermissionError):
                (directory/f'{role}.key').read_bytes()
        with self.assertRaises(PermissionError):
            (directory/'E.key').unlink()

    def test_broker_rejects_wrong_signature_domain(self):
        e=RemoteEd25519(self.base,'E')
        with self.assertRaises(ProtocolError) as ctx:
            e.sign(canonical(['ZJJ-SIG-v1',{'type':'Permit'},{}]))
        self.assertEqual(ctx.exception.code,'BROKER_REJECTED_E')

    def test_broker_rejects_wrong_actor_even_right_domain(self):
        x=RemoteEd25519(self.base,'X')
        with self.assertRaises(ProtocolError) as ctx:
            x.sign(canonical(['ZJJ-SIG-v1',{'issuer':'pilot-g',
                  'kid':self.witness['fixture_actor_public']['G']['kid'],
                  'profile':'IND-DEMO-1','proto':'ZJJ-AAP','version':'2.6',
                  'type':'Permit','alg':'Ed25519'},{}]))
        self.assertEqual(ctx.exception.code,'BROKER_REJECTED_X')

    def test_c_broker_rejects_unapproved_domain(self):
        c=RemoteEd25519(self.base,'C')
        with self.assertRaises(ProtocolError) as ctx:
            c.sign(canonical(['OTHER_PROTOCOL',{}]))
        self.assertEqual(ctx.exception.code,'BROKER_REJECTED_C')

    def test_minimal_ind_closure_with_remote_signers(self):
        a=self.r['readonly_audit']
        self.assertEqual(self.r['stage_count'],25)
        self.assertEqual(a['W_accept_count'],1)
        self.assertEqual(a['W_call_count'],1)
        self.assertEqual(a['W_settlement_count'],1)
        self.assertEqual(a['durable_effects'],1)
        self.assertTrue(a['recovery_no_second_effect'])
        self.assertTrue(a['forged_E_rejected'] and a['forged_X_rejected'] and a['forged_W_rejected'])
        signers={x['role'] for x in self.r['public_signer_receipts']}
        self.assertTrue({'C','E','H','G','X','U','TOOL'}.issubset(signers))
        self.assertTrue(all(x['signature_verified'] for x in self.r['public_signer_receipts']))

    def test_db_effect_unique(self):
        with sqlite3.connect(tool_path(self.base)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM finalized').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM p16_authenticated_delivery').fetchone()[0],1)
        with sqlite3.connect(db(self.base)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM r2_settled').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM p16_outbox').fetchone()[0],1)

if __name__=='__main__':unittest.main()
