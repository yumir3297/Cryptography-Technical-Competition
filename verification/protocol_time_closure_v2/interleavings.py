"""Finite interleavings for the candidate time-observation contract.

There is one already durable historical acceptance, one server query/nonce and
two distinct client query bindings.  The second query is only a replay target;
this is not an exploration of two concurrent server observation transactions.
Cryptographic authenticity, historical authorization, linearizable protected W
transactions and authenticated current control mappings are explicit premises.
No database, network, real clock, private-key operation or device is implemented.

Reading, calculating a candidate signature, publication and receiving are
separate events.  A candidate is NOT an issued protocol proof.  Publication is
the protocol qualification point and compare-and-set on the control revision
and pending query nonce.  A frozen state snapshot may age independently.
All checks below concern safety in this finite domain, never eventual delivery,
fairness, physical device deadlines or complete R2/product conformance.
"""
from collections import deque
from dataclasses import asdict, dataclass, replace


EXPIRES = 4
FACT = ("original-core-bytes", "original-commit-ref", 0, "scope-A", "op-A")
QUERY = ("query-0-ref", "nonce-0", "attempt-0", "session-0")
OTHER_QUERY = ("query-1-ref", "nonce-1", "attempt-1", "session-1")


@dataclass(frozen=True)
class Snapshot:
    read_at: int
    status_seq: int
    revision: int
    generation: int
    fact: tuple = FACT
    query: tuple = QUERY


@dataclass(frozen=True)
class Candidate:
    snapshot: Snapshot
    sign_at: int
    exp: int = EXPIRES

    def bytes(self):
        # A deterministic symbolic byte identity, not a real signature/encoding.
        return repr((self.snapshot, self.sign_at, self.exp)).encode("ascii")


@dataclass(frozen=True)
class Published:
    candidate: Candidate
    publish_at: int
    response: bytes


@dataclass(frozen=True)
class State:
    now: int = 0
    revision: int = 0
    generation: int = 0
    delegation_active: bool = True
    requester_active: bool = True
    observer_scope: bool = True
    observer_purpose: bool = True
    continuous: bool = True
    archive: bool = True
    status_seq: int = 0
    snapshot: Snapshot | None = None
    candidate: Candidate | None = None
    published: Published | None = None
    pending_nonce: bool = True
    fact: tuple = FACT
    accepted: int = 1
    reserved: int = 1
    dispatch: int = 0


def current_t(s):
    """Every current authorization, scope/purpose, history and time gate is T.

    Trusted event intervals in this bounded model are [now, now].  A real
    verifier must obtain a trustworthy bounded interval covering its event.
    Unknown premises are conservatively represented by False; this abstraction
    cannot distinguish a known denial F from unavailable evidence U.
    """
    return (s.now < EXPIRES and s.delegation_active and s.requester_active
            and s.observer_scope and s.observer_purpose and s.continuous
            and s.archive)


def can_publish(s, *, use_cas=True):
    c = s.candidate
    return bool(c and s.pending_nonce and s.published is None and current_t(s)
                and c.snapshot.query == QUERY and c.snapshot.fact == s.fact
                and c.snapshot.generation == s.generation
                and c.sign_at <= s.now < c.exp
                and (not use_cas or c.snapshot.revision == s.revision))


def client_accepts(s, proof, expected_query, *, exact_response=None):
    """Receive only the exact authenticated W publication for this request.

    A matching independently constructed/signed candidate is insufficient.
    Current mapping and trusted current time are rechecked at this event.
    status_seq is the signed read snapshot, not a promise of current execution
    status.  Exact publication authentication is an explicit W-interface oracle.
    """
    if not (proof and s.published and current_t(s)):
        return False
    p = s.published
    response = proof.response if exact_response is None else exact_response
    return bool(proof == p and response == p.response
                and p.candidate.snapshot.query == expected_query
                and p.candidate.snapshot.fact == s.fact
                and p.candidate.snapshot.revision == s.revision
                and p.candidate.snapshot.generation == s.generation
                and p.candidate.sign_at <= s.now < p.candidate.exp)


