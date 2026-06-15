from __future__ import annotations

import ast
import csv
import re
import shutil
import tokenize
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

PASS_STATUS = "PASS_V20_50_TESTS"
FAIL_STATUS = "FAIL_V20_50_TESTS"
STAGE = "V20.50_RESEARCH_ONLY_DECISION_PACKET"
RUN_ID_PATTERN = re.compile(r"V20_47_\d{8}T\d{6}Z")
ACCEPTANCE_STATUS = "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY"
DECISION_PASS = "PASS_RESEARCH_ONLY_DECISION_PACKET_CREATED"
ALLOWED_NEXT_STAGES = {"V20.50_FORMAL_TESTS", "V20.51_OFFICIAL_RECOMMENDATION_READINESS_GATE"}

PROD_SCRIPT = SCRIPT_DIR / "v20_50_research_only_decision_packet.py"
WRAPPER = SCRIPT_DIR / "run_v20_50_research_only_decision_packet.ps1"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_50_research_only_decision_packet.py"

OUT_SUMMARY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_50_UPSTREAM_V20_49_VALIDATION.csv"
OUT_RULES = CONSOLIDATION / "V20_50_RESEARCH_DECISION_CATEGORY_RULES.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
OUT_FACTOR = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
OUT_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_MANIFEST.csv"
OUT_ACTION = CONSOLIDATION / "V20_50_RESEARCH_ONLY_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_50_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_50_RESEARCH_ONLY_DECISION_PACKET_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_RESEARCH_ONLY_DECISION_PACKET.md"
READ_FIRST = OPS / "V20_50_READ_FIRST.txt"

REQUIRED_FILES = [
    OUT_SUMMARY,
    OUT_UPSTREAM,
    OUT_RULES,
    OUT_CANDIDATE,
    OUT_BENCHMARK,
    OUT_FACTOR,
    OUT_ENTRY,
    OUT_LINEAGE,
    OUT_MANIFEST,
    OUT_ACTION,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_49_acceptance_status",
    "upstream_v20_49_tests_status",
    "v20_47_run_id",
    "operator_review_package_used",
    "research_only_decision_packet_created",
    "candidate_rows_included",
    "benchmark_rows_included",
    "factor_rows_included",
    "entry_strategy_rows_included",
    "lineage_rows_included",
    "expected_lineage_row_policy",
    "minimum_required_lineage_rows",
    "actual_lineage_rows_available",
    "lineage_row_count_validation_status",
    "duplicate_lineage_rows",
    "malformed_lineage_rows",
    "stale_lineage_rows",
    "checklist_rows_included",
    "research_decision_categories_created",
    "official_recommendation_allowed",
    "official_trading_allowed",
    "broker_order_execution_used",
    "provider_refresh_executed_in_this_stage",
    "yfinance_import_used_in_this_stage",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "returns_calculated",
    "scores_recomputed",
    "rankings_recomputed",
    "trading_signals_created",
    "blocker_count",
    "warning_count",
    "decision_packet_status",
    "next_recommended_stage",
}

UPSTREAM_ITEMS = {
    "v20_49_acceptance_summary_exists_non_empty",
    "v20_49_operator_package_manifest_exists_non_empty",
    "v20_49_candidate_readiness_exists_non_empty",
    "v20_49_benchmark_readiness_exists_non_empty",
    "v20_49_factor_readiness_exists_non_empty",
    "v20_49_entry_readiness_exists_non_empty",
    "v20_49_lineage_readiness_exists_non_empty",
    "v20_49_checklist_exists_non_empty",
    "v20_49_action_boundary_exists_non_empty",
    "v20_49_safety_boundary_exists_non_empty",
    "v20_49_next_step_decision_exists_non_empty",
    "v20_49_read_center_report_exists_non_empty",
    "v20_49_current_alias_exists_non_empty",
    "v20_49_read_first_exists_non_empty",
    "v20_49_formal_test_script_exists",
    "v20_49_acceptance_status",
    "v20_49_tests_status",
    "v20_49_candidate_count",
    "v20_49_benchmark_count",
    "v20_49_factor_count",
    "v20_49_entry_count",
    "v20_49_lineage_count",
    "v20_49_lineage_policy_status",
    "v20_49_duplicate_lineage_rows",
    "v20_49_malformed_lineage_rows",
    "v20_49_stale_lineage_rows",
    "v20_49_official_recommendation_allowed",
    "v20_49_official_trading_allowed",
    "v20_49_provider_refresh_executed_in_this_stage",
    "v20_49_yfinance_import_used_in_this_stage",
    "v20_49_broker_order_execution_used",
    "v20_49_official_ranking_mutated",
    "v20_49_dynamic_weighting_mutated",
    "v20_49_returns_calculated",
    "v20_49_scores_recomputed",
    "v20_49_rankings_recomputed",
    "v20_49_ranking_dynamic_mutation_boundary_false",
    "v20_49_returns_scores_rankings_recomputed_false",
    "v20_49_trading_signals_created_false",
}

