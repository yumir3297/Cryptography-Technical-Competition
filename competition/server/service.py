"""The trusted service: orchestrator + Resolver + W behind the minimal interface.

The interface is three messages wide:

    submit(profile, intent)                       -> {operation_id, challenge}
    challenge(operation_id, step)                 -> claim
    prove(operation_id, step, {claim, signature}) -> step result

A caller holds only two things: its own key and its business intent.  Everything
else -- scope, principals, holders, tool, destination, task, scene key, the
operation id, and the whole signed chain -- is filled from the profile's bound
corpus, so a caller never has to supply a field it cannot see.

Everything past ``submit`` is a verbatim forward to the unchanged core.  The only
real logic here is merging ``intent`` into the profile template, deriving the
scene key, and re-binding the one field that cascades from it (IND's destination
follows the chosen route).  Validation, signatures, windows, nonces, idempotence
and state live in the black box, not here.

Session authentication has no message of its own: a session *is* the caller
holding the registered key, and it is proven by the signature carried in every
``prove``.  ``answer``/``step``/``run_normal`` are the local fallback that lets
the three normal paths run before external role clients are connected.
"""
import copy

from competition.bridge.facade import TrustedFacade
from competition.support.scene_contract import DEST
from competition.support.wire import require

# The core's challenge signature domains, as the black box defines them.
GUARD_DOMAIN = 'COMP-APP-AUTHZ-IDENTITY-v1'   # H, TrustedState.challenge(GUARD)
ACCEPT_DOMAIN = 'COMP-APP-ACCEPT-v1'          # H, CommonW.challenge_accept
WORKER_DOMAIN = 'COMP-W-WORKER-v1'            # worker, CommonW.challenge_worker
READ_DOMAIN = 'COMP-W-READ-v1'                # H, CommonW.challenge_read
SIGN_CALL_DOMAIN = 'COMP-APP-SIGN-CALL-v1'    # role alias, ScopedSignerBroker.challenge

# The business fields a caller actually knows, per profile.  Every other Action
# field is a schema const or is bound by the profile corpus.
INTENT_FIELDS = {
    'IND-DEMO-1': ('line_id', 'station_id', 'unit_id', 'batch_id',
                   'inspection_cycle', 'phase', 'route'),
    'PAY-1': ('order_id', 'stage', 'payer', 'payee', 'amount_minor'),
    'MED-DEMO-1': ('synthetic_patient_id', 'encounter_id', 'template_id'),
}

# step -> (challenge kind, purpose, signing role, signing domain)
STEPS = {
    'prepare': ('guard', None, 'H', GUARD_DOMAIN),
    'accept': ('accept', None, 'H', ACCEPT_DOMAIN),
    'claim': ('worker', 'CLAIM', 'worker', WORKER_DOMAIN),
    'exec': ('worker', 'EXECUTE', 'worker', WORKER_DOMAIN),
    'query': ('worker', 'QUERY', 'worker', WORKER_DOMAIN),
    'settle': ('worker', 'SETTLE', 'worker', WORKER_DOMAIN),
    'cancel': ('worker', 'CANCEL', 'worker', WORKER_DOMAIN),
    'status': ('read', 'STATUS', 'H', READ_DOMAIN),
    'audit': ('read', 'AUDIT', 'H', READ_DOMAIN),
}


def scene_key_for(profile, scope, payload):
    """The scene key the seeded W keys its business records under."""
    prefix = [scope['domain'], scope['tenant'], scope['scenario']]
    if profile == 'IND-DEMO-1':
        return prefix + [payload['line_id'], payload['unit_id']]
    if profile == 'MED-DEMO-1':
        return prefix + [payload['synthetic_patient_id'], payload['encounter_id']]
    if profile == 'PAY-1':
        return payload['order_id']
    raise KeyError(profile)


def _bound_destination(profile, payload):
    """The only Action field that cascades from a caller's business choice."""
    if profile == 'IND-DEMO-1':
        return DEST[payload['route']]
    return None


