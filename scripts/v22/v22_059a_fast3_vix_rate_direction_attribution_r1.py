#!/usr/bin/env python
r"""
V22.059A FAST3 VIX change-rate direction attribution R1.

This is an existing-result diagnostic. It reads V22.059 CSV/JSON outputs only.

Questions answered
------------------
1. Does falling VIX help LONG and rising VIX help SHORT?
2. Is the effect stable in both Validation and Confirmation?
3. Does VIX change-rate filtering improve entry alpha but lose it through exits?
4. Which VIX states, directions, symbols and exit reasons create tail losses?
5. Should VIX rate remain a hard entry gate, be demoted to a risk overlay,
   or be removed?

No Canonical partition is read. No backtest, parameter sweep, broker action,
paper trading or data mutation is performed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


VERSION = "V22.059A_FAST3_VIX_RATE_DIRECTION_ATTRIBUTION_R1"

NO_VIX = "NO_VIX_CONTROL"
OLD_LEVEL = "OLD_LEVEL_VIX_CONTROL"
RATE_1D = "VIX_RATE_1D"
RATE_1D_3D = "VIX_RATE_1D_3D_CONFIRM"
VARIANTS = (NO_VIX, OLD_LEVEL, RATE_1D, RATE_1D_3D)

DEVELOPMENT = "2018-2022_DEVELOPMENT"
VALIDATION = "2023-2024_VALIDATION"
CONFIRMATION = "2025-2026_YTD_CONFIRMATION"
PERIODS = (DEVELOPMENT, VALIDATION, CONFIRMATION)


class DiagnosticError(RuntimeError):
    """Existing V22.059 results are missing or structurally invalid."""


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DiagnosticError(f"{name} missing required columns: {missing}")


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
        raise DiagnosticError(
            "V22.059 lineage validation failed: " + "; ".join(failures)
        )

    counts = summary.get("trade_count_by_variant", {})
    for variant in VARIANTS:
        if int(counts.get(variant, -1)) < 0:
            raise DiagnosticError(
                f"V22.059 trade count missing for {variant}"
            )


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    peaks = nav.cummax()
    return float((nav / peaks - 1.0).min())


def vix_state(rate_1d: float, rate_3d: float) -> str:
    if not np.isfinite(rate_1d) or not np.isfinite(rate_3d):
        return "MISSING"
    one = "UP" if rate_1d > 0 else "DOWN" if rate_1d < 0 else "FLAT"
    three = "UP" if rate_3d > 0 else "DOWN" if rate_3d < 0 else "FLAT"
    return f"{one}_{three}"


def direction_alignment(
    direction: str,
    rate_1d: float,
    rate_3d: float,
    positive_shock: bool,
) -> str:
    if positive_shock:
        return "POSITIVE_SHOCK"
    if not np.isfinite(rate_1d) or not np.isfinite(rate_3d):
        return "MISSING"

    if direction == "LONG":
        if rate_1d < 0 and rate_3d <= 0:
            return "ALIGNED_1D_3D"
        if rate_1d < 0:
            return "ALIGNED_1D_ONLY"
        if rate_1d > 0 and rate_3d >= 0:
            return "OPPOSED_1D_3D"
        return "MIXED"
    if direction == "SHORT":
        if rate_1d > 0 and rate_3d >= 0:
            return "ALIGNED_1D_3D"
        if rate_1d > 0:
            return "ALIGNED_1D_ONLY"
        if rate_1d < 0 and rate_3d <= 0:
            return "OPPOSED_1D_3D"
        return "MIXED"
    return "UNKNOWN_DIRECTION"


def signed_rate_percentile_bin(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value <= 0.05:
        return "P00_05_EXTREME_DROP"
    if value <= 0.20:
        return "P05_20_DROP"
    if value < 0.50:
        return "P20_50_LOWER"
    if value < 0.80:
        return "P50_80_UPPER"
    if value < 0.95:
        return "P80_95_RISE"
    return "P95_100_EXTREME_RISE"


def normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "variant",
        "study_period",
        "calendar_year",
        "trade_date",
        "direction",
        "execution_symbol",
        "exit_reason",
        "holding_minutes",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "vix_rate_1d_prior",
        "vix_rate_3d_prior",
        "vix_rate_1d_pctl_252_prior",
        "vix_positive_shock_prior",
        "entry_signal_60m_net_return",
        "pit_baseline_eligible_60m",
        "entry_excess_pit_60m",
    ]
    require_columns(frame, required, "V22.059 trades")

    result = frame.copy()
    numeric = [
        "calendar_year",
        "holding_minutes",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "vix_rate_1d_prior",
        "vix_rate_3d_prior",
        "vix_rate_1d_pctl_252_prior",
        "entry_signal_60m_net_return",
        "entry_excess_pit_60m",
    ]
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result["calendar_year"] = result["calendar_year"].astype("Int64")
    result["vix_positive_shock_prior"] = as_bool(
        result["vix_positive_shock_prior"]
    )
    result["pit_baseline_eligible_60m"] = as_bool(
        result["pit_baseline_eligible_60m"]
    )
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.strftime("%Y-%m-%d")

    result["vix_state"] = [
        vix_state(one, three)
        for one, three in zip(
            result["vix_rate_1d_prior"],
            result["vix_rate_3d_prior"],
        )
    ]
    result["vix_direction_alignment"] = [
        direction_alignment(direction, one, three, shock)
        for direction, one, three, shock in zip(
            result["direction"],
            result["vix_rate_1d_prior"],
            result["vix_rate_3d_prior"],
            result["vix_positive_shock_prior"],
        )
    ]
    result["vix_rate_percentile_bin"] = [
        signed_rate_percentile_bin(value)
        for value in result["vix_rate_1d_pctl_252_prior"]
    ]
    result["realized_minus_fixed_60m"] = (
        result["instrument_net_return"]
        - result["entry_signal_60m_net_return"]
    )
    return result.sort_values(
        ["variant", "trade_date", "direction", "execution_symbol"],
        kind="mergesort",
    ).reset_index(drop=True)


def normalize_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "trade_date",
        "study_period",
        "direction",
        "execution_symbol",
        "vix_rate_1d_prior",
        "vix_rate_3d_prior",
        "vix_rate_1d_pctl_252_prior",
        "vix_positive_shock_prior",
    ]
    signal_columns = [
        f"{variant.lower()}_signal" for variant in VARIANTS
    ]
    require_columns(
        frame,
        required + signal_columns,
        "V22.059 candidates",
    )
    result = frame.copy()
    for column in [
        "vix_rate_1d_prior",
        "vix_rate_3d_prior",
        "vix_rate_1d_pctl_252_prior",
    ]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["vix_positive_shock_prior"] = as_bool(
        result["vix_positive_shock_prior"]
    )
    for column in signal_columns:
        result[column] = as_bool(result[column])

    result["vix_state"] = [
        vix_state(one, three)
        for one, three in zip(
            result["vix_rate_1d_prior"],
            result["vix_rate_3d_prior"],
        )
    ]
    result["vix_direction_alignment"] = [
        direction_alignment(direction, one, three, shock)
        for direction, one, three, shock in zip(
            result["direction"],
            result["vix_rate_1d_prior"],
            result["vix_rate_3d_prior"],
            result["vix_positive_shock_prior"],
        )
    ]
    return result


def summarize(group: pd.DataFrame) -> dict[str, Any]:
    instrument = pd.to_numeric(
        group["instrument_net_return"], errors="coerce"
    ).dropna()
    account = pd.to_numeric(
        group["account_trade_return"], errors="coerce"
    ).dropna()
    pit = group.loc[
        group["pit_baseline_eligible_60m"]
        & group["entry_excess_pit_60m"].notna(),
        "entry_excess_pit_60m",
    ]
    signal_60m = pd.to_numeric(
        group["entry_signal_60m_net_return"], errors="coerce"
    ).dropna()
    capture_gap = pd.to_numeric(
        group["realized_minus_fixed_60m"], errors="coerce"
    ).dropna()
    holding = pd.to_numeric(
        group["holding_minutes"], errors="coerce"
    ).dropna()

    count = int(len(group))
    return {
        "trade_count": count,
        "mean_instrument_net_return": (
            float(instrument.mean()) if len(instrument) else np.nan
        ),
        "median_instrument_net_return": (
            float(instrument.median()) if len(instrument) else np.nan
        ),
        "positive_rate": (
            float((instrument > 0).mean()) if len(instrument) else np.nan
        ),
        "profit_factor": profit_factor(account),
        "mean_account_trade_return": (
            float(account.mean()) if len(account) else np.nan
        ),
        "sequential_trade_max_drawdown": maximum_drawdown(account),
        "mean_entry_signal_60m_return": (
            float(signal_60m.mean()) if len(signal_60m) else np.nan
        ),
        "pit_eligible_trade_count": int(len(pit)),
        "mean_entry_excess_pit_60m": (
            float(pit.mean()) if len(pit) else np.nan
        ),
        "mean_realized_minus_fixed_60m": (
            float(capture_gap.mean()) if len(capture_gap) else np.nan
        ),
        "mean_mfe": float(group["mfe"].mean()),
        "mean_mae": float(group["mae"].mean()),
        "mean_holding_minutes": (
            float(holding.mean()) if len(holding) else np.nan
        ),
        "hard_stop_rate": float(
            (group["exit_reason"] == "HARD_STOP").mean()
        ),
        "trailing_protection_rate": float(
            (group["exit_reason"] == "TRAILING_PROTECTION").mean()
        ),
    }


def grouped_summary(
    trades: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        group_columns,
        sort=True,
        dropna=False,
    ):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_columns, keys))
        row.update(summarize(group))
        rows.append(row)
    return pd.DataFrame(rows)


def exit_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = [
        "study_period",
        "direction",
        "vix_direction_alignment",
        "exit_reason",
    ]
    for keys, group in trades.groupby(columns, sort=True, dropna=False):
        period, direction, alignment, reason = keys
        instrument = pd.to_numeric(
            group["instrument_net_return"], errors="coerce"
        ).dropna()
        rows.append(
            {
                "study_period": period,
                "direction": direction,
                "vix_direction_alignment": alignment,
                "exit_reason": reason,
                "trade_count": int(len(group)),
                "mean_instrument_net_return": (
                    float(instrument.mean())
                    if len(instrument)
                    else np.nan
                ),
                "positive_rate": (
                    float((instrument > 0).mean())
                    if len(instrument)
                    else np.nan
                ),
                "profit_factor": profit_factor(
                    group["account_trade_return"]
                ),
                "mean_mfe": float(group["mfe"].mean()),
                "mean_mae": float(group["mae"].mean()),
                "mean_holding_minutes": float(
                    group["holding_minutes"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def tail_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = [
        "study_period",
        "direction",
        "vix_direction_alignment",
    ]
    for keys, group in trades.groupby(columns, sort=True, dropna=False):
        period, direction, alignment = keys
        ordered = group.sort_values(
            "instrument_net_return",
            kind="mergesort",
        )
        worst_count = min(5, len(ordered))
        worst = ordered.head(worst_count)
        remaining = ordered.iloc[worst_count:]

        all_loss = float(
            -ordered.loc[
                ordered["instrument_net_return"] < 0,
                "instrument_net_return",
            ].sum()
        )
        worst_loss = float(
            -worst.loc[
                worst["instrument_net_return"] < 0,
                "instrument_net_return",
            ].sum()
        )
        first = ordered.iloc[0]
        rows.append(
            {
                "study_period": period,
                "direction": direction,
                "vix_direction_alignment": alignment,
                "trade_count": int(len(ordered)),
                "worst_5_loss_share": (
                    worst_loss / all_loss
                    if all_loss > 0
                    else np.nan
                ),
                "mean_net_excluding_worst_5": (
                    float(
                        remaining["instrument_net_return"].mean()
                    )
                    if len(remaining)
                    else np.nan
                ),
                "worst_trade_return": float(
                    first["instrument_net_return"]
                ),
                "worst_trade_date": first["trade_date"],
                "worst_trade_symbol": first["execution_symbol"],
                "worst_trade_exit_reason": first["exit_reason"],
            }
        )
    return pd.DataFrame(rows)


def candidate_funnel(candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = [
        "study_period",
        "direction",
        "vix_direction_alignment",
        "vix_state",
    ]
    signal_columns = {
        variant: f"{variant.lower()}_signal"
        for variant in VARIANTS
    }
    for keys, group in candidates.groupby(
        group_columns,
        sort=True,
        dropna=False,
    ):
        period, direction, alignment, state = keys
        row: dict[str, Any] = {
            "study_period": period,
            "direction": direction,
            "vix_direction_alignment": alignment,
            "vix_state": state,
            "base_candidate_count": int(len(group)),
        }
        for variant, column in signal_columns.items():
            row[f"{variant.lower()}_candidate_count"] = int(
                group[column].sum()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def period_lookup(
    frame: pd.DataFrame,
    variant: str,
    period: str,
) -> pd.Series | None:
    rows = frame.loc[
        (frame["variant"] == variant)
        & (frame["study_period"] == period)
    ]
    return None if rows.empty else rows.iloc[0]


def compare_risk_reduction(
    period_summary: pd.DataFrame,
) -> dict[str, Any]:
    required = [
        "variant",
        "study_period",
        "trade_count",
        "mean_instrument_net_return",
        "max_drawdown",
    ]
    require_columns(
        period_summary,
        required,
        "V22.059 period summary",
    )
    for column in [
        "trade_count",
        "mean_instrument_net_return",
        "max_drawdown",
    ]:
        period_summary[column] = pd.to_numeric(
            period_summary[column],
            errors="coerce",
        )

    rows: list[dict[str, Any]] = []
    both_period_mdd_reduction = True
    reductions: list[float] = []

    for period in (VALIDATION, CONFIRMATION):
        control = period_lookup(period_summary, NO_VIX, period)
        rate = period_lookup(period_summary, RATE_1D_3D, period)
        if control is None or rate is None:
            both_period_mdd_reduction = False
            continue

        control_mdd = abs(float(control["max_drawdown"]))
        rate_mdd = abs(float(rate["max_drawdown"]))
        reduction = (
            1.0 - rate_mdd / control_mdd
            if control_mdd > 0
            else np.nan
        )
        reductions.append(reduction)
        if not np.isfinite(reduction) or reduction < 0.30:
            both_period_mdd_reduction = False

        rows.append(
            {
                "study_period": period,
                "no_vix_trade_count": int(control["trade_count"]),
                "rate_1d_3d_trade_count": int(rate["trade_count"]),
                "no_vix_mean_net_return": float(
                    control["mean_instrument_net_return"]
                ),
                "rate_1d_3d_mean_net_return": float(
                    rate["mean_instrument_net_return"]
                ),
                "mean_return_difference": float(
                    rate["mean_instrument_net_return"]
                    - control["mean_instrument_net_return"]
                ),
                "no_vix_max_drawdown": float(
                    control["max_drawdown"]
                ),
                "rate_1d_3d_max_drawdown": float(
                    rate["max_drawdown"]
                ),
                "max_drawdown_reduction": reduction,
            }
        )

    return {
        "comparison": pd.DataFrame(rows),
        "both_period_mdd_reduction_at_least_30pct": bool(
            both_period_mdd_reduction
        ),
        "minimum_mdd_reduction": (
            float(min(reductions))
            if reductions
            else np.nan
        ),
    }


def direction_candidate(
    direction_summary: pd.DataFrame,
) -> str | None:
    for direction in ("LONG", "SHORT"):
        rows = direction_summary.loc[
            (direction_summary["direction"] == direction)
            & (
                direction_summary["vix_direction_alignment"]
                == "ALIGNED_1D_3D"
            )
            & direction_summary["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ]
        if len(rows) != 2:
            continue
        validation = rows.loc[
            rows["study_period"] == VALIDATION
        ].iloc[0]
        confirmation = rows.loc[
            rows["study_period"] == CONFIRMATION
        ].iloc[0]
        if (
            int(validation["trade_count"]) >= 10
            and int(confirmation["trade_count"]) >= 10
            and float(validation["mean_instrument_net_return"]) > 0
            and float(confirmation["mean_instrument_net_return"]) > 0
            and float(validation["profit_factor"]) > 1.0
            and float(confirmation["profit_factor"]) > 1.0
            and float(validation["mean_entry_excess_pit_60m"]) > 0
            and float(confirmation["mean_entry_excess_pit_60m"]) > 0
        ):
            return direction
    return None


def choose_decision(
    period_summary: pd.DataFrame,
    no_vix_direction_alignment: pd.DataFrame,
) -> dict[str, Any]:
    risk = compare_risk_reduction(period_summary)
    candidate_direction = direction_candidate(
        no_vix_direction_alignment
    )

    if candidate_direction:
        final_decision = (
            f"VIX_RATE_ALIGNMENT_SUPPORTED_FOR_{candidate_direction}_"
            "DIRECTION_REPLICATION"
        )
        next_stage = (
            "V22.060_FAST3_DIRECTION_SPECIFIC_VIX_RATE_REPLICATION_R1"
        )
        role = "DIRECTION_PERMISSION_CANDIDATE"
    elif risk["both_period_mdd_reduction_at_least_30pct"]:
        final_decision = (
            "VIX_RATE_NOT_SUPPORTED_AS_HARD_GATE_"
            "RETAIN_AS_RISK_OVERLAY_CANDIDATE"
        )
        next_stage = (
            "V22.060_FAST3_VIX_RATE_RISK_SCALING_STUDY_R1"
        )
        role = "RISK_SCALER_ONLY"
    else:
        final_decision = (
            "VIX_RATE_NOT_SUPPORTED_AS_ENTRY_GATE_OR_RISK_OVERLAY"
        )
        next_stage = "STOP_VIX_RATE_MODULE"
        role = "DIAGNOSTIC_ONLY"

    return {
        "final_decision": final_decision,
        "recommended_vix_role": role,
        "direction_specific_candidate": candidate_direction,
        "hard_entry_gate_supported": False,
        "risk_overlay_candidate": bool(
            risk["both_period_mdd_reduction_at_least_30pct"]
        ),
        "minimum_mdd_reduction": risk["minimum_mdd_reduction"],
        "next_stage": next_stage,
        "risk_comparison": risk["comparison"],
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
        "mean_instrument_net_return",
        "median_instrument_net_return",
        "mean_account_trade_return",
        "mean_entry_signal_60m_return",
        "mean_entry_excess_pit_60m",
        "mean_realized_minus_fixed_60m",
        "mean_mfe",
        "mean_mae",
        "mean_net_excluding_worst_5",
        "worst_trade_return",
        "instrument_net_return",
        "account_trade_return",
        "entry_signal_60m_net_return",
        "entry_excess_pit_60m",
        "realized_minus_fixed_60m",
        "no_vix_mean_net_return",
        "rate_1d_3d_mean_net_return",
        "mean_return_difference",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_rate",
        "sequential_trade_max_drawdown",
        "hard_stop_rate",
        "trailing_protection_rate",
        "worst_5_loss_share",
        "max_drawdown_reduction",
        "no_vix_max_drawdown",
        "rate_1d_3d_max_drawdown",
    }:
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        numeric = float(value)
        return "INF" if np.isinf(numeric) else f"{numeric:.3f}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.2f}"
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


def run_diagnostic(
    root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    paths = {
        "summary": root / "v22_059_summary.json",
        "trades": root / "v22_059_trades.csv",
        "candidates": root / "v22_059_signal_candidates.csv",
        "period": root / "v22_059_period_summary.csv",
    }
    for label, path in paths.items():
        if not path.exists():
            raise DiagnosticError(
                f"Missing V22.059 {label} file: {path}"
            )

    source_summary = json.loads(
        paths["summary"].read_text(encoding="utf-8-sig")
    )
    validate_v22_059(source_summary)

    trades = normalize_trades(pd.read_csv(paths["trades"]))
    candidates = normalize_candidates(
        pd.read_csv(paths["candidates"])
    )
    period_summary = pd.read_csv(paths["period"])

    variant_direction = grouped_summary(
        trades,
        [
            "variant",
            "study_period",
            "direction",
        ],
    )
    variant_direction_symbol = grouped_summary(
        trades,
        [
            "variant",
            "study_period",
            "direction",
            "execution_symbol",
        ],
    )

    no_vix = trades.loc[trades["variant"] == NO_VIX].copy()
    if no_vix.empty:
        raise DiagnosticError("NO_VIX_CONTROL trades are empty")

    no_vix_direction_alignment = grouped_summary(
        no_vix,
        [
            "study_period",
            "direction",
            "vix_direction_alignment",
        ],
    )
    no_vix_state = grouped_summary(
        no_vix,
        [
            "study_period",
            "direction",
            "vix_state",
        ],
    )
    percentile = grouped_summary(
        no_vix,
        [
            "study_period",
            "direction",
            "vix_rate_percentile_bin",
        ],
    )
    exits = exit_summary(no_vix)
    tails = tail_summary(no_vix)
    funnel = candidate_funnel(candidates)
    worst = (
        no_vix.sort_values(
            "instrument_net_return",
            kind="mergesort",
        )
        .head(20)
        .loc[
            :,
            [
                "trade_date",
                "study_period",
                "direction",
                "execution_symbol",
                "vix_state",
                "vix_direction_alignment",
                "vix_rate_1d_prior",
                "vix_rate_3d_prior",
                "vix_rate_1d_pctl_252_prior",
                "instrument_net_return",
                "account_trade_return",
                "entry_signal_60m_net_return",
                "entry_excess_pit_60m",
                "realized_minus_fixed_60m",
                "mfe",
                "mae",
                "holding_minutes",
                "exit_reason",
            ],
        ]
        .reset_index(drop=True)
    )

    decision = choose_decision(
        period_summary,
        no_vix_direction_alignment,
    )
    risk_comparison = decision.pop("risk_comparison")

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "variant_direction": result_dir
        / "v22_059a_variant_direction_summary.csv",
        "variant_direction_symbol": result_dir
        / "v22_059a_variant_direction_symbol_summary.csv",
        "direction_alignment": result_dir
        / "v22_059a_no_vix_direction_alignment_summary.csv",
        "vix_state": result_dir
        / "v22_059a_no_vix_vix_state_summary.csv",
        "percentile": result_dir
        / "v22_059a_no_vix_rate_percentile_summary.csv",
        "exit": result_dir
        / "v22_059a_exit_reason_attribution.csv",
        "tail": result_dir
        / "v22_059a_tail_loss_attribution.csv",
        "funnel": result_dir
        / "v22_059a_candidate_funnel_by_vix_state.csv",
        "worst": result_dir
        / "v22_059a_worst_20_trades.csv",
        "risk_comparison": result_dir
        / "v22_059a_risk_reduction_comparison.csv",
        "summary": result_dir / "v22_059a_summary.json",
    }

    frames = {
        "variant_direction": variant_direction,
        "variant_direction_symbol": variant_direction_symbol,
        "direction_alignment": no_vix_direction_alignment,
        "vix_state": no_vix_state,
        "percentile": percentile,
        "exit": exits,
        "tail": tails,
        "funnel": funnel,
        "worst": worst,
        "risk_comparison": risk_comparison,
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
        "source_v22_059_validated": True,
        "source_v22_059_decision": source_summary["final_decision"],
        "source_trade_count": int(len(trades)),
        "source_no_vix_trade_count": int(len(no_vix)),
        "canonical_partition_count_read": 0,
        "backtest_executed": False,
        "parameter_sweep_executed": False,
        "entry_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        **decision,
        "outputs": {
            name: str(path)
            for name, path in outputs.items()
        },
    }
    write_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.059A VIX-rate direction attribution")
    print("==============================================")

    print_table(
        "四版本 × 阶段 × 方向",
        variant_direction.loc[
            variant_direction["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )
    print_table(
        "NO-VIX基础信号 × VIX方向一致性",
        no_vix_direction_alignment.loc[
            no_vix_direction_alignment["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )
    print_table(
        "NO-VIX基础信号 × VIX 1日/3日状态",
        no_vix_state.loc[
            no_vix_state["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )
    print_table(
        "退出原因归因",
        exits.loc[
            exits["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )
    print_table("尾部损失归因", tails)
    print_table("VIX过滤的回撤压缩", risk_comparison)
    print_table("最差20笔", worst)

    print()
    print("========== 自动研究决策 ==========")
    for key in [
        "FINAL_DECISION",
        "RECOMMENDED_VIX_ROLE",
        "DIRECTION_SPECIFIC_CANDIDATE",
        "HARD_ENTRY_GATE_SUPPORTED",
        "RISK_OVERLAY_CANDIDATE",
        "MINIMUM_MDD_REDUCTION",
        "NEXT_STAGE",
    ]:
        source_key = key.lower()
        print(f"{key}={summary.get(source_key)}")

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={summary['final_decision']}")
    print(f"RECOMMENDED_VIX_ROLE={summary['recommended_vix_role']}")
    print("CANONICAL_PARTITION_COUNT_READ=0")
    print("BACKTEST_EXECUTED=False")
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
        "--root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.059_FAST3_VIX_CHANGE_RATE_DIRECTION_STUDY_R1"
        ),
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.059A_FAST3_VIX_RATE_DIRECTION_ATTRIBUTION_R1"
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
        run_diagnostic(
            root=Path(args.root),
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
