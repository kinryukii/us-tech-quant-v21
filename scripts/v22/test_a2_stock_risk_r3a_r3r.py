"""Focused contracts for R3A/R3R attribution and execution alignment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r3a_r3r.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r3a_r3r", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_r3_contract_is_reused_without_new_features() -> None:
    assert len(MODULE.R3.FEATURES) == 22
    assert len(MODULE.R3.CANDIDATES) == 6
    assert MODULE.REFERENCE_CANDIDATE in {candidate.candidate_id for candidate in MODULE.R3.CANDIDATES}


def test_part_a_uses_existing_oof_and_fixed_groups() -> None:
    deciles, scaling, matrix, extremes, summary = MODULE.r3a_attribution()
    assert set(deciles.risk_decile) == set(range(1, 11))
    assert set(scaling.risk_scope) == {"ALL", "TOP_5PCT", "TOP_10PCT", "TOP_20PCT", "TOP_30PCT"}
    assert len(matrix) == 12
    assert set(extremes.outcome_group) == {"WORST_50", "BEST_50", "WORST_100", "BEST_100"}
    assert summary["OOF_ATTRIBUTION_ROW_COUNT"] > 0


def test_execution_coverage_reads_only_pre2026_partitions() -> None:
    _, score_panel, _, _, _ = MODULE.R3.build_panels()
    prices = MODULE.load_canonical_prices(set(score_panel.ticker))
    assert prices.trade_date.lt(pd.Timestamp("2026-01-01")).all()
    coverage, required = MODULE.coverage_table(score_panel, prices)
    assert len(coverage) == len(score_panel)
    assert required.trade_date.lt(pd.Timestamp("2026-01-01")).all()
    assert coverage.exact_execution_reference.mean() < 1.0


def test_corrected_target_uses_open_then_low_high_close() -> None:
    score = pd.DataFrame({"signal_date": [pd.Timestamp("2025-01-02")], "ticker": ["TEST"]})
    rows = []
    for horizon, values in enumerate([(100, 103, 98, 102), (102, 105, 97, 104), (104, 110, 101, 109), (109, 111, 95, 96), (96, 100, 94, 99)]):
        rows.append({"signal_date": score.signal_date.iloc[0], "ticker": "TEST", "horizon": horizon, "trade_date": pd.Timestamp("2025-01-02") + pd.Timedelta(days=horizon), "open": values[0], "high": values[1], "low": values[2], "close": values[3], "authoritative_bar": True})
    target = MODULE.build_corrected_targets(score, pd.DataFrame(rows)).iloc[0]
    assert abs(target.post_entry_forward_1d_return - 0.02) < 1e-12
    assert abs(target.post_entry_forward_5d_return + 0.01) < 1e-12
    assert abs(target.post_entry_5d_mae - 0.06) < 1e-12
    assert abs(target.post_entry_5d_mfe - 0.11) < 1e-12
