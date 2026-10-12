"""Demonstrate the documented post-claim boundary on unchanged competition code."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from competition.profiles.w_seed import initialize
from competition.w_cases import accept_operation, tool_snapshot
from competition.run_w_slice import public_ledgers
from competition.support.wire import ProtocolError


def main():
    output = ROOT / 'competition/evidence/protocol-review-20261011-boundaries'
    output.mkdir(exist_ok=False)
    run = initialize(ROOT / '.runtime' / 'protocol-review-20261011-boundaries')
    cases = []
    try:
        for profile in ('IND-DEMO-1', 'PAY-1', 'MED-DEMO-1'):
            oid, _ = accept_operation(run, profile)
            claimed = run.w.claim(profile, oid, run.worker_proof(profile, oid, 'CLAIM'))
            run.base.update_role(profile, 'G', False)
            try:
                run.w.cancel(profile, oid, run.worker_proof(profile, oid, 'CANCEL'))
            except ProtocolError as error:
                cancel_reason = error.code
            else:
                raise AssertionError('STARTED must not cancel')
            assert cancel_reason == 'CANCEL_STARTED'
            response = run.w.execute_once(profile, oid, run.worker_proof(profile, oid, 'EXECUTE'))
            assert response['record']['value']['outcome'] == 'SUCCEEDED'
            settled = run.w.settle(profile, oid, response, run.worker_proof(profile, oid, 'SETTLE'))
            assert settled['state'] == 'SETTLED'
            before = run.w.counts()
            repeated = run.w.execute_once(profile, oid, run.worker_proof(profile, oid, 'EXECUTE'))
            status = run.w.status(profile, oid, run.read_proof(profile, oid))
            assert repeated['reason'] == 'EXEC_ALREADY_CONSUMED' and repeated['state'] == 'UNKNOWN'
            assert status['dispatch_state'] == 'SETTLED' and status['effect_state'] == 'SUCCEEDED'
            assert before == run.w.counts() and tool_snapshot(run, profile)['effect_count'] == 1
            filename = profile + '-post-claim-revocation.json'
            (output / filename).write_text(json.dumps({
                'profile': profile, 'operation_id': oid, 'claim': claimed,
                'G_role_revoked_after_claim': True, 'cancel_reason': cancel_reason,
                'response': response, 'settlement': settled,
                'repeated_exec_result': repeated, 'authoritative_local_status': status,
                'business_counts_before_repeat': before, 'business_counts_after_repeat': run.w.counts(),
                'public_ledgers': public_ledgers(run),
                'scope': 'Post-claim revocation does not retract granted dispatch; UNKNOWN call result does not replace SETTLED.'
            }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            cases.append({'profile': profile, 'evidence': filename, 'confirmed': True})
    finally:
        run.close()
    (output / 'report.json').write_text(json.dumps({
        'kind': 'confirmed_competition_execution_boundaries', 'cases': cases,
        'case_count': 3, 'all_expected_boundaries_confirmed': True,
        'classification': 'Observed behavior boundaries; not new R2 conformance or immediate-revocation guarantees.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'case_count': 3, 'all_expected_boundaries_confirmed': True}))


if __name__ == '__main__':
    main()
