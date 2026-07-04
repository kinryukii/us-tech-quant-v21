#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

STAGE = "V21.250_TECHNICAL_DIAGNOSTIC_FREEZE_AND_MANUAL_CHECKLIST_ARCHIVE_R1"
OUT_REL = Path("outputs/v21") / STAGE
V246_REL = Path("outputs/v21/V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1")
V247_REL = Path("outputs/v21/V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT")
V248_REL = Path("outputs/v21/V21.248_TECHNICAL_SIGNAL_FAILURE_ATTRIBUTION_AND_REPAIR_SPEC_R1")
V249_REL = Path("outputs/v21/V21.249_TECHNICAL_REPAIR_SPEC_PIT_RETEST_R1")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "automatic_timing_overlay_allowed": False,
    "context_filter_integration_allowed": False,
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


def intv(v: Any) -> int:
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def stage_roots(repo: Path, v246: Path, v247: Path, v248: Path, v249: Path) -> dict[str, Path]:
    return {
        "V21.246": v246 if v246.is_absolute() else repo / v246,
        "V21.247": v247 if v247.is_absolute() else repo / v247,
        "V21.248": v248 if v248.is_absolute() else repo / v248,
        "V21.249": v249 if v249.is_absolute() else repo / v249,
    }


def load_summaries(roots: dict[str, Path]) -> dict[str, dict[str, Any]]:
    files = {
        "V21.246": "v21_246_summary.json",
        "V21.247": "v21_247_summary.json",
        "V21.248": "v21_248_summary.json",
        "V21.249": "v21_249_summary.json",
    }
    return {stage: read_json(root / files[stage]) for stage, root in roots.items()}


def noncritical_missing(roots: dict[str, Path]) -> list[str]:
    required = {
        "V21.246": ["technical_panel_quality_audit.csv", "forward_return_quality_audit.csv"],
        "V21.247": ["technical_subfactor_effectiveness_master.csv", "technical_subfactor_candidate_for_v21_248.csv"],
        "V21.248": ["technical_repair_candidate_spec.csv", "technical_signal_final_disposition.csv"],
        "V21.249": ["technical_repair_role_recommendation.csv", "technical_repair_keep_drop_review.csv"],
    }
    missing = []
    for stage, names in required.items():
        for name in names:
            if not (roots[stage] / name).exists():
                missing.append(f"{stage}/{name}")
    return missing


def chain_audit(roots: dict[str, Path], summaries: dict[str, dict[str, Any]], missing: list[str]) -> list[dict[str, Any]]:
    rows = []
    labels = {
        "V21.246": "technical forward panel build",
        "V21.247": "technical effectiveness PIT-lite audit",
        "V21.248": "failure attribution and repair spec",
        "V21.249": "repair spec PIT retest",
    }
    for stage, label in labels.items():
        s = summaries.get(stage, {})
        rows.append({"stage": stage, "stage_description": label, "root": str(roots[stage]), "summary_found": bool(s), "final_status": s.get("final_status", ""), "final_decision": s.get("final_decision", ""), "archived": bool(s), "noncritical_missing_count": sum(1 for m in missing if m.startswith(stage + "/")), "research_only": s.get("research_only", True), "official_adoption_allowed": s.get("official_adoption_allowed", False), "broker_action_allowed": s.get("broker_action_allowed", False)})
    return rows


def final_disposition() -> list[dict[str, Any]]:
    return [
        {"disposition_label": "MODEL_ENTRY_BLOCKED", "allowed": False, "reason": "V21.249 found zero passed repair candidates and zero confirmed incremental edge."},
        {"disposition_label": "WEIGHT_UPDATE_BLOCKED", "allowed": False, "reason": "No technical repair passed research gates."},
        {"disposition_label": "AUTOMATIC_TIMING_OVERLAY_BLOCKED", "allowed": False, "reason": "No timing overlay candidate survived V21.249."},
        {"disposition_label": "CONTEXT_FILTER_BLOCKED", "allowed": False, "reason": "No context filter candidate survived V21.249."},
        {"disposition_label": "MANUAL_CHECKLIST_ALLOWED", "allowed": True, "reason": "Human observation-only checklist is permitted outside ranking/weight/broker inputs."},
        {"disposition_label": "DIAGNOSTIC_ONLY_ARCHIVED", "allowed": True, "reason": "Technical exploration chain archived as diagnostic research."},
    ]


