from __future__ import annotations

import ast
import csv
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

PASS_STATUS = "PASS_V20_43_TESTS"
STAGE_NAME = "V20.43_DAILY_OPERATOR_REPORT_DRY_RUN"
PRODUCTION_STATUS = "PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN"

REQUIRED_FILES = [
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SHADOW_WEIGHTING_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_PORTFOLIO_EVIDENCE_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_RISK_BLOCKER_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv",
    CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv",
    CONSOLIDATION / "V20_43_VALIDATION_SUMMARY.csv",
    READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md",
    READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md",
    OPS / "V20_43_READ_FIRST.txt",
]

CSV_REQUIRED_COLUMNS = {
    "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv": {
        "STAGE_NAME",
        "STATUS",
        "SECTION_STATUS_ROWS",
        "CANDIDATE_RESEARCH_ROWS",
        "FACTOR_SUPPORT_ROWS",
        "ENTRY_STRATEGY_ROWS",
        "LINEAGE_FRESHNESS_ROWS",
        "MISSING_REQUIRED_SOURCE_COUNT",
        "DRY_RUN_ONLY",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "BROKER_ORDER_PATH_CREATED",
        "OFFICIAL_RANKING_MUTATED",
        "DYNAMIC_WEIGHTING_EXECUTED",
        "PROVIDER_REFRESH_EXECUTED",
        "V21_OUTPUTS_CREATED",
        "V19_21_OUTPUTS_CREATED",
    },
    "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv": {
        "source_stage",
        "source_file",
        "source_exists",
        "row_count",
        "required_for_dry_run",
        "used_existing_output_only",
        "provider_refresh_executed",
        "new_return_computation_executed",
        "source_status",
    },
    "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv": {
        "section_id",
        "section_title",
        "section_render_status",
        "payload_row_count",
        "dry_run_only",
        "research_only",
        "official_output_allowed",
        "render_note",
    },
    "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv": {
        "ticker",
        "signal_date",
        "research_rank",
        "top_bucket",
        "technical_score",
        "candidate_source_stage",
        "official_recommendation",
        "trading_signal",
        "dry_run_only",
    },
    "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv": {
        "summary_type",
        "factor_category",
        "factor_name",
        "pit_backtest_eligible_now",
        "stability_or_coverage_status",
        "readable_note",
    },
    "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv": {
        "strategy_family",
        "strategy_design_count",
        "fill_or_execution_note",
        "readable_evidence_note",
        "official_strategy_promoted",
        "trading_signal_created",
    },
    "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv": {
        "lineage_item",
        "source_file",
        "source_exists",
        "row_count",
        "freshness_status",
        "provider_refresh_executed",
        "leakage_or_formula_status",
    },
    "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv": {
        "STAGE_NAME",
        "STATUS",
        "HUMAN_READABLE_NEXT_STEP",
        "READY_FOR_V20_44_RESEARCH_REPORT_REVIEW_TESTS",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION",
        "DRY_RUN_ONLY",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "TRADING_SIGNAL_CREATED",
        "BROKER_ORDER_PATH_CREATED",
        "OFFICIAL_RANKING_MUTATED",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED",
        "DYNAMIC_WEIGHTING_EXECUTED",
        "PROVIDER_REFRESH_EXECUTED",
        "V21_OUTPUTS_CREATED",
        "V19_21_OUTPUTS_CREATED",
    },
}

REQUIRED_COUNTS = {
    "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv": 15,
    "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv": 50,
    "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv": 21,
    "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv": 5,
    "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv": 27,
}

REQUIRED_SECTION_IDS = {
    "RUN_IDENTITY",
    "RESEARCH_BOUNDARY",
    "MARKET_REGIME_PLACEHOLDER",
    "BENCHMARK_CONTEXT_PLACEHOLDER",
    "CANDIDATE_UNIVERSE_SUMMARY",
    "TOP_CANDIDATE_RESEARCH_TABLE_DESIGN",
    "FACTOR_SUPPORT_SUMMARY",
    "ENTRY_STRATEGY_EVIDENCE_SUMMARY",
    "SHADOW_DYNAMIC_WEIGHTING_EVIDENCE_SUMMARY",
    "PORTFOLIO_EXPLORATORY_BACKTEST_EVIDENCE_SUMMARY",
    "PIT_FACTOR_EXPANSION_STATUS",
    "RISK_AND_BLOCKER_SUMMARY",
    "DATA_FRESHNESS_LINEAGE_LEAKAGE_STATUS",
    "HUMAN_READABLE_NEXT_STEP_DECISION",
    "OFFICIAL_OUTPUT_PROHIBITION",
}

