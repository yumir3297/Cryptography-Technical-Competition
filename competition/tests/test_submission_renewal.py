"""Joint V1/P2 behavior with real signatures and one persistent request store."""
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from competition.tests.renewal_fixtures import RenewalCase, refresh_short, SHORT, P
from competition.support.wire import ProtocolError, b64, digest

class SubmissionRenewalTests(RenewalCase):
    def test_short_only_replacement_preserves_authority_and_blocks_old_ticket(self):
        saved = self.freeze(); old = self.prepare(self.op)
        fresh = refresh_short(self.run,self.op)
        updated = self.replace(fresh,saved)
        self.assertEqual(updated['version'],2)
        for name in self.op:
            if name not in SHORT: self.assertEqual(updated['op'][name],self.op[name])
        self.blocked(lambda:self.accept(old),'SUBMISSION_SUPERSEDED')
        self.assertEqual(self.accept(self.prepare(fresh))['acceptance_state'],'COMMITTED')
        self.assertEqual(self.run.w.counts()['accepts'],1)

    def test_expired_short_chain_renews_using_original_permit(self):
        short = refresh_short(self.run,self.op,expires=int(time.time())+5)
        saved = self.freeze(short)
        until = int(short['proof']['body']['exp'])
        time.sleep(max(0,until-time.time())+.05)
        self.blocked(lambda:self.prepare(short),'EXPIRED')
        fresh = refresh_short(self.run,short)
        self.assertEqual(fresh['permit'],short['permit'])
        self.replace(fresh,saved)
        self.assertEqual(self.accept(self.prepare(fresh))['acceptance_state'],'COMMITTED')

    def test_reissued_authorization_or_issue_or_permit_is_rejected(self):
        saved = self.freeze()
        fresh = copy.deepcopy(self.op)
        signing = copy.copy(self.run.base); signing.operations={**self.run.operations,P:fresh}
        signing.resign_chain(P,fresh,keep_permit_deps=False)
        for name in ('authorization','issue','permit'):
            changed=refresh_short(self.run,self.op);changed[name]=fresh[name]
            self.blocked(lambda:self.replace(changed,saved),'FROZEN_AUTHORITY_CONFLICT')
        self.assertEqual(self.store.load(self.row['key'])['op'],self.op)

    def test_full_old_packet_cannot_become_current_again(self):
        first=self.freeze();fresh=refresh_short(self.run,self.op)
        second=self.replace(fresh,first)
        self.blocked(lambda:self.replace(self.op,second),'SUBMISSION_REPLAY')
        self.assertEqual(self.store.load(self.row['key'])['op'],fresh)

    def test_new_signatures_cannot_reuse_challenge_session_nonce_or_attempt(self):
        first=self.freeze()
        for field in ('session','nonce','attempt','ChallengeRequest','Challenge','CommitProof'):
            with self.subTest(reused=field):
                fresh=refresh_short(self.run,self.op,reuse=self.op,reuse_fields=(field,))
                self.blocked(lambda:self.replace(fresh,first),'SUBMISSION_REPLAY')
        self.assertEqual(self.store.load(self.row['key']),first)

    def test_replacement_retry_is_idempotent_but_stale_writer_cannot_overwrite(self):
        first=self.freeze();a=refresh_short(self.run,self.op);b=refresh_short(self.run,self.op)
        second=self.replace(a,first)
        self.assertEqual(self.replace(a,first),second)
        self.blocked(lambda:self.replace(b,first),'SUBMISSION_VERSION_CONFLICT')
        self.assertEqual(self.store.load(self.row['key']),second)

    def test_bad_signature_does_not_replace_current_packet(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        from competition.support.wire import raw, L
        sig=raw(fresh['proof']['sig'],64)
        fresh['proof']['sig']=b64(sig[:32]+((int.from_bytes(sig[32:],'little')+1)%L).to_bytes(32,'little'))
        self.blocked(lambda:self.replace(fresh,saved),'BAD_SIGNATURE')
        self.assertEqual(self.store.load(self.row['key']),saved)

    def test_original_holder_proof_does_not_authenticate_replacement(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        old_identity=self.run.identity_proof(P,self.op)
        self.replace(fresh,saved)
        self.blocked(lambda:self.run.w.prepare(P,fresh,old_identity),'BINDING')

    def test_published_deny_remains_after_approve_and_replacement_attempt(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        signing=copy.copy(self.run.base);signing.operations={**self.run.operations,P:self.op}
        signing.deny(P,self.op,purpose='EXECUTE')
        signing.deny(P,self.op,purpose='EXECUTE',verdict='APPROVE')
        self.blocked(lambda:self.replace(fresh,saved),'REVIEW_DENY')
        self.assertEqual(self.store.load(self.row['key']),saved)
        self.blocked(lambda:self.prepare(self.op),'REVIEW_DENY')

    def test_acceptance_and_replacement_have_exactly_one_safe_winner(self):
        saved=self.freeze();old=self.prepare(self.op);proof=self.run.accept_proof(P,old['ticket_id'])
        fresh=refresh_short(self.run,self.op);barrier=threading.Barrier(2)
        def run(fn):
            barrier.wait()
            try:return ('ok',fn())
            except ProtocolError as exc:return ('blocked',exc.code)
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(run,lambda:self.run.w.accept(P,old['ticket_id'],proof))
            b=pool.submit(run,lambda:self.replace(fresh,saved))
            results=[a.result(),b.result()]
        self.assertEqual(sum(r[0]=='ok' for r in results),1)
        self.assertIn(next(r[1] for r in results if r[0]=='blocked'),('ALREADY_ACCEPTED','SUBMISSION_SUPERSEDED'))
        if results[1][0]=='ok':self.accept(self.prepare(fresh))
        self.assertEqual(self.run.w.counts()['accepts'],1)

    def test_two_pending_replacements_cannot_both_commit(self):
        saved=self.freeze();packets=[refresh_short(self.run,self.op) for _ in range(2)]
        barrier=threading.Barrier(2)
        def run(op):
            barrier.wait()
            try:self.replace(op,saved);return 'ok'
            except ProtocolError as exc:return exc.code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,packets))
        self.assertCountEqual(results,['ok','SUBMISSION_VERSION_CONFLICT'])

    def test_accepted_packet_never_changes_and_recovery_retains_frozen_core(self):
        from competition.w_cases import public_snapshot
        saved=self.freeze();self.accept(self.prepare(self.op))
        before=public_snapshot(self.run,P,self.op['action']['operation_id'])
        fresh=refresh_short(self.run,self.op)
        self.blocked(lambda:self.replace(fresh,saved),'ALREADY_ACCEPTED')
        returned=self.accept(self.prepare(self.op))
        self.assertEqual({k:returned['acceptance'][k] for k in ('protected','body')},before['acceptance_core'])
        self.assertEqual(self.store.load(self.row['key']),saved)

    def test_bound_entry_rejects_unregistered_signed_action(self):
        raw=self.run.clone(P)
        self.blocked(lambda:self.prepare(raw),'ALLOCATION_UNKNOWN')

    def test_final_time_gate_failure_rolls_back_replacement(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        verify=self.run.w.guard.verify
        def delayed(*args):
            result=verify(*args);time.sleep(2.01);return result
        self.run.w.guard.verify=delayed
        self.blocked(lambda:self.replace(fresh,saved),'CLOCK_UNKNOWN')
        self.assertEqual(self.store.load(self.row['key']),saved)

    def test_revoked_holder_cannot_replace_even_with_previously_signed_packet(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        self.run.base.update_role(P,'H',False)
        self.blocked(lambda:self.replace(fresh,saved),'REVOKED')
        self.assertEqual(self.store.load(self.row['key']),saved)

    def test_original_permit_expiry_cannot_be_extended_by_short_chain(self):
        signing=copy.copy(self.run.base);op=copy.deepcopy(self.op)
        signing.operations={**self.run.operations,P:op}
        exp=int(time.time())+7
        payload={**op['permit']['body']['payload'],'dispatch_before':str(exp)}
        op['permit']=signing.sign(P,'G','Permit',payload,
            refs=op['permit']['body']['refs'],deps=op['deps'],aud=('H','X'),
            iat=int(time.time()),exp=exp)
        op=refresh_short(self.run,op);saved=self.freeze(op)
        candidate=refresh_short(self.run,op)
        time.sleep(max(0,exp-time.time())+.05)
        self.blocked(lambda:self.replace(candidate,saved),'EXPIRED')
        self.assertEqual(self.store.load(self.row['key']),saved)
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_store_binding_cannot_be_disabled_at_public_startup(self):
        from competition.application.request_bound_w import RequestBoundW
        self.blocked(lambda:RequestBoundW(self.run.w,None),'REQUEST_STORE_REQUIRED')

    def test_existing_v1_saved_row_migrates_without_reallocation_or_resigning(self):
        from competition.application.request_store import RequestStore
        saved=self.freeze()
        with self.run.store.tx() as c:
            c.execute('ALTER TABLE app_request DROP COLUMN submission_history')
            c.execute('ALTER TABLE app_request DROP COLUMN submission_version')
        restored=RequestStore(self.run.store)
        self.assertEqual(restored.load(self.row['key']),saved)
        self.assertEqual(self.accept(self.prepare(self.op))['acceptance_state'],'COMMITTED')

    def test_published_deny_races_replacement_but_cannot_be_lost_before_acceptance(self):
        saved=self.freeze();fresh=refresh_short(self.run,self.op)
        signing=copy.copy(self.run.base);signing.operations={**self.run.operations,P:self.op}
        from competition.support.wire import msgref, sortset
        rr=sortset([msgref(r) for r in self.op['reviews']])
        message=signing.sign(P,'U','Authorization',{'ctx':self.op['ctx'],'review_refs':rr,
            'purpose':'EXECUTE','verdict':'DENY'},deps=self.op['deps'],refs=rr)
        barrier=threading.Barrier(2)
        def save():
            barrier.wait()
            try:self.replace(fresh,saved);return 'saved'
            except ProtocolError as exc:return exc.code
        def deny():
            barrier.wait();return self.run.base.service.publish_review(P,message)
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(save);b=pool.submit(deny);outcome=a.result();published=b.result()
        self.assertIn(outcome,('saved','REVIEW_DENY'))
        self.blocked(lambda:self.prepare(self.store.load(self.row['key'])['op']),'REVIEW_DENY')
        self.assertEqual(self.run.w.counts()['accepts'],0)

    def test_renewed_packet_lost_tool_ack_recovers_same_attempt_and_one_effect(self):
        from competition.w_cases import lost_ack
        saved=self.freeze();fresh=refresh_short(self.run,self.op);self.replace(fresh,saved)
        self.run.operations[P]=fresh
        result=lost_ack(self.run,P)
        self.assertEqual(result['lost_ack']['trace']['exit_code'],98)
        self.assertEqual(result['persisted_fact_id'],result['query_fact_id'])
        counts=self.run.w.counts()
        self.assertEqual((counts['accepts'],counts['attempts'],counts['exec_invocations'],
            result['effect_count'],counts['settlements']),(1,1,1,1,1))
