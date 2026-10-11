"""Read-only Profile transaction plans using the original v2.6 witnesses.

The common W authenticates/guards the request first, then applies these proposed
transitions in its own transaction. This module never publishes, signs, reserves,
dispatches, changes source timestamps, or initializes a research authority.
"""
from copy import deepcopy

from competition.core.event_clock import require_window
from research.phase18.key_broker import PROFILE_SCOPES
from research.reference_executor.wire import digest, number, require, sortset


SCENES = {'IND-DEMO-1': 'UNIT', 'MED-DEMO-1': 'ENCOUNTER'}


class TransactionPlans:
    def __init__(self, state):
        self.state = state

    @staticmethod
    def _prefix(profile, action):
        require(profile in PROFILE_SCOPES and action['scope'] == PROFILE_SCOPES[profile], 'WRONG_SCOPE')
        return [action['scope'][k] for k in ('domain', 'tenant', 'scenario')]

    def _current(self, c, profile, namespace, key, kinds):
        current = self.state.current(c, profile, namespace, key)
        record = current['record']
        require(type(current['revision']) is int and current['revision'] > 0, 'REVISION')
        require(set(record) == {'version', 'profile', 'kind', 'scope', 'value'} and
                (record['version'], record['profile'], record['scope']) ==
                ('2.6', profile, PROFILE_SCOPES[profile]) and record['kind'] in kinds, 'OBJECT_KIND')
        if namespace in ('BEHAVIOR', 'UNIT', 'ENCOUNTER'):
            require(current['ref'] == digest(['ZJJ-STATE-v1', namespace, key,
                                             str(current['revision']), record['value']]), 'STATE_INTEGRITY')
        return current

    @staticmethod
    def _witness(namespace, key, current, *, after=None):
        revision = current['revision'] + (after is not None)
        row = deepcopy(current['record']['value'] if after is None else after)
        ref = current['ref'] if after is None else digest(['ZJJ-STATE-v1', namespace, key, str(revision), row])
        witness = {'key': deepcopy(key), 'revision': str(revision), 'ref': ref, 'row': row}
        if namespace != 'BEHAVIOR':
            witness['namespace'] = namespace
        return witness

    def plan(self, c, profile, op, event, accept_seq: int) -> dict:
        """Return original witnesses and scoped intent/resource keys, without writes."""
        require(type(accept_seq) is int and accept_seq > 0, 'ACCEPT_SEQUENCE')
        require(type(event['lo']) is int and type(event['hi']) is int and
                0 <= event['lo'] <= event['hi'], 'TIME_INTERVAL')
        action = op['action']; prefix = self._prefix(profile, action)
        schema = self.state.schemas[profile]
        schema.validate(action, 'Action')
        payload = action['payload']; oid = action['operation_id']
        policy = self._current(c, profile, 'POLICY', prefix, {'POLICY'})['record']
        task = self._current(c, profile, 'TASK', prefix + [op['task_id']],
                             {'PAY_TASK' if profile == 'PAY-1' else 'IND_TASK' if profile == 'IND-DEMO-1' else 'MED_TASK'})['record']
        schema.validate(policy, 'Record_POLICY'); schema.validate(task, 'Record_' + task['kind'])
        pv, tv = policy['value'], task['value']
        require_window(pv, event); require_window(tv, event)
        require(tv['task_id'] == op['task_id'] and tv['principal'] == action['principal'] and
                tv['holder'] == action['holder'] and tv['holder_kid'] == action['holder_kid'] and
                tv['executor'] == action['executor'], 'BINDING')
        behavior_key = prefix + [action['principal']]
        behavior = self._current(c, profile, 'BEHAVIOR', behavior_key,
                                 {'BEHAVIOR_STATE'} if profile == 'PAY-1' else {'BEHAVIOR'})
        schema.validate(behavior['record']['value'], 'BehaviorRow')
        br = behavior['record']['value']
        require(int(br['accepted_count']) < int(br['count_cap']), 'BEHAVIOR_LIMIT')
        require(br['inflight'] == sortset(br['inflight']) and oid not in br['inflight'], 'BEHAVIOR_INTEGRITY')
        next_behavior = deepcopy(br)
        next_behavior['accepted_count'] = str(int(br['accepted_count']) + 1)
        next_behavior['inflight'] = sortset(br['inflight'] + [oid])
        before_scene = after_scene = None
        if profile == 'PAY-1':
            require(op['scene_key'] == payload['order_id'] and
                    all(tv[k] == payload[k] for k in ('order_id', 'stage', 'payer')), 'BINDING')
            require(number(payload['amount_minor'], True), 'AMOUNT')
            intent = prefix + [payload['order_id'], payload['stage']]
            resource_key = prefix + [payload['payer'], payload['currency']]
            unit, amount, limit = 'CNY_MINOR', int(payload['amount_minor']), 10000
        else:
            namespace = SCENES[profile]
            expected_key = (prefix + [payload['line_id'], payload['unit_id']] if profile == 'IND-DEMO-1'
                            else prefix + [payload['synthetic_patient_id'], payload['encounter_id']])
            require(op['scene_key'] == expected_key, 'BINDING')
            scene = self._current(c, profile, namespace, expected_key, {namespace})
            sr = scene['record']['value']; schema.validate(sr, 'SceneRow')
            require(sr['state'] == 'READY', 'SCENE_NOT_READY')
            if profile == 'IND-DEMO-1':
                identity_key = prefix + [payload['unit_id']]
                identity = self._current(c, profile, 'IDENTITY', identity_key, {'IND_UNIT'})
                iv = identity['record']['value']
                require(sr['unit_ref'] == identity['ref'] and all(payload[k] == iv[k]
                        for k in ('unit_id', 'batch_id', 'line_id', 'station_id')), 'IDENTITY_BINDING')
                require(payload['phase'] == sr['phase'] and payload['inspection_cycle'] == sr['inspection_cycle'] and
                        payload['line_id'] == tv['line_id'] and payload['station_id'] == tv['station_id'], 'BINDING')
                allowed = {'unit_ref': sr['unit_ref'], 'unit_id': payload['unit_id'], 'batch_id': payload['batch_id'],
                           'inspection_cycle': payload['inspection_cycle'], 'phase': payload['phase']}
                require(allowed in tv['allowed_units'], 'BINDING')
                intent = prefix + [payload[k] for k in ('line_id', 'unit_id', 'inspection_cycle', 'phase')]
                resource_key = prefix + ['route-capacity', payload['line_id'], action['destination'], 'unit']
                unit, amount, limit = 'UNIT', 1, int(pv['capacity_per_destination'])
            else:
                identity_key = prefix + [payload['synthetic_patient_id'], payload['encounter_id']]
                identity = self._current(c, profile, 'IDENTITY', identity_key, {'MED_ENCOUNTER'})
                iv = identity['record']['value']
                require(sr['encounter_ref'] == identity['ref'] == tv['encounter_ref'] and
                        all(payload[k] == iv[k] == tv[k] for k in ('synthetic_patient_id', 'encounter_id')),
                        'IDENTITY_BINDING')
                require(payload['order_group_id'] == sr['order_group_id'] == tv['order_group_id'] and
                        payload['phase'] == sr['phase'] == tv['phase'], 'BINDING')
                intent = prefix + [payload[k] for k in ('synthetic_patient_id', 'encounter_id', 'order_group_id', 'phase')]
                resource_key = prefix + ['order-capacity', action['destination'], 'order']
                unit, amount, limit = 'ORDER', 1, int(pv['destination_capacity'])
            next_scene = deepcopy(sr); next_scene.update(state='ACCEPTED', operation_id=oid)
            before_scene = self._witness(namespace, expected_key, scene)
            after_scene = self._witness(namespace, expected_key, scene, after=next_scene)
            schema.validate(before_scene, 'SceneWitness'); schema.validate(after_scene, 'SceneWitness')
        before_behavior = self._witness('BEHAVIOR', behavior_key, behavior)
        after_behavior = self._witness('BEHAVIOR', behavior_key, behavior, after=next_behavior)
        schema.validate(before_behavior, 'BehaviorWitness'); schema.validate(after_behavior, 'BehaviorWitness')
        return {'intent': intent, 'resource_key': resource_key, 'unit': unit, 'amount': amount, 'limit': limit,
                'behavior_before': before_behavior, 'behavior_after': after_behavior,
                'taskflight': {'key': prefix + [op['task_id']], 'operation_id': oid},
                'scene_before': before_scene, 'scene_after': after_scene}

    def terminal(self, profile, scene_record, outcome: str, *, action):
        """Return a legal original SceneRow terminal record for the frozen Action."""
        self._prefix(profile, action)
        require(outcome in ('SUCCEEDED', 'FAILED_CONFIRMED'), 'FINAL_OUTCOME')
        if profile == 'PAY-1':
            require(scene_record is None, 'SCENE_PROFILE')
            return None
        schema = self.state.schemas[profile]; schema.validate(action, 'Action')
        require(type(scene_record) is dict and set(scene_record) == {'version', 'profile', 'kind', 'scope', 'value'} and
                (scene_record['version'], scene_record['profile'], scene_record['scope'], scene_record['kind']) ==
                ('2.6', profile, action['scope'], SCENES[profile]), 'OBJECT_KIND')
        row = scene_record['value']; schema.validate(row, 'SceneRow')
        require(row['operation_id'] == action['operation_id'] and row['state'] in ('ACCEPTED', 'EFFECT_UNKNOWN'), 'STALE_SCENE')
        payload = action['payload']
        if profile == 'IND-DEMO-1':
            require(row['phase'] == payload['phase'] and row['inspection_cycle'] == payload['inspection_cycle'], 'BINDING')
            success = {'RELEASE': 'RELEASED', 'QUARANTINE': 'QUARANTINED', 'INSPECT': 'AWAITING_REINSPECT'}[payload['route']]
        else:
            require(row['phase'] == payload['phase'] and row['order_group_id'] == payload['order_group_id'], 'BINDING')
            success = 'REGISTERED'
        result = deepcopy(scene_record)
        result['value']['state'] = success if outcome == 'SUCCEEDED' else 'STOPPED'
        schema.validate(result['value'], 'SceneRow')
        return result
