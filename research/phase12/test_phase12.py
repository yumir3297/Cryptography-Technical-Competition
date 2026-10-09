"""Executed Phase12 local facets. These tests never award full official PASS."""
from __future__ import annotations
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from research.reference_executor.wire import ProtocolError, sid
from research.phase11.run_phase11 import setup_pay_aud, payclock, setup_scene, activate, clock
from research.phase8.fixtures import build_scene, prepare_approved
from research.phase6.trusted_final import ToolLedger, final_sign_bytes, Controller
from research.phase11.trusted_clock import seal
from research.phase12.authority import HardenedPayW, HardenedSceneW
from research.reference_executor.wire import b64

ROOT=Path(__file__).resolve().parents[2]

class Phase12Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)

    def failure(self,code,call):
        with self.assertRaises(ProtocolError) as x:call()
        self.assertEqual(x.exception.code,code)

    def _scene(self,profile):
        d=self.d
        a,act,tid,sk,ev=build_scene(d/'w.sqlite',profile,authority_class=HardenedSceneW)
        op=prepare_approved(a,act,tid,sk)
        a.accept(op)
        ledger,key,cert=activate(a,act,d)
        return a,act,ledger,key,op

    def _pay(self):
        c,w,f,op,ledger,key,cert,windows,gate=setup_pay_aud(self.d)
        return c,HardenedPayW(self.d/'payw.sqlite',c.public_key,ledger=ledger),f,op,ledger,key

    def _time(self,a,op,purpose,seq,profile,scope):
        controller=Controller.fixture() if profile=='PAY-1' else Controller(a.controller)
        return seal(controller,profile,scope,op,purpose,seq,107,107)

    def test_pay_ledger_missing_blocks_first_settlement_and_can_recover(self):
        c,w,f,op,ledger,key=self._pay();att=sid(8101);oid=op.action['operation_id']
        clock=payclock(w,c,f.scope,oid,'DISPATCH',107,107)
        self.assertEqual(w.claim_r2(oid,att,clock=clock)['status'],'CLAIMED')
        fact=ledger.freeze(f.scope,op.action,att,at=110)
        signed=ledger.reattest(f.scope,fact,key,'tool-issuer',111,2000)
        with ledger._db() as db:
            old=db.execute('SELECT * FROM finalized WHERE operation_id=?',(oid,)).fetchone()
            db.execute('DELETE FROM finalized WHERE operation_id=?',(oid,))
        before=w.snapshot()
        rejected=payclock(w,c,f.scope,oid,'SETTLE',112,112)
        self.failure('LEDGER_FACT_NOT_FOUND',lambda:w.settle_r2(signed,clock=rejected))
        self.assertEqual(before,w.snapshot())
        with ledger._db() as db:
            db.execute('INSERT INTO finalized VALUES(?,?,?,?,?)',old)
        fresh=payclock(w,c,f.scope,oid,'SETTLE',113,113)
        self.assertEqual(w.settle_r2(signed,clock=fresh)['status'],'SUCCEEDED')
        self.assertEqual(w.snapshot()['spent'],2000)

    def test_pay_replaced_ledger_same_id_different_origin_blocks(self):
        c,w,f,op,ledger,key=self._pay();oid=op.action['operation_id'];att=sid(8102)
        w.claim_r2(oid,att,clock=payclock(w,c,f.scope,oid,'DISPATCH',107,107))
        fact=ledger.freeze(f.scope,op.action,att,at=110)
        signed=ledger.reattest(f.scope,fact,key,'tool-issuer',111,2000)
        alternate=ToolLedger(self.d/'alternate.sqlite',ledger_id=ledger.ledger_id,profile='PAY-1')
        alternate.freeze(f.scope,op.action,att,at=110)
        w.r2_ledger=alternate
        before=w.snapshot()
        self.failure('CONTINUITY_UNKNOWN',lambda:w.settle_r2(signed,clock=payclock(w,c,f.scope,oid,'SETTLE',112,112)))
        self.assertEqual(w.snapshot(),before)

    def test_ind_med_missing_tool_fact_blocks_and_recovers(self):
        for profile in ('IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as d:
                self.d=Path(d)
                a,act,ledger,key,op=self._scene(profile)
                oid=act['operation_id'];att=sid(8103)
                a.claim_r2(oid,att,clock=clock(a,oid,'DISPATCH',107,107))
                fact=ledger.freeze(a.scope,act,att,at=110)
                signed=ledger.reattest(a.scope,fact,key,'tool-issuer',111,2000)
                with ledger._db() as db:
                    old=db.execute('SELECT * FROM finalized WHERE operation_id=?',(oid,)).fetchone()
                    db.execute('DELETE FROM finalized WHERE operation_id=?',(oid,))
                before=a.snapshot()
                self.failure('LEDGER_FACT_NOT_FOUND',lambda:a.settle_r2(signed,ledger,clock=clock(a,oid,'SETTLE',112,112)))
                self.assertEqual(before,a.snapshot())
                with ledger._db() as db:db.execute('INSERT INTO finalized VALUES(?,?,?,?,?)',old)
                self.assertEqual(a.settle_r2(signed,ledger,clock=clock(a,oid,'SETTLE',113,113))['status'],'SUCCEEDED')

    def test_valid_signature_but_fact_conflict_never_settles(self):
        # Even if a currently trusted tool signing key signs a new claim, W
        # must verify the immutable first fact, not merely its signature.
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as d:
                self.d=Path(d)
                if profile=='PAY-1':
                    c,w,f,op,ledger,key=self._pay()
                    act=op.action;scope=f.scope
                    get_clock=lambda purpose,t:payclock(w,c,scope,act['operation_id'],purpose,t,t)
                else:
                    w,act,ledger,key,op=self._scene(profile)
                    scope=w.scope
                    get_clock=lambda purpose,t:clock(w,act['operation_id'],purpose,t,t)
                oid=act['operation_id'];attempt=sid(8106)
                w.claim_r2(oid,attempt,clock=get_clock('DISPATCH',107))
                original=ledger.freeze(scope,act,attempt,at=110)
                signed=ledger.reattest(scope,original,key,'tool-issuer',111,2000)
                # The attestation itself is genuinely signed by the current key.
                altered=copy.deepcopy(signed)
                altered['value']['effect_id']='alternative-effect'
                altered['value']['attestation']['sig']=b64(key.sign(final_sign_bytes(altered)))
                before=w.snapshot()
                check=get_clock('SETTLE',112)
                if profile=='PAY-1':
                    self.failure('LEDGER_FACT_CONFLICT',lambda:w.settle_r2(altered,clock=check))
                else:
                    self.failure('LEDGER_FACT_NOT_FOUND',lambda:w.settle_r2(altered,ledger,clock=check))
                self.assertEqual(w.snapshot(),before)
                self.assertEqual(ledger.lookup(oid,attempt),original)

    def test_both_orders_cancel_then_claim_and_claim_then_cancel(self):
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            for first in ('cancel','claim'):
                with self.subTest(profile=profile,first=first),tempfile.TemporaryDirectory() as d:
                    self.d=Path(d)
                    if profile=='PAY-1':
                        c,w,f,op,ledger,key=self._pay()
                        oid=op.action['operation_id'];scope=f.scope
                        get_clock=lambda purpose,t:payclock(w,c,scope,oid,purpose,t,t)
                    else:
                        w,act,ledger,key,op=self._scene(profile)
                        oid=act['operation_id']
                        get_clock=lambda purpose,t:clock(w,oid,purpose,t,t)
                    if first=='cancel':
                        result=w.cancel_r2(oid,clock=get_clock('CANCEL',107))
                        self.assertEqual(result['status'],'CANCELLED')
                        self.failure('NO_DISPATCH',lambda:w.claim_r2(oid,sid(8108),clock=get_clock('DISPATCH',108)))
                    else:
                        self.assertEqual(w.claim_r2(oid,sid(8108),clock=get_clock('DISPATCH',107))['status'],'CLAIMED')
                        result=w.cancel_r2(oid,clock=get_clock('CANCEL',108))
                        self.assertEqual(result['status'],'TOO_LATE')
                    with (w._read() if profile=='PAY-1' else w.db()) as db:
                        table='accepted' if profile=='PAY-1' else 'accept_intent'
                        row=db.execute(f'SELECT state FROM {table} WHERE operation_id=?',(oid,)).fetchone()
                    self.assertEqual(row['state'],'CANCELLED' if first=='cancel' else 'EFFECT_UNKNOWN')

    def test_two_way_claim_cancel_race_three_profiles(self):
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as d:
                self.d=Path(d)
                if profile=='PAY-1':
                    c,a,f,op,ledger,key=self._pay();oid=op.action['operation_id'];scope=f.scope
                else:
                    a,act,ledger,key,op=self._scene(profile);oid=act['operation_id'];scope=a.scope
                # Both C-signed proofs use identical next sequence, so only
                # one can win the serialized W transaction. The loser may get
                # CLOCK_REPLAY or NO_DISPATCH/TOO_LATE after retry.
                with (a._read() if profile=='PAY-1' else a.db()) as conn:
                    seq=conn.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]+1
                cp=self._time(a,oid,'CANCEL',seq,profile,scope)
                dp=self._time(a,oid,'DISPATCH',seq,profile,scope)
                barrier=threading.Barrier(2)
                results=[]
                def go(kind):
                    barrier.wait(timeout=10)
                    try:
                        if kind=='cancel':return ('cancel',a.cancel_r2(oid,clock=cp))
                        return ('claim',a.claim_r2(oid,sid(8104),clock=dp))
                    except ProtocolError as e:return (kind,e.code)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(go,k) for k in ('cancel','claim')]
                    results=[x.result(timeout=20) for x in futures]
                self.assertEqual(sum(type(x[1]) is dict for x in results),1,results)
                state=a.snapshot()
                if profile=='PAY-1':
                    with a._read() as conn:row=conn.execute('SELECT state,exec_calls FROM accepted WHERE operation_id=?',(oid,)).fetchone()
                    reserved=state['reserved'];expected=2000
                    calls=row['exec_calls']
                else:
                    with a.db() as conn:row=conn.execute('SELECT state,calls FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
                    reserved=state['reserved'];expected=1
                    calls=row['calls']
                self.assertIn(row['state'],('CANCELLED','EFFECT_UNKNOWN'))
                self.assertEqual(calls,1 if row['state']=='EFFECT_UNKNOWN' else 0)
                self.assertEqual(reserved,expected if calls else 0)
                if calls:
                    retryseq=seq+1
                    post=self._time(a,oid,'CANCEL',retryseq,profile,scope)
                    self.assertEqual(a.cancel_r2(oid,clock=post)['status'],'TOO_LATE')
                    self.assertEqual(a.snapshot()['reserved'],expected)
                else:
                    with self.assertRaises(ProtocolError):
                        proof=self._time(a,oid,'DISPATCH',seq+1,profile,scope)
                        a.claim_r2(oid,sid(8105),clock=proof)

    def test_claim_crash_after_commit_recovery_no_redispatch(self):
        for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as d:
                self.d=Path(d)
                if profile=='PAY-1':
                    c,a,f,op,ledger,key=self._pay();oid=op.action['operation_id'];scope=f.scope
                    proof=payclock(a,c,scope,oid,'DISPATCH',107,107)
                    db=self.d/'payw.sqlite'
                else:
                    a,act,ledger,key,op=self._scene(profile);oid=act['operation_id'];scope=a.scope
                    proof=clock(a,oid,'DISPATCH',107,107);db=self.d/'w.sqlite'
                payload={'profile':profile,'db_path':str(db),'ledger_path':ledger.path,
                         'operation_id':oid,'attempt':sid(8110),'clock':proof}
                cfg=self.d/'crash.json';cfg.write_text(json.dumps(payload),encoding='utf8')
                done=subprocess.run([sys.executable,'-m','research.phase12.crash_worker',str(cfg)],
                                    cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
                self.assertEqual(done.returncode,79,done.stderr.decode(errors='replace'))
                if profile=='PAY-1':
                    b=HardenedPayW(db,c.public_key,ledger=ledger)
                    with b._read() as conn:r=conn.execute('SELECT state,exec_calls,dispatch_attempt FROM accepted WHERE operation_id=?',(oid,)).fetchone()
                else:
                    b=HardenedSceneW(db,profile)
                    with b.db() as conn:r=conn.execute('SELECT state,calls,attempt FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
                self.assertEqual(r['state'],'EFFECT_UNKNOWN')
                self.assertEqual(r['exec_calls'] if profile=='PAY-1' else r['calls'],1)
                # No implicit return to pending or second dispatch with new attempt.
                with self.assertRaises(ProtocolError):
                    if profile=='PAY-1':b.claim_r2(oid,sid(8111),clock=payclock(b,c,scope,oid,'DISPATCH',108,108))
                    else:b.claim_r2(oid,sid(8111),clock=clock(b,oid,'DISPATCH',108,108))
                self.assertGreater(b.snapshot()['reserved'],0)

if __name__=='__main__':unittest.main()
