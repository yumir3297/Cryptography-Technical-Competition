"""The public package: what W registered each endpoint as, checked by the endpoint.

The claims this file pins down:

* the package carries public facts and the records C already signed -- never a
  private key, a ledger or a local path -- and it is assembled from the current,
  certificate-verified records in W, not from anything an endpoint said;
* an endpoint that made its own key can check its own registration from the
  package and its credential alone: the key, the name, the purposes and the
  grants must all be exactly right, and tampering with any of them is refused;
* the two sides of the hand-off are reachable from the command line, in both the
  local fallback and the collected-key mode.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from competition.client.host import answer
from competition.client.keys import generate, propose_purposes, propose_subject
from competition.client.package import check, check_actor, read_package
from competition.client.signer import RoleSigner, load_role_key
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.export import forbidden_secrets
from competition.server.package import KIND, public_package, write_package
from competition.server.roster import ALIASES, Fleet, owner_purposes, read_entry
from competition.support.wire import ProtocolError, b64, canonical, keyid, raw, sortset
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
ROOT = Path(__file__).resolve().parents[2]


def own_key(path):
    """The public facts of the credential an endpoint holds as its own 0600 file."""
    key = load_role_key(path)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return public, keyid(public)


def reject(test, code, call, *args, **kwargs):
    with test.assertRaises(ProtocolError) as caught:
        call(*args, **kwargs)
    test.assertEqual(caught.exception.code, code)


def client_cli(directory, profile, alias, package_path):
    """The client's own ``--check-package``, as every endpoint would run it."""
    argv = [sys.executable, '-m', 'competition.client', '--directory', str(directory)]
    if profile is not None:
        argv += ['--profile', profile]
    argv += ['--alias', alias, '--check-package', str(package_path)]
    return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True)


