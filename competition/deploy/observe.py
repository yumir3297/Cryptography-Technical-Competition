"""The observation face as its own service: one local W, three seeded operations.

This is the page a reviewer looks at, so the image starts it without asking for
anything: it initializes a run with the local signer, drives three real
operations through it (PAY and IND settled, MED parked at claim), mints one
auditor token and serves the page on 8770.  It is self-contained on purpose --
the face is a projection of one run, and a demo run nobody else drives is the
cheapest honest one to show.

The token is printed, never baked into the page: the page itself is static and
still reads every number through ``/api/diag/*`` with that token, exactly like
the trusted entry does.  Tokens live as long as the chain window; restart the
service to mint a new one.

``python -m competition.deploy.observe``
    host, port and run directory come from ``ZJJ_OBSERVE_HOST``,
    ``ZJJ_OBSERVE_PORT`` and ``ZJJ_OBSERVE_WORK``.
"""
import json
import os
import shutil
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.responses import JSONResponse

from competition.profiles.w_seed import initialize
from competition.server.service import STEPS, TrustedService
from competition.server.signer import LocalSigner
from competition.support.wire import b64, canonical, keyid
from competition.web.app import make_app
from competition.web.session import SESSION_DOMAIN, Sessions, read_callers


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


def main():
    host = os.environ.get('ZJJ_OBSERVE_HOST', '0.0.0.0')
    port = int(os.environ.get('ZJJ_OBSERVE_PORT', '8770'))
    work = Path(os.environ.get('ZJJ_OBSERVE_WORK', '.runtime/observe-demo'))
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

    # 页面打开就自己填 token。这条路由只属于这个自包含演示服务；受信端入口
    # 没有它，页面在那边仍走手工粘贴。服务只监听回环，token 也只活一个窗口。
    @app.get('/api/observe/demo-token', include_in_schema=False)
    def demo_token():
        return JSONResponse(content={'token': token})

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level='warning', access_log=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
