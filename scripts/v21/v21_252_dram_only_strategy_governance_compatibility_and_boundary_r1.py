#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

STAGE = "V21.252_DRAM_ONLY_STRATEGY_GOVERNANCE_COMPATIBILITY_AND_BOUNDARY_R1"
OUT_REL = Path("outputs/v21") / STAGE
V251_REL = Path("outputs/v21/V21.251_STRATEGY_WEIGHT_GOVERNANCE_FROM_V21_255_AND_CURRENT_REGIME_R1")
V250_REL = Path("outputs/v21/V21.250_TECHNICAL_DIAGNOSTIC_FREEZE_AND_MANUAL_CHECKLIST_ARCHIVE_R1")
DRAM_HINTS = ("V21.201", "V21.232", "V21.234", "V21.241")
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "weight_update_allowed": False,
    "ranking_mutation_allowed": False,
    "trade_plan_mutation_allowed": False,
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


def version_key(path: Path) -> tuple[int, str]:
    m = re.search(r"V21\.(\d+)", path.name)
    return (int(m.group(1)) if m else -1, path.name)


def discover_dram_summary(repo: Path) -> tuple[Path | None, dict[str, Any]]:
    base = repo / "outputs" / "v21"
    candidates: list[Path] = []
    if base.exists():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            upper = d.name.upper()
            if "DRAM" not in upper and not any(h in d.name for h in DRAM_HINTS):
                continue
            for summary in d.glob("*summary*.json"):
                candidates.append(summary)
    candidates.sort(key=lambda p: version_key(p.parent), reverse=True)
    for path in candidates:
        data = read_json(path)
        if data:
            return path, data
    return None, {}


def boundary_policy() -> list[dict[str, Any]]:
    rows = [
        ("DRAM_PRIMARY_FOCUS_ACTIVE", True, "DRAM remains the primary trading focus."),
        ("STRATEGY_GOVERNANCE_RESEARCH_CONTEXT_ONLY", True, "V21.251 roles may inform research context only."),
        ("STRATEGY_GOVERNANCE_RISK_REVIEW_ONLY", True, "Strategy governance may create risk-review warnings only."),
        ("TECHNICAL_CHECKLIST_OBSERVATION_ONLY", True, "V21.250 technical checklist remains observation-only."),
        ("NO_AUTO_TICKER_REPLACEMENT", False, "No automatic ticker replacement is allowed."),
        ("NO_AUTO_POSITION_INCREASE", False, "No automatic position increase is allowed."),
        ("NO_AUTO_TRADE_TRIGGER", False, "No automatic trade trigger is allowed."),
        ("NO_RANKING_MUTATION", False, "No ranking mutation is allowed."),
        ("NO_WEIGHT_UPDATE", False, "No factor or strategy weight update is allowed."),
        ("NO_BROKER_ACTION", False, "No broker action is allowed."),
    ]
    return [{"boundary_label": label, "allowed_or_active": allowed, "policy_detail": detail, "research_only": True} for label, allowed, detail in rows]


def conflict_resolution(current: str, fallback: str, watch: str) -> list[dict[str, Any]]:
    return [
        {"conflict_case": "DRAM_VS_STRATEGY_GOVERNANCE", "policy": "DRAM primary focus remains dominant.", "allowed_action": "RESEARCH_CONTEXT_ONLY", "blocked_action": "TICKER_REPLACEMENT_OR_TRADE_PLAN_MUTATION"},
        {"conflict_case": "STRATEGY_GOVERNANCE_HIGH_RISK_FLAG", "policy": "Risk flags may produce research warnings only.", "allowed_action": "RISK_REVIEW_WARNING", "blocked_action": "BROKER_OR_RANKING_ACTION"},
        {"conflict_case": "HIGH_RETURN_WATCH_OUTPERFORMS", "policy": f"{watch} remains watch-only unless the user explicitly approves broader action.", "allowed_action": "WATCH_ONLY", "blocked_action": "AUTOMATIC_POSITION_CHANGE"},
        {"conflict_case": "TECHNICAL_CHECKLIST_FAVORABLE", "policy": "Technical checklist remains observation-only and cannot unlock trades.", "allowed_action": "MANUAL_OBSERVATION", "blocked_action": "AUTOMATIC_TRADE_TRIGGER"},
        {"conflict_case": "CURRENT_REGIME_VS_LONG_HISTORY", "policy": f"{current} can contextualize current regime; {fallback} can contextualize fallback review only.", "allowed_action": "RESEARCH_REVIEW", "blocked_action": "WEIGHT_UPDATE"},
    ]


