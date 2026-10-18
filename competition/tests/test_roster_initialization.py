"""Initialization from collected public keys: no role key is written here.

The whole point of the inversion, in one place:

* the endpoints generate their own keys and publish only the public halves;
* initialization builds the roster from those publics and writes **C.key and
  nothing else** -- there is no ``<profile>-<alias>.key`` beside the trusted state
  to find;
* every signature in the corpus -- each chain message, each source attestation,
  each possession proof -- still comes back over the protocol, from the endpoint
  that owns the key, and is verified against the published public key;
* the default local path is untouched: the same function with no ``roster``
  generates the keys it always did.
"""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from competition.client.host import answer
from competition.client.keys import generate
from competition.client.signer import CHAIN_DOMAIN, RoleSigner
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.authorization_seed import initialize
from competition.server.roster import ALIASES, actors, read_entry
from competition.support.wire import ProtocolError, canonical, load_canonical, raw, strict_verify

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)

CHAIN_FIELDS = (('reviews', 'V'), ('authorization', 'U'), ('issue', 'H'),
                ('permit', 'G'), ('challenge_request', 'H'), ('challenge', 'X'), ('proof', 'H'))


def verify_chain(test, roster, profile, op):
    """Every message in the operation's chain, checked against the published key."""
    for name, alias in CHAIN_FIELDS:
        messages = op[name] if name == 'reviews' else [op[name]]
        for message in messages:
            with test.subTest(profile=profile, field=name):
                who = roster[profile][alias]
                test.assertEqual(message['protected']['kid'], who.kid)
                strict_verify(who.pub, raw(message['sig'], 64),
                              canonical([CHAIN_DOMAIN, message['protected'], message['body']]))


class EndpointFleet:
    """Every endpoint on one machine, reached through the real signing host."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.calls = []
        self.lines = [generate(self.folder, profile, role)
                      for profile in PROFILE_SCOPES for role in ALIASES]
        self.entries = [read_entry(line) for line in self.lines]
        self.clients = {(entry.profile, entry.role):
                        RoleSigner.from_directory(self.folder, entry.profile, entry.role)
                        for entry in self.entries}

    def roster(self):
        return actors(self.entries, self.transport_for)

    def transport_for(self, entry):
        return _EndpointTransport(self, entry)


class _EndpointTransport:
    """One endpoint's socket, in process: the same ``answer`` the host serves."""

    def __init__(self, fleet, entry):
        self.fleet = fleet
        self.entry = entry

    def request(self, message):
        blob = base64.urlsafe_b64decode(message['data'] + '=' * (-len(message['data']) % 4))
        self.fleet.calls.append((self.entry.profile, self.entry.role,
                                 load_canonical(blob)[0]))
        line = json.dumps(message, sort_keys=True).encode('utf-8') + b'\n'
        return answer(line, self.fleet.clients[(self.entry.profile, self.entry.role)])


class ExternalRosterInitializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.fleet = EndpointFleet(Path(cls.work.name) / 'endpoints')
        cls.roster = cls.fleet.roster()
        cls.folder = Path(cls.work.name) / 'w'
        cls.trusted = initialize(cls.folder, roster=cls.roster)

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_no_role_key_is_written_beside_the_trusted_state(self):
        self.assertEqual({path.name for path in self.folder.glob('*.key')}, {'C.key'})
        for profile in PROFILE_SCOPES:
            for alias in ALIASES:
                self.assertFalse((self.folder / (profile + '-' + alias + '.key')).exists())

    def test_every_endpoint_signed_its_own_part_of_the_corpus(self):
        asked = {(profile, role) for profile, role, _ in self.fleet.calls}
        expected = {(profile, role) for profile in PROFILE_SCOPES for role in ALIASES}
        self.assertEqual(asked, expected)

    def test_each_endpoint_proved_possession_of_its_own_key(self):
        # The black box verifies every possession proof against the public key it
        # published (``TrustedState._possession``), so the corpus existing at all
        # already means the endpoints produced them; this pins who and over what.
        proofs = {(profile, role) for profile, role, domain in self.fleet.calls
                  if domain == 'ZJJ-ENROLL-v1'}
        self.assertEqual(proofs, {(profile, role) for profile in PROFILE_SCOPES
                                  for role in ALIASES})
        self.assertTrue({'ZJJ-SIG-v1', 'ZJJ-SOURCE-v1', 'ZJJ-ENROLL-v1'} <=
                        {domain for _, _, domain in self.fleet.calls})

    def test_the_corpus_verifies_against_the_published_public_keys(self):
        for profile, op in self.trusted.operations.items():
            verify_chain(self, self.roster, profile, op)

    def test_the_guard_accepts_an_identity_proof_signed_by_the_endpoint(self):
        for profile, op in self.trusted.operations.items():
            with self.subTest(profile=profile):
                proof = self.trusted.identity_proof(profile, op)
                decision = self.trusted.service.guard(profile, op, proof)
                self.assertEqual(decision['decision'], 'T')


class InitializationGuardsTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.work.cleanup)
        self.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        self.addCleanup(self._restore_env)
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)

    def _restore_env(self):
        for name, value in self.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_a_roster_and_its_own_names_cannot_be_combined(self):
        with self.assertRaises(ProtocolError) as caught:
            initialize(Path(self.work.name) / 'both', roster={}, names={('PAY-1', 'H'): 'x'})
        self.assertEqual(caught.exception.code, 'INIT_ROSTER_NAMES')

    def test_an_incomplete_roster_is_refused_by_the_black_box(self):
        fleet = EndpointFleet(Path(self.work.name) / 'partial')
        full = fleet.roster()
        partial = {profile: {alias: actor for alias, actor in roster.items() if alias != 'E'}
                   for profile, roster in full.items()}
        with self.assertRaises(ProtocolError) as caught:
            initialize(Path(self.work.name) / 'partial-w', roster=partial)
        self.assertEqual(caught.exception.code, 'ROSTER_SET')


if __name__ == '__main__':
    unittest.main()
