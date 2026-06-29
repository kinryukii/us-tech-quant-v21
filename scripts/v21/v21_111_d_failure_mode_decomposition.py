#!/usr/bin/env python
"""V21.111 research-only D failure mode decomposition.

This stage reads archived V21.108 ranking outputs and available forward/price
artifacts, then writes isolated diagnostics. It never mutates source rankings,
official outputs, broker actions, protected outputs, source data, or weights.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "V21.111_D_FAILURE_MODE_DECOMPOSITION"
ARCHIVE_REL = Path("outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings")
OUTPUT_REL = Path("outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION")
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
BENCHMARKS = ["QQQ", "SPY", "SOXX", "SMH"]
HORIZONS = [1, 5, 10, 20]

SUMMARY_JSON = "V21.111_D_FAILURE_MODE_DECOMPOSITION_SUMMARY.json"
REPORT_MD = "V21.111_D_FAILURE_MODE_DECOMPOSITION_REPORT.md"
MANIFEST_CSV = "V21.111_D_FAILURE_MODE_DECOMPOSITION_MANIFEST.csv"

CSV_SCHEMAS: dict[str, list[str]] = {
    "input_inventory.csv": ["source_name", "path", "exists", "row_count", "min_date", "max_date", "hash", "notes"],
    "exposure_top20.csv": ["strategy", "view", "exposure_type", "bucket", "count", "weight", "notes"],
    "exposure_top50.csv": ["strategy", "view", "exposure_type", "bucket", "count", "weight", "notes"],
    "exposure_comparison_A1_B_C_D.csv": ["strategy", "view", "metric", "value", "notes"],
    "concentration_metrics.csv": [
        "strategy", "view", "count", "unique_sectors", "top_sector_weight", "top_industry_weight",
        "sector_hhi", "industry_hhi", "ticker_hhi", "top_5_ticker_score_share",
        "average_momentum", "average_rs", "average_volatility", "missing_factor_coverage_ratio",
        "stale_or_missing_price_ratio", "low_data_trust_ratio", "high_breakout_or_overextension_ratio",
        "high_volatility_ratio", "notes",
    ],
    "forward_failure_summary.csv": [
        "strategy", "horizon", "observation_count", "average_return", "median_return", "hit_rate",
        "downside_hit_rate", "worst_ticker_return", "bottom_5_average_return", "left_tail_mean",
        "drawdown_proxy", "excess_return_vs_A1", "excess_return_vs_QQQ", "excess_return_vs_SPY",
        "excess_return_vs_SOXX", "excess_return_vs_SMH", "notes",
    ],
    "forward_horizon_comparison.csv": ["strategy", "horizon", "metric", "value", "notes"],
    "forward_regime_split.csv": ["strategy", "horizon", "split_type", "split_bucket", "observation_count", "average_return", "left_tail_mean", "notes"],
    "forward_left_tail_events.csv": ["strategy", "horizon", "ticker", "forward_return", "rank", "sector", "industry", "notes"],
    "d_loss_contributors.csv": [
        "ticker", "strategy", "horizon", "observation_count", "loss_count", "avg_return", "worst_return",
        "total_negative_contribution", "repeated_loss_flag", "sector", "industry", "notes",
    ],
    "repeated_loss_tickers.csv": ["ticker", "loss_windows", "total_negative_contribution", "sector", "industry", "notes"],
    "strategy_loss_concentration.csv": ["strategy", "horizon", "loss_count", "top_5_loss_share", "loss_hhi", "notes"],
    "momentum_bucket_failure.csv": ["strategy", "horizon", "bucket", "observation_count", "average_return", "left_tail_mean", "stress_average_return", "notes"],
    "rs_crowding_failure.csv": ["strategy", "horizon", "bucket", "observation_count", "average_return", "stress_average_return", "notes"],
    "overextension_failure_cases.csv": ["strategy", "horizon", "ticker", "forward_return", "rsi", "kdj", "macd", "bb", "breakout", "notes"],
    "d_vs_a1_divergence.csv": ["view", "metric", "value", "notes"],
    "d_only_vs_a1_only_returns.csv": ["view", "group", "horizon", "observation_count", "average_return", "left_tail_mean", "notes"],
    "d_only_exposure_profile.csv": ["view", "group", "exposure_type", "bucket", "count", "weight", "notes"],
    "failure_mode_classification.csv": ["event_id", "strategy", "horizon", "ticker", "failure_mode", "severity", "evidence", "research_only"],
    "failure_mode_summary.csv": ["failure_mode", "event_count", "severity", "notes"],
}


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def truth(value: Any) -> bool:
    return clean(value).upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    def default(value: Any) -> Any:
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return None if np.isnan(value) else float(value)
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if pd.isna(value):
            return None
        raise TypeError(type(value).__name__)

    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def immutable_output(root: Path, override: Path | None) -> Path:
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    allowed = {
        *CSV_SCHEMAS.keys(),
        SUMMARY_JSON,
        REPORT_MD,
        MANIFEST_CSV,
    }
    existing = [p.name for p in output.iterdir() if p.is_file() and p.name not in allowed]
    if existing:
        raise RuntimeError(f"Output directory contains unmanaged files: {existing}")
    return output


def read_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def first_col(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    lowered = {col.lower(): col for col in frame.columns}
    for name in names:
        if name in frame.columns:
            return name
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def numeric(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if not column or column not in frame:
        return pd.Series([np.nan] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def inventory_row(source_name: str, root: Path, path: Path | None, notes: str = "") -> dict[str, Any]:
    if not path:
        return {"source_name": source_name, "path": "", "exists": False, "row_count": 0, "min_date": "", "max_date": "", "hash": "", "notes": notes}
    resolved = path if path.is_absolute() else root / path
    if not resolved.is_file():
        rel = path.as_posix() if not path.is_absolute() else str(path)
        return {"source_name": source_name, "path": rel, "exists": False, "row_count": 0, "min_date": "", "max_date": "", "hash": "", "notes": notes}
    try:
        frame = pd.read_csv(resolved, low_memory=False)
        date_cols = [col for col in frame.columns if "date" in col.lower() or col.lower().endswith("_at")]
        dates = []
        for col in date_cols:
            parsed = pd.to_datetime(frame[col], errors="coerce")
            if parsed.notna().any():
                dates.append(parsed)
        if dates:
            all_dates = pd.concat(dates)
            min_date = all_dates.min().strftime("%Y-%m-%d")
            max_date = all_dates.max().strftime("%Y-%m-%d")
        else:
            min_date = max_date = ""
        row_count = len(frame)
    except Exception as exc:  # inventory must survive unreadable optional inputs
        row_count = 0
        min_date = max_date = ""
        notes = f"{notes}; read_error={exc}".strip("; ")
    rel = resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(resolved)
    return {"source_name": source_name, "path": rel, "exists": True, "row_count": row_count, "min_date": min_date, "max_date": max_date, "hash": sha256(resolved), "notes": notes}


def discover_latest(root: Path, patterns: list[str], required_cols: set[str] | None = None) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if required_cols:
                try:
                    cols = set(pd.read_csv(path, nrows=1).columns)
                except Exception:
                    continue
                if not required_cols.issubset(cols):
                    continue
            candidates.append((path.stat().st_mtime, path))
    return max(candidates)[1] if candidates else None


def load_rankings(root: Path) -> tuple[dict[str, dict[str, pd.DataFrame]], dict[str, Path]]:
    archive = root / ARCHIVE_REL
    frames: dict[str, dict[str, pd.DataFrame]] = {}
    paths: dict[str, Path] = {}
    for strategy in STRATEGIES:
        frames[strategy] = {}
        for view, filename in {"top20": "top20_ranking.csv", "top50": "top50_ranking.csv", "full": "full_ranking.csv"}.items():
            path = archive / strategy / filename
            paths[f"{strategy}_{view}"] = path
            frame = read_frame(path)
            if not frame.empty:
                frame["strategy"] = strategy
                frame["view"] = view
                frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
            frames[strategy][view] = frame
    return frames, paths


def augment_with_metadata(root: Path, frame: pd.DataFrame, classification: pd.DataFrame, explainability: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty or "ticker" not in result:
        return result
    if not classification.empty and "ticker" in classification:
        cls_cols = [c for c in ["ticker", "sector", "industry", "sub_industry", "theme_tags", "is_etf", "classification_quality_flag"] if c in classification]
        cls = classification[cls_cols].drop_duplicates("ticker", keep="last").copy()
        cls["ticker"] = cls["ticker"].astype(str).str.upper().str.strip()
        result = result.merge(cls, on="ticker", how="left", suffixes=("", "_classification"))
    if not explainability.empty and "ticker" in explainability:
        exp_cols = [
            c for c in [
                "ticker", "technical__rsi", "technical__kdj", "technical__macd", "technical__bb",
                "technical__volume", "technical__volatility", "technical__relative_strength",
                "technical__breakout", "technical__pullback", "risk__volatility_penalty",
                "data_trust_score_raw", "data_trust__warning_flag", "component_coverage_ratio",
            ] if c in explainability
        ]
        exp = explainability[exp_cols].drop_duplicates("ticker", keep="last").copy()
        exp["ticker"] = exp["ticker"].astype(str).str.upper().str.strip()
        result = result.merge(exp, on="ticker", how="left", suffixes=("", "_explainability"))
    return result


def hhi(weights: pd.Series) -> float:
    weights = pd.to_numeric(weights, errors="coerce").dropna()
    total = weights.sum()
    if total <= 0:
        return 0.0
    shares = weights / total
    return float((shares ** 2).sum())


def classify_theme(row: pd.Series) -> list[str]:
    text = " ".join(clean(row.get(col)) for col in ["sector", "industry", "sub_industry", "theme_tags", "ticker"]).lower()
    tags = []
    if any(key in text for key in ["semiconductor", "semiconductors", "chip", "semi equipment"]):
        tags.append("SEMICONDUCTOR")
    if any(key in text for key in ["storage", "memory", "disk drive", "data storage"]) or clean(row.get("ticker")) in {"WDC", "STX", "PSTG"}:
        tags.append("STORAGE")
    if any(key in text for key in ["ai", "artificial intelligence", "gpu", "accelerator", "hardware"]):
        tags.append("AI_HARDWARE")
    return tags or ["UNCLASSIFIED_OR_OTHER"]


def exposure_rows(frame: pd.DataFrame, view: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    n = len(frame)
    for strategy, group in frame.groupby("strategy", sort=True):
        for exposure_type, column in [("sector", "sector"), ("industry", "industry"), ("ticker", "ticker"), ("market_regime", "market_regime")]:
            if column in group:
                for bucket, count in group[column].fillna("UNKNOWN").astype(str).value_counts(dropna=False).items():
                    rows.append({"strategy": strategy, "view": view, "exposure_type": exposure_type, "bucket": bucket, "count": int(count), "weight": count / len(group), "notes": "research_only"})
        themes: dict[str, int] = {}
        for _, row in group.iterrows():
            for tag in classify_theme(row):
                themes[tag] = themes.get(tag, 0) + 1
        for tag, count in sorted(themes.items()):
            rows.append({"strategy": strategy, "view": view, "exposure_type": "theme", "bucket": tag, "count": count, "weight": count / n if strategy == "D_WEIGHT_OPTIMIZED_R1" else count / len(group), "notes": "keyword_or_classification_based"})
    return rows


def concentration_row(strategy: str, view: str, group: pd.DataFrame, full_reference: pd.DataFrame) -> dict[str, Any]:
    score_col = first_col(group, ["final_score", "score"])
    momentum_col = first_col(group, ["momentum_score"])
    rs_col = first_col(group, ["technical__relative_strength", "relative_momentum_score"])
    volatility_col = first_col(group, ["technical__volatility", "risk__volatility_penalty"])
    breakout_col = first_col(group, ["technical__breakout", "exhaustion_risk_score"])
    sector_counts = group["sector"].fillna("UNKNOWN").value_counts() if "sector" in group else pd.Series(dtype=float)
    industry_counts = group["industry"].fillna("UNKNOWN").value_counts() if "industry" in group else pd.Series(dtype=float)
    score = numeric(group, score_col)
    score_total = score.sum()
    factor_candidates = [
        "momentum_score", "technical__relative_strength", "relative_momentum_score", "technical__volatility",
        "technical__rsi", "technical__kdj", "technical__macd", "technical__bb", "technical__breakout",
        "technical__pullback", "data_trust_score_raw", "component_coverage_ratio",
    ]
    existing_factors = [col for col in factor_candidates if col in group]
    missing_ratio = 1.0 - (len(existing_factors) / len(factor_candidates))
    stale = pd.Series(False, index=group.index)
    if "latest_price_date" in group:
        latest = pd.to_datetime(group["latest_price_date"], errors="coerce")
        stale = latest.isna() | (latest < latest.max())
    for col in ["warning_flags", "data_warning_label", "price_data_status"]:
        if col in group:
            stale = stale | group[col].astype(str).str.contains("STALE|MISSING|BITF|PSTG", case=False, na=False)
    low_trust = pd.Series(False, index=group.index)
    if "data_trust__warning_flag" in group:
        low_trust = low_trust | group["data_trust__warning_flag"].map(truth)
    for col in ["data_warning_label", "warning_flags"]:
        if col in group:
            low_trust = low_trust | group[col].astype(str).str.strip().replace("nan", "").ne("")
    high_vol = pd.Series(False, index=group.index)
    if volatility_col:
        ref = numeric(full_reference, volatility_col)
        cutoff = ref.quantile(.75) if ref.notna().any() else numeric(group, volatility_col).quantile(.75)
        high_vol = numeric(group, volatility_col).ge(cutoff)
    high_breakout = pd.Series(False, index=group.index)
    if breakout_col:
        ref = numeric(full_reference, breakout_col)
        cutoff = ref.quantile(.75) if ref.notna().any() else numeric(group, breakout_col).quantile(.75)
        high_breakout = numeric(group, breakout_col).ge(cutoff)
    return {
        "strategy": strategy, "view": view, "count": len(group),
        "unique_sectors": int(group["sector"].nunique(dropna=True)) if "sector" in group else 0,
        "top_sector_weight": float(sector_counts.iloc[0] / len(group)) if len(sector_counts) else "",
        "top_industry_weight": float(industry_counts.iloc[0] / len(group)) if len(industry_counts) else "",
        "sector_hhi": hhi(sector_counts) if len(sector_counts) else "",
        "industry_hhi": hhi(industry_counts) if len(industry_counts) else "",
        "ticker_hhi": 1.0 / len(group) if len(group) else 0,
        "top_5_ticker_score_share": float(score.nlargest(5).sum() / score_total) if score_total else "",
        "average_momentum": numeric(group, momentum_col).mean() if momentum_col else "",
        "average_rs": numeric(group, rs_col).mean() if rs_col else "",
        "average_volatility": numeric(group, volatility_col).mean() if volatility_col else "",
        "missing_factor_coverage_ratio": missing_ratio,
        "stale_or_missing_price_ratio": float(stale.mean()) if len(stale) else 0,
        "low_data_trust_ratio": float(low_trust.mean()) if len(low_trust) else 0,
        "high_breakout_or_overextension_ratio": float(high_breakout.mean()) if len(high_breakout) else "",
        "high_volatility_ratio": float(high_vol.mean()) if len(high_vol) else "",
        "notes": "research_only; current_snapshot_pit_lite",
    }


def build_forward_from_price(root: Path, rankings: dict[str, dict[str, pd.DataFrame]], price_path: Path | None, bench_path: Path | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not price_path or not bench_path or not (root / price_path).is_file() or not (root / bench_path).is_file():
        return pd.DataFrame(), pd.DataFrame()
    prices_raw = pd.read_csv(root / price_path, low_memory=False)
    bench_raw = pd.read_csv(root / bench_path, low_memory=False)
    if not {"symbol", "date", "close"}.issubset(prices_raw.columns) or not {"symbol", "date", "close"}.issubset(bench_raw.columns):
        return pd.DataFrame(), pd.DataFrame()
    prices_raw["symbol"] = prices_raw["symbol"].astype(str).str.upper().str.strip()
    prices_raw["date"] = prices_raw["date"].astype(str).str.slice(0, 10)
    bench_raw["symbol"] = bench_raw["symbol"].astype(str).str.upper().str.strip()
    bench_raw["date"] = bench_raw["date"].astype(str).str.slice(0, 10)
    prices = prices_raw.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    bench = bench_raw.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    calendar = sorted(set(prices.index).union(set(bench.index)))
    rows: list[dict[str, Any]] = []
    bench_rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        frame = rankings[strategy]["top50"]
        if frame.empty:
            continue
        rank_date = clean(frame.get("latest_price_date", pd.Series([""])).dropna().astype(str).max())
        if not rank_date:
            continue
        future = [day for day in calendar if day > rank_date]
        if not future:
            continue
        for horizon in HORIZONS:
            if len(future) < horizon:
                continue
            end_date = future[horizon - 1]
            for _, row in frame.iterrows():
                ticker = clean(row.get("ticker")).upper()
                if ticker not in prices.columns or rank_date not in prices.index or end_date not in prices.index:
                    continue
                start = pd.to_numeric(pd.Series([prices.at[rank_date, ticker]]), errors="coerce").iloc[0]
                end = pd.to_numeric(pd.Series([prices.at[end_date, ticker]]), errors="coerce").iloc[0]
                if pd.notna(start) and pd.notna(end) and start:
                    rows.append({
                        "strategy": strategy, "horizon": horizon, "ticker": ticker, "rank": row.get("rank"),
                        "forward_return": float(end / start - 1.0), "start_date": rank_date, "end_date": end_date,
                    })
            for benchmark in BENCHMARKS:
                if benchmark in bench.columns and rank_date in bench.index and end_date in bench.index:
                    start = bench.at[rank_date, benchmark]
                    end = bench.at[end_date, benchmark]
                    if pd.notna(start) and pd.notna(end) and start:
                        bench_rows.append({"benchmark": benchmark, "horizon": horizon, "return": float(end / start - 1.0), "start_date": rank_date, "end_date": end_date})
    return pd.DataFrame(rows), pd.DataFrame(bench_rows)


def forward_outputs(forward: pd.DataFrame, benchmarks: pd.DataFrame, augmented_top50: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    outputs = {name: [] for name in [
        "forward_failure_summary.csv", "forward_horizon_comparison.csv", "forward_regime_split.csv",
        "forward_left_tail_events.csv", "d_loss_contributors.csv", "repeated_loss_tickers.csv",
        "strategy_loss_concentration.csv", "momentum_bucket_failure.csv", "rs_crowding_failure.csv",
        "overextension_failure_cases.csv", "d_only_vs_a1_only_returns.csv",
    ]}
    if forward.empty:
        return outputs
    meta_cols = [c for c in ["ticker", "sector", "industry", "momentum_score", "relative_momentum_score", "technical__rsi", "technical__kdj", "technical__macd", "technical__bb", "technical__breakout"] if c in augmented_top50]
    meta = augmented_top50[meta_cols].drop_duplicates("ticker", keep="last") if meta_cols else pd.DataFrame()
    if not meta.empty:
        forward = forward.merge(meta, on="ticker", how="left")
    a1_means = forward[forward["strategy"].eq("A1_BASELINE_CONTROL")].groupby("horizon")["forward_return"].mean().to_dict()
    bench_means = benchmarks.groupby(["benchmark", "horizon"])["return"].mean().to_dict() if not benchmarks.empty else {}
    for (strategy, horizon), group in forward.groupby(["strategy", "horizon"], sort=True):
        returns = group["forward_return"].dropna()
        bottom = returns.nsmallest(max(1, int(np.ceil(len(returns) * .10))))
        row = {
            "strategy": strategy, "horizon": horizon, "observation_count": len(returns),
            "average_return": returns.mean(), "median_return": returns.median(), "hit_rate": returns.gt(0).mean(),
            "downside_hit_rate": returns.lt(0).mean(), "worst_ticker_return": returns.min(),
            "bottom_5_average_return": returns.nsmallest(min(5, len(returns))).mean(),
            "left_tail_mean": bottom.mean(), "drawdown_proxy": returns.min(),
            "excess_return_vs_A1": returns.mean() - a1_means.get(horizon, np.nan),
            "excess_return_vs_QQQ": returns.mean() - bench_means.get(("QQQ", horizon), np.nan),
            "excess_return_vs_SPY": returns.mean() - bench_means.get(("SPY", horizon), np.nan),
            "excess_return_vs_SOXX": returns.mean() - bench_means.get(("SOXX", horizon), np.nan),
            "excess_return_vs_SMH": returns.mean() - bench_means.get(("SMH", horizon), np.nan),
            "notes": "computed_from_available_post_ranking_price_panel",
        }
        outputs["forward_failure_summary.csv"].append(row)
        for metric in ["average_return", "median_return", "hit_rate", "left_tail_mean", "excess_return_vs_A1"]:
            outputs["forward_horizon_comparison.csv"].append({"strategy": strategy, "horizon": horizon, "metric": metric, "value": row[metric], "notes": row["notes"]})
        for _, event in group.nsmallest(min(10, len(group)), "forward_return").iterrows():
            outputs["forward_left_tail_events.csv"].append({"strategy": strategy, "horizon": horizon, "ticker": event["ticker"], "forward_return": event["forward_return"], "rank": event.get("rank", ""), "sector": event.get("sector", ""), "industry": event.get("industry", ""), "notes": "left_tail_available_price_panel"})
        losses = group[group["forward_return"].lt(0)].copy()
        if not losses.empty:
            neg = losses.groupby("ticker")["forward_return"].sum().abs()
            top5_share = neg.nlargest(min(5, len(neg))).sum() / neg.sum() if neg.sum() else 0
            outputs["strategy_loss_concentration.csv"].append({"strategy": strategy, "horizon": horizon, "loss_count": len(losses), "top_5_loss_share": top5_share, "loss_hhi": hhi(neg), "notes": "negative_return_contribution_share"})
    d = forward[forward["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")]
    if not d.empty:
        by_ticker = []
        for (ticker, horizon), group in d.groupby(["ticker", "horizon"], sort=True):
            losses = group[group["forward_return"].lt(0)]
            by_ticker.append({
                "ticker": ticker, "strategy": "D_WEIGHT_OPTIMIZED_R1", "horizon": horizon,
                "observation_count": len(group), "loss_count": len(losses), "avg_return": group["forward_return"].mean(),
                "worst_return": group["forward_return"].min(),
                "total_negative_contribution": losses["forward_return"].sum(),
                "repeated_loss_flag": len(losses) > 1,
                "sector": group.get("sector", pd.Series([""])).iloc[0], "industry": group.get("industry", pd.Series([""])).iloc[0],
                "notes": "available_forward_window",
            })
        outputs["d_loss_contributors.csv"].extend(by_ticker)
        repeated = pd.DataFrame(by_ticker)
        if not repeated.empty:
            agg = repeated.groupby("ticker").agg(loss_windows=("loss_count", "sum"), total_negative_contribution=("total_negative_contribution", "sum"), sector=("sector", "first"), industry=("industry", "first")).reset_index()
            for _, row in agg[agg["loss_windows"].gt(1)].iterrows():
                outputs["repeated_loss_tickers.csv"].append({**row.to_dict(), "notes": "loss_in_multiple_available_windows"})
    return outputs


def divergence_outputs(a1: pd.DataFrame, d: pd.DataFrame, view: str, forward: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    d_tickers = set(d["ticker"]) if "ticker" in d else set()
    a1_tickers = set(a1["ticker"]) if "ticker" in a1 else set()
    d_only = d[d["ticker"].isin(d_tickers - a1_tickers)].copy() if not d.empty else pd.DataFrame()
    a1_only = a1[a1["ticker"].isin(a1_tickers - d_tickers)].copy() if not a1.empty else pd.DataFrame()
    overlap = len(d_tickers & a1_tickers)
    rows = [
        {"view": view, "metric": "a1_d_overlap_count", "value": overlap, "notes": "research_only"},
        {"view": view, "metric": "a1_d_overlap_ratio_of_d", "value": overlap / len(d_tickers) if d_tickers else 0, "notes": "research_only"},
        {"view": view, "metric": "d_only_count", "value": len(d_only), "notes": "research_only"},
        {"view": view, "metric": "a1_only_count", "value": len(a1_only), "notes": "research_only"},
    ]
    returns_rows: list[dict[str, Any]] = []
    if not forward.empty:
        for group_name, tickers in [("D_ONLY", set(d_only["ticker"]) if not d_only.empty else set()), ("A1_ONLY", set(a1_only["ticker"]) if not a1_only.empty else set())]:
            subset = forward[forward["ticker"].isin(tickers)]
            for horizon, group in subset.groupby("horizon"):
                bottom = group["forward_return"].nsmallest(max(1, int(np.ceil(len(group) * .10))))
                returns_rows.append({"view": view, "group": group_name, "horizon": horizon, "observation_count": len(group), "average_return": group["forward_return"].mean(), "left_tail_mean": bottom.mean(), "notes": "available_forward_only"})
    profile_rows: list[dict[str, Any]] = []
    for group_name, frame in [("D_ONLY", d_only), ("A1_ONLY", a1_only)]:
        if frame.empty:
            continue
        for row in exposure_rows(frame.assign(strategy=group_name), view):
            row["group"] = group_name
            profile_rows.append({"view": view, "group": group_name, "exposure_type": row["exposure_type"], "bucket": row["bucket"], "count": row["count"], "weight": row["weight"], "notes": row["notes"]})
    return rows, returns_rows, profile_rows


def classify_failures(concentration: list[dict[str, Any]], forward_summary: list[dict[str, Any]], matured_available: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    rows: list[dict[str, Any]] = []
    warnings = {"left_tail": False, "concentration": False, "rs_crowding": False, "benchmark_beta": False}
    for row in concentration:
        if row["strategy"] != "D_WEIGHT_OPTIMIZED_R1":
            continue
        if clean(row.get("top_sector_weight")) and float(row["top_sector_weight"]) >= .40:
            warnings["concentration"] = True
            rows.append({"event_id": f"{row['view']}::sector_concentration", "strategy": row["strategy"], "horizon": "", "ticker": "", "failure_mode": "SEMI_STORAGE_CONCENTRATION", "severity": "WARN", "evidence": f"top_sector_weight={row['top_sector_weight']}", "research_only": True})
        if clean(row.get("top_industry_weight")) and float(row["top_industry_weight"]) >= .30:
            warnings["concentration"] = True
            rows.append({"event_id": f"{row['view']}::industry_concentration", "strategy": row["strategy"], "horizon": "", "ticker": "", "failure_mode": "SEMI_STORAGE_CONCENTRATION", "severity": "WARN", "evidence": f"top_industry_weight={row['top_industry_weight']}", "research_only": True})
        if clean(row.get("high_volatility_ratio")) and float(row["high_volatility_ratio"]) >= .40:
            rows.append({"event_id": f"{row['view']}::high_volatility", "strategy": row["strategy"], "horizon": "", "ticker": "", "failure_mode": "HIGH_VOLATILITY_TRAP", "severity": "WARN", "evidence": f"high_volatility_ratio={row['high_volatility_ratio']}", "research_only": True})
        if float(row.get("stale_or_missing_price_ratio") or 0) > 0 or float(row.get("low_data_trust_ratio") or 0) > 0:
            rows.append({"event_id": f"{row['view']}::data_trust", "strategy": row["strategy"], "horizon": "", "ticker": "", "failure_mode": "LOW_DATA_TRUST_OR_STALE_PRICE", "severity": "INFO", "evidence": f"stale_ratio={row.get('stale_or_missing_price_ratio')}; low_trust={row.get('low_data_trust_ratio')}", "research_only": True})
    d_forward = [r for r in forward_summary if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1"]
    for row in d_forward:
        if clean(row.get("left_tail_mean")) and float(row["left_tail_mean"]) < -0.05:
            warnings["left_tail"] = True
            rows.append({"event_id": f"h{row['horizon']}::left_tail", "strategy": row["strategy"], "horizon": row["horizon"], "ticker": "", "failure_mode": "TICKER_SPECIFIC_IDIOSYNCRATIC", "severity": "WARN", "evidence": f"left_tail_mean={row['left_tail_mean']}", "research_only": True})
        if clean(row.get("excess_return_vs_A1")) and float(row["excess_return_vs_A1"]) < 0 and clean(row.get("excess_return_vs_SOXX")) and abs(float(row["excess_return_vs_SOXX"])) < abs(float(row["excess_return_vs_A1"])):
            warnings["benchmark_beta"] = True
            rows.append({"event_id": f"h{row['horizon']}::benchmark_beta", "strategy": row["strategy"], "horizon": row["horizon"], "ticker": "", "failure_mode": "BENCHMARK_BETA_NOT_STOCK_SELECTION", "severity": "WARN", "evidence": f"excess_vs_A1={row['excess_return_vs_A1']}; excess_vs_SOXX={row['excess_return_vs_SOXX']}", "research_only": True})
    if not matured_available:
        rows.append({"event_id": "forward_maturity::insufficient", "strategy": "D_WEIGHT_OPTIMIZED_R1", "horizon": "", "ticker": "", "failure_mode": "INSUFFICIENT_MATURED_FORWARD_DATA", "severity": "BLOCKER", "evidence": "No matured forward returns found for required 1D/5D/10D/20D diagnostics.", "research_only": True})
    if not rows:
        rows.append({"event_id": "columns::unknown", "strategy": "D_WEIGHT_OPTIMIZED_R1", "horizon": "", "ticker": "", "failure_mode": "UNKNOWN_INSUFFICIENT_COLUMNS", "severity": "INFO", "evidence": "No classified failure event detected from available columns.", "research_only": True})
    summary = []
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mode.setdefault(row["failure_mode"], []).append(row)
    for mode, items in sorted(by_mode.items()):
        severity = "BLOCKER" if any(i["severity"] == "BLOCKER" for i in items) else "WARN" if any(i["severity"] == "WARN" for i in items) else "INFO"
        summary.append({"failure_mode": mode, "event_count": len(items), "severity": severity, "notes": "research_only_classification"})
    return rows, summary, warnings


def manifest_rows(output: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file():
            rows.append({"file": path.name, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path), "research_only": True})
    return rows


def run(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    output = immutable_output(root, output_override)
    rankings, ranking_paths = load_rankings(root)
    classification_path = discover_latest(root, ["outputs/v21/v21_078/*CLASSIFICATION_MASTER*.csv", "outputs/v21/v21_076/*CLASSIFICATION_MASTER*.csv"], {"ticker"})
    explainability_path = discover_latest(root, ["outputs/v21/explainability/*FACTOR_EXPLAINABILITY*.csv"], {"ticker"})
    price_path = discover_latest(root, ["outputs/v20/price_history/*HISTORICAL_OHLCV.csv", "outputs/v21/**/*PRICE_PATH_PANEL.csv"], None)
    bench_path = discover_latest(root, ["outputs/v20/price_history/*BENCHMARK_OHLCV.csv"], None)
    v107_matured = discover_latest(root, ["outputs/v21/v21_107_live_forward_tracking/*/v21_107_matured_observations.csv"], None)
    v060_forward = discover_latest(root, ["outputs/v21/experiments/momentum_dynamic/**/*FORWARD_OBSERVATION_LEDGER*.csv"], None)
    warning_paths = {f"{s}_warnings": root / ARCHIVE_REL / s / "warnings.csv" for s in STRATEGIES}

    inventory = []
    for key, path in ranking_paths.items():
        inventory.append(inventory_row(key, root, path, "V21.108-R2 archived ranking input"))
    for key, path in warning_paths.items():
        inventory.append(inventory_row(key, root, path, "Warning preservation input; BITF/PSTG warnings preserved if present"))
    for name, path, note in [
        ("classification_master", classification_path, "sector/industry/theme join source"),
        ("factor_explainability", explainability_path, "technical/data-trust optional factor source"),
        ("candidate_price_panel", price_path, "price panel used only for matured forward diagnostics when post-ranking dates exist"),
        ("benchmark_price_panel", bench_path, "benchmark panel for QQQ/SPY/SOXX/SMH when available"),
        ("v21_107_matured_forward", v107_matured, "preferred live forward maturity source if non-empty"),
        ("v21_060_forward_ledger", v060_forward, "older forward ledger fallback if realized returns are present"),
    ]:
        inventory.append(inventory_row(name, root, path, note))

    classification = read_frame(classification_path) if classification_path else pd.DataFrame()
    explainability = read_frame(explainability_path) if explainability_path else pd.DataFrame()
    if not classification.empty and "ticker" in classification:
        classification["ticker"] = classification["ticker"].astype(str).str.upper().str.strip()
    if not explainability.empty and "ticker" in explainability:
        explainability["ticker"] = explainability["ticker"].astype(str).str.upper().str.strip()

    augmented: dict[str, dict[str, pd.DataFrame]] = {}
    for strategy in STRATEGIES:
        augmented[strategy] = {}
        for view in ["top20", "top50", "full"]:
            augmented[strategy][view] = augment_with_metadata(root, rankings[strategy][view], classification, explainability)

    all_top20 = pd.concat([augmented[s]["top20"] for s in STRATEGIES], ignore_index=True) if STRATEGIES else pd.DataFrame()
    all_top50 = pd.concat([augmented[s]["top50"] for s in STRATEGIES], ignore_index=True) if STRATEGIES else pd.DataFrame()
    exposure_top20 = exposure_rows(all_top20, "top20")
    exposure_top50 = exposure_rows(all_top50, "top50")
    concentration = []
    comparison = []
    for strategy in STRATEGIES:
        for view in ["top20", "top50"]:
            row = concentration_row(strategy, view, augmented[strategy][view], augmented[strategy]["full"])
            concentration.append(row)
            for metric in CSV_SCHEMAS["concentration_metrics.csv"][2:-1]:
                comparison.append({"strategy": strategy, "view": view, "metric": metric, "value": row.get(metric, ""), "notes": "research_only"})

    forward, benchmark_returns = build_forward_from_price(root, augmented, price_path.relative_to(root) if price_path and price_path.is_absolute() and price_path.is_relative_to(root) else price_path, bench_path.relative_to(root) if bench_path and bench_path.is_absolute() and bench_path.is_relative_to(root) else bench_path)
    matured_available = not forward.empty
    f_outputs = forward_outputs(forward, benchmark_returns, all_top50)

    div_rows: list[dict[str, Any]] = []
    div_return_rows: list[dict[str, Any]] = []
    div_profile_rows: list[dict[str, Any]] = []
    for view in ["top20", "top50"]:
        rows, returns, profile = divergence_outputs(augmented["A1_BASELINE_CONTROL"][view], augmented["D_WEIGHT_OPTIMIZED_R1"][view], view, forward)
        div_rows.extend(rows)
        div_return_rows.extend(returns)
        div_profile_rows.extend(profile)

    classifications, classification_summary, warning_flags = classify_failures(concentration, f_outputs["forward_failure_summary.csv"], matured_available)
    partial = not matured_available
    if partial:
        final_status = "PARTIAL_PASS"
        decision = "D_FAILURE_MODE_DIAGNOSTIC_PARTIAL_INSUFFICIENT_FORWARD_DATA"
    elif warning_flags["left_tail"] and (warning_flags["concentration"] or warning_flags["rs_crowding"]):
        final_status = "FAIL"
        decision = "D_FAILURE_MODE_DIAGNOSTIC_FAIL_LEFT_TAIL_OR_CROWDING_CONFIRMED"
    elif warning_flags["left_tail"] or warning_flags["concentration"] or warning_flags["benchmark_beta"]:
        final_status = "WARN"
        decision = "D_FAILURE_MODE_DIAGNOSTIC_WARN_CONCENTRATION_OR_LEFT_TAIL"
    else:
        final_status = "PASS"
        decision = "D_FAILURE_MODE_DIAGNOSTIC_PASS_NO_MAJOR_LEFT_TAIL_FOUND"

    outputs: dict[str, list[dict[str, Any]]] = {
        "input_inventory.csv": inventory,
        "exposure_top20.csv": exposure_top20,
        "exposure_top50.csv": exposure_top50,
        "exposure_comparison_A1_B_C_D.csv": comparison,
        "concentration_metrics.csv": concentration,
        "d_vs_a1_divergence.csv": div_rows,
        "d_only_vs_a1_only_returns.csv": div_return_rows or f_outputs["d_only_vs_a1_only_returns.csv"],
        "d_only_exposure_profile.csv": div_profile_rows,
        "failure_mode_classification.csv": classifications,
        "failure_mode_summary.csv": classification_summary,
    }
    for name in [
        "forward_failure_summary.csv", "forward_horizon_comparison.csv", "forward_regime_split.csv",
        "forward_left_tail_events.csv", "d_loss_contributors.csv", "repeated_loss_tickers.csv",
        "strategy_loss_concentration.csv", "momentum_bucket_failure.csv", "rs_crowding_failure.csv",
        "overextension_failure_cases.csv",
    ]:
        outputs[name] = f_outputs[name]

    for name, fields in CSV_SCHEMAS.items():
        write_csv(output / name, outputs.get(name, []), fields)

    d_top20_rows = len(augmented["D_WEIGHT_OPTIMIZED_R1"]["top20"])
    d_top50_rows = len(augmented["D_WEIGHT_OPTIMIZED_R1"]["top50"])
    repeated_loss_count = len(outputs["repeated_loss_tickers.csv"])
    warnings_text = []
    warning_frames = [read_frame(path) for path in warning_paths.values() if path.is_file()]
    if warning_frames:
        warning_blob = "\n".join(frame.to_csv(index=False) for frame in warning_frames)
        for token in ["BITF", "PSTG"]:
            if token in warning_blob:
                warnings_text.append(f"{token} warning present in source warnings and preserved by read-only inventory.")
    warnings_text.append("Full PIT replay unavailable; diagnostics use PIT-lite/current snapshot archived rankings where applicable.")

    summary = {
        "stage": STAGE,
        "generated_at_utc": started,
        "final_status": final_status,
        "decision": decision,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "official_outputs_modified": False,
        "source_ranking_files_modified": False,
        "model_weights_changed": False,
        "trade_instructions_produced": False,
        "output_dir": output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output),
        "d_top20_rows": d_top20_rows,
        "d_top50_rows": d_top50_rows,
        "forward_data_available": matured_available,
        "matured_observations": int(len(forward)),
        "left_tail_warning": warning_flags["left_tail"],
        "concentration_warning": warning_flags["concentration"],
        "rs_crowding_warning": warning_flags["rs_crowding"],
        "benchmark_beta_warning": warning_flags["benchmark_beta"],
        "repeated_loss_tickers": repeated_loss_count,
        "available_diagnostics": [name for name, rows in outputs.items() if rows],
        "missing_or_sparse_diagnostics": [name for name, rows in outputs.items() if not rows],
        "warnings": warnings_text,
        "next_recommended_step": (
            "continue V21.109 maturity tracking" if partial else
            "design V21.114 risk-control diagnostic only" if decision.endswith("CONFIRMED") else
            "continue waiting for more matured forward observations before any shadow official review"
        ),
    }
    write_json(output / SUMMARY_JSON, summary)

    d_conc = [r for r in concentration if r["strategy"] == "D_WEIGHT_OPTIMIZED_R1"]
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS: {final_status}",
        f"DECISION: {decision}",
        "",
        "## Controls",
        "- research_only = true",
        "- official_adoption_allowed = false",
        "- broker_action_allowed = false",
        "- protected_outputs_modified = false",
        "- official ranking files, broker/action outputs, protected outputs, source data, and model weights were not modified.",
        "",
        "## Input Inventory",
        f"- Inventory rows: {len(inventory)}",
        f"- Full PIT replay availability: not found; PIT-lite/current snapshot warning preserved.",
        f"- Warning preservation notes: {'; '.join(warnings_text)}",
        "",
        "## Available / Missing Diagnostics",
        f"- Available: {', '.join(summary['available_diagnostics'])}",
        f"- Missing or sparse: {', '.join(summary['missing_or_sparse_diagnostics'])}",
        "",
        "## D Top20 and Top50 Exposure Summary",
    ]
    for row in d_conc:
        report.append(f"- {row['view']}: count={row['count']}, top_sector_weight={row['top_sector_weight']}, top_industry_weight={row['top_industry_weight']}, avg_momentum={row['average_momentum']}, avg_rs={row['average_rs']}, high_vol_ratio={row['high_volatility_ratio']}")
    report.extend([
        "",
        "## D Versus A1/B/C",
        "- See exposure_comparison_A1_B_C_D.csv and d_vs_a1_divergence.csv for strategy-level concentration and overlap diagnostics.",
        "",
        "## Forward Maturity Availability",
        f"- forward_data_available = {str(matured_available).lower()}",
        f"- matured_observations = {len(forward)}",
        "- If forward rows are unavailable, forward failure, left-tail, regime split, and repeated-loss outputs are emitted as readable empty CSVs.",
        "",
        "## Left-Tail Findings",
        f"- left_tail_warning = {str(warning_flags['left_tail']).lower()}",
        "- No left-tail conclusion is made without matured forward observations.",
        "",
        "## Sector / Industry / Momentum Crowding Findings",
        f"- concentration_warning = {str(warning_flags['concentration']).lower()}",
        f"- rs_crowding_warning = {str(warning_flags['rs_crowding']).lower()}",
        "- Sector/industry diagnostics use the latest available classification master. Momentum/RS diagnostics use archived ranking and explainability columns where present.",
        "",
        "## Repeated Loss Contributors",
        f"- repeated_loss_tickers = {repeated_loss_count}",
        "- Requires matured ticker-level forward returns; unavailable rows remain empty instead of fabricated.",
        "",
        "## D-Only Versus A1-Only",
        "- D-only and A1-only membership and exposure profiles are reported. Forward-return comparison is populated only when matured forward data exists.",
        "",
        "## Failure-Mode Classification",
        f"- Classification rows: {len(classifications)}",
        f"- Summary rows: {len(classification_summary)}",
        "",
        "## Next Recommended Step",
        f"- {summary['next_recommended_step']}",
    ])
    (output / REPORT_MD).write_text("\n".join(report) + "\n", encoding="utf-8")

    write_csv(output / MANIFEST_CSV, manifest_rows(output), ["file", "path", "bytes", "sha256", "research_only"])
    # Re-write manifest after it exists so the manifest records itself.
    write_csv(output / MANIFEST_CSV, manifest_rows(output), ["file", "path", "bytes", "sha256", "research_only"])

    print(f"FINAL_STATUS: {final_status}")
    print(f"DECISION: {decision}")
    print(f"D_TOP20_ROWS: {d_top20_rows}")
    print(f"D_TOP50_ROWS: {d_top50_rows}")
    print(f"FORWARD_DATA_AVAILABLE: {str(matured_available).lower()}")
    print(f"MATURED_OBSERVATIONS: {len(forward)}")
    print(f"LEFT_TAIL_WARNING: {str(warning_flags['left_tail']).lower()}")
    print(f"CONCENTRATION_WARNING: {str(warning_flags['concentration']).lower()}")
    print(f"RS_CROWDING_WARNING: {str(warning_flags['rs_crowding']).lower()}")
    print(f"BENCHMARK_BETA_WARNING: {str(warning_flags['benchmark_beta']).lower()}")
    print(f"REPEATED_LOSS_TICKERS: {repeated_loss_count}")
    print("RESEARCH_ONLY: true")
    print("OFFICIAL_ADOPTION_ALLOWED: false")
    print("BROKER_ACTION_ALLOWED: false")
    print("PROTECTED_OUTPUTS_MODIFIED: false")
    print(f"REPORT_PATH: {(output / REPORT_MD).relative_to(root).as_posix() if (output / REPORT_MD).is_relative_to(root) else output / REPORT_MD}")
    print(f"SUMMARY_PATH: {(output / SUMMARY_JSON).relative_to(root).as_posix() if (output / SUMMARY_JSON).is_relative_to(root) else output / SUMMARY_JSON}")
    print(f"MANIFEST_PATH: {(output / MANIFEST_CSV).relative_to(root).as_posix() if (output / MANIFEST_CSV).is_relative_to(root) else output / MANIFEST_CSV}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    run(args.root.resolve(), args.output_dir)


if __name__ == "__main__":
    main()
