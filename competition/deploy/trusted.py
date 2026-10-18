"""Bring up the trusted side: wait for the endpoints, initialize once, serve.

Initialization asks every endpoint for a signature, so it cannot begin until they
all answer: a run started against a half-started fleet would come back with a
fleet error rather than a run.  So this waits -- for the manifest to be complete
and for each endpoint to answer -- and only then initializes.

It refuses to initialize twice.  The run directory *is* the record: its ledgers are
what a verification is checked against, so a second initialization against a
directory that already holds one is not a restart, and this says so rather than
guessing at one.  There is no reopen yet; see the deployment note in
``docker-compose.yml``.

The entry is given no signer.  It has no route that could use one -- only the
endpoints produce business signatures -- so "the trusted side does not sign for a
caller" is a fact of how this process is built, not a promise in a comment.
"""
import os
import sys
import time
from pathlib import Path

import httpx

from competition.deploy import serves
from competition.profiles.w_seed import initialize
from competition.server.roster import Fleet, read_manifest
from competition.server.service import TrustedService
from competition.support.wire import ProtocolError
from competition.web.app import serve
from competition.web.session import Sessions, read_callers

# How long one request to an endpoint may take here.  A step's challenge is a
# network round trip and the transport's own default suits it, but the chain's
# signatures wait for a person to open a page and answer -- so the side that
# assembles the chain has to be willing to wait seconds, not milliseconds.
#
# It is deliberately longer than the endpoint's own waiting room
# (``client.approval.DEFAULT_TIMEOUT``): when one of the two gives up first, it
# should be the side holding the request, so that a person who is late gets told
# "nobody answered" rather than a caller that quietly failed a chain.  It stays
# under the signing call's own thirty seconds, which core sets and would refuse
# an answer past.
CHAIN_TIMEOUT = 28.0


def wait_for_manifest(path, base_url, timeout=600.0, sign_timeout=CHAIN_TIMEOUT):
    """The fleet, once every endpoint has published its line."""
    from competition.deploy import expected_manifest
    expected = expected_manifest()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            entries = read_manifest(path)
        except (ProtocolError, OSError):
            entries = []
        if len(entries) == expected:
            return Fleet(entries, Path(path).parent, base_url=base_url,
                         timeout=sign_timeout)
        time.sleep(0.2)
    raise SystemExit('no complete manifest at %s' % path)


def wait_for_endpoints(fleet, timeout=600.0):
    """Block until each endpoint with a face answers, or say which one did not."""
    deadline = time.monotonic() + timeout
    for entry in fleet.entries:
        if not serves(entry.role):
            continue
        url = fleet.endpoint_url(entry) + '/healthz'
        while True:
            try:
                if httpx.get(url, timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise SystemExit('endpoint did not answer at %s' % url)
            time.sleep(0.2)


def sessions_for(path):
    """Sessions over the caller list, tolerating a list that is not written yet.

    The list is read again whenever a key is unknown, so the entry can serve before
    its callers have started and still accept them a moment later.
    """
    try:
        return Sessions(read_callers(path), source=path)
    except ProtocolError:
        print('caller list not readable yet at %s; it will be read on first use' % path,
              flush=True)
        return Sessions({}, source=path)


def main():
    run = Path(os.environ.get('ZJJ_RUN', '/run'))
    endpoints = Path(os.environ.get('ZJJ_ENDPOINTS', '/endpoints'))
    manifest = Path(os.environ.get('ZJJ_MANIFEST', str(endpoints / 'roster.jsonl')))
    callers = Path(os.environ.get('ZJJ_CALLERS', '/callers/callers.jsonl'))
    base_url = os.environ.get('ZJJ_ENDPOINT_BASE', 'http://endpoints')
    host = os.environ.get('ZJJ_ENTRY_HOST', '0.0.0.0')
    port = int(os.environ.get('ZJJ_ENTRY_PORT', '8000'))

    fleet = wait_for_manifest(manifest, base_url)
    wait_for_endpoints(fleet)
    if (run / 'auth-w.sqlite').exists():
        print('%s already holds an initialized run, and this deployment has no reopen yet'
              % run, file=sys.stderr)
        return 1
    trusted = initialize(run, fleet=fleet)
    sessions = sessions_for(callers)
    print('trusted entry on %s:%d over %d endpoints' % (host, port, len(fleet.entries)),
          flush=True)
    serve(host, port, TrustedService(trusted, None), sessions)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
