# Trusted Action Resolver V1 implementation plan

> For agentic workers: execute inline with superpowers:executing-plans, then independent whole-branch review.

Goal: expose a minimal IND proposal-to-Action application library without changing the security core.
Architecture: data-only parser; public-state resolver; W-controlled transactional request/outbox store; orchestrator receiving already signed approvals. No participant keys or automatic approvals in application modules.
Tech stack: existing Python, SQLite, cryptography/jsonschema dependencies.
Spec: approved four-part delivery and six-field requirements; detailed contract in trusted-action-resolver-v1.md.

## Constraints

- Base competition/zjj-core-final-20261010 at cc4e36b4e302fcdc53cc809a012c77d8464182af.
- Add only application code, tests and new documentation/evidence; no original core/Schema/evidence changes.
- Preserve complete Action, ActionHash, existing message signature domains, COMMIT and EXEC-0.
- IND only; PAY/MED and DelegationProof explicitly unsupported by the new proposal entry.
- Retain old full-Action ingress; never expose test signing helpers as application capability.

## Tasks

- [x] Write tests for strict proposals, source bindings, authority revocation, immutable mapping/outbox and real W flow; observe missing application implementation.
- [x] Implement candidate_proposal.py, request_store.py, trusted_action_resolver.py, operation_orchestrator.py. Resolver returns unsigned approval material; only authentic signed chains can first-freeze through the orchestrator.
- [x] Run focused tests and complete regression, review independently, record exact commands/results and publish feature branch plus draft PR against competition branch.

## Review focus

Cached retry current ACL; immutable full request and canonical request_ref; no implicit signer/worker capability; malformed approved op cannot poison first freeze; authentic same-Action re-sign conflict; committed-operation recovery must not recheck mutable READY genesis as a new operation.

Ruling: use the existing isolated clone and a new feature branch rather than moving the desktop project mirror; user authorized this isolation and publication. No merge is authorized.
Ruling: application proposal authentication gets its own ZJJ-APP-PROPOSAL-v1 domain; all existing protocol domains remain byte-for-byte unchanged. This is a new application envelope, not a core protocol change.
