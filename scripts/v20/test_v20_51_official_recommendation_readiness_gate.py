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

PASS_STATUS = "PASS_V20_51_TESTS"
FAIL_STATUS = "FAIL_V20_51_TESTS"
STAGE = "V20.51_OFFICIAL_RECOMMENDATION_READINESS_GATE"
RUN_ID = "V20_47_20260604T114058Z"
V20_50_PASS = "PASS_RESEARCH_ONLY_DECISION_PACKET_CREATED"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_READINESS_GATE_CREATED"
ALLOWED_NEXT_STAGES = {"V20.51_FORMAL_TESTS", "V20.52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"}

PROD_SCRIPT = SCRIPT_DIR / "v20_51_official_recommendation_readiness_gate.py"
WRAPPER = SCRIPT_DIR / "run_v20_51_official_recommendation_readiness_gate.ps1"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_51_official_recommendation_readiness_gate.py"

OUT_SUMMARY = CONSOLIDATION / "V20_51_OFFICIAL_RECOMMENDATION_READINESS_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_51_UPSTREAM_V20_50_VALIDATION.csv"
OUT_PREREQ = CONSOLIDATION / "V20_51_RECOMMENDATION_GATE_PREREQUISITE_REVIEW.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_51_CANDIDATE_READINESS_FOR_FUTURE_OFFICIAL_GATE.csv"
OUT_CONTEXT = CONSOLIDATION / "V20_51_CONTEXT_READINESS_FOR_FUTURE_OFFICIAL_GATE.csv"
OUT_GAPS = CONSOLIDATION / "V20_51_OFFICIAL_GATE_POLICY_GAP_REGISTER.csv"
OUT_ACTION = CONSOLIDATION / "V20_51_GATE_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_51_GATE_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_51_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_READINESS_GATE.md"
READ_FIRST = OPS / "V20_51_READ_FIRST.txt"

REQUIRED_FILES = [
    OUT_SUMMARY,
    OUT_UPSTREAM,
    OUT_PREREQ,
    OUT_CANDIDATE,
    OUT_CONTEXT,
    OUT_GAPS,
    OUT_ACTION,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_50_packet_status",
    "upstream_v20_50_tests_status",
    "v20_47_run_id",
    "research_only_packet_used",
    "candidate_rows_reviewed",
    "benchmark_rows_reviewed",
    "factor_rows_reviewed",
    "entry_strategy_rows_reviewed",
    "lineage_rows_reviewed",
    "priority_review_rows",
    "standard_review_rows",
    "official_recommendation_created",
    "official_recommendation_allowed_in_this_stage",
    "official_trading_allowed",
    "broker_order_execution_used",
    "provider_refresh_executed_in_this_stage",
    "yfinance_import_used_in_this_stage",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "returns_calculated",
    "benchmark_relative_returns_calculated",
    "scores_recomputed",
    "rankings_recomputed",
    "trading_signals_created",
    "future_official_recommendation_gate_ready",
    "readiness_status",
    "blocker_count",
    "warning_count",
    "next_recommended_stage",
}

UPSTREAM_ITEMS = {
    "v20_50_summary_exists_non_empty",
    "v20_50_upstream_validation_exists_non_empty",
    "v20_50_category_rules_exists_non_empty",
    "v20_50_candidate_packet_exists_non_empty",
    "v20_50_benchmark_packet_exists_non_empty",
    "v20_50_factor_packet_exists_non_empty",
    "v20_50_entry_packet_exists_non_empty",
    "v20_50_lineage_packet_exists_non_empty",
    "v20_50_manifest_exists_non_empty",
    "v20_50_action_boundary_exists_non_empty",
    "v20_50_safety_boundary_exists_non_empty",
    "v20_50_next_step_decision_exists_non_empty",
    "v20_50_read_center_report_exists_non_empty",
    "v20_50_current_alias_exists_non_empty",
    "v20_50_read_first_exists_non_empty",
    "v20_50_formal_test_script_exists",
    "v20_50_packet_status",
    "v20_50_tests_status",
    "v20_50_candidate_count",
    "v20_50_benchmark_count",
    "v20_50_factor_count",
    "v20_50_entry_count",
    "v20_50_lineage_count",
    "v20_50_priority_review_count",
    "v20_50_standard_review_count",
    "v20_50_official_recommendation_allowed",
    "v20_50_official_trading_allowed",
    "v20_50_broker_order_execution_used",
    "v20_50_provider_refresh_executed_in_this_stage",
    "v20_50_yfinance_import_used_in_this_stage",
    "v20_50_official_ranking_mutated",
    "v20_50_dynamic_weighting_mutated",
    "v20_50_returns_calculated",
    "v20_50_scores_recomputed",
    "v20_50_rankings_recomputed",
    "v20_50_trading_signals_created",
    "v20_50_forbidden_actionable_language_scan",
}

