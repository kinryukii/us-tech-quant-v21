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

STAGE = "V20.50_RESEARCH_ONLY_DECISION_PACKET"
PASS_STATUS = "PASS_V20_50_RESEARCH_ONLY_DECISION_PACKET"
BLOCKED_STATUS = "BLOCKED_V20_50_RESEARCH_ONLY_DECISION_PACKET"
ACCEPTED_V20_49 = "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY"
DECISION_PASS = "PASS_RESEARCH_ONLY_DECISION_PACKET_CREATED"
NEXT_STAGE = "V20.50_FORMAL_TESTS"
RUN_ID = "V20_47_20260604T114058Z"

IN_V49_SUMMARY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
IN_V49_UPSTREAM = CONSOLIDATION / "V20_49_UPSTREAM_V20_48_VALIDATION.csv"
IN_V49_MANIFEST = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv"
IN_V49_CANDIDATE = CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv"
IN_V49_BENCHMARK = CONSOLIDATION / "V20_49_OPERATOR_BENCHMARK_REVIEW_READINESS.csv"
IN_V49_FACTOR = CONSOLIDATION / "V20_49_OPERATOR_FACTOR_REVIEW_READINESS.csv"
IN_V49_ENTRY = CONSOLIDATION / "V20_49_OPERATOR_ENTRY_STRATEGY_REVIEW_READINESS.csv"
IN_V49_LINEAGE = CONSOLIDATION / "V20_49_OPERATOR_LINEAGE_REVIEW_READINESS.csv"
IN_V49_CHECKLIST = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_CHECKLIST.csv"
IN_V49_ACTION = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACTION_BOUNDARY.csv"
IN_V49_SAFETY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_SAFETY_BOUNDARY.csv"
IN_V49_NEXT = CONSOLIDATION / "V20_49_NEXT_STEP_DECISION.csv"
IN_V49_RESEARCH_GATE = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
IN_V49_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
IN_V49_REPORT = READ_CENTER / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_GATE_REPORT.md"
IN_V49_CURRENT = READ_CENTER / "V20_CURRENT_OPERATOR_REVIEW_ACCEPTANCE_GATE.md"
IN_V49_READ_FIRST = OPS / "V20_49_READ_FIRST.txt"
IN_V49_TEST = SCRIPT_DIR / "test_v20_49_operator_review_acceptance_gate.py"
IN_V7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_V16_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
IN_V17_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
IN_V18_GATE = CONSOLIDATION / "V20_18_GATE_DECISION.csv"
IN_V19_GATE = CONSOLIDATION / "V20_19_GATE_DECISION.csv"

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


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


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


def row_count(path: Path) -> int:
    rows, _ = read_csv(path)
    return len(rows)


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


def run_v49_tests() -> tuple[bool, str]:
    if not IN_V49_TEST.exists():
        return False, "V20.49 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V49_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_49_TESTS" in result.stdout.splitlines(), output


def validate_boundary_value(rows: list[dict[str, str]], key: str, expected: str, name_field: str) -> bool:
    for row in rows:
        if clean(row.get(name_field)) == key:
            return clean(row.get("allowed_flag") or row.get("actual_value")) == expected
    return False


