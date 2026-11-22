"""Reproducible competition security checks; keys stay in ignored .runtime.

The reference gate is deliberately explicit: it verifies the SAME complete
current signed chain and persists request-id deduplication, but has no business
intent tombstone or W resource/dispatch ledger. It compares mechanisms, not
cryptography novelty, real banks, or every possible signed-approval design.
"""
import argparse
import copy
import json
import hashlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from competition.profiles.w_seed import initialize
from competition.run_w_slice import normal, public_ledgers, evaluate
from competition.run_authorization_slice import write, build_identity
from competition.w_cases import accept_operation, tool_snapshot, lost_ack
from competition.core.candidate_ingress import CandidateIngress
from competition.support.wire import ProtocolError, require, canonical, b64

ROOT=Path(__file__).resolve().parents[1]

def refusal(fn):
    try:fn()
    except ProtocolError as exc:return exc.code
    raise AssertionError('Expected refusal')

class SignedApprovalReference:
    def __init__(self,run):
        self.run=run
        with run.store.db() as c:
            c.execute('CREATE TABLE comparison_request(profile TEXT,oid TEXT,PRIMARY KEY(profile,oid))')
    def accept(self,p,op):
        run=self.run;oid=op['action']['operation_id']
        with run.store.tx() as c:
            event=run.store.event(c,p,oid,'AUTHZ_GUARD','reference')
            run.w.guard.verify(c,p,op,event)
            require(c.execute('SELECT 1 FROM comparison_request WHERE profile=? AND oid=?',(p,oid)).fetchone() is None,'REFERENCE_REQUEST_REPLAY')
            c.execute('INSERT INTO comparison_request VALUES(?,?)',(p,oid))
        return 'T'

def adversarial(run):
    p='PAY-1';op=run.clone(p)
    unsigned=copy.deepcopy(op['authorization']);unsigned.pop('sig')
    rows=[]
    def add(name,fn,expected=None):
        before=run.w.counts();code=refusal(fn);after=run.w.counts()
        require(before==after,'NEGATIVE_SIDE_EFFECT')
        require(expected is None or code==expected,'UNEXPECTED_REFUSAL')
        rows.append({'case':name,'refusal':code,'before':before,'after':after,'passed':True})
    add('no_sign_caller',lambda:run.base.broker.sign(p,'U',unsigned,op['action']),'SIGN_CALLER_REQUIRED')
    cl=run.base.broker.challenge(p,'U',unsigned,op['action'])
    fake={'claim':cl,'signature':b64(run.actors[p]['H'].key.sign(canonical(['COMP-APP-SIGN-CALL-v1',cl])))}
    add('holder_cannot_sign_as_U',lambda:run.base.broker.sign(p,'U',unsigned,op['action'],caller_proof=fake),'BAD_SIGNATURE')
    changed=run.clone(p);changed['action']['payload']['amount_minor']='732'
    add('agent_action_replacement',lambda:run.w.prepare(p,changed,run.identity_proof(p,changed)))
    missing=run.clone(p);missing['reviews']=[]
    add('missing_required_approval',lambda:run.w.prepare(p,missing,run.identity_proof(p,missing)),'REVIEW_REQUIRED')
    legacy=run.clone(p);m=legacy['authorization'];m['protected']['proto']='ZJJ-AAP'
    m['sig']=b64(run.actors[p]['U'].key.sign(canonical(['ZJJ-SIG-v1',m['protected'],m['body']])))
    add('genuine_R2_message_not_contest',lambda:run.w.prepare(p,legacy,run.identity_proof(p,legacy)))
    ingress=CandidateIngress(ROOT)
    add('candidate_cannot_inject_private_path',lambda:ingress.parse(p,canonical({'key_path':'C.key'})))
    return rows

def comparison(run):
    p='PAY-1';op=run.clone(p);ref=SignedApprovalReference(run)
    first=ref.accept(p,op)
    replay=refusal(lambda:ref.accept(p,op))
    oid,_=accept_operation(run,p)
    run.w.claim(p,oid,run.worker_proof(p,oid,'CLAIM'))
    response=run.w.execute_once(p,oid,run.worker_proof(p,oid,'EXECUTE'))
    settled=run.w.settle(p,oid,response,run.worker_proof(p,oid,'SETTLE'))
    require(settled['state']=='SETTLED','REFERENCE_FIRST_FLOW')
    fresh=run.fork_operation(p,op)
    next_ref=ref.accept(p,fresh)
    ticket=run.w.prepare(p,fresh,run.identity_proof(p,fresh))
    next_w=refusal(lambda:run.w.accept(p,ticket['ticket_id'],run.accept_proof(p,ticket['ticket_id'])))
    with run.store.db() as c:reference_rows=[dict(row) for row in c.execute('SELECT * FROM comparison_request')]
    accepted_reference=len(reference_rows)
    require((first,replay,next_ref,next_w,accepted_reference)==('T','REFERENCE_REQUEST_REPLAY','T','INTENT_CONFLICT',2),'COMPARISON_OUTCOME')
    require(run.w.counts()['accepts']==tool_snapshot(run,p)['effect_count']==1,'COMPARISON_REPEAT_EFFECT')
    return {'same_original_chain':op,'new_genuinely_approved_chain':fresh,
            'reference_first':first,'reference_same_request':replay,'reference_new_request':next_ref,
            'W_new_request':next_w,'reference_accepted_requests':accepted_reference,'reference_rows':reference_rows,
            'W_confirmed_effects':tool_snapshot(run,p)['effect_count'],'passed':True,
            'scope':'Identical complete signed-chain validation; persistent request-id replay protection in reference; business-intent deduplication is W addition. Reference results count admitted requests, not bank payments or signed tool effects.'}

