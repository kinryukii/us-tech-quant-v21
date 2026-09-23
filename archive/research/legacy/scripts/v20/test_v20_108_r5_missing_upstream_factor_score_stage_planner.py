from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r5_missing_upstream_factor_score_stage_planner.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r5_missing_upstream_factor_score_stage_planner.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r5_missing_upstream_factor_score_stage_planner.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_STAGE_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
OUT_GAP_MAP = CONSOLIDATION / "V20_108_R5_FACTOR_FAMILY_GAP_TO_STAGE_MAP.csv"
OUT_SOURCE_REQ = CONSOLIDATION / "V20_108_R5_UPSTREAM_SOURCE_REQUIREMENT_AUDIT.csv"
OUT_RESOLUTION = CONSOLIDATION / "V20_108_R5_SHADOW_RERANK_BLOCKER_RESOLUTION_PLAN.csv"
REPORT = READ_CENTER / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN_REPORT.md"

FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
REQUIRED_STAGES = {
    "V20.108-R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER",
    "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
    "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
    "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
    "V20.108-R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER",
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
    before_scores = R4_SCORES.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true("PASS_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER" in result.stdout, "missing pass")
    for marker in [
        "R6_PRESENT=TRUE", "R7_PRESENT=TRUE", "R8_PRESENT=TRUE", "R9_PRESENT=TRUE", "R10_PRESENT=TRUE",
        "CONTRIBUTION_SCORES_CREATED=FALSE", "PROXY_VALUES_ACTIVATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE", "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
    ]:
        assert_true(marker in result.stdout, f"missing marker {marker}")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 weights mutated")
    assert_true(before_scores == R4_SCORES.read_text(encoding="utf-8"), "R4 scores mutated")
    for path in [OUT_STAGE_PLAN, OUT_GAP_MAP, OUT_SOURCE_REQ, OUT_RESOLUTION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_stage_plan_and_gap_map() -> None:
    stages = read_csv(OUT_STAGE_PLAN)
    gaps = read_csv(OUT_GAP_MAP)
    assert_true({row["planned_stage"] for row in stages} == REQUIRED_STAGES, "R6-R10 stages not all present")
    assert_true({row["factor_family"] for row in gaps} == FAMILIES, "all six families not represented")
    by_family = {row["factor_family"]: row for row in gaps}
    assert_true(by_family["TECHNICAL"]["gap_type"] == "NO_GAP_ALREADY_MATERIALIZED", "technical not recognized materialized")
    assert_true(by_family["DATA_TRUST"]["gap_type"] == "NO_GAP_ALREADY_MATERIALIZED", "data trust not recognized materialized")
    assert_true(by_family["RISK"]["gap_type"] == "PARTIAL_CANDIDATE_LEVEL_COVERAGE", "risk partial not recognized")
    assert_true(by_family["RISK"]["current_coverage_count"] == "11", "risk 11/315 not recognized")
    for family in ["FUNDAMENTAL", "STRATEGY", "MARKET_REGIME"]:
        assert_true(by_family[family]["gap_type"] == "MISSING_CANDIDATE_LEVEL_COVERAGE", f"{family} missing not recognized")
    for row in stages + gaps:
        assert_safety(row)
        if "proxy_allowed" in row:
            assert_true(row["proxy_allowed"] == "FALSE", f"proxy allowed: {row}")


def test_source_requirements_and_resolution() -> None:
    source = read_csv(OUT_SOURCE_REQ)
    resolution = read_csv(OUT_RESOLUTION)
    assert_true(source, "source requirement audit empty")
    assert_true(all(row["contribution_scores_created"] == "FALSE" for row in source), "scores created")
    assert_true(all(row["shadow_rerank_created"] == "FALSE" for row in source), "rerank created")
    assert_true(all(row["proxy_activation_allowed"] == "FALSE" for row in source), "proxy activated")
    for row in source:
        assert_safety(row)
    assert_true(len(resolution) == 1, "resolution should have one row")
    row = resolution[0]
    assert_safety(row)
    assert_true(row["complete_six_family_contribution_candidate_count"] == "0", f"complete count wrong: {row}")
    assert_true(row["usable_for_shadow_rerank_count"] == "0", f"usable count wrong: {row}")
    for family in ["FUNDAMENTAL", "STRATEGY", "RISK", "MARKET_REGIME"]:
        assert_true(family in row["blocking_factor_families"], f"{family} not blocking: {row}")
    for stage in REQUIRED_STAGES:
        assert_true(stage in row["required_repair_stages"], f"{stage} missing from resolution")
    text = REPORT.read_text(encoding="utf-8")
    assert_true("wrapper_status: PASS_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER" in text, "report missing pass")
    assert_true("shadow_rerank_output_created: FALSE" in text, "report claims rerank")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_stage_plan_and_gap_map()
    test_source_requirements_and_resolution()
    print("PASS_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
