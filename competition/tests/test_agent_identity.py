"""The agent-side process credential: private key stays private, line stays public."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.agent.identity import callers_file, enroll, key_path
from competition.caller.flow import Caller

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def lines(self):
        path = self.root / 'callers' / 'callers.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()
                if line.strip()]

    def test_enroll_writes_one_0600_key_and_one_public_line(self):
        path, line = enroll(self.root / 'agent', 'zjj-agent', ['H'], self.root / 'callers')
        status = path.stat()
        self.assertEqual((status.st_uid, status.st_mode & 0o777), (os.geteuid(), 0o600))
        self.assertEqual(len(path.read_bytes()), 32)
        self.assertEqual(set(line), {'name', 'public_key', 'sides'})
        self.assertEqual(self.lines(), [line])
        self.assertNotIn('private', json.dumps(line).lower())

    def test_enroll_is_idempotent(self):
        first = enroll(self.root / 'agent', 'zjj-agent', ['H'], self.root / 'callers')
        second = enroll(self.root / 'agent', 'zjj-agent', ['H'], self.root / 'callers')
        self.assertEqual(first[1], second[1])
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(first[0], second[0])

    def test_a_directory_can_be_the_callers_location(self):
        path, _ = enroll(self.root / 'agent', 'zjj-agent', ['worker'], self.root / 'callers')
        self.assertEqual(callers_file(self.root / 'callers'),
                         self.root / 'callers' / 'callers.jsonl')
        self.assertEqual(callers_file(self.root / 'x.jsonl'), self.root / 'x.jsonl')
        self.assertEqual(key_path(self.root / 'agent', 'zjj-agent'), path)

    def test_the_line_really_opens_a_session_against_a_real_entry(self):
        # The caller module is what the gateway uses; this is the same key.
        path, _ = enroll(self.root / 'agent', 'zjj-agent', ['H'], self.root / 'callers')
        caller = Caller('http://127.0.0.1:1', path, None)
        public = caller.session.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.assertEqual(len(public), 32)


if __name__ == '__main__':
    unittest.main()
