"""Single-use training stage. It does not mount or read any 2026 test source."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from prepare import FEATURES

ROOT = Path(__file__).resolve().parent
STEPS = ("technical_tests.py", "fit_supervised.py", "risk_aux.py",
         "optimize_route.py", "rl_train.py")
PANEL_FIELDS = ["signal_date", "ticker", "security_id", "raw_rank", "raw_score",
                "prediction_asof_date", "training_cutoff", "model_hash", "entry_date",
                "label_end_date_5", "entry_open", "end_open_5", "y5",
                "y5_cost_positive", "label_status", *FEATURES]
RISK_FIELDS = ["signal_date", "ticker", "raw_rank_strength", "raw_score_z",
               "ret_1d", "ret_5d", "ret_20d", "realized_vol_20d",
               "downside_vol_20d", "max_drawdown_20d", "volume_ratio_5d_20d",
               "price_vs_ma20", "distance_from_high_20d"]


def prefit_eligibility():
    schemas = (("panel.parquet", PANEL_FIELDS), ("risk_panel.parquet", RISK_FIELDS),
               ("prices.parquet", ["ticker", "trade_date", "open", "close"]))
    for name, fields in schemas:
        if pq.ParquetFile(ROOT / "data" / name).schema_arrow.names != fields:
            raise RuntimeError(f"TRAINING_FIELD_WHITELIST_CHANGED:{name}")
    panel = pq.read_table(ROOT / "data" / "panel.parquet",
                          columns=["signal_date", "prediction_asof_date", "training_cutoff",
                                   "label_end_date_5", "y5", "y5_cost_positive"]).to_pandas()
    if panel.signal_date.ge("2026-01-01").any():
        raise RuntimeError("POST_CUTOFF_SIGNAL")
    if (panel.prediction_asof_date > panel.signal_date).any() or (panel.training_cutoff >= panel.signal_date).any():
        raise RuntimeError("A2_FUTURE_LINEAGE")
    mature = (panel.label_end_date_5.notna() & np.isfinite(panel.y5)
              & np.isfinite(panel.y5_cost_positive))
    if panel.loc[~np.isfinite(panel.y5), "y5_cost_positive"].notna().any():
        raise RuntimeError("UNLABELLED_ROW_HAS_CLASS_ANSWER")
    if not panel.loc[mature, "y5_cost_positive"].isin([0., 1.]).all():
        raise RuntimeError("BAD_CLASS_DOMAIN")
    if not ((panel.loc[mature, "y5"] > .001).to_numpy()
            == panel.loc[mature, "y5_cost_positive"].to_numpy(bool)).all():
        raise RuntimeError("CLASS_RETURN_MISMATCH")
    folds = {}
    for name, cutoff in (("2024", "2024-01-01"), ("2025", "2025-01-01"),
                         ("FINAL", "2026-01-01")):
        eligible = panel.loc[panel.signal_date.lt(cutoff)
                             & panel.label_end_date_5.lt(cutoff) & mature]
        if eligible.empty or eligible.label_end_date_5.max() >= pd.Timestamp(cutoff):
            raise RuntimeError(f"FOLD_MATURITY_FAILURE:{name}")
        folds[name] = {"train_rows": len(eligible),
                       "last_signal": str(eligible.signal_date.max().date()),
                       "last_mature_label": str(eligible.label_end_date_5.max().date())}
    return folds


def main() -> None:
    if os.environ.get("R1_VERIFIED_ISOLATION") != "1" or not Path("/bundle").is_dir():
        raise RuntimeError("RESTRICTED_RUNTIME_HANDOFF_REQUIRED")
    resume_risk = os.environ.get("R1_RESUME_FROM_RISK") == "1"
    if (ROOT / "training_run.json").exists() and not resume_risk:
        raise RuntimeError("TRAINING_RUN_ALREADY_STARTED")
    manifest_bytes = (ROOT / "input_manifest.json").read_bytes()
    expected_manifest = os.environ.get("R1_EXPECTED_MANIFEST_SHA256")
    actual_manifest = hashlib.sha256(manifest_bytes).hexdigest()
    if not expected_manifest or actual_manifest != expected_manifest:
        raise RuntimeError("EXTERNAL_BUNDLE_SEAL_MISMATCH")
    manifest = json.loads(manifest_bytes)
    for name, expected in manifest["training_code_sha256"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"TRAINING_CODE_HASH_CHANGED:{name}")
    for relative, key in (("data/panel.parquet", "panel_sha256"),
                          ("data/risk_panel.parquet", "risk_panel_sha256"),
                          ("data/prices.parquet", "prices_sha256")):
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != manifest[key]:
            raise RuntimeError(f"TRAINING_INPUT_HASH_CHANGED:{relative}")
    fold_eligibility = prefit_eligibility()
    path = ROOT / "training_run.json"
    if resume_risk:
        if not path.exists():
            raise RuntimeError("RECOVERY_RECEIPT_ABSENT")
        old_bytes = path.read_bytes()
        record = json.loads(old_bytes)
        previous_hash = os.environ.get("R1_PREVIOUS_RUN_SHA256")
        previous_manifest = os.environ.get("R1_PREVIOUS_MANIFEST_SHA256")
        steps = record.get("steps", [])
        if (not previous_hash or hashlib.sha256(old_bytes).hexdigest() != previous_hash
                or record.get("input_manifest_sha256") != previous_manifest
                or record.get("status") != "FAILED"
                or record.get("error") != "TRAINING_STEP_FAILED:risk_aux.py:1"
                or [item["script"] for item in steps] != list(STEPS[:3])
                or [item["exit_code"] for item in steps] != [0, 0, 1]):
            raise RuntimeError("RECOVERY_RECEIPT_MISMATCH")
        supervised = json.loads((ROOT / "supervised_manifest.json").read_text())
        fit_log = ROOT / "fit_supervised.log"
        if (supervised.get("fit_count") != 27
                or sum(line.startswith("FIT ") for line in fit_log.open()) != 27
                or not (ROOT / "pre2026_oof.parquet").is_file()):
            raise RuntimeError("RECOVERY_SUPERVISED_INCOMPLETE")
        for name, key in (("pre2026_oof.parquet", "oof_sha256"),
                          ("supervised_trials.csv", "trials_sha256")):
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != supervised[key]:
                raise RuntimeError("RECOVERY_SUPERVISED_HASH_MISMATCH")
        for artifact in supervised["artifacts"].values():
            if hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
                raise RuntimeError("RECOVERY_SUPERVISED_HASH_MISMATCH")
        record["recovery"] = {"prior_run_sha256": previous_hash,
                              "prior_manifest_sha256": previous_manifest,
                              "reason": "rank missing from risk-fit panel in validation diagnostic",
                              "resume_step": "risk_aux.py",
                              "resumed_utc": datetime.now(timezone.utc).isoformat()}
        record["input_manifest_sha256"] = actual_manifest
        record["fold_eligibility"] = fold_eligibility
        record["status"] = "RUNNING"
        record.pop("error", None)
        remaining = STEPS[2:]
    else:
        record = {"status": "RUNNING", "started_utc": datetime.now(timezone.utc).isoformat(),
                  "steps": [], "input_manifest_sha256": actual_manifest,
                  "fold_eligibility": fold_eligibility}
        remaining = STEPS
    path.write_text(json.dumps(record, indent=2) + "\n")
    try:
        for script in remaining:
            started = datetime.now(timezone.utc).isoformat()
            log = ROOT / f"{Path(script).stem}.log"
            with log.open("w", encoding="utf-8") as stream:
                process = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT,
                                         stdout=stream, stderr=subprocess.STDOUT, check=False)
            record["steps"].append({"script": script, "started_utc": started,
                                    "ended_utc": datetime.now(timezone.utc).isoformat(),
                                    "exit_code": process.returncode, "log": log.name})
            path.write_text(json.dumps(record, indent=2) + "\n")
            if process.returncode:
                raise RuntimeError(f"TRAINING_STEP_FAILED:{script}:{process.returncode}")
        record["status"] = "PRE2026_TRAINING_COMPLETE_AWAITING_INDEPENDENT_REVIEW"
    except BaseException as exc:
        record["status"] = "FAILED"
        record["error"] = str(exc)
        raise
    finally:
        supervised_log = ROOT / "fit_supervised.log"
        risk_log = ROOT / "risk_aux.log"
        rl_updates = ROOT / "rl_artifacts" / "updates.jsonl"
        record["observed_work"] = {
            "supervised_fit_log_lines": sum(line.startswith("FIT ") for line in supervised_log.open(
                encoding="utf-8", errors="replace")) if supervised_log.exists() else 0,
            "risk_bundle_fit_log_lines": sum(line.startswith("FITTED ") for line in risk_log.open(
                encoding="utf-8", errors="replace")) if risk_log.exists() else 0,
            "rl_parameter_updates_logged": sum(1 for _ in rl_updates.open(encoding="utf-8"))
            if rl_updates.exists() else 0,
        }
        record["input_integrity_at_exit"] = {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == manifest[key]
            for relative, key in (("data/panel.parquet", "panel_sha256"),
                                  ("data/risk_panel.parquet", "risk_panel_sha256"),
                                  ("data/prices.parquet", "prices_sha256"))}
        record["code_integrity_at_exit"] = all(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
            for name, expected in manifest["training_code_sha256"].items())
        record["ended_utc"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
