"""Phase15 PAY verifier-only W: production-shaped boundaries, laboratory actors."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase4.flow import SignedPayFlow
from research.phase7.guarded_dispatch import _make_cert
from research.phase11.pay_r2 import sign_window
from research.phase11.trusted_clock import seal
from research.phase11.run_phase11 import ROOT
from research.phase15.pay_accept import VerifierOnlyPayW
from research.phase6.trusted_final import Controller,ToolLedger,_pub
from research.reference_executor.wire import (ProtocolError, b64, keyid, sid, rec_ref, msgref, sortset)


class PayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.path=Path(self.t.name);self.root=Controller.fixture()
        # The proposer is a LAB fixture with private keys; it is never passed to W.
        self.f=SignedPayFlow(schema_root=ROOT);self.op=self.f.prepare()
        for purpose in self.op.required:self.f.review(self.op,purpose=purpose)
        self.f.authorize(self.op);self.f.issue(self.op);self.f.challenge(self.op)
        self.f.commit(self.op)
        self.bundle={'commit':copy.deepcopy(self.f.commit_record),'permit':copy.deepcopy(self.op.permit),
          'proof':copy.deepcopy(self.op.proof),'challenge':copy.deepcopy(self.op.challenge),
          'challenge_request':copy.deepcopy(self.op.challenge_request),
          'authorization':copy.deepcopy(self.op.authorization),'reviews':copy.deepcopy(self.op.reviews)}
        self.ledger=ToolLedger(self.path/'tool.sqlite')
        self.w=VerifierOnlyPayW(self.path/'w.sqlite',self.root.public_key,
                                ledger=self.ledger,actors=self.f.actors)
        self.assertTrue(all(not hasattr(a,'key') and not hasattr(a,'sign')
                            for a in self.w.public_actors.values()))
        self.assertFalse(hasattr(self.w,'idents'))
        # C independently publishes current dependency positions and validity.
        changes=[{**d,'active':True} for d in self.bundle['commit']['value']['checked_deps']
                 if d['namespace']!='BEHAVIOR']
        self.w.certified_publish(_make_cert(self.root,
                {'operation_id':'','scope':self.f.scope,'changes':changes}))
        for dep in changes:
            cl={'scope':self.f.scope,'dep':{k:dep[k] for k in ('namespace','key','revision','ref')},
                'seq':'1','iat':'90','exp':'2000'}
            self.w.publish_window(sign_window(self.root,cl))

    def clock(self,purpose,seq,at):
        return seal(self.root,'PAY-1',self.f.scope,self.op.action['operation_id'],
                    purpose,seq,at,at)

    def sign_x(self,req):
        x=self.f.idents['X']
        acc=x.sign('PAY-1','Acceptance',req['scope'],req['acceptance_payload'],
              refs=req['refs'],deps=self.f.issuerdeps(['X']),aud=req['aud'],
              at=req['signed_at'],iid=sid(15111))
        result={'request_ref':req['proof_ref'],'attempt_id':
                    self.op.proof['body']['payload']['attempt_id'],
                'result':'ACCEPTED','reasons':[{'check':'result','code':'OK'}],
                'operation_id':req['operation_id'],'permit_ref':'',
                'acceptance_ref':msgref(acc),'status':'ACCEPTED',
                'status_seq':req['accept_seq'],'retry_after':''}
        reply=x.sign('PAY-1','Result',req['scope'],result,
              refs=[req['proof_ref'],msgref(acc)],deps=self.f.issuerdeps(['X']),
              aud=[self.f.idents['H'].name],at=req['signed_at'],iid=sid(15112))
        return acc,reply

    def prepare(self):
        out=self.w.prepare_pay(copy.deepcopy(self.bundle),clock=self.clock('PREPARE',1,100))
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)
        self.assertEqual(self.w.snapshot()['reserved'],0)
        return out

    def test_atomic_external_sign_restart_duplicate_and_tool_final(self):
        req=self.prepare();acc,reply=self.sign_x(req)
        self.w=VerifierOnlyPayW(self.path/'w.sqlite',self.root.public_key,
                                ledger=self.ledger,actors=self.f.actors)
        first=self.w.finalize_pay(req['ticket'],acc,reply,clock=self.clock('FINALIZE',2,100))
        self.assertFalse(first['idempotent'])
        same=self.w.finalize_pay(req['ticket'],acc,reply,clock={'invalid':True})
        self.assertTrue(same['idempotent'])
        self.assertEqual(self.w.snapshot()['accepted_rows'],1)
        self.assertEqual(self.w.snapshot()['reserved'],2000)
        self.assertEqual(first['acceptance'],acc)
        key=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        value={'issuer':'tool-issuer','tool':self.op.action['tool'],
          'tool_version':self.op.action['tool_version'],'destination':self.op.action['destination'],
          'ledger_id':self.ledger.ledger_id,'evidence_method':'tool-final-v2',
          'public_key':b64(_pub(key)),'kid':keyid(_pub(key)),
          'epoch':'1','iat':'90','exp':'2000'}
        cert=self.root.certify(self.f.scope,value,1,self.ledger.head(),self.ledger.origin)
        self.w.activate(cert,self.ledger,now=101)
        attempt=sid(15300)
        claim=self.w.claim_r2(self.op.action['operation_id'],attempt,
                              clock=self.clock('DISPATCH',3,107))
        self.assertEqual(claim['status'],'CLAIMED')
        fact=self.ledger.freeze(self.f.scope,self.op.action,attempt,at=110,effect_id='p15-pay1')
        final=self.ledger.reattest(self.f.scope,fact,key,'tool-issuer',111,2000)
        settled=self.w.settle_r2(final,clock=self.clock('SETTLE',4,112))
        self.assertEqual(settled['status'],'SUCCEEDED')
        self.assertEqual(self.w.snapshot()['reserved'],0)
        self.assertEqual(self.w.snapshot()['spent'],2000)
        with self.assertRaises(ProtocolError):
            self.w.claim_r2(self.op.action['operation_id'],sid(15301),clock={'invalid':True})

    def test_external_signature_tamper_is_atomic(self):
        req=self.prepare();acc,reply=self.sign_x(req)
        acc['body']['payload']['accept_seq']='900'
        with self.assertRaises(ProtocolError):
            self.w.finalize_pay(req['ticket'],acc,reply,clock=self.clock('FINALIZE',2,100))
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)
        self.assertEqual(self.w.snapshot()['reserved'],0)

    def test_certified_revocation_after_prepare_fails_closed(self):
        req=self.prepare();acc,reply=self.sign_x(req)
        dep=next(d for d in self.bundle['commit']['value']['checked_deps']
                 if d['namespace']=='POLICY')
        replacement={**dep,'revision':str(int(dep['revision'])+1),'active':False}
        self.w.certified_publish(_make_cert(self.root,
              {'operation_id':'','scope':self.f.scope,'changes':[replacement]}))
        with self.assertRaises(ProtocolError):
            self.w.finalize_pay(req['ticket'],acc,reply,clock=self.clock('FINALIZE',2,100))
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)

    def test_resource_race_after_prepare_fails_closed(self):
        req=self.prepare();acc,reply=self.sign_x(req)
        with self.w._tx() as c:
            c.execute('UPDATE account SET reserved=reserved+100,revision=revision+1 WHERE id=1')
        with self.assertRaises(ProtocolError):
            self.w.finalize_pay(req['ticket'],acc,reply,clock=self.clock('FINALIZE',2,100))
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)
        self.assertEqual(self.w.snapshot()['reserved'],100)

    def test_w_cannot_use_legacy_signer_accept(self):
        with self.assertRaises(ProtocolError):
            self.w.accept(self.f,self.op)
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)


if __name__=='__main__':unittest.main()
