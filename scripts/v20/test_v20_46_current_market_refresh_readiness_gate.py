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

PASS_STATUS = "PASS_V20_46_TESTS"
STAGE = "V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE"
READY_STATUS = "READY_FOR_CONTROLLED_REFRESH_STAGE"
NEXT_STAGE = "V20.46_FORMAL_TESTS"
CONTROLLED_REFRESH_STAGE = "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION"

REQUIRED_FILES = [
    CONSOLIDATION / "V20_46_CURRENT_MARKET_REFRESH_READINESS_SUMMARY.csv",
    CONSOLIDATION / "V20_46_UPSTREAM_V20_45_VALIDATION.csv",
    CONSOLIDATION / "V20_46_REFRESH_SOURCE_ARCHITECTURE_REVIEW.csv",
    CONSOLIDATION / "V20_46_CONTROLLED_REFRESH_REQUIREMENTS.csv",
    CONSOLIDATION / "V20_46_REFRESH_SCOPE_DECISION.csv",
    CONSOLIDATION / "V20_46_REFRESH_SAFETY_BOUNDARY.csv",
    CONSOLIDATION / "V20_46_CANDIDATE_REFRESH_UNIVERSE.csv",
    CONSOLIDATION / "V20_46_SOURCE_AUDIT.csv",
    CONSOLIDATION / "V20_46_NEXT_STEP_DECISION.csv",
    READ_CENTER / "V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE_REPORT.md",
    READ_CENTER / "V20_CURRENT_MARKET_REFRESH_READINESS_GATE.md",
    OPS / "V20_46_READ_FIRST.txt",
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_45_run_status",
    "upstream_v20_45_tests_status",
    "candidate_refresh_universe_status",
    "candidate_refresh_universe_path",
    "candidate_refresh_ticker_count",
    "candidate_refresh_source_artifact",
    "v20_45_report_ready",
    "v20_45_research_only_status",
    "current_market_refresh_needed",
    "yahoo_runtime_architecture_detected",
    "yahoo_cache_certification_architecture_detected",
    "historical_cache_architecture_detected",
    "refresh_allowed_in_this_stage",
    "provider_network_execution_used",
    "broker_order_execution_used",
    "official_recommendation_allowed",
    "official_trading_allowed",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "blocker_count",
    "warning_count",
    "readiness_status",
    "next_recommended_stage",
}

CANDIDATE_COLUMNS = {
    "ticker",
    "universe_role",
    "source_stage",
    "source_rank",
    "source_rank_or_score",
    "source_artifact",
    "source_row_count",
    "selection_rule",
    "candidate_refresh_universe_cap",
    "requested_for_refresh",
    "benchmark_flag",
    "candidate_flag",
    "duplicate_removed_flag",
    "research_only",
    "official_decision_impact",
}

SOURCE_AUDIT_COLUMNS = {
    "source_artifact",
    "source_type",
    "source_exists",
    "source_row_count",
    "source_field_count",
    "accepted_ticker_count",
    "duplicate_ticker_count",
    "invalid_ticker_count",
    "selection_rule",
    "candidate_refresh_universe_path",
    "candidate_refresh_universe_status",
    "blocker_reason",
    "fabricated_ticker_rows",
    "manual_ticker_additions",
    "research_only",
}

V45_VALIDATION_COLUMNS = {
    "validation_item",
    "source_path",
    "expected_value",
    "actual_value",
    "validation_status",
    "blocker_reason",
}

ARCH_COLUMNS = {
    "architecture_component",
    "file_or_directory_path",
    "detected_flag",
    "intended_future_use",
    "allowed_in_v20_46",
    "allowed_in_v20_47_candidate",
    "risk_notes",
    "blocker_reason",
}

REQ_COLUMNS = {
    "requirement_id",
    "requirement_name",
    "required_flag",
    "requirement_status",
    "applies_to_stage",
    "rationale",
    "blocker_if_missing",
}

SCOPE_COLUMNS = {
    "scope_item",
    "allowed_for_v20_47",
    "required_for_v20_47",
    "blocked_in_v20_46",
    "output_class",
    "notes",
}

