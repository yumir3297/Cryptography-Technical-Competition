"""Run batch accounting through the existing isolated PAY-1 effect ledger."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from competition.profiles.w_seed import initialize
from competition.run_payment_batch import AMOUNT, PROFILE, balances, obtain_execution, run_demo, worker
from competition.support.wire import ProtocolError, raw
from competition.verify_payment_batch import verify
from competition.w_cases import _configure_tool


class PaymentBatchTests(unittest.TestCase):
    def test_public_evidence_reproduces_two_effects_after_restart(self):
        report = run_demo()
        facts = verify(report, raw(report['root_public'], 32))
        self.assertEqual(facts['original_paid_minor'], AMOUNT)
        self.assertEqual(facts['third_paid_minor'], AMOUNT)
        self.assertEqual(facts['total_paid_minor'], report['stages']['final']['spent_minor'])
        self.assertEqual(facts['confirmed_payment_effects'], report['stages']['final']['tool_payments'])

    def test_fully_paid_and_zero_paid_batch_can_be_closed_concurrently(self):
        for paid in (False, True):
            with self.subTest(paid=paid), TemporaryDirectory() as path:
                run = initialize(Path(path), resource_capacity={PROFILE: AMOUNT})
                try:
                    _configure_tool(run, PROFILE, crash_after_commit=paid, drop_before_tool=not paid)
                    payment, lost = obtain_execution(run, run.operations[PROFILE])
                    self.assertIsNone(lost['record'])
                    oid = payment['action']['operation_id']
                    ids = [oid]
                    request = run.w.request_pay_batch(ids, {oid: worker(run, oid)})
                    pending = run.w.settle(PROFILE, oid, lost, worker(run, oid))
                    self.assertEqual(pending['state'], 'BATCH_PENDING')
                    self.assertEqual(balances(run)['reserved_minor'], AMOUNT)
                    _configure_tool(run, PROFILE, crash_after_commit=False, drop_before_tool=False)
                    gateway = run.tool_gateways[PROFILE]
                    certificate = gateway.close_batch(request)['certificate']
                    proofs = [{oid: worker(run, oid)} for _ in range(2)]
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        updates = list(pool.map(lambda proof: run.w.settle_pay_batch(certificate, proof), proofs))
                    self.assertCountEqual([r['existing'] for r in updates], [False, True])
                    if not paid:
                        with self.assertRaisesRegex(ProtocolError, 'PAY_BATCH_CLOSED'):
                            gateway.execute(request['packets'][0])
                    reply = run.w.query_attempt(PROFILE, oid, worker(run, oid, 'QUERY'))
                    gap = run.w.settle(PROFILE, oid, reply, worker(run, oid))
                    self.assertEqual(gap['state'], 'BATCH_DETAIL_REQUIRED')
                    current = balances(run)
                    self.assertEqual(current['reserved_minor'], 0)
                    self.assertEqual(current['spent_minor'], AMOUNT if paid else 0)
                    batch = updates[0]['batch_id']
                    request = run.w.request_pay_batch_detail(batch, oid, worker(run, oid))
                    detail = gateway.batch_detail(request)['detail']
                    settled = run.w.settle_pay_batch_detail(detail, worker(run, oid))
                    self.assertEqual(settled['outcome'], 'SUCCEEDED' if paid else 'FAILED_CONFIRMED')
                    self.assertEqual(balances(run)['spent_minor'], current['spent_minor'])
                    self.assertEqual(balances(run)['tool_payments'], int(paid))
                finally:
                    run.close()
