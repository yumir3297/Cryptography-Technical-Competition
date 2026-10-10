# ZJJ-CORE — Competition Edition (work in progress)

This **branch** is an independent competition delivery track started at
`research/zjj-core-phase13-handoff-20261009`, commit
`3633db637c52bb0429c0b61af426d4c7eced5097`.
The research branch, protocol-time study and original 39-case manifest remain
unchanged. Do not merge this branch into `main` as an R2 conformance release.

## Current scope and evidence

| Item | State | Evidence / limitation |
|---|---|---|
| IND-Demo-1 pre-existing Phase18 industrial execution loop | existing scoped PASS, rechecked on competition branch | 25 process stages, Linux DAC role keys, dedicated W/Tool signature, one SQLite simulated effect |
| MED-DEMO-1 / PAY-1 legacy local verifier-only path | existing scoped tests, rechecked | NOT yet using same deployed W, broker custody and tool outbox |
| Signed C clock sequence + durable lower floor | implemented | `competition/core/trusted_clock.py`, bounded interval/replay/rollback/transaction regressions |
| Cross-profile restricted signing broker | partially implemented | IND/MED role bindings, PAY X, profile scopes; PAY H/G/U/V governance not enrolled |
| PREPARE -> X Sign -> FINALIZE with real elapsed time | **BLOCKED** | legacy Phase14 requires identical times; `test_acceptance_gap.py` records this deliberately RED business capability |
| Unified CoreService / three adapters | DESIGNED, NOT implemented | `docs/unified-core-migration.md` |
| Original 39 full official obligations | **0 FULL PASS / 39 BLOCKED** | unchanged original adjudicator; competition tests are not official substitutes |

The new clock adapter is not yet wired into legacy Phase14/15 W acceptance; the protected research clock code is preserved byte-for-byte so its original evidence hashes remain valid.\n\nThe Phase18 lab signer broker remains privileged-runner administered. It
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

Next delivery gate: change acceptance construction to happen under FINALIZE's
current guarded W transaction, invoke external X signer on that frozen final
commit, then atomically accept. Never fix `TIME_CHANGED` by merely deleting it
or backdating the acceptance. See migration contract for exact sequencing.
