"""Public-key-only, authenticated finite object graph and DENY coverage in one W."""
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from competition.support.wire import require, ProtocolError, b64, raw, canonical, strict_verify, keyid, rec_ref, digest, sortset, action_hash
from competition.support.broker_policy import PROFILE_SCOPES
from competition.support.scene_contract import ROLES as SCENE_ROLES
from competition.support.schema import CompetitionSchema, COMPETITION_PROTO
from competition.core.event_clock import checked_event_clock, require_window

ROOT = Path(__file__).resolve().parents[2]
ROLES = {**SCENE_ROLES, 'PAY-1': {'H': 'HOLDER', 'G': 'ISSUER', 'X': 'EXECUTOR', 'U': 'FINANCE', 'V': 'ANOMALY', 'E': 'SOURCE'}}
TYPES = {'H': ('IssueRequest', 'ChallengeRequest', 'CommitProof', 'StatusQuery'), 'G': ('Permit',), 'X': ('Challenge', 'Acceptance', 'Result'), 'U': ('Authorization',), 'V': ('Review',), 'E': ('SOURCE',)}

def enc(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def prefix(profile):
    return [PROFILE_SCOPES[profile][k] for k in ('domain', 'tenant', 'scenario')]

@dataclass(frozen=True)
class PublicActor:
    name: str
    kid: str
    pub: bytes
    roles: frozenset
    purposes: frozenset

    @classmethod
    def from_actor(cls, actor):
        require(keyid(actor.pub) == actor.kid, 'ROSTER_KEY')
        return cls(actor.name, actor.kid, bytes(actor.pub), frozenset(actor.roles), frozenset(actor.purposes))

class TrustedState:
    def __init__(self, path, root_public, actors, clock):
        self.protocol = COMPETITION_PROTO
        self.path = str(path); self.root_public = bytes(root_public); self.clock = clock
        require(raw(clock.info['public_key'], 32) == self.root_public, 'CLOCK_ROOT')
        require(bool(actors) and set(actors) <= set(PROFILE_SCOPES), 'PROFILE_REGISTRY')
        self.actors = {p: {a: PublicActor.from_actor(v) for a, v in roster.items()} for p, roster in actors.items()}
        require(all(set(r) == set(TYPES) for r in self.actors.values()), 'ROSTER_SET')
        self.schemas = {p: CompetitionSchema(ROOT, p) for p in PROFILE_SCOPES}
        with self.db() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS a_current(profile TEXT,namespace TEXT,key TEXT,revision INTEGER,ref TEXT,record TEXT,active INTEGER,certificate TEXT,PRIMARY KEY(profile,namespace,key));
              CREATE TABLE IF NOT EXISTS a_journal(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,profile TEXT,operation_id TEXT,blob TEXT);
              CREATE TABLE IF NOT EXISTS a_deny_range(profile TEXT,operation_id TEXT,basis_ref TEXT,revision INTEGER,context TEXT,purposes TEXT,root_certificate TEXT,PRIMARY KEY(profile,operation_id,basis_ref));
              CREATE TABLE IF NOT EXISTS a_publication(profile TEXT,operation_id TEXT,basis_ref TEXT,purpose TEXT,ref TEXT,message TEXT,verdict TEXT,seq INTEGER,PRIMARY KEY(profile,ref));
              CREATE TABLE IF NOT EXISTS a_sign_call(nonce TEXT PRIMARY KEY,profile TEXT,alias TEXT,request_ref TEXT,expires INTEGER,used INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS a_identity(nonce TEXT PRIMARY KEY,profile TEXT,operation_id TEXT,request_ref TEXT,stage TEXT,expires INTEGER,used INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS a_guard_fact(profile TEXT,operation_id TEXT,request_ref TEXT,seq INTEGER,blob TEXT,PRIMARY KEY(profile,operation_id));
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None); c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=FULL'); c.execute('PRAGMA busy_timeout=15000')
        try: yield c
        finally: c.close()

    @contextmanager
    def tx(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                yield c; c.execute('COMMIT')
            except BaseException:
                if c.in_transaction: c.execute('ROLLBACK')
                raise

    def event(self, c, profile, oid, stage, request_ref):
        sample = self.clock.sample(profile, PROFILE_SCOPES[profile], oid, stage, request_ref)
        return checked_event_clock(c, sample, self.root_public, self.clock.instance_id, profile, PROFILE_SCOPES[profile], oid, stage, request_ref)

    @staticmethod
    def row_ref(ns, key, revision, record):
        if ns in ('UNIT', 'ENCOUNTER', 'BEHAVIOR'):
            return digest(['ZJJ-STATE-v1', ns, key, str(revision), record['value']])
        return rec_ref(record)

    def publish(self, certificate):
        require(type(certificate) is dict and set(certificate) == {'claim', 'signature'}, 'CONTROL_FIELDS')
        cl = certificate['claim']
        require(set(cl) == {'profile', 'scope', 'namespace', 'key', 'previous_revision', 'record', 'active', 'enrollment'}, 'CONTROL_FIELDS')
        p = cl['profile']; require(p in PROFILE_SCOPES and cl['scope'] == PROFILE_SCOPES[p], 'BINDING')
        strict_verify(self.root_public, raw(certificate['signature'], 64), canonical(['COMP-APP-C-PUBLISH-v1', cl]))
        ns, key, r = cl['namespace'], cl['key'], cl['record']
        require(type(key) is list and all(type(k) is str for k in key) and type(cl['active']) is bool, 'CONTROL_FIELDS')
        require(set(r) == {'version','profile','kind','scope','value'} and (r['version'],r['profile'],r['scope']) == ('2.6',p,cl['scope']), 'BINDING')
        allowed = {'POLICY':'POLICY','KEY':'KEY_GRANT','ROLE':'ROLE_GRANT','BEHAVIOR':'BEHAVIOR','UNIT':'UNIT','ENCOUNTER':'ENCOUNTER','TASK':{'IND-DEMO-1':'IND_TASK','MED-DEMO-1':'MED_TASK','PAY-1':'PAY_TASK'}[p], 'IDENTITY':'IND_UNIT' if p == 'IND-DEMO-1' else 'MED_ENCOUNTER','PACKAGE':'IND_PACKAGE','EVIDENCE':'IND_EVIDENCE' if p == 'IND-DEMO-1' else 'MED_EVIDENCE','ORDER':'PAY_EVIDENCE','EXPERIENCE':'PAY_HISTORY'}
        require(ns in allowed and r['kind'] in (allowed[ns], allowed[ns] + '_STATE'), 'OBJECT_KIND')
        if ns not in ('UNIT','ENCOUNTER','BEHAVIOR'):
            self.schemas[p].validate(r, 'Record_' + allowed[ns])
        with self.tx() as c:
            event = self.event(c, p, '', 'CONTROL_PUBLISH', rec_ref(r))
            old = c.execute('SELECT * FROM a_current WHERE profile=? AND namespace=? AND key=?',(p,ns,enc(key))).fetchone()
            rev = (old['revision'] if old else 0) + 1
            require(str(rev-1) == cl['previous_revision'], 'NONMONOTONIC')
            require(not (ns == 'KEY' and old and old['active'] == 0 and cl['active']), 'REVOKED_KEY_TOMBSTONE')
            v = r['value']
            if ns in ('KEY','ROLE'):
                require(v['epoch'] == str(rev), 'ROW_VERSION')
                require_window(v, event)
            if ns == 'KEY':
                require(key == [v['kid']] and keyid(raw(v['public_key'],32)) == v['kid'], 'KEY_BINDING')
                who = next((a for a in self.actors[p].values() if a.kid == v['kid']), None)
                require(who is not None and who.name == v['subject'] and b64(who.pub) == v['public_key'] and set(v['purposes']) <= who.purposes, 'ROSTER_BINDING')
                if cl['active']:
                    self._possession(cl['enrollment'], p, v, event)
            if ns == 'ROLE':
                require(key == prefix(p) + [v['subject'],v['role']] and v['scope_set'] == [PROFILE_SCOPES[p]], 'ROLE_BINDING')
                require(any(a.name == v['subject'] and v['role'] in (ROLES[p][alias], 'READER' if p != 'PAY-1' else ROLES[p][alias]) for alias,a in self.actors[p].items()), 'ROSTER_BINDING')
            ref = self.row_ref(ns,key,rev,r)
            c.execute('INSERT INTO a_current VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(profile,namespace,key) DO UPDATE SET revision=excluded.revision,ref=excluded.ref,record=excluded.record,active=excluded.active,certificate=excluded.certificate', (p,ns,enc(key),rev,ref,enc(r),int(cl['active']),enc(certificate)))
            c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',('CONTROL',p,'',enc({'certificate':certificate,'event':event,'revision':rev,'ref':ref})))
        return ref

    @staticmethod
    def _possession(proof, profile, grant, event):
        require(type(proof) is dict and set(proof) == {'tuple','enrollment_id','nonce','iat','exp','signature'}, 'POP_REQUIRED')
        t = proof['tuple']; require_window(proof,event)
        require(t == {'scope': PROFILE_SCOPES[profile], 'subject':grant['subject'],'public_key':grant['public_key'],'kid':grant['kid'],'purposes':grant['purposes'],'key_not_before':grant['iat'],'key_not_after':grant['exp'],'root_generation':grant['root_generation']}, 'POP_BINDING')
        raw(proof['enrollment_id'],16); raw(proof['nonce'],32)
        strict_verify(raw(grant['public_key'],32),raw(proof['signature'],64),canonical(['ZJJ-ENROLL-v1','2.6',t,proof['enrollment_id'],proof['nonce'],proof['iat'],proof['exp']]))
        require(grant['enrollment_ref'] == digest(['COMP-APP-POP-v1',proof]), 'POP_BINDING')

    def current(self, c, profile, ns, key):
        row = c.execute('SELECT * FROM a_current WHERE profile=? AND namespace=? AND key=?',(profile,ns,enc(key))).fetchone()
        require(row is not None, 'STATE_UNAVAILABLE'); require(row['active'] == 1, 'REVOKED')
        cert = json.loads(row['certificate']); cl = cert['claim']; r = json.loads(row['record'])
        strict_verify(self.root_public,raw(cert['signature'],64),canonical(['COMP-APP-C-PUBLISH-v1',cl]))
        require(cl['profile'] == profile and cl['scope'] == PROFILE_SCOPES[profile] and cl['namespace'] == ns and cl['key'] == key and cl['record'] == r and cl['active'] is True and int(cl['previous_revision'])+1 == row['revision'] and self.row_ref(ns,key,row['revision'],r) == row['ref'], 'STATE_INTEGRITY')
        return {'revision': row['revision'], 'ref':row['ref'], 'record':r, 'certificate':cert}

    def credential(self, c, profile, alias, role, purpose, action, event):
        who = self.actors[profile][alias]
        require(role == ROLES[profile][alias] or (role == 'READER' and profile != 'PAY-1'), 'NO_ROLE')
        k = self.current(c,profile,'KEY',[who.kid]); r = self.current(c,profile,'ROLE',prefix(profile)+[who.name,role])
        kv,rv = k['record']['value'],r['record']['value']
        require(kv['subject'] == rv['subject'] == who.name and kv['kid'] == who.kid and kv['public_key'] == b64(who.pub) and purpose in kv['purposes'] and purpose in who.purposes and rv['role'] == role and PROFILE_SCOPES[profile] in rv['scope_set'], 'NO_ROLE')
        require(kv['epoch'] == str(k['revision']) and rv['epoch'] == str(r['revision']), 'STALE')
        require_window(kv,event); require_window(rv,event)
        if action:
            require(action['scope'] == PROFILE_SCOPES[profile] and action['tool'] in rv['tool_set'] and action['destination'] in rv['destination_set'], 'NO_ROLE')
            p = action['payload']; rule = rv['constraints']
            if profile == 'PAY-1':
                require(p['payer'] in rule['payer_set'] and int(p['amount_minor']) <= int(rule['max_amount_minor']), 'NO_ROLE')
            elif profile == 'IND-DEMO-1':
                require(p['line_id'] in rule['line_set'] and p['station_id'] in rule['station_set'] and p['route'] in rule['route_set'] and ('unit_set' not in rule or p['unit_id'] in rule['unit_set']), 'NO_ROLE')
            else:
                require(p['synthetic_patient_id'] in rule['patient_set'] and p['encounter_id'] in rule['encounter_set'] and p['template_id'] in rule['template_set'], 'NO_ROLE')
        return k,r

    def read_permission(self, c, profile, alias, action, event):
        policy = self.current(c,profile,'POLICY',prefix(profile))['record']['value']
        require_window(policy,event)
        require(self.actors[profile][alias].name in policy['readers'], 'NO_ROLE')
        # Original PAY has no READER role: policy ACL + scoped actor role, not an invalid new wire grant.
        self.credential(c,profile,alias,'READER' if profile != 'PAY-1' else ROLES[profile][alias],'READ',action,event)

    def challenge(self, profile, op, stage='GUARD'):
        require(stage in ('GUARD','CANDIDATE','DETAIL'), 'IDENTITY_STAGE')
        oid = op['action']['operation_id']; ref = digest(['COMP-APP-CALL-v1',profile,op])
        with self.tx() as c:
            event = self.event(c,profile,oid,'AUTHZ_READ' if stage != 'GUARD' else 'AUTHZ_GUARD',ref)
            nonce=b64(os.urandom(32)); c.execute('INSERT INTO a_identity VALUES(?,?,?,?,?,?,0)',(nonce,profile,oid,ref,stage,event['lo']+30))
        return {'profile':profile,'scope':PROFILE_SCOPES[profile],'operation_id':oid,'request_ref':ref,'stage':stage,'nonce':nonce}

    def authenticate(self, c, profile, op, proof, stage, event):
        require(type(proof) is dict and set(proof)=={'claim','signature'}, 'IDENTITY_REQUIRED')
        cl=proof['claim']; ref=digest(['COMP-APP-CALL-v1',profile,op]); who=self.actors[profile]['H']
        require(set(cl)=={'profile','scope','operation_id','request_ref','stage','nonce'} and (cl['profile'],cl['scope'],cl['operation_id'],cl['request_ref'],cl['stage']) == (profile,PROFILE_SCOPES[profile],op['action']['operation_id'],ref,stage), 'BINDING')
        strict_verify(who.pub,raw(proof['signature'],64),canonical(['COMP-APP-AUTHZ-IDENTITY-v1',cl]))
        nonce=c.execute('SELECT * FROM a_identity WHERE nonce=?',(cl['nonce'],)).fetchone()
        require(nonce is not None and nonce['used']==0 and nonce['request_ref']==ref and nonce['stage']==stage,'REPLAY')
        require_window({'iat':'0','exp':str(nonce['expires'])},event)
        self.credential(c,profile,'H',ROLES[profile]['H'],'IssueRequest',op['action'],event)
        self.read_permission(c,profile,'H',op['action'],event)
        c.execute('UPDATE a_identity SET used=1 WHERE nonce=?',(cl['nonce'],))

    def initialize_coverage(self, certificate):
        require(set(certificate)=={'claim','signature'}, 'COVERAGE_FIELDS')
        cl=certificate['claim']; p=cl['profile']
        require(set(cl)=={'profile','scope','operation_id','ctx','action','purposes','revision','complete','refs'} and p in PROFILE_SCOPES and cl['scope']==PROFILE_SCOPES[p] and cl['action']['scope']==cl['scope'] and cl['action']['operation_id']==cl['operation_id'] and cl['ctx']['scope']==cl['scope'] and cl['ctx']['operation_id']==cl['operation_id'] and cl['revision']=='1' and cl['complete'] is True and cl['refs']==[] and cl['purposes']==sortset(cl['purposes']) and 'EXECUTE' in cl['purposes'],'COVERAGE_FIELDS')
        strict_verify(self.root_public,raw(certificate['signature'],64),canonical(['COMP-APP-DENY-COVERAGE-v1',cl]))
        require(cl['ctx']['action_hash']==action_hash(p,cl['action']) and all(cl['ctx'][k]==cl['action'][k] for k in ('principal','holder','holder_kid','executor')),'COVERAGE_FIELDS')
        with self.tx() as c:
            c.execute('INSERT INTO a_deny_range VALUES(?,?,?,?,?,?,?)',(p,cl['operation_id'],cl['ctx']['basis_ref'],1,enc(cl['ctx']),enc(cl['purposes']),enc(certificate)))
            c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',('COVERAGE',p,cl['operation_id'],enc(certificate)))

    def deny_witness(self,c,profile,ctx,required):
        row=c.execute('SELECT * FROM a_deny_range WHERE profile=? AND operation_id=? AND basis_ref=?',(profile,ctx['operation_id'],ctx['basis_ref'])).fetchone()
        require(row is not None,'DENY_COVERAGE_UNKNOWN')
        cert=json.loads(row['root_certificate']); cl=cert['claim']
        strict_verify(self.root_public,raw(cert['signature'],64),canonical(['COMP-APP-DENY-COVERAGE-v1',cl]))
        require(json.loads(row['context'])==cl['ctx']==ctx and cl['complete'] is True and json.loads(row['purposes'])==cl['purposes']==sortset(['EXECUTE']+required),'DENY_COVERAGE_UNKNOWN')
        records=c.execute('SELECT * FROM a_publication WHERE profile=? AND operation_id=? AND basis_ref=? ORDER BY seq',(profile,ctx['operation_id'],ctx['basis_ref'])).fetchall()
        require(row['revision']==1+len(records),'DENY_COVERAGE_UNKNOWN')
        from competition.support.wire import envelope, msgref
        for index, publication in enumerate(records):
            message=json.loads(publication['message']); payload=message['body']['payload']
            alias='V' if message['protected']['type']=='Review' else 'U'; who=self.actors[profile][alias]
            journal=c.execute('SELECT * FROM a_journal WHERE seq=?',(publication['seq'],)).fetchone()
            require(journal is not None and journal['kind']=='PUBLICATION' and journal['profile']==profile and journal['operation_id']==ctx['operation_id'],'DENY_COVERAGE_UNKNOWN')
            fact=json.loads(journal['blob']); event=fact['event']
            self.schemas[profile].validate(message,'Review' if alias=='V' else 'Authorization')
            envelope(message,{who.kid:who},now=event['lo'],proto=self.protocol); require_window(message['body'],event)
            strict_verify(self.root_public,raw(event['sample']['signature'],64),canonical(['ZJJ-COMP-EVENT-CLOCK-v1',event['sample']['claim']]))
            require(fact['message']==message and fact['previous_revision']==index+1 and msgref(message)==publication['ref'] and payload['ctx']==ctx and payload['purpose']==publication['purpose'] and payload['verdict']==publication['verdict'] and payload['purpose'] in cl['purposes'] and message['protected']['issuer']==who.name and message['body']['scope']==PROFILE_SCOPES[profile],'DENY_COVERAGE_UNKNOWN')
            sample=event['sample']['claim']
            require((sample['profile'],sample['scope'],sample['operation_id'],sample['stage'],sample['request_ref'])==(profile,PROFILE_SCOPES[profile],ctx['operation_id'],'DENY_PUBLISH',msgref(message)),'DENY_COVERAGE_UNKNOWN')
        refs=sortset([x['ref'] for x in records if x['verdict']=='DENY' and x['purpose'] in cl['purposes']])
        return {'profile':profile,'scope':PROFILE_SCOPES[profile],'operation_id':ctx['operation_id'],'basis_ref':ctx['basis_ref'],'revision':row['revision'],'complete':True,'refs':refs,'publication_seqs':[x['seq'] for x in records],'w_seq':c.execute('SELECT COALESCE(MAX(seq),0) FROM a_journal').fetchone()[0]}
