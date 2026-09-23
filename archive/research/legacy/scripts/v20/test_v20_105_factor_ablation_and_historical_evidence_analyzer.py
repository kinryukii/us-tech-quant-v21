from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_105_factor_ablation_and_historical_evidence_analyzer.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_105_factor_ablation_and_historical_evidence_analyzer.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_105_factor_ablation_and_historical_evidence_analyzer.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_FAMILY = CONSOLIDATION / "V20_105_FACTOR_FAMILY_HISTORICAL_EVIDENCE.csv"
OUT_ABLATION = CONSOLIDATION / "V20_105_FACTOR_ABLATION_EVIDENCE_MATRIX.csv"
OUT_WINDOW = CONSOLIDATION / "V20_105_FORWARD_WINDOW_FACTOR_PERFORMANCE.csv"
OUT_QUALITY = CONSOLIDATION / "V20_105_FACTOR_EVIDENCE_QUALITY_AUDIT.csv"
OUT_READY = CONSOLIDATION / "V20_105_SHADOW_REWEIGHTING_READINESS.csv"
REPORT = READ_CENTER / "V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_REPORT.md"

FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
WINDOWS = {"5D", "10D", "20D", "60D", "120D"}
ACCEPTED = {
    "PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER",
    "PARTIAL_PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER_WITH_LIMITED_FACTOR_GRANULARITY",
    "PARTIAL_PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER_WITH_LIMITED_HISTORICAL_COVERAGE",
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
    assert_true("V20_104_PARTIAL_PASS_RECOGNIZED=TRUE" in result.stdout, "V20.104 partial pass not recognized")
    assert_true("DYNAMIC_FACTOR_WEIGHT_CREATED=FALSE" in result.stdout, "dynamic weight safety missing")
    assert_true("V20_107_EXECUTION_STATUS=NOT_RUN" in result.stdout, "V20.107 not preserved")
    assert_true(before == after, "R5 active research base weights were mutated")
    for path in [OUT_FAMILY, OUT_ABLATION, OUT_WINDOW, OUT_QUALITY, OUT_READY, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_family_and_window_coverage() -> None:
    rows = read_csv(OUT_FAMILY)
    assert_true({row["factor_family"] for row in rows} == FAMILIES, "not all factor families represented")
    assert_true({row["forward_window"] for row in rows} == WINDOWS, "not all windows represented")
    assert_true(len(rows) == 30, f"expected 30 family/window rows: {len(rows)}")
    for row in rows:
        assert_safety(row)
        assert_true(row["active_research_base_weight"], f"missing active base weight: {row}")
        assert_true(row["evidence_status"] in {"USABLE_EVIDENCE", "INSUFFICIENT_EVIDENCE"}, f"bad evidence status: {row}")
        if int(row["usable_observation_count"]) >= 30:
            assert_true(row["dynamic_reweighting_eligible"] == "TRUE", f"threshold row not eligible: {row}")


def test_ablation_limited_not_fabricated() -> None:
    rows = read_csv(OUT_ABLATION)
    assert_true({row["factor_family"] for row in rows} == FAMILIES, "ablation missing families")
    assert_true({row["forward_window"] for row in rows} == WINDOWS, "ablation missing windows")
    for row in rows:
        assert_safety(row)
        assert_true(row["ablation_status"] == "LIMITED_FACTOR_GRANULARITY", f"factor-level ablation fabricated: {row}")
        assert_true(row["ablated_mean_alpha"] == "", f"ablated alpha fabricated: {row}")
        assert_true(row["estimated_factor_contribution"] == "", f"factor contribution fabricated: {row}")
        assert_true(row["missing_reason"] == "PIT_SAFE_FACTOR_LEVEL_NUMERIC_CONTRIBUTIONS_UNAVAILABLE", f"missing reason wrong: {row}")


def test_quality_and_readiness_contract() -> None:
    quality = read_csv(OUT_QUALITY)
    ready = read_csv(OUT_READY)
    assert_true(quality, "quality audit empty")
    assert_true(len(ready) == 1, "readiness should have one row")
    assert_true(any(row["v20_104_partial_pass_recognized"] == "TRUE" for row in quality), "V20.104 partial pass not recorded")
    assert_true(any(row["missing_historical_coverage_classified"] == "TRUE" for row in quality), "missing coverage not classified")
    assert_true(all(row["source_rank_or_score_used_as_weight"] == "FALSE" for row in quality), "source rank used as weight")
    for row in quality:
        assert_safety(row)
    row = ready[0]
    assert_safety(row)
    assert_true(row["active_research_base_weights_available"] == "TRUE", f"base weights not available: {row}")
    assert_true(row["usable_etf_regime_evidence_available"] == "TRUE", f"ETF evidence unavailable: {row}")
    assert_true(row["random_asof_backtest_available"] == "TRUE", f"random asof unavailable: {row}")
    assert_true(row["factor_ablation_evidence_available"] == "TRUE", f"ablation unavailable: {row}")
    assert_true(row["v20_107_execution_status"] == "NOT_RUN", f"V20.107 executed: {row}")
    assert_true(row["dynamic_factor_weight_created"] == "FALSE", f"dynamic weights created: {row}")


def test_report_boundaries() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing accepted status")
    assert_true("ablation_status: LIMITED_FACTOR_GRANULARITY" in text, "report missing limited granularity")
    assert_true("dynamic_factor_weight_created: FALSE" in text, "report missing dynamic safety")
    assert_true("v20_107_execution_status: NOT_RUN" in text, "report missing V20.107 safety")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion safety")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_family_and_window_coverage()
    test_ablation_limited_not_fabricated()
    test_quality_and_readiness_contract()
    test_report_boundaries()
    print("PASS_V20_105_FACTOR_ABLATION_AND_HISTORICAL_EVIDENCE_ANALYZER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
