"""Bulk authenticated IND units for long-sequence evaluation.

This helper creates the same C/E records as ``register_ind_unit`` but widens
role unit sets once and signs each operation after the last publication.  It is
an evaluation fixture, not a production entry point.
"""
import copy
import json
import os

from competition.core.trusted_state import prefix
from competition.support.wire import b64, canonical, rec_ref, require, sortset

IND = 'IND-DEMO-1'


def bulk_ind_units(run, specs, *, route=None):
    """Create one real signed operation per spec ``(unit_id, batch_id, principal)``."""
    profile = IND
    original = run.clone(profile)
    scope_key = prefix(profile)
    payload = original['action']['payload']
    units = []
    with run.store.db() as c:
        base_identity = copy.deepcopy(run.store.current(c, profile, 'IDENTITY',
                                                       scope_key + [payload['unit_id']])['record'])
        base_evidence = copy.deepcopy(run.store.current(c, profile, 'EVIDENCE',
                                                       original['scene_key'])['record'])
        base_scene = copy.deepcopy(run.store.current(c, profile, 'UNIT',
                                                    original['scene_key'])['record'])
        base_task = copy.deepcopy(run.store.current(c, profile, 'TASK',
                                                   scope_key + [original['task_id']])['record'])
        base_behavior = copy.deepcopy(run.store.current(c, profile, 'BEHAVIOR',
                                                       scope_key + [original['action']['principal']])['record'])
        role_rows = [dict(row) for row in c.execute(
            "SELECT key,revision,record FROM a_current WHERE profile=? AND namespace='ROLE' AND active=1",
            (profile,))]
    require(base_scene['value']['state'] == 'READY', 'SCENE_NOT_READY')
    for unit_id, batch_id, principal in specs:
        identity = copy.deepcopy(base_identity)
        evidence = copy.deepcopy(base_evidence)
        scene = copy.deepcopy(base_scene)
        task = copy.deepcopy(base_task)
        behavior = copy.deepcopy(base_behavior)
        identity['value'].update(unit_id=unit_id, batch_id=batch_id)
        identity_ref = rec_ref(identity)
        evidence['value']['data'].update(unit_id=unit_id, batch_id=batch_id,
                                        unit_ref=identity_ref, evidence_id=b64(os.urandom(16)))
        if route is not None:
            from competition.support.scene_contract import DEST, MAPPING
            require(route in DEST and route in set(MAPPING.values()), 'SCENARIO_ROUTE')
            evidence['value']['data']['label'] = next(label for label, mapped in MAPPING.items()
                                                      if mapped == route)
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
        for record in (identity, evidence, task):
            schema.validate(record, 'Record_' + record['kind'])
        schema.validate(scene['value'], 'SceneRow')
        schema.validate(behavior['value'], 'BehaviorRow')
        scene_key = scope_key + [payload['line_id'], unit_id]
        for namespace, key, record in (
                ('IDENTITY', scope_key + [unit_id], identity),
                ('EVIDENCE', scene_key, evidence),
                ('UNIT', scene_key, scene),
                ('TASK', scope_key + [task_id], task),
                ('BEHAVIOR', scope_key + [principal], behavior)):
            run.base.publish(profile, namespace, key, record)
        original_unit = run.clone(profile)
        original_unit['action']['payload'].update(unit_id=unit_id, batch_id=batch_id)
        if route is not None:
            from competition.support.scene_contract import DEST
            original_unit['action']['payload']['route'] = route
            original_unit['action']['destination'] = DEST[route]
        original_unit['action']['principal'] = principal
        original_unit['task_id'] = task_id
        original_unit['scene_key'] = scene_key
        units.append(original_unit)
    # One role publication per role after all units are known.
    unit_ids = [spec[0] for spec in specs]
    for role_row in role_rows:
        record = json.loads(role_row['record'])
        constraints = record['value']['constraints']
        if 'unit_set' in constraints:
            missing = [unit for unit in unit_ids if unit not in constraints['unit_set']]
            if missing:
                constraints['unit_set'] = sortset(constraints['unit_set'] + missing)
                record['value']['epoch'] = str(role_row['revision'] + 1)
                run.base.publish(profile, 'ROLE', json.loads(role_row['key']), record)
    # Sign every chain after the last C revision.
    return [run.fork_operation(profile, unit) for unit in units]
