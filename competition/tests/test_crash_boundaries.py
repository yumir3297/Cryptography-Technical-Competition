"""Crash consistency at real persistence boundaries.

Each child process commits one W transaction and dies before the next side
effect.  The parent reopens the authentic ledgers and checks that a retry cannot
create a second execution qualification or a second settlement.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from competition.profiles.w_seed import initialize
from competition.w_cases import recover_fixture, save_recovery_fixture

PROFILE = 'IND-DEMO-1'
ROOT = Path(__file__).resolve().parents[2]


class CrashBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp(dir=ROOT / '.runtime'))
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        run = initialize(folder)
        self.fixture = save_recovery_fixture(run)
        self.oid = run.operations[PROFILE]['action']['operation_id']
        run.close()

    def _crash(self, mode):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-m', 'competition.evaluation.crash_child',
                                 self.fixture, mode], cwd=str(ROOT), env=env,
                                capture_output=True, text=True, timeout=180)
        self.assertIn(result.returncode, (96, 97, 98, 99), result.stderr)
        return result

    def test_accept_commit_crash_leaves_one_committed_operation_and_pending_receipt(self):
        self._crash('accept')
        run = recover_fixture(self.fixture)
        self.addCleanup(run.close)
        with run.store.db() as c:
            row = c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',
                            (PROFILE, self.oid)).fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row['receipt'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM w_reservation WHERE profile=? AND oid=?',
                                       (PROFILE, self.oid)).fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT reserved FROM w_resource WHERE profile=?',
                                       (PROFILE,)).fetchone()[0], 1)
        view = run.w.complete_receipt(PROFILE, self.oid)
        self.assertEqual(view['acceptance_state'], 'COMMITTED')
        self.assertIsNotNone(view['acceptance'])
        self.assertEqual(run.w.counts()['attempts'], 0)

    def test_exec_marker_crash_uses_one_execution_qualification_and_does_not_call_tool(self):
        self._crash('exec')
        run = recover_fixture(self.fixture)
        self.addCleanup(run.close)
        counts = run.w.counts()
        self.assertEqual((counts['exec_invocations'], counts['attempts']), (1, 1))
        retry = run.w.execute_once(PROFILE, self.oid, run.worker_proof(PROFILE, self.oid, 'EXECUTE'))
        self.assertEqual((retry['state'], retry['reason']), ('UNKNOWN', 'EXEC_ALREADY_CONSUMED'))
        query = run.w.query_attempt(PROFILE, self.oid, run.worker_proof(PROFILE, self.oid, 'QUERY'))
        self.assertIsNone(query.get('record'))
        unknown = run.w.settle(PROFILE, self.oid, query, run.worker_proof(PROFILE, self.oid, 'SETTLE'))
        self.assertEqual(unknown['state'], 'UNKNOWN')
        self.assertTrue(unknown['reservation_retained'])
        with run.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM w_settlement').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT reserved FROM w_resource WHERE profile=?',
                                       (PROFILE,)).fetchone()[0], 1)
        self.assertEqual(run.w.counts()['exec_invocations'], 1)

    def test_settlement_commit_crash_is_recovered_without_a_second_settlement(self):
        self._crash('settle')
        run = recover_fixture(self.fixture)
        self.addCleanup(run.close)
        with run.store.db() as c:
            row = c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',
                            (PROFILE, self.oid)).fetchone()
            self.assertIsNotNone(row)
            response = json.loads(row['evidence'])
            self.assertEqual(c.execute('SELECT state FROM w_operation WHERE profile=? AND oid=?',
                                       (PROFILE, self.oid)).fetchone()[0], 'SETTLED')
            self.assertEqual(c.execute('SELECT state FROM w_reservation WHERE profile=? AND oid=?',
                                       (PROFILE, self.oid)).fetchone()[0], 'SPENT')
        repeated = run.w.settle(PROFILE, self.oid, response,
                                run.worker_proof(PROFILE, self.oid, 'SETTLE'))
        self.assertEqual((repeated['state'], repeated['existing']), ('SETTLED', True))
        self.assertEqual(run.w.counts()['settlements'], 1)


if __name__ == '__main__':
    unittest.main()
