"""Result face: a caller retrieves its operation's result and its evidence.

One real trusted run drives the PAY-1 normal path to a committed, settled
operation; the result face then exports the public keys, the signed chain, the
authenticated read projections and the independent tool snapshot.  The tests
assert that the package verifies, that any tampering is caught, that no private
key or ledger file leaks in, and that ``chain_valid`` matches an independent
re-verification of the same operation.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from competition.server import export
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.support import artifact
from competition.support.wire import b64


class ExportFaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from competition.profiles.w_seed import initialize
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.output = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.profile = 'PAY-1'
        cls.trusted_run = initialize(Path(cls.folder.name) / 'w')
        cls.service = TrustedService(cls.trusted_run, LocalSigner(cls.trusted_run))
        normal = cls.service.run_normal(cls.profile)
        cls.operation_id = normal['operation_id']
        cls.bundle = cls.service.result(cls.operation_id)
        cls.out_dir = Path(cls.output.name) / 'package'
        cls.written = cls.service.export(cls.operation_id, cls.out_dir)

    @classmethod
    def tearDownClass(cls):
        cls.trusted_run.close()
        cls.folder.cleanup()
        cls.output.cleanup()
        for key, value in cls.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- 1. a normal export verifies ---------------------------------------
    def test_export_verifies(self):
        report = export.verify_bundle(self.out_dir)
        self.assertTrue(report['passed'])
        self.assertEqual(report['kind'], export.VERIFY_KIND)
        self.assertEqual(report['operation_id'], self.operation_id)
        self.assertEqual(report['profile'], self.profile)
        self.assertTrue(report['chain_valid'])
        self.assertEqual(sorted(p.name for p in self.out_dir.iterdir()),
                         sorted(export.EVIDENCE_FILES))

    def test_bundle_carries_the_declared_sections(self):
        for field in ('kind', 'build', 'profile', 'operation_id', 'roster',
                      'root_public', 'worker_certificate', 'status', 'audit',
                      'chain_valid', 'tools', 'chain'):
            self.assertIn(field, self.bundle)
        self.assertEqual(self.bundle['kind'], export.KIND)
        self.assertEqual(self.bundle['operation_id'], self.operation_id)
        self.assertEqual(self.bundle['profile'], self.profile)
        self.assertTrue(self.bundle['chain_valid'])
        self.assertEqual(self.bundle['status']['view_kind'], 'APPLICATION_W_PROJECTION')
        self.assertIn('commit', self.bundle['audit'])
        self.assertEqual(sorted(self.bundle['roster']),
                         sorted(self.trusted_run.store.actors))

    # -- 2. tampering any exported file is caught --------------------------
    def _copy(self, name):
        target = Path(self.output.name) / name
        shutil.copytree(self.out_dir, target)
        return target

    def _rewrite_manifest(self, target):
        """Re-hash the evidence files so only a genuine check can reject the copy."""
        files = [export._row(name, target / name) for name in ('bundle.json', 'chain.json')]
        for name in ('bundle.json', 'manifest.json'):
            doc = json.loads((target / name).read_text(encoding='utf-8'))
            if name == 'bundle.json':
                doc['manifest'] = [row for row in files if row['path'] == 'chain.json']
            else:
                doc['files'] = files
            (target / name).write_bytes(export._json_bytes(doc))

    def test_tampered_bundle_is_rejected(self):
        target = self._copy('tampered-bundle')
        blob = (target / 'bundle.json').read_bytes()
        (target / 'bundle.json').write_bytes(blob.replace(b'"PAY-1"', b'"PAY-9"', 1))
        with self.assertRaises(Exception):
            export.verify_bundle(target)

    def test_tampered_chain_is_rejected(self):
        target = self._copy('tampered-chain')
        blob = (target / 'chain.json').read_bytes()
        (target / 'chain.json').write_bytes(blob[:-2] + b' \n')
        with self.assertRaises(Exception):
            export.verify_bundle(target)

    def test_forged_chain_signature_is_rejected(self):
        target = self._copy('forged-chain')
        chain = json.loads((target / 'chain.json').read_text(encoding='utf-8'))
        chain['messages']['proof']['sig'] = b64(b'\x00' * 64)
        (target / 'chain.json').write_bytes(export._json_bytes(chain))
        self._rewrite_manifest(target)
        with self.assertRaises(Exception):
            export.verify_bundle(target)

    def test_extra_file_is_rejected(self):
        target = self._copy('extra-file')
        (target / 'leaked.key').write_bytes(b'x' * 32)
        with self.assertRaises(Exception):
            export.verify_bundle(target)

    # -- 3. no private material and no ledger file leaks -------------------
    def test_no_private_material_leaks(self):
        self.assertEqual(export.forbidden_secrets(self.bundle), [])
        private = b64(b'\x01' * 32)
        self.assertFalse(export._secret_field('public_key', private))
        self.assertFalse(export._secret_field('kid', private))
        self.assertFalse(export._secret_field('key', ['behavior', 'before']))
        self.assertFalse(export._secret_field('key_grant_ref', private))
        self.assertTrue(export._secret_field('private_key', private))
        self.assertTrue(export._secret_field('key', private))
        self.assertTrue(export._credential_path('W-worker.key'))
        self.assertTrue(export._credential_path('/run/auth-w.sqlite'))
        key_files = sorted(Path(self.trusted_run.folder).rglob('*.key'))
        self.assertTrue(key_files, 'the run should have private key files to compare against')
        text = ''.join((self.out_dir / name).read_text(encoding='utf-8')
                       for name in export.EVIDENCE_FILES)
        for key_file in key_files:
            self.assertNotIn(b64(key_file.read_bytes()), text, str(key_file))
        for path in self.out_dir.rglob('*'):
            self.assertFalse(path.name.endswith(('.key', '.sqlite')), str(path))
        self.assertNotIn('.sqlite', text)

    # -- 4. chain_valid matches an independent re-verification -------------
    def test_chain_valid_matches_independent_recheck(self):
        op = self.service._entries[self.operation_id]['op']
        self.assertTrue(self.bundle['chain_valid'])
        self.assertTrue(artifact.signed_messages_valid(self.trusted_run, self.profile, op))
        self.assertEqual(len(self.bundle['chain']['messages']), len(export.CHAIN_ALIASES))
        self.assertEqual(self.bundle['chain']['operation_id'], self.operation_id)

    # -- CLI commands appended for the result face -------------------------
    def test_cli_result_export_verify(self):
        from competition.cli.app import COMMANDS, Session
        for command in ('result', 'export', 'verify'):
            self.assertIn(command, COMMANDS)
        session = Session()
        session.run = self.trusted_run
        session.service = self.service
        session.profile = self.profile
        session.operation_id = self.operation_id
        cli_dir = Path(self.output.name) / 'cli-package'
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            session.cmd_result([])
            session.cmd_export([self.operation_id, str(cli_dir)])
            session.cmd_verify([str(cli_dir)])
        self.assertIn('"passed": true', buffer.getvalue())


if __name__ == '__main__':
    unittest.main()
