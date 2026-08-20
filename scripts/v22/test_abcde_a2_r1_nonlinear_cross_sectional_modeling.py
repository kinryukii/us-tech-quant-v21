from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import abcde_a2_r1_nonlinear_cross_sectional_modeling as r1


def _prices(ticker: str, periods: int = 160, start: str = "2022-01-03") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    values = np.linspace(100.0, 180.0, periods)
    return pd.DataFrame({"ticker": ticker, "trade_date": dates, "close": values, "volume": np.arange(periods) + 1000.0})


def test_all_authoritative_frozen_inputs_match_exact_fingerprints():
    frozen = r1.load_and_validate_frozen_inputs()
    assert all(frozen.validation["checks"].values())
    assert frozen.validation["preregistration_sha256"] == r1.EXPECTED_PREREG_FINGERPRINT
    assert frozen.validation["feature_schema_fingerprint"] == r1.EXPECTED_FEATURE_SCHEMA_FINGERPRINT
    assert frozen.validation["model_config_fingerprint"] == r1.EXPECTED_MODEL_CONFIG_FINGERPRINT
    assert len(frozen.eligibility) == 436043


def test_feature_contract_is_exactly_32_and_outcome_blind():
    frozen = r1.load_and_validate_frozen_inputs()
    assert tuple(frozen.prereg.FEATURES) == r1.FEATURE_COLUMNS
    assert len(frozen.feature_contract["features"]) == 32
    assert frozen.feature_contract["ambiguous_feature_count"] == 0
    assert frozen.feature_contract["max_required_lookback_trading_days"] == 120
    assert frozen.feature_contract["max_required_observations"] == 121


def test_feature_equations_and_future_mutation_asof_invariance():
    prices = _prices("AAA")
    original = r1.build_stock_state_features(prices)
    changed_prices = prices.copy()
    changed_prices.loc[changed_prices.index[-1], "close"] = 9999.0
    changed = r1.build_stock_state_features(changed_prices)
    cutoff = len(prices) - 2
    pd.testing.assert_frame_equal(
        original.loc[:cutoff, list(r1.FEATURE_COLUMNS)],
        changed.loc[:cutoff, list(r1.FEATURE_COLUMNS)],
    )
    row = original.iloc[130]
    assert np.isclose(row["ret_20d"], prices.iloc[130].close / prices.iloc[110].close - 1.0)
    returns = prices.close.pct_change(fill_method=None).iloc[111:131]
    assert np.isclose(row["realized_vol_20d"], returns.std(ddof=0))
    assert row["max_drawdown_20d"] <= 0.0


def test_target_alignment_uses_future_trading_dates_only():
    dates = pd.bdate_range("2023-01-02", periods=30)
    qqq = pd.DataFrame({"ticker": "QQQ", "trade_date": dates, "close": np.arange(30) + 100.0, "volume": 1.0})
    aaa = pd.DataFrame({"ticker": "AAA", "trade_date": dates, "close": 2.0 * (np.arange(30) + 100.0), "volume": 1.0})
    matrix = aaa.rename(columns={"trade_date": "signal_date"}).copy()
    matrix["universe_size"] = 1
    targeted = r1.attach_targets(matrix, pd.concat([aaa, qqq], ignore_index=True))
    assert targeted.loc[0, "target_end_date"] == dates[20]
    assert np.isclose(targeted.loc[0, "target"], 0.0)
    assert targeted.tail(20)["target"].isna().all()


def test_twenty_day_boundary_purge_is_strict():
    dates = pd.to_datetime(["2022-11-01", "2022-12-01", "2022-12-15", "2023-01-03"])
    matrix = pd.DataFrame({
        "signal_date": dates,
        "ticker": ["AAA"] * 4,
        "target": [0.1] * 4,
        "target_end_date": pd.to_datetime(["2022-12-01", "2022-12-30", "2023-01-03", "2023-02-01"]),
    })
    train, evaluation, audit = r1.stage_rows(matrix, 2023)
    assert list(train.signal_date) == list(pd.to_datetime(["2022-11-01", "2022-12-01"]))
    assert len(evaluation) == 1
    assert audit["purged_boundary_rows"] == 1
    assert audit["leakage_row_count"] == 0


