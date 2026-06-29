#!/usr/bin/env python
"""Focused tests for V21.104-R2 contribution replay."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_104_r2_holdings_persistence_and_ticker_contribution_replay.py"
spec = importlib.util.spec_from_file_location("v21_104_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    holdings = []
    source = []
    for sample, qqq, soxx in (("S1", .05, .10), ("S2", .06, 1.0)):
        contributions = {"MU": .10, "AMAT": .05, "OTHER": -.02}
        portfolio_return = sum(contributions.values())
        source.append({
            "sample_id": sample, "variant": "D", "portfolio_size": 20,
            "horizon": 252, "portfolio_return": portfolio_return,
            "excess_vs_A1": .02, "excess_vs_QQQ": portfolio_return - qqq,
            "excess_vs_semiconductor_benchmark": portfolio_return - soxx,
            "benchmark_semiconductor_return": soxx,
        })
        for rank, (ticker, contribution) in enumerate(contributions.items(), start=1):
            holdings.append({
                "sample_id": sample, "variant": "D", "portfolio_size": 20,
                "horizon": 252, "ticker": ticker,
                "manual_group": module.manual_group(ticker), "rank": rank,
                "weight": 1 / 20, "ticker_return": contribution * 20,
                "weighted_contribution": contribution,
            })
    return pd.DataFrame(holdings), pd.DataFrame(source)


def test_contributions_sum_and_classify_groups() -> None:
    holdings, source = fixture()
    rows = module.contribution_summary(holdings, source, 20)
    assert abs(sum(row["total_contribution"] for row in rows) - source["portfolio_return"].sum()) < 1e-12
    assert next(row for row in rows if row["ticker"] == "MU")["manual_group"] == "MEMORY_STORAGE"
    assert next(row for row in rows if row["ticker"] == "AMAT")["manual_group"] == "SEMICONDUCTOR_OTHER"


def test_soxx_gap_attributes_underparticipation() -> None:
    holdings, source = fixture()
    rows = module.soxx_gap_attribution(holdings, source)
    assert rows
    assert sum(row["total_underparticipation_gap"] for row in rows) < 0


def test_concentration_metrics_exist() -> None:
    holdings, source = fixture()
    contribution = {20: module.contribution_summary(holdings, source, 20)}
    contribution[50] = contribution[20]
    rows = module.concentration_analysis(contribution)
    assert any(row["metric"] == "TOP5_ABSOLUTE_CONTRIBUTION_SHARE" for row in rows)
    assert any(row["metric"] == "EFFECTIVE_NUMBER_OF_TICKERS_BY_APPEARANCE" for row in rows)


if __name__ == "__main__":
    test_contributions_sum_and_classify_groups()
    test_soxx_gap_attributes_underparticipation()
    test_concentration_metrics_exist()
    print("PASS test_v21_104_r2_holdings_persistence_and_ticker_contribution_replay")
