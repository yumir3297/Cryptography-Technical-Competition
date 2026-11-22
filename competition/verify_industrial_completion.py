"""Offline reproduction of the industrial completion decision from a W audit."""
import argparse
import json
from pathlib import Path

from competition.core.event_clock import require_window
from competition.profiles.industrial_completion import MODEL, completion_ref
from competition.support.scene_authority import DEST
from competition.support.schema import CompetitionSchema
from competition.support.wire import (
    ProtocolError, action_hash, canonical, digest, keyid, raw, rec_ref, require, strict_verify,
)


PROFILE = 'IND-DEMO-1'


def verify(audit, *, c_public, x_public, e_public):
    """Use separately pinned C/X/E keys and X's attestation of W's snapshot."""
    try:
        return _verify(audit, c_public, x_public, e_public)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        if isinstance(exc, ProtocolError):
            raise
        raise ProtocolError('COMPLETION_EVIDENCE_FORMAT') from exc


def _verify(audit, c_public, x_public, e_public):
    receipt, commit, evidence = (audit[k] for k in ('acceptance', 'commit', 'completion_basis'))
    schema = CompetitionSchema(Path(__file__).resolve().parents[1], PROFILE)
    schema.validate(receipt, 'Acceptance')
    schema.validate(commit, 'Record_COMMIT')
    header, body = receipt['protected'], receipt['body']
    strict_verify(x_public, raw(receipt['sig'], 64), canonical(['ZJJ-SIG-v1', header, body]))
    cv, payload = commit['value'], body['payload']
    action, ctx = cv['action'], cv['ctx']
    scope = commit['scope']
    require(body['scope'] == scope == ctx['scope'] == action['scope'] and
            header['kid'] == keyid(x_public) and header['issuer'] == action['executor'] and
            raw(cv['signing_public_key'], 32) == x_public and
            payload['commit_record_ref'] == rec_ref(commit) and
            all(payload[k] == cv[k] for k in ('ctx', 'accept_seq', 'accepted_at', 'permit_ref',
                                             'proof_ref', 'authorization_ref', 'review_refs', 'dispatch_before')) and
            ctx == evidence['ctx'] and ctx['action_hash'] == action_hash(PROFILE, action) and
            ctx['operation_id'] == action['operation_id'] and
            cv['completion_ref'] == completion_ref(evidence), 'COMPLETION_BINDING')
    prefix = [scope[k] for k in ('domain', 'tenant', 'scenario')]
    event = {k: int(cv['trusted_time'][k]) for k in ('lo', 'hi')}
    task_key = cv['taskflight']['key']
    require(task_key[:-1] == prefix and cv['taskflight']['operation_id'] ==
            action['operation_id'], 'COMPLETION_BINDING')
    records = {}
    for ns, key, kind in (('TASK', task_key, 'IND_TASK'), ('POLICY', prefix, 'POLICY')):
        cert = evidence[ns.lower() + '_certificate']
        claim = cert['claim']
        strict_verify(c_public, raw(cert['signature'], 64), canonical(['COMP-APP-C-PUBLISH-v1', claim]))
        record = claim['record']
        schema.validate(record, 'Record_' + kind)
        require((claim['profile'], claim['scope'], claim['namespace'], claim['key'], claim['active']) ==
                (PROFILE, scope, ns, key, True) and record['scope'] == scope, 'COMPLETION_CONTROL')
        require({'namespace': ns, 'key': key, 'ref': rec_ref(record),
                 'revision': str(int(claim['previous_revision']) + 1)} in cv['checked_deps'],
                'COMPLETION_CONTROL')
        require_window(record['value'], event)
        records[ns] = record
    task, policy = (records[k]['value'] for k in ('TASK', 'POLICY'))
    basis = evidence['basis_record']
    schema.validate(basis, 'Record_BASIS')
    require_window(basis['value'], event)
    require(rec_ref(basis) == ctx['basis_ref'] and basis['value']['action'] == action and
            basis['value']['task_ref'] == rec_ref(records['TASK']) and
            basis['value']['policy_ref'] == task['policy_ref'] == ctx['policy_ref'] ==
            rec_ref(records['POLICY']), 'COMPLETION_BINDING')
    candidate = action['payload']
    require(evidence['model'] == task['completion_model'] == MODEL and
            task['task_id'] == task_key[-1] and task['principal'] == action['principal'] and
            task['line_id'] == policy['line_id'] == candidate['line_id'] and
            task['station_id'] == policy['station_id'] == candidate['station_id'] and
            'RELEASE' in task['allowed_routes'] and candidate['route'] == 'RELEASE' and
            action['destination'] == DEST['RELEASE'], 'COMPLETION_MODEL')
    units = {u['unit_id']: u for u in task['allowed_units']}
    path, done = evidence['path'], evidence['completed']
    ids = [step['unit_id'] for step in path + done]
    require(len(units) == len(task['allowed_units']) == len(ids) == len(set(ids)) and
            set(ids) == set(units) and path and path[0]['unit_id'] == candidate['unit_id'],
            'COMPLETION_PATH')
    for step in path + done:
        unit_id, row = step['unit_id'], step['scene_row']
        unit = units[unit_id]
        key = prefix + [task['line_id'], unit_id]
        schema.validate(row, 'SceneRow')
        require(unit['phase'] == row['phase'] == 'INITIAL' and
                unit['inspection_cycle'] == row['inspection_cycle'] == '1' and
                row['unit_ref'] == unit['unit_ref'] and step['scene_ref'] ==
                digest(['ZJJ-STATE-v1', 'UNIT', key, step['scene_revision'], row]), 'COMPLETION_PATH')
        if step in done:
            require(row['state'] == 'RELEASED', 'COMPLETION_PATH')
            raw(step['commit_ref'], 32)
            raw(step['final_fact_id'], 32)
            continue
        source = step['evidence']
        schema.validate(source, 'Record_IND_EVIDENCE')
        data, attestation = (source['value'][k] for k in ('data', 'attestation'))
        header = {k: attestation[k] for k in ('issuer', 'kid', 'iat', 'exp')}
        strict_verify(e_public, raw(attestation['sig'], 64),
                      canonical(['ZJJ-SOURCE-v1', '2.6', PROFILE, 'IND_EVIDENCE', scope, data, header]))
        require_window(header, event)
        require(row['state'] == 'READY' and row['evidence_ref'] == rec_ref(source) and
                source['scope'] == scope and header['issuer'] == policy['source'] and
                header['kid'] == keyid(e_public) and
                (data['unit_id'], data['unit_ref'], data['batch_id'], data['phase'], data['inspection_cycle'],
                 data['line_id'], data['station_id'], data['quality_flag'], data['label']) ==
                (unit_id, unit['unit_ref'], unit['batch_id'], 'INITIAL', '1', task['line_id'],
                 task['station_id'], 'VALID', 'DEMO_NORMAL') and
                int(data['sampled_at']) <= int(data['known_at']) <= int(header['iat']) and
                int(header['exp']) <= int(data['sampled_at']) + 300 and
                event['hi'] < int(step['expires']), 'COMPLETION_PATH')
    require(path[0]['scene_ref'] == cv['scene_before']['ref'] and
            [rec_ref(path[0]['evidence'])] == basis['value']['evidence_refs'] and
            candidate['batch_id'] == units[candidate['unit_id']]['batch_id'], 'COMPLETION_BINDING')

    resource, reservation = evidence['resource'], cv['reservation_plan'][0]
    cert = resource['certificate']
    claim = cert['claim']
    strict_verify(c_public, raw(cert['signature'], 64), canonical(['COMP-W-RESOURCE-v1', claim]))
    require((claim['profile'], claim['scope'], claim['unit'], claim['active'], claim['key']) ==
            (PROFILE, scope, 'UNIT', True, prefix + ['route-capacity', task['line_id'], DEST['RELEASE'], 'unit']) and
            claim['capacity'] == resource['capacity'] == reservation['capacity_before'] and
            reservation['key'] == claim['key'] and reservation['amount'] == '1' and
            reservation['revision_before'] == resource['revision'] and
            reservation['reserved_before'] == resource['reserved'] and
            reservation['spent_before'] == resource['spent'] and
            evidence['behavior_before'] == cv['behavior_before'], 'COMPLETION_RESOURCE')
    commitments = resource['commitments']
    require(len({r['id'] for r in commitments}) == len(commitments) and
            all(r['amount'] == '1' and r['state'] in ('RESERVED', 'SPENT') for r in commitments),
            'COMPLETION_RESOURCE')
    reserved, spent, capacity = (int(resource[k]) for k in ('reserved', 'spent', 'capacity'))
    behavior = cv['behavior_before']['row']
    require(reserved == sum(r['state'] == 'RESERVED' for r in commitments) and
            spent == sum(r['state'] == 'SPENT' for r in commitments) and
            reserved + spent + len(path) <= capacity <= int(policy['capacity_per_destination']) and
            int(behavior['accepted_count']) + len(path) <= int(behavior['count_cap']),
            'TASK_COMPLETION_UNREACHABLE')
    return {'operation_id': action['operation_id'], 'task_ref': basis['value']['task_ref'],
            'path': [step['unit_id'] for step in path]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', type=Path)
    for actor in ('c', 'x', 'e'):
        parser.add_argument('--' + actor + '-public', required=True, help='Pinned base64url public key')
    args = parser.parse_args()
    try:
        result = verify(json.loads(args.audit.read_text(encoding='utf-8')),
                        c_public=raw(args.c_public, 32), x_public=raw(args.x_public, 32),
                        e_public=raw(args.e_public, 32))
    except (ProtocolError, ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
