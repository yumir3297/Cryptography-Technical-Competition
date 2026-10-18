"""The endpoint's HTTP face: the line protocol, carried in a request body.

An endpoint that made its own key answers challenges over a socket.  This is the
second way to reach it, and it is deliberately not a second protocol: the body of
``POST /sign`` is the **same object** the line protocol accepts -- a challenge
``{op, profile, role, domain, claim}``, in-chain bytes ``{op: 'raw', ...}``, or a
possession proof ``{op: 'enrollment', ...}`` -- and it is answered by the same
:func:`competition.client.host.answer`.  There is one place where a request
becomes a signature, so the two transports cannot drift apart.

Three more routes are the endpoint's own business rather than a signing
capability: ``/healthz`` and ``/identity`` say what this process holds, and
``/check-package`` runs :func:`competition.client.package.check` against a
package handed over the wire, so an endpoint can verify its own registration
without a file on disk.

Every refusal is ``403`` with ``{"deny": <rule>}`` -- the same rule name the line
protocol refuses under, so nothing downstream has to know which door it knocked
on.  A request that is not exactly the shape of one op never reaches the signer:
the size bound, the JSON parse and the field set are all checked first, and a
request that fails any of them is refused rather than guessed at.

When this endpoint was started in the waiting room (``approval``), the chain's own
signatures park there before they reach the signer and are answered only once
someone says yes or no.  The room sits *ahead of* the one signing point, not beside
it: what comes back is still that point's answer, and the two ways of not getting
one -- nobody answered, or somebody said no -- are named as such rather than
dressed up as a signature this module made up.

Which requests park is the room's own decision, and it is a narrow one: the
chain's signing domain waits for a person, and every other request an endpoint
answers -- an enrollment's possession proof, a step's challenge -- is answered
straight away.  A deployment initializes its run and enrolls every role before
anybody has a page open, so waiting on those would stop it from ever coming up.
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from competition.client.approval import WaitingRoom, chain_request_ref, needs_a_person
from competition.client.host import MAX_REQUEST_LINE, answer
from competition.client.keys import propose_purposes, propose_subject
from competition.client.package import check, validate_package
# The refusal status and body shape are one wire fact shared with the transport
# that reads them, so they live with the endpoint wire, not here.
from competition.server.roster import DENY_STATUS
from competition.support.wire import ProtocolError, b64, require

# One package carries every endpoint's public facts and the certificates behind
# them; generous, and still bounded.
MAX_PACKAGE_BODY = 1 << 22


def _deny(code):
    """The one refusal shape, named after the rule that failed."""
    return JSONResponse(status_code=DENY_STATUS, content={'deny': code})


def _line(body):
    """The body as the line protocol reads it, without changing its bytes."""
    return body if body.endswith(b'\n') else body + b'\n'


def make_app(signer, *, name=None, approval=None):
    """Build the HTTP face of one endpoint's signing host.

    ``signer`` is a :class:`~competition.client.signer.RoleSigner`: it already
    bound the one key this process may use and the domains it may sign, so this
    module adds a transport and no authority.  ``approval`` is the waiting room,
    when this endpoint was started to ask a person before it signs.
    """
    app = FastAPI(title='zjj-endpoint', docs_url=None, redoc_url=None, openapi_url=None)
    profile, role = signer.profile, signer.role
    # The name this endpoint proposed for itself; the roster is what decides.
    subject = name or propose_subject(profile, role)

    @app.get('/healthz')
    def healthz():
        return {'ok': True, 'profile': profile, 'role': role, 'kid': signer.kid}

    @app.get('/identity')
    def identity():
        return {'profile': profile, 'role': role, 'subject': subject,
                'public_key': b64(signer.public), 'kid': signer.kid,
                'purposes': propose_purposes(role)}

    @app.post('/sign')
    async def sign(request: Request):
        body = await request.body()
        try:
            require(len(body) <= MAX_REQUEST_LINE, 'CLIENT_SIZE')
            line = _line(body)
            if approval is not None and needs_a_person(line):
                # The chain's own signing call.  A person was asked before it
                # opened (``/preapprove``), so the answer is usually already in
                # hand and the call is answered straight away.  When it is not --
                # a caller that did not report first -- the request parks the way
                # it used to, held only as long as the open call would still take
                # the answer.
                ref = chain_request_ref(line)
                if ref is None or not approval.take_approved(ref):
                    ticket = approval.park(line)
                    approved = await run_in_threadpool(ticket.wait, approval.timeout)
                    approval.drop(ticket.id)
                    if approved is None:
                        return _deny('CLIENT_NO_ANSWER')
                    if not approved:
                        return _deny('CLIENT_REFUSED')
            reply = answer(line, signer)
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content=reply)

    @app.post('/preapprove')
    async def preapprove(request: Request):
        """Ask a person about one chain message before its signing call opens.

        The caller hands over the message it is about to have signed, and waits.
        Nothing is opened by this route: the signing call, with the thirty seconds
        core puts on it, only begins on the caller's side once this answers.  So a
        person may take as long as they take, and the signature that follows is
        immediate.

        An endpoint without a waiting room is an endpoint whose signatures are not
        a person's decision, so it agrees at once and says nobody was asked.
        """
        body = await request.body()
        try:
            require(len(body) <= MAX_REQUEST_LINE, 'CLIENT_SIZE')
            try:
                value = json.loads(body)
            except (UnicodeError, json.JSONDecodeError):
                raise ProtocolError('CLIENT_MALFORMED')
            require(type(value) is dict and set(value) == {'profile', 'role', 'unsigned', 'action'},
                    'CLIENT_FIELDS')
            # The message is signed by this endpoint's one key or by nothing, so
            # a report naming another profile or role is not this endpoint's to
            # ask about.
            require(value['profile'] == profile and value['role'] == role, 'CLIENT_BINDING')
            require(type(value['unsigned']) is dict and type(value['action']) is dict, 'CLIENT_FIELDS')
            if approval is None:
                return JSONResponse(content={'approved': True, 'waited': False})
            approved = await run_in_threadpool(approval.preapprove, profile=profile, role=role,
                                               unsigned=value['unsigned'], action=value['action'],
                                               timeout=approval.preapproval_timeout)
            if approved is None:
                return _deny('CLIENT_NO_ANSWER')
            if not approved:
                return _deny('CLIENT_REFUSED')
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content={'approved': True, 'waited': True})

    @app.get('/awaiting')
    def awaiting():
        """What is parked here, so a page can show it and answer it.

        This is the endpoint's own business rather than a signing capability: it
        hands over the requests themselves, and no signature, key or decision.
        """
        return {'profile': profile, 'role': role,
                'tickets': approval.list() if approval is not None else []}

    @app.post('/decide')
    async def decide(request: Request):
        """Answer one parked request.

        A decision is not a signature: the request still goes to the one signing
        point afterwards, and can still be refused there.
        """
        body = await request.body()
        try:
            try:
                value = json.loads(body)
            except (UnicodeError, json.JSONDecodeError):
                raise ProtocolError('CLIENT_MALFORMED')
            require(type(value) is dict and set(value) == {'id', 'approve'},
                    'CLIENT_FIELDS')
            require(type(value['approve']) is bool, 'CLIENT_FIELDS')
            require(approval is not None, 'CLIENT_NO_ROOM')
            taken = approval.decide(value['id'], value['approve'])
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content={'taken': taken})

    @app.post('/check-package')
    async def check_package(request: Request):
        body = await request.body()
        try:
            require(len(body) <= MAX_PACKAGE_BODY, 'CLIENT_SIZE')
            try:
                value = json.loads(body)
            except (UnicodeError, json.JSONDecodeError):
                raise ProtocolError('CLIENT_MALFORMED')
            require(type(value) is dict and set(value) <= {'package', 'subject'}
                    and 'package' in value, 'CLIENT_FIELDS')
            package = validate_package(value['package'])
            facts = check(package, profile, role, public=signer.public, kid=signer.kid,
                          name=value.get('subject') or subject,
                          purposes=propose_purposes(role))
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content={'check': 'OK', **facts})

    return app


def serve_http(host, port, signer, *, name=None, approval=None):
    """Serve one endpoint's HTTP face until the process is stopped.

    One process, one key: an endpoint is a client, so its key never shares a
    process with another endpoint's key or with the trusted side.  With
    ``approval``, this endpoint asks a person before it signs; without it, it
    answers exactly the way it always has.
    """
    import uvicorn
    uvicorn.run(make_app(signer, name=name, approval=approval), host=host, port=port,
                log_level='warning', access_log=False)
