"""Real CommonW C/D runs for generated resource-floor sequences.

Each task creates a fresh SQLite W, real Ed25519 C records and a real action
chain.  The worker never calls ``goal_floor.evaluate``; the independent oracle is
in ``external_benchmark.oracle``.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from external_benchmark.adapters.zjj_core.harness import ZjjSession  # noqa: E402
from external_benchmark.benchmarks.differential_effectiveness.scenarios import (  # noqa: E402
    SequenceSpec,
    costs,
    make_specs,
)
from external_benchmark.oracle.goalfloor import FloorOracle  # noqa: E402

RESULTS = ROOT / "external_benchmark" / "results"


def _spec_from_dict(raw: dict) -> SequenceSpec:
    return SequenceSpec(
        sequence_id=raw["sequence_id"],
        capacity=raw["capacity"],
        required=raw["required"],
        optional=raw["optional"],
        order=list(raw["order"]),
        unknown_at=raw["unknown_at"],
    )


def run_one(payload: dict) -> dict:
    raw_spec, mode = payload["spec"], payload["mode"]
    spec = _spec_from_dict(raw_spec)
    required_costs, optional_costs = costs(spec)
    oracle = FloorOracle(spec.capacity, required_costs, optional_costs,
                         enforce=(mode == "enforce"))
    accepted = []
    rows = []
    started = time.perf_counter()
    try:
        with ZjjSession.create(capacity=spec.capacity, required=spec.required,
                               optional=spec.optional, mode=mode,
                               publish_floor=(mode == "enforce")) as session:
            for position, token in enumerate(spec.order):
                kind, index = token[0], int(token[1:])
                expected, expected_code = oracle.local_checks(kind, index)
                legitimate_optional = (oracle.legitimate_optional_before(index)
                                        if kind == "O" else None)
                actual = session.accept(kind, index)
                is_unknown = bool(actual["accepted"] and spec.unknown_at == position)
                outcome = ""
                if actual["accepted"]:
                    execution = session.execute(kind, index, settle=not is_unknown,
                                                leave_unknown=is_unknown)
                    outcome = "PENDING" if is_unknown else (
                        "SUCCESS" if execution.get("state") == "SETTLED" else "BLOCKED")
                    if not is_unknown and execution.get("state") != "SETTLED":
                        raise RuntimeError("accepted action did not settle: " + str(execution))
                    accepted.append({"kind": kind, "index": index, "outcome": outcome})
                    oracle.observe_accept(kind, index, outcome=outcome)
                rows.append({
                    "position": position,
                    "token": token,
                    "expected": expected,
                    "expected_code": expected_code,
                    "accepted": actual["accepted"],
                    "actual_code": actual["code"],
                    "outcome": outcome,
                    "legitimate_optional": legitimate_optional,
                    "elapsed_ns": actual["elapsed_ns"],
                })
            snapshot = session.snapshot()
        elapsed = time.perf_counter() - started
        floor_ok = oracle.floor_feasible_after(accepted)
        required_done = sum(row["outcome"] == "SUCCESS" for row in accepted if row["kind"] == "R")
        return {
            "mode": mode,
            "sequence_id": spec.sequence_id,
            "spec": asdict(spec),
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
            "oracle_mismatch": sum(row["expected"] != row["accepted"] for row in rows),
            "inconsistent_codes": sum(
                1 for row in rows if not row["expected"] and not row["accepted"] and
                row["expected_code"] != row["actual_code"]),
            "all_done": (required_done == spec.required and
                         sum(row["kind"] == "R" for row in accepted) == spec.required and
                         sum(row["kind"] == "O" for row in accepted) == spec.optional),
            "snapshot": snapshot,
            "elapsed_seconds": elapsed,
            "error": "",
        }
    except Exception as exc:  # keep the batch running; the error is evidence
        return {
            "mode": mode,
            "sequence_id": spec.sequence_id,
            "spec": asdict(spec),
            "error": type(exc).__name__ + ": " + str(exc)[:300],
            "traceback": traceback.format_exc()[-1500:],
            "elapsed_seconds": time.perf_counter() - started,
        }


def summarize(results: dict[str, list[dict]]) -> dict:
    out = {}
    for mode, rows in results.items():
        ok = [row for row in rows if not row.get("error")]
        latencies = sorted(row["elapsed_ns"] for row in ok for row in row["rows"]
                           if row.get("accepted"))
        def pct(p):
            if not latencies:
                return None
            return latencies[min(len(latencies) - 1, int((len(latencies) - 1) * p))]
        out[mode] = {
            "sequences": len(rows),
            "errors": len(rows) - len(ok),
            "floor_preserved": sum(row["floor_preserved"] for row in ok),
            "floor_violations": sum(not row["floor_preserved"] for row in ok),
            "false_reject_optional": sum(row["false_reject_optional"] for row in ok),
            "illegal_accept_optional": sum(row["illegal_accept_optional"] for row in ok),
            "optional_accepted": sum(row["optional_accepted"] for row in ok),
            "required_done": sum(row["required_done"] for row in ok),
            "all_done": sum(row["all_done"] for row in ok),
            "oracle_mismatch": sum(row["oracle_mismatch"] for row in ok),
            "inconsistent_codes": sum(row["inconsistent_codes"] for row in ok),
            "accept_p50_ns": pct(0.50),
            "accept_p95_ns": pct(0.95),
            "accept_p99_ns": pct(0.99),
            "wall_seconds": round(sum(row["elapsed_seconds"] for row in ok), 1),
        }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequences", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default=str(RESULTS / "zjj-goalfloor-differential.json"))
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--modes", nargs="+", choices=("off", "enforce"),
                        default=("off", "enforce"))
    args = parser.parse_args()
    specs = make_specs(args.sequences, seed=args.seed)
    tasks = [{"spec": spec.as_dict(), "mode": mode}
             for spec in specs for mode in args.modes]
    by_mode = {mode: {} for mode in args.modes}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, task): task for task in tasks}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            by_mode[result["mode"]][result["sequence_id"]] = result
            done += 1
            if done % args.checkpoint_every == 0:
                payload = {
                    "seed": args.seed,
                    "requested_sequences": args.sequences,
                    "workers": args.workers,
                    "completed_tasks": done,
                    "total_tasks": len(tasks),
                    "wall_seconds": round(time.time() - started, 1),
                    "results": {mode: [rows[i] for i in sorted(rows)]
                                for mode, rows in by_mode.items()},
                    "summary": summarize({mode: [rows[i] for i in sorted(rows)]
                                          for mode, rows in by_mode.items()}),
                }
                out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                print("checkpoint", done, payload["summary"], flush=True)
    payload = {
        "seed": args.seed,
        "requested_sequences": args.sequences,
        "workers": args.workers,
        "completed_tasks": len(tasks),
        "total_tasks": len(tasks),
        "wall_seconds": round(time.time() - started, 1),
        "results": {mode: [rows[i] for i in sorted(rows)]
                    for mode, rows in by_mode.items()},
        "summary": summarize({mode: [rows[i] for i in sorted(rows)]
                              for mode, rows in by_mode.items()}),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
