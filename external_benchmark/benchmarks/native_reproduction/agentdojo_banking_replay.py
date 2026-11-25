"""Deterministic AgentDojo Banking replay.

This is NOT a model-based AgentDojo run.  It executes the benchmark's own user
task and injection task ground-truth tool calls against the original environment
and uses the original utility/security scoring functions.  It is therefore an
upper-bound replay of the tool trace, not a measurement of LLM behaviour.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite

OUT = Path(__file__).resolve().parents[2] / "results"


def execute_calls(env, runtime, calls):
    traces = []
    for call in calls:
        result, error = runtime.run_function(env, call.function, call.args, raise_on_error=True)
        if error is not None:
            raise RuntimeError(error)
        traces.append(call.model_dump(mode="json"))
    return env, traces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1.2.2")
    parser.add_argument("--suite", default="banking")
    parser.add_argument("--out", default=str(OUT / "agentdojo-banking-replay.json"))
    args = parser.parse_args()
    suite = get_suite(args.version, args.suite)
    runtime = FunctionsRuntime(suite.tools)
    payload = {
        "benchmark": "AgentDojo",
        "version": args.version,
        "suite": args.suite,
        "mode": "deterministic_ground_truth_replay",
        "not_full_benchmark": True,
        "reason": "No LLM API key/CLI model was available. The benchmark's own "
                  "ground-truth tool calls and scoring functions are used.",
        "user_tasks": [],
        "injection_tasks": [],
    }
    for task_id, task in suite.user_tasks.items():
        env = suite.load_and_inject_default_environment({})
        env = task.init_environment(env)
        pre = copy.deepcopy(env)
        env, traces = execute_calls(env, runtime, task.ground_truth(pre))
        output = task.GROUND_TRUTH_OUTPUT
        utility_trace = task.utility_from_traces(output, pre, env, traces)
        utility = utility_trace if utility_trace is not None else task.utility(output, pre, env)
        payload["user_tasks"].append({
            "task_id": task_id,
            "difficulty": task.DIFFICULTY.name,
            "prompt": task.PROMPT,
            "tool_calls": traces,
            "utility": bool(utility),
            "utility_source": "traces" if utility_trace is not None else "state",
        })
    for task_id, task in suite.injection_tasks.items():
        env = suite.load_and_inject_default_environment({})
        if hasattr(task, "init_environment"):
            env = task.init_environment(env)
        pre = copy.deepcopy(env)
        env, traces = execute_calls(env, runtime, task.ground_truth(pre))
        insecure = task.security("", pre, env)
        payload["injection_tasks"].append({
            "task_id": task_id,
            "goal": task.GOAL,
            "difficulty": task.DIFFICULTY.name,
            "tool_calls": traces,
            "attack_succeeded_without_defense": bool(insecure),
        })
    payload["summary"] = {
        "user_tasks": len(payload["user_tasks"]),
        "user_utility_pass": sum(row["utility"] for row in payload["user_tasks"]),
        "injection_tasks": len(payload["injection_tasks"]),
        "injection_success_without_defense": sum(
            row["attack_succeeded_without_defense"] for row in payload["injection_tasks"]),
        "zjj_end_to_end": "NOT_RUN",
        "camel": "NOT_RUN",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
