"""The observation face as its own service.

Two modes, picked by ``ZJJ_OBSERVE_ENTRY``:

* **live** -- the face reads the run the entry is actually driving.  The service
  registers one auditor caller in the entry's caller list, opens a session over
  HTTP and forwards ``/api/diag/*`` to that entry with its own token.  The page
  still polls every five seconds; a candidate submitted from the console or an
  agent appears and advances without a reload.  This is what the one-click stack
  starts, so the face follows real progress instead of a canned run.
* **demo** -- no entry configured: one local W, three seeded operations (PAY and
  IND settled, MED parked at claim), one auditor token, served on 8770.  Useful
  when only the page is wanted.

Either way the page itself is static and holds no credential: every number is
read through ``/api/diag/*`` with the auditor token, and ``/api/observe/demo-token``
only hands that token to the local page so it can fill itself in.

``python -m competition.deploy.observe``
    host, port and run directory come from ``ZJJ_OBSERVE_HOST``,
    ``ZJJ_OBSERVE_PORT`` and ``ZJJ_OBSERVE_WORK``.  Live mode also reads
    ``ZJJ_OBSERVE_ENTRY`` (for example ``http://trusted:8000``) and
    ``ZJJ_OBSERVE_CALLERS`` (the entry's ``callers.jsonl``).
"""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption,
                                                          PrivateFormat, PublicFormat)
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from competition.profiles.w_seed import initialize
from competition.server.service import STEPS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import b64, canonical, keyid
from competition.web.app import make_app
from competition.web.session import SESSION_DOMAIN, Sessions, read_callers

STATIC = Path(__file__).resolve().parent.parent / 'web' / 'static'
TOKEN_AGE = 25 * 60


def public_of(key):
    """The raw public half of one generated key."""
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def auditor_caller(folder):
    """One auditor credential and its allowlist, plus the thing that answers it."""
    folder.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    entry = {'name': 'auditor', 'public_key': b64(public_of(key)),
             'sides': ['auditor']}
    path = folder / 'callers.jsonl'
    path.write_text(json.dumps(entry) + '\n', encoding='utf-8')
    caller = {'kid': keyid(public_of(key)),
              'sign': lambda claim: b64(key.sign(canonical([SESSION_DOMAIN, claim])))}
    return path, caller


def seed(service):
    """Three real operations: two finished, one parked where a person reads it."""
    settled_pay = service.run_normal('PAY-1')
    settled_ind = service.run_normal('IND-DEMO-1')

    submitted = service.submit('MED-DEMO-1')
    oid = submitted['operation_id']
    _, _, role, domain = STEPS['prepare']
    service.prove(oid, 'prepare',
                  service.answer('MED-DEMO-1', role, domain, submitted['challenge']))
    accepted = service.step(oid, 'accept')
    claimed = service.step(oid, 'claim')
    return {
        'SETTLED PAY': settled_pay['operation_id'],
        'SETTLED IND': settled_ind['operation_id'],
        'CLAIMED MED': oid,
        'accept': accepted.get('dispatch_state'),
        'claim': claimed.get('dispatch_state'),
    }


def demo(host, port, work):
    """The self-contained run, for when no entry is configured."""
    if work.exists():
        shutil.rmtree(work)

    run = initialize(work / 'w')
    service = TrustedService(run, LocalSigner(run))
    report = seed(service)

    callers_path, caller = auditor_caller(work / 'callers')
    sessions = Sessions(read_callers(callers_path))
    claim = sessions.challenge(caller['kid'])
    token = sessions.open(claim, caller['sign'](claim))['token']

    print('URL   http://%s:%d/observe#map' % (host, port), flush=True)
    print('TOKEN %s' % token, flush=True)
    for name, value in report.items():
        print('SEED  %s = %s' % (name, value), flush=True)

    app = make_app(service, sessions)

    @app.get('/api/observe/demo-token', include_in_schema=False)
    def demo_token():
        return JSONResponse(content={'token': token})

    serve(app, host, port)
    return 0


def wait_for_entry(entry, seconds=600.0):
    """Hold until the entry answers, so the face does not race its own stack."""
    deadline = time.monotonic() + seconds
    url = entry.rstrip('/') + '/healthz'
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as reply:
                if reply.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