SAFETY_COLUMNS = {
    "safety_boundary",
    "expected_value",
    "actual_value",
    "validation_status",
    "evidence",
    "blocker_reason",
}

NEXT_COLUMNS = {
    "stage",
    "decision",
    "readiness_status",
    "controlled_refresh_stage_allowed_next",
    "refresh_executed_in_this_stage",
    "provider_refresh_allowed_next_stage",
    "broker_execution_allowed_next_stage",
    "official_recommendation_allowed_next_stage",
    "official_trading_allowed_next_stage",
    "formal_tests_required_next",
    "blocker_count",
    "warning_count",
    "next_recommended_stage",
}

REQUIRED_V45_VALIDATIONS = {
    "v20_45_run_summary_exists_non_empty",
    "v20_45_next_step_exists_non_empty",
    "v20_45_current_alias_exists_non_empty",
    "v20_45_read_first_exists_non_empty",
    "v20_45_test_script_exists",
    "v20_45_formal_tests_passed",
    "v20_45_report_generation_status",
    "v20_45_decision",
    "v20_45_current_market_refresh_needed",
    "v20_45_official_trading_allowed",
    "v20_45_official_recommendation_allowed",
    "v20_45_provider_network_refresh_used",
    "v20_45_broker_order_execution_used",
    "v20_45_dynamic_weighting_mutated",
    "v20_45_official_ranking_mutated",
}

ARCH_COMPONENTS = {
    "yahoo_runtime_adapter_script",
    "yahoo_cache_certification_script",
    "historical_yahoo_cache_expansion_script",
    "active_outcome_benchmark_inputs",
    "yahoo_cache_directory",
    "random_asof_historical_cache_directory",
    "hash_ledger_or_certification_outputs",
    "read_first_safety_outputs",
    "provider_refresh_execution",
    "broker_order_execution",
}

REQUIRED_REQUIREMENTS = {
    "explicit provider refresh stage separation",
    "yahoo provider access isolated to v20.47 only",
    "no broker/order execution",
    "no official recommendation creation",
    "no official ranking mutation",
    "no dynamic weighting mutation",
    "run_id creation",
    "source hash ledger",
    "cache path isolation",
    "raw cache output",
    "candidate active input staging candidate",
    "certification before active use",
    "stale/pit/leakage checks",
    "failed ticker capture",
    "benchmark refresh support",
    "read_first safety flags",
    "no v21/v19.21 output paths",
    "current operator report refresh handoff to later stage",
    "formal tests required after v20.47",
}

ALLOWED_SCOPE = {
    "current candidate ticker prices",
    "benchmark prices SPY and QQQ",
    "local Yahoo cache",
    "source hash ledger",
    "staged current market source candidate",
    "certification report",
}

BLOCKED_SCOPE = {
    "official recommendation packet",
    "official trading signal",
    "broker order route",
    "real portfolio mutation",
    "dynamic factor weight mutation",
}

SAFETY_CHECKS = {
    "refresh_executed_in_v20_46",
    "yfinance_imported_in_v20_46",
    "provider_network_execution_used",
    "broker_order_execution_used",
    "official_recommendation_allowed",
    "official_trading_allowed",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "real_portfolio_mutated",
    "returns_calculated",
    "scores_recomputed",
    "rankings_recomputed",
    "v21_output_path_created",
    "v19_21_output_path_created",
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


def test_required_outputs_exist_and_non_empty() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required V20.46 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty required V20.46 outputs: {empty}")


def test_readiness_summary() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_CURRENT_MARKET_REFRESH_READINESS_SUMMARY.csv", SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Readiness summary expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "v20_45_research_only_status": "TRUE",
        "current_market_refresh_needed": "TRUE",
        "candidate_refresh_universe_status": "PASS",
        "yahoo_runtime_architecture_detected": "TRUE",
        "yahoo_cache_certification_architecture_detected": "TRUE",
        "historical_cache_architecture_detected": "TRUE",
        "refresh_allowed_in_this_stage": "FALSE",
        "provider_network_execution_used": "FALSE",
        "broker_order_execution_used": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "blocker_count": "0",
        "readiness_status": READY_STATUS,
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {row.get(key)}")
    assert_true(int(clean(row.get("candidate_refresh_ticker_count")) or "0") > 0, "candidate_refresh_ticker_count must be > 0")
    assert_true(clean(row.get("candidate_refresh_source_artifact")), "candidate_refresh_source_artifact must be recorded")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, CONTROLLED_REFRESH_STAGE}, "Unexpected next recommended stage")


