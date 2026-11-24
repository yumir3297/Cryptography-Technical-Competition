"""E6: accept-path latency with 8 signed units per run, off vs enforce."""
from __future__ import annotations
import json
import statistics
import tempfile
import time
from pathlib import Path

from competition.evaluation.bulk import bulk_ind_units
from competition.evaluation.fixtures import accept
from competition.evaluation.package import build_package
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round((len(values) - 1) * q)))]


def one_run(mode, samples):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: 8}, goal_mode=mode)
    try:
        units = [f'r0'] + [f'o{i}' for i in range(7)]
        ops = bulk_ind_units(run, [(unit, f'perf-{unit}', f'perf-{unit}') for unit in units])
        rules = ([{'name': 'required', 'op': ops[0], 'obligation': 'required', 'cost': 1}] +
                 [{'name': f'opt-{i}', 'op': op, 'obligation': '', 'cost': 1}
                  for i, op in enumerate(ops[1:], start=1)])
        publish_goal(run, IND, goal_claim(run, IND, 'perf', rules, capacity=8))
        # Optional actions are measured first; the required action is last so its
        # PENDING state does not block the samples.
        order = ops[1:] + [ops[0]]
        for op in order:
            ticket = run.w.prepare(IND, op, run.identity_proof(IND, op))
            proof = run.accept_proof(IND, ticket['ticket_id'])
            start = time.perf_counter_ns()
            run.w.accept(IND, ticket['ticket_id'], proof)
            samples.append(time.perf_counter_ns() - start)
            oid = op['action']['operation_id']
            run.w.claim(IND, oid, run.worker_proof(IND, oid, 'CLAIM'))
            response = run.w.execute_once(IND, oid, run.worker_proof(IND, oid, 'EXECUTE'))
            run.w.settle(IND, oid, response, run.worker_proof(IND, oid, 'SETTLE'))
        package = build_package(run, IND, ops[0]['action']['operation_id'])
        return len(json.dumps(package).encode('utf-8'))
    finally:
        run.close(); folder.cleanup()


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'note': '8 samples per run; cold/warm mixed; exploratory tail.'}
    for mode in ('off', 'enforce'):
        samples = []
        sizes = []
        for _ in range(5):
            sizes.append(one_run(mode, samples))
        report[mode] = {'n': len(samples), 'p50_ns': pct(samples, 0.5),
                        'p95_ns': pct(samples, 0.95), 'p99_ns': pct(samples, 0.99),
                        'mean_ns': int(statistics.mean(samples)),
                        'min_ns': min(samples), 'max_ns': max(samples),
                        'package_bytes': sizes}
        print(mode, report[mode])
    (RESULTS / 'performance-bulk.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written')


if __name__ == '__main__':
    main()
