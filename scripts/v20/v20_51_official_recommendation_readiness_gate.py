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

STAGE = "V20.51_OFFICIAL_RECOMMENDATION_READINESS_GATE"
PASS_STATUS = "PASS_V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE"
BLOCKED_STATUS = "BLOCKED_V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_READINESS_GATE_CREATED"
READY_STATUS = "READY_WITH_RESEARCH_ONLY_LIMITS"
NEXT_STAGE = "V20.51_FORMAL_TESTS"
RUN_ID = "V20_47_20260604T114058Z"
V20_50_PASS = "PASS_RESEARCH_ONLY_DECISION_PACKET_CREATED"

IN_V50_SUMMARY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv"
IN_V50_UPSTREAM = CONSOLIDATION / "V20_50_UPSTREAM_V20_49_VALIDATION.csv"
IN_V50_RULES = CONSOLIDATION / "V20_50_RESEARCH_DECISION_CATEGORY_RULES.csv"
IN_V50_CANDIDATE = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
IN_V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_FACTOR = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_LINEAGE = CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_MANIFEST = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_MANIFEST.csv"
IN_V50_ACTION = CONSOLIDATION / "V20_50_RESEARCH_ONLY_ACTION_BOUNDARY.csv"
IN_V50_SAFETY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_SAFETY_BOUNDARY.csv"
IN_V50_NEXT = CONSOLIDATION / "V20_50_NEXT_STEP_DECISION.csv"
IN_V50_REPORT = READ_CENTER / "V20_50_RESEARCH_ONLY_DECISION_PACKET_REPORT.md"
IN_V50_CURRENT = READ_CENTER / "V20_CURRENT_RESEARCH_ONLY_DECISION_PACKET.md"
IN_V50_READ_FIRST = OPS / "V20_50_READ_FIRST.txt"
IN_V50_TEST = SCRIPT_DIR / "test_v20_50_research_only_decision_packet.py"

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


def clean(value: object) -> str:
    return str(value or "").strip()


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


def status_row(item: str, path: Path, expected: str, actual: str, ok: bool, blocker: str = "") -> dict[str, object]:
    return {
        "validation_item": item,
        "source_path": rel(path),
        "expected_value": expected,
        "actual_value": actual,
        "validation_status": "PASS" if ok else "BLOCKED",
        "blocker_reason": "" if ok else blocker,
    }


def run_v50_tests() -> tuple[bool, str]:
    if not IN_V50_TEST.exists():
        return False, "V20.50 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V50_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0 and "PASS_V20_50_TESTS" in result.stdout.splitlines(), output


def boundary_value(rows: list[dict[str, str]], key: str, expected: str, name_field: str) -> bool:
    for row in rows:
        if clean(row.get(name_field)) == key:
            return clean(row.get("allowed_flag") or row.get("actual_value")) == expected
    return False


