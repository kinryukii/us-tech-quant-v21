from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r41_independent_economic_score_alignment_r1.py"
SPEC = importlib.util.spec_from_file_location("r41", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def test_preregistration_freezes_horizons_quintiles_and_zero_model_budget():
    contract = R.preregistration("fixed")
    assert R.HORIZONS == (5, 10, 15, 30, 60) and R.QUINTILES == ("Q1", "Q2", "Q3", "Q4", "Q5")
    assert not contract["MODEL_FIT_ALLOWED"] and not contract["MODEL_PREDICT_ALLOWED"]
    assert not contract["HORIZON_SELECTION_ALLOWED"] and not contract["THRESHOLD_SEARCH_ALLOWED"]


def test_authoritative_hashes_are_exact():
    paths = {"PHASE2_DECISION": R.PHASE2_DECISION, "PHASE2_LINEAGE": R.PHASE2_LINEAGE,
             "R36_PREREG": R.R36_PREREG, "R36_SUMMARY": R.R36_SUMMARY, "R36_LEDGER": R.R36_LEDGER,
             "R36_SOURCE": R.R36_SOURCE, "R40_SUMMARY": R.R40_SUMMARY,
             "UP_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_UP_IMMUTABLE_VALIDATION_LEDGER.parquet",
             "DOWN_LEDGER": R.SCORE_ROOT / "R28_3_CROSS_ASSET_FLOW_DOWN_IMMUTABLE_VALIDATION_LEDGER.parquet"}
    assert {name: R.sha256(path) for name, path in paths.items()} == R.EXPECTED


def test_stable_direction_quintiles_are_equal_count_and_outcome_blind():
    n = 20
    frame = pd.DataFrame({"direction": ["UP"] * 10 + ["DOWN"] * 10, "score": [.5] * n,
                          "decision_timestamp_utc": pd.date_range("2020-01-01", periods=n, tz="UTC"),
                          "candidate_id": [str(i) for i in range(n)], "future_outcome": np.arange(n)[::-1]})
    first = R.stable_quintiles(frame); frame["future_outcome"] *= -999; second = R.stable_quintiles(frame)
    assert first.equals(second)
    for _, index in frame.groupby("direction").groups.items(): assert first.loc[index].value_counts().to_dict() == {q: 2 for q in R.QUINTILES}


def test_ordering_enum_is_exact():
    assert R.ordering([1, 2, 3, 4, 5]) == "MONOTONIC_POSITIVE"
    assert R.ordering([1, 2, 3, 2, 5]) == "MOSTLY_POSITIVE"
    assert R.ordering([5, 4, 3, 2, 1]) == "MONOTONIC_NEGATIVE"
    assert R.ordering([1, 3, 2, 4, 2]) == "NON_MONOTONIC"


def test_actual_join_is_exact_and_all_five_payoffs_independent():
    frame, _ = R.verify_and_join()
    assert len(frame) == 1197 and not frame.candidate_id.duplicated().any()
    assert set(frame.direction) == {"UP", "DOWN"} and set(frame.score_quintile) == set(R.QUINTILES)
    assert frame[list(R.RETURN_COLUMNS.values())].notna().all().all()


def synthetic_tables(strong_head=None, candidate=False):
    corr, cont, folds = [], [], []
    for head in R.HEADS:
        good = head == strong_head
        for minute in R.HORIZONS:
            corr.append({"direction": head, "horizon_minutes": minute, "spearman": .1 if good else -.1})
            cont.append({"direction": head, "horizon_minutes": minute,
                         "q5_minus_q1_mean_net20": .01 if good else -.01,
                         "q5_mean_net20": .01 if candidate and good else -.01,
                         "q5_profit_factor_net20": 1.2 if candidate and good else .8,
                         "mean_net20_ordering": "MOSTLY_POSITIVE" if good else "NON_MONOTONIC"})
        for fold in ("F1", "F2", "F3"):
            for minute in R.HORIZONS:
                folds.append({"direction": head, "validation_slice": fold, "horizon_minutes": minute,
                              "score_net20_spearman": .1 if good else -.1,
                              "q5_minus_q1_mean_net20": .01 if good else -.01})
    return pd.DataFrame(corr), pd.DataFrame(cont), pd.DataFrame(folds)


def test_classification_strong_and_candidate_gates_are_deterministic():
    assert R.classify(*synthetic_tables("UP", True))[0] == "D_INDEPENDENT_ECONOMIC_CANDIDATE_PRESENT"
    assert R.classify(*synthetic_tables("UP", False))[0] == "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED"
    assert R.classify(*synthetic_tables())[0] == "C_NO_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT"


def test_empty_global_quintile_fold_contrast_is_not_rebucketed_or_positive_support():
    correlations, contrasts, folds = synthetic_tables("UP", False)
    folds.loc[(folds.direction.eq("UP")) & (folds.validation_slice.eq("F1")), "q5_minus_q1_mean_net20"] = np.nan
    classification, flags = R.classify(correlations, contrasts, folds)
    assert classification == "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED"
    assert flags["UP_SUPPORTING_FOLD_COUNT"] == 2
    assert R.preregistration("fixed")["EMPTY_FOLD_Q1_Q5_HANDLING"].startswith("record fold")


def test_no_fit_predict_threshold_horizon_selection_or_final():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (".fit(", ".predict(", "GridSearchCV", "RandomizedSearchCV", "FINAL_HOLDOUT"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"HORIZON_SELECTION_COUNT": 0' in source and '"FINAL_CONFIRMATION_DATA_USED": False' in source
    assert R.RESULTS == Path(r"D:\us-tech-quant-results")


def test_allowed_classification_enum_only():
    assert len(R.CLASSIFICATIONS) == 5 and "E_INVALID_INDEPENDENT_ECONOMIC_ALIGNMENT_IDENTITY" in R.CLASSIFICATIONS
