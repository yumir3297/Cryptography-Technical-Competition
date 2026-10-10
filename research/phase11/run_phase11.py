"""Pinned Phase11 executed facet transcript generator. Use from repository root:

    python -m research.phase11.run_phase11

Produces independently inspectable signed inputs, verified Schema outcomes,
transaction snapshots, C certificates, immutable tool facts and W audit log.
All phase11 results are scoped facets, NEVER automatic full official PASS.
"""
from __future__ import annotations
import copy,hashlib,json,tempfile,sqlite3,io,unittest
from pathlib import Path
from datetime import datetime,timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.reference_executor.wire import ProtocolError,b64,keyid,sid,rec_ref,envelope,canonical
from research.phase6.trusted_final import ToolLedger,Controller,_pub,final_fact_id,final_sign_bytes
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase8.scene_authority import ROLES
from research.phase5.run_phase5 import prepare_cases
from research.phase7.guarded_dispatch import _make_cert
from research.phase11.scene_r2 import SceneR2W
from research.phase11.pay_r2 import StrictPayW,sign_window
from research.phase11.trusted_clock import seal
from research.strict_v26.upstream_schema import UpstreamSchema
from research.phase11 import test_phase11

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
OUT=HERE/'evidence'
IDS=('CORE-03','CORE-13','AUD-02A','AUD-02B')
BLOBS={'manifest':'b0bc9dbeedac135f6520b5e93729f63686d97bb4',
       'pay':'86ba1bae0e4c455899af661bed44edfc5494aa5e',
       'industrial':'f937286b1be32b2a8356b991a93770abff430578',
       'medical':'5e43b803ed32a3359e4ad2b7e48a3c96f7fd9482'}

def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def expect(code,f):
    try:f()
    except ProtocolError as exc:
        if exc.code!=code:raise AssertionError(f'Expected {code}, received {exc.code}')
        return {'observed':exc.code,'expected':code,'confirmed':True}
    raise AssertionError('Expected '+code+' but unexpectedly accepted')

def certs(a):
    with a.db() as conn:
        enrollment=[dict(x) for x in conn.execute('SELECT claim,proof,grant FROM verified_enrollment ORDER BY kid')]
        cb=[json.loads(x['blob']) for x in conn.execute("SELECT blob FROM journal WHERE kind='C' ORDER BY seq")]
    return {'registered_pop_grants':[{'tuple':json.loads(x['claim']),'proof':json.loads(x['proof']),
                                      'grant':json.loads(x['grant'])} for x in enrollment],
            'signed_C_publications':cb}

def clock(a,op,purpose,lo,hi):
    with a.db() as c:seq=c.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
    return seal(Controller(a.controller),a.profile,a.scope,op,purpose,seq,lo,hi)

def claim(a,op,attempt,lo=107,hi=107):
    cc=clock(a,op,'DISPATCH',lo,hi)
    result=a.claim_r2(op,attempt,clock=cc)
    return cc,result

def settle(a,record,ledger,lo=111,hi=111):
    cc=clock(a,record['value']['operation_id'],'SETTLE',lo,hi)
    result=a.settle_r2(record,ledger,clock=cc)
    return cc,result

def setup_scene(temp,profile,accept=True):
    a,action,tid,sk,ev=build_scene(temp/'w.sqlite',profile,authority_class=SceneR2W)
    op=prepare_approved(a,action,tid,sk)
    if accept:a.accept(op)
    gate=UpstreamSchema(ROOT,profile)
    for name,item in [('Record_KEY_GRANT',a.current_record('KEY',[a.actors['G'].kid])),
                      ('Permit',op['permit']),('Record_BASIS',op['basis'])]:gate.validate(item,name)
    if accept:
        for name,item in [('Record_COMMIT',op['commit_record']),('Acceptance',op['acceptance'])]:gate.validate(item,name)
    return a,action,op,gate

def activate(a,action,temp,*,seed=b'Q',epoch=1,rev=1,ledger=None):
    ledger=ledger or ToolLedger(temp/'tool.sqlite',profile=a.profile)
    private=Ed25519PrivateKey.from_private_bytes(seed*32)
    value={'issuer':'tool-issuer','tool':action['tool'],'tool_version':action['tool_version'],
           'destination':action['destination'],'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2',
           'public_key':b64(_pub(private)),'kid':keyid(_pub(private)),'epoch':str(epoch),'iat':'90','exp':'2000'}
    certificate=Controller(a.controller).certify(a.scope,value,rev,ledger.head(),ledger.origin,profile=a.profile)
    UpstreamSchema(ROOT,a.profile).validate(certificate['claim']['record'],'Record_TOOL_TRUST')
    a.activate_tool(certificate,ledger,now=107+rev)
    return ledger,private,certificate

