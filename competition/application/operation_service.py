"""Allowlisted IND boundary. Transport access never supplies role signing authority."""
import copy
import os
from jsonschema import ValidationError
from competition.application.request_bound_w import RequestBoundW
from competition.application.trusted_action_resolver import PROFILE
from competition.core.trusted_state import PROFILE_SCOPES, ROLES
from competition.core.event_clock import require_window
from competition.support.wire import require, raw, b64, canonical, digest, strict_verify, number, ProtocolError

METHOD_FIELDS = {
    'propose':('proposal','auth'), 'identity_challenge':('op',),
    'submit':('key','op','identity','expected_version','expected_ref'),
    'prepare':('key','identity'), 'accept_challenge':('ticket_id',),
    'accept':('ticket_id','proof'), 'recover_challenge':('key',),
    'recover':('key','proof'), 'status_challenge':('operation_id',),
    'status':('operation_id','proof'),
}

class OperationService:
    def __init__(self,resolver,workflow):
        require(isinstance(workflow.w,RequestBoundW) and
                workflow.requests is resolver.requests is workflow.w.requests and
                workflow.w.source is resolver.state and workflow.profile == resolver.profile == PROFILE,
                'REQUEST_BOUND_W_REQUIRED')
        self.resolver,self.workflow,self.w=resolver,workflow,workflow.w
        self.requests=resolver.requests

    def _scoped_row(self,c,key):
        raw(key,32)
        row=self.requests._row(c,key);require(row is not None,'REQUEST_UNKNOWN')
        construction=self.requests._construction(row)
        require(construction['task_id']==self.resolver.task_id and
                construction['approval_request']['basis']['profile']==PROFILE,'REQUEST_SCOPE')
        return row,construction

    def _recover_challenge(self,key):
        raw(key,32)
        # No lookup: arbitrary challenge requests reveal no saved data or existence.
        with self.w.source.tx() as c:
            event=self.w._event(c,PROFILE,'','AUTHZ_READ',key)
            claim={'profile':PROFILE,'scope':PROFILE_SCOPES[PROFILE],
                'task_id':self.resolver.task_id,'key':key,'purpose':'RECOVER',
                'nonce':b64(os.urandom(32)),'iat':str(event['lo']),'exp':str(event['lo']+30)}
            c.execute('INSERT INTO a_identity VALUES(?,?,?,?,?,?,0)',
                (claim['nonce'],PROFILE,'',digest(claim),'APP_RECOVER',event['lo']+30))
            return claim

    def _recover(self,key,proof):
        raw(key,32)
        require(type(proof) is dict and set(proof)=={'claim','signature'},'IDENTITY_REQUIRED')
        claim=proof['claim']
        require(type(claim) is dict and set(claim)=={
            'profile','scope','task_id','key','purpose','nonce','iat','exp'},'AUTH_FIELDS')
        require((claim['profile'],claim['scope'],claim['task_id'],claim['key'],claim['purpose'])==
            (PROFILE,PROFILE_SCOPES[PROFILE],self.resolver.task_id,key,'RECOVER'),'AUTH_BINDING')
        who=self.w.source.actors[PROFILE]['H']
        strict_verify(who.pub,raw(proof['signature'],64),canonical(['ZJJ-APP-RECOVER-v1',claim]))
        with self.w.source.tx() as c:
            event=self.w._event(c,PROFILE,'','AUTHZ_READ',digest(claim))
            nonce=c.execute('SELECT * FROM a_identity WHERE nonce=?',(claim['nonce'],)).fetchone()
            require(nonce is not None and nonce['used']==0 and nonce['profile']==PROFILE and
                nonce['stage']=='APP_RECOVER' and nonce['request_ref']==digest(claim),'REPLAY')
            require_window(claim,event)
            row,construction=self._scoped_row(c,key);action=construction['action']
            self.w.source.credential(c,PROFILE,'H',ROLES[PROFILE]['H'],'StatusQuery',action,event)
            self.w.source.read_permission(c,PROFILE,'H',action,event)
            saved=self.requests._loaded(row) if row['full_op'] is not None else None
            result={'key':key,'operation_id':row['oid'],'construction':construction,
                'submission':saved,'state':'NOT_ACCEPTED' if saved else 'APPROVAL_PENDING','operation':None}
            operation=c.execute('SELECT * FROM w_operation WHERE profile=? AND oid=?',
                                (PROFILE,row['oid'])).fetchone()
            if operation:
                require(saved is not None and operation['request_ref']==saved['request_ref'],'OUTBOX_INTEGRITY')
                out=c.execute('SELECT * FROM w_outbox WHERE profile=? AND oid=?',(PROFILE,row['oid'])).fetchone()
                result.update(state='COMMITTED',operation={**self.w._view(operation),
                    'attempt_id':out['attempt_id'],'exec_consumed':bool(out['exec_marker'])})
            final=self.w._end_event(event);require_window(claim,final)
            self.w.source.credential(c,PROFILE,'H',ROLES[PROFILE]['H'],'StatusQuery',action,final)
            self.w.source.read_permission(c,PROFILE,'H',action,final)
            c.execute('UPDATE a_identity SET used=1 WHERE nonce=?',(claim['nonce'],))
            return result

    def invoke(self,method,params):
        require(type(method) is str and method in METHOD_FIELDS,'METHOD_NOT_ALLOWED')
        require(type(params) is dict and set(params)==set(METHOD_FIELDS[method]),'SERVICE_FIELDS')
        try:return self._invoke(method,copy.deepcopy(params))
        except ValidationError as exc:raise ProtocolError('SCHEMA_INVALID') from exc
        except (KeyError,TypeError,ValueError) as exc:
            if isinstance(exc,ProtocolError):raise
            raise ProtocolError('INPUT_FIELDS') from exc

    def _invoke(self,method,args):
        if method=='propose':return self.resolver.resolve(args['proposal'],args['auth'])
        if method in ('identity_challenge','submit'):
            require(args['op']['task_id']==self.resolver.task_id,'REQUEST_SCOPE')
        if method=='identity_challenge':
            self.w.source.schemas[PROFILE].validate(args['op']['action'],'Action')
            return self.w.source.challenge(PROFILE,args['op'],'GUARD')
        if method=='submit':
            raw(args['key'],32)
            require(number(args['expected_version']) and type(args['expected_ref']) is str,'SERVICE_FIELDS')
            return self.workflow.submit_authenticated(args['key'],args['op'],args['identity'],
                int(args['expected_version']),args['expected_ref'])
        if method=='prepare':
            with self.w.source.db() as c:self._scoped_row(c,args['key'])
            return self.workflow.prepare_saved(args['key'],args['identity'])
        if method=='accept_challenge':
            raw(args['ticket_id'],16);return self.w.challenge_accept(PROFILE,args['ticket_id'])
        if method=='accept':
            raw(args['ticket_id'],16);return self.workflow.accept(args['ticket_id'],args['proof'])
        if method=='recover_challenge':return self._recover_challenge(args['key'])
        if method=='recover':return self._recover(args['key'],args['proof'])
        raw(args['operation_id'],16)
        if method=='status_challenge':return self.w.challenge_read(PROFILE,args['operation_id'])
        return self.w.status(PROFILE,args['operation_id'],args['proof'])
