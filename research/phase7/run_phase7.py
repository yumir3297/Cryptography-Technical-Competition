"""Run pinned original PAY Schema + Phase 1-6 regressions and Phase-7 mutation checks.

This is a completed PAY structural gate, NOT all-39 semantic conformance.
"""
from __future__ import annotations
import hashlib,io,json,platform,sys,unittest
from datetime import datetime,timezone
from importlib import metadata
from pathlib import Path
ROOT_DIR=Path(__file__).resolve().parents[2]
if str(ROOT_DIR/'research'/'assurance') not in sys.path:sys.path.insert(0,str(ROOT_DIR/'research'/'assurance'))
from research.assurance import test_abstract_checker,test_deny_range_model
from research.reference_executor import test_reference
from research.strict_v26 import test_pay_history,test_pay_dependencies,test_upstream_schema
from research.phase4 import test_flow
from research.phase5 import test_durable_w
from research.phase6 import test_trusted_final
from research.phase7 import test_official_contract,test_guarded_dispatch,test_dispatch_gap
from research.phase7.test_official_contract import all_objects,OfficialPaySchemaTests,ROOT
from research.phase5.run_phase5 import schema_probe

DIR=Path(__file__).resolve().parent
MODULES=(test_abstract_checker,test_deny_range_model,test_reference,test_pay_history,test_pay_dependencies,
         test_upstream_schema,test_flow,test_durable_w,test_trusted_final,test_official_contract,test_guarded_dispatch,test_dispatch_gap)
CASES=('CORE-01 CORE-02 CORE-03 CORE-04 CORE-05 CORE-06 CORE-07 CORE-08 CORE-09 CORE-10 '
       'CORE-11 CORE-12 CORE-13 CORE-14 CORE-15 CORE-16 CORE-17 CORE-18 CORE-19 CORE-20 '
       'PAY-01 PAY-02 PAY-03 PAY-04 PAY-05 IND-01 IND-02 IND-03 IND-04 '
       'MED-01 MED-02 MED-03 MED-04 SC-01 SC-02 AUD-02A AUD-02B AUD-02C AUD-02D').split()


def main():
    gate,source=schema_probe(ROOT)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in MODULES)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (DIR/'test_log.txt').write_text(stream.getvalue(),encoding='utf-8')
    if not result.wasSuccessful():
        print(stream.getvalue()[-6000:]);return 1
    # Exact official Draft-2020-12 definitions, no substitute schema.
    cls=OfficialPaySchemaTests
    cls.setUpClass()
    counts={'risk_paths':len(cls.objects),'valid_emitted_objects':0,'removed_required_outer':0,
            'extra_outer_properties':0,'removed_required_inner':0,'wrong_profile':0,
            'support_objects':2,'total_positive_plus_rejection_probes':0}
    for risk,objects in cls.objects.items():
        for kind,record in objects:
            counts['valid_emitted_objects']+=1
            counts['removed_required_outer']+=len(record)
            counts['extra_outer_properties']+=1
            counts['wrong_profile']+=2
            topdef=gate.defs[kind]
            base=topdef['properties']['value'] if kind.startswith('Record_') else topdef['properties']['body']['properties']['payload']
            counts['removed_required_inner']+=len(base.get('required',[]))
    counts['total_positive_plus_rejection_probes']=sum(counts[k] for k in (
        'valid_emitted_objects','removed_required_outer','extra_outer_properties','removed_required_inner','wrong_profile','support_objects'))
    # Cross-check PINNED official case metadata when source manifest exists: do not mark PASS unless
    # every case has a dedicated executable witness, semantics, and complete W state evidence.
    manifest=ROOT/'system_dev/v26/semantic_cases.json'
    status='REMOTE_GITHUB_CASE_IDS_CHECKED__LOCAL_FULL_MANIFEST_NOT_INSTALLED'
    if manifest.exists():
        doc=json.loads(manifest.read_text(encoding='utf-8'))
        assert doc['contract']=='ZJJ-CORE-2.6-R2' and [x['id'] for x in doc['cases']]==CASES
        status='EXACT_LOCAL_UPSTREAM_39_CASES_LOADED'
    # The user must not interpret tests of a PAY fixture as all-profile conformance.
    matrices=[]
    for cid in CASES:
        if cid.startswith(('IND-','MED-')):level='PROFILE_NOT_IMPLEMENTED_IN_STRICT_ENGINE'
        elif cid=='SC-02':level='PAY_CROSS_PROFILE_SHAPE_REJECT_ONLY'
        elif cid in ('AUD-02A','AUD-02B','AUD-02C','AUD-02D'):
            level='PAY_LOCAL_TOOL_LEDGER_PARTIAL'
        elif cid.startswith('PAY-'):level='PAY_LOCAL_SIGNED_FLOW_PARTIAL'
        else:level='LOCAL_MODEL_OR_PAY_FIXTURE_PARTIAL'
        matrices.append({'id':cid,'official_full_conformance':'NOT_RUN','phase7_level':level,
                         'official_acceptance':False,'notes':'Requires complete independent case orchestration & trusted C/E/W inputs; schema alone does not establish semantic correctness'})
    (DIR/'conformance_matrix.json').write_text(json.dumps(matrices,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'generated_utc':datetime.now(timezone.utc).isoformat(),
            'upstream_repository':'yumir3297/Cryptography-Technical-Competition',
            'protocol':'ZJJ-CORE-2.6-R2',
            'source_schema':source,
            'official_schema_validation':{'status':'PASS_PAY1_DRAFT_2020_12_STRUCTURAL_SUBSET',
                  'schema_defs':len(gate.defs),'mutation_cases':counts,
                  'warning':'x-zjj-order and semantic constraints are custom annotations, not enforced by jsonschema'},
            'combined_regression':{'tests':result.testsRun,'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
                  'failed':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)},
            'official_39_semantic':{'total':len(CASES),'fully_passed':0,'fully_run':0,
                      'manifest_provenance':status,'note':'Local tests are fixtures, not official full-case executions'},
            'phase7_dispatch_gate':{'status':'LAB_MITIGATION_TESTED_NOT_PRODUCTION_COMPLETE',
                      'issue':'Legacy FinalW.claim_bound accepted a dispatch after C policy revocation',
                      'disclosed_reproduction_test':'test_dispatch_gap.DisclosedProtocolGap',
                      'mitigation':'GuardedFinalW C-root signed current-state rows plus same-SQLite transaction check; fail closed on missing, revoked, changed or stale deps',
                      'limitations':'Initial accepted dependency set remains a trusted fixture; root enrollment/authenticated E and real source publishers not integrated'},
            'tool_control_limits':['No authenticated external C enrollment/publication service',
                      'No independently authenticated source E at real network boundary',
                      'ClaimDispatch still omits full current-policy/RequiredDeps transactional recheck',
                      'ToolLedger continuity uses same-host local SQLite snapshots and trusted controller',
                      'No strict IND/MED end-to-end executor, and no guaranteed real-world exactly-once effect'],
            'environment':{'python':sys.version.split()[0],'platform':platform.platform(),'jsonschema':metadata.version('jsonschema'),
                      'cryptography':metadata.version('cryptography')},
            'code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DIR.glob('*.py')}}
    (DIR/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'regression':report['combined_regression'],'official_PAY_schema':report['official_schema_validation'],
                      '39_semantic_cases':report['official_39_semantic']},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
