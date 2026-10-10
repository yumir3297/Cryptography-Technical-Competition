"""Run phase3 research tests and produce an explicit nonconformance report."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,importlib.metadata,io,json,platform,sys,unittest
ROOT=Path(__file__).resolve().parents[2]
ASSURANCE=ROOT/'research'/'assurance'
for path in (str(ROOT),str(ASSURANCE)):
    if path not in sys.path:sys.path.insert(0,path)

from research.strict_v26 import (test_pay_history,test_pay_dependencies,test_upstream_schema)
from research.reference_executor import test_reference
from research.assurance import test_abstract_checker,test_deny_range_model
from research.strict_v26.test_pay_history import bundle,case,run
from research.strict_v26.test_pay_dependencies import setup
from research.strict_v26.pay_dependencies import required_pay_deps
from research.strict_v26.upstream_schema import UpstreamSchema
from research.reference_executor.wire import ProtocolError,rec_ref,digest
from research.reference_executor.coverage import matrix

HERE=Path(__file__).resolve().parent


def run_all():
    loader=unittest.defaultTestLoader
    units=[test_reference,test_pay_history,test_pay_dependencies,test_upstream_schema,
           test_abstract_checker,test_deny_range_model]
    suite=unittest.TestSuite([loader.loadTestsFromModule(mod) for mod in units])
    stream=io.StringIO()
    res=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'phase3_test_log.txt').write_text(stream.getvalue(),encoding='utf-8')

    cases=[('CLEAR',[case(i) for i in range(1,4)]),
           ('FLAG',[case(i,action_class='HOLD') for i in range(1,5)]+[case(5)]),
           ('INSUFFICIENT',[case(1),case(2)])]
    vectors=[]
    for label,items in cases:
        bundle_in=bundle(items);risk,assessment=run(bundle_in)
        assert label==risk.result
        bad=dict(assessment,result='CLEAR' if label!='CLEAR' else 'FLAG')
        try:run({**bundle_in,'claimed_assessment':bad});tamper='INVALID_ACCEPTED'
        except ProtocolError as e:tamper=e.code
        assert tamper=='ASSESSMENT_MISMATCH'
        b,s,ids,signers=setup(label!='CLEAR')
        if label=='CLEAR':deps=required_pay_deps(s,b['action'],b['task_record']['value']['task_id'],signers,False,100)
        else:deps=required_pay_deps(s,b['action'],b['task_record']['value']['task_id'],signers,True,100)
        vectors.append({'case':label,'risk_result':risk.result,'ratio_feature':risk.feature,
                        'selected_cases':list(risk.selected_cases),'support':risk.support,'different':risk.different,
                        'required_reviews':list(risk.required_reviews),
                        'independently_derived_dep_count':len(deps),
                        'tampered_result_rejection':tamper,
                        'source_record_ref':rec_ref(bundle_in['evidence_record']),
                        'history_record_ref':rec_ref(bundle_in['history_record']),
                        'assessment_candidate':assessment,
                        'limits':'C publication authenticity and v2.5 historical credential graph are fixtures; no full official conformance'})
    (HERE/'pay_profile_traces.json').write_text(json.dumps(vectors,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    schema_probes={}
    for name,defname in [('policy','Record_POLICY'),('task','Record_PAY_TASK'),('history','Record_PAY_HISTORY'),('evidence','Record_PAY_EVIDENCE'),('assessment','Record_ASSESSMENT')]:
        try:
            official=UpstreamSchema(ROOT,'PAY-1')
            source=bundle()
            obj={'policy':source['policy_record'],'task':source['task_record'],
                 'history':source['history_record'],'evidence':source['evidence_record']}.get(name)
            if name=='assessment':
                _,a=run(source)
                obj={'version':'2.6','profile':'PAY-1','kind':'ASSESSMENT','scope':source['scope'],'value':a}
            official.validate(obj,defname)
            schema_probes[name]={'status':'PASS_UPSTREAM_SCHEMA','schema_file':str(official.path)}
        except ProtocolError as e:
            schema_probes[name]={'status':'SKIPPED_NO_UPSTREAM_SCHEMA' if e.code=='SCHEMA_NOT_INSTALLED' else 'FAIL_UPSTREAM_SCHEMA',
                                 'detail':e.code}
    (HERE/'official_schema_probes.json').write_text(json.dumps(schema_probes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    current_coverage=matrix(ROOT)
    supplemented={
        'CORE-03':'Independently derived PAY seven-namespace closure from trusted rows; requires end-to-end graph/transaction test',
        'CORE-05':'PAY trusted row revisions and persistent tombstone behavior in in-memory model',
        'CORE-07':'PAY U/G and U/V subject separation and current ROLE/KEY grant checks on fixture',
        'CORE-20':'G/X frozen kid binding to trusted PAY policy; no C root rotation implementation',
        'PAY-01':'CALCULATED CLEAR/FLAG/INSUFFICIENT via history-int-v2; full profile approvals not integrated',
        'PAY-02':'Integer algorithm candidate selection, min/max, distance and time edges tested independently; no signed full-chain case',
        'PAY-03':'Full snapshot duplicates, wrong claimed result/feature/cutoff tests; no actual client->W action accept',
        'PAY-04':'PAY signed source matching and hard false claims; historical 2.5 dep authentication not implemented',
        'PAY-05':'V2.5 Evidence type/version whitelist and strict Ed25519; no complete legacy grammar verification',
    }
    for item in current_coverage['cases']:
        if item['id'] in supplemented:
            item['status']='PARTIAL';item['phase3_evidence']=supplemented[item['id']]
    current_coverage['partial_count']=sum(x['status']=='PARTIAL' for x in current_coverage['cases'])
    current_coverage['not_run_count']=sum(x['status']=='NOT_RUN' for x in current_coverage['cases'])
    current_coverage['official_full_conformance_pass']=0
    current_coverage['note']='No cases promoted to FULL PASS; no upstream official test harness available in detached patch.'
    (HERE/'coverage_phase3.json').write_text(json.dumps(current_coverage,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    sources=[HERE/x for x in ('pay_history.py','pay_dependencies.py','upstream_schema.py',
                 'test_pay_history.py','test_pay_dependencies.py','test_upstream_schema.py','run_phase3.py')]
    report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
      'contract_basis':'ZJJ-CORE-2.6-R2 pinned at HEAD 0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c',
      'research_scope':'SELECTED_PAY_CLAUSES_AND_ABSTRACT_REFERENCE_ONLY_NOT_FULL_V26_CONFORMANCE',
      'suite':{'tests':res.testsRun,'pass':res.testsRun-len(res.failures)-len(res.errors)-len(res.skipped),
               'failures':len(res.failures),'errors':len(res.errors),'skipped':len(res.skipped)},
      'new_strict_pay_tests':sum(loader.loadTestsFromModule(m).countTestCases() for m in (test_pay_history,test_pay_dependencies,test_upstream_schema)),
      'official_schema_probes':schema_probes,
      'official_semantic_cases':{'full_pass':0,'partial_relevance':current_coverage['partial_count'],
                                 'not_run':current_coverage['not_run_count']},
      'profile_traces':len(vectors),
      'environment':{'python':sys.version.split()[0],'platform':platform.platform(),
                     'cryptography':importlib.metadata.version('cryptography'),
                     'jsonschema':importlib.metadata.version('jsonschema')},
      'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
      'known_gaps':['No upstream official JSON Schema files in detached patch; probes not executed',
         'No full v2.5 Evidence signature/dependency/audience historical graph',
         'C publication and credential historical provenance are pretrusted in-memory inputs',
         'Current KEY/ROLE range semantics are tested only in PAY slice; no authenticated C PoP',
         'No complete COMMIT/Acceptance fields, Result transport, real durable W transactions',
         'IND/MED schemas and full source/phase read rights not integrated into this slice',
         'No official 39-case end-to-end execution or independent complete secondary implementation']}
    (HERE/'phase3_validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'tests':res.testsRun,'pass':report['suite']['pass'],'failures':len(res.failures),
       'errors':len(res.errors),'new_strict_pay_tests':report['new_strict_pay_tests'],
       'official_full_pass':0,'schema_probe_status':sorted(set(x['status'] for x in schema_probes.values())),
       'artifact':'research/strict_v26/phase3_validation_report.json'},ensure_ascii=False))
    return 0 if res.wasSuccessful() and all(x['status']!='FAIL_UPSTREAM_SCHEMA' for x in schema_probes.values()) else 1

if __name__=='__main__':raise SystemExit(run_all())