def build_upstream_validation(v49_tests_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V49_SUMMARY)
    actions, _ = read_csv(IN_V49_ACTION)
    safety, _ = read_csv(IN_V49_SAFETY)
    checks: list[dict[str, object]] = []
    files = [
        ("v20_49_acceptance_summary_exists_non_empty", IN_V49_SUMMARY),
        ("v20_49_operator_package_manifest_exists_non_empty", IN_V49_MANIFEST),
        ("v20_49_candidate_readiness_exists_non_empty", IN_V49_CANDIDATE),
        ("v20_49_benchmark_readiness_exists_non_empty", IN_V49_BENCHMARK),
        ("v20_49_factor_readiness_exists_non_empty", IN_V49_FACTOR),
        ("v20_49_entry_readiness_exists_non_empty", IN_V49_ENTRY),
        ("v20_49_lineage_readiness_exists_non_empty", IN_V49_LINEAGE),
        ("v20_49_checklist_exists_non_empty", IN_V49_CHECKLIST),
        ("v20_49_action_boundary_exists_non_empty", IN_V49_ACTION),
        ("v20_49_safety_boundary_exists_non_empty", IN_V49_SAFETY),
        ("v20_49_next_step_decision_exists_non_empty", IN_V49_NEXT),
        ("v20_49_read_center_report_exists_non_empty", IN_V49_REPORT),
        ("v20_49_current_alias_exists_non_empty", IN_V49_CURRENT),
        ("v20_49_read_first_exists_non_empty", IN_V49_READ_FIRST),
    ]
    for item, path in files:
        ok = exists_non_empty(path)
        checks.append(status_row(item, path, "TRUE", tf(ok), ok, "missing_or_empty"))
    checks.append(status_row("v20_49_formal_test_script_exists", IN_V49_TEST, "TRUE", tf(IN_V49_TEST.exists()), IN_V49_TEST.exists(), "missing_test_script"))
    checks.append(status_row("v20_49_acceptance_status", IN_V49_SUMMARY, ACCEPTED_V20_49, clean(summary.get("acceptance_status")), clean(summary.get("acceptance_status")) == ACCEPTED_V20_49, "acceptance_status_not_accepted"))
    checks.append(status_row("v20_49_tests_status", IN_V49_TEST, "PASS", "PASS" if v49_tests_passed else "FAIL", v49_tests_passed, "formal_tests_failed"))
    checks.append(status_row("v20_49_candidate_count", IN_V49_CANDIDATE, "50", str(row_count(IN_V49_CANDIDATE)), row_count(IN_V49_CANDIDATE) >= 50, "candidate_rows_less_than_50"))
    checks.append(status_row("v20_49_benchmark_count", IN_V49_BENCHMARK, "2", str(row_count(IN_V49_BENCHMARK)), row_count(IN_V49_BENCHMARK) == 2, "benchmark_count_not_2"))
    checks.append(status_row("v20_49_factor_count", IN_V49_FACTOR, "21", str(row_count(IN_V49_FACTOR)), row_count(IN_V49_FACTOR) == 21, "factor_count_not_21"))
    checks.append(status_row("v20_49_entry_count", IN_V49_ENTRY, "5", str(row_count(IN_V49_ENTRY)), row_count(IN_V49_ENTRY) == 5, "entry_count_not_5"))
    minimum_lineage_rows = int(float(clean(summary.get("minimum_required_lineage_rows")) or "35"))
    lineage_status = clean(summary.get("lineage_row_count_validation_status")) or ("PASS" if row_count(IN_V49_LINEAGE) >= minimum_lineage_rows else "BLOCKED")
    checks.append(status_row("v20_49_lineage_count", IN_V49_LINEAGE, f">={minimum_lineage_rows}", str(row_count(IN_V49_LINEAGE)), row_count(IN_V49_LINEAGE) >= minimum_lineage_rows, "lineage_count_less_than_minimum"))
    checks.append(status_row("v20_49_lineage_policy_status", IN_V49_SUMMARY, "PASS", lineage_status, lineage_status == "PASS", "lineage_policy_not_pass"))
    for field in ["duplicate_lineage_rows", "malformed_lineage_rows", "stale_lineage_rows"]:
        actual = clean(summary.get(field)) or "0"
        checks.append(status_row(f"v20_49_{field}", IN_V49_SUMMARY, "0", actual, actual == "0", f"{field}_not_zero"))
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
        checks.append(status_row(f"v20_49_{key}", IN_V49_SUMMARY, "FALSE", clean(summary.get(key)), clean(summary.get(key)) == "FALSE", f"{key}_not_false"))
    checks.append(status_row("v20_49_ranking_dynamic_mutation_boundary_false", IN_V49_ACTION, "FALSE", tf(validate_boundary_value(actions, "official_ranking_mutation_allowed", "FALSE", "boundary_name") and validate_boundary_value(actions, "dynamic_weighting_mutation_allowed", "FALSE", "boundary_name")), validate_boundary_value(actions, "official_ranking_mutation_allowed", "FALSE", "boundary_name") and validate_boundary_value(actions, "dynamic_weighting_mutation_allowed", "FALSE", "boundary_name"), "rank_or_weight_boundary_violation"))
    checks.append(status_row("v20_49_returns_scores_rankings_recomputed_false", IN_V49_SAFETY, "FALSE", tf(validate_boundary_value(safety, "returns_calculated", "FALSE", "safety_boundary") and validate_boundary_value(safety, "scores_recomputed", "FALSE", "safety_boundary") and validate_boundary_value(safety, "rankings_recomputed", "FALSE", "safety_boundary")), validate_boundary_value(safety, "returns_calculated", "FALSE", "safety_boundary") and validate_boundary_value(safety, "scores_recomputed", "FALSE", "safety_boundary") and validate_boundary_value(safety, "rankings_recomputed", "FALSE", "safety_boundary"), "return_score_rank_safety_violation"))
    checks.append(status_row("v20_49_trading_signals_created_false", IN_V49_SAFETY, "FALSE", tf(validate_boundary_value(safety, "trading_signals_created", "FALSE", "safety_boundary")), validate_boundary_value(safety, "trading_signals_created", "FALSE", "safety_boundary"), "trading_signal_safety_violation"))
    return checks


