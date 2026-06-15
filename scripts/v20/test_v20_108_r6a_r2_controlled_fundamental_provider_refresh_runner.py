from __future__ import annotations

import csv
import os
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6a_r2_controlled_fundamental_provider_refresh_runner.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6a_r2_controlled_fundamental_provider_refresh_runner.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6a_r2_controlled_fundamental_provider_refresh_runner.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_CACHE = CONSOLIDATION / "V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R6A_R2_PROVIDER_REFRESH_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R6A_R2_FUNDAMENTAL_METRIC_COVERAGE_CERTIFICATION.csv"
OUT_FAILURE = CONSOLIDATION / "V20_108_R6A_R2_REFRESH_FAILURE_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R6A_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CERTIFIED",
    "PARTIAL_PASS_V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_REFRESH_NOT_ENABLED",
    "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_PROVIDER_NOT_CONFIGURED",
    "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_REFRESH_FAILED",
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


def run(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)


def default_refresh_disabled_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ENABLE_FUNDAMENTAL_REFRESH", None)
    env.pop("FUNDAMENTAL_PROVIDER_NAME", None)
    return env


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
    before_r4 = R4_SCORES.read_text(encoding="utf-8")
    before_auth = AUTHORITATIVE.read_text(encoding="utf-8") if AUTHORITATIVE.exists() else ""
    result = run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        env=default_refresh_disabled_env(),
    )
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "BLOCKED_V20_108_R6A_R2_FUNDAMENTAL_REFRESH_NOT_ENABLED",
        "PROVIDER_REFRESH_ALLOWED=FALSE",
        "PROVIDER_REFRESH_ATTEMPTED=FALSE",
        "FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE",
        "SHADOW_RERANK_OUTPUT_CREATED=FALSE",
        "OFFICIAL_RANKING_CREATED=FALSE",
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
    assert_true(before_r4 == R4_SCORES.read_text(encoding="utf-8"), "R4 scores mutated")
    if AUTHORITATIVE.exists():
        assert_true(before_auth == AUTHORITATIVE.read_text(encoding="utf-8"), "authoritative ranking overwritten")
    for path in [OUT_CACHE, OUT_AUDIT, OUT_CERT, OUT_FAILURE, OUT_GATE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_cache_and_audit_contract() -> None:
    cache = read_csv(OUT_CACHE)
    audit = read_csv(OUT_AUDIT)
    assert_true(len(cache) == 315, "all 315 candidates not represented")
    assert_true(len(audit) == 1, "provider audit should have one row")
    assert_true(audit[0]["provider_refresh_attempted"] == "FALSE", "provider refresh attempted without enable flag")
    assert_true(audit[0]["provider_refresh_allowed"] == "FALSE", "provider refresh allowed without enable flag")
    assert_true(audit[0]["source_rank_or_score_used_as_fundamental"] == "FALSE", "source score used")
    assert_true(audit[0]["baseline_rank_used_as_fundamental"] == "FALSE", "baseline rank used")
    assert_true(audit[0]["fabricated_values_created"] == "FALSE", "fabricated values")
    for row in cache + audit:
        assert_safety(row)
    for row in cache:
        assert_true(row["fundamental_metric_certification_status"] == "FUNDAMENTAL_REFRESH_NOT_ENABLED", f"wrong no-refresh status: {row}")
        assert_true(all(row[metric] == "" for metric in METRICS), f"metric fabricated while refresh disabled: {row}")


def test_certification_gate_and_report() -> None:
    cert = read_csv(OUT_CERT)
    failures = read_csv(OUT_FAILURE)
    gate = read_csv(OUT_GATE)
    assert_true(len(cert) == 1, "certification should have one row")
    assert_true(len(gate) == 1, "next stage gate should have one row")
    assert_true(len(failures) == 315, "failure audit should preserve candidate scope in blocked run")
    assert_true(cert[0]["candidate_count"] == "315", "cert candidate count wrong")
    threshold = int(cert[0]["candidates_meeting_minimum_metric_threshold"])
    ready = cert[0]["fundamental_score_materialization_ready"] == "TRUE"
    assert_true(ready == (threshold == 315), "readiness not tied to enough real ticker-level metrics")
    assert_true(gate[0]["next_stage_allowed"] == "FALSE", "next stage allowed while blocked")
    for row in cert + failures + gate:
        assert_safety(row)
    text = REPORT.read_text(encoding="utf-8")
    for marker in [
        "provider_refresh_attempted: FALSE",
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
    test_cache_and_audit_contract()
    test_certification_gate_and_report()
    print("PASS_V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_RUNNER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
