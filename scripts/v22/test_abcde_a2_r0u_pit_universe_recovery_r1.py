from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import abcde_a2_r0u_pit_universe_recovery_r1 as r0u


def test_current_325_cannot_define_historical_membership():
    assert not r0u.source_can_define_history("TIER_C", "2026-07-07")
    assert not r0u.source_can_define_history("TIER_A", "2026-07-07")
    assert r0u.source_can_define_history("TIER_A", "2020-01-02")


def test_listing_terminal_and_feature_ready_are_distinct():
    before = r0u.eligibility_state("2020-01-01", "2020-01-02", None, 500)
    young = r0u.eligibility_state("2020-06-01", "2020-01-02", None, 20)
    ready = r0u.eligibility_state("2020-09-01", "2020-01-02", None, 120)
    inactive = r0u.eligibility_state("2022-01-03", "2020-01-02", "2022-01-03", 500)
    assert before == {"universe_eligible": False, "feature_ready": False}
    assert young == {"universe_eligible": True, "feature_ready": False}
    assert ready == {"universe_eligible": True, "feature_ready": True}
    assert inactive == {"universe_eligible": False, "feature_ready": False}


def test_pit_source_timestamp_guard():
    r0u.assert_pit_timestamp("2024-05-15", "2024-05-15")
    with pytest.raises(ValueError, match="PIT_SOURCE_TIMESTAMP_AFTER_SIGNAL"):
        r0u.assert_pit_timestamp("2024-05-15", "2024-05-16")


def test_route_priority_exact_over_reconstruction():
    assert r0u.choose_route(True, True).startswith("A_EXACT")
    assert r0u.choose_route(False, True).startswith("B_NEW")
    assert r0u.choose_route(False, False).startswith("C_INSUFFICIENT")


def test_deterministic_fingerprint():
    value = {"b": [2, 1], "a": {"x": True}}
    assert r0u.canonical_fingerprint(value) == r0u.canonical_fingerprint(value)
    assert r0u.canonical_fingerprint(value) == r0u.canonical_fingerprint({"a": {"x": True}, "b": [2, 1]})


def test_recovery_module_has_no_model_fit_predict_or_broker_calls():
    paths = [Path(r0u.__file__), Path(r0u.__file__).with_name("run_abcde_a2_r0u_pit_universe_recovery_r1.py")]
    forbidden_attributes = {"fit", "fit_predict", "predict", "place_order", "unlock_trade"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not (called & forbidden_attributes)


def test_actual_summary_schema_fail_closed_and_zero_model_activity():
    path = r0u.RESULTS_ROOT / "abcde_a2_r0u_summary.json"
    assert path.is_file()
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert set(r0u.SUMMARY_FIELDS).issubset(summary)
    assert summary["ABCDE_A2_R0U_CLASSIFICATION"].startswith("C_INSUFFICIENT")
    assert summary["MODEL_FIT_COUNT"] == 0
    assert summary["MODEL_PREDICT_CALL_COUNT"] == 0
    assert summary["TRAINING_2026_ROW_COUNT"] == 0
    assert summary["BROKER_ACTION_COUNT"] == 0
    assert summary["CURRENT_325_USED_AS_HISTORICAL_SOURCE"] is False
    assert summary["NEW_RESEARCH_PIT_UNIVERSE_CREATED"] is False
    assert summary["outcome_or_target_paths_read"] == []


def test_a1_daily_fast_and_preregistration_unchanged():
    summary = json.loads((r0u.RESULTS_ROOT / "abcde_a2_r0u_summary.json").read_text(encoding="utf-8"))
    for field in ("DAILY_CHAIN_CHANGED", "A1_CHANGED", "B_CHANGED", "C_CHANGED", "D_CHANGED", "E_CHANGED", "FAST_CHANGED"):
        assert summary[field] is False
    assert summary["A1_CONTROL_IDENTITY_STATUS"] == "PASS"
    assert summary["A2_R1_PREREGISTRATION_CHANGED"] is False


def test_security_master_failure_is_specific_and_manager_versions_not_fabricated():
    summary = json.loads((r0u.RESULTS_ROOT / "abcde_a2_r0u_summary.json").read_text(encoding="utf-8"))
    audit = summary["security_master_capability_audit"]
    assert audit["historical_master_valid"] is False
    assert audit["archived_rows_retain_exchange_type_and_listing"] is False
    assert audit["terminal_effective_date_column_present"] is False
    assert summary["MANAGER_SET_VERSIONING_STATUS"].startswith("NOT_RECOVERED")
    assert summary["LEOPOLD_EARLIEST_ELIGIBLE_DATE"] is None
    assert summary["EXACT_NINE_MANAGER_GROUP_ARTIFACT_STATUS"] == "NOT_FOUND"
    assert summary["CURRENT_325_REPRODUCIBLE_FROM_HOLDINGS_RULE"] is False
    assert "DELISTED_INACTIVE" in summary["FAILURE_REASON"]


def test_identical_rerun_fingerprint_recorded():
    summary = json.loads((r0u.RESULTS_ROOT / "abcde_a2_r0u_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((r0u.RESULTS_ROOT / "a2_r0u_manifest.json").read_text(encoding="utf-8"))
    assert summary["DETERMINISTIC_CONTRACT_FINGERPRINT"] == manifest["contract_fingerprint"]
