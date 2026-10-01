"""One-off, no-test verification of the sealed R1 training output."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path("/bundle")
OUT = Path("/out")
CUTOFF = pd.Timestamp("2026-01-01")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    seal = json.loads((OUT / "input_seal.json").read_text())
    expected = {item["path"]: item for item in seal["files"]}
    actual = {str(path.relative_to(ROOT)).replace("\\", "/"): path
              for path in ROOT.rglob("*") if path.is_file()}
    if set(actual) != set(expected):
        raise RuntimeError("SEALED_FILE_SET_CHANGED")
    for name, path in actual.items():
        item = expected[name]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError(f"SEALED_FILE_CHANGED:{name}")

    manifest = json.loads((ROOT / "input_manifest.json").read_text())
    if sha(ROOT / "input_manifest.json") != seal["bundle_manifest_sha256"]:
        raise RuntimeError("MANIFEST_SEAL_MISMATCH")
    for name, expected_hash in manifest["training_code_sha256"].items():
        if sha(ROOT / name) != expected_hash:
            raise RuntimeError(f"CODE_HASH_CHANGED:{name}")
    for name, key in (("panel.parquet", "panel_sha256"),
                      ("risk_panel.parquet", "risk_panel_sha256"),
                      ("prices.parquet", "prices_sha256")):
        if sha(ROOT / "data" / name) != manifest[key]:
            raise RuntimeError(f"INPUT_HASH_CHANGED:{name}")

    date_columns_checked = 0
    for name, path in actual.items():
        if path.suffix != ".parquet":
            continue
        source = pq.ParquetFile(path)
        for field in source.schema_arrow:
            if not (pa.types.is_timestamp(field.type) or pa.types.is_date(field.type)):
                continue
            values = pq.read_table(path, columns=[field.name]).to_pandas()[field.name]
            if values.notna().any() and pd.Timestamp(values.max()) >= CUTOFF:
                raise RuntimeError(f"POST_CUTOFF_DATE:{name}:{field.name}")
            date_columns_checked += 1

    panel = pq.read_table(ROOT / "data/panel.parquet",
                          columns=["signal_date", "label_end_date_5", "y5",
                                   "y5_cost_positive"]).to_pandas()
    mature = panel.label_end_date_5.notna() & np.isfinite(panel.y5)
    if (panel.loc[mature, "label_end_date_5"] >= CUTOFF).any():
        raise RuntimeError("CROSS_YEAR_LABEL_ADMITTED")
    if panel.loc[~np.isfinite(panel.y5), "y5_cost_positive"].notna().any():
        raise RuntimeError("MISSING_RETURN_CLASSIFIED")

    receipt = json.loads((ROOT / "training_run.json").read_text())
    observed = receipt["observed_work"]
    if (receipt["status"] != "PRE2026_TRAINING_COMPLETE_AWAITING_INDEPENDENT_REVIEW"
            or observed["supervised_fit_log_lines"] != 27
            or observed["rl_parameter_updates_logged"] != 196
            or not receipt["code_integrity_at_exit"]
            or not all(receipt["input_integrity_at_exit"].values())):
        raise RuntimeError("TRAINING_RECEIPT_INCONSISTENT")
    supervised = json.loads((ROOT / "supervised_manifest.json").read_text())
    if supervised["fit_count"] != 27 or sha(ROOT / "pre2026_oof.parquet") != supervised["oof_sha256"]:
        raise RuntimeError("SUPERVISED_RECEIPT_INCONSISTENT")
    for artifact in supervised["artifacts"].values():
        if sha(ROOT / artifact["path"]) != artifact["sha256"]:
            raise RuntimeError("SUPERVISED_MODEL_CHANGED")
    revision = json.loads((ROOT / "risk_artifacts/final_aux_revision.json").read_text())
    if sha(ROOT / "risk_artifacts/final_pre2026.joblib") != revision["updated_model_sha256"]:
        raise RuntimeError("RISK_MODEL_CHANGED")
    updates = [json.loads(line) for line in (ROOT / "rl_artifacts/updates.jsonl").read_text().splitlines()]
    rl_manifest = json.loads((ROOT / "rl_artifacts/manifest.json").read_text())
    if len(updates) != rl_manifest["total_updates"] or len(updates) > 288:
        raise RuntimeError("RL_UPDATE_COUNT_MISMATCH")
    if any(pd.Timestamp(row["train_last_signal"]) >= CUTOFF for row in updates):
        raise RuntimeError("RL_POST_CUTOFF_TRAJECTORY")

    report = {"status": "NO_TEST_TECHNICAL_REVIEW_PASS",
              "sealed_files_verified": len(actual),
              "parquet_date_columns_checked": date_columns_checked,
              "panel_rows": len(panel), "mature_labels": int(mature.sum()),
              "supervised_fits": supervised["fit_count"],
              "rl_parameter_updates": len(updates),
              "risk_final_hash_verified": True,
              "scope": "sealed pre-2026 output only; no 2026 test source mounted"}
    (OUT / "technical_review_receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
