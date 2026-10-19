"""The entry serves its flow on a worker thread, not on the event loop.

The chain is assembled while a person answers G/U/V/X, and that wait is minutes.
If it ran on the loop, every other route -- the observation reads the console
polls included -- would wait with it, which is exactly what made the page look
frozen.  Two claims:

* a flow call in progress does not stop the entry answering another request;
* the three flow calls are still one at a time, so moving them off the loop did
  not quietly turn the trusted side concurrent.
"""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx

from competition.support.wire import ProtocolError
from competition.tests.helpers import Face
from competition.web.app import make_app

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)

# Long enough that a blocked loop would be unmistakable, short enough for a test.
DELAY = 1.0


class SlowService:
    """A service whose three flow calls take a while, and that counts overlap."""

    def __init__(self, path, delay=DELAY):
        self.run = SimpleNamespace(store=SimpleNamespace(path=str(path)))
        self.delay = delay
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.fail = None

    def _work(self):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(self.delay)
        finally:
            with self.lock:
                self.running -= 1

    def submit(self, profile, intent=None, *, announce=None):
        if announce is not None:
            announce(profile, 'op-1')
        self._work()
        if self.fail is not None:
            raise ProtocolError(self.fail)
        return {'operation_id': 'op-1', 'challenge': {}}

    def challenge(self, operation_id, step):
        self._work()
        return {'profile': 'PAY-1', 'claim': {}}

    def prove(self, operation_id, step, proof):
        self._work()
        return {'ok': True}

    def profile_of(self, operation_id):
        return 'PAY-1'


def observable(path):
    """Give a stub service's file the one table the observation face writes."""
    with sqlite3.connect(str(path)) as connection:
        connection.execute('CREATE TABLE a_observe_event('
                           'seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, kind TEXT, '
                           'profile TEXT, operation_id TEXT, blob TEXT)')
    return path


class OpenSessions:
    """Sessions that take any token: the route's own shape is what is under test."""

    def authorize(self, token, side):
        return side

    def challenge(self, kid):
        return 'nonce'

    def open(self, claim, signature):
        return {'token': 't', 'caller': 'c', 'sides': ['H'], 'expires': '0'}


class EntryConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.service = SlowService(observable(Path(self.work.name) / 'observe.sqlite'))
        self.face = Face(make_app(self.service, OpenSessions()))
        self.headers = {'authorization': 'Bearer t'}

    def tearDown(self):
        self.face.close()
        self.work.cleanup()

    def events(self):
        reply = httpx.get(self.face.base + '/api/observe/events', headers=self.headers,
                          timeout=5.0)
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()['events']

    def in_background(self, path, payload):
        thread = threading.Thread(
            target=lambda: httpx.post(self.face.base + path,
                                      content=json.dumps(payload).encode(),
                                      headers=self.headers, timeout=10.0))
        thread.start()
        # Let the flow call be inside the service before asking anything else.
        time.sleep(0.2)
        return thread

    def test_a_flow_call_does_not_stop_the_entry_answering(self):
        cases = (
            ('/api/submit', {'profile': 'PAY-1', 'intent': {}}),
            ('/api/challenge', {'operation_id': 'op-1', 'step': 'prepare'}),
            ('/api/prove', {'operation_id': 'op-1', 'step': 'prepare', 'proof': {}}),
        )
        for path, payload in cases:
            with self.subTest(path=path):
                worker = self.in_background(path, payload)
                started = time.perf_counter()
                reply = httpx.get(self.face.base + '/healthz', timeout=5.0)
                waited = time.perf_counter() - started
                worker.join(timeout=10)
                self.assertEqual(reply.status_code, 200)
                self.assertLess(waited, DELAY / 2, 'healthz waited %.3fs behind %s'
                                % (waited, path))

    def test_the_three_flow_calls_are_still_one_at_a_time(self):
        threads = [
            threading.Thread(
                target=lambda: httpx.post(self.face.base + '/api/submit',
                                          content=json.dumps({'profile': 'PAY-1',
                                                              'intent': {}}).encode(),
                                          headers=self.headers, timeout=10.0))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(self.service.peak, 1)

    def test_a_refused_flow_call_still_answers_from_the_worker(self):
        reply = httpx.post(self.face.base + '/api/challenge',
                           content=b'{"operation_id":"op-1","step":"nope"}',
                           headers=self.headers, timeout=10.0)
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'STEP'})

    def test_the_candidate_is_reported_before_the_chain_is_assembled(self):
        # The whole point: while assembly is still running, a reader already sees
        # what it is being asked to release.
        worker = self.in_background('/api/submit', {'profile': 'PAY-1', 'intent': {}})
        kinds = [event['kind'] for event in self.events()]
        self.assertIn('CANDIDATE_SUBMITTED', kinds)
        self.assertNotIn('CHAIN_ASSEMBLED', kinds, 'assembly had not finished yet')
        worker.join(timeout=10)
        kinds = [event['kind'] for event in self.events()]
        self.assertLess(kinds.index('CANDIDATE_SUBMITTED'), kinds.index('CHAIN_ASSEMBLED'))

    def test_a_candidate_that_never_assembles_says_so(self):
        self.service.fail = 'STATE_UNAVAILABLE'
        reply = httpx.post(self.face.base + '/api/submit',
                           content=json.dumps({'profile': 'PAY-1', 'intent': {}}).encode(),
                           headers=self.headers, timeout=10.0)
        self.assertEqual(reply.status_code, 403, reply.text)
        self.assertEqual(reply.json(), {'deny': 'STATE_UNAVAILABLE'})
        events = self.events()
        denied = [event for event in events if event['kind'] == 'CANDIDATE_DENIED']
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]['status_label'], 'DENIED')
        self.assertEqual(denied[0]['detail']['rule'], 'STATE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
