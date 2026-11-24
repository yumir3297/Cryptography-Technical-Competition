"""E5: GoalFloor enforce on PAY-1 and MED-DEMO-1 business semantics.

The default action is locally legal under the legacy resource bound.  A second
C-certified GoalFloor reserves capacity for an unmatched necessary item; the sum
of the two individually valid goals exceeds capacity, so enforce rejects the
default action while off accepts it.  No business rule is changed.
"""
from __future__ import annotations
import json
import tempfile
import time
from pathlib import Path

from competition.profiles.w_plans import TransactionPlans
from competition.profiles.w_seed import initialize
from competition.evaluation.fixtures import accept, execute_and_settle
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.wire import ProtocolError, digest

EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def _resource(run, profile):
    with run.store.db() as c:
        row = c.execute('SELECT key,unit,capacity FROM w_resource WHERE profile=?',
                        (profile,)).fetchone()
        return json.loads(row[0]), row[1], row[2]


def _plan(run, profile, op):
    with run.store.db() as c:
        now = int(time.time())
        return TransactionPlans(run.store).plan(c, profile, op, {'lo': now, 'hi': now}, 1)


def _unmatched_goal(run, profile, op, capacity, group):
    claim = goal_claim(run, profile, group,
                       [{'name': 'reserve-necessary', 'op': op,
                         'obligation': 'reserve-necessary', 'cost': capacity}],
                       capacity=capacity)
    claim['actions'][0]['action_digest'] = digest(['E5-UNMATCHED', profile, group])
    return claim


def one(profile, mode, *, crowd):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), goal_mode=mode)
    try:
        op = run.operations[profile]
        key, unit, capacity = _resource(run, profile)
        plan = _plan(run, profile, op)
        cost = plan['amount']
        publish_goal(run, profile, goal_claim(
            run, profile, 'g-required',
            [{'name': 'required-action', 'op': op, 'obligation': 'required-action',
              'cost': cost}],
            capacity=capacity, resource_key=key, unit=unit))
        if crowd:
            publish_goal(run, profile, _unmatched_goal(
                run, profile, op, capacity, 'g-reserve'))
        try:
            accept(run, profile, op)
            accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        package = None
        audit = None
        if accepted and not crowd:
            response, _ = execute_and_settle(run, profile, op)
            package = build_package(run, profile, op['action']['operation_id'])
            audit = verify_package(package, build_anchor(run))
        return {'profile': profile, 'mode': mode, 'crowd': crowd,
                'capacity': capacity, 'plan_amount': cost,
                'accepted': accepted, 'code': code,
                'counts': run.w.counts(),
                'audit_status': audit['status'] if audit else None,
                'audit_checks': len(audit['checks']) if audit else None}
    finally:
        run.close(); folder.cleanup()


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for profile in ('PAY-1', 'MED-DEMO-1'):
        rows.append(one(profile, 'off', crowd=True))
        rows.append(one(profile, 'enforce', crowd=True))
        rows.append(one(profile, 'enforce', crowd=False))
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'rows': rows,
              'all_expected': all(
                  (r['mode'] == 'off' and r['crowd'] and r['accepted']) or
                  (r['mode'] == 'enforce' and r['crowd'] and not r['accepted'] and
                   r['code'] == 'GOAL_CAPACITY_FLOOR') or
                  (r['mode'] == 'enforce' and not r['crowd'] and r['accepted'] and
                   r['audit_status'] == 'PASS')
                  for r in rows)}
    (RESULTS / 'cross-goal.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['all_expected'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
