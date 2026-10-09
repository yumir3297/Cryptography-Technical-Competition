"""Phase12 stricter W adapters: C-clocked CANCEL/CLAIM race and PAY ledger-origin gate.

A shared interface across local Profile adapters, not a single deployed W.
The ToolLedger remains a simulator and is not evidence of physical tool effects.
"""
from __future__ import annotations
import json
import os
import sqlite3

from research.reference_executor.wire import require, ProtocolError, rec_ref
from research.phase5.durable_w import _json
from research.phase6.trusted_final import ToolLedger, final_fact
from research.phase11.pay_r2 import StrictPayW
from research.phase11.scene_r2 import SceneR2W
from research.phase11.trusted_clock import checked_clock, consume_clock


class HardenedPayW(StrictPayW):
    """Fail closed on missing/mismatched independent immutable tool fact.

    The existing StrictPayW remains a historical Phase11 research baseline;
    this adapter overrides both admission and verification paths for Phase12.
    """
    def __init__(self, path, root_pub, *, ledger: ToolLedger, **kwargs):
        require(isinstance(ledger, ToolLedger) and ledger.profile == 'PAY-1', 'LEDGER_REQUIRED')
        self.r2_ledger = ledger
        super().__init__(path, root_pub, **kwargs)

    def settle_r2(self, record, *, clock=None, ledger=None):
        # No API that silently downgrades to the old ledger-free PAY settlement.
        require(ledger is None or ledger is self.r2_ledger, 'LEDGER_MISMATCH')
        return super().settle_r2(record, clock=clock)

    def _verify_final(self, c, record, now):
        row, fact_id = super()._verify_final(c, record, now)
        operation_id = record['value']['operation_id']
        # A historically settled original is handled by the inherited idempotent
        # path. Unsettled operations must re-prove the independent original fact.
        if c.execute('SELECT 1 FROM settled WHERE operation_id=?', (operation_id,)).fetchone() is None:
            trust = c.execute('SELECT ledger_origin,certificate FROM tool_trust WHERE id=1').fetchone()
            dispatch = c.execute('SELECT ledger_id,attempt FROM dispatch_witness WHERE operation_id=?',
                                 (operation_id,)).fetchone()
            require(trust is not None and dispatch is not None, 'LEDGER_UNAVAILABLE')
            require(dispatch['ledger_id'] == self.r2_ledger.ledger_id, 'LEDGER_MISMATCH')
            require(record['value']['ledger_id'] == self.r2_ledger.ledger_id, 'LEDGER_MISMATCH')
            require(dispatch['attempt'] == record['value']['dispatch_attempt'], 'FINAL_BINDING')
            # SQLite auto-creates a missing file. Never allow that to impersonate
            # the persisted tool authority: explicitly fail if backing file vanished.
            require(os.path.isfile(self.r2_ledger.path), 'LEDGER_UNAVAILABLE')
            try:
                origin = self.r2_ledger.origin
                original = self.r2_ledger.lookup(operation_id, dispatch['attempt'])
            except (sqlite3.Error, OSError) as exc:
                raise ProtocolError('LEDGER_UNAVAILABLE') from exc
            require(trust['ledger_origin'] == origin, 'CONTINUITY_UNKNOWN')
            require(original is not None, 'LEDGER_FACT_NOT_FOUND')
            require(original == final_fact(record), 'LEDGER_FACT_CONFLICT')
        return row, fact_id

    def cancel_r2(self, operation_id, *, clock):
        """Atomic C-authorized cancellation, never unwind EFFECT_UNKNOWN."""
        with self._tx() as c:
            row = c.execute('SELECT * FROM accepted WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None, 'MISSING_ACCEPTANCE')
            scope = json.loads(row['commit_bytes'])['scope']
            lo,hi,seq = checked_clock(c,clock,self.root_pub,'PAY-1',scope,operation_id,'CANCEL')
            if row['state']=='ACCEPTED' and row['exec_calls']==0:
                result = self._cancel(c,row,'C_AUTHORIZED_CANCEL')
            else:
                result = {'status':'TOO_LATE' if row['exec_calls'] else row['state'],
                          'calls':row['exec_calls']}
            consume_clock(c,seq)
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('C_CANCEL_REQUEST',operation_id,_json({'clock':clock,'result':{**result,'calls':str(result['calls'])}})))
            return result


class HardenedSceneW(SceneR2W):
    """C-clocked atomic explicit cancellation and existing strict scene claim."""
    def cancel_r2(self, operation_id, *, clock):
        with self.tx() as c:
            row = c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None, 'NOT_ACCEPTED')
            lo,hi,seq = checked_clock(c,clock,self.root_public,self.profile,self.scope,
                                      operation_id,'CANCEL')
            if row['state']=='ACCEPTED' and row['calls']==0:
                freeze=json.loads(row['accepted_blob'])
                result=self._cancel(c,row,freeze,'C_AUTHORIZED_CANCEL')
            else:
                result={'status':'TOO_LATE' if row['calls'] else row['state'], 'calls':row['calls']}
            consume_clock(c,seq)
            c.execute('INSERT INTO r2_audit(kind,operation_id,payload) VALUES(?,?,?)',
                      ('C_CANCEL_REQUEST',operation_id,_json({'clock':clock,'result':{**result,'calls':str(result['calls'])}})))
            return result
