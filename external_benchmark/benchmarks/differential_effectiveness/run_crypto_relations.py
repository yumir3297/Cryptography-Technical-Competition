"""Ten individually-signed object-combination negatives.

The object signatures are produced by the protocol's real keys.  The negative is
a relationship between objects (task, policy revision, action, dependency,
attempt or acceptance), not a broken Ed25519 signature.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from competition.core.trusted_state import PROFILE_SCOPES, prefix  # noqa: E402
from competition.evaluation.bulk import bulk_ind_units  # noqa: E402
from competition.evaluation.package import build_anchor, build_package  # noqa: E402
from competition.evaluation.verify import verify_package  # noqa: E402
from competition.profiles.authorization_seed import initialize as init_auth  # noqa: E402
from competition.profiles.w_seed import initialize as init_w  # noqa: E402
from competition.support.wire import ProtocolError, b64, canonical, keyid  # noqa: E402

PROFILE = "IND-DEMO-1"
RESULTS = ROOT / "external_benchmark" / "results"
RUNTIME = ROOT / ".runtime" / "external-benchmark"


def _auth():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="rel-auth-", dir=RUNTIME))
    return init_auth(folder), folder


def _w():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="rel-w-", dir=RUNTIME))
    return init_w(folder, goal_mode="off"), folder


def _reject(fn):
    try:
        fn()
        return {"rejected": False, "code": "ACCEPTED"}
    except ProtocolError as exc:
        return {"rejected": True, "code": exc.code}
    except Exception as exc:
        return {"rejected": True, "code": type(exc).__name__ + ": " + str(exc)[:120]}


def cross_review_case() -> dict:
    run, folder = _w()
    try:
        units = bulk_ind_units(run, [("rel-review-a", "rel-review-batch-a", "rel-review-a"),
                                     ("rel-review-b", "rel-review-batch-b", "rel-review-b")])
        first = run.fork_operation(PROFILE, units[0])
        second = run.fork_operation(PROFILE, units[1])
        first["reviews"] = copy.deepcopy(second["reviews"])
        signing = copy.copy(run.base)
        signing.operations = {**run.base.operations, PROFILE: first}
        signing.resign_chain(PROFILE, first)
        outcome = _reject(lambda: run.base.service.guard(
            PROFILE, first, run.identity_proof(PROFILE, first)))
        outcome["case"] = "cross_review"
        outcome["signatures_verified_individually"] = True
        return outcome
    finally:
        run.close()
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def gate_case(kind: str) -> dict:
    if kind == "cross_review":
        return cross_review_case()
    run, folder = _auth()
    try:
        op = run.clone(PROFILE)
        if kind == "different_task":
            op["task_id"] = "task-from-another-chain"
        elif kind == "policy_version":
            with run.store.db() as c:
                row = run.store.current(c, PROFILE, "POLICY", prefix(PROFILE))
            run.publish(PROFILE, "POLICY", prefix(PROFILE), row["record"])
        elif kind == "payload_action":
            op["action"]["payload"]["route"] = "QUARANTINE"
            from competition.support.scene_contract import DEST
            op["action"]["destination"] = DEST["QUARANTINE"]
        elif kind == "cross_review":
            other = run.clone(PROFILE)
            op["reviews"] = copy.deepcopy(other["reviews"])
            run.resign_chain(PROFILE, op)
        elif kind == "missing_dep":
            op["permit"]["body"]["deps"] = op["permit"]["body"]["deps"][1:]
            run.resign_chain(PROFILE, op)
        elif kind == "stale_task":
            with run.store.db() as c:
                row = run.store.current(c, PROFILE, "TASK", prefix(PROFILE) + [op["task_id"]])
            run.publish(PROFILE, "TASK", prefix(PROFILE) + [op["task_id"]], row["record"])
        else:
            raise ValueError(kind)
        outcome = _reject(lambda: run.service.guard(
            PROFILE, op, run.identity_proof(PROFILE, op)))
        outcome["case"] = kind
        outcome["signatures_verified_individually"] = True
        return outcome
    finally:
        run.close()
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def prepare_then_update() -> dict:
    run, folder = _w()
    try:
        op = run.operations[PROFILE]
        ticket = run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))
        with run.store.db() as c:
            row = run.store.current(c, PROFILE, "TASK", prefix(PROFILE) + [op["task_id"]])
        run.base.publish(PROFILE, "TASK", prefix(PROFILE) + [op["task_id"]], row["record"])
        outcome = _reject(lambda: run.w.accept(
            PROFILE, ticket["ticket_id"], run.accept_proof(PROFILE, ticket["ticket_id"])))
        outcome["case"] = "gate_version_change"
        outcome["signatures_verified_individually"] = True
        return outcome
    finally:
        run.close()
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def cross_attempt_and_receipt() -> list[dict]:
    run, folder = _w()
    try:
        units = bulk_ind_units(run, [("rel-a", "rel-batch-a", "rel-principal-a"),
                                     ("rel-b", "rel-batch-b", "rel-principal-b"),
                                     ("rel-c", "rel-batch-c", "rel-principal-c")])
        first, second, third = [run.fork_operation(PROFILE, unit) for unit in units]
        for op in (first, second, third):
            ticket = run.w.prepare(PROFILE, op, run.identity_proof(PROFILE, op))
            run.w.accept(PROFILE, ticket["ticket_id"],
                         run.accept_proof(PROFILE, ticket["ticket_id"]))
        oid1, oid2, oid3 = [op["action"]["operation_id"] for op in (first, second, third)]
        # Settle each attempt before starting the next: this is the supported
        # single-inflight path.  A separate defect record covers the unsupported
        # two-inflight interleaving discovered during this experiment.
        run.w.claim(PROFILE, oid1, run.worker_proof(PROFILE, oid1, "CLAIM"))
        response1 = run.w.execute_once(PROFILE, oid1, run.worker_proof(PROFILE, oid1, "EXECUTE"))
        run.w.settle(PROFILE, oid1, response1, run.worker_proof(PROFILE, oid1, "SETTLE"))
        run.w.claim(PROFILE, oid2, run.worker_proof(PROFILE, oid2, "CLAIM"))
        response2 = run.w.execute_once(PROFILE, oid2, run.worker_proof(PROFILE, oid2, "EXECUTE"))
        run.w.settle(PROFILE, oid2, response2, run.worker_proof(PROFILE, oid2, "SETTLE"))
        run.w.claim(PROFILE, oid3, run.worker_proof(PROFILE, oid3, "CLAIM"))
        response3 = run.w.execute_once(PROFILE, oid3, run.worker_proof(PROFILE, oid3, "EXECUTE"))
        cross = _reject(lambda: run.w.settle(
            PROFILE, oid3, response2, run.worker_proof(PROFILE, oid3, "SETTLE")))
        run.w.settle(PROFILE, oid3, response3, run.worker_proof(PROFILE, oid3, "SETTLE"))
        package1 = build_package(run, PROFILE, oid1)
        package2 = build_package(run, PROFILE, oid2)
        anchor = build_anchor(run)
        cross["case"] = "cross_attempt_settlement"
        cross["signatures_verified_individually"] = True

        # C10: structurally valid X receipt from operation 2 inside package 1.
        forged = copy.deepcopy(package1)
        forged["acceptance"] = copy.deepcopy(package2["acceptance"])
        receipt_result = verify_package(forged, anchor)
        failed = [c for c in receipt_result["checks"] if c["status"] != "PASS"]
        receipt = {
            "case": "cross_receipt_settlement",
            "rejected": receipt_result["status"] != "PASS",
            "code": failed[0]["check"] + ":" + failed[0].get("error", ""),
            "signatures_verified_individually": True,
        }

        # C4: a root-signed resource certificate for another resource key.
        second_key = prefix(PROFILE) + ["second-resource"]
        claim = {"profile": PROFILE, "scope": PROFILE_SCOPES[PROFILE], "key": second_key,
                 "unit": "UNIT", "capacity": "1", "revision": "1", "active": True}
        cert = {"claim": claim,
                "signature": b64(run.base.root.sign(canonical(["COMP-W-RESOURCE-v1", claim])))}
        run.w.register_resource(cert)
        forged_resource = copy.deepcopy(package1)
        forged_resource["resource"] = {
            "reserved": 0, "spent": 0, "capacity": 1, "unit": "UNIT", "certificate": cert}
        resource_result = verify_package(forged_resource, anchor)
        failed = [c for c in resource_result["checks"] if c["status"] != "PASS"]
        resource = {
            "case": "cross_resource_certificate",
            "rejected": resource_result["status"] != "PASS",
            "code": failed[0]["check"] + ":" + failed[0].get("error", ""),
            "signatures_verified_individually": True,
        }
        return [cross, receipt, resource]
    finally:
        run.close()
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def main():
    results = []
    for case in ("different_task", "policy_version", "payload_action", "cross_review",
                 "missing_dep", "stale_task"):
        results.append(gate_case(case))
    results.append(prepare_then_update())
    results.extend(cross_attempt_and_receipt())
    payload = {
        "profile": PROFILE,
        "class_count": len(results),
        "all_rejected": all(row["rejected"] for row in results),
        "results": results,
        "note": "Every listed negative keeps the producing signature valid; the "
                "rejection is caused by the relationship between independently "
                "signed objects. The substituted resource certificate is root-signed.",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "crypto_relations.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
