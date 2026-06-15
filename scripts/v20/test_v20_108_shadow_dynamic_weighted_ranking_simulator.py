from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_shadow_dynamic_weighted_ranking_simulator.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_shadow_dynamic_weighted_ranking_simulator.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_shadow_dynamic_weighted_ranking_simulator.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"

OUT_RANKING = CONSOLIDATION / "V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING.csv"
OUT_CHANGE = CONSOLIDATION / "V20_108_SHADOW_RANK_CHANGE_AUDIT.csv"
OUT_INPUT = CONSOLIDATION / "V20_108_SHADOW_RANKING_INPUT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_SHADOW_RANKING_VALIDATION.csv"
REPORT = READ_CENTER / "V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR",
    "PARTIAL_PASS_V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR_WITH_LIMITED_CANDIDATE_FACTOR_GRANULARITY",
}
SCOPE = "RESEARCH_ONLY_SHADOW_FACTOR_FAMILY"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_safety(row: dict[str, str]) -> None:
    assert_true(row.get("research_only", "TRUE") == "TRUE", f"research_only false: {row}")
    assert_true(row["official_promotion_allowed"] == "FALSE", f"promotion allowed: {row}")
    assert_true(row["official_recommendation_created"] == "FALSE", f"recommendation created: {row}")
    assert_true(row.get("is_official_ranking", "FALSE") == "FALSE", f"official ranking claimed: {row}")
    assert_true(row.get("is_official_weight", "FALSE") == "FALSE", f"official weight claimed: {row}")
    assert_true(row["weight_mutated"] == "FALSE", f"weight mutation claimed: {row}")
    assert_true(row["trade_action_created"] == "FALSE", f"trade action claimed: {row}")
    assert_true(row["broker_execution_supported"] == "FALSE", f"broker execution claimed: {row}")


def parse_wrapper() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{WRAPPER.as_posix()}', [ref]$tokens, [ref]$errors) > $null;"
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command])
    assert_true(result.returncode == 0, f"PowerShell parser failed: {result.stdout}\n{result.stderr}")


def test_wrapper_runs_and_outputs_created() -> None:
    before_r5 = R5_REGISTRY.read_text(encoding="utf-8")
    before_v107 = V107_WEIGHTS.read_text(encoding="utf-8")
    before_candidates = V48_CANDIDATES.read_text(encoding="utf-8")
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    assert_true("SHADOW_WEIGHTS_AVAILABLE=TRUE" in result.stdout, "V20.107 shadow weights not recognized")
    assert_true("V20_107_LIMITED_FACTOR_GRANULARITY_RECOGNIZED=TRUE" in result.stdout, "V20.107 limited granularity not recognized")
    assert_true("FACTOR_LEVEL_WEIGHTS_CREATED=FALSE" in result.stdout, "factor-level weights created")
    assert_true("CANDIDATE_FACTOR_SCORES_FABRICATED=FALSE" in result.stdout, "candidate factor scores fabricated")
    assert_true("OFFICIAL_RANKING_CREATED=FALSE" in result.stdout, "official ranking created")
    assert_true("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE" in result.stdout, "authoritative ranking overwritten")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 base weights mutated")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 shadow weights mutated")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "authoritative candidate ranking overwritten")
    for path in [OUT_RANKING, OUT_CHANGE, OUT_INPUT, OUT_VALIDATION, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_shadow_ranking_contract() -> None:
    ranking = read_csv(OUT_RANKING)
    changes = read_csv(OUT_CHANGE)
    candidates = read_csv(V48_CANDIDATES)
    assert_true(len(ranking) == len(candidates), "candidate rows not represented")
    assert_true(len(changes) == len(candidates), "rank change rows not represented")
    assert_true(all(row["candidate_factor_granularity_status"] == "LIMITED_CANDIDATE_FACTOR_GRANULARITY" for row in ranking), "limited candidate granularity not recorded")
    assert_true(all(row["dynamic_weight_scope"] == SCOPE for row in ranking), "wrong dynamic weight scope")
    assert_true(all(row["shadow_weight_confidence"] == "PARTIAL" for row in ranking), "partial shadow confidence not preserved")
    assert_true(all(int(row["baseline_rank"]) == int(row["shadow_dynamic_rank"]) for row in ranking), "baseline rank not preserved under limited granularity fallback")
    assert_true(all(row["rank_change"] == "0" for row in ranking), "rank change fabricated under limited granularity fallback")
    for row in ranking + changes:
        assert_safety(row)
    assert_true(all(row["candidate_score_source_status"] != "CANDIDATE_FACTOR_FAMILY_SCORE_AVAILABLE" for row in changes), "candidate factor score availability fabricated")


def test_input_audit_and_validation() -> None:
    inputs = read_csv(OUT_INPUT)
    validation = read_csv(OUT_VALIDATION)
    assert_true(inputs, "input audit empty")
    assert_true(any(row["shadow_weights_recognized"] == "TRUE" for row in inputs), "shadow weights not audited")
    assert_true(any(row["v20_107_limited_factor_granularity_recognized"] == "TRUE" for row in inputs), "V20.107 limited granularity not audited")
    assert_true(all(row["source_rank_or_score_used_as_factor_weight"] == "FALSE" for row in inputs), "source_rank_or_score used as factor weight")
    assert_true(all(row["candidate_factor_scores_fabricated"] == "FALSE" for row in inputs), "candidate factor scores fabricated")
    assert_true(all(row["factor_level_weights_created"] == "FALSE" for row in inputs), "factor-level weights created")
    assert_true(all(row["authoritative_ranking_overwritten"] == "FALSE" for row in inputs), "authoritative ranking overwritten")
    for row in inputs:
        assert_safety(row)
    assert_true(len(validation) == 1, "validation should have one row")
    row = validation[0]
    assert_safety(row)
    assert_true(row["candidate_count"] == row["shadow_rank_count"], f"rank count mismatch: {row}")
    assert_true(row["shadow_weights_available"] == "TRUE", f"shadow weights unavailable: {row}")
    assert_true(row["shadow_weight_sum_valid"] == "TRUE", f"shadow weight sum invalid: {row}")
    assert_true(row["factor_level_weights_created"] == "FALSE", f"factor-level weights created: {row}")
    assert_true(row["candidate_factor_granularity_status"] == "LIMITED_CANDIDATE_FACTOR_GRANULARITY", f"wrong granularity: {row}")
    assert_true(row["official_ranking_created"] == "FALSE", f"official ranking created: {row}")
    assert_true(row["authoritative_ranking_overwritten"] == "FALSE", f"authoritative ranking overwritten: {row}")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("official_ranking_created: FALSE" in text, "report claims official ranking")
    assert_true("authoritative_ranking_overwritten: FALSE" in text, "report claims overwrite")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_shadow_ranking_contract()
    test_input_audit_and_validation()
    print("PASS_V20_108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
