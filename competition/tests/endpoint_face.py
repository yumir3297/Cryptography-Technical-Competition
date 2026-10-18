"""One endpoint's HTTP face, served for real: shared by the tests that need it.

A test of the transport has to exercise a transport, so this starts a real
uvicorn server on a real port in a thread of the test process -- the same
server and the same app the command line serves, minus the process.  Naming it
without a ``test`` prefix keeps test discovery from collecting it.
"""
import json
import socket
import threading
import time

import httpx
import uvicorn


def free_port():
    """One free local port, asked of the kernel rather than guessed."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def body(**request):
    """One request object as the wire carries it."""
    return json.dumps(request, ensure_ascii=False).encode('utf-8')


class Face:
    """One endpoint's face on a real port, served until :meth:`close`."""

    def __init__(self, app, *, port=None, host='127.0.0.1'):
        config = uvicorn.Config(app, host=host, port=port if port else free_port(),
                                log_level='warning', access_log=False)
        self.port = config.port
        self.base = 'http://%s:%d' % (host, config.port)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        self.await_ready()

    def await_ready(self, timeout=30.0):
        """Wait for the face to answer, rather than guessing a startup delay."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if httpx.get(self.base + '/healthz', timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.02)
        raise AssertionError('endpoint did not answer within %ss' % timeout)

    def get(self, path):
        return httpx.get(self.base + path, timeout=5.0)

    def post(self, path, payload):
        return httpx.post(self.base + path, content=payload, timeout=5.0)

    def close(self):
        self._server.should_exit = True
        self._thread.join(timeout=10)
