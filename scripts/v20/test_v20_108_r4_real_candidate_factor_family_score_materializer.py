from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r4_real_candidate_factor_family_score_materializer.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r4_real_candidate_factor_family_score_materializer.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r4_real_candidate_factor_family_score_materializer.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R2_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R4_FACTOR_FAMILY_SCORE_MATERIALIZATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R4_CANDIDATE_CONTRIBUTION_COVERAGE_AFTER_MATERIALIZATION.csv"
OUT_READINESS = CONSOLIDATION / "V20_108_R4_SHADOW_RERANK_READINESS_AFTER_MATERIALIZATION.csv"
REPORT = READ_CENTER / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER",
    "PARTIAL_PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_WITH_PARTIAL_FAMILY_COVERAGE",
    "BLOCKED_V20_108_R4_NO_REAL_MATERIALIZABLE_CANDIDATE_FACTOR_SCORES",
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
    for marker in [
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE",
        "BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "CONTRIBUTION_SCORES_FABRICATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
    ]:
        assert_true(marker in result.stdout, f"missing marker {marker}")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 weights mutated")
    assert_true(before_r2 == R2_EXPANDED.read_text(encoding="utf-8"), "R2 contributions mutated")
    for path in [OUT_SCORES, OUT_AUDIT, OUT_COVERAGE, OUT_READINESS, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_scores_and_coverage_contract() -> None:
    scores = read_csv(OUT_SCORES)
    r2 = {row["ticker"]: row for row in read_csv(R2_EXPANDED)}
    candidates = read_csv(V48_CANDIDATES)
    coverage = {row["factor_family"]: row for row in read_csv(OUT_COVERAGE)}
    assert_true(len(scores) == len(candidates) == 315, "all candidates not represented")
    assert_true(set(coverage) == FAMILIES, "all families not represented in coverage")
    for row in scores:
        assert_safety(row)
        original = r2[row["ticker"]]
        assert_true(row["technical_contribution"] == original["technical_contribution"], f"technical not from R2 real value: {row}")
        assert_true(row["data_trust_contribution"] == original["data_trust_contribution"], f"data trust not from R2 real value: {row}")
        assert_true(row["fundamental_contribution"] == "", f"fundamental fabricated: {row}")
        assert_true(row["strategy_contribution"] == "", f"strategy fabricated: {row}")
        assert_true(row["market_regime_contribution"] == "", f"market regime fabricated: {row}")
        assert_true(row["risk_contribution"] == original["risk_contribution"], f"risk not limited to R2 real value: {row}")
        complete = all(row[col] for col in [
            "fundamental_contribution", "technical_contribution", "strategy_contribution",
            "risk_contribution", "market_regime_contribution", "data_trust_contribution",
        ])
        assert_true(row["usable_for_shadow_rerank"] == ("TRUE" if complete else "FALSE"), f"usable flag wrong: {row}")
    assert_true(coverage["TECHNICAL"]["materialized_candidate_count"] == "315", "technical count wrong")
    assert_true(coverage["DATA_TRUST"]["materialized_candidate_count"] == "315", "data trust count wrong")
    assert_true(coverage["RISK"]["materialized_candidate_count"] == "11", "risk count wrong")
    for family in ["FUNDAMENTAL", "STRATEGY", "MARKET_REGIME"]:
        assert_true(coverage[family]["materialized_candidate_count"] == "0", f"{family} fabricated")


def test_audit_and_readiness_contract() -> None:
    audit = read_csv(OUT_AUDIT)
    readiness = read_csv(OUT_READINESS)
    assert_true({row["factor_family"] for row in audit} == FAMILIES, "audit missing families")
    for row in audit:
        assert_safety(row)
        assert_true(row["used_source_rank_or_score"] == "FALSE", f"source rank used: {row}")
        assert_true(row["used_baseline_rank"] == "FALSE", f"baseline rank used: {row}")
        assert_true(row["used_proxy"] == "FALSE", f"proxy used: {row}")
        assert_true(row["fabricated_values_created"] == "FALSE", f"fabricated values: {row}")
    assert_true(len(readiness) == 1, "readiness should have one row")
    row = readiness[0]
    assert_safety(row)
    assert_true(row["candidate_count"] == "315", f"wrong candidate count: {row}")
    assert_true(row["usable_for_shadow_rerank_count"] == row["complete_six_family_contribution_candidate_count"], f"usable count mismatch: {row}")
    assert_true(row["shadow_rerank_readiness_status"] != "READY_FOR_SHADOW_RERANK", "ready despite incomplete families")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("shadow_rerank_output_created: FALSE" in text, "report claims rerank")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_scores_and_coverage_contract()
    test_audit_and_readiness_contract()
    print("PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
