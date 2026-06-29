from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from pandas.errors import EmptyDataError


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.178_R1A_DAILY_DRAM_CHAIN_EXECUTION_MODE"
OUT = ROOT / "outputs" / "v21" / STAGE
V178 = ROOT / "outputs" / "v21" / "V21.178_DAILY_DRAM_PLAN_CHAIN_ORCHESTRATOR_R1"
R1C = ROOT / "outputs" / "v21" / "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
V176 = ROOT / "outputs" / "v21" / "V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1"
V177 = ROOT / "outputs" / "v21" / "V21.177_DAILY_DRAM_PLAN_LEDGER_AND_STALENESS_GATE_R1"
R1A = ROOT / "outputs" / "v21" / "V21.177_R1A_STALENESS_SEMANTIC_REPAIR"

CHILDREN = [
    ("V21.174_R1C", "scripts/v21/run_v21_174_r1c_auto_dram_price_fetch_and_cache.ps1"),
    ("V21.176", "scripts/v21/run_v21_176_daily_dram_premarket_trade_plan_r1.ps1"),
    ("V21.177", "scripts/v21/run_v21_177_daily_dram_plan_ledger_and_staleness_gate_r1.ps1"),
    ("V21.177_R1A", "scripts/v21/run_v21_177_r1a_staleness_semantic_repair.ps1"),
    ("V21.178", "scripts/v21/run_v21_178_daily_dram_plan_chain_orchestrator_r1.ps1"),
]

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


def tail_text(text: str, n: int = 3000) -> str:
    if not text:
        return ""
    return text[-n:].replace("\r", "")


def run_child(stage: str, script: str, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script]
    try:
        proc = runner(cmd, cwd=ROOT, text=True, capture_output=True, timeout=300, check=False)
        code = int(getattr(proc, "returncode", 1))
        stdout = getattr(proc, "stdout", "")
        stderr = getattr(proc, "stderr", "")
        return {
            "stage": stage,
            "command": " ".join(cmd),
            "attempted": True,
            "success": code == 0,
            "return_code": code,
            "stdout_tail": tail_text(stdout),
            "stderr_tail": tail_text(stderr),
            "blocking_issue": code != 0,
            "notes": "" if code == 0 else "CHILD_STAGE_FAILED_CAPTURED",
        }
    except Exception as exc:
        return {
            "stage": stage,
            "command": " ".join(cmd),
            "attempted": True,
            "success": False,
            "return_code": -1,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}:{exc}",
            "blocking_issue": True,
            "notes": "CHILD_STAGE_EXCEPTION_CAPTURED",
        }


def latest_dates() -> dict[str, str]:
    summary = read_json(V178 / "V21.178_daily_dram_orchestrator_summary.json")
    return {
        "latest_price_date": str(summary.get("latest_price_date", "")),
        "latest_plan_date": str(summary.get("latest_plan_date", "")),
    }


def compare_freshness(before: dict[str, str], after: dict[str, str]) -> pd.DataFrame:
    rows = []
    for field in ["latest_price_date", "latest_plan_date"]:
        b = before.get(field, "")
        a = after.get(field, "")
        rows.append(
            {
                "field": field,
                "before_value": b,
                "after_value": a,
                "changed": b != a,
                "notes": "updated" if b != a else "unchanged",
            }
        )
    return pd.DataFrame(rows)


def load_refreshed_outputs() -> dict[str, Any]:
    return {
        "r1c_summary": read_json(R1C / "V21.174_R1C_summary.json"),
        "v176_summary": read_json(V176 / "V21.176_daily_dram_summary.json"),
        "v177_summary": read_json(V177 / "V21.177_daily_dram_summary.json"),
        "r1a_summary": read_json(R1A / "V21.177_R1A_summary.json"),
        "v178_summary": read_json(V178 / "V21.178_daily_dram_orchestrator_summary.json"),
        "v178_final": read_csv(V178 / "dram_daily_chain_final_decision.csv"),
    }


def final_copy(final_df: pd.DataFrame, all_success: bool, comparison: pd.DataFrame) -> pd.DataFrame:
    if final_df.empty:
        return pd.DataFrame()
    out = final_df.copy()
    out["execution_mode"] = True
    out["child_chain_executed"] = True
    out["all_required_children_success"] = all_success
    out["refresh_attempted"] = True
    improved = {r["field"]: bool(r["changed"]) for _, r in comparison.iterrows()}
    out["refresh_improved_latest_price_date"] = improved.get("latest_price_date", False)
    out["refresh_improved_latest_plan_date"] = improved.get("latest_plan_date", False)
    return out


def status_decision(all_success: bool, final_loaded: bool, final_summary: dict[str, Any]) -> tuple[str, str]:
    if not final_loaded:
        return "BLOCKED_V21_178_R1A_FINAL_DECISION_MISSING", "DAILY_DRAM_EXECUTION_CHAIN_BLOCKED_NO_FINAL_DECISION"
    if not all_success:
        return "WARN_V21_178_R1A_CHILD_STAGE_FAILED", "DAILY_DRAM_EXECUTION_CHAIN_WARN_CHILD_FAILURE"
    action = str(final_summary.get("consolidated_action_label", ""))
    refresh = bool(final_summary.get("refresh_required", False))
    if refresh or action == "DRAM_DAILY_LIMIT_PLAN_ACTIVE_STALE_WARN":
        return "PARTIAL_PASS_V21_178_R1A_EXECUTION_CHAIN_READY_STALE_WARN", "DAILY_DRAM_EXECUTION_CHAIN_READY_REFRESH_STILL_RECOMMENDED"
    return "PASS_V21_178_R1A_EXECUTION_CHAIN_READY", "DAILY_DRAM_EXECUTION_CHAIN_READY"


