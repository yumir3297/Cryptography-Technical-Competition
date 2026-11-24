"""Read-only endpoints for construction, source, store boundary and obligations.

Every handler here is a display projection of already-committed state.  It opens
the trusted SQLite stores through :mod:`competition.server.diagnostics`
(``mode=ro`` plus ``PRAGMA query_only``) and returns an
:func:`~competition.server.diagnostics.envelope`.  Nothing writes a table,
creates a nonce, advances or samples the event clock, or calls a service method;
the HTTP layer has already required the ``auditor`` session side.

The projections deliberately keep the authority chain and its business summary
apart: an operation shows the hashes, refs and the bounded Basis/Assessment
values that a guard reads, while the Source view reduces a dependency record to
its envelope window and payload identifiers.  No full Action payload, private
key, nonce, session id or signature packet leaves the store.
"""
from contextlib import closing
from functools import partial
from pathlib import Path

from competition.server import diagnostics
from competition.support.wire import b64, require

# The Basis value fields a guard re-derives; ``action`` itself stays in W.
BASIS_FIELDS = ('action_hash', 'policy_ref', 'task_ref', 'evidence_refs',
                'required_reviews', 'deps', 'assessment_ref')
ASSESSMENT_FIELDS = ('action_hash', 'policy_ref', 'task_ref', 'evidence_refs',
                     'required_reviews', 'result', 'cutoff', 'method')

# Dependency namespaces whose records back an operation's business facts.
SOURCE_NAMESPACES = ('ORDER', 'EVIDENCE', 'INCIDENT')

# Business identifiers a payload summary may name; everything else is a key.
IDENTIFIER_FIELDS = ('order_id', 'stage', 'line_id', 'station_id',
                     'patient_id', 'synthetic_patient_id', 'encounter_id')


def _operation(store, request):
    """The path's operation id, its row, frozen record and op, or a refusal."""
    oid = request.path_params.get('oid')
    require(type(oid) is str and oid != '', 'OPERATION_UNKNOWN')
    row = diagnostics.operation_row(store, oid)
    frozen = diagnostics.decode(row, 'frozen')
    require(isinstance(frozen, dict), 'DIAG_CORRUPT')
    op = frozen.get('op')
    require(isinstance(op, dict), 'DIAG_CORRUPT')
    return oid, row, op


def _value(record):
    """The ``value`` of a protocol record, or an empty mapping."""
    value = record.get('value') if isinstance(record, dict) else None
    return value if isinstance(value, dict) else {}


def _submission_version(store, oid):
    """The current submission version of ``oid``, or ``None`` when W has none.

    ``app_request`` is application-owned and absent from a bare W.  It is read
    only when the table exists, and only its version and request ref leave.
    """
    with closing(diagnostics.connect(store.path)) as c:
        present = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='app_request'").fetchone()
        if present is None:
            return None
        columns = {row[1] for row in c.execute('PRAGMA table_info(app_request)')}
        if 'submission_version' not in columns:
            return None
        row = c.execute('SELECT submission_version,request_ref FROM app_request '
                        'WHERE oid=?', (oid,)).fetchone()
    if row is None:
        return None
    return {'submission_version': row['submission_version'],
            'request_ref': row['request_ref']}


def _source_envelope(value):
    """The public envelope window of a source record, never its signature."""
    envelope = value.get('source_envelope') if isinstance(value, dict) else None
    if not isinstance(envelope, dict):
        return None
    body = envelope.get('body')
    body = body if isinstance(body, dict) else {}
    return {'protected': envelope.get('protected'),
            'body': {key: body.get(key) for key in ('iat', 'exp', 'aud')}}


def _payload_summary(value):
    """The payload's key names plus its business identifiers, never values.

    Scene evidence keeps its business fields under ``value.data``; a PAY source
    keeps them under ``source_envelope.body.payload``.  Both reduce to the same
    summary shape.
    """
    payload = None
    envelope = value.get('source_envelope') if isinstance(value, dict) else None
    if isinstance(envelope, dict):
        body = envelope.get('body')
        payload = body.get('payload') if isinstance(body, dict) else None
    if not isinstance(payload, dict):
        payload = value.get('data') if isinstance(value, dict) else None
    if not isinstance(payload, dict):
        return None
    summary = {'keys': sorted(payload)}
    for key in IDENTIFIER_FIELDS:
        if key in payload:
            summary[key] = payload[key]
    return summary


def construct(service, request):
    """P1-06: how the frozen Action became its Basis, Assessment and selector."""
    store = service.run.store
    oid, row, op = _operation(store, request)
    profile = row['profile']
    action = op.get('action')
    require(isinstance(action, dict), 'DIAG_CORRUPT')
    from competition.core.goal_floor import action_selector
    from competition.support.wire import action_hash, rec_ref
    basis_record = op.get('basis')
    assessment_record = op.get('assessment')
    require(isinstance(basis_record, dict) and isinstance(assessment_record, dict),
            'DIAG_CORRUPT')
    basis_value = _value(basis_record)
    assessment_value = _value(assessment_record)
    data = {
        'request_ref': row['request_ref'],
        'action_hash': action_hash(profile, action),
        'selector': action_selector(profile, action),
        'ctx': op.get('ctx'),
        'basis': {
            'ref': rec_ref(basis_record),
            'iat': basis_value.get('iat'),
            'exp': basis_value.get('exp'),
            'value': {key: basis_value.get(key) for key in BASIS_FIELDS},
        },
        'assessment': {
            'ref': rec_ref(assessment_record),
            'iat': assessment_value.get('iat'),
            'exp': assessment_value.get('exp'),
            'value': {key: assessment_value.get(key) for key in ASSESSMENT_FIELDS},
        },
        'required': op.get('required'),
        'deps': op.get('deps'),
        'submission_version': _submission_version(store, oid),
    }
    return diagnostics.envelope('CONSTRUCT', operation_id=oid, profile=profile, data=data)


