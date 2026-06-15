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

PASS_STATUS = "PASS_V20_54_TESTS"
FAIL_STATUS = "FAIL_V20_54_TESTS"
STAGE = "V20.54_USER_READABLE_CURRENT_DECISION_REPORT"
REPORT_PASS = "PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT"
NEXT_STAGE = "V20.55_DAILY_ONE_CLICK_RESEARCH_RUNNER"

PROD_SCRIPT = SCRIPT_DIR / "v20_54_user_readable_current_decision_report.py"
WRAPPER = SCRIPT_DIR / "run_v20_54_user_readable_current_decision_report.ps1"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_54_user_readable_current_decision_report.py"

OUT_SUMMARY = CONSOLIDATION / "V20_54_USER_READABLE_REPORT_SUMMARY.csv"
OUT_CANDIDATE = CONSOLIDATION / "V20_54_USER_READABLE_CANDIDATE_VIEW.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_54_PRIORITY_REVIEW_READABLE_VIEW.csv"
OUT_STANDARD = CONSOLIDATION / "V20_54_STANDARD_REVIEW_READABLE_VIEW.csv"
OUT_FACTOR = CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv"
OUT_ENTRY = CONSOLIDATION / "V20_54_ENTRY_STRATEGY_READABLE_VIEW.csv"
OUT_BENCHMARK = CONSOLIDATION / "V20_54_BENCHMARK_CONTEXT_READABLE_VIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_54_LINEAGE_FRESHNESS_READABLE_VIEW.csv"
OUT_POLICY = CONSOLIDATION / "V20_54_POLICY_LANGUAGE_BOUNDARY_CHECK.csv"
OUT_SAFETY = CONSOLIDATION / "V20_54_SAFETY_BOUNDARY_VALIDATION.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_54_REQUIRED_ARTIFACT_MANIFEST.csv"
REPORT = READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md"
READ_FIRST = OPS / "V20_54_READ_FIRST.txt"

REQUIRED_OUTPUTS = [
    OUT_SUMMARY,
    OUT_CANDIDATE,
    OUT_PRIORITY,
    OUT_STANDARD,
    OUT_FACTOR,
    OUT_ENTRY,
    OUT_BENCHMARK,
    OUT_LINEAGE,
    OUT_POLICY,
    OUT_SAFETY,
    OUT_MANIFEST,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
]

SUMMARY_FALSE_FIELDS = [
    "official_recommendation_created",
    "buy_sell_hold_instruction_created",
    "trading_signal_created",
    "provider_refresh_executed",
    "broker_order_execution_used",
    "returns_calculated",
    "scores_recomputed",
    "rankings_recomputed",
    "factor_weight_mutated",
    "dynamic_weighting_mutated",
    "real_book_mutated",
]


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


def pycache_paths() -> list[Path]:
    return [path for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]


def cleanup_pycache() -> None:
    for path in pycache_paths():
        shutil.rmtree(path, ignore_errors=True)


