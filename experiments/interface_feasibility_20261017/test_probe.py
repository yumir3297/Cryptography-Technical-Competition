"""Isolated E1-E4 acceptance probes. No Agent-callable signing capability."""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from competition.profiles.w_seed import initialize
from competition.support.wire import ProtocolError, canonical, b64, raw, digest, action_hash
from competition.w_cases import lost_ack, unknown_query, public_snapshot, save_recovery_fixture, recover_fixture

P = 'IND-DEMO-1'

class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='zjj-probe-')
        self.addCleanup(self.tmp.cleanup)
        self.run = initialize(Path(self.tmp.name))
        self.addCleanup(self.run.close)
        try:
            self.mod = importlib.import_module('experiments.interface_feasibility_20261017.adapter')
        except ModuleNotFoundError:
            self.fail('Missing isolated trusted adapter')
        self.adapter = self.mod.TrustedAdapter(self.run.store, self.run.operations[P]['task_id'])
        self.proposal = {'request_id':'industrial-request-1','unit_id':'unit-a','route':'INSPECT'}

    def auth(self, proposal=None, task_id=None):
        claim = {'profile':P,'task_id':task_id or self.adapter.task_id,
                 'proposal':proposal or self.proposal,'iat':str(int(time.time())),
                 'exp':str(int(time.time())+60)}
        return {'claim':claim,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['EXP-PROPOSAL-AUTH-v1',claim])))}

    def submit(self, proposal=None):
        proposal = proposal or self.proposal
        return self.adapter.submit(proposal, self.auth(proposal))

    def signed(self):
        from experiments.interface_feasibility_20261017.lab import approve_in_trusted_lab
        row = self.submit()
        op = approve_in_trusted_lab(self.run,row)
        self.adapter.freeze(row['key'],op)
        return row,op

    def accept(self,op):
        ticket=self.run.w.prepare(P,op,self.run.identity_proof(P,op))
        return ticket,self.run.w.accept(P,ticket['ticket_id'],self.run.accept_proof(P,ticket['ticket_id']))

    def test_E1_sources_and_original_schema(self):
        row=self.submit(); a=row['action']
        self.assertEqual(set(a),{'scope','operation_id','principal','holder','holder_kid','executor','tool','tool_version','destination','payload'})
        self.assertEqual(len(raw(a['operation_id'],16)),16)
        self.assertEqual(a['principal'],'principal')
        self.assertEqual(a['holder'],self.run.store.actors[P]['H'].name)
        self.assertEqual(a['holder_kid'],self.run.store.actors[P]['H'].kid)
        self.assertEqual(a['executor'],self.run.store.actors[P]['X'].name)
        self.assertEqual((a['tool'],a['tool_version'],a['destination']),('line-sort-sim','1','ind-inspection-bay'))
        self.assertEqual(a['payload'],{'line_id':'demo-line-a','station_id':'demo-check-1','unit_id':'unit-a','batch_id':'batch-a','inspection_cycle':'1','phase':'INITIAL','route':'INSPECT'})
        self.run.store.schemas[P].validate(a,'Action')
        self.assertNotEqual(a['operation_id'],self.run.operations[P]['action']['operation_id'])

    def test_E1_malicious_fields_and_inputs_rejected_before_allocation(self):
        for field in ('operation_id','principal','holder','holder_kid','executor','destination','tool','scope','payload','sign','auto_approve'):
            bad={**self.proposal,field:'attacker'}
            with self.subTest(field=field),self.assertRaises(ProtocolError):self.submit(bad)
        for patch in ({'unit_id':'unit-b'},{'route':'RELEASE'},{'request_id':''},{'request_id':True},{'route':[]},{'unit_id':1}):
            with self.subTest(patch=patch),self.assertRaises(ProtocolError):self.submit({**self.proposal,**patch})
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM exp_proposal').fetchone()[0],0)

    def test_E1_authentication_and_task_binding(self):
        with self.assertRaises(ProtocolError):self.adapter.submit(self.proposal,None)
        proof=self.auth();proof['signature']=b64(bytes(64))
        with self.assertRaises(ProtocolError):self.adapter.submit(self.proposal,proof)
        with self.assertRaises(ProtocolError):self.adapter.submit(self.proposal,self.auth(task_id=b64(os.urandom(16))))

    def test_E1_revoked_holder_role_rejected(self):
        self.run.base.update_role(P,'H',False)
        with self.assertRaises(ProtocolError):self.submit()

    def test_E1_tampered_authenticated_task_rejected(self):
        with self.run.store.tx() as c:
            c.execute("UPDATE a_current SET record=replace(record,'principal','attacker') WHERE profile=? AND namespace='TASK'",(P,))
        with self.assertRaisesRegex(ProtocolError,'STATE_INTEGRITY'):self.submit()

    def test_E1_tool_configuration_required(self):
        with self.run.store.tx() as c:c.execute('DELETE FROM w_tool WHERE profile=?',(P,))
        with self.assertRaisesRegex(ProtocolError,'TOOL_TRUST_UNKNOWN'):self.submit()

    def test_E2_guard_hash_chain_and_E4_industrial_end_to_end(self):
        row,op=self.signed()
        self.assertEqual(op['basis']['value']['action_hash'],action_hash(P,row['action']))
        ticket,accepted=self.accept(op);oid=row['action']['operation_id']
        self.assertEqual(accepted['acceptance_state'],'COMMITTED')
        self.assertEqual(ticket['request_ref'],self.adapter.load(row['key'])['request_ref'])
        self.run.w.claim(P,oid,self.run.worker_proof(P,oid,'CLAIM'))
        response=self.run.w.execute_once(P,oid,self.run.worker_proof(P,oid,'EXECUTE'))
        self.assertEqual(response['record']['value']['outcome'],'SUCCEEDED')
        settled=self.run.w.settle(P,oid,response,self.run.worker_proof(P,oid,'SETTLE'))
        again=self.run.w.settle(P,oid,response,self.run.worker_proof(P,oid,'SETTLE'))
        self.assertEqual(settled['final_fact_id'],again['final_fact_id'])
        snap=public_snapshot(self.run,P,oid)
        self.assertEqual((snap['counts']['accepts'],snap['counts']['attempts'],snap['counts']['exec_invocations'],snap['counts']['settlements'],snap['effect_count']),(1,1,1,1,1))
        self.assertEqual(snap['tool']['effects']['industrial_routes'][0]['payload'],row['action']['payload'])
        self.assertEqual(self.submit()['action'],row['action'])

    def test_E2_missing_U_V_tampered_action_and_bad_signature_rejected(self):
        row,op=self.signed()
        variants=[]
        for field in ('authorization','permit','proof'):
            bad=copy.deepcopy(op);bad[field]=None;variants.append(bad)
        bad=copy.deepcopy(op);bad['reviews']=[];variants.append(bad)
        bad=copy.deepcopy(op);bad['action']['payload']['batch_id']='attacker';variants.append(bad)
        bad=copy.deepcopy(op);bad['permit']['sig']=b64(bytes(64));variants.append(bad)
        for i,bad in enumerate(variants):
            with self.subTest(variant=i),self.assertRaises(ProtocolError):
                self.run.w.prepare(P,bad,self.run.identity_proof(P,bad))
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_E3_retries_conflicts_and_concurrent_allocation(self):
        proofs=[self.auth() for _ in range(8)]
        with ThreadPoolExecutor(8) as pool:
            rows=list(pool.map(lambda proof:self.adapter.submit(self.proposal,proof),proofs))
        self.assertEqual(len({r['action']['operation_id'] for r in rows}),1)
        self.assertEqual(self.mod.TrustedAdapter(self.run.store,self.adapter.task_id).submit(self.proposal,self.auth()),rows[0])
        with self.assertRaisesRegex(ProtocolError,'REQUEST_CONFLICT'):
            self.submit({**self.proposal,'route':'QUARANTINE'})
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM exp_proposal').fetchone()[0],1)

    def test_E3_frozen_full_request_replay_and_resign_conflict(self):
        row,op=self.signed();ticket,accepted=self.accept(op)
        retry=self.adapter.load(row['key']);t2,a2=self.accept(retry['op'])
        self.assertEqual(ticket['request_ref'],t2['request_ref'])
        self.assertEqual(accepted['acceptance'],a2['acceptance'])
        changed=copy.deepcopy(op)
        signing=copy.copy(self.run.base);signing.operations={**self.run.operations,P:changed}
        signing.resign_chain(P,changed,keep_permit_deps=False)
        self.assertEqual(action_hash(P,op['action']),action_hash(P,changed['action']))
        self.notes={'original_request_ref':digest(['COMP-APP-CALL-v1',P,op]),'resigned_request_ref':digest(['COMP-APP-CALL-v1',P,changed]),'action_hash':action_hash(P,op['action']),'adapter_rejection':'FROZEN_REQUEST_CONFLICT','W_rejection':'ID_CONFLICT'}
        self.assertNotEqual(self.notes['original_request_ref'],self.notes['resigned_request_ref'])
        with self.assertRaisesRegex(ProtocolError,'FROZEN_REQUEST_CONFLICT'):self.adapter.freeze(row['key'],changed)
        with self.assertRaisesRegex(ProtocolError,'ID_CONFLICT'):
            self.run.w.prepare(P,changed,self.run.identity_proof(P,changed))
        self.assertEqual(self.run.w.counts()['accepts'],1)

    def test_E3_new_request_id_cannot_repeat_same_business_effect(self):
        row,op=self.signed()
        row2=self.submit({**self.proposal,'request_id':'request-2'})
        from experiments.interface_feasibility_20261017.lab import approve_in_trusted_lab
        op2=approve_in_trusted_lab(self.run,row2)
        ticket2=self.run.w.prepare(P,op2,self.run.identity_proof(P,op2))
        self.accept(op)
        with self.assertRaises(ProtocolError):self.run.w.accept(P,ticket2['ticket_id'],self.run.accept_proof(P,ticket2['ticket_id']))
        self.assertEqual(self.run.w.counts()['accepts'],1)

    def test_E3_real_process_exit_after_allocation_restores_same_id(self):
        meta=save_recovery_fixture(self.run)
        proof=self.auth()
        proc=subprocess.run([sys.executable,'-m','experiments.interface_feasibility_20261017.lab','allocate-crash',meta,self.adapter.task_id],input=json.dumps({'proposal':self.proposal,'auth':proof}),text=True,capture_output=True,timeout=30)
        self.assertEqual(proc.returncode,96,proc.stderr)
        self.notes={'child_exit_code':proc.returncode,'child_stderr':proc.stderr}
        row=self.submit()
        with self.run.store.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM exp_proposal').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT oid FROM exp_proposal').fetchone()[0],row['action']['operation_id'])

    def test_E3_E4_real_W_commit_crash_and_restart_from_frozen_request(self):
        row,op=self.signed();meta=save_recovery_fixture(self.run)
        ticket=self.run.w.prepare(P,op,self.run.identity_proof(P,op))
        proof=self.run.accept_proof(P,ticket['ticket_id'])
        proc=subprocess.run([sys.executable,'-m','competition.w_cases','crash-accept',meta,P,ticket['ticket_id']],input=json.dumps(proof),capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,97,proc.stderr)
        self.notes={'child_exit_code':proc.returncode,'child_stderr':proc.stderr}
        before=public_snapshot(self.run,P,row['action']['operation_id'])
        self.assertIsNone(before['operation']['receipt'])
        recovered=recover_fixture(meta)
        try:
            saved=self.mod.TrustedAdapter(recovered.store,self.adapter.task_id).load(row['key'])
            t=recovered.w.prepare(P,saved['op'],recovered.identity_proof(P,saved['op']))
            a=recovered.w.accept(P,t['ticket_id'],recovered.accept_proof(P,t['ticket_id']))
            self.assertEqual(t['request_ref'],ticket['request_ref'])
            self.assertEqual({k:a['acceptance'][k] for k in ('protected','body')},before['acceptance_core'])
            self.assertEqual(recovered.w.counts()['accepts'],1)
            oid=row['action']['operation_id']
            recovered.w.claim(P,oid,recovered.worker_proof(P,oid,'CLAIM'))
            response=recovered.w.execute_once(P,oid,recovered.worker_proof(P,oid,'EXECUTE'))
            recovered.w.settle(P,oid,response,recovered.worker_proof(P,oid,'SETTLE'))
            self.assertEqual(public_snapshot(recovered,P,oid)['effect_count'],1)
        finally:recovered.close()

    def test_E4_tool_commit_lost_ack_queries_same_fact(self):
        row,op=self.signed();self.run.operations[P]=op
        result=lost_ack(self.run,P)
        self.notes={'lost_ack_trace':result['lost_ack']['trace'],'query_trace':result['query']['trace'],'persisted_fact_id':result['persisted_fact_id'],'query_fact_id':result['query_fact_id']}
        self.assertEqual(result['lost_ack']['trace']['exit_code'],98)
        self.assertNotEqual(result['lost_ack']['trace']['pid'],result['query']['trace']['pid'])
        self.assertEqual(result['persisted_fact_id'],result['query_fact_id'])
        self.assertEqual(result['before_retry']['execution_sends_observed'],result['after_retry']['execution_sends_observed'])
        self.assertEqual((result['effect_count'],result['after_settlement']['settlements']),(1,1))

    def test_E4_unknown_tool_result_keeps_reservation_and_no_effect(self):
        row,op=self.signed();self.run.operations[P]=op
        result=unknown_query(self.run,P)
        self.notes={'before':result['before']['counts'],'after':result['after']['counts'],'settlement':result['settlement']}
        self.assertIsNone(result['query']['record'])
        self.assertEqual(result['before']['resources'],result['after']['resources'])
        self.assertEqual(result['before']['flights'],result['after']['flights'])
        self.assertEqual((result['after']['effect_count'],result['after']['counts']['settlements']),(0,0))

    def test_E1_revoked_holder_key_rejected(self):
        kid=self.run.store.actors[P]['H'].kid
        with self.run.store.db() as c:record=self.run.store.current(c,P,'KEY',[kid])['record']
        record['value']['epoch']='2'
        self.run.base.publish(P,'KEY',[kid],record,active=False)
        with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.submit()

    def test_E1_revoked_executor_role_rejected(self):
        self.run.base.update_role(P,'X',False)
        with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.submit()

    def test_E1_expired_auth_and_substituted_proposal_rejected(self):
        proof=self.auth();proof['claim']['exp']='1';proof['claim']['iat']='0'
        proof['signature']=b64(self.run.actors[P]['H'].key.sign(canonical(['EXP-PROPOSAL-AUTH-v1',proof['claim']])))
        with self.assertRaises(ProtocolError):self.adapter.submit(self.proposal,proof)
        with self.assertRaisesRegex(ProtocolError,'AUTH_BINDING'):
            self.adapter.submit({**self.proposal,'request_id':'substituted'},self.auth())

    def test_E3_real_process_exit_after_full_op_persist_restores_exact_request(self):
        from experiments.interface_feasibility_20261017.lab import approve_in_trusted_lab
        row=self.submit();op=approve_in_trusted_lab(self.run,row)
        with self.assertRaisesRegex(ProtocolError,'APPROVAL_PENDING'):self.adapter.load(row['key'])
        meta=save_recovery_fixture(self.run)
        proc=subprocess.run([sys.executable,'-m','experiments.interface_feasibility_20261017.lab','freeze-crash',meta,self.adapter.task_id],input=json.dumps({'key':row['key'],'op':op}),capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,95,proc.stderr)
        self.notes={'child_exit_code':proc.returncode,'child_stderr':proc.stderr}
        restored=self.adapter.load(row['key'])
        self.assertEqual(restored['op'],op)
        ticket,_=self.accept(restored['op'])
        self.assertEqual(ticket['request_ref'],restored['request_ref'])

    def test_E1_reader_revocation_precedes_evidence_access(self):
        from competition.core.trusted_state import prefix
        who=self.run.store.actors[P]['H'];key=prefix(P)+[who.name,'READER']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'ROLE',key)['record']
        record['value']['epoch']='2'
        self.run.base.publish(P,'ROLE',key,record,active=False)
        reads=[];original=self.run.store.current
        def observed(c,profile,ns,key):
            reads.append(ns)
            return original(c,profile,ns,key)
        self.run.store.current=observed
        with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.submit()
        self.assertNotIn('EVIDENCE',reads)

    def test_E1_cached_retry_rechecks_current_policy_read_acl(self):
        from competition.core.trusted_state import prefix
        self.submit()
        with self.run.store.db() as c:record=self.run.store.current(c,P,'POLICY',prefix(P))['record']
        record['value']['readers'].remove(self.run.store.actors[P]['H'].name)
        self.run.base.publish(P,'POLICY',prefix(P),record)
        with self.assertRaisesRegex(ProtocolError,'NO_ROLE'):self.submit()

    def test_E1_cached_retry_rechecks_reader_action_constraints(self):
        from competition.core.trusted_state import prefix
        self.submit();who=self.run.store.actors[P]['H'];key=prefix(P)+[who.name,'READER']
        with self.run.store.db() as c:record=self.run.store.current(c,P,'ROLE',key)['record']
        record['value']['epoch']='2';record['value']['constraints']['unit_set']=['unit-b']
        self.run.base.publish(P,'ROLE',key,record)
        with self.assertRaisesRegex(ProtocolError,'NO_ROLE'):self.submit()

if __name__=='__main__':unittest.main()
