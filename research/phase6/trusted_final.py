"""Phase 6 research-only durable R2 tool final and controller registry.

Separate SQLite tool effect ledger and W acceptance ledger. The controller is a
trusted fixture; trust updates are signed, versioned, and bound to the tool
ledger. No physical effect, external identity service, or distributed atomicity.
"""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.phase5.durable_w import DurablePayW, _json
from research.reference_executor.wire import (ProtocolError, require, canonical, b64, raw,
    digest, keyid, rec_ref, strict_verify, good_point, is_id, number, action_hash)

FACT_FIELDS=('ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version',
             'destination','outcome','effect_id','no_late_effect','final_seq','finalized_at')
BASE_FIELDS=set(FACT_FIELDS)|{'method','iat','exp'}
TRUST_FIELDS={'issuer','tool','tool_version','destination','ledger_id','evidence_method',
              'public_key','kid','epoch','iat','exp'}


def final_fact(record):
    return {k:record['value'][k] for k in FACT_FIELDS}

def final_fact_id(record):
    return digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',record['profile'],record['scope'],final_fact(record)])

def final_sign_bytes(record):
    v=record['value']; t=v['attestation'];vv={k:v[k] for k in v if k!='attestation'}
    return canonical(['ZJJ-TOOL-FINAL-v2','2.6',record['profile'],record['scope'],vv,
                      {'issuer':t['issuer'],'kid':t['kid']}])


def _pub(priv):
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    return priv.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)

@dataclass(frozen=True)
class Controller:
    key: Ed25519PrivateKey
    name: str = 'c-root'
    @classmethod
    def fixture(cls):
        return cls(Ed25519PrivateKey.from_private_bytes(b'\x77'*32))
    @property
    def public_key(self):return _pub(self.key)
    def certify(self,scope,value,revision,ledger_head,ledger_origin,profile="PAY-1"):
        require(set(value)==TRUST_FIELDS,'TRUST_FIELDS')
        rec={'version':'2.6','profile':profile,'kind':'TOOL_TRUST','scope':scope,'value':value}
        claim={'record':rec,'revision':str(revision),'ledger_head':ledger_head,'ledger_origin':ledger_origin}
        return {'claim':claim,'root_kid':keyid(self.public_key),
                'signature':b64(self.key.sign(canonical(['ZJJ-CONTROL-TOOL-v1',claim])))}


def verify_certificate(cert,root_pub,expected_profile="PAY-1"):
    require(set(cert)=={'claim','root_kid','signature'},'CONTROL_FIELDS')
    require(cert['root_kid']==keyid(root_pub),'CONTROL_ROOT')
    claim=cert['claim'];require(set(claim)=={'record','revision','ledger_head','ledger_origin'},'CONTROL_FIELDS')
    strict_verify(root_pub,raw(cert['signature'],64),canonical(['ZJJ-CONTROL-TOOL-v1',claim]))
    rec=claim['record'];require(set(rec)=={'version','profile','kind','scope','value'},'RECORD_FIELDS')
    require((rec['version'],rec['profile'],rec['kind'])==('2.6',expected_profile,'TOOL_TRUST'),'TRUST_KIND')
    v=rec['value'];require(set(v)==TRUST_FIELDS and v['evidence_method']=='tool-final-v2','TRUST_FIELDS')
    require(keyid(raw(v['public_key'],32))==v['kid'] and good_point(raw(v['public_key'],32)),'TRUST_KEY')
    require(number(v['epoch'],True) and number(v['iat']) and number(v['exp']) and
            0<int(v['exp'])-int(v['iat'])<=31536000,'TRUST_TIME')
    require(number(claim['revision'],True) and claim['ledger_head'] and len(raw(claim['ledger_origin'],32))==32,'TRUST_REVISION')
    for k in ('issuer','tool','tool_version','destination','ledger_id'):require(is_id(v[k]),'TRUST_ID')
    return rec


