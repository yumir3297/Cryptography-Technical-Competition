"""A scripted MCP client: the deployment's agent-side end-to-end check.

It is not the dsh agent.  It speaks the same two-tool MCP surface with the same
bearer token, so a deployment can prove propose -> independent operator ->
independent executor -> settled without a model in the loop.  The dsh plugin is
installed beside it and consumes the same ``/zjj/events`` feed.
"""
import argparse
import asyncio
import json
import os
import sys
import time

from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

DEFAULT_INTENT = {
    'PAY-1': {'order_id': 'ord', 'stage': 'pay', 'payer': 'payer', 'payee': 'payee',
              'amount_minor': '2000'},
    'IND-DEMO-1': {'line_id': 'demo-line-a', 'station_id': 'demo-check-1',
                   'unit_id': 'unit-a', 'batch_id': 'batch-a', 'inspection_cycle': '1',
                   'phase': 'INITIAL', 'route': 'RELEASE'},
    'MED-DEMO-1': {'synthetic_patient_id': 'patient-a', 'encounter_id': 'encounter-a',
                   'template_id': 'DEMO-ORDER-A'},
}
TERMINAL = {'SETTLED', 'HALTED', 'CANCELED', 'UNAVAILABLE'}


async def drive(url, token, profile, intent, timeout):
    http = create_mcp_http_client(headers={'Authorization': 'Bearer ' + token})
    try:
        transport = streamable_http_client(url, http_client=http)
        async with Client(transport) as client:
            proposed = await client.call_tool('zjj_propose',
                                              {'profile': profile, 'intent': intent})
            if proposed.is_error:
                print('propose refused: %s' % proposed.content[0].text, flush=True)
                return 1
            operation_id = proposed.structured_content['operation_id']
            print('proposed %s (%s)' % (operation_id, profile), flush=True)
            deadline = time.monotonic() + timeout
            seen = None
            while time.monotonic() < deadline:
                status = await client.call_tool('zjj_status',
                                                {'operation_id': operation_id})
                if status.is_error:
                    print('status refused: %s' % status.content[0].text, flush=True)
                    return 1
                row = status.structured_content
                marker = (row['state'], row.get('effect_state'),
                          row.get('exec_consumed'), row.get('attempt_id'))
                if marker != seen:
                    seen = marker
                    print('  %-10s effect=%s receipt=%s exec_consumed=%s'
                          % (row['state'], row.get('effect_state'),
                             row.get('receipt_state'), row.get('exec_consumed')),
                          flush=True)
                if row['state'] in TERMINAL:
                    return 0 if (row['state'] == 'SETTLED'
                                 and row.get('effect_state') == 'SUCCEEDED') else 1
                await asyncio.sleep(0.5)
            print('timed out waiting for a terminal state', flush=True)
            return 1
    finally:
        await http.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(description='scripted ZJJ-CORE MCP client')
    parser.add_argument('--profile', default='PAY-1', choices=sorted(DEFAULT_INTENT))
    parser.add_argument('--intent', default=None, help='JSON object overriding the default intent')
    parser.add_argument('--timeout', type=float, default=120.0)
    args = parser.parse_args(argv)
    url = os.environ.get('ZJJ_MCP_URL', 'http://127.0.0.1:8090/mcp')
    token = os.environ.get('ZJJ_AGENT_TOKEN', '')
    if not token:
        raise SystemExit('ZJJ_AGENT_TOKEN is required')
    intent = DEFAULT_INTENT[args.profile]
    if args.intent:
        intent = json.loads(args.intent)
    return asyncio.run(drive(url, token, args.profile, intent, args.timeout))


if __name__ == '__main__':
    sys.exit(main())
