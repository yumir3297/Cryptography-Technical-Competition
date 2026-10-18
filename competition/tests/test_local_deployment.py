"""Deployment configuration behavior, using fresh synthetic credentials only."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from competition.support.wire import ProtocolError

class LocalDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('competition.application.local_runtime'),
                             'Missing persistent local deployment bootstrap')
        from competition.deployment.provision_demo import provision
        self.tmp = tempfile.TemporaryDirectory(prefix='zjj-deploy-config-')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)/'installation'
        self.config = Path(provision(self.home, port=0))
        self.value = json.loads(self.config.read_text())

    def test_public_runtime_restarts_without_reading_participant_secrets(self):
        from competition.application.local_runtime import open_runtime
        state = Path(self.value['runtime_dir'])
        protected = {state/(p+'-'+a+'.key') for p in self.value['actors']
                     for a in ('H','U','V','G','E')}
        protected.add(state/'W-worker.key')
        read_bytes = Path.read_bytes
        def checked(path):
            self.assertNotIn(path.resolve(), protected, 'HTTP host read participant private key')
            return read_bytes(path)
        with patch.object(Path, 'read_bytes', checked):
            for _ in range(2):
                with open_runtime(self.config) as run:
                    self.assertEqual(run.store.path, str(state/'auth-w.sqlite'))
                    self.assertTrue(all(not hasattr(a,'key') for r in run.store.actors.values() for a in r.values()))
                    self.assertEqual(run.w.counts()['accepts'],0)
                    self.assertIs(run.service.requests,run.w.requests)

    def test_missing_database_is_rejected_without_recreating_it(self):
        from competition.application.local_runtime import inspect_config
        db = Path(self.value['runtime_dir'])/'auth-w.sqlite'
        db.unlink()
        with self.assertRaises(ProtocolError) as caught: inspect_config(self.config)
        self.assertEqual(caught.exception.code,'DEPLOYMENT_FILE_MISSING')
        self.assertFalse(db.exists())

    def test_world_readable_transport_token_is_rejected(self):
        from competition.application.local_runtime import inspect_config
        token = self.home/'transport-token'
        token.chmod(0o644)
        with self.assertRaises(ProtocolError) as caught: inspect_config(self.config)
        self.assertEqual(caught.exception.code,'DEPLOYMENT_PERMISSIONS')

    def test_changed_tool_delivery_binding_is_rejected(self):
        from competition.application.local_runtime import inspect_config
        p=Path(self.value['runtime_dir'])/'IND-DEMO-1-tool.json'
        v=json.loads(p.read_text());v['w_public']=self.value['root_public']
        p.write_text(json.dumps(v))
        with self.assertRaises(ProtocolError) as caught: inspect_config(self.config)
        self.assertEqual(caught.exception.code,'TOOL_BINDING')

    def test_remote_listen_and_unknown_config_fields_are_rejected(self):
        from competition.application.local_runtime import inspect_config
        for patch_value in ({'host':'0.0.0.0'},{'disable_checks':True}):
            self.config.write_text(json.dumps({**self.value,**patch_value}))
            with self.assertRaises(ProtocolError): inspect_config(self.config)

    def test_repeat_provision_never_overwrites_existing_installation(self):
        from competition.deployment.provision_demo import provision
        before=(self.home/'transport-token').read_bytes()
        with self.assertRaises(FileExistsError): provision(self.home,port=0)
        self.assertEqual((self.home/'transport-token').read_bytes(),before)

    def test_wrong_receipt_signer_key_is_rejected_before_serving(self):
        from competition.application.local_runtime import open_runtime
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key=Ed25519PrivateKey.generate().private_bytes_raw()
        (Path(self.value['runtime_dir'])/'IND-DEMO-1-X.key').write_bytes(key)
        with self.assertRaises(ProtocolError) as caught:
            with open_runtime(self.config): pass
        self.assertEqual(caught.exception.code,'RECOVERY_EXECUTOR')

if __name__=='__main__': unittest.main()
