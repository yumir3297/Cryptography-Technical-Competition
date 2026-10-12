"""Read-only W planning against fresh authenticated three-profile state."""
import copy
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.profiles.authorization_seed import initialize
from competition.support.wire import ProtocolError, b64, digest, sortset


class TransactionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.seed = initialize(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.seed.close()
        cls.folder.cleanup()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        try:
            self.module = importlib.import_module('competition.profiles.w_plans')
        except ModuleNotFoundError:
            self.fail('Missing read-only TransactionPlans implementation')
        self.plans = self.module.TransactionPlans(self.seed.store)

    def plan(self, profile, op=None):
        op = op or self.seed.clone(profile)
        with self.seed.store.db() as c:
            now = int(op['basis']['value']['iat'])
            return self.plans.plan(c, profile, op, {'lo': now, 'hi': now}, 1)

    def publish_temporarily(self, profile, namespace, key, value):
        with self.seed.store.db() as c:
            original = self.seed.store.current(c, profile, namespace, key)['record']
        updated = copy.deepcopy(original)
        updated['value'] = value
        self.seed.publish(profile, namespace, key, updated)
        self.addCleanup(self.seed.publish, profile, namespace, key, original)

    def test_original_witnesses_and_resources_are_schema_valid_without_writes(self):
        expected = {
            'PAY-1': (['ord', 'pay'], ['payer', 'CNY'], 'CNY_MINOR', 2000, 10000),
            'IND-DEMO-1': (['demo-line-a', 'unit-a', '1', 'INITIAL'],
                           ['route-capacity', 'demo-line-a', 'ind-inspection-bay', 'unit'], 'UNIT', 1, 8),
            'MED-DEMO-1': (None, ['order-capacity', 'med-demo-ledger', 'order'], 'ORDER', 1, 8),
        }
        for profile, (intent, resource, unit, amount, limit) in expected.items():
            with self.subTest(profile=profile), self.seed.store.db() as c:
                op = self.seed.clone(profile)
                if intent is None:
                    intent = ['patient-a', 'encounter-a', op['action']['payload']['order_group_id'], 'SUBMIT']
                before = list(c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key'))
                changes = c.total_changes
                now = int(op['basis']['value']['iat'])
                plan = self.plans.plan(c, profile, op, {'lo': now, 'hi': now}, 1)
                self.assertEqual(set(plan), {'intent', 'resource_key', 'unit', 'amount', 'limit',
                                            'behavior_before', 'behavior_after', 'taskflight', 'scene_before', 'scene_after'})
                self.assertEqual(plan['intent'], prefix(profile) + intent)
                self.assertEqual(plan['resource_key'], prefix(profile) + resource)
                self.assertEqual((plan['unit'], plan['amount'], plan['limit']), (unit, amount, limit))
                self.assertIs(type(plan['amount']), int)
                self.assertEqual(plan['taskflight'], {'key': prefix(profile) + [op['task_id']],
                                                    'operation_id': op['action']['operation_id']})
                schema = self.seed.store.schemas[profile]
                key = prefix(profile) + [op['action']['principal']]
                original = self.seed.store.current(c, profile, 'BEHAVIOR', key)
                bw = plan['behavior_before']; aw = plan['behavior_after']
                self.assertEqual(bw, {'key': key, 'revision': str(original['revision']),
                                      'ref': original['ref'], 'row': original['record']['value']})
                self.assertEqual(aw['revision'], str(original['revision'] + 1))
                self.assertEqual(aw['row'], {'accepted_count': '1', 'count_cap': original['record']['value']['count_cap'],
                                             'inflight': [op['action']['operation_id']]})
                self.assertEqual(aw['ref'], digest(['ZJJ-STATE-v1', 'BEHAVIOR', key, aw['revision'], aw['row']]))
                schema.validate(bw, 'BehaviorWitness'); schema.validate(aw, 'BehaviorWitness')
                if profile == 'PAY-1':
                    self.assertIsNone(plan['scene_before']); self.assertIsNone(plan['scene_after'])
                else:
                    ns = 'UNIT' if profile == 'IND-DEMO-1' else 'ENCOUNTER'
                    current = self.seed.store.current(c, profile, ns, op['scene_key'])
                    self.assertEqual(plan['scene_before'], {'namespace': ns, 'key': op['scene_key'],
                        'revision': str(current['revision']), 'ref': current['ref'], 'row': current['record']['value']})
                    after = plan['scene_after']; row = copy.deepcopy(current['record']['value'])
                    row.update(state='ACCEPTED', operation_id=op['action']['operation_id'])
                    self.assertEqual(after['row'], row)
                    self.assertEqual(after['revision'], str(current['revision'] + 1))
                    self.assertEqual(after['ref'], digest(['ZJJ-STATE-v1', ns, op['scene_key'], after['revision'], row]))
                    schema.validate(plan['scene_before'], 'SceneWitness'); schema.validate(after, 'SceneWitness')
                witness = {'reservation_id': b64(bytes(16)), 'key': plan['resource_key'], 'unit': unit,
                           'amount': str(amount), 'capacity_before': str(limit), 'reserved_before': '0',
                           'spent_before': '0', 'reserved_after': str(amount), 'spent_after': '0',
                           'revision_before': '1', 'revision_after': '2'}
                schema.validate(witness, 'ResourceWitness')
                self.assertEqual(c.total_changes, changes)
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key')],
                                 [tuple(r) for r in before])

    def test_intent_omits_operation_route_and_template(self):
        for profile in PROFILE_SCOPES:
            first = self.plan(profile)
            op = self.seed.clone(profile); op['action']['operation_id'] = b64(bytes([1]) * 16)
            if profile == 'IND-DEMO-1':
                op['action']['payload']['route'] = 'QUARANTINE'; op['action']['destination'] = 'ind-quarantine-bin'
            elif profile == 'MED-DEMO-1':
                op['action']['payload']['template_id'] = 'DEMO-ORDER-B'
            self.assertEqual(self.plan(profile, op)['intent'], first['intent'])

    def test_full_scope_and_task_and_scene_bindings_are_required(self):
        for profile in PROFILE_SCOPES:
            op = self.seed.clone(profile); op['action']['scope']['tenant'] = 'other-tenant'
            with self.assertRaises(ProtocolError): self.plan(profile, op)
            op = self.seed.clone(profile); op['task_id'] = b64(bytes(16))
            with self.assertRaises(ProtocolError): self.plan(profile, op)
            op = self.seed.clone(profile)
            if profile == 'PAY-1': op['scene_key'] = 'another-order'
            else: op['scene_key'][1] = 'other-tenant'
            with self.assertRaises(ProtocolError): self.plan(profile, op)

    def test_rejects_noninteger_pay_amount_and_invalid_accept_sequence(self):
        for amount in (2000.0, '2000.0', True, '0', '-1'):
            op = self.seed.clone('PAY-1'); op['action']['payload']['amount_minor'] = amount
            with self.assertRaises(ProtocolError): self.plan('PAY-1', op)
        op = self.seed.clone('PAY-1')
        with self.seed.store.db() as c:
            for sequence in (True, 0, -1, 1.0):
                with self.assertRaises(ProtocolError): self.plans.plan(c, 'PAY-1', op, {'lo': 1, 'hi': 1}, sequence)

    def test_current_behavior_cap_and_sorted_inflight_are_preserved(self):
        profile = 'PAY-1'; op = self.seed.clone(profile); key = prefix(profile) + ['payer']
        other = b64(bytes([3]) * 16)
        self.publish_temporarily(profile, 'BEHAVIOR', key, {'accepted_count': '4', 'count_cap': '7', 'inflight': [other]})
        plan = self.plan(profile)
        self.assertEqual(plan['behavior_after']['row'], {'accepted_count': '5', 'count_cap': '7',
                         'inflight': sortset([other, op['action']['operation_id']])})
        self.publish_temporarily(profile, 'BEHAVIOR', key, {'accepted_count': '7', 'count_cap': '7', 'inflight': []})
        with self.assertRaises(ProtocolError): self.plan(profile)

    def test_scene_requires_ready_and_capacity_uses_current_policy(self):
        for profile, field in [('IND-DEMO-1', 'capacity_per_destination'), ('MED-DEMO-1', 'destination_capacity')]:
            with self.seed.store.db() as c:
                policy_record = self.seed.store.current(c, profile, 'POLICY', prefix(profile))['record']
                policy = policy_record['value']
            changed = copy.deepcopy(policy); changed[field] = '3'
            # The original controlled policy has a fixed finite capacity of 8.
            changed_record = copy.deepcopy(policy_record); changed_record['value'] = changed
            with self.assertRaises(ProtocolError) as rejected:
                self.seed.store.schemas[profile].validate(changed_record, 'Record_POLICY')
            self.assertEqual(rejected.exception.code, 'UPSTREAM_SCHEMA_REJECT:Record_POLICY:value.' + field)
            self.assertEqual(self.plan(profile)['limit'], int(policy[field]))
            op = self.seed.clone(profile); ns = 'UNIT' if profile == 'IND-DEMO-1' else 'ENCOUNTER'
            with self.seed.store.db() as c: row = self.seed.store.current(c, profile, ns, op['scene_key'])['record']['value']
            row['state'] = 'STOPPED'; self.publish_temporarily(profile, ns, op['scene_key'], row)
            with self.assertRaises(ProtocolError): self.plan(profile)

    def test_different_scene_phase_or_group_has_different_intent(self):
        for profile in ('IND-DEMO-1', 'MED-DEMO-1'):
            op = self.seed.clone(profile); original = self.plan(profile)['intent']
            ns = 'UNIT' if profile == 'IND-DEMO-1' else 'ENCOUNTER'
            with self.seed.store.db() as c:
                row = self.seed.store.current(c, profile, ns, op['scene_key'])['record']['value']
                task = self.seed.store.current(c, profile, 'TASK', prefix(profile) + [op['task_id']])['record']['value']
            if profile == 'IND-DEMO-1':
                op['action']['payload']['phase'] = row['phase'] = 'REINSPECT'
                task['allowed_units'][0]['phase'] = 'REINSPECT'
            else:
                group = b64(bytes([4]) * 16)
                op['action']['payload']['order_group_id'] = row['order_group_id'] = task['order_group_id'] = group
            self.publish_temporarily(profile, ns, op['scene_key'], row)
            self.publish_temporarily(profile, 'TASK', prefix(profile) + [op['task_id']], task)
            self.assertNotEqual(self.plan(profile, op)['intent'], original)

    def test_planning_preserves_original_time_and_review_and_pay_history_routing(self):
        for profile in PROFILE_SCOPES:
            op = self.seed.clone(profile); before = json.dumps(op, sort_keys=True)
            with self.seed.store.db() as c:
                now = int(op['basis']['value']['iat'])
                self.plans.plan(c, profile, op, {'lo': now + 1, 'hi': now + 1}, 2)
            self.assertEqual(json.dumps(op, sort_keys=True), before)
        self.assertEqual(self.seed.operations['MED-DEMO-1']['required'], ['CLINICAL_REVIEW'])
        self.assertEqual(self.seed.operations['PAY-1']['required'], ['ANOMALY'])
        with self.seed.store.db() as c:
            history = self.seed.store.current(c, 'PAY-1', 'EXPERIENCE', prefix('PAY-1') + ['main'])['record']['value']
        self.assertEqual([case['action_class'] for case in history['cases']], ['HOLD', 'HOLD', 'HOLD'])

    def test_terminal_medical_and_confirmed_failure_use_legal_original_rows(self):
        self.assertIsNone(self.plans.terminal('PAY-1', None, 'SUCCEEDED', action=self.seed.clone('PAY-1')['action']))
        for profile in ('IND-DEMO-1', 'MED-DEMO-1'):
            op = self.seed.clone(profile); plan = self.plan(profile)
            ns = 'UNIT' if profile == 'IND-DEMO-1' else 'ENCOUNTER'
            with self.seed.store.db() as c: original = self.seed.store.current(c, profile, ns, op['scene_key'])['record']
            original['value'] = plan['scene_after']['row']; saved = copy.deepcopy(original)
            result = self.plans.terminal(profile, original, 'FAILED_CONFIRMED', action=op['action'])
            self.assertEqual(original, saved)
            expected = copy.deepcopy(saved); expected['value']['state'] = 'STOPPED'
            self.assertEqual(result, expected)
            self.seed.store.schemas[profile].validate(result['value'], 'SceneRow')
            if profile == 'MED-DEMO-1':
                result = self.plans.terminal(profile, original, 'SUCCEEDED', action=op['action'])
                self.assertEqual(result['value']['state'], 'REGISTERED')
            else:
                for route, state in [('RELEASE', 'RELEASED'), ('QUARANTINE', 'QUARANTINED'), ('INSPECT', 'AWAITING_REINSPECT')]:
                    action = copy.deepcopy(op['action']); action['payload']['route'] = route
                    action['destination'] = {'RELEASE': 'ind-release-bin', 'QUARANTINE': 'ind-quarantine-bin',
                                             'INSPECT': 'ind-inspection-bay'}[route]
                    result = self.plans.terminal(profile, original, 'SUCCEEDED', action=action)
                    self.assertEqual(result['value']['state'], state)
                    self.seed.store.schemas[profile].validate(result['value'], 'SceneRow')
                    self.assertEqual({k:v for k,v in result['value'].items() if k != 'state'},
                                     {k:v for k,v in saved['value'].items() if k != 'state'})
            with self.assertRaises(ProtocolError): self.plans.terminal(profile, original, 'TIMEOUT', action=op['action'])


if __name__ == '__main__':
    unittest.main()
