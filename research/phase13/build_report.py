"""Build phase13 attachment to Phase12 formal39 results WITHOUT altering PASS statuses."""
from __future__ import annotations
import csv,datetime,hashlib,json,platform,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'research'/'phase13'
EVID=BASE/'evidence'/'core01_process'
FORMAL=ROOT/'research'/'formal39'/'formal39_report.json'
IDS=('PAY-1','IND-DEMO-1','MED-DEMO-1')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
def main():
    formal=json.loads(FORMAL.read_text(encoding='utf8'))
    process=json.loads((EVID/'phase13_process_report.json').read_text(encoding='utf8'))
    official={x['id']:x for x in formal['official_cases']}
    assert set(process['three_profiles'])==set(IDS) and len(official)==39
    assert formal['summary']['official_complete_pass']==0
    assert all(x['status']=='BLOCKED_FULL_CONFORMANCE' for x in official.values())
    for p in IDS:
        e=process['three_profiles'][p]
        assert e['audit']['W_accept_count']==1 and e['audit']['W_settlement_count']==1
        assert len(e['mutations'])==3 and all(x['rejected'] for x in e['mutations'])
    files={}
    for p in IDS:
        d=EVID/p
        files[str((d/'witness.json').relative_to(ROOT))]=sha(d/'witness.json')
    src=['research/phase13/process_flow.py','research/phase13/test_phase13.py',
         'research/phase13/build_report.py','research/phase12/authority.py',
         'research/phase11/scene_r2.py','research/phase11/pay_r2.py',
         'research/phase8/scene_authority.py']
    pinned=['system_dev/v26/semantic_cases.json',
            'system_dev/v26/contracts/pay1.schema.json',
            'system_dev/v26/contracts/industrial.schema.json',
            'system_dev/v26/contracts/medical.schema.json']
    summary={
       'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'contract':'ZJJ-CORE-2.6-R2','phase':13,
       'selected_official_case':{
         'id':'CORE-01','scenario':official['CORE-01']['official_original_scenario'],
         'expected':official['CORE-01']['official_original_expected'],
         'new_evidence_status':'PASS_PROCESS_SEPARATED_LAB_CANDIDATE',
         'official_complete_pass':False,'formal_status':'BLOCKED_FULL_CONFORMANCE'},
       'three_profiles':{p:{
          'independently_verified':True,
          'W_acceptances':process['three_profiles'][p]['audit']['W_accept_count'],
          'W_dispatches':process['three_profiles'][p]['audit']['W_call_count'],
          'W_settlements':process['three_profiles'][p]['audit']['W_settlement_count'],
          'negative_transcript_mutations_rejected':len(process['three_profiles'][p]['mutations']),
          'distinct_executed_stage_processes':process['three_profiles'][p]['audit']['distinct_stage_pids'],
          'evidence':process['three_profiles'][p]['witness_path']} for p in IDS},
       'phase13_test_cases':5,'phase13_test_log':'research/phase13/phase13_test_stdout.txt',
       'formal39_reexecuted':True,
       'formal39_summary':formal['summary'],
       'formal_status_unchanged':{'PASS':0,'FAIL':0,'BLOCKED_FULL_CONFORMANCE':39},
       'verified_experimental_scope':['distinct bootstrap / claim / simulated tool final / settle / redispatch check / readonly verifier processes',
          'original signed envelopes and schemas', 'COMMIT and acceptance ref equality',
          'SQL persistent acceptance/attempt/final fact/settlement consistency',
          'tampered Acceptance, TOOL_FINAL and profile substitution rejection'],
       'full_official_case_blockers':[
          'C and E issuer trust roots and change governance remain lab fixtures (trust root is supplied by transcript)',
          'IND/MED HardenedSceneW still instantiate and expose C private signing key and X private signing key',
          'W persists one SQLite database per profile instead of a single deployed authority spanning all profiles',
          'TOOL_FINAL comes from deterministic simulated ToolLedger, not externally attested effect source',
          'Full official typed RequiredDeps and T/F/U proof not independently reconstructed for every transitive binding',
          'Complete path/aud/scope, STATUS/Result, response binding, 0-RTT, transport and cross-service failure/lifecycle proofs not closed'],
       'code_sha256':{f:sha(ROOT/f) for f in src},
       'original_resource_sha256':{f:sha(ROOT/f) for f in pinned},
       'transcript_sha256':files,
       'environment':{'python':sys.version.split()[0],'platform':platform.platform()},
       'do_not_infer':'Phase13 local positive candidate is not one complete official semantic conformance PASS.'}
    dump(BASE/'phase13_report.json',summary)
    # Preserve exact original case requirements/status in all 39 rows; add a
    # distinct evidence field only for CORE-01, never forge a PASS status.
    with (BASE/'phase13_39case_matrix.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['Official ID','Profile','Original scenario','Original expected','Official status',
                    'Prior local tests passed','Phase13 new candidate trace','Phase13 complete PASS','Remaining obligations'])
        for x in formal['official_cases']:
            newer=x['id']=='CORE-01'
            problems=list(x['full_case_unmet_requirements'])
            if newer:problems+=summary['full_official_case_blockers']
            w.writerow([x['id'],x['profile'],x['official_original_scenario'],x['official_original_expected'],
                        x['status'],x['partial_witnesses']['passed'],
                        'research/phase13/evidence/core01_process/phase13_process_report.json' if newer else '',
                        'NO' if newer else '', '; '.join(dict.fromkeys(problems))])
    return summary
if __name__=='__main__':
    r=main()
    print(json.dumps({'phase':r['phase'],'case':r['selected_official_case']['id'],
                      'official_PASS':r['formal_status_unchanged']['PASS'],
                      'signed_process_profiles':list(r['three_profiles']),
                      'case_matrix':'research/phase13/phase13_39case_matrix.csv'}))
