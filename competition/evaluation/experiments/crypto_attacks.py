"""Generate the crypto tamper/replay evidence table."""
from __future__ import annotations
import copy
import json
import tempfile
import time
from pathlib import Path

from competition.evaluation.fixtures import accept, execute_and_settle, ind_goal, ind_three_actions
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def _flip(sig):
    return ('A' if sig[0] != 'A' else 'B') + sig[1:]


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: 2}, goal_mode='enforce')
    try:
        ops = ind_three_actions(run)
        ind_goal(run, ops)
        accept(run, IND, ops[0])
        execute_and_settle(run, IND, ops[0])
        package_a = build_package(run, IND, ops[0]['action']['operation_id'])
        anchor = build_anchor(run)
        accept(run, IND, ops[1])
        execute_and_settle(run, IND, ops[1])
        package_b = build_package(run, IND, ops[1]['action']['operation_id'])
    finally:
        run.close(); folder.cleanup()

    mutations = {
        'action_payload': lambda p: p['commit']['value']['action']['payload'].__setitem__('route', 'QUARANTINE'),
        'action_hash': lambda p: p['frozen']['op']['ctx'].__setitem__('action_hash', 'A' * 43),
        'goal_capacity': lambda p: [c['record']['value'].__setitem__('capacity', '3')
                                    for c in p['controls'] if c['namespace'] == 'GOAL'],
        'task_ref': lambda p: p['frozen']['op']['basis']['value'].__setitem__('task_ref', 'B' * 43),
        'resource_capacity': lambda p: p['resource'].__setitem__('capacity', 99),
        'scope': lambda p: p['commit']['scope'].__setitem__('scenario', 'medical'),
        'permit_ref': lambda p: p['commit']['value'].__setitem__('permit_ref', 'C' * 43),
        'acceptance_commit_ref': lambda p: p['acceptance']['body']['payload'].__setitem__('commit_record_ref', 'D' * 43),
        'acceptance_signature': lambda p: p['acceptance'].__setitem__('sig', _flip(p['acceptance']['sig'])),
        'control_signature': lambda p: next(c for c in p['controls'] if c['namespace'] == 'GOAL')['certificate'].__setitem__('signature', _flip(next(c for c in p['controls'] if c['namespace'] == 'GOAL')['certificate']['signature'])),
        'attempt_id': lambda p: p['outbox'].__setitem__('attempt_id', 'E' * 22),
        'final_outcome': lambda p: (p['settlement_evidence']['record']['value'].__setitem__('outcome', 'FAILED_CONFIRMED'),
                                    p['settlement_evidence']['record']['value'].__setitem__('effect_id', ''),
                                    p['settlement_evidence']['record']['value'].__setitem__('no_late_effect', True)),
        'final_fact_id': lambda p: p['settlement'].__setitem__('fact_id', 'F' * 43),
        'replay_acceptance_from_other_operation': lambda p: p.__setitem__('acceptance', copy.deepcopy(package_b['acceptance'])),
        'replay_commit_from_other_operation': lambda p: (p.__setitem__('commit', copy.deepcopy(package_b['commit'])),
                                                         p.__setitem__('commit_ref', package_b['commit_ref'])),
    }
    rows = []
    clean = verify_package(copy.deepcopy(package_a), anchor)
    rows.append({'mutation': 'none', 'status': clean['status'],
                 'failed_checks': [c['check'] for c in clean['checks'] if c['status'] != 'PASS']})
    for name, mutate in mutations.items():
        package = copy.deepcopy(package_a)
        mutate(package)
        result = verify_package(package, anchor)
        rows.append({'mutation': name, 'status': result['status'],
                     'failed_checks': [{'check': c['check'], 'status': c['status'],
                                        'error': c.get('error')}
                                       for c in result['checks'] if c['status'] != 'PASS']})
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'clean_status': clean['status'], 'mutations': rows,
              'all_mutations_rejected': all(r['status'] == 'FAIL' for r in rows if r['mutation'] != 'none')}
    (RESULTS / 'crypto-attacks.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['all_mutations_rejected'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
