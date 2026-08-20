from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import abcde_a2_r2_signal_lag_and_incremental_mechanism as r2


def _synthetic_oof(days: int = 8, tickers: int = 25) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=days)
    rows = []
    for day_index, date in enumerate(dates):
        for ticker_index in range(tickers):
            rows.append({
                "signal_date": date, "ticker": f"T{ticker_index:03d}", "split": "CONFIRMATION",
                "target": (ticker_index - 12) / 100.0 + day_index / 1000.0,
                "a1_raw_score": float(tickers - ticker_index), "a1_rank": ticker_index + 1,
                "a2_prediction": float(ticker_index), "a2_rank": tickers - ticker_index,
                "universe_size": tickers,
            })
    return pd.DataFrame(rows)


def test_analysis_contract_was_frozen_before_outcome_read_and_is_immutable():
    witness = json.loads(r2.FREEZE_WITNESS_PATH.read_text(encoding="utf-8"))
    assert witness["status"] == "PASS_FROZEN_BEFORE_OUTCOME_READ"
    assert witness["r1_outcome_or_prediction_read_count_before_freeze"] == 0
    assert r2.sha256_file(r2.ANALYSIS_CONTRACT_PATH) == r2.EXPECTED_ANALYSIS_CONTRACT_SHA256
    assert r2.freeze_analysis_contract()["contract_sha256"] == r2.EXPECTED_ANALYSIS_CONTRACT_SHA256


def test_r1_authoritative_artifacts_and_identity_are_exact():
    _, summary, oof, families, audit = r2.validate_authoritative_r1()
    assert summary["ABCDE_A2_R1_STATUS"] == "PASS"
    assert summary["ABCDE_A2_R1_CLASSIFICATION"] == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE"
    assert summary["A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS"] == "PASS"
    assert all(audit["checks"].values())
    assert len(oof) == 210445
    assert sum(map(len, families.values())) == 32


def test_entry_event_requires_five_prior_non_top_days():
    dates = pd.bdate_range("2024-01-02", periods=8)
    frame = pd.DataFrame({
        "signal_date": dates, "ticker": "AAA", "split": "CONFIRMATION", "target": 0.0,
        "a1_raw_score": 0.0, "a2_prediction": 0.0, "universe_size": 30,
        "a1_rank": [30, 30, 30, 30, 30, 10, 10, 30],
        "a2_rank": [30, 30, 30, 30, 30, 10, 10, 30],
    })
    events = r2.build_entry_events(frame)
    assert len(events) == 4  # A1/A2 times Top20/Top10
    assert set(events.signal_date) == {dates[5]}


def test_signal_path_uses_same_qqq_trading_date_endpoints():
    dates = pd.bdate_range("2024-01-02", periods=30)
    qqq = pd.DataFrame({"ticker": "QQQ", "trade_date": dates, "close": np.arange(30) + 100.0})
    aaa = pd.DataFrame({"ticker": "AAA", "trade_date": dates, "close": 2.0 * (np.arange(30) + 100.0)})
    event = pd.DataFrame({"signal_date": [dates[10]], "ticker": ["AAA"], "split": ["CONFIRMATION"], "model": ["A2"], "top_n": [20], "year": [2024], "year_role": ["CONFIRMATION_EXPLANATORY"]})
    result = r2.attach_signal_paths(event, pd.concat([aaa, qqq], ignore_index=True))
    for column in ("PRE_5D_ER", "PRE_3D_ER", "PRE_1D_ER", "POST_1D_ER", "POST_3D_ER", "POST_5D_ER", "POST_10D_ER"):
        assert np.isclose(result.loc[0, column], 0.0)


def test_disagreement_direction_q5_is_a2_upgrade():
    analysis, spreads = r2.disagreement_analysis(_synthetic_oof(days=2))
    assert spreads["2024"] > 0
    q1 = analysis.query("scope == '2024' and disagreement_quintile == 1").iloc[0]
    q5 = analysis.query("scope == '2024' and disagreement_quintile == 5").iloc[0]
    assert q5.mean_target > q1.mean_target


