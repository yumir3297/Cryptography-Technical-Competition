# ZJJ-CORE-2.6-R2 — Research handoff (2026-10-09)

> **Research-only status checkpoint.** This is not a certification, deployed system, or evidence of an official 39-case PASS.

## Source baseline / delivery boundary

- Canonical upstream repo: `yumir3297/Cryptography-Technical-Competition`, `main` remains unchanged by this checkpoint.
- Latest **verified local source snapshot**: `ZJJ_CORE_2_6_R2_Phase13_Reproducible_20261009.zip`, 248 ZIP entries.
- Archive SHA-256: `f434a0831a983deaa4797482181561c31dcae8bebb851afca7ff55c2e9296c12`.
- **Important:** The archive itself and its 248 entries are **not yet uploaded to GitHub** by this handoff commit. They remain in the current ChatGPT conversation as a downloadable attachment. Do not treat this branch as a complete source mirror.
- The separately named Phase 14 work directory available during this handoff contained only `INSTALL_AND_SCOPE.md`. It did **not** contain persisted or independently verified Phase 14 code modifications. Previous dialogue described work in progress on verifier-only W / external X, which must be implemented again from the Phase 13 baseline or recovered from another verified artifact.

## Research scope and accurate case count

Project: safety-protocol semantics and reproducible crypto/authorization research for the ZJJ-CORE-2.6-R2 contest, not an operational real-world industrial or medical deployment.

Phases 1–13 are included in the local archive. The Phase 13 report recorded:
- 39 / 39 official cases with local evidence and 110 / 110 correlated local tests passing.
- 5 / 5 independent integration probes passing.
- Three-profile CORE-01 process-separated lab candidate for PAY-1, IND-DEMO-1, MED-DEMO-1. Each had one persistent acceptance, dispatch, settlement, restart no-redispatch, and read-only audit; 9 transcript-corruption variants were rejected.
- **Official complete conformance: 0 PASS / 0 proved full FAIL / 39 BLOCKED_FULL_CONFORMANCE.**
- None of the local success counts may be upgraded to official PASS without the entire official scenario, all negative branches, and independently checkable evidence.

The original `system_dev/v26/semantic_cases.json` and three official JSON Schemas must remain immutable. Do not confuse JSON Schema syntax conformance with normative authorization and state-machine semantics.

## Next implementation milestone: Phase 14

**Primary goal:** finish *independently signed C/E/X control and acceptance issuance* without giving W any C, E, or X signing private key.

1. Refactor IND/MED `HardenedSceneW` into a verifier-only W. Existing Phase 13 reference W exposes C private key via `w.controller` and X private key via `w.actors['X'].key`; this is a documented **real trust-boundary gap**, not a passing isolation test.
2. Separate C/E publishing and qualification, G commit, X acceptance signing, and W authoritative acceptance into independently authenticated processes/interfaces. W may hold public keys, never signer private keys.
3. Implement an atomic two-phase/prepare-sign-finalize acceptance, with recomputation and compare-and-swap on every dependent control/resource/time precondition. Verify no unreserved/expired commit can be accepted after external X signs.
4. Preserve signed authority events, replay-resistant registration, versioned qualifications, revocation/rotation semantics, independent RequiredDeps rebuilding, and refusal without side effects. Extend PAY/IND/MED only after shared W assumptions are explicit.
5. Reproduce CORE-01 signed positive and negative transports on all 3 profiles; test forged Acceptance, TOCTOU control revision, lost X response, process crash, retry idempotence, and stale clock interval. Use a read-only external verifier with original official assets.
6. Recompute the full 39-row conformance matrix. Only change a case to `PASS` if *all* normative official obligations are fully tested and evidenced.

## Reproduction (from local Phase 13 archive root)

```bash
python -m pip install -r requirements_phase13.txt
python -m unittest research.phase13.test_phase13 -q
python -m research.phase13.process_flow --output /tmp/zjj13_fresh
python -m research.formal39.run_formal39
python -m research.phase13.build_report
```

Check `research/phase13/README.md`, `research/phase13/phase13_report.json`, `research/phase13/evidence/core01_process/`, `research/phase13/phase13_39case_matrix.csv`, and `research/phase13/DELIVERY_INTEGRITY.json` in the ZIP.

## Trust and remaining blockers

External C/E trust roots, independently pinned audit trust, single deployed cross-profile W, physically/clinically attested tool outcomes, complete transitive RequiredDeps and T/F/U semantics, transport path/aud/scope/0-RTT, STATUS/Result/response bindings, and cross-service error/crash handling are incomplete. Deterministic keys, simulated tool ledger, and laboratory trusted-time prove only the documented lab scope.

## Repository synchronization note

This GitHub branch records the handoff **metadata only**. The Phase 13 source ZIP is available separately in the originating conversation. Future contributors must import the canonical ZIP bytes, verify SHA-256, review content for public-release suitability (including synthetic key fixtures), then commit source under `research/` and official assets under `system_dev/v26/`, without overwriting unrelated existing files. Run full tests and attach execution logs before merging to `main`.
