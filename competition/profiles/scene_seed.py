"""Fresh synthetic IND/MED business records; controller grants are caller-owned.

The seed contains READY business state and a real E source attestation, never an
accepted transaction or publicly known fixture keys. State references use the
original ZJJ-STATE-v1 namespace/key/revision/value construction in the store.
"""
import os

from competition.support.scene_authority import PROFILES, DEST, MAPPING, TEMPLATES, _rec
from competition.support.wire import b64, canonical, rec_ref, require, sortset


def build_scene(profile, actors, scope, now, label=None):
    require(profile in PROFILES, 'PROFILE')
    require(type(now) is int and now >= 0, 'TIME_INTERVAL')
    require(scope['scenario'] == PROFILES[profile][0], 'WRONG_SCOPE')
    prefix = [scope[k] for k in ('domain', 'tenant', 'scenario')]
    rows = []
    new_id = lambda: b64(os.urandom(16))
    task_id, operation_id = new_id(), new_id()
    starts, expires = str(now), str(now + 1800)

    def add(namespace, key, kind, value):
        record = _rec(profile, kind, scope, value)
        rows.append({'namespace': namespace, 'key': key, 'record': record})
        return record

    base_policy = {
        'profile': profile, 'policy_revision': '1',
        'gateway': actors['G'].name, 'gateway_kid': actors['G'].kid,
        'executor': actors['X'].name, 'executor_kid': actors['X'].kid,
        'source': actors['E'].name, 'readers': sortset({a.name for a in actors.values()}),
        'tool_version': '1', 'controller': 'demo-controller',
        'history_mode': 'DISABLED', 'evidence_ttl_seconds': '300',
        'task_ttl_seconds': '900', 'behavior_count_cap': '32',
        'iat': starts, 'exp': expires,
    }
    base_task = {
        'task_id': task_id, 'task_revision': '1', 'principal': 'principal',
        'holder': actors['H'].name, 'holder_kid': actors['H'].kid,
        'executor': actors['X'].name, 'tool_version': '1',
        'max_inflight': '1', 'iat': starts, 'exp': str(now + 900),
    }
    if profile == 'IND-DEMO-1':
        label = label or 'DEMO_UNCERTAIN'
        require(label in MAPPING, 'CLAIM_FALSE')
        route = MAPPING[label]
        package = add('PACKAGE', prefix, 'IND_PACKAGE', {
            'package_id': 'ind-fixed-package-1', 'package_revision': '1',
            'detector': 'SYNTHETIC-LABEL-1', 'preprocessing': 'IDENTITY-1',
            'output_schema': 'IND-LABEL-V1', 'mapper': 'IND-ROUTE-V1',
            'label_routes': {'normal': 'RELEASE', 'defect': 'QUARANTINE', 'uncertain': 'INSPECT'},
            'iat': starts, 'exp': expires,
        })
        destinations = {'release': DEST['RELEASE'], 'quarantine': DEST['QUARANTINE'], 'inspect': DEST['INSPECT']}
        policy = add('POLICY', prefix, 'POLICY', {
            **base_policy, 'schema_version': 'ind-payload-v1', 'verifier_version': 'ind-fixed-v1',
            'tool': 'line-sort-sim', 'line_id': 'demo-line-a', 'station_id': 'demo-check-1',
            'route_destinations': destinations, 'decision_package_ref': rec_ref(package),
            'max_cycles': '2', 'capacity_per_destination': '8',
        })
        identity = add('IDENTITY', prefix + ['unit-a'], 'IND_UNIT', {
            'unit_id': 'unit-a', 'batch_id': 'batch-a', 'line_id': 'demo-line-a',
            'station_id': 'demo-check-1', 'synthetic': True, 'iat': starts, 'exp': expires,
        })
        scene_key = prefix + ['demo-line-a', 'unit-a']
        scene = {
            'unit_ref': rec_ref(identity), 'inspection_cycle': '1', 'phase': 'INITIAL',
            'state': 'READY', 'evidence_ref': '', 'operation_id': '',
            'predecessor_operation_id': '', 'predecessor_commit_ref': '',
        }
        data = {
            'evidence_id': new_id(), 'evidence_revision': '1', 'unit_ref': rec_ref(identity),
            'unit_id': 'unit-a', 'batch_id': 'batch-a', 'line_id': 'demo-line-a',
            'station_id': 'demo-check-1', 'inspection_cycle': '1', 'phase': 'INITIAL',
            'sampled_at': starts, 'known_at': starts, 'quality_flag': 'VALID', 'label': label,
        }
        task = {
            **base_task, 'policy_ref': rec_ref(policy), 'line_id': 'demo-line-a',
            'station_id': 'demo-check-1', 'allowed_units': [{
                'unit_ref': rec_ref(identity), 'unit_id': 'unit-a', 'batch_id': 'batch-a',
                'inspection_cycle': '1', 'phase': 'INITIAL',
            }], 'allowed_routes': ['INSPECT', 'QUARANTINE', 'RELEASE'],
            'tool': 'line-sort-sim', 'route_destinations': destinations,
        }
        payload = {
            'line_id': 'demo-line-a', 'station_id': 'demo-check-1', 'unit_id': 'unit-a',
            'batch_id': 'batch-a', 'inspection_cycle': '1', 'phase': 'INITIAL', 'route': route,
        }
        tool, destination = 'line-sort-sim', DEST[route]
    else:
        label = label or 'DEMO_A'
        require(label in TEMPLATES, 'CLAIM_FALSE')
        policy = add('POLICY', prefix, 'POLICY', {
            **base_policy, 'schema_version': 'med-payload-v1', 'verifier_version': 'med-fixed-v1',
            'tool': 'med-order-sim', 'destination': 'med-demo-ledger',
            'allowed_templates': ['DEMO-ORDER-A', 'DEMO-ORDER-B'],
            'template_mapping': {'demo_a': 'DEMO-ORDER-A', 'demo_b': 'DEMO-ORDER-B'},
            'required_review': 'CLINICAL_REVIEW', 'destination_capacity': '8',
            'max_groups_per_encounter': '1',
        })
        identity = add('IDENTITY', prefix + ['patient-a', 'encounter-a'], 'MED_ENCOUNTER', {
            'synthetic_patient_id': 'patient-a', 'encounter_id': 'encounter-a',
            'synthetic': True, 'iat': starts, 'exp': expires,
        })
        scene_key = prefix + ['patient-a', 'encounter-a']
        group_id = new_id()
        scene = {
            'encounter_ref': rec_ref(identity), 'order_group_id': group_id,
            'phase': 'SUBMIT', 'state': 'READY', 'evidence_ref': '', 'operation_id': '',
        }
        data = {
            'evidence_id': new_id(), 'evidence_revision': '1', 'record_id': 'record-a',
            'record_revision': '1', 'encounter_ref': rec_ref(identity),
            'synthetic_patient_id': 'patient-a', 'encounter_id': 'encounter-a',
            'record_status': 'AVAILABLE', 'completeness': 'COMPLETE',
            'event_at': starts, 'known_at': starts, 'template_label': label,
        }
        task = {
            **base_task, 'policy_ref': rec_ref(policy), 'encounter_ref': rec_ref(identity),
            'synthetic_patient_id': 'patient-a', 'encounter_id': 'encounter-a',
            'order_group_id': group_id, 'phase': 'SUBMIT',
            'allowed_templates': ['DEMO-ORDER-A', 'DEMO-ORDER-B'],
            'tool': 'med-order-sim', 'destination': 'med-demo-ledger',
        }
        payload = {
            'synthetic_patient_id': 'patient-a', 'encounter_id': 'encounter-a',
            'order_group_id': group_id, 'phase': 'SUBMIT', 'template_id': TEMPLATES[label],
            'record_ref': '', 'destination_system': 'med-demo-ledger',
        }
        tool, destination = 'med-order-sim', 'med-demo-ledger'

    source = actors['E']
    attestation = {'issuer': source.name, 'kid': source.kid, 'iat': starts, 'exp': str(now + 120)}
    signature = b64(source.key.sign(canonical([
        'ZJJ-SOURCE-v1', '2.6', profile, PROFILES[profile][1], scope, data, attestation,
    ])))
    evidence = add('EVIDENCE', scene_key, PROFILES[profile][1], {
        'data': data, 'attestation': {**attestation, 'sig': signature},
    })
    evidence_ref = rec_ref(evidence)
    scene['evidence_ref'] = evidence_ref
    if profile == 'MED-DEMO-1':
        payload['record_ref'] = evidence_ref
    add('TASK', prefix + [task_id], PROFILES[profile][3], task)
    add(PROFILES[profile][2], scene_key, PROFILES[profile][2], scene)
    add('BEHAVIOR', prefix + ['principal'], 'BEHAVIOR', {
        'accepted_count': '0', 'count_cap': '32', 'inflight': [],
    })
    action = {
        'scope': scope, 'operation_id': operation_id, 'principal': 'principal',
        'holder': actors['H'].name, 'holder_kid': actors['H'].kid,
        'executor': actors['X'].name, 'tool': tool, 'tool_version': '1',
        'destination': destination, 'payload': payload,
    }
    return {'rows': rows, 'action': action, 'task_id': task_id, 'scene_key': scene_key}
