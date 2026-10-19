"""The independent operator and executor: queue hand-off and no blind re-execution."""
import unittest

from competition.deploy import executor, operator, workbench
from competition.tests.agent_case import INTERNAL_TOKEN, AgentStack

PAY_INTENT = {'order_id': 'ord', 'stage': 'pay', 'payer': 'payer', 'payee': 'payee',
              'amount_minor': '2000'}


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.stack = AgentStack()

    def tearDown(self):
        self.stack.close()

    def propose(self):
        proposal = self.stack.service.propose('PAY-1', dict(PAY_INTENT))
        # The submit is carried off the request thread; the operation id arrives
        # the way the pushed notice does.
        operation_id = self.stack.await_submission(proposal['operation_id'])
        return dict(proposal, operation_id=operation_id)

    def test_the_internal_queue_hands_one_operation_to_each_side(self):
        proposal = self.propose()
        claimed = workbench.claim(self.stack.gateway.base, INTERNAL_TOKEN, 'operator')
        self.assertEqual(claimed['operation_id'], proposal['operation_id'])
        self.assertEqual(claimed['state'], 'SUBMITTED')
        workbench.release(self.stack.gateway.base, INTERNAL_TOKEN, 'operator',
                          proposal['operation_id'])
        # No accepted operation yet, so the executor side has nothing.
        self.assertIsNone(workbench.claim(self.stack.gateway.base, INTERNAL_TOKEN,
                                          'executor'))

    def test_operator_accepts_and_executor_settles_through_the_queue(self):
        proposal = self.propose()
        operation_id = proposal['operation_id']
        operator_caller = self.stack.caller('operator')
        row = workbench.claim(self.stack.gateway.base, INTERNAL_TOKEN, 'operator')
        operator.approve(operator_caller, self.stack.gateway.base, INTERNAL_TOKEN, row)
        accepted = self.stack.service.status(operation_id)
        self.assertEqual(accepted['state'], 'ACCEPTED')

        executor_caller = self.stack.caller('executor')
        row = workbench.claim(self.stack.gateway.base, INTERNAL_TOKEN, 'executor')
        self.assertEqual(row['operation_id'], operation_id)
        executor.execute(executor_caller, self.stack.gateway.base, INTERNAL_TOKEN, row)
        settled = self.stack.service.status(operation_id)
        self.assertEqual(settled['state'], 'SETTLED')
        self.assertEqual(settled['effect_state'], 'SUCCEEDED')
        kinds = [event['kind'] for event in self.stack.service.events(operation_id=operation_id)]
        self.assertIn('ACCEPTED', kinds)
        self.assertIn('SETTLED', kinds)

    def test_executor_recovers_by_querying_an_already_consumed_attempt(self):
        proposal = self.propose()
        operation_id = proposal['operation_id']
        operator_caller = self.stack.caller('operator')
        operator_caller.step(operation_id, 'prepare')
        operator_caller.step(operation_id, 'accept')
        executor_caller = self.stack.caller('executor')
        executor_caller.step(operation_id, 'claim')
        executor_caller.step(operation_id, 'exec')
        # The trusted side now holds the exec response, so a restart must query,
        # not execute a second time.
        row = {'operation_id': operation_id, 'profile': 'PAY-1', 'state': 'STARTED',
               'exec_consumed': True}
        executor.execute(executor_caller, self.stack.gateway.base, INTERNAL_TOKEN, row)
        settled = self.stack.service.status(operation_id)
        self.assertEqual(settled['state'], 'SETTLED')
        self.assertEqual(settled['effect_state'], 'SUCCEEDED')


if __name__ == '__main__':
    unittest.main()
