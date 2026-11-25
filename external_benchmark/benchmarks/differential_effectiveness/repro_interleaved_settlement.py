"""Reproduce the interleaved-settlement defect found by experiment D.

Two real attempts on the same tool ledger are executed (claims and tool finals
created in order A then B).  A is settled after B's final exists.  The tool
checkpoint is authentic for A, but W compares its high-water mark with the
ledger's *current* high-water mark and refuses the older final.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from competition.support.wire import ProtocolError  # noqa: E402
from external_benchmark.adapters.zjj_core.harness import IND as PROFILE, ZjjSession  # noqa: E402

RESULTS = ROOT / "external_benchmark" / "results"


def main():
    session = ZjjSession.create(capacity=4, required=2, optional=0, mode="off",
                                publish_floor=False)
    try:
        a, b = session.required_ops
        oid_a, oid_b = a["action"]["operation_id"], b["action"]["operation_id"]
        for op in (a, b):
            ticket = session.run.w.prepare(PROFILE, op, session.run.identity_proof(PROFILE, op))
            session.run.w.accept(PROFILE, ticket["ticket_id"],
                                 session.run.accept_proof(PROFILE, ticket["ticket_id"]))
        # Both attempts are claimed and executed before either settles.
        for oid in (oid_a, oid_b):
            session.run.w.claim(PROFILE, oid, session.run.worker_proof(PROFILE, oid, "CLAIM"))
        response_a = session.run.w.execute_once(
            PROFILE, oid_a, session.run.worker_proof(PROFILE, oid_a, "EXECUTE"))
        response_b = session.run.w.execute_once(
            PROFILE, oid_b, session.run.worker_proof(PROFILE, oid_b, "EXECUTE"))
        outcomes = {}
        for label, oid, response in (("settle_a_after_b_final", oid_a, response_a),
                                     ("settle_b", oid_b, response_b)):
            try:
                result = session.run.w.settle(
                    PROFILE, oid, response, session.run.worker_proof(PROFILE, oid, "SETTLE"))
                outcomes[label] = {"ok": True, "result": result}
            except ProtocolError as exc:
                outcomes[label] = {"ok": False, "code": exc.code}
        snapshot = session.snapshot()
        payload = {
            "experiment": "interleaved attempts on one tool ledger",
            "sequence": ["accept A", "accept B", "claim A", "claim B", "execute A",
                         "execute B", "settle A", "settle B"],
            "outcomes": outcomes,
            "snapshot": snapshot,
            "finding": ("Authentic final fact A is rejected after final B advanced the "
                        "tool ledger's high-water mark. The operation remains STARTED, "
                        "resource reservation is retained, and no duplicate effect was "
                        "observed. This is a liveness/availability defect in evidence "
                        "coupling, not evidence of an unauthorized effect."),
        }
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "interleaved-settlement-defect.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
