"""PAY-1 selected RequiredDeps independently reconstructed from trusted rows.

TrustedStore is a laboratory W/C fixture: its imports presume an already authenticated
control-plane publisher. It is deliberately not a signed enrollment implementation.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from research.reference_executor.wire import require,ProtocolError,rec_ref,digest,sortset,raw,is_id,number,validset
from .pay_history import record,scope_check,parse_task,parse_policy,parse_action,fields

@dataclass(frozen=True)
class Active:
    revision:int
    ref:str
    value:dict
    record:dict|None
    active:bool

class TrustedStore:
    def __init__(self,scope):
        scope_check(scope);self.scope=copy.deepcopy(scope)
        self._rows={}
    def _set(self,ns,key,revision,ref,value,document=None):
        require(type(key) is list and all(type(v) is str and bool(v) for v in key),'KEY')
        require(isinstance(revision,int) and revision>0,'REVISION')
        k=(ns,tuple(key));old=self._rows.get(k)
        require(old is None or revision>old.revision,'NONMONOTONIC')
        if old is not None and not old.active and ns=='KEY':
            raise ProtocolError('REVOKED_KEY_TOMBSTONE')
        self._rows[k]=Active(revision,ref,copy.deepcopy(value),copy.deepcopy(document),True)
    def publish_record(self,ns,key,revision,r,expected_kind):
        v=record(r,expected_kind,self.scope)
        # Enforce identity between authoritative row revision and the version in
        # each published Record. Historical source bridge derives ORDER revision
        # from the authenticated v2.5 Evidence payload.
        version_field={'POLICY':'policy_revision','TASK':'task_revision',
                       'EXPERIENCE':'publication_revision','KEY':'epoch','ROLE':'epoch'}
        if ns in version_field:
            require(number(v[version_field[ns]],True) and int(v[version_field[ns]])==revision,'ROW_VERSION')
        if ns=='ORDER':
            payload=v['source_envelope']['body']['payload']
            require(number(payload['order_revision'],True) and int(payload['order_revision'])==revision,'ROW_VERSION')
        ref=rec_ref(r);self._set(ns,key,revision,ref,v,r)
    def publish_state(self,ns,key,revision,value):
        ref=digest(['ZJJ-STATE-v1',ns,key,str(revision),value]);self._set(ns,key,revision,ref,value,None)
    def current(self,ns,key):
        p=self._rows.get((ns,tuple(key)))
        require(p is not None,'STATE_UNAVAILABLE')
        require(p.active,'REVOKED')
        return p
    def dep(self,ns,key):
        p=self.current(ns,key)
        return {'namespace':ns,'key':list(key),'revision':str(p.revision),'ref':p.ref}
    def remove(self,ns,key):
        k=ns,tuple(key);v=self.current(ns,key)
        self._rows[k]=Active(v.revision+1,v.ref,v.value,v.record,False)


def _parse_keygrant(r,scope,kid,subject,purpose,at):
    v=record(r,'KEY_GRANT',scope)
    fields(v,{'subject','public_key','kid','epoch','purposes','iat','exp','root_generation','enrollment_ref'})
    require(v['subject']==subject and v['kid']==kid and is_id(subject),'NO_ROLE')
    raw(kid,32);raw(v['public_key'],32);raw(v['enrollment_ref'],32)
    require(validset(v['purposes']) and purpose in v['purposes'],'NO_ROLE')
    require(number(v['epoch'],True) and number(v['root_generation'],True),'RANGE')
    require(number(v['iat']) and number(v['exp']) and int(v['iat'])<=at<int(v['exp']),'EXPIRED')
    from research.reference_executor.wire import keyid
    require(keyid(raw(v['public_key'],32))==kid,'KEY_BINDING')
    return v


def _parse_rolegrant(r,scope,subject,role,action,at):
    v=record(r,'ROLE_GRANT',scope)
    fields(v,{'subject','role','epoch','iat','exp','tool_set','destination_set','scope_set','constraints'})
    require(v['subject']==subject and v['role']==role,'NO_ROLE')
    require(number(v['epoch'],True) and number(v['iat']) and number(v['exp']) and int(v['iat'])<=at<int(v['exp']),'EXPIRED')
    require(validset(v['tool_set']) and action['tool'] in v['tool_set'],'NO_ROLE')
    require(validset(v['destination_set']) and action['destination'] in v['destination_set'],'NO_ROLE')
    require(validset(v['scope_set']) and scope in v['scope_set'],'NO_ROLE')
    c=v['constraints'];fields(c,{'payer_set','max_amount_minor'})
    require(validset(c['payer_set']) and action['payload']['payer'] in c['payer_set'],'NO_ROLE')
    require(number(c['max_amount_minor'],True) and int(action['payload']['amount_minor'])<=int(c['max_amount_minor']),'NO_ROLE')
    return v


def _check_credential(store,action,subject,kid,role,purpose,at):
    scope=store.scope
    key_record=store.current('KEY',[kid]);role_record=store.current('ROLE',[scope['domain'],scope['tenant'],scope['scenario'],subject,role])
    require(key_record.record is not None and role_record.record is not None,'OBJECT_KIND')
    kg=_parse_keygrant(key_record.record,scope,kid,subject,purpose,at)
    rg=_parse_rolegrant(role_record.record,scope,subject,role,action,at)
    require(key_record.revision==int(kg['epoch']) and role_record.revision==int(rg['epoch']),'STALE')
    return [store.dep('KEY',[kid]),store.dep('ROLE',[scope['domain'],scope['tenant'],scope['scenario'],subject,role])]


def required_pay_deps(store,action,task_id,signers,needs_review,at):
    """Read all implicit dependencies without trusting signed Permit.deps.

    signers contains genuine upstream signers, resolved and verified by another
    input-envelope component. H/G/X/E match controlled Task/Policy identities.
    """
    scope=store.scope;parse_action(action,scope)
    prefix=[scope['domain'],scope['tenant'],scope['scenario']];p=action['payload']
    policyrow=store.current('POLICY',prefix)
    require(policyrow.record is not None,'OBJECT_KIND')
    policy=parse_policy(policyrow.record,scope,at)
    taskrow=store.current('TASK',prefix+[task_id])
    require(taskrow.record is not None,'OBJECT_KIND')
    task=parse_task(taskrow.record,scope,at)
    require(task['policy_ref']==policyrow.ref,'POLICY_BINDING')
    require(task['task_id']==task_id and task['holder']==action['holder'],'TASK_BINDING')
    require(policy['gateway']==signers['G'][0] and policy['gateway_kid']==signers['G'][1],'G_BINDING')
    require(policy['executor']==signers['X'][0] and policy['executor_kid']==signers['X'][1],'X_BINDING')
    require(policy['source']==signers['E'][0] and action['holder_kid']==signers['H'][1] and action['holder']==signers['H'][0],'H_BINDING')
    require(action['executor']==policy['executor'],'X_BINDING')
    require('U' in signers and signers['U'][0] not in (signers['G'][0],signers['X'][0]),'SUBJECT_SEPARATION')
    require(not needs_review or ('V' in signers and signers['V'][0] not in (signers['U'][0],signers['G'][0],signers['X'][0])),'SUBJECT_SEPARATION')
    raw(signers['E'][1],32)
    o=[store.dep('POLICY',prefix),store.dep('TASK',prefix+[task_id]),
       store.dep('ORDER',prefix+[p['order_id'],p['stage']]),
       store.dep('EXPERIENCE',prefix+[policy['partition']]),
       store.dep('BEHAVIOR',prefix+[action['principal']])]
    actor_roles={'E':('SOURCE','SOURCE'), 'H':('HOLDER','IssueRequest'),
                 'G':('ISSUER','Permit'),'X':('EXECUTOR','Acceptance'),
                 'U':('FINANCE','Authorization')}
    if needs_review:actor_roles['V']=('ANOMALY','Review')
    for alias,(role,purpose) in actor_roles.items():
        subject,kid=signers[alias]
        o.extend(_check_credential(store,action,subject,kid,role,purpose,at))
    # Distinct actor records may refer to the same actual registered grant.
    unique={}
    for d in o:
        key=d['namespace'],tuple(d['key'])
        if key in unique:require(unique[key]==d,'DEP_CONFLICT')
        unique[key]=d
    return sortset(list(unique.values()))


def verify_claimed_dependencies(claimed,derived):
    require(validset(claimed),'DEP_CONFLICT')
    require(claimed==derived,'DEP_CONFLICT')
    return True
