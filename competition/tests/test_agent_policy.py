"""The agent boundary accepts one shape of candidate and refuses everything else."""
import unittest

from competition.agent import policy


class ProfileCatalogTests(unittest.TestCase):
    def test_catalog_covers_the_three_fixed_profiles(self):
        rows = policy.profiles()
        self.assertEqual([row['profile'] for row in rows],
                         ['IND-DEMO-1', 'MED-DEMO-1', 'PAY-1'])
        for row in rows:
            self.assertTrue(row['intent_fields'])
            for field in row['intent_fields']:
                self.assertEqual(field['type'], 'string')
                self.assertTrue(field['required'])

    def test_the_gateway_may_drive_only_status(self):
        self.assertEqual(policy.ALLOWED_STEPS, frozenset({'status'}))
        with self.assertRaises(policy.PolicyError) as caught:
            policy.require_step('prepare')
        self.assertEqual(caught.exception.code, 'AGENT_STEP')


class IntentTests(unittest.TestCase):
    pay = {'order_id': 'ord', 'stage': 'pay', 'payer': 'payer', 'payee': 'payee',
           'amount_minor': '2000'}
    ind = {'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'unit_id': 'unit-a',
           'batch_id': 'batch-a', 'inspection_cycle': '1', 'phase': 'INITIAL',
           'route': 'RELEASE'}
    med = {'synthetic_patient_id': 'DEMO_A', 'encounter_id': 'demo-encounter-a',
           'template_id': 'med-fixed-v1'}

    def test_each_profile_has_a_complete_valid_intent(self):
        for profile, intent in (('PAY-1', self.pay), ('IND-DEMO-1', self.ind),
                                ('MED-DEMO-1', self.med)):
            with self.subTest(profile=profile):
                self.assertEqual(policy.validate_intent(profile, intent), intent)

    def test_unknown_profile_and_unknown_field_are_refused(self):
        with self.assertRaises(policy.PolicyError) as caught:
            policy.validate_intent('PAY-2', self.pay)
        self.assertEqual(caught.exception.code, 'PROFILE')
        with self.assertRaises(policy.PolicyError) as caught:
            policy.validate_intent('PAY-1', dict(self.pay, role='H'))
        self.assertEqual(caught.exception.code, 'INTENT_FIELDS')

    def test_missing_field_is_refused(self):
        intent = dict(self.pay)
        del intent['amount_minor']
        with self.assertRaises(policy.PolicyError) as caught:
            policy.validate_intent('PAY-1', intent)
        self.assertEqual(caught.exception.code, 'INTENT_FIELDS')

    def test_values_must_be_trimmed_printable_ascii_strings(self):
        for value, code in ((2000, 'INTENT_FIELD_TYPE'), (' 2000', 'INTENT_FIELD_CHARS'),
                            ('2000\n', 'INTENT_FIELD_CHARS'), ('病人', 'INTENT_FIELD_CHARS'),
                            ('x' * 129, 'INTENT_FIELD_LENGTH')):
            with self.subTest(value=value):
                with self.assertRaises(policy.PolicyError) as caught:
                    policy.validate_intent('PAY-1', dict(self.pay, amount_minor=value))
                self.assertEqual(caught.exception.code, code)

    def test_amount_and_route_constraints(self):
        for value in ('0', '-1', '1.0', '01', 'x'):
            with self.subTest(value=value):
                with self.assertRaises(policy.PolicyError) as caught:
                    policy.validate_intent('PAY-1', dict(self.pay, amount_minor=value))
                self.assertEqual(caught.exception.code, 'INTENT_AMOUNT')
        with self.assertRaises(policy.PolicyError) as caught:
            policy.validate_intent('IND-DEMO-1', dict(self.ind, route='DROP'))
        self.assertEqual(caught.exception.code, 'INTENT_ROUTE')
        self.assertEqual(policy.ROUTES, ('INSPECT', 'QUARANTINE', 'RELEASE'))

    def test_digest_is_stable_and_key_order_independent(self):
        one = policy.validate_intent('PAY-1', self.pay)
        two = policy.validate_intent('PAY-1', dict(reversed(list(self.pay.items()))))
        self.assertEqual(policy.intent_digest('PAY-1', one),
                         policy.intent_digest('PAY-1', two))
        self.assertNotEqual(policy.intent_digest('PAY-1', one),
                            policy.intent_digest('MED-DEMO-1', one))


if __name__ == '__main__':
    unittest.main()
