"""Driving a flow: submit, read, and hand each step to the endpoint that owns it.

A step is two moves, exactly as the interface defines them: ask the entry for the
challenge, hand the proof back.  The middle move is why a caller exists at all --
the signature comes from the endpoint that owns that role, and this module only
carries it.  The entry says which endpoint that is (role and domain travel back
with the claim, and the profile comes from the operation), so the caller keeps no
copy of a table that could drift.

What comes back is checked before it is forwarded.  A caller that relayed
whatever bytes arrived would be a blind relay; instead it re-verifies the
signature against the key the *published package* says the roster bound to that
place, so a wrong answer stops here instead of travelling on.  The trusted side
checks every signature again -- this check exists so the caller can tell, not so
the trusted side can rely on it.
"""
from competition.server.roster import HTTPTransport, endpoint_port
from competition.support import trace
from competition.support.wire import b64, canonical, raw, require, strict_verify


class EndpointSigner:
    """Ask one endpoint for a signature, and check what comes back."""

    def __init__(self, base_url, package, *, transport=HTTPTransport):
        self.base_url = str(base_url).rstrip('/')
        self.package = package
        self._transport = transport

    @staticmethod
    def place(profile, role):
        """How an endpoint is addressed: the worker is one capability, so it names none.

        Only the package lookup needs this.  The request itself carries the real
        profile even for the worker, because the challenge it signs names the
        profile the step belongs to, and an endpoint refuses a verification claim
        that does not match the message it was asked to sign.
        """
        return (None, role) if role == 'worker' else (profile, role)

    def url(self, profile, role):
        """Where the endpoint that owns this place answers."""
        return '%s:%d' % (self.base_url, endpoint_port(profile, role))

    def public_key(self, profile, role):
        """The key the roster bound to this place, read out of the package."""
        if role == 'worker':
            return raw(self.package['worker_certificate']['claim']['public_key'], 32)
        return raw(self.package['actors'][profile][role]['public_key'], 32)

    def signature(self, profile, role, domain, claim):
        """One signature, from the endpoint that owns the step, and checked here."""
        with trace.span('endpoint.sign', endpoint=self.url(profile, role), role=role,
                        domain=domain) as entry:
            reply = self._transport(self.url(profile, role)).request(
                {'op': 'challenge', 'profile': profile, 'role': role, 'domain': domain,
                 'claim': claim})
            entry['answer'] = reply.get('role') if type(reply) is dict else None
        require(type(reply.get('signature')) is str and reply.get('role') == role
                and reply.get('domain') == domain, 'CALLER_ANSWER')
        signature = raw(reply['signature'], 64)
        strict_verify(self.public_key(profile, role), signature, canonical([domain, claim]))
        return b64(signature)

    def proof(self, profile, role, domain, claim):
        """The one proof shape the interface takes."""
        return {'claim': claim, 'signature': self.signature(profile, role, domain, claim)}


class Caller:
    """One caller: a session, the published roster, and the steps it drives.

    ``start`` opens the session and reads the package; everything after that is a
    call on the entry, with the endpoints reached only to sign.
    """

    def __init__(self, entry, key_path, endpoints=None, *, transport=HTTPTransport):
        from competition.caller.session import Session
        self.session = Session(entry, key_path)
        self.endpoints = None if endpoints is None else str(endpoints).rstrip('/')
        self._transport = transport
        self.package = None
        self._signers = None

    def start(self):
        """Open the session and read the package endpoint answers are checked against."""
        with trace.span('entry.session'):
            opened = self.session.open()
        with trace.span('entry.package'):
            self.package = self.session.call('GET', '/api/package')
        return opened

    def signers(self):
        """The endpoint signer, built once there is a package to check against."""
        require(self.package is not None, 'CALLER_START')
        require(self.endpoints is not None, 'CALLER_ENDPOINTS')
        if self._signers is None:
            self._signers = EndpointSigner(self.endpoints, self.package,
                                           transport=self._transport)
        return self._signers

    def submit(self, profile, intent=None):
        """Propose an operation; the entry answers with the first challenge.

        Submitting is the side that proposes, and the entry's caller list is what
        decides which side this caller is -- not anything in this request.
        """
        return self.session.call('POST', '/api/submit', {'profile': profile, 'intent': intent})

    def challenge(self, operation_id, step):
        """Ask for one step's challenge, and what the entry says about who signs it."""
        return self.session.call('POST', '/api/challenge',
                                 {'operation_id': operation_id, 'step': step})

    def step(self, operation_id, step):
        """One step start to finish: ask, get it signed where it belongs, hand it back."""
        with trace.span('entry.challenge', operation_id=operation_id, step=step):
            asked = self.challenge(operation_id, step)
        with trace.span('endpoint.proof', operation_id=operation_id, step=step):
            proof = self.signers().proof(asked['profile'], asked['role'], asked['domain'],
                                         asked['claim'])
        with trace.span('entry.prove', operation_id=operation_id, step=step):
            return self.session.call('POST', '/api/prove',
                                     {'operation_id': operation_id, 'step': step,
                                      'proof': proof})
