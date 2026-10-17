"""Explicit interface to the competition core.

A frontend or bridge depends only on this Protocol; the concrete trusted
implementation is :mod:`competition.bridge.facade`.  Every operation mirrors the
core's own signature and the core's own challenge/signature separation: a caller
owns its keys, requests a challenge, signs it and passes the proof back.  The
shell forwards verbatim and never signs on the caller's behalf.

The single assembly method, :meth:`CompetitionFacade.build_op`, turns a candidate
Action plus its business context into the full signed request the core requires,
so a caller supplies intent while every derived field stays trusted.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class CompetitionFacade(Protocol):
    """Explicit, challenge/signature-separated operations over the trusted core."""

    def build_op(self, profile: str, action: dict, task_id: str, scene_key: list) -> dict:
        """Validate a candidate Action and assemble the full signed request."""
        ...

    def challenge(self, profile: str, op: dict) -> dict:
        """Issue the GUARD acceptance-identity challenge for an assembled request."""
        ...

    def prepare(self, profile: str, op: dict, proof: dict) -> dict:
        """Accept the caller's GUARD proof; returns the acceptance ticket."""
        ...

    def challenge_accept(self, profile: str, ticket: str) -> dict:
        """Issue the acceptance challenge for a ticket."""
        ...

    def accept(self, profile: str, ticket: str, proof: dict) -> dict:
        """Accept the prepared operation with the caller's proof."""
        ...

    def challenge_worker(self, profile: str, oid: str, purpose: str) -> dict:
        """Issue a worker challenge for CLAIM/EXECUTE/QUERY/SETTLE/CANCEL."""
        ...

    def claim(self, profile: str, oid: str, proof: dict) -> dict:
        """Claim the single tool dispatch attempt."""
        ...

    def execute_once(self, profile: str, oid: str, proof: dict) -> dict:
        """Consume the one execution entitlement and send the tool request."""
        ...

    def query_attempt(self, profile: str, oid: str, proof: dict) -> dict:
        """Re-authenticate a query of the same attempt; never re-executes."""
        ...

    def settle(self, profile: str, oid: str, response: dict, proof: dict) -> dict:
        """Settle from the caller-supplied final response."""
        ...

    def cancel(self, profile: str, oid: str, proof: dict) -> dict:
        """Cancel an unclaimed operation that is invalid under current rules."""
        ...

    def challenge_read(self, profile: str, oid: str, purpose: str = 'STATUS') -> dict:
        """Issue a read challenge for STATUS or AUDIT."""
        ...

    def status(self, profile: str, oid: str, proof: dict) -> dict:
        """Authenticated single-operation projection."""
        ...

    def audit(self, profile: str, oid: str, proof: dict) -> dict:
        """Authenticated projection plus commit, witnesses and evidence."""
        ...

    def counts(self) -> dict:
        """Whole-W summary counters. Not a caller-authenticated query."""
        ...
