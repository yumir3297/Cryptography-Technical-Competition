"""Desired recovery properties against the unchanged R1 guard witness."""
import unittest
from verification.protocol_v26_audit.lifecycle.model import Final, first_settlement


class OldGap(unittest.TestCase):
    def test_first_expired_receipt_has_a_recovery_route(self):
        self.assertTrue(first_settlement(Final(),1002,'K1')['admitted'])

    def test_first_receipt_after_rotation_has_a_recovery_route(self):
        self.assertTrue(first_settlement(Final(),200,'K2')['admitted'])


if __name__=='__main__':unittest.main()
