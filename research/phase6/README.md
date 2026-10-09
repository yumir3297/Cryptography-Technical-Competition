# Phase 6 — ZJJ-CORE-2.6-R2 durable tool-final recovery research

**Strict identity of the work:** additive reference experiment for PAY-1, against GitHub `yumir3297/Cryptography-Technical-Competition`, historical `main` commit `0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c`. This is **not a production protocol service**, **not a new cryptographic primitive**, and **not formal proof of 39 official semantic cases**.

## Reproduce

Unzip at the root of the original repository; do not overwrite `system_dev/`, `docs/`, or `verification/`. Python 3.10+ with `cryptography`, `PyNaCl`, `jsonschema`.

```bash
python -m research.phase6.run_phase6
# In the original repository containing its unchanged official schemas and semantic manifest:
python -m research.phase6.run_phase6 --upstream-root .
```

The first command runs baseline Phases 1–5 and Phase 6, saves `test_log.txt`, `validation_report.json`, `signed_durable_final_traces.json`, and `case_evidence_matrix.json`. **When the upstream JSON is absent, `official_schema.status` is `NOT_RUN_OFFICIAL_JSON_UNAVAILABLE`, not PASS.** The second command refuses to proceed if the official PAY schema bytes mismatch the pinned Git blob SHA-1 `86ba1bae0e4c455899af661bed44edfc5494aa5e` or if `semantic_cases.json` differs from the pinned 39-case list. It then invokes the existing upstream PAY schema validator on generated signed protocol objects. This is *structural* validation, not authorization correctness.

## What Phase 6 actually implements

1. `ToolLedger`: a separate SQLite effect-ledger simulator. Freezes a unique `(operation_id, attempt)` outcome with one final sequence and an effect ID unique within the ledger; has read-only lookup and reattestation from the stored fact. Missing entry **never implies** `FAILED_CONFIRMED`.
2. `Controller`: signs a domain-separated **research-only** control certificate covering an exact schema-shaped `TOOL_TRUST` Record, monotonic epoch/revision, ledger origin and current local snapshot digest. The trusted controller root is a fixed test fixture. The signed sidecar is **not claimed as an upstream-defined CONTROL wire type**.
3. `FinalW`: extends Phase-5 SQLite authority with durable `tool_trust`, `dispatch_witness`, `settled`, and `final_seen`. Claim checks frozen action, trust, deadline and unique attempt, but **does not yet implement the complete normative dispatch-time dynamic dependency guard**.
4. `TOOL_FINAL`: exact R2 schema field set. Strict Ed25519 signature over `ZJJ-TOOL-FINAL-v2` domain; current authenticated trust mapping, expiry, profile/scope, attempt, action hash, ledger and source identity must agree.
5. `FinalFactID` is separate from `RecordRef`. Changing attestation time or rotating keys changes RecordRef but not the immutable fact ID. `SUCCEEDED` moves one reservation to spent; `FAILED_CONFIRMED` releases it without spending. `settlement_count` cannot exceed one.
6. Signed, bound contradictory FinalFacts HALT, without reversing an already settled ledger. Bad signatures / wrong attempts / wrong tool / expired proofs do not change W and never HALT a valid operation.
7. Two real subprocess `os._exit(79)` crashes: after durable tool freeze but before W receipt, and after W settlement but before client response. Restart + read-only tool reattestation restores the same fact; neither interval creates a second execution.
8. Tool-ledger **origin is distinct from ledger_id**, persisted across restart and included in signed C certificate. A newly created ledger using the same textual ledger_id but a different origin is rejected at rotation. This is still not a distributed, hardware-backed, independently proven ledger-continuity protocol; a malicious controller or ledger storage administrator is outside these experiments.

## Research trace cases and result status

- `SUCCEEDED`: single immutable final, atomic W settlement, subsequent historical replay.
- `FAILED_CONFIRMED`: explicit no-late-effect tool final, reservation release, accepted-count tombstone retained.
- `ROTATION`: same ledger, higher signed epoch, different tool key, reattested original fact, one W settlement.
- 28 Phase-6 unit tests plus 200 tests carried over from Phases 1–5 (locally 228/228).
- 39 official case rows represented in `case_evidence_matrix.json`, each remains **NOT_RUN** for full conformance; eight have associated partial Phase-6 research tests. The matrix is not an official test pass report.

## Trust and proof boundaries

- Controller root and issued roles, reader scope, old Evidence provenance, and PAY policy/task publication remain fixtures from previous phases. `Controller` has a signing key, but root-management enrollment/revocation and the complete C source-publication protocol are not implemented.
- Separate SQLite database files remove the illusion of a single atomic W/tool transaction, but they do **not** simulate an independent physical tool, hardware secrets, stable network identity, disk power loss, or replicated database failover.
- The controller certification binds a ledger origin and digest but cannot rule out a privileged actor cloning both a ledger and its origin. W's local check verifies equality of **previously confirmed** final facts, not unknowable lost tool effects. R2's trust assumption of correct C/ledger continuity is retained.
- Exact-once **W settlement** and at-most-once *simulated* dispatch are different from exactly-once real-world side effects.
- The incomplete mandatory work remains: unmodified official schema validation in the same repo checkout; all 39 end-to-end case runners with independent authority, T/F/U, E/C provenance, H/U/G/X credentials; IND/MED strict profiles; complete dispatch-time current-state reconstruction; independently auditable C ledger migration.

**No commit was pushed to GitHub.** Prior attempts to create a branch using the connected GitHub integration returned 403; this remains a locally mergeable additive patch.