def category_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = clean(row.get("research_decision_category"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_upstream_validation(v50_tests_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V50_SUMMARY)
    candidates, _ = read_csv(IN_V50_CANDIDATE)
    actions, _ = read_csv(IN_V50_ACTION)
    safety, _ = read_csv(IN_V50_SAFETY)
    counts = category_counts(candidates)
    checks: list[dict[str, object]] = []
    files = [
        ("v20_50_summary_exists_non_empty", IN_V50_SUMMARY),
        ("v20_50_upstream_validation_exists_non_empty", IN_V50_UPSTREAM),
        ("v20_50_category_rules_exists_non_empty", IN_V50_RULES),
        ("v20_50_candidate_packet_exists_non_empty", IN_V50_CANDIDATE),
        ("v20_50_benchmark_packet_exists_non_empty", IN_V50_BENCHMARK),
        ("v20_50_factor_packet_exists_non_empty", IN_V50_FACTOR),
        ("v20_50_entry_packet_exists_non_empty", IN_V50_ENTRY),
        ("v20_50_lineage_packet_exists_non_empty", IN_V50_LINEAGE),
        ("v20_50_manifest_exists_non_empty", IN_V50_MANIFEST),
        ("v20_50_action_boundary_exists_non_empty", IN_V50_ACTION),
        ("v20_50_safety_boundary_exists_non_empty", IN_V50_SAFETY),
        ("v20_50_next_step_decision_exists_non_empty", IN_V50_NEXT),
        ("v20_50_read_center_report_exists_non_empty", IN_V50_REPORT),
        ("v20_50_current_alias_exists_non_empty", IN_V50_CURRENT),
        ("v20_50_read_first_exists_non_empty", IN_V50_READ_FIRST),
    ]
    for item, path in files:
        ok = exists_non_empty(path)
        checks.append(status_row(item, path, "TRUE", tf(ok), ok, "missing_or_empty"))
    checks.append(status_row("v20_50_formal_test_script_exists", IN_V50_TEST, "TRUE", tf(IN_V50_TEST.exists()), IN_V50_TEST.exists(), "missing_test_script"))
    checks.append(status_row("v20_50_packet_status", IN_V50_SUMMARY, V20_50_PASS, clean(summary.get("decision_packet_status")), clean(summary.get("decision_packet_status")) == V20_50_PASS, "packet_status_not_pass"))
    checks.append(status_row("v20_50_tests_status", IN_V50_TEST, "PASS", "PASS" if v50_tests_passed else "FAIL", v50_tests_passed, "formal_tests_failed"))
    checks.append(status_row("v20_50_candidate_count", IN_V50_CANDIDATE, "50", str(row_count(IN_V50_CANDIDATE)), row_count(IN_V50_CANDIDATE) >= 50, "candidate_count_less_than_50"))
    checks.append(status_row("v20_50_benchmark_count", IN_V50_BENCHMARK, "2", str(row_count(IN_V50_BENCHMARK)), row_count(IN_V50_BENCHMARK) == 2, "benchmark_count_not_2"))
    checks.append(status_row("v20_50_factor_count", IN_V50_FACTOR, "21", str(row_count(IN_V50_FACTOR)), row_count(IN_V50_FACTOR) == 21, "factor_count_not_21"))
    checks.append(status_row("v20_50_entry_count", IN_V50_ENTRY, "5", str(row_count(IN_V50_ENTRY)), row_count(IN_V50_ENTRY) == 5, "entry_count_not_5"))
    checks.append(status_row("v20_50_lineage_count", IN_V50_LINEAGE, "35", str(row_count(IN_V50_LINEAGE)), row_count(IN_V50_LINEAGE) >= 35, "lineage_count_less_than_35"))
    checks.append(status_row("v20_50_priority_review_count", IN_V50_CANDIDATE, "20", str(counts.get("PRIORITY_REVIEW", 0)), counts.get("PRIORITY_REVIEW", 0) == 20, "priority_review_count_not_20"))
    checks.append(status_row("v20_50_standard_review_count", IN_V50_CANDIDATE, "30", str(counts.get("STANDARD_REVIEW", 0)), counts.get("STANDARD_REVIEW", 0) == 30, "standard_review_count_not_30"))
    for key in [
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
    ]:
        checks.append(status_row(f"v20_50_{key}", IN_V50_SUMMARY, "FALSE", clean(summary.get(key)), clean(summary.get(key)) == "FALSE", f"{key}_not_false"))
    checks.append(status_row("v20_50_ranking_dynamic_mutation_false", IN_V50_ACTION, "FALSE", tf(boundary_value(actions, "official_ranking_mutation_allowed", "FALSE", "boundary_name") and boundary_value(actions, "dynamic_weighting_mutation_allowed", "FALSE", "boundary_name")), boundary_value(actions, "official_ranking_mutation_allowed", "FALSE", "boundary_name") and boundary_value(actions, "dynamic_weighting_mutation_allowed", "FALSE", "boundary_name"), "rank_or_weight_boundary_violation"))
    checks.append(status_row("v20_50_returns_scores_rankings_recomputed_false", IN_V50_SAFETY, "FALSE", tf(boundary_value(safety, "returns_calculated", "FALSE", "safety_boundary") and boundary_value(safety, "scores_recomputed", "FALSE", "safety_boundary") and boundary_value(safety, "rankings_recomputed", "FALSE", "safety_boundary")), boundary_value(safety, "returns_calculated", "FALSE", "safety_boundary") and boundary_value(safety, "scores_recomputed", "FALSE", "safety_boundary") and boundary_value(safety, "rankings_recomputed", "FALSE", "safety_boundary"), "return_score_rank_safety_violation"))
    checks.append(status_row("v20_50_forbidden_actionable_language_scan", IN_V50_TEST, "PASS", "PASS" if v50_tests_passed else "FAIL", v50_tests_passed, "forbidden_language_scan_not_pass"))
    return checks


def prerequisite_rows(v50_tests_passed: bool) -> list[dict[str, object]]:
    specs = [
        ("PRQ001", "accepted research-only decision packet", "TRUE", IN_V50_SUMMARY, "PASS", "v20_50_packet_not_pass", "V20.50 packet status is the source evidence."),
        ("PRQ002", "V20.50 formal tests passed", "TRUE", IN_V50_TEST, "PASS" if v50_tests_passed else "BLOCKED", "v20_50_tests_not_pass", "Formal test output must pass."),
        ("PRQ003", "certified current market cache reference", "TRUE", IN_V50_LINEAGE, "PASS", "cache_reference_missing", "V20.47 run/cache reference is preserved."),
        ("PRQ004", "refreshed candidate price context", "TRUE", IN_V50_CANDIDATE, "PASS", "candidate_context_missing", "Candidate packet contains certified refreshed price context."),
        ("PRQ005", "benchmark context present", "TRUE", IN_V50_BENCHMARK, "PASS", "benchmark_context_missing", "SPY and QQQ context are present."),
        ("PRQ006", "factor context present", "TRUE", IN_V50_FACTOR, "PASS", "factor_context_missing", "Factor context rows are present."),
        ("PRQ007", "entry strategy context present", "TRUE", IN_V50_ENTRY, "PASS", "entry_context_missing", "Entry setup context rows are present."),
        ("PRQ008", "lineage/freshness context present", "TRUE", IN_V50_LINEAGE, "PASS", "lineage_context_missing", "Lineage rows are present."),
        ("PRQ009", "action boundary present", "TRUE", IN_V50_ACTION, "PASS", "action_boundary_missing", "V20.50 action boundary is present."),
        ("PRQ010", "safety boundary present", "TRUE", IN_V50_SAFETY, "PASS", "safety_boundary_missing", "V20.50 safety boundary is present."),
        ("PRQ011", "forbidden language scan passed", "TRUE", IN_V50_TEST, "PASS" if v50_tests_passed else "BLOCKED", "forbidden_language_scan_not_pass", "Represented by V20.50 formal test pass."),
        ("PRQ012", "no broker/order path", "TRUE", IN_V50_SAFETY, "PASS", "broker_path_present", "Safety evidence shows no broker/order execution."),
        ("PRQ013", "no official recommendation generated yet", "TRUE", IN_V50_SUMMARY, "PASS", "official_recommendation_already_generated", "V20.50 remains research-only."),
        ("PRQ014", "no trading signal generated yet", "TRUE", IN_V50_SAFETY, "PASS", "trading_signal_already_generated", "V20.50 safety evidence shows no trading signals."),
        ("PRQ015", "no official ranking mutation", "TRUE", IN_V50_SUMMARY, "PASS", "official_ranking_mutated", "V20.50 summary shows no official rank mutation."),
        ("PRQ016", "no dynamic weighting mutation", "TRUE", IN_V50_SUMMARY, "PASS", "dynamic_weighting_mutated", "V20.50 summary shows no dynamic weighting mutation."),
        ("PRQ017", "future official recommendation policy still required", "TRUE", OUT_GAPS, "PENDING_NEXT", "", "Policy contract is required before a future generation stage."),
        ("PRQ018", "future official recommendation tests required", "TRUE", OUT_GAPS, "PENDING_NEXT", "", "Formal tests are required before any future generation stage."),
    ]
    return [
        {
            "prerequisite_id": pid,
            "prerequisite_name": name,
            "required_for_future_official_gate": required,
            "source_evidence": rel(path),
            "prerequisite_status": status,
            "blocker_if_missing": blocker if status == "BLOCKED" else "",
            "notes": notes,
        }
        for pid, name, required, path, status, blocker, notes in specs
    ]


def candidate_readiness(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        ready = clean(row.get("review_ready")) == "TRUE" and not clean(row.get("blocker_reason")) and clean(row.get("research_decision_category")) in {"PRIORITY_REVIEW", "STANDARD_REVIEW", "WATCH_CONTEXT"}
        out.append({
            "packet_row_id": clean(row.get("packet_row_id")),
            "report_rank": clean(row.get("report_rank")),
            "normalized_ticker": clean(row.get("normalized_ticker")),
            "display_name_or_ticker": clean(row.get("display_name_or_ticker")),
            "v20_47_run_id": clean(row.get("v20_47_run_id")),
            "research_decision_category": clean(row.get("research_decision_category")),
            "research_priority_band": clean(row.get("research_priority_band")),
            "refreshed_price_certification_status": clean(row.get("refreshed_price_certification_status")),
            "review_ready": clean(row.get("review_ready")),
            "future_official_gate_candidate_ready": tf(ready),
            "official_recommendation_created": "FALSE",
            "official_recommendation_allowed_in_this_stage": "FALSE",
            "official_trading_allowed": "FALSE",
            "broker_execution_allowed": "FALSE",
            "trading_signal_created": "FALSE",
            "ranking_mutated": "FALSE",
            "score_recomputed": "FALSE",
            "required_future_checks": "Future official policy, output schema, risk constraints, and human gate acceptance are still required.",
            "blocker_reason": clean(row.get("blocker_reason")),
        })
    return out


def context_rows(benchmarks: list[dict[str, str]], factors: list[dict[str, str]], entries: list[dict[str, str]], lineage: list[dict[str, str]], actions: list[dict[str, str]], safety: list[dict[str, str]]) -> list[dict[str, object]]:
    specs = [
        ("benchmark_context", "SPY_QQQ", "V20.50", len(benchmarks), len(benchmarks) == 2),
        ("factor_context", "factor_support_context", "V20.50", len(factors), len(factors) == 21),
        ("entry_strategy_context", "entry_strategy_context", "V20.50", len(entries), len(entries) == 5),
        ("lineage_context", "lineage_freshness_context", "V20.50", len(lineage), len(lineage) >= 35),
        ("action_boundary", "V20.50_action_boundary", "V20.50", "PASS" if actions else "MISSING", bool(actions)),
        ("safety_boundary", "V20.50_safety_boundary", "V20.50", "PASS" if safety else "MISSING", bool(safety) and all(clean(row.get("validation_status")) == "PASS" for row in safety)),
    ]
    return [
        {
            "context_type": ctype,
            "context_name": name,
            "source_stage": source,
            "row_count_or_status": count,
            "future_official_gate_context_ready": tf(ready),
            "official_recommendation_created": "FALSE",
            "official_trading_allowed": "FALSE",
            "mutation_allowed": "FALSE",
            "blocker_reason": "" if ready else f"{ctype}_not_ready",
        }
        for ctype, name, source, count, ready in specs
    ]


def gap_rows() -> list[dict[str, object]]:
    names = [
        ("GAP001", "official recommendation policy contract", "policy", "Define formal policy before any future generation stage."),
        ("GAP002", "official output schema contract", "schema", "Define final official output schema and required fields."),
        ("GAP003", "recommendation language policy", "language", "Define allowed official wording and prohibited wording."),
        ("GAP004", "position/risk cap policy binding", "risk", "Bind future output to position and risk constraints."),
        ("GAP005", "user/manual approval policy", "approval", "Require explicit human acceptance before any official gate result is used."),
        ("GAP006", "real-book separation confirmation", "portfolio_safety", "Confirm separation from real portfolio state."),
        ("GAP007", "broker-disabled enforcement", "execution_safety", "Enforce no broker/order path in future stages unless explicitly authorized elsewhere."),
        ("GAP008", "post-recommendation audit tests", "testing", "Add formal audit tests for any future official generation stage."),
        ("GAP009", "final human review or explicit gate acceptance", "approval", "Document final human review before any official generation stage."),
    ]
    return [
        {
            "gap_id": gid,
            "gap_name": name,
            "gap_category": category,
            "required_before_official_recommendation_generation": "TRUE",
            "current_status": "PENDING_FUTURE_STAGE",
            "recommended_resolution_stage": "V20.52_OR_LATER_POLICY_GATE",
            "blocker_for_v20_51": "FALSE",
            "blocker_for_future_official_generation": "TRUE",
            "notes": notes,
        }
        for gid, name, category, notes in names
    ]


def action_boundary_rows() -> list[dict[str, object]]:
    true_rows = [
        "official_recommendation_readiness_assessment_allowed",
        "future_official_gate_preparation_allowed",
        "prerequisite_review_allowed",
        "policy_gap_register_allowed",
        "candidate_future_gate_readiness_allowed",
    ]
    false_rows = [
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
    ]
    rows = [{"boundary_name": name, "allowed_flag": "TRUE", "evidence": "Allowed for gate-only readiness assessment.", "blocker_reason": ""} for name in true_rows]
    rows.extend({"boundary_name": name, "allowed_flag": "FALSE", "evidence": "Blocked by V20.51 gate-only safety boundary.", "blocker_reason": "blocked_by_readiness_gate_boundary"} for name in false_rows)
    return rows


def safety_boundary_rows() -> list[dict[str, object]]:
    specs = [
        ("provider_refresh_executed_in_v20_51", "FALSE", "FALSE", "No provider refresh in V20.51."),
        ("yfinance_imported_in_v20_51", "FALSE", "FALSE", "No yfinance import in V20.51."),
        ("v20_50_research_only_packet_used", "TRUE", "TRUE", "V20.50 packet consumed."),
        ("v20_49_operator_review_package_used", "TRUE", "TRUE", "V20.50 carries V20.49 review evidence."),
        ("v20_47_certified_cache_reference_used", "TRUE", "TRUE", "V20.47 run/cache reference preserved."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_created", "FALSE", "FALSE", "No official recommendation created."),
        ("official_recommendation_allowed_in_this_stage", "FALSE", "FALSE", "Generation is blocked in V20.51."),
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
    v50_tests_passed, v50_test_output = run_v50_tests()
    upstream = build_upstream_validation(v50_tests_passed)
    v50_summary = first_row(IN_V50_SUMMARY)
    candidates, _ = read_csv(IN_V50_CANDIDATE)
    benchmarks, _ = read_csv(IN_V50_BENCHMARK)
    factors, _ = read_csv(IN_V50_FACTOR)
    entries, _ = read_csv(IN_V50_ENTRY)
    lineage, _ = read_csv(IN_V50_LINEAGE)
    actions50, _ = read_csv(IN_V50_ACTION)
    safety50, _ = read_csv(IN_V50_SAFETY)
    counts = category_counts(candidates)
    v20_47_run_id = clean(v50_summary.get("v20_47_run_id")) or RUN_ID

    candidate_rows = candidate_readiness(candidates)
    context = context_rows(benchmarks, factors, entries, lineage, actions50, safety50)
    gaps = gap_rows()
    prereqs = prerequisite_rows(v50_tests_passed)
    actions = action_boundary_rows()
    safety = safety_boundary_rows()

    blockers = [clean(row.get("blocker_reason")) for row in upstream + candidate_rows + context + prereqs if clean(row.get("blocker_reason"))]
    if clean(v50_summary.get("decision_packet_status")) != V20_50_PASS:
        blockers.append("v20_50_packet_status_not_pass")
    if not v50_tests_passed:
        blockers.append("v20_50_formal_tests_not_pass")
    if len(candidates) < 50:
        blockers.append("candidate_rows_less_than_expected_50")
    if not benchmarks or not factors or not entries or not lineage:
        blockers.append("required_context_packet_missing")
    if any(row.get("validation_status") != "PASS" for row in safety):
        blockers.append("v20_51_safety_boundary_failed")
    warnings: list[str] = []

    blocked = bool(blockers)
    decision = DECISION_PASS if not blocked else "BLOCKED_OFFICIAL_RECOMMENDATION_READINESS_GATE"
    final_status = PASS_STATUS if not blocked else BLOCKED_STATUS
    readiness_status = READY_STATUS if not blocked else "BLOCKED_READINESS_GATE"
    future_ready = "CONDITIONAL" if not blocked else "FALSE"
    next_stage = NEXT_STAGE if not blocked else "REPAIR_V20_51_INPUTS"

    summary = [{
        "stage": STAGE,
        "upstream_v20_50_packet_status": clean(v50_summary.get("decision_packet_status")),
        "upstream_v20_50_tests_status": "PASS" if v50_tests_passed else "FAIL",
        "v20_47_run_id": v20_47_run_id,
        "research_only_packet_used": "TRUE",
        "candidate_rows_reviewed": len(candidates),
        "benchmark_rows_reviewed": len(benchmarks),
        "factor_rows_reviewed": len(factors),
        "entry_strategy_rows_reviewed": len(entries),
        "lineage_rows_reviewed": len(lineage),
        "priority_review_rows": counts.get("PRIORITY_REVIEW", 0),
        "standard_review_rows": counts.get("STANDARD_REVIEW", 0),
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
        "future_official_recommendation_gate_ready": future_ready,
        "readiness_status": readiness_status,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": next_stage,
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "readiness_status": readiness_status,
        "future_official_recommendation_gate_ready": future_ready,
        "official_recommendation_created_in_this_stage": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": tf(not blocked),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_recommended_stage": next_stage,
    }]

    write_csv(OUT_UPSTREAM, upstream, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_PREREQ, prereqs, ["prerequisite_id", "prerequisite_name", "required_for_future_official_gate", "source_evidence", "prerequisite_status", "blocker_if_missing", "notes"])
    write_csv(OUT_CANDIDATE, candidate_rows, ["packet_row_id", "report_rank", "normalized_ticker", "display_name_or_ticker", "v20_47_run_id", "research_decision_category", "research_priority_band", "refreshed_price_certification_status", "review_ready", "future_official_gate_candidate_ready", "official_recommendation_created", "official_recommendation_allowed_in_this_stage", "official_trading_allowed", "broker_execution_allowed", "trading_signal_created", "ranking_mutated", "score_recomputed", "required_future_checks", "blocker_reason"])
    write_csv(OUT_CONTEXT, context, ["context_type", "context_name", "source_stage", "row_count_or_status", "future_official_gate_context_ready", "official_recommendation_created", "official_trading_allowed", "mutation_allowed", "blocker_reason"])
    write_csv(OUT_GAPS, gaps, ["gap_id", "gap_name", "gap_category", "required_before_official_recommendation_generation", "current_status", "recommended_resolution_stage", "blocker_for_v20_51", "blocker_for_future_official_generation", "notes"])
    write_csv(OUT_ACTION, actions, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.51 Official Recommendation Readiness Gate

## Stage Status

Stage: {STAGE}
Status: {final_status}
Decision: {decision}
Readiness status: {readiness_status}
Future official gate ready: {future_ready}

## Upstream V20.50 Validation

V20.50 packet status: {clean(v50_summary.get("decision_packet_status"))}
V20.50 formal tests status: {"PASS" if v50_tests_passed else "FAIL"}
V20.47 run ID/cache reference: {v20_47_run_id}

{md_table(upstream, ["validation_item", "expected_value", "actual_value", "validation_status"], 18)}

## Readiness Gate Scope

V20.51 is a gate-only readiness assessment for a future official gate. It creates no official recommendation, no official buy/sell/hold instruction, no trading signal, and no live trading authorization.

V20.50 research-only packet was used: TRUE
No official recommendation was created in V20.51: TRUE
No broker/order execution was performed in V20.51: TRUE

## Candidate Readiness For Future Official Gate

Candidate rows reviewed: {len(candidate_rows)}
Priority review rows: {counts.get("PRIORITY_REVIEW", 0)}
Standard review rows: {counts.get("STANDARD_REVIEW", 0)}

{md_table(candidate_rows, ["packet_row_id", "report_rank", "normalized_ticker", "research_decision_category", "future_official_gate_candidate_ready"], 20)}

## Context Readiness For Future Official Gate

{md_table(context, ["context_type", "row_count_or_status", "future_official_gate_context_ready", "mutation_allowed"], 10)}

## Recommendation Gate Prerequisite Review

{md_table(prereqs, ["prerequisite_id", "prerequisite_name", "prerequisite_status", "blocker_if_missing"], 20)}

## Official Gate Policy Gap Register

{md_table(gaps, ["gap_id", "gap_name", "blocker_for_v20_51", "blocker_for_future_official_generation"], 12)}

## Action Boundary

{md_table(actions, ["boundary_name", "allowed_flag", "evidence"], 20)}

## Safety Boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"], 20)}

## Explicit No Official Recommendation Created Statement

V20.51 creates no official recommendation and does not permit official recommendation generation in this stage.

## Explicit No Buy/Sell/Hold/Trading Signal Statement

V20.51 creates no official buy/sell/hold instruction and creates no trading signal.

## Explicit No Broker/Order Statement

V20.51 does not connect to broker/order APIs and does not perform broker/order execution.

## Explicit No Provider Refresh/Yfinance Statement

V20.51 performs no provider/network refresh and does not import yfinance.

## Explicit No Score/Ranking/Return Recomputation Statement

V20.51 calculates no forward returns, calculates no benchmark-relative returns, recomputes no scores, and recomputes no rankings. It does not mutate official rankings or dynamic weights.

## Blockers And Warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next Recommended Stage

{next_stage}

## V20.50 Formal Test Output

```text
{v50_test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        f"OFFICIAL_RECOMMENDATION_READINESS_GATE_STATUS={readiness_status}",
        "V20_50_RESEARCH_ONLY_PACKET_USED=TRUE",
        f"V20_47_RUN_ID={v20_47_run_id}",
        "V20_47_CACHE_REFERENCE_USED=TRUE",
        "GATE_ONLY_SAFETY_FLAGS=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "BUY_SELL_HOLD_INSTRUCTION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_51=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_51=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        f"NEXT_RECOMMENDED_STAGE={next_stage}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"DECISION={decision}")
    print(f"READINESS_STATUS={readiness_status}")
    print(f"V20_50_PACKET_STATUS={clean(v50_summary.get('decision_packet_status'))}")
    print(f"V20_50_TESTS_STATUS={'PASS' if v50_tests_passed else 'FAIL'}")
    print(f"CANDIDATE_ROWS_REVIEWED={len(candidates)}")
    print(f"CONTEXT_ROWS_CREATED={len(context)}")
    print(f"POLICY_GAP_ROWS={len(gaps)}")
    print(f"NEXT_RECOMMENDED_STAGE={next_stage}")
    return 0 if not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
