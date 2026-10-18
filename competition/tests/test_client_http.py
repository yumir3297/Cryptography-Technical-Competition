"""The endpoint's HTTP face: one protocol, two transports, no extra authority.

Three claims:

* ``POST /sign`` answers with exactly what the line protocol answers -- same op
  set, same field set, same refusals -- because both hand the request to
  :func:`competition.client.host.answer`.  The two transports cannot drift;
* the HTTP face adds no authority: a domain outside the signer's whitelist, a
  request for another binding, and a malformed or over-sized body are all
  refused, and the refusal names the same rule the line protocol names;
* a real endpoint process serves that face, and ``/check-package`` lets it
  verify its own registration from a package handed over the wire.

Every face here is a real uvicorn server on a real port rather than a simulated
transport, because the thing being tested *is* the transport.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

from competition.client.approval import WaitingRoom
from competition.client.host import MAX_REQUEST_LINE, answer
from competition.client.keys import generate
from competition.client.signer import CHAIN_DOMAIN, RoleSigner
from competition.client.web import make_app
from competition.core.signer_broker import ScopedSignerBroker
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.package import public_package
from competition.server.roster import ALIASES, HTTP_PORT_BASE, endpoint_port
from competition.support.wire import ProtocolError, b64, canonical, keyid, raw, strict_verify
from competition.tests.helpers import Face, body, free_port

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
ROOT = Path(__file__).resolve().parents[2]
SIGN_CALL = 'COMP-APP-SIGN-CALL-v1'
WORKER = 'COMP-W-WORKER-v1'


class HttpFaceTests(unittest.TestCase):
    """One endpoint's own key, reached by HTTP instead of a byte stream."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = Path(cls.work.name)
        for profile in PROFILE_SCOPES:
            for role in ('H', 'U', 'V'):
                generate(cls.keys, profile, role)
        generate(cls.keys, None, 'worker')
        cls._faces = {}

    @classmethod
    def tearDownClass(cls):
        for _, face in cls._faces.values():
            face.close()
        cls.work.cleanup()

    def endpoint(self, profile='PAY-1', role='U'):
        """The signer and its served face, started once per endpoint."""
        key = (profile, role)
        if key not in self._faces:
            signer = RoleSigner.from_directory(self.keys, profile, role)
            self._faces[key] = (signer, Face(make_app(signer)))
        return self._faces[key]

    def test_healthz_and_identity_report_the_key_this_process_holds(self):
        signer, face = self.endpoint('PAY-1', 'V')
        health = face.get('/healthz')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()['kid'], signer.kid)
        identity = face.get('/identity').json()
        self.assertEqual((identity['profile'], identity['role']), ('PAY-1', 'V'))
        self.assertEqual(identity['public_key'], b64(signer.public))
        self.assertEqual(identity['kid'], keyid(signer.public))
        self.assertEqual(identity['subject'], 'auth-payment-v')

    def test_the_worker_serves_without_a_profile(self):
        signer, face = self.endpoint(None, 'worker')
        identity = face.get('/identity').json()
        self.assertEqual((identity['profile'], identity['role']), (None, 'worker'))
        self.assertEqual(identity['subject'], 'competition-worker')
        self.assertEqual(identity['purposes'], [])

    def test_a_challenge_is_answered_and_verifies_against_the_public_key(self):
        signer, face = self.endpoint('PAY-1', 'U')
        claim = {'profile': 'PAY-1', 'request_ref': 'r'}
        reply = face.post('/sign', body(op='challenge', profile='PAY-1', role='U',
                                        domain=SIGN_CALL, claim=claim))
        self.assertEqual(reply.status_code, 200)
        served = reply.json()
        self.assertEqual(served['kid'], signer.kid)
        self.assertEqual(served['domain'], SIGN_CALL)
        strict_verify(signer.public, raw(served['signature'], 64), canonical([SIGN_CALL, claim]))

    def test_the_worker_answers_only_its_own_domain(self):
        signer, face = self.endpoint(None, 'worker')
        claim = {'operation_id': 'o', 'purpose': 'CLAIM'}
        reply = face.post('/sign', body(op='challenge', profile=None, role='worker',
                                        domain=WORKER, claim=claim))
        self.assertEqual(reply.status_code, 200)
        strict_verify(signer.public, raw(reply.json()['signature'], 64),
                      canonical([WORKER, claim]))

    def test_the_raw_op_signs_the_bytes_it_is_handed(self):
        signer, face = self.endpoint('PAY-1', 'U')
        data = canonical([CHAIN_DOMAIN, {'profile': 'PAY-1'}, {'x': '1'}])
        reply = face.post('/sign', body(op='raw', profile='PAY-1', role='U', data=b64(data)))
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()['domain'], CHAIN_DOMAIN)
        strict_verify(signer.public, raw(reply.json()['signature'], 64), data)

    # -- refusals -----------------------------------------------------------
    def test_a_domain_outside_the_whitelist_is_refused(self):
        _, face = self.endpoint('PAY-1', 'U')
        reply = face.post('/sign', body(op='challenge', profile='PAY-1', role='U',
                                        domain='ZJJ-SOURCE-v1', claim={}))
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'CLIENT_DOMAIN'})

    def test_another_binding_is_refused(self):
        _, face = self.endpoint('PAY-1', 'U')
        for profile, role in (('MED-DEMO-1', 'U'), ('PAY-1', 'V')):
            with self.subTest(profile=profile, role=role):
                reply = face.post('/sign', body(op='challenge', profile=profile, role=role,
                                                domain=SIGN_CALL, claim={}))
                self.assertEqual(reply.json(), {'deny': 'CLIENT_BINDING'})

    def test_a_claim_naming_another_profile_is_refused(self):
        _, face = self.endpoint('PAY-1', 'U')
        reply = face.post('/sign', body(op='challenge', profile='PAY-1', role='U',
                                        domain=SIGN_CALL, claim={'profile': 'MED-DEMO-1'}))
        self.assertEqual(reply.json(), {'deny': 'CLIENT_BINDING'})

    def test_malformed_and_over_sized_requests_are_refused(self):
        _, face = self.endpoint('PAY-1', 'U')
        cases = ((b'not json', 'CLIENT_MALFORMED'),
                 (body(op='bogus', profile='PAY-1', role='U'), 'CLIENT_OP'),
                 (body(profile='PAY-1', role='U', domain='d'), 'CLIENT_FIELDS'),
                 (body(op='raw', profile='PAY-1', role='U', data='AA', extra='1'), 'CLIENT_FIELDS'),
                 (b'x' * (MAX_REQUEST_LINE + 1), 'CLIENT_SIZE'))
        for payload, code in cases:
            with self.subTest(code=code):
                reply = face.post('/sign', payload)
                self.assertEqual(reply.status_code, 403)
                self.assertEqual(reply.json(), {'deny': code})

    def test_the_two_transports_answer_identically(self):
        # Same decision point: the rule names are the line protocol's, and an
        # accepted request produces the same answer object either way.
        signer, face = self.endpoint('PAY-1', 'U')
        payload = body(op='challenge', profile='PAY-1', role='U', domain=SIGN_CALL,
                       claim={'profile': 'PAY-1'})
        self.assertEqual(face.post('/sign', payload).json(), answer(payload + b'\n', signer))

    def test_a_package_of_the_wrong_shape_is_refused(self):
        _, face = self.endpoint('PAY-1', 'U')
        cases = ((body(package={'kind': 'something-else'}), 'PACKAGE_FORMAT'),
                 (body(package={'kind': 'x'}, extra='1'), 'CLIENT_FIELDS'),
                 (body(subject='x'), 'CLIENT_FIELDS'),
                 (body(), 'CLIENT_FIELDS'),
                 (b'not json', 'CLIENT_MALFORMED'))
        for payload, code in cases:
            with self.subTest(code=code):
                self.assertEqual(face.post('/check-package', payload).json(), {'deny': code})


