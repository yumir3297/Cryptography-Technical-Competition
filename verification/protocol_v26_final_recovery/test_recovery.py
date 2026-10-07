import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from .model import fixture,Ledger,sign,record_ref,fact_id,b64


class RecoveryTests(unittest.TestCase):
    def test_expired_first_proof_rejected_then_current_same_fact_recovers(self):
        ledger,w,t,_,k,_=fixture();old=ledger.reattest(t,k,101)
        with self.assertRaisesRegex(ValueError,'EXPIRED'):w.receive(old,1002)
        self.assertEqual((w.reserved,w.settlements,w.flight),(1,0,True))
        fresh=ledger.reattest(t,k,1002)
        self.assertNotEqual(record_ref(old),record_ref(fresh));self.assertEqual(fact_id(old),fact_id(fresh))
        self.assertEqual(w.receive(fresh,1002)['code'],'SETTLED')
        self.assertEqual((w.reserved,w.spent,w.settlements,w.flight),(0,1,1,False))
        self.assertEqual((ledger.call_count,ledger.effect_count),(1,1))

    def test_rotation_recovers_original_fact_without_old_key_acceptance(self):
        ledger,w,t1,t2,k1,k2=fixture();old=ledger.reattest(t1,k1,101)
        w.rotate(t2,continuity_verified=True)
        with self.assertRaisesRegex(ValueError,'CURRENT_KEY'):w.receive(old,200)
        fresh=ledger.reattest(t2,k2,200)
        self.assertEqual(fact_id(old),fact_id(fresh));self.assertNotEqual(record_ref(old),record_ref(fresh))
        self.assertEqual(w.receive(fresh,200)['code'],'SETTLED');self.assertEqual(w.settlements,1)

    def test_same_fact_new_proof_never_settles_twice(self):
        ledger,w,t1,t2,k1,k2=fixture();one=ledger.reattest(t1,k1,101);w.receive(one,102)
        w.rotate(t2,continuity_verified=True);two=ledger.reattest(t2,k2,200)
        self.assertEqual(w.receive(two,200)['code'],'EXISTING')
        self.assertEqual((w.state,w.settlements,w.spent),('SUCCEEDED',1,1))
        self.assertEqual(w.receive(one,20000)['code'],'EXISTING')

    def test_concurrent_distinct_proofs_one_settlement(self):
        ledger,w,t,_,k,_=fixture();proofs=[ledger.reattest(t,k,200+i) for i in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda r:w.receive(r,210),proofs))
        self.assertEqual(sum(r['code']=='SETTLED' for r in results),1)
        self.assertEqual((w.settlements,w.spent,w.reserved),(1,1,0))
        self.assertEqual((ledger.call_count,ledger.effect_count),(1,1))

    def test_wrong_ledger_and_unknown_continuity_cannot_inherit(self):
        _,w,_,t2,_,_=fixture()
        with self.assertRaisesRegex(ValueError,'CONTINUITY_UNKNOWN'):w.rotate(t2,continuity_verified=False)
        bad=copy.deepcopy(t2);bad['value']['ledger_id']='other-ledger'
        with self.assertRaisesRegex(ValueError,'LEDGER_MISMATCH'):w.rotate(bad,continuity_verified=True)
        self.assertEqual((w.reserved,w.settlements,w.state),(1,0,'EFFECT_UNKNOWN'))

    def test_bad_signature_does_not_halt_or_release(self):
        ledger,w,t,_,k,_=fixture();r=ledger.reattest(t,k,101);r['value']['attestation']['sig']=b64(bytes(64))
        with self.assertRaises(ValueError):w.receive(r,102)
        self.assertEqual((w.state,w.reserved,w.settlements),('EFFECT_UNKNOWN',1,0))

    def test_signed_wrong_binding_does_not_halt(self):
        ledger,w,t,_,k,_=fixture();r=ledger.reattest(t,k,101)
        for field,value in [('ledger_id','other-ledger'),('operation_id',b64(bytes([9])*16)),('dispatch_attempt',b64(bytes([8])*16)),('action_hash',b64(bytes([7])*32)),('destination','other-destination')]:
            bad=copy.deepcopy(r);bad['value'][field]=value;bad=sign(bad,k)
            with self.assertRaisesRegex(ValueError,'BINDING'):w.receive(bad,102)
        self.assertEqual((w.state,w.reserved,w.settlements),('EFFECT_UNKNOWN',1,0))

    def test_authenticated_fact_conflict_halts_without_reverse_accounting(self):
        ledger,w,t,_,k,_=fixture();original=ledger.reattest(t,k,101);w.receive(original,102)
        for field,value in [('effect_id','effect-2'),('final_seq','2'),('finalized_at','100')]:
            bad=copy.deepcopy(original);bad['value'][field]=value;bad=sign(bad,k)
            self.assertEqual(w.receive(bad,102)['code'],'HALTED')
        self.assertEqual((w.state,w.spent,w.reserved,w.settlements),('HALTED',1,0,1))
        self.assertEqual(w.receive(original,20000)['state'],'HALTED')
        self.assertEqual(w.receive(ledger.reattest(t,k,300),300)['state'],'HALTED')

    def test_failure_recovery_releases_once(self):
        ledger,w,t,_,k,_=fixture(outcome='FAILED_CONFIRMED')
        fresh=ledger.reattest(t,k,1002);w.receive(fresh,1002);w.receive(ledger.reattest(t,k,1003),1003)
        self.assertEqual((w.state,w.spent,w.reserved,w.settlements,w.flight),('FAILED_CONFIRMED',0,0,1,False))
        self.assertEqual((ledger.call_count,ledger.effect_count),(1,0))

    def test_opposite_authenticated_outcome_halts_without_refund(self):
        ledger,w,t,_,k,_=fixture();original=ledger.reattest(t,k,101);w.receive(original,102)
        opposite=copy.deepcopy(original)
        opposite['value'].update(outcome='FAILED_CONFIRMED',effect_id='',no_late_effect=True)
        self.assertEqual(w.receive(sign(opposite,k),102)['code'],'HALTED')
        self.assertEqual((w.spent,w.reserved,w.settlements,w.flight),(1,0,1,False))

    def test_forged_conflict_cannot_halt_a_settled_operation(self):
        ledger,w,t,_,k,_=fixture();original=ledger.reattest(t,k,101);w.receive(original,102)
        forged=copy.deepcopy(original);forged['value']['effect_id']='attacker-effect'
        with self.assertRaises(ValueError):w.receive(forged,102)
        self.assertEqual((w.state,w.spent,w.settlements),('SUCCEEDED',1,1))

    def test_missing_ledger_fact_cannot_become_confirmed_failure(self):
        ledger,w,t,_,k,_=fixture();missing=Ledger(None,ledger.scope,ledger.profile)
        with self.assertRaisesRegex(ValueError,'UNKNOWN'):missing.reattest(t,k,1002)
        self.assertEqual((w.reserved,w.settlements,w.flight),(1,0,True))

    def test_false_failure_flag_or_future_fact_time_rejected(self):
        ledger,w,t,_,k,_=fixture(outcome='FAILED_CONFIRMED');r=ledger.reattest(t,k,101)
        bad=copy.deepcopy(r);bad['value']['no_late_effect']=False
        with self.assertRaisesRegex(ValueError,'OUTCOME'):w.receive(sign(bad,k),102)
        bad=copy.deepcopy(r);bad['value']['finalized_at']='500'
        with self.assertRaisesRegex(ValueError,'TIME_BINDING'):w.receive(sign(bad,k),102)
        self.assertEqual((w.reserved,w.settlements),(1,0))

    def test_fresh_proof_expiry_cannot_exceed_current_trust(self):
        ledger,w,t,_,k,_=fixture();t['value']['exp']='250';w.trust=copy.deepcopy(t)
        r=ledger.reattest(t,k,200);self.assertEqual(r['value']['exp'],'250')
        with self.assertRaisesRegex(ValueError,'EXPIRED'):w.receive(r,250)
        bad=copy.deepcopy(r);bad['value']['exp']='1000'
        with self.assertRaisesRegex(ValueError,'TIME_BINDING'):w.receive(sign(bad,k),200)

    def test_time_uncertainty_does_not_settle(self):
        ledger,w,t,_,k,_=fixture();r=ledger.reattest(t,k,101)
        with self.assertRaisesRegex(ValueError,'CLOCK_UNKNOWN'):w.receive(r,1000,1002)
        self.assertEqual((w.reserved,w.settlements),(1,0))

    def test_three_profiles_recover_and_cross_profile_is_rejected(self):
        records=[]
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            ledger,w,t,_,k,_=fixture(profile);r=ledger.reattest(t,k,1002);w.receive(r,1002)
            self.assertEqual(w.settlements,1);records.append(r)
        _,w,_,_,_,_=fixture()
        with self.assertRaises(Exception):w.receive(records[1],1002)
        self.assertEqual(w.settlements,0)


if __name__=='__main__':unittest.main()
