from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

SNAP_CACHE = CONSOLIDATION / "snapshots" / "V20_108_R6A_R2_ENABLED_REFRESH_CACHE.csv"
R3_REPAIR = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AUDIT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_SCORE_COMPONENT_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_MATERIALIZATION_VALIDATION.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R6B_FACTOR_FAMILY_COVERAGE_AFTER_FUNDAMENTAL.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R6B_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE",
    "PARTIAL_PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_EXCLUSIONS",
    "BLOCKED_V20_108_R6B_NO_CERTIFIED_FUNDAMENTAL_METRICS_AVAILABLE",
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
    before_research = V49_RESEARCH.read_text(encoding="utf-8")
    before_official = V49_OFFICIAL.read_text(encoding="utf-8")
    before_v107 = V107_WEIGHTS.read_text(encoding="utf-8")
    before_r5 = R5_REGISTRY.read_text(encoding="utf-8")
    before_auth = AUTHORITATIVE.read_text(encoding="utf-8") if AUTHORITATIVE.exists() else ""
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
        "OFFICIAL_PROMOTION_ALLOWED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "IS_OFFICIAL_WEIGHT=FALSE",
        "WEIGHT_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
    ]:
        assert_true(marker in result.stdout, f"missing marker {marker}")
    assert_true(before_research == V49_RESEARCH.read_text(encoding="utf-8"), "V20.49 research gate mutated")
    assert_true(before_official == V49_OFFICIAL.read_text(encoding="utf-8"), "V20.49 official gate mutated")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "active research base weights mutated")
    if AUTHORITATIVE.exists():
        assert_true(before_auth == AUTHORITATIVE.read_text(encoding="utf-8"), "authoritative ranking overwritten")
    for path in [OUT_SOURCE, OUT_COMPONENT, OUT_VALIDATION, OUT_COVERAGE, OUT_GATE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_materialization_scope() -> None:
    source = read_csv(OUT_SOURCE)
    snap = read_csv(SNAP_CACHE)
    repair = read_csv(R3_REPAIR)
    certified = {row["ticker"] for row in snap if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED"}
    non_certified = {row["ticker"] for row in snap if row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_CERTIFIED"}
    assert_true(len(source) == len(snap) == 315, "all 315 candidates not represented")
    for row in source:
        assert_safety(row)
        if row["ticker"] in certified:
            assert_true(row["fundamental_contribution"] != "", f"certified candidate not materialized: {row}")
            assert_true(row["fundamental_materialization_status"] == "MATERIALIZED_FROM_CERTIFIED_REAL_METRICS", f"bad certified status: {row}")
        else:
            assert_true(row["fundamental_contribution"] == "", f"non-certified candidate materialized: {row}")
            assert_true(row["fundamental_materialization_status"] in {"EXCLUDED_NON_EQUITY_OR_FUNDAMENTAL_NOT_APPLICABLE", "PENDING_LOCAL_PATCH", "MISSING_CERTIFIED_METRICS"}, f"bad non-certified status: {row}")
    repair_non_cert = {row["ticker"] for row in repair if row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_CERTIFIED"}
    assert_true(non_certified == repair_non_cert, "R6B non-certified scope does not match R6A-R3 repair scope")


def test_audits_gates_and_report() -> None:
    component = read_csv(OUT_COMPONENT)
    validation = read_csv(OUT_VALIDATION)
    coverage = read_csv(OUT_COVERAGE)
    gate = read_csv(OUT_GATE)
    assert_true(component, "component audit empty")
    assert_true(len(validation) == 1, "validation should have one row")
    assert_true(len(gate) == 1, "next stage gate should have one row")
    for row in component + validation + coverage + gate:
        assert_safety(row)
    assert_true(all(row["fabricated_values_created"] == "FALSE" for row in component), "fabricated component values")
    assert_true(all(row["proxy_values_activated"] == "FALSE" for row in component), "proxy component values")
    v = validation[0]
    assert_true(v["source_rank_or_score_used"] == "FALSE", "source score used")
    assert_true(v["baseline_rank_used"] == "FALSE", "baseline rank used")
    assert_true(v["fabricated_values_created"] == "FALSE", "fabricated values")
    assert_true(v["proxy_values_activated"] == "FALSE", "proxy values")
    assert_true(v["shadow_rerank_output_created"] == "FALSE", "shadow rerank created")
    assert_true(v["official_ranking_created"] == "FALSE", "official ranking created")
    assert_true(v["authoritative_ranking_overwritten"] == "FALSE", "authoritative ranking overwritten")
    assert_true(gate[0]["next_stage_allowed"] == "FALSE", "next stage should remain blocked")
    assert_true(gate[0]["complete_six_family_contribution_candidate_count"] == "0", "complete six-family contribution should remain blocked")
    assert_true(gate[0]["usable_for_shadow_rerank_count"] == "0", "shadow rerank should remain blocked")
    text = REPORT.read_text(encoding="utf-8")
    for marker in [
        "source_rank_or_score_used: FALSE",
        "baseline_rank_used: FALSE",
        "fabricated_values_created: FALSE",
        "proxy_values_activated: FALSE",
        "shadow_rerank_output_created: FALSE",
        "official_ranking_created: FALSE",
        "authoritative_ranking_overwritten: FALSE",
        "official_promotion_allowed: FALSE",
        "official_recommendation_created: FALSE",
        "is_official_weight: FALSE",
        "weight_mutated: FALSE",
        "trade_action_created: FALSE",
        "broker_execution_supported: FALSE",
        "v20_49_research_only_gate_status: PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE",
        "v20_49_official_promotion_gate_status: BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE",
    ]:
        assert_true(marker in text, f"report missing marker {marker}")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_materialization_scope()
    test_audits_gates_and_report()
    print("PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
