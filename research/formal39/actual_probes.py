"""Fresh 39-case acceptance probes: actual signed messages and persistent W, not witness aliases.

These probes test narrow case facets. Their SUCCESS does not certify the whole case.
Use official original manifest and exact PAY JSON Schema in addition to signed fixture verification.
"""
from __future__ import annotations
import concurrent.futures,copy,json,tempfile
from pathlib import Path
from research.reference_executor.wire import ProtocolError,rec_ref,msgref
from research.phase5.run_phase5 import prepare_cases,check_emitted,schema_probe
from research.phase5.durable_w import DurablePayW,archive_verify,archive_verify_reply
from research.strict_v26.test_pay_history import case
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase7.guarded_dispatch import GuardedFinalW,_make_cert
from research.phase6.trusted_final import Controller,ToolLedger,_pub
from research.reference_executor.wire import b64,keyid,sid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT=Path(__file__).resolve().parents[2]

def must(condition,message):
    if not condition:raise AssertionError(message)

def error(code,fn):
    try:fn()
    except ProtocolError as exc:
        must(str(exc.code)==code,f'expected {code}, got {exc.code}')
        return code
    raise AssertionError('expected '+code+' but operation succeeded')

def pay_signed_durable_paths():
    gate,meta=schema_probe(ROOT)
    must(meta['git_blob_sha1']=='86ba1bae0e4c455899af661bed44edfc5494aa5e','PAY official schema mismatch')
    paths=[('CLEAR',None,[],3,0),('FLAG',[case(i,action_class=('HOLD' if i<=4 else 'PAY')) for i in range(1,6)],['ANOMALY'],5,4),('INSUFFICIENT',[case(1),case(2)],['LOW_EVIDENCE'],2,0),
           ('DISTANCE_1000',[case(1,'1000'),case(2,'3000'),case(3,'2000')],[],3,0),
           ('ORDER_TIE',[case(3,'2100'),case(2,'1900'),case(1,'2000'),case(4,'2100'),case(5,'1900'),case(6,'2000')],[],5,0)]
    transcripts=[]
    for label,cases,required,n,d in paths:
        with tempfile.TemporaryDirectory() as temp:
            flow,op=prepare_cases(cases,ROOT)
            risk=flow.assessment_record['value']
            must(list(op.required)==required,f'wrong reviewers for {label}')
            must((int(risk['support']),int(risk['different']))==(n,d),f'risk metrics mismatch: {label}')
            if label=='ORDER_TIE':must(risk['selected_cases']==['case-01','case-06','case-02','case-03','case-04'],'wrong tied order')
            db=Path(temp)/'w.sqlite';w=DurablePayW(db)
            accepted=w.accept(flow,op)
            emitted=check_emitted(gate,flow,op,accepted)
            must(archive_verify(accepted['commit'],accepted['acceptance']),'archived cryptographic binding')
            must(archive_verify_reply(accepted['acceptance'],accepted['reply'],accepted['commit']['value']['signing_public_key']),'signed Result mismatch')
            before=w.snapshot()
            freshflow,freshop=prepare_cases(cases,ROOT)
            retry=DurablePayW(db).accept(freshflow,freshop)
            must(retry['idempotent'] and w.snapshot()==before,'replay changed persisted state')
            must(before['accepted_rows']==1 and before['reserved']==2000 and before['accept_seq']==1,'nonunique commit or bad escrow')
            transcripts.append({'path':label,'outcome':'PASS_SCOPED_INTEGRATION','expected_reviews':required,'risk_result':risk['result'],
                  'support':risk['support'],'different':risk['different'],'selected_cases':risk['selected_cases'],
                  'upstream_schema_objects_checked':emitted,'permit_ref':msgref(op.permit),
                  'commit_ref':rec_ref(accepted['commit']),'acceptance_ref':msgref(accepted['acceptance']),
                  'result_ref':msgref(accepted['reply']),'accept_seq':before['accept_seq'],'reserved':before['reserved'],
                  'read_after_restart_byte_identical':True})
    return {'checked':len(transcripts),'paths':transcripts}

def pay_hard_false_no_accept():
    # Hard false is a verified authoritative input; it may be F before a Permit exists.
    # Use previous strict verifier, then assert no persistent W state is created.
    from research.strict_v26.test_pay_history import bundle,resign_source,run
    cases=[]
    for field in ('accepted_goods','unsettled','beneficiary_active'):
        b=bundle();ev=b['evidence_record']['value']['source_envelope'];ev['body']['payload'][field]=False
        resign_source(b)
        outcome=error('CLAIM_FALSE',lambda:run(b))
        cases.append({'field':field,'expected':'CLAIM_FALSE','actual':outcome,'claim_false_before_signed_permit':True})
    return {'cases':cases,'total':len(cases)}

