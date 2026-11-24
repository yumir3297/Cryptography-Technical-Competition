"""Demo replay: GoalFloor normal/reject/UNKNOWN and cross-profile audit."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TESTS = [
    'competition.tests.test_goal_floor',
    'competition.tests.test_goal_floor_pure',
    'competition.tests.test_cross_goal',
    'competition.tests.test_incident_workflow',
    'competition.tests.test_crash_boundaries',
]


def main():
    for test in TESTS:
        result = subprocess.run([sys.executable, '-m', 'unittest', '-v', test],
                                cwd=str(ROOT), text=True)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    print('DEMO REPLAY PASS')


if __name__ == '__main__':
    main()
