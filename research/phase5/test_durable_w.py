"""Real SQLite ACID and signed archive tests, with true process kills."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
import unittest
from concurrent.futures import ThreadPoolExecutor
from research.phase4.flow import SignedPayFlow
from research.strict_v26.test_pay_history import case
from research.reference_executor.wire import ProtocolError, canonical, msgref, rec_ref
from .durable_w import DurablePayW, InjectedCrash, archive_verify


def ready(*, operation=None, cases=None):
    f=SignedPayFlow(cases=cases)
    if operation is not None:
        f.source['action']['operation_id']=operation
    op=f.prepare()
    for purpose in op.required:f.review(op,purpose=purpose)
    f.authorize(op);f.issue(op);f.challenge(op)
    return f,op

class DurableWTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'authority.sqlite'
        self.w=DurablePayW(self.path)
    def tearDown(self):self.tmp.cleanup()
    def same(self, r):
        self.assertEqual(r['seq'],1)
        self.assertTrue(archive_verify(r['commit'],r['acceptance']))
    def test_bad_signature_cannot_fetch_archived_receipt(self):
        f,o=ready();self.w.accept(f,o)
        f2,o2=ready();proof=f2.make_proof(o2)
        proof['sig']='A'*86
        with self.assertRaises(ProtocolError):
            self.w.accept(f2,o2,proof)
        self.assertEqual(self.w.snapshot()['audit_rows'],1)

    def test_official_schema_mismatched_bytes_fail_closed(self):
        from .run_phase5 import schema_probe
        folder=Path(self.tmp.name)/'fake_repo'/'system_dev/v26/contracts'
        folder.mkdir(parents=True)
        (folder/'pay1.schema.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'blob mismatch'):
            schema_probe(Path(self.tmp.name)/'fake_repo')

    def test_initial_ledger(self):
        s=self.w.snapshot();self.assertEqual((s['reserved'],s['accept_seq'],s['accepted_rows']),(0,0,0))
    def test_signed_commit_persists_and_recovers_new_connection(self):
        f,o=ready();r=self.w.accept(f,o);self.same(r)
        self.assertFalse(r['idempotent']);self.assertEqual(self.w.snapshot()['reserved'],2000)
        again=DurablePayW(self.path).accepted_operation(o.action['operation_id'])
        self.same(again);self.assertEqual(canonical(r['acceptance']),canonical(again['acceptance']))
        self.assertEqual(self.w.snapshot()['audit_rows'],1)
    def test_replay_same_bytes_returns_original_receipt_without_new_accept(self):
        f,o=ready();r=self.w.accept(f,o)
        f2,o2=ready();proof2=f2.make_proof(o2)
        again=DurablePayW(self.path).accept(f2,o2,proof2)
        self.assertTrue(again['idempotent'])
        self.assertEqual(r['acceptance'],again['acceptance'])
        self.assertEqual((self.w.snapshot()['accepted_count'],self.w.snapshot()['reserved']),(1,2000))
    def test_same_operation_changed_signed_proof_rejects(self):
        f,o=ready();self.w.accept(f,o)
        f2,o2=ready();proof=f2.make_proof(o2)
        proof2=copy.deepcopy(proof);proof2['body']['id']=f2.newid()
        proof2['sig']=f2.idents['H'].key.sign(canonical(['ZJJ-SIG-v1',proof2['protected'],proof2['body']]))
        # A changed proof cannot be the replayed original even with a valid signature.
        from research.reference_executor.wire import b64
        proof2['sig']=b64(proof2['sig'])
        with self.assertRaisesRegex(ProtocolError,'REPLAY'):
            self.w.accept(f2,o2,proof2)
        self.assertEqual(self.w.snapshot()['accepted_rows'],1)
    def test_same_intent_different_operation_conflict(self):
        f,o=ready();self.w.accept(f,o)
        f2,o2=ready(operation='YWJjZGVmZ2hpamtsbW5vcA')  # 16 bytes base64url
        with self.assertRaisesRegex(ProtocolError,'OPERATION_CONFLICT'):
            self.w.accept(f2,o2)
        self.assertEqual(self.w.snapshot()['accepted_rows'],1)
    def test_rollback_after_verification_injected(self):
        f,o=ready()
        with self.assertRaises(InjectedCrash):self.w.accept(f,o,inject='after_validation')
        self.assertEqual(self.w.snapshot()['accepted_rows'],0)
        f2,o2=ready();self.same(self.w.accept(f2,o2))
    def test_rollback_after_multiple_database_writes_injected(self):
        f,o=ready()
        with self.assertRaises(InjectedCrash):self.w.accept(f,o,inject='after_writes')
        s=DurablePayW(self.path).snapshot()
        self.assertEqual((s['accepted_rows'],s['reserved'],s['flight_rows'],s['audit_rows']),(0,0,0,0))
    def test_commit_before_reply_crash_keeps_original(self):
        f,o=ready()
        with self.assertRaises(InjectedCrash):self.w.accept(f,o,inject='after_commit')
        self.assertEqual(self.w.snapshot()['accepted_rows'],1)
        f2,o2=ready();self.assertTrue(DurablePayW(self.path).accept(f2,o2)['idempotent'])
        self.assertEqual(self.w.snapshot()['audit_rows'],1)
    def test_eight_thread_duplicate_submission_one_accept(self):
        work=[ready() for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies=list(pool.map(lambda x:DurablePayW(self.path).accept(*x), work))
        self.assertEqual(sum(not r['idempotent'] for r in replies),1)
        self.assertEqual(sum(r['idempotent'] for r in replies),7)
        self.assertEqual(len({msgref(r['acceptance']) for r in replies}),1)
        s=self.w.snapshot();self.assertEqual((s['accepted_rows'],s['reserved'],s['audit_rows']),(1,2000,1))
    def test_weak_capacity_rejected_without_state_mutation(self):
        path=Path(self.tmp.name)/'limited.sqlite';w=DurablePayW(path,capacity=1999)
        f,o=ready()
        with self.assertRaisesRegex(ProtocolError,'RESOURCE_LIMIT'):w.accept(f,o)
        self.assertEqual(w.snapshot()['reserved'],0)
    def test_archive_tamper_rejected(self):
        f,o=ready();self.w.accept(f,o)
        with closing(sqlite3.connect(self.path)) as c:
            row=c.execute('SELECT acceptance_bytes FROM accepted').fetchone()[0]
            obj=json.loads(row);obj['body']['payload']['accept_seq']='999'
            c.execute('UPDATE accepted SET acceptance_bytes=?',(json.dumps(obj),));c.commit()
        with self.assertRaisesRegex(ProtocolError,'ARCHIVE_BINDING|COMMIT_REF'):
            self.w.accepted_operation(o.action['operation_id'])
    def test_claim_single_dispatch_and_restart_unknown(self):
        f,o=ready();self.w.accept(f,o)
        attempt='YWJjZGVmZ2hpamtsbW5vcA'
        with self.assertRaisesRegex(ProtocolError,'CLAIM_WITNESS_NOT_VERIFIED'):
            self.w.claim(o.action['operation_id'],attempt)
        self.assertEqual(self.w.claim(o.action['operation_id'],attempt,witness_ok=True),'CLAIMED')
        self.assertEqual(DurablePayW(self.path).accepted_operation(o.action['operation_id'])['state'],'EFFECT_UNKNOWN')
        self.assertEqual(self.w.claim(o.action['operation_id'],attempt,witness_ok=True),'EXISTING')
        with self.assertRaisesRegex(ProtocolError,'NO_REDISPATCH'):
            self.w.claim(o.action['operation_id'],'AAAAAAAAAAAAAAAAAAAAAA',witness_ok=True)
        self.assertEqual(self.w.snapshot()['reserved'],2000)
    def test_claim_crash_rolls_back(self):
        f,o=ready();self.w.accept(f,o)
        with self.assertRaises(InjectedCrash):
            self.w.claim(o.action['operation_id'],'YWJjZGVmZ2hpamtsbW5vcA',witness_ok=True,inject='after_writes')
        self.assertEqual(DurablePayW(self.path).accepted_operation(o.action['operation_id'])['state'],'ACCEPTED')
    def test_flag_signed_path_is_persisted(self):
        samples=[case(i,action_class='HOLD' if i<=4 else 'PAY') for i in range(1,6)]
        f,o=ready(cases=samples)
        self.assertEqual(o.required,('ANOMALY',))
        r=self.w.accept(f,o);self.same(r)
        self.assertEqual(len(r['commit']['value']['review_refs']),1)

    def test_insufficient_signed_path_is_persisted(self):
        f,o=ready(cases=[case(1),case(2)])
        self.assertEqual(o.required,('LOW_EVIDENCE',))
        r=self.w.accept(f,o);self.same(r)
        self.assertEqual(len(r['commit']['value']['review_refs']),1)

    def test_returned_result_tamper_rejected(self):
        f,o=ready();self.w.accept(f,o)
        with closing(sqlite3.connect(self.path)) as c:
            blob=c.execute('SELECT reply_bytes FROM accepted').fetchone()[0]
            reply=json.loads(blob);reply['body']['payload']['status']='SUCCEEDED'
            c.execute('UPDATE accepted SET reply_bytes=?',(json.dumps(reply),));c.commit()
        with self.assertRaisesRegex(ProtocolError,'RESULT_STATUS'):
            self.w.accepted_operation(o.action['operation_id'])

    def test_ledger_integrity(self):
        self.assertEqual(self.w.integrity_check(),{'integrity':'ok','foreign_key_errors':0})
    def test_true_process_hard_kills_at_commit_boundaries(self):
        for point,committed in [('hard_after_validation',False),('hard_after_writes',False),('hard_after_commit',True)]:
            with self.subTest(point=point):
                db=Path(self.tmp.name)/(point+'.sqlite')
                command=[sys.executable,'-m','research.phase5.crash_worker',str(db),point]
                p=subprocess.run(command,cwd=str(Path(__file__).resolve().parents[2]),capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,79,(point,p.stdout,p.stderr))
                w=DurablePayW(db);s=w.snapshot()
                self.assertEqual(s['accepted_rows'],int(committed))
                self.assertEqual(s['reserved'],2000 if committed else 0)
                self.assertEqual(w.integrity_check()['integrity'],'ok')
                f,o=ready()
                result=w.accept(f,o)
                self.assertEqual(result['idempotent'],committed)
                self.assertEqual(w.snapshot()['accepted_rows'],1)

if __name__=='__main__':unittest.main()
