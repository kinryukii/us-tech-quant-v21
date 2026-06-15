from __future__ import annotations

import ast
import csv
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

PASS_STATUS = "PASS_V20_53_TESTS"
FAIL_STATUS = "FAIL_V20_53_TESTS"
STAGE = "V20.53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
WRAPPER_PASS = "PASS_V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_CREATED"
SCHEMA_DRY_RUN_PASS = "PASS_SCHEMA_DRY_RUN_GATE_CREATED"
V20_52_CONTRACT_PASS = "PASS_POLICY_CONTRACT_GATE_CREATED"
NEXT_STAGE = "V20.53_FORMAL_TESTS"

PROD_SCRIPT = SCRIPT_DIR / "v20_53_official_recommendation_schema_dry_run_gate.py"
WRAPPER = SCRIPT_DIR / "run_v20_53_official_recommendation_schema_dry_run_gate.ps1"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_53_official_recommendation_schema_dry_run_gate.py"

OUT_SUMMARY = CONSOLIDATION / "V20_53_OFFICIAL_SCHEMA_DRY_RUN_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_53_UPSTREAM_V20_52_VALIDATION.csv"
OUT_MAPPING = CONSOLIDATION / "V20_53_SCHEMA_FIELD_MAPPING_DRY_RUN.csv"
OUT_DRY_ROWS = CONSOLIDATION / "V20_53_CANDIDATE_SCHEMA_DRY_RUN_ROWS.csv"
OUT_LANGUAGE = CONSOLIDATION / "V20_53_LANGUAGE_POLICY_DRY_RUN_VALIDATION.csv"
OUT_BINDING = CONSOLIDATION / "V20_53_POLICY_BINDING_DRY_RUN_VALIDATION.csv"
OUT_ACTION = CONSOLIDATION / "V20_53_SCHEMA_DRY_RUN_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_53_SCHEMA_DRY_RUN_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_53_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE.md"
READ_FIRST = OPS / "V20_53_READ_FIRST.txt"

