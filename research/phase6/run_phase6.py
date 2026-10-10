"""Phase-6 reproducibility runner and conservative case-evidence manifest."""
from __future__ import annotations
import hashlib,io,json,os,platform,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from importlib import metadata
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ROOT=Path(__file__).resolve().parents[2]
for d in (str(ROOT),str(ROOT/'research/assurance')):
    if d not in sys.path:sys.path.insert(0,d)
from research.assurance import test_abstract_checker,test_deny_range_model
from research.reference_executor import test_reference
from research.strict_v26 import test_pay_history,test_pay_dependencies,test_upstream_schema
from research.phase4 import test_flow
from research.phase5 import test_durable_w
from research.phase5.test_durable_w import ready
from research.phase5.run_phase5 import schema_probe
from research.phase6 import test_trusted_final
from research.phase6.trusted_final import Controller,ToolLedger,FinalW,final_fact_id,final_fact,_pub
from research.reference_executor.wire import sid,b64,keyid,rec_ref

HERE=Path(__file__).resolve().parent
CASES='CORE-01 CORE-02 CORE-03 CORE-04 CORE-05 CORE-06 CORE-07 CORE-08 CORE-09 CORE-10 CORE-11 CORE-12 CORE-13 CORE-14 CORE-15 CORE-16 CORE-17 CORE-18 CORE-19 CORE-20 PAY-01 PAY-02 PAY-03 PAY-04 PAY-05 IND-01 IND-02 IND-03 IND-04 MED-01 MED-02 MED-03 MED-04 SC-01 SC-02 AUD-02A AUD-02B AUD-02C AUD-02D'.split()
AUD_EVIDENCE={
 'AUD-02A':['test_expired_first_proof_requires_fresh_reattest','test_missing_fact_never_implies_failed'],
 'AUD-02B':['test_rotation_recovery_same_ledger','test_same_fact_fresh_attestation_new_ref_no_second_settlement','test_rotation_to_different_ledger_reject'],
 'AUD-02C':['test_missing_fact_never_implies_failed','test_rotation_ledger_head_mismatch','test_rotation_to_different_ledger_reject'],
 'AUD-02D':['test_bad_signature_cannot_halt','test_trusted_conflicting_fact_halts_without_reverse_settlement','test_halted_not_unhalted_by_good_replay'],
 'CORE-08':['test_two_crash_boundaries_recovery'],
 'CORE-15':['test_two_crash_boundaries_recovery','test_claim_is_one_shot_no_arbitrary_witness_bool'],
 'CORE-16':['test_success_and_persistent_settlement','test_failed_confirmed_no_late_effect','test_forged_effect_semantics_fail'],
 'CORE-20':['test_rotation_recovery_same_ledger','test_rotation_replay_epoch_reject'],
}

def record_tests(suite):
    out=[]
    for t in suite:
        if isinstance(t,unittest.TestSuite):out.extend(record_tests(t))
        else:out.append(t.id())
    return out

