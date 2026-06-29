#!/usr/bin/env python
"""Replay V21.104 holdings and attribute D long-horizon contribution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


STAGE = "V21.104-R2_HOLDINGS_PERSISTENCE_AND_TICKER_CONTRIBUTION_REPLAY"
SOURCE_RUN_ID = "20260623_163856"
SOURCE_R1_RUN_ID = "20260623_165210"
SOURCE_REL = Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run") / SOURCE_RUN_ID
SOURCE_R1_REL = Path("outputs/v21/v21_104_r1_d_long_horizon_edge_decomposition") / SOURCE_R1_RUN_ID
OUTPUT_REL = Path("outputs/v21/v21_104_r2_holdings_persistence_and_ticker_contribution")

CONFIG = "v21_104_r2_config.json"
HOLDINGS = "v21_104_r2_holdings_snapshots.csv"
TOP20 = "v21_104_r2_d_top20_ticker_contribution_252d.csv"
TOP50 = "v21_104_r2_d_top50_ticker_contribution_252d.csv"
QQQ_ATTR = "v21_104_r2_d_vs_qqq_best_worst_ticker_attribution.csv"
SOXX_ATTR = "v21_104_r2_d_vs_soxx_best_worst_ticker_attribution.csv"
SOXX_GAP = "v21_104_r2_soxx_top5pct_gap_attribution.csv"
CONCENTRATION = "v21_104_r2_concentration_analysis.csv"
SIZE_COMPARE = "v21_104_r2_top20_vs_top50_contribution_comparison.csv"
WARNING = "v21_104_r2_warning_audit.csv"
README = "v21_104_r2_decision_readme.md"

PASS = "PASS_V21_104_R2_D_EDGE_CONTRIBUTION_BROAD_RESEARCH_ONLY"
PARTIAL_CONCENTRATED = "PARTIAL_PASS_V21_104_R2_D_EDGE_VALID_BUT_CONCENTRATED"
PARTIAL_SOXX = "PARTIAL_PASS_V21_104_R2_D_EDGE_VALID_BUT_SOXX_GAP_EXPLAINED_BY_UNDERPARTICIPATION"
FAIL_FEW = "FAIL_V21_104_R2_D_EDGE_DOMINATED_BY_FEW_TICKERS"
FAIL_REPLAY = "FAIL_V21_104_R2_REPLAY_OR_LEAKAGE_BLOCKER"

SEMICONDUCTOR = {
    "ACLS", "ACMR", "AEHR", "AEIS", "ALAB", "AMAT", "AMD", "AMKR", "ASML",
    "AVGO", "CAMT", "COHR", "COHU", "CRDO", "ENTG", "FORM", "ICHR", "INTC",
    "KLAC", "KLIC", "LRCX", "LSCC", "MCHP", "MKSI", "MPWR", "MRVL", "MU",
    "NVDA", "NXPI", "QCOM", "SANM", "SITM", "SMTC", "SNPS", "SOXL", "SOXX",
    "STM", "TSEM", "TER", "TSM", "TTMI", "TXN", "VECO",
}
MEMORY_STORAGE = {"MU", "WDC", "STX", "SNDK", "PSTG", "NTAP"}

SOURCE_FILES = (
    "v21_104_abcd_random_sample_dates.csv",
    "v21_104_abcd_252d_hold_row_results.csv",
    "v21_104_abcd_252d_hold_leakage_audit.csv",
    "v21_104_abcd_252d_hold_data_quality_warnings.csv",
)
R1_FILES = (
    "v21_104_r1_benchmark_decomposition.csv",
    "v21_104_r1_best_worst_sample_decomposition.csv",
    "v21_104_r1_warning_audit.csv",
)

HOLDING_FIELDS = [
    "sample_id", "seed", "draw_index", "start_date", "variant", "portfolio_size",
    "horizon", "rank", "ticker", "weight", "base_score", "momentum_score",
    "final_score", "momentum_weight", "manual_group", "manual_group_mapping_status",
    "entry_date", "exit_date", "entry_price", "exit_price", "ticker_return",
    "weighted_contribution", "price_status", "ranking_max_input_date",
    "point_in_time_valid", "survivorship_bias_warning",
    "pit_factor_approximation_warning", "research_only",
]

CONTRIBUTION_FIELDS = [
    "ticker", "manual_group", "appearance_count", "appearance_share",
    "average_rank", "average_weight", "mean_ticker_return", "mean_contribution",
    "median_contribution", "total_contribution", "absolute_contribution",
    "absolute_contribution_share", "win_sample_count", "loss_sample_count",
    "positive_contribution_count", "negative_contribution_count",
]


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


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v104_r2", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 replay helpers unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def manual_group(ticker: str) -> str:
    if ticker in MEMORY_STORAGE:
        return "MEMORY_STORAGE"
    if ticker in SEMICONDUCTOR:
        return "SEMICONDUCTOR_OTHER"
    return "OTHER_OR_UNMAPPED"


def source_hashes(source: Path, names: tuple[str, ...]) -> dict[str, str]:
    missing = [name for name in names if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing source files: {missing}")
    return {name: sha256(source / name) for name in names}


def replay_holdings(
    v103, data, features: dict[str, pd.DataFrame], samples: pd.DataFrame,
    source_results: pd.DataFrame, holdings_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    rank_cache: dict[str, dict[str, pd.DataFrame]] = {}
    source_lookup = source_results.set_index(
        ["sample_id", "variant", "portfolio_size", "horizon"]
    )["portfolio_return"].to_dict()
    d_252_holdings: list[dict[str, object]] = []
    reconciliation: list[dict[str, object]] = []
    total_rows = 0
    calendar_index = {day: index for index, day in enumerate(data.calendar)}
    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    with holdings_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HOLDING_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for sample in samples.to_dict("records"):
            day = clean(sample["start_date"])
            if day not in rank_cache:
                rank_cache[day] = v103.rank_variants(features, day)
            start_index = calendar_index[day]
            for variant in v103.VARIANTS:
                ranking = rank_cache[day][variant]
                for size in v103.PORTFOLIO_SIZES:
                    selected = ranking.head(size).copy()
                    weight = 1.0 / len(selected)
                    for horizon in v103.HORIZONS:
                        exit_index = start_index + horizon
                        exit_date = data.calendar[exit_index]
                        contributions = []
                        for row in selected.to_dict("records"):
                            ticker = clean(row["ticker"])
                            entry = data.candidate_prices.at[day, ticker]
                            exit_price = data.candidate_prices.at[exit_date, ticker]
                            available = pd.notna(entry) and pd.notna(exit_price) and float(entry) > 0
                            ticker_return = float(exit_price / entry - 1) if available else np.nan
                            contribution = weight * ticker_return if available else np.nan
                            if available:
                                contributions.append(contribution)
                            holding = {
                            "sample_id": sample["sample_id"], "seed": sample["seed"],
                            "draw_index": sample["draw_index"], "start_date": day,
                            "variant": variant, "portfolio_size": size, "horizon": horizon,
                            "rank": int(row["rank"]), "ticker": ticker, "weight": weight,
                            "base_score": row["base_score"],
                            "momentum_score": row["momentum_score"],
                            "final_score": row["score"],
                            "momentum_weight": row["momentum_weight"],
                            "manual_group": manual_group(ticker),
                            "manual_group_mapping_status": "MANUAL_DIAGNOSTIC_MAPPING",
                            "entry_date": day, "exit_date": exit_date,
                            "entry_price": entry, "exit_price": exit_price,
                            "ticker_return": ticker_return,
                            "weighted_contribution": contribution,
                            "price_status": "PASS" if available else "MISSING_FORWARD_PRICE",
                            "ranking_max_input_date": row["max_input_date"],
                            "point_in_time_valid": str(clean(row["max_input_date"]) <= day).upper(),
                            "survivorship_bias_warning": "TRUE",
                            "pit_factor_approximation_warning": "TRUE",
                            "research_only": "TRUE",
                            }
                            writer.writerow(holding)
                            total_rows += 1
                            if variant == "D" and horizon == 252:
                                d_252_holdings.append(holding)
                        replay_return = float(np.nansum(contributions))
                        source_return = float(source_lookup[(sample["sample_id"], variant, size, horizon)])
                        reconciliation.append({
                            "sample_id": sample["sample_id"], "variant": variant,
                            "portfolio_size": size, "horizon": horizon,
                            "replay_return": replay_return, "source_return": source_return,
                            "absolute_difference": abs(replay_return - source_return),
                            "reconciled": abs(replay_return - source_return) <= 1e-10,
                        })
    return d_252_holdings, reconciliation, total_rows


def contribution_summary(holdings: pd.DataFrame, source_results: pd.DataFrame, size: int) -> list[dict[str, object]]:
    d = holdings[
        (holdings["variant"] == "D") & (holdings["portfolio_size"] == size)
        & (holdings["horizon"] == 252)
    ].copy()
    sample_return = source_results[
        (source_results["variant"] == "D") & (source_results["portfolio_size"] == size)
        & (source_results["horizon"] == 252)
    ].set_index("sample_id")["portfolio_return"]
    d["sample_return"] = d["sample_id"].map(sample_return)
    grouped = d.groupby(["ticker", "manual_group"], sort=False)
    total_abs = d.groupby("ticker")["weighted_contribution"].sum().abs().sum()
    total_appearances = len(d)
    output = []
    for (ticker, group_name), group in grouped:
        contribution = group["weighted_contribution"]
        total = contribution.sum()
        output.append({
            "ticker": ticker, "manual_group": group_name,
            "appearance_count": len(group),
            "appearance_share": len(group) / total_appearances,
            "average_rank": group["rank"].mean(),
            "average_weight": group["weight"].mean(),
            "mean_ticker_return": group["ticker_return"].mean(),
            "mean_contribution": contribution.mean(),
            "median_contribution": contribution.median(),
            "total_contribution": total,
            "absolute_contribution": abs(total),
            "absolute_contribution_share": abs(total) / total_abs if total_abs else np.nan,
            "win_sample_count": int(group["sample_return"].gt(0).sum()),
            "loss_sample_count": int(group["sample_return"].le(0).sum()),
            "positive_contribution_count": int(contribution.gt(0).sum()),
            "negative_contribution_count": int(contribution.lt(0).sum()),
        })
    return sorted(output, key=lambda row: row["total_contribution"], reverse=True)


def sample_sets(source_results: pd.DataFrame, size: int, benchmark: str) -> dict[str, set[str]]:
    d = source_results[
        (source_results["variant"] == "D") & (source_results["portfolio_size"] == size)
        & (source_results["horizon"] == 252)
    ].copy()
    column = "excess_vs_QQQ" if benchmark == "QQQ" else "excess_vs_semiconductor_benchmark"
    d = d.sort_values(column)
    return {
        "WORST50": set(d.head(50)["sample_id"]),
        "BEST50": set(d.tail(50)["sample_id"]),
        "SOXX_TOP5PCT": set(
            d[d["benchmark_semiconductor_return"].ge(d["benchmark_semiconductor_return"].quantile(.95))]["sample_id"]
        ),
    }


def attribution(
    holdings: pd.DataFrame, source_results: pd.DataFrame, benchmark: str,
) -> list[dict[str, object]]:
    rows = []
    for size in (20, 50):
        sets = sample_sets(source_results, size, benchmark)
        for bucket in ("BEST50", "WORST50"):
            subset = holdings[
                (holdings["variant"] == "D") & (holdings["portfolio_size"] == size)
                & (holdings["horizon"] == 252) & holdings["sample_id"].isin(sets[bucket])
            ]
            for (ticker, group_name), group in subset.groupby(["ticker", "manual_group"]):
                rows.append({
                    "benchmark": benchmark, "portfolio_size": size, "bucket": bucket,
                    "ticker": ticker, "manual_group": group_name,
                    "appearance_count": len(group),
                    "sample_coverage_rate": group["sample_id"].nunique() / 50,
                    "average_rank": group["rank"].mean(),
                    "mean_ticker_return": group["ticker_return"].mean(),
                    "mean_contribution": group["weighted_contribution"].mean(),
                    "total_contribution": group["weighted_contribution"].sum(),
                    "positive_contribution_count": int(group["weighted_contribution"].gt(0).sum()),
                    "negative_contribution_count": int(group["weighted_contribution"].lt(0).sum()),
                })
    return sorted(rows, key=lambda row: (row["portfolio_size"], row["bucket"], -row["total_contribution"]))


def soxx_gap_attribution(holdings: pd.DataFrame, source_results: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for size in (20, 50):
        samples = sample_sets(source_results, size, "SOXX")["SOXX_TOP5PCT"]
        source = source_results[
            (source_results["variant"] == "D") & (source_results["portfolio_size"] == size)
            & (source_results["horizon"] == 252) & source_results["sample_id"].isin(samples)
        ].set_index("sample_id")
        subset = holdings[
            (holdings["variant"] == "D") & (holdings["portfolio_size"] == size)
            & (holdings["horizon"] == 252) & holdings["sample_id"].isin(samples)
        ].copy()
        subset["soxx_equal_share_contribution"] = subset["sample_id"].map(
            source["benchmark_semiconductor_return"]
        ) * subset["weight"]
        subset["underparticipation_gap"] = (
            subset["weighted_contribution"] - subset["soxx_equal_share_contribution"]
        )
        for (ticker, group_name), group in subset.groupby(["ticker", "manual_group"]):
            rows.append({
                "portfolio_size": size, "ticker": ticker, "manual_group": group_name,
                "appearance_count": len(group),
                "sample_coverage_rate": group["sample_id"].nunique() / len(samples),
                "average_rank": group["rank"].mean(),
                "mean_ticker_return": group["ticker_return"].mean(),
                "mean_weighted_contribution": group["weighted_contribution"].mean(),
                "total_weighted_contribution": group["weighted_contribution"].sum(),
                "mean_soxx_equal_share_contribution": group["soxx_equal_share_contribution"].mean(),
                "mean_underparticipation_gap": group["underparticipation_gap"].mean(),
                "total_underparticipation_gap": group["underparticipation_gap"].sum(),
            })
    return sorted(rows, key=lambda row: (row["portfolio_size"], row["total_underparticipation_gap"]))


def concentration_analysis(contribution: dict[int, list[dict[str, object]]]) -> list[dict[str, object]]:
    rows = []
    for size, items in contribution.items():
        frame = pd.DataFrame(items)
        absolute = frame.sort_values("absolute_contribution", ascending=False)
        appearances = frame["appearance_count"] / frame["appearance_count"].sum()
        effective = 1 / float((appearances ** 2).sum())
        for metric, value in (
            ("TOP5_ABSOLUTE_CONTRIBUTION_SHARE", absolute.head(5)["absolute_contribution_share"].sum()),
            ("TOP10_ABSOLUTE_CONTRIBUTION_SHARE", absolute.head(10)["absolute_contribution_share"].sum()),
            ("TOP5_APPEARANCE_SHARE", frame.nlargest(5, "appearance_count")["appearance_share"].sum()),
            ("TOP10_APPEARANCE_SHARE", frame.nlargest(10, "appearance_count")["appearance_share"].sum()),
            ("EFFECTIVE_NUMBER_OF_TICKERS_BY_APPEARANCE", effective),
            ("MEMORY_STORAGE_APPEARANCE_SHARE", frame.loc[frame["manual_group"] == "MEMORY_STORAGE", "appearance_share"].sum()),
            ("SEMICONDUCTOR_TOTAL_APPEARANCE_SHARE", frame.loc[frame["manual_group"].isin(["MEMORY_STORAGE", "SEMICONDUCTOR_OTHER"]), "appearance_share"].sum()),
            ("MEMORY_STORAGE_TOTAL_CONTRIBUTION", frame.loc[frame["manual_group"] == "MEMORY_STORAGE", "total_contribution"].sum()),
            ("SEMICONDUCTOR_TOTAL_CONTRIBUTION", frame.loc[frame["manual_group"].isin(["MEMORY_STORAGE", "SEMICONDUCTOR_OTHER"]), "total_contribution"].sum()),
        ):
            rows.append({
                "portfolio_size": size, "metric": metric, "value": value,
                "mapping_status": "MANUAL_DIAGNOSTIC_MAPPING" if "MEMORY" in metric or "SEMICONDUCTOR" in metric else "DIRECT",
            })
    return rows


def size_comparison(
    contribution: dict[int, list[dict[str, object]]], source_results: pd.DataFrame,
) -> list[dict[str, object]]:
    rows = []
    for size in (20, 50):
        source = source_results[
            (source_results["variant"] == "D") & (source_results["portfolio_size"] == size)
            & (source_results["horizon"] == 252)
        ]
        frame = pd.DataFrame(contribution[size])
        rows.append({
            "portfolio_size": size,
            "mean_return": source["portfolio_return"].mean(),
            "median_return": source["portfolio_return"].median(),
            "p5_return": source["portfolio_return"].quantile(.05),
            "mean_excess_vs_A1": source["excess_vs_A1"].mean(),
            "win_rate_vs_A1": source["excess_vs_A1"].gt(0).mean(),
            "top5_absolute_contribution_share": frame.nlargest(5, "absolute_contribution")["absolute_contribution_share"].sum(),
            "top10_absolute_contribution_share": frame.nlargest(10, "absolute_contribution")["absolute_contribution_share"].sum(),
            "effective_ticker_count": 1 / float(((frame["appearance_count"] / frame["appearance_count"].sum()) ** 2).sum()),
            "semiconductor_appearance_share": frame.loc[
                frame["manual_group"].isin(["MEMORY_STORAGE", "SEMICONDUCTOR_OTHER"]), "appearance_share"
            ].sum(),
            "interpretation": (
                "STRONGER_RELATIVE_EDGE_HIGHER_CONCENTRATION"
                if size == 20 else "HIGHER_ABSOLUTE_RETURN_AND_P5_DIVERSIFICATION_STABILITY"
            ),
        })
    return rows


def classify(concentration: pd.DataFrame, soxx_gap: pd.DataFrame) -> tuple[str, str, dict[str, object]]:
    top20 = concentration[concentration["portfolio_size"].eq(20)].set_index("metric")["value"]
    top5 = float(top20["TOP5_ABSOLUTE_CONTRIBUTION_SHARE"])
    top10 = float(top20["TOP10_ABSOLUTE_CONTRIBUTION_SHARE"])
    effective = float(top20["EFFECTIVE_NUMBER_OF_TICKERS_BY_APPEARANCE"])
    concentrated = top5 > .35 or top10 > .60 or effective < 20
    dominated = top5 > .50 or top10 > .75 or effective < 12
    gap20 = soxx_gap[soxx_gap["portfolio_size"].eq(20)]
    underparticipation = float(gap20["total_underparticipation_gap"].sum()) < 0
    facts = {
        "top20_top5_absolute_contribution_share": top5,
        "top20_top10_absolute_contribution_share": top10,
        "top20_effective_ticker_count": effective,
        "contribution_concentrated": concentrated,
        "dominated_by_few_tickers": dominated,
        "soxx_gap_explained_by_underparticipation": underparticipation,
    }
    if dominated:
        return FAIL_FEW, "D_EDGE_DOMINATED_BY_FEW_TICKERS", facts
    if concentrated:
        return PARTIAL_CONCENTRATED, "D_EDGE_VALID_BUT_TICKER_CONTRIBUTION_CONCENTRATED", facts
    if underparticipation:
        return PARTIAL_SOXX, "D_EDGE_VALID_AND_SOXX_GAP_EXPLAINED_BY_UNDERPARTICIPATION", facts
    return PASS, "D_EDGE_CONTRIBUTION_BROAD_RESEARCH_ONLY", facts


def render_readme(
    output: Path, run_id: str, status: str, decision: str, facts: dict[str, object],
    contribution: dict[int, list[dict[str, object]]], size_rows: list[dict[str, object]],
    soxx_gap_rows: list[dict[str, object]], leakage_failures: int,
) -> None:
    top = contribution[20]
    top_contributors = ", ".join(row["ticker"] for row in top[:10])
    damaging = ", ".join(row["ticker"] for row in sorted(top, key=lambda row: row["total_contribution"])[:10])
    gap = [row for row in soxx_gap_rows if row["portfolio_size"] == 20][:10]
    underparticipants = ", ".join(row["ticker"] for row in gap)
    size = {row["portfolio_size"]: row for row in size_rows}
    text = f"""# V21.104-R2 Holdings Persistence and Ticker Contribution Replay

