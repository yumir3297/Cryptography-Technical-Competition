"""Concurrency histories and an independent GoalFloor reference model."""
from __future__ import annotations
import argparse
import json
import random
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from competition.evaluation.fixtures import (accept, execute_and_settle, ind_goal,
                                             ind_three_actions)
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.wire import ProtocolError

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def _prepared(run, ops):
    out = []
    for op in ops:
        ticket = run.w.prepare(IND, op, run.identity_proof(IND, op))
        out.append((op, ticket['ticket_id'], run.accept_proof(IND, ticket['ticket_id'])))
    return out


def _race(run, prepared):
    def call(item):
        op, ticket, proof = item
        start = time.monotonic_ns()
        try:
            result = run.w.accept(IND, ticket, proof)
            status, code = result['acceptance_state'], ''
        except ProtocolError as exc:
            status, code = 'REJECTED', exc.code
        return {'operation_id': op['action']['operation_id'], 'start_ns': start,
                'end_ns': time.monotonic_ns(), 'status': status, 'code': code}
    with ThreadPoolExecutor(len(prepared)) as pool:
        outcomes = list(pool.map(call, prepared))
    return outcomes


def _winners(run):
    with run.store.db() as c:
        rows = c.execute('SELECT oid,frozen FROM w_operation WHERE profile=?',
                         (IND,)).fetchall()
        result = []
        for row in rows:
            frozen = json.loads(row['frozen'])
            witness = frozen['commit']['value']['reservation_plan'][0]
            result.append({'operation_id': row['oid'],
                           'accept_seq': int(frozen['commit']['value']['accept_seq']),
                           'reserved_before': int(witness['reserved_before']),
                           'spent_before': int(witness['spent_before']),
                           'reserved_after': int(witness['reserved_after']),
                           'spent_after': int(witness['spent_after']),
                           'amount': int(witness['amount'])})
        return sorted(result, key=lambda row: row['accept_seq'])


def _linearizable(run, outcomes, capacity):
    winners = _winners(run)
    by_id = {row['operation_id']: row for row in winners}
    accepted = [o for o in outcomes if o['status'] == 'COMMITTED']
    rejected = [o for o in outcomes if o['status'] == 'REJECTED']
    if len(accepted) != len(winners):
        return False, 'accepted_count_mismatch'
    if len({row['accept_seq'] for row in winners}) != len(winners):
        return False, 'duplicate_accept_sequence'
    ordered = sorted(winners, key=lambda row: row['accept_seq'])
    reserved = 0
    for row in ordered:
        if row['reserved_before'] != reserved or row['spent_before'] != 0:
            return False, 'non_serial_reservation_chain'
        reserved = row['reserved_after']
        if reserved + row['spent_after'] > capacity:
            return False, 'capacity_violation'
    with run.store.db() as c:
        reservations = c.execute("SELECT COUNT(*) FROM w_reservation WHERE profile=? AND state='RESERVED'",
                                 (IND,)).fetchone()[0]
        resource = c.execute('SELECT reserved,spent,capacity FROM w_resource WHERE profile=?',
                             (IND,)).fetchone()
    if reservations != len(winners) or resource[0] != reserved or resource[1] != 0:
        return False, 'ledger_mismatch'
    # A rejected call must not leave an operation row or reservation.
    for outcome in rejected:
        if outcome['operation_id'] in by_id:
            return False, 'rejected_has_operation'
    return True, {'accept_seq': [row['accept_seq'] for row in ordered],
                  'reserved_chain': [row['reserved_after'] for row in ordered],
                  'rejected_codes': [o['code'] for o in rejected]}


def required_race(run):
    a, b, _ = ind_three_actions(run)
    ind_goal(run, (a, b, _))
    prepared = _prepared(run, (a, b))
    outcomes = _race(run, prepared)
    ok, detail = _linearizable(run, outcomes, 2)
    return {'scenario': 'two_required_obligations', 'outcomes': outcomes,
            'linearizable': ok, 'detail': detail,
            'counts': run.w.counts()}


