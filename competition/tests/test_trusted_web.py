"""The trusted entry: a session in front, the minimal interface behind, nothing else.

Five claims:

* the caller list is configuration, and its rules are the roster's rules: the key
  id is re-derived from the public key rather than read, the curve point must be
  real, and the sides must be names this repository actually has;
* a session proves the caller's own key once and then carries a token, and every
  refusal says which rule failed -- an unknown caller, a replayed challenge, a
  stale one, a missing or expired token, and a caller reaching for a side of the
  flow it was not allowed;
* the two sides really are two sides: the repository's own ``STEPS`` table says
  who signs each step, and a session allowed ``H`` cannot drive ``exec`` any more
  than one allowed ``worker`` can submit;
* the entry is a transport and not a signer: a whole flow runs through it with
  the signatures travelling in the body, and a caller cannot state a role, a key
  or a test switch because no body has a field for one;
* what the interface reference rules out is not published: initialization,
  enrollment, ``counts`` and the internal read steps have no route at all.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.export import forbidden_secrets
from competition.server.service import STEPS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import (
    ProtocolError, b64, canonical, keyid, raw, strict_verify,
)
from competition.tests.endpoint_face import Face, body
from competition.web.app import make_app
from competition.web.session import (
    CHALLENGE_TTL, SESSION_DOMAIN, SESSION_TTL, Sessions, read_callers,
)

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


def public_of(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def make_callers(folder, specs):
    """Write one caller credential per spec and the list that names them."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    entries, keys = [], {}
    for name, sides in specs:
        key = Ed25519PrivateKey.generate()
        keys[name] = key
        entries.append({'name': name, 'public_key': b64(public_of(key)), 'sides': list(sides)})
    path = folder / 'callers.json'
    path.write_text(json.dumps(entries), encoding='utf-8')
    return path, keys


def caller_of(key):
    """One caller key, with the one thing it does: answer its own session."""
    return {'kid': keyid(public_of(key)),
            'sign': lambda claim: b64(key.sign(canonical([SESSION_DOMAIN, claim])))}


