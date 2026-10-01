"""Read-only artifact checks followed by a compact local summary manifest."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from distribution_readout import cdf, inverse_cdf
from fit_predictive import HERE, KEY, MATRIX, REFERENCE, QUANTILES, sha, write_json


def main() -> None:
    identity = json.loads((HERE / "INPUT_IDENTITY.json").read_text(encoding="utf-8"))
    maturity = json.loads((HERE / "TARGET_MATURITY_AUDIT.json").read_text(encoding="utf-8"))
    assert maturity["status"] == "PASS_ALL_SAVED_TRAINING_LABELS_MATURED_PRE2026"
    assert maturity["row_count_checked"] == identity["train_rows"]
    assert maturity["rows_label_maturity_2026_plus"] == 0
    assert maturity["rows_20_session_mapping_mismatch"] == 0
    assert sha(HERE / "TARGET_MATURITY_BY_SIGNAL_DATE.csv") == maturity["daily_proof_sha256"]
    ref = pd.read_parquet(REFERENCE, columns=KEY).sort_values(KEY, kind="mergesort").reset_index(drop=True)
    paths = []
    methods = {}
    for name, directory, prediction_name in [
        ("logistic", "logistic_positive_target", "pre2026_oof_probability.parquet"),
        ("distribution", "distribution_quantile_function", "pre2026_oof_distribution.parquet"),
    ]:
        root = HERE / directory
        logs = json.loads((root / "fit_log.json").read_text(encoding="utf-8"))
        pred = pd.read_parquet(root / prediction_name).sort_values(KEY, kind="mergesort").reset_index(drop=True)
        assert pred[KEY].equals(ref[KEY]) and len(pred) == 313668
        assert pred.signal_date.max() < pd.Timestamp("2026-01-01")
        assert all(x["leakage_row_count"] == 0 for x in logs if x["stage"] != "FULL_PRE2026")
        for entry in logs:
            model_path = Path(entry["model_path"])
            assert model_path.resolve().is_relative_to(HERE.resolve())
            assert sha(model_path) == entry["model_sha256"]
            model = joblib.load(model_path)
            assert hasattr(model, "predict")
            paths.append(model_path)
        if name == "logistic":
            assert len(logs) == 4 and pred.positive_probability.between(0, 1).all()
            assert np.isfinite(pred.positive_probability.to_numpy()).all()
            assert max(x["n_iter"] for x in logs) < 300
        else:
            assert len(logs) == 12 and sorted(set(x["quantile"] for x in logs)) == list(QUANTILES)
            q = pred[["q10", "q50", "q90"]].to_numpy(dtype=float)
            assert np.isfinite(q).all() and (q[:, 0] <= q[:, 1]).all() and (q[:, 1] <= q[:, 2]).all()
            sample = q[::997]
            assert (inverse_cdf(sample, np.full(len(sample), .1)) == sample[:, 0]).all()
            assert (inverse_cdf(sample, np.full(len(sample), .5)) == sample[:, 1]).all()
            assert (inverse_cdf(sample, np.full(len(sample), .9)) == sample[:, 2]).all()
            grid = np.linspace(float(sample.min()) - 1, float(sample.max()) + 1, 101)
            cdf_grid = np.stack([cdf(sample, np.full(len(sample), z)) for z in grid], axis=1)
            assert (np.diff(cdf_grid, axis=1) >= -1e-12).all()
            assert (cdf_grid >= 0).all() and (cdf_grid <= 1).all()
        paths += [root / "fit_log.json", root / "pre2026_validation.json", root / prediction_name]
        methods[name] = {
            "completed_fits": len(logs), "out_of_fold_prediction_rows": len(pred),
            "stage_training_rows": [x["train_rows"] for x in logs if x["stage"] != "FULL_PRE2026"],
            "full_training_rows": next(x["train_rows"] for x in logs if x["stage"] == "FULL_PRE2026"),
            "validation": str(root / "pre2026_validation.json"),
            "prediction_artifact": str(root / prediction_name),
        }
    paths += [HERE / "PRE_FIT_CONTRACT.json", HERE / "fit_predictive.py",
              HERE / "distribution_readout.py", HERE / "finalize_predictive.py",
              HERE / "RECOVERY_NOTE.json", HERE / "INPUT_IDENTITY.json", HERE / "REPORT.md",
              HERE / "audit_target_maturity.py", HERE / "TARGET_MATURITY_AUDIT.json",
              HERE / "TARGET_MATURITY_BY_SIGNAL_DATE.csv"]
    hashes = {str(path): sha(path) for path in paths}
    summary = {
        "status": "PASS_PRE2026_ADDITIONAL_METHODS_FIT_AND_VALIDATED",
        "original_training_matrix_sha256": sha(MATRIX),
        "original_training_matrix_rows": identity["train_rows"],
        "method_fits_completed": sum(x["completed_fits"] for x in methods.values()),
        "interrupted_extra_fit": 1,
        "actual_fit_calls_total": sum(x["completed_fits"] for x in methods.values()) + 1,
        "2026_input_read": False, "2026_model_fit_count": 0,
        "model_selection_trials": 0,
        "methods": methods,
        "limitation": "Classification changes target to sign(y); quantile distribution predicts a piecewise inverse CDF with declared constant tails. Neither has a predeclared original-return mean ranking or portfolio readout.",
        "artifact_sha256": hashes,
    }
    write_json(HERE / "FIT_SUMMARY.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "artifact_sha256"}, indent=2))


if __name__ == "__main__":
    main()
