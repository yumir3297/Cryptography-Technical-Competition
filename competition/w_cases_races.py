"""Reusable actual races for the competition CLI and unittest suite.

README categories: same_intent8 tests acceptance uniqueness; last_resource tests
capacity contention with separate authenticated Scene/Task/Behavior rows;
claim_cancel_revoked and claimed_cancel8 test claim/cancel ordering. Each case
requires a fresh WRun. last_resource requires the IND C resource capacity to be
initialized to 1. Functions never initialize/reset W, create fake guard results,
or label an unexpected failure as passed. Parent CLI owns public snapshots.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from competition.profiles.w_scenarios import register_ind_unit
from competition.support.wire import ProtocolError, msgref


PROFILE = 'IND-DEMO-1'


def _execute(fn):
    try:
        return {'kind': 'value', 'value': fn()}
    except ProtocolError as exc:
        return {'kind': 'rejection', 'code': exc.code}
    except Exception as exc:
        return {'kind': 'error', 'code': type(exc).__name__, 'message': str(exc)}


def _race(functions):
    barrier = threading.Barrier(len(functions))
    def start(fn):
        barrier.wait()
        return _execute(fn)
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(start, functions))


def _prepare(run, op):
    ticket = run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))['ticket_id']
    return ticket, run.accept_proof(PROFILE, ticket)


def _accept_original(run):
    op = run.operations[PROFILE]
    ticket, proof = _prepare(run, op)
    run.w.accept(PROFILE, ticket, proof)
    return op['action']['operation_id']


def _metrics(run):
    with run.store.db() as c:
        resources = c.execute('SELECT capacity,reserved,spent FROM w_resource WHERE profile=?', (PROFILE,)).fetchall()
        return {'capacity': sum(row['capacity'] for row in resources),
                'reserved': sum(row['reserved'] for row in resources),
                'spent': sum(row['spent'] for row in resources),
                'reservations': c.execute('SELECT COUNT(*) FROM w_reservation WHERE profile=?', (PROFILE,)).fetchone()[0],
                'active_flights': c.execute('SELECT COUNT(*) FROM w_flight WHERE profile=? AND active=1', (PROFILE,)).fetchone()[0]}


def _case(name, run, expected, perform):
    start = time.monotonic()
    outcomes = []
    try:
        actual, outcomes = perform()
        actual.update(_metrics(run))
        counts = run.w.counts()
        actual.update({k: counts[k] for k in ('accepts', 'outbox', 'attempts', 'exec_invocations', 'cancellations')})
        passed = all(actual.get(k) == value for k, value in expected.items())
    except Exception as exc:
        actual = {'scenario_error': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)}
        try: counts = run.w.counts()
        except Exception: counts = {}
        passed = False
    return {'case': name, 'profile': PROFILE, 'expected': expected, 'actual': actual,
            'passed': passed, 'counts': counts, 'outcomes': outcomes,
            'elapsed_seconds': time.monotonic() - start}


def same_intent8(run):
    """Eight real fresh ops/permits are all prepared before concurrent accepts."""
    expected = {'distinct_operations': 8, 'distinct_permits': 8, 'prepared': 8,
                'winners': 1, 'rejections': 7, 'unexpected_errors': 0, 'unexpected_rejections': 0,
                'reservations': 1, 'reserved': 1, 'spent': 0,
                'accepts': 1, 'outbox': 1, 'attempts': 0, 'exec_invocations': 0}
    def perform():
        ops = [run.fork_operation(PROFILE) for _ in range(8)]
        prepared = [_prepare(run, op) for op in ops]
        outcomes = _race([lambda ticket=ticket, proof=proof: run.w.accept(PROFILE, ticket, proof)
                          for ticket, proof in prepared])
        conflict_codes = {'STALE', 'DEP_CONFLICT', 'INTENT_CONFLICT', 'SCENE_NOT_READY', 'ASSESSMENT_MISMATCH'}
        actual = {'distinct_operations': len({op['action']['operation_id'] for op in ops}),
                  'distinct_permits': len({msgref(op['permit']) for op in ops}), 'prepared': len(prepared),
                  'winners': sum(r['kind'] == 'value' and r['value']['acceptance_state'] == 'COMMITTED' for r in outcomes),
                  'rejections': sum(r['kind'] == 'rejection' for r in outcomes),
                  'unexpected_rejections': sum(r['kind'] == 'rejection' and r['code'] not in conflict_codes
                                               for r in outcomes),
                  'unexpected_errors': sum(r['kind'] == 'error' for r in outcomes),
                  'rejection_codes': [r['code'] for r in outcomes if r['kind'] == 'rejection']}
        return actual, outcomes
    return _case('same_intent8', run, expected, perform)


def last_resource(run):
    """Two independent authenticated business intents compete for one IND slot."""
    expected = {'prepared': 2, 'independent_business_rows': True, 'winners': 1,
                'resource_rejections': 1, 'rejection_codes': ['RESOURCE_EXHAUSTED'],
                'unexpected_errors': 0, 'capacity': 1, 'reserved': 1, 'spent': 0,
                'reservations': 1, 'accepts': 1, 'outbox': 1, 'attempts': 0, 'exec_invocations': 0}
    def perform():
        second = register_ind_unit(run, unit_id='unit-b', batch_id='batch-b', principal='principal-b')
        first = run.fork_operation(PROFILE)
        prepared = [_prepare(run, op) for op in (first, second)]
        outcomes = _race([lambda ticket=ticket, proof=proof: run.w.accept(PROFILE, ticket, proof)
                          for ticket, proof in prepared])
        codes = [r['code'] for r in outcomes if r['kind'] == 'rejection']
        actual = {'prepared': len(prepared), 'independent_business_rows':
                    first['task_id'] != second['task_id'] and first['scene_key'] != second['scene_key'] and
                    first['action']['principal'] != second['action']['principal'],
                  'winners': sum(r['kind'] == 'value' and r['value']['acceptance_state'] == 'COMMITTED' for r in outcomes),
                  'resource_rejections': codes.count('RESOURCE_EXHAUSTED'), 'rejection_codes': codes,
                  'unexpected_errors': sum(r['kind'] == 'error' for r in outcomes),
                  'business_rows': [{'operation_id': op['action']['operation_id'], 'principal': op['action']['principal'],
                                     'task_id': op['task_id'], 'scene_key': op['scene_key']} for op in (first, second)]}
        return actual, outcomes
    return _case('last_resource', run, expected, perform)


def claim_cancel_revoked(run):
    """After a real G revocation, claim cannot race past valid cancellation."""
    expected = {'successful_states': ['CANCELED'], 'claim_rejected': True, 'unexpected_errors': 0,
                'accepts': 1, 'outbox': 1, 'attempts': 0, 'exec_invocations': 0,
                'cancellations': 1, 'reserved': 0, 'spent': 0, 'active_flights': 0}
    def perform():
        oid = _accept_original(run)
        run.base.update_role(PROFILE, 'G', False)
        claim_proof = run.worker_proof(PROFILE, oid, 'CLAIM')
        cancel_proof = run.worker_proof(PROFILE, oid, 'CANCEL')
        outcomes = _race([lambda: run.w.claim(PROFILE, oid, claim_proof),
                          lambda: run.w.cancel(PROFILE, oid, cancel_proof)])
        actual = {'successful_states': [r['value']['dispatch_state'] for r in outcomes if r['kind'] == 'value'],
                  'claim_rejected': outcomes[0]['kind'] == 'rejection' and
                                    outcomes[0]['code'] in {'REVOKED', 'RECEIPT_PENDING'},
                  'unexpected_errors': sum(r['kind'] == 'error' for r in outcomes)}
        return actual, outcomes
    return _case('claim_cancel_revoked', run, expected, perform)


def claimed_cancel8(run):
    """Eight claims freeze one attempt; later revocation cannot cancel STARTED."""
    expected = {'claim_successes': 8, 'distinct_attempts': 1, 'cancel_code': 'CANCEL_STARTED',
                'unexpected_errors': 0, 'accepts': 1, 'outbox': 1, 'attempts': 1,
                'exec_invocations': 0, 'cancellations': 0, 'reserved': 1, 'spent': 0, 'active_flights': 1}
    def perform():
        oid = _accept_original(run)
        proofs = [run.worker_proof(PROFILE, oid, 'CLAIM') for _ in range(8)]
        outcomes = _race([lambda proof=proof: run.w.claim(PROFILE, oid, proof) for proof in proofs])
        run.base.update_role(PROFILE, 'G', False)
        cancel = _execute(lambda: run.w.cancel(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CANCEL')))
        successes = [r['value'] for r in outcomes if r['kind'] == 'value']
        actual = {'claim_successes': len(successes), 'distinct_attempts': len({r['attempt_id'] for r in successes}),
                  'cancel_code': cancel.get('code'),
                  'unexpected_errors': sum(r['kind'] == 'error' for r in outcomes + [cancel])}
        return actual, outcomes + [cancel]
    return _case('claimed_cancel8', run, expected, perform)


CASES = {'same_intent8': same_intent8, 'last_resource': last_resource,
         'claim_cancel_revoked': claim_cancel_revoked, 'claimed_cancel8': claimed_cancel8}
