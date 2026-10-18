"""Sessions at the entry: prove a caller key once, carry a bearer token after.

The trusted service's own checks authenticate *business* steps -- every ``proof``
is a signature by the key registered for that step's role, and the black box
verifies it.  This is the layer in front of that, and it exists because reaching
the service at all costs something: a ``submit`` already asks the trusted side to
gather a whole fresh approval chain from the endpoints, so an entry has to know
who is asking before it lets the request through.

A caller is deliberately **not** a roster role.  It has its own key, the
deployment lists it by public key the way it lists the endpoints, and that list
is configuration rather than part of the protocol: nothing here signs anything
the protocol defines, and nothing here can produce a business signature -- only
the endpoints can, and only for their own roles.

What a session decides is *which side of the flow* its caller may drive.  The
repository's own ``STEPS`` table says who signs each step, so the session is held
to that same table: an entry allowed ``H`` cannot drive ``exec``, and one allowed
``worker`` cannot submit.  How many callers there are and what each may drive is
the deployment's choice, made in that list.

The two clocks are deliberately different.  Challenge and token lifetimes are
wall-clock bookkeeping for the entry itself, not a business fact: nothing here
is used as evidence of when anything happened, and the protocol's own event clock
is untouched.
"""
import json
import os
import time
from pathlib import Path

from competition.support.wire import (
    ProtocolError, b64, canonical, good_point, is_id, keyid, raw, require, sortset,
    strict_verify,
)

# The one domain this layer signs under.  It is not a protocol message: it exists
# so a caller can see, in the bytes it is asked to sign, that this is a session
# and not a business step.
SESSION_DOMAIN = 'ZJJ-SESSION-v1'
# How long a challenge stays good, and how long a token does.
CHALLENGE_TTL = 60
SESSION_TTL = 900
# The sides of the flow a caller may be allowed to drive; the same names
# ``competition.server.service.STEPS`` gives each step's signing role.
SIDES = ('H', 'worker')
CALLER_FIELDS = frozenset({'name', 'public_key', 'sides'})
CLAIM_FIELDS = frozenset({'caller', 'kid', 'nonce', 'iat', 'exp', 'domain'})


def read_callers(path):
    """Read the entry's caller allowlist: who may open a session, and for what.

    One caller per line, exactly as ``--keygen`` prints it, so a deployment
    collects the list the same way it collects the endpoint roster:
    ``>> callers.jsonl`` and no merge step.

    The key id is re-derived from the public key rather than read from the line,
    and the sides must be names this repository actually has -- the same "the
    holder proposes, the table decides" rule the endpoint roster is held to.
    """
    callers, names = {}, set()
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        raise ProtocolError('SESSION_CALLERS')
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            raise ProtocolError('SESSION_CALLERS')
        require(type(entry) is dict and set(entry) == CALLER_FIELDS, 'SESSION_CALLERS')
        require(is_id(entry['name']) and entry['name'] not in names, 'SESSION_CALLERS')
        pub = raw(entry['public_key'], 32)
        require(good_point(pub), 'PUBLIC_KEY_POINT')
        sides = entry['sides']
        require(type(sides) is list and sides and len(set(sides)) == len(sides)
                and set(sides) <= set(SIDES), 'SESSION_SIDES')
        kid = keyid(pub)
        require(kid not in callers, 'SESSION_CALLERS')
        callers[kid] = {'name': entry['name'], 'pub': pub, 'kid': kid,
                        'sides': tuple(sortset(sides))}
        names.add(entry['name'])
    require(callers, 'SESSION_CALLERS')
    return callers


class Sessions:
    """One entry's pending challenges and live tokens, over its caller list."""

    def __init__(self, callers, *, now=time.time, source=None):
        self.callers = dict(callers)
        self.source = source
        self.now = now
        self._pending = {}
        self._tokens = {}

    def _known(self, kid):
        """The caller that holds ``kid``, re-reading the list when it is not there.

        The list is deployment configuration, and a deployment can add a caller to
        it while it runs -- the same way the roster can enroll a subject later.  It
        is read again only when a key is unknown, so it costs one small file read
        on a request that was going to be refused anyway, and it means the entry
        never has to wait for its callers before it serves.
        """
        if kid in self.callers or self.source is None:
            return self.callers.get(kid)
        try:
            self.callers = read_callers(self.source)
        except ProtocolError:
            return None
        return self.callers.get(kid)

    def _prune(self, at):
        """Drop what has already expired, so neither table grows without bound.

        Called where entries are *added*, never on a lookup: a stale token or
        challenge has to keep reporting itself as expired rather than decaying
        into "never issued", because only the caller can tell those apart and
        only one of them means "prove your key again".
        """
        self._pending = {nonce: claim for nonce, claim in self._pending.items()
                         if int(claim['exp']) > at}
        self._tokens = {token: live for token, live in self._tokens.items()
                        if live[1] > at}

    def challenge(self, kid):
        """Hand out one session challenge to the caller that holds ``kid``.

        The caller names the key it holds; the allowlist, not the request, decides
        whether that key is a caller at all.
        """
        at = int(self.now())
        self._prune(at)
        caller = self._known(kid)
        require(caller is not None, 'SESSION_CALLER')
        claim = {'caller': caller['name'], 'kid': kid,
                 'nonce': b64(os.urandom(32)), 'domain': SESSION_DOMAIN,
                 'iat': str(at), 'exp': str(at + CHALLENGE_TTL)}
        self._pending[claim['nonce']] = claim
        return claim

    def open(self, claim, signature):
        """Verify one possession proof and hand back a bearer token.

        The challenge is consumed by this call whatever the outcome, so a replayed
        nonce or a signature made for a different caller cannot be retried into a
        session.
        """
        at = int(self.now())
        require(type(claim) is dict and set(claim) == CLAIM_FIELDS, 'SESSION_FIELDS')
        require(claim['domain'] == SESSION_DOMAIN, 'SESSION_DOMAIN')
        pending = self._pending.pop(claim.get('nonce'), None)
        require(pending is not None and claim == pending, 'SESSION_CHALLENGE')
        require(at < int(claim['exp']), 'SESSION_EXPIRED')
        caller = self._known(claim['kid'])
        require(caller is not None, 'SESSION_CALLER')
        strict_verify(caller['pub'], raw(signature, 64), canonical([SESSION_DOMAIN, claim]))
        token = b64(os.urandom(32))
        expires = at + SESSION_TTL
        self._tokens[token] = (caller, expires)
        self._prune(at)
        return {'token': token, 'caller': caller['name'], 'sides': list(caller['sides']),
                'expires': str(expires)}

    def authorize(self, token, side=None):
        """The caller behind ``token``, if that caller may drive ``side``.

        ``side`` is ``None`` for something every authenticated caller may do, such
        as reading the public package.
        """
        at = int(self.now())
        require(type(token) is str and token, 'SESSION_REQUIRED')
        live = self._tokens.get(token)
        require(live is not None, 'SESSION_REQUIRED')
        caller, expires = live
        require(at < expires, 'SESSION_EXPIRED')
        require(side is None or side in caller['sides'], 'SESSION_SIDE')
        return caller
