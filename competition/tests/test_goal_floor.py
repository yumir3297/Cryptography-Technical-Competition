"""GoalFloor integration: shadow, enforce, freshness and atomic rollback.

These tests use the real CommonW/SQLite transaction, the real C publish path and
the real signed acceptance chain.  They do not replace W's guard or the tool.
"""
import json
import tempfile
import unittest
from pathlib import Path

from competition.profiles.w_seed import initialize
from competition.profiles.w_scenarios import register_ind_unit
from competition.support.goal_seed import (current_goal, goal_claim, publish_goal,
                                           update_goal)
from competition.support.wire import ProtocolError

PROFILE = 'IND-DEMO-1'


def _tempdir(test):
    root = Path(__file__).resolve().parents[2] / '.runtime' / 'goal-tests'
    root.mkdir(parents=True, exist_ok=True)
    folder = tempfile.TemporaryDirectory(dir=root)
    test.addCleanup(folder.cleanup)
    return Path(folder.name)


def _accept(run, op):
    ticket = run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))
    return run.w.accept(PROFILE, ticket['ticket_id'],
                        run.accept_proof(PROFILE, ticket['ticket_id']))


def _commit(run, op):
    with run.store.db() as c:
        row = c.execute('SELECT frozen FROM w_operation WHERE profile=? AND oid=?',
                        (PROFILE, op['action']['operation_id'])).fetchone()
        return json.loads(row[0])['commit']