RULE_CATEGORIES = {
    "PRIORITY_REVIEW",
    "STANDARD_REVIEW",
    "WATCH_CONTEXT",
    "NEEDS_HUMAN_CHECK",
    "BLOCKED_FROM_DECISION_PACKET",
}

TRUE_BOUNDARIES = {
    "research_only_decision_packet_creation_allowed",
    "candidate_research_categorization_allowed",
    "benchmark_context_inclusion_allowed",
    "factor_context_inclusion_allowed",
    "entry_strategy_context_inclusion_allowed",
    "lineage_context_inclusion_allowed",
    "future_official_recommendation_gate_preparation_allowed",
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
    "benchmark_relative_return_calculation_allowed",
    "score_recomputation_allowed",
    "ranking_recomputation_allowed",
    "trading_signal_generation_allowed",
}

SAFETY_CHECKS = {
    "provider_refresh_executed_in_v20_50": "FALSE",
    "yfinance_imported_in_v20_50": "FALSE",
    "v20_49_operator_review_package_used": "TRUE",
    "v20_48_refreshed_report_used": "TRUE",
    "v20_47_certified_cache_reference_used": "TRUE",
    "broker_order_execution_used": "FALSE",
    "official_recommendation_allowed": "FALSE",
    "official_trading_allowed": "FALSE",
    "official_ranking_mutated": "FALSE",
    "dynamic_weighting_mutated": "FALSE",
    "real_portfolio_mutated": "FALSE",
    "returns_calculated": "FALSE",
    "benchmark_relative_returns_calculated": "FALSE",
    "scores_recomputed": "FALSE",
    "rankings_recomputed": "FALSE",
    "trading_signals_created": "FALSE",
    "v21_output_path_created": "FALSE",
    "v19_21_output_path_created": "FALSE",
}