def source(service, request):
    """P1-07: the E-signed Source records the operation's deps point at."""
    store = service.run.store
    oid, row, op = _operation(store, request)
    profile = row['profile']
    deps = [dep for dep in (op.get('deps') or [])
            if isinstance(dep, dict) and dep.get('namespace') in SOURCE_NAMESPACES]
    from competition.core.trusted_state import enc
    source_deps = []
    sources = []
    with closing(diagnostics.connect(store.path)) as c:
        for dep in deps:
            namespace = dep['namespace']
            key = dep.get('key') if isinstance(dep.get('key'), list) else []
            ref = dep.get('ref')
            source_deps.append({'namespace': namespace, 'key': key,
                                'revision': dep.get('revision'), 'ref': ref})
            current = c.execute('SELECT revision,ref,record FROM a_current '
                                'WHERE profile=? AND namespace=? AND key=?',
                                (profile, namespace, enc(key))).fetchone()
            record = diagnostics.decode(current, 'record') if current is not None else None
            require(record is None or isinstance(record, dict), 'DIAG_CORRUPT')
            value = _value(record)
            envelope = _source_envelope(value)
            sources.append({
                'namespace': namespace,
                'key': key,
                'ref': (current['ref'] if current is not None else ref),
                'kind': record.get('kind') if isinstance(record, dict) else None,
                'source_envelope': envelope,
                'payload_summary': _payload_summary(value),
            })
    actor = service.run.store.actors[profile]['E']
    assessment_value = _value(op.get('assessment'))
    evidence_refs = assessment_value.get('evidence_refs', [])
    data = {
        'actor': {'subject': actor.name, 'kid': actor.kid,
                  'public_key': b64(actor.pub)},
        'evidence_refs': evidence_refs if isinstance(evidence_refs, list) else [],
        'source_deps': source_deps,
        'sources': sources,
    }
    return diagnostics.envelope('SOURCE', operation_id=oid, profile=profile, data=data)


def store(service, request):
    """P0-01/P0-05: the shared W/C boundary and the separate tool databases."""
    path = service.run.store.path
    with closing(diagnostics.connect(path)) as c:
        names = [row['name'] for row in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    tables = {
        'control': [name for name in names if name.startswith('a_')],
        'business': [name for name in names if name.startswith('w_')],
        'clock': [name for name in names if name == 'comp_event_clock'],
    }
    gateways = getattr(getattr(service.run, 'w', None), 'tool_gateways', {}) or {}
    databases = []
    for gateway in gateways.values():
        config = getattr(gateway, 'config', None)
        if not isinstance(config, dict) or not config.get('database'):
            continue
        name = Path(config['database']).name
        if name not in databases:
            databases.append(name)
    data = {
        'shared': {'database': Path(path).name,
                   'tables': tables,
                   'transaction': 'BEGIN IMMEDIATE'},
        'transaction': 'BEGIN IMMEDIATE',
        'tool': {'databases': databases, 'separate': True},
    }
    return diagnostics.envelope('STORE', data=data)


def obligations(service, request):
    """P0-04: one profile's GoalFloor obligations and resource ledgers."""
    profile = request.path_params.get('profile')
    require(profile in service.run.operations, 'PROFILE')
    with closing(diagnostics.connect(service.run.store.path)) as c:
        goals = [{'group': row['goal_group'], 'obligation': row['obligation'],
                  'state': row['state'], 'cost': row['cost'],
                  'goal_ref': row['goal_ref'], 'epoch': row['epoch'],
                  'oid': row['oid'], 'action': row['action']}
                 for row in c.execute('SELECT * FROM w_goal WHERE profile=? '
                                      'ORDER BY goal_group', (profile,))]
        resources = [{'key': diagnostics.decode(row, 'key'), 'unit': row['unit'],
                      'capacity': row['capacity'], 'reserved': row['reserved'],
                      'spent': row['spent'], 'revision': row['revision']}
                     for row in c.execute('SELECT * FROM w_resource WHERE profile=? '
                                          'ORDER BY key', (profile,))]
        reservations = [{'id': row['id'], 'oid': row['oid'],
                         'key': diagnostics.decode(row, 'key'),
                         'amount': row['amount'], 'state': row['state']}
                        for row in c.execute('SELECT * FROM w_reservation '
                                             'WHERE profile=? ORDER BY id', (profile,))]
    data = {'profile': profile, 'mode': service.run.w.goal_mode,
            'goals': goals, 'resources': resources, 'reservations': reservations}
    return diagnostics.envelope('OBLIGATIONS', profile=profile, data=data)


def routes(service):
    return [
        ('/api/diag/construct/{oid}', partial(construct, service)),
        ('/api/diag/source/{oid}', partial(source, service)),
        ('/api/diag/store', partial(store, service)),
        ('/api/diag/obligations/{profile}', partial(obligations, service)),
    ]
