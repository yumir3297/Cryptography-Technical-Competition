"""The console: two callers, a page's worth of HTTP, and no third protocol.

Four claims:

* a page drives each of the three scenarios over the console's own HTTP, and
  every business signature is still made by the endpoint that owns its step --
  the console holds two credentials of its own and no role key;
* the entry's caller list is what keeps each side on its side: the holder side
  cannot ``exec`` and the worker side cannot ``accept``, and both refusals arrive
  under the entry's own rule name;
* the console's bodies are exact -- a field it does not take, or a side it does
  not have, is refused before the entry is reached;
* the two credentials are private (``0600``, never a token in a reply) and listed
  by public key alone, exactly like the endpoints.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from competition.caller import CALLER_LIST
from competition.client.signer import RoleSigner
from competition.client.web import make_app as endpoint_app
from competition.console.app import make_app as console_app
from competition.console.control import Console
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.roster import ALIASES, endpoint_port
from competition.server.service import INTENT_FIELDS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import ProtocolError
from competition.tests.helpers import Face
from competition.web.app import make_app as entry_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class ConsoleFlowTests(unittest.TestCase):
    """One console, two sides, nineteen endpoints and one entry."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.faces = []
        try:
            for profile in sorted(PROFILE_SCOPES):
                for role in ALIASES:
                    signer = RoleSigner.from_directory(cls.trusted.folder, profile, role)
                    cls.faces.append(Face(endpoint_app(signer),
                                          port=endpoint_port(profile, role)))
            cls.faces.append(Face(endpoint_app(
                RoleSigner.from_directory(cls.trusted.folder, None, 'worker')),
                port=endpoint_port(None, 'worker')))
            # The entry is built before the console enrolls, because a deployment
            # starts its services at once: the list it reads again when it meets
            # the console's key is the same list the console is about to write.
            cls.callers = Path(cls.work.name) / 'callers'
            cls.callers_path = cls.callers / CALLER_LIST
            try:
                sessions = Sessions(read_callers(cls.callers_path), source=cls.callers_path)
            except ProtocolError:
                sessions = Sessions({}, source=cls.callers_path)
            cls.entry = Face(entry_app(
                TrustedService(cls.trusted, LocalSigner(cls.trusted)), sessions))
            cls.console = Console(cls.callers, cls.entry.base, 'http://127.0.0.1', timeout=60)
            cls.console.enroll()
            cls.console.start()
            cls.client = TestClient(console_app(cls.console))
        except BaseException:
            for face in cls.faces:
                face.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.entry.close()
        for face in cls.faces:
            face.close()
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def operate(self):
        """One fresh operation on the holder side, and its id."""
        return self.console.submit('PAY-1', None)['operation_id']

    # -- every scenario, over the console's own HTTP -------------------------
    def test_a_page_drives_every_scenario_over_its_own_http(self):
        for profile in INTENT_FIELDS:
            with self.subTest(profile=profile):
                submitted = self.client.post('/console/api/submit', json={'profile': profile})
                self.assertEqual(submitted.status_code, 200, submitted.text)
                operation_id = submitted.json()['operation_id']
                for side, step in (('H', 'prepare'), ('H', 'accept'),
                                   ('worker', 'claim'), ('worker', 'exec')):
                    reply = self.client.post('/console/api/step', json={
                        'side': side, 'operation_id': operation_id, 'step': step})
                    self.assertEqual(reply.status_code, 200, reply.text)
                settled = self.client.post('/console/api/step', json={
                    'side': 'worker', 'operation_id': operation_id, 'step': 'settle'}).json()
                self.assertEqual(settled['state'], 'SETTLED')
                view = self.client.post('/console/api/step', json={
                    'side': 'H', 'operation_id': operation_id, 'step': 'status'}).json()
                self.assertEqual(view['acceptance_state'], 'COMMITTED')
                self.assertTrue(view['exec_consumed'])

    def test_the_scenarios_are_the_entry_s_own(self):
        reply = self.client.get('/console/api/scenarios')
        self.assertEqual(reply.status_code, 200, reply.text)
        profiles = reply.json()['profiles']
        self.assertEqual([entry['profile'] for entry in profiles], list(INTENT_FIELDS))
        for entry in profiles:
            with self.subTest(profile=entry['profile']):
                self.assertEqual(entry['intents'], list(INTENT_FIELDS[entry['profile']]))

    # -- the entry's caller list is what keeps each side on its side ---------
    def test_a_side_cannot_drive_the_other_side(self):
        operation_id = self.operate()
        for side, step in (('H', 'exec'), ('worker', 'accept')):
            with self.subTest(side=side, step=step):
                with self.assertRaises(ProtocolError) as caught:
                    self.console.step(side, operation_id, step)
                self.assertEqual(caught.exception.code, 'SESSION_SIDE')

    # -- the bodies are exact ------------------------------------------------
    def test_the_page_calls_refuse_a_body_that_is_not_their_own(self):
        for path, body in (('/console/api/submit', {'profile': 'PAY-1', 'role': 'H'}),
                           ('/console/api/submit', {}),
                           ('/console/api/step', {'side': 'H', 'operation_id': 'x'}),
                           ('/console/api/step', {'side': 'H', 'operation_id': 'x',
                                                  'step': 'prepare', 'key': 'y'})):
            with self.subTest(path=path, body=body):
                reply = self.client.post(path, json=body)
                self.assertEqual(reply.status_code, 403, reply.text)
                self.assertEqual(reply.json(), {'deny': 'CONSOLE_FIELDS'})

    def test_a_side_the_console_does_not_have_is_refused(self):
        reply = self.client.post('/console/api/step', json={
            'side': 'X', 'operation_id': 'x', 'step': 'prepare'})
        self.assertEqual(reply.status_code, 403, reply.text)
        self.assertEqual(reply.json(), {'deny': 'CONSOLE_SIDE'})

    # -- the status says a session is open, and never hands out a token ------
    def test_the_status_names_the_sessions_but_no_token(self):
        status = self.client.get('/console/api/status').json()
        self.assertEqual([entry['side'] for entry in status['sessions']], ['H', 'worker'])
        for entry in status['sessions']:
            self.assertTrue(entry['open'])
            self.assertEqual(entry['sides'], [entry['side']])
            self.assertNotIn('token', json.dumps(entry))

    # -- the credentials are the console's own ------------------------------
    def test_the_two_credentials_are_private_and_listed_publicly(self):
        names = sorted(path.name for path in self.callers.glob('*.key'))
        self.assertEqual(names, ['console-h.key', 'console-worker.key'])
        for path in self.callers.glob('*.key'):
            status = path.stat()
            self.assertEqual((status.st_uid, status.st_mode & 0o777), (os.geteuid(), 0o600))
        lines = [json.loads(line) for line in
                 self.callers_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertEqual(sorted(line['name'] for line in lines),
                         ['console-h', 'console-worker'])
        for line in lines:
            self.assertEqual(set(line), {'name', 'public_key', 'sides'})
        self.assertEqual({line['name']: line['sides'] for line in lines},
                         {'console-h': ['H'], 'console-worker': ['worker']})


if __name__ == '__main__':
    unittest.main()
