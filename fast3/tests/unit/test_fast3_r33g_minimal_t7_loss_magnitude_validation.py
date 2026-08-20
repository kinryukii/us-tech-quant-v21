from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33g_minimal_t7_loss_magnitude_validation.py"
spec = importlib.util.spec_from_file_location("r33g", RUNNER)
r33g = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33g)


def synthetic() -> pd.DataFrame:
    rows = []
    i = 0
    for t1 in (0.1, 0.9):
        for t5 in (0.1, 0.9):
            for t6 in (0.1, 0.9):
                for repeat in range(12):
                    score = i / 1000 + repeat / 10000
                    rows.append({
                        "candidate_id": f"c{i:04d}_{repeat:02d}",
                        "decision_timestamp_utc": pd.Timestamp("2024-01-02T14:00:00Z") + pd.Timedelta(minutes=5 * i),
                        "trading_date": f"2024-01-{2 + repeat % 3:02d}",
                        "pred_t1": t1, "pred_t5": t5, "pred_t6": t6, "pred_t7": score,
                        "raw_net20": -(0.001 + score), "loss_magnitude": 0.001 + score,
                    })
                    i += 1
    return pd.DataFrame(rows)


def test_t7_exactly_uses_t6_feature_manifest_and_model_contract() -> None:
    _, contract, _, _ = r33g.recover_t6_contract()
    prereg = r33g.preregistration("2026-08-10T00:00:00+00:00", contract, ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"])
    assert prereg["T6_FEATURE_MANIFEST_SHA256"] == prereg["T7_FEATURE_MANIFEST_SHA256"] == r33g.T6_FEATURE_MANIFEST_SHA256
    assert prereg["FEATURE_MANIFEST_EXACT_MATCH"] is True
    assert prereg["T6_FEATURE_NAMES"] == prereg["T7_FEATURE_NAMES"]
    assert prereg["T6_MODEL_FAMILY"] == prereg["T7_MODEL_FAMILY"] == r33g.T6_MODEL_FAMILY
    assert prereg["T6_HYPERPARAMETERS"] == prereg["T7_HYPERPARAMETERS"]
    assert prereg["NEW_FEATURE_COUNT"] == prereg["REMOVED_FEATURE_COUNT"] == 0


def test_t7_target_is_strict_loser_log1p_mirror_without_zero_fill() -> None:
    net = pd.Series([-0.10, -0.01, 0.0, 0.01])
    target = r33g.derive_t7(net)
    assert np.isclose(target.iloc[0], np.log1p(0.10))
    assert np.isclose(target.iloc[1], np.log1p(0.01))
    assert target.iloc[2:].isna().all()
    assert r33g.T7_TARGET_TRANSFORM == "natural_log1p(abs(raw_net20))"
    source = inspect.getsource(r33g.main)
    assert 'training = train & losers_mask & dataset["head"].eq(direction)' in source
    assert 'validation = valid & dataset["head"].eq(direction)' in source
    assert 'validation = valid & losers_mask' not in source


def test_t7_fold_identity_and_strict_temporal_assertions_are_frozen() -> None:
    _, contract, _, _ = r33g.recover_t6_contract()
    fold_ids = [row["fold"] for row in contract["PER_FOLD_DIRECTION_COUNTS"][::2]]
    assert fold_ids == ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"]
    assert contract["SPLIT_CONTRACT_SHA256"] == r33g.T6_SPLIT_CONTRACT_SHA256
    source = inspect.getsource(r33g.main)
    assert "not train_max < valid_min" in source
    assert "(training & validation).any()" in source
    assert 'audit["overlap_count"] != 0' in source


def test_fixed_quantiles_and_2x2x2_incremental_metric() -> None:
    data = synthetic()
    table, monotonicity, spread = r33g.quantile_diagnostics(data)
    pooled, date_balanced, cells = r33g.incremental_three_head_audit(data)
    assert len(table) == 5 and table["count"].sum() == len(data)
    assert monotonicity >= 0.8 and spread > 0
    assert len(cells) == 8 and cells["count"].gt(0).all()
    assert pooled > 0 and date_balanced > 0
    assert r33g.QUANTILE_COUNT == 5 and r33g.CONDITIONAL_GRID == (2, 2, 2)


def test_gate_constants_and_allowed_classification_enum() -> None:
    assert r33g.GATE_A_MIN == r33g.GATE_B_MIN == 0.15
    assert r33g.GATE_E_MIN == 0.8
    all_pass = {key: True for key in "ABCDEFG"}
    assert r33g.classify(all_pass)[0] == "A_T7_VALIDATED"
    all_pass["F"] = False
    result_b = r33g.classify(all_pass)
    assert result_b[0] == "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED"
    assert result_b[4] is False
    all_pass["F"] = True
    all_pass["B"] = False
    result_c = r33g.classify(all_pass)
    assert result_c[0] == "C_T7_NOT_VALIDATED"
    assert result_c[4] is False
    assert r33g.ALLOWED_CLASSIFICATIONS == {"A_T7_VALIDATED", "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED", "C_T7_NOT_VALIDATED"}


def test_exact_existing_head_identity_cannot_pass_incremental_gates() -> None:
    source = inspect.getsource(r33g.main)
    assert "np.array_equal(oof.pred_t7.to_numpy(), oof.pred_t5.to_numpy())" in source
    assert '"F": conditional_s > 0 and not t7_t5_exact_match' in source
    assert '"G": conditional_date_s > 0 and not t7_t5_exact_match' in source


def test_exactly_one_model_variant_and_preregistration_precedes_fit() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fits = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"]
    predicts = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "predict"]
    main_source = inspect.getsource(r33g.main)
    assert r33g.T7_MODEL_VARIANT_COUNT == 1
    assert len(fits) == len(predicts) == 1
    assert main_source.index("write_json(prereg_path, prereg)") < main_source.index("model.fit(")
    assert main_source.index("write_json(contract_path, contract)") < main_source.index("model.fit(")


