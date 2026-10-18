"""PAY adapter business derivation against fresh keys and current authenticated rows."""
import copy
import importlib
import time
import unittest
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from competition.support.wire import WINDOW, b64, canonical, digest, keyid, rec_ref, ProtocolError
from competition.support.pay_dependencies import _parse_keygrant, _parse_rolegrant


SCOPE = {'domain': 'lab', 'tenant': 'tenant-1', 'scenario': 'payment'}
ROLES = {'E': 'SOURCE', 'H': 'HOLDER', 'G': 'ISSUER', 'X': 'EXECUTOR', 'U': 'FINANCE', 'V': 'ANOMALY'}
PURPOSES = {'E': ['SOURCE'], 'H': ['IssueRequest'], 'G': ['Permit'], 'X': ['Acceptance'], 'U': ['Authorization'], 'V': ['Review']}


def actors():
    out = {}
    for alias, role in ROLES.items():
        key = Ed25519PrivateKey.generate()
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        out[alias] = SimpleNamespace(name='pay-' + alias.lower(), key=key, pub=pub,
                                    kid=keyid(pub), roles=frozenset([role]), purposes=frozenset(PURPOSES[alias]))
    return out


class CurrentRows:
    """In-memory authenticated boundary for pure adapter tests; core integration is separate."""
    def __init__(self, identities, seed, now):
        self.actors = identities
        self.rows = {}
        for row in seed['rows']:
            self.add(row['namespace'], row['key'], row['record'])
        for alias, actor in identities.items():
            self.add('KEY', [actor.kid], self.record('KEY_GRANT', {
                'subject': actor.name, 'public_key': b64(actor.pub), 'kid': actor.kid,
                'epoch': '1', 'purposes': PURPOSES[alias], 'iat': str(now - 60),
                'exp': str(now + 600), 'root_generation': '1', 'enrollment_ref': digest(['fresh-test', actor.kid])}))
            self.add('ROLE', list(SCOPE.values()) + [actor.name, ROLES[alias]], self.record('ROLE_GRANT', {
                'subject': actor.name, 'role': ROLES[alias], 'epoch': '1', 'iat': str(now - 60),
                'exp': str(now + 600), 'tool_set': ['pay-sim'], 'destination_set': ['pay-sim-dest'],
                'scope_set': [SCOPE], 'constraints': {'payer_set': ['payer'], 'max_amount_minor': '10000'}}))

    @staticmethod
    def record(kind, value):
        return {'version': '2.6', 'profile': 'PAY-1', 'kind': kind, 'scope': copy.deepcopy(SCOPE), 'value': value}

    def add(self, namespace, key, record):
        ref = digest(['ZJJ-STATE-v1', namespace, key, '1', record['value']]) if namespace == 'BEHAVIOR' else rec_ref(record)
        self.rows[namespace, tuple(key)] = {'revision': 1, 'ref': ref, 'record': copy.deepcopy(record)}

    def current(self, c, profile, namespace, key):
        if (namespace, tuple(key)) not in self.rows:
            raise ProtocolError('STATE_UNAVAILABLE')
        return copy.deepcopy(self.rows[namespace, tuple(key)])

    def credential(self, c, profile, alias, role, purpose, action, event):
        actor = self.actors[alias]
        key = self.current(c, profile, 'KEY', [actor.kid])
        grant = self.current(c, profile, 'ROLE', list(SCOPE.values()) + [actor.name, role])
        for at in (event.lo, event.hi):
            _parse_keygrant(key['record'], SCOPE, actor.kid, actor.name, purpose, at)
            _parse_rolegrant(grant['record'], SCOPE, actor.name, role, action, at)
        return key, grant


