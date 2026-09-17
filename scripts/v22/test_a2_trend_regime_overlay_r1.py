from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_trend_regime_overlay_r1.py")


def load_module(name: str = "a2_trend_regime_overlay_test"):
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_market(periods: int = 620) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=periods)
    rows = []
    for ticker, offset, wave in (("QQQ", 100.0, 2.0), ("SOXX", 80.0, 3.0)):
        close = offset + np.linspace(0, 50, periods) + wave * np.sin(np.arange(periods) / 11.0)
        rows.append(pd.DataFrame({"ticker": ticker, "trade_date": dates, "close": close}))
    return pd.concat(rows, ignore_index=True)


def test_signal_uses_completed_prior_session_and_sma_has_no_future_leakage() -> None:
    module = load_module()
    market = synthetic_market()
    original = module.compute_market_regime(market)
    changed = market.copy()
    cutoff = pd.Timestamp("2021-12-31")
    changed.loc[changed.trade_date > cutoff, "close"] *= 50.0
    perturbed = module.compute_market_regime(changed)
    columns = ["qqq_sma200", "soxx_sma200", "trend_multiplier"]
    pd.testing.assert_frame_equal(
        original.loc[original.trade_date <= cutoff, columns].reset_index(drop=True),
        perturbed.loc[perturbed.trade_date <= cutoff, columns].reset_index(drop=True),
    )
    calendar = pd.DatetimeIndex(sorted(market.trade_date.unique()))
    signals = calendar[400:410]
    schedule = module.regime_schedule(original, signals, calendar)
    assert (schedule.indicator_source_date == schedule.signal_date).all()
    assert (schedule.execution_date > schedule.indicator_source_date).all()
    assert schedule.signal_lag_sessions.eq(1).all()


def test_rv20_and_trailing252_percentile_have_no_future_leakage() -> None:
    module = load_module("a2_regime_vol_test")
    market = synthetic_market()
    original = module.compute_market_regime(market)
    cutoff = pd.Timestamp("2021-12-31")
    changed = market.copy()
    changed.loc[changed.trade_date > cutoff, "close"] *= np.linspace(1.0, 4.0, (changed.trade_date > cutoff).sum())
    perturbed = module.compute_market_regime(changed)
    columns = ["qqq_rv20", "soxx_rv20", "qqq_vol_percentile", "soxx_vol_percentile", "vol_multiplier"]
    pd.testing.assert_frame_equal(
        original.loc[original.trade_date <= cutoff, columns].reset_index(drop=True),
        perturbed.loc[perturbed.trade_date <= cutoff, columns].reset_index(drop=True),
    )
    series = pd.Series(np.arange(1.0, 254.0))
    ranked = module.rolling_percentile_current(series, 252)
    assert np.isnan(ranked.iloc[250])
    assert ranked.iloc[251] == 1.0


def test_fixed_multiplier_states_and_combined_min_rule() -> None:
    module = load_module("a2_regime_state_test")
    regime = module.compute_market_regime(synthetic_market())
    valid = regime.dropna(subset=["qqq_vol_percentile", "soxx_vol_percentile"])
    for column in ("trend_multiplier", "vol_multiplier", "combined_multiplier"):
        assert set(valid[column]).issubset({0.50, 0.75, 1.00})
    np.testing.assert_array_equal(
        valid.combined_multiplier.to_numpy(),
        valid[["trend_multiplier", "vol_multiplier"]].min(axis=1).to_numpy(),
    )


def test_scaled_weights_preserve_names_relative_weights_cash_and_no_leverage() -> None:
    module = load_module("a2_regime_scale_test")
    date = pd.Timestamp("2025-01-02")
    base = {date: {"AAA": 0.30, "BBB": 0.20, "CCC": 0.50}}
    scaled = module.scale_target_map(base, {date: 0.75})
    assert set(scaled[date]) == set(base[date])
    assert sum(scaled[date].values()) == pytest.approx(0.75)
    assert 1.0 - sum(scaled[date].values()) == pytest.approx(0.25)
    assert scaled[date]["AAA"] / scaled[date]["BBB"] == pytest.approx(1.5)
    assert all(weight >= 0 for weight in scaled[date].values())


def test_invalid_target_and_invalid_multiplier_fail_closed() -> None:
    module = load_module("a2_regime_guard_test")
    date = pd.Timestamp("2025-01-02")
    with pytest.raises(module.RegimeContractError, match="INVALID_TARGET_MULTIPLIER"):
        module.scale_target_map({date: {"AAA": 1.0}}, {date: 0.60})
    with pytest.raises(module.RegimeContractError, match="INVALID_BASE_TARGET"):
        module.scale_target_map({date: {"AAA": 1.01}}, {date: 0.75})
    with pytest.raises(module.RegimeContractError, match="INVALID_BASE_TARGET"):
        module.scale_target_map({date: {"AAA": -0.01}}, {date: 0.75})


