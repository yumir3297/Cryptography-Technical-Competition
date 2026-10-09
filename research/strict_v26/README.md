# Strict PAY v2.6 selected-clause research slice

## Run

From the repository root after adding this `research/` directory:

```shell
python -m pip install cryptography jsonschema
python -m research.strict_v26.run_phase3
python -m unittest research.strict_v26.test_pay_history research.strict_v26.test_pay_dependencies research.strict_v26.test_upstream_schema -v
```

This package builds on `research/reference_executor` (phase2) and `research/assurance` (phase1). Main deliverable: [`PHASE3_PROGRESS.md`](PHASE3_PROGRESS.md).

**Do not use this test harness to authorize a real-world transaction.** Identity secrets are deterministic public test seeds, C/ W authentication witnesses are modeled inputs, and only some clauses of the payment Profile are checked. The program must NOT be represented as a complete implementation of ZJJ-CORE-2.6-R2, nor is any upstream semantic case marked fully passed.

When this directory is overlaid onto the upstream repository with its `system_dev/v26/contracts/pay1.schema.json`, the schema adapter runs against the real file, reporting actual PASS or FAIL for each example. If absent, the status is SKIPPED rather than fabricated. See `official_schema_probes.json`.
