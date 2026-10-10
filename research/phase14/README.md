# ZJJ-CORE-2.6-R2 — Phase 14 experimental signer-free W checkpoint

**No official full-case promotion:** `0 PASS / 0 FAIL / 39 BLOCKED_FULL_CONFORMANCE`.

## Verified boundary and implementation

- `verifier.py`: `VerifierOnlySceneW` accepts public Ed25519 C and H/G/X/U/V/E identities. The W instance cannot sign C control messages, E source records or X Acceptance, and deliberately rejects legacy `accept()`.
- `prepare_accept(op, clock)`: authenticated C PREPARE interval, original signed chain + current control and source checks, resource/behavior/flight inspection; creates a durable, unique pending ticket and deterministic 21-field COMMIT candidate **without reserving any resource or adding ACCEPTED**.
- `finalize_accept(ticket, signed_acceptance, clock)`: verifies external X signature under original schema, external trusted clock and exact COMMIT refs. Reconstructs all dependencies; global control/event journal fence, root epoch, resource and behavior revisions, and live capacity remain consistent. Only then updates scene, behavior, resource, taskflight and accepted archive inside a single `BEGIN IMMEDIATE` transaction. Any failure before COMMIT rolls back all acceptance effects.
- `process_flow.py`: IND and MED bootstrap, independent C clock/certificate signing, verifier-only W PREPARE/FINALIZE, independent X signature issuance, independent simulated tool fact, dispatch, settlement, restart rejection and read-only signature+SQLite verification, each as distinct Python interpreter invocations. Some data/provenance attestation logic reuses the original Phase13 read-only auditor.
- `test_phase14.py`: scoped positive and rejection regressions. Passing unittest counts are **not** official cases.

## Reproduce in a clean checkout

```bash
python -m pip install -r requirements_phase13.txt
python -m unittest research.phase14.test_phase14 -v
python -m research.phase14.process_flow --output research/phase14/evidence/core01_process
python -m research.formal39.run_formal39
python -m research.phase14.build_report --evidence research/phase14/evidence/core01_process
```

These commands generate `research/phase14/phase14_report.json`, `phase14_39case_matrix.csv`, SQLite state witnesses and `research_archives/ZJJ_CORE_2_6_R2_Phase14_Candidate_20261009.zip`. The CI workflow reproduces the same operations, retains raw logs and only commits generated evidence if all steps succeed.

## Explicit unresolved security and conformance boundaries

1. Signer separation is by *Python process*, **not by operating-system security principal, HSM or external root-trust authority**. Publicly known deterministic Phase8 fixture seeds remain accessible to any party with code execution in the same lab. Do not use them in production.
2. The synthetic IND/MED bootstrap fixture initially constructs C, E and X signers to generate original source and enrollment records. The new W instances do not retain private signing keys, but a true independently operated C/E issuance lifecycle remains outstanding.
3. PAY uses the Phase13 legacy process candidate. **PAY verifier-only external-X two-phase migration is NOT complete**; therefore the three-profile Phase14 trust boundary is not fully closed.
4. Two local SQLite scene profiles are not one deployed cross-profile authority; synchronous local C clocks are not independently trusted physical time. `ToolLedger` is a simulated fact origin, not physical/clinical proof.
5. Transitive typed RequiredDeps, full T/F/U semantics, path/aud/0-RTT, STATUS, Result, upstream C/E governance and official negative branches are incomplete.
6. CORE-03, CORE-13, CORE-15, AUD-02A/B/C remain prior-phase scoped evidence; their official rows are unchanged.

The `research/formal39` original dispatcher, `system_dev/v26/semantic_cases.json` and the three original JSON Schemas are retained unchanged. `build_report.py` refuses to generate results if any official asset's pinned SHA-256 changes or if any of the 39 formal case statuses appears to have been promoted.
