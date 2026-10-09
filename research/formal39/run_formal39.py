"""Fail-closed formal-case acceptance audit for the pinned ZJJ-CORE-2.6-R2 manifest.

'Formally accepted' requires complete official case semantics including trusted
control/source provenance, original Schemas, serialized W and cross-profile
trace coverage. Partial witnesses NEVER automatically become a full PASS.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,platform,sys
from datetime import datetime,timezone
from pathlib import Path
from research.conformance39.run39 import check_manifest,check_schemas,index_tests,run_case,sha256
from research.conformance39.cases import CASES, EXPECTED_IDS
from .actual_probes import run_all

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def exact_manifest(root):
    state=check_manifest(root)
    if state['status']!='EXACT_OFFICIAL_MANIFEST_VERIFIED':
        raise RuntimeError('FAIL_CLOSED: Original official semantic_cases.json is not verified: '+str(state))
    data=json.loads((Path(root)/'system_dev/v26/semantic_cases.json').read_text(encoding='utf8'))
    if len(data['cases'])!=39 or [x['id'] for x in data['cases']]!=EXPECTED_IDS:
        raise RuntimeError('FAIL_CLOSED: 39 official case IDs differ')
    return data,state

def case_status(local,probe_values,missing):
    # A passing unit test only shows a slice of the contract. PASS requires a
    # complete, authenticated full-protocol test whose obligations have been
    # independently discharged; no current case has such a transcript.
    if local['status']=='LOCAL_WITNESS_FAILED' or any(x['status']=='FAIL_SCOPED_INTEGRATION' for x in probe_values):
        return 'FAIL_OBSERVED_SUBTEST'
    if local['status']!='PARTIAL_WITNESSES_PASS':
        return 'BLOCKED_EVIDENCE_RUNNER'
    if not missing:
        # Fail closed: an empty checklist alone never constitutes a proof.
        return 'BLOCKED_INDEPENDENT_FULL_TRACE_REQUIRED'
    return 'BLOCKED_FULL_CONFORMANCE'

def generate(root=ROOT,output=HERE/'formal39_report.json'):
    manifest,original=exact_manifest(root)
    schemas=check_schemas(root)
    if schemas['PAY-1']['status']!='EXACT_ORIGINAL_SCHEMA_LOADED':
        raise RuntimeError('FAIL_CLOSED: pinned original PAY Schema is unavailable')
    # Validate actual emitted IND/MED signed records with unmodified original
    # schemas, not only the schema meta-contract. This gate caught the previous
    # private EVIDENCE namespace defect in wire deps.
    from research.phase8.run_phase8 import run_official_schemas
    emitted_scene_schemas=run_official_schemas(root,require=False)
    map_probe,run_probe=run_all()
    # Phase 11 is never promoted to official PASS by attaching a report.
    # Reject stale / tampered snapshots by checking every declared file hash.
    phase11_path=ROOT/'research/phase11/phase11_report.json'
    phase11=None
    if phase11_path.is_file():
        candidate=json.loads(phase11_path.read_text(encoding='utf8'))
        good=(candidate.get('phase')==11 and candidate.get('official_complete_passes_from_phase11')==0)
        for rel,sha in candidate.get('source_sha256',{}).items():
            path=ROOT/rel
            good=good and path.is_file() and sha256(path)==sha
        if not good:raise RuntimeError('PHASE11_EVIDENCE_STALE_OR_CODE_TAMPER')
        for item in candidate['targeted_slices'].values():
            path=ROOT/item['path']
            if not path.is_file() or sha256(path)!=item['sha256']:
                raise RuntimeError('PHASE11_EVIDENCE_HASH_MISMATCH')
        phase11=candidate
    # Phase12 scoped addendum: independently hash-check evidence AND the exact
    # experiment source files. Never promote these facets to official full PASS.
    phase12_path=ROOT/'research/phase12/phase12_report.json'
    phase12=None
    if phase12_path.is_file():
        candidate=json.loads(phase12_path.read_text(encoding='utf8'))
        if candidate.get('phase')!=12 or candidate.get('official_complete_passes_from_phase12')!=0:
            raise RuntimeError('PHASE12_REPORT_CONTRACT_INVALID')
        if set(candidate.get('targeted_slices',{})) != {'CORE-15','AUD-02C'}:
            raise RuntimeError('PHASE12_CASE_SET_INVALID')
        for rel,want in candidate.get('source_sha256',{}).items():
            path=ROOT/rel
            if not path.is_file() or sha256(path)!=want:
                raise RuntimeError('PHASE12_SOURCE_STALE_OR_TAMPERED: '+rel)
        for item in [*candidate['targeted_slices'].values(),candidate['phase11_pay_gap']]:
            path=ROOT/item['path']
            if not path.is_file() or sha256(path)!=item['sha256']:
                raise RuntimeError('PHASE12_EVIDENCE_HASH_MISMATCH')
        phase12=candidate
    tests=index_tests()
    per=[];logs=[];counts={}
    for spec,c in zip(CASES,manifest['cases']):
        w=run_case(spec,tests)
        names=map_probe.get(spec.id,[])
        got=[run_probe[k] for k in names]
        problems=list(spec.missing)
        if c['profile'] in ('IND-DEMO-1','MED-DEMO-1'):
            if schemas[c['profile']]['status']!='EXACT_ORIGINAL_SCHEMA_LOADED':
                problems.insert(0,'official full original '+c['profile']+' JSON Schema not installed/verified')
        elif c['profile'] in ('ALL','IND-DEMO-1,MED-DEMO-1'):
            for p in ('IND-DEMO-1','MED-DEMO-1'):
                if schemas[p]['status']!='EXACT_ORIGINAL_SCHEMA_LOADED':
                    problems.insert(0,p+' original official Schema not installed')
        if phase11 and spec.id in phase11['targeted_slices']:
            # Previous phases recorded what was then unimplemented. Phase11 has
            # now provided local executable facets, but is not a production
            # control authority, trusted-clock service or complete formal test.
            phase11_remaining={
              'CORE-03':[
                'Local triple-profile signed G reissue rejection exists, but the independently operated C/E admission and transitive current issuer graph are not established',
                'Complete official case proof over all authorized dependency shapes, T/F/U and transport/scope/lifecycle variants requires independent review'],
              'CORE-13':[
                'Local signed-clock cancel/unknown/expiry and legacy endpoint fail-closed exist; externally trusted C time and full interval provenance remain unproven',
                'Complete concurrent cancellation versus real tool dispatch, unknown effect reconciliation and one deployed cross-profile W still missing'],
              'AUD-02A':[
                'All three local R2 ledgers reattest expired first TOOL_FINAL and settle once; real registered external tool authorization and physical-effect audit are absent',
                'Complete protocol negative variants, recovery and message/STATUS transport lifecycle are not independently demonstrated'],
              'AUD-02B':[
                'Three profiles demonstrate local C-signed same-ledger key rollover and same-fact settlement; independent C root-key approval and external ledger continuity are not established',
                'Tool-equivocation HALTED path is local; real contradictory bound tool outputs and full three-profile STATUS/receipt behavior require verification'],
            }
            problems=phase11_remaining[spec.id]
        if phase12 and spec.id in phase12['targeted_slices']:
            remaining12={
                'CORE-15': [
                    'Three-profile local serialized C-clocked CANCEL/CLAIM racing and subprocess crash-after-claim observed; distributed delivery vs external tool started/effect-unknown reconciliation unproven',
                    'Globally operated W, independently governed C/E, transport lifecycle and exhaustive scheduler interleavings unverified'],
                'AUD-02C': [
                    'PAY prior ledger-free first settlement was reproducible; hardened PAY now verifies immutable original fact and origin, alongside IND/MED; real authenticated external ledger outage and recovery unproven',
                    'Proof against forged negative final, across independent tool service restart and all official status/transport branches still missing']}
            problems=remaining12[spec.id]
        s=case_status(w,got,problems)
        counts[s]=counts.get(s,0)+1
        logid=spec.id.replace('/','_')
        ldir=HERE/'logs';ldir.mkdir(parents=True,exist_ok=True)
        logfile=ldir/(logid+'.txt')
        logfile.write_text(w['runner_log'],encoding='utf-8')
        logs.append((logid,str(logfile.relative_to(HERE)),sha256(logfile)))
        per.append({'id':spec.id,'profile':c['profile'],'official_original_scenario':c['scenario'],
                    'official_original_expected':c['expected'],'status':s,
                    'official_complete_pass':False,'official_manifest_source':'PINNED_UPSTREAM_GIT_BLOB',
                    'partial_witnesses':{'status':w['status'],'executed':w.get('run',0),'passed':w.get('passed',0),
                                        'test_ids':w.get('test_ids',[]),'test_log':str(logfile.relative_to(HERE)),
                                        'log_sha256':sha256(logfile),'failed':w.get('failures',[]),'errors':w.get('errors',[])},
                    'phase11_scoped_signed_trace':(phase11['targeted_slices'][spec.id] if phase11 and spec.id in phase11['targeted_slices'] else None),
                    'phase12_scoped_signed_trace':(phase12['targeted_slices'][spec.id] if phase12 and spec.id in phase12['targeted_slices'] else None),
                    'fresh_end_to_end_facets':{k:run_probe[k]['status'] for k in names},
                    'full_case_unmet_requirements':problems,
                    'reason_full_pass_not_issued':'Missing full-case obligations and independent trusted-authority transcript' if problems else 'Missing independently reviewed full transcript'})
    full_pass=sum(x['official_complete_pass'] for x in per)
    failed_cases=[x['id'] for x in per if x['status']=='FAIL_OBSERVED_SUBTEST']
    summary={'official_cases':39,'official_complete_pass':full_pass,
             'official_complete_fail':0, # Only a complete official counterexample permits FAIL, see observed subtests separately.
             'case_facets_with_fresh_integrated_probes':sum(bool(x['fresh_end_to_end_facets']) for x in per),
             'independent_integrated_probe_functions':len(run_probe),
             'independent_integrated_probes_passed':sum(x['status']=='PASS_SCOPED_INTEGRATION' for x in run_probe.values()),
             'local_witness_cases_executed':sum(x['partial_witnesses']['executed']>0 for x in per),
             'local_witness_tests_executed':sum(x['partial_witnesses']['executed'] for x in per),
             'local_witness_tests_passed':sum(x['partial_witnesses']['passed'] for x in per),
             'observed_subtest_failure_cases':failed_cases,'case_statuses':counts}
    summary['phase11_targeted_case_facets']=len(phase11['targeted_slices']) if phase11 else 0
    summary['phase11_unit_facet_checks']=phase11['phase11_unittests']['run'] if phase11 else 0
    summary['phase11_signed_profile_transcripts']=sum(len(x['profiles']) for x in phase11['targeted_slices'].values()) if phase11 else 0
    summary['phase12_targeted_case_facets']=len(phase12['targeted_slices']) if phase12 else 0
    summary['phase12_signed_profile_transcripts']=sum(len(x['profiles']) for x in phase12['targeted_slices'].values()) if phase12 else 0
    summary['official_scene_objects_structurally_passed']=sum(v.get('checked_objects',0) for v in emitted_scene_schemas.values())
    summary['official_scene_schema_failures']=sum(len(v.get('rejected_objects',[])) for v in emitted_scene_schemas.values())
    report={'date_utc':datetime.now(timezone.utc).isoformat(),'contract':'ZJJ-CORE-2.6-R2',
        'status':'FORMAL_GATE_EXECUTED_BUT_NOT_YET_ALL_CONFORMANT',
        'upstream':{'repository':'yumir3297/Cryptography-Technical-Competition',
            'manifest':original,'schemas':schemas},
        'phase11_scoped_integration':phase11,'phase12_scoped_integration':phase12,'summary':summary,'fresh_integration':run_probe,'official_scene_schema_emitted_objects':emitted_scene_schemas,'official_cases':per,
        'trust_model':{'C_control':'in-process signed laboratory controller; not full production trust/PoP provenance',
            'E_source':'signed synthetic source inputs; current complete versioned certification not integrated across profiles',
            'W':'Phase12 scoped PAY ledger gate and signed-C CANCEL/CLAIM races extend Phase11; PAY/IND/MED separate SQLite W adapters; global W and external governance incomplete',
            'Tool':'Phase12 PAY ledger-origin and first-fact checks integrated in stricter adapter; all profiles still use simulated tool SQLite, no physical effect proof or distributed atomic commit',
            'transport':'transport route/0-RTT and complete signed STATUS/Result lifecycle incomplete'},
        'runner_integrity':{'formal_runner_sha256':sha256(__file__),
            'probe_source_sha256':sha256(HERE/'actual_probes.py'),
            'manifest_sha256':sha256(Path(root)/'system_dev/v26/semantic_cases.json'),
            'logs':[{'case':cid,'path':path,'sha256':sha} for cid,path,sha in logs]},
        'execution_environment':{'python':sys.version.split()[0],'platform':platform.platform()}}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    table=HERE/'formal39_matrix.csv'
    with table.open('w',encoding='utf-8-sig',newline='') as out:
        writer=csv.writer(out);writer.writerow(['Official case','Profile','Official scenario','Official expected','Formal status','Local tests run','Local passed','Fresh E2E facet checks','Phase11 signed case facet evidence','Phase12 signed case facet evidence','Remaining obligations'])
        for r in per:writer.writerow([r['id'],r['profile'],r['official_original_scenario'],r['official_original_expected'],
          r['status'],r['partial_witnesses']['executed'],r['partial_witnesses']['passed'],
          ';'.join(f'{k}:{v}' for k,v in r['fresh_end_to_end_facets'].items()),
          r['phase11_scoped_signed_trace']['path'] if r['phase11_scoped_signed_trace'] else '',
          r['phase12_scoped_signed_trace']['path'] if r['phase12_scoped_signed_trace'] else '',
          '; '.join(r['full_case_unmet_requirements'])])
    md=[
        '# ZJJ-CORE-2.6-R2：39项正式验收与Phase11–12独立局部证据',
        '',
        '**核心说明：本报告执行了全部39项的原始清单校验、局部独立单元测试以及选定的端到端专项探针；尚未完成的整条用例不得记为PASS。**',
        '',f'- 官方清单：Git blob `{original["git_blob"]}`，固定版本核验通过',
        f'- PAY 官方 Schema：`{schemas["PAY-1"]["status"]}`',
        f'- 工业官方 Schema：`{schemas["IND-DEMO-1"]["status"]}`',
        f'- 医疗官方 Schema：`{schemas["MED-DEMO-1"]["status"]}`',
        f'- 39项局部关联测试：{summary["local_witness_tests_passed"]}/{summary["local_witness_tests_executed"]}',
        f'- 新增独立端到端探针：{summary["independent_integrated_probes_passed"]}/{summary["independent_integrated_probe_functions"]} 个通过',
        f'- 有新增端到端验证切面的正式用例：{summary["case_facets_with_fresh_integrated_probes"]}/39',
        f'- Phase11四项重点专项签名切面：{summary["phase11_targeted_case_facets"]}/4 项，带原始输入/签名/C证书/SQLite事务审计（仅局部）',
        f'- Phase11新增检查：{summary["phase11_unit_facet_checks"]} 项，完整Profile切面 {summary["phase11_signed_profile_transcripts"]} 组',
        f'- Phase12新增局部证据：{summary["phase12_targeted_case_facets"]}/2 官方用例，{summary["phase12_signed_profile_transcripts"]} 组三Profile运行记录',
        f'- **正式完整通过：{full_pass}/39**',
        '',
        '## 为什么仍未颁发完整PASS',
        '',
        '虽然Phase11已有本地PoP/签名C控制/跨IND-MED ToolFinal/局部依赖闭包和统一领取取消语义，但远端真实C/E可信治理、全局统一部署的W、物理工具账和完整传输/STATUS尚未闭合。每条用例的具体缺口、实际测试ID和测试日志见JSON/CSV。',
        '',
        '## 高价值已执行的端到端验证',
        '',
        '| 专项 | 实际结果 |', '|---|---|',
    ]
    for k,v in run_probe.items():md.append('| '+k+' | '+v['status']+' |')
    md.extend(['','## 复现','',
       '将ZIP解压到仓库根目录：依次执行 `python -m research.phase11.run_phase11`、`python -m research.phase12.run_phase12` 和 `python -m research.formal39.run_formal39`。',
       '若新增官方原始 Schema 文件，程序会重新读取并校验固定 Git blob；完整PASS仍需专门的独立签名及信任证据证明，不由文件存在自动赋予。',
       '','## 验收口径','',
       '`BLOCKED_FULL_CONFORMANCE`不是FAIL：已经运行过局部及部分端到端检查，但缺少完整可信证据。',
       '`FAIL_OBSERVED_SUBTEST`表示确实发现可重现的测试违例，需要修复；它也不等同于已穷尽正式全量验收。',
       '将来只有提供完整检查、签名、权威状态、全部预期/副作用证明后才可单独转为 `PASS`。',''])
    (HERE/'formal39_summary.md').write_text('\n'.join(md),encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--upstream-root',type=Path,default=ROOT)
    args=p.parse_args()
    res=generate(args.upstream_root)
    print(json.dumps({'upstream_manifest':res['upstream']['manifest'],'schema_statuses':{k:v['status'] for k,v in res['upstream']['schemas'].items()},
       'summary':res['summary']},ensure_ascii=False,indent=2))
    if res['summary']['observed_subtest_failure_cases'] or res['summary']['official_scene_schema_failures'] or res['summary']['independent_integrated_probes_passed']!=res['summary']['independent_integrated_probe_functions']:
        return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
