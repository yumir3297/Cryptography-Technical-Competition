"""Persistent IND simulator host. No participant/worker signing helper is loaded.

Provisioning and approvals belong to the separately invoked controlled demo
operator. Same-user processes do not establish OS credential isolation.
"""
import argparse
from contextlib import contextmanager, closing
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from competition.application.http_service import create_server, parse_json
from competition.application.operation_orchestrator import OperationOrchestrator
from competition.application.operation_service import OperationService
from competition.application.request_bound_w import RequestBoundW
from competition.application.trusted_action_resolver import TrustedActionResolver, PROFILE
from competition.core.common_receipt import CommonReceiptSigner
from competition.core.common_w import CommonW
from competition.core.signing import ClockClient
from competition.core.trusted_state import TrustedState, PublicActor
from competition.support.tool_final import verify_certificate
from competition.support.wire import b64, raw, keyid, canonical, strict_verify, require, ProtocolError
from competition.tools.common_tool import ToolGateway

FIELDS={'version','mode','profile','host','port','runtime_dir','task_id',
        'root_public','actors','worker_certificate','delivery_public'}
STATE_TABLES=frozenset(('a_current','a_journal','a_deny_range','a_publication',
    'a_sign_call','a_identity','a_guard_fact','comp_event_clock','app_request',
    'w_meta','w_ticket','w_operation','w_intent','w_consumed','w_mutable','w_resource',
    'w_reservation','w_flight','w_outbox','w_nonce','w_tool','w_settlement','w_evidence'))
TOOL_TABLES=frozenset(('tool_meta','tool_requests','tool_finalfacts','tool_clock_sessions',
                       'payments','industrial_routes','medical_orders'))

def _schema(c, required):
    names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(required<=names,'DEPLOYMENT_SCHEMA')

def _private(path, *, directory=False):
    path=Path(path)
    require(not path.is_symlink() and path.exists(),'DEPLOYMENT_FILE_MISSING')
    info=path.stat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==(0o700 if directory else 0o600),
            'DEPLOYMENT_PERMISSIONS')
    return path

@contextmanager
def _read_db(path):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        require(c.execute('PRAGMA quick_check').fetchone()[0]=='ok','STATE_INTEGRITY')
        yield c

def inspect_config(path):
    path=Path(path).absolute();_private(path)
    path=path.resolve();_private(path.parent,directory=True)
    cfg=parse_json(path.read_bytes())
    require(type(cfg) is dict and set(cfg)==FIELDS and type(cfg['version']) is int and
            cfg['version']==1 and cfg['mode']=='local-industrial-simulator' and
            cfg['profile']==PROFILE,'DEPLOYMENT_CONFIG')
    require(cfg['host']=='127.0.0.1' and type(cfg['port']) is int and
            0<=cfg['port']<=65535,'LOCAL_BINDING_REQUIRED')
    raw(cfg['task_id'],16)
    state=Path(cfg['runtime_dir'])
    require(state.is_absolute() and state==path.parent/'runtime','DEPLOYMENT_PATH')
    _private(state,directory=True)
    for name in ('auth-w.sqlite','c-clock.sqlite','C.key','IND-DEMO-1-X.key',
                 'W-delivery.key','IND-DEMO-1-tool.key','IND-DEMO-1-tool.sqlite','IND-DEMO-1-tool.json'):
        _private(state/name)
    token=_private(path.parent/'transport-token').read_text().strip()
    require(32<=len(token)<=256 and token.isascii() and
            not any(x.isspace() for x in token),'TRANSPORT_TOKEN_REQUIRED')
    raw(cfg['root_public'],32);raw(cfg['delivery_public'],32)
    cert=cfg['worker_certificate']
    strict_verify(raw(cfg['root_public'],32),raw(cert['signature'],64),
                  canonical(['COMP-W-WORKER-GRANT-v1',cert['claim']]))
    expected={'worker':cert,'delivery_public':cfg['delivery_public']}
    with _read_db(state/'auth-w.sqlite') as c:
        _schema(c,STATE_TABLES)
        require(c.execute('SELECT 1 FROM w_meta WHERE id=1').fetchone() is not None and
                c.execute('SELECT 1 FROM comp_event_clock WHERE id=1').fetchone() is not None,
                'DEPLOYMENT_SCHEMA')
        boot=c.execute("SELECT blob FROM a_journal WHERE kind='W_BOOTSTRAP' ORDER BY seq LIMIT 1").fetchone()
        require(boot is not None,'RECOVERY_BOOTSTRAP')
        saved=json.loads(boot['blob'])
        require(all(saved[k]==v for k,v in expected.items()),'W_BOOTSTRAP_CONFLICT')
        tools=c.execute('SELECT * FROM w_tool WHERE profile=?',(PROFILE,)).fetchall()
        require(len(tools)==1,'TOOL_BINDING')
        tool=dict(tools[0])
    with _read_db(state/'c-clock.sqlite') as c:
        _schema(c,{'source_sequence'})
        require(c.execute('SELECT 1 FROM source_sequence WHERE id=1').fetchone() is not None,
                'DEPLOYMENT_SCHEMA')
    tool_cfg=parse_json((state/'IND-DEMO-1-tool.json').read_bytes())
    tool_fields={'database','profile','certificate','root_public','w_public',
                 'tool_key_path','clock_key_path','clock_database'}
    require(set(tool_cfg)==tool_fields and tool_cfg['profile']==PROFILE and
            tool_cfg['certificate']==json.loads(tool['certificate']) and
            tool_cfg['root_public']==cfg['root_public'] and tool_cfg['w_public']==cfg['delivery_public'],
            'TOOL_BINDING')
    for field,name in {'database':'IND-DEMO-1-tool.sqlite','tool_key_path':'IND-DEMO-1-tool.key',
                       'clock_key_path':'C.key','clock_database':'c-clock.sqlite'}.items():
        require(tool_cfg[field]==str(state/name),'DEPLOYMENT_PATH')
    trust=verify_certificate(tool_cfg['certificate'],raw(cfg['root_public'],32),PROFILE)
    with _read_db(state/'IND-DEMO-1-tool.sqlite') as c:
        _schema(c,TOOL_TABLES)
        meta=c.execute('SELECT * FROM tool_meta WHERE id=1').fetchone()
        require(meta is not None and meta['profile']==PROFILE and
                meta['ledger_id']==trust['value']['ledger_id'] and
                meta['ledger_origin']==tool['origin']==tool_cfg['certificate']['claim']['ledger_origin'],
                'CONTINUITY_UNKNOWN')
        require(meta['certificate'] is None or json.loads(meta['certificate'])==tool_cfg['certificate'],
                'TOOL_TRUST_CHANGED')
    return cfg

