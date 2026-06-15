from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

PASS_STATUS = "PASS_V20_41_TESTS"

REQUIRED_FILES = [
    CONSOLIDATION / "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv",
    CONSOLIDATION / "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv",
    CONSOLIDATION / "V20_41_PIT_READY_FACTOR_CANDIDATES.csv",
    CONSOLIDATION / "V20_41_PRICE_DERIVED_FACTOR_CANDIDATES.csv",
    CONSOLIDATION / "V20_41_BACKFILL_REQUIRED_FACTOR_BACKLOG.csv",
    CONSOLIDATION / "V20_41_NON_PIT_BLOCKED_FACTOR_REGISTER.csv",
    CONSOLIDATION / "V20_41_DYNAMIC_WEIGHTING_EXPANSION_CANDIDATES.csv",
    CONSOLIDATION / "V20_41_REQUIRED_SOURCE_BACKLOG.csv",
    CONSOLIDATION / "V20_41_NEXT_STEP_DECISION_SUMMARY.csv",
    READ_CENTER / "V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN_REPORT.md",
    READ_CENTER / "V20_CURRENT_RESEARCH_FACTOR_PIT_EXPANSION_PLAN.md",
    OPS / "V20_41_READ_FIRST.txt",
]

CSV_REQUIRED_COLUMNS = {
    "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv": {
        "factor_key",
        "factor_name",
        "factor_family",
        "factor_category",
        "source_stage",
        "source_input_required",
        "prior_evidence",
        "pit_backtest_eligible_now",
        "price_cache_computable",
        "historical_source_backfill_required",
        "blocked_non_pit_current_only",
        "future_dynamic_weighting_candidate",
        "official_recommendation_allowed",
        "official_factor_weight_mutation_allowed",
        "official_ranking_mutation_allowed",
        "recommended_next_action",
        "decision_reason",
    },
    "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv": {
        "factor_category",
        "factor_count",
        "pit_backtest_eligible_now_count",
        "price_cache_computable_count",
        "historical_source_backfill_required_count",
        "blocked_non_pit_current_only_count",
        "future_dynamic_weighting_candidate_count",
        "official_recommendation_allowed_count",
        "coverage_status",
    },
    "V20_41_REQUIRED_SOURCE_BACKLOG.csv": {
        "factor_key",
        "factor_category",
        "required_source",
        "source_need_type",
        "fetch_or_refresh_now",
        "allowed_current_stage_action",
        "official_use_allowed",
        "reason",
    },
    "V20_41_NEXT_STEP_DECISION_SUMMARY.csv": {
        "STAGE_NAME",
        "STATUS",
        "RESEARCH_ONLY",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "TRADING_SIGNAL_CREATED",
        "BROKER_ORDER_PATH_CREATED",
        "OFFICIAL_RANKING_MUTATED",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED",
        "DYNAMIC_WEIGHTING_EXECUTED",
        "PORTFOLIO_BACKTEST_RERUN",
        "NEW_RETURN_COMPUTATION_CREATED",
        "PROVIDER_REFRESH_EXECUTED",
        "V21_OUTPUTS_CREATED",
        "V19_21_OUTPUTS_CREATED",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION",
    },
}

DECISION_LIKE_OUTPUTS = [
    "V20_41_PIT_READY_FACTOR_CANDIDATES.csv",
    "V20_41_PRICE_DERIVED_FACTOR_CANDIDATES.csv",
    "V20_41_BACKFILL_REQUIRED_FACTOR_BACKLOG.csv",
    "V20_41_NON_PIT_BLOCKED_FACTOR_REGISTER.csv",
    "V20_41_DYNAMIC_WEIGHTING_EXPANSION_CANDIDATES.csv",
]

REQUIRED_CATEGORIES = {
    "fundamental",
    "technical",
    "strategy",
    "risk",
    "market_regime",
    "data_trustworthiness",
}

