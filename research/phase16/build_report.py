"""Phase16 IND evidence bundle from GitHub Actions; NOT official conformance."""
from __future__ import annotations
import csv,hashlib,json,re,sys,zipfile
from pathlib import Path
from research.phase14.build_report import EXPECTED

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'research_evidence/phase16'
ARCHIVE=ROOT/'research_archives/ZJJ_CORE_2_6_R2_Phase16_Industrial_Candidate_20261009.zip'
SOURCES=[
    'research/phase16/industrial_delivery.py',
    'research/phase16/test_industrial_delivery.py',
    'research/phase16/process_flow.py',
    'research/phase16/build_report.py',
    'research/phase14/verifier.py',
    'research/phase11/scene_r2.py',
    'research/phase6/trusted_final.py',
    '.github/workflows/phase16-ind.yml',
    'research/formal39/run_formal39.py',
]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def run():
    for p,want in EXPECTED.items():assert sha(ROOT/p)==want,('ORIGINAL_ARTIFACT_CHANGED',p)
    formal=json.loads((ROOT/'research/formal39/formal39_report.json').read_text(encoding='utf-8'))
    cases=formal['official_cases']
    assert len(cases)==39 and len({a['id'] for a in cases})==39
    assert formal['summary']['official_complete_pass']==0
    assert all(not a['official_complete_pass'] for a in cases)
    raw=json.loads((OUT/'industrial_process/phase16_process_report.json').read_text(encoding='utf-8'))
    audit=raw['readonly_audit']
    assert raw['official_complete_pass'] is False and raw['profile']=='IND-DEMO-1'
    assert audit['phase16_gateway_integrity'] and audit['independent_readonly_verifier']
    assert audit['authenticated_tool_effects']==1 and audit['no_new_effect_on_retry']
    assert audit['lost_reply_observed_exit']==97 and audit['W_accept_count']==1
    assert audit['W_settlement_count']==1 and audit['physical_execution_proven'] is False
    tests=(OUT/'industrial_delivery_tests.txt').read_text(encoding='utf-8')
    m=re.search(r'Ran (\d+) tests in ',tests)
    assert m and int(m.group(1))>=8 and re.search(r'\nOK\s*$',tests)
    assert 'test_concurrent_delivery_only_one_effect' in tests
    artifacts=[
        OUT/'industrial_delivery_tests.txt',
        OUT/'industrial_process_output.txt',
        OUT/'original39.txt',
        OUT/'industrial_process/phase14_witness.json',
        OUT/'industrial_process/witness.json',
        OUT/'industrial_process/w.sqlite',
        OUT/'industrial_process/tool.sqlite',
        OUT/'industrial_process/phase16_process_report.json',
    ]
    for p in artifacts:assert p.is_file(),p
    report={'contract':'ZJJ-CORE-2.6-R2','phase':16,
      'label':'IND_AUTHENTICATED_TOOL_DELIVERY_LAB_CANDIDATE',
      'official_full_conformance':{'PASS':0,'FAIL':0,'BLOCKED_FULL_CONFORMANCE':39},
      'test_count':int(m.group(1)),
      'original_contract_sha256':EXPECTED,
      'source_sha256':{p:sha(ROOT/p) for p in SOURCES},
      'experiment_sha256':{str(p.relative_to(ROOT)):sha(p) for p in artifacts},
      'readonly_audit':audit,
      'scoped_case_facets':{
          'CORE-01':'IND existing C/X/W acceptance and separate tool authenticated delivery; lab positive path',
          'CORE-13':'IND post-CLAIM EFFECT_UNKNOWN held on lost tool reply; recover original fact, never redispatch',
          'CORE-15':'IND transport retry concurrent and after local tool process death; one simulated effect fact',
          'AUD-02C':'Tool immutable original fact and W first settlement are compared with independent SQLite record',
      },
      'unmet':[
          'C/E/X/W keys are still synthetic, with no hardware or independent privilege custody',
          'No real industrial actuator; exactly one SQLite fact is not proof of exactly one physical effect',
          'Signed W delivery token is handed off through local test files, not an authenticated network',
          'No trusted wall clock or variable Prepare/Sign/Finalize latency solution',
          'No unified real cross-profile W and no full 39-case transport/status/exhaustive semantics',
      ],
      'warning':'A successful lab tool receipt does NOT certify a real effect, safe remote actuation, or 39-case PASS.'}
    save(OUT/'phase16_report.json',report)
    with (OUT/'phase16_39case_matrix.csv').open('w',newline='',encoding='utf-8-sig') as fp:
        w=csv.writer(fp);w.writerow(['Official ID','Profile','Official original scenario','Official expected',
                                     'Official status','IND Phase16 scoped evidence','Unmet official criteria'])
        for x in cases:
            note=report['scoped_case_facets'].get(x['id'],'')
            w.writerow([x['id'],x['profile'],x['official_original_scenario'],
                        x['official_original_expected'],x['status'],note,
                        '; '.join(x['full_case_unmet_requirements'])])
    ARCHIVE.parent.mkdir(exist_ok=True)
    entries=sorted(p for p in ROOT.rglob('*') if p.is_file() and
                   '.git' not in p.parts and '__pycache__' not in p.parts and
                   not p.name.endswith(('.pyc','.pyo')) and p.suffix!='.zip')
    with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for p in entries:
            info=zipfile.ZipInfo(str(p.relative_to(ROOT)),date_time=(2026,10,9,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,p.read_bytes())
    report['deliverable']={'path':str(ARCHIVE.relative_to(ROOT)),
         'sha256':sha(ARCHIVE),'entries':len(entries)}
    save(OUT/'phase16_report.json',report)
    return {'status':report['label'],'official':report['official_full_conformance'],
            'new_tests':report['test_count'],'audit':audit,
            'archive':report['deliverable']}
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
