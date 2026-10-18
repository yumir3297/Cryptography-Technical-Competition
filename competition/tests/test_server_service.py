"""Trusted service: the minimal three-message interface, answered locally here.

The tests assert the local fallback satisfies the ``Signer`` protocol; that
``submit`` returns an operation handle plus the first core challenge; that only
business intent is accepted; that every later move really is "challenge handed
out -> proof returned"; and that a proof made with the wrong role's key is
rejected -- i.e. the interface, not the shell, decides what a caller may sign.
"""
import os
import tempfile
import unittest
from pathlib import Path

from competition.server.service import GUARD_DOMAIN, TrustedService
from competition.server.signer import LocalSigner, Signer


class ServerServiceTests(unittest.TestCase):
    trusted_run = None
    signer = None
    service = None

    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        from competition.profiles.w_seed import initialize
        if type(self).trusted_run is None:
            type(self).trusted_run = initialize(Path(self.folder.name) / 'w')
            type(self).signer = LocalSigner(type(self).trusted_run)
            type(self).service = TrustedService(type(self).trusted_run, type(self).signer)

    def test_local_signer_satisfies_the_protocol(self):
        self.assertIsInstance(self.signer, Signer)

    def test_submit_returns_operation_and_first_challenge(self):
        submitted = self.service.submit('PAY-1')
        self.assertIn('operation_id', submitted)
        self.assertEqual(submitted['challenge']['profile'], 'PAY-1')
        self.assertEqual(submitted['challenge']['stage'], 'GUARD')

    def test_intent_takes_only_business_fields(self):
        # ``tool`` is a bound field, never caller intent.
        with self.assertRaises(Exception):
            self.service.submit('PAY-1', {'tool': 'evil'})

    def test_interface_is_challenge_then_proof(self):
        submitted = self.service.submit('PAY-1')
        operation_id = submitted['operation_id']
        proof = self.service.answer('PAY-1', 'H', GUARD_DOMAIN, submitted['challenge'])
        ticket = self.service.prove(operation_id, 'prepare', proof)
        self.assertEqual(ticket['operation_id'], operation_id)

    def test_wrong_role_proof_is_rejected(self):
        submitted = self.service.submit('IND-DEMO-1')
        # The worker key is the wrong key/domain for the H GUARD challenge.
        proof = self.service.answer('IND-DEMO-1', 'worker', GUARD_DOMAIN, submitted['challenge'])
        with self.assertRaises(Exception):
            self.service.prove(submitted['operation_id'], 'prepare', proof)

    def test_unknown_operation_is_refused(self):
        with self.assertRaises(Exception):
            self.service.challenge('not-an-operation', 'status')


if __name__ == '__main__':
    unittest.main()
