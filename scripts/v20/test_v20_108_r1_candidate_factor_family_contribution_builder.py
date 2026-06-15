from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r1_candidate_factor_family_contribution_builder.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r1_candidate_factor_family_contribution_builder.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r1_candidate_factor_family_contribution_builder.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
OUT_SOURCE = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_CONTRIBUTION_SOURCE_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R1_FACTOR_FAMILY_CONTRIBUTION_COVERAGE.csv"
REPORT = READ_CENTER / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER",
    "PARTIAL_PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER_WITH_PARTIAL_CONTRIBUTION_COVERAGE",
    "PARTIAL_PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER_WITH_MISSING_CONTRIBUTION_DATA",
}
FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}


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
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE" in result.stdout, "source rank used as contribution")
    assert_true("CONTRIBUTION_SCORES_FABRICATED=FALSE" in result.stdout, "contribution scores fabricated")
    assert_true("OFFICIAL_RANKING_CREATED=FALSE" in result.stdout, "official ranking created")
    assert_true("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE" in result.stdout, "authoritative ranking overwritten")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking artifact overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 shadow weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 base weights mutated")
    for path in [OUT_CONTRIB, OUT_SOURCE, OUT_COVERAGE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_contribution_outputs() -> None:
    contributions = read_csv(OUT_CONTRIB)
    candidates = read_csv(V48_CANDIDATES)
    assert_true(len(contributions) == len(candidates), "candidate rows not represented")
    for row in contributions:
        assert_safety(row)
        assert_true(row["usable_for_shadow_rerank"] == ("TRUE" if row["contribution_status"] == "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION" else "FALSE"), f"usable flag wrong: {row}")
        assert_true(row["baseline_score_source"].startswith("source_rank_or_score_preserved_baseline"), f"baseline score source not preserved: {row}")
    assert_true(any(row["contribution_status"] != "COMPLETE_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION" for row in contributions), "missing/partial coverage not classified")


def test_source_audit_and_coverage() -> None:
    sources = read_csv(OUT_SOURCE)
    coverage = read_csv(OUT_COVERAGE)
    assert_true(sources, "source audit empty")
    assert_true({row["factor_family"] for row in coverage} == FAMILIES, "not all factor families represented")
    assert_true(all(row["source_rank_or_score_used_as_contribution"] == "FALSE" for row in sources), "source_rank_or_score used as contribution")
    for row in sources:
        assert_safety(row)
    for row in coverage:
        assert_safety(row)
        with_count = int(row["candidates_with_contribution"])
        assert_true(row["usable_for_shadow_rerank"] == ("TRUE" if with_count > 0 else "FALSE"), f"usable coverage without real data: {row}")
        if with_count == 0:
            assert_true(row["missing_reason"] == "MISSING_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION", f"missing reason absent: {row}")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("source_rank_or_score_used_as_contribution: FALSE" in text, "report claims source score use")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_contribution_outputs()
    test_source_audit_and_coverage()
    print("PASS_V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTION_BUILDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
