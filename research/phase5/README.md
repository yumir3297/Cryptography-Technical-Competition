# Phase 5 — PAY-1 signed acceptance with SQLite persistence

**Scope:** ZJJ-CORE-2.6-R2 research *subset*, based on upstream `main` at `0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c`. This module is **not a deployed protocol endpoint**, **not the official 39-case conformance harness**, and **not proof of exactly-once real-world tool effects**.

## Execution

Unzip/merge into the original `Cryptography-Technical-Competition` repository root without overwriting the existing official `system_dev` or `docs` tree. Install Python 3.10+, `cryptography`, `jsonschema`, and `PyNaCl` (prior stages require PyNaCl). From the project root:

```bash
python -m research.phase5.run_phase5

# Official schema mode: requires the exact, unchanged upstream contract file
python -m research.phase5.run_phase5 --upstream-root .
```

The official PAY-1 JSON Schema is expected at `system_dev/v26/contracts/pay1.schema.json` and MUST have Git blob SHA-1 `86ba1bae0e4c455899af661bed44edfc5494aa5e`. A missing file or mismatched blob is **not** silently replaced by a local approximation. In the isolated patch-building runtime the original JSON bytes could not be mounted, so the official schema mode was `NOT_RUN`, not PASS. Once the patch is merged into the pinned original checkout, the second command will run Draft 2020-12 validation on generated signed protocol artifacts or raise on the first schema error.

## What changed

- `durable_w.py`: `BEGIN IMMEDIATE` SQLite transaction with WAL and `synchronous=FULL`, durable per-operation intent/proof/nonce uniqueness, persistent resource reservation and count, exact COMMIT and signed Acceptance/Result archiving, and one-shot dispatch state. Original COMMIT/Acceptance/Result can be reconstructed and re-verified from the database after opening a new connection.
- `crash_worker.py`: **real subprocess termination** with `os._exit(79)` at three boundaries: after validation, after multiple SQL writes but before commit, and after commit but before response.
- `test_durable_w.py`: concurrency with 8 independent SQLite connections; exact signed proof retry vs altered signed proof; wrong operation ID under same intent; archive tamper; hard process termination; dispatch claim no-redelivery; three PAY risk paths; pinned schema mismatch rejects.
- `run_phase5.py`: runs all prior Phase-1–4 unit suites plus the Phase-5 tests, reproduces three signed persistent positive PAY traces, writes scoped machine-readable evidence (`phase5_validation_report.json`, `durable_signed_traces.json`, `phase5_test_log.txt`).

## Local evidence on 2026-10-09

- **200 / 200** combined research unit tests PASS (0 FAIL, 0 ERROR, 0 SKIP).
- **3 / 3** PAY risk outcomes (CLEAR, FLAG, INSUFFICIENT) signed, accepted, stored, recovered and returned idempotently.
- **Three hard-exit boundaries** checked using independent interpreter processes; before COMMIT no partial acceptance remained, after COMMIT an original receipt could be recovered without increasing reservation or acceptance sequence.
- **8 concurrent same-proof submissions:** exactly 1 new ACCEPT and 7 original-receipt replays; 1 resource reservation.
- **Official source JSON Schema validation: NOT_RUN** in this offline bundle. **39 official semantic cases: 0 full PASS**, because there is no official full-conformance runner and trusted C/X/W/E components are incomplete.

## Important limitations and trust boundaries

1. The existing Phase-4 `SignedPayFlow` validates candidate signed protocol messages and produces COMMIT/Acceptance as a **trusted fixture**. The SQLite wrapper serializes and archives this decision. It does not independently implement every original C/E publication, history provenance, controller enrollment, all key-revocation semantics, or real-world W transaction predicates. The code must not be exposed as a service accepting untrusted HTTP inputs.
2. A same-proof duplicate is accepted only after the caller supplies a signed proof that is independently checked against the expected challenge, session, nonce, action context, and registered H key. A raw operation ID is not an authenticated read capability.
3. The `claim(..., witness_ok=True)` mechanism deliberately models a **prevalidated internal claim witness** and is NOT a production authorization input. The hard problem of durable authenticated C and tool trust continuity remains outside this experiment.
4. The SQLite checks demonstrate **local crash rollback and receipt recovery**, not disk power-failure guarantees on every platform, replication safety, broad concurrency across multiple different actions or external tool exactly-once execution.
5. All generated signatures are for deterministic public research fixtures. The fixed keys must never be reused in any actual payment or medical system.
6. The official 39 semantic cases, industrial and medical strict Profiles, and real tool-final effect ledger are future work. All original upstream normative files and JSON contracts remain untouched by this add-on.

## Proposed next work

Run pinned Schema validation after merging into the original checkout; resolve every genuine disagreement between generated PAY objects and machine contracts. Then replace the `witness_ok` claim fixture with current, auditable tool/credential checks, add a persistent TOOL_FINAL/TOOL_TRUST ledger model, and create independent official semantic-case runners with per-case evidence.
