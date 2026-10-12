"""Fresh common W bootstrap and genuine authorization-chain forks."""
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.support.wire import canonical, raw, keyid, strict_verify, action_hash
from competition.support.tool_final import verify_certificate


class WSeedTests(unittest.TestCase):
    seed = None

    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)

    @classmethod
    def tearDownClass(cls):
        if cls.seed is not None: cls.seed.close()
        cls.folder.cleanup()
        for k, v in cls.env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def setUp(self):
        try:
            self.module = importlib.import_module('competition.profiles.w_seed')
        except ModuleNotFoundError:
            self.fail('Missing fresh common W initialization helper')
        if type(self).seed is None:
            type(self).seed = self.module.initialize(Path(self.folder.name))

    def test_fresh_worker_and_tool_credentials_bind_original_public_scopes(self):
        cert = self.seed.worker_certificate; claim = cert['claim']
        strict_verify(self.seed.store.root_public, raw(cert['signature'], 64),
                      canonical(['COMP-W-WORKER-GRANT-v1', claim]))
        worker_public = raw(claim['public_key'], 32)
        delivery_public = self.seed.w.delivery_key.public_key().public_bytes_raw()
        self.assertNotEqual(delivery_public, worker_public)
        self.assertEqual(keyid(worker_public), claim['kid'])
        self.assertEqual(set(claim['profiles']), set(PROFILE_SCOPES))
        self.assertEqual(claim['purposes'], ['AUDIT', 'CANCEL', 'CLAIM', 'EXECUTE', 'QUERY', 'RECEIPT', 'SETTLE'])
        self.assertEqual(claim['revision'], '1'); self.assertTrue(claim['active'])
        forbidden = {self.seed.store.root_public} | {a.pub for roster in self.seed.actors.values() for a in roster.values()}
        self.assertNotIn(worker_public, forbidden)
        tool_keys = set()
        for profile, tool in self.seed.tools.items():
            record = verify_certificate(tool['certificate'], self.seed.store.root_public, profile)
            self.seed.store.schemas[profile].validate(record, 'Record_TOOL_TRUST')
            self.assertEqual(record['scope'], PROFILE_SCOPES[profile])
            public = raw(record['value']['public_key'], 32)
            self.assertEqual(self.seed.tool_keys[profile].public_key().public_bytes_raw(), public)
            self.assertNotIn(public, forbidden | {worker_public, delivery_public} | tool_keys)
            tool_keys.add(public)
            config = json.loads(Path(tool['config_path']).read_text(encoding='utf-8'))
            self.assertEqual(Path(self.seed.configs[profile]).resolve(), Path(tool['config_path']).resolve())
            self.assertEqual(raw(config['w_public'], 32), delivery_public)
            self.assertEqual(config['profile'], profile)
            self.assertNotEqual(Path(config['database']).resolve(), Path(self.seed.store.path).resolve())

    def test_forks_rebuild_real_signed_chains_and_preserve_source_records(self):
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile), self.seed.store.db() as c:
                before = [tuple(r) for r in c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key')]
                original = self.seed.operations[profile]
                fork = self.seed.fork_operation(profile, original)
                self.assertNotEqual(fork['action']['operation_id'], original['action']['operation_id'])
                self.assertEqual(fork['action']['payload'], original['action']['payload'])
                self.assertEqual(fork['ctx']['operation_id'], fork['action']['operation_id'])
                self.assertEqual(fork['ctx']['action_hash'], action_hash(profile, fork['action']))
                result = self.seed.base.service.guard(profile, fork, self.seed.identity_proof(profile, fork))
                self.assertEqual(result['decision'], 'T')
                self.assertEqual(result['required_reviews'], original['required'])
                self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key')], before)

    def test_existing_w_is_never_reset_by_initialization(self):
        with self.seed.store.db() as c:
            before = [tuple(r) for r in c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key')]
        with self.assertRaises(ValueError): self.module.initialize(Path(self.folder.name))
        with self.seed.store.db() as c:
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM a_current ORDER BY profile,namespace,key')], before)

    def test_holder_read_proof_signs_current_status_claim(self):
        self.assertTrue(callable(getattr(self.seed, 'read_proof', None)), 'Missing holder read proof helper')
        profile = 'PAY-1'; op = self.seed.operations[profile]
        ticket = self.seed.w.prepare(profile, op, self.seed.identity_proof(profile, op))['ticket_id']
        self.seed.w.accept(profile, ticket, self.seed.accept_proof(profile, ticket))
        oid = op['action']['operation_id']
        proof = self.seed.read_proof(profile, oid)
        strict_verify(self.seed.actors[profile]['H'].pub, raw(proof['signature'], 64),
                      canonical(['COMP-W-READ-v1', proof['claim']]))
        status = self.seed.w.status(profile, oid, proof)
        self.assertEqual(status['operation_id'], oid)
        self.assertEqual(status['acceptance_state'], 'COMMITTED')


if __name__ == '__main__': unittest.main()
