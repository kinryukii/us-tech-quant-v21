from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_stock_risk_r10_r11_fast_track.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r10_r11_fast_track", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_r10_r6_authoritative_hash_identity() -> None:
    assert MODULE.sha(MODULE.R6_OOF) == MODULE.R6_OOF_EXPECTED
    assert MODULE.R7.R6_TARGET_CONTRACT_ID == MODULE.R6_TARGET_ID_EXPECTED
    assert MODULE.R7.R6_FOLD_CONTRACT_ID == MODULE.R6_FOLD_ID_EXPECTED


def test_r10_no_new_model_fit() -> None:
    if (MODULE.R10_ROOT / "r10_audit.json").exists():
        audit = json.loads((MODULE.R10_ROOT / "r10_audit.json").read_text(encoding="utf-8"))
        assert audit["model_fit_count"] == 0
        assert audit["parameter_search_count"] == 0
        assert audit["threshold_search_count"] == 0
        assert audit["2026_file_read_count"] == 0


def test_r10_closeout_manifest_reproducible() -> None:
    if (MODULE.R10_ROOT / "r10_freeze_manifest.json").exists():
        manifest = json.loads((MODULE.R10_ROOT / "r10_freeze_manifest.json").read_text(encoding="utf-8"))
        assert MODULE.R1.canonical_hash(manifest["freeze_payload"]) == manifest["freeze_hash"]


def test_r11_preregistration_precedes_2026_outcome_read() -> None:
    if (MODULE.R11_ROOT / "r11_run_manifest.json").exists():
        run = json.loads((MODULE.R11_ROOT / "r11_run_manifest.json").read_text(encoding="utf-8"))
        assert pd.Timestamp(run["first_2026_outcome_read_timestamp"]) > pd.Timestamp(run["preregistration_timestamp"])
        assert run["2026_OUTCOME_READ_AFTER_PREREGISTRATION"] == "PASS"


def test_r11_no_2026_training() -> None:
    if (MODULE.R11_ROOT / "r11_summary.json").exists():
        summary = json.loads((MODULE.R11_ROOT / "r11_summary.json").read_text(encoding="utf-8"))
        assert summary["2026_MODEL_FIT_ROWS"] == 0
        assert summary["R11_PRE2026_DEPLOYMENT_MODEL_FIT_COUNT"] == 1


def test_r11_exact_frozen_r6_model_contract() -> None:
    if (MODULE.R11_ROOT / "r6_frozen_deploy_r1.joblib").exists():
        artifact = joblib.load(MODULE.R11_ROOT / "r6_frozen_deploy_r1.joblib")
        spec = artifact["spec"]
        candidate = next(x for x in MODULE.R6.CANDIDATES if x.candidate_id == MODULE.R6_REFERENCE_MODEL)
        assert spec["candidate_params"] == candidate.params
        assert spec["features"] == list(MODULE.R3.FEATURES)
        assert spec["2026_model_fit_rows"] == 0


def test_r11_exact_frozen_r6_target_contract() -> None:
    if (MODULE.R11_ROOT / "r11_preregistered_evaluation_contract.json").exists():
        contract = json.loads((MODULE.R11_ROOT / "r11_preregistered_evaluation_contract.json").read_text(encoding="utf-8"))
        payload = contract["preregistered_payload"]
        assert payload["r6_target_contract_id"] == MODULE.R6_TARGET_ID_EXPECTED
        assert payload["target"]["horizon_sessions"] == 5
        assert "MAE>=frozen pre2026 Q90" in payload["target"]["definition"]


def test_r11_only_mature_2026_labels() -> None:
    path = MODULE.R11_ROOT / "r11_2026_r6_predictions.parquet"
    if path.exists():
        frame = pd.read_parquet(path)
        assert frame.target_end_date.notna().all()
        assert frame.bad_target.notna().all()
        assert frame.groupby(["signal_date", "ticker"]).size().eq(1).all()


def test_r11_pre2026_percentile_reference_only() -> None:
    if (MODULE.R11_ROOT / "r6_frozen_deploy_r1.joblib").exists():
        artifact = joblib.load(MODULE.R11_ROOT / "r6_frozen_deploy_r1.joblib")
        assert artifact["spec"]["training_end_date"] < "2026-01-01"
        assert artifact["spec"]["reference_score_count"] == artifact["spec"]["training_rows"]
        assert np.all(np.diff(artifact["reference_scores_sorted"]) >= 0)


def test_r11_no_2026_threshold_search() -> None:
    if (MODULE.R11_ROOT / "r11_summary.json").exists():
        summary = json.loads((MODULE.R11_ROOT / "r11_summary.json").read_text(encoding="utf-8"))
        assert summary["2026_THRESHOLD_SEARCH_COUNT"] == 0
        assert summary["2026_TARGET_SEARCH_COUNT"] == 0


def test_r11_no_2026_parameter_search() -> None:
    if (MODULE.R11_ROOT / "r11_summary.json").exists():
        summary = json.loads((MODULE.R11_ROOT / "r11_summary.json").read_text(encoding="utf-8"))
        assert summary["2026_PARAMETER_SEARCH_COUNT"] == 0
        assert summary["2026_FEATURE_SELECTION_COUNT"] == 0
        assert summary["2026_MODEL_SELECTION_COUNT"] == 0


def test_r11_prediction_reproducibility() -> None:
    if (MODULE.R11_ROOT / "r11_summary.json").exists():
        summary = json.loads((MODULE.R11_ROOT / "r11_summary.json").read_text(encoding="utf-8"))
        assert summary["REPRODUCIBILITY_STATUS"] == "PASS_EXACT_SAME_ARTIFACT_DOUBLE_PREDICT"
