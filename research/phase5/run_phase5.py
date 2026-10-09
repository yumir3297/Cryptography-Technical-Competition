"""Reproduce Phase-5 W transaction experiments + all earlier regression tests.

Optional --upstream-root verifies the exact original PAY JSON Schema blob and
executes full Draft-2020-12 structural checks on emitted signed artifacts.
When the file is unavailable, official verification is explicitly NOT_RUN.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import platform
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
import importlib.metadata
ROOT=Path(__file__).resolve().parents[2]
for patch in (str(ROOT),str(ROOT/'research'/'assurance')):
    if patch not in sys.path:sys.path.insert(0,patch)
from research.assurance import test_abstract_checker,test_deny_range_model
from research.reference_executor import test_reference
from research.strict_v26 import test_pay_history,test_pay_dependencies,test_upstream_schema
from research.strict_v26.upstream_schema import UpstreamSchema
from research.phase4 import test_flow
from research.phase4.flow import SignedPayFlow
from research.phase5 import test_durable_w
from research.phase5.durable_w import DurablePayW
from research.reference_executor.wire import rec_ref,msgref
from research.strict_v26.test_pay_history import case

HERE=Path(__file__).resolve().parent
EXPECTED_BLOB='86ba1bae0e4c455899af661bed44edfc5494aa5e'
UPSTREAM_COMMIT='0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c'


def schema_probe(root):
    if root is None:
        return None,{'status':'NOT_RUN_OFFICIAL_JSON_UNAVAILABLE','expected_git_blob_sha1':EXPECTED_BLOB}
    path=Path(root)/'system_dev/v26/contracts/pay1.schema.json'
    if not path.is_file():raise RuntimeError('Official PAY schema missing: '+str(path))
    content=path.read_bytes()
    blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
    if blob!=EXPECTED_BLOB:
        raise RuntimeError('Official PAY schema blob mismatch: expected '+EXPECTED_BLOB+', found '+blob)
    gate=UpstreamSchema(root,'PAY-1')
    return gate,{'status':'PINNED_OFFICIAL_JSON_AVAILABLE','path':str(path),'size_bytes':len(content),
                 'git_blob_sha1':blob}


def prepare_cases(cases,root=None):
    w=SignedPayFlow(cases=cases,schema_root=root)
    op=w.prepare()
    for purpose in op.required:w.review(op,purpose=purpose)
    w.authorize(op);w.issue(op);w.challenge(op)
    return w,op


def check_emitted(gate,w,op,result):
    objects=[('Record_POLICY',w.source['policy_record']),
             ('Record_PAY_TASK',w.source['task_record']),
             ('Record_PAY_EVIDENCE',w.source['evidence_record']),
             ('Record_PAY_HISTORY',w.source['history_record']),
             ('Record_ASSESSMENT',w.assessment_record),
             ('Record_BASIS',w.basis_record)]
    objects += [('Review',r) for r in op.reviews]
    objects += [('Authorization',op.authorization),('IssueRequest',op.issue),
                ('Permit',op.permit),('Result',w.issue_result),
                ('ChallengeRequest',op.challenge_request),('Challenge',op.challenge),
                ('CommitProof',op.proof),('Record_COMMIT',result['commit']),
                ('Acceptance',result['acceptance']),('Result',result['reply'])]
    for typ,o in objects:gate.validate(o,typ)
    return len(objects)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--upstream-root',type=Path,help='Checkout with unmodified pinned official PAY schema')
    args=parser.parse_args(argv)
    gate,schema=schema_probe(args.upstream_root)
    stream=io.StringIO()
    modules=[test_abstract_checker,test_deny_range_model,test_reference,
             test_pay_history,test_pay_dependencies,test_upstream_schema,test_flow,test_durable_w]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
    test_result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'phase5_test_log.txt').write_text(stream.getvalue(),encoding='utf-8')
    positive=[];official_checks=0
    if test_result.wasSuccessful():
        for label,cs in [('CLEAR',None),
                         ('FLAG',[case(i,action_class='HOLD' if i<=4 else 'PAY') for i in range(1,6)]),
                         ('INSUFFICIENT',[case(1),case(2)])]:
            f,op=prepare_cases(cs,args.upstream_root if gate else None)
            with tempfile.TemporaryDirectory() as d:
                authority=DurablePayW(Path(d)/'durable.sqlite')
                res=authority.accept(f,op)
                if gate:official_checks+=check_emitted(gate,f,op,res)
                state=authority.snapshot()
                replay_f,replay_op=prepare_cases(cs,args.upstream_root if gate else None)
                retry=DurablePayW(Path(d)/'durable.sqlite').accept(replay_f,replay_op)
                assert retry['idempotent']
                assert authority.snapshot()==state
                positive.append({'risk_result':label,'operation_id':op.action['operation_id'],
                    'authorization_review_purposes':list(op.required),
                    'permit_ref':msgref(op.permit),'commit_ref':rec_ref(res['commit']),
                    'acceptance_ref':msgref(res['acceptance']),
                    'single_accept_seq':state['accept_seq'],'reserved_minor':state['reserved'],
                    'after_replay_unchanged':True,'schema_validated':bool(gate)})
    if gate:schema.update(status='PINNED_OFFICIAL_JSON_VALIDATED',structural_checks=official_checks)
    total=test_result.testsRun; failures=len(test_result.failures);errors=len(test_result.errors);skipped=len(test_result.skipped)
    source_files=list(HERE.glob('*.py'))
    result={'contract':'ZJJ-CORE-2.6-R2','generated_at_utc':datetime.now(timezone.utc).isoformat(),
            'upstream_commit':UPSTREAM_COMMIT,'experiment_scope':'PHASE5_PAY1_SQLITE_DURABLE_ACCEPT_SUBSET',
            'suite':{'tests':total,'passed':total-failures-errors-skipped,'failed':failures,'errors':errors,'skipped':skipped},
            'official_json_schema':schema,
            'formal_official_semantic_cases':{'cases_total':39,'fully_executed':0,'passed':0,
                    'note':'This runner is not the official 39-case conformance harness.'},
            'positive_signed_durable_traces':positive,
            'fault_model':{'transactional_engine':'SQLite BEGIN IMMEDIATE/WAL/FULL','hard_process_exit_code':79,
                  'crash_points':['after_validation_before_write','after_SQL_writes_before_commit','after_commit_before_reply'],
                  'effect_of_test_process_exit':'evidence of SQLite transaction atomicity in the local test environment; not OS power failure or replicated durability'},
            'known_gaps':['Control C and source E authentication/legacy provenance remain Phase-4 trusted fixtures',
                  'Only one fixed PAY account / principal; no arbitrary operations or all PAY resource/behavior interleavings',
                  'Full required-dependency scope has no authenticated external current-state service',
                  'Dispatch claim uses a caller-supplied verified-witness fixture, not a production trust boundary',
                  'No persistent authenticated TOOL_FINAL/effect ledger or real effect exactly-once proof',
                  'SQL transaction rollback is validated, not power-loss fsync durability on all environments',
                  'When schema is NOT_RUN, no claim of official machine-contract validation',
                  'No complete official 39-case protocol semantic conformance or IND/MED strict implementation'],
            'environment':{'python':sys.version.split()[0],'platform':platform.platform(),
                    'sqlite':__import__('sqlite3').sqlite_version,
                    'cryptography':importlib.metadata.version('cryptography'),
                    'jsonschema':importlib.metadata.version('jsonschema')},
            'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}}
    (HERE/'phase5_validation_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'durable_signed_traces.json').write_text(json.dumps(positive,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'tests':result['suite'],'official_schema':schema,'positive_traces':len(positive),
         'official_full_conformance_passed':0,'report':'research/phase5/phase5_validation_report.json'},ensure_ascii=False))
    return 0 if test_result.wasSuccessful() and len(positive)==3 else 1

if __name__=='__main__':raise SystemExit(main())
