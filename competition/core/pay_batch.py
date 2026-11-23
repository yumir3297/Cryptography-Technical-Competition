"""W-side accounting for immutable, whole-original-debit PAY batch closures."""
import json

from competition.core.trusted_state import PROFILE_SCOPES, enc
from competition.core.event_clock import require_window
from competition.support.wire import action_hash, digest, msgref, raw, rec_ref, require
from competition.tools.common_tool import request_hash
from competition.tools import pay_batch as wire


PROFILE = 'PAY-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS w_pay_batch(
    batch_id TEXT PRIMARY KEY, resource_key TEXT NOT NULL, total INTEGER NOT NULL,
    paid INTEGER, certificate TEXT);
CREATE TABLE IF NOT EXISTS w_pay_batch_member(
    oid TEXT PRIMARY KEY, batch_id TEXT NOT NULL, attempt TEXT NOT NULL UNIQUE,
    amount INTEGER NOT NULL, detail TEXT, assigned INTEGER);
CREATE INDEX IF NOT EXISTS w_pay_batch_by_id ON w_pay_batch_member(batch_id);
'''


def membership(c, oid):
    return c.execute('SELECT m.*,b.resource_key,b.certificate,b.paid FROM w_pay_batch_member m '
                     'JOIN w_pay_batch b USING(batch_id) WHERE m.oid=?', (oid,)).fetchone()


def verify_member(w, c, oid, proof):
    row, frozen = w._operation(c, PROFILE, oid)
    event = w._event(c, PROFILE, oid, 'SETTLE_GUARD', frozen['commit_ref'])
    w._worker(c, PROFILE, oid, 'SETTLE', proof, event, frozen)
    require(row['state'] != 'HALTED', 'TRUSTED_CONTRADICTION')
    action = frozen['op']['action']
    tool, trust = w._tool(c, PROFILE, action, event)
    require(json.loads(tool['certificate']) == frozen['tool_certificate'], 'TOOL_TRUST_CHANGED')
    out = c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?', (PROFILE, oid)).fetchone()
    require(out is not None and out['exec_marker'] == 1 and out['packet'] is not None, 'BATCH_EXEC_REQUIRED')
    packet = json.loads(out['packet'])
    cl = packet['claim']
    require(cl['operation_id'] == oid and cl['attempt_id'] == out['attempt_id'] and
            cl['action'] == action and cl['action_hash'] == action_hash(PROFILE, action) and
            cl['commit_ref'] == frozen['commit_ref'] and cl['acceptance_ref'] == msgref(json.loads(row['receipt'])) and
            (cl['tool_trust_ref'], cl['ledger_id'], cl['ledger_origin']) ==
            (rec_ref(trust), trust['value']['ledger_id'], tool['origin']), 'BATCH_FROZEN_BINDING')
    return row, frozen, packet, event, trust['value']


def finish(w, c, proof, event, trust):
    event = w._end_event(event)
    w._finish_worker(c, proof, event)
    require_window(trust, event)


def verify_set(w, c, oids, proofs):
    require(type(oids) in (list, tuple) and 1 <= len(oids) <= 256 and all(type(x) is str for x in oids)
            and len(set(oids)) == len(oids) and type(proofs) is dict and set(oids) == set(proofs), 'BATCH_MEMBERS')
    return {oid: verify_member(w, c, oid, proofs[oid]) for oid in sorted(oids)}


def request_batch(w, oids, proofs):
    with w.source.tx() as c:
        states = verify_set(w, c, oids, proofs)
        packets = [entry[2] for entry in states.values()]
        batch_id = wire.batch_id_for(packets)
        keys = {enc(f['plan']['resource_key']) for _, f, _, _, _ in states.values()}
        require(len(keys) == 1, 'BATCH_RESOURCE')
        key = keys.pop()
        total = sum(f['plan']['amount'] for _, f, _, _, _ in states.values())
        old = c.execute('SELECT * FROM w_pay_batch WHERE batch_id=?', (batch_id,)).fetchone()
        if old is None:
            c.execute('INSERT INTO w_pay_batch VALUES(?,?,?,NULL,NULL)', (batch_id, key, total))
        else:
            require(old['resource_key'] == key and old['total'] == total, 'BATCH_BINDING')
        for oid, (row, frozen, packet, event, trust) in states.items():
            member = membership(c, oid)
            if old is None:
                require(member is None, 'BATCH_OVERLAP')
                require(row['state'] == 'STARTED' and row['effect_state'] == 'UNKNOWN' and
                        row['observed_fact'] is None, 'BATCH_MEMBER_STATE')
                w._ownership(c, PROFILE, oid, frozen)
                c.execute('INSERT INTO w_pay_batch_member VALUES(?,?,?,?,NULL,NULL)',
                          (oid, batch_id, packet['claim']['attempt_id'], frozen['plan']['amount']))
            else:
                require(member is not None and member['batch_id'] == batch_id, 'BATCH_OVERLAP')
        request = wire.make_close_request(w.delivery_key, packets)
        for oid, (_, _, _, event, trust) in states.items():
            finish(w, c, proofs[oid], event, trust)
        if old is None:
            w._journal(c, 'W_PAY_BATCH_REQUEST', PROFILE, '', {'batch_id': batch_id, 'request': request})
        return request


def possible(amounts):
    # PAY-1 capacity is capped at 10,000 minor units per pool.
    bits = 1
    for amount in amounts:
        bits |= bits << amount
    return bits


def allocation_consistent(c, batch_id, paid, observation=None):
    members = c.execute('SELECT m.oid,m.amount,m.assigned,o.observed_fact FROM w_pay_batch_member m '
                        'JOIN w_operation o ON o.profile=? AND o.oid=m.oid WHERE m.batch_id=?',
                        (PROFILE, batch_id))
    unknown = []
    remaining = paid
    for oid, amount, assigned, old in members:
        outcome = observation[1] if observation and observation[0] == oid else (
            json.loads(old)['fact']['outcome'] if old else None)
        if outcome:
            known = amount if outcome == 'SUCCEEDED' else 0
            if assigned is not None and assigned != known:
                return False
            assigned = known
        if assigned is None:
            unknown.append(amount)
        else:
            remaining -= assigned
    return 0 <= remaining <= sum(unknown) and bool((possible(unknown) >> remaining) & 1)


def settle_batch(w, certificate, proofs):
    require(type(proofs) is dict and proofs, 'WORKER_REQUIRED')
    with w.source.tx() as c:
        states = verify_set(w, c, list(proofs), proofs)
        first = next(iter(states.values()))
        claim = wire.verify_certificate(raw(first[4]['public_key'], 32), certificate)
        packets = [entry[2] for entry in states.values()]
        batch_id = wire.batch_id_for(packets)
        require(batch_id == claim['batch_id'], 'BATCH_BINDING')
        batch = c.execute('SELECT * FROM w_pay_batch WHERE batch_id=?', (batch_id,)).fetchone()
        require(batch is not None, 'BATCH_UNREQUESTED')
        members = []
        existing = batch['certificate'] is not None
        for oid, (row, frozen, packet, event, trust) in states.items():
            cl = packet['claim']
            info = membership(c, oid)
            require(info is not None and info['batch_id'] == batch_id and
                    enc(frozen['plan']['resource_key']) == batch['resource_key'], 'BATCH_BINDING')
            require((claim['profile'], claim['scope'], claim['ledger_id'], claim['ledger_origin'],
                     claim['tool_trust_ref'], claim['payer'], claim['currency']) ==
                    (PROFILE, PROFILE_SCOPES[PROFILE], cl['ledger_id'], cl['ledger_origin'],
                     cl['tool_trust_ref'], cl['action']['payload']['payer'], cl['action']['payload']['currency']),
                    'BATCH_TOOL_BINDING')
            members.append({'operation_id': oid, 'attempt_id': cl['attempt_id'], 'request_hash': request_hash(cl),
                            'amount_minor': str(info['amount'])})
            if not existing:
                require(row['state'] == 'STARTED', 'BATCH_MEMBER_STATE')
                w._ownership(c, PROFILE, oid, frozen)
        require(sorted(claim['members'], key=lambda m: m['operation_id']) == members and
                int(claim['total_minor']) == batch['total'], 'BATCH_MEMBERS')
        paid = int(claim['paid_minor'])
        if existing:
            require(json.loads(batch['certificate']) == certificate, 'BATCH_CERTIFICATE_CONFLICT')
        else:
            require(allocation_consistent(c, batch_id, paid), 'BATCH_TOTAL_CONTRADICTION')
            c.execute("UPDATE w_reservation SET state='BATCH_ACCOUNTED' WHERE profile=? AND oid IN "
                      "(SELECT oid FROM w_pay_batch_member WHERE batch_id=?)",
                      (PROFILE, batch_id))
            c.execute('UPDATE w_resource SET reserved=reserved-?,spent=spent+?,revision=revision+1 WHERE profile=? AND key=?',
                      (batch['total'], paid, PROFILE, batch['resource_key']))
            c.execute('UPDATE w_pay_batch SET certificate=?,paid=? WHERE batch_id=?', (enc(certificate), paid, batch_id))
            w._resource(c, PROFILE, json.loads(batch['resource_key']))
            w._journal(c, 'W_PAY_BATCH_CLOSED', PROFILE, '', certificate)
        for oid, (_, _, _, event, trust) in states.items():
            finish(w, c, proofs[oid], event, trust)
        return {'state': 'BATCH_CLOSED', 'batch_id': batch_id, 'existing': existing,
                'paid_minor': str(paid), 'released_minor': str(batch['total'] - paid)}


def request_detail(w, batch_id, oid, proof):
    with w.source.tx() as c:
        _, _, packet, event, trust = verify_member(w, c, oid, proof)
        member = membership(c, oid)
        require(member is not None and member['batch_id'] == batch_id and member['certificate'], 'BATCH_NOT_CLOSED')
        request = wire.make_detail_request(w.delivery_key, batch_id, packet)
        finish(w, c, proof, event, trust)
        return request


def settle_detail(w, detail, proof):
    require(type(proof) is dict and type(proof.get('claim')) is dict, 'WORKER_REQUIRED')
    oid = proof['claim'].get('operation_id')
    with w.source.tx() as c:
        row, frozen, packet, event, trust = verify_member(w, c, oid, proof)
        member = membership(c, oid)
        require(member is not None and member['certificate'], 'BATCH_NOT_CLOSED')
        certificate = json.loads(member['certificate'])
        claim = wire.verify_detail_for(raw(trust['public_key'], 32), certificate, detail)
        require((claim['operation_id'], claim['attempt_id'], claim['batch_id'], claim['request_hash'],
                 claim['amount_minor'], claim['certificate_ref']) ==
                (oid, member['attempt'], member['batch_id'], request_hash(packet['claim']),
                 str(member['amount']), wire.certificate_ref(certificate)), 'BATCH_DETAIL_BINDING')
        outcome = claim['outcome']
        paid = member['amount'] if outcome == 'SUCCEEDED' else 0
        fact_id = claim['final_fact_id'] if outcome == 'SUCCEEDED' else digest(['COMP-PAY-BATCH-NO-EFFECT-v1', claim])
        if row['observed_fact']:
            observed = json.loads(row['observed_fact'])
            require(observed['final_fact_id'] == claim['final_fact_id'] and
                    observed['fact']['outcome'] == outcome, 'BATCH_FINAL_CONTRADICTION')
        existing = member['detail'] is not None
        if existing:
            require(json.loads(member['detail']) == detail, 'BATCH_DETAIL_CONFLICT')
        else:
            require(row['state'] == 'STARTED', 'BATCH_MEMBER_STATE')
            w._ownership(c, PROFILE, oid, frozen, reservation_state='BATCH_ACCOUNTED')
            c.execute('UPDATE w_pay_batch_member SET detail=?,assigned=? WHERE oid=?', (enc(detail), paid, oid))
            require(allocation_consistent(c, member['batch_id'], member['paid']), 'BATCH_TOTAL_CONTRADICTION')
            # Batch debit remains the sole contribution to spent for these orders.
            w._clear_flight(c, PROFILE, oid, frozen)
            c.execute("UPDATE w_operation SET state='SETTLED',effect_state=? WHERE profile=? AND oid=?",
                      (outcome, PROFILE, oid))
            c.execute('INSERT INTO w_evidence(profile,oid,kind,blob) VALUES(?,?,?,?)',
                      (PROFILE,oid,'PAY_BATCH_DETAIL',enc(detail)))
            w._journal(c, 'W_PAY_BATCH_DETAIL', PROFILE, oid, detail)
        finish(w, c, proof, event, trust)
        return {'state': 'SETTLED', 'operation_id': oid, 'outcome': outcome, 'existing': existing,
                'batch_id': member['batch_id'], 'final_fact_id': fact_id}


def ordinary_settlement(member, oid):
    if member['detail']:
        claim = json.loads(member['detail'])['claim']
        fact_id = claim['final_fact_id'] or digest(['COMP-PAY-BATCH-NO-EFFECT-v1', claim])
        return {'state': 'SETTLED', 'existing': True, 'operation_id': oid, 'final_fact_id': fact_id,
                'batch_id': member['batch_id'], 'outcome': claim['outcome']}
    closed = member['certificate'] is not None
    return {'state': 'BATCH_DETAIL_REQUIRED' if closed else 'BATCH_PENDING', 'operation_id': oid,
            'batch_id': member['batch_id'], 'reservation_retained': not closed, 'final_fact_id': None}


def conflicts_with_observation(c, oid, fid, outcome):
    member = membership(c, oid)
    if member is None:
        return False
    if member['detail']:
        detail = json.loads(member['detail'])['claim']
        if (detail['final_fact_id'], detail['outcome']) != (fid, outcome):
            return True
    if member['certificate']:
        return not allocation_consistent(c, member['batch_id'], member['paid'], (oid, outcome))
    return False
