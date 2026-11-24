"""Read-only endpoints for clock, endpoints, tool ledger and result export.

Every handler is a projection: it opens the trusted SQLite stores through
:mod:`competition.server.diagnostics` (``mode=ro`` plus ``PRAGMA query_only``)
and returns an :func:`~competition.server.diagnostics.envelope`.  Nothing here
writes a table, creates a nonce, advances the event clock, samples the clock or
calls a service method.
"""
from contextlib import closing
from functools import partial

from competition.server.diagnostics import (
    connect, decode, envelope, evidence_rows, operation_row, operation_view,
)
from competition.support.wire import ProtocolError, b64, require
from competition.tools.common_tool import EFFECT_FIELDS


def _columns(c, table):
    """The column names of ``table``, read from the file itself."""
    return [row[1] for row in c.execute('PRAGMA table_info(%s)' % table)]


def _exists(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                     (table,)).fetchone() is not None


def _tool_summary(database, oid, profile):
    """One profile's tool-ledger rows for ``oid``, or ``None`` if it has none.

    The tool schema has no ``state`` column.  The state reported for a request
    or an effect is the final fact's own ``outcome`` (the same value the tool
    itself returns as ``state``), or ``EFFECT_UNKNOWN`` when no final fact
    exists yet.  Only identifiers and hashes leave; ``claim`` and ``fact``
    payloads never do.
    """
    with closing(connect(database)) as c:
        req_cols = _columns(c, 'tool_requests') if _exists(c, 'tool_requests') else []
        fact_cols = _columns(c, 'tool_finalfacts') if _exists(c, 'tool_finalfacts') else []
        effect_table = EFFECT_FIELDS.get(profile, (None, ()))[0]
        eff_cols = (_columns(c, effect_table)
                    if effect_table and _exists(c, effect_table) else [])
        # A table that cannot be filtered by operation id is reported by shape,
        # never by guessing which of its rows belongs to this operation.
        unsupported = {}
        for name, cols in (('tool_requests', req_cols), ('tool_finalfacts', fact_cols),
                           (effect_table, eff_cols)):
            if name and cols and 'operation_id' not in cols:
                unsupported[name] = cols
        fact_rows = []
        if 'operation_id' in fact_cols:
            fact_rows = c.execute(
                'SELECT operation_id,final_seq,effect_id,fact FROM tool_finalfacts '
                'WHERE operation_id=? ORDER BY final_seq', (oid,)).fetchall()
        request_rows = []
        if 'operation_id' in req_cols:
            request_rows = c.execute(
                'SELECT operation_id,request_hash FROM tool_requests '
                'WHERE operation_id=?', (oid,)).fetchall()
        effect_rows = []
        if 'operation_id' in eff_cols:
            effect_rows = c.execute(
                'SELECT operation_id,effect_id FROM %s WHERE operation_id=? '
                'ORDER BY effect_id' % effect_table, (oid,)).fetchall()
        if not (request_rows or fact_rows or effect_rows):
            return None
        outcome_by_oid, outcome_by_effect = {}, {}
        finalfacts = []
        for row in fact_rows:
            value = decode(row, 'fact')
            outcome = value.get('outcome') if isinstance(value, dict) else None
            outcome_by_oid[row['operation_id']] = outcome
            if row['effect_id'] is not None:
                outcome_by_effect[row['effect_id']] = outcome
            finalfacts.append({'final_seq': row['final_seq'], 'outcome': outcome,
                               'effect_id': row['effect_id']})
        requests = [{'request_hash': row['request_hash'],
                     'state': outcome_by_oid.get(row['operation_id'], 'EFFECT_UNKNOWN')}
                    for row in request_rows]
        effects = [{'effect_id': row['effect_id'],
                    'state': outcome_by_effect.get(row['effect_id'], 'EFFECT_UNKNOWN')}
                   for row in effect_rows]
        data = {'profile': profile, 'requests': requests, 'finalfacts': finalfacts,
                'effects': effects}
        if unsupported:
            data['columns'] = unsupported
        return data


def clock(service, request):
    """A1: the committed W clock head, read without sampling it."""
    with closing(connect(service.run.store.path)) as c:
        row = c.execute('SELECT sequence,time_floor FROM comp_event_clock WHERE id=1').fetchone()
    require(row is not None, 'DIAG_CORRUPT')
    data = {'w_sequence': row['sequence'], 'time_floor': row['time_floor'],
            'instance_id': service.run.clock.instance_id}
    return envelope('A1', data=data)


