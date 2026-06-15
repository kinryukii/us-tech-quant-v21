from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6a_controlled_fundamental_candidate_metric_refresh_and_cache_certification.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6a_controlled_fundamental_candidate_metric_refresh_and_cache_certification.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6a_controlled_fundamental_candidate_metric_refresh_and_cache_certification.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_CACHE = CONSOLIDATION / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_SOURCE_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
OUT_REPAIR = CONSOLIDATION / "V20_108_R6A_FUNDAMENTAL_REFRESH_REPAIR_PLAN.csv"
REPORT = READ_CENTER / "V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_REFRESH_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_CERTIFIED",
    "PARTIAL_PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_108_R6A_NO_FUNDAMENTAL_REFRESH_SOURCE_CONFIGURED",
    "BLOCKED_V20_108_R6A_FUNDAMENTAL_REFRESH_FAILED",
}
METRICS = [
    "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
    "profit_margin", "return_on_equity", "return_on_assets", "operating_cashflow",
    "free_cashflow", "capital_expenditures", "debt_to_equity", "current_ratio",
    "quick_ratio", "market_cap", "enterprise_value", "trailing_pe", "forward_pe",
    "price_to_sales", "price_to_book", "ev_to_ebitda", "ebitda_margin",
    "revenue_ttm", "net_income_ttm", "total_debt", "total_cash",
]


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
        "FUNDAMENTAL_CONTRIBUTION_CREATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE",
        "BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
        "AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE",
    ]:
        assert_true(marker in result.stdout, f"missing marker {marker}")
    assert_true(before_candidates == V48_CANDIDATES.read_text(encoding="utf-8"), "candidate ranking overwritten")
    assert_true(before_v107 == V107_WEIGHTS.read_text(encoding="utf-8"), "V20.107 weights mutated")
    assert_true(before_r5 == R5_REGISTRY.read_text(encoding="utf-8"), "R5 weights mutated")
    assert_true(before_r4 == R4_SCORES.read_text(encoding="utf-8"), "R4 scores mutated")
    for path in [OUT_CACHE, OUT_AUDIT, OUT_CERT, OUT_REPAIR, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_cache_contract() -> None:
    rows = read_csv(OUT_CACHE)
    candidates = read_csv(V48_CANDIDATES)
    assert_true(len(rows) == len(candidates) == 315, "all candidates not represented")
    for row in rows:
        assert_safety(row)
        assert_true("fundamental_contribution" not in row, "fundamental contribution created")
        present = int(row["present_numeric_metric_count"])
        assert_true(present == sum(1 for metric in METRICS if row[metric] != ""), f"present metric count mismatch: {row}")
        if present == 0:
            assert_true(row["fundamental_metric_certification_status"] in {"FUNDAMENTAL_REFRESH_NOT_CONFIGURED", "FUNDAMENTAL_REFRESH_FAILED", "FUNDAMENTAL_METRICS_MISSING"}, f"bad missing status: {row}")


def test_audit_certification_repair_contract() -> None:
    audit = read_csv(OUT_AUDIT)
    cert = read_csv(OUT_CERT)
    repair = read_csv(OUT_REPAIR)
    assert_true(audit, "audit empty")
    assert_true(all(row["source_rank_or_score_used_as_fundamental"] == "FALSE" for row in audit), "source score used")
    assert_true(all(row["baseline_rank_used_as_fundamental"] == "FALSE" for row in audit), "baseline rank used")
    assert_true(all(row["fabricated_values_created"] == "FALSE" for row in audit), "fabricated metrics")
    for row in audit + cert + repair:
        assert_safety(row)
    assert_true(len(cert) == 1, "certification should have one row")
    row = cert[0]
    assert_true(row["candidate_count"] == "315", f"wrong candidate count: {row}")
    ready = row["fundamental_score_materialization_ready"] == "TRUE"
    enough = int(row["candidates_meeting_minimum_metric_threshold"]) == 315
    assert_true(ready == enough, f"readiness not tied to metric coverage: {row}")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    assert_true("fundamental_contribution_created: FALSE" in text, "report claims contribution")


def main() -> int:
    py_compile.compile(str(SCRIPT), doraise=True)
    py_compile.compile(str(TEST_SCRIPT), doraise=True)
    parse_wrapper()
    test_wrapper_runs_and_outputs_created()
    test_cache_contract()
    test_audit_certification_repair_contract()
    print("PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
