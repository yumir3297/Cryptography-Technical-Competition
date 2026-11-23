"""Offline verifier negative tests: valid signature, invalid relation.

The package is real: C's GoalFloor, the full authorization chain, X's acceptance,
the W-signed attempt and the tool final fact.  Each test changes one relation
while leaving the bytes structurally parseable.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from competition.evaluation.fixtures import (accept, execute_and_settle, goal_package,
                                             ind_goal, ind_three_actions)
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize

IND = 'IND-DEMO-1'
ROOT = Path(__file__).resolve().parents[2]


class EvidenceVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(dir=ROOT / '.runtime')
        cls.wrun = initialize(Path(cls.folder.name), resource_capacity={IND: 2},
                             goal_mode='enforce')
        cls.ops = ind_three_actions(cls.wrun)
        ind_goal(cls.wrun, cls.ops)
        cls.oid = goal_package(cls.wrun, cls.ops)
        cls.package = build_package(cls.wrun, IND, cls.oid)
        cls.anchor = build_anchor(cls.wrun)

    @classmethod
    def tearDownClass(cls):
        cls.wrun.close()
        cls.folder.cleanup()

    def _mutated(self, mutate):
        package = copy.deepcopy(self.package)
        mutate(package)
        return verify_package(package, self.anchor)

    def assertRejected(self, mutate, label):
        result = self._mutated(mutate)
        self.assertEqual(result['status'], 'FAIL', label + ': ' + json.dumps(result, ensure_ascii=False)[:500])

    def test_clean_package_passes_independent_audit(self):
        result = verify_package(copy.deepcopy(self.package), self.anchor)
        self.assertEqual(result['status'], 'PASS', json.dumps(result, ensure_ascii=False)[:1200])
        self.assertGreaterEqual(result['passed'], 10)

    def test_action_payload_substitution(self):
        def mutate(p):
            p['commit']['value']['action']['payload']['route'] = 'QUARANTINE'
        self.assertRejected(mutate, 'action payload')

    def test_action_hash_substitution(self):
        def mutate(p):
            p['frozen']['op']['ctx']['action_hash'] = 'A' * 43
        self.assertRejected(mutate, 'action hash')

    def test_goal_capacity_tamper(self):
        def mutate(p):
            for control in p['controls']:
                if control['namespace'] == 'GOAL':
                    control['record']['value']['capacity'] = '3'
        self.assertRejected(mutate, 'goal capacity')

    def test_task_ref_substitution(self):
        def mutate(p):
            p['frozen']['op']['basis']['value']['task_ref'] = 'B' * 43
        self.assertRejected(mutate, 'task ref')

    def test_resource_capacity_tamper(self):
        def mutate(p):
            p['resource']['capacity'] = 99
        self.assertRejected(mutate, 'resource capacity')

    def test_scope_substitution(self):
        def mutate(p):
            p['commit']['scope']['scenario'] = 'medical'
        self.assertRejected(mutate, 'scope')

    def test_permit_ref_substitution(self):
        def mutate(p):
            p['commit']['value']['permit_ref'] = 'C' * 43
        self.assertRejected(mutate, 'permit ref')

    def test_acceptance_commit_ref_substitution(self):
        def mutate(p):
            p['acceptance']['body']['payload']['commit_record_ref'] = 'D' * 43
        self.assertRejected(mutate, 'acceptance commit ref')

    def test_acceptance_signature_tamper(self):
        def mutate(p):
            sig = p['acceptance']['sig']
            p['acceptance']['sig'] = ('A' if sig[0] != 'A' else 'B') + sig[1:]
        self.assertRejected(mutate, 'acceptance signature')

    def test_control_signature_tamper(self):
        def mutate(p):
            control = next(c for c in p['controls'] if c['namespace'] == 'GOAL')
            sig = control['certificate']['signature']
            control['certificate']['signature'] = ('A' if sig[0] != 'A' else 'B') + sig[1:]
        self.assertRejected(mutate, 'control signature')

    def test_attempt_id_substitution(self):
        def mutate(p):
            p['outbox']['attempt_id'] = 'E' * 22
        self.assertRejected(mutate, 'attempt id')

    def test_final_fact_signature_tamper(self):
        def mutate(p):
            p['settlement_evidence']['record']['value']['outcome'] = 'FAILED_CONFIRMED'
            p['settlement_evidence']['record']['value']['effect_id'] = ''
            p['settlement_evidence']['record']['value']['no_late_effect'] = True
        self.assertRejected(mutate, 'final fact signature/outcome')

    def test_final_fact_id_substitution(self):
        def mutate(p):
            p['settlement']['fact_id'] = 'F' * 43
        self.assertRejected(mutate, 'final fact id')

    def test_package_private_key_absence(self):
        text = json.dumps(self.package)
        for marker in ('PRIVATE KEY', 'private_key', 'signing_key'):
            self.assertNotIn(marker, text)


if __name__ == '__main__':
    unittest.main()
