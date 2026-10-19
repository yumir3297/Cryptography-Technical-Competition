"""The endpoint makes its own key: generation, the widened host, and the POP.

Three claims:

* :func:`competition.client.keys.generate` writes the conventional file
  exclusively as the endpoint's own 0600 credential, refuses to replace one, and
  returns public metadata only -- the private half never leaves the machine;
* a key made here is immediately a client, and the subject and purposes it
  proposes are exactly the ones the controlled bootstrap gives that alias, so the
  proposal is checkable rather than arbitrary;
* the client signs the opaque canonical bytes an in-chain caller hands over (the
  broker envelope, E's own source attestation) and the possession message the
  repository's own enrollment contract verifies -- and refuses everything else.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from competition.client.host import answer, decode_request
from competition.client.keys import (
    ENDPOINTS, generate, key_file_name, propose_purposes, propose_subject,
)
from competition.client.signer import (
    CHAIN_DOMAIN, ENROLL_DOMAIN, SOURCE_DOMAIN, RoleSigner, role_key_path,
)
from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.support.enrollment import EnrollmentLab
from competition.support.wire import ProtocolError, b64, canonical, raw, strict_verify

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class KeyGenerationTests(unittest.TestCase):
    """One endpoint, one key: written here, kept here, published as a public only."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)

    def test_the_key_is_this_processes_own_0600_credential(self):
        metadata = generate(self.folder.name, 'IND-DEMO-1', 'U')
        path = role_key_path(self.folder.name, 'IND-DEMO-1', 'U')
        self.assertEqual(path.name, 'IND-DEMO-1-U.key')
        status = path.stat()
        self.assertEqual(status.st_uid, os.geteuid())
        self.assertEqual(status.st_mode & 0o777, 0o600)
        self.assertEqual(len(path.read_bytes()), 32)
        # Only public fields travel: the private half is not in the metadata at all.
        self.assertEqual(set(metadata),
                         {'profile', 'role', 'subject', 'public_key', 'kid', 'purposes'})

    def test_the_metadata_matches_the_written_key(self):
        metadata = generate(self.folder.name, 'MED-DEMO-1', 'X')
        signer = RoleSigner.from_directory(self.folder.name, 'MED-DEMO-1', 'X')
        self.assertEqual(metadata['public_key'], b64(signer.public))
        self.assertEqual(metadata['kid'], signer.kid)

    def test_it_refuses_to_replace_an_existing_credential(self):
        generate(self.folder.name, 'PAY-1', 'H')
        with self.assertRaises(FileExistsError):
            generate(self.folder.name, 'PAY-1', 'H')

    def test_worker_and_tool_use_the_conventional_names(self):
        self.assertEqual(key_file_name('PAY-1', 'worker'), 'W-worker.key')
        self.assertEqual(key_file_name('PAY-1', 'tool'), 'PAY-1-tool.key')
        generate(self.folder.name, 'PAY-1', 'worker')
        generate(self.folder.name, 'PAY-1', 'tool')
        self.assertTrue((Path(self.folder.name) / 'W-worker.key').exists())
        self.assertTrue((Path(self.folder.name) / 'PAY-1-tool.key').exists())

    def test_unknown_endpoints_are_refused(self):
        for profile, role, code in (('PAY-2', 'H', 'CLIENT_PROFILE'),
                                    ('PAY-1', 'C', 'CLIENT_ROLE')):
            with self.subTest(profile=profile, role=role):
                with self.assertRaises(ProtocolError) as caught:
                    generate(self.folder.name, profile, role)
                self.assertEqual(caught.exception.code, code)
        self.assertIn('tool', ENDPOINTS)