def daily_chain_recommendations() -> list[dict[str, Any]]:
    return [
        {"recommendation": "ADD_V21_251_V21_252_CONTEXT_BLOCK", "detail": "Add governance context to daily research reports only.", "allowed": True, "mutation_allowed": False},
        {"recommendation": "DO_NOT_MODIFY_RANKING_OUTPUTS", "detail": "Ranking outputs remain unchanged.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_MODIFY_DRAM_TRADE_PLAN", "detail": "DRAM trade plan remains unchanged.", "allowed": False, "mutation_allowed": False},
        {"recommendation": "DO_NOT_ALTER_BROKER_PERMISSIONS", "detail": "Broker permissions remain locked.", "allowed": False, "mutation_allowed": False},
    ]


def technical_freeze_rows(s250: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("technical_model_entry_allowed", False, "model_entry_allowed"),
        ("technical_timing_overlay_allowed", False, "technical_timing_overlay_allowed"),
        ("technical_context_filter_allowed", False, "technical_context_filter_allowed"),
        ("technical_manual_checklist_allowed", True, "technical_manual_checklist_allowed"),
    ]
    rows = []
    for label, expected, key in checks:
        observed = s250.get(key, expected)
        rows.append({"boundary_item": label, "expected": expected, "observed": observed, "passed": observed == expected, "source": "V21.250"})
    return rows


def dram_audit(dram_path: Path | None, dram_summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"audit_item": "latest_dram_summary_found", "value": bool(dram_path), "source_path": str(dram_path or ""), "detail": "Latest local DRAM-related summary discovery."},
        {"audit_item": "latest_dram_final_status", "value": dram_summary.get("final_status", ""), "source_path": str(dram_path or ""), "detail": "DRAM chain final_status if available."},
        {"audit_item": "latest_dram_final_decision", "value": dram_summary.get("final_decision", ""), "source_path": str(dram_path or ""), "detail": "DRAM chain final_decision if available."},
        {"audit_item": "latest_dram_plan_currentness", "value": dram_summary.get("latest_dram_plan_currentness", dram_summary.get("plan_currentness", "")), "source_path": str(dram_path or ""), "detail": "Plan currentness if exposed by summary."},
        {"audit_item": "broker_action_allowed", "value": dram_summary.get("broker_action_allowed", False), "source_path": str(dram_path or ""), "detail": "Broker action remains blocked for this boundary."},
        {"audit_item": "trade_plan_mutation_allowed", "value": dram_summary.get("trade_plan_mutation_allowed", False), "source_path": str(dram_path or ""), "detail": "Trade plan mutation remains blocked for this boundary."},
    ]


def context_block(s251: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"context_item": "current_regime_shadow_primary", "value": s251.get("current_regime_shadow_primary", ""), "allowed_use": "RESEARCH_CONTEXT_ONLY", "blocked_use": "OFFICIAL_ADOPTION"},
        {"context_item": "long_history_fallback", "value": s251.get("long_history_fallback", ""), "allowed_use": "RISK_REVIEW_ONLY", "blocked_use": "WEIGHT_UPDATE"},
        {"context_item": "high_return_watch_only", "value": s251.get("high_return_watch_only", ""), "allowed_use": "WATCH_ONLY", "blocked_use": "POSITION_CHANGE"},
        {"context_item": "switch_condition_count", "value": s251.get("switch_condition_count", 0), "allowed_use": "RESEARCH_WARNING_ONLY", "blocked_use": "AUTOMATIC_SWITCH"},
        {"context_item": "dram_compatible", "value": s251.get("dram_compatible", False), "allowed_use": "BOUNDARY_CONFIRMATION", "blocked_use": "TRADE_PLAN_MUTATION"},
    ]


