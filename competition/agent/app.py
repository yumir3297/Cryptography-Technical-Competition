"""The ASGI app: MCP over Streamable HTTP, one feedback log, and token gates.

Two tokens, two scopes.  The agent token reaches ``/mcp`` and ``/zjj/*`` and
nothing else.  The internal token reaches ``/internal/*`` for the operator and
executor queues and nothing else.  Neither token can sign, and the gateway's
caller key never leaves this process.

The MCP transport is the official Python SDK's Starlette app.  It is mounted
inside a FastAPI host, so the host lifespan must enter the SDK's session manager;
without that line the first request fails with "Task group is not initialized".
"""
import asyncio
import hmac
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from competition.agent.mcp_server import build_server
from competition.agent.service import GatewayError, OperationUnknown

# dsh connects from inside its own container to host.docker.internal.  The
# compose-internal name is accepted too, so a deployment that attaches dsh to the
# same network does not need a different build.
ALLOWED_HOSTS = [
    '127.0.0.1', '127.0.0.1:*',
    'localhost', 'localhost:*',
    'host.docker.internal', 'host.docker.internal:*',
    'agent-gateway', 'agent-gateway:*',
]
ALLOWED_ORIGINS = [
    'http://127.0.0.1:8090', 'http://localhost:8090',
    'http://host.docker.internal:8090', 'http://agent-gateway:8090',
]


class QueueClaim(BaseModel):
    role: Literal['operator', 'executor']


class QueueRelease(BaseModel):
    role: Literal['operator', 'executor']
    operation_id: str


class Hint(BaseModel):
    stage: Literal['prepared', 'accepted', 'claimed', 'executed',
                   'settled', 'failed', 'unknown']


def _unauthorized(message='AUTH_REQUIRED'):
    return JSONResponse(status_code=401, content={'deny': message},
                        headers={'WWW-Authenticate': 'Bearer'})


class TokenGate:
    """Pure ASGI gate so the mounted MCP app sees the original request untouched."""

    def __init__(self, app, agent_token, internal_token):
        self.app = app
        self.agent_token = agent_token
        self.internal_token = internal_token

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if path == '/healthz':
            return await self.app(scope, receive, send)
        if path.startswith('/internal/'):
            required = self.internal_token
        elif path == '/mcp' or path.startswith('/mcp/') or path.startswith('/zjj/'):
            required = self.agent_token
        else:
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get('headers', [])}
        authorization = headers.get(b'authorization', b'').decode('latin-1')
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        if not required or not token or not hmac.compare_digest(token, required):
            response = _unauthorized()
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def _poll_loop(service, interval, stop):
    while not stop.is_set():
        try:
            service.poll_once()
        except Exception:
            # One journal error must not end feedback for every operation.
            pass
        stop.wait(max(0.1, float(interval)))


def make_app(service, *, agent_token, internal_token, poll_interval=1.0):
    """Build the gateway app over one started service."""
    mcp = build_server(service)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path='/mcp',
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(ALLOWED_HOSTS),
            allowed_origins=list(ALLOWED_ORIGINS),
        ),
        max_request_body_size=1 << 20,
    )

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            stop = threading.Event()
            thread = threading.Thread(target=_poll_loop,
                                      args=(service, poll_interval, stop),
                                      name='zjj-status-poller', daemon=True)
            thread.start()
            try:
                yield
            finally:
                stop.set()
                thread.join(timeout=5.0)

    app = FastAPI(title='zjj-agent-gateway', description='agent-facing MCP entry',
                  lifespan=lifespan)

    @app.get('/healthz')
    def healthz():
        return {'ok': True, 'service': 'zjj-agent-gateway'}

    @app.get('/zjj/events')
    def events(since: int = Query(0, ge=0), operation_id: str | None = None,
               limit: int = Query(100, ge=1, le=500)):
        rows = service.events(since=since, operation_id=operation_id, limit=limit)
        next_seq = rows[-1]['seq'] if rows else since
        return {'events': rows, 'next_seq': next_seq}

    @app.post('/internal/queue/claim')
    def queue_claim(body: QueueClaim):
        row = service.queue_claim(body.role)
        if row is None:
            return Response(status_code=204)
        return row

    @app.post('/internal/queue/release')
    def queue_release(body: QueueRelease):
        service.queue_release(body.role, body.operation_id)
        return {'ok': True}

    @app.post('/internal/operations/{operation_id}/hint')
    def operation_hint(operation_id: str, body: Hint):
        try:
            return service.hint(operation_id, body.stage)
        except OperationUnknown as exc:
            return JSONResponse(status_code=404, content={'deny': exc.code})

    @app.get('/internal/healthz')
    def internal_healthz():
        return {'ok': True, 'service': 'zjj-agent-gateway-internal'}

    # The MCP app is the last route: Starlette tries the FastAPI routes first.
    app.mount('/', mcp_app)
    return TokenGate(app, agent_token, internal_token)


def serve(service, host='0.0.0.0', port=8090, *, agent_token, internal_token,
          poll_interval=1.0):
    """Serve the gateway until the process stops."""
    import os

    import uvicorn
    uvicorn.run(make_app(service, agent_token=agent_token,
                         internal_token=internal_token,
                         poll_interval=poll_interval),
                host=host, port=port, log_level='warning',
                access_log=bool(os.environ.get('ZJJ_ACCESS_LOG')))