def manual_checklist() -> list[dict[str, Any]]:
    items = [
        "RSI_LOW_REVERSAL_OBSERVATION_ONLY",
        "KDJ_LOW_GOLDEN_CROSS_OBSERVATION_ONLY",
        "BB_PULLBACK_REENTRY_OBSERVATION_ONLY",
        "MACD_LOW_CROSS_OBSERVATION_ONLY",
        "BREAKOUT_NEXT_DAY_CONFIRM_OBSERVATION_ONLY",
        "MULTI_TIMEFRAME_1H_15M_1M_OBSERVATION_ONLY",
    ]
    return [{"checklist_item": item, "manual_review_scope": "human trading review only", "research_only": True, "automated_signal": False, "ranking_input": False, "weight_input": False, "broker_action_input": False} for item in items]


def reopen_conditions() -> list[dict[str, Any]]:
    items = [
        ("NEW_DATA_WINDOW_AVAILABLE", "A materially newer forward sample is available."),
        ("MATERIALLY_LARGER_FORWARD_SAMPLE", "Forward rows increase enough to retest weak/partial signals."),
        ("NEW_TECHNICAL_FEATURE_CONSTRUCTION", "New PIT-safe technical construction is added."),
        ("INDEPENDENT_NON_TECHNICAL_CONFIRMATION", "Non-technical evidence supports a context-conditioned retest."),
        ("EXPLICIT_USER_APPROVAL_TO_REOPEN_TECHNICAL_RESEARCH", "User explicitly requests another technical research cycle."),
    ]
    return [{"reopen_condition": k, "description": v, "required_before_reopen": True, "automatic_reopen_allowed": False} for k, v in items]


def no_go_audit(s249: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("passed_repair_candidate_count_is_zero", intv(s249.get("passed_repair_candidate_count")) == 0, s249.get("passed_repair_candidate_count", "")),
        ("incremental_edge_confirmed_count_is_zero", intv(s249.get("incremental_edge_confirmed_count")) == 0, s249.get("incremental_edge_confirmed_count", "")),
        ("timing_overlay_candidate_count_is_zero", intv(s249.get("timing_overlay_candidate_count")) == 0, s249.get("timing_overlay_candidate_count", "")),
        ("context_filter_candidate_count_is_zero", intv(s249.get("context_filter_candidate_count")) == 0, s249.get("context_filter_candidate_count", "")),
    ]
    rows = [{"check_name": name, "passed": ok, "observed_value": value, "no_go_required": True} for name, ok, value in checks]
    for key, value in GATES.items():
        rows.append({"check_name": key, "passed": value is True if key == "research_only" else value is False, "observed_value": value, "no_go_required": key != "research_only"})
    return rows


def gate_violation(summary: dict[str, Any]) -> bool:
    return any(summary[k] is not v for k, v in GATES.items())


