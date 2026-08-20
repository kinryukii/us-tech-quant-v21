from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import abcde_a2_r4_portfolio_translation_using_hgb_incumbent as r4


def _metric(cumulative: float, cagr: float, sharpe: float, calmar: float) -> dict:
    return {
        "cumulative_return": cumulative, "cagr": cagr, "sharpe_rf0": sharpe,
        "calmar": calmar, "max_drawdown": -0.1, "annualized_turnover": 5.0,
        "cost_drag": 0.01, "net_excess_return": cumulative - 0.02,
    }


def _gate_fixture(a1_value: float, a2_value: float, better_years: int = 3) -> dict:
    result = {"A1": {"20": {"10": {}}}, "A2_HGB": {"20": {"10": {}}}}
    result["A1"]["20"]["10"]["POOLED_PRE2026"] = _metric(a1_value, a1_value, a1_value, a1_value)
    result["A2_HGB"]["20"]["10"]["POOLED_PRE2026"] = _metric(a2_value, a2_value, a2_value, a2_value)
    for index, year in enumerate((2023, 2024, 2025)):
        a1_year = 0.01
        a2_year = 0.02 if index < better_years else 0.0
        result["A1"]["20"]["10"][str(year)] = _metric(a1_year, a1_year, a1_year, a1_year)
        result["A2_HGB"]["20"]["10"][str(year)] = _metric(a2_year, a2_year, a2_year, a2_year)
    return result


def test_contract_is_immutable_and_frozen_before_outcome_read():
    witness = json.loads(r4.WITNESS_PATH.read_text(encoding="utf-8"))
    assert witness["status"] == "PASS_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ"
    assert witness["future_execution_price_value_read_count_before_freeze"] == 0
    assert witness["portfolio_outcome_read_count_before_freeze"] == 0
    assert r4.sha256_file(r4.CONTRACT_PATH) == r4.EXPECTED_CONTRACT_SHA256
    assert r4.freeze_contract()["contract_sha256"] == r4.EXPECTED_CONTRACT_SHA256


def test_execution_timing_is_next_open_and_same_close_forbidden():
    timing = r4.portfolio_contract()["signal_and_execution"]
    assert timing["same_close_execution_allowed"] is False
    assert timing["first_legal_execution_timestamp"] == "NEXT_QQQ_CANONICAL_TRADING_SESSION_OPEN_AFTER_SIGNAL_DATE"
    assert timing["execution_price_field"] == "canonical_qfq_open"
    assert timing["future_fill_allowed"] is False


def test_portfolio_cost_and_gate_are_frozen_without_search():
    contract = r4.portfolio_contract()
    assert contract["portfolio"]["primary"]["top_n"] == 20
    assert contract["portfolio"]["primary"]["target_weight_per_name"] == 0.05
    assert contract["transaction_cost"]["primary_one_way_cost_bps"] == 10
    assert contract["transaction_cost"]["sensitivity_bps"] == [0, 5, 10, 20]
    assert contract["decision_gate"]["primary_top_n"] == 20
    assert contract["prohibitions"]["new_model"] is True
    assert contract["prohibitions"]["model_tuning"] is True


def test_authoritative_prerequisite_hashes_and_statuses_pass():
    r1, r2, r3, audit = r4.validate_prerequisites()
    assert r1["ABCDE_A2_R1_CLASSIFICATION"] == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE"
    assert r2["ABCDE_A2_R2_CLASSIFICATION"] == "M1_STRONG_MECHANISTIC_SUPPORT"
    assert r3["R3_CLASSIFICATION"] == "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE"
    assert all(audit["checks"].values())


def test_signal_artifact_has_common_rows_and_no_target_or_2026_read():
    signals, audit = r4.load_authoritative_signals()
    assert list(signals.columns) == ["signal_date", "ticker", "universe_size", "split", "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"]
    assert len(signals) == 210445
    assert audit["a1_a2_signal_date_identity"] is True
    assert audit["oof_target_availability_gap_date_count"] == 16
    assert audit["shared_cash_override_incomplete_topn_date_count"]["20"] == 3
    assert (signals.signal_date < pd.Timestamp("2026-01-01")).all()


