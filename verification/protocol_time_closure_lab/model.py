"""Finite, one-operation protocol abstraction for TIME-CLOSURE-PROPOSED-0.1.

Authentication, archival validation and ledger continuity are explicit boolean
premises. NO signatures, wire parsing, database, network or real tool are modeled.
This is not the R2 implementation or a complete conformance checker.
"""
from collections import deque
from dataclasses import dataclass, replace, asdict
import json


@dataclass(frozen=True)
class Interval:
    lo: int
    hi: int


def advance_sample(sample, elapsed):
    """Abstract aging with trustworthy elapsed bounds, NOT a clock service.

    Missing/reset/untrusted elapsed time is represented by None. A signature
    on an old sample alone supplies no trustworthy elapsed bounds.
    """
    if elapsed is None or not (0 <= elapsed.lo <= elapsed.hi and 0 <= sample.lo <= sample.hi):
        return None
    return Interval(sample.lo + elapsed.lo, sample.hi + elapsed.hi)


def gate(iat, exp, clock, floor=0):
    if clock is None:
        return 'U'
    if not (0 <= clock.lo <= clock.hi and clock.hi - clock.lo <= 2 and clock.lo >= floor):
        return 'U'
    if clock.lo >= exp:
        return 'F'
    if iat <= clock.lo and clock.hi < exp:
        return 'T'
    return 'U'


@dataclass(frozen=True)
class Fact:
    accepted_at: int
    accepted_hi: int
    original_exp: int
    dispatch_before: int
    core: str
    ledger_origin: str = 'model-pinned-origin'
    scope: str = 'model-scope'
    operation: str = 'model-operation'


@dataclass(frozen=True)
class State:
    now: int = 100
    floor: int = 0
    fact: Fact | None = None
    accepts: int = 0
    calls: int = 0  # abstract claim/call opportunity, NOT observed tool calls
    reserved: int = 0
    mode: str = 'NONE'
    original_signed: bool = False
    observed_at: int = -1
    original_key_active: bool = True
    current_signer_active: bool = True
    current_key_generation: int = 0
    ledger_continuous: bool = True
    archive_verified: bool = True


@dataclass(frozen=True)
class Observation:
    fact: Fact
    issued_at: int
    exp: int
    query: str
    key_generation: int
    authenticated: bool = True


def commit(s, clock, *, permit_exp=120, deps_current=True, resource_free=True, original_ttl=900):
    # Prior authentication/read authorization is outside this model. Returning
    # existing fact here does not model a fresh successful protocol response.
    if s.fact is not None:
        return s
    if gate(100, permit_exp, clock, s.floor) != 'T' or not deps_current or not resource_free:
        return s
    if not s.original_key_active or not s.archive_verified:
        return s
    f = Fact(clock.lo, clock.hi, clock.lo + original_ttl, permit_exp,
             f'model-core-{clock.lo}-{clock.hi}')
    return replace(s, fact=f, accepts=1, reserved=1, mode='PENDING', floor=clock.lo)


def sign_original(s, clock, *, original_key_active=None):
    active = s.original_key_active if original_key_active is None else original_key_active
    return bool(s.fact and active and s.archive_verified and s.ledger_continuous and
                gate(s.fact.accepted_at, s.fact.original_exp, clock, s.floor) == 'T')


def attest(s, clock, *, query='query-1', ledger_continuous=None,
           archive_verified=None, current_signer_active=None):
    continuous = s.ledger_continuous if ledger_continuous is None else ledger_continuous
    archive = s.archive_verified if archive_verified is None else archive_verified
    active = s.current_signer_active if current_signer_active is None else current_signer_active
    if not (s.fact and continuous and archive and active):
        return None
    if clock is None:
        return None
    if gate(s.fact.accepted_at, clock.lo + 30, clock, s.floor) != 'T':
        return None
    # No authority or execution mutation: observation is a pure return value.
    return Observation(s.fact, clock.lo, clock.lo + 30, query, s.current_key_generation)


def verify_attestation(s, proof, clock, *, query='query-1'):
    return bool(proof and s.fact and proof.authenticated and s.archive_verified and
                s.ledger_continuous and s.current_signer_active and
                proof.key_generation == s.current_key_generation and
                proof.fact == s.fact and proof.query == query and
                gate(proof.issued_at, proof.exp, clock, s.floor) == 'T')


