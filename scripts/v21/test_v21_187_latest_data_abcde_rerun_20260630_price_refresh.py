#!/usr/bin/env python
"""Validation for V21.187 latest-data ABCDE rerun."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_187_latest_data_abcde_rerun_20260630_price_refresh.py"
RUNNER = ROOT / "scripts/v21/run_v21_187_latest_data_abcde_rerun_20260630_price_refresh.ps1"
OUT = ROOT / "outputs/v21/V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH"
SUMMARY = OUT / "v21_187_summary.json"
EXPECTED_DATE = "2026-06-30"
REQUIRED_OUTPUTS = [
    "a1_latest_ranking.csv",
    "b_latest_ranking.csv",
    "c_latest_ranking.csv",
    "d_latest_ranking.csv",
    "e_r1_latest_ranking.csv",
    "abcde_top20_summary.csv",
    "abcde_top50_summary.csv",
    "abcde_overlap_top20_matrix.csv",
    "abcde_overlap_top50_matrix.csv",
    "abcde_rank_diff_summary.csv",
    "abcde_same_date_alignment_audit.csv",
    "stale_or_missing_ticker_report.csv",
    "forward_maturity_update_summary.csv",
    "v21_187_summary.json",
    "V21.187_latest_data_abcde_rerun_report.txt",
]
STRATEGIES = {"A1", "B", "C", "D", "E_R1"}


def load_module():
    spec = importlib.util.spec_from_file_location("v21_187", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protected_outputs_modified() -> bool:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    allowed_prefixes = (
        "?? outputs/v21/V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH/",
    )
    allowed_scripts = {
        "?? scripts/v21/v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
        "?? scripts/v21/test_v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
        "?? scripts/v21/run_v21_187_latest_data_abcde_rerun_20260630_price_refresh.ps1",
    }
    for line in completed.stdout.splitlines():
        normalized = line.replace("\\", "/")
        if normalized.startswith(allowed_prefixes) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def test_static_contract():
    module = load_module()
    assert module.STAGE == "V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH"
    assert module.EXPECTED_LATEST_COMPLETED_TRADING_DATE == EXPECTED_DATE
    assert module.OUT == OUT
    assert module.REFRESH.name == "v20_199d_approved_historical_price_refresh.py"
    assert RUNNER.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "official_adoption_allowed" in text
    assert "broker_action_allowed" in text
    assert "protected_outputs_modified" in text
    assert "V20_199D_ENABLE_YFINANCE_REFRESH" in text


def test_outputs_if_stage_has_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    for name in REQUIRED_OUTPUTS:
        assert (OUT / name).is_file(), name
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert summary["expected_latest_completed_trading_date"] == EXPECTED_DATE
    assert summary["latest_price_date_used"] <= summary["latest_price_date_after_refresh"]
    assert summary["final_status"] in {
        "PASS_V21_187_LATEST_DATA_ABCDE_RERUN_READY",
        "PARTIAL_PASS_V21_187_WAIT_20260630_DATA",
        "FAIL_V21_187_ABCDE_ALIGNMENT_BROKEN",
    }
    if summary["latest_price_date_used"] >= EXPECTED_DATE and summary["same_date_comparable_all_strategies"]:
        assert summary["final_status"] == "PASS_V21_187_LATEST_DATA_ABCDE_RERUN_READY"
    elif summary["same_date_comparable_all_strategies"]:
        assert summary["final_status"] == "PARTIAL_PASS_V21_187_WAIT_20260630_DATA"


def test_ranking_outputs_if_stage_has_run():
    if not SUMMARY.is_file():
        return
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    mapping = {
        "A1": "a1_latest_ranking.csv",
        "B": "b_latest_ranking.csv",
        "C": "c_latest_ranking.csv",
        "D": "d_latest_ranking.csv",
        "E_R1": "e_r1_latest_ranking.csv",
    }
    for strategy, name in mapping.items():
        frame = pd.read_csv(OUT / name, low_memory=False)
        assert len(frame) >= 50
        assert len(frame.sort_values(["rank", "ticker"]).head(20)) == 20
        assert frame["latest_price_date"].astype(str).max() == summary["latest_price_date_used"]
        assert frame["research_only"].astype(str).str.upper().isin(["TRUE", "1"]).all()
        assert not frame["broker_action_allowed"].astype(str).str.upper().isin(["TRUE", "1"]).any()
        assert not frame["official_adoption_allowed"].astype(str).str.upper().isin(["TRUE", "1"]).any()

    audit = pd.read_csv(OUT / "abcde_same_date_alignment_audit.csv")
    assert set(audit["strategy_id"]) == STRATEGIES
    matrix20 = pd.read_csv(OUT / "abcde_overlap_top20_matrix.csv").set_index("strategy_id")
    matrix50 = pd.read_csv(OUT / "abcde_overlap_top50_matrix.csv").set_index("strategy_id")
    assert set(matrix20.index) == STRATEGIES
    assert set(matrix50.index) == STRATEGIES
    for left in STRATEGIES:
        assert int(matrix20.loc[left, left]) == 20
        assert int(matrix50.loc[left, left]) == 50
        for right in STRATEGIES:
            assert int(matrix20.loc[left, right]) == int(matrix20.loc[right, left])
            assert int(matrix50.loc[left, right]) == int(matrix50.loc[right, left])


def test_no_protected_official_broker_outputs_modified():
    assert not protected_outputs_modified()
