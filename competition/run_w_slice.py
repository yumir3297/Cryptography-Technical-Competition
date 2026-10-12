"""Export fresh common-W real-process cases and independent public ledgers."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from competition.run_authorization_slice import build_identity, write
from competition.profiles.w_seed import initialize
from competition.core.trusted_state import PROFILE_SCOPES
from competition import w_cases
from competition.support.wire import b64, rec_ref

ROOT=Path(__file__).resolve().parents[1]
TABLES=('a_current','a_journal','a_deny_range','a_publication','comp_event_clock','w_meta','w_operation','w_intent','w_consumed','w_mutable','w_resource','w_reservation','w_flight','w_outbox','w_tool','w_settlement','w_evidence')

def public_ledgers(run):
    with run.store.db() as c:tables={t:[dict(row) for row in c.execute('SELECT * FROM '+t)] for t in TABLES}
    return {'root_public':b64(run.store.root_public),'roster':{p:{a:{'subject':w.name,'kid':w.kid,'public_key':b64(w.pub)} for a,w in roster.items()} for p,roster in run.store.actors.items()},'worker_certificate':run.worker_certificate,'tables':tables,'tools':{p:w_cases.tool_snapshot(run,p) for p in PROFILE_SCOPES}}

def normal(run,p):
    from competition.support.tool_final import final_fact_id
    op=run.operations[p];ticket=run.w.prepare(p,op,run.identity_proof(p,op));time.sleep(1.05)
    accepted=run.w.accept(p,ticket['ticket_id'],run.accept_proof(p,ticket['ticket_id']));oid=op['action']['operation_id']
    elapsed=int(accepted['acceptance']['body']['payload']['accepted_at'])-ticket['time_witness']['lo']
    claimed=run.w.claim(p,oid,run.worker_proof(p,oid,'CLAIM'))
    response=run.w.execute_once(p,oid,run.worker_proof(p,oid,'EXECUTE'))
    settled=run.w.settle(p,oid,response,run.worker_proof(p,oid,'SETTLE'))
    until=int(response['record']['value']['iat'])+1.02
    while time.time()<until:time.sleep(min(0.02,until-time.time()))
    reattested=run.w.query_attempt(p,oid,run.worker_proof(p,oid,'QUERY'))
    repeated=run.w.settle(p,oid,reattested,run.worker_proof(p,oid,'SETTLE'));before=run.w.counts()
    status=run.w.status(p,oid,run.read_proof(p,oid));audit=run.w.audit(p,oid,run.read_proof(p,oid,'AUDIT'))
    after=run.w.counts()
    return {'profile':p,'operation_id':oid,'prepare_ticket':ticket,'prepare_to_accept_seconds':elapsed,'acceptance':accepted,'claim':claimed,'response':response,'reattested':reattested,'different_record_refs':rec_ref(response['record'])!=rec_ref(reattested['record']),'same_final_fact_id':final_fact_id(response['record'])==final_fact_id(reattested['record']),'settled':settled,'repeated':repeated,'status':status,'audit':audit,'before_reads':before,'after_reads':after,'final_fact_id':final_fact_id(response['record']),'snapshot':w_cases.public_snapshot(run,p,oid)}

def evaluate(name,result,run,p):
    c=run.w.counts();tools=w_cases.tool_snapshot(run,p);effect=tools['effect_count']
    if name=='normal':return result['prepare_to_accept_seconds']>=1 and c['accepts']==c['attempts']==c['exec_invocations']==c['execution_sends_observed']==c['settlements']==effect==1 and c['queries']==1 and result['different_record_refs'] and result['same_final_fact_id'] and result['before_reads']==result['after_reads'] and result['settled']['final_fact_id']==result['repeated']['final_fact_id']
    if name=='lost_ack':return result['lost_ack'].get('trace',{}).get('exit_code')==98 and result['persisted_fact_id']==result['query_fact_id']==result['settlement']['final_fact_id']==result['repeated_settlement']['final_fact_id'] and result['before_retry']==result['after_retry'] and c['accepts']==c['attempts']==c['exec_invocations']==c['execution_sends_observed']==c['queries']==effect==c['settlements']==1
    if name=='unknown_query':return result['query']['record'] is None and effect==c['settlements']==0 and c['exec_invocations']==c['attempts']==c['queries']==1 and result['before']['reservations']==result['after']['reservations'] and result['before']['flights']==result['after']['flights'] and result['after']['operation']['state']=='STARTED'
    if name=='concurrent_claim_settle':return len(set(result['attempt_ids']))==len(set(result['final_fact_ids']))==1 and c['attempts']==c['exec_invocations']==effect==c['settlements']==1
    if name=='w_commit_crash':return result['crash']['exit_code']==97 and result['before_receipt']['operation']['receipt'] is None and result['frozen_core']==result['returned_core'] and result['before_receipt']['commit_ref']==result['after_receipt']['commit_ref'] and c['accepts']==1 and c['attempts']==c['exec_invocations']==effect==c['settlements']==0
    if name=='conflicting_final':
        return c['halts']==1 and c['settlements']==0 and c['attempts']==c['exec_invocations']==effect==1 and 'UNEXPECTEDLY_ACCEPTED' not in result['rejected'] and result['before_bad']['reservations']==result['after_bad']['reservations'] and result['before_bad']['operation']['state']==result['after_bad']['operation']['state'] and any(r['state']=='RESERVED' for r in result['after_conflict']['reservations'])
    return result.get('passed') is True

def run_all(output):
    from competition import w_cases_races
    output.mkdir(parents=True,exist_ok=False);run_id='w-'+str(time.time_ns());identity=build_identity();cases=[]
    jobs=[(name,p,fn,{}) for p in PROFILE_SCOPES for name,fn in [('normal',normal),('lost_ack',w_cases.lost_ack),('unknown_query',w_cases.unknown_query),('concurrent_claim_settle',w_cases.concurrent_claim_and_settle),('conflicting_final',w_cases.bad_and_conflicting_final),('w_commit_crash',w_cases.w_commit_crash)]]
    jobs += [(name,'IND-DEMO-1',lambda r,p,fn=fn:fn(r),{'resource_capacity':{'IND-DEMO-1':1}}) for name,fn in [('same_intent8',w_cases_races.same_intent8),('last_resource',w_cases_races.last_resource),('claim_cancel_revoked',w_cases_races.claim_cancel_revoked),('claimed_cancel8',w_cases_races.claimed_cancel8)]]
    for index,(name,p,fn,kwargs) in enumerate(jobs):
        run=initialize(ROOT/'.runtime'/run_id/(p+'-'+name),**kwargs)
        try:
            result=fn(run,p);passed=evaluate(name,result,run,p);filename=p+'-'+name+'.json'
            write(output/filename,{'run_id':run_id,'case':name,'profile':p,'expected':'declared W single-host simulator invariant','actual':result,'status':'PASS' if passed else 'FAIL','counts':run.w.counts(),'public_ledgers':public_ledgers(run)})
            cases.append({'profile':p,'scenario':name,'status':'PASS' if passed else 'FAIL','evidence':filename,'counts':run.w.counts()})
            print(json.dumps({'case':index+1,'total':len(jobs),'profile':p,'scenario':name,'passed':passed}),flush=True)
        finally:run.close()
    report={'kind':'three_profile_common_W_scoped_evidence_not_full_21_groups','run_id':run_id,'base_commit':'be4d2cbca3d71653ba86333f156dc42d96608d99','build':identity,'contract':'COMP-APP-W-1.0','cases':cases,'passed':all(c['status']=='PASS' for c in cases),'limits':['Single trusted host and three signed SQLite simulators; no physical/bank/clinical effect guarantee.','Immutable ledger/checkpoints detect representative inconsistencies, not malicious whole-disk rollback.','Windows processes with trusted bootstrap; Linux DAC/HSM still S/T.','status/audit are authenticated application projections, not full R2 signed STATUS.','EXEC consumption is separate from observed process sends; unobserved send upper bound is reported.']}
    write(output/'report.json',report)
    files=[{'path':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.glob('*.json'))]
    write(output/'manifest.json',{'run_id':run_id,'build':identity,'files':files})
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=run_all(args.output);print(json.dumps({'run_id':report['run_id'],'passed':report['passed'],'cases':len(report['cases'])}));raise SystemExit(0 if report['passed'] else 1)
