from __future__ import annotations

import ast
import json
from pathlib import Path

import abcde_a2_r1c_execution_contract_freeze_r1 as r1c


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_original_preregistration_is_immutable_and_exact():
    prereg = r1c.load_original_preregistration()
    assert r1c.canonical_fingerprint(r1c.original_prereg_contract(prereg)) == r1c.ORIGINAL_PREREG_FINGERPRINT
    assert r1c.sha256_file(r1c.ORIGINAL_PREREG) == r1c.ORIGINAL_PREREG_SOURCE_SHA256


def test_all_32_features_are_fully_machine_specified():
    prereg = r1c.load_original_preregistration()
    contract = r1c.build_feature_contract(prereg.FEATURES)
    assert contract["feature_count"] == 32
    assert contract["fully_specified_feature_count"] == 32
    assert contract["ambiguous_feature_count"] == 0
    assert contract["max_required_lookback_trading_days"] == 120
    assert contract["max_required_observations"] == 121
    assert all(set(r1c.REQUIRED_FEATURE_FIELDS).issubset(row) for row in contract["features"])


def test_primitive_equations_and_nan_policies_are_frozen():
    rows = {row["feature_name"]: row for row in read(r1c.FEATURE_CONTRACT_PATH)["features"]}
    assert rows["ret_120d"]["exact_equation"] == "P_t / P_(t-120) - 1"
    assert rows["realized_vol_20d"]["ddof_if_any"] == "0"
    assert rows["realized_vol_20d"]["annualization_if_any"] == "NONE"
    assert "SIGNED_LE_ZERO" in rows["max_drawdown_60d"]["exact_equation"]
    assert rows["avg_dollar_volume_20d"]["source_series"] == "canonical_qfq_close*canonical_volume"
    assert all("NO_BACKWARD_FILL" in row["missing_value_policy"] for row in rows.values())


def test_purge_embargo_stages_and_final_lock_are_exact():
    contract = read(r1c.SPLIT_GATE_PATH)
    boundary = contract["target_boundary"]
    assert boundary["purge_horizon_trading_days"] == 20
    assert boundary["embargo_after_evaluation_trading_days"] == 0
    assert [row["stage"] for row in contract["stages"]] == ["DEVELOPMENT", "CONFIRMATION", "FINAL"]
    assert [row["evaluation_region"][:4] for row in contract["stages"]] == ["2023", "2024", "2025"]
    assert contract["final_unlock_protocol"]["final_evaluation_max_count"] == 1
    assert contract["final_unlock_protocol"]["persist_before_any_2025_target_read"] is True


def test_existing_hgb_config_is_reused_without_search():
    prereg = r1c.load_original_preregistration()
    execution = read(r1c.EXECUTION_CONTRACT_PATH)
    assert execution["model_contract"]["family"] == "HistGradientBoostingRegressor"
    assert execution["model_contract"]["config"] == prereg.HGB_CONFIG
    assert execution["model_contract"]["hyperparameter_search_trial_count"] == 0
    assert execution["model_contract"]["unsupported_installed_api_parameters"] == []


def test_decision_gate_is_executable_for_a_b_c_and_fail():
    base = {
        "confirmation_delta_mean_rank_ic": 1.0, "final_delta_mean_rank_ic": 1.0,
        "confirmation_a2_mean_rank_ic": 1.0, "final_a2_mean_rank_ic": 1.0,
        "confirmation_delta_top20_mean_target": 1.0, "final_delta_top20_mean_target": 1.0,
        "final_delta_top_bottom_spread": 1.0, "final_a2_top_quintile_mean_target": 1.0,
        "final_a2_bottom_quintile_mean_target": 0.0,
    }
    assert r1c.classify_gate(base) == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE"
    partial = dict(base, final_delta_top20_mean_target=-1.0)
    assert r1c.classify_gate(partial) == "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE"
    none = {key: -1.0 for key in base}
    assert r1c.classify_gate(none) == "C_NO_RELIABLE_INCREMENTAL_EDGE"
    assert r1c.classify_gate(base, failure_count=1) == "FAIL_CLOSED"


def test_artifacts_are_canonical_and_hashes_match_summary():
    summary = read(r1c.SUMMARY_PATH)
    for path, field in ((r1c.EXECUTION_CONTRACT_PATH, "EXECUTION_CONTRACT_SHA256"), (r1c.FEATURE_CONTRACT_PATH, "FEATURE_CONTRACT_SHA256"), (r1c.SPLIT_GATE_PATH, "SPLIT_GATE_SHA256")):
        value = read(path)
        assert path.read_bytes() == r1c.canonical_bytes(value)
        assert r1c.sha256_file(path) == summary[field]


def test_no_target_outcome_model_or_broker_activity():
    summary = read(r1c.SUMMARY_PATH)
    for field in ("TARGET_VALUE_READ_COUNT", "OUTCOME_READ_COUNT", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "BROKER_ACTION_COUNT"):
        assert summary[field] == 0
    assert summary["outcome_or_target_paths_read"] == []
    tree = ast.parse(Path(r1c.__file__).read_text(encoding="utf-8"))
    forbidden = {"fit", "fit_predict", "predict", "place_order", "unlock_trade"}
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls & forbidden


def test_production_fast_daily_remain_unchanged():
    summary = read(r1c.SUMMARY_PATH)
    assert summary["A1_PRODUCTION_CHANGED"] is False
    assert summary["A2_PRODUCTION_ADOPTED"] is False
    assert summary["FAST_CHANGED"] is False
    assert summary["DAILY_CHAIN_CHANGED"] is False


def test_final_status_and_reproducibility_after_second_run():
    summary = read(r1c.SUMMARY_PATH)
    if summary["REPRODUCIBILITY_STATUS"] == "PASS":
        assert summary["ABCDE_A2_R1C_STATUS"] == "PASS"
        assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
        assert summary["NEXT_AUTHORIZED_STEP"] == "RERUN_ABCDE_A2_R1_UNDER_R1C_FROZEN_EXECUTION_CONTRACT"
