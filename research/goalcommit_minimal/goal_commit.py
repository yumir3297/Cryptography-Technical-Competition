"""GoalCommit: minimal C-certified necessary-condition guard (research-only).

NOT ZJJ-CORE's real CommonW, signer broker, time checks or tool interface.
This module isolates the proposed C payload / guard and uses an SQLite test
harness to demonstrate atomicity and cryptographic binding. Fixture-only.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

GOAL_DOM = 'ZJJ-C-GOAL-FLOOR-v1'
COMMIT_DOM = 'ZJJ-W-GOAL-COMMIT-v1'
RECEIPT_DOM = 'ZJJ-X-GOAL-ACCEPT-v1'
FINAL_DOM = 'ZJJ-E-GOAL-FINAL-v1'


def canonical(x):
    """Match the real project's canonical JSON domain: str, bool, list, dict."""
    if type(x) is dict:
        if not all(type(k) is str and k.isascii() for k in x):
            raise Reject('BAD_KEY')
        for v in x.values(): canonical(v)
    elif type(x) is list:
        for v in x: canonical(v)
    elif type(x) not in (str, bool):
        raise Reject('BAD_WIRE_TYPE')
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def digest(domain, body):
    return base64.urlsafe_b64encode(hashlib.sha256(canonical([domain,body])).digest()).decode().rstrip('=')


def sign(sk, domain, body):
    return base64.urlsafe_b64encode(sk.sign(canonical([domain,body]))).decode().rstrip('=')


def check_sig(pk, domain, body, signature):
    try:
        pk.verify(base64.urlsafe_b64decode(signature+'='*(-len(signature)%4)),canonical([domain,body]))
    except (InvalidSignature,ValueError,TypeError) as exc:
        raise Reject('BAD_SIGNATURE') from exc


class Reject(ValueError):
    pass


def require(test, code):
    if not test:raise Reject(code)


def validate_goal(c):
    require(set(c)=={'group','epoch','capacity','resource','deps','actions','model'},'GOAL_FIELDS')
    require(c['model']=='goal-floor-v1' and type(c['group']) is str and bool(c['group']), 'GOAL_MODEL')
    require(type(c['epoch']) is str and c['epoch'].isdigit() and int(c['epoch'])>0,'GOAL_EPOCH')
    require(type(c['capacity']) is str and c['capacity'].isdigit(),'GOAL_CAPACITY')
    require(type(c['resource']) is str and bool(c['resource']),'GOAL_RESOURCE')
    require(type(c['deps']) is dict and bool(c['deps']) and all(type(v) is str for v in c['deps'].values()),'GOAL_DEPS')
    require(type(c['actions']) is list and 1<=len(c['actions'])<=64,'GOAL_ACTIONS')
    names=[]; obligations=[]
    for a in c['actions']:
        require(set(a)=={'name','profile','obligation','cost'} and all(type(a[k]) is str for k in a),'GOAL_ACTION_FIELDS')
        require(a['name'] and a['profile'] and a['cost'].isdigit() and int(a['cost'])>0,'GOAL_ACTION')
        require(a['obligation']=='' or a['obligation'].startswith('required:'),'GOAL_OBLIGATION')
        names.append(a['name'])
        if a['obligation']: obligations.append(a['obligation'])
    require(len(set(names))==len(names) and len(set(obligations))==len(obligations) and obligations,'GOAL_UNIQUENESS')
    # Reject a goal that is already impossible at the time of publication,
    # within this intentionally restricted resource-floor model.
    require(sum(int(a['cost']) for a in c['actions'] if a['obligation'])<=int(c['capacity']),
            'GOAL_UNREACHABLE_AT_PUBLISH')
    return c


