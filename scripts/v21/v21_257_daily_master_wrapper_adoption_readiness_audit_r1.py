#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.257_DAILY_MASTER_WRAPPER_ADOPTION_READINESS_AUDIT_R1"
OUT_REL = Path("outputs/v21") / STAGE
V256_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1")
V241_REL = Path("outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION")
V253_REL = Path("outputs/v21/V21.253_DAILY_RESEARCH_CHAIN_CONTEXT_BLOCK_INTEGRATION_R1")
V254_REL = Path("outputs/v21/V21.254_DAILY_CHAIN_WRAPPER_CONTEXT_BLOCK_APPEND_R1")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "trade_plan_mutation_allowed": False,
    "child_output_mutation_allowed": False,
    "automatic_ticker_replacement_allowed": False,
    "automatic_position_increase_allowed": False,
    "automatic_trade_trigger_allowed": False,
    "protected_outputs_modified": False,
    "market_data_fetch_allowed": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def root(repo: Path, rel: Path) -> Path:
    return rel if rel.is_absolute() else repo / rel


def load_v256_modes(repo: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    r = root(repo, V256_REL)
    active = read_json(r / "v21_256_summary.json")
    audit = read_json(r / "v21_256_summary_auditonly.json")
    execute = read_json(r / "v21_256_summary_execute.json")
    if active.get("run_mode") == "AuditOnly" and not audit:
        audit = active
    if active.get("run_mode") == "Execute" and not execute:
        execute = active
    return active, audit, execute


def passed(summary: dict[str, Any]) -> bool:
    return bool(summary) and not str(summary.get("final_status", "")).startswith("FAIL")


def retention_label(v241: dict[str, Any], v256: dict[str, Any]) -> tuple[str, bool]:
    status = str(v241.get("final_status", v256.get("latest_daily_chain_final_status", "")))
    decision = str(v241.get("final_decision", v256.get("latest_daily_chain_final_decision", "")))
    found = bool(v241 or v256.get("retention_guard_status_found"))
    if found and ("READY" in status and "DISCOVERY" not in status and "REVIEW" not in decision):
        return "RETENTION_GUARD_READY", False
    if (not v256.get("retention_guard_status_found", found)) and ("DISCOVERY_READY" in status or "REVIEW_CANDIDATES" in decision):
        return "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED", True
    if "DISCOVERY_READY" in status or "REVIEW_CANDIDATES" in decision:
        return "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED", True
    return "RETENTION_GUARD_MISSING", True


def gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) != v for k, v in GATES.items())


def audit_rows(audit: dict[str, Any], execute: dict[str, Any], v241: dict[str, Any], v253: dict[str, Any], v254: dict[str, Any], retention: str) -> list[dict[str, Any]]:
    checks = [
        ("AUDITONLY_MODE_PASSES", passed(audit), "V21.256 AuditOnly output is pass/warn but not fail."),
        ("EXECUTE_MODE_PASSES", passed(execute), "V21.256 Execute output is required for entrypoint acceptance."),
        ("ALL_MANDATORY_CHILD_STAGES_SUCCEED", bool(execute.get("daily_chain_stage_succeeded") and execute.get("context_block_stage_succeeded") and execute.get("context_append_stage_succeeded")), "Daily chain, context block, and append stages must succeed."),
        ("COMBINED_REPORT_CREATED", bool(execute.get("combined_report_created") or v254.get("combined_report_created")), "Combined report artifact must exist."),
        ("CONTEXT_BLOCK_AVAILABLE", bool(v253), "V21.253 context block summary must be available."),
        ("APPEND_REPORT_AVAILABLE", bool(v254), "V21.254 append summary must be available."),
        ("DRAM_PRIMARY_FOCUS_ACTIVE", bool(execute.get("dram_primary_focus_active", v253.get("dram_primary_focus_active", False))), "DRAM focus remains active."),
        ("TECHNICAL_FREEZE_ENFORCED", bool(execute.get("technical_freeze_enforced", v253.get("technical_freeze_enforced", False))), "Technical freeze must be enforced."),
        ("STRATEGY_GOVERNANCE_RESEARCH_ONLY", bool(execute.get("strategy_governance_research_context_only", v253.get("strategy_governance_research_context_only", False))), "Strategy governance is research context only."),
        ("RETENTION_GUARD_READINESS", retention in {"RETENTION_GUARD_READY", "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED"}, retention),
    ]
    return [{"check_name": name, "passed": ok, "detail": detail} for name, ok, detail in checks]


def gate_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate_name": k, "expected": v, "observed": summary.get(k), "passed": summary.get(k) == v} for k, v in GATES.items()]


