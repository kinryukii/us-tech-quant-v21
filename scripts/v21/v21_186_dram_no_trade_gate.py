from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_179e_dram_intraday_replay_validation as replay


MODULE = "V21.186_DRAM_NO_TRADE_GATE"
V185_STAGE = "V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND"
V184_STAGE = "V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY"
DEFAULT_V185_DIR = ROOT / "outputs" / "v21" / V185_STAGE
DEFAULT_V184_DIR = ROOT / "outputs" / "v21" / V184_STAGE
DEFAULT_PLAN_DIR = ROOT / "outputs" / "v21" / "FULL_SYSTEM_LATEST_RERUN_20260630_152719"
DEFAULT_OUT = ROOT / "outputs" / "v21" / MODULE

V185_LEDGER_NAME = "dram_intraday_trigger_event_ledger.csv"
V185_SUMMARY_NAME = "v21_185_summary.json"
V184_DASHBOARD_NAME = "dram_intraday_outcome_dashboard.csv"
V184_SUMMARY_NAME = "v21_184_summary.json"
PLAN_CSV_NAME = "latest_dram_plan_snapshot.csv"
PLAN_JSON_NAME = "latest_dram_plan_snapshot.json"

LATEST_NAME = "dram_no_trade_gate_latest.csv"
AUDIT_NAME = "dram_no_trade_gate_audit.csv"
SUMMARY_NAME = "v21_186_summary.json"
REPORT_NAME = "V21.186_dram_no_trade_gate_report.txt"

FINAL_PASS = "PASS_V21_186_DRAM_NO_TRADE_GATE_READY"
FINAL_PARTIAL_WAIT = "PARTIAL_PASS_V21_186_DRAM_NO_TRADE_GATE_WAIT_FORWARD_DATA"
FINAL_FAIL_MISSING_LEDGER = "FAIL_V21_186_MISSING_V21_185_LEDGER"
FINAL_FAIL_ERROR = "FAIL_V21_186_NO_TRADE_GATE_ERROR"

DECISION_READY = "DRAM_NO_TRADE_GATE_READY_RESEARCH_ONLY"
DECISION_WAIT = "DRAM_NO_TRADE_GATE_WAIT_FORWARD_DATA_RESEARCH_ONLY"
DECISION_MISSING = "DRAM_NO_TRADE_GATE_BLOCKED_MISSING_INPUT_RESEARCH_ONLY"
DECISION_ERROR = "DRAM_NO_TRADE_GATE_BLOCKED_ERROR_RESEARCH_ONLY"

POLICY = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "protected_outputs_modified": False,
}

ALIASES = {
    "ticker": ["ticker", "symbol", "latest_ticker", "source_ticker"],
    "plan_date": ["plan_date", "latest_plan_date", "latest_price_date_used", "source_plan_date", "source_latest_price_date_used"],
    "trade_plan_currentness": ["trade_plan_currentness", "source_trade_plan_currentness"],
    "trade_allowed_current": ["trade_allowed_current", "source_trade_allowed_current"],
    "entry": ["dram_entry", "entry", "source_entry", "source_dram_entry"],
    "no_chase": ["dram_no_chase", "no_chase", "source_no_chase", "source_dram_no_chase"],
    "stop": ["dram_stop", "stop", "source_stop", "source_dram_stop"],
    "latest_price": ["latest_price", "current_price", "source_latest_1m_close", "latest_1m_close", "source_current_price"],
    "observed_bar_time": ["latest_observed_bar_time", "observed_bar_time", "bar_time", "source_latest_1m_bar_time", "source_snapshot_time"],
    "event_type": ["latest_event_type", "event_type"],
    "event_state_label": ["latest_event_state_label", "event_state_label"],
    "latest_intraday_state_label": ["latest_intraday_state_label", "source_intraday_state_label"],
    "decision_summary_label": ["decision_summary_label", "source_decision_summary_label"],
    "final_decision": ["final_decision", "source_final_decision"],
    "entry_touched": ["entry_touched", "source_hit_entry"],
    "no_chase_touched": ["no_chase_touched", "source_hit_no_chase"],
    "stop_touched": ["stop_touched", "source_hit_stop"],
    "forward_complete": ["forward_complete"],
    "outcome_status": ["outcome_status", "source_forward_status"],
    "structure_broken": ["structure_broken", "trend_structure_broken", "source_structure_broken", "source_trend_structure_broken"],
    "structure_status": ["structure_status", "source_structure_status"],
}