REQUIRED_UPSTREAM_STAGES = {
    "V20.35-R2",
    "V20.36",
    "V20.37",
    "V20.38",
    "V20.39",
    "V20.39-R1",
    "V20.39-R2",
    "V20.40",
    "V20.41",
    "V20.42",
}

SAFETY_FALSE_FLAGS = {
    "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION",
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
}

REPORT_FORBIDDEN_READY_CLAIMS = [
    re.compile(r"\bofficial trading readiness\b", re.IGNORECASE),
    re.compile(r"\bofficial recommendation readiness\b", re.IGNORECASE),
    re.compile(r"\bready for official trading\b", re.IGNORECASE),
    re.compile(r"\bready for official recommendation\b", re.IGNORECASE),
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


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


def has_any(columns: list[str], *names: str) -> bool:
    available = {column.lower() for column in columns}
    return any(name.lower() in available for name in names)


def assert_semantic_columns(filename: str, columns: list[str]) -> None:
    checks = {
        "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv": [
            ("section_id", ("section_id",)),
            ("section_name", ("section_name", "section_title")),
            ("section_status", ("section_status", "section_render_status")),
            ("source_contract", ("source_contract", "render_note")),
            ("required_flag", ("required_flag", "dry_run_only", "research_only")),
            ("blocker_count", ("blocker_count", "official_output_allowed")),
        ],
        "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv": [
            ("ticker_or_candidate_id", ("ticker", "candidate_id")),
            ("signal_or_report_date", ("signal_date", "report_date")),
            ("rank_or_score", ("research_rank", "rank", "score", "technical_score")),
            ("research_category", ("research_category", "top_bucket")),
            ("report_section", ("report_section", "display_order")),
            ("source_lineage", ("source_lineage", "source_contract", "candidate_source_stage")),
        ],
        "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv": [
            ("factor_id_or_name", ("factor_id", "factor_name")),
            ("factor_category", ("factor_category",)),
            ("pit_status", ("pit_status", "pit_backtest_eligible_now")),
            ("support_status", ("support_status", "stability_or_coverage_status")),
            ("report_section", ("report_section", "summary_type")),
        ],
        "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv": [
            ("strategy_id_or_name", ("strategy_id", "strategy_name", "strategy_family")),
            ("strategy_family", ("strategy_family",)),
            ("execution_or_readiness_status", ("execution_status", "readiness_status", "fill_or_execution_note")),
            ("report_section", ("report_section", "readable_evidence_note")),
        ],
        "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv": [
            ("source_name_or_input_name", ("source_name", "input_name", "lineage_item")),
            ("source_version_or_contract", ("source_version", "source_contract", "source_file")),
            ("freshness_status", ("freshness_status",)),
            ("lineage_status", ("lineage_status", "leakage_or_formula_status")),
            ("blocker_count", ("blocker_count", "source_exists")),
        ],
        "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv": [
            ("stage", ("stage", "STAGE_NAME")),
            ("decision", ("decision", "STATUS")),
            ("ready_for_next_step", ("ready_for_next_step", "READY_FOR_V20_44_RESEARCH_REPORT_REVIEW_TESTS")),
            ("official_trading_allowed", ("official_trading_allowed", "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION")),
            ("dynamic_weighting_mutated", ("dynamic_weighting_mutated", "DYNAMIC_WEIGHTING_EXECUTED")),
        ],
    }
    for semantic_name, names in checks.get(filename, []):
        assert_true(has_any(columns, *names), f"{filename} missing semantic field {semantic_name}; accepted columns: {names}")


def test_required_files_exist() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required V20.43 output files: {missing}")


def test_required_csvs_non_empty_columns_and_counts() -> None:
    for filename, required_columns in CSV_REQUIRED_COLUMNS.items():
        path = CONSOLIDATION / filename
        rows, columns = read_csv(path)
        missing_columns = sorted(required_columns - set(columns))
        assert_true(not missing_columns, f"{filename} missing required columns: {missing_columns}")
        assert_semantic_columns(filename, columns)
        assert_true(rows, f"{filename} must be non-empty")

    for filename, expected_count in REQUIRED_COUNTS.items():
        rows, _ = read_csv(consolidation_file(filename))
        assert_true(len(rows) == expected_count, f"{filename} expected {expected_count} rows, got {len(rows)}")


def consolidation_file(filename: str) -> Path:
    return CONSOLIDATION / filename


def test_missing_required_sources_zero() -> None:
    manifest_rows, _ = read_csv(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv")
    assert_true(len(manifest_rows) == 1, f"Manifest expected 1 row, got {len(manifest_rows)}")
    assert_true(clean(manifest_rows[0].get("MISSING_REQUIRED_SOURCE_COUNT")) == "0", "Manifest missing required source count is not 0")

    source_rows, _ = read_csv(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv")
    missing_required = [
        row
        for row in source_rows
        if upper(row.get("required_for_dry_run")) == "TRUE" and upper(row.get("source_status")) != "AVAILABLE"
    ]
    assert_true(not missing_required, f"Required source rows are not available: {missing_required}")


def test_section_coverage() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv")
    section_ids = [clean(row.get("section_id")) for row in rows]
    assert_true(len(section_ids) == len(set(section_ids)), "Section IDs must be unique")
    missing = sorted(REQUIRED_SECTION_IDS - set(section_ids))
    assert_true(not missing, f"Section status missing required sections: {missing}")

    for row in rows:
        section_id = clean(row.get("section_id"))
        assert_true(bool(clean(row.get("section_title"))), f"Section {section_id} has an empty section name")
        assert_true(upper(row.get("section_render_status")) == "RENDERED", f"Section {section_id} is not rendered")
        assert_true(upper(row.get("dry_run_only")) == "TRUE", f"Section {section_id} is not marked dry-run-only")
        assert_true(upper(row.get("research_only")) == "TRUE", f"Section {section_id} is not marked research-only")
        assert_true(upper(row.get("official_output_allowed")) == "FALSE", f"Section {section_id} allows official output")
        assert_true(as_int(row.get("payload_row_count")) >= 1, f"Section {section_id} has no payload rows")


def test_input_dependency_coverage() -> None:
    rows, _ = read_csv(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv")
    stages = {clean(row.get("source_stage")) for row in rows}
    missing = sorted(REQUIRED_UPSTREAM_STAGES - stages)
    assert_true(not missing, f"Source status missing required upstream stage coverage: {missing}")
    for row in rows:
        stage = clean(row.get("source_stage"))
        assert_true(upper(row.get("source_exists")) == "TRUE", f"Dependency {stage} source does not exist")
        assert_true(upper(row.get("used_existing_output_only")) == "TRUE", f"Dependency {stage} did not use existing outputs only")
        assert_true(upper(row.get("provider_refresh_executed")) == "FALSE", f"Dependency {stage} executed provider refresh")
        assert_true(upper(row.get("new_return_computation_executed")) == "FALSE", f"Dependency {stage} executed new returns")


def assert_safety_flags(mapping: dict[str, str], context: str) -> None:
    assert_true(mapping.get("DRY_RUN_ONLY") == "TRUE", f"{context} DRY_RUN_ONLY expected TRUE, got {mapping.get('DRY_RUN_ONLY')}")
    for key in SAFETY_FALSE_FLAGS:
        if key in mapping:
            assert_true(mapping.get(key) == "FALSE", f"{context} {key} expected FALSE, got {mapping.get(key)}")


def test_safety_boundaries_from_outputs() -> None:
    for filename in [
        "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv",
        "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv",
    ]:
        rows, _ = read_csv(CONSOLIDATION / filename)
        assert_true(len(rows) == 1, f"{filename} expected 1 row, got {len(rows)}")
        assert_safety_flags(rows[0], filename)
        assert_true(clean(rows[0].get("STAGE_NAME")) == STAGE_NAME, f"{filename} stage name mismatch")

    read_first_flags = read_flags(OPS / "V20_43_READ_FIRST.txt")
    assert_safety_flags(read_first_flags, "READ_FIRST")
    assert_true(read_first_flags.get("NETWORK_REFRESH_EXECUTED") == "FALSE", "READ_FIRST NETWORK_REFRESH_EXECUTED expected FALSE")
    assert_true(read_first_flags.get("YFINANCE_REFRESH_EXECUTED") == "FALSE", "READ_FIRST YFINANCE_REFRESH_EXECUTED expected FALSE")
    assert_true(read_first_flags.get("PRIOR_ACCEPTED_OUTPUTS_MUTATED") == "FALSE", "READ_FIRST prior outputs mutation expected FALSE")

    report_text = (READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md").read_text(encoding="utf-8")
    required_phrases = [
        "DRY_RUN_ONLY=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "BROKER_ORDER_PATH_CREATED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED=FALSE",
        "PROVIDER_REFRESH_EXECUTED=FALSE",
        "V21_OUTPUTS_CREATED=FALSE",
        "V19_21_OUTPUTS_CREATED=FALSE",
    ]
    for phrase in required_phrases:
        assert_true(phrase in report_text, f"Report missing safety phrase: {phrase}")


def test_current_alias_report() -> None:
    path = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md"
    text = path.read_text(encoding="utf-8")
    assert_true(path.stat().st_size > 0, "Current alias report is empty")
    assert_true(STAGE_NAME in text, "Current alias report does not correspond to V20.43")
    assert_true("dry run" in text.lower() or "dry-run" in text.lower(), "Current alias report lacks dry-run language")
    assert_true("not official" in text.lower(), "Current alias report lacks reporting-only/not-official language")
    for pattern in REPORT_FORBIDDEN_READY_CLAIMS:
        assert_true(not pattern.search(text), f"Current alias report contains forbidden readiness claim: {pattern.pattern}")


def test_read_first() -> None:
    path = OPS / "V20_43_READ_FIRST.txt"
    text = path.read_text(encoding="utf-8")
    flags = read_flags(path)
    assert_true(path.stat().st_size > 0, "READ_FIRST is empty")
    assert_true(flags.get("STAGE_NAME") == STAGE_NAME, "READ_FIRST missing stage name")
    assert_true("READ_FIRST_PURPOSE" in flags, "READ_FIRST missing purpose/next-step guidance")
    assert_true(flags.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION") == "FALSE", "READ_FIRST claims official readiness")
    assert_true("OFFICIAL_RECOMMENDATION_CREATED=FALSE" in text, "READ_FIRST missing official recommendation safety flag")


def string_literals_from_ast(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_static_path_and_execution_safety_scans() -> None:
    scan_paths = [
        SCRIPT_DIR / "v20_43_daily_operator_report_dry_run.py",
        SCRIPT_DIR / "run_v20_43_daily_operator_report_dry_run.ps1",
        SCRIPT_DIR / "test_v20_43_daily_operator_report_dry_run.py",
    ]
    forbidden_path_write = re.compile(r"outputs[\\/](?:v21|v19_21|v19[\\/]V19_21)", re.IGNORECASE)
    execution_patterns = [
        re.compile(r"\bsubmit_order\b|\bplace_order\b|\bbroker\.(?:buy|sell|order|submit)", re.IGNORECASE),
        re.compile(r"\blive_trading\s*=\s*TRUE\b|\bLIVE_TRADING\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\breal_portfolio_mutat(?:e|ion)\b.*\bTRUE\b", re.IGNORECASE),
        re.compile(r"\brequests\.(?:get|post|put|delete)\b|\bhttpx\.(?:get|post|put|delete)\b", re.IGNORECASE),
        re.compile(r"\byfinance\.download\b|\byf\.download\b", re.IGNORECASE),
    ]

    production_literals = string_literals_from_ast(SCRIPT_DIR / "v20_43_daily_operator_report_dry_run.py")
    for literal in production_literals:
        assert_true(not forbidden_path_write.search(literal), f"Forbidden output path write literal in production script: {literal}")

    for path in scan_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in execution_patterns:
            assert_true(not pattern.search(text), f"Forbidden executable logic {pattern.pattern!r} found in {path}")


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def test_pycache_hygiene() -> None:
    cleanup_pycache()
    remaining = [str(path) for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]
    assert_true(not remaining, f"__pycache__ remains under scripts/v20: {remaining}")


def main() -> int:
    tests = [
        test_required_files_exist,
        test_required_csvs_non_empty_columns_and_counts,
        test_missing_required_sources_zero,
        test_section_coverage,
        test_input_dependency_coverage,
        test_safety_boundaries_from_outputs,
        test_current_alias_report,
        test_read_first,
        test_static_path_and_execution_safety_scans,
        test_pycache_hygiene,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL_DETAIL: {failure}")
        print("FAIL_V20_43_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
