"""Phase13 CORE-01 process-separated LAB experiment and *read-only* verifier.

Do not treat this as independent production C/E or an official complete PASS.
The bootstrap fixture still possesses signer keys; stage separation tests persistence
and independently verifies cryptographic archives, not secure key custody.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, sqlite3, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.reference_executor.wire import (ProtocolError, b64, raw, keyid, sid, rec_ref,
    msgref, envelope, require, strict_verify, action_hash)
from research.phase6.trusted_final import ToolLedger, Controller, verify_certificate, final_fact, final_sign_bytes
from research.phase8.fixtures import build_scene, prepare_approved
from research.phase11.run_phase11 import setup_pay_aud, activate, clock, payclock, ROOT
from research.phase11.trusted_clock import checked_clock, DOMAIN as CLOCK_DOMAIN
from research.phase12.authority import HardenedSceneW,HardenedPayW
from research.strict_v26.upstream_schema import UpstreamSchema
from research.reference_executor.wire import canonical

PROFILES=('PAY-1','IND-DEMO-1','MED-DEMO-1')
HERE=Path(__file__).resolve().parent

def write(path,data):
    Path(path).write_text(json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dbpath(d,p):return Path(d)/('payw.sqlite' if p=='PAY-1' else 'w.sqlite')
def ledgerpath(d):return Path(d)/'tool.sqlite'
def witnesspath(d):return Path(d)/'witness.json'
def _publics(actors):return {k:{'name':x.name,'kid':x.kid,'pub':b64(x.pub),'purposes':sorted(x.purposes)} for k,x in actors.items()}

def _w(d,p):
    ledger=ToolLedger(ledgerpath(d),profile=p)
    if p=='PAY-1':return HardenedPayW(dbpath(d,p),Controller.fixture().public_key,ledger=ledger),ledger
    return HardenedSceneW(dbpath(d,p),p),ledger

def bootstrap(d,p):
    d=Path(d);d.mkdir(parents=True,exist_ok=True)
    if p=='PAY-1':
        # Initialise all C publications as signed Phase11 fixtures; new strict W
        # is opened separately for later claim and settlement.
        c,base,flow,op,oldledger,key,cert,windows,gate=setup_pay_aud(d)
        # Fixture's ledger is named pay-tool.sqlite, use the same bytes at the
        # dedicated Phase13 path before any tool effect (copy done via backup).
        with oldledger._db() as old,sqlite3.connect(ledgerpath(d)) as new:old.backup(new)
        ledger=ToolLedger(ledgerpath(d),profile=p)
        # Note: the old tool-trust cert references ledger origin; identical copy
        # retains origin/head and is intentionally an isolated research fixture.
        acceptance=base.accepted_operation(op.action['operation_id'])['acceptance']
        commit=base.accepted_operation(op.action['operation_id'])['commit']
        messages={'permit':op.permit,'issue':op.issue,'challenge_request':op.challenge_request,
                  'challenge':op.challenge,'proof':op.proof,'authorization':op.authorization,
                  'acceptance':acceptance}
        extra={'tool_certificate':cert,'control_windows':windows,
               'signed_publish':None}
        pub=_publics(flow.actors)
        root=b64(c.public_key)
        action=op.action;scope=flow.scope
        w,_=_w(d,p)
    else:
        w,action,tid,sk,ev=build_scene(dbpath(d,p),p,authority_class=HardenedSceneW)
        op=prepare_approved(w,action,tid,sk)
        w.accept(op)
        ledger,key,cert=activate(w,action,d)
        messages={'permit':op['permit'],'issue':op['issue'],'challenge_request':op['challenge_request'],
                  'challenge':op['challenge'],'proof':op['proof'],'authorization':op['authorization'],
                  'acceptance':op['acceptance']}
        for i,review in enumerate(op['reviews']):messages[f'review_{i}']=review
        extra={'tool_certificate':cert,'control_windows':[], 'signed_publish':None}
        pub=_publics(w.actors);root=b64(w.root_public);commit=op['commit_record'];scope=w.scope
    gate=UpstreamSchema(ROOT,p)
    gate.validate(commit,'Record_COMMIT')
    gate.validate(messages['acceptance'],'Acceptance')
    gate.validate(messages['permit'],'Permit')
    gate.validate(cert['claim']['record'],'Record_TOOL_TRUST')
    require(w.snapshot()['reserved']>0,'ACCEPT_NOT_RESERVED')
    require((w.snapshot()['accepted_rows'] if p=='PAY-1' else w.snapshot()['accepts'])==1,'ACCEPT_COUNT')
    wtn={'candidate':'CORE-01','profile':p,'scope':scope,'action':action,'operation_id':action['operation_id'],
         'official_complete_pass':False,'fixture_root_public':root,'fixture_actor_public':pub,
         'signed_messages':messages,'commit':commit,'tool_certificate':cert,
         'C_windows':extra['control_windows'],'initial_snapshot':w.snapshot(),
         'stage_pids':{'bootstrap':__import__('os').getpid()},'process_stage_outcomes':{}}
    write(witnesspath(d),wtn)
    return {'stage':'bootstrap','profile':p,'accepted':True,'commit_ref':rec_ref(commit),
            'acceptance_ref':msgref(messages['acceptance'])}

def stage(d,which):
    d=Path(d);v=read(witnesspath(d));p=v['profile'];oid=v['operation_id'];action=v['action']
    if which=='tool':
        require('dispatch' in v,'NO_DISPATCH')
        ledger=ToolLedger(ledgerpath(d),profile=p)
        fact=ledger.freeze(v['scope'],action,v['dispatch']['attempt'],at=110,
                           effect_id='phase13-effect-'+('pay' if p=='PAY-1' else ('ind' if p=='IND-DEMO-1' else 'med')))
        key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        signed=ledger.reattest(v['scope'],fact,key,'tool-issuer',111,2000)
        UpstreamSchema(ROOT,p).validate(signed,'Record_TOOL_FINAL')
        v['tool']={'fact':fact,'signed_final':signed,'ledger_origin':ledger.origin}
        result={'stage':'tool','fact_frozen':True,'tool_final_ref':rec_ref(signed)}
    else:
        w,ledger=_w(d,p)
        if which=='claim':
            before=w.snapshot()
            controller=Controller.fixture() if p=='PAY-1' else Controller(w.controller)
            tm=payclock(w,controller,v['scope'],oid,'DISPATCH',107,107) if p=='PAY-1' else clock(w,oid,'DISPATCH',107,107)
            attempt=sid(1313)
            res=w.claim_r2(oid,attempt,clock=tm)
            require(res['status']=='CLAIMED','CLAIM_FAILED')
            after=w.snapshot()
            require(after['reserved']==before['reserved'],'RESERVATION_LOST')
            v['dispatch']={'clock':tm,'attempt':attempt,'response':res,'before':before,'after':after}
            result={'stage':'claim','claimed':True,'attempt':attempt}
        elif which=='settle':
            require('tool' in v,'TOOL_MISSING')
            before=w.snapshot()
            controller=Controller.fixture() if p=='PAY-1' else Controller(w.controller)
            tm=payclock(w,controller,v['scope'],oid,'SETTLE',112,112) if p=='PAY-1' else clock(w,oid,'SETTLE',112,112)
            signed=v['tool']['signed_final']
            res=w.settle_r2(signed,clock=tm) if p=='PAY-1' else w.settle_r2(signed,ledger,clock=tm)
            after=w.snapshot()
            require(res['status']=='SUCCEEDED','SETTLEMENT_FAILED')
            require(after['reserved']==0 and after['spent']>0,'NOT_CONSUMED')
            v['settlement']={'clock':tm,'response':res,'before':before,'after':after}
            result={'stage':'settle','status':res['status'],'once':True}
        elif which=='no_redispatch':
            # After restart and settlement, a fresh attempt must never create a
            # second tool instruction. No clock needed for rejected replay.
            before=w.snapshot();attempt=sid(1314)
            try:
                w.claim_r2(oid,attempt,clock={'invalid':'ignored'})
            except ProtocolError as exc:
                require(exc.code in ('NO_REDISPATCH','NO_DISPATCH'),'REPLAY_WRONG_REASON')
                rejection=exc.code
            else:raise AssertionError('second dispatch permitted')
            require(w.snapshot()==before,'REPLAY_SIDE_EFFECT')
            v['replay']={'attempt':attempt,'rejection':rejection,'unchanged':True}
            result={'stage':'no_redispatch','reject':rejection}
        else:raise ValueError(which)
    v['stage_pids'][which]=__import__('os').getpid()
    v['process_stage_outcomes'][which]=result
    write(witnesspath(d),v)
    return result

def _verify_message(message,actors,p,kind,scope):
    require(message['protected']['profile']==p and message['protected']['type']==kind,'MESSAGE_BINDING')
    require(message['body']['scope']==scope,'MESSAGE_SCOPE')
    k=message['protected']['kid']; require(k in actors,'UNREGISTERED_KEY')
    envelope(message,{k:actors[k]},now=106)
    UpstreamSchema(ROOT,p).validate(message,kind)
    return msgref(message)

def readonly_audit(d,witness=None):
    """No W classes, no controller private keys; opens both SQLite files read-only."""
    d=Path(d);v=copy.deepcopy(witness if witness is not None else read(witnesspath(d)))
    p=v['profile'];require(p in PROFILES,'PROFILE');oid=v['operation_id']
    ids=v['stage_pids'];require(len(ids)==5 and len(set(ids.values()))==5,'PROCESS_NOT_SEPARATED')
    require(v['action']['operation_id']==oid and v['action']['scope']==v['scope'],'ACTION_BINDING')
    actors={a['kid']:SimpleNamespace(name=a['name'],kid=a['kid'],pub=raw(a['pub'],32),purposes=frozenset(a['purposes'])) for a in v['fixture_actor_public'].values()}
    references={}
    for name,msg in v['signed_messages'].items():
        kind='Review' if name.startswith('review_') else {
            'issue':'IssueRequest','challenge_request':'ChallengeRequest','challenge':'Challenge',
            'proof':'CommitProof','permit':'Permit','authorization':'Authorization','acceptance':'Acceptance'}[name]
        references[name]=_verify_message(msg,actors,p,kind,v['scope'])
    require(v['signed_messages']['acceptance']['body']['payload']['commit_record_ref']==rec_ref(v['commit']),'COMMIT_REF')
    require(v['signed_messages']['acceptance']['body']['payload']['permit_ref']==references['permit'],'PERMIT_REF')
    require(v['signed_messages']['acceptance']['body']['payload']['proof_ref']==references['proof'],'PROOF_REF')
    UpstreamSchema(ROOT,p).validate(v['commit'],'Record_COMMIT')
    require(v['commit']['value']['action']==v['action'],'COMMIT_ACTION')
    root=raw(v['fixture_root_public'],32)
    trust=verify_certificate(v['tool_certificate'],root,p)
    UpstreamSchema(ROOT,p).validate(trust,'Record_TOOL_TRUST')
    require(trust['scope']==v['scope'],'TOOL_SCOPE')
    for key,purpose in (('dispatch','DISPATCH'),('settlement','SETTLE')):
        t=v[key]['clock']; cl=t['claim']
        require(cl['profile']==p and cl['scope']==v['scope'] and cl['operation_id']==oid and cl['purpose']==purpose,'CLOCK_BINDING')
        strict_verify(root,raw(t['signature'],64),canonical([CLOCK_DOMAIN,cl]))
    require(int(v['dispatch']['clock']['claim']['sequence'])<int(v['settlement']['clock']['claim']['sequence']),'CLOCK_ORDER')
    final=v['tool']['signed_final'];UpstreamSchema(ROOT,p).validate(final,'Record_TOOL_FINAL')
    require(final['value']['operation_id']==oid and final['scope']==v['scope'],'FINAL_BINDING')
    fact=final_fact(final);require(fact==v['tool']['fact'],'FACT_BINDING')
    tv=trust['value'];require(final['value']['attestation']['kid']==tv['kid'],'TOOL_SIGNER')
    strict_verify(raw(tv['public_key'],32),raw(final['value']['attestation']['sig'],64),final_sign_bytes(final))
    wdb=sqlite3.connect('file:'+str(dbpath(d,p).resolve())+'?mode=ro',uri=True)
    ldb=sqlite3.connect('file:'+str(ledgerpath(d).resolve())+'?mode=ro',uri=True)
    try:
        require(wdb.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and ldb.execute('PRAGMA integrity_check').fetchone()[0]=='ok','DB_CORRUPT')
        lr=ldb.execute('SELECT fact,attempt FROM finalized WHERE operation_id=?',(oid,)).fetchone()
        require(lr is not None and json.loads(lr[0])==fact and lr[1]==v['dispatch']['attempt'],'LEDGER_FACT_NOT_FOUND')
        if p=='PAY-1':
            acc=wdb.execute('SELECT state,exec_calls,settlement_count,commit_bytes,acceptance_bytes,commit_ref FROM accepted WHERE operation_id=?',(oid,)).fetchone()
            settled=wdb.execute('SELECT fact,record_ref FROM settled WHERE operation_id=?',(oid,)).fetchone()
            count=wdb.execute('SELECT COUNT(*) FROM accepted').fetchone()[0]
            reserved,spent=wdb.execute('SELECT reserved,spent FROM account WHERE id=1').fetchone()
            require(acc and count==1 and acc[:3]==('SUCCEEDED',1,1),'ACCEPTED_STATE')
            require(json.loads(acc[3])==v['commit'] and json.loads(acc[4])==v['signed_messages']['acceptance'] and acc[5]==rec_ref(v['commit']),'ACCEPTED_RECORD_INTEGRITY')
        else:
            # Public identity in the witness must correspond to C-controlled,
            # currently active KEY_GRANT and persistent PoP enrollment records.
            # This checks provenance independently of a self-asserted roster.
            for entry in v['fixture_actor_public'].values():
                keyjson=json.dumps([entry['kid']],separators=(',',':'))
                keyrow=wdb.execute("SELECT record,active FROM current_row WHERE namespace='KEY' AND key=?",(keyjson,)).fetchone()
                enrollment=wdb.execute('SELECT grant,proof FROM verified_enrollment WHERE kid=?',(entry['kid'],)).fetchone()
                require(keyrow is not None and keyrow[1]==1 and enrollment is not None,'KEY_GRANT_MISSING')
                grant=json.loads(keyrow[0]);kv=grant['value']
                require(grant==json.loads(enrollment[0]) and kv['kid']==entry['kid'] and
                        kv['public_key']==entry['pub'] and kv['subject']==entry['name'],'KEY_GRANT_MISMATCH')
                require('signature' in json.loads(enrollment[1]),'POP_MISSING')
            acc=wdb.execute('SELECT state,calls,settlements,accepted_blob FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
            settled=wdb.execute('SELECT fact,first_record FROM r2_settled WHERE operation_id=?',(oid,)).fetchone()
            count=wdb.execute('SELECT COUNT(*) FROM accept_intent').fetchone()[0]
            reserved,spent=wdb.execute('SELECT COALESCE(SUM(reserved),0),COALESCE(SUM(spent),0) FROM resource').fetchone()
            require(acc and count==1 and acc[:3]==('SUCCEEDED',1,1),'ACCEPTED_STATE')
            fr=json.loads(acc[3]);require(fr['commit_record']==v['commit'] and fr['acceptance']==v['signed_messages']['acceptance'],'ACCEPTED_RECORD_INTEGRITY')
        require(settled is not None and json.loads(settled[0])==fact,'SETTLED_FACT')
        require(reserved==0 and spent>0,'RESERVATION_FINAL')
        require(v['initial_snapshot']['reserved']>0 and v['dispatch']['after']['reserved']>0 and v['settlement']['after']['reserved']==0,'STAGE_SNAPSHOTS')
        require(v['replay']['unchanged'],'NO_REDISPATCH')
    finally:wdb.close();ldb.close()
    return {'candidate':'CORE-01','profile':p,'status':'PASS_PROCESS_SEPARATED_LAB_CANDIDATE',
            'official_complete_pass':False,'validated_message_types':list(references),
            'commit_ref':rec_ref(v['commit']),'acceptance_ref':references['acceptance'],
            'final_ref':rec_ref(final),'W_accept_count':count,'W_call_count':1,'W_settlement_count':1,
            'W_reserved_after':reserved,'W_spent_after':spent,'distinct_stage_pids':len(set(ids.values())),
            'independent_readonly_verifier':True,'official_schema_check':True,
            'limitations':['deterministic C/X signer keys remain constructed within the reference W; no true custody isolation',
             'ToolLedger is a simulator; cannot independently attest a physical or clinical effect',
             'No canonical transport aud/scope/path/0-RTT/STATUS lifecycle verification',
             'A per-profile W SQLite store is not one deployed cross-profile W',
             'The independent auditor reads the public tuple and fixture trusted root supplied in the witness, not external root trust']}

def child(d,which,p=''):
    command=[sys.executable,'-m','research.phase13.process_flow','--child',which,'--dir',str(d)]
    if p:command+=['--profile',p]
    run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=90)
    if run.returncode:raise RuntimeError(f'{which}: exit={run.returncode}: {run.stderr[-3000:]}')
    return json.loads(run.stdout)

def orchestrate(base):
    base=Path(base);base.mkdir(parents=True,exist_ok=True)
    status={}
    for profile in PROFILES:
        d=base/profile;d.mkdir(exist_ok=True)
        if witnesspath(d).exists():
            saved=read(witnesspath(d))
            events=list(saved['process_stage_outcomes'].values())
        else:
            events=[child(d,'bootstrap',profile)]
            saved=read(witnesspath(d))
        for which in ('claim','tool','settle','no_redispatch'):
            if which not in saved.get('stage_pids',{}):
                events.append(child(d,which))
                saved=read(witnesspath(d))
        # Verification runs in a separate process, whose result also has an
        # independent oracle mutation test and is not a trust anchor.
        external=child(d,'audit');events.append(external)
        audit=external['audit']
        # Tamper two distinct signed data types; offline verifier must reject.
        transcript=read(witnesspath(d))
        attacks=[]
        for attack in ('acceptance_commit_ref','tool_final_effect_id','profile_substitution'):
            changed=copy.deepcopy(transcript)
            if attack=='acceptance_commit_ref':changed['signed_messages']['acceptance']['body']['payload']['commit_record_ref']='tampered'
            elif attack=='tool_final_effect_id':changed['tool']['signed_final']['value']['effect_id']='tampered'
            else:changed['profile']='MED-DEMO-1' if profile!='MED-DEMO-1' else 'PAY-1'
            try:readonly_audit(d,changed)
            except (ProtocolError,ValueError,KeyError,AssertionError) as exc:attacks.append({'variant':attack,'rejected':True,'exception':getattr(exc,'code',type(exc).__name__)})
            else:raise AssertionError('offline audit accepted altered '+attack)
        status[profile]={'events':events,'audit':audit,'mutations':attacks,
                         'witness_path':str(witnesspath(d).relative_to(base)),
                         'witness_sha256':sha(witnesspath(d)),
                         'db_integrity':{'w_sha256':sha(dbpath(d,profile)),'tool_sha256':sha(ledgerpath(d))}}
    report={'contract':'ZJJ-CORE-2.6-R2','phase':13,'case_id':'CORE-01','official_complete_pass':False,
            'status':'PASS_PROCESS_SEPARATED_LAB_CANDIDATE','official_39_status':'0 PASS / 39 BLOCKED',
            'three_profiles':status}
    write(base/'phase13_process_report.json',report)
    return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--child',choices=('bootstrap','claim','tool','settle','no_redispatch','audit'))
    ap.add_argument('--dir');ap.add_argument('--profile',choices=PROFILES);ap.add_argument('--output')
    x=ap.parse_args()
    if x.child:
        if x.child=='bootstrap':result=bootstrap(x.dir,x.profile)
        elif x.child=='audit':result={'stage':'audit','audit':readonly_audit(x.dir)}
        else:result=stage(x.dir,x.child)
        print(json.dumps(result,ensure_ascii=False));return
    dest=Path(x.output or HERE/'evidence'/'core01_process')
    report=orchestrate(dest)
    print(json.dumps({'case':'CORE-01','profiles':list(report['three_profiles']),
        'status':report['status'],'official_passes':0,'evidence':str(dest)},ensure_ascii=False))
if __name__=='__main__':main()
