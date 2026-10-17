"""EXPERIMENT ONLY: trusted, public-key-only IND construction and frozen outbox.

The untrusted boundary is submit(proposal, auth). Server bootstrap chooses Task.
freeze/load are trusted-host operations, never Agent tools. No signer is held or
imported here. Tables are additive and live inside the controlled W database.
"""
import copy
import json
import os
from competition.core.trusted_state import prefix, enc, ROLES, PROFILE_SCOPES
from competition.core.event_clock import require_window
from competition.profiles.authorization_scene import SceneAuthorizationAdapter
from competition.support.tool_final import verify_certificate
from competition.support.wire import require, b64, raw, canonical, strict_verify, digest, rec_ref

P='IND-DEMO-1'

class TrustedAdapter:
    def __init__(self, store, task_id):
        self.store=store
        self.task_id=task_id
        raw(task_id,16)
        self.business=SceneAuthorizationAdapter(store,P,store.actors[P])
        with store.db() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS exp_proposal(
                request_key TEXT PRIMARY KEY, intent_ref TEXT NOT NULL,
                oid TEXT NOT NULL UNIQUE, construction TEXT NOT NULL,
                full_op TEXT, request_ref TEXT)''')

    def submit(self, proposal, auth):
        require(type(proposal) is dict and set(proposal)=={'request_id','unit_id','route'},'PROPOSAL_FIELDS')
        require(all(type(v) is str and 0<len(v)<=128 for v in proposal.values()),'PROPOSAL_VALUE')
        require(proposal['route'] in ('INSPECT','RELEASE','QUARANTINE'),'PROPOSAL_ROUTE')
        require(type(auth) is dict and set(auth)=={'claim','signature'},'IDENTITY_REQUIRED')
        cl=auth['claim']
        require(type(cl) is dict and set(cl)=={'profile','task_id','proposal','iat','exp'},'AUTH_FIELDS')
        require((cl['profile'],cl['task_id'],cl['proposal'])==(P,self.task_id,proposal),'AUTH_BINDING')
        who=self.store.actors[P]['H']
        strict_verify(who.pub,raw(auth['signature'],64),canonical(['EXP-PROPOSAL-AUTH-v1',cl]))
        key=digest(['EXP-REQUEST-KEY-v1',P,who.name,self.task_id,proposal['request_id']])
        intent=digest(['EXP-PROPOSAL-v1',P,self.task_id,proposal])
        with self.store.tx() as c:
            event=self.store.event(c,P,'','AUTHZ_READ',intent)
            require_window(cl,event)
            self.store.credential(c,P,'H',ROLES[P]['H'],'IssueRequest',None,event)
            self.store.credential(c,P,'H','READER','READ',None,event)
            # Authenticated retries recover frozen construction even after READY
            # changes at accept; W still rechecks current qualification on calls.
            old=c.execute('SELECT * FROM exp_proposal WHERE request_key=?',(key,)).fetchone()
            if old:
                require(old['intent_ref']==intent,'REQUEST_CONFLICT')
                saved=json.loads(old['construction'])
                self.store.read_permission(c,P,'H',saved['action'],event)
                return saved
            taskrow=self.store.current(c,P,'TASK',prefix(P)+[self.task_id])
            polrow=self.store.current(c,P,'POLICY',prefix(P))
            task,policy=taskrow['record']['value'],polrow['record']['value']
            require_window(task,event);require_window(policy,event)
            require(task['policy_ref']==polrow['ref'],'STALE')
            require((task['holder'],task['holder_kid'])==(who.name,who.kid),'WRONG_HOLDER')
            allowed=[u for u in task['allowed_units'] if u['unit_id']==proposal['unit_id']]
            require(len(allowed)==1 and proposal['route'] in task['allowed_routes'],'TASK_SCOPE')
            unit=allowed[0];route=proposal['route'];route_key=route.lower()
            require(task['route_destinations'][route_key]==policy['route_destinations'][route_key],'TOOL_BINDING')
            destination=policy['route_destinations'][route_key]
            require(task['tool']==policy['tool'] and task['tool_version']==policy['tool_version'],'TOOL_BINDING')
            x=self.store.actors[P]['X']
            require(task['executor']==policy['executor']==x.name and policy['executor_kid']==x.kid,'KEY_BINDING')
            # ID is allocated only here, within the authenticated W transaction.
            action={'scope':copy.deepcopy(PROFILE_SCOPES[P]),'operation_id':b64(os.urandom(16)),
                    'principal':task['principal'],'holder':who.name,'holder_kid':who.kid,
                    'executor':x.name,'tool':policy['tool'],'tool_version':policy['tool_version'],
                    'destination':destination,'payload':{
                        'line_id':task['line_id'],'station_id':task['station_id'],
                        'unit_id':unit['unit_id'],'batch_id':unit['batch_id'],
                        'inspection_cycle':unit['inspection_cycle'],'phase':unit['phase'],'route':route}}
            self.store.schemas[P].validate(action,'Action')
            self.store.credential(c,P,'H',ROLES[P]['H'],'IssueRequest',action,event)
            self.store.credential(c,P,'X',ROLES[P]['X'],'Acceptance',action,event)
            toolkey=enc([action[k] for k in ('tool','tool_version','destination')])
            tool=c.execute('SELECT * FROM w_tool WHERE profile=? AND key=?',(P,toolkey)).fetchone()
            require(tool is not None,'TOOL_TRUST_UNKNOWN');require(not tool['halted'],'TRUSTED_CONTRADICTION')
            certificate=json.loads(tool['certificate']);record=verify_certificate(certificate,self.store.root_public,P)
            require(record['scope']==action['scope'] and tool['origin']==certificate['claim']['ledger_origin'],'TOOL_BINDING')
            require([record['value'][k] for k in ('tool','tool_version','destination')]==[action[k] for k in ('tool','tool_version','destination')],'TOOL_BINDING')
            require_window(record['value'],event)
            self.store.read_permission(c,P,'H',action,event)
            scene_key=prefix(P)+[task['line_id'],unit['unit_id']]
            ev=self.store.current(c,P,'EVIDENCE',scene_key)['record']['value']
            # Preserve a fixed assessment window; retries never extend it.
            exp=min(event['lo']+90,int(ev['attestation']['exp']),int(task['exp']),int(policy['exp']))
            op={'action':action,'task_id':self.task_id,'scene_key':scene_key,
                'assessment':{'value':{'cutoff':str(event['lo']),'iat':str(event['lo']),'exp':str(exp)}}}
            derived=self.business.derive(c,op,event)
            row={'key':key,'action':action,'task_id':self.task_id,'scene_key':scene_key,
                 'assessment_value':derived['assessment_value'],
                 'sources':{'task_ref':taskrow['ref'],'policy_ref':polrow['ref'],
                            'holder_kid':who.kid,'executor_kid':x.kid,'tool_ref':rec_ref(record)}}
            c.execute('INSERT INTO exp_proposal VALUES(?,?,?,?,NULL,NULL)',(key,intent,action['operation_id'],enc(row)))
            return copy.deepcopy(row)

    def freeze(self,key,op):
        """Trusted host persists the exact approved request BEFORE W.prepare.

        This is a write-once outbox, not an approval API. Invalid chains still
        fail at the unmodified CommonGuard; a conflicting frozen request fails.
        """
        ref=digest(['COMP-APP-CALL-v1',P,op])
        with self.store.tx() as c:
            old=c.execute('SELECT * FROM exp_proposal WHERE request_key=?',(key,)).fetchone()
            require(old is not None,'REQUEST_UNKNOWN')
            row=json.loads(old['construction'])
            require(op['action']==row['action'] and op['task_id']==row['task_id'] and op['scene_key']==row['scene_key'],'FROZEN_ACTION_CONFLICT')
            if old['full_op'] is not None:
                require(old['request_ref']==ref and json.loads(old['full_op'])==op,'FROZEN_REQUEST_CONFLICT')
            else:c.execute('UPDATE exp_proposal SET full_op=?,request_ref=? WHERE request_key=?',(enc(op),ref,key))
        return ref

    def load(self,key):
        """Trusted host only; never a public lookup using arbitrary request keys."""
        with self.store.db() as c:row=c.execute('SELECT * FROM exp_proposal WHERE request_key=?',(key,)).fetchone()
        require(row is not None,'REQUEST_UNKNOWN')
        require(row['full_op'] is not None,'APPROVAL_PENDING')
        op=json.loads(row['full_op'])
        require(digest(['COMP-APP-CALL-v1',P,op])==row['request_ref'],'OUTBOX_INTEGRITY')
        return {'op':op,'request_ref':row['request_ref']}
