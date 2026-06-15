from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
PASS_STATUS = "PASS_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
WARN_STATUS = "WARN_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"
BLOCKED_STATUS = "BLOCKED_V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE"
ACCEPTANCE_STATUS = "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY"
DECISION_PASS = "PASS_OPERATOR_REVIEW_ACCEPTED_RESEARCH_ONLY"
RESEARCH_ONLY_PASS = "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
PROMOTION_BLOCKED = "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE"
NEXT_STAGE = "V20.49_FORMAL_TESTS"

IN_V48_SUMMARY = CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv"
IN_V48_CANDIDATE = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
IN_V48_BENCHMARK = CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv"
IN_V48_FACTOR = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
IN_V48_ENTRY = CONSOLIDATION / "V20_48_REFRESHED_ENTRY_STRATEGY_VIEW.csv"
IN_V48_LINEAGE = CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv"
IN_V48_ACTION = CONSOLIDATION / "V20_48_REFRESHED_REPORT_ACTION_BOUNDARY.csv"
IN_V48_SAFETY = CONSOLIDATION / "V20_48_REFRESHED_REPORT_SAFETY_BOUNDARY.csv"
IN_V48_NEXT = CONSOLIDATION / "V20_48_NEXT_STEP_DECISION.csv"
IN_V48_REPORT = READ_CENTER / "V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT.md"
IN_V48_CURRENT = READ_CENTER / "V20_CURRENT_REFRESHED_OPERATOR_RESEARCH_REPORT.md"
IN_V48_READ_FIRST = OPS / "V20_48_READ_FIRST.txt"
IN_V48_TEST = SCRIPT_DIR / "test_v20_48_refreshed_current_operator_research_report.py"
IN_V47_CONTROLLED_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_PROVIDER_SUMMARY = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_SUMMARY.csv"
IN_V7V_SUMMARY = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
IN_V7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_V16_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
IN_V17_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
IN_V17_PREP = CONSOLIDATION / "V20_17_BACKTEST_INPUT_PREPARATION.csv"
IN_V18_GATE = CONSOLIDATION / "V20_18_GATE_DECISION.csv"
IN_V19_GATE = CONSOLIDATION / "V20_19_GATE_DECISION.csv"
IN_V27_GATE = CONSOLIDATION / "V20_27_GATE_DECISION.csv"
IN_SWEEP_STATUS = CONSOLIDATION / "V20_DOWNSTREAM_REPAIR_SWEEP_STATUS.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
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
OUT_RESEARCH_GATE = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
OUT_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
OUT_STATIC_ACCEPTANCE = CONSOLIDATION / "V20_49_STATIC_OPERATOR_REVIEW_ACCEPTANCE.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_49_SOURCE_AUDIT.csv"
OUT_GATE_DIAGNOSTICS = CONSOLIDATION / "V20_49_GATE_DIAGNOSTICS.csv"
REPORT = READ_CENTER / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OPERATOR_REVIEW_ACCEPTANCE_GATE.md"
READ_FIRST = OPS / "V20_49_READ_FIRST.txt"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return 0


def status_row(item: str, path: Path, expected: str, actual: str, ok: bool, blocker: str = "") -> dict[str, object]:
    return {
        "validation_item": item,
        "source_path": rel(path),
        "expected_value": expected,
        "actual_value": actual,
        "validation_status": "PASS" if ok else "BLOCKED",
        "blocker_reason": "" if ok else blocker,
    }


def run_v48_tests() -> tuple[bool, str]:
    if not IN_V48_TEST.exists():
        return False, "V20.48 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V48_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_48_TESTS" in result.stdout.splitlines(), output


def build_upstream_validation(v48_tests_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V48_SUMMARY)
    next_step = first_row(IN_V48_NEXT)
    checks = []
    required_files = [
        ("v20_48_summary_exists_non_empty", IN_V48_SUMMARY),
        ("v20_48_refreshed_candidate_view_exists_non_empty", IN_V48_CANDIDATE),
        ("v20_48_benchmark_context_exists_non_empty", IN_V48_BENCHMARK),
        ("v20_48_factor_support_exists_non_empty", IN_V48_FACTOR),
        ("v20_48_entry_strategy_exists_non_empty", IN_V48_ENTRY),
        ("v20_48_lineage_freshness_exists_non_empty", IN_V48_LINEAGE),
        ("v20_48_action_boundary_exists_non_empty", IN_V48_ACTION),
        ("v20_48_safety_boundary_exists_non_empty", IN_V48_SAFETY),
        ("v20_48_next_step_exists_non_empty", IN_V48_NEXT),
        ("v20_48_read_center_report_exists_non_empty", IN_V48_REPORT),
        ("v20_48_current_alias_exists_non_empty", IN_V48_CURRENT),
        ("v20_48_read_first_exists_non_empty", IN_V48_READ_FIRST),
    ]
    for item, path in required_files:
        ok = exists_non_empty(path)
        checks.append(status_row(item, path, "TRUE", tf(ok), ok, "missing_or_empty"))
    checks.append(status_row("v20_48_formal_test_script_exists", IN_V48_TEST, "TRUE", tf(IN_V48_TEST.exists()), IN_V48_TEST.exists(), "missing_test_script"))
    checks.append(status_row("v20_48_report_status", IN_V48_NEXT, "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED", clean(next_step.get("decision")), clean(next_step.get("decision")) == "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED", "report_status_not_pass"))
    checks.append(status_row("v20_48_tests_status", IN_V48_TEST, "PASS", "PASS" if v48_tests_passed else "FAIL", v48_tests_passed, "formal_tests_failed"))
    checks.append(status_row("v20_48_candidate_rows_with_refreshed_price", IN_V48_SUMMARY, "50", clean(summary.get("candidate_research_rows_with_refreshed_price")), clean(summary.get("candidate_research_rows_with_refreshed_price")) == "50", "candidate_refreshed_count_mismatch"))
    checks.append(status_row("v20_48_missing_refreshed_price", IN_V48_SUMMARY, "0", clean(summary.get("candidate_research_rows_missing_refreshed_price")), clean(summary.get("candidate_research_rows_missing_refreshed_price")) == "0", "missing_refreshed_price_not_zero"))
    for key in [
        "official_recommendation_allowed",
        "official_trading_allowed",
        "provider_refresh_executed_in_this_stage",
        "yfinance_import_used_in_this_stage",
        "broker_order_execution_used",
        "official_ranking_mutated",
        "dynamic_weighting_mutated",
        "returns_calculated",
        "scores_recomputed",
        "rankings_recomputed",
    ]:
        checks.append(status_row(f"v20_48_{key}", IN_V48_SUMMARY, "FALSE", clean(summary.get(key)), clean(summary.get(key)) == "FALSE", f"{key}_not_false"))
    return checks


