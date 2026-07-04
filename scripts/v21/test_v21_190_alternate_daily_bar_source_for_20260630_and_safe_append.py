#!/usr/bin/env python
"""Validation for V21.190 alternate 2026-06-30 daily bar append."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_190_alternate_daily_bar_source_for_20260630_and_safe_append.py"
RUNNER = ROOT / "scripts/v21/run_v21_190_alternate_daily_bar_source_for_20260630_and_safe_append.ps1"
OUT = ROOT / "outputs/v21/V21.190_ALTERNATE_DAILY_BAR_SOURCE_FOR_20260630_AND_SAFE_APPEND"
SUMMARY = OUT / "v21_190_summary.json"
REQUIRED = [
    "canonical_before_v21_190_audit.csv",
    "local_20260630_price_file_inventory.csv",
    "provider_mode_diagnostics.csv",
    "provider_success_rows_20260630.csv",
    "provider_failed_tickers_20260630.csv",
    "candidate_append_rows_20260630.csv",
    "candidate_canonical_through_20260630.csv",
    "candidate_canonical_audit.csv",
    "canonical_apply_audit.csv",
    "yfinance_cache_diagnostic.json",
    "provider_healthcheck_20260630.csv",
    "provider_exception_trace_sample.txt",
    "v21_190_summary.json",
    "V21.190_alternate_daily_bar_source_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_190", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.190_ALTERNATE_DAILY_BAR_SOURCE_FOR_20260630_AND_SAFE_APPEND"
    assert module.TARGET_DATE == "2026-06-30"
    assert module.APPLY_ENV == "V21_190_APPLY_20260630_APPEND"
    assert module.CACHE_DIR.name == "yfinance_cache"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "REFUSED_INVALID_CANDIDATE" in text
    assert "VERIFY_FAILED_RESTORED_BACKUP" in text
    assert "set_tz_cache_location" in text
    assert "provider_healthcheck_20260630.csv" in text
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text


def test_outputs_if_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if not summary.get("r1_patch_applied"):
        return
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["expected_append_date"] == "2026-06-30"
    assert summary["final_status"] in {
        "PARTIAL_PASS_V21_190_20260630_CANDIDATE_READY_NOT_APPLIED",
        "PASS_V21_190_CANONICAL_APPENDED_TO_20260630",
        "PARTIAL_PASS_V21_190_NO_20260630_DATA_AVAILABLE",
        "PARTIAL_PASS_V21_190_R1_20260630_CANDIDATE_READY_NOT_APPLIED",
        "PASS_V21_190_R1_CANONICAL_APPENDED_TO_20260630",
        "FAIL_V21_190_R1_YFINANCE_CACHE_OR_SQLITE_FAILURE",
        "PARTIAL_PASS_V21_190_R1_PROVIDER_NO_20260630_DATA",
        "FAIL_V21_190_CANDIDATE_VALIDATION_FAILED",
    }
    assert summary["r1_patch_applied"] is True
    for key in [
        "yfinance_cache_dir",
        "cache_dir_exists",
        "cache_dir_writable",
        "cache_probe_file_created",
        "yfinance_cache_location_set",
        "provider_healthcheck_attempted",
        "provider_healthcheck_success_count",
        "provider_healthcheck_failed_count",
        "operational_error_count",
        "first_operational_error_message",
    ]:
        assert key in summary
    assert isinstance(summary["provider_modes_attempted"], list)
    assert summary["canonical_apply_succeeded"] in {True, False}


def test_candidate_validation_if_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if not summary.get("r1_patch_applied"):
        return
    candidate = pd.read_csv(OUT / "candidate_canonical_through_20260630.csv", low_memory=False)
    audit = pd.read_csv(OUT / "candidate_canonical_audit.csv", low_memory=False).iloc[0]
    assert len(candidate) == int(audit["row_count"])
    if len(candidate):
        assert not candidate.duplicated(["symbol", "date"]).any()
        assert {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"}.issubset(candidate.columns)
    if summary["candidate_panel_valid"]:
        assert summary["candidate_panel_latest_date"] == "2026-06-30"
        assert summary["append_rows_created"] > 0
        assert summary["append_ticker_coverage_ratio"] >= 0.80
        assert int(audit["zero_or_negative_close_rows"]) == 0
    health = pd.read_csv(OUT / "provider_healthcheck_20260630.csv", low_memory=False)
    assert set(["QQQ", "AAPL", "MU", "AMAT"]).issubset(set(health["ticker"]))