OUTPUT_COLUMNS = [
    "run_timestamp",
    "input_v21_185_ledger_path",
    "input_v21_185_summary_path",
    "input_v21_184_dashboard_path",
    "input_v21_184_summary_path",
    "latest_ticker",
    "latest_plan_date",
    "latest_observed_bar_time",
    "latest_event_type",
    "latest_event_state_label",
    "trade_plan_currentness",
    "latest_price",
    "dram_entry",
    "dram_no_chase",
    "dram_stop",
    "no_trade_gate_label",
    "gate_state",
    "gate_reason",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
    "protected_outputs_modified",
]


def rel(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def first_value(row: pd.Series, names: list[str], default: Any = "NA") -> Any:
    lower = {str(k).strip().lower(): k for k in row.index}
    for name in names:
        col = lower.get(name.lower())
        if col is None:
            continue
        value = row.get(col)
        if pd.notna(value) and str(value).strip() != "":
            return value
    return default


def bool_like(value: Any) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "t"}:
        return True
    if text in {"false", "0", "no", "n", "f"}:
        return False
    return None


def as_float(value: Any) -> float:
    try:
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return float(parsed) if pd.notna(parsed) else np.nan
    except Exception:
        return np.nan


def load_json(path: Path, warnings: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        warnings.append(f"{label} missing")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"{label} unreadable: {exc}")
        return {}


def plan_context(plan_dir: Path, warnings: list[str]) -> dict[str, Any]:
    csv_path = plan_dir / PLAN_CSV_NAME
    json_path = plan_dir / PLAN_JSON_NAME
    if csv_path.exists():
        frame = read_csv(csv_path)
        if not frame.empty:
            return frame.iloc[-1].to_dict()
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError as exc:
            warnings.append(f"daily plan JSON unreadable: {exc}")
            return {}
    warnings.append("daily plan context missing; trade_plan_currentness set to UNKNOWN")
    return {}


def merged_latest_context(event_row: pd.Series, dashboard: pd.DataFrame, plan: dict[str, Any]) -> pd.Series:
    merged: dict[str, Any] = {}
    if not dashboard.empty:
        merged.update({f"dashboard_{k}": v for k, v in dashboard.iloc[-1].to_dict().items()})
        merged.update(dashboard.iloc[-1].to_dict())
    merged.update({f"plan_{k}": v for k, v in plan.items()})
    merged.update(plan)
    merged.update(event_row.to_dict())
    return pd.Series(merged)


def currentness_is_stale(value: Any) -> bool:
    text = str(value).strip().upper()
    return any(token in text for token in ["STALE", "EXPIRED", "MISSING", "NOT_CURRENT"])


def structure_is_broken(row: pd.Series) -> bool:
    broken = bool_like(first_value(row, ALIASES["structure_broken"], None))
    if broken is True:
        return True
    status = str(first_value(row, ALIASES["structure_status"], "")).strip().upper()
    return status in {"BROKEN", "BEARISH", "BREAKDOWN"}


