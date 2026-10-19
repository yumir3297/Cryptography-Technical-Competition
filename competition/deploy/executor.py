"""Independent worker-side executor: claim, execute once, query, settle.

The executor is not the agent.  It has its own key, its own volume and only the
worker side of the flow.  Its recovery rule is the repository's: after an
unknown execution result it queries the original attempt and settles what the
attempt reports; it never calls execute again.  The trusted core's EXEC marker is
the final guard, so a second executor cannot create a second effect.
"""
import argparse
import os
import time
from pathlib import Path

from competition.agent.identity import enroll
from competition.caller.flow import Caller
from competition.deploy import workbench
from competition.support.wire import ProtocolError


def settings():
    return {
        'entry': os.environ.get('ZJJ_ENTRY', 'http://127.0.0.1:8000'),
        'endpoints': os.environ.get('ZJJ_ENDPOINTS', 'http://127.0.0.1'),
        'callers': os.environ.get('ZJJ_CALLERS', '/callers'),
        'keys': Path(os.environ.get('ZJJ_EXECUTOR_KEYS', '/executor')),
        'name': os.environ.get('ZJJ_EXECUTOR_NAME', 'zjj-executor'),
        'gateway': os.environ.get('ZJJ_GATEWAY', 'http://127.0.0.1:8090'),
        'token': os.environ.get('ZJJ_INTERNAL_TOKEN', ''),
    }


def query(caller, operation_id):
    """Read the original attempt; return ``(response, refusal)``."""
    try:
        return caller.step(operation_id, 'query'), None
    except ProtocolError as exc:
        return None, exc.code


def settle(caller, operation_id):
    """Settle whatever the trusted service currently holds for the attempt."""
    try:
        return caller.step(operation_id, 'settle'), None
    except ProtocolError as exc:
        return None, exc.code


LOST_ANSWER = frozenset({'ENTRY_UNAVAILABLE', 'ENTRY_ANSWER'})


def execute(caller, gateway, token, row):
    """One claimed operation, with no blind retry after an unknown exec answer."""
    operation_id = row['operation_id']
    print('executing %s (state %s, exec_consumed=%s)'
          % (workbench.describe(row), row.get('state'), row.get('exec_consumed')),
          flush=True)
    caller.step(operation_id, 'claim')
    response = None
    if row.get('state') == 'STARTED' and row.get('exec_consumed'):
        response, refusal = query(caller, operation_id)
        if refusal:
            print('query refused %s: %s' % (workbench.describe(row), refusal), flush=True)
            workbench.hint(gateway, token, operation_id, 'unknown')
            return
        workbench.hint(gateway, token, operation_id, 'executed')
    else:
        try:
            response = caller.step(operation_id, 'exec')
            workbench.hint(gateway, token, operation_id, 'executed')
        except ProtocolError as exc:
            if exc.code not in LOST_ANSWER:
                print('exec refused %s: %s' % (workbench.describe(row), exc.code), flush=True)
                workbench.hint(gateway, token, operation_id, 'failed')
                return
            # The tool may have run before the answer was lost.  Do not execute
            # again; query the original attempt instead.
            print('exec answer lost for %s: %s; querying original attempt'
                  % (workbench.describe(row), exc.code), flush=True)
            response, refusal = query(caller, operation_id)
            if refusal:
                print('query refused %s: %s' % (workbench.describe(row), refusal), flush=True)
                workbench.hint(gateway, token, operation_id, 'unknown')
                return
            workbench.hint(gateway, token, operation_id, 'executed')
    if isinstance(response, dict) and response.get('reason') == 'EXEC_ALREADY_CONSUMED':
        response, refusal = query(caller, operation_id)
        if refusal:
            print('query refused %s: %s' % (workbench.describe(row), refusal), flush=True)
            workbench.hint(gateway, token, operation_id, 'unknown')
            return
    settled, refusal = settle(caller, operation_id)
    if refusal:
        print('settle refused %s: %s' % (workbench.describe(row), refusal), flush=True)
        workbench.hint(gateway, token, operation_id, 'unknown')
        return
    state = (settled or {}).get('state')
    print('settled %s: %s' % (workbench.describe(row), state), flush=True)
    workbench.hint(gateway, token, operation_id,
                   'settled' if state == 'SETTLED' else 'unknown')


def run(args):
    config = settings()
    if not config['token']:
        raise SystemExit('ZJJ_INTERNAL_TOKEN is required')
    key_path, _line = enroll(config['keys'], config['name'], ['worker'], config['callers'])
    caller = Caller(config['entry'], key_path, config['endpoints'])
    workbench.started(caller)
    workbench.wait_for_gateway(config['gateway'], config['token'])
    print('executor ready: %s' % config['name'], flush=True)
    while True:
        try:
            row = workbench.claim(config['gateway'], config['token'], 'executor')
        except workbench.GatewayUnavailable:
            time.sleep(1.0)
            continue
        if row is None:
            if args.once:
                return 0
            time.sleep(0.5)
            continue
        try:
            execute(caller, config['gateway'], config['token'], row)
        except ProtocolError as exc:
            print('refused %s: %s' % (workbench.describe(row), exc.code), flush=True)
            workbench.hint(config['gateway'], config['token'], row['operation_id'], 'failed')
        except Exception as exc:
            print('executor error %s: %s' % (workbench.describe(row), exc), flush=True)
            workbench.hint(config['gateway'], config['token'], row['operation_id'], 'failed')
        finally:
            workbench.release(config['gateway'], config['token'], 'executor',
                              row['operation_id'])
        if args.once:
            return 0
        time.sleep(0.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description='ZJJ-CORE independent executor (demo)')
    parser.add_argument('--once', action='store_true', help='process at most one operation')
    args = parser.parse_args(argv)
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