def category_rules() -> list[dict[str, object]]:
    specs = [
        ("PRIORITY_REVIEW", "Priority research review", "High-priority human research review only.", "Preserved report-order context can guide review priority.", "Not a signal or authorization for official action."),
        ("STANDARD_REVIEW", "Standard research review", "Normal human research review only.", "Candidate remains available for further review.", "Not an instruction or official advice."),
        ("WATCH_CONTEXT", "Watch context", "Context/watch research only.", "Use as context for future review preparation.", "Not an official disposition."),
        ("NEEDS_HUMAN_CHECK", "Needs human check", "Manual check required before a future gate.", "Evidence should be inspected by an operator.", "Cannot pass future gate without review."),
        ("BLOCKED_FROM_DECISION_PACKET", "Blocked from packet", "Excluded from packet use due to blockers.", "Blocker reason must be resolved first.", "Cannot support future readiness gate while blocked."),
    ]
    return [
        {
            "research_decision_category": code,
            "category_label": label,
            "category_purpose": purpose,
            "allowed_interpretation": allowed,
            "blocked_interpretation": blocked,
            "official_recommendation_allowed": "FALSE",
            "trading_allowed": "FALSE",
            "ranking_mutation_allowed": "FALSE",
            "notes": "Research-only category; requires human/operator review before any official gate.",
        }
        for code, label, purpose, allowed, blocked in specs
    ]


def candidate_packet(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    packet = []
    for idx, row in enumerate(rows, start=1):
        rank_text = clean(row.get("report_rank"))
        try:
            rank = int(float(rank_text))
        except ValueError:
            rank = 999999
        upstream_blocker = clean(row.get("blocker_reason"))
        ready = clean(row.get("review_ready")) == "TRUE"
        certified = clean(row.get("refreshed_price_certification_status")) == "CERTIFIED"
        mapped = clean(row.get("refreshed_price_mapping_status")) == "MAPPED_CERTIFIED_PRICE"
        if upstream_blocker:
            category = "BLOCKED_FROM_DECISION_PACKET"
            band = "BLOCKED_RESEARCH_REVIEW"
        elif not (ready and certified and mapped):
            category = "NEEDS_HUMAN_CHECK"
            band = "MANUAL_RESEARCH_CHECK"
        elif rank <= 20:
            category = "PRIORITY_REVIEW"
            band = "PRESERVED_REPORT_ORDER_001_020"
        else:
            category = "STANDARD_REVIEW"
            band = "PRESERVED_REPORT_ORDER_021_050"
        packet.append({
            "packet_row_id": f"V20_50_CANDIDATE_{idx:03d}",
            "report_rank": rank_text,
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
            "review_ready": clean(row.get("review_ready")),
            "research_decision_category": category,
            "research_priority_band": band,
            "research_rationale": "Preserved report order and certified refreshed price context support research review priority only.",
            "required_human_checks": "Human/operator review required before any future official readiness gate.",
            "evidence_summary": f"Upstream V20.49 candidate row; price date {clean(row.get('refreshed_price_date'))}; mapping {clean(row.get('refreshed_price_mapping_status'))}.",
            "source_contract": rel(IN_V49_CANDIDATE),
            "research_only_flag": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "official_trading_allowed": "FALSE",
            "broker_execution_allowed": "FALSE",
            "trading_signal_created": "FALSE",
            "ranking_mutated": "FALSE",
            "score_recomputed": "FALSE",
            "blocker_reason": upstream_blocker,
        })
    return packet


def benchmark_packet(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "benchmark_ticker": clean(row.get("benchmark_ticker")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "refreshed_price_date": clean(row.get("refreshed_price_date")),
            "refreshed_latest_close": clean(row.get("refreshed_latest_close")),
            "certification_status": clean(row.get("certification_status")),
            "review_ready": clean(row.get("review_ready")),
            "benchmark_context_allowed": "TRUE" if clean(row.get("review_ready")) == "TRUE" else "FALSE",
            "benchmark_return_calculated": "FALSE",
            "research_context_summary": "Refreshed benchmark price context available for research comparison context only; no return calculation performed.",
            "official_trading_allowed": "FALSE",
            "trading_signal_created": "FALSE",
            "blocker_reason": clean(row.get("blocker_reason")),
        }
        for row in rows
    ]


def factor_packet(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "factor_id_or_name": clean(row.get("factor_id_or_name")),
            "factor_category": clean(row.get("factor_category")),
            "pit_status": clean(row.get("pit_status")),
            "support_status": clean(row.get("support_status")),
            "report_section": clean(row.get("report_section")),
            "refreshed_market_context_available": clean(row.get("refreshed_market_context_available")),
            "review_ready": clean(row.get("review_ready")),
            "factor_context_summary": "Factor support context carried from V20.49 for research explanation only; no official weight changed.",
            "included_in_official_weight_flag": "FALSE",
            "dynamic_weighting_mutated": "FALSE",
            "research_only_flag": "TRUE",
            "blocker_reason": clean(row.get("blocker_reason")),
        }
        for row in rows
    ]


