from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_research_only_factor_weight_exposure_auditor.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_research_only_factor_weight_exposure_auditor.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_research_only_factor_weight_exposure_auditor.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

EXPOSURE = CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv"
SUMMARY = CONSOLIDATION / "V20_98B_FACTOR_FAMILY_WEIGHT_SUMMARY.csv"
CONTRIBUTION = CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv"
REPORT = READ_CENTER / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_REPORT.md"


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


def test_wrapper_passes_and_outputs_created() -> None:
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_49_RESEARCH_ONLY_GATE_STATUS=PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" in result.stdout, "research-only gate not preserved")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "official blocked gate not preserved")
    for path in [EXPOSURE, SUMMARY, CONTRIBUTION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def assert_safety_rows(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
        assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
        assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")


def test_no_official_promotion_or_weight_mutation_claims() -> None:
    assert_safety_rows(read_csv(EXPOSURE))
    assert_safety_rows(read_csv(SUMMARY))
    assert_safety_rows(read_csv(CONTRIBUTION))
    text = REPORT.read_text(encoding="utf-8")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion blocked status")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion allowed")
    assert_true("weight_mutated: FALSE" in text, "report missing weight mutation safety")


def test_factor_families_represented_when_discoverable() -> None:
    exposure_rows = read_csv(EXPOSURE)
    summary_rows = read_csv(SUMMARY)
    families = {row["factor_family"] for row in exposure_rows if row["factor_family"]}
    assert_true(families, f"no factor families represented: {exposure_rows}")
    assert_true({row["factor_family"] for row in summary_rows} == families, f"summary families mismatch: {summary_rows}, {families}")
    assert_true(any(row["source_stage"] in {"V20.48", "V20.50"} for row in exposure_rows), f"expected V20.48/V20.50 factor sources: {exposure_rows}")


def test_missing_numeric_weights_explicit_not_fabricated() -> None:
    rows = read_csv(EXPOSURE)
    missing = [row for row in rows if row["weight_source_status"] == "MISSING_NUMERIC_WEIGHT_SOURCE"]
    assert_true(missing, f"missing numeric weights not classified: {rows}")
    for row in missing:
        assert_true(row["base_weight"] == "", f"base weight fabricated: {row}")
        assert_true(row["current_research_weight"] == "", f"current research weight fabricated: {row}")
        assert_true(row["effective_research_weight"] == "", f"effective weight fabricated: {row}")
        assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")


def test_candidate_contribution_sources_audited() -> None:
    rows = read_csv(CONTRIBUTION)
    assert_true(rows, "contribution audit empty")
    assert_true(any(row["source_stage"] == "V20.48" and row["source_column"] == "source_rank_or_score" and int(row["numeric_count"]) > 0 for row in rows), f"V20.48 score source missing: {rows}")
    assert_true(any(row["source_stage"] == "V20.50" for row in rows), f"V20.50 contribution context missing: {rows}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_no_official_promotion_or_weight_mutation_claims()
    test_factor_families_represented_when_discoverable()
    test_missing_numeric_weights_explicit_not_fabricated()
    test_candidate_contribution_sources_audited()
    print("PASS_V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE_AUDITOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
