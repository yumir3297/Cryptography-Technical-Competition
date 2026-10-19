"""The observation display's gateway: serve the page, carry only the read routes.

The page in :mod:`competition.display` is a browser program, and a browser cannot
be the observer directly: it must not hold the observer's private key, and the
observation routes take the bearer token in a header that ``EventSource`` cannot
set.  So the credential stays here, in a process, and the browser talks to this --
the same shape as every other caller in the deployment.

What it carries is deliberately the whole surface, and it is one narrow path:

* ``/`` and assets -- the built page, nothing about the protocol;
* ``/api/observe/events``, ``/stream``, ``/operations``, ``/operations/{oid}`` --
  the four read routes, proxied to the entry with the observer's bearer token and
  ``Last-Event-ID`` passed through so a dropped browser stream resumes where it
  stopped;
* everything else -- ``404``.

That last line is the point.  A page that could ask for ``/api/submit`` would make
the display a way to drive the protocol; by refusing to carry anything but the
four read routes, the gateway cannot, whatever the page sends.  The token it holds
is an ``observer`` token, which could not drive a step even if one were asked for.

The token lasts 15 minutes (``competition.web.session.SESSION_TTL``), which is
nothing like a display's uptime, so the session is opened again before it expires
and once more if the entry ever answers ``SESSION_EXPIRED``.
"""
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from competition.caller import announce
from competition.caller.session import Session
from competition.deploy.demo import add_line
from competition.support.wire import ProtocolError

# The only paths this gateway will carry to the entry, and the only methods.
# ``operations/{oid}`` is one segment; anything with a slash after it is not a
# route this repository has.
MIRRORED = re.compile(r'^(events|stream|operations|operations/[^/]+)$')
# Open the next token this long before the current one expires, so no request is
# ever the one that finds it stale.
RENEW_MARGIN = 60.0
# Where ``npm run build`` leaves the page, if nothing else says.
DEFAULT_DIST = Path(__file__).resolve().parents[2] / 'competition' / 'display' / 'dist'
# What to say when the page has not been built yet, rather than a broken mount.
UNBUILT = '观察页面还没构建：进入 competition/display 跑 npm install && npm run build。\n'


def opened(session, timeout=600.0):
    """Hold until the entry answers, so the gateway does not race its deployment."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            session.refresh()
            session.token()
            return session.session.token
        except ProtocolError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


class ObserverSession:
    """The gateway's own observer credential, opened again before it goes stale."""

    def __init__(self, entry, key_path):
        self.session = Session(entry, key_path)
        self.expires = 0.0
        self.lock = threading.Lock()

    def token(self):
        """A live bearer token, opening a session if there is none or it is old."""
        with self.lock:
            if self.session.token is None or time.time() > self.expires - RENEW_MARGIN:
                self._open()
            return self.session.token

    def refresh(self):
        """Forget the current token, so the next ``token()`` is a fresh proof."""
        with self.lock:
            self.session.token = None

    def _open(self):
        opened = self.session.open()
        self.expires = float(opened['expires'])


async def _carry(client, url, observer, last_event_id):
    """One read request to the entry, streamed, carrying this gateway's token."""
    headers = {'authorization': 'Bearer ' + observer.token()}
    if last_event_id:
        headers['last-event-id'] = last_event_id
    return await client.send(client.build_request('GET', url, headers=headers), stream=True)


async def _relay(reply):
    """Forward one entry response body as it arrives, and let go of it at the end."""
    try:
        async for chunk in reply.aiter_raw():
            yield chunk
    finally:
        await reply.aclose()


def make_viewer(entry, observer, dist, *, secret=None):
    """The display gateway: the built page, and the four read routes behind it."""
    entry = str(entry).rstrip('/')
    dist = Path(dist)
    # No read timeout: one request here may be the long-lived SSE stream.
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0, read=None))

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    app = FastAPI(title='zjj-observe-display', lifespan=lifespan)

    def allowed(request):
        """A shared secret, only when one is configured; the page shell stays open."""
        if not secret:
            return True
        given = request.headers.get('x-viewer-key') or request.query_params.get('key')
        return given == secret

    @app.get('/healthz')
    def healthz():
        return {'ok': True, 'entry': entry, 'observer': observer.session.caller}

    @app.get('/api/observe/{tail:path}')
    async def mirror(tail: str, request: Request):
        if not MIRRORED.match(tail):
            return JSONResponse(status_code=404, content={'deny': 'VIEWER_PATH'})
        if not allowed(request):
            return JSONResponse(status_code=401, content={'deny': 'VIEWER_KEY'})
        query = request.url.query
        url = '%s/api/observe/%s%s' % (entry, tail, ('?' + query) if query else '')
        last = request.headers.get('last-event-id')
        reply = await _carry(client, url, observer, last)
        if reply.status_code == 401:
            # The one token case worth a second try: prove the key again and reask.
            await reply.aread()
            await reply.aclose()
            observer.refresh()
            reply = await _carry(client, url, observer, last)
        return StreamingResponse(_relay(reply), status_code=reply.status_code,
                                 media_type=reply.headers.get('content-type',
                                                              'application/json'),
                                 headers={'cache-control': 'no-store',
                                          'x-accel-buffering': 'no'})

    # Every other ``/api`` path, whatever the method, is not this gateway's to
    # carry: the entry's own submit/challenge/prove are not reachable from a page.
    @app.api_route('/api/{tail:path}',
                   methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
    async def not_carried(tail: str):
        return JSONResponse(status_code=404, content={'deny': 'VIEWER_PATH'})

    if (dist / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=str(dist), html=True), name='display')
    else:
        @app.get('/{tail:path}')
        def unbuilt(tail: str):
            return PlainTextResponse(UNBUILT, status_code=501)

    return app


def serve(host, port, entry, observer, dist, *, secret=None):
    """Serve the display until the process is stopped."""
    uvicorn.run(make_viewer(entry, observer, dist, secret=secret), host=host, port=port,
                log_level='warning', access_log=False)


def main():
    directory = Path(os.environ.get('ZJJ_CALLERS', '/callers'))
    name = os.environ.get('ZJJ_NAME', 'caller-observer')
    entry = os.environ.get('ZJJ_ENTRY', 'http://127.0.0.1:8000')
    host = os.environ.get('ZJJ_VIEWER_HOST', '127.0.0.1')
    port = int(os.environ.get('ZJJ_VIEWER_PORT', '8008'))
    dist = Path(os.environ.get('ZJJ_VIEWER_DIST', str(DEFAULT_DIST)))
    secret = os.environ.get('ZJJ_VIEWER_SECRET') or None
    line = announce(directory, name, ['observer'])
    print('%s in %s' % (name, add_line(directory, line)), flush=True)
    observer = ObserverSession(entry, directory / (name + '.key'))
    opened(observer)
    print('展示页在 http://%s:%d/（观察 %s）' % (host, port, entry), flush=True)
    serve(host, port, entry, observer, dist, secret=secret)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