def status_load(run,p,oid,workers,requests):
    samples=[];errors=[]
    def read(i):
        start=time.perf_counter()
        try:
            status=run.w.status(p,oid,run.read_proof(p,oid))
            require(status['dispatch_state']=='SETTLED','LOAD_STATE')
            return time.perf_counter()-start,None
        except ProtocolError as exc:return time.perf_counter()-start,exc.code
    before=run.w.counts()
    with ThreadPoolExecutor(workers) as pool:
        for seconds,error in pool.map(read,range(requests)):
            samples.append(seconds)
            if error:errors.append(error)
    samples.sort()
    require(before==run.w.counts(),'LOAD_BUSINESS_MUTATION')
    return {'profile':p,'workers':workers,'requests':requests,'successes':requests-len(errors),
            'errors':errors,'max_seconds':max(samples),'median_seconds':samples[len(samples)//2],
            'p95_seconds':samples[min(len(samples)-1,int(len(samples)*.95))],
            'no_business_mutation':True,'passed':not errors}

def run_all(output,workers=8,requests=24):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    run_id='security-'+str(time.time_ns())
    runtime=ROOT/'.runtime'/run_id
    w_output=output/'w-slice';w_output.mkdir()
    w_cases=[]
    report={'contract':'ZJJ-CORE-COMP-1','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'build':build_identity(),'cases':[],'load':[]}
    run=initialize(runtime/'main')
    try:
        rows=adversarial(run);write(output/'adversarial.json',{'cases':rows,'public_ledgers':public_ledgers(run)})
        report['cases']+=rows
    finally:run.close()
    for p in ('IND-DEMO-1','PAY-1','MED-DEMO-1'):
        run=initialize(runtime/('normal-'+p))
        try:
            start=time.perf_counter();result=normal(run,p)
            require(evaluate('normal',result,run,p),'NORMAL_FLOW')
            write(w_output/(p+'-normal.json'),{'run_id':run_id,'case':'normal','profile':p,'status':'PASS','result':result,'counts':run.w.counts(),'public_ledgers':public_ledgers(run)})
            w_cases.append({'profile':p,'scenario':'normal','status':'PASS','evidence':p+'-normal.json'})
            report['cases'].append({'case':p+'/normal','passed':True,'seconds':time.perf_counter()-start})
            report['load'].append(status_load(run,p,result['operation_id'],workers,requests))
            print(json.dumps({'profile':p,'normal':True,'load':report['load'][-1]}),flush=True)
        finally:run.close()
    run=initialize(runtime/'comparison')
    try:
        result=comparison(run);write(output/'signed-approval-comparison.json',{'result':result,'public_ledgers':public_ledgers(run)})
        report['cases'].append({'case':'signed-approval-comparison','passed':result['passed']})
    finally:run.close()
    for p in ('IND-DEMO-1','PAY-1','MED-DEMO-1'):
        run=initialize(runtime/('lost-ack-'+p))
        try:
            result=lost_ack(run,p)
            require(evaluate('lost_ack',result,run,p),'RECOVERY_FLOW')
            write(w_output/(p+'-lost-ack.json'),{'run_id':run_id,'case':'lost_ack','profile':p,'status':'PASS','result':result,'counts':run.w.counts(),'public_ledgers':public_ledgers(run)})
            w_cases.append({'profile':p,'scenario':'lost_ack','status':'PASS','evidence':p+'-lost-ack.json'})
            report['cases'].append({'case':p+'/lost_ack','passed':True})
        finally:run.close()
    report['passed']=all(r['passed'] for r in report['cases']+report['load'])
    write(output/'report.json',report)
    write(w_output/'report.json',{'run_id':run_id,'build':report['build'],'cases':w_cases,'passed':report['passed']})
    rows=[{'path':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(w_output.glob('*.json'))]
    write(w_output/'manifest.json',{'run_id':run_id,'build':report['build'],'files':rows})
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=8);ap.add_argument('--requests',type=int,default=24)
    args=ap.parse_args();require(1<=args.workers<=32 and 1<=args.requests<=256,'LOAD_LIMIT')
    result=run_all(args.output,args.workers,args.requests)
    print(json.dumps({'passed':result['passed'],'cases':len(result['cases']),'load':len(result['load'])}))
    raise SystemExit(0 if result['passed'] else 1)
