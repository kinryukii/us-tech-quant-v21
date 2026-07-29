#!/usr/bin/env python
r"""
V22.060 FAST3 VIX change-magnitude risk scaling and exit capture study R1.

This is an existing-result study. It does not reread the 582 ETF Canonical
partitions and does not regenerate entry signals.

Inputs
------
- V22.059 summary and trade records.
- Official Cboe daily VIX history produced by V22.056.

Frozen questions
----------------
1. Does scaling risk by the absolute magnitude of the prior-day VIX change
   improve drawdown and return/drawdown characteristics without changing the
   entry signal?
2. Do the current dynamic exits destroy value relative to an exactly matched
   fixed 60-minute exit?
3. Does retaining only the hard stop and otherwise holding to 60 minutes
   improve results?
4. How often do hard-stop trades recover by the matched 60-minute horizon?

No threshold sweep is performed.

Frozen VIX magnitude risk schedule
----------------------------------
absolute prior-day VIX change percentile < 80%  -> 1.00x current risk
80% <= percentile < 95%                         -> 0.50x current risk
percentile >= 95%                               -> 0.00x current risk

Frozen exit variants
--------------------
DYNAMIC_EXIT:
    Actual V22.059 exit.
FIXED_60M_EXIT:
    Same entry and position weight, exit at the precomputed 60-minute price.
HYBRID_HARD_STOP_THEN_60M:
    Preserve actual HARD_STOP exits; all other trades use the 60-minute exit.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


VERSION = (
    "V22.060_FAST3_VIX_CHANGE_MAGNITUDE_RISK_"
    "AND_EXIT_CAPTURE_STUDY_R1"
)

SOURCE_VARIANT = "NO_VIX_CONTROL"
DEVELOPMENT = "2018-2022_DEVELOPMENT"
VALIDATION = "2023-2024_VALIDATION"
CONFIRMATION = "2025-2026_YTD_CONFIRMATION"
PERIODS = (DEVELOPMENT, VALIDATION, CONFIRMATION)

CONTROL_RISK = "CONTROL_FIXED_RISK"
MAGNITUDE_SCALER = "VIX_CHANGE_MAGNITUDE_SCALER"
RISK_VARIANTS = (CONTROL_RISK, MAGNITUDE_SCALER)

DYNAMIC_EXIT = "DYNAMIC_EXIT"
FIXED_60M_EXIT = "FIXED_60M_EXIT"
HYBRID_EXIT = "HYBRID_HARD_STOP_THEN_60M"
EXIT_VARIANTS = (DYNAMIC_EXIT, FIXED_60M_EXIT, HYBRID_EXIT)

ABS_PCTL_FULL_RISK = 0.80
ABS_PCTL_HALF_RISK = 0.95
PIT_WINDOW = 252


class StudyError(RuntimeError):
    """V22.060 cannot continue safely."""


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise StudyError(f"{name} missing required columns: {missing}")


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
    )


def validate_v22_059(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_VIX_CHANGE_RATE_CANDIDATE_QUALIFIED",
        "v22_058_validated": True,
        "v22_058a_validated": True,
        "v22_056_validated": True,
        "vix_mode": "PRIOR_DAY_CHANGE_RATE_ONLY_FOR_RATE_VARIANTS",
        "vix_absolute_level_core_used": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "kdj_entry_used": False,
        "kdj_exit_used": False,
        "old_level_candidate_reproduction_pass": True,
        "old_level_trade_reproduction_pass": True,
        "parameter_sweep_executed": False,
        "entry_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise StudyError(
            "V22.059 lineage validation failed: " + "; ".join(failures)
        )

    trade_counts = summary.get("trade_count_by_variant", {})
    if int(trade_counts.get(SOURCE_VARIANT, -1)) <= 0:
        raise StudyError(
            f"Missing positive V22.059 trade count for {SOURCE_VARIANT}"
        )


def validate_v22_059a(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "source_v22_059_validated": True,
        "hard_entry_gate_supported": False,
        "risk_overlay_candidate": True,
        "recommended_vix_role": "RISK_SCALER_ONLY",
        "canonical_partition_count_read": 0,
        "backtest_executed": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise StudyError(
            "V22.059A lineage validation failed: " + "; ".join(failures)
        )


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def maximum_drawdown(daily_returns: pd.Series) -> float:
    clean = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    peaks = nav.cummax()
    return float((nav / peaks - 1.0).min())


def cumulative_return(daily_returns: pd.Series) -> float:
    clean = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    return float(np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0)


def return_to_drawdown(
    cumulative: float,
    max_drawdown_value: float,
) -> float:
    if not np.isfinite(cumulative):
        return math.nan
    if not np.isfinite(max_drawdown_value) or max_drawdown_value >= 0:
        return math.nan
    return cumulative / abs(max_drawdown_value)


def worst_loss_sum(values: pd.Series, count: int = 5) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    negative = clean.loc[clean < 0].sort_values()
    if negative.empty:
        return 0.0
    return float(-negative.head(count).sum())


def prior_absolute_rate_percentile(
    close: pd.Series,
    window: int = PIT_WINDOW,
) -> tuple[pd.Series, pd.Series]:
    values = pd.to_numeric(close, errors="raise").to_numpy(dtype=float)
    rate = np.full(len(values), np.nan, dtype=float)
    abs_percentile = np.full(len(values), np.nan, dtype=float)

    for index in range(1, len(values)):
        if values[index - 1] > 0 and np.isfinite(values[index]):
            rate[index] = values[index] / values[index - 1] - 1.0

    absolute = np.abs(rate)
    for index in range(window + 1, len(values)):
        current = absolute[index]
        history = absolute[index - window : index]
        if np.isfinite(current) and np.isfinite(history).all():
            abs_percentile[index] = float(np.mean(history <= current))

    return (
        pd.Series(rate, index=close.index, dtype=float),
        pd.Series(abs_percentile, index=close.index, dtype=float),
    )


def build_vix_trade_date_features(vix_daily: pd.DataFrame) -> pd.DataFrame:
    frame = vix_daily.copy()
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    require_columns(frame, ["DATE", "CLOSE"], "official VIX daily")

    frame["DATE"] = pd.to_datetime(frame["DATE"], errors="raise")
    frame["CLOSE"] = pd.to_numeric(frame["CLOSE"], errors="raise")
    frame = (
        frame.sort_values("DATE", kind="mergesort")
        .drop_duplicates("DATE", keep=False)
        .reset_index(drop=True)
    )
    if len(frame) < 7000:
        raise StudyError(
            f"Official VIX daily history unexpectedly short: {len(frame)}"
        )
    if (frame["CLOSE"] <= 0).any():
        raise StudyError("Official VIX CLOSE contains non-positive values")

    rate_1d, abs_pctl = prior_absolute_rate_percentile(frame["CLOSE"])
    frame["vix_rate_1d"] = rate_1d
    frame["vix_abs_rate_pctl_252"] = abs_pctl

    # At trade date t, use the VIX change observed at the previous VIX session.
    feature = pd.DataFrame(
        {
            "trade_date": frame["DATE"].shift(-1),
            "vix_source_date": frame["DATE"],
            "vix_rate_1d_prior_rebuilt": frame["vix_rate_1d"],
            "vix_abs_rate_pctl_252_prior": frame[
                "vix_abs_rate_pctl_252"
            ],
        }
    )
    feature = feature.dropna(subset=["trade_date"]).copy()
    feature["trade_date"] = feature["trade_date"].dt.strftime("%Y-%m-%d")
    feature["vix_source_date"] = feature[
        "vix_source_date"
    ].dt.strftime("%Y-%m-%d")
    return feature


def risk_scale(percentile: float) -> float:
    if not np.isfinite(percentile):
        return math.nan
    if percentile < ABS_PCTL_FULL_RISK:
        return 1.0
    if percentile < ABS_PCTL_HALF_RISK:
        return 0.5
    return 0.0


def normalize_source_trades(
    trades: pd.DataFrame,
    vix_features: pd.DataFrame,
) -> pd.DataFrame:
    required = [
        "variant",
        "study_period",
        "calendar_year",
        "trade_date",
        "direction",
        "execution_symbol",
        "exit_reason",
        "holding_minutes",
        "position_weight",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "vix_rate_1d_prior",
        "entry_signal_60m_net_return",
        "pit_baseline_eligible_60m",
        "entry_excess_pit_60m",
    ]
    require_columns(trades, required, "V22.059 trades")

    source = trades.loc[
        trades["variant"] == SOURCE_VARIANT
    ].copy()
    if source.empty:
        raise StudyError(f"No source trades for {SOURCE_VARIANT}")

    numeric_columns = [
        "calendar_year",
        "holding_minutes",
        "position_weight",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "vix_rate_1d_prior",
        "entry_signal_60m_net_return",
        "entry_excess_pit_60m",
    ]
    for column in numeric_columns:
        source[column] = pd.to_numeric(source[column], errors="coerce")
    source["pit_baseline_eligible_60m"] = as_bool(
        source["pit_baseline_eligible_60m"]
    )
    source["trade_date"] = pd.to_datetime(
        source["trade_date"], errors="raise"
    ).dt.strftime("%Y-%m-%d")

    source = source.merge(
        vix_features,
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    missing = int(
        source["vix_abs_rate_pctl_252_prior"].isna().sum()
    )
    if missing:
        raise StudyError(
            f"Missing rebuilt VIX absolute-rate percentile for {missing} trades"
        )

    comparable = source[
        ["vix_rate_1d_prior", "vix_rate_1d_prior_rebuilt"]
    ].dropna()
    if comparable.empty:
        raise StudyError("No VIX rate rows available for lineage validation")
    maximum_difference = float(
        (
            comparable["vix_rate_1d_prior"]
            - comparable["vix_rate_1d_prior_rebuilt"]
        )
        .abs()
        .max()
    )
    if maximum_difference > 1e-9:
        raise StudyError(
            "Rebuilt VIX prior-day rate does not match V22.059: "
            f"max_abs_difference={maximum_difference}"
        )

    source["vix_magnitude_risk_scale"] = [
        risk_scale(value)
        for value in source["vix_abs_rate_pctl_252_prior"]
    ]
    source["matched_60m_available"] = (
        source["entry_signal_60m_net_return"].notna()
    )
    return source.sort_values(
        ["trade_date", "direction", "execution_symbol"],
        kind="mergesort",
    ).reset_index(drop=True)


def build_risk_variant_trades(source: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []

    control = source.copy()
    control["risk_variant"] = CONTROL_RISK
    control["risk_scale"] = 1.0
    control["scaled_position_weight"] = control["position_weight"]
    control["scaled_account_trade_return"] = control[
        "account_trade_return"
    ]
    rows.append(control)

    scaled = source.copy()
    scaled["risk_variant"] = MAGNITUDE_SCALER
    scaled["risk_scale"] = scaled["vix_magnitude_risk_scale"]
    scaled["scaled_position_weight"] = (
        scaled["position_weight"] * scaled["risk_scale"]
    )
    scaled["scaled_account_trade_return"] = (
        scaled["account_trade_return"] * scaled["risk_scale"]
    )
    rows.append(scaled)

    return pd.concat(rows, ignore_index=True, sort=False)


def build_exit_variant_trades(source: pd.DataFrame) -> pd.DataFrame:
    matched = source.loc[source["matched_60m_available"]].copy()
    if matched.empty:
        raise StudyError("No matched 60-minute source trades")

    rows: list[pd.DataFrame] = []
    for variant in EXIT_VARIANTS:
        frame = matched.copy()
        frame["exit_variant"] = variant

        if variant == DYNAMIC_EXIT:
            instrument = frame["instrument_net_return"]
        elif variant == FIXED_60M_EXIT:
            instrument = frame["entry_signal_60m_net_return"]
        elif variant == HYBRID_EXIT:
            instrument = np.where(
                frame["exit_reason"].eq("HARD_STOP"),
                frame["instrument_net_return"],
                frame["entry_signal_60m_net_return"],
            )
            instrument = pd.Series(instrument, index=frame.index)
        else:
            raise StudyError(f"Unknown exit variant: {variant}")

        frame["exit_variant_instrument_return"] = pd.to_numeric(
            instrument, errors="coerce"
        )
        frame["exit_variant_account_return"] = (
            frame["position_weight"]
            * frame["exit_variant_instrument_return"]
        )
        rows.append(frame)

    return pd.concat(rows, ignore_index=True, sort=False)


def daily_returns(
    frame: pd.DataFrame,
    variant_column: str,
    return_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(
        [variant_column, "study_period", "trade_date"],
        sort=True,
    ):
        variant, period, trade_date = keys
        values = pd.to_numeric(
            group[return_column], errors="coerce"
        ).dropna()
        daily_return = (
            float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)
            if len(values)
            else 0.0
        )
        rows.append(
            {
                variant_column: variant,
                "study_period": period,
                "trade_date": trade_date,
                "calendar_year": int(str(trade_date)[:4]),
                "event_count": int(len(group)),
                "daily_return": daily_return,
            }
        )
    return pd.DataFrame(rows)


def summarize_risk_periods(
    risk_trades: pd.DataFrame,
    risk_daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in RISK_VARIANTS:
        for period in PERIODS:
            trades = risk_trades.loc[
                (risk_trades["risk_variant"] == variant)
                & (risk_trades["study_period"] == period)
            ]
            daily = risk_daily.loc[
                (risk_daily["risk_variant"] == variant)
                & (risk_daily["study_period"] == period)
            ]
            if trades.empty or daily.empty:
                continue

            account = trades["scaled_account_trade_return"]
            cumulative = cumulative_return(daily["daily_return"])
            mdd = maximum_drawdown(daily["daily_return"])
            rows.append(
                {
                    "risk_variant": variant,
                    "study_period": period,
                    "signal_event_count": int(len(trades)),
                    "active_risk_trade_count": int(
                        (trades["risk_scale"] > 0).sum()
                    ),
                    "zero_risk_event_count": int(
                        (trades["risk_scale"] == 0).sum()
                    ),
                    "half_risk_event_count": int(
                        (trades["risk_scale"] == 0.5).sum()
                    ),
                    "mean_risk_scale": float(
                        trades["risk_scale"].mean()
                    ),
                    "mean_scaled_account_return": float(account.mean()),
                    "median_scaled_account_return": float(
                        account.median()
                    ),
                    "positive_account_rate": float(
                        (account > 0).mean()
                    ),
                    "profit_factor": profit_factor(account),
                    "cumulative_return": cumulative,
                    "max_drawdown": mdd,
                    "return_to_drawdown": return_to_drawdown(
                        cumulative, mdd
                    ),
                    "worst_5_account_loss_sum": worst_loss_sum(
                        account, 5
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_risk_years(
    risk_trades: pd.DataFrame,
    risk_daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, daily in risk_daily.groupby(
        ["risk_variant", "calendar_year"],
        sort=True,
    ):
        variant, year = keys
        trades = risk_trades.loc[
            (risk_trades["risk_variant"] == variant)
            & (risk_trades["calendar_year"] == year)
        ]
        cumulative = cumulative_return(daily["daily_return"])
        mdd = maximum_drawdown(daily["daily_return"])
        rows.append(
            {
                "risk_variant": variant,
                "calendar_year": int(year),
                "trade_event_count": int(len(trades)),
                "active_risk_trade_count": int(
                    (trades["risk_scale"] > 0).sum()
                ),
                "cumulative_return": cumulative,
                "max_drawdown": mdd,
                "return_to_drawdown": return_to_drawdown(
                    cumulative, mdd
                ),
                "profit_factor": profit_factor(
                    trades["scaled_account_trade_return"]
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_exit_periods(
    exit_trades: pd.DataFrame,
    exit_daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        for period in PERIODS:
            trades = exit_trades.loc[
                (exit_trades["exit_variant"] == variant)
                & (exit_trades["study_period"] == period)
            ]
            daily = exit_daily.loc[
                (exit_daily["exit_variant"] == variant)
                & (exit_daily["study_period"] == period)
            ]
            if trades.empty or daily.empty:
                continue
            instrument = trades[
                "exit_variant_instrument_return"
            ]
            account = trades["exit_variant_account_return"]
            cumulative = cumulative_return(daily["daily_return"])
            mdd = maximum_drawdown(daily["daily_return"])
            rows.append(
                {
                    "exit_variant": variant,
                    "study_period": period,
                    "matched_trade_count": int(len(trades)),
                    "mean_instrument_return": float(
                        instrument.mean()
                    ),
                    "median_instrument_return": float(
                        instrument.median()
                    ),
                    "positive_rate": float((instrument > 0).mean()),
                    "mean_account_return": float(account.mean()),
                    "profit_factor": profit_factor(account),
                    "cumulative_return": cumulative,
                    "max_drawdown": mdd,
                    "return_to_drawdown": return_to_drawdown(
                        cumulative, mdd
                    ),
                    "worst_5_account_loss_sum": worst_loss_sum(
                        account, 5
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_exit_directions(
    exit_trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = ["exit_variant", "study_period", "direction"]
    for keys, group in exit_trades.groupby(
        columns, sort=True, dropna=False
    ):
        variant, period, direction = keys
        instrument = group["exit_variant_instrument_return"]
        account = group["exit_variant_account_return"]
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "direction": direction,
                "matched_trade_count": int(len(group)),
                "mean_instrument_return": float(
                    instrument.mean()
                ),
                "median_instrument_return": float(
                    instrument.median()
                ),
                "positive_rate": float((instrument > 0).mean()),
                "profit_factor": profit_factor(account),
                "mean_account_return": float(account.mean()),
            }
        )
    return pd.DataFrame(rows)


def hard_stop_diagnostic(source: pd.DataFrame) -> pd.DataFrame:
    hard = source.loc[
        source["exit_reason"].eq("HARD_STOP")
        & source["matched_60m_available"]
    ].copy()
    if hard.empty:
        return pd.DataFrame()

    hard["fixed_60m_positive"] = (
        hard["entry_signal_60m_net_return"] > 0
    )
    hard["recovered_to_positive_by_60m"] = (
        (hard["instrument_net_return"] < 0)
        & (hard["entry_signal_60m_net_return"] > 0)
    )
    hard["fixed_60m_improvement"] = (
        hard["entry_signal_60m_net_return"]
        - hard["instrument_net_return"]
    )

    rows: list[dict[str, Any]] = []
    for keys, group in hard.groupby(
        ["study_period", "direction"],
        sort=True,
    ):
        period, direction = keys
        rows.append(
            {
                "study_period": period,
                "direction": direction,
                "hard_stop_count": int(len(group)),
                "stop_within_3m_count": int(
                    (group["holding_minutes"] <= 3).sum()
                ),
                "stop_within_3m_rate": float(
                    (group["holding_minutes"] <= 3).mean()
                ),
                "stop_within_5m_count": int(
                    (group["holding_minutes"] <= 5).sum()
                ),
                "stop_within_5m_rate": float(
                    (group["holding_minutes"] <= 5).mean()
                ),
                "mean_dynamic_stop_return": float(
                    group["instrument_net_return"].mean()
                ),
                "mean_fixed_60m_return": float(
                    group["entry_signal_60m_net_return"].mean()
                ),
                "mean_fixed_60m_improvement": float(
                    group["fixed_60m_improvement"].mean()
                ),
                "fixed_60m_positive_rate": float(
                    group["fixed_60m_positive"].mean()
                ),
                "recovered_to_positive_by_60m_rate": float(
                    group["recovered_to_positive_by_60m"].mean()
                ),
                "mean_mfe_before_stop": float(group["mfe"].mean()),
                "mean_mae_before_stop": float(group["mae"].mean()),
                "mean_holding_minutes": float(
                    group["holding_minutes"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def risk_period_lookup(
    summary: pd.DataFrame,
    variant: str,
    period: str,
) -> pd.Series:
    rows = summary.loc[
        (summary["risk_variant"] == variant)
        & (summary["study_period"] == period)
    ]
    if rows.empty:
        raise StudyError(
            f"Missing risk period row: {variant} / {period}"
        )
    return rows.iloc[0]


def exit_period_lookup(
    summary: pd.DataFrame,
    variant: str,
    period: str,
) -> pd.Series:
    rows = summary.loc[
        (summary["exit_variant"] == variant)
        & (summary["study_period"] == period)
    ]
    if rows.empty:
        raise StudyError(
            f"Missing exit period row: {variant} / {period}"
        )
    return rows.iloc[0]


def evaluate_risk_scaler(
    period: pd.DataFrame,
    year: pd.DataFrame,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    risk_metrics_pass = True
    tradable_edge_pass = True

    for study_period in (VALIDATION, CONFIRMATION):
        control = risk_period_lookup(
            period, CONTROL_RISK, study_period
        )
        scaled = risk_period_lookup(
            period, MAGNITUDE_SCALER, study_period
        )
        control_mdd = abs(float(control["max_drawdown"]))
        scaled_mdd = abs(float(scaled["max_drawdown"]))
        mdd_reduction = (
            1.0 - scaled_mdd / control_mdd
            if control_mdd > 0
            else math.nan
        )
        worst_reduction = (
            1.0
            - float(scaled["worst_5_account_loss_sum"])
            / float(control["worst_5_account_loss_sum"])
            if float(control["worst_5_account_loss_sum"]) > 0
            else math.nan
        )
        rdd_improved = (
            float(scaled["return_to_drawdown"])
            > float(control["return_to_drawdown"])
        )

        if (
            not np.isfinite(mdd_reduction)
            or mdd_reduction < 0.30
            or not np.isfinite(worst_reduction)
            or worst_reduction < 0.25
            or not rdd_improved
        ):
            risk_metrics_pass = False

        if (
            float(scaled["cumulative_return"]) <= 0
            or float(scaled["profit_factor"]) <= 1.0
        ):
            tradable_edge_pass = False

        comparisons.append(
            {
                "study_period": study_period,
                "control_cumulative_return": float(
                    control["cumulative_return"]
                ),
                "scaled_cumulative_return": float(
                    scaled["cumulative_return"]
                ),
                "control_max_drawdown": float(
                    control["max_drawdown"]
                ),
                "scaled_max_drawdown": float(
                    scaled["max_drawdown"]
                ),
                "max_drawdown_reduction": mdd_reduction,
                "control_return_to_drawdown": float(
                    control["return_to_drawdown"]
                ),
                "scaled_return_to_drawdown": float(
                    scaled["return_to_drawdown"]
                ),
                "return_to_drawdown_improved": bool(rdd_improved),
                "worst_5_loss_reduction": worst_reduction,
                "scaled_profit_factor": float(
                    scaled["profit_factor"]
                ),
            }
        )

    scaled_years = year.loc[
        year["risk_variant"] == MAGNITUDE_SCALER
    ].copy()
    positive = scaled_years.loc[
        scaled_years["cumulative_return"] > 0,
        "cumulative_return",
    ]
    single_year_share = (
        float(positive.max() / positive.sum())
        if len(positive) and float(positive.sum()) > 0
        else math.nan
    )
    year_concentration_pass = bool(
        np.isfinite(single_year_share)
        and single_year_share <= 0.60
    )
    tradable_edge_pass = bool(
        tradable_edge_pass and year_concentration_pass
    )

    return {
        "risk_comparison": pd.DataFrame(comparisons),
        "risk_metrics_pass": bool(risk_metrics_pass),
        "tradable_edge_pass": bool(tradable_edge_pass),
        "single_positive_year_profit_share": single_year_share,
        "year_concentration_pass": year_concentration_pass,
    }


def evaluate_exit_variants(
    period: pd.DataFrame,
) -> dict[str, Any]:
    comparison_rows: list[dict[str, Any]] = []
    supported: list[str] = []

    for candidate in (FIXED_60M_EXIT, HYBRID_EXIT):
        candidate_pass = True
        for study_period in (VALIDATION, CONFIRMATION):
            dynamic = exit_period_lookup(
                period, DYNAMIC_EXIT, study_period
            )
            tested = exit_period_lookup(
                period, candidate, study_period
            )
            mean_improvement = (
                float(tested["mean_account_return"])
                - float(dynamic["mean_account_return"])
            )
            pf_improved = (
                float(tested["profit_factor"])
                > float(dynamic["profit_factor"])
            )
            cumulative_improved = (
                float(tested["cumulative_return"])
                > float(dynamic["cumulative_return"])
            )
            dynamic_mdd = abs(float(dynamic["max_drawdown"]))
            tested_mdd = abs(float(tested["max_drawdown"]))
            mdd_not_materially_worse = (
                tested_mdd <= dynamic_mdd * 1.20
            )
            positive_edge = (
                float(tested["mean_account_return"]) > 0
                and float(tested["profit_factor"]) > 1.0
            )

            if not (
                mean_improvement > 0
                and pf_improved
                and cumulative_improved
                and mdd_not_materially_worse
                and positive_edge
            ):
                candidate_pass = False

            comparison_rows.append(
                {
                    "exit_variant": candidate,
                    "study_period": study_period,
                    "dynamic_mean_account_return": float(
                        dynamic["mean_account_return"]
                    ),
                    "candidate_mean_account_return": float(
                        tested["mean_account_return"]
                    ),
                    "mean_account_return_improvement": mean_improvement,
                    "dynamic_profit_factor": float(
                        dynamic["profit_factor"]
                    ),
                    "candidate_profit_factor": float(
                        tested["profit_factor"]
                    ),
                    "profit_factor_improved": bool(pf_improved),
                    "dynamic_cumulative_return": float(
                        dynamic["cumulative_return"]
                    ),
                    "candidate_cumulative_return": float(
                        tested["cumulative_return"]
                    ),
                    "dynamic_max_drawdown": float(
                        dynamic["max_drawdown"]
                    ),
                    "candidate_max_drawdown": float(
                        tested["max_drawdown"]
                    ),
                    "max_drawdown_not_materially_worse": bool(
                        mdd_not_materially_worse
                    ),
                    "positive_edge": bool(positive_edge),
                }
            )
        if candidate_pass:
            supported.append(candidate)

    preferred = None
    if supported:
        confirmation_rows = period.loc[
            (period["exit_variant"].isin(supported))
            & (period["study_period"] == CONFIRMATION)
        ].sort_values(
            ["return_to_drawdown", "profit_factor"],
            ascending=False,
        )
        preferred = str(
            confirmation_rows.iloc[0]["exit_variant"]
        )

    return {
        "exit_comparison": pd.DataFrame(comparison_rows),
        "supported_exit_variants": supported,
        "preferred_exit_variant": preferred,
    }


def evaluate_hard_stops(
    diagnostic: pd.DataFrame,
) -> dict[str, Any]:
    recent = diagnostic.loc[
        diagnostic["study_period"].isin(
            [VALIDATION, CONFIRMATION]
        )
    ]
    if recent.empty:
        return {
            "hard_stop_capture_problem": False,
            "minimum_stop_within_5m_rate": math.nan,
            "minimum_recovery_rate": math.nan,
        }

    minimum_stop_5m = float(
        recent["stop_within_5m_rate"].min()
    )
    minimum_recovery = float(
        recent["recovered_to_positive_by_60m_rate"].min()
    )
    capture_problem = bool(
        (
            (recent["mean_fixed_60m_improvement"] > 0)
            & (
                recent["recovered_to_positive_by_60m_rate"]
                >= 0.30
            )
        ).all()
    )
    return {
        "hard_stop_capture_problem": capture_problem,
        "minimum_stop_within_5m_rate": minimum_stop_5m,
        "minimum_recovery_rate": minimum_recovery,
    }


def choose_decision(
    risk_eval: Mapping[str, Any],
    exit_eval: Mapping[str, Any],
    stop_eval: Mapping[str, Any],
) -> dict[str, Any]:
    preferred_exit = exit_eval["preferred_exit_variant"]

    if preferred_exit is not None:
        return {
            "final_decision": (
                f"{preferred_exit}_SUPPORTED_FOR_"
                "INDEPENDENT_REPLICATION"
            ),
            "recommended_risk_role": (
                "VIX_MAGNITUDE_SCALER_RETAINED_AS_SECONDARY"
                if risk_eval["risk_metrics_pass"]
                else "VIX_MAGNITUDE_SCALER_NOT_SUPPORTED"
            ),
            "recommended_exit_variant": preferred_exit,
            "next_stage": (
                "V22.061_FAST3_EXIT_ARCHITECTURE_REPLICATION_R1"
            ),
        }

    if (
        risk_eval["risk_metrics_pass"]
        and risk_eval["tradable_edge_pass"]
    ):
        return {
            "final_decision": (
                "VIX_MAGNITUDE_RISK_SCALER_SUPPORTED_"
                "FOR_INDEPENDENT_REPLICATION"
            ),
            "recommended_risk_role": "RISK_SCALER",
            "recommended_exit_variant": None,
            "next_stage": (
                "V22.061_FAST3_VIX_MAGNITUDE_"
                "RISK_SCALER_REPLICATION_R1"
            ),
        }

    if risk_eval["risk_metrics_pass"]:
        next_stage = (
            "V22.061_FAST3_ENTRY_TIMING_AND_"
            "STOP_MECHANICS_AUDIT_R1"
            if stop_eval["hard_stop_capture_problem"]
            else "STOP_CURRENT_FAST3_ENTRY_ARCHITECTURE"
        )
        return {
            "final_decision": (
                "VIX_MAGNITUDE_SCALER_REDUCES_RISK_"
                "BUT_NO_TRADABLE_EDGE"
            ),
            "recommended_risk_role": "DIAGNOSTIC_RISK_OVERLAY_ONLY",
            "recommended_exit_variant": None,
            "next_stage": next_stage,
        }

    if stop_eval["hard_stop_capture_problem"]:
        return {
            "final_decision": (
                "HARD_STOP_AND_EXIT_CAPTURE_PROBLEM_"
                "REQUIRES_MECHANICS_AUDIT"
            ),
            "recommended_risk_role": (
                "VIX_MAGNITUDE_SCALER_NOT_SUPPORTED"
            ),
            "recommended_exit_variant": None,
            "next_stage": (
                "V22.061_FAST3_ENTRY_TIMING_AND_"
                "STOP_MECHANICS_AUDIT_R1"
            ),
        }

    return {
        "final_decision": (
            "NO_RISK_SCALER_OR_EXIT_ARCHITECTURE_QUALIFIED"
        ),
        "recommended_risk_role": (
            "VIX_MAGNITUDE_DIAGNOSTIC_ONLY"
        ),
        "recommended_exit_variant": None,
        "next_stage": "STOP_CURRENT_FAST3_ENTRY_ARCHITECTURE",
    }


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_scaled_account_return",
        "median_scaled_account_return",
        "mean_instrument_return",
        "median_instrument_return",
        "mean_account_return",
        "control_cumulative_return",
        "scaled_cumulative_return",
        "dynamic_mean_account_return",
        "candidate_mean_account_return",
        "mean_account_return_improvement",
        "dynamic_cumulative_return",
        "candidate_cumulative_return",
        "mean_dynamic_stop_return",
        "mean_fixed_60m_return",
        "mean_fixed_60m_improvement",
        "mean_mfe_before_stop",
        "mean_mae_before_stop",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_account_rate",
        "positive_rate",
        "cumulative_return",
        "max_drawdown",
        "control_max_drawdown",
        "scaled_max_drawdown",
        "max_drawdown_reduction",
        "worst_5_loss_reduction",
        "dynamic_max_drawdown",
        "candidate_max_drawdown",
        "stop_within_3m_rate",
        "stop_within_5m_rate",
        "fixed_60m_positive_rate",
        "recovered_to_positive_by_60m_rate",
    }:
        return f"{float(value) * 100:.2f}"
    if column in {"profit_factor", "scaled_profit_factor"}:
        numeric = float(value)
        return "INF" if np.isinf(numeric) else f"{numeric:.3f}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.3f}"
    return str(value)


def print_table(title: str, frame: pd.DataFrame) -> None:
    print()
    print(f"========== {title} ==========")
    if frame.empty:
        print("NO_ROWS")
        return
    display = frame.copy()
    for column in display.columns:
        display[column] = [
            format_value(column, value)
            for value in display[column]
        ]
    print(display.to_string(index=False))


def run_study(
    v22_059_root: Path,
    v22_059a_root: Path,
    vix_daily_path: Path,
    result_dir: Path,
) -> dict[str, Any]:
    summary_059_path = v22_059_root / "v22_059_summary.json"
    trades_path = v22_059_root / "v22_059_trades.csv"
    summary_059a_path = v22_059a_root / "v22_059a_summary.json"

    for path in [
        summary_059_path,
        trades_path,
        summary_059a_path,
        vix_daily_path,
    ]:
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    summary_059 = json.loads(
        summary_059_path.read_text(encoding="utf-8-sig")
    )
    summary_059a = json.loads(
        summary_059a_path.read_text(encoding="utf-8-sig")
    )
    validate_v22_059(summary_059)
    validate_v22_059a(summary_059a)

    vix_features = build_vix_trade_date_features(
        pd.read_csv(vix_daily_path)
    )
    source = normalize_source_trades(
        pd.read_csv(trades_path),
        vix_features,
    )

    expected_source_count = int(
        summary_059["trade_count_by_variant"][SOURCE_VARIANT]
    )
    if len(source) != expected_source_count:
        raise StudyError(
            "NO_VIX source trade reproduction failed: "
            f"expected {expected_source_count}, got {len(source)}"
        )

    risk_trades = build_risk_variant_trades(source)
    risk_daily = daily_returns(
        risk_trades,
        "risk_variant",
        "scaled_account_trade_return",
    )
    risk_period = summarize_risk_periods(
        risk_trades, risk_daily
    )
    risk_year = summarize_risk_years(
        risk_trades, risk_daily
    )

    exit_trades = build_exit_variant_trades(source)
    exit_daily = daily_returns(
        exit_trades,
        "exit_variant",
        "exit_variant_account_return",
    )
    exit_period = summarize_exit_periods(
        exit_trades, exit_daily
    )
    exit_direction = summarize_exit_directions(exit_trades)
    hard_stops = hard_stop_diagnostic(source)

    worst_hard_stops = (
        source.loc[
            source["exit_reason"].eq("HARD_STOP")
            & source["matched_60m_available"]
        ]
        .assign(
            fixed_60m_improvement=lambda frame: (
                frame["entry_signal_60m_net_return"]
                - frame["instrument_net_return"]
            ),
            recovered_to_positive_by_60m=lambda frame: (
                frame["entry_signal_60m_net_return"] > 0
            ),
        )
        .sort_values(
            "instrument_net_return",
            kind="mergesort",
        )
        .head(25)
        .loc[
            :,
            [
                "trade_date",
                "study_period",
                "direction",
                "execution_symbol",
                "holding_minutes",
                "position_weight",
                "vix_rate_1d_prior",
                "vix_abs_rate_pctl_252_prior",
                "vix_magnitude_risk_scale",
                "instrument_net_return",
                "account_trade_return",
                "entry_signal_60m_net_return",
                "fixed_60m_improvement",
                "recovered_to_positive_by_60m",
                "mfe",
                "mae",
                "exit_reason",
            ],
        ]
        .reset_index(drop=True)
    )

    risk_eval = evaluate_risk_scaler(
        risk_period, risk_year
    )
    exit_eval = evaluate_exit_variants(exit_period)
    stop_eval = evaluate_hard_stops(hard_stops)
    decision = choose_decision(
        risk_eval, exit_eval, stop_eval
    )

    risk_comparison = risk_eval.pop("risk_comparison")
    exit_comparison = exit_eval.pop("exit_comparison")

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "risk_period": result_dir
        / "v22_060_risk_scaling_period_summary.csv",
        "risk_year": result_dir
        / "v22_060_risk_scaling_year_summary.csv",
        "risk_comparison": result_dir
        / "v22_060_risk_scaling_comparison.csv",
        "exit_period": result_dir
        / "v22_060_exit_capture_period_summary.csv",
        "exit_direction": result_dir
        / "v22_060_exit_capture_direction_summary.csv",
        "exit_comparison": result_dir
        / "v22_060_exit_capture_comparison.csv",
        "hard_stops": result_dir
        / "v22_060_hard_stop_diagnostic.csv",
        "worst_hard_stops": result_dir
        / "v22_060_worst_25_hard_stops.csv",
        "source_trades": result_dir
        / "v22_060_source_trade_reconstruction.csv",
        "summary": result_dir / "v22_060_summary.json",
    }

    frames = {
        "risk_period": risk_period,
        "risk_year": risk_year,
        "risk_comparison": risk_comparison,
        "exit_period": exit_period,
        "exit_direction": exit_direction,
        "exit_comparison": exit_comparison,
        "hard_stops": hard_stops,
        "worst_hard_stops": worst_hard_stops,
        "source_trades": source,
    }
    for name, frame in frames.items():
        frame.to_csv(
            outputs[name],
            index=False,
            encoding="utf-8-sig",
        )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "v22_059_validated": True,
        "v22_059a_validated": True,
        "source_variant": SOURCE_VARIANT,
        "source_trade_count": int(len(source)),
        "matched_60m_trade_count": int(
            source["matched_60m_available"].sum()
        ),
        "vix_absolute_magnitude_percentile_window": PIT_WINDOW,
        "full_risk_percentile_upper_exclusive": (
            ABS_PCTL_FULL_RISK
        ),
        "half_risk_percentile_upper_exclusive": (
            ABS_PCTL_HALF_RISK
        ),
        "canonical_partition_count_read": 0,
        "etf_minute_data_read": False,
        "backtest_entry_signal_regenerated": False,
        "parameter_sweep_executed": False,
        "risk_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        **risk_eval,
        **exit_eval,
        **stop_eval,
        **decision,
        "outputs": {
            name: str(path) for name, path in outputs.items()
        },
    }
    write_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.060 VIX magnitude risk + exit capture")
    print("==============================================")

    print_table(
        "VIX变化幅度风险缩放：阶段表现",
        risk_period,
    )
    print_table(
        "VIX变化幅度风险缩放：验证对比",
        risk_comparison,
    )
    print_table(
        "退出架构：阶段表现",
        exit_period,
    )
    print_table(
        "退出架构：Validation / Confirmation 对比",
        exit_comparison,
    )
    print_table(
        "HARD_STOP 恢复诊断",
        hard_stops,
    )
    print_table(
        "最差25笔 HARD_STOP",
        worst_hard_stops,
    )

    print()
    print("========== 自动研究决策 ==========")
    for key in [
        "FINAL_DECISION",
        "RECOMMENDED_RISK_ROLE",
        "RECOMMENDED_EXIT_VARIANT",
        "RISK_METRICS_PASS",
        "TRADABLE_EDGE_PASS",
        "SUPPORTED_EXIT_VARIANTS",
        "HARD_STOP_CAPTURE_PROBLEM",
        "NEXT_STAGE",
    ]:
        print(f"{key}={summary.get(key.lower())}")

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={summary['final_decision']}")
    print(
        f"RECOMMENDED_RISK_ROLE="
        f"{summary['recommended_risk_role']}"
    )
    print(
        f"RECOMMENDED_EXIT_VARIANT="
        f"{summary['recommended_exit_variant']}"
    )
    print("CANONICAL_PARTITION_COUNT_READ=0")
    print("ETF_MINUTE_DATA_READ=False")
    print("BACKTEST_ENTRY_SIGNAL_REGENERATED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"NEXT_STAGE={summary['next_stage']}")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-059-root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.059_FAST3_VIX_CHANGE_RATE_DIRECTION_STUDY_R1"
        ),
    )
    parser.add_argument(
        "--v22-059a-root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.059A_FAST3_VIX_RATE_DIRECTION_ATTRIBUTION_R1"
        ),
    )
    parser.add_argument(
        "--vix-daily",
        default=(
            r"D:\us-tech-quant-data\fast3\vix_cboe_daily"
            r"\canonical\vix_daily.csv"
        ),
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.060_FAST3_VIX_MAGNITUDE_RISK_AND_EXIT_CAPTURE_R1"
        ),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        run_study(
            v22_059_root=Path(args.v22_059_root),
            v22_059a_root=Path(args.v22_059a_root),
            vix_daily_path=Path(args.vix_daily),
            result_dir=Path(args.result_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
