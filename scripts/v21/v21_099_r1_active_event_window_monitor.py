#!/usr/bin/env python
"""V21.099-R1 research-only active event-window operational monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay


OUT = Path("outputs/v21")
LEDGER_REL = OUT / "v21_098_r4_top20_forward_policy_observation_ledger.csv"
DASHBOARD_REL = OUT / "v21_098_r6_current_d_top20_event_policy_dashboard.csv"
MATURITY_REL = OUT / "v21_099_r2_policy_checkpoint_maturity_status.csv"
SUMMARY_099_REL = OUT / "v21_099_r6_forward_event_policy_maturity_summary.json"
SUMMARY_098_REL = OUT / "v21_098_r7_event_aware_entry_throttle_overlay_summary.json"
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
REQUIRED_INPUTS = (LEDGER_REL, DASHBOARD_REL, SUMMARY_099_REL, SUMMARY_098_REL, PRICE_REL, D_REL)
IMMUTABLE_INPUTS = (LEDGER_REL, DASHBOARD_REL, MATURITY_REL, SUMMARY_099_REL, SUMMARY_098_REL, D_REL)
OUTPUTS = (
    "v21_099_r1_active_event_window_input_validation.csv",
    "v21_099_r1_active_event_window_input_validation.json",
    "v21_099_r1_active_event_window_calendar.csv",
    "v21_099_r1_current_active_event_watch_dashboard.csv",
    "v21_099_r1_next_maturity_trigger_table.csv",
    "v21_099_r1_active_event_window_monitor_report.md",
    "v21_099_r1_active_event_window_monitor_summary.json",
)
CALENDAR_COLUMNS = [
    "ticker", "rank", "event_type", "event_name", "event_date", "event_time",
    "event_severity", "event_confidence", "days_to_event", "t_minus_5_date",
    "t_minus_3_date", "t_minus_1_date", "t0_date", "t_plus_1_date",
    "t_plus_3_date", "t_plus_5_date", "t_plus_10_date", "t_plus_20_date",
    "nearest_checkpoint_label", "nearest_checkpoint_date",
    "nearest_checkpoint_days", "research_only",
]
WATCH_COLUMNS = [
    "rank", "ticker", "final_score", "event_date", "days_to_event",
    "event_window_state", "event_type", "event_severity", "event_confidence",
    "historical_event_vulnerability_bucket",
    "recommended_research_policy_variant", "entry_throttle_window",
    "exposure_overlay_window", "active_research_observation_flag",
    "official_trade_action_allowed", "official_adoption_allowed", "notes",
]
TRIGGER_COLUMNS = [
    "ticker", "rank", "event_date", "policy_variant", "checkpoint_label",
    "checkpoint_date", "price_required_date", "expected_maturity_date",
    "days_until_maturity", "maturity_status", "rerun_v21_099_after_date",
    "research_only",
]
CHECKPOINT_LABELS = ("T-5", "T-3", "T-1", "T0", "T+1", "T+3", "T+5", "T+10", "T+20")
APPROACHING_STATES = {
    "APPROACHING_T_MINUS_20", "APPROACHING_T_MINUS_10", "APPROACHING_T_MINUS_5",
}
ACTIVE_STATES = {
    "INSIDE_T_MINUS_5_TO_T0", "INSIDE_T0_TO_T_PLUS_3",
    "INSIDE_T_PLUS_3_TO_T_PLUS_20",
}


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8"
    )


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def latest_price_date(root: Path, symbols: set[str]) -> pd.Timestamp:
    latest = pd.NaT
    for chunk in pd.read_csv(
        root / PRICE_REL, usecols=["symbol", "date"], chunksize=250_000, low_memory=False
    ):
        selected = chunk[chunk["symbol"].astype(str).str.upper().isin(symbols)]
        if selected.empty:
            continue
        value = pd.to_datetime(selected["date"], errors="coerce").max()
        if pd.notna(value) and (pd.isna(latest) or value > latest):
            latest = value
    return latest.normalize() if pd.notna(latest) else pd.NaT


def checkpoint_map(group: pd.DataFrame) -> dict[str, pd.Timestamp]:
    result: dict[str, pd.Timestamp] = {}
    for label in CHECKPOINT_LABELS:
        values = pd.to_datetime(
            group.loc[group["checkpoint_label"].eq(label), "checkpoint_date"],
            errors="coerce",
        ).dropna()
        result[label] = values.iloc[0].normalize() if len(values) else pd.NaT
    return result


def event_window_state(run_date: pd.Timestamp, event_date: pd.Timestamp) -> str:
    if pd.isna(event_date):
        return "DATE_INVALID"
    days = int((event_date - run_date).days)
    if days > 20:
        return "OUTSIDE_EVENT_WINDOW"
    if days > 10:
        return "APPROACHING_T_MINUS_20"
    if days > 5:
        return "APPROACHING_T_MINUS_10"
    if days > 0:
        return "APPROACHING_T_MINUS_5"
    if days >= -3:
        return "INSIDE_T0_TO_T_PLUS_3" if days < 0 else "INSIDE_T_MINUS_5_TO_T0"
    if days >= -20:
        return "INSIDE_T_PLUS_3_TO_T_PLUS_20"
    return "POST_EVENT_OBSERVATION_MATURED"


def validate(
    root: Path,
    ledger: pd.DataFrame,
    dashboard: pd.DataFrame,
    ranking: pd.DataFrame,
    summary_098: dict[str, Any],
    summary_099: dict[str, Any],
    d_hash_before: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    top20 = ranking[
        ranking["eligible_for_variant_ranking"].map(truth)
    ].sort_values("final_shadow_rank").head(20)
    expected_binding = set(
        zip(
            top20["ticker"].astype(str),
            pd.to_numeric(top20["final_shadow_rank"], errors="coerce").astype("Int64"),
        )
    )
    dashboard_binding = set(
        zip(
            dashboard["ticker"].astype(str),
            pd.to_numeric(dashboard["rank"], errors="coerce").astype("Int64"),
        )
    )
    checks = [
        ("v21_098_policy_observation_ledger_exists", (root / LEDGER_REL).is_file(), ""),
        ("v21_099_summary_exists", (root / SUMMARY_099_REL).is_file(), ""),
        ("v21_099_final_status_pass", summary_099.get("FINAL_STATUS") == "PASS", str(summary_099.get("FINAL_STATUS", "MISSING"))),
        ("policy_observation_rows_loaded", len(ledger) > 0, str(len(ledger))),
        ("all_policy_rows_research_only", ledger["research_only"].map(truth).all(), ""),
        ("historical_pre_event_random_backtest_blocked", summary_099.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False, ""),
        ("pit_leakage_warnings_zero", int(summary_099.get("PIT_LEAKAGE_WARNINGS", 1)) == 0, ""),
        ("v21_098_status_pass", summary_098.get("FINAL_STATUS") == "PASS", str(summary_098.get("FINAL_STATUS", "MISSING"))),
        ("current_d_top20_binding_matches_dashboard", expected_binding == dashboard_binding and len(expected_binding) == 20, ""),
        ("d_baseline_hash_available", bool(d_hash_before), d_hash_before),
    ]
    rows = pd.DataFrame(checks, columns=["check_name", "passed", "detail"])
    result = {
        "stage": "V21.099-R1_ACTIVE_EVENT_WINDOW_INPUT_VALIDATION",
        "status": "PASS" if rows["passed"].all() else "FAIL",
        "input_v21_098_status": summary_098.get("FINAL_STATUS", "MISSING"),
        "input_v21_099_status": summary_099.get("FINAL_STATUS", "MISSING"),
        "policy_observation_rows_loaded": len(ledger),
        "all_policy_rows_research_only": bool(ledger["research_only"].map(truth).all()),
        "current_d_top20_binding_matches_dashboard": expected_binding == dashboard_binding and len(expected_binding) == 20,
        "historical_pre_event_random_backtest_allowed": False,
        "pit_leakage_warnings": int(summary_099.get("PIT_LEAKAGE_WARNINGS", 0)),
        "research_only": True,
        "official_adoption_allowed": False,
        "d_baseline_sha256_before": d_hash_before,
    }
    return rows, result


def build_calendar(ledger: pd.DataFrame, run_date: pd.Timestamp) -> pd.DataFrame:
    identity = [
        "ticker", "rank", "event_type", "event_name", "event_date", "event_time",
        "event_severity", "event_confidence",
    ]
    rows: list[dict[str, Any]] = []
    for keys, group in ledger.groupby(identity, dropna=False, sort=False):
        base = dict(zip(identity, keys))
        event_date = pd.to_datetime(base["event_date"], errors="coerce")
        checkpoints = checkpoint_map(group)
        future = [
            (label, value) for label, value in checkpoints.items()
            if pd.notna(value) and value >= run_date
        ]
        nearest_label, nearest_date = min(future, key=lambda item: item[1]) if future else ("", pd.NaT)
        rows.append({
            **base,
            "event_date": "" if pd.isna(event_date) else event_date.date().isoformat(),
            "days_to_event": np.nan if pd.isna(event_date) else int((event_date.normalize() - run_date).days),
            "t_minus_5_date": date_text(checkpoints["T-5"]),
            "t_minus_3_date": date_text(checkpoints["T-3"]),
            "t_minus_1_date": date_text(checkpoints["T-1"]),
            "t0_date": date_text(checkpoints["T0"]),
            "t_plus_1_date": date_text(checkpoints["T+1"]),
            "t_plus_3_date": date_text(checkpoints["T+3"]),
            "t_plus_5_date": date_text(checkpoints["T+5"]),
            "t_plus_10_date": date_text(checkpoints["T+10"]),
            "t_plus_20_date": date_text(checkpoints["T+20"]),
            "nearest_checkpoint_label": nearest_label,
            "nearest_checkpoint_date": date_text(nearest_date),
            "nearest_checkpoint_days": np.nan if pd.isna(nearest_date) else int((nearest_date - run_date).days),
            "research_only": True,
        })
    return pd.DataFrame(rows, columns=CALENDAR_COLUMNS).sort_values(["rank", "ticker"])


def date_text(value: pd.Timestamp) -> str:
    return "" if pd.isna(value) else value.date().isoformat()


def build_watch(
    dashboard: pd.DataFrame, calendar: pd.DataFrame, run_date: pd.Timestamp
) -> pd.DataFrame:
    event_names = calendar.set_index("ticker")["event_name"].to_dict()
    rows: list[dict[str, Any]] = []
    for _, row in dashboard.sort_values("rank").iterrows():
        event_date = pd.to_datetime(row["nearest_future_event_date"], errors="coerce")
        state = event_window_state(run_date, event_date)
        active = state in APPROACHING_STATES | ACTIVE_STATES
        rows.append({
            "rank": row["rank"], "ticker": row["ticker"], "final_score": row["final_score"],
            "event_date": date_text(event_date),
            "days_to_event": np.nan if pd.isna(event_date) else int((event_date.normalize() - run_date).days),
            "event_window_state": state, "event_type": row["event_type"],
            "event_severity": row["event_severity"], "event_confidence": row["event_confidence"],
            "historical_event_vulnerability_bucket": row["historical_event_vulnerability_bucket"],
            "recommended_research_policy_variant": row["recommended_research_policy_variant"],
            "entry_throttle_window": row["entry_throttle_window"],
            "exposure_overlay_window": row["exposure_overlay_window"],
            "active_research_observation_flag": active,
            "official_trade_action_allowed": False, "official_adoption_allowed": False,
            "notes": (
                f"Research observation only for {event_names.get(row['ticker'], 'scheduled event')}; "
                "no buy/sell/hold or official trade action."
            ),
        })
    return pd.DataFrame(rows, columns=WATCH_COLUMNS)


def build_triggers(
    ledger: pd.DataFrame,
    maturity: pd.DataFrame | None,
    run_date: pd.Timestamp,
) -> pd.DataFrame:
    status_map = (
        maturity.set_index("policy_observation_id")["checkpoint_maturity_status"].to_dict()
        if maturity is not None and not maturity.empty else {}
    )
    rows: list[dict[str, Any]] = []
    for _, row in ledger.iterrows():
        checkpoint = pd.to_datetime(row["checkpoint_date"], errors="coerce")
        expected = checkpoint + BDay(5) if pd.notna(checkpoint) else pd.NaT
        status = status_map.get(row["policy_observation_id"], str(row.get("checkpoint_maturity_status", "PENDING")))
        rows.append({
            "ticker": row["ticker"], "rank": row["rank"], "event_date": row["event_date"],
            "policy_variant": row["policy_variant"], "checkpoint_label": row["checkpoint_label"],
            "checkpoint_date": date_text(checkpoint), "price_required_date": row["price_required_date"],
            "expected_maturity_date": date_text(expected),
            "days_until_maturity": np.nan if pd.isna(expected) else int((expected.normalize() - run_date).days),
            "maturity_status": status, "rerun_v21_099_after_date": date_text(expected),
            "research_only": True,
        })
    return pd.DataFrame(rows, columns=TRIGGER_COLUMNS).sort_values(
        ["expected_maturity_date", "rank", "policy_variant", "checkpoint_date"]
    )


def report(summary: dict[str, Any], run_date: pd.Timestamp, latest_price: pd.Timestamp) -> str:
    lines = ["# V21.099-R1 Active Event Window Monitor", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        f"- RUN_DATE: `{date_text(run_date)}`",
        f"- LATEST_AVAILABLE_LOCAL_PRICE_DATE: `{date_text(latest_price)}`",
        "",
        "This dashboard schedules forward research observations only. It does not evaluate "
        "policy effectiveness, compute non-matured outcomes, recommend trades, or authorize "
        "official policy adoption.",
        "",
        "Expected maturity dates use the checkpoint plus five business-day targets. Actual "
        "maturity remains subject to observed local price availability and must be confirmed "
        "by rerunning the V21.099 maturity tracker.",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path, run_date: pd.Timestamp) -> dict[str, Any]:
    run_date = run_date.normalize()
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    missing = [path.as_posix() for path in REQUIRED_INPUTS if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))
    immutable_paths = [path for path in IMMUTABLE_INPUTS if (root / path).is_file()]
    immutable_hashes = {path.as_posix(): sha256(root / path) for path in immutable_paths}
    d_hash_before = sha256(root / D_REL)
    before = protected_snapshot(root, output_paths)

    ledger = pd.read_csv(root / LEDGER_REL, low_memory=False)
    dashboard = pd.read_csv(root / DASHBOARD_REL, low_memory=False)
    ranking = pd.read_csv(root / D_REL, low_memory=False)
    maturity = (
        pd.read_csv(root / MATURITY_REL, low_memory=False)
        if (root / MATURITY_REL).is_file() else None
    )
    summary_098 = json.loads((root / SUMMARY_098_REL).read_text(encoding="utf-8"))
    summary_099 = json.loads((root / SUMMARY_099_REL).read_text(encoding="utf-8"))
    validation_rows, validation = validate(
        root, ledger, dashboard, ranking, summary_098, summary_099, d_hash_before
    )
    validation_rows.to_csv(out / OUTPUTS[0], index=False)

    calendar = build_calendar(ledger, run_date)
    calendar.to_csv(out / OUTPUTS[2], index=False)
    watch = build_watch(dashboard, calendar, run_date)
    watch.to_csv(out / OUTPUTS[3], index=False)
    triggers = build_triggers(ledger, maturity, run_date)
    triggers.to_csv(out / OUTPUTS[4], index=False)

    latest_price = latest_price_date(
        root, set(ledger["ticker"].astype(str).str.upper()) | {"QQQ", "SPY"}
    )
    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_hash_after = sha256(root / D_REL)
    d_preserved = d_hash_after == d_hash_before
    inputs_preserved = all(
        sha256(root / Path(path)) == digest for path, digest in immutable_hashes.items()
    )
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    protected_modified = bool(changed or not d_preserved or not inputs_preserved)
    validation.update({
        "latest_available_local_price_date": date_text(latest_price),
        "d_baseline_sha256_after": d_hash_after,
        "d_baseline_preserved": d_preserved,
        "input_ledgers_preserved": inputs_preserved,
    })
    if protected_modified or official_changed:
        validation["status"] = "FAIL"
    write_json(out / OUTPUTS[1], validation)

    active_rows = int(watch["event_window_state"].isin(ACTIVE_STATES).sum())
    approaching_rows = int(watch["event_window_state"].isin(APPROACHING_STATES).sum())
    earliest_event = pd.to_datetime(calendar["event_date"], errors="coerce").min()
    earliest_t5 = pd.to_datetime(calendar["t_minus_5_date"], errors="coerce").min()
    pending_triggers = triggers[~triggers["maturity_status"].eq("MATURED")]
    earliest_maturity = pd.to_datetime(
        pending_triggers["expected_maturity_date"], errors="coerce"
    ).min()
    pit_warnings = int(summary_099.get("PIT_LEAKAGE_WARNINGS", 0))
    if pit_warnings:
        decision = "REJECT_ACTIVE_EVENT_MONITOR_DUE_TO_PIT_LEAKAGE"
    elif protected_modified or official_changed:
        decision = "REJECT_ACTIVE_EVENT_MONITOR_DUE_TO_PROTECTED_MUTATION"
    elif calendar.empty:
        decision = "ACTIVE_EVENT_MONITOR_BLOCKED_NO_FORWARD_EVENTS"
    elif active_rows or approaching_rows:
        decision = "ACTIVE_EVENT_MONITOR_READY_EVENT_WINDOW_APPROACHING"
    else:
        decision = "ACTIVE_EVENT_MONITOR_READY_NO_ACTIVE_WINDOW_YET"
    performance_allowed = int(summary_099.get("MATURED_POLICY_OUTCOME_ROWS", 0)) > 0
    summary = {
        "FINAL_STATUS": (
            "PASS" if validation["status"] == "PASS" and not pit_warnings
            and not protected_modified and not official_changed else "FAIL"
        ),
        "DECISION": decision,
        "INPUT_V21_098_STATUS": summary_098.get("FINAL_STATUS", "MISSING"),
        "INPUT_V21_099_STATUS": summary_099.get("FINAL_STATUS", "MISSING"),
        "TOP20_EVENTS_TRACKED": len(calendar),
        "POLICY_OBSERVATION_ROWS_TRACKED": len(ledger),
        "CURRENT_ACTIVE_EVENT_WINDOW_ROWS": active_rows,
        "CURRENT_APPROACHING_EVENT_ROWS": approaching_rows,
        "EARLIEST_EVENT_DATE": date_text(earliest_event),
        "EARLIEST_T_MINUS_5_DATE": date_text(earliest_t5),
        "EARLIEST_EXPECTED_MATURITY_DATE": date_text(earliest_maturity),
        "DAYS_TO_EARLIEST_EVENT": np.nan if pd.isna(earliest_event) else int((earliest_event - run_date).days),
        "DAYS_TO_EARLIEST_MATURITY": np.nan if pd.isna(earliest_maturity) else int((earliest_maturity - run_date).days),
        "FORWARD_POLICY_OBSERVATION_ALLOWED": True,
        "POLICY_PERFORMANCE_EVALUATION_ALLOWED": performance_allowed,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "RECOMMENDED_NEXT_STAGE": "RERUN_V21_099_ON_OR_AFTER_EARLIEST_EXPECTED_MATURITY_DATE",
    }
    write_json(out / OUTPUTS[6], summary)
    (out / OUTPUTS[5]).write_text(
        report(summary, run_date, latest_price), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--run-date", default=date.today().isoformat())
    args = parser.parse_args()
    run_date = pd.to_datetime(args.run_date, errors="raise")
    summary = run(args.root.resolve(), run_date)
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
