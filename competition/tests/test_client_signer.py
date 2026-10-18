"""The signing face: one external client per role, one key each, one whitelist.

The tests pin down the three claims that make the face worth having:

* a role client answers only the domains its role may sign, only for the one
  profile and role it was built with, and only with a key file it owns as 0600;
* the line protocol carries one request in and one response out, and a refused
  request stops the host instead of being skipped;
* with :class:`RoleSigner` clients injected, the trusted service and the whole
  in-chain signing path run unchanged -- the fresh chain built by ``submit`` is
  signed by the external clients, and a client using another role's key is still
  rejected by the trusted side, which trusts its own roster and not the caller.
"""
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from competition.client.host import MAX_REQUEST_LINE, answer, decode_request, serve_connection, serve_unix
from competition.client.signer import (
    CHAIN_DOMAIN, ENROLL_DOMAIN, ROLE_DOMAINS, SOURCE_DOMAIN, RoleSigner, role_key_path,
)
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.service import (
    ACCEPT_DOMAIN, GUARD_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN, WORKER_DOMAIN, TrustedService,
)
from competition.server.signer import LocalSigner, Signer
from competition.support.wire import ProtocolError, canonical, raw, strict_verify

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
RUN = None
FOLDER = None
KEYS = None
_TEMP = None
_ENV = {}


def setUpModule():
    global RUN, FOLDER, KEYS, _TEMP
    TEMP_ROOT.mkdir(exist_ok=True)
    _TEMP = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
    FOLDER = Path(_TEMP.name)
    for name in ('TMP', 'TEMP'):
        _ENV[name] = os.environ.get(name)
        os.environ[name] = str(TEMP_ROOT)
    RUN = initialize(FOLDER / 'w')
    # The seed writes every role key inside the run folder it was given.
    KEYS = RUN.folder


def tearDownModule():
    RUN.close()
    _TEMP.cleanup()
    for name, value in _ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class RoleClients:
    """Independent per-role signing clients on one machine, routed like a roster.

    Each entry is its own :class:`RoleSigner` holding its own key file; the
    router only records what was asked so a test can tell which client answered.
    """

    def __init__(self, folder, roles=('H', 'U', 'V', 'G', 'X', 'worker'),
                 profiles=tuple(PROFILE_SCOPES)):
        self.calls = []
        self.clients = {(profile, role): RoleSigner.from_directory(folder, profile, role)
                        for profile in profiles for role in roles}

    def sign(self, profile, role, domain, claim):
        self.calls.append((profile, role, domain))
        return self.clients[(profile, role)].sign(profile, role, domain, claim)

    # ``AuthorizationRun.signature`` hands the whole chain to a plain callable.
    def __call__(self, profile, role, domain, claim):
        return self.sign(profile, role, domain, claim)


def challenge_of(profile):
    """A real GUARD challenge for the shared run's bound corpus."""
    return RUN.store.challenge(profile, RUN.operations[profile], 'GUARD')


