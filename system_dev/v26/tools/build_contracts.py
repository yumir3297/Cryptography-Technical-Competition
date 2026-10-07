"""Generate standard protocol schemas only; no product handlers or persistence."""
from pathlib import Path
import copy
import json
import re

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]
TYPES = ['Review','Authorization','IssueRequest','Permit','ChallengeRequest','Challenge','CommitProof','Acceptance','Result','StatusQuery']
PROFILES = {'PAY-1':('payment','pay1'), 'IND-DEMO-1':('industrial','industrial'), 'MED-DEMO-1':('medical','medical')}
CHECKS = 'format signature audience scope binding policy task source assessment reviews authorization deps holder nonce intent resource behavior tool result'.split()
CODES = 'MALFORMED LIMIT UNSUPPORTED_VERSION BAD_SIGNATURE WRONG_SCOPE WRONG_HOLDER WRONG_AUDIENCE BINDING DEP_CONFLICT REVOKED STALE EXPIRED NO_ROLE REPLAY OPERATION_CONFLICT ID_CONFLICT OBJECT_KIND OBJECT_INTEGRITY CLAIM_FALSE POLICY_DENY REVIEW_DENY AUTH_DENY REVIEW_PURPOSE REVIEW_REASON REVIEW_REQUIRED RISK_POLICY DUPLICATE_CASE DUPLICATE_INTENT RESOURCE_LIMIT BEHAVIOR_LIMIT STATE_UNAVAILABLE CLOCK_UNKNOWN RISK_UNKNOWN TOOL_UNAVAILABLE TASK_BUSY RETRY_CONFLICT MISSING_OBJECT MISSING_REVIEW MISSING_AUTH OK EXISTING_ACCEPTANCE'.split()

def obj(**p):
    return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
def ref(t): return {'$ref':'#/$defs/'+t}
def const(v): return {'const':v}
def enum(*v): return {'type':'string','enum':list(v)}
def arr(t, minimum=0, maximum=256, ordered=False):
    out={'type':'array','items':copy.deepcopy(t),'minItems':minimum,'maxItems':maximum}
    if not ordered: out.update(uniqueItems=True, **{'x-zjj-order':'strict lexicographic Enc bytes'})
    return out
def tuple_schema(*items):
    return {'type':'array','prefixItems':list(items),'items':False,'minItems':len(items),'maxItems':len(items)}
def maybe(t): return {'oneOf':[const(''),ref(t)]}
def fields(spec): return obj(**{k:ref(t) for k,t in spec.items()})
def decimal(upper, positive=False):
    s=str(upper); alts=[] if positive else ['0']
    if len(s)>1: alts.append('[1-9][0-9]{0,'+str(len(s)-2)+'}')
    for i,ch in enumerate(s):
        lo,hi=(1 if i==0 else 0),int(ch)-1
        if hi>=lo:
            digit=str(lo) if lo==hi else f'[{lo}-{hi}]'
            alts.append(s[:i]+digit+'[0-9]{'+str(len(s)-i-1)+'}')
    alts.append(s)
    return {'type':'string','pattern':'^(?:'+'|'.join(alts)+')(?![\\s\\S])'}

