"""Phase16 IND multi-process W-to-tool delivery with simulated lost ACK.

Separates C, X, W, tool and a read-only verifier into distinct ephemeral
laboratory processes. Secrets are *known synthetic fixture seeds* and there is
no actual industrial actuator. Terminating the tool immediately AFTER durable
effect demonstrates why a W cannot safely redispatch a new attempt.
"""
from __future__ import annotations
import argparse,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase14.process_flow import (
    step as phase14_step,bootstrap as phase14_bootstrap,independent_audit as phase14_audit,
    manifest,db,tool_path,load,dump
)
from research.phase16.industrial_delivery import (
    WDispatchOutbox,AuthenticatedIndustrialGateway,public_key,DOMAIN
)
from research.phase6.trusted_final import ToolLedger
from research.phase11.run_phase11 import ROOT
from research.reference_executor.wire import (
    require,ProtocolError,strict_verify,raw,canonical,rec_ref,digest
)
from research.strict_v26.upstream_schema import UpstreamSchema

PROFILE='IND-DEMO-1'

def W_key():return Ed25519PrivateKey.from_private_bytes(b'W'*32)
def gateway(d,v):
    ledger=ToolLedger(tool_path(d),profile=PROFILE)
    return AuthenticatedIndustrialGateway(ledger,w_public=public_key(W_key()),scope=v['scope'])

def action(d,name):
    d=Path(d)
    if name=='bootstrap':
        return phase14_bootstrap(d,PROFILE)
    if name in ('c_prepare','w_prepare','x_sign','c_finalize','w_finalize','c_trust',
                'w_activate','c_claim','claim','c_settle','settle','no_redispatch'):
        return phase14_step(d,name)
    v=load(manifest(d)); ledger=ToolLedger(tool_path(d),profile=PROFILE)
    if name=='w_delivery':
        outbox=WDispatchOutbox(db(d),PROFILE,signer=W_key())
        token=outbox.issue(v['operation_id'],ledger=ledger)
        # No C/E/X secrets are given to the delivery adapter.
        v['dispatch_token']=token
        v['delivery_issue_pid']=os.getpid()
        result={'kind':'W_SIGNED_DISPATCH','packet_ref':digest([DOMAIN,token['claim']]),
                'outbox_persisted':True}
    elif name=='tool_crash':
        # The tool process exits immediately after the *committed* local effect,
        # so it writes no reply and no witness JSON update.
        gateway(d,v).deliver(v['dispatch_token'],inject='hard_after_commit')
        raise AssertionError('UNEXPECTED_TOOL_RETURN')
    elif name=='tool_recovery':
        g=gateway(d,v)
        out=g.deliver(v['dispatch_token'])
        require(not out['new_effect'],'TOOL_DUPLICATED_AFTER_LOST_ACK')
        fact=out['fact']
        signed=ledger.reattest(v['scope'],fact,
             Ed25519PrivateKey.from_private_bytes(b'Q'*32),'tool-issuer',111,2000)
        UpstreamSchema(ROOT,PROFILE).validate(signed,'Record_TOOL_FINAL')
        v['tool']={'fact':fact,'signed_final':signed,'ledger_origin':ledger.origin}
        v['stage_pids']['tool']=os.getpid()
        result={'kind':'TOOL_RECOVERED_ORIGINAL','new_effect':False,
                'tool_final_ref':rec_ref(signed),'tool_audit':g.audit()}
        v['process_stage_outcomes']['tool']=result
    else:raise ValueError(name)
    v['process_stage_outcomes'][name]=result
    dump(manifest(d),v)
    return result

