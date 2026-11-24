"""One-command quick replay: verify evidence and run the negative verifier."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'competition' / 'evaluation' / 'evidence' / '20261123'


def run(args):
    print('$', ' '.join(args))
    result = subprocess.run(args, cwd=str(ROOT), text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    pairs = [
        ('IND-DEMO-1-package.json', 'anchor-three-profiles.json'),
        ('PAY-1-package.json', 'anchor-three-profiles.json'),
        ('MED-DEMO-1-package.json', 'anchor-three-profiles.json'),
        ('ind-goal-package.json', 'anchor-goal.json'),
    ]
    for package, anchor in pairs:
        run([sys.executable, '-m', 'competition.evaluation.verify',
             str(EVIDENCE / package), str(EVIDENCE / anchor)])
    run([sys.executable, '-m', 'unittest', '-v',
         'competition.tests.test_evidence_verifier'])
    print('QUICK REPLAY PASS')


if __name__ == '__main__':
    main()
