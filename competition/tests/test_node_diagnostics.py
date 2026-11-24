"""The read-only diagnostic face: 27 routes behind the ``auditor`` session side.

The routes are flat projections of the committed W, one URL per node.  They are
not protocol messages and not evidence: the only thing they may do is read.  So
this file holds the face to seven claims:

* a route with no bearer token is a missing session (``SESSION_REQUIRED``);
* a live session that is not an ``auditor`` -- ``H`` or ``observer`` -- is the
  wrong side (``SESSION_SIDE``), because reading is not the same permission as
  driving a step or watching the feed;
* an ``auditor`` session reads every route, on a real committed operation;
* reading twice changes no counter: ``a_journal``, ``w_nonce``,
  ``comp_event_clock``, ``a_observe_event`` and ``w_evidence`` stay exactly as
  they were;
* the projections carry no nonce value, no ``private_key``, no ``session_id``
  and no private key wearing a ``signature`` name -- refs, public keys and the
  protocol's public signatures are allowed, secret material is not;
* an operation id that was never committed is answered (``OPERATION_UNKNOWN``),
  not turned into a 500;
* a table name outside the whitelist is refused by name (``DIAG_TABLE``).

The auditor session is opened for real: the caller answers a ``/session``
challenge with its own key on ``/session/prove``, exactly as a deployment does.
"""
import base64
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from competition.profiles.w_seed import initialize
from competition.server.signer import LocalSigner
from competition.server.service import TrustedService
from competition.tests.helpers import Face, body, caller_of, make_callers
from competition.web.app import make_app
from competition.web.session import Sessions, read_callers

TEMP_ROOT = Path(__file__).resolve().parents[3] / 'tmp'
TEMP_ROOT.mkdir(exist_ok=True)

# Counters the diagnostic face must never change.  They cover all three ledgers
# the face reads: authorization (journal, clock), nonces, observation, evidence.
FROZEN_TABLES = ('a_journal', 'w_nonce', 'comp_event_clock',
                 'a_observe_event', 'w_evidence')

# The seven routes that name no operation; the table read is included here so the
# 27-path sweep uses the whitelisted ``w_operation`` rather than a bad name.
STATIC_ROUTES = (
    '/api/diag/entry',
    '/api/diag/observe',
    '/api/diag/registry',
    '/api/diag/db/w_operation',
    '/api/diag/clock',
    '/api/diag/endpoints',
    '/api/diag/store',
)

# The nineteen routes that project one operation.
OPERATION_ROUTES = (
    '/api/diag/guard',
    '/api/diag/plan',
    '/api/diag/goal',
    '/api/diag/accept',
    '/api/diag/commit',
    '/api/diag/receipt',
    '/api/diag/deny',
    '/api/diag/identity',
    '/api/diag/challenge',
    '/api/diag/claim',
    '/api/diag/exec',
    '/api/diag/final',
    '/api/diag/settlement',
    '/api/diag/cancel',
    '/api/diag/query',
    '/api/diag/tool',
    '/api/diag/result',
    '/api/diag/construct',
    '/api/diag/source',
)

# The one route that names a profile rather than an operation.
PROFILE_ROUTES = (
    '/api/diag/obligations/PAY-1',
)

# An id no committed operation can hold; the routes must answer it, not crash.
UNKNOWN_OID = 'never-committed-operation'


def _private_key_shaped(value):
    """A raw 32-byte Ed25519 key, base64url-encoded, is 43 characters."""
    if type(value) is not str or len(value) != 43:
        return False
    try:
        return len(base64.urlsafe_b64decode(value + '=')) == 32
    except Exception:
        return False


