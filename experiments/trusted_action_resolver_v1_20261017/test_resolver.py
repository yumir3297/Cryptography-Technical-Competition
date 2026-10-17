"""Trusted Action Resolver V1.0 conformance probes, not a production Resolver.

Uses the existing isolated adapter unmodified. Test-only lab owns all simulated
approvals. No DelegationProof implementation or untrusted signing endpoint.
"""
import copy
import json
import os
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from competition.core.trusted_state import prefix
from competition.support.wire import ProtocolError, b64, canonical, raw, action_hash, strict_verify
from competition.w_cases import public_snapshot
from experiments.interface_feasibility_20261017.test_probe import Probe, P

FIELDS=('operation_id','principal','holder','holder_kid','executor','destination')
FORGED={'operation_id':b64(b'A'*16),'principal':'attacker-principal','holder':'attacker-holder',
        'holder_kid':b64(b'K'*32),'executor':'attacker-executor','destination':'ind-release-bin'}

class ResolverCases(unittest.TestCase):
    setUp=Probe.setUp
    auth=Probe.auth
    submit=Probe.submit
    signed=Probe.signed
    accept=Probe.accept

    def rejected(self,call,code=None):
        with self.assertRaises(ProtocolError) as cm:call()
        if code:self.assertEqual(cm.exception.code,code)
        return cm.exception.code

    def no_allocations(self):
        with self.run.store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM exp_proposal').fetchone()[0],0)
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_authoritative_sources_for_all_six_fields(self):
        row=self.submit();a=row['action']
        with self.run.store.db() as c:
            task=self.run.store.current(c,P,'TASK',prefix(P)+[row['task_id']])
            policy=self.run.store.current(c,P,'POLICY',prefix(P))
            holder_key=self.run.store.current(c,P,'KEY',[a['holder_kid']])
            allocated=c.execute('SELECT oid FROM exp_proposal WHERE request_key=?',(row['key'],)).fetchone()[0]
        tv,pv=task['record']['value'],policy['record']['value']
        self.assertEqual(len(raw(a['operation_id'],16)),16)
        self.assertEqual(a['operation_id'],allocated)
        self.assertEqual(a['principal'],tv['principal'])
        self.assertEqual(a['holder'],tv['holder'])
        self.assertEqual(a['holder'],holder_key['record']['value']['subject'])
        self.assertEqual(a['holder_kid'],tv['holder_kid'])
        self.assertEqual(a['holder_kid'],self.run.store.actors[P]['H'].kid)
        self.assertEqual(a['executor'],tv['executor'])
        self.assertEqual(a['executor'],pv['executor'])
        self.assertEqual(a['executor'],self.run.store.actors[P]['X'].name)
        self.assertEqual(a['destination'],tv['route_destinations']['inspect'])
        self.assertEqual(a['destination'],pv['route_destinations']['inspect'])
        self.assertEqual(a['destination'],self.run.tools[P]['certificate']['claim']['record']['value']['destination'])
        self.assertEqual(set(a),{'scope','operation_id','principal','holder','holder_kid','executor','tool','tool_version','destination','payload'})
        self.run.store.schemas[P].validate(a,'Action')
        self.notes={'six_field_sources':row['sources'],'authority_model':'C-authenticated Task/Policy and roster; W-controlled map/tool trust, not Agent assertions'}

    def task_mismatch(self,field):
        with self.run.store.db() as c:
            record=self.run.store.current(c,P,'TASK',prefix(P)+[self.adapter.task_id])['record']
        if field=='destination':record['value']['route_destinations']['inspect']='ind-release-bin'
        else:record['value'][field]=FORGED[field]
        self.run.base.publish(P,'TASK',prefix(P)+[self.adapter.task_id],record)
        code=self.rejected(self.submit)
        self.no_allocations()
        self.notes={'authenticated_task_mismatch':field,'rejection':code}

    def test_signed_task_cannot_substitute_holder(self):self.task_mismatch('holder')
    def test_signed_task_cannot_substitute_holder_kid(self):self.task_mismatch('holder_kid')
    def test_signed_task_cannot_substitute_executor(self):self.task_mismatch('executor')
    def test_signed_task_cannot_override_policy_destination(self):
        with self.run.store.db() as c:
            record=self.run.store.current(c,P,'TASK',prefix(P)+[self.adapter.task_id])['record']
        record['value']['route_destinations']['inspect']='ind-release-bin'
        code=self.rejected(lambda:self.run.base.publish(P,'TASK',prefix(P)+[self.adapter.task_id],record),
                           'UPSTREAM_SCHEMA_REJECT:Record_IND_TASK:value.route_destinations.inspect')
        self.no_allocations()
        self.notes={'field':'destination','rejection':code,'boundary':'C publication/original schema'}

    def test_executor_destination_grant_narrowing_rejects_before_allocation(self):
        who=self.run.store.actors[P]['X'];key=prefix(P)+[who.name,'EXECUTOR']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'ROLE',key)['record']
        record['value']['epoch']='2';record['value']['destination_set']=['ind-release-bin']
        self.run.base.publish(P,'ROLE',key,record)
        self.rejected(self.submit,'NO_ROLE');self.no_allocations()

    def test_holder_key_purpose_narrowing_rejects_before_allocation(self):
        # Publish a legitimate current KEY revision with IssueRequest withdrawn.
        from competition.support.enrollment import EnrollmentLab
        from competition.support.wire import digest
        h=self.run.actors[P]['H']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'KEY',[h.kid])['record']
        v=record['value'];v['epoch']='2';v['purposes'].remove('IssueRequest')
        tup={'scope':self.run.operations[P]['action']['scope'],
             'subject':h.name,'public_key':b64(h.pub),'kid':h.kid,'purposes':v['purposes'],
             'key_not_before':v['iat'],'key_not_after':v['exp'],'root_generation':v['root_generation']}
        pending={'tuple':tup,'enrollment_id':b64(os.urandom(16)),'nonce':b64(os.urandom(32))}
        import time
        now=int(time.time());pop=EnrollmentLab.possession(h,pending,iat=now,exp=now+60)
        v['enrollment_ref']=digest(['COMP-APP-POP-v1',pop])
        self.run.base.publish(P,'KEY',[h.kid],record,enrollment=pop)
        self.rejected(self.submit,'NO_ROLE');self.no_allocations()

    def test_proposal_is_not_approval_or_any_participant_signature(self):
        with self.run.store.db() as c:
            before=(c.execute('SELECT count(*) FROM a_sign_call').fetchone()[0],c.execute('SELECT count(*) FROM a_publication').fetchone()[0])
        row=self.submit()
        with self.run.store.db() as c:
            after=(c.execute('SELECT count(*) FROM a_sign_call').fetchone()[0],c.execute('SELECT count(*) FROM a_publication').fetchone()[0])
        self.assertEqual(before,after)
        self.assertFalse({'authorization','reviews','issue','permit','challenge','proof','acceptance'} & set(row))
        self.rejected(lambda:self.adapter.load(row['key']),'APPROVAL_PENDING')
        incomplete={'action':row['action'],'task_id':row['task_id'],'scene_key':row['scene_key']}
        self.rejected(lambda:self.run.w.prepare(P,incomplete,self.run.identity_proof(P,incomplete)))
        self.assertEqual(self.run.w.counts()['accepts'],0)
        self.notes={'signer_calls_before_after':[before[0],after[0]],'publication_before_after':[before[1],after[1]]}

    def test_forged_signer_calls_for_H_U_V_G_X_all_rejected(self):
        row,op=self.signed();broker=self.run.base.broker
        messages={'H':op['issue'],'U':op['authorization'],'V':op['reviews'][0],'G':op['permit'],'X':op['challenge']}
        outcomes=[];attacker=Ed25519PrivateKey.generate()
        for alias,message in messages.items():
            unsigned=copy.deepcopy(message);unsigned.pop('sig')
            self.rejected(lambda:broker.sign(P,alias,unsigned,op['action']),'SIGN_CALLER_REQUIRED')
            cl=broker.challenge(P,alias,unsigned,op['action'])
            fake={'claim':cl,'signature':b64(attacker.sign(canonical(['COMP-APP-SIGN-CALL-v1',cl])))}
            code=self.rejected(lambda:broker.sign(P,alias,unsigned,op['action'],caller_proof=fake),'BAD_SIGNATURE')
            if alias!='H':
                holder_proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['COMP-APP-SIGN-CALL-v1',cl])))}
                self.rejected(lambda:broker.sign(P,alias,unsigned,op['action'],caller_proof=holder_proof),'BAD_SIGNATURE')
            with self.run.store.db() as c:self.assertEqual(c.execute('SELECT used FROM a_sign_call WHERE nonce=?',(cl['nonce'],)).fetchone()[0],0)
            outcomes.append({'alias':alias,'rejection':code})
        self.notes={'forged_signer_calls':outcomes}

    def test_unapproved_frozen_op_still_cannot_execute(self):
        from experiments.interface_feasibility_20261017.lab import approve_in_trusted_lab
        row=self.submit();op=approve_in_trusted_lab(self.run,row)
        bad=copy.deepcopy(op);bad['authorization']={}
        # First freeze is immutable storage, not approval. No database reset or
        # replacing an existing frozen request is needed for this host-misuse case.
        self.rejected(lambda:self.adapter.load(row['key']),'APPROVAL_PENDING')
        self.adapter.freeze(row['key'],bad)
        loaded=self.adapter.load(row['key'])['op']
        code=self.rejected(lambda:self.run.w.prepare(P,loaded,self.run.identity_proof(P,loaded)))
        self.assertEqual(self.run.w.counts()['accepts'],0)
        self.notes={'trusted_storage_is_not_approval':True,'host_misuse_fixture':True,'rejection':code}

    def test_copy_mutation_cannot_change_persisted_action_or_request(self):
        row,op=self.signed();expected=copy.deepcopy(op)
        for field in FIELDS:row['action'][field]=FORGED[field];op['action'][field]=FORGED[field]
        self.assertEqual(self.adapter.load(row['key'])['op'],expected)
        self.assertEqual(self.submit()['action'],expected['action'])

    def test_guard_real_signatures_commit_and_once_execution_compatible(self):
        row,op=self.signed()
        guarded=self.run.base.service.guard(P,op,self.run.identity_proof(P,op))
        self.assertEqual(guarded['decision'],'T')
        for alias,message in [('H',op['issue']),('U',op['authorization']),('V',op['reviews'][0]),('G',op['permit']),('X',op['challenge'])]:
            strict_verify(self.run.store.actors[P][alias].pub,raw(message['sig'],64),canonical(['ZJJ-SIG-v1',message['protected'],message['body']]))
        self.assertEqual(op['ctx']['action_hash'],action_hash(P,row['action']))
        ticket,first=self.accept(op);oid=row['action']['operation_id']
        before=public_snapshot(self.run,P,oid)
        ticket2,second=self.accept(self.adapter.load(row['key'])['op'])
        after=public_snapshot(self.run,P,oid)
        self.assertEqual(ticket['request_ref'],ticket2['request_ref'])
        self.assertEqual(first['acceptance'],second['acceptance'])
        self.assertEqual(before['commit_ref'],after['commit_ref'])
        self.assertEqual(before['commit'],after['commit'])
        self.assertEqual(before['counts'],after['counts'])
        for _ in range(2):self.run.w.claim(P,oid,self.run.worker_proof(P,oid,'CLAIM'))
        response=self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        final=self.run.w.settle(P,oid,response,self.run.worker_proof(P,oid,'SETTLE'))
        again=self.run.w.settle(P,oid,response,self.run.worker_proof(P,oid,'SETTLE'))
        self.assertEqual(final['final_fact_id'],again['final_fact_id'])
        snap=public_snapshot(self.run,P,oid)
        self.assertEqual((snap['counts']['accepts'],snap['counts']['attempts'],snap['counts']['exec_invocations'],snap['counts']['settlements'],snap['effect_count']),(1,1,1,1,1))
        self.notes={'commit_ref_before_after':[before['commit_ref'],after['commit_ref']],'guard_decision':guarded['decision'],'request_refs':[ticket['request_ref'],ticket2['request_ref']]}

    def test_delegation_fields_and_bearer_claims_are_not_accepted(self):
        codes=[]
        for field in ('delegation_proof','DelegationProof','act_as','on_behalf_of','sign_as'):
            proposal={**self.proposal,field:{'principal':'principal','holder':'attacker'}}
            codes.append(self.rejected(lambda:self.submit(proposal),'PROPOSAL_FIELDS'))
        proof=self.auth();claim=proof['claim']
        proof['signature']=b64(Ed25519PrivateKey.generate().sign(canonical(['EXP-PROPOSAL-AUTH-v1',claim])))
        self.rejected(lambda:self.adapter.submit(self.proposal,proof),'BAD_SIGNATURE')
        self.no_allocations();self.notes={'delegation_status':'NOT_IMPLEMENTED','extra_field_rejections':codes}

# Each six-field mutation has its own fresh authenticated fixture and named result.
def external_case(field):
    def test(self):
        bad={**self.proposal,field:FORGED[field]}
        code=self.rejected(lambda:self.submit(bad),'PROPOSAL_FIELDS')
        self.no_allocations();self.notes={'field':field,'rejection':code,'boundary':'proposal'}
    return test

def signed_case(field):
    def test(self):
        row,op=self.signed();bad=copy.deepcopy(op);bad['action'][field]=FORGED[field]
        code=self.rejected(lambda:self.run.w.prepare(P,bad,self.run.identity_proof(P,bad)))
        self.assertEqual(self.run.w.counts()['accepts'],0)
        self.notes={'field':field,'rejection':code,'boundary':'signed_action'}
    return test

for field in FIELDS:
    setattr(ResolverCases,'test_external_override_'+field,external_case(field))
    setattr(ResolverCases,'test_signed_action_substitution_'+field,signed_case(field))

if __name__=='__main__':unittest.main()
