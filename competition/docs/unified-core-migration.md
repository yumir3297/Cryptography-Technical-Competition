# Competition Edition: single common security core + three profile adapters

**Status (2026-10-10): implementation migration plan; not a claim of a deployed
unified W.** Baseline Phase18 `3633db63` and protocol time study `afc00bd2`.
The latter is explicitly a research candidate, not an executable drop-in for R2.

## 1. Existing code map

- IND: `research/phase17/process_flow.py` + `research/phase18/process_flow.py`
  + `research/phase14/verifier.py` + `research/phase16/industrial_delivery.py`.
- MED: original Phase14 verifier plus competition-extended
  `research/phase17/process_flow.py` / `research/phase18/process_flow.py`,
  with an explicit signed V clinical review and Phase16 shared simulated
  delivery ledger. On competition branch this is a 26-stage scoped pipeline;
  original research branch is unchanged.
- PAY: `research/phase15/pay_accept.py` +
  `research/phase15/process_flow.py`, its independent source-history/
  RequiredDeps resolver, without common signer broker or W/Tool outbox.
- Original official source: `system_dev/v26/contracts/*.schema.json`,
  `system_dev/v26/semantic_cases.json` and `research/formal39`, frozen.

## 2. Stable common API target

```python
class CoreService:
    def prepare(self, profile: str, request, trusted_sources) -> PrepareTicket: ...
    def accept(self, ticket: PrepareTicket, current_time, external_x_signer) -> AcceptedFact: ...
    def claim(self, operation_id: str, attempt_id: str, current_time) -> DispatchFact: ...
    def deliver(self, dispatch_fact: DispatchFact, tool_gateway) -> ToolFact: ...
    def settle(self, tool_fact: ToolFact, current_time) -> SettlementFact: ...
    def audit(self, operation_id: str) -> AuditBundle: ...

class ProfileAdapter:
    profile: str
    def validate_action(self, action): ...
    def resolve_required_deps(self, trusted_snapshot, action): ...
    def required_approvals(self, trusted_snapshot, action): ...
    def resource_claim(self, action): ...
    def tool_simulator(self): ...
```

Mandatory shared ownership: key/role/purpose verifier, authenticated clock,
trusted C/E state, DENY search, signed dependencies, consistent authorization
guard, SQLite W acceptance/nonce/intent/flight single transaction, durable
outbox, tool-side unique attempt/effect record and immutable audit provenance.

Profile modules **may not** override a false shared signature, DENY, clock,
nonce, concurrency or replay decision. Dependencies must be rebuilt from
trusted C-source snapshots; caller-supplied Permit/deps is not an oracle.

## 3. Required acceptance sequence (not yet implemented)

1. PREPARE validates current grants/sources, identifies missing approvals and
   returns a non-authorizing ticket. No resources, nonce or intent consumed.
2. FINALIZE opens one serialized W decision transaction. Obtain a **new** C
   authenticated time interval and verify its freshness/uncertainty and durable
   lower floor. Rebuild and check *all* RequiredDeps, required reviews, every
   applicable DENY (including existing history), authority and revoke state.
3. Under the same W isolation boundary, compute the **final** COMMIT and
   accepted_at from FINALIZE's guarded logical point, using current resource
   revisions; it is not PREPARE's timestamp or a client-supplied timestamp.
4. Ask the independent role-scoped X signer to sign that exact frozen Acceptance
   with bounded timeout. Verify strict Ed25519/domain/kid/role/scope/refs and
   validate the unchanged official wire Schema. X failure => rollback/no accept.
5. Before committing, recheck all required current controls and signed time
   window. Any uncertain interval, changed revision, expired grant, missing
   witness or lost signer response => rollback/no accept (or indeterminate on
   unknown database commit). The accepted point must be explicitly defined as
   the W guarded logical decision within this atomic transaction.
6. Persist acceptance, unique intent/nonce tombstones, resource reservations,
   immutable COMMIT/Acceptance bytes and audit fact in one W transaction.
   Recovery reads the stored decision; no second signing/acceptance based on
   the same attempt. No dispatch before committed acceptance.
7. Claim once, persist one signed W outbox packet, and let profile simulator
   persist once by W/attempt/operation binding. Lost tool ACK returns the
   immutable original fact. Settle once and read-only audit across both stores.

**Nontrivial protocol detail:** physical wall-clock time during sign/commit,
authoritative time interval coverage and revocations during a long-lived
transaction are NOT solved by this plan alone. The implementation must bind
the final guarded point to authenticated C time, reject stale sample/races and
require bounded signer latency; otherwise keep the operation unaccepted.
The 0.2 observation side channel may later authenticate historical facts but
must never silently substitute for original R2 Acceptance or tool authority.

## 4. Incremental code migration and exit criteria

| Wave | Change | Real exit evidence |
|---|---|---|
| A — completed initial slice | Cross-profile broker rules and sequence/floor clock | New negative tests + Phase14/15/18 regression |
| B — next P0 | Finalize-time current signing under W transaction, DENY/dependency fences | Nonzero-elapsed IND success, expiry/revoke/denial/race negative tests, signed independent audit |
| C | Remove industrial-specific broker/Tool gateway assumptions; one W ledger core | Existing IND regression preserved, no profile action bypass |
| D | MED scoped Phase18 path implemented; PAY still separate | MED 26 stages incl. required V review, signed delivery/recovery, one simulated effect. PAY must migrate next |
| E | Unified demo, reproducible security matrix and competition documents | All three through exact same core service and same source, audit output reproducible |

## 5. Competition acceptance gates (separate from 39 official)

- Positive: IND, MED, PAY each have verified C/E/X keys, authorization,
  original-schema data, COMMIT and durable execution proof.
- Negative: corrupted Ed25519, wrong kid/role/scope, omitted required
  dependency/review, applicable DENY, expiry/unknown time, revoke/change,
  stale snapshot, resource race, replay and crash-lost ACK all fail closed.
- Independent read-only auditor verifies COMMIT, Acceptance, dispatch, tool
  simulator fact, settlement and unique counters. Scoping is explicit.
- Tests include one-second-or-greater elapsed PREPARE to FINALIZE. An old test
  that expects `TIME_CHANGED` is a **known-gap detector**, not evidence of
  completing this gate.
- Never describe simulated payment as money movement, simulated medical write
  as a clinical action, or a role broker invoked by a sudo-enabled coordinator
  as independently governed signing approval.
- Original complete 39-case suite is continuously run, but its 0/39 outcome
  remains unchanged until independently adjudicated.