class ToolLedger:
    """Separate durable simulator; never creates final facts from a query/missing row."""
    def __init__(self,path,ledger_id='ledger1',profile='PAY-1'):
        self.path=str(path);self.ledger_id=ledger_id;self.profile=profile
        with self._db() as c:
            c.executescript('''
             CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY CHECK(id=1),ledger TEXT NOT NULL, seq INTEGER NOT NULL, origin TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS finalized(operation_id TEXT PRIMARY KEY, attempt TEXT NOT NULL UNIQUE,
                 fact TEXT NOT NULL, final_seq INTEGER NOT NULL UNIQUE, effect_id TEXT UNIQUE);
            ''')
            c.execute('INSERT OR IGNORE INTO meta VALUES(1,?,0,?)',(ledger_id,b64(os.urandom(32))))
            require(c.execute('SELECT ledger FROM meta').fetchone()[0]==ledger_id,'LEDGER_MISMATCH')
    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,isolation_level=None,timeout=20)
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA busy_timeout=20000')
        try:yield c
        finally:c.close()
    @property
    def origin(self):
        with self._db() as c:return c.execute('SELECT origin FROM meta WHERE id=1').fetchone()[0]
    def all_facts(self):
        with self._db() as c:
            return [json.loads(x[0]) for x in c.execute('SELECT fact FROM finalized ORDER BY final_seq')]
    def head(self):
        return digest(['ZJJ-LEDGER-SNAPSHOT-RESEARCH-v1',self.ledger_id,self.all_facts()])
    def freeze(self,scope,action,attempt,*,outcome='SUCCEEDED',effect_id='effect1',at=105):
        require(outcome in ('SUCCEEDED','FAILED_CONFIRMED'),'OUTCOME')
        require(is_id(effect_id) if outcome=='SUCCEEDED' else effect_id=='','EFFECT_ID')
        op=action['operation_id']
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                found=c.execute('SELECT fact FROM finalized WHERE operation_id=?',(op,)).fetchone()
                if found:
                    fact=json.loads(found[0]);require(fact['dispatch_attempt']==attempt,'ATTEMPT_CONFLICT')
                else:
                    seq=c.execute('SELECT seq FROM meta').fetchone()[0]+1
                    fact={'ledger_id':self.ledger_id,'operation_id':op,
                          'action_hash':action_hash(self.profile,action),'dispatch_attempt':attempt,
                          'tool':action['tool'],'tool_version':action['tool_version'],
                          'destination':action['destination'],'outcome':outcome,
                          'effect_id':effect_id,'no_late_effect':outcome=='FAILED_CONFIRMED',
                          'final_seq':str(seq),'finalized_at':str(at)}
                    c.execute('INSERT INTO finalized VALUES(?,?,?,?,?)',(op,attempt,_json(fact),seq,effect_id or None))
                    c.execute('UPDATE meta SET seq=?',(seq,))
                c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:c.execute('ROLLBACK')
                raise
        return fact
    def lookup(self,op,attempt):
        with self._db() as c:
            row=c.execute('SELECT fact FROM finalized WHERE operation_id=? AND attempt=?',(op,attempt)).fetchone()
            return json.loads(row[0]) if row else None
    def reattest(self,scope,fact,signer,issuer,at,trust_exp):
        original=self.lookup(fact['operation_id'],fact['dispatch_attempt'])
        require(original is not None and original==fact,'LEDGER_FACT_NOT_FOUND')
        require(int(at)>=int(fact['finalized_at']) and int(at)+120<=int(trust_exp),'ATTEST_TIME')
        v={'method':'tool-final-v2',**fact,'iat':str(at),'exp':str(at+120),
           'attestation':{'issuer':issuer,'kid':keyid(_pub(signer)),'sig':''}}
        rec={'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':scope,'value':v}
        rec['value']['attestation']['sig']=b64(signer.sign(final_sign_bytes(rec)))
        return rec


