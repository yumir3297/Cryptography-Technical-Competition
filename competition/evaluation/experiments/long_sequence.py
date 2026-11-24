"""E1: long-sequence Agent decision differential experiment.

A fixed external action sequence is replayed against the original CommonW
(goal_mode=off) and the GoalFloor-enforced CommonW.  The independent Oracle is
implemented here and never calls competition.core.goal_floor.evaluate.
"""
from __future__ import annotations
import argparse
import json
import random
import tempfile
import time
from pathlib import Path

from competition.evaluation.bulk import bulk_ind_units
from competition.evaluation.fixtures import accept
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.wire import ProtocolError
from competition.tools.common_tool import ToolGateway

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'
COUNTER = EVAL / 'counterexamples'


class Oracle:
    """Independent arithmetic/status model for the fixed sequence."""
    def __init__(self, capacity, required, optional, *, enforce, costs=None):
        self.capacity = capacity
        self.required = ([f'r{i}' for i in range(required)]
                         if isinstance(required, int) else list(required))
        self.optional = optional
        self.enforce = enforce
        self.costs = costs or {}
        self.spent = 0
        self.reserved = 0
        self.status = {name: 'OPEN' for name in self.required}

    def cost_of(self, kind, index):
        return int(self.costs.get(f'{kind}{index}', 1))

    def accept(self, kind, index):
        obligation = f'r{index}' if kind == 'R' else ''
        cost = self.cost_of(kind, index)
        if self.enforce:
            if any(state == 'PENDING' for state in self.status.values()):
                return False, 'GOAL_PENDING_UNKNOWN'
            if any(state == 'BLOCKED' for state in self.status.values()):
                return False, 'GOAL_BLOCKED'
            if obligation and self.status[obligation] != 'OPEN':
                return False, 'GOAL_ALREADY_COMMITTED'
            remaining = sum(self.cost_of('R', int(name[1:])) for name, state in self.status.items()
                            if state == 'OPEN' and name != obligation)
            if self.spent + self.reserved + cost + remaining > self.capacity:
                return False, 'GOAL_CAPACITY_FLOOR'
        elif self.spent + self.reserved + cost > self.capacity:
            return False, 'RESOURCE_EXHAUSTED'
        self.reserved += cost
        if obligation:
            self.status[obligation] = 'PENDING'
        return True, ''

    def settle(self, kind, index, outcome='SUCCEEDED'):
        obligation = f'r{index}' if kind == 'R' else ''
        cost = self.cost_of(kind, index)
        if outcome == 'UNKNOWN':
            return
        self.reserved -= cost
        if outcome == 'SUCCEEDED':
            self.spent += cost
            if obligation:
                self.status[obligation] = 'DONE'
        else:
            if obligation:
                self.status[obligation] = 'BLOCKED'


def _tool_flag(run, **flags):
    path = Path(run.tools[IND]['config_path'])
    config = json.loads(path.read_text(encoding='utf-8')); config.update(flags)
    path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    run.tool_gateways[IND] = ToolGateway(path)


def _make_run(mode, spec):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: spec['capacity']}, goal_mode=mode)
    units = [f"r{i}" for i in range(spec['required'])] + [f"o{i}" for i in range(spec['optional'])]
    ops = bulk_ind_units(run, [(unit, f"inc-{unit}", f"soc-{unit}") for unit in units])
    required_ops = ops[:spec['required']]
    optional_ops = ops[spec['required']:]
    rules = ([{'name': f'req-{i}', 'op': op, 'obligation': f'r{i}', 'cost': 1}
              for i, op in enumerate(required_ops)] +
             [{'name': f'opt-{i}', 'op': op, 'obligation': '', 'cost': 1}
              for i, op in enumerate(optional_ops)])
    if spec.get('multi_goal'):
        half = max(1, len(required_ops) // 2)
        first = [rule for rule in rules if rule['obligation'] in
                 {f'r{i}' for i in range(half)}]
        second = [rule for rule in rules if rule not in first]
        publish_goal(run, IND, goal_claim(run, IND, 'g1', first, capacity=spec['capacity']))
        publish_goal(run, IND, goal_claim(run, IND, 'g2', second, capacity=spec['capacity']))
    else:
        publish_goal(run, IND, goal_claim(run, IND, 'g1', rules, capacity=spec['capacity']))
    return run, folder, required_ops, optional_ops


def _result(run, op):
    with run.store.db() as c:
        row = c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',
                        (IND, op['action']['operation_id'])).fetchone()
        if row is None:
            return None
        frozen = json.loads(row['frozen'])
        witness = frozen['commit']['value'].get('goal')
        resource = c.execute('SELECT reserved,spent,capacity FROM w_resource WHERE profile=?',
                             (IND,)).fetchone()
        return {'commit_ref': frozen['commit_ref'], 'goal': witness,
                'reserved': resource[0], 'spent': resource[1], 'capacity': resource[2]}


