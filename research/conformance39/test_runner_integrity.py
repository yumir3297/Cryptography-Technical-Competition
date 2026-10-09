"""Guardrails: a positive local test can never silently become an official PASS."""
import json,tempfile,unittest
from pathlib import Path
from research.conformance39.cases import CASES,EXPECTED_IDS,Case
from research.conformance39.run39 import check_manifest,check_schemas,git_blob,index_tests,run_case

class HarnessIntegrityTests(unittest.TestCase):
 def test_exactly_39_unique_expected_ids(self):
  self.assertEqual(len(CASES),39)
  self.assertEqual([c.id for c in CASES],EXPECTED_IDS)
  self.assertEqual(len({c.id for c in CASES}),39)
 def test_every_case_has_declared_missing_requirements(self):
  self.assertTrue(all(c.missing and all(c.missing) for c in CASES))
 def test_every_case_has_at_least_one_implemented_local_witness(self):
  ix=index_tests();self.assertTrue(all(c.witnesses and all(w in ix for w in c.witnesses) for c in CASES))
 def test_no_local_pass_upgrades_to_official(self):
  r=run_case(Case('SAMPLE','Sample witness',('strict_v26:n2_insufficient',),('Not full')),index_tests())
  self.assertEqual(r['status'],'PARTIAL_WITNESSES_PASS')
  self.assertEqual(r['official_full_conformance'],'NOT_ESTABLISHED')
 def test_absent_witness_cannot_be_a_pass(self):
  r=run_case(Case('SAMPLE','Sample no witness',(),('Missing')),index_tests())
  self.assertEqual(r['status'],'BLOCKED_NO_EXECUTABLE_WITNESS')
 def test_unknown_witness_is_error_not_pass(self):
  r=run_case(Case('SAMPLE','Missing test',('missing_module:foo',),('Missing')),index_tests())
  self.assertEqual(r['status'],'HARNESS_ERROR')
 def test_modified_case_manifest_is_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'system_dev/v26/semantic_cases.json';path.parent.mkdir(parents=True)
   path.write_text('{"cases":[]}',encoding='utf-8')
   self.assertEqual(check_manifest(Path(tmp))['status'],'BLOB_MISMATCH')
 def test_unverified_schema_cannot_be_called_official(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'system_dev/v26/contracts/pay1.schema.json';path.parent.mkdir(parents=True)
   path.write_text('{}',encoding='utf-8')
   self.assertEqual(check_schemas(Path(tmp))['PAY-1']['status'],'BLOB_MISMATCH')
 def test_missing_original_manifest_is_transparent(self):
  with tempfile.TemporaryDirectory() as tmp:self.assertEqual(check_manifest(Path(tmp))['status'],'NOT_INSTALLED')
 def test_upstream_pay_schema_version_is_pinned(self):
  root=Path(__file__).resolve().parents[2]
  self.assertEqual(check_schemas(root)['PAY-1']['status'],'EXACT_ORIGINAL_SCHEMA_LOADED')
