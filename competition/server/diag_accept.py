"""Read-only endpoints for the authorization and acceptance nodes.

Every handler reads one operation's frozen record (or the DENY coverage rows it
points at) through :mod:`competition.server.diagnostics` and returns a display
projection.  Nothing here writes a table, creates a nonce, advances the clock or
calls a service method; the HTTP layer has already required the ``auditor``
session side.
"""
from contextlib import closing

from competition.server import diagnostics
from competition.support.wire import require

# The Goal witness may carry more than this (``goals``, ``deps``); only the
# decision inputs and outputs below leave the store.
GOAL_FIELDS = ('mode', 'decision', 'reason', 'goal_refs', 'matched', 'capacity',
               'spent', 'reserved', 'candidate_cost', 'remaining_floor', 'total',
               'headroom', 'state_ref', 'check_ref')

# A commit's credential witnesses, action payload and reservation plan stay in W.
COMMIT_FIELDS = ('ctx', 'permit_ref', 'proof_ref', 'authorization_ref',
                 'review_refs', 'accept_seq', 'accepted_at', 'dispatch_before',
                 'reservation_ids')

# The lifecycle kinds A3 may observe in ``a_journal``.  Anything else is a
# different node's concern; nothing is inferred from a missing kind.
GUARD_STAGES = frozenset({'W_COMMIT', 'W_RECEIPT', 'W_CLAIM', 'W_EXEC_INTENT',
                          'W_QUERY_INTENT', 'W_SETTLE', 'W_CANCEL'})


def _time(value):
    """The bounded interval of an event witness, never its signed sample."""
    if not isinstance(value, dict):
        return None
    return {'lo': value.get('lo'), 'hi': value.get('hi')}


def _operation(store, request):
    """The path's operation id, its row and its frozen record, or OPERATION_UNKNOWN."""
    oid = request.path_params.get('oid')
    require(type(oid) is str and oid != '', 'OPERATION_UNKNOWN')
    row = diagnostics.operation_row(store, oid)
    frozen = diagnostics.decode(row, 'frozen') or {}
    return oid, row, frozen


def _observed_stages(store, profile, oid):
    """The whitelisted lifecycle kinds journaled for one operation, sorted."""
    with closing(diagnostics.connect(store.path)) as c:
        rows = c.execute('SELECT DISTINCT kind FROM a_journal '
                         'WHERE profile=? AND operation_id=?',
                         (profile, oid)).fetchall()
    return sorted({row['kind'] for row in rows if row['kind'] in GUARD_STAGES})