def test_path_accounting_buys_next_open_and_liquidates_without_new_signal():
    dates = pd.bdate_range("2024-01-02", periods=3)
    signals = pd.DataFrame({
        "signal_date": [dates[0], dates[0]], "ticker": ["AAA", "BBB"],
        "a1_rank": [1, 2], "a2_rank": [2, 1],
    })
    prices = pd.DataFrame([
        {"trade_date": date, "ticker": ticker, "open": value, "close": value}
        for date, a, b, q in zip(dates, (100, 110, 121), (100, 100, 100), (100, 101, 102))
        for ticker, value in (("AAA", a), ("BBB", b), ("QQQ", q))
    ])
    path = r4.simulate_portfolio(signals, prices, "A1", "a1_rank", 2, 0)
    assert path.execution_date.tolist() == [dates[1], dates[2]]
    assert path.iloc[0].signal_date_used == dates[0]
    assert np.isclose(path.iloc[0].turnover, 0.5)
    assert np.isclose(path.iloc[1].gross_return, 0.05)
    assert np.isclose(path.iloc[1].turnover, 0.5)
    assert pd.isna(path.iloc[1].signal_date_used)


def test_execution_eligibility_policy_is_immutable_generic_and_outcome_blind():
    witness = json.loads(r4.EXECUTION_ELIGIBILITY_WITNESS_PATH.read_text(encoding="utf-8"))
    policy = json.loads(r4.EXECUTION_ELIGIBILITY_POLICY_PATH.read_text(encoding="utf-8"))
    assert witness["status"] == "PASS_FROZEN_OUTCOME_BLIND_BEFORE_R4_PORTFOLIO_MATERIALIZATION"
    assert witness["portfolio_outcome_read_count_before_freeze"] == 0
    assert witness["prior_outcome_audit"]["R4_PORTFOLIO_OUTCOME_PREVIOUSLY_READ"] is False
    assert policy["execution_eligibility_equation"] == "HAS_AUTHORITATIVE_CANONICAL_QFQ_OPEN_SECURITY_DATE"
    assert policy["missing_entry_execution_policy"] == "SKIP_ENTRY_HOLD_CASH"
    assert policy["missing_held_execution_policy"] == "HOLD_POSITION_NO_TRADE"
    assert policy["ticker_specific_exception_allowed"] is False
    assert policy["permanent_security_exclusion"] is False
    assert r4.sha256_file(r4.CONTRACT_PATH) == r4.EXPECTED_CONTRACT_SHA256


def test_missing_held_open_uses_stale_mark_without_trade_then_rechecks_next_session():
    dates = pd.bdate_range("2024-01-02", periods=4)
    signals = pd.DataFrame([
        {"signal_date": dates[0], "ticker": "AAA", "a1_rank": 1, "a2_rank": 1},
        {"signal_date": dates[0], "ticker": "BBB", "a1_rank": 2, "a2_rank": 2},
        {"signal_date": dates[1], "ticker": "BBB", "a1_rank": 1, "a2_rank": 1},
        {"signal_date": dates[1], "ticker": "CCC", "a1_rank": 2, "a2_rank": 2},
    ])
    rows = []
    for date in dates:
        for ticker in ("AAA", "BBB", "CCC", "QQQ"):
            if ticker == "AAA" and date == dates[2]:
                continue
            rows.append({"trade_date": date, "ticker": ticker, "open": 100.0, "close": 100.0})
    prices = pd.DataFrame(rows)
    path = r4.simulate_portfolio(signals, prices, "A1", "a1_rank", 2, 10)
    blocked = path.loc[path.execution_date == dates[2]].iloc[0]
    assert blocked.blocked_sell_or_rebalance_count == 1
    assert bool(blocked.stale_mark) is True
    assert blocked.stale_mark_oldest_source_date == dates[1]
    assert path.iloc[-1].actual_risky_name_count == 0
    assert (path.cash_weight >= -1e-12).all()
    assert (path.buy_cash_scale <= 1.0).all()


def test_execution_open_coverage_audit_is_deterministic_and_fail_closed():
    dates = pd.bdate_range("2024-01-02", periods=3)
    tickers = [f"T{index:02d}" for index in range(20)]
    signals = pd.DataFrame({
        "signal_date": dates[0], "ticker": tickers,
        "a1_rank": np.arange(1, 21), "a2_rank": np.arange(20, 0, -1),
    })
    prices = pd.DataFrame([
        {"trade_date": date, "ticker": ticker, "open": (np.nan if ticker == "T00" and date == dates[2] else 100.0)}
        for date in dates for ticker in tickers
    ])
    prices = pd.concat([prices, pd.DataFrame({"trade_date": dates, "ticker": "QQQ", "open": [100.0, 101.0, 102.0]})], ignore_index=True)
    first = r4.execution_open_coverage_audit(signals, prices)
    second = r4.execution_open_coverage_audit(signals, prices)
    assert first == second
    assert first["status"] == "FAIL_CLOSED_MISSING_CANONICAL_EXECUTION_OPEN"
    assert any(event["ticker"] == "T00" for event in first["missing_events"])


