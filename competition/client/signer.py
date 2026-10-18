"""One role, one key, one bounded set of signing domains.

A role client is deliberately narrow.  It holds a single Ed25519 private key, it
is bound at construction time to a single ``(profile, role)``, and it will answer
only the challenge domains that role is allowed to sign.  The trusted side still
verifies every signature against its own roster -- this whitelist is a client-side
boundary, not the security boundary -- but a client that refuses a request it
never should have received is worth more than a client that quietly signs it.

The domains come from the trusted service's own tables
(:mod:`competition.server.service`), so the client and the server cannot drift
apart; the key file layout is the one the seeds write
(``<folder>/<profile>-<alias>.key``, ``<folder>/W-worker.key`` for the worker).

:class:`RoleSigner` satisfies :class:`competition.server.signer.Signer`, so
swapping the local fallback for external role clients changes no trusted code.
"""
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.core.trusted_state import PROFILE_SCOPES
from competition.server.service import (
    ACCEPT_DOMAIN, GUARD_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN, WORKER_DOMAIN,
)
from competition.support.wire import b64, canonical, keyid, require

# Which role may sign which domain.  ``H`` answers its own identity, acceptance
# and read challenges (and its in-chain caller proofs); every other roster alias
# signs only its own chain messages; the worker answers only the W step
# challenges; ``E`` signs no approval in this flow, so it may sign nothing.
ROLE_DOMAINS = {
    'H': frozenset({GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN}),
    'U': frozenset({SIGN_CALL_DOMAIN}),
    'V': frozenset({SIGN_CALL_DOMAIN}),
    'G': frozenset({SIGN_CALL_DOMAIN}),
    'X': frozenset({SIGN_CALL_DOMAIN}),
    'worker': frozenset({WORKER_DOMAIN}),
    'E': frozenset(),
}


def role_key_path(folder, profile, role):
    """The key file a role owns: ``<profile>-<alias>.key``, ``W-worker.key`` for worker."""
    require(role in ROLE_DOMAINS, 'CLIENT_ROLE')
    name = 'W-worker.key' if role == 'worker' else profile + '-' + role + '.key'
    return Path(folder) / name


def load_role_key(path):
    """Load one role's Ed25519 key, refusing anything its own uid does not own as 0600.

    A role credential is a process credential: a file another user can read, or
    one this process does not own, is not a key this process may use.
    """
    require(os.name == 'posix', 'LINUX_ONLY')
    path = Path(path)
    status = path.stat()
    require(status.st_uid == os.geteuid() and (status.st_mode & 0o777) == 0o600,
            'CLIENT_KEY_OWNER')
    raw_key = path.read_bytes()
    require(len(raw_key) == 32, 'CLIENT_KEY_FORMAT')
    return Ed25519PrivateKey.from_private_bytes(raw_key)


class RoleSigner:
    """Sign with exactly one role key, in exactly the domains that role may sign."""

    def __init__(self, profile, role, key_path):
        require(profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
        require(role in ROLE_DOMAINS, 'CLIENT_ROLE')
        self.profile = profile
        self.role = role
        self.domains = ROLE_DOMAINS[role]
        self.key_path = str(Path(key_path))
        self.key = load_role_key(key_path)
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.kid = keyid(self.public)

    @classmethod
    def from_directory(cls, folder, profile, role):
        """Bind to the conventional key file ``folder`` holds for ``(profile, role)``."""
        return cls(profile, role, role_key_path(folder, profile, role))

    def sign(self, profile, role, domain, claim):
        """Answer one challenge, or refuse -- never a silent empty answer.

        Refuses a request for another profile or role, a domain outside this
        role's whitelist, and a claim that names a profile other than this one.
        """
        require(profile == self.profile and role == self.role, 'CLIENT_BINDING')
        require(domain in self.domains, 'CLIENT_DOMAIN')
        require(type(claim) is dict, 'CLIENT_CLAIM')
        require(claim.get('profile', self.profile) == self.profile, 'CLIENT_BINDING')
        return b64(self.key.sign(canonical([domain, claim])))

    def __call__(self, profile, role, domain, claim):
        """The in-chain seam (``AuthorizationRun.signature``) is a plain callable.

        Assigning a role client to ``AuthorizationRun.signer`` therefore uses the
        same single decision point as :meth:`sign` -- there is no second path.
        """
        return self.sign(profile, role, domain, claim)
