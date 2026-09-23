from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r3_candidate_factor_family_score_materialization_plan.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r3_candidate_factor_family_score_materialization_plan.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r3_candidate_factor_family_score_materialization_plan.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R2_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_PLAN = CONSOLIDATION / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN.csv"
OUT_MAPPING = CONSOLIDATION / "V20_108_R3_FACTOR_FAMILY_SOURCE_COLUMN_MAPPING_PLAN.csv"
OUT_PROXY = CONSOLIDATION / "V20_108_R3_SAFE_PROXY_ELIGIBILITY_AUDIT.csv"
OUT_BLOCKER = CONSOLIDATION / "V20_108_R3_MATERIALIZATION_BLOCKER_AUDIT.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R3_NEXT_STAGE_RECOMMENDATION.csv"
REPORT = READ_CENTER / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_CREATED",
    "PARTIAL_PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_WITH_BLOCKERS",
    "BLOCKED_V20_108_R3_NO_SAFE_MATERIALIZATION_PATHS_FOUND",
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
    before_r2 = R2_EXPANDED.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("FINAL_CONTRIBUTION_SCORES_CREATED=FALSE" in result.stdout, "scores materialized")
    assert_true("CONTRIBUTION_SCORES_FABRICATED=FALSE" in result.stdout, "scores fabricated")
    assert_true("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE" in result.stdout, "source score used")
    assert_true("BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE" in result.stdout, "baseline rank used")
    assert_true("SHADOW_RERANK_OUTPUT_CREATED=FALSE" in result.stdout, "shadow rerank created")
    assert_true("OFFICIAL_RANKING_CREATED=FALSE" in result.stdout, "official ranking created")
    assert_true("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE" in result.stdout, "authoritative ranking overwritten")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 weights mutated")
    assert_true(before_r2 == R2_EXPANDED.read_text(encoding="utf-8"), "R2 contributions mutated")
    for path in [OUT_PLAN, OUT_MAPPING, OUT_PROXY, OUT_BLOCKER, OUT_NEXT, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_plan_contract() -> None:
    plan = read_csv(OUT_PLAN)
    assert_true({row["factor_family"] for row in plan} == FAMILIES, "all six families not represented")
    by_family = {row["factor_family"]: row for row in plan}
    assert_true("PARTIAL_EXISTING_CONTRIBUTION_FAMILY" in by_family["TECHNICAL"]["current_coverage_status"], "technical partial existing coverage not recognized")
    assert_true("PARTIAL_EXISTING_CONTRIBUTION_FAMILY" in by_family["DATA_TRUST"]["current_coverage_status"], "data trust partial existing coverage not recognized")
    assert_true(by_family["RISK"]["current_candidate_coverage_count"] == "11", f"risk 11-candidate coverage not recognized: {by_family['RISK']}")
    for family in ["FUNDAMENTAL", "STRATEGY", "MARKET_REGIME"]:
        assert_true(by_family[family]["current_candidate_coverage_count"] == "0", f"{family} missing coverage not represented")
        assert_true(by_family[family]["materialization_allowed_now"] == "FALSE", f"{family} materialization allowed now")
    for row in plan:
        assert_safety(row)
        assert_true(row["materialization_allowed_now"] == "FALSE", f"R3 materialization allowed: {row}")


def test_mapping_proxy_blocker_contract() -> None:
    mapping = read_csv(OUT_MAPPING)
    proxy = read_csv(OUT_PROXY)
    blockers = read_csv(OUT_BLOCKER)
    next_rows = read_csv(OUT_NEXT)
    assert_true(mapping, "mapping plan empty")
    assert_true({row["factor_family"] for row in proxy} == FAMILIES, "proxy audit missing families")
    assert_true(all(row["source_rank_or_score_used_as_contribution"] == "FALSE" for row in mapping), "source score used in mapping")
    assert_true(all(row["materialization_allowed"] == "FALSE" for row in mapping), "mapping materializes in R3")
    assert_true(all(row["operator_approval_required"] == "TRUE" for row in proxy), "safe proxies do not require approval")
    assert_true(all(row["proxy_activation_allowed"] == "FALSE" for row in proxy), "proxy activation allowed")
    assert_true(blockers, "blocker audit empty")
    assert_true(all("source_rank_or_score" in row["unsafe_action_forbidden"] for row in blockers), "unsafe source score action not forbidden")
    for row in mapping + proxy + blockers + next_rows:
        assert_safety(row)
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("final_contribution_scores_created: FALSE" in text, "report claims scores created")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_plan_contract()
    test_mapping_proxy_blocker_contract()
    print("PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
