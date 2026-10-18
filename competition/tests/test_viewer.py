"""The display gateway: it carries the four read routes, and nothing else.

Five claims:

* the page is served, and the four observation routes are carried to the entry
  with the gateway's own observer credential -- the browser sends none;
* the gateway is not a way to drive the protocol: a submit is not carried, and an
  observation path that is not one of the four is refused;
* the push channel survives the hop: an SSE frame comes through the gateway;
* the session is kept fresh: a token the entry will not take costs one re-proof,
  not a broken page;
* the observer side is the entry's rule, not the gateway's promise: a gateway
  built on a key with no ``observer`` side is refused by the entry itself.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx

from competition.caller import announce
from competition.caller.session import Session
from competition.deploy.demo import add_line
from competition.deploy.viewer import ObserverSession, make_viewer
from competition.profiles.w_seed import initialize
from competition.server.service import STEPS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import b64, canonical
from competition.tests.helpers import Face, body
from competition.web.app import make_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
PROFILE = 'PAY-1'


class ViewerTests(unittest.TestCase):
    """One served entry, one run of events, and the gateway in front of it."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        root = Path(cls.work.name)
        cls.wrun = initialize(root / 'w')
        cls.service = TrustedService(cls.wrun, LocalSigner(cls.wrun))
        # The gateway makes its own credential in a run, so the test's allowlist is
        # built the same way: announce the key, then list the line it returned.
        cls.callers = root / 'callers'
        cls.callers.mkdir(parents=True, exist_ok=True)
        add_line(cls.callers, announce(cls.callers, 'observer-1', ['observer']))
        add_line(cls.callers, announce(cls.callers, 'caller-h', ['H']))
        add_line(cls.callers, announce(cls.callers, 'caller-worker', ['worker']))
        cls.sessions = Sessions(read_callers(cls.callers / 'callers.jsonl'))
        cls.entry = Face(make_app(cls.service, cls.sessions))
        cls.holder = Session(cls.entry.base, cls.callers / 'caller-h.key')
        cls.holder.open()
        cls.worker = Session(cls.entry.base, cls.callers / 'caller-worker.key')
        cls.worker.open()
        # One whole flow, so the read routes have a committed operation to carry.
        cls.operation_id = cls.run_flow()
        # A built page, so the same mount the deployment makes is tested here.
        cls.dist = root / 'dist'
        cls.dist.mkdir()
        (cls.dist / 'index.html').write_text(
            '<!doctype html><div id="app"></div>\n', encoding='utf-8')
        cls.observer = ObserverSession(cls.entry.base, cls.callers / 'observer-1.key')
        cls.viewer = Face(make_viewer(cls.entry.base, cls.observer, cls.dist))

    @classmethod
    def tearDownClass(cls):
        cls.viewer.close()
        cls.entry.close()
        cls.wrun.close()
        cls.work.cleanup()

    # -- one whole flow, so the face has a committed operation --------------
    @classmethod
    def proof(cls, step, challenge):
        role, domain = STEPS[step][2], STEPS[step][3]
        key = (cls.wrun.worker_key if role == 'worker'
               else cls.wrun.actors[PROFILE][role].key)
        return {'claim': challenge, 'signature': b64(key.sign(canonical([domain, challenge])))}

    @classmethod
    def run_flow(cls):
        submitted = cls.entry.post('/api/submit', body(profile=PROFILE, intent=None),
                                   {'authorization': 'Bearer ' + cls.holder.token}).json()
        operation_id = submitted['operation_id']
        for step, token in (('prepare', cls.holder.token), ('accept', cls.holder.token),
                            ('claim', cls.worker.token), ('exec', cls.worker.token),
                            ('settle', cls.worker.token), ('status', cls.holder.token)):
            asked = cls.entry.post('/api/challenge', body(operation_id=operation_id, step=step),
                                   {'authorization': 'Bearer ' + token}).json()
            proved = cls.entry.post('/api/prove',
                                    body(operation_id=operation_id, step=step,
                                         proof=cls.proof(step, asked['claim'])),
                                    {'authorization': 'Bearer ' + token})
            assert proved.status_code == 200, (step, proved.text)
        return operation_id

    # -- the page, and the routes behind it ---------------------------------
    def test_the_page_shell_is_served(self):
        reply = httpx.get(self.viewer.base + '/', timeout=5.0)
        self.assertEqual(reply.status_code, 200)
        self.assertIn('id="app"', reply.text)

    def test_the_read_routes_are_carried_without_a_browser_credential(self):
        reply = httpx.get(self.viewer.base + '/api/observe/events', timeout=5.0)
        self.assertEqual(reply.status_code, 200)
        listed = reply.json()
        self.assertTrue(listed['events'])
        self.assertIsInstance(listed['last'], int)

    def test_the_operations_routes_are_carried(self):
        listed = httpx.get(self.viewer.base + '/api/observe/operations', timeout=5.0)
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(listed.json()['operations'])
        oid = listed.json()['operations'][0]['operation_id']
        one = httpx.get(self.viewer.base + '/api/observe/operations/' + oid, timeout=5.0)
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.json()['operation_id'], oid)

    def test_healthz_names_the_entry_and_the_observer(self):
        reply = httpx.get(self.viewer.base + '/healthz', timeout=5.0).json()
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['observer'], 'observer-1')

    # -- and nothing else ---------------------------------------------------
    def test_a_submit_is_not_carried(self):
        # The page may not reach anything but the four read routes, so there is no
        # route here for a submit -- and the gateway's own token could not drive
        # one anyway.
        for method in ('get', 'post'):
            reply = httpx.request(method, self.viewer.base + '/api/submit',
                                  content=body(profile=PROFILE, intent=None), timeout=5.0)
            self.assertEqual(reply.status_code, 404, method)

    def test_an_observation_path_that_is_not_one_of_the_four_is_refused(self):
        reply = httpx.get(self.viewer.base + '/api/observe/challenge', timeout=5.0)
        self.assertEqual(reply.status_code, 404)
        self.assertEqual(reply.json()['deny'], 'VIEWER_PATH')

    # -- the push channel ---------------------------------------------------
    def test_a_frame_comes_through_the_gateway(self):
        url = self.viewer.base + '/api/observe/stream?after=0'
        with httpx.stream('GET', url, timeout=10.0) as reply:
            self.assertEqual(reply.status_code, 200)
            for line in reply.iter_lines():
                if line.startswith('data: '):
                    event = json.loads(line[len('data: '):])
                    self.assertIsInstance(event['seq'], int)
                    self.assertTrue(event['not_evidence'])
                    return
        self.fail('no frame came through the gateway')

    # -- the session is kept fresh ------------------------------------------
    def test_a_token_the_entry_will_not_take_costs_one_reproof(self):
        # Hold a token the entry refuses and say it is good for a long time, so the
        # gateway has to find the refusal for itself and prove the key again.
        self.observer.session.token = 'not-a-token'
        self.observer.expires = time.time() + 1e9
        reply = httpx.get(self.viewer.base + '/api/observe/events', timeout=5.0)
        self.assertEqual(reply.status_code, 200)
        self.assertNotEqual(self.observer.session.token, 'not-a-token')

    def test_a_gateway_key_without_the_observer_side_is_refused_by_the_entry(self):
        # The side is the entry's rule.  An H key opens a session, but the entry
        # answers the observation routes with SESSION_SIDE, and the gateway passes
        # that refusal through rather than inventing events.
        holder = ObserverSession(self.entry.base, self.callers / 'caller-h.key')
        face = Face(make_viewer(self.entry.base, holder, self.dist))
        try:
            reply = httpx.get(face.base + '/api/observe/events', timeout=5.0)
            self.assertEqual(reply.status_code, 403)
            self.assertEqual(reply.json()['deny'], 'SESSION_SIDE')
        finally:
            face.close()
