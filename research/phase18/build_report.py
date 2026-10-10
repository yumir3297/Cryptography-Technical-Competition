"""Phase18 immutable public artifact builder, with explicit forbidden-key scan."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,shutil,zipfile
from pathlib import Path
from research.phase14.build_report import EXPECTED
ROOT=Path(__file__).resolve().parents[2]
PUBLIC=ROOT/'research_evidence/phase18'
ARCHIVE=ROOT/'research_archives/ZJJ_CORE_2_6_R2_Phase18_Industrial_Role_Isolation_20261010.zip'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')

def run(source):
    source=Path(source).resolve()
    lab=json.loads((source/'phase18_process_report.json').read_text(encoding='utf-8'))
    audit=lab['readonly_audit'];access=lab['OS_access_audit']
    assert lab['stage_count']==25 and lab['official_complete_pass'] is False
    assert access['roles_verified']==8 and access['unprivileged_W_cannot_read'] and access['other_roles_cannot_read']
    assert audit['W_accept_count']==audit['W_call_count']==audit['W_settlement_count']==audit['durable_effects']==1
    assert audit['recovery_no_second_effect'] and audit['forged_E_rejected'] and audit['forged_X_rejected']
    assert audit['forged_W_rejected']
    assert set(('C','E','H','G','U','X','TOOL')).issubset({v['role'] for v in lab['public_signer_receipts']})
    for path,wanted in EXPECTED.items():
        assert sha(ROOT/path)==wanted,('UNMODIFIED_ORIGINAL_REQUIRED',path)
    formal=json.loads((ROOT/'research/formal39/formal39_report.json').read_text(encoding='utf-8'))
    cases=formal['official_cases']
    assert len(cases)==39 and formal['summary']['official_complete_pass']==0
    assert all(not x['official_complete_pass'] for x in cases)
    tests=(PUBLIC/'test_isolated_signers.txt').read_text(encoding='utf-8')
    match=re.search(r'Ran (\d+) tests in ',tests)
    assert match and int(match.group(1))>=7 and re.search(r'\nOK\s*$',tests)
    root=PUBLIC/'public_process'
    root.mkdir(parents=True,exist_ok=True)
    collected=[]
    for f in ('phase14_witness.json','witness.json','phase18_process_report.json',
              'w.sqlite','tool.sqlite'):
        src=source/f;dst=root/f
        assert src.is_file(),('MISSING_FILE',f)
        shutil.copy2(src,dst);collected.append(dst)
    assert not list(PUBLIC.rglob('*.key')), 'PRIVATE_KEY_LEAK_IN_EVIDENCE'
    report={'phase':18,'project':'ZJJ-CORE-2.6-R2',
      'candidate':'IND_LINUX_DAC_ROLE_SIGNER_ISOLATION_LAB',
      'status':'PASS_SCOPED_LAB_ONLY','profile':'IND-DEMO-1','test_count':int(match.group(1)),
      'stages':lab['stage_count'],'OS_access_audit':access,
      'public_role_signer_receipt_count':len(lab['public_signer_receipts']),
      'readonly_audit':audit,'evidence_hashes':{str(p.relative_to(ROOT)):sha(p) for p in collected},
      'original_artifact_sha256':EXPECTED,
      'published_private_key_files':0,
      'official_conformance':{'FULL_PASS':0,'FULL_FAIL':0,'BLOCKED_FULL_CONFORMANCE':39},
      'limitations':lab['limitations']}
    write(PUBLIC/'phase18_report.json',report)
    with (PUBLIC/'phase18_39case_matrix.csv').open('w',newline='',encoding='utf-8-sig') as ff:
        wr=csv.writer(ff)
        wr.writerow(['Official ID','Profile','Original requirement','Original expected',
                     'Official state','Phase18 IND scoped evidence','Unmet official obligations'])
        for x in cases:
            note=('Per-role Linux DAC ownership and signed E/C/H/G/U/X/Tool chain; '
                  '1 simulated IND accept/dispatch/settle, 1 crash-recovered tool fact'
                  if x['id'] in ('CORE-01','CORE-13','CORE-15','AUD-02C') else '')
            wr.writerow([x['id'],x['profile'],x['official_original_scenario'],
                     x['official_original_expected'],x['status'],note,
                     '; '.join(x['full_case_unmet_requirements'])])
    whitelisted=[]
    prefixes=('research/phase18/','research/phase17/','research/phase16/',
       'research/phase14/','research/phase13/','research/phase12/','research/phase11/',
       'research/phase8/','research/phase6/','research/reference_executor/',
       'research/strict_v26/','research/formal39/','system_dev/v26/',
       'research_evidence/phase18/')
    include={'.github/workflows/phase18-ind.yml','requirements_phase13.txt'}
    for f in ROOT.rglob('*'):
        if not f.is_file():continue
        name=f.relative_to(ROOT).as_posix()
        if not (name.startswith(prefixes) or name in include):continue
        if ('signers' in f.parts or name.startswith('.phase18_lab/') or
            f.suffix in ('.pyc','.pyo','.key','.zip') or '__pycache__' in f.parts):
            continue
        whitelisted.append(f)
    whitelisted=sorted(set(whitelisted))
    assert whitelisted and all('.key' not in x.name for x in whitelisted)
    ARCHIVE.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(ARCHIVE,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for f in whitelisted:
            info=zipfile.ZipInfo(f.relative_to(ROOT).as_posix(),date_time=(2026,10,10,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16
            z.writestr(info,f.read_bytes())
    report['archive']={'path':str(ARCHIVE.relative_to(ROOT)),'sha256':sha(ARCHIVE),
         'file_count':len(whitelisted),'secret_key_files':0}
    write(PUBLIC/'phase18_report.json',report)
    return {'phase':18,'result':report['status'],'tests':report['test_count'],
            'official':report['official_conformance'],'archive':report['archive']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True)
    print(json.dumps(run(p.parse_args().input),ensure_ascii=False))
