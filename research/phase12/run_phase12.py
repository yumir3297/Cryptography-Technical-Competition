"""Phase12 signed, replayable scoped case evidence for CORE-15 and AUD-02C.

Only exact observations from this execution are recorded. No official PASS.
"""
from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile,sqlite3,threading,copy,io,unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from research.reference_executor.wire import ProtocolError, sid,rec_ref
from research.phase11.run_phase11 import setup_pay_aud, payclock, activate, clock, ROOT
from research.phase8.fixtures import build_scene, prepare_approved
from research.phase6.trusted_final import ToolLedger,Controller
from research.phase11.trusted_clock import seal
from research.phase12.authority import HardenedPayW,HardenedSceneW
from research.strict_v26.upstream_schema import UpstreamSchema

HERE=Path(__file__).parent
OUT=HERE/'evidence'

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def doc(value):return json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n'

def rejection(code,fn):
    try:fn()
    except ProtocolError as x:
        if x.code!=code:raise AssertionError('expected '+code+', got '+x.code)
        return {'expected':code,'observed':x.code,'confirmed':True}
    raise AssertionError('Expected rejection '+code+' but accepted')

def fixture(tmp,profile):
    if profile=='PAY-1':
        c,old,flow,op,ledger,key,cert,windows,gate=setup_pay_aud(tmp)
        w=HardenedPayW(tmp/'payw.sqlite',c.public_key,ledger=ledger)
        return {'w':w,'action':op.action,'op':op,'ledger':ledger,'key':key,
                'scope':flow.scope,'control':c,'tool_cert':cert,'windows':windows,'gate':gate}
    w,act,tid,sk,ev=build_scene(tmp/'w.sqlite',profile,authority_class=HardenedSceneW)
    op=prepare_approved(w,act,tid,sk);w.accept(op)
    ledger,key,cert=activate(w,act,tmp)
    return {'w':w,'action':act,'op':op,'ledger':ledger,'key':key,'scope':w.scope,
            'control':Controller(w.controller),'tool_cert':cert,'windows':[],
            'gate':UpstreamSchema(ROOT,profile)}

def cclock(f,purpose,lo=107,hi=107,seq=None):
    w=f['w'];profile=f['ledger'].profile;oid=f['action']['operation_id']
    if seq is None:
        with (w._read() if profile=='PAY-1' else w.db()) as c:
            seq=c.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
    return seal(f['control'],profile,f['scope'],oid,purpose,seq,lo,hi)

def snapshot(f):return f['w'].snapshot()
def claim(f,attempt,proof):return f['w'].claim_r2(f['action']['operation_id'],attempt,clock=proof)
def settle(f,rec,proof):
    if f['ledger'].profile=='PAY-1':return f['w'].settle_r2(rec,clock=proof)
    return f['w'].settle_r2(rec,f['ledger'],clock=proof)

def events(f):
    w=f['w'];pay=f['ledger'].profile=='PAY-1'
    with (w._read() if pay else w.db()) as c:
        sql='SELECT kind,operation_id,detail FROM audit ORDER BY ordinal' if pay else 'SELECT kind,operation_id,payload FROM r2_audit ORDER BY id'
        rows=c.execute(sql).fetchall()
    return [{'kind':x[0],'operation_id':x[1],'detail':json.loads(x[2])} for x in rows]

def full_auth(f):
    if f['ledger'].profile=='PAY-1':return {'control_certificate':f['tool_cert'],'published_validity_windows':f['windows']}
    with f['w'].db() as c:
        enrol=[dict(x) for x in c.execute('SELECT claim,proof,grant FROM verified_enrollment ORDER BY kid')]
    return {'control_certificate':f['tool_cert'],
            'signed_POP_enrollments':[{'tuple':json.loads(x['claim']),'proof':json.loads(x['proof']),'grant':json.loads(x['grant'])} for x in enrol]}

def recorded_commit(f):
    p=f['op']
    if f['ledger'].profile=='PAY-1':
        with f['w']._read() as c:
            row=c.execute('SELECT commit_bytes,acceptance_bytes FROM accepted WHERE operation_id=?',(f['action']['operation_id'],)).fetchone()
        return {'commit':json.loads(row['commit_bytes']),'acceptance':json.loads(row['acceptance_bytes'])}
    return {'commit':p['commit_record'],'acceptance':p['acceptance']}

