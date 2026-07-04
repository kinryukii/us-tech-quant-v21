from __future__ import annotations

import argparse
import hashlib
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


MODULE = "V21.185_DRAM_INTRADAY_TRIGGER_EVENT_ARCHIVE_AND_DAILY_APPEND"
V184_STAGE = "V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY"
DEFAULT_V184_DIR = ROOT / "outputs" / "v21" / V184_STAGE
DEFAULT_OUT = ROOT / "outputs" / "v21" / MODULE

DASHBOARD_NAME = "dram_intraday_outcome_dashboard.csv"
SUMMARY_NAME = "v21_184_summary.json"
LEDGER_NAME = "dram_intraday_trigger_event_ledger.csv"
LATEST_NAME = "dram_intraday_trigger_event_latest.csv"
SUMMARY_OUT_NAME = "v21_185_summary.json"
REPORT_NAME = "V21.185_dram_intraday_trigger_event_archive_report.txt"

FINAL_PASS = "PASS_V21_185_DRAM_TRIGGER_EVENT_ARCHIVE_READY"
FINAL_PARTIAL_WAIT = "PARTIAL_PASS_V21_185_DRAM_TRIGGER_EVENT_ARCHIVE_WAIT_FORWARD_DATA"
FINAL_FAIL_MISSING_DASHBOARD = "FAIL_V21_185_MISSING_V21_184_DASHBOARD"
FINAL_FAIL_ERROR = "FAIL_V21_185_TRIGGER_EVENT_ARCHIVE_ERROR"

DECISION_READY = "DRAM_TRIGGER_EVENT_ARCHIVE_READY_RESEARCH_ONLY"
DECISION_WAIT = "DRAM_TRIGGER_EVENT_ARCHIVE_WAIT_FORWARD_DATA_RESEARCH_ONLY"
DECISION_BLOCKED = "DRAM_TRIGGER_EVENT_ARCHIVE_BLOCKED_MISSING_INPUT_RESEARCH_ONLY"

POLICY = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "protected_outputs_modified": False,
}

DEDUP_FIELDS = [
    "source_stage",
    "source_row_hash",
    "ticker",
    "plan_date",
    "observed_bar_time",
    "event_type",
    "event_state_label",
]

BASE_LEDGER_COLUMNS = [
    "archive_run_timestamp",
    "source_stage",
    "source_dashboard_path",
    "source_summary_path",
    "source_row_hash",
    "ticker",
    "plan_date",
    "observed_bar_time",
    "event_type",
    "event_state_label",
    "entry",
    "no_chase",
    "stop",
    "latest_intraday_state_label",
    "decision_summary_label",
    "final_decision",
    "outcome_status",
    "entry_touched",
    "no_chase_touched",
    "stop_touched",
    "forward_complete",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
    "protected_outputs_modified",
]

ALIASES = {
    "ticker": ["ticker", "symbol"],
    "plan_date": ["plan_date", "latest_price_date_used"],
    "observed_bar_time": ["observed_bar_time", "bar_time", "latest_1m_bar_time", "snapshot_time"],
    "entry": ["entry", "dram_entry"],
    "no_chase": ["no_chase", "dram_no_chase"],
    "stop": ["stop", "dram_stop"],
    "latest_intraday_state_label": ["latest_intraday_state_label", "intraday_state_label"],
    "decision_summary_label": ["decision_summary_label"],
    "final_decision": ["final_decision"],
    "entry_touched": ["entry_touched", "hit_entry"],
    "no_chase_touched": ["no_chase_touched", "hit_no_chase"],
    "stop_touched": ["stop_touched", "hit_stop"],
    "forward_complete": ["forward_complete"],
    "outcome_status": ["outcome_status", "forward_status"],
}


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


def row_hash(row: pd.Series) -> str:
    payload = {str(k): "" if pd.isna(v) else str(v) for k, v in sorted(row.to_dict().items(), key=lambda item: str(item[0]))}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def status_text(row: pd.Series) -> str:
    parts = [
        first_value(row, ALIASES["latest_intraday_state_label"], ""),
        first_value(row, ALIASES["outcome_status"], ""),
        first_value(row, ALIASES["decision_summary_label"], ""),
    ]
    return " ".join(str(part).upper() for part in parts if str(part).strip())


