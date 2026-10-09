"""Phase 8: independently authenticated IND/MED authority and atomic scene guards.

This is an *experimental* subset of ZJJ CORE 2.6-R2. Ed25519 is real;
C-root and keys are deterministic laboratory fixtures; no enrollment PoP, complete
role constraints, full Receipt/COMMIT integration, or network/tool implementation.
Every authority mutation and acceptance uses a local SQLite transaction.
"""
from __future__ import annotations
import copy, json, sqlite3
from contextlib import contextmanager
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from research.reference_executor.wire import (
    Identity, ProtocolError, b64, raw, require, canonical, strict_verify,
    keyid, digest, rec_ref, action_hash, is_id, sid, sortset, envelope,
)

PROFILES={'IND-DEMO-1':('industrial','IND_EVIDENCE','UNIT','IND_TASK','IND_UNIT'),
          'MED-DEMO-1':('medical','MED_EVIDENCE','ENCOUNTER','MED_TASK','MED_ENCOUNTER')}
MAPPING={'DEMO_NORMAL':'RELEASE','DEMO_DEFECT':'QUARANTINE','DEMO_UNCERTAIN':'INSPECT'}
DEST={'RELEASE':'ind-release-bin','QUARANTINE':'ind-quarantine-bin','INSPECT':'ind-inspection-bay'}
TEMPLATES={'DEMO_A':'DEMO-ORDER-A','DEMO_B':'DEMO-ORDER-B'}
EVID_FIELDS={
 'IND-DEMO-1':{'evidence_id','evidence_revision','unit_ref','unit_id','batch_id','line_id','station_id','inspection_cycle','phase','sampled_at','known_at','quality_flag','label'},
 'MED-DEMO-1':{'evidence_id','evidence_revision','record_id','record_revision','encounter_ref','synthetic_patient_id','encounter_id','record_status','completeness','event_at','known_at','template_label'}}
ACTION_FIELDS={
 'IND-DEMO-1':{'line_id','station_id','unit_id','batch_id','inspection_cycle','phase','route'},
 'MED-DEMO-1':{'synthetic_patient_id','encounter_id','order_group_id','phase','template_id','record_ref','destination_system'}}
ROLES={'IND-DEMO-1':{'H':'HOLDER','G':'ISSUER','X':'EXECUTOR','U':'LINE_OPERATOR','V':'QUALITY_REVIEWER','E':'SOURCE'},
       'MED-DEMO-1':{'H':'HOLDER','G':'ISSUER','X':'EXECUTOR','U':'MEDICAL_AUTHORIZER','V':'CLINICAL_REVIEWER','E':'SOURCE'}}
PURPOSES={'H':['IssueRequest','ChallengeRequest','CommitProof','StatusQuery','READ'],
          'G':['Permit','Result','READ'], 'X':['Challenge','Acceptance','Result','READ'],
          'U':['Authorization','READ'], 'V':['Review','READ'],'E':['SOURCE','READ']}