def test_upstream_v20_45_validation() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_UPSTREAM_V20_45_VALIDATION.csv", V45_VALIDATION_COLUMNS)
    validation = by_key(rows, "validation_item")
    missing = sorted(REQUIRED_V45_VALIDATIONS - set(validation))
    assert_true(not missing, f"Missing V20.45 validation rows: {missing}")
    for name in REQUIRED_V45_VALIDATIONS - {"v20_45_formal_tests_passed", "v20_45_report_generation_status", "v20_45_decision"}:
        row = validation[name]
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not pass")
        assert_true(not clean(row.get("blocker_reason")), f"{name} has blocker_reason {row.get('blocker_reason')}")


def test_candidate_refresh_universe() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_CANDIDATE_REFRESH_UNIVERSE.csv", CANDIDATE_COLUMNS)
    audit_rows, _ = assert_columns(CONSOLIDATION / "V20_46_SOURCE_AUDIT.csv", SOURCE_AUDIT_COLUMNS)
    assert_true(rows, "candidate refresh universe must contain rows")
    tickers = [clean(row.get("ticker")).upper() for row in rows]
    assert_true(all(tickers), "candidate refresh universe has blank ticker")
    assert_true(len(tickers) == len(set(tickers)), "candidate refresh universe has duplicate tickers")
    assert_true(all(clean(row.get("universe_role")) == "candidate" for row in rows), "candidate refresh universe should contain candidate role rows")
    assert_true(all(clean(row.get("requested_for_refresh")) == "TRUE" for row in rows), "all V20.46 candidates must be requested for refresh")
    assert_true(clean(audit_rows[0].get("candidate_refresh_universe_status")) == "PASS", "source audit must mark candidate universe PASS")
    assert_true(clean(audit_rows[0].get("fabricated_ticker_rows")) == "FALSE", "source audit must not fabricate tickers")
    assert_true(clean(audit_rows[0].get("manual_ticker_additions")) == "FALSE", "source audit must not manually add tickers")


def test_refresh_architecture_review() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_REFRESH_SOURCE_ARCHITECTURE_REVIEW.csv", ARCH_COLUMNS)
    arch = by_key(rows, "architecture_component")
    missing = sorted(ARCH_COMPONENTS - set(arch))
    assert_true(not missing, f"Missing architecture rows: {missing}")
    for name in [
        "yahoo_runtime_adapter_script",
        "yahoo_cache_certification_script",
        "historical_yahoo_cache_expansion_script",
        "hash_ledger_or_certification_outputs",
        "yahoo_cache_directory",
        "active_outcome_benchmark_inputs",
        "random_asof_historical_cache_directory",
    ]:
        assert_true(clean(arch[name].get("detected_flag")) == "TRUE", f"{name} was not detected")
    assert_true(clean(arch["provider_refresh_execution"].get("allowed_in_v20_46")) == "FALSE", "Provider refresh allowed in V20.46")
    assert_true(clean(arch["broker_order_execution"].get("allowed_in_v20_46")) == "FALSE", "Broker execution allowed in V20.46")
    assert_true(clean(arch["provider_refresh_execution"].get("detected_flag")) == "FALSE", "Provider refresh executed/detected in V20.46")
    assert_true(clean(arch["broker_order_execution"].get("detected_flag")) == "FALSE", "Broker execution executed/detected in V20.46")


