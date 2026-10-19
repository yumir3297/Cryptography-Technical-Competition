"""The agent boundary's own journal.

It records two things the trusted side does not expose through its three-message
interface: which candidates this gateway submitted, and which status projections
it has already shown.  It deliberately keeps no business intent and no signed
receipt: the trusted side owns those, and a feedback message only needs scalar
state plus references.

The journal is SQLite because two kinds of caller touch it at once: the MCP
tools (request threads) and the status poller (one background thread).  A single
connection guarded by one lock is enough for this deployment; WAL keeps a reader
from blocking the short writes.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# A submitted operation lives in the trusted process's memory.  A read that still
# says OPERATION_UNKNOWN after this grace period is treated as unavailable rather
# than as "not accepted yet"; the trusted side has no NONE view to distinguish
# the two.
DEFAULT_GRACE_SECONDS = 300.0
LEASE_SECONDS = 30.0

TERMINAL_STATES = frozenset({'SETTLED', 'HALTED', 'CANCELED', 'UNAVAILABLE'})

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    profile TEXT NOT NULL,
    digest TEXT NOT NULL,
    state TEXT NOT NULL,
    operation_id TEXT,
    detail TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (profile, digest)
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    digest TEXT NOT NULL,
    submitted_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    state TEXT NOT NULL,
    fingerprint TEXT,
    status_json TEXT,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    last_read_at REAL,
    read_failures INTEGER NOT NULL DEFAULT 0,
    terminal INTEGER NOT NULL DEFAULT 0,
    operator_lease_until REAL,
    executor_lease_until REAL
);

CREATE INDEX IF NOT EXISTS operations_active
    ON operations(terminal, state, submitted_at);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail_json TEXT,
    created_at REAL NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE
);
"""


class JournalError(RuntimeError):
    """The gateway's own journal could not satisfy a request."""