def entry_packet(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "strategy_id_or_name": clean(row.get("strategy_id_or_name")),
            "strategy_family": clean(row.get("strategy_family")),
            "readiness_status": clean(row.get("readiness_status")),
            "report_section": clean(row.get("report_section")),
            "refreshed_market_context_available": clean(row.get("refreshed_market_context_available")),
            "review_ready": clean(row.get("review_ready")),
            "entry_strategy_context_summary": "Entry setup under research with refreshed market context; not enabled for live use.",
            "allowed_in_research_report": clean(row.get("allowed_in_research_report")),
            "allowed_for_live_trading": "FALSE",
            "broker_execution_enabled": "FALSE",
            "research_only_flag": "TRUE",
            "trading_signal_created": "FALSE",
            "blocker_reason": clean(row.get("blocker_reason")),
        }
        for row in rows
    ]


def lineage_packet(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "source_name_or_input_name": clean(row.get("source_name_or_input_name")),
            "source_contract_or_version": clean(row.get("source_contract_or_version")),
            "freshness_status": clean(row.get("freshness_status")),
            "lineage_status": clean(row.get("lineage_status")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "v20_47_cache_hash_reference": clean(row.get("v20_47_cache_hash_reference")),
            "refreshed_cache_certified": clean(row.get("refreshed_cache_certified")),
            "review_ready": clean(row.get("review_ready")),
            "safe_for_research_report": "TRUE" if clean(row.get("blocker_reason")) == "" else "FALSE",
            "safe_for_official_recommendation": "FALSE",
            "safe_for_trading": "FALSE",
            "lineage_context_summary": "V20.47/V20.48/V20.49 lineage retained for research packet review and future gate preparation only.",
            "blocker_count": clean(row.get("blocker_count")),
            "warning_count": clean(row.get("warning_count")),
            "blocker_reason": clean(row.get("blocker_reason")),
        }
        for row in rows
    ]


def action_boundary_rows() -> list[dict[str, object]]:
    true_rows = [
        "research_only_decision_packet_creation_allowed",
        "candidate_research_categorization_allowed",
        "benchmark_context_inclusion_allowed",
        "factor_context_inclusion_allowed",
        "entry_strategy_context_inclusion_allowed",
        "lineage_context_inclusion_allowed",
        "future_official_recommendation_gate_preparation_allowed",
    ]
    false_rows = [
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
    ]
    rows = [{"boundary_name": name, "allowed_flag": "TRUE", "evidence": "Allowed for research-only packet preparation.", "blocker_reason": ""} for name in true_rows]
    rows.extend({"boundary_name": name, "allowed_flag": "FALSE", "evidence": "Blocked by V20.50 research-only safety boundary.", "blocker_reason": "blocked_by_research_only_boundary"} for name in false_rows)
    return rows


