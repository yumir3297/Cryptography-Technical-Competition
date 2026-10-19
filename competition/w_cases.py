"""Reusable real-process competition recovery cases and public evidence snapshots.

Private key files are read only by the controlled local test bootstrap. Exported
JSON contains public keys, certificates, messages and ledger rows, never secrets.
"""
import copy
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from competition.support.wire import (Identity,ProtocolError,require,b64,raw,canonical,
    keyid,digest)
from competition.support.final_fact import final_fact_id,final_sign_bytes
from competition.tools.common_tool import ToolGateway


def tool_snapshot(run,profile):
    """Independent public read of the tool's persisted business tables."""
    uri=Path(run.tools[profile]['database']).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as c:
        c.row_factory=sqlite3.Row
        m=dict(c.execute('SELECT profile,ledger_id,ledger_origin,high_water,ledger_head FROM tool_meta WHERE id=1').fetchone())
        facts=[dict(r) for r in c.execute('SELECT * FROM tool_finalfacts ORDER BY final_seq')]
        requests=[dict(r) for r in c.execute('SELECT * FROM tool_requests ORDER BY operation_id')]
        for r in facts:r['fact']=json.loads(r['fact'])
        for r in requests:r['claim']=json.loads(r['claim'])
        effects={}
        for table in ('payments','industrial_routes','medical_orders'):
            effects[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY operation_id')]
            for r in effects[table]:r['payload']=json.loads(r['payload'])
    return {'meta':m,'requests':requests,'finalfacts':facts,'effects':effects,
            'effect_count':sum(len(rows) for rows in effects.values())}


def public_snapshot(run,profile,oid):
    """W and independent-tool facts suitable for a JSON evidence package."""
    with run.store.db() as c:
        op=dict(c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',(profile,oid)).fetchone())
        frozen=json.loads(op.pop('frozen'))
        for field in ('receipt','observed_fact'):
            if op[field]:op[field]=json.loads(op[field])
        resources=[dict(r) for r in c.execute('SELECT profile,key,unit,capacity,reserved,spent,revision FROM w_resource WHERE profile=? ORDER BY key',(profile,))]
        reservations=[dict(r) for r in c.execute('SELECT * FROM w_reservation WHERE profile=? AND oid=? ORDER BY id',(profile,oid))]
        flights=[dict(r) for r in c.execute('SELECT * FROM w_flight WHERE profile=? AND oid=?',(profile,oid))]
        outbox=dict(c.execute('SELECT profile,oid,state,attempt_id,exec_marker,send_observed,queries FROM w_outbox WHERE profile=? AND oid=?',(profile,oid)).fetchone())
    tool=tool_snapshot(run,profile)
    return {'profile':profile,'operation_id':oid,'operation':op,'commit_ref':frozen['commit_ref'],
        'commit':frozen['commit'],'acceptance_core':frozen['acceptance_core'],'counts':run.w.counts(),
        'resources':resources,'reservations':reservations,'flights':flights,'outbox':outbox,
        'tool':tool,'effect_count':tool['effect_count']}


def accept_operation(run,profile,op=None):
    op=op or run.operations[profile]
    ticket=run.w.prepare(profile,op,run.identity_proof(profile,op))
    result=run.w.accept(profile,ticket['ticket_id'],run.accept_proof(profile,ticket['ticket_id']))
    require(result['acceptance_state']=='COMMITTED' and result['acceptance'] is not None,'CASE_RECEIPT_PENDING')
    return op['action']['operation_id'],result


def _configure_tool(run,profile,**flags):
    """Fixed trusted-fixture configuration, outside all protocol input."""
    path=Path(run.tools[profile]['config_path'])
    config=json.loads(path.read_text(encoding='utf-8'));config.update(flags)
    path.write_text(json.dumps(config,ensure_ascii=False,sort_keys=True),encoding='utf-8')
    run.tool_gateways[profile]=ToolGateway(path)


def lost_ack(run,profile):
    oid,accepted=accept_operation(run,profile)
    claim=run.w.claim(profile,oid,run.worker_proof(profile,oid,'CLAIM'))
    _configure_tool(run,profile,crash_after_commit=True)
    lost=run.w.execute_once(profile,oid,run.worker_proof(profile,oid,'EXECUTE'))
    saved=tool_snapshot(run,profile)['finalfacts'][0]
    before_retry=run.w.counts()
    retry=run.w.execute_once(profile,oid,run.worker_proof(profile,oid,'EXECUTE'))
    after_retry=run.w.counts()
    query=run.w.query_attempt(profile,oid,run.worker_proof(profile,oid,'QUERY'))
    before_settlement=run.w.counts()
    settled=run.w.settle(profile,oid,query,run.worker_proof(profile,oid,'SETTLE'))
    repeated=run.w.settle(profile,oid,query,run.worker_proof(profile,oid,'SETTLE'))
    after=public_snapshot(run,profile,oid)
    return {'profile':profile,'operation_id':oid,'commit_ref':after['commit_ref'],
        'attempt_id':claim['attempt_id'],'lost_ack':lost,'retry':retry,'before_retry':before_retry,
        'after_retry':after_retry,'persisted_fact_id':saved['final_fact_id'],'query':query,
        'query_fact_id':final_fact_id(query['record']),'before_settlement':before_settlement,
        'settlement':settled,'repeated_settlement':repeated,'after_settlement':run.w.counts(),
        'effect_count':after['effect_count'],'snapshot':after}


def unknown_query(run,profile):
    oid,_=accept_operation(run,profile)
    claim=run.w.claim(profile,oid,run.worker_proof(profile,oid,'CLAIM'))
    _configure_tool(run,profile,drop_before_tool=True)
    lost=run.w.execute_once(profile,oid,run.worker_proof(profile,oid,'EXECUTE'))
    before=public_snapshot(run,profile,oid)
    query=run.w.query_attempt(profile,oid,run.worker_proof(profile,oid,'QUERY'))
    settlement=run.w.settle(profile,oid,query,run.worker_proof(profile,oid,'SETTLE'))
    after=public_snapshot(run,profile,oid)
    return {'profile':profile,'operation_id':oid,'attempt_id':claim['attempt_id'],'lost':lost,
            'query':query,'settlement':settlement,'before':before,'after':after}


def concurrent_claim_and_settle(run,profile,workers=8):
    oid,_=accept_operation(run,profile)
    proofs=[run.worker_proof(profile,oid,'CLAIM') for _ in range(workers)]
    with ThreadPoolExecutor(workers) as pool:
        claims=list(pool.map(lambda proof:run.w.claim(profile,oid,proof),proofs))
    response=run.w.execute_once(profile,oid,run.worker_proof(profile,oid,'EXECUTE'))
    proofs=[run.worker_proof(profile,oid,'SETTLE') for _ in range(workers)]
    with ThreadPoolExecutor(workers) as pool:
        settlements=list(pool.map(lambda proof:run.w.settle(profile,oid,response,proof),proofs))
    return {'profile':profile,'operation_id':oid,'attempt_ids':[r['attempt_id'] for r in claims],
        'final_fact_ids':[r['final_fact_id'] for r in settlements], 'response':response,
        'claims':claims,'settlements':settlements,'after':public_snapshot(run,profile,oid)}


def _test_sign_final(run,profile,response):
    """Explicit controlled test evidence, never a claimed new simulator effect."""
    response=copy.deepcopy(response)
    key=Ed25519PrivateKey.from_private_bytes(Path(run.tools[profile]['key_path']).read_bytes())
    record=response['record'];record['value']['attestation']['sig']=b64(key.sign(final_sign_bytes(record)))
    response['checkpoint']['claim']['final_fact_id']=final_fact_id(record)
    claim=response['checkpoint']['claim']
    response['checkpoint']['signature']=b64(key.sign(canonical(['COMP-TOOL-CHECKPOINT-v1',claim])))
    response['controlled_test_evidence']=True
    return response


def bad_and_conflicting_final(run,profile):
    oid,_=accept_operation(run,profile)
    run.w.claim(profile,oid,run.worker_proof(profile,oid,'CLAIM'))
    response=run.w.execute_once(profile,oid,run.worker_proof(profile,oid,'EXECUTE'))
    before_bad=public_snapshot(run,profile,oid);rejected=[]
    bad=copy.deepcopy(response);bad['record']['value']['attestation']['sig']=b64(b'\x00'*64)
    bads=[bad]
    wrong_attempt=copy.deepcopy(response);wrong_attempt['record']['value']['dispatch_attempt']=b64(b'x'*16)
    bads.append(_test_sign_final(run,profile,wrong_attempt))
    wrong_ledger=copy.deepcopy(response);wrong_ledger['record']['value']['ledger_id']='wrong-ledger'
    bads.append(_test_sign_final(run,profile,wrong_ledger))
    for bad in bads:
        try:run.w.settle(profile,oid,bad,run.worker_proof(profile,oid,'SETTLE'))
        except ProtocolError as exc:rejected.append(exc.code)
        else:rejected.append('UNEXPECTEDLY_ACCEPTED')
    after_bad=public_snapshot(run,profile,oid)
    before_conflict=public_snapshot(run,profile,oid)
    conflict=copy.deepcopy(response);conflict['record']['value']['effect_id']='controlled-conflicting-effect'
    conflict['checkpoint']['claim']['ledger_head']=digest(['CONTROLLED-CONTRADICTION-TEST',final_fact_id(response['record'])])
    conflict=_test_sign_final(run,profile,conflict)
    result=run.w.settle(profile,oid,conflict,run.worker_proof(profile,oid,'SETTLE'))
    after_conflict=public_snapshot(run,profile,oid)
    return {'profile':profile,'operation_id':oid,'before_bad':before_bad,'rejected':rejected,
        'after_bad':after_bad,'original_response':response,'controlled_contradictory_response':conflict,
        'before_conflict':before_conflict,'conflict_result':result,'after_conflict':after_conflict}


def save_recovery_fixture(run,path=None):
    """Save public bootstrap provenance; existing key files remain path-only."""
    path=Path(path or (run.folder/'recovery-public.json')).resolve()
    actors={p:{alias:{'name':a.name,'public_key':b64(a.pub),'kid':a.kid,
        'roles':sorted(a.roles),'purposes':sorted(a.purposes)} for alias,a in roster.items()}
        for p,roster in run.actors.items()}
    value={'folder':str(run.folder),'root_public':b64(run.store.root_public),
        'actors':actors,'operations':run.operations,'worker_certificate':run.worker_certificate,
        'tools':run.tools,'delivery_public':b64(run.delivery_public),'delivery_key_path':run.delivery_key_path,
        'simulation_fixture':True}
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,sort_keys=True)
    return str(path)


def recover_fixture(path):
    """Rebuild clients against existing authentic ledgers; never initialize/reset."""
    from competition.core.trusted_state import TrustedState
    from competition.core.signing import ClockClient
    from competition.core.common_receipt import CommonReceiptSigner
    from competition.core.common_w import CommonW
    from competition.core.authorization import AuthorizationService
    from competition.core.signer_broker import ScopedSignerBroker
    from competition.profiles.authorization_seed import AuthorizationRun
    from competition.profiles.w_seed import WRun
    meta=json.loads(Path(path).read_text(encoding='utf-8'));folder=Path(meta['folder']).resolve()
    require(meta.get('simulation_fixture') is True and (folder/'auth-w.sqlite').is_file(),'RECOVERY_FIXTURE')
    # This is an owned bootstrap fixture, with public metadata independently
    # pinned to every original key before constructing any transport client.
    root=Ed25519PrivateKey.from_private_bytes((folder/'C.key').read_bytes())
    rootpub=root.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    require(b64(rootpub)==meta['root_public'],'RECOVERY_ROOT')
    actors={}
    for profile,roster in meta['actors'].items():
        actors[profile]={}
        for alias,public in roster.items():
            actor=object.__new__(Identity)
            actor.key=Ed25519PrivateKey.from_private_bytes((folder/(profile+'-'+alias+'.key')).read_bytes())
            actor.pub=actor.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
            actor.kid=keyid(actor.pub);actor.name=public['name']
            actor.roles=frozenset(public['roles']);actor.purposes=frozenset(public['purposes'])
            require(actor.kid==public['kid'] and b64(actor.pub)==public['public_key'],'RECOVERY_ACTOR')
            actors[profile][alias]=actor
    worker=Ed25519PrivateKey.from_private_bytes((folder/'W-worker.key').read_bytes())
    require(b64(worker.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))==meta['worker_certificate']['claim']['public_key'],'RECOVERY_WORKER')
    delivery=Ed25519PrivateKey.from_private_bytes(Path(meta['delivery_key_path']).read_bytes())
    delivery_public=delivery.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    require(b64(delivery_public)==meta['delivery_public'] and delivery_public!=worker.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),'RECOVERY_DELIVERY')
    with closing(sqlite3.connect((folder/'auth-w.sqlite').as_uri()+'?mode=ro',uri=True)) as c:
        boot=c.execute("SELECT blob FROM a_journal WHERE kind='W_BOOTSTRAP' ORDER BY seq LIMIT 1").fetchone()
        require(boot is not None and json.loads(boot[0])['worker']==meta['worker_certificate'],'RECOVERY_BOOTSTRAP')
    clock=ClockClient(folder/'C.key',folder/'c-clock.sqlite');signers={}
    try:
        store=TrustedState(folder/'auth-w.sqlite',rootpub,actors,clock)
        base=AuthorizationRun(folder,root,actors,clock,store,AuthorizationService(store),ScopedSignerBroker(store,actors),meta['operations'])
        tools=meta['tools'];gateways={}
        for profile,info in tools.items():
            require(Path(info['database']).is_file(),'CONTINUITY_UNKNOWN')
            gateways[profile]=ToolGateway(info['config_path'])
            signers[profile]=CommonReceiptSigner(folder/(profile+'-X.key'),store.path,rootpub,profile)
        w=CommonW(store,delivery,meta['worker_certificate'],signers,gateways)
        tool_keys={p:Ed25519PrivateKey.from_private_bytes(Path(info['key_path']).read_bytes()) for p,info in tools.items()}
        configs={p:info['config_path'] for p,info in tools.items()}
        return WRun(base,w,worker,meta['worker_certificate'],signers,gateways,tools,tool_keys,configs,delivery_public,meta['delivery_key_path'])
    except BaseException:
        for signer in signers.values():signer.close()
        clock.close();raise


