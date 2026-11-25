"""Build the property-level capability matrix from frozen JUnit evidence."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "external_benchmark" / "results"


def load(path: Path):
    root = ET.parse(path).getroot()
    rows = {}
    for case in root.findall(".//testcase"):
        failed = case.find("failure") is not None or case.find("error") is not None
        rows[(case.get("classname", ""), case.get("name", ""))] = not failed
    return rows


ZJJ = load(RESULTS / "zjj-capability-junit.xml")
AADP = load(RESULTS / "aadp-capability-junit.xml")
AP2 = load(RESULTS / "ap2-native-junit.xml")


def passed(rows, class_suffix, test_name):
    for (cls, name), ok in rows.items():
        if class_suffix in cls and name == test_name:
            return bool(ok)
    return None


def any_passed(rows, checks):
    values = [passed(rows, cls, name) for cls, name in checks]
    if any(value is False for value in values):
        return False
    return True if any(value is True for value in values) else None


PROPERTIES = [
    {
        "id": "P01",
        "name": "动作授权有效性",
        "aadp": any_passed(AADP, [("tests.guardrail.test_default_deny", "test_an_unlisted_action_is_denied_with_default_deny_and_creates_no_approval"),
                                  ("tests.guardrail.test_bounds", "test_setpoint_out_of_bounds_denied")]),
        "ap2": any_passed(AP2, [("tests.payment_mandate_chain_tests", "test_payment_chain_constraint_violation")]),
        "zjj": any_passed(ZJJ, [("test_common_authorization", "test_omitted_review_with_other_legitimate_signatures_is_rejected"),
                                ("test_common_authorization", "test_published_deny_is_not_bypassed_by_omission_or_later_approval")]),
        "sources": ["AADP default-deny/bounds", "AP2 constraint chain", "ZJJ CommonGuard"],
    },
    {
        "id": "P02",
        "name": "身份及授权来源认证",
        "aadp": any_passed(AADP, [("tests.guardrail.test_approver_identity", "test_resume_approval_refuses_the_proposer_and_executes_nothing"),
                                  ("tests.guardrail.test_bound_permit_issuance", "test_issue_requires_issuer")]),
        "ap2": "PARTIAL",
        "zjj": any_passed(ZJJ, [("test_common_authorization", "test_actual_bad_signature_is_rejected"),
                                ("test_common_authorization", "test_legitimate_key_signature_cannot_claim_a_different_subject")]),
        "sources": ["AADP approver identity", "AP2 issuer/holder signatures", "ZJJ Ed25519 registry"],
    },
    {
        "id": "P03",
        "name": "动作与授权内容一致性",
        "aadp": None,
        "ap2": True,
        "zjj": any_passed(ZJJ, [("test_common_authorization", "test_broker_checked_action_must_bind_signed_payload_context")]),
        "sources": ["AP2 mandate chain (aud/nonce caveat)", "ZJJ ActionHash/Ctx binding"],
    },
    {
        "id": "P04",
        "name": "并发预算安全",
        "aadp": any_passed(AADP, [("tests.guardrail.test_concurrency", "test_no_over_reservation_under_concurrency[4-25]"),
                                  ("tests.guardrail.test_concurrency", "test_no_over_reservation_under_concurrency[8-15]"),
                                  ("tests.guardrail.test_concurrency", "test_no_over_reservation_under_concurrency[16-10]")]),
        "ap2": None,
        "zjj": any_passed(ZJJ, [("test_w_acceptance_races", "test_independent_intents_and_behavior_rows_compete_for_last_resource")]),
        "sources": ["AADP SQLite BEGIN IMMEDIATE concurrency", "ZJJ W last-resource race"],
    },
    {
        "id": "P05",
        "name": "原子资源预留",
        "aadp": any_passed(AADP, [("tests.guardrail.test_reservation_reclaim", "test_unreported_permit_holds_budget_until_reclaimed"),
                                  ("tests.guardrail.test_reservation_reclaim", "test_double_reclaim_is_harmless")]),
        "ap2": None,
        "zjj": any_passed(ZJJ, [("test_goal_floor", "test_enforce_rejects_without_business_side_effect")]),
        "sources": ["AADP reservation ledger", "ZJJ resource transaction + GoalFloor rollback"],
    },
    {
        "id": "P06",
        "name": "重放与重复执行控制",
        "aadp": any_passed(AADP, [("tests.guardrail.test_resume_idempotency", "test_a_resume_with_an_unchanged_request_gets_its_original_approval")]),
        "ap2": any_passed(AP2, [("tests.receipt_wrapper_tests", "test_verify_receipt_not_found_in_store")]),
        "zjj": any_passed(ZJJ, [("test_w_acceptance_races", "test_eight_distinct_valid_permits_for_same_intent_have_one_accept"),
                                ("test_w_acceptance_races", "test_eight_claims_share_one_attempt_and_later_revoke_cannot_cancel")]),
        "sources": ["AADP request_id replay", "ZJJ intent tombstone/nonce/attempt"],
    },
    {
        "id": "P07",
        "name": "崩溃恢复",
        "aadp": "PARTIAL",
        "ap2": None,
        "zjj": any_passed(ZJJ, [("test_crash_boundaries", "test_accept_commit_crash_leaves_one_committed_operation_and_pending_receipt"),
                                ("test_crash_boundaries", "test_exec_marker_crash_uses_one_execution_qualification_and_does_not_call_tool"),
                                ("test_crash_boundaries", "test_settlement_commit_crash_is_recovered_without_a_second_settlement")]),
        "sources": ["AADP has rebuild/audit recovery, no process-kill boundary test in the frozen revision", "ZJJ 3 real child-process crash boundaries"],
    },
    {
        "id": "P08",
        "name": "审批及撤销语义",
        "aadp": any_passed(AADP, [("tests.guardrail.test_approval_consumption", "test_approval_is_consumed_before_evaluation"),
                                  ("tests.guardrail.test_approver_identity", "test_resume_approval_refuses_the_proposer_and_executes_nothing")]),
        "ap2": None,
        "zjj": any_passed(ZJJ, [("test_common_authorization", "test_current_role_revoke_and_regrant_cannot_revalidate_old_deps"),
                                ("test_common_authorization", "test_published_deny_is_not_bypassed_by_omission_or_later_approval")]),
        "sources": ["AADP approvals", "ZJJ role revocation/deny coverage"],
    },
    {
        "id": "P09",
        "name": "执行结果关联",
        "aadp": any_passed(AADP, [("tests.guardrail.test_report_outcome", "test_all_four_outcomes_are_expressible"),
                                  ("tests.guardrail.test_report_outcome", "test_settlement_depends_on_the_outcome[timeout]")]),
        "ap2": any_passed(AP2, [("tests.receipt_wrapper_tests", "test_verify_payment_receipt_success")]),
        "zjj": any_passed(ZJJ, [("test_common_w", "test_full_chain_exec_query_and_once_settlement_three_profiles"),
                                ("test_w_recovery", "test_three_profiles_lost_ack_query_same_fact_without_new_exec")]),
        "sources": ["AADP report_result", "AP2 receipt", "ZJJ attempt/final/settlement binding"],
    },
    {
        "id": "P10",
        "name": "历史证据独立验证",
        "aadp": any_passed(AADP, [("tests.guardrail.test_audit_append_only", "test_replay_returns_prior_result_and_adds_no_rows")]),
        "ap2": any_passed(AP2, [("tests.receipt_wrapper_tests", "test_verify_receipt_invalid_signature")]),
        "zjj": any_passed(ZJJ, [("test_evidence_verifier", "test_clean_package_passes_independent_audit"),
                                ("test_cross_scenario_evidence", "test_each_profile_passes_offline_audit")]),
        "sources": ["AADP hash-chained audit", "AP2 receipt verification", "ZJJ offline evidence verifier"],
    },
    {
        "id": "P11",
        "name": "高后果恶意动作阻断",
        "aadp": True,
        "ap2": "PARTIAL",
        "zjj": "PARTIAL",
        "sources": ["AADP eval: harmful carried out 16 -> 3", "AP2 scope/amount constraints", "ZJJ policy-bound action; LLM benchmark pending"],
        "note": "AADP eval is scripted, not model-based; ZJJ row is deterministic authorization, not an LLM agent score.",
    },
    {
        "id": "P12",
        "name": "跨步骤安全状态保持",
        "aadp": any_passed(AADP, [("tests.guardrail.test_sequence", "test_count_over_denies_a_second_refund_over_threshold_within_the_window")]),
        "ap2": "PARTIAL",
        "zjj": any_passed(ZJJ, [("test_goal_floor", "test_pending_required_obligation_blocks_a_second_accept"),
                                ("test_goal_floor", "test_required_action_links_and_settlement_marks_done")]),
        "sources": ["AADP sequence rules", "Tether stateful policy (paper only)", "ZJJ GoalFloor/W ledger"],
    },
    {
        "id": "P13",
        "name": "跨信任边界动作绑定凭证",
        "aadp": any_passed(AADP, [("tests.permit.test_recipient", "test_a_valid_permit_from_end_to_end_is_verified"),
                                  ("tests.permit.test_recipient", "test_a_tampered_permit_body_fails_signature_verification"),
                                  ("tests.permit.test_recipient", "test_a_replay_with_a_different_content_digest_after_completion_is_a_permanent_conflict")]),
        "ap2": any_passed(AP2, [("tests.chain_tests", "test_three_step_bank_sa_cp_merchant_flow")]),
        "zjj": "PARTIAL",
        "sources": ["AADP bound-permit profile 23/24 (V17 gap)", "AP2 delegated mandate chain",
                    "ZJJ internal delivery/attempt receipt; no public cross-organization bound-permit profile"],
        "note": "ZJJ binds a tool delivery packet to action, attempt and commit, but this is an internal W-to-tool credential, not an AADP-style cross-domain permit.",
    },
]


def normalize(value):
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    if value is None:
        return "N/A"
    return str(value)


def main():
    for row in PROPERTIES:
        row["aadp"] = normalize(row["aadp"])
        row["ap2"] = normalize(row["ap2"])
        row["zjj"] = normalize(row["zjj"])
    # A property is common/applicable when at least one competitor has a
    # verified public capability and ZJJ has an executable mapping.
    applicable = [row for row in PROPERTIES
                  if row["zjj"] in ("PASS", "PARTIAL") and
                  (row["aadp"] == "PASS" or row["ap2"] == "PASS")]
    satisfied = [row for row in applicable if row["zjj"] == "PASS"]
    payload = {
        "definition": {
            "coverage_num": "ZJJ properties satisfied",
            "coverage_den": "competitor-verified and commonly applicable properties",
            "coverage": len(satisfied) / len(applicable) if applicable else None,
            "note": "Property-level, not a claim of implementation equivalence or universal proof.",
        },
        "properties": PROPERTIES,
        "applicable": [row["id"] for row in applicable],
        "satisfied": [row["id"] for row in satisfied],
        "not_satisfied": [row["id"] for row in applicable if row["zjj"] != "PASS"],
        "coverage": len(satisfied) / len(applicable) if applicable else None,
        "junit": {
            "aadp_selected": {"passed": sum(AADP.values()), "total": len(AADP)},
            "ap2_all": {"passed": sum(AP2.values()), "total": len(AP2)},
            "zjj_selected": {"passed": sum(ZJJ.values()), "total": len(ZJJ)},
        },
    }
    (RESULTS / "capability_coverage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["definition"], ensure_ascii=False, indent=2))
    for row in PROPERTIES:
        print(row["id"], row["name"], row["aadp"], row["ap2"], row["zjj"])


if __name__ == "__main__":
    main()
