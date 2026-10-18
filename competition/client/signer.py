"""One role, one key, one bounded set of signing domains.

A role client is deliberately narrow.  It holds a single Ed25519 private key, it
is bound at construction time to a single ``(profile, role)``, and it will answer
only the signing domains that role is allowed to sign.  The trusted side still
verifies every signature against its own roster -- this whitelist is a client-side
boundary, not the security boundary -- but a client that refuses a request it
never should have received is worth more than a client that quietly signs it.

A role really signs three shapes, and each has its own door here:

``sign``
    one challenge: ``canonical([domain, claim])``, the step and caller-proof face.
``sign_raw``
    the opaque canonical bytes an in-chain caller hands over -- the broker's
    envelope signature, E's source attestation, X's receipt.  The domain is read
    back off the decoded payload instead of being taken on trust.
``sign_enrollment``
    one possession proof, in the exact shape the black box verifies.

The domains come from the trusted service's own tables
(:mod:`competition.server.service`) and from the repository's own
``ZJJ-SIG-v1`` / ``ZJJ-SOURCE-v1`` envelope domains; the key file layout is the
one the seeds write (``<folder>/<profile>-<alias>.key``, ``<folder>/W-worker.key``
for the worker).

:class:`RoleSigner` satisfies :class:`competition.server.signer.Signer`, so
swapping the local fallback for external role clients changes no trusted code.
"""
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.client.keys import key_file_name
from competition.core.trusted_state import PROFILE_SCOPES
from competition.server.service import (
    ACCEPT_DOMAIN, GUARD_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN, WORKER_DOMAIN,
)
from competition.support.wire import b64, canonical, keyid, load_canonical, require

# The envelope domain every roster alias signs its own chain messages under
# (``competition.core.signer_broker``), and the domain ``E`` signs its own source
# evidence under (``competition.profiles.scene_seed``).
CHAIN_DOMAIN = 'ZJJ-SIG-v1'
SOURCE_DOMAIN = 'ZJJ-SOURCE-v1'
# The possession-proof domain; the shape is the black box's, never redefined here.
ENROLL_DOMAIN = 'ZJJ-ENROLL-v1'

# Which role may sign which domain.  ``H`` answers its own identity, acceptance
# and read challenges (and its in-chain caller proofs); every other roster alias
# signs its own chain messages; the worker answers only the W step challenges.
# ``E`` signs no approval in this flow -- only its own source evidence, whose shape
# is the seven-element ``ZJJ-SOURCE-v1`` message or, in PAY-1, an envelope.  Every
# alias also signs its own possession proof, which :meth:`RoleSigner.sign_raw`
# accepts only when the tuple really names that key.
ROLE_DOMAINS = {
    'H': frozenset({GUARD_DOMAIN, ACCEPT_DOMAIN, READ_DOMAIN, SIGN_CALL_DOMAIN,
                    CHAIN_DOMAIN, ENROLL_DOMAIN}),
    'U': frozenset({SIGN_CALL_DOMAIN, CHAIN_DOMAIN, ENROLL_DOMAIN}),
    'V': frozenset({SIGN_CALL_DOMAIN, CHAIN_DOMAIN, ENROLL_DOMAIN}),
    'G': frozenset({SIGN_CALL_DOMAIN, CHAIN_DOMAIN, ENROLL_DOMAIN}),
    'X': frozenset({SIGN_CALL_DOMAIN, CHAIN_DOMAIN, ENROLL_DOMAIN}),
    'worker': frozenset({WORKER_DOMAIN}),
    'E': frozenset({SOURCE_DOMAIN, CHAIN_DOMAIN, ENROLL_DOMAIN}),
}


def role_key_path(folder, profile, role):
    """The key file a role owns: ``<profile>-<alias>.key``, ``W-worker.key`` for worker."""
    require(role in ROLE_DOMAINS, 'CLIENT_ROLE')
    return Path(folder) / key_file_name(profile, role)


def enrollment_message(tup, enrollment_id, nonce, iat, exp):
    """The exact possession message the black box verifies.

    ``competition.support.enrollment`` and ``competition.core.trusted_state``
    both check this seven-element shape; the client signs it rather than
    redefining it.
    """
    return canonical([ENROLL_DOMAIN, '2.6', tup, enrollment_id, nonce, str(iat), str(exp)])


