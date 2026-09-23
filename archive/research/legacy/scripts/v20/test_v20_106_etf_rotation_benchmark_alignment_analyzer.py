from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_106_etf_rotation_benchmark_alignment_analyzer.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_106_etf_rotation_benchmark_alignment_analyzer.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_106_etf_rotation_benchmark_alignment_analyzer.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_ALIGNMENT = CONSOLIDATION / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT.csv"
OUT_FACTOR_ALIGNMENT = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
OUT_SIGNAL_AUDIT = CONSOLIDATION / "V20_106_ETF_REGIME_REWEIGHTING_SIGNAL_AUDIT.csv"
OUT_PRECONDITION = CONSOLIDATION / "V20_106_SHADOW_REWEIGHTING_PRECONDITION_AUDIT.csv"
REPORT = READ_CENTER / "V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_REPORT.md"

FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
WINDOWS = {"5D", "10D", "20D", "60D", "120D"}
PAIRS = {
    "QQQ_SPY", "XLK_SPY", "SOXX_QQQ", "SMH_QQQ", "SOXX_SPY", "SMH_SPY",
    "TQQQ_SQQQ", "SOXL_SOXS", "RSP_SPY", "XLU_SPY", "XLP_SPY", "TLT_SPY", "GLD_SPY",
}
ACCEPTED = {
    "PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER",
    "PARTIAL_PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER_WITH_LIMITED_FACTOR_GRANULARITY",
    "PARTIAL_PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER_WITH_LIMITED_HISTORICAL_COVERAGE",
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
    if "is_official_weight" in row:
        assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")
    if "dynamic_factor_weight_created" in row:
        assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic weight claimed: {row}")
    if "v20_107_execution_status" in row:
        assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")


def test_wrapper_runs_and_outputs_created() -> None:
    before = R5_REGISTRY.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    after = R5_REGISTRY.read_text(encoding="utf-8")
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("LIMITED_FACTOR_GRANULARITY_RECOGNIZED=TRUE" in result.stdout, "limited factor granularity not recognized")
    assert_true("MULTIPLIER_ACTIVATION_ALLOWED=FALSE" in result.stdout, "multiplier activation safety missing")
    assert_true("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE" in result.stdout, "dynamic weight safety missing")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 not preserved")
    assert_true(before == after, "R5 active research base weights mutated")
    for path in [OUT_ALIGNMENT, OUT_FACTOR_ALIGNMENT, OUT_SIGNAL_AUDIT, OUT_PRECONDITION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_etf_alignment_contract() -> None:
    rows = read_csv(OUT_ALIGNMENT)
    assert_true(PAIRS == {row["etf_pair"] for row in rows}, "not all ETF regime pairs represented")
    assert_true(WINDOWS == {row["forward_window"] for row in rows}, "not all windows represented in alignment")
    assert_true(len(rows) == 65, f"expected 13 pairs x 5 windows: {len(rows)}")
    for row in rows:
        assert_safety(row)
        assert_true(row["benchmark_alignment_status"] == "BENCHMARK_ALIGNMENT_AVAILABLE", f"missing benchmark alignment: {row}")
        assert_true(row["alignment_status"] == "USABLE_ALIGNMENT_EVIDENCE", f"alignment not usable: {row}")
        assert_true(row["benchmark_observation_count"] != "0", f"no benchmark observations: {row}")


def test_factor_alignment_contract() -> None:
    rows = read_csv(OUT_FACTOR_ALIGNMENT)
    assert_true(FAMILIES == {row["factor_family"] for row in rows}, "not all families represented")
    assert_true(WINDOWS == {row["forward_window"] for row in rows}, "not all windows represented")
    assert_true(rows, "factor alignment empty")
    for row in rows:
        assert_safety(row)
        assert_true(row["multiplier_activation_allowed"] == "FALSE", f"multiplier activated: {row}")
        assert_true(row["dynamic_weight_created"] == "FALSE", f"dynamic weight created: {row}")
        assert_true(row["active_research_base_weight"], f"missing base weight: {row}")


def test_signal_and_precondition_safety() -> None:
    signals = read_csv(OUT_SIGNAL_AUDIT)
    pre = read_csv(OUT_PRECONDITION)
    assert_true(signals, "signal audit empty")
    assert_true(len(pre) == 1, "precondition audit should have one row")
    assert_true(any(row["limited_factor_granularity_recognized"] == "TRUE" for row in signals), "limited granularity not audited")
    for row in signals:
        assert_safety(row)
        assert_true(row["multiplier_activation_allowed"] == "FALSE", f"multiplier activated: {row}")
        assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic weight created: {row}")
    row = pre[0]
    assert_safety(row)
    assert_true(row["usable_etf_regime_evidence_available"] == "TRUE", f"ETF evidence unavailable: {row}")
    assert_true(row["random_asof_backtest_available"] == "TRUE", f"V20.104 unavailable: {row}")
    assert_true(row["factor_granularity_status"] == "LIMITED_FACTOR_GRANULARITY", f"limited factor granularity not recognized: {row}")
    assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")
    assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic weights created: {row}")


def test_report_boundaries() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing accepted status")
    assert_true("limited_factor_granularity_recognized: TRUE" in text, "report missing limited granularity")
    assert_true("multiplier_activation_allowed: FALSE" in text, "report missing multiplier safety")
    assert_true("dynamic_factor_weight_created: FALSE" in text, "report missing dynamic weight safety")
    assert_true("v20_107_execution_status: NOT_RUN" in text, "report missing V20.107 safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_etf_alignment_contract()
    test_factor_alignment_contract()
    test_signal_and_precondition_safety()
    test_report_boundaries()
    print("PASS_V20_106_ETF_ROTATION_BENCHMARK_ALIGNMENT_ANALYZER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
