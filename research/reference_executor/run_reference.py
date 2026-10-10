"""Run signed-envelope offline reference slice and produce verification artifacts."""
from pathlib import Path
import hashlib, importlib.metadata, io, json, platform, sys, unittest, datetime

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from research.reference_executor import test_reference
from research.reference_executor.coverage import matrix
from research.reference_executor.upstream_schema_probe import probe
from research.reference_executor.engine import ReferenceW
from research.reference_executor.wire import msgref,rec_ref,sid,ProtocolError

OUT=Path(__file__).resolve().parent

def trace():
 traces=[];wire_samples=[]
 inputs=[
  ('PAY-1',{'order_id':'ord1','stage':'initial','payer':'payer1','payee':'payee1','amount_minor':'1000','currency':'CNY','purpose':'order-settlement'},{'risk':'CLEAR'}),
  ('IND-DEMO-1',{'line_id':'linea','unit_id':'unit1','station_id':'station1','inspection_cycle':'1','phase':'INITIAL','route':'INSPECT'},{'label':'DEMO_UNCERTAIN'}),
  ('MED-DEMO-1',{'synthetic_patient_id':'patient1','encounter_id':'visit1','order_group_id':sid(44),'phase':'SUBMIT','template_id':'DEMO-ORDER-A',
                 'record_ref':'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA','destination_system':'med-demo-ledger'},
                {'available':True,'complete':True,'label':'DEMO_A'})
 ]
 for profile,payload,evidence in inputs:
  w=ReferenceW(profile);op=w.prepare(payload,evidence)
  refs={'basis_ref':op.ctx['basis_ref'],'action_hash':op.ctx['action_hash']}
  if op.required:refs['review_ref']=msgref(w.review(op))
  refs['authorization_ref']=msgref(w.authorize(op));refs['permit_ref']=msgref(w.issue(op));refs['challenge_ref']=msgref(w.challenge(op))
  proof=w.make_proof(op);refs['proof_ref']=msgref(proof)
  refs['acceptance_ref']=msgref(w.commit(op,proof))
  w.claim(op);f=w.tool_fact(op);proof_of_effect=w.certify_fact(op,f)
  before=rec_ref(proof_of_effect);first=w.receive_final(op,proof_of_effect)
  w.rotate_tool(101,True);w.now=101
  refreshed=w.certify_fact(op,f);again=w.receive_final(op,refreshed)
  refs.update({'original_tool_final_ref':before,'refreshed_tool_final_ref':rec_ref(refreshed),'final_fact_id':op.finalfact_id})
  wire_samples.append({'profile':profile,
    'warning':'public deterministic test signers; no full profile schema / COMMIT audit witness',
    'public_keys':{alias:__import__('research.reference_executor.wire',fromlist=['b64']).b64(identity.pub) for alias,identity in w.idents.items()},
    'basis_fixture':op.basis,'evidence_fixture':op.evidence,
    'envelopes':{'review':op.reviews,'authorization':op.authorization,'issue_request':op.issue,
                 'permit':op.permit,'challenge_request':op.challenge_request,
                 'challenge':op.challenge,'commit_proof':op.proof,'acceptance':op.acceptance},
    'original_tool_final':proof_of_effect,'refreshed_tool_final':refreshed})
  traces.append({'profile':profile,'run':'signed-positive-rotation-recovery','required_reviews':list(op.required),'refs':refs,
                 'first_settlement':first,'second_re_attestation':again,'final_status':op.status,'calls':op.calls,'settlements':op.settlements,
                 'resource_reserved':w.reserved,'resource_spent':w.spent,'fixture_notice':'in-memory tool ledger; no durable execution'})
 return traces,wire_samples

def run():
 stream=io.StringIO()
 suite=unittest.defaultTestLoader.loadTestsFromModule(test_reference)
 res=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
 (OUT/'test_run.txt').write_text(stream.getvalue(),encoding='utf-8')
 covered=matrix(ROOT)
 (OUT/'coverage_matrix.json').write_text(json.dumps(covered,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 schema_checks=probe(ROOT)
 (OUT/'upstream_schema_probe.json').write_text(json.dumps(schema_checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 demos,samples=trace() if res.wasSuccessful() else ([],[])
 (OUT/'signed_wire_samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (OUT/'demo_traces.json').write_text(json.dumps(demos,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 sources=[OUT/x for x in ('wire.py','engine.py','test_reference.py','coverage.py','run_reference.py','upstream_schema_probe.py','README.md')]
 out={'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'OFFLINE_SIGNED_REFERENCE_SLICE_NOT_UPSTREAM_CONFORMANCE',
      'upstream_snapshot_head_used_for_design':'0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c',
      'tests':{'run':res.testsRun,'passed':res.testsRun-len(res.failures)-len(res.errors)-len(res.skipped),'failures':len(res.failures),'errors':len(res.errors),'skipped':len(res.skipped)},
      'official_full_conformance':{'passed':0,'partial_model_relevance':covered['partial_count'],
         'untouched':covered['not_run_count'],'upstream_inventory_verified_here':covered['source_verified']},
      'trace_demo_profiles':[x['profile'] for x in demos],
      'upstream_schema_probe':schema_checks,
      'environment':{'python':sys.version.split()[0],'platform':platform.platform(),
                     'cryptography':importlib.metadata.version('cryptography')},
      'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
      'limits':['In-memory mock of C/W, not durable or linearizable across processes',
                'Full upstream JSON Schema not loaded in this detached patch',
                'Basis/COMMIT and evidence Record are only partial: not wire-compatible full contract',
                'PAY risk status is a trusted fixture; no history-int-v2 re-computation',
                'No key enrollment/revocation attestation, full authenticated source or old-version migration',
                'No real tool effects; Ed25519 Python subgroup test is research-only']}
 (OUT/'validation_report.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'unit_tests':res.testsRun,'success':res.wasSuccessful(),
                   'trace_profiles':len(demos),'source_case_partial':covered['partial_count'],
                   'source_case_not_run':covered['not_run_count'],'official_full_pass':0,
                   'report':'research/reference_executor/validation_report.json'},ensure_ascii=False))
 return 0 if res.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(run())
