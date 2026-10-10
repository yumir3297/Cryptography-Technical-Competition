"""Run all Phase 1-8 tests; optionally gate against *unmodified* IND/MED official Schema.

No test auto-upgrades an official semantic case from NOT_RUN to PASS.
"""
from __future__ import annotations
import argparse,hashlib,io,json,platform,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from importlib import metadata
from research.phase7.run_phase7 import MODULES as PREVIOUS,CASES
from research.phase8 import test_scene_authority
from research.phase8.fixtures import build_scene,prepare_approved
from research.strict_v26.upstream_schema import UpstreamSchema
from research.reference_executor.wire import ProtocolError,rec_ref

ROOT=Path(__file__).resolve().parents[2]
DIR=Path(__file__).resolve().parent
PIN={'IND-DEMO-1':{'filename':'industrial.schema.json','sha':'f937286b1be32b2a8356b991a93770abff430578'},
     'MED-DEMO-1':{'filename':'medical.schema.json','sha':'5e43b803ed32a3359e4ad2b7e48a3c96f7fd9482'}}
CASE_MAP={
 'CORE-01':['test_all_five_fixed_synthetic_paths','test_atomic_accept_and_archive_after_restart'],
 'CORE-02':['test_evidence_kind_cannot_be_cross_profile_reused','test_broken_signed_permit_rejected'],
 'CORE-03':['test_controller_update_invalidates_signed_candidate'],
 'CORE-05':['test_controller_update_invalidates_signed_candidate','test_invalid_scene_evidence_current_revision'],
 'CORE-07':['test_review_read_permission_revocation','test_wrong_review_purpose_rejected'],
 'CORE-08':['test_hard_crash_rolls_back_every_write'],
 'CORE-09':['test_atomic_accept_and_archive_after_restart'],
 'CORE-11':['test_identical_commitproof_idempotent','test_nonce_same_other_proof_rejected'],
 'CORE-12':['test_eight_concurrent_identical_submit_single_accept'],
 'CORE-13':['test_role_revocation_after_accept_blocks_dispatch'],
 'CORE-14':['test_behavior_inflight_missing_blocks_dispatch'],
 'CORE-15':['test_repeat_claim_is_nonexecuting'],
 'CORE-20':['test_key_revocation_prevents_accept'],
 'IND-01':['test_all_five_fixed_synthetic_paths','test_ind_defect_cannot_release','test_missing_required_review_rejected'],
 'IND-02':['test_ind_fixed_package_mismatch_is_rejected','test_ind_missing_package_fails_closed'],
 'IND-03':['test_scene_external_update_after_accept_blocks_dispatch'],
 'MED-01':['test_all_five_fixed_synthetic_paths','test_missing_required_review_rejected'],
 'MED-02':['test_med_wrong_patient_rejected','test_med_wrong_group_rejected','test_med_wrong_record_ref_rejected','test_med_wrong_template_rejected'],
 'MED-03':['test_med_signed_but_incomplete_record_is_hard_reject','test_med_signed_but_unavailable_record_is_hard_reject'],
 'MED-04':['test_review_read_permission_revocation','test_authenticated_policy_reader_removed_fails'],
 'SC-01':['test_source_expires_at_upper_boundary','test_zero_capacity_rejects_without_consuming'],
 'SC-02':['test_ind_med_receipts_have_different_protected_profiles']}

def _sha_git_blob(contents):return hashlib.sha1(b'blob '+str(len(contents)).encode()+b'\0'+contents).hexdigest()

def _objects(a,op):
    objects=[]
    for ns,key in [('POLICY',a.scope_key()),('TASK',a.scope_key()+[op['task_id']]),
                   ('IDENTITY',a.scope_key()+ ([op['action']['payload']['unit_id']] if a.profile=='IND-DEMO-1'
                        else [op['action']['payload']['synthetic_patient_id'],op['action']['payload']['encounter_id']])),
                   ('EVIDENCE',op['scene_key'])]:
        record=a.current_record(ns,key)
        objects.append(('Record_'+record['kind'],record))
    if a.profile=='IND-DEMO-1':objects.append(('Record_IND_PACKAGE',a.current_record('PACKAGE',a.scope_key())))
    for alias in a.actors:
        who=a.actors[alias]
        record=a.current_record('KEY',[who.kid]);objects.append(('Record_KEY_GRANT',record))
        for role in (next(iter(who.roles)),)+(('READER',) if alias in ('H','G','X','U','V') else ()):
            objects.append(('Record_ROLE_GRANT',a.current_record('ROLE',a.role_key(who,role))))
    objects.extend([('Record_ASSESSMENT',op['assessment']),('Record_BASIS',op['basis']),
                    ('Record_COMMIT',op['commit_record']),('Acceptance',op['acceptance'])])
    for r in op['reviews']:objects.append(('Review',r))
    for k in ('authorization','issue','permit','challenge_request','challenge','proof'):
        m=op[k];objects.append((m['protected']['type'],m))
    return objects

