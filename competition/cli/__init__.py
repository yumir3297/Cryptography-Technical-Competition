"""Trusted-side interactive CLI over the challenge/signature interface.

Run it with ``python -m competition.cli`` (or ``python -m competition.server``).
It opens a fresh trusted single-host run and drives the
:class:`~competition.server.service.TrustedService` interface one call at a time.
Operations that need a signature first request the core's challenge, answer it
and pass the proof back; this round the answer comes from the local fallback
signer, and only it changes when external role clients are connected.
"""
