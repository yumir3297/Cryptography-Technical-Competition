# Phase 10 -> Phase 11 changes (research / local integration)

- **Added** `research/phase11/scene_r2.py`: PoP-controlled KEY grants and C publication guard; dynamic implicit scene dependencies; clock-sealed atomic claim, cancel, tool trust rotation and final settlement; durable audit and evidence methods.
- **Added** `research/phase11/pay_r2.py`: strict clock-sealed PAY Claim and Final settlement; signed C time window rows; atomic safe cancellation and no legacy unguarded API bypass.
- **Added** `research/phase11/trusted_clock.py`: signed C interval binding and durable W monotone local sequence. This is NOT external trusted time.
- **Added** `research/phase11/test_phase11.py` and `run_phase11.py`: three-profile signed positive/negative paths, tool-final expiry/re-attestation, rotation, equivocation, non-effect assertions, official Schema checks, transcript exports.
- **Extended** Phase 6 generic ToolLedger and Controller/verify_certificate so profile is explicit; PAY defaults preserve Phase 6 behavior.
- **Extended** Phase 8 fixture factory to allow a strict authority class and PoP bootstrap without changing historical default behavior.
- **Extended** Phase 5 accepted-state enum with a `CANCELLED` terminal state for Phase 11 safe-cancel; original existing states preserved.
- **Extended** Phase 10 official-39 runner/matrix with verified-source-hash Phase11 evidence links and revised remaining obligations for four targeted cases; all 39 official statuses remain fail-closed `BLOCKED_FULL_CONFORMANCE`.
- **Not changed** original upstream Schema files, official 39 manifest, existing official case IDs, or pinned manifest/blob hashes.

No files are silently synchronized to GitHub. This ZIP is the actual delivery; remote repository write/access is a separate step.