def build(profile):
    scene,stem=PROFILES[profile]; idt=ref('Id'); h=ref('B32'); n=ref('N'); pos=ref('Positive'); b16=ref('B16')
    d={'N':decimal(9223372036854775807),'Positive':decimal(9223372036854775807,True),'Ratio':decimal(10000),
       'Id':{'type':'string','pattern':'^[a-z0-9][a-z0-9._:-]{0,63}(?![\\s\\S])'},
       'Text':{'type':'string','maxLength':1024},
       'Nonblank':{'type':'string','maxLength':1024,'pattern':'[^\\u0009-\\u000d\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]'}}
    for length,width,tail in [(16,22,'AQgw'),(32,43,'AEIMQUYcgkosw048'),(64,86,'AQgw')]:
        d[f'B{length}']={'type':'string','pattern':f'^[A-Za-z0-9_-]{{{width-1}}}[{tail}](?![\\s\\S])','minLength':width,'maxLength':width}
    d['Scope']=obj(domain=idt,tenant=idt,scenario=const(scene))
    scope=ref('Scope'); ss=[idt,idt,const(scene)]
    roles=['HOLDER','ISSUER','SOURCE','FINANCE','ANOMALY','EXECUTOR'] if scene=='payment' else ['CONTROLLER','SOURCE','HOLDER','ISSUER','EXECUTOR','READER','AUDITOR']+(['LINE_OPERATOR','QUALITY_REVIEWER'] if scene=='industrial' else ['MEDICAL_AUTHORIZER','CLINICAL_REVIEWER'])
    purposes=['ANOMALY','LOW_EVIDENCE'] if scene=='payment' else ['QUALITY_REVIEW'] if scene=='industrial' else ['CLINICAL_REVIEW']
    d['Role']=enum(*roles); d['ReviewPurpose']=enum(*purposes)
    keys={'POLICY':ss,'TASK':ss+[b16],'KEY':[h],'ROLE':ss+[idt,ref('Role')],'BEHAVIOR':ss+[idt]}
    if scene=='payment': keys.update(ORDER=ss+[idt,idt],EXPERIENCE=ss+[idt])
    elif scene=='industrial': keys['UNIT']=ss+[idt,idt]
    else: keys['ENCOUNTER']=ss+[idt,idt]
    d['Dep']=obj(namespace=enum(*keys),key={'type':'array','maxItems':6,'items':{'type':'string'}},revision=pos,ref=h)
    d['Dep']['allOf']=[{'if':{'properties':{'namespace':const(k)},'required':['namespace']},'then':{'properties':{'key':tuple_schema(*v)}}} for k,v in keys.items()]
    d['Ctx']=obj(scope=scope,operation_id=b16,principal=idt,holder=idt,holder_kid=h,executor=idt,action_hash=h,policy_ref=h,basis_ref=h)
    if scene=='payment':
        d['ActionPayload']=obj(order_id=idt,stage=idt,payer=idt,payee=idt,amount_minor=pos,currency=const('CNY'),purpose=const('order-settlement'))
    elif scene=='industrial':
        d['ActionPayload']=obj(line_id=idt,station_id=idt,unit_id=idt,batch_id=idt,inspection_cycle=enum('1','2'),phase=enum('INITIAL','REINSPECT'),route=enum('RELEASE','QUARANTINE','INSPECT'))
    else:
        d['ActionPayload']=obj(synthetic_patient_id=idt,encounter_id=idt,order_group_id=b16,phase=const('SUBMIT'),template_id=enum('DEMO-ORDER-A','DEMO-ORDER-B'),record_ref=h,destination_system=const('med-demo-ledger'))
    tool={'payment':'pay-sim','industrial':'line-sort-sim','medical':'med-order-sim'}[scene]
    d['Action']=obj(scope=scope,operation_id=b16,principal=idt,holder=idt,holder_kid=h,executor=idt,tool=const(tool),tool_version=const('1'),destination=idt,payload=ref('ActionPayload'))
    ctx=ref('Ctx'); refs=arr(h); deps=arr(ref('Dep'))
    payloads={
        'Review':obj(ctx=ctx,purpose=ref('ReviewPurpose'),verdict=enum('APPROVE','DENY'),reason=ref('Nonblank')),
        'Authorization':obj(ctx=ctx,review_refs=refs,purpose=const('EXECUTE'),verdict=enum('APPROVE','DENY')),
        'IssueRequest':obj(ctx=ctx,review_refs=refs,authorization_ref=h),
        'Permit':obj(ctx=ctx,review_refs=refs,authorization_ref=h,max_uses=const('1'),dispatch_before=n),
        'ChallengeRequest':obj(purpose=enum('COMMIT','STATUS'),operation_id=b16,permit_ref=maybe('B32'),action_hash=maybe('B32'),attempt_id=b16),
        'Challenge':obj(purpose=enum('COMMIT','STATUS'),operation_id=b16,permit_ref=maybe('B32'),action_hash=maybe('B32'),holder=idt,holder_kid=h,session_id=b16,nonce=h,request_ref=h),
        'CommitProof':obj(ctx=ctx,permit_ref=h,challenge_ref=h,session_id=b16,nonce=h,attempt_id=b16),
        'Acceptance':obj(ctx=ctx,permit_ref=h,proof_ref=h,authorization_ref=h,review_refs=refs,accept_seq=pos,accepted_at=n,commit_record_ref=h,dispatch_before=n),
        'Result':obj(request_ref=h,attempt_id=maybe('B16'),result=enum('ISSUED','ACCEPTED','REJECT','DEFER','EXISTING','STATUS'),reasons=arr(ref('Reason'),1,20,True),operation_id=maybe('B16'),permit_ref=maybe('B32'),acceptance_ref=maybe('B32'),status=enum('NONE','PENDING','ACCEPTED','EFFECT_UNKNOWN','SUCCEEDED','FAILED_CONFIRMED','HALTED'),status_seq=n,retry_after=maybe('N')),
        'StatusQuery':obj(operation_id=b16,challenge_ref=h,session_id=b16,nonce=h,attempt_id=b16)}
    d['Reason']=obj(check=enum(*CHECKS),code=enum(*CODES))
    for typ,p in payloads.items():
        head=obj(proto=const('ZJJ-AAP'),version=const('2.6'),profile=const(profile),alg=const('Ed25519'),type=const(typ),issuer=idt,kid=h)
        body=obj(id=b16,scope=scope,iat=n,exp=n,aud=arr(idt,1),refs=refs,deps=deps,payload=p)
        d[typ]=obj(protected=head,body=body,sig=ref('B64'))
        d[typ]['x-zjj-max-lifetime-seconds']=120 if typ in ('IssueRequest','Permit') else 900 if typ in ('Review','Authorization','Acceptance') else 30
    d['Envelope']={'oneOf':[ref(t) for t in TYPES]}
    # Exact controlled record fields. Authentication and state guards stay normative.
    record_values={}
    readers=arr(idt,1,256 if scene=='payment' else 8); times={'iat':n,'exp':n}
    common_policy=dict(profile=const(profile),policy_revision=pos,schema_version=const({'payment':'pay1-payload-v1','industrial':'ind-payload-v1','medical':'med-payload-v1'}[scene]),verifier_version=const({'payment':'pay1-verifier-v1','industrial':'ind-fixed-v1','medical':'med-fixed-v1'}[scene]),gateway=idt,gateway_kid=h,executor=idt,executor_kid=h,source=idt,readers=readers,tool=const(tool),tool_version=const('1'))
    record_values['BASIS']=obj(scope=scope,operation_id=b16,action=ref('Action'),action_hash=h,policy_ref=h,task_ref=h,evidence_refs=arr(h,1,1),assessment_ref=h,required_reviews=arr(ref('ReviewPurpose')),deps=deps,**times)
    record_values['KEY_GRANT']=obj(subject=idt,public_key=h,kid=h,epoch=pos,purposes=arr(enum(*(TYPES+['SOURCE','CONTROL','READ'])),1),root_generation=pos,enrollment_ref=h,**times)
    if scene=='payment':
        constraints=obj(payer_set=arr(idt,1),max_amount_minor=pos)
    elif scene=='industrial':
        constraints=obj(line_set=arr(idt,1,16),station_set=arr(idt,1,16),unit_set=arr(idt,1,16),route_set=arr(enum('RELEASE','QUARANTINE','INSPECT'),1,16))
    else:
        constraints=obj(patient_set=arr(idt,1,16),encounter_set=arr(idt,1,16),template_set=arr(enum('DEMO-ORDER-A','DEMO-ORDER-B'),1,16))
    broad=obj(scope_set=arr(scope,1,8))
    grant=obj(subject=idt,role=ref('Role'),epoch=pos,tool_set=arr(idt,1,256 if scene=='payment' else 16),destination_set=arr(idt,1,256 if scene=='payment' else 16),scope_set=arr(scope,1,256 if scene=='payment' else 16),constraints=constraints,**times)
    if scene!='payment':
        if scene=='industrial':
            control_constraints=obj(line_set=arr(idt,1,16),station_set=arr(idt,1,16),route_set=arr(enum('RELEASE','QUARANTINE','INSPECT'),1,3))
            grant['properties']['constraints']={'oneOf':[constraints,control_constraints,broad]}
            grant['allOf']=[{'if':{'properties':{'role':const('AUDITOR')},'required':['role']},'then':{'properties':{'constraints':broad}},'else':{'if':{'properties':{'role':enum('CONTROLLER','SOURCE','ISSUER','EXECUTOR')},'required':['role']},'then':{'properties':{'constraints':control_constraints}},'else':{'properties':{'constraints':constraints}}}}]
        else:
            grant['properties']['constraints']={'oneOf':[constraints,broad]}
            grant['allOf']=[{'if':{'properties':{'role':const('AUDITOR')},'required':['role']},'then':{'properties':{'constraints':broad}},'else':{'properties':{'constraints':constraints}}}]
    record_values['ROLE_GRANT']=grant
    d['BehaviorRow']=obj(accepted_count=n,count_cap=pos if scene=='payment' else const('32'),inflight=arr(b16))
    d['BehaviorWitness']=obj(key=tuple_schema(*ss,idt),revision=pos,ref=h,row=ref('BehaviorRow'))
    unit='CNY_MINOR' if scene=='payment' else 'UNIT' if scene=='industrial' else 'ORDER'
    resource_key=tuple_schema(*ss,idt,const('CNY')) if scene=='payment' else tuple_schema(*ss,const('route-capacity'),idt,idt,const('unit')) if scene=='industrial' else tuple_schema(*ss,const('order-capacity'),idt,const('order'))
    d['ResourceWitness']=obj(reservation_id=b16,key=resource_key,unit=const(unit),amount=pos,capacity_before=n,reserved_before=n,spent_before=n,reserved_after=n,spent_after=n,revision_before=pos,revision_after=pos)
    d['CredentialWitness']=obj(subject=idt,kid=h,public_key=h,key_grant_ref=h,role=ref('Role'),role_grant_ref=h,key_revision=pos,role_revision=pos,verified_at_seq=pos)
    commit=obj(ctx=ctx,action=ref('Action'),permit_ref=h,proof_ref=h,authorization_ref=h,review_refs=refs,accept_seq=pos,accepted_at=n,trusted_time=obj(lo=n,hi=n),checked_deps=deps,reservation_plan=arr(ref('ResourceWitness'),1),reservation_ids=arr(b16,1),behavior_before=ref('BehaviorWitness'),behavior_after=ref('BehaviorWitness'),taskflight=obj(key=tuple_schema(*ss,b16),operation_id=b16),dispatch_before=n,frozen_tool_request=ref('Action'),signing_public_key=h,credential_witnesses=arr(ref('CredentialWitness'),1))
    record_values['COMMIT']=commit
    record_values['TOOL_FINAL']=obj(method=const('tool-final-v2'),ledger_id=idt,operation_id=b16,action_hash=h,dispatch_attempt=b16,tool=const(tool),tool_version=const('1'),destination=idt,outcome=enum('SUCCEEDED','FAILED_CONFIRMED'),effect_id=maybe('Id'),no_late_effect={'type':'boolean'},final_seq=pos,finalized_at=n,attestation=obj(issuer=idt,kid=h,sig=ref('B64')),**times)
    record_values['TOOL_TRUST']=obj(issuer=idt,tool=const(tool),tool_version=const('1'),destination=idt,ledger_id=idt,evidence_method=const('tool-final-v2'),public_key=h,kid=h,epoch=pos,**times)
    if scene=='payment':
        record_values['POLICY']=obj(**common_policy,destination=idt,currency=const('CNY'),method=const('order-match-v1'),risk_method=const('history-int-v2'),partition=idt,count_cap=pos,**times)
        record_values['PAY_TASK']=obj(task_id=b16,task_revision=pos,principal=idt,holder=idt,holder_kid=h,order_id=idt,stage=idt,payer=idt,allowed_payees=arr(idt,1),max_amount_minor=pos,executor=idt,destination=idt,policy_ref=h,**times)
        old=json.loads((ROOT/'system_dev/contracts/pay1.schema.json').read_text(encoding='utf-8'))['$defs']
        def old_copy(name):
            target='V25_'+name
            if target in d: return
            d[target]={}
            v=copy.deepcopy(old[name])
            def rewrite(x):
                if isinstance(x,dict):
                    for k,y in x.items():
                        if k=='$ref' and y.startswith('#/$defs/'):
                            sub=y.split('/')[-1]; old_copy(sub); x[k]='#/$defs/V25_'+sub
                        else: rewrite(y)
                elif isinstance(x,list):
                    for y in x: rewrite(y)
            rewrite(v); d[target]=v
        old_copy('Evidence')
        record_values['PAY_EVIDENCE']=obj(source_version=const('2.5'),source_profile=const('PAY-1'),source_type=const('Evidence'),source_ref=h,source_envelope=ref('V25_Evidence'))
        d['Case']=obj(case_id=idt,intent=idt,revision=n,scope=scope,partition=idt,payer=idt,stage=idt,currency=const('CNY'),ratio=ref('Ratio'),action_class=enum('PAY','HOLD'),event_at=n,known_at=n,label=const('CONFIRMED_GOOD'))
        record_values['PAY_HISTORY']=obj(partition=idt,publication_revision=pos,feature_schema=const('ratio-int-v1'),cases=arr(ref('Case'),0,128),**times)
        record_values['ASSESSMENT']=obj(action_hash=h,policy_ref=h,task_ref=h,evidence_refs=arr(h,1,1),snapshot_ref=h,cutoff=n,feature=ref('Ratio'),selected_cases=arr(idt,0,5,True),support=decimal(5),different=decimal(5),result=enum('CLEAR','FLAG','INSUFFICIENT','UNKNOWN'),method=const('history-int-v2'),**times)
    else:
        route=enum('RELEASE','QUARANTINE','INSPECT'); template=enum('DEMO-ORDER-A','DEMO-ORDER-B')
        attest=obj(issuer=idt,kid=h,iat=n,exp=n,sig=ref('B64'))
        if scene=='industrial':
            destinations=obj(release=const('ind-release-bin'),quarantine=const('ind-quarantine-bin'),inspect=const('ind-inspection-bay'))
            record_values['POLICY']=obj(**common_policy,controller=idt,line_id=const('demo-line-a'),station_id=const('demo-check-1'),route_destinations=destinations,decision_package_ref=h,history_mode=const('DISABLED'),max_cycles=const('2'),evidence_ttl_seconds=const('300'),task_ttl_seconds=const('900'),behavior_count_cap=const('32'),capacity_per_destination=const('8'),**times)
            record_values['IND_PACKAGE']=obj(package_id=const('ind-fixed-package-1'),package_revision=pos,detector=const('SYNTHETIC-LABEL-1'),preprocessing=const('IDENTITY-1'),output_schema=const('IND-LABEL-V1'),mapper=const('IND-ROUTE-V1'),label_routes=obj(normal=const('RELEASE'),defect=const('QUARANTINE'),uncertain=const('INSPECT')),**times)
            record_values['IND_UNIT']=obj(unit_id=idt,batch_id=idt,line_id=idt,station_id=idt,synthetic=const(True),**times)
            phase=enum('INITIAL','REINSPECT'); cycle=enum('1','2'); label=enum('DEMO_NORMAL','DEMO_DEFECT','DEMO_UNCERTAIN')
            record_values['IND_TASK']=obj(task_id=b16,task_revision=pos,principal=idt,holder=idt,holder_kid=h,executor=idt,policy_ref=h,line_id=idt,station_id=idt,allowed_units=arr(obj(unit_ref=h,unit_id=idt,batch_id=idt,inspection_cycle=cycle,phase=phase),1,16),allowed_routes=arr(route,1,3),tool=const(tool),tool_version=const('1'),route_destinations=destinations,max_inflight=const('1'),**times)
            record_values['IND_EVIDENCE']=obj(data=obj(evidence_id=b16,evidence_revision=pos,unit_ref=h,unit_id=idt,batch_id=idt,line_id=idt,station_id=idt,inspection_cycle=cycle,phase=phase,sampled_at=n,known_at=n,quality_flag=enum('VALID','INVALID'),label=label),attestation=attest)
            record_values['ASSESSMENT']=obj(scope=scope,operation_id=b16,action_hash=h,policy_ref=h,task_ref=h,evidence_refs=arr(h,1,1),decision_package_ref=h,cutoff=n,method=const('ind-fixed-v1'),history_mode=const('DISABLED'),label=label,proposed_route=route,result=const('MATCH'),required_reviews=arr(enum('QUALITY_REVIEW'),0,1),**times)
            d['SceneRow']=obj(unit_ref=h,inspection_cycle=cycle,phase=phase,state=enum('READY','ACCEPTED','RELEASED','QUARANTINED','AWAITING_REINSPECT','MANUAL_HOLD','STOPPED','EFFECT_UNKNOWN','HALTED'),evidence_ref=maybe('B32'),operation_id=maybe('B16'),predecessor_operation_id=maybe('B16'),predecessor_commit_ref=maybe('B32'))
            namespace='UNIT'
        else:
            record_values['POLICY']=obj(**common_policy,controller=idt,destination=const('med-demo-ledger'),allowed_templates=arr(template,2,2),template_mapping=obj(demo_a=const('DEMO-ORDER-A'),demo_b=const('DEMO-ORDER-B')),history_mode=const('DISABLED'),required_review=const('CLINICAL_REVIEW'),evidence_ttl_seconds=const('300'),task_ttl_seconds=const('900'),behavior_count_cap=const('32'),destination_capacity=const('8'),max_groups_per_encounter=const('1'),**times)
            record_values['MED_ENCOUNTER']=obj(synthetic_patient_id=idt,encounter_id=idt,synthetic=const(True),**times)
            record_values['MED_TASK']=obj(task_id=b16,task_revision=pos,principal=idt,holder=idt,holder_kid=h,executor=idt,policy_ref=h,encounter_ref=h,synthetic_patient_id=idt,encounter_id=idt,order_group_id=b16,phase=const('SUBMIT'),allowed_templates=arr(template,1,2),tool=const(tool),tool_version=const('1'),destination=const('med-demo-ledger'),max_inflight=const('1'),**times)
            record_values['MED_EVIDENCE']=obj(data=obj(evidence_id=b16,evidence_revision=pos,record_id=idt,record_revision=pos,encounter_ref=h,synthetic_patient_id=idt,encounter_id=idt,record_status=enum('AVAILABLE','UNAVAILABLE'),completeness=enum('COMPLETE','INCOMPLETE'),event_at=n,known_at=n,template_label=enum('DEMO_A','DEMO_B')),attestation=attest)
            record_values['ASSESSMENT']=obj(scope=scope,operation_id=b16,action_hash=h,policy_ref=h,task_ref=h,evidence_refs=arr(h,1,1),cutoff=n,method=const('med-fixed-v1'),history_mode=const('DISABLED'),template_label=enum('DEMO_A','DEMO_B'),proposed_template=template,result=const('MATCH'),required_reviews=arr(enum('CLINICAL_REVIEW'),1,1),**times)
            d['SceneRow']=obj(encounter_ref=h,order_group_id=maybe('B16'),phase=const('SUBMIT'),state=enum('READY','ACCEPTED','REGISTERED','STOPPED','EFFECT_UNKNOWN','HALTED'),evidence_ref=maybe('B32'),operation_id=maybe('B16'))
            namespace='ENCOUNTER'
        d['SceneWitness']=obj(namespace=const(namespace),key=tuple_schema(*keys[namespace]),revision=pos,ref=h,row=ref('SceneRow'))
        commit['properties'].update(scene_before=ref('SceneWitness'),scene_after=ref('SceneWitness'))
        commit['required'].extend(['scene_before','scene_after'])
    for kind,value in record_values.items():
        d['Record_'+kind]=obj(version=const('2.6'),profile=const(profile),kind=const(kind),scope=scope,value=value)
    d['Record']={'oneOf':[ref('Record_'+k) for k in record_values]}
    d['Bundle']=obj(message=ref('Envelope'),objects=arr({'oneOf':[ref('Envelope'),ref('Record')]},0,128,True))
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':f'https://zjj.invalid/v26/{stem}.schema.json','title':profile+' 2.6-R2 structural contract; not authorization','$ref':'#/$defs/Envelope','$defs':d,'x-zjj-profile':profile,'$comment':'Canonical bytes, signatures, cross-field guards, references, authority, time and state transitions are required by 01/02/03/04; schema alone is insufficient.'}

