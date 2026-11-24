"""Run the three crash-boundary tests and record a machine-readable result."""
import json
import subprocess
import sys
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'
TESTS = [
    'competition.tests.test_crash_boundaries.CrashBoundaryTests.test_accept_commit_crash_leaves_one_committed_operation_and_pending_receipt',
    'competition.tests.test_crash_boundaries.CrashBoundaryTests.test_exec_marker_crash_uses_one_execution_qualification_and_does_not_call_tool',
    'competition.tests.test_crash_boundaries.CrashBoundaryTests.test_settlement_commit_crash_is_recovered_without_a_second_settlement',
]


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for test in TESTS:
        start = time.time()
        result = subprocess.run([sys.executable, '-m', 'unittest', '-v', test],
                                cwd=str(REPO), capture_output=True, text=True, timeout=300)
        rows.append({'test': test.rsplit('.', 1)[-1], 'returncode': result.returncode,
                     'passed': result.returncode == 0,
                     'seconds': round(time.time() - start, 3),
                     'tail': (result.stderr or result.stdout or '').strip().splitlines()[-6:]})
        print(rows[-1])
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'tests': rows, 'all_pass': all(r['passed'] for r in rows)}
    (RESULTS / 'crash-recovery.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('all_pass', report['all_pass'])
    return 0 if report['all_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
