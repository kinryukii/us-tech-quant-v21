from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.178_DAILY_DRAM_PLAN_CHAIN_ORCHESTRATOR_R1"
OUT = ROOT / "outputs" / "v21" / STAGE
R1C = ROOT / "outputs" / "v21" / "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
V176 = ROOT / "outputs" / "v21" / "V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1"
V177 = ROOT / "outputs" / "v21" / "V21.177_DAILY_DRAM_PLAN_LEDGER_AND_STALENESS_GATE_R1"
R1A = ROOT / "outputs" / "v21" / "V21.177_R1A_STALENESS_SEMANTIC_REPAIR"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
    "daily_frequency_only": True,
    "intraday_required": False,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def boolish(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def warnings_count(summary: dict[str, Any]) -> int:
    w = summary.get("warnings", [])
    return len(w) if isinstance(w, list) else int(bool(w))


def inline_semantic_repair(v177_summary: dict[str, Any], v177_review: pd.DataFrame) -> dict[str, Any]:
    stale = str(v177_summary.get("staleness_status", ""))
    orig_action = str(v177_summary.get("latest_immediate_action_label", ""))
    orig_allowed = boolish(v177_summary.get("trade_allowed_current", False))
    if stale == "STALE_BLOCK":
        return {
            "corrected_decision": "DAILY_DRAM_PLAN_STALE_DO_NOT_USE",
            "corrected_immediate_action_label": "STALE_DO_NOT_USE",
            "corrected_trade_allowed_current": False,
            "refresh_required": True,
            "trade_plan_currentness": "STALE_BLOCKED",
            "staleness_severity": "BLOCK",
        }
    if stale == "STALE_WARN":
        return {
            "corrected_decision": "DAILY_DRAM_PLAN_LEDGER_ACTIVE_STALE_WARN",
            "corrected_immediate_action_label": "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING" if orig_action == "LIMIT_PLAN_ALLOWED" else orig_action or "WAIT",
            "corrected_trade_allowed_current": orig_allowed,
            "refresh_required": True,
            "trade_plan_currentness": "RECENT_WARN",
            "staleness_severity": "WARN",
        }
    return {
        "corrected_decision": "DAILY_DRAM_PLAN_LEDGER_ACTIVE",
        "corrected_immediate_action_label": orig_action or ("LIMIT_PLAN_ALLOWED" if orig_allowed else "WAIT"),
        "corrected_trade_allowed_current": orig_allowed,
        "refresh_required": False,
        "trade_plan_currentness": "CURRENT",
        "staleness_severity": "NONE",
    }


def consolidated_action(final_decision: str, immediate_action: str, currentness: str, staleness: str) -> str:
    if staleness == "STALE_BLOCK" or currentness == "STALE_BLOCKED":
        return "DRAM_DAILY_PLAN_STALE_BLOCKED"
    if "NO_CHASE" in str(final_decision):
        return "DRAM_DAILY_NO_CHASE"
    if "NO_TRADE" in str(final_decision):
        return "DRAM_DAILY_NO_TRADE"
    if "WAIT" in str(final_decision):
        return "DRAM_DAILY_WAIT"
    if immediate_action == "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING" or currentness == "RECENT_WARN":
        return "DRAM_DAILY_LIMIT_PLAN_ACTIVE_STALE_WARN"
    if immediate_action == "LIMIT_PLAN_ALLOWED" and staleness == "CURRENT_OR_RECENT":
        return "DRAM_DAILY_LIMIT_PLAN_ACTIVE"
    return "DRAM_DAILY_WAIT"


def final_status_decision(action: str, refresh_required: bool, blocking: list[str]) -> tuple[str, str]:
    if "MISSING_DAILY_PLAN" in blocking:
        return "BLOCKED_V21_178_MISSING_DAILY_PLAN", "DAILY_DRAM_CHAIN_BLOCKED_MISSING_PLAN"
    if "MISSING_DRAM_PRICE" in blocking:
        return "BLOCKED_V21_178_MISSING_DRAM_PRICE", "DAILY_DRAM_CHAIN_BLOCKED_MISSING_PRICE"
    if action == "DRAM_DAILY_PLAN_STALE_BLOCKED":
        return "WARN_V21_178_DAILY_DRAM_CHAIN_STALE_BLOCK", "DAILY_DRAM_CHAIN_STALE_DO_NOT_USE"
    if refresh_required or action == "DRAM_DAILY_LIMIT_PLAN_ACTIVE_STALE_WARN":
        return "PARTIAL_PASS_V21_178_DAILY_DRAM_CHAIN_READY_STALE_WARN", "DAILY_DRAM_CHAIN_READY_REFRESH_RECOMMENDED"
    return "PASS_V21_178_DAILY_DRAM_CHAIN_READY", "DAILY_DRAM_CHAIN_READY_RESEARCH_ONLY"


def health_row(stage: str, loaded: bool, summary: dict[str, Any], blocking: bool, notes: str = "") -> dict[str, Any]:
    return {
        "stage": stage,
        "loaded": loaded,
        "final_status": summary.get("final_status", "") if loaded else "",
        "decision": summary.get("decision", "") if loaded else "",
        "warning_count": warnings_count(summary) if loaded else 0,
        "blocking_issue": blocking,
        "notes": notes,
    }


def write_report(summary: dict[str, Any], health: pd.DataFrame, out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"latest_price_date: {summary['latest_price_date']}",
        f"latest_plan_date: {summary['latest_plan_date']}",
        f"setup_classification: {summary['setup_classification']}",
        f"final_trade_decision: {summary['final_trade_decision']}",
        f"consolidated_action_label: {summary['consolidated_action_label']}",
        f"trade_plan_currentness: {summary['trade_plan_currentness']}",
        f"staleness_status: {summary['staleness_status']}",
        f"refresh_required: {summary['refresh_required']}",
        f"trade_allowed_current: {summary['trade_allowed_current']}",
        f"planned_entry/no_chase/stop/tp1/tp2: {summary['planned_entry_base']} / {summary['no_chase_above']} / {summary['stop_loss_base']} / {summary['take_profit_1_base']} / {summary['take_profit_2_base']}",
        "chain_health:",
    ]
    for _, r in health.iterrows():
        lines.append(f"- {r['stage']}: loaded={r['loaded']} status={r['final_status']} blocking={r['blocking_issue']}")
    lines.extend(["blocking_issues:", *([f"- {b}" for b in summary["blocking_issues"]] if summary["blocking_issues"] else ["- none"])])
    lines.extend(["child_stage_warnings:", *([f"- {w}" for w in summary["child_stage_warnings"]] if summary["child_stage_warnings"] else ["- none"])])
    (out_dir / "V21.178_daily_dram_orchestrator_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(out_dir: Path = OUT) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    r1c_summary = read_json(R1C / "V21.174_R1C_summary.json")
    r1c_price = read_csv(R1C / "dram_auto_price_bridge_daily_ohlcv.csv")
    v176_summary = read_json(V176 / "V21.176_daily_dram_summary.json")
    v176_plan = read_csv(V176 / "dram_daily_premarket_trade_plan_latest.csv")
    v177_summary = read_json(V177 / "V21.177_daily_dram_summary.json")
    v177_review = read_csv(V177 / "dram_current_plan_review.csv")
    r1a_summary = read_json(R1A / "V21.177_R1A_summary.json")
    r1a_review = read_csv(R1A / "dram_current_plan_review_REPAIRED.csv")

    r1c_loaded = bool(r1c_summary) and not r1c_price.empty
    v176_loaded = bool(v176_summary) and not v176_plan.empty
    v177_loaded = bool(v177_summary) and not v177_review.empty
    r1a_loaded = bool(r1a_summary) and not r1a_review.empty
    blocking: list[str] = []
    if not r1c_loaded:
        blocking.append("MISSING_DRAM_PRICE")
    if not v176_loaded:
        blocking.append("MISSING_DAILY_PLAN")

    health = pd.DataFrame(
        [
            health_row("V21.174_R1C", r1c_loaded, r1c_summary, not r1c_loaded, "daily price bridge required"),
            health_row("V21.176", v176_loaded, v176_summary, not v176_loaded, "daily premarket plan required"),
            health_row("V21.177", v177_loaded, v177_summary, False if v177_loaded else True, "ledger/staleness state"),
            health_row("V21.177_R1A", r1a_loaded, r1a_summary, False, "preferred repaired staleness semantics" if r1a_loaded else "inline semantic repair fallback"),
        ]
    )

    latest_price_date = str(r1c_summary.get("latest_dram_date") or (r1c_price["date"].max() if not r1c_price.empty and "date" in r1c_price.columns else ""))
    plan = v176_plan.iloc[0].to_dict() if v176_loaded else {}
    if r1a_loaded:
        repaired = r1a_summary
        repaired_row = r1a_review.iloc[0].to_dict()
        corrected_immediate_action = str(repaired.get("corrected_immediate_action_label", repaired_row.get("immediate_action_label_corrected", "")))
        trade_currentness = str(repaired.get("trade_plan_currentness", repaired_row.get("trade_plan_currentness", "")))
        refresh_required = boolish(repaired.get("refresh_required", repaired_row.get("refresh_required", False)))
        trade_allowed_current = boolish(repaired.get("corrected_trade_allowed_current", repaired_row.get("trade_allowed_current_corrected", False)))
        staleness = str(repaired.get("original_staleness_status", repaired_row.get("staleness_status", "")))
    elif v177_loaded:
        repaired = inline_semantic_repair(v177_summary, v177_review)
        corrected_immediate_action = repaired["corrected_immediate_action_label"]
        trade_currentness = repaired["trade_plan_currentness"]
        refresh_required = bool(repaired["refresh_required"])
        trade_allowed_current = bool(repaired["corrected_trade_allowed_current"])
        staleness = str(v177_summary.get("staleness_status", ""))
    else:
        corrected_immediate_action = "WAIT"
        trade_currentness = "UNKNOWN"
        refresh_required = True
        trade_allowed_current = False
        staleness = "UNKNOWN"

    final_decision = str(v176_summary.get("final_trade_decision", plan.get("final_decision", ""))) if v176_loaded else "DRAM_DAILY_PLAN_MISSING"
    action = "DRAM_DAILY_PLAN_MISSING" if not v176_loaded else consolidated_action(final_decision, corrected_immediate_action, trade_currentness, staleness)
    if not r1c_loaded:
        action = "DRAM_DAILY_DATA_MISSING"
    final_status, decision = final_status_decision(action, refresh_required, blocking)
    warnings = []
    for label, summary in [("V21.174_R1C", r1c_summary), ("V21.176", v176_summary), ("V21.177", v177_summary), ("V21.177_R1A", r1a_summary)]:
        for w in summary.get("warnings", []) if summary else []:
            warnings.append(f"{label}:{w}")

    run_ts = datetime.now(timezone.utc).isoformat()
    row = {
        "run_timestamp": run_ts,
        "ticker": "DRAM",
        "latest_price_date": latest_price_date,
        "latest_plan_date": str(v176_summary.get("latest_dram_date", plan.get("plan_date", ""))) if v176_loaded else "",
        "setup_classification": str(v176_summary.get("setup_classification", plan.get("setup_classification", ""))) if v176_loaded else "",
        "final_trade_decision": final_decision,
        "position_mode": str(v176_summary.get("position_mode", plan.get("position_mode", ""))) if v176_loaded else "",
        "consolidated_action_label": action,
        "corrected_immediate_action_label": corrected_immediate_action,
        "trade_plan_currentness": trade_currentness,
        "staleness_status": staleness,
        "refresh_required": refresh_required,
        "trade_allowed_current": trade_allowed_current,
        "planned_entry_base": v176_summary.get("planned_entry_base", plan.get("planned_entry_base", np.nan)),
        "planned_entry_conservative": plan.get("planned_entry_conservative", np.nan),
        "no_chase_above": v176_summary.get("no_chase_above", plan.get("no_chase_above", np.nan)),
        "stop_loss_base": v176_summary.get("stop_loss_base", plan.get("stop_loss_base", np.nan)),
        "stop_loss_tight": plan.get("stop_loss_tight", np.nan),
        "take_profit_1_base": v176_summary.get("take_profit_1_base", plan.get("take_profit_1_base", np.nan)),
        "take_profit_2_base": plan.get("take_profit_2_base", np.nan),
        "next_required_condition": plan.get("next_required_condition", ""),
        "explanation": "Daily DRAM chain consolidated from R1C, V21.176, V21.177, and repaired staleness semantics.",
        "daily_frequency_only": True,
        "intraday_required": False,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }
    pd.DataFrame([row]).to_csv(out_dir / "dram_daily_chain_final_decision.csv", index=False)
    health.to_csv(out_dir / "dram_daily_chain_health.csv", index=False)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "r1c_loaded": r1c_loaded,
        "v21_176_loaded": v176_loaded,
        "v21_177_loaded": v177_loaded,
        "v21_177_r1a_loaded": r1a_loaded,
        "latest_price_date": latest_price_date,
        "latest_plan_date": row["latest_plan_date"],
        "setup_classification": row["setup_classification"],
        "final_trade_decision": final_decision,
        "consolidated_action_label": action,
        "corrected_immediate_action_label": corrected_immediate_action,
        "trade_plan_currentness": trade_currentness,
        "staleness_status": staleness,
        "refresh_required": refresh_required,
        "trade_allowed_current": trade_allowed_current,
        "planned_entry_base": row["planned_entry_base"],
        "no_chase_above": row["no_chase_above"],
        "stop_loss_base": row["stop_loss_base"],
        "take_profit_1_base": row["take_profit_1_base"],
        "take_profit_2_base": row["take_profit_2_base"],
        "child_stage_warnings": warnings,
        "blocking_issues": blocking,
        **POLICY,
        "created_at_utc": run_ts,
    }
    (out_dir / "V21.178_daily_dram_orchestrator_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, health, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
