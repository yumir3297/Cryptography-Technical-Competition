"""Three-Profile SQLite simulator with authenticated EXEC and QUERY-only recovery.

Local trusted-host demonstration: subprocesses do not establish DAC/HSM isolation
and the hash checkpoint does not prove resistance to a complete disk rollback.
"""
from __future__ import annotations
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager, closing
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from competition.core.event_clock import checked_event_clock, require_window, refresh_event_age
from competition.core.signing import ClockClient
from research.phase6.trusted_final import verify_certificate, final_fact_id, final_sign_bytes
from research.reference_executor.wire import (ProtocolError, require, raw, b64, canonical,
    digest, keyid, strict_verify, action_hash, rec_ref, number, is_id, good_point)
from research.strict_v26.upstream_schema import UpstreamSchema

EXEC_DOMAIN = 'COMP-W-TOOL-EXEC-v1'
QUERY_DOMAIN = 'COMP-W-TOOL-QUERY-v1'
CHECKPOINT_DOMAIN = 'COMP-TOOL-CHECKPOINT-v1'
EXEC_FIELDS = frozenset({'profile','scope','operation_id','attempt_id','ledger_id','ledger_origin',
    'action','action_hash','commit_ref','acceptance_ref','tool_trust_ref','issued_at','expires'})
QUERY_FIELDS = EXEC_FIELDS | {'query_id','iat','exp'}
EFFECT_FIELDS = {
    'PAY-1': ('payments', ('order_id','stage','payer','payee','amount_minor','currency','purpose')),
    'IND-DEMO-1': ('industrial_routes', ('line_id','station_id','unit_id','batch_id','inspection_cycle','phase','route')),
    'MED-DEMO-1': ('medical_orders', ('synthetic_patient_id','encounter_id','order_group_id','phase','template_id','record_ref','destination_system')),
}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':'))


def ledger_head(ledger_id, facts):
    return digest(['ZJJ-LEDGER-SNAPSHOT-RESEARCH-v1', ledger_id, facts])


def request_hash(claim):
    return digest(['COMP-W-TOOL-REQUEST-v1', {k:claim[k] for k in EXEC_FIELDS}])


def create_tool_database(path, profile, ledger_id):
    require(profile in EFFECT_FIELDS and is_id(ledger_id), 'TOOL_CONFIGURATION')
    path = Path(path).resolve()
    require(not path.exists(), 'LEDGER_EXISTS')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally reinitializing an unresolved ledger.
    with path.open('xb'):
        pass
    origin = b64(os.urandom(32))
    with closing(sqlite3.connect(path)) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=FULL')
        c.executescript('''
          CREATE TABLE tool_meta(id INTEGER PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL,
            ledger_id TEXT NOT NULL,ledger_origin TEXT NOT NULL,high_water INTEGER NOT NULL,
            ledger_head TEXT NOT NULL,certificate TEXT);
          CREATE TABLE tool_requests(operation_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL UNIQUE,claim TEXT NOT NULL);
          CREATE TABLE tool_finalfacts(operation_id TEXT PRIMARY KEY REFERENCES tool_requests(operation_id),
            attempt_id TEXT NOT NULL UNIQUE,final_seq INTEGER NOT NULL UNIQUE,effect_id TEXT UNIQUE,
            final_fact_id TEXT NOT NULL UNIQUE,fact TEXT NOT NULL);
          CREATE TABLE tool_clock_sessions(session_id TEXT PRIMARY KEY,instance_id TEXT NOT NULL);
        ''')
        for table, fields in EFFECT_FIELDS.values():
            columns = ','.join(f'{name} TEXT NOT NULL' for name in fields)
            c.execute(f'CREATE TABLE {table}(operation_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL UNIQUE,effect_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,{columns})')
        for table in ('tool_requests','tool_finalfacts',*(v[0] for v in EFFECT_FIELDS.values())):
            for verb in ('UPDATE','DELETE'):
                c.execute(f"CREATE TRIGGER {table}_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TOOL_LEDGER'); END")
        c.execute('INSERT INTO tool_meta VALUES(1,?,?,?,0,?,NULL)',(profile,ledger_id,origin,ledger_head(ledger_id,[])))
        c.commit()
    return {'ledger_id':ledger_id,'ledger_origin':origin}


