"""Controlled C/E registrations for independent common-W business scenarios."""
import copy
import json
import os

from competition.core.trusted_state import prefix
from research.reference_executor.wire import b64, canonical, rec_ref, require, sortset


def register_ind_unit(run, *, unit_id='unit-b', batch_id='batch-b', principal='principal-b'):
    """Register a second real authenticated unit/task/behavior, then sign its op.

    The original policy/package and all source windows stay unchanged. C widens
    current role unit sets before either competing operation is re-derived, so
    resource contention cannot accidentally be a shared Behavior revision race.
    """
    profile = 'IND-DEMO-1'; original = run.clone(profile); scope_key = prefix(profile)
    payload = original['action']['payload']
    require(unit_id != payload['unit_id'] and principal != original['action']['principal'], 'SCENARIO_BINDING')
    with run.store.db() as c:
        identity = copy.deepcopy(run.store.current(c, profile, 'IDENTITY', scope_key + [payload['unit_id']])['record'])
        evidence = copy.deepcopy(run.store.current(c, profile, 'EVIDENCE', original['scene_key'])['record'])
        scene = copy.deepcopy(run.store.current(c, profile, 'UNIT', original['scene_key'])['record'])
        task = copy.deepcopy(run.store.current(c, profile, 'TASK', scope_key + [original['task_id']])['record'])
        behavior = copy.deepcopy(run.store.current(c, profile, 'BEHAVIOR', scope_key + [original['action']['principal']])['record'])
        role_rows = [dict(row) for row in c.execute("SELECT key,revision,record FROM a_current WHERE profile=? AND namespace='ROLE' AND active=1", (profile,))]
        require(c.execute("SELECT 1 FROM a_current WHERE profile=? AND namespace='IDENTITY' AND key=?", (profile, json.dumps(scope_key + [unit_id], ensure_ascii=False, sort_keys=True, separators=(',', ':')))).fetchone() is None, 'SCENARIO_EXISTS')
    require(scene['value']['state'] == 'READY', 'SCENE_NOT_READY')
    identity['value'].update(unit_id=unit_id, batch_id=batch_id)
    identity_ref = rec_ref(identity)
    evidence['value']['data'].update(unit_id=unit_id, batch_id=batch_id,
                                    unit_ref=identity_ref, evidence_id=b64(os.urandom(16)))
    attestation = evidence['value']['attestation']
    header = {k: attestation[k] for k in ('issuer', 'kid', 'iat', 'exp')}
    attestation['sig'] = b64(run.actors[profile]['E'].key.sign(canonical([
        'ZJJ-SOURCE-v1', '2.6', profile, 'IND_EVIDENCE', original['action']['scope'],
        evidence['value']['data'], header])))
    scene['value'].update(unit_ref=identity_ref, evidence_ref=rec_ref(evidence), operation_id='')
    task_id = b64(os.urandom(16))
    task['value'].update(task_id=task_id, principal=principal, allowed_units=[{
        'unit_ref': identity_ref, 'unit_id': unit_id, 'batch_id': batch_id,
        'inspection_cycle': payload['inspection_cycle'], 'phase': payload['phase']}])
    behavior['value'].update(accepted_count='0', inflight=[])
    schema = run.store.schemas[profile]
    for record in (identity, evidence, task): schema.validate(record, 'Record_' + record['kind'])
    schema.validate(scene['value'], 'SceneRow'); schema.validate(behavior['value'], 'BehaviorRow')
    for role_row in role_rows:
        record = json.loads(role_row['record']); constraints = record['value']['constraints']
        if 'unit_set' in constraints and unit_id not in constraints['unit_set']:
            constraints['unit_set'] = sortset(constraints['unit_set'] + [unit_id])
            record['value']['epoch'] = str(role_row['revision'] + 1)
            run.base.publish(profile, 'ROLE', json.loads(role_row['key']), record)
    scene_key = scope_key + [payload['line_id'], unit_id]
    for namespace, key, record in (
        ('IDENTITY', scope_key + [unit_id], identity), ('EVIDENCE', scene_key, evidence),
        ('UNIT', scene_key, scene), ('TASK', scope_key + [task_id], task),
        ('BEHAVIOR', scope_key + [principal], behavior)):
        run.base.publish(profile, namespace, key, record)
    original['action']['payload'].update(unit_id=unit_id, batch_id=batch_id)
    original['action']['principal'] = principal
    original['task_id'] = task_id; original['scene_key'] = scene_key
    return run.fork_operation(profile, original)
