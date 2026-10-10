# ZJJ CORE 2.6-R2 / Phase 7: formal-schema gate and revocation-safe dispatch research

**Date**: 2026-10-09. **Scope**: isolated PAY-1 laboratory; this is not a certification or proof of all 39 official semantic cases.

## What was run and what is evidenced

1. The **exact original** `system_dev/v26/contracts/pay1.schema.json` was recovered from GitHub, reconstituted without modification, and checked against the original Git blob SHA-1 `86ba1bae0e4c455899af661bed44edfc5494aa5e` (101,858 bytes). This is not a locally invented substitute.
2. Draft 2020-12 (`jsonschema`) validates **50** emitted signed-chain objects over CLEAR / FLAG / INSUFFICIENT PAY-1 paths. Two signed support records, TOOL_TRUST and TOOL_FINAL, also passed.
3. The official-schema regression suite checks **858** validation probes: 50 positive generated objects, 2 signed support records, 192 removed outer required fields, 464 removed payload/value required fields, 50 additional top-level properties, and 100 profile-confusion substitutions. Rejection probes were expected to be rejected; the tests enforce that expectation.
4. All historical Phase 1–6 regressions and Phase 7 tests pass. Run `python -m research.phase7.run_phase7` from repository root; see `test_log.txt` and `validation_report.json`.
5. **Confirmed and reproduced gap**: the legacy research `FinalW.claim_bound` accepted a dispatch after a post-acceptance POLICY revocation because it never queried live C state (`test_dispatch_gap.py`). This is a vulnerability of the *reference prototype*, not demonstrated to exist in the abstract R2 contract. Importantly, a test that reproduces the gap is not a passing safety result.
6. Added **experimental fail-closed mitigation** `GuardedFinalW` (`guarded_dispatch.py`). It accepts only C-root signed authority publications and reads the resulting authoritative dependency rows atomically in the same SQLite `BEGIN IMMEDIATE` transaction as `ClaimDispatch`. It blocks missing, revoked, and version-drifted POLICY/KEY/ROLE/TASK/ORDER/EXPERIENCE rows; treats self BEHAVIOR revision as the accepted COMMIT's post-state witness; preserves revocations over restarts; detects publication replay and forged signatures. The original `FinalW` is **not** silently changed: only the new `GuardedFinalW` enforces this extra guard. Upgrading to this class is necessary in research integrations claiming the local property.

## What is NOT verified

- **39/39 official semantic cases**: 0 complete end-to-end case-level passes; cases are specifications, not executable test code. `conformance_matrix.json` preserves NOT_RUN for full cases, with partial/local evidence levels. The official case list is confirmed from the GitHub repository, but its original full JSON bytes are not embedded in this patch.
- **IND/MED** strict end-to-end state transitions and official schema execution remain open; Phase 2 simplified traces are not official conformance.
- **Full control plane**: real C enrollment / key PoP / signed E-source publishing / revocation / audit evidence must be completed and integrated. In the lab, the C signer is a trusted deterministic fixture, and initial imported current state is a trusted snapshot.
- **True independent RequiredDeps reconstruction at claim**: the new guarded prototype uses an independently validated frozen COMMIT dependency snapshot, which is then compared to C-root signed current rows at claim. A production proof would require a trusted current record store, full coverage of implicit dependencies and range reads, and authenticated C/E update paths.
- **Tool effect correctness, external continuity**: local SQLite ledger snapshots do not establish physical-world effects, distributed crash atomicity, or an independently certified ledger migration. Source/distributed time still rests on simulation assumptions.
- **Schema annotations**: JSON Schema Draft 2020-12 does not automatically enforce `x-zjj-order`; ordering, crypto and cross-record invariants require separate semantic verification.

## Use

```bash
python -m research.phase7.run_phase7
python -m unittest research.phase7.test_guarded_dispatch -v
python -m unittest research.phase7.test_dispatch_gap -v
```

Requires Python 3.10+, `cryptography`, `PyNaCl` (prior reference tests), `jsonschema`. Keep `system_dev/v26/contracts/pay1.schema.json` byte-for-byte unchanged. This phase is additive to the existing research directory.

## Security decision

Until verified control publishing and atomic current-dependency guard are used at ClaimDispatch, do **not** represent the legacy `FinalW` as permitting safe dispatch after policy/role revocation. Treat this as a blocking gap for the protocol's implementation conformance claims, even though the normative protocol calls for the guard. The Phase-7 `GuardedFinalW` is an isolated demonstration of a mitigation under explicit lab assumptions.
