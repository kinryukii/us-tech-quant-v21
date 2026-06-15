from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6a_r3_fundamental_refresh_coverage_repair_and_local_patch_gate.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6a_r3_fundamental_refresh_coverage_repair_and_local_patch_gate.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6a_r3_fundamental_refresh_coverage_repair_and_local_patch_gate.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_REPAIR = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AUDIT.csv"
OUT_PATCH_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_LOCAL_PATCH_TEMPLATE.csv"
OUT_PATCH_GATE = CONSOLIDATION / "V20_108_R6A_R3_FUNDAMENTAL_PATCH_IMPORT_GATE_AUDIT.csv"
OUT_PARTIAL_GATE = CONSOLIDATION / "V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R6A_R3_NEXT_REPAIR_ACTION.csv"
REPORT = READ_CENTER / "V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_GATE",
    "PARTIAL_PASS_V20_108_R6A_R3_WAITING_FOR_LOCAL_PATCH",
    "PASS_V20_108_R6A_R3_PARTIAL_MATERIALIZATION_GATE_APPROVED",
    "BLOCKED_V20_108_R6A_R3_INSUFFICIENT_CERTIFIED_FUNDAMENTAL_COVERAGE",
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
    before_research = V49_RESEARCH.read_text(encoding="utf-8")
    before_official = V49_OFFICIAL.read_text(encoding="utf-8")
    before_v107 = V107_WEIGHTS.read_text(encoding="utf-8")
    before_r5 = R5_REGISTRY.read_text(encoding="utf-8")
    before_auth = AUTHORITATIVE.read_text(encoding="utf-8") if AUTHORITATIVE.exists() else ""
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "EXTERNAL_REFRESH_ATTEMPTED=FALSE",
        "SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE",
        "BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE",
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
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_research == V49_RESEARCH.read_text(encoding="utf-8"), "V20.49 research gate mutated")
    assert_true(before_official == V49_OFFICIAL.read_text(encoding="utf-8"), "V20.49 official gate mutated")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "active research base weights mutated")
    if AUTHORITATIVE.exists():
        assert_true(before_auth == AUTHORITATIVE.read_text(encoding="utf-8"), "authoritative ranking overwritten")
    for path in [OUT_REPAIR, OUT_PATCH_TEMPLATE, OUT_PATCH_GATE, OUT_PARTIAL_GATE, OUT_NEXT, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_repair_scope_and_patch_template() -> None:
    repair = read_csv(OUT_REPAIR)
    patch_template = read_csv(OUT_PATCH_TEMPLATE)
    non_certified = [row for row in repair if row["fundamental_metric_certification_status"] != "FUNDAMENTAL_METRICS_CERTIFIED"]
    assert_true(len(repair) == 315, "all 315 candidates not represented in repair audit")
    assert_true(len(non_certified) > 0, "non-certified candidates not identified")
    assert_true(len(patch_template) == len(non_certified), "patch template should include only non-certified candidates")
    assert_true({row["ticker"] for row in patch_template} == {row["ticker"] for row in non_certified}, "patch template ticker scope wrong")
    for row in repair + patch_template:
        assert_safety(row)
    assert_true(all(row["local_patch_required"] == "TRUE" for row in non_certified), "non-certified rows should require patch or exclusion")
    assert_true(all(row["partial_materialization_eligible"] == "TRUE" for row in repair if row["fundamental_metric_certification_status"] == "FUNDAMENTAL_METRICS_CERTIFIED"), "certified rows not eligible")


def test_gates_and_report_safety() -> None:
    patch_gate = read_csv(OUT_PATCH_GATE)
    partial_gate = read_csv(OUT_PARTIAL_GATE)
    next_rows = read_csv(OUT_NEXT)
    assert_true(len(patch_gate) == 3, "patch import gate should inspect three optional paths")
    assert_true(len(partial_gate) == 1, "partial materialization gate should have one row")
    gate = partial_gate[0]
    threshold_met = float(gate["certified_coverage_ratio"]) >= float(gate["partial_materialization_threshold"])
    safety_met = (
        gate["certified_candidates_usable"] == "TRUE"
        and gate["partial_candidates_excluded_or_pending_patch"] == "TRUE"
        and gate["missing_candidates_excluded_or_pending_patch"] == "TRUE"
    )
    assert_true((gate["partial_materialization_allowed"] == "TRUE") == (threshold_met and safety_met), "partial materialization allowance not tied to threshold and safety")
    assert_true(gate["fundamental_score_materialization_ready"] == "FALSE", "full materialization readiness should remain false")
    for row in patch_gate + partial_gate + next_rows:
        assert_safety(row)
    assert_true(all(row["source_rank_or_score_used_as_fundamental"] == "FALSE" for row in patch_gate), "source score used")
    assert_true(all(row["baseline_rank_used_as_fundamental"] == "FALSE" for row in patch_gate), "baseline rank used as metric")
    assert_true(all(row["fabricated_values_created"] == "FALSE" for row in patch_gate), "fabricated values")
    assert_true(all(row["proxy_values_activated"] == "FALSE" for row in patch_gate), "proxy values activated")
    text = REPORT.read_text(encoding="utf-8")
    for marker in [
        "external_refresh_attempted: FALSE",
        "source_rank_or_score_used_as_fundamental: FALSE",
        "baseline_rank_used_as_fundamental: FALSE",
        "fabricated_values_created: FALSE",
        "proxy_values_activated: FALSE",
        "fundamental_contribution_scores_created: FALSE",
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
    test_repair_scope_and_patch_template()
    test_gates_and_report_safety()
    print("PASS_V20_108_R6A_R3_FUNDAMENTAL_REFRESH_COVERAGE_REPAIR_AND_LOCAL_PATCH_GATE_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
