# ZJJ-CORE-2.6-R2 / Phase 8 — IND/MED Signed Scene Authority (Research Slice)

**Date:** 2026-10-09. **Protocol project:** ZJJ safety protocol, not a medical device, payment service, or industrial controller.

This package extends Phases 1–7 with an independently written IND-DEMO-1 / MED-DEMO-1, synthetic-only, signed evidence and authoritative scene-state laboratory. The goal is to turn previously untested industrial/medical assumptions into executable positive and negative experiments, without claiming completed official protocol conformance.

## Implemented and exercised

- **C-authorized publication:** domain-separated Ed25519 certificates for KEY_GRANT, ROLE_GRANT, POLICY, TASK, IDENTITY, and industrial fixed decision PACKAGE; exact scope, record kind, revision CAS, signature validation and transaction journal. Replaying a signed control publication cannot move the revision backwards. C is a deterministic lab trust anchor; enrollment PoP and physical authentication are not implemented.
- **E source authentication:** the normative `Enc(["ZJJ-SOURCE-v1","2.6",profile,kind,scope,data,{issuer,kid,iat,exp}])` signature is verified with current C-certified SOURCE KEY/ROLE. Evidence is bound to a synthetic scene row in a single SQLite transaction; invented refs, wrong issuer, signature tampering, type/profile confusion and 300-second evidence expiry are rejected. A known `INVALID` industrial label, or `UNAVAILABLE` / `INCOMPLETE` medical evidence, is hard F — not grounds to skip review.
- **Policy-specific fixed decisions:** `DEMO_NORMAL→RELEASE`, `DEMO_DEFECT→QUARANTINE`, `DEMO_UNCERTAIN→INSPECT` (requires QUALITY_REVIEW); MED uses only synthetic `DEMO_A/B→DEMO-ORDER-A/B` (requires CLINICAL_REVIEW). Industrial package `ind-fixed-package-1` is an exact C-certified policy-bound fixed combination, not a loadable plugin. MED binds patient, encounter, stable group, exact signed record ref and template.
- **Explicit read rights:** policy reader allowlist AND current C-granted READER scope for H/G/X/U/V as applicable; doctor/reviewer titles alone grant no read access. Role revocation stops preparation or later acceptance/dispatch.
- **Signed protocol interaction:** real Ed25519 Review, Authorization, IssueRequest, Permit, ChallengeRequest, Challenge, CommitProof and Acceptance, independently checked for actual cross-message references, subject, purpose and current grants. The **21-field** industrial/medical COMMIT now includes scene_before/scene_after, behavior witnesses, resource witness, C credential witnesses, frozen action and timed dependency check. COMMIT, signed Acceptance, intention tombstone, resource, flight and state are committed in the **same SQLite transaction**. Receipt refers to the real COMMIT RecordRef, not an experiment placeholder.
- **Concurrency and fail-closed dispatch:** acceptance uses a stable intent uniqueness constraint, frozen evidence dependency revisions, behavior inflight and resource count, with eight concurrent identical CommitProof submissions converging on one acceptance. ClaimDispatch rejects external UNIT/ENCOUNTER changes, role/key revocation, missing own flight and frozen dependency drift; repeated claim does not execute again.
- **Crash injection:** independent Python subprocess termination (`os._exit(73)`) after scene write, after resource write and before archive. On reopening SQLite, no partial state survives; a subsequent valid operation can still commit.

## What is not implemented / not proved

**Critical transparency:** Although the signed scene core is much more complete than Phase 2 fixtures, it still **does not certify any of the original 39 full protocol semantic cases**. `conformance_matrix.json` intentionally leaves `official_full_conformance=NOT_RUN` for all cases. The 54 standalone Phase 8 tests are local, synthetic, selectively scoped experiments; the complete official case includes additional obligations, including typed graph closure, status/Result envelopes, non-self behavior trace proofs, C enrollment PoP, legacy migration, formal reader scopes, genuine tool evidence, and external trust continuity.

1. The two exact upstream **IND/MED JSON Schema files** are not part of this offline patch. We inspected their public GitHub machine contracts and fixed an industrial package identifier/constant mismatch. The `run_phase8.py --upstream-root <your repo root> --require-ind-med-schemas` option requires original unmodified bytes and checks the Git blob SHAs. Absent local files are **NOT_RUN**, never PASS. The exact PAY official Schema remains locally bundled from Phase 7.
2. **C/E proof of enrollment and source physical reality**: deterministically seeded lab actors, not a trustworthy external identity provider or physical sensors. Control signing domain in this particular experiment is `ZJJ-C-CONTROL-LAB-v1`, a local certificate profile, **not** a normative new ZJJ control-message standard. KEY/ROLE records have typed payloads and scoped checks but not the entire enrollment / revocation lifecycle.
3. **No strict full external tool ledger integration** for IND/MED: ClaimDispatch freezes one dispatch attempt but does **not** execute the tool, produce TOOL_FINAL, settle reservations, or confirm real effects. The PAY Phase 6 ledger remains a separate experiment. Unknown outcomes stay reserved; never claim exactly-once physical effects.
4. **No complete transport/result/query specification** or complete required transitive dependency graph (notably C publishing lineage, multi-candidate range witnesses, and independent group identities). Source, controller and W share a single lab SQLite process, not separate trust domains or a distributed crash/replication protocol.
5. **Time discipline:** fixed synthetic times are for reproducible tests; actual trusted time intervals/clock uncertainty and source expiration inheritance require stronger end-to-end checking. Schema's `x-zjj-order` annotations require explicit manual semantic checks beyond Draft 2020-12.
6. **Data privacy:** all patients, events and orders are synthetic, with **no diagnosis or real clinical decision**. AUDITOR redacted detail view not implemented.
7. **No real mathematical cryptographic proof**. Abstract state model exhaustiveness is for the bounded model only.

## Run

Requirements: Python 3.10+, `cryptography`, `jsonschema`; inherited suites also use `PyNaCl`.

```bash
# Only Phase 8 signed scene tests
python -m unittest research.phase8.test_scene_authority -v

# Full prior regressions (Phases 1–7) plus Phase 8
python -m research.phase8.run_phase8

# When you unpack the patch into your original GitHub repo root:
python -m research.phase8.run_phase8 --upstream-root . --require-ind-med-schemas
```

The full combined run outputs `research/phase8/test_log.txt`, `validation_report.json`, `conformance_matrix.json`, and five synthetic signed traces. When the two original schemas are present, it also exercises their actual Draft 2020-12 definitions against emitted records; missing or altered schema files cannot be counted as a passing official-schema result.

## Provenance of official machine contracts

GitHub default-branch contract filenames and their observed blob SHAs as of 2026-10-09:

- `system_dev/v26/contracts/pay1.schema.json`: `86ba1bae0e4c455899af661bed44edfc5494aa5e` (bundled original)
- `system_dev/v26/contracts/industrial.schema.json`: `f937286b1be32b2a8356b991a93770abff430578` (must load from user repo)
- `system_dev/v26/contracts/medical.schema.json`: `5e43b803ed32a3359e4ad2b7e48a3c96f7fd9482` (must load from user repo)

The exact original cases (39 rows) are in upstream `system_dev/v26/semantic_cases.json`, Git blob SHA `b0bc9dbeedac135f6520b5e93729f63686d97bb4` when inspected. No statuses from that original file are changed.
