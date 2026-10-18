"""The trusted side's HTTP entry: a session in front, the minimal interface behind.

The interface is three messages wide -- ``submit``, ``challenge``, ``prove`` --
and this is a transport for them, not a fourth one.  Every route calls the same
:class:`~competition.server.service.TrustedService` the command line calls, and
the signatures still travel in the body: the entry carries the proof, it does not
make one.  Nothing here signs, and there is deliberately no route that would.

What the entry adds is the two things the interface does not have:

* **a session**, because ``submit`` and ``challenge`` are cheap for a stranger to
  call and expensive for the trusted side to serve -- see
  :mod:`competition.web.session`;
* **input bounds**, because a body off a network is not a Python dict a caller
  already built.  Every route parses its body itself, holds it to one exact field
  set, and refuses anything else before the service is reached.

Two repository rules shape the surface.  Initialization, enrollment,
``counts`` and the read projections' internal steps are *not* published here at
all: the interface reference says they may not be exposed as unauthenticated
external routes, and the honest reading of that is that they are not the entry's
to publish.  And a caller cannot state its own role or key -- the request bodies
have no field for either, so a caller naming itself ``H`` is not an input this
entry can even receive.
"""
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from competition.server.observe import ObservationFeed
from competition.server.roster import DENY_STATUS
from competition.server.service import STEPS, TrustedService
from competition.support.wire import ProtocolError, require

# One body here is a business intent or a step's proof: small, and bounded anyway.
MAX_BODY = 1 << 16
# A missing or stale session is a credential problem and says so; a caller that is
# simply not allowed to do this is a refusal, not an authentication gap.
UNAUTHORIZED = frozenset({'SESSION_REQUIRED', 'SESSION_EXPIRED'})


def _deny(code):
    """One refusal shape, named after the rule that failed."""
    return JSONResponse(status_code=401 if code in UNAUTHORIZED else DENY_STATUS,
                        content={'deny': code})


async def _json(request, fields):
    """One bounded body holding exactly those fields, or a refusal."""
    body = await request.body()
    require(len(body) <= MAX_BODY, 'WEB_SIZE')
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        raise ProtocolError('WEB_MALFORMED')
    require(type(value) is dict and set(value) == set(fields), 'WEB_FIELDS')
    return value


def _token(request):
    """The bearer token this request carries, or a refusal saying it is missing."""
    header = request.headers.get('authorization', '')
    require(header.startswith('Bearer '), 'SESSION_REQUIRED')
    return header[len('Bearer '):]


def _side(step):
    """Which side of the flow signs this step, from the repository's own table."""
    return STEPS[step][2]


def _int_param(request, name, default):
    """One non-negative integer query parameter, or a refusal naming the rule."""
    raw = request.query_params.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ProtocolError('WEB_FIELDS')
    require(value >= 0, 'WEB_FIELDS')
    return value


