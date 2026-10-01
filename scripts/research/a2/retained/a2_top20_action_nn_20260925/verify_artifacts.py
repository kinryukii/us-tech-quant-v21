"""Read-only focused checks of data boundary, fitted parameters and replay identities."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import safe_inputs
import test2026
import train

ROOT = Path(__file__).resolve().parent


def main() -> None:
    frozen = test2026.freeze()
    panel, prices, _, lineage = safe_inputs.load_inputs()
    frame, _ = train.make_panel(panel, prices)
    final = frame.loc[frame.label_end_date_exec.lt(train.CUTOFF) & frame.y_exec20.notna()]
    assert len(panel) == 49400 and len(final) == frozen["models"]["RIDGE_20260925"]["train_rows"]
    assert final.signal_date.max() < train.CUTOFF and final.label_end_date_exec.max() < train.CUTOFF
    matrix = final[list(train.FEATURES)]
    ridge = joblib.load(ROOT / "model_RIDGE_20260925.joblib")
    imputed = ridge.named_steps["impute"].transform(matrix)
    imputer_error = float(np.max(np.abs(np.nanmedian(matrix.to_numpy(float), axis=0) - ridge.named_steps["impute"].statistics_)))
    scaler_error = float(np.max(np.abs(imputed.mean(axis=0) - ridge.named_steps["scale"].mean_)))
    assert imputer_error == 0 and scaler_error == 0
    nn = {}
    for seed in train.SEEDS:
        model = joblib.load(ROOT / f"model_MLP_{seed}.joblib").named_steps["model"]
        assert model.n_iter_ > 0 and model.loss_curve_[-1] < model.loss_curve_[0]
        assert all(np.isfinite(w).all() and np.linalg.norm(w) > 0 for w in model.coefs_)
        nn[str(seed)] = {"iterations": int(model.n_iter_), "initial_loss": float(model.loss_curve_[0]),
                         "final_loss": float(model.loss_curve_[-1]),
                         "parameter_count": int(sum(w.size for w in model.coefs_))}
    for name in ("test2026.py", "score_corrected.py", "describe_results.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        fits = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                isinstance(node.func, ast.Attribute) and node.func.attr in {"fit", "fit_transform", "partial_fit"}]
        assert not fits, f"TEST_PATH_CONTAINS_FIT:{name}"
    paths = pd.read_parquet(ROOT / "2026_daily_paths_corrected.parquet")
    nav_error = float(paths.nav_identity_error.abs().max())
    cost_error = float(paths.cost_identity_error.abs().max())
    turnover_error = float(paths.turnover_identity_error.abs().max())
    assert max(nav_error, cost_error, turnover_error) < 1e-10
    assert paths.skipped_buy_count.sum() > 0  # coverage is retained, not silently filtered
    output = {"status": "PASS_FOCUSED", "panel_rows": len(panel), "final_train_rows": len(final),
              "max_train_label_end": str(final.label_end_date_exec.max()),
              "imputer_stat_max_abs_error": imputer_error, "scaler_mean_max_abs_error": scaler_error,
              "mlp_training": nn, "test_path_fit_calls_static": 0,
              "replay_nav_identity_max_abs": nav_error, "replay_cost_identity_max_abs": cost_error,
              "replay_turnover_identity_max_abs": turnover_error,
              "test_skipped_buy_count_all_candidates": int(paths.skipped_buy_count.sum()),
              "input_reconstruction": lineage}
    (ROOT / "verification.json").write_text(json.dumps(output, indent=2, default=str) + "\n", encoding="utf-8")
    print("PASS_FOCUSED", len(panel), len(final), nn)


if __name__ == "__main__":
    main()
