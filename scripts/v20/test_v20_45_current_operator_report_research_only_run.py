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

PASS_STATUS = "PASS_V20_45_TESTS"
STAGE = "V20.45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
NEXT_STAGE = "V20.45_FORMAL_TESTS"

REQUIRED_FILES = [
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_REPORT_RUN_SUMMARY.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ENTRY_STRATEGY_VIEW.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ACTION_BOUNDARY.csv",
    CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv",
    READ_CENTER / "V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN_REPORT.md",
    READ_CENTER / "V20_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY.md",
    OPS / "V20_45_READ_FIRST.txt",
]

SUMMARY_COLUMNS = {
    "stage",
    "upstream_v20_43_status",
    "upstream_v20_44_status",
    "report_generation_status",
    "research_only_status",
    "source_snapshot_status",
    "current_market_refresh_needed_before_real_use",
    "candidate_rows_included",
    "factor_support_rows_included",
    "entry_strategy_rows_included",
    "lineage_freshness_rows_included",
    "blocker_count",
    "warning_count",
    "official_trading_allowed",
    "official_recommendation_allowed",
    "official_ranking_mutated",
    "dynamic_weighting_mutated",
    "provider_network_refresh_used",
    "broker_order_execution_used",
    "next_recommended_stage",
}

CANDIDATE_COLUMNS = {
    "report_rank",
    "ticker_or_candidate_id",
    "display_name_or_ticker",
    "source_rank_or_score",
    "research_category",
    "report_section",
    "source_contract",
    "source_lineage",
    "freshness_status",
    "operator_research_note",
    "research_only_flag",
    "official_recommendation_flag",
}

FACTOR_COLUMNS = {
    "factor_id_or_name",
    "factor_category",
    "pit_status",
    "support_status",
    "report_section",
    "factor_research_interpretation",
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
    "blocker_count",
    "warning_count",
    "current_market_refresh_needed",
    "safe_for_research_report",
    "safe_for_official_recommendation",
    "safe_for_trading",
}

BOUNDARY_COLUMNS = {"boundary_name", "allowed_flag", "evidence", "blocker_reason"}

NEXT_COLUMNS = {
    "stage",
    "decision",
    "report_created",
    "research_only_report_ready",
    "current_market_refresh_needed_before_real_use",
    "formal_tests_required_next",
    "provider_refresh_stage_required",
    "official_recommendation_allowed",
    "official_trading_allowed",
    "blocker_count",
    "warning_count",
    "next_recommended_stage",
}

TRUE_BOUNDARIES = {
    "research_report_generation_allowed",
    "candidate_review_allowed",
    "factor_review_allowed",
    "entry_strategy_review_allowed",
}

FALSE_BOUNDARIES = {
    "official_buy_sell_hold_recommendation_allowed",
    "live_trading_allowed",
    "broker_order_execution_allowed",
    "official_ranking_mutation_allowed",
    "dynamic_weighting_mutation_allowed",
    "provider_network_refresh_allowed_in_this_stage",
    "real_portfolio_mutation_allowed",
}


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


def assert_columns(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing required columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows, columns


def row_text(row: dict[str, str]) -> str:
    return " ".join(clean(value).lower() for value in row.values())


def test_required_outputs_exist_and_non_empty() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.exists()]
    assert_true(not missing, f"Missing required V20.45 outputs: {missing}")
    empty = [str(path) for path in REQUIRED_FILES if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty required V20.45 outputs: {empty}")


def test_run_summary() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_REPORT_RUN_SUMMARY.csv", SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Run summary expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "report_generation_status": "PASS",
        "research_only_status": "TRUE",
        "current_market_refresh_needed_before_real_use": "TRUE",
        "candidate_rows_included": "50",
        "factor_support_rows_included": "21",
        "entry_strategy_rows_included": "5",
        "lineage_freshness_rows_included": "27",
        "blocker_count": "0",
        "official_trading_allowed": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "provider_network_refresh_used": "FALSE",
        "broker_order_execution_used": "FALSE",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Run summary {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("upstream_v20_43_status")) == "PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN", "Unexpected V20.43 status")
    assert_true(clean(row.get("upstream_v20_44_status")) == "ACCEPTED_WITH_RESEARCH_ONLY_LIMITS", "Unexpected V20.44 status")


def test_candidate_research_view() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_CANDIDATE_RESEARCH_VIEW.csv", CANDIDATE_COLUMNS)
    assert_true(len(rows) == 50, f"Candidate view expected 50 rows, got {len(rows)}")
    forbidden = [
        re.compile(r"\bofficial\s+(buy|sell|hold)\b", re.IGNORECASE),
        re.compile(r"\b(buy|sell|hold)\s+recommendation\b", re.IGNORECASE),
        re.compile(r"\blive\s+trade\b|\btrading-authorized\b", re.IGNORECASE),
    ]
    for idx, row in enumerate(rows, start=1):
        assert_true(clean(row.get("research_only_flag")) == "TRUE", f"Candidate row {idx} research_only_flag is not TRUE")
        assert_true(clean(row.get("official_recommendation_flag")) == "FALSE", f"Candidate row {idx} official_recommendation_flag is not FALSE")
        text = row_text(row)
        for pattern in forbidden:
            assert_true(not pattern.search(text), f"Candidate row {idx} contains forbidden recommendation or live authorization language")


