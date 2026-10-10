"""Behavior gates for the actual IND time/receipt slice, separate from formal39."""
import importlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from research.reference_executor.wire import ProtocolError, rec_ref, canonical, b64, raw, strict_verify


class IndustrialTimeAcceptance(unittest.TestCase):
    def setUp(self):
        try:
            self.seed_module = importlib.import_module('competition.profiles.industrial_seed')
        except ModuleNotFoundError:
            self.fail('Missing real-time industrial initializer/acceptance path')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.seed = self.seed_module.initialize(Path(self.folder.name))
        self.addCleanup(self.seed.close)
        self.w = self.seed.w

    def ticket(self):
        return self.w.prepare(self.seed.op)

    def authenticated_accept(self, ticket_id, signer=None):
        return self.w.accept(ticket_id, signer, proof=self.seed.accept_proof(ticket_id))

    def test_unsigned_outer_action_cannot_change_signed_context(self):
        op = json.loads(json.dumps(self.seed.op))
        op['action']['operation_id'] = b64(b'A' * 16)
        with self.assertRaises(ProtocolError) as cm:
            self.w.prepare(op)
        self.assertEqual(cm.exception.code, 'BINDING')
        self.assertEqual(self.w.snapshot()['accepts'], 0)

    def test_ticket_alone_does_not_authenticate_acceptance(self):
        ticket = self.ticket()
        with self.assertRaises(ProtocolError) as cm:
            self.w.accept(ticket['ticket_id'])
        self.assertEqual(cm.exception.code, 'ACCEPT_AUTH_REQUIRED')
        self.assertEqual(self.w.snapshot()['accepts'], 0)

    def test_accept_identity_challenge_is_one_use(self):
        ticket = self.ticket()
        proof = self.seed.accept_proof(ticket['ticket_id'])
        first = self.w.accept(ticket['ticket_id'], proof=proof)
        with self.assertRaises(ProtocolError) as cm:
            self.w.accept(ticket['ticket_id'], proof=proof)
        self.assertEqual(cm.exception.code, 'REPLAY')
        recovered = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(first['frozen'], recovered['frozen'])
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (1, 1))

    def test_x_signature_cannot_authenticate_holder_acceptance(self):
        ticket = self.ticket()
        claim = self.w.challenge_accept(ticket['ticket_id'])
        proof = {'claim': claim, 'signature': b64(self.seed.actors['X'].key.sign(canonical(['COMP-APP-ACCEPT-v1', claim])))}
        with self.assertRaises(ProtocolError):
            self.w.accept(ticket['ticket_id'], proof=proof)
        self.assertEqual(self.w.snapshot()['accepts'], 0)

    def test_current_policy_removal_denies_status(self):
        ticket = self.ticket()
        self.authenticated_accept(ticket['ticket_id'])
        key = self.seed.issuer.scope_key()
        record = self.seed.issuer.current_record('POLICY', key)
        record['value']['readers'].remove(self.seed.actors['H'].name)
        self.seed.issuer.publish('POLICY', key, record)
        with self.assertRaises(ProtocolError) as cm:
            self.w.status(self.seed.op['action']['operation_id'], self.seed.status_proof())
        self.assertEqual(cm.exception.code, 'NO_ROLE')

    def test_legacy_mutation_entrypoints_are_closed(self):
        for name in ('prepare_accept', 'finalize_accept', 'claim_r2', 'cancel_r2', 'settle_r2', 'activate_tool', 'rotate_root_epoch', 'init_scene', 'init_behavior'):
            with self.subTest(name=name), self.assertRaises(ProtocolError) as cm:
                getattr(self.w, name)()
            self.assertEqual(cm.exception.code, 'LEGACY_ENTRY_DISABLED')

    def test_reader_expiry_is_rechecked_at_final_acceptance_event(self):
        from unittest.mock import patch
        self.seed.close()
        expires = int(time.time()) + 6
        publish = self.seed_module.LiveInitializer.publish
        def short_readers(issuer, ns, key, record, **kw):
            if ns == 'ROLE' and record['value']['role'] == 'READER':
                record['value']['exp'] = str(expires)
            return publish(issuer, ns, key, record, **kw)
        with patch.object(self.seed_module.LiveInitializer, 'publish', short_readers):
            self.seed = self.seed_module.initialize(Path(self.folder.name) / 'reader-expiry')
        self.addCleanup(self.seed.close)
        self.w = self.seed.w
        ticket = self.ticket()
        original = self.w._plan
        def delayed(c, op, at):
            plan = original(c, op, at)
            time.sleep(max(0, expires - time.time()) + 0.05)
            return plan
        self.w._plan = delayed
        with self.assertRaises(ProtocolError) as cm:
            self.authenticated_accept(ticket['ticket_id'])
        self.assertEqual(cm.exception.code, 'EXPIRED')
        self.assertEqual(self.w.snapshot()['accepts'], 0)

    def test_cross_one_real_second_accepts_current_time_then_signs_original_core(self):
        ticket = self.ticket()
        time.sleep(1.1)
        result = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(result['observation_code'], 'ACCEPTED_WITH_RECEIPT')
        frozen = result['frozen']
        self.assertGreaterEqual(int(frozen['commit']['value']['accepted_at']) - ticket['prepared_at'], 1)
        self.assertEqual(frozen['core']['body']['iat'], frozen['commit']['value']['accepted_at'])
        self.assertEqual(frozen['core']['body']['payload']['commit_record_ref'], rec_ref(frozen['commit']))
        self.assertEqual(self.w.snapshot()['accepts'], 1)
        self.assertEqual(self.w.snapshot()['reserved'], 1)
        self.assertEqual(self.w.snapshot()['calls'], 0)
        sig = raw(result['acceptance']['sig'], 64)
        strict_verify(self.seed.actors['X'].pub, sig, canonical(['ZJJ-SIG-v1', frozen['core']['protected'], frozen['core']['body']]))

    def test_signer_failure_preserves_acceptance_and_blocks_claim(self):
        ticket = self.ticket()
        self.seed.x.close()
        result = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(result['observation_code'], 'COMMITTED_RECEIPT_PENDING')
        self.assertEqual(self.w.snapshot()['accepts'], 1)
        self.assertEqual(self.w.snapshot()['reserved'], 1)
        with self.assertRaises(ProtocolError):
            self.w.claim(self.seed.op['action']['operation_id'])
        self.assertEqual(self.w.snapshot()['calls'], 0)

    def test_recovery_keeps_exact_commit_core_refs_and_one_reservation(self):
        ticket = self.ticket()
        first = self.authenticated_accept(ticket['ticket_id'])
        second = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        third = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(first['frozen'], second['frozen'])
        self.assertEqual(second['acceptance'], third['acceptance'])
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (1, 1))

    def test_original_request_retry_requires_current_holder_identity(self):
        ticket = self.ticket()
        self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.seed.revoke('H')
        with self.assertRaises(ProtocolError):
            self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (1, 1))

    def test_revocation_before_accept_leaves_no_acceptance(self):
        ticket = self.ticket()
        self.seed.revoke('U')
        with self.assertRaises(ProtocolError):
            self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (0, 0))

    def test_current_x_revocation_after_accept_leaves_original_pending(self):
        ticket = self.ticket()
        first = self.authenticated_accept(ticket['ticket_id'])
        self.seed.revoke('X')
        second = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(second['observation_code'], 'COMMITTED_RECEIPT_PENDING')
        self.assertEqual(first['frozen'], second['frozen'])
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (1, 1))

    def test_expired_ticket_leaves_no_acceptance(self):
        self.seed.close()
        self.seed = self.seed_module.initialize(Path(self.folder.name) / 'expiry', proof_ttl=5)
        self.addCleanup(self.seed.close)
        self.w = self.seed.w
        ticket = self.ticket()
        time.sleep(max(0, ticket['expires'] - time.time()) + 0.05)
        with self.assertRaises(ProtocolError) as cm:
            self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(cm.exception.code, 'EXPIRED')
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (0, 0))

    def test_clock_unavailable_cannot_accept(self):
        ticket = self.ticket()
        self.seed.clock.close()
        with self.assertRaises(ProtocolError) as cm:
            self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(cm.exception.code, 'CLOCK_UNKNOWN')
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved']), (0, 0))

    def test_current_x_grant_expiry_cannot_change_original_core_or_release(self):
        ticket = self.ticket()
        first = self.authenticated_accept(ticket['ticket_id'])
        self.seed.expire_x_credential()
        second = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(second['observation_code'], 'COMMITTED_RECEIPT_PENDING')
        self.assertEqual(first['frozen'], second['frozen'])
        self.assertEqual(self.w.snapshot()['reserved'], 1)

    def test_status_is_authenticated_and_does_not_sign_or_accept(self):
        ticket = self.ticket()
        original = self.authenticated_accept(ticket['ticket_id'])
        before = self.w.snapshot()
        query = self.seed.status_proof()
        view = self.w.status(self.seed.op['action']['operation_id'], query)
        self.assertEqual(view['observation_code'], 'COMMITTED_RECEIPT_PENDING')
        self.assertEqual(view['frozen'], original['frozen'])
        self.assertEqual(before, self.w.snapshot())
        with self.assertRaises(ProtocolError):
            self.w.status(self.seed.op['action']['operation_id'], None)

    def test_hard_exit_after_commit_recovers_without_second_accept_or_reservation(self):
        ticket = self.ticket()
        checkpoint = Path(self.folder.name) / 'child_checkpoint.json'
        self.seed.save_public_checkpoint(checkpoint, ticket['ticket_id'])
        child = subprocess.run([sys.executable, '-m', 'competition.run_time_slice', '--crash-accept', str(checkpoint)], capture_output=True, text=True)
        self.assertEqual(child.returncode, 97, child.stderr)
        with self.w.db() as c:
            before = c.execute('SELECT frozen_json FROM comp_acceptance').fetchone()[0]
        result = self.authenticated_accept(ticket['ticket_id'], self.seed.x)
        self.assertEqual(json.loads(before), result['frozen'])
        self.assertEqual((self.w.snapshot()['accepts'], self.w.snapshot()['reserved'], self.w.snapshot()['calls']), (1, 1, 0))


if __name__ == '__main__':
    unittest.main()
