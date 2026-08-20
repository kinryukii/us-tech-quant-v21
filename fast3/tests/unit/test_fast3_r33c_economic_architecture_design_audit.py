from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33c_economic_architecture_design_audit.py"
spec = importlib.util.spec_from_file_location("r33c", RUNNER)
r33c = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33c)


def sample() -> pd.DataFrame:
    n = 100
    values = np.arange(n)
    frame = pd.DataFrame(
        {
            "candidate_id": [f"c{i:03d}" for i in values],
            "decision_timestamp_utc": pd.date_range("2024-01-02T14:00:00Z", periods=n, freq="min"),
            "pred_t1": values.astype(float),
            "pred_t5": (values % 10).astype(float),
            "raw_net20": np.where(values % 2 == 0, 0.01 + values / 10000, -0.02 - values / 10000),
            "fold": "OOF_TEST",
            "head": np.where(values % 4 < 2, "UP", "DOWN"),
            "trading_date": "2024-01-02",
        }
    )
    return frame


def test_fixed_bins_and_grid_are_deterministic_and_complete() -> None:
    frame = sample()
    first = r33c.assign_fixed_bins(frame, "pred_t1", 10, "decile")
    second = r33c.assign_fixed_bins(frame.iloc[::-1], "pred_t1", 10, "decile")
    assert first.sort_values("candidate_id").decile.tolist() == second.sort_values("candidate_id").decile.tolist()
    grid, quintiles, relationships = r33c.fixed_grid(frame)
    assert len(grid) == 25 and grid.descriptive_only.all() and len(quintiles) == 5
    assert set(relationships) == {
        "t5_quintile_vs_gain_magnitude_spearman",
        "t5_quintile_vs_loss_magnitude_spearman",
        "t5_quintile_vs_payoff_amplitude_spearman",
    }


def test_gain_gate_uses_strict_preregistered_limits() -> None:
    assert r33c.GAIN_SPEARMAN_LIMIT == 0.20
    assert r33c.GAIN_RELATIVE_DEVIATION_LIMIT == 0.15
    assert r33c.MIN_COMPATIBLE_FOLDS == 3
    compatible = abs(0.19) < r33c.GAIN_SPEARMAN_LIMIT and 0.14 < r33c.GAIN_RELATIVE_DEVIATION_LIMIT
    boundary = abs(0.20) < r33c.GAIN_SPEARMAN_LIMIT and 0.15 < r33c.GAIN_RELATIVE_DEVIATION_LIMIT
    assert compatible and not boundary


def test_conditional_gain_audit_uses_winners_without_zero_fill() -> None:
    table, global_gain, decile_s, conditional_t5 = r33c.gain_decile_table(sample())
    assert len(table) == 10 and table["count"].sum() == 50
    assert global_gain > 0 and decile_s is not None and conditional_t5 is not None
    assert (table.mean_gain > 0).all()


def test_no_model_execution_search_or_helper_framework() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_methods = {"fit", "predict", "predict_proba"}
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_methods
    ]
    assert not calls
    for forbidden in ("GridSearch", "RandomizedSearch", "Optuna", "score = T1", "pred_t1 / pred_t5"):
        assert forbidden not in source
    assert r33c.OUTPUT_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert not any(RUNNER.parent.glob("*r33c*helper*.py"))


def test_frozen_input_hashes_and_identity_load() -> None:
    frame, r33a = r33c.validate_and_load()
    assert len(frame) == r33c.OOF_ROW_COUNT and frame.fold.nunique() == 5
    assert r33a["SPEARMAN_T1_DECILE_VS_MEAN_GAIN"] == 0.5393939393939393
    conditional_loss, correct_deciles = r33c.conditional_t5_loss_audit(frame)
    assert np.isclose(conditional_loss, 0.17858870714095537, rtol=0, atol=1e-15)
    assert correct_deciles == 10
    assert all(r33c.file_sha256(path) == digest for path, digest in r33c.EXPECTED.items())
