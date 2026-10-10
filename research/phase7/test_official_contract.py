"""Independent tests against byte-identical upstream PAY-1 JSON Schema.

This only tests Draft-2020-12 structure. The contract's custom x-zjj-order
and signatures are checked separately by reference code, not by JSON Schema.
"""
from __future__ import annotations
import copy
import tempfile
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from research.phase5.run_phase5 import schema_probe, prepare_cases
from research.phase5.durable_w import DurablePayW
from research.strict_v26.test_pay_history import case
from research.strict_v26.upstream_schema import UpstreamSchema
from research.reference_executor.wire import ProtocolError
from research.phase6.trusted_final import Controller, ToolLedger, FinalW, _pub
from research.reference_executor.wire import sid,b64,keyid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT=Path(__file__).resolve().parents[2]


def all_objects(cases):
    f,op=prepare_cases(cases,ROOT)
    with tempfile.TemporaryDirectory() as td:
        w=DurablePayW(Path(td)/'pay.sqlite')
        result=w.accept(f,op)
        objects=[('Record_POLICY',f.source['policy_record']),('Record_PAY_TASK',f.source['task_record']),
            ('Record_PAY_EVIDENCE',f.source['evidence_record']),('Record_PAY_HISTORY',f.source['history_record']),
            ('Record_ASSESSMENT',f.assessment_record),('Record_BASIS',f.basis_record)]
        objects.extend(('Review',r) for r in op.reviews)
        objects.extend([('Authorization',op.authorization),('IssueRequest',op.issue),('Permit',op.permit),
            ('Result',f.issue_result),('ChallengeRequest',op.challenge_request),('Challenge',op.challenge),
            ('CommitProof',op.proof),('Record_COMMIT',result['commit']),('Acceptance',result['acceptance']),
            ('Result',result['reply'])])
    return objects

class OfficialPaySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate,meta=schema_probe(ROOT)
        assert meta['git_blob_sha1']=='86ba1bae0e4c455899af661bed44edfc5494aa5e'
        cls.fixture_sets={
            'CLEAR':None,
            'FLAG':[case(i,action_class='HOLD' if i<=4 else 'PAY') for i in range(1,6)],
            'INSUFFICIENT':[case(1),case(2)]}
        cls.objects={k:all_objects(v) for k,v in cls.fixture_sets.items()}

    def test_official_schema_is_valid_2020_12(self):
        Draft202012Validator.check_schema(self.gate.schema)
        self.assertEqual(self.gate.schema['$defs']['Record_TOOL_FINAL']['properties']['kind']['const'],'TOOL_FINAL')

    def test_all_emitted_positive_objects_pass_official_schema(self):
        self.assertEqual(sum(map(len,self.objects.values())),50)
        for risk,objs in self.objects.items():
            for idx,(kind,record) in enumerate(objs):
                with self.subTest(risk=risk,idx=idx,kind=kind):self.assertTrue(self.gate.validate(record,kind))

    def test_every_top_level_required_field_is_enforced(self):
        count=0
        for risk,objs in self.objects.items():
            for kind,record in objs:
                for key in list(record):
                    mutated=copy.deepcopy(record);mutated.pop(key)
                    with self.subTest(risk=risk,kind=kind,field=key):
                        with self.assertRaisesRegex(ProtocolError,'UPSTREAM_SCHEMA_REJECT'):
                            self.gate.validate(mutated,kind)
                    count+=1
        self.assertGreaterEqual(count,160)

    def test_extra_top_level_field_is_rejected(self):
        for risk,objs in self.objects.items():
            for kind,record in objs:
                mutated=copy.deepcopy(record);mutated['hidden_privilege']='yes'
                with self.subTest(risk=risk,kind=kind):
                    with self.assertRaisesRegex(ProtocolError,'UPSTREAM_SCHEMA_REJECT'):
                        self.gate.validate(mutated,kind)

    def test_required_payload_or_value_fields_are_enforced(self):
        count=0
        for risk,objs in self.objects.items():
            for kind,record in objs:
                is_record=kind.startswith('Record_')
                payload=record['value'] if is_record else record['body']['payload']
                definition=self.gate.defs[kind]
                if is_record:
                    required=definition['properties']['value'].get('required',[])
                else:
                    required=definition['properties']['body']['properties']['payload'].get('required',[])
                for key in required:
                    mutated=copy.deepcopy(record)
                    (mutated['value'] if is_record else mutated['body']['payload']).pop(key)
                    with self.subTest(risk=risk,kind=kind,field=key):
                        with self.assertRaisesRegex(ProtocolError,'UPSTREAM_SCHEMA_REJECT'):
                            self.gate.validate(mutated,kind)
                    count+=1
        self.assertGreaterEqual(count,280)

    def test_cross_profile_confusion_and_foreign_version_rejected(self):
        for risk,objs in self.objects.items():
            for kind,record in objs:
                for bad in ('IND-DEMO-1','MED-DEMO-1'):
                    obj=copy.deepcopy(record)
                    if kind.startswith('Record_'):obj['profile']=bad
                    else:obj['protected']['profile']=bad
                    with self.subTest(kind=kind,risk=risk,profile=bad):
                        with self.assertRaisesRegex(ProtocolError,'UPSTREAM_SCHEMA_REJECT'):
                            self.gate.validate(obj,kind)

    def test_tool_support_records_match_official_schema(self):
        with tempfile.TemporaryDirectory() as td:
            scope={'domain':'lab','tenant':'tenant-1','scenario':'payment'}
            ledger=ToolLedger(Path(td)/'ledger.sqlite')
            ctrl=Controller.fixture()
            key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
            tr={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
                'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
                'public_key':b64(_pub(key)),'kid':keyid(_pub(key)),
                'epoch':'1','iat':'90','exp':'2000'}
            cert=ctrl.certify(scope,tr,1,ledger.head(),ledger.origin)
            self.assertTrue(self.gate.validate(cert['claim']['record'],'Record_TOOL_TRUST'))
            f,op=prepare_cases(None,ROOT)
            w=FinalW(Path(td)/'w.sqlite',ctrl.public_key)
            w.activate(cert,ledger)
            w.accept(f,op)
            attempt=sid(501)
            w.claim_bound(op.action['operation_id'],attempt)
            fact=ledger.freeze(scope,op.action,attempt)
            signed=ledger.reattest(scope,fact,key,'tool-issuer',130,'2000')
            self.assertTrue(self.gate.validate(signed,'Record_TOOL_FINAL'))
            self.assertEqual(w.settle(signed,now=140)['status'],'SUCCEEDED')

if __name__=='__main__':unittest.main()
