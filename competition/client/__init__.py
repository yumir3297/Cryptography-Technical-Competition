"""The signing face: an external signing client per role.

The trusted side (``competition/server``) never has to hold a role's private key.
It hands out a challenge; a role client answers with the signature of
``canonical([domain, claim])`` -- but only for the one profile, the one role and
the handful of domains it was built for.  Everything else is refused loudly.

Three pieces, layered so each can be tested alone:

``signer``
    :class:`~competition.client.signer.RoleSigner` -- one key, one binding, one
    domain whitelist.  Implements :class:`competition.server.signer.Signer`, so
    the trusted service is unchanged whether it is answered locally
    (:class:`~competition.server.signer.LocalSigner`) or externally.
``host``
    the line protocol that carries ``{profile, role, domain, claim}`` in and
    ``{signature}`` out, modelled on :mod:`competition.support.broker_policy`.
``__main__``
    the process entry point: pick the role, load its own 0600 credential, serve.

A client that cannot sign is far less dangerous than one that signs something it
was never meant to, so every refusal is an exception, never a silent empty
answer.
"""
