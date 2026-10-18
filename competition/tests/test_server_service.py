"""Trusted service: the challenge/signature interface, answered locally this round.

The tests assert the local fallback satisfies the ``Signer`` protocol; that every
operation really is "challenge handed out -> proof returned"; and that a proof
made with the wrong role's key is rejected -- i.e. the interface, not the shell,
decides what a caller may sign.
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

    def _op(self, profile):
        base = self.trusted_run.operations[profile]
        return self.service.build_op(profile, base['action'], base['task_id'], base['scene_key'])

    def test_local_signer_satisfies_the_protocol(self):
        self.assertIsInstance(self.signer, Signer)

    def test_interface_is_challenge_then_proof(self):
        profile = 'PAY-1'
        op = self._op(profile)
        claim = self.service.challenge(profile, op)
        proof = self.service.answer(profile, 'H', GUARD_DOMAIN, claim)
        ticket = self.service.prepare(profile, op, proof)
        self.assertEqual(ticket['operation_id'], op['action']['operation_id'])

    def test_wrong_role_proof_is_rejected(self):
        profile = 'IND-DEMO-1'
        op = self._op(profile)
        claim = self.service.challenge(profile, op)
        # The worker key is the wrong key/domain for the H GUARD challenge.
        proof = self.service.answer(profile, 'worker', GUARD_DOMAIN, claim)
        with self.assertRaises(Exception):
            self.service.prepare(profile, op, proof)


if __name__ == '__main__':
    unittest.main()