class PublicPackageTests(unittest.TestCase):
    """One W built the local way, its package, and every endpoint checking itself."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.package = public_package(cls.trusted)
        cls.path = Path(cls.work.name) / 'public-package.json'
        write_package(cls.package, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # -- what is in the package ---------------------------------------------
    def test_the_package_carries_only_public_facts(self):
        self.assertEqual(self.package['kind'], KIND)
        self.assertEqual(forbidden_secrets(self.package), [])
        text = json.dumps(self.package)
        for leak in ('.key', '.sqlite', str(self.work.name)):
            self.assertNotIn(leak, text)

    def test_every_roster_entry_is_a_current_verified_record(self):
        # Assembly goes through ``TrustedState.current``, so a package that exists
        # at all is one whose records and C certificates already verify.
        for profile, roster in self.package['actors'].items():
            self.assertEqual(set(roster), set(ALIASES))
            for alias, entry in roster.items():
                with self.subTest(profile=profile, alias=alias):
                    self.assertEqual(entry['purposes'], owner_purposes(alias))
                    self.assertEqual(entry['key_grant']['record']['value']['kid'], entry['kid'])
                    self.assertTrue(entry['role_grants'])

    def test_every_roster_endpoint_checks_its_own_registration(self):
        for profile, roster in self.trusted.actors.items():
            for alias, actor in roster.items():
                with self.subTest(profile=profile, alias=alias):
                    facts = check(self.package, profile, alias, public=actor.pub, kid=actor.kid,
                                  name=actor.name, purposes=sorted(actor.purposes))
                    self.assertEqual((facts['kid'], facts['name']), (actor.kid, actor.name))

    def test_the_worker_and_every_tool_check_their_own_registration(self):
        claim = self.trusted.worker_certificate['claim']
        worker = check(self.package, None, 'worker',
                       public=raw(claim['public_key'], 32), kid=claim['kid'])
        self.assertEqual(worker['name'], 'competition-worker')
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile):
                value = self.trusted.tools[profile]['certificate']['claim']['record']['value']
                tool = check(self.package, profile, 'tool',
                             public=raw(value['public_key'], 32), kid=value['kid'])
                self.assertEqual(tool['name'], value['issuer'])

    # -- refusals -----------------------------------------------------------
    def test_an_endpoint_that_did_not_make_the_key_is_refused(self):
        line = generate(Path(self.work.name) / 'stranger', 'PAY-1', 'U')
        reject(self, 'PACKAGE_KEY_BINDING', check_actor, self.package, 'PAY-1', 'U',
               public=raw(line['public_key'], 32), kid=line['kid'])

    def test_widened_purposes_are_refused(self):
        actor = self.trusted.actors['PAY-1']['U']
        forged = copy.deepcopy(self.package)
        entry = forged['actors']['PAY-1']['U']
        entry['purposes'] = sortset(list(entry['purposes']) + ['SOURCE'])
        reject(self, 'PACKAGE_PURPOSES', check_actor, forged, 'PAY-1', 'U',
               public=actor.pub, kid=actor.kid)

    def test_a_swapped_key_or_a_swapped_name_is_refused(self):
        actor = self.trusted.actors['IND-DEMO-1']['X']
        other = self.trusted.actors['IND-DEMO-1']['V']
        reject(self, 'PACKAGE_KEY_BINDING', check_actor, self.package, 'IND-DEMO-1', 'X',
               public=other.pub, kid=actor.kid)
        reject(self, 'PACKAGE_SUBJECT', check_actor, self.package, 'IND-DEMO-1', 'X',
               public=actor.pub, kid=actor.kid, name='not-my-name')
        forged = copy.deepcopy(self.package)
        forged['actors']['IND-DEMO-1']['X']['public_key'] = b64(other.pub)
        forged['actors']['IND-DEMO-1']['X']['kid'] = other.kid
        reject(self, 'PACKAGE_GRANT', check_actor, forged, 'IND-DEMO-1', 'X',
               public=other.pub, kid=other.kid)

    def test_a_tampered_certificate_or_record_is_refused(self):
        actor = self.trusted.actors['MED-DEMO-1']['G']
        # A changed claim no longer matches the signature C made over it.
        forged = copy.deepcopy(self.package)
        claim = forged['actors']['MED-DEMO-1']['G']['key_grant']['certificate']['claim']
        claim['record']['value']['subject'] = 'other-g'
        reject(self, 'BAD_SIGNATURE', check_actor, forged, 'MED-DEMO-1', 'G',
               public=actor.pub, kid=actor.kid)

        # A changed record under an untouched certificate is a splice.
        forged = copy.deepcopy(self.package)
        forged['actors']['MED-DEMO-1']['G']['key_grant']['record']['value']['subject'] = 'other-g'
        reject(self, 'PACKAGE_GRANT', check_actor, forged, 'MED-DEMO-1', 'G',
               public=actor.pub, kid=actor.kid)

    def test_another_endpoints_role_grant_cannot_be_passed_off(self):
        actor = self.trusted.actors['PAY-1']['V']
        forged = copy.deepcopy(self.package)
        entry = forged['actors']['PAY-1']['V']
        entry['role_grants'] = copy.deepcopy(self.package['actors']['PAY-1']['U']['role_grants'])
        entry['roles'] = copy.deepcopy(self.package['actors']['PAY-1']['U']['roles'])
        reject(self, 'PACKAGE_GRANT', check_actor, forged, 'PAY-1', 'V',
               public=actor.pub, kid=actor.kid)

    def test_another_root_a_missing_entry_and_a_wrong_role_are_refused(self):
        actor = self.trusted.actors['MED-DEMO-1']['E']
        forged = copy.deepcopy(self.package)
        forged['root_public'] = generate(Path(self.work.name) / 'other-root',
                                        'MED-DEMO-1', 'E')['public_key']
        reject(self, 'BAD_SIGNATURE', check_actor, forged, 'MED-DEMO-1', 'E',
               public=actor.pub, kid=actor.kid)

        forged = copy.deepcopy(self.package)
        del forged['actors']['MED-DEMO-1']['H']
        reject(self, 'PACKAGE_MISSING', check_actor, forged, 'MED-DEMO-1', 'H',
               public=actor.pub, kid=actor.kid)
        reject(self, 'PACKAGE_ROLE', check_actor, self.package, 'MED-DEMO-1', 'C',
               public=actor.pub, kid=actor.kid)

    def test_a_wrong_shape_is_refused(self):
        bad = Path(self.work.name) / 'bad.json'
        bad.write_text(json.dumps({'kind': 'something-else'}), encoding='utf-8')
        reject(self, 'PACKAGE_FORMAT', read_package, bad)
        bad.write_text('not json', encoding='utf-8')
        reject(self, 'PACKAGE_FORMAT', read_package, bad)
        self.assertEqual(read_package(self.path), self.package)

    def test_the_trusted_cli_writes_the_package_the_client_cli_reads(self):
        from competition.cli.app import Session
        session = Session()
        written = Path(self.work.name) / 'cli-package.json'
        try:
            with redirect_stdout(StringIO()):
                session.cmd_init([str(Path(self.work.name) / 'cli')])
                session.cmd_package([str(written)])
                expected = public_package(session.run)
                folder = session.run.folder
        finally:
            if session.run is not None:
                session.run.close()
        self.assertEqual(read_package(written), expected)
        result = client_cli(folder, 'PAY-1', 'G', written)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['check'], 'OK')

    def test_the_client_cli_refuses_a_tampered_package_with_deny(self):
        forged = copy.deepcopy(self.package)
        forged['actors']['PAY-1']['G']['purposes'] = []
        path = Path(self.work.name) / 'forged.json'
        path.write_text(json.dumps(forged), encoding='utf-8')
        result = client_cli(self.trusted.folder, 'PAY-1', 'G', path)
        self.assertEqual(result.returncode, 41)
        self.assertIn('DENY:PACKAGE_PURPOSES', result.stderr)

    def test_every_endpoint_kind_is_reachable_from_the_client_cli(self):
        for profile, alias in (('MED-DEMO-1', 'U'), ('MED-DEMO-1', 'worker'),
                               ('MED-DEMO-1', 'tool')):
            with self.subTest(profile=profile, alias=alias):
                result = client_cli(self.trusted.folder, profile, alias, self.path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['role'], alias)


class _LocalTransport:
    """One endpoint's signing socket, in process: the same ``answer`` the host serves."""

    def __init__(self, folder, profile, role):
        self.signer = RoleSigner.from_directory(folder, profile, role)

    def request(self, message):
        return answer(json.dumps(message, sort_keys=True).encode('utf-8') + b'\n', self.signer)


