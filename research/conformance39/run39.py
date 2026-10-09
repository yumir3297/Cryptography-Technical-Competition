"""Independent 39-row case-evidence runner (not a fictitious 39/39 conformance claim).

Maps each official requirement to a *real, named executable unittest*, captures the individual
result and declares its mandatory missing conditions. Upgrades to official PASS are prohibited
until the upstream exact case manifest, full preconditions and signed W evidence are present.
"""
from __future__ import annotations
import argparse, hashlib, importlib, inspect, io, json, os, platform, sys, time, unittest
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from research.conformance39.cases import CASES, EXPECTED_IDS

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
# Legacy assurance modules use absolute imports from their directory.
if str(ROOT/'research'/'assurance') not in sys.path:sys.path.insert(0,str(ROOT/'research'/'assurance'))
UPSTREAM_CASE_SHA='b0bc9dbeedac135f6520b5e93729f63686d97bb4'
SCHEMAS={
 'PAY-1':('pay1.schema.json','86ba1bae0e4c455899af661bed44edfc5494aa5e'),
 'IND-DEMO-1':('industrial.schema.json','f937286b1be32b2a8356b991a93770abff430578'),
 'MED-DEMO-1':('medical.schema.json','5e43b803ed32a3359e4ad2b7e48a3c96f7fd9482')}
MODULES={
 'assurance':['research.assurance.test_abstract_checker','research.assurance.test_deny_range_model'],
 'reference_executor':['research.reference_executor.test_reference'],
 'strict_v26':['research.strict_v26.test_pay_history','research.strict_v26.test_pay_dependencies','research.strict_v26.test_upstream_schema'],
 'phase4':['research.phase4.test_flow'],
 'phase5':['research.phase5.test_durable_w'],
 'phase6':['research.phase6.test_trusted_final'],
 'phase7':['research.phase7.test_guarded_dispatch','research.phase7.test_official_contract'],
 'phase8':['research.phase8.test_scene_authority'],
 'conformance39':['research.conformance39.test_enrollment_lab','research.conformance39.test_industrial_advance_lab']}


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode('ascii')+b'\0'+data).hexdigest()


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_manifest(root: Path):
    path=root/'system_dev/v26/semantic_cases.json'
    if not path.is_file():return {'status':'NOT_INSTALLED','source':'GitHub connector verified case IDs, local original manifest required','expected_git_blob':UPSTREAM_CASE_SHA}
    actual=git_blob(path.read_bytes())
    if actual!=UPSTREAM_CASE_SHA:
        return {'status':'BLOB_MISMATCH','actual_git_blob':actual,'expected_git_blob':UPSTREAM_CASE_SHA}
    obj=json.loads(path.read_text(encoding='utf-8'))
    ids=[c.get('id') for c in obj.get('cases',[])]
    if obj.get('contract')!='ZJJ-CORE-2.6-R2' or ids!=EXPECTED_IDS:
        return {'status':'INVALID_CASE_MANIFEST','actual_ids':ids}
    return {'status':'EXACT_OFFICIAL_MANIFEST_VERIFIED','git_blob':actual,'count':len(ids),'unmodified_declared_statuses':all(c.get('status')=='NOT_RUN' for c in obj['cases'])}


