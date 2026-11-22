from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

from competition.core.trusted_state import prefix
from competition.profiles.w_scenarios import register_ind_unit, register_release_batch
from competition.profiles.w_seed import initialize
from competition.support.wire import ProtocolError, sortset
from competition.verify_industrial_completion import verify
from competition.w_cases import _configure_tool


PROFILE = 'IND-DEMO-1'


class IndustrialTaskCompletionTests(unittest.TestCase):
    def build(self, capacity):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        run = initialize(Path(folder.name), ind_label='DEMO_NORMAL',
                         resource_capacity={PROFILE: capacity})
        self.addCleanup(run.close)
        first, second = register_release_batch(run)
        return run, first, second

    def prepare(self, run, op):
        return run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))['ticket_id']

    def accept(self, run, ticket):
        return run.w.accept(PROFILE, ticket, run.accept_proof(PROFILE, ticket))

    def test_both_release_steps_fit(self):
        run, op, second = self.build(2)
        ticket = self.prepare(run, op)
        view = self.accept(run, ticket)
        self.assertEqual(view['acceptance_state'], 'COMMITTED')
        self.assertEqual(self.accept(run, ticket)['acceptance'], view['acceptance'])
        oid = op['action']['operation_id']
        audit = run.w.audit(PROFILE, oid, run.read_proof(PROFILE, oid, 'AUDIT'))
        pins = {'c_public': run.root.public_key().public_bytes_raw(),
                'x_public': run.actors[PROFILE]['X'].pub, 'e_public': run.actors[PROFILE]['E'].pub}
        self.assertEqual(verify(audit, **pins)['path'], ['unit-a', 'unit-b'])
        edited = deepcopy(audit)
        edited['completion_basis']['path'].pop()
        with self.assertRaisesRegex(ProtocolError, '^COMPLETION_BINDING$'):
            verify(edited, **pins)

        run.w.claim(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CLAIM'))
        response = run.w.execute_once(PROFILE, oid, run.worker_proof(PROFILE, oid, 'EXECUTE'))
        self.assertEqual(response['state'], 'SUCCEEDED')
        for existing in (False, True):
            result = run.w.settle(PROFILE, oid, response, run.worker_proof(PROFILE, oid, 'SETTLE'))
            self.assertEqual((result['state'], result['existing']), ('SETTLED', existing))
        second = self.same_task(run, op, second)
        self.assertEqual(self.accept(run, self.prepare(run, second))['acceptance_state'], 'COMMITTED')
        second_oid = second['action']['operation_id']
        audit = run.w.audit(PROFILE, second_oid, run.read_proof(PROFILE, second_oid, 'AUDIT'))
        self.assertEqual(verify(audit, **pins)['path'], ['unit-b'])
        self.assertEqual(audit['completion_basis']['completed'][0]['unit_id'], 'unit-a')
        self.assertEqual(audit['completion_basis']['resource']['spent'], '1')

    def same_task(self, run, first, second):
        second['task_id'] = first['task_id']
        second['action']['principal'] = first['action']['principal']
        return run.fork_operation(PROFILE, second)

    def test_single_step_fits_but_entire_task_does_not(self):
        run, op, _ = self.build(1)
        self.assert_completion_rejected(run, self.prepare(run, op), 0)

    def test_unknown_competing_commitment_counts_after_prepare(self):
        run, op, second = self.build(2)
        ticket = self.prepare(run, op)
        self.accept(run, self.prepare(run, second))
        oid = second['action']['operation_id']
        run.w.claim(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CLAIM'))
        unknown = run.w.settle(PROFILE, oid, {'record': None}, run.worker_proof(PROFILE, oid, 'SETTLE'))
        self.assertTrue(unknown['reservation_retained'])
        self.assert_completion_rejected(run, ticket, 1)

    def test_same_task_unknown_commitment_blocks_completion_until_reconciled(self):
        run, first, second = self.build(2)
        first_oid = first['action']['operation_id']
        self.assertEqual(self.accept(run, self.prepare(run, first))['acceptance_state'], 'COMMITTED')
        claim = run.w.claim(PROFILE, first_oid, run.worker_proof(PROFILE, first_oid, 'CLAIM'))
        _configure_tool(run, PROFILE, crash_after_commit=True)
        lost = run.w.execute_once(PROFILE, first_oid, run.worker_proof(PROFILE, first_oid, 'EXECUTE'))
        self.assertEqual(lost['state'], 'EFFECT_UNKNOWN')
        self.assertIsNone(lost['record'])
        unknown = run.w.settle(PROFILE, first_oid, lost, run.worker_proof(PROFILE, first_oid, 'SETTLE'))
        self.assertEqual((unknown['state'], unknown['reservation_retained']), ('UNKNOWN', True))

        # Sign after the first acceptance so the second Basis carries current Behavior.
        second = self.same_task(run, first, second)
        second_oid = second['action']['operation_id']
        self.assertEqual(second['task_id'], first['task_id'])
        self.assertEqual(second['basis']['value']['task_ref'], first['basis']['value']['task_ref'])
        ticket = self.prepare(run, second)
        with run.store.db() as conn:
            row = conn.execute(
                'SELECT o.effect_state, r.state, r.amount, b.attempt_id FROM w_operation o '
                'JOIN w_reservation r ON r.profile=o.profile AND r.oid=o.oid '
                'JOIN w_outbox b ON b.profile=o.profile AND b.oid=o.oid WHERE o.oid=?',
                (first_oid,)).fetchone()
            self.assertEqual(tuple(row), ('UNKNOWN', 'RESERVED', 1, claim['attempt_id']))
            self.assertEqual(tuple(conn.execute(
                'SELECT capacity, reserved, spent FROM w_resource WHERE profile=? AND reserved=1',
                (PROFILE,)).fetchone()), (2, 1, 0))
        with self.assertRaisesRegex(ProtocolError, '^TASK_COMPLETION_PENDING_UNKNOWN$'):
            self.accept(run, ticket)
        with run.store.db() as conn:
            for table in ('w_operation', 'w_reservation', 'w_outbox'):
                self.assertEqual(conn.execute('SELECT oid FROM ' + table).fetchone()[0], first_oid)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 1)
                self.assertIsNone(conn.execute('SELECT 1 FROM ' + table + ' WHERE oid=?',
                                               (second_oid,)).fetchone())
            self.assertEqual(conn.execute('SELECT state FROM w_reservation WHERE oid=?',
                                          (first_oid,)).fetchone()[0], 'RESERVED')

        recovered = run.w.query_attempt(PROFILE, first_oid, run.worker_proof(PROFILE, first_oid, 'QUERY'))
        self.assertEqual(recovered['state'], 'SUCCEEDED')
        settled = run.w.settle(PROFILE, first_oid, recovered, run.worker_proof(PROFILE, first_oid, 'SETTLE'))
        self.assertEqual(settled['state'], 'SETTLED')
        with run.store.db() as conn:
            self.assertEqual(conn.execute('SELECT state FROM w_reservation WHERE oid=?',
                                          (first_oid,)).fetchone()[0], 'SPENT')
        retry = run.fork_operation(PROFILE, second)
        self.assertEqual(self.accept(run, self.prepare(run, retry))['acceptance_state'], 'COMMITTED')

    def test_permitted_cancellation_restores_competing_capacity(self):
        run, op, second = self.build(2)
        self.accept(run, self.prepare(run, second))
        oid = second['action']['operation_id']
        run.base.update_role(PROFILE, 'G', active=False)
        result = run.w.cancel(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CANCEL'))
        self.assertEqual((result['dispatch_state'], result['effect_state']), ('CANCELED', 'NO_EFFECT'))
        run.base.update_role(PROFILE, 'G')
        # The canceled unit remains stopped. C certifies a fresh member.
        third = register_ind_unit(run, unit_id='unit-c', batch_id='batch-c', principal='principal-c')
        key = prefix(PROFILE) + [op['task_id']]
        with run.store.db() as conn:
            task = run.store.current(conn, PROFILE, 'TASK', key)['record']
            other = run.store.current(conn, PROFILE, 'TASK', prefix(PROFILE) + [third['task_id']])['record']
        task['value'].update(task_revision='3', allowed_units=sortset(
            [u for u in task['value']['allowed_units'] if u['unit_id'] == 'unit-a'] +
            other['value']['allowed_units']))
        run.base.publish(PROFILE, 'TASK', key, task)
        op = run.fork_operation(PROFILE, op)
        self.assertEqual(self.accept(run, self.prepare(run, op))['acceptance_state'], 'COMMITTED')
        with run.store.db() as conn:
            self.assertEqual(conn.execute('SELECT state FROM w_reservation WHERE oid=?',
                                          (oid,)).fetchone()[0], 'CANCELED')

    def test_policy_revision_invalidates_prepared_candidate(self):
        run, op, _ = self.build(2)
        ticket = self.prepare(run, op)
        with run.store.db() as conn:
            policy = run.store.current(conn, PROFILE, 'POLICY', prefix(PROFILE))['record']
        policy['value']['policy_revision'] = '2'
        run.base.publish(PROFILE, 'POLICY', prefix(PROFILE), policy)
        with self.assertRaisesRegex(ProtocolError, '^STALE$'):
            self.accept(run, ticket)
        self.assertEqual(run.w.counts()['accepts'], 0)

    def test_task_revision_invalidates_prepared_candidate(self):
        run, op, _ = self.build(2)
        ticket = self.prepare(run, op)
        key = prefix(PROFILE) + [op['task_id']]
        with run.store.db() as conn:
            task = run.store.current(conn, PROFILE, 'TASK', key)['record']
        task['value']['task_revision'] = '3'
        run.base.publish(PROFILE, 'TASK', key, task)
        with self.assertRaisesRegex(ProtocolError, '^ASSESSMENT_MISMATCH$'):
            self.accept(run, ticket)
        self.assertEqual(run.w.counts()['accepts'], 0)

    def test_future_unit_no_longer_ready_even_with_capacity_remaining(self):
        run, op, second = self.build(3)
        ticket = self.prepare(run, op)
        self.assertEqual(self.accept(run, self.prepare(run, second))['acceptance_state'], 'COMMITTED')
        self.assert_completion_rejected(run, ticket, 1)

    def test_two_candidates_for_one_batch_share_one_flight(self):
        run, first, second = self.build(2)
        second = self.same_task(run, first, second)
        tickets = [self.prepare(run, op) for op in (first, second)]
        proofs = [run.accept_proof(PROFILE, ticket) for ticket in tickets]

        def attempt(ticket, proof):
            try:
                return run.w.accept(PROFILE, ticket, proof)['acceptance_state']
            except ProtocolError as exc:
                return exc.code

        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(attempt, t, p) for t, p in zip(tickets, proofs)]
            outcomes = [result.result() for result in results]
        self.assertEqual(outcomes.count('COMMITTED'), 1, outcomes)
        self.assertIn(next(r for r in outcomes if r != 'COMMITTED'),
                      {'DEP_CONFLICT', 'BASIS_BINDING', 'TASK_FLIGHT_LIMIT'})
        with run.store.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM w_reservation WHERE state='RESERVED'").fetchone()[0], 1)

    def assert_completion_rejected(self, run, ticket, committed):
        with self.assertRaisesRegex(ProtocolError, '^TASK_COMPLETION_UNREACHABLE$'):
            self.accept(run, ticket)
        with run.store.db() as conn:
            for table in ('w_operation', 'w_reservation', 'w_outbox'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], committed)
