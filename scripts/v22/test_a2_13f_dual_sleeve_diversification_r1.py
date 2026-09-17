from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_13f_dual_sleeve_diversification_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_13f_dual_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sleeve_maps() -> tuple[dict[pd.Timestamp, dict[str, float]], dict[pd.Timestamp, dict[str, float]]]:
    date = pd.Timestamp("2025-01-02")
    a2 = {f"A{index:02d}": 0.05 for index in range(20)}
    institutional = {f"A{index:02d}": 0.05 for index in range(5)}
    institutional.update({f"I{index:02d}": 0.05 for index in range(15)})
    return {date: a2}, {date: institutional}


def test_score_level_blend_is_not_used() -> None:
    source = inspect.getsource(MOD.combine_target_maps)
    assert "rank" not in source.lower()
    assert "score" not in source.lower()
    assert "fixed_blend" not in Path(MOD.__file__).read_text(encoding="utf-8")


def test_sleeve_weights_are_fixed_80_20() -> None:
    assert MOD.A2_WEIGHT == 0.80
    assert MOD.INSTITUTIONAL_WEIGHT == 0.20
    assert MOD.A2_WEIGHT + MOD.INSTITUTIONAL_WEIGHT == 1.0


def test_overlap_target_weights_are_added_before_execution() -> None:
    a2, institutional = sleeve_maps()
    combined, audit = MOD.combine_target_maps(a2, institutional)
    target = combined[pd.Timestamp("2025-01-02")]
    assert target["A00"] == pytest.approx(0.05)
    assert target["A10"] == pytest.approx(0.04)
    assert target["I00"] == pytest.approx(0.01)
    assert audit.iloc[0].name_overlap == 5
    assert audit.iloc[0].combined_position_count == 35


def test_overlap_order_flow_is_netted_by_existing_portfolio_engine() -> None:
    a2, institutional = sleeve_maps()
    combined, _ = MOD.combine_target_maps(a2, institutional)
    r0f = MOD.import_file(
        "dual_test_r0f",
        Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"),
    )
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    tickers = ["QQQ", *combined[pd.Timestamp("2025-01-02")].keys()]
    prices = pd.DataFrame(
        [(ticker, date, 10.0, 10.0) for ticker in tickers for date in dates],
        columns=["ticker", "trade_date", "open", "close"],
    )
    result = r0f.reconstruct_path(
        model="S2_TEST", target_map=combined, qfq=prices,
        signal_dates=[pd.Timestamp("2025-01-02")], cost_bps=10,
    )
    first_day = result.trades.loc[result.trades.date.eq(pd.Timestamp("2025-01-03"))]
    assert len(first_day.loc[first_day.ticker.eq("A00") & first_day.side.eq("BUY")]) == 1
    assert first_day.loc[first_day.ticker.eq("A00"), "notional"].iloc[0] == pytest.approx(0.05 * 0.9995)


def test_combined_gross_and_cash_identity() -> None:
    combined, audit = MOD.combine_target_maps(*sleeve_maps())
    target = next(iter(combined.values()))
    assert min(target.values()) >= 0
    assert sum(target.values()) <= 1.0 + 1e-12
    assert sum(target.values()) + audit.iloc[0].combined_target_cash == pytest.approx(1.0)
    assert audit.iloc[0].max_single_name_target_weight == pytest.approx(0.05)


def test_13f_target_cannot_precede_effective_vintage() -> None:
    bad = pd.DataFrame({
        "signal_date": [pd.Timestamp("2025-05-14")],
        "quarter_effective_date": [pd.Timestamp("2025-05-15")],
        "target_end_date": [pd.Timestamp("2025-06-14")],
        "target": [0.1],
    })
    with pytest.raises(MOD.DualSleeveContractError, match="PREMATURE_13F_TARGET"):
        MOD.validate_pit_target_dates(bad)


def test_post_2025_outcome_is_rejected() -> None:
    bad = pd.DataFrame({
        "signal_date": [pd.Timestamp("2025-12-01")],
        "quarter_effective_date": [pd.Timestamp("2025-11-20")],
        "target_end_date": [pd.Timestamp("2026-01-02")],
        "target": [0.1],
    })
    with pytest.raises(MOD.DualSleeveContractError, match="POST2025_OUTCOME_USED"):
        MOD.validate_pit_target_dates(bad)


def test_raw_and_institutional_saved_controls_are_present() -> None:
    prior = pd.read_csv(MOD.PRIOR_OUT / "strategy_metrics.csv")
    aggregate = prior.loc[prior.scope_type.eq("aggregate")].set_index("strategy")
    assert "C0_RAW_A2" in aggregate.index
    assert "C1_INSTITUTIONAL_CHANGE_STANDALONE" in aggregate.index
    assert aggregate.at["C0_RAW_A2", "sharpe"] == pytest.approx(1.2353699802070324)
    assert aggregate.at["C1_INSTITUTIONAL_CHANGE_STANDALONE", "sharpe"] == pytest.approx(1.3267859066006926)


def test_combined_target_construction_is_deterministic() -> None:
    first, first_audit = MOD.combine_target_maps(*sleeve_maps())
    a2, institutional = sleeve_maps()
    a2 = {date: dict(reversed(list(target.items()))) for date, target in a2.items()}
    institutional = {date: dict(reversed(list(target.items()))) for date, target in institutional.items()}
    second, second_audit = MOD.combine_target_maps(a2, institutional)
    assert first == second
    pd.testing.assert_frame_equal(first_audit, second_audit, check_exact=True)
    assert MOD.fingerprint_target_map(first) == MOD.fingerprint_target_map(second)


def test_positive_increment_concentration_uses_positive_denominator() -> None:
    values = pd.Series([0.3, 0.2, -0.9, 0.1])
    assert MOD.positive_concentration(values, 1) == pytest.approx(0.5)
    assert MOD.positive_concentration(values, 3) == pytest.approx(1.0)


def test_daily_curve_metrics_are_deterministic() -> None:
    daily = pd.DataFrame({
        "execution_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
        "reconstructed_daily_return": [0.01, -0.005],
        "reconstructed_gross_return": [0.011, -0.004],
        "reconstructed_turnover": [0.5, 0.1],
        "reconstructed_transaction_cost": [0.0005, 0.0001],
        "actual_risky_name_count": [20, 20],
    })
    first = MOD.metrics_from_daily(daily)
    second = MOD.metrics_from_daily(daily.copy())
    assert first == second
    assert first["cumulative_return"] == pytest.approx((1.01 * 0.995) - 1.0)


def test_not_applicable_nonfinite_diagnostic_serializes_as_null() -> None:
    assert MOD.json_safe({"share": float("nan")}) == {"share": None}
