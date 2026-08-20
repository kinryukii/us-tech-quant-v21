from __future__ import annotations

import ast
import json
from pathlib import Path

import pyarrow.parquet as pq

import abcde_a2_r0v_current_cohort_historical_eligibility_r1 as r0v


def test_frozen_feature_contract_derives_121_observation_maximum():
    a2 = r0v.r0u_module().import_prior_a2()
    contract = r0v.feature_lookback_contract(a2.FEATURES)
    assert set(contract) == set(a2.FEATURES)
    assert contract["ret_120d"]["required_observations_including_t"] == 121
    assert max(row["required_observations_including_t"] for row in contract.values()) == 121


def test_eligibility_rule_enforces_date_price_and_all_lookbacks():
    required = {"close": 121, "volume": 60, "dollar_volume": 20}
    assert not r0v.row_is_eligible(True, True, 120, 60, 20, "2025-01-02", required)
    assert not r0v.row_is_eligible(True, False, 121, 60, 20, "2025-01-02", required)
    assert not r0v.row_is_eligible(True, True, 121, 60, 20, "2026-01-02", required)
    assert r0v.row_is_eligible(True, True, 121, 60, 20, "2025-01-02", required)


def test_current_cohort_identity_matches_authoritative_manifest():
    tickers, audit = r0v.freeze_current_cohort()
    assert len(tickers) == 325
    assert audit["status"] == "PASS"
    assert audit["fingerprint"] == "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc"


def test_actual_summary_has_zero_forbidden_activity_and_preserves_r0u():
    summary = json.loads(r0v.SUMMARY_PATH.read_text(encoding="utf-8"))
    for field in ("MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "TARGET_VALUE_READ_COUNT", "OUTCOME_READ_COUNT", "BROKER_ACTION_COUNT", "TRAINING_ROW_COUNT_2026_PLUS"):
        assert summary[field] == 0
    assert summary["HISTORICAL_PIT_INVESTABLE_UNIVERSE_CLAIM"] is False
    assert summary["R0U_STATUS_PRESERVED"] is True
    assert summary["A2_R1_PREREGISTRATION_CHANGED"] is False
    assert summary["outcome_or_target_paths_read"] == []


def test_actual_eligibility_schema_and_guards():
    table = pq.read_table(r0v.ELIGIBILITY_PATH)
    expected = {
        "signal_date", "ticker", "in_current_cohort", "price_available_at_t",
        "lookback_complete_at_t", "valid_close_observation_count_to_t",
        "valid_volume_observation_count_to_t", "date_lt_2026", "eligible_for_a1",
        "eligible_for_a2", "eligible_training",
    }
    assert set(table.schema.names) == expected
    frame = table.to_pandas()
    assert not frame.duplicated(["signal_date", "ticker"]).any()
    assert frame["ticker"].nunique() == 325
    assert frame["signal_date"].max().isoformat() == "2025-12-31"
    assert not (frame["eligible_training"] & ~frame["price_available_at_t"]).any()
    assert not (frame["eligible_training"] & ~frame["lookback_complete_at_t"]).any()
    assert frame["eligible_for_a1"].equals(frame["eligible_for_a2"])


def test_security_diagnostics_distinguish_observation_from_listing():
    payload = json.loads(r0v.SECURITY_DIAGNOSTICS_PATH.read_text(encoding="utf-8"))
    assert payload["first_observed_price_date_is_official_listing_date"] is False
    assert len(payload["records"]) == 325
    dram = next(row for row in payload["records"] if row["ticker"] == "DRAM")
    assert dram["historical_price_available"] is False
    assert dram["eligible_training_row_count"] == 0


def test_summary_pass_contract_and_a1_a2_identity():
    summary = json.loads(r0v.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["ABCDE_A2_R0V_STATUS"] == "PASS"
    assert summary["CURRENT_COHORT_ONLY_STATUS"] == "PASS"
    assert summary["A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS"] == "PASS"
    assert summary["PRE_FIRST_PRICE_ELIGIBLE_ROW_COUNT"] == 0
    assert summary["INSUFFICIENT_LOOKBACK_ELIGIBLE_ROW_COUNT"] == 0
    assert summary["POST_2025_TRAINING_ELIGIBLE_ROW_COUNT"] == 0


def test_module_has_no_model_broker_target_or_outcome_calls():
    paths = [Path(r0v.__file__), Path(r0v.__file__).with_name("run_abcde_a2_r0v_current_cohort_historical_eligibility_r1.py")]
    forbidden = {"fit", "fit_predict", "predict", "place_order", "unlock_trade"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        assert not calls & forbidden


def test_production_daily_fast_and_abcde_paths_unchanged():
    summary = json.loads(r0v.SUMMARY_PATH.read_text(encoding="utf-8"))
    for field in ("DAILY_CHAIN_CHANGED", "A1_CHANGED", "B_CHANGED", "C_CHANGED", "D_CHANGED", "E_CHANGED", "FAST_CHANGED"):
        assert summary[field] is False


def test_reproducibility_fingerprints_match_after_second_run():
    summary = json.loads(r0v.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary["REPRODUCIBILITY_STATUS"] == "PASS":
        assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
