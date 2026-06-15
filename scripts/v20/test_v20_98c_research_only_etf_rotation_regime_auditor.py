from __future__ import annotations

import csv
import importlib.util
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98c_research_only_etf_rotation_regime_auditor.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98c_research_only_etf_rotation_regime_auditor.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98c_research_only_etf_rotation_regime_auditor.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
MATRIX = CONSOLIDATION / "V20_98C_ETF_PAIR_RELATIVE_STRENGTH_MATRIX.csv"
SCAFFOLD = CONSOLIDATION / "V20_98C_ETF_REGIME_FACTOR_MULTIPLIER_SCAFFOLD.csv"
REPORT = READ_CENTER / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_REPORT.md"
R2_CACHE = CONSOLIDATION / "V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv"
R3_INTEGRATION_AUDIT = CONSOLIDATION / "V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_AUDIT.csv"
R3_INTEGRATION_REPORT = READ_CENTER / "V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIR_REPORT.md"

REQUIRED_PAIRS = {
    "QQQ_SPY",
    "XLK_SPY",
    "SOXX_QQQ",
    "SMH_QQQ",
    "SOXX_SPY",
    "SMH_SPY",
    "TQQQ_SQQQ",
    "SOXL_SOXS",
    "RSP_SPY",
    "XLU_SPY",
    "XLP_SPY",
    "TLT_SPY",
    "GLD_SPY",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_module():
    spec = importlib.util.spec_from_file_location("v20_98c_stage", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "failed to load script spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")


def test_wrapper_passes_and_outputs_created() -> str:
    before = (CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv").read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    after = (CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv").read_text(encoding="utf-8")
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("R5_ACTIVE_RESEARCH_BASE_WEIGHT_COUNT=6" in result.stdout, "R5 weights not recognized")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "official promotion block not preserved")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 executed")
    assert_true("CURRENT_PAIR_DATA_AVAILABLE_COUNT=13" in result.stdout, "R2 cache did not lift pair coverage to 13")
    assert_true("MISSING_ETF_PAIR_DATA_COUNT=0" in result.stdout, "missing pair data remains after R2 integration")
    assert_true(before == after, "R5 active research base weight registry was mutated")
    for path in [AUDIT, MATRIX, SCAFFOLD, REPORT, R3_INTEGRATION_AUDIT, R3_INTEGRATION_REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")
    return result.stdout


def test_audit_rows_use_r2_cache_and_preserve_safety() -> None:
    rows = read_csv(AUDIT)
    pairs = {row["etf_pair"] for row in rows}
    assert_true(REQUIRED_PAIRS.issubset(pairs), f"missing required pairs: {REQUIRED_PAIRS - pairs}")
    assert_true(len(rows) == 13, f"wrong pair row count: {len(rows)}")
    assert_true(all(row["data_available"] == "TRUE" for row in rows), "not all pair rows have current data")
    assert_true(not any(row["relative_strength_status"] == "MISSING_ETF_PAIR_DATA" for row in rows), "missing ETF data remains")
    assert_true(any(row["regime_classification"] == "MIXED_OR_INSUFFICIENT_DATA" for row in rows), "insufficient data classification missing")
    for row in rows:
        assert_safety(row)
        assert_true("V20.98C-R2_CERTIFIED_ETF_PRICE_CACHE" in row["price_source_stage"], f"R2 cache stage not used: {row}")
        assert_true(row["multiplier_activation_allowed"] == "FALSE", f"multiplier activation allowed: {row}")


def test_matrix_prioritizes_r2_cache_over_fallback_sources() -> None:
    matrix_rows = read_csv(MATRIX)
    r2_rows = {row["ticker"]: row for row in read_csv(R2_CACHE) if row["certification_status"] == "CERTIFIED"}
    assert_true(len(r2_rows) == 14, "R2 cache is not fully certified for test precondition")
    for row in matrix_rows:
        assert_true(row["data_available"] == "TRUE", f"matrix pair unavailable: {row}")
        assert_true("outputs/v20/consolidation/V20_98C_R2_CONTROLLED_ETF_PRICE_REFRESH_CACHE.csv" in row["evidence_source_artifact"], f"R2 source not prioritized: {row}")
        assert_true("V20.98C-R2_CERTIFIED_ETF_PRICE_CACHE" in row["price_source_stage"], f"R2 stage not written: {row}")
        left = r2_rows[row["left_ticker"]]
        right = r2_rows[row["right_ticker"]]
        assert_true(row["left_latest_price"] == left["latest_price"], f"left price not sourced from R2 cache: {row}")
        assert_true(row["right_latest_price"] == right["latest_price"], f"right price not sourced from R2 cache: {row}")
        assert_true(row["left_latest_price"] and row["right_latest_price"], f"fabricated or missing pair prices: {row}")


def test_r3_integration_audit_contract() -> None:
    rows = read_csv(R3_INTEGRATION_AUDIT)
    assert_true(len(rows) == 1, f"expected one R3 audit row: {rows}")
    row = rows[0]
    assert_true(row["artifact_exists"] == "TRUE", f"R2 cache missing: {row}")
    assert_true(row["artifact_non_empty"] == "TRUE", f"R2 cache empty: {row}")
    assert_true(row["certified_etf_price_count"] == "14", f"wrong certified ETF count: {row}")
    assert_true(row["certified_pair_coverage_count"] == "13", f"wrong certified pair count: {row}")
    assert_true(row["v20_98c_used_r2_cache"] == "TRUE", f"R2 cache not used: {row}")
    assert_true(row["fallback_used"] == "FALSE", f"fallback used despite R2 cache: {row}")
    assert_true(row["current_pair_data_available_after"] == "13", f"after count wrong: {row}")
    assert_true(row["missing_pair_data_after"] == "0", f"missing after count wrong: {row}")
    assert_true(row["integration_status"] == "PASS_V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIRED", f"integration did not pass: {row}")
    assert_true(row["research_only"] == "TRUE", f"research flag wrong: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutated: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker supported: {row}")


def test_stale_and_uncertified_r2_rows_are_rejected_by_price_loader() -> None:
    module = load_module()
    assert_true(module.current_freshness("CURRENT_REFRESHED_PRICE_AVAILABLE") is True, "current freshness rejected")
    assert_true(module.current_freshness("STALE_PRICE_NOT_ACCEPTED") is False, "stale freshness accepted")
    assert_true(module.current_freshness("MISSING_CURRENT_ETF_PRICE_DATA") is False, "missing freshness accepted")
    assert_true(module.certified_status("CERTIFIED") is True, "CERTIFIED rejected")
    assert_true(module.certified_status("PASS") is True, "PASS rejected")
    assert_true(module.certified_status("BLOCKED") is False, "BLOCKED accepted")


def test_matrix_and_scaffold_do_not_create_dynamic_weights() -> None:
    matrix_rows = read_csv(MATRIX)
    scaffold_rows = read_csv(SCAFFOLD)
    assert_true(matrix_rows, "matrix empty")
    assert_true(scaffold_rows, "scaffold empty")
    for row in matrix_rows:
        assert_safety(row)
    for row in scaffold_rows:
        assert_safety(row)
        assert_true(row["multiplier_activation_allowed"] == "FALSE", f"multiplier activated: {row}")
        assert_true(row["numeric_multiplier_created"] == "FALSE", f"numeric multiplier created: {row}")
        assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic factor weight created: {row}")
        assert_true(row["v20_107_precondition_status"] == "USABLE_ETF_REGIME_EVIDENCE_AVAILABLE", f"wrong V20.107 precondition: {row}")
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")


def test_report_preserves_research_only_boundary() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims promotion")
    assert_true("weight_mutated: FALSE" in text, "report missing weight mutation safety")
    assert_true("trade_action_created: FALSE" in text, "report missing trade safety")
    assert_true("v20_107_execution_status: NOT_RUN" in text, "report missing V20.107 not-run status")
    r3_text = R3_INTEGRATION_REPORT.read_text(encoding="utf-8")
    assert_true("integration_status: PASS_V20_98C_R3_CERTIFIED_ETF_CACHE_INTEGRATION_REPAIRED" in r3_text, "R3 report missing pass status")
    assert_true("V20.107: NOT_RUN" in r3_text, "R3 report missing V20.107 not-run")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_audit_rows_use_r2_cache_and_preserve_safety()
    test_matrix_prioritizes_r2_cache_over_fallback_sources()
    test_r3_integration_audit_contract()
    test_stale_and_uncertified_r2_rows_are_rejected_by_price_loader()
    test_matrix_and_scaffold_do_not_create_dynamic_weights()
    test_report_preserves_research_only_boundary()
    print("PASS_V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDITOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