def keep_watch_fix(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if summary["accepted_daily_research_entrypoint"]:
        action = "KEEP_AS_RESEARCH_ENTRYPOINT"
    elif summary["accepted_with_retention_review_required"]:
        action = "KEEP_WITH_RETENTION_REVIEW"
    elif summary["execute_passed"] is False:
        action = "FIX_EXECUTE_MODE"
    else:
        action = "WATCH_AND_REPAIR"
    return [
        {"review_item": "V21.256_master_wrapper", "review_action": action, "reason": summary["entrypoint_recommendation"]},
        {"review_item": "retention_guard", "review_action": "REVIEW_REQUIRED" if summary["retention_review_required"] else "KEEP", "reason": summary["retention_guard_readiness_label"]},
        {"review_item": "no_go_gates", "review_action": "KEEP_LOCKED", "reason": "No official, broker, ranking, weight, trade-plan, child-output, or automatic action gate may unlock."},
    ]


def recommendation_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"entrypoint_recommendation": summary["entrypoint_recommendation"], "accepted_daily_research_entrypoint": summary["accepted_daily_research_entrypoint"], "accepted_with_retention_review_required": summary["accepted_with_retention_review_required"], "final_decision": summary["final_decision"]}]


def retention_rows(label: str, review: bool, v241: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"retention_guard_readiness_label": label, "retention_review_required": review, "v21_241_final_status": v241.get("final_status", ""), "v21_241_final_decision": v241.get("final_decision", "")}]


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "entrypoint_recommendation": "NOT_ACCEPTED_INPUT_MISSING",
        "auditonly_passed": False,
        "execute_passed": False,
        "child_stage_count": 0,
        "child_stage_succeeded_count": 0,
        "mandatory_child_stages_succeeded": False,
        "combined_report_created": False,
        "retention_guard_readiness_label": "RETENTION_GUARD_MISSING",
        "retention_review_required": True,
        "dram_primary_focus_active": False,
        "technical_freeze_enforced": False,
        "strategy_governance_research_context_only": False,
        "accepted_daily_research_entrypoint": False,
        "accepted_with_retention_review_required": False,
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 1,
        **GATES,
    }


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    active, audit, execute = load_v256_modes(repo)
    v241 = read_json(root(repo, V241_REL) / "v21_241_summary.json")
    v253 = read_json(root(repo, V253_REL) / "v21_253_summary.json")
    v254 = read_json(root(repo, V254_REL) / "v21_254_summary.json")
    if not active and not audit and not execute:
        summary = fail_summary("FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_INPUT_MISSING", "DAILY_MASTER_ENTRYPOINT_BLOCKED_V21_256_MISSING", 1)
        write_outputs(out, [], [], [], [], [], summary)
        return summary

    candidate = execute or active
    label, review = retention_label(v241, candidate)
    audit_passed = passed(audit)
    execute_passed = passed(execute)
    mandatory = bool(execute.get("daily_chain_stage_succeeded") and execute.get("context_block_stage_succeeded") and execute.get("context_append_stage_succeeded"))
    combined = bool(execute.get("combined_report_created") or v254.get("combined_report_created"))
    summary = {
        "final_status": "PASS_V21_257_DAILY_MASTER_ENTRYPOINT_ACCEPTED_RESEARCH_ONLY",
        "final_decision": "DAILY_MASTER_WRAPPER_ACCEPTED_AS_RESEARCH_ENTRYPOINT",
        "entrypoint_recommendation": "ACCEPTED_DAILY_RESEARCH_ENTRYPOINT",
        "auditonly_passed": audit_passed,
        "execute_passed": execute_passed,
        "child_stage_count": execute.get("child_stage_count", candidate.get("child_stage_count", 0)),
        "child_stage_succeeded_count": execute.get("child_stage_succeeded_count", candidate.get("child_stage_succeeded_count", 0)),
        "mandatory_child_stages_succeeded": mandatory,
        "combined_report_created": combined,
        "retention_guard_readiness_label": label,
        "retention_review_required": review,
        "dram_primary_focus_active": bool(candidate.get("dram_primary_focus_active", v253.get("dram_primary_focus_active", False))),
        "technical_freeze_enforced": bool(candidate.get("technical_freeze_enforced", v253.get("technical_freeze_enforced", False))),
        "strategy_governance_research_context_only": bool(candidate.get("strategy_governance_research_context_only", v253.get("strategy_governance_research_context_only", False))),
        "accepted_daily_research_entrypoint": True,
        "accepted_with_retention_review_required": False,
        "missing_input_count": 0,
        "warning_count": 0,
        "error_count": 0,
        **GATES,
    }
    if not execute:
        summary.update({"final_status": "WARN_V21_257_DAILY_MASTER_ENTRYPOINT_AUDIT_ONLY_ONLY", "final_decision": "DAILY_MASTER_ENTRYPOINT_AUDIT_ONLY_EXECUTE_REQUIRED", "entrypoint_recommendation": "NOT_ACCEPTED_EXECUTE_MISSING", "accepted_daily_research_entrypoint": False, "warning_count": 1})
    elif not execute_passed or not mandatory:
        summary.update({"final_status": "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_CHILD_FAILURE", "final_decision": "DAILY_MASTER_ENTRYPOINT_BLOCKED_CHILD_FAILURE", "entrypoint_recommendation": "NOT_ACCEPTED_CHILD_FAILURE", "accepted_daily_research_entrypoint": False, "error_count": 1})
    elif not combined:
        summary.update({"final_status": "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_CHILD_FAILURE", "final_decision": "DAILY_MASTER_ENTRYPOINT_BLOCKED_COMBINED_REPORT_MISSING", "entrypoint_recommendation": "NOT_ACCEPTED_CHILD_FAILURE", "accepted_daily_research_entrypoint": False, "error_count": 1})
    elif label == "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED":
        summary.update({"final_status": "PARTIAL_PASS_V21_257_DAILY_MASTER_ENTRYPOINT_ACCEPTED_WITH_RETENTION_REVIEW", "final_decision": "DAILY_MASTER_WRAPPER_ACCEPTED_WITH_RETENTION_REVIEW", "entrypoint_recommendation": "ACCEPTED_WITH_RETENTION_REVIEW_REQUIRED", "accepted_daily_research_entrypoint": False, "accepted_with_retention_review_required": True, "warning_count": 1})
    elif label == "RETENTION_GUARD_MISSING":
        summary.update({"final_status": "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_INPUT_MISSING", "final_decision": "DAILY_MASTER_ENTRYPOINT_BLOCKED_RETENTION_MISSING", "entrypoint_recommendation": "NOT_ACCEPTED_CHILD_FAILURE", "accepted_daily_research_entrypoint": False, "missing_input_count": 1, "error_count": 1})
    if gate_violation(summary):
        summary.update({"final_status": "FAIL_V21_257_DAILY_MASTER_ENTRYPOINT_GATE_VIOLATION", "final_decision": "DAILY_MASTER_ENTRYPOINT_BLOCKED_GATE_VIOLATION", "entrypoint_recommendation": "NOT_ACCEPTED_GATE_VIOLATION", "accepted_daily_research_entrypoint": False, "error_count": 1})
    rows = audit_rows(audit, execute, v241, v253, v254, label)
    write_outputs(out, rows, recommendation_rows(summary), retention_rows(label, review, v241), gate_rows(summary), keep_watch_fix(summary), summary)
    return summary