def _json(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def _pub(k):return k.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
def _clone(obj):return json.loads(_json(obj))
def _rowkey(ns,key):return _json([ns,key])
def _rec(profile,kind,scope,value):return {'version':'2.6','profile':profile,'kind':kind,'scope':scope,'value':value}


class SceneAuthority:
    def __init__(self,db_path,profile,controller=None,actors=None):
        require(profile in PROFILES,'PROFILE')
        self.profile=profile;scenario,_,_,_,_=PROFILES[profile]
        self.scope={'domain':'lab','tenant':'tenant-1','scenario':scenario}
        self.path=str(db_path); self.controller=controller or Ed25519PrivateKey.from_private_bytes(b'\x45'*32)
        self.root_public=_pub(self.controller)
        self.actors=actors or {name:Identity('fixture-'+name.lower(),10+i,roles=[ROLES[profile][name]],purposes=PURPOSES[name])
                               for i,name in enumerate(('H','G','X','U','V','E'))}
        with self.db() as c:
            c.executescript('''
             CREATE TABLE IF NOT EXISTS current_row(namespace TEXT NOT NULL,key TEXT NOT NULL, revision INTEGER NOT NULL,
              ref TEXT NOT NULL,record TEXT NOT NULL,active INTEGER NOT NULL,PRIMARY KEY(namespace,key));
             CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,key TEXT NOT NULL,blob TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS accept_intent(intent TEXT PRIMARY KEY,operation_id TEXT UNIQUE NOT NULL,
              scene_namespace TEXT NOT NULL,scene_key TEXT NOT NULL,accepted_blob TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'ACCEPTED',
              calls INTEGER NOT NULL DEFAULT 0,attempt TEXT DEFAULT '',settlements INTEGER NOT NULL DEFAULT 0);
             CREATE TABLE IF NOT EXISTS resource(destination TEXT PRIMARY KEY,capacity INTEGER NOT NULL DEFAULT 8,reserved INTEGER NOT NULL DEFAULT 0,spent INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1);
             CREATE TABLE IF NOT EXISTS flight(task_id TEXT PRIMARY KEY,operation_id TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS behavior(principal TEXT PRIMARY KEY,accepted_count INTEGER NOT NULL DEFAULT 0,count_cap INTEGER NOT NULL DEFAULT 32,revision INTEGER NOT NULL DEFAULT 1,inflight TEXT NOT NULL DEFAULT '[]');
             CREATE TABLE IF NOT EXISTS deny(basis_ref TEXT NOT NULL,purpose TEXT NOT NULL, ref TEXT NOT NULL UNIQUE);
            ''')
        self.op_cache={}

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA busy_timeout=10000')
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL')
        try:yield c
        finally:c.close()
    @contextmanager
    def tx(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:yield c;c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:c.execute('ROLLBACK')
                raise
    def current(self,c,ns,key):
        row=c.execute('SELECT * FROM current_row WHERE namespace=? AND key=?',(ns,_json(key))).fetchone()
        require(row is not None,'STATE_UNAVAILABLE')
        require(row['active']==1,'REVOKED')
        return {'revision':row['revision'],'ref':row['ref'],'record':json.loads(row['record'])}
    def _read_row(self,ns,key):
        with self.db() as c:return self.current(c,ns,key)
    def current_record(self,ns,key):return self._read_row(ns,key)['record']
    def _cert(self,ns,key,old_revision,record,active=True):
        claim={'scope':_clone(self.scope),'namespace':ns,'key':key,'previous_revision':str(old_revision),
               'record':record,'active':active}
        return {'claim':claim,'kid':keyid(self.root_public),
                'sig':b64(self.controller.sign(canonical(['ZJJ-C-CONTROL-LAB-v1',claim])))}
    def certify(self,ns,key,record,*,active=True):
        with self.db() as c:
            row=c.execute('SELECT revision FROM current_row WHERE namespace=? AND key=?',(ns,_json(key))).fetchone()
        return self._cert(ns,key,row['revision'] if row else 0,record,active)
    def publish_cert(self,certificate):
        require(set(certificate)=={'claim','kid','sig'},'CONTROL_FIELDS')
        claim=certificate['claim']
        require(set(claim)=={'scope','namespace','key','previous_revision','record','active'},'CONTROL_FIELDS')
        require(claim['scope']==self.scope,'WRONG_SCOPE')
        require(certificate['kid']==keyid(self.root_public),'CONTROL_ROOT')
        strict_verify(self.root_public,raw(certificate['sig'],64),canonical(['ZJJ-C-CONTROL-LAB-v1',claim]))
        ns=claim['namespace']; key=claim['key'];record=claim['record']
        require(type(key) is list and type(claim['active']) is bool,'CONTROL_FIELDS')
        require(record['scope']==self.scope and record['profile']==self.profile and record['version']=='2.6','WRONG_SCOPE')
        allowed={'POLICY':'POLICY','TASK':PROFILES[self.profile][3],'IDENTITY':PROFILES[self.profile][4],
                 'KEY':'KEY_GRANT','ROLE':'ROLE_GRANT','PACKAGE':'IND_PACKAGE'}
        require(ns in allowed and record['kind']==allowed[ns],'OBJECT_KIND')
        require(int(claim['previous_revision'])>=0,'CONTROL_REVISION')
        with self.tx() as c:
            old=c.execute('SELECT revision FROM current_row WHERE namespace=? AND key=?',(ns,_json(key))).fetchone()
            cur=old['revision'] if old else 0
            require(cur==int(claim['previous_revision']),'NONMONOTONIC')
            rv=cur+1;rr=rec_ref(record)
            c.execute('INSERT INTO current_row VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET revision=excluded.revision,ref=excluded.ref,record=excluded.record,active=excluded.active',
                      (ns,_json(key),rv,rr,_json(record),int(claim['active'])))
            c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)',('C',_rowkey(ns,key),_json(certificate)))
        return rr
    def publish(self,ns,key,record,*,active=True):return self.publish_cert(self.certify(ns,key,record,active=active))
    def scope_key(self):return [self.scope[x] for x in ('domain','tenant','scenario')]
    def role_key(self,who,role):return self.scope_key()+[who.name,role]
    def grant(self,alias,roles=None):
        actor=self.actors[alias]
        # Signed by trusted lab C; does NOT implement enrollment PoP or exact full ROLE_GRANT constraints.
        self.publish('KEY',[actor.kid],_rec(self.profile,'KEY_GRANT',self.scope,
           {'subject':actor.name,'kid':actor.kid,'public_key':b64(actor.pub),'epoch':'1',
            'purposes':sortset(list(actor.purposes)),'root_generation':'1','enrollment_ref':digest(['lab-enroll',actor.name]),'iat':'1','exp':'2000'}))
        for role in roles or [ROLES[self.profile][alias]]:
            self.publish('ROLE',self.role_key(actor,role),_rec(self.profile,'ROLE_GRANT',self.scope,
             {'subject':actor.name,'role':role,'epoch':'1','scope_set':[self.scope],
              'tool_set':[('line-sort-sim' if self.profile=='IND-DEMO-1' else 'med-order-sim')],
              'destination_set':sortset(list(DEST.values()) if self.profile=='IND-DEMO-1' else ['med-demo-ledger']),
              'constraints':self._role_constraints(alias,role),'iat':'1','exp':'2000'}))
    def _role_constraints(self,alias,role):
        if self.profile=='IND-DEMO-1':
            if role in ('CONTROLLER','SOURCE','ISSUER','EXECUTOR'):
                return {'line_set':['demo-line-a'],'station_set':['demo-check-1'],'route_set':['RELEASE','QUARANTINE','INSPECT']}
            return {'line_set':['demo-line-a'],'station_set':['demo-check-1'],'unit_set':['unit-a'],
                    'route_set':['INSPECT'] if role=='QUALITY_REVIEWER' else ['RELEASE','QUARANTINE','INSPECT']}
        return {'patient_set':['patient-a'],'encounter_set':['encounter-a'],
                'template_set':['DEMO-ORDER-A','DEMO-ORDER-B']}
    def _credential(self,c,alias,role,purpose,action=None):
        who=self.actors[alias];k=self.current(c,'KEY',[who.kid]);r=self.current(c,'ROLE',self.role_key(who,role))
        kv,rv=k['record']['value'],r['record']['value']
        require(kv['subject']==who.name and kv['kid']==who.kid and purpose in kv['purposes'] and
                b64(who.pub)==kv['public_key'],'NO_ROLE')
        require(rv['subject']==who.name and rv['role']==role and self.scope in rv['scope_set'],'NO_ROLE')
        if action:
            p=action['payload'];rule=rv['constraints']
            require(action['tool'] in rv['tool_set'] and action['destination'] in rv['destination_set'],'NO_ROLE')
            if self.profile=='IND-DEMO-1':
                require(p['line_id'] in rule['line_set'] and p['station_id'] in rule['station_set'] and p['route'] in rule['route_set'],'NO_ROLE')
                if 'unit_set' in rule:require(p['unit_id'] in rule['unit_set'],'NO_ROLE')
            else:
                require(p['synthetic_patient_id'] in rule['patient_set'] and
                    p['encounter_id'] in rule['encounter_set'] and p['template_id'] in rule['template_set'],'NO_ROLE')
        return k,r
    def _read_permission(self,c,alias,action,policy):
        who=self.actors[alias]
        require(who.name in policy['readers'],'NO_ROLE')
        self._credential(c,alias,'READER','READ',action)
    def _state_ref(self,ns,key,revision,body):
        return digest(['ZJJ-STATE-v1',ns,key,str(revision),body])
    def _scene_current(self,c,key):
        ns=PROFILES[self.profile][2];row=self.current(c,ns,key)
        rawrow=row['record']['value'];require(row['ref']==self._state_ref(ns,key,row['revision'],rawrow),'SCENE_INTEGRITY')
        return row
    def init_scene(self,key,value):
        ns=PROFILES[self.profile][2]
        with self.tx() as c:
            require(c.execute('SELECT 1 FROM current_row WHERE namespace=? AND key=?',(ns,_json(key))).fetchone() is None,'SCENE_EXISTS')
            rr=self._state_ref(ns,key,1,value)
            c.execute('INSERT INTO current_row VALUES(?,?,?,?,?,1)',(ns,_json(key),1,rr,_json(_rec(self.profile,ns,self.scope,value))))
            c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)',('SCENE_INIT',_rowkey(ns,key),_json(value)))
    def init_behavior(self,principal):
        key=self.scope_key()+[principal]
        with self.tx() as c:
            old=c.execute('SELECT 1 FROM current_row WHERE namespace=? AND key=?',('BEHAVIOR',_json(key))).fetchone()
            require(old is None,'BEHAVIOR_EXISTS')
            val={'accepted_count':'0','count_cap':'32','inflight':[]}
            ref=self._state_ref('BEHAVIOR',key,1,val)
            c.execute('INSERT INTO current_row VALUES(?,?,?,?,?,1)',('BEHAVIOR',_json(key),1,ref,_json(_rec(self.profile,'BEHAVIOR',self.scope,val))))
            c.execute('INSERT INTO behavior(principal) VALUES(?)',(principal,))

    def _behavior_update(self,c,principal,revision,val):
        key=self.scope_key()+[principal]
        ref=self._state_ref('BEHAVIOR',key,revision+1,val)
        count=c.execute('UPDATE current_row SET revision=?,ref=?,record=? WHERE namespace=? AND key=? AND revision=?',
             (revision+1,ref,_json(_rec(self.profile,'BEHAVIOR',self.scope,val)),'BEHAVIOR',_json(key),revision)).rowcount
        require(count==1,'STALE_BEHAVIOR')
        return ref

    def _scene_witness(self,key,scene):
        return {'namespace':PROFILES[self.profile][2],'key':key,'revision':str(scene['revision']),
                'ref':scene['ref'],'row':_clone(scene['record']['value'])}

    def _behavior_witness(self,principal,row):
        return {'key':self.scope_key()+[principal],'revision':str(row['revision']),
                'ref':row['ref'],'row':_clone(row['record']['value'])}

    def _credential_witnesses(self,c,op,seq):
        result=[]
        needed=('H','E','G','X','U')+(('V',) if op['required'] else ())
        for alias in needed:
            actor=self.actors[alias];role=ROLES[self.profile][alias]
            k=self.current(c,'KEY',[actor.kid]);r=self.current(c,'ROLE',self.role_key(actor,role))
            result.append({'subject':actor.name,'kid':actor.kid,'public_key':b64(actor.pub),
                           'key_grant_ref':k['ref'],'role':role,'role_grant_ref':r['ref'],
                           'key_revision':str(k['revision']),'role_revision':str(r['revision']),
                           'verified_at_seq':str(seq)})
        return sortset(result)

    def _scene_update(self,c,key,revision,value):
        ns=PROFILES[self.profile][2]
        rr=self._state_ref(ns,key,revision+1,value)
        count=c.execute('UPDATE current_row SET revision=?,ref=?,record=? WHERE namespace=? AND key=? AND revision=? AND active=1',
             (revision+1,rr,_json(_rec(self.profile,ns,self.scope,value)),ns,_json(key),revision)).rowcount
        require(count==1,'STALE')
        return rr
    def _evidence_signed(self,data,at=100):
        kind=PROFILES[self.profile][1];e=self.actors['E']
        a={'issuer':e.name,'kid':e.kid,'iat':str(at),'exp':str(at+120)}
        att={**a,'sig':b64(e.key.sign(canonical(['ZJJ-SOURCE-v1','2.6',self.profile,kind,self.scope,data,a])))}
        return _rec(self.profile,kind,self.scope,{'data':data,'attestation':att})
    def sign_evidence(self,data,at=100):return self._evidence_signed(data,at)
    def verify_evidence(self,c,record,at=101):
        kind=PROFILES[self.profile][1]
        require(set(record)=={'version','profile','kind','scope','value'} and
                (record['profile'],record['kind'],record['version'],record['scope'])==(self.profile,kind,'2.6',self.scope),'OBJECT_KIND')
        v=record['value'];require(set(v)=={'data','attestation'} and set(v['data'])==EVID_FIELDS[self.profile],'EVIDENCE_FIELDS')
        d,a=v['data'],v['attestation'];require(set(a)=={'issuer','kid','iat','exp','sig'},'EVIDENCE_FIELDS')
        e=self.actors['E'];require(a['issuer']==e.name and a['kid']==e.kid,'WRONG_SOURCE')
        self._credential(c,'E','SOURCE','SOURCE')
        require(0<int(a['exp'])-int(a['iat'])<=300 and int(a['iat'])<=at<int(a['exp']),'EXPIRED')
        observed=int(d['sampled_at'] if self.profile=='IND-DEMO-1' else d['event_at'])
        require(observed<=int(d['known_at'])<=int(a['iat']) and int(a['exp'])<=observed+300,'EVIDENCE_TIME')
        if self.profile=='IND-DEMO-1':require(d['quality_flag']=='VALID' and d['label'] in MAPPING,'CLAIM_FALSE')
        else:require(d['record_status']=='AVAILABLE' and d['completeness']=='COMPLETE' and d['template_label'] in TEMPLATES,'CLAIM_FALSE')
        to_sign={k:a[k] for k in ('issuer','kid','iat','exp')}
        strict_verify(e.pub,raw(a['sig'],64),canonical(['ZJJ-SOURCE-v1','2.6',self.profile,kind,self.scope,d,to_sign]))
        return True
    def import_evidence(self,record,scene_key,at=101):
        # E signed source + atomic W publication; not allowed to bypass by giving an unsigned Ref.
        with self.tx() as c:
            self.verify_evidence(c,record,at)
            scene=self._scene_current(c,scene_key);row=_clone(scene['record']['value']);d=record['value']['data']
            require(row['state']=='READY','SCENE_NOT_READY')
            if self.profile=='IND-DEMO-1':
                require([d['line_id'],d['unit_id']]==scene_key[-2:] and d['inspection_cycle']==row['inspection_cycle']
                        and d['phase']==row['phase'] and d['unit_ref']==row['unit_ref'],'BINDING')
            else:
                require([d['synthetic_patient_id'],d['encounter_id']]==scene_key[-2:] and d['encounter_ref']==row['encounter_ref'],'BINDING')
            ref=rec_ref(record)
            require(row['evidence_ref']!=ref,'REPLAY')
            row['evidence_ref']=ref
            self._scene_update(c,scene_key,scene['revision'],row)
            key=scene_key
            cur=c.execute('SELECT revision FROM current_row WHERE namespace=? AND key=?',('EVIDENCE',_json(key))).fetchone()
            rev=1 if cur is None else cur['revision']+1
            c.execute('INSERT INTO current_row VALUES(?,?,?,?,?,1) ON CONFLICT(namespace,key) DO UPDATE SET revision=excluded.revision,ref=excluded.ref,record=excluded.record,active=1',
                      ('EVIDENCE',_json(key),rev,ref,_json(record)))
            c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)',('E',_rowkey('EVIDENCE',key),_json(record)))
        return ref
    def _depend(self,c,ns,key):
        r=self.current(c,ns,key)
        return {'namespace':ns,'key':key,'revision':str(r['revision']),'ref':r['ref']}
    def _deps(self,c,action,task_id,scene_key,roles):
        d=[];prefix=self.scope_key()
        # The private EVIDENCE lookup is NOT a wire dependency namespace.
        # Source currentness is covered by the signed UNIT/ENCOUNTER row revision/ref,
        # which changes atomically on every accepted/replaced source evidence.
        for ns,key in [('POLICY',prefix),('TASK',prefix+[task_id]),(PROFILES[self.profile][2],scene_key),('BEHAVIOR',prefix+[action['principal']])]:
            d.append(self._depend(c,ns,key))
        for alias,role in roles:
            actor=self.actors[alias]
            d.append(self._depend(c,'KEY',[actor.kid]));d.append(self._depend(c,'ROLE',self.role_key(actor,role)))
        return sortset({(x['namespace'],tuple(x['key'])):x for x in d}.values())
    def _bound(self,c,action,task_id,scene_key,at=102):
        require(set(action)=={'scope','operation_id','principal','holder','holder_kid','executor','tool','tool_version','destination','payload'},'ACTION_FIELDS')
        require(action['scope']==self.scope and set(action['payload'])==ACTION_FIELDS[self.profile],'BINDING')
        p=action['payload'];pol=self.current(c,'POLICY',self.scope_key())['record']['value']
        task=self.current(c,'TASK',self.scope_key()+[task_id])['record']['value']
        s=self._scene_current(c,scene_key);sr=s['record']['value'];ev=self.current(c,'EVIDENCE',scene_key)['record']
        identity_key=(self.scope_key()+[p['unit_id']] if self.profile=='IND-DEMO-1'
                      else self.scope_key()+[p['synthetic_patient_id'],p['encounter_id']])
        ident=self.current(c,'IDENTITY',identity_key)
        require(rec_ref(ident['record'])==sr['unit_ref' if self.profile=='IND-DEMO-1' else 'encounter_ref'],'IDENTITY_BINDING')
        if self.profile=='IND-DEMO-1':
            package=self.current(c,'PACKAGE',self.scope_key())
            require(pol['decision_package_ref']==package['ref'],'PACKAGE_BINDING')
            pkg=package['record']['value']
            require(pkg['package_id']=='ind-fixed-package-1' and pkg['detector']=='SYNTHETIC-LABEL-1' and
                    pkg['preprocessing']=='IDENTITY-1' and pkg['output_schema']=='IND-LABEL-V1' and
                    pkg['mapper']=='IND-ROUTE-V1' and pkg['label_routes']=={'normal':'RELEASE','defect':'QUARANTINE','uncertain':'INSPECT'},'PACKAGE_BINDING')
        self.verify_evidence(c,ev,at)
        ed=ev['value']['data']
        require(sr['state']=='READY' and sr['evidence_ref']==rec_ref(ev),'STALE')
        require(action['holder']==task['holder']==self.actors['H'].name and action['holder_kid']==task['holder_kid']==self.actors['H'].kid,'WRONG_HOLDER')
        require(action['principal']==task['principal'] and action['executor']==task['executor']==pol['executor']==self.actors['X'].name,'BINDING')
        require(action['tool']==pol['tool']==task['tool'] and action['tool_version']==pol['tool_version']==task['tool_version']=='1','BINDING')
        require(task['policy_ref']==self.current(c,'POLICY',self.scope_key())['ref'],'STALE')
        require(int(task['iat'])<=at<int(task['exp']) and int(pol['iat'])<=at<int(pol['exp']),'EXPIRED')
        require(pol['gateway_kid']==self.actors['G'].kid and pol['executor_kid']==self.actors['X'].kid,'KEY_BINDING')
        require(pol['gateway']==self.actors['G'].name and pol['source']==self.actors['E'].name,'BINDING')
        for alias in ('H','G','X','U')+ (('V',) if (self.profile=='MED-DEMO-1' or (self.profile=='IND-DEMO-1' and action['payload'].get('route')=='INSPECT')) else ()): 
            role=ROLES[self.profile][alias]
            # All required subjects are distinct; never compare only kid.
            purpose={'H':'CommitProof','G':'Permit','X':'Acceptance','U':'Authorization','V':'Review'}[alias]
            self._credential(c,alias,role,purpose,action)
            self._read_permission(c,alias,action,pol)
        require(len({self.actors[x].name for x in ('G','X','U','V')})==4,'SUBJECT_SEPARATION')
        if self.profile=='IND-DEMO-1':
            require(p['line_id']==task['line_id']==pol['line_id']==ed['line_id']=='demo-line-a' and
                    p['station_id']==task['station_id']==pol['station_id']==ed['station_id']=='demo-check-1','BINDING')
            require([p['line_id'],p['unit_id']]==scene_key[-2:] and p['unit_id']==ed['unit_id'] and p['batch_id']==ed['batch_id'],'BINDING')
            require(p['inspection_cycle']==ed['inspection_cycle']==sr['inspection_cycle'] and p['phase']==ed['phase']==sr['phase'],'BINDING')
            require(p['route']==MAPPING[ed['label']] and p['route'] in task['allowed_routes'] and
                    action['destination']==DEST[p['route']],'CLAIM_FALSE')
            allowed={'unit_ref':sr['unit_ref'],'unit_id':p['unit_id'],'batch_id':p['batch_id'],
                     'inspection_cycle':p['inspection_cycle'],'phase':p['phase']}
            require(allowed in task['allowed_units'],'BINDING')
            required=['QUALITY_REVIEW'] if p['route']=='INSPECT' else []
        else:
            require(p['synthetic_patient_id']==task['synthetic_patient_id']==ed['synthetic_patient_id'] and
                    p['encounter_id']==task['encounter_id']==ed['encounter_id'] and p['order_group_id']==task['order_group_id']==sr['order_group_id'],'BINDING')
            require(p['record_ref']==rec_ref(ev) and task['encounter_ref']==ed['encounter_ref']==sr['encounter_ref'],'BINDING')
            require(p['phase']==task['phase']=='SUBMIT' and p['template_id']==TEMPLATES[ed['template_label']] and
                    p['template_id'] in task['allowed_templates'],'CLAIM_FALSE')
            require(action['destination']==pol['destination']==task['destination']==p['destination_system']=='med-demo-ledger','BINDING')
            required=['CLINICAL_REVIEW']
        roles=[(a,ROLES[self.profile][a]) for a in ('H','E','G','X','U')]
        if required:roles.append(('V',ROLES[self.profile]['V']))
        # R2 requires READER roles for anyone who accesses patient/unit data.
        roles.extend((a,'READER') for a in ('H','G','X','U')+ (('V',) if required else ()))
        return pol,task,ev,s,required,self._deps(c,action,task_id,scene_key,roles)
    def prepare(self,action,task_id,scene_key,at=102):
        with self.db() as c:
            pol,task,ev,scene,required,deps=self._bound(c,action,task_id,scene_key,at)
        policy_ref=self.current_record('POLICY',self.scope_key())
        task_rec=self.current_record('TASK',self.scope_key()+[task_id])
        pref=rec_ref(policy_ref);tr=rec_ref(task_rec);er=rec_ref(ev);ah=action_hash(self.profile,action)
        d=ev['value']['data']
        av={'scope':self.scope,'operation_id':action['operation_id'],'action_hash':ah,
            'policy_ref':pref,'task_ref':tr,'evidence_refs':[er],
            'cutoff':str(at),'history_mode':'DISABLED','result':'MATCH','required_reviews':required,
            'iat':str(at),'exp':'220'}
        if self.profile=='IND-DEMO-1':
            av.update({'decision_package_ref':pol['decision_package_ref'],'method':'ind-fixed-v1','label':d['label'],
                       'proposed_route':action['payload']['route']})
        else:
            av.update({'method':'med-fixed-v1','template_label':d['template_label'],
                       'proposed_template':action['payload']['template_id']})
        assessment=_rec(self.profile,'ASSESSMENT',self.scope,av)
        basis=_rec(self.profile,'BASIS',self.scope,{'scope':self.scope,'operation_id':action['operation_id'],
         'action':action,'action_hash':ah,'policy_ref':pref,'task_ref':tr,'evidence_refs':[er],
         'assessment_ref':rec_ref(assessment),'required_reviews':required,
         'deps':deps,'iat':str(at),'exp':'220'})
        ctx={'scope':self.scope,'operation_id':action['operation_id'],'principal':action['principal'],
             'holder':action['holder'],'holder_kid':action['holder_kid'],'executor':action['executor'],
             'action_hash':ah,'policy_ref':pref,'basis_ref':rec_ref(basis)}
        return {'action':action,'task_id':task_id,'scene_key':scene_key,'assessment':assessment,
                'basis':basis,'ctx':ctx,'deps':deps,'required':required,'at':at,
                'reviews':[],'authorization':None,'permit':None,'issue':None,'challenge_request':None,
                'challenge':None,'proof':None,'acceptance':None,'commit_record':None}
    def _env(self,alias,kind,payload,refs=(),deps=(),aud=('H','G','X'),at=103,nonce=1,ttl=None):
        who=self.actors[alias]
        msg=who.sign(self.profile,kind,self.scope,payload,refs=refs,deps=deps,
                     aud=[self.actors[a].name for a in aud],at=at,iid=sid(at*1000+nonce),ttl=ttl)
        envelope(msg,{who.kid:who},now=at)
        return msg
    def _fresh(self,c,op,at):
        pol,task,ev,scene,required,deps=self._bound(c,op['action'],op['task_id'],op['scene_key'],at)
        require(required==op['required'] and deps==op['deps'],'STALE')
        require(op['ctx']['basis_ref']==rec_ref(op['basis']) and
                op['basis']['value']['assessment_ref']==rec_ref(op['assessment']),'BINDING')
        require(op['basis']['value']['deps']==deps,'DEP_CONFLICT')
        for purpose in required:
            require(not c.execute('SELECT 1 FROM deny WHERE basis_ref=? AND purpose=?',(op['ctx']['basis_ref'],purpose)).fetchone(),'REVIEW_DENY')
        return scene
    def review(self,op,purpose=None,verdict='APPROVE'):
        use=purpose or (op['required'][0] if op['required'] else 'QUALITY_REVIEW')
        with self.db() as c:self._credential(c,'V',ROLES[self.profile]['V'],'Review',op['action'])
        env=self._env('V','Review',{'ctx':op['ctx'],'purpose':use,'verdict':verdict,'reason':'scene checked'},
                      deps=op['deps'],at=103,nonce=1,ttl=117)
        if verdict=='DENY':
            with self.tx() as c:c.execute('INSERT INTO deny VALUES(?,?,?)',(op['ctx']['basis_ref'],use,digest(env)))
        else:op['reviews'].append(env)
        return env
    def authorize(self,op):
        require(sorted(x['body']['payload']['purpose'] for x in op['reviews'])==sorted(op['required']),'REVIEW_PURPOSE')
        refs=sortset([digest(['ZJJ-OBJ-v1',r['protected'],r['body']]) for r in op['reviews']])
        op['authorization']=self._env('U','Authorization',{'ctx':op['ctx'],'review_refs':refs,
                            'purpose':'EXECUTE','verdict':'APPROVE'},refs=refs,deps=op['deps'],at=103,nonce=2,ttl=117)
        return op['authorization']
    def issue(self,op):
        require(op['authorization'] is not None,'MISSING_AUTH')
        with self.db() as c:self._fresh(c,op,104)
        refs=sortset([digest(['ZJJ-OBJ-v1',r['protected'],r['body']]) for r in op['reviews']]); ar=digest(['ZJJ-OBJ-v1',op['authorization']['protected'],op['authorization']['body']])
        op['issue']=self._env('H','IssueRequest',{'ctx':op['ctx'],'review_refs':refs,'authorization_ref':ar},refs=refs+[ar],deps=op['deps'],aud=('G',),at=104,nonce=3,ttl=116)
        op['permit']=self._env('G','Permit',{'ctx':op['ctx'],'review_refs':refs,'authorization_ref':ar,'max_uses':'1','dispatch_before':'220'},
                         refs=refs+[ar],deps=op['deps'],aud=('H','X'),at=104,nonce=4,ttl=116)
        return op['permit']
    def challenge(self,op):
        pref=digest(['ZJJ-OBJ-v1',op['permit']['protected'],op['permit']['body']]);rid=sid(705)
        op['challenge_request']=self._env('H','ChallengeRequest',{'purpose':'COMMIT','operation_id':op['action']['operation_id'],
               'permit_ref':pref,'action_hash':op['ctx']['action_hash'],'attempt_id':rid},refs=[pref],aud=('X',),at=105,nonce=5)
        qr=digest(['ZJJ-OBJ-v1',op['challenge_request']['protected'],op['challenge_request']['body']])
        op['challenge']=self._env('X','Challenge',{'purpose':'COMMIT','operation_id':op['action']['operation_id'],
               'permit_ref':pref,'action_hash':op['ctx']['action_hash'],'holder':op['action']['holder'],
               'holder_kid':op['action']['holder_kid'],'session_id':sid(706),
               'nonce':digest(['scene-challenge',op['action']['operation_id']]),'request_ref':qr},
               refs=[pref,qr],aud=('H',),at=105,nonce=6)
        return op['challenge']
    def proof(self,op):
        ch=op['challenge']['body']['payload'];pref=digest(['ZJJ-OBJ-v1',op['permit']['protected'],op['permit']['body']]);
        cref=digest(['ZJJ-OBJ-v1',op['challenge']['protected'],op['challenge']['body']])
        op['proof']=self._env('H','CommitProof',{'ctx':op['ctx'],'permit_ref':pref,'challenge_ref':cref,
              'session_id':ch['session_id'],'nonce':ch['nonce'],'attempt_id':sid(705)},
              refs=[pref,cref],aud=('X',),at=106,nonce=7,ttl=29)
        return op['proof']
    def _verify_signed_chain(self,c,op,now=106):
        """Independent binding check; a valid Ed25519 signature alone is not approval."""
        msglist=[('H','IssueRequest',op['issue']),('G','Permit',op['permit']),
                 ('H','ChallengeRequest',op['challenge_request']),('X','Challenge',op['challenge']),
                 ('H','CommitProof',op['proof']),('U','Authorization',op['authorization'])]
        msglist.extend(('V','Review',r) for r in op['reviews'])
        for alias,typ,env in msglist:
            require(env is not None,'MISSING_OBJECT')
            who=self.actors[alias]
            envelope(env,{who.kid:who},now=now)
            require(env['protected']['type']==typ and env['protected']['issuer']==who.name,'BINDING')
            require(env['body']['scope']==self.scope,'WRONG_SCOPE')
            self._credential(c,alias,ROLES[self.profile][alias],typ,op['action'])
        ctx=op['ctx'];ref=lambda env:digest(['ZJJ-OBJ-v1',env['protected'],env['body']])
        rp=sortset([ref(r) for r in op['reviews']]);ar=ref(op['authorization']);pref=ref(op['permit'])
        chref=ref(op['challenge']);qrref=ref(op['challenge_request'])
        require(len(rp)==len(op['required']) and
                sorted(r['body']['payload']['purpose'] for r in op['reviews'])==sorted(op['required']),'REVIEW_REQUIRED')
        for r in op['reviews']:
            q=r['body']['payload']
            require(q['ctx']==ctx and q['verdict']=='APPROVE' and q['purpose'] in op['required'],'REVIEW_DENY')
        auth=op['authorization']['body']['payload']
        require(auth=={'ctx':ctx,'review_refs':rp,'purpose':'EXECUTE','verdict':'APPROVE'},'AUTH_DENY')
        require(op['issue']['body']['payload']=={'ctx':ctx,'review_refs':rp,'authorization_ref':ar},'BINDING')
        permit=op['permit']['body']['payload']
        require(permit=={'ctx':ctx,'review_refs':rp,'authorization_ref':ar,'max_uses':'1','dispatch_before':'220'},'BINDING')
        require(op['permit']['body']['deps']==op['deps'],'DEP_CONFLICT')
        qr=op['challenge_request']['body']['payload'];ch=op['challenge']['body']['payload'];pr=op['proof']['body']['payload']
        require(qr['purpose']=='COMMIT' and qr['operation_id']==ctx['operation_id'] and
                qr['permit_ref']==pref and qr['action_hash']==ctx['action_hash'],'BINDING')
        require(ch['purpose']=='COMMIT' and ch['request_ref']==qrref and ch['operation_id']==ctx['operation_id'] and
                ch['permit_ref']==pref and ch['action_hash']==ctx['action_hash'] and
                ch['holder']==ctx['holder'] and ch['holder_kid']==ctx['holder_kid'],'BINDING')
        require(pr=={'ctx':ctx,'permit_ref':pref,'challenge_ref':chref,'session_id':ch['session_id'],
                     'nonce':ch['nonce'],'attempt_id':qr['attempt_id']},'BINDING')
        return True

    def accept(self,op,crash_at=None):
        """Freeze exact 21-field COMMIT and signed Acceptance in one SQLite tx.

        Key signing occurs before COMMIT. A failure rolls back both bytes and
        all W state. This models a durable signer, NOT hardware remote KMS.
        """
        require(op['proof'] is not None and op['permit'] is not None,'MISSING_PROOF')
        for alias,msg in [('H',op['proof']),('G',op['permit']),('X',op['challenge']),
                          ('H',op['issue']),('U',op['authorization'])]:
            envelope(msg,{self.actors[alias].kid:self.actors[alias]},now=106)
        for rev in op['reviews']:
            envelope(rev,{self.actors['V'].kid:self.actors['V']},now=106)
        require(sorted(r['body']['payload']['purpose'] for r in op['reviews'])==sorted(op['required']),'REVIEW_PURPOSE')
        require(op['permit']['body']['deps']==op['deps'],'DEP_CONFLICT')
        with self.tx() as c:
            prev=c.execute('SELECT accepted_blob FROM accept_intent WHERE operation_id=?',(op['action']['operation_id'],)).fetchone()
            if prev:
                saved=json.loads(prev['accepted_blob'])
                proofref=digest(['ZJJ-OBJ-v1',op['proof']['protected'],op['proof']['body']])
                require(saved['commit_record']['value']['proof_ref']==proofref and saved['commit_record']['value']['action']==op['action'],'REPLAY')
                acceptance=saved['acceptance']
                envelope(acceptance,{self.actors['X'].kid:self.actors['X']},now=106)
                op['commit_record']=saved['commit_record'];op['acceptance']=acceptance
                return acceptance
            self._verify_signed_chain(c,op)
            scene=self._fresh(c,op,106);act=op['action'];p=act['payload'];dest=act['destination'];task=op['task_id']
            intent=_json([self.profile,self.scope,p['line_id'],p['unit_id'],p['inspection_cycle']] if self.profile=='IND-DEMO-1'
                         else [self.profile,self.scope,p['synthetic_patient_id'],p['encounter_id']])
            old=c.execute('SELECT operation_id FROM accept_intent WHERE intent=?',(intent,)).fetchone()
            require(old is None,'DUPLICATE_INTENT')
            require(c.execute('SELECT 1 FROM flight WHERE task_id=?',(task,)).fetchone() is None,'TASK_BUSY')
            c.execute('INSERT OR IGNORE INTO resource(destination) VALUES(?)',(dest,))
            res=c.execute('SELECT * FROM resource WHERE destination=?',(dest,)).fetchone()
            require(res['reserved']+res['spent']+1<=res['capacity'],'RESOURCE_LIMIT')
            bh=c.execute('SELECT * FROM behavior WHERE principal=?',(act['principal'],)).fetchone()
            require(bh is not None and bh['accepted_count']<bh['count_cap'],'BEHAVIOR_LIMIT')
            bev=self.current(c,'BEHAVIOR',self.scope_key()+[act['principal']])
            require(bev['revision']==bh['revision'] and int(bev['record']['value']['accepted_count'])==bh['accepted_count'],'BEHAVIOR_INTEGRITY')
            oid=act['operation_id'];before_scene=self._scene_witness(op['scene_key'],scene)
            row=_clone(scene['record']['value']);row['state']='ACCEPTED';row['operation_id']=oid
            afterref=self._scene_update(c,op['scene_key'],scene['revision'],row)
            if crash_at=='after_scene':__import__('os')._exit(73)
            after_scene={'namespace':PROFILES[self.profile][2],'key':op['scene_key'],
                         'revision':str(scene['revision']+1),'ref':afterref,'row':row}
            before_behavior=self._behavior_witness(act['principal'],bev)
            next_inflight=sortset(json.loads(bh['inflight'])+[oid])
            behavior_row={'accepted_count':str(bh['accepted_count']+1),'count_cap':'32','inflight':next_inflight}
            bref=self._behavior_update(c,act['principal'],bev['revision'],behavior_row)
            after_behavior={'key':self.scope_key()+[act['principal']], 'revision':str(bev['revision']+1),
                            'ref':bref,'row':behavior_row}
            c.execute('UPDATE behavior SET accepted_count=accepted_count+1,revision=revision+1,inflight=? WHERE principal=?',
                      (_json(next_inflight),act['principal']))
            c.execute('UPDATE resource SET reserved=reserved+1,revision=revision+1 WHERE destination=?',(dest,))
            c.execute('INSERT INTO flight VALUES(?,?)',(task,oid))
            if crash_at=='after_resource':__import__('os')._exit(73)
            seq=c.execute('SELECT COALESCE(MAX(rowid),0)+1 FROM accept_intent').fetchone()[0]
            reservation=sid(800+seq)
            resource_key=(self.scope_key()+['route-capacity',p['line_id'],dest,'unit'] if self.profile=='IND-DEMO-1'
                          else self.scope_key()+['order-capacity',dest,'order'])
            plan={'reservation_id':reservation,'key':resource_key,'unit':'UNIT' if self.profile=='IND-DEMO-1' else 'ORDER',
                  'amount':'1','capacity_before':str(res['capacity']),'reserved_before':str(res['reserved']),
                  'spent_before':str(res['spent']),'reserved_after':str(res['reserved']+1),
                  'spent_after':str(res['spent']),'revision_before':str(res['revision']),
                  'revision_after':str(res['revision']+1)}
            def ref(message):return digest(['ZJJ-OBJ-v1',message['protected'],message['body']])
            pref=ref(op['permit']);proofref=ref(op['proof']);authref=ref(op['authorization'])
            rrs=sortset([ref(r) for r in op['reviews']])
            value={'ctx':op['ctx'],'action':act,'permit_ref':pref,'proof_ref':proofref,'authorization_ref':authref,
                   'review_refs':rrs,'accept_seq':str(seq),'accepted_at':'106','trusted_time':{'lo':'106','hi':'106'},
                   'checked_deps':op['deps'],'reservation_plan':[plan],'reservation_ids':[reservation],
                   'behavior_before':before_behavior,'behavior_after':after_behavior,
                   'taskflight':{'key':self.scope_key()+[task],'operation_id':oid},
                   'dispatch_before':'220','frozen_tool_request':act,
                   'signing_public_key':b64(self.actors['X'].pub),
                   'credential_witnesses':self._credential_witnesses(c,op,seq),
                   'scene_before':before_scene,'scene_after':after_scene}
            commit_record=_rec(self.profile,'COMMIT',self.scope,value)
            require(len(value)==21 and rec_ref(commit_record),'COMMIT_STRUCTURE')
            acceptance=self._env('X','Acceptance',{'ctx':op['ctx'],'permit_ref':pref,'proof_ref':proofref,
                'authorization_ref':authref,'review_refs':rrs,'accept_seq':str(seq),'accepted_at':'106',
                'commit_record_ref':rec_ref(commit_record),'dispatch_before':'220'},
                refs=sortset([pref,proofref,authref]+rrs),aud=('H','G','U'),at=106,nonce=8)
            freeze={'action':act,'pre_deps':op['deps'],'scene_after_ref':afterref,'scene_after_revision':scene['revision']+1,
                    'behavior_after':after_behavior,'task_id':task,'commit_record':commit_record,'acceptance':acceptance}
            if crash_at=='before_archive':__import__('os')._exit(73)
            c.execute('INSERT INTO accept_intent(intent,operation_id,scene_namespace,scene_key,accepted_blob) VALUES(?,?,?,?,?)',
                      (intent,oid,PROFILES[self.profile][2],_json(op['scene_key']),_json(freeze)))
            c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)',('ACCEPT',intent,_json(freeze)))
        op['commit_record']=commit_record;op['acceptance']=acceptance
        return acceptance

    def claim(self,op):
        oid=op['action']['operation_id']
        with self.tx() as c:
            record=c.execute('SELECT * FROM accept_intent WHERE operation_id=?',(oid,)).fetchone()
            require(record is not None,'NOT_ACCEPTED')
            if record['calls']:
                require(record['calls']==1,'NO_REDISPATCH');return 'EXISTING'
            info=json.loads(record['accepted_blob']);ns=PROFILES[self.profile][2];scene=self._scene_current(c,op['scene_key'])
            require(scene['revision']==info['scene_after_revision'] and scene['ref']==info['scene_after_ref'] and
                    scene['record']['value']['operation_id']==oid and scene['record']['value']['state']=='ACCEPTED','STALE_SCENE')
            for dep in info['pre_deps']:
                if dep['namespace'] in (ns,'BEHAVIOR'):continue   # frozen own acceptance transitions only
                current=self.current(c,dep['namespace'],dep['key'])
                require(current['revision']==int(dep['revision']) and current['ref']==dep['ref'],'STALE')
            bf=c.execute('SELECT * FROM behavior WHERE principal=?',(op['action']['principal'],)).fetchone()
            require(bf is not None and oid in json.loads(bf['inflight']) and
                    bf['accepted_count']>=int(info['behavior_after']['row']['accepted_count']),'BEHAVIOR_INTEGRITY')
            require(c.execute('SELECT operation_id FROM flight WHERE task_id=?',(info['task_id'],)).fetchone()['operation_id']==oid,'TASK_BUSY')
            rr=c.execute('SELECT * FROM resource WHERE destination=?',(op['action']['destination'],)).fetchone()
            require(rr['reserved']>=1 and rr['reserved']+rr['spent']<=rr['capacity'],'RESOURCE_LIMIT')
            attempt=b64(__import__('hashlib').sha256(canonical(['scene-attempt',oid])).digest()[:16])
            c.execute('UPDATE accept_intent SET calls=1,attempt=?,state=? WHERE operation_id=?',(attempt,'EFFECT_UNKNOWN',oid))
        return attempt
    def snapshot(self):
        with self.db() as c:
            records=c.execute('SELECT * FROM accept_intent').fetchall()
            res=c.execute('SELECT * FROM resource').fetchall()
            return {'accepts':len(records),'calls':sum(x['calls'] for x in records),
                    'settlements':sum(x['settlements'] for x in records),
                    'reserved':sum(x['reserved'] for x in res),'spent':sum(x['spent'] for x in res)}
