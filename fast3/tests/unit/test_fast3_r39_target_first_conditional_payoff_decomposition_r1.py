from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r39_target_first_conditional_payoff_decomposition_r1.py"
SPEC = importlib.util.spec_from_file_location("r39", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def test_frozen_checkpoints_variables_and_model_budget():
    assert R.CHECKPOINTS == (("T0", 0), ("T1", 1), ("T3", 3), ("T5", 5), ("T10", 10))
    assert len(R.DYNAMIC_VARIABLES) == 7
    contract = R.preregistration("fixed")
    assert not contract["MODEL_FIT_ALLOWED"] and not contract["MODEL_PREDICT_ALLOWED"]
    assert not contract["PARAMETER_SEARCH_ALLOWED"] and not contract["THRESHOLD_SEARCH_ALLOWED"]


def test_checkpoint_coverage_censors_every_post_touch_checkpoint_when_exit_is_touch():
    touch = pd.Timestamp("2024-01-02T15:00:00Z")
    frame = pd.DataFrame({"touch_timestamp": [touch, touch], "first_touch_exit_timestamp": [touch, touch]})
    result = R.checkpoint_coverage(frame).set_index("checkpoint")
    assert result.loc["T0", "ELIGIBLE_COUNT"] == 2
    assert (result.loc[["T1", "T3", "T5", "T10"], "ELIGIBLE_COUNT"] == 0).all()
    assert (result.loc[["T1", "T3", "T5", "T10"], "CENSORED_COUNT"] == 2).all()


def test_authoritative_input_hashes_are_exact():
    paths = {
        "PHASE2_DECISION": R.PHASE2_DECISION, "PHASE2_LINEAGE": R.PHASE2_LINEAGE,
        "R28_LEDGER": R.R28_LEDGER, "R36_LEDGER": R.R36_LEDGER, "R37_SUMMARY": R.R37_SUMMARY,
        "UP_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_UP_IMMUTABLE_VALIDATION_LEDGER.parquet",
        "DOWN_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_DOWN_IMMUTABLE_VALIDATION_LEDGER.parquet",
    }
    assert {name: R.sha256(path) for name, path in paths.items()} == R.EXPECTED


def test_target1_identity_observable_but_has_no_post_target_window():
    target1, hashes = R.verify_and_load()
    assert len(target1) == 613 and not target1.candidate_id.duplicated().any()
    assert target1.touch_timestamp.notna().all()
    assert target1.touch_timestamp.eq(target1.first_touch_exit_timestamp).all()
    summary, coverage = R.audit(target1, hashes)
    assert summary["TARGET_FIRST_REALTIME_OBSERVABLE"]
    assert summary["TARGET1_FINAL_WIN_COUNT"] == 546 and summary["TARGET1_FINAL_LOSS_COUNT"] == 67
    assert summary["TARGET1_PATH_COMPLETE_COUNT"] == 0 and summary["TARGET1_PATH_COMPLETE_RATIO"] == 0
    assert summary["FAST3_R39_CLASSIFICATION"] == "E_INVALID_PATH_OR_IDENTITY"
    assert coverage.loc[coverage.checkpoint.ne("T0"), "ELIGIBLE_COUNT"].sum() == 0


def test_fail_close_does_not_invent_post_target_metrics():
    target1, hashes = R.verify_and_load()
    summary, _ = R.audit(target1, hashes)
    for key in ("T1_MAX_ORIENTED_UNIVARIATE_AUC", "T3_DRAWDOWN_AUC",
                "FINAL_LOSER_TIME_TO_BREAKEVEN_LOSS_MEDIAN", "UP_POST_TARGET_MAX_AUC"):
        assert str(summary[key]).startswith("NOT_AVAILABLE")
    assert not summary["STRONG_POST_TARGET_STRUCTURE"]
    assert summary["MODEL_FIT_COUNT"] == summary["MODEL_PREDICT_CALL_COUNT"] == 0


def test_allowed_classification_and_final_integrity_guards():
    assert len(R.CLASSIFICATIONS) == 5 and "E_INVALID_PATH_OR_IDENTITY" in R.CLASSIFICATIONS
    target1, hashes = R.verify_and_load()
    summary, _ = R.audit(target1, hashes)
    assert summary["FAST3_R39_CLASSIFICATION"] in R.CLASSIFICATIONS
    assert summary["R28_PREDICTIVE_IDENTITY_UNCHANGED"]
    assert summary["PIT_STATUS"] == summary["CORPORATE_ACTION_STATUS"] == summary["OOF_INTEGRITY_STATUS"] == "PASS"
    assert summary["FINAL_CONFIRMATION_DATA_USED"] is False


def test_source_has_no_fit_predict_search_or_strategy_simulation():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", "GridSearchCV", "RandomizedSearchCV", "XGB", "LightGBM", "AutoML"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"THRESHOLD_SEARCH_COUNT": 0' in source and '"STOP_SEARCH_COUNT": 0' in source
    assert R.RESULTS == Path(r"D:\us-tech-quant-results")
