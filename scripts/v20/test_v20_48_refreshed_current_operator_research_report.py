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

PASS_STATUS = "PASS_V20_48_TESTS"
STAGE = "V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
RUN_ID_PATTERN = re.compile(r"V20_47_\d{8}T\d{6}Z")
NEXT_STAGE = "V20.48_FORMAL_TESTS"
REVIEW_GATE_STAGE = "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
CERT_STATUS = "CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF"

OUT_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
OUT_FACTOR = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
OUT_ENTRY = CONSOLIDATION / "V20_48_REFRESHED_ENTRY_STRATEGY_VIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_48_REFRESHED_REPORT_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_48_REFRESHED_REPORT_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_48_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_REFRESHED_OPERATOR_RESEARCH_REPORT.md"
READ_FIRST = OPS / "V20_48_READ_FIRST.txt"

IN_V47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_CACHE_HASH_LEDGER = CONSOLIDATION / "V20_47_CACHE_HASH_LEDGER.csv"
IN_V47_STAGED_CANDIDATE = CONSOLIDATION / "V20_47_CURRENT_MARKET_SOURCE_STAGED_CANDIDATE.csv"
IN_V47_STAGED_BENCHMARK = CONSOLIDATION / "V20_47_CURRENT_BENCHMARK_SOURCE_STAGED_CANDIDATE.csv"
IN_V47_NEXT = CONSOLIDATION / "V20_47_NEXT_STEP_DECISION.csv"
IN_V47_TEST = SCRIPT_DIR / "test_v20_47_controlled_current_market_refresh_and_cache_certification.py"
IN_V45_CANDIDATE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv"
IN_V45_FACTOR = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv"
IN_V45_ENTRY = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ENTRY_STRATEGY_VIEW.csv"
IN_V45_LINEAGE = CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv"

REQUIRED_FILES = [
    OUT_SUMMARY,
    OUT_CANDIDATE,
    OUT_BENCHMARK,
    OUT_FACTOR,
    OUT_ENTRY,
    OUT_LINEAGE,
    OUT_BOUNDARY,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_47_certification_status",
    "upstream_v20_47_tests_status",
    "v20_47_run_id",
    "refreshed_market_cache_used",
    "provider_refresh_executed_in_this_stage",
    "yfinance_import_used_in_this_stage",
    "candidate_research_rows_input",
    "unique_certified_candidate_tickers_available",
    "candidate_research_rows_with_refreshed_price",
    "candidate_research_rows_missing_refreshed_price",
    "benchmark_rows_available",
    "factor_support_rows_included",
    "entry_strategy_rows_included",
    "lineage_rows_included",
    "refreshed_report_created",
    "research_only_status",
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
    "next_recommended_stage",
}

CANDIDATE_COLUMNS = {
    "report_rank",
    "ticker_or_candidate_id",
    "normalized_ticker",
    "display_name_or_ticker",
    "source_rank_or_score",
    "research_category",
    "report_section",
    "source_contract",
    "source_lineage",
    "v20_47_run_id",
    "refreshed_price_date",
    "refreshed_latest_close",
    "refreshed_latest_adj_close",
    "refreshed_latest_volume",
    "refreshed_price_certification_status",
    "refreshed_price_mapping_status",
    "duplicate_ticker_mapping_flag",
    "research_only_flag",
    "official_recommendation_flag",
    "official_trading_allowed",
    "broker_execution_allowed",
    "operator_research_note",
}

BENCHMARK_COLUMNS = {
    "benchmark_ticker",
    "v20_47_run_id",
    "refreshed_price_date",
    "refreshed_latest_close",
    "refreshed_latest_adj_close",
    "refreshed_latest_volume",
    "certification_status",
    "research_context_allowed",
    "benchmark_return_calculated",
    "official_trading_allowed",
    "blocker_reason",
}

FACTOR_COLUMNS = {
    "factor_id_or_name",
    "factor_category",
    "pit_status",
    "support_status",
    "report_section",
    "factor_research_interpretation",
    "refreshed_market_context_available",
    "included_in_official_weight_flag",
    "dynamic_weighting_mutated",
    "research_only_flag",
}

ENTRY_COLUMNS = {
    "strategy_id_or_name",
    "strategy_family",
    "readiness_status",
    "report_section",
    "entry_strategy_interpretation",
    "refreshed_market_context_available",
    "allowed_in_research_report",
    "allowed_for_live_trading",
    "broker_execution_enabled",
    "research_only_flag",
}