def optional_race(run):
    a, c, d = ind_three_actions(run)
    # A is a required floor; C and D are optional consumers.  Both optional
    # calls fit when the floor is empty, but not once either one reserves.
    rules = [{'name': 'required-a', 'op': a, 'obligation': 'required-a', 'cost': 1},
             {'name': 'optional-c', 'op': c, 'obligation': '', 'cost': 1},
             {'name': 'optional-d', 'op': d, 'obligation': '', 'cost': 1}]
    with run.store.db() as db:
        resource = json.loads(db.execute('SELECT key FROM w_resource WHERE profile=?',
                                         (IND,)).fetchone()[0])
    publish_goal(run, IND, goal_claim(run, IND, 'capacity-race', rules, capacity=2,
                                      resource_key=resource, unit='UNIT'))
    prepared = _prepared(run, (c, d))
    outcomes = _race(run, prepared)
    ok, detail = _linearizable(run, outcomes, 2)
    return {'scenario': 'optional_last_slot', 'outcomes': outcomes,
            'linearizable': ok, 'detail': detail,
            'counts': run.w.counts()}


def run_actual(repetitions=10):
    results = []
    for index in range(repetitions):
        for scenario in (required_race, optional_race):
            folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
            run = initialize(Path(folder.name), resource_capacity={IND: 2}, goal_mode='enforce')
            try:
                record = scenario(run)
            finally:
                run.close()
                folder.cleanup()
            record['repetition'] = index
            results.append(record)
            print(scenario.__name__, index, record['linearizable'], record['detail'])
    return results


class Model:
    """Independent arithmetic model; it does not import competition.core.goal_floor."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.reserved = 0
        self.spent = 0
        self.status = {'A': 'OPEN', 'B': 'OPEN'}

    def accept(self, name, obligation, cost):
        if obligation and self.status[obligation] != 'OPEN':
            return 'REJECT', 'GOAL_ALREADY_COMMITTED'
        if any(state == 'PENDING' for state in self.status.values()):
            return 'REJECT', 'GOAL_PENDING_UNKNOWN'
        if any(state == 'BLOCKED' for state in self.status.values()):
            return 'REJECT', 'GOAL_BLOCKED'
        remaining = sum(1 for key, state in self.status.items()
                        if state == 'OPEN' and key != obligation)
        if self.spent + self.reserved + cost + remaining > self.capacity:
            return 'REJECT', 'GOAL_CAPACITY_FLOOR'
        self.reserved += cost
        if obligation:
            self.status[obligation] = 'PENDING'
        self.invariant()
        return 'ACCEPT', ''

    def settle(self, obligation, outcome):
        if obligation and self.status[obligation] != 'PENDING':
            return 'REJECT', 'FINAL_STATE'
        self.reserved -= 1
        if outcome == 'SUCCESS':
            self.spent += 1
            self.status[obligation] = 'DONE'
        else:
            self.status[obligation] = 'BLOCKED'
        self.invariant()
        return 'SETTLE', ''

    def invariant(self):
        assert 0 <= self.reserved + self.spent <= self.capacity
        assert all(state in ('OPEN', 'PENDING', 'DONE', 'BLOCKED')
                   for state in self.status.values())


def model_histories(count=10000, seed=20261123, operations=24):
    rng = random.Random(seed)
    failures = []
    for history in range(count):
        model = Model(rng.choice([2, 3, 4]))
        trace = []
        for _ in range(operations):
            choice = rng.choice(['acceptA', 'acceptB', 'acceptOpt',
                                 'settleA', 'settleB', 'failA', 'cancelA'])
            if choice.startswith('accept'):
                obligation = {'acceptA': 'A', 'acceptB': 'B', 'acceptOpt': None}[choice]
                result = model.accept(choice, obligation, 1)
            elif choice == 'settleA':
                result = model.settle('A', 'SUCCESS')
            elif choice == 'settleB':
                result = model.settle('B', 'SUCCESS')
            elif choice == 'failA':
                result = model.settle('A', 'FAILED_CONFIRMED')
            else:
                result = model.settle('A', 'FAILED_CONFIRMED')
            trace.append((choice, result))
        try:
            model.invariant()
        except AssertionError:
            failures.append({'history': history, 'trace': trace})
            if len(failures) >= 3:
                break
    return {'histories': count, 'seed': seed, 'operations_per_history': operations,
            'violations': len(failures), 'counterexamples': failures,
            'checked_transitions': count * operations}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repetitions', type=int, default=10)
    parser.add_argument('--model-count', type=int, default=10000)
    parser.add_argument('--output', default=str(RESULTS / 'concurrency.json'))
    args = parser.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    actual = run_actual(args.repetitions)
    model = model_histories(args.model_count)
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'actual_histories': len(actual),
              'actual_all_linearizable': all(r['linearizable'] for r in actual),
              'actual': actual, 'model': model}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                 encoding='utf-8')
    print('actual', len(actual), 'all_linearizable', report['actual_all_linearizable'])
    print('model', model['histories'], 'violations', model['violations'])
    return 0 if report['actual_all_linearizable'] and not model['violations'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