def test_regime_transition_turnover_and_cost_enter_existing_engine() -> None:
    module = load_module("a2_regime_engine_test")
    r0f = module.import_file("r0f_for_regime_test", Path(__file__).with_name("fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"))
    dates = pd.bdate_range("2025-01-02", periods=16)
    qfq = pd.concat([
        pd.DataFrame({"ticker": ticker, "trade_date": dates, "open": price, "close": price})
        for ticker, price in (("QQQ", 100.0), ("AAA", 50.0))
    ], ignore_index=True)
    signals = pd.DatetimeIndex(dates[1:12])
    raw = {date: {"AAA": 1.0} for date in signals}
    multiplier = {date: (0.50 if 4 <= index <= 6 else 1.0) for index, date in enumerate(signals)}
    overlay = module.scale_target_map(raw, multiplier)
    raw_path = r0f.reconstruct_path(model="RAW", target_map=raw, qfq=qfq, signal_dates=signals, cost_bps=10)
    overlay_path = r0f.reconstruct_path(model="OVERLAY", target_map=overlay, qfq=qfq, signal_dates=signals, cost_bps=10)
    assert overlay_path.daily.reconstructed_turnover.sum() > raw_path.daily.reconstructed_turnover.sum()
    assert overlay_path.daily.reconstructed_transaction_cost.sum() > raw_path.daily.reconstructed_transaction_cost.sum()
    assert overlay_path.daily.TURNOVER_IDENTITY_ERROR.abs().max() <= np.finfo(float).eps
    assert overlay_path.daily.TRANSACTION_COST_IDENTITY_ERROR.abs().max() <= np.finfo(float).eps


def test_fixed_dual_sleeve_contract_is_reused_without_score_blend() -> None:
    module = load_module("a2_regime_dual_test")
    dual = module.import_file("dual_for_regime_test", module.DUAL_SOURCE)
    assert dual.A2_WEIGHT == 0.80
    assert dual.INSTITUTIONAL_WEIGHT == 0.20
    date = pd.Timestamp("2025-01-02")
    a2 = {date: {f"A{i:02d}": 0.05 for i in range(20)}}
    inst = {date: {f"I{i:02d}": 0.05 for i in range(20)}}
    combined, _ = dual.combine_target_maps(a2, inst)
    scaled = module.scale_target_map(combined, {date: 0.50})
    assert scaled[date]["A00"] == pytest.approx(0.02)
    assert scaled[date]["I00"] == pytest.approx(0.005)
    source = SOURCE.read_text(encoding="utf-8")
    assert "0.8 * A2_RANK" not in source
    assert "score_blend" not in source.lower()


def test_raw_control_saved_contract_is_exact_and_pre2026() -> None:
    module = load_module("a2_regime_control_test")
    prior_ledger = json.loads((module.DUAL_OUT / "trial_ledger.json").read_text(encoding="utf-8"))
    assert prior_ledger["reconciliation"]["S0_RAW_A2"]["status"] == "PASS_EXACT_OR_MACHINE_PRECISION"
    assert prior_ledger["post_2025_outcome_used"] is False
    curves = pd.read_csv(module.DUAL_OUT / "daily_curves.csv", parse_dates=["date"])
    assert curves.date.max() == pd.Timestamp("2025-12-31")
    assert (curves.date < pd.Timestamp("2026-01-01")).all()


def test_deterministic_regime_and_scaled_targets() -> None:
    module = load_module("a2_regime_determinism_test")
    market = synthetic_market()
    first = module.compute_market_regime(market)
    second = module.compute_market_regime(market)
    pd.testing.assert_frame_equal(first, second)
    dates = pd.bdate_range("2025-01-02", periods=3)
    targets = {date: {"AAA": 0.5, "BBB": 0.5} for date in dates}
    multipliers = {dates[0]: 1.0, dates[1]: 0.75, dates[2]: 0.50}
    assert module.scale_target_map(targets, multipliers) == module.scale_target_map(targets, multipliers)


def test_no_2026_signal_or_outcome_is_accepted_in_schedule() -> None:
    module = load_module("a2_regime_boundary_test")
    market = synthetic_market(1600)
    market = market.loc[market.trade_date < pd.Timestamp("2026-01-01")]
    regime = module.compute_market_regime(market)
    calendar = pd.DatetimeIndex(sorted(market.trade_date.unique()))
    signals = calendar[(calendar >= pd.Timestamp("2025-12-01")) & (calendar < pd.Timestamp("2026-01-01"))][:-1]
    schedule = module.regime_schedule(regime, signals, calendar)
    assert schedule.execution_date.max() < pd.Timestamp("2026-01-01")


def test_bootstrap_is_fixed_seed_deterministic() -> None:
    module = load_module("a2_regime_bootstrap_test")
    difference = np.sin(np.arange(300)) / 1000.0
    first = module.bootstrap_block(difference, 21, repeats=100, seed=7)
    second = module.bootstrap_block(difference, 21, repeats=100, seed=7)
    assert first == second
