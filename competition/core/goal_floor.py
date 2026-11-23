"""Minimal C-certified GoalFloor guard (competition integration, shadow first).

This module is deliberately a pure necessary-condition checker.  It does not
plan, search a winning region, rank states, or claim that a goal is reachable.
It answers one question for W's *current* atomic-accept transaction:

    spent + reserved + candidate_cost + remaining_goal_floor <= capacity

``spent``/``reserved`` are W's reservation ledger totals, ``candidate_cost`` is
W's own transaction plan amount, and ``remaining_goal_floor`` is the sum of the
still-open required obligations certified by C for every active GoalFloor that
shares the candidate's resource.  No number in this module is read from an
Agent request.
"""
from competition.support.wire import digest, number, require, sortset

MODEL = 'goal-floor-v1'
GOAL_DOMAIN = 'ZJJ-C-GOAL-FLOOR-v1'
STATE_DOMAIN = 'ZJJ-GOAL-STATE-v1'
CHECK_DOMAIN = 'ZJJ-GOAL-CHECK-v1'
ACTION_DOMAIN = 'ZJJ-GOAL-ACTION-v1'
UNITS = ('UNIT', 'ORDER', 'CNY_MINOR')
STATES = ('OPEN', 'PENDING', 'DONE', 'BLOCKED')
SELECTOR_FIELDS = ('scope', 'principal', 'holder', 'holder_kid', 'executor',
                   'tool', 'tool_version', 'destination', 'payload')


def _is_id(value):
    return (type(value) is str and 1 <= len(value) <= 64 and
            value[0].isascii() and value[0].islower() and
            all(ch.isascii() and (ch.islower() or ch.isdigit() or ch in '._:-')
                for ch in value))


def action_selector(profile, action):
    """Stable digest of the business action, excluding its fresh operation id.

    A GoalFloor rule names this digest, not an Agent-supplied action name.  An
    Agent therefore cannot drop or swap a goal reference: W maps the frozen
    Action itself to the C-certified rule.
    """
    require(type(action) is dict and set(action) == set(SELECTOR_FIELDS) | {'operation_id'},
            'ACTION_FIELDS')
    body = {key: action[key] for key in SELECTOR_FIELDS}
    return digest([ACTION_DOMAIN, '2.6', profile, body])


def goal_ref(profile, claim):
    return digest([GOAL_DOMAIN, '2.6', profile, claim])


def validate_claim(profile, claim):
    """Strict shape check for the C-signed value.  Called on publish and on use."""
    require(type(claim) is dict and
            set(claim) == {'model', 'group', 'epoch', 'resource_key', 'unit',
                           'capacity', 'deps', 'actions'}, 'GOAL_FIELDS')
    require(claim['model'] == MODEL, 'GOAL_MODEL')
    require(_is_id(claim['group']), 'GOAL_GROUP')
    require(number(claim['epoch'], True), 'GOAL_EPOCH')
    require(type(claim['resource_key']) is list and 1 <= len(claim['resource_key']) <= 8 and
            all(_is_id(item) for item in claim['resource_key']), 'GOAL_RESOURCE_KEY')
    require(claim['unit'] in UNITS, 'GOAL_UNIT')
    require(number(claim['capacity'], True), 'GOAL_CAPACITY')
    deps = claim['deps']
    require(type(deps) is list and 1 <= len(deps) <= 16, 'GOAL_DEPS')
    dep_keys = []
    for dep in deps:
        require(type(dep) is dict and
                set(dep) == {'namespace', 'key', 'revision', 'ref'}, 'GOAL_DEP_FIELDS')
        require(dep['namespace'] in ('POLICY', 'TASK', 'INCIDENT'), 'GOAL_DEP_NAMESPACE')
        require(type(dep['key']) is list and 1 <= len(dep['key']) <= 8 and
                all(type(item) is str and item for item in dep['key']), 'GOAL_DEP_KEY')
        require(number(dep['revision'], True), 'GOAL_DEP_REVISION')
        require(type(dep['ref']) is str and len(dep['ref']) == 43, 'GOAL_DEP_REF')
        dep_keys.append((dep['namespace'], tuple(dep['key'])))
    require(len(dep_keys) == len(set(dep_keys)), 'GOAL_DEP_DUPLICATE')
    require(any(dep['namespace'] == 'POLICY' for dep in deps), 'GOAL_POLICY_DEP')
    actions = claim['actions']
    require(type(actions) is list and 1 <= len(actions) <= 64, 'GOAL_ACTIONS')
    names, obligations = [], []
    for action in actions:
        require(type(action) is dict and
                set(action) == {'name', 'profile', 'action_digest', 'obligation', 'cost'},
                'GOAL_ACTION_FIELDS')
        require(_is_id(action['name']) and action['profile'] == profile, 'GOAL_ACTION')
        require(type(action['action_digest']) is str and len(action['action_digest']) == 43,
                'GOAL_ACTION_DIGEST')
        require(action['obligation'] == '' or _is_id(action['obligation']),
                'GOAL_OBLIGATION')
        require(number(action['cost'], True), 'GOAL_ACTION_COST')
        names.append(action['name'])
        if action['obligation']:
            obligations.append(action['obligation'])
    require(len(names) == len(set(names)), 'GOAL_ACTION_DUPLICATE')
    require(len({action['action_digest'] for action in actions}) == len(actions),
            'GOAL_SELECTOR_DUPLICATE')
    require(len(obligations) == len(set(obligations)), 'GOAL_OBLIGATION_DUPLICATE')
    require(bool(obligations), 'GOAL_OBLIGATION_NONE')
    # This is not a reachability claim: it only rejects a goal that cannot meet
    # its own certified floor even before any candidate is accepted.
    require(sum(int(action['cost']) for action in actions if action['obligation']) <=
            int(claim['capacity']), 'GOAL_UNREACHABLE_AT_PUBLISH')
    return claim


