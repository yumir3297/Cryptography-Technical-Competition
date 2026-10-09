"""PAY-1 history-int-v2 independent recomputation (ZJJ-CORE-2.6-R2 §PAY4).

This module verifies the exact enumerated PAY fields and algorithm, with
trusted authenticated-publisher metadata supplied by the caller. It is NOT a
full v2.5 Evidence parser, C enrollment service or W transactional backend.
All externally supplied verdicts are recomputed rather than trusted.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from research.reference_executor.wire import (
    ProtocolError, require, canonical, raw, b64, rec_ref, action_hash,
    number, is_id, validset, PROFILE_SCENARIO, strict_verify,
)

SCOPE_KEYS={'domain','tenant','scenario'}
PAY_PAYLOAD={'order_id','stage','payer','payee','amount_minor','currency','purpose'}
ACTION_KEYS={'scope','operation_id','principal','holder','holder_kid','executor',
             'tool','tool_version','destination','payload'}
POLICY_FIELDS={'profile','schema_version','verifier_version','policy_revision',
               'gateway','gateway_kid','executor','executor_kid','source','readers',
               'tool','tool_version','destination','currency','method','risk_method',
               'partition','count_cap','iat','exp'}
TASK_FIELDS={'task_id','task_revision','principal','holder','holder_kid','order_id',
             'stage','payer','allowed_payees','max_amount_minor','executor',
             'destination','policy_ref','iat','exp'}
CASE_FIELDS={'case_id','intent','revision','scope','partition','payer','stage',
             'currency','ratio','action_class','event_at','known_at','label'}
HISTORY_FIELDS={'partition','publication_revision','feature_schema','cases','iat','exp'}
EVIDENCE_FIELDS={'order_id','stage','order_revision','payer','payee','amount_minor',
                 'currency','accepted_goods','unsettled','beneficiary_active','observed_at'}
ASSESSMENT_FIELDS={'action_hash','policy_ref','task_ref','evidence_refs','snapshot_ref',
                   'cutoff','feature','selected_cases','support','different','result',
                   'method','iat','exp'}
BASIS_FIELDS={'scope','operation_id','action','action_hash','policy_ref','task_ref',
              'evidence_refs','assessment_ref','required_reviews','deps','iat','exp'}


def fields(v,expected,code='FIELDS'):
    require(type(v) is dict and set(v)==set(expected),code)

def idfield(v): require(is_id(v),'ID')
def nat(v,positive=False): require(number(v,positive),'NUMBER')
def bound_time(iat,exp,t,maxlife):
    nat(iat);nat(exp);require(int(iat)<int(exp) and int(exp)-int(iat)<=maxlife,'TIME')
    require(int(iat)<=t<int(exp),'EXPIRED')

def scope_check(v):
    fields(v,SCOPE_KEYS,'SCOPE')
    for k in SCOPE_KEYS:idfield(v[k])
    require(v['scenario']=='payment','PROFILE')

def record(record,kind,scope):
    fields(record,{'version','profile','kind','scope','value'})
    require((record['version'],record['profile'],record['kind'])==('2.6','PAY-1',kind),'OBJECT_KIND')
    require(record['scope']==scope,'WRONG_SCOPE')
    return record['value']

def parse_policy(r,scope,at):
    v=record(r,'POLICY',scope);fields(v,POLICY_FIELDS)
    for k in ('gateway','executor','source','destination','partition'):idfield(v[k])
    for k in ('gateway_kid','executor_kid'):raw(v[k],32)
    require(validset(v['readers']) and bool(v['readers']) and all(is_id(s) for s in v['readers']),'READERS')
    require({v['gateway'],v['executor'],v['source']}.issubset(v['readers']),'READERS')
    require((v['profile'],v['schema_version'],v['verifier_version'])==('PAY-1','pay1-payload-v1','pay1-verifier-v1'),'POLICY')
    require((v['tool'],v['tool_version'],v['currency'],v['method'],v['risk_method'])==('pay-sim','1','CNY','order-match-v1','history-int-v2'),'POLICY')
    nat(v['policy_revision'],True);nat(v['count_cap'],True)
    bound_time(v['iat'],v['exp'],at,31536000)
    return v

def parse_task(r,scope,at):
    v=record(r,'PAY_TASK',scope);fields(v,TASK_FIELDS)
    for k in ('principal','holder','order_id','stage','payer','executor','destination'):idfield(v[k])
    raw(v['task_id'],16);raw(v['holder_kid'],32);raw(v['policy_ref'],32)
    require(validset(v['allowed_payees']) and bool(v['allowed_payees']) and all(is_id(x) for x in v['allowed_payees']),'PAYEES')
    for k in ('task_revision','max_amount_minor'):nat(v[k],True)
    bound_time(v['iat'],v['exp'],at,86400)
    return v

def parse_history(r,scope,at):
    v=record(r,'PAY_HISTORY',scope);fields(v,HISTORY_FIELDS)
    require(v['feature_schema']=='ratio-int-v1','FEATURE_SCHEMA')
    idfield(v['partition']);nat(v['publication_revision'],True)
    bound_time(v['iat'],v['exp'],at,31536000)
    a=v['cases'];require(type(a) is list and len(a)<=128 and validset(a),'CASES')
    ids=set();intents=set()
    for case in a:
        fields(case,CASE_FIELDS,'CASE_FIELDS')
        for k in ('case_id','intent','partition','payer','stage'):idfield(case[k])
        scope_check(case['scope'])
        nat(case['revision']);nat(case['ratio']);nat(case['event_at']);nat(case['known_at'])
        require(int(case['ratio'])<=10000,'RATIO')
        require(case['currency']=='CNY' and case['action_class'] in ('PAY','HOLD') and case['label']=='CONFIRMED_GOOD','CASE_ENUM')
        # History publication cannot know a case before its event occurred.
        require(int(case['event_at'])<=int(case['known_at'])<=int(v['iat']),'HISTORY_TIME')
        require(case['case_id'] not in ids and case['intent'] not in intents,'DUPLICATE_CASE')
        ids.add(case['case_id']);intents.add(case['intent'])
    return v

def parse_action(a,scope):
    fields(a,ACTION_KEYS,'ACTION_FIELDS');require(a['scope']==scope,'WRONG_SCOPE')
    raw(a['operation_id'],16);raw(a['holder_kid'],32)
    for k in ('principal','holder','executor','tool','tool_version','destination'):idfield(a[k])
    p=a['payload'];fields(p,PAY_PAYLOAD,'ACTION_PAYLOAD')
    for k in ('order_id','stage','payer','payee'):idfield(p[k])
    nat(p['amount_minor'],True)
    require((p['currency'],p['purpose'],a['tool'],a['tool_version'])==('CNY','order-settlement','pay-sim','1'),'ACTION_POLICY')
    return p

def legacy_dep_structure(d):
    """v2.5 PAY Dep field/typed key shape; not historical row authorization."""
    fields(d,{'namespace','key','revision','ref'},'SOURCE_DEPS')
    ns=d['namespace'];require(ns in {'CONFIG','TASK','ORDER','EXPERIENCE','ROLE','KEY','BEHAVIOR'},'SOURCE_DEPS')
    key=d['key'];require(type(key) is list,'SOURCE_DEPS')
    raw(d['ref'],32);nat(d['revision'])
    prefix=[lambda x:is_id(x),lambda x:is_id(x),lambda x:x=='payment']
    items={
      'CONFIG':prefix,
      'TASK':prefix+[lambda x:type(x) is str and len(raw(x,16))==16],
      'ORDER':prefix+[lambda x:is_id(x),lambda x:is_id(x)],
      'EXPERIENCE':prefix+[lambda x:is_id(x)],
      'ROLE':prefix+[lambda x:is_id(x),lambda x:x in {'HOLDER','ISSUER','SOURCE','FINANCE','ANOMALY','EXECUTOR'}],
      'KEY':[lambda x:type(x) is str and len(raw(x,32))==32],
      'BEHAVIOR':prefix+[lambda x:is_id(x)],
    }[ns]
    require(len(key)==len(items),'SOURCE_DEPS')
    require(all(check(k) for check,k in zip(items,key)),'SOURCE_DEPS')
    return True

def claims(task,action,source_payload):
    p=action['payload'];fields(source_payload,EVIDENCE_FIELDS,'EVIDENCE_FIELDS')
    for k in ('order_id','stage','payer','payee'):idfield(source_payload[k])
    nat(source_payload['order_revision'],True);nat(source_payload['amount_minor'],True);nat(source_payload['observed_at'])
    require(source_payload['currency']=='CNY','CLAIM_FALSE')
    for k in ('accepted_goods','unsettled','beneficiary_active'):
        require(type(source_payload[k]) is bool and source_payload[k] is True,'CLAIM_FALSE')
    require(all(source_payload[k]==p[k] for k in ('order_id','stage','payer','payee','amount_minor','currency')),'CLAIM_FALSE')
    require(all(task[k]==action[k] for k in ('principal','holder','holder_kid','executor','destination')),'TASK_BINDING')
    require(all(task[k]==p[k] for k in ('order_id','stage','payer')),'TASK_BINDING')
    require(p['payee'] in task['allowed_payees'],'TASK_BINDING')
    require(int(p['amount_minor'])<=int(task['max_amount_minor']),'TASK_BINDING')
    return True

@dataclass(frozen=True)
class Risk:
    feature: str
    selected_cases: tuple[str,...]
    support: str
    different: str
    result: str
    required_reviews: tuple[str,...]


def history_int_v2(action,task,policy,history,cutoff):
    """Full deterministic selection and integer decision on pre-validated inputs."""
    nat(cutoff)
    p=action['payload']
    x=(10000*int(p['amount_minor']))//int(task['max_amount_minor'])
    require(0<=x<=10000,'FEATURE_RANGE')
    selected=[]
    for c in history['cases']:
        if (c['scope']==action['scope'] and c['partition']==policy['partition'] and
                c['payer']==p['payer'] and c['stage']==p['stage'] and c['currency']==p['currency'] and
                int(c['event_at'])<=int(cutoff) and int(c['known_at'])<=int(cutoff) and
                abs(int(c['ratio'])-x)<=1000):
            selected.append(c)
    selected.sort(key=lambda c:(abs(int(c['ratio'])-x),c['case_id'].encode('ascii')))
    selected=selected[:5];n=len(selected)
    d=sum(c['action_class']!='PAY' for c in selected)
    result='INSUFFICIENT' if n<3 else 'FLAG' if 5*d>=4*n else 'CLEAR'
    required=() if result=='CLEAR' else ('ANOMALY',) if result=='FLAG' else ('LOW_EVIDENCE',)
    return Risk(str(x),tuple(c['case_id'] for c in selected),str(n),str(d),result,required)

def assessment_from(risk,refs,cutoff,exp):
    fields(refs,{'action_hash','policy_ref','task_ref','evidence_ref','snapshot_ref'})
    return {'action_hash':refs['action_hash'],'policy_ref':refs['policy_ref'],
      'task_ref':refs['task_ref'],'evidence_refs':[refs['evidence_ref']],
      'snapshot_ref':refs['snapshot_ref'],'cutoff':str(cutoff),
      'feature':risk.feature,'selected_cases':list(risk.selected_cases),
      'support':risk.support,'different':risk.different,'result':risk.result,
      'method':'history-int-v2','iat':str(cutoff),'exp':str(exp)}

def verify_assessment(untrusted,expected):
    fields(untrusted,ASSESSMENT_FIELDS,'ASSESSMENT_FIELDS')
    require(untrusted==expected,'ASSESSMENT_MISMATCH')
    return True


def verify_pay_authoritative(*,scope,action,policy_record,task_record,history_record,
    evidence_record,source_public_key,source_subject,cutoff,
    policy_rev,task_rev,order_rev,history_rev,
    witness_authenticated,claimed_assessment=None):
    """A strict *subset* acceptance predicate for authoritative PAY inputs.

    The caller must prove W publication/control and historical C provenance;
    witness_authenticated is injected from a TRUSTED harness, not client data.
    Schema parsing is complete for the PAY records listed here, but v2.5
    Evidence deps/audience/issuer historical enrollment require independent
    legacy validation and are outside this function's guarantee.
    """
    scope_check(scope);nat(str(cutoff));now=int(cutoff)
    require(witness_authenticated is True,'AUTHORITY_UNKNOWN')
    p=parse_action(action,scope)
    pol=parse_policy(policy_record,scope,now)
    task=parse_task(task_record,scope,now)
    hist=parse_history(history_record,scope,now)
    require((int(pol['policy_revision']),int(task['task_revision']),int(hist['publication_revision']))==(policy_rev,task_rev,history_rev),'STALE')
    require(task['policy_ref']==rec_ref(policy_record),'POLICY_BINDING')
    require(pol['executor']==action['executor'] and pol['destination']==action['destination'],'POLICY_BINDING')
    require(hist['partition']==pol['partition'],'PARTITION')
    ev=record(evidence_record,'PAY_EVIDENCE',scope)
    fields(ev,{'source_version','source_profile','source_type','source_ref','source_envelope'})
    require((ev['source_version'],ev['source_profile'],ev['source_type'])==('2.5','PAY-1','Evidence'),'SOURCE_TYPE')
    env=ev['source_envelope'];fields(env,{'protected','body','sig'},'SOURCE_FIELDS')
    h=env['protected'];b=env['body']
    fields(h,{'proto','version','profile','alg','type','issuer','kid'},'SOURCE_FIELDS')
    require((h['proto'],h['version'],h['profile'],h['alg'],h['type'],h['issuer'])==('ZJJ-AAP','2.5','PAY-1','Ed25519','Evidence',source_subject),'SOURCE_TYPE')
    require(source_subject==pol['source'],'SOURCE_BINDING')
    require(h['kid']==__import__('research.reference_executor.wire',fromlist=['keyid']).keyid(source_public_key),'SOURCE_KEY')
    fields(b,{'id','scope','iat','exp','aud','refs','deps','payload'},'SOURCE_FIELDS')
    raw(b['id'],16);scope_check(b['scope']);require(b['scope']==scope,'WRONG_SCOPE')
    bound_time(b['iat'],b['exp'],now,900)
    require(validset(b['aud']) and bool(b['aud']) and all(is_id(x) and x in pol['readers'] for x in b['aud']),'SOURCE_AUDIENCE')
    require(validset(b['refs']) and not b['refs'] and validset(b['deps']),'SOURCE_REFS')
    for dep in b['deps']:
        legacy_dep_structure(dep)  # types checked; historical closure separately trusted
    import hashlib
    from research.reference_executor.wire import digest
    require(ev['source_ref']==digest(['ZJJ-OBJ-v1',h,b]),'SOURCE_REF')
    strict_verify(source_public_key,raw(env['sig'],64),canonical(['ZJJ-SIG-v1',h,b]))
    claims(task,action,b['payload'])
    require(int(b['payload']['observed_at'])<=int(b['iat']),'SOURCE_TIME')
    require(int(b['payload']['order_revision'])==order_rev,'STALE')
    risk=history_int_v2(action,task,pol,hist,str(cutoff))
    expire=min(int(pol['exp']),int(task['exp']),int(hist['exp']),int(b['exp']),now+900)
    require(expire>now,'EXPIRED')
    refs={'action_hash':action_hash('PAY-1',action),'policy_ref':rec_ref(policy_record),
          'task_ref':rec_ref(task_record),'evidence_ref':rec_ref(evidence_record),
          'snapshot_ref':rec_ref(history_record)}
    expected=assessment_from(risk,refs,now,expire)
    if claimed_assessment is not None:verify_assessment(claimed_assessment,expected)
    return risk,expected
