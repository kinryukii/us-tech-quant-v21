from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33j_relative_economic_score_identifiability.py"
spec = importlib.util.spec_from_file_location("r33j", RUNNER)
r33j = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33j)


@functools.lru_cache(maxsize=1)
def lineage():
    r33i = r33j.load_r33i_module()
    return (r33i, *r33j.validate_lineage(r33i))


def test_sources_roles_and_folds_are_exactly_frozen() -> None:
    assert (r33j.P_SOURCE, r33j.L_SOURCE, r33j.G_RANK_SOURCE) == ("T1", "T5", "T6")
    assert r33j.EVALUATION_FOLDS == ("OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025")
    assert r33j.EXCLUDED_FOLD == "OOF_2021"
    contract = r33j.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["EVALUATION_FOLDS"] == list(r33j.EVALUATION_FOLDS)
    assert contract["OOF_2021_EXCLUSION_REASON"] == "NO_PRE_FOLD_CALIBRATION_HISTORY"


def test_grid_quantiles_and_gates_are_frozen_without_search() -> None:
    assert r33j.PL_GRID_SIZE == (3, 3)
    assert r33j.T6_WITHIN_CELL_QUANTILE_COUNT == 3
    assert r33j.GATE_B_MIN == 0.10 and r33j.GATE_E_MIN == 0.8
    contract = r33j.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["CONDITIONING_GRID_SIZE"] == "3x3"
    assert contract["PL_CONDITIONING_GRID_COUNT"] == 1
    assert contract["PL_CONDITIONING_GRID_SEARCH_COUNT"] == 0
    assert contract["T6_WITHIN_CELL_QUANTILE_SEARCH_COUNT"] == 0
    assert contract["GATES"]["C_ALL_4_FOLDS_STRICTLY_POSITIVE"] is True
    assert contract["GATES"]["D_UP_AND_DOWN_STRICTLY_POSITIVE"] is True


def test_training_mapping_uses_training_only_outcomes_and_boundaries() -> None:
    training = pd.DataFrame({"score": np.arange(30, dtype=float), "target": np.linspace(0, 1, 30)})
    evaluation_a = pd.DataFrame({"score": [-10.0, 15.0, 100.0], "target": [999.0] * 3})
    evaluation_b = evaluation_a.copy()
    evaluation_b["target"] = -999.0
    pred_a, info_a = r33j.training_mapping(training, "score", "target", [evaluation_a])
    pred_b, info_b = r33j.training_mapping(training, "score", "target", [evaluation_b])
    assert np.array_equal(pred_a[0], pred_b[0])
    assert info_a == info_b
    source = inspect.getsource(r33j.fold_safe_calibrated_population)
    assert "decision_timestamp_utc.lt(cutoff)" in source
    assert "historical.decision_timestamp_utc.max() < evaluation.decision_timestamp_utc.min()" in source


def test_no_model_score_weight_threshold_ev_trading_or_final_path() -> None:
    contract = r33j.preregistration("2026-08-10T00:00:00+00:00")
    zero_keys = (
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "CALIBRATION_METHOD_SEARCH_COUNT",
        "CALIBRATION_BUCKET_SEARCH_COUNT", "CALIBRATION_REBUILD_VARIANT_COUNT",
        "GAIN_CALIBRATION_RETRY_COUNT", "RELATIVE_SCORE_CANDIDATE_COUNT",
        "RELATIVE_SCORE_FORMULA_SEARCH_COUNT", "RELATIVE_SCORE_WEIGHT_SEARCH_COUNT",
        "T6_ECONOMIC_LEVEL_MAPPING_COUNT", "WEIGHT_SEARCH_COUNT", "WEIGHT_ASSIGNMENT_COUNT",
        "ABSOLUTE_EV_CONSTRUCTION_COUNT", "EV_SCORE_CONSTRUCTION_COUNT",
        "EV_COMBINATION_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT", "SIGNAL_SELECTION_COUNT",
        "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT",
    )
    assert all(contract[key] == 0 for key in zero_keys)
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert contract["FINAL_HOLDOUT_INSPECTED"] is False
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    forbidden_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "predict", "predict_proba"}
    ]
    assert not forbidden_calls


def test_r33g_conditional_statistic_is_reused_and_date_balanced_fixed() -> None:
    contract = r33j.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["CONDITIONAL_STATISTIC_IMPLEMENTATION_REUSED"] is True
    assert contract["CONDITIONAL_STATISTIC"] == r33j.CONDITIONAL_STATISTIC
    source = inspect.getsource(r33j.conditional_rank_statistic)
    assert 'rank(method="average", pct=True)' in source
    assert 'groupby("trading_date"' in source


def test_same_day_diagnostic_is_deterministic_and_not_selection() -> None:
    frame = pd.DataFrame({
        "candidate_id": ["b", "a", "c", "d"], "trading_date": ["2026-01-01"] * 4,
        "outer_fold": ["OOF_2022"] * 4, "p_cell": [1] * 4, "l_cell": [1] * 4,
        "pred_t6": [0.2, 0.1, 0.4, 0.3], "raw_net20": [2.0, -1.0, 4.0, 1.0],
    })
    first = r33j.same_day_diagnostic(frame)
    second = r33j.same_day_diagnostic(frame.sample(frac=1, random_state=7))
    assert first == second
    assert first["comparison_count"] == 1
    assert first["high_minus_low_mean_payoff"] == 5.0


def test_classification_enum_and_no_head_expansion() -> None:
    all_pass = {key: True for key in "ABCDEF"}
    assert r33j.classify(all_pass)[0] == "A_RELATIVE_ECONOMIC_ORDERING_IDENTIFIABLE"
    unstable = dict(all_pass, C=False)
    assert r33j.classify(unstable)[0] == "B_CONDITIONAL_UPSIDE_INFORMATION_PRESENT_BUT_RELATIVE_ORDERING_NOT_STABLE"
    absent = {key: False for key in "ABCDEF"}
    assert r33j.classify(absent)[0] == "C_RELATIVE_ECONOMIC_ORDERING_NOT_IDENTIFIED"
    assert len(r33j.ALLOWED_CLASSIFICATIONS) == 3
    contract = r33j.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["HEAD_EXPANSION_LIMIT_AFTER_R33G"] is True
    assert contract["FURTHER_HEAD_EXPANSION_ALLOWED"] is False


def test_lineage_payoff_and_preregistration_before_metrics_external_storage() -> None:
    _, frame, summary, audits, _ = lineage()
    assert len(frame) == 984_049 and not frame.candidate_id.duplicated().any()
    assert frame.raw_net20.ne(0).all()
    assert summary["P_CALIBRATION_STATUS"] == "CALIBRATED"
    assert summary["L_CALIBRATION_STATUS"] == "CALIBRATED"
    assert [row["outer_fold"] for row in audits] == list(r33j.EVALUATION_FOLDS)
    source = inspect.getsource(r33j.main)
    prereg_index = source.index("write_json(prereg_path, prereg)")
    assert prereg_index < source.index("reconcile_r33i_calibration")
    assert prereg_index < source.index("conditional_rank_statistic(study)")
    assert r33j.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert not any(RUNNER.parent.glob("*r33j*helper*.py"))
