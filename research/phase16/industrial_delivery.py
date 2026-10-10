"""Phase16 IND trusted-delivery laboratory: durable W outbox + authenticated tool ledger.

W's transport signing key is *not* a C/E/X authority key. The tool independently
pins the W transport public key. The simulator makes one durable decision, not
a claim of a real physical effect. No original v2.6 schema is changed.
"""
from __future__ import annotations
import json
import hashlib
import os
import sqlite3
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from research.phase6.trusted_final import ToolLedger
from research.reference_executor.wire import (
    ProtocolError, require, canonical, raw, b64, strict_verify, action_hash,
    rec_ref, digest, good_point, keyid,
)

DOMAIN='ZJJ-W-TOOL-DELIVERY-RESEARCH-v1'
FIELDS={'profile','scope','operation_id','attempt','ledger_id','ledger_origin',
        'action','action_hash','commit_ref','tool_trust_ref'}

def public_key(priv):
    return priv.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)

def canon(obj):
    return canonical(obj).decode('utf-8')

class WDispatchOutbox:
    """W-side transport adapter after the existing W.claim_r2 transaction.

    The only signing capability is a dedicated W->Tool *delivery* credential,
    not a controller/source/executor signing key. Persistent outbox replays the
    exact same bytes after loss of response or service restart.
    """
    def __init__(self, w_db, profile, *, signer):
        require(profile=='IND-DEMO-1','IND_ONLY')
        require(isinstance(signer,Ed25519PrivateKey),'TRANSPORT_KEY')
        self.w_db=str(w_db);self.profile=profile;self.signer=signer
        require(Path(self.w_db).is_file(),'W_DB_UNAVAILABLE')
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS p16_outbox (
                operation_id TEXT PRIMARY KEY, attempt TEXT NOT NULL UNIQUE,
                envelope TEXT NOT NULL, binding_ref TEXT NOT NULL
            )""")

    def _db(self):
        c=sqlite3.connect(self.w_db,timeout=20,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA busy_timeout=20000')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=FULL')
        return c

    def issue(self,operation_id,*,ledger):
        require(isinstance(ledger,ToolLedger) and ledger.profile==self.profile,'LEDGER_BINDING')
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=c.execute('SELECT * FROM p16_outbox WHERE operation_id=?',(operation_id,)).fetchone()
                if old:
                    packet=json.loads(old['envelope'])
                    require(old['binding_ref']==digest([DOMAIN,packet['claim']]),'OUTBOX_INTEGRITY')
                    require(packet['claim']['ledger_id']==ledger.ledger_id and
                            packet['claim']['ledger_origin']==ledger.origin,'LEDGER_CHANGED')
                    ret=packet
                else:
                    dr=c.execute('SELECT * FROM r2_dispatch WHERE operation_id=?',(operation_id,)).fetchone()
                    ac=c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(operation_id,)).fetchone()
                    require(dr is not None and ac is not None,'NO_CLAIM')
                    require(ac['state']=='EFFECT_UNKNOWN' and ac['calls']==1 and
                            ac['attempt']==dr['attempt'],'NOT_DISPATCHABLE')
                    freeze=json.loads(ac['accepted_blob'])
                    action=freeze['action']
                    require(action['operation_id']==operation_id and
                            action['scope']==json.loads(dr['scope']) and
                            dr['hash']==action_hash(self.profile,action),'ACTION_BINDING')
                    require(dr['ledger_id']==ledger.ledger_id,'LEDGER_MISMATCH')
                    trust=c.execute('SELECT cert,origin FROM r2_tool_trust WHERE id=1').fetchone()
                    require(trust is not None and trust['origin']==ledger.origin,'TRUST_MISMATCH')
                    certified=json.loads(trust['cert']);claim=certified['claim']
                    require(rec_ref(claim['record'])==dr['trust_ref'],'TRUST_BINDING')
                    tv=claim['record']['value']
                    require(all(action[x]==tv[x] for x in ('tool','tool_version','destination')),
                            'TOOL_BINDING')
                    info={'profile':self.profile,'scope':action['scope'],'operation_id':operation_id,
                          'attempt':dr['attempt'],'ledger_id':dr['ledger_id'],
                          'ledger_origin':ledger.origin,'action':action,'action_hash':dr['hash'],
                          'commit_ref':rec_ref(freeze['commit_record']),
                          'tool_trust_ref':dr['trust_ref']}
                    sig=self.signer.sign(canonical([DOMAIN,info]))
                    ret={'claim':info,'kid':keyid(public_key(self.signer)),'signature':b64(sig)}
                    c.execute('INSERT INTO p16_outbox VALUES(?,?,?,?)',
                              (operation_id,dr['attempt'],canon(ret),digest([DOMAIN,info])))
                c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:c.execute('ROLLBACK')
                raise
        return ret


class AuthenticatedIndustrialGateway:
    """Independent tool-side transactional *simulation* with pinned W key.

    A valid W dispatch token is necessary, but cannot itself attest that a
    physical industrial operation occurred. This adapter's transaction proves
    only simulator exactly-once recording under crash/retry/concurrent delivery.
    """
    def __init__(self,ledger:ToolLedger,*,w_public:bytes,scope:dict):
        require(ledger.profile=='IND-DEMO-1','IND_ONLY')
        require(type(w_public) is bytes and len(w_public)==32 and good_point(w_public),
                'W_PUBLIC_KEY')
        self.ledger=ledger
        self.w_public=w_public
        self.scope=scope
        with self.ledger._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS p16_authenticated_delivery(
                operation_id TEXT PRIMARY KEY, packet_ref TEXT NOT NULL,
                attempt TEXT NOT NULL UNIQUE, effect_count INTEGER NOT NULL CHECK(effect_count=1)
            )""")

    def _check(self,packet):
        require(type(packet) is dict and set(packet)=={'claim','kid','signature'},'DISPATCH_FIELDS')
        v=packet['claim']
        require(type(v) is dict and set(v)==FIELDS,'DISPATCH_FIELDS')
        require(packet['kid']==keyid(self.w_public),'WRONG_W_SIGNER')
        strict_verify(self.w_public,raw(packet['signature'],64),canonical([DOMAIN,v]))
        require(v['profile']==self.ledger.profile and v['scope']==self.scope and
                v['action']['scope']==self.scope and
                v['operation_id']==v['action']['operation_id'],'DISPATCH_SCOPE')
        require(v['action_hash']==action_hash(self.ledger.profile,v['action']),'ACTION_BINDING')
        require(v['ledger_id']==self.ledger.ledger_id and
                v['ledger_origin']==self.ledger.origin,'LEDGER_BINDING')
        raw(v['attempt'],16)
        raw(v['commit_ref'],32)
        raw(v['tool_trust_ref'],32)
        return v

    def deliver(self,packet,*,at=110,inject=None):
        require(inject in (None,'before_commit','after_commit','hard_after_commit'),'INJECT_ARG')
        v=self._check(packet)
        packet_ref=digest([DOMAIN,v])
        # This is ONE transaction: logged W authority, synthetic effect,
        # immutable original fact, sequence and dedup are all committed together.
        with self.ledger._db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=c.execute('SELECT * FROM p16_authenticated_delivery WHERE operation_id=?',
                              (v['operation_id'],)).fetchone()
                if old:
                    require(old[0]==v['operation_id'] and old[1]==packet_ref and old[2]==v['attempt'],
                            'DISPATCH_CONFLICT')
                    require(c.execute('SELECT COUNT(*) FROM finalized WHERE operation_id=?',
                                      (v['operation_id'],)).fetchone()[0]==1,'LEDGER_INTEGRITY')
                    fact=json.loads(c.execute('SELECT fact FROM finalized WHERE operation_id=?',
                                              (v['operation_id'],)).fetchone()[0])
                    require(fact['dispatch_attempt']==v['attempt'] and
                            fact['action_hash']==v['action_hash'],'FACT_CONFLICT')
                    fresh=False
                else:
                    require(c.execute('SELECT 1 FROM finalized WHERE operation_id=?',
                                      (v['operation_id'],)).fetchone() is None,
                            'UNAUTHENTICATED_ORIGINAL')
                    sequence=c.execute('SELECT seq FROM meta WHERE id=1').fetchone()[0]+1
                    effect_id='ind-'+hashlib.sha256(canonical([DOMAIN,v])).hexdigest()[:32]
                    a=v['action']
                    fact={'ledger_id':v['ledger_id'],'operation_id':v['operation_id'],
                          'action_hash':v['action_hash'],'dispatch_attempt':v['attempt'],
                          'tool':a['tool'],'tool_version':a['tool_version'],
                          'destination':a['destination'],'outcome':'SUCCEEDED',
                          'effect_id':effect_id,'no_late_effect':False,
                          'final_seq':str(sequence),'finalized_at':str(at)}
                    c.execute('INSERT INTO finalized(operation_id,attempt,fact,final_seq,effect_id) VALUES(?,?,?,?,?)',
                              (v['operation_id'],v['attempt'],canon(fact),sequence,effect_id))
                    c.execute('INSERT INTO p16_authenticated_delivery VALUES(?,?,?,1)',
                              (v['operation_id'],packet_ref,v['attempt']))
                    c.execute('UPDATE meta SET seq=? WHERE id=1',(sequence,))
                    fresh=True
                if inject=='before_commit':raise ProtocolError('SIMULATED_PRECOMMIT_CRASH')
                c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:c.execute('ROLLBACK')
                raise
        if inject=='hard_after_commit':os._exit(97)
        if inject=='after_commit':raise ProtocolError('SIMULATED_RESPONSE_LOSS')
        return {'fact':fact,'new_effect':fresh,'packet_ref':packet_ref}

    def audit(self):
        with self.ledger._db() as c:
            rows=c.execute('SELECT operation_id,packet_ref,attempt,effect_count FROM p16_authenticated_delivery').fetchall()
            return {'authenticated_operations':len(rows),'simulated_effects':sum(x[3] for x in rows),
                    'frozen_ledger_facts':c.execute('SELECT COUNT(*) FROM finalized').fetchone()[0],
                    'ledger_sequence':c.execute('SELECT seq FROM meta WHERE id=1').fetchone()[0] }
