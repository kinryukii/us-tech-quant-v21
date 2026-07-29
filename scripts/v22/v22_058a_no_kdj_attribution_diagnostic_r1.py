#!/usr/bin/env python
r"""
V22.058A NO-KDJ attribution diagnostic R1.

Reads existing V22.058 outputs only. It does not reread the 582 Canonical
partitions and does not execute a backtest.

Purpose:
- determine whether losses are concentrated in LONG or SHORT;
- identify problematic execution ETFs;
- attribute outcomes to exit reasons;
- quantify worst-five-trade loss concentration;
- list the worst 15 trades;
- summarize annual behavior;
- print a rule-based next-stage research recommendation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


VERSION = "V22.058A_NO_KDJ_ATTRIBUTION_DIAGNOSTIC_R1"
TARGET_VARIANT = "NO_KDJ_CONTROL"
VALIDATION = "2023-2024_VALIDATION"
CONFIRMATION = "2025-2026_YTD_CONFIRMATION"


class DiagnosticError(RuntimeError):
    """Existing V22.058 results are absent or structurally invalid."""


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DiagnosticError(f"{name} missing required columns: {missing}")


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    positive = float(clean.loc[clean > 0].sum())
    negative = float(-clean.loc[clean < 0].sum())
    if negative == 0:
        return math.inf if positive > 0 else math.nan
    return positive / negative


def summarize_group(group: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(
        group["instrument_net_return"],
        errors="coerce",
    ).dropna()
    account = pd.to_numeric(
        group["account_trade_return"],
        errors="coerce",
    ).dropna()
    holding = pd.to_numeric(
        group["holding_minutes"],
        errors="coerce",
    ).dropna()

    return {
        "trade_count": int(len(group)),
        "mean_net_return": float(returns.mean()) if len(returns) else np.nan,
        "median_net_return": (
            float(returns.median()) if len(returns) else np.nan
        ),
        "positive_rate": (
            float((returns > 0).mean()) if len(returns) else np.nan
        ),
        "profit_factor": profit_factor(account),
        "mean_holding_minutes": (
            float(holding.mean()) if len(holding) else np.nan
        ),
    }


def direction_symbol_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = ["study_period", "direction", "execution_symbol"]
    for keys, group in trades.groupby(columns, sort=True, dropna=False):
        period, direction, symbol = keys
        rows.append(
            {
                "study_period": period,
                "direction": direction,
                "execution_symbol": symbol,
                **summarize_group(group),
            }
        )
    return pd.DataFrame(rows)


def exit_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = ["study_period", "exit_reason"]
    for keys, group in trades.groupby(columns, sort=True, dropna=False):
        period, reason = keys
        rows.append(
            {
                "study_period": period,
                "exit_reason": reason,
                **summarize_group(group),
            }
        )
    return pd.DataFrame(rows)


def tail_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    period_order = [
        "2018-2022_DEVELOPMENT",
        VALIDATION,
        CONFIRMATION,
    ]

    for period in period_order:
        group = trades.loc[trades["study_period"] == period].copy()
        if group.empty:
            continue

        group["instrument_net_return"] = pd.to_numeric(
            group["instrument_net_return"],
            errors="coerce",
        )
        group = group.dropna(
            subset=["instrument_net_return"]
        ).sort_values("instrument_net_return", kind="mergesort")

        worst_count = min(5, len(group))
        worst = group.head(worst_count)
        remaining = group.iloc[worst_count:]

        all_negative = float(
            -group.loc[
                group["instrument_net_return"] < 0,
                "instrument_net_return",
            ].sum()
        )
        worst_negative = float(
            -worst.loc[
                worst["instrument_net_return"] < 0,
                "instrument_net_return",
            ].sum()
        )

        first = group.iloc[0]
        rows.append(
            {
                "study_period": period,
                "trade_count": int(len(group)),
                "worst_5_loss_share": (
                    worst_negative / all_negative
                    if all_negative > 0
                    else np.nan
                ),
                "mean_net_excluding_worst_5": (
                    float(remaining["instrument_net_return"].mean())
                    if len(remaining)
                    else np.nan
                ),
                "worst_trade_return": float(
                    first["instrument_net_return"]
                ),
                "worst_trade_date": first.get("trade_date", ""),
                "worst_trade_direction": first.get("direction", ""),
                "worst_trade_symbol": first.get(
                    "execution_symbol", ""
                ),
                "worst_trade_exit_reason": first.get(
                    "exit_reason", ""
                ),
            }
        )
    return pd.DataFrame(rows)


def worst_trades(trades: pd.DataFrame, count: int = 15) -> pd.DataFrame:
    result = trades.copy()
    numeric = [
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "holding_minutes",
    ]
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    columns = [
        "trade_date",
        "study_period",
        "direction",
        "execution_symbol",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "holding_minutes",
        "exit_reason",
    ]
    return (
        result.sort_values(
            "instrument_net_return",
            kind="mergesort",
        )
        .head(count)
        .loc[:, columns]
        .reset_index(drop=True)
    )


def annual_summary(
    trades: pd.DataFrame,
    existing_year: pd.DataFrame,
) -> pd.DataFrame:
    target = existing_year.loc[
        existing_year["variant"] == TARGET_VARIANT
    ].copy()
    if not target.empty:
        columns = [
            "calendar_year",
            "trade_count",
            "cumulative_return",
            "max_drawdown",
            "mean_instrument_net_return",
            "median_instrument_net_return",
            "positive_rate",
            "profit_factor",
        ]
        require_columns(target, columns, "V22.058 year summary")
        return target.loc[:, columns].sort_values("calendar_year")

    rows: list[dict[str, Any]] = []
    for year, group in trades.groupby("calendar_year", sort=True):
        summary = summarize_group(group)
        rows.append(
            {
                "calendar_year": int(year),
                **summary,
            }
        )
    return pd.DataFrame(rows)


def direction_period_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["study_period", "direction"],
        sort=True,
        dropna=False,
    ):
        period, direction = keys
        rows.append(
            {
                "study_period": period,
                "direction": direction,
                **summarize_group(group),
            }
        )
    return pd.DataFrame(rows)


def choose_recommendation(
    direction_period: pd.DataFrame,
    exits: pd.DataFrame,
    tail: pd.DataFrame,
) -> dict[str, Any]:
    result = {
        "final_status": "PASS",
        "final_decision": "ATTRIBUTION_COMPLETED_REVIEW_TABLES",
        "short_freeze_recommended": False,
        "long_freeze_recommended": False,
        "tail_risk_priority": False,
        "hard_stop_priority": False,
        "no_progress_priority": False,
        "factor_invalidation_priority": False,
        "next_stage": "MANUAL_REVIEW_REQUIRED",
    }

    def period_direction(period: str, direction: str) -> pd.Series | None:
        rows = direction_period.loc[
            (direction_period["study_period"] == period)
            & (direction_period["direction"] == direction)
        ]
        return None if rows.empty else rows.iloc[0]

    long_val = period_direction(VALIDATION, "LONG")
    long_conf = period_direction(CONFIRMATION, "LONG")
    short_val = period_direction(VALIDATION, "SHORT")
    short_conf = period_direction(CONFIRMATION, "SHORT")

    def both_negative(a: pd.Series | None, b: pd.Series | None) -> bool:
        return bool(
            a is not None
            and b is not None
            and float(a["mean_net_return"]) < 0
            and float(b["mean_net_return"]) < 0
        )

    result["short_freeze_recommended"] = both_negative(
        short_val, short_conf
    )
    result["long_freeze_recommended"] = both_negative(
        long_val, long_conf
    )

    confirmation_tail = tail.loc[
        tail["study_period"] == CONFIRMATION
    ]
    if not confirmation_tail.empty:
        share = float(
            confirmation_tail.iloc[0]["worst_5_loss_share"]
        )
        remaining_mean = float(
            confirmation_tail.iloc[0][
                "mean_net_excluding_worst_5"
            ]
        )
        result["tail_risk_priority"] = bool(
            np.isfinite(share)
            and share >= 0.50
            and np.isfinite(remaining_mean)
            and remaining_mean > 0
        )

    confirmation_exits = exits.loc[
        exits["study_period"] == CONFIRMATION
    ].copy()
    if not confirmation_exits.empty:
        total = int(confirmation_exits["trade_count"].sum())
        for reason, key in [
            ("HARD_STOP", "hard_stop_priority"),
            ("NO_PROGRESS_15M", "no_progress_priority"),
            ("FACTOR_INVALIDATION", "factor_invalidation_priority"),
        ]:
            rows = confirmation_exits.loc[
                confirmation_exits["exit_reason"] == reason
            ]
            if not rows.empty and total > 0:
                count_share = float(rows.iloc[0]["trade_count"]) / total
                mean_return = float(rows.iloc[0]["mean_net_return"])
                result[key] = bool(
                    count_share >= 0.30 and mean_return < 0
                )

    if (
        result["short_freeze_recommended"]
        and not result["long_freeze_recommended"]
    ):
        result["final_decision"] = (
            "FREEZE_SHORT_RESEARCH_LONG_ONLY_NEXT"
        )
        result["next_stage"] = (
            "V22.059_FAST3_LONG_ONLY_NO_KDJ_REPLICATION_R1"
        )
    elif result["tail_risk_priority"]:
        result["final_decision"] = (
            "TAIL_LOSS_CONCENTRATION_REQUIRES_RISK_EXIT_STUDY"
        )
        result["next_stage"] = (
            "V22.059_FAST3_TAIL_RISK_EXIT_ATTRIBUTION_R1"
        )
    elif result["long_freeze_recommended"] and result[
        "short_freeze_recommended"
    ]:
        result["final_decision"] = (
            "NO_KDJ_CORE_NEGATIVE_BOTH_DIRECTIONS"
        )
        result["next_stage"] = (
            "STOP_CURRENT_ENTRY_ARCHITECTURE"
        )
    return result


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_net_return",
        "median_net_return",
        "mean_net_excluding_worst_5",
        "worst_trade_return",
        "instrument_net_return",
        "account_trade_return",
        "mfe",
        "mae",
        "mean_instrument_net_return",
        "median_instrument_net_return",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_rate",
        "worst_5_loss_share",
        "cumulative_return",
        "max_drawdown",
    }:
        return f"{float(value) * 100:.2f}"
    if column in {"profit_factor"}:
        return (
            "INF"
            if np.isinf(float(value))
            else f"{float(value):.3f}"
        )
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.2f}"
    return str(value)


def print_table(
    title: str,
    frame: pd.DataFrame,
    rename: dict[str, str] | None = None,
) -> None:
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
    if rename:
        display = display.rename(columns=rename)
    print(display.to_string(index=False))


def run_diagnostic(
    root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    trades_path = root / "v22_058_trades.csv"
    year_path = root / "v22_058_year_summary.csv"
    funnel_path = root / "v22_058_signal_funnel.csv"
    summary_path = root / "v22_058_summary.json"

    for path in [trades_path, year_path, funnel_path, summary_path]:
        if not path.exists():
            raise DiagnosticError(f"Missing V22.058 result: {path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    if summary.get("final_status") != "PASS":
        raise DiagnosticError(
            "V22.058 summary is not PASS; diagnostic blocked."
        )

    trades = pd.read_csv(trades_path)
    year = pd.read_csv(year_path)
    funnel = pd.read_csv(funnel_path)

    trade_required = [
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
    ]
    require_columns(trades, trade_required, "V22.058 trades")

    target = trades.loc[
        trades["variant"] == TARGET_VARIANT
    ].copy()
    if target.empty:
        raise DiagnosticError(
            f"No trades found for {TARGET_VARIANT}."
        )

    direction_symbol = direction_symbol_summary(target)
    direction_period = direction_period_summary(target)
    exits = exit_summary(target)
    tail = tail_summary(target)
    worst = worst_trades(target)
    annual = annual_summary(target, year)
    recommendation = choose_recommendation(
        direction_period,
        exits,
        tail,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "direction_symbol": output_dir
        / "v22_058a_direction_symbol_attribution.csv",
        "direction_period": output_dir
        / "v22_058a_direction_period_attribution.csv",
        "exit": output_dir
        / "v22_058a_exit_reason_attribution.csv",
        "tail": output_dir
        / "v22_058a_tail_loss_concentration.csv",
        "worst": output_dir
        / "v22_058a_worst_15_trades.csv",
        "annual": output_dir
        / "v22_058a_annual_summary.csv",
        "funnel": output_dir
        / "v22_058a_source_signal_funnel.csv",
        "summary": output_dir / "v22_058a_summary.json",
    }

    direction_symbol.to_csv(
        outputs["direction_symbol"],
        index=False,
        encoding="utf-8-sig",
    )
    direction_period.to_csv(
        outputs["direction_period"],
        index=False,
        encoding="utf-8-sig",
    )
    exits.to_csv(
        outputs["exit"],
        index=False,
        encoding="utf-8-sig",
    )
    tail.to_csv(
        outputs["tail"],
        index=False,
        encoding="utf-8-sig",
    )
    worst.to_csv(
        outputs["worst"],
        index=False,
        encoding="utf-8-sig",
    )
    annual.to_csv(
        outputs["annual"],
        index=False,
        encoding="utf-8-sig",
    )
    funnel.to_csv(
        outputs["funnel"],
        index=False,
        encoding="utf-8-sig",
    )

    diagnostic_summary = {
        "version": VERSION,
        "final_status": "PASS",
        "source_v22_058_status": summary.get("final_status"),
        "source_v22_058_decision": summary.get("final_decision"),
        "source_variant": TARGET_VARIANT,
        "trade_count": int(len(target)),
        "canonical_partitions_read": 0,
        "backtest_executed": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        **recommendation,
        "outputs": {
            key: str(path)
            for key, path in outputs.items()
            if key != "summary"
        },
    }
    outputs["summary"].write_text(
        json.dumps(
            diagnostic_summary,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("==============================================")
    print(" V22.058A NO-KDJ attribution diagnostic")
    print("==============================================")

    print_table(
        "阶段 × 方向",
        direction_period,
    )
    print_table(
        "阶段 × 方向 × 执行标的",
        direction_symbol,
    )
    print_table(
        "阶段 × 退出原因",
        exits,
    )
    print_table(
        "尾部损失集中度",
        tail,
    )
    print_table(
        "NO-KDJ 最差15笔",
        worst,
    )
    print_table(
        "NO-KDJ 年度表现",
        annual,
    )
    print_table(
        "原始信号漏斗",
        funnel,
    )

    print()
    print("========== 自动归因结论 ==========")
    for key in [
        "final_decision",
        "short_freeze_recommended",
        "long_freeze_recommended",
        "tail_risk_priority",
        "hard_stop_priority",
        "no_progress_priority",
        "factor_invalidation_priority",
        "next_stage",
    ]:
        print(f"{key.upper()}={diagnostic_summary[key]}")

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={diagnostic_summary['final_decision']}")
    print("CANONICAL_PARTITIONS_READ=0")
    print("BACKTEST_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={output_dir}")

    return diagnostic_summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.058_FAST3_KDJ_TEMPORAL_ALIGNMENT_STUDY_R1"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.058A_NO_KDJ_ATTRIBUTION_DIAGNOSTIC_R1"
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
            output_dir=Path(args.output_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
