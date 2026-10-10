"""Persist fresh abstract-model evidence. No product or official case execution."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io
import json
import platform
import sys
import unittest

from model import characterize, explore
import test_model


def main():
    base = Path(__file__).resolve().parent
    root = base.parents[1]
    out = base / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_model))
    (out / 'tests.txt').write_text(stream.getvalue(), encoding='utf-8')
    enumeration = explore()
    cases = json.loads((base / 'temporal_cases.json').read_text(encoding='utf-8'))
    original = json.loads((root / 'system_dev/v26/semantic_cases.json').read_text(encoding='utf-8'))
    known = set(unittest.defaultTestLoader.getTestCaseNames(test_model.TimeClosureTests))
    unknown_tests = [name for c in cases['cases'] for name in c['abstract_checks'] if name not in known]
    unknown_ids = sorted({name for c in cases['cases'] for name in c['original_case_ids']} -
                         {c['id'] for c in original['cases']})
    passed = (result.wasSuccessful() and result.testsRun == 27 and not enumeration['violations']
              and not unknown_tests and not unknown_ids
              and len(cases['cases']) == 22 and all(c['status'] == 'NOT_RUN' for c in cases['cases']))
    sources = [base / f for f in ('model.py', 'test_model.py', 'run_all.py', 'README.md', 'temporal_cases.json')]
    sources += [root / p for p in (
        'system_dev/v26/01_core_contract.md', 'system_dev/v26/04_tool_final_recovery.md',
        'system_dev/v26/05_time_acceptance_recovery_PROPOSED.md',
        'system_dev/v26/semantic_cases.json')]
    report = {
        'contract': 'TIME-CLOSURE-PROPOSED-0.1', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'passed': passed, 'model_tests': {'run': result.testsRun, 'failures': len(result.failures),
                                         'errors': len(result.errors), 'skipped': len(result.skipped)},
        'bounded_exploration': enumeration, 'characterization': characterize(),
        'supplemental_protocol_cases': {'total': len(cases['cases']), 'NOT_RUN': len(cases['cases']),
                                       'unknown_test_refs': unknown_tests, 'unknown_original_ids': unknown_ids},
        'official_cases': {'total': len(original['cases']), 'executed_here': 0,
                          'source_status_counts': {s: sum(c['status'] == s for c in original['cases'])
                                                   for s in sorted({c['status'] for c in original['cases']})}},
        'source_sha256': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'environment': {'python': sys.version, 'platform': platform.platform()},
        'limits': [
            'Finite single-operation abstraction, not R2 wire/crypto/schema conformance.',
            'Authentication, current authority, archive validity and ledger continuity are explicit premises.',
            'Atomic durable commit and trustworthy current time are assumed; no database or real clock proved.',
            'No original signatures, network/STATUS/Result/Bundle, fair scheduling, full profiles or physical tools modeled.',
            'Claim/call opportunity collapsed in calls; no claim-to-send window or real settlement modeled.',
            '27 local tests and finite exploration do not promote any of the 22 supplemental or 39 original cases.',
        ],
    }
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': passed, 'tests': result.testsRun, 'states': enumeration['states'],
                      'transitions': enumeration['transitions'], 'violations': len(enumeration['violations']),
                      'results': (out / 'results.json').relative_to(root).as_posix()}, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
