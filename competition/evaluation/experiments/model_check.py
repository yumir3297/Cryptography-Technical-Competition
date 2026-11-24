"""E7: bounded exhaustive independent model of the GoalFloor state machine."""
from __future__ import annotations
import itertools
import json
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
RESULTS = EVAL / 'results'


def explore(capacity, required, optional):
    """BFS over all reachable states; no import of the tested evaluator."""
    start = (0, 0, tuple('OPEN' for _ in range(required)))
    seen = {start}
    queue = [start]
    transitions = 0
    violations = []
    while queue:
        spent, reserved, status = queue.pop()
        actions = []
        for i in range(required):
            actions.append(('accept', 'R', i))
        for i in range(optional):
            actions.append(('accept', 'O', i))
        for i in range(required):
            actions.append(('settle', 'R', i))
            actions.append(('fail', 'R', i))
            actions.append(('cancel', 'R', i))
        for action in actions:
            kind, typ, index = action
            transitions += 1
            nspent, nreserved, nstatus = spent, reserved, list(status)
            if kind == 'accept':
                obligation = index if typ == 'R' else None
                if any(s == 'PENDING' for s in nstatus):
                    allowed = False
                elif any(s == 'BLOCKED' for s in nstatus):
                    allowed = False
                elif obligation is not None and nstatus[obligation] != 'OPEN':
                    allowed = False
                else:
                    remaining = sum(1 for j, s in enumerate(nstatus)
                                    if s == 'OPEN' and j != obligation)
                    allowed = spent + reserved + 1 + remaining <= capacity
                if allowed:
                    nreserved += 1
                    if obligation is not None:
                        nstatus[obligation] = 'PENDING'
            else:
                if typ != 'R' or nstatus[index] != 'PENDING':
                    allowed = False
                else:
                    allowed = True
                    nreserved -= 1
                    if kind == 'settle':
                        nspent += 1
                        nstatus[index] = 'DONE'
                    else:
                        nstatus[index] = 'BLOCKED'
            if not allowed:
                continue
            state = (nspent, nreserved, tuple(nstatus))
            if nspent + nreserved > capacity:
                violations.append({'from': (spent, reserved, status), 'action': action,
                                   'to': state, 'reason': 'RESOURCE_BOUND'})
            if any(nstatus.count('DONE') > 1 for _ in (0,)):
                pass
            if state not in seen:
                seen.add(state); queue.append(state)
    return {'capacity': capacity, 'required': required, 'optional': optional,
            'states': len(seen), 'transitions': transitions,
            'violations': len(violations), 'examples': violations[:3]}


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for capacity in (2, 3, 4, 5, 6):
        for required in (2, 3, 4):
            for optional in (0, 1, 2, 3, 4):
                rows.append(explore(capacity, required, optional))
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'runs': rows, 'states': sum(r['states'] for r in rows),
              'transitions': sum(r['transitions'] for r in rows),
              'violations': sum(r['violations'] for r in rows),
              'all_zero': all(r['violations'] == 0 for r in rows)}
    (RESULTS / 'model-check.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
