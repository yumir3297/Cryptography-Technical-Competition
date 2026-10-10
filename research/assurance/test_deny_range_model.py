import unittest
from deny_range_model import ApprovalIndex


class ProposedDenyRangeTests(unittest.TestCase):
    def test_deny_before_prepare_blocks(self):
        w=ApprovalIndex()
        w.publish('basis-1','ANOMALY','APPROVE','v2')
        w.publish('basis-1','ANOMALY','DENY','v1')
        self.assertEqual(w.commit(w.prepare('basis-1','ANOMALY'),'op1'),'REJECT')

    def test_concurrent_deny_after_prepare_invalidates_range(self):
        w=ApprovalIndex()
        w.publish('basis-1','ANOMALY','APPROVE','v2')
        read=w.prepare('basis-1','ANOMALY')
        w.publish('basis-1','ANOMALY','DENY','v1')
        self.assertEqual(w.commit(read,'op1'),'STALE')
        self.assertEqual(len(w.accepted),0)

    def test_empty_range_to_nonempty_changes_revision(self):
        w=ApprovalIndex()
        first=w.prepare('basis-1','ANOMALY')
        self.assertEqual(first.publish_revision,0)
        w.publish('basis-1','ANOMALY','DENY','v1')
        self.assertEqual(w.commit(first,'op1'),'STALE')

    def test_deny_after_already_accepted_is_not_retroactive(self):
        w=ApprovalIndex()
        w.publish('basis-1','ANOMALY','APPROVE','v2')
        self.assertEqual(w.commit(w.prepare('basis-1','ANOMALY'),'op1'),'ACCEPTED')
        w.publish('basis-1','ANOMALY','DENY','v1')
        self.assertIn('op1',w.accepted)
        self.assertEqual(w.commit(w.prepare('basis-1','ANOMALY'),'op2'),'REJECT')

    def test_selected_refs_only_has_counterexample(self):
        w=ApprovalIndex()
        w.publish('basis-1','ANOMALY','APPROVE','v2')
        w.publish('basis-1','ANOMALY','DENY','v1')
        self.assertEqual(w.naive_selected_refs_only(True,'op_bad'),'ACCEPTED')
        self.assertEqual(w.commit(w.prepare('basis-1','ANOMALY'),'op_good'),'REJECT')

if __name__=='__main__':unittest.main()
