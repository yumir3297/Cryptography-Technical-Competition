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
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from competition.client.host import answer
from competition.client.keys import generate
from competition.client.signer import CHAIN_DOMAIN, RoleSigner
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.authorization_seed import initialize
from competition.server.roster import ALIASES, actors, key_file_name, read_entry
from competition.support.wire import ProtocolError, b64, canonical, load_canonical, raw, strict_verify

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


class FleetEndToEndTests(unittest.TestCase):
    """Every endpoint a real process, reached over its own socket.

    This is the deployment the other tests describe: ``--keygen`` writes one key
    per endpoint, each endpoint serves its own signing socket, the trusted side
    reads only the published publics, and the three normal profiles run end to
    end -- worker, X receipt and tool included -- with no role key on the trusted
    side at all.
    """

    @classmethod
    def setUpClass(cls):
        from competition.profiles.w_seed import initialize as initialize_w
        from competition.server.roster import Fleet
        from competition.server.service import TrustedService
        from competition.server.signer import LocalSigner
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        root = Path(cls.work.name) / 'endpoints'
        lines = [generate(root, profile, role) for profile in PROFILE_SCOPES for role in ALIASES]
        lines.append(generate(root, None, 'worker'))
        lines += [generate(root, profile, 'tool') for profile in PROFILE_SCOPES]
        cls.root = root
        manifest = cls.manifest = Path(cls.work.name) / 'roster.jsonl'
        manifest.write_text('\n'.join(json.dumps(line, sort_keys=True) for line in lines) + '\n',
                            encoding='utf-8')
        cls.processes = []
        cls.fleet = Fleet.read(root, manifest)
        try:
            for entry in cls.fleet.entries:
                if entry.role == 'tool':
                    continue  # the tool reads its own key; it serves no challenge host
                cls.processes.append(_serve_process(root, entry))
            for entry in cls.fleet.entries:
                if entry.role != 'tool':
                    _await_socket(Path(cls.fleet.socket_path(entry)))
            cls.folder = Path(cls.work.name) / 'w'
            cls.trusted = initialize_w(cls.folder, fleet=cls.fleet)
            cls.service = TrustedService(cls.trusted, LocalSigner(cls.trusted))
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls, 'processes', ()):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        if getattr(cls, 'trusted', None) is not None:
            cls.trusted.close()
        work = getattr(cls, 'work', None)
        if work is not None:
            work.cleanup()
        for name, value in getattr(cls, 'env', {}).items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.trusted = None

    def test_only_the_root_and_the_delivery_key_are_written_here(self):
        self.assertEqual({path.name for path in self.folder.glob('*.key')},
                         {'C.key', 'W-delivery.key'})
        for profile in PROFILE_SCOPES:
            for suffix in ('-H.key', '-U.key', '-V.key', '-G.key', '-X.key', '-E.key', '-tool.key'):
                self.assertFalse((self.folder / (profile + suffix)).exists())
        self.assertFalse((self.folder / 'W-worker.key').exists())

    def test_the_three_profiles_run_end_to_end_over_the_endpoints(self):
        before = self.service.counts()
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile):
                result = self.service.run_normal(profile)
                self.assertEqual(result['settled']['state'], 'SETTLED')
        after = self.service.counts()
        self.assertEqual(after['accepts'] - before['accepts'], len(PROFILE_SCOPES))
        self.assertEqual(after['settlements'] - before['settlements'], len(PROFILE_SCOPES))

    def test_the_endpoints_are_still_needed_after_initialization(self):
        # A fork rebuilds the whole chain, so it only works while every endpoint
        # keeps serving -- which is exactly the operational requirement.
        profile = 'MED-DEMO-1'
        op = self.trusted.fork_operation(profile)
        verify_chain(self, self.fleet.roster(), profile, op)

    def test_the_workers_certificate_carries_only_the_published_key(self):
        worker = self.fleet.worker()
        claim = self.trusted.worker_certificate['claim']
        self.assertEqual(claim['public_key'], b64(worker.pub))
        self.assertEqual(claim['kid'], worker.kid)

    def test_each_tool_reads_its_own_credential(self):
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile):
                entry = self.fleet.find('tool', profile)
                config = json.loads((self.folder / (profile + '-tool.json')).read_text())
                self.assertEqual(config['tool_key_path'], self.fleet.key_path(entry))
                self.assertFalse((self.folder / (profile + '-tool.key')).exists())

    def test_the_cli_starts_the_trusted_side_from_the_manifest(self):
        import contextlib
        import io

        from competition.cli.app import Session
        session = Session()
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buffer:
                session.cmd_init([str(Path(self.work.name) / 'cli'), str(self.manifest),
                                  str(self.root)])
                session.cmd_use(['PAY-1'])
                session.cmd_auto([])
        finally:
            if session.run is not None:
                session.run.close()
        self.assertIn('SETTLED', buffer.getvalue())
        self.assertEqual({path.name for path in (Path(self.work.name) / 'cli').glob('*.key')},
                         {'C.key', 'W-delivery.key'})


def _serve_process(root, entry):
    """One endpoint as its own process: the client module, serving its socket."""
    argv = [sys.executable, '-m', 'competition.client', '--directory', str(root)]
    if entry.profile is not None:
        argv += ['--profile', entry.profile]
    argv += ['--alias', entry.role, '--serve', '--socket',
             str(Path(root) / key_file_name(entry.profile, entry.role).replace('.key', '.sock'))]
    return subprocess.Popen(argv, cwd=str(Path(__file__).resolve().parents[2]),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _await_socket(path, deadline=30.0):
    limit = time.monotonic() + deadline
    while not path.exists():
        if time.monotonic() > limit:
            raise AssertionError('endpoint socket never appeared: %s' % path)
        time.sleep(0.02)


if __name__ == '__main__':
    unittest.main()
