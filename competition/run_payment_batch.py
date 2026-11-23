"""Run three synthetic PAY-1 orders through CommonW and its isolated payment tool."""

import argparse
import copy
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from competition.profiles.w_seed import initialize
from competition.support.wire import ProtocolError, b64, canonical, digest, require
from competition.w_cases import (
    _configure_tool, accept_operation, recover_fixture, save_recovery_fixture, tool_snapshot,
)


PROFILE = "PAY-1"
AMOUNT = 2000  # PAY-1 seed uses CNY cents.


def additional_order(run, order_id):
    """Register an independent order/task with the controller and original source."""
    op = run.clone(PROFILE)
    payload = op["action"]["payload"]
    scope = op["action"]["scope"]
    prefix = [scope[k] for k in ("domain", "tenant", "scenario")]
    with run.store.db() as db:
        task = run.store.current(db, PROFILE, "TASK", prefix + [op["task_id"]])["record"]
        evidence = run.store.current(db, PROFILE, "ORDER", prefix + [payload["order_id"], payload["stage"]])["record"]
    task_id = b64(os.urandom(16))
    task["value"].update(task_id=task_id, order_id=order_id)
    source = evidence["value"]["source_envelope"]
    source["body"]["id"] = b64(os.urandom(16))
    source["body"]["payload"]["order_id"] = order_id
    source["sig"] = b64(run.actors[PROFILE]["E"].key.sign(canonical(
        ["ZJJ-SIG-v1", source["protected"], source["body"]])))
    evidence["value"]["source_ref"] = digest(["ZJJ-OBJ-v1", source["protected"], source["body"]])
    run.base.publish(PROFILE, "TASK", prefix + [task_id], task)
    run.base.publish(PROFILE, "ORDER", prefix + [order_id, payload["stage"]], evidence)
    op["task_id"] = task_id
    op["scene_key"] = payload["order_id"] = order_id
    return op


def balances(run):
    """Independent read-only views of W's signed-resource scope and the payment effect table."""
    with run.store.db() as db:
        resource = db.execute("SELECT capacity, reserved, spent FROM w_resource WHERE profile=?", (PROFILE,)).fetchone()
        ops = db.execute("SELECT effect_state FROM w_operation WHERE profile=?", (PROFILE,)).fetchall()
        intent_count = db.execute("SELECT count(*) FROM w_intent WHERE profile=?", (PROFILE,)).fetchone()[0]
    effects = tool_snapshot(run, PROFILE)["effects"]["payments"]
    capacity, reserved, spent = resource
    paid = sum(int(row["payload"]["amount_minor"]) for row in effects)
    return {"capacity_minor": capacity, "reserved_minor": reserved, "spent_minor": spent,
            "available_minor": capacity - reserved - spent, "tool_payments": len(effects),
            "tool_paid_minor": paid, "unknown_orders": sum(row[0] == "UNKNOWN" for row in ops),
            "protected_intents": intent_count}


def worker(run, oid, purpose="SETTLE"):
    return run.worker_proof(PROFILE, oid, purpose)


def approved_order(run, template):
    # PAY derives its actual assessment from C/E data, as of this cutoff.
    # Each new request gets a fresh review; source expiry still bounds its life.
    op = copy.deepcopy(template)
    op["assessment"]["value"]["cutoff"] = str(int(time.time()))
    return run.fork_operation(PROFILE, op)


def obtain_execution(run, op):
    oid, receipt = accept_operation(run, PROFILE, op)
    attempt = run.w.claim(PROFILE, oid, worker(run, oid, "CLAIM"))
    result = run.w.execute_once(PROFILE, oid, worker(run, oid, "EXECUTE"))
    with run.store.db() as db:
        row = db.execute("SELECT packet FROM w_outbox WHERE profile=? AND oid=?", (PROFILE, oid)).fetchone()
    claim = json.loads(row["packet"])["claim"]
    return {"action": op["action"], "acceptance": receipt["acceptance"],
            "attempt_id": attempt["attempt_id"], "dispatch_claim": claim}, result


def reject_order(run, op, expected):
    try:
        accept_operation(run, PROFILE, op)
    except ProtocolError as error:
        require(error.code == expected, "DEMO_EXPECTED_" + expected + "_GOT_" + error.code)
        return error.code
    raise AssertionError("Order unexpectedly accepted")


