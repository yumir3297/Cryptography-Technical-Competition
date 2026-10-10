"""Real C signatures, persistent W bounds and deliberately bad authenticated samples."""
import copy
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
from competition.core.signing import ClockClient
from competition.core.event_clock import DOMAIN, checked_event_clock, require_window
from research.reference_executor.wire import ProtocolError, b64, canonical


class EventClockSafety(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.keypath = Path(self.folder.name) / 'C.key'
        self.keypath.write_bytes(self.key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        self.source = Path(self.folder.name) / 'source.sqlite'
        self.clock = ClockClient(self.keypath, self.source); self.addCleanup(self.clock.close)
        self.dbpath = Path(self.folder.name) / 'w.sqlite'
        self.scope = {'domain': 'lab', 'tenant': 'tenant-1', 'scenario': 'industrial'}

    def sample(self):
        return self.clock.sample('IND-DEMO-1', self.scope, 'operation', 'ACCEPT_GUARD', 'request')

    def check(self, packet):
        with closing(sqlite3.connect(self.dbpath, isolation_level=None)) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                result = checked_event_clock(c, packet, self.pub, self.clock.instance_id, 'IND-DEMO-1', self.scope, 'operation', 'ACCEPT_GUARD', 'request')
                c.execute('COMMIT')
                return result
            except BaseException:
                c.execute('ROLLBACK'); raise

    def signed_mutation(self, packet, changes):
        value = copy.deepcopy(packet); value['claim'].update(changes)
        value['signature'] = b64(self.key.sign(canonical([DOMAIN, value['claim']])))
        return value

    def test_valid_current_sample_persists_floor_and_replay_is_rejected(self):
        packet = self.sample(); first = self.check(packet)
        with closing(sqlite3.connect(self.dbpath)) as c:
            self.assertEqual(c.execute('SELECT sequence,time_floor FROM comp_event_clock').fetchone(), (first['sequence'], first['lo']))
        with self.assertRaises(ProtocolError) as cm:
            self.check(packet)
        self.assertEqual(cm.exception.code, 'CLOCK_REPLAY')

    def test_new_sequence_cannot_make_old_sample_fresh(self):
        packet = self.sample()
        stale = self.signed_mutation(packet, {'sequence': '999', 'monotonic_ns': str(int(packet['claim']['monotonic_ns']) - 3_000_000_000)})
        with self.assertRaises(ProtocolError) as cm:
            self.check(stale)
        self.assertEqual(cm.exception.code, 'CLOCK_UNKNOWN')

    def test_new_sequence_cannot_move_below_persistent_floor(self):
        first = self.check(self.sample()); packet = self.sample()
        wall = int(packet['claim']['wall_ns']) - 5_000_000_000
        rollback = self.signed_mutation(packet, {'wall_ns': str(wall), 'lo': str(wall // 1_000_000_000), 'hi': str(wall // 1_000_000_000)})
        with self.assertRaises(ProtocolError) as cm:
            self.check(rollback)
        self.assertEqual(cm.exception.code, 'CLOCK_ROLLBACK')
        with closing(sqlite3.connect(self.dbpath)) as c:
            self.assertEqual(c.execute('SELECT time_floor FROM comp_event_clock').fetchone()[0], first['lo'])

    def test_previous_provider_instance_is_unknown_after_restart(self):
        old = self.sample(); self.clock.close()
        self.clock = ClockClient(self.keypath, self.source); self.addCleanup(self.clock.close)
        with self.assertRaises(ProtocolError) as cm:
            self.check(old)
        self.assertEqual(cm.exception.code, 'CLOCK_UNKNOWN')
        newer = self.check(self.sample())
        self.assertGreater(newer['sequence'], int(old['claim']['sequence']))

    def test_bad_signature_or_wrong_stage_cannot_consume_time(self):
        packet = self.sample(); packet['claim']['sequence'] = '999'
        with self.assertRaises(ProtocolError):
            self.check(packet)
        wrong = self.signed_mutation(self.sample(), {'stage': 'PREPARE'})
        with self.assertRaises(ProtocolError) as cm:
            self.check(wrong)
        self.assertEqual(cm.exception.code, 'CLOCK_BINDING')

    def test_interval_crossing_expiry_is_unknown_and_expired_lo_is_false(self):
        with self.assertRaises(ProtocolError) as cm:
            require_window({'iat': '100', 'exp': '102'}, {'lo': 101, 'hi': 102})
        self.assertEqual(cm.exception.code, 'CLOCK_UNKNOWN')
        with self.assertRaises(ProtocolError) as cm:
            require_window({'iat': '100', 'exp': '102'}, {'lo': 102, 'hi': 102})
        self.assertEqual(cm.exception.code, 'EXPIRED')

    def test_overwide_authenticated_interval_is_unknown(self):
        packet = self.sample()
        wide = self.signed_mutation(packet, {'hi': str(int(packet['claim']['lo']) + 3)})
        with self.assertRaises(ProtocolError) as cm:
            self.check(wide)
        self.assertEqual(cm.exception.code, 'CLOCK_UNKNOWN')


if __name__ == '__main__':
    unittest.main()