def pay_archive_tamper():
    with tempfile.TemporaryDirectory() as temp:
        f,op=prepare_cases(None,ROOT);w=DurablePayW(Path(temp)/'w.sqlite')
        res=w.accept(f,op)
        bad=copy.deepcopy(res['commit']);bad['value']['action']['payload']['amount_minor']='2001'
        outcome=error('COMMIT_REF',lambda:archive_verify(bad,res['acceptance']))
        must(w.snapshot()['accepted_rows']==1,'archive mutation changed state')
        return {'tamper':'accepted COMMIT action amount','detection':outcome,'accepted_unchanged':True}

def guarded_revocation():
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);c=Controller.fixture();tool=ToolLedger(d/'tool.sqlite')
        w=GuardedFinalW(d/'w.sqlite',c.public_key)
        f,op=prepare_cases(None,ROOT)
        key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        val={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
             'ledger_id':tool.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
             'kid':keyid(_pub(key)),'epoch':'1','iat':'90','exp':'2000'}
        w.activate(c.certify(f.scope,val,1,tool.head(),tool.origin),tool)
        w.accept(f,op)
        current=GuardedFinalW.initial_claim(f,op)
        w.certified_publish(_make_cert(c,current))
        dep=next(x for x in current['changes'] if x['namespace']=='POLICY')
        mutation={**dep,'revision':str(int(dep['revision'])+1),'active':False}
        w.certified_publish(_make_cert(c,{'operation_id':op.action['operation_id'],
                            'scope':f.scope,'changes':[mutation]}))
        rejected=error('REVOKED',lambda:w.claim_bound(op.action['operation_id'],sid(501)))
        state=w.accepted_operation(op.action['operation_id'])
        must(state['state']=='ACCEPTED' and w.snapshot()['reserved']==2000,'revocation incorrectly released funds')
        return {'signed_c_publication':True,'revoke_before_dispatch':'POLICY','actual':rejected,
                'accepted_state':state['state'],'reserved_unchanged':True,'dispatch_attempts':0}

def scene_signed_positive():
    outcomes=[]
    for profile,label in [('IND-DEMO-1','DEMO_NORMAL'),('IND-DEMO-1','DEMO_DEFECT'),
                          ('IND-DEMO-1','DEMO_UNCERTAIN'),('MED-DEMO-1','DEMO_A'),('MED-DEMO-1','DEMO_B')]:
        with tempfile.TemporaryDirectory() as temp:
            a,action,tid,sk,ev=build_scene(Path(temp)/'w.sqlite',profile,label)
            op=prepare_approved(a,action,tid,sk)
            accepted=a.accept(op)
            must(accepted['body']['payload']['commit_record_ref']==rec_ref(op['commit_record']),'COMMIT ref mismatch')
            must(len(op['commit_record']['value'])==21,'COMMIT fields mismatch')
            fresh=a.snapshot();again=a.accept(op)
            must(again==accepted and a.snapshot()==fresh,'not idempotent')
            attempt=a.claim(op)
            must(a.claim(op)=='EXISTING','redispatched')
            outcomes.append({'profile':profile,'label':label,'required_reviews':op['required'],
                'commit_ref':rec_ref(op['commit_record']),'acceptance_ref':msgref(accepted),
                'accepted_once':True,'attempt':attempt,'redispatch_blocked':True})
    return {'checked':len(outcomes),'paths':outcomes}

def run_all():
    funcs={'CORE-01':['pay_signed_durable_paths','scene_signed_positive'],
           'CORE-10':['pay_archive_tamper'],
           'CORE-11':['pay_signed_durable_paths','scene_signed_positive'],
           'CORE-13':['guarded_revocation'],
           'PAY-01':['pay_signed_durable_paths'],
           'PAY-02':['pay_signed_durable_paths'],
           'PAY-04':['pay_hard_false_no_accept'],
           'IND-01':['scene_signed_positive'],
           'MED-01':['scene_signed_positive'],
           'SC-02':['scene_signed_positive']}
    runs={}
    for name in sorted(set(x for arr in funcs.values() for x in arr)):
        try:
            got=globals()[name]()
            runs[name]={'status':'PASS_SCOPED_INTEGRATION','evidence':got}
        except Exception as e:
            runs[name]={'status':'FAIL_SCOPED_INTEGRATION','error':type(e).__name__+': '+str(e)}
    return funcs,runs