def evaluate_goal(goal, ledger, action_name, profile):
    """Only a necessary resource floor, NOT a full plan/reachability solver."""
    rules={a['name']:a for a in goal['actions']}
    require(action_name in rules and rules[action_name]['profile']==profile,'GOAL_ACTION_SCOPE')
    rule=rules[action_name]
    needed={a['obligation']:int(a['cost']) for a in goal['actions'] if a['obligation']}
    require(set(ledger['status'])==set(needed),'GOAL_STATUS_SET')
    require(ledger['spent']>=0 and ledger['reserved']>=0 and ledger['spent']+ledger['reserved']<=int(goal['capacity']),'GOAL_LEDGER')
    require(all(x in ('OPEN','PENDING','DONE','BLOCKED') for x in ledger['status'].values()),'GOAL_STATUS')
    require(not any(v=='BLOCKED' for v in ledger['status'].values()),'GOAL_UNRECOVERABLE')
    # This deliberately does not infer that an UNKNOWN attempt will succeed.
    require(not any(v=='PENDING' for v in ledger['status'].values()),'GOAL_PENDING_UNKNOWN')
    if rule['obligation']:
        require(ledger['status'][rule['obligation']]=='OPEN','GOAL_ALREADY_COMMITTED')
    future=sum(cost for key,cost in needed.items()
               if ledger['status'][key]=='OPEN' and key!=rule['obligation'])
    # C signed floor is necessary only. W's actual plan cost must match C's
    # certified cost, not an untrusted amount claimed by the Agent.
    available=int(goal['capacity'])-ledger['spent']-ledger['reserved']
    allowed=int(rule['cost'])+future <=available
    require(allowed,'GOAL_CAPACITY_FLOOR')
    return {'action':action_name,'obligation':rule['obligation'], 'cost':rule['cost'],
            'remaining_floor':str(future),'available_before':str(available),
            'available_after':str(available-int(rule['cost']))}