def test_controlled_refresh_requirements() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_CONTROLLED_REFRESH_REQUIREMENTS.csv", REQ_COLUMNS)
    names = {clean(row.get("requirement_name")).lower() for row in rows}
    missing = sorted(REQUIRED_REQUIREMENTS - names)
    assert_true(not missing, f"Missing controlled refresh requirements: {missing}")
    for row in rows:
        assert_true(clean(row.get("required_flag")) == "TRUE", f"Requirement {row.get('requirement_name')} not marked required")
        assert_true(clean(row.get("blocker_if_missing")) == "TRUE", f"Requirement {row.get('requirement_name')} not blocker_if_missing")


def test_refresh_scope_decision() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_REFRESH_SCOPE_DECISION.csv", SCOPE_COLUMNS)
    scope = by_key(rows, "scope_item")
    missing = sorted((ALLOWED_SCOPE | BLOCKED_SCOPE) - set(scope))
    assert_true(not missing, f"Missing scope rows: {missing}")
    for name in ALLOWED_SCOPE:
        assert_true(clean(scope[name].get("allowed_for_v20_47")) == "TRUE", f"{name} not allowed for V20.47")
    for name in BLOCKED_SCOPE:
        assert_true(clean(scope[name].get("allowed_for_v20_47")) == "FALSE", f"{name} unexpectedly allowed for V20.47")
    for name, row in scope.items():
        assert_true(clean(row.get("blocked_in_v20_46")) == "TRUE", f"{name} not blocked in V20.46")


def test_safety_boundary() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_REFRESH_SAFETY_BOUNDARY.csv", SAFETY_COLUMNS)
    safety = by_key(rows, "safety_boundary")
    missing = sorted(SAFETY_CHECKS - set(safety))
    assert_true(not missing, f"Missing safety boundary rows: {missing}")
    for name in SAFETY_CHECKS:
        row = safety[name]
        assert_true(clean(row.get("expected_value")) == "FALSE", f"{name} expected_value is not FALSE")
        assert_true(clean(row.get("actual_value")) == "FALSE", f"{name} actual_value is not FALSE")
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not pass")


def test_next_step_decision() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_46_NEXT_STEP_DECISION.csv", NEXT_COLUMNS)
    assert_true(len(rows) == 1, f"Next-step decision expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "decision": "PASS_READY_FOR_CONTROLLED_CURRENT_MARKET_REFRESH_STAGE",
        "readiness_status": READY_STATUS,
        "controlled_refresh_stage_allowed_next": "TRUE",
        "refresh_executed_in_this_stage": "FALSE",
        "provider_refresh_allowed_next_stage": "TRUE",
        "broker_execution_allowed_next_stage": "FALSE",
        "official_recommendation_allowed_next_stage": "FALSE",
        "official_trading_allowed_next_stage": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, CONTROLLED_REFRESH_STAGE}, "Unexpected next recommended stage")


def test_read_center_report() -> None:
    path = READ_CENTER / "V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE_REPORT.md"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    required_phrases = [
        "v20.46",
        "gate-only",
        "current market refresh",
        "v20.46 did not refresh providers",
        "did not use the yahoo provider package",
        "broker routes",
        "did not generate official recommendations",
        "trading signals",
        "current returns, scores, rankings",
        "dynamic factor weights",
        "controlled refresh requirements",
        "v20.47 allowed scope",
        "next recommended stage",
    ]
    for phrase in required_phrases:
        assert_true(phrase in lower, f"Report missing phrase: {phrase}")


def test_current_alias() -> None:
    path = READ_CENTER / "V20_CURRENT_MARKET_REFRESH_READINESS_GATE.md"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    assert_true(path.stat().st_size > 0, "Current alias report is empty")
    assert_true(STAGE in text, "Current alias does not correspond to V20.46")
    assert_true("readiness gate" in lower and "did not refresh providers" in lower, "Current alias missing readiness/no-refresh language")
    assert_true("ready for official trading" not in lower, "Current alias claims official trading readiness")
    assert_true("ready for official recommendation" not in lower, "Current alias claims official recommendation readiness")


