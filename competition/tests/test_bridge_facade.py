"""Same-process bridge shell: explicit challenge/signature separation.

The tests assert the concrete shell satisfies the abstract ``CompetitionFacade``
contract; that a caller-supplied Action and context drive the whole path; and
that signatures genuinely come from the caller -- a wrong-key proof and a
replayed challenge are both rejected.
"""
import copy
import os
import tempfile
import unittest
from pathlib import Path

from competition.bridge.contract import CompetitionFacade
from competition.bridge.facade import TrustedFacade
from competition.support.wire import b64, canonical


class ExternalSigner:
    """A stand-in external caller that owns keys and answers challenges itself."""

    def __init__(self, run):
        self._run = run

    def guard(self, profile, claim):
        return self._sign(self._run.actors[profile]['H'].key, 'COMP-APP-AUTHZ-IDENTITY-v1', claim)

    def accept(self, profile, claim):
        return self._sign(self._run.actors[profile]['H'].key, 'COMP-APP-ACCEPT-v1', claim)

    def worker(self, claim):
        return self._sign(self._run.worker_key, 'COMP-W-WORKER-v1', claim)

    def read(self, profile, claim):
        return self._sign(self._run.actors[profile]['H'].key, 'COMP-W-READ-v1', claim)

    @staticmethod
    def _sign(key, domain, claim):
        return {'claim': claim, 'signature': b64(key.sign(canonical([domain, claim])))}


class BridgeFacadeTests(unittest.TestCase):
    seed = None
    facade = None
    signer = None

    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[3] / 'tmp'
        cls.temp_root.mkdir(exist_ok=True)
        cls.folder = tempfile.TemporaryDirectory(dir=cls.temp_root)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(cls.temp_root)

    @classmethod
    def tearDownClass(cls):
        if cls.seed is not None:
            cls.seed.close()
        cls.folder.cleanup()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        from competition.profiles.w_seed import initialize
        if type(self).seed is None:
            type(self).seed = initialize(Path(self.folder.name) / 'w')
            type(self).facade = TrustedFacade(type(self).seed)
            type(self).signer = ExternalSigner(type(self).seed)

    def _build(self, profile):
        base = self.seed.operations[profile]
        return self.facade.build_op(profile, copy.deepcopy(base['action']),
                                    base['task_id'], base['scene_key'])

    def test_shell_satisfies_the_abstract_contract(self):
        self.assertIsInstance(self.facade, CompetitionFacade)

    def test_build_op_uses_the_supplied_action(self):
        profile = 'PAY-1'
        base = self.seed.operations[profile]
        action = copy.deepcopy(base['action'])
        op = self.facade.build_op(profile, action, base['task_id'], base['scene_key'])
        self.assertEqual(op['action']['payload'], action['payload'])
        self.assertNotEqual(op['action']['operation_id'], action['operation_id'])
        self.assertEqual(op['task_id'], base['task_id'])
        self.assertEqual(op['scene_key'], base['scene_key'])

    def test_profile_action_and_context_drive_the_whole_path(self):
        for profile in ('IND-DEMO-1', 'PAY-1', 'MED-DEMO-1'):
            with self.subTest(profile=profile):
                op = self._build(profile)
                oid = op['action']['operation_id']
                guard = self.facade.challenge(profile, op)
                ticket = self.facade.prepare(profile, op, self.signer.guard(profile, guard))
                self.assertEqual(ticket['operation_id'], oid)
                acc = self.facade.challenge_accept(profile, ticket['ticket_id'])
                accepted = self.facade.accept(profile, ticket['ticket_id'],
                                              self.signer.accept(profile, acc))
                self.assertEqual(accepted['acceptance_state'], 'COMMITTED')
                cl = self.facade.challenge_worker(profile, oid, 'CLAIM')
                claimed = self.facade.claim(profile, oid, self.signer.worker(cl))
                self.assertEqual(claimed['dispatch_state'], 'STARTED')
                ex = self.facade.challenge_worker(profile, oid, 'EXECUTE')
                response = self.facade.execute_once(profile, oid, self.signer.worker(ex))
                self.assertIsNotNone(response.get('record'))
                st = self.facade.challenge_worker(profile, oid, 'SETTLE')
                settled = self.facade.settle(profile, oid, response, self.signer.worker(st))
                self.assertEqual(settled['state'], 'SETTLED')
                rd = self.facade.challenge_read(profile, oid, 'STATUS')
                view = self.facade.status(profile, oid, self.signer.read(profile, rd))
                self.assertEqual(view['operation_id'], oid)
                self.assertEqual(view['acceptance_state'], 'COMMITTED')

    def test_wrong_signature_is_rejected(self):
        profile = 'PAY-1'
        op = self._build(profile)
        claim = self.facade.challenge(profile, op)
        # A worker-key signature is the wrong key/domain for the GUARD step.
        with self.assertRaises(Exception):
            self.facade.prepare(profile, op, self.signer.worker(claim))

    def test_replayed_challenge_is_rejected(self):
        profile = 'PAY-1'
        op = self._build(profile)
        claim = self.facade.challenge(profile, op)
        proof = self.signer.guard(profile, claim)
        self.facade.prepare(profile, op, proof)
        with self.assertRaises(Exception):
            self.facade.prepare(profile, op, proof)


if __name__ == '__main__':
    unittest.main()
