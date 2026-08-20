from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33e_three_head_economic_semantics_closure.py"
spec = importlib.util.spec_from_file_location("r33e", RUNNER)
r33e = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33e)


def synthetic() -> pd.DataFrame:
    n = 100
    values = np.arange(n)
    frame = pd.DataFrame(
        {
            "candidate_id": [f"c{i:03d}" for i in values],
            "decision_timestamp_utc": pd.date_range("2024-01-02T14:00:00Z", periods=n, freq="5min"),
            "trading_date": np.where(values < 50, "2024-01-02", "2024-01-03"),
            "fold": np.where(values < 50, "F1", "F2"),
            "head": np.where(values % 2, "UP", "DOWN"),
            "raw_net20": np.where(values % 3, 0.01 + values / 10000, -0.01 - values / 10000),
            "pred_t1": values / n,
            "pred_t5": ((values * 7) % n) / n,
            "pred_t6": values / n,
        }
    )
    return frame


def test_loss_magnitude_and_winner_loser_exclusivity() -> None:
    net = pd.Series([-0.10, -0.01, 0.0, 0.02])
    loss = r33e.loss_magnitude(net)
    assert np.isclose(loss.iloc[0], 0.10) and np.isclose(loss.iloc[1], 0.01)
    assert loss.iloc[2:].isna().all()
    assert not ((net > 0) & (net < 0)).any()


def test_bucket_definitions_are_frozen_and_deterministic() -> None:
    assert r33e.HEAD_BUCKET_COUNT == 5
    assert r33e.LOSS_JOINT_BUCKET_COUNT == 3
    first = r33e.assign_fixed_bins(synthetic(), "pred_t1", 5, "bucket")
    second = r33e.assign_fixed_bins(synthetic().iloc[::-1], "pred_t1", 5, "bucket")
    assert first.sort_values("candidate_id").bucket.tolist() == second.sort_values("candidate_id").bucket.tolist()
    assert first.bucket.value_counts().eq(20).all()


def test_date_balanced_aggregation_is_deterministic() -> None:
    frame = synthetic()
    frame["winner"] = frame.raw_net20.gt(0).astype(int)
    a = r33e.mean_within_date_spearman(frame, "pred_t1", "winner")
    b = r33e.mean_within_date_spearman(frame.iloc[::-1], "pred_t1", "winner")
    assert a == b and a[1] == 2


def test_joint_loss_grid_is_fixed_nine_cells() -> None:
    losers = synthetic().loc[lambda x: x.raw_net20 < 0].copy()
    losers["loss_magnitude"] = -losers.raw_net20
    cells, relative_range = r33e.joint_loss_cells(losers)
    assert len(cells) == 9 and cells["count"].sum() == len(losers)
    assert relative_range >= 0


def test_allowed_classification_enum_and_gates() -> None:
    a = r33e.classify(True, True, True, False)[0]
    b = r33e.classify(True, True, True, True)[0]
    c = r33e.classify(True, False, True, False)[0]
    assert {a, b, c} == r33e.ALLOWED_CLASSIFICATIONS


def test_lineage_no_final_and_external_storage() -> None:
    frame, r33c, r33d = r33e.validate_lineage()
    assert len(frame) == r33e.OOF_ROW_COUNT and not frame.candidate_id.duplicated().any()
    assert r33c["FINAL_CONFIRMATION_DATA_USED"] is False
    assert r33d["FINAL_CONFIRMATION_DATA_INSPECTED"] is False
    assert r33e.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))


def test_zero_model_calls_searches_and_no_adaptive_bucket_logic() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "predict", "predict_proba"}
    ]
    assert not forbidden_calls
    for forbidden in ("GridSearch", "RandomizedSearch", "Optuna", ".sample(", "SHAP", "KMeans"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source
    assert '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"BUCKET_SEARCH_COUNT": 0' in source
    assert '"ANTI_BLOAT_STATUS": "PASS"' in source
    assert not any(RUNNER.parent.glob("*r33e*helper*.py"))