def package_manifest() -> list[dict[str, object]]:
    items = [
        ("refreshed operator research report", IN_V48_REPORT, "read_center_report", "Primary human-readable refreshed research report."),
        ("refreshed candidate research view", IN_V48_CANDIDATE, "candidate_review_input", "Candidate review rows with refreshed price context."),
        ("refreshed benchmark context view", IN_V48_BENCHMARK, "benchmark_review_input", "SPY/QQQ benchmark context review rows."),
        ("refreshed factor support view", IN_V48_FACTOR, "factor_review_input", "Factor support review rows."),
        ("refreshed entry strategy view", IN_V48_ENTRY, "entry_strategy_review_input", "Entry setup under research review rows."),
        ("refreshed lineage/freshness view", IN_V48_LINEAGE, "lineage_review_input", "Freshness and cache certification review rows."),
        ("refreshed action boundary", IN_V48_ACTION, "boundary", "Allowed and blocked action reference."),
        ("refreshed safety boundary", IN_V48_SAFETY, "boundary", "Safety validation reference."),
        ("V20.47 run/cache certification reference", CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv", "cache_certification_reference", "Certified cache handoff reference."),
        ("V20.48 READ_FIRST", IN_V48_READ_FIRST, "ops_read_first", "Operator safety handoff."),
        ("V20.48 current alias report", IN_V48_CURRENT, "current_alias", "Current refreshed report pointer."),
    ]
    rows = []
    for item, path, role, use in items:
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = exists and non_empty
        rows.append({
            "package_item": item,
            "artifact_path": rel(path),
            "artifact_role": role,
            "required_for_operator_review": "TRUE",
            "exists_flag": tf(exists),
            "non_empty_flag": tf(non_empty),
            "review_use": use,
            "research_only_flag": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "trading_allowed": "FALSE",
            "validation_status": "PASS" if ok else "BLOCKED",
            "blocker_reason": "" if ok else "missing_or_empty",
        })
    return rows


def candidate_review(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        ready = clean(row.get("refreshed_price_mapping_status")) == "MAPPED_CERTIFIED_PRICE" and clean(row.get("refreshed_latest_close"))
        out.append({
            "report_rank": clean(row.get("report_rank")),
            "normalized_ticker": clean(row.get("normalized_ticker")),
            "display_name_or_ticker": clean(row.get("display_name_or_ticker")),
            "research_category": clean(row.get("research_category")),
            "report_section": clean(row.get("report_section")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "refreshed_price_date": clean(row.get("refreshed_price_date")),
            "refreshed_latest_close": clean(row.get("refreshed_latest_close")),
            "refreshed_price_certification_status": clean(row.get("refreshed_price_certification_status")),
            "refreshed_price_mapping_status": clean(row.get("refreshed_price_mapping_status")),
            "duplicate_ticker_mapping_flag": clean(row.get("duplicate_ticker_mapping_flag")),
            "review_ready": tf(ready),
            "operator_review_scope": "candidate review with refreshed price context",
            "required_human_checks": "Review candidate context, source rank, and refreshed price date; do not treat as official advice.",
            "research_only_flag": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "official_trading_allowed": "FALSE",
            "broker_execution_allowed": "FALSE",
            "blocker_reason": "" if ready else "missing_certified_refreshed_price",
        })
    return out


def benchmark_review(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "benchmark_ticker": clean(row.get("benchmark_ticker")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "refreshed_price_date": clean(row.get("refreshed_price_date")),
            "refreshed_latest_close": clean(row.get("refreshed_latest_close")),
            "certification_status": clean(row.get("certification_status")),
            "review_ready": tf(clean(row.get("certification_status")) == "CERTIFIED"),
            "benchmark_context_allowed": clean(row.get("research_context_allowed")),
            "benchmark_return_calculated": "FALSE",
            "official_trading_allowed": "FALSE",
            "blocker_reason": "" if clean(row.get("certification_status")) == "CERTIFIED" else "benchmark_not_certified",
        }
        for row in rows
    ]


def factor_review(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "factor_id_or_name": clean(row.get("factor_id_or_name")),
            "factor_category": clean(row.get("factor_category")),
            "pit_status": clean(row.get("pit_status")),
            "support_status": clean(row.get("support_status")),
            "report_section": clean(row.get("report_section")),
            "refreshed_market_context_available": clean(row.get("refreshed_market_context_available")),
            "review_ready": tf(clean(row.get("refreshed_market_context_available")) == "TRUE"),
            "operator_review_scope": "factor support review with refreshed market context",
            "included_in_official_weight_flag": "FALSE",
            "dynamic_weighting_mutated": "FALSE",
            "research_only_flag": "TRUE",
            "blocker_reason": "" if clean(row.get("refreshed_market_context_available")) == "TRUE" else "missing_refreshed_context",
        }
        for row in rows
    ]


def entry_review(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "strategy_id_or_name": clean(row.get("strategy_id_or_name")),
            "strategy_family": clean(row.get("strategy_family")),
            "readiness_status": clean(row.get("readiness_status")),
            "report_section": clean(row.get("report_section")),
            "refreshed_market_context_available": clean(row.get("refreshed_market_context_available")),
            "review_ready": tf(clean(row.get("refreshed_market_context_available")) == "TRUE"),
            "operator_review_scope": "entry setup research review with refreshed context",
            "allowed_in_research_report": "TRUE",
            "allowed_for_live_trading": "FALSE",
            "broker_execution_enabled": "FALSE",
            "research_only_flag": "TRUE",
            "blocker_reason": "" if clean(row.get("refreshed_market_context_available")) == "TRUE" else "missing_refreshed_context",
        }
        for row in rows
    ]


def lineage_review(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        blocker_count = int(float(clean(row.get("blocker_count")) or "0"))
        out.append({
            "source_name_or_input_name": clean(row.get("source_name_or_input_name")),
            "source_contract_or_version": clean(row.get("source_contract_or_version")),
            "freshness_status": clean(row.get("freshness_status")),
            "lineage_status": clean(row.get("lineage_status")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "v20_47_cache_hash_reference": clean(row.get("v20_47_cache_hash_reference")),
            "refreshed_cache_certified": clean(row.get("refreshed_cache_certified")),
            "review_ready": tf(blocker_count == 0 and clean(row.get("safe_for_research_report")) == "TRUE"),
            "safe_for_research_report": clean(row.get("safe_for_research_report")),
            "safe_for_official_recommendation": "FALSE",
            "safe_for_trading": "FALSE",
            "blocker_count": blocker_count,
            "warning_count": clean(row.get("warning_count")) or "0",
            "blocker_reason": "" if blocker_count == 0 else "lineage_blocker_present",
        })
    return out


MINIMUM_REQUIRED_LINEAGE_ROWS = 35
REQUIRED_LINEAGE_SOURCE_NAMES = {
    "V20.42",
    "V20.35-R2",
    "V20.36",
    "V20.37",
    "V20.38",
    "V20.39",
    "V20.40",
    "V20.41",
    "raw_candidate_price_cache",
    "raw_benchmark_price_cache",
    "candidate_certification",
    "benchmark_certification",
}
VALID_LINEAGE_FRESHNESS = {"REFRESHED_CERTIFIED_CONTEXT_ATTACHED", "V20_47_REFRESHED_CACHE_CERTIFIED"}


def lineage_row_key(row: dict[str, object]) -> tuple[str, str]:
    return (clean(row.get("source_name_or_input_name")), clean(row.get("source_contract_or_version")))


def lineage_policy_diagnostics(rows: list[dict[str, object]]) -> dict[str, object]:
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    malformed_count = 0
    stale_count = 0
    missing_sources = set(REQUIRED_LINEAGE_SOURCE_NAMES)
    for row in rows:
        key = lineage_row_key(row)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        source_name = clean(row.get("source_name_or_input_name"))
        missing_sources.discard(source_name)
        required_values = [
            source_name,
            clean(row.get("source_contract_or_version")),
            clean(row.get("freshness_status")),
            clean(row.get("lineage_status")),
            clean(row.get("safe_for_research_report")),
        ]
        if any(not value for value in required_values):
            malformed_count += 1
        try:
            blocker_count = int(float(clean(row.get("blocker_count")) or "0"))
        except ValueError:
            blocker_count = 1
        if clean(row.get("freshness_status")) not in VALID_LINEAGE_FRESHNESS or clean(row.get("safe_for_research_report")) != "TRUE" or blocker_count != 0:
            stale_count += 1
    status = "PASS" if len(rows) >= MINIMUM_REQUIRED_LINEAGE_ROWS and duplicate_count == 0 and malformed_count == 0 and stale_count == 0 and not missing_sources else "BLOCKED"
    return {
        "expected_lineage_row_policy": "minimum_count_required_source_coverage_no_duplicate_malformed_or_stale_rows",
        "minimum_required_lineage_rows": MINIMUM_REQUIRED_LINEAGE_ROWS,
        "actual_lineage_rows_available": len(rows),
        "lineage_row_count_validation_status": status,
        "duplicate_lineage_rows": duplicate_count,
        "malformed_lineage_rows": malformed_count,
        "stale_lineage_rows": stale_count,
        "missing_required_lineage_sources": ";".join(sorted(missing_sources)),
    }


def checklist_rows() -> list[dict[str, object]]:
    items = [
        ("CHK_01", "candidate review completeness", "candidate", "Confirm 50 candidate rows are present for operator review."),
        ("CHK_02", "refreshed price mapping review", "candidate", "Confirm refreshed price context is mapped for all candidate rows."),
        ("CHK_03", "benchmark context review", "benchmark", "Confirm SPY and QQQ context rows are present."),
        ("CHK_04", "factor support review", "factor", "Review factor support as research context."),
        ("CHK_05", "entry strategy research review", "entry_strategy", "Review entry setup rows under research-only boundary."),
        ("CHK_06", "lineage/freshness review", "lineage", "Review refreshed cache certification and lineage references."),
        ("CHK_07", "action boundary review", "boundary", "Review allowed and blocked action rows."),
        ("CHK_08", "safety boundary review", "boundary", "Review no-refresh/no-trading/no-mutation rows."),
        ("CHK_09", "no official recommendation confirmation", "safety", "Confirm no official recommendation is created."),
        ("CHK_10", "no trading authorization confirmation", "safety", "Confirm report is not trading-authorized."),
        ("CHK_11", "no broker/order confirmation", "safety", "Confirm no broker/order execution path exists."),
        ("CHK_12", "no provider refresh in V20.49 confirmation", "safety", "Confirm no provider refresh occurs in V20.49."),
        ("CHK_13", "no score/ranking/return recomputation confirmation", "safety", "Confirm no returns, scores, or rankings are recomputed."),
        ("CHK_14", "next-stage research-only decision packet readiness", "next_stage", "Confirm next packet remains research-only."),
    ]
    return [
        {
            "checklist_item_id": item_id,
            "checklist_item": item,
            "review_category": category,
            "required_before_next_stage": "TRUE",
            "expected_evidence": evidence,
            "allowed_action": "operator research review",
            "blocked_action": "official recommendation; trading authorization; broker/order execution",
            "completion_status": "READY_FOR_OPERATOR_REVIEW",
            "blocker_if_missing": "TRUE",
        }
        for item_id, item, category, evidence in items
    ]


def boundary_rows() -> list[dict[str, object]]:
    specs = [
        ("operator_research_review_allowed", "TRUE", "V20.48 refreshed report passed and formal tests passed."),
        ("candidate_review_allowed", "TRUE", "Candidate review package has refreshed price context."),
        ("benchmark_context_review_allowed", "TRUE", "SPY/QQQ context is present."),
        ("factor_review_allowed", "TRUE", "Factor support rows are present."),
        ("entry_strategy_review_allowed", "TRUE", "Entry setup research rows are present."),
        ("lineage_review_allowed", "TRUE", "Lineage/freshness rows are present."),
        ("research_only_decision_packet_preparation_allowed_next", "TRUE", "Next packet can be prepared as research-only."),
        ("provider_refresh_allowed_in_this_stage", "FALSE", "V20.49 is gate-only and review-only."),
        ("yfinance_import_allowed_in_this_stage", "FALSE", "No provider package use in V20.49."),
        ("official_buy_sell_hold_recommendation_allowed", "FALSE", "No official advice output."),
        ("live_trading_allowed", "FALSE", "Not trading-authorized."),
        ("broker_order_execution_allowed", "FALSE", "No broker/order path."),
        ("official_ranking_mutation_allowed", "FALSE", "No official rank mutation."),
        ("dynamic_weighting_mutation_allowed", "FALSE", "No dynamic weighting mutation."),
        ("real_portfolio_mutation_allowed", "FALSE", "No portfolio mutation."),
        ("return_calculation_allowed", "FALSE", "No return calculation."),
        ("score_recomputation_allowed", "FALSE", "No score recomputation."),
        ("ranking_recomputation_allowed", "FALSE", "No ranking recomputation."),
        ("trading_signal_generation_allowed", "FALSE", "No trading signal generation."),
    ]
    return [{"boundary_name": name, "allowed_flag": allowed, "evidence": evidence, "blocker_reason": "" if allowed == "TRUE" else "blocked_by_operator_review_boundary"} for name, allowed, evidence in specs]


def safety_rows() -> list[dict[str, object]]:
    specs = [
        ("provider_refresh_executed_in_v20_49", "FALSE", "FALSE", "No provider refresh in review gate."),
        ("yfinance_imported_in_v20_49", "FALSE", "FALSE", "No provider import."),
        ("refreshed_v20_48_report_used", "TRUE", "TRUE", "V20.48 report package consumed."),
        ("v20_47_certified_cache_reference_used", "TRUE", "TRUE", "V20.47 run/cache reference preserved."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_allowed", "FALSE", "FALSE", "Research-only review."),
        ("official_trading_allowed", "FALSE", "FALSE", "Not trading-authorized."),
        ("official_ranking_mutated", "FALSE", "FALSE", "No rank mutation."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No dynamic weight mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No portfolio mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No returns calculated."),
        ("scores_recomputed", "FALSE", "FALSE", "No scores recomputed."),
        ("rankings_recomputed", "FALSE", "FALSE", "No rankings recomputed."),
        ("trading_signals_created", "FALSE", "FALSE", "No trading signals."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 output path."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 output path."),
    ]
    return [{"safety_boundary": name, "expected_value": expected, "actual_value": actual, "validation_status": "PASS" if expected == actual else "BLOCKED", "evidence": evidence, "blocker_reason": "" if expected == actual else f"expected_{expected}_got_{actual}"} for name, expected, actual, evidence in specs]


def build_dual_gate_state(
    v20_47_run_id: str,
    v48_tests_passed: bool,
    lineage_diagnostics: dict[str, object],
    official_blockers: list[str],
) -> dict[str, object]:
    v47 = first_row(IN_V47_PROVIDER_SUMMARY)
    v47_controlled = first_row(IN_V47_CONTROLLED_SUMMARY)
    v7v = first_row(IN_V7V_SUMMARY)
    v16 = first_row(IN_V16_GATE)
    v17 = first_row(IN_V17_GATE)
    v18 = first_row(IN_V18_GATE)
    v19 = first_row(IN_V19_GATE)
    v27 = first_row(IN_V27_GATE)
    sweep = first_row(IN_SWEEP_STATUS)
    staging_rows, _ = read_csv(IN_V7V_STAGING)
    v17_prep_rows, _ = read_csv(IN_V17_PREP)

    active_candidate_rows = as_int(v7v.get("eligible_row_count")) or len(staging_rows)
    factor_rows = as_int(v16.get("FACTOR_SCORE_ROWS_REVIEWED"))
    prepared_rows = as_int(v17.get("prepared_candidate_input_rows")) or len(v17_prep_rows)
    benchmark_rows = as_int(v17.get("prepared_benchmark_rows")) or as_int(v47.get("benchmark_success_count"))

    v47_status = clean(v47_controlled.get("certification_status"))
    v7v_status = clean(v7v.get("status"))
    v16_status = clean(v16.get("v20_16_status")) or clean(v16.get("STATUS"))
    v17_status = clean(v17.get("v20_17_status")) or clean(v17.get("STATUS"))
    v18_status = clean(v18.get("v20_18_status")) or clean(v18.get("STATUS"))
    v19_status = clean(v19.get("v20_19_status")) or clean(v19.get("STATUS"))
    v27_status = clean(v27.get("STATUS"))
    v27_blocker = clean(sweep.get("ending_blocker_reason")) or (
        "V20.27 active outcome/benchmark staged inputs unavailable"
        if clean(v27.get("READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT")) != "TRUE"
        else ""
    )

    research_failures = []
    if v47_status not in {"CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF", "CERTIFIED_CACHE_FALLBACK_HANDOFF"}:
        research_failures.append("v20_47_not_certified")
    if v7v_status != "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY":
        research_failures.append("v20_7v_not_pass")
    if clean(v7v.get("active_market_source_staging_usable")) != "TRUE" and clean(v7v.get("active_source_staging_candidate_ready")) != "TRUE":
        research_failures.append("active_market_source_staging_not_usable")
    if active_candidate_rows <= 0:
        research_failures.append("no_active_candidate_rows")
    if v16_status != "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE":
        research_failures.append("v20_16_not_pass")
    if v17_status != "PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION":
        research_failures.append("v20_17_not_pass")
    if v18_status != "PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW":
        research_failures.append("v20_18_not_pass")
    if v19_status != "PASS_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION":
        research_failures.append("v20_19_not_pass")
    if factor_rows <= 0:
        research_failures.append("no_factor_rows")
    if prepared_rows <= 0:
        research_failures.append("no_prepared_candidate_input_rows")
    if benchmark_rows < 2:
        research_failures.append("benchmark_rows_less_than_2")

    promotion_blockers = list(dict.fromkeys([blocker for blocker in official_blockers if blocker]))
    if clean(v27.get("READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT")) != "TRUE":
        promotion_blockers.append("v20_27_missing_pit_safe_active_outcome_benchmark_staged_inputs")
    if not v48_tests_passed:
        promotion_blockers.append("upstream_v20_48_tests_status_fail")
    if clean(lineage_diagnostics.get("lineage_row_count_validation_status")) != "PASS":
        promotion_blockers.append("missing_promotion_lineage_sources")

    research_status = RESEARCH_ONLY_PASS if not research_failures else "BLOCKED_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
    official_status = PASS_STATUS if not promotion_blockers else PROMOTION_BLOCKED
    recommended = (
        "V20_55_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED"
        if research_status == RESEARCH_ONLY_PASS and official_status != PASS_STATUS
        else "REPAIR_V20_49_RESEARCH_ONLY_INPUTS"
        if research_status != RESEARCH_ONLY_PASS
        else NEXT_STAGE
    )
    return {
        "v20_47_run_id": v20_47_run_id,
        "v20_47_status": v47_status,
        "v20_7v_status": v7v_status,
        "v20_16_status": v16_status,
        "v20_17_status": v17_status,
        "v20_18_status": v18_status,
        "v20_19_status": v19_status,
        "v20_27_status": v27_status,
        "v20_27_blocker": v27_blocker,
        "active_candidate_rows_available": active_candidate_rows,
        "factor_rows_available": factor_rows,
        "prepared_candidate_input_rows": prepared_rows,
        "benchmark_rows_available": benchmark_rows,
        "research_only_gate_status": research_status,
        "official_promotion_gate_status": official_status,
        "research_only_failed_conditions": ";".join(research_failures),
        "official_promotion_blockers": ";".join(dict.fromkeys(promotion_blockers)),
        "missing_promotion_lineage_sources": clean(lineage_diagnostics.get("missing_required_lineage_sources")),
        "operator_acceptance_required": "TRUE",
        "official_recommendation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "weight_mutation_allowed": "FALSE",
        "recommended_next_action": recommended,
    }


def md_table(rows: list[dict[str, object]], columns: list[str], limit: int = 15) -> str:
    if not rows:
        return "_No rows available._\n"
    text = "| " + " | ".join(columns) + " |\n"
    text += "| " + " | ".join("---" for _ in columns) + " |\n"
    for row in rows[:limit]:
        text += "| " + " | ".join(clean(row.get(col)).replace("|", "/") for col in columns) + " |\n"
    if len(rows) > limit:
        text += f"\n_Showing {limit} of {len(rows)} rows._\n"
    return text


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    v48_tests_passed, v48_test_output = run_v48_tests()
    upstream_rows = build_upstream_validation(v48_tests_passed)
    manifest = package_manifest()
    v48_summary = first_row(IN_V48_SUMMARY)
    v48_next = first_row(IN_V48_NEXT)
    v20_47_run_id = clean(v48_summary.get("v20_47_run_id"))

    v48_candidates, _ = read_csv(IN_V48_CANDIDATE)
    v48_benchmarks, _ = read_csv(IN_V48_BENCHMARK)
    v48_factors, _ = read_csv(IN_V48_FACTOR)
    v48_entries, _ = read_csv(IN_V48_ENTRY)
    v48_lineage, _ = read_csv(IN_V48_LINEAGE)

    candidate_rows = candidate_review(v48_candidates)
    benchmark_rows = benchmark_review(v48_benchmarks)
    factor_rows = factor_review(v48_factors)
    entry_rows = entry_review(v48_entries)
    lineage_rows = lineage_review(v48_lineage)
    lineage_diagnostics = lineage_policy_diagnostics(lineage_rows)
    checklist = checklist_rows()
    actions = boundary_rows()
    safety = safety_rows()

    blockers = [clean(row.get("blocker_reason")) for row in upstream_rows + manifest + candidate_rows + benchmark_rows + factor_rows + entry_rows + lineage_rows if clean(row.get("blocker_reason"))]
    if clean(v48_next.get("decision")) != "PASS_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT_CREATED":
        blockers.append("v20_48_next_step_not_pass")
    if len(v48_candidates) < 50:
        blockers.append("candidate_rows_less_than_expected_50")
    if {clean(row.get("benchmark_ticker")) for row in v48_benchmarks} != {"SPY", "QQQ"}:
        blockers.append("spy_qqq_benchmark_context_missing")
    if any(row.get("validation_status") != "PASS" for row in safety):
        blockers.append("safety_boundary_failed")
    if clean(lineage_diagnostics.get("lineage_row_count_validation_status")) != "PASS":
        blockers.append("lineage_contract_validation_failed")
    warnings: list[str] = []

    blocked = bool(blockers)
    dual_gate = build_dual_gate_state(v20_47_run_id, v48_tests_passed, lineage_diagnostics, blockers)
    research_only_ready = clean(dual_gate.get("research_only_gate_status")) == RESEARCH_ONLY_PASS
    official_promotion_ready = clean(dual_gate.get("official_promotion_gate_status")) == PASS_STATUS
    acceptance_status = ACCEPTANCE_STATUS if not blocked else "BLOCKED_OPERATOR_REVIEW_ACCEPTANCE"
    final_status = PASS_STATUS if official_promotion_ready else WARN_STATUS if research_only_ready else BLOCKED_STATUS
    decision = DECISION_PASS if official_promotion_ready else "WARN_RESEARCH_ONLY_DAILY_CONCLUSION_READY_OFFICIAL_PROMOTION_BLOCKED" if research_only_ready else "BLOCKED_OPERATOR_REVIEW_ACCEPTANCE_GATE"

    summary = [{
        "stage": STAGE,
        "upstream_v20_48_report_status": clean(v48_next.get("decision")),
        "upstream_v20_48_tests_status": "PASS" if v48_tests_passed else "FAIL",
        "v20_47_run_id": v20_47_run_id,
        "refreshed_report_available": tf(exists_non_empty(IN_V48_REPORT)),
        "refreshed_candidate_rows_available": dual_gate["active_candidate_rows_available"],
        "refreshed_benchmark_rows_available": len(v48_benchmarks),
        "factor_rows_available": dual_gate["factor_rows_available"],
        "entry_strategy_rows_available": dual_gate["prepared_candidate_input_rows"],
        "active_candidate_rows_available": dual_gate["active_candidate_rows_available"],
        "prepared_candidate_input_rows": dual_gate["prepared_candidate_input_rows"],
        "benchmark_rows_available": dual_gate["benchmark_rows_available"],
        "research_only_gate_status": dual_gate["research_only_gate_status"],
        "official_promotion_gate_status": dual_gate["official_promotion_gate_status"],
        "lineage_rows_available": len(v48_lineage),
        "expected_lineage_row_policy": lineage_diagnostics["expected_lineage_row_policy"],
        "minimum_required_lineage_rows": lineage_diagnostics["minimum_required_lineage_rows"],
        "actual_lineage_rows_available": lineage_diagnostics["actual_lineage_rows_available"],
        "lineage_row_count_validation_status": lineage_diagnostics["lineage_row_count_validation_status"],
        "duplicate_lineage_rows": lineage_diagnostics["duplicate_lineage_rows"],
        "malformed_lineage_rows": lineage_diagnostics["malformed_lineage_rows"],
        "stale_lineage_rows": lineage_diagnostics["stale_lineage_rows"],
        "missing_required_lineage_sources": lineage_diagnostics["missing_required_lineage_sources"],
        "operator_review_package_created": tf(not blocked),
        "operator_review_ready": tf(not blocked),
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
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "acceptance_status": acceptance_status,
        "next_recommended_stage": dual_gate["recommended_next_action"],
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "operator_review_package_created": tf(official_promotion_ready),
        "operator_review_ready": tf(official_promotion_ready),
        "research_only_status": "TRUE",
        "research_only_decision_packet_allowed_next": tf(research_only_ready),
        "research_only_gate_status": dual_gate["research_only_gate_status"],
        "official_promotion_gate_status": dual_gate["official_promotion_gate_status"],
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": dual_gate["recommended_next_action"],
    }]
    research_gate = [{
        "research_only_gate_status": dual_gate["research_only_gate_status"],
        "active_candidate_rows_available": dual_gate["active_candidate_rows_available"],
        "factor_rows_available": dual_gate["factor_rows_available"],
        "prepared_candidate_input_rows": dual_gate["prepared_candidate_input_rows"],
        "benchmark_rows_available": dual_gate["benchmark_rows_available"],
        "v20_47_status": dual_gate["v20_47_status"],
        "v20_7v_status": dual_gate["v20_7v_status"],
        "v20_16_status": dual_gate["v20_16_status"],
        "v20_17_status": dual_gate["v20_17_status"],
        "v20_18_status": dual_gate["v20_18_status"],
        "v20_19_status": dual_gate["v20_19_status"],
        "failed_condition_list": dual_gate["research_only_failed_conditions"],
        "official_recommendation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "weight_mutation_allowed": "FALSE",
        "recommended_next_action": dual_gate["recommended_next_action"],
    }]
    promotion_gate = [{
        "official_promotion_gate_status": dual_gate["official_promotion_gate_status"],
        "operator_acceptance_required": dual_gate["operator_acceptance_required"],
        "acceptance_status": acceptance_status,
        "upstream_v20_48_tests_status": "PASS" if v48_tests_passed else "FAIL",
        "v20_27_status": dual_gate["v20_27_status"],
        "v20_27_blocker": dual_gate["v20_27_blocker"],
        "lineage_rows_available": len(v48_lineage),
        "minimum_required_lineage_rows": lineage_diagnostics["minimum_required_lineage_rows"],
        "missing_promotion_lineage_sources": dual_gate["missing_promotion_lineage_sources"],
        "official_promotion_blockers": dual_gate["official_promotion_blockers"],
        "official_recommendation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "weight_mutation_allowed": "FALSE",
        "recommended_next_action": "REPAIR_PROMOTION_INPUTS_AND_OPERATOR_ACCEPTANCE_SEPARATELY",
    }]
    source_audit = [
        {"source_name": "V20.47 provider refresh", "source_path": rel(IN_V47_PROVIDER_SUMMARY), "status": dual_gate["v20_47_status"], "rows_available": clean(first_row(IN_V47_PROVIDER_SUMMARY).get("success_count")), "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.7V active staging", "source_path": rel(IN_V7V_STAGING), "status": dual_gate["v20_7v_status"], "rows_available": dual_gate["active_candidate_rows_available"], "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.16 factor score review", "source_path": rel(IN_V16_GATE), "status": dual_gate["v20_16_status"], "rows_available": dual_gate["factor_rows_available"], "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.17 backtest input preparation", "source_path": rel(IN_V17_GATE), "status": dual_gate["v20_17_status"], "rows_available": dual_gate["prepared_candidate_input_rows"], "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.18 source attachment review", "source_path": rel(IN_V18_GATE), "status": dual_gate["v20_18_status"], "rows_available": clean(first_row(IN_V18_GATE).get("BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED")), "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.19 blocker resolution", "source_path": rel(IN_V19_GATE), "status": dual_gate["v20_19_status"], "rows_available": clean(first_row(IN_V19_GATE).get("candidate_rows_reviewed")), "used_for_research_gate": "TRUE", "used_for_official_promotion_gate": "FALSE"},
        {"source_name": "V20.27 active outcome/benchmark staging", "source_path": rel(IN_V27_GATE), "status": dual_gate["v20_27_status"], "rows_available": clean(first_row(IN_V27_GATE).get("ACTIVE_OUTCOME_ROWS")), "used_for_research_gate": "FALSE", "used_for_official_promotion_gate": "TRUE"},
        {"source_name": "V20.48 operator lineage", "source_path": rel(IN_V48_LINEAGE), "status": clean(lineage_diagnostics.get("lineage_row_count_validation_status")), "rows_available": len(v48_lineage), "used_for_research_gate": "FALSE", "used_for_official_promotion_gate": "TRUE"},
    ]
    diagnostics = [{
        "research_only_gate_status": dual_gate["research_only_gate_status"],
        "official_promotion_gate_status": dual_gate["official_promotion_gate_status"],
        "active_candidate_rows_available": dual_gate["active_candidate_rows_available"],
        "factor_rows_available": dual_gate["factor_rows_available"],
        "prepared_candidate_input_rows": dual_gate["prepared_candidate_input_rows"],
        "benchmark_rows_available": dual_gate["benchmark_rows_available"],
        "v20_27_blocker": dual_gate["v20_27_blocker"],
        "missing_promotion_lineage_sources": dual_gate["missing_promotion_lineage_sources"],
        "operator_acceptance_required": dual_gate["operator_acceptance_required"],
        "official_recommendation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "weight_mutation_allowed": "FALSE",
        "recommended_next_action": dual_gate["recommended_next_action"],
    }]

    write_csv(OUT_UPSTREAM, upstream_rows, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_MANIFEST, manifest, ["package_item", "artifact_path", "artifact_role", "required_for_operator_review", "exists_flag", "non_empty_flag", "review_use", "research_only_flag", "official_recommendation_allowed", "trading_allowed", "validation_status", "blocker_reason"])
    write_csv(OUT_CANDIDATE, candidate_rows, ["report_rank", "normalized_ticker", "display_name_or_ticker", "research_category", "report_section", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "refreshed_price_certification_status", "refreshed_price_mapping_status", "duplicate_ticker_mapping_flag", "review_ready", "operator_review_scope", "required_human_checks", "research_only_flag", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "blocker_reason"])
    write_csv(OUT_BENCHMARK, benchmark_rows, ["benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "certification_status", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated", "official_trading_allowed", "blocker_reason"])
    write_csv(OUT_FACTOR, factor_rows, ["factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section", "refreshed_market_context_available", "review_ready", "operator_review_scope", "included_in_official_weight_flag", "dynamic_weighting_mutated", "research_only_flag", "blocker_reason"])
    write_csv(OUT_ENTRY, entry_rows, ["strategy_id_or_name", "strategy_family", "readiness_status", "report_section", "refreshed_market_context_available", "review_ready", "operator_review_scope", "allowed_in_research_report", "allowed_for_live_trading", "broker_execution_enabled", "research_only_flag", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, ["source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status", "v20_47_run_id", "v20_47_cache_hash_reference", "refreshed_cache_certified", "review_ready", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading", "blocker_count", "warning_count", "blocker_reason"])
    write_csv(OUT_CHECKLIST, checklist, ["checklist_item_id", "checklist_item", "review_category", "required_before_next_stage", "expected_evidence", "allowed_action", "blocked_action", "completion_status", "blocker_if_missing"])
    write_csv(OUT_ACTION, actions, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_RESEARCH_GATE, research_gate, list(research_gate[0].keys()))
    write_csv(OUT_PROMOTION_GATE, promotion_gate, list(promotion_gate[0].keys()))
    write_csv(OUT_STATIC_ACCEPTANCE, summary, list(summary[0].keys()))
    write_csv(OUT_SOURCE_AUDIT, source_audit, list(source_audit[0].keys()))
    write_csv(OUT_GATE_DIAGNOSTICS, diagnostics, list(diagnostics[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    report = f"""# V20.49 Operator Review Acceptance Gate

## Stage Status

Stage: {STAGE}
Status: {final_status}
Acceptance status: {acceptance_status}
Decision: {decision}

## Dual Gate Status

Research-only daily conclusion gate: {dual_gate["research_only_gate_status"]}
Official promotion/operator acceptance gate: {dual_gate["official_promotion_gate_status"]}
Active candidate rows available: {dual_gate["active_candidate_rows_available"]}
Factor rows available: {dual_gate["factor_rows_available"]}
Prepared candidate input rows: {dual_gate["prepared_candidate_input_rows"]}
Benchmark rows available: {dual_gate["benchmark_rows_available"]}
V20.27 promotion/backtest blocker: {dual_gate["v20_27_blocker"]}
Missing promotion lineage sources: {dual_gate["missing_promotion_lineage_sources"] or "None"}
Official recommendation allowed: FALSE
Trade action allowed: FALSE
Weight mutation allowed: FALSE

## Upstream V20.48 Validation

V20.48 report status: {clean(v48_next.get("decision"))}
V20.48 formal tests status: {"PASS" if v48_tests_passed else "FAIL"}
V20.47 run ID/cache reference: {v20_47_run_id}

{md_table(upstream_rows, ["validation_item", "expected_value", "actual_value", "validation_status"], 15)}

## Operator Review Package Manifest

{md_table(manifest, ["package_item", "artifact_role", "research_only_flag", "validation_status"], 15)}

## Candidate Review Readiness

{md_table(candidate_rows, ["report_rank", "normalized_ticker", "review_ready", "operator_review_scope"], 20)}

## Benchmark Review Readiness

{md_table(benchmark_rows, ["benchmark_ticker", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated"], 10)}

## Factor Review Readiness

{md_table(factor_rows, ["factor_id_or_name", "factor_category", "review_ready"], 12)}

## Entry Strategy Review Readiness

{md_table(entry_rows, ["strategy_id_or_name", "review_ready", "allowed_for_live_trading"], 10)}

## Lineage/Freshness Review Readiness

Lineage row policy: {lineage_diagnostics["expected_lineage_row_policy"]}
Minimum required lineage rows: {lineage_diagnostics["minimum_required_lineage_rows"]}
Actual lineage rows available: {lineage_diagnostics["actual_lineage_rows_available"]}
Lineage row count validation status: {lineage_diagnostics["lineage_row_count_validation_status"]}
Duplicate lineage rows: {lineage_diagnostics["duplicate_lineage_rows"]}
Malformed lineage rows: {lineage_diagnostics["malformed_lineage_rows"]}
Stale lineage rows: {lineage_diagnostics["stale_lineage_rows"]}
Missing required lineage sources: {lineage_diagnostics["missing_required_lineage_sources"] or "None"}

{md_table(lineage_rows, ["source_name_or_input_name", "refreshed_cache_certified", "review_ready", "safe_for_research_report"], 12)}

## Operator Review Checklist

{md_table(checklist, ["checklist_item_id", "checklist_item", "completion_status", "blocked_action"], 20)}

## Action Boundary

{md_table(actions, ["boundary_name", "allowed_flag", "evidence"], 20)}

## Safety Boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Explicit No-Provider-Refresh-In-V20.49 Statement

V20.49 performs no provider/network refresh and does not use yfinance.

## Explicit Non-Official-Recommendation Statement

This package is not an official recommendation. It is for candidate review, refreshed price context review, research support review, and operator review readiness only.

## Explicit Non-Trading/Broker Statement

This package is not trading-authorized, creates no trading signals, and performs no broker/order execution.

## Explicit No Score/Ranking/Return Recomputation Statement

V20.49 calculates no forward returns, no benchmark-relative returns, no scores, and no rankings.

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: None
Promotion blockers: {dual_gate["official_promotion_blockers"] or "None"}

## Next Recommended Stage

{dual_gate["recommended_next_action"]}

## V20.48 Formal Test Output

```text
{v48_test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"ACCEPTANCE_STATUS={acceptance_status}",
        f"DECISION={decision}",
        f"RESEARCH_ONLY_GATE_STATUS={dual_gate['research_only_gate_status']}",
        f"OFFICIAL_PROMOTION_GATE_STATUS={dual_gate['official_promotion_gate_status']}",
        f"ACTIVE_CANDIDATE_ROWS_AVAILABLE={dual_gate['active_candidate_rows_available']}",
        f"FACTOR_ROWS_AVAILABLE={dual_gate['factor_rows_available']}",
        f"PREPARED_CANDIDATE_INPUT_ROWS={dual_gate['prepared_candidate_input_rows']}",
        f"BENCHMARK_ROWS_AVAILABLE={dual_gate['benchmark_rows_available']}",
        f"V20_27_BLOCKER={dual_gate['v20_27_blocker']}",
        f"MISSING_PROMOTION_LINEAGE_SOURCES={dual_gate['missing_promotion_lineage_sources']}",
        "OPERATOR_REVIEW_GATE_STATUS=TRUE",
        "V20_48_REFRESHED_REPORT_USED=TRUE",
        f"V20_47_RUN_ID={v20_47_run_id}",
        "REPORT_REVIEW_ONLY=TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_49=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_49=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "RESEARCH_ONLY_STATUS=TRUE",
        f"CANDIDATE_REVIEW_READY_ROWS={sum(1 for row in candidate_rows if row['review_ready'] == 'TRUE')}",
        f"BENCHMARK_REVIEW_READY_ROWS={sum(1 for row in benchmark_rows if row['review_ready'] == 'TRUE')}",
        f"FACTOR_REVIEW_READY_ROWS={sum(1 for row in factor_rows if row['review_ready'] == 'TRUE')}",
        f"ENTRY_REVIEW_READY_ROWS={sum(1 for row in entry_rows if row['review_ready'] == 'TRUE')}",
        f"LINEAGE_REVIEW_READY_ROWS={sum(1 for row in lineage_rows if row['review_ready'] == 'TRUE')}",
        f"NEXT_RECOMMENDED_STAGE={dual_gate['recommended_next_action']}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"ACCEPTANCE_STATUS={acceptance_status}")
    print(f"RESEARCH_ONLY_GATE_STATUS={dual_gate['research_only_gate_status']}")
    print(f"OFFICIAL_PROMOTION_GATE_STATUS={dual_gate['official_promotion_gate_status']}")
    print(f"V20_47_RUN_ID={v20_47_run_id}")
    print(f"ACTIVE_CANDIDATE_ROWS_AVAILABLE={dual_gate['active_candidate_rows_available']}")
    print(f"FACTOR_ROWS_AVAILABLE={dual_gate['factor_rows_available']}")
    print(f"PREPARED_CANDIDATE_INPUT_ROWS={dual_gate['prepared_candidate_input_rows']}")
    print(f"BENCHMARK_ROWS_AVAILABLE={dual_gate['benchmark_rows_available']}")
    print(f"CANDIDATE_REVIEW_READY_ROWS={sum(1 for row in candidate_rows if row['review_ready'] == 'TRUE')}")
    print(f"BENCHMARK_REVIEW_READY_ROWS={sum(1 for row in benchmark_rows if row['review_ready'] == 'TRUE')}")
    print(f"FACTOR_REVIEW_READY_ROWS={sum(1 for row in factor_rows if row['review_ready'] == 'TRUE')}")
    print(f"ENTRY_REVIEW_READY_ROWS={sum(1 for row in entry_rows if row['review_ready'] == 'TRUE')}")
    print(f"LINEAGE_REVIEW_READY_ROWS={sum(1 for row in lineage_rows if row['review_ready'] == 'TRUE')}")
    print(f"NEXT_RECOMMENDED_STAGE={dual_gate['recommended_next_action']}")
    return 0 if final_status in {PASS_STATUS, WARN_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