def pay_core03():
    with tempfile.TemporaryDirectory() as td:
        flow,op=prepare_cases(None,ROOT)
        signed=copy.deepcopy(op.permit)
        complete=copy.deepcopy(signed['body']['deps'])
        signed['body']['deps']=signed['body']['deps'][:-1]
        signed['sig']=b64(flow.actors['G'].key.sign(canonical(['ZJJ-SIG-v1',signed['protected'],signed['body']])))
        gate=UpstreamSchema(ROOT,'PAY-1')
        envelope(signed,{flow.actors['G'].kid:flow.actors['G']},now=flow.now)
        gate.validate(signed,'Permit')
        op.permit=signed
        flow.challenge(op)
        w=StrictPayW(Path(td)/'payw.sqlite',Controller.fixture().public_key)
        before=w.snapshot()
        refusal=expect('DEP_CONFLICT',lambda:w.accept(flow,op))
        after=w.snapshot()
        assert before==after and after['accepted_rows']==0
        return {'profile':'PAY-1','status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'signed_reduced_permit':signed,'omitted_dep':complete[-1],
                'complete_independently_reconstructed_deps':complete,'signed_challenge':op.challenge,
                'signed_challenge_request':op.challenge_request,
                'refusal':refusal,'before':before,'after':after,
                'official_schema_checked':['Permit'],'signer':'current fixture G (Ed25519)'}

def core03(profile):
    with tempfile.TemporaryDirectory() as td:
        a,action,op,gate=setup_scene(Path(td),profile,accept=False)
        missing=copy.deepcopy(op['deps'][:-1]);true_permit=op['permit']
        altered=copy.deepcopy(op)
        altered['permit']=a._env('G','Permit',true_permit['body']['payload'],refs=true_permit['body']['refs'],
                                 deps=missing,aud=('H','X'),at=104,nonce=4,ttl=116)
        envelope(altered['permit'],{a.actors['G'].kid:a.actors['G']},now=106)
        gate.validate(altered['permit'],'Permit')
        before=a.snapshot();reject=expect('DEP_CONFLICT',lambda:a.accept(altered));after=a.snapshot()
        assert before==after and before['accepts']==0
        return {'profile':profile,'status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'signed_incoming_permit':altered['permit'],'original_full_deps':op['deps'],
                'omitted_dep':op['deps'][-1], 'basis':op['basis'],'g_signature_valid':True,
                'independent_W_rebuilt_rejection':reject,'before':before,'after':after,
                'official_schema_checked':['Permit','Record_BASIS','Record_KEY_GRANT'],
                'control_and_enrolment':certs(a),'audit':a.audit_r2()}

def core13(profile):
    cases=[]
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);a,action,op,gate=setup_scene(d,profile)
        ledger,signer,t=activate(a,action,d)
        actor=a.actors['H'];rolekey=a.role_key(actor,ROLES[profile]['H'])
        certificate=a.certify('ROLE',rolekey,a.current_record('ROLE',rolekey),active=False)
        a.publish_cert(certificate)
        before=a.snapshot();cc,result=claim(a,action['operation_id'],sid(901))
        after=a.snapshot()
        assert result['status']=='CANCELLED' and result['reason']=='REVOKED' and after['calls']==0 and after['reserved']==0
        cases.append({'scenario':'C signed ROLE revocation before claim','input_C_certificate':certificate,
                      'trusted_clock':cc,'before':before,'after':after,'result':result,'audit':a.audit_r2(),
                      'signed_commit':op['commit_record'],'signed_acceptance':op['acceptance']})
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);a,action,op,gate=setup_scene(d,profile);ledger,signer,t=activate(a,action,d)
        mid=a.snapshot();cc=clock(a,action['operation_id'],'DISPATCH',219,220)
        unknown=expect('UNKNOWN_TIME',lambda:a.claim_r2(action['operation_id'],sid(902),clock=cc))
        still=a.snapshot();assert mid==still and still['reserved']==1 and still['calls']==0
        finalcc,result=claim(a,action['operation_id'],sid(903),221,221)
        end=a.snapshot();assert end['calls']==0 and end['reserved']==0
        cases.append({'scenario':'trusted time interval crosses expiry, then certainly expired',
                      'crossing_clock':cc,'crossing_rejection':unknown,'before':mid,'preserved':still,
                      'expired_clock':finalcc,'cancelled':result,'after':end,'audit':a.audit_r2()})
    return {'profile':profile,'status':'PASS_SCOPED_FACET','official_complete_pass':False,'cases':cases}

