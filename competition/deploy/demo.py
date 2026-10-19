"""Demo driver: one operation end to end, split the way the flow is split.

A demo, not part of the product surface: a real UI drives the same calls.  It
exists so a deployment can be *seen* to work -- the holder proposes and reads, the
worker claims, executes and settles, and the two hand the operation id over
through a file, because they are two processes on purpose and handing the id over
is what an orchestrator does.

Each side makes its own credential here and puts its own line in the shared caller
list, exactly as an operator would with ``--keygen``.  Nothing about either side is
special: both are :class:`~competition.caller.flow.Caller`.
"""
import json
import os
import time
from pathlib import Path

from competition.caller import announce
from competition.caller.flow import Caller
from competition.support.wire import ProtocolError

HOLDER = 'H'
WORKER = 'worker'


def add_line(directory, line):
    """Put one caller's line in the shared list, once."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'callers.jsonl'
    text = json.dumps(line, ensure_ascii=False, sort_keys=True)
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    if text + '\n' not in existing:
        with path.open('a', encoding='utf-8') as stream:
            stream.write(text + '\n')
    return path


def started(caller, timeout=600.0):
    """Hold until the entry answers, so a demo does not race its own deployment."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return caller.start()
        except ProtocolError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def wait_for(path, timeout=600.0):
    """The text one side left for the other, once it is there."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding='utf-8').strip()
        time.sleep(0.2)
    raise SystemExit('%s never appeared' % path)


def holder(caller, profile, handoff):
    """Propose, accept, hand the operation over, and read how it finished."""
    operation_id = caller.submit(profile, None)['operation_id']
    print('operation %s' % operation_id, flush=True)
    for step in ('prepare', 'accept'):
        caller.step(operation_id, step)
    print('accepted; handing it to the worker side', flush=True)
    handoff.write_text(operation_id + '\n', encoding='utf-8')
    wait_for(Path(str(handoff) + '.done'))
    view = caller.step(operation_id, 'status')
    print('status %s' % json.dumps(
        {key: view[key] for key in ('acceptance_state', 'dispatch_state', 'effect_state',
                                    'exec_consumed')}, ensure_ascii=False), flush=True)
    return view


def worker(caller, handoff):
    """Claim, execute and settle the operation the holder handed over."""
    operation_id = wait_for(handoff)
    print('picked up %s' % operation_id, flush=True)
    caller.step(operation_id, 'claim')
    caller.step(operation_id, 'exec')
    settled = caller.step(operation_id, 'settle')
    Path(str(handoff) + '.done').write_text(json.dumps(settled) + '\n', encoding='utf-8')
    print('settled %s' % settled['state'], flush=True)
    return settled


def main():
    side = os.environ['ZJJ_SIDE']
    directory = Path(os.environ.get('ZJJ_CALLERS', '/callers'))
    name = os.environ.get('ZJJ_NAME', 'caller-' + side.lower())
    profile = os.environ.get('ZJJ_PROFILE', 'PAY-1')
    handoff = Path(os.environ.get('ZJJ_HANDOFF', str(directory / 'demo-operation')))
    line = announce(directory, name, [side])
    print('%s in %s' % (name, add_line(directory, line)), flush=True)
    caller = Caller(os.environ.get('ZJJ_ENTRY', 'http://caddy'),
                    directory / (name + '.key'),
                    os.environ.get('ZJJ_ENDPOINTS', 'http://endpoints'))
    started(caller)
    if side == HOLDER:
        holder(caller, profile, handoff)
    else:
        worker(caller, handoff)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
