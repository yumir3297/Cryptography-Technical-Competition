# Phase 15 — PAY-1 verifier-only acceptance and reconstructed RequiredDeps

**Status:** experimental PAY-1 proof-of-concept; **0/39 official semantic PASS**, not a deployed payment, authorization, or official conformance certificate. Original `semantic_cases.json` and all three official v2.6 schemas are unmodified.

## The architectural defect we are removing

Prior `DurablePayW.accept(flow, op)` invokes `flow.commit(op)` from inside the SQLite transaction. `SignedPayFlow.commit` uses X's signing private key to create Acceptance and Result. A production W would therefore have to hold or invoke X's signing authority. Tests of durable SQL alone did not demonstrate that C, E, X, and W were independent principals.

Phase15 introduces `VerifierOnlyPayW` with no `SignedPayFlow` or signer instance; it only receives C's trusted Ed25519 public key and the actor public roster. The old `accept()` entrypoint is explicitly rejected.

## Concrete flow

1. A lab *proposer* prepares a complete PAY-1 candidate COMMIT, signed Permit, CommitProof and authorization chain. The proposer is intentionally still a fixture possessing legacy private keys: this is not true separated issuance.
2. C (as another process) publishes signed current `authority` rows, validity windows, and a **signed source corpus** containing POLICY, TASK, ORDER, EXPERIENCE, KEY/ROLE and initial BEHAVIOR records. These C publications can be verified by W using only the pinned root public key.
3. W validates original official PAY schema, original signatures and authority versions. **Crucially**, it reconstructs PAY RequiredDeps from the C-signed source corpus using the existing `required_pay_deps` validator, independently of Permit.deps. It reconstructs the PAY risk decision from C-signed POLICY/TASK/ORDER/EXPERIENCE records using history-int-v2, verifies the original ASSESSMENT and BASIS under the pinned original schemas, and derives mandatory reviews from the computed risk — **not** from the number of submitted Review envelopes. It also binds the task and BASIS source refs, and checks account, behavior, nonce, task and resource witnesses. PREPARE persists a ticket but does not reserve resources yet.
4. X, in a different lab process, signs the exact Acceptance + Result challenge payload. W verifies their signatures, current X KEY/ROLE issuer dependencies, Core/Ref bindings and the entire candidate a second time; it commits account reservation, unique operation/nonce/intent, flight, archive, audit and ticket state under one `BEGIN IMMEDIATE` transaction.
5. The C-certified simulator tool, signed C dispatch/settlement time, PAY guarded dispatch, simulated ToolLedger and single settlement continue to run. A separate read-only auditor checks the persisted COMMIT/Acceptance/Result and separate original tool ledger.

## Negative evidence with practical meaning

- Tampered external Acceptance does **not** cause a partial acceptance.
- C-signed POLICY revocation after W Prepare blocks W Finalize.
- Account changes after Prepare block Finalize rather than reserving against stale funds.
- X signature missing leaves no accepted transaction.
- The same signed Acceptance/Result retry after DB restart returns the frozen historical receipt; no second reservation.
- **Risk-required REVIEW slice:** A legitimate G/U/H-signed chain removes a mandatory ANOMALY review. W independently recomputes the risk from the C-backed history and refuses the omission.\n- **External X grant slice:** A correctly signed Acceptance that omits the X KEY/ROLE dependency list is refused.\n- **CORE-03 PAY slice:** G signs a Permit with its EXPERIENCE dependency removed and H signs an updated proof. These are cryptographically authentic packets, and the malicious COMMIT agrees with the malicious Permit. The independent C source reconstruction rejects with `REQUIRED_DEPS_INCOMPLETE`.

These are scoped experiments: an adversarial signer test does **not** imply the entire official CORE-03 across PAY/IND/MED and every transport/dependency shape has passed.

## Reproduce in GitHub Actions or a clean checkout

```bash
python -m pip install -r requirements_phase13.txt
python -m unittest research.phase15.test_pay_accept -v
python -m research.phase15.process_flow --output research_evidence/phase15_pay_process
python -m research.formal39.run_formal39
# Save unittest stdout/stderr as research_evidence/phase15_pay_test_output.txt
# and formal39 stdout as research_evidence/phase15_formal39_output.txt:
python -m research.phase15.build_report
```

For complete evidence generation without manual log steps, trigger `.github/workflows/phase15-pay.yml` on the existing research branch. It uploads raw logs, the SQLite databases, signed transcripts, a 39-row unchanged-status matrix, a reviewable report, and a candidate ZIP. If successful, it commits these to `research_evidence/` and `research_archives/` (the source-triggered CI ignores evidence-only updates).

## Hard deployment blockers — no claims of production readiness

| Missing boundary | Production-oriented resolution |
|---|---|
| Real C and E custody / enrollment | Separate identities, independently authenticated C publications, rooted key/role certificates, revocation and root rollovers |
| Real X custody | Hardware-backed signer or separately privileged X process; authenticated W-to-X channel, X-side validation and bounded signing policy |
| Prepare-to-Finalize duration | The current lab deliberately requires C-signed `accepted_at=100` at both stages. A real clock inevitably advances, and durable commit may occur after the signed logical acceptance time. Resolve protocol temporal semantics **before** relaxing this check. |
| Distributed consistency | A single transactional W store shared across profiles; durable outbox and tool-side idempotency plus reconciliation for EFFECT_UNKNOWN |
| Real evidence | Replace deterministic fake C/E signatures, simulated assessment history and ToolLedger with authenticated source and physical-effect attestations |
| Complete semantic conformance | Independent full-case comparator for all 39 originals, including transport, unknown time/0-RTT, STATUS/Result, AUD variants, crash model and cross-profile semantics |

**Scope of new evidence:** primarily PAY slices of CORE-01 and CORE-03, with local revision/clock/dispatch evidence. The official case files are untouched, and the formal runner remains **0 PASS / 0 FAIL / 39 BLOCKED_FULL_CONFORMANCE**.
