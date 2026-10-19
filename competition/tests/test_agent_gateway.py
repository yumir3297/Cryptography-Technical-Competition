"""The gateway end to end: MCP tools, a real trusted flow, and redacted feedback."""
import asyncio
import json
import unittest

import httpx
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from competition.agent import policy
from competition.agent.service import GatewayService
from competition.support.wire import ProtocolError
from competition.tests.agent_case import AGENT_TOKEN, INTERNAL_TOKEN, AgentStack

PAY_INTENT = {'order_id': 'ord', 'stage': 'pay', 'payer': 'payer', 'payee': 'payee',
              'amount_minor': '2000'}


def mcp_call(stack, tool, arguments):
    """One tool call over real Streamable HTTP with the agent bearer token."""
    async def run():
        http = create_mcp_http_client(headers={'Authorization': 'Bearer ' + AGENT_TOKEN})
        try:
            transport = streamable_http_client(stack.gateway.base + '/mcp',
                                               http_client=http)
            async with Client(transport) as client:
                return await client.call_tool(tool, arguments)
        finally:
            await http.aclose()
    return asyncio.run(run())


def mcp_tools(stack):
    async def run():
        http = create_mcp_http_client(headers={'Authorization': 'Bearer ' + AGENT_TOKEN})
        try:
            transport = streamable_http_client(stack.gateway.base + '/mcp',
                                               http_client=http)
            async with Client(transport) as client:
                return [tool.name for tool in (await client.list_tools()).tools]
        finally:
            await http.aclose()
    return asyncio.run(run())


class GatewayHttpTests(unittest.TestCase):
    def setUp(self):
        self.stack = AgentStack()

    def tearDown(self):
        self.stack.close()

    def test_the_mcp_surface_is_exactly_propose_and_status(self):
        self.assertEqual(mcp_tools(self.stack), ['zjj_propose', 'zjj_status'])

    def test_two_tokens_two_scopes(self):
        base = self.stack.gateway.base
        self.assertEqual(httpx.get(base + '/healthz', timeout=5).status_code, 200)
        self.assertEqual(httpx.get(base + '/zjj/events', timeout=5).status_code, 401)
        self.assertEqual(httpx.get(base + '/zjj/events', timeout=5,
                                   headers={'Authorization': 'Bearer ' + AGENT_TOKEN}
                                   ).status_code, 200)
        self.assertEqual(httpx.get(base + '/internal/healthz', timeout=5).status_code, 401)
        self.assertEqual(httpx.get(base + '/internal/healthz', timeout=5,
                                   headers={'Authorization': 'Bearer ' + AGENT_TOKEN}
                                   ).status_code, 401)
        self.assertEqual(httpx.get(base + '/internal/healthz', timeout=5,
                                   headers={'Authorization': 'Bearer ' + INTERNAL_TOKEN}
                                   ).status_code, 200)
        self.assertEqual(httpx.post(base + '/mcp', json={}, timeout=5,
                                    headers={'Authorization': 'Bearer ' + INTERNAL_TOKEN}
                                    ).status_code, 401)

    def test_a_full_flow(self):
        proposed = mcp_call(self.stack, 'zjj_propose',
                            {'profile': 'PAY-1', 'intent': PAY_INTENT})
        self.assertFalse(proposed.is_error)
        handle = proposed.structured_content['operation_id']
        self.assertEqual(proposed.structured_content['state'], 'PENDING')

        duplicate = mcp_call(self.stack, 'zjj_propose',
                             {'profile': 'PAY-1', 'intent': PAY_INTENT})
        self.assertTrue(duplicate.structured_content['deduplicated'])
        self.assertEqual(duplicate.structured_content['operation_id'], handle)

        # The tool returned before the trusted side answered.  The handle resolves
        # to the operation the way the pushed notice would tell the agent.
        operation_id = self.stack.await_submission(handle)
        accepted = [event for event in self.stack.service.events(operation_id=handle)
                    if event['kind'] == 'SUBMISSION_ACCEPTED']
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['detail']['operation_id'], operation_id)

        before = mcp_call(self.stack, 'zjj_status', {'operation_id': handle})
        self.assertFalse(before.is_error)
        self.assertEqual(before.structured_content['state'], 'SUBMITTED')

        operator = self.stack.caller('operator')
        operator.step(operation_id, 'prepare')
        operator.step(operation_id, 'accept')
        accepted = mcp_call(self.stack, 'zjj_status', {'operation_id': operation_id})
        self.assertEqual(accepted.structured_content['state'], 'ACCEPTED')
        self.assertEqual(accepted.structured_content['receipt_state'], 'SIGNED')

        executor = self.stack.caller('executor')
        executor.step(operation_id, 'claim')
        executor.step(operation_id, 'exec')
        executor.step(operation_id, 'settle')
        settled = mcp_call(self.stack, 'zjj_status', {'operation_id': operation_id})
        self.assertEqual(settled.structured_content['state'], 'SETTLED')
        self.assertEqual(settled.structured_content['effect_state'], 'SUCCEEDED')

    def test_a_submission_that_has_not_resolved_reads_as_pending(self):
        # The trusted side has not answered yet: the handle is all the agent has,
        # and it must read as pending rather than as an unknown operation.
        row, should_submit = self.stack.journal.begin_submission('PAY-1', 'pending-digest')
        self.assertTrue(should_submit)
        self.assertEqual(row['state'], 'SUBMITTING')
        status = self.stack.service.status('pending-digest')
        self.assertEqual(status['state'], 'PENDING')
        self.assertEqual(status['operation_id'], 'pending-digest')
        self.assertEqual(status['profile'], 'PAY-1')

    def test_a_submission_the_trusted_side_refused_reads_as_denied(self):
        self.stack.journal.begin_submission('PAY-1', 'denied-digest')
        self.stack.journal.mark_submission_denied('PAY-1', 'denied-digest', 'BINDING')
        status = self.stack.service.status('denied-digest')
        self.assertEqual(status['state'], 'DENIED')
        self.assertIn('BINDING', status['reason'])

    def test_status_never_carries_the_commit_or_business_payload(self):
        proposed = mcp_call(self.stack, 'zjj_propose',
                            {'profile': 'PAY-1', 'intent': dict(PAY_INTENT)})
        operation_id = self.stack.await_submission(proposed.structured_content['operation_id'])
        operator = self.stack.caller('operator')
        operator.step(operation_id, 'prepare')
        operator.step(operation_id, 'accept')
        status = mcp_call(self.stack, 'zjj_status', {'operation_id': operation_id})
        self.assertFalse(status.is_error)
        row = status.structured_content
        self.assertTrue({'operation_id', 'profile', 'state', 'acceptance_state',
                         'receipt_state', 'dispatch_state', 'effect_state',
                         'attempt_id', 'exec_consumed', 'commit_record_ref',
                         'read_at', 'read_error', 'note'} <= set(row))
        self.assertNotIn('commit', {key.lower() for key in row})
        self.assertNotIn('action', row)
        self.assertNotIn('payload', row)

    def test_a_candidate_with_a_role_or_key_field_is_refused(self):
        result = mcp_call(self.stack, 'zjj_propose',
                          {'profile': 'PAY-1', 'intent': dict(PAY_INTENT, role='H')})
        self.assertTrue(result.is_error)
        self.assertIn('INTENT_FIELDS', result.content[0].text)

    def test_unknown_operation_is_a_tool_error(self):
        result = mcp_call(self.stack, 'zjj_status', {'operation_id': 'not-an-operation'})
        self.assertTrue(result.is_error)
        self.assertIn('OPERATION_UNKNOWN', result.content[0].text)

    def test_the_gateway_has_no_advance_or_signing_method(self):
        self.assertEqual(policy.ALLOWED_STEPS, frozenset({'status'}))
        for forbidden in ('prepare', 'accept', 'claim', 'execute_once', 'settle',
                          'cancel', 'sign', 'answer'):
            self.assertFalse(hasattr(self.stack.service, forbidden), forbidden)


