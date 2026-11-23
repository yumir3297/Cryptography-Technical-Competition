"""Child-process crash points for the crash-consistency experiment.

The parent saves a public recovery fixture; this module reopens the authentic
ledgers and exits at one controlled persistence boundary.  It is never imported
by the served protocol.
"""
import sys
from pathlib import Path

from competition.w_cases import recover_fixture


def main(argv):
    if len(argv) != 2:
        raise SystemExit('usage: crash_child <fixture.json> <accept|exec|settle>')
    fixture, mode = argv
    run = recover_fixture(fixture)
    profile = 'IND-DEMO-1'
    op = run.operations[profile]
    oid = op['action']['operation_id']
    if mode == 'accept':
        ticket = run.w.prepare(profile, op, run.identity_proof(profile, op))
        run.w.accept(profile, ticket['ticket_id'], run.accept_proof(profile, ticket['ticket_id']),
                     crash_after_commit=True)
    if mode == 'exec':
        try:
            ticket = run.w.prepare(profile, op, run.identity_proof(profile, op))
            run.w.accept(profile, ticket['ticket_id'], run.accept_proof(profile, ticket['ticket_id']))
        except Exception:
            pass
        run.w.claim(profile, oid, run.worker_proof(profile, oid, 'CLAIM'))
        run.w.execute_once(profile, oid, run.worker_proof(profile, oid, 'EXECUTE'),
                           crash_after_marker=True)
    if mode == 'settle':
        try:
            ticket = run.w.prepare(profile, op, run.identity_proof(profile, op))
            run.w.accept(profile, ticket['ticket_id'], run.accept_proof(profile, ticket['ticket_id']))
        except Exception:
            pass
        run.w.claim(profile, oid, run.worker_proof(profile, oid, 'CLAIM'))
        response = run.w.execute_once(profile, oid, run.worker_proof(profile, oid, 'EXECUTE'))
        run.w.settle(profile, oid, response, run.worker_proof(profile, oid, 'SETTLE'),
                     crash_after_settlement=True)
    raise SystemExit('mode did not reach a crash point')


if __name__ == '__main__':
    main(sys.argv[1:])