class Journal:
    """One process's append-only feedback log plus its operation index."""

    def __init__(self, path, *, grace=DEFAULT_GRACE_SECONDS,
                 lease=LEASE_SECONDS, now=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.grace = float(grace)
        self.lease = float(lease)
        self.now = now
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=NORMAL')
            self._db.executescript(SCHEMA)

    def close(self):
        with self._lock:
            self._db.close()

    # -- submissions --------------------------------------------------------
    def submission(self, profile, digest):
        with self._lock:
            row = self._db.execute(
                'SELECT * FROM submissions WHERE profile=? AND digest=?',
                (profile, digest)).fetchone()
        return dict(row) if row else None

    def submission_by_digest(self, digest):
        """One reservation by its own handle.

        The digest is the stable identity of a business intent, so it is unique
        across profiles -- it is taken over the profile too -- and it is what the
        agent is handed before the trusted side has answered.  A caller that only
        holds that handle can still read what is known about its own submission.
        """
        with self._lock:
            row = self._db.execute('SELECT * FROM submissions WHERE digest=?',
                                   (digest,)).fetchone()
        return dict(row) if row else None

    def begin_submission(self, profile, digest):
        """Reserve one intent, or return the reservation already made.

        Returns ``(row, should_submit)``.  A denied intent may be proposed again
        because the caller is expected to correct it; an in-flight or unknown
        submission may not, because the gateway cannot know whether the trusted
        side already created an operation.
        """
        now = self.now()
        with self._lock:
            row = self._db.execute(
                'SELECT * FROM submissions WHERE profile=? AND digest=?',
                (profile, digest)).fetchone()
            if row is None:
                self._db.execute(
                    'INSERT INTO submissions(profile, digest, state, created_at, updated_at) '
                    'VALUES(?,?,?,?,?)',
                    (profile, digest, 'SUBMITTING', now, now))
                return ({'profile': profile, 'digest': digest, 'state': 'SUBMITTING',
                         'operation_id': None, 'created_at': now, 'updated_at': now}, True)
            row = dict(row)
            if row['state'] == 'DENIED':
                self._db.execute(
                    'UPDATE submissions SET state=?, operation_id=NULL, detail=NULL, '
                    'updated_at=? WHERE profile=? AND digest=?',
                    ('SUBMITTING', now, profile, digest))
                row.update({'state': 'SUBMITTING', 'operation_id': None,
                            'detail': None, 'updated_at': now})
                return row, True
            return row, False

    def mark_submitted(self, profile, digest, operation_id):
        now = self.now()
        with self._lock:
            self._db.execute(
                'UPDATE submissions SET state=?, operation_id=?, detail=NULL, updated_at=? '
                'WHERE profile=? AND digest=?',
                ('SUBMITTED', operation_id, now, profile, digest))
            self._db.execute(
                'INSERT OR IGNORE INTO operations(operation_id, profile, digest, submitted_at, '
                'updated_at, state) VALUES(?,?,?,?,?,?)',
                (operation_id, profile, digest, now, now, 'SUBMITTED'))

    def mark_submission_denied(self, profile, digest, code):
        now = self.now()
        with self._lock:
            self._db.execute(
                'UPDATE submissions SET state=?, detail=?, updated_at=? '
                'WHERE profile=? AND digest=?',
                ('DENIED', code, now, profile, digest))

    def mark_submission_unknown(self, profile, digest, detail):
        now = self.now()
        with self._lock:
            self._db.execute(
                'UPDATE submissions SET state=?, detail=?, updated_at=? '
                'WHERE profile=? AND digest=?',
                ('SUBMIT_UNKNOWN', detail, now, profile, digest))

    # -- operations ---------------------------------------------------------
    def operation(self, operation_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM operations WHERE operation_id=?',
                                   (operation_id,)).fetchone()
        return self._decode(row) if row else None

    def active_operations(self):
        with self._lock:
            rows = self._db.execute(
                'SELECT * FROM operations WHERE terminal=0 ORDER BY submitted_at').fetchall()
        return [self._decode(row) for row in rows]

    def update_status(self, operation_id, state, fingerprint, status, *,
                      read_ok=True):
        """Store one observed projection; return ``(previous, changed)``.

        ``status`` is the already-redacted scalar view.  The full raw status
        response never enters the journal.
        """
        now = self.now()
        blob = json.dumps(status, ensure_ascii=False, sort_keys=True)
        terminal = 1 if state in TERMINAL_STATES else 0
        with self._lock:
            row = self._db.execute('SELECT * FROM operations WHERE operation_id=?',
                                   (operation_id,)).fetchone()
            if row is None:
                raise JournalError('OPERATION_UNKNOWN')
            previous = self._decode(row)
            if previous['fingerprint'] == fingerprint:
                self._db.execute(
                    'UPDATE operations SET last_read_at=?, read_failures=0, updated_at=? '
                    'WHERE operation_id=?', (now, now, operation_id))
                return previous, False
            self._db.execute(
                'UPDATE operations SET state=?, fingerprint=?, status_json=?, '
                'last_read_at=?, read_failures=0, updated_at=?, terminal=? '
                'WHERE operation_id=?',
                (state, fingerprint, blob, now, now, terminal, operation_id))
            updated = self._decode(self._db.execute(
                'SELECT * FROM operations WHERE operation_id=?',
                (operation_id,)).fetchone())
        return previous, True

    def record_read_failure(self, operation_id, detail=''):
        """Keep the last known projection; return the new failure count."""
        now = self.now()
        with self._lock:
            row = self._db.execute(
                'SELECT read_failures FROM operations WHERE operation_id=?',
                (operation_id,)).fetchone()
            if row is None:
                raise JournalError('OPERATION_UNKNOWN')
            failures = int(row['read_failures']) + 1
            self._db.execute(
                'UPDATE operations SET read_failures=?, last_read_at=?, updated_at=? '
                'WHERE operation_id=?',
                (failures, now, now, operation_id))
            return failures

    def mark_terminal(self, operation_id, state):
        now = self.now()
        with self._lock:
            self._db.execute(
                'UPDATE operations SET terminal=1, state=?, updated_at=? '
                'WHERE operation_id=?', (state, now, operation_id))

    # -- events -------------------------------------------------------------
    def add_event(self, operation_id, kind, state, summary, detail=None, *,
                  dedupe_key=None):
        """Append one event unless its exact dedupe key is already present."""
        now = self.now()
        key = dedupe_key or '%s:%s:%s' % (operation_id, kind, state)
        blob = None if detail is None else json.dumps(detail, ensure_ascii=False,
                                                      sort_keys=True)
        with self._lock:
            cursor = self._db.execute(
                'INSERT OR IGNORE INTO events(operation_id, kind, state, summary, '
                'detail_json, created_at, dedupe_key) VALUES(?,?,?,?,?,?,?)',
                (operation_id, kind, state, summary, blob, now, key))
            if cursor.rowcount == 0:
                return None
            seq = int(cursor.lastrowid)
            self._db.execute(
                'UPDATE operations SET last_event_seq=? WHERE operation_id=?',
                (seq, operation_id))
            return seq

    def events(self, *, since=0, operation_id=None, limit=100):
        limit = max(1, min(int(limit), 500))
        sql = 'SELECT * FROM events WHERE seq>?'
        params = [int(since)]
        if operation_id is not None:
            sql += ' AND operation_id=?'
            params.append(operation_id)
        sql += ' ORDER BY seq LIMIT ?'
        params.append(limit)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._decode_event(row) for row in rows]

    def latest_seq(self, operation_id=None):
        sql = 'SELECT COALESCE(MAX(seq),0) AS seq FROM events'
        params = []
        if operation_id is not None:
            sql += ' WHERE operation_id=?'
            params.append(operation_id)
        with self._lock:
            row = self._db.execute(sql, params).fetchone()
        return int(row['seq'])

    # -- operator / executor queue -----------------------------------------
    def claim(self, role, *, lease=None):
        """Take one eligible operation for ``operator`` or ``executor``.

        The lease is not a security boundary; the trusted side's own ticket,
        attempt and EXEC rules decide what work is possible.  It only keeps two
        identical demo workers from stepping on each other.
        """
        if role not in ('operator', 'executor'):
            raise JournalError('QUEUE_ROLE')
        now = self.now()
        column = role + '_lease_until'
        where_state = ("state='SUBMITTED'" if role == 'operator'
                       else "state IN ('ACCEPTED','STARTED')")
        with self._immediate():
            row = self._db.execute(
                'SELECT * FROM operations WHERE terminal=0 AND %s '
                'AND (%s IS NULL OR %s < ?) ORDER BY submitted_at LIMIT 1'
                % (where_state, column, column), (now,)).fetchone()
            if row is None:
                return None
            self._db.execute(
                'UPDATE operations SET %s=? WHERE operation_id=?' % column,
                (now + (lease or self.lease), row['operation_id']))
            return self._decode(row)

    def release(self, role, operation_id):
        if role not in ('operator', 'executor'):
            raise JournalError('QUEUE_ROLE')
        column = role + '_lease_until'
        with self._lock:
            self._db.execute(
                'UPDATE operations SET %s=NULL WHERE operation_id=?' % column,
                (operation_id,))

    # -- internals ----------------------------------------------------------
    @contextmanager
    def _immediate(self):
        self._lock.acquire()
        try:
            self._db.execute('BEGIN IMMEDIATE')
            yield
            self._db.execute('COMMIT')
        except BaseException:
            self._db.execute('ROLLBACK')
            raise
        finally:
            self._lock.release()

    @staticmethod
    def _decode(row):
        value = dict(row)
        if value.get('status_json'):
            try:
                value['status'] = json.loads(value['status_json'])
            except json.JSONDecodeError:
                value['status'] = None
        else:
            value['status'] = None
        value.pop('status_json', None)
        value['terminal'] = bool(value.get('terminal'))
        return value

    @staticmethod
    def _decode_event(row):
        value = dict(row)
        if value.get('detail_json'):
            try:
                value['detail'] = json.loads(value['detail_json'])
            except json.JSONDecodeError:
                value['detail'] = None
        else:
            value['detail'] = None
        value.pop('detail_json', None)
        return value
