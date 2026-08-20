from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r42_frozen_independent_economic_selection_confirmation_r1.py"
SPEC = importlib.util.spec_from_file_location("r42", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_preregistration_is_single_iteration_down_primary_and_frozen():
    contract = R.preregistration("fixed")
    assert contract["PRIMARY_DIRECTION"] == "DOWN"
    assert contract["SECONDARY_DIRECTION"] == "UP"
    assert contract["UP_CANNOT_REPLACE_FAILED_DOWN_PRIMARY"] is True
    assert contract["HORIZONS_FIXED_MINUTES"] == [5, 10, 15, 30, 60]
    assert contract["SCORE_BUCKETS_FIXED"] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert contract["MAX_RESEARCH_ITERATION_COUNT"] == 1
    assert contract["MODEL_FIT_ALLOWED"] is False
    assert contract["R41_BOUNDARY_REFIT_ALLOWED"] is False
    assert contract["HISTORICAL_BACKFILL_ALLOWED"] is False
    assert contract["SECOND_ROUND_ANALYSIS_ALLOWED"] is False


def test_r28_frozen_model_feature_and_threshold_identity_is_exact():
    observed, _ = R.verify_r28_identity()
    assert observed["identity"]["candidate"] == "R28_3_CROSS_ASSET_FLOW"
    assert observed["identity"]["feature_count"] == 14
    assert observed["identity"]["threshold_optimization_allowed"] is False


def test_r41_did_not_save_applicable_quintile_boundaries():
    frozen, values, found, _ = R.r41_boundaries()
    assert frozen is False
    assert found == []
    assert set(values) == set(R.BOUNDARY_KEYS)
    assert set(values.values()) == {"NOT_SAVED_IN_R41_ARTIFACT"}


def test_no_legal_r28_prospective_score_ledger_exists():
    assert R.sealed_prospective_manifests() == []


def test_audit_stops_without_evaluating_hypotheses_or_reusing_r41():
    summary, metrics, buckets = R.audit()
    assert summary["FAST3_R42_CLASSIFICATION"] == "E_NO_LEGAL_CONFIRMATION_DATA"
    assert summary["CONFIRMATION_SIGNAL_COUNT"] == 0
    assert summary["R41_DATA_REUSED_FOR_CONFIRMATION"] is False
    assert summary["QUINTILE_BOUNDARIES_FROZEN"] is False
    assert summary["DOWN_PRIMARY_CONFIRMATION_EVALUATED"] is False
    assert summary["MODEL_FIT_COUNT"] == 0
    assert len(metrics) == 10 and metrics["score_vs_net20_spearman"].isna().all()
    assert len(buckets) == 50 and buckets["mean_net20"].isna().all()


def test_source_has_no_training_prediction_or_selection_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", ".predict_proba(", "GridSearchCV", "RandomizedSearchCV"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source
    assert '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False' in source
