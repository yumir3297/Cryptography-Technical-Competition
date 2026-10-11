"""Independent X process signs only committed bytes with current C credentials."""
import copy
import importlib
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat,PrivateFormat,NoEncryption
from research.reference_executor.wire import b64,raw,canonical,keyid,digest,rec_ref,action_hash,strict_verify,ProtocolError,sortset
from research.phase18.key_broker import PROFILE_SCOPES


class CommonReceiptTests(unittest.TestCase):
    def setUp(self):
        try:self.module=importlib.import_module('competition.core.common_receipt')
        except ModuleNotFoundError:self.fail('Missing independent committed-receipt signer')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.root=Ed25519PrivateKey.generate();self.key=Ed25519PrivateKey.generate()
        self.pub=self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        self.rootpub=self.root.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        self.kid=keyid(self.pub);self.profile='PAY-1';self.scope=PROFILE_SCOPES[self.profile];self.oid=b64(b'o'*16)
        self.keypath=self.folder/'X.key';self.keypath.write_bytes(self.key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()))
        self.dbpath=self.folder/'w.sqlite';now=int(time.time());self.now=now
        self.action={'scope':self.scope,'operation_id':self.oid,'principal':'principal','holder':'holder','holder_kid':b64(b'h'*32),'executor':'executor',
             'tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest',
             'payload':{'order_id':'order1','stage':'settle','payer':'payer','payee':'payee','amount_minor':'731','currency':'CNY','purpose':'order-settlement'}}
        ctx={k:self.action[k] for k in ('scope','operation_id','principal','holder','holder_kid','executor')}
        ctx.update(action_hash=action_hash(self.profile,self.action),policy_ref=b64(b'p'*32),basis_ref=b64(b'b'*32))
        self.core={'protected':{'proto':'ZJJ-AAP','version':'2.6','profile':self.profile,'alg':'Ed25519','type':'Acceptance','issuer':'executor','kid':self.kid},
            'body':{'id':b64(b'i'*16),'scope':self.scope,'iat':str(now-2),'exp':str(now+120),'aud':['holder'],'refs':[],'deps':[],
             'payload':{'ctx':ctx,'permit_ref':b64(b'P'*32),'proof_ref':b64(b'F'*32),'authorization_ref':b64(b'A'*32),'review_refs':[],
                'accept_seq':'1','accepted_at':str(now-2),'commit_record_ref':b64(b'C'*32),'dispatch_before':str(now+60)}}}
        self.core['body']['refs']=sortset([self.core['body']['payload'][k] for k in ('permit_ref','proof_ref','authorization_ref')])
        self.frozen={'op':{'action':self.action,'ctx':ctx},'acceptance_core':self.core,'commit_ref':b64(b'C'*32),'accepted_at':str(now-2),'x_public':b64(self.pub),'x_kid':self.kid}
        self.keyvalue={'subject':'executor','public_key':b64(self.pub),'kid':self.kid,'epoch':'1','purposes':['Acceptance','Challenge','Result'],
            'iat':str(now-5),'exp':str(now+600),'root_generation':'1','enrollment_ref':b64(b'e'*32)}
        self.rolevalue={'subject':'executor','role':'EXECUTOR','epoch':'1','scope_set':[self.scope],'tool_set':['pay-sim'],
            'destination_set':['pay-sim-dest'],'constraints':{'payer_set':['payer'],'max_amount_minor':'1000'},'iat':str(now-5),'exp':str(now+600)}
        with closing(sqlite3.connect(self.dbpath)) as c:
            c.execute('CREATE TABLE a_current(profile TEXT,namespace TEXT,key TEXT,revision INTEGER,ref TEXT,record TEXT,active INTEGER,certificate TEXT,PRIMARY KEY(profile,namespace,key))')
            c.execute('CREATE TABLE w_operation(profile TEXT,oid TEXT,frozen TEXT,receipt TEXT,PRIMARY KEY(profile,oid))')
            c.execute('INSERT INTO w_operation VALUES(?,?,?,NULL)',(self.profile,self.oid,json.dumps(self.frozen)))
            c.commit()
        self.publish('KEY',self.keyvalue)
        self.publish('ROLE',self.rolevalue)
        self.signer=self.module.CommonReceiptSigner(self.keypath,self.dbpath,self.rootpub,self.profile)
        self.addCleanup(self.signer.close)

    def publish(self,namespace,value,active=True,signature=None):
        key=[self.kid] if namespace=='KEY' else [self.scope[k] for k in ('domain','tenant','scenario')]+['executor','EXECUTOR']
        record={'version':'2.6','profile':self.profile,'kind':namespace+'_GRANT','scope':self.scope,'value':copy.deepcopy(value)}
        cl={'profile':self.profile,'scope':self.scope,'namespace':namespace,'key':key,'previous_revision':'0','record':record,'active':active,'enrollment':{}}
        cert={'claim':cl,'signature':signature or b64(self.root.sign(canonical(['COMP-APP-C-PUBLISH-v1',cl])))}
        with closing(sqlite3.connect(self.dbpath)) as c:
            c.execute('INSERT OR REPLACE INTO a_current VALUES(?,?,?,?,?,?,?,?)',(self.profile,namespace,json.dumps(key,sort_keys=True,separators=(',',':')),1,rec_ref(record),json.dumps(record),int(active),json.dumps(cert)));c.commit()

    def test_committed_receipt_is_signed_by_actual_other_process(self):
        result=self.signer.sign(self.profile,self.oid,self.core)
        strict_verify(self.pub,raw(result['sig'],64),canonical(['ZJJ-SIG-v1',result['protected'],result['body']]))
        self.assertEqual({k:result[k] for k in ('protected','body')},self.core)
        import os
        self.assertNotEqual(self.signer.info['pid'],os.getpid())
        with closing(sqlite3.connect(self.dbpath)) as c:
            self.assertIsNone(c.execute('SELECT receipt FROM w_operation').fetchone()[0])

    def test_uncommitted_or_modified_core_cannot_be_signed(self):
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,b64(b'n'*16),self.core)
        changed=copy.deepcopy(self.core);changed['body']['payload']['accept_seq']='2'
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,changed)
        with self.assertRaises(ProtocolError):self.signer.sign('MED-DEMO-1',self.oid,self.core)

    def test_revoked_expired_and_bad_c_certificate_cannot_sign(self):
        self.publish('ROLE',self.rolevalue,active=False)
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,self.core)
        expired=copy.deepcopy(self.rolevalue);expired['exp']=str(self.now-1)
        self.publish('ROLE',expired)
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,self.core)
        self.publish('ROLE',self.rolevalue,signature=b64(b'\x00'*64))
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,self.core)

    def test_original_business_constraints_are_checked_in_child(self):
        reduced=copy.deepcopy(self.rolevalue);reduced['constraints']['max_amount_minor']='700'
        self.publish('ROLE',reduced)
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,self.core)
        self.publish('ROLE',self.rolevalue)
        wrong=copy.deepcopy(self.keyvalue);wrong['purposes']=['Challenge','Result']
        self.publish('KEY',wrong)
        with self.assertRaises(ProtocolError):self.signer.sign(self.profile,self.oid,self.core)


if __name__=='__main__':unittest.main()