def check_schemas(root: Path):
    from jsonschema import Draft202012Validator
    status={}
    for name,(filename,pin) in SCHEMAS.items():
        path=root/'system_dev/v26/contracts'/filename
        if not path.is_file():status[name]={'status':'MISSING','expected_git_blob':pin};continue
        actual=git_blob(path.read_bytes())
        if actual!=pin:status[name]={'status':'BLOB_MISMATCH','expected_git_blob':pin,'actual_git_blob':actual};continue
        try:
            schema=json.loads(path.read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
            status[name]={'status':'EXACT_ORIGINAL_SCHEMA_LOADED','git_blob':actual,'definitions':len(schema.get('$defs',{}))}
        except Exception as exc:status[name]={'status':'INVALID_SCHEMA','error':str(exc)}
    return status


def index_tests():
    index={}
    for hint,modules in MODULES.items():
        for module in modules:
            m=importlib.import_module(module)
            for name,cls in inspect.getmembers(m,inspect.isclass):
                if cls.__module__ != module or not issubclass(cls,unittest.TestCase):continue
                for method in unittest.defaultTestLoader.getTestCaseNames(cls):
                    short=method[5:]
                    key=f'{hint}:{short}'
                    if key in index:raise RuntimeError(f'ambiguous witness alias: {key}')
                    index[key]=f'{module}.{cls.__name__}.{method}'
    return index


def run_case(case,index):
    names=[];missing=[]
    for key in case.witnesses:
        if key not in index:missing.append(key)
        else:names.append(index[key])
    if missing:
        return {'id':case.id,'profile':case.profile,'expected':case.expectation,
                'status':'HARNESS_ERROR','missing_test_identifiers':missing,'missing_full_requirements':list(case.missing),
                'official_full_conformance':'NOT_ESTABLISHED'}
    if not names:
        return {'id':case.id,'profile':case.profile,'expected':case.expectation,
                'status':'BLOCKED_NO_EXECUTABLE_WITNESS','run':0,'passed':0,
                'missing_full_requirements':list(case.missing),'official_full_conformance':'NOT_ESTABLISHED'}
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    buf=io.StringIO()
    t=time.perf_counter()
    result=unittest.TextTestRunner(stream=buf,verbosity=2).run(suite)
    elapsed=round(time.perf_counter()-t,3)
    failures=[{'test':a.id(),'traceback':b[-4000:]} for a,b in result.failures]
    errors=[{'test':a.id(),'traceback':b[-4000:]} for a,b in result.errors]
    skipped=[{'test':a.id(),'reason':reason} for a,reason in result.skipped]
    status='LOCAL_WITNESS_FAILED' if failures or errors or skipped or result.testsRun!=len(names) else 'PARTIAL_WITNESSES_PASS'
    return {'id':case.id,'profile':case.profile,'expected':case.expectation,'status':status,
            'official_full_conformance':'NOT_ESTABLISHED','run':result.testsRun,
            'passed':result.testsRun-len(failures)-len(errors)-len(skipped),'seconds':elapsed,
            'test_ids':names,'missing_full_requirements':list(case.missing),
            'failures':failures,'errors':errors,'skipped':skipped,'runner_log':buf.getvalue()[-16000:]}


def main(argv=None):
    ap=argparse.ArgumentParser(description='Execute all 39 case evidence slices, fail closed on missing official preconditions')
    ap.add_argument('--upstream-root',default=str(ROOT),help='directory containing original system_dev/v26/...')
    ap.add_argument('--output',default=str(OUT/'official39_evidence_report.json'))
    ap.add_argument('--case-id',action='append',help='run only selected case IDs (default all 39)')
    args=ap.parse_args(argv)
    assert len(CASES)==39 and [c.id for c in CASES]==EXPECTED_IDS
    root=Path(args.upstream_root).resolve();selected=CASES
    if args.case_id:
        invalid=set(args.case_id)-set(EXPECTED_IDS)
        if invalid:ap.error('unknown official case IDs: '+','.join(sorted(invalid)))
        selected=[c for c in CASES if c.id in set(args.case_id)]
    manifest=check_manifest(root)
    schema=check_schemas(root)
    # When the exact original IND/MED schema bytes are installed, validate
    # *emitted signed records*, not only the meta-schema. This cannot be
    # counted as executed when their original bytes are missing.
    schema_emission={}
    if all(schema[x]['status']=='EXACT_ORIGINAL_SCHEMA_LOADED' for x in ('IND-DEMO-1','MED-DEMO-1')):
        from research.phase8.run_phase8 import run_official_schemas
        schema_emission=run_official_schemas(root)
    else:
        schema_emission={x:{'status':'BLOCKED_ORIGINAL_SCHEMA_REQUIRED'} for x in ('IND-DEMO-1','MED-DEMO-1')}
    index=index_tests()
    cases=[]
    for case in selected:
        r=run_case(case,index);cases.append(r)
        print(f"{r['id']:8} {r['status']:30} {r.get('passed',0)}/{r.get('run',0)} witness tests",flush=True)
    counters=Counter(r['status'] for r in cases)
    if any(r['status']=='HARNESS_ERROR' for r in cases):result='HARNESS_ERROR'
    elif any(r['status']=='LOCAL_WITNESS_FAILED' for r in cases):result='LOCAL_WITNESS_FAILURE'
    else:result='PARTIAL_EVIDENCE_COLLECTED'
    report={'generated_utc':datetime.now(timezone.utc).isoformat(),'protocol':'ZJJ-CORE-2.6-R2',
        'repository':'yumir3297/Cryptography-Technical-Competition',
        'meaning':'Partial individually executed case witnesses; cannot issue official PASS without complete inputs, trusted authority and all case obligations',
        'original_manifest':manifest,'official_schema_gates':schema,'official_schema_emitted_records':schema_emission,
        'summary':{'case_ids_in_official_manifest':39,'cases_selected':len(selected),'local_witness_executed':sum(bool(r.get('run')) for r in cases),
                   'local_witness_passed_cases':counters['PARTIAL_WITNESSES_PASS'],
                   'local_witness_failed_cases':counters['LOCAL_WITNESS_FAILED'],
                   'cases_without_witness':counters['BLOCKED_NO_EXECUTABLE_WITNESS'],
                   'harness_errors':counters['HARNESS_ERROR'],
                   'official_complete_pass':0,'official_complete_fail':0,
                   'still_blocked_or_partially_verified':len(selected),'outcome':result},
        'cases':cases,'integrity':{
          'suite_source_sha256':{name:sha256(ROOT.joinpath(name.replace('.','/')+'.py')) for name in sorted({t.split('.')[0]+'.'+t.split('.')[1]+'.'+t.split('.')[2] for r in cases for t in r.get('test_ids',[])})},
          'runner_sha256':sha256(__file__),'cases_sha256':sha256(OUT/'cases.py')},
        'environment':{'python':sys.version.split()[0],'platform':platform.platform()},
        'warnings':['No case status is lifted from PARTIAL to FULL merely by counting module tests.',
                    'Official schema Draft 2020-12 checks do NOT implement extra x-zjj-order constraints.',
                    'The known legacy dispatch revocation vulnerability has an experimental guarded mitigation only.',
                    'Unimplemented enrollment PoP, lifecycle transitions, trust continuity and cross-profile linkage can invalidate case assumptions.']}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('\nSUMMARY '+json.dumps(report['summary'],ensure_ascii=False),flush=True)
    print('REPORT '+str(output),flush=True)
    return 0 if result=='PARTIAL_EVIDENCE_COLLECTED' else 1

if __name__=='__main__':raise SystemExit(main())
