"""Read-only observation face: project committed decisions into a display stream.

The trusted side's decisions are real only once their transaction commits.  This
face reads exactly two things and writes no business fact of its own:

* ``a_observe_event`` -- the append-only publish log the core writes *inside* its
  own transactions, so a committed decision is observable and a rolled-back one is
  not.  ``seq`` is the subscription cursor.
* the ``w_operation`` / ``w_outbox`` / ``w_settlement`` rows, for one operation's
  current snapshot.

Nothing here can drive a step: there is no challenge, no proof and no signature
path, and the connection is opened read-only.  Every response is a *display*
projection and says so -- ``signed`` is false, ``original_envelope`` is false and
``not_evidence`` is true.  Business payloads, nonces, session ids, signatures and
private material never leave: each event is re-checked against an explicit
forbidden-field set and :func:`competition.server.export.forbidden_secrets`, and a
row that fails is dropped rather than shown.
"""
import json
import sqlite3
import time
from contextlib import closing

from competition.core.trusted_state import enc
from competition.server.export import forbidden_secrets

# What every projection is and is not.  A reader must not mistake this for the
# protocol's own signed status or for an audit-evidence object.
VIEW_KIND = 'OBSERVATION_PROJECTION'
NOT_EVIDENCE = True
# Field names that must never appear in a published event, whatever the source.
FORBIDDEN_KEYS = frozenset({
    'payload', 'nonce', 'session_id', 'signature', 'sig', 'receipt', 'ticket_id',
    'private_key', 'privkey', 'private', 'secret', 'secret_key', 'seed', 'password',
})


def _contains_forbidden_key(value):
    """True when ``value`` holds any field a display event must not carry."""
    if isinstance(value, dict):
        return any(k in FORBIDDEN_KEYS or _contains_forbidden_key(v)
                   for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(v) for v in value)
    return False


def _sse(seq, event):
    """One Server-Sent Events frame carrying one observation event."""
    return 'id: %d\ndata: %s\n\n' % (seq, json.dumps(event, ensure_ascii=False, sort_keys=True))


