"""The trusted side reaches every endpoint over HTTP, and the rules survive it.

Four claims:

* :class:`~competition.server.roster.HTTPTransport` carries the same request the
  socket carries and returns the same envelope, so ``RemoteKey`` and everything
  above it cannot tell which transport carried the bytes;
* a refusal keeps the endpoint's own rule name instead of being flattened, and a
  dead or nonsensical endpoint fails as a transport error rather than as a
  signature;
* ``Fleet`` picks the transport from ``base_url`` and derives each address from
  the one port rule; with no ``base_url`` it still reaches the socket beside the
  key file, so the old deployment is untouched;
* a whole collected-key initialization runs over HTTP -- every alias signed its
  own chain messages, and a normal run settles.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from competition.client.keys import generate
from competition.client.signer import CHAIN_DOMAIN, RoleSigner
from competition.client.web import make_app
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.roster import (
    ALIASES, DENY_STATUS, Fleet, HTTPTransport, RemoteKey, SocketTransport, endpoint_port,
    read_entry,
)
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.support.artifact import signed_messages_valid
from competition.support.wire import ProtocolError, canonical, raw, strict_verify
from competition.tests.endpoint_face import Face, free_port

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
SIGN_CALL = 'COMP-APP-SIGN-CALL-v1'


class HttpTransportTests(unittest.TestCase):
    """One endpoint over HTTP, with its own refusals carried through."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = Path(cls.work.name)
        cls.entry = read_entry(generate(cls.keys, 'PAY-1', 'U'))
        cls.signer = RoleSigner.from_directory(cls.keys, 'PAY-1', 'U')
        cls.face = Face(make_app(cls.signer))
        cls.transport = HTTPTransport(cls.face.base)

    @classmethod
    def tearDownClass(cls):
        cls.face.close()
        cls.work.cleanup()

    def test_a_remote_key_signs_through_the_transport(self):
        data = canonical([CHAIN_DOMAIN, {'profile': 'PAY-1'}, {'x': '1'}])
        strict_verify(self.signer.public, RemoteKey(self.entry, self.transport).sign(data), data)

    def test_a_signing_request_round_trips_unchanged(self):
        claim = {'profile': 'PAY-1'}
        reply = self.transport.request({'op': 'challenge', 'profile': 'PAY-1', 'role': 'U',
                                        'domain': SIGN_CALL, 'claim': claim})
        self.assertEqual(reply['kid'], self.signer.kid)
        self.assertEqual(reply['role'], 'U')
        strict_verify(self.signer.public, raw(reply['signature'], 64),
                      canonical([SIGN_CALL, claim]))

    def test_a_refusal_keeps_the_endpoints_own_rule_name(self):
        with self.assertRaises(ProtocolError) as caught:
            self.transport.request({'op': 'challenge', 'profile': 'PAY-1', 'role': 'U',
                                    'domain': 'ZJJ-SOURCE-v1', 'claim': {}})
        self.assertEqual(caught.exception.code, 'CLIENT_DOMAIN')

    def test_a_dead_endpoint_fails_as_unavailable(self):
        with self.assertRaises(ProtocolError) as caught:
            HTTPTransport('http://127.0.0.1:%d' % free_port()).request({'op': 'challenge'})
        self.assertEqual(caught.exception.code, 'ENDPOINT_UNAVAILABLE')

    def test_a_nonsense_answer_fails_as_a_transport_error(self):
        # Something that answers on the port but is not an endpoint must never be
        # mistaken for one, whatever it says.
        app = FastAPI()

        @app.get('/healthz')
        def healthz():
            return {'ok': True}

        @app.post('/plain/sign')
        def plain():
            return PlainTextResponse('hello')

        @app.post('/nosig/sign')
        def nosig():
            return JSONResponse(content={'ok': True})

        @app.post('/boom/sign')
        def boom():
            return JSONResponse(status_code=500, content={'error': 'x'})

        @app.post('/denytext/sign')
        def denytext():
            return PlainTextResponse('no', status_code=DENY_STATUS)

        face = Face(app)
        self.addCleanup(face.close)
        for suffix in ('plain', 'nosig', 'boom', 'denytext'):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ProtocolError) as caught:
                    HTTPTransport('%s/%s' % (face.base, suffix)).request({'op': 'challenge'})
                self.assertEqual(caught.exception.code, 'ENDPOINT_ANSWER')