def localize(value):
    if isinstance(value,dict): return {k:(v.replace('#/$defs/','#/components/schemas/') if k=='$ref' else localize(v)) for k,v in value.items()}
    if isinstance(value,list): return [localize(v) for v in value]
    return value

def main():
    folder=BASE/'contracts'; folder.mkdir(exist_ok=True)
    for profile,(scene,stem) in PROFILES.items():
        s=build(profile)
        (folder/(stem+'.schema.json')).write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        defs=localize(s['$defs']); paths={}
        prefix='/zjj/2.6'+('' if scene=='payment' else '/'+scene)
        for route,typ,out in [('issue','IssueRequest',['Result']),('challenge','ChallengeRequest',['Challenge','Result']),('commit','CommitProof',['Result']),('status','StatusQuery',['Result'])]:
            def bundle(types): return obj(message={'oneOf':[{'$ref':'#/components/schemas/'+t} for t in types]},objects=defs['Bundle']['properties']['objects'])
            content=lambda schema:{'application/json':{'schema':schema}}
            paths[prefix+'/'+route]={'post':{'operationId':stem+'_'+route,'description':'Fixed profile/type/aud; TLS 1.3; no 0-RTT. Authenticated body controls outcome, HTTP 200 does not grant permission. No product service supplied.','requestBody':{'required':True,'content':content(bundle([typ]))},'responses':{'200':{'description':'Signed response; verify binding, signature and current or historical role as specified.','content':content(bundle(out))},'400':{'description':'Malformed or unauthenticated transport input; no business outcome asserted'},'413':{'description':'Byte/object limits exceeded'},'415':{'description':'Unsupported content type'},'503':{'description':'Communication outcome unknown'}}}}
        api={'openapi':'3.1.1','info':{'title':profile+' protocol transport','version':'2.6-R2'},'paths':paths,'components':{'schemas':defs}}
        (folder/(stem+'.openapi.json')).write_text(json.dumps(api,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Generated 3 structural schemas and 3 protocol-only OpenAPI contracts.')

if __name__=='__main__': main()
