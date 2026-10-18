"""Behavioral regressions for independently reviewed deployment gaps."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from competition.deployment.provision_demo import provision
from competition.application.local_runtime import open_runtime
from competition.support.wire import ProtocolError

class DeploymentReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='zjj-deploy-review-')
        self.addCleanup(self.tmp.cleanup)
        self.config=Path(provision(Path(self.tmp.name)/'installation',port=0))
        self.state=Path(json.loads(self.config.read_text())['runtime_dir'])
        with open_runtime(self.config):pass

    def test_wrong_tool_private_key_is_rejected_before_serving(self):
        (self.state/'IND-DEMO-1-tool.key').write_bytes(Ed25519PrivateKey.generate().private_bytes_raw())
        with self.assertRaises(ProtocolError) as caught:
            with open_runtime(self.config):pass
        self.assertEqual(caught.exception.code,'RECOVERY_TOOL')

    def missing_table(self,database,table):
        with closing(sqlite3.connect(self.state/database)) as c:
            c.execute('DROP TABLE '+table);c.commit()
        with self.assertRaises(ProtocolError) as caught:
            with open_runtime(self.config):pass
        self.assertEqual(caught.exception.code,'DEPLOYMENT_SCHEMA')
        with closing(sqlite3.connect(self.state/database)) as c:
            self.assertIsNone(c.execute('SELECT name FROM sqlite_master WHERE name=?',(table,)).fetchone())

    def test_missing_request_mapping_never_recreated(self):
        self.missing_table('auth-w.sqlite','app_request')

    def test_missing_W_acceptance_ledger_never_recreated(self):
        self.missing_table('auth-w.sqlite','w_operation')

    def test_missing_C_sequence_never_recreated(self):
        self.missing_table('c-clock.sqlite','source_sequence')

    def test_missing_tool_request_ledger_never_recreated(self):
        self.missing_table('IND-DEMO-1-tool.sqlite','tool_requests')

if __name__=='__main__':unittest.main(verbosity=2)