class PayAuthorizationAdapterTests(unittest.TestCase):
    def setUp(self):
        try:
            self.build = importlib.import_module('competition.profiles.pay_seed').build_pay
            self.adapter_type = importlib.import_module('competition.profiles.authorization_pay').PayAuthorizationAdapter
        except ModuleNotFoundError:
            self.fail('Missing PAY business seed/authorization adapter APIs')
        self.now = int(time.time())
        self.actors = actors()

    def run_mode(self, mode='FLAG'):
        seed = self.build(self.actors, SCOPE, self.now, mode)
        store = CurrentRows(self.actors, seed, self.now)
        op = {**seed, 'assessment': {'value': {'cutoff': str(self.now)}}, 'exp': str(self.now + 120)}
        event = SimpleNamespace(lo=self.now + 1, hi=self.now + 2)
        return seed, store, op, event, self.adapter_type(store, 'PAY-1', self.actors)

    def test_fresh_signed_sources_derive_three_original_risk_routes(self):
        for mode, required, support in [('FLAG', ['ANOMALY'], '3'), ('CLEAR', [], '3'), ('INSUFFICIENT', ['LOW_EVIDENCE'], '2')]:
            with self.subTest(mode=mode):
                seed, store, op, event, adapter = self.run_mode(mode)
                result = adapter.derive(None, op, event)
                self.assertEqual(result['required_reviews'], required)
                self.assertEqual(result['assessment_value']['result'], mode)
                self.assertEqual(result['assessment_value']['support'], support)
                self.assertEqual(result['assessment_value']['cutoff'], str(self.now))
                self.assertEqual(len(result['basis_deps']), 9)
                self.assertEqual(len(result['deps']), 17 if required else 15)
                self.assertEqual(len(seed['rows']), 5)

    def test_action_payee_cannot_override_signed_source(self):
        _, _, op, event, adapter = self.run_mode()
        op['action']['payload']['payee'] = 'attacker'
        with self.assertRaises(ProtocolError):
            adapter.derive(None, op, event)

    def test_event_interval_must_fit_source_window(self):
        _, _, op, event, adapter = self.run_mode()
        # A whole window past the event is past the source's own exp as well.  This
        # fixture used to pin two minutes; the window is the knob now, so it has to
        # reach past whatever that knob is set to.
        event.hi = self.now + WINDOW
        with self.assertRaises(ProtocolError):
            adapter.derive(None, op, event)

    def test_cutoff_cannot_be_after_trusted_event(self):
        _, _, op, event, adapter = self.run_mode()
        op['assessment']['value']['cutoff'] = str(event.lo + 1)
        with self.assertRaises(ProtocolError):
            adapter.derive(None, op, event)

    def test_source_dependency_must_match_exact_current_revision(self):
        _, store, op, event, adapter = self.run_mode()
        orderkey = list(SCOPE.values()) + ['ord', 'pay']
        record = store.current(None, 'PAY-1', 'ORDER', orderkey)['record']
        source = record['value']['source_envelope']
        source['body']['deps'] = [{'namespace': 'KEY', 'key': [self.actors['E'].kid], 'revision': '2', 'ref': store.rows['KEY', (self.actors['E'].kid,)]['ref']}]
        source['sig'] = b64(self.actors['E'].key.sign(canonical(['ZJJ-SIG-v1', source['protected'], source['body']])))
        record['value']['source_ref'] = digest(['ZJJ-OBJ-v1', source['protected'], source['body']])
        store.add('ORDER', orderkey, record)
        with self.assertRaises(ProtocolError):
            adapter.derive(None, op, event)

    def test_holder_and_finance_may_share_subject_without_extra_basis_role(self):
        self.actors['U'].name = self.actors['H'].name
        _, _, op, event, adapter = self.run_mode()
        result = adapter.derive(None, op, event)
        self.assertEqual(result['required_reviews'], ['ANOMALY'])
        self.assertEqual(len(result['basis_deps']), 9)

    def test_signed_source_must_allow_required_reviewer(self):
        _, store, op, event, adapter = self.run_mode()
        key = list(SCOPE.values()) + ['ord', 'pay']
        record = store.current(None, 'PAY-1', 'ORDER', key)['record']
        source = record['value']['source_envelope']
        source['body']['aud'].remove(self.actors['V'].name)
        source['sig'] = b64(self.actors['E'].key.sign(canonical(['ZJJ-SIG-v1', source['protected'], source['body']])))
        record['value']['source_ref'] = digest(['ZJJ-OBJ-v1', source['protected'], source['body']])
        store.add('ORDER', key, record)
        with self.assertRaises(ProtocolError):
            adapter.derive(None, op, event)

    def test_declared_current_source_dependency_is_accepted(self):
        _, store, op, event, adapter = self.run_mode()
        key = list(SCOPE.values()) + ['ord', 'pay']
        record = store.current(None, 'PAY-1', 'ORDER', key)['record']
        source = record['value']['source_envelope']
        source['body']['deps'] = [{'namespace': 'KEY', 'key': [self.actors['E'].kid], 'revision': '1',
                                  'ref': store.rows['KEY', (self.actors['E'].kid,)]['ref']}]
        source['sig'] = b64(self.actors['E'].key.sign(canonical(['ZJJ-SIG-v1', source['protected'], source['body']])))
        record['value']['source_ref'] = digest(['ZJJ-OBJ-v1', source['protected'], source['body']])
        store.add('ORDER', key, record)
        result = adapter.derive(None, op, event)
        self.assertEqual(result['required_reviews'], ['ANOMALY'])
        self.assertEqual(len(result['deps']), 17)


if __name__ == '__main__':
    unittest.main()
