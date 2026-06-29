#!/usr/bin/env python
"""V21.100 PIT post-occurrence event-risk weight grid diagnostic backtest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay


OUT = Path("outputs/v21")
MASTER = OUT / "v21_096_r6_certified_event_master_ledger.csv"
RETURNS = OUT / "v21_097_r2_historical_event_occurrence_return_rows.csv"
IMPACT = OUT / "v21_097_r3_event_type_impact_summary.csv"
VULNERABILITY = OUT / "v21_097_r4_ticker_event_vulnerability_summary.csv"
DASHBOARD = OUT / "v21_097_r6_current_d_event_risk_dashboard.csv"
BUCKETS = OUT / "v21_098_r2_event_vulnerability_policy_buckets.csv"
POLICIES = OUT / "v21_098_r3_event_policy_variants.csv"
SUMMARY_096 = OUT / "v21_096_r7_top50_historical_top20_forward_event_ledger_summary.json"
SUMMARY_097 = OUT / "v21_097_r7_event_occurrence_and_forward_observation_summary.json"
SUMMARY_098 = OUT / "v21_098_r7_event_aware_entry_throttle_overlay_summary.json"
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
D_BASELINE = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
INPUTS = (
    MASTER, RETURNS, IMPACT, VULNERABILITY, DASHBOARD, BUCKETS, POLICIES,
    SUMMARY_096, SUMMARY_097, SUMMARY_098, PRICE, D_BASELINE,
)
OUTPUTS = (
    "v21_100_r1_input_validation.csv",
    "v21_100_r1_input_validation.json",
    "v21_100_r2_event_risk_primitives.csv",
    "v21_100_r3_event_risk_weight_grid.csv",
    "v21_100_r4_event_risk_scores_by_variant.csv",
    "v21_100_r5_event_row_weight_backtest_results.csv",
    "v21_100_r6_optional_pit_portfolio_skipped.json",
    "v21_100_r7_event_weight_variant_summary.csv",
    "v21_100_r8_event_weight_robustness_checks.csv",
    "v21_100_r9_event_risk_weight_grid_backtest_report.md",
    "v21_100_r9_event_risk_weight_grid_backtest_summary.json",
)
WINDOWS = (1, 3, 5, 10, 20)
PRIMITIVE_COLUMNS = [
    "event_id", "ticker", "event_type", "event_date", "known_as_of_timestamp",
    "historical_event_occurrence_usable", "historical_pre_event_calendar_usable",
    "forward_observation_usable", "event_type_left_tail_score",
    "ticker_vulnerability_score", "event_severity_score",
    "event_confidence_score", "macro_event_score", "financing_event_score",
    "earnings_event_score", "ownership_event_score", "research_only",
]


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    def default(value: Any) -> Any:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return None if np.isnan(value) else float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        raise TypeError(type(value).__name__)
    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def protected_snapshot(root: Path, outputs: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.resolve() not in outputs:
                if any(token in path.as_posix().lower() for token in tokens):
                    result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def normalize_loss_score(values: pd.Series) -> pd.Series:
    loss = (-pd.to_numeric(values, errors="coerce")).clip(lower=0)
    maximum = loss.max()
    return loss / maximum if pd.notna(maximum) and maximum > 0 else pd.Series(0.0, index=values.index)


def leave_one_out_score(frame: pd.DataFrame, key: str) -> pd.Series:
    return_5d = pd.to_numeric(frame["return_5d"], errors="coerce")
    return_10d = pd.to_numeric(frame["return_10d"], errors="coerce")
    loss = (
        (-return_5d).clip(lower=0).fillna(0)
        + (-return_10d).clip(lower=0).fillna(0)
        + frame[["return_5d", "return_10d"]].le(-.10).sum(axis=1) * .10
    )
    totals = loss.groupby(frame[key]).transform("sum") - loss
    counts = loss.groupby(frame[key]).transform("count") - 1
    raw = totals / counts.replace(0, np.nan)
    fallback = (loss.sum() - loss) / max(len(loss) - 1, 1)
    raw = raw.fillna(fallback)
    maximum = raw.max()
    return (raw / maximum).clip(0, 1) if maximum > 0 else pd.Series(0.0, index=frame.index)


def static_event_scores(event_type: str, source: str, pit: bool) -> tuple[float, float]:
    text = event_type.lower()
    severity = .85 if any(x in text for x in ("financing", "mna", "earnings")) else .65
    if any(x in text for x in ("management", "agreement", "reg_fd")):
        severity = .55
    confidence = 1.0 if pit and ("sec" in source.lower() or "deterministic" in source.lower()) else .75 if pit else .25
    return severity, confidence


def build_primitives(master: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "event_id", "known_as_of_timestamp", "historical_event_occurrence_usable",
        "historical_pre_event_calendar_usable", "forward_observation_usable",
        "pit_certified", "source_name",
    ]
    merged = returns.merge(master[columns], on="event_id", how="left", validate="one_to_one")
    merged["event_type_left_tail_score"] = leave_one_out_score(merged, "event_type")
    merged["ticker_vulnerability_score"] = leave_one_out_score(merged, "ticker")
    severity, confidence = [], []
    for _, row in merged.iterrows():
        sev, conf = static_event_scores(
            str(row["event_type"]), str(row["source_name"]), truth(row["pit_certified"])
        )
        severity.append(sev)
        confidence.append(conf)
    merged["event_severity_score"] = severity
    merged["event_confidence_score"] = confidence
    event_text = merged["event_type"].astype(str).str.lower()
    merged["macro_event_score"] = event_text.str.contains("macro|fomc|cpi|payroll|opex|holiday").astype(float)
    merged["financing_event_score"] = event_text.str.contains("financing|offering|shelf").astype(float)
    merged["earnings_event_score"] = event_text.str.contains("earnings|financial_report").astype(float)
    merged["ownership_event_score"] = event_text.str.contains("ownership|proxy|shareholder").astype(float)
    merged["research_only"] = True
    return merged[PRIMITIVE_COLUMNS]


def variants() -> pd.DataFrame:
    rows = [
        ("EVENT_WEIGHT_CONTROL_0", 0, 0, 0, 0, 0, 0, 1.00),
        ("EVENT_TYPE_ONLY_LIGHT", .25, 0, 0, 0, 0, 5, .75),
        ("EVENT_TYPE_ONLY_MEDIUM", .50, 0, 0, 0, 0, 5, .50),
        ("EVENT_TYPE_ONLY_HEAVY", 1.00, 0, 0, 0, 0, 5, .25),
        ("TICKER_VULNERABILITY_ONLY", 0, 1.00, 0, 0, 0, 5, .50),
        ("EVENT_TYPE_PLUS_TICKER_LIGHT", .25, .25, 0, 0, 0, 5, .75),
        ("EVENT_TYPE_PLUS_TICKER_MEDIUM", .50, .50, 0, 0, 0, 5, .50),
        ("EVENT_TYPE_PLUS_TICKER_HEAVY", 1.00, 1.00, 0, 0, 0, 5, .25),
        ("FULL_EVENT_RISK_LIGHT", .25, .25, .25, .25, .25, 3, .75),
        ("FULL_EVENT_RISK_MEDIUM", .50, .50, .25, .25, .25, 5, .50),
        ("FULL_EVENT_RISK_HEAVY", 1.00, 1.00, .50, .50, .50, 10, .25),
        ("POST_EVENT_COOLDOWN_1D", .50, .50, .25, .25, 0, 1, .50),
        ("POST_EVENT_COOLDOWN_3D", .50, .50, .25, .25, 0, 3, .50),
        ("POST_EVENT_COOLDOWN_5D", .50, .50, .25, .25, 0, 5, .50),
        ("POST_EVENT_OVERLAY_075", .50, .50, .25, .25, 0, 5, .75),
        ("POST_EVENT_OVERLAY_050", .50, .50, .25, .25, 0, 5, .50),
        ("POST_EVENT_OVERLAY_025", .50, .50, .25, .25, 0, 5, .25),
    ]
    columns = [
        "variant_id", "event_type_weight", "ticker_vulnerability_weight",
        "severity_weight", "confidence_weight", "macro_weight",
        "post_event_cooldown_days", "exposure_scale_when_risky",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["grid_mode"] = "COMPACT_NAMED_VARIANTS"
    frame["full_cartesian_grid_size"] = 5 * 5 * 3 * 3 * 3 * 5 * 4
    frame["skipped_grid_rationale"] = (
        "Full 13500-combination Cartesian grid skipped to bound multiplicity; "
        "17 predeclared compact variants tested first."
    )
    frame["research_only"] = True
    frame["official_adoption_allowed"] = False
    return frame


def score_rows(primitives: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    category = primitives[
        ["macro_event_score", "financing_event_score", "earnings_event_score", "ownership_event_score"]
    ].max(axis=1)
    for _, variant in grid.iterrows():
        weights = np.array([
            variant["event_type_weight"], variant["ticker_vulnerability_weight"],
            variant["severity_weight"], variant["confidence_weight"], variant["macro_weight"],
        ], dtype=float)
        components = np.column_stack([
            primitives["event_type_left_tail_score"],
            primitives["ticker_vulnerability_score"],
            primitives["event_severity_score"],
            primitives["event_confidence_score"],
            category,
        ])
        denominator = weights.sum()
        score = components.dot(weights) / denominator if denominator else np.zeros(len(primitives))
        score = np.clip(score, 0, 1)
        bucket = pd.cut(
            score, bins=[-np.inf, .01, .25, .50, .75, np.inf],
            labels=["NONE", "LOW", "MEDIUM", "HIGH", "EXTREME"],
        ).astype(str)
        cooldown = int(variant["post_event_cooldown_days"])
        known_date = pd.to_datetime(primitives["known_as_of_timestamp"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
        event_date = pd.to_datetime(primitives["event_date"], errors="coerce").dt.normalize()
        start = pd.concat([known_date, event_date], axis=1).max(axis=1)
        result = primitives[["event_id", "ticker", "event_type", "event_date", "known_as_of_timestamp"]].copy()
        result.insert(0, "variant_id", variant["variant_id"])
        result["event_risk_score"] = score
        result["event_risk_bucket"] = bucket
        result["post_event_cooldown_days"] = cooldown
        result["exposure_scale_when_risky"] = float(variant["exposure_scale_when_risky"])
        risky = pd.Series(score >= .50, index=primitives.index) & (float(variant["exposure_scale_when_risky"]) < 1)
        result["risk_action"] = np.where(risky, "POST_DISCLOSURE_SCALE_EXPOSURE", "OBSERVE_NO_CHANGE")
        result["risk_window_start"] = start.dt.date.astype(str)
        result["risk_window_end"] = (start + BDay(cooldown)).dt.date.astype(str)
        result["historical_backtest_allowed"] = True
        result["historical_pre_event_backtest_allowed"] = False
        result["research_only"] = True
        rows.append(result)
    return pd.concat(rows, ignore_index=True)


def backtest(scores: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    base_columns = ["event_id", *[f"return_{w}d" for w in WINDOWS]]
    merged = scores.merge(returns[base_columns], on="event_id", how="left", validate="many_to_one")
    output = merged[[
        "variant_id", "event_id", "ticker", "event_type", "event_date",
        "known_as_of_timestamp", "event_risk_score", "event_risk_bucket",
    ]].copy()
    risky = merged["event_risk_score"].ge(.50)
    scale = merged["exposure_scale_when_risky"].where(risky, 1.0)
    cooldown = merged["post_event_cooldown_days"].astype(float)
    for window in WINDOWS:
        baseline = pd.to_numeric(merged[f"return_{window}d"], errors="coerce")
        fraction = np.minimum(cooldown / window, 1.0)
        effective = 1.0 - fraction * (1.0 - scale)
        scaled = baseline * effective
        output[f"baseline_return_{window}d"] = baseline
        output[f"scaled_return_{window}d"] = scaled
        output[f"loss_reduction_{window}d"] = np.where(
            baseline < 0, scaled - baseline, 0.0
        )
        output[f"missed_upside_{window}d"] = np.where(
            baseline > 0, baseline - scaled, 0.0
        )
    output["avoided_severe_loss_flag"] = (
        output["baseline_return_5d"].le(-.10)
        & output["scaled_return_5d"].gt(-.10)
    )
    output["missed_large_winner_flag"] = (
        output["baseline_return_5d"].ge(.10)
        & output["scaled_return_5d"].lt(output["baseline_return_5d"])
    )
    output["diagnostic_only"] = True
    output["research_only"] = True
    ordered = [
        "variant_id", "event_id", "ticker", "event_type", "event_date",
        "known_as_of_timestamp", "event_risk_score", "event_risk_bucket",
        *[f"baseline_return_{w}d" for w in WINDOWS],
        *[f"scaled_return_{w}d" for w in WINDOWS],
        *[f"loss_reduction_{w}d" for w in WINDOWS],
        *[f"missed_upside_{w}d" for w in WINDOWS],
        "avoided_severe_loss_flag", "missed_large_winner_flag",
        "diagnostic_only", "research_only",
    ]
    return output[ordered]


def cvar5(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values[values <= values.quantile(.05)].mean())


def summarize(backtest_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, group in backtest_rows.groupby("variant_id", sort=True):
        base, scaled = group["baseline_return_5d"], group["scaled_return_5d"]
        base_cvar, scaled_cvar = cvar5(base), cvar5(scaled)
        base_p5, scaled_p5 = base.quantile(.05), scaled.quantile(.05)
        left_tail = max(0.0, scaled_p5 - base_p5) + max(0.0, scaled_cvar - base_cvar)
        penalty = float(group.loc[group["baseline_return_5d"].ge(.10), "missed_upside_5d"].mean())
        penalty = 0.0 if np.isnan(penalty) else penalty
        rows.append({
            "variant_id": variant, "event_count": len(group),
            "usable_event_count": int(base.notna().sum()),
            "mean_baseline_return_5d": base.mean(), "mean_scaled_return_5d": scaled.mean(),
            "median_baseline_return_5d": base.median(), "median_scaled_return_5d": scaled.median(),
            "p5_baseline_return_5d": base_p5, "p5_scaled_return_5d": scaled_p5,
            "cvar5_baseline_5d": base_cvar, "cvar5_scaled_5d": scaled_cvar,
            "severe_loss_count_baseline": int(base.le(-.10).sum()),
            "severe_loss_count_scaled": int(scaled.le(-.10).sum()),
            "avoided_severe_loss_count": int(group["avoided_severe_loss_flag"].map(truth).sum()),
            "missed_large_winner_count": int(group["missed_large_winner_flag"].map(truth).sum()),
            "missed_upside_penalty": penalty, "left_tail_improvement": left_tail,
            "net_research_score": left_tail - penalty, "research_only": True,
            "official_adoption_allowed": False,
        })
    result = pd.DataFrame(rows)
    result["rank_by_left_tail"] = result["left_tail_improvement"].rank(method="min", ascending=False).astype(int)
    result["rank_by_net_score"] = result["net_research_score"].rank(method="min", ascending=False).astype(int)
    ordered = [
        "variant_id", "event_count", "usable_event_count",
        "mean_baseline_return_5d", "mean_scaled_return_5d",
        "median_baseline_return_5d", "median_scaled_return_5d",
        "p5_baseline_return_5d", "p5_scaled_return_5d",
        "cvar5_baseline_5d", "cvar5_scaled_5d",
        "severe_loss_count_baseline", "severe_loss_count_scaled",
        "avoided_severe_loss_count", "missed_large_winner_count",
        "missed_upside_penalty", "left_tail_improvement", "net_research_score",
        "rank_by_left_tail", "rank_by_net_score", "research_only",
        "official_adoption_allowed",
    ]
    return result[ordered]


def score_with_components(
    primitive_subset: pd.DataFrame, variant: pd.Series,
    event_override: pd.Series | None = None, ticker_override: pd.Series | None = None,
) -> pd.Series:
    event = event_override if event_override is not None else primitive_subset["event_type_left_tail_score"]
    ticker = ticker_override if ticker_override is not None else primitive_subset["ticker_vulnerability_score"]
    category = primitive_subset[
        ["macro_event_score", "financing_event_score", "earnings_event_score", "ownership_event_score"]
    ].max(axis=1)
    weights = np.array([
        variant["event_type_weight"], variant["ticker_vulnerability_weight"],
        variant["severity_weight"], variant["confidence_weight"], variant["macro_weight"],
    ], dtype=float)
    denominator = weights.sum()
    if not denominator:
        return pd.Series(0.0, index=primitive_subset.index)
    components = np.column_stack([
        event, ticker, primitive_subset["event_severity_score"],
        primitive_subset["event_confidence_score"], category,
    ])
    return pd.Series(np.clip(components.dot(weights) / denominator, 0, 1), index=primitive_subset.index)


def diagnostic_metric(
    primitive_subset: pd.DataFrame, returns_subset: pd.DataFrame, variant: pd.Series,
    score: pd.Series | None = None,
) -> tuple[float, float, int]:
    joined = primitive_subset[["event_id"]].copy()
    joined["score"] = score if score is not None else score_with_components(primitive_subset, variant)
    joined = joined.merge(returns_subset[["event_id", "return_5d"]], on="event_id", how="left")
    scale = np.where(joined["score"].ge(.50), float(variant["exposure_scale_when_risky"]), 1.0)
    fraction = min(float(variant["post_event_cooldown_days"]) / 5.0, 1.0)
    scaled = joined["return_5d"] * (1 - fraction * (1 - scale))
    left = max(0.0, scaled.quantile(.05) - joined["return_5d"].quantile(.05)) + max(
        0.0, cvar5(scaled) - cvar5(joined["return_5d"])
    )
    winners = joined["return_5d"].ge(.10)
    penalty = float((joined.loc[winners, "return_5d"] - scaled[winners]).mean()) if winners.any() else 0.0
    return left, 0.0 if np.isnan(penalty) else penalty, int(joined["return_5d"].notna().sum())


def load_price_map(root: Path, symbols: set[str]) -> dict[str, pd.DataFrame]:
    parts = []
    for chunk in pd.read_csv(
        root / PRICE, usecols=["symbol", "date", "adjusted_close"],
        chunksize=250_000, low_memory=False,
    ):
        keep = chunk["symbol"].astype(str).str.upper().isin(symbols)
        if keep.any():
            parts.append(chunk.loc[keep])
    if not parts:
        return {}
    frame = pd.concat(parts)
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna().sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"])
    return {symbol: group.reset_index(drop=True) for symbol, group in frame.groupby("symbol")}


def date_shift_returns(primitives: pd.DataFrame, price_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for _, row in primitives.iterrows():
        frame = price_map.get(str(row["ticker"]).upper())
        value = np.nan
        if frame is not None:
            dates = frame["date"].to_numpy(dtype="datetime64[ns]")
            event = np.datetime64(pd.to_datetime(row["event_date"]).normalize())
            start = int(np.searchsorted(dates, event, side="left")) + 20
            if start + 5 < len(frame):
                value = float(frame.iloc[start + 5]["adjusted_close"]) / float(frame.iloc[start]["adjusted_close"]) - 1
        rows.append({"event_id": row["event_id"], "return_5d": value})
    return pd.DataFrame(rows)


def robustness(
    primitives: pd.DataFrame, returns: pd.DataFrame, grid: pd.DataFrame,
    summary: pd.DataFrame, price_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    best_id = summary.sort_values("net_research_score").iloc[-1]["variant_id"]
    variant = grid.set_index("variant_id").loc[best_id]
    real_left = float(summary.set_index("variant_id").loc[best_id, "left_tail_improvement"])
    rng = np.random.default_rng(2100)
    checks: list[dict[str, Any]] = []

    def add(name: str, subset: pd.DataFrame, ret: pd.DataFrame, score: pd.Series | None = None) -> None:
        left, penalty, count = diagnostic_metric(subset, ret, variant, score)
        status = "INCONCLUSIVE_INSUFFICIENT_SAMPLE" if count < 30 else "PASS" if left > 0 and left >= penalty else "WEAK"
        checks.append({
            "check_name": name, "variant_id": best_id, "sample_size": count,
            "left_tail_improvement": left, "missed_upside_penalty": penalty,
            "real_variant_left_tail_improvement": real_left, "check_status": status,
            "beats_placebo": np.nan, "concentration_risk": False,
            "research_only": True,
        })

    event_shuffle = pd.Series(
        rng.permutation(primitives["event_type_left_tail_score"].to_numpy()), index=primitives.index
    )
    score = score_with_components(primitives, variant, event_override=event_shuffle)
    left, penalty, count = diagnostic_metric(primitives, returns, variant, score)
    checks.append({
        "check_name": "event_type_shuffle_placebo", "variant_id": best_id, "sample_size": count,
        "left_tail_improvement": left, "missed_upside_penalty": penalty,
        "real_variant_left_tail_improvement": real_left,
        "check_status": "PASS" if real_left > left else "WEAK",
        "beats_placebo": real_left > left, "concentration_risk": False, "research_only": True,
    })
    ticker_shuffle = pd.Series(
        rng.permutation(primitives["ticker_vulnerability_score"].to_numpy()), index=primitives.index
    )
    score = score_with_components(primitives, variant, ticker_override=ticker_shuffle)
    left, penalty, count = diagnostic_metric(primitives, returns, variant, score)
    checks.append({
        "check_name": "ticker_shuffle_placebo", "variant_id": best_id, "sample_size": count,
        "left_tail_improvement": left, "missed_upside_penalty": penalty,
        "real_variant_left_tail_improvement": real_left,
        "check_status": "PASS" if real_left > left else "WEAK",
        "beats_placebo": real_left > left, "concentration_risk": False, "research_only": True,
    })
    shifted = date_shift_returns(primitives, price_map)
    left, penalty, count = diagnostic_metric(primitives, shifted, variant)
    checks.append({
        "check_name": "date_shift_plus_20_sessions_placebo", "variant_id": best_id,
        "sample_size": count, "left_tail_improvement": left,
        "missed_upside_penalty": penalty, "real_variant_left_tail_improvement": real_left,
        "check_status": "PASS" if count >= 30 and real_left > left else "WEAK" if count >= 30 else "INCONCLUSIVE_INSUFFICIENT_SAMPLE",
        "beats_placebo": real_left > left if count >= 30 else np.nan,
        "concentration_risk": False, "research_only": True,
    })
    text = primitives["event_type"].astype(str).str.lower()
    rank = returns.set_index("event_id")["rank_if_current_top50"].reindex(primitives["event_id"]).reset_index(drop=True)
    subsets = {
        "exclude_earnings_occurrence": ~text.str.contains("earnings"),
        "earnings_only_subset": text.str.contains("earnings"),
        "financing_only_subset": text.str.contains("financing|offering|shelf"),
        "high_confidence_only_subset": primitives["event_confidence_score"].ge(.99),
        "low_confidence_excluded_subset": primitives["event_confidence_score"].ge(.75),
        "top20_only_subset": pd.to_numeric(rank, errors="coerce").le(20),
        "top50_only_subset": pd.to_numeric(rank, errors="coerce").le(50),
    }
    for name, mask in subsets.items():
        ids = set(primitives.loc[mask, "event_id"])
        add(name, primitives.loc[mask].copy(), returns[returns["event_id"].isin(ids)])

    best_scores = score_with_components(primitives, variant)
    contribution = pd.DataFrame({
        "ticker": primitives["ticker"], "event_type": primitives["event_type"],
        "improvement": np.where(
            (best_scores >= .50) & returns["return_5d"].lt(0).to_numpy(),
            -returns["return_5d"].to_numpy() * (1 - float(variant["exposure_scale_when_risky"])), 0,
        ),
    })
    total = contribution["improvement"].sum()
    ticker_share = contribution.groupby("ticker")["improvement"].sum().max() / total if total > 0 else 0
    type_share = contribution.groupby("event_type")["improvement"].sum().max() / total if total > 0 else 0
    concentration = ticker_share > .50 or type_share > .50
    checks.append({
        "check_name": "ticker_and_event_type_concentration", "variant_id": best_id,
        "sample_size": len(primitives), "left_tail_improvement": real_left,
        "missed_upside_penalty": float(summary.set_index("variant_id").loc[best_id, "missed_upside_penalty"]),
        "real_variant_left_tail_improvement": real_left,
        "check_status": "WEAK_CONCENTRATION_RISK" if concentration else "PASS",
        "beats_placebo": np.nan, "concentration_risk": concentration,
        "research_only": True,
    })
    return pd.DataFrame(checks)


def report(summary: dict[str, Any]) -> str:
    lines = ["# V21.100 Event Risk Weight Grid Backtest", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        "",
        "This is a current-universe event-row diagnostic using PIT-certified event occurrences. "
        "It is not an official historical D strategy or portfolio backtest.",
        "",
        "Risk primitives use leave-one-event-out event-type and ticker aggregates. All simulated "
        "actions begin no earlier than the event known-as-of/event date. No pre-event blocking, "
        "manual future Top20 dates, or post-event-derived pre-event labels are used.",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    missing = [path.as_posix() for path in INPUTS if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))
    hashes = {path.as_posix(): sha256(root / path) for path in INPUTS if path != PRICE}
    prior_stage_paths = sorted({
        path
        for prefix in ("v21_096*", "v21_097*", "v21_098*", "v21_099*")
        for path in (root / OUT).glob(prefix)
        if path.is_file()
    })
    prior_stage_hashes = {
        path.relative_to(root).as_posix(): sha256(path) for path in prior_stage_paths
    }
    d_before = sha256(root / D_BASELINE)
    before = protected_snapshot(root, output_paths)

    master = pd.read_csv(root / MASTER, low_memory=False)
    returns = pd.read_csv(root / RETURNS, low_memory=False)
    impact = pd.read_csv(root / IMPACT, low_memory=False)
    vulnerability = pd.read_csv(root / VULNERABILITY, low_memory=False)
    dashboard = pd.read_csv(root / DASHBOARD, low_memory=False)
    buckets = pd.read_csv(root / BUCKETS, low_memory=False)
    policies = pd.read_csv(root / POLICIES, low_memory=False)
    summaries = [
        json.loads((root / path).read_text(encoding="utf-8"))
        for path in (SUMMARY_096, SUMMARY_097, SUMMARY_098)
    ]
    master_map = master.set_index("event_id")
    usable_master = returns["event_id"].map(
        master_map["historical_event_occurrence_usable"].map(truth)
    ).fillna(False)
    pit = returns["event_id"].map(master_map["pit_certified"].map(truth)).fillna(False)
    price_ok = ~returns["price_missing_flag"].map(truth)
    usable = returns[usable_master & pit & price_ok].copy().reset_index(drop=True)
    checks = [
        ("v21_096_master_exists", (root / MASTER).is_file(), len(master)),
        ("v21_097_returns_exist", (root / RETURNS).is_file(), len(returns)),
        ("v21_097_impact_exists", len(impact) > 0, len(impact)),
        ("v21_097_vulnerability_exists", len(vulnerability) > 0, len(vulnerability)),
        ("v21_097_dashboard_exists", len(dashboard) > 0, len(dashboard)),
        ("v21_098_buckets_exist", len(buckets) > 0, len(buckets)),
        ("v21_098_policy_variants_exist", len(policies) > 0, len(policies)),
        ("event_rows_pit_certified", bool(pit.all()), int(pit.sum())),
        ("historical_occurrence_usable_rows_exist", len(usable) > 0, len(usable)),
        ("historical_pre_event_random_backtest_blocked", all(s.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False for s in summaries), ""),
        ("price_coverage_exists", bool(price_ok.any()), int(price_ok.sum())),
        ("pit_leakage_warnings_zero", sum(int(s.get("PIT_LEAKAGE_WARNINGS", 0)) for s in summaries) == 0, ""),
        ("d_baseline_hash_available", bool(d_before), d_before),
    ]
    validation_rows = pd.DataFrame(checks, columns=["check_name", "passed", "detail"])
    validation = {
        "stage": "V21.100-R1_INPUT_VALIDATION",
        "status": "PASS" if validation_rows["passed"].all() else "FAIL",
        "event_rows_loaded": len(returns), "event_rows_usable": len(usable),
        "event_rows_pit_certified": int(pit.sum()),
        "price_covered_rows": int(price_ok.sum()),
        "historical_pre_event_random_backtest_allowed": False,
        "pit_leakage_warnings": sum(int(s.get("PIT_LEAKAGE_WARNINGS", 0)) for s in summaries),
        "risk_primitive_aggregation_method": "LEAVE_ONE_EVENT_OUT_CURRENT_UNIVERSE_DIAGNOSTIC",
        "current_universe_diagnostic_only": True,
        "d_baseline_sha256_before": d_before, "research_only": True,
        "official_adoption_allowed": False,
    }
    validation_rows.to_csv(out / OUTPUTS[0], index=False)

    primitives = build_primitives(master, usable)
    primitives.to_csv(out / OUTPUTS[2], index=False)
    grid = variants()
    grid.to_csv(out / OUTPUTS[3], index=False)
    scores = score_rows(primitives, grid)
    scores.to_csv(out / OUTPUTS[4], index=False)
    results = backtest(scores, usable)
    results.to_csv(out / OUTPUTS[5], index=False)
    skip = {
        "OPTIONAL_PIT_PORTFOLIO_BACKTEST_RUN": False,
        "skip_reason": "HISTORICAL_PIT_D_RANKING_SNAPSHOTS_NOT_AVAILABLE",
        "detail": "Only isolated/current ranking snapshots were found; no PIT historical D ranking sequence suitable for portfolio simulation.",
        "research_only": True, "official_adoption_allowed": False,
    }
    write_json(out / OUTPUTS[6], skip)
    variant_summary = summarize(results)
    variant_summary.to_csv(out / OUTPUTS[7], index=False)
    price_map = load_price_map(root, set(primitives["ticker"].astype(str).str.upper()))
    robust = robustness(primitives, usable, grid, variant_summary, price_map)
    robust.to_csv(out / OUTPUTS[8], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_after = sha256(root / D_BASELINE)
    d_preserved = d_after == d_before
    inputs_preserved = all(sha256(root / Path(path)) == digest for path, digest in hashes.items())
    prior_stages_preserved = all(
        path.is_file() and sha256(path) == digest
        for relative, digest in prior_stage_hashes.items()
        for path in [root / relative]
    )
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    protected_modified = bool(
        changed or not d_preserved or not inputs_preserved or not prior_stages_preserved
    )
    validation.update({
        "d_baseline_sha256_after": d_after, "d_baseline_preserved": d_preserved,
        "input_ledgers_preserved": inputs_preserved,
        "v21_096_through_v21_099_artifacts_preserved": prior_stages_preserved,
    })
    if protected_modified or official_changed:
        validation["status"] = "FAIL"
    write_json(out / OUTPUTS[1], validation)

    noncontrol = variant_summary[variant_summary["variant_id"].ne("EVENT_WEIGHT_CONTROL_0")]
    best_left = noncontrol.sort_values(["left_tail_improvement", "net_research_score"]).iloc[-1]
    best_net = noncontrol.sort_values(["net_research_score", "left_tail_improvement"]).iloc[-1]
    placebo_rows = robust[robust["check_name"].str.contains("placebo")]
    placebo_pass = bool(len(placebo_rows) and placebo_rows["check_status"].eq("PASS").all())
    robustness_rows = robust[~robust["check_name"].str.contains("placebo")]
    robustness_pass = bool(len(robustness_rows) and robustness_rows["check_status"].eq("PASS").all())
    severe_reduction = bool(noncontrol["severe_loss_count_scaled"].lt(noncontrol["severe_loss_count_baseline"]).any())
    missed_risk = bool(noncontrol["missed_large_winner_count"].gt(0).any())
    pit_warnings = int(validation["pit_leakage_warnings"])
    if pit_warnings:
        decision = "REJECT_EVENT_WEIGHT_BACKTEST_DUE_TO_PIT_LEAKAGE"
    elif protected_modified or official_changed:
        decision = "REJECT_EVENT_WEIGHT_BACKTEST_DUE_TO_PROTECTED_MUTATION"
    elif usable.empty:
        decision = "EVENT_WEIGHT_BACKTEST_BLOCKED_NO_USABLE_EVENTS"
    elif float(best_left["left_tail_improvement"]) <= 0:
        decision = "EVENT_WEIGHT_NO_LEFT_TAIL_EDGE_RESEARCH_ONLY"
    elif float(best_net["net_research_score"]) <= 0:
        decision = "EVENT_WEIGHT_REJECTED_DUE_TO_MISSED_UPSIDE_RESEARCH_ONLY"
    elif placebo_pass and robustness_pass:
        decision = "EVENT_WEIGHT_PROMISING_RESEARCH_ONLY_FORWARD_VALIDATION_REQUIRED"
    else:
        decision = "EVENT_WEIGHT_NO_LEFT_TAIL_EDGE_RESEARCH_ONLY"
    summary = {
        "FINAL_STATUS": "PASS" if validation["status"] == "PASS" and not pit_warnings and not protected_modified else "FAIL",
        "DECISION": decision, "EVENT_ROWS_LOADED": len(returns),
        "EVENT_ROWS_USABLE": len(usable), "WEIGHT_VARIANTS_TESTED": len(grid),
        "EVENT_ROW_BACKTEST_ROWS": len(results),
        "OPTIONAL_PIT_PORTFOLIO_BACKTEST_RUN": False,
        "CURRENT_UNIVERSE_DIAGNOSTIC_ONLY": True,
        "OFFICIAL_HISTORICAL_STRATEGY_BACKTEST_RUN": False,
        "BEST_LEFT_TAIL_VARIANT": best_left["variant_id"],
        "BEST_NET_SCORE_VARIANT": best_net["variant_id"],
        "SEVERE_LOSS_REDUCTION_OBSERVED": severe_reduction,
        "MISSED_UPSIDE_RISK_OBSERVED": missed_risk,
        "PLACEBO_CHECK_PASSED": placebo_pass,
        "ROBUSTNESS_CHECK_PASSED": robustness_pass,
        "HISTORICAL_EVENT_OCCURRENCE_BACKTEST_ALLOWED": True,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "FORWARD_POLICY_OBSERVATION_ALLOWED": True,
        "EVENT_WEIGHT_RESEARCH_ALLOWED": True,
        "OFFICIAL_EVENT_WEIGHT_ADOPTION_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "RECOMMENDED_NEXT_STAGE": "V21.101_EVENT_WEIGHT_FORWARD_VALIDATION_OR_PRIMITIVE_RECALIBRATION",
    }
    write_json(out / OUTPUTS[10], summary)
    (out / OUTPUTS[9]).write_text(report(summary), encoding="utf-8")
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
