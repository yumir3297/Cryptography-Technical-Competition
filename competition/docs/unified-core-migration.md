# Competition Edition: single common security core + three profile adapters

**Status (2026-10-11): common authorization implemented and consumed by IND
actual acceptance; complete three-profile business W still pending.** Baseline Phase18 `3633db63` and protocol time study `afc00bd2`.
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

The frozen application contract is COMP-APP-MIN-1.0: prepare, accept, claim,
execute_once, query_attempt, settle, status, audit. Core owns identity, time,
dependencies, deny decisions, unique acceptance, reservation and recovery.
Adapters own business validation, dependency descriptions and simulated tools;
none may override a shared false/unknown verdict. Caller cannot supply an
attempt id or decision timestamp. After started, only query_attempt is legal.

The local IND slice implements prepare/accept, receipt completion and authenticated
application status. claim is conservative refusal; delivery/settlement/audit and
three-profile shared W remain future waves. It adds one-use H identity challenges
rather than treating a ticket as caller authentication.

A-01..04 now provide CommonGuard/TrustedState/ScopedSignerBroker and three
trusted derivation adapters. DENY publications and IND actual acceptance share
one SQLite transaction order. [authorization-contract.md](authorization-contract.md)
defines current APIs, source binding and medical read-before-candidate ACL.
PAY all roles are enrolled in this competition path; historical Phase18 broker
tests intentionally retain their original PAY-H-unregistered expectations.

## 3. Default R2 acceptance sequence

Use [acceptance-sequence.md](acceptance-sequence.md) as the concrete local
contract. W checks fresh time/dependencies/current grants, freezes and durably
commits the original COMMIT/Core/Refs and one reservation first. Then X reads
that committed Core and signs it under a bounded current W guard. W rechecks
receipt publication time/current X and saves exact signature bytes. Signature
failure after COMMIT means pending receipt with reservation retained, not rollback.
Claim requires a legal saved receipt and PR3's further current dispatch checks.
An unknown commit ACK requires original-state lookup, never a new action.

accepted_at is the final logical ACCEPT_GUARD lo, not physical disk time. The
real signature generation time is separately evidenced; the original Core iat
is historical accepted_at. Same-W control revision locking plus time age/health
checks support only the stated trusted-host logical guard. They do not prove
external hardware physical-time revocation freedom. Long-term Observation and
independent time facilities remain research/post-competition work.

## 4. Incremental code migration and exit criteria

| Wave | Change | Real exit evidence |
|---|---|---|
| A — completed initial slice | Cross-profile broker rules and sequence/floor clock | New negative tests + Phase14/15/18 regression |
| B — next P0 | Local IND durable-accept/frozen receipt slice; full approvals/DENY and three-profile migration pending | Nonzero-elapsed IND success, expiry/revoke/denial/race negative tests, signed independent audit |
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
