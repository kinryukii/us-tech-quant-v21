from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33h_existing_head_economic_role_reconciliation.py"
spec = importlib.util.spec_from_file_location("r33h", RUNNER)
r33h = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33h)


@functools.lru_cache(maxsize=1)
def frozen_lineage():
    return r33h.validate_and_load_lineage()


def synthetic() -> pd.DataFrame:
    n = 100
    values = np.arange(n, dtype=float)
    return pd.DataFrame({
        "candidate_id": [f"c{i:03d}" for i in range(n)],
        "decision_timestamp_utc": pd.date_range("2024-01-02T14:00:00Z", periods=n, freq="5min"),
        "trading_date": np.where(values < 50, "2024-01-02", "2024-01-03"),
        "fold": np.array([f"OOF_202{1 + (i % 5)}" for i in range(n)]),
        "head": np.where(values % 2 == 0, "UP", "DOWN"),
        "raw_net20": np.where(values >= 50, 0.01, -0.01),
        "winner": (values >= 50).astype(int),
        "pred_t1": values / n,
        "pred_t5": (values + (values % 3)) / n,
        "pred_t6": values[::-1] / n,
    })


def test_zero_fit_predict_new_head_feature_target_contract() -> None:
    contract = r33h.preregistration("2026-08-10T00:00:00+00:00")
    for key in (
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "T1_REFIT_COUNT", "T5_REFIT_COUNT", "T6_REFIT_COUNT",
        "T7_REFIT_COUNT", "T1_NEW_PREDICT_COUNT", "T5_NEW_PREDICT_COUNT",
        "T6_NEW_PREDICT_COUNT", "T7_NEW_PREDICT_COUNT",
    ):
        assert contract[key] == 0
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    model_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "predict", "predict_proba"}
    ]
    assert not model_calls


def test_exact_three_candidates_and_p1_p2_p3_definitions() -> None:
    frame = synthetic()
    scored = r33h.add_probability_candidates(frame)
    expected_t1_rank = frame.pred_t1.rank(method="average", pct=True)
    expected_t5_rank = frame.pred_t5.rank(method="average", pct=True)
    assert r33h.PROBABILITY_CANDIDATES == ("P1_T1", "P2_T5", "P3_EQUAL_RANK_T1_T5")
    assert np.array_equal(scored.P1_T1, frame.pred_t1)
    assert np.array_equal(scored.P2_T5, frame.pred_t5)
    assert np.allclose(scored.P3_EQUAL_RANK_T1_T5, 0.5 * expected_t1_rank + 0.5 * expected_t5_rank)
    assert "T6" not in " ".join(r33h.PROBABILITY_CANDIDATES)


def test_fixed_five_quantiles_and_probability_metrics() -> None:
    scored = r33h.add_probability_candidates(synthetic())
    metrics, quantiles, _ = r33h.probability_ordering_metrics(scored, "P1_T1", "P1_T1")
    assert r33h.QUANTILE_COUNT == 5
    assert len(quantiles) == 5 and quantiles["count"].sum() == len(scored)
    assert metrics["pooled_spearman"] > 0
    assert metrics["quantile_monotonicity"] >= 0.8


def test_probability_gates_and_simplicity_selection_are_frozen() -> None:
    contract = r33h.preregistration("2026-08-10T00:00:00+00:00")
    gates = contract["PROBABILITY_ORDERING_GATES"]
    assert gates["A_POOLED_SPEARMAN_MIN"] == 0.05
    assert gates["B_DATE_BALANCED_SPEARMAN_MIN"] == 0.15
    assert gates["C_ALL_FOLDS_STRICTLY_POSITIVE"] is True
    assert gates["D_UP_AND_DOWN_STRICTLY_POSITIVE"] is True
    assert gates["E_QUANTILE_WINNER_RATE_SPEARMAN_MIN"] == 0.8
    results = {candidate: {"gate_status": "PASS", "pooled_spearman": 0.1} for candidate in r33h.PROBABILITY_CANDIDATES}
    assert r33h.select_first_pass(results) == "P1_T1"
    results["P1_T1"]["gate_status"] = "FAIL"
    assert r33h.select_first_pass(results) == "P2_T5"
    results["P2_T5"]["gate_status"] = "FAIL"
    assert r33h.select_first_pass(results) == "P3_EQUAL_RANK_T1_T5"


