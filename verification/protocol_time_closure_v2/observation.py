"""Candidate observation contract checker, with explicit trusted C/W premises.

Authority/Grant/History/FrozenRead/Publication are supplied by an authenticated adapter in a
real implementation. The tests provide fixed premises, NOT independent proof
of W history, governance, clock or actual atomic database behavior.
"""
import copy
import hashlib
import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator
from codec import (CheckError, require, enc, parse, b64, unb64, digest, key_id,
                   core_ref, commit_ref, action_hash, candidate_ref, fact_id,
                   to_sign, verify_signature, point_ok, MAX_OBJECT)

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {'PAY-1':'payment','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}
FILES = {'PAY-1':'pay1','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}
SCHEMA = json.loads((Path(__file__).parent/'schema.json').read_text(encoding='utf-8'))


@dataclass(frozen=True)
class Interval:
    lo: int
    hi: int


@dataclass(frozen=True)
class Grant:
    subject: str
    public_key: bytes
    profile: str
    scope_wire: bytes
    purpose: str
    role: str
    operations: tuple
    ledger_origin: str
    iat: int
    exp: int
    active: bool = True
    # iat/exp/active are the COMPLETE intersection of key, role, purpose,
    # access/delegation and fixed observer mapping, supplied by trusted C.


@dataclass(frozen=True)
class History:
    archive_wire: bytes
    ledger_origin: str
    ledger_epoch: int
    anchor_ref: str
    independent_highwater: int
    archive_validated: bool = True
    continuous: bool = True
    independent_anchor: bool = True


@dataclass(frozen=True)
class FrozenRead:
    # Trusted W lookup keyed by query_ref, not an object accepted from clients.
    query_wire: bytes
    archive_wire: bytes
    fact_wire: bytes
    snapshot_wire: bytes
    control_revision: int
    ledger_epoch: int
    anchor_ref: str


@dataclass(frozen=True)
class Publication:
    package_wire: bytes
    query_wire: bytes
    witness: FrozenRead
    publish_seq: int
    publish_time: Interval
    # Trusted W row of an atomic committed publication, never parsed from
    # client JSON. It is not a portable signed certificate by itself.


@dataclass(frozen=True)
class Authority:
    profile: str
    scope_wire: bytes
    reader: Grant | None
    observer: Grant | None
    control_revision: int
    history: History | None
    challenge_wire: bytes
    status: str = 'ACCEPTED'
    status_seq: int = 1
    time_floor: int = 0
    publications: tuple = ()
    effects: tuple = (1, 1, 0, 0)  # accept/reserve/dispatch/settle, unchanged here


def gate(iat, exp, clock, floor=0):
    if clock is None or not (0 <= clock.lo <= clock.hi and clock.hi-clock.lo <= 2 and clock.lo >= floor):
        return 'U'
    if clock.lo >= exp:
        return 'F'
    return 'T' if iat <= clock.lo and clock.hi < exp else 'U'


def current_window(iat, exp, clock, floor=0):
    truth = gate(iat, exp, clock, floor)
    require(truth == 'T', 'EXPIRED' if truth == 'F' else 'CLOCK_UNKNOWN', truth)


def _walk(value, schema, defs):
    if '$ref' in schema:
        name = schema['$ref'].split('/')[-1]
        if name in ('N','Positive','Ratio'):
            require(re.fullmatch(r'0|[1-9][0-9]*', value) is not None and int(value) <= 2**63-1, 'FORMAT')
        if name in ('B16','B32','B64'):
            unb64(value, int(name[1:]))
        if name == 'Id':
            require(re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,63}', value) is not None, 'FORMAT')
        _walk(value, defs[name], defs)
        return
    if 'x-zjj-order' in schema:
        items = [enc(x) for x in value]
        require(all(a < b for a,b in zip(items, items[1:])), 'FORMAT')
    if isinstance(value, dict):
        for k, sub in schema.get('properties', {}).items():
            if k in value:
                _walk(value[k], sub, defs)
    if isinstance(value, list):
        if isinstance(schema.get('items'), dict):
            for x in value:
                _walk(x, schema['items'], defs)
        for x, sub in zip(value, schema.get('prefixItems', [])):
            _walk(x, sub, defs)


def structural(value, schema, definition):
    selected = {'$ref':'#/$defs/'+definition, '$defs':schema['$defs']}
    require(not list(Draft202012Validator(selected).iter_errors(value)), 'FORMAT')
    _walk(value, selected, schema['$defs'])


@lru_cache(maxsize=3)
def r2_schema(profile):
    require(profile in FILES, 'FORMAT')
    s = json.loads((ROOT/'system_dev/v26/contracts'/ (FILES[profile]+'.schema.json')).read_text(encoding='utf-8'))
    core = copy.deepcopy(s['$defs']['Acceptance'])
    del core['properties']['sig']
    core['required'].remove('sig')
    s['$defs']['AcceptanceCore'] = core
    return s


def validate_archive(archive, profile):
    structural(archive, SCHEMA, 'Archive')
    core, record = archive['original_core'], archive['commit']
    require(len(enc(core)) <= MAX_OBJECT and len(enc(record)) <= MAX_OBJECT, 'FORMAT')
    s = r2_schema(profile)
    structural(core, s, 'AcceptanceCore')
    structural(record, s, 'Record_COMMIT')
    p, v = core['body']['payload'], record['value']
    scope = record['scope']
    require(core['body']['scope'] == scope == p['ctx']['scope'] == v['ctx']['scope'] == v['action']['scope'])
    require(scope['scenario'] == SCENARIOS[profile])
    for field in ('ctx','permit_ref','proof_ref','authorization_ref','review_refs','accept_seq','accepted_at','dispatch_before'):
        require(p[field] == v[field])
    require(p['commit_record_ref'] == commit_ref(record))
    require(v['action'] == v['frozen_tool_request'])
    for field in ('scope','operation_id','principal','holder','holder_kid','executor'):
        require(v['action'][field] == p['ctx'][field])
    require(p['ctx']['action_hash'] == action_hash(profile, v['action']))
    require(core['protected']['issuer'] == p['ctx']['executor'])
    original_pk = unb64(v['signing_public_key'], 32)
    require(point_ok(original_pk) and key_id(original_pk) == core['protected']['kid'])
    lo, hi = int(v['trusted_time']['lo']), int(v['trusted_time']['hi'])
    require(0 <= lo <= hi and hi-lo <= 2 and p['accepted_at'] == str(lo))
    require(core['body']['iat'] == str(lo) and 0 < int(core['body']['exp'])-lo <= 900)
    expected_refs = sorted({p['permit_ref'], p['proof_ref'], p['authorization_ref'], *p['review_refs']}, key=enc)
    require(core['body']['refs'] == expected_refs)
    deps = core['body']['deps']
    require(len({enc([d['namespace'],d['key']]) for d in deps}) == len(deps), 'FORMAT')
    return core, record


def get_history(ctx):
    h = ctx.history
    require(h is not None, 'HISTORY_UNAVAILABLE', 'U')
    require(h.archive_validated and h.continuous and h.independent_anchor, 'HISTORY_UNAVAILABLE', 'U')
    archive = parse(h.archive_wire)
    core, record = validate_archive(archive, ctx.profile)
    require(enc(record['scope']) == ctx.scope_wire)
    require(h.independent_highwater >= int(record['value']['accept_seq']), 'HISTORY_UNAVAILABLE', 'U')
    p = core['body']['payload']
    fact = {'profile':ctx.profile, 'scope':parse(ctx.scope_wire), 'operation_id':p['ctx']['operation_id'],
            'action_hash':p['ctx']['action_hash'], 'ledger_origin':h.ledger_origin,
            'accept_seq':p['accept_seq'], 'accepted_at':p['accepted_at'],
            'commit_record_ref':p['commit_record_ref'], 'original_acceptance_ref':core_ref(core),
            'original_core_digest':digest(['ZJJ-TIME-CORE-PROPOSED-v2',core])}
    structural(fact, SCHEMA, 'Fact')
    require(h.ledger_epoch > 0 and ctx.control_revision > 0)
    unb64(h.anchor_ref, 32)
    return h, archive, fact


def check_grant(grant, ctx, obj, purpose, role, operation, now):
    require(grant is not None, 'AUTHORITY_UNAVAILABLE', 'U')
    require(grant.active and grant.purpose == purpose and grant.role == role, 'CURRENT_AUTH')
    require(grant.profile == ctx.profile and grant.scope_wire == ctx.scope_wire and operation in grant.operations, 'CURRENT_AUTH')
    require(ctx.history is not None, 'HISTORY_UNAVAILABLE', 'U')
    require(grant.ledger_origin == ctx.history.ledger_origin, 'CURRENT_AUTH')
    require(obj['protected']['issuer'] == grant.subject and obj['protected']['kid'] == key_id(grant.public_key), 'CURRENT_AUTH')
    require(grant.iat < grant.exp, 'CURRENT_AUTH')
    current_window(grant.iat, grant.exp, now, ctx.time_floor)
    verify_signature(obj, grant.public_key)


def check_query(ctx, query_wire, now, *, fresh=True):
    q = parse(query_wire, MAX_OBJECT)
    structural(q, SCHEMA, 'Query')
    b = q['body']
    require(q['protected']['profile'] == ctx.profile and enc(b['scope']) == ctx.scope_wire)
    require(ctx.profile in SCENARIOS and b['scope']['scenario'] == SCENARIOS[ctx.profile])
    check_grant(ctx.reader,ctx,q,'AcceptanceObservationQuery','HOLDER',b['operation_id'],now)
    require(ctx.observer is not None, 'AUTHORITY_UNAVAILABLE', 'U')
    require(b['aud'] == [ctx.observer.subject])
    c = parse(ctx.challenge_wire)
    expected = {'issuer':q['protected']['issuer'],'kid':q['protected']['kid'],
                'operation_id':b['operation_id'],'session_id':b['session_id'],'nonce':b['nonce'],
                'attempt_id':b['attempt_id'],'aud':b['aud'],'iat':c['iat'],'exp':c['exp']}
    require(c == expected)
    require(int(b['iat']) >= int(c['iat']) and int(b['exp']) <= int(c['exp']))
    require(0 < int(b['exp'])-int(b['iat']) <= 30)
    if fresh:
        current_window(int(b['iat']),int(b['exp']),now,ctx.time_floor)
    return q


def read(ctx, query_wire, now):
    q = check_query(ctx, query_wire, now)
    require(not any(parse(p.query_wire)['body']['nonce'] == q['body']['nonce'] for p in ctx.publications), 'REPLAY')
    h, archive, fact = get_history(ctx)
    require(q['body']['operation_id'] == fact['operation_id'])
    require(ctx.status_seq >= int(fact['accept_seq']))
    snapshot = {'status':ctx.status,'status_seq':str(ctx.status_seq),
                'observed_time':{'lo':str(now.lo),'hi':str(now.hi)}}
    structural(snapshot, SCHEMA, 'Snapshot')
    return FrozenRead(query_wire,enc(archive),enc(fact),enc(snapshot),ctx.control_revision,h.ledger_epoch,h.anchor_ref)


def candidate(ctx, witness, sk, now):
    # A precomputed signature; even valid output is NOT published evidence.
    q = parse(witness.query_wire)
    require(ctx.observer is not None and ctx.reader is not None, 'AUTHORITY_UNAVAILABLE', 'U')
    require(witness.control_revision == ctx.control_revision)
    current_window(int(q['body']['iat']), int(q['body']['exp']), now, ctx.time_floor)
    snapshot = parse(witness.snapshot_wire)
    require(int(snapshot['observed_time']['hi']) <= now.lo)
    exp = min(now.lo+30,int(q['body']['exp']),ctx.reader.exp,ctx.observer.exp)
    current_window(now.lo,exp,now,ctx.time_floor)
    f = parse(witness.fact_wire)
    proof = {'protected':{'proto':'ZJJ-TIME-RESEARCH','version':'0.2','profile':ctx.profile,
                          'alg':'Ed25519','type':'AcceptanceObservation','issuer':ctx.observer.subject,
                          'kid':key_id(ctx.observer.public_key)},
             'body':{'id':q['body']['id'],'scope':parse(ctx.scope_wire),'iat':str(now.lo),'exp':str(exp),
                     'aud':[q['protected']['issuer']],'query_ref':candidate_ref(q),'query_nonce':q['body']['nonce'],
                     'fact':f,'fact_id':fact_id(f),'snapshot':snapshot,
                     'control_revision':str(witness.control_revision),'ledger_epoch':str(witness.ledger_epoch),
                     'history_anchor_ref':witness.anchor_ref}}
    proof['sig'] = b64(sk.sign(to_sign(proof)))
    package = {'format':'ZJJ-TIME-PACKAGE-PROPOSED-2','observation':proof,
               'archive':parse(witness.archive_wire)}
    structural(package, SCHEMA, 'Package')
    return enc(package)


def check_package(ctx, query_wire, package_wire, witness, now):
    q = check_query(ctx,query_wire,now)
    package = parse(package_wire)
    structural(package,SCHEMA,'Package')
    proof = package['observation']
    require(len(enc(proof)) <= MAX_OBJECT, 'FORMAT')
    b = proof['body']
    require(proof['protected']['profile'] == ctx.profile and enc(b['scope']) == ctx.scope_wire)
    check_grant(ctx.observer,ctx,proof,'AcceptanceObservation','HISTORY_OBSERVER',q['body']['operation_id'],now)
    h, archive, fact = get_history(ctx)
    require(witness.query_wire == query_wire and b['query_ref'] == candidate_ref(q) and b['query_nonce'] == q['body']['nonce'])
    require(b['aud'] == [q['protected']['issuer']])
    require(enc(package['archive']) == witness.archive_wire == enc(archive))
    require(enc(b['fact']) == witness.fact_wire == enc(fact) and b['fact_id'] == fact_id(fact))
    require(b['fact']['operation_id'] == q['body']['operation_id'])
    require(enc(b['snapshot']) == witness.snapshot_wire)
    require(int(b['snapshot']['status_seq']) >= int(fact['accept_seq']))
    interval = b['snapshot']['observed_time']
    require(0 <= int(interval['lo']) <= int(interval['hi']) <= int(b['iat']) and int(interval['hi'])-int(interval['lo']) <= 2)
    require(int(b['control_revision']) == witness.control_revision == ctx.control_revision, 'RETRY_CONFLICT', 'U')
    require(int(b['ledger_epoch']) == witness.ledger_epoch == h.ledger_epoch, 'RETRY_CONFLICT', 'U')
    require(b['history_anchor_ref'] == witness.anchor_ref == h.anchor_ref)
    require(int(b['iat']) >= int(q['body']['iat']) and 0 < int(b['exp'])-int(b['iat']) <= 30)
    require(int(b['exp']) <= min(int(q['body']['exp']),ctx.reader.exp,ctx.observer.exp))
    current_window(int(b['iat']),int(b['exp']),now,ctx.time_floor)
    return package


def publish(ctx, query_wire, package_wire, witness, now):
    # Pure simulation of the contracted W transaction. Real CAS/durability
    # is a premise, and must be implemented by the W adapter.
    q = check_query(ctx,query_wire,now,fresh=False)
    for old in ctx.publications:
        old_q = parse(old.query_wire)
        if old_q['body']['nonce'] == q['body']['nonce']:
            require(old.query_wire == query_wire, 'REPLAY')
            return ctx, old  # stored response only, never rewrite or re-sign
    check_package(ctx,query_wire,package_wire,witness,now)
    p = Publication(package_wire,query_wire,witness,len(ctx.publications)+1,now)
    after = replace(ctx,publications=ctx.publications+(p,),time_floor=max(ctx.time_floor,now.lo))
    return after, p


def receive(ctx, query_wire, package_wire, now):
    # Trusted publication must come from authenticated W authority, not
    # from package fields or a client-authored boolean.
    match = [p for p in ctx.publications if p.query_wire == query_wire and p.package_wire == package_wire]
    require(len(match) == 1, 'PUBLICATION_UNAVAILABLE', 'U')
    p = match[0]
    package = check_package(ctx,query_wire,package_wire,p.witness,now)
    # Recheck publication-time rules using the trusted archived publication
    # premise, with exact bytes pinned. This is not verification of W itself.
    b = package['observation']['body']
    require(p.publish_seq > 0 and p.publish_time.lo <= now.lo)
    current_window(int(b['iat']),int(b['exp']),p.publish_time)
    current_window(int(parse(query_wire)['body']['iat']),int(parse(query_wire)['body']['exp']),p.publish_time)
    return {'truth':'T','fact':package['observation']['body']['fact'],
            'snapshot':package['observation']['body']['snapshot'],
            'publication_digest':b64(hashlib.sha256(p.package_wire).digest()),
            'new_execution_rights':False}
