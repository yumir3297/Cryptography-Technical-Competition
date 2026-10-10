"""Phase14 scene acceptance tests. Synthetic signers; NOT official 39-case PASS."""
from __future__ import annotations
import copy, json, tempfile, unittest
from pathlib import Path
from research.phase8.fixtures import build_scene, prepare_approved
from research.phase12.authority import HardenedSceneW
from research.phase14.verifier import VerifierOnlySceneW
from research.phase6.trusted_final import Controller
from research.phase11.trusted_clock import seal
from research.phase8.scene_authority import _rec
from research.reference_executor.wire import ProtocolError, sid

class TwoPhaseSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
    def bootstrap(self,profile):
        self.path=Path(self.tmp.name)/'w.sqlite'
        issuer,action,task,scene,ev=build_scene(self.path,profile,authority_class=HardenedSceneW)
        op=prepare_approved(issuer,action,task,scene)
        self.controller=Controller(issuer.controller)
        self.x=issuer.actors['X']
        w=VerifierOnlySceneW(self.path,profile,root_public=issuer.root_public,actors=issuer.actors)
        self.assertFalse(hasattr(w.controller,'sign'))
        self.assertTrue(all(not hasattr(a,'key') and not hasattr(a,'sign') for a in w.actors.values()))
        self.assertEqual(w.snapshot()['accepts'],0)
        return w,op
    def clock(self,w,op,purpose,sequence,at=106):
        return seal(self.controller,w.profile,w.scope,op['action']['operation_id'],
                    purpose,sequence,at,at)
    def signed(self,req,*,signer=None):
        x=signer or self.x
        return x.sign(req['profile'],'Acceptance',req['scope'],req['acceptance_payload'],
            refs=req['refs'],aud=req['aud'],at=req['signed_at'],iid=sid(106008))
    def prepared(self,w,op):
        req=w.prepare_accept(op,clock=self.clock(w,op,'PREPARE',1))
        self.assertEqual(w.snapshot()['accepts'],0)
        self.assertEqual(w.snapshot()['reserved'],0)
        return req
    def test_success_both_profiles_and_restart(self):
        for profile in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile):
                w,op=self.bootstrap(profile)
                req=self.prepared(w,op)
                x=self.signed(req)
                w=VerifierOnlySceneW(self.path,profile,root_public=w.root_public,actors=w.actors)
                self.assertEqual(w.finalize_accept(req['ticket'],x,clock=self.clock(w,op,'FINALIZE',2)),x)
                self.assertEqual(w.finalize_accept(req['ticket'],x,clock={'invalid':True}),x)
                self.assertEqual(w.snapshot()['accepts'],1)
                self.assertEqual(w.snapshot()['reserved'],1)
                self.assertEqual(w.snapshot()['calls'],0)
                with w.db() as c:
                    row=c.execute('SELECT accepted_blob FROM accept_intent').fetchone()
                    self.assertEqual(json.loads(row[0])['commit_record'],req['commit_record'])
                self.assertFalse(hasattr(w.controller,'sign'))
                # Clean test isolation per subtest requires a fresh temporary DB.
                if profile=='IND-DEMO-1':
                    self.tmp.cleanup(); self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
    def test_bad_signature_rejected_without_accept(self):
        w,op=self.bootstrap('IND-DEMO-1')
        req=self.prepared(w,op)
        altered=copy.deepcopy(self.signed(req))
        altered['body']['payload']['commit_record_ref']='forgery'
        with self.assertRaises(ProtocolError):
            w.finalize_accept(req['ticket'],altered,clock=self.clock(w,op,'FINALIZE',2))
        self.assertEqual(w.snapshot()['accepts'],0)
    def test_control_revision_change_rejected(self):
        w,op=self.bootstrap('MED-DEMO-1')
        req=self.prepared(w,op);signed=self.signed(req)
        with w.db() as c:
            policy_key=w.scope_key()
            original=w.current(c,'POLICY',policy_key)['record']
        # Signed by external C issuer, accepted by W using public root only.
        cert=self.controller.key.sign
        from research.reference_executor.wire import canonical,b64,keyid
        with w.db() as c:
            old=w.current(c,'POLICY',w.scope_key())['revision']
        claim={'scope':w.scope,'namespace':'POLICY','key':w.scope_key(),
           'previous_revision':str(old),'record':original,'active':True}
        w.publish_cert({'claim':claim,'kid':keyid(w.root_public),
            'sig':b64(cert(canonical(['ZJJ-C-CONTROL-LAB-v1',claim])))})
        with self.assertRaises(ProtocolError):
            w.finalize_accept(req['ticket'],signed,clock=self.clock(w,op,'FINALIZE',2))
        self.assertEqual(w.snapshot()['accepts'],0)
    def test_resource_competition_rejected(self):
        w,op=self.bootstrap('IND-DEMO-1')
        req=self.prepared(w,op);signed=self.signed(req)
        with w.tx() as c:
            c.execute('INSERT OR IGNORE INTO resource(destination) VALUES(?)',(op['action']['destination'],))
            c.execute('UPDATE resource SET reserved=8,revision=revision+1 WHERE destination=?',
                (op['action']['destination'],))
        with self.assertRaises(ProtocolError):
            w.finalize_accept(req['ticket'],signed,clock=self.clock(w,op,'FINALIZE',2))
        self.assertEqual(w.snapshot()['accepts'],0)
    def test_stale_clock_and_lost_x_recovery(self):
        w,op=self.bootstrap('MED-DEMO-1')
        req=self.prepared(w,op)
        self.assertEqual(w.snapshot()['accepts'],0) # X never returned
        with self.assertRaises(ProtocolError):
            w.finalize_accept(req['ticket'],self.signed(req),clock=self.clock(w,op,'FINALIZE',2,240))
        self.assertEqual(w.snapshot()['accepts'],0)
        self.assertEqual(w.snapshot()['reserved'],0)
        self.assertEqual(w.finalize_accept(req['ticket'],self.signed(req),
            clock=self.clock(w,op,'FINALIZE',2))['protected']['type'],'Acceptance')
    def test_no_direct_legacy_accept(self):
        w,op=self.bootstrap('IND-DEMO-1')
        with self.assertRaises(ProtocolError):w.accept(op)
        with self.assertRaises(ProtocolError):w.sign_evidence({})
        with self.assertRaises(ProtocolError):w.certify('POLICY',[],{})
        self.assertEqual(w.snapshot()['accepts'],0)

if __name__=='__main__':unittest.main()