def test_factor_support_view() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv", FACTOR_COLUMNS)
    assert_true(len(rows) == 21, f"Factor support view expected 21 rows, got {len(rows)}")
    for idx, row in enumerate(rows, start=1):
        assert_true(clean(row.get("dynamic_weighting_mutated")) == "FALSE", f"Factor row {idx} mutated dynamic weighting")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", f"Factor row {idx} research_only_flag is not TRUE")
        assert_true(clean(row.get("included_in_official_weight_flag")) == "FALSE", f"Factor row {idx} is included in official weights")


def test_entry_strategy_view() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ENTRY_STRATEGY_VIEW.csv", ENTRY_COLUMNS)
    assert_true(len(rows) == 5, f"Entry strategy view expected 5 rows, got {len(rows)}")
    for idx, row in enumerate(rows, start=1):
        assert_true(clean(row.get("allowed_in_research_report")) == "TRUE", f"Entry row {idx} is not allowed in research report")
        assert_true(clean(row.get("allowed_for_live_trading")) == "FALSE", f"Entry row {idx} allows live trading")
        assert_true(clean(row.get("broker_execution_enabled")) == "FALSE", f"Entry row {idx} enables broker execution")
        assert_true(clean(row.get("research_only_flag")) == "TRUE", f"Entry row {idx} research_only_flag is not TRUE")


def test_lineage_freshness_view() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_LINEAGE_FRESHNESS_VIEW.csv", LINEAGE_COLUMNS)
    assert_true(len(rows) == 27, f"Lineage/freshness view expected 27 rows, got {len(rows)}")
    refresh_values = {clean(row.get("current_market_refresh_needed")) for row in rows}
    assert_true(refresh_values <= {"TRUE", "CONDITIONAL"}, f"Unexpected refresh-needed values: {sorted(refresh_values)}")
    assert_true("TRUE" in refresh_values or "CONDITIONAL" in refresh_values, "Lineage view does not warn about current market refresh")
    for idx, row in enumerate(rows, start=1):
        blocker_count = as_int(row.get("blocker_count"))
        if blocker_count == 0:
            assert_true(clean(row.get("safe_for_research_report")) == "TRUE", f"Lineage row {idx} not safe for research despite blocker_count 0")
        assert_true(clean(row.get("safe_for_official_recommendation")) == "FALSE", f"Lineage row {idx} allows official recommendation")
        assert_true(clean(row.get("safe_for_trading")) == "FALSE", f"Lineage row {idx} allows trading")


def test_action_boundary() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_ACTION_BOUNDARY.csv", BOUNDARY_COLUMNS)
    by_name = {clean(row.get("boundary_name")): row for row in rows}
    missing = sorted((TRUE_BOUNDARIES | FALSE_BOUNDARIES) - set(by_name))
    assert_true(not missing, f"Action boundary missing checks: {missing}")
    for name in TRUE_BOUNDARIES:
        assert_true(clean(by_name[name].get("allowed_flag")) == "TRUE", f"Boundary {name} expected TRUE")
    for name in FALSE_BOUNDARIES:
        assert_true(clean(by_name[name].get("allowed_flag")) == "FALSE", f"Boundary {name} expected FALSE")


def test_next_step_decision() -> None:
    rows, _ = assert_columns(CONSOLIDATION / "V20_45_CURRENT_OPERATOR_NEXT_STEP_DECISION.csv", NEXT_COLUMNS)
    assert_true(len(rows) == 1, f"Next-step decision expected 1 row, got {len(rows)}")
    row = rows[0]
    expected = {
        "stage": STAGE,
        "decision": "PASS_RESEARCH_ONLY_CURRENT_OPERATOR_REPORT_CREATED",
        "report_created": "TRUE",
        "research_only_report_ready": "TRUE",
        "current_market_refresh_needed_before_real_use": "TRUE",
        "formal_tests_required_next": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "blocker_count": "0",
    }
    for key, value in expected.items():
        assert_true(clean(row.get(key)) == value, f"Next-step {key} expected {value}, got {row.get(key)}")
    assert_true(clean(row.get("provider_refresh_stage_required")) in {"TRUE", "CONDITIONAL"}, "Provider refresh next-stage requirement must be TRUE or CONDITIONAL")
    assert_true(clean(row.get("next_recommended_stage")) in {NEXT_STAGE, "V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE"}, "Unexpected next recommended stage")


