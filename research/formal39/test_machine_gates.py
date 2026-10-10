"""Regression: pinned original machine contract and prior EVIDENCE wire bug."""
import copy,tempfile,unittest
from pathlib import Path
from research.conformance39.run39 import check_manifest,check_schemas
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase8.run_phase8 import run_official_schemas
from research.strict_v26.upstream_schema import UpstreamSchema
from research.reference_executor.wire import ProtocolError,digest,sortset
ROOT=Path(__file__).resolve().parents[2]

class OfficialMachineGates(unittest.TestCase):
 def test_unmodified_manifest_and_all_three_exact_schemas_pinned(self):
  self.assertEqual(check_manifest(ROOT)['status'],'EXACT_OFFICIAL_MANIFEST_VERIFIED')
  for name,result in check_schemas(ROOT).items():
   with self.subTest(name=name):
    self.assertEqual(result['status'],'EXACT_ORIGINAL_SCHEMA_LOADED')
 def test_all_emitted_scene_records_pass_official_schema(self):
  r=run_official_schemas(ROOT,require=True)
  self.assertEqual((r['IND-DEMO-1']['checked_objects'],r['MED-DEMO-1']['checked_objects']),(97,64))
  self.assertEqual(sum(len(i['rejected_objects']) for i in r.values()),0)
 def test_unknown_evidence_wire_namespace_is_rejected(self):
  for profile,label in [('IND-DEMO-1','DEMO_NORMAL'),('MED-DEMO-1','DEMO_A')]:
   with self.subTest(profile=profile),tempfile.TemporaryDirectory() as td:
    a,action,tid,k,ev=build_scene(Path(td)/'w.sqlite',profile,label)
    op=prepare_approved(a,action,tid,k)
    a.accept(op)
    for item in op['deps']:self.assertNotEqual(item['namespace'],'EVIDENCE')
    bad=copy.deepcopy(op['basis']);bad['value']['deps']=sortset(bad['value']['deps']+[
          {'namespace':'EVIDENCE','key':k,'revision':'1','ref':digest(['wrong'])}])
    with self.assertRaisesRegex(ProtocolError,'UPSTREAM_SCHEMA_REJECT'):
     UpstreamSchema(ROOT,profile).validate(bad,'Record_BASIS')
 def test_post_evidence_mutation_makes_prepared_chain_stale(self):
  for profile,label in [('IND-DEMO-1','DEMO_NORMAL'),('MED-DEMO-1','DEMO_A')]:
   with self.subTest(profile=profile),tempfile.TemporaryDirectory() as td:
    a,action,tid,k,ev=build_scene(Path(td)/'w.sqlite',profile,label)
    op=prepare_approved(a,action,tid,k)
    with a.tx() as c:
     row=a._scene_current(c,k);before=row['record']['value'];new=dict(before)
     new['evidence_ref']=digest(['new-authoritative-evidence'])
     a._scene_update(c,k,row['revision'],new)
    with self.assertRaises(ProtocolError):a.accept(op)
    self.assertEqual(a.snapshot()['accepts'],0)

if __name__=='__main__':unittest.main()
