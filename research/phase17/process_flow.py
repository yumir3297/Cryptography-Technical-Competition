"""Phase17 minimum IND evidence->authorization->execution->audit laboratory.

All runtime C/E/H/G/U/X and tool signatures come from separate signer
subprocess invocations with fresh per-run keys, not deterministic fixture seeds.
Provisioning remains a single trusted laboratory process and files share an
OS account: this is NOT production HSM / KMS / privilege isolation.
Original v2.6 wire types and three official schemas are unchanged.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption
from research.phase8.fixtures import build_scene
from research.phase8.scene_authority import PROFILES, ROLES, PURPOSES, _rec
from research.phase12.authority import HardenedSceneW
from research.phase14.verifier import VerifierOnlySceneW
from research.phase14.process_flow import dump,load,manifest,db,tool_path,independent_audit
from research.phase16.industrial_delivery import (
    WDispatchOutbox, AuthenticatedIndustrialGateway, public_key, DOMAIN
)
from research.phase6.trusted_final import Controller, ToolLedger
from research.phase11.trusted_clock import seal
from research.phase11.run_phase11 import ROOT
from research.reference_executor.wire import (
    Identity,ProtocolError,require,canonical,b64,raw,sid,sortset,digest,
    rec_ref,msgref,keyid,envelope,action_hash,LIFETIME
)
from research.strict_v26.upstream_schema import UpstreamSchema

PROFILE=os.environ.get('ZJJ_COMPETITION_PROFILE','IND-DEMO-1')
require(PROFILE in ('IND-DEMO-1','MED-DEMO-1'),'COMPETITION_PROFILE')
SIGNERS=('C','H','G','X','U','V','E','TOOL','WTOOL')
STAGE_SIGNERS={'e_sign':'E','u_authorize':'U','h_issue':'H','g_permit':'G',
 'h_challenge':'H','x_challenge':'X','h_proof':'H','x_accept':'X',
 'c_prepare':'C','c_finalize':'C','c_trust':'C','c_claim':'C','c_settle':'C',
 'tool_recover':'TOOL','w_delivery':'WTOOL'}

def secrets(d):return Path(d)/'signers'
def private_path(d,name):return secrets(d)/(name+'.key')
def pub_from_key(k):return k.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
def provision_key(d,name):
    k=Ed25519PrivateKey.generate()
    f=private_path(d,name)
    f.write_bytes(k.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()))
    os.chmod(f,0o600)
    return k
def key(d,name):
    require(name in SIGNERS,'SIGNER')
    f=private_path(d,name)
    require(f.is_file() and len(f.read_bytes())==32,'MISSING_SIGNER')
    return Ed25519PrivateKey.from_private_bytes(f.read_bytes())

def verifier(d,v):
    actors={a:SimpleNamespace(name=i['name'],kid=i['kid'],pub=raw(i['pub'],32),
          roles=frozenset(i['roles']),purposes=frozenset(i['purposes']))
          for a,i in v['fixture_actor_public'].items()}
    w=VerifierOnlySceneW(db(d),PROFILE,root_public=raw(v['fixture_root_public'],32),actors=actors)
    require(not hasattr(w.controller,'sign') and all(not hasattr(x,'key') for x in w.actors.values()),'W_HAS_ACTOR_SECRET')
    return w

def role_envelope(d,v,alias,typ,payload,*,refs=(),deps=(),aud=('H','G','X'),at=103,nonce=1,ttl=None):
    r=v['fixture_actor_public'][alias]
    k=key(d,alias)
    require(keyid(pub_from_key(k))==r['kid'],'SIGNER_KEY_MISMATCH')
    header={'proto':'ZJJ-AAP','version':'2.6','profile':PROFILE,'alg':'Ed25519',
            'type':typ,'issuer':r['name'],'kid':r['kid']}
    body={'id':sid(at*1000+nonce),'scope':v['scope'],'iat':str(at),
          'exp':str(at+(ttl or LIFETIME[typ])),
          'aud':sortset([v['fixture_actor_public'][a]['name'] for a in aud]),
          'refs':sortset(list(refs)),'deps':sortset(list(deps)),'payload':payload}
    result={'protected':header,'body':body,'sig':b64(k.sign(canonical(['ZJJ-SIG-v1',header,body])))}
    who=SimpleNamespace(name=r['name'],kid=r['kid'],pub=raw(r['pub'],32),
                        purposes=frozenset(r['purposes']))
    envelope(result,{r['kid']:who},now=at)
    return result

def obj_ref(msg):return digest(['ZJJ-OBJ-v1',msg['protected'],msg['body']])

def start(d):
    d=Path(d);d.mkdir(parents=True,exist_ok=True)
    sd=secrets(d);sd.mkdir(mode=0o700,exist_ok=True);os.chmod(sd,0o700)
    keys={n:provision_key(d,n) for n in SIGNERS}
    actors={}
    for i,alias in enumerate(('H','G','X','U','V','E')):
        a=Identity('pilot-'+alias.lower(),10+i,roles=[ROLES[PROFILE][alias]],purposes=PURPOSES[alias])
        a.key=keys[alias];a.pub=pub_from_key(keys[alias]);a.kid=keyid(a.pub)
        actors[alias]=a
    # Local adapter avoids ANY mutation of historical Phase8 fixture source/hash.
    class ProvisionedScene(HardenedSceneW):
        def __init__(self,path,profile):
            super().__init__(path,profile,controller=keys['C'],actors=actors)
    issuer,act,task,scene,ev=build_scene(db(d),PROFILE,authority_class=ProvisionedScene)
    require(not any(pub_from_key(keys[n])==pub_from_key(keys[m]) for i,n in
        enumerate(SIGNERS) for m in SIGNERS[i+1:]),'KEY_COLLISION')
    roster={a:{'name':v.name,'kid':v.kid,'pub':b64(v.pub),
               'roles':sorted(v.roles),'purposes':sorted(v.purposes)} for a,v in actors.items()}
    v={'profile':PROFILE,'scope':issuer.scope,'action':act,
       'operation_id':act['operation_id'],'task_id':task,'scene_key':scene,
       'fixture_root_public':b64(pub_from_key(keys['C'])),
       'fixture_actor_public':roster,'w_delivery_public':b64(pub_from_key(keys['WTOOL'])),
       'tool_public':b64(pub_from_key(keys['TOOL'])),
       'evidence_data':ev['value']['data'],'signed_messages':{},
       'stage_pids':{'bootstrap':os.getpid()},'process_stage_outcomes':{},
       'signer_key_custody':'fresh_per_run_role_keyfiles_shared_lab_os_account',
       'official_complete_pass':False}
    dump(manifest(d),v)
    return {'stage':'provision','fresh_random_roles':len(keys),
            'W_has_C_E_X_private_keys':False,'separate_OS_accounts':False}

def stage(d,name):
    d=Path(d)
    if name=='provision':return start(d)
    v=load(manifest(d));op=v.get('op');result={'stage':name}
    p=v['scope'];oid=v['operation_id'];act=v['action']
    if name=='e_sign':
        data=copy.deepcopy(v['evidence_data'])
        data['evidence_revision']='2';data['evidence_id']=sid(171111)
        e=v['fixture_actor_public']['E']
        a={'issuer':e['name'],'kid':e['kid'],'iat':'100','exp':'220'}
        att={**a,'sig':b64(key(d,'E').sign(canonical(
            ['ZJJ-SOURCE-v1','2.6',PROFILE,PROFILES[PROFILE][1],p,data,a])))}
        v['signed_evidence']=_rec(PROFILE,PROFILES[PROFILE][1],p,
                                 {'data':data,'attestation':att})
        result.update({'E_source_signed':True,'E_pub':e['kid']})
    elif name=='w_import':
        w=verifier(d,v);ev=v['signed_evidence']
        # Negative proof: a forged E record must never mutate current state.
        bad=copy.deepcopy(ev);bad['value']['attestation']['sig']=b64(b'\x00'*64)
        before=w._read_row('EVIDENCE',v['scene_key'])['ref']
        try:w.import_evidence(bad,v['scene_key'])
        except ProtocolError as e:result['forged_E_rejected']=e.code
        else:raise AssertionError('FORGED_SOURCE_ACCEPTED')
        require(w._read_row('EVIDENCE',v['scene_key'])['ref']==before,'FORGED_SOURCE_SIDE_EFFECT')
        ev_ref=w.import_evidence(ev,v['scene_key'])
        require(w._read_row('EVIDENCE',v['scene_key'])['ref']==ev_ref,'SOURCE_NOT_CURRENT')
        result['imported_source_ref']=ev_ref
    elif name=='w_plan':
        w=verifier(d,v);op=w.prepare(act,v['task_id'],v['scene_key'],at=102)
        require(op['required']==([] if PROFILE=='IND-DEMO-1' else ['CLINICAL_REVIEW']),
                'UNRECOGNIZED_SCENE_REVIEW')
        v['op']=op;result['basis_ref']=op['ctx']['basis_ref']
    elif name=='v_review':
        require(PROFILE=='MED-DEMO-1' and op['required']==['CLINICAL_REVIEW'],
                'REVIEW_NOT_REQUIRED')
        op['reviews'].append(role_envelope(d,v,'V','Review',
             {'ctx':op['ctx'],'purpose':'CLINICAL_REVIEW',
              'verdict':'APPROVE','reason':'scene checked'},
             deps=op['deps'],at=103,nonce=1,ttl=117))
        result['signed_required_clinical_review']=True
    elif name=='u_authorize':
        refs=sortset([obj_ref(r) for r in op['reviews']])
        require(sorted(x['body']['payload']['purpose'] for x in op['reviews'])==
                sorted(op['required']),'REVIEW_REQUIRED')
        op['authorization']=role_envelope(d,v,'U','Authorization',
             {'ctx':op['ctx'],'review_refs':refs,'purpose':'EXECUTE','verdict':'APPROVE'},
             refs=refs,deps=op['deps'],at=103,nonce=2,ttl=117)
    elif name in ('h_issue','g_permit'):
        ar=obj_ref(op['authorization']);rr=sortset([obj_ref(r) for r in op['reviews']])
        payload=({'ctx':op['ctx'],'review_refs':rr,'authorization_ref':ar} if name=='h_issue'
            else {'ctx':op['ctx'],'review_refs':rr,'authorization_ref':ar,
                 'max_uses':'1','dispatch_before':'220'})
        alias,typ,recipients,nonce=('H','IssueRequest',('G',),3) if name=='h_issue' else (
             'G','Permit',('H','X'),4)
        op['issue' if name=='h_issue' else 'permit']=role_envelope(d,v,alias,typ,payload,
             refs=sortset(rr+[ar]),deps=op['deps'],aud=recipients,at=104,nonce=nonce,ttl=116)
    elif name=='h_challenge':
        pref=obj_ref(op['permit'])
        op['challenge_request']=role_envelope(d,v,'H','ChallengeRequest',
             {'purpose':'COMMIT','operation_id':oid,'permit_ref':pref,
              'action_hash':op['ctx']['action_hash'],'attempt_id':sid(705)},
             refs=[pref],aud=('X',),at=105,nonce=5)
    elif name=='x_challenge':
        pref=obj_ref(op['permit']);qr=obj_ref(op['challenge_request'])
        op['challenge']=role_envelope(d,v,'X','Challenge',
             {'purpose':'COMMIT','operation_id':oid,'permit_ref':pref,
              'action_hash':op['ctx']['action_hash'],'holder':act['holder'],
              'holder_kid':act['holder_kid'],'session_id':sid(706),
              'nonce':digest(['scene-challenge',oid]),'request_ref':qr},
             refs=[pref,qr],aud=('H',),at=105,nonce=6)
    elif name=='h_proof':
        pref=obj_ref(op['permit']);cr=obj_ref(op['challenge']);ch=op['challenge']['body']['payload']
        op['proof']=role_envelope(d,v,'H','CommitProof',
             {'ctx':op['ctx'],'permit_ref':pref,'challenge_ref':cr,
              'session_id':ch['session_id'],'nonce':ch['nonce'],'attempt_id':sid(705)},
             refs=[pref,cr],aud=('X',),at=106,nonce=7,ttl=29)
        v['signed_messages']={k:op[k] for k in
              ('authorization','issue','permit','challenge_request','challenge','proof')}
    elif name.startswith('c_'):
        c=Controller(key(d,'C'))
        if name=='c_trust':
            ledger=ToolLedger(tool_path(d),profile=PROFILE)
            tool_public=raw(v['tool_public'],32)
            tv={'issuer':'pilot-tool','tool':act['tool'],'tool_version':act['tool_version'],
                'destination':act['destination'],'ledger_id':ledger.ledger_id,
                'evidence_method':'tool-final-v2','public_key':v['tool_public'],
                'kid':keyid(tool_public),'epoch':'1','iat':'90','exp':'2000'}
            v['tool_certificate']=c.certify(p,tv,1,ledger.head(),ledger.origin,profile=PROFILE)
            result['tool_root_certified']=True
        else:
            purpose={'c_prepare':'PREPARE','c_finalize':'FINALIZE',
                     'c_claim':'DISPATCH','c_settle':'SETTLE'}[name]
            with sqlite3.connect(db(d)) as conn:
                seq=conn.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
            at=106 if purpose in ('PREPARE','FINALIZE') else 107 if purpose=='DISPATCH' else 112
            v.setdefault('clocks',{})[purpose]=seal(c,PROFILE,p,oid,purpose,seq,at,at)
            result.update({'purpose':purpose,'sequence':seq,'C_signed':True})
    elif name=='w_prepare':
        w=verifier(d,v)
        v['prepared']=w.prepare_accept(op,clock=v['clocks']['PREPARE'])
        require(w.snapshot()['accepts']==0 and w.snapshot()['reserved']==0,'PREPARE_EFFECT')
        result['prepared_without_side_effect']=True
    elif name=='x_accept':
        q=v['prepared']
        v['acceptance']=role_envelope(d,v,'X','Acceptance',q['acceptance_payload'],
                      refs=q['refs'],aud=('H','G','U'),at=q['signed_at'],nonce=8)
        result['acceptance_ref']=msgref(v['acceptance'])
    elif name=='w_finalize':
        w=verifier(d,v)
        # Wrong-X signature must fail and keep the reservation unmodified.
        bad=copy.deepcopy(v['acceptance']);bad['sig']=b64(b'\x00'*64)
        try:w.finalize_accept(v['prepared']['ticket'],bad,clock=v['clocks']['FINALIZE'])
        except ProtocolError as e:result['forged_X_rejected']=e.code
        else:raise AssertionError('FORGED_ACCEPTANCE')
        require(w.snapshot()['accepts']==0 and w.snapshot()['reserved']==0,'FORGED_X_MUTATED_STATE')
        accepted=w.finalize_accept(v['prepared']['ticket'],v['acceptance'],clock=v['clocks']['FINALIZE'])
        v['signed_messages']['acceptance']=accepted
        v['commit']=v['prepared']['commit_record'];v['initial_snapshot']=w.snapshot()
        require(v['initial_snapshot']['accepts']==1 and v['initial_snapshot']['reserved']==1,'ACCEPT_STATE')
        result['commit_ref']=rec_ref(v['commit'])
    elif name=='w_activate':
        ledger=ToolLedger(tool_path(d),profile=PROFILE)
        verifier(d,v).activate_tool(v['tool_certificate'],ledger,now=108)
        result['C_signed_tool_trust_verified']=True
    elif name=='w_claim':
        w=verifier(d,v);before=w.snapshot();attempt=sid(171003)
        res=w.claim_r2(oid,attempt,clock=v['clocks']['DISPATCH'])
        require(res['status']=='CLAIMED','NO_DISPATCH')
        after=w.snapshot();require(before['reserved']==after['reserved']==1,'RESERVATION_LOST')
        v['dispatch']={'clock':v['clocks']['DISPATCH'],'attempt':attempt,'response':res,
                       'before':before,'after':after}
        v['stage_pids']['claim']=os.getpid()
        result['claimed']=True
    elif name=='w_delivery':
        ledger=ToolLedger(tool_path(d),profile=PROFILE)
        v['dispatch_token']=WDispatchOutbox(db(d),PROFILE,signer=key(d,'WTOOL')).issue(oid,ledger=ledger)
        result['W_transport_signature']=True
    elif name=='tool_crash':
        ledger=ToolLedger(tool_path(d),profile=PROFILE)
        g=AuthenticatedIndustrialGateway(ledger,w_public=raw(v['w_delivery_public'],32),scope=p)
        bad=copy.deepcopy(v['dispatch_token']);bad['signature']=b64(b'\x00'*64)
        try:g.deliver(bad)
        except ProtocolError:pass
        else:raise AssertionError('FORGED_W_ACCEPTED')
        require(g.audit()['simulated_effects']==0,'FORGED_W_SIDE_EFFECT')
        g.deliver(v['dispatch_token'],inject='hard_after_commit')
        raise AssertionError('TOOL_DID_NOT_CRASH')
    elif name=='tool_recover':
        ledger=ToolLedger(tool_path(d),profile=PROFILE)
        g=AuthenticatedIndustrialGateway(ledger,w_public=raw(v['w_delivery_public'],32),scope=p)
        out=g.deliver(v['dispatch_token'])
        require(not out['new_effect'] and g.audit()['simulated_effects']==1,'DOUBLE_EFFECT')
        signed=ledger.reattest(p,out['fact'],key(d,'TOOL'),'pilot-tool',111,2000)
        UpstreamSchema(ROOT,PROFILE).validate(signed,'Record_TOOL_FINAL')
        v['tool']={'fact':out['fact'],'signed_final':signed,'ledger_origin':ledger.origin}
        v['stage_pids']['tool']=os.getpid()
        result['recover_original_only']=True
    elif name=='w_settle':
        w=verifier(d,v);ledger=ToolLedger(tool_path(d),profile=PROFILE)
        before=w.snapshot();r=w.settle_r2(v['tool']['signed_final'],ledger,clock=v['clocks']['SETTLE'])
        after=w.snapshot()
        require(r['status']=='SUCCEEDED' and after['reserved']==0 and after['spent']==1,'SETTLE_FAILED')
        v['settlement']={'clock':v['clocks']['SETTLE'],'response':r,'before':before,'after':after}
        v['stage_pids']['settle']=os.getpid()
        result['settled']=True
    elif name=='w_no_replay':
        w=verifier(d,v);before=w.snapshot()
        try:w.claim_r2(oid,sid(171004),clock={'bad':True})
        except ProtocolError as e:
            require(e.code in ('NO_REDISPATCH','NO_DISPATCH'),'WRONG_REPLAY_ERROR')
            reason=e.code
        else:raise AssertionError('DOUBLE_DISPATCH')
        require(w.snapshot()==before,'REPLAY_SIDE_EFFECT')
        v['replay']={'attempt':sid(171004),'rejection':reason,'unchanged':True}
        v['stage_pids']['no_redispatch']=os.getpid()
        result['no_redispatch']=True
    else:raise ValueError(name)
    v['process_stage_outcomes'][name]=result
    dump(manifest(d),v)
    return result

def audit(d):
    d=Path(d);v=load(manifest(d));w=verifier(d,v)
    base=independent_audit(d)
    token=v['dispatch_token']; cl=token['claim']
    require(cl['action']==v['action'] and cl['operation_id']==v['operation_id'],
            'DELIVERY_ACTION')
    strict_key=raw(v['w_delivery_public'],32)
    from research.reference_executor.wire import strict_verify
    strict_verify(strict_key,raw(token['signature'],64),canonical([DOMAIN,cl]))
    with sqlite3.connect('file:'+str(db(d).resolve())+'?mode=ro',uri=True) as db_ro, sqlite3.connect(
            'file:'+str(tool_path(d).resolve())+'?mode=ro',uri=True) as t_ro:
        p=db_ro.execute('SELECT attempt,envelope FROM p16_outbox WHERE operation_id=?',
                        (v['operation_id'],)).fetchone()
        t=t_ro.execute('SELECT packet_ref,effect_count FROM p16_authenticated_delivery WHERE operation_id=?',
                       (v['operation_id'],)).fetchone()
        require(p and p[0]==cl['attempt'] and json.loads(p[1])==token,'OUTBOX_NOT_PERSISTED')
        require(t and t[0]==digest([DOMAIN,cl]) and t[1]==1,'MISMATCHED_TOOL')
        require(t_ro.execute('SELECT COUNT(*) FROM finalized').fetchone()[0]==1,'TOOL_DOUBLE_EFFECT')
    require(len({v['fixture_root_public'],v['w_delivery_public'],v['tool_public'],
                 *(x['pub'] for x in v['fixture_actor_public'].values())})==9,'NOT_DISTINCT_KEYS')
    require(v['process_stage_outcomes']['w_import']['forged_E_rejected'] and
            v['process_stage_outcomes']['w_finalize']['forged_X_rejected'],'NEGATIVE_GUARD_MISSING')
    require(v['process_stage_outcomes']['tool_recover']['recover_original_only'] and
            v['delivery_crash']['exit_code']==97,'NO_LOST_ACK_TEST')
    return {**base,'candidate':'IND_MINIMAL_SIGNER_SOURCE_EXECUTION_CLOSED_LOOP',
        'role_public_keys_distinct':9,'fresh_provisioned_key_sets':True,
        'W_has_C_E_X_private_keys':False,'signer_processes_separate':True,
        'E_source_attestation_verified':True,'forged_E_rejected':True,'forged_X_rejected':True,
        'forged_W_rejected':True,'durable_effects':1,'recovery_no_second_effect':True,
        'real_independent_OS_identity_custody':False,'physical_effect_proven':False,
        'official_complete_pass':False}

def subprocess_stage(d,name):
    p=subprocess.run([sys.executable,'-m','research.phase17.process_flow','--child',name,
                      '--dir',str(d)],cwd=ROOT,text=True,capture_output=True,timeout=120)
    if name=='tool_crash':
        require(p.returncode==97,'TOOL_CRASH_MISSING')
        return {'stage':'tool_crash','exit_code':97,'response_lost':True}
    if p.returncode:raise RuntimeError(f'{name} failed with {p.returncode}: {p.stderr[-4000:]}')
    return json.loads(p.stdout)

STAGES=('provision','e_sign','w_import','w_plan',
        *(('v_review',) if PROFILE=='MED-DEMO-1' else ()),
        'u_authorize','h_issue','g_permit',
        'h_challenge','x_challenge','h_proof','c_prepare','w_prepare','x_accept',
        'c_finalize','w_finalize','c_trust','w_activate','c_claim','w_claim',
        'w_delivery','tool_crash','tool_recover','c_settle','w_settle','w_no_replay')
def orchestrate(destination):
    d=Path(destination).resolve();d.mkdir(parents=True,exist_ok=True)
    # Never destroy a genuine key store or prior evidence silently.
    require(not any(d.iterdir()),'OUTPUT_DIRECTORY_NOT_EMPTY')
    seq=[]
    for name in STAGES:
        result=subprocess_stage(d,name);seq.append(result)
        if name=='tool_crash':
            v=load(manifest(d));v['delivery_crash']=result;dump(manifest(d),v)
    verified=audit(d)
    report={'contract':'ZJJ-CORE-2.6-R2','phase':17,'profile':PROFILE,
        'case':'IND_MINIMUM_CLOSED_LOOP','official_complete_pass':False,
        'stage_count':len(seq),'stages':seq,'readonly_audit':verified,
        'witness_sha256':hashlib.sha256(manifest(d).read_bytes()).hexdigest(),
        'limitations':[
            'Provisioner initially sees all private signing keys; no KMS, HSM or separate OS identities',
            'The role keyfiles must NEVER be committed or delivered as an artifact',
            'C signed laboratory time still uses equal PREPARE/FINALIZE timestamp',
            'No PLC/sensor hardware attached; SQLite simulator records one fact, not a physical action',
            'No full 39-case conformance or full network STATUS/0-RTT evidence',
        ]}
    dump(d/'phase17_process_report.json',report)
    return report

def main():
    a=argparse.ArgumentParser();a.add_argument('--child');a.add_argument('--dir')
    a.add_argument('--output');args=a.parse_args()
    x=stage(args.dir,args.child) if args.child else orchestrate(args.output or '/tmp/zjj_phase17_ind')
    print(json.dumps(x,ensure_ascii=False))
if __name__=='__main__':main()
