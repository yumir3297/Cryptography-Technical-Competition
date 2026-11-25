"""The observation face's live mode: one auditor caller, reads forwarded.

The page is still static and still reads through ``/api/diag/*``.  What live
mode changes is where those reads go: to the entry a deployment is running,
with a session the service opened for itself.  These tests cover the two pieces
that are easy to get wrong -- the caller line it writes into a shared list, and
the forwarding route -- without starting an entry.
"""
import json
import stat
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from competition.deploy.observe import RemoteAuditor, live_app, write_token
from competition.web.session import read_callers


class AuditorLineTest(unittest.TestCase):
    def test_line_is_a_valid_auditor_and_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            callers = root / 'callers' / 'callers.jsonl'
            first = RemoteAuditor('http://127.0.0.1:1', callers)
            first.load(root / 'work')

            read = read_callers(callers)
            self.assertEqual(len(read), 1)
            caller = next(iter(read.values()))
            self.assertEqual(caller['sides'], ('auditor',))
            self.assertEqual(caller['kid'], first.kid)

            # A restart with the same work folder keeps the same key and does
            # not add a second line with the same name (the list refuses dups).
            second = RemoteAuditor('http://127.0.0.1:1', callers)
            second.load(root / 'work')
            self.assertEqual(second.kid, first.kid)
            self.assertEqual(len(read_callers(callers)), 1)
            self.assertEqual(len(callers.read_text(encoding='utf-8').splitlines()), 1)

    def test_a_different_work_folder_gets_its_own_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            callers = root / 'callers' / 'callers.jsonl'
            for name in ('a', 'b'):
                RemoteAuditor('http://127.0.0.1:1', callers).load(root / name)
            self.assertEqual(len(read_callers(callers)), 2)


class TokenFileTest(unittest.TestCase):
    def test_the_start_script_gets_the_live_token_privately(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / 'work'
            write_token(work, 'first-token')
            path = work / 'token'
            self.assertEqual(path.read_text(encoding='utf-8'), 'first-token')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            # A re-minted session replaces the file rather than appending, and
            # the published credential is the newest one.
            write_token(work, 'second-token')
            self.assertEqual(path.read_text(encoding='utf-8'), 'second-token')
            self.assertFalse((work / 'token.tmp').exists())


class _Stub:
    token = 'stub-token'

    def __init__(self):
        self.paths = []

    def ensure(self):
        return self.token

    def get(self, path, token):
        self.paths.append((path, token))
        return 200, 'application/json', json.dumps({'data': {'path': path}}).encode()


class LiveAppTest(unittest.TestCase):
    def test_token_and_reads_are_forwarded(self):
        stub = _Stub()
        client = TestClient(live_app(stub))

        self.assertEqual(client.get('/api/observe/demo-token').json(),
                         {'token': 'stub-token'})
        reply = client.get('/api/diag/entry?x=1',
                           headers={'authorization': 'Bearer page-token'})
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()['data']['path'], '/api/diag/entry?x=1')
        self.assertEqual(stub.paths[-1], ('/api/diag/entry?x=1', 'page-token'))
        self.assertEqual(client.get('/healthz').json(), {'ok': True})
        # Missing credential is refused here, not silently replaced by ours.
        self.assertEqual(client.get('/api/diag/entry').status_code, 401)

    def test_an_entry_that_is_down_is_a_gateway_error(self):
        class Down(_Stub):
            def get(self, path, token):
                raise OSError('down')

        client = TestClient(live_app(Down()))
        self.assertEqual(client.get('/api/diag/entry',
                                   headers={'authorization': 'Bearer t'}).status_code, 502)


if __name__ == '__main__':
    unittest.main()