class RoleSignerScopeTests(unittest.TestCase):
    def client(self, profile='IND-DEMO-1', role='H'):
        return RoleSigner.from_directory(KEYS, profile, role)

    def test_a_client_satisfies_the_signer_protocol(self):
        self.assertIsInstance(self.client(), Signer)
        self.assertIsInstance(LocalSigner(RUN), Signer)

    def test_h_answers_its_own_step_domains_and_its_chain_call(self):
        profile = 'IND-DEMO-1'
        client = self.client(profile, 'H')
        for domain in (GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN):
            with self.subTest(domain=domain):
                claim = {'profile': profile}
                signature = client.sign(profile, 'H', domain, claim)
                strict_verify(client.public, raw(signature, 64), canonical([domain, claim]))

    def test_the_other_roles_sign_only_their_chain_call(self):
        profile = 'MED-DEMO-1'
        for role in ('U', 'V', 'G', 'X'):
            with self.subTest(role=role):
                client = self.client(profile, role)
                signature = client.sign(profile, role, SIGN_CALL_DOMAIN, {'profile': profile})
                strict_verify(client.public, raw(signature, 64),
                              canonical([SIGN_CALL_DOMAIN, {'profile': profile}]))
                for domain in (GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, WORKER_DOMAIN):
                    with self.assertRaises(ProtocolError) as caught:
                        client.sign(profile, role, domain, {'profile': profile})
                    self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')

    def test_worker_answers_only_the_worker_domain(self):
        profile = 'PAY-1'
        client = self.client(profile, 'worker')
        client.sign(profile, 'worker', WORKER_DOMAIN, {'profile': profile})
        for domain in (GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN):
            with self.assertRaises(ProtocolError) as caught:
                client.sign(profile, 'worker', domain, {'profile': profile})
            self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')

    def test_e_signs_no_approval_domain_at_all(self):
        # E signs no approval in the chain; the only domains it may sign are its
        # own source evidence, the envelope that carries it in PAY-1, and its own
        # possession proof.
        profile = 'PAY-1'
        client = self.client(profile, 'E')
        self.assertEqual(client.domains, frozenset({CHAIN_DOMAIN, SOURCE_DOMAIN, ENROLL_DOMAIN}))
        for domain in (GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, WORKER_DOMAIN, SIGN_CALL_DOMAIN):
            with self.assertRaises(ProtocolError) as caught:
                client.sign(profile, 'E', domain, {'profile': profile})
            self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')

    def test_a_client_answers_only_its_own_profile_and_role(self):
        client = self.client('IND-DEMO-1', 'H')
        with self.assertRaises(ProtocolError) as caught:
            client.sign('PAY-1', 'H', GUARD_DOMAIN, {'profile': 'PAY-1'})
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')
        with self.assertRaises(ProtocolError) as caught:
            client.sign('IND-DEMO-1', 'U', SIGN_CALL_DOMAIN, {'profile': 'IND-DEMO-1'})
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')

    def test_a_claim_naming_another_profile_is_refused(self):
        client = self.client('PAY-1', 'U')
        with self.assertRaises(ProtocolError) as caught:
            client.sign('PAY-1', 'U', SIGN_CALL_DOMAIN, {'profile': 'MED-DEMO-1'})
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')
        with self.assertRaises(ProtocolError) as caught:
            client.sign('PAY-1', 'U', SIGN_CALL_DOMAIN, ['not a claim'])
        self.assertEqual(caught.exception.code, 'CLIENT_CLAIM')

    def test_unknown_profile_and_role_are_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            RoleSigner('PAY-2', 'H', role_key_path(KEYS, 'PAY-1', 'H'))
        self.assertEqual(caught.exception.code, 'CLIENT_PROFILE')
        with self.assertRaises(ProtocolError) as caught:
            RoleSigner('PAY-1', 'C', role_key_path(KEYS, 'PAY-1', 'H'))
        self.assertEqual(caught.exception.code, 'CLIENT_ROLE')

    def test_the_key_is_the_roles_own_0600_credential(self):
        self.assertEqual(role_key_path(KEYS, 'PAY-1', 'X').name, 'PAY-1-X.key')
        self.assertEqual(role_key_path(KEYS, 'PAY-1', 'worker').name, 'W-worker.key')
        loose = KEYS / 'loose.key'
        loose.write_bytes(role_key_path(KEYS, 'PAY-1', 'X').read_bytes())
        os.chmod(loose, 0o644)
        with self.assertRaises(ProtocolError) as caught:
            RoleSigner('PAY-1', 'X', loose)
        self.assertEqual(caught.exception.code, 'CLIENT_KEY_OWNER')
        short = KEYS / 'short.key'
        short.write_bytes(b'too short')
        os.chmod(short, 0o600)
        with self.assertRaises(ProtocolError) as caught:
            RoleSigner('PAY-1', 'X', short)
        self.assertEqual(caught.exception.code, 'CLIENT_KEY_FORMAT')


