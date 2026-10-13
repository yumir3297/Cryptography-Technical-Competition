"""Regression tests for authenticated contest semantics and signer requests."""
import copy
import tempfile
import unittest
from pathlib import Path
from competition.profiles.authorization_seed import initialize
from competition.support.wire import b64, canonical, ProtocolError, strict_verify, raw

class RectificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = initialize(Path(self.tmp.name))
        self.addCleanup(self.run.close)
        self.p = 'PAY-1'
        self.op = self.run.clone(self.p)
        self.unsigned = copy.deepcopy(self.op['authorization'])
        self.unsigned.pop('sig')

    def proof(self, alias='U', signer='U'):
        cl = self.run.broker.challenge(self.p, alias, self.unsigned, self.op['action'])
        return {'claim':cl, 'signature':b64(self.run.actors[self.p][signer].key.sign(canonical(['COMP-APP-SIGN-CALL-v1',cl])))}

    def test_wire_variant_is_signed_and_original_r2_rejected(self):
        for p, original in self.run.operations.items():
            self.assertEqual(original['authorization']['protected']['proto'], 'ZJJ-CORE-COMP-1')
            op=self.run.clone(p)
            msg=op['authorization'];msg['protected']['proto']='ZJJ-AAP'
            msg['sig']=b64(self.run.actors[p]['U'].key.sign(canonical(['ZJJ-SIG-v1',msg['protected'],msg['body']])))
            strict_verify(self.run.actors[p]['U'].pub,raw(msg['sig'],64),canonical(['ZJJ-SIG-v1',msg['protected'],msg['body']]))
            with self.assertRaises(ProtocolError):
                self.run.service.guard(p,op,self.run.identity_proof(p,op))

    def test_signer_requires_authenticated_caller(self):
        with self.assertRaises(ProtocolError) as cm:
            self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'])
        self.assertEqual(cm.exception.code,'SIGN_CALLER_REQUIRED')

    def test_holder_cannot_request_authorizer_signature(self):
        proof=self.proof(signer='H')
        with self.assertRaises(ProtocolError):
            self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'],caller_proof=proof)

    def test_sign_request_is_single_use_and_content_bound(self):
        proof=self.proof()
        changed=copy.deepcopy(self.unsigned);changed['body']['payload']['verdict']='DENY'
        with self.assertRaises(ProtocolError):
            self.run.broker.sign(self.p,'U',changed,self.op['action'],caller_proof=proof)
        msg=self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'],caller_proof=proof)
        self.assertEqual(msg['body'],self.unsigned['body'])
        with self.assertRaises(ProtocolError) as cm:
            self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'],caller_proof=proof)
        self.assertEqual(cm.exception.code,'SIGN_CALLER_REPLAY')

    def test_revocation_after_challenge_still_prevents_signing(self):
        proof=self.proof()
        self.run.update_role(self.p,'U',False)
        with self.assertRaises(ProtocolError) as cm:
            self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'],caller_proof=proof)
        self.assertEqual(cm.exception.code,'REVOKED')

    def test_malformed_sign_requests_have_protocol_errors(self):
        for unsigned,action in [({},self.op['action']),(self.unsigned,{}),(None,self.op['action'])]:
            with self.subTest(unsigned=unsigned),self.assertRaises(ProtocolError):
                self.run.broker.sign(self.p,'U',unsigned,action)
        with self.assertRaises(ProtocolError):
            self.run.broker.challenge(self.p,'U',self.unsigned,{})


    def test_signing_delay_cannot_return_signature_after_caller_expiry(self):
        import time
        from unittest.mock import patch
        proof=self.proof()
        expires=int(time.time())+3
        with self.run.store.tx() as c:
            c.execute('UPDATE a_sign_call SET expires=? WHERE nonce=?',(expires,proof['claim']['nonce']))
        credential=self.run.store.credential
        def delayed(*args,**kwargs):
            result=credential(*args,**kwargs)
            time.sleep(max(0,expires-time.time())+.05)
            return result
        with patch.object(self.run.store,'credential',delayed),self.assertRaises(ProtocolError) as cm:
            self.run.broker.sign(self.p,'U',self.unsigned,self.op['action'],caller_proof=proof)
        self.assertIn(cm.exception.code,('CLOCK_UNKNOWN','EXPIRED'))
        with self.run.store.db() as c:
            self.assertEqual(c.execute('SELECT used FROM a_sign_call WHERE nonce=?',(proof['claim']['nonce'],)).fetchone()[0],0)


class CurrentWRequestTests(unittest.TestCase):
    def test_canceled_intent_rebuild_uses_current_w_then_refuses_rehandling(self):
        from competition.profiles.w_seed import initialize as initialize_w
        from competition.w_cases import accept_operation, tool_snapshot
        with tempfile.TemporaryDirectory() as folder:
            run=initialize_w(Path(folder))
            try:
                p='PAY-1';op=run.clone(p);oid,_=accept_operation(run,p)
                run.base.update_role(p,'G',False)
                canceled=run.w.cancel(p,oid,run.worker_proof(p,oid,'CANCEL'))
                self.assertEqual(canceled['dispatch_state'],'CANCELED')
                run.base.update_role(p,'G',True)
                verifier=run.base.service.verifier
                fresh=run.fork_operation(p,op)
                self.assertIs(run.base.service.verifier,verifier)
                ticket=run.w.prepare(p,fresh,run.identity_proof(p,fresh))
                with self.assertRaises(ProtocolError) as cm:
                    run.w.accept(p,ticket['ticket_id'],run.accept_proof(p,ticket['ticket_id']))
                self.assertEqual(cm.exception.code,'INTENT_CONFLICT')
                self.assertEqual(tool_snapshot(run,p)['effect_count'],0)
                self.assertEqual(run.w.counts()['accepts'],1)
            finally:run.close()
    def test_existing_runtime_cannot_silently_change_protocol_identity(self):
        import json
        from competition.profiles.w_seed import initialize as initialize_w
        from competition.core.common_w import CommonW
        with tempfile.TemporaryDirectory() as folder:
            run=initialize_w(Path(folder))
            try:
                with run.store.tx() as c:
                    row=c.execute("SELECT seq,blob FROM a_journal WHERE kind='W_BOOTSTRAP'").fetchone()
                    boot=json.loads(row['blob']);boot.pop('protocol',None)
                    c.execute('UPDATE a_journal SET blob=? WHERE seq=?',(json.dumps(boot),row['seq']))
                with self.assertRaises(ProtocolError) as cm:
                    CommonW(run.store,run.w.delivery_key,run.worker_certificate,run.x_signers,run.tool_gateways)
                self.assertEqual(cm.exception.code,'W_BOOTSTRAP_CONFLICT')
                self.assertEqual(run.w.counts()['accepts'],0)
            finally:run.close()
