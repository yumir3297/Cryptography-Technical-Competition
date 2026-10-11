"""Actual W/tool/X process crash recovery and competing W transactions."""
import importlib
import tempfile
import unittest
from pathlib import Path
from competition.profiles.w_seed import initialize


class WRecoveryTests(unittest.TestCase):
    def setUp(self):
        try:self.cases=importlib.import_module('competition.w_cases')
        except ModuleNotFoundError:self.fail('Missing reusable real W recovery cases')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.run=initialize(Path(self.tmp.name));self.addCleanup(self.run.close)

    def test_three_profiles_lost_ack_query_same_fact_without_new_exec(self):
        for profile in self.run.operations:
            with self.subTest(profile=profile):
                result=self.cases.lost_ack(self.run,profile)
                self.assertEqual(result['lost_ack']['trace']['exit_code'],98)
                self.assertNotEqual(result['lost_ack']['trace']['pid'],result['query']['trace']['pid'])
                self.assertEqual(result['attempt_id'],result['query']['record']['value']['dispatch_attempt'])
                self.assertEqual(result['persisted_fact_id'],result['query_fact_id'])
                self.assertEqual(result['before_retry']['execution_sends_observed'],result['after_retry']['execution_sends_observed'])
                self.assertEqual(result['settlement']['final_fact_id'],result['repeated_settlement']['final_fact_id'])
                self.assertEqual(result['after_settlement']['settlements'],result['before_settlement']['settlements']+1)
                self.assertEqual(result['effect_count'],1)

    def test_unknown_query_preserves_resource_flight_and_creates_no_effect(self):
        for profile in self.run.operations:
            with self.subTest(profile=profile):
                result=self.cases.unknown_query(self.run,profile)
                self.assertIsNone(result['query']['record'])
                self.assertEqual(result['before']['reservations'],result['after']['reservations'])
                self.assertEqual(result['before']['resources'],result['after']['resources'])
                self.assertEqual(result['before']['flights'],result['after']['flights'])
                self.assertEqual(result['after']['effect_count'],0)
                self.assertEqual(result['after']['counts']['settlements'],0)

    def test_eight_claims_and_eight_settlements_create_one_attempt_effect_settlement(self):
        result=self.cases.concurrent_claim_and_settle(self.run,'PAY-1',workers=8)
        self.assertEqual(len(set(result['attempt_ids'])),1)
        self.assertEqual(len(set(result['final_fact_ids'])),1)
        self.assertEqual((result['after']['counts']['attempts'],result['after']['counts']['exec_invocations'],
            result['after']['counts']['settlements'],result['after']['effect_count']),(1,1,1,1))
        self.assertEqual(sum(r['reserved'] for r in result['after']['resources']),0)
        self.assertEqual(sum(r['spent'] for r in result['after']['resources']),int(self.run.operations['PAY-1']['action']['payload']['amount_minor']))

    def test_bad_final_does_not_halt_but_authenticated_contradiction_does(self):
        result=self.cases.bad_and_conflicting_final(self.run,'PAY-1')
        self.assertEqual(len(result['rejected']),3)
        self.assertNotIn('UNEXPECTEDLY_ACCEPTED',result['rejected'])
        self.assertEqual(result['after_bad']['counts']['halts'],0)
        self.assertEqual(result['before_bad']['resources'],result['after_bad']['resources'])
        self.assertEqual(result['conflict_result']['state'],'HALTED')
        self.assertGreater(sum(r['reserved'] for r in result['before_conflict']['resources']),0)
        self.assertEqual(result['before_conflict']['counts']['settlements'],0)
        self.assertTrue(all(r['active']==1 for r in result['after_conflict']['flights']))
        self.assertEqual(result['before_conflict']['resources'],result['after_conflict']['resources'])
        self.assertEqual(result['before_conflict']['reservations'],result['after_conflict']['reservations'])

    def test_actual_w_exit_after_commit_recovers_exact_frozen_acceptance(self):
        result=self.cases.w_commit_crash(self.run,'PAY-1')
        self.assertEqual(result['crash']['exit_code'],97)
        self.assertIsNone(result['before_receipt']['operation']['receipt'])
        self.assertEqual(result['before_receipt']['counts']['accepts'],1)
        self.assertEqual(result['after_receipt']['counts']['accepts'],1)
        self.assertEqual(result['before_receipt']['commit_ref'],result['after_receipt']['commit_ref'])
        self.assertEqual(result['frozen_core'],result['returned_core'])
        self.assertEqual(result['before_receipt']['resources'],result['after_receipt']['resources'])
        self.assertEqual(result['after_receipt']['counts']['attempts'],0)
        self.assertIsNotNone(result['after_receipt']['operation']['receipt'])


if __name__=='__main__':unittest.main()
