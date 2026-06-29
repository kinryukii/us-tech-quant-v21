#!/usr/bin/env python
"""V21.098 event-aware entry throttle and exposure overlay research."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay


OUT = Path("outputs/v21")
RETURNS_REL = Path("outputs/v21/v21_097_r2_historical_event_occurrence_return_rows.csv")
IMPACT_REL = Path("outputs/v21/v21_097_r3_event_type_impact_summary.csv")
SCHEDULE_REL = Path("outputs/v21/v21_097_r5_top20_forward_event_observation_schedule.csv")
DASHBOARD_REL = Path("outputs/v21/v21_097_r6_current_d_event_risk_dashboard.csv")
SUMMARY_REL = Path("outputs/v21/v21_097_r7_event_occurrence_and_forward_observation_summary.json")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
INPUTS = (RETURNS_REL, IMPACT_REL, SCHEDULE_REL, DASHBOARD_REL, SUMMARY_REL)
OUTPUTS = (
    "v21_098_r1_input_validation.csv",
    "v21_098_r1_input_validation.json",
    "v21_098_r2_event_vulnerability_policy_buckets.csv",
    "v21_098_r3_event_policy_variants.csv",
    "v21_098_r4_top20_forward_policy_observation_ledger.csv",
    "v21_098_r5_historical_support_diagnostic_summary.csv",
    "v21_098_r6_current_d_top20_event_policy_dashboard.csv",
    "v21_098_r7_event_aware_entry_throttle_overlay_report.md",
    "v21_098_r7_event_aware_entry_throttle_overlay_summary.json",
)

VARIANTS = (
    {
        "policy_variant": "EVENT_WATCH_ONLY", "policy_family": "WATCH",
        "entry_start": np.nan, "entry_end": np.nan,
        "overlay_start": np.nan, "overlay_end": np.nan,
        "exposure_multiplier": 1.0,
        "rule": "Observation only; no action.",
    },
    {
        "policy_variant": "EVENT_ENTRY_THROTTLE_LIGHT", "policy_family": "ENTRY",
        "entry_start": -1, "entry_end": 0,
        "overlay_start": np.nan, "overlay_end": np.nan,
        "exposure_multiplier": 1.0,
        "rule": "Block new entry T-1 through T0 for high-severity/high-vulnerability candidates.",
    },
    {
        "policy_variant": "EVENT_ENTRY_THROTTLE_MEDIUM", "policy_family": "ENTRY",
        "entry_start": -3, "entry_end": 1,
        "overlay_start": np.nan, "overlay_end": np.nan,
        "exposure_multiplier": 1.0,
        "rule": "Block new entry T-3 through T+1.",
    },
    {
        "policy_variant": "EVENT_ENTRY_THROTTLE_HEAVY", "policy_family": "ENTRY",
        "entry_start": -5, "entry_end": 1,
        "overlay_start": np.nan, "overlay_end": np.nan,
        "exposure_multiplier": 1.0,
        "rule": "Block new entry T-5 through T+1.",
    },
    {
        "policy_variant": "EVENT_EXPOSURE_OVERLAY_LIGHT", "policy_family": "OVERLAY",
        "entry_start": np.nan, "entry_end": np.nan,
        "overlay_start": -1, "overlay_end": 1,
        "exposure_multiplier": .75,
        "rule": "Scale exposure to 0.75 during T-1 through T+1.",
    },
    {
        "policy_variant": "EVENT_EXPOSURE_OVERLAY_MEDIUM", "policy_family": "OVERLAY",
        "entry_start": np.nan, "entry_end": np.nan,
        "overlay_start": -3, "overlay_end": 1,
        "exposure_multiplier": .50,
        "rule": "Scale exposure to 0.50 during T-3 through T+1.",
    },
    {
        "policy_variant": "EVENT_EXPOSURE_OVERLAY_HEAVY", "policy_family": "OVERLAY",
        "entry_start": np.nan, "entry_end": np.nan,
        "overlay_start": -5, "overlay_end": 3,
        "exposure_multiplier": .25,
        "rule": "Scale exposure to 0.25 during T-5 through T+3.",
    },
    {
        "policy_variant": "EVENT_COMBINED_LIGHT", "policy_family": "COMBINED",
        "entry_start": -1, "entry_end": 0,
        "overlay_start": -1, "overlay_end": 1,
        "exposure_multiplier": .75,
        "rule": "Light entry throttle plus 0.75 exposure overlay.",
    },
    {
        "policy_variant": "EVENT_COMBINED_MEDIUM", "policy_family": "COMBINED",
        "entry_start": -3, "entry_end": 1,
        "overlay_start": -3, "overlay_end": 1,
        "exposure_multiplier": .50,
        "rule": "Medium entry throttle plus 0.50 exposure overlay.",
    },
    {
        "policy_variant": "EVENT_COMBINED_HEAVY", "policy_family": "COMBINED",
        "entry_start": -5, "entry_end": 1,
        "overlay_start": -5, "overlay_end": 3,
        "exposure_multiplier": .25,
        "rule": "Heavy entry throttle plus 0.25 exposure overlay.",
    },
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in payload.items())
    lines.extend([
        "",
        "These policy variants are diagnostic forward-observation schedules only. Historical "
        "event-occurrence returns are supporting evidence, not pre-event tradability evidence.",
    ])
    return "\n".join(lines) + "\n"


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def validate_inputs(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    requirements = {
        RETURNS_REL: {
            "event_id", "ticker", "event_type", "return_5d", "return_10d",
            "price_missing_flag", "research_only",
        },
        IMPACT_REL: {
            "event_type", "window", "usable_event_count", "cvar_5",
            "severe_loss_count", "research_only",
        },
        SCHEDULE_REL: {
            "observation_id", "ticker", "rank", "event_type", "event_date",
            "checkpoint_label", "checkpoint_date", "checkpoint_maturity_status",
        },
        DASHBOARD_REL: {
            "rank", "ticker", "final_score", "historical_event_count",
            "historical_event_vulnerability_score",
            "historical_event_vulnerability_bucket",
            "future_event_count_next_180d", "nearest_future_event_date",
        },
    }
    rows = []
    all_pass = True
    for rel, required in requirements.items():
        path = root / rel
        exists = path.is_file()
        columns = set(pd.read_csv(path, nrows=0).columns) if exists else set()
        missing = sorted(required - columns)
        status = "PASS" if exists and not missing else "FAIL"
        all_pass &= status == "PASS"
        rows.append({
            "source_path": rel.as_posix(), "exists": exists,
            "required_columns_exist": not missing,
            "missing_columns": "|".join(missing), "status": status,
            "research_only": True,
        })
    summary_path = root / SUMMARY_REL
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    checks = {
        "summary_exists": summary_path.is_file(),
        "v21_097_final_status_pass": summary.get("FINAL_STATUS") == "PASS",
        "historical_pre_event_random_backtest_blocked": summary.get(
            "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED"
        ) is False,
        "forward_event_observation_allowed": summary.get(
            "FORWARD_EVENT_OBSERVATION_ALLOWED"
        ) is True,
        "pit_leakage_warnings": int(summary.get("PIT_LEAKAGE_WARNINGS", 999)),
    }
    all_pass &= (
        checks["summary_exists"] and checks["v21_097_final_status_pass"]
        and checks["historical_pre_event_random_backtest_blocked"]
        and checks["forward_event_observation_allowed"]
        and checks["pit_leakage_warnings"] == 0
    )
    result = {
        "stage": "V21.098-R1_INPUT_VALIDATION",
        "status": "PASS" if all_pass else "FAIL",
        "input_v21_097_status": summary.get("FINAL_STATUS", "MISSING"),
        **checks, "research_only": True, "official_adoption_allowed": False,
    }
    return pd.DataFrame(rows), result


def historical_ticker_stats(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, group in returns.groupby("ticker"):
        severe = int(
            group["return_5d"].le(-.10).sum()
            + group["return_10d"].le(-.10).sum()
        )
        rows.append({
            "ticker": ticker, "historical_severe_loss_count": severe,
            "historical_worst_5d_return": group["return_5d"].min(),
            "historical_worst_10d_return": group["return_10d"].min(),
        })
    return pd.DataFrame(rows)


def build_buckets(
    dashboard: pd.DataFrame, schedule: pd.DataFrame, ticker_stats: pd.DataFrame,
) -> pd.DataFrame:
    confidence = (
        schedule.sort_values(["ticker", "event_date"])
        .drop_duplicates("ticker")[["ticker", "event_confidence"]]
    )
    frame = dashboard.merge(ticker_stats, on="ticker", how="left").merge(
        confidence, on="ticker", how="left"
    )
    rows = []
    for _, row in frame.iterrows():
        has_future = int(row["future_event_count_next_180d"]) > 0
        high_vulnerability = str(row["historical_event_vulnerability_bucket"]).upper() == "HIGH"
        score = pd.to_numeric(row["historical_event_vulnerability_score"], errors="coerce")
        severe_value = pd.to_numeric(
            row.get("historical_severe_loss_count", 0), errors="coerce"
        )
        severe = 0 if pd.isna(severe_value) else int(severe_value)
        severity = str(row.get("future_event_severity", "")).upper()
        confidence_value = str(row.get("event_confidence", "")).upper()
        data_sufficient = pd.notna(score) and int(row["historical_event_count"]) > 0
        entry = bool(
            has_future and high_vulnerability
            and severity in {"HIGH", "CRITICAL", "SEVERE"}
        )
        overlay = bool(
            has_future and data_sufficient
            and (score >= 40 or severe > 0)
        )
        if not data_sufficient:
            bucket = "DATA_INSUFFICIENT"
            reason = "Historical occurrence vulnerability is unavailable."
        elif entry and overlay:
            bucket = "ENTRY_THROTTLE_AND_OVERLAY_CANDIDATE"
            reason = "High vulnerability and high-severity forward event."
        elif entry:
            bucket = "ENTRY_THROTTLE_CANDIDATE"
            reason = "High-severity forward event on a high-vulnerability ticker."
        elif overlay:
            bucket = "EXPOSURE_OVERLAY_CANDIDATE"
            reason = "Historical left-tail vulnerability supports overlay observation."
        elif has_future:
            bucket = "WATCH_ONLY"
            reason = "Forward event exists but stronger policy criteria are not met."
        else:
            bucket = "NO_EVENT_RISK_ACTION"
            reason = "No forward event is scheduled within 180 days."
        rows.append({
            "rank": row["rank"], "ticker": row["ticker"],
            "final_score": row["final_score"],
            "historical_event_count": row["historical_event_count"],
            "historical_earnings_occurrence_count": row["historical_earnings_occurrence_count"],
            "historical_severe_loss_count": severe,
            "historical_event_vulnerability_score": score,
            "historical_event_vulnerability_bucket": row["historical_event_vulnerability_bucket"],
            "future_event_count_next_180d": row["future_event_count_next_180d"],
            "nearest_future_event_date": row["nearest_future_event_date"],
            "days_to_nearest_future_event": row["days_to_nearest_future_event"],
            "future_event_severity": severity,
            "future_event_confidence": confidence_value,
            "event_policy_bucket": bucket, "policy_reason": reason,
            "entry_throttle_candidate": entry,
            "exposure_overlay_candidate": overlay,
            "research_only": True, "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def variant_table() -> pd.DataFrame:
    rows = []
    for variant in VARIANTS:
        rows.append({
            **variant,
            "entry_window": (
                "" if pd.isna(variant["entry_start"])
                else f"T{int(variant['entry_start']):+d}_TO_T{int(variant['entry_end']):+d}"
            ),
            "overlay_window": (
                "" if pd.isna(variant["overlay_start"])
                else f"T{int(variant['overlay_start']):+d}_TO_T{int(variant['overlay_end']):+d}"
            ),
            "historical_pre_event_backtest_allowed": False,
            "forward_observation_only": True,
            "diagnostic_only": True, "research_only": True,
            "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def checkpoint_offset(label: str) -> int:
    if label == "T0":
        return 0
    return int(label.replace("T", ""))


def action_for(
    variant: pd.Series, bucket: pd.Series, checkpoint: int
) -> str:
    family = variant["policy_family"]
    entry_candidate = truth(bucket["entry_throttle_candidate"])
    overlay_candidate = truth(bucket["exposure_overlay_candidate"])
    entry_active = (
        entry_candidate and pd.notna(variant["entry_start"])
        and int(variant["entry_start"]) <= checkpoint <= int(variant["entry_end"])
    )
    overlay_active = (
        overlay_candidate and pd.notna(variant["overlay_start"])
        and int(variant["overlay_start"]) <= checkpoint <= int(variant["overlay_end"])
    )
    if family == "WATCH":
        return "WATCH_ONLY"
    if family == "ENTRY":
        return "BLOCK_NEW_ENTRY" if entry_active else "OBSERVE_NO_CHANGE"
    if family == "OVERLAY":
        return (
            f"SCALE_EXPOSURE_{float(variant['exposure_multiplier']):.2f}"
            if overlay_active else "OBSERVE_NO_CHANGE"
        )
    if entry_active and overlay_active:
        return f"BLOCK_NEW_ENTRY_AND_SCALE_{float(variant['exposure_multiplier']):.2f}"
    if entry_active:
        return "BLOCK_NEW_ENTRY"
    if overlay_active:
        return f"SCALE_EXPOSURE_{float(variant['exposure_multiplier']):.2f}"
    return "OBSERVE_NO_CHANGE"


def policy_ledger(
    schedule: pd.DataFrame, buckets: pd.DataFrame, variants: pd.DataFrame
) -> pd.DataFrame:
    bucket_map = buckets.set_index("ticker")
    rows = []
    for _, observation in schedule.iterrows():
        ticker = observation["ticker"]
        bucket = bucket_map.loc[ticker]
        event_date = pd.Timestamp(observation["event_date"])
        checkpoint = checkpoint_offset(observation["checkpoint_label"])
        for _, variant in variants.iterrows():
            starts = [
                int(value) for value in (
                    variant["entry_start"], variant["overlay_start"]
                ) if pd.notna(value)
            ]
            ends = [
                int(value) for value in (
                    variant["entry_end"], variant["overlay_end"]
                ) if pd.notna(value)
            ]
            policy_start = event_date + BDay(min(starts)) if starts else event_date
            policy_end = event_date + BDay(max(ends)) if ends else event_date
            action = action_for(variant, bucket, checkpoint)
            rows.append({
                "policy_observation_id": "V21_098_POL_" + hashlib.sha256(
                    f"{observation['observation_id']}|{variant['policy_variant']}".encode()
                ).hexdigest()[:20].upper(),
                "ticker": ticker, "rank": observation["rank"],
                "event_type": observation["event_type"],
                "event_name": observation["event_name"],
                "event_date": observation["event_date"],
                "event_time": observation["event_time"],
                "event_severity": observation["event_severity"],
                "event_confidence": observation["event_confidence"],
                "historical_event_vulnerability_bucket": bucket[
                    "historical_event_vulnerability_bucket"
                ],
                "historical_event_vulnerability_score": bucket[
                    "historical_event_vulnerability_score"
                ],
                "policy_variant": variant["policy_variant"],
                "policy_action": action,
                "policy_window_start": policy_start.date().isoformat(),
                "policy_window_end": policy_end.date().isoformat(),
                "checkpoint_label": observation["checkpoint_label"],
                "checkpoint_date": observation["checkpoint_date"],
                "checkpoint_maturity_status": observation["checkpoint_maturity_status"],
                "baseline_action": "D_BASELINE_UNCHANGED_OBSERVE",
                "research_policy_action": action,
                "price_required_date": observation["price_required_date"],
                "price_available": observation["price_available"],
                "realized_return_available": observation["realized_return_available"],
                "research_only": True, "official_adoption_allowed": False,
                "notes": (
                    "Forward diagnostic schedule only; no official action and no historical "
                    "pre-event validity claim."
                ),
            })
    return pd.DataFrame(rows)


def cvar(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    cutoff = clean.quantile(.05)
    return clean[clean.le(cutoff)].mean()


def historical_support(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for event_type, group in returns.groupby("event_type"):
        ret5, ret10 = group["return_5d"].dropna(), group["return_10d"].dropna()
        severe = int(ret5.le(-.10).sum() + ret10.le(-.10).sum())
        usable = int(group[["return_5d", "return_10d"]].notna().any(axis=1).sum())
        rate = severe / (len(ret5) + len(ret10)) if len(ret5) + len(ret10) else np.nan
        cvar5, cvar10 = cvar(ret5), cvar(ret10)
        entry = bool(rate >= .08 or (pd.notna(cvar5) and cvar5 <= -.15))
        overlay = bool(rate >= .05 or (pd.notna(cvar10) and cvar10 <= -.12))
        strength = (
            "STRONG" if entry and overlay and severe >= 10
            else "MODERATE" if entry or overlay
            else "WEAK"
        )
        rows.append({
            "event_type": event_type, "historical_event_count": len(group),
            "usable_event_count": usable, "severe_loss_count": severe,
            "severe_loss_rate": rate, "cvar_5d": cvar5, "cvar_10d": cvar10,
            "worst_5d_return": ret5.min(), "worst_10d_return": ret10.min(),
            "supports_entry_throttle_research": entry,
            "supports_exposure_overlay_research": overlay,
            "support_strength": strength, "diagnostic_only": True,
            "historical_pre_event_backtest_allowed": False,
        })
    return pd.DataFrame(rows)


def recommended_variant(bucket: str) -> tuple[str, str, str, str]:
    if bucket == "ENTRY_THROTTLE_AND_OVERLAY_CANDIDATE":
        return (
            "EVENT_COMBINED_MEDIUM", "T-3_TO_T+1", "T-3_TO_T+1",
            "COMBINED_POLICY_OBSERVE_FORWARD",
        )
    if bucket == "ENTRY_THROTTLE_CANDIDATE":
        return (
            "EVENT_ENTRY_THROTTLE_MEDIUM", "T-3_TO_T+1", "",
            "ENTRY_THROTTLE_OBSERVE_FORWARD",
        )
    if bucket == "EXPOSURE_OVERLAY_CANDIDATE":
        return (
            "EVENT_EXPOSURE_OVERLAY_MEDIUM", "", "T-3_TO_T+1",
            "EXPOSURE_OVERLAY_OBSERVE_FORWARD",
        )
    if bucket == "WATCH_ONLY":
        return "EVENT_WATCH_ONLY", "", "", "WATCH_ONLY_RESEARCH"
    if bucket == "DATA_INSUFFICIENT":
        return "EVENT_WATCH_ONLY", "", "", "DATA_INSUFFICIENT"
    return "EVENT_WATCH_ONLY", "", "", "NO_ACTION_RESEARCH_ONLY"


def top20_dashboard(buckets: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    first_events = schedule.sort_values(
        ["ticker", "event_date", "checkpoint_date"]
    ).drop_duplicates("ticker")
    event_map = first_events.set_index("ticker")
    rows = []
    for _, bucket in buckets[buckets["rank"].le(20)].iterrows():
        ticker = bucket["ticker"]
        event = event_map.loc[ticker] if ticker in event_map.index else None
        variant, entry_window, overlay_window, status = recommended_variant(
            bucket["event_policy_bucket"]
        )
        rows.append({
            "rank": bucket["rank"], "ticker": ticker,
            "final_score": bucket["final_score"],
            "nearest_future_event_date": bucket["nearest_future_event_date"],
            "days_to_nearest_future_event": bucket["days_to_nearest_future_event"],
            "event_type": "" if event is None else event["event_type"],
            "event_severity": bucket["future_event_severity"],
            "event_confidence": bucket["future_event_confidence"],
            "historical_event_vulnerability_bucket": bucket[
                "historical_event_vulnerability_bucket"
            ],
            "event_policy_bucket": bucket["event_policy_bucket"],
            "recommended_research_policy_variant": variant,
            "entry_throttle_window": entry_window,
            "exposure_overlay_window": overlay_window,
            "policy_status": status, "research_only": True,
            "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256(root / D_REL)
    input_hashes_before = {rel.as_posix(): sha256(root / rel) for rel in INPUTS}

    validation_rows, validation = validate_inputs(root)
    validation_rows.to_csv(out / OUTPUTS[0], index=False)
    write_json(out / OUTPUTS[1], validation)
    returns = pd.read_csv(root / RETURNS_REL, low_memory=False)
    schedule = pd.read_csv(root / SCHEDULE_REL, low_memory=False)
    dashboard = pd.read_csv(root / DASHBOARD_REL, low_memory=False)
    stats = historical_ticker_stats(returns)
    buckets = build_buckets(dashboard, schedule, stats)
    buckets.to_csv(out / OUTPUTS[2], index=False)
    variants = variant_table()
    variants.to_csv(out / OUTPUTS[3], index=False)
    ledger = policy_ledger(schedule, buckets, variants)
    ledger.to_csv(out / OUTPUTS[4], index=False)
    support = historical_support(returns)
    support.to_csv(out / OUTPUTS[5], index=False)
    policy_dashboard = top20_dashboard(buckets, schedule)
    policy_dashboard.to_csv(out / OUTPUTS[6], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256(root / D_REL) == d_hash_before
    input_preserved = all(
        sha256(root / Path(path)) == digest
        for path, digest in input_hashes_before.items()
    )
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    pit_warnings = int(validation["pit_leakage_warnings"])
    entry_candidates = int(buckets["entry_throttle_candidate"].map(truth).sum())
    overlay_candidates = int(buckets["exposure_overlay_candidate"].map(truth).sum())
    combined_candidates = int((
        buckets["entry_throttle_candidate"].map(truth)
        & buckets["exposure_overlay_candidate"].map(truth)
    ).sum())
    watch_rows = int(buckets["event_policy_bucket"].eq("WATCH_ONLY").sum())
    if pit_warnings:
        decision = "REJECT_EVENT_POLICY_RESEARCH_DUE_TO_PIT_LEAKAGE"
    elif changed or not d_preserved or not input_preserved:
        decision = "REJECT_EVENT_POLICY_RESEARCH_DUE_TO_PROTECTED_MUTATION"
    elif schedule.empty:
        decision = "FORWARD_EVENT_POLICY_OBSERVATION_BLOCKED_NO_EVENTS"
    elif entry_candidates or overlay_candidates:
        decision = "EVENT_POLICY_FORWARD_OBSERVATION_READY_RESEARCH_ONLY"
    elif watch_rows:
        decision = "EVENT_POLICY_WATCH_ONLY_READY_RESEARCH_ONLY"
    else:
        decision = "FORWARD_EVENT_POLICY_OBSERVATION_BLOCKED_NO_EVENTS"
    summary = {
        "FINAL_STATUS": (
            "PASS" if validation["status"] == "PASS" and not pit_warnings
            and not changed and d_preserved and input_preserved else "FAIL"
        ),
        "DECISION": decision,
        "INPUT_V21_097_STATUS": validation["input_v21_097_status"],
        "TOP20_FORWARD_EVENTS_LOADED": int(schedule["ticker"].nunique()),
        "TOP20_POLICY_OBSERVATION_ROWS": len(ledger),
        "POLICY_VARIANTS_TESTED_OR_SCHEDULED": len(variants),
        "ENTRY_THROTTLE_CANDIDATES": entry_candidates,
        "EXPOSURE_OVERLAY_CANDIDATES": overlay_candidates,
        "COMBINED_POLICY_CANDIDATES": combined_candidates,
        "WATCH_ONLY_ROWS": watch_rows,
        "HISTORICAL_SUPPORT_ROWS": len(support),
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "FORWARD_POLICY_OBSERVATION_ALLOWED": not schedule.empty,
        "ENTRY_THROTTLE_RESEARCH_ALLOWED": entry_candidates > 0,
        "EXPOSURE_OVERLAY_RESEARCH_ALLOWED": overlay_candidates > 0,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved or not input_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "V21_097_INPUTS_PRESERVED": input_preserved,
        "RECOMMENDED_NEXT_STAGE": "V21.099_FORWARD_EVENT_POLICY_MATURITY_MONITOR",
    }
    write_json(out / OUTPUTS[8], summary)
    (out / OUTPUTS[7]).write_text(markdown(
        "V21.098 Event-Aware Entry Throttle and Exposure Overlay Research", summary
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
