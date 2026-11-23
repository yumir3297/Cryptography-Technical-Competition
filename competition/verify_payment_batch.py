"""Verify the signed PAY-1 artifacts from the three-order batch demonstration."""
import argparse
import json
from pathlib import Path

from competition.support.tool_final import final_fact_id, final_sign_bytes, verify_certificate as verify_tool
from competition.support.wire import action_hash, canonical, msgref, raw, rec_ref, require, strict_verify
from competition.tools.common_tool import request_hash
from competition.tools.pay_batch import verify_certificate, verify_detail_for


def verify(report, root_public):
    profile = 'PAY-1'
    require(report['fixture'] == profile and raw(report['root_public'], 32) == root_public, 'ROOT_MISMATCH')
    trust = verify_tool(report['tool_certificate'], root_public, profile)
    registered = trust['value']
    public = raw(registered['public_key'], 32)
    require(public == raw(report['tool_public'], 32), 'TOOL_KEY')
    certificate = report['batch_certificate']
    batch = verify_certificate(public, certificate)
    require(batch['profile'] == profile and batch['scope'] == trust['scope']
            and batch['ledger_id'] == registered['ledger_id']
            and batch['ledger_origin'] == report['tool_certificate']['claim']['ledger_origin']
            and batch['tool_trust_ref'] == rec_ref(trust), 'BATCH_TRUST')
    payments = report['payments']
    require(len(payments) == 3 and len(batch['members']) == len(report['details']) == 2, 'DEMO_SIZE')
    oids = [p['action']['operation_id'] for p in payments]
    require(len(set(oids)) == len({p['attempt_id'] for p in payments}) == 3, 'DEMO_ATTEMPTS')
    require(len({(p['action']['payload']['order_id'], p['action']['payload']['stage'])
                 for p in payments}) == 3, 'DEMO_ORDERS')
    for p in payments:
        action, dispatch = p['action'], p['dispatch_claim']
        require(dispatch['action'] == action and dispatch['action_hash'] == action_hash(profile, action)
                and dispatch['operation_id'] == action['operation_id']
                and dispatch['attempt_id'] == p['attempt_id']
                and dispatch['acceptance_ref'] == msgref(p['acceptance'])
                and dispatch['ledger_id'] == batch['ledger_id'] and dispatch['ledger_origin'] == batch['ledger_origin']
                and action['scope'] == trust['scope'] and dispatch['tool_trust_ref'] == rec_ref(trust)
                and action['payload']['currency'] == batch['currency']
                and action['payload']['payer'] == batch['payer'], 'DEMO_PAYMENT')

    details = {d['operation_id']: d for d in
               (verify_detail_for(public, certificate, signed) for signed in report['details'])}
    require(set(details) == set(oids[:2]), 'DEMO_DETAIL_MEMBERS')
    require({details[oid]['outcome'] for oid in oids[:2]} == {'SUCCEEDED', 'FAILED_CONFIRMED'}, 'DEMO_OUTCOMES')
    original_paid = 0
    for p in payments[:2]:
        d = details[p['action']['operation_id']]
        require(d['attempt_id'] == p['attempt_id'] and d['request_hash'] == request_hash(p['dispatch_claim']),
                'DEMO_DETAIL_REQUEST')
        if d['outcome'] == 'SUCCEEDED':
            original_paid += int(p['action']['payload']['amount_minor'])
    promised = sum(int(p['action']['payload']['amount_minor']) for p in payments[:2])
    require(int(batch['total_minor']) == promised and int(batch['paid_minor']) == original_paid, 'DEMO_BATCH_SUM')

    third = payments[2]
    record, checkpoint = third['tool_final'], third['checkpoint']
    fact, cl = record['value'], checkpoint['claim']
    strict_verify(public, raw(fact['attestation']['sig'], 64), final_sign_bytes(record))
    strict_verify(public, raw(checkpoint['signature'], 64), canonical(['COMP-TOOL-CHECKPOINT-v1', cl]))
    require(record['profile'] == cl['profile'] == profile and record['scope'] == cl['scope'] == trust['scope']
            and fact['ledger_id'] == cl['ledger_id'] == batch['ledger_id'] and cl['ledger_origin'] == batch['ledger_origin']
            and fact['operation_id'] == cl['operation_id'] == oids[2]
            and fact['dispatch_attempt'] == cl['attempt_id'] == third['attempt_id']
            and fact['action_hash'] == third['dispatch_claim']['action_hash']
            and fact['outcome'] == 'SUCCEEDED' and bool(fact['effect_id'])
            and cl['final_fact_id'] == final_fact_id(record)
            and cl['request_hash'] == request_hash(third['dispatch_claim']), 'DEMO_THIRD_FINAL')
    successes = [d for d in details.values() if d['outcome'] == 'SUCCEEDED']
    require(all(d['effect_id'] != fact['effect_id'] and d['final_seq'] != fact['final_seq']
                for d in successes), 'DEMO_DISTINCT_EFFECTS')
    third_paid = int(third['action']['payload']['amount_minor'])
    require(0 < third_paid == promised - original_paid, 'DEMO_RELEASED_AMOUNT')
    return {'batch_id': batch['batch_id'], 'currency': batch['currency'],
            'original_paid_minor': original_paid, 'third_paid_minor': third_paid,
            'total_paid_minor': original_paid + third_paid, 'confirmed_payment_effects': 2}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--root-public', required=True, help='independently supplied base64url C public key')
    args = parser.parse_args()
    result = verify(json.loads(args.report.read_text(encoding='utf-8')), raw(args.root_public, 32))
    print(json.dumps(result, ensure_ascii=False))