class CommonToolLedger:
    def __init__(self,path,profile,*,certificate,root_public,w_public,private_key,clock):
        self.path = str(Path(path).resolve())
        self.profile = profile
        self.root_public = root_public
        self.w_public = w_public
        self.private_key = private_key
        self.clock = clock
        self.certificate = json.loads(_json(certificate))
        self.trust = verify_certificate(self.certificate,root_public,profile)
        self.scope = self.trust['scope']
        self.ledger_id = self.trust['value']['ledger_id']
        self.ledger_origin = self.certificate['claim']['ledger_origin']
        pub = private_key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        require(good_point(w_public) and good_point(root_public),'TOOL_CONFIGURATION')
        require(b64(pub)==self.trust['value']['public_key'] and keyid(pub)==self.trust['value']['kid'],'TOOL_KEY')
        self.schema = UpstreamSchema(Path(__file__).resolve().parents[2],profile)
        self.schema.validate(self.trust,'Record_TOOL_TRUST')
        self.session_id = b64(os.urandom(16))
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            self._continuity(c)
            saved = c.execute('SELECT certificate FROM tool_meta WHERE id=1').fetchone()[0]
            if saved is None:
                meta = c.execute('SELECT high_water,ledger_head FROM tool_meta WHERE id=1').fetchone()
                require(meta['high_water']==0 and self.certificate['claim']['ledger_head']==meta['ledger_head'],'CONTINUITY_UNKNOWN')
                c.execute('UPDATE tool_meta SET certificate=? WHERE id=1',(_json(self.certificate),))
            else:
                require(json.loads(saved)==self.certificate,'TOOL_TRUST_CHANGED')
            c.execute('INSERT INTO tool_clock_sessions VALUES(?,?)',(self.session_id,clock.instance_id))
            c.execute('COMMIT')

    @contextmanager
    def _db(self):
        require(Path(self.path).is_file(),'CONTINUITY_UNKNOWN')
        try:
            uri = Path(self.path).as_uri()+'?mode=rw'
            c = sqlite3.connect(uri,uri=True,isolation_level=None,timeout=20)
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA synchronous=FULL')
            c.execute('PRAGMA foreign_keys=ON')
            try:
                yield c
            finally:
                if c.in_transaction:
                    c.execute('ROLLBACK')
                c.close()
        except sqlite3.Error as exc:
            raise ProtocolError('CONTINUITY_UNKNOWN') from exc

    def _facts(self,c):
        return [json.loads(row[0]) for row in c.execute('SELECT fact FROM tool_finalfacts ORDER BY final_seq')]

    def _continuity(self,c):
        m = c.execute('SELECT * FROM tool_meta WHERE id=1').fetchone()
        require(m is not None and (m['profile'],m['ledger_id'],m['ledger_origin']) ==
                (self.profile,self.ledger_id,self.ledger_origin),'CONTINUITY_UNKNOWN')
        facts = self._facts(c)
        require(m['high_water']==len(facts) and m['ledger_head']==ledger_head(self.ledger_id,facts),'CONTINUITY_UNKNOWN')
        requests = {r['operation_id']:r for r in c.execute('SELECT * FROM tool_requests')}
        require(len(requests)==len(facts),'CONTINUITY_UNKNOWN')
        table,_ = EFFECT_FIELDS[self.profile]
        effects = {r['operation_id']:r for r in c.execute(f'SELECT * FROM {table}')}
        require(len(effects)==len(facts),'CONTINUITY_UNKNOWN')
        for seq, row in enumerate(c.execute('SELECT * FROM tool_finalfacts ORDER BY final_seq'),1):
            fact = json.loads(row['fact']); r = requests.get(row['operation_id']); e = effects.get(row['operation_id'])
            require(r is not None and e is not None,'CONTINUITY_UNKNOWN')
            claim = json.loads(r['claim'])
            rec = {'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':self.scope,'value':fact}
            require(row['final_seq']==seq and fact['final_seq']==str(seq) and row['final_fact_id']==final_fact_id(rec)
                and row['attempt_id']==r['attempt_id']==e['attempt_id']==fact['dispatch_attempt']
                and row['effect_id']==e['effect_id']==fact['effect_id']
                and request_hash(claim)==r['request_hash']
                and fact['action_hash']==claim['action_hash']==action_hash(self.profile,claim['action'])
                and json.loads(e['payload'])==claim['action']['payload'],'CONTINUITY_UNKNOWN')
            for name in EFFECT_FIELDS[self.profile][1]:
                require(e[name]==claim['action']['payload'][name],'CONTINUITY_UNKNOWN')
        for other,_ in EFFECT_FIELDS.values():
            if other != table:
                require(c.execute(f'SELECT COUNT(*) FROM {other}').fetchone()[0]==0,'CONTINUITY_UNKNOWN')

    def _verify(self,packet,query):
        require(type(packet) is dict and set(packet)=={'claim','signature'},'TOOL_REQUEST_FIELDS')
        cl = packet['claim']
        require(type(cl) is dict and set(cl)==(QUERY_FIELDS if query else EXEC_FIELDS),'TOOL_REQUEST_FIELDS')
        strict_verify(self.w_public,raw(packet['signature'],64),canonical([QUERY_DOMAIN if query else EXEC_DOMAIN,cl]))
        require(cl['profile']==self.profile and cl['scope']==self.scope and
            cl['ledger_id']==self.ledger_id and cl['ledger_origin']==self.ledger_origin,'TOOL_REQUEST_BINDING')
        raw(cl['operation_id'],16); raw(cl['attempt_id'],16)
        for field in ('action_hash','commit_ref','acceptance_ref','tool_trust_ref'):
            raw(cl[field],32)
        action = cl['action']
        self.schema.validate(action,'Action')
        require(action['scope']==self.scope and action['operation_id']==cl['operation_id']
            and action_hash(self.profile,action)==cl['action_hash'],'TOOL_REQUEST_BINDING')
        require(all(action[k]==self.trust['value'][k] for k in ('tool','tool_version','destination'))
            and cl['tool_trust_ref']==rec_ref(self.trust),'TOOL_REQUEST_BINDING')
        require(number(cl['issued_at']) and number(cl['expires']) and int(cl['issued_at'])<int(cl['expires']),'TOOL_REQUEST_TIME')
        if query:
            raw(cl['query_id'],16)
            require(number(cl['iat']) and number(cl['exp']) and 0<int(cl['exp'])-int(cl['iat'])<=900,'TOOL_REQUEST_TIME')
        return {k:cl[k] for k in EXEC_FIELDS},request_hash(cl)

    def _event(self,c,packet,rh,query,*,check_request=True):
        cl = packet['claim']
        require(verify_certificate(self.certificate,self.root_public,self.profile)==self.trust,'TOOL_TRUST_CHANGED')
        pin = c.execute('SELECT instance_id FROM tool_clock_sessions WHERE session_id=?',(self.session_id,)).fetchone()
        require(pin is not None and pin[0]==self.clock.instance_id,'CLOCK_UNKNOWN')
        eventref = digest([QUERY_DOMAIN if query else EXEC_DOMAIN,cl])
        sampled = self.clock.sample(self.profile,self.scope,cl['operation_id'],'TOOL_FINAL_AUTH',eventref)
        event = checked_event_clock(c,sampled,self.root_public,pin[0],self.profile,self.scope,cl['operation_id'],'TOOL_FINAL_AUTH',eventref)
        require_window(self.trust['value'],event)
        if check_request:require_window({'iat':cl['iat'],'exp':cl['exp']} if query else {'iat':cl['issued_at'],'exp':cl['expires']},event)
        return event

    def _known(self,c,cl,rh):
        rows = c.execute('SELECT * FROM tool_requests WHERE operation_id=? OR attempt_id=?',(cl['operation_id'],cl['attempt_id'])).fetchall()
        for row in rows:
            require(row['operation_id']==cl['operation_id'] and row['attempt_id']==cl['attempt_id']
                and row['request_hash']==rh and json.loads(row['claim'])==cl,'TOOL_REQUEST_CONFLICT')
        if not rows:
            return None
        row = c.execute('SELECT fact FROM tool_finalfacts WHERE operation_id=?',(cl['operation_id'],)).fetchone()
        require(row is not None,'CONTINUITY_UNKNOWN')
        return json.loads(row[0])

    def execute_once(self,packet,*,crash_after_commit=False):
        cl,rh = self._verify(packet,False)
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE'); self._continuity(c)
            fact = self._known(c,cl,rh)
            event = self._event(c,packet,rh,False)
            before = self._counts(c)
            event=refresh_event_age(event);require_window(self.trust['value'],event);require_window({'iat':cl['issued_at'],'exp':cl['expires']},event)
            if fact is None:
                seq = int(before['high_water'])+1
                effect = 'effect-'+os.urandom(16).hex()
                fact = {'ledger_id':self.ledger_id,'operation_id':cl['operation_id'],'action_hash':cl['action_hash'],
                    'dispatch_attempt':cl['attempt_id'],'tool':cl['action']['tool'],'tool_version':cl['action']['tool_version'],
                    'destination':cl['action']['destination'],'outcome':'SUCCEEDED','effect_id':effect,'no_late_effect':False,
                    'final_seq':str(seq),'finalized_at':str(event['lo'])}
                c.execute('INSERT INTO tool_requests VALUES(?,?,?,?)',(cl['operation_id'],cl['attempt_id'],rh,_json(cl)))
                table, fields = EFFECT_FIELDS[self.profile]; payload=cl['action']['payload']
                names = ('operation_id','attempt_id','effect_id','payload',*fields)
                c.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",
                    (cl['operation_id'],cl['attempt_id'],effect,_json(payload),*(payload[k] for k in fields)))
                rec = {'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':self.scope,'value':fact}
                c.execute('INSERT INTO tool_finalfacts VALUES(?,?,?,?,?,?)',(cl['operation_id'],cl['attempt_id'],seq,effect,final_fact_id(rec),_json(fact)))
                c.execute('UPDATE tool_meta SET high_water=?,ledger_head=? WHERE id=1',(seq,ledger_head(self.ledger_id,self._facts(c))))
            after = self._counts(c)
            event=self._event(c,packet,rh,False)
            response_data = self._response_data(c,cl,rh,fact,event,before,after)
            c.execute('COMMIT')
        if crash_after_commit:
            os._exit(98)
        return self._sign_response(response_data,packet,False)

    def query_attempt(self,packet):
        cl,rh = self._verify(packet,True)
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE'); self._continuity(c)
            fact = self._known(c,cl,rh)
            event = self._event(c,packet,rh,True)
            counts = self._counts(c)
            event=refresh_event_age(event);require_window(self.trust['value'],event);require_window({'iat':packet['claim']['iat'],'exp':packet['claim']['exp']},event)
            response_data = self._response_data(c,cl,rh,fact,event,counts,counts)
            c.execute('COMMIT')
        return self._sign_response(response_data,packet,True)

    def _counts(self,c):
        m = c.execute('SELECT high_water,ledger_head FROM tool_meta WHERE id=1').fetchone()
        return {'high_water':str(m['high_water']),'ledger_head':m['ledger_head'],
                'effect_count':str(sum(c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table,_ in EFFECT_FIELDS.values()))}

    def _response_data(self,c,cl,rh,fact,event,before,after):
        rec = None
        if fact is not None:
            at = max(event['lo'],int(fact['finalized_at']))
            exp = min(at+120,int(self.trust['value']['exp']))
            require(at<exp,'TOOL_REQUEST_TIME')
            rec = {'version':'2.6','profile':self.profile,'kind':'TOOL_FINAL','scope':self.scope,
                'value':{'method':'tool-final-v2',**fact,'iat':str(at),'exp':str(exp),
                    'attestation':{'issuer':self.trust['value']['issuer'],'kid':self.trust['value']['kid'],'sig':''}}}
        checkpoint = {'profile':self.profile,'scope':self.scope,'operation_id':cl['operation_id'],
            'attempt_id':cl['attempt_id'],'ledger_id':self.ledger_id,'ledger_origin':self.ledger_origin,
            'request_hash':rh,'final_fact_id':final_fact_id(rec) if rec else '',
            'high_water':after['high_water'],'ledger_head':after['ledger_head']}
        return {'state':fact['outcome'] if fact else 'EFFECT_UNKNOWN','record':rec,
            'checkpoint':{'claim':checkpoint,'signature':''},'time_witness':event,'before':before,'after':after}

    def _sign_response(self,response,packet,query):
        # Authentication happens after the business COMMIT. Failure here leaves
        # the immutable fact intact, recoverable only by an authenticated QUERY.
        cl,rh=self._verify(packet,query)
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE');self._continuity(c);fact=self._known(c,cl,rh)
            event=self._event(c,packet,rh,query,check_request=False);counts=self._counts(c)
            response=self._response_data(c,cl,rh,fact,event,response['before'],counts)
            c.execute('COMMIT')
        event=refresh_event_age(event);require_window(self.trust['value'],event)
        response['time_witness']=event
        if response['record'] is not None:
            rec = response['record']
            rec['value']['attestation']['sig'] = b64(self.private_key.sign(final_sign_bytes(rec)))
            self.schema.validate(rec,'Record_TOOL_FINAL')
        cl = response['checkpoint']['claim']
        response['checkpoint']['signature']=b64(self.private_key.sign(canonical([CHECKPOINT_DOMAIN,cl])))
        return response

    def snapshot(self):
        with self._db() as c:
            c.execute('BEGIN'); self._continuity(c)
            meta = dict(c.execute('SELECT profile,ledger_id,ledger_origin,high_water,ledger_head FROM tool_meta WHERE id=1').fetchone())
            meta['high_water']=str(meta['high_water'])
            requests = [dict(r) for r in c.execute('SELECT * FROM tool_requests ORDER BY operation_id')]
            for r in requests: r['claim']=json.loads(r['claim'])
            facts = [dict(r) for r in c.execute('SELECT * FROM tool_finalfacts ORDER BY final_seq')]
            for r in facts: r['fact']=json.loads(r['fact']); r['final_seq']=str(r['final_seq'])
            effects = {}
            for table,_ in EFFECT_FIELDS.values():
                effects[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY operation_id')]
                for r in effects[table]: r['payload']=json.loads(r['payload'])
            c.execute('COMMIT')
        return {'meta':meta,'requests':requests,'dedup':[{'operation_id':r['operation_id'],'attempt_id':r['attempt_id'],'request_hash':r['request_hash']} for r in requests],
                'finalfacts':facts,'effects':effects}


class ToolGateway:
    """Fixed local startup configuration; every call starts one actual child."""
    def __init__(self,config_path):
        self.config_path = str(Path(config_path).resolve())
        self.config = json.loads(Path(self.config_path).read_text(encoding='utf-8'))
        required = {'database','profile','certificate','root_public','w_public','tool_key_path','clock_key_path','clock_database'}
        require(required <= set(self.config) <= required|{'crash_after_commit','drop_before_tool'},'TOOL_CONFIGURATION')
        self._frozen_config = _json(self.config)

    def _call(self,operation,packet):
        require(_json(json.loads(Path(self.config_path).read_text(encoding='utf-8')))==self._frozen_config,'TOOL_CONFIGURATION_CHANGED')
        trace = {'pid':None,'exit_code':None,'started':False,'input_submitted':False}
        try:
            p = subprocess.Popen([sys.executable,'-m','competition.tools.common_tool',operation,self.config_path],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
                cwd=str(Path(__file__).resolve().parents[2]))
            trace.update(pid=p.pid,started=True)
            try:
                # A process-launch flag is not an EXEC-send observation. Mark
                # the actual complete pipe write only after a successful flush.
                wire=_json(packet)
                require(p.stdin.write(wire)==len(wire),'TOOL_TRANSPORT_UNKNOWN')
                p.stdin.flush();trace['input_submitted']=True
                p.stdin.close();p.stdin=None
                output,_ = p.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill(); p.communicate(); trace['exit_code']=p.returncode
                return {'state':'EFFECT_UNKNOWN','record':None,'checkpoint':None,'time_witness':None,'trace':trace}
            trace['exit_code']=p.returncode
            if p.returncode==0:
                response = json.loads(output)
                if 'error' in response:
                    error=ProtocolError(response['error']);error.trace=trace;raise error
                response['trace']=trace
                return response
        except (OSError,ValueError) as exc:
            if isinstance(exc,ProtocolError):
                raise
        return {'state':'EFFECT_UNKNOWN','record':None,'checkpoint':None,'time_witness':None,'trace':trace}

    def execute(self,packet):
        return self._call('execute',packet)

    def query(self,packet):
        return self._call('query',packet)


def worker(operation,config_path):
    clock = None
    try:
        gateway = ToolGateway(config_path); config=gateway.config
        require(operation in {'execute','query'},'TOOL_OPERATION')
        packet=json.loads(sys.stdin.read())
        if config.get('drop_before_tool') is True and operation=='execute':
            os._exit(97)
        clock=ClockClient(config['clock_key_path'],config['clock_database'])
        ledger=CommonToolLedger(config['database'],config['profile'],certificate=config['certificate'],
            root_public=raw(config['root_public'],32),w_public=raw(config['w_public'],32),
            private_key=Ed25519PrivateKey.from_private_bytes(Path(config['tool_key_path']).read_bytes()),clock=clock)
        result=ledger.execute_once(packet,crash_after_commit=config.get('crash_after_commit') is True) if operation=='execute' else ledger.query_attempt(packet)
        print(_json(result),flush=True)
    except Exception as exc:
        print(_json({'error':exc.code if isinstance(exc,ProtocolError) else 'TOOL_UNAVAILABLE'}),flush=True)
    finally:
        if clock is not None:
            clock.close()


if __name__=='__main__':
    worker(*sys.argv[1:])