def test_a1_control_weights_and_reverse_volatility_are_frozen():
    day = pd.DataFrame({
        "signal_date": pd.to_datetime(["2023-01-03"] * 3),
        "ticker": ["AAA", "BBB", "CCC"],
        "a1_momentum_raw": [3.0, 2.0, 1.0],
        "a1_trend_raw": [3.0, 2.0, 1.0],
        "a1_volatility_raw": [3.0, 2.0, 1.0],
        "a1_drawdown_raw": [0.0, -0.1, -0.2],
        "a1_liquidity_raw": [3.0, 2.0, 1.0],
        "a1_data_trust_raw": [1.0, 1.0, 1.0],
    })
    scored = r1.materialize_a1_control(day).set_index("ticker")
    assert scored.loc["AAA", "a1_score_volatility"] == 0.0
    assert scored.loc["CCC", "a1_score_volatility"] == 1.0
    expected_aaa = 0.35 + 0.25 + 0.0 + 0.10 + 0.10 + 0.10
    assert np.isclose(scored.loc["AAA", "a1_raw_score"], expected_aaa)


def test_model_family_config_and_zero_search_are_frozen():
    frozen = r1.load_and_validate_frozen_inputs()
    assert frozen.execution["model_contract"]["family"] == "HistGradientBoostingRegressor"
    assert frozen.execution["model_contract"]["hyperparameter_search_trial_count"] == 0
    assert frozen.execution["model_contract"]["additional_model_allowed"] is False
    assert frozen.prereg.HGB_CONFIG == frozen.execution["model_contract"]["config"]


def test_split_regions_final_unlock_and_gate_are_frozen():
    frozen = r1.load_and_validate_frozen_inputs()
    assert [row["stage"] for row in frozen.split_gate["stages"]] == ["DEVELOPMENT", "CONFIRMATION", "FINAL"]
    assert frozen.split_gate["target_boundary"]["purge_horizon_trading_days"] == 20
    assert frozen.split_gate["target_boundary"]["embargo_after_evaluation_trading_days"] == 0
    assert frozen.split_gate["final_unlock_protocol"]["final_evaluation_max_count"] == 1


def test_gate_classifies_a_b_c_and_failure_without_tuning():
    frozen = r1.load_and_validate_frozen_inputs()
    positive = {
        "confirmation_delta_mean_rank_ic": 0.01, "final_delta_mean_rank_ic": 0.01,
        "confirmation_a2_mean_rank_ic": 0.01, "final_a2_mean_rank_ic": 0.01,
        "confirmation_delta_top20_mean_target": 0.01, "final_delta_top20_mean_target": 0.01,
        "final_delta_top_bottom_spread": 0.01,
        "final_a2_top_quintile_mean_target": 0.01, "final_a2_bottom_quintile_mean_target": 0.0,
    }
    assert frozen.r1c.classify_gate(positive) == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE"
    partial = dict(positive, final_delta_mean_rank_ic=-0.01)
    assert frozen.r1c.classify_gate(partial) == "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE"
    negative = {key: -0.01 for key in positive}
    assert frozen.r1c.classify_gate(negative) == "C_NO_RELIABLE_INCREMENTAL_EDGE"
    assert frozen.r1c.classify_gate(positive, failure_count=1) == "FAIL_CLOSED"


def test_completed_artifacts_have_expected_schema_and_no_2026_target_if_present():
    if not r1.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r1.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("ABCDE_A2_R1_STATUS") != "PASS":
        return
    assert summary["FINAL_EVALUATION_COUNT"] == 1
    assert summary["POST2025_TARGET_READ_COUNT"] == 0
    assert summary["POST2025_OUTCOME_READ_COUNT"] == 0
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    assert summary["A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS"] == "PASS"
    table = pq.read_table(r1.OOF_PATH)
    required = {"signal_date", "ticker", "universe_size", "split", "target", "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"}
    assert required.issubset(table.schema.names)
    dates = pd.to_datetime(table.column("signal_date").to_pandas())
    assert (dates < pd.Timestamp("2026-01-01")).all()


def test_production_files_remain_unchanged():
    hashes = r1.protected_hashes()
    assert hashes["scripts/v21/v21_233_moomoo_only_abcde_rerun.py"] == r1.EXPECTED_A1_PRODUCER_SHA256
    assert r1.sha256_file(r1.PREREG_SOURCE) == r1.EXPECTED_PREREG_SOURCE_SHA256
