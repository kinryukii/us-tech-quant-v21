#!/usr/bin/env python
"""V21.099 forward-only event policy maturity and realized-outcome tracker."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUT = Path("outputs/v21")
LEDGER_REL = OUT / "v21_098_r4_top20_forward_policy_observation_ledger.csv"
DASHBOARD_REL = OUT / "v21_098_r6_current_d_top20_event_policy_dashboard.csv"
SUMMARY_098_REL = OUT / "v21_098_r7_event_aware_entry_throttle_overlay_summary.json"
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
INPUTS = (LEDGER_REL, DASHBOARD_REL, SUMMARY_098_REL)
OUTPUTS = (
    "v21_099_r1_policy_observation_input_validation.csv",
    "v21_099_r1_policy_observation_input_validation.json",
    "v21_099_r2_policy_checkpoint_maturity_status.csv",
    "v21_099_r3_matured_policy_observation_outcomes.csv",
    "v21_099_r4_policy_variant_performance_summary.csv",
    "v21_099_r5_ticker_forward_policy_summary.csv",
    "v21_099_r6_forward_event_policy_maturity_report.md",
    "v21_099_r6_forward_event_policy_maturity_summary.json",
)
REQUIRED_LEDGER_COLUMNS = {
    "policy_observation_id", "ticker", "rank", "event_type", "event_name",
    "event_date", "event_severity", "event_confidence",
    "historical_event_vulnerability_bucket", "policy_variant", "policy_action",
    "checkpoint_label", "checkpoint_date", "price_required_date",
    "research_only", "official_adoption_allowed",
}
MATURITY_COLUMNS = [
    "policy_observation_id", "ticker", "rank", "event_type", "event_name",
    "event_date", "policy_variant", "policy_action", "checkpoint_label",
    "checkpoint_date", "price_required_date", "latest_available_price_date",
    "checkpoint_maturity_status", "maturity_reason", "price_available",
    "realized_return_available", "research_only",
]
OUTCOME_COLUMNS = [
    "policy_observation_id", "ticker", "rank", "event_type", "event_name",
    "event_date", "event_severity", "event_confidence",
    "historical_event_vulnerability_bucket", "policy_variant", "policy_action",
    "checkpoint_label", "checkpoint_date", "return_endpoint_date",
    "realized_return_from_checkpoint", "event_window_return",
    "benchmark_return_vs_QQQ", "benchmark_return_vs_SPY",
    "excess_return_vs_QQQ", "severe_loss_flag", "missed_upside_flag",
    "avoided_loss_flag", "policy_would_have_blocked_entry",
    "policy_would_have_scaled_exposure", "policy_adjusted_return",
    "diagnostic_policy_outcome", "research_only", "official_adoption_allowed",
]


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
    if isinstance(value, (pd.Timestamp, datetime)):
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


def load_prices(root: Path, symbols: set[str]) -> dict[str, pd.DataFrame]:
    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        root / PRICE_REL,
        usecols=["symbol", "date", "adjusted_close"],
        chunksize=250_000,
        low_memory=False,
    ):
        keep = chunk["symbol"].astype(str).str.upper().isin(symbols)
        if keep.any():
            parts.append(chunk.loc[keep].copy())
    if not parts:
        return {}
    frame = pd.concat(parts, ignore_index=True)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna(subset=["date", "adjusted_close"])
    frame = frame.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"])
    return {symbol: group.reset_index(drop=True) for symbol, group in frame.groupby("symbol")}


def price_position(frame: pd.DataFrame | None, date: pd.Timestamp) -> int | None:
    if frame is None or frame.empty or pd.isna(date):
        return None
    dates = frame["date"].to_numpy(dtype="datetime64[ns]")
    position = int(np.searchsorted(dates, np.datetime64(date.normalize()), side="left"))
    if position >= len(frame) or pd.Timestamp(frame.iloc[position]["date"]) != date.normalize():
        return None
    return position


def return_between_positions(frame: pd.DataFrame, start: int, end: int) -> float:
    start_price = float(frame.iloc[start]["adjusted_close"])
    end_price = float(frame.iloc[end]["adjusted_close"])
    return end_price / start_price - 1.0


def aligned_benchmark_return(
    frame: pd.DataFrame | None, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> float:
    start = price_position(frame, start_date)
    end = price_position(frame, end_date)
    if start is None or end is None or end <= start:
        return np.nan
    return return_between_positions(frame, start, end)


def exposure_multiplier(variant: str) -> float:
    if "OVERLAY_LIGHT" in variant or "COMBINED_LIGHT" in variant:
        return .75
    if "OVERLAY_MEDIUM" in variant or "COMBINED_MEDIUM" in variant:
        return .50
    if "OVERLAY_HEAVY" in variant or "COMBINED_HEAVY" in variant:
        return .25
    return 1.0


def validate_inputs(
    root: Path, ledger: pd.DataFrame, summary_098: dict[str, Any], d_hash_before: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing_columns = sorted(REQUIRED_LEDGER_COLUMNS - set(ledger.columns))
    variants = sorted(ledger["policy_variant"].dropna().astype(str).unique()) if not missing_columns else []
    row_match = len(ledger) == 1800
    explanation = "" if row_match else f"Expected 1800 rows; loaded {len(ledger)}."
    checks = [
        ("v21_098_summary_exists", (root / SUMMARY_098_REL).is_file(), ""),
        ("v21_098_final_status_pass", summary_098.get("FINAL_STATUS") == "PASS", str(summary_098.get("FINAL_STATUS", "MISSING"))),
        ("policy_observation_ledger_exists", (root / LEDGER_REL).is_file(), ""),
        ("top20_policy_observation_rows_1800", row_match, explanation),
        ("required_columns_exist", not missing_columns, ",".join(missing_columns)),
        ("policy_variants_exist", bool(variants), ",".join(variants)),
        ("historical_pre_event_random_backtest_blocked", summary_098.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False, ""),
        ("pit_leakage_warnings_zero", int(summary_098.get("PIT_LEAKAGE_WARNINGS", 1)) == 0, ""),
        ("research_only_true", bool(len(ledger)) and ledger["research_only"].map(truth).all(), ""),
        ("official_adoption_false", bool(len(ledger)) and not ledger["official_adoption_allowed"].map(truth).any(), ""),
        ("d_baseline_hash_available", bool(d_hash_before), d_hash_before),
    ]
    rows = pd.DataFrame(checks, columns=["check_name", "passed", "detail"])
    summary = {
        "stage": "V21.099-R1_POLICY_OBSERVATION_INPUT_VALIDATION",
        "status": "PASS" if rows["passed"].all() else "FAIL",
        "input_v21_098_status": summary_098.get("FINAL_STATUS", "MISSING"),
        "policy_observation_rows_loaded": len(ledger),
        "expected_policy_observation_rows": 1800,
        "row_count_mismatch_explanation": explanation,
        "required_columns_missing": missing_columns,
        "policy_variants": variants,
        "historical_pre_event_random_backtest_allowed": False,
        "pit_leakage_warnings": int(summary_098.get("PIT_LEAKAGE_WARNINGS", 0)),
        "research_only": True,
        "official_adoption_allowed": False,
        "d_baseline_sha256_before": d_hash_before,
    }
    return rows, summary


def maturity_status(
    ledger: pd.DataFrame,
    dashboard: pd.DataFrame,
    price_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    dashboard_dates = {
        str(row["ticker"]).upper(): pd.to_datetime(
            row.get("nearest_future_event_date"), errors="coerce"
        )
        for _, row in dashboard.iterrows()
    }
    latest_global = max(
        (frame["date"].max() for frame in price_map.values() if not frame.empty),
        default=pd.NaT,
    )
    rows: list[dict[str, Any]] = []
    for _, row in ledger.iterrows():
        ticker = str(row["ticker"]).upper()
        checkpoint = pd.to_datetime(row["checkpoint_date"], errors="coerce")
        event_date = pd.to_datetime(row["event_date"], errors="coerce")
        ticker_prices = price_map.get(ticker)
        latest = ticker_prices["date"].max() if ticker_prices is not None and not ticker_prices.empty else latest_global
        position = price_position(ticker_prices, checkpoint)
        current_event_date = dashboard_dates.get(ticker)
        event_changed = (
            current_event_date is not None and pd.notna(current_event_date)
            and pd.notna(event_date) and current_event_date.normalize() != event_date.normalize()
        )
        if pd.isna(checkpoint) or pd.isna(event_date):
            status, reason = "INVALID_DATE", "Checkpoint or event date is invalid."
        elif event_changed:
            status, reason = "EVENT_DATE_CHANGED_NEEDS_REVIEW", "V21.098 dashboard event date differs from ledger event date."
        elif pd.isna(latest) or checkpoint > latest:
            status, reason = "PENDING_FUTURE_CHECKPOINT", "Checkpoint is later than latest available ticker price date."
        elif ticker_prices is None or ticker_prices.empty:
            status, reason = "PENDING_PRICE_DATA", "No local daily price series is available for ticker."
        elif position is None:
            status, reason = "PRICE_MISSING", "Exact checkpoint trading-date price is missing; no price was inferred."
        elif position + 5 >= len(ticker_prices):
            status, reason = "PENDING_PRICE_DATA", "Fifth subsequent observed trading-session endpoint is not available."
        else:
            status, reason = "MATURED", "Checkpoint and fifth subsequent observed trading-session prices are available."
        record = {column: row.get(column, "") for column in MATURITY_COLUMNS}
        record.update({
            "latest_available_price_date": "" if pd.isna(latest) else latest.date().isoformat(),
            "checkpoint_maturity_status": status,
            "maturity_reason": reason,
            "price_available": position is not None,
            "realized_return_available": status == "MATURED",
            "research_only": True,
        })
        rows.append(record)
    return pd.DataFrame(rows, columns=MATURITY_COLUMNS)


def matured_outcomes(
    ledger: pd.DataFrame,
    maturity: pd.DataFrame,
    price_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    matured_ids = set(
        maturity.loc[maturity["checkpoint_maturity_status"].eq("MATURED"), "policy_observation_id"]
    )
    rows: list[dict[str, Any]] = []
    for _, row in ledger[ledger["policy_observation_id"].isin(matured_ids)].iterrows():
        ticker = str(row["ticker"]).upper()
        frame = price_map[ticker]
        checkpoint = pd.to_datetime(row["checkpoint_date"]).normalize()
        event_date = pd.to_datetime(row["event_date"]).normalize()
        start = price_position(frame, checkpoint)
        if start is None or start + 5 >= len(frame):
            continue
        end = start + 5
        endpoint_date = pd.Timestamp(frame.iloc[end]["date"])
        realized = return_between_positions(frame, start, end)
        event_start = price_position(frame, event_date)
        event_window = (
            return_between_positions(frame, event_start, event_start + 5)
            if event_start is not None and event_start + 5 < len(frame) else np.nan
        )
        qqq = aligned_benchmark_return(price_map.get("QQQ"), checkpoint, endpoint_date)
        spy = aligned_benchmark_return(price_map.get("SPY"), checkpoint, endpoint_date)
        variant = str(row["policy_variant"])
        action = str(row["policy_action"]).upper()
        blocked = "BLOCK" in action and "OBSERVE_NO_CHANGE" not in action
        multiplier = exposure_multiplier(variant)
        scaled = multiplier < 1.0 and (
            "SCALE" in action or "OVERLAY" in action or "COMBINED" in variant
        )
        adjusted = 0.0 if blocked else realized * multiplier if scaled else realized
        severe = realized <= -.10
        upside = realized >= .10
        avoided = severe and adjusted > realized
        missed = upside and adjusted < realized
        if avoided:
            diagnostic = "AVOIDED_SEVERE_LOSS"
        elif missed:
            diagnostic = "MISSED_UPSIDE"
        elif blocked:
            diagnostic = "BLOCKED_ENTRY_NEUTRAL"
        elif scaled:
            diagnostic = "SCALED_EXPOSURE_NEUTRAL"
        else:
            diagnostic = "NO_POLICY_EFFECT"
        record = {column: row.get(column, "") for column in OUTCOME_COLUMNS}
        record.update({
            "return_endpoint_date": endpoint_date.date().isoformat(),
            "realized_return_from_checkpoint": realized,
            "event_window_return": event_window,
            "benchmark_return_vs_QQQ": qqq,
            "benchmark_return_vs_SPY": spy,
            "excess_return_vs_QQQ": realized - qqq if pd.notna(qqq) else np.nan,
            "severe_loss_flag": severe,
            "missed_upside_flag": missed,
            "avoided_loss_flag": avoided,
            "policy_would_have_blocked_entry": blocked,
            "policy_would_have_scaled_exposure": scaled,
            "policy_adjusted_return": adjusted,
            "diagnostic_policy_outcome": diagnostic,
            "research_only": True,
            "official_adoption_allowed": False,
        })
        rows.append(record)
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def cvar_5(values: pd.Series) -> float:
    clean = values.dropna()
    if clean.empty:
        return np.nan
    cutoff = clean.quantile(.05)
    return float(clean[clean <= cutoff].mean())


def variant_summary(
    ledger: pd.DataFrame, maturity: pd.DataFrame, outcomes: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant, group in ledger.groupby("policy_variant", sort=True):
        ids = set(group["policy_observation_id"])
        mature_group = outcomes[outcomes["policy_observation_id"].isin(ids)]
        status_group = maturity[maturity["policy_observation_id"].isin(ids)]
        adjusted = mature_group["policy_adjusted_return"]
        excess = mature_group["excess_return_vs_QQQ"]
        severe_count = int(mature_group["severe_loss_flag"].map(truth).sum())
        avoided_count = int(mature_group["avoided_loss_flag"].map(truth).sum())
        missed_count = int(mature_group["missed_upside_flag"].map(truth).sum())
        matured_count = len(mature_group)
        severe_rate = severe_count / matured_count if matured_count else np.nan
        avoided_rate = avoided_count / severe_count if severe_count else 0.0
        upside_count = int(mature_group["realized_return_from_checkpoint"].ge(.10).sum())
        missed_rate = missed_count / upside_count if upside_count else 0.0
        tail_proxy = float(
            (mature_group["policy_adjusted_return"] - mature_group["realized_return_from_checkpoint"])
            .where(mature_group["realized_return_from_checkpoint"].le(-.10)).mean()
        ) if severe_count else 0.0
        winner_penalty = float(
            (mature_group["realized_return_from_checkpoint"] - mature_group["policy_adjusted_return"])
            .where(mature_group["realized_return_from_checkpoint"].ge(.10)).mean()
        ) if upside_count else 0.0
        rows.append({
            "policy_variant": variant,
            "total_rows": len(group),
            "matured_rows": matured_count,
            "pending_rows": int((~status_group["checkpoint_maturity_status"].eq("MATURED")).sum()),
            "severe_loss_count": severe_count,
            "severe_loss_rate": severe_rate,
            "avoided_loss_count": avoided_count,
            "avoided_loss_rate": avoided_rate,
            "missed_upside_count": missed_count,
            "missed_upside_rate": missed_rate,
            "mean_realized_return": adjusted.mean(),
            "median_realized_return": adjusted.median(),
            "p10_return": adjusted.quantile(.10) if matured_count else np.nan,
            "p5_return": adjusted.quantile(.05) if matured_count else np.nan,
            "cvar_5": cvar_5(adjusted),
            "worst_return": adjusted.min(),
            "mean_excess_vs_QQQ": excess.mean(),
            "median_excess_vs_QQQ": excess.median(),
            "left_tail_improvement_proxy": tail_proxy,
            "missed_winner_penalty": winner_penalty,
            "net_research_score": tail_proxy - winner_penalty,
            "research_only": True,
            "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def ticker_summary(
    ledger: pd.DataFrame, maturity: pd.DataFrame, outcomes: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    identity = [
        "ticker", "rank", "event_date", "event_type", "event_severity",
        "event_confidence", "historical_event_vulnerability_bucket",
    ]
    for keys, group in ledger.groupby(identity, dropna=False, sort=True):
        ids = set(group["policy_observation_id"])
        status_group = maturity[maturity["policy_observation_id"].isin(ids)]
        result = outcomes[outcomes["policy_observation_id"].isin(ids)]
        scores = (
            result.groupby("policy_variant")["policy_adjusted_return"].mean().sort_values()
            if not result.empty else pd.Series(dtype=float)
        )
        rows.append({
            **dict(zip(identity, keys)),
            "policy_variants_observed": group["policy_variant"].nunique(),
            "matured_policy_rows": len(result),
            "pending_policy_rows": int((~status_group["checkpoint_maturity_status"].eq("MATURED")).sum()),
            "severe_loss_observed": bool(result["severe_loss_flag"].map(truth).any()) if not result.empty else False,
            "best_research_policy_variant_so_far": scores.index[-1] if len(scores) else "",
            "worst_policy_variant_so_far": scores.index[0] if len(scores) else "",
            "missed_upside_count": int(result["missed_upside_flag"].map(truth).sum()) if not result.empty else 0,
            "avoided_loss_count": int(result["avoided_loss_flag"].map(truth).sum()) if not result.empty else 0,
            "notes": (
                "Forward matured checkpoints only; diagnostic research, no official adoption."
                if len(result) else "No matured forward checkpoints; waiting for price maturity."
            ),
        })
    return pd.DataFrame(rows)


def report(summary: dict[str, Any]) -> str:
    lines = ["# V21.099 Forward Event Policy Maturity Report", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        "",
        "Only checkpoints created by the V21.098 forward ledger and matured against observed "
        "local prices were evaluated. Returns use the checkpoint close through the fifth "
        "subsequent observed trading-session close. Missing prices were not inferred.",
        "",
        "This is research-only monitoring. It does not establish historical pre-event "
        "tradability, modify D, or authorize official policy adoption.",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    missing = [path.as_posix() for path in (*INPUTS, PRICE_REL, D_REL) if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))
    d_hash_before = sha256(root / D_REL)
    input_hashes = {path.as_posix(): sha256(root / path) for path in INPUTS}
    before = protected_snapshot(root, output_paths)

    ledger = pd.read_csv(root / LEDGER_REL, low_memory=False)
    dashboard = pd.read_csv(root / DASHBOARD_REL, low_memory=False)
    summary_098 = json.loads((root / SUMMARY_098_REL).read_text(encoding="utf-8"))
    validation_rows, validation = validate_inputs(root, ledger, summary_098, d_hash_before)
    validation_rows.to_csv(out / OUTPUTS[0], index=False)
    write_json(out / OUTPUTS[1], validation)

    symbols = set(ledger["ticker"].dropna().astype(str).str.upper()) | {"QQQ", "SPY"}
    price_map = load_prices(root, symbols)
    maturity = maturity_status(ledger, dashboard, price_map)
    maturity.to_csv(out / OUTPUTS[2], index=False)
    outcomes = matured_outcomes(ledger, maturity, price_map)
    outcomes.to_csv(out / OUTPUTS[3], index=False)
    variants = variant_summary(ledger, maturity, outcomes)
    variants.to_csv(out / OUTPUTS[4], index=False)
    tickers = ticker_summary(ledger, maturity, outcomes)
    tickers.to_csv(out / OUTPUTS[5], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_hash_after = sha256(root / D_REL)
    d_preserved = d_hash_after == d_hash_before
    inputs_preserved = all(sha256(root / Path(path)) == digest for path, digest in input_hashes.items())
    validation.update({
        "d_baseline_sha256_after": d_hash_after,
        "d_baseline_preserved": d_preserved,
        "v21_098_inputs_preserved": inputs_preserved,
    })
    if not d_preserved or not inputs_preserved:
        validation["status"] = "FAIL"
    write_json(out / OUTPUTS[1], validation)
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    pit_warnings = int(validation["pit_leakage_warnings"])
    matured_count = int(maturity["checkpoint_maturity_status"].eq("MATURED").sum())
    price_missing_count = int(maturity["checkpoint_maturity_status"].isin(["PRICE_MISSING", "PENDING_PRICE_DATA"]).sum())
    pending_count = len(maturity) - matured_count
    severe = int(outcomes["severe_loss_flag"].map(truth).sum()) if not outcomes.empty else 0
    avoided = int(outcomes["avoided_loss_flag"].map(truth).sum()) if not outcomes.empty else 0
    missed = int(outcomes["missed_upside_flag"].map(truth).sum()) if not outcomes.empty else 0
    ranked = variants[variants["matured_rows"].gt(0)].sort_values("net_research_score")
    best = ranked.iloc[-1]["policy_variant"] if len(ranked) else ""
    worst = ranked.iloc[0]["policy_variant"] if len(ranked) else ""
    left_tail = bool(avoided > 0 and variants["left_tail_improvement_proxy"].max() > 0)
    missed_risk = bool(missed > 0)
    protected_modified = bool(changed or not d_preserved or not inputs_preserved)
    if pit_warnings:
        decision = "REJECT_FORWARD_POLICY_TRACKER_DUE_TO_PIT_LEAKAGE"
    elif protected_modified or official_changed:
        decision = "REJECT_FORWARD_POLICY_TRACKER_DUE_TO_PROTECTED_MUTATION"
    elif not matured_count:
        decision = "FORWARD_POLICY_TRACKER_READY_WAITING_FOR_MATURITY"
    elif matured_count < 100:
        decision = "FORWARD_POLICY_TRACKER_PARTIAL_MATURITY_INSUFFICIENT_SAMPLE"
    elif missed > avoided and missed_risk:
        decision = "FORWARD_EVENT_POLICY_REJECTED_DUE_TO_MISSED_UPSIDE_RESEARCH_ONLY"
    elif left_tail and missed <= avoided:
        decision = "FORWARD_EVENT_POLICY_PROMISING_RESEARCH_ONLY"
    else:
        decision = "FORWARD_EVENT_POLICY_NO_EDGE_YET_RESEARCH_ONLY"
    final_status = (
        "PASS" if validation["status"] == "PASS" and not pit_warnings
        and not protected_modified and not official_changed else "FAIL"
    )
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "INPUT_V21_098_STATUS": validation["input_v21_098_status"],
        "POLICY_OBSERVATION_ROWS_LOADED": len(ledger),
        "POLICY_CHECKPOINTS_MATURED": matured_count,
        "POLICY_CHECKPOINTS_PENDING": pending_count,
        "POLICY_CHECKPOINTS_PRICE_MISSING": price_missing_count,
        "MATURED_POLICY_OUTCOME_ROWS": len(outcomes),
        "POLICY_VARIANTS_EVALUATED": int(ledger["policy_variant"].nunique()),
        "SEVERE_LOSS_EVENTS_OBSERVED": severe,
        "AVOIDED_LOSS_COUNT": avoided,
        "MISSED_UPSIDE_COUNT": missed,
        "BEST_POLICY_VARIANT_SO_FAR": best,
        "WORST_POLICY_VARIANT_SO_FAR": worst,
        "LEFT_TAIL_IMPROVEMENT_OBSERVED": left_tail,
        "MISSED_WINNER_RISK_OBSERVED": missed_risk,
        "FORWARD_POLICY_OBSERVATION_ALLOWED": True,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "OFFICIAL_POLICY_ADOPTION_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "D_BASELINE_SHA256_BEFORE": d_hash_before,
        "D_BASELINE_SHA256_AFTER": d_hash_after,
        "RECOMMENDED_NEXT_STAGE": "V21.100_FORWARD_EVENT_POLICY_MATURITY_CONTINUATION",
    }
    write_json(out / OUTPUTS[7], summary)
    (out / OUTPUTS[6]).write_text(report(summary), encoding="utf-8")
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
