"""Signed, immutable closing statements for one simulated payment ledger."""
import json
import re

from competition.support.wire import b64, canonical, digest, is_id, number, raw, require, strict_verify
from competition.tools.common_tool import request_hash


CLOSE = 'COMP-W-PAY-BATCH-CLOSE-v1'
READ = 'COMP-W-PAY-BATCH-DETAIL-v1'
CERT = 'COMP-TOOL-PAY-BATCH-CERT-v1'
DETAIL = 'COMP-TOOL-PAY-BATCH-DETAIL-v1'
GROUP = {'profile', 'scope', 'ledger_id', 'ledger_origin', 'tool_trust_ref', 'payer', 'currency'}
MEMBER = {'operation_id', 'attempt_id', 'request_hash', 'amount_minor'}


def _fields(value, expected):
    require(type(value) is dict and set(value) == expected, 'PAY_BATCH_FIELDS')


def _signed(key, domain, claim):
    return {'claim': claim, 'signature': b64(key.sign(canonical([domain, claim])))}


def _verify(public_key, domain, obj):
    _fields(obj, {'claim', 'signature'})
    strict_verify(public_key, raw(obj['signature'], 64), canonical([domain, obj['claim']]))
    return obj['claim']


def _member(claim):
    return {'operation_id': claim['operation_id'], 'attempt_id': claim['attempt_id'],
            'request_hash': request_hash(claim), 'amount_minor': claim['action']['payload']['amount_minor']}


def _group(claim):
    require(claim['profile'] == 'PAY-1', 'PAY_BATCH_GROUP')
    return {**{k: claim[k] for k in ('profile', 'scope', 'ledger_id', 'ledger_origin', 'tool_trust_ref')},
            **{k: claim['action']['payload'][k] for k in ('payer', 'currency')}}


def _validate_member(member):
    _fields(member, MEMBER)
    raw(member['operation_id'], 16)
    raw(member['attempt_id'], 16)
    raw(member['request_hash'], 32)
    require(number(member['amount_minor'], positive=True), 'PAY_BATCH_AMOUNT')


def _identity(group, members):
    _fields(group, GROUP)
    require(group['profile'] == 'PAY-1' and is_id(group['payer']) and is_id(group['ledger_id']),
            'PAY_BATCH_GROUP')
    _fields(group['scope'], {'domain', 'tenant', 'scenario'})
    require(group['scope']['scenario'] == 'payment' and all(is_id(v) for v in group['scope'].values())
            and type(group['currency']) is str and re.fullmatch('[A-Z]{3}', group['currency']),
            'PAY_BATCH_GROUP')
    raw(group['ledger_origin'], 32)
    raw(group['tool_trust_ref'], 32)
    require(type(members) is list and 1 <= len(members) <= 256, 'PAY_BATCH_SIZE')
    for member in members:
        _validate_member(member)
    for key in ('operation_id', 'attempt_id', 'request_hash'):
        require(len({m[key] for m in members}) == len(members), 'PAY_BATCH_DUPLICATE')
    require(members == sorted(members, key=lambda m: m['operation_id']), 'PAY_BATCH_ORDER')
    return digest(['COMP-PAY-BATCH-ID-v1', group, members])


def _description(packets):
    require(type(packets) is list and 1 <= len(packets) <= 256, 'PAY_BATCH_SIZE')
    claims = [p['claim'] for p in packets]
    group = _group(claims[0])
    require(all(_group(cl) == group for cl in claims), 'PAY_BATCH_GROUP')
    members = sorted((_member(cl) for cl in claims), key=lambda m: m['operation_id'])
    return {**group, 'members': members, 'batch_id': _identity(group, members)}


def batch_id_for(packets):
    return _description(packets)['batch_id']


def make_close_request(delivery_key, packets):
    return {'authorization': _signed(delivery_key, CLOSE, {'batch_id': batch_id_for(packets)}),
            'packets': packets}


def make_detail_request(delivery_key, batch_id, packet):
    return {'authorization': _signed(delivery_key, READ, {'batch_id': batch_id, **_member(packet['claim'])}),
            'packet': packet}


def certificate_ref(certificate):
    return digest(['COMP-PAY-BATCH-CERT-REF-v1', certificate['claim']])


def verify_certificate(public_key, certificate):
    cl = _verify(public_key, CERT, certificate)
    _fields(cl, GROUP | {'members', 'batch_id', 'total_minor', 'paid_minor'})
    require(cl['batch_id'] == _identity({k: cl[k] for k in GROUP}, cl['members']), 'PAY_BATCH_BINDING')
    require(number(cl['total_minor'], positive=True) and number(cl['paid_minor'])
            and int(cl['total_minor']) == sum(int(m['amount_minor']) for m in cl['members'])
            and int(cl['paid_minor']) <= int(cl['total_minor']), 'PAY_BATCH_AMOUNT')
    return cl


def verify_detail(public_key, detail):
    cl = _verify(public_key, DETAIL, detail)
    _fields(cl, MEMBER | {'batch_id', 'certificate_ref', 'outcome', 'effect_id', 'final_seq', 'final_fact_id'})
    _validate_member({k: cl[k] for k in MEMBER})
    raw(cl['batch_id'], 32)
    raw(cl['certificate_ref'], 32)
    if cl['outcome'] == 'SUCCEEDED':
        require(is_id(cl['effect_id']) and number(cl['final_seq'], positive=True), 'PAY_BATCH_OUTCOME')
        raw(cl['final_fact_id'], 32)
    else:
        require(cl['outcome'] == 'FAILED_CONFIRMED' and
                cl['effect_id'] == cl['final_seq'] == cl['final_fact_id'] == '', 'PAY_BATCH_OUTCOME')
    return cl


