"""Seal only this joint batch's revised pre-2026 supervised models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
JOINT = BASE.parent
OUT = BASE / "out"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    target = BASE / "PRE2026_V2_FREEZE.json"
    if target.exists():
        raise RuntimeError("V2_FREEZE_ALREADY_EXISTS")
    contract = json.loads((OUT / "PRE_FIT_CONTRACT.json").read_text(encoding="utf-8"))
    receipt = json.loads((OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    verification = json.loads((OUT / "TECHNICAL_VERIFICATION.json").read_text(encoding="utf-8"))
    if contract["status"] != "PRE_FIT_LOCKED" or receipt["status"] != "PASS" or verification["status"] != "PASS":
        raise RuntimeError("NOT_VERIFIED_FOR_FREEZE")
    if receipt["fit_calls"] != 14 or receipt["total_fit_calls_including_numerical_repairs"] != 16:
        raise RuntimeError("UNEXPECTED_FIT_COUNT")
    paths = [
        JOINT / "data/pre2026_joint.parquet",
        JOINT / "joint_linear_tree.py",
        JOINT / "joint_linear_tree_artifacts/FIT_RECEIPT.json",
        JOINT / "joint_linear_tree_artifacts/final_hgb.joblib",
        BASE / "bundle/joint_linear_tree.py",
        BASE / "bundle/models/model_registry.json",
        BASE / "bundle/retrain_coverage_v2.py",
        BASE / "bundle/refine_coverage_v2_elastic.py",
        BASE / "bundle/v2_policy.py",
        BASE / "bundle/verify_coverage_v2.py",
        BASE / "run_v2.ps1",
        OUT / "PRE_FIT_CONTRACT.json",
        OUT / "FIT_RECEIPT_BEFORE_NUMERICAL_REPAIR.json",
        OUT / "ELASTIC_REPAIR_PRE_FIT_CONTRACT.json",
        OUT / "FIT_RECEIPT.json",
        OUT / "ELASTIC_REPAIR_RECEIPT.json",
        OUT / "TECHNICAL_VERIFICATION.json",
    ]
    paths += sorted(OUT.glob("sample_keys_*.parquet"))
    paths += sorted(OUT.glob("*.joblib"))
    for phase in ("canary", "prepare", "train", "repair_prepare", "repair_train", "verify"):
        paths += [BASE / f"{phase}.CONTAINER_RECEIPT.json",
                  BASE / f"{phase}.CONTAINER_INSPECT.json",
                  BASE / f"{phase}.CONTAINER_FINAL_INSPECT.json",
                  BASE / f"{phase}.CONTAINER_LOG.txt",
                  BASE / f"{phase}.CREATE_ARGV.json"]
    files = {str(p.relative_to(JOINT)).replace("\\", "/"): sha(p) for p in paths}
    assert files["data/pre2026_joint.parquet"] == contract["input_sha256"]
    assert files["joint_linear_tree.py"] == files["joint_linear_tree_coverage_v2/bundle/joint_linear_tree.py"]
    for record in [*receipt["fits"], *receipt["numerical_repairs"]]:
        p = OUT / Path(record["artifact"]).name
        assert files[str(p.relative_to(JOINT)).replace("\\", "/")] == record["artifact_sha256"]
    seal = {"status": "PRE2026_SUPERVISED_V2_FROZEN",
            "version": "joint_linear_tree_coverage_v2",
            "scope": "seven joint linear/tree action-value estimators; validation and final, plus two same-objective ElasticNet numerical continuations",
            "scientific_change": contract["scientific_change"],
            "validation_training_dates_old_new": [30, contract["stages"]["validation"]["selected_dates"]],
            "final_training_dates_old_new": [27, contract["stages"]["final"]["selected_dates"]],
            "main_fit_calls": 14, "numerical_repair_fit_calls": 2,
            "peak_rss_kib_main_training": receipt["peak_rss_kib"],
            "test2026_input_mounted_or_read": False,
            "mlp_retrained": False, "rl_updates": 0,
            "model_artifact_count": len(list(OUT.glob("*.joblib"))),
            "files_sha256": files,
            "not_a_full_batch_test_freeze": True}
    target.write_text(json.dumps(seal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": seal["status"], "files": len(files),
                      "sha256": sha(target)}))


if __name__ == "__main__":
    main()