def run_sequence(mode, spec, order, *, capture_position=None):
    run, folder, required_ops, optional_ops = _make_run(mode, spec)
    oracle = Oracle(spec['capacity'], spec['required'], spec['optional'],
                    enforce=(mode == 'enforce'), costs=spec.get('costs'))
    trace = []
    counters = {'accepted': 0, 'rejected': 0, 'mismatch': 0, 'unknown': 0}
    try:
        for position, token in enumerate(order):
            kind, index = token[0], int(token[1:])
            op = required_ops[index] if kind == 'R' else optional_ops[index]
            expected_ok, expected_code = oracle.accept(kind, index)
            try:
                accept(run, IND, op)
                actual_ok, actual_code = True, ''
            except ProtocolError as exc:
                actual_ok, actual_code = False, exc.code
            mismatch = (actual_ok != expected_ok or
                        (not actual_ok and actual_code != expected_code))
            if mismatch:
                counters['mismatch'] += 1
            record = {'position': position, 'token': token, 'kind': kind, 'index': index,
                      'operation_id': op['action']['operation_id'],
                      'expected': expected_ok, 'expected_code': expected_code,
                      'actual': actual_ok, 'actual_code': actual_code,
                      'mismatch': mismatch}
            if actual_ok:
                counters['accepted'] += 1
                unknown = (spec.get('unknown_at') == position)
                if unknown:
                    oid = op['action']['operation_id']
                    run.w.claim(IND, oid, run.worker_proof(IND, oid, 'CLAIM'))
                    _tool_flag(run, drop_before_tool=True)
                    response = run.w.execute_once(IND, oid, run.worker_proof(IND, oid, 'EXECUTE'))
                    counters['unknown'] += 1
                    record['unknown'] = response.get('state')
                    oracle.settle(kind, index, 'UNKNOWN')
                    _tool_flag(run, drop_before_tool=False)
                else:
                    oid = op['action']['operation_id']
                    run.w.claim(IND, oid, run.worker_proof(IND, oid, 'CLAIM'))
                    response = run.w.execute_once(IND, oid, run.worker_proof(IND, oid, 'EXECUTE'))
                    if response.get('record') is None:
                        raise RuntimeError('ACCEPTED_ACTION_DID_NOT_SETTLE ' + token + ' '
                                           + json.dumps(response, ensure_ascii=False)[:500])
                    run.w.settle(IND, oid, response, run.worker_proof(IND, oid, 'SETTLE'))
                    oracle.settle(kind, index)
                    if capture_position == position:
                        record['package'] = build_package(run, IND, oid)
                        record['anchor'] = build_anchor(run)
                record['after'] = _result(run, op)
            else:
                counters['rejected'] += 1
                record['after'] = _result(run, op)
            trace.append(record)
        counts = run.w.counts()
        return {'mode': mode, 'spec': spec, 'order': order, 'trace': trace,
                'counters': counters, 'counts': counts,
                'final_reserved': counts.get('goal_pending', 0)}
    finally:
        run.close(); folder.cleanup()


def model_sequence(spec, order, *, enforce):
    oracle = Oracle(spec['capacity'], spec['required'], spec['optional'],
                    enforce=enforce, costs=spec.get('costs'))
    rows = []
    for position, token in enumerate(order):
        kind, index = token[0], int(token[1:])
        ok, code = oracle.accept(kind, index)
        if ok:
            if spec.get('unknown_at') == position:
                oracle.settle(kind, index, 'UNKNOWN')
            else:
                oracle.settle(kind, index)
        rows.append({'position': position, 'token': token, 'accepted': ok, 'code': code,
                     'spent': oracle.spent, 'reserved': oracle.reserved})
    return rows


def fixed_orders():
    return ['mixed', 'required_first', 'optional_first']


