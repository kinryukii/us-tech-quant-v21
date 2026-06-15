from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6_fundamental_candidate_score_source_builder.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6_fundamental_candidate_score_source_builder.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6_fundamental_candidate_score_source_builder.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
OUT_COLUMN_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SOURCE_COLUMN_AUDIT.csv"
OUT_MATERIAL_AUDIT = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_SCORE_MATERIALIZATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R6_FUNDAMENTAL_COVERAGE_AFTER_BUILD.csv"
REPORT = READ_CENTER / "V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER",
    "PARTIAL_PASS_V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_108_R6_NO_SAFE_FUNDAMENTAL_CANDIDATE_SOURCE_FOUND",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row["research_only"] == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row.get("is_official_ranking", "FALSE") == "FALSE", f"official ranking claimed: {row}")
    assert_true(row.get("is_official_weight", "FALSE") == "FALSE", f"official weight claimed: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutated: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action created: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution supported: {row}")


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def test_wrapper_runs_and_outputs_created() -> None:
    before_candidates = V48_CANDIDATES.read_text(encoding="utf-8")
    before_v107 = V107_WEIGHTS.read_text(encoding="utf-8")
    before_r5 = R5_REGISTRY.read_text(encoding="utf-8")
    before_r4 = R4_SCORES.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE",
        "BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
    ]:
        assert_true(marker in result.stdout, f"missing marker {marker}")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 weights mutated")
    assert_true(before_r4 == R4_SCORES.read_text(encoding="utf-8"), "R4 scores mutated")
    for path in [OUT_SOURCE, OUT_COLUMN_AUDIT, OUT_MATERIAL_AUDIT, OUT_COVERAGE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_fundamental_source_contract() -> None:
    rows = read_csv(OUT_SOURCE)
    candidates = read_csv(V48_CANDIDATES)
    assert_true(len(rows) == len(candidates) == 315, "all candidates not represented")
    for row in rows:
        assert_safety(row)
        if row["fundamental_contribution"]:
            assert_true(row["fundamental_source_artifact"], f"materialized without source: {row}")
            assert_true(row["fundamental_raw_columns_used"], f"materialized without columns: {row}")
        else:
            assert_true(row["missing_reason"] == "MISSING_CANDIDATE_LEVEL_FUNDAMENTAL_SOURCE", f"missing reason absent: {row}")


def test_audit_and_coverage_contract() -> None:
    audit = read_csv(OUT_COLUMN_AUDIT)
    material = read_csv(OUT_MATERIAL_AUDIT)
    coverage = read_csv(OUT_COVERAGE)
    assert_true(audit, "column audit empty")
    assert_true(all(row["source_rank_or_score_used_as_fundamental"] == "FALSE" for row in audit), "source score used")
    for row in audit + material + coverage:
        assert_safety(row)
    assert_true(len(material) == 1 and material[0]["factor_family"] == "FUNDAMENTAL", "material audit wrong")
    assert_true(material[0]["used_source_rank_or_score"] == "FALSE", "source score used in materialization")
    assert_true(material[0]["used_baseline_rank"] == "FALSE", "baseline rank used")
    assert_true(material[0]["used_proxy"] == "FALSE", "proxy used")
    assert_true(material[0]["fabricated_values_created"] == "FALSE", "fabricated values")
    assert_true(len(coverage) == 1 and coverage[0]["factor_family"] == "FUNDAMENTAL", "coverage wrong")
    assert_true(coverage[0]["required_candidate_count"] == "315", f"wrong required count: {coverage[0]}")
    materialized = int(coverage[0]["materialized_candidate_count"])
    source_rows = read_csv(OUT_SOURCE)
    assert_true(materialized == sum(1 for row in source_rows if row["fundamental_contribution"]), "coverage mismatch")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("fabricated_values_created: FALSE" in text, "report claims fabrication")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_fundamental_source_contract()
    test_audit_and_coverage_contract()
    print("PASS_V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