def _status_key(group, obligation):
    return group + '\x00' + obligation


def state_digest(capacity, spent, reserved, statuses):
    """Canonical digest of the W ledger snapshot used by one decision."""
    rows = [{'group': group, 'obligation': obligation, 'state': state}
            for (group, obligation), state in sorted(statuses.items(),
                                                     key=lambda item: (item[0][0], item[0][1]))]
    return digest([STATE_DOMAIN, {'capacity': str(capacity), 'spent': str(spent),
                                  'reserved': str(reserved), 'statuses': rows}])


def evaluate(profile, goals, statuses, *, capacity, spent, reserved, candidate):
    """Return one deterministic decision and its witness.

    ``goals`` is every active GoalFloor whose resource key equals the candidate
    resource.  ``statuses`` maps ``(group, obligation)`` to OPEN/PENDING/DONE/
    BLOCKED; absence means OPEN.  ``candidate`` is W's own plan: cost, resource
    key, unit, and the already-computed action selector.
    """
    require(type(goals) is list and bool(goals), 'GOAL_UNKNOWN')
    require(type(statuses) is dict, 'GOAL_STATUS')
    require(number(str(capacity), True) and number(str(spent)) and number(str(reserved)),
            'GOAL_LEDGER')
    require(0 <= int(spent) + int(reserved) <= int(capacity), 'GOAL_LEDGER')
    require(type(candidate) is dict and
            set(candidate) == {'cost', 'resource_key', 'unit', 'selector'}, 'GOAL_CANDIDATE')
    require(number(str(candidate['cost']), True), 'GOAL_COST')
    matches, open_rows = [], []
    for goal in goals:
        claim = goal['claim']
        require(validate_claim(profile, claim) is claim, 'GOAL_CERTIFIED')
        require(goal['ref'] == goal_ref(profile, claim), 'GOAL_REF')
        require(claim['resource_key'] == candidate['resource_key'], 'GOAL_RESOURCE_MISMATCH')
        require(claim['unit'] == candidate['unit'], 'GOAL_UNIT_MISMATCH')
        require(int(claim['capacity']) == int(capacity), 'GOAL_CAPACITY_MISMATCH')
        for action in claim['actions']:
            if action['action_digest'] == candidate['selector']:
                require(int(action['cost']) == int(candidate['cost']), 'GOAL_COST_MISMATCH')
                matches.append({'group': claim['group'], 'goal_ref': goal['ref'],
                                'epoch': claim['epoch'], 'action': action['name'],
                                'obligation': action['obligation'],
                                'cost': action['cost']})
        for action in claim['actions']:
            if not action['obligation']:
                continue
            state = statuses.get((claim['group'], action['obligation']), 'OPEN')
            require(state in STATES, 'GOAL_STATUS')
            open_rows.append({'group': claim['group'], 'obligation': action['obligation'],
                              'cost': action['cost'], 'state': state,
                              'obligation_name': action['name']})
    matched_obligations = {(row['group'], row['obligation']) for row in matches
                           if row['obligation']}
    for row in open_rows:
        if row['state'] == 'PENDING':
            raise_decision = {'ok': False, 'reason': 'GOAL_PENDING_UNKNOWN'}
            return _decision(profile, candidate, capacity, spent, reserved, open_rows,
                             matches, raise_decision)
        if row['state'] == 'BLOCKED':
            return _decision(profile, candidate, capacity, spent, reserved, open_rows,
                             matches, {'ok': False, 'reason': 'GOAL_BLOCKED'})
        if row['state'] == 'DONE' and (row['group'], row['obligation']) in matched_obligations:
            return _decision(profile, candidate, capacity, spent, reserved, open_rows,
                             matches, {'ok': False, 'reason': 'GOAL_ALREADY_COMMITTED'})
        if row['state'] == 'DONE':
            continue
    remaining = sum(int(row['cost']) for row in open_rows
                    if row['state'] == 'OPEN' and
                    (row['group'], row['obligation']) not in matched_obligations)
    total = int(spent) + int(reserved) + int(candidate['cost']) + remaining
    ok = total <= int(capacity)
    return _decision(profile, candidate, capacity, spent, reserved, open_rows, matches,
                     {'ok': ok, 'reason': '' if ok else 'GOAL_CAPACITY_FLOOR'})


def _decision(profile, candidate, capacity, spent, reserved, open_rows, matches, result):
    remaining = sum(int(row['cost']) for row in open_rows
                    if row['state'] == 'OPEN' and
                    (row['group'], row['obligation']) not in
                    {(m['group'], m['obligation']) for m in matches if m['obligation']})
    total = int(spent) + int(reserved) + int(candidate['cost']) + remaining
    decision = {
        'profile': profile,
        'decision': 'T' if result['ok'] else 'F',
        'reason': result['reason'],
        'capacity': str(capacity),
        'spent': str(spent),
        'reserved': str(reserved),
        'candidate_cost': str(candidate['cost']),
        'remaining_floor': str(remaining),
        'total': str(total),
        'headroom': str(int(capacity) - total),
        'matched': sortset(matches),
        'obligations': sorted(open_rows, key=lambda row: (row['group'], row['obligation'])),
    }
    decision['check_ref'] = digest([CHECK_DOMAIN, decision])
    return decision
