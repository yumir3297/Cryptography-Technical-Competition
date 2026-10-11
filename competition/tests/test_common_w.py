"""Actual shared W transactions and independent simulator recovery."""
import importlib
import tempfile
import unittest
from pathlib import Path

class SharedWTests(unittest.TestCase):
    def setUp(self):
        try:self.module=importlib.import_module('competition.profiles.w_seed')
        except ModuleNotFoundError:self.fail('Missing common W runtime/transaction path')
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.run=self.module.initialize(Path(self.folder.name));self.addCleanup(self.run.close)

    def accept(self,p,op=None):
        op=op or self.run.operations[p]
        ticket=self.run.w.prepare(p,op,self.run.identity_proof(p,op))
        return self.run.w.accept(p,ticket['ticket_id'],self.run.accept_proof(p,ticket['ticket_id']))

    def test_three_profiles_share_real_acceptance_and_pending_outbox_transaction(self):
        for p in self.run.operations:
            result=self.accept(p)
            self.assertEqual(result['acceptance_state'],'COMMITTED')
            self.assertEqual(result['dispatch_state'],'PENDING')
            self.assertIsNotNone(result['acceptance'])
        counts=self.run.w.counts()
        self.assertEqual((counts['accepts'],counts['outbox'],counts['attempts'],counts['exec_invocations'],counts['settlements']),(3,3,0,0,0))

    def test_full_chain_exec_query_and_once_settlement_three_profiles(self):
        for p in self.run.operations:
            self.accept(p);oid=self.run.operations[p]['action']['operation_id']
            d=self.run.w.claim(p,oid,self.run.worker_proof(p,oid,'CLAIM'))
            response=self.run.w.execute_once(p,oid,self.run.worker_proof(p,oid,'EXECUTE'))
            self.assertEqual(response['record']['value']['outcome'],'SUCCEEDED')
            settled=self.run.w.settle(p,oid,response,self.run.worker_proof(p,oid,'SETTLE'))
            again=self.run.w.settle(p,oid,response,self.run.worker_proof(p,oid,'SETTLE'))
            self.assertEqual(settled['final_fact_id'],again['final_fact_id'])
            self.assertEqual(d['attempt_id'],response['record']['value']['dispatch_attempt'])
        counts=self.run.w.counts();self.assertEqual((counts['attempts'],counts['exec_invocations'],counts['confirmed_simulated_effects'],counts['settlements']),(3,3,3,3))

    def test_unsigned_worker_cannot_claim_committed_operation(self):
        from research.reference_executor.wire import ProtocolError
        p='PAY-1';self.accept(p);oid=self.run.operations[p]['action']['operation_id']
        with self.assertRaises(ProtocolError):self.run.w.claim(p,oid,None)
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_ownership_loss_blocks_claim_and_cancel_without_releasing_others(self):
        from research.reference_executor.wire import ProtocolError
        p='IND-DEMO-1';self.accept(p);oid=self.run.operations[p]['action']['operation_id']
        with self.run.store.tx() as c:c.execute('DELETE FROM w_flight WHERE profile=? AND oid=?',(p,oid))
        self.run.base.update_role(p,'G',False)
        for method,purpose in [(self.run.w.claim,'CLAIM'),(self.run.w.cancel,'CANCEL')]:
            with self.assertRaises(ProtocolError) as error:method(p,oid,self.run.worker_proof(p,oid,purpose))
            self.assertEqual(error.exception.code,'FLIGHT_OWNERSHIP')
        with self.run.store.db() as c:self.assertEqual(c.execute('SELECT SUM(reserved) FROM w_resource').fetchone()[0],1)
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_status_and_audit_are_current_authenticated_reads_with_zero_execution(self):
        from research.reference_executor.wire import ProtocolError
        for p in self.run.operations:
            self.accept(p);oid=self.run.operations[p]['action']['operation_id'];before=self.run.w.counts()
            self.assertIsNone(self.run.w.status(p,oid,self.run.read_proof(p,oid))['attempt_id'])
            self.assertEqual(self.run.w.audit(p,oid,self.run.read_proof(p,oid,'AUDIT'))['commit']['value']['action'],self.run.operations[p]['action'])
            self.assertEqual(self.run.w.counts(),before)
            self.run.base.update_role(p,'H',False)
            with self.assertRaises(ProtocolError):self.run.w.status(p,oid,None)

    def test_delayed_final_acceptance_guard_cannot_publish_a_stale_time_sample(self):
        import time
        from research.reference_executor.wire import ProtocolError
        p='PAY-1';op=self.run.operations[p];ticket=self.run.w.prepare(p,op,self.run.identity_proof(p,op))
        proof=self.run.accept_proof(p,ticket['ticket_id']);verify=self.run.w.guard.verify;calls=[]
        def delayed(*args):
            result=verify(*args);calls.append(True)
            if len(calls)==2:time.sleep(2.01)
            return result
        self.run.w.guard.verify=delayed
        with self.assertRaises(ProtocolError) as error:self.run.w.accept(p,ticket['ticket_id'],proof)
        self.assertEqual(error.exception.code,'CLOCK_UNKNOWN');self.assertEqual(self.run.w.counts()['accepts'],0)