def endpoints(service, request):
    """A6: every profile's public roster; only public actor fields leave."""
    profiles = {}
    for profile, roster in service.run.actors.items():
        profiles[profile] = {
            alias: {'subject': actor.name, 'kid': actor.kid,
                    'public_key': b64(actor.pub),
                    'roles': sorted(actor.roles),
                    'purposes': sorted(actor.purposes)}
            for alias, actor in roster.items()}
    return envelope('A6', data={'profiles': profiles})


def tool(service, request):
    """D4: one operation's rows in the independent tool ledgers."""
    oid = request.path_params.get('oid')
    require(oid, 'OPERATION_UNKNOWN')
    gateways = getattr(getattr(service.run, 'w', None), 'tool_gateways', {}) or {}
    for gateway in gateways.values():
        config = getattr(gateway, 'config', None)
        if not isinstance(config, dict):
            continue
        database, profile = config.get('database'), config.get('profile')
        if not database or not profile:
            continue
        data = _tool_summary(database, oid, profile)
        if data is not None:
            return envelope('D4', operation_id=oid, profile=profile, data=data)
    return envelope('D4', operation_id=oid, data={})


COMMIT_FIELDS = ('ctx', 'permit_ref', 'proof_ref', 'authorization_ref',
                 'review_refs', 'accept_seq', 'accepted_at', 'dispatch_before',
                 'reservation_ids')


def _safe_time(value):
    """The bounded interval of an event witness, never its signed sample."""
    if not isinstance(value, dict):
        return None
    return {'lo': value.get('lo'), 'hi': value.get('hi')}


def _audit_safe(frozen, evidence):
    """The default audit projection: no business payload, no signed sample."""
    frozen = frozen if isinstance(frozen, dict) else {}
    record = frozen.get('commit')
    value = record.get('value') if isinstance(record, dict) else None
    value = value if isinstance(value, dict) else {}
    commit = {'commit_ref': frozen.get('commit_ref')}
    commit.update({key: value.get(key) for key in COMMIT_FIELDS})
    return {'commit': commit,
            'time_witness': _safe_time(frozen.get('time_witness')),
            'evidence': evidence}


def result(service, request):
    """R1+R2: the operation's status/audit projection and, on demand, its bundle."""
    oid = request.path_params.get('oid')
    require(oid, 'OPERATION_UNKNOWN')
    store = service.run.store
    status = operation_view(store, oid)
    row = operation_row(store, oid)
    frozen = decode(row, 'frozen')
    require(isinstance(frozen, dict), 'DIAG_CORRUPT')
    op = frozen.get('op')
    require(isinstance(op, dict), 'DIAG_CORRUPT')
    profile = status.get('profile') or row['profile']
    with closing(connect(store.path)) as c:
        evidence = evidence_rows(c, profile, oid)
    audit = {'commit': frozen.get('commit'), 'time_witness': frozen.get('time_witness'),
             'evidence': evidence}
    from competition.server.export import KIND, operation_bundle
    try:
        bundle = operation_bundle(service.run, profile, op, status, audit)
    except ProtocolError as exc:
        # A bundle that would leak private material is not a server failure:
        # the read projection is still useful, so report why it was withheld.
        bundle, export_error = None, exc.code
    else:
        export_error = None
    if bundle is not None:
        chain_valid = bundle['chain_valid']
    else:
        from competition.support.artifact import signed_messages_valid
        try:
            chain_valid = signed_messages_valid(service.run, profile, op)
        except ProtocolError:
            chain_valid = False
    if request.query_params.get('full') == '1' and bundle is not None:
        data = bundle
    else:
        data = {'kind': KIND, 'profile': profile, 'operation_id': oid,
                'chain_valid': chain_valid, 'status': status,
                'audit': _audit_safe(frozen, evidence)}
        if export_error is not None:
            data['export_error'] = export_error
    return envelope('R1+R2', operation_id=oid, profile=profile, data=data)


def routes(service):
    return [
        ('/api/diag/clock', partial(clock, service)),
        ('/api/diag/endpoints', partial(endpoints, service)),
        ('/api/diag/tool/{oid}', partial(tool, service)),
        ('/api/diag/result/{oid}', partial(result, service)),
    ]
