# Resolver V1 verification evidence, 2026-10-17

This directory is new. Historical evidence directories and all baseline tracked bytes are preserved.

- `full-regression-release.log`: final branch-source regression. Use this result rather than earlier runs.
- `tested-source-sha256.json`: SHA-256 of the application and test sources in that final run.
- Earlier red, review, intermediate regression and targeted green logs are retained verbatim, including failures.
- `generated-*.json`: newly generated verifier reports saved separately; these do not replace historical reports.
- `original-files-integrity.json`: byte comparison against all 350 baseline tracked files.
- `verification-report-preservation.json`: restoration checks for verifier-generated historical paths.
- `repository-check.json`: final scope/import/link and original evidence checks.
- `review-notes.md`: independent read-only review findings and corrections.
- `manifest.json`: integrity inventory for this evidence directory (excluding itself).

Exact environment, commands, results and limitations: [results](../../docs/final/trusted-action-resolver-v1-results.md). Design, sources and impacts: [maintenance](../../docs/final/trusted-action-resolver-v1.md).

These are scoped software tests using simulated tools and test participants. They are not universal protocol proofs, production authentication evidence or real-device measurements. Historical verifier results are historical package consistency checks.
