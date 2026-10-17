"""Abstract minimal-input interface to the competition core.

A frontend or bridge depends only on this Protocol; the concrete trusted
implementations are adapted in :mod:`competition.bridge.facade`.  The interface
carries the smallest inputs the core actually needs from a caller: a profile and
an operation id.  Every other wire field is owned by the shell (see
:mod:`competition.bridge.defaults`).
"""
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class CompetitionFacade(Protocol):
    """Intent-only operations over the unchanged trusted core."""

    def prepare(self, profile: str) -> dict:
        """Form a fresh candidate chain and an unsigned acceptance ticket."""
        ...

    def accept(self, profile: str, operation_id: str) -> dict:
        """Accept the prepared operation; returns the acceptance view."""
        ...

    def claim(self, profile: str, operation_id: str) -> dict:
        """Claim the single tool dispatch attempt."""
        ...

    def execute_once(self, profile: str, operation_id: str) -> dict:
        """Consume the one execution entitlement and send the tool request."""
        ...

    def query_attempt(self, profile: str, operation_id: str) -> dict:
        """Re-authenticate a query of the same attempt; never re-executes."""
        ...

    def settle(self, profile: str, operation_id: str,
               response: Optional[dict] = None) -> dict:
        """Settle from a final response; reuses the last observed response."""
        ...

    def cancel(self, profile: str, operation_id: str) -> dict:
        """Cancel an unclaimed operation that is invalid under current rules."""
        ...

    def status(self, profile: str, operation_id: str) -> dict:
        """Authenticated single-operation projection."""
        ...

    def audit(self, profile: str, operation_id: str) -> dict:
        """Authenticated projection plus commit, witnesses and evidence."""
        ...

    def counts(self) -> dict:
        """Whole-W summary counters."""
        ...