class SigningRequestTests(unittest.TestCase):
    """The client signs what it is handed, and only inside its own whitelist."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = Path(cls.work.name)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def client(self, profile='IND-DEMO-1', role='H'):
        if not role_key_path(self.keys, profile, role).exists():
            generate(self.keys, profile, role)
        return RoleSigner.from_directory(self.keys, profile, role)

    def envelope_bytes(self, client, profile):
        header = {'proto': 'ZJJ-AAP', 'version': '2.6', 'profile': profile, 'alg': 'Ed25519',
                  'type': 'Authorization', 'issuer': 'auth-x-u', 'kid': client.kid}
        return canonical([CHAIN_DOMAIN, header, {'scope': PROFILE_SCOPES[profile], 'payload': {}}])

    def test_the_bytes_are_signed_verbatim(self):
        client = self.client('IND-DEMO-1', 'U')
        data = self.envelope_bytes(client, 'IND-DEMO-1')
        strict_verify(client.public, raw(client.sign_raw('IND-DEMO-1', 'U', data), 64), data)

    def test_a_domain_outside_the_whitelist_is_refused(self):
        client = self.client('PAY-1', 'U')
        with self.assertRaises(ProtocolError) as caught:
            client.sign_raw('PAY-1', 'U', canonical([SOURCE_DOMAIN, '2.6']))
        self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')

    def test_another_binding_is_refused(self):
        client = self.client('PAY-1', 'U')
        data = self.envelope_bytes(client, 'PAY-1')
        with self.assertRaises(ProtocolError) as caught:
            client.sign_raw('MED-DEMO-1', 'U', data)
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')

    def test_a_payload_that_is_not_a_canonical_message_is_refused(self):
        client = self.client()
        cases = ((b'not json', 'MALFORMED'),
                 (b'["ZJJ-SIG-v1",{"b":"1","a":"2"}]', 'NONCANONICAL'),
                 (canonical([CHAIN_DOMAIN]), 'CLIENT_MESSAGE'),
                 (canonical({'profile': 'IND-DEMO-1'}), 'CLIENT_MESSAGE'))
        for data, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ProtocolError) as caught:
                    client.sign_raw('IND-DEMO-1', 'H', data)
                self.assertEqual(caught.exception.code, code)

    def test_e_may_sign_its_own_source_attestation(self):
        profile = 'IND-DEMO-1'
        client = self.client(profile, 'E')
        data = canonical([SOURCE_DOMAIN, '2.6', profile, 'IND_EVIDENCE',
                          PROFILE_SCOPES[profile], {'data': 'x'}, {'issuer': 'auth-x-e'}])
        strict_verify(client.public, raw(client.sign_raw(profile, 'E', data), 64), data)

    # -- possession proof ---------------------------------------------------
    def pending(self, client, profile, role, now):
        lab = EnrollmentLab(self.keys / ('lab-' + profile + '-' + role + '.sqlite'), profile)
        return lab, lab.begin(propose_subject(profile, role), b64(client.public),
                              propose_purposes(role), not_before=now, not_after=now + 1000, now=now)

    def test_the_proof_is_the_message_the_enrollment_contract_verifies(self):
        profile, role = 'PAY-1', 'U'
        client = self.client(profile, role)
        now = int(time.time())
        lab, pending = self.pending(client, profile, role, now)
        signature = client.sign_enrollment(
            profile, role,
            {k: pending[k] for k in ('tuple', 'enrollment_id', 'nonce')}, now, now + 10)
        proof = {**{k: pending[k] for k in ('tuple', 'enrollment_id', 'nonce')},
                 'iat': str(now), 'exp': str(now + 10), 'signature': signature}
        grant = lab.register(proof, now=now)
        self.assertEqual(grant['kind'], 'KEY_GRANT')
        self.assertEqual(grant['value']['subject'], propose_subject(profile, role))
        self.assertEqual(grant['value']['public_key'], b64(client.public))

    def test_a_pending_about_another_key_is_refused(self):
        profile, role = 'PAY-1', 'U'
        client, other = self.client(profile, role), self.client(profile, 'V')
        pending = {'tuple': {'scope': PROFILE_SCOPES[profile], 'public_key': b64(other.public),
                             'kid': other.kid},
                   'enrollment_id': b64(os.urandom(16)), 'nonce': b64(os.urandom(32))}
        with self.assertRaises(ProtocolError) as caught:
            client.sign_enrollment(profile, role, pending, 0, 10)
        self.assertEqual(caught.exception.code, 'CLIENT_KEY_BINDING')

    def test_a_pending_from_another_profile_is_refused(self):
        profile, role = 'PAY-1', 'U'
        client = self.client(profile, role)
        pending = {'tuple': {'scope': PROFILE_SCOPES['MED-DEMO-1'], 'public_key': b64(client.public),
                             'kid': client.kid},
                   'enrollment_id': b64(os.urandom(16)), 'nonce': b64(os.urandom(32))}
        with self.assertRaises(ProtocolError) as caught:
            client.sign_enrollment(profile, role, pending, 0, 10)
        self.assertEqual(caught.exception.code, 'CLIENT_SCOPE')

    # -- the line protocol --------------------------------------------------
    def request(self, **body):
        return json.dumps(body).encode('utf-8') + b'\n'

    def test_the_raw_op_signs_the_handed_bytes(self):
        profile, client = 'IND-DEMO-1', self.client('IND-DEMO-1', 'U')
        data = self.envelope_bytes(client, profile)
        response = answer(self.request(op='raw', profile=profile, role='U', data=b64(data)), client)
        self.assertEqual(response['domain'], CHAIN_DOMAIN)
        strict_verify(client.public, raw(response['signature'], 64), data)

    def test_the_enrollment_op_returns_one_pop_signature(self):
        profile, role = 'MED-DEMO-1', 'V'
        client = self.client(profile, role)
        now = int(time.time())
        lab, pending = self.pending(client, profile, role, now)
        response = answer(self.request(op='enrollment', profile=profile, role=role,
                                       pending={k: pending[k] for k in
                                                ('tuple', 'enrollment_id', 'nonce')},
                                       iat=str(now), exp=str(now + 10)), client)
        self.assertEqual(response['domain'], ENROLL_DOMAIN)
        message = canonical([ENROLL_DOMAIN, '2.6', pending['tuple'], pending['enrollment_id'],
                             pending['nonce'], str(now), str(now + 10)])
        strict_verify(client.public, raw(response['signature'], 64), message)

    def test_malformed_op_requests_are_refused(self):
        cases = (({'op': 'bogus', 'profile': 'p', 'role': 'r'}, 'CLIENT_OP'),
                 ({'op': 'raw', 'profile': 'p', 'role': 'r', 'data': 5}, 'CLIENT_DATA'),
                 ({'op': 'enrollment', 'profile': 'p', 'role': 'r', 'pending': [],
                   'iat': '0', 'exp': '1'}, 'CLIENT_PENDING'),
                 ({'op': 'raw', 'profile': 'p', 'role': 'r', 'data': 'AA', 'extra': 1},
                  'CLIENT_FIELDS'),
                 ({'profile': 'p', 'role': 'r', 'domain': 'd'}, 'CLIENT_FIELDS'),
                 ({'op': 'raw', 'profile': 'p', 'role': 'r', 'data': '!!'}, None))
        for body, code in cases:
            with self.subTest(body=body):
                line = self.request(**body)
                if code is None:
                    with self.assertRaises(ProtocolError) as caught:
                        answer(line, self.client())
                    self.assertEqual(caught.exception.code, 'BASE64')
                else:
                    with self.assertRaises(ProtocolError) as caught:
                        decode_request(line)
                    self.assertEqual(caught.exception.code, code)


class GeneratedKeyMatchesRosterTests(unittest.TestCase):
    """A key made here stands in for the seeded one, alias for alias."""

    @classmethod
    def setUpClass(cls):
        from competition.profiles.w_seed import initialize
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        cls.keys.cleanup()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def seeded_client(self, profile, role):
        """A client over the key the controlled bootstrap itself seeded."""
        return RoleSigner.from_directory(self.trusted.folder, profile, role)

    def generated_client(self, profile, role):
        if not role_key_path(self.keys.name, profile, role).exists():
            generate(self.keys.name, profile, role)
        return RoleSigner.from_directory(self.keys.name, profile, role)

    def test_the_proposal_equals_the_seeded_roster(self):
        for profile, roster in self.trusted.actors.items():
            for alias, actor in roster.items():
                with self.subTest(profile=profile, alias=alias):
                    self.assertEqual(propose_subject(profile, alias), actor.name)
                    self.assertEqual(set(propose_purposes(alias)), set(actor.purposes))

    def test_the_client_signs_exactly_the_bytes_the_core_itself_signs(self):
        # Over the same key file the core used, the client's message construction
        # must be the core's, byte for byte -- Ed25519 is deterministic, so an
        # equal signature is an equal message.
        fields = (('reviews', 'V'), ('authorization', 'U'), ('issue', 'H'),
                  ('permit', 'G'), ('challenge', 'X'))
        for profile in PROFILE_SCOPES:
            op = self.trusted.operations[profile]
            for name, alias in fields:
                messages = op[name] if name == 'reviews' else [op[name]]
                for message in messages:
                    with self.subTest(profile=profile, field=name):
                        data = canonical([CHAIN_DOMAIN, message['protected'], message['body']])
                        self.assertEqual(self.seeded_client(profile, alias).sign_raw(profile, alias, data),
                                         message['sig'])

    def test_a_generated_key_signs_the_same_message_shape(self):
        for profile in PROFILE_SCOPES:
            op = self.trusted.operations[profile]
            message = op['authorization']
            data = canonical([CHAIN_DOMAIN, message['protected'], message['body']])
            client = self.generated_client(profile, 'U')
            self.assertNotEqual(client.kid, message['protected']['kid'])
            strict_verify(client.public, raw(client.sign_raw(profile, 'U', data), 64), data)

    def test_the_client_reproduces_the_seeded_e_source_signature(self):
        # PAY-1 carries its E evidence as a full envelope, so the client's
        # signature can be compared byte for byte with the seeded one.
        with self.trusted.store.db() as c:
            record = self.trusted.store.current(
                c, 'PAY-1', 'ORDER', prefix('PAY-1') + ['ord', 'pay'])['record']
        envelope = record['value']['source_envelope']
        data = canonical([CHAIN_DOMAIN, envelope['protected'], envelope['body']])
        self.assertEqual(self.seeded_client('PAY-1', 'E').sign_raw('PAY-1', 'E', data),
                         envelope['sig'])


if __name__ == '__main__':
    unittest.main()
