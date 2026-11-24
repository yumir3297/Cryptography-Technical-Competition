"""Measured overhead: pure GoalFloor check and one real accept/execute path."""
from __future__ import annotations
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from competition.core.goal_floor import action_selector, evaluate, goal_ref
from competition.evaluation.fixtures import accept, ind_goal, ind_three_actions
from competition.profiles.w_seed import initialize

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    index = min(len(values) - 1, int(round((len(values) - 1) * q)))
    return values[index]


def summary(values):
    return {'n': len(values), 'p50_ns': pct(values, 0.50), 'p95_ns': pct(values, 0.95),
            'p99_ns': pct(values, 0.99), 'mean_ns': int(statistics.mean(values)),
            'min_ns': min(values), 'max_ns': max(values)}


def bench_pure(count=20000):
    resource = ['lab', 'tenant-1', 'industrial', 'route-capacity', 'demo-line-a',
                'ind-inspection-bay', 'unit']
    selector = action_selector(IND, {
        'scope': {'domain': 'lab', 'tenant': 'tenant-1', 'scenario': 'industrial'},
        'operation_id': 'A' * 22, 'principal': 'p', 'holder': 'h',
        'holder_kid': 'k' * 43, 'executor': 'x', 'tool': 't', 'tool_version': '1',
        'destination': 'd', 'payload': {'route': 'INSPECT'}})
    claim = {'model': 'goal-floor-v1', 'group': 'bench', 'epoch': '1',
             'resource_key': resource, 'unit': 'UNIT', 'capacity': '8',
             'deps': [{'namespace': 'POLICY', 'key': resource[:3],
                       'revision': '1', 'ref': 'p' * 43}],
             'actions': [{'name': 'required-a', 'profile': IND, 'action_digest': selector,
                          'obligation': 'a', 'cost': '1'},
                         {'name': 'required-b', 'profile': IND, 'action_digest': 'b' * 43,
                          'obligation': 'b', 'cost': '1'}]}
    goal = {'ref': goal_ref(IND, claim), 'claim': claim}
    times = []
    for _ in range(count):
        start = time.perf_counter_ns()
        evaluate(IND, [goal], {}, capacity=8, spent=0, reserved=0,
                 candidate={'cost': 1, 'resource_key': resource, 'unit': 'UNIT',
                            'selector': selector})
        times.append(time.perf_counter_ns() - start)
    return summary(times)


def bench_accept(mode, samples=5):
    times = []
    for _ in range(samples):
        folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
        run = initialize(Path(folder.name), goal_mode=mode)
        try:
            op = run.fork_operation(IND)
            ticket = run.w.prepare(IND, op, run.identity_proof(IND, op))
            proof = run.accept_proof(IND, ticket['ticket_id'])
            start = time.perf_counter_ns()
            run.w.accept(IND, ticket['ticket_id'], proof)
            times.append(time.perf_counter_ns() - start)
        finally:
            run.close(); folder.cleanup()
    return summary(times)


def bench_lifecycle(mode):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), goal_mode=mode)
    try:
        op = run.fork_operation(IND)
        accept(run, IND, op)
        oid = op['action']['operation_id']
        start = time.perf_counter_ns()
        run.w.claim(IND, oid, run.worker_proof(IND, oid, 'CLAIM'))
        claim_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        response = run.w.execute_once(IND, oid, run.worker_proof(IND, oid, 'EXECUTE'))
        execute_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        run.w.settle(IND, oid, response, run.worker_proof(IND, oid, 'SETTLE'))
        settle_ns = time.perf_counter_ns() - start
        return {'claim_ns': claim_ns, 'execute_ns': execute_ns, 'settle_ns': settle_ns}
    finally:
        run.close(); folder.cleanup()


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'python': sys.version, 'platform': platform.platform(),
              'pure_goal_floor': bench_pure()}
    for mode in ('off', 'enforce'):
        report['accept_' + mode] = bench_accept(mode)
        report['lifecycle_' + mode] = bench_lifecycle(mode)
    report['note'] = ('Single-host simulator; execute includes a real subprocess and '
                      'signed tool SQLite transaction, not production hardware.')
    Path(RESULTS / 'performance.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
