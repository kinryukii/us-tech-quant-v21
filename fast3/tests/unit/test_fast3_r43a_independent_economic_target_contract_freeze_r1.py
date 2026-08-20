from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r43a_independent_economic_target_contract_freeze_r1.py"
SPEC = importlib.util.spec_from_file_location("r43a", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_target_math_uses_all_five_horizons_and_strict_k3():
    frame = pd.DataFrame({
        "candidate_id": ["a", "b"],
        "decision_timestamp_utc": pd.to_datetime(["2020-01-01", "2020-01-02"], utc=True),
        "entry_timestamp": pd.to_datetime(["2020-01-01 00:02", "2020-01-02 00:02"], utc=True),
        "head": ["UP", "DOWN"], "underlying_symbol": ["QQQ", "SOXX"],
        "action_instrument": ["TQQQ", "SOXS"], "path_complete": [True, True],
        "return_5m_net20": [.01, 0], "return_10m_net20": [.02, .01],
        "return_15m_net20": [-.01, .01], "return_30m_net20": [.03, 0],
        "return_60m_net20": [-.02, -.01],
    })
    numeric = frame.loc[:, R.RETURN_COLUMNS]
    primary = numeric.mean(axis=1)
    secondary = numeric.gt(0).sum(axis=1).ge(3).astype(int)
    assert np.isclose(primary.iloc[0], .006)
    assert secondary.tolist() == [1, 0]
    assert R.PRIMARY_FORMULA.count("NET20_") == 5
    assert ">=3" in R.SECONDARY_FORMULA


def test_contract_freezes_independence_equal_horizons_and_research_sequence():
    _, r28 = R.verify_line_a_isolation()
    lineage = R.verify_payoff_lineage()
    contract = R.target_contract("fixed", r28, lineage)
    assert contract["PRIMARY_TARGET_NAME"] == "AVERAGE_FIXED_HORIZON_NET20"
    assert contract["HORIZONS"] == [5, 10, 15, 30, 60]
    assert set(contract["HORIZON_WEIGHTS"].values()) == {.2}
    assert contract["PRIMARY_TARGET_DEPENDS_ON_TARGET_FIRST"] is False
    assert contract["PRIMARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT"] is False
    assert contract["PRIMARY_TARGET_DEPENDS_ON_R28_SCORE"] is False
    assert contract["TARGET_PAYOFF_MECHANICAL_COUPLING"] is False
    assert contract["R28_PROSPECTIVE_LINE_ISOLATION"] is True
    assert contract["NEXT_GENERATION_RESEARCH_SEQUENCE"][0] == "R43B_CURRENT_14_FEATURE_BASELINE"
    assert contract["MAX_NEW_FEATURES_PER_FAMILY"] == 8
    assert contract["MAX_MODEL_FAMILY_COUNT"] == 1


def test_actual_target_cohort_is_complete_and_distribution_is_not_constant():
    frame, metadata = R.load_target_frame()
    assert metadata["PRIMARY_TARGET_VALID_COUNT"] == 1197
    assert metadata["PRIMARY_TARGET_INVALID_COUNT"] == 0
    frame = R.attach_folds(frame)
    distribution, by_fold, tails, audit = R.audit_distribution(frame)
    assert set(distribution.direction) == {"ALL", "UP", "DOWN"}
    assert len(by_fold) >= 2 and len(tails) == 3
    assert audit["TARGET_DISTRIBUTION_SANITY_PASS"] is True
    assert audit["TARGET_WINSORIZATION_COUNT"] == 0


def test_source_has_no_fit_predict_feature_or_strategy_execution():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", ".predict_proba(", "GridSearchCV", "RandomizedSearchCV"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source
    assert '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"MAX_NEW_FEATURE_COUNT": 0' in source
    assert '"STRATEGY_SIMULATION_COUNT": 0' in source
