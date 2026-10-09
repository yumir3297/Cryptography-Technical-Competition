# ZJJ-CORE-2.6-R2 Phase 13 — research archive

Phase 1–12 source/partial evidence preserved, Phase13 process-separated CORE-01 candidate appended. This is **not** a complete protocol implementation, external compliance certificate, deployed service, or proof of physical/clinical tool effect.

Quick reproducibility from unpacked archive root:

```
python -m pip install -r requirements_phase13.txt
python -m unittest research.phase13.test_phase13 -q
python -m research.phase13.process_flow --output /tmp/zjj13_fresh
python -m research.formal39.run_formal39
python -m research.phase13.build_report
```

Results and signed messages: `research/phase13/evidence/core01_process/`. Updated 39-row matrix: `research/phase13/phase13_39case_matrix.csv`. Detailed scope: `research/phase13/README.md` and `research/phase13/phase13_report.json`.

The untouched official semantics, PAY/IND/MED schemas, and unchanged formal 39-case statuses are included. The original manifest is pinned; all 39 cases remain `BLOCKED_FULL_CONFORMANCE`. No remote GitHub push was performed.
