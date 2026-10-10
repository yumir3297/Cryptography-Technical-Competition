"""Real Ed25519 signed clock sequence/floor/interval regression."""
import sqlite3
import unittest
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.core.trusted_clock import (
    seal, prepare_table, checked_clock, consume_clock,
)
from research.reference_executor.wire import ProtocolError


SCOPE = {"domain": "lab", "tenant": "tenant-1", "scenario": "industrial"}
PROFILE, OP = "IND-DEMO-1", "competition-operation"


class SignedClockSafety(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:", isolation_level=None)
        prepare_table(self.c)
        self.sk = Ed25519PrivateKey.generate()
        self.pk = self.sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.controller = SimpleNamespace(key=self.sk)

    def tearDown(self):
        self.c.close()

    def cert(self, seq, lo, hi, purpose="PREPARE"):
        return seal(self.controller, PROFILE, SCOPE, OP, purpose, seq, lo, hi)

    def commit_interval(self, seq, lo, hi, purpose="PREPARE"):
        self.c.execute("BEGIN IMMEDIATE")
        try:
            result = checked_clock(
                self.c, self.cert(seq, lo, hi, purpose),
                self.pk, PROFILE, SCOPE, OP, purpose,
            )
            consume_clock(self.c, result[2])
            self.c.execute("COMMIT")
            return result
        except BaseException:
            if self.c.in_transaction:
                self.c.execute("ROLLBACK")
            raise

    def test_signed_elapsed_time_increases_without_equal_instant(self):
        self.assertEqual(self.commit_interval(1, 100, 100)[0], 100)
        self.assertEqual(self.commit_interval(2, 101, 102, "FINALIZE")[:2], (101, 102))
        self.assertEqual(self.c.execute(
            "SELECT sequence,time_floor FROM r2_clock WHERE id=1").fetchone(), (2, 101))

    def test_replay_rejected(self):
        self.commit_interval(1, 100, 100)
        with self.assertRaises(ProtocolError) as cm:
            self.commit_interval(1, 101, 101)
        self.assertEqual(cm.exception.code, "CLOCK_REPLAY")

    def test_time_rollback_rejected_even_with_new_sequence(self):
        self.commit_interval(1, 100, 100)
        with self.assertRaises(ProtocolError) as cm:
            self.commit_interval(2, 99, 99)
        self.assertEqual(cm.exception.code, "CLOCK_ROLLBACK")

    def test_unbounded_interval_fails_closed(self):
        with self.assertRaises(ProtocolError) as cm:
            self.commit_interval(1, 100, 103)
        self.assertEqual(cm.exception.code, "CLOCK_UNKNOWN")

    def test_tampered_signed_interval_rejected(self):
        packet = self.cert(1, 100, 100)
        packet["claim"]["hi"] = "101"
        self.c.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ProtocolError):
                checked_clock(self.c, packet, self.pk, PROFILE, SCOPE, OP, "PREPARE")
        finally:
            self.c.execute("ROLLBACK")

    def test_failed_transaction_does_not_consume_floor_or_seq(self):
        self.c.execute("BEGIN IMMEDIATE")
        checked_clock(self.c, self.cert(1, 100, 100), self.pk, PROFILE, SCOPE, OP, "PREPARE")
        self.c.execute("ROLLBACK")
        self.assertEqual(self.c.execute(
            "SELECT sequence,time_floor FROM r2_clock WHERE id=1").fetchone(), (0, 0))

    def test_schema_migrates_existing_sequence_without_reset(self):
        self.c.execute("DROP TABLE r2_clock")
        self.c.execute("CREATE TABLE r2_clock(id INTEGER PRIMARY KEY, sequence INTEGER NOT NULL)")
        self.c.execute("INSERT INTO r2_clock VALUES(1,12)")
        prepare_table(self.c)
        self.assertEqual(self.c.execute(
            "SELECT sequence,time_floor FROM r2_clock WHERE id=1").fetchone(), (12, 0))


if __name__ == "__main__":
    unittest.main()
