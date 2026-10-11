"""Export real signed A-01..04 checks and same-W IND acceptance races; no keys."""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import time
from pathlib import Path
from research.reference_executor.wire import ProtocolError, b64, raw, canonical, strict_verify, sortset
from competition.core.trusted_state import PROFILE_SCOPES, prefix
from competition.profiles.authorization_seed import initialize
from competition.profiles.industrial_seed import initialize as industrial

ROOT=Path(__file__).resolve().parents[1]

def write(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))

def build_identity():
    files=sorted(p for p in (ROOT/'competition').rglob('*') if p.suffix in ('.py','.md') and 'evidence' not in p.parts)
    rows=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    return {'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_files':rows,'source_digest':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),'dirty':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).splitlines()}

def public_state(run):
    with run.store.db() as c:
        tables={name:[dict(r) for r in c.execute('SELECT * FROM '+name)] for name in ('a_current','a_journal','a_deny_range','a_publication','a_guard_fact','comp_event_clock')}
    return {'root_public':b64(run.store.root_public),'roster':{p:{a:{'subject':who.name,'kid':who.kid,'public_key':b64(who.pub),'role':sorted(who.roles),'purposes':sorted(who.purposes)} for a,who in roster.items()} for p,roster in run.store.actors.items()},'tables':tables}

def signed_messages_valid(run,p,op):
    aliases={'issue':'H','permit':'G','authorization':'U','challenge_request':'H','challenge':'X','proof':'H'}
    for name,alias in aliases.items():
        m=op[name];strict_verify(run.actors[p][alias].pub,raw(m['sig'],64),canonical(['ZJJ-SIG-v1',m['protected'],m['body']]))
    for m in op['reviews']:strict_verify(run.actors[p]['V'].pub,raw(m['sig'],64),canonical(['ZJJ-SIG-v1',m['protected'],m['body']]))
    return True

def replace_source(run,p,op):
    ns='ORDER' if p=='PAY-1' else 'EVIDENCE'
    key=prefix(p)+[op['action']['payload']['order_id'],op['action']['payload']['stage']] if p=='PAY-1' else op['scene_key']
    with run.store.db() as c:record=run.store.current(c,p,ns,key)['record']
    if p!='PAY-1':
        data=record['value']['data'];data['evidence_revision']='2'
        if p=='MED-DEMO-1':data['record_revision']='2'
        att=record['value']['attestation'];head={k:att[k] for k in ('issuer','kid','iat','exp')}
        att['sig']=b64(run.actors[p]['E'].key.sign(canonical(['ZJJ-SOURCE-v1','2.6',p,record['kind'],record['scope'],data,head])))
    run.publish(p,ns,key,record)

