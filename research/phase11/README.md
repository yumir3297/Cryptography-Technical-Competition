# Phase 11: C/E authenticated laboratory execution and trusted-clock R2 W slices

This phase extends the original pinned ZJJ-CORE-2.6-R2 Phase 10 package **without modifying any official original Schema or official 39-case manifest**.

## Reproduce

From the extracted project root (Python 3.10+ with `cryptography` and `jsonschema`):

```bash
python -m unittest research.phase11.test_phase11 -q
python -m research.phase11.run_phase11
python -m research.formal39.run_formal39
```

`research/phase11/phase11_report.json` contains source-file hashes and four signed, replay-generated evidence references. `research/phase11/evidence/*.json` contain original signed messages and/or records, C enrollment PoP, signed control certificates, signed trusted-clock interval inputs, original-schema check declarations, durable W state before/after, tool ledger facts, and audit events.

`research/formal39/formal39_report.json` and `formal39_matrix.csv` include all **39 official IDs**, the latest status and an attached Phase11 evidence path for four targeted cases. The gate hashes the generated Phase11 evidence and its source files before admitting the addendum; stale or modified source causes an error. No automatic promotion to formal PASS is implemented.

## What is actually implemented

- C proof-of-possession enrollment follows `ZJJ-ENROLL-v1` tuple/enrollment-id/nonce/iat/exp signature binding inside the authoritative scene W SQLite database, including one-use nonce and root epoch invalidation for pending certificates.
- Versioned Ed25519 C-controlled KEY_GRANT, ROLE_GRANT, POLICY, TASK, identity and fixed package publication uses the existing signed CAS journal; source E evidence is signed, verified and atomically bound to scene revisions.
- IND/MED W re-derives role/reader/scene/policy/task/credential dependencies independent of the G-signed Permit. Unsupported `EVIDENCE`/`IDENTITY`/`PACKAGE` wire dep namespaces are never emitted; hidden references must still resolve correctly.
- PAY W adds signed-C validity windows per current dependency row. PAY/IND/MED strict adapters reject legacy clockless Claim interfaces. C signs bounded trusted-time assertions and each strict W serializes its clock sequence in the same SQLite claim or settle transaction.
- Before claim, definite current-state revocation or expiry performs atomic safe cancellation **without tool invocation**, freeing reservation and flight while preserving intent and acceptance tombstones. An interval crossing expiry fails closed as unknown and preserves reservation. Accepted scene tombstones remain occupied conservatively after safe cancellation.
- Per-profile `tool-final-v2` references the same immutable tool fact under new attestations. C-signed trust rotation and ledger-origin/head checks, current signer verification, expired-first-proof rejection, same-fact idempotency and signed tool equivocation HALTED have been tested. Separate simulated tool SQLite is queried for immutable fact before first IND/MED settlement.
- Original PAY/IND/MED Git-pinned JSON Schemas validate emitted target records/messages in the runner. Legacy tests continue separately.

## Security limitations and **why official full PASS remains 0/39**

1. In-process C controller, simulated enrollment and C-signed time assertions are **laboratory trust assumptions**, not a remotely authenticated governance service or externally validated interval clock.
2. PAY and IND/MED are separate W adapters with shared strict transaction semantics, **not one deployed authoritative W service**. Legacy classes remain for research, but the Phase11 strict adapters reject legacy dispatch/settle entry points.
3. The durable ToolLedger is an independent *simulator*, not a physical/sandbox-executing trusted tool. No cross-database distributed atomicity or proof of real physical effect is claimed.
4. Original JSON Schema passing is structural; protocol `x-zjj-order` and all official semantic variants, network paths, aud/0-RTT, STATUS/Result and full lifecycle audit are not exhaustively closed.
5. Only CORE-03, CORE-13, AUD-02A and AUD-02B have new Phase11 scoped integration transcripts. Remaining 35 official cases retain Phase 10 witnesses and remain `BLOCKED_FULL_CONFORMANCE` too.
6. Real stable control root rotation, issuer certification lifecycle, genuine C ledger continuity and external auditor attestation need formal engineering and independent adversarial review. Case numbers refer to required semantics, not proof of production-grade conformance.

The `phase11_test_run.txt` / `test_run.txt` count, machine probes and 39-case local tests **must not** be labeled 39 official full passes.
