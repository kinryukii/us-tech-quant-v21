from __future__ import annotations

import ast
import csv
import importlib.util
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

PASS_STATUS = "PASS_V20_49_TESTS"
STAGE = "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
RUN_ID_PATTERN = re.compile(r"V20_47_\d{8}T\d{6}Z")
NEXT_STAGE = "V20.49_FORMAL_TESTS"
DECISION_PACKET_STAGE = "V20.50_RESEARCH_ONLY_DECISION_PACKET"
ACCEPTANCE_STATUS = "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY"

OUT_SUMMARY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
OUT_RESEARCH_GATE = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
OUT_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
OUT_STATIC_ACCEPTANCE = CONSOLIDATION / "V20_49_STATIC_OPERATOR_REVIEW_ACCEPTANCE.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_49_SOURCE_AUDIT.csv"
OUT_GATE_DIAGNOSTICS = CONSOLIDATION / "V20_49_GATE_DIAGNOSTICS.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_49_UPSTREAM_V20_48_VALIDATION.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_49_OPERATOR_BENCHMARK_REVIEW_READINESS.csv"
OUT_FACTOR = CONSOLIDATION / "V20_49_OPERATOR_FACTOR_REVIEW_READINESS.csv"
OUT_ENTRY = CONSOLIDATION / "V20_49_OPERATOR_ENTRY_STRATEGY_REVIEW_READINESS.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_49_OPERATOR_LINEAGE_REVIEW_READINESS.csv"
OUT_CHECKLIST = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_CHECKLIST.csv"
OUT_ACTION = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_49_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OPERATOR_REVIEW_ACCEPTANCE_GATE.md"
READ_FIRST = OPS / "V20_49_READ_FIRST.txt"

IN_V47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_CACHE_HASH_LEDGER = CONSOLIDATION / "V20_47_CACHE_HASH_LEDGER.csv"
IN_V48_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
IN_V48_CANDIDATE = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
IN_V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
IN_V48_LINEAGE = CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"

REQUIRED_FILES = [
    OUT_SUMMARY,
    OUT_UPSTREAM,
    OUT_MANIFEST,
    OUT_CANDIDATE,
    OUT_BENCHMARK,
    OUT_FACTOR,
    OUT_ENTRY,
    OUT_LINEAGE,
    OUT_CHECKLIST,
    OUT_ACTION,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
    OUT_RESEARCH_GATE,
    OUT_PROMOTION_GATE,
    OUT_STATIC_ACCEPTANCE,
    OUT_SOURCE_AUDIT,
    OUT_GATE_DIAGNOSTICS,
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_48_report_status",
    "upstream_v20_48_tests_status",
    "v20_47_run_id",
    "refreshed_report_available",
    "refreshed_candidate_rows_available",
    "refreshed_benchmark_rows_available",
    "factor_rows_available",
    "entry_strategy_rows_available",
    "active_candidate_rows_available",
    "prepared_candidate_input_rows",
    "benchmark_rows_available",
    "research_only_gate_status",
    "official_promotion_gate_status",
    "lineage_rows_available",
    "expected_lineage_row_policy",
    "minimum_required_lineage_rows",
    "actual_lineage_rows_available",
    "lineage_row_count_validation_status",
    "duplicate_lineage_rows",
    "malformed_lineage_rows",
    "stale_lineage_rows",
    "missing_required_lineage_sources",
    "operator_review_package_created",
    "operator_review_ready",
    "research_only_status",
    "provider_refresh_executed_in_this_stage",
    "yfinance_import_used_in_this_stage",
    "official_recommendation_allowed",
    "official_trading_allowed",
    "broker_order_execution_used",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "returns_calculated",
    "scores_recomputed",
    "rankings_recomputed",
    "blocker_count",
    "warning_count",
    "acceptance_status",
    "next_recommended_stage",
}


