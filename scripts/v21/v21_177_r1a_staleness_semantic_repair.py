from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.177_R1A_STALENESS_SEMANTIC_REPAIR"
OUT = ROOT / "outputs" / "v21" / STAGE
SRC = ROOT / "outputs" / "v21" / "V21.177_DAILY_DRAM_PLAN_LEDGER_AND_STALENESS_GATE_R1"
SRC_SUMMARY = SRC / "V21.177_daily_dram_summary.json"
SRC_REVIEW = SRC / "dram_current_plan_review.csv"
SRC_LEDGER = SRC / "dram_daily_plan_ledger.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
    "daily_frequency_only": True,
    "intraday_required": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def boolish(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def action_for_current(final_decision: str, trade_allowed: bool) -> str:
    if trade_allowed and final_decision == "DRAM_TRADE_ALLOWED_LIMIT_ONLY":
        return "LIMIT_PLAN_ALLOWED"
    if "NO_TRADE" in final_decision:
        return "NO_TRADE"
    if "NO_CHASE" in final_decision:
        return "NO_CHASE"
    return "WAIT"


def repair_semantics(
    staleness_status: str,
    original_decision: str,
    original_trade_allowed_current: Any,
    original_immediate_action_label: str,
    final_decision: str,
    trade_allowed_daily_plan: Any = True,
) -> dict[str, Any]:
    stale = str(staleness_status)
    allowed_original = boolish(original_trade_allowed_current)
    plan_allowed = boolish(trade_allowed_daily_plan)
    if stale == "CURRENT_OR_RECENT":
        corrected_allowed = bool(plan_allowed)
        action = action_for_current(str(final_decision), corrected_allowed)
        return {
            "staleness_severity": "NONE",
            "corrected_decision": "DAILY_DRAM_PLAN_LEDGER_ACTIVE",
            "trade_allowed_current_corrected": corrected_allowed,
            "immediate_action_label_corrected": action,
            "refresh_required": False,
            "trade_plan_currentness": "CURRENT",
        }
    if stale == "STALE_WARN":
        if str(original_immediate_action_label) == "LIMIT_PLAN_ALLOWED":
            action = "LIMIT_PLAN_ALLOWED_WITH_STALE_WARNING"
        else:
            action = str(original_immediate_action_label) or action_for_current(str(final_decision), allowed_original)
        return {
            "staleness_severity": "WARN",
            "corrected_decision": "DAILY_DRAM_PLAN_LEDGER_ACTIVE_STALE_WARN",
            "trade_allowed_current_corrected": allowed_original,
            "immediate_action_label_corrected": action,
            "refresh_required": True,
            "trade_plan_currentness": "RECENT_WARN",
        }
    return {
        "staleness_severity": "BLOCK",
        "corrected_decision": "DAILY_DRAM_PLAN_STALE_DO_NOT_USE",
        "trade_allowed_current_corrected": False,
        "immediate_action_label_corrected": "STALE_DO_NOT_USE",
        "refresh_required": True,
        "trade_plan_currentness": "STALE_BLOCKED",
    }


def inconsistency_detected(staleness_status: str, decision: str) -> bool:
    return str(staleness_status) == "STALE_WARN" and str(decision) == "DAILY_DRAM_PLAN_STALE_DO_NOT_USE"


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"original_decision: {summary['original_decision']}",
        f"original_staleness_status: {summary['original_staleness_status']}",
        f"corrected_decision: {summary['corrected_decision']}",
        f"corrected_immediate_action_label: {summary['corrected_immediate_action_label']}",
        f"corrected_trade_allowed_current: {summary['corrected_trade_allowed_current']}",
        f"refresh_required: {summary['refresh_required']}",
        f"trade_plan_currentness: {summary['trade_plan_currentness']}",
        f"semantic_repair_applied: {summary['semantic_repair_applied']}",
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
        "research_only: True",
        "broker_action_allowed: False",
        "official_adoption_allowed: False",
        "canonical_price_panel_modified: False",
    ]
    (out_dir / "V21.177_R1A_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked(out_dir: Path = OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame().to_csv(out_dir / "dram_current_plan_review_REPAIRED.csv", index=False)
    summary = {
        "final_status": "BLOCKED_V21_177_R1A_MISSING_V21_177_OUTPUTS",
        "decision": "STALENESS_SEMANTIC_REPAIR_BLOCKED_MISSING_INPUTS",
        "source_v21_177_loaded": False,
        "original_final_status": "",
        "original_decision": "",
        "original_staleness_status": "",
        "original_trade_allowed_current": False,
        "original_immediate_action_label": "",
        "corrected_decision": "",
        "corrected_trade_allowed_current": False,
        "corrected_immediate_action_label": "",
        "staleness_severity": "",
        "refresh_required": False,
        "trade_plan_currentness": "",
        "semantic_inconsistency_detected": False,
        "semantic_repair_applied": False,
        "warnings": ["WARN_MISSING_V21_177_OUTPUTS"],
        **POLICY,
    }
    (out_dir / "V21.177_R1A_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)


def main(out_dir: Path = OUT, src_summary: Path = SRC_SUMMARY, src_review: Path = SRC_REVIEW, src_ledger: Path = SRC_LEDGER) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_src = read_json(src_summary)
    review = read_csv(src_review)
    ledger = read_csv(src_ledger)
    if not summary_src or review.empty or ledger.empty:
        blocked(out_dir)
        return 0
    review_row = review.iloc[0]
    ledger_row = ledger.tail(1).iloc[0]
    stale = str(summary_src.get("staleness_status", review_row.get("staleness_status", "")))
    original_decision = str(summary_src.get("decision", ""))
    original_allowed = summary_src.get("trade_allowed_current", review_row.get("trade_allowed_current", False))
    original_action = str(summary_src.get("latest_immediate_action_label", review_row.get("immediate_action_label", "")))
    final_decision = str(summary_src.get("latest_final_decision", review_row.get("final_decision", "")))
    repaired = repair_semantics(
        stale,
        original_decision,
        original_allowed,
        original_action,
        final_decision,
        ledger_row.get("trade_allowed_daily_plan", True),
    )
    detected = inconsistency_detected(stale, original_decision)
    repair_applied = detected or repaired["corrected_decision"] != original_decision or repaired["immediate_action_label_corrected"] != original_action
    repaired_review = review.copy()
    for k, v in repaired.items():
        repaired_review[k] = v
    repaired_review["semantic_repair_applied"] = repair_applied
    repaired_review["repair_reason"] = (
        "STALE_WARN_MUST_NOT_USE_DO_NOT_USE_DECISION" if detected else "SEMANTIC_MAPPING_CONFIRMED"
    )
    repaired_review.to_csv(out_dir / "dram_current_plan_review_REPAIRED.csv", index=False)
    final_status = (
        "PASS_V21_177_R1A_STALENESS_SEMANTICS_REPAIRED"
        if repair_applied
        else "WARN_V21_177_R1A_NO_INCONSISTENCY_FOUND"
    )
    decision = "STALENESS_SEMANTIC_REPAIR_READY" if repair_applied else "STALENESS_SEMANTIC_REPAIR_NOT_REQUIRED"
    out = {
        "final_status": final_status,
        "decision": decision,
        "source_v21_177_loaded": True,
        "original_final_status": summary_src.get("final_status", ""),
        "original_decision": original_decision,
        "original_staleness_status": stale,
        "original_trade_allowed_current": boolish(original_allowed),
        "original_immediate_action_label": original_action,
        "corrected_decision": repaired["corrected_decision"],
        "corrected_trade_allowed_current": repaired["trade_allowed_current_corrected"],
        "corrected_immediate_action_label": repaired["immediate_action_label_corrected"],
        "staleness_severity": repaired["staleness_severity"],
        "refresh_required": repaired["refresh_required"],
        "trade_plan_currentness": repaired["trade_plan_currentness"],
        "semantic_inconsistency_detected": detected,
        "semantic_repair_applied": repair_applied,
        "warnings": [],
        **POLICY,
    }
    (out_dir / "V21.177_R1A_summary.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    write_report(out, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
