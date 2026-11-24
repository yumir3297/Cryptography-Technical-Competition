"""E2: real CommonW concurrency histories with bulk signed units."""
from __future__ import annotations
import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from competition.evaluation.bulk import bulk_ind_units
from competition.evaluation.experiments.concurrency import _linearizable, _prepared, _race
from competition.evaluation.fixtures import accept
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.wire import ProtocolError

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def _run(mode, capacity):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: capacity}, goal_mode=mode)
    return run, folder


def _goal(run, groups, capacity, required_count, optional_count):
    units = [f'r{i}' for i in range(required_count)] + [f'o{i}' for i in range(optional_count)]
    ops = bulk_ind_units(run, [(unit, f"h-{unit}", f"soc-{unit}") for unit in units])
    required = ops[:required_count]; optional = ops[required_count:]
    if groups == 1:
        rules = ([{'name': f'req-{i}', 'op': op, 'obligation': f'req-{i}', 'cost': 1}
                  for i, op in enumerate(required)] +
                 [{'name': f'opt-{i}', 'op': op, 'obligation': '', 'cost': 1}
                  for i, op in enumerate(optional)])
        publish_goal(run, IND, goal_claim(run, IND, 'g1', rules, capacity=capacity))
    else:
        half = max(1, len(required) // 2)
        first = [{'name': f'req-{i}', 'op': op, 'obligation': f'req-{i}', 'cost': 1}
                 for i, op in enumerate(required[:half])]
        second = ([{'name': f'req-{i}', 'op': op, 'obligation': f'req-{i}', 'cost': 1}
                   for i, op in enumerate(required[half:], start=half)] +
                  [{'name': f'opt-{i}', 'op': op, 'obligation': '', 'cost': 1}
                   for i, op in enumerate(optional)])
        publish_goal(run, IND, goal_claim(run, IND, 'g1', first, capacity=capacity))
        publish_goal(run, IND, goal_claim(run, IND, 'g2', second, capacity=capacity))
    return required, optional


def scenario_optional_last(mode):
    run, folder = _run(mode, 3)
    try:
        required, optional = _goal(run, 1, 3, 2, 4)
        prepared = _prepared(run, optional)
        outcomes = _race(run, prepared)
        ok, detail = _linearizable(run, outcomes, 3)
        return {'scenario': 'optional_last_slot', 'outcomes': outcomes,
                'linearizable': ok, 'detail': detail, 'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def scenario_required_race(mode):
    run, folder = _run(mode, 4)
    try:
        required, optional = _goal(run, 1, 4, 4, 0)
        prepared = _prepared(run, required)
        outcomes = _race(run, prepared)
        ok, detail = _linearizable(run, outcomes, 4)
        return {'scenario': 'required_race', 'outcomes': outcomes,
                'linearizable': ok, 'detail': detail, 'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def scenario_multi_goal(mode):
    run, folder = _run(mode, 5)
    try:
        required, optional = _goal(run, 2, 5, 4, 4)
        prepared = _prepared(run, optional)
        outcomes = _race(run, prepared)
        ok, detail = _linearizable(run, outcomes, 5)
        return {'scenario': 'multi_goal_shared_resource', 'outcomes': outcomes,
                'linearizable': ok, 'detail': detail, 'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def scenario_same_intent(mode):
    run, folder = _run(mode, 1)
    try:
        op = run.fork_operation(IND)
        prepared = _prepared(run, [op] * 4)
        outcomes = _race(run, prepared)
        ids = {o['operation_id'] for o in outcomes}
        return {'scenario': 'same_intent', 'outcomes': outcomes,
                'linearizable': len(ids) == 1 and run.w.counts()['accepts'] == 1,
                'detail': {'distinct_operations': len(ids), 'accepts': run.w.counts()['accepts']},
                'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


SCENARIOS = {
    'optional_last': scenario_optional_last,
    'required_race': scenario_required_race,
    'multi_goal': scenario_multi_goal,
    'same_intent': scenario_same_intent,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--mode', default='enforce')
    parser.add_argument('--output', default=str(RESULTS / 'concurrency-bulk.json'))
    args = parser.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, fn in SCENARIOS.items():
        for index in range(args.repetitions):
            row = fn(args.mode)
            row['repetition'] = index
            rows.append(row)
            print(name, index, row['linearizable'], row['detail'])
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'mode': args.mode, 'histories': len(rows),
              'all_linearizable': all(r['linearizable'] for r in rows),
              'rows': rows}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('histories', len(rows), 'all', report['all_linearizable'])
    return 0 if report['all_linearizable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
