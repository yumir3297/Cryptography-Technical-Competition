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
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from competition.client.host import MAX_REQUEST_LINE, answer
from competition.client.keys import propose_purposes, propose_subject
from competition.client.package import check, validate_package
from competition.support.wire import ProtocolError, b64, require

# A refused request answers with this one rule name, under this one status.
DENY_STATUS = 403
# One package carries every endpoint's public facts and the certificates behind
# them; generous, and still bounded.
MAX_PACKAGE_BODY = 1 << 22


def _deny(code):
    """The one refusal shape, named after the rule that failed."""
    return JSONResponse(status_code=DENY_STATUS, content={'deny': code})


def _line(body):
    """The body as the line protocol reads it, without changing its bytes."""
    return body if body.endswith(b'\n') else body + b'\n'


def make_app(signer, *, name=None):
    """Build the HTTP face of one endpoint's signing host.

    ``signer`` is a :class:`~competition.client.signer.RoleSigner`: it already
    bound the one key this process may use and the domains it may sign, so this
    module adds a transport and no authority.
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
            reply = answer(_line(body), signer)
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content=reply)

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


def serve_http(host, port, signer, *, name=None):
    """Serve one endpoint's HTTP face until the process is stopped.

    One process, one key: an endpoint is a client, so its key never shares a
    process with another endpoint's key or with the trusted side.
    """
    import uvicorn
    uvicorn.run(make_app(signer, name=name), host=host, port=port,
                log_level='warning', access_log=False)