def fail_summary(status: str, decision: str, missing: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "dram_primary_focus_active": False,
        "strategy_governance_research_context_only": False,
        "strategy_governance_risk_review_only": False,
        "technical_checklist_observation_only": False,
        "current_regime_shadow_primary": "",
        "long_history_fallback": "",
        "high_return_watch_only": "",
        "conflict_policy_count": 0,
        "daily_chain_recommendation_count": 0,
        "latest_dram_summary_found": False,
        "latest_dram_final_status": "",
        "latest_dram_final_decision": "",
        "latest_dram_plan_currentness": "",
        "missing_input_count": missing,
        "warning_count": 0,
        "error_count": 1,
        **GATES,
    }


def gate_violation(summary: dict[str, Any]) -> bool:
    blocked = [
        "official_adoption_allowed",
        "broker_action_allowed",
        "factor_promotion_allowed",
        "weight_update_allowed",
        "ranking_mutation_allowed",
        "trade_plan_mutation_allowed",
        "automatic_ticker_replacement_allowed",
        "automatic_position_increase_allowed",
        "automatic_trade_trigger_allowed",
        "protected_outputs_modified",
        "market_data_fetch_allowed",
    ]
    return any(summary.get(k) is True for k in blocked) or summary.get("dram_primary_focus_active") is not True


def run(repo: Path, output_dir: Path | None = None, v251_root: Path = V251_REL, v250_root: Path = V250_REL) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    r251, r250 = root(repo, v251_root), root(repo, v250_root)
    s251 = read_json(r251 / "v21_251_summary.json")
    s250 = read_json(r250 / "v21_250_summary.json")
    missing = []
    if not s251:
        missing.append("V21.251 summary")
    if not s250:
        missing.append("V21.250 summary")
    if missing:
        summary = fail_summary("FAIL_V21_252_DRAM_ONLY_BOUNDARY_INPUT_MISSING", "DRAM_ONLY_BOUNDARY_BLOCKED_INPUT_MISSING", len(missing))
        write_outputs(out, [], [], [], [], [], summary)
        return summary

    dram_path, sdram = discover_dram_summary(repo)
    current = s251.get("current_regime_shadow_primary", "")
    fallback = s251.get("long_history_fallback", "")
    watch = s251.get("high_return_watch_only", "")
    boundary = boundary_policy()
    conflicts = conflict_resolution(current, fallback, watch)
    daily = daily_chain_recommendations()
    freeze = technical_freeze_rows(s250)
    freeze_ok = all(r["passed"] for r in freeze)
    latest_currentness = sdram.get("latest_dram_plan_currentness", sdram.get("plan_currentness", ""))
    summary = {
        "final_status": "PASS_V21_252_DRAM_ONLY_BOUNDARY_READY_RESEARCH_ONLY" if dram_path else "WARN_V21_252_DRAM_ONLY_BOUNDARY_READY_WITH_MISSING_DRAM_SUMMARY",
        "final_decision": "DRAM_ONLY_STRATEGY_GOVERNANCE_BOUNDARY_READY_RESEARCH_ONLY" if dram_path else "DRAM_ONLY_BOUNDARY_READY_WITH_MISSING_DRAM_CONTEXT",
        "dram_primary_focus_active": True,
        "strategy_governance_research_context_only": True,
        "strategy_governance_risk_review_only": True,
        "technical_checklist_observation_only": s250.get("technical_manual_checklist_allowed", True) is True,
        "current_regime_shadow_primary": current,
        "long_history_fallback": fallback,
        "high_return_watch_only": watch,
        "conflict_policy_count": len(conflicts),
        "daily_chain_recommendation_count": len(daily),
        "latest_dram_summary_found": bool(dram_path),
        "latest_dram_final_status": sdram.get("final_status", ""),
        "latest_dram_final_decision": sdram.get("final_decision", ""),
        "latest_dram_plan_currentness": latest_currentness,
        "missing_input_count": 0,
        "warning_count": 0 if dram_path else 1,
        "error_count": 0,
        **GATES,
    }
    if not freeze_ok or not summary["technical_checklist_observation_only"] or gate_violation(summary):
        summary["final_status"] = "FAIL_V21_252_DRAM_ONLY_BOUNDARY_GATE_VIOLATION"
        summary["final_decision"] = "DRAM_ONLY_BOUNDARY_BLOCKED_GATE_VIOLATION"
        summary["error_count"] = 1
    write_outputs(out, boundary, conflicts, dram_audit(dram_path, sdram), daily, freeze, summary, context_block(s251))
    return summary


