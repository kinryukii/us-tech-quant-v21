#!/usr/bin/env python
"""Validation for V21.191 latest-available ABCDE rerun and manual import scaffold."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py"
RUNNER = ROOT / "scripts/v21/run_v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.ps1"
OUT = ROOT / "outputs/v21/V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD"
OUT_R1 = ROOT / "outputs/v21/V21.191_R1_ABCD_FEATURE_DATE_ALIGNMENT_REPAIR"
SUMMARY = OUT / "v21_191_summary.json"
SUMMARY_R1 = OUT_R1 / "v21_191_r1_summary.json"
REQUIRED_ALWAYS = [
    "canonical_before_v21_191_audit.csv",
    "manual_20260630_import_status.csv",
    "manual_20260630_schema_audit.csv",
    "manual_20260630_validation_errors.csv",
    "manual_20260630_candidate_audit.csv",
    "manual_20260630_apply_audit.csv",
    "v21_191_summary.json",
    "V21.191_latest_available_abcde_and_manual_import_scaffold_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_191", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD"
    assert module.LATEST_AVAILABLE_DATE == "2026-06-29"
    assert module.EXPECTED_MISSING_DATE == "2026-06-30"
    assert module.APPLY_ENV == "V21_191_APPLY_MANUAL_20260630_IMPORT"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text
    assert "fillna(out[\"close\"])" in text
    assert "manual_20260630_validation_errors.csv" in text


def test_outputs_if_run():
    if not SUMMARY.is_file():
        return
    for name in REQUIRED_ALWAYS:
        assert (OUT / name).is_file(), name
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["latest_available_rerun_date"] == "2026-06-29"
    assert summary["expected_missing_date"] == "2026-06-30"
    assert summary["final_status"] in {
        "PARTIAL_PASS_V21_191_20260629_ABCDE_READY_WAIT_MANUAL_20260630",
        "FAIL_V21_191_ABCDE_20260629_RERUN_FAILED",
        "PARTIAL_PASS_V21_191_MANUAL_20260630_CANDIDATE_READY_NOT_APPLIED",
        "PASS_V21_191_MANUAL_20260630_IMPORTED",
    }
    if summary["abcde_rerun_succeeded"]:
        for name in [
            "a1_latest_available_20260629_ranking.csv",
            "b_latest_available_20260629_ranking.csv",
            "c_latest_available_20260629_ranking.csv",
            "d_latest_available_20260629_ranking.csv",
            "e_r1_latest_available_20260629_ranking.csv",
            "abcde_top20_summary_20260629.csv",
            "abcde_top50_summary_20260629.csv",
            "abcde_overlap_top20_matrix_20260629.csv",
            "abcde_overlap_top50_matrix_20260629.csv",
            "abcde_rank_diff_summary_20260629.csv",
            "abcde_same_date_alignment_audit_20260629.csv",
        ]:
            assert (OUT / name).is_file(), name
        matrix = pd.read_csv(OUT / "abcde_overlap_top20_matrix_20260629.csv").set_index("strategy_id")
        for label in ["A1", "B", "C", "D", "E_R1"]:
            assert int(matrix.loc[label, label]) == 20
    if SUMMARY_R1.is_file():
        s = json.loads(SUMMARY_R1.read_text(encoding="utf-8"))
        assert s["research_only"] is True
        assert s["official_adoption_allowed"] is False
        assert s["broker_action_allowed"] is False
        assert s["target_rerun_date"] == "2026-06-29"
        assert s["canonical_latest_date"] >= "2026-06-29"
        assert s["final_status"] in {
            "PASS_V21_191_R1_20260629_ABCDE_SAME_DATE_READY",
            "PARTIAL_PASS_V21_191_R1_UPSTREAM_ABCD_REBUILD_REQUIRED",
            "FAIL_V21_191_R1_ABCD_STALE_DATE_ROOT_CAUSE_UNKNOWN",
            "FAIL_V21_191_R1_MIXED_DATE_ABCDE_OUTPUT",
        }
        for name in [
            "canonical_audit_20260629.csv",
            "abcd_source_resolution_audit.csv",
            "stale_feature_source_diagnostic.csv",
            "upstream_feature_builder_inventory.csv",
            "abcde_same_date_alignment_audit_20260629_r1.csv",
            "v21_191_r1_summary.json",
            "V21.191_R1_abcd_feature_date_alignment_repair_report.txt",
        ]:
            assert (OUT_R1 / name).is_file(), name


def test_no_protected_official_broker_outputs_modified():
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    allowed_prefix = "?? outputs/v21/V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD/"
    allowed_scripts = {
        "?? scripts/v21/v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py",
        "?? scripts/v21/test_v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py",
        "?? scripts/v21/run_v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.ps1",
    }
    for line in completed.stdout.splitlines():
        normalized = line.replace("\\", "/")
        if normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        assert not (
            lowered.startswith((" m outputs/", " d outputs/", "?? outputs/"))
            and ("official" in lowered or "broker" in lowered or "protected" in lowered)
        )
