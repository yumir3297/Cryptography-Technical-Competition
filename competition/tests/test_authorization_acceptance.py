"""The common DENY registry and real IND R2 acceptance share one SQLite W."""
import tempfile
import unittest
import concurrent.futures
from pathlib import Path
from competition.profiles.industrial_seed import initialize
from competition.support.wire import ProtocolError, sortset

class AuthorizationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.seed=initialize(Path(self.folder.name),label='DEMO_UNCERTAIN'); self.addCleanup(self.seed.close)

    def deny_message(self):
        s=self.seed; op=s.op
        return s.actors['V'].sign('IND-DEMO-1','Review',s.issuer.scope,{'ctx':op['ctx'],'purpose':'QUALITY_REVIEW','verdict':'DENY','reason':'authenticated quality stop'},deps=op['deps'],aud=sortset([s.actors[a].name for a in ('H','G','X')]),at=op['at'],ttl=120)

    def test_deny_after_prepare_before_actual_accept_blocks_all_business_writes(self):
        s=self.seed; ticket=s.w.prepare(s.op); before=s.w.snapshot()
        s.w.publish_review(self.deny_message())
        with self.assertRaises(ProtocolError) as cm:
            s.w.accept(ticket['ticket_id'],proof=s.accept_proof(ticket['ticket_id']))
        self.assertEqual(cm.exception.code,'REVIEW_DENY')
        after=s.w.snapshot()
        for k in ('accepts','reserved','spent','calls'): self.assertEqual(before[k],after[k])

    def test_actual_accept_before_deny_preserves_original_fact_and_one_reservation(self):
        s=self.seed; t=s.w.prepare(s.op)
        first=s.w.accept(t['ticket_id'],proof=s.accept_proof(t['ticket_id']))
        s.w.publish_review(self.deny_message())
        recovered=s.w.accept(t['ticket_id'],proof=s.accept_proof(t['ticket_id']))
        self.assertEqual(first['frozen'],recovered['frozen'])
        self.assertEqual((s.w.snapshot()['accepts'],s.w.snapshot()['reserved']),(1,1))

    def test_simultaneous_deny_and_actual_accept_are_serialized(self):
        s=self.seed; t=s.w.prepare(s.op); proof=s.accept_proof(t['ticket_id']); message=self.deny_message()
        def accept():
            try:return s.w.accept(t['ticket_id'],proof=proof)['acceptance_state']
            except ProtocolError as exc:return exc.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            a=pool.submit(accept); d=pool.submit(s.w.publish_review,message)
            result=a.result(); publication=d.result()
        self.assertIn(result,('COMMITTED','REVIEW_DENY'))
        self.assertEqual(s.w.snapshot()['accepts'],int(result=='COMMITTED'))
        self.assertEqual(s.w.snapshot()['reserved'],int(result=='COMMITTED'))
        with s.w.db() as c:
            seqs=c.execute("SELECT seq,kind FROM a_journal WHERE kind IN ('PUBLICATION','ACCEPT_AUTHORIZATION') ORDER BY seq").fetchall()
        self.assertEqual(len(seqs),1+int(result=='COMMITTED'))
        self.assertEqual(seqs[0]['kind'],'ACCEPT_AUTHORIZATION' if result=='COMMITTED' else 'PUBLICATION')