def test_no_base_head_refit_search_final_ev_trading_or_t8() -> None:
    _, contract, _, _ = r33g.recover_t6_contract()
    prereg = r33g.preregistration("2026-08-10T00:00:00+00:00", contract, ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"])
    for key in (
        "MODEL_FAMILY_SEARCH_COUNT", "HYPERPARAMETER_SEARCH_COUNT", "FEATURE_SEARCH_COUNT",
        "TARGET_SEARCH_COUNT", "TARGET_TRANSFORM_SEARCH_COUNT", "INTERACTION_SEARCH_COUNT",
        "BUCKET_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT",
        "EV_COMBINATION_SEARCH_COUNT", "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT",
        "POSITION_SIZING_SEARCH_COUNT", "T1_REFIT_COUNT", "T5_REFIT_COUNT", "T6_REFIT_COUNT",
        "T1_NEW_PREDICT_COUNT", "T5_NEW_PREDICT_COUNT", "T6_NEW_PREDICT_COUNT",
    ):
        assert prereg[key] == 0
    assert prereg["FINAL_DATA_PROHIBITED"] is True
    assert prereg["FINAL_CONFIRMATION_DATA_USED"] is False
    assert prereg["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert prereg["FINAL_HOLDOUT_INSPECTED"] is False
    assert prereg["HEAD_EXPANSION_LIMIT_AFTER_R33G"] is True
    assert prereg["T8_MODEL_CREATED"] is False


def test_external_storage_and_parent_lineage_contract() -> None:
    _, _, _, r33fr = r33g.recover_t6_contract()
    assert r33g.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert r33fr["FAST3_R33FR_CLASSIFICATION"] == "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE"
    assert r33fr["NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED"] is True
    assert r33g.EXPECTED_SHA256[r33g.R33FR_PREREGISTRATION] == "5f3463390cd2f13d5fd1a18bc793c1b0c4f0f3712d0f658d461b0236ea9ea6b3"