def aud02a(profile):
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);a,action,op,gate=setup_scene(d,profile)
        ledger,key,cert=activate(a,action,d)
        attempt=sid(905);cc,cl=claim(a,action['operation_id'],attempt)
        fact=ledger.freeze(a.scope,action,attempt,at=110)
        expired=ledger.reattest(a.scope,fact,key,'tool-issuer',111,2000)
        gate.validate(expired,'Record_TOOL_FINAL')
        oldclock=clock(a,action['operation_id'],'SETTLE',240,240)
        reject=expect('FINAL_EXPIRED',lambda:a.settle_r2(expired,ledger,clock=oldclock))
        unchanged=a.snapshot();assert unchanged['reserved']==1 and unchanged['settlements']==0
        new=ledger.reattest(a.scope,fact,key,'tool-issuer',240,2000)
        gate.validate(new,'Record_TOOL_FINAL')
        newclock,done=settle(a,new,ledger,241,241)
        final=a.snapshot();assert done['status']=='SUCCEEDED' and final['settlements']==1 and final['calls']==1
        return {'profile':profile,'status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'tool_C_certificate':cert,'accepted_COMMIT':op['commit_record'],'acceptance':op['acceptance'],
                'dispatch_time':cc,'dispatch':cl,'immutable_ledger_fact':fact,'ledger_origin':ledger.origin,
                'expired_first_TOOL_FINAL':expired,'expired_attempt_clock':oldclock,'expiry_rejected':reject,
                'snapshot_after_rejection':unchanged, 'current_TOOL_FINAL':new,'fresh_clock':newclock,'settlement':done,
                'final_snapshot':final,'fact_id_unchanged':final_fact_id(new)==final_fact_id(expired),
                'record_ref_changed':rec_ref(new)!=rec_ref(expired),
                'official_schema_checked':['Record_TOOL_FINAL','Record_TOOL_TRUST','Record_COMMIT','Acceptance'],
                'C_and_enrollment':certs(a),'audit':a.audit_r2()}

def aud02b(profile):
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);a,action,op,gate=setup_scene(d,profile)
        ledger,oldkey,oldcert=activate(a,action,d)
        attempt=sid(906);cc,cl=claim(a,action['operation_id'],attempt)
        fact=ledger.freeze(a.scope,action,attempt,at=110)
        old=ledger.reattest(a.scope,fact,oldkey,'tool-issuer',111,2000)
        _,key,newcert=activate(a,action,d,seed=b'R',epoch=2,rev=2,ledger=ledger)
        oldclock=clock(a,action['operation_id'],'SETTLE',114,114)
        reject=expect('FINAL_SIGNER',lambda:a.settle_r2(old,ledger,clock=oldclock))
        fresh=ledger.reattest(a.scope,fact,key,'tool-issuer',114,2000)
        gate.validate(fresh,'Record_TOOL_FINAL')
        curclock,done=settle(a,fresh,ledger,115,115)
        snapshot=a.snapshot()
        same=ledger.reattest(a.scope,fact,key,'tool-issuer',116,2000)
        dup_clock,dup=settle(a,same,ledger,117,117)
        assert dup['idempotent'] and a.snapshot()==snapshot
        wrong=copy.deepcopy(same);wrong['value']['effect_id']='unexpected-other-effect'
        wrong['value']['attestation']['sig']=b64(key.sign(final_sign_bytes(wrong)))
        gate.validate(wrong,'Record_TOOL_FINAL')
        conclock,outcome=settle(a,wrong,ledger,118,118)
        end=a.snapshot()
        assert outcome['status']=='HALTED' and end==snapshot and any(x['kind']=='CONTRADICTION' for x in a.audit_r2())
        return {'profile':profile,'status':'PASS_SCOPED_FACET','official_complete_pass':False,
            'old_C_certificate':oldcert,'new_C_certificate':newcert,'tool_ledger_origin':ledger.origin,
            'frozen_fact':fact,'dispatch_clock':cc,'dispatch':cl,'old_TOOL_FINAL':old,
            'old_clock':oldclock,'old_signer_rejected':reject,'new_TOOL_FINAL':fresh,
            'fresh_clock':curclock,'once_settled':done,'duplicate_current_TOOL_FINAL':same,
            'duplicate_clock':dup_clock,'duplicate':dup,'trusted_signer_equivocation_record':wrong,
            'equivocation_clock':conclock,'equivocation_result':outcome,
            'before_equivocation_snapshot':snapshot,'after_equivocation_snapshot':end,
            'same_fact_id':final_fact_id(old)==final_fact_id(fresh)==final_fact_id(same),
            'different_refs':len({rec_ref(old),rec_ref(fresh),rec_ref(same)})==3,
            'official_schema_checked':['Record_TOOL_FINAL','Record_TOOL_TRUST','Record_COMMIT'],
            'C_and_enrollment':certs(a),'audit':a.audit_r2()}