def test_daily_incremental_edge_and_distribution_are_deterministic():
    daily1 = r2.build_daily_edge(_synthetic_oof())
    daily2 = r2.build_daily_edge(_synthetic_oof())
    pd.testing.assert_frame_equal(daily1, daily2)
    assert (daily1.delta_ic > 0).all()
    stats = r2.distribution(daily1.delta_ic)
    assert stats["positive_fraction"] == 1.0


def test_state_analysis_runs_all_32_features_without_selection():
    oof = _synthetic_oof(days=8)
    matrix = oof[["signal_date", "ticker"]].copy()
    for index, feature in enumerate(r2.import_module("r1_test_state", r2.R1_MODULE_PATH).FEATURE_COLUMNS):
        matrix[feature] = np.arange(len(matrix), dtype=float) + index
    daily = r2.build_daily_edge(oof)
    output, relationships = r2.state_conditional_analysis(matrix, oof, daily, tuple(matrix.columns[2:]))
    frozen_states = output.query("state_kind == 'FROZEN_FEATURE_DAILY_STATE'")
    assert frozen_states.state_feature.nunique() == 64
    assert set(frozen_states.quartile) == {1, 2, 3, 4}
    assert "2024" in relationships


def test_mechanism_gate_m1_m2_m3_and_fail_are_predefined():
    spreads = {"2024": 0.1, "2025": 0.1, "POOLED": 0.1}
    lag = {year: {"a2_minus_a1_post5_mean": 0.1, "a2_minus_a1_post10_mean": 0.1} for year in ("2024", "2025")}
    daily = {year: {"delta_ic": {"trimmed_mean_5pct": 0.1}} for year in ("2024", "2025")}
    assert r2.classify_mechanism(spreads, lag, daily, True, True)[0] == "M1_STRONG_MECHANISTIC_SUPPORT"
    assert r2.classify_mechanism({**spreads, "2025": -0.1}, lag, daily, True, True)[0] == "M2_PARTIAL_OR_MIXED_MECHANISM"
    negative_lag = {year: {"a2_minus_a1_post5_mean": -0.1, "a2_minus_a1_post10_mean": -0.1} for year in ("2024", "2025")}
    negative_daily = {year: {"delta_ic": {"trimmed_mean_5pct": -0.1}} for year in ("2024", "2025")}
    assert r2.classify_mechanism({"2024": -0.1, "2025": -0.1, "POOLED": -0.1}, negative_lag, negative_daily, False, True)[0] == "M3_INCREMENTAL_EDGE_NOT_MECHANISTICALLY_RESOLVED"
    assert r2.classify_mechanism(spreads, lag, daily, True, False)[0] == "FAIL_CLOSED"


def test_completed_outputs_have_no_2026_and_reproduce_if_present():
    if not r2.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r2.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("ABCDE_A2_R2_STATUS") != "PASS":
        return
    assert summary["POST2025_TARGET_READ_COUNT"] == 0
    assert summary["POST2025_OUTCOME_READ_COUNT"] == 0
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    events = pq.read_table(r2.SIGNAL_EVENTS_PATH).to_pandas()
    assert (pd.to_datetime(events.signal_date) < pd.Timestamp("2026-01-01")).all()
    interactions = json.loads(r2.FEATURE_MECHANISM_PATH.read_text(encoding="utf-8"))["pairwise_interactions_all_15_each_stage"]
    assert len(interactions) == 45


def test_no_production_or_fast_mutation_contract():
    contract = r2.analysis_contract()
    assert contract["production"]["A2_R1_MODEL_CHANGED"] is False
    assert contract["production"]["A2_R1_FEATURE_SCHEMA_CHANGED"] is False
    assert contract["production"]["A1_PRODUCTION_CHANGED"] is False
    assert contract["production"]["FAST_CHANGED"] is False
    assert contract["production"]["BROKER_ACTION_COUNT"] == 0
