"""Scene business derivation against actual signed records and upstream schemas."""
import copy
import importlib
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from competition.support.scene_authority import SceneAuthority, ROLES, PURPOSES, _json
from competition.support.wire import Identity, ProtocolError, keyid, rec_ref
from competition.support.schema import UpstreamSchema
from competition.core.event_clock import require_window


class Actor(Identity):
    def __init__(self, alias, profile):
        self.name = 'fresh-' + alias.lower()
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kid = keyid(self.pub)
        self.roles = frozenset([ROLES[profile][alias]])
        self.purposes = frozenset(PURPOSES[alias])


class AuthenticatedStore:
    """Use real C publication and original credentials for isolated business tests."""
    def __init__(self, authority):
        self.authority = authority
        self.reads = []

    def current(self, c, profile, namespace, key):
        assert profile == self.authority.profile
        self.reads.append(namespace)
        return self.authority.current(c, namespace, key)

    def credential(self, c, profile, alias, role, purpose, action, event):
        rows = self.authority._credential(c, alias, role, purpose, action)
        for row in rows:
            require_window(row['record']['value'], event)
        return rows


class SceneAdapterTests(unittest.TestCase):
    def setUp(self):
        try:
            self.seed = importlib.import_module('competition.profiles.scene_seed').build_scene
            self.adapter_type = importlib.import_module('competition.profiles.authorization_scene').SceneAuthorizationAdapter
        except ModuleNotFoundError:
            self.fail('Missing Scene business seed/authorization derivation API')
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.folder.cleanup)

    def build(self, profile, label=None, same_holder=False):
        actors = {alias: Actor(alias, profile) for alias in ('H', 'G', 'X', 'U', 'V', 'E')}
        if same_holder:
            actors['U'].name = actors['H'].name
        authority = SceneAuthority(Path(self.folder.name) / (profile + str(label) + str(same_holder) + '.sqlite'), profile, actors=actors)
        for alias in actors:
            roles = [ROLES[profile][alias]] + (['READER'] if alias != 'E' else [])
            authority.grant(alias, roles)
        result = self.seed(profile, actors, authority.scope, 1000, label=label)
        with authority.tx() as c:
            for row in result['rows']:
                ns, key, record = row['namespace'], row['key'], row['record']
                rr = authority._state_ref(ns, key, 1, record['value']) if ns in ('UNIT', 'ENCOUNTER', 'BEHAVIOR') else rec_ref(record)
                c.execute('INSERT INTO current_row VALUES(?,?,?,?,?,1)', (ns, _json(key), 1, rr, _json(record)))
        store = AuthenticatedStore(authority)
        op = {k: result[k] for k in ('action', 'task_id', 'scene_key')}
        op['assessment'] = {'value': {'cutoff': '1000', 'iat': '1000', 'exp': '1100'}}
        return authority, store, op, self.adapter_type(store, profile, actors)

    def test_defaults_reconstruct_real_schema_and_required_reviews(self):
        for profile, expected in [('IND-DEMO-1', ['QUALITY_REVIEW']), ('MED-DEMO-1', ['CLINICAL_REVIEW'])]:
            with self.subTest(profile=profile):
                authority, store, op, adapter = self.build(profile)
                with authority.db() as c:
                    derived = adapter.derive(c, op, {'lo': 1001, 'hi': 1002})
                self.assertEqual(derived['required_reviews'], expected)
                self.assertEqual(derived['basis_deps'], derived['deps'])
                self.assertFalse({'EVIDENCE', 'IDENTITY', 'PACKAGE'} & {d['namespace'] for d in derived['deps']})
                schema = UpstreamSchema(Path(__file__).resolve().parents[2], profile)
                assessment = {'version': '2.6', 'profile': profile, 'kind': 'ASSESSMENT', 'scope': authority.scope, 'value': derived['assessment_value']}
                schema.validate(assessment, 'Record_ASSESSMENT')
                for dep in derived['deps']:
                    schema.validate(dep, 'Dep')
                for row in self.seed(profile, authority.actors, authority.scope, 1000)['rows']:
                    if row['namespace'] not in ('UNIT', 'ENCOUNTER', 'BEHAVIOR'):
                        schema.validate(row['record'], 'Record_' + row['record']['kind'])

    def test_med_read_denial_precedes_source_read(self):
        authority, store, op, adapter = self.build('MED-DEMO-1')
        key = authority.role_key(authority.actors['H'], 'READER')
        authority.publish('ROLE', key, authority.current_record('ROLE', key), active=False)
        with authority.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, {'lo': 1001, 'hi': 1002})
        self.assertNotIn('EVIDENCE', store.reads)

    def test_ind_authenticated_defect_cannot_release(self):
        authority, store, op, adapter = self.build('IND-DEMO-1', 'DEMO_DEFECT')
        op['action']['payload']['route'] = 'RELEASE'
        op['action']['destination'] = 'ind-release-bin'
        with authority.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, {'lo': 1001, 'hi': 1002})

    def test_med_signature_cannot_cover_tampered_patient(self):
        authority, store, op, adapter = self.build('MED-DEMO-1')
        with authority.tx() as c:
            row = authority.current(c, 'EVIDENCE', op['scene_key'])
            record = copy.deepcopy(row['record'])
            record['value']['data']['synthetic_patient_id'] = 'patient-b'
            c.execute('UPDATE current_row SET ref=?,record=? WHERE namespace=? AND key=?', (rec_ref(record), _json(record), 'EVIDENCE', _json(op['scene_key'])))
        with authority.db() as c:
            with self.assertRaisesRegex(ProtocolError, 'BAD_SIGNATURE'):
                adapter.derive(c, op, {'lo': 1001, 'hi': 1002})

    def test_h_u_same_subject_remains_legal(self):
        authority, store, op, adapter = self.build('MED-DEMO-1', same_holder=True)
        with authority.db() as c:
            self.assertEqual(adapter.derive(c, op, {'lo': 1001, 'hi': 1002})['required_reviews'], ['CLINICAL_REVIEW'])

    def test_original_identity_current_window_is_rechecked(self):
        authority, store, op, adapter = self.build('MED-DEMO-1')
        key = authority.scope_key() + ['patient-a', 'encounter-a']
        record = authority.current_record('IDENTITY', key)
        record['value']['exp'] = '1002'
        authority.publish('IDENTITY', key, record)
        with authority.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, {'lo': 1001, 'hi': 1002})

    def test_frozen_cutoff_cannot_be_in_current_future(self):
        authority, store, op, adapter = self.build('MED-DEMO-1')
        op['assessment']['value']['cutoff'] = '1003'
        with authority.db() as c:
            with self.assertRaises(ProtocolError):
                adapter.derive(c, op, {'lo': 1001, 'hi': 1002})


if __name__ == '__main__':
    unittest.main()
