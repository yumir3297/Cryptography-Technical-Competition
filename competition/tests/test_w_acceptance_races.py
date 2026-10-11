"""CLI-exportable actual acceptance/last-resource/claim-cancel race cases."""
import importlib
import tempfile
import unittest
from pathlib import Path


class AcceptanceRaceTests(unittest.TestCase):
    profile = 'IND-DEMO-1'

    def setUp(self):
        try:
            self.cases = importlib.import_module('competition.w_cases_races')
        except ModuleNotFoundError:
            self.fail('Missing reusable actual race case exports')
        from competition.profiles.w_seed import initialize
        root = Path(__file__).resolve().parents[3] / 'tmp'; root.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=root); self.addCleanup(self.folder.cleanup)
        self.run = initialize(Path(self.folder.name), resource_capacity={self.profile: 1})
        self.addCleanup(self.run.close)

    def test_eight_distinct_valid_permits_for_same_intent_have_one_accept(self):
        result = self.cases.same_intent8(self.run)
        self.assertTrue(result['passed'], result)
        actual = result['actual']
        self.assertEqual((actual['distinct_operations'], actual['distinct_permits'], actual['prepared']), (8, 8, 8))
        self.assertEqual((actual['winners'], actual['rejections']), (1, 7))
        self.assertEqual(actual.get('unexpected_rejections'), 0,
                         'Late expiry or unrelated authority rejection must fail the race case')
        self.assertEqual((actual['reservations'], actual['reserved'], actual['spent']), (1, 1, 0))
        counts = result['counts']
        self.assertEqual((counts['accepts'], counts['outbox'], counts['attempts'], counts['exec_invocations']), (1, 1, 0, 0))

    def test_independent_intents_and_behavior_rows_compete_for_last_resource(self):
        result = self.cases.last_resource(self.run)
        self.assertTrue(result['passed'], result)
        actual = result['actual']
        self.assertTrue(actual['independent_business_rows'])
        self.assertEqual((actual['winners'], actual['resource_rejections']), (1, 1))
        self.assertEqual(actual['rejection_codes'], ['RESOURCE_EXHAUSTED'])
        self.assertEqual((actual['capacity'], actual['reserved'], actual['spent']), (1, 1, 0))
        self.assertEqual(result['counts']['accepts'], 1)

    def test_revoked_claim_races_cancellation_and_only_cancel_releases(self):
        result = self.cases.claim_cancel_revoked(self.run)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['actual']['successful_states'], ['CANCELED'])
        self.assertEqual((result['counts']['attempts'], result['counts']['cancellations']), (0, 1))
        self.assertEqual((result['actual']['reserved'], result['actual']['spent'], result['actual']['active_flights']), (0, 0, 0))

    def test_eight_claims_share_one_attempt_and_later_revoke_cannot_cancel(self):
        result = self.cases.claimed_cancel8(self.run)
        self.assertTrue(result['passed'], result)
        self.assertEqual((result['actual']['claim_successes'], result['actual']['distinct_attempts']), (8, 1))
        self.assertEqual(result['actual']['cancel_code'], 'CANCEL_STARTED')
        self.assertEqual((result['counts']['attempts'], result['counts']['exec_invocations']), (1, 0))
        self.assertEqual((result['actual']['reserved'], result['actual']['spent']), (1, 0))


if __name__ == '__main__': unittest.main()
