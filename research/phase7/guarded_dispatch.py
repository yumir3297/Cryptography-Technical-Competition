"""Phase 7 laboratory atomic C-authenticated current-state dispatch gate.

NOT a complete protocol control-plane: enrollments, sources and transaction isolation
across physically separate storage are outside this model. Uses the exact same
SQLite authority transaction for C updates and ClaimDispatch to avoid a local
TOCTOU gap. Separate strict class; old FinalW remains for historical regressions.
"""
from __future__ import annotations
import json
from research.phase6.trusted_final import FinalW,Controller
from research.reference_executor.wire import (require,ProtocolError,canonical,raw,b64,
    strict_verify,rec_ref,action_hash,number)
from research.phase5.durable_w import _json

DOMAIN='ZJJ-RESEARCH-CURRENT-C-v1'


def _make_cert(controller:Controller,claim):
    return {'claim':claim,'signature':b64(controller.key.sign(canonical([DOMAIN,claim])))}


class GuardedFinalW(FinalW):
    """Strict PAY-1 current-dependency gate enforced in same SQLite transaction."""
    def __init__(self,path,root_pub,**kw):
        super().__init__(path,root_pub,**kw)
        with self._read() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS authority (
              namespace TEXT NOT NULL, dep_key TEXT NOT NULL, revision INTEGER NOT NULL,
              ref TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN(0,1)),
              PRIMARY KEY(namespace,dep_key));
            CREATE TABLE IF NOT EXISTS authority_cert (
              id INTEGER PRIMARY KEY AUTOINCREMENT, certified TEXT NOT NULL);
            ''')

    def certified_publish(self,certificate):
        require(type(certificate) is dict and set(certificate)=={'claim','signature'},'CONTROL_FIELDS')
        claim=certificate['claim'];require(type(claim) is dict and set(claim)=={'operation_id','scope','changes'},'CONTROL_FIELDS')
        strict_verify(self.root_pub,raw(certificate['signature'],64),canonical([DOMAIN,claim]))
        changes=claim['changes'];require(type(changes) is list and len(changes)>0,'CONTROL_FIELDS')
        with self._tx() as c:
            if claim['operation_id']:
                row=c.execute('SELECT commit_bytes FROM accepted WHERE operation_id=?',(claim['operation_id'],)).fetchone()
                require(row is not None,'MISSING_ACCEPTANCE')
                require(json.loads(row['commit_bytes'])['scope']==claim['scope'],'WRONG_SCOPE')
            for d in changes:
                require(set(d)=={'namespace','key','revision','ref','active'},'CONTROL_FIELDS')
                require(type(d['active']) is bool and number(d['revision'],True),'CONTROL_FIELDS')
                require(type(d['namespace']) is str and type(d['key']) is list and
                    all(type(i) is str for i in d['key']) and type(d['ref']) is str,'CONTROL_FIELDS')
                k=_json(d['key']);old=c.execute('SELECT revision FROM authority WHERE namespace=? AND dep_key=?',
                    (d['namespace'],k)).fetchone()
                revision=int(d['revision'])
                require(old is None or revision>old['revision'],'NONMONOTONIC')
                c.execute('''INSERT INTO authority(namespace,dep_key,revision,ref,active)
                  VALUES(?,?,?,?,?) ON CONFLICT(namespace,dep_key) DO UPDATE SET
                  revision=excluded.revision,ref=excluded.ref,active=excluded.active''',
                    (d['namespace'],k,revision,d['ref'],int(d['active'])))
            c.execute('INSERT INTO authority_cert(certified) VALUES(?)',(_json(certificate),))
        return True

    @staticmethod
    def initial_claim(flow,op):
        # Trusted C can assert rows to initialize this isolated lab. Caller-supplied
        # permit deps are *not* accepted as sole source: reconstruct first.
        # Accept validated op against the trusted registry before COMMIT was frozen;
        # after the transaction, W's BEHAVIOR revision has legitimately changed.
        # The signed archived COMMIT and signed Permit must retain the same
        # pre-accept dependency snapshot; don't recompute against post-accept rows.
        require(flow.commit_record is not None,'MISSING_ACCEPTANCE')
        expected=flow.commit_record['value']['checked_deps']
        require(expected==op.permit['body']['deps'],'DEP_CONFLICT')
        return {'operation_id':op.action['operation_id'],'scope':flow.scope,'changes':[
            {**d,'active':True} for d in expected if d['namespace']!='BEHAVIOR']}

    def _guard_in_tx(self,c,commit):
        deps=commit['value']['checked_deps']
        require(deps and type(deps) is list,'DEPENDENCIES_MISSING')
        observed={(r['namespace'],r['dep_key']):r for r in c.execute('SELECT * FROM authority')}
        for dep in deps:
            ns=dep['namespace'];k=_json(dep['key'])
            if ns=='BEHAVIOR':
                # Behavioral own-change must not be compared to pre-accept dep.
                b=commit['value']['behavior_after']
                require(dep['key']==b['key'],'BEHAVIOR_WITNESS')
                account=c.execute('SELECT accepted_count FROM account WHERE id=1').fetchone()
                require(account['accepted_count']>=int(b['row']['accepted_count']),'BEHAVIOR_WITNESS')
                continue
            row=observed.get((ns,k));require(row is not None,'STATE_UNAVAILABLE')
            require(row['active']==1,'REVOKED')
            require(row['revision']==int(dep['revision']) and row['ref']==dep['ref'],'STALE')
        return True

    def claim_bound(self,operation_id,attempt,*,now=100):
        raw(attempt,16)
        with self._tx() as c:
            trust=self._current_trust(c,now);v=trust['value']
            row=c.execute('SELECT * FROM accepted WHERE operation_id=?',(operation_id,)).fetchone()
            require(row is not None,'MISSING_ACCEPTANCE')
            archive=self._load(row)['commit'];action=archive['value']['action']
            require(trust['scope']==action['scope'] and all(action[k]==v[k] for k in
                        ('tool','tool_version','destination')),'TOOL_BINDING')
            earlier=c.execute('SELECT * FROM dispatch_witness WHERE operation_id=?',(operation_id,)).fetchone()
            if earlier:
                require(earlier['attempt']==attempt,'NO_REDISPATCH')
                return 'EXISTING'
            require(row['state']=='ACCEPTED' and row['exec_calls']==0,'NO_REDISPATCH')
            require(now<int(archive['value']['dispatch_before']),'DISPATCH_EXPIRED')
            require(action==archive['value']['frozen_tool_request'],'FROZEN_ACTION_MISMATCH')
            # This guard and the C state publications serialize on the *same*
            # BEGIN IMMEDIATE SQLite transaction. Any earlier revocation wins.
            self._guard_in_tx(c,archive)
            c.execute('INSERT INTO dispatch_witness VALUES(?,?,?,?,?,?)',
                (operation_id,attempt,rec_ref(trust),v['ledger_id'],_json(action['scope']),action_hash('PAY-1',action)))
            c.execute("UPDATE accepted SET state='EFFECT_UNKNOWN',exec_calls=1,dispatch_attempt=? WHERE operation_id=? AND state='ACCEPTED'",
                (attempt,operation_id))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                ('CLAIM_PHASE7',operation_id,_json({'attempt':attempt,'ledger':v['ledger_id']})))
        return 'CLAIMED'
