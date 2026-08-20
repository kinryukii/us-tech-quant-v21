from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r38_net20_positive_target_r1.py"
SPEC = importlib.util.spec_from_file_location("r38", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def test_exact_feature_target_and_model_budget():
    assert len(R.FEATURES) == 14 and len(set(R.FEATURES)) == 14
    assert R.HGB_PARAMS == {"learning_rate": .08, "max_iter": 100, "max_leaf_nodes": 7,
                            "min_samples_leaf": 200, "l2_regularization": 1.0, "random_state": 1729}
    assert R.HEADS == ("UP", "DOWN") and R.QUINTILES == ("Q1", "Q2", "Q3", "Q4", "Q5")


def test_preregistration_is_one_target_one_config_no_search():
    class Stub: ECONOMIC_FOLDS = tuple((str(i), "x", "y") for i in range(5))
    contract = R.preregistration("fixed", Stub)
    assert contract["TARGET_COUNT"] == contract["MODEL_FAMILY_COUNT"] == contract["MODEL_CONFIG_COUNT"] == 1
    assert contract["EXPECTED_FIT_COUNT"] == 10 and contract["EXPECTED_PREDICT_CALL_COUNT"] == 20
    assert contract["NO_PARAMETER_SEARCH"] and contract["NO_FEATURE_SEARCH"] and contract["NO_THRESHOLD_SEARCH"]


def test_lineage_hashes_are_frozen():
    assert R.sha256(R.R28_LEDGER) == R.EXPECTED["R28_LEDGER"]
    assert R.sha256(R.R28_DECISION) == R.EXPECTED["R28_DECISION"]


def test_target_is_strict_positive_and_costed_payoff_metrics():
    net = pd.Series([.01, 0, -.01]); target = (net > 0).astype(int)
    assert target.tolist() == [1, 0, 0]
    metrics = R.payoff_metrics(net)
    assert metrics["win_rate"] == 1 / 3 and metrics["profit_factor"] == 1


def test_stable_quintiles_are_exact_even_with_tied_scores():
    frame = pd.DataFrame({"head": ["UP"] * 10 + ["DOWN"] * 10, "score": [0.5] * 20,
                          "decision_timestamp_utc": pd.date_range("2020-01-01", periods=20, tz="UTC"),
                          "candidate_id": [str(i) for i in range(20)]})
    q = R.stable_quintiles(frame, "score")
    for _, index in frame.groupby("head").groups.items():
        assert q.loc[index].value_counts().to_dict() == {name: 2 for name in R.QUINTILES}


def test_top20_is_fixed_and_outcome_blind():
    frame = pd.DataFrame({"score": range(11), "decision_timestamp_utc": pd.date_range("2020-01-01", periods=11, tz="UTC"),
                          "candidate_id": [str(i) for i in range(11)], "outcome": range(11)[::-1]})
    selected = R.top20_mask(frame, "score")
    assert selected.sum() == 3 and set(frame.loc[selected, "score"]) == {8, 9, 10}


def classification_inputs(success_head=None, predictive_heads=()):
    pred, q5, comp, folds = [], [], [], []
    for head in R.HEADS:
        pred_gate = head in predictive_heads or head == success_head
        pred.append({"head": head, "oof_auroc": .6 if pred_gate else .49, "oof_pr_auc": .7 if pred_gate else .4, "base_positive_rate": .5})
        good = head == success_head
        q5.append({"head": head, "q5_mean_net20": .01 if good else -.01, "q5_profit_factor": 1.2 if good else .8, "rest_mean_net20": 0})
        comp += [{"head": head, "score_name": "R38_SCORE", "score_vs_net20_spearman": .10 if good else 0},
                 {"head": head, "score_name": "R28_SCORE", "score_vs_net20_spearman": 0}]
        for i in range(5):
            folds.append({"head": head, "fold_mean_net20_q5": .01 if good and i < 3 else -.01,
                          "fold_mean_net20_rest": 0, "fold_score_net20_spearman": .1 if good and i < 3 else -.1})
    return map(pd.DataFrame, (pred, q5, comp, folds))


def test_direction_asymmetric_classification_is_not_forced_symmetric():
    classification, flags = R.classify(*classification_inputs(success_head="UP"))
    assert classification == "D_DIRECTION_ASYMMETRIC_PARTIAL_SUCCESS" and flags["UP_SUCCESS_GATE"] and not flags["DOWN_SUCCESS_GATE"]


def test_predictable_without_economic_gate_is_b():
    classification, _ = R.classify(*classification_inputs(predictive_heads=("UP", "DOWN")))
    assert classification == "B_ECONOMIC_TARGET_PREDICTABLE_BUT_PAYOFF_RANKING_WEAK"


def test_future_mutation_cannot_change_past_feature_fold_or_score_hash():
    frame = pd.DataFrame({"candidate_id": ["a", "b"], "decision_timestamp_utc": pd.to_datetime(["2020-01-01", "2021-01-01"], utc=True),
                          "fold": ["F1", "F2"], "R38_SCORE": [.4, .6], "NET20_POSITIVE": [0, 1],
                          **{name: [0., 1.] for name in R.FEATURES}})
    assert R.future_mutation_audit(frame)


def test_no_forbidden_model_search_threshold_or_final_prospective_use():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("GridSearchCV", "RandomizedSearchCV", "XGBClassifier", "LGBMClassifier", "RandomForestClassifier", "KFold(", "FINAL_HOLDOUT"):
        assert forbidden not in source
    assert '"FEATURE_SEARCH_COUNT": 0' in source and '"PARAMETER_SEARCH_COUNT": 0' in source
    assert '"R28_REFIT_COUNT": 0' in source and '"R28_THRESHOLD_CHANGE_COUNT": 0' in source


def test_external_storage_and_allowed_classifications():
    assert R.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert len(R.CLASSIFICATIONS) == 5 and "E_INVALID_RESEARCH_INTEGRITY" in R.CLASSIFICATIONS
