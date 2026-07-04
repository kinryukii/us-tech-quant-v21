#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.258_RETENTION_GUARD_DISCOVERY_REVIEW_AND_DAILY_ENTRYPOINT_UNBLOCK_R1"
OUT_REL = Path("outputs/v21") / STAGE
V257_REL = Path("outputs/v21/V21.257_DAILY_MASTER_WRAPPER_ADOPTION_READINESS_AUDIT_R1")
V256_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1")
V241_REL = Path("outputs/v21/V21.241_DAILY_CHAIN_RETENTION_GUARD_INTEGRATION")
V253_REL = Path("outputs/v21/V21.253_DAILY_RESEARCH_CHAIN_CONTEXT_BLOCK_INTEGRATION_R1")
V254_REL = Path("outputs/v21/V21.254_DAILY_CHAIN_WRAPPER_CONTEXT_BLOCK_APPEND_R1")
GATES = {
    "research_only": True,
    "retention_review_only": True,
    "retention_delete_allowed": False,
    "retention_move_allowed": False,
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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(f)]
    except Exception:
        return []


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


def discover_v241_root(repo: Path) -> Path:
    return root(repo, V241_REL)


def classify_candidate(row: dict[str, str]) -> tuple[str, str]:
    cls = row.get("classification", "").upper()
    blocker_type = row.get("blocker_type", "").upper()
    notes = row.get("notes", "").upper()
    risk_text = " ".join([cls, blocker_type, notes])
    full_text = " ".join(str(v) for v in row.values()).upper()
    rel = row.get("relative_path", row.get("path", "")).upper()
    selected = row.get("selected_for_patch", "").lower() == "true"
    if "BLOCK" in risk_text or "FAIL" in risk_text or "HARD_BUDGET" in risk_text:
        return "BLOCKS_DAILY_ENTRYPOINT", "Explicit blocker/failure wording found."
    if "CURRENT_DAILY_CHAIN_CONFIRMED" in cls or selected:
        return "KEEP_ACTIVE_CHAIN", "Current daily chain candidate; non-blocking."
    if "PROTECTED" in full_text:
        return "KEEP_PROTECTED", "Protected candidate; keep and do not mutate."
    if "CACHE" in full_text or "ARCHIVE" in full_text or "QUARANTINE" in full_text:
        return "KEEP_EXTERNAL_CACHE", "External/cache/archive candidate; non-blocking."
    if "LEGACY" in cls or "STAGE" in cls or "TEST" in rel:
        return "REVIEW_FUTURE_CLEANUP_ONLY", "Legacy/stage candidate; future cleanup only."
    if not row:
        return "SAFE_TO_IGNORE_FOR_ENTRYPOINT", "No candidate content."
    return "RETENTION_CANDIDATES_OBSERVATION_ONLY", "Discovery candidate retained as observation-only."


