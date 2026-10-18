"""Public role boundary: transport access alone never grants H/worker authority."""
import copy
import importlib
import time
from competition.tests.renewal_fixtures import RenewalCase, refresh_short, P
from competition.support.wire import b64, canonical

class OperationServiceTests(RenewalCase):
    def service(self):
        module=importlib.import_module('competition.application.operation_service')
        return module.OperationService(self.resolver,self.flow)

    def proof(self, claim, alias='H'):
        return {'claim':claim,'signature':b64(self.run.actors[P][alias].key.sign(
            canonical(['ZJJ-APP-RECOVER-v1',claim])))}

    def recover(self, service, key=None):
        key=key or self.row['key']
        cl=service.invoke('recover_challenge',{'key':key})
        return service.invoke('recover',{'key':key,'proof':self.proof(cl)})

    def test_transport_caller_cannot_read_saved_approval_without_holder_proof(self):
        self.freeze();service=self.service();cl=service.invoke('recover_challenge',{'key':self.row['key']})
        self.blocked(lambda:service.invoke('recover',{'key':self.row['key'],'proof':self.proof(cl,'U')}),'BAD_SIGNATURE')
        got=service.invoke('recover',{'key':self.row['key'],'proof':self.proof(cl)})
        self.assertEqual(got['submission']['op'],self.op)
        self.assertEqual(got['state'],'NOT_ACCEPTED')
        self.blocked(lambda:service.invoke('recover',{'key':self.row['key'],'proof':self.proof(cl)}),'REPLAY')

    def test_internal_mutators_signer_and_worker_are_not_public_methods(self):
        service=self.service()
        for method in ('load','save_submission','replace_pending','complete_receipt','execute_once',
                       'query_attempt','claim','settle','sign','publish','register_resource','__dict__'):
            self.blocked(lambda:service.invoke(method,{}),'METHOD_NOT_ALLOWED')

    def test_submit_requires_full_packet_identity_and_version_binding(self):
        service=self.service()
        params={'key':self.row['key'],'op':self.op,'identity':None,
                'expected_version':'0','expected_ref':''}
        self.blocked(lambda:service.invoke('submit',params),'IDENTITY_REQUIRED')
        params['identity']=self.run.identity_proof(P,self.op)
        first=service.invoke('submit',params)
        fresh=refresh_short(self.run,self.op)
        params.update(op=fresh,identity=self.run.identity_proof(P,fresh),
                      expected_version='1',expected_ref=first['request_ref'])
        second=service.invoke('submit',params)
        self.assertEqual(second['version'],2)
        self.assertEqual(self.recover(service)['submission'],second)

    def test_recovery_checks_current_reader_credential_after_acceptance(self):
        service=self.service();self.freeze();self.accept(self.prepare(self.op))
        cl=service.invoke('recover_challenge',{'key':self.row['key']})
        self.run.base.update_role(P,'H',False)
        self.blocked(lambda:service.invoke('recover',{'key':self.row['key'],'proof':self.proof(cl)}),'REVOKED')

    def test_approval_pending_and_committed_receipt_pending_are_distinct(self):
        service=self.service()
        self.assertEqual(self.recover(service)['state'],'APPROVAL_PENDING')
        self.freeze();self.run.x_signers[P].close()
        accepted=self.accept(self.prepare(self.op))
        self.assertEqual(accepted['receipt_state'],'PENDING')
        view=self.recover(service)
        self.assertEqual(view['state'],'COMMITTED')
        self.assertEqual(view['operation']['receipt_state'],'PENDING')
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_public_prepare_and_accept_use_original_holder_authentication(self):
        service=self.service();self.freeze()
        ticket=service.invoke('prepare',{'key':self.row['key'],'identity':self.run.identity_proof(P,self.op)})
        cl=service.invoke('accept_challenge',{'ticket_id':ticket['ticket_id']})
        proof={'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical(['COMP-APP-ACCEPT-v1',cl])))}
        result=service.invoke('accept',{'ticket_id':ticket['ticket_id'],'proof':proof})
        self.assertEqual(result['acceptance_state'],'COMMITTED')
        view=self.recover(service)
        self.assertEqual(view['operation']['acceptance'],result['acceptance'])
        self.assertEqual(self.run.w.counts()['attempts'],0)

    def test_extra_transport_fields_and_arbitrary_profiles_are_rejected(self):
        service=self.service()
        self.blocked(lambda:service.invoke('propose',{'proposal':self.proposal,'auth':self.auth(self.proposal),'profile':'PAY-1'}),'SERVICE_FIELDS')
        self.blocked(lambda:service.invoke('prepare',{'key':self.row['key'],'identity':None,'auto_approve':True}),'SERVICE_FIELDS')

    def test_identity_expiry_during_first_freeze_cannot_mutate_submission(self):
        service=self.service();identity=self.run.identity_proof(P,self.op)
        expiry=int(time.time())+1
        with self.run.store.tx() as c:
            c.execute('UPDATE a_identity SET expires=? WHERE nonce=?',(expiry,identity['claim']['nonce']))
        verify=self.run.w.guard.verify
        def delayed(*args):
            result=verify(*args);time.sleep(max(0,expiry-time.time())+.02);return result
        self.run.w.guard.verify=delayed
        self.blocked(lambda:service.invoke('submit',{'key':self.row['key'],'op':self.op,
            'identity':identity,'expected_version':'0','expected_ref':''}))
        self.blocked(lambda:self.store.load(self.row['key']),'APPROVAL_PENDING')

    def test_identity_expiry_during_replacement_rolls_back_version_and_nonce(self):
        service=self.service();saved=self.freeze();fresh=refresh_short(self.run,self.op)
        identity=self.run.identity_proof(P,fresh);expiry=int(time.time())+1
        with self.run.store.tx() as c:
            c.execute('UPDATE a_identity SET expires=? WHERE nonce=?',(expiry,identity['claim']['nonce']))
        verify=self.run.w.guard.verify
        def delayed(*args):
            result=verify(*args);time.sleep(max(0,expiry-time.time())+.02);return result
        self.run.w.guard.verify=delayed
        self.blocked(lambda:service.invoke('submit',{'key':self.row['key'],'op':fresh,
            'identity':identity,'expected_version':'1','expected_ref':saved['request_ref']}))
        self.assertEqual(self.store.load(self.row['key']),saved)
        with self.run.store.db() as c:
            self.assertEqual(c.execute('SELECT used FROM a_identity WHERE nonce=?',
                (identity['claim']['nonce'],)).fetchone()[0],0)

    def test_expired_short_packet_retry_acknowledges_same_version_without_new_submission(self):
        service=self.service();op=refresh_short(self.run,self.op,expires=int(time.time())+5)
        saved=self.freeze(op)
        with self.run.store.db() as c:
            before=c.execute("SELECT count(*) FROM a_journal WHERE kind='APP_SUBMISSION'").fetchone()[0]
        time.sleep(max(0,int(op['proof']['body']['exp'])-time.time())+.02)
        for version,ref in (('1',saved['request_ref']),('0','')):
            result=service.invoke('submit',{'key':self.row['key'],'op':op,
                'identity':self.run.identity_proof(P,op),'expected_version':version,'expected_ref':ref})
            self.assertEqual(result,saved)
        with self.run.store.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM a_journal WHERE kind='APP_SUBMISSION'").fetchone()[0],before)
        self.assertEqual(self.run.w.counts()['accepts'],0)
