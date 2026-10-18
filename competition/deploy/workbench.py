"""Small shared helpers for the two independent workbench callers.

The operator and executor are not agent-side: each owns its own key, its own
volume and its own side of the flow.  They share only the public caller list and
the gateway's internal queue, which is a work hand-off, never an authority.
"""
import json
import time

import httpx

from competition.support.wire import ProtocolError


class GatewayUnavailable(RuntimeError):
    """The agent gateway did not answer, or answered with a refusal."""


def internal(gateway, token, method, path, payload=None, *, timeout=15.0):
    """One authenticated call to the gateway's internal face."""
    url = str(gateway).rstrip('/') + path
    headers = {'Authorization': 'Bearer ' + token}
    try:
        reply = httpx.request(method, url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise GatewayUnavailable(str(exc)) from exc
    if reply.status_code == 204:
        return None
    try:
        body = reply.json()
    except ValueError as exc:
        raise GatewayUnavailable('gateway answer is not JSON') from exc
    if reply.status_code != 200:
        code = body.get('deny') if isinstance(body, dict) else None
        raise GatewayUnavailable(code or 'GATEWAY_DENY')
    return body


def claim(gateway, token, role):
    return internal(gateway, token, 'POST', '/internal/queue/claim', {'role': role})


def release(gateway, token, role, operation_id):
    try:
        internal(gateway, token, 'POST', '/internal/queue/release',
                 {'role': role, 'operation_id': operation_id})
    except GatewayUnavailable:
        pass


def hint(gateway, token, operation_id, stage):
    try:
        return internal(gateway, token, 'POST',
                        '/internal/operations/%s/hint' % operation_id,
                        {'stage': stage})
    except GatewayUnavailable:
        # The gateway's own poller will read the projection later; a lost hint is
        # a lost wake-up, not a lost business fact.
        return None


def wait_for_gateway(gateway, token, timeout=600.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            internal(gateway, token, 'GET', '/internal/healthz', timeout=2.0)
            return
        except GatewayUnavailable:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def started(caller, timeout=600.0):
    """Hold until the trusted entry answers, so a workbench does not race it."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return caller.start()
        except ProtocolError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def describe(row):
    return '%s %s' % (row.get('operation_id'), row.get('profile'))


def json_line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