def test_t5_lineage_t5_t7_identity_and_t6_metrics_reconcile() -> None:
    frame, r33d, r33e = frozen_lineage()
    assert r33e["T5_ORIGINAL_MODEL_TARGET_LINEAGE"] == "R33B_CONDITIONAL_LOSS_SEVERITY"
    assert len(frame) == r33h.OOF_ROW_COUNT
    assert np.array_equal(frame.pred_t5.to_numpy(), frame.pred_t7.to_numpy())
    assert np.max(np.abs(frame.pred_t5 - frame.pred_t7)) == 0.0
    evidence = r33h.reconcile_t6_gain_role(frame, r33d)
    assert evidence["reference_reconciled"] is True


def test_allowed_role_and_scientific_classification_enums() -> None:
    passed = {candidate: {"gate_status": "PASS", "pooled_spearman": 0.1} for candidate in r33h.PROBABILITY_CANDIDATES}
    assert r33h.classify(passed)[0] == "A_EXISTING_HEADS_CONTAIN_STABLE_WINNER_PROBABILITY_ORDERING"
    failed_positive = {candidate: {"gate_status": "FAIL", "pooled_spearman": 0.01} for candidate in r33h.PROBABILITY_CANDIDATES}
    assert r33h.classify(failed_positive)[0] == "B_WINNER_PROBABILITY_ORDERING_PRESENT_BUT_NOT_STABLE_ENOUGH"
    failed_zero = {candidate: {"gate_status": "FAIL", "pooled_spearman": 0.0} for candidate in r33h.PROBABILITY_CANDIDATES}
    assert r33h.classify(failed_zero)[0] == "C_EXISTING_HEADS_DO_NOT_IDENTIFY_WINNER_PROBABILITY_ORDERING"
    assert r33h.classify(failed_positive)[2] == "UNRESOLVED"
    assert r33h.classify(failed_zero)[2] is False
    assert len(r33h.ALLOWED_CLASSIFICATIONS) == 3
    assert len(r33h.ALLOWED_T1_ROLES) == 3 and len(r33h.ALLOWED_T5_ROLES) == 3 and len(r33h.ALLOWED_T6_ROLES) == 2


def test_no_search_calibration_ev_trading_final_or_head_expansion() -> None:
    contract = r33h.preregistration("2026-08-10T00:00:00+00:00")
    for key in (
        "WIN_PROBABILITY_WEIGHT_SEARCH_COUNT", "ALTERNATIVE_PROBABILITY_SCORE_SEARCH_COUNT",
        "MODEL_FAMILY_SEARCH_COUNT", "HYPERPARAMETER_SEARCH_COUNT", "FEATURE_SEARCH_COUNT",
        "INTERACTION_SEARCH_COUNT", "PROBABILITY_CALIBRATION_FIT_COUNT",
        "PROBABILITY_CALIBRATION_SEARCH_COUNT", "EV_COMBINATION_SEARCH_COUNT",
        "EV_SCORE_CONSTRUCTION_COUNT", "THRESHOLD_SEARCH_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT",
    ):
        assert contract[key] == 0
    assert contract["NEW_HEAD_PROHIBITED"] is True
    assert contract["PROBABILITY_CALIBRATION_PROHIBITED"] is True
    assert contract["EV_PROHIBITED"] is True
    assert contract["FINAL_PROHIBITED"] is True
    assert contract["HEAD_EXPANSION_LIMIT_AFTER_R33G"] is True
    assert contract["FURTHER_HEAD_EXPANSION_ALLOWED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert contract["FINAL_HOLDOUT_INSPECTED"] is False


def test_preregistration_precedes_metrics_and_external_storage() -> None:
    source = inspect.getsource(r33h.main)
    assert source.index("write_json(prereg_path, prereg)") < source.index("add_probability_candidates(frame)")
    assert source.index("write_json(prereg_path, prereg)") < source.index("probability_ordering_metrics")
    assert r33h.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert not any(RUNNER.parent.glob("*r33h*helper*.py"))