def split_message(data):
    """The ``[domain, ...]`` list a signing request must be, or a refusal.

    The client signs opaque canonical bytes; reading the domain off the front of
    the decoded list is all it needs to know about the shape.
    """
    value = load_canonical(data)
    require(type(value) is list and len(value) >= 2 and type(value[0]) is str, 'CLIENT_MESSAGE')
    return value[0], value


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
    """Sign with exactly one role key, in exactly the domains that role may sign.

    The one endpoint not bound to a profile is the worker: its certificate covers
    every profile and it answers every profile's step challenges, so it names
    none.  Every other role is bound to exactly one profile.
    """

    def __init__(self, profile, role, key_path):
        require(role in ROLE_DOMAINS, 'CLIENT_ROLE')
        require(role == 'worker' or profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
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

    def _bound(self, profile, role):
        """Refuse a request for another role, or a profile this endpoint does not own."""
        require(role == self.role and (self.profile is None or profile == self.profile),
                'CLIENT_BINDING')

    def sign(self, profile, role, domain, claim):
        """Answer one challenge, or refuse -- never a silent empty answer.

        Refuses a request for another profile or role, a domain outside this
        role's whitelist, and a claim that names a profile other than this one.
        """
        self._bound(profile, role)
        require(domain in self.domains, 'CLIENT_DOMAIN')
        require(type(claim) is dict, 'CLIENT_CLAIM')
        require(claim.get('profile', profile) == profile, 'CLIENT_BINDING')
        return b64(self.key.sign(canonical([domain, claim])))

    def __call__(self, profile, role, domain, claim):
        """The in-chain seam (``AuthorizationRun.signature``) is a plain callable.

        Assigning a role client to ``AuthorizationRun.signer`` therefore uses the
        same single decision point as :meth:`sign` -- there is no second path.
        """
        return self.sign(profile, role, domain, claim)

    def proves_own_key(self, tup):
        """Refuse a possession tuple that is not about this key, in this scope.

        The scope, public key and key id all come back from the trusted side
        inside the tuple; an applicant handed a proof for somebody else's key
        refuses instead of claiming possession it does not have.
        """
        require(self.profile is not None, 'CLIENT_BINDING')
        require(type(tup) is dict and tup.get('scope') == PROFILE_SCOPES[self.profile],
                'CLIENT_SCOPE')
        require(tup.get('public_key') == b64(self.public) and tup.get('kid') == self.kid,
                'CLIENT_KEY_BINDING')

    def sign_raw(self, profile, role, data):
        """Sign exactly the canonical bytes a caller hands over, if the domain fits.

        This is the seam the in-chain signing paths use: the broker's envelope
        signature (``competition.core.signer_broker``), ``E``'s source attestation,
        ``X``'s receipt and the possession proof the bootstrap publishes with its
        grants.  The client re-derives the domain from the payload instead of
        trusting a label, refuses anything outside its whitelist, and never
        re-encodes what it was handed.

        The ``(profile, role)`` binding is checked here, but the profile a chain
        message names is not: an opaque payload has no shape the client may assume.
        What closes that gap is the trusted side's own roster -- each profile's
        roster holds its own aliases' key ids, so a signature produced for the
        wrong profile is rejected where it is used, not here.  The one shape this
        client does understand is its own possession proof, and that it checks.
        """
        self._bound(profile, role)
        domain, value = split_message(data)
        require(domain in self.domains, 'CLIENT_DOMAIN')
        if domain == ENROLL_DOMAIN:
            require(len(value) == 7, 'CLIENT_MESSAGE')
            self.proves_own_key(value[2])
        return b64(self.key.sign(data))

    def sign_enrollment(self, profile, role, pending, iat, exp):
        """Sign one possession proof -- and only for a pending about this key."""
        self._bound(profile, role)
        require(type(pending) is dict and set(pending) == {'tuple', 'enrollment_id', 'nonce'},
                'CLIENT_PENDING')
        self.proves_own_key(pending['tuple'])
        return b64(self.key.sign(enrollment_message(
            tup=pending['tuple'], enrollment_id=pending['enrollment_id'],
            nonce=pending['nonce'], iat=iat, exp=exp)))
