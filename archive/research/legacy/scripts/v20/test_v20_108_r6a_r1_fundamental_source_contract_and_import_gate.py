from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_108_r6a_r1_fundamental_source_contract_and_import_gate.py"
TEST_SCRIPT = ROOT / "scripts" / "v20" / "test_v20_108_r6a_r1_fundamental_source_contract_and_import_gate.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_108_r6a_r1_fundamental_source_contract_and_import_gate.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"

OUT_CONTRACT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT.csv"
OUT_TEMPLATE = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_TEMPLATE.csv"
OUT_IMPORT_AUDIT = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_AUDIT.csv"
OUT_PROVIDER_REQ = CONSOLIDATION / "V20_108_R6A_R1_FUNDAMENTAL_PROVIDER_CONFIG_REQUIREMENT.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R6A_R1_NEXT_REPAIR_ACTION.csv"
REPORT = READ_CENTER / "V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_REPORT.md"

ACCEPTED = {
    "PASS_V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_CREATED",
    "PARTIAL_PASS_V20_108_R6A_R1_FUNDAMENTAL_IMPORT_GATE_WAITING_FOR_LOCAL_INPUT",
    "PASS_V20_108_R6A_R1_FUNDAMENTAL_LOCAL_INPUT_VALIDATED",
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


def fieldnames(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


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
    result = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    assert_true(result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}")
    assert_true(any(status in result.stdout for status in ACCEPTED), f"missing accepted status: {result.stdout}")
    for marker in [
        "EXTERNAL_DATA_FETCHED=FALSE",
        "PROVIDER_REFRESH_EXECUTED=FALSE",
        "FUNDAMENTAL_CONTRIBUTION_SCORES_CREATED=FALSE",
        "SOURCE_RANK_OR_SCORE_USED_AS_FUNDAMENTAL=FALSE",
        "BASELINE_RANK_USED_AS_FUNDAMENTAL=FALSE",
        "FABRICATED_VALUES_CREATED=FALSE",
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
    assert_true(before_r4 == R4_SCORES.read_text(encoding="utf-8"), "R4 scores mutated")
    for path in [OUT_CONTRACT, OUT_TEMPLATE, OUT_IMPORT_AUDIT, OUT_PROVIDER_REQ, OUT_NEXT, REPORT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"missing output: {path}")


def test_contract_and_template() -> None:
    contract = read_csv(OUT_CONTRACT)
    template = read_csv(OUT_TEMPLATE)
    assert_true(len(contract) == len(METRICS), "contract does not cover required metrics")
    assert_true({row["required_column"] for row in contract} == set(METRICS), "missing metric contract columns")
    assert_true(set(METRICS).issubset(set(fieldnames(OUT_TEMPLATE))), "template missing schema metric columns")
    assert_true({"ticker", "metric_source_provider", "metric_source_timestamp"}.issubset(set(fieldnames(OUT_TEMPLATE))), "template missing source columns")
    assert_true(len(template) == 315, "all 315 candidates not represented in local input template")
    assert_true(len({row["ticker"] for row in template}) == 315, "template ticker set not unique")
    for row in contract + template:
        assert_safety(row)
        assert_true(row.get("contribution_score_created", "FALSE") == "FALSE", f"contribution score created: {row}")
    for row in template:
        assert_true(all(row[metric] == "" for metric in METRICS), f"template fabricated metric values: {row}")


def test_import_gate_and_provider_requirement() -> None:
    audit = read_csv(OUT_IMPORT_AUDIT)
    provider = read_csv(OUT_PROVIDER_REQ)
    next_rows = read_csv(OUT_NEXT)
    assert_true(len(audit) == 3, "import audit should inspect three optional local paths")
    assert_true(len(provider) == 1, "provider requirement should have one row")
    assert_true(provider[0]["refresh_allowed_flag"] == "ENABLE_FUNDAMENTAL_REFRESH", "provider flag not defined")
    assert_true(provider[0]["refresh_allowed_flag_required_value"] == "TRUE", "provider flag required value wrong")
    assert_true(provider[0]["refresh_execution_allowed_in_this_stage"] == "FALSE", "provider refresh executed/allowed")
    for row in audit + provider + next_rows:
        assert_safety(row)
    assert_true(all(row["source_rank_or_score_used_as_fundamental"] == "FALSE" for row in audit), "source score used")
    assert_true(all(row["baseline_rank_used_as_fundamental"] == "FALSE" for row in audit), "baseline rank used")
    assert_true(all(row["fabricated_values_created"] == "FALSE" for row in audit), "fabricated values created")
    assert_true(all(row["candidate_count_required"] == "315" for row in audit), "candidate count contract wrong")
    text = REPORT.read_text(encoding="utf-8")
    assert_true(any(f"wrapper_status: {status}" in text for status in ACCEPTED), "report missing status")
    for marker in [
        "external_data_fetched: FALSE",
        "provider_refresh_executed: FALSE",
        "fundamental_contribution_scores_created: FALSE",
        "source_rank_or_score_used_as_fundamental: FALSE",
        "baseline_rank_used_as_fundamental: FALSE",
        "fabricated_values_created: FALSE",
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
    test_contract_and_template()
    test_import_gate_and_provider_requirement()
    print("PASS_V20_108_R6A_R1_FUNDAMENTAL_SOURCE_CONTRACT_AND_IMPORT_GATE_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
