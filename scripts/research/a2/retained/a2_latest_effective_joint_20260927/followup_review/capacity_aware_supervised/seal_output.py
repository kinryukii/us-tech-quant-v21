"""Read-only verification and append-only seal of the two fixed HGB fits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SEAL = OUT / "OUTPUT_SEAL.json"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    if SEAL.exists():
        raise RuntimeError("PRESERVE_EXISTING_OUTPUT_SEAL")
    frozen = json.loads((OUT / "PRE_FIT_FREEZE.json").read_text(encoding="utf-8"))
    receipt = json.loads((OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    if frozen["status"] != "PRE_FIT_CAPACITY_HGB_LOCKED" or \
       receipt["status"] != "PASS" or receipt["revision"] != "CAPACITY_AWARE_HGB_ONE_STEP_R1" or \
       receipt["fit_calls"] != 2 or receipt["test_2026_reads"] != 0 or \
       receipt["hyperparameter_search_count"] != 0 or \
       not receipt["source_unchanged"] or not receipt["label_unchanged"]:
        raise RuntimeError("FIT_OR_FREEZE_NOT_ACCEPTABLE")
    if receipt["pre_fit_freeze_sha256"] != sha(OUT / "PRE_FIT_FREEZE.json"):
        raise RuntimeError("FIT_NOT_BOUND_TO_PRE_FIT_FREEZE")
    if [(r["stage"], r["name"]) for r in receipt["fits"]] != \
       [("validation", "hgb"), ("final", "hgb")]:
        raise RuntimeError("UNEXPECTED_FIT_SEQUENCE")
    names = ["PRE_FIT_FREEZE.json", "FIT_RECEIPT.json", "FIT_RECEIPT.partial.json",
             "validation_hgb.joblib", "final_hgb.joblib",
             "labels_validation.parquet", "labels_final.parquet",
             "labels_validation_metrics.parquet", "REAL_PRE2026_TECHNICAL_CHECK.json"]
    hashes = {}
    for name in names:
        path = OUT / name
        if not path.is_file():
            raise RuntimeError(f"MISSING_SEAL_FILE:{name}")
        hashes[name] = sha(path)
    for record in receipt["fits"]:
        if hashes[Path(record["artifact"]).name] != record["artifact_sha256"]:
            raise RuntimeError("MODEL_ARTIFACT_HASH_MISMATCH")
    for stage, details in frozen["stages"].items():
        if hashes[f"labels_{stage}.parquet"] != details["label_sha256"]:
            raise RuntimeError(f"LABEL_HASH_MISMATCH:{stage}")
    if hashes["REAL_PRE2026_TECHNICAL_CHECK.json"] != frozen["real_technical_check_sha256"]:
        raise RuntimeError("REAL_TECHNICAL_HASH_MISMATCH")
    seal = dict(status="CAPACITY_AWARE_SUPERVISED_HGB_TWO_FITS_SEALED",
                batch="a2_latest_effective_joint_20260927", source_contract="SCIENCE_CONTRACT.md",
                fit_calls=2, test_2026_reads=0, stage_rows={r["stage"]: r["rows"] for r in receipt["fits"]},
                model_sha256={r["stage"]: r["artifact_sha256"] for r in receipt["fits"]},
                files_sha256=hashes, input_and_code_sha256=frozen["sources_sha256"],
                pre_fit_freeze_sha256=hashes["PRE_FIT_FREEZE.json"],
                fit_receipt_sha256=hashes["FIT_RECEIPT.json"],
                policy_code_sha256=frozen["sources_sha256"]["/joint/followup_review/capacity_aware_supervised/policy.py"],
                technical_synthetic_sha256=frozen["technical_check_sha256"],
                technical_real_sha256=frozen["real_technical_check_sha256"],
                validation_economic_comparison_read=False)
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps(dict(status=seal["status"], seal_sha256=sha(SEAL),
                          fit_calls=2, test_2026_reads=0)))


if __name__ == "__main__":
    main()