LINEAGE_COLUMNS = {
    "source_name_or_input_name",
    "source_contract_or_version",
    "freshness_status",
    "lineage_status",
    "v20_47_run_id",
    "v20_47_cache_hash_reference",
    "refreshed_cache_certified",
    "blocker_count",
    "warning_count",
    "safe_for_research_report",
    "safe_for_official_recommendation",
    "safe_for_trading",
}

TRUE_BOUNDARIES = {
    "refreshed_research_report_generation_allowed",
    "candidate_review_with_refreshed_prices_allowed",
    "factor_review_with_refreshed_context_allowed",
    "entry_strategy_review_with_refreshed_context_allowed",
    "benchmark_context_review_allowed",
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
    "provider_refresh_executed_in_v20_48": "FALSE",
    "yfinance_imported_in_v20_48": "FALSE",
    "refreshed_v20_47_cache_used": "TRUE",
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

RUN_ID_COLUMNS = [
    "run_id",
    "upstream_run_id",
    "v20_47_run_id",
    "current_market_refresh_run_id",
    "cache_run_id",
    "refresh_run_id",
    "source_run_id",
    "lineage_run_id",
]


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return str(value or "").strip()


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


def v20_48_run_ids_by_artifact() -> dict[Path, set[str]]:
    artifacts = [OUT_SUMMARY, OUT_CANDIDATE, OUT_BENCHMARK, OUT_LINEAGE]
    found: dict[Path, set[str]] = {}
    for path in artifacts:
        rows, columns = read_csv(path)
        found[path] = run_ids_from_rows(rows, columns)
    return found


def discover_active_v20_47_run_id() -> str:
    by_artifact = v20_48_run_ids_by_artifact()
    missing = [path.name for path, ids in by_artifact.items() if not ids]
    assert_true(not missing, f"No V20.47 run_id discovered from V20.48 outputs: {missing}")
    all_ids = set().union(*by_artifact.values())
    assert_true(len(all_ids) == 1, f"V20.48 outputs reference inconsistent V20.47 run_ids: {by_artifact}")
    run_id = next(iter(all_ids))
    assert_true(valid_v20_47_run_id(run_id), f"Invalid discovered V20.47 run_id format: {run_id}")
    return run_id


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
    assert_true(not missing, f"Missing required V20.48 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty required V20.48 outputs: {empty}")


def test_summary() -> None:
    rows, _ = assert_columns(OUT_SUMMARY, SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    run_id = discover_active_v20_47_run_id()
    expected = {
        "stage": STAGE,
        "upstream_v20_47_certification_status": CERT_STATUS,
        "upstream_v20_47_tests_status": "PASS",
        "refreshed_market_cache_used": "TRUE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "candidate_research_rows_input": "50",
        "unique_certified_candidate_tickers_available": "40",
        "candidate_research_rows_with_refreshed_price": "50",
        "candidate_research_rows_missing_refreshed_price": "0",
        "benchmark_rows_available": "2",
        "factor_support_rows_included": "21",
        "entry_strategy_rows_included": "5",
        "lineage_rows_included": "27",
        "refreshed_report_created": "TRUE",
        "research_only_status": "TRUE",
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
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("v20_47_run_id")) == run_id, f"Summary v20_47_run_id expected active run_id {run_id}, got {row.get('v20_47_run_id')}")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, REVIEW_GATE_STAGE}, "Unexpected next recommended stage")


def test_v20_47_run_id_handoff() -> None:
    run_id = discover_active_v20_47_run_id()
    assert_run_id_exists_in_v20_47_artifacts(run_id)
    for path, column in [
        (OUT_SUMMARY, "v20_47_run_id"),
        (OUT_CANDIDATE, "v20_47_run_id"),
        (OUT_BENCHMARK, "v20_47_run_id"),
        (OUT_LINEAGE, "v20_47_run_id"),
    ]:
        rows, _ = read_csv(path)
        values = {clean(row.get(column)) for row in rows if clean(row.get(column))}
        assert_true(values == {run_id}, f"{path.name} run_id mismatch: {values}")
    lineage_rows, _ = read_csv(OUT_LINEAGE)
    assert_true(any(clean(row.get("v20_47_cache_hash_reference")) for row in lineage_rows), "Lineage lacks V20.47 cache/hash references")


