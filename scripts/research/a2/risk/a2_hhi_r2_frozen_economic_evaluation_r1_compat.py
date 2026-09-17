"""Compatibility launch adapter for the frozen HHI R2 economic evaluation.

The frozen four-layer sector surface ends at signal 2026-08-25 because its
2026-08-26 one-day outcome had not matured in that lineage.  The economic
replay itself validly ends on 2026-08-27 and therefore needs the 2026-08-26
target membership and structural benchmark.  This adapter binds the exact
taxonomy reconciliation already frozen in the parent beta/sector audit and
constructs only the missing date's outcome-blind equal-weight benchmark from
the authoritative valid ranked surface.  It does not alter any evaluation
metric, economic outcome, R2 transition, cost, or classification gate.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE = Path(r"D:\us-tech-quant\a2_hhi_r2_frozen_economic_evaluation_r1.py")
SPEC = importlib.util.spec_from_file_location("frozen_hhi_eval", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("evaluation import failure")
EVAL = importlib.util.module_from_spec(SPEC)
sys.modules["frozen_hhi_eval"] = EVAL
SPEC.loader.exec_module(EVAL)

EXTRA_BENCHMARK: dict[pd.Timestamp, dict[str, float]] = {}
CURRENT_WEIGHTS: list[dict[pd.Timestamp, dict[str, float]]] = []
ORIGINAL_BENCHMARK = EVAL.benchmark_weights_and_peers


def benchmark_weights_and_peers() -> tuple[dict[pd.Timestamp, dict[str, float]], pd.DataFrame]:
    weights, peers = ORIGINAL_BENCHMARK()
    weights.update(EXTRA_BENCHMARK)
    CURRENT_WEIGHTS[:] = [weights]
    additions = []
    existing_dates = set(pd.to_datetime(peers.signal_date).dt.normalize())
    for date, by_sector in EXTRA_BENCHMARK.items():
        if date in existing_dates:
            continue
        for sector, benchmark_weight in by_sector.items():
            additions.append({
                "record_type": "DAILY_SECTOR",
                "signal_date": date,
                "realization_date": pd.NaT,
                "taxonomy_level": "FF12",
                "sector": sector,
                "portfolio_weight": float("nan"),
                "benchmark_weight": benchmark_weight,
                "benchmark_sector_return": float("nan"),
            })
    if additions:
        peers = pd.concat([peers, pd.DataFrame(additions)], ignore_index=True)
    return weights, peers


def bind_2026_taxonomy(
    pre_panel: pd.DataFrame,
    post_pool: pd.DataFrame,
    sector: pd.DataFrame,
    beta: Any,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    matched, _ = beta.read_matched()
    exact, latest = beta.build_taxonomy_maps(matched)
    post = post_pool.merge(exact, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    fallback = latest.rename(columns={"ff12": "ff12_fallback", "ff48": "ff48_fallback"})
    post = post.merge(fallback, on="ticker", how="left", validate="many_to_one")
    post["ff12"] = post.ff12.fillna(post.ff12_fallback).fillna("UNKNOWN")
    post = post.drop(columns=[column for column in ("ff48", "ff12_fallback", "ff48_fallback") if column in post])

    raw_top = post.loc[post.a2_rank.le(EVAL.TOP_N), ["signal_date", "ticker", "ff12"]].rename(columns={"ff12": "FF12"})
    reconciled, reconciliation_audit = beta.reconcile_unknown_2026_ff12(raw_top, sector)
    recovered = reconciled.loc[reconciled.FF12.ne("UNKNOWN")].sort_values("signal_date").drop_duplicates("ticker", keep="last").set_index("ticker").FF12.to_dict()
    unknown = post.ff12.eq("UNKNOWN")
    post.loc[unknown, "ff12"] = post.loc[unknown, "ticker"].map(recovered).fillna("UNKNOWN")

    inferred = post.loc[post.a2_rank.le(EVAL.TOP_N)].groupby(["signal_date", "ff12"]).size().mul(EVAL.WEIGHT).rename("inferred").reset_index()
    frozen = sector.loc[sector.signal_date.ge("2026-01-01"), ["signal_date", "sector", "portfolio_weight"]].rename(columns={"sector": "ff12", "portfolio_weight": "frozen"})
    overlap_dates = set(frozen.signal_date)
    check = inferred.loc[inferred.signal_date.isin(overlap_dates)].merge(frozen, on=["signal_date", "ff12"], how="outer").fillna(0.0)
    max_error = float((check.inferred - check.frozen).abs().max())
    EVAL.require(max_error <= 5e-4, "2026_RAW_TAXONOMY_IDENTITY", max_error)

    missing_dates = sorted(set(post.signal_date) - overlap_dates)
    for date in missing_dates:
        day = post.loc[post.signal_date.eq(date)]
        counts = day.groupby("ff12").ticker.nunique().astype(float)
        EXTRA_BENCHMARK[pd.Timestamp(date)] = (counts / counts.sum()).to_dict()
        if CURRENT_WEIGHTS:
            CURRENT_WEIGHTS[0][pd.Timestamp(date)] = EXTRA_BENCHMARK[pd.Timestamp(date)]

    audit = {
        "compatibility_adapter": "PARENT_BETA_SECTOR_EXACT_2026_TAXONOMY_PLUS_OUTCOME_BLIND_MISSING_DATE_BENCHMARK",
        "taxonomy_sources": [str(EVAL.TAXONOMY), str(EVAL.MATCHED)],
        "unknown_row_fraction": float(post.ff12.eq("UNKNOWN").mean()),
        "raw_top20_sector_weight_max_error_on_matured_surface": max_error,
        "parent_tolerance": 5e-4,
        "missing_sector_surface_signal_dates": [str(pd.Timestamp(date).date()) for date in missing_dates],
        "missing_date_benchmark_definition": "equal-weight authoritative valid ranked candidate surface by frozen FF12/UNKNOWN",
        "raw_top20_unknown_reconciliation": reconciliation_audit,
        "economic_definition_change": False,
    }
    return post, audit


EVAL.benchmark_weights_and_peers = benchmark_weights_and_peers
EVAL.bind_2026_taxonomy = bind_2026_taxonomy

if __name__ == "__main__":
    EVAL.evaluate()