def test_read_center_report() -> None:
    path = READ_CENTER / "V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN_REPORT.md"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    required_phrases = [
        "v20.45",
        "research-only",
        "not official recommendations",
        "not trading-authorized",
        "no provider/network refresh",
        "market refresh required before operational use",
        "candidate research view summary",
        "factor support summary",
        "entry strategy readiness summary",
        "lineage and freshness summary",
        "next recommended stage",
    ]
    for phrase in required_phrases:
        assert_true(phrase in lower, f"Report missing phrase: {phrase}")
    broker_order_equivalent = "no broker/order execution" in lower or "no broker or order path is used" in lower
    assert_true(broker_order_equivalent, "Report missing broker/order execution safety statement")
    forbidden = [
        re.compile(r"\bofficial\s+(buy|sell|hold)\b", re.IGNORECASE),
        re.compile(r"\b(buy|sell|hold)\s+recommendation\b", re.IGNORECASE),
    ]
    for pattern in forbidden:
        assert_true(not pattern.search(text), f"Report contains forbidden official recommendation language: {pattern.pattern}")


def test_current_alias() -> None:
    path = READ_CENTER / "V20_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY.md"
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    assert_true(path.stat().st_size > 0, "Current alias report is empty")
    assert_true(STAGE in text, "Current alias does not correspond to V20.45")
    assert_true("research-only" in lower, "Current alias does not clearly say research-only")
    assert_true("ready for official trading" not in lower, "Current alias claims official trading readiness")
    assert_true("ready for official recommendation" not in lower, "Current alias claims official recommendation readiness")


def test_read_first() -> None:
    path = OPS / "V20_45_READ_FIRST.txt"
    flags = read_flags(path)
    assert_true(path.stat().st_size > 0, "READ_FIRST is empty")
    expected = {
        "STAGE_NAME": STAGE,
        "REPORT_GENERATION_ONLY": "TRUE",
        "RESEARCH_ONLY_STATUS": "TRUE",
        "BROKER_ORDER_EXECUTION_USED": "FALSE",
        "PROVIDER_NETWORK_REFRESH_USED": "FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED": "FALSE",
        "OFFICIAL_RANKING_MUTATED": "FALSE",
        "DYNAMIC_WEIGHTING_MUTATED": "FALSE",
        "REAL_PORTFOLIO_MUTATED": "FALSE",
        "CURRENT_MARKET_REFRESH_NEEDED_BEFORE_REAL_USE": "TRUE",
        "NEXT_RECOMMENDED_STAGE": NEXT_STAGE,
    }
    for key, value in expected.items():
        assert_true(flags.get(key) == value, f"READ_FIRST {key} expected {value}, got {flags.get(key)}")


def python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_static_safety_scans() -> None:
    py_paths = [
        SCRIPT_DIR / "v20_45_current_operator_report_research_only_run.py",
        SCRIPT_DIR / "test_v20_45_current_operator_report_research_only_run.py",
    ]
    text_paths = [
        SCRIPT_DIR / "run_v20_45_current_operator_report_research_only_run.ps1",
    ]
    executable_patterns = [
        re.compile(r"\bimport\s+yfinance\b|\bfrom\s+yfinance\b", re.IGNORECASE),
        re.compile(r"\byfinance\.\w+\s*\(|\byf\.download\s*\(", re.IGNORECASE),
        re.compile(r"\brequests\.(?:get|post|put|delete)\s*\(|\bhttpx\.(?:get|post|put|delete)\s*\(", re.IGNORECASE),
        re.compile(r"\bsubmit_order\s*\(|\bplace_order\s*\(|\bbroker\.(?:buy|sell|order|submit)\s*\(", re.IGNORECASE),
        re.compile(r"\blive_trading\s*=\s*TRUE\b|\bLIVE_TRADING\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\breal_portfolio_mutat(?:e|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_ranking_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bofficial_recommendation_(?:created|generated|allowed)\b\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\bdynamic_weighting_mutat(?:e|ed|ion)\b\s*=\s*TRUE\b", re.IGNORECASE),
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
        if path.name.startswith("v20_45_"):
            literals = python_string_literals(path)
            for literal in literals:
                normalized = literal.replace("\\", "/")
                parts = tuple(part.lower() for part in normalized.split("/"))
                for forbidden in forbidden_path_parts:
                    expected = tuple(part.lower() for part in forbidden)
                    assert_true(expected not in tuple(parts[i:i + len(expected)] for i in range(len(parts))), f"Forbidden output path literal found in {path}: {literal}")

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
        test_run_summary,
        test_candidate_research_view,
        test_factor_support_view,
        test_entry_strategy_view,
        test_lineage_freshness_view,
        test_action_boundary,
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
        print("FAIL_V20_45_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
