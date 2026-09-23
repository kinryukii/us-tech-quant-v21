#!/usr/bin/env python
"""Tests for V20.213 daily price path source repair or equity curve input staging."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_213_daily_price_path_source_repair_or_equity_curve_input_staging.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_213_daily_price_path_source_repair_or_equity_curve_input_staging.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
INPUT_EC = ROOT / "inputs" / "v20" / "equity_curve"

OUTPUTS = [
    CONSOLIDATION / "V20_213_V20_212_BLOCKER_INTAKE.csv",
    CONSOLIDATION / "V20_213_MEMBERSHIP_SOURCE_DISCOVERY.csv",
    CONSOLIDATION / "V20_213_DAILY_PRICE_SOURCE_DISCOVERY.csv",
    CONSOLIDATION / "V20_213_EQUITY_CURVE_REQUIRED_INPUT_SCHEMA.csv",
    CONSOLIDATION / "V20_213_EQUITY_CURVE_INPUT_STAGING_STATUS.csv",
    CONSOLIDATION / "V20_213_YAHOO_HISTORICAL_PRICE_ACQUISITION_MANIFEST.csv",
    CONSOLIDATION / "V20_213_PRICE_PATH_CERTIFICATION_AUDIT.csv",
    CONSOLIDATION / "V20_213_MEMBERSHIP_CERTIFICATION_AUDIT.csv",
    CONSOLIDATION / "V20_213_ETF_ROTATION_HISTORY_STAGING_CONTRACT.csv",
    CONSOLIDATION / "V20_213_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_213_DAILY_PRICE_PATH_SOURCE_REPAIR_OR_EQUITY_CURVE_INPUT_STAGING_REPORT.md",
]
TEMPLATES = [
    INPUT_EC / "V20_213_BASELINE_TOP20_MEMBERSHIP_INPUT_TEMPLATE.csv",
    INPUT_EC / "V20_213_SHADOW_TOP20_MEMBERSHIP_INPUT_TEMPLATE.csv",
    INPUT_EC / "V20_213_DAILY_PRICE_PATH_INPUT_TEMPLATE.csv",
    INPUT_EC / "V20_213_BENCHMARK_DAILY_PRICE_PATH_INPUT_TEMPLATE.csv",
    INPUT_EC / "V20_213_SELECTED_ETF_HISTORY_INPUT_TEMPLATE.csv",
]
VALID_STATUSES = {
    "PASS_V20_213_EQUITY_CURVE_INPUTS_STAGED_AND_READY_FOR_RETRY",
    "PASS_V20_213_EQUITY_CURVE_INPUT_STAGING_CONTRACT_READY_DATA_COLLECTION_REQUIRED",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v20_213_daily_price_path_source_repair_or_equity_curve_input_staging() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout
    assert "TRADE_ACTION_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"
        if path.suffix.lower() == ".csv":
            assert read_csv(path), f"output has no rows {path}"
    for path in TEMPLATES:
        assert path.exists() and path.stat().st_size > 0, f"missing template {path}"
        assert read_csv(path), f"template has no rows {path}"

    gate = read_csv(CONSOLIDATION / "V20_213_NEXT_STAGE_GATE.csv")[0]
    assert gate["v20_213_status"] in VALID_STATUSES
    assert gate["official_promotion_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["weight_mutated"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"
    assert gate["consumed_v20_212_status"]
    assert gate["v20_212_blocker_intake_created"] == "TRUE"
    assert gate["membership_source_discovery_created"] == "TRUE"
    assert gate["price_source_discovery_created"] == "TRUE"
    assert gate["required_input_schema_created"] == "TRUE"
    assert gate["input_templates_created"] == "TRUE"
    assert gate["yahoo_acquisition_manifest_created"] == "TRUE"

    membership_ready = gate["membership_history_available"] == "TRUE"
    price_ready = gate["daily_ticker_price_paths_available"] == "TRUE"
    assert (gate["equity_curve_retry_ready"] == "TRUE") == (membership_ready and price_ready)

    price_cert = read_csv(CONSOLIDATION / "V20_213_PRICE_PATH_CERTIFICATION_AUDIT.csv")
    header_only_price = [row for row in price_cert if row["header_only"] == "TRUE"]
    assert all(row["certified_usable"] == "FALSE" for row in header_only_price)
    assert all(int(float(row["distinct_trading_dates"] or 0)) >= 121 for row in price_cert if row["certified_usable"] == "TRUE")

    membership_cert = read_csv(CONSOLIDATION / "V20_213_MEMBERSHIP_CERTIFICATION_AUDIT.csv")
    header_only_membership = [row for row in membership_cert if row["header_only"] == "TRUE"]
    assert all(row["certified_usable"] == "FALSE" for row in header_only_membership)

    etf_contract = read_csv(CONSOLIDATION / "V20_213_ETF_ROTATION_HISTORY_STAGING_CONTRACT.csv")
    selected_required = next(row for row in etf_contract if row["contract_item"] == "selected_etf_history_required")
    if selected_required["available"] == "FALSE":
        assert gate["selected_etf_history_available"] == "FALSE"

    manifest = read_csv(CONSOLIDATION / "V20_213_YAHOO_HISTORICAL_PRICE_ACQUISITION_MANIFEST.csv")
    assert manifest
    assert all(row["acquisition_status"] == "NOT_FETCHED_BY_DEFAULT" for row in manifest)
    assert {"QQQ", "SPY", "SOXX", "SMH"}.issubset({row["ticker"] for row in manifest})

    staging = read_csv(CONSOLIDATION / "V20_213_EQUITY_CURVE_INPUT_STAGING_STATUS.csv")
    staging_map = {row["staging_item"]: row["status"] for row in staging}
    assert staging_map["allow_yahoo_download_argument_used"] == "FALSE"

    created_names = [path.name.lower() for path in CONSOLIDATION.glob("V20_213*")]
    forbidden = ["drawdown_metrics", "performance_metrics", "equity_curve.csv"]
    assert not any(any(term in name for term in forbidden) for name in created_names)

    wrapper_text = WRAPPER.read_text(encoding="utf-8")
    assert "--allow-yahoo-download" not in wrapper_text

    report_text = (READ_CENTER / "V20_213_DAILY_PRICE_PATH_SOURCE_REPAIR_OR_EQUITY_CURVE_INPUT_STAGING_REPORT.md").read_text(encoding="utf-8")
    assert "No network download was performed by default" in report_text
    assert "No drawdown or performance metric was fabricated" in report_text
    assert gate["recommended_next_stage"] in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "FINAL_STATUS=" in result.stdout
    assert "EQUITY_CURVE_RETRY_READY=" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_v20_213_daily_price_path_source_repair_or_equity_curve_input_staging()
    test_wrapper_parseable()
    print("PASS test_v20_213_daily_price_path_source_repair_or_equity_curve_input_staging")
