"""Application proposal/resolver/outbox against real public state, broker and W."""
import copy
import importlib
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from competition.profiles.w_seed import initialize
from competition.support.wire import ProtocolError,b64,canonical,digest,action_hash
from competition.core.trusted_state import prefix
from competition.tests.resolver_fixtures import approve_in_lab,P
from competition.w_cases import public_snapshot,lost_ack,unknown_query,save_recovery_fixture,recover_fixture

FIELDS=('operation_id','principal','holder','holder_kid','executor','destination')

class ActionResolverTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module=importlib.import_module('competition.application.trusted_action_resolver')
            self.workflow_module=importlib.import_module('competition.application.operation_orchestrator')
        except ModuleNotFoundError:self.fail('Missing application resolver implementation')
        self.tmp=tempfile.TemporaryDirectory(prefix='zjj-app-')
        self.addCleanup(self.tmp.cleanup)
        self.run=initialize(Path(self.tmp.name));self.addCleanup(self.run.close)
        self.resolver=self.module.TrustedActionResolver(self.run.store,self.run.operations[P]['task_id'])
        self.workflow=self.workflow_module.OperationOrchestrator(self.run.w,self.resolver.requests)
        self.proposal={'request_id':'app-request-1','unit_id':'unit-a','route':'INSPECT'}

    def auth(self,proposal=None,signer='H'):
        claim={'profile':P,'task_id':self.resolver.task_id,'proposal':proposal or self.proposal,
               'iat':str(int(time.time())),'exp':str(int(time.time())+60)}
        return {'claim':claim,'signature':b64(self.run.actors[P][signer].key.sign(canonical([self.module.AUTH_DOMAIN,claim])))}

    def resolve(self,proposal=None):
        proposal=proposal or self.proposal
        return self.resolver.resolve(proposal,self.auth(proposal))

    def signed(self):
        row=self.resolve();return row,approve_in_lab(self.run,row)

    def prepare(self,row,op):
        return self.workflow.prepare_approved(row['key'],op,self.run.identity_proof(P,op))

    def accept(self,ticket):
        tid=ticket['ticket_id']
        return self.workflow.accept(tid,self.run.accept_proof(P,tid))

    def reject(self,call,code=None):
        with self.assertRaises(ProtocolError) as cm:call()
        if code:self.assertEqual(cm.exception.code,code)
        return cm.exception.code

    def test_strict_proposal_does_not_allocate_or_sign(self):
        with self.run.store.db() as c:before=c.execute('SELECT count(*) FROM a_sign_call').fetchone()[0]
        for field in FIELDS+('delegation_proof','sign_as','auto_approve'):
            bad={**self.proposal,field:'attacker'}
            self.reject(lambda:self.resolve(bad),'PROPOSAL_FIELDS')
        for patch in ({'request_id':''},{'request_id':True},{'unit_id':'unit-b'},{'route':[]}):
            bad={**self.proposal,**patch};self.reject(lambda:self.resolve(bad))
        with self.run.store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM app_request').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM a_sign_call').fetchone()[0],before)

    def test_authentication_binding_and_unsupported_profile(self):
        self.reject(lambda:self.resolver.resolve(self.proposal,None),'IDENTITY_REQUIRED')
        self.reject(lambda:self.resolver.resolve(self.proposal,self.auth(signer='U')),'BAD_SIGNATURE')
        proof=self.auth();proof['claim']['task_id']=b64(b'T'*16)
        self.reject(lambda:self.resolver.resolve(self.proposal,proof),'AUTH_BINDING')
        self.reject(lambda:self.module.TrustedActionResolver(self.run.store,self.resolver.task_id,profile='PAY-1'),'PROFILE')

    def test_canonical_bytes_and_source_bound_ten_field_action(self):
        row=self.resolver.resolve(canonical(self.proposal),self.auth());a=row['action']
        self.assertEqual(set(a),{'scope','operation_id','principal','holder','holder_kid','executor','tool','tool_version','destination','payload'})
        self.assertEqual((a['principal'],a['holder'],a['holder_kid'],a['executor']),
            ('principal',self.run.store.actors[P]['H'].name,self.run.store.actors[P]['H'].kid,self.run.store.actors[P]['X'].name))
        self.assertEqual((a['tool'],a['tool_version'],a['destination']),('line-sort-sim','1','ind-inspection-bay'))
        self.run.store.schemas[P].validate(a,'Action')
        self.assertEqual(row['approval_request']['ctx']['action_hash'],action_hash(P,a))
        self.assertFalse({'reviews','authorization','permit','proof'} & set(row['approval_request']))
        self.reject(lambda:self.resolver.resolve(b' '+canonical(self.proposal),self.auth()))
        self.reject(lambda:self.resolver.resolve(b'x'*65537,self.auth()),'CANDIDATE_LIMIT')

    def test_cached_retry_checks_policy_acl(self):
        self.resolve()
        with self.run.store.db() as c:record=self.run.store.current(c,P,'POLICY',prefix(P))['record']
        record['value']['readers'].remove(self.run.store.actors[P]['H'].name)
        self.run.base.publish(P,'POLICY',prefix(P),record)
        self.reject(self.resolve,'NO_ROLE')

    def test_reader_revocation_precedes_evidence_read(self):
        who=self.run.store.actors[P]['H'];key=prefix(P)+[who.name,'READER']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'ROLE',key)['record']
        record['value']['epoch']='2';self.run.base.publish(P,'ROLE',key,record,active=False)
        reads=[];original=self.run.store.current
        def observed(c,p,ns,key):reads.append(ns);return original(c,p,ns,key)
        self.run.store.current=observed
        self.reject(self.resolve,'REVOKED');self.assertNotIn('EVIDENCE',reads)

    def test_revoked_executor_and_task_holder_mismatch(self):
        self.run.base.update_role(P,'X',False)
        self.reject(self.resolve,'REVOKED')
        self.run.base.update_role(P,'X',True)
        with self.run.store.db() as c:record=self.run.store.current(c,P,'TASK',prefix(P)+[self.resolver.task_id])['record']
        record['value']['holder']='attacker'
        self.run.base.publish(P,'TASK',prefix(P)+[self.resolver.task_id],record)
        self.reject(self.resolve,'WRONG_HOLDER')

    def test_concurrent_mapping_and_request_content_conflict(self):
        proofs=[self.auth() for _ in range(8)]
        with ThreadPoolExecutor(8) as pool:rows=list(pool.map(lambda p:self.resolver.resolve(self.proposal,p),proofs))
        self.assertEqual(len({x['action']['operation_id'] for x in rows}),1)
        self.reject(lambda:self.resolve({**self.proposal,'route':'QUARANTINE'}),'REQUEST_CONFLICT')
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM app_request').fetchone()[0],1)

    def test_mapping_survives_new_resolver_and_copy_mutation(self):
        row=self.resolve();original=copy.deepcopy(row)
        row['action']['principal']='attacker';row['approval_request']['action']['principal']='attacker'
        resolver=self.module.TrustedActionResolver(self.run.store,self.resolver.task_id)
        self.assertEqual(resolver.resolve(self.proposal,self.auth()),original)

    def test_bad_approval_cannot_poison_first_freeze(self):
        row,op=self.signed();bad=copy.deepcopy(op);bad['authorization']={}
        self.reject(lambda:self.prepare(row,bad))
        self.reject(lambda:self.resolver.requests.load(row['key']),'APPROVAL_PENDING')
        ticket=self.prepare(row,op);self.assertEqual(self.accept(ticket)['acceptance_state'],'COMMITTED')

    def test_six_field_changes_and_missing_review_cannot_freeze(self):
        row,op=self.signed()
        for field in FIELDS:
            bad=copy.deepcopy(op);bad['action'][field]=b64(b'A'*16) if field=='operation_id' else 'attacker'
            self.reject(lambda:self.prepare(row,bad),'FROZEN_ACTION_CONFLICT')
        bad=copy.deepcopy(op);bad['reviews']=[]
        self.reject(lambda:self.prepare(row,bad),'REVIEW_REQUIRED')
        self.reject(lambda:self.resolver.requests.load(row['key']),'APPROVAL_PENDING')
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_same_action_resign_cannot_replace_frozen_request(self):
        row,op=self.signed();ticket=self.prepare(row,op);self.accept(ticket)
        changed=copy.deepcopy(op);signing=copy.copy(self.run.base);signing.operations={**self.run.operations,P:changed}
        signing.resign_chain(P,changed,keep_permit_deps=False)
        self.assertEqual(action_hash(P,op['action']),action_hash(P,changed['action']))
        self.assertNotEqual(digest(['COMP-APP-CALL-v1',P,op]),digest(['COMP-APP-CALL-v1',P,changed]))
        self.reject(lambda:self.prepare(row,changed),'FROZEN_REQUEST_CONFLICT')
        self.assertEqual(self.resolver.requests.load(row['key'])['op'],op)

    def test_full_chain_retry_commit_and_once_effect(self):
        row,op=self.signed();ticket=self.prepare(row,op);first=self.accept(ticket);oid=row['action']['operation_id']
        before=public_snapshot(self.run,P,oid)
        retry=self.workflow.prepare_saved(row['key'],self.run.identity_proof(P,op));second=self.accept(retry)
        self.assertEqual(ticket['request_ref'],retry['request_ref']);self.assertEqual(first['acceptance'],second['acceptance'])
        self.assertEqual(before['commit'],public_snapshot(self.run,P,oid)['commit'])
        for _ in range(2):self.run.w.claim(P,oid,self.run.worker_proof(P,oid,'CLAIM'))
        result=self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        a=self.run.w.settle(P,oid,result,self.run.worker_proof(P,oid,'SETTLE'))
        b=self.run.w.settle(P,oid,result,self.run.worker_proof(P,oid,'SETTLE'))
        self.assertEqual(a['final_fact_id'],b['final_fact_id'])
        snap=public_snapshot(self.run,P,oid)
        self.assertEqual((snap['counts']['accepts'],snap['counts']['attempts'],snap['counts']['exec_invocations'],snap['counts']['settlements'],snap['effect_count']),(1,1,1,1,1))
        self.assertEqual(snap['tool']['effects']['industrial_routes'][0]['payload'],row['action']['payload'])

    def test_tool_lost_ack_preserves_core_semantics(self):
        row,op=self.signed();self.workflow.freeze_approved(row['key'],op);self.run.operations[P]=op
        result=lost_ack(self.run,P)
        self.assertEqual(result['lost_ack']['trace']['exit_code'],98)
        self.assertEqual(result['persisted_fact_id'],result['query_fact_id'])
        self.assertEqual(result['effect_count'],1)
        self.assertEqual(result['before_retry']['execution_sends_observed'],result['after_retry']['execution_sends_observed'])

    def test_new_request_id_cannot_bypass_business_intent_deduplication(self):
        row,op=self.signed()
        second=self.resolve({**self.proposal,'request_id':'request-2'});op2=approve_in_lab(self.run,second)
        ticket2=self.prepare(second,op2)
        self.accept(self.prepare(row,op))
        self.reject(lambda:self.accept(ticket2));self.assertEqual(self.run.w.counts()['accepts'],1)

    def test_resume_existing_ledgers_and_frozen_request_after_restart(self):
        row,op=self.signed();self.prepare(row,op)
        metadata=save_recovery_fixture(self.run);recovered=recover_fixture(metadata)
        try:
            resolver=self.module.TrustedActionResolver(recovered.store,self.resolver.task_id)
            workflow=self.workflow_module.OperationOrchestrator(recovered.w,resolver.requests)
            saved=resolver.requests.load(row['key'])
            self.assertEqual(saved['op'],op)
            ticket=workflow.prepare_saved(row['key'],recovered.identity_proof(P,op))
            accepted=workflow.accept(ticket['ticket_id'],recovered.accept_proof(P,ticket['ticket_id']))
            self.assertEqual(accepted['acceptance_state'],'COMMITTED')
            self.assertEqual(ticket['request_ref'],saved['request_ref'])
        finally:recovered.close()

    def test_cached_retry_checks_reader_action_scope(self):
        self.resolve();who=self.run.store.actors[P]['H'];key=prefix(P)+[who.name,'READER']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'ROLE',key)['record']
        record['value']['epoch']='2';record['value']['constraints']['unit_set']=['unit-b']
        self.run.base.publish(P,'ROLE',key,record)
        self.reject(self.resolve,'NO_ROLE')

    def test_allocator_retries_collision_and_fails_closed_on_exhaustion(self):
        from unittest.mock import patch
        from competition.support.wire import raw
        first=self.resolve();blocked=raw(first['action']['operation_id'],16)
        proposal={**self.proposal,'request_id':'request-2'};proof=self.auth(proposal)
        with patch('competition.application.request_store.os.urandom',side_effect=[blocked,b'B'*16]):
            second=self.resolver.resolve(proposal,proof)
        self.assertEqual(second['action']['operation_id'],b64(b'B'*16))
        third={**self.proposal,'request_id':'request-3'};proof=self.auth(third)
        with patch('competition.application.request_store.os.urandom',return_value=blocked):
            self.reject(lambda:self.resolver.resolve(third,proof),'ID_ALLOCATION_FAILED')
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM app_request').fetchone()[0],2)

    def test_unknown_result_keeps_resources_without_effect(self):
        row,op=self.signed();self.workflow.freeze_approved(row['key'],op);self.run.operations[P]=op
        result=unknown_query(self.run,P)
        self.assertIsNone(result['query']['record'])
        self.assertEqual(result['before']['resources'],result['after']['resources'])
        self.assertEqual(result['before']['flights'],result['after']['flights'])
        self.assertEqual((result['after']['effect_count'],result['after']['counts']['settlements']),(0,0))

    def test_W_commit_crash_recovers_same_request_and_receipt(self):
        import subprocess,sys
        row,op=self.signed();ticket=self.prepare(row,op)
        meta=save_recovery_fixture(self.run)
        proc=subprocess.run([sys.executable,'-m','competition.w_cases','crash-accept',meta,P,ticket['ticket_id']],
            input=json.dumps(self.run.accept_proof(P,ticket['ticket_id'])),capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,97,proc.stderr)
        oid=row['action']['operation_id'];before=public_snapshot(self.run,P,oid)
        self.assertIsNone(before['operation']['receipt'])
        recovered=recover_fixture(meta)
        try:
            resolver=self.module.TrustedActionResolver(recovered.store,self.resolver.task_id)
            workflow=self.workflow_module.OperationOrchestrator(recovered.w,resolver.requests)
            t=workflow.prepare_saved(row['key'],recovered.identity_proof(P,op))
            a=workflow.accept(t['ticket_id'],recovered.accept_proof(P,t['ticket_id']))
            self.assertEqual(t['request_ref'],ticket['request_ref'])
            self.assertEqual({k:a['acceptance'][k] for k in ('protected','body')},before['acceptance_core'])
            self.assertEqual(public_snapshot(recovered,P,oid)['commit'],before['commit'])
            self.assertEqual(recovered.w.counts()['accepts'],1)
        finally:recovered.close()

    def test_short_valid_package_bounds_assessment_lifetime(self):
        from competition.support.wire import rec_ref
        with self.run.store.db() as c:
            package=self.run.store.current(c,P,'PACKAGE',prefix(P))['record']
            policy=self.run.store.current(c,P,'POLICY',prefix(P))['record']
            task=self.run.store.current(c,P,'TASK',prefix(P)+[self.resolver.task_id])['record']
        expires=str(int(time.time())+30)
        package['value']['exp']=expires
        package_ref=self.run.base.publish(P,'PACKAGE',prefix(P),package)
        policy['value']['decision_package_ref']=package_ref
        policy_ref=self.run.base.publish(P,'POLICY',prefix(P),policy)
        task['value']['policy_ref']=policy_ref
        self.run.base.publish(P,'TASK',prefix(P)+[self.resolver.task_id],task)
        row=self.resolve()
        self.assertEqual(row['approval_request']['assessment']['value']['exp'],expires)
        op=approve_in_lab(self.run,row)
        self.assertEqual(self.accept(self.prepare(row,op))['acceptance_state'],'COMMITTED')

    def test_delayed_first_freeze_does_not_persist_stale_event(self):
        row,op=self.signed();original=self.run.w.guard.verify
        def delayed(*args):
            result=original(*args);time.sleep(2.01);return result
        self.run.w.guard.verify=delayed
        self.reject(lambda:self.workflow.freeze_approved(row['key'],op),'CLOCK_UNKNOWN')
        self.reject(lambda:self.resolver.requests.load(row['key']),'APPROVAL_PENDING')
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_new_requests_use_W_current_state_while_cached_request_stays_frozen(self):
        row,op=self.signed();self.accept(self.prepare(row,op))
        self.assertEqual(self.resolve(),row)
        self.reject(lambda:self.resolve({**self.proposal,'request_id':'after-commit'}),'STALE')
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM app_request').fetchone()[0],1)
        retry=self.workflow.prepare_saved(row['key'],self.run.identity_proof(P,op))
        self.assertEqual(self.accept(retry)['acceptance_state'],'COMMITTED')
        self.assertEqual(self.run.w.counts()['accepts'],1)

if __name__=='__main__':unittest.main()