def classify_gate(row: pd.Series) -> tuple[str, str, str]:
    event_type = str(first_value(row, ALIASES["event_type"], "")).strip().upper()
    event_state = str(first_value(row, ALIASES["event_state_label"], "")).strip().upper()
    status_text = " ".join(
        str(first_value(row, ALIASES[key], "")).upper()
        for key in ["latest_intraday_state_label", "decision_summary_label", "final_decision", "outcome_status"]
    )
    trade_currentness = first_value(row, ALIASES["trade_plan_currentness"], "UNKNOWN")
    entry_touched = bool_like(first_value(row, ALIASES["entry_touched"], None))
    no_chase_touched = bool_like(first_value(row, ALIASES["no_chase_touched"], None))
    stop_touched = bool_like(first_value(row, ALIASES["stop_touched"], None))
    forward_complete = bool_like(first_value(row, ALIASES["forward_complete"], None))
    latest_price = as_float(first_value(row, ALIASES["latest_price"], np.nan))
    entry = as_float(first_value(row, ALIASES["entry"], np.nan))
    no_chase = as_float(first_value(row, ALIASES["no_chase"], np.nan))
    stop = as_float(first_value(row, ALIASES["stop"], np.nan))

    if not event_type and not event_state:
        return "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "No usable V21.185 event state was available."
    if "PENDING_FORWARD_DATA" in event_state or "PENDING_FORWARD_DATA" in status_text:
        return "NO_TRADE_PENDING_FORWARD_DATA_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "Forward data is pending; execution permission remains blocked."
    if currentness_is_stale(trade_currentness):
        return "NO_TRADE_STALE_PLAN_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", f"Trade plan currentness is {trade_currentness}."
    if stop_touched is True or (pd.notna(latest_price) and pd.notna(stop) and latest_price < stop):
        return "NO_TRADE_STOP_BREACH_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "Stop was touched or latest price is below stop."
    if no_chase_touched is True or (pd.notna(latest_price) and pd.notna(no_chase) and latest_price > no_chase):
        return "NO_TRADE_NO_CHASE_BREACH_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "No-chase was touched or latest price is above no-chase."
    if structure_is_broken(row):
        return "NO_TRADE_STRUCTURE_BROKEN_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "Source structure status indicates broken or bearish structure."
    if entry_touched is True or event_type == "ENTRY_TOUCH" or event_state == "WAIT_CONFIRMATION":
        return "WAIT_CONFIRMATION_RESEARCH_ONLY", "WAIT_RESEARCH_ONLY", "Entry was touched but confirmation or forward completion is not available."
    plan_current = str(trade_currentness).strip().upper() == "CURRENT"
    if plan_current and pd.notna(latest_price) and pd.notna(no_chase) and pd.notna(stop) and stop < latest_price < no_chase and entry_touched is not True:
        if pd.notna(entry) and latest_price > entry:
            return "ALLOW_PULLBACK_ONLY_RESEARCH_ONLY", "ALLOW_RESEARCH_ONLY", "Price is between entry and no-chase without enough confirmation; pullback-only research gate."
        return "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY", "ALLOW_RESEARCH_ONLY", "Plan is current and latest price is between stop and no-chase without trigger."
    if pd.notna(latest_price) and pd.notna(entry) and pd.notna(no_chase) and entry < latest_price < no_chase:
        return "ALLOW_PULLBACK_ONLY_RESEARCH_ONLY", "ALLOW_RESEARCH_ONLY", "Price is between entry and no-chase; only pullback research observation is allowed."
    return "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY", "BLOCK_RESEARCH_ONLY", "No deterministic no-trade gate rule matched the latest state."


def status_decision_for(label: str, gate_state: str) -> tuple[str, str]:
    if label == "NO_TRADE_PENDING_FORWARD_DATA_RESEARCH_ONLY":
        return FINAL_PARTIAL_WAIT, DECISION_WAIT
    if gate_state == "ALLOW_RESEARCH_ONLY":
        return FINAL_PASS, DECISION_READY
    return FINAL_PASS, DECISION_READY


def gate_record(
    row: pd.Series,
    run_timestamp: str,
    v185_ledger_path: Path,
    v185_summary_path: Path,
    v184_dashboard_path: Path,
    v184_summary_path: Path,
) -> dict[str, Any]:
    label, state, reason = classify_gate(row)
    return {
        "run_timestamp": run_timestamp,
        "input_v21_185_ledger_path": rel(v185_ledger_path),
        "input_v21_185_summary_path": rel(v185_summary_path) if v185_summary_path.exists() else "",
        "input_v21_184_dashboard_path": rel(v184_dashboard_path) if v184_dashboard_path.exists() else "",
        "input_v21_184_summary_path": rel(v184_summary_path) if v184_summary_path.exists() else "",
        "latest_ticker": str(first_value(row, ALIASES["ticker"], "DRAM")).upper().strip() or "DRAM",
        "latest_plan_date": first_value(row, ALIASES["plan_date"], "UNKNOWN"),
        "latest_observed_bar_time": first_value(row, ALIASES["observed_bar_time"], "UNKNOWN"),
        "latest_event_type": first_value(row, ALIASES["event_type"], "UNKNOWN"),
        "latest_event_state_label": first_value(row, ALIASES["event_state_label"], "UNKNOWN"),
        "trade_plan_currentness": first_value(row, ALIASES["trade_plan_currentness"], "UNKNOWN"),
        "latest_price": as_float(first_value(row, ALIASES["latest_price"], np.nan)),
        "dram_entry": as_float(first_value(row, ALIASES["entry"], np.nan)),
        "dram_no_chase": as_float(first_value(row, ALIASES["no_chase"], np.nan)),
        "dram_stop": as_float(first_value(row, ALIASES["stop"], np.nan)),
        "no_trade_gate_label": label,
        "gate_state": state,
        "gate_reason": reason,
        **POLICY,
    }


