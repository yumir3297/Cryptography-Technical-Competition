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
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from competition.deploy import expected_manifest, places, serves
from competition.deploy import endpoints, trusted, up
from competition.server.roster import endpoint_port, read_entry, read_manifest
from competition.support.wire import ProtocolError
from competition.tests.helpers import caller_of, make_callers, public_of

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)

# A stand-in ``docker``: it records what it was asked for and answers the few
# questions the start script reads back.  No daemon, no containers, no network.
FAKE_DOCKER = '''#!%s
import os, sys
args = sys.argv[1:]
with open(os.environ['ZJJ_FAKE_CALLS'], 'a') as log:
    log.write(' '.join(args) + '\\n')

def answer(text=''):
    if text:
        print(text)
    sys.exit(0)

if args[:1] == ['info']:
    sys.exit(1 if os.environ.get('ZJJ_FAKE_INFO_FAIL') else 0)

# The harness: by default it is neither up nor pulled, so the script goes and
# pulls the image and runs it.  Two switches show the two other answers.
if args[:1] == ['ps']:
    answer('stub-harness' if os.environ.get('ZJJ_FAKE_HARNESS_UP') else '')
if args[:1] == ['images']:
    answer('stub-image' if os.environ.get('ZJJ_FAKE_HARNESS_IMAGE') else '')
if args[:1] == ['logs']:
    answer('dsh web: http://127.0.0.1:3079/?token=stub')

if args[:2] == ['inspect', '-f']:
    answer(os.environ.get('ZJJ_FAKE_CALLER_EXIT', '0') if 'ExitCode' in args[2] else 'exited')

if args[:1] == ['compose']:
    if 'logs' in args:
        answer('a line from the stubbed service')
    if 'ps' in args:
        answer('stub-container')

answer()
'''


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


class OrchestrationTests(unittest.TestCase):
    """The start script's own logic, with the daemon's answers stubbed.

    A stand-in ``docker`` on the path is the only way to check what the script
    asks for without a daemon, and what it asks for is the whole of the script:
    which commands, in which order, and what it says when something refuses.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)
        binary = Path(self.folder.name) / 'bin'
        binary.mkdir()
        shim = binary / 'docker'
        shim.write_text(FAKE_DOCKER % sys.executable, encoding='utf-8')
        shim.chmod(0o755)
        self.log = Path(self.folder.name) / 'calls'
        self.env = {'PATH': '%s:%s' % (binary, os.environ['PATH']),
                    'ZJJ_FAKE_CALLS': str(self.log)}

    def run_up(self, *argv, **environment):
        with mock.patch.dict(os.environ, {**self.env, **environment}), \
                mock.patch.object(up, 'harness_ready', return_value=True), \
                mock.patch.object(up, 'open_page', return_value=False), \
                redirect_stdout(StringIO()):
            return up.main(['--timeout', '5', *argv])

    def calls(self):
        return self.log.read_text(encoding='utf-8').splitlines() if self.log.exists() else []

    def test_a_good_run_starts_the_stack_and_watches_the_flow(self):
        self.assertEqual(self.run_up(), 0)
        calls = self.calls()
        self.assertTrue(any(call.endswith('build') for call in calls))
        self.assertTrue(any('up -d' in call for call in calls))
        for service in up.DEMO:
            self.assertTrue(any('ps --all -q %s' % service in call for call in calls))
            self.assertTrue(any('logs --no-log-prefix %s' % service in call for call in calls))

    def test_it_leaves_the_stack_up_unless_asked_to_stop(self):
        self.run_up()
        self.assertFalse([call for call in self.calls() if 'down' in call])
        self.run_up('--down')
        self.assertTrue([call for call in self.calls() if 'down -v' in call])

    def test_fresh_drops_the_previous_volumes_before_building(self):
        self.run_up('--fresh', '--no-build')
        calls = self.calls()
        self.assertLess(next(i for i, call in enumerate(calls) if 'down -v' in call),
                        next(i for i, call in enumerate(calls) if 'up -d' in call))
        self.assertFalse([call for call in calls if call.endswith('build')])

    def test_a_side_that_fails_is_reported_with_the_way_out(self):
        buffer = StringIO()
        with redirect_stderr(buffer):
            code = self.run_up(ZJJ_FAKE_CALLER_EXIT='1')
        self.assertEqual(code, 1)
        self.assertIn('--fresh', buffer.getvalue())

    def test_a_daemon_that_does_not_answer_says_what_to_do_instead(self):
        buffer = StringIO()
        with redirect_stderr(buffer):
            code = self.run_up(ZJJ_FAKE_INFO_FAIL='1')
        self.assertEqual(code, 1)
        self.assertIn('--local', buffer.getvalue())

    def test_the_workbench_is_brought_up_beside_the_deployment(self):
        self.assertEqual(self.run_up(), 0)
        calls = self.calls()
        self.assertTrue(any('pull %s' % up.HARNESS_IMAGE in call for call in calls))
        self.assertTrue(any('run -d --name %s' % up.HARNESS_NAME in call for call in calls))
        # 只对宿主机的回环开放，而不是对局域网。
        door = '127.0.0.1:%d:%d' % (up.HARNESS_PORT, up.HARNESS_PORT)
        self.assertTrue(any(door in call for call in calls))
        # 数据卷挂上去，否则配置和会话在容器重建时会跟着走。
        self.assertTrue(any('%s:/root/.dsh' % up.HARNESS_HOME in call for call in calls))

    def test_a_workbench_that_is_already_up_is_not_started_twice(self):
        self.run_up(ZJJ_FAKE_HARNESS_UP='1')
        self.assertFalse([call for call in self.calls() if 'run -d' in call
                          or 'pull' in call])

    def test_an_image_that_is_already_here_is_not_pulled_again(self):
        self.run_up(ZJJ_FAKE_HARNESS_IMAGE='1')
        calls = self.calls()
        self.assertFalse([call for call in calls if call.startswith('pull')])
        self.assertTrue(any('run -d' in call for call in calls))

    def test_the_workbench_can_be_left_out_entirely(self):
        self.assertEqual(self.run_up('--no-deepseek'), 0)
        self.assertFalse([call for call in self.calls()
                          if up.HARNESS_NAME in call or 'pull' in call])

    def test_stopping_takes_the_workbench_container_but_not_its_volume(self):
        self.run_up('--down')
        calls = self.calls()
        self.assertIn('rm -f %s' % up.HARNESS_NAME, calls)
        self.assertFalse([call for call in calls if 'volume' in call])

    def test_a_desktop_is_only_asked_when_there_is_one(self):
        headless = {name: value for name, value in os.environ.items()
                    if name not in ('DISPLAY', 'WAYLAND_DISPLAY')}
        with mock.patch.dict(os.environ, headless, clear=True):
            self.assertFalse(up.open_page('http://127.0.0.1:3080/'))


if __name__ == '__main__':
    unittest.main()
