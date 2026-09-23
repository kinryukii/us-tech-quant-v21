from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98c_r2_controlled_etf_price_refresh_and_cache_certification.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98c_r2_controlled_etf_price_refresh_and_cache_certification.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98c_r2_controlled_etf_price_refresh_and_cache_certification.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

REFRESH_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
CERTIFICATION = CONSOLIDATION / "V20_98C_R2_ETF_PRICE_REFRESH_CERTIFICATION.csv"
PAIR_AFTER_REFRESH = CONSOLIDATION / "V20_98C_R2_ETF_PAIR_COVERAGE_AFTER_REFRESH.csv"
REPORT = READ_CENTER / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_REPORT.md"
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

ACCEPTED_STATUSES = {
    "PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CERTIFIED",
    "PARTIAL_PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_WITH_MISSING_DATA",
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
    assert_true(any(status in result.stdout for status in ACCEPTED_STATUSES), f"missing accepted status: {result.stdout}")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 execution not preserved")
    assert_true("OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout, "official promotion safety missing")
    assert_true(before == after, "R5 active research base weight registry was mutated")
    for path in [REFRESH_CACHE, CERTIFICATION, PAIR_AFTER_REFRESH, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_cache_contract_and_no_fabricated_prices() -> None:
    rows = read_csv(REFRESH_CACHE)
    tickers = {row["ticker"] for row in rows}
    assert_true(tickers == REQUIRED_ETFS, f"ETF universe mismatch: {tickers}")
    by_ticker = {row["ticker"]: row for row in rows}
    for ticker in ["SPY", "QQQ"]:
        row = by_ticker[ticker]
        assert_true(row["data_available"] == "TRUE", f"{ticker} not retained/refreshed safely: {row}")
        assert_true(row["latest_price"], f"{ticker} missing price: {row}")
        assert_true(row["latest_price_date"], f"{ticker} missing date: {row}")
    for row in rows:
        assert_safety(row)
        assert_true(row["asset_class"] == "ETF", f"wrong asset class: {row}")
        assert_true(row["required_for_pair_checks"] == "TRUE", f"not required for pairs: {row}")
        if row["certification_status"] == "CERTIFIED":
            assert_true(row["data_available"] == "TRUE", f"certified row unavailable: {row}")
            assert_true(row["latest_price"], f"certified row missing price: {row}")
            assert_true(row["latest_price_date"], f"certified row missing date: {row}")
            assert_true(row["data_freshness_status"] == "CURRENT_REFRESHED_PRICE_AVAILABLE", f"certified stale/missing row: {row}")
        else:
            assert_true(row["latest_price"] == "", f"blocked row fabricated price: {row}")
            assert_true(row["data_freshness_status"] in {"MISSING_CURRENT_ETF_PRICE_DATA", "STALE_PRICE_NOT_ACCEPTED"}, f"blocked row not classified: {row}")
            assert_true(row["refresh_status"] in {"REFRESH_FAILED", "REFRESH_STALE_REJECTED", "REUSED_PRICE_STALE_REJECTED"}, f"blocked row status wrong: {row}")


def test_stale_prices_are_not_accepted() -> None:
    rows = read_csv(REFRESH_CACHE)
    stale_rows = [row for row in rows if row["data_freshness_status"] == "STALE_PRICE_NOT_ACCEPTED"]
    for row in stale_rows:
        assert_true(row["certification_status"] == "BLOCKED", f"stale row certified: {row}")
        assert_true(row["data_available"] == "FALSE", f"stale row marked available: {row}")
        assert_true(row["latest_price"] == "", f"stale row retained price as current: {row}")


def test_certification_summary_contract() -> None:
    rows = read_csv(CERTIFICATION)
    assert_true(len(rows) == 1, f"expected one certification row: {rows}")
    row = rows[0]
    assert_safety(row)
    assert_true(row["certification_status"] in ACCEPTED_STATUSES, f"unexpected certification status: {row}")
    assert_true(row["required_etf_count"] == "14", f"wrong ETF count: {row}")
    assert_true(row["pair_target_count"] == "13", f"wrong pair count: {row}")
    certified = int(row["certified_current_etf_price_count"])
    missing = int(row["missing_current_etf_price_count"])
    assert_true(certified + missing == 14, f"certified/missing count mismatch: {row}")
    assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")


def test_pair_after_refresh_contract() -> None:
    rows = read_csv(PAIR_AFTER_REFRESH)
    pairs = {row["etf_pair"] for row in rows}
    assert_true(pairs == REQUIRED_PAIRS, f"pair universe mismatch: {pairs}")
    for row in rows:
        assert_safety(row)
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")
        if row["pair_data_available"] == "TRUE":
            assert_true(row["coverage_status"] == "PAIR_CURRENT_PRICE_COVERAGE_AVAILABLE", f"wrong complete pair status: {row}")
            assert_true(row["left_latest_price"] and row["right_latest_price"], f"complete pair missing prices: {row}")
        else:
            assert_true(row["missing_side"] in {"LEFT", "RIGHT", "LEFT_AND_RIGHT"}, f"missing side not classified: {row}")
            assert_true(row["coverage_status"] in {"MISSING_CURRENT_ETF_PRICE_DATA", "STALE_PRICE_NOT_ACCEPTED"}, f"missing pair not classified: {row}")


def test_report_boundaries() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED_STATUSES), "report missing accepted status")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion")
    assert_true("dynamic_factor_weight_created: FALSE" in text, "report missing dynamic weight safety")
    assert_true("V20.107: NOT_RUN" in text, "report missing V20.107 not-run status")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_cache_contract_and_no_fabricated_prices()
    test_stale_prices_are_not_accepted()
    test_certification_summary_contract()
    test_pair_after_refresh_contract()
    test_report_boundaries()
    print("PASS_V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_AND_CACHE_CERTIFICATION_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