def aud02c(profile):
    with tempfile.TemporaryDirectory() as d:
        f=fixture(Path(d),profile);w=f['w'];ledger=f['ledger'];op=f['action']['operation_id'];scope=f['scope']
        attempt=sid(8201)
        dispatch_clock=cclock(f,'DISPATCH');accepted=claim(f,attempt,dispatch_clock)
        fact=ledger.freeze(scope,f['action'],attempt,at=110,effect_id='effect1')
        final=ledger.reattest(scope,fact,f['key'],'tool-issuer',111,2000)
        f['gate'].validate(final,'Record_TOOL_FINAL')
        for name,obj in [('Record_COMMIT',recorded_commit(f)['commit']),('Acceptance',recorded_commit(f)['acceptance'])]:
            f['gate'].validate(obj,name)
        before=snapshot(f)
        with ledger._db() as c:
            original=c.execute('SELECT * FROM finalized WHERE operation_id=?',(op,)).fetchone()
            assert original is not None
            c.execute('DELETE FROM finalized WHERE operation_id=?',(op,))
        badclock=cclock(f,'SETTLE',112,112)
        rejected=rejection('LEDGER_FACT_NOT_FOUND',lambda:settle(f,final,badclock))
        unknown=snapshot(f);assert unknown==before
        with ledger._db() as c:c.execute('INSERT INTO finalized VALUES(?,?,?,?,?)',original)
        validclock=cclock(f,'SETTLE',113,113)
        outcome=settle(f,final,validclock)
        after=snapshot(f)
        assert outcome['status']=='SUCCEEDED' and after!=before
        return {'official_case':'AUD-02C','profile':profile,'scope':'LAB_SCOPED_FACET',
          'official_complete_pass':False,'initial_signed_objects':recorded_commit(f),
          'C_authorization':full_auth(f),'dispatch_clock':dispatch_clock,'dispatch_result':accepted,
          'original_immutable_tool_fact':fact,'tool_ledger_id':ledger.ledger_id,'tool_ledger_origin':ledger.origin,
          'signed_tool_final_while_ledger_fact_missing':final,'missing_attempt_clock':badclock,
          'missing_original_rejected':rejected,'unchanged_W_state':unknown,'state_before':before,
          'restored_same_original_fact':list(original),'settlement_clock':validclock,
          'settlement_after_restore':outcome,'W_state_after':after,'W_audit':events(f),
          'schema_structural_checks':['Record_TOOL_FINAL','Record_COMMIT','Acceptance'],
          'known_limitations':['Manipulated local SQLite fixture, not a real physical ledger failure',
                               'No network, source C/E operational independence or transport certification']}

def core15(profile):
    # Two live concurrent workers consume distinct C-signed authorizations sharing
    # the next sequence; exactly one atomic transition must win.
    with tempfile.TemporaryDirectory() as d:
        f=fixture(Path(d),profile);w=f['w'];oid=f['action']['operation_id']
        cp=cclock(f,'CANCEL');dp=cclock(f,'DISPATCH')
        for name,obj in [('Record_COMMIT',recorded_commit(f)['commit']),('Acceptance',recorded_commit(f)['acceptance'])]:
            f['gate'].validate(obj,name)
        before=snapshot(f)
        barrier=threading.Barrier(2)
        def worker(label):
            barrier.wait(timeout=10)
            try:
                val=w.cancel_r2(oid,clock=cp) if label=='CANCEL' else claim(f,sid(8202),dp)
                return {'name':label,'succeeded':True,'result':val}
            except ProtocolError as err:
                return {'name':label,'succeeded':False,'error':err.code}
        with ThreadPoolExecutor(max_workers=2) as pool:
            ps=[pool.submit(worker,label) for label in ('CANCEL','DISPATCH')]
            observed=[p.result(timeout=20) for p in ps]
        assert sum(x['succeeded'] for x in observed)==1
        after=snapshot(f)
        with (w._read() if profile=='PAY-1' else w.db()) as c:
            table='accepted' if profile=='PAY-1' else 'accept_intent'
            r=c.execute(f'SELECT * FROM {table} WHERE operation_id=?',(oid,)).fetchone()
            state=r['state'];calls=r['exec_calls'] if profile=='PAY-1' else r['calls']
        assert state in ('CANCELLED','EFFECT_UNKNOWN') and calls in (0,1)
        race={'before':before,'signed_C_cancel':cp,'signed_C_dispatch_clock':dp,
              'results':observed,'after':after,'persisted_state':state,'persisted_calls':calls,
              'W_audit':events(f)}
    # Genuine process exit immediately after committed W claim, before tool invoked.
    with tempfile.TemporaryDirectory() as d:
        f=fixture(Path(d),profile);w=f['w'];oid=f['action']['operation_id'];ledger=f['ledger']
        proof=cclock(f,'DISPATCH');attempt=sid(8203)
        config={'profile':profile,'db_path':str(Path(d)/('payw.sqlite' if profile=='PAY-1' else 'w.sqlite')),
                'ledger_path':ledger.path,'operation_id':oid,'attempt':attempt,'clock':proof}
        src=Path(d)/'child_input.json';src.write_text(doc(config),encoding='utf8')
        before=snapshot(f)
        run=subprocess.run([sys.executable,'-m','research.phase12.crash_worker',str(src)],
                           cwd=ROOT,timeout=30,capture_output=True,text=True)
        assert run.returncode==79,(run.returncode,run.stderr)
        # Deliberately no tool freeze; an absent fact must not be synthesized as failure.
        neww=HardenedPayW(config['db_path'],f['control'].public_key,ledger=ledger) if profile=='PAY-1' else HardenedSceneW(config['db_path'],profile)
        f['w']=neww
        post=snapshot(f)
        again_clock=cclock(f,'DISPATCH',108,108)
        no_redispatch=rejection('NO_REDISPATCH',lambda:claim(f,sid(8204),again_clock))
        ccp=cclock(f,'CANCEL',108,108)
        too_late=f['w'].cancel_r2(oid,clock=ccp)
        assert too_late['status']=='TOO_LATE' and all(snapshot(f)[k]==v for k,v in post.items() if k!='audit_rows')
        assert ledger.lookup(oid,attempt) is None
        crash={'W_before':before,'signed_C_dispatch_clock':proof,'dispatch_attempt':attempt,
               'subprocess_abrupt_exit_code':run.returncode,'W_after_restart':post,
               'no_reclaim_with_fresh_attempt_clock':again_clock,'no_redispatch':no_redispatch,
               'signed_cancel_after_started':ccp,'cancel_refused':too_late,
               'no_tool_original_fact':ledger.lookup(oid,attempt) is None,'W_audit':events(f),
               'signed_initial_objects':recorded_commit(f),'C_authorization':full_auth(f)}
        return {'official_case':'CORE-15','profile':profile,'scope':'LAB_SCOPED_FACET',
                'official_complete_pass':False,'concurrent_claim_cancel':race,
                'crash_after_claim_before_tool':crash,'known_limitations':[
                'A deterministic same-sequence contention run is not an exhaustive real scheduling model',
                'The worker exits after W commit, not after verified physical tool effect',
                'Missing authenticated dispatch delivery and full multi-service cancellation protocol']}

