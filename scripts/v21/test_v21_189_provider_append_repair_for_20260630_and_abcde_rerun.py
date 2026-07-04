#!/usr/bin/env python
"""Validation for V21.189 provider append repair and ABCDE rerun."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_189_provider_append_repair_for_20260630_and_abcde_rerun.py"
RUNNER = ROOT / "scripts/v21/run_v21_189_provider_append_repair_for_20260630_and_abcde_rerun.ps1"
OUT = ROOT / "outputs/v21/V21.189_PROVIDER_APPEND_REPAIR_FOR_20260630_AND_ABCDE_RERUN"
SUMMARY = OUT / "v21_189_summary.json"
EXPECTED = "2026-06-30"
REQUIRED = [
    "canonical_before_append_audit.csv",
    "provider_fetch_diagnostics.csv",
    "provider_failed_tickers.csv",
    "provider_success_tickers.csv",
    "candidate_20260630_append_rows.csv",
    "candidate_canonical_through_20260630.csv",
    "candidate_canonical_audit.csv",
    "canonical_apply_audit.csv",
    "v21_189_summary.json",
    "V21.189_provider_append_repair_and_abcde_rerun_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_189", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.189_PROVIDER_APPEND_REPAIR_FOR_20260630_AND_ABCDE_RERUN"
    assert module.EXPECTED_DATE == EXPECTED
    assert module.APPLY_ENV == "V21_189_APPLY_20260630_APPEND"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "REFUSED_INVALID_CANDIDATE" in text
    assert "broker_action_allowed" in text
    assert "official_adoption_allowed" in text


def test_outputs_if_run():
    if not SUMMARY.is_file():
        return
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["expected_latest_completed_trading_date"] == EXPECTED
    assert summary["final_status"] in {
        "PASS_V21_189_20260630_ABCDE_RERUN_READY",
        "PARTIAL_PASS_V21_189_20260630_CANDIDATE_READY_NOT_APPLIED",
        "PARTIAL_PASS_V21_189_PROVIDER_STILL_BLOCKED_WAIT_DATA",
        "FAIL_V21_189_CANONICAL_RECOVERY_NOT_APPLIED",
    }
    assert summary["canonical_apply_succeeded"] in {True, False}


def test_candidate_integrity_if_run():
    if not SUMMARY.is_file():
        return
    candidate = pd.read_csv(OUT / "candidate_canonical_through_20260630.csv", low_memory=False)
    audit = pd.read_csv(OUT / "candidate_canonical_audit.csv", low_memory=False).iloc[0]
    assert len(candidate) == int(audit["row_count"])
    if len(candidate):
        assert not candidate.duplicated(["symbol", "date"]).any()
        assert {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"}.issubset(candidate.columns)
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if summary["abcde_rerun_succeeded"]:
        for name in ["a1_latest_ranking.csv", "b_latest_ranking.csv", "c_latest_ranking.csv", "d_latest_ranking.csv", "e_r1_latest_ranking.csv", "abcde_top20_summary.csv", "abcde_overlap_top20_matrix.csv"]:
            assert (OUT / name).is_file(), name