def write_report(summary: dict[str, Any], audit: pd.DataFrame, out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"child stages attempted/succeeded: {len(audit)} / {int(audit['success'].sum()) if not audit.empty else 0}",
        f"before/after latest_price_date: {summary['before_latest_price_date']} / {summary['after_latest_price_date']}",
        f"before/after latest_plan_date: {summary['before_latest_plan_date']} / {summary['after_latest_plan_date']}",
        f"final_consolidated_action_label: {summary['final_consolidated_action_label']}",
        f"final_trade_plan_currentness: {summary['final_trade_plan_currentness']}",
        f"final_staleness_status: {summary['final_staleness_status']}",
        f"final_refresh_required: {summary['final_refresh_required']}",
        f"final_trade_allowed_current: {summary['final_trade_allowed_current']}",
        f"planned/no_chase/stop/tp1/tp2: {summary['planned_entry_base']} / {summary['no_chase_above']} / {summary['stop_loss_base']} / {summary['take_profit_1_base']} / {summary['take_profit_2_base']}",
        "failed_child_stages:",
        *([f"- {s}" for s in summary["failed_child_stages"]] if summary["failed_child_stages"] else ["- none"]),
        "blocking_issues:",
        *([f"- {b}" for b in summary["blocking_issues"]] if summary["blocking_issues"] else ["- none"]),
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
    ]
    (out_dir / "V21.178_R1A_execution_mode_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(out_dir: Path = OUT, runner: Callable[..., Any] = subprocess.run) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = latest_dates()
    audit_rows = [run_child(stage, script, runner) for stage, script in CHILDREN]
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(out_dir / "dram_daily_chain_execution_audit.csv", index=False)
    after = latest_dates()
    comparison = compare_freshness(before, after)
    comparison.to_csv(out_dir / "dram_daily_chain_refresh_comparison.csv", index=False)
    outputs = load_refreshed_outputs()
    final_df = outputs["v178_final"]
    all_success = bool(not audit.empty and audit["success"].all())
    copied = final_copy(final_df, all_success, comparison)
    copied.to_csv(out_dir / "dram_daily_chain_final_decision_EXECUTION_MODE.csv", index=False)
    final_summary = outputs["v178_summary"]
    final_loaded = bool(final_summary) and not final_df.empty
    final_status, decision = status_decision(all_success, final_loaded, final_summary)
    failed = audit.loc[~audit["success"], "stage"].astype(str).tolist() if not audit.empty else []
    blocking = []
    if not final_loaded:
        blocking.append("FINAL_DECISION_MISSING_AFTER_EXECUTION")
    warnings = [f"CHILD_STAGE_FAILED:{s}" for s in failed]
    row = copied.iloc[0].to_dict() if not copied.empty else {}
    summary = {
        "final_status": final_status,
        "decision": decision,
        "child_chain_executed": True,
        "all_required_children_success": all_success,
        "failed_child_stages": failed,
        "refresh_attempted": True,
        "before_latest_price_date": before.get("latest_price_date", ""),
        "after_latest_price_date": after.get("latest_price_date", ""),
        "before_latest_plan_date": before.get("latest_plan_date", ""),
        "after_latest_plan_date": after.get("latest_plan_date", ""),
        "refresh_improved_latest_price_date": bool(comparison.loc[comparison["field"].eq("latest_price_date"), "changed"].iloc[0]),
        "refresh_improved_latest_plan_date": bool(comparison.loc[comparison["field"].eq("latest_plan_date"), "changed"].iloc[0]),
        "final_consolidated_action_label": final_summary.get("consolidated_action_label", row.get("consolidated_action_label", "")),
        "final_trade_plan_currentness": final_summary.get("trade_plan_currentness", row.get("trade_plan_currentness", "")),
        "final_staleness_status": final_summary.get("staleness_status", row.get("staleness_status", "")),
        "final_refresh_required": bool(final_summary.get("refresh_required", row.get("refresh_required", False))),
        "final_trade_allowed_current": bool(final_summary.get("trade_allowed_current", row.get("trade_allowed_current", False))),
        "planned_entry_base": final_summary.get("planned_entry_base", row.get("planned_entry_base", "")),
        "no_chase_above": final_summary.get("no_chase_above", row.get("no_chase_above", "")),
        "stop_loss_base": final_summary.get("stop_loss_base", row.get("stop_loss_base", "")),
        "take_profit_1_base": final_summary.get("take_profit_1_base", row.get("take_profit_1_base", "")),
        "take_profit_2_base": final_summary.get("take_profit_2_base", row.get("take_profit_2_base", "")),
        "warnings": warnings,
        "blocking_issues": blocking,
        **POLICY,
    }
    (out_dir / "V21.178_R1A_execution_mode_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, audit, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
