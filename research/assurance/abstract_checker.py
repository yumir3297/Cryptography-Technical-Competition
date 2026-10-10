"""ZJJ-CORE-2.6-R2 finite-state *abstraction* (stdlib only).

No packet decoding, Ed25519 verification, authenticated control/source import,
real execution, crash durability or W/C trust-boundary implementation.
This model asks whether the stated state-machine guards suffice for selected
safety properties under a bounded, explicitly abstract environment.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, replace
from typing import NamedTuple
import argparse
import json

ABSENT = -1

@dataclass(frozen=True)
class State:
    # Two operation candidates share one stable business-intent key.
    revision: int = 0
    u_approved: int = ABSENT
    denied: int = ABSENT
    permit: tuple[int, int] = (ABSENT, ABSENT)
    accepted: tuple[bool, bool] = (False, False)
    legitimate_at_accept: tuple[bool, bool] = (False, False)
    revoked: bool = False
    calls: tuple[int, int] = (0, 0)
    final_fact: tuple[bool, bool] = (False, False)
    proof_epoch: tuple[int, int] = (ABSENT, ABSENT)
    settled: tuple[int, int] = (0, 0)
    tool_epoch: int = 0
    ledger_continuous: bool = True

class ModelFlags(NamedTuple):
    ignore_u: bool = False
    ignore_revision: bool = False
    ignore_deny: bool = False
    ignore_intent: bool = False
    allow_redispatch: bool = False
    allow_double_settle: bool = False
    ignore_revocation: bool = False
    separate_subjects: bool = True
    ignore_separation: bool = False

MUTANTS = {
    'ignore_u': ModelFlags(ignore_u=True),
    'ignore_revision': ModelFlags(ignore_revision=True),
    'ignore_deny': ModelFlags(ignore_deny=True),
    'ignore_intent': ModelFlags(ignore_intent=True),
    'allow_redispatch': ModelFlags(allow_redispatch=True),
    'allow_double_settle': ModelFlags(allow_double_settle=True),
    'ignore_revocation': ModelFlags(ignore_revocation=True),
    'same_subject': ModelFlags(separate_subjects=False, ignore_separation=True),
}

def put(t: tuple, i: int, v):
    x = list(t)
    x[i] = v
    return tuple(x)

def genuine_authorization(s: State, i: int, cfg: ModelFlags) -> bool:
    return (
        cfg.separate_subjects
        and s.u_approved == s.revision
        and s.permit[i] == s.revision
        and s.denied != s.revision
        and not s.revoked
    )

def successors(s: State, cfg: ModelFlags = ModelFlags()):
    # Each transition is a linearized W-visible event, unless marked external.
    if s.u_approved != s.revision and not s.revoked:
        yield 'independent_U_approve', replace(s, u_approved=s.revision)
    if s.denied != s.revision:
        yield 'publish_V_deny', replace(s, denied=s.revision)
    if s.revision == 0:
        yield 'new_basis_revision', replace(s, revision=1)
    if not s.revoked:
        yield 'revoke_role', replace(s, revoked=True)
    for i in range(2):
        # Compromised G may sign/submit a candidate Permit, irrespective of U.
        if s.permit[i] != s.revision:
            yield f'G_issue_permit_{i}', replace(s, permit=put(s.permit, i, s.revision))
        if s.permit[i] != ABSENT and not s.accepted[i]:
            valid = genuine_authorization(s, i, cfg)
            guards = (
                (cfg.ignore_u or s.u_approved == s.revision)
                and (cfg.ignore_separation or cfg.separate_subjects)
                and (cfg.ignore_revision or s.permit[i] == s.revision)
                and (cfg.ignore_deny or s.denied != s.revision)
                and (cfg.ignore_revocation or not s.revoked)
                and (cfg.ignore_intent or not any(s.accepted))
            )
            if guards:
                yield f'W_accept_{i}', replace(
                    s, accepted=put(s.accepted, i, True),
                    legitimate_at_accept=put(s.legitimate_at_accept, i, valid))
        if s.accepted[i] and not s.revoked:
            if s.calls[i] == 0 or (cfg.allow_redispatch and s.calls[i] == 1):
                yield f'claim_and_dispatch_{i}', replace(s, calls=put(s.calls, i, s.calls[i]+1))
        if s.calls[i] > 0 and not s.final_fact[i]:
            # Durable tool fact is modeled as external fact; it is not a verified tool call.
            yield f'tool_finalizes_{i}', replace(s, final_fact=put(s.final_fact, i, True))
        if s.final_fact[i] and s.ledger_continuous and s.proof_epoch[i] != s.tool_epoch:
            # Read-only re-attestation: does not increment calls or produce effects.
            yield f'reattest_final_{i}', replace(s, proof_epoch=put(s.proof_epoch, i, s.tool_epoch))
        if (s.ledger_continuous and s.final_fact[i] and s.proof_epoch[i] == s.tool_epoch and
                (s.settled[i] == 0 or (cfg.allow_double_settle and s.settled[i] == 1))):
            yield f'W_settle_{i}', replace(s, settled=put(s.settled, i, s.settled[i]+1))
    if s.tool_epoch == 0 and s.ledger_continuous:
        yield 'rotate_tool_key_with_continuity', replace(s, tool_epoch=1)
    if s.ledger_continuous:
        yield 'lose_tool_ledger_continuity', replace(s, ledger_continuous=False)

def violations(s: State):
    bad = []
    if any(a and not g for a, g in zip(s.accepted, s.legitimate_at_accept)):
        bad.append('NO_UNAUTHORIZED_ACCEPT')
    if sum(s.accepted) > 1:
        bad.append('INTENT_AT_MOST_ONCE')
    if any(n > 1 for n in s.calls):
        bad.append('NO_REDISPATCH')
    if any(n > 1 for n in s.settled):
        bad.append('SETTLE_AT_MOST_ONCE')
    if any(f and not c for f, c in zip(s.final_fact, s.calls)):
        bad.append('FACT_REQUIRES_DISPATCH')
    if any(n and (not s.final_fact[i] or not s.accepted[i]) for i, n in enumerate(s.settled)):
        bad.append('SETTLE_REQUIRES_FACT_AND_ACCEPT')
    return bad

def explore(cfg=ModelFlags(), max_depth=18, max_states=500000):
    first = State()
    queue = deque([(first, ())]); seen = {first}
    edge_count = 0
    first_violation = None
    depths = 0
    while queue:
        state, trace = queue.popleft()
        depths = max(depths, len(trace))
        bad = violations(state)
        if bad and first_violation is None:
            first_violation = {'properties': bad, 'trace': list(trace), 'state': repr(state)}
            break
        if len(trace) >= max_depth:
            continue
        for event, future in successors(state, cfg):
            edge_count += 1
            if future not in seen:
                seen.add(future)
                if len(seen) > max_states:
                    raise RuntimeError(f'model too large; visited={len(seen)}')
                queue.append((future, trace+(event,)))
    return {'visited_states': len(seen), 'explored_edges': edge_count,
            'max_reached_depth': depths, 'configured_depth': max_depth,
            'fully_explored_finite_model': first_violation is None and depths < max_depth,
            'first_violation': first_violation,
            'claim': 'bounded abstract state-space exploration only'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--depth', type=int, default=18)
    p.add_argument('--mutants', action='store_true')
    p.add_argument('--output')
    args=p.parse_args()
    out={'baseline':explore(max_depth=args.depth)}
    if args.mutants:
        out['mutants']={k:explore(v,max_depth=args.depth) for k,v in MUTANTS.items()}
    formatted=json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(formatted+'\n',encoding='utf-8')
    print(formatted)

if __name__=='__main__': main()
