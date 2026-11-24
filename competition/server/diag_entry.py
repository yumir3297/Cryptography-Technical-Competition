"""Read-only endpoints for the entry/observation/registry/storage nodes.

Every handler here projects already-committed state.  Nothing writes a table,
creates a nonce, advances the clock, signs, or touches the web flow lock; the
HTTP layer has already checked the ``auditor`` session side and wraps the
returned dict as JSON.
"""
from contextlib import closing

from competition.server.diagnostics import (
    connect,
    decode,
    envelope,
    table_rows,
)
from competition.support.wire import require


def _int_param(request, name, default):
    """One non-negative query parameter, or a refusal naming the rule."""
    raw = request.query_params.get(name)
    if raw in (None, ''):
        return default
    require(raw.isdigit(), 'WEB_FIELDS')
    return int(raw)


def _text_param(request, name):
    """One optional query parameter; an empty value means it was absent."""
    raw = request.query_params.get(name)
    return raw if raw not in (None, '') else None


def routes(service):
    def entry(request):
        """E1+E2: in-memory candidates merged with the newest W operations."""
        entries = getattr(service, '_entries', None) or {}
        memory = {}
        for oid, item in list(entries.items()):
            item = item or {}
            memory[oid] = {
                'profile': item.get('profile'),
                'operation_id': oid,
                'state': None,
                'effect_state': None,
                'receipt_state': 'PENDING',
                'in_memory': True,
                'ticket': item.get('ticket') is not None,
                'response': item.get('response') is not None,
            }
        with closing(connect(service.run.store.path)) as c:
            rows = c.execute('SELECT profile,oid,state,effect_state,receipt '
                             'FROM w_operation ORDER BY rowid DESC LIMIT 100').fetchall()
            # The request store lives beside W; its presence is what admits the
            # two independent entry kinds next to the server-side one.
            request_table = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_request'"
            ).fetchone() is not None
        operations = []
        seen = set()
        for row in rows:
            oid = row['oid']
            seen.add(oid)
            view = memory.get(oid) or {}
            view.update({
                'profile': row['profile'],
                'operation_id': oid,
                'state': row['state'],
                'effect_state': row['effect_state'],
                'receipt_state': 'SIGNED' if row['receipt'] else 'PENDING',
                'in_memory': oid in memory,
            })
            operations.append(view)
        for oid, view in memory.items():
            if oid not in seen:
                operations.append(view)
        return envelope('E1+E2', data={
            'profiles': list(service.run.operations),
            'endpoints': sum(len(roster) for roster in service.run.actors.values()),
            'goal_mode': service.run.w.goal_mode,
            'entry_kinds': (['server', 'ind_http', 'ind_mcp'] if request_table
                            else ['server']),
            'operations': operations,
        })

    def observe(request):
        """E3: committed observation events after a cursor, newest page."""
        from competition.server.observe import ObservationFeed
        after = _int_param(request, 'after', 0)
        limit = min(_int_param(request, 'limit', 500), 1000)
        events = ObservationFeed(service.run.store.path).events(
            after,
            limit=max(1, limit),
            profile=_text_param(request, 'profile'),
            operation_id=_text_param(request, 'operation_id'),
        )
        return envelope('E3', data={
            'events': events,
            'last': events[-1]['seq'] if events else after,
        })

    def registry(request):
        """A4: current control records without the record or certificate body."""
        namespace = _text_param(request, 'namespace')
        sql = 'SELECT namespace,key,revision,ref,active,record FROM a_current'
        args = []
        if namespace is not None:
            sql += ' WHERE namespace=?'
            args.append(namespace)
        with closing(connect(service.run.store.path)) as c:
            rows = c.execute(sql, args).fetchall()
        records = []
        for row in rows:
            record = decode(row, 'record') or {}
            records.append({
                'namespace': row['namespace'],
                'key': decode(row, 'key'),
                'revision': row['revision'],
                'ref': row['ref'],
                'active': bool(row['active']),
                'kind': record.get('kind') if isinstance(record, dict) else None,
            })
        return envelope('A4', data={'records': records})

    def db(request):
        """P1+P2+P3: one whitelisted table, redacted and paged."""
        table = request.path_params.get('table')
        require(table is not None, 'DIAG_TABLE')
        rows = table_rows(
            service.run.store,
            table,
            profile=_text_param(request, 'profile'),
            limit=_int_param(request, 'limit', 100),
            offset=_int_param(request, 'offset', 0),
        )
        return envelope('P1+P2+P3', data=rows)

    return [
        ('/api/diag/entry', entry),
        ('/api/diag/observe', observe),
        ('/api/diag/registry', registry),
        ('/api/diag/db/{table}', db),
    ]