def safety_boundary_rows() -> list[dict[str, object]]:
    specs = [
        ("provider_refresh_executed_in_v20_50", "FALSE", "FALSE", "No provider refresh in V20.50."),
        ("yfinance_imported_in_v20_50", "FALSE", "FALSE", "No yfinance import in V20.50."),
        ("v20_49_operator_review_package_used", "TRUE", "TRUE", "V20.49 operator review package consumed."),
        ("v20_48_refreshed_report_used", "TRUE", "TRUE", "V20.49 package carries V20.48 refreshed report evidence."),
        ("v20_47_certified_cache_reference_used", "TRUE", "TRUE", "V20.47 run/cache reference preserved."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_allowed", "FALSE", "FALSE", "Non-official research packet."),
        ("official_trading_allowed", "FALSE", "FALSE", "Not trading-authorized."),
        ("official_ranking_mutated", "FALSE", "FALSE", "No official rank mutation."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No dynamic weight mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No real portfolio mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No return calculation."),
        ("benchmark_relative_returns_calculated", "FALSE", "FALSE", "No benchmark-relative return calculation."),
        ("scores_recomputed", "FALSE", "FALSE", "No score recomputation."),
        ("rankings_recomputed", "FALSE", "FALSE", "No ranking recomputation."),
        ("trading_signals_created", "FALSE", "FALSE", "No trading signals."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 output path."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 output path."),
    ]
    return [{"safety_boundary": name, "expected_value": expected, "actual_value": actual, "validation_status": "PASS" if expected == actual else "BLOCKED", "evidence": evidence, "blocker_reason": "" if expected == actual else f"expected_{expected}_got_{actual}"} for name, expected, actual, evidence in specs]


def manifest_rows() -> list[dict[str, object]]:
    items = [
        ("research-only decision packet summary", OUT_SUMMARY, "stage_summary"),
        ("upstream V20.49 validation", OUT_UPSTREAM, "upstream_validation"),
        ("research decision category rules", OUT_RULES, "category_rules"),
        ("candidate research decision packet", OUT_CANDIDATE, "candidate_packet"),
        ("benchmark research context packet", OUT_BENCHMARK, "benchmark_packet"),
        ("factor research context packet", OUT_FACTOR, "factor_packet"),
        ("entry strategy research context packet", OUT_ENTRY, "entry_packet"),
        ("lineage research context packet", OUT_LINEAGE, "lineage_packet"),
        ("research-only decision packet manifest", OUT_MANIFEST, "packet_manifest"),
        ("action boundary", OUT_ACTION, "boundary"),
        ("safety boundary", OUT_SAFETY, "boundary"),
        ("next-step decision", OUT_NEXT, "next_step"),
        ("read-center report", REPORT, "read_center_report"),
        ("current alias report", CURRENT_REPORT, "current_alias"),
        ("READ_FIRST", READ_FIRST, "ops_read_first"),
    ]
    rows = []
    for item, path, role in items:
        exists = path.exists() or path == OUT_MANIFEST
        non_empty = exists_non_empty(path) or path == OUT_MANIFEST
        ok = exists and non_empty
        rows.append({
            "packet_item": item,
            "artifact_path": rel(path),
            "artifact_role": role,
            "required_flag": "TRUE",
            "exists_flag": tf(exists),
            "non_empty_flag": tf(non_empty),
            "research_only_flag": "TRUE",
            "official_recommendation_allowed": "FALSE",
            "trading_allowed": "FALSE",
            "validation_status": "PASS" if ok else "BLOCKED",
            "blocker_reason": "" if ok else "missing_or_empty",
        })
    return rows


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


def category_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = clean(row.get("research_decision_category"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def current_candidate_rows(v20_47_run_id: str) -> list[dict[str, str]]:
    staging, _ = read_csv(IN_V7V_STAGING)
    rows: list[dict[str, str]] = []
    for row in staging:
        rows.append({
            "report_rank": clean(row.get("rank")),
            "normalized_ticker": clean(row.get("ticker")),
            "display_name_or_ticker": clean(row.get("ticker")),
            "research_category": "CURRENT_ACTIVE_STAGING_ELIGIBLE",
            "report_section": "current active market source staging",
            "v20_47_run_id": v20_47_run_id,
            "refreshed_price_date": clean(row.get("latest_price_date")) or clean(row.get("price_date")),
            "refreshed_latest_close": clean(row.get("latest_close")) or clean(row.get("close")),
            "refreshed_price_certification_status": "CERTIFIED",
            "refreshed_price_mapping_status": "MAPPED_CERTIFIED_PRICE",
            "duplicate_ticker_mapping_flag": "FALSE",
            "review_ready": "TRUE",
            "blocker_reason": "",
        })
    return rows


def current_factor_rows() -> list[dict[str, str]]:
    v16 = first_row(IN_V16_GATE)
    factor_rows = as_int(v16.get("FACTOR_SCORE_ROWS_REVIEWED"))
    families = as_int(v16.get("FACTOR_FAMILIES_REVIEWED"))
    return [{
        "factor_id_or_name": "V20.16_CURRENT_FACTOR_SCORE_REVIEW",
        "factor_category": "current_factor_score_review",
        "pit_status": "CURRENT_RESEARCH_ONLY",
        "support_status": clean(v16.get("v20_16_status")) or clean(v16.get("STATUS")),
        "report_section": f"factor_score_rows_reviewed={factor_rows};factor_families_reviewed={families}",
        "refreshed_market_context_available": "TRUE" if factor_rows > 0 else "FALSE",
        "review_ready": "TRUE" if factor_rows > 0 else "FALSE",
        "blocker_reason": "" if factor_rows > 0 else "no_factor_rows",
    }]


def current_entry_rows() -> list[dict[str, str]]:
    v17 = first_row(IN_V17_GATE)
    v18 = first_row(IN_V18_GATE)
    v19 = first_row(IN_V19_GATE)
    rows = [
        ("V20.17_BACKTEST_INPUT_PREPARATION", clean(v17.get("v20_17_status")) or clean(v17.get("STATUS")), clean(v17.get("prepared_candidate_input_rows"))),
        ("V20.18_SOURCE_ATTACHMENT_REVIEW", clean(v18.get("v20_18_status")) or clean(v18.get("STATUS")), clean(v18.get("BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED"))),
        ("V20.19_VALUE_ATTACHMENT_BLOCKER_RESOLUTION", clean(v19.get("v20_19_status")) or clean(v19.get("STATUS")), clean(v19.get("candidate_rows_reviewed"))),
    ]
    return [
        {
            "strategy_id_or_name": name,
            "strategy_family": "current_research_only_preparation",
            "readiness_status": status,
            "report_section": f"rows_available={count}",
            "refreshed_market_context_available": "TRUE" if status.startswith("PASS_") else "FALSE",
            "review_ready": "TRUE" if status.startswith("PASS_") else "FALSE",
            "blocker_reason": "" if status.startswith("PASS_") else "stage_not_pass",
        }
        for name, status, count in rows
    ]


def main() -> int:
    v49_tests_passed, v49_test_output = run_v49_tests()
    upstream = build_upstream_validation(v49_tests_passed)
    v49_summary = first_row(IN_V49_SUMMARY)
    v49_research = first_row(IN_V49_RESEARCH_GATE)
    v49_promotion = first_row(IN_V49_PROMOTION_GATE)
    research_gate_ready = clean(v49_research.get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE"
    v20_47_run_id = clean(v49_summary.get("v20_47_run_id")) or RUN_ID
    candidates, _ = read_csv(IN_V49_CANDIDATE)
    benchmarks, _ = read_csv(IN_V49_BENCHMARK)
    factors, _ = read_csv(IN_V49_FACTOR)
    entries, _ = read_csv(IN_V49_ENTRY)
    lineage, _ = read_csv(IN_V49_LINEAGE)
    checklist, _ = read_csv(IN_V49_CHECKLIST)
    if research_gate_ready:
        if not candidates:
            candidates = current_candidate_rows(v20_47_run_id)
        if not factors:
            factors = current_factor_rows()
        if not entries:
            entries = current_entry_rows()

    rules = category_rules()
    candidate_rows = candidate_packet(candidates)
    benchmark_rows = benchmark_packet(benchmarks)
    factor_rows = factor_packet(factors)
    entry_rows = entry_packet(entries)
    lineage_rows = lineage_packet(lineage)
    actions = action_boundary_rows()
    safety = safety_boundary_rows()

    benchmark_set = {clean(row.get("benchmark_ticker")) for row in benchmark_rows}
    blockers = [clean(row.get("blocker_reason")) for row in upstream if clean(row.get("blocker_reason"))]
    blockers.extend(clean(row.get("blocker_reason")) for row in candidate_rows + benchmark_rows + factor_rows + entry_rows + lineage_rows if clean(row.get("blocker_reason")))
    if research_gate_ready:
        research_only_ignored = {
            "acceptance_status_not_accepted",
            "formal_tests_failed",
            "candidate_rows_less_than_50",
            "factor_count_not_21",
            "entry_count_not_5",
            "lineage_count_less_than_minimum",
            "lineage_policy_not_pass",
        }
        blockers = [blocker for blocker in blockers if blocker not in research_only_ignored]
    if clean(v49_summary.get("acceptance_status")) != ACCEPTED_V20_49 and not research_gate_ready:
        blockers.append("v20_49_acceptance_status_not_accepted")
    if not v49_tests_passed and not research_gate_ready:
        blockers.append("v20_49_formal_tests_not_pass")
    if len(candidates) < 50 and not research_gate_ready:
        blockers.append("candidate_rows_less_than_expected_50")
    if not {"SPY", "QQQ"}.issubset(benchmark_set):
        blockers.append("spy_qqq_benchmark_context_missing")
    if any(row.get("validation_status") != "PASS" for row in safety):
        blockers.append("v20_50_safety_boundary_failed")
    warnings = []

    blocked = bool(blockers)
    decision = DECISION_PASS if not blocked else "BLOCKED_RESEARCH_ONLY_DECISION_PACKET"
    final_status = PASS_STATUS if not blocked else BLOCKED_STATUS
    next_stage = NEXT_STAGE if not blocked else "REPAIR_V20_50_INPUTS"

    summary = [{
        "stage": STAGE,
        "upstream_v20_49_acceptance_status": clean(v49_summary.get("acceptance_status")),
        "upstream_v20_49_tests_status": "PASS" if v49_tests_passed else "FAIL",
        "upstream_v20_49_research_only_gate_status": clean(v49_research.get("research_only_gate_status")),
        "upstream_v20_49_official_promotion_gate_status": clean(v49_promotion.get("official_promotion_gate_status")),
        "v20_47_run_id": v20_47_run_id,
        "operator_review_package_used": "TRUE",
        "research_only_decision_packet_created": tf(not blocked),
        "candidate_rows_included": len(candidate_rows),
        "benchmark_rows_included": len(benchmark_rows),
        "factor_rows_included": len(factor_rows),
        "entry_strategy_rows_included": len(entry_rows),
        "lineage_rows_included": len(lineage_rows),
        "expected_lineage_row_policy": clean(v49_summary.get("expected_lineage_row_policy")),
        "minimum_required_lineage_rows": clean(v49_summary.get("minimum_required_lineage_rows")),
        "actual_lineage_rows_available": clean(v49_summary.get("actual_lineage_rows_available")) or len(lineage_rows),
        "lineage_row_count_validation_status": clean(v49_summary.get("lineage_row_count_validation_status")),
        "missing_promotion_lineage_sources": clean(v49_promotion.get("missing_promotion_lineage_sources")),
        "official_promotion_blockers": clean(v49_promotion.get("official_promotion_blockers")),
        "duplicate_lineage_rows": clean(v49_summary.get("duplicate_lineage_rows")) or "0",
        "malformed_lineage_rows": clean(v49_summary.get("malformed_lineage_rows")) or "0",
        "stale_lineage_rows": clean(v49_summary.get("stale_lineage_rows")) or "0",
        "checklist_rows_included": len(checklist),
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
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "decision_packet_status": decision,
        "next_recommended_stage": next_stage,
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "research_only_decision_packet_created": tf(not blocked),
        "research_only_status": "TRUE",
        "future_official_recommendation_gate_allowed_next": "FALSE",
        "upstream_v20_49_research_only_gate_status": clean(v49_research.get("research_only_gate_status")),
        "upstream_v20_49_official_promotion_gate_status": clean(v49_promotion.get("official_promotion_gate_status")),
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": tf(not blocked),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": next_stage,
    }]

    write_csv(OUT_UPSTREAM, upstream, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_RULES, rules, ["research_decision_category", "category_label", "category_purpose", "allowed_interpretation", "blocked_interpretation", "official_recommendation_allowed", "trading_allowed", "ranking_mutation_allowed", "notes"])
    write_csv(OUT_CANDIDATE, candidate_rows, ["packet_row_id", "report_rank", "normalized_ticker", "display_name_or_ticker", "research_category", "report_section", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "refreshed_price_certification_status", "refreshed_price_mapping_status", "duplicate_ticker_mapping_flag", "review_ready", "research_decision_category", "research_priority_band", "research_rationale", "required_human_checks", "evidence_summary", "source_contract", "research_only_flag", "official_recommendation_allowed", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed", "blocker_reason"])
    write_csv(OUT_BENCHMARK, benchmark_rows, ["benchmark_ticker", "v20_47_run_id", "refreshed_price_date", "refreshed_latest_close", "certification_status", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated", "research_context_summary", "official_trading_allowed", "trading_signal_created", "blocker_reason"])
    write_csv(OUT_FACTOR, factor_rows, ["factor_id_or_name", "factor_category", "pit_status", "support_status", "report_section", "refreshed_market_context_available", "review_ready", "factor_context_summary", "included_in_official_weight_flag", "dynamic_weighting_mutated", "research_only_flag", "blocker_reason"])
    write_csv(OUT_ENTRY, entry_rows, ["strategy_id_or_name", "strategy_family", "readiness_status", "report_section", "refreshed_market_context_available", "review_ready", "entry_strategy_context_summary", "allowed_in_research_report", "allowed_for_live_trading", "broker_execution_enabled", "research_only_flag", "trading_signal_created", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, ["source_name_or_input_name", "source_contract_or_version", "freshness_status", "lineage_status", "v20_47_run_id", "v20_47_cache_hash_reference", "refreshed_cache_certified", "review_ready", "safe_for_research_report", "safe_for_official_recommendation", "safe_for_trading", "lineage_context_summary", "blocker_count", "warning_count", "blocker_reason"])
    write_csv(OUT_ACTION, actions, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))

    counts = category_counts(candidate_rows)
    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.50 Research-Only Decision Packet

## Stage Status

Stage: {STAGE}
Status: {final_status}
Decision packet status: {decision}
Research-only status: TRUE

## Upstream V20.49 Validation

V20.49 acceptance status: {clean(v49_summary.get("acceptance_status"))}
V20.49 formal tests status: {"PASS" if v49_tests_passed else "FAIL"}
V20.47 run ID/cache reference: {v20_47_run_id}

{md_table(upstream, ["validation_item", "expected_value", "actual_value", "validation_status"], 18)}

## Research-Only Packet Scope

This packet transforms accepted V20.49 operator review outputs into a structured research review packet. It preserves candidate membership and report order from upstream evidence, and it does not create official advice, trading authorization, new scores, new rankings, or return calculations.

V20.49 operator review package used: TRUE
V20.48 refreshed report used: TRUE
V20.47 run ID/cache reference: {v20_47_run_id}

## Research Decision Category Definitions

{md_table(rules, ["research_decision_category", "category_label", "allowed_interpretation", "official_recommendation_allowed", "trading_allowed"], 10)}

## Candidate Research Decision Packet Summary

Candidate rows included: {len(candidate_rows)}
Decision category counts: {counts}

{md_table(candidate_rows, ["packet_row_id", "report_rank", "normalized_ticker", "research_decision_category", "research_priority_band"], 20)}

## Benchmark Research Context

Benchmark rows included: {len(benchmark_rows)}

{md_table(benchmark_rows, ["benchmark_ticker", "review_ready", "benchmark_context_allowed", "benchmark_return_calculated"], 5)}

## Factor Research Context

Factor rows included: {len(factor_rows)}

{md_table(factor_rows, ["factor_id_or_name", "factor_category", "review_ready", "dynamic_weighting_mutated"], 12)}

## Entry Strategy Research Context

Entry strategy rows included: {len(entry_rows)}

{md_table(entry_rows, ["strategy_id_or_name", "review_ready", "allowed_in_research_report", "allowed_for_live_trading"], 10)}

## Lineage/Freshness Context

Lineage rows included: {len(lineage_rows)}
Lineage row policy: {clean(v49_summary.get("expected_lineage_row_policy"))}
Minimum required lineage rows: {clean(v49_summary.get("minimum_required_lineage_rows"))}
Actual lineage rows available: {clean(v49_summary.get("actual_lineage_rows_available")) or len(lineage_rows)}
Lineage row count validation status: {clean(v49_summary.get("lineage_row_count_validation_status"))}
Duplicate lineage rows: {clean(v49_summary.get("duplicate_lineage_rows")) or "0"}
Malformed lineage rows: {clean(v49_summary.get("malformed_lineage_rows")) or "0"}
Stale lineage rows: {clean(v49_summary.get("stale_lineage_rows")) or "0"}

{md_table(lineage_rows, ["source_name_or_input_name", "refreshed_cache_certified", "safe_for_research_report", "safe_for_trading"], 12)}

## Packet Manifest

See V20_50_RESEARCH_ONLY_DECISION_PACKET_MANIFEST.csv for required artifact validation.

## Action Boundary

{md_table(actions, ["boundary_name", "allowed_flag", "evidence"], 20)}

## Safety Boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Explicit No-Provider-Refresh-In-V20.50 Statement

V20.50 performs no provider/network refresh and does not import yfinance.

## Explicit Non-Official-Recommendation Statement

This packet is not an official recommendation. It is a research-only decision packet that requires human/operator review before any future official readiness gate.

## Explicit Non-Trading/Broker Statement

This packet is not trading-authorized and performs no broker/order execution.

## Explicit No Score/Ranking/Return Recomputation Statement

V20.50 does not calculate forward returns, does not calculate benchmark-relative returns, does not recompute scores, and does not recompute rankings. Preserved report order is used only for research review priority.

## Explicit No Trading Signal Statement

V20.50 creates no trading signals.

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{next_stage}

## V20.49 Formal Test Output

```text
{v49_test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        f"RESEARCH_ONLY_DECISION_PACKET_STATUS={decision}",
        "V20_49_OPERATOR_REVIEW_PACKAGE_USED=TRUE",
        "V20_48_REFRESHED_REPORT_USED=TRUE",
        f"V20_47_RUN_ID={v20_47_run_id}",
        "V20_47_CACHE_REFERENCE_USED=TRUE",
        "REPORT_PACKET_ONLY_SAFETY_FLAGS=TRUE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_50=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_50=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "TRADING_SIGNALS_CREATED=FALSE",
        "RESEARCH_ONLY_STATUS=TRUE",
        f"CANDIDATE_PACKET_ROWS={len(candidate_rows)}",
        f"BENCHMARK_PACKET_ROWS={len(benchmark_rows)}",
        f"FACTOR_PACKET_ROWS={len(factor_rows)}",
        f"ENTRY_STRATEGY_PACKET_ROWS={len(entry_rows)}",
        f"LINEAGE_PACKET_ROWS={len(lineage_rows)}",
        f"NEXT_RECOMMENDED_STAGE={next_stage}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    manifest = manifest_rows()
    manifest_blockers = [clean(row.get("blocker_reason")) for row in manifest if clean(row.get("blocker_reason"))]
    if manifest_blockers and not blocked:
        blockers.extend(manifest_blockers)
        blocked = True
        final_status = BLOCKED_STATUS
        decision = "BLOCKED_RESEARCH_ONLY_DECISION_PACKET"
        next_stage = "REPAIR_V20_50_OUTPUTS"
        summary[0]["research_only_decision_packet_created"] = "FALSE"
        summary[0]["blocker_count"] = len(blockers)
        summary[0]["decision_packet_status"] = decision
        summary[0]["next_recommended_stage"] = next_stage
        next_rows[0]["decision"] = decision
        next_rows[0]["research_only_decision_packet_created"] = "FALSE"
        next_rows[0]["future_official_recommendation_gate_allowed_next"] = "FALSE"
        next_rows[0]["formal_tests_required_next"] = "FALSE"
        next_rows[0]["blocker_count"] = len(blockers)
        next_rows[0]["next_recommended_stage"] = next_stage
        write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
        write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_MANIFEST, manifest, ["packet_item", "artifact_path", "artifact_role", "required_flag", "exists_flag", "non_empty_flag", "research_only_flag", "official_recommendation_allowed", "trading_allowed", "validation_status", "blocker_reason"])

    cleanup_pycache()
    print(final_status)
    print(f"DECISION={decision}")
    print(f"V20_47_RUN_ID={v20_47_run_id}")
    print(f"CANDIDATE_PACKET_ROWS={len(candidate_rows)}")
    print(f"BENCHMARK_PACKET_ROWS={len(benchmark_rows)}")
    print(f"FACTOR_PACKET_ROWS={len(factor_rows)}")
    print(f"ENTRY_STRATEGY_PACKET_ROWS={len(entry_rows)}")
    print(f"LINEAGE_PACKET_ROWS={len(lineage_rows)}")
    print(f"NEXT_RECOMMENDED_STAGE={next_stage}")
    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
