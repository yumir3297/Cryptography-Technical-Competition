"""Reproducible signed PAY end-to-end study; emits scoped claims only."""
from __future__ import annotations
import argparse, io, json, sys, hashlib, platform, unittest, importlib.metadata
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
for path in [str(ROOT),str(ROOT/'research'/'assurance')]:
    if path not in sys.path:sys.path.insert(0,path)
from research.assurance import test_abstract_checker,test_deny_range_model
from research.reference_executor import test_reference
from research.strict_v26 import test_pay_history,test_pay_dependencies,test_upstream_schema
from research.phase4 import test_flow
from research.phase4.flow import SignedPayFlow
from research.strict_v26.test_pay_history import case
from research.reference_executor.wire import rec_ref,msgref,canonical,ProtocolError
from research.strict_v26.upstream_schema import UpstreamSchema

SOURCE_HEAD='0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c'
OFFICIAL_SCHEMA_GIT_BLOB='86ba1bae0e4c455899af661bed44edfc5494aa5e'

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--upstream-root',type=Path, help='Path to repository checkout containing original system_dev/v26/contracts/pay1.schema.json')
    args=parser.parse_args(argv)
    # Official schema should not be silently replaced with a synthetic subset.
    schema_status='SKIPPED_OFFICIAL_SCHEMA_NOT_INSTALLED'
    schema_root=None
    candidate_root=args.upstream_root or ROOT
    check=candidate_root/'system_dev/v26/contracts/pay1.schema.json'
    if check.is_file():
        buf=check.read_bytes()
        sha=hashlib.sha1(b'blob '+str(len(buf)).encode()+b'\0'+buf).hexdigest()
        if sha!=OFFICIAL_SCHEMA_GIT_BLOB:
            raise SystemExit('expected pinned upstream PAY schema blob '+OFFICIAL_SCHEMA_GIT_BLOB+', found '+sha)
        schema_root=candidate_root
        UpstreamSchema(schema_root,'PAY-1')
        schema_status='PINNED_OFFICIAL_SCHEMA_ACTIVE'
    elif args.upstream_root is not None:
        raise SystemExit('official schema file missing: '+str(check))

    stream=io.StringIO()
    modules=[test_reference,test_pay_history,test_pay_dependencies,test_upstream_schema,
             test_abstract_checker,test_deny_range_model,test_flow]
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules])
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'test_log.txt').write_text(stream.getvalue(),encoding='utf-8')

    traces=[];samples=[]
    if result.wasSuccessful():
        for label,cs in [('CLEAR',None),('FLAG',[case(i,action_class='HOLD' if i<=4 else 'PAY') for i in range(1,6)]),
                          ('INSUFFICIENT',[case(1),case(2)])]:
            w=SignedPayFlow(cases=cs,schema_root=schema_root)
            op=w.prepare()
            for purpose in op.required:w.review(op,purpose=purpose)
            w.authorize(op)
            w.issue(op)
            w.challenge(op)
            proof=w.make_proof(op)
            acc=w.commit(op,proof)
            assert w.verify_archive(op)
            first_state={'accepted':w.sequence,'reserved':w.reserved,'spent':w.spent,'status':op.status}
            w.claim(op)
            fact=w.tool_fact(op)
            first=w.receive_final(op,w.certify_fact(op,fact))
            w.now+=1;w.rotate_tool(50,True)
            second=w.receive_final(op,w.certify_fact(op,fact))
            assert first=='SETTLED' and second=='EXISTING'
            traces.append({'risk_result':label,'operation_id':op.action['operation_id'],
                'required_reviews':list(op.required),'phase3_assessment_ref':rec_ref(w.assessment_record),
                'basis_ref':rec_ref(w.basis_record),'permit_ref':msgref(op.permit),
                'commit_ref':rec_ref(w.commit_record),'acceptance_ref':msgref(acc),
                'issue_result_ref':msgref(w.issue_result),'commit_result_ref':msgref(w.commit_result),
                'initial_W_after_acceptance':first_state,
                'after_first_final':first,'after_re_attestation':second,
                'final_W':{'reserved':w.reserved,'spent':w.spent,'settlements':op.settlements,'status':op.status},
                'original_message_rounds':10,'note':'in-memory fixture; not upstream formal conformance'})
            samples.append({'risk_result':label,'public_key_b64':{k:__import__('research.reference_executor.wire',fromlist=['b64']).b64(w.idents[k].pub) for k in ['H','G','X','U','E','V']},
                'trusted_RECORD_Fixtures':{k:w.source[k] for k in ['policy_record','task_record','evidence_record','history_record']},
                'assessment':w.assessment_record,'basis':w.basis_record,
                'envelopes':{'reviews':op.reviews,'authorization':op.authorization,'issue_request':op.issue,
                  'permit':op.permit,'issue_result':w.issue_result,'challenge_request':op.challenge_request,
                  'challenge':op.challenge,'commit_proof':op.proof,'acceptance':op.acceptance,
                  'commit_result':w.commit_result},
                'commit_record':w.commit_record,
                'notice':'public deterministic test keys, no real C/legacy provenance or durable W'})
    (HERE/'signed_pay_traces.json').write_text(json.dumps(traces,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (HERE/'signed_pay_artifacts.json').write_text(json.dumps(samples,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    sources=list(HERE.glob('*.py'))
    checks={'test_count':result.testsRun,'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
            'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}
    out={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'protocol':'ZJJ-CORE-2.6-R2',
         'target_head':SOURCE_HEAD,'suite':checks,'official_schema':{'status':schema_status,'pinned_blob_sha1':OFFICIAL_SCHEMA_GIT_BLOB},
         'official_full_conformance':{'passed':0,'official_semantic_cases_executed':0,
              'note':'No official semantic_cases.json harness or full trusted actor/transaction implementation'},
         'result_scope':'OFFLINE_SIGNED_PAY1_IN_MEMORY_INTEGRATION_SUBSET',
         'positive_traces':[x['risk_result'] for x in traces],
         'environment':{'python':sys.version.split()[0], 'platform':platform.platform(),
                         'cryptography':importlib.metadata.version('cryptography'),
                         'jsonschema':importlib.metadata.version('jsonschema')},
         'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
         'limits':['C control publication and historic provenance provided as trusted fixtures',
                 'W state and resource/nonce/intent transitions in-process RLock, no durable DB isolation/crash verification',
                 'PAY complete v2.5 legacy dependency and signing-authority snapshot not independently verified',
                 'Current key role checks are a selected PAY RequiredDeps closure, not all transitive witness edges',
                 'Pending vs started retrieval, cross-operation ledger continuity and C key rotation not complete',
                 'Remaining IND/MED Profiles use older illustrative ReferenceW, not this strict PAY integration',
                 'No actual payment or tool effect; finite tests not proof of universal security']}
    (HERE/'validation_report.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'test_suite':checks,'schema_status':schema_status,
            'traces':len(traces),'official_full_conformance_pass':0,
            'report':'research/phase4/validation_report.json'},ensure_ascii=False))
    return 0 if result.wasSuccessful() and len(traces)==3 else 1

if __name__=='__main__':raise SystemExit(main())
