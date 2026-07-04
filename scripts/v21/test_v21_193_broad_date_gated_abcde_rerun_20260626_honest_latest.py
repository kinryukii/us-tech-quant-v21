#!/usr/bin/env python
"""Validation for V21.193 broad-date gated ABCDE rerun."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.py"
RUNNER = ROOT / "scripts/v21/run_v21_193_broad_date_gated_abcde_rerun_20260626_honest_latest.ps1"
OUT = ROOT / "outputs/v21/V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST"
SUMMARY = OUT / "v21_193_summary.json"
REQUIRED = [
    "broad_date_gate_consumption_audit.csv",
    "canonical_date_status_audit.csv",
    "abcde_source_resolution_audit_20260626.csv",
    "blocked_newer_dates_audit.csv",
    "v21_193_summary.json",
    "V21.193_broad_date_gated_abcde_rerun_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_193", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.193_BROAD_DATE_GATED_ABCDE_RERUN_20260626_HONEST_LATEST"
    assert module.EXPECTED_TARGET == "2026-06-26"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "latest_broad_date_gate.json" in text
    assert "refuse_raw_max_date" in text
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text


def test_outputs_if_run():
    if not SUMMARY.is_file():
        return
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["target_rerun_date"] == "2026-06-26"
    assert summary["final_status"] in {
        "PASS_V21_193_HONEST_LATEST_20260626_ABCDE_READY",
        "FAIL_V21_193_MIXED_DATE_ABCDE_OUTPUT",
        "FAIL_V21_193_BROAD_DATE_GATE_MISSING",
        "FAIL_V21_193_TARGET_DATE_NOT_BROAD_ELIGIBLE",
    }
    if summary["abcde_rerun_succeeded"]:
        for name in [
            "a1_honest_latest_20260626_ranking.csv",
            "b_honest_latest_20260626_ranking.csv",
            "c_honest_latest_20260626_ranking.csv",
            "d_honest_latest_20260626_ranking.csv",
            "e_r1_honest_latest_20260626_ranking.csv",
            "abcde_top20_summary_honest_latest_20260626.csv",
            "abcde_top50_summary_honest_latest_20260626.csv",
            "abcde_overlap_top20_matrix_honest_latest_20260626.csv",
            "abcde_overlap_top50_matrix_honest_latest_20260626.csv",
            "abcde_rank_diff_summary_honest_latest_20260626.csv",
            "abcde_same_date_alignment_audit_honest_latest_20260626.csv",
        ]:
            assert (OUT / name).is_file(), name
        matrix = pd.read_csv(OUT / "abcde_overlap_top20_matrix_honest_latest_20260626.csv").set_index("strategy_id")
        for label in ["A1", "B", "C", "D", "E_R1"]:
            assert int(matrix.loc[label, label]) == 20


def test_same_date_audit_if_success():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if not summary["abcde_rerun_succeeded"]:
        return
    audit = pd.read_csv(OUT / "abcde_same_date_alignment_audit_honest_latest_20260626.csv")
    assert set(audit["strategy_id"]) == {"A1", "B", "C", "D", "E_R1"}
    assert audit["same_date_comparable"].astype(str).str.upper().isin(["TRUE", "1"]).all()
    assert set(audit["resolved_date"].astype(str)) == {"2026-06-26"}
