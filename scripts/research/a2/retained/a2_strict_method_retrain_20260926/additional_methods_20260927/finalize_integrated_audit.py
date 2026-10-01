"""Read-only, bounded-memory identity/time audit of new methods and frozen A2."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def main() -> None:
    cutoff = read(HERE / "TRAINING_CUTOFF_AUDIT.json")
    pred = read(HERE / "predictive/FIT_SUMMARY.json")
    risk = read(HERE / "risk_optimization/results/TEMPORAL_BOUNDARY_AUDIT_20260927.json")
    risk_repair = read(HERE / "risk_optimization/REPAIR_8_TO_10_BPS.json")
    rl = read(HERE / "state_rl/POLICY_GRADIENT_REPORT.json")
    rl_audit = read(HERE / "state_rl/POSTFIT_LEAKAGE_AND_ACCOUNTING_AUDIT.json")
    cluster = read(HERE / "state_rl/STATE_CLUSTER_REPORT.json")
    freeze = read(BASE / "pre2026_model_freeze.json")
    assert cutoff["max_target_end_date"] == cutoff["max_price_date"] == "2025-12-31"
    assert cutoff["targets_maturing_in_2026_or_later"] == cutoff["price_rows_in_2026_or_later"] == 0
    assert pred["actual_fit_calls_total"] == 17 and not pred["2026_input_read"]
    assert pred["original_training_matrix_sha256"] == cutoff["training_matrix_sha256"]
    assert risk["read_2026_price_rows"] == risk["used_2026_training_labels"] == 0
    assert risk["training_matrix_sha256"] == cutoff["training_matrix_sha256"]
    assert risk["price_coordinate_sha256"] == cutoff["source_price_sha256"]
    assert risk_repair["actual_execution_history_counts"]["cumulative_actual"]["factor_pipeline_fits"] == 11
    assert risk_repair["corrected_ex_ante_budget_bps_min"] == risk_repair["corrected_ex_ante_budget_bps_max"] == 10
    assert rl["total_policy_optimizer_steps_including_aborted_pilot"] == 33
    assert rl["total_preprocessor_fit_calls_including_aborted_pilot"] == 3
    assert rl["2026_input_used_for_fit_selection_or_reward"] is False
    assert rl_audit["no_2026_fit_reward_selection_or_eval"] is True
    assert rl_audit["full_pre2026_refit_train_log_max_consumed_price_date"] == "2025-12-31"
    assert cluster["purpose"].startswith("Observation-time")

    frozen = {}
    for method in ("hgb", "ridge", "elastic_net", "mlp"):
        model = BASE / method / "final_full_pre2026.joblib"
        expected = next(item["sha256"] for item in freeze["models"][method]["fits"]
                        if item["stage"] == "FULL_PRE2026")
        actual = sha(model)
        assert actual == expected, method
        frozen[method] = actual
    assert sha(BASE / "common_frozen.json") == "ac5c4e82791bda9670c3f81660f2cdf7ae3cd191f7b333f894452eabaadb4f8e"

    for name, expected in rl["artifacts"].items():
        assert sha(HERE / "state_rl" / name) == expected, name
    for path_text, expected in pred["artifact_sha256"].items():
        assert sha(Path(path_text)) == expected, path_text

    result = {
        "status": "IDENTITIES_AND_PRE2026_CUTOFF_VERIFIED_NO_2026_METHOD_TEST",
        "training_matrix_sha256": cutoff["training_matrix_sha256"],
        "training_matrix_rows": cutoff["training_matrix_rows"],
        "latest_training_label_date": cutoff["max_target_end_date"],
        "latest_training_price_date": cutoff["max_price_date"],
        "2026_training_labels_or_prices": 0,
        "original_four_full_pre2026_sha256": frozen,
        "original_four_fit_calls_in_test2026": 0,
        "new_predictive_actual_fit_calls": 17,
        "new_risk_actual_factor_pipeline_fit_calls": 11,
        "new_risk_actual_covariance_fit_calls": 2250,
        "new_rl_actual_optimizer_steps": 33,
        "new_rl_actual_preprocessor_fit_calls": 3,
        "new_cluster_model_fit_calls": 4,
        "new_cluster_preprocessor_fit_calls": 4,
        "limits": [
            "RL 2025 forward result belongs only to policy_validated.pt; FULL_PRE2026 refit has no independent forward test.",
            "Risk budget was corrected from 8 to 10 bps after viewing pre2026 validation; corrected historical scores are not untouched validation.",
            "Original adjusted-price history has not been independently proven point-in-time at every historical receipt date.",
            "Common 2026 candidate and portfolio price gates remain incomplete; no method winner or 2026 NAV is established.",
        ],
    }
    (HERE / "INTEGRATED_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": result["status"], "frozen_models": len(frozen),
                      "new_fit_calls": {"predictive": 17, "risk_pipeline": 11, "rl_steps": 33}}))


if __name__ == "__main__":
    main()
