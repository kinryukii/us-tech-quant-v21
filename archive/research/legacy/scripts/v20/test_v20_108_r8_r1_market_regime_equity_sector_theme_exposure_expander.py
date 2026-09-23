from __future__ import annotations

import csv
import os
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r8_r1_market_regime_equity_sector_theme_exposure_expander.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r8_r1_market_regime_equity_sector_theme_exposure_expander.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r8_r1_market_regime_equity_sector_theme_exposure_expander.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R8_SOURCE = CONSOLIDATION / "V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE_SOURCE.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
AUTHORITATIVE = CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"

OUT_SOURCE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_EQUITY_EXPOSURE_SOURCE.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_108_R8_R1_SECTOR_THEME_SOURCE_AUDIT.csv"
OUT_MAPPING_AUDIT = CONSOLIDATION / "V20_108_R8_R1_EXPOSURE_MAPPING_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R8_R1_MARKET_REGIME_COVERAGE_AFTER_EXPANSION.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R8_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER",
    "PARTIAL_PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_WITH_PARTIAL_COVERAGE",
    "BLOCKED_V20_108_R8_R1_NO_SAFE_EQUITY_EXPOSURE_SOURCE_FOUND",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def disabled_refresh_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ENABLE_MARKET_REGIME_EXPOSURE_REFRESH", None)
    env.pop("MARKET_REGIME_EXPOSURE_PROVIDER_NAME", None)
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
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], env=disabled_refresh_env())
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "SOURCE_RANK_OR_SCORE_USED=FALSE",
        "BASELINE_RANK_USED=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
        "PROXY_VALUES_ACTIVATED=FALSE",
        "GLOBAL_REGIME_COPIED_WITHOUT_EXPOSURE_CONDITIONING=FALSE",
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
    for path in [OUT_SOURCE, OUT_SOURCE_AUDIT, OUT_MAPPING_AUDIT, OUT_COVERAGE, OUT_GATE, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_scope_carry_forward_and_mapping_safety() -> None:
    rows = read_csv(OUT_SOURCE)
    r8 = read_csv(R8_SOURCE)
    audits = read_csv(OUT_SOURCE_AUDIT)
    mapping = read_csv(OUT_MAPPING_AUDIT)
    assert_true(len(rows) == 315, "all 315 candidates not represented")
    r8_carried = {row["ticker"] for row in r8 if row["market_regime_contribution"]}
    carried = {row["ticker"] for row in rows if row["carried_forward_from_r8"] == "TRUE"}
    assert_true(r8_carried == carried, "R8 ETF/benchmark exposures not carried forward exactly")
    for row in rows + audits + mapping:
        assert_safety(row)
    assert_true(all(row["source_rank_or_score_used_as_market_regime"] == "FALSE" for row in audits), "source score used")
    assert_true(all(row["baseline_rank_used_as_market_regime"] == "FALSE" for row in audits), "baseline rank used")
    assert_true(all(row["fabricated_values_created"] == "FALSE" for row in audits + mapping), "fabricated values")
    assert_true(all(row["proxy_values_activated"] == "FALSE" for row in audits + mapping), "proxy values")
    assert_true(all(row["global_regime_copied_without_exposure_conditioning"] == "FALSE" for row in mapping), "global copied")
    for row in rows:
        if row["market_regime_contribution"] and row["carried_forward_from_r8"] == "FALSE":
            assert_true(row["exposure_source_artifact"], f"new materialization without source artifact: {row}")
            assert_true(row["exposure_mapping_method"].startswith("DETERMINISTIC"), f"new materialization without deterministic mapping: {row}")


def test_coverage_gate_and_report() -> None:
    coverage = read_csv(OUT_COVERAGE)
    gate = read_csv(OUT_GATE)
    assert_true(len(coverage) == 1, "coverage should have one row")
    assert_true(len(gate) == 1, "gate should have one row")
    for row in coverage + gate:
        assert_safety(row)
    assert_true(gate[0]["next_stage_allowed"] == "FALSE", "shadow rerank should remain blocked")
    assert_true(gate[0]["complete_six_family_contribution_candidate_count"] == "0", "complete six-family should remain blocked")
    text = REPORT.read_text(encoding="utf-8")
    for marker in [
        "source_rank_or_score_used: FALSE",
        "baseline_rank_used: FALSE",
        "fabricated_values_created: FALSE",
        "proxy_values_activated: FALSE",
        "global_regime_copied_without_exposure_conditioning: FALSE",
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
    test_scope_carry_forward_and_mapping_safety()
    test_coverage_gate_and_report()
    print("PASS_V20_108_R8_R1_MARKET_REGIME_EQUITY_SECTOR_THEME_EXPOSURE_EXPANDER_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