def classify_event(row: pd.Series) -> tuple[str, str]:
    text = status_text(row)
    entry_touched = bool_like(first_value(row, ALIASES["entry_touched"], None))
    no_chase_touched = bool_like(first_value(row, ALIASES["no_chase_touched"], None))
    stop_touched = bool_like(first_value(row, ALIASES["stop_touched"], None))
    forward_complete = bool_like(first_value(row, ALIASES["forward_complete"], None))

    if "PENDING_FORWARD_DATA" in text or ("PENDING" in text and "FORWARD" in text):
        return "WAIT_FORWARD_DATA", "PENDING_FORWARD_DATA"
    if forward_complete is True or "COMPLETE" in text:
        return "ENTRY_AND_FORWARD_COMPLETE", "COMPLETE"
    if stop_touched is True or "STOP_TOUCHED" in text:
        return "STOP_TOUCH", "WAIT_CONFIRMATION"
    if no_chase_touched is True or "NO_CHASE_TOUCHED" in text:
        return "NO_CHASE_TOUCH", "WAIT_CONFIRMATION"
    if entry_touched is True or "ENTRY_TOUCHED" in text:
        return "ENTRY_TOUCH", "WAIT_CONFIRMATION"
    if any(flag is False for flag in [entry_touched, no_chase_touched, stop_touched, forward_complete]) or "ENTRY_NOT_REACHED" in text or "NO_TRIGGER" in text:
        return "NO_TRIGGER", "NO_TRIGGER"
    return "UNKNOWN_EVENT_STATE", "UNKNOWN"


def event_from_row(row: pd.Series, dashboard_path: Path, summary_path: Path, run_timestamp: str) -> dict[str, Any]:
    event_type, event_state_label = classify_event(row)
    out = {
        "archive_run_timestamp": run_timestamp,
        "source_stage": V184_STAGE,
        "source_dashboard_path": rel(dashboard_path),
        "source_summary_path": rel(summary_path) if summary_path.exists() else "",
        "source_row_hash": row_hash(row),
        "ticker": str(first_value(row, ALIASES["ticker"], "DRAM")).upper().strip() or "DRAM",
        "plan_date": first_value(row, ALIASES["plan_date"], "NA"),
        "observed_bar_time": first_value(row, ALIASES["observed_bar_time"], "NA"),
        "event_type": event_type,
        "event_state_label": event_state_label,
        "entry": first_value(row, ALIASES["entry"], np.nan),
        "no_chase": first_value(row, ALIASES["no_chase"], np.nan),
        "stop": first_value(row, ALIASES["stop"], np.nan),
        "latest_intraday_state_label": first_value(row, ALIASES["latest_intraday_state_label"], "NA"),
        "decision_summary_label": first_value(row, ALIASES["decision_summary_label"], "NA"),
        "final_decision": first_value(row, ALIASES["final_decision"], "NA"),
        "outcome_status": first_value(row, ALIASES["outcome_status"], "NA"),
        "entry_touched": bool_like(first_value(row, ALIASES["entry_touched"], None)),
        "no_chase_touched": bool_like(first_value(row, ALIASES["no_chase_touched"], None)),
        "stop_touched": bool_like(first_value(row, ALIASES["stop_touched"], None)),
        "forward_complete": bool_like(first_value(row, ALIASES["forward_complete"], None)),
        **POLICY,
    }
    for col, value in row.to_dict().items():
        key = f"source_{col}"
        if key not in out:
            out[key] = value
    return out


def build_events(dashboard: pd.DataFrame, dashboard_path: Path, summary_path: Path, run_timestamp: str) -> pd.DataFrame:
    rows = [event_from_row(row, dashboard_path, summary_path, run_timestamp) for _, row in dashboard.iterrows()]
    if not rows:
        return pd.DataFrame(columns=BASE_LEDGER_COLUMNS)
    out = pd.DataFrame(rows)
    front = [col for col in BASE_LEDGER_COLUMNS if col in out.columns]
    rest = [col for col in out.columns if col not in front]
    return out[front + rest]


def load_summary(path: Path, warnings: list[str]) -> dict[str, Any]:
    if not path.exists():
        warnings.append("V21.184 summary JSON missing; proceeding from dashboard CSV only")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"V21.184 summary JSON unreadable; proceeding from dashboard CSV only: {exc}")
        return {}


