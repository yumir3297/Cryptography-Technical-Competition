"""This caller's credential, and the session it opens with the trusted entry.

One key, one entry, one token.  Opening a session is a challenge and a proof, the
same two moves every other authentication in this repository is: the entry hands
out a nonce, the caller signs it with the key it holds, and the entry answers
with a bearer token that the rest of the calls carry.

The credential is loaded the same way an endpoint's is -- its own uid, mode
``0600``, nothing else -- because it is the same kind of thing: a process
credential that proves which party is acting.
"""
import os

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.client.signer import load_role_key
from competition.support.wire import WINDOW, ProtocolError, b64, canonical, keyid, require
from competition.web.session import SESSION_DOMAIN

# One entry call carries an intent or a proof, and the entry bounds its own side;
# this is only how long a caller waits before calling the entry unavailable.
#
# Most calls are answered at once, but one is not: a submit asks the trusted side
# to gather a fresh approval chain, and with the waiting room on that chain the
# answer waits for a person -- the room's own patience, which follows ``WINDOW``.
# A caller that gave up first would call the entry unavailable while it was still
# assembling, which is a fact about the caller and not about the entry.  So the
# default is the room's patience plus a margin, and a deployment may set its own.
TIMEOUT = float(os.environ.get('ZJJ_CALLER_TIMEOUT', str(WINDOW + 30)))


class Session:
    """One caller's session on the trusted entry."""

    def __init__(self, entry, key_path, *, timeout=TIMEOUT):
        self.entry = str(entry).rstrip('/')
        self.timeout = timeout
        self.key = load_role_key(key_path)
        self.kid = keyid(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        self.token = None
        self.caller = None

    def call(self, method, path, payload=None):
        """One call on the entry: the body back, or the rule name it refused under.

        A refusal is re-raised under the entry's own rule name, so a caller can
        tell "the entry would not take that" from "the entry was not there" --
        the same choice the trusted side makes about endpoints.
        """
        headers = {} if self.token is None else {'authorization': 'Bearer ' + self.token}
        try:
            reply = httpx.request(method, self.entry + path, json=payload, headers=headers,
                                  timeout=self.timeout)
        except httpx.HTTPError:
            raise ProtocolError('ENTRY_UNAVAILABLE')
        try:
            body = reply.json()
        except ValueError:
            raise ProtocolError('ENTRY_ANSWER')
        if reply.status_code != 200:
            code = body.get('deny') if type(body) is dict else None
            raise ProtocolError(code if type(code) is str else 'ENTRY_DENY')
        require(type(body) is dict, 'ENTRY_ANSWER')
        return body

    def open(self):
        """Prove the key this caller holds and keep the token that comes back."""
        challenge = self.call('POST', '/session', {'kid': self.kid})['challenge']
        opened = self.call('POST', '/session/prove',
                           {'claim': challenge,
                            'signature': b64(self.key.sign(canonical([SESSION_DOMAIN,
                                                                     challenge])))})
        self.token = opened['token']
        self.caller = opened['caller']
        return opened