class SigningHostTests(unittest.TestCase):
    profile = 'IND-DEMO-1'

    def setUp(self):
        self.signer = RoleSigner.from_directory(KEYS, self.profile, 'H')
        self.claim = {'profile': self.profile, 'stage': 'GUARD', 'nonce': 'test-nonce'}

    def request(self, **overrides):
        body = {'profile': self.profile, 'role': 'H', 'domain': GUARD_DOMAIN, 'claim': self.claim}
        body.update(overrides)
        return json.dumps(body).encode('utf-8')

    def test_an_answer_signs_exactly_the_domain_bound_claim(self):
        response = answer(self.request() + b'\n', self.signer)
        strict_verify(self.signer.public, raw(response['signature'], 64),
                      canonical([GUARD_DOMAIN, self.claim]))
        self.assertEqual(response['kid'], self.signer.kid)
        self.assertEqual((response['profile'], response['role'], response['domain']),
                         (self.profile, 'H', GUARD_DOMAIN))

    def test_one_shot_writes_one_line_and_stops(self):
        reader = io.BytesIO(self.request() + b'\n' + self.request(domain=READ_DOMAIN) + b'\n')
        writer = io.BytesIO()
        serve_connection(reader, writer, self.signer, once=True)
        self.assertEqual(len(writer.getvalue().splitlines()), 1)

    def test_resident_mode_answers_every_line_until_input_closes(self):
        lines = [self.request(), self.request(domain=READ_DOMAIN),
                 self.request(domain=SIGN_CALL_DOMAIN)]
        writer = io.BytesIO()
        serve_connection(io.BytesIO(b'\n'.join(lines) + b'\n'), writer, self.signer)
        responses = [json.loads(row) for row in writer.getvalue().splitlines()]
        self.assertEqual([row['domain'] for row in responses],
                         [GUARD_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN])

    def test_malformed_requests_are_refused(self):
        cases = ((b'not json\n', 'CLIENT_MALFORMED'),
                 (b'{"profile":"IND-DEMO-1"}\n', 'CLIENT_FIELDS'),
                 (self.request(claim=[]) + b'\n', 'CLIENT_CLAIM'),
                 (b'x' * MAX_REQUEST_LINE, 'CLIENT_SIZE'))
        for line, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ProtocolError) as caught:
                    decode_request(line)
                self.assertEqual(caught.exception.code, code)

    def test_a_request_for_another_profile_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            answer(self.request(profile='PAY-1', claim={'profile': 'PAY-1', 'nonce': 'n'}) + b'\n',
                   self.signer)
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')

    def test_a_refused_request_ends_the_stream_without_an_answer(self):
        # H never signs the worker domain, so the host must stop, not skip.
        lines = self.request(domain=WORKER_DOMAIN) + b'\n' + self.request() + b'\n'
        writer = io.BytesIO()
        with self.assertRaises(ProtocolError) as caught:
            serve_connection(io.BytesIO(lines), writer, self.signer)
        self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')
        self.assertEqual(writer.getvalue(), b'')

    def test_a_unix_socket_serves_and_fails_closed(self):
        path = FOLDER / 'H.sign.sock'
        outcome = []
        thread = threading.Thread(target=lambda: _capture(outcome, serve_unix, path, self.signer),
                                  daemon=True)
        thread.start()
        self.addCleanup(thread.join, 30)
        deadline = time.monotonic() + 10
        while not path.exists():
            self.assertLess(time.monotonic(), deadline, 'signing socket never appeared')
            time.sleep(0.02)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(path))
            stream = client.makefile('rb')
            client.sendall(self.request() + b'\n')
            response = json.loads(stream.readline())
            strict_verify(self.signer.public, raw(response['signature'], 64),
                          canonical([GUARD_DOMAIN, self.claim]))
            client.sendall(b'{"profile":"IND-DEMO-1"}\n')
            self.assertEqual(stream.readline(), b'')
            stream.close()
        thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcome[0], ProtocolError)
        self.assertEqual(outcome[0].code, 'CLIENT_FIELDS')
        self.assertFalse(path.exists())


def _capture(sink, call, *args):
    try:
        call(*args)
    except BaseException as exc:  # noqa: BLE001 - the test asserts what came out
        sink.append(exc)


