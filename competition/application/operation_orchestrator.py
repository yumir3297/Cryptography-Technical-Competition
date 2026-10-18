"""Trusted host orchestration. Receives approvals/proofs; never creates them."""
import copy
from competition.application.request_store import request_ref
from competition.application.trusted_action_resolver import PROFILE
from competition.support.wire import require
from competition.core.event_clock import require_window
from competition.core.trusted_state import ROLES

class OperationOrchestrator:
    def __init__(self, w, requests, *, profile=PROFILE):
        require(profile == PROFILE and requests.state is w.source, 'W_BINDING')
        self.w, self.requests, self.profile = w, requests, profile

    def freeze_approved(self, key, op):
        op = copy.deepcopy(op)
        with self.w.source.tx() as c:
            return self._freeze_in_tx(c,key,op)

    def _freeze_in_tx(self,c,key,op):
        row = self.requests._row(c,key)
        require(row is not None,'REQUEST_UNKNOWN')
        self.requests._check_op(row,op)
        if row['full_op'] is None:
            event = self.w._event(c,self.profile,op['action']['operation_id'],
                                  'AUTHZ_GUARD',request_ref(self.profile,op))
            self.w.guard.verify(c,self.profile,op,event)
            self.w._current_windows(c,self.profile,op,event,accept=True)
        return self.requests._freeze(c,key,self.profile,op)

    def prepare_approved(self, key, op, identity_proof):
        self.freeze_approved(key, op)
        return self.prepare_saved(key, identity_proof)

    def replace_pending(self, key, op, expected_version, expected_ref):
        """Internal trusted coordinator; participants supplied all signatures."""
        op = copy.deepcopy(op)
        with self.w.source.tx() as c:
            return self._replace_in_tx(c,key,op,expected_version,expected_ref)

    def _replace_in_tx(self,c,key,op,expected_version,expected_ref):
        row,history,ref,changed = self.requests._replacement(c,key,self.profile,op,
                                                          expected_version,expected_ref)
        if changed:
            event = self.w._event(c,self.profile,row['oid'],'AUTHZ_GUARD',ref)
            self.w.guard.verify(c,self.profile,op,event)
            self.w._current_windows(c,self.profile,op,event,accept=True)
            self.requests._save(c,row,self.profile,op,ref,history)
        return self.requests._loaded(self.requests._row(c,key))

    def submit_authenticated(self,key,op,identity,version,previous_ref):
        """Transport boundary: authenticate full op before mutating the request store."""
        op=copy.deepcopy(op)
        with self.w.source.tx() as c:
            event=self.w._event(c,self.profile,op['action']['operation_id'],'AUTHZ_GUARD',
                                request_ref(self.profile,op))
            self.w.source.authenticate(c,self.profile,op,identity,'GUARD',event)
            before=self.requests._row(c,key)
            previous_version=before['submission_version'] if before is not None else 0
            if version == 0:
                require(previous_ref == '','SUBMISSION_VERSION_CONFLICT')
                self._freeze_in_tx(c,key,op)
                result=self.requests._loaded(self.requests._row(c,key))
            else:result=self._replace_in_tx(c,key,op,version,previous_ref)
            # A valid entry proof is not a lease past its server nonce expiry.
            final=self.w._event(c,self.profile,op['action']['operation_id'],'AUTHZ_GUARD',
                                request_ref(self.profile,op))
            nonce=c.execute('SELECT expires FROM a_identity WHERE nonce=?',
                            (identity['claim']['nonce'],)).fetchone()
            require(nonce is not None,'REPLAY')
            window={'iat':'0','exp':str(nonce['expires'])}
            require_window(window,final)
            self.w.source.credential(c,self.profile,'H',ROLES[self.profile]['H'],'IssueRequest',op['action'],final)
            self.w.source.read_permission(c,self.profile,'H',op['action'],final)
            if result['version'] != previous_version:
                final=self.w._current_windows(c,self.profile,op,final,accept=True)
            else:final=self.w._end_event(final)
            self.w.source.credential(c,self.profile,'H',ROLES[self.profile]['H'],'IssueRequest',op['action'],final)
            self.w.source.read_permission(c,self.profile,'H',op['action'],final)
            require_window(window,final)
            self.w._journal(c,'APP_SUBMIT_AUTH',self.profile,op['action']['operation_id'],
                {'request_ref':result['request_ref'],'version':str(result['version']),
                 'identity':identity,'event':final})
            return result

    def prepare_saved(self, key, identity_proof):
        saved = self.requests.load(key)
        return self.w.prepare(self.profile, saved['op'], identity_proof)

    def accept(self, ticket_id, holder_proof):
        return self.w.accept(self.profile, ticket_id, holder_proof)
