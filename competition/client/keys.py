"""Key generation for one endpoint: the private half never leaves this machine.

The rest of the client package answers challenges with a key; this module makes
that key.  One endpoint -- a roster alias, the worker, or a profile tool --
generates its own Ed25519 pair here, writes the private half once as its own
exclusive ``0600`` file, and returns **only** the public metadata a roster
manifest carries: ``{profile, role, subject, public_key, kid, purposes}``.

That is the whole "the private key never travels" rule: the trusted side collects
public keys, and every signature still comes back over the challenge protocol in
:mod:`competition.client.host`.

The file layout is the one the seeds already write and
:class:`~competition.client.signer.RoleSigner` already reads, so a key made here
is immediately a client: ``<profile>-<alias>.key``, ``W-worker.key`` for the
worker, ``<profile>-tool.key`` for the tool.
"""
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from competition.core.trusted_state import PROFILE_SCOPES, TYPES
from competition.support.wire import b64, keyid, require

# Every endpoint that owns a credential: each roster alias, plus the worker and
# the per-profile tool -- a capability rather than a business role, but still a
# key generated at the endpoint and published as a public only.
ENDPOINTS = tuple(sorted(TYPES)) + ('tool', 'worker')

# The purposes the worker's own certificate carries, as
# ``competition.profiles.w_seed`` writes them.
WORKER_PURPOSES = ('AUDIT', 'CANCEL', 'CLAIM', 'EXECUTE', 'QUERY', 'RECEIPT', 'SETTLE')


def key_file_name(profile, role):
    """The file an endpoint of this kind owns."""
    require(profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    if role == 'worker':
        return 'W-worker.key'
    if role == 'tool':
        return profile + '-tool.key'
    return profile + '-' + role + '.key'


def propose_subject(profile, role):
    """The subject an endpoint proposes for itself when it announces its key.

    A proposal is a name, never an authority: the trusted side checks it against
    its own tables before the key can enter a roster.
    """
    require(profile in PROFILE_SCOPES and role in ENDPOINTS, 'CLIENT_ROLE')
    if role == 'worker':
        return 'competition-worker'
    if role == 'tool':
        return 'competition-tool-' + profile.lower()
    return 'auth-' + PROFILE_SCOPES[profile]['scenario'] + '-' + role.lower()


def propose_purposes(role):
    """The purposes an endpoint proposes for itself; the trusted side validates."""
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    if role == 'worker':
        return sorted(WORKER_PURPOSES)
    if role == 'tool':
        return []
    return sorted(TYPES[role] + ('READ',))


def write_key(path, key):
    """Write one private key exclusively as this process's own 0600 credential."""
    require(os.name == 'posix', 'LINUX_ONLY')
    with Path(path).open('xb') as stream:
        stream.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    os.chmod(path, 0o600)


def metadata(profile, role, public, *, name=None):
    """The public-only manifest entry for one endpoint's key."""
    require(profile in PROFILE_SCOPES and role in ENDPOINTS, 'CLIENT_ROLE')
    require(type(public) is bytes and len(public) == 32, 'CLIENT_KEY_FORMAT')
    return {'profile': profile, 'role': role, 'subject': name or propose_subject(profile, role),
            'public_key': b64(public), 'kid': keyid(public),
            'purposes': propose_purposes(role)}


def generate(folder, profile, role, *, name=None):
    """Generate one endpoint's own key and return only its public metadata.

    Refuses to replace an existing credential -- the file is created exclusively
    -- and the private half is never returned, logged or transported.
    """
    path = Path(folder) / key_file_name(profile, role)
    key = Ed25519PrivateKey.generate()
    write_key(path, key)
    return metadata(profile, role,
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), name=name)
