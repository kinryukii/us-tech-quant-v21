from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

PASS_STATUS = "PASS_V20_42_TESTS"

REQUIRED_FILES = [
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FIELD_CONTRACT.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_INPUT_DEPENDENCY_MAP.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_CANDIDATE_TABLE_SCHEMA.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FACTOR_SUMMARY_SCHEMA.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_STRATEGY_SUMMARY_SCHEMA.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_RISK_BLOCKER_SCHEMA.csv",
    CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv",
    CONSOLIDATION / "V20_42_VALIDATION_SUMMARY.csv",
    READ_CENTER / "V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN_REPORT.md",
    READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN.md",
    OPS / "V20_42_READ_FIRST.txt",
]

CSV_REQUIRED_COLUMNS = {
    "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv": {
        "section_order",
        "section_id",
        "section_title",
        "section_type",
        "design_status",
        "research_only",
        "official_output_allowed",
        "primary_content_contract",
    },
    "V20_42_DAILY_OPERATOR_REPORT_FIELD_CONTRACT.csv": {
        "section_id",
        "field_name",
        "field_type",
        "readable_description",
        "requirement_level",
        "source_contract",
        "may_create_official_output",
        "may_trigger_provider_refresh",
    },
    "V20_42_DAILY_OPERATOR_REPORT_INPUT_DEPENDENCY_MAP.csv": {
        "source_stage",
        "input_file",
        "source_exists",
        "row_count",
        "required_for_report_design",
        "used_for_return_computation",
        "provider_refresh_required",
        "dependency_status",
    },
    "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv": {
        "STAGE_NAME",
        "STATUS",
        "V20_40_READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN",
        "V20_41_STATUS",
        "SECTION_COUNT",
        "FIELD_CONTRACT_ROWS",
        "INPUT_DEPENDENCY_ROWS",
        "REQUIRED_INPUT_MISSING_COUNT",
        "RESEARCH_ONLY",
        "DESIGN_ONLY",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "BUY_SELL_TRIM_RECOMMENDATION_CREATED",
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
        "HUMAN_READABLE_NEXT_STEP",
    },
    "V20_42_VALIDATION_SUMMARY.csv": {
        "validation_check",
        "result",
        "detail",
    },
}

TABLE_SCHEMA_FILES = [
    "V20_42_DAILY_OPERATOR_REPORT_CANDIDATE_TABLE_SCHEMA.csv",
    "V20_42_DAILY_OPERATOR_REPORT_FACTOR_SUMMARY_SCHEMA.csv",
    "V20_42_DAILY_OPERATOR_REPORT_STRATEGY_SUMMARY_SCHEMA.csv",
    "V20_42_DAILY_OPERATOR_REPORT_RISK_BLOCKER_SCHEMA.csv",
]

TABLE_SCHEMA_COLUMNS = {
    "table_name",
    "column_order",
    "column_name",
    "column_type",
    "column_description",
    "required",
    "research_only",
    "official_recommendation_field",
}

REQUIRED_SECTION_TITLES = {
    "Run identity and report date",
    "Research-only boundary",
    "Market regime placeholder",
    "Benchmark context placeholder for SPY/QQQ",
    "Candidate universe summary",
    "Top candidate research table design",
    "Factor support summary",
    "Entry strategy evidence summary",
    "Shadow dynamic weighting evidence summary",
    "Portfolio exploratory backtest evidence summary",
    "PIT factor expansion status",
    "Risk and blocker summary",
    "Data freshness / lineage / leakage status",
    "Human-readable next-step decision",
    "Explicit prohibition against official trading or recommendation output",
}

REQUIRED_DEPENDENCY_STAGES = {
    "V20.35-R2",
    "V20.36",
    "V20.37",
    "V20.38",
    "V20.39",
    "V20.39-R1",
    "V20.39-R2",
    "V20.40",
    "V20.41",
}

