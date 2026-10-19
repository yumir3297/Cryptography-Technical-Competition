"""Fresh PAY business publications; identity grants and C publication belong to core."""
import copy
import os

from competition.support.wire import WINDOW, b64, canonical, digest, rec_ref, require, sortset
from competition.support.pay_records import scope_check
from competition.support.schema import UpstreamSchema
from pathlib import Path


def build_pay(actors, scope, now, mode='FLAG'):
    scope_check(scope)
    require(scope == {'domain': 'lab', 'tenant': 'tenant-1', 'scenario': 'payment'}, 'WRONG_SCOPE')
    require(mode in ('CLEAR', 'FLAG', 'INSUFFICIENT'), 'PAY_MODE')
    require(type(now) is int and now >= 60, 'TIME')
    require(set(actors) >= {'H', 'G', 'X', 'U', 'V', 'E'}, 'ACTOR_SET')
    prefix = [scope[k] for k in ('domain', 'tenant', 'scenario')]
    task_id, operation_id = b64(os.urandom(16)), b64(os.urandom(16))

    def record(kind, value):
        return {'version': '2.6', 'profile': 'PAY-1', 'kind': kind,
                'scope': copy.deepcopy(scope), 'value': value}

    policy = record('POLICY', {
        'profile': 'PAY-1', 'schema_version': 'pay1-payload-v1', 'verifier_version': 'pay1-verifier-v1',
        'policy_revision': '1', 'gateway': actors['G'].name, 'gateway_kid': actors['G'].kid,
        'executor': actors['X'].name, 'executor_kid': actors['X'].kid, 'source': actors['E'].name,
        'readers': sortset(list({actors[a].name for a in ('H', 'G', 'X', 'U', 'V', 'E')})),
        'tool': 'pay-sim', 'tool_version': '1', 'destination': 'pay-sim-dest', 'currency': 'CNY',
        'method': 'order-match-v1', 'risk_method': 'history-int-v2', 'partition': 'main', 'count_cap': '32',
        'iat': str(now - 30), 'exp': str(now + WINDOW)})
    task = record('PAY_TASK', {
        'task_id': task_id, 'task_revision': '1', 'principal': 'payer', 'holder': actors['H'].name,
        'holder_kid': actors['H'].kid, 'order_id': 'ord', 'stage': 'pay', 'payer': 'payer',
        'allowed_payees': ['payee'], 'max_amount_minor': '10000', 'executor': actors['X'].name,
        'destination': 'pay-sim-dest', 'policy_ref': rec_ref(policy),
        'iat': str(now - 30), 'exp': str(now + WINDOW)})
    action = {'scope': copy.deepcopy(scope), 'operation_id': operation_id, 'principal': 'payer',
              'holder': actors['H'].name, 'holder_kid': actors['H'].kid, 'executor': actors['X'].name,
              'tool': 'pay-sim', 'tool_version': '1', 'destination': 'pay-sim-dest',
              'payload': {'order_id': 'ord', 'stage': 'pay', 'payer': 'payer', 'payee': 'payee',
                          'amount_minor': '2000', 'currency': 'CNY', 'purpose': 'order-settlement'}}
    count = 2 if mode == 'INSUFFICIENT' else 3
    cases = [{'case_id': 'case-%02d' % i, 'intent': 'intent-%02d' % i, 'revision': '1',
              'scope': copy.deepcopy(scope), 'partition': 'main', 'payer': 'payer', 'stage': 'pay',
              'currency': 'CNY', 'ratio': '2000', 'action_class': 'HOLD' if mode == 'FLAG' else 'PAY',
              'event_at': str(now - 50), 'known_at': str(now - 40), 'label': 'CONFIRMED_GOOD'}
             for i in range(1, count + 1)]
    history = record('PAY_HISTORY', {'partition': 'main', 'publication_revision': '1',
                                    'feature_schema': 'ratio-int-v1', 'cases': sortset(cases),
                                    'iat': str(now - 30), 'exp': str(now + WINDOW)})
    payload = {k: action['payload'][k] for k in ('order_id', 'stage', 'payer', 'payee', 'amount_minor', 'currency')}
    payload.update({'order_revision': '1', 'accepted_goods': True, 'unsettled': True,
                    'beneficiary_active': True, 'observed_at': str(now - 20)})
    header = {'proto': 'ZJJ-AAP', 'version': '2.5', 'profile': 'PAY-1', 'alg': 'Ed25519',
              'type': 'Evidence', 'issuer': actors['E'].name, 'kid': actors['E'].kid}
    body = {'id': b64(os.urandom(16)), 'scope': copy.deepcopy(scope), 'iat': str(now - 10),
            # The source's life is the window, measured from an observation ten
            # seconds ago, so the two ends keep the same distance apart however the
            # window is set -- and the width stays inside the window's own bound.
            'exp': str(now + WINDOW - 10), 'aud': policy['value']['readers'][:], 'refs': [], 'deps': [], 'payload': payload}
    source = {'protected': header, 'body': body,
              'sig': b64(actors['E'].key.sign(canonical(['ZJJ-SIG-v1', header, body])))}
    evidence = record('PAY_EVIDENCE', {'source_version': '2.5', 'source_profile': 'PAY-1',
                                      'source_type': 'Evidence', 'source_ref': digest(['ZJJ-OBJ-v1', header, body]),
                                      'source_envelope': source})
    behavior = record('BEHAVIOR_STATE', {'accepted_count': '0', 'count_cap': '32', 'inflight': []})
    rows = [{'namespace': ns, 'key': key, 'record': obj} for ns, key, obj in (
        ('POLICY', prefix, policy), ('TASK', prefix + [task_id], task),
        ('ORDER', prefix + ['ord', 'pay'], evidence), ('EXPERIENCE', prefix + ['main'], history),
        ('BEHAVIOR', prefix + ['payer'], behavior))]
    schema = UpstreamSchema(Path(__file__).resolve().parents[2], 'PAY-1')
    for row in rows:
        if row['namespace'] != 'BEHAVIOR':
            schema.validate(row['record'], 'Record_' + row['record']['kind'])
    return {'rows': rows, 'action': action, 'task_id': task_id, 'scene_key': 'ord'}