class EndpointPortTests(unittest.TestCase):
    """One deterministic port per endpoint, computed from its place in the roster."""

    def test_every_endpoint_gets_its_own_port(self):
        places = [(profile, role) for profile in PROFILE_SCOPES for role in ALIASES]
        places.append((None, 'worker'))
        ports = {place: endpoint_port(*place) for place in places}
        self.assertEqual(len(ports), 3 * 6 + 1)
        self.assertEqual(len(set(ports.values())), len(ports))
        self.assertEqual(ports[(None, 'worker')], HTTP_PORT_BASE)

    def test_the_rule_is_stable_and_refuses_what_has_no_face(self):
        self.assertEqual(endpoint_port('PAY-1', 'U'), endpoint_port('PAY-1', 'U'))
        for profile, role in (('PAY-2', 'U'), ('PAY-1', 'C'), ('PAY-1', 'tool')):
            with self.subTest(profile=profile, role=role):
                with self.assertRaises(ProtocolError):
                    endpoint_port(profile, role)


class ServedEndpointTests(unittest.TestCase):
    """A real endpoint serves the face and checks its own registration over it."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.package = public_package(cls.trusted)
        cls.faces = {}

    @classmethod
    def tearDownClass(cls):
        for _, face in cls.faces.values():
            face.close()
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def endpoint(self, profile, role):
        key = (profile, role)
        if key not in self.faces:
            signer = RoleSigner.from_directory(self.trusted.folder, profile, role)
            self.faces[key] = (self.trusted.actors[profile][role], Face(make_app(signer)))
        return self.faces[key]

    def test_an_endpoint_checks_its_own_registration_from_the_wire(self):
        profile, role = 'MED-DEMO-1', 'E'
        actor, face = self.endpoint(profile, role)
        checked = face.post('/check-package', body(package=self.package)).json()
        self.assertEqual(checked['check'], 'OK')
        self.assertEqual(checked['kid'], actor.kid)
        self.assertEqual(checked['name'], actor.name)
        self.assertEqual(checked['purposes'], sorted(actor.purposes))

    def test_a_widened_package_is_refused(self):
        profile, role = 'MED-DEMO-1', 'E'
        _, face = self.endpoint(profile, role)
        forged = json.loads(json.dumps(self.package))
        entry = forged['actors'][profile][role]
        entry['purposes'] = sorted(set(entry['purposes']) | {'Review'})
        self.assertNotEqual(entry['purposes'], sorted(self.trusted.actors[profile][role].purposes))
        reply = face.post('/check-package', body(package=forged))
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'PACKAGE_PURPOSES'})

    def test_the_command_line_serves_the_face(self):
        profile, role = 'PAY-1', 'G'
        port = free_port()
        argv = [sys.executable, '-m', 'competition.client', '--directory',
                str(self.trusted.folder), '--profile', profile, '--alias', role,
                '--serve-http', '--port', str(port)]
        process = subprocess.Popen(argv, cwd=str(ROOT), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        base = 'http://127.0.0.1:%d' % port
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    self.fail('endpoint exited: %s' % process.communicate()[1])
                try:
                    if httpx.get(base + '/healthz', timeout=1.0).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    self.fail('endpoint did not answer')
                time.sleep(0.05)
            actor = self.trusted.actors[profile][role]
            identity = httpx.get(base + '/identity', timeout=5.0).json()
            self.assertEqual(identity['kid'], actor.kid)
            claim = {'profile': profile, 'probe': True}
            served = httpx.post(base + '/sign', timeout=5.0,
                                content=body(op='challenge', profile=profile, role=role,
                                             domain=SIGN_CALL, claim=claim)).json()
            strict_verify(actor.pub, raw(served['signature'], 64), canonical([SIGN_CALL, claim]))
        finally:
            process.terminate()
            process.communicate(timeout=10)
        self.assertNotEqual(process.returncode, 0)


class RecordedApprovalTests(unittest.TestCase):
    """What a report can be, and what the endpoint does with each kind.

    A person's decision parks until somebody answers it.  The trusted side's own
    bootstrap reports the same messages but says they are not a person's
    decision, so the answer is recorded and the signing call that follows is
    answered instead of parked -- otherwise initialization, which the documented
    boundary calls scripted rather than a person's, would stop a deployment on
    nobody's answer.
    """

    def room(self):
        return WaitingRoom(limit=4, timeout=1.0, preapproval_timeout=1.0)

    def test_a_recorded_answer_is_taken_by_exactly_one_signature(self):
        room = self.room()
        unsigned, action = {'body': {'id': 'one'}}, {'payload': {'k': 'v'}}
        room.remember(profile='PAY-1', role='G', unsigned=unsigned, action=action)
        ref = ScopedSignerBroker.request_ref('PAY-1', 'G', unsigned, action)
        self.assertTrue(room.take_approved(ref))
        # One reference is answered by one signature, so the second call is not
        # the one that was agreed to.
        self.assertFalse(room.take_approved(ref))

    def test_a_reference_nobody_reported_has_no_answer(self):
        room = self.room()
        ref = ScopedSignerBroker.request_ref('PAY-1', 'G', {'a': 'x'}, {'b': 'y'})
        self.assertFalse(room.take_approved(ref))


if __name__ == '__main__':
    unittest.main()
