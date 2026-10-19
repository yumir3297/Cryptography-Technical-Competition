"""Single-host common W. SQLite commits precede receipt signing or tool I/O.

No remote tool is atomic with W. A persisted EXEC-0 consumption can therefore
remain unknown forever; recovery authenticates queries of that same attempt.
"""
from competition.support.schema import COMPETITION_PROTO
import copy
import json
import os
import threading
import time
from jsonschema import Draft202012Validator
from competition.core.trusted_state import enc, prefix, ROLES, PROFILE_SCOPES
from competition.core.w_state import WState
from competition.core.authorization import CommonGuard
from competition.core.event_clock import require_window, refresh_event_age
from competition.profiles.w_plans import TransactionPlans
from competition.support.wire import require, ProtocolError, canonical, b64, raw, digest, rec_ref, msgref, sortset, keyid, action_hash, strict_verify, envelope
from competition.support.final_fact import verify_certificate, final_fact_id, final_fact, final_sign_bytes

WORKER_PURPOSES=('AUDIT','CANCEL','CLAIM','EXECUTE','QUERY','RECEIPT','SETTLE')
KNOWN_CANCEL={'EXPIRED','REVOKED','STALE','NO_ROLE','DEP_CONFLICT','REVIEW_DENY','STATE_GENESIS_CHANGED','STATE_CONFLICT','ASSESSMENT_MISMATCH'}

