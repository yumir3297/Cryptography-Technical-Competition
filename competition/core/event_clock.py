"""Event-bound C samples for a trusted single host; no external clock attestation."""
import time

from competition.support.wire import require, canonical, raw, strict_verify, number

DOMAIN = 'ZJJ-COMP-EVENT-CLOCK-v1'
STAGES = frozenset({'PREPARE', 'ACCEPT_GUARD', 'RECEIPT_SIGN_GUARD', 'RECEIPT_PUBLISH', 'CLAIM_GUARD', 'STATUS_READ', 'AUTHZ_GUARD', 'AUTHZ_READ', 'DENY_PUBLISH', 'CONTROL_PUBLISH', 'TOOL_FINAL_AUTH', 'SETTLE_GUARD', 'EXECUTE_GUARD', 'QUERY_GUARD', 'CANCEL_GUARD', 'AUDIT_READ', 'WORKER_CHALLENGE'})
MAX_AGE_NS = 2_000_000_000
AGE_MARGIN_NS = 25_000_000

def refresh_event_age(event):
    """Final bounded interval after verification, without reusing a consumed sample."""
    cl=event['sample']['claim'];age=time.monotonic_ns()-int(cl['monotonic_ns'])
    require(0<=age<=MAX_AGE_NS-AGE_MARGIN_NS,'CLOCK_UNKNOWN')
    lo=event['lo'];hi=int(cl['hi'])+(int(cl['wall_ns'])+age+AGE_MARGIN_NS)//1_000_000_000-lo
    require(lo<=hi and hi-lo<=2,'CLOCK_UNKNOWN')
    return {**event,'hi':hi,'age_upper_bound_ns':age+AGE_MARGIN_NS}


def checked_event_clock(c, packet, root_pub, instance_id, profile, scope, operation_id, stage, request_ref):
    """Must run within the W transaction; floor/sequence rollback with its decision."""
    require(c.in_transaction, 'CLOCK_TRANSACTION_REQUIRED')
    require(type(packet) is dict and set(packet) == {'claim', 'signature'}, 'CLOCK_FIELDS')
    cl = packet['claim']
    fields = {'provider_id', 'epoch', 'instance_id', 'sequence', 'profile', 'scope', 'operation_id', 'stage', 'request_ref', 'wall_ns', 'monotonic_ns', 'lo', 'hi', 'healthy'}
    require(type(cl) is dict and set(cl) == fields, 'CLOCK_FIELDS')
    strict_verify(root_pub, raw(packet['signature'], 64), canonical([DOMAIN, cl]))
    require(stage in STAGES and (cl['provider_id'], cl['epoch'], cl['instance_id']) == ('local-c', '1', instance_id), 'CLOCK_UNKNOWN')
    require((cl['profile'], cl['scope'], cl['operation_id'], cl['stage'], cl['request_ref']) == (profile, scope, operation_id, stage, request_ref), 'CLOCK_BINDING')
    require(cl['healthy'] is True, 'CLOCK_UNKNOWN')
    require(all(number(cl[k]) for k in ('sequence', 'wall_ns', 'monotonic_ns', 'lo', 'hi')) and int(cl['sequence']) > 0, 'CLOCK_RANGE')
    age = time.monotonic_ns() - int(cl['monotonic_ns'])
    require(0 <= age <= MAX_AGE_NS - AGE_MARGIN_NS, 'CLOCK_UNKNOWN')
    wall = int(cl['wall_ns'])
    lo, sampled_hi = int(cl['lo']), int(cl['hi'])
    require(lo == wall // 1_000_000_000 and sampled_hi >= lo, 'CLOCK_RANGE')
    require(sampled_hi - lo <= 2, 'CLOCK_UNKNOWN')
    # Advance the signed sample using the trusted host monotonic age bound.
    # This covers integer Unix event time, including a crossed second boundary.
    hi = sampled_hi + (wall + age + AGE_MARGIN_NS) // 1_000_000_000 - lo
    require(lo <= hi and hi - lo <= 2, 'CLOCK_UNKNOWN')
    c.execute('CREATE TABLE IF NOT EXISTS comp_event_clock(id INTEGER PRIMARY KEY CHECK(id=1),sequence INTEGER NOT NULL,time_floor INTEGER NOT NULL)')
    c.execute('INSERT OR IGNORE INTO comp_event_clock VALUES(1,0,0)')
    old_seq, floor = c.execute('SELECT sequence,time_floor FROM comp_event_clock WHERE id=1').fetchone()
    require(int(cl['sequence']) > old_seq, 'CLOCK_REPLAY')
    require(lo >= floor, 'CLOCK_ROLLBACK')
    c.execute('UPDATE comp_event_clock SET sequence=?,time_floor=MAX(time_floor,?) WHERE id=1', (int(cl['sequence']), lo))
    return {'lo': lo, 'hi': hi, 'sequence': int(cl['sequence']), 'age_upper_bound_ns': age + AGE_MARGIN_NS, 'sample': packet, 'stage': stage}


def require_window(value, event):
    lo, hi = event['lo'], event['hi']
    iat, exp = int(value['iat']), int(value['exp'])
    if lo >= exp:
        require(False, 'EXPIRED')
    require(iat <= lo and hi < exp, 'CLOCK_UNKNOWN')
