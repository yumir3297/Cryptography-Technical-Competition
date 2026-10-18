"""Independent H-side operator: prepare and accept what the agent proposed.

This is a demonstration stand-in for the holder's application step, not a human
approval surface.  The business approvals (U/V) are still the trusted initiator's
seeded signatures; the operator only obtains the H application proof from the H
endpoint, exactly as the existing demo holder does.  In a real deployment this
process would be replaced by an authenticated approval UI.

The operator never sees or trusts the agent's MCP tools.  It claims one operation
id from the gateway's internal queue and drives only ``prepare`` and ``accept``.
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
        'keys': Path(os.environ.get('ZJJ_OPERATOR_KEYS', '/operator')),
        'name': os.environ.get('ZJJ_OPERATOR_NAME', 'zjj-operator'),
        'gateway': os.environ.get('ZJJ_GATEWAY', 'http://127.0.0.1:8090'),
        'token': os.environ.get('ZJJ_INTERNAL_TOKEN', ''),
    }


def _already_accepted(caller, operation_id):
    """A lost accept answer is not a failure: ask the entry for the current view."""
    try:
        return caller.step(operation_id, 'status')
    except ProtocolError:
        return None


def approve(caller, gateway, token, row):
    """Drive prepare and accept for one claimed operation."""
    operation_id = row['operation_id']
    caller.step(operation_id, 'prepare')
    workbench.hint(gateway, token, operation_id, 'prepared')
    try:
        accepted = caller.step(operation_id, 'accept')
    except ProtocolError as exc:
        if exc.code not in ('ENTRY_UNAVAILABLE', 'ENTRY_ANSWER'):
            raise
        view = _already_accepted(caller, operation_id)
        if view is None or view.get('acceptance_state') != 'COMMITTED':
            raise
        accepted = view
    workbench.hint(gateway, token, operation_id, 'accepted')
    print('accepted %s; receipt %s'
          % (workbench.describe(row), accepted.get('receipt_state')), flush=True)
    return accepted


def run(args):
    config = settings()
    if not config['token']:
        raise SystemExit('ZJJ_INTERNAL_TOKEN is required')
    key_path, _line = enroll(config['keys'], config['name'], ['H'], config['callers'])
    caller = Caller(config['entry'], key_path, config['endpoints'])
    workbench.started(caller)
    workbench.wait_for_gateway(config['gateway'], config['token'])
    print('operator ready: %s' % config['name'], flush=True)
    manual = args.manual or os.environ.get('ZJJ_OPERATOR_AUTO', '1') != '1'
    while True:
        try:
            row = workbench.claim(config['gateway'], config['token'], 'operator')
        except workbench.GatewayUnavailable:
            time.sleep(1.0)
            continue
        if row is None:
            if args.once:
                return 0
            time.sleep(0.5)
            continue
        print('claimed %s' % workbench.describe(row), flush=True)
        if manual:
            answer = input('approve this operation? [y/N] ').strip().lower()
            if answer != 'y':
                workbench.release(config['gateway'], config['token'], 'operator',
                                  row['operation_id'])
                if args.once:
                    return 0
                continue
        try:
            approve(caller, config['gateway'], config['token'], row)
        except ProtocolError as exc:
            print('refused %s: %s' % (workbench.describe(row), exc.code), flush=True)
            workbench.hint(config['gateway'], config['token'], row['operation_id'], 'failed')
        except Exception as exc:
            print('operator error %s: %s' % (workbench.describe(row), exc), flush=True)
            workbench.hint(config['gateway'], config['token'], row['operation_id'], 'failed')
        finally:
            workbench.release(config['gateway'], config['token'], 'operator',
                              row['operation_id'])
        if args.once:
            return 0
        time.sleep(0.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description='ZJJ-CORE independent operator (demo)')
    parser.add_argument('--once', action='store_true', help='process at most one operation')
    parser.add_argument('--manual', action='store_true', help='ask before approving')
    args = parser.parse_args(argv)
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
