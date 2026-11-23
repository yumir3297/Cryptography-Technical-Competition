"""Build a public, offline-verifiable evidence package from one W run.

The package contains public keys, signed records, the frozen authorization chain
and the tool final fact.  It never contains private keys or a writable database.
"""
import json
import time
from pathlib import Path

from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.support.wire import b64, canonical, rec_ref


def _row(row):
    return {key: row[key] for key in row.keys()} if row is not None else None


def _json(value):
    return json.loads(value) if value is not None else None


def build_anchor(run):
    """The out-of-band trust anchor a judge must receive separately."""
    actors = {}
    for profile, roster in run.base.actors.items():
        actors[profile] = {alias: {'name': actor.name, 'kid': actor.kid,
                                   'public_key': b64(actor.pub),
                                   'roles': sorted(actor.roles),
                                   'purposes': sorted(actor.purposes)}
                           for alias, actor in roster.items()}
    return {'format': 'ZJJ-CORE-TRUST-ANCHOR-1', 'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'root_public': b64(run.store.root_public), 'actors': actors,
            'delivery_public': b64(run.delivery_public),
            'protocol': 'ZJJ-CORE-COMP-1'}


def build_package(run, profile, operation_id, *, include_all_current=True):
    require_profile(profile)
    with run.store.db() as c:
        operation = c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',
                              (profile, operation_id)).fetchone()
        if operation is None:
            raise KeyError('OPERATION_UNKNOWN')
        operation = _row(operation)
        frozen = _json(operation['frozen'])
        outbox = _row(c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',
                                (profile, operation_id)).fetchone())
        reservation = _row(c.execute('SELECT * FROM w_reservation WHERE profile=? AND oid=?',
                                     (profile, operation_id)).fetchone())
        resource_key_json = json.dumps(frozen['plan']['resource_key'], ensure_ascii=False,
                                       sort_keys=True, separators=(',', ':'))
        all_reservations = [_row(row) for row in c.execute(
            'SELECT * FROM w_reservation WHERE profile=? AND key=? ORDER BY id',
            (profile, resource_key_json))]
        resource = _row(c.execute('SELECT * FROM w_resource WHERE profile=? AND key=?',
                                  (profile, resource_key_json)).fetchone())
        resource['certificate'] = _json(resource['certificate'])
        settlement = _row(c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',
                                    (profile, operation_id)).fetchone())
        goal_links = [_row(row) for row in c.execute(
            'SELECT * FROM w_goal WHERE profile=? AND oid=? ORDER BY goal_group', (profile, operation_id))]
        goal_links_all = [_row(row) for row in c.execute(
            'SELECT * FROM w_goal WHERE profile=? ORDER BY goal_group,obligation', (profile,))]
        current_rows = [_row(row) for row in c.execute(
            'SELECT namespace,key,revision,ref,record,certificate,active FROM a_current WHERE profile=? ORDER BY namespace,key', (profile,))]
        history_rows = [row[0] for row in c.execute(
            "SELECT blob FROM a_journal WHERE profile=? AND kind='CONTROL' ORDER BY seq", (profile,))]
        tool_key_json = json.dumps([frozen['op']['action']['tool'],
                                    frozen['op']['action']['tool_version'],
                                    frozen['op']['action']['destination']],
                                   ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        tool_row = _row(c.execute('SELECT * FROM w_tool WHERE profile=? AND key=?',
                                  (profile, tool_key_json)).fetchone())
    controls = []
    for row in current_rows:
        if include_all_current or row['active']:
            controls.append({'namespace': row['namespace'], 'key': _json(row['key']),
                             'revision': row['revision'], 'ref': row['ref'],
                             'record': _json(row['record']),
                             'certificate': _json(row['certificate']),
                             'active': bool(row['active'])})
    history = {}; seen_refs = set()
    for blob in history_rows:
        fact = _json(blob); cert = fact.get('certificate')
        if not cert:
            continue
        claim = cert['claim']; ref = fact.get('ref')
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        history[ref] = {'namespace': claim['namespace'], 'key': claim['key'],
                        'revision': str(fact['revision']), 'ref': ref,
                        'record': claim['record'], 'certificate': cert,
                        'active': bool(claim['active'])}
    settlement_evidence = _json(settlement['evidence']) if settlement else None
    response = settlement_evidence
    if response is None:
        with run.store.db() as c:
            row = c.execute("SELECT blob FROM w_evidence WHERE profile=? AND oid=? AND kind='SETTLE_PROOF' ORDER BY seq DESC LIMIT 1",
                            (profile, operation_id)).fetchone()
            response = _json(row[0]) if row else None
    return {
        'format': 'ZJJ-CORE-EVIDENCE-1',
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'profile': profile,
        'operation_id': operation_id,
        'protocol': 'ZJJ-CORE-COMP-1',
        'operation': operation,
        'frozen': frozen,
        'commit': frozen['commit'],
        'commit_ref': frozen['commit_ref'],
        'acceptance_core': frozen['acceptance_core'],
        'acceptance': _json(operation['receipt']),
        'outbox': outbox,
        'reservation': reservation,
        'reservations': all_reservations,
        'resource': resource,
        'settlement': settlement,
        'settlement_evidence': response,
        'goal_links': goal_links,
        'goal_links_all': goal_links_all,
        'tool_certificate': frozen['tool_certificate'],
        'tool_trust_row': tool_row,
        'controls': controls,
        'control_history': list(history.values()),
        'root_public': b64(run.store.root_public),
        'delivery_public': b64(run.delivery_public),
        'counts': run.w.counts(),
        'manifest_note': 'W ledger totals are a trusted assertion; signatures and refs are independently checkable.',
    }


def require_profile(profile):
    if profile not in PROFILE_SCOPES:
        raise ValueError('PROFILE_UNKNOWN')
