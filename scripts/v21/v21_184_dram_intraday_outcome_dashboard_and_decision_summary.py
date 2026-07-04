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


STAGE = "V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY"
DEFAULT_OUT = ROOT / "outputs" / "v21" / STAGE
V183_STAGE = "V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER"
DEFAULT_LEDGER_NAME = "dram_intraday_forward_tracking_ledger_with_outcomes.csv"

REQUIRED_CORE_COLUMNS = ["ticker", "entry", "no_chase", "stop", "forward_status"]
DASHBOARD_COLUMNS = [
    "run_timestamp",
    "source_ledger_path",
    "plan_date",
    "snapshot_time",
    "ticker",
    "entry",
    "no_chase",
    "stop",
    "latest_1m_bar_time",
    "latest_1m_close",
    "forward_status",
    "hit_entry",
    "hit_no_chase",
    "hit_stop",
    "max_favorable_move",
    "max_adverse_move",
    "distance_to_entry_pct",
    "distance_to_no_chase_pct",
    "distance_to_stop_pct",
    "intraday_state_label",
    "decision_summary_label",
    "action_allowed_research_only",
    "official_adoption_allowed",
    "broker_action_allowed",
    "protected_outputs_modified",
]

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "action_allowed_research_only": True,
}

FINAL_PASS = "PASS_V21_184_DRAM_INTRADAY_DASHBOARD_READY"
FINAL_PARTIAL = "PARTIAL_PASS_V21_184_DASHBOARD_READY_WITH_WARNINGS"
FINAL_WARN_NO_ROWS = "WARN_V21_184_NO_VALID_LEDGER_ROWS"
FINAL_FAIL_NOT_FOUND = "FAIL_V21_184_INPUT_LEDGER_NOT_FOUND"
FINAL_FAIL_SCHEMA = "FAIL_V21_184_INPUT_SCHEMA_INVALID"
FINAL_FAIL_EXCEPTION = "FAIL_V21_184_UNHANDLED_EXCEPTION"

DECISION_READY = "DRAM_INTRADAY_DASHBOARD_READY_RESEARCH_ONLY"
DECISION_WAIT = "DRAM_INTRADAY_DASHBOARD_WAIT_FORWARD_DATA_RESEARCH_ONLY"
DECISION_REPAIR = "DRAM_INTRADAY_DASHBOARD_INPUT_REPAIR_REQUIRED"