def test_refreshed_candidate_view() -> None:
    run_id = discover_active_v20_47_run_id()
    rows, columns = assert_columns(OUT_CANDIDATE, CANDIDATE_COLUMNS)
    assert_true(len(rows) == 50, f"Candidate view expected 50 rows, got {len(rows)}")
    assert_true(len({clean(row.get("normalized_ticker")) for row in rows}) == 40, "Expected 40 unique normalized tickers")
    assert_true(any(clean(row.get("duplicate_ticker_mapping_flag")) == "TRUE" for row in rows), "Duplicate ticker mapping flag never TRUE despite 50 rows/40 tickers")
    forbidden_cols = [column for column in columns if "recomputed" in column.lower() or "new_score" in column.lower() or "new_rank" in column.lower()]
    assert_true(not forbidden_cols, f"Candidate view has recomputation columns: {forbidden_cols}")
    for idx, row in enumerate(rows, start=1):
        assert_true(clean(row.get("v20_47_run_id")) == run_id, f"Candidate row {idx} run_id mismatch")
        assert_true(clean(row.get("refreshed_price_date")), f"Candidate row {idx} missing price date")
        assert_true(clean(row.get("refreshed_latest_close")) or clean(row.get("refreshed_latest_adj_close")), f"Candidate row {idx} missing close-compatible price")
        assert_true(clean(row.get("refreshed_price_certification_status")) in {"CERTIFIED", CERT_STATUS, "PASS"}, f"Candidate row {idx} not certified")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", f"Candidate row {idx} research_only_flag not TRUE")
        assert_true(clean(row.get("official_recommendation_flag")) == "FALSE", f"Candidate row {idx} recommendation flag not FALSE")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", f"Candidate row {idx} trading allowed")
        assert_true(clean(row.get("broker_execution_allowed")) == "FALSE", f"Candidate row {idx} broker execution allowed")
    assert_no_recommendation_language(rows, "candidate")


def test_benchmark_context() -> None:
    run_id = discover_active_v20_47_run_id()
    rows, columns = assert_columns(OUT_BENCHMARK, BENCHMARK_COLUMNS)
    by_ticker = by_key(rows, "benchmark_ticker")
    assert_true({"SPY", "QQQ"} <= set(by_ticker), "Benchmark context missing SPY or QQQ")
    return_cols = [column for column in columns if "return" in column.lower() and column != "benchmark_return_calculated"]
    assert_true(not return_cols, f"Benchmark context has return calculation columns: {return_cols}")
    for ticker in ["SPY", "QQQ"]:
        row = by_ticker[ticker]
        assert_true(clean(row.get("v20_47_run_id")) == run_id, f"{ticker} run_id mismatch")
        assert_true(clean(row.get("certification_status")) in {"CERTIFIED", CERT_STATUS, "PASS"}, f"{ticker} not certified")
        assert_true(clean(row.get("research_context_allowed")) == "TRUE", f"{ticker} research context not allowed")
        assert_true(clean(row.get("benchmark_return_calculated")) == "FALSE", f"{ticker} benchmark return calculated")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", f"{ticker} trading allowed")
        assert_true(clean(row.get("refreshed_price_date")), f"{ticker} missing price date")
        assert_true(clean(row.get("refreshed_latest_close")) or clean(row.get("refreshed_latest_adj_close")), f"{ticker} missing price")


def test_factor_entry_lineage() -> None:
    factor_rows, _ = assert_columns(OUT_FACTOR, FACTOR_COLUMNS)
    assert_true(len(factor_rows) == 21, f"Factor rows expected 21, got {len(factor_rows)}")
    for row in factor_rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Factor refreshed context not TRUE")
        assert_true(clean(row.get("dynamic_weighting_mutated")) == "FALSE", "Factor dynamic weighting mutated")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Factor research_only_flag not TRUE")
        assert_true(clean(row.get("included_in_official_weight_flag")) == "FALSE", "Factor included in official weights")

    entry_rows, _ = assert_columns(OUT_ENTRY, ENTRY_COLUMNS)
    assert_true(len(entry_rows) == 5, f"Entry rows expected 5, got {len(entry_rows)}")
    for row in entry_rows:
        assert_true(clean(row.get("refreshed_market_context_available")) == "TRUE", "Entry refreshed context not TRUE")
        assert_true(clean(row.get("allowed_in_research_report")) == "TRUE", "Entry not allowed in research report")
        assert_true(clean(row.get("allowed_for_live_trading")) == "FALSE", "Entry live trading allowed")
        assert_true(clean(row.get("broker_execution_enabled")) == "FALSE", "Entry broker execution enabled")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", "Entry research_only_flag not TRUE")

    lineage_rows, _ = assert_columns(OUT_LINEAGE, LINEAGE_COLUMNS)
    assert_true(len(lineage_rows) >= 27, f"Lineage expected at least 27 rows, got {len(lineage_rows)}")
    assert_true(any("V20_47" in clean(row.get("freshness_status")) or clean(row.get("refreshed_cache_certified")) == "TRUE" for row in lineage_rows), "Lineage lacks V20.47 cache/certification rows")
    for row in lineage_rows:
        if as_int(row.get("blocker_count")) == 0:
            assert_true(clean(row.get("safe_for_research_report")) == "TRUE", "Lineage safe_for_research_report not TRUE with zero blockers")
        assert_true(clean(row.get("safe_for_official_recommendation")) == "FALSE", "Lineage official recommendation safe")
        assert_true(clean(row.get("safe_for_trading")) == "FALSE", "Lineage trading safe")


