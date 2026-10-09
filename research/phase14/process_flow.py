"""Phase14 IND/MED laboratory process isolation and independent Phase13-format audit.
External signing processes are simulated with PUBLICLY DOCUMENTED deterministic lab
fixture seeds. They are NOT production key custody or privilege separation.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase8.scene_authority import PURPOSES,ROLES
from research.phase12.authority import HardenedSceneW
from research.phase14.verifier import VerifierOnlySceneW
from research.phase6.trusted_final import Controller,ToolLedger
from research.phase11.trusted_clock import seal
from research.phase11.run_phase11 import ROOT
from research.phase13.process_flow import readonly_audit
from research.reference_executor.wire import (Identity,ProtocolError,b64,raw,require,rec_ref,msgref,sid)
from research.strict_v26.upstream_schema import UpstreamSchema

PROFILES=('IND-DEMO-1','MED-DEMO-1')
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def manifest(d):return Path(d)/'phase14_witness.json'
def db(d):return Path(d)/'w.sqlite'
def tool_path(d):return Path(d)/'tool.sqlite'
def _key():return Ed25519PrivateKey.from_private_bytes(b'\\x45'*32)
def c():return Controller(Ed25519PrivateKey.from_private_bytes(bytes([0x45])*32))
def _w(d,v):
    roster={k:SimpleNamespace(name=x['name'],kid=x['kid'],pub=raw(x['pub'],32),
                 roles=frozenset(x['roles']),purposes=frozenset(x['purposes']))
                 for k,x in v['fixture_actor_public'].items()}
    w=VerifierOnlySceneW(db(d),v['profile'],root_public=raw(v['fixture_root_public'],32),actors=roster)
    require(not hasattr(w.controller,'sign') and all(not hasattr(x,'key') for x in w.actors.values()),'PRIVATE_KEY_IN_W')
    return w

def bootstrap(d,profile):
    d=Path(d);d.mkdir(parents=True,exist_ok=True)
    issuer,action,task,sk,ev=build_scene(db(d),profile,authority_class=HardenedSceneW)
    op=prepare_approved(issuer,action,task,sk)
    a={k:{'name':x.name,'kid':x.kid,'pub':b64(x.pub),'roles':sorted(x.roles),
           'purposes':sorted(x.purposes)} for k,x in issuer.actors.items()}
    signed={'permit':op['permit'],'issue':op['issue'],'challenge_request':op['challenge_request'],
         'challenge':op['challenge'],'proof':op['proof'],'authorization':op['authorization']}
    for i,r in enumerate(op['reviews']):signed['review_'+str(i)]=r
    v={'profile':profile,'scope':issuer.scope,'action':action,'operation_id':action['operation_id'],
       'fixture_root_public':b64(issuer.root_public),'fixture_actor_public':a,
       'op':op,'signed_messages':signed,'process_stage_outcomes':{},'stage_pids':{'bootstrap':os.getpid()},
       'official_complete_pass':False,'signer_key_custody':'deterministic_insecure_fixtures'}
    dump(manifest(d),v)
    return {'stage':'bootstrap','profile':profile,'private_keys_exported_to_W':False}

def step(d,name):
    d=Path(d);v=load(manifest(d));p=v['profile'];oid=v['operation_id'];op=v['op']
    if name.startswith('c_'):
        purpose={'c_prepare':'PREPARE','c_finalize':'FINALIZE','c_claim':'DISPATCH','c_settle':'SETTLE'}.get(name)
        if purpose:
            with sqlite3.connect(db(d)) as conn:
                seq=conn.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
            at=106 if purpose in ('PREPARE','FINALIZE') else (107 if purpose=='DISPATCH' else 112)
            cert=seal(c(),p,v['scope'],oid,purpose,seq,at,at)
            v.setdefault('clocks',{})[purpose]=cert
            result={'stage':name,'sequence':seq,'signed_by':'external_C_fixture_process'}
        elif name=='c_trust':
            ledger=ToolLedger(tool_path(d),profile=p)
            from research.phase6.trusted_final import _pub
            from research.reference_executor.wire import keyid
            tool=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
            a=v['action']
            value={'issuer':'tool-issuer','tool':a['tool'],'tool_version':a['tool_version'],
              'destination':a['destination'],'ledger_id':ledger.ledger_id,
              'evidence_method':'tool-final-v2','public_key':b64(_pub(tool)),
              'kid':keyid(_pub(tool)),'epoch':'1','iat':'90','exp':'2000'}
            v['tool_certificate']=c().certify(v['scope'],value,1,ledger.head(),ledger.origin,profile=p)
            result={'stage':name,'certified':True,'external_C':True}
        else:raise ValueError(name)
    elif name=='x_sign':
        req=v['prepared'];x=Identity('fixture-x',12,roles=[ROLES[p]['X']],purposes=PURPOSES['X'])
        require(x.kid==req['x_kid'],'X_KEY_MISMATCH')
        v['acceptance']=x.sign(p,'Acceptance',v['scope'],req['acceptance_payload'],
           refs=req['refs'],aud=req['aud'],at=req['signed_at'],iid=sid(106008))
        result={'stage':name,'signature_ref':msgref(v['acceptance']),'external_X':True}
    elif name=='tool':
        ledger=ToolLedger(tool_path(d),profile=p)
        fact=ledger.freeze(v['scope'],v['action'],v['dispatch']['attempt'],at=110,
                 effect_id='phase14-'+('ind' if p.startswith('IND') else 'med')+'-effect')
        signed=ledger.reattest(v['scope'],fact,Ed25519PrivateKey.from_private_bytes(b'Q'*32),
                  'tool-issuer',111,2000)
        UpstreamSchema(ROOT,p).validate(signed,'Record_TOOL_FINAL')
        v['tool']={'fact':fact,'signed_final':signed,'ledger_origin':ledger.origin}
        result={'stage':name,'tool_final_ref':rec_ref(signed),'W_private_signing':False}
    else:
        w=_w(d,v)
        if name=='w_prepare':
            v['prepared']=w.prepare_accept(op,clock=v['clocks']['PREPARE'])
            require(w.snapshot()['accepts']==0 and w.snapshot()['reserved']==0,'PREPARE_SIDE_EFFECT')
            result={'stage':name,'ticket':v['prepared']['ticket'],'no_acceptance_yet':True}
        elif name=='w_finalize':
            a=w.finalize_accept(v['prepared']['ticket'],v['acceptance'],clock=v['clocks']['FINALIZE'])
            require(a==v['acceptance'],'SIGNATURE_RESPONSE')
            v['signed_messages']['acceptance']=a
            v['commit']=v['prepared']['commit_record']
            v['initial_snapshot']=w.snapshot()
            require(v['initial_snapshot']['accepts']==1 and v['initial_snapshot']['reserved']==1,'FINALIZE_ATOMICITY')
            result={'stage':name,'commit_ref':rec_ref(v['commit']),'acceptance_ref':msgref(a)}
        elif name=='w_activate':
            ledger=ToolLedger(tool_path(d),profile=p)
            w.activate_tool(v['tool_certificate'],ledger,now=108)
            result={'stage':name,'public_C_cert_verified':True}
        elif name=='claim':
            before=w.snapshot()
            tm=v['clocks']['DISPATCH'];attempt=sid(1413)
            res=w.claim_r2(oid,attempt,clock=tm)
            require(res['status']=='CLAIMED','CLAIM_FAILED')
            after=w.snapshot();require(after['reserved']==before['reserved'],'RESERVATION_LOST')
            v['dispatch']={'clock':tm,'attempt':attempt,'response':res,'before':before,'after':after}
            result={'stage':name,'claimed':True,'attempt':attempt}
        elif name=='settle':
            before=w.snapshot();ledger=ToolLedger(tool_path(d),profile=p)
            tm=v['clocks']['SETTLE'];signed=v['tool']['signed_final']
            res=w.settle_r2(signed,ledger,clock=tm)
            after=w.snapshot();require(res['status']=='SUCCEEDED' and after['reserved']==0 and after['spent']==1,'SETTLE_INTEGRITY')
            v['settlement']={'clock':tm,'response':res,'before':before,'after':after}
            result={'stage':name,'status':res['status']}
        elif name=='no_redispatch':
            before=w.snapshot()
            try:w.claim_r2(oid,sid(1414),clock={'irrelevant':True})
            except ProtocolError as e:
                require(e.code in ('NO_REDISPATCH','NO_DISPATCH'),'REPLAY_REASON');why=e.code
            else:raise AssertionError('redispatched')
            require(w.snapshot()==before,'REPLAY_SIDE_EFFECT')
            v['replay']={'attempt':sid(1414),'rejection':why,'unchanged':True}
            result={'stage':name,'rejected':why}
        else:raise ValueError(name)
    if name in ('claim','tool','settle','no_redispatch'):v['stage_pids'][name]=os.getpid()
    v['process_stage_outcomes'][name]=result
    dump(manifest(d),v)
    return result

def independent_audit(d):
    d=Path(d);v=load(manifest(d));p=v['profile']
    # Use the unmodified Phase13 verifier as an independent read-only oracle.
    audited={k:v[k] for k in ['profile','scope','action','operation_id','fixture_root_public',
                'fixture_actor_public','signed_messages','commit','tool_certificate',
                'initial_snapshot','dispatch','settlement','replay','stage_pids','process_stage_outcomes']}
    # Phase13 auditor requires its standard witness name; it does not open W classes.
    dump(d/'witness.json',audited)
    result=readonly_audit(d)
    require(result['W_accept_count']==1 and result['W_settlement_count']==1,'AUDIT_FAILED')
    with sqlite3.connect('file:'+str(db(d).resolve())+'?mode=ro',uri=True) as conn:
        row=conn.execute('SELECT state,plan_json,acceptance_json FROM p14_pending WHERE ticket=?',
                 (v['prepared']['ticket'],)).fetchone()
    require(row and row[0]=='DONE' and json.loads(row[1])['commit']==v['commit'] and
          json.loads(row[2])==v['acceptance'],'PREPARE_ARCHIVE_MISMATCH')
    return {**result,'phase14_prepared_ticket_checked':True,
         'processes':len(v['process_stage_outcomes'])+1,'official_complete_pass':False}

def child(d,name,profile=None):
    cmd=[sys.executable,'-m','research.phase14.process_flow','--child',name,'--dir',str(d)]
    if profile:cmd+=['--profile',profile]
    proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=120)
    if proc.returncode:raise RuntimeError(name+' '+str(proc.returncode)+' '+proc.stderr[-3000:])
    return json.loads(proc.stdout)

def orchestrate(base):
    base=Path(base);base.mkdir(parents=True,exist_ok=True);output={}
    for p in PROFILES:
        d=base/p;d.mkdir(exist_ok=True)
        outcomes=[child(d,'bootstrap',p)]
        for name in ('c_prepare','w_prepare','x_sign','c_finalize','w_finalize','c_trust',
                      'w_activate','c_claim','claim','tool','c_settle','settle','no_redispatch'):
            outcomes.append(child(d,name))
        audit=child(d,'audit')['audit']
        v=load(manifest(d))
        output[p]={'stages':outcomes,'audit':audit,'witness_sha256':sha(manifest(d)),
              'db_sha256':sha(db(d)),'tool_sha256':sha(tool_path(d))}
    result={'contract':'ZJJ-CORE-2.6-R2','phase':14,'official_passes':0,
         'case':'CORE-01','label':'LAB_PROCESS_ISOLATED_SCENE_CANDIDATE',
         'limitations':['C/X use insecure publicly known fixture keys',
             'separate OS processes do not establish separate OS account privileges',
             'PAY legacy Phase13 path not yet migrated',
             'simulated ToolLedger not physical effect','original full 39-case conformance not closed'],
         'profiles':output}
    dump(base/'phase14_process_report.json',result)
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--child',choices=('bootstrap','c_prepare','w_prepare','x_sign','c_finalize','w_finalize',
        'c_trust','w_activate','c_claim','claim','tool','c_settle','settle','no_redispatch','audit'))
    ap.add_argument('--dir');ap.add_argument('--profile',choices=PROFILES)
    ap.add_argument('--output');args=ap.parse_args()
    if args.child=='bootstrap':out=bootstrap(args.dir,args.profile)
    elif args.child=='audit':out={'stage':'audit','audit':independent_audit(args.dir)}
    elif args.child:out=step(args.dir,args.child)
    else:out=orchestrate(args.output or '/tmp/zjj_phase14_scene')
    print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':main()
