"""Real participant short-chain signatures for integration tests ONLY."""
import copy
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from competition.profiles.w_seed import initialize
from competition.application.trusted_action_resolver import TrustedActionResolver, AUTH_DOMAIN
from competition.application.operation_orchestrator import OperationOrchestrator
from competition.tests.resolver_fixtures import P, approve_in_lab
from competition.support.wire import b64, canonical, msgref, ProtocolError

SHORT = ('challenge_request', 'challenge', 'proof')

def bind(run, requests):
    name = 'competition.application.request_bound_w'
    if importlib.util.find_spec(name) is not None:
        from competition.application.request_bound_w import RequestBoundW
        run.w = RequestBoundW(run.w, requests)
    return run.w

def refresh_short(run, op, *, expires=None, reuse=None, reuse_fields=None):
    """Keep every original approval byte; H/X sign only three fresh messages."""
    op = copy.deepcopy(op)
    signing = copy.copy(run.base)
    signing.operations = {**run.operations, P: op}
    now = int(time.time())
    exp = min(now + 30, int(op['permit']['body']['exp'])) if expires is None else expires
    pr = msgref(op['permit']); ctx = op['ctx']; deps = op['deps']
    attempt, session, nonce = b64(os.urandom(16)), b64(os.urandom(16)), b64(os.urandom(32))
    if reuse:
        reuse_fields=('attempt','session','nonce') if reuse_fields is None else reuse_fields
        if 'attempt' in reuse_fields:attempt=reuse['challenge_request']['body']['payload']['attempt_id']
        if 'session' in reuse_fields:session=reuse['challenge']['body']['payload']['session_id']
        if 'nonce' in reuse_fields:nonce=reuse['challenge']['body']['payload']['nonce']
        original_sign=signing.sign
        def sign(profile,alias,typ,payload,**kwargs):
            result=original_sign(profile,alias,typ,payload,**kwargs)
            if typ in reuse_fields:
                field={'ChallengeRequest':'challenge_request','Challenge':'challenge','CommitProof':'proof'}[typ]
                unsigned={k:copy.deepcopy(v) for k,v in result.items() if k!='sig'}
                unsigned['body']['id']=reuse[field]['body']['id']
                cl=signing.broker.challenge(profile,alias,unsigned,op['action'])
                proof={'claim':cl,'signature':b64(run.actors[profile][alias].key.sign(canonical(['COMP-APP-SIGN-CALL-v1',cl])))}
                result=signing.broker.sign(profile,alias,unsigned,op['action'],caller_proof=proof)
            return result
        signing.sign=sign
    op['challenge_request'] = signing.sign(P, 'H', 'ChallengeRequest', {
        'purpose':'COMMIT','operation_id':ctx['operation_id'],'permit_ref':pr,
        'action_hash':ctx['action_hash'],'attempt_id':attempt}, refs=[pr], deps=deps,
        aud=('X',), iat=now, exp=exp)
    qr = msgref(op['challenge_request'])
    op['challenge'] = signing.sign(P, 'X', 'Challenge', {
        'purpose':'COMMIT','operation_id':ctx['operation_id'],'permit_ref':pr,
        'action_hash':ctx['action_hash'],'holder':ctx['holder'],'holder_kid':ctx['holder_kid'],
        'session_id':session,'nonce':nonce,'request_ref':qr}, refs=[pr,qr], deps=deps,
        aud=('H',), iat=now, exp=exp)
    op['proof'] = signing.sign(P, 'H', 'CommitProof', {
        'ctx':ctx,'permit_ref':pr,'challenge_ref':msgref(op['challenge']),
        'session_id':session,'nonce':nonce,'attempt_id':attempt},
        refs=[pr,msgref(op['challenge'])], deps=deps, aud=('X',), iat=now, exp=exp)
    return op

class RenewalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='zjj-renewal-')
        self.addCleanup(self.tmp.cleanup)
        self.run = initialize(Path(self.tmp.name)); self.addCleanup(self.run.close)
        self.resolver = TrustedActionResolver(self.run.store, self.run.operations[P]['task_id'])
        self.store = self.resolver.requests
        bind(self.run, self.store)
        self.flow = OperationOrchestrator(self.run.w, self.store)
        self.proposal = {'request_id':'renew-1','unit_id':'unit-a','route':'INSPECT'}
        self.row = self.resolve(self.proposal)
        self.op = approve_in_lab(self.run, self.row)

    def auth(self, proposal):
        now = int(time.time())
        cl = {'profile':P,'task_id':self.resolver.task_id,'proposal':proposal,
              'iat':str(now),'exp':str(now+60)}
        return {'claim':cl,'signature':b64(self.run.actors[P]['H'].key.sign(canonical([AUTH_DOMAIN,cl])))}

    def resolve(self, proposal):
        return self.resolver.resolve(proposal,self.auth(proposal))

    def freeze(self, op=None):
        self.flow.freeze_approved(self.row['key'], op or self.op)
        return self.store.load(self.row['key'])

    def replace(self, op, saved):
        method = getattr(self.flow,'replace_pending',None)
        self.assertTrue(callable(method),'Missing restricted pending-packet replacement')
        return method(self.row['key'], op, saved['version'], saved['request_ref'])

    def prepare(self, op):
        return self.run.w.prepare(P,op,self.run.identity_proof(P,op))

    def accept(self, ticket):
        return self.run.w.accept(P,ticket['ticket_id'],self.run.accept_proof(P,ticket['ticket_id']))

    def blocked(self, fn, code=None):
        with self.assertRaises(ProtocolError) as caught: fn()
        if code: self.assertEqual(caught.exception.code,code)
        return caught.exception.code