def setup_pay_aud(temp):
    c=Controller.fixture();f,op=prepare_cases(None,ROOT)
    w=StrictPayW(temp/'payw.sqlite',c.public_key);ledger=ToolLedger(temp/'pay-tool.sqlite')
    key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
    v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
       'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
       'kid':keyid(_pub(key)),'epoch':'1','iat':'90','exp':'2000'}
    cert=c.certify(f.scope,v,1,ledger.head(),ledger.origin)
    gate=UpstreamSchema(ROOT,'PAY-1');gate.validate(cert['claim']['record'],'Record_TOOL_TRUST')
    w.activate(cert,ledger);w.accept(f,op)
    cl=w.initial_claim(f,op);w.certified_publish(_make_cert(c,cl))
    windows=[]
    for d in cl['changes']:
        x={'scope':f.scope,'dep':{k:d[k] for k in ('namespace','key','revision','ref')},
           'seq':'1','iat':'90','exp':'2000'}
        signed=sign_window(c,x);w.publish_window(signed);windows.append(signed)
    return c,w,f,op,ledger,key,cert,windows,gate

def payclock(w,c,scope,op,purpose,lo,hi):
    with w._read() as db:seq=db.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
    return seal(c,'PAY-1',scope,op,purpose,seq,lo,hi)

def pay_aud02a():
    with tempfile.TemporaryDirectory() as td:
        c,w,f,op,ledger,key,cert,windows,gate=setup_pay_aud(Path(td))
        action=op.action;att=sid(921)
        dc=payclock(w,c,f.scope,action['operation_id'],'DISPATCH',107,107)
        claimed=w.claim_r2(action['operation_id'],att,clock=dc)
        fact=ledger.freeze(f.scope,action,att,at=110)
        expired=ledger.reattest(f.scope,fact,key,'tool-issuer',111,2000)
        gate.validate(expired,'Record_TOOL_FINAL')
        oldc=payclock(w,c,f.scope,action['operation_id'],'SETTLE',240,240)
        failure=expect('FINAL_EXPIRED',lambda:w.settle_r2(expired,clock=oldc))
        before=w.snapshot();assert before['reserved']==2000 and before['spent']==0
        fresh=ledger.reattest(f.scope,fact,key,'tool-issuer',240,2000)
        gate.validate(fresh,'Record_TOOL_FINAL')
        now=payclock(w,c,f.scope,action['operation_id'],'SETTLE',241,241)
        done=w.settle_r2(fresh,clock=now)
        after=w.snapshot();assert after['reserved']==0 and after['spent']==2000
        return {'profile':'PAY-1','status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'controller_certificate':cert,'controlled_publication':windows,'dispatch_clock':dc,
                'dispatch':claimed,'fact':fact,'expired_record':expired,'expiry_clock':oldc,
                'expiry_reject':failure,'unchanged':before,'current_record':fresh,'current_clock':now,
                'settlement':done,'after':after,'matching_fact_id':final_fact_id(expired)==final_fact_id(fresh),
                'official_schema_checked':['Record_TOOL_TRUST','Record_TOOL_FINAL'],
                'signed_commit':w.accepted_operation(action['operation_id'])['commit'],
                'audit':w.audit()}