class CollectedKeyPackageTests(unittest.TestCase):
    """The endpoints made the keys; W sends back what it registered them as."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.endpoints = Path(cls.work.name) / 'endpoints'
        lines = [generate(cls.endpoints, profile, role)
                 for profile in PROFILE_SCOPES for role in ALIASES]
        lines.append(generate(cls.endpoints, None, 'worker'))
        lines += [generate(cls.endpoints, profile, 'tool') for profile in PROFILE_SCOPES]
        fleet = Fleet([read_entry(line) for line in lines], cls.endpoints,
                      lambda entry: _LocalTransport(cls.endpoints, entry.profile, entry.role))
        cls.trusted = initialize(Path(cls.work.name) / 'w', fleet=fleet)
        cls.package = public_package(cls.trusted)
        cls.path = Path(cls.work.name) / 'public-package.json'
        write_package(cls.package, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_no_role_key_was_written_but_the_package_still_verifies(self):
        self.assertEqual({path.name for path in Path(self.trusted.folder).glob('*.key')},
                         {'C.key', 'W-delivery.key'})
        self.assertEqual(forbidden_secrets(self.package), [])

    def test_each_endpoint_checks_itself_from_the_key_it_made(self):
        for profile in PROFILE_SCOPES:
            for alias in ALIASES:
                with self.subTest(profile=profile, alias=alias):
                    public, kid = own_key(self.endpoints / (profile + '-' + alias + '.key'))
                    facts = check(self.package, profile, alias, public=public, kid=kid,
                                  name=propose_subject(profile, alias),
                                  purposes=propose_purposes(alias))
                    self.assertEqual(facts['kid'], kid)

    def test_the_worker_and_the_tools_check_the_key_files_they_made(self):
        public, kid = own_key(self.endpoints / 'W-worker.key')
        self.assertEqual(check(self.package, None, 'worker', public=public, kid=kid)['name'],
                         'competition-worker')
        for profile in PROFILE_SCOPES:
            with self.subTest(profile=profile):
                public, kid = own_key(self.endpoints / (profile + '-tool.key'))
                self.assertEqual(check(self.package, profile, 'tool',
                                       public=public, kid=kid)['kid'], kid)

    def test_the_client_cli_checks_an_endpoint_from_the_endpoint_directory(self):
        for profile, alias in (('IND-DEMO-1', 'H'), (None, 'worker'), ('IND-DEMO-1', 'tool')):
            with self.subTest(profile=profile, alias=alias):
                result = client_cli(self.endpoints, profile, alias, self.path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['check'], 'OK')


if __name__ == '__main__':
    unittest.main()
