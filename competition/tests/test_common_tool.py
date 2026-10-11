"""Real W signatures, independent effects, and crash-before-ACK recovery."""
import copy
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from research.phase6.trusted_final import Controller, final_fact_id, final_sign_bytes
from research.phase18.key_broker import PROFILE_SCOPES
from research.reference_executor.wire import ProtocolError, action_hash, b64, canonical, digest, keyid, rec_ref, strict_verify, raw
from competition.core.signing import ClockClient


def public(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


class CommonToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def fixture(self, profile='PAY-1', crash=False, ttl=120):
        from competition.tools.common_tool import CommonToolLedger, ToolGateway, create_tool_database
        folder = self.folder / profile
        folder.mkdir(exist_ok=True)
        root, w, tool = (Ed25519PrivateKey.generate() for _ in range(3))
        for name, key in [('C', root), ('tool', tool)]:
            (folder / (name+'.key')).write_bytes(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        meta = create_tool_database(folder/'tool.sqlite', profile, 'ledger-test')
        scope = PROFILE_SCOPES[profile]
        tools = {'PAY-1':'pay-sim','IND-DEMO-1':'line-sort-sim','MED-DEMO-1':'med-order-sim'}
        now = int(time.time())
        trust = {'issuer':'sim-tool','tool':tools[profile],'tool_version':'1','destination':'sim-dest',
                 'ledger_id':meta['ledger_id'],'evidence_method':'tool-final-v2','public_key':b64(public(tool)),
                 'kid':keyid(public(tool)),'epoch':'1','iat':str(now-10),'exp':str(now+1800)}
        cert = Controller(root).certify(scope, trust, 1, digest(['ZJJ-LEDGER-SNAPSHOT-RESEARCH-v1','ledger-test',[]]), meta['ledger_origin'], profile)
        payloads = {
            'PAY-1':{'order_id':'order1','stage':'settle','payer':'alice','payee':'bob','amount_minor':'731','currency':'CNY','purpose':'order-settlement'},
            'IND-DEMO-1':{'line_id':'line1','station_id':'station1','unit_id':'unit1','batch_id':'batch1','inspection_cycle':'1','phase':'INITIAL','route':'QUARANTINE'},
            'MED-DEMO-1':{'synthetic_patient_id':'patient1','encounter_id':'enc1','order_group_id':b64(b'g'*16),'phase':'SUBMIT','template_id':'DEMO-ORDER-B','record_ref':b64(b'r'*32),'destination_system':'med-demo-ledger'},
        }
        action = {'scope':scope,'operation_id':b64(b'o'*16),'principal':'principal','holder':'holder','holder_kid':keyid(public(w)),
                  'executor':'executor','tool':trust['tool'],'tool_version':'1','destination':'sim-dest','payload':payloads[profile]}
        cl = {'profile':profile,'scope':scope,'operation_id':action['operation_id'],'attempt_id':b64(b'a'*16),
              **meta,'action':action,'action_hash':action_hash(profile,action),'commit_ref':b64(b'c'*32),
              'acceptance_ref':b64(b'e'*32),'tool_trust_ref':rec_ref(cert['claim']['record']),'issued_at':str(now-5),'expires':str(now+ttl)}
        clock = ClockClient(folder/'C.key',folder/'clock.sqlite')
        self.addCleanup(clock.close)
        ledger = CommonToolLedger(folder/'tool.sqlite',profile,certificate=cert,root_public=public(root),w_public=public(w),private_key=tool,clock=clock)
        config = {'database':str(folder/'tool.sqlite'),'profile':profile,'certificate':cert,'root_public':b64(public(root)),
                  'w_public':b64(public(w)),'tool_key_path':str(folder/'tool.key'),'clock_key_path':str(folder/'C.key'),
                  'clock_database':str(folder/'clock.sqlite'),'crash_after_commit':crash}
        configpath = folder/'config.json'
        configpath.write_text(json.dumps(config),encoding='utf-8')
        packet = self.sign(w,cl)
        return ledger, ToolGateway(configpath), packet, w, tool

    @staticmethod
    def sign(w,cl,query=False):
        return {'claim':cl,'signature':b64(w.sign(canonical(['COMP-W-TOOL-QUERY-v1' if query else 'COMP-W-TOOL-EXEC-v1',cl])))}

    def query(self,w,packet):
        now = int(time.time())
        cl = {**packet['claim'],'query_id':b64(b'q'*16),'iat':str(now-1),'exp':str(now+60)}
        return self.sign(w,cl,True)

    def test_three_profiles_persist_actual_payload_and_immutable_fact(self):
        for profile, table in [('PAY-1','payments'),('IND-DEMO-1','industrial_routes'),('MED-DEMO-1','medical_orders')]:
            with self.subTest(profile=profile):
                ledger, _, packet, w, tool = self.fixture(profile)
                response = ledger.execute_once(packet)
                self.assertEqual(response['state'],'SUCCEEDED')
                strict_verify(public(tool), raw(response['record']['value']['attestation']['sig'],64), final_sign_bytes(response['record']))
                strict_verify(public(tool),raw(response['checkpoint']['signature'],64),canonical(['COMP-TOOL-CHECKPOINT-v1',response['checkpoint']['claim']]))
                first = ledger.snapshot()
                self.assertEqual(len(first['effects'][table]),1)
                self.assertEqual(first['effects'][table][0]['payload'],packet['claim']['action']['payload'])
                repeated = ledger.execute_once(packet)
                queried = ledger.query_attempt(self.query(w,packet))
                self.assertEqual(final_fact_id(response['record']),final_fact_id(repeated['record']))
                self.assertEqual(final_fact_id(response['record']),final_fact_id(queried['record']))
                self.assertEqual(ledger.snapshot()['effects'],first['effects'])
                self.assertEqual(ledger.snapshot()['finalfacts'],first['finalfacts'])
                self.assertEqual(first['meta']['high_water'],'1')

    def test_tool_decision_after_dispatch_expiry_rolls_back_every_effect(self):
        ledger,_,packet,_,_=self.fixture(ttl=2);original=ledger._counts;calls=[]
        def delayed(c):
            result=original(c);calls.append(True)
            if len(calls)==1:time.sleep(2.05)
            return result
        ledger._counts=delayed
        with self.assertRaises(ProtocolError):ledger.execute_once(packet)
        snapshot=ledger.snapshot();self.assertEqual(snapshot['finalfacts'],[])
        self.assertEqual(snapshot['effects']['payments'],[])

    def test_unknown_query_never_creates_effect_or_failed_final(self):
        ledger, _, packet, w, _ = self.fixture()
        response = ledger.query_attempt(self.query(w,packet))
        self.assertEqual((response['state'],response['record']),('EFFECT_UNKNOWN',None))
        self.assertEqual(response['checkpoint']['claim']['final_fact_id'],'')
        self.assertEqual(ledger.snapshot()['meta']['high_water'],'0')
        self.assertEqual(ledger.snapshot()['requests'],[])

    def test_bad_signatures_binding_and_request_conflicts_have_no_second_effect(self):
        ledger, _, packet, w, _ = self.fixture()
        bad = copy.deepcopy(packet); bad['signature'] = b64(b'\x00'*64)
        with self.assertRaises(ProtocolError): ledger.execute_once(bad)
        for field, value in [('profile','MED-DEMO-1'),('attempt_id','notb16'),('ledger_id','other-ledger'),('ledger_origin',b64(b'x'*32)),('action_hash',b64(b'x'*32))]:
            bad = copy.deepcopy(packet['claim']); bad[field] = value
            with self.assertRaises(ProtocolError): ledger.execute_once(self.sign(w,bad))
        ledger.execute_once(packet)
        bad = copy.deepcopy(packet['claim']); bad['action']['payload']['amount_minor']='999'; bad['action_hash']=action_hash('PAY-1',bad['action'])
        with self.assertRaises(ProtocolError): ledger.execute_once(self.sign(w,bad))
        bad = copy.deepcopy(packet['claim']); bad['attempt_id']=b64(b'b'*16)
        with self.assertRaises(ProtocolError): ledger.query_attempt(self.query(w,self.sign(w,bad)))
        self.assertEqual(len(ledger.snapshot()['effects']['payments']),1)

    def test_real_child_commit_exit_98_query_recovers_same_fact(self):
        ledger, gateway, packet, w, _ = self.fixture(crash=True)
        lost = gateway.execute(packet)
        self.assertEqual((lost['state'],lost['record'],lost['trace']['exit_code']),('EFFECT_UNKNOWN',None,98))
        saved = ledger.snapshot()['finalfacts'][0]
        recovered = gateway.query(self.query(w,packet))
        self.assertEqual(recovered['state'],'SUCCEEDED')
        self.assertEqual(final_fact_id(recovered['record']),saved['final_fact_id'])
        self.assertEqual(recovered['record']['value']['final_seq'],'1')
        self.assertNotEqual(lost['trace']['pid'],recovered['trace']['pid'])
        self.assertEqual(len(ledger.snapshot()['effects']['payments']),1)

    def test_query_uses_new_window_after_original_dispatch_expiry(self):
        ledger, _, packet, w, _ = self.fixture(ttl=3)
        result=ledger.execute_once(packet)
        time.sleep(max(0,int(packet['claim']['expires'])-time.time()+0.1))
        recovered=ledger.query_attempt(self.query(w,packet))
        self.assertEqual(final_fact_id(result['record']),final_fact_id(recovered['record']))
        with self.assertRaises(ProtocolError): ledger.execute_once(packet)

    def test_missing_or_corrupt_ledger_refuses_continuity(self):
        from competition.tools.common_tool import create_tool_database
        ledger, _, _, _, _ = self.fixture()
        with self.assertRaises(ProtocolError): create_tool_database(ledger.path,'PAY-1','ledger-test')
        import sqlite3
        with closing(sqlite3.connect(ledger.path)) as c:
            c.execute("UPDATE tool_meta SET ledger_origin=?",(b64(b'x'*32),)); c.commit()
        with self.assertRaises(ProtocolError): ledger.snapshot()

    def test_query_requires_w_signature_and_never_accepts_execution_flags(self):
        ledger, gateway, packet, w, _ = self.fixture()
        query=self.query(w,packet)
        bad=copy.deepcopy(query); bad['signature']=b64(b'\x00'*64)
        with self.assertRaises(ProtocolError): ledger.query_attempt(bad)
        cl=copy.deepcopy(query['claim']); cl['crash_after_commit']=True
        with self.assertRaises(ProtocolError): gateway.query(self.sign(w,cl,True))
        self.assertEqual(ledger.snapshot()['meta']['high_water'],'0')

    def test_final_fact_and_effect_rows_are_immutable_and_partial_loss_is_rejected(self):
        import sqlite3
        ledger, _, packet, w, _=self.fixture()
        ledger.execute_once(packet)
        with closing(sqlite3.connect(ledger.path)) as c:
            for command in ("UPDATE tool_finalfacts SET final_seq=2", "DELETE FROM payments"):
                with self.assertRaises(sqlite3.IntegrityError): c.execute(command)
            # Simulated disk damage deliberately bypasses the application latch.
            c.execute('DROP TRIGGER payments_delete')
            c.execute('DELETE FROM payments')
            c.commit()
        with self.assertRaises(ProtocolError): ledger.query_attempt(self.query(w,packet))


if __name__ == '__main__':
    unittest.main()
