"""Generate the security-incident workflow evidence bundle."""
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

from competition.core.trusted_state import prefix
from competition.evaluation.fixtures import accept, execute_and_settle
from competition.evaluation.incident import (incident_action, install_incident_tool,
                                             publish_incident, set_incident_status)
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import current_goal, goal_claim, publish_goal, update_goal

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parent
REPO = EVAL.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(EVAL / 'evidence' / 'incident-20261123'))
    args = parser.parse_args(argv)
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: 2}, goal_mode='enforce')
    try:
        install_incident_tool(run)
        a_inc = publish_incident(run, incident_id='inc-001', asset='asset-db-01', severity='CRITICAL')
        b_inc = publish_incident(run, incident_id='inc-002', asset='asset-db-02', severity='CRITICAL')
        c_inc = publish_incident(run, incident_id='inc-003', asset='asset-web-03', severity='LOW')
        a = incident_action(run, incident=a_inc, principal='soc-a')
        b = incident_action(run, incident=b_inc, principal='soc-b')
        c = incident_action(run, incident=c_inc, principal='soc-c')
        a = run.fork_operation(IND, a); b = run.fork_operation(IND, b); c = run.fork_operation(IND, c)
        with run.store.db() as db:
            resource = json.loads(db.execute(
                "SELECT key FROM w_resource WHERE profile=? AND key LIKE '%quarantine%'",
                (IND,)).fetchone()[0])
        rules = [{'name': 'contain-db1', 'op': a, 'obligation': 'contain-db1', 'cost': 1},
                 {'name': 'contain-db2', 'op': b, 'obligation': 'contain-db2', 'cost': 1},
                 {'name': 'contain-web3', 'op': c, 'obligation': '', 'cost': 1}]
        ids = ['inc-001', 'inc-002', 'inc-003']
        publish_goal(run, IND, goal_claim(run, IND, 'incident-priority', rules, capacity=2,
                                          resource_key=resource, unit='UNIT', incident_deps=ids))
        # Low-priority containment is rejected by the certified floor.
        try:
            accept(run, IND, c); low = {'accepted': True}
        except Exception as exc:
            low = {'accepted': False, 'code': getattr(exc, 'code', type(exc).__name__)}
        accept(run, IND, a); execute_and_settle(run, IND, a)
        set_incident_status(run, a_inc, 'CONTAINED')
        # Old goal is stale; C re-certifies epoch 2.
        try:
            accept(run, IND, b); stale = {'accepted': True}
        except Exception as exc:
            stale = {'accepted': False, 'code': getattr(exc, 'code', type(exc).__name__)}
        current, revision = current_goal(run, IND, 'incident-priority')
        epoch2 = goal_claim(run, IND, 'incident-priority', rules, capacity=2,
                            resource_key=resource, unit='UNIT', epoch=str(revision + 1),
                            incident_deps=ids)
        update_goal(run, IND, 'incident-priority', epoch2)
        accept(run, IND, b); execute_and_settle(run, IND, b)
        set_incident_status(run, b_inc, 'CONTAINED')
        package = build_package(run, IND, b['action']['operation_id'])
        anchor = build_anchor(run)
        (output / 'anchor-incident.json').write_text(
            json.dumps(anchor, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        (output / 'incident-package.json').write_text(
            json.dumps(package, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        audit = verify_package(package, anchor)
        (output / 'incident-audit.json').write_text(
            json.dumps(audit, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        manifest = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'git_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                                       cwd=str(REPO), text=True).strip(),
                    'python': sys.version, 'platform': platform.platform(),
                    'low_priority': low, 'stale_goal': stale,
                    'audit_status': audit['status'], 'checks': len(audit['checks']),
                    'files': {p.name: sha(p) for p in sorted(output.glob('*.json'))}}
        (output / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        print(json.dumps(manifest, ensure_ascii=False, indent=1))
        return 0 if audit['status'] == 'PASS' else 1
    finally:
        run.close(); folder.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
