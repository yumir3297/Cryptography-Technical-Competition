"""Freeze public Phase17 IND evidence only; never archive private signer material."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,shutil,zipfile
from pathlib import Path
from research.phase14.build_report import EXPECTED

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'research_evidence/phase17'
ZIP=ROOT/'research_archives/ZJJ_CORE_2_6_R2_Phase17_Industrial_Minimum_20261010.zip'
CODE_PREFIX=('research/phase8/','research/phase6/','research/phase11/',
             'research/phase12/','research/phase13/','research/phase14/',
             'research/phase16/','research/phase17/','research/formal39/',
             'research/reference_executor/','research/strict_v26/','system_dev/v26/')
EXTRA=('.github/workflows/phase17-ind.yml','requirements_phase13.txt')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')
def run(inp):
    inp=Path(inp).resolve()
    require=lambda cond,why:cond or (_ for _ in ()).throw(AssertionError(why))
    require(inp.is_dir() and (inp/'signers').is_dir(),'MISSING_PRIVATE_SIGNERS_FOR_LAB')
    require(len(list((inp/'signers').glob('*.key')))==9,'ROLE_PROVISIONING')
    signed=json.loads((inp/'phase17_process_report.json').read_text(encoding='utf-8'))
    audit=signed['readonly_audit']
    require(signed['official_complete_pass'] is False and signed['stage_count']==25,'LOOP_STATUS')
    require(audit['E_source_attestation_verified'] and
            audit['forged_E_rejected'] and audit['forged_X_rejected'] and
            audit['forged_W_rejected'] and audit['recovery_no_second_effect'],'MISSING_NEGATIVE_GUARDS')
    require(audit['W_accept_count']==audit['W_call_count']==audit['W_settlement_count']==
            audit['durable_effects']==1,'COUNTS_NOT_SINGLE')
    for p,want in EXPECTED.items():require(sha(ROOT/p)==want,'OFFICIAL_CONTRACT_MUTATED:'+p)
    formal=json.loads((ROOT/'research/formal39/formal39_report.json').read_text(encoding='utf-8'))
    cases=formal['official_cases']
    require(len(cases)==39 and formal['summary']['official_complete_pass']==0,'OFFICIAL_MATRIX')
    require(all(not c['official_complete_pass'] for c in cases),'FALSE_OFFICIAL_PASS')
    tests=(OUT/'minimal_loop_tests.txt').read_text(encoding='utf-8')
    n=re.search(r'Ran (\d+) tests in ',tests)
    require(n is not None and int(n.group(1))>=6 and re.search(r'\nOK\s*$',tests),'TEST_FAILED')
    dest=OUT/'public_process';dest.mkdir(parents=True,exist_ok=True)
    copied=[]
    for name in ('phase14_witness.json','witness.json','phase17_process_report.json','w.sqlite','tool.sqlite'):
        src=inp/name
        require(src.is_file(),'REQUIRED_EVIDENCE_MISSING:'+name)
        shutil.copy2(src,dest/name);copied.append(dest/name)
    # The secret directory remains at RUNNER_TEMP, outside published evidence
    # and outside archive. Fail closed if any key ends up in the artifact root.
    require(not list(OUT.rglob('*.key')),'LEAKED_SECRET_KEY_FILE')
    audit_file=OUT/'phase17_report.json'
    public_report={'phase':17,'profile':'IND-DEMO-1','project':'ZJJ-CORE-2.6-R2',
      'scope':'IND_MINIMUM_CLOSED_LOOP_RESEARCH_ONLY',
      'official_full_conformance':{'PASS':0,'FAIL':0,'BLOCKED_FULL_CONFORMANCE':39},
      'test_count':int(n.group(1)),'stage_count':signed['stage_count'],
      'readonly_audit':audit,
      'original_contract_sha256':EXPECTED,
      'public_witness_sha256':{str(f.relative_to(ROOT)):sha(f) for f in copied},
      'private_signer_files_exported':False,
      'limitations':signed['limitations'],
      'important':'A fresh per-run key is not independently custodied: the single provisioner sees all keys and runner shares OS credentials. Device effect is simulated only.'}
    write(audit_file,public_report)
    with (OUT/'phase17_39case_matrix.csv').open('w',newline='',encoding='utf-8-sig') as fo:
        wr=csv.writer(fo);wr.writerow(['Official case','Official profile','Original scenario','Expected',
                                       'Official status','Phase17 scoped contribution','Still unmet'])
        for c in cases:
            note=('IND minimal full lab flow: signed source, role approvals, W acceptance, '
                  'tool logged recovery and readonly audit' if c['id']=='CORE-01' else
                  'Lost result recovery with same signed request and no new tool fact'
                  if c['id'] in ('CORE-13','CORE-15','AUD-02C') else '')
            wr.writerow([c['id'],c['profile'],c['official_original_scenario'],
                 c['official_original_expected'],c['status'],note,
                 '; '.join(c['full_case_unmet_requirements'])])
    ZIP.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for f in ROOT.rglob('*'):
        if not f.is_file():continue
        r=f.relative_to(ROOT);s=r.as_posix()
        if s.startswith(CODE_PREFIX) or s in EXTRA or s.startswith('research_evidence/phase17/'):
            if (f.suffix in ('.pyc','.pyo','.key','.zip') or '__pycache__' in f.parts or
                '/signers/' in '/'+s+'/'):
                continue
            files.append(f)
    files=sorted(set(files))
    require(all(x.suffix!='.key' and 'signers' not in x.parts for x in files),'SECRET_LEAK')
    with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for f in files:
            arc=f.relative_to(ROOT).as_posix()
            info=zipfile.ZipInfo(arc,date_time=(2026,10,10,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,f.read_bytes())
    public_report['archive']={'path':str(ZIP.relative_to(ROOT)),
                              'sha256':sha(ZIP),'entry_count':len(files),
                              'contains_private_keys':False}
    write(audit_file,public_report)
    return {'status':'PASS_MINIMUM_INDUSTRIAL_RESEARCH_LAB','phase':17,
        'tests':int(n.group(1)),'stage_count':signed['stage_count'],
        'archive':public_report['archive'],
        'official_full_conformance':public_report['official_full_conformance']}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);args=p.parse_args()
    print(json.dumps(run(args.input),ensure_ascii=False))