def verify(d):
    d=Path(d);v=load(manifest(d))
    # Reuse the independent full accepted/dispatch/tool/settlement auditor.
    base=phase14_audit(d)
    packet=v['dispatch_token'];cl=packet['claim']
    require(cl['profile']==PROFILE and cl['scope']==v['scope'] and
            cl['operation_id']==v['operation_id'] and cl['action']==v['action'],
            'COMMAND_BINDING')
    strict_verify(public_key(W_key()),raw(packet['signature'],64),
                  canonical([DOMAIN,cl]))
    w=sqlite3.connect('file:'+str(db(d).resolve())+'?mode=ro',uri=True)
    t=sqlite3.connect('file:'+str(tool_path(d).resolve())+'?mode=ro',uri=True)
    try:
        p=w.execute('SELECT attempt,envelope FROM p16_outbox WHERE operation_id=?',
                    (v['operation_id'],)).fetchone()
        require(p is not None and p[0]==v['dispatch']['attempt'] and
                json.loads(p[1])==packet,'OUTBOX_INTEGRITY')
        actual=t.execute('SELECT packet_ref,effect_count FROM p16_authenticated_delivery WHERE operation_id=?',
                        (v['operation_id'],)).fetchone()
        require(actual is not None and actual[0]==digest([DOMAIN,cl]) and actual[1]==1,
                'AUTHENTICATED_LEDGER_FACT')
        require(t.execute('SELECT COUNT(*) FROM finalized').fetchone()[0]==1,
                'DUPLICATE_EFFECT')
        require(t.execute('SELECT seq FROM meta WHERE id=1').fetchone()[0]==1,
                'EFFECT_SEQUENCE')
    finally:w.close();t.close()
    require(v['delivery_crash']['tool_exit']==97 and
            v['process_stage_outcomes']['tool_recovery']['new_effect'] is False,
            'LOST_REPLY_RECOVERY_MISSING')
    return {**base,'phase16_gateway_integrity':True,'authenticated_tool_effects':1,
        'lost_reply_observed_exit':97,'W_outbox_verified':True,
        'no_new_effect_on_retry':True,'physical_execution_proven':False,
        'official_complete_pass':False}

def child(d,name,allow_crash=False):
    p=subprocess.run([sys.executable,'-m','research.phase16.process_flow',
                '--child',name,'--dir',str(d)],cwd=ROOT,capture_output=True,text=True,timeout=120)
    if allow_crash:
        require(p.returncode==97,'NO_SIMULATED_CRASH_AFTER_COMMIT')
        return {'stage':name,'exit_code':97,'reply_lost':True}
    if p.returncode:raise RuntimeError(f'{name} exited {p.returncode}: {p.stderr[-2500:]}')
    return json.loads(p.stdout)

def orchestrate(output):
    d=Path(output);d.mkdir(parents=True,exist_ok=True)
    # The evidence directory could have been committed by older CI runs.
    # Always discard previous SQLite snapshots before a fresh experiment.
    for entry in d.iterdir():
        if entry.is_file():entry.unlink()
    stages=[child(d,'bootstrap')]
    for name in ('c_prepare','w_prepare','x_sign','c_finalize','w_finalize',
                 'c_trust','w_activate','c_claim','claim','w_delivery'):
        stages.append(child(d,name))
    stages.append(child(d,'tool_crash',True))
    v=load(manifest(d));v['delivery_crash']={'tool_exit':97,'reply_lost':True}
    dump(manifest(d),v)
    for name in ('tool_recovery','c_settle','settle','no_redispatch'):
        stages.append(child(d,name))
    check=verify(d)
    report={'contract':'ZJJ-CORE-2.6-R2','phase':16,
          'candidate':'IND_AUTHENTICATED_DELIVERY_AFTER_COMMIT_REPLY_LOSS',
          'profile':PROFILE,'official_complete_pass':False,
          'steps':stages,'readonly_audit':check,
          'witness_sha256':hashlib.sha256(manifest(d).read_bytes()).hexdigest(),
          'limitations':['fixture W/C/X/tool signing seeds are known and unprotected',
            'no hardware actuator connected; effect is a SQLite simulation',
            'separate processes do not establish real independent OS key custody',
            'transport uses local files not authenticated network/mTLS',
            'original official 39 scenarios not fully covered']}
    dump(d/'phase16_process_report.json',report)
    return report

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--child');ap.add_argument('--dir');ap.add_argument('--output')
    a=ap.parse_args()
    if a.child:out=action(a.dir,a.child)
    else:out=orchestrate(a.output or '/tmp/zjj_phase16_ind')
    print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':main()