def verify_detail_for(public_key, certificate, detail):
    cert = verify_certificate(public_key, certificate)
    item = verify_detail(public_key, detail)
    require(item['batch_id'] == cert['batch_id'] and item['certificate_ref'] == certificate_ref(certificate)
            and {k: item[k] for k in MEMBER} in cert['members'], 'PAY_BATCH_BINDING')
    amount = int(item['amount_minor'])
    available = int(cert['paid_minor']) if item['outcome'] == 'SUCCEEDED' else int(cert['total_minor']) - int(cert['paid_minor'])
    require(amount <= available, 'PAY_BATCH_AMOUNT')
    return item


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS pay_closed_batch(
        batch_id TEXT PRIMARY KEY, certificate TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pay_closed_member(
        operation_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL UNIQUE,
        batch_id TEXT NOT NULL REFERENCES pay_closed_batch(batch_id), detail TEXT NOT NULL)''')
    for table in ('pay_closed_batch', 'pay_closed_member'):
        for verb in ('UPDATE', 'DELETE'):
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_{verb.lower()} BEFORE {verb} ON {table}
                         BEGIN SELECT RAISE(ABORT,'IMMUTABLE_BATCH'); END""")


def _closed(c, cl):
    return c.execute('SELECT * FROM pay_closed_member WHERE operation_id=? OR attempt_id=?',
                     (cl['operation_id'], cl['attempt_id'])).fetchone()


def allow_execute(c, cl, rh, fact):
    row = _closed(c, cl)
    if row is not None:
        require(row['request_hash'] == rh and fact is not None, 'PAY_BATCH_CLOSED')


def close_batch(tool, request):
    require(tool.profile == 'PAY-1', 'PAY_BATCH_GROUP')
    _fields(request, {'authorization', 'packets'})
    authorization = _verify(tool.w_public, CLOSE, request['authorization'])
    packets = request['packets']
    require(type(packets) is list and 1 <= len(packets) <= 256, 'PAY_BATCH_SIZE')
    with tool._db() as c:
        c.execute('BEGIN IMMEDIATE')
        tool._continuity(c)
        claims = [tool._verify(p, False)[0] for p in packets]
        desc = _description(packets)
        bid = desc['batch_id']
        require(authorization == {'batch_id': bid}, 'PAY_BATCH_BINDING')
        tool._event(c, packets[0], None, False, check_request=False)
        old = c.execute('SELECT certificate FROM pay_closed_batch WHERE batch_id=?', (bid,)).fetchone()
        if old:
            c.execute('COMMIT')
            return {'certificate': json.loads(old[0])}

        details = []
        paid = 0
        for cl in claims:
            m = _member(cl)
            require(_closed(c, cl) is None, 'PAY_BATCH_OVERLAP')
            fact = tool._known(c, cl, m['request_hash'])
            result = {'outcome': 'FAILED_CONFIRMED', 'effect_id': '', 'final_seq': '', 'final_fact_id': ''}
            if fact is not None:
                require(fact['outcome'] == 'SUCCEEDED', 'CONTINUITY_UNKNOWN')
                fid = c.execute('SELECT final_fact_id FROM tool_finalfacts WHERE operation_id=?',
                                (cl['operation_id'],)).fetchone()[0]
                result = {'outcome': 'SUCCEEDED', 'effect_id': fact['effect_id'],
                          'final_seq': fact['final_seq'], 'final_fact_id': fid}
                paid += int(m['amount_minor'])
            details.append({**m, **result})
        total = sum(int(m['amount_minor']) for m in desc['members'])
        require(number(str(total)), 'PAY_BATCH_AMOUNT')
        certificate = _signed(tool.private_key, CERT, {**desc, 'total_minor': str(total), 'paid_minor': str(paid)})
        c.execute('INSERT INTO pay_closed_batch VALUES (?,?)', (bid, canonical(certificate).decode()))
        ref = certificate_ref(certificate)
        for item in details:
            detail = _signed(tool.private_key, DETAIL, {**item, 'batch_id': bid, 'certificate_ref': ref})
            c.execute('INSERT INTO pay_closed_member VALUES (?,?,?,?,?)',
                      (item['operation_id'], item['attempt_id'], item['request_hash'], bid, canonical(detail).decode()))
        # The summary and all per-attempt fences become visible together.
        tool._event(c, packets[0], None, False, check_request=False)
        c.execute('COMMIT')
        return {'certificate': certificate}


def batch_detail(tool, request):
    require(tool.profile == 'PAY-1', 'PAY_BATCH_GROUP')
    _fields(request, {'authorization', 'packet'})
    authorization = _verify(tool.w_public, READ, request['authorization'])
    _fields(authorization, MEMBER | {'batch_id'})
    raw(authorization['batch_id'], 32)
    packet = request['packet']
    with tool._db() as c:
        c.execute('BEGIN IMMEDIATE')
        tool._continuity(c)
        cl, rh = tool._verify(packet, False)
        require({k: authorization[k] for k in MEMBER} == _member(cl), 'PAY_BATCH_BINDING')
        tool._event(c, packet, rh, False, check_request=False)
        row = _closed(c, cl)
        require(row is not None and row['request_hash'] == rh and row['batch_id'] == authorization['batch_id'],
                'PAY_BATCH_MEMBER')
        c.execute('COMMIT')
        return {'detail': json.loads(row['detail'])}
