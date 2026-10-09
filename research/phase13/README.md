# Phase 13: CORE-01 process-separated integration candidate

**Status:** `PASS_PROCESS_SEPARATED_LAB_CANDIDATE` in three fixed profiles; **official complete PASS: 0/39**.

## Why this is an improvement

The official CORE-01 scenario is `合法完整链，全部守卫T`; expected `唯一ACCEPTED，原COMMIT/Core/Ref一致`. This phase adds a single persistent positive chain for each profile with six distinct Python processes: (1) C/E fixture publication, signing, acceptance and reservation; (2) signed C-clocked claim; (3) separate persisted simulated tool finalization; (4) signed TOOL_FINAL settlement; (5) no redispatch after restart; (6) **read-only** independent audit of signed objects and persisted W and tool-ledger database rows. The auditor is not an alternate W instance. It checks original signed messages, upstream Draft-2020-12 schemas, matching COMMIT/Acceptance refs, correct tool certificate/TOOL_FINAL signature and immutable ledger fact, and unique accepted/dispatch/settled rows. Three distinct deliberately corrupted transcript variants per profile must fail the auditor.

`phase13_process_report.json` and `PAY-1/`, `IND-DEMO-1/`, `MED-DEMO-1/` directories include signed messages, actual snapshots, fact, certificates, both SQLite DBs and audit results. All proof files are synthetic; the W and tool databases are separate.

## Reproduce from archive root

```sh
python -m pip install -r requirements_phase13.txt
# A truly fresh, distinct output directory is preferable to reusing the included evidence:
python -m research.phase13.process_flow --output /tmp/zjj_phase13_new_run
# Independently check the included witness and all 9 tampering variants:
python -m unittest research.phase13.test_phase13 -q
# Re-run the full 39-case partial dispatch (does not award official PASS):
python -m research.formal39.run_formal39
# Update Phase13 derived 39-case matrix/report after the formal dispatcher:
python -m research.phase13.build_report
```

To inspect an included witness without touching W or using its signing material:

```sh
python -m research.phase13.process_flow --child audit --dir research/phase13/evidence/core01_process/PAY-1
```

**Important limits:** All identities, controllers and trusted times are laboratory fixtures. In IND/MED, the reference W constructor itself has access to C and X private signing keys; separate invocations do *not* prove custody isolation. The auditor's root of trust is transcript supplied rather than pinned to an external trust service. It does not prove a physical tool effect or clinical order. Each profile uses a separate SQLite W, not a shared deployed cross-profile W; full recursive RequiredDeps, transport (path/0-RTT/aud), STATUS, Result and cross-service failure handling are not fully covered. These remain strict blockers for official CORE-01 complete PASS.

The bundled original `system_dev/v26` manifest and three schemas are unchanged. The 39 official statuses remain `0 PASS, 0 complete FAIL, 39 BLOCKED_FULL_CONFORMANCE`. A passing Phase13 test is **not** a PASS under the original 39-case contract.