PREREQ_NAMES = {
    "accepted research-only decision packet",
    "V20.50 formal tests passed",
    "certified current market cache reference",
    "refreshed candidate price context",
    "benchmark context present",
    "factor context present",
    "entry strategy context present",
    "lineage/freshness context present",
    "action boundary present",
    "safety boundary present",
    "forbidden language scan passed",
    "no broker/order path",
    "no official recommendation generated yet",
    "no trading signal generated yet",
    "no official ranking mutation",
    "no dynamic weighting mutation",
    "future official recommendation policy still required",
    "future official recommendation tests required",
}

TRUE_BOUNDARIES = {
    "official_recommendation_readiness_assessment_allowed",
    "future_official_gate_preparation_allowed",
    "prerequisite_review_allowed",
    "policy_gap_register_allowed",
    "candidate_future_gate_readiness_allowed",
}

FALSE_BOUNDARIES = {
    "official_recommendation_generation_allowed_in_this_stage",
    "official_buy_sell_hold_recommendation_allowed",
    "live_trading_allowed",
    "broker_order_execution_allowed",
    "provider_refresh_allowed_in_this_stage",
    "yfinance_import_allowed_in_this_stage",
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
    "provider_refresh_executed_in_v20_51": "FALSE",
    "yfinance_imported_in_v20_51": "FALSE",
    "v20_50_research_only_packet_used": "TRUE",
    "v20_49_operator_review_package_used": "TRUE",
    "v20_47_certified_cache_reference_used": "TRUE",
    "broker_order_execution_used": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_recommendation_allowed_in_this_stage": "FALSE",
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

GAP_NAMES = {
    "official recommendation policy contract",
    "official output schema contract",
    "recommendation language policy",
    "position/risk cap policy binding",
    "user/manual approval policy",
    "real-book separation confirmation",
    "broker-disabled enforcement",
    "post-recommendation audit tests",
    "final human review or explicit gate acceptance",
}


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


def remove_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def pycache_paths() -> list[Path]:
    return [path for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]


def tokenized_text(path: Path) -> str:
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
            assert_true(all(alias.name != "yfinance" for alias in node.names), f"{path.name} imports yfinance")
        elif isinstance(node, ast.ImportFrom):
            assert_true(node.module != "yfinance", f"{path.name} imports from yfinance")


def assert_no_executable_safety_patterns() -> None:
    assert_no_import_yfinance(PROD_SCRIPT)
    assert_no_import_yfinance(TEST_SCRIPT)
    stage_code = tokenized_text(PROD_SCRIPT) + " " + tokenized_text(TEST_SCRIPT)
    forbidden = [
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
        r"outputs\\v19\\V19_21",
        r"outputs\\v19_21",
    ]
    for pattern in forbidden:
        assert_true(not re.search(pattern, stage_code, re.IGNORECASE), f"Executable safety pattern found: {pattern}")
    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    wrapper_forbidden = ["import yfinance", "from yfinance", "submit_order", "place_order", "alpaca", "ib_insync", "ccxt", "outputs/v21", "outputs\\v21", "outputs/v19_21", "outputs\\v19_21", "outputs/v19/v19_21", "outputs\\v19\\v19_21"]
    for pattern in wrapper_forbidden:
        assert_true(pattern not in wrapper_text, f"Wrapper safety pattern found: {pattern}")


def negation_filtered_text(text: str) -> str:
    lowered = text.lower()
    substitutions = [
        r"not a buy signal",
        r"no buy/sell/hold recommendation",
        r"no buy/sell/hold instruction",
        r"official buy/sell/hold/trading signal statement",
        r"explicit no buy/sell/hold/trading signal statement",
        r"official buy/sell/hold instruction",
        r"not trading-authorized",
        r"no broker/order execution",
        r"does not perform broker/order execution",
        r"no trading signal",
        r"creates no trading signal",
        r"creates no trading signals",
        r"no official recommendation",
        r"no official recommendations",
        r"does not import yfinance",
        r"no provider/network refresh",
        r"does not connect to broker/order APIs",
        r"does not permit official recommendation generation",
        r"recomputes no scores",
        r"recomputes no rankings",
        r"calculates no forward returns",
        r"calculates no benchmark-relative returns",
        r"does not mutate official rankings",
        r"does not mutate dynamic weights",
    ]
    for pattern in substitutions:
        lowered = re.sub(pattern, "", lowered, flags=re.IGNORECASE)
    return lowered


def forbidden_language_hits(text: str) -> list[str]:
    filtered = negation_filtered_text(text)
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
    hits: list[str] = []
    for pattern in forbidden:
        for match in re.finditer(pattern, filtered, flags=re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(filtered), match.end() + 35)
            hits.append(filtered[start:end].replace("\n", " "))
    return hits


def test_required_outputs_exist_and_non_empty() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing V20.51 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty V20.51 outputs: {empty}")


def test_summary() -> None:
    rows, _ = assert_columns(OUT_SUMMARY, SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "upstream_v20_50_packet_status": V20_50_PASS,
        "upstream_v20_50_tests_status": "PASS",
        "v20_47_run_id": RUN_ID,
        "research_only_packet_used": "TRUE",
        "candidate_rows_reviewed": "50",
        "benchmark_rows_reviewed": "2",
        "factor_rows_reviewed": "21",
        "entry_strategy_rows_reviewed": "5",
        "lineage_rows_reviewed": "35",
        "priority_review_rows": "20",
        "standard_review_rows": "30",
        "official_recommendation_created": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "benchmark_relative_returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "trading_signals_created": "FALSE",
        "blocker_count": "0",
        "warning_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {clean(row.get(key))}")
    assert_true(clean(row.get("future_official_recommendation_gate_ready")) in {"CONDITIONAL", "TRUE"}, "Summary future gate readiness must be CONDITIONAL or TRUE")
    assert_true(clean(row.get("readiness_status")) in {"READY_WITH_RESEARCH_ONLY_LIMITS", "READY_FOR_FUTURE_OFFICIAL_RECOMMENDATION_GATE"}, "Summary readiness status unexpected")
    assert_true(clean(row.get("next_recommended_stage")) in ALLOWED_NEXT_STAGES, f"Summary next stage unexpected: {row.get('next_recommended_stage')}")


def test_upstream_validation() -> None:
    rows, _ = assert_columns(OUT_UPSTREAM, {"validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    item_map = by_key(rows, "validation_item")
    missing = sorted(UPSTREAM_ITEMS - set(item_map))
    assert_true(not missing, f"Missing V20.50 upstream validation items: {missing}")
    assert_true(len(rows) == 39, f"Upstream validation expected 39 rows, got {len(rows)}")
    blocked = [row for row in rows if clean(row.get("validation_status")) != "PASS" or clean(row.get("blocker_reason"))]
    assert_true(not blocked, f"Upstream validation has blocked rows: {blocked[:3]}")


def test_prereq_review() -> None:
    rows, _ = assert_columns(OUT_PREREQ, {"prerequisite_id", "prerequisite_name", "required_for_future_official_gate", "source_evidence", "prerequisite_status", "blocker_if_missing", "notes"})
    name_map = by_key(rows, "prerequisite_name")
    missing = sorted(PREREQ_NAMES - set(name_map))
    assert_true(not missing, f"Missing prerequisite rows: {missing}")
    assert_true(len(rows) == 18, f"Prerequisite review expected 18 rows, got {len(rows)}")
    for row in rows:
        name = clean(row.get("prerequisite_name"))
        status = clean(row.get("prerequisite_status"))
        assert_true(clean(row.get("required_for_future_official_gate")) == "TRUE", f"Prerequisite {name} must be required")
        if name.startswith("future official recommendation"):
            assert_true(status in {"PENDING_NEXT", "REQUIRED_NEXT"}, f"Future policy prerequisite should be pending, got {status}")
            assert_true(not clean(row.get("blocker_if_missing")), f"Future policy prerequisite should not block V20.51, got blocker {row.get('blocker_if_missing')}")
        else:
            assert_true(status == "PASS", f"Prerequisite {name} expected PASS, got {status}")
            assert_true(not clean(row.get("blocker_if_missing")), f"Prerequisite {name} unexpectedly blocked")


def test_candidate_readiness() -> None:
    rows, _ = assert_columns(OUT_CANDIDATE, {"packet_row_id", "report_rank", "normalized_ticker", "display_name_or_ticker", "v20_47_run_id", "research_decision_category", "research_priority_band", "refreshed_price_certification_status", "review_ready", "future_official_gate_candidate_ready", "official_recommendation_created", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed", "required_future_checks", "blocker_reason"})
    assert_true(len(rows) == 50, f"Candidate readiness expected 50 rows, got {len(rows)}")
    counts = {}
    for row in rows:
        cat = clean(row.get("research_decision_category"))
        counts[cat] = counts.get(cat, 0) + 1
        assert_true(clean(row.get("v20_47_run_id")) == RUN_ID, "Candidate run_id mismatch")
        assert_true(clean(row.get("official_recommendation_created")) == "FALSE", "Candidate created official recommendation")
        for key in ["official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed"]:
            assert_true(clean(row.get(key)) == "FALSE", f"Candidate {key} must be FALSE")
        if clean(row.get("blocker_reason")):
            assert_true(clean(row.get("future_official_gate_candidate_ready")) == "FALSE", "Blocked candidate cannot be ready")
        else:
            assert_true(clean(row.get("future_official_gate_candidate_ready")) == "TRUE", "Unblocked candidate must be ready")
        assert_true(clean(row.get("research_priority_band")).startswith("PRESERVED_REPORT_ORDER_"), "Research priority band must preserve report order")
    assert_true(counts.get("PRIORITY_REVIEW") == 20, f"Expected PRIORITY_REVIEW=20, got {counts.get('PRIORITY_REVIEW')}")
    assert_true(counts.get("STANDARD_REVIEW") == 30, f"Expected STANDARD_REVIEW=30, got {counts.get('STANDARD_REVIEW')}")
    assert_true(counts.get("WATCH_CONTEXT", 0) == 0, "Unexpected WATCH_CONTEXT rows in accepted V20.51 run")


def test_context_readiness() -> None:
    rows, _ = assert_columns(OUT_CONTEXT, {"context_type", "context_name", "source_stage", "row_count_or_status", "future_official_gate_context_ready", "official_recommendation_created", "official_trading_allowed", "mutation_allowed", "blocker_reason"})
    assert_true(len(rows) == 6, f"Context readiness expected 6 rows, got {len(rows)}")
    context_types = {clean(row.get("context_type")) for row in rows}
    assert_true(context_types == {"benchmark_context", "factor_context", "entry_strategy_context", "lineage_context", "action_boundary", "safety_boundary"}, f"Unexpected context types: {context_types}")
    for row in rows:
        assert_true(clean(row.get("future_official_gate_context_ready")) == "TRUE", f"Context {row.get('context_type')} not ready")
        assert_true(clean(row.get("official_recommendation_created")) == "FALSE", "Context created official recommendation")
        assert_true(clean(row.get("official_trading_allowed")) == "FALSE", "Context allowed trading")
        assert_true(clean(row.get("mutation_allowed")) == "FALSE", "Context allowed mutation")


def test_policy_gap_register() -> None:
    rows, _ = assert_columns(OUT_GAPS, {"gap_id", "gap_name", "gap_category", "required_before_official_recommendation_generation", "current_status", "recommended_resolution_stage", "blocker_for_v20_51", "blocker_for_future_official_generation", "notes"})
    assert_true(len(rows) == 9, f"Policy gap register expected 9 rows, got {len(rows)}")
    gap_names = {clean(row.get("gap_name")) for row in rows}
    missing = sorted(GAP_NAMES - gap_names)
    assert_true(not missing, f"Missing policy gaps: {missing}")
    for row in rows:
        assert_true(clean(row.get("blocker_for_v20_51")) == "FALSE", f"Gap {row.get('gap_id')} incorrectly blocks V20.51")
        assert_true(clean(row.get("blocker_for_future_official_generation")) == "TRUE", f"Gap {row.get('gap_id')} must block future official generation")
        assert_true("official recommendation" in clean(row.get("required_before_official_recommendation_generation")).lower() or clean(row.get("required_before_official_recommendation_generation")) == "TRUE", "Gap requirement must not authorize generation")


def test_action_and_safety_boundaries() -> None:
    actions, _ = assert_columns(OUT_ACTION, {"boundary_name", "allowed_flag", "evidence", "blocker_reason"})
    action_map = by_key(actions, "boundary_name")
    assert_true(TRUE_BOUNDARIES <= set(action_map), f"Missing TRUE boundaries: {sorted(TRUE_BOUNDARIES - set(action_map))}")
    assert_true(FALSE_BOUNDARIES <= set(action_map), f"Missing FALSE boundaries: {sorted(FALSE_BOUNDARIES - set(action_map))}")
    for key in TRUE_BOUNDARIES:
        assert_true(clean(action_map[key].get("allowed_flag")) == "TRUE", f"Action boundary {key} must be TRUE")
    for key in FALSE_BOUNDARIES:
        assert_true(clean(action_map[key].get("allowed_flag")) == "FALSE", f"Action boundary {key} must be FALSE")

    safety, _ = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    safety_map = by_key(safety, "safety_boundary")
    assert_true(set(SAFETY_CHECKS) <= set(safety_map), f"Missing safety checks: {sorted(set(SAFETY_CHECKS) - set(safety_map))}")
    assert_true(len(safety) == 19, f"Safety boundary expected 19 rows, got {len(safety)}")
    for key, expected in SAFETY_CHECKS.items():
        row = safety_map[key]
        assert_true(clean(row.get("expected_value")) == expected, f"Safety {key} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"Safety {key} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Safety {key} must be PASS")
        assert_true(not clean(row.get("blocker_reason")), f"Safety {key} unexpectedly blocked")


def test_next_step() -> None:
    rows, _ = assert_columns(OUT_NEXT, {"stage", "decision", "readiness_status", "future_official_recommendation_gate_ready", "official_recommendation_created_in_this_stage", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed", "formal_tests_required_next", "blocker_count", "warning_count", "next_recommended_stage"})
    assert_true(len(rows) == 1, f"Next-step expected 1 row, got {len(rows)}")
    row = rows[0]
    assert_true(clean(row.get("stage")) == STAGE, "Next-step stage mismatch")
    assert_true(clean(row.get("decision")) == DECISION_PASS, f"Next-step decision expected {DECISION_PASS}, got {row.get('decision')}")
    assert_true(clean(row.get("readiness_status")) in {"READY_WITH_RESEARCH_ONLY_LIMITS", "READY_FOR_FUTURE_OFFICIAL_RECOMMENDATION_GATE"}, "Unexpected readiness status")
    assert_true(clean(row.get("future_official_recommendation_gate_ready")) in {"CONDITIONAL", "TRUE"}, "Future gate readiness must be CONDITIONAL or TRUE")
    for key in ["official_recommendation_created_in_this_stage", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed"]:
        assert_true(clean(row.get(key)) == "FALSE", f"Next-step {key} must be FALSE")
    assert_true(clean(row.get("formal_tests_required_next")) == "TRUE", "formal_tests_required_next must be TRUE")
    assert_true(clean(row.get("blocker_count")) == "0", "Next-step blocker_count must be 0")
    assert_true(clean(row.get("warning_count")) == "0", "Next-step warning_count must be 0")
    assert_true(clean(row.get("next_recommended_stage")) in ALLOWED_NEXT_STAGES, f"Unexpected next recommended stage: {row.get('next_recommended_stage')}")


def test_read_center_and_alias() -> None:
    report = REPORT.read_text(encoding="utf-8")
    report_lower = report.lower()
    required_phrases = [
        "v20.51_official_recommendation_readiness_gate",
        "gate-only readiness assessment",
        "v20.50 research-only packet was used",
        RUN_ID.lower(),
        "no official recommendation was created",
        "no official buy/sell/hold instruction",
        "no trading signal",
        "no broker/order execution",
        "no provider/network refresh",
        "does not import yfinance",
        "recomputes no scores",
        "recomputes no rankings",
        "calculates no forward returns",
        "calculates no benchmark-relative returns",
        "future official gate ready",
        "policy gap register",
        "next recommended stage",
    ]
    for phrase in required_phrases:
        assert_true(phrase in report_lower, f"Report missing phrase: {phrase}")

    alias = CURRENT_REPORT.read_text(encoding="utf-8").lower()
    assert_true("v20.51_official_recommendation_readiness_gate" in alias, "Current alias does not correspond to V20.51")
    assert_true("official recommendation readiness gate" in alias, "Current alias missing readiness gate wording")
    assert_true("no official recommendation was created" in alias, "Current alias missing no-recommendation statement")
    assert_true("official trading readiness" not in alias, "Current alias should not claim official trading readiness")


def test_read_first() -> None:
    flags = read_flags(READ_FIRST)
    expected = {
        "STAGE_NAME": STAGE,
        "OFFICIAL_RECOMMENDATION_READINESS_GATE_STATUS": "READY_WITH_RESEARCH_ONLY_LIMITS",
        "V20_50_RESEARCH_ONLY_PACKET_USED": "TRUE",
        "V20_47_RUN_ID": RUN_ID,
        "V20_47_CACHE_REFERENCE_USED": "TRUE",
        "GATE_ONLY_SAFETY_FLAGS": "TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "BUY_SELL_HOLD_INSTRUCTION_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_51": "FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_51": "FALSE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "RETURNS_CALCULATED": "FALSE",
        "SCORES_RECOMPUTED": "FALSE",
        "RANKINGS_RECOMPUTED": "FALSE",
    }
    for key, value in expected.items():
        assert_true(flags.get(key) == value, f"READ_FIRST {key} expected {value}, got {flags.get(key)}")
    assert_true(flags.get("NEXT_RECOMMENDED_STAGE") in ALLOWED_NEXT_STAGES, f"Unexpected READ_FIRST next stage: {flags.get('NEXT_RECOMMENDED_STAGE')}")


def test_forbidden_language() -> None:
    candidate_text = OUT_CANDIDATE.read_text(encoding="utf-8")
    report_text = REPORT.read_text(encoding="utf-8")
    alias_text = CURRENT_REPORT.read_text(encoding="utf-8")
    read_first_text = READ_FIRST.read_text(encoding="utf-8")
    hits = forbidden_language_hits("\n".join([candidate_text, report_text, alias_text, read_first_text]))
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
        test_prereq_review,
        test_candidate_readiness,
        test_context_readiness,
        test_policy_gap_register,
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