class GatewayDegradedTests(unittest.TestCase):
    """Recovery paths that need a fresh stack: unknown means unavailable, not failed."""

    def setUp(self):
        self.stack = AgentStack()

    def tearDown(self):
        self.stack.close()

    def test_an_operation_the_trusted_side_lost_becomes_unavailable(self):
        self.stack.journal.begin_submission('PAY-1', 'ghost-digest')
        self.stack.journal.mark_submitted('PAY-1', 'ghost-digest', 'ghost-op')
        self.stack.service.status_grace = 0
        status = self.stack.service.status('ghost-op')
        self.assertEqual(status['state'], 'UNAVAILABLE')
        self.assertIn('last known state retained', status['reason'])
        events = self.stack.service.events(operation_id='ghost-op')
        self.assertEqual(events[-1]['kind'], 'UNAVAILABLE')

    def test_a_read_failure_keeps_the_last_known_projection(self):
        proposed = self.stack.service.propose('PAY-1', dict(PAY_INTENT))
        operation_id = self.stack.await_submission(proposed['operation_id'])
        operator = self.stack.caller('operator')
        operator.step(operation_id, 'prepare')
        operator.step(operation_id, 'accept')
        accepted = self.stack.service.status(operation_id)
        self.assertEqual(accepted['state'], 'ACCEPTED')

        def broken(call):
            raise ProtocolError('ENTRY_UNAVAILABLE')

        original = self.stack.service._trusted
        self.stack.service._trusted = broken
        try:
            degraded = self.stack.service.status(operation_id)
        finally:
            self.stack.service._trusted = original
        self.assertEqual(degraded['state'], 'ACCEPTED')
        self.assertEqual(degraded['read_error'], 'ENTRY_UNAVAILABLE')
        self.assertGreaterEqual(degraded['read_failures'], 1)
        events = self.stack.service.events(operation_id=operation_id)
        self.assertEqual(events[-1]['kind'], 'READ_FAILED')


if __name__ == '__main__':
    unittest.main()
