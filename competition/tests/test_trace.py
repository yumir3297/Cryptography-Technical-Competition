"""Tracing: one request, one id, one line -- and nothing that can break a step.

Four claims:

* a page's call and the console's own work carry the same id, so a click and the
  three moves it caused can be read as one thing;
* the spans are the moves, not a total: the entry challenge, the endpoint's
  signature and the entry's proof are each timed where they happen;
* the page's own events are written beside them, and a body that is not the
  trace's own is refused rather than guessed at;
* tracing is inert where there is no page -- the caller, the CLI and the trusted
  side record nothing, and a trace file that cannot be written does not fail a
  request.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from competition.console.app import make_app as console_app
from competition.console.control import Console
from competition.core.trusted_state import PROFILE_SCOPES
from competition.client.signer import RoleSigner
from competition.client.web import make_app as endpoint_app
from competition.profiles.w_seed import initialize
from competition.server.roster import ALIASES, endpoint_port
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.support import trace
from competition.tests.helpers import Face
from competition.web.app import make_app as entry_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


def read_trace(path):
    """Every trace line, parsed, in the order it was written."""
    return [json.loads(line) for line in
            Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


class TraceFileTests(unittest.TestCase):
    """The log itself: bounded, safe to write, and never in the way."""

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.path = Path(self.work.name) / 'trace' / 'console.jsonl'

    def tearDown(self):
        self.work.cleanup()

    def test_a_request_line_carries_its_spans_in_order(self):
        log = trace.TraceLog(self.path)
        with trace.request_trace(log, 'abc-1', '/console/api/step', 'POST') as record:
            record['status'] = 200
            with trace.span('entry.challenge', step='prepare'):
                pass
            with trace.span('endpoint.sign', role='H') as entry:
                entry['answer'] = 'H'
        line = read_trace(self.path)[0]
        self.assertEqual((line['id'], line['route'], line['status']), ('abc-1',
                                                                     '/console/api/step', 200))
        self.assertEqual([span['name'] for span in line['spans']],
                         ['entry.challenge', 'endpoint.sign'])
        self.assertEqual(line['spans'][1]['answer'], 'H')
        self.assertIn('ms', line['spans'][0])

    def test_a_span_outside_a_request_records_nothing(self):
        # The CLI and the trusted side import the same modules; there is no page
        # and no file there, so a span must be a no-op rather than an error.
        log = trace.TraceLog(self.path)
        with trace.span('nowhere') as entry:
            entry['ignored'] = True
        self.assertFalse(self.path.exists())

    def test_a_trace_that_cannot_be_written_does_not_fail_the_request(self):
        log = trace.TraceLog(self.path)
        self.path.mkdir(parents=True)  # a directory where the file should be
        with trace.request_trace(log, 'abc-2', '/console/api/step', 'POST'):
            pass
        self.assertTrue(self.path.is_dir())

    def test_the_file_rotates_instead_of_growing_without_limit(self):
        log = trace.TraceLog(self.path, limit=200)
        for index in range(20):
            log.write({'source': 'console', 'id': str(index), 'spans': []})
        self.assertTrue(Path(str(self.path) + '.1').exists())
        self.assertLess(self.path.stat().st_size, 1000)

    def test_a_page_cannot_name_itself_outside_the_header_alphabet(self):
        self.assertEqual(trace.clean_id('ok-1_2.3'), 'ok-1_2.3')
        self.assertEqual(trace.clean_id('a b\nc'), 'abc')
        self.assertEqual(trace.clean_id('../../etc/passwd'), '....etcpasswd')
        self.assertEqual(trace.clean_id(None, 'fallback'), 'fallback')


class ConsoleTraceTests(unittest.TestCase):
    """One console, two sides and one traced step, over the console's own HTTP."""

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
            cls.callers = Path(cls.work.name) / 'callers'
            try:
                sessions = Sessions(read_callers(cls.callers / 'callers.jsonl'),
                                    source=cls.callers / 'callers.jsonl')
            except Exception:
                sessions = Sessions({}, source=cls.callers / 'callers.jsonl')
            cls.entry = Face(entry_app(
                TrustedService(cls.trusted, LocalSigner(cls.trusted)), sessions))
            cls.console = Console(cls.callers, cls.entry.base, 'http://127.0.0.1', timeout=60)
            cls.console.enroll()
            cls.console.start()
            cls.trace_path = cls.callers / 'trace' / 'console.jsonl'
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

    def test_a_step_and_the_endpoint_that_signed_it_share_one_id(self):
        submitted = self.client.post('/console/api/submit',
                                     json={'profile': 'PAY-1'},
                                     headers={'x-zjj-trace': 'page-1'})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.headers.get('x-zjj-trace'), 'page-1')
        operation_id = submitted.json()['operation_id']
        stepped = self.client.post('/console/api/step',
                                   json={'side': 'H', 'operation_id': operation_id,
                                         'step': 'prepare'},
                                   headers={'x-zjj-trace': 'page-2'})
        self.assertEqual(stepped.status_code, 200, stepped.text)
        lines = [line for line in read_trace(self.trace_path)
                 if line.get('id') in ('page-1', 'page-2')]
        self.assertEqual([line['id'] for line in lines], ['page-1', 'page-2'])
        spans = [span['name'] for span in lines[1]['spans']]
        self.assertEqual(spans, ['console.step', 'entry.challenge', 'endpoint.proof',
                                 'endpoint.sign', 'entry.prove'])
        # The endpoint's own move is in there, with the role it signed as.
        sign = [span for span in lines[1]['spans'] if span['name'] == 'endpoint.sign'][0]
        self.assertEqual(sign['role'], 'H')

    def test_a_call_without_an_id_is_given_one_and_told_which(self):
        reply = self.client.get('/console/api/status')
        self.assertEqual(reply.status_code, 200, reply.text)
        given = reply.headers.get('x-zjj-trace')
        self.assertTrue(given)
        self.assertIn(given, [line['id'] for line in read_trace(self.trace_path)])

    def test_a_read_that_fails_is_still_a_line(self):
        reply = self.client.post('/console/api/step',
                                 json={'side': 'H', 'operation_id': 'nope',
                                       'step': 'prepare'},
                                 headers={'x-zjj-trace': 'page-bad'})
        self.assertEqual(reply.status_code, 403, reply.text)
        line = [line for line in read_trace(self.trace_path)
                if line.get('id') == 'page-bad'][0]
        self.assertEqual(line['status'], 403)

    def test_the_page_s_own_events_are_written_beside_the_server_s(self):
        reply = self.client.post('/console/api/trace', json={
            'page': 'p-1',
            'events': [{'kind': 'action', 'trace': 'page-3', 'ms': 412.5,
                        'side': 'H', 'step': 'prepare'}],
        })
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json(), {'taken': True})
        line = [line for line in read_trace(self.trace_path)
                if line.get('source') == 'ui'][0]
        self.assertEqual((line['page'], line['kind'], line['trace'], line['ms']),
                         ('p-1', 'action', 'page-3', 412.5))

    def test_a_page_event_body_that_is_not_the_trace_s_own_is_refused(self):
        # The field set is refused the way every other console body is; a body
        # with the right fields and the wrong shapes is refused under the trace's
        # own name, so a page can tell the two apart.
        for body, deny in (({'page': 'p', 'events': 'x'}, 'CONSOLE_TRACE'),
                           ({'page': 1, 'events': []}, 'CONSOLE_TRACE'),
                           ({'page': 'p'}, 'CONSOLE_FIELDS'),
                           ({'page': 'p', 'events': [1]}, 'CONSOLE_TRACE')):
            with self.subTest(body=body):
                reply = self.client.post('/console/api/trace', json=body)
                self.assertEqual(reply.status_code, 403, reply.text)
                self.assertEqual(reply.json(), {'deny': deny})

    def test_the_console_does_not_trace_a_non_api_route(self):
        # The page's own static files are not calls; writing a line per asset
        # would bury the calls that matter.
        before = len(read_trace(self.trace_path))
        self.client.get('/console/healthz')
        self.assertEqual(len(read_trace(self.trace_path)), before)


if __name__ == '__main__':
    unittest.main()