def write_outputs(out: Path, audit: list[dict[str, Any]], rec: list[dict[str, Any]], retention: list[dict[str, Any]], gates: list[dict[str, Any]], review: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "daily_master_wrapper_adoption_readiness_audit.csv", audit, ["check_name", "passed", "detail"])
    write_csv(out / "daily_master_wrapper_entrypoint_recommendation.csv", rec, ["entrypoint_recommendation", "accepted_daily_research_entrypoint", "accepted_with_retention_review_required", "final_decision"])
    write_csv(out / "retention_guard_readiness_audit.csv", retention, ["retention_guard_readiness_label", "retention_review_required", "v21_241_final_status", "v21_241_final_decision"])
    write_csv(out / "daily_master_wrapper_gate_audit.csv", gates, ["gate_name", "expected", "observed", "passed"])
    write_csv(out / "daily_master_wrapper_keep_watch_fix_review.csv", review, ["review_item", "review_action", "reason"])
    write_json(out / "v21_257_summary.json", summary)
    text = "\n".join([f"{STAGE}", f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"entrypoint_recommendation={summary['entrypoint_recommendation']}", f"retention_guard_readiness_label={summary['retention_guard_readiness_label']}", "research_only=True", "official_adoption_allowed=False", "broker_action_allowed=False", "market_data_fetch_allowed=False"]) + "\n"
    (out / "V21.257_daily_master_wrapper_adoption_readiness_audit_report.txt").write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir)
    for k in ["final_status", "final_decision", "entrypoint_recommendation", "auditonly_passed", "execute_passed", "child_stage_count", "child_stage_succeeded_count", "mandatory_child_stages_succeeded", "combined_report_created", "retention_guard_readiness_label", "retention_review_required", "accepted_daily_research_entrypoint", "accepted_with_retention_review_required", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