def fresh_trace(kind):
    with tempfile.TemporaryDirectory() as temp:
        loc=Path(temp); c=Controller.fixture();led=ToolLedger(loc/'tool.sqlite')
        w=FinalW(loc/'w.sqlite',c.public_key)
        scope={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
        k1=Ed25519PrivateKey.from_private_bytes(b'\x51'*32)
        k2=Ed25519PrivateKey.from_private_bytes(b'\x52'*32)
        def certify(k,epoch):
            v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
                'ledger_id':led.ledger_id,'evidence_method':'tool-final-v2',
                'public_key':b64(_pub(k)),'kid':keyid(_pub(k)),
                'epoch':str(epoch),'iat':'90','exp':'2000'}
            return c.certify(scope,v,epoch,led.head(),led.origin)
        w.activate(certify(k1,1),led)
        f,op=ready();a=w.accept(f,op);attempt=sid(501)
        w.claim_bound(op.action['operation_id'],attempt)
        outcome='FAILED_CONFIRMED' if kind=='FAILED_CONFIRMED' else 'SUCCEEDED'
        fact=led.freeze(scope,op.action,attempt,outcome=outcome,
                        effect_id='' if outcome=='FAILED_CONFIRMED' else 'effect1')
        signer=k1
        if kind=='ROTATION':
            w.activate(certify(k2,2),led)
            signer=k2
        final=led.reattest(scope,fact,signer,'tool-issuer',130,'2000')
        result=w.settle(final,now=140)
        retry=w.settle(final,now=1600)
        assert retry['idempotent'] and w.snapshot()['accepted_count']==1
        assert len(led.all_facts())==1
        return {'kind':kind,'profile':'PAY-1','signed_commit_ref':rec_ref(a['commit']),
                'final_fact_id':final_fact_id(final),'final_record_ref':rec_ref(final),
                'immutable_fact':final_fact(final),'result':result,'historical_replay':retry,
                'w_state':w.snapshot(),'tool_ledger_head':led.head(),'tool_final_count':len(led.all_facts())}

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--upstream-root',type=Path)
    args=p.parse_args(argv)
    # Official gate deliberately keeps the file SHA-1 pin: schema need not be present in additive patch.
    gate,schema=schema_probe(args.upstream_root)
    original_cases_status='NOT_RUN_OFFICIAL_CASES_FILE_UNAVAILABLE'
    if args.upstream_root is not None:
        manifest=Path(args.upstream_root)/'system_dev/v26/semantic_cases.json'
        if not manifest.is_file():raise RuntimeError('Official semantic_cases.json missing at '+str(manifest))
        original=json.loads(manifest.read_text(encoding='utf-8'))
        original_ids=[x['id'] for x in original['cases']]
        if original_ids!=CASES or original.get('contract')!='ZJJ-CORE-2.6-R2':
            raise RuntimeError('Semantic manifest does not match pinned 39-case ordering / contract')
        original_cases_status='PINNED_39_CASE_IDS_VERIFIED_NOT_FULLY_EXECUTED'
    mods=[test_abstract_checker,test_deny_range_model,test_reference,
          test_pay_history,test_pay_dependencies,test_upstream_schema,test_flow,test_durable_w,test_trusted_final]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in mods)
    tests=record_tests(suite)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'test_log.txt').write_text(stream.getvalue(),encoding='utf-8')
    failures=len(result.failures)+len(result.errors);skips=len(result.skipped)
    assertions={name: next((q for q in tests if q.split('.')[-1]==name),None)
                for block in AUD_EVIDENCE.values() for name in block}
    matrix=[]
    for cid in CASES:
        local=[assertions[x] for x in AUD_EVIDENCE.get(cid,[]) if assertions[x]]
        matrix.append({'id':cid,'full_official_case_status':'NOT_RUN',
            'research_subtest_status':'PASS_PARTIAL' if local and result.wasSuccessful() else 'NOT_MAPPED_IN_PHASE6',
            'phase6_related_tests':local,'fully_conformant':False,
            'scope_note':'Offline PAY-1 simulator with controller/trust fixtures; not the all-profile official case.'})
    traces=[fresh_trace(k) for k in ('SUCCEEDED','FAILED_CONFIRMED','ROTATION')] if result.wasSuccessful() else []
    status={**schema}
    if gate:
        # Official Schema is checked via the unmodified pinned Git blob *and* the
        # upstream Phase-5 contract-object conformance probe; no partial aliases.
        from research.phase5.run_phase5 import prepare_cases,check_emitted
        count=0
        for cs in (None,):
            flow,op=prepare_cases(cs,args.upstream_root)
            from research.phase5.durable_w import DurablePayW
            with tempfile.TemporaryDirectory() as d:
                outcome=DurablePayW(Path(d)/'pay.sqlite').accept(flow,op)
                count+=check_emitted(gate,flow,op,outcome)
        status['status']='PINNED_OFFICIAL_PAY_JSON_SCHEMA_VALIDATED'
        status['objects_validated']=count
    report={'contract':'ZJJ-CORE-2.6-R2','upstream_commit':'0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c',
         'generated_at_utc':datetime.now(timezone.utc).isoformat(),
         'suite':{'tests':result.testsRun,'passed':result.testsRun-failures-skips,'failed':len(result.failures),
                  'errors':len(result.errors),'skipped':skips},
         'official_schema':status,'official_semantic_cases':{'total':len(CASES),'source_status':original_cases_status,'fully_run':0,'passed':0,
              'related_partial_evidence':sum(bool(r['phase6_related_tests']) for r in matrix)},
         'durable_r2_traces':traces,
         'scope':{'implemented':'PAY-1 laboratory immutable tool-final + controller-signed trust + W settlement; separate SQLite files',
              'assumptions':['Controller root signing key trusted; no control-plane compromise model',
              'Two local SQLite files, not external production tool or distributed atomic protocol',
              'Claim has authenticated tool mapping but not full current-policy/RequiredDeps reconstruction',
              'Simulated signed facts are not proof of actual economic/industrial effects',
              'Trust rotation snapshot is only a local continuity check, not external ledger migration proof',
              'Hard process termination does not test real disk power failure or all concurrency interleavings'],
              'uncompleted':['Official 39-case integrated harness, all three profiles',
                    'Source E and real C enrollment/publication workflow',
                    'Complete transaction-current authorization guard for dispatch',
                    'External tool ledger and independent, verifiable continuity at key rotation']},
         'environment':{'python':sys.version.split()[0],'platform':platform.platform(),
                        'cryptography':metadata.version('cryptography'),'sqlite3':__import__('sqlite3').sqlite_version},
         'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}}
    (HERE/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'case_evidence_matrix.json').write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'signed_durable_final_traces.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'suite':report['suite'],'official_schema':status['status'],'official_complete_passed':0,
        'related_partial_cases':report['official_semantic_cases']['related_partial_evidence'],
        'durable_traces':len(traces)},ensure_ascii=False))
    return 0 if result.wasSuccessful() and len(CASES)==39 and len(traces)==3 else 1

if __name__=='__main__':raise SystemExit(main())
