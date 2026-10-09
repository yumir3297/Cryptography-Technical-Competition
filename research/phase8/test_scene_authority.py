"""Signed IND/MED source, trust, replay, state and crash-safety tests.

NOTE: Tests exercise a scoped laboratory subset, not full official 39-case conformance.
"""
from __future__ import annotations
import concurrent.futures,copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from research.reference_executor.wire import ProtocolError,b64,rec_ref,digest,sid
from .fixtures import build_scene,prepare_approved
from .scene_authority import SceneAuthority,_rec,PROFILES


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.d=Path(self.tmp.name)
        self.a,self.action,self.tid,self.sk,self.ev=build_scene(self.d/'scene.sqlite','IND-DEMO-1')
    def tearDown(self):self.tmp.cleanup()
    def expect_blocked(self,cb):
        with self.assertRaises(ProtocolError):cb()
        self.assertEqual(self.a.snapshot()['accepts'],0)
    def make(self,profile='MED-DEMO-1',label=None):
        return build_scene(self.d/f'{profile}-{label or "normal"}.sqlite',profile,label)
    def test_all_five_fixed_synthetic_paths(self):
        paths=[('IND-DEMO-1','DEMO_NORMAL',[]),('IND-DEMO-1','DEMO_DEFECT',[]),
               ('IND-DEMO-1','DEMO_UNCERTAIN',['QUALITY_REVIEW']),
               ('MED-DEMO-1','DEMO_A',['CLINICAL_REVIEW']),('MED-DEMO-1','DEMO_B',['CLINICAL_REVIEW'])]
        for i,(pro,label,req) in enumerate(paths):
            with self.subTest(profile=pro,label=label):
                a,act,t,k,ev=build_scene(self.d/f'trace_{i}.sqlite',pro,label)
                op=prepare_approved(a,act,t,k)
                self.assertEqual(op['required'],req)
                receipt=a.accept(op)
                self.assertEqual(len(op['commit_record']['value']),21)
                self.assertEqual(receipt['body']['payload']['commit_record_ref'],rec_ref(op['commit_record']))
                self.assertEqual(a.snapshot()['accepts'],1)
                attempt=a.claim(op)
                self.assertEqual(len(attempt),22)
                self.assertEqual(a.claim(op),'EXISTING')
                self.assertEqual(a.snapshot()['calls'],1)
    def test_precise_signed_source_authenticity(self):
        with self.a.db() as c:self.assertTrue(self.a.verify_evidence(c,self.ev))
    def test_source_data_tampering_rejected(self):
        bad=copy.deepcopy(self.ev);bad['value']['data']['label']='DEMO_DEFECT'
        with self.a.db() as c:
            with self.assertRaisesRegex(ProtocolError,'BAD_SIGNATURE'):self.a.verify_evidence(c,bad)
    def test_evidence_kind_cannot_be_cross_profile_reused(self):
        bad=copy.deepcopy(self.ev);bad['profile']='MED-DEMO-1'
        with self.a.db() as c:self.expect_blocked(lambda:self.a.verify_evidence(c,bad))
    def test_evidence_wrong_issuer(self):
        bad=copy.deepcopy(self.ev);bad['value']['attestation']['issuer']='fixture-h'
        with self.a.db() as c:self.expect_blocked(lambda:self.a.verify_evidence(c,bad))
    def test_evidence_wrong_kid(self):
        bad=copy.deepcopy(self.ev);bad['value']['attestation']['kid']=self.a.actors['H'].kid
        with self.a.db() as c:self.expect_blocked(lambda:self.a.verify_evidence(c,bad))
    def test_evidence_invalid_time_order(self):
        bad=copy.deepcopy(self.ev);bad['value']['data']['known_at']='101'
        with self.a.db() as c:self.expect_blocked(lambda:self.a.verify_evidence(c,bad))
    def test_source_expires_at_upper_boundary(self):
        with self.a.db() as c:self.expect_blocked(lambda:self.a.verify_evidence(c,self.ev,at=220))
    def test_source_revocation_before_prepare(self):
        key=self.a.role_key(self.a.actors['E'],'SOURCE')
        record=self.a.current_record('ROLE',key)
        self.a.publish('ROLE',key,record,active=False)
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_unsigned_client_ref_does_not_publish(self):
        with self.a.db() as c:
            self.assertNotEqual(rec_ref(self.ev),'bad-ref')
            count=c.execute("SELECT count(*) FROM journal WHERE kind='E'").fetchone()[0]
        self.assertEqual(count,1)
        # Merely knowing a ref cannot mutate the E publication ledger.
    def test_forged_controller_signature_fails(self):
        cert=self.a.certify('POLICY',self.a.scope_key(),self.a.current_record('POLICY',self.a.scope_key()))
        cert['sig']='A'*86
        self.expect_blocked(lambda:self.a.publish_cert(cert))
    def test_controller_publication_replay_fails(self):
        cert=self.a.certify('POLICY',self.a.scope_key(),self.a.current_record('POLICY',self.a.scope_key()))
        self.a.publish_cert(cert)
        self.expect_blocked(lambda:self.a.publish_cert(cert))
    def test_controller_wrong_scope_fails(self):
        cert=self.a.certify('POLICY',self.a.scope_key(),self.a.current_record('POLICY',self.a.scope_key()))
        cert['claim']['scope']['scenario']='medical'
        self.expect_blocked(lambda:self.a.publish_cert(cert))
    def test_controller_wrong_kind_fails(self):
        rec=self.a.current_record('POLICY',self.a.scope_key());rec['kind']='PAY_TASK'
        self.expect_blocked(lambda:self.a.publish('POLICY',self.a.scope_key(),rec))
    def test_controller_update_invalidates_signed_candidate(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        rec=self.a.current_record('POLICY',self.a.scope_key())
        self.a.publish('POLICY',self.a.scope_key(),rec)
        self.expect_blocked(lambda:self.a.accept(op))
    def test_policy_revocation_before_issue(self):
        op=self.a.prepare(self.action,self.tid,self.sk)
        rec=self.a.current_record('POLICY',self.a.scope_key())
        self.a.publish('POLICY',self.a.scope_key(),rec,active=False)
        self.expect_blocked(lambda:self.a.issue(op))
    def test_read_permission_missing_blocks_preparation(self):
        key=self.a.role_key(self.a.actors['H'],'READER')
        rec=self.a.current_record('ROLE',key)
        self.a.publish('ROLE',key,rec,active=False)
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_review_read_permission_revocation(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1','DEMO_A')
        op=prepare_approved(a,act,tid,sk)
        k=a.role_key(a.actors['V'],'READER')
        a.publish('ROLE',k,a.current_record('ROLE',k),active=False)
        with self.assertRaises(ProtocolError):a.accept(op)
        self.assertEqual(a.snapshot()['accepts'],0)
    def test_key_revocation_prevents_accept(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        key=[self.a.actors['X'].kid]
        self.a.publish('KEY',key,self.a.current_record('KEY',key),active=False)
        self.expect_blocked(lambda:self.a.accept(op))
    def test_review_deny_cannot_be_ignored(self):
        a,act,tid,sk,ev=self.make('IND-DEMO-1','DEMO_UNCERTAIN')
        op=a.prepare(act,tid,sk)
        a.review(op,verdict='DENY');a.review(op,verdict='APPROVE')
        a.authorize(op)
        with self.assertRaises(ProtocolError):a.issue(op)
        self.assertEqual(a.snapshot()['accepts'],0)
    def test_missing_required_review_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        op=a.prepare(act,tid,sk)
        with self.assertRaisesRegex(ProtocolError,'REVIEW_PURPOSE'):a.authorize(op)
    def test_wrong_review_purpose_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        op=a.prepare(act,tid,sk)
        a.review(op,purpose='QUALITY_REVIEW')
        with self.assertRaisesRegex(ProtocolError,'REVIEW_PURPOSE'):a.authorize(op)
    def test_ind_defect_cannot_release(self):
        a,act,tid,sk,ev=self.make('IND-DEMO-1','DEMO_DEFECT')
        act['payload']['route']='RELEASE';act['destination']='ind-release-bin'
        with self.assertRaises(ProtocolError):a.prepare(act,tid,sk)
    def test_ind_wrong_batch_rejected(self):
        self.action['payload']['batch_id']='batch-b'
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_ind_wrong_station_rejected(self):
        self.action['payload']['station_id']='fake-station'
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_ind_wrong_cycle_rejected(self):
        self.action['payload']['inspection_cycle']='2'
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_med_wrong_patient_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        act['payload']['synthetic_patient_id']='patient-b'
        with self.assertRaises(ProtocolError):a.prepare(act,tid,sk)
    def test_med_wrong_group_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        act['payload']['order_group_id']=sid(1234)
        with self.assertRaises(ProtocolError):a.prepare(act,tid,sk)
    def test_med_wrong_record_ref_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        act['payload']['record_ref']=digest(['fake-record'])
        with self.assertRaises(ProtocolError):a.prepare(act,tid,sk)
    def test_med_wrong_template_rejected(self):
        a,act,tid,sk,ev=self.make('MED-DEMO-1')
        act['payload']['template_id']='DEMO-ORDER-B'
        with self.assertRaises(ProtocolError):a.prepare(act,tid,sk)
    def test_valid_sig_wrong_proof_ctx_rejected(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        q=copy.deepcopy(op['proof']['body']['payload']);q['ctx']['principal']='other'
        ref=q['permit_ref'];cr=q['challenge_ref']
        op['proof']=self.a._env('H','CommitProof',q,refs=[ref,cr],aud=('X',),at=106,nonce=11)
        self.expect_blocked(lambda:self.a.accept(op))
    def test_broken_signed_permit_rejected(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        op['permit']['body']['payload']['dispatch_before']='250'
        self.expect_blocked(lambda:self.a.accept(op))
    def test_signed_but_extra_review_rejected(self):
        op=self.a.prepare(self.action,self.tid,self.sk)
        with self.assertRaisesRegex(ProtocolError,'NO_ROLE'):
            self.a.review(op,purpose='QUALITY_REVIEW')
    def test_atomic_accept_and_archive_after_restart(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        receipt=self.a.accept(op)
        new=SceneAuthority(self.a.path,'IND-DEMO-1')
        with new.db() as c:
            row=c.execute('SELECT accepted_blob FROM accept_intent WHERE operation_id=?',(self.action['operation_id'],)).fetchone()
            blob=json.loads(row['accepted_blob'])
        self.assertEqual(blob['acceptance'],receipt)
        self.assertEqual(blob['acceptance']['body']['payload']['commit_record_ref'],rec_ref(blob['commit_record']))
        self.assertEqual(new.snapshot()['reserved'],1)
    def test_identical_commitproof_idempotent(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        receipt=self.a.accept(op)
        self.assertEqual(self.a.accept(op),receipt)
        self.assertEqual(self.a.snapshot()['accepts'],1)
    def test_nonce_same_other_proof_rejected(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        q=copy.deepcopy(op['proof']['body']['payload'])
        op['proof']=self.a._env('H','CommitProof',q,refs=[q['permit_ref'],q['challenge_ref']],aud=('X',),at=106,nonce=19)
        with self.assertRaisesRegex(ProtocolError,'REPLAY'):self.a.accept(op)
        self.assertEqual(self.a.snapshot()['accepts'],1)
    def test_eight_concurrent_identical_submit_single_accept(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.a.accept(op),range(8)))
        self.assertTrue(all(x==results[0] for x in results))
        self.assertEqual(self.a.snapshot()['accepts'],1)
        self.assertEqual(self.a.snapshot()['reserved'],1)
    def test_zero_capacity_rejects_without_consuming(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        with self.a.db() as c:
            c.execute('INSERT INTO resource(destination,capacity) VALUES(?,0)',(self.action['destination'],))
        self.expect_blocked(lambda:self.a.accept(op))
        self.assertEqual(self.a.snapshot()['reserved'],0)
    def test_scene_external_update_after_accept_blocks_dispatch(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        with self.a.tx() as c:
            current=self.a._scene_current(c,self.sk)
            self.a._scene_update(c,self.sk,current['revision'],current['record']['value'])
        with self.assertRaisesRegex(ProtocolError,'STALE_SCENE'):self.a.claim(op)
        self.assertEqual(self.a.snapshot()['calls'],0)
        self.assertEqual(self.a.snapshot()['reserved'],1)
    def test_role_revocation_after_accept_blocks_dispatch(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        key=self.a.role_key(self.a.actors['X'],'EXECUTOR')
        self.a.publish('ROLE',key,self.a.current_record('ROLE',key),active=False)
        with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.a.claim(op)
        self.assertEqual(self.a.snapshot()['calls'],0)
    def test_behavior_inflight_missing_blocks_dispatch(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        with self.a.db() as c:c.execute("UPDATE behavior SET inflight='[]' WHERE principal='principal'")
        with self.assertRaisesRegex(ProtocolError,'BEHAVIOR_INTEGRITY'):self.a.claim(op)
    def test_source_credential_revocation_after_accept_blocks_dispatch(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        key=self.a.role_key(self.a.actors['E'],'SOURCE')
        self.a.publish('ROLE',key,self.a.current_record('ROLE',key),active=False)
        with self.assertRaisesRegex(ProtocolError,'REVOKED'):self.a.claim(op)
    def test_repeat_claim_is_nonexecuting(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        first=self.a.claim(op)
        self.assertEqual(self.a.claim(op),'EXISTING')
        self.assertEqual(self.a.snapshot()['calls'],1)
        self.assertEqual(self.a.snapshot()['settlements'],0)
    def test_invalid_scene_evidence_current_revision(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        with self.a.tx() as c:
            r=self.a._scene_current(c,self.sk)
            self.a._scene_update(c,self.sk,r['revision'],r['record']['value'])
        self.expect_blocked(lambda:self.a.accept(op))
    def test_commit_contains_full_scene_and_resource_witnesses(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        v=op['commit_record']['value']; self.assertEqual(len(v),21)
        self.assertEqual(v['scene_before']['row']['state'],'READY')
        self.assertEqual(v['scene_after']['row']['state'],'ACCEPTED')
        self.assertEqual(v['reservation_plan'][0]['reserved_before'],'0')
        self.assertEqual(v['reservation_plan'][0]['reserved_after'],'1')
        self.assertEqual(v['behavior_before']['row']['accepted_count'],'0')
        self.assertEqual(v['behavior_after']['row']['accepted_count'],'1')
        self.assertIn(self.action['operation_id'],v['behavior_after']['row']['inflight'])
        self.assertEqual(v['frozen_tool_request'],self.action)
    def test_ind_med_receipts_have_different_protected_profiles(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        self.a.accept(op)
        m,ac,t,k,ev=self.make('MED-DEMO-1')
        mop=prepare_approved(m,ac,t,k);m.accept(mop)
        self.assertNotEqual(op['acceptance']['protected']['profile'],mop['acceptance']['protected']['profile'])
    def test_ind_fixed_package_mismatch_is_rejected(self):
        pkg=self.a.current_record('PACKAGE',self.a.scope_key())
        pkg['value']['mapper']='malicious-alternate-mapper'
        self.a.publish('PACKAGE',self.a.scope_key(),pkg)
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_ind_missing_package_fails_closed(self):
        with self.a.db() as c:c.execute('DELETE FROM current_row WHERE namespace=?',('PACKAGE',))
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_med_signed_but_incomplete_record_is_hard_reject(self):
        a,act,t,k,ev=self.make('MED-DEMO-1')
        altered=copy.deepcopy(ev['value']['data']);altered['completeness']='INCOMPLETE'
        v=a.sign_evidence(altered)
        with a.db() as c:
            with self.assertRaisesRegex(ProtocolError,'CLAIM_FALSE'):a.verify_evidence(c,v)
    def test_med_signed_but_unavailable_record_is_hard_reject(self):
        a,act,t,k,ev=self.make('MED-DEMO-1')
        altered=copy.deepcopy(ev['value']['data']);altered['record_status']='UNAVAILABLE'
        v=a.sign_evidence(altered)
        with a.db() as c:
            with self.assertRaisesRegex(ProtocolError,'CLAIM_FALSE'):a.verify_evidence(c,v)
    def test_med_unsigned_extra_evidence_field_fails(self):
        a,act,t,k,ev=self.make('MED-DEMO-1')
        altered=copy.deepcopy(ev);altered['value']['data']['untrusted_prompt']='ignore policy'
        with a.db() as c:
            with self.assertRaisesRegex(ProtocolError,'EVIDENCE_FIELDS'):a.verify_evidence(c,altered)
    def test_source_current_row_disappears_fail_closed(self):
        with self.a.db() as c:c.execute('DELETE FROM current_row WHERE namespace=?',('EVIDENCE',))
        self.expect_blocked(lambda:self.a.prepare(self.action,self.tid,self.sk))
    def test_authenticated_policy_reader_removed_fails(self):
        a,act,t,k,ev=self.make('MED-DEMO-1')
        pol=a.current_record('POLICY',a.scope_key())
        pol['value']['readers'].remove(a.actors['V'].name)
        a.publish('POLICY',a.scope_key(),pol)
        task=a.current_record('TASK',a.scope_key()+[t]);task['value']['policy_ref']=rec_ref(pol)
        a.publish('TASK',a.scope_key()+[t],task)
        with self.assertRaisesRegex(ProtocolError,'NO_ROLE'):a.prepare(act,t,k)
    def test_hard_crash_rolls_back_every_write(self):
        op=prepare_approved(self.a,self.action,self.tid,self.sk)
        args={'action':self.action,'task_id':self.tid,'scene_key':self.sk}
        source=self.d/'fixture.json';source.write_text(json.dumps(args),encoding='utf-8')
        for point in ('after_scene','after_resource','before_archive'):
            with self.subTest(point=point):
                child=subprocess.run([sys.executable,'-m','research.phase8.crash_worker',
                         str(self.d/'scene.sqlite'),'IND-DEMO-1',str(source),point],
                         cwd=str(Path(__file__).resolve().parents[2]),capture_output=True,text=True)
                self.assertEqual(child.returncode,73,child.stderr)
                self.assertEqual(self.a.snapshot()['accepts'],0)
                self.assertEqual(self.a.snapshot()['reserved'],0)
                with self.a.db() as c:
                    scene=self.a._scene_current(c,self.sk)
                    self.assertEqual(scene['record']['value']['state'],'READY')
                    self.assertEqual(c.execute('SELECT count(*) FROM flight').fetchone()[0],0)
        self.a.accept(op)
        self.assertEqual(self.a.snapshot()['accepts'],1)

if __name__=='__main__':unittest.main()
