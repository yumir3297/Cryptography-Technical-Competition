"""The trusted service: orchestrator + Resolver + W behind the interface.

Every method mirrors the challenge/signature interface.  ``challenge_*`` hands
out a core challenge for a caller to sign; the operation methods accept the proof
back.  The service never signs on a caller's behalf -- :meth:`TrustedService.answer`
delegates to the configured :class:`~competition.server.signer.Signer`, which this
round is the local fallback.

Lane mapping (diagram -> black box):
  受信编排器            this service's orchestration (build, prepare, accept, ...)
  Resolver              :meth:`build_op` -> ``WRun.fork_operation``
  W                     the unchanged ``CommonW`` reached through ``TrustedFacade``
"""
from competition.bridge.facade import TrustedFacade

# The core's challenge signature domains, as the black box defines them.
GUARD_DOMAIN = 'COMP-APP-AUTHZ-IDENTITY-v1'   # H, TrustedState.challenge(GUARD)
ACCEPT_DOMAIN = 'COMP-APP-ACCEPT-v1'          # H, CommonW.challenge_accept
WORKER_DOMAIN = 'COMP-W-WORKER-v1'            # worker, CommonW.challenge_worker
READ_DOMAIN = 'COMP-W-READ-v1'                # H, CommonW.challenge_read
SIGN_CALL_DOMAIN = 'COMP-APP-SIGN-CALL-v1'    # role alias, ScopedSignerBroker.challenge


class TrustedService:
    """Orchestrator + Resolver + W, exposed as the challenge/signature interface."""

    def __init__(self, run, signer):
        self.run = run
        self.facade = TrustedFacade(run)
        self.signer = signer

    # -- Resolver -----------------------------------------------------------
    def build_op(self, profile, action, task_id, scene_key):
        """Rebuild an Action plus its basis/assessment/chain from the current W."""
        return self.facade.build_op(profile, action, task_id, scene_key)

    # -- interface out: challenges for a caller to sign ---------------------
    def challenge(self, profile, op):
        return self.facade.challenge(profile, op)

    def challenge_accept(self, profile, ticket):
        return self.facade.challenge_accept(profile, ticket)

    def challenge_worker(self, profile, oid, purpose):
        return self.facade.challenge_worker(profile, oid, purpose)

    def challenge_read(self, profile, oid, purpose='STATUS'):
        return self.facade.challenge_read(profile, oid, purpose)

    # -- interface in: operations that accept the caller's proof ------------
    def prepare(self, profile, op, proof):
        return self.facade.prepare(profile, op, proof)

    def accept(self, profile, ticket, proof):
        return self.facade.accept(profile, ticket, proof)

    def claim(self, profile, oid, proof):
        return self.facade.claim(profile, oid, proof)

    def execute_once(self, profile, oid, proof):
        return self.facade.execute_once(profile, oid, proof)

    def query_attempt(self, profile, oid, proof):
        return self.facade.query_attempt(profile, oid, proof)

    def settle(self, profile, oid, response, proof):
        return self.facade.settle(profile, oid, response, proof)

    def cancel(self, profile, oid, proof):
        return self.facade.cancel(profile, oid, proof)

    def status(self, profile, oid, proof):
        return self.facade.status(profile, oid, proof)

    def audit(self, profile, oid, proof):
        return self.facade.audit(profile, oid, proof)

    def counts(self):
        return self.facade.counts()

    # -- local fallback: answer a challenge through the configured signer ---
    def answer(self, profile, role, domain, claim):
        """Return a ``{claim, signature}`` proof for a handed-out challenge."""
        return {'claim': claim, 'signature': self.signer.sign(profile, role, domain, claim)}

    # -- orchestration: one normal path, end to end -------------------------
    def run_normal(self, profile, action=None):
        """Drive build_op -> prepare -> accept -> claim -> execute -> settle -> status.

        Each step is the interface: request the challenge, answer it (local
        fallback this round), then submit the proof.
        """
        base = self.run.operations[profile]
        op = self.build_op(profile, action or base['action'], base['task_id'], base['scene_key'])
        oid = op['action']['operation_id']
        guard = self.challenge(profile, op)
        ticket = self.prepare(profile, op, self.answer(profile, 'H', GUARD_DOMAIN, guard))
        acc = self.challenge_accept(profile, ticket['ticket_id'])
        self.accept(profile, ticket['ticket_id'], self.answer(profile, 'H', ACCEPT_DOMAIN, acc))
        claim = self.challenge_worker(profile, oid, 'CLAIM')
        self.claim(profile, oid, self.answer(profile, 'worker', WORKER_DOMAIN, claim))
        execute = self.challenge_worker(profile, oid, 'EXECUTE')
        response = self.execute_once(profile, oid, self.answer(profile, 'worker', WORKER_DOMAIN, execute))
        settle = self.challenge_worker(profile, oid, 'SETTLE')
        settled = self.settle(profile, oid, response, self.answer(profile, 'worker', WORKER_DOMAIN, settle))
        read = self.challenge_read(profile, oid, 'STATUS')
        view = self.status(profile, oid, self.answer(profile, 'H', READ_DOMAIN, read))
        return {'op': op, 'operation_id': oid, 'ticket': ticket, 'response': response,
                'settled': settled, 'status': view}