class FleetTransportTests(unittest.TestCase):
    """The deployment picks a transport; every other rule is shared."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.keys = Path(cls.work.name)
        cls.entry = read_entry(generate(cls.keys, 'PAY-1', 'U'))

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_the_base_url_chooses_the_transport(self):
        self.assertIsInstance(Fleet([self.entry], self.keys).transport_for(self.entry),
                              SocketTransport)
        self.assertIsInstance(
            Fleet([self.entry], self.keys, base_url='http://endpoints').transport_for(self.entry),
            HTTPTransport)

    def test_the_address_follows_the_one_port_rule(self):
        fleet = Fleet([self.entry], self.keys, base_url='http://endpoints/')
        self.assertEqual(fleet.base_url, 'http://endpoints')
        self.assertEqual(fleet.endpoint_url(self.entry),
                         'http://endpoints:%d' % endpoint_port('PAY-1', 'U'))
        self.assertEqual(fleet.http_transport(self.entry).url, fleet.endpoint_url(self.entry))

    def test_without_a_base_url_there_is_no_http_address(self):
        with self.assertRaises(ProtocolError) as caught:
            Fleet([self.entry], self.keys).endpoint_url(self.entry)
        self.assertEqual(caught.exception.code, 'FLEET_TRANSPORT')

    def test_the_socket_convention_is_unchanged(self):
        fleet = Fleet([self.entry], self.keys)
        self.assertEqual(fleet.key_path(self.entry), str(self.keys / 'PAY-1-U.key'))
        self.assertEqual(fleet.socket_path(self.entry), str(self.keys / 'PAY-1-U.sock'))

    def test_an_explicit_transport_still_wins(self):
        fleet = Fleet([self.entry], self.keys, base_url='http://endpoints',
                      transport_for=lambda entry: 'custom')
        self.assertEqual(fleet.transport_for(self.entry), 'custom')

    def test_read_carries_the_base_url_through(self):
        manifest = self.keys / 'roster.jsonl'
        manifest.write_text(json.dumps(generate(self.keys, 'MED-DEMO-1', 'V')) + '\n',
                            encoding='utf-8')
        fleet = Fleet.read(self.keys, manifest, base_url='http://endpoints')
        self.assertIsInstance(fleet.transport_for(fleet.find('V', 'MED-DEMO-1')), HTTPTransport)


class InitializationOverHttpTests(unittest.TestCase):
    """A whole collected-key initialization, with every endpoint on HTTP.

    The endpoints listen on the ports their roster places imply and the fleet is
    built from one ``base_url``, so this is the deployment rather than a
    simulation of it.
    """

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.endpoints = Path(cls.work.name) / 'endpoints'
        lines = [generate(cls.endpoints, profile, role)
                 for profile in sorted(PROFILE_SCOPES) for role in ALIASES]
        lines.append(generate(cls.endpoints, None, 'worker'))
        lines += [generate(cls.endpoints, profile, 'tool')
                  for profile in sorted(PROFILE_SCOPES)]
        cls.entries = [read_entry(line) for line in lines]
        cls.faces = []
        try:
            for entry in cls.entries:
                if entry.role == 'tool':
                    continue
                signer = RoleSigner.from_directory(cls.endpoints, entry.profile, entry.role)
                cls.faces.append(Face(make_app(signer),
                                      port=endpoint_port(entry.profile, entry.role)))
            cls.fleet = Fleet(cls.entries, cls.endpoints, base_url='http://127.0.0.1')
            cls.trusted = initialize(Path(cls.work.name) / 'w', fleet=cls.fleet)
        except BaseException:
            for face in cls.faces:
                face.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        for face in cls.faces:
            face.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_every_alias_signed_its_own_chain_messages(self):
        for profile, op in self.trusted.operations.items():
            with self.subTest(profile=profile):
                self.assertTrue(signed_messages_valid(self.trusted, profile, op))

    def test_a_normal_run_settles_with_every_signature_coming_over_http(self):
        service = TrustedService(self.trusted, LocalSigner(self.trusted))
        for profile in sorted(PROFILE_SCOPES):
            with self.subTest(profile=profile):
                result = service.run_normal(profile)
                self.assertEqual(result['settled']['state'], 'SETTLED')
                self.assertEqual(result['status']['acceptance_state'], 'COMMITTED')

    def test_no_role_key_was_generated_on_the_trusted_side(self):
        self.assertEqual({path.name for path in Path(self.trusted.folder).glob('*.key')},
                         {'C.key', 'W-delivery.key'})


if __name__ == '__main__':
    unittest.main()