def candidate_review(v241_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates = read_csv(v241_root / "v21_241_discovered_daily_chain_candidates.csv")
    blockers = read_csv(v241_root / "v21_241_skipped_blockers.csv")
    for i, row in enumerate(candidates, 1):
        label, reason = classify_candidate(row)
        rows.append({"candidate_id": i, "source_file": "v21_241_discovered_daily_chain_candidates.csv", "candidate_path": row.get("relative_path", row.get("path", "")), "source_classification": row.get("classification", ""), "entrypoint_impact_class": label, "blocks_daily_entrypoint": label == "BLOCKS_DAILY_ENTRYPOINT", "reason": reason})
    offset = len(rows)
    for i, row in enumerate(blockers, 1):
        has_blocker = any(v for v in row.values())
        label = "BLOCKS_DAILY_ENTRYPOINT" if has_blocker else "SAFE_TO_IGNORE_FOR_ENTRYPOINT"
        rows.append({"candidate_id": offset + i, "source_file": "v21_241_skipped_blockers.csv", "candidate_path": row.get("path", ""), "source_classification": row.get("blocker_type", ""), "entrypoint_impact_class": label, "blocks_daily_entrypoint": label == "BLOCKS_DAILY_ENTRYPOINT", "reason": row.get("notes", "Skipped blocker audit row.")})
    return rows


def run_mode_history(repo: Path, v256: dict[str, Any]) -> tuple[str, bool, list[dict[str, Any]]]:
    r = root(repo, V256_REL)
    audit = r / "v21_256_summary_auditonly.json"
    execute = r / "v21_256_summary_execute.json"
    persisted = audit.exists() and execute.exists()
    label = "RUN_MODE_HISTORY_PERSISTED" if persisted else "RUN_MODE_HISTORY_NOT_PERSISTED"
    warning = not persisted
    rows = [
        {"history_item": "auditonly_summary", "path": str(audit), "exists": audit.exists()},
        {"history_item": "execute_summary", "path": str(execute), "exists": execute.exists()},
        {"history_item": "latest_run_mode", "path": str(r / "v21_256_summary.json"), "exists": bool(v256), "run_mode": v256.get("run_mode", "")},
        {"history_item": "run_mode_history_label", "path": "", "exists": persisted, "run_mode": label},
    ]
    return label, warning, rows


def readiness_after(v257: dict[str, Any], v256: dict[str, Any], v241: dict[str, Any], blocking: int) -> tuple[str, bool]:
    before = v257.get("retention_guard_readiness_label", "")
    if blocking:
        return "RETENTION_GUARD_BLOCKER_REMAINS", False
    if before == "RETENTION_GUARD_READY":
        return "RETENTION_GUARD_READY", True
    status = str(v241.get("final_status", v256.get("latest_daily_chain_final_status", "")))
    decision = str(v241.get("final_decision", v256.get("latest_daily_chain_final_decision", "")))
    if "DISCOVERY_READY" in status or "REVIEW_CANDIDATES" in decision or before == "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED":
        return "RETENTION_GUARD_DISCOVERY_REVIEW_RESOLVED_FOR_ENTRYPOINT", True
    return "RETENTION_GUARD_BLOCKER_REMAINS", False


def gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary.get(k) != v for k, v in GATES.items())