class ObservationFeed:
    """Read-only projector over one committed W database."""

    def __init__(self, db_path, *, now=time.monotonic):
        self.db_path = str(db_path)
        self.now = now

    # -- read-only connections ---------------------------------------------
    def _read(self, *, check_same_thread=True):
        """A read-only connection to the committed W database.

        ``mode=ro`` plus ``query_only`` makes the read-only rule a property of the
        connection rather than a promise in the readers.  WAL already lets this
        coexist with the writer.  The streaming reader runs its body on a
        thread-pool worker that the ASGI server may not keep on one thread, so it
        opts out of sqlite's thread check -- the connection is still used
        sequentially, one statement at a time.
        """
        c = sqlite3.connect('file:%s?mode=ro' % self.db_path, uri=True,
                            isolation_level=None, timeout=5,
                            check_same_thread=check_same_thread)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        return c

    # -- event projection ---------------------------------------------------
    @staticmethod
    def _project(row):
        """One stored event as a safe display projection, or ``None`` if refused."""
        try:
            fields = json.loads(row['blob'])
        except (TypeError, ValueError):
            return None
        if type(fields) is not dict or _contains_forbidden_key(fields):
            return None
        event = {'seq': row['seq'], 'kind': row['kind'], 'source': row['source'],
                 'profile': row['profile'], 'operation_id': row['operation_id'],
                 'stage': fields.get('stage'), 'lanes': fields.get('lanes') or [],
                 'trusted_time': fields.get('trusted_time'),
                 'refs': fields.get('refs') or {}, 'status_label': fields.get('status_label'),
                 'detail': fields.get('detail') or {},
                 'view_kind': VIEW_KIND, 'original_envelope': False, 'signed': False,
                 'not_evidence': NOT_EVIDENCE}
        if row['source'] == 'ENTRY':
            event['flow'] = True
        if forbidden_secrets(event):
            return None
        return event

    def events(self, after=0, *, limit=500, profile=None, operation_id=None):
        """Committed observation events with ``seq`` greater than ``after``."""
        limit = max(1, min(int(limit), 1000))
        sql = ('SELECT seq,source,kind,profile,operation_id,blob FROM a_observe_event '
               'WHERE seq>?')
        args = [int(after)]
        if profile is not None:
            sql += ' AND profile=?'; args.append(profile)
        if operation_id is not None:
            sql += ' AND operation_id=?'; args.append(operation_id)
        sql += ' ORDER BY seq LIMIT ?'; args.append(limit)
        with closing(self._read()) as c:
            return [event for event in (self._project(row) for row in c.execute(sql, args))
                    if event is not None]

    # -- one-operation snapshot --------------------------------------------
    def snapshot(self, operation_id):
        """The current projection of one committed operation, or ``None``.

        Reads only the operation's own status columns and its observation events;
        the frozen request (which carries business payload) never leaves.
        """
        with closing(self._read()) as c:
            row = c.execute('SELECT * FROM w_operation WHERE oid=?', (operation_id,)).fetchone()
            if row is None:
                return None
            profile = row['profile']
            out = c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',
                            (profile, operation_id)).fetchone()
            settle = c.execute('SELECT fact_id,outcome FROM w_settlement WHERE profile=? AND oid=?',
                               (profile, operation_id)).fetchone()
            frozen = json.loads(row['frozen'])
            events = [event for event in
                      (self._project(r) for r in c.execute(
                          'SELECT seq,source,kind,profile,operation_id,blob FROM a_observe_event '
                          'WHERE profile=? AND operation_id=? ORDER BY seq', (profile, operation_id)))
                      if event is not None]
        witness = frozen.get('time_witness') or {}
        view = {'kind': 'competition_operation_observation',
                'profile': profile, 'operation_id': operation_id,
                'acceptance_state': 'COMMITTED', 'dispatch_state': row['state'],
                'effect_state': row['effect_state'],
                'receipt_state': 'SIGNED' if row['receipt'] else 'PENDING',
                'attempt_id': out['attempt_id'] if out else None,
                'exec_consumed': bool(out['exec_marker']) if out else False,
                'queries': out['queries'] if out else 0,
                'accepted_at': str(frozen.get('accepted_at')) if frozen.get('accepted_at') else None,
                'trusted_time': ({'lo': witness.get('lo'), 'hi': witness.get('hi')}
                                 if witness else None),
                'final_fact_id': settle['fact_id'] if settle else None,
                'final_outcome': settle['outcome'] if settle else None,
                'events': events,
                'view_kind': VIEW_KIND, 'original_envelope': False, 'signed': False,
                'not_evidence': NOT_EVIDENCE}
        if forbidden_secrets(view):
            return None
        return view

    def operations(self, *, profile=None, state=None, limit=500):
        """The newest committed operations, as display rows (no payload, no receipt)."""
        limit = max(1, min(int(limit), 1000))
        sql = 'SELECT profile,oid,state,effect_state,receipt IS NOT NULL AS signed FROM w_operation'
        args = []
        if profile is not None:
            sql += ' WHERE profile=?'; args.append(profile)
        if state is not None:
            sql += (' AND ' if args else ' WHERE ') + 'state=?'; args.append(state)
        sql += ' ORDER BY rowid DESC LIMIT ?'; args.append(limit)
        with closing(self._read()) as c:
            return [{'profile': r['profile'], 'operation_id': r['oid'],
                     'dispatch_state': r['state'], 'effect_state': r['effect_state'],
                     'receipt_state': 'SIGNED' if r['signed'] else 'PENDING'}
                    for r in c.execute(sql, args)]

    # -- push channel -------------------------------------------------------
    def stream(self, after=0, *, poll=0.25, ping=15.0):
        """Yield Server-Sent Events frames for every event after ``after``.

        A long-lived read-only connection is fine: with WAL, each statement sees
        the latest committed state without a write lock.  An idle stream is kept
        alive with an SSE comment so a reader can tell "nothing has happened yet"
        apart from "the connection died".
        """
        cursor = int(after)
        c = self._read(check_same_thread=False)
        last = self.now()
        try:
            while True:
                rows = c.execute('SELECT seq,source,kind,profile,operation_id,blob '
                                 'FROM a_observe_event WHERE seq>? ORDER BY seq',
                                 (cursor,)).fetchall()
                if rows:
                    for row in rows:
                        event = self._project(row)
                        cursor = max(cursor, row['seq'])
                        if event is not None:
                            yield _sse(row['seq'], event)
                    last = self.now()
                    continue
                time.sleep(poll)
                if self.now() - last >= ping:
                    last = self.now()
                    yield ': ping\n\n'
        finally:
            c.close()

    # -- entry-side best-effort publish ------------------------------------
    def publish(self, kind, profile, operation_id, fields):
        """Append one ENTRY (flow, non-authoritative) event; never raises.

        Entry events describe what the trusted entry saw, not a core decision, so
        they are best-effort: a failure to record one must not fail the request.
        They are marked ``source='ENTRY'`` and ``flow=true`` downstream.
        """
        try:
            c = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
            try:
                c.execute('INSERT INTO a_observe_event(source,kind,profile,operation_id,blob) '
                          'VALUES(?,?,?,?,?)', ('ENTRY', kind, profile, operation_id, enc(fields)))
            finally:
                c.close()
            return True
        except sqlite3.Error:
            return False
