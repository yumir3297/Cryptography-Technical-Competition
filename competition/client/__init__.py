"""The signing face: an external signing client per role.

The trusted side (``competition/server``) never has to hold a role's private key.
It hands out a challenge; a role client answers with the signature of
``canonical([domain, claim])`` -- but only for the one profile, the one role and
the handful of domains it was built for.  Everything else is refused loudly.

Five pieces, layered so each can be tested alone:

``keys``
    :func:`~competition.client.keys.generate` -- the endpoint makes its own key
    pair, keeps the private half as its own exclusive 0600 file, and hands back
    only the public metadata a roster manifest carries.
``signer``
    :class:`~competition.client.signer.RoleSigner` -- one key, one binding, one
    domain whitelist.  Implements :class:`competition.server.signer.Signer`, so
    the trusted service is unchanged whether it is answered locally
    (:class:`~competition.server.signer.LocalSigner`) or externally.
``host``
    the line protocol that carries ``{profile, role, domain, claim}`` (or the
    ``raw`` / ``enrollment`` ops) in and ``{signature}`` out, modelled on
    :mod:`competition.support.broker_policy`.
``web``
    the same protocol over HTTP: one route that hands the request body to the
    same ``host.answer``, plus the endpoint's own ``/healthz``, ``/identity`` and
    ``/check-package``.
``package``
    :func:`~competition.client.package.check` -- the other end of the hand-off:
    read the trusted side's public package and check that this endpoint was
    registered as exactly what it announced, and no more.
``__main__``
    the process entry point: generate the credential, check the registration, or
    pick the role, load its own 0600 credential, serve.

A client that cannot sign is far less dangerous than one that signs something it
was never meant to, so every refusal is an exception, never a silent empty
answer.
"""
