"""The caller-side signing interface, plus a local fallback implementation.

A real deployment runs this interface outside the trusted host: one client per
role, each holding its own key, answering the challenges the trusted side hands
out.  This round uses :class:`LocalSigner` -- the trusted side signs locally with
the run's own role keys (the documented "bootstrap holds role keys to generate
real input") -- so the three normal paths run end to end.  When external role
clients are connected they implement the same :class:`Signer` protocol and the
service does not change.
"""
from typing import Protocol, runtime_checkable

from competition.support.wire import b64, canonical


@runtime_checkable
class Signer(Protocol):
    """Answers one challenge: sign ``canonical([domain, claim])`` with the
    caller's own key for ``role`` and return the base64 Ed25519 signature."""

    def sign(self, profile: str, role: str, domain: str, claim: dict) -> str:
        ...


class LocalSigner:
    """Local fallback: sign with the trusted run's own role keys.

    ``role`` is a roster alias (``H``/``U``/``V``/``G``/``X``/``E``) or ``worker``.
    """

    def __init__(self, run):
        self._run = run

    def sign(self, profile, role, domain, claim):
        key = self._run.worker_key if role == 'worker' else self._run.actors[profile][role].key
        return b64(key.sign(canonical([domain, claim])))
