"""Read-only diagnostic projections for the trusted entry.

Every helper here opens the trusted SQLite stores in ``mode=ro`` and returns a
display projection.  Nothing creates a nonce, advances the clock, writes
evidence or calls a signer.  The HTTP layer requires the ``auditor`` session
side before any of this is reached.
"""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from competition.support.wire import require, ProtocolError

VIEW_KIND = 'DIAGNOSTIC_PROJECTION'
NOT_EVIDENCE = True

# Column names that never leave the database through /api/diag/db.
REDACT_COLUMNS = frozenset({
    'frozen', 'op', 'packet', 'receipt', 'record', 'certificate', 'blob',
    'message', 'context', 'root_certificate', 'nonce', 'signature', 'sig',
    'private_key', 'payload', 'evidence', 'session_id',
})

# Only these tables may be read through /api/diag/db.
TABLE_WHITELIST = frozenset({
    'w_meta', 'w_ticket', 'w_operation', 'w_intent', 'w_consumed', 'w_mutable',
    'w_resource', 'w_reservation', 'w_flight', 'w_outbox', 'w_nonce', 'w_tool',
    'w_settlement', 'w_goal', 'w_evidence', 'a_current', 'a_journal',
    'a_deny_range', 'a_publication', 'a_guard_fact', 'a_observe_event',
    'comp_event_clock',
})


def connect(path):
    """Open one SQLite file read-only; never create it."""
    require(Path(path).is_file(), 'DIAG_DB_UNAVAILABLE')
    try:
        c = sqlite3.connect('file:%s?mode=ro' % Path(path).resolve(), uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        return c
    except sqlite3.Error as exc:
        raise ProtocolError('DIAG_DB_UNAVAILABLE') from exc


def envelope(node, *, operation_id=None, profile=None, data=None):
    return {'node': node, 'operation_id': operation_id, 'profile': profile,
            'as_of': int(time.time()), 'view_kind': VIEW_KIND,
            'signed': False, 'not_evidence': NOT_EVIDENCE,
            'data': data if data is not None else {}}


def decode(row, column):
    value = row[column] if row is not None else None
    if value in (None, ''):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise ProtocolError('DIAG_CORRUPT')


def operation_row(store, oid):
    with closing(connect(store.path)) as c:
        row = c.execute('SELECT * FROM w_operation WHERE oid=?', (oid,)).fetchone()
    require(row is not None, 'OPERATION_UNKNOWN')
    return row


def operation_view(store, oid):
    from competition.server.observe import ObservationFeed
    view = ObservationFeed(store.path).snapshot(oid)
    require(view is not None, 'OPERATION_UNKNOWN')
    return view


def outbox_row(c, profile, oid):
    return c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',
                     (profile, oid)).fetchone()


def settlement_row(c, profile, oid):
    return c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',
                     (profile, oid)).fetchone()


def goal_rows(c, profile, oid):
    return c.execute('SELECT * FROM w_goal WHERE profile=? AND oid=? ORDER BY goal_group',
                     (profile, oid)).fetchall()


def evidence_rows(c, profile, oid, limit=100):
    rows = c.execute('SELECT seq,kind,blob FROM w_evidence WHERE profile=? AND oid=? '
                     'ORDER BY seq DESC LIMIT ?', (profile, oid, max(1, min(int(limit), 200)))).fetchall()
    out = []
    for row in rows:
        try:
            value = json.loads(row['blob'])
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        item = {'seq': row['seq'], 'kind': row['kind']}
        for key in ('state', 'reason', 'effect_state', 'validation_error'):
            if key in value:
                item[key] = value[key]
        out.append(item)
    return out


def table_rows(store, table, *, profile=None, limit=100, offset=0):
    require(table in TABLE_WHITELIST, 'DIAG_TABLE')
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    with closing(connect(store.path)) as c:
        columns = [row[1] for row in c.execute('PRAGMA table_info(%s)' % table)]
        sql = 'SELECT * FROM %s' % table
        args = []
        if profile is not None and 'profile' in columns:
            sql += ' WHERE profile=?'
            args.append(profile)
        sql += ' ORDER BY rowid DESC LIMIT ? OFFSET ?'
        args += [limit, offset]
        rows = [dict(row) for row in c.execute(sql, args)]
    for row in rows:
        for name in list(row):
            if name in REDACT_COLUMNS:
                del row[name]
            elif isinstance(row[name], str) and len(row[name]) > 200:
                row[name] = row[name][:200] + '...'
    return {'table': table, 'columns': columns, 'rows': rows,
            'limit': limit, 'offset': offset}
