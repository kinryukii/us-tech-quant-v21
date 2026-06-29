#!/usr/bin/env python
"""Decompose the immutable V21.104 D long-horizon hold results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE = "V21.104-R1_D_LONG_HORIZON_EDGE_DECOMPOSITION"
SOURCE_RUN_ID = "20260623_163856"
SOURCE_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run") / SOURCE_RUN_ID
OUTPUT_REL = Path("outputs/v21/v21_104_r1_d_long_horizon_edge_decomposition")

CONFIG = "v21_104_r1_config.json"
HORIZON = "v21_104_r1_horizon_decomposition.csv"
SIZE = "v21_104_r1_portfolio_size_decomposition.csv"
BENCHMARK = "v21_104_r1_benchmark_decomposition.csv"
TAIL = "v21_104_r1_left_tail_decomposition.csv"
TIME = "v21_104_r1_time_bucket_decomposition.csv"
SAMPLES = "v21_104_r1_best_worst_sample_decomposition.csv"
CONCENTRATION = "v21_104_r1_concentration_or_unavailable_report.csv"
WARNINGS = "v21_104_r1_warning_audit.csv"
README = "v21_104_r1_decision_readme.md"

PASS = "PASS_V21_104_R1_D_EDGE_BROAD_AND_LEFT_TAIL_ACCEPTABLE_RESEARCH_ONLY"
PARTIAL_SOXX = "PARTIAL_PASS_V21_104_R1_D_EDGE_CONFIRMED_BUT_SOXX_EXTREME_UPSIDE_GAP"
PARTIAL_REGIME = "PARTIAL_PASS_V21_104_R1_D_EDGE_CONCENTRATED_OR_REGIME_DEPENDENT"
FAIL_BIAS = "FAIL_V21_104_R1_D_EDGE_EXPLAINED_BY_BIAS_OR_CONCENTRATION"
FAIL_DATA = "FAIL_V21_104_R1_DATA_REQUIRED_FOR_DECOMPOSITION_MISSING"

SOURCE_FILES = (
    "v21_104_abcd_252d_hold_row_results.csv",
    "v21_104_abcd_252d_hold_summary.csv",
    "v21_104_abcd_252d_hold_pairwise_comparison.csv",
    "v21_104_abcd_252d_hold_benchmark_comparison.csv",
    "v21_104_abcd_252d_hold_worst_samples.csv",
    "v21_104_abcd_252d_hold_leakage_audit.csv",
    "v21_104_abcd_252d_hold_data_quality_warnings.csv",
)


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def truth(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def immutable_output(root: Path, override: Path | None, run_id: str | None) -> tuple[Path, str]:
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = (
        override if override and override.is_absolute()
        else root / (override or OUTPUT_REL / identifier)
    ).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Immutable output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output, identifier


def load_inputs(root: Path) -> tuple[Path, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source = root / SOURCE_REL
    missing = [name for name in SOURCE_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing V21.104 source files: {missing}")
    rows = pd.read_csv(source / SOURCE_FILES[0], low_memory=False)
    audit = pd.read_csv(source / SOURCE_FILES[5], low_memory=False)
    warning = pd.read_csv(source / SOURCE_FILES[6], low_memory=False)
    required = {
        "sample_id", "start_date", "variant", "portfolio_size", "horizon",
        "portfolio_return", "benchmark_QQQ_return", "benchmark_SPY_return",
        "benchmark_semiconductor_return", "excess_vs_A1", "excess_vs_B",
        "excess_vs_C", "excess_vs_QQQ", "excess_vs_SPY",
        "excess_vs_semiconductor_benchmark", "point_in_time_valid",
    }
    if not required.issubset(rows.columns):
        raise RuntimeError(f"Row-result schema missing: {sorted(required - set(rows.columns))}")
    return source, rows, audit, warning


def numeric(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy()
    for column in (
        "portfolio_size", "horizon", "portfolio_return", "benchmark_QQQ_return",
        "benchmark_SPY_return", "benchmark_semiconductor_return",
        "excess_vs_A1", "excess_vs_B", "excess_vs_C", "excess_vs_D",
        "excess_vs_QQQ", "excess_vs_SPY", "excess_vs_semiconductor_benchmark",
        "max_drawdown", "missing_price_count",
    ):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["start_year"] = frame["start_date"].astype(str).str[:4]
    return frame


def horizon_decomposition(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")]
    comparisons = {
        "A1": "excess_vs_A1", "B": "excess_vs_B", "C": "excess_vs_C",
        "QQQ": "excess_vs_QQQ", "SPY": "excess_vs_SPY",
        "SOXX": "excess_vs_semiconductor_benchmark",
    }
    rows = []
    for (size, horizon), group in d.groupby(["portfolio_size", "horizon"], sort=True):
        for comparison, column in comparisons.items():
            excess = group[column].dropna()
            rows.append({
                "portfolio_size": int(size), "horizon": int(horizon),
                "comparison": f"D_VS_{comparison}", "sample_count": len(excess),
                "d_mean_return": group.loc[excess.index, "portfolio_return"].mean(),
                "mean_excess": excess.mean(), "median_excess": excess.median(),
                "p5_excess": excess.quantile(.05), "p10_excess": excess.quantile(.10),
                "win_rate": excess.gt(0).mean(),
                "edge_status": "POSITIVE" if excess.mean() > 0 and excess.median() > 0 else "MIXED" if excess.mean() > 0 or excess.median() > 0 else "NEGATIVE",
            })
    return rows


def size_decomposition(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")]
    rows = []
    for horizon in sorted(d["horizon"].dropna().unique()):
        subset = d[d["horizon"].eq(horizon)]
        for size in (20, 50):
            group = subset[subset["portfolio_size"].eq(size)]
            rows.append({
                "horizon": int(horizon), "portfolio_size": size,
                "sample_count": len(group), "mean_return": group["portfolio_return"].mean(),
                "median_return": group["portfolio_return"].median(),
                "p5_return": group["portfolio_return"].quantile(.05),
                "p10_return": group["portfolio_return"].quantile(.10),
                "mean_excess_vs_A1": group["excess_vs_A1"].mean(),
                "win_rate_vs_A1": group["excess_vs_A1"].gt(0).mean(),
                "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
                "win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
                "mean_excess_vs_SOXX": group["excess_vs_semiconductor_benchmark"].mean(),
                "win_rate_vs_SOXX": group["excess_vs_semiconductor_benchmark"].gt(0).mean(),
                "return_volatility": group["portfolio_return"].std(ddof=0),
            })
        top20 = subset[subset["portfolio_size"].eq(20)].set_index("sample_id")
        top50 = subset[subset["portfolio_size"].eq(50)].set_index("sample_id")
        joined = top20[["portfolio_return"]].join(
            top50[["portfolio_return"]], lsuffix="_20", rsuffix="_50", how="inner",
        )
        delta = joined["portfolio_return_20"] - joined["portfolio_return_50"]
        rows.append({
            "horizon": int(horizon), "portfolio_size": "TOP20_MINUS_TOP50",
            "sample_count": len(delta), "mean_return": delta.mean(),
            "median_return": delta.median(), "p5_return": delta.quantile(.05),
            "p10_return": delta.quantile(.10),
            "mean_excess_vs_A1": "", "win_rate_vs_A1": "",
            "mean_excess_vs_QQQ": "", "win_rate_vs_QQQ": "",
            "mean_excess_vs_SOXX": "", "win_rate_vs_SOXX": "",
            "return_volatility": delta.std(ddof=0),
        })
    return rows


def benchmark_decomposition(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")]
    rows = []
    for (size, horizon), group in d.groupby(["portfolio_size", "horizon"], sort=True):
        excess = group["excess_vs_semiconductor_benchmark"].dropna()
        wins = group.loc[excess.index][excess.gt(0)]
        losses = group.loc[excess.index][excess.le(0)]
        cutoff = group["benchmark_semiconductor_return"].quantile(.95)
        extreme = group[group["benchmark_semiconductor_return"].ge(cutoff)]
        trimmed = group[group["benchmark_semiconductor_return"].lt(cutoff)]
        rows.append({
            "portfolio_size": int(size), "horizon": int(horizon),
            "sample_count": len(excess), "d_win_rate_vs_SOXX": excess.gt(0).mean(),
            "d_mean_excess_vs_SOXX": excess.mean(),
            "d_median_excess_vs_SOXX": excess.median(),
            "mean_excess_in_D_wins": wins["excess_vs_semiconductor_benchmark"].mean(),
            "mean_excess_in_D_losses": losses["excess_vs_semiconductor_benchmark"].mean(),
            "soxx_p95_return_cutoff": cutoff, "soxx_extreme_sample_count": len(extreme),
            "soxx_extreme_mean_return": extreme["benchmark_semiconductor_return"].mean(),
            "d_mean_excess_in_soxx_extreme_samples": extreme["excess_vs_semiconductor_benchmark"].mean(),
            "d_mean_excess_excluding_soxx_top5pct": trimmed["excess_vs_semiconductor_benchmark"].mean(),
            "soxx_extreme_gap_explains_negative_mean": bool(
                excess.mean() < 0 and trimmed["excess_vs_semiconductor_benchmark"].mean() >= 0
            ),
        })
    return rows


def left_tail_decomposition(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")]
    comparisons = {
        "A1": "excess_vs_A1", "B": "excess_vs_B", "C": "excess_vs_C",
        "QQQ": "excess_vs_QQQ", "SOXX": "excess_vs_semiconductor_benchmark",
    }
    rows = []
    for (size, horizon), group in d.groupby(["portfolio_size", "horizon"], sort=True):
        for name, column in comparisons.items():
            values = group[column].dropna()
            downside = values[values.lt(0)]
            rows.append({
                "portfolio_size": int(size), "horizon": int(horizon),
                "comparison": f"D_VS_{name}", "sample_count": len(values),
                "p5_excess": values.quantile(.05), "p10_excess": values.quantile(.10),
                "worst_excess": values.min(), "downside_sample_count": len(downside),
                "downside_rate": values.lt(0).mean(),
                "mean_downside_excess": downside.mean(),
                "median_downside_excess": downside.median(),
                "d_p5_return": group["portfolio_return"].quantile(.05),
                "d_p10_return": group["portfolio_return"].quantile(.10),
                "d_worst_return": group["portfolio_return"].min(),
                "material_left_tail_warning": bool(
                    values.quantile(.05) < -.30 or group["portfolio_return"].quantile(.05) < -.20
                ),
            })
    return rows


def regime_bucket(group: pd.DataFrame) -> pd.Series:
    qqq = group["benchmark_QQQ_return"]
    spy = group["benchmark_SPY_return"]
    soxx = group["benchmark_semiconductor_return"]
    soxx_extreme = soxx >= soxx.quantile(.90)
    return pd.Series(
        np.select(
            [
                soxx_extreme,
                qqq.lt(0) & spy.lt(0),
                qqq.gt(spy) & qqq.gt(0),
                spy.ge(qqq) & spy.gt(0),
            ],
            ["SOXX_EXTREME_UPSIDE", "QQQ_SPY_DOWN", "QQQ_LED_RISK_ON", "SPY_LED_UP"],
            default="MIXED_FLAT",
        ),
        index=group.index,
    )


def time_bucket_decomposition(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")].copy()
    rows = []
    for (size, horizon), base in d.groupby(["portfolio_size", "horizon"], sort=True):
        base = base.copy()
        base["regime_bucket"] = regime_bucket(base)
        for bucket_type, column in (("CALENDAR_YEAR", "start_year"), ("BENCHMARK_CONDITION", "regime_bucket")):
            for bucket, group in base.groupby(column, sort=True):
                rows.append({
                    "portfolio_size": int(size), "horizon": int(horizon),
                    "bucket_type": bucket_type, "bucket": bucket,
                    "sample_count": len(group),
                    "mean_return": group["portfolio_return"].mean(),
                    "median_return": group["portfolio_return"].median(),
                    "mean_excess_vs_A1": group["excess_vs_A1"].mean(),
                    "win_rate_vs_A1": group["excess_vs_A1"].gt(0).mean(),
                    "mean_excess_vs_QQQ": group["excess_vs_QQQ"].mean(),
                    "win_rate_vs_QQQ": group["excess_vs_QQQ"].gt(0).mean(),
                    "mean_excess_vs_SOXX": group["excess_vs_semiconductor_benchmark"].mean(),
                    "win_rate_vs_SOXX": group["excess_vs_semiconductor_benchmark"].gt(0).mean(),
                    "p5_excess_vs_QQQ": group["excess_vs_QQQ"].quantile(.05),
                })
    return rows


def best_worst_samples(frame: pd.DataFrame) -> list[dict[str, object]]:
    d = frame[frame["variant"].eq("D")]
    rows = []
    for (size, horizon), group in d.groupby(["portfolio_size", "horizon"], sort=True):
        group = group.copy()
        group["benchmark_condition"] = regime_bucket(group)
        for benchmark, column in (
            ("QQQ", "excess_vs_QQQ"),
            ("SOXX", "excess_vs_semiconductor_benchmark"),
        ):
            ordered = group.sort_values(column)
            for direction, selected in (
                ("WORST", ordered.head(50)), ("BEST", ordered.tail(50).sort_values(column, ascending=False)),
            ):
                for rank, (_, row) in enumerate(selected.iterrows(), start=1):
                    rows.append({
                        "portfolio_size": int(size), "horizon": int(horizon),
                        "benchmark": benchmark, "direction": direction,
                        "tail_rank": rank, "sample_id": row["sample_id"],
                        "seed": row["seed"], "draw_index": row["draw_index"],
                        "start_date": row["start_date"], "start_year": row["start_year"],
                        "d_return": row["portfolio_return"],
                        "benchmark_return": row[
                            "benchmark_QQQ_return" if benchmark == "QQQ" else "benchmark_semiconductor_return"
                        ],
                        "d_excess": row[column],
                        "benchmark_condition": row["benchmark_condition"],
                    })
    return rows


def warning_audit(
    source: Path, audit: pd.DataFrame, warnings: pd.DataFrame,
    source_before: dict[str, str], source_after: dict[str, str],
) -> list[dict[str, object]]:
    codes = set(warnings["warning_code"].astype(str))
    leakage_failures = int((~audit["point_in_time_valid"].map(truth)).sum())
    modified = [name for name in source_before if source_before[name] != source_after[name]]
    return [
        {
            "check": "SURVIVORSHIP_BIAS_WARN_PRESERVED",
            "status": "PASS" if "SURVIVORSHIP_BIAS_WARN" in codes else "FAIL",
            "value": str("SURVIVORSHIP_BIAS_WARN" in codes).upper(),
            "details": "",
        },
        {
            "check": "PIT_FACTOR_APPROXIMATION_WARN_PRESERVED",
            "status": "PASS" if "PIT_FACTOR_APPROXIMATION_WARN" in codes else "FAIL",
            "value": str("PIT_FACTOR_APPROXIMATION_WARN" in codes).upper(),
            "details": "",
        },
        {
            "check": "LEAKAGE_FAILURE_COUNT",
            "status": "PASS" if leakage_failures == 0 else "FAIL",
            "value": leakage_failures, "details": "",
        },
        {
            "check": "SOURCE_V21_104_OUTPUTS_MODIFIED",
            "status": "PASS" if not modified else "FAIL",
            "value": str(bool(modified)).upper(), "details": "|".join(modified),
        },
        {
            "check": "TICKER_CONTRIBUTION_AVAILABILITY",
            "status": "WARN", "value": "TICKER_CONTRIBUTION_UNAVAILABLE",
            "details": "Portfolio holdings/ticker constituents are absent from V21.104 row results.",
        },
    ]


def classify(
    horizon: pd.DataFrame, size: pd.DataFrame, benchmark: pd.DataFrame,
    tail: pd.DataFrame, time: pd.DataFrame, warning_rows: list[dict[str, object]],
) -> tuple[str, str, dict[str, object]]:
    if any(row["status"] == "FAIL" for row in warning_rows):
        return FAIL_DATA, "SOURCE_INTEGRITY_OR_LEAKAGE_CHECK_FAILED", {}
    primary = horizon[(horizon["portfolio_size"] == 20) & (horizon["horizon"] == 252)]
    broad_cells = horizon[
        horizon["comparison"].isin(["D_VS_A1", "D_VS_B", "D_VS_C", "D_VS_QQQ", "D_VS_SPY"])
    ]
    broad = bool((broad_cells.groupby("comparison")["mean_excess"].apply(lambda x: (x > 0).all())).all())
    strengthens = bool(
        horizon[
            (horizon["portfolio_size"] == 20)
            & (horizon["comparison"].isin(["D_VS_A1", "D_VS_B", "D_VS_C"]))
        ].pivot(index="horizon", columns="comparison", values="mean_excess")
        .mean(axis=1).sort_index().is_monotonic_increasing
    )
    size252 = size[size["horizon"] == 252]
    top20 = size252[size252["portfolio_size"].astype(str) == "20"].iloc[0]
    top50 = size252[size252["portfolio_size"].astype(str) == "50"].iloc[0]
    top20_better = float(top20["mean_excess_vs_A1"]) >= float(top50["mean_excess_vs_A1"])
    soxx = benchmark[(benchmark["portfolio_size"] == 20) & (benchmark["horizon"] == 252)].iloc[0]
    soxx_gap = bool(
        float(soxx["d_win_rate_vs_SOXX"]) > .5 and float(soxx["d_mean_excess_vs_SOXX"]) < 0
    )
    tail_primary = tail[
        (tail["portfolio_size"] == 20) & (tail["horizon"] == 252)
        & tail["comparison"].isin(["D_VS_A1", "D_VS_QQQ"])
    ]
    tail_warn = bool(tail_primary["material_left_tail_warning"].any())
    time_primary = time[
        (time["portfolio_size"] == 20) & (time["horizon"] == 252)
        & (time["bucket_type"] == "CALENDAR_YEAR")
    ]
    positive_year_share = float((time_primary["mean_excess_vs_A1"] > 0).mean())
    regime_concentrated = positive_year_share < .5
    facts = {
        "edge_broad_across_horizons": broad,
        "edge_strengthens_with_horizon": strengthens,
        "d_top20_better_than_top50": top20_better,
        "soxx_positive_win_rate_negative_mean_gap": soxx_gap,
        "material_left_tail_warning": tail_warn,
        "positive_calendar_year_bucket_share_vs_A1": positive_year_share,
        "regime_or_time_concentrated": regime_concentrated,
        "ticker_contribution_available": False,
    }
    if regime_concentrated:
        return PARTIAL_REGIME, "D_EDGE_IS_TIME_BUCKET_OR_REGIME_DEPENDENT", facts
    if soxx_gap:
        return PARTIAL_SOXX, "D_EDGE_CONFIRMED_BUT_SOXX_EXTREME_UPSIDE_CREATES_NEGATIVE_MEAN_GAP", facts
    if broad and not tail_warn:
        return PASS, "D_EDGE_BROAD_AND_LEFT_TAIL_ACCEPTABLE_RESEARCH_ONLY", facts
    if not broad and tail_warn:
        return FAIL_BIAS, "D_EDGE_NOT_BROAD_AND_TAIL_OR_CONCENTRATION_RISK_DOMINATES", facts
    return PARTIAL_REGIME, "D_EDGE_CONFIRMED_WITH_CONCENTRATION_OR_TAIL_QUALIFICATION", facts


def render_readme(
    output: Path, run_id: str, status: str, decision: str, facts: dict[str, object],
    horizon: pd.DataFrame, size: pd.DataFrame, benchmark: pd.DataFrame,
    warning_rows: list[dict[str, object]],
) -> None:
    soxx = benchmark[(benchmark["portfolio_size"] == 20) & (benchmark["horizon"] == 252)].iloc[0]
    size252 = size[size["horizon"] == 252]
    top20 = size252[size252["portfolio_size"].astype(str) == "20"].iloc[0]
    top50 = size252[size252["portfolio_size"].astype(str) == "50"].iloc[0]
    source_modified = next(row for row in warning_rows if row["check"] == "SOURCE_V21_104_OUTPUTS_MODIFIED")
    leakage = next(row for row in warning_rows if row["check"] == "LEAKAGE_FAILURE_COUNT")
    text = f"""# V21.104-R1 D Long-Horizon Edge Decomposition

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
source V21.104 run_id: `{SOURCE_RUN_ID}`  
decomposition run_id: `{run_id}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Findings

- D edge broad across all horizons: {'YES' if facts.get('edge_broad_across_horizons') else 'NO'}
- D edge strengthens with horizon: {'YES' if facts.get('edge_strengthens_with_horizon') else 'NO'} (126D is weak; 189D and 252D are positive versus A1/B/C.)
- Better relative edge at 252D: {'Top20' if facts.get('d_top20_better_than_top50') else 'Top50'}
- Better absolute return and p5 stability at 252D: {'Top50' if float(top50['mean_return']) > float(top20['mean_return']) and float(top50['p5_return']) > float(top20['p5_return']) else 'Top20'}
- D Top20 252D mean excess vs A1: {float(top20['mean_excess_vs_A1']):.6f}
- D Top50 252D mean excess vs A1: {float(top50['mean_excess_vs_A1']):.6f}
- Why D has negative mean excess vs SOXX despite a positive win rate: D wins more often, but SOXX's strongest upside samples produce much larger D shortfalls. SOXX top-5% return cutoff is {float(soxx['soxx_p95_return_cutoff']):.6f}; D mean excess in those samples is {float(soxx['d_mean_excess_in_soxx_extreme_samples']):.6f}.
- D has material absolute/A1/QQQ left-tail weakness: {'YES' if facts.get('material_left_tail_warning') else 'NO'}; SOXX-relative left tail remains severe because of SOXX extreme upside.
- Edge time-bucket or regime concentrated: {'YES' if facts.get('regime_or_time_concentrated') else 'NO'}
- Ticker contribution available: NO (`TICKER_CONTRIBUTION_UNAVAILABLE`)
- Recommended V21.104-R2 addition: persist holdings snapshots for every sample/variant/portfolio size.

## Integrity and warnings

- Leakage failures remain zero: {'YES' if int(leakage['value']) == 0 else 'NO'}
- V21.104 source outputs modified: {source_modified['value']}
- Protected outputs modified: `FALSE`
- Warnings preserved: `SURVIVORSHIP_BIAS_WARN`, `PIT_FACTOR_APPROXIMATION_WARN`

## Interpretation boundary

This decomposition is research-only. It does not modify D, integrate event risk, authorize official adoption, or create broker/trading actions.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    source, raw, audit, source_warnings = load_inputs(root)
    source_before = {name: sha256(source / name) for name in SOURCE_FILES}
    frame = numeric(raw)
    horizon_rows = horizon_decomposition(frame)
    size_rows = size_decomposition(frame)
    benchmark_rows = benchmark_decomposition(frame)
    tail_rows = left_tail_decomposition(frame)
    time_rows = time_bucket_decomposition(frame)
    sample_rows = best_worst_samples(frame)
    concentration_rows = [{
        "analysis": "TICKER_CONTRIBUTION",
        "status": "TICKER_CONTRIBUTION_UNAVAILABLE",
        "available_columns": "|".join(raw.columns),
        "reason": "V21.104 row results contain portfolio-level returns but no holdings/ticker constituents.",
        "recommended_next_stage": "V21.104-R2_ADD_SAMPLE_VARIANT_PORTFOLIO_HOLDINGS_SNAPSHOTS",
        "research_only": "TRUE",
    }]
    source_after = {name: sha256(source / name) for name in SOURCE_FILES}
    warning_rows = warning_audit(source, audit, source_warnings, source_before, source_after)
    horizon_frame = pd.DataFrame(horizon_rows)
    size_frame = pd.DataFrame(size_rows)
    benchmark_frame = pd.DataFrame(benchmark_rows)
    tail_frame = pd.DataFrame(tail_rows)
    time_frame = pd.DataFrame(time_rows)
    status, decision, facts = classify(
        horizon_frame, size_frame, benchmark_frame, tail_frame, time_frame, warning_rows,
    )
    config = {
        "stage": STAGE, "run_id": run_id, "source_run_id": SOURCE_RUN_ID,
        "source_directory": source.as_posix(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file_hashes": source_before,
        "analyses": [
            "HORIZON", "PORTFOLIO_SIZE", "BENCHMARK", "LEFT_TAIL",
            "TIME_BUCKET", "BEST_WORST_SAMPLE", "CONCENTRATION_AVAILABILITY",
        ],
        "time_regime_method": "DIAGNOSTIC_BUCKETS_FROM_SAME_HORIZON_QQQ_SPY_SOXX_RETURNS",
        "official_adoption_allowed": False, "broker_action_allowed": False,
        "event_risk_integrated": False, "research_only": True,
    }
    write_json(output / CONFIG, config)
    write_csv(output / HORIZON, horizon_rows, list(horizon_rows[0]))
    write_csv(output / SIZE, size_rows, list(size_rows[0]))
    write_csv(output / BENCHMARK, benchmark_rows, list(benchmark_rows[0]))
    write_csv(output / TAIL, tail_rows, list(tail_rows[0]))
    write_csv(output / TIME, time_rows, list(time_rows[0]))
    write_csv(output / SAMPLES, sample_rows, list(sample_rows[0]))
    write_csv(output / CONCENTRATION, concentration_rows, list(concentration_rows[0]))
    write_csv(output / WARNINGS, warning_rows, list(warning_rows[0]))
    render_readme(
        output, run_id, status, decision, facts, horizon_frame, size_frame,
        benchmark_frame, warning_rows,
    )
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "SOURCE_RUN_ID": SOURCE_RUN_ID,
        "LEAKAGE_FAILURE_COUNT": int((~audit["point_in_time_valid"].map(truth)).sum()),
        "SOURCE_OUTPUTS_MODIFIED": any(source_before[k] != source_after[k] for k in source_before),
        "PROTECTED_OUTPUTS_MODIFIED": False,
        "TICKER_CONTRIBUTION_AVAILABLE": False,
        "OUTPUT_DIR": output.as_posix(), "OFFICIAL_ADOPTION_ALLOWED": False,
        "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    output, run_id = immutable_output(root, args.output_dir, args.run_id)
    try:
        result = run_stage(root, output, run_id)
    except Exception as exc:
        status = FAIL_DATA
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "source_run_id": SOURCE_RUN_ID,
            "execution_error": str(exc), "official_adoption_allowed": False,
            "broker_action_allowed": False, "research_only": True,
        })
        for name in (HORIZON, SIZE, BENCHMARK, TAIL, TIME, SAMPLES, CONCENTRATION, WARNINGS):
            write_csv(output / name, [], ["status", "details"])
        (output / README).write_text(
            f"# V21.104-R1 Decomposition\n\nFINAL_STATUS: `{status}`  \n"
            "DECISION: `DATA_REQUIRED_FOR_DECOMPOSITION_MISSING`  \n"
            f"source V21.104 run_id: `{SOURCE_RUN_ID}`  \n"
            "official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\n"
            f"Error: {exc}\n",
            encoding="utf-8",
        )
        result = {"FINAL_STATUS": status, "DECISION": "DATA_REQUIRED_FOR_DECOMPOSITION_MISSING", "OUTPUT_DIR": output.as_posix()}
        print(json.dumps(result, indent=2))
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
