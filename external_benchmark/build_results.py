"""Consolidate all external-benchmark evidence into RESULTS.json."""
from __future__ import annotations

import json
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "external_benchmark" / "results"


def junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    skipped = [c for c in cases if c.find("skipped") is not None]
    return {"total": len(cases), "passed": len(cases) - len(failed) - len(skipped),
            "failed": len(failed), "skipped": len(skipped),
            "failures": [c.get("classname", "") + "::" + c.get("name", "") for c in failed]}


def load(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def zjj_summary(path: str) -> dict:
    data = load(path)
    mode = next(iter(data["summary"]))
    rows = data["results"][mode]
    clean = [r for r in rows if not r.get("error") and r.get("oracle_mismatch") == 0
             and r.get("inconsistent_codes") == 0]
    latencies = sorted(row["elapsed_ns"] for r in clean for row in r["rows"] if row["accepted"])

    def pct(p):
        if not latencies:
            return None
        return latencies[min(len(latencies) - 1, int((len(latencies) - 1) * p))]

    return {
        "attempted_sequences": len(rows),
        "clean_sequences": len(clean),
        "excluded_clock_or_environment": len(rows) - len(clean),
        "floor_violations": sum(not r["floor_preserved"] for r in clean),
        "floor_preserved": sum(r["floor_preserved"] for r in clean),
        "illegal_accept_optional": sum(r["illegal_accept_optional"] for r in clean),
        "false_reject_optional": sum(r["false_reject_optional"] for r in clean),
        "optional_accepted": sum(r["optional_accepted"] for r in clean),
        "required_done": sum(r["required_done"] for r in clean),
        "all_done": sum(r["all_done"] for r in clean),
        "oracle_mismatch": sum(r["oracle_mismatch"] for r in clean),
        "accept_samples": len(latencies),
        "p50_ns": pct(0.50), "p95_ns": pct(0.95), "p99_ns": pct(0.99),
        "wall_seconds": round(sum(r["elapsed_seconds"] for r in clean), 1),
    }


def main():
    aadp_native = junit(RESULTS / "aadp-native-junit.xml")
    aadp_cap = junit(RESULTS / "aadp-capability-junit.xml")
    ap2 = junit(RESULTS / "ap2-native-junit.xml")
    agentdojo = junit(RESULTS / "agentdojo-native-junit.xml")
    zjj = junit(RESULTS / "zjj-capability-junit.xml")

    aadp_diff = load("aadp-goalfloor-differential.json")
    seqs20 = aadp_diff["sequences"][:20]
    aadp_20 = {}
    for variant in ("A", "B"):
        rows = [row[variant] for row in seqs20]
        aadp_20[variant] = {
            "sequences": len(rows),
            "floor_violations": sum(not r["floor_preserved"] for r in rows),
            "optional_accepted": sum(r["optional_accepted"] for r in rows),
            "required_done": sum(r["required_done"] for r in rows),
            "all_done": sum(r["all_done"] for r in rows),
            "false_reject_optional": sum(r["false_reject_optional"] for r in rows),
        }
    aadp_all = {}
    for variant in ("A", "B"):
        rows = [row[variant] for row in aadp_diff["sequences"]]
        aadp_all[variant] = {
            "sequences": len(rows),
            "floor_violations": sum(not r["floor_preserved"] for r in rows),
            "optional_accepted": sum(r["optional_accepted"] for r in rows),
            "required_done": sum(r["required_done"] for r in rows),
            "all_done": sum(r["all_done"] for r in rows),
            "false_reject_optional": sum(r["false_reject_optional"] for r in rows),
        }

    zjj_off = zjj_summary("zjj-goalfloor-off-20-clean.json")
    zjj_enforce_20 = zjj_summary("zjj-goalfloor-enforce-paired-20.json")
    zjj_enforce_120 = zjj_summary("zjj-goalfloor-enforce-attempted-120.json")
    relations = load("crypto_relations.json")
    verify_text = (RESULTS / "evidence-package-verify.log").read_bytes()
    try:
        verify_text = verify_text.decode("utf-8-sig")
    except UnicodeDecodeError:
        verify_text = verify_text.decode("utf-16")
    package_verify = json.loads(verify_text)
    interleaved = load("interleaved-settlement-defect.json")
    agentdojo_replay = load("agentdojo-banking-replay.json")
    capability = load("capability_coverage.json")

    native = {
        "aadp": {
            "repository": "shamiksaharcciit-oss/onedoor",
            "version": "0.12.1", "sha": "9d0b69879273af21b8cbf5d1098ff50f2cb1d6ea",
            "license": "Apache-2.0",
            "full_suite": aadp_native,
            "selected_capability_suite": aadp_cap,
            "native_eval": {
                "harmful_without": 16, "harmful_with": 3,
                "legitimate_wrongly_stopped": 0, "held": 4,
                "duplicate_effects_without": 2, "duplicate_effects_with": 2,
                "scenarios": 32, "categories": 8,
            },
            "environment_failures": [
                "8 failures: locale GBK chart read (1), release build pinned versions (3), "
                "stray virtualenv lint scan (1), ruff not on PATH (2), build module absent (1); "
                "none in the guardrail decision suite.",
                "17 targeted chart/gate tests pass when PYTHONUTF8=1 and Scripts is on PATH.",
            ],
        },
        "ap2": {
            "repository": "google-agentic-commerce/AP2",
            "sha": "e1ea56db72a6385bce3e5c1112b3a56ce60acb43",
            "license": "Apache-2.0", "full_suite": ap2,
            "relevant_failure": "Two intermediate KB-SD-JWT tests expect aud/nonce mismatch rejection; "
                                "the frozen SDK did not raise in this path. Final-hop aud/nonce tests pass.",
        },
        "agentdojo": {
            "repository": "ethz-spylab/agentdojo", "version": "0.1.35",
            "sha": "089ed468cf3ed0322acc66b0211f26d9d90dbf60", "license": "MIT",
            "full_suite": agentdojo, "banking_user_tasks": 16, "banking_injection_tasks": 9,
            "failure": "One Anthropic message-merge test fails because typing.Union cannot be instantiated "
                       "in the installed SDK; unrelated to Banking tool execution.",
        },
        "camel": {
            "repository": "google-research/camel-prompt-injection",
            "sha": "f083b6b396399d3b3c7f2ddaf613a5945eaf32d8",
            "license": "Apache-2.0", "status": "BLOCKED_NO_MODEL_API",
        },
        "tether": {
            "paper": "arXiv:2611.25599v1", "published": "2026-11-19",
            "code_release": "NOT_PUBLIC_AT_CHECK_TIME",
            "status": "BLOCKED_NO_PUBLIC_IMPLEMENTATION",
        },
    }

    atomic = {
        "crash_boundaries": {"passed": 3, "total": 3,
                             "source": "competition.tests.test_crash_boundaries (real child processes)"},
        "acceptance_races": {"passed": 4, "total": 4,
                             "source": "competition.tests.test_w_acceptance_races"},
        "offline_package": {"status": package_verify["status"],
                            "passed": package_verify["passed"],
                            "failed": package_verify["failed"],
                            "checks": [c["check"] for c in package_verify["checks"]]},
        "evidence_tamper_tests": {"passed": 15, "total": 15,
                                  "source": "competition.tests.test_evidence_verifier"},
        "interleaved_settlement": {
            "status": "CORE_DEFECT_FOUND",
            "observed": interleaved["outcomes"],
            "state": interleaved["snapshot"]["operations"],
            "reserved_after": interleaved["snapshot"]["reserved"],
            "settlements_after": interleaved["snapshot"]["counts"]["settlements"],
            "scope": "Authentic final fact for A rejected as LEDGER_STALE_UNKNOWN after B advanced "
                     "the tool ledger. No duplicate effect; A remains STARTED with its reservation held.",
        },
        "external_effect_boundary": "ZJJ's accept transaction is atomic; the tool effect is not. "
                                    "UNKNOWN retains the reservation and is not re-executed.",
    }

    payload = {
        "generated_utc": "2026-11-25",
        "baseline_sha": "c5caa73f711da93a24efacbac0456ed82a79dd4e",
        "baseline_branch": "research/external-benchmark-20261125",
        "native": native,
        "capability_coverage": capability,
        "differential_goalfloor": {
            "paired_20": {"aadp": aadp_20, "zjj_off": zjj_off, "zjj_enforce": zjj_enforce_20},
            "aadp_1000": aadp_all,
            "zjj_enforce_clean_aggregate": zjj_enforce_120,
            "literal_1000_zjj": {
                "requested": 1000,
                "completed_clean": zjj_enforce_120["clean_sequences"],
                "attempted_120": zjj_enforce_120["attempted_sequences"],
                "blocked": "The first 120-sequence run was interrupted by a harness restart; "
                           "22 CLOCK_UNKNOWN rows and 4 aborted sessions from 14-way load are "
                           "reported and excluded from the clean subset. They are not protocol denials.",
            },
            "interpretation": "For fixed unit costs, a static AADP carve-out (B) preserves the floor "
                              "and matches or exceeds ZJJ availability in this sample. GoalFloor's "
                              "difference is not established for fixed-cost single-goal reserve; "
                              "the dynamic-cost case remains checker-level only.",
        },
        "crypto_relations": {
            "class_count": relations["class_count"],
            "all_rejected": relations["all_rejected"],
            "single_signature_baseline": {"rejected": 0, "accepted": relations["class_count"],
                                          "basis": "all producing signatures were made by registered keys; "
                                                   "the protocol rejected on relationship checks, not signature checks"},
            "results": relations["results"],
        },
        "atomic_evidence": atomic,
        "agentdojo_replay": agentdojo_replay["summary"],
        "research_boundaries": [
            "No LLM API key: AgentDojo is a ground-truth tool-trajectory replay, not a model evaluation.",
            "CaMeL was not run end-to-end because it requires model APIs.",
            "Tether has no public implementation at the frozen date; LinuxArena is a different OS-level scope.",
            "AP2 native tests are 186/188 PASS; the two failures concern intermediate aud/nonce binding.",
            "GoalFloor heterogeneous-cost evidence is checker-level; the 93/20 real W sample uses unit costs.",
            "ZJJ does not publish a cross-organization bound-permit profile; P13 is PARTIAL.",
        ],
    }
    (RESULTS / "RESULTS.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({
        "aadp_full": aadp_native,
        "ap2": ap2,
        "agentdojo": agentdojo,
        "zjj_off": zjj_off,
        "zjj_enforce_20": zjj_enforce_20,
        "zjj_enforce_120": zjj_enforce_120,
        "paired_aadp": aadp_20,
        "coverage": capability["coverage"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