def routes(service):
    store = service.run.store

    def guard(request):
        oid, row, frozen = _operation(store, request)
        stages = _observed_stages(store, row['profile'], oid)
        finding = frozen.get('guard')
        if not isinstance(finding, dict) or not finding:
            return diagnostics.envelope('A3', operation_id=oid,
                                        profile=row['profile'],
                                        data={'scope': ['accept'],
                                              'observed_stages': stages})
        return diagnostics.envelope('A3', operation_id=oid, profile=row['profile'],
                                    data={'scope': ['accept'],
                                          'observed_stages': stages,
                                          'decision': finding.get('decision'),
                                          'status': finding.get('status'),
                                          'checks': finding.get('checks'),
                                          'chain_refs': finding.get('chain_refs'),
                                          'time_witness': _time(finding.get('time_witness'))})

    def plan(request):
        oid, row, frozen = _operation(store, request)
        value = frozen.get('plan')
        if not isinstance(value, dict):
            return diagnostics.envelope('A7', operation_id=oid,
                                        profile=row['profile'], data={})
        return diagnostics.envelope('A7', operation_id=oid, profile=row['profile'],
                                    data={key: value.get(key) for key in
                                          ('intent', 'amount', 'resource_key', 'unit',
                                           'taskflight', 'behavior_before',
                                           'behavior_after', 'scene_before',
                                           'scene_after')})

    def goal(request):
        oid, row, frozen = _operation(store, request)
        commit = frozen.get('commit')
        value = commit.get('value') if isinstance(commit, dict) else None
        witness = value.get('goal') if isinstance(value, dict) else None
        if not isinstance(witness, dict):
            return diagnostics.envelope('W1', operation_id=oid,
                                        profile=row['profile'],
                                        data={'applicable': False})
        return diagnostics.envelope('W1', operation_id=oid, profile=row['profile'],
                                    data={key: witness.get(key) for key in GOAL_FIELDS})

    def accept(request):
        oid, row, frozen = _operation(store, request)
        return diagnostics.envelope('W2', operation_id=oid, profile=row['profile'],
                                    data={'request_ref': row['request_ref'],
                                          'state': row['state'],
                                          'effect_state': row['effect_state'],
                                          'receipt_state': 'SIGNED' if row['receipt'] else 'PENDING',
                                          # No receipt yet: a new CLAIM is not expected to succeed.
                                          'claim_blocked': row['receipt'] is None,
                                          'accepted_at': frozen.get('accepted_at'),
                                          'trusted_time': _time(frozen.get('time_witness'))})

    def commit(request):
        oid, row, frozen = _operation(store, request)
        record = frozen.get('commit')
        value = record.get('value') if isinstance(record, dict) else None
        value = value if isinstance(value, dict) else {}
        data = {'commit_ref': frozen.get('commit_ref')}
        data.update({key: value.get(key) for key in COMMIT_FIELDS})
        return diagnostics.envelope('W3', operation_id=oid, profile=row['profile'],
                                    data=data)

    def receipt(request):
        oid, row, _ = _operation(store, request)
        signed = diagnostics.decode(row, 'receipt')
        if signed is None:
            data = {'state': 'PENDING'}
        else:
            require(isinstance(signed, dict), 'DIAG_CORRUPT')
            protected = signed.get('protected') or {}
            body = signed.get('body') or {}
            payload = body.get('payload') or {}
            data = {'state': 'SIGNED',
                    'kid': protected.get('kid'),
                    'iat': body.get('iat'),
                    'exp': body.get('exp'),
                    'commit_record_ref': payload.get('commit_record_ref')}
        return diagnostics.envelope('W4', operation_id=oid, profile=row['profile'],
                                    data=data)

    def deny(request):
        oid, row, _ = _operation(store, request)
        profile = row['profile']
        with closing(diagnostics.connect(store.path)) as c:
            ranges = c.execute('SELECT * FROM a_deny_range WHERE profile=? AND operation_id=? '
                               'ORDER BY revision DESC, basis_ref',
                               (profile, oid)).fetchall()
            if not ranges:
                data = {'complete': False, 'revision': 0, 'refs': [], 'publications': []}
            else:
                coverage = ranges[0]
                certificate = diagnostics.decode(coverage, 'root_certificate') or {}
                claim = certificate.get('claim') if isinstance(certificate, dict) else None
                claim = claim if isinstance(claim, dict) else {}
                publications = [dict(item) for item in
                                c.execute('SELECT purpose, verdict, ref FROM a_publication '
                                          'WHERE profile=? AND operation_id=? ORDER BY seq',
                                          (profile, oid))]
                data = {'complete': claim.get('complete') is True,
                        'revision': coverage['revision'],
                        'refs': sorted({item['ref'] for item in publications
                                        if item['verdict'] == 'DENY'}),
                        'publications': publications}
        return diagnostics.envelope('A5', operation_id=oid, profile=profile, data=data)

    return [('/api/diag/guard/{oid}', guard),
            ('/api/diag/plan/{oid}', plan),
            ('/api/diag/goal/{oid}', goal),
            ('/api/diag/accept/{oid}', accept),
            ('/api/diag/commit/{oid}', commit),
            ('/api/diag/receipt/{oid}', receipt),
            ('/api/diag/deny/{oid}', deny)]
