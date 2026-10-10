"""Temporal fault trajectories using the real candidate signature/wire path."""
import importlib.util
import unittest
from dataclasses import replace
from codec import enc, parse, b64, to_sign, CheckError, candidate_ref
from observation import Interval, read, candidate, publish, receive, gate
from fixtures import fixture, published_fixture


class CandidateObservationTests(unittest.TestCase):
    def reject(self, fn, code=None, truth=None):
        with self.assertRaises(CheckError) as cm:
            fn()
        if code:
            self.assertEqual(cm.exception.code, code)
        if truth:
            self.assertEqual(cm.exception.truth, truth)

    def signed_mutation(self, package, sk, change):
        obj = parse(package)
        change(obj)
        obj['observation']['sig'] = b64(sk.sign(to_sign(obj['observation'])))
        return enc(obj)

    def test_three_profiles_recover_without_original_signature_after_expiry(self):
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile):
                ctx, _, _, q, package, _, _ = published_fixture(profile)
                answer = receive(ctx,q,package,Interval(1103,1103))
                self.assertEqual(answer['truth'],'T')
                self.assertEqual(answer['fact']['accepted_at'],'100')
                self.assertFalse(answer['new_execution_rights'])
                self.assertNotIn('sig',parse(package)['archive']['original_core'])
                self.assertEqual(ctx.effects,(1,1,0,0))

    def test_new_observer_key_recovers_same_fact_identity(self):
        first = published_fixture(observer_seed=51)
        second = published_fixture(observer_seed=68)
        f1 = receive(first[0],first[3],first[4],Interval(1103,1103))['fact']
        f2 = receive(second[0],second[3],second[4],Interval(1103,1103))['fact']
        self.assertEqual(f1,f2)
        self.assertNotEqual(parse(first[4])['observation']['protected']['kid'],parse(second[4])['observation']['protected']['kid'])

    def test_unpublished_signed_candidate_is_not_success(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        self.reject(lambda:receive(ctx,q,package,Interval(1102,1102)),'PUBLICATION_UNAVAILABLE','U')

    def test_revoke_observer_between_read_and_publish(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        revoked = replace(ctx,observer=replace(ctx.observer,active=False),control_revision=2)
        self.reject(lambda:publish(revoked,q,package,witness,Interval(1102,1102)),'CURRENT_AUTH','F')
        self.assertEqual(revoked.publications,())

    def test_role_delegation_aba_rejects_old_control_revision(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        regranted = replace(ctx,control_revision=3)  # revoked/regranted Role, never revive old kid
        self.reject(lambda:publish(regranted,q,package,witness,Interval(1102,1102)),'RETRY_CONFLICT','U')

    def test_revoke_reader_between_read_and_publish(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        revoked = replace(ctx,reader=replace(ctx.reader,active=False),control_revision=2)
        self.reject(lambda:publish(revoked,q,package,witness,Interval(1102,1102)),'CURRENT_AUTH')

    def test_revoke_or_renew_control_after_publication_before_receive(self):
        ctx, _, _, q, package, _, _ = published_fixture()
        for changed in (replace(ctx,observer=replace(ctx.observer,active=False),control_revision=2),
                        replace(ctx,control_revision=2)):
            self.reject(lambda:receive(changed,q,package,Interval(1103,1103)))

    def test_current_authority_missing_unknown(self):
        ctx, _, _, q, package, _, _ = published_fixture()
        self.reject(lambda:receive(replace(ctx,observer=None),q,package,Interval(1103,1103)),'AUTHORITY_UNAVAILABLE','U')

    def test_read_or_executor_role_does_not_grant_observation(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        for purpose,role in (('READ','EXECUTOR'),('AcceptanceObservation','EXECUTOR')):
            altered = replace(ctx,observer=replace(ctx.observer,purpose=purpose,role=role))
            self.reject(lambda:publish(altered,q,package,witness,Interval(1102,1102)),'CURRENT_AUTH')

    def test_key_role_purpose_access_intersection_expiry(self):
        ctx, _, sk, q = fixture()
        limited = replace(ctx,observer=replace(ctx.observer,exp=1102))
        witness = read(limited,q,Interval(1100,1100))
        package = candidate(limited,witness,sk,Interval(1101,1101))
        self.assertEqual(parse(package)['observation']['body']['exp'],'1102')
        self.reject(lambda:publish(limited,q,package,witness,Interval(1102,1102)),'EXPIRED','F')

    def test_current_operation_access_required(self):
        ctx, _, _, q = fixture()
        no_access = replace(ctx,reader=replace(ctx.reader,operations=()))
        self.reject(lambda:read(no_access,q,Interval(1100,1100)),'CURRENT_AUTH')

    def test_observer_authorized_for_another_ledger_rejected(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        altered = replace(ctx,observer=replace(ctx.observer,ledger_origin='other-ledger'))
        self.reject(lambda:publish(altered,q,package,w,Interval(1102,1102)),'CURRENT_AUTH')

    def test_archive_continuity_anchor_and_highwater_unknown(self):
        ctx, _, _, q = fixture()
        for h in (None,replace(ctx.history,continuous=False),replace(ctx.history,archive_validated=False),
                  replace(ctx.history,independent_anchor=False),replace(ctx.history,independent_highwater=0)):
            self.reject(lambda:read(replace(ctx,history=h),q,Interval(1100,1100)),'HISTORY_UNAVAILABLE','U')

    def test_signed_false_snapshot_rejected_against_frozen_read(self):
        ctx, _, sk, q = fixture()
        witness = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,witness,sk,Interval(1101,1101))
        def change(obj):
            obj['observation']['body']['snapshot'].update(status='SUCCEEDED',status_seq='9')
        bad = self.signed_mutation(package,sk,change)
        self.reject(lambda:publish(ctx,q,bad,witness,Interval(1102,1102)),'BINDING')

    def test_signed_fact_field_substitutions_rejected(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        for field,new in (('accepted_at','101'),('ledger_origin','other-ledger'),('accept_seq','2'),
                          ('operation_id',b64(bytes([99])*16)),('original_core_digest',b64(bytes(32)))):
            def change(obj,field=field,new=new):
                obj['observation']['body']['fact'][field] = new
            self.reject(lambda:publish(ctx,q,self.signed_mutation(package,sk,change),w,Interval(1102,1102)))

    def test_signed_archive_tampering_rejected(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        def change(obj):
            obj['archive']['original_core']['body']['payload']['accepted_at'] = '101'
        self.reject(lambda:publish(ctx,q,self.signed_mutation(package,sk,change),w,Interval(1102,1102)))

    def test_original_action_hash_and_core_commit_time_link_checked(self):
        ctx, _, _, q = fixture()
        for field,value in (('accepted_at','101'),('dispatch_before','999')):
            archive = parse(ctx.history.archive_wire)
            archive['commit']['value'][field] = value
            h = replace(ctx.history,archive_wire=enc(archive))
            self.reject(lambda:read(replace(ctx,history=h),q,Interval(1100,1100)))

    def test_fake_original_envelope_and_extra_fields_rejected(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        for field,value in (('sig',''),('extra','x')):
            def change(obj,field=field,value=value):
                obj['archive']['original_core'][field] = value
            self.reject(lambda:publish(ctx,q,self.signed_mutation(package,sk,change),w,Interval(1102,1102)),'FORMAT')

    def test_query_wrong_nonce_attempt_and_audience_rejected(self):
        ctx, holder, _, q = fixture()
        for field,value in (('nonce',b64(bytes([8])*32)),('attempt_id',b64(bytes([9])*16)),('aud',['wrong'])):
            obj = parse(q)
            obj['body'][field] = value
            obj['sig'] = b64(holder.sign(to_sign(obj)))
            self.reject(lambda:read(ctx,enc(obj),Interval(1100,1100)))

    def test_challenge_window_cannot_be_renewed_by_signed_query(self):
        ctx, holder, _, q = fixture()
        obj = parse(q)
        obj['body'].update(iat='1140',exp='1170')
        obj['sig'] = b64(holder.sign(to_sign(obj)))
        self.reject(lambda:read(ctx,enc(obj),Interval(1140,1140)),'BINDING')

    def test_nonce_reuse_with_another_query_rejected(self):
        ctx, holder, _, q, package, w, _ = published_fixture()
        obj = parse(q)
        obj['body']['id'] = b64(bytes([99])*16)
        obj['sig'] = b64(holder.sign(to_sign(obj)))
        self.reject(lambda:publish(ctx,enc(obj),package,w,Interval(1103,1103)),'REPLAY')
        self.reject(lambda:receive(ctx,enc(obj),package,Interval(1103,1103)),'PUBLICATION_UNAVAILABLE','U')

    def test_exact_replay_is_stored_bytes_even_after_expiry(self):
        ctx, _, _, q, package, w, row = published_fixture()
        after, replay = publish(ctx,q,b'ignored candidate',w,Interval(1140,1140))
        self.assertEqual(replay.package_wire,package)
        self.assertEqual(replay,row)
        self.assertEqual(after,ctx)
        self.reject(lambda:receive(ctx,q,package,Interval(1140,1140)),'EXPIRED','F')

    def test_saved_snapshot_can_be_older_than_later_current_state(self):
        ctx, _, _, q, package, _, _ = published_fixture()
        later = replace(ctx,status='SUCCEEDED',status_seq=9)
        result = receive(later,q,package,Interval(1103,1103))
        self.assertEqual(result['snapshot']['status'],'ACCEPTED')
        self.assertEqual(result['snapshot']['status_seq'],'1')
        self.assertEqual(result['snapshot']['observed_time'],{'lo':'1100','hi':'1100'})

    def test_publication_pins_signature_bytes_not_only_reference(self):
        ctx, _, _, q, package, _, _ = published_fixture()
        obj = parse(package)
        ref_before = candidate_ref(obj['observation'])
        obj['observation']['sig'] = b64(bytes(64))
        self.assertEqual(candidate_ref(obj['observation']),ref_before)
        self.reject(lambda:receive(ctx,q,enc(obj),Interval(1103,1103)),'PUBLICATION_UNAVAILABLE','U')

    def test_expiry_crossing_and_clock_loss_never_publish(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        for clock in (None,Interval(1129,1130),Interval(1130,1130),Interval(1102,1105)):
            self.reject(lambda:publish(ctx,q,package,w,clock))
        self.assertEqual(ctx.effects,(1,1,0,0))

    def test_raw_tamper_wrong_profile_and_domain_rejected(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        def change(obj):
            obj['observation']['protected']['profile'] = 'MED-DEMO-1'
        self.reject(lambda:publish(ctx,q,self.signed_mutation(package,sk,change),w,Interval(1102,1102)))
        obj = parse(package)
        obj['observation']['body']['snapshot']['status']='SUCCEEDED'
        self.reject(lambda:publish(ctx,q,enc(obj),w,Interval(1102,1102)),'SIGNATURE')

    def test_publish_side_effects_are_only_response_and_time_floor(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        after, _ = publish(ctx,q,package,w,Interval(1102,1102))
        self.assertEqual(after.effects,ctx.effects)
        self.assertEqual(after.history,ctx.history)
        self.assertEqual(after.status_seq,ctx.status_seq)
        self.assertEqual(len(after.publications),1)
        self.assertEqual(after.time_floor,1102)

    def test_interval_upper_bound_is_not_a_persistent_time_lower_bound(self):
        ctx, _, sk, q = fixture()
        w = read(ctx,q,Interval(1100,1100))
        package = candidate(ctx,w,sk,Interval(1101,1101))
        after, _ = publish(ctx,q,package,w,Interval(1102,1104))
        self.assertEqual(after.time_floor,1102)
        self.assertEqual(receive(after,q,package,Interval(1103,1103))['truth'],'T')


if __name__ == '__main__':
    unittest.main()