def w_commit_crash(run,profile):
    # A fresh genuine signed chain avoids reusing an elapsed 30-second proof
    # across child bootstrap startup; the shared current C business source stays.
    op=run.fork_operation(profile)
    ticket=run.w.prepare(profile,op,run.identity_proof(profile,op))
    proof=run.accept_proof(profile,ticket['ticket_id']);oid=op['action']['operation_id']
    metadata=save_recovery_fixture(run)
    p=subprocess.Popen([sys.executable,'-m','competition.w_cases','crash-accept',metadata,profile,ticket['ticket_id']],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
        cwd=str(Path(__file__).resolve().parents[1]))
    output,_=p.communicate(json.dumps(proof),timeout=30)
    crash={'pid':p.pid,'exit_code':p.returncode,'started':True,'output':output}
    before=public_snapshot(run,profile,oid)
    recovered=recover_fixture(metadata)
    try:
        receipt=recovered.w.complete_receipt(profile,oid)
        after=public_snapshot(recovered,profile,oid)
        returned=receipt['acceptance']
        core={k:returned[k] for k in ('protected','body')} if returned else None
    finally:recovered.close()
    return {'profile':profile,'operation_id':oid,'crash':crash,'before_receipt':before,
        'after_receipt':after,'frozen_core':before['acceptance_core'],'returned_core':core,
        'metadata_path':metadata}


if __name__=='__main__':
    require(len(sys.argv)==5 and sys.argv[1]=='crash-accept','CASE_COMMAND')
    recovered=recover_fixture(sys.argv[2])
    try:recovered.w.accept(sys.argv[3],sys.argv[4],json.loads(sys.stdin.read()),crash_after_commit=True)
    finally:recovered.close()
