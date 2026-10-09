"""CORE-19 key enrollment possession-proof testbed.

Implements the normative ZJJ-ENROLL-v1 signature domain and KEY_GRANT binding
under a trusted in-process controller C. Not a remote enrollment/authentication
service, so results are CASE SUBSET evidence only.
"""
from __future__ import annotations
import json, os, sqlite3
from contextlib import contextmanager
from pathlib import Path
from research.reference_executor.wire import Identity, ProtocolError, b64, raw, canonical, keyid, digest, strict_verify, require, good_point, is_id, number, rec_ref

MAX_KEY_LIFE=31536000

class EnrollmentLab:
    def __init__(self,path,profile='PAY-1'):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.profile=profile
        self.scope={'domain':'lab','tenant':'tenant-1','scenario':{'PAY-1':'payment','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}[profile]}
        self.c=Identity('fixture-controller',211)
        with self.db() as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS pending(
                enrollment_id TEXT PRIMARY KEY, tuple_json TEXT NOT NULL,nonce TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,expires INTEGER NOT NULL,consumed INTEGER NOT NULL DEFAULT 0,
                proof_json TEXT,grant_json TEXT);
            CREATE TABLE IF NOT EXISTS key_grants(kid TEXT PRIMARY KEY, grant_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS root_epoch(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL);
            INSERT OR IGNORE INTO root_epoch VALUES(1,1);''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,isolation_level=None,timeout=15.0)
        c.row_factory=sqlite3.Row
        try:yield c
        finally:c.close()
    @property
    def root_generation(self):
        with self.db() as c:return c.execute('SELECT generation FROM root_epoch WHERE id=1').fetchone()[0]
    def begin(self,subject,public_key,purposes,not_before=100,not_after=1000,now=100):
        """Privileged C operation: creates a pending approval, no business role."""
        require(is_id(subject),'SUBJECT');pk=raw(public_key,32)
        require(good_point(pk),'PUBLIC_KEY_POINT')
        require(isinstance(purposes,list) and bool(purposes) and len(set(purposes))==len(purposes) and
                all(p in {'Review','Authorization','IssueRequest','Permit','ChallengeRequest','Challenge','CommitProof','Acceptance','Result','StatusQuery','SOURCE','CONTROL','READ'} for p in purposes),'PURPOSE')
        require(number(str(not_before)) and number(str(not_after)) and int(not_before)>=now and int(not_before)<int(not_after) and int(not_after)-int(not_before)<=MAX_KEY_LIFE,'KEY_LIFETIME')
        tup={'scope':self.scope,'subject':subject,'public_key':public_key,'kid':keyid(pk),
             'purposes':sorted(purposes),'key_not_before':str(not_before),'key_not_after':str(not_after),
             'root_generation':str(self.root_generation)}
        enrollment_id=b64(os.urandom(16));nonce=b64(os.urandom(32))
        with self.db() as c:
            c.execute('INSERT INTO pending(enrollment_id,tuple_json,nonce,created_at,expires) VALUES(?,?,?,?,?)',
                      (enrollment_id,json.dumps(tup,sort_keys=True),nonce,now,now+60))
        return {'tuple':tup,'enrollment_id':enrollment_id,'nonce':nonce,'pending_expires':str(now+60)}
    @staticmethod
    def possession(applicant: Identity, pending: dict,iat=101,exp=140):
        tup=pending['tuple'];msg=canonical(['ZJJ-ENROLL-v1','2.6',tup,pending['enrollment_id'],pending['nonce'],str(iat),str(exp)])
        return {'tuple':tup,'enrollment_id':pending['enrollment_id'],'nonce':pending['nonce'],
                'iat':str(iat),'exp':str(exp),'signature':b64(applicant.key.sign(msg))}
    def register(self,proof,now=102):
        require(type(proof) is dict and set(proof)=={'tuple','enrollment_id','nonce','iat','exp','signature'},'ENROLL_FIELDS')
        raw(proof['enrollment_id'],16);raw(proof['nonce'],32);raw(proof['signature'],64)
        require(number(proof['iat']) and number(proof['exp']), 'PROOF_TIME')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                row=c.execute('SELECT * FROM pending WHERE enrollment_id=?',(proof['enrollment_id'],)).fetchone()
                require(row is not None,'NO_PENDING')
                require(row['nonce']==proof['nonce'],'NONCE_BINDING')
                tup=json.loads(row['tuple_json'])
                require(tup==proof['tuple'],'TUPLE_BINDING')
                pk=raw(tup['public_key'],32)
                require(good_point(pk) and keyid(pk)==tup['kid'],'KEY_BINDING')
                msg=canonical(['ZJJ-ENROLL-v1','2.6',tup,proof['enrollment_id'],proof['nonce'],proof['iat'],proof['exp']])
                strict_verify(pk,raw(proof['signature'],64),msg)
                # An identical already-committed proof is merely historical recovery:
                # never consume a second nonce or publish a second grant.
                if row['consumed']:
                    require(json.loads(row['proof_json'])==proof,'REPLAY')
                    saved=json.loads(row['grant_json']);c.execute('COMMIT');return saved
                require(int(tup['root_generation'])==self.root_generation,'ROOT_GENERATION')
                require(row['created_at']<=int(proof['iat'])<int(proof['exp']) and
                        0<int(proof['exp'])-int(proof['iat'])<=60 and
                        int(proof['exp'])<=row['expires'] and int(proof['iat'])<=now<int(proof['exp']), 'PROOF_TIME')
                require(int(tup['key_not_before'])<=now<int(tup['key_not_after']), 'KEY_LIFETIME')
                require(c.execute('SELECT 1 FROM key_grants WHERE kid=?',(tup['kid'],)).fetchone() is None,'KEY_EXISTS')
                enr=digest(['ZJJ-ENROLL-RECORD-v1','2.6',tup,proof['enrollment_id'],proof['nonce'],proof['iat'],proof['exp'],proof['signature']])
                grant={'version':'2.6','profile':self.profile,'kind':'KEY_GRANT','scope':self.scope,
                       'value':{'subject':tup['subject'],'public_key':tup['public_key'],'kid':tup['kid'],'epoch':'1',
                                'purposes':tup['purposes'],'root_generation':tup['root_generation'],
                                'enrollment_ref':enr,'iat':tup['key_not_before'],'exp':tup['key_not_after']}}
                rec_ref(grant)
                c.execute('INSERT INTO key_grants VALUES(?,?)',(tup['kid'],json.dumps(grant,sort_keys=True)))
                c.execute('UPDATE pending SET consumed=1,proof_json=?,grant_json=? WHERE enrollment_id=?',
                          (json.dumps(proof,sort_keys=True),json.dumps(grant,sort_keys=True),proof['enrollment_id']))
                c.execute('INSERT INTO audit(kind,data) VALUES(?,?)',('ENROLL',json.dumps({'kid':tup['kid'],'nonce':proof['nonce'],'ref':enr})))
                c.execute('COMMIT');return grant
            except BaseException:
                c.execute('ROLLBACK');raise
    def rotate_root(self):
        # Privileged C operation in this laboratory. Existing *pending* proof
        # may not migrate across generations merely by changing a label.
        with self.db() as c:c.execute('UPDATE root_epoch SET generation=generation+1 WHERE id=1')
    def snapshot(self):
        with self.db() as c:return {'grants':c.execute('SELECT COUNT(*) FROM key_grants').fetchone()[0],
                                   'consumed':c.execute('SELECT COUNT(*) FROM pending WHERE consumed=1').fetchone()[0],
                                   'audit':c.execute('SELECT COUNT(*) FROM audit').fetchone()[0]}
