from __future__ import annotations

import csv
import os
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r8_r2_controlled_market_regime_exposure_metadata_refresh_and_cache_certification.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r8_r2_controlled_market_regime_exposure_metadata_refresh_and_cache_certification.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r8_r2_controlled_market_regime_exposure_metadata_refresh_and_cache_certification.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_R1_SOURCE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_CACHE = CONSOLIDATION / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_CACHE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_PROVIDER_AUDIT.csv"
OUT_CERT = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_COVERAGE_CERTIFICATION.csv"
OUT_FAILURE = CONSOLIDATION / "V20_108_R8_R2_EXPOSURE_METADATA_FAILURE_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_R2_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_CERTIFIED",
    "PARTIAL_PASS_V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_REFRESH_NOT_ENABLED",
    "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_PROVIDER_NOT_CONFIGURED",
    "BLOCKED_V20_108_R8_R2_MARKET_REGIME_EXPOSURE_REFRESH_FAILED",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def disabled_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ENABLE_MARKET_REGIME_EXPOSURE_REFRESH", None)
    env.pop("MARKET_REGIME_EXPOSURE_PROVIDER_NAME", None)
    env.pop("MARKET_REGIME_EXPOSURE_INPUT_PATH", None)
    env.pop("MARKET_REGIME_EXPOSURE_PROVIDER_INPUT_PATH", None)
    return env


def run(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)


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
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], env=disabled_env())
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "PROVIDER_REFRESH_ALLOWED=FALSE",
        "PROVIDER_REFRESH_ATTEMPTED=FALSE",
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "GLOBAL_REGIME_COPIED_WITHOUT_EXPOSURE_CONDITIONING=FALSE",
        "MARKET_REGIME_CONTRIBUTION_CREATED=FALSE",
        "ENTRY_EXIT_PRICES_CREATED=FALSE",
        "BUY_SELL_RECOMMENDATIONS_CREATED=FALSE",
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
    for path in [OUT_CACHE, OUT_AUDIT, OUT_CERT, OUT_FAILURE, OUT_GATE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_cache_scope_and_safety() -> None:
    cache = read_csv(OUT_CACHE)
    audit = read_csv(OUT_AUDIT)
    cert = read_csv(OUT_CERT)
    r8_r1 = read_csv(R8_R1_SOURCE)
    assert_true(len(cache) == 315, "all 315 candidates not represented")
    carried_expected = {row["ticker"] for row in r8_r1 if row["carried_forward_from_r8"] == "TRUE" and row["market_regime_contribution"]}
    carried_cache = {row["ticker"] for row in cache if row["exposure_metadata_certification_status"] == "EXPOSURE_CARRIED_FORWARD_FROM_R8"}
    assert_true(carried_expected == carried_cache, "R8 ETF exposures not carried forward")
    for row in cache + audit + cert:
        assert_safety(row)
    assert_true(audit[0]["provider_refresh_attempted"] == "FALSE", "provider refresh attempted without flag")
    assert_true(audit[0]["source_rank_or_score_used_as_market_regime"] == "FALSE", "source score used")
    assert_true(audit[0]["baseline_rank_used_as_market_regime"] == "FALSE", "baseline rank used")
    assert_true(audit[0]["fabricated_values_created"] == "FALSE", "fabricated metadata")
    assert_true(audit[0]["global_regime_copied_without_exposure_conditioning"] == "FALSE", "global regime copied")
    assert_true(audit[0]["market_regime_contribution_created"] == "FALSE", "contribution created")
    assert_true(all(row["market_regime_contribution_created"] == "FALSE" for row in cache), "cache contribution created")


def test_gate_and_report() -> None:
    cert = read_csv(OUT_CERT)
    failures = read_csv(OUT_FAILURE)
    gate = read_csv(OUT_GATE)
    assert_true(len(cert) == 1, "cert should have one row")
    assert_true(len(gate) == 1, "gate should have one row")
    threshold = int(cert[0]["candidates_meeting_minimum_metadata_threshold"])
    ready = cert[0]["market_regime_materialization_ready"] == "TRUE"
    assert_true(ready == (threshold == 315), "readiness not tied to full real metadata threshold coverage")
    assert_true(gate[0]["next_stage_allowed"] == ("TRUE" if ready else "FALSE"), "next stage allowance mismatch")
    for row in failures + gate:
        assert_safety(row)
    text = REPORT.read_text(encoding="utf-8")
    for marker in [
        "source_rank_or_score_used: FALSE",
        "baseline_rank_used: FALSE",
        "fabricated_values_created: FALSE",
        "global_regime_copied_without_exposure_conditioning: FALSE",
        "market_regime_contribution_created: FALSE",
        "entry_exit_prices_created: FALSE",
        "buy_sell_recommendations_created: FALSE",
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
    test_cache_scope_and_safety()
    test_gate_and_report()
    print("PASS_V20_108_R8_R2_CONTROLLED_MARKET_REGIME_EXPOSURE_METADATA_REFRESH_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