def successors(s, *, use_cas=True):
    # metadata holds event outcomes even for rejected/no-state-change attempts.
    if s.now < EXPIRES:
        yield "tick", replace(s, now=s.now + 1), {}
    if s.status_seq == 0:
        yield "advance-W-status", replace(s, status_seq=1), {}
    if s.revision == 0:
        # Only role/task delegation is restored below.  This NEVER restores a
        # permanently revoked R2 kid.  Every control change advances revision.
        yield "revoke-delegation", replace(s, revision=1, delegation_active=False), {}
        yield "renew-control-grant", replace(s, revision=2), {}
        yield "rotate-observer-key", replace(s, revision=2, generation=1), {}
    elif s.revision == 1:
        yield "regrant-delegation", replace(s, revision=2, delegation_active=True), {}
        yield "regrant-with-new-key", replace(s, revision=2, generation=1,
                                               delegation_active=True), {}
    for flag in ("requester_active", "observer_scope", "observer_purpose",
                 "continuous", "archive"):
        if getattr(s, flag):
            yield "invalidate-" + flag, replace(s, **{flag: False}), {}
    if s.pending_nonce and current_t(s):
        snap = Snapshot(s.now, s.status_seq, s.revision, s.generation)
        yield "observe-read", replace(s, snapshot=snap, candidate=None), {}
    if s.snapshot and s.pending_nonce and current_t(s):
        # A current check can authorize precomputation, yet the old frozen
        # snapshot may carry another revision.  Only publication makes it proof.
        c = Candidate(s.snapshot, s.now)
        yield "sign-candidate", replace(s, candidate=c), {}
    if can_publish(s, use_cas=use_cas):
        p = Published(s.candidate, s.now, s.candidate.bytes())
        yield "publish-CAS" if use_cas else "publish-without-revision-CAS", \
            replace(s, published=p, pending_nonce=False), {}
    if s.published:
        yield "exact-retransmission", s, {"response": s.published.response}
        yield "client-receive", s, {"accepted": client_accepts(s, s.published, QUERY)}
        yield "client-receive-new-query-replay", s, {
            "accepted": client_accepts(s, s.published, OTHER_QUERY)}
        yield "client-receive-altered-response", s, {
            "accepted": client_accepts(s, s.published, QUERY,
                                       exact_response=s.published.response + b"changed")}
    if s.candidate and s.published is None:
        # A caller holding a candidate cannot treat it as a W publication.
        fake = Published(s.candidate, s.now, s.candidate.bytes())
        yield "client-receive-unpublished-candidate", s, {
            "accepted": client_accepts(s, fake, QUERY)}


def edge_errors(s, action, after, metadata):
    errors = []
    if (after.fact, after.accepted, after.reserved, after.dispatch) != (
            s.fact, s.accepted, s.reserved, s.dispatch):
        errors.append("historical fact or execution counters changed")
    if s.published and after.published != s.published:
        errors.append("published response changed")
    if action.startswith("publish"):
        if not current_t(s):
            errors.append("publication without all current premises T")
        if s.candidate.snapshot.revision != s.revision:
            errors.append("publication crossed control revision")
        if not s.pending_nonce or s.published is not None or after.pending_nonce:
            errors.append("publication did not CAS pending query nonce exactly once")
    if action == "exact-retransmission" and metadata["response"] != s.published.response:
        errors.append("retransmission changed stored response bytes")
    if action.startswith("client-receive") and metadata["accepted"]:
        if action != "client-receive":
            errors.append("wrong query, altered or unpublished proof accepted")
        if not current_t(s) or s.now >= EXPIRES:
            errors.append("receive succeeded after expiry or current denial")
        if s.published.candidate.snapshot.revision != s.revision:
            errors.append("receive accepted stale control mapping")
    return errors


