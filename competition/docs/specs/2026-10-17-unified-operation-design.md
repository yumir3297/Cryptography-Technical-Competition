# ZJJ-CORE unified operation lifecycle

User approved starting experiments after the read-only P2 review. Execute locally, preserve prior work, no remote merge/delete or shared-branch overwrite.

## Requirements

P2: build on PR #3 @ 86f284bf4787e9990b47b8159cd1e6b9e5824b03. One RequestStore, bounded B16 allocation checking app and W. Preserve request-key idempotency and W intent uniqueness, without early intent allocation uniqueness. Freeze all op fields except challenge_request/challenge/proof. Verify original signatures, current source/credentials, DENY coverage, original windows and refreshed final gate on every replacement. Keep ActionHash/Basis/Permit and original issue/authorization/reviews exact. Version replacement and W acceptance serialize in the same database. Never restore an older packet or reuse short-chain IDs/session/nonce/commit-attempt. Accepted operations can only recover original W facts/receipt Core and original tool attempt. Full public wire schemas and signature domains remain unchanged.

IND simplified input stays request_id/unit_id/route; PAY/MED complete Action remain available through existing trusted components, no invented simplified business contract. No private keys or synthetic approvals in application/service code.

P4: implement minimal local HTTP and MCP-over-stdio adapters using an explicit allowlist and existing cryptographic identity, approval and worker proofs; possession of a transport session is not H authority. Public candidate/submit/challenge/accept/status/recovery routes must not expose RequestStore mutation, raw W, arbitrary signer or complete_receipt. Independent participants provide signatures. Local trusted worker owns receipt/dispatch/query/settle, recovery queries the same attempt and never automatically repeats EXEC. Protocol functions without MCP. Strict request/response/error/authentication contracts, disconnect/restart tests; documented role table and sequences. Do not claim production network identity or real-device deployment.

P5: re-read remote SHA/ancestry/diffs for main, dev, competition, PR #3 and experiment branches, classify code/spec/tests/evidence, preserve experiments, document single-writer handoff and integration path. No merge/delete, no automatic main sync; optional new incremental Draft PR only after implementation and verification and only if deliverable warrants it.

Clock: preserve original thresholds, healthy logic, signatures and frozen Core. Capture all natural failures with signed samples, reasons and durable state; distinguish injected negative cases. Diagnose rather than rerun until green. Fix only evidence-backed engineering defects within these constraints; unresolved natural cause remains explicit and blocks full completion.

## Design

Extend app_request in place with version/history metadata, migrate authentic existing rows without allocation backfill. A RequestBoundW subclass uses two internal transaction hooks in CommonW and the same store. Existing CommonW stays internal with its existing semantics. Preserve complete op snapshots for history and idempotent replacement retries; compare-and-swap prevents stale writers. Validate whole replacement then final windows before atomic update. Fresh signatures occur outside database transactions.

Replacements are internal trusted orchestration, not an arbitrary Agent write endpoint. Transport submit requires existing H proof over the full submitted op; all U/V/G/X messages still validated. A dedicated authenticated RequestStore read proof supports preaccept recovery without leaking materials by guessed request keys. Responses distinguish approval pending, submission current, accepted with receipt pending, attempt/effect unknown, and terminal state. The worker uses original worker proofs and remains internal.

## Verification

Run original 159 baseline once, preserve failures. Add real-signature negative and race tests before implementation. Joint final suite over exactly the final code, transport loopback/stdio and process restart/disconnect cases, contract verifier and immutable baseline evidence checks. No summed historical pass count. Export four-part handoff, tested source digests, raw logs, public evidence and patch; exclude runtime private keys/databases.
