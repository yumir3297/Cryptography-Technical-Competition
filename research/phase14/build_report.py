"""Phase14 evidence/report build. Never promotes local probes to official PASS."""
from __future__ import annotations
import argparse,csv,datetime,hashlib,json,platform,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
EXPECTED={
'system_dev/v26/semantic_cases.json':'43cb3de4492c290f9ebcd6570db2e59e1865ede33fcd58190ac6e7f688b507da',
'system_dev/v26/contracts/pay1.schema.json':'84f57ba485abe56b94141dc8d27968c56ecad50fb50095565939b02fd2f8833e',
'system_dev/v26/contracts/industrial.schema.json':'36c325808a01d5afb51f27872df4fdc7c40907aa56b023a10bd5a949e4ad768d',
'system_dev/v26/contracts/medical.schema.json':'033df4601364abcb2bf9f4673d43804150da47e598b71cfceb0ec090366b7ac2'}
TARGETS=['CORE-01','CORE-03','CORE-13','CORE-15','AUD-02A','AUD-02B','AUD-02C']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')
def run(evidence,assemble=True):
    p=Path(evidence).resolve()
    data=json.loads((p/'phase14_process_report.json').read_text(encoding='utf8'))
    assert set(data['profiles'])=={'IND-DEMO-1','MED-DEMO-1'}
    assert data['official_passes']==0
    for q in data['profiles'].values():
        a=q['audit']; assert a['independent_readonly_verifier'] and a['W_accept_count']==1 and a['W_settlement_count']==1
        assert a['phase14_prepared_ticket_checked'] and not a['official_complete_pass']
    formal=json.loads((ROOT/'research/formal39/formal39_report.json').read_text(encoding='utf8'))
    cases=formal['official_cases']
    assert len(cases)==39 and len({x['id'] for x in cases})==39
    assert all(x['status']=='BLOCKED_FULL_CONFORMANCE' for x in cases)
    assert formal['summary']['official_complete_pass']==0
    for asset,expected in EXPECTED.items():assert sha(ROOT/asset)==expected,(asset,'OFFICIAL_ARTIFACT_CHANGED')
    src=['research/phase14/verifier.py','research/phase14/test_phase14.py',
         'research/phase14/process_flow.py','research/phase14/build_report.py',
         'research/phase13/process_flow.py','research/phase12/authority.py']
    paths=[p/'phase14_process_report.json']
    for profile in sorted(data['profiles']):
        folder=p/profile
        paths.extend([folder/'phase14_witness.json',folder/'witness.json',folder/'w.sqlite',folder/'tool.sqlite'])
    report={'contract':'ZJJ-CORE-2.6-R2','phase':14,
       'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'status':'EXPERIMENTAL_PHASE14_SCENE_CANDIDATE',
       'formal_status':{'PASS':0,'FAIL':0,'BLOCKED_FULL_CONFORMANCE':39},
       'executed_process_profiles':['IND-DEMO-1','MED-DEMO-1'],
       'pay_status':'Phase13 regression only; PAY two-phase acceptance not implemented in Phase14',
       'original_official_artifact_sha256':EXPECTED,
       'source_sha256':{f:sha(ROOT/f) for f in src},
       'witness_sha256':{str(x.relative_to(ROOT)):sha(x) for x in paths},
       'formal39':formal['summary'],
       'preserved_regressions':TARGETS,
       'unresolved':['PAY Prepare/Sign/Finalize migration','C/E issuer custody and independent root trust',
            'trusted time outside insecure laboratory fixture','one deployed cross-profile W',
            'real physical/clinical tool attestation','full transitive RequiredDeps T/F/U',
            'transport aud/path/0-RTT/STATUS/Result completion'],
       'read_only_audit':{profile:data['profiles'][profile]['audit'] for profile in sorted(data['profiles'])},
       'warning':'Process-separated laboratory signing is not privileged key custody or an official full conformance PASS.'}
    save(HERE/'phase14_report.json',report)
    matrix=HERE/'phase14_39case_matrix.csv'
    with matrix.open('w',newline='',encoding='utf-8-sig') as handle:
        w=csv.writer(handle)
        w.writerow(['Official ID','Profile','Original scenario','Original expected','Official status',
            'Phase14 new evidence','Official PASS','Open obligations'])
        for item in cases:
            w.writerow([item['id'],item['profile'],item['official_original_scenario'],
                item['official_original_expected'],item['status'],
                str((p/'phase14_process_report.json').relative_to(ROOT)) if item['id']=='CORE-01' else
                ('Prior phase evidence maintained; no Phase14 promotion' if item['id'] in TARGETS else ''),
                'NO', '; '.join(item['full_case_unmet_requirements']+
                      (report['unresolved'] if item['id']=='CORE-01' else []))])
    if assemble:
        dest=ROOT/'research_archives/ZJJ_CORE_2_6_R2_Phase14_Candidate_20261009.zip'
        dest.parent.mkdir(exist_ok=True)
        # Self-contained branch snapshot excluding prior binary archive and git internals.
        allfiles=sorted(x for x in ROOT.rglob('*') if x.is_file() and '.git' not in x.parts
             and not x.name.endswith(('.pyc','.pyo')) and '__pycache__' not in x.parts
             and x!=dest and x.suffix!='zip')
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as archive:
            for path in allfiles:
                info=zipfile.ZipInfo(str(path.relative_to(ROOT)),date_time=(2026,10,9,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                info.external_attr=0o644<<16
                archive.writestr(info,path.read_bytes())
        report['delivery_zip']={'path':str(dest.relative_to(ROOT)),'sha256':sha(dest),
          'entries':len(allfiles),'excludes':'pre-existing Phase13 ZIP and .git history'}
        save(HERE/'phase14_report.json',report)
    return report
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',default=str(HERE/'evidence/core01_process'))
    result=run(parser.parse_args().evidence)
    print(json.dumps({'official_status':result['formal_status'],
       'profiles':result['executed_process_profiles'],'zip':result['delivery_zip']},ensure_ascii=False))
