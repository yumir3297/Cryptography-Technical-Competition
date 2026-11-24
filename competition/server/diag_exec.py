"""Read-only endpoints for the claim, execution and settlement nodes.

Every handler receives the Starlette request, takes the routed ``oid`` from
``request.path_params`` and returns one :func:`diagnostics.envelope`.  The web
entry has already checked the ``auditor`` side and owns the JSON/error mapping;
these functions only project rows out of the trusted W database.

Nothing here writes: the connection is opened by :func:`diagnostics.connect`
(``mode=ro`` + ``query_only``), and no service method is called.  Optional
tables are probed before use, so a missing table or an absent row yields an
empty projection rather than an error.  Nonce values, request refs, encrypted
tool keys, signatures and full payloads are never selected.
"""
import sqlite3
from contextlib import closing

from competition.server.diagnostics import (
    connect, decode, envelope, operation_row, operation_view, outbox_row,
    settlement_row,
)
from competition.support.wire import ProtocolError, require

MAX_TOOL_ROWS = 10
OUTBOX_FIELDS = ('attempt_id', 'state', 'exec_marker', 'send_observed', 'queries')
SETTLEMENT_FIELDS = ('fact_id', 'ledger', 'final_seq', 'effect_id', 'outcome')


def _oid(request):
    """The operation id from the route, or the same refusal an unknown one gets."""
    oid = request.path_params.get('oid')
    require(type(oid) is str and oid, 'OPERATION_UNKNOWN')
    return oid


def _store(service):
    return service.run.store


def _operation(store, oid):
    """The operation row, with a missing table treated as an unknown operation."""
    try:
        return operation_row(store, oid)
    except sqlite3.Error as exc:
        raise ProtocolError('OPERATION_UNKNOWN') from exc


def _has_table(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                     (table,)).fetchone() is not None


def _rows(c, table, sql, args=()):
    """Rows from an optional table; a missing table is an empty result."""
    if not _has_table(c, table):
        return []
    try:
        return c.execute(sql, args).fetchall()
    except sqlite3.Error as exc:
        raise ProtocolError('DIAG_DB_UNAVAILABLE') from exc


def _outbox(c, profile, oid):
    """The outbox row, or ``None`` when the table or the row is absent."""
    try:
        return outbox_row(c, profile, oid)
    except sqlite3.Error:
        return None


def _outbox_data(row):
    if row is None:
        return {}
    return {name: row[name] for name in OUTBOX_FIELDS}