class LocalRuntime:
    def __init__(self, config, store, clock, signer, w, service):
        self.config,self.store,self.clock,self.signer,self.w,self.service=config,store,clock,signer,w,service

@contextmanager
def open_runtime(config_path):
    cfg=inspect_config(config_path);state=Path(cfg['runtime_dir'])
    clock=signer=None
    lock=(state/'service.lock').open('a')
    os.chmod(state/'service.lock',0o600)
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ProtocolError('SERVICE_ALREADY_RUNNING')
        tool_path=state/'IND-DEMO-1-tool.json'
        try:
            probe=subprocess.run([sys.executable,'-m','competition.deployment.tool_probe',str(tool_path)],
                                 capture_output=True,text=True,timeout=8)
            info=json.loads(probe.stdout)
        except (subprocess.SubprocessError,ValueError) as exc:
            raise ProtocolError('RECOVERY_TOOL') from exc
        trust=json.loads(tool_path.read_text())['certificate']['claim']['record']['value']
        require(probe.returncode==0 and type(info) is dict and
                info.get('profile')==PROFILE and info.get('public_key')==trust['public_key'] and
                info.get('kid')==trust['kid'],'RECOVERY_TOOL')
        roster={}
        for p,actors in cfg['actors'].items():
            roster[p]={}
            for a,v in actors.items():
                pub=raw(v['public_key'],32);require(keyid(pub)==v['kid'],'ROSTER_KEY')
                roster[p][a]=PublicActor(v['name'],v['kid'],pub,frozenset(v['roles']),frozenset(v['purposes']))
        key=Ed25519PrivateKey.from_private_bytes((state/'W-delivery.key').read_bytes())
        require(b64(key.public_key().public_bytes_raw())==cfg['delivery_public'],'RECOVERY_DELIVERY')
        clock=ClockClient(state/'C.key',state/'c-clock.sqlite')
        store=TrustedState(state/'auth-w.sqlite',raw(cfg['root_public'],32),roster,clock)
        signer=CommonReceiptSigner(state/'IND-DEMO-1-X.key',store.path,store.root_public,PROFILE)
        executor=store.actors[PROFILE]['X']
        require(signer.info['kid']==executor.kid and
                raw(signer.info['public_key'],32)==executor.pub,'RECOVERY_EXECUTOR')
        core=CommonW(store,key,cfg['worker_certificate'],{PROFILE:signer},
                     {PROFILE:ToolGateway(state/'IND-DEMO-1-tool.json')})
        resolver=TrustedActionResolver(store,cfg['task_id'])
        w=RequestBoundW(core,resolver.requests)
        service=OperationService(resolver,OperationOrchestrator(w,resolver.requests))
        yield LocalRuntime(cfg,store,clock,signer,w,service)
    finally:
        if signer:signer.close()
        if clock:clock.close()
        lock.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    config=Path(args.config).absolute()
    try:
        if args.check:
            with open_runtime(config) as runtime:
                cfg=runtime.config
                print(json.dumps({'ok':True,'profile':cfg['profile'],'host':cfg['host'],'port':cfg['port'],
                                  'task_id':cfg['task_id'],'mode':cfg['mode'],'component_bindings':True}))
            return
        previous=os.umask(0o077)
        try:
            with open_runtime(config) as runtime:
                token=(config.parent/'transport-token').read_text().strip()
                server=create_server(runtime.service,token,host=runtime.config['host'],port=runtime.config['port'])
                ready=config.parent/'service-ready.json'
                value={'pid':os.getpid(),'url':'http://127.0.0.1:'+str(server.server_port),
                       'profile':PROFILE,'task_id':runtime.config['task_id'],
                       'clock_pid':runtime.clock.proc.pid,'receipt_pid':runtime.signer.proc.pid}
                temp=config.parent/('service-ready.'+str(os.getpid())+'.tmp')
                with temp.open('x') as stream:json.dump(value,stream)
                os.replace(temp,ready)
                def stop(*_):raise SystemExit(0)
                signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
                print(json.dumps({'ready':True,**value}),flush=True)
                try:server.serve_forever(poll_interval=.1)
                finally:
                    server.server_close()
                    if ready.exists() and json.loads(ready.read_text())['pid']==os.getpid():ready.unlink()
        finally:os.umask(previous)
    except (ProtocolError,OSError,ValueError,KeyError,sqlite3.Error) as exc:
        print(json.dumps({'ready':False,'error':getattr(exc,'code','DEPLOYMENT_UNAVAILABLE')}),flush=True)
        raise SystemExit(1)

if __name__=='__main__':main()
