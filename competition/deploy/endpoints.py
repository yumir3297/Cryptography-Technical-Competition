"""Bring up every endpoint this machine runs: the signing services, one per key.

Each endpoint is its own process with its own key, because that is why the
endpoints exist at all -- one process holding several roles' keys would put them
back in one place, which is the arrangement this whole round was about leaving.

Startup is idempotent on purpose.  A deployment restarts its containers, and a
restart has to find the same credentials and the same manifest rather than a
second set, so a credential already on the volume is announced from the key
itself instead of being regenerated.  The manifest is rebuilt from whatever is
there every time, and the tool keys are made here too: the tools are credentials
without a service, and this is the container that owns their directory.

Only public halves reach the manifest.  The private halves stay in ``/endpoints``,
and nothing here logs, copies or returns one.
"""
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from competition.client.keys import generate, key_file_name, metadata
from competition.client.signer import load_role_key
from competition.deploy import places, serves
from competition.server.roster import endpoint_port

DIRECTORY = Path(os.environ.get('ZJJ_ENDPOINTS', '/endpoints'))
HOST = os.environ.get('ZJJ_ENDPOINT_HOST', '0.0.0.0')
MANIFEST = DIRECTORY / 'roster.jsonl'
# The roles whose signatures are a person's decision rather than a step a page
# drives.  Their endpoints park each request in the waiting room, so a page can
# show what is being asked and take a yes or a no.  The two roles a page drives
# step by step are left alone: a person already pressed their button.
APPROVAL_ROLES = frozenset({'G', 'U', 'V', 'X'})


def announce(profile, role):
    """Make this endpoint's key if it has none, and return its public line."""
    path = DIRECTORY / key_file_name(profile, role)
    if not path.exists():
        return generate(DIRECTORY, profile, role)
    key = load_role_key(path)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return metadata(profile, role, public)


def serve_argv(profile, role):
    """The command that serves one endpoint's HTTP face on the port it implies."""
    argv = [sys.executable, '-m', 'competition.client', '--directory', str(DIRECTORY)]
    if profile is not None:
        argv += ['--profile', profile]
    if role in APPROVAL_ROLES:
        argv += ['--await-approval']
    return argv + ['--alias', role, '--serve-http', '--host', HOST,
                   '--port', str(endpoint_port(profile, role))]


def write_manifest(lines):
    """Publish the manifest whole, so a reader never sees half of one."""
    pending = MANIFEST.with_suffix('.jsonl.pending')
    pending.write_text(''.join(json.dumps(line, ensure_ascii=False, sort_keys=True) + '\n'
                               for line in lines), encoding='utf-8')
    pending.replace(MANIFEST)
    return MANIFEST


def supervise(children, stopping):
    """Watch the children until one dies or the process is asked to stop.

    The cleanup runs on an ordinary exit and on a caught signal alike, because a
    supervisor that walks away from its children leaves them orphaned: they keep
    the ports they hold, and the next start on this machine fails with "address
    already in use" for reasons nothing in the logs explains.
    """
    try:
        while not stopping.is_set():
            for child in children:
                code = child.poll()
                if code is not None:
                    print('an endpoint exited with %s' % code, file=sys.stderr)
                    return 1
            stopping.wait(0.5)
        return 0
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=10)


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    lines = [announce(profile, role) for profile, role in places()]
    print('%d credentials, manifest at %s' % (len(lines), write_manifest(lines)), flush=True)
    children = [subprocess.Popen(serve_argv(profile, role))
                for profile, role in places() if serves(role)]
    stopping = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stopping.set())
    return supervise(children, stopping)


if __name__ == '__main__':
    raise SystemExit(main())
