"""Same-process bridge shell: a minimal-input facade over the unchanged core.

The tests assert two things: the concrete shell satisfies the abstract
``CompetitionFacade`` contract, and a caller needs nothing beyond a profile and
an operation id to drive acceptance, one execution, settlement and an
authenticated status read for all three profiles.
"""
import os
import tempfile
import unittest
from pathlib import Path

from competition.bridge.contract import CompetitionFacade
from competition.bridge.facade import TrustedFacade


class BridgeFacadeTests(unittest.TestCase):
    seed = None
    facade = None

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

    def test_shell_satisfies_the_abstract_contract(self):
        self.assertIsInstance(self.facade, CompetitionFacade)

    def test_candidate_ingress_accepts_a_trusted_corpus_action(self):
        profile = 'PAY-1'
        action = self.seed.operations[profile]['action']
        self.assertEqual(self.facade.submit(profile, action), action)
        with self.assertRaises(Exception):
            self.facade.submit(profile, {**action, 'scope': {'domain': 'lab', 'tenant': 'tenant-1',
                                                             'scenario': 'industrial'}})

    def test_profile_and_operation_id_drive_the_whole_path(self):
        for profile in ('IND-DEMO-1', 'PAY-1', 'MED-DEMO-1'):
            with self.subTest(profile=profile):
                ticket = self.facade.prepare(profile)
                operation_id = ticket['operation_id']
                accepted = self.facade.accept(profile, operation_id)
                self.assertEqual(accepted['acceptance_state'], 'COMMITTED')
                claimed = self.facade.claim(profile, operation_id)
                self.assertEqual(claimed['dispatch_state'], 'STARTED')
                response = self.facade.execute_once(profile, operation_id)
                self.assertIsNotNone(response.get('record'))
                settled = self.facade.settle(profile, operation_id)
                self.assertEqual(settled['state'], 'SETTLED')
                view = self.facade.status(profile, operation_id)
                self.assertEqual(view['operation_id'], operation_id)
                self.assertEqual(view['acceptance_state'], 'COMMITTED')


if __name__ == '__main__':
    unittest.main()
