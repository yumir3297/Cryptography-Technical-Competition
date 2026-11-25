"""AADP A/B and independent-oracle reference runs for generated sequences."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from external_benchmark.adapters.aadp.harness import AadpBudgetSession  # noqa: E402
from external_benchmark.benchmarks.differential_effectiveness.scenarios import (  # noqa: E402
    costs,
    make_specs,
)
from external_benchmark.oracle.goalfloor import FloorOracle  # noqa: E402

RESULTS = ROOT / "external_benchmark" / "results"


def run_aadp(spec, *, carve_out: bool) -> dict:
    required_costs, optional_costs = costs(spec)
    quota = (max(0, spec.capacity - sum(required_costs)) if carve_out else spec.capacity)
    oracle = FloorOracle(spec.capacity, required_costs, optional_costs, enforce=False)
    accepted = []
    rows = []
    with AadpBudgetSession(capacity=spec.capacity, optional_quota=quota) as session:
        for position, token in enumerate(spec.order):
            kind, index = token[0], int(token[1:])
            is_unknown = spec.unknown_at == position
            result = session.decide(kind, leave_pending=is_unknown)
            outcome = "PENDING" if result["accepted"] and is_unknown else "SUCCESS"
            if result["accepted"]:
                accepted.append({"kind": kind, "index": index, "outcome": outcome})
                oracle.observe_accept(kind, index, outcome=outcome)
            rows.append({
                "position": position,
                "token": token,
                "accepted": result["accepted"],
                "code": result["code"],
                "outcome": outcome if result["accepted"] else "",
                "legitimate_optional": (oracle.legitimate_optional_before(index)
                                        if kind == "O" else None),
            })
    floor_ok = oracle.floor_feasible_after(accepted)
    required_done = sum(row["outcome"] == "SUCCESS" for row in accepted if row["kind"] == "R")
    return {
        "variant": "B_static_carveout" if carve_out else "A_native_budget",
        "sequence_id": spec.sequence_id,
        "spec": spec.as_dict(),
        "rows": rows,
        "accepted": accepted,
        "floor_preserved": floor_ok,
        "required_done": required_done,
        "required_total": spec.required,
        "optional_accepted": sum(row["kind"] == "O" for row in accepted),
        "false_reject_optional": sum(
            1 for row in rows if row["token"].startswith("O") and
            row["legitimate_optional"] and not row["accepted"]),
        "illegal_accept_optional": sum(
            1 for row in rows if row["token"].startswith("O") and
            row["accepted"] and not row["legitimate_optional"]),
        "all_done": (required_done == spec.required and
                     sum(row["kind"] == "R" for row in accepted) == spec.required and
                     sum(row["kind"] == "O" for row in accepted) == spec.optional),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequences", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--out", default=str(RESULTS / "aadp-goalfloor-differential.json"))
    args = parser.parse_args()
    specs = make_specs(args.sequences, seed=args.seed)
    rows = {"seed": args.seed, "sequences": [], "source": "AADP/onedoor 0.12.1 official API"}
    for spec in specs:
        rows["sequences"].append({
            "A": run_aadp(spec, carve_out=False),
            "B": run_aadp(spec, carve_out=True),
        })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for variant in ("A", "B"):
        stats = [seq[variant] for seq in rows["sequences"]]
        print(variant, {
            "n": len(stats),
            "floor_preserved": sum(s["floor_preserved"] for s in stats),
            "false_reject_optional": sum(s["false_reject_optional"] for s in stats),
            "optional_accepted": sum(s["optional_accepted"] for s in stats),
            "required_done": sum(s["required_done"] for s in stats),
            "all_done": sum(s["all_done"] for s in stats),
        })


if __name__ == "__main__":
    main()
