"""ZJJ-CORE adapter for the external benchmark.

This module deliberately does not re-implement any protocol rule.  Every
decision is made by ``competition.core.common_w.CommonW`` after a real C
publication, real Ed25519 signatures and a real SQLite resource transaction.
The adapter only supplies business fixtures (IND units) and records outcomes.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from competition.evaluation.bulk import bulk_ind_units
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.wire import ProtocolError

IND = "IND-DEMO-1"
ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / ".runtime" / "external-benchmark"


def _new_folder() -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="zjj-", dir=RUNTIME))


class ZjjSession:
    """One isolated real CommonW instance."""

    def __init__(self, run, folder: Path):
        self.run = run
        self.folder = folder
        self.profile = IND

    @classmethod
    def create(cls, *, capacity: int, required: int, optional: int,
               mode: str = "enforce", publish_floor: bool = True) -> "ZjjSession":
        folder = _new_folder()
        run = initialize(folder, resource_capacity={IND: capacity}, goal_mode=mode)
        session = cls(run, folder)
        specs = ([(f"r{i}", f"req-batch-{i}", f"req-principal-{i}") for i in range(required)] +
                 [(f"o{i}", f"opt-batch-{i}", f"opt-principal-{i}") for i in range(optional)])
        units = bulk_ind_units(run, specs)
        session.required_ops = units[:required]
        session.optional_ops = units[required:]
        session.claim = None
        if publish_floor:
            rules = ([{"name": f"req-{i}", "op": op, "obligation": f"r{i}", "cost": 1}
                      for i, op in enumerate(session.required_ops)] +
                     [{"name": f"opt-{i}", "op": op, "obligation": "", "cost": 1}
                      for i, op in enumerate(session.optional_ops)])
            claim = goal_claim(run, IND, "bench-goal", rules, capacity=capacity)
            publish_goal(run, IND, claim)
            session.claim = claim
        return session

    def op(self, kind: str, index: int):
        return (self.required_ops if kind == "R" else self.optional_ops)[index]

    def accept(self, kind: str, index: int) -> dict:
        op = self.op(kind, index)
        oid = op["action"]["operation_id"]
        started = time.perf_counter_ns()
        try:
            ticket = self.run.w.prepare(self.profile, op, self.run.identity_proof(self.profile, op))
            result = self.run.w.accept(
                self.profile, ticket["ticket_id"],
                self.run.accept_proof(self.profile, ticket["ticket_id"]))
            elapsed = time.perf_counter_ns() - started
            return {"accepted": True, "code": "", "operation_id": oid,
                    "acceptance_state": result.get("acceptance_state"),
                    "elapsed_ns": elapsed}
        except ProtocolError as exc:
            return {"accepted": False, "code": exc.code, "operation_id": oid,
                    "elapsed_ns": time.perf_counter_ns() - started}

    def execute(self, kind: str, index: int, *, settle: bool = True,
                leave_unknown: bool = False) -> dict:
        op = self.op(kind, index)
        oid = op["action"]["operation_id"]
        try:
            self.run.w.claim(self.profile, oid,
                             self.run.worker_proof(self.profile, oid, "CLAIM"))
            if leave_unknown:
                path = Path(self.run.tools[self.profile]["config_path"])
                config = json.loads(path.read_text(encoding="utf-8"))
                config["drop_before_tool"] = True
                path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                from competition.tools.common_tool import ToolGateway
                self.run.tool_gateways[self.profile] = ToolGateway(path)
            response = self.run.w.execute_once(
                self.profile, oid, self.run.worker_proof(self.profile, oid, "EXECUTE"))
            if leave_unknown:
                config["drop_before_tool"] = False
                path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                from competition.tools.common_tool import ToolGateway
                self.run.tool_gateways[self.profile] = ToolGateway(path)
            if not settle:
                return {"state": response.get("state"), "record": response.get("record") is not None}
            settled = self.run.w.settle(
                self.profile, oid, response,
                self.run.worker_proof(self.profile, oid, "SETTLE"))
            return {"state": settled.get("state"), "record": response.get("record") is not None,
                    "outcome": (response.get("record") or {}).get("value", {}).get("outcome")}
        except ProtocolError as exc:
            return {"state": "ERROR", "code": exc.code}

    def reject(self, kind: str, index: int) -> dict:
        return self.accept(kind, index)

    def snapshot(self) -> dict:
        with self.run.store.db() as c:
            resource = c.execute(
                "SELECT reserved,spent,capacity FROM w_resource WHERE profile=?",
                (self.profile,)).fetchone()
            goals = [dict(row) for row in c.execute(
                "SELECT goal_group,obligation,state,cost FROM w_goal WHERE profile=? "
                "ORDER BY goal_group,obligation", (self.profile,))]
            operations = [dict(row) for row in c.execute(
                "SELECT oid,state,effect_state FROM w_operation WHERE profile=?",
                (self.profile,))]
        return {"reserved": resource[0], "spent": resource[1], "capacity": resource[2],
                "goals": goals, "operations": operations, "counts": self.run.w.counts()}

    def close(self):
        try:
            self.run.close()
        finally:
            shutil.rmtree(self.folder, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