class GoalCommitHarness:
    """An intentionally narrow replacement for neither C nor CommonW.

    It exercises their proposed contract using one SQLite write transaction.
    Production integration MUST use the existing signer broker and W tables.
    """
    def __init__(self,path,c_public,x_secret,e_public):
        self.path=str(Path(path));self.c_public=c_public;self.x_secret=x_secret;self.e_public=e_public
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS c_goal(grp TEXT PRIMARY KEY,epoch INTEGER,certificate TEXT);
            CREATE TABLE IF NOT EXISTS c_refs(grp TEXT PRIMARY KEY,refs TEXT);
            CREATE TABLE IF NOT EXISTS w_state(grp TEXT PRIMARY KEY,rev INTEGER,spent INTEGER,reserved INTEGER,status TEXT);
            CREATE TABLE IF NOT EXISTS w_operation(oid TEXT PRIMARY KEY,grp TEXT,action TEXT,obligation TEXT,cost INTEGER,commit_body TEXT,commit_ref TEXT,receipt TEXT);
            CREATE TABLE IF NOT EXISTS w_final(oid TEXT PRIMARY KEY,fact TEXT);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=10000')
        c.execute('PRAGMA synchronous=FULL')
        try:yield c
        finally:c.close()
    @contextmanager
    def tx(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                yield c
                c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:c.execute('ROLLBACK')
                raise
    def publish(self,certificate):
        claim=validate_goal(certificate['claim'])
        check_sig(self.c_public,GOAL_DOM,claim,certificate['signature'])
        key=claim['group']
        with self.tx() as c:
            old=c.execute('SELECT epoch FROM c_goal WHERE grp=?',(key,)).fetchone()
            require(int(claim['epoch'])==(old['epoch']+1 if old else 1),'GOAL_EPOCH_CAS')
            if old:
                row=c.execute('SELECT status FROM w_state WHERE grp=?',(key,)).fetchone()
                require(all(v!='PENDING' for v in json.loads(row['status']).values()),'GOAL_PENDING_UNKNOWN')
                # This minimal demo forbids changing the obligation set across
                # epochs; a real migration requires a separately reviewed rule.
                previous=json.loads(c.execute('SELECT certificate FROM c_goal WHERE grp=?',(key,)).fetchone()[0])['claim']
                old_ob={a['obligation'] for a in previous['actions'] if a['obligation']}
                new_ob={a['obligation'] for a in claim['actions'] if a['obligation']}
                require(old_ob==new_ob and previous['capacity']==claim['capacity'] and previous['resource']==claim['resource'],'GOAL_MIGRATION_REQUIRED')
                c.execute('UPDATE c_goal SET epoch=?,certificate=? WHERE grp=?',(int(claim['epoch']),json.dumps(certificate),key))
            else:
                status={a['obligation']:'OPEN' for a in claim['actions'] if a['obligation']}
                c.execute('INSERT INTO c_goal VALUES(?,?,?)',(key,1,json.dumps(certificate)))
                c.execute('INSERT INTO c_refs VALUES(?,?)',(key,json.dumps(claim['deps'])))
                c.execute('INSERT INTO w_state VALUES(?,0,0,0,?)',(key,json.dumps(status)))
        return digest(GOAL_DOM,claim)
    def trusted_update_deps(self,group,refs):
        """Fixture for a C-published Task/Policy update; never expose to Agent."""
        with self.tx() as c:
            require(c.execute('SELECT 1 FROM c_goal WHERE grp=?',(group,)).fetchone() is not None,'GROUP_UNKNOWN')
            c.execute('UPDATE c_refs SET refs=? WHERE grp=?',(json.dumps(refs),group))
            c.execute('UPDATE w_state SET rev=rev+1 WHERE grp=?',(group,))
    def snapshot(self,group):
        with self.db() as c:
            row=c.execute('SELECT * FROM w_state WHERE grp=?',(group,)).fetchone()
            require(row is not None,'GROUP_UNKNOWN')
            return {'revision':str(row['rev']),'spent':str(row['spent']),'reserved':str(row['reserved']),
                    'status':json.loads(row['status'])}
    def accept(self,group,oid,action,profile,expected_revision,*,crash_after_commit=False):
        """Input action is only a name. Actual costs/profiles come from C cert."""
        with self.tx() as c:
            r=c.execute('SELECT * FROM c_goal WHERE grp=?',(group,)).fetchone()
            require(r is not None,'GROUP_UNKNOWN')
            cert=json.loads(r['certificate']);goal=cert['claim']
            check_sig(self.c_public,GOAL_DOM,goal,cert['signature'])
            require(goal['deps']==json.loads(c.execute('SELECT refs FROM c_refs WHERE grp=?',(group,)).fetchone()[0]),'GOAL_STALE_DEPS')
            s=c.execute('SELECT * FROM w_state WHERE grp=?',(group,)).fetchone()
            require(str(s['rev'])==str(expected_revision),'W_STATE_STALE')
            require(c.execute('SELECT 1 FROM w_operation WHERE oid=?',(oid,)).fetchone() is None,'INTENT_REPLAY')
            state={'spent':s['spent'],'reserved':s['reserved'],'status':json.loads(s['status'])}
            decision=evaluate_goal(goal,state,action,profile)
            before={'revision':str(s['rev']),'spent':str(s['spent']),'reserved':str(s['reserved']),'status':state['status']}
            # Commit binds certified goal, dependencies, pre-accept W snapshot,
            # the exact action and the necessary-condition witness.
            body={'group':group,'oid':oid,'goal_ref':digest(GOAL_DOM,goal),
                  'deps_ref':digest('ZJJ-GOAL-DEPS-v1',goal['deps']),
                  'state_ref':digest('ZJJ-GOAL-STATE-v1',before),
                  'action_ref':digest('ZJJ-GOAL-ACTION-v1',[profile,action,oid]),
                  'check_ref':digest('ZJJ-GOAL-CHECK-v1',decision),
                  'epoch':goal['epoch'],'accept_seq':str(s['rev']+1)}
            ref=digest(COMMIT_DOM,body)
            status=dict(state['status']);ob=decision['obligation']
            if ob:status[ob]='PENDING'
            c.execute('INSERT INTO w_operation VALUES(?,?,?,?,?,?,?,NULL)',
                      (oid,group,action,ob,int(decision['cost']),json.dumps(body),ref))
            c.execute('UPDATE w_state SET rev=rev+1,reserved=reserved+?,status=? WHERE grp=?',
                      (int(decision['cost']),json.dumps(status),group))
        if crash_after_commit:raise RuntimeError('SIMULATED_CRASH_AFTER_COMMIT')
        return self.receipt(oid)
    def receipt(self,oid):
        with self.tx() as c:
            row=c.execute('SELECT * FROM w_operation WHERE oid=?',(oid,)).fetchone()
            require(row is not None,'UNKNOWN_OPERATION')
            body=json.loads(row['commit_body']);ref=digest(COMMIT_DOM,body)
            require(ref==row['commit_ref'],'COMMIT_TAMPER')
            if row['receipt']:
                receipt=json.loads(row['receipt'])
                check_sig(self.x_secret.public_key(),RECEIPT_DOM,receipt['claim'],receipt['signature'])
                require(receipt['claim']=={'oid':oid,'commit_ref':ref},'RECEIPT_MISMATCH')
                return receipt
            claim={'oid':oid,'commit_ref':ref}
            receipt={'claim':claim,'signature':sign(self.x_secret,RECEIPT_DOM,claim)}
            c.execute('UPDATE w_operation SET receipt=? WHERE oid=?',(json.dumps(receipt),oid))
            return receipt
    def settle(self,oid,fact):
        check_sig(self.e_public,FINAL_DOM,fact['claim'],fact['signature'])
        f=fact['claim'];require(set(f)=={'oid','commit_ref','outcome','effect_id'},'FINAL_FIELDS')
        require(f['oid']==oid and f['outcome'] in ('SUCCEEDED','FAILED_CONFIRMED'), 'FINAL_CLAIM')
        with self.tx() as c:
            row=c.execute('SELECT * FROM w_operation WHERE oid=?',(oid,)).fetchone()
            require(row is not None and f['commit_ref']==row['commit_ref'],'FINAL_BINDING')
            # The real W only dispatches after X's certified Acceptance; the
            # harness preserves that dependency rather than skipping it.
            require(row['receipt'] is not None,'RECEIPT_NOT_SIGNED')
            receipt=json.loads(row['receipt'])
            check_sig(self.x_secret.public_key(),RECEIPT_DOM,receipt['claim'],receipt['signature'])
            require(receipt['claim']=={'oid':oid,'commit_ref':row['commit_ref']},'RECEIPT_MISMATCH')
            old=c.execute('SELECT fact FROM w_final WHERE oid=?',(oid,)).fetchone()
            if old:
                require(json.loads(old['fact'])==fact,'FINAL_CONFLICT')
                return 'ALREADY_SETTLED'
            s=c.execute('SELECT * FROM w_state WHERE grp=?',(row['grp'],)).fetchone()
            statuses=json.loads(s['status'])
            require(not row['obligation'] or statuses[row['obligation']]=='PENDING','FINAL_STATE')
            # Failure cannot reset the original intent. Here it blocks the goal
            # until a trusted change of goal/compensation policy.
            if row['obligation']:
                statuses[row['obligation']]='DONE' if f['outcome']=='SUCCEEDED' else 'BLOCKED'
            spent_inc=row['cost'] if f['outcome']=='SUCCEEDED' else 0
            c.execute('UPDATE w_state SET rev=rev+1,reserved=reserved-?,spent=spent+?,status=? WHERE grp=?',
                      (row['cost'],spent_inc,json.dumps(statuses),row['grp']))
            c.execute('INSERT INTO w_final VALUES(?,?)',(oid,json.dumps(fact)))
            return 'SETTLED'


def fixture_key(marker):
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(('FIXTURE-ONLY:'+marker).encode()).digest())


def issue_goal(key,claim):
    validate_goal(claim)
    return {'claim':claim,'signature':sign(key,GOAL_DOM,claim)}


def issue_final(key,oid,commit_ref,outcome,effect_id):
    body={'oid':oid,'commit_ref':commit_ref,'outcome':outcome,'effect_id':effect_id}
    return {'claim':body,'signature':sign(key,FINAL_DOM,body)}


def get_commit_ref(host,oid):
    with host.db() as c:
        row=c.execute('SELECT commit_ref FROM w_operation WHERE oid=?',(oid,)).fetchone()
        return row['commit_ref'] if row else None
