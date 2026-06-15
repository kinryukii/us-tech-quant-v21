from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_98b_r1_research_only_factor_weight_source_registry.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_98b_r1_research_only_factor_weight_source_registry.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_98b_r1_research_only_factor_weight_source_registry.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
GAP_AUDIT = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_GAP_AUDIT.csv"
COLUMN_MAP = CONSOLIDATION / "V20_98B_R1_FACTOR_COLUMN_TO_FAMILY_MAP.csv"
REPORT = READ_CENTER / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY_REPORT.md"


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
    assert_true("PASS_V20_98B_R1_RESEARCH_ONLY_FACTOR_WEIGHT_SOURCE_REGISTRY" in result.stdout, f"missing pass status: {result.stdout}")
    assert_true("V20_49_RESEARCH_ONLY_GATE_STATUS=PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE" in result.stdout, "research-only gate not preserved")
    assert_true("V20_49_OFFICIAL_PROMOTION_GATE_STATUS=BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE" in result.stdout, "official blocked gate not preserved")
    for path in [REGISTRY, GAP_AUDIT, COLUMN_MAP, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
        assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
        assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")
        assert_true(row["is_official_weight"] == "FALSE", f"official weight claimed: {row}")


def test_no_numeric_weights_fabricated_and_gaps_classified() -> None:
    rows = read_csv(REGISTRY)
    assert_true(rows, "registry empty")
    assert_safety(rows)
    missing_rows = [row for row in rows if row["weight_source_status"] == "MISSING_NUMERIC_WEIGHT_SOURCE"]
    assert_true(missing_rows, f"missing numeric weight rows absent: {rows}")
    for row in missing_rows:
        assert_true(row["base_weight"] == "", f"base weight fabricated: {row}")
        assert_true(row["current_research_weight"] == "", f"research weight fabricated: {row}")
        assert_true(row["effective_research_weight"] == "", f"effective weight fabricated: {row}")
        assert_true(row["base_weight_gap"] == "TRUE", f"missing base weight gap not marked: {row}")
        assert_true(row["downstream_blocker_v20_107"] == "TRUE", f"V20.107 blocker missing: {row}")


def test_gap_audit_blocks_v20_107_until_base_weight_exists() -> None:
    rows = read_csv(GAP_AUDIT)
    assert_true(rows, "gap audit empty")
    assert_safety(rows)
    assert_true(any(row["gap_status"] == "MISSING_BASE_WEIGHT_SOURCE" for row in rows), f"missing base weight gap absent: {rows}")
    assert_true(all("V20.107" in row["downstream_blocker"] for row in rows), f"V20.107 blocker not present: {rows}")


def test_source_rank_or_score_is_score_not_factor_weight() -> None:
    rows = read_csv(COLUMN_MAP)
    assert_safety(rows)
    score_rows = [row for row in rows if row["source_column"] == "source_rank_or_score"]
    assert_true(score_rows, f"source_rank_or_score missing from column map: {rows}")
    for row in score_rows:
        assert_true(row["is_candidate_score_source"] == "TRUE", f"source_rank_or_score not score source: {row}")
        assert_true(row["is_factor_weight_source"] == "FALSE", f"source_rank_or_score treated as weight: {row}")
        assert_true(row["classification"] == "CANDIDATE_SCORE_SOURCE_NOT_FACTOR_WEIGHT", f"wrong score classification: {row}")


def test_report_safety_language() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert_true("official_promotion_allowed: FALSE" in text, "report missing promotion blocked status")
    assert_true("official_promotion_allowed: TRUE" not in text, "report claims official promotion allowed")
    assert_true("weight_mutated: FALSE" in text, "report missing weight mutation safety")
    assert_true("source_rank_or_score" in text and "not factor weights" in text, "report missing score-not-weight statement")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_passes_and_outputs_created()
    test_no_numeric_weights_fabricated_and_gaps_classified()
    test_gap_audit_blocks_v20_107_until_base_weight_exists()
    test_source_rank_or_score_is_score_not_factor_weight()
    test_report_safety_language()
    print("PASS_V20_98B_R1_RESEARCH_ONLY_FACTOR_WEIGHT_SOURCE_REGISTRY_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
