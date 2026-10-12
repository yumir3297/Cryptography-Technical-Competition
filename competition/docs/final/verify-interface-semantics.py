"""Check internal interface signatures and ambiguous responses on real W/tool state."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from competition.core.common_w import CommonW
from competition.profiles.w_seed import initialize
from competition.w_cases import accept_operation, public_snapshot, tool_snapshot
from competition.support.wire import ProtocolError, b64


def main():
    output = ROOT / 'competition/evidence/interface-review-20261011'
    output.mkdir(exist_ok=False)
    run = initialize(ROOT / '.runtime/interface-review-20261011')
    cases = []
    def save(name, data):
        filename = name + '.json'
        (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        cases.append({'case': name, 'confirmed': True, 'evidence': filename})
    def reject(call):
        try:
            call()
        except ProtocolError as error:
            return error.code
        raise AssertionError('Expected rejection')
    try:
        names = ('prepare', 'accept', 'claim', 'execute_once', 'query_attempt', 'settle', 'status', 'audit',
                 'challenge_accept', 'challenge_worker', 'challenge_read', 'cancel', 'complete_receipt')
        signatures = {name: str(inspect.signature(getattr(CommonW, name))) for name in names}
        bad_keyword = False
        try:
            inspect.signature(CommonW.prepare).bind(None, 'PAY-1', {}, identity_proof={})
        except TypeError:
            bad_keyword = True
        assert bad_keyword
        save('actual-signatures', {'signatures': signatures,
             'identity_proof_keyword_is_not_actual_prepare_parameter': bad_keyword,
             'scope': 'Introspection only; actual parameter is identity.'})

        p = 'PAY-1'
        oid, _ = accept_operation(run, p)
        claimed = run.w.claim(p, oid, run.worker_proof(p, oid, 'CLAIM'))
        real_gateway = run.w.tool_gateways[p]
        class BadReply:
            def execute(self, packet):
                result = copy.deepcopy(real_gateway.execute(packet))
                result['record']['value']['attestation']['sig'] = b64(bytes(64))
                return result
        run.w.tool_gateways[p] = BadReply()
        response = run.w.execute_once(p, oid, run.worker_proof(p, oid, 'EXECUTE'))
        status = run.w.status(p, oid, run.read_proof(p, oid))
        assert response['state'] == 'SUCCEEDED' and response.get('validation_error')
        assert status['effect_state'] == 'UNKNOWN' and run.w.counts()['settlements'] == 0
        assert tool_snapshot(run, p)['effect_count'] == 1
        save('invalid-tool-response-label', {'response': response, 'status': status,
             'snapshot': public_snapshot(run, p, oid),
             'scope': 'Controlled response signature corruption after a real tool effect; untrusted success label is retained but not accepted by W.'})

        run.w.tool_gateways[p] = real_gateway
        valid = run.w.query_attempt(p, oid, run.worker_proof(p, oid, 'QUERY'))
        before = run.w.counts()
        bare_record = run.w.settle(p, oid, valid['record'], run.worker_proof(p, oid, 'SETTLE'))
        assert bare_record['state'] == 'UNKNOWN' and run.w.counts() == before
        save('bare-record-is-not-settle-response', {'result': bare_record, 'before': before,
             'after': run.w.counts(), 'scope': 'Bare TOOL_FINAL lacks response.record; current method takes the unknown branch.'})
        reason = reject(lambda: run.w.settle(p, oid, {'record': valid['record']},
                                             run.worker_proof(p, oid, 'SETTLE')))
        assert reason == 'LEDGER_CHECKPOINT_UNKNOWN' and run.w.counts() == before
        save('settle-requires-checkpoint', {'reason': reason, 'before': before,
             'after': run.w.counts(), 'scope': 'Record wrapper without checkpoint cannot settle.'})
        run.w.settle(p, oid, valid, run.worker_proof(p, oid, 'SETTLE'))
        repeated = run.w.claim(p, oid, run.worker_proof(p, oid, 'CLAIM'))
        status = run.w.status(p, oid, run.read_proof(p, oid))
        assert repeated['dispatch_state'] == 'STARTED' and repeated['attempt_id'] == claimed['attempt_id']
        assert status['dispatch_state'] == 'SETTLED'
        save('claim-retrieves-outbox-not-operation-state', {'repeated_claim': repeated, 'status': status,
             'core_request_attempt_id': run.operations[p]['proof']['body']['payload']['attempt_id'],
             'tool_dispatch_attempt_id': claimed['attempt_id'], 'snapshot': public_snapshot(run, p, oid)})

        p = 'MED-DEMO-1'
        oid, _ = accept_operation(run, p)
        reason = reject(lambda: run.w.audit(p, oid, run.worker_proof(p, oid, 'AUDIT')))
        save('audit-authenticates-holder-not-worker', {'reason': reason,
             'scope': 'Genuine worker AUDIT proof is not the H COMP-W-READ-v1 proof required by audit.'})
        before = run.w.counts()
        with run.store.tx() as c:
            c.execute('DELETE FROM w_flight WHERE profile=? AND oid=?', (p, oid))
        reason = reject(lambda: run.w.claim(p, oid, run.worker_proof(p, oid, 'CLAIM')))
        status = run.w.status(p, oid, run.read_proof(p, oid))
        assert reason == 'FLIGHT_OWNERSHIP' and status['dispatch_state'] == 'PENDING'
        assert run.w.counts()['halts'] == before['halts'] and run.w.counts()['attempts'] == before['attempts']
        save('ownership-exception-does-not-persist-halted', {'reason': reason, 'status': status,
             'snapshot': public_snapshot(run, p, oid),
             'scope': 'Explicit trusted test perturbation of a Flight row; not a demonstrated remote corruption attack.'})
    finally:
        run.close()
    runtime = ROOT / 'competition/core/common_w.py'
    report = {'kind': 'internal_interface_semantics_review', 'confirmed_cases': len(cases), 'cases': cases,
              'passed': True, 'build_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'common_w_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
              'limits': ['Selected internal method cases; no HTTP adapter or complete R2 conformance assertion.',
                         'Controlled malformed response and ledger perturbation remain explicitly identified.']}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'confirmed_cases': len(cases)}))


if __name__ == '__main__':
    main()