ALIASES = {
    "snapshot_time": ["snapshot_time", "latest_completed_bar_end", "latest_1m_bar_time"],
    "latest_1m_bar_time": ["latest_1m_bar_time", "latest_completed_bar_end"],
    "latest_1m_close": ["latest_1m_close", "latest_completed_price"],
    "forward_status": ["forward_status", "outcome_status"],
    "final_status": ["final_status", "outcome_status"],
    "hit_no_chase": ["hit_no_chase", "hit_no_chase_after_snapshot"],
    "hit_stop": ["hit_stop", "hit_stop_after_snapshot"],
    "hit_entry": ["hit_entry", "entry_allowed_followthrough_flag"],
    "max_favorable_move": ["max_favorable_move", "mfe_60m", "mfe_30m"],
    "max_adverse_move": ["max_adverse_move", "mae_60m", "mae_30m"],
}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def parse_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def first_present(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def discover_latest_ledger(base_dir: Path = ROOT / "outputs" / "v21") -> Path | None:
    if not base_dir.exists():
        return None
    preferred = [p for p in base_dir.rglob(DEFAULT_LEDGER_NAME) if V183_STAGE in p.as_posix()]
    if preferred:
        return max(preferred, key=lambda p: (p.stat().st_mtime, p.as_posix()))
    fallback = [p for p in base_dir.rglob("*outcomes*.csv") if V183_STAGE in p.as_posix()]
    if not fallback:
        return None
    return max(fallback, key=lambda p: (p.stat().st_mtime, p.as_posix()))


def canonicalize_ledger(raw: pd.DataFrame, strict: bool = False) -> tuple[pd.DataFrame, list[str], list[str]]:
    warnings: list[str] = []
    missing_required: list[str] = []
    out = pd.DataFrame(index=raw.index)

    for column in set(DASHBOARD_COLUMNS + ["final_status", "research_only"]):
        if column in {"run_timestamp", "source_ledger_path", "intraday_state_label", "decision_summary_label"}:
            continue
        aliases = ALIASES.get(column, [column])
        source = first_present(raw, aliases)
        if source is not None:
            out[column] = raw[source]
        else:
            out[column] = np.nan

    for column in REQUIRED_CORE_COLUMNS:
        if out[column].isna().all():
            missing_required.append(column)
    if missing_required and strict:
        return pd.DataFrame(), warnings, missing_required
    if missing_required:
        warnings.append(f"missing required core columns filled with neutral placeholders: {', '.join(missing_required)}")

    for column in ["entry", "no_chase", "stop", "latest_1m_close", "max_favorable_move", "max_adverse_move"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    for column in ["hit_entry", "hit_no_chase", "hit_stop"]:
        out[column] = out[column].map(parse_bool)
    for column in ["ticker", "forward_status", "final_status", "plan_date", "snapshot_time", "latest_1m_bar_time"]:
        out[column] = out[column].astype(object)

    if out["plan_date"].isna().all():
        inferred = pd.to_datetime(out["snapshot_time"], errors="coerce").dt.strftime("%Y-%m-%d")
        if inferred.notna().any():
            out["plan_date"] = inferred
            warnings.append("plan_date missing; inferred from snapshot_time")
        else:
            out["plan_date"] = "NA"
            warnings.append("plan_date missing and could not be inferred")
    if out["snapshot_time"].isna().all():
        inferred_ts = out["latest_1m_bar_time"]
        if inferred_ts.notna().any():
            out["snapshot_time"] = inferred_ts
            warnings.append("snapshot_time missing; inferred from latest_1m_bar_time")
        else:
            out["snapshot_time"] = "NA"
            warnings.append("snapshot_time missing and could not be inferred")

    valid = out.dropna(subset=["entry", "no_chase", "stop"], how="any")
    valid = valid[valid["ticker"].astype(str).str.strip().ne("")]
    valid = valid[valid["forward_status"].astype(str).str.strip().ne("")]
    return valid.reset_index(drop=True), warnings, missing_required


def classify_row(row: pd.Series) -> tuple[str, str]:
    forward_status = str(row.get("forward_status", "")).upper()
    close = row.get("latest_1m_close", np.nan)
    entry = row.get("entry", np.nan)

    if "PENDING" in forward_status:
        return "PENDING_FORWARD_DATA", "WAIT_FOR_FORWARD_DATA"
    if parse_bool(row.get("hit_stop", False)):
        return "STOP_TOUCHED", "STOP_RISK_TRIGGERED_RESEARCH_ONLY"
    if parse_bool(row.get("hit_no_chase", False)):
        return "NO_CHASE_TOUCHED", "NO_CHASE_ZONE_REACHED_DO_NOT_CHASE_RESEARCH_ONLY"
    if parse_bool(row.get("hit_entry", False)):
        return "ENTRY_TOUCHED_ACTIVE", "ENTRY_ZONE_ACTIVE_RESEARCH_ONLY"
    if pd.notna(close) and pd.notna(entry) and float(close) < float(entry):
        return "ENTRY_NOT_REACHED", "WAIT_ENTRY_NOT_TRIGGERED"
    if "COMPLETE" in forward_status:
        return "COMPLETE_OUTCOME_AVAILABLE", "OUTCOME_COMPLETE_REVIEW_ONLY"
    if "FAIL" in forward_status or "INVALID" in forward_status:
        return "FAIL_INPUT_INVALID", "INPUT_INVALID_REPAIR_REQUIRED"
    return "UNKNOWN_STATE", "UNKNOWN_REVIEW_REQUIRED"


def add_dashboard_fields(df: pd.DataFrame, run_timestamp: str, source_path: Path) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    out = df.copy()
    out["run_timestamp"] = run_timestamp
    out["source_ledger_path"] = rel(source_path)
    for denom, dest in [
        ("entry", "distance_to_entry_pct"),
        ("no_chase", "distance_to_no_chase_pct"),
        ("stop", "distance_to_stop_pct"),
    ]:
        out[dest] = np.where(
            out["latest_1m_close"].notna() & out[denom].notna() & (out[denom] != 0),
            (out["latest_1m_close"] / out[denom] - 1.0) * 100.0,
            np.nan,
        )
    if out["latest_1m_close"].isna().any():
        warnings.append("latest_1m_close missing for one or more rows; distance fields left as NaN")

    labels = out.apply(classify_row, axis=1, result_type="expand")
    out["intraday_state_label"] = labels[0] if not labels.empty else "NO_VALID_ROWS"
    out["decision_summary_label"] = labels[1] if not labels.empty else "INPUT_INVALID_REPAIR_REQUIRED"
    out["action_allowed_research_only"] = True
    out["official_adoption_allowed"] = False
    out["broker_action_allowed"] = False
    out["protected_outputs_modified"] = False
    return out.reindex(columns=DASHBOARD_COLUMNS), warnings


def final_status_for(dashboard: pd.DataFrame, warnings: list[str], protected_changed: bool) -> str:
    if dashboard.empty:
        return FINAL_WARN_NO_ROWS
    if warnings or protected_changed:
        return FINAL_PARTIAL
    return FINAL_PASS


def final_decision_for(status: str, latest_state: str) -> str:
    if latest_state == "PENDING_FORWARD_DATA" and not status.startswith("FAIL"):
        return DECISION_WAIT
    if status in {FINAL_PASS, FINAL_PARTIAL}:
        return DECISION_READY
    return DECISION_REPAIR


def build_summary(
    dashboard: pd.DataFrame,
    source_path: Path | None,
    final_status: str,
    warnings: list[str],
) -> dict[str, Any]:
    latest = dashboard.iloc[-1].to_dict() if not dashboard.empty else {}
    statuses = dashboard["forward_status"].astype(str).str.upper() if not dashboard.empty else pd.Series(dtype=str)
    latest_state = str(latest.get("intraday_state_label", "NO_VALID_ROWS"))
    return {
        "final_status": final_status,
        "final_decision": final_decision_for(final_status, latest_state),
        "source_ledger_path": rel(source_path) if source_path else "",
        "row_count": int(len(dashboard)),
        "pending_count": int(statuses.str.contains("PENDING", na=False).sum()),
        "complete_count": int(statuses.str.contains("COMPLETE", na=False).sum()),
        "fail_count": int(statuses.str.contains("FAIL|INVALID", regex=True, na=False).sum()),
        "latest_plan_date": latest.get("plan_date", "NA"),
        "latest_snapshot_time": latest.get("snapshot_time", "NA"),
        "latest_ticker": latest.get("ticker", "NA"),
        "latest_entry": latest.get("entry", np.nan),
        "latest_no_chase": latest.get("no_chase", np.nan),
        "latest_stop": latest.get("stop", np.nan),
        "latest_forward_status": latest.get("forward_status", "NA"),
        "latest_intraday_state_label": latest_state,
        "latest_decision_summary_label": latest.get("decision_summary_label", "INPUT_INVALID_REPAIR_REQUIRED"),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "warnings": warnings,
    }


def write_report(path: Path, summary: dict[str, Any], latest: dict[str, Any]) -> None:
    warnings = summary.get("warnings") or []
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"final_decision: {summary['final_decision']}",
        f"source_ledger_path: {summary['source_ledger_path']}",
        f"latest_plan_date: {summary['latest_plan_date']}",
        f"latest_snapshot_time: {summary['latest_snapshot_time']}",
        f"ticker: {summary['latest_ticker']}",
        f"entry / no-chase / stop: {summary['latest_entry']} / {summary['latest_no_chase']} / {summary['latest_stop']}",
        f"latest_1m_bar_time: {latest.get('latest_1m_bar_time', 'NA')}",
        f"latest_1m_close: {latest.get('latest_1m_close', 'NA')}",
        f"forward_status: {summary['latest_forward_status']}",
        f"intraday_state_label: {summary['latest_intraday_state_label']}",
        f"decision_summary_label: {summary['latest_decision_summary_label']}",
        "",
        "warnings:",
    ]
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- none"])
    lines.extend(
        [
            "",
            "governance:",
            "research_only: true",
            "action_allowed_research_only: true",
            "official_adoption_allowed: false",
            "broker_action_allowed: false",
            "protected_outputs_modified: false",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage(
    input_ledger: Path | None = None,
    output_dir: Path = DEFAULT_OUT,
    asof_ts: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = asof_ts or datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    before = replay.protected_hashes()
    source_path = input_ledger or discover_latest_ledger()
    if source_path is None or not source_path.exists():
        summary = build_summary(pd.DataFrame(columns=DASHBOARD_COLUMNS), source_path, FINAL_FAIL_NOT_FOUND, ["input ledger not found"])
        write_json(output_dir / "v21_184_summary.json", summary)
        write_report(output_dir / "V21.184_dram_intraday_outcome_dashboard_report.txt", summary, {})
        return summary

    raw = read_csv(source_path)
    dashboard = pd.DataFrame(columns=DASHBOARD_COLUMNS)
    if raw.empty:
        warnings.append("input ledger exists but has no rows")
        final_status = FINAL_WARN_NO_ROWS
    else:
        valid, normalize_warnings, missing_required = canonicalize_ledger(raw, strict=strict)
        warnings.extend(normalize_warnings)
        if missing_required and strict:
            final_status = FINAL_FAIL_SCHEMA
            warnings.append(f"strict mode missing required core columns: {', '.join(missing_required)}")
        elif valid.empty:
            final_status = FINAL_WARN_NO_ROWS
            warnings.append("input ledger has no usable rows after normalization")
        else:
            dashboard, dashboard_warnings = add_dashboard_fields(valid, run_timestamp, source_path)
            warnings.extend(dashboard_warnings)
            after = replay.protected_hashes()
            changed = [path for path, digest in before.items() if after.get(path) != digest]
            if changed:
                warnings.append(f"protected output hash changed unexpectedly: {', '.join(changed)}")
            final_status = final_status_for(dashboard, warnings, bool(changed))

    dashboard.to_csv(output_dir / "dram_intraday_outcome_dashboard.csv", index=False)
    latest = dashboard.iloc[-1].to_dict() if not dashboard.empty else {}
    summary = build_summary(dashboard, source_path, final_status, warnings)
    write_json(output_dir / "v21_184_summary.json", summary)
    write_report(output_dir / "V21.184_dram_intraday_outcome_dashboard_report.txt", summary, latest)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--input-ledger", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--asof-ts", default=None)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_stage(args.input_ledger, args.output_dir, args.asof_ts, args.strict)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = build_summary(pd.DataFrame(columns=DASHBOARD_COLUMNS), args.input_ledger, FINAL_FAIL_EXCEPTION, [repr(exc)])
        write_json(output_dir / "v21_184_summary.json", summary)
        write_report(output_dir / "V21.184_dram_intraday_outcome_dashboard_report.txt", summary, {})
    print(json.dumps(summary, indent=2, default=str))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
