"""Integration-shaped tests for minimal C-goal floor + crypto evidence links."""
import copy
import tempfile
import unittest
from pathlib import Path
from goal_commit import (GoalCommitHarness,Reject,fixture_key,issue_goal,issue_final,
                         get_commit_ref,check_sig,GOAL_DOM,RECEIPT_DOM,COMMIT_DOM,digest)


def make_goal(group='shared-agent',costs=(1,1),budget=3,epoch=1,profiles=('IND-DEMO-1','PAY-1'),extra=1):
    actions=[{'name':'task_'+str(i),'profile':profiles[i], 'obligation':'required:'+str(i),'cost':str(v)} for i,v in enumerate(costs)]
    actions.append({'name':'extra_check','profile':profiles[0],'obligation':'','cost':str(extra)})
    return {'model':'goal-floor-v1','group':group,'epoch':str(epoch), 'capacity':str(budget),
            'resource':'test-shared-wallet','deps':{'TaskRef':'task-1','PolicyRef':'policy-1'},'actions':actions}


class GoalCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ck=fixture_key('C');self.xk=fixture_key('X');self.ek=fixture_key('E')
        self.w=GoalCommitHarness(Path(self.tmp.name)/'test.sqlite',self.ck.public_key(),self.xk,self.ek.public_key())
        self.goal=make_goal();self.w.publish(issue_goal(self.ck,self.goal))
    def accept(self,oid,action,profile,rev=None,**kwargs):
        rev=self.w.snapshot('shared-agent')['revision'] if rev is None else rev
        return self.w.accept('shared-agent',oid,action,profile,rev,**kwargs)
    def final(self,oid,result='SUCCEEDED'):
        return issue_final(self.ek,oid,get_commit_ref(self.w,oid),result,'effect-'+oid)
    def expect(self,code,fn):
        with self.assertRaises(Reject) as x: fn()
        self.assertEqual(str(x.exception),code)
    def test_first_optional_allowed_second_destroys_goal(self):
        self.accept('one','extra_check','IND-DEMO-1')
        self.w.settle('one',self.final('one'))
        self.expect('GOAL_CAPACITY_FLOOR',lambda:self.accept('two','extra_check','IND-DEMO-1'))
    def test_old_state_request_rejected(self):
        rev=self.w.snapshot('shared-agent')['revision']
        self.accept('one','extra_check','IND-DEMO-1',rev)
        self.expect('W_STATE_STALE',lambda:self.accept('two','extra_check','IND-DEMO-1',rev))
    def test_unknown_holds_resource_and_no_false_done(self):
        self.accept('one','task_0','IND-DEMO-1')
        self.expect('GOAL_PENDING_UNKNOWN',lambda:self.accept('two','task_1','PAY-1'))
        snapshot=self.w.snapshot('shared-agent')
        self.assertEqual((snapshot['reserved'],snapshot['status']['required:0']),('1','PENDING'))
    def test_settlement_reopens_progress(self):
        self.accept('one','task_0','IND-DEMO-1');self.w.settle('one',self.final('one'))
        self.accept('two','task_1','PAY-1');self.w.settle('two',self.final('two'))
        self.assertEqual(set(self.w.snapshot('shared-agent')['status'].values()),{'DONE'})
    def test_wrong_profile(self):
        self.expect('GOAL_ACTION_SCOPE',lambda:self.accept('one','task_1','IND-DEMO-1'))
    def test_expired_dependencies(self):
        self.w.trusted_update_deps('shared-agent',{'TaskRef':'task-1','PolicyRef':'policy-2'})
        self.expect('GOAL_STALE_DEPS',lambda:self.accept('one','task_0','IND-DEMO-1'))
    def test_c_valid_new_epoch_after_dependency_change(self):
        self.w.trusted_update_deps('shared-agent',{'TaskRef':'task-1','PolicyRef':'policy-2'})
        g=copy.deepcopy(self.goal);g['epoch']='2';g['deps']['PolicyRef']='policy-2'
        self.w.publish(issue_goal(self.ck,g));self.accept('one','task_0','IND-DEMO-1')
    def test_tampered_c_certificate(self):
        c=issue_goal(self.ck,self.goal);c['claim']['capacity']='100'
        self.expect('BAD_SIGNATURE',lambda:self.w.publish(c))
    def test_c_epoch_replay(self):
        self.expect('GOAL_EPOCH_CAS',lambda:self.w.publish(issue_goal(self.ck,self.goal)))
    def test_no_extra_accepted_after_full_floor(self):
        self.goal=make_goal(costs=(1,1),budget=2)
        # Fresh group for exact-capacity proof; old cert deliberately immutable.
        self.goal['group']='exact';self.w.publish(issue_goal(self.ck,self.goal))
        self.expect('GOAL_CAPACITY_FLOOR',lambda:self.w.accept('exact','x','extra_check','IND-DEMO-1','0'))
        self.assertEqual(self.w.snapshot('exact')['revision'],'0')
    def test_x_receipt_bind_and_restart_recovery(self):
        with self.assertRaisesRegex(RuntimeError,'SIMULATED_CRASH'):
            self.accept('one','task_0','IND-DEMO-1',crash_after_commit=True)
        first=self.w.receipt('one');again=self.w.receipt('one')
        self.assertEqual(first,again)
        reopened=GoalCommitHarness(Path(self.tmp.name)/'test.sqlite',self.ck.public_key(),self.xk,self.ek.public_key())
        self.assertEqual(first,reopened.receipt('one'))
        check_sig(self.xk.public_key(),RECEIPT_DOM,first['claim'],first['signature'])
    def test_c_cannot_publish_already_impossible_goal(self):
        g=make_goal(group='impossible',costs=(2,2),budget=3)
        self.expect('GOAL_UNREACHABLE_AT_PUBLISH',lambda:issue_goal(self.ck,g))
    def test_no_final_before_original_receipt(self):
        with self.assertRaisesRegex(RuntimeError,'SIMULATED_CRASH'):
            self.accept('one','task_0','IND-DEMO-1',crash_after_commit=True)
        f=self.final('one')
        self.expect('RECEIPT_NOT_SIGNED',lambda:self.w.settle('one',f))
        self.w.receipt('one')
        self.assertEqual(self.w.settle('one',f),'SETTLED')
    def test_x_receipt_tamper(self):
        receipt=self.accept('one','task_0','IND-DEMO-1')
        bad=copy.deepcopy(receipt);bad['claim']['commit_ref']='changed'
        self.expect('BAD_SIGNATURE',lambda:check_sig(self.xk.public_key(),RECEIPT_DOM,bad['claim'],bad['signature']))
    def test_e_final_tamper(self):
        self.accept('one','task_0','IND-DEMO-1')
        f=self.final('one');f['claim']['outcome']='FAILED_CONFIRMED'
        self.expect('BAD_SIGNATURE',lambda:self.w.settle('one',f))
    def test_e_final_wrong_commit(self):
        self.accept('one','task_0','IND-DEMO-1')
        f=issue_final(self.ek,'one','wrong','SUCCEEDED','effect-1')
        self.expect('FINAL_BINDING',lambda:self.w.settle('one',f))
    def test_conflicting_final_cannot_replace(self):
        self.accept('one','task_0','IND-DEMO-1')
        f=self.final('one');self.w.settle('one',f)
        self.assertEqual(self.w.settle('one',f),'ALREADY_SETTLED')
        altered=issue_final(self.ek,'one',get_commit_ref(self.w,'one'),'FAILED_CONFIRMED','effect-2')
        self.expect('FINAL_CONFLICT',lambda:self.w.settle('one',altered))
    def test_failed_required_action_blocks_goal(self):
        self.accept('one','task_0','IND-DEMO-1');self.w.settle('one',self.final('one','FAILED_CONFIRMED'))
        self.expect('GOAL_UNRECOVERABLE',lambda:self.accept('two','task_1','PAY-1'))
    def test_intent_replay(self):
        self.accept('one','extra_check','IND-DEMO-1')
        self.expect('INTENT_REPLAY',lambda:self.accept('one','extra_check','IND-DEMO-1'))
    def test_commit_binding_refs(self):
        self.accept('one','task_0','IND-DEMO-1')
        with self.w.db() as c:
            r=c.execute('SELECT * FROM w_operation WHERE oid=?',('one',)).fetchone()
            b=__import__('json').loads(r['commit_body'])
        self.assertEqual(b['commit_ref'] if 'commit_ref' in b else digest(COMMIT_DOM,b),r['commit_ref'])
        self.assertEqual(b['goal_ref'],digest(GOAL_DOM,self.goal))
    def test_no_accept_side_effects_on_floor_denial(self):
        self.goal=make_goal(budget=2);self.goal['group']='tight';self.w.publish(issue_goal(self.ck,self.goal))
        self.expect('GOAL_CAPACITY_FLOOR',lambda:self.w.accept('tight','blocked','extra_check','IND-DEMO-1','0'))
        with self.w.db() as c:
            n=c.execute('SELECT count(*) FROM w_operation WHERE oid=?',('blocked',)).fetchone()[0]
        self.assertEqual(n,0)
    def test_foreign_c_key_rejected(self):
        fake=issue_goal(fixture_key('evil'),make_goal(group='evil'))
        self.expect('BAD_SIGNATURE',lambda:self.w.publish(fake))


