# Phase 12 — durable recovery / ledger-present settlement / C-clocked cancel–claim races

ZJJ-CORE-2.6-R2 research-only hardening atop the exact Phase11 baseline. **0/39 official full PASS**. Tests and traces below are *scoped local facets*. The original 39 official cases and all three upstream JSON Schemas are unchanged.

## Changes and why

- `authority.py`: `HardenedPayW` requires an injected independent durable `ToolLedger` and, **inside the existing W SQLite settlement transaction**, verifies the tool-ledger origin, ledger ID, dispatch attempt and exact immutable FinalFact *before* first settlement. Lost/missing original fact or mismatched ledger fails closed and preserves account reservations. Historical already-committed original proofs retain the existing idempotent path. Older `StrictPayW` is kept as a baseline for reproducible differential testing, not selected in Phase12 strict usage.
- `HardenedSceneW` plus `HardenedPayW` implement identical **laboratory-only** explicit C-signed `CANCEL` semantics. The C interval proof binds Profile, scope, operation ID, purpose, monotone sequence, and time interval. The `BEGIN IMMEDIATE` claim/cancel race has exactly one winner; after `EFFECT_UNKNOWN`, cancellation returns `TOO_LATE` and never releases escrow. There is no claim of an official on-wire cancellation envelope or transport certificate.
- `crash_worker.py` runs in an **independent local subprocess**. It commits W's claim and calls `os._exit(79)` before creating a tool fact; W is then reopened. Recovery preserves `EFFECT_UNKNOWN`, and a different attempt cannot re-dispatch.
- `run_phase12.py` exports the **actual signed input envelopes**, C control certificates, immutable tool facts, three-Profile W state snapshots, durable events, crash return code, allowed/blocked transitions, and negative evidence. No artificial PASS promotion.
- `PAY_LEGACY_AUD02C_GAP.json` independently demonstrates why this change was needed: the earlier PAY strict implementation could settle a validly signed ToolFinal even after the independent original tool fact had been deleted. The new adapter refuses until the same original fact is restored.

## Reproduce (from extracted project root)

Requires Python >=3.10, `cryptography`, `jsonschema`.

```bash
python -m unittest research.phase12.test_phase12 -q
python -m research.phase12.run_phase12
python -m research.formal39.run_formal39
```

- 7 Phase12 `unittest` methods, covering multiple scenarios, with test logs in `research/phase12/test_run.txt`.
- Two new official case IDs (`CORE-15`, `AUD-02C`) × 3 Profile transcripts = 6 signed local facets, stored in `research/phase12/evidence/`.
- Phase12 case source SHA-256 and evidence SHA-256 are in `research/phase12/phase12_report.json`. The 39-case runner enforces both before attaching references to the official matrix.
- Existing Phase5/6/7/8/11 modules and Phase12 were run **separately**, with the actual module-level logs and observed totals preserved. The all-in-one command timed out: it is not counted as passing. See `research/phase12/module_regression_summary.json`.

## Remaining formal blockers

The C private key, enrollment/root management and signed clock remain local fixtures, **not independently operated externally governed C/E services**. PAY and IND/MED share a strict behavioral interface but **do not share one deployed W instance or datastore**. The tool ledger is local SQLite simulated execution, not independently attested physical effects. Full aud/scope/path network transport, replay/0-RTT, STATUS/Result, and real cross-process dispatch delivery/acknowledgment are not covered. JSON Schema checks are structural, not exhaustive x-zjj-order and semantic validation. An explicit locally signed cancel is an experimental interface, not proof of an official transport command.