def run_official_schemas(upstream_root,require=False):
    data={}
    for profile,meta in PIN.items():
        path=Path(upstream_root)/'system_dev'/'v26'/'contracts'/meta['filename']
        if not path.is_file():
            data[profile]={'status':'NOT_RUN_SCHEMA_NOT_INSTALLED','expected_blob_sha1':meta['sha']}
            continue
        b=path.read_bytes();actual=_sha_git_blob(b)
        if actual!=meta['sha']:
            data[profile]={'status':'ERROR_UNPINNED_SCHEMA','actual_blob_sha1':actual,'expected_blob_sha1':meta['sha']}
            continue
        schema=UpstreamSchema(upstream_root,profile)
        seen=0;fail=[]
        for i,label in enumerate(('DEMO_NORMAL','DEMO_DEFECT','DEMO_UNCERTAIN') if profile=='IND-DEMO-1' else ('DEMO_A','DEMO_B')):
            with tempfile.TemporaryDirectory() as td:
                a,action,tid,key,ev=build_scene(Path(td)/'demo.sqlite',profile,label)
                op=prepare_approved(a,action,tid,key)
                a.accept(op)
                for name,ob in _objects(a,op):
                    try:schema.validate(ob,name);seen+=1
                    except ProtocolError as e:fail.append({'label':label,'kind':name,'error':str(e)})
        data[profile]={'status':'PASS_STRUCTURAL_SUBSET' if not fail else 'FAIL_STRUCTURAL_SUBSET',
                       'checked_objects':seen,'rejected_objects':fail[:30],
                       'sha':actual,'warning':'Schema does not enforce x-zjj-order or all semantic bindings'}
    if require and any(x['status']!='PASS_STRUCTURAL_SUBSET' for x in data.values()):
        raise RuntimeError('Exact IND/MED schema gate incomplete or failed: '+str(data))
    return data

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--upstream-root',default=str(ROOT));p.add_argument('--require-ind-med-schemas',action='store_true')
    opts=p.parse_args(argv)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in [*PREVIOUS,test_scene_authority])
    buffer=io.StringIO();results=unittest.TextTestRunner(stream=buffer,verbosity=2).run(suite)
    (DIR/'test_log.txt').write_text(buffer.getvalue(),encoding='utf-8')
    schema_info=run_official_schemas(opts.upstream_root,require=opts.require_ind_med_schemas)
    matrix=[]
    for cid in CASES:
        tests=CASE_MAP.get(cid,[])
        matrix.append({'id':cid,'official_full_conformance':'NOT_RUN',
             'phase8_evidence':'SCENE_SIGNED_SQLITE_SUBSET' if tests else 'NO_ADDITIONAL_PHASE8_TEST',
             'phase8_tests':tests,
             'status_note':'This case includes other mandatory conditions not covered by the fixture; not an official PASS'})
    assert len(matrix)==39
    (DIR/'conformance_matrix.json').write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'generated_utc':datetime.now(timezone.utc).isoformat(),
            'protocol':'ZJJ-CORE-2.6-R2','source_repo':'yumir3297/Cryptography-Technical-Competition',
            'combined_regression':{'tests':results.testsRun,'passed':results.testsRun-len(results.failures)-len(results.errors)-len(results.skipped),
                'failures':len(results.failures),'errors':len(results.errors),'skipped':len(results.skipped)},
            'phase8_local':{'tests':unittest.defaultTestLoader.loadTestsFromModule(test_scene_authority).countTestCases(),
                'case_ids_with_partial_evidence':len(CASE_MAP),'source_sign_domain':'ZJJ-SOURCE-v1',
                'control_sign_domain':'ZJJ-C-CONTROL-LAB-v1','sqlite_atomic_receipt':True,
                'ind_med_signed_scene_paths':5,'commit_record_value_fields':21},
            'official_schema_ind_med':schema_info,
            'official_semantic_cases':{'total':39,'fully_passed':0,'fully_run':0,'all_case_claims_unmodified':True,
                'note':'Local fixture tests are not complete, independently authenticated official tests'},
            'limitations':['No original industrial/medical full JSON Schema local unless supplied from repository',
              'C signers and E SOURCE signing keys are deterministic fixtures, no key PoP enrollment',
              'Source/current records are in same single-process W SQLite for experiments, not independent distributed services',
              'R2 TOOL_FINAL integration with scene engine and ledger continuity not present',
              'No complete Result/status/issuer-idempotency/transport/bundle lifecycle or DENY range coverage',
              'No full exact role scope, expiry inheritance and implicit dependency closure for every Profile',
              'Known race between authoritative updates and separately signed application envelopes not formalized beyond local W transaction',
              'Full all-39 official conformance not established'],
            'runtime':{'python':sys.version.split()[0],'platform':platform.platform()},
            'code_sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in DIR.glob('*.py')}}
    (DIR/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DIR/'signed_scene_traces.json').write_text(json.dumps(build_traces(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'regression':report['combined_regression'],'scene':report['phase8_local'],
        'official_ind_med_schema':schema_info,'official_semantic_full_pass':0},ensure_ascii=False,indent=2))
    return 0 if results.wasSuccessful() else 1

def build_traces():
    traces=[]
    for i,(profile,label) in enumerate([('IND-DEMO-1','DEMO_NORMAL'),('IND-DEMO-1','DEMO_DEFECT'),
             ('IND-DEMO-1','DEMO_UNCERTAIN'),('MED-DEMO-1','DEMO_A'),('MED-DEMO-1','DEMO_B')]):
        with tempfile.TemporaryDirectory() as td:
            a,action,task,key,ev=build_scene(Path(td)/'scene.sqlite',profile,label)
            op=prepare_approved(a,action,task,key)
            receipt=a.accept(op);attempt=a.claim(op)
            traces.append({'profile':profile,'label':label,'required_review_purposes':op['required'],
               'action_hash':op['ctx']['action_hash'],'basis_ref':rec_ref(op['basis']),
               'commit_ref':rec_ref(op['commit_record']),'acceptance_ref':hashlib.sha256(json.dumps(receipt,sort_keys=True).encode()).hexdigest(),
               'acceptance':receipt,'COMMIT':op['commit_record'], 'dispatch_attempt':attempt,'W_snapshot':a.snapshot()})
    return traces

if __name__=='__main__':sys.exit(main())
