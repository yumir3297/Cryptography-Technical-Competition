"""Three distinct business profiles produce independently verifiable packages."""
import tempfile
import unittest
from pathlib import Path

from competition.evaluation.fixtures import accept, execute_and_settle
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize

ROOT = Path(__file__).resolve().parents[2]


class CrossScenarioEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(dir=ROOT / '.runtime')
        cls.wrun = initialize(Path(cls.folder.name), goal_mode='off')
        cls.anchor = build_anchor(cls.wrun)
        cls.packages = {}
        for profile, op in cls.wrun.operations.items():
            accept(cls.wrun, profile, op)
            execute_and_settle(cls.wrun, profile, op)
            cls.packages[profile] = build_package(cls.wrun, profile, op['action']['operation_id'])

    @classmethod
    def tearDownClass(cls):
        cls.wrun.close()
        cls.folder.cleanup()

    def test_each_profile_passes_offline_audit(self):
        for profile, package in self.packages.items():
            result = verify_package(package, self.anchor)
            self.assertEqual(result['status'], 'PASS', profile + ': ' + str(result['checks']))

    def test_reviews_are_distinct_business_requirements(self):
        purposes = {}
        for profile, package in self.packages.items():
            purposes[profile] = [r['body']['payload']['purpose']
                                 for r in package['frozen']['op']['reviews']]
        self.assertEqual(purposes['PAY-1'], ['ANOMALY'])
        self.assertEqual(purposes['MED-DEMO-1'], ['CLINICAL_REVIEW'])
        self.assertEqual(purposes['IND-DEMO-1'], ['QUALITY_REVIEW'])

    def test_each_package_binds_a_different_tool_ledger_and_effect(self):
        ledgers = {p: pkg['tool_certificate']['claim']['record']['value']['ledger_id']
                   for p, pkg in self.packages.items()}
        self.assertEqual(len(set(ledgers.values())), 3, ledgers)
        effects = {p: pkg['settlement']['effect_id'] for p, pkg in self.packages.items()}
        self.assertTrue(all(effects.values()), effects)
