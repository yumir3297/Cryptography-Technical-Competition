"""Shared test helpers: a real served face, and real caller credentials.

A test of a transport has to exercise a transport, so :class:`Face` starts a real
uvicorn server on a real port in a thread of the test process -- the same server
and the same app the command line serves, minus the process.

:func:`make_callers` writes real caller credentials and the allowlist that names
them, because the entry's own rules are about real keys and a stubbed one would
test nothing.

Naming this without a ``test`` prefix keeps test discovery from collecting it.
"""
import json
import socket
import threading
import time

import httpx
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.support.wire import b64, canonical, keyid
from competition.web.session import SESSION_DOMAIN


def free_port():
    """One free local port, asked of the kernel rather than guessed."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def body(**request):
    """One request object as the wire carries it."""
    return json.dumps(request, ensure_ascii=False).encode('utf-8')


class Face:
    """One served face on a real port, served until :meth:`close`."""

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
        """Wait for the face to answer, rather than guessing a startup delay.

        A face that could not bind has to fail here rather than be mistaken for
        one that did: if this process cannot take the port, something else is
        already answering on it, and talking to that would be a test of the wrong
        server.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._thread.is_alive():
                raise AssertionError('the face on port %d stopped before it answered'
                                     % self.port)
            try:
                if httpx.get(self.base + '/healthz', timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.02)
        raise AssertionError('the face on port %d did not answer within %ss'
                             % (self.port, timeout))

    def get(self, path, headers=None):
        return httpx.get(self.base + path, headers=headers, timeout=5.0)

    def post(self, path, payload, headers=None):
        return httpx.post(self.base + path, content=payload, headers=headers, timeout=5.0)

    def close(self):
        self._server.should_exit = True
        self._thread.join(timeout=10)


def public_of(key):
    """The raw public half of one generated key."""
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def make_callers(folder, specs):
    """Write one caller credential per spec and the allowlist that names them."""
    from pathlib import Path
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    entries, keys = [], {}
    for name, sides in specs:
        key = Ed25519PrivateKey.generate()
        keys[name] = key
        entries.append({'name': name, 'public_key': b64(public_of(key)), 'sides': list(sides)})
    path = folder / 'callers.jsonl'
    path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries), encoding='utf-8')
    return path, keys


def caller_of(key):
    """One caller key, with the one thing it does: answer its own session."""
    return {'kid': keyid(public_of(key)),
            'sign': lambda claim: b64(key.sign(canonical([SESSION_DOMAIN, claim])))}
