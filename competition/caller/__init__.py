"""A business caller: its own key, a session, and the steps it is allowed to drive.

The endpoints hold the roles and sign for them.  A caller is the other side of the
exchange -- the thing that actually walks a flow: proposing an operation, reading
its state, and carrying each challenge to the endpoint that owns that step and
the signature back to the entry.

It holds no role key and produces no business signature.  What it has is a
credential of its own, which the deployment lists so the entry knows who is
asking (see :mod:`competition.web.session`), plus the entry's own routing, which
tells it which endpoint a step belongs to and which the endpoint confirms.

``session``
    :class:`~competition.caller.session.Session` -- the credential, the entry and
    the bearer token between them.
``flow``
    :class:`~competition.caller.flow.Caller` -- submitting, reading, and the
    explicit two-move a step is: ask, get it signed where it belongs, hand it back.
``__main__``
    the process entry point: make this caller's credential, or drive the one side
    of the flow it was listed for.
"""
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.client.keys import write_key
from competition.support.wire import b64, is_id, require, sortset
from competition.web.session import SIDES


def key_file_name(name):
    """The file a caller keeps its own credential in."""
    require(is_id(name), 'CALLER_NAME')
    return name + '.key'


def generate(folder, name, sides):
    """Make one caller's own key; returns the allowlist line the deployment needs.

    Refuses to replace an existing credential, and the private half is never
    returned, logged or transported -- the same rule the endpoints are held to.
    The sides are a proposal: what a caller may actually drive is decided by the
    allowlist the trusted entry reads, not by this line.
    """
    require(is_id(name), 'CALLER_NAME')
    require(type(sides) is list and sides and len(set(sides)) == len(sides)
            and set(sides) <= set(SIDES), 'SESSION_SIDES')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    write_key(folder / key_file_name(name), key)
    return {'name': name,
            'public_key': b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)),
            'sides': sortset(sides)}
