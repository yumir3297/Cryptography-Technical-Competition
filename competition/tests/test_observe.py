"""The observation face: a read-only, redacted, pushable view of every step.

Five claims:

* the observer side reads and drives nothing: only the four ``/api/observe``
  routes are open to it, and an H or worker token cannot read them;
* every committed step is observable, from the entry's own candidate submission
  and the Resolver's assembly through the core's prepare, accept, claim, execute,
  settle and read -- and the entry's flow events are marked non-authoritative;
* nothing sensitive leaves: no business payload, nonce, session id, signature or
  private material appears in any event or snapshot;
* reading the face changes no fact: the W tables and ``a_journal`` are byte-for-
  byte unchanged, and no nonce is consumed;
* the publish log is a separate table, so ``a_journal`` carries none of the
  observation-only step names.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx

from competition.profiles.w_seed import initialize
from competition.server.export import forbidden_secrets
from competition.server.observe import ObservationFeed
from competition.server.service import STEPS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import b64, canonical
from competition.tests.helpers import Face, body, caller_of, make_callers
from competition.web.app import make_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
PROFILE = 'PAY-1'
# Observation-only step names that must never appear in the core's own journal.
OBSERVE_ONLY = ('PREPARED', 'CHALLENGE_ISSUED', 'ACCEPT_COMMITTED', 'RECEIPT_SIGNED',
                'RECEIPT_PENDING', 'CLAIMED', 'EXEC_DISPATCHED', 'QUERY_DISPATCHED',
                'TOOL_RESPONDED', 'SETTLED', 'CANCELED', 'HALTED', 'READ_PROJECTED',
                'CANDIDATE_SUBMITTED', 'CHAIN_ASSEMBLED', 'STEP_CHALLENGED', 'STEP_PROVED')


class ObserveFaceTests(unittest.TestCase):
    """One initialized W, one whole flow, and the read-only face over it."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.wrun = initialize(Path(cls.work.name) / 'w')
        cls.service = TrustedService(cls.wrun, LocalSigner(cls.wrun))
        cls.callers_path, cls.keys = make_callers(
            Path(cls.work.name) / 'callers',
            [('caller-h', ['H']), ('caller-worker', ['worker']), ('observer-1', ['observer'])])
        cls.sessions = Sessions(read_callers(cls.callers_path))
        cls.face = Face(make_app(cls.service, cls.sessions))
        cls.feed = ObservationFeed(cls.wrun.store.path)
        cls.profile = PROFILE
        cls.observer = cls.session('observer-1')
        cls.holder = cls.session('caller-h')
        cls.worker = cls.session('caller-worker')
        cls.operation_id = cls.run_flow()

    @classmethod
    def tearDownClass(cls):
        cls.face.close()
        cls.wrun.close()
        cls.work.cleanup()

    # -- helpers ------------------------------------------------------------
    @classmethod
    def session(cls, name):
        caller = caller_of(cls.keys[name])
        challenge = cls.face.post('/session', body(kid=caller['kid'])).json()['challenge']
        opened = cls.face.post('/session/prove',
                               body(claim=challenge, signature=caller['sign'](challenge)))
        return opened.json()['token']

    @classmethod
    def proof(cls, step, challenge):
        role, domain = STEPS[step][2], STEPS[step][3]
        key = cls.wrun.worker_key if role == 'worker' else cls.wrun.actors[cls.profile][role].key
        return {'claim': challenge, 'signature': b64(key.sign(canonical([domain, challenge])))}

    @classmethod
    def run_flow(cls):
        submitted = cls.face.post('/api/submit', body(profile=cls.profile, intent=None),
                                  {'authorization': 'Bearer ' + cls.holder}).json()
        operation_id = submitted['operation_id']
        for step, token in (('prepare', cls.holder), ('accept', cls.holder),
                            ('claim', cls.worker), ('exec', cls.worker),
                            ('settle', cls.worker), ('status', cls.holder)):
            asked = cls.face.post('/api/challenge', body(operation_id=operation_id, step=step),
                                  {'authorization': 'Bearer ' + token}).json()
            proved = cls.face.post('/api/prove',
                                   body(operation_id=operation_id, step=step,
                                        proof=cls.proof(step, asked['claim'])),
                                   {'authorization': 'Bearer ' + token})
            assert proved.status_code == 200, (step, proved.text)
        return operation_id

    def observe(self, path, token=None):
        headers = {'authorization': 'Bearer ' + (token or self.observer)}
        return self.face.get(path, headers)

    def events(self, **params):
        query = '&'.join('%s=%s' % (k, v) for k, v in params.items())
        return self.observe('/api/observe/events' + ('?' + query if query else '')).json()

    def last_seq(self):
        return self.events(limit=1000)['last']

    def dump(self):
        """Every fact table the face must not touch, as tuples."""
        tables = ('w_operation', 'w_outbox', 'w_settlement', 'w_nonce',
                  'a_journal', 'a_observe_event')
        with self.wrun.store.db() as c:
            return {t: [tuple(row) for row in c.execute('SELECT * FROM ' + t)] for t in tables}

    # -- the observer reads and drives nothing ------------------------------
    def test_only_an_observer_may_read_the_face(self):
        for token in (self.holder, self.worker):
            reply = self.observe('/api/observe/events', token)
            self.assertEqual(reply.status_code, 403)
            self.assertEqual(reply.json(), {'deny': 'SESSION_SIDE'})
        self.assertEqual(self.face.get('/api/observe/events').status_code, 401)

    def test_the_observer_cannot_drive_a_step(self):
        reply = self.face.post('/api/prove', body(operation_id=self.operation_id, step='exec',
                                                  proof={}),
                               {'authorization': 'Bearer ' + self.observer})
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'SESSION_SIDE'})

    def test_the_four_read_routes_answer_the_observer(self):
        self.assertEqual(self.observe('/api/observe/events').status_code, 200)
        self.assertEqual(self.observe('/api/observe/operations').status_code, 200)
        self.assertEqual(
            self.observe('/api/observe/operations/' + self.operation_id).status_code, 200)
        reply = self.observe('/api/observe/operations/never-committed')
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(reply.json(), {'deny': 'OPERATION_UNKNOWN'})

    # -- every step is observable -------------------------------------------
    def test_the_flow_is_observable_end_to_end(self):
        kinds = {event['kind'] for event in self.events(limit=1000)['events']}
        for kind in ('CANDIDATE_SUBMITTED', 'CHAIN_ASSEMBLED', 'STEP_CHALLENGED',
                     'STEP_PROVED', 'PREPARED', 'CHALLENGE_ISSUED',
                     'ACCEPT_COMMITTED', 'RECEIPT_SIGNED', 'CLAIMED', 'EXEC_DISPATCHED',
                     'TOOL_RESPONDED', 'SETTLED', 'READ_PROJECTED',
                     'CONTROL_PUBLISHED', 'W_BOOTSTRAP', 'W_RESOURCE', 'W_TOOL'):
            self.assertIn(kind, kinds)
        entry = [event for event in self.events(limit=1000)['events']
                 if event['kind'] == 'STEP_PROVED']
        self.assertTrue(entry and all(event.get('flow') is True and event['source'] == 'ENTRY'
                                      for event in entry))

    def test_the_snapshot_reports_current_state_without_payload(self):
        view = self.observe('/api/observe/operations/' + self.operation_id).json()
        self.assertEqual(view['dispatch_state'], 'SETTLED')
        self.assertEqual(view['effect_state'], 'SUCCEEDED')
        self.assertEqual(view['receipt_state'], 'SIGNED')
        self.assertTrue(view['exec_consumed'])
        self.assertIsNotNone(view['final_fact_id'])
        self.assertTrue(view['not_evidence'])
        self.assertEqual(view['view_kind'], 'OBSERVATION_PROJECTION')
        self.assertTrue(any(event['kind'] == 'SETTLED' for event in view['events']))

    # -- nothing sensitive leaves -------------------------------------------
    def test_every_projection_is_redacted(self):
        events = self.events(limit=1000)
        self.assertEqual(forbidden_secrets(events), [])
        blob = json.dumps(events, ensure_ascii=False)
        for token in ('"payload"', '"nonce"', '"session_id"', '"signature"', '.key', '.sqlite'):
            self.assertNotIn(token, blob)
        view = self.observe('/api/observe/operations/' + self.operation_id).json()
        self.assertEqual(forbidden_secrets(view), [])

    # -- reading changes no fact --------------------------------------------
    def test_reading_the_face_does_not_change_any_fact(self):
        before = self.dump()
        self.events(limit=1000)
        self.observe('/api/observe/operations')
        self.observe('/api/observe/operations/' + self.operation_id)
        after = self.dump()
        self.assertEqual(before, after)

    def test_no_observation_step_name_enters_the_core_journal(self):
        with self.wrun.store.db() as c:
            kinds = {row[0] for row in c.execute('SELECT kind FROM a_journal')}
        self.assertTrue(set(OBSERVE_ONLY).isdisjoint(kinds), set(OBSERVE_ONLY) & kinds)

    def test_the_guard_and_publication_paths_are_observable(self):
        """The other authorization entrance publishes its own two events."""
        base = self.wrun.base
        profile = 'IND-DEMO-1'
        op = base.operations[profile]
        result = base.service.guard(profile, op, base.identity_proof(profile, op))
        self.assertEqual(result['decision'], 'T')
        base.deny(profile, op)
        kinds = {event['kind'] for event in
                 self.events(operation_id=result['operation_id'], limit=1000)['events']}
        self.assertIn('AUTHORIZED_GUARD', kinds)
        self.assertIn('PUBLICATION', kinds)

    # -- the cursor ---------------------------------------------------------
    def test_the_cursor_is_monotonic_and_filterable(self):
        first = self.events(after=0, limit=10)
        again = self.events(after=first['events'][-1]['seq'], limit=10)
        self.assertTrue(all(event['seq'] > first['events'][-1]['seq']
                            for event in again['events']))
        filtered = self.events(operation_id=self.operation_id, limit=1000)
        self.assertTrue(filtered['events'])
        self.assertTrue(all(event['operation_id'] == self.operation_id
                            for event in filtered['events']))
        profile_events = self.events(profile=PROFILE, limit=1000)['events']
        self.assertTrue(any(event['source'] == 'ENTRY' for event in profile_events))

    # -- push channel -------------------------------------------------------
    def test_the_stream_delivers_committed_frames(self):
        after = self.last_seq()
        self.feed.publish('STEP_PROVED', PROFILE, 'observe-stream-marker',
                          {'stage': '某角色签名并交回', 'lanes': ['编排器', '签署端'],
                           'detail': {'step': 'status', 'role': 'H'}})
        gen = self.feed.stream(after=after, poll=0.01, ping=100.0)
        try:
            frame = next(gen)
        finally:
            gen.close()
        self.assertTrue(frame.startswith('id: '))
        self.assertIn('"kind": "STEP_PROVED"', frame)
        self.assertIn('"flow": true', frame)
        self.assertTrue(frame.endswith('\n\n'))

    def test_an_idle_stream_pings(self):
        after = self.last_seq()
        gen = self.feed.stream(after=after, poll=0.005, ping=0.02)
        try:
            frame = next(gen)
        finally:
            gen.close()
        self.assertEqual(frame, ': ping\n\n')

    def test_the_stream_route_speaks_sse(self):
        after = self.last_seq()
        self.feed.publish('STEP_PROVED', PROFILE, 'observe-sse-route-marker',
                          {'stage': '某角色签名并交回', 'lanes': ['编排器', '签署端'],
                           'detail': {'step': 'status', 'role': 'H'}})
        url = self.face.base + '/api/observe/stream?after=%d' % after
        with httpx.stream('GET', url, headers={'authorization': 'Bearer ' + self.observer},
                          timeout=5.0) as reply:
            self.assertEqual(reply.status_code, 200)
            self.assertTrue(reply.headers['content-type'].startswith('text/event-stream'))
            lines = []
            for line in reply.iter_lines():
                lines.append(line)
                if len(lines) >= 3:
                    break
        self.assertTrue(lines[0].startswith('id: '))
        self.assertIn('"kind": "STEP_PROVED"', lines[1])
        self.assertEqual(lines[2], '')

    # -- the deployment watcher reads the same live stream ------------------
    def test_the_deployment_watcher_reads_the_live_stream(self):
        from types import SimpleNamespace
        from competition.deploy import observer
        steps = observer.watch(SimpleNamespace(token=self.observer), self.face.base, until=10.0)
        self.assertGreater(steps, 0)

    # -- the entry side is best-effort --------------------------------------
    def test_entry_publish_never_raises(self):
        feed = ObservationFeed('/nonexistent-directory-xyz/observe.sqlite')
        self.assertFalse(feed.publish('STEP_PROVED', PROFILE, 'op', {'stage': 'x'}))


if __name__ == '__main__':
    unittest.main()