def assert_columns(path: Path, required: set[str]) -> list[dict[str, str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing required columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows


def assert_required_outputs() -> None:
    missing = [str(path) for path in REQUIRED_OUTPUTS if not path.exists()]
    assert_true(not missing, f"Missing V20.54 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_OUTPUTS if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty V20.54 outputs: {empty}")
    assert_true(PROD_SCRIPT.exists(), "V20.54 production script missing")
    assert_true(WRAPPER.exists(), "V20.54 wrapper missing")


def forbidden_language_hits(text: str) -> list[str]:
    lowered = text.lower()
    allowed_patterns = [
        r"not_a_trading_signal",
        r"no_broker_action",
        r"no_order_execution",
        r"this_is_not_an_official_recommendation=true",
        r"this_is_not_a_trading_signal=true",
        r"not an official recommendation",
        r"not a trading signal",
        r"no trading signal",
        r"no trading signals",
        r"no official recommendation generation",
        r"does not create buy/sell/hold instructions",
        r"buy_sell_hold_instructions_created=false",
        r"no buy/sell/hold instruction",
        r"no buy/sell/hold instructions",
        r"no broker action",
        r"no order execution",
        r"no broker/order execution path",
        r"no broker/order execution",
        r"manual review is required before any real-world action",
        r"broker/order systems",
        r"broker_order_system_connected=false",
        r"broker_order_execution_used=false",
        r"preserved report order",
        r"report order",
    ]
    for pattern in allowed_patterns:
        lowered = re.sub(pattern, "", lowered, flags=re.IGNORECASE)
    forbidden = [
        r"\bstrong buy\b",
        r"\bstrong sell\b",
        r"\bauto trade\b",
        r"\bposition instruction\b",
        r"\bofficial recommendation\b",
        r"\btrading signal\b",
        r"\border\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    hits: list[str] = []
    for pattern in forbidden:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(lowered), match.end() + 35)
            hits.append(lowered[start:end].replace("\n", " "))
    return hits


def test_summary_schema_and_counts() -> None:
    row = first_row(OUT_SUMMARY)
    expected = {
        "stage": STAGE,
        "status": REPORT_PASS,
        "upstream_v20_53_schema_dry_run_status": "PASS_SCHEMA_DRY_RUN_GATE_CREATED",
        "required_artifacts_checked": "24",
        "required_artifacts_passed": "24",
        "candidate_rows_included": "50",
        "priority_review_rows": "20",
        "standard_review_rows": "30",
        "factor_support_rows": "21",
        "entry_strategy_rows": "5",
        "benchmark_context_rows": "2",
        "lineage_freshness_rows": "35",
        "policy_boundary_status": "PASS",
        "safety_boundary_status": "PASS",
        "blocker_count": "0",
        "warning_count": "0",
        "next_recommended_stage": "V20.54_FORMAL_TESTS",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Summary {key} expected {value}, got {clean(row.get(key))}")
    for key in SUMMARY_FALSE_FIELDS:
        assert_true(clean(row.get(key)) == "FALSE", f"Summary {key} must be FALSE")

    assert_columns(OUT_SUMMARY, {"stage", "status", "upstream_v20_53_schema_dry_run_status", "candidate_rows_included", "priority_review_rows", "standard_review_rows", "policy_boundary_status", "safety_boundary_status", "next_recommended_stage"})
    assert_columns(OUT_CANDIDATE, {"ticker", "decision_category", "research_only_status", "safe_human_readable_rationale", "risk_freshness_lineage_notes"})
    assert_true(len(assert_columns(OUT_CANDIDATE, {"ticker"})) == 50, "Candidate view expected 50 rows")
    assert_true(len(assert_columns(OUT_FACTOR, {"factor_id_or_name", "factor_support_summary"})) == 21, "Factor view expected 21 rows")
    assert_true(len(assert_columns(OUT_ENTRY, {"strategy_id_or_name", "entry_strategy_support_summary"})) == 5, "Entry view expected 5 rows")
    assert_true(len(assert_columns(OUT_BENCHMARK, {"benchmark_ticker", "research_context_summary"})) == 2, "Benchmark view expected 2 rows")
    assert_true(len(assert_columns(OUT_LINEAGE, {"source_name_or_input_name", "freshness_status", "lineage_status"})) == 35, "Lineage view expected 35 rows")


def test_priority_standard_views() -> None:
    priority = assert_columns(OUT_PRIORITY, {"ticker", "decision_category", "safe_human_readable_rationale"})
    standard = assert_columns(OUT_STANDARD, {"ticker", "decision_category", "safe_human_readable_rationale"})
    assert_true(len(priority) == 20, f"Priority view expected 20 rows, got {len(priority)}")
    assert_true(len(standard) == 30, f"Standard view expected 30 rows, got {len(standard)}")
    for row in priority:
        assert_true(clean(row.get("decision_category")) == "PRIORITY_REVIEW", f"Priority row has category {row.get('decision_category')}")
    for row in standard:
        assert_true(clean(row.get("decision_category")) == "STANDARD_REVIEW", f"Standard row has category {row.get('decision_category')}")
    for path in [OUT_PRIORITY, OUT_STANDARD]:
        hits = forbidden_language_hits(path.read_text(encoding="utf-8"))
        assert_true(not hits, f"Forbidden actionable language in {path.name}: {hits[:3]}")


def test_policy_and_safety_boundaries() -> None:
    policy = assert_columns(OUT_POLICY, {"checked_artifact", "forbidden_actionable_phrase_count", "research_only_language_confirmed", "validation_status", "blocker_reason"})
    assert_true(len(policy) == 10, f"Policy boundary expected 10 rows, got {len(policy)}")
    for row in policy:
        assert_true(clean(row.get("validation_status")) == "PASS", f"Policy boundary {row.get('checked_artifact')} must PASS")
        assert_true(clean(row.get("forbidden_actionable_phrase_count")) == "0", f"Policy boundary {row.get('checked_artifact')} found forbidden terms")
        assert_true(clean(row.get("research_only_language_confirmed")) == "TRUE", f"Policy boundary {row.get('checked_artifact')} must confirm research-only language")
        assert_true(not clean(row.get("blocker_reason")), f"Policy boundary {row.get('checked_artifact')} unexpectedly blocked")

    safety = assert_columns(OUT_SAFETY, {"safety_check", "expected_value", "actual_value", "validation_status", "blocker_reason"})
    assert_true(len(safety) == 15, f"Safety boundary expected 15 rows, got {len(safety)}")
    for row in safety:
        assert_true(clean(row.get("validation_status")) == "PASS", f"Safety {row.get('safety_check')} must PASS")
        assert_true(clean(row.get("expected_value")) == clean(row.get("actual_value")), f"Safety {row.get('safety_check')} expected/actual mismatch")
        assert_true(not clean(row.get("blocker_reason")), f"Safety {row.get('safety_check')} unexpectedly blocked")

    manifest = assert_columns(OUT_MANIFEST, {"artifact_role", "artifact_path", "exists_non_empty", "validation_status", "blocker_reason"})
    assert_true(len(manifest) == 24, f"Manifest expected 24 rows, got {len(manifest)}")
    for row in manifest:
        assert_true(clean(row.get("exists_non_empty")) == "TRUE", f"Manifest artifact missing: {row.get('artifact_path')}")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Manifest artifact not PASS: {row.get('artifact_path')}")


def test_forbidden_language_and_safe_language() -> None:
    scan_paths = [
        OUT_CANDIDATE,
        OUT_PRIORITY,
        OUT_STANDARD,
        OUT_FACTOR,
        OUT_ENTRY,
        OUT_BENCHMARK,
        OUT_LINEAGE,
        REPORT,
        CURRENT_REPORT,
        READ_FIRST,
    ]
    for path in scan_paths:
        hits = forbidden_language_hits(path.read_text(encoding="utf-8"))
        assert_true(not hits, f"Forbidden actionable language in {path.name}: {hits[:3]}")

    combined = "\n".join([REPORT.read_text(encoding="utf-8"), READ_FIRST.read_text(encoding="utf-8")]).lower()
    required_safe = [
        "research-only",
        "manual_review_required",
        "not_a_trading_signal",
        "no_broker_action",
        "no_order_execution",
        "not an official recommendation",
        "does not create buy/sell/hold instructions",
    ]
    for phrase in required_safe:
        assert_true(phrase in combined, f"Missing safe language phrase: {phrase}")


def test_read_center_alias_and_sections() -> None:
    report = REPORT.read_text(encoding="utf-8")
    alias = CURRENT_REPORT.read_text(encoding="utf-8")
    assert_true(report == alias, "Current alias must match primary report content")
    lower = report.lower()
    sections = [
        "stage status",
        "upstream artifacts used",
        "current run / refreshed price context",
        "candidate overview",
        "priority review candidates",
        "standard review candidates",
        "factor support summary",
        "entry strategy support summary",
        "benchmark context",
        "lineage and freshness",
        "policy/language boundary",
        "safety boundary",
        "what this report is allowed to mean",
        "what this report is not allowed to mean",
        "recommended next gated stage",
    ]
    for section in sections:
        assert_true(section in lower, f"Report missing section: {section}")
    assert_true(STAGE.lower() in lower, "Report missing V20.54 stage marker")


def test_read_first() -> None:
    text = READ_FIRST.read_text(encoding="utf-8").lower()
    required = [
        "user_readable_research_only_current_decision_report",
        "this_is_not_an_official_recommendation=true",
        "this_is_not_a_trading_signal=true",
        "buy_sell_hold_instructions_created=false",
        "market_provider_refresh_executed_in_v20_54=false",
        "broker_order_system_connected=false",
        "official_ranking_mutated=false",
        "score_recomputed=false",
        "factor_weight_mutated=false",
        "dynamic_weight_mutated=false",
        "real_book_position_mutated=false",
        "manual_review_required_before_real_world_action=true",
    ]
    for phrase in required:
        assert_true(phrase in text, f"READ_FIRST missing required statement: {phrase}")


def test_static_safety_scans() -> None:
    forbidden_imports = {"yfinance", "requests", "urllib", "httpx", "alpaca_trade_api", "ibapi", "ccxt"}
    forbidden_calls = {"submit_order", "place_order", "create_order", "buy_order", "sell_order", "download"}
    for path in [PROD_SCRIPT, TEST_SCRIPT]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bad = [alias.name for alias in node.names if alias.name.split(".")[0] in forbidden_imports]
                assert_true(not bad, f"{path.name} forbidden imports: {bad}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert_true(node.module.split(".")[0] not in forbidden_imports, f"{path.name} imports forbidden module {node.module}")
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert_true(name.lower() not in forbidden_calls, f"{path.name} forbidden executable call: {name}")

    wrapper_text = WRAPPER.read_text(encoding="utf-8").lower()
    wrapper_forbidden = ["import yfinance", "from yfinance", "submit_order", "place_order", "create_order", "buy_order", "sell_order", "alpaca", "ibapi", "ccxt"]
    for term in wrapper_forbidden:
        assert_true(term not in wrapper_text, f"Wrapper contains forbidden executable text: {term}")

    forbidden_paths = [ROOT / "outputs" / "v21", ROOT / "outputs" / "v19_21", ROOT / "outputs" / "v19" / "V19_21"]
    existing = [str(path) for path in forbidden_paths if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")


def main() -> int:
    tests = [
        assert_required_outputs,
        test_summary_schema_and_counts,
        test_priority_standard_views,
        test_policy_and_safety_boundaries,
        test_forbidden_language_and_safe_language,
        test_read_center_alias_and_sections,
        test_read_first,
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