READ_FIRST_FLAGS = {
    "STATUS": "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN",
    "DESIGN_ONLY": "TRUE",
    "RESEARCH_ONLY": "TRUE",
    "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
    "BUY_SELL_TRIM_RECOMMENDATION_CREATED": "FALSE",
    "TRADING_SIGNAL_CREATED": "FALSE",
    "BROKER_ORDER_PATH_CREATED": "FALSE",
    "OFFICIAL_RANKING_MUTATED": "FALSE",
    "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
    "DYNAMIC_WEIGHTING_EXECUTED": "FALSE",
    "PORTFOLIO_BACKTEST_RERUN": "FALSE",
    "NEW_RETURN_COMPUTATION_CREATED": "FALSE",
    "PROVIDER_REFRESH_EXECUTED": "FALSE",
    "YFINANCE_REFRESH_EXECUTED": "FALSE",
    "NETWORK_REFRESH_EXECUTED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_flags(path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[key.strip()] = value.strip()
    return flags


def test_required_files_exist() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required V20.42 output files: {missing}")


def test_required_csvs_non_empty_and_columns() -> None:
    for filename in TABLE_SCHEMA_FILES:
        CSV_REQUIRED_COLUMNS[filename] = TABLE_SCHEMA_COLUMNS

    for filename, required_columns in CSV_REQUIRED_COLUMNS.items():
        path = CONSOLIDATION / filename
        rows, columns = read_csv(path)
        missing_columns = sorted(required_columns - set(columns))
        assert_true(not missing_columns, f"{filename} missing required columns: {missing_columns}")
        assert_true(rows, f"{filename} must be non-empty")


def test_section_map_contains_required_sections() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv")
    titles = {clean(row.get("section_title")) for row in rows}
    missing = sorted(REQUIRED_SECTION_TITLES - titles)
    assert_true(not missing, f"Section map missing required report sections: {missing}")
    assert_true(len(rows) == 15, f"Section map expected 15 rows, got {len(rows)}")
    for row in rows:
        section_id = clean(row.get("section_id"))
        assert_true(upper(row.get("design_status")) == "DESIGN_ONLY", f"Section {section_id} is not design-only")
        assert_true(upper(row.get("research_only")) == "TRUE", f"Section {section_id} is not research-only")
        assert_true(upper(row.get("official_output_allowed")) == "FALSE", f"Section {section_id} allows official output")
        assert_true(bool(clean(row.get("primary_content_contract"))), f"Section {section_id} missing content contract")


def test_field_contract_validity() -> None:
    section_rows, _ = read_csv(CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_SECTION_MAP.csv")
    valid_sections = {clean(row.get("section_id")) for row in section_rows}
    field_rows, _ = read_csv(CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_FIELD_CONTRACT.csv")
    seen_fields: set[tuple[str, str]] = set()
    for row in field_rows:
        section_id = clean(row.get("section_id"))
        field_name = clean(row.get("field_name"))
        assert_true(section_id in valid_sections, f"Field contract references unknown section_id: {section_id}")
        assert_true(field_name.isidentifier(), f"Field name is not a valid identifier: {field_name}")
        assert_true(bool(clean(row.get("readable_description"))), f"Field {section_id}.{field_name} missing description")
        assert_true(bool(clean(row.get("source_contract"))), f"Field {section_id}.{field_name} missing source/dependency reference")
        assert_true(upper(row.get("may_create_official_output")) == "FALSE", f"Field {section_id}.{field_name} may create official output")
        assert_true(upper(row.get("may_trigger_provider_refresh")) == "FALSE", f"Field {section_id}.{field_name} may trigger provider refresh")
        key = (section_id, field_name)
        assert_true(key not in seen_fields, f"Duplicate field contract row: {section_id}.{field_name}")
        seen_fields.add(key)


def test_input_dependency_map_contains_required_stages() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_INPUT_DEPENDENCY_MAP.csv")
    stages = {clean(row.get("source_stage")) for row in rows}
    missing = sorted(REQUIRED_DEPENDENCY_STAGES - stages)
    assert_true(not missing, f"Input dependency map missing stages: {missing}")
    for row in rows:
        stage = clean(row.get("source_stage"))
        assert_true(bool(clean(row.get("input_file"))), f"Dependency row for {stage} missing input_file")
        assert_true(upper(row.get("source_exists")) == "TRUE", f"Dependency row for {stage} source_exists is not TRUE")
        assert_true(upper(row.get("used_for_return_computation")) == "FALSE", f"Dependency row for {stage} used for return computation")
        assert_true(upper(row.get("provider_refresh_required")) == "FALSE", f"Dependency row for {stage} requires provider refresh")
        assert_true(upper(row.get("dependency_status")) == "AVAILABLE", f"Dependency row for {stage} is not AVAILABLE")


def test_missing_required_input_count_zero() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv")
    assert_true(len(rows) == 1, f"Next-step decision expected 1 row, got {len(rows)}")
    row = rows[0]
    assert_true(clean(row.get("REQUIRED_INPUT_MISSING_COUNT")) == "0", "Required input missing count is not 0")

    validation_rows, _ = read_csv(CONSOLIDATION / "V20_42_VALIDATION_SUMMARY.csv")
    required_input_rows = [r for r in validation_rows if clean(r.get("validation_check")) == "required_inputs_available"]
    assert_true(required_input_rows, "Validation summary missing required_inputs_available check")
    assert_true(upper(required_input_rows[0].get("result")) == "PASS", "required_inputs_available validation did not pass")


def test_next_step_decision_design_research_only() -> None:
    path = CONSOLIDATION / "V20_42_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv"
    assert_true(path.exists(), "Next-step decision output does not exist")
    rows, _ = read_csv(path)
    row = rows[0]
    expected = {
        "STATUS": "PASS_V20_42_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN",
        "RESEARCH_ONLY": "TRUE",
        "DESIGN_ONLY": "TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "BUY_SELL_TRIM_RECOMMENDATION_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "BROKER_ORDER_PATH_CREATED": "FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED": "FALSE",
        "PORTFOLIO_BACKTEST_RERUN": "FALSE",
        "NEW_RETURN_COMPUTATION_CREATED": "FALSE",
        "PROVIDER_REFRESH_EXECUTED": "FALSE",
        "V21_OUTPUTS_CREATED": "FALSE",
        "V19_21_OUTPUTS_CREATED": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(bool(clean(row.get("HUMAN_READABLE_NEXT_STEP"))), "Next-step decision missing human-readable next step")


def test_read_first_safety_flags() -> None:
    path = OPS / "V20_42_READ_FIRST.txt"
    assert_true(path.exists(), "V20_42_READ_FIRST.txt does not exist")
    flags = read_flags(path)
    for key, expected in READ_FIRST_FLAGS.items():
        actual = flags.get(key)
        assert_true(actual == expected, f"READ_FIRST flag {key} expected {expected}, got {actual}")


def test_current_alias_report_exists() -> None:
    path = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN.md"
    assert_true(path.exists(), "Current alias report does not exist")
    assert_true(path.stat().st_size > 0, "Current alias report is empty")


def main() -> int:
    tests = [
        test_required_files_exist,
        test_required_csvs_non_empty_and_columns,
        test_section_map_contains_required_sections,
        test_field_contract_validity,
        test_input_dependency_map_contains_required_stages,
        test_missing_required_input_count_zero,
        test_next_step_decision_design_research_only,
        test_read_first_safety_flags,
        test_current_alias_report_exists,
    ]
    for test in tests:
        test()
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