def append_and_dedup(existing: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    combined = pd.concat([existing, candidates], ignore_index=True, sort=False)
    before = len(combined)
    for field in DEDUP_FIELDS:
        if field not in combined.columns:
            combined[field] = "NA"
    combined = combined.drop_duplicates(subset=DEDUP_FIELDS, keep="first").reset_index(drop=True)
    return combined, before - len(combined)


def final_status_and_decision(latest_event_type: str, fail: bool = False) -> tuple[str, str]:
    if fail:
        return FINAL_FAIL_MISSING_DASHBOARD, DECISION_BLOCKED
    if latest_event_type == "WAIT_FORWARD_DATA":
        return FINAL_PARTIAL_WAIT, DECISION_WAIT
    return FINAL_PASS, DECISION_READY


def build_summary(
    final_status: str,
    final_decision: str,
    dashboard_path: Path | None,
    input_summary_path: Path | None,
    output_dir: Path,
    previous_rows: int,
    candidate_rows: int,
    appended_rows: int,
    final_rows: int,
    duplicates_removed: int,
    latest: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "module": MODULE,
        "final_status": final_status,
        "final_decision": final_decision,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "protected_outputs_modified": False,
        "input_dashboard_path": rel(dashboard_path),
        "input_summary_path": rel(input_summary_path) if input_summary_path and input_summary_path.exists() else "",
        "output_dir": rel(output_dir),
        "previous_ledger_rows": int(previous_rows),
        "new_candidate_event_rows": int(candidate_rows),
        "appended_event_rows": int(appended_rows),
        "final_ledger_rows": int(final_rows),
        "duplicate_rows_removed": int(duplicates_removed),
        "latest_event_type": latest.get("event_type", "NA"),
        "latest_event_state_label": latest.get("event_state_label", "NA"),
        "latest_plan_date": latest.get("plan_date", "NA"),
        "latest_observed_bar_time": latest.get("observed_bar_time", "NA"),
        "warning_count": int(len(warnings)),
        "warnings": warnings,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    warnings = summary.get("warnings") or []
    lines = [
        MODULE,
        f"final_status = {summary['final_status']}",
        f"final_decision = {summary['final_decision']}",
        f"input_dashboard_path = {summary['input_dashboard_path']}",
        f"input_summary_path = {summary['input_summary_path']}",
        f"output_dir = {summary['output_dir']}",
        f"ledger_path = {summary['output_dir']}/{LEDGER_NAME}",
        f"latest_path = {summary['output_dir']}/{LATEST_NAME}",
        f"summary_path = {summary['output_dir']}/{SUMMARY_OUT_NAME}",
        f"previous_ledger_rows = {summary['previous_ledger_rows']}",
        f"appended_event_rows = {summary['appended_event_rows']}",
        f"final_ledger_rows = {summary['final_ledger_rows']}",
        f"latest_event_type = {summary['latest_event_type']}",
        f"latest_event_state_label = {summary['latest_event_state_label']}",
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
    input_dir: Path = DEFAULT_V184_DIR,
    output_dir: Path = DEFAULT_OUT,
    input_dashboard: Path | None = None,
    input_summary: Path | None = None,
    asof_ts: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = asof_ts or datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    dashboard_path = input_dashboard or input_dir / DASHBOARD_NAME
    summary_path = input_summary or input_dir / SUMMARY_NAME
    ledger_path = output_dir / LEDGER_NAME
    latest_path = output_dir / LATEST_NAME
    summary_out_path = output_dir / SUMMARY_OUT_NAME
    report_path = output_dir / REPORT_NAME

    before = replay.protected_hashes()
    if not dashboard_path.exists():
        final_status, final_decision = final_status_and_decision("NA", fail=True)
        summary = build_summary(final_status, final_decision, dashboard_path, summary_path, output_dir, 0, 0, 0, 0, 0, {}, ["V21.184 dashboard CSV missing"])
        write_json(summary_out_path, summary)
        write_report(report_path, summary)
        return summary

    load_summary(summary_path, warnings)
    dashboard = read_csv(dashboard_path)
    existing = read_csv(ledger_path)
    previous_rows = len(existing)
    candidates = build_events(dashboard, dashboard_path, summary_path, run_timestamp)
    final_ledger, duplicates_removed = append_and_dedup(existing, candidates)

    final_ledger.to_csv(ledger_path, index=False)
    latest = final_ledger.iloc[-1].to_dict() if not final_ledger.empty else {}
    latest_frame = final_ledger.tail(1).copy() if not final_ledger.empty else pd.DataFrame(columns=final_ledger.columns)
    latest_frame.to_csv(latest_path, index=False)

    after = replay.protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    if changed:
        warnings.append(f"protected output hash changed unexpectedly: {', '.join(changed)}")

    appended_rows = len(final_ledger) - previous_rows
    final_status, final_decision = final_status_and_decision(str(latest.get("event_type", "NA")))
    if changed:
        final_status = FINAL_FAIL_ERROR
        final_decision = DECISION_BLOCKED

    summary = build_summary(
        final_status,
        final_decision,
        dashboard_path,
        summary_path,
        output_dir,
        previous_rows,
        len(candidates),
        appended_rows,
        len(final_ledger),
        duplicates_removed,
        latest,
        warnings,
    )
    write_json(summary_out_path, summary)
    write_report(report_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=MODULE)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_V184_DIR)
    parser.add_argument("--input-dashboard", type=Path, default=None)
    parser.add_argument("--input-summary", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--asof-ts", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_stage(args.input_dir, args.output_dir, args.input_dashboard, args.input_summary, args.asof_ts)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        args.output_dir.mkdir(parents=True, exist_ok=True)
        summary = build_summary(
            FINAL_FAIL_ERROR,
            DECISION_BLOCKED,
            args.input_dashboard or args.input_dir / DASHBOARD_NAME,
            args.input_summary or args.input_dir / SUMMARY_NAME,
            args.output_dir,
            0,
            0,
            0,
            0,
            0,
            {},
            [repr(exc)],
        )
        write_json(args.output_dir / SUMMARY_OUT_NAME, summary)
        write_report(args.output_dir / REPORT_NAME, summary)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