def test_metrics_are_true_compounded_path_not_forward_target_average():
    dates = pd.bdate_range("2024-01-02", periods=3)
    frame = pd.DataFrame({
        "execution_date": dates, "net_return": [0.1, -0.1, 0.0],
        "gross_return": [0.1, -0.1, 0.0], "benchmark_return": [0.0, 0.0, 0.0],
        "turnover": [0.5, 0.0, 0.5], "transaction_cost_amount": 0.0,
        "transaction_cost_fraction": 0.0,
    })
    metrics = r4.portfolio_metrics(frame)
    assert np.isclose(metrics["cumulative_return"], -0.01)
    assert metrics["max_drawdown"] < 0
    assert metrics["total_turnover"] == 1.0


def test_frozen_gate_yields_p1_p2_p3_and_fail_closed():
    assert r4.classify_translation(_gate_fixture(0.1, 0.2, 3), True)[0] == "P1_STRONG_PORTFOLIO_TRANSLATION"
    assert r4.classify_translation(_gate_fixture(0.1, 0.11, 1), True)[0] == "P2_PARTIAL_OR_COST_SENSITIVE_TRANSLATION"
    assert r4.classify_translation(_gate_fixture(0.1, 0.0, 0), True)[0] == "P3_RANKING_EDGE_DOES_NOT_TRANSLATE"
    assert r4.classify_translation(_gate_fixture(0.1, 0.2, 3), False)[0] == "FAIL_CLOSED"


def test_benchmark_is_uniquely_qqq_open_to_open():
    benchmark = r4.benchmark_contract()
    assert benchmark["identity"] == "QQQ"
    assert benchmark["price_field"] == "canonical_qfq_open"
    assert benchmark["inheritance"] == "R1_TARGET_CANONICAL_BENCHMARK"
    assert r4.portfolio_contract()["benchmark"]["benchmark_contract_fingerprint"] == r4.canonical_fingerprint(benchmark)


def test_completed_outputs_are_reproducible_and_pre2026_if_present():
    if not r4.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r4.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("ABCDE_A2_R4_STATUS") == "FAIL_CLOSED":
        if summary.get("RUN1_FINGERPRINT") is not None:
            assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
        return
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    assert summary["POST2025_TARGET_READ_COUNT"] == 0
    assert summary["POST2025_OUTCOME_READ_COUNT"] == 0
    daily = pq.read_table(r4.DAILY_PATH).to_pandas()
    assert (pd.to_datetime(daily.execution_date) < pd.Timestamp("2026-01-01")).all()
    assert set(daily.top_n) == {20}
    assert set(daily.cost_bps) == {10}


def test_r4e_completed_outputs_apply_generic_policy_and_preserve_cash_if_present():
    if not r4.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r4.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("ABCDE_A2_R4_STATUS") != "PASS":
        return
    assert summary["EXECUTION_ELIGIBILITY_POLICY_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ"] is True
    assert summary["R4_PORTFOLIO_OUTCOME_PREVIOUSLY_READ"] is False
    assert summary["MODEL_COHORT_CHANGED"] is False
    assert summary["PERMANENT_SECURITY_EXCLUSION_COUNT"] == 0
    assert summary["EXECUTION_INELIGIBLE_EVENT_COUNT"] == 1
    audit = pq.read_table(r4.EXECUTION_ELIGIBILITY_AUDIT_PATH).to_pandas()
    missing = audit.loc[~audit.execution_eligible]
    assert len(missing) == 1
    assert missing.iloc[0].ticker == "HIVE"
    assert pd.Timestamp(missing.iloc[0].execution_date) == pd.Timestamp("2023-07-12")
    assert missing.iloc[0].required_action == "SELL_EXIT"
    daily = pq.read_table(r4.DAILY_PATH).to_pandas()
    assert (daily.cash_weight >= -1e-12).all()
    assert (daily.executed_turnover <= daily.target_turnover + 1e-10).all()
    assert int(daily.blocked_sell_or_rebalance_count.sum()) == 1
    if summary["R4_CLASSIFICATION"] == "P1_STRONG_PORTFOLIO_TRANSLATION":
        activation = json.loads(r4.ACTIVATION_PATH.read_text(encoding="utf-8"))
        assert activation["NO_BACKFILL"] is True
        assert activation["POST2025_TARGET_READ_COUNT"] == 0
        assert activation["POST2025_OUTCOME_READ_COUNT"] == 0


def test_no_production_fast_broker_or_optimizer_authority():
    contract = r4.portfolio_contract()
    assert contract["portfolio"]["portfolio_optimizer"] is False
    assert contract["portfolio"]["fast_gating"] is False
    assert contract["prospective_activation"]["production_adoption"] is False
    assert contract["prospective_activation"]["broker_action_allowed"] is False