READ_FIRST_FLAGS = {
    "STATUS": "PASS_V20_41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN",
    "RESEARCH_ONLY": "TRUE",
    "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
    "TRADING_SIGNAL_CREATED": "FALSE",
    "BROKER_ORDER_PATH_CREATED": "FALSE",
    "OFFICIAL_RANKING_MUTATED": "FALSE",
    "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
    "DYNAMIC_WEIGHTING_EXECUTED": "FALSE",
    "PORTFOLIO_BACKTEST_RERUN": "FALSE",
    "NEW_RETURN_COMPUTATION_CREATED": "FALSE",
    "PROVIDER_REFRESH_EXECUTED": "FALSE",
    "HISTORICAL_SOURCE_BACKFILL_EXECUTED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def read_flags(path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[key.strip()] = value.strip()
    return flags


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def test_required_files_exist() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required V20.41 output files: {missing}")


def test_required_csvs_non_empty_and_columns() -> None:
    decision_columns = CSV_REQUIRED_COLUMNS["V20_41_FACTOR_PIT_EXPANSION_DECISION.csv"]
    for filename in DECISION_LIKE_OUTPUTS:
        CSV_REQUIRED_COLUMNS[filename] = decision_columns

    for filename, required_columns in CSV_REQUIRED_COLUMNS.items():
        path = CONSOLIDATION / filename
        rows, columns = read_csv(path)
        missing_columns = sorted(required_columns - set(columns))
        assert_true(not missing_columns, f"{filename} missing required columns: {missing_columns}")
        assert_true(rows, f"{filename} must be non-empty")


def test_read_first_safety_flags() -> None:
    path = OPS / "V20_41_READ_FIRST.txt"
    assert_true(path.exists(), "V20_41_READ_FIRST.txt does not exist")
    flags = read_flags(path)
    for key, expected in READ_FIRST_FLAGS.items():
        actual = flags.get(key)
        assert_true(actual == expected, f"READ_FIRST flag {key} expected {expected}, got {actual}")


def test_no_forbidden_output_paths_or_refresh_claims() -> None:
    scan_paths = [
        *REQUIRED_FILES,
        ROOT / "scripts" / "v20" / "v20_41_research_factor_pit_expansion_plan.py",
        ROOT / "scripts" / "v20" / "run_v20_41_research_factor_pit_expansion_plan.ps1",
    ]
    forbidden_path_pattern = re.compile(r"outputs[\\/](?:v21|v19(?:\.21|_21)?)", re.IGNORECASE)
    provider_refresh_patterns = [
        re.compile(r"\byfinance\b", re.IGNORECASE),
        re.compile(r"\byf\.", re.IGNORECASE),
        re.compile(r"\brequests\.", re.IGNORECASE),
        re.compile(r"\bhttpx\.", re.IGNORECASE),
        re.compile(r"fetch_or_refresh_now\s*,?\s*TRUE", re.IGNORECASE),
        re.compile(r"PROVIDER_REFRESH_EXECUTED=TRUE", re.IGNORECASE),
    ]
    for path in scan_paths:
        if not path.exists() or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert_true(not forbidden_path_pattern.search(text), f"Forbidden V21/V19.21 output path found in {path}")
        for pattern in provider_refresh_patterns:
            assert_true(not pattern.search(text), f"Provider/network refresh marker {pattern.pattern!r} found in {path}")


def test_factor_category_coverage() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_41_FACTOR_COVERAGE_BY_CATEGORY.csv")
    categories = {clean(r.get("factor_category")) for r in rows}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    assert_true(not missing, f"Missing factor categories from coverage output: {missing}")
    for category in REQUIRED_CATEGORIES:
        row = next(r for r in rows if clean(r.get("factor_category")) == category)
        assert_true(upper(row.get("coverage_status")) == "COVERED", f"{category} coverage_status is not COVERED")
        assert_true(int(clean(row.get("factor_count")) or "0") > 0, f"{category} factor_count must be positive")


def test_dynamic_candidates_subset_of_valid_decisions() -> None:
    decisions, _ = read_csv(CONSOLIDATION / "V20_41_FACTOR_PIT_EXPANSION_DECISION.csv")
    dynamic, _ = read_csv(CONSOLIDATION / "V20_41_DYNAMIC_WEIGHTING_EXPANSION_CANDIDATES.csv")
    by_key = {clean(row.get("factor_key")): row for row in decisions}
    for row in dynamic:
        key = clean(row.get("factor_key"))
        decision = by_key.get(key)
        assert_true(decision is not None, f"Dynamic candidate {key} missing from decision output")
        assert_true(
            upper(decision.get("future_dynamic_weighting_candidate")) == "TRUE",
            f"Dynamic candidate {key} is not marked future_dynamic_weighting_candidate in decisions",
        )
        valid_source_state = (
            upper(decision.get("pit_backtest_eligible_now")) == "TRUE"
            or upper(decision.get("price_cache_computable")) == "TRUE"
            or upper(decision.get("future_dynamic_weighting_candidate")) == "TRUE"
        )
        assert_true(valid_source_state, f"Dynamic candidate {key} is not PIT/cache-derived or future-eligible")


def test_backfill_rows_have_source_reason_fields() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_41_BACKFILL_REQUIRED_FACTOR_BACKLOG.csv")
    for row in rows:
        key = clean(row.get("factor_key"))
        assert_true(upper(row.get("historical_source_backfill_required")) == "TRUE", f"Backfill row {key} is not marked as requiring backfill")
        assert_true(bool(clean(row.get("source_input_required"))), f"Backfill row {key} missing source_input_required")
        assert_true(bool(clean(row.get("recommended_next_action"))), f"Backfill row {key} missing recommended_next_action")
        assert_true(bool(clean(row.get("decision_reason"))), f"Backfill row {key} missing decision_reason")

    source_rows, _ = read_csv(CONSOLIDATION / "V20_41_REQUIRED_SOURCE_BACKLOG.csv")
    for row in source_rows:
        key = clean(row.get("factor_key"))
        assert_true(bool(clean(row.get("required_source"))), f"Required source backlog row {key} missing required_source")
        assert_true(bool(clean(row.get("source_need_type"))), f"Required source backlog row {key} missing source_need_type")
        assert_true(bool(clean(row.get("reason"))), f"Required source backlog row {key} missing reason")
        assert_true(upper(row.get("fetch_or_refresh_now")) == "FALSE", f"Required source backlog row {key} must not refresh now")


def test_non_pit_blocked_rows_have_blocker_reason_fields() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_41_NON_PIT_BLOCKED_FACTOR_REGISTER.csv")
    for row in rows:
        key = clean(row.get("factor_key"))
        assert_true(upper(row.get("blocked_non_pit_current_only")) == "TRUE", f"Blocked row {key} is not marked blocked")
        assert_true(bool(clean(row.get("source_input_required"))), f"Blocked row {key} missing source_input_required")
        assert_true(bool(clean(row.get("recommended_next_action"))), f"Blocked row {key} missing recommended_next_action")
        assert_true(bool(clean(row.get("decision_reason"))), f"Blocked row {key} missing decision_reason")


def test_current_alias_report_exists() -> None:
    path = READ_CENTER / "V20_CURRENT_RESEARCH_FACTOR_PIT_EXPANSION_PLAN.md"
    assert_true(path.exists(), "Current alias report does not exist")
    assert_true(path.stat().st_size > 0, "Current alias report is empty")


def main() -> int:
    tests = [
        test_required_files_exist,
        test_required_csvs_non_empty_and_columns,
        test_read_first_safety_flags,
        test_no_forbidden_output_paths_or_refresh_claims,
        test_factor_category_coverage,
        test_dynamic_candidates_subset_of_valid_decisions,
        test_backfill_rows_have_source_reason_fields,
        test_non_pit_blocked_rows_have_blocker_reason_fields,
        test_current_alias_report_exists,
    ]
    for test in tests:
        test()
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
