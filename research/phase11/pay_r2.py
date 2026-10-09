"""Phase11 PAY guarded claim with signed C time windows, deterministic cancel.

Legacy FinalW/GuardedFinalW deliberately left as baseline, this strict adapter
uses the same sqlite transaction for current dependencies and claim/cancel.
"""
import json
from research.phase7.guarded_dispatch import GuardedFinalW
from research.reference_executor.wire import require,ProtocolError,canonical,b64,raw,strict_verify,number,rec_ref,action_hash
from research.phase5.durable_w import _json
from .scene_r2 import interval
from .trusted_clock import prepare_table,checked_clock,consume_clock

DOMAIN='ZJJ-RESEARCH-C-VALIDITY-v1'


def sign_window(controller,claim):
    return {'claim':claim,'signature':b64(controller.key.sign(canonical([DOMAIN,claim])))}


class StrictPayW(GuardedFinalW):
    def claim(self,*args,**kwargs):
        raise ProtocolError('STRICT_CLOCKED_CLAIM_ONLY')

    def claim_bound(self,*args,**kwargs):
        raise ProtocolError('STRICT_CLOCKED_CLAIM_ONLY')

    def __init__(self,path,root_pub,**kw):
        super().__init__(path,root_pub,**kw)
        with self._read() as c:
            prepare_table(c)
            c.executescript('''CREATE TABLE IF NOT EXISTS authority_window(
                namespace TEXT NOT NULL,dep_key TEXT NOT NULL,revision INTEGER NOT NULL,
                ref TEXT NOT NULL,seq INTEGER NOT NULL,iat INTEGER NOT NULL,exp INTEGER NOT NULL,
                certificate TEXT NOT NULL, PRIMARY KEY(namespace,dep_key));''')

    def publish_window(self,certificate):
        require(type(certificate) is dict and set(certificate)=={'claim','signature'},'CONTROL_FIELDS')
        cl=certificate['claim']
        require(type(cl) is dict and set(cl)=={'scope','dep','seq','iat','exp'},'CONTROL_FIELDS')
        d=cl['dep'];require(type(d) is dict and set(d)=={'namespace','key','revision','ref'},'CONTROL_FIELDS')
        require(all(number(cl[x],True) for x in ('seq','exp')) and number(cl['iat']) and
                number(d['revision'],True) and int(cl['iat'])<int(cl['exp']),'CONTROL_TIME')
        strict_verify(self.root_pub,raw(certificate['signature'],64),canonical([DOMAIN,cl]))
        k=_json(d['key']);ns=d['namespace']
        with self._tx() as c:
            row=c.execute('SELECT * FROM authority WHERE namespace=? AND dep_key=?',(ns,k)).fetchone()
            require(row is not None and row['active']==1 and row['revision']==int(d['revision'])
                    and row['ref']==d['ref'],'STALE')
            prev=c.execute('SELECT seq FROM authority_window WHERE namespace=? AND dep_key=?',(ns,k)).fetchone()
            require(prev is None or int(cl['seq'])>prev['seq'],'NONMONOTONIC')
            c.execute('''INSERT INTO authority_window VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(namespace,dep_key) DO UPDATE SET revision=excluded.revision,ref=excluded.ref,
                seq=excluded.seq,iat=excluded.iat,exp=excluded.exp,certificate=excluded.certificate''',
                (ns,k,int(d['revision']),d['ref'],int(cl['seq']),int(cl['iat']),int(cl['exp']),_json(certificate)))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('C_VALIDITY','-',_json({'dep':d,'seq':cl['seq']})))

    def _cancel(self,c,row,reason):
        require(row['state']=='ACCEPTED' and row['exec_calls']==0,'CANCEL_TOO_LATE')
        oid=row['operation_id'];amt=row['amount']
        c.execute('UPDATE account SET reserved=reserved-?,revision=revision+1 WHERE id=1 AND reserved>=?',(amt,amt))
        require(c.execute('SELECT changes()').fetchone()[0]==1,'ACCOUNT_INTEGRITY')
        require(c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(row['task_id'],oid)).rowcount==1,'ACCOUNT_INTEGRITY')
        require(c.execute("UPDATE accepted SET state='CANCELLED' WHERE operation_id=? AND state='ACCEPTED'",(oid,)).rowcount==1,'CANCEL_TOO_LATE')
        c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',('SAFE_CANCEL',oid,_json({'reason':reason})))
        return {'status':'CANCELLED','reason':reason,'calls':0}

    def settle(self,*args,**kwargs):
        raise ProtocolError('STRICT_CLOCKED_SETTLEMENT_ONLY')

    def settle_r2(self,record,*,clock=None):
        """PAY single-transaction signed-clock FinalFact settlement.

        R2 facts are certified by C ToolTrust and ledger-continuity activation;
        the external tool's immutable physical effect is not proven by W alone.
        """
        from research.reference_executor.wire import rec_ref
        from research.phase6.trusted_final import final_fact,final_fact_id
        op=record.get('value',{}).get('operation_id') if isinstance(record,dict) else None
        with self._tx() as c:
            rr=rec_ref(record)
            prior_record=c.execute('SELECT record FROM final_seen WHERE record_ref=?',(rr,)).fetchone()
            if prior_record:
                require(json.loads(prior_record['record'])==record,'RECORD_COLLISION')
                saved=c.execute('SELECT fact_id FROM settled WHERE operation_id=?',(op,)).fetchone()
                require(saved is not None,'FINAL_STATE')
                return {'status':c.execute('SELECT state FROM accepted WHERE operation_id=?',(op,)).fetchone()[0],
                        'fact_id':saved['fact_id'],'idempotent':True,'historical':True}
            lo,hi,seq=checked_clock(c,clock,self.root_pub,'PAY-1',record['scope'],op,'SETTLE')
            row,fid=self._verify_final(c,record,lo)
            v=record['value'];t=self._current_trust(c,lo)['value']
            require(interval(lo,hi,int(v['iat']),int(v['exp']))=='VALID','UNKNOWN_TIME')
            require(interval(lo,hi,int(t['iat']),int(t['exp']))=='VALID','UNKNOWN_TIME')
            previous=c.execute('SELECT * FROM settled WHERE operation_id=?',(op,)).fetchone()
            if previous:
                if previous['fact_id']!=fid or json.loads(previous['fact'])!=final_fact(record):
                    c.execute("UPDATE accepted SET state='HALTED' WHERE operation_id=?",(op,))
                    c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                              ('CONTRADICTION',op,_json({'old':previous['fact_id'],'new':fid,'clock':clock})))
                    consume_clock(c,seq)
                    return {'status':'HALTED','fact_id':previous['fact_id'],'conflict':True}
                c.execute('INSERT INTO final_seen VALUES(?,?,?)',(rr,op,_json(record)))
                consume_clock(c,seq)
                return {'status':row['state'],'fact_id':fid,'idempotent':True,'historical':False}
            require(row['state']=='EFFECT_UNKNOWN' and row['settlement_count']==0 and row['exec_calls']==1,'FINAL_STATE')
            require(row['dispatch_attempt']==v['dispatch_attempt'],'FINAL_BINDING')
            amt=row['amount'];outcome=v['outcome']
            a=c.execute('SELECT * FROM account WHERE id=1').fetchone()
            flight=c.execute('SELECT operation_id FROM flight WHERE task_id=?',(row['task_id'],)).fetchone()
            require(a['reserved']>=amt and flight is not None and flight['operation_id']==op,'ACCOUNT_INTEGRITY')
            state='SUCCEEDED' if outcome=='SUCCEEDED' else 'FAILED_CONFIRMED'
            c.execute('UPDATE account SET reserved=reserved-?,spent=spent+?,revision=revision+1 WHERE id=1',
                      (amt,amt if state=='SUCCEEDED' else 0))
            c.execute('DELETE FROM flight WHERE task_id=? AND operation_id=?',(row['task_id'],op))
            c.execute('UPDATE accepted SET state=?,settlement_count=1 WHERE operation_id=?',(state,op))
            c.execute('INSERT INTO settled VALUES(?,?,?,?,?,?)',
                      (op,fid,_json(final_fact(record)),_json(record),rr,v['ledger_id']))
            c.execute('INSERT INTO final_seen VALUES(?,?,?)',(rr,op,_json(record)))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('SETTLED_PHASE11',op,_json({'fact_id':fid,'outcome':outcome,'clock':clock})))
            consume_clock(c,seq)
            return {'status':state,'fact_id':fid,'idempotent':False,'historical':False}

    def claim_r2(self,operation_id,attempt,*,clock):
        raw(attempt,16)
        with self._tx() as c:
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None,'MISSING_ACCEPTANCE')
            if row['exec_calls']:
                require(row['dispatch_attempt']==attempt,'NO_REDISPATCH')
                return {'status':'EXISTING','attempt':attempt}
            require(row['state']=='ACCEPTED','NO_DISPATCH')
            lo,hi,clock_seq=checked_clock(c,clock,self.root_pub,'PAY-1',json.loads(row['commit_bytes'])['scope'],operation_id,'DISPATCH')
            archive=self._load(row)['commit'];act=archive['value']['action']
            require(act==archive['value']['frozen_tool_request'],'FROZEN_ACTION_MISMATCH')
            try:
                trust=self._current_trust(c,lo)
            except ProtocolError as e:
                if e.code=='TRUST_EXPIRED':
                    result=self._cancel(c,row,'TRUST_EXPIRED');consume_clock(c,clock_seq);return result
                raise
            v=trust['value']
            require(trust['scope']==act['scope'] and all(v[k]==act[k] for k in ('tool','tool_version','destination')),'TOOL_BINDING')
            st=interval(lo,hi,int(v['iat']),int(v['exp']))
            if st=='EXPIRED':
                result=self._cancel(c,row,'TRUST_EXPIRED');consume_clock(c,clock_seq);return result
            require(st=='VALID',st)
            before=int(archive['value']['dispatch_before'])
            if lo>=before:
                result=self._cancel(c,row,'DISPATCH_EXPIRED');consume_clock(c,clock_seq);return result
            require(hi<before,'UNKNOWN_TIME')
            try:self._guard_in_tx(c,archive)
            except ProtocolError as e:
                if e.code in ('STALE','REVOKED'):
                    result=self._cancel(c,row,e.code);consume_clock(c,clock_seq);return result
                raise
            for d in archive['value']['checked_deps']:
                if d['namespace']=='BEHAVIOR':continue
                ns=d['namespace'];k=_json(d['key'])
                rw=c.execute('SELECT * FROM authority_window WHERE namespace=? AND dep_key=?',(ns,k)).fetchone()
                require(rw is not None,'AUTHORITY_TIME_UNAVAILABLE')
                require(rw['revision']==int(d['revision']) and rw['ref']==d['ref'],'AUTHORITY_TIME_UNAVAILABLE')
                certainty=interval(lo,hi,rw['iat'],rw['exp'])
                if certainty=='EXPIRED':
                    result=self._cancel(c,row,'DEP_EXPIRED');consume_clock(c,clock_seq);return result
                require(certainty=='VALID',certainty)
            c.execute('INSERT INTO dispatch_witness VALUES(?,?,?,?,?,?)',
                      (operation_id,attempt,rec_ref(trust),v['ledger_id'],_json(act['scope']),action_hash('PAY-1',act)))
            require(c.execute("UPDATE accepted SET state='EFFECT_UNKNOWN',exec_calls=1,dispatch_attempt=? WHERE operation_id=? AND state='ACCEPTED' AND exec_calls=0",
                      (attempt,operation_id)).rowcount==1,'NO_REDISPATCH')
            consume_clock(c,clock_seq)
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',('CLAIM_PHASE11',operation_id,_json({'attempt':attempt,'clock':clock})))
        return {'status':'CLAIMED','attempt':attempt}