def research_only_mode() -> bool:
    if not OUT_RESEARCH_GATE.exists() or not OUT_PROMOTION_GATE.exists():
        return False
    research_rows, _ = read_csv(OUT_RESEARCH_GATE)
    promotion_rows, _ = read_csv(OUT_PROMOTION_GATE)
    return bool(
        research_rows
        and promotion_rows
        and clean(research_rows[0].get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
        and clean(promotion_rows[0].get("official_promotion_gate_status")) == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE"
    )

UPSTREAM_ITEMS = {
    "v20_48_summary_exists_non_empty",
    "v20_48_refreshed_candidate_view_exists_non_empty",
    "v20_48_benchmark_context_exists_non_empty",
    "v20_48_factor_support_exists_non_empty",
    "v20_48_entry_strategy_exists_non_empty",
    "v20_48_lineage_freshness_exists_non_empty",
    "v20_48_action_boundary_exists_non_empty",
    "v20_48_safety_boundary_exists_non_empty",
    "v20_48_next_step_exists_non_empty",
    "v20_48_read_center_report_exists_non_empty",
    "v20_48_current_alias_exists_non_empty",
    "v20_48_read_first_exists_non_empty",
    "v20_48_formal_test_script_exists",
    "v20_48_report_status",
    "v20_48_tests_status",
    "v20_48_candidate_rows_with_refreshed_price",
    "v20_48_missing_refreshed_price",
    "v20_48_official_recommendation_allowed",
    "v20_48_official_trading_allowed",
    "v20_48_provider_refresh_executed_in_this_stage",
    "v20_48_yfinance_import_used_in_this_stage",
    "v20_48_broker_order_execution_used",
    "v20_48_official_ranking_mutated",
    "v20_48_dynamic_weighting_mutated",
    "v20_48_returns_calculated",
    "v20_48_scores_recomputed",
    "v20_48_rankings_recomputed",
}

PACKAGE_ITEMS = {
    "refreshed operator research report",
    "refreshed candidate research view",
    "refreshed benchmark context view",
    "refreshed factor support view",
    "refreshed entry strategy view",
    "refreshed lineage/freshness view",
    "refreshed action boundary",
    "refreshed safety boundary",
    "V20.47 run/cache certification reference",
    "V20.48 READ_FIRST",
    "V20.48 current alias report",
}

TRUE_BOUNDARIES = {
    "operator_research_review_allowed",
    "candidate_review_allowed",
    "benchmark_context_review_allowed",
    "factor_review_allowed",
    "entry_strategy_review_allowed",
    "lineage_review_allowed",
    "research_only_decision_packet_preparation_allowed_next",
}

FALSE_BOUNDARIES = {
    "provider_refresh_allowed_in_this_stage",
    "yfinance_import_allowed_in_this_stage",
    "official_buy_sell_hold_recommendation_allowed",
    "live_trading_allowed",
    "broker_order_execution_allowed",
    "official_ranking_mutation_allowed",
    "dynamic_weighting_mutation_allowed",
    "real_portfolio_mutation_allowed",
    "return_calculation_allowed",
    "score_recomputation_allowed",
    "ranking_recomputation_allowed",
    "trading_signal_generation_allowed",
}

SAFETY_CHECKS = {
    "provider_refresh_executed_in_v20_49": "FALSE",
    "yfinance_imported_in_v20_49": "FALSE",
    "refreshed_v20_48_report_used": "TRUE",
    "v20_47_certified_cache_reference_used": "TRUE",
    "broker_order_execution_used": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "official_trading_allowed": "FALSE",
    "official_ranking_mutated": "FALSE",
    "dynamic_weighting_mutated": "FALSE",
    "real_portfolio_mutated": "FALSE",
    "returns_calculated": "FALSE",
    "scores_recomputed": "FALSE",
    "rankings_recomputed": "FALSE",
    "trading_signals_created": "FALSE",
    "v21_output_path_created": "FALSE",
    "v19_21_output_path_created": "FALSE",
}

CHECKLIST_ITEMS = {
    "candidate review completeness",
    "refreshed price mapping review",
    "benchmark context review",
    "factor support review",
    "entry strategy research review",
    "lineage/freshness review",
    "action boundary review",
    "safety boundary review",
    "no official recommendation confirmation",
    "no trading authorization confirmation",
    "no broker/order confirmation",
    "no provider refresh in V20.49 confirmation",
    "no score/ranking/return recomputation confirmation",
    "next-stage research-only decision packet readiness",
}

RUN_ID_COLUMNS = [
    "run_id",
    "upstream_run_id",
    "v20_47_run_id",
    "current_market_refresh_run_id",
    "cache_run_id",
    "refresh_run_id",
    "source_run_id",
    "lineage_run_id",
    "upstream_v20_47_run_id",
    "v20_48_upstream_run_id",
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def load_production_module():
    path = SCRIPT_DIR / "v20_49_operator_review_acceptance_gate.py"
    spec = importlib.util.spec_from_file_location("v20_49_stage", path)
    assert_true(spec is not None and spec.loader is not None, "Unable to load V20.49 production module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def assert_columns(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing required columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows, columns


def by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {clean(row.get(key)): row for row in rows}


def valid_v20_47_run_id(value: object) -> bool:
    return RUN_ID_PATTERN.fullmatch(clean(value)) is not None


def run_ids_from_rows(rows: list[dict[str, str]], columns: list[str]) -> set[str]:
    ids: set[str] = set()
    lower_to_actual = {column.lower(): column for column in columns}
    for wanted in RUN_ID_COLUMNS:
        actual = lower_to_actual.get(wanted.lower())
        if not actual:
            continue
        for row in rows:
            value = clean(row.get(actual))
            if value:
                assert_true(valid_v20_47_run_id(value), f"Invalid V20.47 run_id format in {actual}: {value}")
                ids.add(value)
    if ids:
        return ids

    for row in rows:
        for value in row.values():
            for match in RUN_ID_PATTERN.findall(clean(value)):
                ids.add(match)
    return ids


def run_ids_by_artifact(paths: list[Path]) -> dict[Path, set[str]]:
    found: dict[Path, set[str]] = {}
    for path in paths:
        rows, columns = read_csv(path)
        found[path] = run_ids_from_rows(rows, columns)
    return found


def discover_active_v20_47_run_id() -> str:
    v49_paths = [OUT_SUMMARY, OUT_CANDIDATE, OUT_BENCHMARK, OUT_LINEAGE]
    v49_ids = run_ids_by_artifact(v49_paths)
    present_v49 = {path: ids for path, ids in v49_ids.items() if ids}

    if present_v49:
        all_ids = set().union(*present_v49.values())
        assert_true(len(all_ids) == 1, f"V20.49 outputs reference inconsistent V20.47 run_ids: {present_v49}")
        run_id = next(iter(all_ids))
    else:
        v48_ids = run_ids_by_artifact([IN_V48_SUMMARY, IN_V48_CANDIDATE, IN_V48_BENCHMARK, IN_V48_LINEAGE])
        missing_v48 = [path.name for path, ids in v48_ids.items() if not ids]
        assert_true(not missing_v48, f"No V20.47 run_id discovered from V20.49 or V20.48 outputs: {missing_v48}")
        all_ids = set().union(*v48_ids.values())
        assert_true(len(all_ids) == 1, f"V20.48 outputs reference inconsistent V20.47 run_ids: {v48_ids}")
        run_id = next(iter(all_ids))

    assert_true(valid_v20_47_run_id(run_id), f"Invalid discovered V20.47 run_id format: {run_id}")
    return run_id


def assert_v20_49_v20_48_run_id_consistency(run_id: str) -> None:
    paths = [OUT_SUMMARY, OUT_CANDIDATE, OUT_BENCHMARK, OUT_LINEAGE, IN_V48_SUMMARY, IN_V48_CANDIDATE, IN_V48_BENCHMARK, IN_V48_LINEAGE]
    by_artifact = run_ids_by_artifact(paths)
    mismatches = {path.name: ids for path, ids in by_artifact.items() if ids and ids != {run_id}}
    assert_true(not mismatches, f"V20.49/V20.48 run_id mismatch for active {run_id}: {mismatches}")


def assert_run_id_exists_in_v20_47_artifacts(run_id: str) -> None:
    artifact_ids: dict[str, set[str]] = {}
    for path in [IN_V47_SUMMARY, IN_V47_CACHE_HASH_LEDGER]:
        rows, columns = assert_columns(path, {"run_id"})
        artifact_ids[path.name] = run_ids_from_rows(rows, columns)
    assert_true(any(run_id in ids for ids in artifact_ids.values()), f"Discovered run_id {run_id} not found in V20.47 artifacts: {artifact_ids}")


def assert_no_recommendation_language(rows: list[dict[str, str]], context: str) -> None:
    forbidden = [
        re.compile(r"\bofficial\s+(buy|sell|hold)\b", re.IGNORECASE),
        re.compile(r"\b(buy|sell|hold)\s+recommendation\b", re.IGNORECASE),
        re.compile(r"\btrading-authorized\b|\blive\s+trade\b", re.IGNORECASE),
    ]
    for idx, row in enumerate(rows, start=1):
        text = " ".join(clean(value).lower() for value in row.values())
        for pattern in forbidden:
            assert_true(not pattern.search(text), f"{context} row {idx} contains forbidden recommendation/trading language")


def test_required_outputs_exist_and_non_empty() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing V20.49 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty V20.49 outputs: {empty}")


def test_acceptance_summary() -> None:
    rows, _ = assert_columns(OUT_SUMMARY, SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    run_id = discover_active_v20_47_run_id()
    assert_v20_49_v20_48_run_id_consistency(run_id)
    assert_run_id_exists_in_v20_47_artifacts(run_id)
    if research_only_mode():
        assert_true(clean(row.get("acceptance_status")) == "BLOCKED_OPERATOR_REVIEW_ACCEPTANCE", "Operator acceptance must remain blocked in research-only mode")
        assert_true(clean(row.get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE", "Research-only gate must pass")
        assert_true(clean(row.get("official_promotion_gate_status")) == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE", "Official promotion gate must remain blocked")
        assert_true(as_int(row.get("active_candidate_rows_available")) > 0, "Active candidate rows must be available")
        assert_true(as_int(row.get("factor_rows_available")) > 0, "Factor rows must be available")
        assert_true(as_int(row.get("prepared_candidate_input_rows")) > 0, "Prepared candidate input rows must be available")
        assert_true(as_int(row.get("benchmark_rows_available")) >= 2, "Benchmark rows must be available")
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", "Official recommendation must remain disallowed")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", "Official trading must remain disallowed")
        return
    expected = {
        "stage": STAGE,
        "upstream_v20_48_report_status": "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED",
        "upstream_v20_48_tests_status": "PASS",
        "refreshed_report_available": "TRUE",
        "refreshed_candidate_rows_available": "50",
        "refreshed_benchmark_rows_available": "2",
        "factor_rows_available": "21",
        "entry_strategy_rows_available": "5",
        "operator_review_package_created": "TRUE",
        "operator_review_ready": "TRUE",
        "research_only_status": "TRUE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "blocker_count": "0",
        "warning_count": "0",
        "acceptance_status": ACCEPTANCE_STATUS,
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {row.get(key)}")
    assert_true(as_int(row.get("lineage_rows_available")) >= as_int(row.get("minimum_required_lineage_rows")), "Summary lineage rows below minimum")
    assert_true(clean(row.get("lineage_row_count_validation_status")) == "PASS", "Lineage row policy did not pass")
    assert_true(clean(row.get("duplicate_lineage_rows")) == "0", "Duplicate lineage rows detected")
    assert_true(clean(row.get("malformed_lineage_rows")) == "0", "Malformed lineage rows detected")
    assert_true(clean(row.get("stale_lineage_rows")) == "0", "Stale lineage rows detected")
    assert_true(clean(row.get("missing_required_lineage_sources")) == "", "Required lineage source missing")
    assert_true(clean(row.get("v20_47_run_id")) == run_id, f"Summary v20_47_run_id expected active run_id {run_id}, got {row.get('v20_47_run_id')}")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, DECISION_PACKET_STAGE}, "Unexpected next recommended stage")


def test_upstream_validation() -> None:
    rows, _ = assert_columns(OUT_UPSTREAM, {"validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    by_item = by_key(rows, "validation_item")
    missing = sorted(UPSTREAM_ITEMS - set(by_item))
    assert_true(not missing, f"Missing upstream validation rows: {missing}")
    if research_only_mode():
        assert_true(clean(by_item["v20_48_tests_status"].get("validation_status")) == "BLOCKED", "V20.48 tests should remain an official promotion blocker in current fixture")
        return
    for item in UPSTREAM_ITEMS:
        row = by_item[item]
        assert_true(clean(row.get("validation_status")) == "PASS", f"{item} did not pass")
        assert_true(not clean(row.get("blocker_reason")), f"{item} has blocker_reason {row.get('blocker_reason')}")


def test_package_manifest() -> None:
    rows, _ = assert_columns(OUT_MANIFEST, {"package_item", "artifact_path", "artifact_role", "required_for_operator_review", "exists_flag", "non_empty_flag", "review_use", "research_only_flag", "official_recommendation_allowed", "trading_allowed", "validation_status", "blocker_reason"})
    by_item = by_key(rows, "package_item")
    missing = sorted(PACKAGE_ITEMS - set(by_item))
    assert_true(not missing, f"Manifest missing package items: {missing}")
    for item in PACKAGE_ITEMS:
        row = by_item[item]
        assert_true(clean(row.get("exists_flag")) == "TRUE", f"{item} does not exist")
        assert_true(clean(row.get("non_empty_flag")) == "TRUE", f"{item} is empty")
        assert_true(clean(row.get("validation_status")) == "PASS", f"{item} did not pass")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", f"{item} research_only_flag not TRUE")
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", f"{item} recommendation allowed")
        assert_true(clean(row.get("trading_allowed")) == "FALSE", f"{item} trading allowed")


def test_candidate_benchmark_readiness() -> None:
    if research_only_mode():
        research_rows, _ = assert_columns(OUT_RESEARCH_GATE, {"active_candidate_rows_available", "benchmark_rows_available", "research_only_gate_status"})
        assert_true(as_int(research_rows[0].get("active_candidate_rows_available")) > 0, "Research gate must expose active candidates")
        assert_true(as_int(research_rows[0].get("benchmark_rows_available")) >= 2, "Research gate must expose benchmark rows")
        return
    run_id = discover_active_v20_47_run_id()
    candidate_rows, _ = assert_columns(OUT_CANDIDATE, {"report_rank", "normalized_ticker", "display_name_or_ticker", "research_category", "report_section", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "refreshed_price_certification_status", "refreshed_price_mapping_status", "duplicate_ticker_mapping_flag", "review_ready", "operator_review_scope", "required_human_checks", "research_only_flag", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "blocker_reason"})
    assert_true(len(candidate_rows) == 50, f"Candidate readiness expected 50 rows, got {len(candidate_rows)}")
    assert_true(any(clean(row.get("duplicate_ticker_mapping_flag")) == "TRUE" for row in candidate_rows), "Duplicate ticker mapping not represented")
    for row in candidate_rows:
        assert_true(clean(row.get("v20_47_run_id")) == run_id, "Candidate run_id mismatch")
        assert_true(clean(row.get("review_ready")) == "TRUE", "Candidate not review_ready")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Candidate research_only_flag not TRUE")
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", "Candidate recommendation allowed")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", "Candidate trading allowed")
        assert_true(clean(row.get("broker_execution_allowed")) == "FALSE", "Candidate broker execution allowed")
    assert_no_recommendation_language(candidate_rows, "candidate readiness")

    benchmark_rows, columns = assert_columns(OUT_BENCHMARK, {"benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "certification_status", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated", "official_trading_allowed", "blocker_reason"})
    assert_true({clean(row.get("benchmark_ticker")) for row in benchmark_rows} == {"SPY", "QQQ"}, "Benchmark readiness missing SPY/QQQ")
    forbidden_return_cols = [column for column in columns if "return" in column.lower() and column != "benchmark_return_calculated"]
    assert_true(not forbidden_return_cols, f"Benchmark readiness has return columns: {forbidden_return_cols}")
    for row in benchmark_rows:
        assert_true(clean(row.get("v20_47_run_id")) == run_id, "Benchmark run_id mismatch")
        assert_true(clean(row.get("review_ready")) == "TRUE", "Benchmark not review_ready")
        assert_true(clean(row.get("benchmark_context_allowed")) == "TRUE", "Benchmark context not allowed")
        assert_true(clean(row.get("benchmark_return_calculated")) == "FALSE", "Benchmark return calculated")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", "Benchmark trading allowed")


def test_factor_entry_lineage_readiness() -> None:
    if research_only_mode():
        research_rows, _ = assert_columns(OUT_RESEARCH_GATE, {"factor_rows_available", "prepared_candidate_input_rows"})
        promotion_rows, _ = assert_columns(OUT_PROMOTION_GATE, {"missing_promotion_lineage_sources", "official_promotion_gate_status"})
        assert_true(as_int(research_rows[0].get("factor_rows_available")) > 0, "Research gate must expose factor rows")
        assert_true(as_int(research_rows[0].get("prepared_candidate_input_rows")) > 0, "Research gate must expose prepared candidate input rows")
        assert_true("V20.35-R2" in clean(promotion_rows[0].get("missing_promotion_lineage_sources")), "Missing lineage sources must remain promotion blockers")
        return
    factor_rows, _ = assert_columns(OUT_FACTOR, {"factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section", "refreshed_market_context_available", "review_ready", "operator_review_scope", "included_in_official_weight_flag", "dynamic_weighting_mutated", "research_only_flag", "blocker_reason"})
    assert_true(len(factor_rows) == 21, f"Factor readiness expected 21 rows, got {len(factor_rows)}")
    for row in factor_rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Factor refreshed context not TRUE")
        assert_true(clean(row.get("review_ready")) == "TRUE", "Factor not review_ready")
        assert_true(clean(row.get("dynamic_weighting_mutated")) == "FALSE", "Factor dynamic weighting mutated")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Factor research_only_flag not TRUE")
        assert_true(clean(row.get("included_in_official_weight_flag")) == "FALSE", "Factor included in official weight")

    entry_rows, _ = assert_columns(OUT_ENTRY, {"strategy_id_or_name", "strategy_family", "readiness_status", "report_section", "refreshed_market_context_available", "review_ready", "operator_review_scope", "allowed_in_research_report", "allowed_for_live_trading", "broker_execution_enabled", "research_only_flag", "blocker_reason"})
    assert_true(len(entry_rows) == 5, f"Entry readiness expected 5 rows, got {len(entry_rows)}")
    for row in entry_rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Entry refreshed context not TRUE")
        assert_true(clean(row.get("review_ready")) == "TRUE", "Entry not review_ready")
        assert_true(clean(row.get("allowed_in_research_report")) == "TRUE", "Entry not allowed in research report")
        assert_true(clean(row.get("allowed_for_live_trading")) == "FALSE", "Entry live trading allowed")
        assert_true(clean(row.get("broker_execution_enabled")) == "FALSE", "Entry broker execution enabled")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Entry research_only_flag not TRUE")

    lineage_rows, _ = assert_columns(OUT_LINEAGE, {"source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status", "v20_47_run_id", "v20_47_cache_hash_reference", "refreshed_cache_certified", "review_ready", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading", "blocker_count", "warning_count", "blocker_reason"})
    assert_true(len(lineage_rows) >= 35, f"Lineage readiness expected at least 35 rows, got {len(lineage_rows)}")
    assert_true(any(clean(row.get("refreshed_cache_certified")) == "TRUE" and clean(row.get("v20_47_cache_hash_reference")) for row in lineage_rows), "Lineage lacks V20.47 cache/certification reference")
    for row in lineage_rows:
        if as_int(row.get("blocker_count")) == 0:
            assert_true(clean(row.get("review_ready")) == "TRUE", "Lineage not review_ready with zero blockers")
            assert_true(clean(row.get("safe_for_research_report")) == "TRUE", "Lineage not safe for research with zero blockers")
        assert_true(clean(row.get("safe_for_official_recommendation")) == "FALSE", "Lineage official recommendation safe")
        assert_true(clean(row.get("safe_for_trading")) == "FALSE", "Lineage trading safe")


def test_checklist() -> None:
    rows, _ = assert_columns(OUT_CHECKLIST, {"checklist_item_id", "checklist_item", "review_category", "required_before_next_stage", "expected_evidence", "allowed_action", "blocked_action", "completion_status", "blocker_if_missing"})
    names = {clean(row.get("checklist_item")) for row in rows}
    missing = sorted(CHECKLIST_ITEMS - names)
    assert_true(not missing, f"Checklist missing items: {missing}")
    for row in rows:
        assert_true(clean(row.get("completion_status")) in {"PREPARED", "READY_FOR_OPERATOR_REVIEW"}, f"Unexpected checklist status {row.get('completion_status')}")
        blocked = clean(row.get("blocked_action")).lower()
        assert_true("official recommendation" in blocked and "broker/order" in blocked, "Checklist blocked_action does not block official/broker actions")
        text = " ".join(clean(value).lower() for value in row.values())
        assert_true("live trading allowed" not in text and "official recommendation allowed" not in text, "Checklist authorizes forbidden action")


def test_action_and_safety_boundaries() -> None:
    action_rows, _ = assert_columns(OUT_ACTION, {"boundary_name", "allowed_flag", "evidence", "blocker_reason"})
    action = by_key(action_rows, "boundary_name")
    missing = sorted((TRUE_BOUNDARIES | FALSE_BOUNDARIES) - set(action))
    assert_true(not missing, f"Action boundary missing rows: {missing}")
    for name in TRUE_BOUNDARIES:
        assert_true(clean(action[name].get("allowed_flag")) == "TRUE", f"{name} expected TRUE")
    for name in FALSE_BOUNDARIES:
        assert_true(clean(action[name].get("allowed_flag")) == "FALSE", f"{name} expected FALSE")

    safety_rows, _ = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    safety = by_key(safety_rows, "safety_boundary")
    missing_safety = sorted(set(SAFETY_CHECKS) - set(safety))
    assert_true(not missing_safety, f"Safety boundary missing rows: {missing_safety}")
    for name, expected in SAFETY_CHECKS.items():
        row = safety[name]
        assert_true(clean(row.get("expected_value")) == expected, f"{name} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"{name} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not pass")


def test_next_step_decision() -> None:
    rows, _ = assert_columns(OUT_NEXT, {"stage", "decision", "operator_review_package_created", "operator_review_ready", "research_only_status", "research_only_decision_packet_allowed_next", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "formal_tests_required_next", "blocker_count", "warning_count", "next_recommended_stage"})
    assert_true(len(rows) == 1, f"Next-step expected 1 row, got {len(rows)}")
    row = rows[0]
    if research_only_mode():
        assert_true(clean(row.get("decision")) == "WARN_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED", "Next-step should warn research-only ready / promotion blocked")
        assert_true(clean(row.get("research_only_decision_packet_allowed_next")) == "TRUE", "Research-only packet must be allowed next")
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", "Official recommendation must remain disallowed")
        return
    expected = {
        "stage": STAGE,
        "decision": "PASS_OPERATOR_REVIEW_ACCEPTED_RESEARCH_ONLY",
        "operator_review_package_created": "TRUE",
        "operator_review_ready": "TRUE",
        "research_only_status": "TRUE",
        "research_only_decision_packet_allowed_next": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": "0",
        "warning_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, DECISION_PACKET_STAGE}, "Unexpected next recommended stage")


def test_report_alias_read_first() -> None:
    run_id = discover_active_v20_47_run_id()
    text = REPORT.read_text(encoding="utf-8")
    lower = text.lower()
    required = [
        "v20.49",
        "operator review",
        "v20.48 refreshed report",
        run_id.lower(),
        "performs no provider/network refresh",
        "does not use yfinance",
        "not an official recommendation",
        "no trading signals",
        "no broker/order execution",
        "no forward returns",
        "no benchmark-relative returns",
        "no scores",
        "no rankings",
        "candidate review readiness",
        "benchmark review readiness",
        "factor review readiness",
        "entry strategy review readiness",
        "lineage/freshness review readiness",
        "operator review checklist",
        "next recommended stage",
    ]
    for phrase in required:
        assert_true(phrase in lower, f"Report missing phrase: {phrase}")
    assert_true(not re.search(r"\bofficial\s+(buy|sell|hold)\b|\b(buy|sell|hold)\s+recommendation\b", lower), "Report contains official buy/sell/hold language")

    alias = CURRENT_REPORT.read_text(encoding="utf-8")
    alias_lower = alias.lower()
    assert_true(STAGE in alias, "Current alias does not correspond to V20.49")
    assert_true("operator review acceptance gate" in alias_lower, "Alias missing operator review acceptance gate language")
    assert_true("research-only" in alias_lower, "Alias missing research-only language")
    assert_true("ready for official trading" not in alias_lower, "Alias claims official trading readiness")
    assert_true("ready for official recommendation" not in alias_lower, "Alias claims official recommendation readiness")

    flags = read_flags(READ_FIRST)
    if research_only_mode():
        assert_true(flags.get("RESEARCH_ONLY_GATE_STATUS") == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE", "READ_FIRST missing research-only PASS")
        assert_true(flags.get("OFFICIAL_PROMOTION_GATE_STATUS") == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE", "READ_FIRST missing promotion BLOCKED")
        assert_true(flags.get("OFFICIAL_RECOMMENDATION_ALLOWED") == "FALSE", "READ_FIRST must disallow official recommendation")
        return
    expected = {
        "STAGE_NAME": STAGE,
        "OPERATOR_REVIEW_GATE_STATUS": "TRUE",
        "V20_48_REFRESHED_REPORT_USED": "TRUE",
        "V20_47_RUN_ID": run_id,
        "REPORT_REVIEW_ONLY": "TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_49": "FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_49": "FALSE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "RETURNS_CALCULATED": "FALSE",
        "SCORES_RECOMPUTED": "FALSE",
        "RANKINGS_RECOMPUTED": "FALSE",
        "RESEARCH_ONLY_STATUS": "TRUE",
        "NEXT_RECOMMENDED_STAGE": NEXT_STAGE,
    }
    for key, value in expected.items():
        assert_true(flags.get(key) == value, f"READ_FIRST {key} expected {value}, got {flags.get(key)}")


def python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_static_safety_scans() -> None:
    production = SCRIPT_DIR / "v20_49_operator_review_acceptance_gate.py"
    wrapper = SCRIPT_DIR / "run_v20_49_operator_review_acceptance_gate.ps1"
    test_script = SCRIPT_DIR / "test_v20_49_operator_review_acceptance_gate.py"
    texts = [(path, path.read_text(encoding="utf-8", errors="ignore")) for path in [production, wrapper, test_script]]
    executable_patterns = [
        re.compile(r"^\s*(import|from)\s+yfinance\b", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\byfinance\.\w+\s*\(|\byf\.\w+\s*\(", re.IGNORECASE),
        re.compile(r"\brequests\.(?:get|post|put|delete)\s*\(|\bhttpx\.(?:get|post|put|delete)\s*\(", re.IGNORECASE),
        re.compile(r"\bsubmit_order\s*\(|\bplace_order\s*\(|\bbroker\.(?:buy|sell|order|submit)\s*\(", re.IGNORECASE),
        re.compile(r"\blive_trading\s*=\s*TRUE\b|\bLIVE_TRADING\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\breal_portfolio_mutat(?:e|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_recommendation_(?:created|generated|allowed)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_ranking_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bdynamic_weighting_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\b(calculate_returns|compute_returns|calculate_benchmark_relative_returns|recompute_scores|recompute_rankings|calculate_scores|calculate_rankings)\s*\(", re.IGNORECASE),
        re.compile(r"\btrading_signal(?:s)?_(?:created|generated)\b\s*=\s*TRUE\b", re.IGNORECASE),
    ]
    for path, text in texts:
        for pattern in executable_patterns:
            assert_true(not pattern.search(text), f"Forbidden executable logic {pattern.pattern!r} found in {path}")

    forbidden_path_parts = [("outputs", "v21"), ("outputs", "v19_21"), ("outputs", "v19", "V19_21")]
    for literal in python_string_literals(production):
        normalized = literal.replace("\\", "/")
        parts = tuple(part.lower() for part in normalized.split("/"))
        for forbidden in forbidden_path_parts:
            expected = tuple(part.lower() for part in forbidden)
            windows = [tuple(parts[i:i + len(expected)]) for i in range(len(parts))]
            assert_true(expected not in windows, f"Forbidden output path literal found in production: {literal}")


def valid_lineage_fixture() -> list[dict[str, object]]:
    module = load_production_module()
    rows = []
    for source in sorted(module.REQUIRED_LINEAGE_SOURCE_NAMES):
        rows.append({
            "source_name_or_input_name": source,
            "source_contract_or_version": f"outputs/v20/consolidation/{source}.csv",
            "freshness_status": "REFRESHED_CERTIFIED_CONTEXT_ATTACHED",
            "lineage_status": "SEE_PRIOR_STAGE_GATES",
            "safe_for_research_report": "TRUE",
            "blocker_count": "0",
        })
    while len(rows) < module.MINIMUM_REQUIRED_LINEAGE_ROWS:
        idx = len(rows)
        rows.append({
            "source_name_or_input_name": f"extra_{idx}",
            "source_contract_or_version": f"extra_{idx}.csv",
            "freshness_status": "V20_47_REFRESHED_CACHE_CERTIFIED",
            "lineage_status": "HASH_LEDGER_VERIFIED",
            "safe_for_research_report": "TRUE",
            "blocker_count": "0",
        })
    return rows


def test_lineage_policy_accepts_valid_rows_above_old_fixed_count() -> None:
    module = load_production_module()
    rows = valid_lineage_fixture()
    rows.extend([
        {
            "source_name_or_input_name": "extra_35",
            "source_contract_or_version": "extra_35.csv",
            "freshness_status": "V20_47_REFRESHED_CACHE_CERTIFIED",
            "lineage_status": "HASH_LEDGER_VERIFIED",
            "safe_for_research_report": "TRUE",
            "blocker_count": "0",
        },
        {
            "source_name_or_input_name": "extra_36",
            "source_contract_or_version": "extra_36.csv",
            "freshness_status": "V20_47_REFRESHED_CACHE_CERTIFIED",
            "lineage_status": "HASH_LEDGER_VERIFIED",
            "safe_for_research_report": "TRUE",
            "blocker_count": "0",
        },
        {
            "source_name_or_input_name": "extra_37",
            "source_contract_or_version": "extra_37.csv",
            "freshness_status": "V20_47_REFRESHED_CACHE_CERTIFIED",
            "lineage_status": "HASH_LEDGER_VERIFIED",
            "safe_for_research_report": "TRUE",
            "blocker_count": "0",
        },
    ])
    diagnostics = module.lineage_policy_diagnostics(rows)
    assert_true(diagnostics["actual_lineage_rows_available"] > 35, "Fixture should exceed old fixed count")
    assert_true(diagnostics["lineage_row_count_validation_status"] == "PASS", "Valid >35 lineage rows should pass")


def test_lineage_policy_detects_duplicate_malformed_stale_and_missing_source() -> None:
    module = load_production_module()
    rows = valid_lineage_fixture()
    duplicate = dict(rows[0])
    malformed = dict(rows[1])
    malformed["source_contract_or_version"] = ""
    stale = dict(rows[2])
    stale["freshness_status"] = "STALE"
    missing_source_rows = [row for row in rows if row["source_name_or_input_name"] != "V20.42"]

    duplicate_diag = module.lineage_policy_diagnostics(rows + [duplicate])
    malformed_diag = module.lineage_policy_diagnostics(rows[:1] + [malformed] + rows[2:])
    stale_diag = module.lineage_policy_diagnostics(rows[:2] + [stale] + rows[3:])
    missing_diag = module.lineage_policy_diagnostics(missing_source_rows)

    assert_true(duplicate_diag["duplicate_lineage_rows"] == 1 and duplicate_diag["lineage_row_count_validation_status"] == "BLOCKED", "Duplicate lineage key should block")
    assert_true(malformed_diag["malformed_lineage_rows"] == 1 and malformed_diag["lineage_row_count_validation_status"] == "BLOCKED", "Malformed lineage row should block")
    assert_true(stale_diag["stale_lineage_rows"] == 1 and stale_diag["lineage_row_count_validation_status"] == "BLOCKED", "Stale lineage row should block")
    assert_true("V20.42" in missing_diag["missing_required_lineage_sources"] and missing_diag["lineage_row_count_validation_status"] == "BLOCKED", "Missing required lineage source should block")


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
        test_required_outputs_exist_and_non_empty,
        test_acceptance_summary,
        test_upstream_validation,
        test_package_manifest,
        test_candidate_benchmark_readiness,
        test_factor_entry_lineage_readiness,
        test_checklist,
        test_action_and_safety_boundaries,
        test_next_step_decision,
        test_report_alias_read_first,
        test_lineage_policy_accepts_valid_rows_above_old_fixed_count,
        test_lineage_policy_detects_duplicate_malformed_stale_and_missing_source,
        test_static_safety_scans,
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
        print("FAIL_V20_49_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
