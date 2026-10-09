"""End-to-end lab traces (not production / official full conformance)."""
import copy, unittest
from concurrent.futures import ThreadPoolExecutor
from research.reference_executor.wire import ProtocolError, rec_ref, msgref, canonical, b64, digest
from research.strict_v26.test_pay_history import case
from .flow import SignedPayFlow, check_record_contract

class Phase4PayFlow(unittest.TestCase):
    def ready(self,ca=None):
        f=SignedPayFlow(cases=ca);op=f.prepare()
        for purpose in op.required:f.review(op,purpose=purpose)
        f.authorize(op)
        f.issue(op)
        f.challenge(op)
        return f,op
    def accepted(self,ca=None):
        f,op=self.ready(ca);f.commit(op);return f,op
    def reject(self,code,fn,*args):
        with self.assertRaises(ProtocolError) as cm:fn(*args)
        self.assertEqual(cm.exception.code,code)

    def test_issue_and_commit_have_signed_result_objects(self):
        f,o=self.accepted()
        self.assertEqual(f.issue_result['body']['payload']['result'],'ISSUED')
        self.assertEqual(f.commit_result['body']['payload']['result'],'ACCEPTED')
        self.assertEqual(f.commit_result['body']['payload']['acceptance_ref'],msgref(o.acceptance))
        self.assertEqual(f.commit_result['body']['payload']['status_seq'],'1')
        self.assertTrue(f.verify_archive(o))
    def test_8_way_same_proof_only_one_acceptance(self):
        f,o=self.ready();proof=f.make_proof(o)
        def call(_):
            try:f.commit(o,proof);return 'ACCEPTED'
            except ProtocolError as e:return e.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(call,range(8)))
        self.assertEqual(results.count('ACCEPTED'),8)  # 1 fresh + 7 idempotent receipts
        self.assertEqual((f.sequence,f.reserved),(1,2000))
    def test_result_signature_tampering_detected(self):
        f,o=self.accepted()
        r=f.commit_result
        r['body']['payload']['status_seq']='2'
        with self.assertRaises(ProtocolError):f._verified(r,'Result','X')
    def test_current_authority_record_swap_detected(self):
        f,o=self.ready()
        current=f.trusted.current('EXPERIENCE',list(f.basekey())+['main'])
        forged=copy.deepcopy(current.record)
        forged['value']['cases']=[]
        f.trusted._rows[('EXPERIENCE',tuple(list(f.basekey())+['main']))]=type(current)(
            1,rec_ref(forged),forged['value'],forged,True)
        self.reject('STALE_AUTHORITY',f._bind_current_records)
        self.reject('DEP_CONFLICT',f.commit,o)
        self.assertEqual(f.reserved,0)
    def test_reviewer_has_explicit_source_read_access(self):
        f=SignedPayFlow()
        policy=f.source['policy_record']['value']
        original=f.source['evidence_record']['value']['source_envelope']['body']['aud']
        self.assertIn(f.idents['V'].name,policy['readers'])
        self.assertIn(f.idents['V'].name,original)
    def test_pay_clear_full_signed_acceptance(self):
        f,o=self.accepted();self.assertEqual(o.status,'ACCEPTED')
        self.assertEqual(o.required,())
        self.assertEqual(o.acceptance['body']['payload']['commit_record_ref'],rec_ref(f.commit_record))
        self.assertTrue(f.verify_archive(o));self.assertEqual(f.reserved,2000)
    def test_pay_flag_requires_anomaly_review(self):
        ca=[case(i,action_class='HOLD' if i<=4 else 'PAY') for i in range(1,6)]
        f,o=self.accepted(ca);self.assertEqual(o.required,('ANOMALY',))
        self.assertEqual(len(o.reviews),1);self.assertTrue(f.verify_archive(o))
    def test_pay_insufficient_requires_low_evidence_review(self):
        f,o=self.accepted([case(1),case(2)])
        self.assertEqual(o.required,('LOW_EVIDENCE',));self.assertEqual(len(o.reviews),1)
    def test_missing_required_review_rejected(self):
        f=SignedPayFlow(cases=[case(1),case(2)]);o=f.prepare()
        self.reject('REVIEW_REQUIRED',f.authorize,o)
    def test_deny_published_prevents_issue(self):
        f=SignedPayFlow(cases=[case(1),case(2)]);o=f.prepare()
        f.review(o,'DENY',purpose='LOW_EVIDENCE')
        f.review(o,'APPROVE',purpose='LOW_EVIDENCE')
        f.authorize(o)
        self.reject('REVIEW_DENY',f.issue,o)
    def test_wrong_review_purpose_rejected(self):
        f=SignedPayFlow(cases=[case(1),case(2)]);o=f.prepare()
        f.review(o,purpose='ANOMALY');f.authorize(o)
        self.reject('REVIEW_PURPOSE',f.issue,o)
    def test_tampered_authorization_signature_rejected(self):
        f,o=self.ready();o.authorization['sig']=b64(bytes(64))
        self.reject('SIGNATURE_ENCODING',f.commit,o)
    def test_signature_valid_missing_permit_dep_rejected(self):
        f,o=self.ready()
        env=o.permit
        env['body']['deps']=env['body']['deps'][1:]
        env['sig']=b64(f.idents['G'].key.sign(canonical(['ZJJ-SIG-v1',env['protected'],env['body']])))
        self.reject('DEP_CONFLICT',f.commit,o)
        self.assertEqual(f.reserved,0)
    def test_revoked_authorization_role_rejected(self):
        f,o=self.ready()
        f.trusted.remove('ROLE',list(f.basekey())+[f.idents['U'].name,'FINANCE'])
        self.reject('REVOKED',f.commit,o)
        self.assertEqual(f.reserved,0)
    def test_revision_mutation_invalidates_old_basis(self):
        f,o=self.ready()
        prefix=list(f.basekey());v=f.trusted.current('BEHAVIOR',prefix+['payer']).value
        f.trusted.publish_state('BEHAVIOR',prefix+['payer'],2,copy.deepcopy(v))
        self.reject('DEP_CONFLICT',f.commit,o)
    def test_resigned_authoritative_source_hard_false_blocks_prepare(self):
        f=SignedPayFlow();ev=f.source['evidence_record']
        src=ev['value']['source_envelope'];src['body']['payload']['unsettled']=False
        src['body']['payload']['order_revision']='2'
        src['sig']=b64(f.idents['E'].key.sign(canonical(['ZJJ-SIG-v1',src['protected'],src['body']])))
        ev['value']['source_ref']=digest(['ZJJ-OBJ-v1',src['protected'],src['body']])
        key=list(f.basekey())+['ord','pay']
        f.trusted.publish_record('ORDER',key,2,ev,'PAY_EVIDENCE')
        self.reject('CLAIM_FALSE',f.prepare)
        self.assertEqual((f.reserved,f.sequence),(0,0))
    def test_prepared_basis_replaced_causes_reject(self):
        f,o=self.ready();o.basis['value']['action_hash']='bogus'
        self.reject('BASIS_REF',f.commit,o)
    def test_commit_proof_binding_rejected(self):
        f,o=self.ready();p=f.make_proof(o);p['body']['payload']['nonce']='bad'
        p['sig']=b64(f.idents['H'].key.sign(canonical(['ZJJ-SIG-v1',p['protected'],p['body']])))
        self.reject('BINDING',f.commit,o,p)
    def test_wrong_acceptance_signature_detected(self):
        f,o=self.accepted();o.acceptance['sig']=b64(bytes(64))
        with self.assertRaises(ProtocolError):f.verify_archive(o)
    def test_archive_commit_mutation_detected(self):
        f,o=self.accepted();f.commit_record['value']['reservation_plan'][0]['reserved_after']='100'
        self.reject('COMMIT_REF',f.verify_archive,o)
    def test_same_proof_retransmission_returns_original_acceptance(self):
        f,o=self.accepted()
        original=canonical(o.acceptance)
        self.assertEqual(canonical(f.commit(o,copy.deepcopy(o.proof))),original)
        self.assertEqual((f.reserved,f.sequence),(2000,1))
    def test_changed_proof_same_nonce_replay_rejected(self):
        f,o=self.accepted()
        bad=copy.deepcopy(o.proof)
        bad['body']['id']=f.newid()
        bad['sig']=b64(f.idents['H'].key.sign(canonical(['ZJJ-SIG-v1',bad['protected'],bad['body']])))
        self.reject('REPLAY',f.commit,o,bad)
        self.assertEqual((f.reserved,f.sequence),(2000,1))
    def test_dispatch_rejects_current_dep_staleness(self):
        f,o=self.accepted();s=f.trusted;key=list(f.basekey())+['ord','pay']
        old=s.current('ORDER',key);s._set('ORDER',key,2,old.ref,old.value,old.record)
        self.reject('STALE',f.claim,o)
    def test_dispatch_allows_only_acceptance_own_behavior_change(self):
        f,o=self.accepted();self.assertEqual(f.claim(o),o.dispatch_attempt)
        self.assertEqual(o.calls,1)
    def test_reservation_ownership_violation_blocks_claim(self):
        f,o=self.accepted();f.taskflight.pop(o.task_id)
        self.reject('RESERVATION',f.claim,o)
    def test_success_final_settles_amount_exactly(self):
        f,o=self.accepted();f.claim(o)
        result=f.receive_final(o,f.certify_fact(o,f.tool_fact(o)))
        self.assertEqual(result,'SETTLED');self.assertEqual((f.reserved,f.spent,o.settlements),(0,2000,1))
    def test_reauthenticated_same_final_no_double_settlement(self):
        f,o=self.accepted();f.claim(o);fact=f.tool_fact(o)
        self.assertEqual(f.receive_final(o,f.certify_fact(o,fact)),'SETTLED')
        f.now+=1;f.rotate_tool(36,continuity_verified=True)
        self.assertEqual(f.receive_final(o,f.certify_fact(o,fact)),'EXISTING')
        self.assertEqual((f.reserved,f.spent,o.settlements),(0,2000,1))
    def test_failed_confirmed_releases_not_spend(self):
        f,o=self.accepted();f.claim(o)
        f.receive_final(o,f.certify_fact(o,f.tool_fact(o,'FAILED_CONFIRMED')))
        self.assertEqual((f.reserved,f.spent),(0,0))
    def test_cancel_pending_releases_full_amount(self):
        f,o=self.accepted();f.cancel_pending(o)
        self.assertEqual((f.reserved,f.spent),(0,0))
        self.reject('NO_REDISPATCH',f.claim,o)
    def test_aborted_commit_not_consume_or_reserve(self):
        f,o=self.ready();o.permit['body']['payload']['ctx']['operation_id']='invalid'
        self.reject('BAD_SIGNATURE',f.commit,o)
        self.assertEqual((f.reserved,f.sequence,o.nonce_consumed),(0,0,False))
    def test_action_tampering_before_issue_rejected(self):
        f,o=self.ready();o.action['payload']['amount_minor']='9999'
        with self.assertRaises(ProtocolError):f.commit(o)
    def test_time_expiry_rejects_commit(self):
        f,o=self.ready();f.now=400
        self.reject('EXPIRED',f.commit,o)
    def test_acceptance_record_contract_exact(self):
        f,o=self.accepted();v=f.commit_record
        self.assertEqual(len(v['value']),19)
        self.assertTrue(check_record_contract(v,'COMMIT',f.scope))
    def test_wrong_resource_witness_rejected(self):
        f,o=self.accepted();bad=copy.deepcopy(f.commit_record)
        bad['value']['reservation_plan'][0]['extra']='bad'
        self.reject('RESOURCE_WITNESS',check_record_contract,bad,'COMMIT',f.scope)
    def test_credential_witness_exact(self):
        f,o=self.accepted();self.assertEqual(len(f.commit_record['value']['credential_witnesses']),5)
        self.assertEqual({r['role'] for r in f.commit_record['value']['credential_witnesses']},
                {'HOLDER','SOURCE','ISSUER','EXECUTOR','FINANCE'})
    def test_expired_permit_no_dispatch(self):
        f,o=self.accepted();f.now=230
        self.reject('EXPIRED',f.claim,o)
    def test_status_query_read_only(self):
        f,o=self.accepted();before=(f.sequence,f.reserved,o.calls)
        self.assertEqual(f.status_query(o),'ACCEPTED')
        self.assertEqual(before,(f.sequence,f.reserved,o.calls))

if __name__=='__main__':unittest.main()