class VariedScenarios(unittest.TestCase):
    def run_case(self,group,costs,profiles,budget,optional_cost):
        with tempfile.TemporaryDirectory() as tmp:
            ck,xk,ek=[fixture_key(x) for x in ('C','X','E')]
            w=GoalCommitHarness(Path(tmp)/'x.db',ck.public_key(),xk,ek.public_key())
            goal=make_goal(group,costs,budget=budget,profiles=profiles,extra=optional_cost);w.publish(issue_goal(ck,goal))
            w.accept(group,'a','task_0',profiles[0],'0')
            fact=issue_final(ek,'a',get_commit_ref(w,'a'),'SUCCEEDED','e1');w.settle('a',fact)
            w.accept(group,'b','task_1',profiles[1],w.snapshot(group)['revision'])
            fact=issue_final(ek,'b',get_commit_ref(w,'b'),'SUCCEEDED','e2');w.settle('b',fact)
            return w.snapshot(group)
    def test_industrial(self):
        s=self.run_case('ind',(1,1),('IND-DEMO-1','IND-DEMO-1'),2,1)
        self.assertEqual(s['spent'],'2')
    def test_payment(self):
        s=self.run_case('pay',(20,30),('PAY-1','PAY-1'),55,10)
        self.assertEqual(s['spent'],'50')
    def test_security_response_not_original_three_profiles(self):
        s=self.run_case('security',(3,2),('SECURITY-LAB','SECURITY-LAB'),6,2)
        self.assertEqual(s['spent'],'5')
    def test_cross_profile_shared_goal(self):
        s=self.run_case('cross',(2,2),('IND-DEMO-1','PAY-1'),5,2)
        self.assertEqual(s['spent'],'4')