def make_order(required, optional, pattern):
    r = [f'R{i}' for i in range(required)]
    o = [f'O{i}' for i in range(optional)]
    if pattern == 'required_first':
        return r + o
    if pattern == 'optional_first':
        return o + r
    mixed = []
    while r or o:
        if o:
            mixed.append(o.pop(0))
        if r:
            mixed.append(r.pop(0))
    return mixed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', type=int, default=2)
    parser.add_argument('--model', type=int, default=1000)
    parser.add_argument('--output', default=str(RESULTS / 'long-sequence.json'))
    args = parser.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    COUNTER.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261124)
    orders = fixed_orders()
    templates = [
        {'capacity': 3, 'required': 3, 'optional': 3, 'pattern': 'mixed',
         'multi_goal': False, 'unknown_at': None},
        {'capacity': 4, 'required': 3, 'optional': 3, 'pattern': 'mixed',
         'multi_goal': False, 'unknown_at': None},
        {'capacity': 6, 'required': 3, 'optional': 3, 'pattern': 'optional_first',
         'multi_goal': False, 'unknown_at': None},
        {'capacity': 4, 'required': 2, 'optional': 3, 'pattern': 'mixed',
         'multi_goal': True, 'unknown_at': None},
        {'capacity': 4, 'required': 3, 'optional': 2, 'pattern': 'mixed',
         'multi_goal': False, 'unknown_at': 1},
    ]
    specs = []
    for index in range(args.real):
        template = dict(templates[index % len(templates)])
        pattern = template.pop('pattern')
        spec = {'name': f'seq-{index}', **template}
        spec['order'] = make_order(spec['required'], spec['optional'], pattern)
        specs.append(spec)
    real = []
    counterexamples = []
    for spec in specs:
        off = run_sequence('off', spec, spec['order'])
        proposed = run_sequence('enforce', spec, spec['order'])
        violations = []
        for left, right in zip(off['trace'], proposed['trace']):
            if left['actual'] and not right['actual']:
                violations.append({'position': left['position'], 'token': left['token'],
                                   'off_code': left['actual_code'],
                                   'proposed_code': right['actual_code']})
        pair = {'spec': spec, 'off': off, 'proposed': proposed,
                'violations': violations,
                'first_violation': violations[0] if violations else None,
                'first_violation_position': violations[0]['position'] if violations else None}
        if violations and len(counterexamples) < 2:
            position = violations[0]['position']
            captured = run_sequence('off', spec, spec['order'], capture_position=position)
            record = next(row for row in captured['trace'] if row['position'] == position)
            if 'package' in record:
                counterexamples.append({
                    'spec': spec, 'position': position,
                    'off_package': record['package'],
                    'off_anchor': record['anchor'],
                    'proposed_rejection': violations[0]})
                (COUNTER / f"{spec['name']}-counterexample.json").write_text(
                    json.dumps(counterexamples[-1], ensure_ascii=False, indent=1),
                    encoding='utf-8')
        real.append(pair)
        print(spec['name'], 'off accepts', off['counters']['accepted'],
              'proposed accepts', proposed['counters']['accepted'],
              'violations', len(violations),
              'mismatch', off['counters']['mismatch'], proposed['counters']['mismatch'])
    model = []
    for index in range(args.model):
        capacity = rng.choice([2, 3, 4, 5])
        required = rng.choice([2, 3, 4])
        optional = rng.choice([2, 3, 4, 5])
        tokens = [f'R{i}' for i in range(required)] + [f'O{i}' for i in range(optional)]
        rng.shuffle(tokens)
        model_type = rng.choice(['fixed', 'heterogeneous', 'burst', 'multi_goal'])
        costs = {}
        for token in tokens:
            if model_type == 'fixed':
                costs[token] = 1
            elif model_type == 'heterogeneous':
                costs[token] = rng.choice([1, 1, 2, 3])
            elif model_type == 'burst':
                costs[token] = 5 if rng.random() < 0.2 else 1
            else:
                costs[token] = rng.choice([1, 2])
        spec = {'name': f'model-{index}', 'capacity': capacity, 'required': required,
                'optional': optional, 'order': tokens,
                'multi_goal': model_type == 'multi_goal',
                'model_type': model_type, 'costs': costs,
                'unknown_at': rng.randrange(len(tokens)) if rng.random() < 0.1 else None}
        model.append({'spec': spec,
                      'off': model_sequence(spec, tokens, enforce=False),
                      'proposed': model_sequence(spec, tokens, enforce=True)})
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'real_sequences': len(real), 'model_sequences': len(model),
              'real': real, 'model': model, 'counterexamples': len(counterexamples),
              'total_violations': sum(len(r['violations']) for r in real),
              'all_real_mismatch_zero': all(r['off']['counters']['mismatch'] == 0 and
                                            r['proposed']['counters']['mismatch'] == 0
                                            for r in real)}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('real', len(real), 'all_mismatch_zero', report['all_real_mismatch_zero'],
          'violations', report['total_violations'])
    return 0 if report['all_real_mismatch_zero'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
