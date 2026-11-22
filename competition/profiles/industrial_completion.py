"""One finite completion model for a C-certified industrial RELEASE task."""
import json

from competition.core.trusted_state import enc
from competition.support.wire import ProtocolError, digest, require


MODEL = 'release-all-initial-v1'
DOMAIN = 'ZJJ-IND-TASK-COMPLETION-v1'


def completion_basis(w, conn, profile, op, plan, resource, event):
    if profile != 'IND-DEMO-1':
        return None
    task_key = plan['taskflight']['key']
    task = w.state.current(conn, profile, 'TASK', task_key)
    value = task['record']['value']
    if 'completion_model' not in value:
        return None
    policy = w.state.current(conn, profile, 'POLICY', task_key[:-1])
    units = value['allowed_units']
    candidate = op['action']['payload']
    require(value['completion_model'] == MODEL and candidate['route'] == 'RELEASE' and
            all((u['phase'], u['inspection_cycle']) == ('INITIAL', '1') for u in units) and
            len({u['unit_id'] for u in units}) == len(units), 'TASK_COMPLETION_UNREACHABLE')
    require(task['ref'] == op['basis']['value']['task_ref'] and
            policy['ref'] == op['ctx']['policy_ref'], 'TASK_COMPLETION_BINDING')

    completed, path = [], []
    adapter = w.guard.adapters[profile]
    for unit in sorted(units, key=lambda u: (u['unit_id'] != candidate['unit_id'], u['unit_id'])):
        unit_id = unit['unit_id']
        key = task_key[:-1] + [value['line_id'], unit_id]
        scene = w.state.current(conn, profile, 'UNIT', key)
        row = scene['record']['value']
        require((row['unit_ref'], row['phase'], row['inspection_cycle']) ==
                (unit['unit_ref'], 'INITIAL', '1'), 'TASK_COMPLETION_UNREACHABLE')
        intent = key + ['1', 'INITIAL']
        prior = conn.execute('SELECT oid FROM w_intent WHERE profile=? AND intent=?',
                             (profile, enc(intent))).fetchone()
        if row['state'] == 'RELEASED':
            require(prior is not None and prior['oid'] == row['operation_id'], 'TASK_COMPLETION_UNREACHABLE')
            operation, frozen = w._operation(conn, profile, prior['oid'])
            final = conn.execute("SELECT fact_id FROM w_settlement WHERE profile=? AND oid=? AND outcome='SUCCEEDED'",
                                 (profile, prior['oid'])).fetchone()
            require(operation['state'] == 'SETTLED' and final is not None and
                    frozen['plan']['taskflight']['key'] == task_key and
                    frozen['op']['action']['payload']['route'] == 'RELEASE',
                    'TASK_COMPLETION_UNREACHABLE')
            completed.append({'unit_id': unit_id, 'scene_ref': scene['ref'],
                              'scene_revision': str(scene['revision']), 'scene_row': row,
                              'commit_ref': frozen['commit_ref'], 'final_fact_id': final['fact_id']})
        else:
            require(row['state'] == 'READY' and prior is None, 'TASK_COMPLETION_UNREACHABLE')
            try:
                path.append(adapter.release_step(conn, op, unit, event))
            except ProtocolError as exc:
                raise ProtocolError('TASK_COMPLETION_UNREACHABLE') from exc

    behavior = plan['behavior_before']
    require(path and path[0]['unit_id'] == candidate['unit_id'] and
            resource['reserved'] + resource['spent'] + len(path) <= resource['capacity'] and
            int(behavior['row']['accepted_count']) + len(path) <= int(behavior['row']['count_cap']),
            'TASK_COMPLETION_UNREACHABLE')
    return {
        'model': MODEL, 'ctx': op['ctx'], 'basis_record': op['basis'],
        'task_certificate': task['certificate'],
        'policy_certificate': policy['certificate'], 'completed': completed, 'path': path,
        'resource': {**{k: str(resource[k]) for k in ('revision', 'capacity', 'reserved', 'spent')},
                     'certificate': json.loads(resource['certificate']),
                     'commitments': [dict(row) for row in conn.execute(
                         "SELECT id,oid,CAST(amount AS TEXT) AS amount,state FROM w_reservation "
                         "WHERE profile=? AND key=? AND state IN ('RESERVED','SPENT') ORDER BY id",
                         (profile, enc(plan['resource_key'])))]},
        'behavior_before': behavior,
    }


def completion_ref(basis):
    return digest([DOMAIN, basis])