def test_read_first() -> None:
    path = OPS / "V20_46_READ_FIRST.txt"
    flags = read_flags(path)
    assert_true(path.stat().st_size > 0, "READ_FIRST is empty")
    expected = {
        "STAGE_NAME": STAGE,
        "GATE_ONLY": "TRUE",
        "REPORTING_ONLY": "TRUE",
        "CANDIDATE_REFRESH_UNIVERSE_STATUS": "PASS",
        "CURRENT_MARKET_REFRESH_NEEDED": "TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_46": "FALSE",
        "YAHOO_PROVIDER_PACKAGE_IMPORTED_IN_V20_46": "FALSE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "READINESS_STATUS": READY_STATUS,
        "NEXT_RECOMMENDED_STAGE": NEXT_STAGE,
    }
    for key, value in expected.items():
        assert_true(flags.get(key) == value, f"READ_FIRST {key} expected {value}, got {flags.get(key)}")
    assert_true(int(flags.get("CANDIDATE_REFRESH_TICKER_COUNT", "0")) > 0, "READ_FIRST candidate count must be > 0")
    assert_true(clean(flags.get("CANDIDATE_REFRESH_SOURCE_ARTIFACT")), "READ_FIRST missing candidate source artifact")
    assert_true("V20_47_REQUIREMENTS" in flags, "READ_FIRST missing V20.47 controlled refresh requirements")


def python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_static_safety_scans() -> None:
    py_paths = [
        SCRIPT_DIR / "v20_46_current_market_refresh_readiness_gate.py",
        SCRIPT_DIR / "test_v20_46_current_market_refresh_readiness_gate.py",
    ]
    text_paths = [SCRIPT_DIR / "run_v20_46_current_market_refresh_readiness_gate.ps1"]
    executable_patterns = [
        re.compile(r"^\s*(import|from)\s+yfinance\b", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\byfinance\.\w+\s*\(|\byf\.download\s*\(", re.IGNORECASE),
        re.compile(r"\brequests\.(?:get|post|put|delete)\s*\(|\bhttpx\.(?:get|post|put|delete)\s*\(", re.IGNORECASE),
        re.compile(r"\bsubmit_order\s*\(|\bplace_order\s*\(|\bbroker\.(?:buy|sell|order|submit)\s*\(", re.IGNORECASE),
        re.compile(r"\blive_trading\s*=\s*TRUE\b|\bLIVE_TRADING\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\breal_portfolio_mutat(?:e|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_ranking_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_recommendation_(?:created|generated|allowed)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bdynamic_weighting_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\b(calculate_returns|compute_returns|recompute_scores|recompute_rankings|calculate_scores|calculate_rankings)\s*\(", re.IGNORECASE),
    ]
    forbidden_path_parts = [
        ("outputs", "v21"),
        ("outputs", "v19_21"),
        ("outputs", "v19", "V19_21"),
    ]

    for path in py_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in executable_patterns:
            assert_true(not pattern.search(text), f"Forbidden executable logic {pattern.pattern!r} found in {path}")
        if path.name.startswith("v20_46_"):
            for literal in python_string_literals(path):
                normalized = literal.replace("\\", "/")
                parts = tuple(part.lower() for part in normalized.split("/"))
                for forbidden in forbidden_path_parts:
                    expected = tuple(part.lower() for part in forbidden)
                    windows = [tuple(parts[i:i + len(expected)]) for i in range(len(parts))]
                    assert_true(expected not in windows, f"Forbidden output path literal found in {path}: {literal}")

    for path in text_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in executable_patterns:
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
        test_required_outputs_exist_and_non_empty,
        test_readiness_summary,
        test_upstream_v20_45_validation,
        test_candidate_refresh_universe,
        test_refresh_architecture_review,
        test_controlled_refresh_requirements,
        test_refresh_scope_decision,
        test_safety_boundary,
        test_next_step_decision,
        test_read_center_report,
        test_current_alias,
        test_read_first,
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
        print("FAIL_V20_46_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
