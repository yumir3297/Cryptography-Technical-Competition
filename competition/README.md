# ZJJ-CORE — Competition Edition (work in progress)

> **先读交付定义**：[`../00_COMPETITION_FINAL_DELIVERY_SPEC.md`](../00_COMPETITION_FINAL_DELIVERY_SPEC.md) — 最终效果、P0/P1/P2 修复、竞赛验收矩阵和本地端逐项对齐表。

This **branch** is an independent competition delivery track started at
`research/zjj-core-phase13-handoff-20261009`, commit
`3633db637c52bb0429c0b61af426d4c7eced5097`.
The research branch, protocol-time study and original 39-case manifest remain
unchanged. Do not merge this branch into `main` as an R2 conformance release.

## Current scope and evidence

Local update 2026-10-11: the common A authorization path and fixed PAY roster are
implemented in `core/authorization.py`, `core/trusted_state.py` and
`core/signer_broker.py`; IND actual prepare/accept shares its DENY transaction.
See [authorization-contract.md](docs/authorization-contract.md). PR3 adds the
three-Profile `core/common_w.py` transaction and separate signed simulator
ledgers; see [w-transaction-contract.md](docs/w-transaction-contract.md).
Common guard T remains an authorization fact; only CommonW creates COMMIT.
The historical rows below identify the original experiments.

| Item | State | Evidence / limitation |
|---|---|---|
| IND-Demo-1 pre-existing Phase18 industrial execution loop | existing scoped PASS, rechecked on competition branch | 25 process stages, Linux DAC role keys, dedicated W/Tool signature, one SQLite simulated effect |
| MED-DEMO-1 Phase18 clinical reviewer + execution candidate | 26-step scoped PASS on competition branch | reuses role broker, W acceptance, signed gateway and single simulated tool fact; still fixed lab times |
| PAY-1 legacy local verifier-only path | existing scoped regression only | NOT yet migrated to unified W, role broker custody or common outbox |
| Signed C clock sequence + durable lower floor | implemented | `competition/core/trusted_clock.py`, bounded interval/replay/rollback/transaction regressions |
| Cross-profile competition signing broker | implemented scoped | Fresh actual PoP/C enrollment, PAY H/G/X/U/V, complete role/purpose/scope/business filtering; Windows same-user bootstrap remains trusted, Linux DAC not proven in this run |
| PREPARE -> X Sign -> FINALIZE with real elapsed time | **BLOCKED** | legacy Phase14 requires identical times; `test_acceptance_gap.py` records this deliberately RED business capability |
| Shared authorization guard / three derivation adapters | implemented scoped; full CoreService pending | Common current identity/signatures/Review/DENY/Deps/source/ACL; actual IND acceptance connected, MED/PAY resource/dispatch/settle future |
| Original 39 full official obligations | **0 FULL PASS / 39 BLOCKED** | unchanged original adjudicator; competition tests are not official substitutes |

The new clock adapter is not yet wired into legacy Phase14/15 W acceptance; the protected research clock code is preserved byte-for-byte so its original evidence hashes remain valid.

The Phase18 lab signer broker remains privileged-runner administered. It
restricts domain, profile, role and key but does **not** independently approve
business operations; the current `C` clock is a lab-signed oracle, not a
demonstrated wall-clock attestation. Tool effects are simulated, not physical,
medical, or financial. No key material from `/tmp` may be uploaded.

## Reproduce the first patch

```bash
python -m pip install -r requirements_phase13.txt
python -m unittest discover -s competition/tests -v
python -m unittest research.phase14.test_phase14 research.phase15.test_pay_accept -v
python -m research.formal39.run_formal39
# Isolated disposable Ubuntu machine with passwordless sudo only:
python -m research.phase18.process_flow --output /tmp/zjj_comp_ind
PHASE18_LAB_PATH=/tmp/zjj_comp_ind python -m unittest research.phase18.test_isolated_signers -v
```

GitHub Actions: `.github/workflows/competition-security-baseline.yml`.
The known-gap test succeeds when the legacy path **rejects** an elapsed-time
acceptance; that test is NOT evidence that elapsed-time acceptance works.

Current local P-01–P-03 slice: `competition/core/acceptance.py` now performs
R2 durable W acceptance before X signs the original committed Core. It uses a
real advancing host-clock Provider, current event/window/identity checks and
frozen receipt recovery. That historical class covers IND acceptance/receipt
and still blocks claim; new CommonW implements the PR3 three-profile path. The legacy
TIME_CHANGED test remains a known-gap detector for unchanged research code.
See [acceptance sequence](docs/acceptance-sequence.md) and run:

```text
python -m competition.run_time_slice --output competition/evidence/time-slice-20261010-final
```

The Windows run does not prove Linux DAC isolation or external time trust.