def pay_aud02b():
    with tempfile.TemporaryDirectory() as td:
        c,w,f,op,ledger,key,cert,windows,gate=setup_pay_aud(Path(td))
        act=op.action;att=sid(922)
        dc=payclock(w,c,f.scope,act['operation_id'],'DISPATCH',107,107)
        claimed=w.claim_r2(act['operation_id'],att,clock=dc)
        fact=ledger.freeze(f.scope,act,att,at=110)
        old=ledger.reattest(f.scope,fact,key,'tool-issuer',111,2000)
        newkey=Ed25519PrivateKey.from_private_bytes(b'R'*32)
        v=dict(cert['claim']['record']['value']);v['epoch']='2';v['kid']=keyid(_pub(newkey));v['public_key']=b64(_pub(newkey))
        newcert=c.certify(f.scope,v,2,ledger.head(),ledger.origin)
        gate.validate(newcert['claim']['record'],'Record_TOOL_TRUST');w.activate(newcert,ledger,now=112)
        oldc=payclock(w,c,f.scope,act['operation_id'],'SETTLE',112,112)
        failure=expect('FINAL_SIGNER',lambda:w.settle_r2(old,clock=oldc))
        fresh=ledger.reattest(f.scope,fact,newkey,'tool-issuer',113,2000)
        gate.validate(fresh,'Record_TOOL_FINAL')
        now=payclock(w,c,f.scope,act['operation_id'],'SETTLE',114,114)
        done=w.settle_r2(fresh,clock=now)
        after=w.snapshot()
        same=ledger.reattest(f.scope,fact,newkey,'tool-issuer',115,2000)
        duptime=payclock(w,c,f.scope,act['operation_id'],'SETTLE',116,116)
        idem=w.settle_r2(same,clock=duptime)
        assert idem['idempotent'] and after==w.snapshot()
        wrong=copy.deepcopy(same);wrong['value']['effect_id']='different-effect'
        wrong['value']['attestation']['sig']=b64(newkey.sign(final_sign_bytes(wrong)))
        gate.validate(wrong,'Record_TOOL_FINAL')
        contradictory_time=payclock(w,c,f.scope,act['operation_id'],'SETTLE',117,117)
        halted=w.settle_r2(wrong,clock=contradictory_time)
        assert halted['status']=='HALTED' and after['spent']==w.snapshot()['spent']
        return {'profile':'PAY-1','status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'old_controller_cert':cert,'new_controller_cert':newcert,'frozen_tool_fact':fact,
                'dispatch_clock':dc,'dispatch':claimed,'old_final':old,'old_clock':oldc,'old_reject':failure,
                'current_final':fresh,'current_clock':now,'settled':done,'duplicate_current_final':same,
                'duplicate_clock':duptime,'idempotent':idem,'trusted_signed_conflict':wrong,
                'conflict_clock':contradictory_time,'conflict_result':halted,'before_halt':after,
                'after_halt':w.snapshot(),'same_fact_id':final_fact_id(fresh)==final_fact_id(old),
                'official_schema_checked':['Record_TOOL_FINAL','Record_TOOL_TRUST'],
                'audit':w.audit()}

def pay_core13():
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);c=Controller.fixture();f,op=prepare_cases(None,ROOT)
        w=StrictPayW(d/'w.sqlite',c.public_key);ledger=ToolLedger(d/'tool.sqlite')
        key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        v={'issuer':'tool-issuer','tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
           'ledger_id':ledger.ledger_id,'evidence_method':'tool-final-v2','public_key':b64(_pub(key)),
           'kid':keyid(_pub(key)),'epoch':'1','iat':'90','exp':'2000'}
        cert=c.certify(f.scope,v,1,ledger.head(),ledger.origin)
        w.activate(cert,ledger);w.accept(f,op)
        claimstate=w.initial_claim(f,op);signed_c=_make_cert(c,claimstate);w.certified_publish(signed_c)
        windowcerts=[]
        for dep in claimstate['changes']:
            x={'scope':f.scope,'dep':{k:dep[k] for k in ('namespace','key','revision','ref')},
               'seq':'1','iat':'90','exp':'108'}
            w.publish_window(sign_window(c,x));windowcerts.append(sign_window(c,x))
        before=w.snapshot()
        with w._read() as cx: seq=cx.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
        unknownclock=seal(c,'PAY-1',f.scope,op.action['operation_id'],'DISPATCH',seq,107,108)
        blocked=expect('UNKNOWN_TIME',lambda:w.claim_r2(op.action['operation_id'],sid(907),clock=unknownclock))
        unchanged=w.snapshot();assert before==unchanged
        expiredclock=seal(c,'PAY-1',f.scope,op.action['operation_id'],'DISPATCH',seq,109,109)
        cancelled=w.claim_r2(op.action['operation_id'],sid(908),clock=expiredclock)
        after=w.snapshot();assert cancelled['status']=='CANCELLED' and after['reserved']==0
        return {'profile':'PAY-1','status':'PASS_SCOPED_FACET','official_complete_pass':False,
                'signed_C_dependency_publication':signed_c,'signed_C_time_windows':windowcerts,
                'unknown_clock':unknownclock,'unknown_reject':blocked,'before':before,'still_occupied':unchanged,
                'expire_clock':expiredclock,'cancel_result':cancelled,'after':after,
                'accepted_commit':w.accepted_operation(op.action['operation_id'])['commit'],
                'audit':w.audit()}

