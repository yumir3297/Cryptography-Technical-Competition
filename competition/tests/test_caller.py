"""Two callers, nineteen endpoints and one entry: the flow a deployment runs.

Four claims:

* a caller's credential is its own -- written exclusively as ``0600``, never
  replaced, and announced as one allowlist line the deployment collects the same
  way it collects the endpoint roster;
* a caller walks a flow without ever holding a role key: it asks the entry, the
  *endpoint* signs, and it hands the proof back.  Two callers on two sides drive
  one operation to a settled state, and the entry's own caller list is what keeps
  each of them on its side;
* the caller checks what an endpoint returned before forwarding it, against the
  key the published package says the roster bound to that place, so a wrong
  answer stops at the caller rather than travelling on;
* the caller's own credential is all it needs to open a session -- no role key,
  no shared secret, and no route that would sign anything for it.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from competition.caller import generate, key_file_name
from competition.caller.flow import Caller, EndpointSigner
from competition.client.signer import RoleSigner
from competition.client.web import make_app as endpoint_app
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.server.roster import ALIASES, endpoint_port
from competition.server.service import TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import ProtocolError, b64, canonical, require
from competition.tests.helpers import Face, free_port
from competition.web.app import make_app as entry_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)
ROOT = Path(__file__).resolve().parents[2]
SIGN_CALL = 'COMP-APP-SIGN-CALL-v1'


class _Reply:
    """One canned endpoint answer, so a check can be tested without an endpoint."""

    def __init__(self, reply):
        self.reply = reply

    def request(self, message):
        return self.reply


def transport_returning(reply):
    return lambda url: _Reply(reply)


class CallerKeyTests(unittest.TestCase):
    """A caller's credential is its own, and announced like every other public key."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.folder.cleanup)

    def test_the_key_is_its_own_0600_credential_and_the_line_is_public_only(self):
        line = generate(self.folder.name, 'caller-h', ['H'])
        path = Path(self.folder.name) / key_file_name('caller-h')
        self.assertEqual(path.name, 'caller-h.key')
        status = path.stat()
        self.assertEqual((status.st_uid, status.st_mode & 0o777), (os.geteuid(), 0o600))
        self.assertEqual(len(path.read_bytes()), 32)
        self.assertEqual(set(line), {'name', 'public_key', 'sides'})
        self.assertEqual(line['name'], 'caller-h')
        self.assertEqual(line['sides'], ['H'])

    def test_it_refuses_to_replace_an_existing_credential(self):
        generate(self.folder.name, 'caller-h', ['H'])
        with self.assertRaises(FileExistsError):
            generate(self.folder.name, 'caller-h', ['H'])

    def test_a_bad_name_or_side_is_refused(self):
        for name, sides, code in (('a b', ['H'], 'CALLER_NAME'),
                                  ('caller-h', [], 'SESSION_SIDES'),
                                  ('caller-h', ['C'], 'SESSION_SIDES'),
                                  ('caller-h', ['H', 'H'], 'SESSION_SIDES')):
            with self.subTest(name=name, sides=sides):
                with self.assertRaises(ProtocolError) as caught:
                    generate(self.folder.name, name, sides)
                self.assertEqual(caught.exception.code, code)

    def test_the_command_line_prints_one_allowlist_line(self):
        result = subprocess.run(
            [sys.executable, '-m', 'competition.caller', '--directory', self.folder.name,
             '--keygen', '--name', 'caller-worker', '--sides', 'worker'],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = json.loads(result.stdout)
        self.assertEqual((line['name'], line['sides']), ('caller-worker', ['worker']))
        self.assertEqual(len(line['public_key']), 43)
        self.assertIn('key:', result.stderr)


class CallerFlowTests(unittest.TestCase):
    """Two callers on two sides drive one operation, with every signature elsewhere."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.faces = []
        try:
            for profile in sorted(PROFILE_SCOPES):
                for role in ALIASES:
                    signer = RoleSigner.from_directory(cls.trusted.folder, profile, role)
                    cls.faces.append(Face(endpoint_app(signer),
                                          port=endpoint_port(profile, role)))
            cls.faces.append(Face(endpoint_app(
                RoleSigner.from_directory(cls.trusted.folder, None, 'worker')),
                port=endpoint_port(None, 'worker')))
            cls.callers = Path(cls.work.name) / 'callers'
            lines = [generate(cls.callers, 'caller-h', ['H']),
                     generate(cls.callers, 'caller-worker', ['worker'])]
            cls.callers_path = cls.callers / 'callers.jsonl'
            cls.callers_path.write_text(
                ''.join(json.dumps(line) + '\n' for line in lines), encoding='utf-8')
            cls.entry = Face(entry_app(
                TrustedService(cls.trusted, LocalSigner(cls.trusted)),
                Sessions(read_callers(cls.callers_path))))
        except BaseException:
            for face in cls.faces:
                face.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.entry.close()
        for face in cls.faces:
            face.close()
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def caller(self, name):
        """One started caller, with the entry and the endpoints it needs."""
        caller = Caller(self.entry.base, self.callers / (name + '.key'), 'http://127.0.0.1')
        caller.start()
        return caller

    def test_the_two_sides_drive_one_operation_to_settled(self):
        holder = self.caller('caller-h')
        submitted = holder.submit('PAY-1', None)
        operation_id = submitted['operation_id']
        self.assertIn('challenge', submitted)
        for step in ('prepare', 'accept'):
            with self.subTest(step=step):
                self.assertEqual(holder.step(operation_id, step)['operation_id'], operation_id)
        executor = self.caller('caller-worker')
        self.assertEqual(executor.step(operation_id, 'claim')['operation_id'], operation_id)
        # A tool response has its own shape and no operation id; the settle that
        # follows is what says the attempt actually finished.
        self.assertIsInstance(executor.step(operation_id, 'exec'), dict)
        settled = executor.step(operation_id, 'settle')
        self.assertEqual(settled['state'], 'SETTLED')
        view = holder.step(operation_id, 'status')
        self.assertEqual(view['acceptance_state'], 'COMMITTED')
        self.assertTrue(view['exec_consumed'])

    def test_a_caller_is_kept_on_the_side_it_was_listed_for(self):
        holder, executor = self.caller('caller-h'), self.caller('caller-worker')
        operation_id = holder.submit('PAY-1', None)['operation_id']
        for caller, step in ((holder, 'exec'), (executor, 'accept')):
            with self.subTest(step=step):
                with self.assertRaises(ProtocolError) as caught:
                    caller.step(operation_id, step)
                self.assertEqual(caught.exception.code, 'SESSION_SIDE')
        with self.assertRaises(ProtocolError) as caught:
            executor.submit('PAY-1', None)
        self.assertEqual(caught.exception.code, 'SESSION_SIDE')

    def test_a_caller_holds_no_role_key_and_signs_nothing_for_itself(self):
        # The only private material this process has is its own session key; the
        # proof it forwards was produced by the endpoint that owns the step.
        holder = self.caller('caller-h')
        self.assertEqual(sorted(p.name for p in self.callers.glob('*.key')),
                         ['caller-h.key', 'caller-worker.key'])
        operation_id = holder.submit('PAY-1', None)['operation_id']
        asked = holder.challenge(operation_id, 'prepare')
        self.assertEqual(asked['role'], 'H')
        self.assertEqual(asked['profile'], 'PAY-1')
        proof = holder.signers().proof('PAY-1', 'H', asked['domain'], asked['claim'])
        actor = self.trusted.actors['PAY-1']['H']
        from competition.support.wire import raw, strict_verify
        strict_verify(actor.pub, raw(proof['signature'], 64),
                      canonical([asked['domain'], asked['claim']]))

    # -- what the caller checks before it forwards -------------------------
    def test_a_signature_from_the_wrong_key_is_refused_here(self):
        holder = self.caller('caller-h')
        claim, domain = {'profile': 'PAY-1'}, SIGN_CALL
        wrong = self.trusted.actors['PAY-1']['V'].key
        reply = {'signature': b64(wrong.sign(canonical([domain, claim]))), 'profile': 'PAY-1',
                 'role': 'U', 'domain': domain, 'kid': 'x', 'pid': 1, 'euid': 1}
        signer = EndpointSigner('http://127.0.0.1', holder.package,
                                transport=transport_returning(reply))
        with self.assertRaises(ProtocolError) as caught:
            signer.proof('PAY-1', 'U', domain, claim)
        self.assertEqual(caught.exception.code, 'BAD_SIGNATURE')

    def test_an_answer_about_another_step_is_refused_here(self):
        holder = self.caller('caller-h')
        for reply in ({'signature': b64(bytes(64)), 'role': 'V', 'domain': SIGN_CALL},
                      {'signature': b64(bytes(64)), 'role': 'U', 'domain': 'ZJJ-SIG-v1'},
                      {'role': 'U', 'domain': SIGN_CALL}):
            with self.subTest(reply=sorted(reply)):
                signer = EndpointSigner('http://127.0.0.1', holder.package,
                                        transport=transport_returning(reply))
                with self.assertRaises(ProtocolError) as caught:
                    signer.proof('PAY-1', 'U', SIGN_CALL, {})
                self.assertEqual(caught.exception.code, 'CALLER_ANSWER')

    def test_a_step_without_an_endpoint_base_is_refused(self):
        holder = Caller(self.entry.base, self.callers / 'caller-h.key')
        holder.start()
        operation_id = holder.submit('PAY-1', None)['operation_id']
        with self.assertRaises(ProtocolError) as caught:
            holder.step(operation_id, 'prepare')
        self.assertEqual(caught.exception.code, 'CALLER_ENDPOINTS')


if __name__ == '__main__':
    unittest.main()
