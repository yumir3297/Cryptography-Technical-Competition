"""The console's HTTP face: the page's own calls, and the page itself.

This is a transport for the console's :class:`~competition.console.control.Console`
and nothing more.  Every route is one call on it, and every call is one
:class:`~competition.caller.flow.Caller` call behind it: nothing here signs, and
there is deliberately no route that would -- only the endpoints can, and only for
their own roles.

Two things shape the surface, the same two the trusted entry is shaped by:

* **the fields are exact**, because a body off a network is not a Python dict a
  caller already built.  Every route names the fields it takes and refuses
  anything else, so the page cannot ask for a role, a key or a test switch that
  this layer has no place to put;
* **a refusal keeps the rule that produced it**, because "the entry would not
  take that" and "the endpoint was not there" are different facts and the page
  shows both.  A rule the entry or an endpoint named travels through unchanged.
"""
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from competition.support.wire import ProtocolError, require

# One body here is a profile, an intent or one step: small, and bounded anyway.
MAX_BODY = 1 << 16
# A rule that refused something.
DENY_STATUS = 403
# A service that was not there.  Not a rule, and different to act on, so it says
# so with a different status: the page can tell "ask again" from "that was not
# allowed".
UNAVAILABLE = frozenset({'ENTRY_UNAVAILABLE', 'ENDPOINT_UNAVAILABLE', 'ENTRY_ANSWER'})
PREFIX = '/console'
# Where the built page is, beside this module (Vite's own ``dist``).
DIST = Path(__file__).resolve().parent / 'frontend' / 'dist'


def _deny(code):
    """One refusal shape, named after the rule that failed."""
    return JSONResponse(status_code=503 if code in UNAVAILABLE else DENY_STATUS,
                        content={'deny': code})


async def _json(request, required, optional=()):
    """One bounded body holding exactly those fields, or a refusal."""
    body = await request.body()
    require(len(body) <= MAX_BODY, 'CONSOLE_SIZE')
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        raise ProtocolError('CONSOLE_MALFORMED')
    require(type(value) is dict, 'CONSOLE_FIELDS')
    keys = set(value)
    require(set(required) <= keys <= set(required) | set(optional), 'CONSOLE_FIELDS')
    return value


def make_app(console, *, dist=None):
    """Build the console over one enrolled, started console state."""
    app = FastAPI(title='zjj-console', description='ZJJ-CORE 客户端控制台')

    @app.get(PREFIX + '/healthz')
    def healthz():
        return {'ok': True}

    # Reading what the roster bound needs no side; it is every authenticated
    # caller's, the same as it is on the entry.
    @app.get(PREFIX + '/api/status')
    def status():
        return console.status()

    # The scenarios the entry fixes, what each one takes, and which roles it
    # needs.  Descriptive only; the entry is still what decides whether a profile
    # is real.
    @app.get(PREFIX + '/api/scenarios')
    def scenarios():
        return console.scenarios()

    # What waits on the roles that sign inside the chain.  Reading it changes
    # nothing and drives nothing -- the same kind of read the roster is.  It goes
    # to those roles' own endpoints, not through the entry, because the entry is
    # what is blocked while one of them waits for an answer.
    @app.get(PREFIX + '/api/pending')
    def pending(profile: str = ''):
        return console.pending(profile or None)

    # The answer to one waiting request.  A yes or a no travels to the role's own
    # endpoint, which is where the decision and the signature both live.
    @app.post(PREFIX + '/api/decide')
    async def decide(request: Request):
        try:
            body = await _json(request, ('profile', 'role', 'id', 'approve'))
            return await run_in_threadpool(console.decide, body['profile'],
                                           body['role'], body['id'], body['approve'])
        except ProtocolError as exc:
            return _deny(exc.code)

    @app.get(PREFIX + '/api/package')
    def package():
        try:
            return console.package()
        except ProtocolError as exc:
            return _deny(exc.code)

    # Submitting and stepping reach the entry, which is a network call, so they
    # run off the event loop and let one page's request wait on another.
    @app.post(PREFIX + '/api/submit')
    async def submit(request: Request):
        try:
            body = await _json(request, ('profile',), ('intent',))
            return await run_in_threadpool(console.submit, body['profile'],
                                           body.get('intent'))
        except ProtocolError as exc:
            return _deny(exc.code)

    @app.post(PREFIX + '/api/step')
    async def step(request: Request):
        try:
            body = await _json(request, ('side', 'operation_id', 'step'))
            return await run_in_threadpool(console.step, body['side'],
                                           body['operation_id'], body['step'])
        except ProtocolError as exc:
            return _deny(exc.code)

    # The page itself, when it has been built.  The routes above are registered
    # first so the mount cannot swallow them; a page that is not built says so
    # rather than answering a request with a directory listing.
    folder = Path(dist) if dist else DIST
    if folder.is_dir():
        app.mount(PREFIX, StaticFiles(directory=str(folder), html=True), name='console-ui')
    else:
        @app.get(PREFIX)
        @app.get(PREFIX + '/')
        def no_page():
            return JSONResponse(status_code=503, content={'deny': 'CONSOLE_PAGE_NOT_BUILT'})

    return app


def serve(host, port, console, *, dist=None):
    """Serve the console until the process is stopped."""
    import uvicorn
    uvicorn.run(make_app(console, dist=dist), host=host, port=port,
                log_level='warning', access_log=False)