class TrustedServiceSigningTests(unittest.TestCase):
    """The trusted service over a run whose chain and steps are signed externally."""

    def setUp(self):
        self.previous = RUN.signer
        self.clients = RoleClients(KEYS)
        RUN.signer = self.clients
        self.service = TrustedService(RUN, self.clients)

    def tearDown(self):
        RUN.signer = self.previous

    def test_the_external_clients_drive_all_three_profiles(self):
        before = self.service.counts()
        for profile in PROFILE_SCOPES:
            self.assertIn('settled', self.service.run_normal(profile))
        after = self.service.counts()
        self.assertEqual(after['accepts'] - before['accepts'], len(PROFILE_SCOPES))
        self.assertEqual(after['settlements'] - before['settlements'], len(PROFILE_SCOPES))
        self.assertEqual(after['confirmed_simulated_effects'] - before['confirmed_simulated_effects'],
                         len(PROFILE_SCOPES))
        # Every request stayed inside the whitelist, and the run exercised every
        # step and caller-proof domain an approval flow actually uses.
        whitelist = {(role, domain) for role, domains in ROLE_DOMAINS.items() for domain in domains}
        answered = {(role, domain) for _, role, domain in self.clients.calls}
        self.assertTrue(answered <= whitelist)
        self.assertEqual(answered, {('H', GUARD_DOMAIN), ('H', ACCEPT_DOMAIN), ('H', READ_DOMAIN),
                                    ('worker', WORKER_DOMAIN)}
                         | {(role, SIGN_CALL_DOMAIN) for role in ('H', 'U', 'V', 'G', 'X')})

    def test_another_roles_key_is_rejected_by_the_trusted_side(self):
        # The client is willing to answer -- it signs with a real roster key --
        # but the trusted side verifies against its own roster, not the caller.
        borrowed = RoleSigner('IND-DEMO-1', 'H', role_key_path(KEYS, 'MED-DEMO-1', 'H'))
        submitted = self.service.submit('IND-DEMO-1')
        proof = {'claim': submitted['challenge'],
                 'signature': borrowed.sign('IND-DEMO-1', 'H', GUARD_DOMAIN,
                                            submitted['challenge'])}
        strict_verify(RUN.actors['MED-DEMO-1']['H'].pub, raw(proof['signature'], 64),
                      canonical([GUARD_DOMAIN, submitted['challenge']]))
        with self.assertRaises(ProtocolError) as caught:
            self.service.prove(submitted['operation_id'], 'prepare', proof)
        self.assertEqual(caught.exception.code, 'BAD_SIGNATURE')

    def test_a_client_bound_to_another_profile_cannot_answer_at_all(self):
        # A real PAY-1 challenge handed to the IND-DEMO-1 client is refused
        # client-side, before any key is used.
        with self.assertRaises(ProtocolError) as caught:
            self.clients.sign('IND-DEMO-1', 'H', GUARD_DOMAIN, challenge_of('PAY-1'))
        self.assertEqual(caught.exception.code, 'CLIENT_BINDING')


class ChainSigningTests(unittest.TestCase):
    """The in-chain caller proof: shipped by an external client, accepted by the broker."""

    def setUp(self):
        self.previous = RUN.signer
        self.clients = RoleClients(KEYS)
        RUN.signer = self.clients

    def tearDown(self):
        RUN.signer = self.previous

    def test_the_run_passes_the_signer_through_to_the_chain(self):
        # Assigning on the W run reaches the chain's own seam.
        self.assertIs(RUN.base.signer, self.clients)
        RUN.signer = None
        self.assertIsNone(RUN.base.signer)
        RUN.signer = self.clients
        self.assertIs(RUN.base.signer, self.clients)

    def test_a_fresh_chain_is_signed_and_accepted_through_the_external_clients(self):
        profile = 'MED-DEMO-1'
        op = RUN.fork_operation(profile)
        chain = (('reviews', 'V'), ('authorization', 'U'), ('issue', 'H'), ('permit', 'G'),
                 ('challenge_request', 'H'), ('challenge', 'X'), ('proof', 'H'))
        for name, alias in chain:
            messages = op[name] if name == 'reviews' else [op[name]]
            for message in messages:
                who = RUN.actors[profile][alias]
                self.assertEqual(message['protected']['kid'], who.kid)
                strict_verify(who.pub, raw(message['sig'], 64),
                              canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))
                self.assertIn((profile, alias, SIGN_CALL_DOMAIN), self.clients.calls)
        # The broker only signs once it has authenticated the caller proof, so a
        # completed chain proves the external proof was accepted in-chain.
        self.assertIn((profile, 'U', SIGN_CALL_DOMAIN), self.clients.calls)


if __name__ == '__main__':
    unittest.main()
