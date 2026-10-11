"""Actual multi-profile authorization behavior, not parser-only or full delivery."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from research.reference_executor.wire import ProtocolError, canonical, b64, digest, msgref, raw, strict_verify
from competition.core.trusted_state import PROFILE_SCOPES, prefix, enc, ROLES


class CommonAuthorizationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.seed_module = importlib.import_module('competition.profiles.authorization_seed')
        except ModuleNotFoundError:
            self.fail('Missing common trusted authorization initialization/path')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.seed = self.seed_module.initialize(Path(self.folder.name))
        self.addCleanup(self.seed.close)

    def test_three_complete_signed_chains_use_the_common_gate(self):
        for profile, required in [('IND-DEMO-1', ['QUALITY_REVIEW']), ('PAY-1', ['ANOMALY']), ('MED-DEMO-1', ['CLINICAL_REVIEW'])]:
            with self.subTest(profile=profile):
                op = self.seed.operations[profile]
                result = self.seed.service.guard(profile, op, self.seed.identity_proof(profile, op))
                self.assertEqual(result['decision'], 'T')
                self.assertEqual(result['required_reviews'], required)
                self.assertEqual(result['deny_witness']['refs'], [])
                self.assertEqual(result['deny_witness']['revision'], 1)

    def test_signed_permit_cannot_omit_independently_required_dependency(self):
        for profile in self.seed.operations:
            with self.subTest(profile=profile):
                op = self.seed.clone(profile)
                op['permit']['body']['deps'] = op['permit']['body']['deps'][1:]
                self.seed.resign_chain(profile, op)
                with self.assertRaises(ProtocolError):
                    self.seed.service.guard(profile, op, self.seed.identity_proof(profile, op))
                self.assertEqual(self.seed.service.counts()['guard_commits'], 0)

    def test_omitted_review_with_other_legitimate_signatures_is_rejected(self):
        for profile in self.seed.operations:
            with self.subTest(profile=profile):
                op = self.seed.clone(profile)
                op['reviews'] = []
                self.seed.resign_chain(profile, op)
                with self.assertRaises(ProtocolError):
                    self.seed.service.guard(profile, op, self.seed.identity_proof(profile, op))
                self.assertEqual(self.seed.service.counts()['guard_commits'], 0)

    def reject(self, profile, op, code=None):
        before=self.seed.service.counts()['guard_commits']
        with self.assertRaises(ProtocolError) as cm:
            self.seed.service.guard(profile,op,self.seed.identity_proof(profile,op))
        if code: self.assertEqual(cm.exception.code,code)
        self.assertEqual(self.seed.service.counts()['guard_commits'],before)

    def test_published_deny_is_not_bypassed_by_omission_or_later_approval(self):
        for profile,op in self.seed.operations.items():
            deny,fact=self.seed.deny(profile,op)
            self.assertNotIn(msgref(deny),op['proof']['body']['refs'])
            self.assertEqual(fact['revision'],2)
            self.reject(profile,op,'REVIEW_DENY')
            self.seed.deny(profile,op,verdict='APPROVE')
            self.reject(profile,op,'REVIEW_DENY')
            with self.seed.store.tx() as c:
                witness=self.seed.store.deny_witness(c,profile,op['ctx'],op['required'])
            self.assertEqual(witness['revision'],3)
            self.assertEqual(witness['refs'],[msgref(deny)])

    def test_missing_coverage_is_unknown_even_with_valid_all_approvals(self):
        for profile,op in self.seed.operations.items():
            with self.seed.store.tx() as c:
                c.execute('DELETE FROM a_deny_range WHERE profile=?',(profile,))
            self.reject(profile,op,'DENY_COVERAGE_UNKNOWN')

    def test_legitimate_key_signature_cannot_claim_a_different_subject(self):
        for profile in self.seed.operations:
            op=self.seed.clone(profile); message=op['issue']
            message['protected']['issuer']='unregistered-holder'
            message['sig']=b64(self.seed.actors[profile]['H'].key.sign(canonical(['ZJJ-SIG-v1',message['protected'],message['body']])))
            strict_verify(self.seed.actors[profile]['H'].pub,raw(message['sig'],64),canonical(['ZJJ-SIG-v1',message['protected'],message['body']]))
            self.reject(profile,op,'MESSAGE_BINDING')

    def test_authenticated_current_source_revision_invalidates_frozen_basis(self):
        for profile,op in self.seed.operations.items():
            ns='ORDER' if profile=='PAY-1' else 'EVIDENCE'; key=prefix(profile)+[op['action']['payload']['order_id'],op['action']['payload']['stage']] if profile=='PAY-1' else op['scene_key']
            with self.seed.store.db() as c: row=self.seed.store.current(c,profile,ns,key)
            if profile!='PAY-1':
                evidence=row['record']; data=evidence['value']['data']; data['evidence_revision']='2'
                if profile=='MED-DEMO-1':
                    data['record_revision']='2'
                att=evidence['value']['attestation']; header={k:att[k] for k in ('issuer','kid','iat','exp')}
                att['sig']=b64(self.seed.actors[profile]['E'].key.sign(canonical(['ZJJ-SOURCE-v1','2.6',profile,evidence['kind'],evidence['scope'],data,header])))
            self.seed.publish(profile,ns,key,row['record'])
            self.reject(profile,op)

    def test_current_role_revoke_and_regrant_cannot_revalidate_old_deps(self):
        for profile,op in self.seed.operations.items():
            self.seed.update_role(profile,'U',False)
            self.reject(profile,op,'REVOKED')
            self.seed.update_role(profile,'U',True)
            self.reject(profile,op)

    def test_med_acl_checked_before_detail_source_and_candidate_callback(self):
        profile='MED-DEMO-1'; op=self.seed.operations[profile]; seen=[]
        result=self.seed.service.read(profile,op,self.seed.identity_proof(profile,op,'CANDIDATE'),stage='CANDIDATE',candidate=lambda data: seen.append(data) or data)
        self.assertEqual(len(seen),1); self.assertTrue(result['records'])
        self.assertEqual(result['view_kind'],'CROPPED_APPLICATION_PROJECTION'); self.assertFalse(result['original_envelope'])
        with self.seed.store.db() as c: policy=self.seed.store.current(c,profile,'POLICY',prefix(profile))['record']
        policy['value']['readers'].remove(self.seed.actors[profile]['H'].name)
        self.seed.publish(profile,'POLICY',prefix(profile),policy)
        adapter=self.seed.service.verifier.adapters[profile]
        original=adapter.derive
        adapter.derive=lambda *args: self.fail('Source derive ran before current medical read ACL')
        try:
            for stage in ('DETAIL','CANDIDATE'):
                with self.assertRaises(ProtocolError) as cm:
                    self.seed.service.read(profile,op,self.seed.identity_proof(profile,op,stage),stage=stage,candidate=(lambda data: seen.append(data)) if stage=='CANDIDATE' else None)
                self.assertEqual(cm.exception.code,'NO_ROLE')
            self.assertEqual(len(seen),1)
        finally: adapter.derive=original

    def test_valid_review_can_be_restored_after_missing_review_rejection(self):
        profile='MED-DEMO-1'; original=self.seed.operations[profile]; op=self.seed.clone(profile)
        op['reviews']=[]; self.seed.resign_chain(profile,op); self.reject(profile,op,'REVIEW_REQUIRED')
        op['reviews']=original['reviews']; self.seed.resign_chain(profile,op)
        result=self.seed.service.guard(profile,op,self.seed.identity_proof(profile,op))
        self.assertEqual(result['decision'],'T')

    def test_publication_corruption_cannot_turn_deny_coverage_into_empty(self):
        profile='MED-DEMO-1'; op=self.seed.operations[profile]; msg,_=self.seed.deny(profile,op)
        with self.seed.store.tx() as c:
            c.execute("UPDATE a_publication SET verdict='APPROVE' WHERE profile=?",(profile,))
        self.reject(profile,op,'DENY_COVERAGE_UNKNOWN')

    def test_three_profile_broker_and_core_reject_wrong_scope_kid_profile_and_purpose(self):
        import copy
        for profile in self.seed.operations:
            for field,value in [('issuer','other'),('kid',digest(['other'])),('profile','PAY-1' if profile!='PAY-1' else 'MED-DEMO-1'),('type','Permit')]:
                op=self.seed.clone(profile); msg=op['issue']; msg['protected'][field]=value
                msg['sig']=b64(self.seed.actors[profile]['H'].key.sign(canonical(['ZJJ-SIG-v1',msg['protected'],msg['body']])))
                self.reject(profile,op)
            op=self.seed.clone(profile); op['issue']['body']['scope']['tenant']='different-tenant'
            op['issue']['sig']=b64(self.seed.actors[profile]['H'].key.sign(canonical(['ZJJ-SIG-v1',op['issue']['protected'],op['issue']['body']])))
            self.reject(profile,op)
            msg=copy.deepcopy(self.seed.operations[profile]['issue']); msg.pop('sig')
            for alias in ('G','U','V','E'):
                with self.assertRaises(ProtocolError):self.seed.broker.sign(profile,alias,msg,op['action'])

    def test_current_business_limit_is_checked_after_valid_chain_was_signed(self):
        for profile,op in self.seed.operations.items():
            who=self.seed.actors[profile]['U']; key=prefix(profile)+[who.name,ROLES[profile]['U']]
            with self.seed.store.db() as c: row=self.seed.store.current(c,profile,'ROLE',key)
            record=row['record']; record['value']['epoch']=str(row['revision']+1)
            constraints=record['value']['constraints']
            if profile=='PAY-1':constraints['max_amount_minor']='1'
            elif profile=='IND-DEMO-1':constraints['line_set']=['different-line']
            else:constraints['patient_set']=['different-patient']
            self.seed.publish(profile,'ROLE',key,record)
            self.reject(profile,op,'NO_ROLE')

    def test_actual_bad_signature_is_rejected(self):
        for profile in self.seed.operations:
            op=self.seed.clone(profile); op['authorization']['sig']=b64(bytes(64))
            self.reject(profile,op)

    def test_subject_separation_uses_subject_and_allows_holder_authorizer_overlap(self):
        folder=Path(self.folder.name)/'overlap'
        names={(p,a):'shared-'+p.lower() for p in PROFILE_SCOPES for a in ('H','U')}
        shared=self.seed_module.initialize(folder,names=names); self.addCleanup(shared.close)
        for p,op in shared.operations.items():
            self.assertNotEqual(shared.actors[p]['H'].kid,shared.actors[p]['U'].kid)
            self.assertEqual(shared.service.guard(p,op,shared.identity_proof(p,op))['decision'],'T')
        names={('PAY-1','G'):'same-pay-subject',('PAY-1','U'):'same-pay-subject'}
        with self.assertRaises(ProtocolError) as cm:
            self.seed_module.initialize(Path(self.folder.name)/'collision',names=names)
        self.assertEqual(cm.exception.code,'SUBJECT_SEPARATION')
        for p in PROFILE_SCOPES:
            with self.assertRaises(ProtocolError) as cm:
                self.seed_module.initialize(Path(self.folder.name)/('collision-v-'+p),names={(p,'U'):'same-approval-subject',(p,'V'):'same-approval-subject'})
            self.assertEqual(cm.exception.code,'SUBJECT_SEPARATION')

    def test_source_current_business_scope_cannot_be_hidden_by_rebased_valid_chain(self):
        for p in ('IND-DEMO-1','MED-DEMO-1'):
            op=self.seed.clone(p);who=self.seed.actors[p]['E'];key=prefix(p)+[who.name,'SOURCE']
            with self.seed.store.db() as c:row=self.seed.store.current(c,p,'ROLE',key)
            record=row['record'];record['value']['epoch']=str(row['revision']+1)
            record['value']['constraints']['line_set' if p=='IND-DEMO-1' else 'patient_set']=['different-business-object']
            self.seed.publish(p,'ROLE',key,record)
            with self.seed.store.tx() as c:
                event=self.seed.store.event(c,p,op['action']['operation_id'],'AUTHZ_GUARD','')
                with self.assertRaises(ProtocolError) as cm:self.seed.service.verifier.adapters[p].derive(c,op,event)
            self.assertEqual(cm.exception.code,'NO_ROLE')

    def test_broker_checked_action_must_bind_signed_payload_context(self):
        import copy
        from research.reference_executor.wire import action_hash
        for p,op in self.seed.operations.items():
            msg=copy.deepcopy(op['authorization']);msg.pop('sig')
            msg['body']['payload']['ctx']['action_hash']=digest(['different-business-action'])
            with self.assertRaises(ProtocolError) as cm:self.seed.broker.sign(p,'U',msg,op['action'])
            self.assertEqual(cm.exception.code,'BROKER_ACTION_BINDING')

    def test_ind_without_review_does_not_require_independent_v_subject(self):
        p='IND-DEMO-1'
        run=self.seed_module.initialize(Path(self.folder.name)/'no-review-overlap',ind_label='DEMO_NORMAL',names={(p,'U'):'same-optional-subject',(p,'V'):'same-optional-subject'})
        self.addCleanup(run.close);op=run.operations[p]
        self.assertEqual(op['required'],[])
        self.assertEqual(run.service.guard(p,op,run.identity_proof(p,op))['decision'],'T')


if __name__ == '__main__':
    unittest.main()