def run_all(output):
    output.mkdir(parents=True,exist_ok=False);run_id='authorization-'+str(time.time_ns());runtime=ROOT/'.runtime'/run_id
    cases=[];identity=build_identity()
    scenarios={'full_signed_chain':'T','missing_review':'REVIEW_REQUIRED','missing_dependency':'DEP_CONFLICT','hidden_deny':'REVIEW_DENY','wrong_subject':'MESSAGE_BINDING','stale_source':'F'}
    for scenario,expected in scenarios.items():
        run=initialize(runtime/scenario)
        try:
            for p in PROFILE_SCOPES:
                op=run.clone(p)
                if scenario=='missing_review':op['reviews']=[];run.resign_chain(p,op)
                elif scenario=='missing_dependency':op['permit']['body']['deps']=op['deps'][1:];run.resign_chain(p,op)
                elif scenario=='hidden_deny':run.deny(p,op)
                elif scenario=='wrong_subject':
                    m=op['issue'];m['protected']['issuer']='unregistered-holder';m['sig']=b64(run.actors[p]['H'].key.sign(canonical(['ZJJ-SIG-v1',m['protected'],m['body']])))
                elif scenario=='stale_source':replace_source(run,p,op)
                actual_sig=signed_messages_valid(run,p,op);proof=run.identity_proof(p,op);before=run.service.counts()
                try:result=run.service.guard(p,op,proof);actual=result['decision']
                except ProtocolError as exc:result={'code':exc.code};actual=exc.code
                after=run.service.counts();passed=(actual=='T') if expected=='T' else (actual!='T' if expected=='F' else actual==expected)
                passed=passed and actual_sig and after['guard_commits']-before['guard_commits']==int(expected=='T')
                cid=p+'/'+scenario; evidence_name=p+'-'+scenario+'.json'
                write(output/evidence_name,{'case':cid,'expected':expected,'actual':actual,'status':'PASS' if passed else 'FAIL','actual_signatures_valid':actual_sig,'identity_proof':proof,'operation':op,'result':result,'before':before,'after':after,'public_state':public_state(run),'protocol_acceptance':False,'business_ledger_scope':'Authorization facts only; MED/PAY resource/dispatch/settle not implemented here'})
                cases.append({'profile':p,'scenario':scenario,'status':'PASS' if passed else 'FAIL','actual':actual,'evidence':evidence_name})
        finally:run.close()
    for order in ('deny_first','accept_first','concurrent'):
        s=industrial(runtime/order,label='DEMO_UNCERTAIN')
        try:
            op=s.op;t=s.w.prepare(op);proof=s.accept_proof(t['ticket_id'])
            msg=s.actors['V'].sign('IND-DEMO-1','Review',s.issuer.scope,{'ctx':op['ctx'],'purpose':'QUALITY_REVIEW','verdict':'DENY','reason':'authenticated quality stop'},deps=op['deps'],aud=sortset([s.actors[a].name for a in ('H','G','X')]),at=op['at'],ttl=120)
            before=s.w.snapshot()
            def accept():
                try:return s.w.accept(t['ticket_id'],proof=proof)
                except ProtocolError as exc:return {'code':exc.code}
            if order=='deny_first':publication=s.w.publish_review(msg);result=accept()
            elif order=='accept_first':result=accept();publication=s.w.publish_review(msg)
            else:
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    a=pool.submit(accept);d=pool.submit(s.w.publish_review,msg);result=a.result();publication=d.result()
            after=s.w.snapshot();accepted=result.get('acceptance_state')=='COMMITTED'
            passed=after['accepts']==after['reserved']==int(accepted) and after['calls']==0 and (result.get('code')=='REVIEW_DENY' if not accepted else True)
            if order!='concurrent':passed=passed and accepted==(order=='accept_first')
            with s.w.db() as c:
                journal=[dict(r) for r in c.execute('SELECT * FROM a_journal ORDER BY seq')]
                receipts=[dict(r) for r in c.execute('SELECT * FROM comp_acceptance')]
            name='IND-DEMO-1-'+order+'.json'
            write(output/name,{'order':order,'status':'PASS' if passed else 'FAIL','operation':op,'deny':msg,'publication':publication,'before':before,'after':after,'result':result,'authorization_journal':journal,'acceptance_rows':receipts,'root_public':b64(s.w.root_public)})
            cases.append({'profile':'IND-DEMO-1','scenario':order,'status':'PASS' if passed else 'FAIL','actual':'COMMITTED' if accepted else result.get('code'),'evidence':name})
        finally:s.close()
    run=initialize(runtime/'medical_read')
    try:
        p='MED-DEMO-1';op=run.operations[p];seen=[]
        valid=run.service.read(p,op,run.identity_proof(p,op,'CANDIDATE'),stage='CANDIDATE',candidate=lambda view: seen.append(view) or view)
        with run.store.db() as c:policy=run.store.current(c,p,'POLICY',prefix(p))['record']
        policy['value']['readers'].remove(run.actors[p]['H'].name);run.publish(p,'POLICY',prefix(p),policy)
        errors=[];proofs=[]
        for stage in ('DETAIL','CANDIDATE'):
            proof=run.identity_proof(p,op,stage);proofs.append(proof)
            try:run.service.read(p,op,proof,stage=stage,candidate=(lambda view:seen.append(view)) if stage=='CANDIDATE' else None);errors.append('unexpected-read')
            except ProtocolError as exc:errors.append(exc.code)
        passed=errors==['NO_ROLE','NO_ROLE'] and len(seen)==1 and valid['original_envelope'] is False and bool(valid['records'])
        name='MED-DEMO-1-current_acl_before_candidate_detail.json'
        write(output/name,{'status':'PASS' if passed else 'FAIL','valid_projection':valid,'after_current_acl_removal':errors,'candidate_calls':len(seen),'identity_proofs':proofs,'operation':op,'public_state':public_state(run)})
        cases.append({'profile':p,'scenario':'current_acl_before_candidate_detail','status':'PASS' if passed else 'FAIL','actual':errors,'evidence':name})
    finally:run.close()
    report={'run_id':run_id,'build':identity,'case_count':len(cases),'pass_count':sum(c['status']=='PASS' for c in cases),'cases':cases,'limits':['Authorization T is not protocol ACCEPTED; only IND cases exercise actual acceptance/resource transaction.','Windows same-user bootstrap remains trusted; no Linux DAC or HSM proof.','C-certified initial complete empty range plus exclusive transactional W publications; not independently authenticated distributed history.','Original finite business rules/schema preserved; synthetic source facts and simulators only.','Complete dynamic governance and MED/PAY dispatch/settlement deferred to later work.']}
    write(output/'report.json',report)
    print(json.dumps({'run_id':run_id,'cases':len(cases),'pass':report['pass_count'],'output':str(output)},ensure_ascii=False))
    return 0 if report['pass_count']==len(cases) else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    raise SystemExit(run_all(parser.parse_args().output.resolve()))