def claim(s, clock, *, deps_current=True):
    if not s.fact or s.mode != 'PENDING':
        return s
    g = gate(s.fact.accepted_at, s.fact.dispatch_before, clock, s.floor)
    if g == 'F' or (g == 'T' and not deps_current):
        return replace(s, mode='CANCELLED', reserved=0)
    if g != 'T':
        return s
    return replace(s, mode='STARTED', calls=1, floor=clock.lo)


def successors(s):
    clock = Interval(s.now, s.now)
    if s.now < 104:
        yield 'tick', replace(s, now=s.now + 1)
    yield 'revoke-original', replace(s, original_key_active=False)
    if s.current_key_generation == 0:
        yield 'rotate-current', replace(s, original_key_active=False,
                                       current_key_generation=1, current_signer_active=True)
    yield 'revoke-current', replace(s, current_signer_active=False)
    yield 'break-continuity', replace(s, ledger_continuous=False)
    yield 'lose-archive', replace(s, archive_verified=False)
    yield 'commit', commit(s, clock, permit_exp=102, original_ttl=3)
    if sign_original(s, clock):
        yield 'sign-original', replace(s, original_signed=True)
    if attest(s, clock):
        yield 'observe', replace(s, observed_at=s.now)
    yield 'claim', claim(s, clock)


def explore():
    initial = State()
    seen = {initial}
    queue = deque([initial])
    transitions = 0
    violations = []
    while queue:
        s = queue.popleft()
        for action, after in successors(s):
            transitions += 1
            errors = []
            if after.accepts > 1 or after.calls > 1:
                errors.append('duplicate accept/claim')
            if s.fact and after.fact != s.fact:
                errors.append('accepted fact changed')
            if action in ('observe', 'sign-original') and (
                    after.accepts, after.calls, after.reserved, after.mode, after.fact) != (
                    s.accepts, s.calls, s.reserved, s.mode, s.fact):
                errors.append('observation changed execution state')
            if action == 'commit' and not s.fact and after.fact and after.fact.accepted_hi >= 102:
                errors.append('accepted beyond permit boundary')
            if s.mode == 'STARTED' and (after.mode != 'STARTED' or after.reserved != 1):
                errors.append('timeout released started operation')
            if after.floor < s.floor:
                errors.append('trusted floor decreased')
            if errors:
                violations.append({'action': action, 'before': asdict(s), 'after': asdict(after), 'errors': errors})
            if after not in seen:
                seen.add(after)
                queue.append(after)
    return {'states': len(seen), 'transitions': transitions, 'violations': violations,
            'domain': {'clock': [100, 101, 102, 103, 104], 'operations': 1,
                       'permit_exp': 102, 'original_receipt_ttl': 3,
                       'current_key_generations': [0, 1]},
            'scope': 'finite abstract reachability only; one operation; trusted atomic accept; no crypto/W/network/tool implementation'}


def characterize():
    accepted = commit(State(), Interval(100, 100))
    expired = Interval(1000, 1000)
    changed_key = replace(accepted, original_key_active=False, current_key_generation=1)
    return {
        'r2_recovery_boundary': {
            'accepted_at': accepted.fact.accepted_at,
            'original_receipt_exp': accepted.fact.original_exp,
            'original_sign_at_expiry': sign_original(accepted, expired),
            'original_sign_after_key_revocation': sign_original(changed_key, Interval(200, 200)),
            'accept_count_unchanged': accepted.accepts,
        },
        'proposed_observation': {
            'current_proof_after_old_expiry': attest(accepted, expired) is not None,
            'current_proof_after_old_key_revocation': attest(changed_key, Interval(200, 200)) is not None,
            'new_accepts': 0, 'new_calls': 0,
        },
        'research_same_timestamp_counterexample': {
            'prepare_at': 100, 'finalize_at': 101, 'permit_exp': 120,
            'research_equality_gate_accepts': 100 == 101,
            'fresh_final_time_gate': gate(100, 120, Interval(101, 101)),
            'meaning': 'research equality gate blocks legal delay; NOT a counterexample against R2 after-commit signing',
        },
    }


if __name__ == '__main__':
    print(json.dumps({'characterization': characterize(), 'exploration': explore()}, indent=2))