if __name__=='__main__':unittest.main()

class OfflineEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from run_demo import main
        from pathlib import Path
        import json
        main()
        cls.original=json.loads(Path(__file__).with_name('sample_evidence.json').read_text())
        cls.c=fixture_key('C').public_key()
        cls.x=fixture_key('X').public_key()
        cls.e=fixture_key('E').public_key()
    def verify(self,packet):
        from offline_verify import verify_bundle
        return verify_bundle(packet,self.c,self.x,self.e)
    def test_genuine_bundle(self):
        self.assertTrue(self.verify(self.original)['verified'])
    def test_tampered_decision(self):
        p=copy.deepcopy(self.original);p['decision']['remaining_floor']='0'
        with self.assertRaisesRegex(Reject,'DECISION_MISMATCH'):self.verify(p)
    def test_tampered_commit(self):
        p=copy.deepcopy(self.original);p['w_commit']['state_ref']='wrong'
        with self.assertRaisesRegex(Reject,'COMMIT_FIELDS_MISMATCH'):self.verify(p)
    def test_tampered_goal_even_with_old_signed_c(self):
        p=copy.deepcopy(self.original);p['c_certificate']['claim']['capacity']='999'
        with self.assertRaisesRegex(Reject,'BAD_SIGNATURE'):self.verify(p)
    def test_tampered_e_signed_final(self):
        p=copy.deepcopy(self.original);p['e_final']['claim']['effect_id']='changed'
        with self.assertRaisesRegex(Reject,'BAD_SIGNATURE'):self.verify(p)