class CallerListTests(unittest.TestCase):
    """The caller list is configuration, held to the roster's own rules."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'callers.json'

    def entry(self, **overrides):
        entry = {'name': 'caller-h', 'public_key': b64(public_of(Ed25519PrivateKey.generate())),
                 'sides': ['H']}
        entry.update(overrides)
        return entry

    def code(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(ProtocolError) as caught:
            read_callers(self.path)
        return caught.exception.code

    def test_a_valid_list_is_read_with_the_kid_re_derived(self):
        entry = self.entry()
        callers = read_callers(self._write([entry]))
        self.assertEqual(list(callers), [keyid(raw(entry['public_key'], 32))])
        self.assertEqual(callers[keyid(raw(entry['public_key'], 32))]['name'], 'caller-h')
        self.assertEqual(callers[keyid(raw(entry['public_key'], 32))]['sides'], ('H',))
        self.assertEqual(set(callers[keyid(raw(entry['public_key'], 32))]),
                         {'name', 'pub', 'kid', 'sides'})

    def _write(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')
        return self.path

    def test_the_key_id_is_never_read_from_the_file(self):
        # A self-reported id is not an input: only the public key is, and the id
        # follows from it exactly as it does for an endpoint's manifest line.
        self.assertEqual(self.code([self.entry(kid='not-a-real-kid')]), 'SESSION_CALLERS')

    def test_malformed_lists_are_refused(self):
        cases = (([], 'SESSION_CALLERS'),
                 ({'name': 'x'}, 'SESSION_CALLERS'),
                 ([self.entry(sides=[])], 'SESSION_SIDES'),
                 ([self.entry(sides=['H', 'H'])], 'SESSION_SIDES'),
                 ([self.entry(sides=['C'])], 'SESSION_SIDES'),
                 ([self.entry(name='a b')], 'SESSION_CALLERS'),
                 ([self.entry(), self.entry()], 'SESSION_CALLERS'),
                 ([self.entry(public_key=b64(bytes(32)))], 'PUBLIC_KEY_POINT'))
        for value, code in cases:
            with self.subTest(code=code):
                self.assertEqual(self.code(value), code)
        self.path.write_text('not json', encoding='utf-8')
        with self.assertRaises(ProtocolError) as caught:
            read_callers(self.path)
        self.assertEqual(caught.exception.code, 'SESSION_CALLERS')

    def test_one_key_listed_twice_is_refused(self):
        public = b64(public_of(Ed25519PrivateKey.generate()))
        self.assertEqual(self.code([self.entry(public_key=public),
                                    self.entry(name='caller-worker', public_key=public)]),
                         'SESSION_CALLERS')


class SessionTests(unittest.TestCase):
    """Prove the caller's key once, then carry a token -- with time as an input."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.clock = [1000]
        self.path, self.keys = make_callers(
            self.folder.name, [('caller-h', ['H']), ('caller-worker', ['worker'])])
        self.sessions = Sessions(read_callers(self.path), now=lambda: self.clock[0])
        self.h = caller_of(self.keys['caller-h'])
        self.w = caller_of(self.keys['caller-worker'])

    def open(self, caller):
        claim = self.sessions.challenge(caller['kid'])
        return claim, caller['sign'](claim)

    def test_a_proven_key_opens_a_session_and_the_token_authorizes(self):
        claim, signature = self.open(self.h)
        self.assertEqual((claim['caller'], claim['domain']), ('caller-h', SESSION_DOMAIN))
        self.assertEqual(claim['exp'], str(self.clock[0] + CHALLENGE_TTL))
        opened = self.sessions.open(claim, signature)
        self.assertEqual((opened['caller'], opened['sides']), ('caller-h', ['H']))
        self.assertEqual(opened['expires'], str(self.clock[0] + SESSION_TTL))
        self.assertEqual(self.sessions.authorize(opened['token'])['name'], 'caller-h')

    def test_an_unknown_caller_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            self.sessions.challenge('nobody')
        self.assertEqual(caught.exception.code, 'SESSION_CALLER')

    def test_a_signature_from_another_key_is_refused(self):
        claim, _ = self.open(self.h)
        with self.assertRaises(ProtocolError) as caught:
            self.sessions.open(claim, self.w['sign'](claim))
        self.assertEqual(caught.exception.code, 'BAD_SIGNATURE')

    def test_a_challenge_is_single_use(self):
        claim, signature = self.open(self.h)
        self.sessions.open(claim, signature)
        with self.assertRaises(ProtocolError) as caught:
            self.sessions.open(claim, signature)
        self.assertEqual(caught.exception.code, 'SESSION_CHALLENGE')

    def test_a_claim_that_was_never_handed_out_is_refused(self):
        claim, signature = self.open(self.h)
        for changed in ({**claim, 'nonce': b64(os.urandom(32))},
                        {**claim, 'exp': str(self.clock[0] + 9999)},
                        {**claim, 'domain': 'ZJJ-SIG-v1'},
                        {**claim, 'caller': 'somebody-else'}):
            with self.subTest(changed=changed['domain']):
                with self.assertRaises(ProtocolError):
                    self.sessions.open(changed, signature)

    def test_a_wrong_field_set_is_refused(self):
        claim, signature = self.open(self.h)
        for changed in ({k: v for k, v in claim.items() if k != 'nonce'},
                        {**claim, 'extra': '1'}):
            with self.subTest(fields=len(changed)):
                with self.assertRaises(ProtocolError) as caught:
                    self.sessions.open(changed, signature)
                self.assertEqual(caught.exception.code, 'SESSION_FIELDS')

    def test_a_stale_challenge_is_refused(self):
        claim, signature = self.open(self.h)
        self.clock[0] += CHALLENGE_TTL + 1
        with self.assertRaises(ProtocolError) as caught:
            self.sessions.open(claim, signature)
        self.assertEqual(caught.exception.code, 'SESSION_EXPIRED')

    def test_a_stale_token_is_refused(self):
        claim = self.sessions.challenge(self.h['kid'])
        token = self.sessions.open(claim, self.h['sign'](claim))['token']
        self.clock[0] += SESSION_TTL + 1
        with self.assertRaises(ProtocolError) as caught:
            self.sessions.authorize(token)
        self.assertEqual(caught.exception.code, 'SESSION_EXPIRED')

    def test_a_token_that_was_never_issued_is_refused(self):
        for token in ('', 'not-a-token', None):
            with self.subTest(token=token):
                with self.assertRaises(ProtocolError) as caught:
                    self.sessions.authorize(token)
                self.assertEqual(caught.exception.code, 'SESSION_REQUIRED')

    def test_a_session_may_only_drive_the_sides_it_was_allowed(self):
        claim, signature = self.open(self.h)
        h = self.sessions.open(claim, signature)['token']
        claim, signature = self.open(self.w)
        w = self.sessions.open(claim, signature)['token']
        self.sessions.authorize(h, 'H')
        self.sessions.authorize(w, 'worker')
        self.sessions.authorize(h, None)
        for token, side in ((h, 'worker'), (w, 'H')):
            with self.subTest(side=side):
                with self.assertRaises(ProtocolError) as caught:
                    self.sessions.authorize(token, side)
                self.assertEqual(caught.exception.code, 'SESSION_SIDE')


