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
from competition.server.roster import ENDPOINTS, key_file_name
from competition.support.wire import b64, keyid, require, sortset


def propose_subject(profile, role):
    """The subject an endpoint proposes for itself when it announces its key.

    A proposal is a name, never an authority: the trusted side re-derives what a
    roster alias may do from its own tables before a key can enter a roster.
    """
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    if role == 'worker':
        # One worker capability serves every profile, so it names no profile.
        return 'competition-worker'
    require(profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
    if role == 'tool':
        return 'competition-tool-' + profile.lower()
    return 'auth-' + PROFILE_SCOPES[profile]['scenario'] + '-' + role.lower()


def propose_purposes(role):
    """The purposes an endpoint proposes for itself; the trusted side validates.

    Only a roster alias has roster purposes.  The worker and the tool hold a
    capability whose terms come from the certificate the root signs, not from
    their own manifest line, so they propose none.
    """
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    return sortset(list(TYPES[role] + ('READ',))) if role in TYPES else []


def write_key(path, key):
    """Write one private key exclusively as this process's own 0600 credential."""
    require(os.name == 'posix', 'LINUX_ONLY')
    with Path(path).open('xb') as stream:
        stream.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    os.chmod(path, 0o600)


def metadata(profile, role, public, *, name=None):
    """The public-only manifest entry for one endpoint's key."""
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    require(role == 'worker' or profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
    require(type(public) is bytes and len(public) == 32, 'CLIENT_KEY_FORMAT')
    entry = {'role': role, 'subject': name or propose_subject(profile, role),
             'public_key': b64(public), 'kid': keyid(public),
             'purposes': propose_purposes(role)}
    if role != 'worker':
        entry['profile'] = profile
    return entry


def generate(folder, profile, role, *, name=None):
    """Generate one endpoint's own key and return only its public metadata.

    Refuses to replace an existing credential -- the file is created exclusively
    -- and the private half is never returned, logged or transported.
    """
    require(role in ENDPOINTS, 'CLIENT_ROLE')
    require(role == 'worker' or profile in PROFILE_SCOPES, 'CLIENT_PROFILE')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / key_file_name(profile, role)
    key = Ed25519PrivateKey.generate()
    write_key(path, key)
    return metadata(profile, role,
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), name=name)