def _signature_leaks(value, where='$'):
    """Fields that hold private key material under the name ``signature``.

    A protocol signature is 64 bytes (86 base64url characters) and is public;
    a 32-byte private key under that name is the leak this looks for.
    """
    bad = []
    if isinstance(value, dict):
        for name, item in value.items():
            path = '%s.%s' % (where, name)
            if name == 'signature' and _private_key_shaped(item):
                bad.append(path)
            bad.extend(_signature_leaks(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            bad.extend(_signature_leaks(item, '%s[%d]' % (where, index)))
    return bad


class DiagnosticEntryTests(unittest.TestCase):
    """One initialized W, one committed PAY-1 operation, three caller keys."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.env = {k: os.environ.get(k) for k in ('TMP', 'TEMP')}
        os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
        cls.trusted = initialize(Path(cls.work.name) / 'w')
        cls.service = TrustedService(cls.trusted, LocalSigner(cls.trusted))
        # A real settled operation, so every projection has something to read.
        cls.committed = cls.service.run_normal('PAY-1')
        cls.oid = cls.committed['operation_id']
        cls.callers_path, cls.callers = make_callers(
            Path(cls.work.name) / 'callers',
            [('caller-h', ['H']),
             ('caller-observer', ['observer']),
             ('caller-auditor', ['auditor'])])
        cls.sessions = Sessions(read_callers(cls.callers_path))
        cls.face = Face(make_app(cls.service, cls.sessions))
        cls.nonces = cls._nonces()

    @classmethod
    def tearDownClass(cls):
        cls.face.close()
        cls.trusted.close()
        cls.work.cleanup()
        for name, value in cls.env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # -- fixture reads ------------------------------------------------------
    @classmethod
    def _read(cls):
        """One read-only connection, the same rule the diagnostics follow."""
        c = sqlite3.connect('file:%s?mode=ro' % Path(cls.trusted.store.path).resolve(),
                            uri=True, timeout=5)
        c.execute('PRAGMA query_only=ON')
        return c

    @classmethod
    def _nonces(cls):
        with closing(cls._read()) as c:
            return [row[0] for row in c.execute('SELECT nonce FROM w_nonce')]

    @classmethod
    def counts(cls):
        with closing(cls._read()) as c:
            return {table: c.execute('SELECT COUNT(*) FROM %s' % table).fetchone()[0]
                    for table in FROZEN_TABLES}

    def session(self, name):
        """One live token, opened the way a caller opens one: challenge, proof."""
        caller = caller_of(self.callers[name])
        reply = self.face.post('/session', body(kid=caller['kid']))
        self.assertEqual(reply.status_code, 200, reply.text)
        challenge = reply.json()['challenge']
        opened = self.face.post('/session/prove',
                                body(claim=challenge, signature=caller['sign'](challenge)))
        self.assertEqual(opened.status_code, 200, opened.text)
        return opened.json()['token']

    def get(self, path, token=None):
        headers = None if token is None else {'authorization': 'Bearer ' + token}
        return self.face.get(path, headers)

    def routes(self):
        """The 27 paths, with the real operation substituted where one is named."""
        return (list(STATIC_ROUTES)
                + [prefix + '/' + self.oid for prefix in OPERATION_ROUTES]
                + list(PROFILE_ROUTES))

    # -- 1. authentication --------------------------------------------------
    def test_every_route_needs_a_session(self):
        for path in self.routes():
            with self.subTest(path=path):
                reply = self.get(path)
                self.assertEqual(reply.status_code, 401, reply.text)
                self.assertEqual(reply.json(), {'deny': 'SESSION_REQUIRED'})

    # -- 2. authorization ---------------------------------------------------
    def test_h_and_observer_sessions_are_not_auditors(self):
        tokens = (('H', self.session('caller-h')),
                  ('observer', self.session('caller-observer')))
        for side, token in tokens:
            for path in self.routes():
                with self.subTest(side=side, path=path):
                    reply = self.get(path, token)
                    self.assertEqual(reply.status_code, 403, reply.text)
                    self.assertEqual(reply.json(), {'deny': 'SESSION_SIDE'})

    # -- 3. the auditor reads every route -----------------------------------
    def test_an_auditor_reads_every_route(self):
        token = self.session('caller-auditor')
        for path in self.routes():
            with self.subTest(path=path):
                reply = self.get(path, token)
                self.assertEqual(reply.status_code, 200, reply.text)
                payload = reply.json()
                self.assertIsInstance(payload, dict)
                # Where the projection uses the shared envelope, it must say
                # what it is: a view, unsigned, and not evidence.
                if 'view_kind' in payload:
                    self.assertEqual(payload['view_kind'], 'DIAGNOSTIC_PROJECTION')
                if 'signed' in payload:
                    self.assertIs(payload['signed'], False)
                if 'not_evidence' in payload:
                    self.assertIs(payload['not_evidence'], True)

    # -- 3b. the new routes project their documented fields -----------------
    def _data(self, path, token):
        """The projection's ``data`` object; the envelope is tested elsewhere."""
        reply = self.get(path, token)
        self.assertEqual(reply.status_code, 200, reply.text)
        payload = reply.json()
        self.assertIsInstance(payload, dict)
        data = payload.get('data')
        self.assertIsInstance(data, dict)
        return data

    def test_new_endpoints_return_their_contract(self):
        token = self.session('caller-auditor')
        cases = (
            ('/api/diag/store', ('shared', 'tool', 'transaction')),
            ('/api/diag/construct/' + self.oid,
             ('action_hash', 'selector', 'basis', 'assessment', 'deps')),
            ('/api/diag/source/' + self.oid, ('source_deps', 'sources')),
            ('/api/diag/obligations/PAY-1', ('goals', 'resources', 'reservations')),
        )
        for path, fields in cases:
            with self.subTest(path=path):
                data = self._data(path, token)
                self.assertEqual([name for name in fields if name not in data], [], data)

    def test_extended_fields_are_present(self):
        token = self.session('caller-auditor')
        cases = (
            ('/api/diag/entry', ('entry_kinds',)),
            ('/api/diag/guard/' + self.oid, ('scope', 'observed_stages')),
            ('/api/diag/accept/' + self.oid, ('claim_blocked',)),
            ('/api/diag/exec/' + self.oid,
             ('exec_consumed', 'replay_blocked', 'halted')),
            ('/api/diag/cancel/' + self.oid, ('released', 'obligation_state')),
        )
        for path, fields in cases:
            with self.subTest(path=path):
                data = self._data(path, token)
                self.assertEqual([name for name in fields if name not in data], [], data)

    # -- 4. read-only, even when polled -------------------------------------
    def test_reading_diagnostics_does_not_change_any_counter(self):
        token = self.session('caller-auditor')
        before = self.counts()
        # Twice each: a poll is a read too, and the face is meant to be polled.
        for _ in range(2):
            for path in self.routes():
                self.get(path, token)
        after = self.counts()
        self.assertEqual(after, before)

    # -- 5. no secrets in the projections -----------------------------------
    def test_no_nonce_or_private_material_is_exposed(self):
        token = self.session('caller-auditor')
        bodies = [(path, self.get(path, token).text) for path in self.routes()]
        # The nonce table is whitelisted, so reading it must redact its column.
        bodies.append(('/api/diag/db/w_nonce', self.get('/api/diag/db/w_nonce', token).text))
        for path, text in bodies:
            with self.subTest(path=path):
                for literal in ('private_key', 'session_id'):
                    self.assertNotIn(literal, text)
                for nonce in self.nonces:
                    self.assertNotIn(nonce, text)
                self.assertEqual(_signature_leaks(json.loads(text)), [], path)
        # The committed flow put nonces in the store; hiding them is not vacuous.
        self.assertTrue(self.nonces, 'the fixture flow left no nonce to hide')

    # -- 6. unknown operation is answered -----------------------------------
    def test_an_unknown_operation_is_reported_not_crashed(self):
        token = self.session('caller-auditor')
        for prefix in OPERATION_ROUTES:
            path = prefix + '/' + UNKNOWN_OID
            with self.subTest(path=path):
                reply = self.get(path, token)
                self.assertLess(reply.status_code, 500, reply.text)
                payload = reply.json()
                if reply.status_code == 200:
                    self.assertIsInstance(payload, dict)
                else:
                    self.assertEqual(payload.get('deny'), 'OPERATION_UNKNOWN', reply.text)

    # -- 7. unknown table is refused by name --------------------------------
    def test_an_unknown_table_is_refused_by_name(self):
        reply = self.get('/api/diag/db/not_a_table', self.session('caller-auditor'))
        self.assertGreaterEqual(reply.status_code, 400, reply.text)
        self.assertLess(reply.status_code, 500, reply.text)
        self.assertEqual(reply.json(), {'deny': 'DIAG_TABLE'})


if __name__ == '__main__':
    unittest.main()