class TrustedEntryTests(unittest.TestCase):
    """The entry over one initialized W: the interface, plus a session in front."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.service = TrustedService(cls.trusted, LocalSigner(cls.trusted))
        cls.callers_path, cls.callers = make_callers(
            Path(cls.work.name) / 'callers', [('caller-h', ['H']), ('caller-worker', ['worker'])])
        cls.sessions = Sessions(read_callers(cls.callers_path))
        cls.face = Face(make_app(cls.service, cls.sessions))

    @classmethod
    def tearDownClass(cls):
        cls.face.close()
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def session(self, name):
        """One live session token, opened the way a caller opens one."""
        caller = caller_of(self.callers[name])
        reply = self.face.post('/session', body(kid=caller['kid']))
        self.assertEqual(reply.status_code, 200)
        challenge = reply.json()['challenge']
        opened = self.face.post('/session/prove',
                                body(claim=challenge, signature=caller['sign'](challenge)))
        self.assertEqual(opened.status_code, 200)
        return opened.json()['token']

    def proof(self, profile, step, claim):
        """The proof the endpoint that signs that step would return."""
        role, domain = STEPS[step][2], STEPS[step][3]
        key = (self.trusted.worker_key if role == 'worker'
               else self.trusted.actors[profile][role].key)
        return {'claim': claim, 'signature': b64(key.sign(canonical([domain, claim])))}

    def post(self, path, payload, token=None):
        headers = None if token is None else {'authorization': 'Bearer ' + token}
        return self.face.post(path, payload, headers)

    def read(self, path, token=None):
        headers = None if token is None else {'authorization': 'Bearer ' + token}
        return self.face.get(path, headers)

    def test_healthz_needs_no_session_and_says_nothing_else(self):
        self.assertEqual(self.read('/healthz').json(), {'ok': True})

    def test_an_unknown_caller_cannot_open_a_session(self):
        reply = self.post('/session', body(kid='nobody'))
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'SESSION_CALLER'})

    def test_every_api_route_needs_a_session(self):
        cases = (('/api/submit', body(profile='PAY-1', intent=None)),
                 ('/api/challenge', body(operation_id='o', step='prepare')),
                 ('/api/prove', body(operation_id='o', step='prepare', proof={})))
        for path, payload in cases:
            with self.subTest(path=path):
                reply = self.post(path, payload)
                self.assertEqual(reply.status_code, 401)
                self.assertEqual(reply.json(), {'deny': 'SESSION_REQUIRED'})
        self.assertEqual(self.read('/api/package').status_code, 401)

    def test_a_whole_flow_runs_through_the_entry_with_two_sides(self):
        profile = 'PAY-1'
        h, w = self.session('caller-h'), self.session('caller-worker')
        submitted = self.post('/api/submit', body(profile=profile, intent=None), h).json()
        oid = submitted['operation_id']
        self.assertIn('challenge', submitted)
        for step, token in (('prepare', h), ('accept', h), ('claim', w), ('exec', w),
                            ('settle', w), ('status', h)):
            with self.subTest(step=step):
                asked = self.post('/api/challenge', body(operation_id=oid, step=step),
                                  token).json()
                self.assertEqual((asked['role'], asked['domain']),
                                 (STEPS[step][2], STEPS[step][3]))
                proved = self.post('/api/prove',
                                   body(operation_id=oid, step=step,
                                        proof=self.proof(profile, step, asked['claim'])), token)
                self.assertEqual(proved.status_code, 200, proved.text)
                if step == 'settle':
                    self.assertEqual(proved.json()['state'], 'SETTLED')
                if step == 'status':
                    self.assertEqual(proved.json()['acceptance_state'], 'COMMITTED')

    def test_a_session_cannot_drive_the_other_side(self):
        profile = 'PAY-1'
        h, w = self.session('caller-h'), self.session('caller-worker')
        oid = self.post('/api/submit', body(profile=profile, intent=None),
                        h).json()['operation_id']
        for token, payload in ((h, body(operation_id=oid, step='exec')),
                               (w, body(operation_id=oid, step='accept'))):
            with self.subTest(step=payload.decode()):
                reply = self.post('/api/challenge', payload, token)
                self.assertEqual(reply.status_code, 403)
                self.assertEqual(reply.json(), {'deny': 'SESSION_SIDE'})
        reply = self.post('/api/submit', body(profile=profile, intent=None), w)
        self.assertEqual(reply.json(), {'deny': 'SESSION_SIDE'})

    def test_a_caller_cannot_state_its_own_role_key_or_a_test_switch(self):
        profile, h = 'PAY-1', self.session('caller-h')
        oid = self.post('/api/submit', body(profile=profile, intent=None),
                        h).json()['operation_id']
        for path, payload in (
                ('/api/submit', body(profile=profile, intent=None, role='H')),
                ('/api/submit', body(profile=profile, intent=None, kid='x')),
                ('/api/submit', body(profile=profile, intent=None, crash_after_commit=True)),
                ('/api/challenge', body(operation_id=oid, step='prepare', role='H')),
                ('/api/challenge', body(operation_id=oid, step='prepare', kid='x')),
                ('/api/prove', body(operation_id=oid, step='prepare', proof={}, role='worker')),
                ('/api/prove', body(operation_id=oid, step='prepare', proof={},
                                    crash_after_commit=True))):
            with self.subTest(path=payload.decode()[:24]):
                self.assertEqual(self.post(path, payload, h).json(), {'deny': 'WEB_FIELDS'})

    def test_what_the_interface_reference_rules_out_has_no_route(self):
        for path in ('/api/init', '/api/counts', '/api/identities', '/api/enroll',
                     '/api/result', '/api/export', '/api/verify', '/api/roster',
                     '/api/sign', '/api/step', '/api/auto'):
            with self.subTest(path=path):
                self.assertEqual(self.read(path).status_code, 404)
                self.assertIn(self.post(path, body()).status_code, (404, 405))

    def test_an_authenticated_caller_may_read_the_public_package(self):
        package = self.read('/api/package', self.session('caller-h')).json()
        self.assertEqual(package['kind'], 'competition_public_package')
        self.assertEqual(sorted(package['actors']), sorted(PROFILE_SCOPES))
        self.assertEqual(forbidden_secrets(package), [])

    def test_a_malformed_or_over_sized_body_is_refused(self):
        for payload, code in ((b'not json', 'WEB_MALFORMED'),
                              (body(), 'WEB_FIELDS'),
                              (body(profile='PAY-1', intent=None, extra='1'), 'WEB_FIELDS'),
                              (b'x' * (1 << 17), 'WEB_SIZE')):
            with self.subTest(code=code):
                reply = self.post('/api/submit', payload, self.session('caller-h'))
                self.assertEqual(reply.status_code, 403)
                self.assertEqual(reply.json(), {'deny': code})

    def test_a_stale_token_is_refused(self):
        token = self.session('caller-h')
        original = self.sessions.now
        self.sessions.now = lambda: time.time() + SESSION_TTL * 2
        try:
            reply = self.post('/api/submit', body(profile='PAY-1', intent=None), token)
            self.assertEqual(reply.status_code, 401)
            self.assertEqual(reply.json(), {'deny': 'SESSION_EXPIRED'})
        finally:
            self.sessions.now = original

    def test_the_entry_carries_a_proof_and_does_not_make_one(self):
        # The signature in the body is the endpoint's; the entry neither produces
        # it nor is able to.  A forged proof is refused by the black box, which is
        # where every business signature is checked.
        profile, h = 'PAY-1', self.session('caller-h')
        oid = self.post('/api/submit', body(profile=profile, intent=None),
                        h).json()['operation_id']
        asked = self.post('/api/challenge', body(operation_id=oid, step='prepare'), h).json()
        forged = {'claim': asked['claim'], 'signature': b64(bytes(64))}
        reply = self.post('/api/prove', body(operation_id=oid, step='prepare', proof=forged), h)
        self.assertEqual(reply.status_code, 403)
        self.assertIn(reply.json()['deny'], ('SIGNATURE_ENCODING', 'BAD_SIGNATURE'))


if __name__ == '__main__':
    unittest.main()
