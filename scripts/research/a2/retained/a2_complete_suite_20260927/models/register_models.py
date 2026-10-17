"""Bind previously completed pre-2026 fits without retraining or reading test data."""
from __future__ import annotations
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
STRICT = WORKSPACE / "a2_strict_method_retrain_20260926"
EXTRA = STRICT / "additional_methods_20260927"
STATE = EXTRA / "state_rl"
CUTOFF = pd.Timestamp("2026-01-01")
MATRIX = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\training_matrix.parquet")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    common = read(STRICT / "results/common_frozen.json")
    features = common["feature_order"]
    cutoff_audit = read(EXTRA / "TRAINING_CUTOFF_AUDIT.json")
    matrix_hash = sha(MATRIX)
    assert matrix_hash == cutoff_audit["training_matrix_sha256"]
    matrix = pd.read_parquet(MATRIX, columns=["signal_date", "target_end_date", "target"])
    assert len(matrix) == 520328
    assert matrix.signal_date.notna().all() and matrix.target_end_date.notna().all()
    assert matrix.signal_date.lt(CUTOFF).all() and matrix.target_end_date.lt(CUTOFF).all()
    assert np.isfinite(matrix.target.to_numpy(float)).all()
    assert matrix.target_end_date.ge(matrix.signal_date).all()
    maturity = {"train_rows": len(matrix), "train_signal_max": str(matrix.signal_date.max().date()),
                "train_label_end_max": str(matrix.target_end_date.max().date()), "train_matrix_sha256": matrix_hash}
    registry = {"created_utc": datetime.now(timezone.utc).isoformat(), "cutoff_exclusive": "2026-01-01",
                "feature_order": features, "target": "MEAN_ER_3D_5D_10D_20D", "training_data": maturity,
                "existing_models_refit_count": 0, "test_outcomes_read": 0, "models": {}, "audits": []}
    checked_fits = []

    def add(name, source, role, log_path=None, quantile=None):
        source = Path(source)
        current_sha = sha(source)
        matched_final = False
        if log_path:
            log_path = Path(log_path)
            entries = read(log_path)
            for entry in entries:
                if quantile is not None and entry.get("quantile") != quantile:
                    continue
                recorded = Path(entry.get("model_path", entry.get("model_artifact", "")))
                model_file = log_path.parent / recorded.name
                assert sha(model_file) == entry["model_sha256"], (name, model_file)
                if entry["stage"] == "FULL_PRE2026":
                    assert entry["train_rows"] == len(matrix)
                    assert current_sha == entry["model_sha256"]
                    matched_final = True
                    bound = maturity["train_label_end_max"]
                else:
                    bound = entry["train_target_end_max"]
                    assert pd.Timestamp(bound) < pd.Timestamp(entry["evaluation_start"]) < CUTOFF
                    assert pd.Timestamp(entry["train_end"]) < pd.Timestamp(entry["evaluation_start"])
                    assert entry["leakage_row_count"] == 0
                assert pd.Timestamp(bound) < CUTOFF
                checked_fits.append({"model": name, "stage": entry["stage"], "train_rows": entry["train_rows"],
                                     "train_label_end_max": bound, "artifact_sha256": entry["model_sha256"]})
            assert matched_final, name
        dest = HERE / (name + source.suffix)
        shutil.copyfile(source, dest)
        assert sha(dest) == current_sha
        registry["models"][name] = {"path": str(dest), "source_path": str(source), "sha256": current_sha,
                                      "role": role, "fit_reused": True, "training_cutoff_exclusive": "2026-01-01",
                                      "fit_log_path": str(log_path) if log_path else None,
                                      "fit_log_sha256": sha(log_path) if log_path else None,
                                      "feature_order": features if name not in ("cluster", "anomaly") else None}

    for name in ("ridge", "elastic_net", "hgb", "mlp"):
        directory = STRICT / "results" / name
        add(name, directory / "final_full_pre2026.joblib", "continuous_target_prediction", directory / "fit_log.json")
    directory = EXTRA / "predictive/logistic_positive_target"
    add("logistic", directory / "final_full_pre2026.joblib", "probability_target_above_zero_for_ranking_only", directory / "fit_log.json")
    directory = EXTRA / "predictive/distribution_quantile_function"
    for quantile in (.1, .5, .9):
        name = f"q{int(100 * quantile)}"
        add(name, directory / f"final_full_pre2026_{name}.joblib", "conditional_target_quantile", directory / "fit_log.json", quantile)
    directory = EXTRA / "risk_optimization/results"
    add("pca_ridge", directory / "final_full_pre2026_factor_model.joblib", "PCA8_continuous_target_prediction", directory / "FIT_LOG.json")
    cluster_report = read(STATE / "STATE_CLUSTER_REPORT.json")
    for entry in cluster_report["training_schedule"]:
        assert max(entry["fit_years"]) < 2026
        model_path = STATE / f"state_cluster_{entry['stage'].lower()}.joblib"
        assert sha(model_path) == entry["model_sha256"]
    add("cluster", STATE / "state_cluster_full_pre2026.joblib", "daily_state_diagnostic_only")
    registry["daily_state_columns"] = cluster_report["daily_state_columns"]
    registry["models"]["cluster"]["feature_order"] = registry["daily_state_columns"]
    rl_preflight = read(STATE / "RL_TIME_LEAKAGE_PREFLIGHT.json")
    for entry in rl_preflight["episode_boundaries"]:
        assert pd.Timestamp(entry["max_consumed_price_date"]) < CUTOFF
        assert entry["cross_year_steps"] == 0
    rl_postfit = read(STATE / "POSTFIT_LEAKAGE_AND_ACCOUNTING_AUDIT.json")
    assert rl_postfit["no_2026_fit_reward_selection_or_eval"]
    assert pd.Timestamp(rl_postfit["full_pre2026_refit_train_log_max_consumed_price_date"]) < CUTOFF
    rl_report = read(STATE / "POLICY_GRADIENT_REPORT.json")
    assert not rl_report["2026_input_used_for_fit_selection_or_reward"]
    add("rl_policy", STATE / "policy_full_pre2026.pt", "linear_policy_gradient_top20_ranking")
    add("rl_scaler", STATE / "policy_full_pre2026_scaler.joblib", "pre2026_RL_feature_scaler")
    for path in (EXTRA / "TRAINING_CUTOFF_AUDIT.json", EXTRA / "predictive/TARGET_MATURITY_AUDIT.json",
                 directory / "TEMPORAL_BOUNDARY_AUDIT_20260927.json", STATE / "STATE_CLUSTER_REPORT.json",
                 STATE / "RL_TIME_LEAKAGE_PREFLIGHT.json", STATE / "POSTFIT_LEAKAGE_AND_ACCOUNTING_AUDIT.json",
                 STATE / "POLICY_GRADIENT_REPORT.json"):
        registry["audits"].append({"path": str(path), "sha256": sha(path)})
    registry["verified_supervised_fit_count"] = len(checked_fits)
    registry["model_scope_note"] = "Full pre-2026 supervised weights are for 2026 inference; pre-2026 output from these weights is a smoke test, never OOF performance. Cluster/anomaly are diagnostic only. RL ranks TOP20 from previous target membership; it is not a continuous-size RL policy."
    write(HERE / "model_registry.json", registry)
    write(HERE / "existing_training_audit.json", {"status": "PASS", **maturity, "verified_supervised_fits": checked_fits,
                                                  "fit_calls_this_script": 0, "test_outcomes_read": 0})
    print(json.dumps({"status": "PASS", "models_copied": len(registry["models"]), "verified_fits": len(checked_fits)}))


if __name__ == "__main__":
    main()