def run_demo():
    with TemporaryDirectory(prefix="awp-pay-batch-") as folder:
        run = initialize(Path(folder), resource_capacity={PROFILE: AMOUNT * 2})
        try:
            orders = [run.clone(PROFILE), additional_order(run, "ord-2"), additional_order(run, "ord-3")]
            payments = []
            for seq, mode in enumerate(("crash_after_commit", "drop_before_tool")):
                _configure_tool(run, PROFILE, crash_after_commit=(mode == "crash_after_commit"),
                                drop_before_tool=(mode == "drop_before_tool"))
                op = approved_order(run, orders[seq])
                entry, response = obtain_execution(run, op)
                require(response["record"] is None, "DEMO_EXPECTED_UNKNOWN")
                payments.append(entry)
            _configure_tool(run, PROFILE, crash_after_commit=False, drop_before_tool=False)
            ids = [entry["action"]["operation_id"] for entry in payments]
            stages = {"two_unknown": balances(run)}
            require(stages["two_unknown"]["reserved_minor"] == 2 * AMOUNT
                    and stages["two_unknown"]["unknown_orders"] == 2
                    and stages["two_unknown"]["tool_payments"] == 1, "DEMO_INITIAL_BALANCES")

            third = approved_order(run, orders[2])
            checks = {"third_before_close": reject_order(run, third, "RESOURCE_EXHAUSTED")}
            request = run.w.request_pay_batch(ids, {oid: worker(run, oid) for oid in ids})
            gateway = run.tool_gateways[PROFILE]
            first_receipt = gateway.close_batch(request)["certificate"]
            # Lose delivery of the first close reply. Reopen exactly the same two
            # ledgers and ask the authority for the receipt again before applying it.
            saved = save_recovery_fixture(run)
            run.close()
            run = None
            run = recover_fixture(saved)
            gateway = run.tool_gateways[PROFILE]
            retry_request = run.w.request_pay_batch(ids, {oid: worker(run, oid) for oid in ids})
            certificate = gateway.close_batch(retry_request)["certificate"]
            require(certificate == first_receipt, "DEMO_CLOSE_REPLAY")
            checks["recovered_same_certificate"] = True
            settled = run.w.settle_pay_batch(certificate, {oid: worker(run, oid) for oid in ids})
            require(settled["state"] == "BATCH_CLOSED" and not settled["existing"], "DEMO_CLOSE")
            repeat = run.w.settle_pay_batch(certificate, {oid: worker(run, oid) for oid in ids})
            require(repeat["existing"], "DEMO_DUPLICATE_CLOSE")
            checks["duplicate_close"] = True
            batch_id = settled["batch_id"]
            stages["batch_applied"] = balances(run)
            require(stages["batch_applied"]["available_minor"] == AMOUNT
                    and stages["batch_applied"]["spent_minor"] == AMOUNT
                    and stages["batch_applied"]["unknown_orders"] == 2, "DEMO_CLOSED_BALANCES")

            third = approved_order(run, orders[2])
            last, response = obtain_execution(run, third)
            third_id = last["action"]["operation_id"]
            require(response["state"] == "SUCCEEDED", "DEMO_THIRD_TOOL")
            posting = run.w.settle(PROFILE, third_id, response, worker(run, third_id))
            require(posting["state"] == "SETTLED", "DEMO_THIRD_SETTLED")
            last.update(tool_final=response["record"], checkpoint=response["checkpoint"])
            payments.append(last)
            stages["third_settled"] = balances(run)

            details = []
            for oid in ids:
                req = run.w.request_pay_batch_detail(batch_id, oid, worker(run, oid))
                detail = gateway.batch_detail(req)["detail"]
                applied = run.w.settle_pay_batch_detail(detail, worker(run, oid))
                duplicate = run.w.settle_pay_batch_detail(detail, worker(run, oid))
                require(applied["state"] == "SETTLED" and not applied["existing"]
                        and duplicate["existing"], "DEMO_DETAIL_REPLAY")
                details.append(detail)
            checks["duplicate_details"] = len(details)
            checks["old_intents"] = [reject_order(run, approved_order(run, op), "INTENT_CONFLICT")
                                     for op in orders[:2]]
            stages["final"] = balances(run)
            final = stages["final"]
            require(final["tool_payments"] == 2 and final["tool_paid_minor"] == final["spent_minor"] == 2 * AMOUNT
                    and final["reserved_minor"] == final["available_minor"] == final["unknown_orders"] == 0
                    and final["protected_intents"] == 3, "DEMO_FINAL_RECONCILIATION")
            return {"fixture": PROFILE, "currency": "CNY", "unit": "minor",
                    "root_public": b64(run.store.root_public), "tool_public": b64(run.tool_keys[PROFILE].public_key().public_bytes_raw()),
                    "tool_certificate": run.tools[PROFILE]["certificate"], "batch_certificate": certificate,
                    "details": details, "payments": payments, "stages": stages, "replay_checks": checks}
        finally:
            if run is not None:
                run.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save public JSON evidence at this path")
    output = parser.parse_args().output
    evidence = run_demo()
    rendered = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    if output is None:
        print(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps(evidence["stages"]["final"], sort_keys=True))
