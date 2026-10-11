"""Security findings reproduced before the final fix pass."""
import copy
import tempfile
import unittest
from pathlib import Path
from research.reference_executor.wire import canonical,b64,digest
from competition.profiles.w_seed import initialize
from competition import w_cases

class FinalRegressionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.run=initialize(Path(self.folder.name));self.addCleanup(self.run.close)
    def test_stale_checkpoint_cannot_hide_a_trusted_immutable_fact_contradiction(self):
        p='PAY-1';oid,_=w_cases.accept_operation(self.run,p)
        self.run.w.claim(p,oid,self.run.worker_proof(p,oid,'CLAIM'))
        response=self.run.w.execute_once(p,oid,self.run.worker_proof(p,oid,'EXECUTE'))
        advanced=copy.deepcopy(response);advanced['checkpoint']['claim']['high_water']='2'
        advanced['checkpoint']['claim']['ledger_head']=digest(['CONTROLLED-FUTURE-HEAD'])
        advanced=w_cases._test_sign_final(self.run,p,advanced)
        self.run.w.settle(p,oid,advanced,self.run.worker_proof(p,oid,'SETTLE'))
        contradiction=copy.deepcopy(response);contradiction['record']['value']['effect_id']='conflicting-effect'
        contradiction=w_cases._test_sign_final(self.run,p,contradiction)
        result=self.run.w.settle(p,oid,contradiction,self.run.worker_proof(p,oid,'SETTLE'))
        self.assertEqual(result['state'],'HALTED');self.assertEqual(self.run.w.counts()['halts'],1)
        self.assertEqual(self.run.w.counts()['settlements'],1)

    def test_final_claim_must_check_current_worker_expiry(self):
        import time
        from research.reference_executor.wire import ProtocolError
        p='PAY-1';oid,_=w_cases.accept_operation(self.run,p)
        certificate=copy.deepcopy(self.run.worker_certificate);expiry=int(time.time())+2
        certificate['claim']['exp']=str(expiry)
        certificate['signature']=b64(self.run.root.sign(canonical(['COMP-W-WORKER-GRANT-v1',certificate['claim']])))
        self.run.w.worker_certificate=certificate
        proof=self.run.worker_proof(p,oid,'CLAIM');original=self.run.w._claim_checks;calls=[]
        def delay(*args):
            result=original(*args);calls.append(True)
            if len(calls)==2:
                while time.time()<expiry+0.015:time.sleep(0.01)
            return result
        self.run.w._claim_checks=delay
        with self.assertRaises(ProtocolError):self.run.w.claim(p,oid,proof)
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_unknown_settle_preserves_durable_halted_state(self):
        p='PAY-1';result=w_cases.bad_and_conflicting_final(self.run,p);oid=result['operation_id']
        returned=self.run.w.settle(p,oid,{'record':None},self.run.worker_proof(p,oid,'SETTLE'))
        self.assertEqual(returned['state'],'HALTED')

    def test_process_start_alone_does_not_prove_execution_packet_was_sent(self):
        p='PAY-1';oid,_=w_cases.accept_operation(self.run,p)
        self.run.w.claim(p,oid,self.run.worker_proof(p,oid,'CLAIM'))
        class UnsentFixture:
            def execute(self,packet):return {'state':'UNKNOWN','record':None,'trace':{'started':True,'input_submitted':False}}
        self.run.w.tool_gateways[p]=UnsentFixture()
        self.run.w.execute_once(p,oid,self.run.worker_proof(p,oid,'EXECUTE'))
        counts=self.run.w.counts();self.assertEqual(counts['execution_sends_observed'],0)
        self.assertEqual(counts['execution_sends_unobserved_upper_bound'],1)