def legacy_pay_gap():
    with tempfile.TemporaryDirectory() as d:
        f=fixture(Path(d),'PAY-1');w=f['w'];old=__import__('research.phase11.pay_r2',fromlist=['StrictPayW']).StrictPayW(Path(d)/'payw.sqlite',f['control'].public_key)
        op=f['action']['operation_id'];attempt=sid(8277)
        old.claim_r2(op,attempt,clock=cclock(f,'DISPATCH'))
        ledger=f['ledger'];fact=ledger.freeze(f['scope'],f['action'],attempt,at=110)
        signed=ledger.reattest(f['scope'],fact,f['key'],'tool-issuer',111,2000)
        with ledger._db() as c:c.execute('DELETE FROM finalized WHERE operation_id=?',(op,))
        before=old.snapshot();observed=old.settle_r2(signed,clock=cclock(f,'SETTLE',112,112))
        after=old.snapshot()
        assert observed['status']=='SUCCEEDED' and before!=after and ledger.lookup(op,attempt) is None
        return {'phase11_existing_strict_pay_code_path':'settle_r2 on signed final with erased independent ledger fact',
                'observed_phase11_accepts_without_original_fact':True,
                'old_signed_tool_final':signed,'ledger_fact_absent':True,'old_before':before,'old_after':after,
                'old_settlement_result':observed,'interpretation':'Reproduced scoped AUD-02C gap; Phase12 HardenedPayW now rejects it'}

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    specs=['CORE-15','AUD-02C'];profiles=('PAY-1','IND-DEMO-1','MED-DEMO-1')
    entries={}
    for case in specs:
        profiles_trace=[]
        for p in profiles:
            datum=core15(p) if case=='CORE-15' else aud02c(p)
            profiles_trace.append(datum)
        path=OUT/(case+'.json');path.write_text(doc({'contract':'ZJJ-CORE-2.6-R2','case':case,
                        'official_complete_pass':False,'profiles':profiles_trace}),encoding='utf8')
        entries[case]={'path':str(path.relative_to(ROOT)),'sha256':digest(path),'profiles':list(profiles)}
    gap=OUT/'PAY_LEGACY_AUD02C_GAP.json';gap.write_text(doc(legacy_pay_gap()),encoding='utf8')
    source_files=['research/phase12/authority.py','research/phase12/crash_worker.py',
                  'research/phase12/test_phase12.py','research/phase12/run_phase12.py']
    manifest={'contract':'ZJJ-CORE-2.6-R2','phase':12,'generated_utc':datetime.now(timezone.utc).isoformat(),
              'official_complete_passes_from_phase12':0,'targeted_slices':entries,
              'phase11_pay_gap':{'path':str(gap.relative_to(ROOT)),'sha256':digest(gap)},
              'source_sha256':{s:digest(ROOT/s) for s in source_files},
              'limitations':['No full C/E managed independent root/issuer graph',
                 'PAY and IND/MED remain separate adapter instances, not one deployed W',
                 'No authenticated transport/0-RTT/STATUS life cycle',
                 'The separate tool SQLite is a simulator, not actual physical-effect attestation',
                 'Only CORE-15 and AUD-02C added new Phase12 scoped facets'],
              'reproduce':['python -m unittest research.phase12.test_phase12 -q',
                           'python -m research.phase12.run_phase12',
                           'python -m research.formal39.run_formal39']}
    report=HERE/'phase12_report.json';report.write_text(doc(manifest),encoding='utf8')
    return manifest

if __name__=='__main__':
    result=run()
    print(doc({'phase':result['phase'],'targeted_case_ids':list(result['targeted_slices']),
              'triprofile_traces':6,'legacy_pay_gap_confirmed':True,
              'official_complete_passes_from_phase12':0}))