def test_action_boundary() -> None:
    rows, _ = assert_columns(OUT_BOUNDARY, {"boundary_name", "allowed_flag", "evidence", "blocker_reason"})
    boundary = by_key(rows, "boundary_name")
    missing = sorted((TRUE_BOUNDARIES | FALSE_BOUNDARIES) - set(boundary))
    assert_true(not missing, f"Action boundary missing rows: {missing}")
    for name in TRUE_BOUNDARIES:
        assert_true(clean(boundary[name].get("allowed_flag")) == "TRUE", f"{name} expected TRUE")
    for name in FALSE_BOUNDARIES:
        assert_true(clean(boundary[name].get("allowed_flag")) == "FALSE", f"{name} expected FALSE")


def test_safety_boundary() -> None:
    rows, _ = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    safety = by_key(rows, "safety_boundary")
    missing = sorted(set(SAFETY_CHECKS) - set(safety))
    assert_true(not missing, f"Safety boundary missing rows: {missing}")
    for name, expected in SAFETY_CHECKS.items():
        row = safety[name]
        assert_true(clean(row.get("expected_value")) == expected, f"{name} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"{name} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not pass")


def test_next_step_decision() -> None:
    rows, _ = assert_columns(OUT_NEXT, {
        "stage",
        "decision",
        "refreshed_report_created",
        "refreshed_cache_certified",
        "research_report_ready",
        "official_recommendation_allowed",
        "official_trading_allowed",
        "broker_execution_allowed",
        "formal_tests_required_next",
        "blocker_count",
        "warning_count",
        "next_recommended_stage",
    })
    assert_true(len(rows) == 1, f"Next-step expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "decision": "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED",
        "refreshed_report_created": "TRUE",
        "refreshed_cache_certified": "TRUE",
        "research_report_ready": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": "0",
        "warning_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, REVIEW_GATE_STAGE}, "Unexpected next recommended stage")


def test_reports_and_read_first() -> None:
    run_id = discover_active_v20_47_run_id()
    text = REPORT.read_text(encoding="utf-8")
    lower = text.lower()
    required = [
        "v20.48",
        "certified v20.47 refreshed market cache",
        "does not perform provider/network refresh",
        "does not use yfinance",
        "not an official recommendation",
        "not trading-authorized",
        "no broker/order execution",
        "no forward returns",
        "no benchmark-relative returns",
        "no scores",
        "no rankings",
        "candidate research view",
        "benchmark context",
        "factor support",
        "entry strategy",
        "lineage/freshness",
        "next recommended stage",
    ]
    for phrase in required:
        assert_true(phrase in lower, f"Report missing phrase: {phrase}")
    assert_true(not re.search(r"\bofficial\s+(buy|sell|hold)\b|\b(buy|sell|hold)\s+recommendation\b", lower), "Report contains official buy/sell/hold language")

    alias = CURRENT_REPORT.read_text(encoding="utf-8")
    alias_lower = alias.lower()
    assert_true(STAGE in alias, "Current alias does not correspond to V20.48")
    assert_true("refreshed" in alias_lower and "research report" in alias_lower, "Alias missing refreshed report language")
    assert_true("research-only" in alias_lower, "Alias missing research-only language")
    assert_true("ready for official trading" not in alias_lower, "Alias claims official trading readiness")
    assert_true("ready for official recommendation" not in alias_lower, "Alias claims official recommendation readiness")

    flags = read_flags(READ_FIRST)
    expected = {
        "STAGE_NAME": STAGE,
        "REFRESHED_V20_47_CACHE_USED": "TRUE",
        "V20_47_RUN_ID": run_id,
        "REPORT_GENERATION_ONLY": "TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_48": "FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_48": "FALSE",
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
    production = SCRIPT_DIR / "v20_48_refreshed_current_operator_research_report.py"
    wrapper = SCRIPT_DIR / "run_v20_48_refreshed_current_operator_research_report.ps1"
    test_script = SCRIPT_DIR / "test_v20_48_refreshed_current_operator_research_report.py"
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
        test_summary,
        test_v20_47_run_id_handoff,
        test_refreshed_candidate_view,
        test_benchmark_context,
        test_factor_entry_lineage,
        test_action_boundary,
        test_safety_boundary,
        test_next_step_decision,
        test_reports_and_read_first,
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
        print("FAIL_V20_48_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
