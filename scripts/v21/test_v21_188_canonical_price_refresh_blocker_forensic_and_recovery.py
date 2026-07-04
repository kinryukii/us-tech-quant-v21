#!/usr/bin/env python
"""Validation for V21.188 canonical price refresh blocker recovery."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py"
RUNNER = ROOT / "scripts/v21/run_v21_188_canonical_price_refresh_blocker_forensic_and_recovery.ps1"
OUT = ROOT / "outputs/v21/V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY"
SUMMARY = OUT / "v21_188_summary.json"
EXPECTED_DATE = "2026-06-30"
REQUIRED = [
    "price_panel_recovery_inventory.csv",
    "current_canonical_audit.csv",
    "best_recoverable_panel_audit.csv",
    "v20_refresh_blocker_diagnostic.json",
    "candidate_repaired_canonical_ohlcv.csv",
    "candidate_repaired_panel_audit.csv",
    "missing_trading_days_report.csv",
    "stale_or_missing_ticker_report.csv",
    "canonical_apply_audit.csv",
    "v21_188_summary.json",
    "V21.188_canonical_price_refresh_blocker_forensic_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_188", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protected_outputs_modified() -> bool:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    allowed_prefix = "?? outputs/v21/V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY/"
    allowed_scripts = {
        "?? scripts/v21/v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py",
        "?? scripts/v21/test_v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py",
        "?? scripts/v21/run_v21_188_canonical_price_refresh_blocker_forensic_and_recovery.ps1",
    }
    for line in completed.stdout.splitlines():
        normalized = line.replace("\\", "/")
        if normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY"
    assert module.EXPECTED_LATEST_COMPLETED_TRADING_DATE == EXPECTED_DATE
    assert module.APPLY_ENV == "V21_188_APPLY_CANONICAL_PRICE_RECOVERY"
    assert module.OUT == OUT
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "REFUSED_CANDIDATE_EMPTY_LOWER_DATE_OR_COVERAGE_REGRESSION" in text
    assert "canonical_restored_after_failed_apply" in text
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text


def test_outputs_if_stage_has_run():
    if not SUMMARY.is_file():
        return
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["expected_latest_completed_trading_date"] == EXPECTED_DATE
    assert summary["candidate_panel_created"] is True
    assert summary["candidate_panel_rows"] > 0
    assert summary["candidate_panel_latest_date"] >= summary["current_canonical_latest_date"]
    assert summary["candidate_panel_rows"] >= summary["current_canonical_rows"] or summary["candidate_panel_latest_date"] > summary["current_canonical_latest_date"]
    assert summary["final_status"] in {
        "PASS_V21_188_CANDIDATE_PRICE_PANEL_RECOVERED",
        "PARTIAL_PASS_V21_188_LOCAL_PRICE_PANEL_PARTIALLY_RECOVERED",
        "FAIL_V21_188_PRICE_REFRESH_BLOCKED_NO_SAFE_RECOVERY",
    }
    assert summary["canonical_apply_requested"] is False
    assert summary["canonical_apply_succeeded"] is False
    assert summary["protected_outputs_modified"] is False


def test_inventory_and_candidate_schema_if_stage_has_run():
    if not SUMMARY.is_file():
        return
    inventory = pd.read_csv(OUT / "price_panel_recovery_inventory.csv", low_memory=False)
    candidate = pd.read_csv(OUT / "candidate_repaired_canonical_ohlcv.csv", low_memory=False)
    audit = pd.read_csv(OUT / "candidate_repaired_panel_audit.csv", low_memory=False).iloc[0]
    required_cols = {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"}
    assert required_cols.issubset(candidate.columns)
    assert len(candidate) == int(audit["row_count"])
    assert not candidate.duplicated(["symbol", "date"]).any()
    assert inventory["valid_ohlcv_schema"].astype(str).str.upper().isin(["TRUE", "1"]).any()
    diagnostic = json.loads((OUT / "v20_refresh_blocker_diagnostic.json").read_text(encoding="utf-8"))
    assert diagnostic["v20_refresh_returned_zero_rows"] is True
    assert diagnostic["universe_input_empty"] is False


def test_no_protected_outputs_modified():
    if SUMMARY.is_file():
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        assert summary["protected_outputs_modified"] is False
    assert not protected_outputs_modified()
