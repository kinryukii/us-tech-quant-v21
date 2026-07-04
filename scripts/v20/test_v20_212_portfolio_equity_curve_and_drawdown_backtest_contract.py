#!/usr/bin/env python
"""Tests for V20.212 portfolio equity curve and drawdown backtest contract."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_212_portfolio_equity_curve_and_drawdown_backtest_contract.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_212_portfolio_equity_curve_and_drawdown_backtest_contract.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

OUTPUTS = [
    CONSOLIDATION / "V20_212_DATA_AVAILABILITY_AUDIT.csv",
    CONSOLIDATION / "V20_212_PORTFOLIO_EQUITY_CURVE_CONTRACT.csv",
    CONSOLIDATION / "V20_212_PORTFOLIO_CONSTRUCTION_POLICY.csv",
    CONSOLIDATION / "V20_212_EQUITY_CURVE_EXECUTION_READINESS.csv",
    CONSOLIDATION / "V20_212_BASELINE_EQUITY_CURVE.csv",
    CONSOLIDATION / "V20_212_SHADOW_EQUITY_CURVE.csv",
    CONSOLIDATION / "V20_212_BENCHMARK_EQUITY_CURVE.csv",
    CONSOLIDATION / "V20_212_PORTFOLIO_DRAWDOWN_METRICS.csv",
    CONSOLIDATION / "V20_212_PORTFOLIO_PERFORMANCE_METRICS.csv",
    CONSOLIDATION / "V20_212_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT_REPORT.md",
]

VALID_STATUSES = {
    "PASS_V20_212_EQUITY_CURVE_CONTRACT_READY_EXECUTION_BLOCKED_BY_MISSING_DAILY_PATHS",
    "PASS_V20_212_RESEARCH_ONLY_EQUITY_CURVE_AND_DRAWDOWN_METRICS_CREATED",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_weight_files() -> list[Path]:
    roots = [ROOT / "outputs", ROOT / "configs", ROOT / "data"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(
                path for path in root.rglob("*.csv")
                if "weight" in path.name.lower() and not path.name.startswith("V20_212_")
            )
    return sorted(files)


def test_v20_212_portfolio_equity_curve_and_drawdown_backtest_contract() -> None:
    weight_before = {path: sha(path) for path in protected_weight_files()}
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout
    assert "TRADE_ACTION_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout
    assert weight_before == {path: sha(path) for path in protected_weight_files()}

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"
        if path.suffix.lower() == ".csv":
            assert read_csv(path), f"output has no rows {path}"

    gate = read_csv(CONSOLIDATION / "V20_212_NEXT_STAGE_GATE.csv")[0]
    assert gate["v20_212_status"] in VALID_STATUSES
    assert gate["official_promotion_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["weight_mutated"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"
    assert gate["consumed_v20_211_status"]
    assert gate["consumed_v20_211_status"] != ""
    assert gate["baseline_retained_from_v20_211"] in {"TRUE", "FALSE"}
    assert gate["current_shadow_rejected_from_v20_211"] in {"TRUE", "FALSE"}

    readiness = read_csv(CONSOLIDATION / "V20_212_EQUITY_CURVE_EXECUTION_READINESS.csv")[0]
    assert readiness["forward_window_mean_returns_used_for_drawdown"] == "FALSE"
    assert readiness["external_api_called"] == "FALSE"
    assert readiness["missing_prices_fabricated"] == "FALSE"

    drawdown = read_csv(CONSOLIDATION / "V20_212_PORTFOLIO_DRAWDOWN_METRICS.csv")
    assert all(row["max_drawdown_source"] == "DAILY_NAV_PATH_REQUIRED_NOT_FORWARD_WINDOW_MEAN_RETURN" for row in drawdown)
    if gate["equity_curve_execution_allowed"] == "FALSE":
        assert readiness["blocker_reason"], "blocked run must explain missing inputs"
        assert readiness["metrics_status"] == "BLOCKED_MISSING_DAILY_NAV_PATH"
        assert gate["drawdown_metrics_created"] == "FALSE"
        assert gate["performance_metrics_created"] == "FALSE"
        assert all(row["max_drawdown"] == "" for row in drawdown)
    else:
        assert gate["drawdown_metrics_created"] == "TRUE"
        assert gate["performance_metrics_created"] == "TRUE"

    audit = read_csv(CONSOLIDATION / "V20_212_DATA_AVAILABILITY_AUDIT.csv")
    audit_map = {row["audit_item"]: row for row in audit}
    assert "baseline_top20_membership_history_available" in audit_map
    assert "shadow_top20_membership_history_available" in audit_map
    assert "daily_ticker_close_paths_available" in audit_map
    assert "max_drawdown_can_be_computed" in audit_map
    assert "selected_etf_rotation_history_available" in audit_map

    etf_history_available = audit_map["selected_etf_rotation_history_available"]["available"] == "TRUE"
    if not etf_history_available:
        assert gate["etf_rotation_equity_curve_available"] == "FALSE"

    contract_text = (CONSOLIDATION / "V20_212_PORTFOLIO_EQUITY_CURVE_CONTRACT.csv").read_text(encoding="utf-8")
    assert "Do not infer max drawdown from V20_109 forward-window mean returns" in contract_text

    report_text = (READ_CENTER / "V20_212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT_REPORT.md").read_text(encoding="utf-8")
    assert "Forward-window mean returns can compare average outcomes" in report_text
    assert "No official recommendation was created" in report_text
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
    assert "EQUITY_CURVE_EXECUTION_ALLOWED=" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_v20_212_portfolio_equity_curve_and_drawdown_backtest_contract()
    test_wrapper_parseable()
    print("PASS test_v20_212_portfolio_equity_curve_and_drawdown_backtest_contract")