def write_outputs(out: Path, boundary: list[dict[str, Any]], conflicts: list[dict[str, Any]], dram: list[dict[str, Any]], daily: list[dict[str, Any]], freeze: list[dict[str, Any]], summary: dict[str, Any], context: list[dict[str, Any]] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "dram_only_boundary_policy.csv", boundary, ["boundary_label", "allowed_or_active", "policy_detail", "research_only"])
    write_csv(out / "strategy_governance_dram_conflict_resolution.csv", conflicts, ["conflict_case", "policy", "allowed_action", "blocked_action"])
    write_csv(out / "dram_compatibility_audit.csv", dram, ["audit_item", "value", "source_path", "detail"])
    write_csv(out / "daily_chain_integration_recommendation.csv", daily, ["recommendation", "detail", "allowed", "mutation_allowed"])
    write_csv(out / "technical_freeze_boundary_enforcement.csv", freeze, ["boundary_item", "expected", "observed", "passed", "source"])
    write_csv(out / "strategy_governance_research_context_block.csv", context or [], ["context_item", "value", "allowed_use", "blocked_use"])
    write_json(out / "v21_252_summary.json", summary)
    (out / "V21.252_dram_only_strategy_governance_boundary_report.txt").write_text(
        f"{STAGE}\n"
        f"final_status={summary['final_status']}\n"
        f"final_decision={summary['final_decision']}\n"
        f"dram_primary_focus_active={summary['dram_primary_focus_active']}\n"
        f"strategy_governance_research_context_only={summary['strategy_governance_research_context_only']}\n"
        f"strategy_governance_risk_review_only={summary['strategy_governance_risk_review_only']}\n"
        f"technical_checklist_observation_only={summary['technical_checklist_observation_only']}\n"
        "official_adoption_allowed=False\nbroker_action_allowed=False\nweight_update_allowed=False\n"
        "ranking_mutation_allowed=False\ntrade_plan_mutation_allowed=False\n"
        "automatic_ticker_replacement_allowed=False\nautomatic_position_increase_allowed=False\n"
        "automatic_trade_trigger_allowed=False\nmarket_data_fetch_allowed=False\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--v21-251-root", type=Path, default=V251_REL)
    p.add_argument("--v21-250-root", type=Path, default=V250_REL)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.output_dir, a.v21_251_root, a.v21_250_root)
    for k in [
        "final_status",
        "final_decision",
        "dram_primary_focus_active",
        "strategy_governance_research_context_only",
        "strategy_governance_risk_review_only",
        "technical_checklist_observation_only",
        "current_regime_shadow_primary",
        "long_history_fallback",
        "high_return_watch_only",
        "conflict_policy_count",
        "daily_chain_recommendation_count",
        "latest_dram_summary_found",
        "latest_dram_final_status",
        "latest_dram_final_decision",
        "latest_dram_plan_currentness",
        "official_adoption_allowed",
        "broker_action_allowed",
        "weight_update_allowed",
        "ranking_mutation_allowed",
        "trade_plan_mutation_allowed",
        "automatic_ticker_replacement_allowed",
        "automatic_position_increase_allowed",
        "automatic_trade_trigger_allowed",
        "market_data_fetch_allowed",
        "missing_input_count",
        "warning_count",
        "error_count",
    ]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
