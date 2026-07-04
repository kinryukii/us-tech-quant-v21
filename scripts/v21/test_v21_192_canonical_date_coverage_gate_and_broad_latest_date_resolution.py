#!/usr/bin/env python
"""Validation for V21.192 canonical broad date gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.py"
RUNNER = ROOT / "scripts/v21/run_v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.ps1"
OUT = ROOT / "outputs/v21/V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION"
SUMMARY = OUT / "v21_192_summary.json"
REQUIRED = [
    "canonical_date_coverage_audit.csv",
    "latest_broad_date_gate.json",
    "feature_latest_date_audit.csv",
    "narrow_tail_rows_after_broad_latest_date.csv",
    "canonical_without_narrow_tail_candidate.csv",
    "narrow_tail_quarantine_apply_audit.csv",
    "v21_192_summary.json",
    "V21.192_canonical_date_coverage_gate_report.txt",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_192", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION"
    assert module.APPLY_ENV == "V21_192_APPLY_NARROW_TAIL_QUARANTINE"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "broad_price_date_eligible" in text
    assert "latest_broad_date_gate.json" in text
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text


def test_outputs_if_run():
    if not SUMMARY.is_file():
        return
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    gate = json.loads((OUT / "latest_broad_date_gate.json").read_text(encoding="utf-8"))
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert gate["abcd_honest_latest_date"] == summary["abcd_honest_latest_date"]
    assert summary["final_status"] in {
        "PARTIAL_PASS_V21_192_NARROW_TAIL_DETECTED_BROAD_DATE_RESOLVED",
        "PASS_V21_192_CANONICAL_BROAD_DATE_READY",
        "PASS_V21_192_NARROW_TAIL_QUARANTINED",
        "PARTIAL_PASS_V21_192_BROAD_DATE_RESOLVED_FEATURE_DATE_LAGS",
    }
    audit = pd.read_csv(OUT / "canonical_date_coverage_audit.csv", low_memory=False)
    assert "broad_price_date_eligible" in audit.columns
    broad = audit[audit["broad_price_date_eligible"].astype(str).str.upper().isin(["TRUE", "1"])]
    assert not broad.empty


def test_candidate_integrity_if_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    candidate = pd.read_csv(OUT / "canonical_without_narrow_tail_candidate.csv", low_memory=False)
    assert len(candidate) > 0
    sym = "symbol" if "symbol" in candidate.columns else "ticker"
    assert not candidate.duplicated([sym, "date"]).any()
    assert str(candidate["date"].max()) == summary["broad_price_latest_date"]
