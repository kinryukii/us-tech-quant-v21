#!/usr/bin/env python
"""Tests for V20.214 operator-approved historical input fill/cache build."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
YAHOO_CACHE = ROOT / "inputs" / "v20" / "equity_curve" / "yahoo_cache" / "v20_214"

OUTPUTS = [
    CONSOLIDATION / "V20_214_OPERATOR_APPROVAL_CAPTURE.csv",
    CONSOLIDATION / "V20_214_PRICE_ACQUISITION_PLAN.csv",
    CONSOLIDATION / "V20_214_YAHOO_DOWNLOAD_STATUS.csv",
    CONSOLIDATION / "V20_214_HISTORICAL_PRICE_CACHE_CERTIFICATION.csv",
    CONSOLIDATION / "V20_214_MEMBERSHIP_RECONSTRUCTION_SOURCE_AUDIT.csv",
    CONSOLIDATION / "V20_214_MEMBERSHIP_RECONSTRUCTION_PLAN.csv",
    CONSOLIDATION / "V20_214_BASELINE_TOP20_MEMBERSHIP_STAGED.csv",
    CONSOLIDATION / "V20_214_SHADOW_TOP20_MEMBERSHIP_STAGED.csv",
    CONSOLIDATION / "V20_214_MEMBERSHIP_STAGING_CERTIFICATION.csv",
    CONSOLIDATION / "V20_214_EQUITY_CURVE_RETRY_READINESS.csv",
    CONSOLIDATION / "V20_214_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_214_OPERATOR_APPROVED_HISTORICAL_PRICE_AND_MEMBERSHIP_INPUT_FILL_OR_YAHOO_CACHE_BUILD_REPORT.md",
]
CACHE_OUTPUTS = [
    YAHOO_CACHE / "V20_214_YAHOO_TICKER_DAILY_PRICE_CACHE.csv",
    YAHOO_CACHE / "V20_214_YAHOO_BENCHMARK_DAILY_PRICE_CACHE.csv",
    YAHOO_CACHE / "V20_214_YAHOO_DOWNLOAD_FAILURES.csv",
    YAHOO_CACHE / "V20_214_YAHOO_CACHE_HASH_LEDGER.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_outputs() -> None:
    for path in OUTPUTS + CACHE_OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"
        if path.suffix.lower() == ".csv":
            rows = read_csv(path)
            if path.name.endswith("_DAILY_PRICE_CACHE.csv"):
                assert rows == [] or isinstance(rows, list)
            else:
                assert rows, f"output has no rows {path}"


def test_v20_214_default_plan_only() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=PASS_V20_214_OPERATOR_APPROVAL_REQUIRED_FOR_YAHOO_CACHE_BUILD_PLAN_READY" in result.stdout
    assert "YAHOO_DOWNLOAD_ATTEMPTED=FALSE" in result.stdout
    assert "OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout
    assert "TRADE_ACTION_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout
    assert_outputs()

    gate = read_csv(CONSOLIDATION / "V20_214_NEXT_STAGE_GATE.csv")[0]
    assert gate["yahoo_download_approved"] == "FALSE"
    assert gate["yahoo_download_attempted"] == "FALSE"
    assert gate["price_cache_created"] == "FALSE"
    assert gate["official_promotion_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["weight_mutated"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"

    retry = read_csv(CONSOLIDATION / "V20_214_EQUITY_CURVE_RETRY_READINESS.csv")[0]
    baseline_ready = retry["baseline_membership_certified"] == "TRUE" and retry["qqq_daily_path_certified"] == "TRUE" and retry["spy_daily_path_certified"] == "TRUE"
    assert (retry["baseline_equity_curve_retry_ready"] == "TRUE") == baseline_ready

    source_audit = read_csv(CONSOLIDATION / "V20_214_MEMBERSHIP_RECONSTRUCTION_SOURCE_AUDIT.csv")
    forbidden_sources = [
        row for row in source_audit
        if row["aggregate_forward_window_or_forbidden_source"] == "TRUE" or row["current_only_file"] == "TRUE"
    ]
    assert all(row["eligible_for_reconstruction"] == "FALSE" for row in forbidden_sources)

    membership = read_csv(CONSOLIDATION / "V20_214_MEMBERSHIP_STAGING_CERTIFICATION.csv")
    cert_map = {row["membership_type"]: row["certified"] for row in membership}
    if cert_map["BASELINE_TOP20"] == "FALSE":
        staged = read_csv(CONSOLIDATION / "V20_214_BASELINE_TOP20_MEMBERSHIP_STAGED.csv")
        assert staged[0]["reconstruction_method"] == "NOT_RECONSTRUCTED"
        assert staged[0]["as_of_date"] == ""
    if cert_map["SHADOW_TOP20"] == "FALSE":
        staged = read_csv(CONSOLIDATION / "V20_214_SHADOW_TOP20_MEMBERSHIP_STAGED.csv")
        assert staged[0]["reconstruction_method"] == "NOT_RECONSTRUCTED"
        assert staged[0]["as_of_date"] == ""

    price_cert = read_csv(CONSOLIDATION / "V20_214_HISTORICAL_PRICE_CACHE_CERTIFICATION.csv")
    for row in price_cert:
        if row["certified_usable_for_120d_equity_curve"] == "TRUE":
            assert int(float(row["distinct_trading_dates"])) >= 121

    plan = read_csv(CONSOLIDATION / "V20_214_PRICE_ACQUISITION_PLAN.csv")
    assert {"QQQ", "SPY", "SOXX", "SMH"}.issubset({row["ticker"] for row in plan})

    created_names = [path.name.lower() for path in CONSOLIDATION.glob("V20_214*")]
    assert not any("drawdown" in name or "performance_metrics" in name for name in created_names)

    wrapper_text = WRAPPER.read_text(encoding="utf-8")
    default_branch = wrapper_text.split("} else {", 1)[1]
    assert "--operator-approve-yahoo-download" not in default_branch

    report = (READ_CENTER / "V20_214_OPERATOR_APPROVED_HISTORICAL_PRICE_AND_MEMBERSHIP_INPUT_FILL_OR_YAHOO_CACHE_BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "Default execution is plan-only" in report
    assert "Aggregate forward-window tables cannot be used as membership history" in report
    assert "No official recommendation" in report


def test_wrapper_default_plan_only() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "FINAL_STATUS=PASS_V20_214_OPERATOR_APPROVAL_REQUIRED_FOR_YAHOO_CACHE_BUILD_PLAN_READY" in result.stdout
    assert "YAHOO_DOWNLOAD_ATTEMPTED=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_v20_214_default_plan_only()
    test_wrapper_default_plan_only()
    print("PASS test_v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build")
