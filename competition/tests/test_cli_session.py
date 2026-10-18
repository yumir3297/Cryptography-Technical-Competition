"""Interactive CLI session: the shell drives the explicit interface end to end.

The test opens one real trusted run and runs the ``auto`` happy path through the
session command handlers, asserting the same once-only settlement the bridge
tests check.  Command output is captured so the test log stays quiet.
"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from competition.cli.app import Session


class CliSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_session_drives_the_whole_path(self):
        session = Session()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                session.cmd_init([str(Path(self.folder.name) / 'w')])
                session.cmd_use(['PAY-1'])
                session.cmd_auto([])
                counts = session.service.counts()
            finally:
                if session.run is not None:
                    session.run.close()
        self.assertEqual(counts['accepts'], 1)
        self.assertEqual(counts['settlements'], 1)
        self.assertEqual(counts['confirmed_simulated_effects'], 1)

    def test_out_of_order_commands_are_guarded(self):
        session = Session()
        with self.assertRaises(RuntimeError):
            session.cmd_use(['PAY-1'])          # before init
        with self.assertRaises(RuntimeError):
            session.cmd_auto([])                # before init


if __name__ == '__main__':
    unittest.main()
