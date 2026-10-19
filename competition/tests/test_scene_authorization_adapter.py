"""Scene business derivation against actual signed records and upstream schemas.

Rewritten for the shared competition core: the fixture is a real three-profile
authorization corpus built by ``authorization_seed`` (C-signed records and a real
E source attestation).  No retired research authority is involved.
"""
import copy
import tempfile
import unittest
from pathlib import Path

from competition.profiles.authorization_seed import initialize
from competition.profiles.authorization_scene import SceneAuthorizationAdapter
from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.support.schema import UpstreamSchema
from competition.support.wire import ProtocolError

ROOT = Path(__file__).resolve().parents[2]


class ReadTrackingStore:
    """Record every namespace read so ACL-before-source can be asserted."""

    def __init__(self, store):
        self.store = store
        self.reads = []

    def current(self, c, profile, namespace, key):
        self.reads.append(namespace)
        return self.store.current(c, profile, namespace, key)

    def credential(self, c, profile, alias, role, purpose, action, event):
        return self.store.credential(c, profile, alias, role, purpose, action, event)


class SceneAdapterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)

    def build(self, profile, label=None, same_holder=False, tag=''):
        names = None
        if same_holder:
            names = {(profile, 'U'): 'auth-' + PROFILE_SCOPES[profile]['scenario'] + '-h'}
        run = initialize(Path(self.folder.name) / (profile + tag), ind_label=label, names=names)
        self.addCleanup(run.close)
        store = ReadTrackingStore(run.store)
        adapter = SceneAuthorizationAdapter(store, profile, run.actors[profile])
        return run, store, adapter

    @staticmethod
    def event(run, profile, offset=1):
        value = run.operations[profile]['assessment']['value']
        lo = int(value['iat']) + offset
        return {'lo': lo, 'hi': lo}

    def test_defaults_reconstruct_real_schema_and_required_reviews(self):
        for profile, expected in [('IND-DEMO-1', ['QUALITY_REVIEW']), ('MED-DEMO-1', ['CLINICAL_REVIEW'])]:
            with self.subTest(profile=profile):
                run, store, adapter = self.build(profile, tag='-' + profile)
                with run.store.db() as c:
                    derived = adapter.derive(c, run.operations[profile], self.event(run, profile))
                self.assertEqual(derived['required_reviews'], expected)
                self.assertEqual(derived['basis_deps'], derived['deps'])
                self.assertFalse({'EVIDENCE', 'IDENTITY', 'PACKAGE'} & {d['namespace'] for d in derived['deps']})
                schema = UpstreamSchema(ROOT, profile)
                assessment = {'version': '2.6', 'profile': profile, 'kind': 'ASSESSMENT',
                              'scope': PROFILE_SCOPES[profile], 'value': derived['assessment_value']}
                schema.validate(assessment, 'Record_ASSESSMENT')
                for dep in derived['deps']:
                    schema.validate(dep, 'Dep')

    def test_med_read_denial_precedes_source_read(self):
        run, store, adapter = self.build('MED-DEMO-1', tag='-acl')
        holder = run.actors['MED-DEMO-1']['H']
        key = prefix('MED-DEMO-1') + [holder.name, 'READER']
        with run.store.db() as c:
            row = run.store.current(c, 'MED-DEMO-1', 'ROLE', key)
        record = copy.deepcopy(row['record'])
        record['value']['epoch'] = str(row['revision'] + 1)
        run.publish('MED-DEMO-1', 'ROLE', key, record, active=False)
        with run.store.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, run.operations['MED-DEMO-1'], self.event(run, 'MED-DEMO-1'))
        self.assertNotIn('EVIDENCE', store.reads)

    def test_ind_authenticated_defect_cannot_release(self):
        run, store, adapter = self.build('IND-DEMO-1', label='DEMO_DEFECT', tag='-defect')
        op = copy.deepcopy(run.operations['IND-DEMO-1'])
        op['action']['payload']['route'] = 'RELEASE'
        op['action']['destination'] = 'ind-release-bin'
        with run.store.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, self.event(run, 'IND-DEMO-1'))

    def test_med_signature_cannot_cover_tampered_patient(self):
        run, store, adapter = self.build('MED-DEMO-1', tag='-tamper')
        op = run.operations['MED-DEMO-1']
        key = op['scene_key']
        with run.store.db() as c:
            record = copy.deepcopy(run.store.current(c, 'MED-DEMO-1', 'EVIDENCE', key)['record'])
        record['value']['data']['synthetic_patient_id'] = 'patient-b'
        run.publish('MED-DEMO-1', 'EVIDENCE', key, record)
        with run.store.db() as c:
            with self.assertRaisesRegex(ProtocolError, 'BAD_SIGNATURE'):
                adapter.derive(c, op, self.event(run, 'MED-DEMO-1'))

    def test_h_u_same_subject_remains_legal(self):
        run, store, adapter = self.build('MED-DEMO-1', same_holder=True, tag='-same')
        with run.store.db() as c:
            derived = adapter.derive(c, run.operations['MED-DEMO-1'], self.event(run, 'MED-DEMO-1'))
        self.assertEqual(derived['required_reviews'], ['CLINICAL_REVIEW'])

    def test_original_identity_current_window_is_rechecked(self):
        run, store, adapter = self.build('MED-DEMO-1', tag='-idwin')
        key = prefix('MED-DEMO-1') + ['patient-a', 'encounter-a']
        with run.store.db() as c:
            row = run.store.current(c, 'MED-DEMO-1', 'IDENTITY', key)
        record = copy.deepcopy(row['record'])
        record['value']['exp'] = str(self.event(run, 'MED-DEMO-1')['lo'])
        run.publish('MED-DEMO-1', 'IDENTITY', key, record)
        with run.store.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, run.operations['MED-DEMO-1'], self.event(run, 'MED-DEMO-1'))

    def test_frozen_cutoff_cannot_be_in_current_future(self):
        run, store, adapter = self.build('MED-DEMO-1', tag='-cutoff')
        op = copy.deepcopy(run.operations['MED-DEMO-1'])
        event = self.event(run, 'MED-DEMO-1')
        op['assessment']['value']['cutoff'] = str(event['lo'] + 10)
        with run.store.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, event)


if __name__ == '__main__':
    unittest.main()