class TrustedService:
    """Orchestrator + Resolver + W, exposed as the minimal three-message interface."""

    def __init__(self, run, signer):
        self.run = run
        self.facade = TrustedFacade(run)
        self.signer = signer
        self._entries = {}

    # -- 候选提交: intent -> full Action -> assembled request ---------------
    def submit(self, profile, intent=None):
        """Assemble the caller's business intent into a signed request.

        Returns the operation handle and the first (prepare/GUARD) challenge, so a
        one-shot caller needs no extra round trip.
        """
        require(profile in INTENT_FIELDS, 'PROFILE')
        base = self.run.operations[profile]
        action = copy.deepcopy(base['action'])
        action['payload'].update(self._kept_intent(profile, intent))
        destination = _bound_destination(profile, action['payload'])
        if destination is not None:
            action['destination'] = destination
        scene_key = scene_key_for(profile, action['scope'], action['payload'])
        op = self.facade.build_op(profile, action, base['task_id'], scene_key)
        operation_id = op['action']['operation_id']
        self._entries[operation_id] = {'profile': profile, 'op': op,
                                       'ticket': None, 'response': None}
        return {'operation_id': operation_id, 'challenge': self.challenge(operation_id, 'prepare')}

    @staticmethod
    def _kept_intent(profile, intent):
        intent = dict(intent or {})
        unknown = sorted(set(intent) - set(INTENT_FIELDS[profile]))
        require(not unknown, 'INTENT_FIELDS')
        return intent

    # -- 发挑战: server hands out one challenge ----------------------------
    def challenge(self, operation_id, step):
        require(step in STEPS, 'STEP')
        entry = self._entry(operation_id)
        kind, purpose, _, _ = STEPS[step]
        profile = entry['profile']
        if kind == 'guard':
            return self.facade.challenge(profile, entry['op'])
        if kind == 'accept':
            require(entry['ticket'] is not None, 'TICKET_UNKNOWN')
            return self.facade.challenge_accept(profile, entry['ticket'])
        if kind == 'worker':
            return self.facade.challenge_worker(profile, operation_id, purpose)
        return self.facade.challenge_read(profile, operation_id, purpose)

    # -- 收签名: server accepts the caller's proof -------------------------
    def prove(self, operation_id, step, proof):
        require(step in STEPS, 'STEP')
        entry = self._entry(operation_id)
        profile = entry['profile']
        if step == 'prepare':
            ticket = self.facade.prepare(profile, entry['op'], proof)
            entry['ticket'] = ticket['ticket_id']
            return ticket
        if step == 'accept':
            require(entry['ticket'] is not None, 'TICKET_UNKNOWN')
            return self.facade.accept(profile, entry['ticket'], proof)
        if step == 'claim':
            return self.facade.claim(profile, operation_id, proof)
        if step == 'exec':
            entry['response'] = self.facade.execute_once(profile, operation_id, proof)
            return entry['response']
        if step == 'query':
            entry['response'] = self.facade.query_attempt(profile, operation_id, proof)
            return entry['response']
        if step == 'settle':
            require(entry['response'] is not None, 'RESPONSE_REQUIRED')
            return self.facade.settle(profile, operation_id, entry['response'], proof)
        if step == 'cancel':
            return self.facade.cancel(profile, operation_id, proof)
        if step == 'status':
            return self.facade.status(profile, operation_id, proof)
        return self.facade.audit(profile, operation_id, proof)

    def counts(self):
        """Whole-W summary counters (no caller authentication)."""
        return self.facade.counts()

    def _entry(self, operation_id):
        require(operation_id in self._entries, 'OPERATION_UNKNOWN')
        return self._entries[operation_id]

    # -- local fallback: answer a challenge through the configured signer ---
    def answer(self, profile, role, domain, claim):
        """Return a ``{claim, signature}`` proof for a handed-out challenge."""
        return {'claim': claim, 'signature': self.signer.sign(profile, role, domain, claim)}

    def step(self, operation_id, step):
        """Local-fallback driver: challenge -> answer -> prove."""
        profile = self._entry(operation_id)['profile']
        _, _, role, domain = STEPS[step]
        claim = self.challenge(operation_id, step)
        return self.prove(operation_id, step, self.answer(profile, role, domain, claim))

    def run_normal(self, profile, intent=None):
        """Drive submit -> prepare -> accept -> claim -> exec -> settle -> status."""
        submitted = self.submit(profile, intent)
        operation_id = submitted['operation_id']
        _, _, role, domain = STEPS['prepare']
        self.prove(operation_id, 'prepare',
                   self.answer(profile, role, domain, submitted['challenge']))
        self.step(operation_id, 'accept')
        self.step(operation_id, 'claim')
        self.step(operation_id, 'exec')
        settled = self.step(operation_id, 'settle')
        view = self.step(operation_id, 'status')
        return {'operation_id': operation_id, 'settled': settled, 'status': view}

    # -- result face: caller retrieves its result with verifiable evidence --
    def result(self, operation_id):
        """Assemble the export bundle for one committed operation.

        Reads ``status`` and ``audit`` through the same challenge/sign path as
        every other step (local fallback or an injected ``Signer``), so the
        projections carry real H read credentials.
        """
        from competition.server import export
        entry = self._entry(operation_id)
        status = self.step(operation_id, 'status')
        audit = self.step(operation_id, 'audit')
        return export.operation_bundle(self.run, entry['profile'], entry['op'], status, audit)

    def export(self, operation_id, out_dir):
        """Write the export bundle (public keys, signatures, projections) to disk."""
        from competition.server import export
        return export.write_bundle(self.result(operation_id), out_dir)
