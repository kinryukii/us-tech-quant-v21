from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33d_t6_conditional_gain_magnitude_validation.py"
spec = importlib.util.spec_from_file_location("r33d", RUNNER)
r33d = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33d)


def synthetic() -> pd.DataFrame:
    n = 500
    values = np.arange(n)
    return pd.DataFrame(
        {
            "candidate_id": [f"c{i:04d}" for i in values],
            "decision_timestamp_utc": pd.date_range("2024-01-02T14:00:00Z", periods=n, freq="5min"),
            "trading_date": np.where(values < 250, "2024-01-02", "2024-01-03"),
            "pred_t1": (values % 50) / 50,
            "pred_t5": ((values // 10) % 50) / 50,
            "pred_t6": values / n,
            "raw_net20": 0.001 + values / 10000,
        }
    )


def test_t6_target_is_winner_only_natural_log1p_without_zero_fill() -> None:
    net = pd.Series([-0.1, 0.0, 0.01, 0.10])
    target = r33d.derive_t6(net)
    assert target.iloc[:2].isna().all()
    assert np.isclose(target.iloc[2], np.log1p(0.01))
    assert np.isclose(target.iloc[3], np.log1p(0.10))


def test_full_validation_prediction_is_separate_from_training_eligibility() -> None:
    source = inspect.getsource(r33d.main)
    assert 'training = train & eligible & dataset["head"].eq(direction)' in source
    assert 'validation = valid & dataset["head"].eq(direction)' in source
    assert 'validation = valid & eligible' not in source
    assert 'part = dataset.loc[validation' in source


def test_incremental_fixed_t1_t5_metric_detects_monotone_t6_information() -> None:
    pooled, date_balanced, cells = r33d.incremental_t1_t5_audit(synthetic())
    assert pooled > 0 and date_balanced > 0
    assert len(cells) == 25


def test_fixed_t6_deciles_are_descriptive_and_complete() -> None:
    table, monotonicity, spread = r33d.quantile_diagnostics(synthetic())
    assert len(table) == 10 and table["count"].sum() == 500
    assert monotonicity > 0 and spread > 0


def test_preregistration_lineage_and_no_final_holdout_use() -> None:
    prereg, architecture, summary = r33d.validate_preregistration()
    assert prereg["LOSING_ROW_T6_ZERO_FILL"] is False
    assert architecture["T6_MUST_BE_VALIDATED_BEFORE_COMBINATION"] is True
    assert summary["FINAL_CONFIRMATION_DATA_USED"] is False
    assert "true_holdout" not in RUNNER.read_text(encoding="utf-8").lower()


def test_anti_bloat_paths_search_gates_and_fixed_model_calls() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fits = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fit"]
    predicts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "predict"]
    assert len(fits) == len(predicts) == 1
    assert r33d.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert r33d.SCRATCH_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    for forbidden in ("GridSearch", "RandomizedSearch", "Optuna", ".sample(", "expected_payoff_score"):
        assert forbidden not in source
    assert not any(RUNNER.parent.glob("*r33d*helper*.py"))


def test_conservative_classification_gate() -> None:
    assert r33d.classify_t6(0.1, 0.1, 3, 0.1, 0.1, 0.1)[0] == "A_T6_VALIDATED"
    assert r33d.classify_t6(0.1, -0.1, 3, 0.1, 0.1, 0.1)[0] == "B_T6_WEAK_OR_MIXED"
    assert r33d.classify_t6(0.1, 0.1, 3, 0.1, 0.1, -0.01)[0] == "C_T6_NOT_VALIDATED"
