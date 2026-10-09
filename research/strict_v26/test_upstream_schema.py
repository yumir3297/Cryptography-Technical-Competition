"""Schema adapter tests; genuine official schemas only loaded when installed."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json,unittest
from research.reference_executor.wire import ProtocolError
from .upstream_schema import UpstreamSchema

class SchemaAdapterTests(unittest.TestCase):
    def test_missing_is_explicit_not_fake_official(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ProtocolError) as e:UpstreamSchema(d,'PAY-1')
            self.assertEqual(e.exception.code,'SCHEMA_NOT_INSTALLED')
    def test_unknown_profile_rejected(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ProtocolError) as e:UpstreamSchema(d,'BAD-PROFILE')
            self.assertEqual(e.exception.code,'PROFILE')
    def test_adapter_checks_actual_file_without_silent_stub(self):
        # This temporary JSON schema is used exclusively to exercise the adapter.
        # It is NOT called an official ZJJ schema in any test/report.
        with TemporaryDirectory() as d:
            p=Path(d)/'system_dev'/'v26'/'contracts';p.mkdir(parents=True)
            schema={'$schema':'https://json-schema.org/draft/2020-12/schema',
              '$defs':{'Record_POLICY':{'type':'object','required':['kind'],
                'properties':{'kind':{'const':'POLICY'}},'additionalProperties':False}}}
            (p/'pay1.schema.json').write_text(json.dumps(schema),encoding='utf-8')
            obj=UpstreamSchema(d,'PAY-1')
            self.assertTrue(obj.validate({'kind':'POLICY'},'Record_POLICY'))
            with self.assertRaises(ProtocolError) as x:obj.validate({'kind':'BAD'},'Record_POLICY')
            self.assertEqual(x.exception.code,'UPSTREAM_SCHEMA_REJECT:Record_POLICY:kind')
            with self.assertRaises(ProtocolError) as x:obj.validate({'kind':'POLICY','extra':1},'Record_POLICY')
            self.assertTrue(x.exception.code.startswith('UPSTREAM_SCHEMA_REJECT'))