def main():
    OUT.mkdir(exist_ok=True)
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_phase11)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (HERE/'test_run.txt').write_text(stream.getvalue(),encoding='utf8')
    if not result.wasSuccessful():raise SystemExit('PHASE11_UNIT_FACETS_FAILED: '+stream.getvalue())
    manifest=json.loads((ROOT/'system_dev/v26/semantic_cases.json').read_text(encoding='utf8'))
    mapping={x['id']:x for x in manifest['cases']}
    records={}
    for case,method in [('CORE-03',core03),('CORE-13',core13),('AUD-02A',aud02a),('AUD-02B',aud02b)]:
        per=[]
        for profile in ('IND-DEMO-1','MED-DEMO-1'):
            per.append(method(profile))
        if case=='CORE-03':per.insert(0,pay_core03())
        elif case=='CORE-13':per.insert(0,pay_core13())
        elif case=='AUD-02A':per.insert(0,pay_aud02a())
        elif case=='AUD-02B':per.insert(0,pay_aud02b())
        report={'id':case,'official_manifest_expectation':mapping[case]['expected'],
                'official_scenario':mapping[case]['scenario'],'official_complete_pass':False,
                'facet_status':'PASS_SCOPED_INTEGRATION',
                'controlled_time_source':'C signed lab assertions (not external trusted clock)',
                'profiles':per}
        filename=OUT/(case+'.json');filename.write_text(dump(report),encoding='utf8')
        records[case]={'status':'PASS_SCOPED_INTEGRATION','path':str(filename.relative_to(ROOT)),
                       'sha256':sha(filename),'profiles':[x['profile'] for x in per]}
    source_files=[ROOT/x for x in ('research/phase5/durable_w.py','research/phase6/trusted_final.py',
        'research/phase8/fixtures.py','research/phase11/scene_r2.py','research/phase11/pay_r2.py',
        'research/phase11/trusted_clock.py','research/phase11/test_phase11.py',
        'research/phase11/run_phase11.py')]
    report={'source_sha256':{str(x.relative_to(ROOT)):sha(x) for x in source_files},
            'generated_utc':datetime.now(timezone.utc).isoformat(),
            'contract':'ZJJ-CORE-2.6-R2','phase':11,'pinned_git_blobs':BLOBS,
            'official_complete_passes_from_phase11':0,'official_cases_total':39,
            'scope':'Strict local controller+signed deterministic time+single-authority W and separate durable simulated tool ledger; not full C/E governance or physical effect',
            'phase11_unittests':{'run':result.testsRun,'failed':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)},
            'targeted_slices':records,
            'known_nonconformance_gaps':['Trusted controller and time source are local laboratory fixtures, not independently operated C/E governance or quorum time',
               'PAY and scene W adapters share transaction semantics but are not one deployed W service or one global datastore',
               'Network/status/aud/path/zero-RTT proof across the official transport contract not exercised',
               'No real external physical tool dispatch or distributed atomic commit across tool ledger and W',
               'Not all official per-case negative subvariants, attestation fail-stops and independent reviewer checks are closed',
               'Official Schema structural validation does not establish semantic requirements or all x-zjj-order constraints'],
            'repro':['python -m unittest research.phase11.test_phase11 -q','python -m research.phase11.run_phase11',
                     'python -m research.formal39.run_formal39']}
    (HERE/'phase11_report.json').write_text(dump(report),encoding='utf8')
    print(dump({'phase11_tests':report['phase11_unittests'],'target_facets':records,'official_complete_pass':0}))
    return 0

if __name__=='__main__':raise SystemExit(main())
