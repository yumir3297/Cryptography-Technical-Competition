"""Controlled C-side GoalFloor fixtures for evaluation tests.

This is a test/bootstrap helper, not a protocol authority.  It builds the
C-signed record through the existing ``AuthorizationRun.publish`` path; it does
not mint a second root key or write W tables directly.
"""
from competition.core.goal_floor import action_selector, goal_ref, validate_claim
from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.support.scene_contract import _rec
from competition.support.wire import require


def current_deps(run, profile, ops):
    """Current POLICY/TASK refs for every distinct action in a goal."""
    deps = []
    with run.store.db() as c:
        policy = run.store.current(c, profile, 'POLICY', prefix(profile))
        deps.append({'namespace': 'POLICY', 'key': prefix(profile),
                     'revision': str(policy['revision']), 'ref': policy['ref']})
        seen = set()
        for op in ops:
            key = prefix(profile) + [op['task_id']]
            if tuple(key) in seen:
                continue
            seen.add(tuple(key))
            task = run.store.current(c, profile, 'TASK', key)
            deps.append({'namespace': 'TASK', 'key': key,
                         'revision': str(task['revision']), 'ref': task['ref']})
    return deps


def goal_claim(run, profile, group, rules, *, capacity, epoch='1', resource_key=None,
               unit=None, incident_deps=()):
    """Build and validate one GoalFloor value.

    ``rules`` items are ``{'name','op','obligation','cost'}``.  The action digest
    is computed from the frozen Action, never from an Agent-supplied label.
    """
    ops = [rule['op'] for rule in rules]
    actions = [{'name': rule['name'], 'profile': profile,
                'action_digest': action_selector(profile, rule['op']['action']),
                'obligation': rule['obligation'], 'cost': str(rule['cost'])}
               for rule in rules]
    deps = current_deps(run, profile, ops)
    with run.store.db() as c:
        for incident_id in incident_deps:
            current = run.store.current(c, profile, 'INCIDENT', prefix(profile) + [incident_id])
            deps.append({'namespace': 'INCIDENT', 'key': prefix(profile) + [incident_id],
                         'revision': str(current['revision']), 'ref': current['ref']})
    claim = {'model': 'goal-floor-v1', 'group': group, 'epoch': str(epoch),
             'resource_key': resource_key, 'unit': unit, 'capacity': str(capacity),
             'deps': deps, 'actions': actions}
    if resource_key is None or unit is None:
        with run.store.db() as c:
            row = c.execute('SELECT key,unit FROM w_resource WHERE profile=?', (profile,)).fetchone()
            require(row is not None, 'GOAL_RESOURCE_UNKNOWN')
            import json
            claim['resource_key'] = json.loads(row['key'])
            claim['unit'] = row['unit']
    validate_claim(profile, claim)
    return claim


def publish_goal(run, profile, claim):
    record = _rec(profile, 'GOAL_FLOOR', PROFILE_SCOPES[profile], claim)
    run.base.publish(profile, 'GOAL', prefix(profile) + [claim['group']], record)
    return goal_ref(profile, claim)


def current_goal(run, profile, group):
    with run.store.db() as c:
        row = run.store.current(c, profile, 'GOAL', prefix(profile) + [group])
        return row['record']['value'], row['revision']


def update_goal(run, profile, group, claim):
    """Publish the next epoch of an existing group (C's existing revision path)."""
    current, revision = current_goal(run, profile, group)
    require(claim['group'] == group and int(claim['epoch']) == revision + 1,
            'GOAL_EPOCH')
    return publish_goal(run, profile, claim)
