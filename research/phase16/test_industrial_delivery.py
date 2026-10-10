"""Phase16 IND authenticated delivery and crash/retry tests. Local simulation only."""
from __future__ import annotations
import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase8.fixtures import build_scene,prepare_approved
from research.phase12.authority import HardenedSceneW
from research.phase14.verifier import VerifierOnlySceneW
from research.phase16.industrial_delivery import (
    WDispatchOutbox,AuthenticatedIndustrialGateway,public_key,DOMAIN
)
from research.phase6.trusted_final import Controller,ToolLedger,_pub
from research.phase11.trusted_clock import seal
from research.reference_executor.wire import (
    ProtocolError,b64,keyid,sid,canonical,rec_ref,action_hash,msgref
)
from research.strict_v26.upstream_schema import UpstreamSchema
from research.phase11.run_phase11 import ROOT


class IndustrialDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.wp=self.base/'w.sqlite';self.lp=self.base/'tool.sqlite'
        self.issuer,self.action,self.task,self.scene,self.evidence=build_scene(
            self.wp,'IND-DEMO-1',authority_class=HardenedSceneW)
        self.op=prepare_approved(self.issuer,self.action,self.task,self.scene)
        self.c=Controller(self.issuer.controller)
        self.w=VerifierOnlySceneW(self.wp,'IND-DEMO-1',
                     root_public=self.issuer.root_public,actors=self.issuer.actors)
        self.oid=self.action['operation_id']
        req=self.w.prepare_accept(self.op,clock=self.clock('PREPARE',1,106))
        acc=self.issuer.actors['X'].sign('IND-DEMO-1','Acceptance',req['scope'],
             req['acceptance_payload'],refs=req['refs'],aud=req['aud'],
             at=req['signed_at'],iid=sid(161001))
        self.w.finalize_accept(req['ticket'],acc,clock=self.clock('FINALIZE',2,106))
        self.ledger=ToolLedger(self.lp,profile='IND-DEMO-1')
        self.tool_signer=Ed25519PrivateKey.from_private_bytes(b'Q'*32)
        tv={'issuer':'tool-issuer','tool':self.action['tool'],'tool_version':self.action['tool_version'],
          'destination':self.action['destination'],'ledger_id':self.ledger.ledger_id,
          'evidence_method':'tool-final-v2','public_key':b64(_pub(self.tool_signer)),
          'kid':keyid(_pub(self.tool_signer)),'epoch':'1','iat':'90','exp':'2000'}
        cert=self.c.certify(self.w.scope,tv,1,self.ledger.head(),self.ledger.origin,profile='IND-DEMO-1')
        self.w.activate_tool(cert,self.ledger,now=107)
        self.attempt=sid(161003)
        result=self.w.claim_r2(self.oid,self.attempt,clock=self.clock('DISPATCH',3,107))
        self.assertEqual(result['status'],'CLAIMED')
        self.w_signer=Ed25519PrivateKey.from_private_bytes(b'W'*32)
        self.outbox=WDispatchOutbox(self.wp,'IND-DEMO-1',signer=self.w_signer)
        self.gateway=AuthenticatedIndustrialGateway(self.ledger,
                w_public=public_key(self.w_signer),scope=self.w.scope)

    def clock(self,purpose,seq,at):
        return seal(self.c,'IND-DEMO-1',self.w.scope if hasattr(self,'w') else self.issuer.scope,
                    self.action['operation_id'],purpose,seq,at,at)

    def token(self):
        return self.outbox.issue(self.oid,ledger=self.ledger)

    def test_lost_reply_restart_and_original_tool_settlement(self):
        token=self.token()
        self.assertEqual(self.w.snapshot()['calls'],1)
        with self.assertRaises(ProtocolError) as e:
            self.gateway.deliver(token,inject='after_commit')
        self.assertEqual(e.exception.code,'SIMULATED_RESPONSE_LOSS')
        self.assertEqual(self.gateway.audit()['simulated_effects'],1)
        # A fresh gateway process instance relies on *persisted* ledger state.
        recovered=AuthenticatedIndustrialGateway(ToolLedger(self.lp,profile='IND-DEMO-1'),
                w_public=public_key(self.w_signer),scope=self.w.scope)
        out=recovered.deliver(token)
        self.assertFalse(out['new_effect'])
        self.assertEqual(out['fact'],self.ledger.lookup(self.oid,self.attempt))
        self.assertEqual(out['fact']['action_hash'],action_hash('IND-DEMO-1',self.action))
        signed=self.ledger.reattest(self.w.scope,out['fact'],self.tool_signer,'tool-issuer',111,2000)
        UpstreamSchema(ROOT,'IND-DEMO-1').validate(signed,'Record_TOOL_FINAL')
        settle=self.w.settle_r2(signed,self.ledger,clock=self.clock('SETTLE',4,112))
        self.assertEqual(settle['status'],'SUCCEEDED')
        self.assertEqual(self.w.snapshot()['reserved'],0)
        self.assertEqual(self.w.snapshot()['spent'],1)
        self.assertEqual(recovered.audit()['simulated_effects'],1)
        with self.assertRaises(ProtocolError):
            self.w.claim_r2(self.oid,sid(161004),clock={'invalid':'replay'})

    def test_unclaimed_operation_cannot_get_dispatch_token(self):
        with self.assertRaises(ProtocolError) as e:
            self.outbox.issue(sid(160999),ledger=self.ledger)
        self.assertEqual(e.exception.code,'NO_CLAIM')
        self.assertEqual(self.gateway.audit()['simulated_effects'],0)

    def test_precommit_crash_rollback_no_effect(self):
        token=self.token()
        with self.assertRaises(ProtocolError) as e:
            self.gateway.deliver(token,inject='before_commit')
        self.assertEqual(e.exception.code,'SIMULATED_PRECOMMIT_CRASH')
        self.assertEqual(self.gateway.audit()['simulated_effects'],0)
        self.assertTrue(self.gateway.deliver(token)['new_effect'])
        self.assertEqual(self.gateway.audit()['simulated_effects'],1)

    def test_forged_w_signature_and_tampered_action_rejected(self):
        token=self.token()
        altered=copy.deepcopy(token);altered['claim']['action']['destination']='evil-route'
        with self.assertRaises(ProtocolError):self.gateway.deliver(altered)
        wrong=copy.deepcopy(token)
        wrong['signature']=b64(Ed25519PrivateKey.from_private_bytes(b'Z'*32).sign(
                            canonical([DOMAIN,wrong['claim']])))
        with self.assertRaises(ProtocolError):self.gateway.deliver(wrong)
        self.assertEqual(self.gateway.audit()['simulated_effects'],0)

    def test_different_tool_ledger_origin_denied(self):
        token=self.token()
        alien=ToolLedger(self.base/'unrelated.sqlite',profile='IND-DEMO-1')
        g=AuthenticatedIndustrialGateway(alien,w_public=public_key(self.w_signer),scope=self.w.scope)
        with self.assertRaises(ProtocolError) as e:g.deliver(token)
        self.assertEqual(e.exception.code,'LEDGER_BINDING')
        self.assertEqual(g.audit()['simulated_effects'],0)

    def test_signed_conflicting_retry_is_not_new_effect(self):
        token=self.token()
        self.gateway.deliver(token)
        altered=copy.deepcopy(token)
        altered['claim']['attempt']=sid(16777)
        altered['signature']=b64(self.w_signer.sign(canonical([DOMAIN,altered['claim']])))
        with self.assertRaises(ProtocolError) as e:self.gateway.deliver(altered)
        self.assertEqual(e.exception.code,'DISPATCH_CONFLICT')
        self.assertEqual(self.gateway.audit()['simulated_effects'],1)

    def test_concurrent_delivery_only_one_effect(self):
        token=self.token()
        def deliver(_):
            g=AuthenticatedIndustrialGateway(ToolLedger(self.lp,profile='IND-DEMO-1'),
                   w_public=public_key(self.w_signer),scope=self.w.scope)
            return g.deliver(token)
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes=list(pool.map(deliver,range(8)))
        self.assertEqual(sum(x['new_effect'] for x in outcomes),1)
        self.assertEqual(len({x['fact']['final_seq'] for x in outcomes}),1)
        self.assertEqual(self.gateway.audit()['simulated_effects'],1)

    def test_outbox_is_immutable_across_restarts(self):
        token=self.token()
        new=WDispatchOutbox(self.wp,'IND-DEMO-1',signer=self.w_signer)
        self.assertEqual(new.issue(self.oid,ledger=self.ledger),token)
        self.assertEqual(self.gateway.audit()['simulated_effects'],0)

if __name__=='__main__':unittest.main()
