"""Trusted host orchestration. Receives approvals/proofs; never creates them."""
import copy
from competition.application.request_store import request_ref
from competition.application.trusted_action_resolver import PROFILE
from competition.support.wire import require

class OperationOrchestrator:
    def __init__(self, w, requests, *, profile=PROFILE):
        require(profile == PROFILE and requests.state is w.source, 'W_BINDING')
        self.w, self.requests, self.profile = w, requests, profile

    def freeze_approved(self, key, op):
        op = copy.deepcopy(op)
        with self.w.source.tx() as c:
            row = self.requests._row(c, key)
            require(row is not None, 'REQUEST_UNKNOWN')
            self.requests._check_op(row, op)
            if row['full_op'] is None:
                event = self.w.source.event(c, self.profile, op['action']['operation_id'],
                                            'AUTHZ_GUARD', request_ref(self.profile, op))
                self.w.guard.verify(c, self.profile, op, event)
                # Reuse W's final bounded-time/current-window gate. Only the
                # first freeze is a new decision; committed retries retain op.
                self.w._current_windows(c, self.profile, op, event, accept=True)
            return self.requests._freeze(c, key, self.profile, op)

    def prepare_approved(self, key, op, identity_proof):
        self.freeze_approved(key, op)
        return self.prepare_saved(key, identity_proof)

    def prepare_saved(self, key, identity_proof):
        saved = self.requests.load(key)
        return self.w.prepare(self.profile, saved['op'], identity_proof)

    def accept(self, ticket_id, holder_proof):
        return self.w.accept(self.profile, ticket_id, holder_proof)
