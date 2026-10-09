"""Phase15 evidence registry, original official39 matrix, frozen lab candidate archive.

Never turns scoped PAY evidence into an official PASS. Signed fixtures and SQLite
witnesses are experimental, not proof of deployed custody/physical settlement.
"""
from __future__ import annotations
import csv,hashlib,json,platform,re,sys,zipfile
from pathlib import Path
from research.phase14.build_report import EXPECTED

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'research_evidence'
ARCHIVE=ROOT/'research_archives/ZJJ_CORE_2_6_R2_Phase15_Pay_Candidate_20261009.zip'
SOURCES=[
 'research/phase15/pay_accept.py',
 'research/phase15/test_pay_accept.py',
 'research/phase15/process_flow.py',
 'research/phase15/build_report.py',
 'research/phase4/flow.py',
 'research/strict_v26/pay_dependencies.py',
 'research/reference_executor/wire.py',
 'research/phase12/authority.py',
 'research/formal39/run_formal39.py',
 '.github/workflows/phase15-pay.yml',
]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jsonout(p,data):
    Path(p).write_text(json.dumps(data,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf8')
def run():
    OUT.mkdir(exist_ok=True)
    for path,expected in EXPECTED.items():
        assert sha(ROOT/path)==expected,(path,'OFFICIAL_ARTIFACT_MODIFIED')
    d=OUT/'phase15_pay_process'
    audit=json.loads((d/'phase15_pay_report.json').read_text(encoding='utf8'))
    assert audit['profile']=='PAY-1' and audit['official_complete_pass'] is False
    assert audit['audit']['independent_readonly_verifier']
    assert audit['audit']['externally_signed_X']
    assert audit['audit']['source_certificate_verified']
    assert audit['audit']['W_accept_count']==1 and audit['audit']['W_settlement_count']==1
    testlog=(OUT/'phase15_pay_test_output.txt').read_text(encoding='utf8')
    match=re.search(r'Ran (\d+) tests in ',testlog)
    assert match and int(match.group(1))>=6 and re.search(r'\nOK\s*$',testlog)
    assert 'test_signed_permit_omits_dependency_but_C_source_reconstruction_rejects' in testlog
    formal=json.loads((ROOT/'research/formal39/formal39_report.json').read_text(encoding='utf8'))
    cases=formal['official_cases']
    assert len(cases)==39 and len({a['id'] for a in cases})==39
    assert formal['summary']['official_complete_pass']==0
    assert all(a['official_complete_pass'] is False for a in cases)
    files=[
      d/'phase15_pay_report.json',
      d/'pay_witness.json',
      d/'pay_w.sqlite',
      d/'tool.sqlite',
      OUT/'phase15_pay_test_output.txt',
      OUT/'phase15_pay_process_output.txt',
      OUT/'phase15_formal39_output.txt',
    ]
    for p in files:assert p.is_file(),p
    report={
        'contract':'ZJJ-CORE-2.6-R2','phase':15,'status':'PAY_LAB_EXPERIMENTAL_NOT_OFFICIAL_CONFORMANT',
        'official':{'PASS':0,'FAIL':0,'BLOCKED':39},
        'original_artifact_sha256':EXPECTED,
        'source_sha256':{p:sha(ROOT/p) for p in SOURCES},
        'raw_evidence_sha256':{str(p.relative_to(ROOT)):sha(p) for p in files},
        'process_audit':audit['audit'],
        'test_count':int(match.group(1)),
        'scoped_facets':{
            'CORE-01/PAY-1':'Proposer/C/X/W separate OS processes; externally X-signed acceptance and result, one durable acceptance, tool simulation, read-only audit',
            'CORE-03/PAY-1':'Signed Permit deliberately omits EXPERIENCE; W recomputes RequiredDeps from C-signed current source corpus and rejects',
            'CORE-13/PAY-1':'C revocation before finalization and resource race after prepare reject; Phase11 dispatch clocks remain laboratory',
            'AUD-02A/B/C':'Phase11/12 prior scoped ledger reattestation preserved; not new complete Phase15 evidence',
        },
        'remaining_blockers':[
            'C/X/E public fixture keys are not independently custodied or production-enrolled',
            'No authenticated W-to-X request channel or independent X admission policy',
            'C-signed source corpus is synthetic and not real evidence provenance',
            'PAY trusted clock requires same timestamp at Prepare and Finalize, disallowing production latency',
            'No deployed cross-profile single W or cross-profile atomicity',
            'ToolLedger is a local simulator, not physical finance/industrial/clinical effect',
            'Full 39 official semantic scenarios, distributed transport and authenticated STATUS/Result lifecycle unproven',
        ],
        'source_date_epoch':'2026-10-09T00:00:00Z',
        'environment':{'python':sys.version.split()[0],'platform':platform.platform()},
        'archive_note':'ZIP entries are deterministic for identical witness bytes; independent runs may differ because simulated ledger origin is random.',
    }
    jsonout(OUT/'phase15_pay_report.json',report)
    with (OUT/'phase15_39case_matrix.csv').open('w',newline='',encoding='utf-8-sig') as fp:
        cw=csv.writer(fp)
        cw.writerow(['Official case ID','Original profile','Original expected','Official status',
                     'Phase15 partial evidence','Missing for full PASS'])
        for x in cases:
            support=report['scoped_facets'].get(x['id']+'/PAY-1','') if x['id'] in ('CORE-01','CORE-03','CORE-13') else ''
            cw.writerow([x['id'],x['profile'],x['official_original_expected'],x['status'],
                support,'; '.join(x['full_case_unmet_requirements'])])
    ARCHIVE.parent.mkdir(exist_ok=True)
    contents=sorted(p for p in ROOT.rglob('*') if p.is_file()
             and '.git' not in p.parts and '__pycache__' not in p.parts
             and not p.name.endswith(('.pyc','.pyo'))
             and p.suffix.lower()!='.zip')
    with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for p in contents:
            info=zipfile.ZipInfo(str(p.relative_to(ROOT)),date_time=(2026,10,9,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16
            z.writestr(info,p.read_bytes())
    external={'path':str(ARCHIVE.relative_to(ROOT)),'sha256':sha(ARCHIVE),
              'entries':len(contents),'note':'archive contains report without self-referential ZIP digest'}
    report['delivery_archive']=external
    jsonout(OUT/'phase15_pay_report.json',report)
    return {'status':report['status'],'formal':report['official'],'tests':report['test_count'],
            'audit':report['process_audit'],'archive':external}
if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