# -- A2: identity / ticket / worker nonces ----------------------------------
def _identity(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        identity = _rows(c, 'a_identity',
                         'SELECT stage,expires,used FROM a_identity '
                         'WHERE operation_id=? ORDER BY rowid DESC LIMIT 1', (oid,))
        tickets = _rows(c, 'w_ticket',
                        'SELECT ticket_id,expires FROM w_ticket WHERE oid=? '
                        'ORDER BY rowid DESC', (oid,))
        nonces = _rows(c, 'w_nonce',
                       'SELECT purpose,expires,used FROM w_nonce WHERE oid=? '
                       'ORDER BY rowid DESC', (oid,))
    ticket_rows = [dict(row) for row in tickets]
    identity_row = identity[0] if identity else None
    data = {
        'stage': identity_row['stage'] if identity_row else None,
        'expires': identity_row['expires'] if identity_row else None,
        'used': identity_row['used'] if identity_row else None,
        'ticket': ticket_rows[0] if ticket_rows else {},
        'tickets': ticket_rows,
        'nonces': [dict(row) for row in nonces],
    }
    return envelope('A2', operation_id=oid, profile=operation['profile'], data=data)


# -- D1: worker nonces ------------------------------------------------------
def _challenge(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        nonces = _rows(c, 'w_nonce',
                       'SELECT purpose,expires,used FROM w_nonce WHERE oid=? '
                       'ORDER BY rowid DESC', (oid,))
    return envelope('D1', operation_id=oid, profile=operation['profile'],
                    data={'nonces': [dict(row) for row in nonces]})


# -- D2: claim / outbox -----------------------------------------------------
def _claim(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        outbox = _outbox(c, operation['profile'], oid)
    return envelope('D2', operation_id=oid, profile=operation['profile'],
                    data=_outbox_data(outbox))


# -- D3: execution ----------------------------------------------------------
def _exec(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        outbox = _outbox(c, operation['profile'], oid)
    data = _outbox_data(outbox)
    marker = bool(outbox['exec_marker']) if outbox is not None else False
    data['effect_state'] = operation['effect_state']
    data['exec_consumed'] = marker
    data['replay_blocked'] = marker
    data['halted'] = operation['state'] == 'HALTED'
    return envelope('D3', operation_id=oid, profile=operation['profile'], data=data)


# -- D5: final fact / tool ledger -------------------------------------------
def _tools(c, profile):
    """At most ten tool-ledger rows; the encrypted ``key`` column is not read."""
    return _rows(c, 'w_tool',
                 'SELECT high_water,head,halted FROM w_tool WHERE profile=? '
                 'ORDER BY rowid DESC LIMIT ?', (profile, MAX_TOOL_ROWS))


def _final(service, oid):
    store = _store(service)
    try:
        view = operation_view(store, oid)
        profile = view['profile']
    except sqlite3.Error:
        # A projection table (e.g. a_observe_event) is absent: fall back to the
        # same two sources operation_view reads, so a missing table is not a 500.
        operation = _operation(store, oid)
        profile = operation['profile']
        with closing(connect(store.path)) as c:
            try:
                settlement = settlement_row(c, profile, oid)
            except sqlite3.Error:
                settlement = None
            tools = _tools(c, profile)
        view = {
            'profile': profile,
            'final_fact_id': settlement['fact_id'] if settlement is not None else None,
            'final_outcome': settlement['outcome'] if settlement is not None else None,
            'effect_state': operation['effect_state'],
            'dispatch_state': operation['state'],
        }
    else:
        with closing(connect(store.path)) as c:
            tools = _tools(c, profile)
    data = {
        'final_fact_id': view.get('final_fact_id'),
        'final_outcome': view.get('final_outcome'),
        'effect_state': view.get('effect_state'),
        'dispatch_state': view.get('dispatch_state'),
        'tools': [dict(row) for row in tools],
    }
    return envelope('D5', operation_id=oid, profile=view.get('profile'), data=data)


# -- S1: settlement ---------------------------------------------------------
def _settlement(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        try:
            settlement = settlement_row(c, operation['profile'], oid)
        except sqlite3.Error:
            settlement = None
    data = {} if settlement is None else \
        {name: settlement[name] for name in SETTLEMENT_FIELDS}
    return envelope('S1', operation_id=oid, profile=operation['profile'], data=data)


# -- S2: cancellation -------------------------------------------------------
def _cancel(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    state = operation['state']
    reason = None
    if state == 'CANCELED':
        with closing(connect(store.path)) as c:
            entries = _rows(c, 'a_journal',
                            "SELECT blob FROM a_journal WHERE profile=? AND operation_id=? "
                            "AND kind='W_CANCEL' ORDER BY seq DESC LIMIT 1",
                            (operation['profile'], oid))
        if entries:
            value = decode(entries[0], 'blob')
            if isinstance(value, dict):
                reason = value.get('reason')
    with closing(connect(store.path)) as c:
        obligations = _rows(c, 'w_goal',
                            'SELECT DISTINCT state FROM w_goal WHERE profile=? AND oid=? '
                            'ORDER BY state', (operation['profile'], oid))
    return envelope('S2', operation_id=oid, profile=operation['profile'],
                    data={'state': state, 'reason': reason,
                          'released': state == 'CANCELED',
                          'obligation_state': [row['state'] for row in obligations]})


# -- S3: query attempt ------------------------------------------------------
def _query(service, oid):
    store = _store(service)
    operation = _operation(store, oid)
    with closing(connect(store.path)) as c:
        outbox = _outbox(c, operation['profile'], oid)
        entries = _rows(c, 'w_evidence',
                        "SELECT blob FROM w_evidence WHERE profile=? AND oid=? "
                        "AND kind='QUERY' ORDER BY seq DESC LIMIT 1",
                        (operation['profile'], oid))
    last_state = last_reason = None
    if entries:
        value = decode(entries[0], 'blob')
        if isinstance(value, dict):
            last_state = value.get('state')
            last_reason = value.get('reason')
    return envelope('S3', operation_id=oid, profile=operation['profile'],
                    data={'queries': outbox['queries'] if outbox is not None else 0,
                          'last_state': last_state, 'last_reason': last_reason})


def routes(service):
    """The claim/execution/settlement read-only routes, for ``web.app``."""
    def identity(request):
        return _identity(service, _oid(request))

    def challenge(request):
        return _challenge(service, _oid(request))

    def claim(request):
        return _claim(service, _oid(request))

    def execution(request):
        return _exec(service, _oid(request))

    def final(request):
        return _final(service, _oid(request))

    def settlement(request):
        return _settlement(service, _oid(request))

    def cancel(request):
        return _cancel(service, _oid(request))

    def query(request):
        return _query(service, _oid(request))

    return [
        ('/api/diag/identity/{oid}', identity),
        ('/api/diag/challenge/{oid}', challenge),
        ('/api/diag/claim/{oid}', claim),
        ('/api/diag/exec/{oid}', execution),
        ('/api/diag/final/{oid}', final),
        ('/api/diag/settlement/{oid}', settlement),
        ('/api/diag/cancel/{oid}', cancel),
        ('/api/diag/query/{oid}', query),
    ]
