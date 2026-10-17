"""Concrete adapter letting the unchanged trusted core satisfy the contract.

The shell composes the existing trusted bootstrap (``WRun``), ``CommonW`` and the
data-only ``CandidateIngress``; it modifies none of them.  It fills every
shell-owned wire field from the trusted fixed corpus and backfills the fields the
core re-derives, so a caller supplies only a profile and an operation id.
"""
from pathlib import Path
from typing import Optional

from competition.core.candidate_ingress import CandidateIngress
from competition.support.wire import canonical, require

ROOT = Path(__file__).resolve().parents[2]


class TrustedFacade:
    """Same-process shell over an initialized ``WRun``.

    Ticket and tool responses are remembered per ``(profile, operation_id)`` so
    the contract stays minimal; a fresh process simply calls ``prepare`` again.
    """

    def __init__(self, run, *, ingress=None):
        self._run = run
        self._ingress = ingress if ingress is not None else CandidateIngress(ROOT)
        self._tickets = {}
        self._responses = {}

    # -- data-only candidate edge (the agent boundary; grants nothing) -------
    def submit(self, profile, action):
        """Validate a candidate Action through the strict ingress; no authority."""
        return self._ingress.parse(profile, canonical(action))

    # -- acceptance ---------------------------------------------------------
    def prepare(self, profile):
        op = self._run.fork_operation(profile)
        operation_id = op['action']['operation_id']
        ticket = self._run.w.prepare(profile, op, self._run.identity_proof(profile, op))
        self._tickets[(profile, operation_id)] = ticket['ticket_id']
        return ticket

    def accept(self, profile, operation_id):
        ticket = self._ticket(profile, operation_id)
        proof = self._run.accept_proof(profile, ticket)
        return self._run.w.accept(profile, ticket, proof)

    # -- single execution attempt ------------------------------------------
    def claim(self, profile, operation_id):
        proof = self._run.worker_proof(profile, operation_id, 'CLAIM')
        return self._run.w.claim(profile, operation_id, proof)

    def execute_once(self, profile, operation_id):
        proof = self._run.worker_proof(profile, operation_id, 'EXECUTE')
        response = self._run.w.execute_once(profile, operation_id, proof)
        self._responses[(profile, operation_id)] = response
        return response

    def query_attempt(self, profile, operation_id):
        proof = self._run.worker_proof(profile, operation_id, 'QUERY')
        response = self._run.w.query_attempt(profile, operation_id, proof)
        self._responses[(profile, operation_id)] = response
        return response

    def settle(self, profile, operation_id, response=None):
        if response is None:
            response = self._responses.get((profile, operation_id))
        require(response is not None, 'NO_TOOL_RESPONSE')
        proof = self._run.worker_proof(profile, operation_id, 'SETTLE')
        return self._run.w.settle(profile, operation_id, response, proof)

    def cancel(self, profile, operation_id):
        proof = self._run.worker_proof(profile, operation_id, 'CANCEL')
        return self._run.w.cancel(profile, operation_id, proof)

    # -- authenticated reads ------------------------------------------------
    def status(self, profile, operation_id):
        return self._run.w.status(profile, operation_id,
                                  self._run.read_proof(profile, operation_id, 'STATUS'))

    def audit(self, profile, operation_id):
        return self._run.w.audit(profile, operation_id,
                                 self._run.read_proof(profile, operation_id, 'AUDIT'))

    def counts(self):
        return self._run.w.counts()

    # -- internal -----------------------------------------------------------
    def _ticket(self, profile, operation_id):
        ticket = self._tickets.get((profile, operation_id))
        require(ticket is not None, 'TICKET_UNKNOWN')
        return ticket
