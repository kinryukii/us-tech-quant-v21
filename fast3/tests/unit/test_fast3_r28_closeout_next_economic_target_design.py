from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_closeout_next_economic_target_design.py"
SPEC = importlib.util.spec_from_file_location("r28_closeout_design", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_signed_log1p_is_fixed_sign_preserving_and_rank_preserving():
    raw = pd.Series([-2.0, -.1, 0.0, .1, 2.0])
    robust = MODULE.signed_log1p(raw)
    assert np.sign(robust).tolist() == np.sign(raw).tolist()
    assert robust.rank().tolist() == raw.rank().tolist()
    assert robust.abs().max() < raw.abs().max()


def test_t1_and_t3_boundaries_are_not_optimized():
    net = pd.Series([-.001, 0.0, .0001, .004999, .005])
    assert net.gt(0).astype(int).tolist() == [0, 0, 1, 1, 1]
    assert net.ge(.005).astype(int).tolist() == [0, 0, 0, 0, 1]


def test_binary_entropy_and_feasibility():
    assert MODULE.binary_entropy(.5) == 1.0
    assert MODULE.class_feasibility_score(.96) == 5
    assert MODULE.class_feasibility_score(.60) == 2


def test_symmetric_trimmed_mean_is_diagnostic_only():
    values = pd.Series([-100.0] + [1.0] * 98 + [100.0])
    assert MODULE.symmetric_trimmed_mean(values) == 1.0


def test_stability_scoring_boundaries_are_fixed():
    assert MODULE.classification_stability_score(.08) == 5
    assert MODULE.classification_stability_score(.10) == 4
    assert MODULE.classification_stability_label(.19) == "MEDIUM"
    assert MODULE.continuous_stability_score(.25) == 5
    assert MODULE.continuous_stability_label(.51) == "LOW"


def test_distribution_coverage_and_grouping_fixture():
    frame = pd.DataFrame({
        "calendar_year": [2023, 2023, 2024], "head": ["UP", "DOWN", "UP"],
        "action_instrument": ["SOXL", "SOXS", "SOXL"], "corrected_net20": [-.01, .01, .02],
        "t1_positive_net20": [0, 1, 1], "t2_robust_net20": MODULE.signed_log1p(pd.Series([-.01, .01, .02])),
        "t3_net20_above_margin": [0, 1, 1],
    })
    result = MODULE.target_distribution_rows(frame)
    all_t1 = result.loc[result.target.eq("T1_POSITIVE_NET20") & result.dimension.eq("ALL")].iloc[0]
    assert all_t1.valid_count == 3
    assert all_t1.coverage_rate == 1.0
    assert np.isclose(all_t1.positive_rate, 2/3)


def test_redundancy_metrics_do_not_train_model():
    frame = pd.DataFrame({"t1_positive_net20": [0, 0, 1, 1], "corrected_net20": [-2., -1., 1., 2.],
                          "t3_net20_above_margin": [0, 0, 1, 1]})
    result = MODULE.target_redundancy(frame)
    assert len(result) == 3
    assert result[1]["pearson_or_point_biserial"] == 1.0


def test_contract_has_every_required_field_and_two_targets_only():
    proposal = MODULE.target_contracts()
    assert len(proposal["recommended_targets"]) == 2
    required = {"TARGET_NAME", "TARGET_TYPE", "REFERENCE_TIMESTAMP", "ENTRY_SEMANTICS", "EXIT/HORIZON_SEMANTICS",
                "PRICE_SOURCE", "CORPORATE_ACTION_NORMALIZATION", "TRANSACTION_COST", "PIT_REQUIREMENT",
                "MISSING_DATA_POLICY", "PRE_ENTRY_EVENT_POLICY", "TARGET_FORMULA"}
    assert all(required <= set(target) for target in proposal["recommended_targets"])


def test_permanent_guards_and_lessons_are_complete():
    assert len(MODULE.LESSONS) == 8
    assert all(MODULE.PERMANENT_GUARDS.values())


def test_source_has_no_training_prediction_or_repo_results():
    text = SOURCE.read_text(encoding="utf-8")
    lowered = text.lower()
    assert ".fit(" not in lowered
    assert ".predict(" not in lowered
    assert "xgboost" not in lowered
    assert 'DATA_ROOT = Path(r"D:\\us-tech-quant-data")' in text
    assert 'RESULTS_ROOT = Path(r"D:\\us-tech-quant-results")' in text
    assert 'CACHE_ROOT = Path(r"D:\\us-tech-quant-cache")' in text
