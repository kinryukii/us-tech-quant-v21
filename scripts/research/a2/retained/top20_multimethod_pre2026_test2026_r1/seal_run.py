"""Write the single final run manifest after every planned pre-2026 fit exists."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from policy_engine import HERE


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    manifest_path = HERE / "RUN_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fits = pd.read_csv(HERE / "FIT_LOG.csv")
    if len(fits) != 64 or fits.groupby("fold").size().to_dict() != {"D1": 21, "D2": 21, "FINAL": 11, "V25": 11}:
        raise RuntimeError("SUPERVISED_BUDGET_NOT_COMPLETE")
    ppo_receipts = [HERE / "ppo_artifacts" / f"PPO_{fold}_seed{seed}.json"
                    for fold in ("D1", "D2", "V25", "FINAL") for seed in (11, 29, 47)]
    if not all(path.exists() for path in ppo_receipts):
        raise RuntimeError("PPO_BUDGET_NOT_COMPLETE")
    ppo = [json.loads(path.read_text(encoding="utf-8")) for path in ppo_receipts]
    if any(r["status"] != "FITTED" or r["environment_steps"] != 32768 or
           r["optimizer_steps"] != 2560 or r["actor_before_sha256"] == r["actor_after_sha256"]
           for r in ppo):
        raise RuntimeError("PPO_RECEIPT_INVALID")
    risk = json.loads((HERE / "RISK_DIAGNOSTIC_MANIFEST.json").read_text(encoding="utf-8"))
    if set(risk) != {"D1", "D2", "V25", "FINAL"} or any(risk[f]["model_fit_count"] != 4 for f in risk):
        raise RuntimeError("RISK_BUDGET_NOT_COMPLETE")
    policy = {fold: json.loads((HERE / f"{prefix}_POLICY_MANIFEST.json").read_text(encoding="utf-8"))
              for fold, prefix in (("D1", "DEVELOPMENT_D1"), ("D2", "DEVELOPMENT_D2"),
                                   ("V25", "V25"), ("FINAL", "FINAL_INSAMPLE"))}
    primary = json.loads((HERE / "PRIMARY_SELECTION.json").read_text(encoding="utf-8"))
    old_continuation = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1" / "CONTINUATION_MANIFEST.json"
    old = json.loads(old_continuation.read_text(encoding="utf-8"))
    if (old["fixed_test_asof"] != manifest["test_asof"] or
        old["this_continuation_counts"]["formal_2026_test_reveals"] != 0):
        raise RuntimeError("OLD_TEST_STATE_CHANGED_RECHECK_REQUIRED")
    final_models = [p for p in (HERE / "models").glob("FINAL_*.*") if p.suffix in (".joblib", ".pt")]
    final_models += [HERE / "models" / name for name in
                     ("SCALER_FINAL.joblib", "LW_FINAL.joblib", "PCA_FINAL.joblib",
                      "KMEANS_FINAL.joblib", "ISOLATION_FINAL.joblib")]
    final_models = sorted(set(final_models), key=lambda p: p.name)
    if not all(p.exists() for p in final_models):
        raise RuntimeError("FINAL_MODEL_MISSING")
    manifest["status"] = "PRE2026_ALL_METHODS_FROZEN_WAITING_TEST_INPUT"
    manifest["new_experiment"] = {
        "a2_fits": 0, "supervised_parameter_fits_completed": len(fits),
        "risk_pca_cluster_isolation_fits_completed": 16,
        "scalers_fitted_on_training_folds": 4,
        "ppo_completed_seed_fits": len(ppo),
        "ppo_environment_steps": int(sum(r["environment_steps"] for r in ppo)),
        "ppo_optimizer_steps": int(sum(r["optimizer_steps"] for r in ppo)),
        "new_predictor_and_ppo_fit_total": len(fits) + len(ppo),
        "qp_deterministic_calls": int(sum(p["solver_calls"] for p in policy.values())),
        "qp_failures": int(sum(p["solver_failed"] for p in policy.values())),
        "model_fitting_2026": 0, "formal_2026_test_reveals": 0}
    manifest["selection"] = {"prediction_configs": "DEVELOPMENT_SELECTION.json",
                              "primary": primary["primary"], "primary_source_sha256": sha(HERE / "PRIMARY_SELECTION.json"),
                              "no_2025_or_2026_used": primary["no_v25_or_2026_read"]}
    manifest["final_frozen_artifacts_sha256"] = {p.name: sha(p) for p in final_models}
    manifest["ppo_seed_artifacts_sha256"] = {p.name: sha(HERE / "ppo_artifacts" / p.name.replace(".json", ".zip"))
                                               for p in ppo_receipts}
    manifest["artifact_checks"] = {name: sha(HERE / name) for name in
                                    ("PRE2026_SHARED_PANEL.parquet", "PRE2026_PRICE_COORDINATE.parquet",
                                     "FIT_LOG.csv", "MODEL_RESTORE_CHECK.json",
                                     "B0_ACCOUNTING_COMPARISON.json", "PREDICTION_DIAGNOSTICS.json",
                                     "POLICY_COMPARISON.csv", "V25_ATTRIBUTION_CHECK.json",
                                     "TRAIN_ONLY_ARTIFACT_AUDIT.json",
                                     "METHOD_COVERAGE.csv", "README.md", "TEST2026_INPUT_GATE.json")}
    gate = json.loads((HERE / "TEST2026_INPUT_GATE.json").read_text(encoding="utf-8"))
    if gate["source"][old_continuation.name]["sha256"] != sha(old_continuation):
        raise RuntimeError("2026_GATE_SOURCE_CHANGED_RECHECK_REQUIRED")
    manifest["test2026"] = {"status": "WAITING_TEST_INPUT", "formal_batch_run": False,
                             "test_reveals": 0,
                             "old_continuation_manifest_path": str(old_continuation),
                             "old_continuation_manifest_sha256": sha(old_continuation),
                             "gate_recheck_path": str(HERE / "TEST2026_INPUT_GATE.json"),
                             "gate_recheck_sha256": sha(HERE / "TEST2026_INPUT_GATE.json"),
                             "candidate_state_complete_days": old["remaining75_resolution"]["candidate_state_complete_days"],
                             "unknown_candidate_days_full_pool": old["remaining75_resolution"]["unknown_candidate_days_full_pool"],
                             "reason": "Full-window frozen A2 candidate comparison and consumed action versions/accounting settlement are not qualified; no shrinking or partial signal accepted."}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "fits": manifest["new_experiment"],
                      "primary": primary["primary"]}))


if __name__ == "__main__":
    main()