def describe(s):
    d = asdict(s)
    if d["published"]:
        d["published"]["response"] = s.published.response.decode("ascii")
    return d


def explore(*, use_cas=True, stop_at_first=False):
    first = State()
    queue = deque([first])
    parents = {first: None}
    transitions = 0
    violations = []
    successful_receive = False
    observed_after_status_advance = False
    while queue:
        s = queue.popleft()
        for action, after, metadata in successors(s, use_cas=use_cas):
            transitions += 1
            if action == "client-receive" and metadata["accepted"]:
                successful_receive = True
                observed_after_status_advance |= (
                    s.published.candidate.snapshot.status_seq < s.status_seq)
            errors = edge_errors(s, action, after, metadata)
            if errors:
                trace = []
                cursor = s
                while parents[cursor] is not None:
                    before, event = parents[cursor]
                    trace.append({"event": event, "after": describe(cursor)})
                    cursor = before
                trace.reverse()
                trace.append({"event": action, "after": describe(after)})
                violations.append({"errors": errors, "trace": trace,
                                   "trace_length": len(trace)})
                if stop_at_first:
                    return {"states": len(parents), "transitions": transitions,
                            "violations": violations, "shortest_by_BFS": True}
            if after not in parents:
                parents[after] = (s, action)
                queue.append(after)
    return {"states": len(parents), "transitions": transitions,
            "violations": violations, "coverage": {
                "successful_receive_reachable": successful_receive,
                "receive_of_older_authenticated_status_snapshot_reachable":
                    observed_after_status_advance}}


def aba_counterexample():
    """A concrete role/task ABA witness; no permanently revoked kid restored."""
    s = State()
    trace = []
    for wanted in ("observe-read", "sign-candidate", "revoke-delegation",
                   "regrant-delegation", "publish-without-revision-CAS"):
        before = s
        _, s, metadata = next(x for x in successors(s, use_cas=False) if x[0] == wanted)
        trace.append({"event": wanted, "after": describe(s)})
    return {"trace": trace, "trace_length": len(trace),
            "errors": edge_errors(before, wanted, s, metadata),
            "meaning": "Role/task delegation was revoked and newly granted; an old revision candidate must be discarded."}


def run():
    checked = explore()
    legacy = explore(use_cas=False, stop_at_first=True)
    return {
        "domain": {"trusted_event_time": [0, 1, 2, 3, 4],
                   "query_and_observer_exp": EXPIRES,
                   "control_revisions": [0, 1, 2], "key_generations": [0, 1],
                   "historical_acceptances": 1, "server_query_transactions": 1,
                   "client_query_bindings": [QUERY, OTHER_QUERY],
                   "status_seq": [0, 1],
                   "premises": ["authentic current C mapping", "trustworthy event interval",
                                "linearizable protected W publication and nonce CAS",
                                "authentic exact W publication lookup", "authenticated W read snapshot",
                                "correct historic durable acceptance and original fact",
                                "cryptographic authenticity assumed; no real signatures here"],
                   "limits": "Finite safety abstraction; no fairness, liveness, database, network, real clock or device proof."},
        "invariants": ["publication rechecks all current gates and control revision",
                       "pending query nonce consumed by exactly one publication",
                       "receive binds exact published bytes and expected current query",
                       "published response immutable; retransmission exact",
                       "fact/accepted/reserved/dispatch counters never change",
                       "expiry prevents successful publication/receive and introduces no execution",
                       "independently advanced W status does not change frozen signed snapshot"],
        "cas_model": checked,
        "legacy_without_CAS": legacy,
        "delegation_ABA_counterexample": aba_counterexample(),
        "passed": not checked["violations"] and bool(legacy["violations"])
                  and checked["coverage"]["successful_receive_reachable"]
                  and checked["coverage"]["receive_of_older_authenticated_status_snapshot_reachable"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), ensure_ascii=False, indent=2))