def build_summary(final_status: str, final_decision: str, record: dict[str, Any], output_dir: Path, warnings: list[str]) -> dict[str, Any]:
    return {
        "module": MODULE,
        "final_status": final_status,
        "final_decision": final_decision,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_v21_185_ledger_path": record.get("input_v21_185_ledger_path", ""),
        "input_v21_185_summary_path": record.get("input_v21_185_summary_path", ""),
        "input_v21_184_dashboard_path": record.get("input_v21_184_dashboard_path", ""),
        "input_v21_184_summary_path": record.get("input_v21_184_summary_path", ""),
        "output_dir": rel(output_dir),
        "latest_ticker": record.get("latest_ticker", "NA"),
        "latest_plan_date": record.get("latest_plan_date", "NA"),
        "latest_observed_bar_time": record.get("latest_observed_bar_time", "NA"),
        "latest_event_type": record.get("latest_event_type", "NA"),
        "latest_event_state_label": record.get("latest_event_state_label", "NA"),
        "trade_plan_currentness": record.get("trade_plan_currentness", "UNKNOWN"),
        "latest_price": record.get("latest_price", np.nan),
        "dram_entry": record.get("dram_entry", np.nan),
        "dram_no_chase": record.get("dram_no_chase", np.nan),
        "dram_stop": record.get("dram_stop", np.nan),
        "no_trade_gate_label": record.get("no_trade_gate_label", "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY"),
        "gate_state": record.get("gate_state", "BLOCK_RESEARCH_ONLY"),
        "gate_reason": record.get("gate_reason", ""),
        "warning_count": int(len(warnings)),
        "warnings": warnings,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    warnings = summary.get("warnings") or []
    lines = [
        MODULE,
        f"final_status = {summary['final_status']}",
        f"final_decision = {summary['final_decision']}",
        f"input_v21_185_ledger_path = {summary['input_v21_185_ledger_path']}",
        f"input_v21_185_summary_path = {summary['input_v21_185_summary_path']}",
        f"input_v21_184_dashboard_path = {summary['input_v21_184_dashboard_path']}",
        f"input_v21_184_summary_path = {summary['input_v21_184_summary_path']}",
        f"output_dir = {summary['output_dir']}",
        f"latest_path = {summary['output_dir']}/{LATEST_NAME}",
        f"audit_path = {summary['output_dir']}/{AUDIT_NAME}",
        f"summary_path = {summary['output_dir']}/{SUMMARY_NAME}",
        f"latest_ticker = {summary['latest_ticker']}",
        f"latest_plan_date = {summary['latest_plan_date']}",
        f"latest_observed_bar_time = {summary['latest_observed_bar_time']}",
        f"latest_event_type = {summary['latest_event_type']}",
        f"latest_event_state_label = {summary['latest_event_state_label']}",
        f"latest_price = {summary['latest_price']}",
        f"dram_entry = {summary['dram_entry']}",
        f"dram_no_chase = {summary['dram_no_chase']}",
        f"dram_stop = {summary['dram_stop']}",
        f"no_trade_gate_label = {summary['no_trade_gate_label']}",
        f"gate_state = {summary['gate_state']}",
        f"gate_reason = {summary['gate_reason']}",
        "",
        "warnings:",
    ]
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- none"])
    lines.extend(
        [
            "",
            "policy:",
            "research_only = true",
            "broker_action_allowed = false",
            "official_adoption_allowed = false",
            "protected_outputs_modified = false",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage(
    v185_dir: Path = DEFAULT_V185_DIR,
    v184_dir: Path = DEFAULT_V184_DIR,
    plan_dir: Path = DEFAULT_PLAN_DIR,
    output_dir: Path = DEFAULT_OUT,
    asof_ts: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = asof_ts or datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    v185_ledger_path = v185_dir / V185_LEDGER_NAME
    v185_summary_path = v185_dir / V185_SUMMARY_NAME
    v184_dashboard_path = v184_dir / V184_DASHBOARD_NAME
    v184_summary_path = v184_dir / V184_SUMMARY_NAME

    before = replay.protected_hashes()
    if not v185_ledger_path.exists():
        record = {
            "input_v21_185_ledger_path": rel(v185_ledger_path),
            "input_v21_185_summary_path": rel(v185_summary_path) if v185_summary_path.exists() else "",
            "input_v21_184_dashboard_path": rel(v184_dashboard_path) if v184_dashboard_path.exists() else "",
            "input_v21_184_summary_path": rel(v184_summary_path) if v184_summary_path.exists() else "",
            "no_trade_gate_label": "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY",
            "gate_state": "BLOCK_RESEARCH_ONLY",
            "gate_reason": "Required V21.185 trigger event ledger is missing.",
        }
        summary = build_summary(FINAL_FAIL_MISSING_LEDGER, DECISION_MISSING, record, output_dir, ["V21.185 trigger event ledger missing"])
        write_json(output_dir / SUMMARY_NAME, summary)
        write_report(output_dir / REPORT_NAME, summary)
        return summary

    load_json(v185_summary_path, warnings, "V21.185 summary JSON")
    load_json(v184_summary_path, warnings, "V21.184 summary JSON")
    ledger = read_csv(v185_ledger_path)
    dashboard = read_csv(v184_dashboard_path)
    if not v184_dashboard_path.exists():
        warnings.append("V21.184 dashboard missing; proceeding in ledger-only mode")
    plan = plan_context(plan_dir, warnings)

    latest_event = ledger.iloc[-1] if not ledger.empty else pd.Series(dtype=object)
    context = merged_latest_context(latest_event, dashboard, plan)
    record = gate_record(context, run_timestamp, v185_ledger_path, v185_summary_path, v184_dashboard_path, v184_summary_path)

    after = replay.protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    if changed:
        warnings.append(f"protected output hash changed unexpectedly: {', '.join(changed)}")

    final_status, final_decision = status_decision_for(record["no_trade_gate_label"], record["gate_state"])
    if changed:
        final_status = FINAL_FAIL_ERROR
        final_decision = DECISION_ERROR
    audit = pd.DataFrame([record]).reindex(columns=OUTPUT_COLUMNS)
    audit.to_csv(output_dir / AUDIT_NAME, index=False)
    audit.tail(1).to_csv(output_dir / LATEST_NAME, index=False)
    summary = build_summary(final_status, final_decision, record, output_dir, warnings)
    write_json(output_dir / SUMMARY_NAME, summary)
    write_report(output_dir / REPORT_NAME, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=MODULE)
    parser.add_argument("--v185-dir", type=Path, default=DEFAULT_V185_DIR)
    parser.add_argument("--v184-dir", type=Path, default=DEFAULT_V184_DIR)
    parser.add_argument("--plan-dir", type=Path, default=DEFAULT_PLAN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--asof-ts", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_stage(args.v185_dir, args.v184_dir, args.plan_dir, args.output_dir, args.asof_ts)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        args.output_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "input_v21_185_ledger_path": rel(args.v185_dir / V185_LEDGER_NAME),
            "input_v21_185_summary_path": rel(args.v185_dir / V185_SUMMARY_NAME),
            "input_v21_184_dashboard_path": rel(args.v184_dir / V184_DASHBOARD_NAME),
            "input_v21_184_summary_path": rel(args.v184_dir / V184_SUMMARY_NAME),
            "no_trade_gate_label": "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY",
            "gate_state": "BLOCK_RESEARCH_ONLY",
            "gate_reason": "Unhandled exception in no-trade gate.",
        }
        summary = build_summary(FINAL_FAIL_ERROR, DECISION_ERROR, record, args.output_dir, [repr(exc)])
        write_json(args.output_dir / SUMMARY_NAME, summary)
        write_report(args.output_dir / REPORT_NAME, summary)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