class GoalFloorWTests(unittest.TestCase):
    def _run(self, mode, capacity=2):
        run = initialize(_tempdir(self), resource_capacity={PROFILE: capacity}, goal_mode=mode)
        self.addCleanup(run.close)
        return run

    def _three_actions(self, run):
        second = register_ind_unit(run, unit_id='unit-b', batch_id='batch-b',
                                   principal='principal-b')
        third = register_ind_unit(run, unit_id='unit-c', batch_id='batch-c',
                                  principal='principal-c')
        # Role revisions change when a new unit is registered.  Re-derive every
        # operation after the last C publication so no basis is stale on purpose.
        second = run.fork_operation(PROFILE, second)
        third = run.fork_operation(PROFILE, third)
        first = run.fork_operation(PROFILE)
        return first, second, third

    def _goal(self, run, ops, *, capacity=2, epoch='1'):
        rules = [{'name': 'inspect-a', 'op': ops[0], 'obligation': 'unit-a', 'cost': 1},
                 {'name': 'inspect-b', 'op': ops[1], 'obligation': 'unit-b', 'cost': 1},
                 {'name': 'inspect-c', 'op': ops[2], 'obligation': '', 'cost': 1}]
        claim = goal_claim(run, PROFILE, 'goal-1', rules, capacity=capacity, epoch=epoch)
        return claim, publish_goal(run, PROFILE, claim)

    def test_shadow_accepts_but_records_capacity_floor_conflict(self):
        run = self._run('shadow')
        ops = self._three_actions(run)
        self._goal(run, ops)
        result = _accept(run, ops[2])
        self.assertEqual(result['acceptance_state'], 'COMMITTED')
        witness = _commit(run, ops[2])['value']['goal']
        self.assertEqual((witness['mode'], witness['decision'], witness['reason']),
                         ('shadow', 'F', 'GOAL_CAPACITY_FLOOR'))
        self.assertEqual(run.w.counts()['accepts'], 1)
        self.assertEqual(run.w.counts()['goal_links'], 0)

    def test_enforce_rejects_without_business_side_effect(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        self._goal(run, ops)
        with self.assertRaises(ProtocolError) as error:
            _accept(run, ops[2])
        self.assertEqual(error.exception.code, 'GOAL_CAPACITY_FLOOR')
        counts = run.w.counts()
        self.assertEqual((counts['accepts'], counts['outbox'], counts['attempts'],
                          counts['goal_links']), (0, 0, 0, 0))
        with run.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM w_reservation').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM w_operation').fetchone()[0], 0)

    def test_no_goal_preserves_legacy_commit_shape(self):
        run = self._run('enforce')
        op = run.fork_operation(PROFILE)
        _accept(run, op)
        commit = _commit(run, op)
        self.assertNotIn('goal', commit['value'])
        self.assertEqual(run.w.counts()['accepts'], 1)

    def test_required_action_links_and_settlement_marks_done(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        self._goal(run, ops)
        _accept(run, ops[0])
        witness = _commit(run, ops[0])['value']['goal']
        self.assertEqual((witness['decision'], witness['matched'][0]['obligation']),
                         ('T', 'unit-a'))
        oid = ops[0]['action']['operation_id']
        run.w.claim(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CLAIM'))
        response = run.w.execute_once(PROFILE, oid, run.worker_proof(PROFILE, oid, 'EXECUTE'))
        settled = run.w.settle(PROFILE, oid, response, run.worker_proof(PROFILE, oid, 'SETTLE'))
        self.assertEqual(settled['state'], 'SETTLED')
        self.assertEqual(run.w.counts()['goal_done'], 1)
        # The next required action is now admissible: its own floor remains.
        result = _accept(run, ops[1])
        self.assertEqual(result['acceptance_state'], 'COMMITTED')
        self.assertEqual(run.w.counts()['goal_pending'], 1)

    def test_pending_required_obligation_blocks_a_second_accept(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        self._goal(run, ops)
        _accept(run, ops[0])
        with self.assertRaises(ProtocolError) as error:
            _accept(run, ops[1])
        self.assertEqual(error.exception.code, 'GOAL_PENDING_UNKNOWN')
        self.assertEqual(run.w.counts()['accepts'], 1)
        self.assertEqual(run.w.counts()['goal_pending'], 1)

    def test_cost_claim_must_match_w_plan(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        rules = [{'name': 'inspect-a', 'op': ops[0], 'obligation': 'unit-a', 'cost': 2}]
        claim = goal_claim(run, PROFILE, 'goal-cost', rules, capacity=2)
        publish_goal(run, PROFILE, claim)
        with self.assertRaises(ProtocolError) as error:
            _accept(run, ops[0])
        self.assertEqual(error.exception.code, 'GOAL_COST_MISMATCH')

    def test_dependency_revision_invalidates_goal(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        self._goal(run, ops)
        with run.store.db() as c:
            key = [*(json.loads(c.execute('SELECT key FROM w_resource WHERE profile=?',
                                          (PROFILE,)).fetchone()[0])[:3]), ops[0]['task_id']]
            record = run.store.current(c, PROFILE, 'TASK', key)['record']
        run.base.publish(PROFILE, 'TASK', key, record)
        # The operation itself is re-derived against the new Task, so the old
        # legacy guard passes; only the GoalFloor dependency is stale.
        refreshed = run.fork_operation(PROFILE, ops[0])
        with self.assertRaises(ProtocolError) as error:
            _accept(run, refreshed)
        self.assertEqual(error.exception.code, 'GOAL_DEPS_STALE')

    def test_goal_epoch_update_replaces_the_certified_ref(self):
        run = self._run('shadow')
        ops = self._three_actions(run)
        claim, first_ref = self._goal(run, ops)
        current, revision = current_goal(run, PROFILE, 'goal-1')
        new_claim = goal_claim(run, PROFILE, 'goal-1',
                               [{'name': 'inspect-a', 'op': ops[0], 'obligation': 'unit-a', 'cost': 1},
                                {'name': 'inspect-b', 'op': ops[1], 'obligation': 'unit-b', 'cost': 1},
                                {'name': 'inspect-c', 'op': ops[2], 'obligation': '', 'cost': 1}],
                               capacity=2, epoch=str(int(current['epoch']) + 1))
        second_ref = update_goal(run, PROFILE, 'goal-1', new_claim)
        self.assertNotEqual(first_ref, second_ref)
        _accept(run, ops[0])
        witness = _commit(run, ops[0])['value']['goal']
        self.assertIn(second_ref, witness['goal_refs'])
        self.assertNotIn(first_ref, witness['goal_refs'])

    def test_goal_epoch_cannot_remove_an_obligation(self):
        run = self._run('shadow')
        ops = self._three_actions(run)
        self._goal(run, ops)
        current, revision = current_goal(run, PROFILE, 'goal-1')
        rules = [{'name': 'inspect-a', 'op': ops[0], 'obligation': 'unit-a', 'cost': 1},
                 {'name': 'inspect-c', 'op': ops[2], 'obligation': '', 'cost': 1}]
        claim = goal_claim(run, PROFILE, 'goal-1', rules, capacity=2,
                           epoch=str(revision + 1))
        with self.assertRaises(ProtocolError) as error:
            update_goal(run, PROFILE, 'goal-1', claim)
        self.assertEqual(error.exception.code, 'GOAL_MIGRATION_REQUIRED')

    def test_concurrent_required_actions_have_one_winner(self):
        run = self._run('enforce')
        ops = self._three_actions(run)
        self._goal(run, ops)
        prepared = []
        for op in (ops[0], ops[1]):
            ticket = run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))
            prepared.append((ticket['ticket_id'], run.accept_proof(PROFILE, ticket['ticket_id'])))
        from concurrent.futures import ThreadPoolExecutor
        def attempt(item):
            try:
                return ('ok', run.w.accept(PROFILE, item[0], item[1])['acceptance_state'])
            except ProtocolError as exc:
                return ('rejected', exc.code)
        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(attempt, prepared))
        self.assertEqual(sum(kind == 'ok' for kind, _ in outcomes), 1, outcomes)
        self.assertIn(('rejected', 'GOAL_PENDING_UNKNOWN'), outcomes)
        self.assertEqual(run.w.counts()['accepts'], 1)
        self.assertEqual(run.w.counts()['goal_pending'], 1)