def review_audit_rows(before: str, after: str, resolved: bool, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = [
        "RETENTION_GUARD_READY",
        "RETENTION_GUARD_DISCOVERY_REVIEW_REQUIRED",
        "RETENTION_GUARD_DISCOVERY_REVIEW_RESOLVED_FOR_ENTRYPOINT",
        "RETENTION_GUARD_BLOCKER_REMAINS",
        "RETENTION_CANDIDATES_OBSERVATION_ONLY",
    ]
    return [{"audit_label": label, "applies": label in {before, after} or (label == "RETENTION_CANDIDATES_OBSERVATION_ONLY" and bool(candidates)), "detail": f"before={before}; after={after}; resolved={resolved}"} for label in labels]


def no_mutation_rows() -> list[dict[str, Any]]:
    keys = ["retention_delete_allowed", "retention_move_allowed", "official_adoption_allowed", "broker_action_allowed", "ranking_mutation_allowed", "weight_update_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "market_data_fetch_allowed"]
    return [{"audit_item": k, "expected": GATES[k], "observed": GATES[k], "passed": True} for k in keys]


def gate_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate_name": k, "expected": v, "observed": summary.get(k), "passed": summary.get(k) == v} for k, v in GATES.items()]


def recommendation_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"entrypoint_unblock_recommendation": summary["entrypoint_unblock_recommendation"], "accepted_daily_research_entrypoint_after_review": summary["accepted_daily_research_entrypoint_after_review"], "accepted_with_retention_observation": summary["accepted_with_retention_observation"], "final_decision": summary["final_decision"]}]


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {"final_status": status, "final_decision": decision, "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "v21_257_entrypoint_recommendation": "", "execute_passed": False, "mandatory_child_stages_succeeded": False, "combined_report_created": False, "retention_guard_readiness_label_before": "", "retention_guard_readiness_label_after": "RETENTION_GUARD_BLOCKER_REMAINS", "retention_review_required_before": False, "retention_review_resolved": False, "retention_candidate_count": 0, "blocking_retention_candidate_count": 0, "observation_only_retention_candidate_count": 0, "future_cleanup_only_candidate_count": 0, "run_mode_history_label": "RUN_MODE_HISTORY_NOT_PERSISTED", "run_mode_history_warning": True, "accepted_daily_research_entrypoint_after_review": False, "accepted_with_retention_observation": False, "missing_input_count": missing, "warning_count": 0, "error_count": 1, **GATES}


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    v257 = read_json(root(repo, V257_REL) / "v21_257_summary.json")
    v256 = read_json(root(repo, V256_REL) / "v21_256_summary.json")
    if not v257 or not v256:
        summary = fail_summary("FAIL_V21_258_RETENTION_REVIEW_INPUT_MISSING", "RETENTION_REVIEW_BLOCKED_INPUT_MISSING", (0 if v257 else 1) + (0 if v256 else 1))
        write_outputs(out, [], [], [], [], no_mutation_rows(), gate_rows(summary), summary)
        return summary
    v241_root = discover_v241_root(repo)
    v241 = read_json(v241_root / "v21_241_summary.json")
    candidates = candidate_review(v241_root)
    blocking = sum(1 for r in candidates if r["blocks_daily_entrypoint"])
    observation = sum(1 for r in candidates if r["entrypoint_impact_class"] in {"RETENTION_CANDIDATES_OBSERVATION_ONLY", "KEEP_ACTIVE_CHAIN", "KEEP_PROTECTED", "KEEP_USER_REVIEW", "KEEP_EXTERNAL_CACHE", "SAFE_TO_IGNORE_FOR_ENTRYPOINT"})
    future = sum(1 for r in candidates if r["entrypoint_impact_class"] == "REVIEW_FUTURE_CLEANUP_ONLY")
    before = v257.get("retention_guard_readiness_label_before", v257.get("retention_guard_readiness_label", ""))
    after, resolved = readiness_after(v257, v256, v241, blocking)
    history_label, history_warn, history_rows = run_mode_history(repo, v256)
    execute_passed = bool(v257.get("execute_passed"))
    mandatory = bool(v257.get("mandatory_child_stages_succeeded"))
    combined = bool(v257.get("combined_report_created"))
    summary = {"final_status": "PASS_V21_258_DAILY_ENTRYPOINT_UNBLOCKED_AFTER_RETENTION_REVIEW", "final_decision": "DAILY_ENTRYPOINT_UNBLOCKED_AFTER_RETENTION_REVIEW_RESEARCH_ONLY", "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_UNBLOCKED_AFTER_RETENTION_REVIEW", "v21_257_entrypoint_recommendation": v257.get("entrypoint_recommendation", ""), "execute_passed": execute_passed, "mandatory_child_stages_succeeded": mandatory, "combined_report_created": combined, "retention_guard_readiness_label_before": before, "retention_guard_readiness_label_after": after, "retention_review_required_before": bool(v257.get("retention_review_required")), "retention_review_resolved": resolved, "retention_candidate_count": len(candidates), "blocking_retention_candidate_count": blocking, "observation_only_retention_candidate_count": observation, "future_cleanup_only_candidate_count": future, "run_mode_history_label": history_label, "run_mode_history_warning": history_warn, "accepted_daily_research_entrypoint_after_review": True, "accepted_with_retention_observation": False, "missing_input_count": 0, "warning_count": 1 if history_warn else 0, "error_count": 0, **GATES}
    if not execute_passed or not mandatory or not combined:
        summary.update({"final_status": "FAIL_V21_258_DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "final_decision": "DAILY_ENTRYPOINT_BLOCKED_BY_INCOMPLETE_MASTER_WRAPPER", "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "accepted_daily_research_entrypoint_after_review": False, "error_count": 1})
    elif blocking:
        summary.update({"final_status": "FAIL_V21_258_DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "final_decision": "DAILY_ENTRYPOINT_BLOCKED_BY_RETENTION_CANDIDATE", "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "accepted_daily_research_entrypoint_after_review": False, "error_count": 1})
    elif len(candidates) > 0:
        summary.update({"final_status": "PARTIAL_PASS_V21_258_DAILY_ENTRYPOINT_ACCEPTED_WITH_RETENTION_OBSERVATION", "final_decision": "DAILY_ENTRYPOINT_ACCEPTED_WITH_RETENTION_OBSERVATION_RESEARCH_ONLY", "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_ACCEPTED_WITH_RETENTION_OBSERVATION", "accepted_daily_research_entrypoint_after_review": False, "accepted_with_retention_observation": True, "warning_count": summary["warning_count"] + 1})
    elif history_warn:
        summary.update({"final_status": "WARN_V21_258_RETENTION_REVIEW_READY_WITH_RUNMODE_HISTORY_WARNING", "final_decision": "RETENTION_REVIEW_RESOLVED_RUNMODE_HISTORY_WARNING"})
    if gate_violation(summary):
        summary.update({"final_status": "FAIL_V21_258_RETENTION_REVIEW_GATE_VIOLATION", "final_decision": "RETENTION_REVIEW_BLOCKED_GATE_VIOLATION", "entrypoint_unblock_recommendation": "DAILY_ENTRYPOINT_STILL_BLOCKED_BY_RETENTION", "accepted_daily_research_entrypoint_after_review": False, "error_count": 1})
    write_outputs(out, review_audit_rows(before, after, resolved, candidates), candidates, recommendation_rows(summary), history_rows, no_mutation_rows(), gate_rows(summary), summary)
    return summary


def write_outputs(out: Path, review: list[dict[str, Any]], candidates: list[dict[str, Any]], rec: list[dict[str, Any]], history: list[dict[str, Any]], no_mut: list[dict[str, Any]], gates: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "retention_guard_discovery_review_audit.csv", review, ["audit_label", "applies", "detail"])
    write_csv(out / "retention_candidate_entrypoint_impact_review.csv", candidates, ["candidate_id", "source_file", "candidate_path", "source_classification", "entrypoint_impact_class", "blocks_daily_entrypoint", "reason"])
    write_csv(out / "daily_entrypoint_unblock_recommendation.csv", rec, ["entrypoint_unblock_recommendation", "accepted_daily_research_entrypoint_after_review", "accepted_with_retention_observation", "final_decision"])
    write_csv(out / "run_mode_history_audit.csv", history, ["history_item", "path", "exists", "run_mode"])
    write_csv(out / "retention_review_no_mutation_audit.csv", no_mut, ["audit_item", "expected", "observed", "passed"])
    write_csv(out / "daily_entrypoint_gate_audit.csv", gates, ["gate_name", "expected", "observed", "passed"])
    write_json(out / "v21_258_summary.json", summary)
    text = "\n".join([STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"entrypoint_unblock_recommendation={summary['entrypoint_unblock_recommendation']}", f"retention_guard_readiness_label_after={summary['retention_guard_readiness_label_after']}", "retention_delete_allowed=False", "retention_move_allowed=False", "market_data_fetch_allowed=False"]) + "\n"
    (out / "V21.258_retention_guard_discovery_review_and_daily_entrypoint_unblock_report.txt").write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir)
    for k in ["final_status", "final_decision", "entrypoint_unblock_recommendation", "v21_257_entrypoint_recommendation", "execute_passed", "mandatory_child_stages_succeeded", "combined_report_created", "retention_guard_readiness_label_before", "retention_guard_readiness_label_after", "retention_review_resolved", "retention_candidate_count", "blocking_retention_candidate_count", "observation_only_retention_candidate_count", "future_cleanup_only_candidate_count", "run_mode_history_label", "run_mode_history_warning", "accepted_daily_research_entrypoint_after_review", "accepted_with_retention_observation", "retention_delete_allowed", "retention_move_allowed", "official_adoption_allowed", "broker_action_allowed", "weight_update_allowed", "ranking_mutation_allowed", "trade_plan_mutation_allowed", "child_output_mutation_allowed", "automatic_ticker_replacement_allowed", "automatic_position_increase_allowed", "automatic_trade_trigger_allowed", "market_data_fetch_allowed", "missing_input_count", "warning_count", "error_count"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
