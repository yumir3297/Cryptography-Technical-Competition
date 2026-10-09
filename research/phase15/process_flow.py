"""PAY-1 Phase15 subprocess-handoff lab. Process separation is NOT OS key isolation."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase4.flow import SignedPayFlow
from research.phase7.guarded_dispatch import _make_cert
from research.phase11.pay_r2 import sign_window
from research.phase11.trusted_clock import seal
from research.phase11.run_phase11 import ROOT
from research.phase15.pay_accept import VerifierOnlyPayW
from research.phase6.trusted_final import (Controller,ToolLedger,_pub,final_fact)
from research.phase5.durable_w import archive_verify,archive_verify_reply
from research.reference_executor.wire import (Identity,ProtocolError,b64,raw,keyid,sid,
    rec_ref,msgref,sortset,require,canonical,strict_verify)
from research.strict_v26.upstream_schema import UpstreamSchema

def dump(p,v):
    Path(p).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8')
def load(p):return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wp(d):return Path(d)/'pay_witness.json'
def db(d):return Path(d)/'pay_w.sqlite'
def lp(d):return Path(d)/'tool.sqlite'
def controller():return Controller.fixture()
def w(d,v):
    actors={k:SimpleNamespace(name=a['name'],kid=a['kid'],pub=raw(a['pub'],32),
        purposes=frozenset(a['purposes'])) for k,a in v['actors'].items()}
    instance=VerifierOnlyPayW(db(d),raw(v['root_public'],32),
              ledger=ToolLedger(lp(d),profile='PAY-1'),actors=actors)
    require(not any(hasattr(a,'key') for a in instance.public_actors.values()),'PRIVATE_KEY_IN_W')
    return instance

def bootstrap(d):
    d=Path(d);d.mkdir(parents=True,exist_ok=True)
    f=SignedPayFlow(schema_root=ROOT);o=f.prepare()
    for purpose in o.required:f.review(o,purpose=purpose)
    f.authorize(o);f.issue(o);f.challenge(o)
    sources=[{'namespace':ns,'key':list(key),'revision':str(row.revision),
              'ref':row.ref,'record':copy.deepcopy(row.record) if row.record is not None else {},
              'value':copy.deepcopy(row.value)}
        for (ns,key),row in f.trusted._rows.items()]
    f.commit(o)
    bundle={'commit':f.commit_record,'permit':o.permit,'proof':o.proof,
        'challenge':o.challenge,'challenge_request':o.challenge_request,
        'authorization':o.authorization,'reviews':o.reviews}
    wanted={(a['namespace'],tuple(a['key'])) for a in f.commit_record['value']['checked_deps']}
    sources=[r for r in sources if (r['namespace'],tuple(r['key'])) in wanted]
    witness={'profile':'PAY-1','scope':f.scope,'operation_id':o.action['operation_id'],
        'action':o.action,'actors':{k:{'name':a.name,'kid':a.kid,'pub':b64(a.pub),
             'purposes':sorted(a.purposes)} for k,a in f.actors.items()},
        'root_public':b64(controller().public_key),'signed_bundle':bundle,
        'source_rows':sources,'stage_pids':{'bootstrap':os.getpid()},
        'stages':{},'official_complete_pass':False,
        'c_key_custody':'insecure fixture','x_key_custody':'insecure fixture'}
    dump(wp(d),witness)
    return {'bootstrap_signed_candidate':True,'W_received_private_signer':False}

def stage(d,name):
    d=Path(d);v=load(wp(d));o=v['operation_id'];scope=v['scope'];act=v['action']
    if name=='c_publish':
        instance=w(d,v)
        deps=v['signed_bundle']['commit']['value']['checked_deps']
        changes=[{**r,'active':True} for r in deps if r['namespace']!='BEHAVIOR']
        instance.certified_publish(_make_cert(controller(),
             {'operation_id':'','scope':scope,'changes':changes}))
        for row in changes:
            cl={'scope':scope,'dep':{k:row[k] for k in ('namespace','key','revision','ref')},
                'seq':'1','iat':'90','exp':'2000'}
            instance.publish_window(sign_window(controller(),cl))
        source={'scope':scope,'seq':'1','rows':v['source_rows']}
        source_cert={'claim':source,'signature':b64(controller().key.sign(
                         canonical(['ZJJ-P15-C-SOURCE-v1',source])))}
        instance.publish_source_bundle(source_cert)
        v['source_certificate']=source_cert
        outcome={'C_signed_publications':len(changes),'source_rows':len(v['source_rows'])}
    elif name in ('c_prepare','c_finalize','c_dispatch','c_settle'):
        purpose={'c_prepare':'PREPARE','c_finalize':'FINALIZE','c_dispatch':'DISPATCH',
                 'c_settle':'SETTLE'}[name]
        with sqlite3.connect(db(d)) as conn:
            seq=conn.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
        at=100 if purpose in ('PREPARE','FINALIZE') else (107 if purpose=='DISPATCH' else 112)
        v.setdefault('clocks',{})[purpose]=seal(controller(),'PAY-1',scope,o,purpose,seq,at,at)
        outcome={'purpose':purpose,'seq':seq,'C_external':True}
    elif name=='x_sign':
        req=v['prepared']
        # Standalone actor seed; proposer flow is absent from this process.
        x=Identity('executor',20,roles=['EXECUTOR'],purposes=['Acceptance','Challenge','Result'])
        require(x.kid==req['x_kid'],'X_KEY_MISMATCH')
        deps=[r for r in v['signed_bundle']['commit']['value']['checked_deps']
              if r['namespace']=='KEY' and r['key']==[x.kid] or
                 r['namespace']=='ROLE' and r['key'][-2:]==['executor','EXECUTOR']]
        acc=x.sign('PAY-1','Acceptance',scope,req['acceptance_payload'],
              refs=req['refs'],deps=sortset(deps),aud=req['aud'],at=req['signed_at'],iid=sid(15511))
        p={'request_ref':req['proof_ref'],'attempt_id':
             v['signed_bundle']['proof']['body']['payload']['attempt_id'],
           'result':'ACCEPTED','reasons':[{'check':'result','code':'OK'}],
           'operation_id':o,'permit_ref':'','acceptance_ref':msgref(acc),
           'status':'ACCEPTED','status_seq':req['accept_seq'],'retry_after':''}
        reply=x.sign('PAY-1','Result',scope,p,refs=[req['proof_ref'],msgref(acc)],
                     deps=sortset(deps),aud=[v['actors']['H']['name']],at=req['signed_at'],iid=sid(15512))
        v['acceptance']=acc;v['result']=reply
        outcome={'X_external':True,'acceptance_ref':msgref(acc),'result_ref':msgref(reply)}
    elif name=='c_trust':
        ledger=ToolLedger(lp(d),profile='PAY-1')
        key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        value={'issuer':'tool-issuer','tool':act['tool'],'tool_version':act['tool_version'],
            'destination':act['destination'],'ledger_id':ledger.ledger_id,
            'evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
            'kid':keyid(_pub(key)),'epoch':'1','iat':'90','exp':'2000'}
        v['tool_certificate']=controller().certify(scope,value,1,ledger.head(),ledger.origin)
        outcome={'C_external':True,'certificate':True}
    elif name=='tool':
        ledger=ToolLedger(lp(d),profile='PAY-1')
        fact=ledger.freeze(scope,act,v['dispatch']['attempt'],at=110,effect_id='phase15-pay-effect')
        signed=ledger.reattest(scope,fact,Ed25519PrivateKey.from_private_bytes(b'Q'*32),
                   'tool-issuer',111,2000)
        UpstreamSchema(ROOT,'PAY-1').validate(signed,'Record_TOOL_FINAL')
        v['tool']={'fact':fact,'final':signed,'ledger_origin':ledger.origin}
        outcome={'simulated_fact':True,'signed_ref':rec_ref(signed)}
    else:
        instance=w(d,v)
        if name=='w_prepare':
            v['prepared']=instance.prepare_pay(v['signed_bundle'],clock=v['clocks']['PREPARE'])
            require(instance.snapshot()['accepted_rows']==0 and instance.snapshot()['reserved']==0,
                    'PREPARE_SIDE_EFFECT')
            outcome={'prepared':True,'ticket':v['prepared']['ticket'],'W_signing_key':False}
        elif name=='w_finalize':
            result=instance.finalize_pay(v['prepared']['ticket'],v['acceptance'],v['result'],
                                      clock=v['clocks']['FINALIZE'])
            snap=instance.snapshot()
            require(snap['accepted_rows']==1 and snap['reserved']==2000 and not result['idempotent'],
                    'FINALIZE_INTEGRITY')
            v['accept_snapshot']=snap
            outcome={'finalized':True,'commit_ref':rec_ref(result['commit'])}
        elif name=='w_activate':
            ledger=ToolLedger(lp(d),profile='PAY-1')
            instance.activate(v['tool_certificate'],ledger,now=101)
            outcome={'trusted_ledger':True}
        elif name=='w_dispatch':
            attempt=sid(15513)
            result=instance.claim_r2(o,attempt,clock=v['clocks']['DISPATCH'])
            require(result['status']=='CLAIMED','CLAIM_FAILED')
            v['dispatch']={'attempt':attempt,'result':result}
            outcome={'claimed':True,'attempt':attempt}
        elif name=='w_settle':
            result=instance.settle_r2(v['tool']['final'],clock=v['clocks']['SETTLE'])
            snap=instance.snapshot()
            require(result['status']=='SUCCEEDED' and snap['reserved']==0 and
                    snap['spent']==2000,'SETTLEMENT_FAILED')
            v['settlement']={'result':result,'snapshot':snap}
            outcome={'settled':True,'spent':snap['spent']}
        elif name=='w_no_redispatch':
            before=instance.snapshot()
            try:instance.claim_r2(o,sid(15514),clock={'invalid':True})
            except ProtocolError as exc:
                require(exc.code=='NO_REDISPATCH','REPLAY_REASON')
                outcome={'rejected':exc.code}
            else:raise AssertionError('new dispatch after settlement')
            require(instance.snapshot()==before,'REPLAY_SIDE_EFFECT')
        else:raise ValueError(name)
    v['stage_pids'][name]=os.getpid()
    v['stages'][name]=outcome
    dump(wp(d),v)
    return outcome

def independent_audit(d):
    d=Path(d);v=load(wp(d))
    with sqlite3.connect('file:'+str(db(d).replace('\\','/'))+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(v['operation_id'],)).fetchone()
        require(row is not None,'NO_ACCEPTED_ROW')
        commit=json.loads(row['commit_bytes']);acc=json.loads(row['acceptance_bytes'])
        result=json.loads(row['reply_bytes'])
        archive_verify(commit,acc)
        archive_verify_reply(acc,result,commit['value']['signing_public_key'])
        UpstreamSchema(ROOT,'PAY-1').validate(commit,'Record_COMMIT')
        UpstreamSchema(ROOT,'PAY-1').validate(acc,'Acceptance')
        UpstreamSchema(ROOT,'PAY-1').validate(result,'Result')
        ticket=c.execute('SELECT * FROM p15_pending_pay WHERE ticket=?',(v['prepared']['ticket'],)).fetchone()
        require(ticket is not None and ticket['state']=='DONE' and
                json.loads(ticket['acceptance'])==acc and json.loads(ticket['reply'])==result,
                'TICKET_ARCHIVE_INTEGRITY')
        sources=c.execute('SELECT certificate FROM p15_authoritative_sources WHERE id=1').fetchone()
        require(sources is not None,'C_SOURCE_MISSING')
        src=json.loads(sources['certificate'])
        strict_verify(raw(v['root_public'],32),raw(src['signature'],64),
                      canonical(['ZJJ-P15-C-SOURCE-v1',src['claim']]))
        require(src==v['source_certificate'],'SOURCE_MISMATCH')
        assert c.execute('SELECT COUNT(*) FROM accepted').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM settled').fetchone()[0]==1
        assert c.execute('SELECT spent,reserved FROM account WHERE id=1').fetchone()==(2000,0)
    with sqlite3.connect('file:'+str(lp(d))+'?mode=ro',uri=True) as c:
        row=c.execute('SELECT fact FROM finalized WHERE operation_id=?',(v['operation_id'],)).fetchone()
        require(row is not None and json.loads(row[0])==final_fact(v['tool']['final']),
                'INDEPENDENT_LEDGER_MISMATCH')
    require(len(set(v['stage_pids'].values()))==len(v['stage_pids']),'NOT_PROCESS_SEPARATED')
    return {'independent_readonly_verifier':True,'original_schema_records':['Record_COMMIT','Acceptance','Result','Record_TOOL_FINAL'],
            'W_accept_count':1,'W_settlement_count':1,'source_certificate_verified':True,
            'externally_signed_X':True,'lab_process_count':len(v['stage_pids']),
            'tool_is_simulation':True,'official_complete_pass':False}

def child(d,name):
    process=subprocess.run([sys.executable,'-m','research.phase15.process_flow','--child',name,'--dir',str(d)],
         cwd=ROOT,text=True,capture_output=True,timeout=120)
    if process.returncode:raise RuntimeError(name+': '+process.stderr[-5000:])
    return json.loads(process.stdout)

def orchestrate(base):
    d=Path(base);d.mkdir(parents=True,exist_ok=True)
    results=[child(d,'bootstrap')]
    for name in ('c_publish','c_prepare','w_prepare','x_sign','c_finalize','w_finalize',
                 'c_trust','w_activate','c_dispatch','w_dispatch','tool','c_settle',
                 'w_settle','w_no_redispatch'):
        results.append(child(d,name))
    audit=independent_audit(d)
    out={'profile':'PAY-1','case':'CORE-01','phase':15,'official_complete_pass':False,
         'audit':audit,'steps':results,'signed_witness_sha256':sha(wp(d)),
         'W_db_sha256':sha(db(d)),'tool_db_sha256':sha(lp(d)),
         'limitations':['publicly known lab fixture signing seeds',
           'different processes do not imply independent OS credentials',
           'pay TrustedStore recreated from C-signed synthetic source records',
           'C time is a signed laboratory assertion, not a physical clock',
           'simulated ToolLedger does not prove real financial settlement',
           'original full39 semantic conformance remains BLOCKED']}
    dump(d/'phase15_pay_report.json',out)
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--child');ap.add_argument('--dir')
    ap.add_argument('--output');a=ap.parse_args()
    if a.child=='bootstrap':r=bootstrap(a.dir)
    elif a.child:r=stage(a.dir,a.child)
    else:r=orchestrate(a.output or '/tmp/phase15_pay')
    print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__':main()
