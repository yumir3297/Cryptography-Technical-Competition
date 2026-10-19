"""Concrete adapter letting the unchanged trusted core satisfy the contract.

Every method mirrors the trusted core's own signature and forwards verbatim; the
shell neither signs nor remembers anything for the caller.  The caller holds and
passes ``op``/``ticket``/``oid``/``proof`` explicitly.  The only method that adds
logic is :meth:`TrustedFacade.build_op`: it validates a candidate Action and
assembles the full signed request the core requires, so a caller supplies the
Action and its context while every derived field and approval is filled by the
unchanged trusted host.
"""
import copy
from pathlib import Path

from competition.core.candidate_ingress import CandidateIngress
from competition.support.wire import canonical

ROOT = Path(__file__).resolve().parents[2]


class TrustedFacade:
    """Explicit forwarding shell over an initialized ``WRun``."""

    def __init__(self, run, *, ingress=None):
        self._run = run
        self._ingress = ingress if ingress is not None else CandidateIngress(ROOT)

    # -- assembly: caller Action -> full signed request (the only logic) -----
    def build_op(self, profile, action, task_id, scene_key, *, operation_id=None):
        """Validate a candidate Action and assemble the full signed request.

        The Action passes the strict candidate ingress first; the caller then
        supplies only the business context (task and scene).  Every other wire
        field -- the derived basis/assessment/required/deps and the trusted
        approval chain -- is rebuilt by the trusted host, never taken from the
        caller.

        ``operation_id`` pins the id the assembled operation will have.  A caller
        that wants to report the candidate before assembly passes one; one that
        does not gets a fresh id from the fork, which is what every other caller
        of this method does.
        """
        action = self._ingress.parse(profile, canonical(action))
        base = self._run.operations[profile]
        op = {'action': action, 'task_id': task_id, 'scene_key': scene_key,
              'assessment': copy.deepcopy(base['assessment'])}
        return self._run.fork_operation(profile, op, operation_id=operation_id)

    # -- acceptance ---------------------------------------------------------
    def challenge(self, profile, op):
        """Issue the GUARD acceptance-identity challenge for an assembled request."""
        return self._run.store.challenge(profile, op, 'GUARD')

    def prepare(self, profile, op, proof):
        """Accept the caller's GUARD proof; returns the acceptance ticket."""
        return self._run.w.prepare(profile, op, proof)

    def challenge_accept(self, profile, ticket):
        """Issue the acceptance challenge for a ticket."""
        return self._run.w.challenge_accept(profile, ticket)

    def accept(self, profile, ticket, proof):
        """Accept the prepared operation with the caller's proof."""
        return self._run.w.accept(profile, ticket, proof)

    # -- single execution attempt ------------------------------------------
    def challenge_worker(self, profile, oid, purpose):
        """Issue a worker challenge for CLAIM/EXECUTE/QUERY/SETTLE/CANCEL."""
        return self._run.w.challenge_worker(profile, oid, purpose)

    def claim(self, profile, oid, proof):
        """Claim the single tool dispatch attempt."""
        return self._run.w.claim(profile, oid, proof)

    def execute_once(self, profile, oid, proof):
        """Consume the one execution entitlement and send the tool request."""
        return self._run.w.execute_once(profile, oid, proof)

    def query_attempt(self, profile, oid, proof):
        """Re-authenticate a query of the same attempt; never re-executes."""
        return self._run.w.query_attempt(profile, oid, proof)

    def settle(self, profile, oid, response, proof):
        """Settle from the caller-supplied final response."""
        return self._run.w.settle(profile, oid, response, proof)

    def cancel(self, profile, oid, proof):
        """Cancel an unclaimed operation that is invalid under current rules."""
        return self._run.w.cancel(profile, oid, proof)

    # -- authenticated reads ------------------------------------------------
    def challenge_read(self, profile, oid, purpose='STATUS'):
        """Issue a read challenge for STATUS or AUDIT."""
        return self._run.w.challenge_read(profile, oid, purpose)

    def status(self, profile, oid, proof):
        """Authenticated single-operation projection."""
        return self._run.w.status(profile, oid, proof)

    def audit(self, profile, oid, proof):
        """Authenticated projection plus commit, witnesses and evidence."""
        return self._run.w.audit(profile, oid, proof)

    def counts(self):
        """Whole-W summary counters. Not a caller-authenticated query."""
        return self._run.w.counts()
