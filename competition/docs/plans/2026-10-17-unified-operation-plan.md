# Unified Operation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. User requests autonomous experiments; no intermediate permission gates for reversible local implementation.

**Goal:** Resolve P2, P4, P5 and investigate clock failures against one verified integration.
**Architecture:** One V1 RequestStore; transaction-bound current packet checks; explicit proof-authenticated local service adapters.
**Tech Stack:** Python stdlib, SQLite, existing cryptography/jsonschema.
**Spec:** competition/docs/specs/2026-10-17-unified-operation-design.md

## Global Constraints
- Preserve core Action/Schema/hash/signature/DENY/time/EXEC invariants and original evidence.
- No shared remote writes, merge, deletion or old experiment overwrite.
- No synthetic approval/private keys in application or transport code.

## Review Focus
- A->B->A and old-writer replay cannot restore superseded tickets.
- H identity proof for old op cannot authenticate new op.
- DENY publication/credential changes racing replacement must serialize.
- Disconnect after commit is committed/pending, never automatically execute again.
- Missing/mismatched store at service startup fails closed, preaccept read needs H proof.

### Task 1: P2 store, bounded W and renewal
Files: application/request_store.py, operation_orchestrator.py, request_bound_w.py; core/common_w.py (two transaction hooks); tests/test_submission_renewal.py, renewal_fixtures.py.
Interfaces: freeze_approved(key,op); replace_pending(key,op,expected_version,expected_ref); load(key); RequestBoundW(core,requests) retains W API.
- [ ] Run original baseline once; record source and failures.
- [ ] Add real short-chain signing tests: unchanged authorization, expiration then fresh chain, changed frozen fields, bad signature, reused token/history, idempotent retry, two writers, old accept race, DENY race, accepted crash/restart and lost ack.
- [ ] Observe expected red results, implement minimal store migration/CAS/history and two W checks, run targeted tests.
- [ ] Preserve allocation behavior and original 22 tests; commit locally.

### Task 2: P4 explicit service and actual transport
Files: application/operation_service.py, http_service.py, mcp_stdio.py; tests/test_operation_service.py and transport fixtures; docs/final/unified-operation-contract.md.
Interfaces: allowlisted invoke(method,params); public routes carry existing H signatures; recovery challenge/response scoped to current H/Task/request. Runtime injected by trusted startup, never request-selected.
- [ ] Write auth/no-data-leak, allowlist, network dropped response and restart tests; observe red.
- [ ] Implement service, local short-connection HTTP and stdio MCP JSON-RPC adapters; no automatic registration or signer.
- [ ] Exercise IND full lifecycle, all three core profiles retain complete Action compatibility; document exact methods/errors, role table, sequences and worker recovery.
- [ ] Commit only verified code/docs.

### Task 3: Clock investigation
Files: diagnostic test runner and public evidence under integration-evidence; narrowly scoped production change only if root cause proven.
- [ ] Preserve signed samples, durations, receipt reasons, durable W state on failures (including test cleanup).
- [ ] Investigate baseline/natural failures and deterministic reproducer before fixes. Do not modify healthy/thresholds/Core.
- [ ] Run evidence-backed regression; report unresolved causes honestly.

### Task 4: P5 baseline/integration handoff and final verification
Files: docs/final/unified-operation-handoff.md, integration-evidence/remote-state.json, final run logs/source hashes, export package.
- [ ] Fetch read-only remote heads and compare ancestry/files; classify changes and concurrency ownership.
- [ ] Run one final joint suite with final source hashes; required contracts/repository/evidence checks; independent code review when available.
- [ ] Resolve substantive review findings using red/green tests, update final evidence after changes.
- [ ] Export four-point handoff, patch, exact code and real results; leave incomplete requirements explicit, never call goal complete prematurely.
