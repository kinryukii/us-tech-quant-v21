from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98c_r1_current_etf_price_coverage_expander.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98c_r1_current_etf_price_coverage_expander.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98c_r1_current_etf_price_coverage_expander.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

COVERAGE = CONSOLIDATION / "V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE.csv"
PAIR_AUDIT = CONSOLIDATION / "V20_98C_R1_ETF_PAIR_COVERAGE_AUDIT.csv"
REPAIR_PLAN = CONSOLIDATION / "V20_98C_R1_ETF_COVERAGE_GAP_REPAIR_PLAN.csv"
REPORT = READ_CENTER / "V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_REPORT.md"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

REQUIRED_ETFS = {
    "SPY",
    "QQQ",
    "XLK",
    "SOXX",
    "SMH",
    "TQQQ",
    "SQQQ",
    "SOXL",
    "SOXS",
    "RSP",
    "XLU",
    "XLP",
    "TLT",
    "GLD",
}

REQUIRED_PAIRS = {
    "QQQ vs SPY",
    "XLK vs SPY",
    "SOXX vs QQQ",
    "SMH vs QQQ",
    "SOXX vs SPY",
    "SMH vs SPY",
    "TQQQ vs SQQQ",
    "SOXL vs SOXS",
    "RSP vs SPY",
    "XLU vs SPY",
    "XLP vs SPY",
    "TLT vs SPY",
    "GLD vs SPY",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")


def test_wrapper_passes_and_outputs_created() -> str:
    before = R5_REGISTRY.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    after = R5_REGISTRY.read_text(encoding="utf-8")
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 execution not preserved")
    assert_true("OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout, "official promotion safety missing")
    assert_true(before == after, "R5 active research base weight registry was mutated")
    for path in [COVERAGE, PAIR_AUDIT, REPAIR_PLAN, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_coverage_contract_and_missing_classification() -> None:
    rows = read_csv(COVERAGE)
    tickers = {row["ticker"] for row in rows}
    assert_true(tickers == REQUIRED_ETFS, f"ETF universe mismatch: {tickers}")
    for row in rows:
        assert_safety(row)
        assert_true(row["asset_class"] == "ETF", f"wrong asset class: {row}")
        assert_true(row["required_for_pair_checks"] == "TRUE", f"not required for pair checks: {row}")
        if row["data_available"] == "TRUE":
            assert_true(row["latest_price"], f"available row missing price: {row}")
            assert_true(row["latest_price_date"], f"available row missing date: {row}")
            assert_true(row["price_source_artifact"] in {
                "outputs/v20/consolidation/V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv",
                "outputs/v20/consolidation/V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv",
            }, f"unexpected source: {row}")
            assert_true(row["repair_action"] == "NONE", f"available row has repair: {row}")
        else:
            assert_true(row["latest_price"] == "", f"missing row fabricated price: {row}")
            assert_true(row["data_freshness_status"] == "MISSING_CURRENT_ETF_PRICE_DATA", f"missing reason not explicit: {row}")
            assert_true(row["missing_reason"] == "MISSING_CURRENT_ETF_PRICE_DATA", f"missing reason wrong: {row}")


def test_pair_audit_contract_and_safety() -> None:
    rows = read_csv(PAIR_AUDIT)
    pairs = {row["etf_pair"] for row in rows}
    assert_true(pairs == REQUIRED_PAIRS, f"pair universe mismatch: {pairs}")
    assert_true(any(row["pair_data_available"] == "TRUE" for row in rows), "existing current pair data was not reused")
    assert_true(any(row["coverage_status"] == "MISSING_CURRENT_ETF_PRICE_DATA" for row in rows), "missing pair data not classified")
    for row in rows:
        assert_safety(row)
        if row["pair_data_available"] == "FALSE":
            assert_true(row["missing_side"] in {"LEFT", "RIGHT", "LEFT_AND_RIGHT"}, f"missing side not classified: {row}")
            assert_true(row["repair_action"] != "NONE", f"missing pair lacks repair action: {row}")


def test_repair_plan_and_report_boundaries() -> None:
    rows = read_csv(REPAIR_PLAN)
    assert_true(rows, "repair plan should be present for missing ETF prices")
    for row in rows:
        assert_safety(row)
        assert_true(row["gap_status"] == "OPEN", f"wrong gap status: {row}")
        assert_true(row["missing_reason"] == "MISSING_CURRENT_ETF_PRICE_DATA", f"wrong missing reason: {row}")
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")
    text = REPORT.read_text(encoding="utf-8")
    assert_true("wrapper_status: PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER_WITH_REPAIR_PLAN" in text, "report missing repair-plan pass")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion")
    assert_true("dynamic_factor_weight_created: FALSE" in text, "report missing dynamic weight safety")
    assert_true("V20.107: NOT_RUN" in text, "report missing V20.107 not-run status")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_coverage_contract_and_missing_classification()
    test_pair_audit_contract_and_safety()
    test_repair_plan_and_report_boundaries()
    print("PASS_V20_98C_R1_CURRENT_ETF_PRICE_COVERAGE_EXPANDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