MANIFEST_ITEMS = {
    "research-only decision packet summary",
    "upstream V20.49 validation",
    "research decision category rules",
    "candidate research decision packet",
    "benchmark research context packet",
    "factor research context packet",
    "entry strategy research context packet",
    "lineage research context packet",
    "action boundary",
    "safety boundary",
    "next-step decision",
    "read-center report",
    "current alias report",
    "READ_FIRST",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def active_run_id() -> str:
    rows, _ = read_csv(OUT_SUMMARY)
    if rows and clean(rows[0].get("v20_47_run_id")):
        run_id = clean(rows[0].get("v20_47_run_id"))
    else:
        rows, _ = read_csv(CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv")
        run_id = clean(rows[0].get("v20_47_run_id")) if rows else ""
    assert_true(RUN_ID_PATTERN.fullmatch(run_id) is not None, f"Invalid active V20.47 run_id: {run_id}")
    return run_id


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


def remove_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def pycache_paths() -> list[Path]:
    return [path for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]


def strip_python_comments_and_strings(path: Path) -> str:
    tokens: list[str] = []
    source = path.read_bytes()
    for token in tokenize.tokenize(BytesIO(source).readline):
        if token.type in {tokenize.ENCODING, tokenize.STRING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE}:
            continue
        tokens.append(token.string)
    return " ".join(tokens)


def assert_no_import_yfinance(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            assert_true("yfinance" not in names, f"{path.name} imports yfinance")
        if isinstance(node, ast.ImportFrom):
            assert_true(node.module != "yfinance", f"{path.name} imports from yfinance")


def assert_no_executable_safety_patterns() -> None:
    assert_no_import_yfinance(PROD_SCRIPT)
    assert_no_import_yfinance(TEST_SCRIPT)
    python_code = strip_python_comments_and_strings(PROD_SCRIPT) + " " + strip_python_comments_and_strings(TEST_SCRIPT)
    forbidden_python = [
        r"\brequests\b",
        r"\burllib\b",
        r"\bhttpx\b",
        r"\baiohttp\b",
        r"\bsocket\b",
        r"\bdownload\s*\(",
        r"\bsubmit_order\s*\(",
        r"\bplace_order\s*\(",
        r"\balpaca\b",
        r"\bib_insync\b",
        r"\bccxt\b",
        r"outputs\s*/\s*v21",
        r"outputs\s*/\s*v19_21",
    ]
    for pattern in forbidden_python:
        assert_true(not re.search(pattern, python_code, re.IGNORECASE), f"Executable Python safety pattern found: {pattern}")
    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    forbidden_wrapper = ["import yfinance", "from yfinance", "submit_order", "place_order", "alpaca", "ib_insync", "ccxt", "outputs/v21", "outputs\\v21", "outputs/v19_21", "outputs\\v19_21", "outputs/v19/v19_21", "outputs\\v19\\v19_21"]
    for pattern in forbidden_wrapper:
        assert_true(pattern not in wrapper_text, f"Wrapper safety pattern found: {pattern}")


def forbidden_actionable_hits(text: str) -> list[str]:
    hits: list[str] = []
    allow_patterns = [
        r"not a buy signal",
        r"no buy/sell/hold recommendation",
        r"official_buy_sell_hold_recommendation_allowed",
        r"not trading-authorized",
        r"no broker/order execution",
        r"performs no broker/order execution",
        r"no trading signals",
        r"creates no trading signals",
        r"not an official recommendation",
        r"no official recommendations",
    ]
    forbidden = [
        r"\bstrong buy\b",
        r"\badd position\b",
        r"\benter position\b",
        r"\bexit position\b",
        r"\btrade now\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    lowered = text.lower()
    for pattern in allow_patterns:
        lowered = re.sub(pattern, "", lowered, flags=re.IGNORECASE)
    for pattern in forbidden:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            start = max(0, match.start() - 40)
            end = min(len(lowered), match.end() + 40)
            hits.append(lowered[start:end].replace("\n", " "))
    return hits


def test_required_outputs_exist_and_non_empty() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing V20.50 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty V20.50 outputs: {empty}")


def test_summary() -> None:
    rows, _ = assert_columns(OUT_SUMMARY, SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    run_id = active_run_id()
    expected = {
        "stage": STAGE,
        "upstream_v20_49_acceptance_status": ACCEPTANCE_STATUS,
        "upstream_v20_49_tests_status": "PASS",
        "v20_47_run_id": run_id,
        "operator_review_package_used": "TRUE",
        "research_only_decision_packet_created": "TRUE",
        "candidate_rows_included": "50",
        "benchmark_rows_included": "2",
        "factor_rows_included": "21",
        "entry_strategy_rows_included": "5",
        "research_decision_categories_created": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "trading_signals_created": "FALSE",
        "blocker_count": "0",
        "warning_count": "0",
        "decision_packet_status": DECISION_PASS,
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {clean(row.get(key))}")
    assert_true(as_int(row.get("lineage_rows_included")) >= as_int(row.get("minimum_required_lineage_rows")), "Lineage rows below minimum")
    assert_true(clean(row.get("lineage_row_count_validation_status")) == "PASS", "Lineage policy did not pass")
    assert_true(clean(row.get("duplicate_lineage_rows")) == "0", "Duplicate lineage rows detected")
    assert_true(clean(row.get("malformed_lineage_rows")) == "0", "Malformed lineage rows detected")
    assert_true(clean(row.get("stale_lineage_rows")) == "0", "Stale lineage rows detected")
    assert_true(as_int(row.get("checklist_rows_included")) > 0, "Summary checklist_rows_included must be positive")
    assert_true(clean(row.get("next_recommended_stage")) in ALLOWED_NEXT_STAGES, f"Unexpected summary next stage: {row.get('next_recommended_stage')}")


def test_upstream_validation() -> None:
    rows, _ = assert_columns(OUT_UPSTREAM, {"validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    item_map = by_key(rows, "validation_item")
    missing = sorted(UPSTREAM_ITEMS - set(item_map))
    assert_true(not missing, f"Missing V20.49 upstream validation items: {missing}")
    blocked = [row for row in rows if clean(row.get("validation_status")) != "PASS" or clean(row.get("blocker_reason"))]
    assert_true(not blocked, f"Upstream validation has blocked rows: {blocked[:3]}")


def test_category_rules() -> None:
    rows, _ = assert_columns(OUT_RULES, {"research_decision_category", "category_label", "category_purpose", "allowed_interpretation", "blocked_interpretation", "official_recommendation_allowed", "trading_allowed", "ranking_mutation_allowed", "notes"})
    row_map = by_key(rows, "research_decision_category")
    missing = sorted(RULE_CATEGORIES - set(row_map))
    assert_true(not missing, f"Missing research decision categories: {missing}")
    for row in rows:
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", "Category allows official recommendation")
        assert_true(clean(row.get("trading_allowed")) == "FALSE", "Category allows trading")
        assert_true(clean(row.get("ranking_mutation_allowed")) == "FALSE", "Category allows ranking mutation")
    priority_text = " ".join(clean(value).lower() for value in row_map["PRIORITY_REVIEW"].values())
    assert_true("research" in priority_text and "priority" in priority_text, "PRIORITY_REVIEW must be research priority")
    assert_true("not a signal" in priority_text or "not a buy signal" in priority_text or "not a signal or authorization" in priority_text, "PRIORITY_REVIEW must not imply an actionable signal")
    blocked_text = " ".join(clean(value).lower() for value in row_map["BLOCKED_FROM_DECISION_PACKET"].values())
    assert_true("blocked" in blocked_text and "cannot" in blocked_text, "BLOCKED_FROM_DECISION_PACKET must not be actionable")


def test_candidate_packet() -> None:
    run_id = active_run_id()
    rows, _ = assert_columns(OUT_CANDIDATE, {"packet_row_id", "report_rank", "normalized_ticker", "display_name_or_ticker", "research_category", "report_section", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "refreshed_price_certification_status", "refreshed_price_mapping_status", "duplicate_ticker_mapping_flag", "review_ready", "research_decision_category", "research_priority_band", "research_rationale", "required_human_checks", "evidence_summary", "source_contract", "research_only_flag", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed", "blocker_reason"})
    assert_true(len(rows) == 50, f"Candidate packet expected 50 rows, got {len(rows)}")
    rules, _ = read_csv(OUT_RULES)
    defined = {clean(row.get("research_decision_category")) for row in rules}
    counts: dict[str, int] = {}
    upstream, _ = read_csv(CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv")
    upstream_ranks = [clean(row.get("report_rank")) for row in upstream]
    packet_ranks = [clean(row.get("report_rank")) for row in rows]
    assert_true(packet_ranks == upstream_ranks, "Candidate report_rank values/order differ from V20.49 upstream")
    for row in rows:
        counts[clean(row.get("research_decision_category"))] = counts.get(clean(row.get("research_decision_category")), 0) + 1
        assert_true(clean(row.get("v20_47_run_id")) == run_id, "Candidate run_id mismatch")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Candidate research_only_flag must be TRUE")
        for key in ["official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed"]:
            assert_true(clean(row.get(key)) == "FALSE", f"Candidate {key} must be FALSE")
        assert_true(clean(row.get("research_decision_category")) in defined, "Candidate category not defined in rules")
        assert_true("official" not in clean(row.get("research_priority_band")).lower(), "Research priority band implies official status")
    assert_true(counts.get("PRIORITY_REVIEW") == 20, f"Expected PRIORITY_REVIEW=20, got {counts.get('PRIORITY_REVIEW')}")
    assert_true(counts.get("STANDARD_REVIEW") == 30, f"Expected STANDARD_REVIEW=30, got {counts.get('STANDARD_REVIEW')}")


def test_benchmark_packet() -> None:
    run_id = active_run_id()
    rows, _ = assert_columns(OUT_BENCHMARK, {"benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "certification_status", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated", "research_context_summary", "official_trading_allowed", "trading_signal_created", "blocker_reason"})
    assert_true({clean(row.get("benchmark_ticker")) for row in rows} == {"SPY", "QQQ"}, "Benchmark packet must include SPY and QQQ only")
    for row in rows:
        assert_true(clean(row.get("v20_47_run_id")) == run_id, "Benchmark run_id mismatch")
        assert_true(clean(row.get("review_ready")) == "TRUE", "Benchmark review_ready must be TRUE")
        assert_true(clean(row.get("benchmark_context_allowed")) == "TRUE", "Benchmark context must be allowed")
        for key in ["benchmark_return_calculated", "official_trading_allowed", "trading_signal_created"]:
            assert_true(clean(row.get(key)) == "FALSE", f"Benchmark {key} must be FALSE")


def test_factor_packet() -> None:
    rows, _ = assert_columns(OUT_FACTOR, {"factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section", "refreshed_market_context_available", "review_ready", "factor_context_summary", "included_in_official_weight_flag", "dynamic_weighting_mutated", "research_only_flag", "blocker_reason"})
    assert_true(len(rows) == 21, f"Factor packet expected 21 rows, got {len(rows)}")
    for row in rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Factor refreshed context must be TRUE")
        assert_true(clean(row.get("dynamic_weighting_mutated")) == "FALSE", "Factor dynamic weighting mutation must be FALSE")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Factor research_only_flag must be TRUE")
        assert_true(clean(row.get("included_in_official_weight_flag")) == "FALSE", "Factor official weight flag must be FALSE")


def test_entry_packet() -> None:
    rows, _ = assert_columns(OUT_ENTRY, {"strategy_id_or_name", "strategy_family", "readiness_status", "report_section", "refreshed_market_context_available", "review_ready", "entry_strategy_context_summary", "allowed_in_research_report", "allowed_for_live_trading", "broker_execution_enabled", "research_only_flag", "trading_signal_created", "blocker_reason"})
    assert_true(len(rows) == 5, f"Entry packet expected 5 rows, got {len(rows)}")
    for row in rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Entry refreshed context must be TRUE")
        assert_true(clean(row.get("allowed_in_research_report")) == "TRUE", "Entry allowed_in_research_report must be TRUE")
        for key in ["allowed_for_live_trading", "broker_execution_enabled", "trading_signal_created"]:
            assert_true(clean(row.get(key)) == "FALSE", f"Entry {key} must be FALSE")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Entry research_only_flag must be TRUE")


def test_lineage_packet() -> None:
    run_id = active_run_id()
    rows, _ = assert_columns(OUT_LINEAGE, {"source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status", "v20_47_run_id", "v20_47_cache_hash_reference", "refreshed_cache_certified", "review_ready", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading", "lineage_context_summary", "blocker_count", "warning_count", "blocker_reason"})
    assert_true(len(rows) >= 35, f"Lineage packet expected at least 35 rows, got {len(rows)}")
    assert_true(any(clean(row.get("v20_47_cache_hash_reference")) for row in rows), "Lineage must include V20.47 cache hash reference")
    for row in rows:
        assert_true(clean(row.get("v20_47_run_id")) == run_id, "Lineage run_id mismatch")
        assert_true(clean(row.get("refreshed_cache_certified")) == "TRUE", "Lineage refreshed cache certified must be TRUE")
        if not clean(row.get("blocker_reason")):
            assert_true(clean(row.get("safe_for_research_report")) == "TRUE", "Lineage safe_for_research_report must be TRUE without blockers")
        assert_true(clean(row.get("safe_for_official_recommendation")) == "FALSE", "Lineage official recommendation safety must be FALSE")
        assert_true(clean(row.get("safe_for_trading")) == "FALSE", "Lineage trading safety must be FALSE")


def test_manifest() -> None:
    rows, _ = assert_columns(OUT_MANIFEST, {"packet_item", "artifact_path", "artifact_role", "required_flag", "exists_flag", "non_empty_flag", "research_only_flag", "official_recommendation_allowed", "trading_allowed", "validation_status", "blocker_reason"})
    item_map = by_key(rows, "packet_item")
    missing = sorted(MANIFEST_ITEMS - set(item_map))
    assert_true(not missing, f"Missing manifest items: {missing}")
    for row in rows:
        assert_true(clean(row.get("exists_flag")) == "TRUE", f"Manifest item missing: {row.get('packet_item')}")
        assert_true(clean(row.get("non_empty_flag")) == "TRUE", f"Manifest item empty: {row.get('packet_item')}")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Manifest item not PASS: {row.get('packet_item')}")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Manifest research_only_flag must be TRUE")
        assert_true(clean(row.get("official_recommendation_allowed")) == "FALSE", "Manifest official recommendation allowed must be FALSE")
        assert_true(clean(row.get("trading_allowed")) == "FALSE", "Manifest trading allowed must be FALSE")


def test_action_and_safety_boundaries() -> None:
    actions, _ = assert_columns(OUT_ACTION, {"boundary_name", "allowed_flag", "evidence", "blocker_reason"})
    action_map = by_key(actions, "boundary_name")
    assert_true(TRUE_BOUNDARIES <= set(action_map), f"Missing TRUE action boundaries: {sorted(TRUE_BOUNDARIES - set(action_map))}")
    assert_true(FALSE_BOUNDARIES <= set(action_map), f"Missing FALSE action boundaries: {sorted(FALSE_BOUNDARIES - set(action_map))}")
    for key in TRUE_BOUNDARIES:
        assert_true(clean(action_map[key].get("allowed_flag")) == "TRUE", f"Action boundary {key} must be TRUE")
    for key in FALSE_BOUNDARIES:
        assert_true(clean(action_map[key].get("allowed_flag")) == "FALSE", f"Action boundary {key} must be FALSE")
    safety, _ = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    safety_map = by_key(safety, "safety_boundary")
    assert_true(set(SAFETY_CHECKS) <= set(safety_map), f"Missing safety checks: {sorted(set(SAFETY_CHECKS) - set(safety_map))}")
    for key, expected in SAFETY_CHECKS.items():
        row = safety_map[key]
        assert_true(clean(row.get("expected_value")) == expected, f"Safety {key} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"Safety {key} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Safety {key} must be PASS")
        assert_true(not clean(row.get("blocker_reason")), f"Safety {key} has blocker")


def test_next_step() -> None:
    rows, _ = assert_columns(OUT_NEXT, {"stage", "decision", "research_only_decision_packet_created", "research_only_status", "future_official_recommendation_gate_allowed_next", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed", "formal_tests_required_next", "blocker_count", "warning_count", "next_recommended_stage"})
    assert_true(len(rows) == 1, f"Next-step expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "decision": DECISION_PASS,
        "research_only_decision_packet_created": "TRUE",
        "research_only_status": "TRUE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": "0",
        "warning_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("future_official_recommendation_gate_allowed_next")) in {"TRUE", "CONDITIONAL"}, "Future gate flag must be TRUE or CONDITIONAL")
    assert_true(clean(row.get("next_recommended_stage")) in ALLOWED_NEXT_STAGES, f"Unexpected next stage: {row.get('next_recommended_stage')}")


def test_read_center_and_alias() -> None:
    run_id = active_run_id()
    report = REPORT.read_text(encoding="utf-8")
    lowered = report.lower()
    required_phrases = [
        "v20.50_research_only_decision_packet",
        "decision packet status",
        "pass_research_only_decision_packet_created",
        "v20.49",
        "operator review",
        "v20.48",
        "refreshed report",
        run_id.lower(),
        "cache reference",
        "no provider/network refresh",
        "does not import yfinance",
        "not an official recommendation",
        "no trading signals",
        "no broker/order execution",
        "does not recompute scores",
        "does not recompute rankings",
        "does not calculate benchmark-relative returns",
        "research-only status",
        "candidate research decision packet summary",
        "benchmark research context",
        "factor research context",
        "entry strategy research context",
        "lineage/freshness context",
        "research decision category definitions",
        "next recommended stage",
    ]
    for phrase in required_phrases:
        assert_true(phrase in lowered, f"Report missing phrase: {phrase}")
    alias = CURRENT_REPORT.read_text(encoding="utf-8")
    alias_lower = alias.lower()
    assert_true("v20.50_research_only_decision_packet" in alias_lower, "Current alias does not correspond to V20.50")
    assert_true("research-only decision packet" in alias_lower, "Current alias missing research-only decision packet")
    assert_true("official trading allowed" not in alias_lower, "Current alias claims official trading readiness")
    assert_true("official recommendation readiness" not in alias_lower, "Current alias claims official recommendation readiness")


def test_read_first() -> None:
    run_id = active_run_id()
    flags = read_flags(READ_FIRST)
    expected = {
        "STAGE_NAME": STAGE,
        "RESEARCH_ONLY_DECISION_PACKET_STATUS": DECISION_PASS,
        "V20_49_OPERATOR_REVIEW_PACKAGE_USED": "TRUE",
        "V20_48_REFRESHED_REPORT_USED": "TRUE",
        "V20_47_RUN_ID": run_id,
        "V20_47_CACHE_REFERENCE_USED": "TRUE",
        "REPORT_PACKET_ONLY_SAFETY_FLAGS": "TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_50": "FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_50": "FALSE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "RETURNS_CALCULATED": "FALSE",
        "SCORES_RECOMPUTED": "FALSE",
        "RANKINGS_RECOMPUTED": "FALSE",
        "TRADING_SIGNALS_CREATED": "FALSE",
        "RESEARCH_ONLY_STATUS": "TRUE",
    }
    for key, value in expected.items():
        assert_true(flags.get(key) == value, f"READ_FIRST {key} expected {value}, got {flags.get(key)}")
    assert_true(flags.get("NEXT_RECOMMENDED_STAGE") in ALLOWED_NEXT_STAGES, f"Unexpected READ_FIRST next stage: {flags.get('NEXT_RECOMMENDED_STAGE')}")


def test_forbidden_language() -> None:
    candidate_text = OUT_CANDIDATE.read_text(encoding="utf-8")
    report_text = REPORT.read_text(encoding="utf-8")
    alias_text = CURRENT_REPORT.read_text(encoding="utf-8")
    read_first_text = READ_FIRST.read_text(encoding="utf-8")
    hits = forbidden_actionable_hits("\n".join([candidate_text, report_text, alias_text, read_first_text]))
    assert_true(not hits, f"Forbidden actionable language found: {hits[:5]}")


def test_static_safety_scans() -> None:
    assert_no_executable_safety_patterns()


def test_no_v21_or_v19_21_outputs() -> None:
    forbidden_paths = [ROOT / "outputs" / "v21", ROOT / "outputs" / "v19_21", ROOT / "outputs" / "v19" / "V19_21"]
    existing = [str(path) for path in forbidden_paths if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")


def main() -> int:
    tests = [
        test_required_outputs_exist_and_non_empty,
        test_summary,
        test_upstream_validation,
        test_category_rules,
        test_candidate_packet,
        test_benchmark_packet,
        test_factor_packet,
        test_entry_packet,
        test_lineage_packet,
        test_manifest,
        test_action_and_safety_boundaries,
        test_next_step,
        test_read_center_and_alias,
        test_read_first,
        test_forbidden_language,
        test_static_safety_scans,
        test_no_v21_or_v19_21_outputs,
    ]
    failures: list[str] = []
    try:
        for test in tests:
            try:
                test()
            except Exception as exc:
                failures.append(f"{test.__name__}: {exc}")
    finally:
        remove_pycache()
    remaining_pycache = pycache_paths()
    if remaining_pycache:
        failures.append(f"pycache remains under scripts/v20: {[str(path) for path in remaining_pycache]}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(FAIL_STATUS)
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