REQUIRED_OUTPUTS = [
    OUT_SUMMARY,
    OUT_UPSTREAM,
    OUT_MAPPING,
    OUT_DRY_ROWS,
    OUT_LANGUAGE,
    OUT_BINDING,
    OUT_ACTION,
    OUT_SAFETY,
    OUT_NEXT,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_FALSE_FIELDS = [
    "official_recommendation_created_in_this_stage",
    "official_recommendation_label_assigned",
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
]

DRY_ROW_FALSE_FIELDS = [
    "broker_execution_allowed",
    "real_book_mutation_allowed",
    "official_trading_allowed",
    "official_recommendation_created",
    "recommendation_label_assigned",
    "trading_signal_created",
    "ranking_mutated",
    "score_recomputed",
]

SAFETY_EXPECTED = {
    "provider_refresh_executed_in_v20_53": "FALSE",
    "yfinance_imported_in_v20_53": "FALSE",
    "v20_52_policy_contract_used": "TRUE",
    "v20_50_research_only_packet_reference_used": "TRUE",
    "v20_47_certified_cache_reference_used": "TRUE",
    "broker_order_execution_used": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_recommendation_label_assigned": "FALSE",
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
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def read_flags(path: Path) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[clean(key)] = clean(value)
    return flags


def by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {clean(row.get(key)): row for row in rows}


def pycache_paths() -> list[Path]:
    return [path for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]


def cleanup_pycache() -> None:
    for path in pycache_paths():
        shutil.rmtree(path, ignore_errors=True)


def assert_columns(path: Path, required: set[str]) -> list[dict[str, str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows


def assert_required_outputs() -> None:
    missing = [str(path) for path in REQUIRED_OUTPUTS if not path.exists()]
    assert_true(not missing, f"Missing V20.53 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_OUTPUTS if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty V20.53 outputs: {empty}")
    assert_true(PROD_SCRIPT.exists(), "V20.53 production script missing")
    assert_true(WRAPPER.exists(), "V20.53 wrapper missing")


def test_summary_and_next_step() -> None:
    row = first_row(OUT_SUMMARY)
    next_row = first_row(OUT_NEXT)
    flags = read_flags(READ_FIRST)
    expected_summary = {
        "stage": STAGE,
        "upstream_v20_52_contract_status": V20_52_CONTRACT_PASS,
        "upstream_v20_52_tests_status": "PASS",
        "schema_contract_used": "TRUE",
        "language_policy_used": "TRUE",
        "risk_position_policy_used": "TRUE",
        "manual_approval_policy_used": "TRUE",
        "broker_disabled_policy_used": "TRUE",
        "audit_contract_used": "TRUE",
        "research_packet_used": "TRUE",
        "candidate_rows_reviewed": "50",
        "schema_fields_reviewed": "17",
        "dry_run_rows_created": "50",
        "required_fields_mapped": "15",
        "required_fields_pending_future_gate": "2",
        "blocker_count": "0",
        "warning_count": "0",
        "schema_dry_run_status": SCHEMA_DRY_RUN_PASS,
        "next_recommended_stage": NEXT_STAGE,
    }
    for key, expected in expected_summary.items():
        assert_true(clean(row.get(key)) == expected, f"Summary {key} expected {expected}, got {clean(row.get(key))}")
    for key in SUMMARY_FALSE_FIELDS:
        assert_true(clean(row.get(key)) == "FALSE", f"Summary {key} must be FALSE")

    assert_true(flags.get("STATUS") == WRAPPER_PASS, f"READ_FIRST STATUS expected {WRAPPER_PASS}, got {flags.get('STATUS')}")
    assert_true(flags.get("SCHEMA_DRY_RUN_GATE_STATUS") == SCHEMA_DRY_RUN_PASS, "READ_FIRST schema dry-run gate status mismatch")
    assert_true(flags.get("DECISION") == DECISION_PASS, "READ_FIRST decision mismatch")

    expected_next = {
        "stage": STAGE,
        "decision": DECISION_PASS,
        "schema_dry_run_status": SCHEMA_DRY_RUN_PASS,
        "schema_dry_run_created": "TRUE",
        "official_recommendation_created_in_this_stage": "FALSE",
        "official_recommendation_label_assigned": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": "0",
        "warning_count": "0",
        "next_recommended_stage": NEXT_STAGE,
    }
    for key, expected in expected_next.items():
        assert_true(clean(next_row.get(key)) == expected, f"Next-step {key} expected {expected}, got {clean(next_row.get(key))}")


def test_upstream_validation() -> None:
    rows = assert_columns(OUT_UPSTREAM, {"validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    assert_true(len(rows) == 50, f"Upstream validation expected 50 rows, got {len(rows)}")
    blocked = [row for row in rows if clean(row.get("validation_status")) != "PASS" or clean(row.get("blocker_reason"))]
    assert_true(not blocked, f"Upstream validation has blocked rows: {blocked[:3]}")
    items = by_key(rows, "validation_item")
    expected = {
        "v20_52_contract_gate_status": V20_52_CONTRACT_PASS,
        "v20_52_tests_status": "PASS",
        "v20_52_official_output_schema_contract_rows": "17",
        "v20_52_language_policy_forbidden_rows": "10",
        "v20_52_language_policy_safe_rows": "7",
        "v20_52_broker_disabled_pass_rows": "8",
    }
    for key, expected_actual in expected.items():
        assert_true(key in items, f"Missing upstream validation item: {key}")
        assert_true(clean(items[key].get("actual_value")) == expected_actual, f"{key} expected actual {expected_actual}, got {clean(items[key].get('actual_value'))}")


def test_mapping_and_dry_rows() -> None:
    mapping = assert_columns(OUT_MAPPING, {"field_name", "required_flag", "source_mapping_status", "pending_future_gate_flag", "dry_run_validation_status"})
    assert_true(len(mapping) == 17, f"Schema mapping expected 17 rows, got {len(mapping)}")
    assert_true(sum(1 for row in mapping if clean(row.get("pending_future_gate_flag")) == "FALSE" and clean(row.get("dry_run_validation_status")) == "PASS") == 15, "Mapped required field count mismatch")
    assert_true(sum(1 for row in mapping if clean(row.get("pending_future_gate_flag")) == "TRUE") == 2, "Pending future-gate field count mismatch")
    mapping_by_field = by_key(mapping, "field_name")
    assert_true(clean(mapping_by_field["official_recommendation_label"].get("source_mapping_status")) in {"PLACEHOLDER_NOT_ASSIGNED", "PENDING_FUTURE_GATE"}, "official_recommendation_label must not be assigned")
    assert_true(clean(mapping_by_field["broker_execution_allowed"].get("dry_run_value_policy")) == "FALSE", "broker_execution_allowed must map to FALSE")
    assert_true(clean(mapping_by_field["official_trading_allowed"].get("dry_run_value_policy")) == "FALSE", "official_trading_allowed must map to FALSE")

    dry_rows = assert_columns(OUT_DRY_ROWS, {"dry_run_row_id", "source_v20_47_run_id", "official_recommendation_label", "schema_dry_run_only", "manual_approval_required", "blocker_reason"})
    assert_true(len(dry_rows) == 50, f"Dry-run row count expected 50, got {len(dry_rows)}")
    for row in dry_rows:
        assert_true(clean(row.get("source_v20_47_run_id")) == "V20_47_20260604T114058Z", "Dry-run row run_id mismatch")
        assert_true(clean(row.get("official_recommendation_label")) == "NOT_ASSIGNED_DRY_RUN", "Dry-run row assigned recommendation label")
        assert_true(clean(row.get("recommendation_confidence_band")) == "NOT_ASSIGNED_DRY_RUN", "Dry-run row assigned confidence band")
        assert_true(clean(row.get("manual_approval_required")) == "TRUE", "manual_approval_required must be TRUE")
        assert_true(clean(row.get("schema_dry_run_only")) == "TRUE", "schema_dry_run_only must be TRUE")
        assert_true(not clean(row.get("blocker_reason")), "Dry-run row must not have blocker")
        for key in DRY_ROW_FALSE_FIELDS:
            assert_true(clean(row.get(key)) == "FALSE", f"Dry-run row {key} must be FALSE")


def test_language_policy_binding_and_safety() -> None:
    language = assert_columns(OUT_LANGUAGE, {"validation_scope", "actionable_instruction_found", "validation_status", "blocker_reason"})
    assert_true(len(language) == 5, f"Language validation expected 5 rows, got {len(language)}")
    for row in language:
        assert_true(clean(row.get("validation_status")) == "PASS", f"Language validation {row.get('validation_scope')} must PASS")
        assert_true(clean(row.get("actionable_instruction_found")) == "FALSE", f"Language validation {row.get('validation_scope')} found actionable instruction")
        assert_true(not clean(row.get("blocker_reason")), f"Language validation {row.get('validation_scope')} unexpectedly blocked")

    binding = assert_columns(OUT_BINDING, {"policy_area", "binding_status", "blocker_reason"})
    counts: dict[str, int] = {}
    for row in binding:
        status = clean(row.get("binding_status"))
        assert_true(status in {"PASS", "PENDING_FUTURE_GATE"}, f"Unexpected binding status: {status}")
        assert_true(not clean(row.get("blocker_reason")), f"Policy binding {row.get('policy_area')} unexpectedly blocked")
        counts[status] = counts.get(status, 0) + 1
    assert_true(counts.get("PASS") == 6, f"Policy binding PASS expected 6, got {counts.get('PASS')}")
    assert_true(counts.get("PENDING_FUTURE_GATE") == 1, f"Policy binding PENDING_FUTURE_GATE expected 1, got {counts.get('PENDING_FUTURE_GATE')}")

    safety = assert_columns(OUT_SAFETY, {"safety_boundary", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    assert_true(len(safety) == 20, f"Safety validation expected 20 rows, got {len(safety)}")
    safety_by_name = by_key(safety, "safety_boundary")
    assert_true(set(SAFETY_EXPECTED) <= set(safety_by_name), f"Missing safety rows: {sorted(set(SAFETY_EXPECTED) - set(safety_by_name))}")
    for key, expected in SAFETY_EXPECTED.items():
        row = safety_by_name[key]
        assert_true(clean(row.get("expected_value")) == expected, f"Safety {key} expected_value mismatch")
        assert_true(clean(row.get("actual_value")) == expected, f"Safety {key} actual_value mismatch")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Safety {key} must PASS")
        assert_true(not clean(row.get("blocker_reason")), f"Safety {key} unexpectedly blocked")


def test_action_boundary() -> None:
    actions = assert_columns(OUT_ACTION, {"boundary_name", "allowed_flag", "blocker_reason"})
    false_boundaries = {
        "official_recommendation_generation_allowed_in_this_stage",
        "official_recommendation_label_assignment_allowed",
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
    action_by_name = by_key(actions, "boundary_name")
    for key in false_boundaries:
        assert_true(key in action_by_name, f"Missing action boundary: {key}")
        assert_true(clean(action_by_name[key].get("allowed_flag")) == "FALSE", f"Action boundary {key} must be FALSE")


def test_static_safety_scans() -> None:
    py_files = [PROD_SCRIPT, TEST_SCRIPT]
    forbidden_imports = {"yfinance", "requests", "urllib", "httpx", "alpaca_trade_api", "ibapi", "ccxt"}
    forbidden_calls = {"download", "submit_order", "place_order", "buy", "sell", "hold"}
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bad = [alias.name for alias in node.names if alias.name.split(".")[0] in forbidden_imports]
                assert_true(not bad, f"{path.name} has forbidden imports: {bad}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert_true(node.module.split(".")[0] not in forbidden_imports, f"{path.name} imports from forbidden module {node.module}")
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert_true(name.lower() not in forbidden_calls, f"{path.name} has forbidden executable call: {name}")

    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    wrapper_forbidden = ["import yfinance", "from yfinance", "submit_order", "place_order", "alpaca", "ibapi", "ccxt", "outputs/v21", "outputs\\v21", "outputs/v19_21", "outputs\\v19_21", "outputs/v19/v19_21", "outputs\\v19\\v19_21"]
    for term in wrapper_forbidden:
        assert_true(term not in wrapper_text, f"Wrapper contains forbidden executable/path text: {term}")

    forbidden_paths = [ROOT / "outputs" / "v21", ROOT / "outputs" / "v19_21", ROOT / "outputs" / "v19" / "V19_21"]
    existing = [str(path) for path in forbidden_paths if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")


def main() -> int:
    tests = [
        assert_required_outputs,
        test_summary_and_next_step,
        test_upstream_validation,
        test_mapping_and_dry_rows,
        test_language_policy_binding_and_safety,
        test_action_boundary,
        test_static_safety_scans,
    ]
    failures: list[str] = []
    try:
        for test in tests:
            try:
                test()
            except Exception as exc:
                failures.append(f"{test.__name__}: {exc}")
    finally:
        cleanup_pycache()
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
