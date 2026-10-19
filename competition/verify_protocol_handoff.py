"""Selected handoff demonstrations; real signatures, unchanged common W.

Exports only public evidence. Existing W runs are verified separately and
are never rerun or overwritten by this module.
"""
import argparse
import json
from pathlib import Path

from competition.profiles.w_seed import initialize
from competition.support.artifact import build_identity, signed_messages_valid, write
from competition.run_w_slice import public_ledgers
from competition.support.wire import ProtocolError, raw, canonical, strict_verify

ROOT = Path(__file__).resolve().parents[1]


def rejected(call, expected):
    try:
        call()
    except ProtocolError as error:
        if error.code != expected:
            raise AssertionError((expected, error.code)) from error
        return error.code
    raise AssertionError('Expected refusal: ' + expected)


def run_all(output):
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for profile in ('IND-DEMO-1', 'PAY-1', 'MED-DEMO-1'):
        run = initialize(ROOT / '.runtime' / output.name / (profile + '-missing-review'))
        try:
            op = run.clone(profile)
            op['reviews'] = []
            run.base.resign_chain(profile, op)
            assert signed_messages_valid(run, profile, op)
            proof = run.identity_proof(profile, op)
            before = run.w.counts()
            reason = rejected(lambda: run.w.prepare(profile, op, proof), 'REVIEW_REQUIRED')
            after = run.w.counts()
            assert before == after and after['accepts'] == after['attempts'] == 0
            evidence = profile + '-missing-review.json'
            write(output / evidence, {
                'profile': profile, 'scenario': 'common_W_missing_review', 'status': 'PASS',
                'operation': op, 'identity_proof': proof, 'actual_signatures_valid': True,
                'reason': reason, 'before_counts': before, 'after_counts': after,
                'public_ledgers': public_ledgers(run),
                'scope': 'Refused at common W prepare; no accept/claim/execute attempted.'})
            cases.append({'profile': profile, 'scenario': 'common_W_missing_review',
                          'status': 'PASS', 'evidence': evidence})
        finally:
            run.close()

        run = initialize(ROOT / '.runtime' / output.name / (profile + '-reads'))
        try:
            op = run.operations[profile]
            oid = op['action']['operation_id']
            ticket = run.w.prepare(profile, op, run.identity_proof(profile, op))
            run.w.accept(profile, ticket['ticket_id'], run.accept_proof(profile, ticket['ticket_id']))
            before = run.w.counts()
            status_proof = run.read_proof(profile, oid)
            status = run.w.status(profile, oid, status_proof)
            audit = run.w.audit(profile, oid, run.read_proof(profile, oid, 'AUDIT'))
            assert status['view_kind'] == audit['view_kind'] == 'APPLICATION_W_PROJECTION'
            assert status['original_envelope'] is audit['original_envelope'] is False
            replay = rejected(lambda: run.w.status(profile, oid, status_proof), 'REPLAY')
            revoked_proof = run.read_proof(profile, oid)
            strict_verify(run.actors[profile]['H'].pub, raw(revoked_proof['signature'], 64),
                          canonical(['COMP-W-READ-v1', revoked_proof['claim']]))
            run.base.update_role(profile, 'H', False)
            revoked = rejected(lambda: run.w.status(profile, oid, revoked_proof), 'REVOKED')
            after = run.w.counts()
            assert before == after
            assert after['accepts'] == 1 and after['attempts'] == after['settlements'] == 0
            evidence = profile + '-authenticated-reads.json'
            write(output / evidence, {
                'profile': profile, 'scenario': 'authenticated_reads', 'status': 'PASS',
                'status_projection': status, 'audit_projection': audit,
                'replayed_status_proof': status_proof, 'replay_reason': replay,
                'valid_signed_proof_before_revocation': revoked_proof,
                'revoked_reason': revoked, 'before_counts': before, 'after_counts': after,
                'public_ledgers': public_ledgers(run),
                'scope': 'Current H local reads; read nonce/clock writes permitted; business counts unchanged.'})
            cases.append({'profile': profile, 'scenario': 'authenticated_reads',
                          'status': 'PASS', 'evidence': evidence})
        finally:
            run.close()
    report = {'kind': 'selected_protocol_handoff_demonstrations', 'build': build_identity(),
              'cases': cases, 'case_count': len(cases), 'passed': True,
              'limits': ['Trusted single-host bootstrap and three fixed synthetic Profiles.',
                         'Missing-review path is a common W entry refusal, not tool execution.',
                         'Reads are authenticated local application projections, not signed R2 Result/AUDITBundle.']}
    write(output / 'report.json', report)
    print(json.dumps({'passed': True, 'case_count': len(cases), 'output': str(output)}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run_all(args.output.resolve())
