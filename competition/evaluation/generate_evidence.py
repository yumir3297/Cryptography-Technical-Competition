"""Generate the public evidence bundle used by the judge replay.

Usage:
  python -m competition.evaluation.generate_evidence --output competition/evaluation/evidence/20261123

The output contains only public keys, signed records and simulator ledgers.  No
private key or writable database is copied.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from competition.evaluation.fixtures import accept, execute_and_settle, ind_goal, ind_three_actions
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parent
REPO = EVAL.parents[1]


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_sha():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(REPO),
                                       text=True).strip()
    except Exception:
        return 'UNKNOWN'


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True),
                    encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(EVAL / 'evidence' / '20261123'))
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'git_sha': _git_sha(), 'python': sys.version, 'platform': platform.platform(),
                'command': 'python -m competition.evaluation.generate_evidence',
                'packages': {}}

    # One run, three profiles, all settled.
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), goal_mode='off')
    try:
        anchor = build_anchor(run)
        _write(output / 'anchor-three-profiles.json', anchor)
        for profile, op in run.operations.items():
            accept(run, profile, op)
            execute_and_settle(run, profile, op)
            package = build_package(run, profile, op['action']['operation_id'])
            path = output / (profile + '-package.json')
            _write(path, package)
            audit = verify_package(package, anchor)
            _write(output / (profile + '-audit.json'), audit)
            manifest['packages'][profile] = {'package': path.name,
                                             'sha256': _sha256(path),
                                             'audit_status': audit['status'],
                                             'checks': len(audit['checks'])}
    finally:
        run.close(); folder.cleanup()

    # One GoalFloor-enforced IND run.
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: 2}, goal_mode='enforce')
    try:
        ops = ind_three_actions(run)
        ind_goal(run, ops)
        accept(run, IND, ops[0])
        execute_and_settle(run, IND, ops[0])
        package = build_package(run, IND, ops[0]['action']['operation_id'])
        anchor = build_anchor(run)
        _write(output / 'anchor-goal.json', anchor)
        _write(output / 'ind-goal-package.json', package)
        audit = verify_package(package, anchor)
        _write(output / 'ind-goal-audit.json', audit)
        manifest['packages']['IND-DEMO-1-goal'] = {
            'package': 'ind-goal-package.json', 'sha256': _sha256(output / 'ind-goal-package.json'),
            'audit_status': audit['status'], 'checks': len(audit['checks'])}
    finally:
        run.close(); folder.cleanup()

    manifest['files'] = {path.name: _sha256(path) for path in sorted(output.glob('*.json'))}
    _write(output / 'manifest.json', manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