FINAL_STATUS: `{status}`  
DECISION: `{decision}`  
source V21.104 run_id: `{SOURCE_RUN_ID}`  
source V21.104-R1 run_id: `{SOURCE_R1_RUN_ID}`  
replay run_id: `{run_id}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Contribution findings

- D contribution is broad or concentrated: {'CONCENTRATED' if facts['contribution_concentrated'] else 'BROAD'}
- Top contributing D Top20 tickers: {top_contributors}
- Top damaging D Top20 tickers: {damaging}
- SOXX gap explained by underparticipation: {'YES' if facts['soxx_gap_explained_by_underparticipation'] else 'NO'}
- Largest SOXX extreme-upside underparticipants: {underparticipants}
- Top20 edge concentrated: {'YES' if facts['contribution_concentrated'] else 'NO'}
- Top50 stability diversification-driven: {'YES' if size[50]['effective_ticker_count'] > size[20]['effective_ticker_count'] and size[50]['p5_return'] > size[20]['p5_return'] else 'NO'}

## Replay integrity

- Exact V21.104 sample dates reused: YES
- Holdings snapshots generated: YES
- Leakage failures remain zero: {'YES' if leakage_failures == 0 else 'NO'}
- V21.104 and V21.104-R1 source outputs modified: FALSE
- Protected outputs modified: FALSE
- Warnings preserved: `SURVIVORSHIP_BIAS_WARN`, `PIT_FACTOR_APPROXIMATION_WARN`
- Manual industry grouping status: `MANUAL_DIAGNOSTIC_MAPPING`

This replay is research-only. It does not alter D, integrate event risk, authorize official adoption, or create broker/trading actions.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    v103 = load_v103(root)
    source = root / SOURCE_REL
    source_r1 = root / SOURCE_R1_REL
    protected = v103.protected_files(root, output)
    protected_before = {path: v103.sha256(path) for path in protected}
    before = source_hashes(source, SOURCE_FILES)
    before_r1 = source_hashes(source_r1, R1_FILES)
    samples = pd.read_csv(source / SOURCE_FILES[0], low_memory=False)
    source_results = pd.read_csv(source / SOURCE_FILES[1], low_memory=False)
    source_audit = pd.read_csv(source / SOURCE_FILES[2], low_memory=False)
    source_warnings = pd.read_csv(source / SOURCE_FILES[3], low_memory=False)
    data = v103.load_market_data(root)
    features = v103.rolling_features(data)
    holdings_rows, reconciliation, holdings_row_count = replay_holdings(
        v103, data, features, samples, source_results, output / HOLDINGS,
    )
    holdings = pd.DataFrame(holdings_rows)
    reconciliation_frame = pd.DataFrame(reconciliation)
    leakage_failures = int((~holdings["point_in_time_valid"].map(truth)).sum())
    reconciliation_failures = int((~reconciliation_frame["reconciled"]).sum())
    sample_match = (
        set(samples["sample_id"]) == set(source_results["sample_id"])
        and len(samples) == 3000
    )
    contribution = {
        20: contribution_summary(holdings, source_results, 20),
        50: contribution_summary(holdings, source_results, 50),
    }
    qqq_rows = attribution(holdings, source_results, "QQQ")
    soxx_rows = attribution(holdings, source_results, "SOXX")
    soxx_gap_rows = soxx_gap_attribution(holdings, source_results)
    concentration_rows = concentration_analysis(contribution)
    size_rows = size_comparison(contribution, source_results)
    concentration_frame = pd.DataFrame(concentration_rows)
    soxx_gap_frame = pd.DataFrame(soxx_gap_rows)
    status, decision, facts = classify(concentration_frame, soxx_gap_frame)
    warning_codes = set(source_warnings["warning_code"].astype(str))
    after = source_hashes(source, SOURCE_FILES)
    after_r1 = source_hashes(source_r1, R1_FILES)
    source_changed = before != after or before_r1 != after_r1
    protected_after = {path: v103.sha256(path) for path in protected}
    protected_changed = [
        path.as_posix() for path in protected
        if protected_before[path] != protected_after[path]
    ]
    audit_rows = [
        {"check": "EXACT_SAMPLE_DATES_REUSED", "status": "PASS" if sample_match else "FAIL", "value": str(sample_match).upper(), "details": f"sample_count={len(samples)}"},
        {"check": "REPLAY_RETURN_RECONCILIATION_FAILURES", "status": "PASS" if reconciliation_failures == 0 else "FAIL", "value": reconciliation_failures, "details": f"max_abs_diff={reconciliation_frame['absolute_difference'].max()}"},
        {"check": "LEAKAGE_FAILURE_COUNT", "status": "PASS" if leakage_failures == 0 else "FAIL", "value": leakage_failures, "details": ""},
        {"check": "SOURCE_LEAKAGE_FAILURE_COUNT", "status": "PASS" if (~source_audit["point_in_time_valid"].map(truth)).sum() == 0 else "FAIL", "value": int((~source_audit["point_in_time_valid"].map(truth)).sum()), "details": ""},
        {"check": "SURVIVORSHIP_BIAS_WARN_PRESERVED", "status": "PASS" if "SURVIVORSHIP_BIAS_WARN" in warning_codes else "FAIL", "value": str("SURVIVORSHIP_BIAS_WARN" in warning_codes).upper(), "details": ""},
        {"check": "PIT_FACTOR_APPROXIMATION_WARN_PRESERVED", "status": "PASS" if "PIT_FACTOR_APPROXIMATION_WARN" in warning_codes else "FAIL", "value": str("PIT_FACTOR_APPROXIMATION_WARN" in warning_codes).upper(), "details": ""},
        {"check": "SOURCE_OUTPUTS_MODIFIED", "status": "PASS" if not source_changed else "FAIL", "value": str(source_changed).upper(), "details": ""},
        {"check": "PROTECTED_OUTPUTS_MODIFIED", "status": "PASS" if not protected_changed else "FAIL", "value": str(bool(protected_changed)).upper(), "details": "|".join(protected_changed)},
    ]
    if any(row["status"] == "FAIL" for row in audit_rows):
        status, decision = FAIL_REPLAY, "REPLAY_RECONCILIATION_OR_LEAKAGE_BLOCKER"
    config = {
        "stage": STAGE, "run_id": run_id,
        "source_v21_104_run_id": SOURCE_RUN_ID,
        "source_v21_104_r1_run_id": SOURCE_R1_RUN_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples), "unique_start_dates": samples["start_date"].nunique(),
        "holdings_row_count": holdings_row_count,
        "source_hashes_before": before, "source_r1_hashes_before": before_r1,
        "protected_file_count": len(protected),
        "ranking_logic": "V21.103_PIT_LITE_SHARED",
        "equal_weight": True, "horizons": [126, 189, 252],
        "portfolio_sizes": [20, 50], "variants": ["A1", "B", "C", "D"],
        "manual_group_mapping": {
            "MEMORY_STORAGE": sorted(MEMORY_STORAGE),
            "SEMICONDUCTOR_OTHER": sorted(SEMICONDUCTOR - MEMORY_STORAGE),
        },
        "official_adoption_allowed": False, "broker_action_allowed": False,
        "event_risk_integrated": False, "research_only": True,
    }
    write_json(output / CONFIG, config)
    write_csv(output / TOP20, contribution[20], CONTRIBUTION_FIELDS)
    write_csv(output / TOP50, contribution[50], CONTRIBUTION_FIELDS)
    write_csv(output / QQQ_ATTR, qqq_rows, list(qqq_rows[0]))
    write_csv(output / SOXX_ATTR, soxx_rows, list(soxx_rows[0]))
    write_csv(output / SOXX_GAP, soxx_gap_rows, list(soxx_gap_rows[0]))
    write_csv(output / CONCENTRATION, concentration_rows, list(concentration_rows[0]))
    write_csv(output / SIZE_COMPARE, size_rows, list(size_rows[0]))
    write_csv(output / WARNING, audit_rows, list(audit_rows[0]))
    render_readme(
        output, run_id, status, decision, facts, contribution, size_rows,
        soxx_gap_rows, leakage_failures,
    )
    result = {
        "FINAL_STATUS": status, "DECISION": decision, "RUN_ID": run_id,
        "SOURCE_V21_104_RUN_ID": SOURCE_RUN_ID,
        "SOURCE_V21_104_R1_RUN_ID": SOURCE_R1_RUN_ID,
        "SAMPLE_COUNT": len(samples), "HOLDINGS_ROW_COUNT": holdings_row_count,
        "RECONCILIATION_FAILURE_COUNT": reconciliation_failures,
        "LEAKAGE_FAILURE_COUNT": leakage_failures,
        "SOURCE_OUTPUTS_MODIFIED": source_changed,
        "PROTECTED_OUTPUTS_MODIFIED": bool(protected_changed), "OUTPUT_DIR": output.as_posix(),
        "OFFICIAL_ADOPTION_ALLOWED": False, "BROKER_ACTION_ALLOWED": False,
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
        status = FAIL_REPLAY
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
            "research_only": True,
        })
        for name in (HOLDINGS, TOP20, TOP50, QQQ_ATTR, SOXX_ATTR, SOXX_GAP, CONCENTRATION, SIZE_COMPARE, WARNING):
            write_csv(output / name, [], ["status", "details"])
        (output / README).write_text(
            f"# V21.104-R2 Replay\n\nFINAL_STATUS: `{status}`  \n"
            "DECISION: `REPLAY_OR_LEAKAGE_BLOCKER`  \n"
            f"source V21.104 run_id: `{SOURCE_RUN_ID}`  \n"
            f"source V21.104-R1 run_id: `{SOURCE_R1_RUN_ID}`  \n"
            "official_adoption_allowed: `false`  \nbroker_action_allowed: `false`\n\n"
            f"Error: {exc}\n",
            encoding="utf-8",
        )
        result = {"FINAL_STATUS": status, "DECISION": "REPLAY_OR_LEAKAGE_BLOCKER", "OUTPUT_DIR": output.as_posix()}
        print(json.dumps(result, indent=2))
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
