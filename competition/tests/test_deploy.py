"""The deployment: what each service runs, and that it need not wait for the others.

Three claims:

* the deployment's own vocabulary is the repository's -- which endpoints exist,
  which of them have a face, and how many lines a complete manifest has;
* each entry point builds the command it says it does: an endpoint on the port its
  roster place implies, the worker without a profile, and the tool never served at
  all, because the trusted side runs it as a child process;
* starting up is idempotent where it has to be: an endpoint that already has a
  credential is announced from that key rather than given a second one, and the
  trusted entry serves before its callers exist rather than waiting for them.
"""
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from competition.deploy import expected_manifest, places, serves
from competition.deploy import endpoints, trusted
from competition.server.roster import endpoint_port, read_entry, read_manifest
from competition.support.wire import ProtocolError
from competition.tests.helpers import caller_of, make_callers, public_of

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)


class SupervisorTests(unittest.TestCase):
    """A supervisor that walks away leaves its children holding the ports."""

    def children(self, count=3, argv=None):
        argv = argv or [sys.executable, '-c', 'import time; time.sleep(60)']
        return [subprocess.Popen(argv) for _ in range(count)]

    def test_being_asked_to_stop_reaps_every_child(self):
        children = self.children()
        stopping = threading.Event()
        threading.Timer(0.3, stopping.set).start()
        self.assertEqual(endpoints.supervise(children, stopping), 0)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_a_child_that_dies_first_stops_the_rest(self):
        children = self.children(argv=[sys.executable, '-c', 'raise SystemExit(3)'])
        self.assertEqual(endpoints.supervise(children, threading.Event()), 1)
        self.assertTrue(all(child.poll() is not None for child in children))


class PlacesTests(unittest.TestCase):
    """Who is in the deployment, and which of them listens."""

    def test_nineteen_sign_and_three_are_only_credentials(self):
        every = list(places())
        served = [(profile, role) for profile, role in every if serves(role)]
        self.assertEqual(len(every), 22)
        self.assertEqual(len(served), 19)
        self.assertEqual([role for _, role in every if not serves(role)], ['tool'] * 3)
        ports = {endpoint_port(profile, role) for profile, role in served}
        self.assertEqual(len(ports), 19)
        self.assertEqual(expected_manifest(), len(every))

    def test_the_worker_is_one_capability_and_the_tools_are_per_profile(self):
        self.assertIn((None, 'worker'), places())
        self.assertEqual([profile for profile, role in places() if role == 'worker'], [None])
        self.assertEqual(len([1 for _, role in places() if role == 'tool']), 3)


class EndpointCommandTests(unittest.TestCase):
    """Each endpoint is started as its own process, on the port it implies."""

    def test_an_alias_is_served_with_its_profile_and_its_port(self):
        argv = endpoints.serve_argv('PAY-1', 'U')
        self.assertEqual(argv[:4], [argv[0], '-m', 'competition.client', '--directory'])
        self.assertIn('--serve-http', argv)
        self.assertEqual(argv[argv.index('--profile') + 1], 'PAY-1')
        self.assertEqual(argv[argv.index('--alias') + 1], 'U')
        self.assertEqual(argv[argv.index('--port') + 1], str(endpoint_port('PAY-1', 'U')))

    def test_the_worker_is_served_without_a_profile(self):
        argv = endpoints.serve_argv(None, 'worker')
        self.assertNotIn('--profile', argv)
        self.assertEqual(argv[argv.index('--alias') + 1], 'worker')
        self.assertEqual(argv[argv.index('--port') + 1], str(endpoint_port(None, 'worker')))


class ManifestTests(unittest.TestCase):
    """The manifest is public, complete, and rebuilt rather than duplicated."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)

    def test_announcing_twice_finds_the_same_credential(self):
        with mock.patch.object(endpoints, 'DIRECTORY', self.directory):
            first = endpoints.announce('PAY-1', 'U')
            second = endpoints.announce('PAY-1', 'U')
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.directory.glob('*.key'))), 1)
        self.assertEqual(set(first), {'profile', 'role', 'subject', 'public_key', 'kid',
                                      'purposes'})

    def test_the_manifest_is_published_whole_and_reads_back(self):
        with mock.patch.object(endpoints, 'DIRECTORY', self.directory), \
                mock.patch.object(endpoints, 'MANIFEST', self.directory / 'roster.jsonl'):
            lines = [endpoints.announce(profile, role) for profile, role in places()]
            path = endpoints.write_manifest(lines)
        self.assertFalse((self.directory / 'roster.jsonl.pending').exists())
        entries = read_manifest(path)
        self.assertEqual(len(entries), expected_manifest())
        self.assertEqual([read_entry(line) for line in lines], entries)


class StartupOrderTests(unittest.TestCase):
    """The entry serves before its callers exist, and accepts one that arrives later."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'callers.jsonl'

    def test_the_entry_is_usable_before_the_caller_list_is_written(self):
        sessions = trusted.sessions_for(self.path)
        with self.assertRaises(ProtocolError) as caught:
            sessions.challenge('nobody')
        self.assertEqual(caught.exception.code, 'SESSION_CALLER')

    def test_a_caller_added_to_a_running_entry_can_open_a_session_anyway(self):
        sessions = trusted.sessions_for(self.path)
        path, keys = make_callers(self.folder.name, [('caller-h', ['H'])])
        self.assertEqual(path, self.path)
        caller = caller_of(keys['caller-h'])
        claim = sessions.challenge(caller['kid'])
        opened = sessions.open(claim, caller['sign'](claim))
        self.assertEqual(opened['caller'], 'caller-h')
        self.assertEqual(sessions.authorize(opened['token'], 'H')['name'], 'caller-h')
        self.assertEqual(public_of(keys['caller-h']), sessions.callers[caller['kid']]['pub'])


if __name__ == '__main__':
    unittest.main()
