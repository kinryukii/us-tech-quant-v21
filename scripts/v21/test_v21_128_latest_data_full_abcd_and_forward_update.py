#!/usr/bin/env python
"""Validation for V21.128 latest-data ABCD and forward update."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
SUMMARY = OUT / "V21.128_summary.json"
EXPECTED_MIN_DATE = "2026-06-26"
STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def git_status_lines() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_outputs_modified() -> bool:
    allowed_prefix = "?? outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/"
    allowed_scripts = {
        "?? scripts/v21/v21_128_latest_data_full_abcd_and_forward_update.py",
        "?? scripts/v21/test_v21_128_latest_data_full_abcd_and_forward_update.py",
    }
    for line in git_status_lines():
        normalized = line.replace("\\", "/")
        if normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered
        ):
            return True
    return False


def main() -> None:
    assert_true(SUMMARY.is_file(), "missing V21.128_summary.json")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert_true(summary["latest_price_date_used"] >= EXPECTED_MIN_DATE, "latest_price_date_used is stale")
    assert_true(summary["latest_price_date_after"] >= EXPECTED_MIN_DATE, "latest_price_date_after is stale")
    assert_true(summary["research_only"] is True, "research_only must be true")
    assert_true(summary["official_adoption_allowed"] is False, "official adoption must be disabled")
    assert_true(summary["broker_action_allowed"] is False, "broker action must be disabled")
    assert_true(summary["protected_outputs_modified"] is False, "summary reports protected output modification")
    assert_true(not protected_outputs_modified(), "git status shows protected official/broker/execution output modification")
    assert_true(summary["D_original_frozen_reference_only"] is True, "D original must remain frozen reference only")
    assert_true(summary["D_R2C_frozen_tracking_only"] is True, "D_R2C must remain frozen tracking only")
    assert_true(summary["no_future_leakage"] is True, "future leakage flag failed")

    for strategy in STRATEGIES:
        path = OUT / f"{strategy}_latest_ranking.csv"
        top20 = OUT / f"{strategy}_top20.csv"
        top50 = OUT / f"{strategy}_top50.csv"
        assert_true(path.is_file(), f"missing ranking: {path.name}")
        assert_true(top20.is_file(), f"missing Top20 ranking: {top20.name}")
        assert_true(top50.is_file(), f"missing Top50 ranking: {top50.name}")
        frame = pd.read_csv(path, low_memory=False)
        assert_true(len(frame) == summary["strategy_counts"][strategy]["rows"], f"row count mismatch for {strategy}")
        eligible = int(frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()) if "eligible_flag" in frame else len(frame)
        excluded = len(frame) - eligible
        assert_true(eligible == summary["strategy_counts"][strategy]["eligible"], f"eligible count mismatch for {strategy}")
        assert_true(excluded == summary["strategy_counts"][strategy]["excluded"], f"excluded count mismatch for {strategy}")
        assert_true(str(frame["latest_price_date"].max()) >= EXPECTED_MIN_DATE, f"{strategy} not generated from refreshed data")
        assert_true(len(pd.read_csv(top20, low_memory=False)) == 20, f"{strategy} Top20 length mismatch")
        assert_true(len(pd.read_csv(top50, low_memory=False)) == 50, f"{strategy} Top50 length mismatch")

    for name in [
        "ABCD_top20_overlap_matrix.csv",
        "ABCD_top50_overlap_matrix.csv",
        "tracking_ledger.csv",
        "V21.128_readable_report.txt",
        "V21.128_compact_report.txt",
    ]:
        assert_true((OUT / name).is_file(), f"missing artifact: {name}")

    report = (OUT / "V21.128_readable_report.txt").read_text(encoding="utf-8")
    assert_true("FINAL_STATUS=" in report, "report missing FINAL_STATUS")
    assert_true("DECISION=" in report, "report missing DECISION")
    assert_true("official_adoption_allowed=false" in report, "report missing official guard")
    assert_true("broker_action_allowed=false" in report, "report missing broker guard")
    print("PASS_V21_128_VALIDATION")


if __name__ == "__main__":
    main()
