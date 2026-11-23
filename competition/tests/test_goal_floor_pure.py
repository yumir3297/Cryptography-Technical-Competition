"""Pure GoalFloor decisions: one necessary resource-floor condition, no planner."""
import unittest

from competition.core.goal_floor import evaluate, goal_ref, validate_claim
from competition.support.wire import ProtocolError, digest

PROFILE = 'IND-DEMO-1'
RESOURCE = ['lab', 't', 'industrial', 'r']


class GoalFloorPureTests(unittest.TestCase):
    def _goal(self, group, actions, capacity=3):
        digests = [digest(['TEST-SEL', group, str(i)]) for i in range(len(actions))]
        claim = {'model': 'goal-floor-v1', 'group': group, 'epoch': '1',
                 'resource_key': RESOURCE, 'unit': 'UNIT', 'capacity': str(capacity),
                 'deps': [{'namespace': 'POLICY', 'key': ['lab', 't', 'industrial'],
                           'revision': '1', 'ref': 'p' * 43}],
                 'actions': [{'name': 'a-' + str(i), 'profile': PROFILE,
                              'action_digest': digests[i],
                              'obligation': obligation, 'cost': str(cost)}
                             for i, (obligation, cost) in enumerate(actions)]}
        return {'ref': goal_ref(PROFILE, claim), 'claim': claim, 'selectors': digests}

    @staticmethod
    def _candidate(goal, cost=1, selector=None):
        return {'cost': cost, 'resource_key': RESOURCE, 'unit': 'UNIT',
                'selector': selector if selector is not None else goal['selectors'][0]}

    def test_floor_is_a_necessary_not_sufficient_condition(self):
        goal = self._goal('g', [('one', 1), ('two', 1)], capacity=3)
        decision = evaluate(PROFILE, [goal], {}, capacity=3, spent=0, reserved=0,
                            candidate=self._candidate(goal))
        self.assertEqual((decision['decision'], decision['reason']), ('T', ''))
        self.assertEqual((decision['remaining_floor'], decision['total']), ('1', '2'))

    def test_unrelated_consumption_can_break_the_floor(self):
        goal = self._goal('g', [('one', 1), ('two', 1)], capacity=3)
        decision = evaluate(PROFILE, [goal], {}, capacity=3, spent=2, reserved=0,
                            candidate=self._candidate(goal))
        self.assertEqual((decision['decision'], decision['reason']),
                         ('F', 'GOAL_CAPACITY_FLOOR'))
        self.assertEqual((decision['total'], decision['headroom']), ('4', '-1'))

    def test_pending_and_blocked_are_not_treated_as_done(self):
        goal = self._goal('g', [('one', 1), ('two', 1)], capacity=3)
        for state, reason in (('PENDING', 'GOAL_PENDING_UNKNOWN'),
                              ('BLOCKED', 'GOAL_BLOCKED')):
            decision = evaluate(PROFILE, [goal], {('g', 'one'): state}, capacity=3,
                                spent=0, reserved=0, candidate=self._candidate(goal))
            self.assertEqual((decision['decision'], decision['reason']), ('F', reason))

    def test_done_obligation_cannot_be_committed_twice(self):
        goal = self._goal('g', [('one', 1), ('two', 1)], capacity=3)
        decision = evaluate(PROFILE, [goal], {('g', 'one'): 'DONE'}, capacity=3,
                            spent=0, reserved=0, candidate=self._candidate(goal))
        self.assertEqual((decision['decision'], decision['reason']),
                         ('F', 'GOAL_ALREADY_COMMITTED'))

    def test_certified_cost_must_equal_w_plan_cost(self):
        goal = self._goal('g', [('one', 2)], capacity=3)
        with self.assertRaises(ProtocolError) as error:
            evaluate(PROFILE, [goal], {}, capacity=3, spent=0, reserved=0,
                     candidate=self._candidate(goal, cost=1))
        self.assertEqual(error.exception.code, 'GOAL_COST_MISMATCH')

    def test_two_goals_on_one_resource_are_summed(self):
        first = self._goal('g1', [('one', 2)], capacity=3)
        second = self._goal('g2', [('two', 2)], capacity=3)
        decision = evaluate(PROFILE, [first, second], {}, capacity=3, spent=0, reserved=0,
                            candidate=self._candidate(first, selector='x' * 43))
        self.assertEqual((decision['decision'], decision['total']), ('F', '5'))

    def test_claim_rejects_duplicate_selector_and_unreachable_floor(self):
        bad = self._goal('g', [('one', 1), ('two', 1)], capacity=1)
        with self.assertRaises(ProtocolError) as error:
            validate_claim(PROFILE, bad['claim'])
        self.assertEqual(error.exception.code, 'GOAL_UNREACHABLE_AT_PUBLISH')
        duplicate = self._goal('g', [('one', 1), ('two', 1)], capacity=3)
        duplicate['claim']['actions'][1]['action_digest'] = duplicate['claim']['actions'][0]['action_digest']
        with self.assertRaises(ProtocolError) as error:
            validate_claim(PROFILE, duplicate['claim'])
        self.assertEqual(error.exception.code, 'GOAL_SELECTOR_DUPLICATE')
