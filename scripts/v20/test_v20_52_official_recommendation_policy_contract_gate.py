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

PASS_STATUS = "PASS_V20_52_TESTS"
FAIL_STATUS = "FAIL_V20_52_TESTS"
STAGE = "V20.52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_CREATED"
CONTRACT_GATE_PASS = "PASS_POLICY_CONTRACT_GATE_CREATED"
NEXT_STAGES = {"V20.52_FORMAL_TESTS", "V20.53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"}
UPSTREAM_READY = {"READY_WITH_RESEARCH_ONLY_LIMITS", "READY_FOR_FUTURE_OFFICIAL_RECOMMENDATION_GATE"}
UPSTREAM_FUTURE_READY = {"CONDITIONAL", "TRUE"}

PROD_SCRIPT = SCRIPT_DIR / "v20_52_official_recommendation_policy_contract_gate.py"
WRAPPER = SCRIPT_DIR / "run_v20_52_official_recommendation_policy_contract_gate.ps1"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_52_official_recommendation_policy_contract_gate.py"

OUT_SUMMARY = CONSOLIDATION / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_52_UPSTREAM_V20_51_VALIDATION.csv"
OUT_GAP_CONTRACT = CONSOLIDATION / "V20_52_POLICY_GAP_RESOLUTION_CONTRACT.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_52_OFFICIAL_OUTPUT_SCHEMA_CONTRACT.csv"
OUT_LANGUAGE = CONSOLIDATION / "V20_52_RECOMMENDATION_LANGUAGE_POLICY.csv"
OUT_RISK = CONSOLIDATION / "V20_52_RISK_POSITION_POLICY_CONTRACT.csv"
OUT_MANUAL = CONSOLIDATION / "V20_52_MANUAL_APPROVAL_AND_REAL_BOOK_POLICY.csv"
OUT_BROKER = CONSOLIDATION / "V20_52_BROKER_DISABLED_ENFORCEMENT_CONTRACT.csv"
OUT_AUDIT = CONSOLIDATION / "V20_52_POST_RECOMMENDATION_AUDIT_TEST_CONTRACT.csv"
OUT_SCOPE = CONSOLIDATION / "V20_52_FUTURE_OFFICIAL_STAGE_ALLOWED_SCOPE.csv"
OUT_ACTION = CONSOLIDATION / "V20_52_POLICY_CONTRACT_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_52_POLICY_CONTRACT_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_52_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE.md"
READ_FIRST = OPS / "V20_52_READ_FIRST.txt"

