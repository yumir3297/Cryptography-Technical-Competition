"""PUBLIC TEST KEYS and synthetic trusted inputs; never real W/C evidence.

R2 structural templates contain placeholder refs. Here Core/COMMIT/Action
bindings are made consistent. Full historical authorization is an explicit
test premise, not inferred from these templates or their signatures.
"""
import copy
import json
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from codec import enc, b64, digest, key_id, action_hash, commit_ref, to_sign
from observation import Grant, History, Authority, Interval, read, candidate, publish

ROOT = Path(__file__).resolve().parents[2]


def public(sk):
    return sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)


def fixture(profile='PAY-1', now=1100, observer_seed=51, query_id=4):
    # All seeds explicitly public test material. Original private key is
    # deliberately not returned; recovery uses current observer key only.
    old = Ed25519PrivateKey.from_private_bytes(bytes([17])*32)
    holder = Ed25519PrivateKey.from_private_bytes(bytes([34])*32)
    observer = Ed25519PrivateKey.from_private_bytes(bytes([observer_seed])*32)
    v = json.loads((ROOT/'system_dev/v26/vectors/wire_vectors.json').read_text(encoding='utf-8'))
    record = copy.deepcopy(next(x['record'] for x in v['records'] if x['id']==profile+':Record_COMMIT'))
    envelope = copy.deepcopy(next(x['envelope'] for x in v['envelopes'] if x['id']==profile+':Acceptance'))
    core = {'protected':envelope['protected'],'body':envelope['body']}
    scope = record['scope']
    ctx = record['value']['ctx']
    ctx.update(scope=scope,holder='holder',holder_kid=key_id(public(holder)),executor='executor')
    a = record['value']['action']
    for field in ('scope','operation_id','principal','holder','holder_kid','executor'):
        a[field] = ctx[field]
    ctx['action_hash'] = action_hash(profile,a)
    rec = record['value']
    rec.update(ctx=ctx,action=a,frozen_tool_request=copy.deepcopy(a),accepted_at='100',
               accept_seq='1',trusted_time={'lo':'100','hi':'100'},dispatch_before='120',
               signing_public_key=b64(public(old)))
    core['protected'].update(issuer='executor',kid=key_id(public(old)))
    p = core['body']['payload']
    for field in ('ctx','permit_ref','proof_ref','authorization_ref','review_refs','accept_seq','accepted_at','dispatch_before'):
        p[field] = copy.deepcopy(rec[field])
    p['commit_record_ref'] = commit_ref(record)
    core['body'].update(scope=scope,iat='100',exp='1000',aud=sorted(['holder','gateway','approver'],key=enc),
                        refs=sorted({p['permit_ref'],p['proof_ref'],p['authorization_ref'],*p['review_refs']},key=enc))
    archive = {'format':'ZJJ-CORE-ARCHIVE-PROPOSED-2','original_core':core,'commit':record}
    op = ctx['operation_id']
    reader = Grant('holder',public(holder),profile,enc(scope),'AcceptanceObservationQuery','HOLDER',(op,),'research-ledger',0,2000)
    writer = Grant('observer',public(observer),profile,enc(scope),'AcceptanceObservation','HISTORY_OBSERVER',(op,),'research-ledger',0,2000)
    q = {'protected':{'proto':'ZJJ-TIME-RESEARCH','version':'0.2','profile':profile,'alg':'Ed25519',
                      'type':'AcceptanceObservationQuery','issuer':'holder','kid':key_id(public(holder))},
         'body':{'id':b64(bytes([query_id])*16),'scope':scope,'iat':str(now),'exp':str(now+30),
                 'aud':['observer'],'operation_id':op,'session_id':b64(bytes([5])*16),
                 'nonce':b64(bytes([6])*32),'attempt_id':b64(bytes([7])*16)}}
    q['sig'] = b64(holder.sign(to_sign(q)))
    c = {'issuer':'holder','kid':key_id(public(holder)),'operation_id':op,
         'session_id':q['body']['session_id'],'nonce':q['body']['nonce'],'attempt_id':q['body']['attempt_id'],
         'aud':['observer'],'iat':str(now),'exp':str(now+30)}
    h = History(enc(archive),'research-ledger',1,digest(['PUBLIC-TEST-INDEPENDENT-ANCHOR',profile]),1)
    auth = Authority(profile,enc(scope),reader,writer,1,h,enc(c))
    return auth, holder, observer, enc(q)


def published_fixture(profile='PAY-1', now=1100, observer_seed=51):
    ctx, holder, observer, query = fixture(profile,now,observer_seed)
    witness = read(ctx,query,Interval(now,now))
    package = candidate(ctx,witness,observer,Interval(now+1,now+1))
    after, row = publish(ctx,query,package,witness,Interval(now+2,now+2))
    return after, holder, observer, query, package, witness, row
