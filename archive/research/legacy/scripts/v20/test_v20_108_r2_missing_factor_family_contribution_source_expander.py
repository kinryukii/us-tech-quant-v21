from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r2_missing_factor_family_contribution_source_expander.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r2_missing_factor_family_contribution_source_expander.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r2_missing_factor_family_contribution_source_expander.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R1_CONTRIB = CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
OUT_SOURCE = CONSOLIDATION / "V20_108_R2_MISSING_FACTOR_FAMILY_SOURCE_AUDIT.csv"
OUT_MATERIAL = CONSOLIDATION / "V20_108_R2_FACTOR_FAMILY_MATERIALIZATION_AUDIT.csv"
OUT_READINESS = CONSOLIDATION / "V20_108_R2_SHADOW_RERANK_READINESS_AFTER_EXPANSION.csv"
REPORT = READ_CENTER / "V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER",
    "PARTIAL_PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_WITH_PARTIAL_CONTRIBUTION_COVERAGE",
    "PARTIAL_PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_WITH_MISSING_CONTRIBUTION_DATA",
}
FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
FAMILY_COLUMNS = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
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
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE" in result.stdout, "source_rank_or_score used")
    assert_true("BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE" in result.stdout, "baseline rank used")
    assert_true("CONTRIBUTION_SCORES_FABRICATED=FALSE" in result.stdout, "fabricated contributions")
    assert_true("OFFICIAL_RANKING_CREATED=FALSE" in result.stdout, "official ranking created")
    assert_true("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE" in result.stdout, "authoritative ranking overwritten")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking artifact overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 shadow weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 base weights mutated")
    for path in [OUT_EXPANDED, OUT_SOURCE, OUT_MATERIAL, OUT_READINESS, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_expanded_contribution_contract() -> None:
    r1 = {row["ticker"]: row for row in read_csv(R1_CONTRIB)}
    expanded = read_csv(OUT_EXPANDED)
    candidates = read_csv(V48_CANDIDATES)
    assert_true(len(expanded) == len(candidates), "all candidates not represented")
    for row in expanded:
        assert_safety(row)
        original = r1[row["ticker"]]
        assert_true(row["technical_contribution"] == original["technical_contribution"], f"R1 technical not preserved: {row}")
        assert_true(row["data_trust_contribution"] == original["data_trust_contribution"], f"R1 data trust not preserved: {row}")
        materialized = [family for family, column in FAMILY_COLUMNS.items() if row[column] != ""]
        assert_true(row["usable_for_shadow_rerank"] == ("TRUE" if len(materialized) == 6 else "FALSE"), f"usable flag wrong: {row}")
        assert_true("source_rank_or_score" not in row["materialized_factor_families"].lower(), f"source score materialized: {row}")


def test_audits_and_readiness() -> None:
    source = read_csv(OUT_SOURCE)
    material = read_csv(OUT_MATERIAL)
    readiness = read_csv(OUT_READINESS)
    assert_true({row["factor_family"] for row in material} == FAMILIES, "all six families not represented in materialization audit")
    assert_true({row["factor_family"] for row in source}.issuperset({"FUNDAMENTAL", "STRATEGY", "RISK", "MARKET_REGIME"}), "missing target family source audit absent")
    assert_true(all(row["source_rank_or_score_used_as_contribution"] == "FALSE" for row in source), "source rank used in source audit")
    assert_true(all(row["source_rank_or_score_used_as_contribution"] == "FALSE" for row in material), "source rank used in material audit")
    assert_true(all(row["baseline_rank_used_as_contribution"] == "FALSE" for row in material), "baseline rank used in material audit")
    assert_true(all(row["contribution_scores_fabricated"] == "FALSE" for row in material), "fabricated scores in material audit")
    assert_true(any(row["source_classification_status"] == "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_CONTRIBUTION" for row in source), "family-level-only evidence not classified")
    for row in source + material:
        assert_safety(row)
    assert_true(len(readiness) == 1, "readiness should have one row")
    row = readiness[0]
    assert_safety(row)
    assert_true(row["candidate_count"] == "315", f"wrong candidate count: {row}")
    assert_true(row["usable_for_shadow_rerank_count"] == row["complete_six_family_contribution_candidate_count"], f"usable count mismatch: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("contribution_scores_fabricated: FALSE" in text, "report claims fabricated scores")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_expanded_contribution_contract()
    test_audits_and_readiness()
    print("PASS_V20_108_R2_MISSING_FACTOR_FAMILY_CONTRIBUTION_SOURCE_EXPANDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
