"""SQLite durable PAY-1 acceptance / dispatch laboratory (ZJJ v2.6-R2 subset).

Separates the Phase-4 *signed protocol validation fixture* from an actual durable,
serialized W accept / consume / reserve / receipt transaction. All privilege
registrations and preparation objects come from the Phase-4 trusted fixture.
No real tool is executed; no service or authenticated network boundary exists.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from research.reference_executor.wire import (
    ProtocolError, require, canonical, msgref, rec_ref, raw, strict_verify, digest,
)

class InjectedCrash(RuntimeError):
    """Fault injection at an explicit commit boundary."""


def _json(data: Any) -> str:
    return canonical(data).decode('utf-8')


def archive_verify_reply(acceptance: dict, reply: dict, signing_pub_b64: str) -> bool:
    """Check that the persisted Result describes this accepted proof and ref."""
    p=reply['body']['payload']
    require(reply['protected']['type']=='Result' and reply['protected']['profile']=='PAY-1','RESULT_TYPE')
    require(reply['protected']['kid']==digest(['ZJJ-KEY-v1','Ed25519',signing_pub_b64]), 'RESULT_KID')
    require(reply['body']['scope']==acceptance['body']['scope'],'RESULT_SCOPE')
    require(p['result']=='ACCEPTED' and p['status']=='ACCEPTED','RESULT_STATUS')
    require(p['acceptance_ref']==msgref(acceptance) and
            p['request_ref']==acceptance['body']['payload']['proof_ref'] and
            p['status_seq']==acceptance['body']['payload']['accept_seq'], 'RESULT_BINDING')
    strict_verify(raw(signing_pub_b64,32),raw(reply['sig'],64),
                  canonical(['ZJJ-SIG-v1',reply['protected'],reply['body']]))
    return True


def archive_verify(commit_record: dict, acceptance: dict) -> bool:
    """Independently re-evaluate archived COMMIT/Acceptance binding + Ed25519.

    This checks the historical *crypto linkage*, not historical KEY/ROLE
    enrollment validity or the complete original W transactional witnesses.
    """
    require(commit_record.get('kind') == 'COMMIT' and commit_record.get('profile') == 'PAY-1', 'ARCHIVE_KIND')
    require(acceptance.get('protected', {}).get('type') == 'Acceptance', 'ARCHIVE_TYPE')
    h, b, v = acceptance['protected'], acceptance['body'], commit_record['value']
    require(h['profile'] == commit_record['profile'] == 'PAY-1', 'WRONG_SCOPE')
    require(b['scope'] == commit_record['scope'] == v['action']['scope'], 'WRONG_SCOPE')
    require(b['payload']['commit_record_ref'] == rec_ref(commit_record), 'COMMIT_REF')
    require(b['payload']['ctx'] == v['ctx'], 'BINDING')
    for field in ('permit_ref','proof_ref','authorization_ref','review_refs',
                  'accept_seq','accepted_at','dispatch_before'):
        require(b['payload'][field] == v[field], 'ARCHIVE_BINDING')
    require(v['frozen_tool_request'] == v['action'], 'TOOL_BINDING')
    require(len(v['reservation_plan'])==1 and
            v['reservation_ids']==[v['reservation_plan'][0]['reservation_id']], 'RESOURCE_WITNESS')
    rw=v['reservation_plan'][0]
    amt=int(rw['amount'])
    require(amt>0 and amt==int(v['action']['payload']['amount_minor']), 'RESOURCE_WITNESS')
    require(int(rw['reserved_after'])==int(rw['reserved_before'])+amt and
            rw['spent_before']==rw['spent_after'] and
            int(rw['revision_after'])==int(rw['revision_before'])+1 and
            int(rw['reserved_after'])+int(rw['spent_after'])<=int(rw['capacity_before']), 'RESOURCE_WITNESS')
    before=v['behavior_before'];after=v['behavior_after']
    require(before['key']==after['key'] and
            int(after['revision'])==int(before['revision'])+1 and
            int(after['row']['accepted_count'])==int(before['row']['accepted_count'])+1 and
            after['row']['inflight']==[v['action']['operation_id']], 'BEHAVIOR_WITNESS')
    for bw in (before,after):
        require(bw['ref']==digest(['ZJJ-STATE-v1','BEHAVIOR',bw['key'],
                                   bw['revision'],bw['row']]), 'BEHAVIOR_REF')
    require(b['iat'] == v['accepted_at'], 'ARCHIVE_TIME')
    require(h['kid'] == digest(['ZJJ-KEY-v1','Ed25519',v['signing_public_key']]), 'ARCHIVE_KID')
    # Strict point validation and signature equation supplied by Phase-2 wire.
    strict_verify(raw(v['signing_public_key'], 32), raw(acceptance['sig'], 64),
                  canonical(['ZJJ-SIG-v1',h,b]))
    return True


class DurablePayW:
    def __init__(self, db_path: str | Path, *, capacity: int = 30000, count_cap: int = 32):
        self.db_path = str(db_path)
        self._create(capacity, count_cap)

    def _connect(self):
        c = sqlite3.connect(self.db_path, timeout=20, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA busy_timeout=20000')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA synchronous=FULL')
        c.execute('PRAGMA journal_mode=WAL')
        return c

    @contextmanager
    def _read(self):
        c=self._connect()
        try:
            yield c
        finally:
            c.close()

    def _create(self, capacity, count_cap):
        with self._read() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK(id=1), capacity INTEGER NOT NULL,
                    reserved INTEGER NOT NULL DEFAULT 0, spent INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 1, accept_seq INTEGER NOT NULL DEFAULT 0,
                    accepted_count INTEGER NOT NULL DEFAULT 0, count_cap INTEGER NOT NULL,
                    CHECK(capacity>=0 AND reserved>=0 AND spent>=0),
                    CHECK(reserved + spent <= capacity), CHECK(accepted_count<=count_cap)
                );
                CREATE TABLE IF NOT EXISTS accepted (
                    operation_id TEXT PRIMARY KEY, intent_key TEXT NOT NULL UNIQUE,
                    proof_ref TEXT NOT NULL UNIQUE, proof_bytes TEXT NOT NULL,
                    nonce_key TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK(amount>0),
                    seq INTEGER NOT NULL UNIQUE, state TEXT NOT NULL CHECK(state IN
                        ('ACCEPTED','EFFECT_UNKNOWN','SUCCEEDED','FAILED_CONFIRMED','HALTED','CANCELLED')),
                    commit_bytes TEXT NOT NULL, acceptance_bytes TEXT NOT NULL,
                    reply_bytes TEXT NOT NULL, commit_ref TEXT NOT NULL,
                    acceptance_ref TEXT NOT NULL, reservation_id TEXT NOT NULL UNIQUE,
                    dispatch_attempt TEXT UNIQUE, exec_calls INTEGER NOT NULL DEFAULT 0,
                    settlement_count INTEGER NOT NULL DEFAULT 0 CHECK(settlement_count<=1),
                    CHECK(exec_calls<=1), CHECK(exec_calls>=0)
                );
                CREATE TABLE IF NOT EXISTS flight (
                    task_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS audit (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    operation_id TEXT NOT NULL, detail TEXT NOT NULL
                );
            ''')
            c.execute('INSERT OR IGNORE INTO account(id,capacity,count_cap) VALUES(1,?,?)',
                      (capacity,count_cap))
            row=c.execute('SELECT capacity,count_cap FROM account WHERE id=1').fetchone()
            require(row['capacity']==capacity and row['count_cap']==count_cap, 'ACCOUNT_CONFIG_MISMATCH')

    @contextmanager
    def _tx(self):
        c=self._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.execute('COMMIT')
        except BaseException:
            if c.in_transaction:c.execute('ROLLBACK')
            raise
        finally:c.close()

    def snapshot(self) -> dict:
        with self._read() as c:
            a=dict(c.execute('SELECT * FROM account WHERE id=1').fetchone())
            return {**a,'accepted_rows':c.execute('SELECT COUNT(*) FROM accepted').fetchone()[0],
                    'flight_rows':c.execute('SELECT COUNT(*) FROM flight').fetchone()[0],
                    'audit_rows':c.execute('SELECT COUNT(*) FROM audit').fetchone()[0]}

    def _load(self, row) -> dict:
        commit=json.loads(row['commit_bytes'])
        acceptance=json.loads(row['acceptance_bytes'])
        archive_verify(commit, acceptance)
        archive_verify_reply(acceptance,json.loads(row['reply_bytes']),commit['value']['signing_public_key'])
        require(rec_ref(commit)==row['commit_ref'] and msgref(acceptance)==row['acceptance_ref'],
                'ARCHIVE_INTEGRITY')
        return {'operation_id':row['operation_id'],'seq':row['seq'],'state':row['state'],
                'proof_ref':row['proof_ref'],'commit':commit,'acceptance':acceptance,
                'reply':json.loads(row['reply_bytes']),'idempotent':True}

    @staticmethod
    def _intent_key(flow, op):
        # Phase4 returns stable tuple: preserve exact domain / scenario separation.
        return _json(list(flow.intent_for(op.action)))

    @staticmethod
    def _nonce_key(op):
        # Tie nonce to original signed challenge and operation, do not trust an
        # unbound application-supplied nonce string.
        return _json([op.challenge['body']['payload']['nonce'],
                      op.challenge['body']['payload']['session_id'],
                      op.action['operation_id']])

    def accept(self, flow, op, proof=None, *, inject: str | None=None) -> dict:
        """Serial BEGIN IMMEDIATE: validate signed candidate, accept once, archive.

        inject = after_validation | after_writes | after_commit.  A new Flow
        fixture is needed to retry after an injected in-process crash.
        """
        require(inject in (None,'after_validation','after_writes','after_commit',
                           'hard_after_validation','hard_after_writes','hard_after_commit'), 'INJECT_ARG')
        require(op.challenge is not None and op.permit is not None, 'MISSING_CHALLENGE')
        proof=proof if proof is not None else flow.make_proof(op)
        proof_ref=msgref(proof)
        operation_id=op.action['operation_id']
        intent=self._intent_key(flow,op)
        nonce=self._nonce_key(op)
        # Even the idempotent-return path must authenticate and bind the actual
        # signed proof. A persisted receipt is not a public unauthenticated API.
        p=flow._verified(proof,'CommitProof','H')
        require(p['ctx']==op.ctx and p['permit_ref']==msgref(op.permit)
                and p['challenge_ref']==msgref(op.challenge)
                and p['session_id']==op.challenge['body']['payload']['session_id']
                and p['nonce']==op.challenge['body']['payload']['nonce']
                and p['attempt_id']==op.challenge_request['body']['payload']['attempt_id'],
                'BINDING')
        committed=False
        with self._tx() as c:
            row=c.execute('SELECT * FROM accepted WHERE operation_id=? OR intent_key=? OR nonce_key=?',
                          (operation_id,intent,nonce)).fetchone()
            if row:
                require(row['operation_id']==operation_id and row['intent_key']==intent,
                        'OPERATION_CONFLICT')
                require(row['nonce_key']==nonce and row['proof_ref']==proof_ref and
                        row['proof_bytes']==_json(proof), 'REPLAY')
                return self._load(row)
            a=c.execute('SELECT * FROM account WHERE id=1').fetchone()
            amount=int(op.action['payload']['amount_minor'])
            require(a['accepted_count'] < a['count_cap'],'BEHAVIOR_LIMIT')
            require(a['reserved']+a['spent']+amount <= a['capacity'],'RESOURCE_LIMIT')
            require(c.execute('SELECT 1 FROM flight WHERE task_id=?',(op.task_id,)).fetchone() is None,
                    'TASK_BUSY')
            # This candidate construction is an explicitly scoped Phase-4 trusted
            # fixture. All signing, claims and Phase3 checks occur before durable W
            # acceptance; its in-memory mutation is NOT the durable accept point.
            flow.sequence=a['accept_seq']
            flow.cap=a['capacity']
            flow.reserved=a['reserved'];flow.spent=a['spent']
            flow.resource_revision=a['revision']
            acceptance=flow.commit(op,proof)
            rec=flow.commit_record
            archive_verify(rec, acceptance)
            require(rec['value']['accept_seq']==str(a['accept_seq']+1), 'SEQ')
            require(rec['value']['reservation_plan'][0]['reserved_before']==str(a['reserved']), 'RESOURCE_WITNESS')
            require(rec['value']['reservation_plan'][0]['amount']==str(amount),'RESOURCE_WITNESS')
            require(rec['value']['reservation_plan'][0]['revision_before']==str(a['revision']), 'RESOURCE_WITNESS')
            if inject=='hard_after_validation': os._exit(79)
            if inject=='after_validation':raise InjectedCrash('after_validation')
            c.execute('UPDATE account SET reserved=reserved+?, accepted_count=accepted_count+1, revision=revision+1, accept_seq=accept_seq+1 WHERE id=1', (amount,))
            c.execute('INSERT INTO flight(task_id,operation_id) VALUES(?,?)',(op.task_id,operation_id))
            c.execute('''INSERT INTO accepted(operation_id,intent_key,proof_ref,proof_bytes,
                nonce_key,task_id,amount,seq,state,commit_bytes,acceptance_bytes,reply_bytes,
                commit_ref,acceptance_ref,reservation_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                operation_id,intent,proof_ref,_json(proof),nonce,op.task_id,amount,
                a['accept_seq']+1,'ACCEPTED',_json(rec),_json(acceptance),
                _json(flow.commit_result),rec_ref(rec),msgref(acceptance),
                rec['value']['reservation_ids'][0]))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('ACCEPTED',operation_id,_json({'proof_ref':proof_ref,'seq':str(a['accept_seq']+1)})))
            if inject=='hard_after_writes': os._exit(79)
            if inject=='after_writes':raise InjectedCrash('after_writes')
            committed=True
        # _tx committed before caller sees a response: losing the response after
        # commit must not trigger a second acceptance or resource reservation.
        if committed and inject=='hard_after_commit':os._exit(79)
        if committed and inject=='after_commit':raise InjectedCrash('after_commit')
        with self._read() as c:
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(operation_id,)).fetchone()
            res=self._load(row)
            res['idempotent']=False
            return res

    def accepted_operation(self, op_id: str) -> dict | None:
        with self._read() as c:
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(op_id,)).fetchone()
            return self._load(row) if row is not None else None

    def claim(self, op_id: str, attempt_id: str, *, witness_ok: bool=False, inject=None):
        """Persist a claim with caller-supplied validated claim witness.

        The trusted claim guard is *not* implemented here: witness_ok is a
        fixture boundary, and should never be exposed as an API parameter.
        """
        require(witness_ok,'CLAIM_WITNESS_NOT_VERIFIED')
        require(inject in (None,'after_writes','after_commit'),'INJECT_ARG')
        with self._tx() as c:
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(op_id,)).fetchone()
            require(row is not None,'MISSING_ACCEPTANCE')
            if row['state'] != 'ACCEPTED':
                require(row['dispatch_attempt']==attempt_id, 'NO_REDISPATCH')
                return 'EXISTING'
            c.execute("UPDATE accepted SET state='EFFECT_UNKNOWN', dispatch_attempt=?, exec_calls=1 WHERE operation_id=? AND state='ACCEPTED'",(attempt_id,op_id))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('CLAIM',op_id,_json({'attempt':attempt_id})))
            if inject=='after_writes':raise InjectedCrash('after_writes')
        if inject=='after_commit':raise InjectedCrash('after_commit')
        return 'CLAIMED'

    def integrity_check(self):
        with self._read() as c:
            return {'integrity':c.execute('PRAGMA integrity_check').fetchone()[0],
                    'foreign_key_errors':len(c.execute('PRAGMA foreign_key_check').fetchall())}

    def audit(self):
        with self._read() as c:
            return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY ordinal')]