class CommonW:
    def __init__(self,state,delivery_key,worker_certificate,x_signers,tool_gateways):
        require(state.protocol==COMPETITION_PROTO,'W_PROTOCOL_BINDING')
        self.source=state; self.state=WState(state); self.guard=CommonGuard(self.state); self.plans=TransactionPlans(self.state)
        self.delivery_key=delivery_key; self.worker_certificate=worker_certificate; self.x_signers=x_signers; self.tool_gateways=tool_gateways
        self._clock_lock=threading.RLock()
        with state.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS w_meta(id INTEGER PRIMARY KEY CHECK(id=1),accept_seq INTEGER);
            INSERT OR IGNORE INTO w_meta VALUES(1,0);
            CREATE TABLE IF NOT EXISTS w_ticket(profile TEXT,ticket_id TEXT PRIMARY KEY,oid TEXT,request_ref TEXT,op TEXT,expires INTEGER);
            CREATE TABLE IF NOT EXISTS w_operation(profile TEXT,oid TEXT,request_ref TEXT,intent TEXT,frozen TEXT,receipt TEXT,state TEXT,effect_state TEXT,observed_fact TEXT,PRIMARY KEY(profile,oid));
            CREATE TABLE IF NOT EXISTS w_intent(profile TEXT,intent TEXT,oid TEXT,PRIMARY KEY(profile,intent));
            CREATE TABLE IF NOT EXISTS w_consumed(profile TEXT,kind TEXT,ref TEXT,oid TEXT,PRIMARY KEY(profile,kind,ref));
            CREATE TABLE IF NOT EXISTS w_mutable(profile TEXT,namespace TEXT,key TEXT,revision INTEGER,ref TEXT,record TEXT,genesis_revision INTEGER,genesis_ref TEXT,PRIMARY KEY(profile,namespace,key));
            CREATE TABLE IF NOT EXISTS w_resource(profile TEXT,key TEXT,unit TEXT,capacity INTEGER,reserved INTEGER,spent INTEGER,revision INTEGER,certificate TEXT,PRIMARY KEY(profile,key));
            CREATE TABLE IF NOT EXISTS w_reservation(profile TEXT,id TEXT,oid TEXT,key TEXT,amount INTEGER,state TEXT,PRIMARY KEY(profile,id));
            CREATE TABLE IF NOT EXISTS w_flight(profile TEXT,key TEXT,oid TEXT,active INTEGER,PRIMARY KEY(profile,oid));
            CREATE TABLE IF NOT EXISTS w_outbox(profile TEXT,oid TEXT,state TEXT,attempt_id TEXT,packet TEXT,exec_marker INTEGER,send_observed INTEGER,queries INTEGER,PRIMARY KEY(profile,oid),UNIQUE(profile,attempt_id));
            CREATE TABLE IF NOT EXISTS w_nonce(profile TEXT,nonce TEXT PRIMARY KEY,oid TEXT,purpose TEXT,anchor TEXT,expires INTEGER,used INTEGER);
            CREATE TABLE IF NOT EXISTS w_tool(profile TEXT,key TEXT,certificate TEXT,origin TEXT,high_water INTEGER,head TEXT,halted INTEGER,PRIMARY KEY(profile,key));
            CREATE TABLE IF NOT EXISTS w_settlement(profile TEXT,oid TEXT,fact_id TEXT,ledger TEXT,final_seq TEXT,effect_id TEXT,outcome TEXT,evidence TEXT,PRIMARY KEY(profile,oid),UNIQUE(profile,ledger,final_seq));
            CREATE UNIQUE INDEX IF NOT EXISTS w_effect_once ON w_settlement(profile,ledger,effect_id) WHERE effect_id!='';
            CREATE TABLE IF NOT EXISTS w_evidence(seq INTEGER PRIMARY KEY AUTOINCREMENT,profile TEXT,oid TEXT,kind TEXT,blob TEXT);
            ''')
            saved=c.execute("SELECT blob FROM a_journal WHERE kind='W_BOOTSTRAP' ORDER BY seq LIMIT 1").fetchone()
            boot={'protocol':COMPETITION_PROTO,'worker':worker_certificate,'delivery_public':b64(delivery_key.public_key().public_bytes_raw())}
            if saved:require(json.loads(saved[0])==boot,'W_BOOTSTRAP_CONFLICT')
            else:
                self._worker_grant(None)
                self._journal(c,'W_BOOTSTRAP','', '',boot)
                self.source.observe(c,'W_BOOTSTRAP','','',{'stage':'W 启动（固定 worker/delivery）','lanes':['W'],'detail':{'purpose':'BOOTSTRAP'}})

    def _event(self,c,p,oid,stage,ref):
        with self._clock_lock:return self.source.event(c,p,oid,stage,ref)
    @staticmethod
    def _end_event(event):
        """Rebound the interval after crypto/Schema work, at the logical gate."""
        return refresh_event_age(event)
    def _current_windows(self,c,p,op,event,*,accept=False):
        messages=op['reviews']+[op['authorization'],op['permit']]
        if accept:messages+= [op['issue'],op['challenge_request'],op['challenge'],op['proof']]
        windows=[m['body'] for m in messages]+[op[name]['value'] for name in ('basis','assessment')]
        for dep in op['deps']:
            row=self.source.current(c,p,dep['namespace'],dep['key'])
            value=row['record']['value']
            if 'iat' in value and 'exp' in value:windows.append(value)
        for alias,purpose in [('H','CommitProof'),('G','Permit'),('X','Acceptance'),('U','Authorization'),('E','SOURCE')]+([('V','Review')] if op['required'] else []):
            pair=self.source.credential(c,p,alias,ROLES[p][alias],purpose,op['action'],event)
            windows.extend(row['record']['value'] for row in pair)
        event=self._end_event(event)
        for value in windows:require_window(value,event)
        return event
    @staticmethod
    def _journal(c,kind,p,oid,blob):
        return c.execute('INSERT INTO a_journal(kind,profile,operation_id,blob) VALUES(?,?,?,?)',(kind,p,oid,enc(blob))).lastrowid
    def _worker_grant(self,event):
        cert=self.worker_certificate; require(type(cert) is dict and set(cert)=={'claim','signature'},'WORKER_GRANT')
        cl=cert['claim'];strict_verify(self.source.root_public,raw(cert['signature'],64),canonical(['COMP-W-WORKER-GRANT-v1',cl]))
        require(set(cl)=={'subject','kid','public_key','profiles','scopes','purposes','iat','exp','revision','active'} and cl['active'] is True and cl['revision']=='1' and cl['purposes']==list(WORKER_PURPOSES),'WORKER_GRANT')
        require(cl['kid']==keyid(raw(cl['public_key'],32)) and set(cl['profiles'])==set(self.source.actors) and cl['scopes']==[PROFILE_SCOPES[p] for p in cl['profiles']],'WORKER_GRANT')
        if event:require_window(cl,event)
        return cl
    def register_resource(self,cert):
        cl=cert['claim'];strict_verify(self.source.root_public,raw(cert['signature'],64),canonical(['COMP-W-RESOURCE-v1',cl]))
        require(set(cl)=={'profile','scope','key','unit','capacity','revision','active'} and cl['profile'] in PROFILE_SCOPES and cl['scope']==PROFILE_SCOPES[cl['profile']] and cl['revision']=='1' and cl['active'] is True and type(cl['capacity']) is str and cl['capacity'].isdigit() and int(cl['capacity'])>0,'RESOURCE_CERTIFICATE')
        require(type(cl['key']) is list and cl['key'][:3]==prefix(cl['profile']) and cl['unit'] in ('UNIT','ORDER','CNY_MINOR'),'RESOURCE_SCOPE')
        with self.source.tx() as c:
            old=c.execute('SELECT certificate FROM w_resource WHERE profile=? AND key=?',(cl['profile'],enc(cl['key']))).fetchone()
            if old:require(json.loads(old[0])==cert,'RESOURCE_ALREADY_INITIALIZED');return
            c.execute('INSERT INTO w_resource VALUES(?,?,?,?,0,0,1,?)',(cl['profile'],enc(cl['key']),cl['unit'],int(cl['capacity']),enc(cert)))
            self._journal(c,'W_RESOURCE',cl['profile'],'',cert)
            self.source.observe(c,'W_RESOURCE',cl['profile'],'',{'stage':'资源登记','lanes':['W'],'detail':{'unit':cl['unit'],'capacity':cl['capacity']}})
    def register_tool(self,p,cert):
        record=verify_certificate(cert,self.source.root_public,p);self.source.schemas[p].validate(record,'Record_TOOL_TRUST');require(record['scope']==PROFILE_SCOPES[p],'TOOL_SCOPE')
        v=record['value'];key=enc([v[k] for k in ('tool','tool_version','destination')])
        with self.source.tx() as c:
            old=c.execute('SELECT certificate FROM w_tool WHERE profile=? AND key=?',(p,key)).fetchone()
            if old:require(json.loads(old[0])==cert,'TOOL_ALREADY_INITIALIZED');return
            c.execute('INSERT INTO w_tool VALUES(?,?,?,?,0,?,0)',(p,key,enc(cert),cert['claim']['ledger_origin'],cert['claim']['ledger_head']))
            self._journal(c,'W_TOOL',p,'',cert)
            self.source.observe(c,'W_TOOL',p,'',{'stage':'工具信任登记','lanes':['W'],'detail':{'ledger_origin':cert['claim']['ledger_origin']}})
    def _tool(self,c,p,action,event):
        key=enc([action[k] for k in ('tool','tool_version','destination')]);row=c.execute('SELECT * FROM w_tool WHERE profile=? AND key=?',(p,key)).fetchone()
        require(row is not None,'TOOL_TRUST_UNKNOWN');require(not row['halted'],'TRUSTED_CONTRADICTION')
        cert=json.loads(row['certificate']);r=verify_certificate(cert,self.source.root_public,p);require(r['scope']==PROFILE_SCOPES[p] and row['origin']==cert['claim']['ledger_origin'],'TOOL_BINDING');require_window(r['value'],event)
        require(key==enc([r['value'][k] for k in ('tool','tool_version','destination')]),'TOOL_BINDING')
        return row,r
    def _resource(self,c,p,key):
        row=c.execute('SELECT * FROM w_resource WHERE profile=? AND key=?',(p,enc(key))).fetchone();require(row is not None,'RESOURCE_UNKNOWN')
        cert=json.loads(row['certificate']);cl=cert['claim'];strict_verify(self.source.root_public,raw(cert['signature'],64),canonical(['COMP-W-RESOURCE-v1',cl]))
        require(cl['profile']==p and cl['scope']==PROFILE_SCOPES[p] and cl['key']==key and cl['unit']==row['unit'] and int(cl['capacity'])==row['capacity'] and cl['active'] is True,'RESOURCE_INTEGRITY')
        totals=c.execute("SELECT COALESCE(SUM(CASE WHEN state='RESERVED' THEN amount ELSE 0 END),0),COALESCE(SUM(CASE WHEN state='SPENT' THEN amount ELSE 0 END),0) FROM w_reservation WHERE profile=? AND key=?",(p,enc(key))).fetchone()
        require(tuple(totals)==(row['reserved'],row['spent']) and 0<=row['reserved']+row['spent']<=row['capacity'],'RESOURCE_INTEGRITY')
        return row
    def _operation(self,c,p,oid):
        require(p in PROFILE_SCOPES,'PROFILE_REGISTRY');row=c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone();require(row is not None,'OPERATION_UNKNOWN')
        return row,json.loads(row['frozen'])
    @staticmethod
    def _view(row):
        return {'profile':row['profile'],'operation_id':row['oid'],'acceptance_state':'COMMITTED','dispatch_state':row['state'],'effect_state':row['effect_state'],'acceptance':json.loads(row['receipt']) if row['receipt'] else None,'receipt_state':'SIGNED' if row['receipt'] else 'PENDING'}
    def prepare(self,p,op,identity):
        oid=op['action']['operation_id'];ref=digest(['COMP-APP-CALL-v1',p,op])
        with self.source.tx() as c:
            event=self._event(c,p,oid,'PREPARE',ref);self.source.authenticate(c,p,op,identity,'GUARD',event)
            old=c.execute('SELECT request_ref FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone()
            if old:require(old[0]==ref,'ID_CONFLICT')
            else:self.guard.verify(c,p,op,event)
            ticket=b64(os.urandom(16));c.execute('INSERT INTO w_ticket VALUES(?,?,?,?,?,?)',(p,ticket,oid,ref,enc(op),event['lo']+30))
            self.source.observe(c,'PREPARED',p,oid,{'stage':'签发准备凭据（ticket）','lanes':['受信编排器'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'refs':{'request_ref':ref}})
            return {'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':oid,'ticket_id':ticket,'request_ref':ref,'time_witness':event,'expires':str(event['lo']+30)}
    def challenge_accept(self,p,ticket):
        with self.source.tx() as c:
            row=c.execute('SELECT * FROM w_ticket WHERE profile=? AND ticket_id=?',(p,ticket)).fetchone();require(row is not None,'TICKET_UNKNOWN')
            event=self._event(c,p,row['oid'],'ACCEPT_GUARD',row['request_ref']);nonce=b64(os.urandom(32))
            c.execute('INSERT INTO w_nonce VALUES(?,?,?,?,?,?,0)',(p,nonce,row['oid'],'ACCEPT',ticket,event['lo']+30))
            self.source.observe(c,'CHALLENGE_ISSUED',p,row['oid'],{'stage':'签发接受挑战','lanes':['W'],'refs':{'request_ref':row['request_ref']},'detail':{'purpose':'ACCEPT'}})
            return {'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':row['oid'],'ticket_id':ticket,'nonce':nonce}
    def _accept_auth(self,c,p,ticket,proof,op,event):
        require(type(proof) is dict and set(proof)=={'claim','signature'},'IDENTITY_REQUIRED');cl=proof['claim'];who=self.source.actors[p]['H']
        require(set(cl)=={'profile','scope','operation_id','ticket_id','nonce'} and (cl['profile'],cl['scope'],cl['operation_id'],cl['ticket_id'])==(p,PROFILE_SCOPES[p],op['action']['operation_id'],ticket),'BINDING')
        strict_verify(who.pub,raw(proof['signature'],64),canonical(['COMP-APP-ACCEPT-v1',cl]));self.source.credential(c,p,'H',ROLES[p]['H'],'CommitProof',op['action'],event);self.source.read_permission(c,p,'H',op['action'],event)
        self._consume_nonce(c,p,cl['nonce'],cl['operation_id'],'ACCEPT',ticket,event)
    @staticmethod
    def _consume_nonce(c,p,nonce,oid,purpose,anchor,event):
        n=c.execute('SELECT * FROM w_nonce WHERE nonce=?',(nonce,)).fetchone();require(n is not None and (n['profile'],n['oid'],n['purpose'],n['anchor'],n['used'])==(p,oid,purpose,anchor,0),'REPLAY')
        require_window({'iat':'0','exp':str(n['expires'])},event);c.execute('UPDATE w_nonce SET used=1 WHERE nonce=?',(nonce,))
    def accept(self,p,ticket,proof,*,crash_after_commit=False):
        with self.source.tx() as c:
            t=c.execute('SELECT * FROM w_ticket WHERE profile=? AND ticket_id=?',(p,ticket)).fetchone();require(t is not None,'TICKET_UNKNOWN');op=json.loads(t['op']);oid=t['oid']
            event=self._event(c,p,oid,'ACCEPT_GUARD',t['request_ref']);self._accept_auth(c,p,ticket,proof,op,event)
            old=c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone()
            if old:require(old['request_ref']==t['request_ref'],'ID_CONFLICT')
            else:
                require_window({'iat':'0','exp':str(t['expires'])},event)
                guarded=self.guard.verify(c,p,op,event);seq=c.execute('SELECT accept_seq+1 FROM w_meta WHERE id=1').fetchone()[0]
                plan=self.plans.plan(c,p,op,event,seq)
                self._behavior_integrity(c,p,plan['behavior_before']['key'])
                require(not c.execute('SELECT 1 FROM w_intent WHERE profile=? AND intent=?',(p,enc(plan['intent']))).fetchone(),'INTENT_CONFLICT')
                resource=self._resource(c,p,plan['resource_key']);require(resource['unit']==plan['unit'] and resource['capacity']<=plan['limit'],'RESOURCE_INTEGRITY')
                require(resource['reserved']+resource['spent']+plan['amount']<=resource['capacity'],'RESOURCE_EXHAUSTED')
                task=self.state.current(c,p,'TASK',plan['taskflight']['key'])['record']['value']
                flight_count=c.execute('SELECT COUNT(*) FROM w_flight WHERE profile=? AND key=? AND active=1',(p,enc(plan['taskflight']['key']))).fetchone()[0]
                # Original PAY_TASK has no max_inflight wire field; its one
                # TaskFlight row grants one slot. Scene tasks explicitly say 1.
                require(flight_count<(1 if p=='PAY-1' else int(task['max_inflight'])),'TASK_FLIGHT_LIMIT')
                toolrow,trust=self._tool(c,p,op['action'],event)
                for kind,ref in [('request',msgref(op['issue'])),('permit',msgref(op['permit'])),('proof',msgref(op['proof'])),('session',op['proof']['body']['payload']['session_id']),('nonce',op['proof']['body']['payload']['nonce'])]:
                    require(not c.execute('SELECT 1 FROM w_consumed WHERE profile=? AND kind=? AND ref=?',(p,kind,ref)).fetchone(),'REPLAY')
                    c.execute('INSERT INTO w_consumed VALUES(?,?,?,?)',(p,kind,ref,oid))
                # Refresh after expensive verification. Recheck all windows against this
                # final logical acceptance event, rather than reusing PREPARE time.
                event=self._event(c,p,oid,'ACCEPT_GUARD',t['request_ref']);guarded=self.guard.verify(c,p,op,event)
                rid=b64(os.urandom(16));witness={'reservation_id':rid,'key':plan['resource_key'],'unit':plan['unit'],'amount':str(plan['amount']),'capacity_before':str(resource['capacity']),'reserved_before':str(resource['reserved']),'spent_before':str(resource['spent']),'reserved_after':str(resource['reserved']+plan['amount']),'spent_after':str(resource['spent']),'revision_before':str(resource['revision']),'revision_after':str(resource['revision']+1)}
                credentials=[]
                for alias,purpose in [('H','CommitProof'),('G','Permit'),('X','Acceptance'),('U','Authorization'),('E','SOURCE')]+([('V','Review')] if op['required'] else []):
                    kr,rr=self.source.credential(c,p,alias,ROLES[p][alias],purpose,op['action'],event);who=self.source.actors[p][alias]
                    credentials.append({'subject':who.name,'kid':who.kid,'public_key':b64(who.pub),'key_grant_ref':kr['ref'],'role':ROLES[p][alias],'role_grant_ref':rr['ref'],'key_revision':str(kr['revision']),'role_revision':str(rr['revision']),'verified_at_seq':str(seq)})
                av=op['action'];rr=sortset([msgref(x) for x in op['reviews']]);pr=msgref(op['permit']);fr=msgref(op['proof']);ar=msgref(op['authorization'])
                cv={'ctx':op['ctx'],'action':av,'permit_ref':pr,'proof_ref':fr,'authorization_ref':ar,'review_refs':rr,'accept_seq':str(seq),'accepted_at':str(event['lo']),'trusted_time':{'lo':str(event['lo']),'hi':str(event['hi'])},'checked_deps':guarded['deps'],'reservation_plan':[witness],'reservation_ids':[rid],'behavior_before':plan['behavior_before'],'behavior_after':plan['behavior_after'],'taskflight':plan['taskflight'],'dispatch_before':op['permit']['body']['payload']['dispatch_before'],'frozen_tool_request':av,'signing_public_key':b64(self.source.actors[p]['X'].pub),'credential_witnesses':sortset(credentials)}
                if p!='PAY-1':cv.update(scene_before=plan['scene_before'],scene_after=plan['scene_after'])
                commit={'version':'2.6','profile':p,'kind':'COMMIT','scope':PROFILE_SCOPES[p],'value':cv};self.source.schemas[p].validate(commit,'Record_COMMIT')
                event=self._end_event(event);event=self._current_windows(c,p,op,event,accept=True)
                cv['trusted_time']['hi']=str(event['hi'])
                cref=rec_ref(commit);xp=self.source.actors[p]['X']
                payload={k:cv[k] for k in ('ctx','permit_ref','proof_ref','authorization_ref','review_refs','accept_seq','accepted_at','dispatch_before')};payload['commit_record_ref']=cref
                core={'protected':{'proto':COMPETITION_PROTO,'version':'2.6','profile':p,'alg':'Ed25519','type':'Acceptance','issuer':xp.name,'kid':xp.kid},'body':{'id':b64(os.urandom(16)),'scope':PROFILE_SCOPES[p],'iat':str(event['lo']),'exp':str(event['lo']+900),'aud':sortset([self.source.actors[p][a].name for a in ('H','G','U')]),'refs':sortset(rr+[pr,fr,ar]),'deps':[],'payload':payload}}
                frozen={'op':op,'plan':plan,'commit':commit,'commit_ref':cref,'acceptance_core':core,'accepted_at':event['lo'],'x_public':b64(xp.pub),'x_kid':xp.kid,'time_witness':event,'guard':guarded,'tool_certificate':json.loads(toolrow['certificate'])}
                c.execute('UPDATE w_meta SET accept_seq=? WHERE id=1',(seq,));c.execute('INSERT INTO w_operation VALUES(?,?,?,?,?,NULL,?,?,NULL)',(p,oid,t['request_ref'],enc(plan['intent']),enc(frozen),'PENDING','NO_ATTEMPT'))
                c.execute('INSERT INTO w_intent VALUES(?,?,?)',(p,enc(plan['intent']),oid));c.execute('INSERT INTO w_reservation VALUES(?,?,?,?,?,?)',(p,rid,oid,enc(plan['resource_key']),plan['amount'],'RESERVED'))
                c.execute('UPDATE w_resource SET reserved=reserved+?,revision=revision+1 WHERE profile=? AND key=?',(plan['amount'],p,enc(plan['resource_key'])))
                c.execute('INSERT INTO w_flight VALUES(?,?,?,1)',(p,enc(plan['taskflight']['key']),oid));c.execute('INSERT INTO w_outbox VALUES(?,?,?,NULL,NULL,0,NULL,0)',(p,oid,'PENDING'))
                self._put_witness(c,p,'BEHAVIOR',plan['behavior_after'])
                if plan['scene_after']:self._put_witness(c,p,plan['scene_after']['namespace'],plan['scene_after'])
                self._journal(c,'W_COMMIT',p,oid,frozen)
                self.source.observe(c,'ACCEPT_COMMITTED',p,oid,{'stage':'接受并永久冻结','lanes':['W'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'refs':{'commit_ref':cref,'action_hash':cv['ctx']['action_hash']},'detail':{'accept_seq':str(seq)}})
        # Explicit controlled fault fixture, never sourced from a wire request.
        if crash_after_commit:os._exit(97)
        return self.complete_receipt(p,oid)
    def _put_witness(self,c,p,ns,witness):
        old=self.state.current(c,p,ns,witness['key']);record=copy.deepcopy(old['record']);record['value']=copy.deepcopy(witness['row']);require(self.state.put(c,p,ns,witness['key'],record,int(witness['revision']))==witness['ref'],'STATE_INTEGRITY')
    def complete_receipt(self,p,oid):
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid)
            if row['receipt']:return self._view(row)
            try:
                event=self._event(c,p,oid,'RECEIPT_SIGN_GUARD',frozen['commit_ref']);self.source.credential(c,p,'X',ROLES[p]['X'],'Acceptance',frozen['op']['action'],event);self.source.read_permission(c,p,'X',frozen['op']['action'],event);require_window(frozen['acceptance_core']['body'],event)
                signed=self.x_signers[p].sign(p,oid,frozen['acceptance_core'])
                require({k:v for k,v in signed.items() if k!='sig'}==frozen['acceptance_core'],'FROZEN_RECEIPT_CONFLICT')
                event=self._event(c,p,oid,'RECEIPT_PUBLISH',frozen['commit_ref']);self.source.credential(c,p,'X',ROLES[p]['X'],'Acceptance',frozen['op']['action'],event);require_window(signed['body'],event)
                self.source.schemas[p].validate(signed,'Acceptance');who=self.source.actors[p]['X'];envelope(signed,{who.kid:who},now=event['lo'],proto=COMPETITION_PROTO)
                event=self._end_event(event);require_window(signed['body'],event);self.source.credential(c,p,'X',ROLES[p]['X'],'Acceptance',frozen['op']['action'],event)
                c.execute('UPDATE w_operation SET receipt=? WHERE profile=? AND oid=?',(enc(signed),p,oid));self._journal(c,'W_RECEIPT',p,oid,{'acceptance':signed,'event':event,'signature_generation_observation':{'pid':self.x_signers[p].info['pid'],'wall_ns':self.x_signers[p].last_generated_wall_ns,'rpc_deadline_seconds':'1.5','kind':'LOCAL_PROCESS_OBSERVATION'}})
                self.source.observe(c,'RECEIPT_SIGNED',p,oid,{'stage':'X 已签回执','lanes':['X','W'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'detail':{'receipt_state':'SIGNED'}})
            except (ProtocolError,TimeoutError,OSError) as exc:
                self._journal(c,'W_RECEIPT_PENDING',p,oid,{'reason':getattr(exc,'code',type(exc).__name__)})
                self.source.observe(c,'RECEIPT_PENDING',p,oid,{'stage':'回执待签','lanes':['X','W'],'detail':{'receipt_state':'PENDING','reason':getattr(exc,'code',type(exc).__name__)}})
            return self._view(c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone())
    def challenge_worker(self,p,oid,purpose):
        require(purpose in WORKER_PURPOSES,'WORKER_PURPOSE')
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid);event=self._event(c,p,oid,'WORKER_CHALLENGE',frozen['commit_ref']);self._worker_grant(event);nonce=b64(os.urandom(32))
            c.execute('INSERT INTO w_nonce VALUES(?,?,?,?,?,?,0)',(p,nonce,oid,purpose,frozen['commit_ref'],event['lo']+30))
            self.source.observe(c,'CHALLENGE_ISSUED',p,oid,{'stage':'签发工人挑战','lanes':['W'],'refs':{'commit_ref':frozen['commit_ref']},'detail':{'purpose':purpose}})
            return {'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':oid,'purpose':purpose,'commit_ref':frozen['commit_ref'],'nonce':nonce}
    def _worker(self,c,p,oid,purpose,proof,event,frozen):
        grant=self._worker_grant(event);require(type(proof) is dict and set(proof)=={'claim','signature'},'WORKER_REQUIRED');cl=proof['claim']
        require(set(cl)=={'profile','scope','operation_id','purpose','commit_ref','nonce'} and (cl['profile'],cl['scope'],cl['operation_id'],cl['purpose'],cl['commit_ref'])==(p,PROFILE_SCOPES[p],oid,purpose,frozen['commit_ref']),'WORKER_BINDING')
        strict_verify(raw(grant['public_key'],32),raw(proof['signature'],64),canonical(['COMP-W-WORKER-v1',cl]));self._consume_nonce(c,p,cl['nonce'],oid,purpose,frozen['commit_ref'],event)
    def _finish_worker(self,c,proof,event):
        self._worker_grant(event)
        nonce=c.execute('SELECT expires FROM w_nonce WHERE nonce=?',(proof['claim']['nonce'],)).fetchone();require(nonce is not None,'REPLAY')
        require_window({'iat':'0','exp':str(nonce[0])},event)
    def _ownership(self,c,p,oid,frozen):
        plan=frozen['plan'];rs=c.execute('SELECT * FROM w_reservation WHERE profile=? AND oid=?',(p,oid)).fetchall()
        require(len(rs)==1 and rs[0]['id']==frozen['commit']['value']['reservation_ids'][0] and rs[0]['key']==enc(plan['resource_key']) and rs[0]['amount']==plan['amount'] and rs[0]['state']=='RESERVED','RESERVATION_OWNERSHIP')
        self._resource(c,p,plan['resource_key'])
        flight=c.execute('SELECT * FROM w_flight WHERE profile=? AND oid=?',(p,oid)).fetchone();require(flight is not None and flight['active']==1 and flight['key']==enc(plan['taskflight']['key']),'FLIGHT_OWNERSHIP')
        self._behavior_integrity(c,p,plan['behavior_before']['key'])
        behavior=self.state.current(c,p,'BEHAVIOR',plan['behavior_before']['key']);br=behavior['record']['value']
        require(oid in br['inflight'],'BEHAVIOR_OWNERSHIP')
        if plan['scene_after']:
            w=plan['scene_after'];s=self.state.current(c,p,w['namespace'],w['key']);require(s['record']['value']==w['row'] and s['ref']==w['ref'],'SCENE_OWNERSHIP')
    def _behavior_integrity(self,c,p,key):
        base=self.source.current(c,p,'BEHAVIOR',key)['record']['value'];actual=self.state.current(c,p,'BEHAVIOR',key)['record']['value']
        principal=key[-1];ops=c.execute('SELECT oid,frozen FROM w_operation WHERE profile=?',(p,)).fetchall()
        owned=[r['oid'] for r in ops if json.loads(r['frozen'])['op']['action']['principal']==principal]
        active=[r[0] for r in c.execute('SELECT oid FROM w_flight WHERE profile=? AND active=1',(p,)) if r[0] in owned]
        require(actual['accepted_count']==str(int(base['accepted_count'])+len(owned)) and actual['count_cap']==base['count_cap'] and actual['inflight']==sortset(base['inflight']+active),'BEHAVIOR_OWNERSHIP')
    def _claim_checks(self,c,p,oid,frozen,event):
        self._ownership(c,p,oid,frozen);op=frozen['op'];require_window({'iat':str(frozen['accepted_at']),'exp':op['permit']['body']['payload']['dispatch_before']},event)
        overlays={(p,'BEHAVIOR',enc(frozen['plan']['behavior_before']['key'])):frozen['plan']['behavior_before']}
        sb=frozen['plan']['scene_before']
        if sb:overlays[(p,sb['namespace'],enc(sb['key']))]=sb
        guard=CommonGuard(WState(self.source,overlays));derived=guard.adapters[p].derive(c,op,event)
        require(derived['deps']==op['deps'] and derived['required_reviews']==op['required'] and derived['assessment_value']==op['assessment']['value'],'DEP_CONFLICT')
        require_window(op['basis']['value'],event);require_window(op['assessment']['value'],event)
        for alias,typ,msg in [('G','Permit',op['permit']),('U','Authorization',op['authorization'])]+[('V','Review',r) for r in op['reviews']]:guard.message(c,p,alias,typ,msg,op['action'],event)
        for alias,purpose in [('H','CommitProof'),('X','Acceptance')]:self.source.credential(c,p,alias,ROLES[p][alias],purpose,op['action'],event)
        deny=self.source.deny_witness(c,p,op['ctx'],derived['required_reviews']);require(not deny['refs'],'REVIEW_DENY')
        tool,r=self._tool(c,p,op['action'],event);require(json.loads(tool['certificate'])==frozen['tool_certificate'],'TOOL_TRUST_CHANGED')
        return tool,r,deny
    def claim(self,p,oid,proof):
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid);event=self._event(c,p,oid,'CLAIM_GUARD',frozen['commit_ref']);self._worker(c,p,oid,'CLAIM',proof,event,frozen)
            out=c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',(p,oid)).fetchone()
            if out['attempt_id']:return {'profile':p,'operation_id':oid,'attempt_id':out['attempt_id'],'dispatch_state':out['state']}
            require(row['state']=='PENDING' and row['receipt'] is not None,'RECEIPT_PENDING');tool,trust,deny=self._claim_checks(c,p,oid,frozen,event)
            event=self._event(c,p,oid,'CLAIM_GUARD',frozen['commit_ref']);tool,trust,deny=self._claim_checks(c,p,oid,frozen,event)
            event=self._end_event(event);event=self._current_windows(c,p,frozen['op'],event);require_window(trust['value'],event)
            self._finish_worker(c,proof,event)
            attempt=b64(os.urandom(16));cl={'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':oid,'attempt_id':attempt,'ledger_id':trust['value']['ledger_id'],'ledger_origin':tool['origin'],'action':frozen['op']['action'],'action_hash':action_hash(p,frozen['op']['action']),'commit_ref':frozen['commit_ref'],'acceptance_ref':msgref(json.loads(row['receipt'])),'tool_trust_ref':rec_ref(trust),'issued_at':str(event['lo']),'expires':frozen['commit']['value']['dispatch_before']}
            packet={'claim':cl,'signature':b64(self.delivery_key.sign(canonical(['COMP-W-TOOL-EXEC-v1',cl])))}
            c.execute("UPDATE w_outbox SET state='STARTED',attempt_id=?,packet=? WHERE profile=? AND oid=? AND state='PENDING'",(attempt,enc(packet),p,oid));c.execute("UPDATE w_operation SET state='STARTED',effect_state='UNKNOWN' WHERE profile=? AND oid=?",(p,oid));self._journal(c,'W_CLAIM',p,oid,{'packet':packet,'event':event,'deny_witness':deny})
            self.source.observe(c,'CLAIMED',p,oid,{'stage':'领取唯一 attempt','lanes':['W','worker'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'refs':{'attempt_id':attempt,'commit_ref':frozen['commit_ref']},'status_label':'STARTED'})
            return {'profile':p,'operation_id':oid,'attempt_id':attempt,'dispatch_state':'STARTED'}
    def cancel(self,p,oid,proof):
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid);event=self._event(c,p,oid,'CANCEL_GUARD',frozen['commit_ref']);self._worker(c,p,oid,'CANCEL',proof,event,frozen)
            if row['state']=='CANCELED':return self._view(row)
            require(row['state']=='PENDING','CANCEL_STARTED');self._ownership(c,p,oid,frozen)
            try:self._claim_checks(c,p,oid,frozen,event)
            except ProtocolError as exc:require(exc.code in KNOWN_CANCEL,'CANCEL_UNKNOWN');reason=exc.code
            else:raise ProtocolError('CANCEL_NOT_INVALID')
            event=self._end_event(event);self._finish_worker(c,proof,event)
            self._release(c,p,oid,frozen,'CANCELED');c.execute("UPDATE w_operation SET state='CANCELED',effect_state='NO_EFFECT' WHERE profile=? AND oid=?",(p,oid));c.execute("UPDATE w_outbox SET state='CANCELED' WHERE profile=? AND oid=?",(p,oid));self._journal(c,'W_CANCEL',p,oid,{'reason':reason,'event':event})
            self.source.observe(c,'CANCELED',p,oid,{'stage':'取消','lanes':['W'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'refs':{'commit_ref':frozen['commit_ref']},'status_label':'CANCELED','detail':{'reason':reason}})
            return self._view(c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone())
    def _send(self,p,oid,proof,query):
        purpose='QUERY' if query else 'EXECUTE'
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid);event=self._event(c,p,oid,'QUERY_GUARD' if query else 'EXECUTE_GUARD',frozen['commit_ref']);self._worker(c,p,oid,purpose,proof,event,frozen)
            out=c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',(p,oid)).fetchone();require(out['attempt_id'] and row['state'] not in ('CANCELED','HALTED'),'NO_ATTEMPT')
            packet=json.loads(out['packet']);tool,trust=self._tool(c,p,frozen['op']['action'],event)
            if query:
                event=self._end_event(event);self._finish_worker(c,proof,event);require_window(trust['value'],event)
                cl={**packet['claim'],'query_id':b64(os.urandom(16)),'iat':str(event['lo']),'exp':str(min(event['lo']+30,int(trust['value']['exp'])))}
                packet={'claim':cl,'signature':b64(self.delivery_key.sign(canonical(['COMP-W-TOOL-QUERY-v1',cl])))};c.execute('UPDATE w_outbox SET queries=queries+1 WHERE profile=? AND oid=?',(p,oid))
            else:
                if out['exec_marker']:return {'state':'UNKNOWN','record':None,'reason':'EXEC_ALREADY_CONSUMED','attempt_id':out['attempt_id']}
                event=self._end_event(event);require_window(trust['value'],event);self._finish_worker(c,proof,event)
                require_window({'iat':packet['claim']['issued_at'],'exp':packet['claim']['expires']},event)
                c.execute('UPDATE w_outbox SET exec_marker=1 WHERE profile=? AND oid=?',(p,oid))
            self._journal(c,'W_QUERY_INTENT' if query else 'W_EXEC_INTENT',p,oid,{'packet':packet,'event':event})
            self.source.observe(c,'QUERY_DISPATCHED' if query else 'EXEC_DISPATCHED',p,oid,{'stage':'查询原 attempt' if query else '消费执行资格并派发','lanes':['worker','工具'],'refs':{'attempt_id':out['attempt_id']},'status_label':'STARTED','detail':{'purpose':purpose}})
        gateway=self.tool_gateways[p]
        try:response=gateway.query(packet) if query else gateway.execute(packet)
        except (ProtocolError,OSError,TimeoutError) as exc:response={'state':'UNKNOWN','record':None,'reason':getattr(exc,'code',type(exc).__name__),'trace':getattr(exc,'trace',{})}
        with self.source.tx() as c:
            if not query and response.get('trace',{}).get('input_submitted') is True:c.execute('UPDATE w_outbox SET send_observed=1 WHERE profile=? AND oid=?',(p,oid))
            if response.get('record') is not None:
                _,frozen=self._operation(c,p,oid)
                try:
                    event=self._event(c,p,oid,'SETTLE_GUARD',frozen['commit_ref'])
                    record,fid,halted=self._verify_final(c,p,oid,frozen,response,event)
                    if not halted:c.execute('UPDATE w_operation SET effect_state=? WHERE profile=? AND oid=?',(record['value']['outcome'],p,oid))
                except ProtocolError as exc:
                    response={**response,'validation_error':exc.code}
            c.execute('INSERT INTO w_evidence(profile,oid,kind,blob) VALUES(?,?,?,?)',(p,oid,purpose,enc(response)))
            self._journal(c,'W_TOOL_RESPONSE',p,oid,{'purpose':purpose,'response':response})
            self.source.observe(c,'TOOL_RESPONDED',p,oid,{'stage':'工具响应','lanes':['worker','工具'],'detail':{'purpose':purpose,'effect_state':response.get('state')}})
        return response
    def execute_once(self,p,oid,proof):return self._send(p,oid,proof,False)
    def query_attempt(self,p,oid,proof):return self._send(p,oid,proof,True)
    def _verify_final(self,c,p,oid,frozen,response,event):
        require(type(response) is dict and response.get('record') is not None,'FINAL_UNKNOWN');record=response['record'];self.source.schemas[p].validate(record,'Record_TOOL_FINAL');require(record['profile']==p and record['scope']==PROFILE_SCOPES[p],'FINAL_BINDING')
        tool,trust=self._tool(c,p,frozen['op']['action'],event);tv=trust['value'];v=record['value'];out=c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',(p,oid)).fetchone();require(out['attempt_id'] is not None,'NO_ATTEMPT')
        for k,expected in {'method':'tool-final-v2','ledger_id':tv['ledger_id'],'operation_id':oid,'action_hash':action_hash(p,frozen['op']['action']),'dispatch_attempt':out['attempt_id'],'tool':tv['tool'],'tool_version':tv['tool_version'],'destination':tv['destination']}.items():require(v[k]==expected,'FINAL_BINDING')
        require((v['attestation']['issuer'],v['attestation']['kid'])==(tv['issuer'],tv['kid']),'FINAL_SIGNER');strict_verify(raw(tv['public_key'],32),raw(v['attestation']['sig'],64),final_sign_bytes(record));require_window(v,event)
        require(int(v['exp'])<=int(tv['exp']) and int(v['finalized_at'])<=int(v['iat']) and int(v['finalized_at'])>=frozen['accepted_at'],'FINAL_TIME')
        require((v['outcome']=='SUCCEEDED' and v['effect_id']!='' and v['no_late_effect'] is False) or (v['outcome']=='FAILED_CONFIRMED' and v['effect_id']=='' and v['no_late_effect'] is True),'FINAL_BINDING')
        checkpoint=response.get('checkpoint');require(type(checkpoint) is dict and set(checkpoint)=={'claim','signature'},'LEDGER_CHECKPOINT_UNKNOWN');cl=checkpoint['claim'];strict_verify(raw(tv['public_key'],32),raw(checkpoint['signature'],64),canonical(['COMP-TOOL-CHECKPOINT-v1',cl]))
        from competition.tools.common_tool import request_hash
        fid=final_fact_id(record);required={'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':oid,'attempt_id':out['attempt_id'],'ledger_id':tv['ledger_id'],'ledger_origin':tool['origin'],'request_hash':request_hash(json.loads(out['packet'])['claim']),'final_fact_id':fid}
        require(set(cl)==set(required)|{'high_water','ledger_head'} and all(cl[k]==v for k,v in required.items()),'LEDGER_BINDING')
        require(type(cl['high_water']) is str and cl['high_water'].isdigit() and int(cl['high_water'])>=int(v['final_seq']) and type(cl['ledger_head']) is str,'LEDGER_BINDING')
        event=self._end_event(event);require_window(v,event);require_window(tv,event)
        contradiction=(int(cl['high_water'])==tool['high_water'] and cl['ledger_head']!=tool['head'])
        existing=c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',(p,oid)).fetchone()
        observation=c.execute('SELECT observed_fact FROM w_operation WHERE profile=? AND oid=?',(p,oid)).fetchone()[0]
        if existing and existing['fact_id']!=fid:contradiction=True
        if observation and json.loads(observation)['final_fact_id']!=fid:contradiction=True
        conflict=c.execute('SELECT * FROM w_settlement WHERE profile=? AND ledger=? AND oid!=? AND (final_seq=? OR (effect_id!=? AND effect_id=?))',(p,tv['ledger_id'],oid,v['final_seq'],'',v['effect_id'])).fetchone()
        if conflict:contradiction=True
        if contradiction:
            c.execute('UPDATE w_tool SET halted=1 WHERE profile=? AND key=?',(p,tool['key']));c.execute("UPDATE w_operation SET state='HALTED' WHERE profile=? AND oid=?",(p,oid));self._journal(c,'W_TRUSTED_CONTRADICTION',p,oid,response)
            self.source.observe(c,'HALTED',p,oid,{'stage':'可信矛盾 → HALTED','lanes':['W'],'status_label':'HALTED','detail':{'reason':'TRUSTED_CONTRADICTION'}})
            return record,fid,True
        if int(cl['high_water'])<tool['high_water']:raise ProtocolError('LEDGER_STALE_UNKNOWN')
        c.execute('UPDATE w_tool SET high_water=?,head=? WHERE profile=? AND key=?',(int(cl['high_water']),cl['ledger_head'],p,tool['key']))
        c.execute('UPDATE w_operation SET observed_fact=? WHERE profile=? AND oid=?',(enc({'final_fact_id':fid,'fact':final_fact(record)}),p,oid))
        return record,fid,False
    def settle(self,p,oid,response,proof):
        with self.source.tx() as c:
            row,frozen=self._operation(c,p,oid);event=self._event(c,p,oid,'SETTLE_GUARD',frozen['commit_ref']);self._worker(c,p,oid,'SETTLE',proof,event,frozen)
            if row['state']=='HALTED':return {'state':'HALTED','operation_id':oid,'reason':'TRUSTED_CONTRADICTION'}
            require(c.execute('SELECT attempt_id FROM w_outbox WHERE profile=? AND oid=?',(p,oid)).fetchone()[0] is not None,'NO_ATTEMPT')
            if response.get('record') is None:
                known=c.execute('SELECT fact_id FROM w_settlement WHERE profile=? AND oid=?',(p,oid)).fetchone()
                if known:return {'state':'SETTLED','operation_id':oid,'final_fact_id':known[0],'existing':True}
                return {'state':'UNKNOWN','operation_id':oid,'reservation_retained':True,'final_fact_id':None}
            record,fid,contradiction=self._verify_final(c,p,oid,frozen,response,event)
            c.execute('INSERT INTO w_evidence(profile,oid,kind,blob) VALUES(?,?,?,?)',(p,oid,'SETTLE_PROOF',enc(response)))
            if contradiction:return {'state':'HALTED','operation_id':oid,'final_fact_id':fid,'reason':'TRUSTED_CONTRADICTION'}
            existing=c.execute('SELECT * FROM w_settlement WHERE profile=? AND oid=?',(p,oid)).fetchone()
            if existing:return {'state':'SETTLED','operation_id':oid,'final_fact_id':fid,'existing':True}
            require(row['state']=='STARTED','SETTLE_STATE');self._ownership(c,p,oid,frozen);v=record['value'];event=self._end_event(event);require_window(v,event);require_window(frozen['tool_certificate']['claim']['record']['value'],event);self._finish_worker(c,proof,event);self._release(c,p,oid,frozen,'SPENT' if v['outcome']=='SUCCEEDED' else 'RELEASED')
            c.execute('INSERT INTO w_settlement VALUES(?,?,?,?,?,?,?,?)',(p,oid,fid,v['ledger_id'],v['final_seq'],v['effect_id'],v['outcome'],enc(response)));c.execute("UPDATE w_operation SET state='SETTLED',effect_state=? WHERE profile=? AND oid=?",(v['outcome'],p,oid));self._journal(c,'W_SETTLE',p,oid,{'final_fact_id':fid,'record':record,'event':event})
            self.source.observe(c,'SETTLED',p,oid,{'stage':'一次结算','lanes':['W'],'trusted_time':{'lo':event['lo'],'hi':event['hi']},'refs':{'final_fact_id':fid},'status_label':'SETTLED','detail':{'outcome':v['outcome']}})
            return {'state':'SETTLED','operation_id':oid,'final_fact_id':fid,'existing':False}
    def _release(self,c,p,oid,frozen,target):
        plan=frozen['plan'];amount=plan['amount'];c.execute('UPDATE w_reservation SET state=? WHERE profile=? AND oid=? AND state=?',(target,p,oid,'RESERVED'))
        c.execute('UPDATE w_resource SET reserved=reserved-?,spent=spent+?,revision=revision+1 WHERE profile=? AND key=?',(amount,amount if target=='SPENT' else 0,p,enc(plan['resource_key'])));c.execute('UPDATE w_flight SET active=0 WHERE profile=? AND oid=?',(p,oid))
        b=self.state.current(c,p,'BEHAVIOR',plan['behavior_before']['key']);record=copy.deepcopy(b['record']);record['value']['inflight'].remove(oid);self.state.put(c,p,'BEHAVIOR',plan['behavior_before']['key'],record,b['revision']+1)
        if plan['scene_after']:
            sw=plan['scene_after'];s=self.state.current(c,p,sw['namespace'],sw['key']);record=self.plans.terminal(p,s['record'],'SUCCEEDED' if target=='SPENT' else 'FAILED_CONFIRMED',action=frozen['op']['action']);self.state.put(c,p,sw['namespace'],sw['key'],record,s['revision']+1)
    def challenge_read(self,p,oid,purpose='STATUS'):
        require(purpose in ('STATUS','AUDIT'),'READ_PURPOSE')
        with self.source.tx() as c:
            row,f=self._operation(c,p,oid);event=self._event(c,p,oid,'STATUS_READ' if purpose=='STATUS' else 'AUDIT_READ',f['commit_ref']);self.source.read_permission(c,p,'H',f['op']['action'],event);nonce=b64(os.urandom(32))
            c.execute('INSERT INTO w_nonce VALUES(?,?,?,?,?,?,0)',(p,nonce,oid,purpose,f['commit_ref'],event['lo']+30));self.source.observe(c,'CHALLENGE_ISSUED',p,oid,{'stage':'签发读取挑战','lanes':['W'],'refs':{'commit_ref':f['commit_ref']},'detail':{'purpose':purpose}});return {'profile':p,'scope':PROFILE_SCOPES[p],'operation_id':oid,'purpose':purpose,'commit_ref':f['commit_ref'],'nonce':nonce}
    def _read(self,p,oid,proof,purpose):
        with self.source.tx() as c:
            row,f=self._operation(c,p,oid);event=self._event(c,p,oid,'STATUS_READ' if purpose=='STATUS' else 'AUDIT_READ',f['commit_ref']);require(type(proof) is dict and set(proof)=={'claim','signature'},'IDENTITY_REQUIRED');cl=proof['claim']
            require(set(cl)=={'profile','scope','operation_id','purpose','commit_ref','nonce'} and (cl['profile'],cl['scope'],cl['operation_id'],cl['purpose'],cl['commit_ref'])==(p,PROFILE_SCOPES[p],oid,purpose,f['commit_ref']),'BINDING');who=self.source.actors[p]['H'];strict_verify(who.pub,raw(proof['signature'],64),canonical(['COMP-W-READ-v1',cl]));self.source.credential(c,p,'H',ROLES[p]['H'],'StatusQuery',f['op']['action'],event);self.source.read_permission(c,p,'H',f['op']['action'],event);self._consume_nonce(c,p,cl['nonce'],oid,purpose,f['commit_ref'],event)
            view=self._view(row);out=c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',(p,oid)).fetchone();view.update(attempt_id=out['attempt_id'],exec_consumed=bool(out['exec_marker']),queries=out['queries'],original_envelope=False,view_kind='APPLICATION_W_PROJECTION')
            if purpose=='AUDIT':view.update(commit=f['commit'],time_witness=f['time_witness'],evidence=[json.loads(r[0]) for r in c.execute('SELECT blob FROM w_evidence WHERE profile=? AND oid=? ORDER BY seq',(p,oid))])
            self.source.observe(c,'READ_PROJECTED',p,oid,{'stage':'认证读取投影','lanes':['受信编排器'],'refs':{'commit_ref':f['commit_ref']},'status_label':view['dispatch_state'],'detail':{'purpose':purpose}})
            return view
    def status(self,p,oid,proof):return self._read(p,oid,proof,'STATUS')
    def audit(self,p,oid,proof):return self._read(p,oid,proof,'AUDIT')
    def counts(self):
        with self.source.db() as c:
            one=lambda sql:c.execute(sql).fetchone()[0]
            return {'accepts':one('SELECT COUNT(*) FROM w_operation'),'outbox':one('SELECT COUNT(*) FROM w_outbox'),'attempts':one('SELECT COUNT(*) FROM w_outbox WHERE attempt_id IS NOT NULL'),'exec_invocations':one('SELECT COALESCE(SUM(exec_marker),0) FROM w_outbox'),'execution_sends_observed':one('SELECT COALESCE(SUM(send_observed),0) FROM w_outbox'),'execution_sends_unobserved_upper_bound':one('SELECT COUNT(*) FROM w_outbox WHERE exec_marker=1 AND send_observed IS NULL'),'queries':one('SELECT COALESCE(SUM(queries),0) FROM w_outbox'),'confirmed_simulated_effects':one("SELECT COUNT(*) FROM w_operation WHERE json_extract(observed_fact,'$.fact.outcome')='SUCCEEDED'"),'settlements':one('SELECT COUNT(*) FROM w_settlement'),'cancellations':one("SELECT COUNT(*) FROM w_operation WHERE state='CANCELED'"),'halts':one("SELECT COUNT(*) FROM w_operation WHERE state='HALTED'")}
