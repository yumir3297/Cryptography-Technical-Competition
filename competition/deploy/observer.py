"""The deployment's watcher: an observer caller that prints every step.

This is the demonstration's outside reader.  It holds a credential of its own --
listed for the ``observer`` side, which drives nothing -- opens a session like any
other caller, and subscribes to the trusted entry's read-only observation stream,
printing one line per step until the run ends.  It is a stand-in for the display
program a real deployment would put here; it shows what such a program sees, and
that it sees it without being able to advance anything.

Nothing is signed and no business field is read: the stream it consumes is already
redacted and marked non-evidence by :mod:`competition.server.observe`.  Startup is
idempotent, like the other callers': it announces its key from the file if one is
already there rather than making a second credential.
"""
import json
import os
import time
from pathlib import Path

import httpx

from competition.caller import announce
from competition.caller.session import Session
from competition.deploy.demo import add_line
from competition.support.wire import ProtocolError

# The step kinds worth a human line; registration and bootstrap noise is skipped.
# A run is watched until one of the final kinds arrives.
STEPS = ('CANDIDATE_SUBMITTED', 'CHAIN_ASSEMBLED', 'STEP_CHALLENGED', 'STEP_PROVED',
         'AUTHORIZED_GUARD', 'PUBLICATION', 'PREPARED', 'CHALLENGE_ISSUED',
         'ACCEPT_COMMITTED', 'RECEIPT_SIGNED', 'RECEIPT_PENDING', 'CLAIMED',
         'EXEC_DISPATCHED', 'QUERY_DISPATCHED', 'TOOL_RESPONDED', 'SETTLED',
         'CANCELED', 'HALTED', 'READ_PROJECTED')
FINAL = frozenset({'SETTLED', 'HALTED', 'CANCELED'})
# How long to wait for the entry and for a run before giving up on a demo.
DEFAULT_TIMEOUT = 600.0


def started(session, timeout=DEFAULT_TIMEOUT):
    """Hold until the entry answers, so a watcher does not race its deployment."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return session.open()
        except ProtocolError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def watch(session, entry, *, until=DEFAULT_TIMEOUT):
    """Print one line per committed step until the run ends (or ``until`` elapses).

    Returns the number of steps printed.  ``session`` only needs a live ``token``;
    the entry is read, never written.
    """
    url = str(entry).rstrip('/') + '/api/observe/stream?after=0'
    headers = {'authorization': 'Bearer ' + session.token}
    deadline = time.monotonic() + until
    steps = 0
    with httpx.stream('GET', url, headers=headers, timeout=30.0) as reply:
        if reply.status_code != 200:
            reply.read()
            raise ProtocolError('OBSERVE_DENY')
        for line in reply.iter_lines():
            if time.monotonic() > deadline:
                break
            if not line.startswith('data: '):
                continue
            event = json.loads(line[len('data: '):])
            if event.get('kind') not in STEPS:
                continue
            steps += 1
            print('%4d %-8s %-20s %s' % (event['seq'], event['profile'], event['kind'],
                                         event.get('stage') or ''), flush=True)
            if event['kind'] in FINAL:
                return steps
    return steps


def main():
    directory = Path(os.environ.get('ZJJ_CALLERS', '/callers'))
    name = os.environ.get('ZJJ_NAME', 'caller-observer')
    entry = os.environ.get('ZJJ_ENTRY', 'http://caddy')
    until = float(os.environ.get('ZJJ_OBSERVE_TIMEOUT', str(DEFAULT_TIMEOUT)))
    line = announce(directory, name, ['observer'])
    print('%s in %s' % (name, add_line(directory, line)), flush=True)
    session = Session(entry, directory / (name + '.key'))
    started(session, until)
    print('watching %s' % entry, flush=True)
    steps = watch(session, entry, until=until)
    print('watched %d steps' % steps, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