def run(repo: Path, output_dir: Path | None = None, v246_root: Path = V246_REL, v247_root: Path = V247_REL, v248_root: Path = V248_REL, v249_root: Path = V249_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    roots = stage_roots(repo, v246_root, v247_root, v248_root, v249_root)
    summaries = load_summaries(roots)
    s249 = summaries.get("V21.249", {})
    if not s249:
        summary = base_summary("FAIL_V21_250_TECHNICAL_FREEZE_INPUT_MISSING", "TECHNICAL_FREEZE_BLOCKED_MISSING_V21_249_SUMMARY", summaries)
        write_outputs(out, roots, summaries, [], summary)
        return summary
    missing = noncritical_missing(roots)
    zero_gate = intv(s249.get("passed_repair_candidate_count")) == 0 and intv(s249.get("incremental_edge_confirmed_count")) == 0 and intv(s249.get("timing_overlay_candidate_count")) == 0 and intv(s249.get("context_filter_candidate_count")) == 0
    if not zero_gate:
        status = "WARN_V21_250_TECHNICAL_ARCHIVE_INCOMPLETE"
        decision = "TECHNICAL_FREEZE_NOT_CONFIRMED_REVIEW_NONZERO_REPAIR_COUNTS"
    elif missing:
        status = "WARN_V21_250_TECHNICAL_ARCHIVE_INCOMPLETE"
        decision = "TECHNICAL_DIAGNOSTIC_FREEZE_ARCHIVED_WITH_MISSING_NONCRITICAL_INPUTS"
    else:
        status = "PASS_V21_250_TECHNICAL_DIAGNOSTIC_FREEZE_ARCHIVED"
        decision = "TECHNICAL_CHAIN_DIAGNOSTIC_ONLY_ARCHIVED_NO_MODEL_ENTRY"
    summary = base_summary(status, decision, summaries)
    if gate_violation(summary):
        summary["final_status"] = "FAIL_V21_250_TECHNICAL_FREEZE_GATE_VIOLATION"
        summary["final_decision"] = "TECHNICAL_FREEZE_BLOCKED_GATE_VIOLATION"
    write_outputs(out, roots, summaries, missing, summary)
    return summary


def base_summary(status: str, decision: str, summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s246, s248, s249 = summaries.get("V21.246", {}), summaries.get("V21.248", {}), summaries.get("V21.249", {})
    return {
        "final_status": status,
        "final_decision": decision,
        "chain_stage_count": 4,
        "archived_stage_count": sum(1 for s in summaries.values() if s),
        "technical_indicator_count": intv(s246.get("technical_indicator_count") or s248.get("technical_indicator_count")),
        "repair_candidate_count": intv(s249.get("repair_candidate_count") or s248.get("repair_candidate_count")),
        "tested_repair_candidate_count": intv(s249.get("tested_repair_candidate_count")),
        "passed_repair_candidate_count": intv(s249.get("passed_repair_candidate_count")),
        "incremental_edge_confirmed_count": intv(s249.get("incremental_edge_confirmed_count")),
        "timing_overlay_candidate_count": intv(s249.get("timing_overlay_candidate_count")),
        "context_filter_candidate_count": intv(s249.get("context_filter_candidate_count")),
        "manual_checklist_item_count": 6,
        "reopen_condition_count": 5,
        "model_entry_allowed": False,
        "technical_timing_overlay_allowed": False,
        "technical_context_filter_allowed": False,
        "technical_manual_checklist_allowed": True,
        **GATES,
    }


def write_outputs(out: Path, roots: dict[str, Path], summaries: dict[str, dict[str, Any]], missing: list[str], summary: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "technical_chain_archive_audit.csv", chain_audit(roots, summaries, missing), ["stage", "stage_description", "root", "summary_found", "final_status", "final_decision", "archived", "noncritical_missing_count", "research_only", "official_adoption_allowed", "broker_action_allowed"])
    write_csv(out / "technical_signal_final_disposition.csv", final_disposition(), ["disposition_label", "allowed", "reason"])
    write_csv(out / "technical_manual_checklist_archive.csv", manual_checklist(), ["checklist_item", "manual_review_scope", "research_only", "automated_signal", "ranking_input", "weight_input", "broker_action_input"])
    write_csv(out / "technical_reopen_conditions.csv", reopen_conditions(), ["reopen_condition", "description", "required_before_reopen", "automatic_reopen_allowed"])
    write_csv(out / "technical_no_go_decision_audit.csv", no_go_audit(summaries.get("V21.249", {})), ["check_name", "passed", "observed_value", "no_go_required"])
    write_json(out / "v21_250_summary.json", summary)
    (out / "V21.250_technical_diagnostic_freeze_and_manual_checklist_archive_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nmanual_checklist_allowed=True\nmodel_entry_allowed=False\nweight_update_allowed=False\nautomatic_timing_overlay_allowed=False\ncontext_filter_integration_allowed=False\nbroker_action_allowed=False\nmarket_data_fetch_allowed=False\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-246-root", type=Path, default=V246_REL)
    p.add_argument("--v21-247-root", type=Path, default=V247_REL)
    p.add_argument("--v21-248-root", type=Path, default=V248_REL)
    p.add_argument("--v21-249-root", type=Path, default=V249_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_246_root, a.v21_247_root, a.v21_248_root, a.v21_249_root)
    for k in ["final_status", "final_decision", "chain_stage_count", "archived_stage_count", "technical_indicator_count", "repair_candidate_count", "tested_repair_candidate_count", "passed_repair_candidate_count", "incremental_edge_confirmed_count", "timing_overlay_candidate_count", "context_filter_candidate_count", "manual_checklist_item_count", "reopen_condition_count", "model_entry_allowed", "technical_timing_overlay_allowed", "technical_context_filter_allowed", "technical_manual_checklist_allowed", "official_adoption_allowed", "broker_action_allowed", "market_data_fetch_allowed"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
