"""The journal: duplicate suppression, event dedupe, and lease hand-off."""
import tempfile
import unittest
from pathlib import Path

from competition.agent.journal import Journal

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.now = [1000.0]
        self.journal = Journal(Path(self.folder.name) / 'agent.sqlite',
                               now=lambda: self.now[0])
        self.addCleanup(self.journal.close)

    def test_submission_is_idempotent_and_an_unknown_outcome_is_not_retried(self):
        row, first = self.journal.begin_submission('PAY-1', 'digest')
        self.assertTrue(first)
        self.assertEqual(row['state'], 'SUBMITTING')
        row, again = self.journal.begin_submission('PAY-1', 'digest')
        self.assertFalse(again)
        self.assertEqual(row['state'], 'SUBMITTING')
        self.journal.mark_submitted('PAY-1', 'digest', 'op-1')
        row, again = self.journal.begin_submission('PAY-1', 'digest')
        self.assertFalse(again)
        self.assertEqual(row['operation_id'], 'op-1')
        self.journal.begin_submission('MED-DEMO-1', 'other')
        self.journal.mark_submission_unknown('MED-DEMO-1', 'other', 'ENTRY_UNAVAILABLE')
        row, again = self.journal.begin_submission('MED-DEMO-1', 'other')
        self.assertFalse(again)
        self.assertEqual(row['state'], 'SUBMIT_UNKNOWN')

    def test_a_denied_intent_may_be_proposed_again(self):
        self.journal.begin_submission('PAY-1', 'digest')
        self.journal.mark_submission_denied('PAY-1', 'digest', 'INTENT_FIELDS')
        row, again = self.journal.begin_submission('PAY-1', 'digest')
        self.assertTrue(again)
        self.assertEqual(row['state'], 'SUBMITTING')

    def test_status_fingerprint_dedupe_and_events(self):
        self.journal.begin_submission('PAY-1', 'digest')
        self.journal.mark_submitted('PAY-1', 'digest', 'op-1')
        status = {'operation_id': 'op-1', 'profile': 'PAY-1', 'state': 'ACCEPTED',
                  'acceptance_state': 'COMMITTED', 'dispatch_state': 'PENDING',
                  'effect_state': 'NO_ATTEMPT', 'receipt_state': 'SIGNED',
                  'attempt_id': None, 'exec_consumed': False, 'queries': 0}
        previous, changed = self.journal.update_status('op-1', 'ACCEPTED', 'fp-1', status)
        self.assertTrue(changed)
        _, changed = self.journal.update_status('op-1', 'ACCEPTED', 'fp-1', status)
        self.assertFalse(changed)
        seq = self.journal.add_event('op-1', 'ACCEPTED', 'ACCEPTED', 'accepted',
                                     dedupe_key='op-1:ACCEPTED:fp-1')
        self.assertEqual(seq, 1)
        self.assertIsNone(self.journal.add_event('op-1', 'ACCEPTED', 'ACCEPTED', 'accepted',
                                                 dedupe_key='op-1:ACCEPTED:fp-1'))
        self.assertEqual([row['seq'] for row in self.journal.events()], [1])
        self.assertEqual(self.journal.events(since=1), [])
        self.assertEqual(self.journal.events(operation_id='other'), [])

    def test_operator_and_executor_leases_do_not_overlap(self):
        for digest, oid in (('a', 'op-1'), ('b', 'op-2')):
            self.journal.begin_submission('PAY-1', digest)
            self.journal.mark_submitted('PAY-1', digest, oid)
        first = self.journal.claim('operator')
        self.assertEqual(first['operation_id'], 'op-1')
        second = self.journal.claim('operator')
        self.assertEqual(second['operation_id'], 'op-2')
        self.assertIsNone(self.journal.claim('operator'))
        self.journal.release('operator', 'op-1')
        again = self.journal.claim('operator')
        self.assertEqual(again['operation_id'], 'op-1')
        self.assertIsNone(self.journal.claim('executor'))
        self.journal.update_status('op-1', 'ACCEPTED', 'fp',
                                   {'operation_id': 'op-1', 'profile': 'PAY-1',
                                    'state': 'ACCEPTED'})
        claimed = self.journal.claim('executor')
        self.assertEqual(claimed['operation_id'], 'op-1')
        self.journal.release('executor', 'op-1')

    def test_lease_expires_and_terminal_operations_are_not_claimed(self):
        self.journal.begin_submission('PAY-1', 'a')
        self.journal.mark_submitted('PAY-1', 'a', 'op-1')
        self.assertIsNotNone(self.journal.claim('operator'))
        self.now[0] += self.journal.lease + 1
        self.assertEqual(self.journal.claim('operator')['operation_id'], 'op-1')
        self.journal.mark_terminal('op-1', 'SETTLED')
        self.assertIsNone(self.journal.claim('operator'))

    def test_operation_rows_never_keep_an_intent(self):
        self.journal.begin_submission('PAY-1', 'digest')
        self.journal.mark_submitted('PAY-1', 'digest', 'op-1')
        row = self.journal.operation('op-1')
        self.assertEqual(set(row), {'operation_id', 'profile', 'digest', 'submitted_at',
                                    'updated_at', 'state', 'fingerprint', 'status',
                                    'last_event_seq', 'last_read_at', 'read_failures',
                                    'terminal', 'operator_lease_until',
                                    'executor_lease_until'})


if __name__ == '__main__':
    unittest.main()