def make_app(service, sessions):
    """Build the trusted entry over one initialized service and its callers."""
    app = FastAPI(title='zjj-trusted', description='ZJJ-CORE trusted entry')
    feed = ObservationFeed(service.run.store.path)

    @app.get('/healthz')
    def healthz():
        return {'ok': True}

    # -- session -----------------------------------------------------------
    @app.post('/session')
    async def open_session(request: Request):
        try:
            body = await _json(request, ('kid',))
            return JSONResponse(content={'challenge': sessions.challenge(body['kid'])})
        except ProtocolError as exc:
            return _deny(exc.code)

    @app.post('/session/prove')
    async def prove_session(request: Request):
        try:
            body = await _json(request, ('claim', 'signature'))
            return JSONResponse(content=sessions.open(body['claim'], body['signature']))
        except ProtocolError as exc:
            return _deny(exc.code)

    # -- the minimal interface ---------------------------------------------
    @app.post('/api/submit')
    async def submit(request: Request):
        try:
            body = await _json(request, ('profile', 'intent'))
            # Submitting is what asks the trusted side to gather a fresh approval
            # chain, so it is the one call held to the side that proposes.
            sessions.authorize(_token(request), 'H')
            result = service.submit(body['profile'], body['intent'])
        except ProtocolError as exc:
            return _deny(exc.code)
        operation_id = result['operation_id']
        feed.publish('CANDIDATE_SUBMITTED', body['profile'], operation_id,
                     {'stage': '外部提交候选动作', 'lanes': ['外部调用方'],
                      'detail': {'profile': body['profile']}})
        feed.publish('CHAIN_ASSEMBLED', body['profile'], operation_id,
                     {'stage': 'Resolver 装配完整动作/依据/用途', 'lanes': ['受信编排器']})
        return JSONResponse(content=result)

    @app.post('/api/challenge')
    async def challenge(request: Request):
        try:
            body = await _json(request, ('operation_id', 'step'))
            require(body['step'] in STEPS, 'STEP')
            sessions.authorize(_token(request), _side(body['step']))
            claim = service.challenge(body['operation_id'], body['step'])
            # The step's own signing role and domain travel back with the claim, so
            # a caller knows which endpoint to ask without keeping its own copy of
            # the table, and cannot mistake one for another.  The profile comes
            # from the operation the entry holds, so a caller handed an id it did
            # not create still knows where the endpoint is.
            profile = service.profile_of(body['operation_id'])
        except ProtocolError as exc:
            return _deny(exc.code)
        feed.publish('STEP_CHALLENGED', profile, body['operation_id'],
                     {'stage': '请求某步挑战', 'lanes': ['受信编排器'],
                      'detail': {'step': body['step'], 'role': _side(body['step'])}})
        return JSONResponse(content={'operation_id': body['operation_id'],
                                     'step': body['step'],
                                     'profile': profile,
                                     'claim': claim,
                                     'role': _side(body['step']),
                                     'domain': STEPS[body['step']][3]})

    @app.post('/api/prove')
    async def prove(request: Request):
        try:
            body = await _json(request, ('operation_id', 'step', 'proof'))
            require(body['step'] in STEPS, 'STEP')
            sessions.authorize(_token(request), _side(body['step']))
            result = service.prove(body['operation_id'], body['step'], body['proof'])
            profile = service.profile_of(body['operation_id'])
        except ProtocolError as exc:
            return _deny(exc.code)
        feed.publish('STEP_PROVED', profile, body['operation_id'],
                     {'stage': '某角色签名并交回', 'lanes': ['编排器', '签署端'],
                      'detail': {'step': body['step'], 'role': _side(body['step'])}})
        return JSONResponse(content=result)

    # -- read-only observation face ----------------------------------------
    # The observer side drives nothing; it may only read these four routes.
    @app.get('/api/observe/events')
    def observe_events(request: Request):
        try:
            sessions.authorize(_token(request), 'observer')
            after = _int_param(request, 'after', 0)
            limit = _int_param(request, 'limit', 500)
            require(limit <= 1000, 'WEB_LIMIT')
            events = feed.events(after, limit=limit,
                                 profile=request.query_params.get('profile') or None,
                                 operation_id=request.query_params.get('operation_id') or None)
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content={'events': events,
                                     'last': events[-1]['seq'] if events else after})

    @app.get('/api/observe/stream')
    def observe_stream(request: Request):
        try:
            sessions.authorize(_token(request), 'observer')
            after = _int_param(request, 'after', 0)
            header = request.headers.get('last-event-id')
            if header:
                try:
                    after = max(after, int(header))
                except ValueError:
                    pass
        except ProtocolError as exc:
            return _deny(exc.code)
        return StreamingResponse(feed.stream(after), media_type='text/event-stream',
                                 headers={'cache-control': 'no-store'})

    @app.get('/api/observe/operations')
    def observe_operations(request: Request):
        try:
            sessions.authorize(_token(request), 'observer')
            limit = _int_param(request, 'limit', 500)
            require(limit <= 1000, 'WEB_LIMIT')
            operations = feed.operations(profile=request.query_params.get('profile') or None,
                                         state=request.query_params.get('state') or None,
                                         limit=limit)
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content={'operations': operations})

    @app.get('/api/observe/operations/{operation_id}')
    def observe_operation(operation_id: str, request: Request):
        try:
            sessions.authorize(_token(request), 'observer')
            view = feed.snapshot(operation_id)
            require(view is not None, 'OPERATION_UNKNOWN')
        except ProtocolError as exc:
            return _deny(exc.code)
        return JSONResponse(content=view)

    # -- what every authenticated caller may read --------------------------
    @app.get('/api/package')
    def package(request: Request):
        try:
            sessions.authorize(_token(request))
            return JSONResponse(content=service.package())
        except ProtocolError as exc:
            return _deny(exc.code)

    return app


def serve(host, port, service, sessions):
    """Serve the trusted entry until the process is stopped.

    Takes the sessions it should use rather than a caller list, because a
    deployment starts its entry and its callers at the same time and the entry
    must not have to wait for them.
    """
    import uvicorn
    uvicorn.run(make_app(service, sessions), host=host, port=port,
                log_level='warning', access_log=False)
