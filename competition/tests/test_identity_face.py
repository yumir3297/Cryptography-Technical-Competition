"""Identity face: enrollment hands out a pending and publishes the grants.

The caller supplies only a subject; the public key, key id and purposes come
from the roster, and every hard constraint -- POP signature, proof/key windows,
``ROSTER_BINDING`` -- is decided by the black box.  These tests drive the two
moves the interface exposes (``enroll`` -> ``enroll_register``) with the local
proof fallback, assert the grants really land in W, and confirm the refusals:
bad signature, a tampered tuple, a non-roster subject, an expired window and a
replayed enrollment id.
"""
import contextlib
import copy
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from competition.cli.app import Session
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import ProtocolError, b64, canonical


class IdentityFaceTests(unittest.TestCase):
    trusted_run = None
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
            type(self).service = TrustedService(type(self).trusted_run, LocalSigner(type(self).trusted_run))
        self.run = type(self).trusted_run
        self.service = type(self).service

    # -- helpers ------------------------------------------------------------
    def _pending(self, profile, alias):
        subject = self.run.actors[profile][alias].name
        return subject, self.service.enroll(profile, subject)

    def _proof(self, profile, subject, pending, iat=None, exp=None):
        now = int(time.time())
        return self.service.enroll_proof(profile, subject, pending, now if iat is None else iat,
                                         now + 60 if exp is None else exp)

    def _reject(self, profile, proof, code):
        with self.assertRaises(ProtocolError) as caught:
            self.service.enroll_register(profile, proof)
        self.assertEqual(caught.exception.code, code)

    # -- 1. happy path ------------------------------------------------------
    def test_enroll_then_register_publishes_key_and_role(self):
        profile, alias = 'PAY-1', 'U'
        subject, pending = self._pending(profile, alias)
        self.assertEqual(set(pending), {'tuple', 'enrollment_id', 'nonce'})
        actor = self.run.actors[profile][alias]
        self.assertEqual(pending['tuple']['subject'], subject)
        self.assertEqual(pending['tuple']['public_key'], b64(actor.pub))
        self.assertEqual(pending['tuple']['kid'], actor.kid)

        grant = self.service.enroll_register(profile, self._proof(profile, subject, pending))
        self.assertEqual(grant['kind'], 'KEY_GRANT')
        self.assertEqual((grant['profile'], grant['value']['subject']), (profile, subject))

        from competition.core.trusted_state import ROLES, prefix
        with self.run.store.db() as c:
            key = self.run.store.current(c, profile, 'KEY', [actor.kid])
            role = self.run.store.current(c, profile, 'ROLE', prefix(profile) + [subject, ROLES[profile][alias]])
        self.assertEqual(key['record']['value']['subject'], subject)
        self.assertEqual(key['record']['value']['public_key'], b64(actor.pub))
        self.assertEqual(role['record']['value']['role'], ROLES[profile][alias])
        # Key and role really are current, authenticated W records.
        self.assertEqual(key['record']['value']['epoch'], str(key['revision']))
        self.assertEqual(role['record']['value']['epoch'], str(role['revision']))

    # -- 2. component refusals ---------------------------------------------
    def test_wrong_signature_is_rejected(self):
        profile, alias = 'PAY-1', 'X'
        subject, pending = self._pending(profile, alias)
        proof = self._proof(profile, subject, pending)
        message = canonical(['ZJJ-ENROLL-v1', '2.6', proof['tuple'], proof['enrollment_id'],
                             proof['nonce'], proof['iat'], proof['exp']])
        proof['signature'] = b64(self.run.actors[profile]['V'].key.sign(message))
        self._reject(profile, proof, 'BAD_SIGNATURE')

    def test_tampered_tuple_is_rejected(self):
        profile, alias = 'PAY-1', 'G'
        subject, pending = self._pending(profile, alias)
        other = self.run.actors[profile]['V']

        forged_key = copy.deepcopy(self._proof(profile, subject, pending))
        forged_key['tuple']['public_key'] = b64(other.pub)
        self._reject(profile, forged_key, 'POP_BINDING')

        forged_purpose = copy.deepcopy(self._proof(profile, subject, pending))
        forged_purpose['tuple']['purposes'] = sorted(set(forged_purpose['tuple']['purposes']) | {'SOURCE'})
        self._reject(profile, forged_purpose, 'POP_BINDING')

    def test_non_roster_subject_is_rejected(self):
        with self.assertRaises(ProtocolError) as caught:
            self.service.enroll('PAY-1', 'not-a-roster-subject')
        self.assertEqual(caught.exception.code, 'ROSTER_BINDING')

    def test_expired_window_and_replayed_enrollment_are_rejected(self):
        # The proof window itself is refused by the core's POP window check.
        profile, alias = 'MED-DEMO-1', 'H'
        subject, pending = self._pending(profile, alias)
        past = int(time.time())
        self._reject(profile, self._proof(profile, subject, pending, iat=past - 120, exp=past - 60), 'EXPIRED')

        # The pending table's own lifetime is refused before any publish.
        _, stale = self._pending(profile, alias)
        self.service._registry()._pending[stale['enrollment_id']]['expires'] = past - 1
        self._reject(profile, self._proof(profile, subject, stale), 'ENROLLMENT_EXPIRED')

        # A consumed enrollment id cannot be replayed.
        profile, alias = 'IND-DEMO-1', 'U'
        subject, pending = self._pending(profile, alias)
        proof = self._proof(profile, subject, pending)
        self.service.enroll_register(profile, proof)
        self._reject(profile, proof, 'ENROLLMENT_CONSUMED')


class IdentityCliTests(unittest.TestCase):
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

    def test_session_identity_commands(self):
        session = Session()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                session.cmd_init([str(Path(self.folder.name) / 'w')])
                session.cmd_use(['MED-DEMO-1'])
                subject = session.run.actors['MED-DEMO-1']['U'].name
                session.cmd_identities([])
                session.cmd_enroll([subject])
                session.cmd_enroll_register([subject])
            finally:
                if session.run is not None:
                    session.run.close()
        out = buffer.getvalue()
        self.assertIn(subject, out)
        self.assertIn('KEY_GRANT', out)
        self.assertIn('enrollment_id', out)


if __name__ == '__main__':
    unittest.main()