REQUIRED_FILES = [
    PROD_SCRIPT,
    WRAPPER,
    OUT_SUMMARY,
    OUT_UPSTREAM,
    OUT_GAP_CONTRACT,
    OUT_SCHEMA,
    OUT_LANGUAGE,
    OUT_RISK,
    OUT_MANUAL,
    OUT_BROKER,
    OUT_AUDIT,
    OUT_SCOPE,
    OUT_ACTION,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_EXPECTED = {
    "stage": STAGE,
    "upstream_v20_51_readiness_status": "READY_WITH_RESEARCH_ONLY_LIMITS",
    "upstream_v20_51_tests_status": "PASS",
    "v20_51_policy_gap_count": "9",
    "policy_contract_created": "TRUE",
    "official_output_schema_contract_created": "TRUE",
    "recommendation_language_policy_created": "TRUE",
    "risk_position_policy_created": "TRUE",
    "manual_approval_policy_created": "TRUE",
    "real_book_separation_policy_created": "TRUE",
    "broker_disabled_policy_created": "TRUE",
    "post_recommendation_audit_policy_created": "TRUE",
    "official_recommendation_created_in_this_stage": "FALSE",
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
    "contract_gate_status": CONTRACT_GATE_PASS,
}

UPSTREAM_EXPECTED_VALUES = {
    "v20_51_summary_exists_non_empty": "TRUE",
    "v20_51_upstream_validation_exists_non_empty": "TRUE",
    "v20_51_prerequisite_review_exists_non_empty": "TRUE",
    "v20_51_candidate_readiness_exists_non_empty": "TRUE",
    "v20_51_context_readiness_exists_non_empty": "TRUE",
    "v20_51_policy_gap_register_exists_non_empty": "TRUE",
    "v20_51_action_boundary_exists_non_empty": "TRUE",
    "v20_51_safety_boundary_exists_non_empty": "TRUE",
    "v20_51_next_step_decision_exists_non_empty": "TRUE",
    "v20_51_read_center_report_exists_non_empty": "TRUE",
    "v20_51_current_alias_exists_non_empty": "TRUE",
    "v20_51_read_first_exists_non_empty": "TRUE",
    "v20_51_formal_test_script_exists": "TRUE",
    "v20_51_decision": "PASS_OFFICIAL_RECOMMENDATION_READINESS_GATE_CREATED",
    "v20_51_tests_status": "PASS",
    "v20_51_candidate_count": "50",
    "v20_51_priority_review_count": "20",
    "v20_51_standard_review_count": "30",
    "v20_51_context_rows": "6",
    "v20_51_policy_gap_count": "9",
    "v20_51_official_recommendation_created": "FALSE",
    "v20_51_official_recommendation_allowed_in_this_stage": "FALSE",
    "v20_51_official_trading_allowed": "FALSE",
    "v20_51_broker_order_execution_used": "FALSE",
    "v20_51_provider_refresh_executed_in_this_stage": "FALSE",
    "v20_51_yfinance_import_used_in_this_stage": "FALSE",
    "v20_51_official_ranking_mutated": "FALSE",
    "v20_51_dynamic_weighting_mutated": "FALSE",
    "v20_51_returns_calculated": "FALSE",
    "v20_51_benchmark_relative_returns_calculated": "FALSE",
    "v20_51_scores_recomputed": "FALSE",
    "v20_51_rankings_recomputed": "FALSE",
    "v20_51_trading_signals_created": "FALSE",
    "v20_51_action_boundary_dynamic_weighting_mutation_allowed": "FALSE",
    "v20_51_action_boundary_official_ranking_mutation_allowed": "FALSE",
    "v20_51_safety_returns_calculated": "FALSE",
    "v20_51_safety_scores_recomputed": "FALSE",
    "v20_51_safety_rankings_recomputed": "FALSE",
    "v20_51_safety_trading_signals_created": "FALSE",
    "v20_51_forbidden_actionable_language_scan": "PASS",
}

SCHEMA_REQUIRED_FIELDS = {
    "recommendation_run_id",
    "source_research_packet_id",
    "source_v20_47_run_id",
    "candidate_id_or_ticker",
    "preserved_report_rank",
    "research_decision_category",
    "official_recommendation_label",
    "recommendation_confidence_band",
    "recommendation_rationale",
    "risk_summary",
    "position_policy_reference",
    "manual_approval_required",
    "broker_execution_allowed",
    "real_book_mutation_allowed",
    "official_trading_allowed",
    "created_timestamp_utc",
    "audit_status",
}

LANGUAGE_FORBIDDEN_PHRASES = {
    "buy",
    "sell",
    "hold",
    "strong buy",
    "reduce",
    "add position",
    "enter position",
    "exit position",
    "execute",
    "trade now",
}

LANGUAGE_SAFE_PHRASES = {
    "research review priority",
    "candidate for further review",
    "factor support context",
    "refreshed price context",
    "not an official recommendation",
    "not trading-authorized",
    "future gate required",
}

RISK_AREAS = {
    "max position size policy",
    "max single-name exposure policy",
    "sector concentration policy",
    "liquidity/volume policy",
    "volatility/VIX risk policy",
    "earnings/event risk policy",
    "stop/exit framework reference",
    "portfolio drawdown policy",
    "cash allocation policy",
    "manual override policy",
}

MANUAL_POLICIES = {
    "human/operator approval required before any official recommendation publication",
    "user/manual approval required before any real-book action",
    "real book must remain separate from research/simulation book",
    "real-book mutation blocked in this stage",
    "broker route disabled",
    "actual holdings not inferred unless explicitly supplied through approved ledger",
    "official output cannot imply automatic execution",
    "recommendation packet cannot mutate portfolio state",
}

BROKER_CHECKS = {
    "broker_order_execution_allowed": "FALSE",
    "broker_api_import_allowed": "FALSE",
    "live_trading_allowed": "FALSE",
    "order_file_creation_allowed": "FALSE",
    "trade_signal_file_creation_allowed": "FALSE",
    "real_portfolio_mutation_allowed": "FALSE",
    "no broker/order code path in V20.52 script": "TRUE",
    "no broker/order code path in wrapper": "TRUE",
}

AUDIT_REQUIREMENTS = {
    "official output schema validation tests",
    "forbidden language scan tests",
    "no broker/order path tests",
    "no trading signal tests",
    "no ranking mutation tests",
    "no dynamic weighting mutation tests",
    "source lineage and run_id tests",
    "manual approval field validation tests",
    "risk policy field validation tests",
    "read-center/READ_FIRST safety tests",
}

FUTURE_SCOPE_CONDITIONAL = {
    "official recommendation schema instantiation",
    "controlled recommendation label assignment",
    "recommendation rationale generation",
    "risk policy binding",
    "manual approval field binding",
    "official recommendation report generation",
}

FUTURE_SCOPE_BLOCKED = {
    "actual candidate recommendation labels",
    "buy/sell/hold instruction generation",
    "trading signal generation",
    "broker/order route",
    "real portfolio mutation",
    "official ranking mutation",
    "dynamic weighting mutation",
    "returns calculation",
    "score/ranking recomputation",
}

ACTION_TRUE = {
    "policy_contract_definition_allowed",
    "official_output_schema_contract_allowed",
    "recommendation_language_policy_allowed",
    "risk_position_policy_contract_allowed",
    "manual_approval_policy_contract_allowed",
    "broker_disabled_policy_contract_allowed",
    "post_recommendation_audit_contract_allowed",
    "future_official_stage_scope_definition_allowed",
}

ACTION_FALSE = {
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

SAFETY_EXPECTED = {
    "provider_refresh_executed_in_v20_52": "FALSE",
    "yfinance_imported_in_v20_52": "FALSE",
    "v20_51_readiness_gate_used": "TRUE",
    "v20_50_research_only_packet_reference_used": "TRUE",
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


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return str(value or "").strip()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def row_count(path: Path) -> int:
    rows, _ = read_csv(path)
    return len(rows)


def by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {clean(row.get(key)): row for row in rows}


def assert_columns(path: Path, required: set[str]) -> list[dict[str, str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing required columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows


def file_is_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def read_flags(path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[clean(key)] = clean(value)
    return flags


def pycache_paths() -> list[Path]:
    return [path for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]


def cleanup_pycache() -> None:
    for path in pycache_paths():
        shutil.rmtree(path, ignore_errors=True)


def tokenized_text(path: Path) -> str:
    tokens: list[str] = []
    source = path.read_bytes()
    for token in tokenize.tokenize(BytesIO(source).readline):
        if token.type in {tokenize.ENCODING, tokenize.STRING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE}:
            continue
        tokens.append(token.string)
    return " ".join(tokens)


def assert_no_yfinance_import(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert_true(all(alias.name.split(".")[0] != "yfinance" for alias in node.names), f"{path.name} imports yfinance")
        elif isinstance(node, ast.ImportFrom):
            assert_true((node.module or "").split(".")[0] != "yfinance", f"{path.name} imports from yfinance")


def assert_no_forbidden_exec_patterns() -> None:
    for path in [PROD_SCRIPT, TEST_SCRIPT]:
        assert_no_yfinance_import(path)
    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    assert_true("import yfinance" not in wrapper_text, "Wrapper imports yfinance")
    assert_true("from yfinance" not in wrapper_text, "Wrapper imports from yfinance")

    tokenized = " ".join(tokenized_text(path) for path in [PROD_SCRIPT, WRAPPER, TEST_SCRIPT]).lower()
    forbidden = [
        r"\bsubmit_order\b",
        r"\bplace_order\b",
        r"\balpaca_trade_api\b",
        r"\bibapi\b",
        r"\bccxt\b",
        r"\brequests\b",
        r"\burllib\b",
        r"\bhttpx\b",
        r"outputs\s*/\s*v21",
        r"outputs\s*/\s*v19_21",
        r"outputs\\v19\\V19_21",
        r"outputs\\v19_21",
    ]
    for pattern in forbidden:
        assert_true(not re.search(pattern, tokenized, re.IGNORECASE), f"Executable safety pattern found: {pattern}")

    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    for term in ["alpaca", "ibapi", "ccxt", "submit_order", "place_order", "outputs/v21", "outputs\\v21", "outputs/v19_21", "outputs\\v19_21", "outputs/v19/v19_21", "outputs\\v19\\v19_21"]:
        assert_true(term not in wrapper_text, f"Wrapper safety pattern found: {term}")


def strip_allowed_negations(text: str) -> str:
    lowered = text.lower()
    substitutions = [
        r"no official recommendation created",
        r"no official recommendation was created",
        r"no official recommendation",
        r"no official buy/sell/hold instruction",
        r"no buy/sell/hold instruction",
        r"no buy/sell/hold instructions",
        r"no trading signal",
        r"no trading signals",
        r"no broker/order execution",
        r"no broker/order execution path",
        r"does not import yfinance",
        r"no provider refresh",
        r"no network refresh",
        r"not trading-authorized",
        r"no official ranking mutation",
        r"no dynamic weighting mutation",
        r"no return calculation",
        r"no benchmark-relative return calculation",
        r"no score recomputation",
        r"no ranking recomputation",
        r"no real portfolio mutation",
        r"policy contract gate only",
        r"policy contract only",
        r"future official gate required",
    ]
    for pattern in substitutions:
        lowered = re.sub(pattern, "", lowered, flags=re.IGNORECASE)
    return lowered


def forbidden_language_hits(text: str) -> list[str]:
    filtered = strip_allowed_negations(text)
    patterns = [
        r"\bstrong buy\b",
        r"\badd position\b",
        r"\benter position\b",
        r"\bexit position\b",
        r"\btrade now\b",
        r"\breduce\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, filtered, flags=re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(filtered), match.end() + 35)
            hits.append(filtered[start:end].replace("\n", " "))
    return hits


def assert_required_files() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required files: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty required files: {empty}")
    assert_true(len(REQUIRED_FILES) == 18, f"Expected 18 required files, got {len(REQUIRED_FILES)}")


def test_summary() -> None:
    rows = assert_columns(
        OUT_SUMMARY,
        {
            "stage",
            "upstream_v20_51_readiness_status",
            "upstream_v20_51_tests_status",
            "v20_47_run_id",
            "v20_51_policy_gap_count",
            "policy_contract_created",
            "official_output_schema_contract_created",
            "recommendation_language_policy_created",
            "risk_position_policy_created",
            "manual_approval_policy_created",
            "real_book_separation_policy_created",
            "broker_disabled_policy_created",
            "post_recommendation_audit_policy_created",
            "future_official_generation_allowed_by_contract",
            "official_recommendation_created_in_this_stage",
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
            "blocker_count",
            "warning_count",
            "contract_gate_status",
            "next_recommended_stage",
        },
    )
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    for key, expected in SUMMARY_EXPECTED.items():
        assert_true(clean(row.get(key)) == expected, f"Summary {key} expected {expected}, got {clean(row.get(key))}")
    assert_true(clean(row.get("v20_47_run_id")), "Summary v20_47_run_id must be present")
    assert_true(clean(row.get("future_official_generation_allowed_by_contract")) in {"CONDITIONAL", "TRUE"}, "Summary future_official_generation_allowed_by_contract must be CONDITIONAL or TRUE")
    assert_true(clean(row.get("next_recommended_stage")) in NEXT_STAGES, f"Summary next_recommended_stage unexpected: {row.get('next_recommended_stage')}")


def test_upstream_validation() -> None:
    rows = assert_columns(
        OUT_UPSTREAM,
        {"validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"},
    )
    assert_true(len(rows) == 42, f"Upstream validation expected 42 rows, got {len(rows)}")
    item_map = by_key(rows, "validation_item")
    missing = sorted(set(UPSTREAM_EXPECTED_VALUES) - set(item_map))
    assert_true(not missing, f"Missing upstream validation items: {missing}")
    for key, expected in UPSTREAM_EXPECTED_VALUES.items():
        row = item_map[key]
        actual = clean(row.get("actual_value"))
        if key == "v20_51_readiness_status":
            assert_true(actual in UPSTREAM_READY, f"Unexpected readiness status: {actual}")
        elif key == "v20_51_future_gate_readiness":
            assert_true(actual in UPSTREAM_FUTURE_READY, f"Unexpected future gate readiness: {actual}")
        else:
            assert_true(actual == expected, f"Upstream {key} expected {expected}, got {actual}")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Upstream {key} must be PASS")
        assert_true(not clean(row.get("blocker_reason")), f"Upstream {key} unexpectedly blocked")
    blocked = [row for row in rows if clean(row.get("validation_status")) != "PASS" or clean(row.get("blocker_reason"))]
    assert_true(not blocked, f"Upstream validation has blocked rows: {blocked[:3]}")


def test_policy_gap_contract() -> None:
    rows = assert_columns(
        OUT_GAP_CONTRACT,
        {
            "gap_id",
            "gap_name",
            "gap_category",
            "v20_51_current_status",
            "blocker_for_future_official_generation",
            "required_policy_contract",
            "v20_52_contract_status",
            "required_before_generation",
            "recommended_resolution_stage",
            "blocker_if_unresolved",
            "notes",
        },
    )
    assert_true(len(rows) == 9, f"Policy gap contract expected 9 rows, got {len(rows)}")
    assert_true({clean(row.get("gap_id")) for row in rows} == {f"GAP00{i}" for i in range(1, 10)}, "Unexpected gap ids")
    for row in rows:
        assert_true(clean(row.get("blocker_for_future_official_generation")) == "TRUE", f"Gap {row.get('gap_id')} must block future generation")
        assert_true(clean(row.get("v20_52_contract_status")) == "CONTRACT_DEFINED", f"Gap {row.get('gap_id')} status must be CONTRACT_DEFINED")
        assert_true(clean(row.get("required_before_generation")) == "TRUE", f"Gap {row.get('gap_id')} must be required before generation")
        assert_true("no official recommendation created" in clean(row.get("notes")).lower(), f"Gap {row.get('gap_id')} notes must remain contract-only")


def test_schema_contract() -> None:
    rows = assert_columns(OUT_SCHEMA, {"field_name", "field_type", "required_flag", "allowed_values", "forbidden_values", "purpose", "validation_rule", "blocker_if_missing"})
    assert_true(len(rows) == 17, f"Schema contract expected 17 rows, got {len(rows)}")
    fields = {clean(row.get("field_name")) for row in rows}
    missing = sorted(SCHEMA_REQUIRED_FIELDS - fields)
    assert_true(not missing, f"Schema contract missing fields: {missing}")
    for row in rows:
        assert_true(clean(row.get("required_flag")) == "TRUE", f"Schema field {row.get('field_name')} must be required")
    lookup = by_key(rows, "field_name")
    assert_true("manual_approval_required" in lookup, "manual_approval_required schema field missing")
    assert_true("broker_execution_allowed" in lookup, "broker_execution_allowed schema field missing")
    assert_true("official_trading_allowed" in lookup, "official_trading_allowed schema field missing")
    assert_true("buy|sell|hold" in clean(lookup["official_recommendation_label"].get("forbidden_values")).lower(), "official_recommendation_label forbidden values must block actionable labels")
    assert_true(clean(lookup["manual_approval_required"].get("allowed_values")) == "TRUE", "manual_approval_required allowed_values must be TRUE")
    assert_true(clean(lookup["manual_approval_required"].get("forbidden_values")) == "FALSE", "manual_approval_required forbidden_values must be FALSE")
    assert_true(clean(lookup["broker_execution_allowed"].get("allowed_values")).lower().startswith("false"), "broker_execution_allowed must remain FALSE in V20.52")
    assert_true(clean(lookup["broker_execution_allowed"].get("forbidden_values")).lower().startswith("true"), "broker_execution_allowed must forbid TRUE in V20.52")
    assert_true(clean(lookup["official_trading_allowed"].get("allowed_values")).lower().startswith("false"), "official_trading_allowed must remain FALSE in V20.52")
    assert_true(clean(lookup["official_trading_allowed"].get("forbidden_values")).lower().startswith("true"), "official_trading_allowed must forbid TRUE in V20.52")
    assert_true("approval" in clean(lookup["manual_approval_required"].get("purpose")).lower(), "manual_approval_required purpose must reference approval")


def test_recommendation_language_policy() -> None:
    rows = assert_columns(
        OUT_LANGUAGE,
        {
            "language_policy_id",
            "phrase_or_pattern",
            "policy_type",
            "allowed_in_future_official_output",
            "allowed_in_research_only_output",
            "requires_manual_approval",
            "replacement_or_safe_phrase",
            "rationale",
        },
    )
    assert_true(len(rows) == 17, f"Language policy expected 17 rows, got {len(rows)}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[clean(row.get("policy_type"))] = counts.get(clean(row.get("policy_type")), 0) + 1
    assert_true(counts.get("FORBIDDEN_ACTIONABLE_LANGUAGE") == 10, f"Forbidden actionable language count mismatch: {counts}")
    assert_true(counts.get("SAFE_RESEARCH_ONLY_LANGUAGE") == 7, f"Safe research-only language count mismatch: {counts}")
    phrases = {clean(row.get("phrase_or_pattern")).lower() for row in rows}
    assert_true(LANGUAGE_FORBIDDEN_PHRASES <= phrases, f"Missing forbidden language phrases: {sorted(LANGUAGE_FORBIDDEN_PHRASES - phrases)}")
    assert_true(LANGUAGE_SAFE_PHRASES <= phrases, f"Missing safe language phrases: {sorted(LANGUAGE_SAFE_PHRASES - phrases)}")


def test_risk_manual_broker_audit_scope() -> None:
    risk_rows = assert_columns(OUT_RISK, {"policy_id", "policy_area", "policy_requirement", "required_before_official_generation", "current_status", "enforcement_stage", "blocker_if_missing", "notes"})
    assert_true(len(risk_rows) == 10, f"Risk contract expected 10 rows, got {len(risk_rows)}")
    assert_true({clean(row.get("policy_area")) for row in risk_rows} == RISK_AREAS, "Risk policy areas mismatch")
    for row in risk_rows:
        assert_true(clean(row.get("required_before_official_generation")) == "TRUE", f"Risk policy {row.get('policy_id')} must be required before official generation")
        assert_true(clean(row.get("current_status")) == "CONTRACT_DEFINED", f"Risk policy {row.get('policy_id')} status must be CONTRACT_DEFINED")

    manual_rows = assert_columns(OUT_MANUAL, {"policy_id", "policy_name", "required_flag", "policy_status", "applies_to", "allowed_state", "blocked_state", "enforcement_notes"})
    assert_true(len(manual_rows) == 8, f"Manual policy expected 8 rows, got {len(manual_rows)}")
    assert_true({clean(row.get("policy_name")) for row in manual_rows} == MANUAL_POLICIES, "Manual policy rows mismatch")
    for row in manual_rows:
        assert_true(clean(row.get("required_flag")) == "TRUE", f"Manual policy {row.get('policy_id')} must be required")
        assert_true(clean(row.get("policy_status")) == "CONTRACT_DEFINED", f"Manual policy {row.get('policy_id')} status must be CONTRACT_DEFINED")

    broker_rows = assert_columns(OUT_BROKER, {"enforcement_id", "enforcement_check", "expected_value", "enforcement_status", "evidence", "blocker_if_failed"})
    assert_true(len(broker_rows) == 8, f"Broker enforcement expected 8 rows, got {len(broker_rows)}")
    broker_map = by_key(broker_rows, "enforcement_check")
    missing_broker = sorted(set(BROKER_CHECKS) - set(broker_map))
    assert_true(not missing_broker, f"Missing broker checks: {missing_broker}")
    for key, expected in BROKER_CHECKS.items():
        row = broker_map[key]
        assert_true(clean(row.get("expected_value")) == expected, f"Broker check {key} expected {expected}, got {clean(row.get('expected_value'))}")
        assert_true(clean(row.get("enforcement_status")) == "PASS", f"Broker check {key} must PASS")
    assert_true("contract-only" in clean(broker_map["no broker/order code path in V20.52 script"].get("evidence")).lower(), "Broker script safety evidence missing")
    assert_true("wrapper only invokes python stage script" in clean(broker_map["no broker/order code path in wrapper"].get("evidence")).lower(), "Broker wrapper safety evidence missing")

    audit_rows = assert_columns(OUT_AUDIT, {"audit_requirement_id", "audit_requirement", "required_before_future_official_generation", "required_after_future_official_generation", "test_or_artifact_needed", "blocker_if_missing", "notes"})
    assert_true(len(audit_rows) == 10, f"Audit contract expected 10 rows, got {len(audit_rows)}")
    assert_true({clean(row.get("audit_requirement")) for row in audit_rows} == AUDIT_REQUIREMENTS, "Audit requirements mismatch")
    for row in audit_rows:
        assert_true(clean(row.get("required_before_future_official_generation")) == "TRUE", f"Audit requirement {row.get('audit_requirement_id')} must be required before future official generation")
        assert_true(clean(row.get("required_after_future_official_generation")) == "TRUE", f"Audit requirement {row.get('audit_requirement_id')} must remain required after generation")

    scope_rows = assert_columns(OUT_SCOPE, {"scope_item", "allowed_for_future_official_stage", "allowed_in_v20_52", "required_precondition", "blocked_action", "notes"})
    assert_true(len(scope_rows) == 15, f"Future scope expected 15 rows, got {len(scope_rows)}")
    scope_map = by_key(scope_rows, "scope_item")
    missing_conditional = FUTURE_SCOPE_CONDITIONAL - set(scope_map)
    missing_blocked = FUTURE_SCOPE_BLOCKED - set(scope_map)
    assert_true(not missing_conditional, f"Missing conditional future scope items: {sorted(missing_conditional)}")
    assert_true(not missing_blocked, f"Missing blocked future scope items: {sorted(missing_blocked)}")
    for row in scope_rows:
        assert_true(clean(row.get("allowed_in_v20_52")) == "FALSE", f"Scope item {row.get('scope_item')} must be blocked in V20.52")
        assert_true("do not instantiate in v20.52" in clean(row.get("blocked_action")).lower() or "blocked by v20.52 policy contract" in clean(row.get("required_precondition")).lower(), f"Scope item {row.get('scope_item')} must remain future-only")


def test_boundaries() -> None:
    action_rows = assert_columns(OUT_ACTION, {"boundary_name", "allowed_flag", "evidence", "blocker_reason"})
    assert_true(len(action_rows) == 22, f"Action boundary expected 22 rows, got {len(action_rows)}")
    action_map = by_key(action_rows, "boundary_name")
    assert_true(ACTION_TRUE <= set(action_map), f"Missing TRUE boundaries: {sorted(ACTION_TRUE - set(action_map))}")
    assert_true(ACTION_FALSE <= set(action_map), f"Missing FALSE boundaries: {sorted(ACTION_FALSE - set(action_map))}")
    for key in ACTION_TRUE:
        assert_true(clean(action_map[key].get("allowed_flag")) == "TRUE", f"Action boundary {key} must be TRUE")
    for key in ACTION_FALSE:
        assert_true(clean(action_map[key].get("allowed_flag")) == "FALSE", f"Action boundary {key} must be FALSE")

    safety_rows = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    assert_true(len(safety_rows) == 19, f"Safety boundary expected 19 rows, got {len(safety_rows)}")
    safety_map = by_key(safety_rows, "safety_boundary")
    assert_true(set(SAFETY_EXPECTED) <= set(safety_map), f"Missing safety rows: {sorted(set(SAFETY_EXPECTED) - set(safety_map))}")
    for key, expected in SAFETY_EXPECTED.items():
        row = safety_map[key]
        assert_true(clean(row.get("expected_value")) == expected, f"Safety {key} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"Safety {key} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Safety {key} must PASS")
        assert_true(not clean(row.get("blocker_reason")), f"Safety {key} unexpectedly blocked")


def test_next_step() -> None:
    rows = assert_columns(
        OUT_NEXT,
        {
            "stage",
            "decision",
            "contract_gate_status",
            "policy_contract_created",
            "future_official_policy_contract_ready",
            "official_recommendation_created_in_this_stage",
            "official_recommendation_allowed_in_this_stage",
            "official_trading_allowed",
            "broker_execution_allowed",
            "formal_tests_required_next",
            "blocker_count",
            "warning_count",
            "next_recommended_stage",
        },
    )
    assert_true(len(rows) == 1, f"Next-step decision expected 1 row, got {len(rows)}")
    row = rows[0]
    assert_true(clean(row.get("stage")) == STAGE, "Next-step stage mismatch")
    assert_true(clean(row.get("decision")) == DECISION_PASS, f"Next-step decision expected {DECISION_PASS}, got {row.get('decision')}")
    assert_true(clean(row.get("contract_gate_status")) == CONTRACT_GATE_PASS, f"Next-step contract gate status expected {CONTRACT_GATE_PASS}, got {row.get('contract_gate_status')}")
    assert_true(clean(row.get("policy_contract_created")) == "TRUE", "Next-step policy_contract_created must be TRUE")
    assert_true(clean(row.get("future_official_policy_contract_ready")) in {"CONDITIONAL", "TRUE"}, "Future official policy contract ready must be CONDITIONAL or TRUE")
    for key in ["official_recommendation_created_in_this_stage", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed"]:
        assert_true(clean(row.get(key)) == "FALSE", f"Next-step {key} must be FALSE")
    assert_true(clean(row.get("formal_tests_required_next")) == "TRUE", "formal_tests_required_next must be TRUE")
    assert_true(clean(row.get("blocker_count")) == "0", "Next-step blocker_count must be 0")
    assert_true(clean(row.get("warning_count")) == "0", "Next-step warning_count must be 0")
    assert_true(clean(row.get("next_recommended_stage")) in NEXT_STAGES, f"Unexpected next recommended stage: {row.get('next_recommended_stage')}")


def test_read_center_report() -> None:
    report = REPORT.read_text(encoding="utf-8")
    lower = report.lower()
    required_phrases = [
        STAGE.lower(),
        "policy contract gate only",
        "v20.51 readiness status",
        "no official recommendation created",
        "no buy/sell/hold instruction",
        "no trading signal created",
        "no broker/order execution path",
        "no provider refresh or network refresh",
        "does not import yfinance",
        "no return calculation",
        "benchmark-relative return calculation",
        "score recomputation",
        "ranking recomputation",
        "policy gap resolution contract",
        "future official output schema contract",
        "recommendation language policy",
        "risk/position policy contract",
        "manual approval and real-book separation policy",
        "broker-disabled enforcement contract",
        "post-recommendation audit/test contract",
        "next recommended stage",
    ]
    for phrase in required_phrases:
        assert_true(phrase in lower, f"Report missing phrase: {phrase}")
    assert_true("official trading readiness" not in lower, "Report should not claim official trading readiness")

    alias = CURRENT_REPORT.read_text(encoding="utf-8").lower()
    assert_true(STAGE.lower() in alias, "Current alias does not correspond to V20.52")
    assert_true("official recommendation policy contract gate" in alias, "Current alias missing stage wording")
    assert_true("no official recommendation created" in alias, "Current alias missing no-recommendation statement")
    assert_true("official trading readiness" not in alias, "Current alias should not claim official trading readiness")


def test_read_first() -> None:
    flags = read_flags(READ_FIRST)
    expected = {
        "STAGE_NAME": STAGE,
        "STATUS": "PASS_V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE",
        "DECISION": DECISION_PASS,
        "POLICY_CONTRACT_GATE_STATUS": CONTRACT_GATE_PASS,
        "V20_51_READINESS_GATE_USED": "TRUE",
        "V20_50_RESEARCH_ONLY_PACKET_REFERENCE": "TRUE",
        "V20_47_RUN_ID_CACHE_REFERENCE": "V20_47_20260604T114058Z",
        "GATE_ONLY_SAFETY_FLAGS": "TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED": "FALSE",
        "BUY_SELL_HOLD_INSTRUCTION_CREATED": "FALSE",
        "TRADING_SIGNAL_CREATED": "FALSE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_52": "FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_52": "FALSE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "RETURNS_CALCULATED": "FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CALCULATED": "FALSE",
        "SCORES_RECOMPUTED": "FALSE",
        "RANKINGS_RECOMPUTED": "FALSE",
        "POLICY_CONTRACT_ONLY": "TRUE",
    }
    for key, expected_value in expected.items():
        assert_true(flags.get(key) == expected_value, f"READ_FIRST {key} expected {expected_value}, got {flags.get(key)}")
    assert_true(flags.get("NEXT_RECOMMENDED_STAGE") in NEXT_STAGES, f"Unexpected READ_FIRST next stage: {flags.get('NEXT_RECOMMENDED_STAGE')}")


def test_forbidden_language_scan() -> None:
    text = "\n".join(
        [
            OUT_SUMMARY.read_text(encoding="utf-8"),
            OUT_NEXT.read_text(encoding="utf-8"),
            READ_FIRST.read_text(encoding="utf-8"),
        ]
    )
    hits = forbidden_language_hits(text)
    assert_true(not hits, f"Forbidden actionable language found: {hits[:5]}")


def test_static_safety_scans() -> None:
    assert_no_forbidden_exec_patterns()


def test_no_forbidden_output_paths() -> None:
    forbidden_paths = [ROOT / "outputs" / "v21", ROOT / "outputs" / "v19_21", ROOT / "outputs" / "v19" / "V19_21"]
    existing = [str(path) for path in forbidden_paths if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")


def main() -> int:
    failures: list[str] = []
    tests = [
        ("required_files", assert_required_files),
        ("summary", test_summary),
        ("upstream_validation", test_upstream_validation),
        ("policy_gap_contract", test_policy_gap_contract),
        ("schema_contract", test_schema_contract),
        ("recommendation_language_policy", test_recommendation_language_policy),
        ("risk_manual_broker_audit_scope", test_risk_manual_broker_audit_scope),
        ("boundaries", test_boundaries),
        ("next_step", test_next_step),
        ("read_center_report", test_read_center_report),
        ("read_first", test_read_first),
        ("forbidden_language_scan", test_forbidden_language_scan),
        ("static_safety_scans", test_static_safety_scans),
        ("no_forbidden_output_paths", test_no_forbidden_output_paths),
    ]
    try:
        for name, test in tests:
            try:
                test()
            except Exception as exc:
                failures.append(f"{name}: {exc}")
    finally:
        cleanup_pycache()
    remaining = pycache_paths()
    if remaining:
        failures.append(f"pycache remains under scripts/v20: {[str(path) for path in remaining]}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(FAIL_STATUS)
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