class FinalW(DurablePayW):
    """Controller-certified tool trust + immutable R2 facts + one-time W settlement.

    Does not implement the complete current-policy/dependency claim guard. The
    pre-existing Phase-5 signed acceptance is the trusted starting fixture.
    """
    def __init__(self,path,root_pub,**kw):
        self.root_pub=root_pub
        super().__init__(path,**kw)
        with self._read() as c:
            c.executescript('''
             CREATE TABLE IF NOT EXISTS tool_trust(id INTEGER PRIMARY KEY CHECK(id=1),certificate TEXT NOT NULL,
                epoch INTEGER NOT NULL, revision INTEGER NOT NULL, ledger_head TEXT NOT NULL, ledger_origin TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS dispatch_witness(operation_id TEXT PRIMARY KEY,attempt TEXT NOT NULL UNIQUE,
                tool_trust_ref TEXT NOT NULL,ledger_id TEXT NOT NULL,scope TEXT NOT NULL, action_hash TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS settled(operation_id TEXT PRIMARY KEY, fact_id TEXT NOT NULL, fact TEXT NOT NULL,
                first_record TEXT NOT NULL,record_ref TEXT NOT NULL,ledger_id TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS final_seen(record_ref TEXT PRIMARY KEY,operation_id TEXT NOT NULL,record TEXT NOT NULL);
             CREATE UNIQUE INDEX IF NOT EXISTS final_effect_unique ON settled(ledger_id, json_extract(fact, '$.effect_id'))
                WHERE json_extract(fact, '$.effect_id') != '';
             CREATE UNIQUE INDEX IF NOT EXISTS final_seq_unique ON settled(ledger_id, json_extract(fact, '$.final_seq'));
            ''')
    def activate(self,cert,ledger:ToolLedger,now=100):
        rec=verify_certificate(cert,self.root_pub);v=rec['value'];claim=cert['claim']
        require(rec['scope']['scenario']=='payment' and v['tool']=='pay-sim' and
                v['tool_version']=='1' and v['destination']=='pay-sim-dest', 'TRUST_BINDING')
        require(int(v['iat'])<=now<int(v['exp']),'TRUST_EXPIRED')
        require(v['ledger_id']==ledger.ledger_id and claim['ledger_head']==ledger.head() and claim['ledger_origin']==ledger.origin,'CONTINUITY_UNKNOWN')
        with self._tx() as c:
            old=c.execute('SELECT * FROM tool_trust WHERE id=1').fetchone()
            if old:
                prev=json.loads(old['certificate'])['claim']['record']
                require(prev['scope']==rec['scope'] and prev['value']['ledger_id']==v['ledger_id'], 'LEDGER_MISMATCH')
                require(old['ledger_origin']==ledger.origin,'CONTINUITY_UNKNOWN')
                require(int(v['epoch'])>old['epoch'] and int(claim['revision'])>old['revision'],'EPOCH_REPLAY')
                # A persistent ledger snapshot must contain the previously
                # confirmed W facts; merely matching a ledger_id is insufficient.
                for row in c.execute('SELECT fact FROM settled WHERE ledger_id=?',(v['ledger_id'],)):
                    require(json.loads(row['fact']) in ledger.all_facts(),'CONTINUITY_UNKNOWN')
            c.execute('''INSERT INTO tool_trust VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                certificate=excluded.certificate,epoch=excluded.epoch,revision=excluded.revision,
                ledger_head=excluded.ledger_head,ledger_origin=excluded.ledger_origin''',(_json(cert),int(v['epoch']),int(claim['revision']),claim['ledger_head'],claim['ledger_origin']))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('TOOL_TRUST','-',_json({'trust_ref':rec_ref(rec),'epoch':v['epoch']})))
        return rec_ref(rec)
    def _current_trust(self,c,now):
        row=c.execute('SELECT certificate FROM tool_trust WHERE id=1').fetchone()
        require(row is not None,'TRUST_MISSING')
        cert=json.loads(row[0]);r=verify_certificate(cert,self.root_pub)
        require(int(r['value']['iat'])<=now<int(r['value']['exp']),'TRUST_EXPIRED')
        return r
    def claim_bound(self,operation_id,attempt,*,now=100):
        """No client-supplied witness_ok. Requires current C-certified tool mapping.
        Current policy/deps of the signed operation are a known unimplemented guard.
        """
        raw(attempt,16)
        with self._tx() as c:
            trust=self._current_trust(c,now);v=trust['value']
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None,'MISSING_ACCEPTANCE')
            archived=self._load(row)['commit'];action=archived['value']['action']
            require(trust['scope']==action['scope'] and all(action[k]==v[k] for k in ('tool','tool_version','destination')),'TOOL_BINDING')
            earlier=c.execute('SELECT * FROM dispatch_witness WHERE operation_id=?',(operation_id,)).fetchone()
            if earlier:
                require(earlier['attempt']==attempt,'NO_REDISPATCH')
                return 'EXISTING'
            require(row['state']=='ACCEPTED' and row['exec_calls']==0,'NO_REDISPATCH')
            require(now<int(archived['value']['dispatch_before']),'DISPATCH_EXPIRED')
            require(action==archived['value']['frozen_tool_request'],'FROZEN_ACTION_MISMATCH')
            c.execute('''INSERT INTO dispatch_witness VALUES(?,?,?,?,?,?)''',
                (operation_id,attempt,rec_ref(trust),v['ledger_id'],_json(action['scope']),action_hash('PAY-1',action)))
            c.execute('''UPDATE accepted SET state='EFFECT_UNKNOWN',exec_calls=1,dispatch_attempt=?
                WHERE operation_id=? AND state='ACCEPTED' ''',(attempt,operation_id))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',('CLAIM_R2',operation_id,_json({'attempt':attempt,'ledger':v['ledger_id']})))
        return 'CLAIMED'
    def _verify_final(self,c,record,now):
        require(type(record) is dict and set(record)=={'version','profile','kind','scope','value'},'FINAL_FIELDS')
        require((record['version'],record['profile'],record['kind'])==('2.6','PAY-1','TOOL_FINAL'),'FINAL_KIND')
        v=record['value'];require(set(v)==BASE_FIELDS|{'attestation'},'FINAL_FIELDS')
        require(v['method']=='tool-final-v2' and type(v['attestation']) is dict and
                set(v['attestation'])=={'issuer','kid','sig'},'FINAL_FIELDS')
        require(v['outcome'] in ('SUCCEEDED','FAILED_CONFIRMED'),'FINAL_OUTCOME')
        require((v['outcome']=='SUCCEEDED' and is_id(v['effect_id']) and v['no_late_effect'] is False)
                or (v['outcome']=='FAILED_CONFIRMED' and v['effect_id']=='' and v['no_late_effect'] is True), 'FINAL_OUTCOME')
        require(number(v['final_seq'],True) and number(v['finalized_at']) and number(v['iat']) and number(v['exp'])
                and 0<int(v['exp'])-int(v['iat'])<=900 and int(v['finalized_at'])<=int(v['iat']), 'FINAL_TIME')
        trust=self._current_trust(c,now);t=trust['value'];a=v['attestation']
        require(int(v['iat'])<=now<int(v['exp']) and int(v['exp'])<=int(t['exp']),'FINAL_EXPIRED')
        require(a['issuer']==t['issuer'] and a['kid']==t['kid'],'FINAL_SIGNER')
        require(v['ledger_id']==t['ledger_id'] and all(v[k]==t[k] for k in ('tool','tool_version','destination')),'LEDGER_MISMATCH')
        strict_verify(raw(t['public_key'],32),raw(a['sig'],64),final_sign_bytes(record))
        op=v['operation_id'];w=c.execute('SELECT * FROM dispatch_witness WHERE operation_id=?',(op,)).fetchone()
        row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(op,)).fetchone()
        require(row is not None and w is not None,'DISPATCH_MISSING')
        action=self._load(row)['commit']['value']['action']
        require(record['scope']==action['scope'] and w['scope']==_json(action['scope'])
                and w['ledger_id']==v['ledger_id'] and w['attempt']==v['dispatch_attempt']
                and w['action_hash']==v['action_hash'] == action_hash('PAY-1',action)
                and v['operation_id']==op,'FINAL_BINDING')
        return row,final_fact_id(record)
    def settle(self,record,*,now=110):
        """Trusted current proof, same fact reattestation, and contradiction HALT.
        Failed authentication/binding cannot turn a valid operation into HALTED.
        """
        op=record.get('value',{}).get('operation_id') if isinstance(record,dict) else None
        with self._tx() as c:
            # Exact previously-confirmed bytes can be replayed as historical
            # evidence after expiry; only the original archived bytes qualify.
            rr=rec_ref(record)
            prior=c.execute('SELECT record FROM final_seen WHERE record_ref=?',(rr,)).fetchone()
            if prior is not None:
                require(json.loads(prior['record'])==record,'RECORD_COLLISION')
                saved=c.execute('SELECT fact_id FROM settled WHERE operation_id=?',(op,)).fetchone()
                require(saved is not None,'FINAL_STATE')
                return {'status':c.execute('SELECT state FROM accepted WHERE operation_id=?',(op,)).fetchone()[0],
                        'fact_id':saved['fact_id'],'idempotent':True,'historical':True}
            row,fid=self._verify_final(c,record,now)
            prev=c.execute('SELECT * FROM settled WHERE operation_id=?',(op,)).fetchone()
            if prev:
                if prev['fact_id']!=fid or json.loads(prev['fact'])!=final_fact(record):
                    c.execute("UPDATE accepted SET state='HALTED' WHERE operation_id=?",(op,))
                    c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                              ('CONTRADICTION',op,_json({'old':prev['fact_id'],'new':fid})))
                    return {'status':'HALTED','fact_id':prev['fact_id'],'idempotent':False,'conflict':True}
                c.execute('INSERT INTO final_seen VALUES(?,?,?)',(rr,op,_json(record)))
                return {'status':row['state'],'fact_id':fid,'idempotent':True,'historical':False}
            require(row['state']=='EFFECT_UNKNOWN' and row['settlement_count']==0,'FINAL_STATE')
            require(row['exec_calls']==1 and row['dispatch_attempt']==record['value']['dispatch_attempt'],'FINAL_STATE')
            amt=row['amount'];outcome=record['value']['outcome']
            a=c.execute('SELECT * FROM account WHERE id=1').fetchone()
            require(a['reserved']>=amt and c.execute('SELECT operation_id FROM flight WHERE task_id=?',(row['task_id'],)).fetchone()[0]==op,'ACCOUNT_INTEGRITY')
            state='SUCCEEDED' if outcome=='SUCCEEDED' else 'FAILED_CONFIRMED'
            c.execute('UPDATE account SET reserved=reserved-?, spent=spent+?,revision=revision+1 WHERE id=1',
                      (amt,amt if state=='SUCCEEDED' else 0))
            c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(row['task_id'],op))
            c.execute('UPDATE accepted SET state=?,settlement_count=1 WHERE operation_id=?',(state,op))
            c.execute('INSERT INTO settled VALUES(?,?,?,?,?,?)',
                      (op,fid,_json(final_fact(record)),_json(record),rr,record['value']['ledger_id']))
            c.execute('INSERT INTO final_seen VALUES(?,?,?)',(rr,op,_json(record)))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('SETTLED',op,_json({'fact_id':fid,'outcome':outcome})))
            return {'status':state,'fact_id':fid,'idempotent':False,'historical':False}
