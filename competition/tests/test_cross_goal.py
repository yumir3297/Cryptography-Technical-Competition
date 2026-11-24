"""GoalFloor enforce on the PAY and MED business profiles."""
import unittest

from competition.evaluation.experiments.cross_goal import one


class CrossProfileGoalFloorTests(unittest.TestCase):
    def test_pay_legacy_accepts_but_enforce_rejects_crowded_action(self):
        self.assertTrue(one('PAY-1', 'off', crowd=True)['accepted'])
        rejected = one('PAY-1', 'enforce', crowd=True)
        self.assertEqual((rejected['accepted'], rejected['code']),
                         (False, 'GOAL_CAPACITY_FLOOR'))
        normal = one('PAY-1', 'enforce', crowd=False)
        self.assertEqual((normal['accepted'], normal['audit_status']), (True, 'PASS'))

    def test_med_legacy_accepts_but_enforce_rejects_crowded_action(self):
        self.assertTrue(one('MED-DEMO-1', 'off', crowd=True)['accepted'])
        rejected = one('MED-DEMO-1', 'enforce', crowd=True)
        self.assertEqual((rejected['accepted'], rejected['code']),
                         (False, 'GOAL_CAPACITY_FLOOR'))
        normal = one('MED-DEMO-1', 'enforce', crowd=False)
        self.assertEqual((normal['accepted'], normal['audit_status']), (True, 'PASS'))


if __name__ == '__main__':
    unittest.main()