class RemoteAuditor:
    """One auditor caller for an entry that is already running.

    The entry reads ``callers.jsonl`` again when it sees an unknown key, so the
    line can be added while the stack is up.  The key lives in the work folder:
    a restart reuses it instead of adding another line, and the name is derived
    from the public key so two processes can never claim the same name.
    """

    def __init__(self, entry, callers):
        self.entry = entry.rstrip('/')
        self.callers = Path(callers)
        self.key = None
        self.kid = ''
        self.token = ''
        self.minted = 0.0
        self.lock = threading.Lock()

    def _post(self, path, body):
        request = urllib.request.Request(
            self.entry + path, data=json.dumps(body).encode(),
            headers={'content-type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=20) as reply:
            return json.loads(reply.read())

    def load(self, work):
        work.mkdir(parents=True, exist_ok=True)
        path = work / 'auditor.key'
        if path.exists():
            self.key = Ed25519PrivateKey.from_private_bytes(path.read_bytes())
        else:
            self.key = Ed25519PrivateKey.generate()
            path.write_bytes(self.key.private_bytes(Encoding.Raw, PrivateFormat.Raw,
                                                    NoEncryption()))
            os.chmod(path, 0o600)
        public = public_of(self.key)
        self.kid = keyid(public)
        name = 'observe-' + hashlib.sha256(public).hexdigest()[:12]
        line = json.dumps({'name': name, 'public_key': b64(public),
                           'sides': ['auditor']}, ensure_ascii=False, sort_keys=True)
        try:
            existing = self.callers.read_text(encoding='utf-8')
        except OSError:
            existing = ''
        if line not in existing.splitlines():
            self.callers.parent.mkdir(parents=True, exist_ok=True)
            with self.callers.open('a', encoding='utf-8') as stream:
                stream.write(line + '\n')

    def mint(self):
        challenge = self._post('/session', {'kid': self.kid})['challenge']
        signature = b64(self.key.sign(canonical([SESSION_DOMAIN, challenge])))
        token = self._post('/session/prove',
                           {'claim': challenge,
                            'signature': signature})['token']
        with self.lock:
            self.token = token
            self.minted = time.monotonic()
        return token

    def ensure(self):
        with self.lock:
            fresh = self.token and time.monotonic() - self.minted < TOKEN_AGE
        return self.token if fresh else self.mint()

    def get(self, path, token):
        """Forward one read with the token the page presented, not our own.

        The page's token is the credential: replacing it here would make the
        token box decorative and let a cleared or expired token keep reading.
        """
        request = urllib.request.Request(
            self.entry + path, headers={'authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=20) as reply:
            return (reply.status, reply.headers.get('content-type', 'application/json'),
                    reply.read())


def live_app(remote):
    """The static page plus a token-forwarding read route."""
    app = FastAPI(title='zjj-observe-live')

    @app.get('/healthz')
    def healthz():
        return {'ok': True}

    @app.get('/observe', include_in_schema=False)
    def page():
        return FileResponse(STATIC / 'observe' / 'index.html', media_type='text/html')

    @app.get('/api/observe/demo-token', include_in_schema=False)
    def demo_token():
        return JSONResponse(content={'token': remote.ensure()})

    @app.api_route('/api/{path:path}', methods=['GET'])
    async def proxy(path: str, request: Request):
        header = request.headers.get('authorization', '')
        if not header.startswith('Bearer '):
            return JSONResponse(status_code=401, content={'deny': 'SESSION_REQUIRED'})
        target = '/api/' + path
        if request.url.query:
            target += '?' + request.url.query
        try:
            status, ctype, body = await run_in_threadpool(
                remote.get, target, header[len('Bearer '):])
            return Response(content=body, status_code=status, media_type=ctype)
        except urllib.error.HTTPError as exc:
            return Response(content=exc.read(), status_code=exc.code,
                            media_type=exc.headers.get('content-type',
                                                      'application/json'))
        except OSError:
            return Response(status_code=502)

    app.mount('/observe/assets/prts', StaticFiles(directory=STATIC / 'prts'),
              name='observe-prts')
    app.mount('/observe/assets', StaticFiles(directory=STATIC / 'observe'),
              name='observe-assets')
    return app


def live(host, port, work, entry):
    """Attach to a running entry and serve the same page over its reads."""
    callers = Path(os.environ.get('ZJJ_OBSERVE_CALLERS',
                                  str(work / 'callers' / 'callers.jsonl')))
    remote = RemoteAuditor(entry, callers)
    remote.load(work)

    print('URL   http://%s:%d/observe#map' % (host, port), flush=True)
    print('LIVE  %s (auditor %s)' % (remote.entry, remote.kid), flush=True)
    if not wait_for_entry(remote.entry):
        print('entry %s did not answer /healthz' % remote.entry, flush=True)
        return 1
    for attempt in range(60):
        try:
            remote.mint()
            break
        except (OSError, KeyError, ValueError) as exc:
            if attempt == 59:
                print('could not open an auditor session: %r' % (exc,), flush=True)
                return 1
            time.sleep(1.0)
    print('TOKEN %s' % remote.token, flush=True)
    serve(live_app(remote), host, port)
    return 0


def serve(app, host, port):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level='warning', access_log=False)


def main():
    host = os.environ.get('ZJJ_OBSERVE_HOST', '0.0.0.0')
    port = int(os.environ.get('ZJJ_OBSERVE_PORT', '8770'))
    work = Path(os.environ.get('ZJJ_OBSERVE_WORK', '.runtime/observe-demo'))
    entry = os.environ.get('ZJJ_OBSERVE_ENTRY', '').strip()
    if entry:
        return live(host, port, work, entry)
    return demo(host, port, work)


if __name__ == '__main__':
    raise SystemExit(main())
