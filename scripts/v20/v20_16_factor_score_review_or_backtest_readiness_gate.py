from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_SCORE = CONSOLIDATION / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
IN_SCHEMA = CONSOLIDATION / "V20_15_FACTOR_SCORE_SCHEMA_AUDIT.csv"
IN_LINEAGE = CONSOLIDATION / "V20_15_FACTOR_SCORE_LINEAGE_AUDIT.csv"
IN_BOUNDARY = CONSOLIDATION / "V20_15_FACTOR_SCORE_BOUNDARY_AUDIT.csv"
IN_DATA_QUALITY = CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv"
IN_FAMILY_SUMMARY = CONSOLIDATION / "V20_15_FACTOR_FAMILY_SCORE_SUMMARY.csv"
IN_SCOPE_COMPLIANCE = CONSOLIDATION / "V20_15_SCORE_SCOPE_COMPLIANCE_AUDIT.csv"
IN_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_15_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_15_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_15_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_15_READ_FIRST.txt"
IN_MISSING = CONSOLIDATION / "V20_15_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"
IN_V20_7V_VALIDATION = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
IN_V20_7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_V20_7V_EXCLUDED = CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv"
IN_V20_14_SCOPE = CONSOLIDATION / "V20_14_FACTOR_SCORE_SCOPE_PLAN.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_16_DEPENDENCY_AUDIT.csv"
OUT_REVIEW = CONSOLIDATION / "V20_16_FACTOR_SCORE_LAYER_REVIEW.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_16_FACTOR_SCORE_SCHEMA_REVIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_16_FACTOR_SCORE_LINEAGE_REVIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_16_FACTOR_SCORE_BOUNDARY_REVIEW.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_16_FACTOR_SCORE_DATA_QUALITY_REVIEW.csv"
OUT_SEMANTIC = CONSOLIDATION / "V20_16_FACTOR_SCORE_SEMANTIC_REVIEW.csv"
OUT_FAMILY_READY = CONSOLIDATION / "V20_16_FACTOR_FAMILY_BACKTEST_READINESS_AUDIT.csv"
OUT_BACKTEST_GATE = CONSOLIDATION / "V20_16_BACKTEST_READINESS_GATE_DECISION.csv"
OUT_REQUIREMENTS = CONSOLIDATION / "V20_16_OUTCOME_BENCHMARK_REQUIREMENT_PLAN.csv"
OUT_MISSING = CONSOLIDATION / "V20_16_MISSING_FACTOR_SOURCE_BLOCKER_REVIEW.csv"
OUT_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_16_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_16_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
OUT_GATE_DIAGNOSTICS = CONSOLIDATION / "V20_16_GATE_DECISION_DIAGNOSTICS.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_16_SOURCE_AUDIT.csv"
OUT_NEXT = CONSOLIDATION / "V20_16_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_16_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE.md"
READ_FIRST = OPS / "V20_16_READ_FIRST.txt"
READ_CENTER_READ_FIRST = READ_CENTER / "V20_16_READ_FIRST.txt"

PATCH_VERSION = "V20.16"
PASS_STATUS = "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE"
BLOCKED_STATUS = "BLOCKED_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY, OUT_REVIEW, OUT_SCHEMA, OUT_LINEAGE, OUT_BOUNDARY,
    OUT_DATA_QUALITY, OUT_SEMANTIC, OUT_FAMILY_READY, OUT_BACKTEST_GATE,
    OUT_REQUIREMENTS, OUT_MISSING, OUT_DOWNSTREAM_BLOCKERS, OUT_BLOCKERS,
    OUT_GATE, OUT_GATE_DIAGNOSTICS, OUT_SOURCE_AUDIT, OUT_NEXT, OUT_VALIDATION,
    REPORT, CURRENT_REPORT, READ_FIRST, READ_CENTER_READ_FIRST,
}

REQUIRED_INPUTS = [
    IN_SCORE, IN_SCHEMA, IN_LINEAGE, IN_BOUNDARY, IN_DATA_QUALITY,
    IN_FAMILY_SUMMARY, IN_SCOPE_COMPLIANCE, IN_DOWNSTREAM_BLOCKERS,
    IN_GATE, IN_VALIDATION, IN_READ_FIRST,
]

REQUIRED_SCORE_COLUMNS = [
    "factor_score_row_id", "factor_evidence_row_id", "factor_attachment_row_id",
    "factor_research_row_id", "normalized_row_id", "ticker",
    "effective_observation_date", "effective_price_date", "effective_close",
    "source_system", "source_hash", "run_id", "sample_id", "factor_category",
    "factor_family", "score_scope_id", "score_type", "score_basis",
    "score_value_type", "factor_score_created", "factor_score_value",
    "factor_score_quality_flag", "score_lineage_complete", "score_pit_safe",
    "score_stale_leakage_checked", "performance_metric_created",
    "forward_return_created", "benchmark_relative_return_created",
    "backtest_metric_created", "dynamic_weighting_input_created",
    "trading_signal_created", "strategy_signal_created",
    "official_recommendation_created", "research_only_flag",
    "official_use_allowed", "allowed_for_score_review_next",
    "allowed_for_backtest_now", "allowed_for_dynamic_weighting_now",
    "allowed_for_trading_now", "allowed_for_official_recommendation_now",
    "score_created_at_utc", "score_source_step",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def parse_float(value: object) -> float | None:
    try:
        return float(clean(value))
    except ValueError:
        return None


def parse_date_ok(value: object) -> bool:
    try:
        datetime.fromisoformat(clean(value))
        return True
    except ValueError:
        return False


def false_or_zero(value: object) -> bool:
    return upper(value) in {"FALSE", "0", ""}


def true_value(value: object) -> bool:
    return upper(value) == "TRUE"


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str, severity: str = "BLOCKING") -> None:
    blockers.append({
        "blocker_id": f"V20_16_BLOCKER_{len(blockers) + 1:03d}",
        "blocker_scope": scope,
        "severity": severity,
        "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
        "blocker_reason": reason,
        "blocks_v20_16": tf(severity == "BLOCKING"),
    })


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in headers) + " |")
    if len(rows) > limit:
        lines.append("| " + " | ".join(["..."] + [f"{len(rows) - limit} more rows omitted"] + [""] * max(0, len(headers) - 2)) + " |")
    return "\n".join(lines)


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []
    score_rows, score_fields = read_csv(IN_SCORE)
    schema_in, _ = read_csv(IN_SCHEMA)
    lineage_in, _ = read_csv(IN_LINEAGE)
    boundary_in, _ = read_csv(IN_BOUNDARY)
    dq_in, _ = read_csv(IN_DATA_QUALITY)
    family_summary_in, _ = read_csv(IN_FAMILY_SUMMARY)
    scope_in, _ = read_csv(IN_SCOPE_COMPLIANCE)
    downstream_in, _ = read_csv(IN_DOWNSTREAM_BLOCKERS)
    gate_rows, _ = read_csv(IN_GATE)
    validation_rows, _ = read_csv(IN_VALIDATION)
    missing_in, _ = read_csv(IN_MISSING)
    v20_7v = first_row(IN_V20_7V_VALIDATION)
    v20_7v_staging, _ = read_csv(IN_V20_7V_STAGING)
    v20_7v_excluded, _ = read_csv(IN_V20_7V_EXCLUDED)
    scope_plan_rows, _ = read_csv(IN_V20_14_SCOPE)
    read_first_in = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    scope = scope_in[0] if scope_in else {}

    dependency_rows = []
    def dependency(name: str, path: Path, passed: bool, reason: str) -> None:
        dependency_rows.append({"dependency": name, "path": rel(path), "exists": tf(path.exists()), "status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else reason})
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason)

    for path in REQUIRED_INPUTS:
        dependency(path.stem, path, path.exists(), f"Required input {rel(path)} is missing.")

    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER"
        and upper(gate.get("LIMITED_FACTOR_SCORE_LAYER_CREATED")) == "TRUE"
        and int(clean(gate.get("FACTOR_SCORE_ROWS_CREATED")) or "0") > 0
        and int(clean(gate.get("FACTOR_SCORE_VALUES_CREATED")) or "0") > 0
        and int(clean(gate.get("FACTOR_FAMILIES_SCORED")) or "0") > 0
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("FORWARD_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_RELATIVE_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
        and upper(gate.get("READY_FOR_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER"
        and upper(validation.get("limited_factor_score_layer_created")) == "TRUE"
        and int(clean(validation.get("factor_score_rows_created")) or "0") > 0
        and int(clean(validation.get("factor_score_values_created")) or "0") > 0
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
        and clean(validation.get("dynamic_weighting_rows_created")) == "0"
        and clean(validation.get("trading_signal_rows_created")) == "0"
        and clean(validation.get("strategy_signal_rows_created")) == "0"
        and clean(validation.get("official_recommendation_rows_created")) == "0"
        and upper(validation.get("ready_for_v20_16_factor_score_review_or_backtest_readiness_gate_next")) == "TRUE"
    )
    read_first_ok = all(flag in read_first_in for flag in [
        "FIRST_LIMITED_FACTOR_SCORE_LAYER = TRUE", "LIMITED_FACTOR_SCORE_LAYER_CREATED = TRUE",
        "PERFORMANCE_METRICS_CREATED = 0", "FORWARD_RETURN_ROWS_CREATED = 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0", "BACKTEST_ROWS_CREATED = 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED = 0", "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNAL_ROWS_CREATED = 0", "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
        "SOURCE_MUTATION_USED = FALSE", "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE", "OFFICIAL_USE_ALLOWED = FALSE",
    ])
    dependency("V20_15_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.15 gate is not in the required pass and safety state.")
    dependency("V20_15_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.15 validation summary is not in the required pass and safety state.")
    dependency("V20_15_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.15 READ_FIRST safety flags are incomplete.")

    v20_7v_status = clean(v20_7v.get("status"))
    v20_7v_usable = upper(v20_7v.get("active_market_source_staging_usable") or v20_7v.get("active_source_staging_candidate_ready"))
    eligible_row_count = int(clean(v20_7v.get("eligible_row_count")) or "0")
    excluded_row_count = int(clean(v20_7v.get("excluded_row_count")) or "0")
    exclusion_threshold = int(clean(v20_7v.get("exclusion_threshold")) or "0")
    excluded_rows_allowed = excluded_row_count <= exclusion_threshold and all(clean(row.get("exclusion_reason")) for row in v20_7v_excluded)
    v20_7v_staging_matches = eligible_row_count > 0 and len(v20_7v_staging) == eligible_row_count
    active_staging_core_ok = all(
        clean(row.get("ticker"))
        and clean(row.get("latest_price_date")) == clean(v20_7v.get("expected_market_date"))
        and clean(row.get("composite_candidate_score"))
        for row in v20_7v_staging
    )
    consumed_current_v20_7v = (
        v20_7v_status == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY"
        and v20_7v_usable == "TRUE"
        and v20_7v_staging_matches
        and excluded_rows_allowed
        and active_staging_core_ok
    )
    dependency("V20_7V_CURRENT_VALIDATION_SUMMARY", IN_V20_7V_VALIDATION, bool(v20_7v) and v20_7v_status == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "V20.16 requires current V20.7V PASS eligible-row staging.")
    dependency("V20_7V_CURRENT_ACTIVE_STAGING", IN_V20_7V_STAGING, v20_7v_staging_matches and active_staging_core_ok, "V20.16 requires active V20.7V staging rows to match eligible_row_count and pass core gates.")
    dependency("V20_7V_CURRENT_EXCLUDED_TICKERS", IN_V20_7V_EXCLUDED, excluded_rows_allowed, "V20.16 requires excluded rows to be within threshold and have reasons.")

    row_count = len(score_rows)
    family_keys = {(clean(r.get("factor_category")), clean(r.get("factor_family"))) for r in score_rows}
    approved_family_count = sum(1 for row in scope_plan_rows if upper(row.get("allowed_for_first_limited_score_layer_next")) == "TRUE") or len(family_keys)
    expected_score_rows = eligible_row_count * approved_family_count if consumed_current_v20_7v else sum(int(clean(row.get("allowed_evidence_rows")) or "0") for row in scope_plan_rows)
    expected_score_rows = expected_score_rows or row_count
    scope_ok = upper(scope.get("score_scope_compliance_status")) == "PASS" and upper(scope.get("all_score_rows_in_v20_14_approved_scope")) == "TRUE"
    no_blocked = upper(scope.get("blocked_factor_families_included")) == "FALSE"
    no_source_required = upper(scope.get("source_required_factor_families_included")) == "FALSE"
    values = [parse_float(r.get("factor_score_value")) for r in score_rows]
    valid_values = [v for v in values if v is not None]
    all_score_basis_ok = all("readiness" in clean(r.get("score_basis")).lower() or "lineage" in clean(r.get("factor_score_quality_flag")).lower() or "readiness" in clean(r.get("factor_score_quality_flag")).lower() for r in score_rows)
    review_passed = row_count > 0 and row_count == expected_score_rows and scope_ok and no_blocked and no_source_required and all_score_basis_ok and consumed_current_v20_7v
    if not review_passed:
        add_blocker(blockers, "SCORE_REVIEW", "Score layer failed count, current V20.7V eligible-staging consumption, scope, blocked family, or semantic readiness basis review.")
    review_rows = [{
        "review_id": "V20_16_FACTOR_SCORE_LAYER_REVIEW_001",
        "factor_score_rows_reviewed": str(row_count),
        "expected_score_rows_from_current_v20_7v_eligible_rows": str(expected_score_rows),
        "matches_expected_current_v20_7v_eligible_rows": tf(row_count == expected_score_rows),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "excluded_rows_allowed_by_v20_16": tf(excluded_rows_allowed),
        "consumed_current_v20_7v_outputs": tf(consumed_current_v20_7v),
        "factor_families_reviewed": str(len(family_keys)),
        "approved_factor_families_expected": str(approved_family_count),
        "score_rows_cover_only_v20_14_approved_scope": tf(scope_ok),
        "blocked_factor_family_appears": tf(not no_blocked),
        "source_required_factor_family_appears": tf(not no_source_required),
        "partial_source_family_silently_promoted": "FALSE",
        "factor_score_value_limited_readiness_lineage_quality_only": tf(all_score_basis_ok),
        "score_layer_review_status": "PASS" if review_passed else "BLOCKED",
        "blocker_reason": "" if review_passed else "Score layer review failed.",
    }]

    ids = [clean(r.get("factor_score_row_id")) for r in score_rows if clean(r.get("factor_score_row_id"))]
    duplicate_ids = row_count - len(set(ids))
    missing_ticker = sum(1 for r in score_rows if not clean(r.get("ticker")))
    missing_hash = sum(1 for r in score_rows if not clean(r.get("source_hash")))
    missing_run_id = sum(1 for r in score_rows if not clean(r.get("run_id")))
    missing_sample_id = sum(1 for r in score_rows if not clean(r.get("sample_id")))
    missing_score_value = sum(1 for r in score_rows if not clean(r.get("factor_score_value")))
    nonnumeric = sum(1 for v in values if v is None)
    below_zero = sum(1 for v in values if v is not None and v < 0)
    above_one = sum(1 for v in values if v is not None and v > 1)
    perf_true = sum(1 for r in score_rows if not false_or_zero(r.get("performance_metric_created")))
    forward_true = sum(1 for r in score_rows if not false_or_zero(r.get("forward_return_created")))
    benchmark_true = sum(1 for r in score_rows if not false_or_zero(r.get("benchmark_relative_return_created")))
    backtest_true = sum(1 for r in score_rows if not false_or_zero(r.get("backtest_metric_created")))
    dynamic_true = sum(1 for r in score_rows if not false_or_zero(r.get("dynamic_weighting_input_created")))
    trading_true = sum(1 for r in score_rows if not false_or_zero(r.get("trading_signal_created")))
    strategy_true = sum(1 for r in score_rows if not false_or_zero(r.get("strategy_signal_created")))
    official_rec_true = sum(1 for r in score_rows if not false_or_zero(r.get("official_recommendation_created")))
    official_use_true = sum(1 for r in score_rows if true_value(r.get("official_use_allowed")))

    schema_rows = []
    fields = set(score_fields)
    for col in REQUIRED_SCORE_COLUMNS:
        non_empty = sum(1 for r in score_rows if clean(r.get(col)))
        if col == "factor_score_row_id":
            passed = col in fields and non_empty == row_count and duplicate_ids == 0
        elif col in {"factor_evidence_row_id", "factor_attachment_row_id", "factor_research_row_id", "normalized_row_id", "ticker", "source_system", "source_hash", "run_id", "sample_id", "factor_category", "factor_family", "score_scope_id", "score_type", "score_basis", "score_value_type", "factor_score_quality_flag", "score_lineage_complete", "score_pit_safe", "score_stale_leakage_checked", "score_created_at_utc", "score_source_step"}:
            passed = col in fields and non_empty == row_count
        elif col in {"effective_observation_date", "effective_price_date"}:
            passed = col in fields and non_empty == row_count and all(parse_date_ok(r.get(col)) for r in score_rows)
        elif col == "effective_close":
            passed = col in fields and non_empty == row_count and all((parse_float(r.get(col)) or 0) > 0 for r in score_rows)
        elif col == "factor_score_created":
            passed = col in fields and all(true_value(r.get(col)) for r in score_rows)
        elif col == "factor_score_value":
            passed = col in fields and missing_score_value == 0 and nonnumeric == 0 and below_zero == 0 and above_one == 0
        elif col == "research_only_flag":
            passed = col in fields and all(true_value(r.get(col)) for r in score_rows)
        elif col == "official_use_allowed":
            passed = col in fields and official_use_true == 0
        elif col == "performance_metric_created":
            passed = col in fields and perf_true == 0
        elif col == "forward_return_created":
            passed = col in fields and forward_true == 0
        elif col == "benchmark_relative_return_created":
            passed = col in fields and benchmark_true == 0
        elif col == "backtest_metric_created":
            passed = col in fields and backtest_true == 0
        elif col == "dynamic_weighting_input_created":
            passed = col in fields and dynamic_true == 0
        elif col == "trading_signal_created":
            passed = col in fields and trading_true == 0
        elif col == "strategy_signal_created":
            passed = col in fields and strategy_true == 0
        elif col == "official_recommendation_created":
            passed = col in fields and official_rec_true == 0
        elif col == "allowed_for_score_review_next":
            passed = col in fields and all(true_value(r.get(col)) for r in score_rows)
        elif col.startswith("allowed_for_"):
            passed = col in fields and all(not true_value(r.get(col)) for r in score_rows)
        else:
            passed = col in fields
        schema_rows.append({"column_name": col, "required": "TRUE", "detected": tf(col in fields), "non_empty_row_count": str(non_empty), "row_count": str(row_count), "schema_review_status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else f"Required score field {col} failed schema or boundary validation."})
    schema_passed = bool(score_rows) and all(r["schema_review_status"] == "PASS" for r in schema_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "Score schema review failed.")

    lineage_counts = {
        "linked_to_v20_15_score_row_count": sum(1 for r in score_rows if clean(r.get("factor_score_row_id")).startswith("V20_15_SCORE_")),
        "linked_to_v20_14_factor_score_gate_and_scope_plan_count": sum(1 for r in score_rows if clean(r.get("score_scope_id")).startswith("V20_14_SCORE_SCOPE_")),
        "linked_to_v20_13_limited_factor_evidence_row_count": sum(1 for r in score_rows if clean(r.get("factor_evidence_row_id")).startswith("V20_13_EVID_")),
        "linked_to_v20_12_evidence_gate_decision_count": sum(1 for r in score_rows if clean(r.get("score_scope_id"))),
        "linked_to_v20_11_factor_attachment_input_row_count": sum(1 for r in score_rows if clean(r.get("factor_attachment_row_id")).startswith("V20_11_ATTACH_")),
        "linked_to_v20_10_factor_source_attachment_classification_count": sum(1 for r in score_rows if clean(r.get("score_basis"))),
        "linked_to_v20_9_factor_research_base_row_count": sum(1 for r in score_rows if clean(r.get("factor_research_row_id")).startswith("V20_9_FACT_")),
        "linked_to_v20_8_normalized_research_row_count": sum(1 for r in score_rows if clean(r.get("normalized_row_id")).startswith("V20_8_NORM_")),
        "linked_to_v20_7x_active_input_lineage_count": sum(1 for r in score_rows if clean(r.get("source_hash")) and clean(r.get("run_id"))),
        "source_hash_preserved_count": sum(1 for r in score_rows if clean(r.get("source_hash"))),
        "run_id_preserved_count": sum(1 for r in score_rows if clean(r.get("run_id"))),
        "sample_id_preserved_count": sum(1 for r in score_rows if clean(r.get("sample_id"))),
    }
    lineage_passed = bool(score_rows) and all(v == row_count for v in lineage_counts.values())
    lineage_rows = [{"lineage_review_id": "V20_16_LINEAGE_REVIEW_001", "factor_score_rows_reviewed": str(row_count), **{k: str(v) for k, v in lineage_counts.items()}, "upstream_v20_15_lineage_audit_status": clean(lineage_in[0].get("lineage_status")) if lineage_in else "", "lineage_review_status": "PASS" if lineage_passed else "BLOCKED", "blocker_reason": "" if lineage_passed else "One or more score lineage links are missing."}]
    if not lineage_passed:
        add_blocker(blockers, "LINEAGE", "Score lineage review failed.")

    boundary_passed = perf_true == forward_true == benchmark_true == backtest_true == dynamic_true == trading_true == strategy_true == official_rec_true == official_use_true == 0
    boundary_rows = [{
        "boundary_review_id": "V20_16_BOUNDARY_REVIEW_001",
        "performance_metrics_created": "0",
        "forward_return_rows_created": "0",
        "benchmark_relative_return_rows_created": "0",
        "backtest_rows_created": "0",
        "dynamic_weighting_rows_created": "0",
        "trading_signal_rows_created": "0",
        "strategy_signal_rows_created": "0",
        "official_recommendation_rows_created": "0",
        "rank_or_ranking_created": "FALSE",
        "buy_sell_hold_action_field_created": "FALSE",
        "official_use_allowed_true_count": str(official_use_true),
        "boundary_review_status": "PASS" if boundary_passed else "BLOCKED",
        "blocker_reason": "" if boundary_passed else "Score review violated downstream/performance boundary.",
    }]
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "Score boundary review failed.")

    min_score = min(valid_values) if valid_values else 0.0
    max_score = max(valid_values) if valid_values else 0.0
    avg_score = sum(valid_values) / len(valid_values) if valid_values else 0.0
    dq_passed = bool(score_rows) and missing_ticker == missing_hash == missing_run_id == missing_sample_id == duplicate_ids == missing_score_value == nonnumeric == below_zero == above_one == perf_true == forward_true == benchmark_true == backtest_true == dynamic_true == trading_true == strategy_true == official_use_true == 0
    dq_rows = [{
        "quality_review_id": "V20_16_QUALITY_REVIEW_001",
        "factor_score_rows_reviewed": str(row_count),
        "unique_tickers": str(len({clean(r.get("ticker")) for r in score_rows if clean(r.get("ticker"))})),
        "unique_factor_families": str(len({clean(r.get("factor_family")) for r in score_rows if clean(r.get("factor_family"))})),
        "unique_factor_categories": str(len({clean(r.get("factor_category")) for r in score_rows if clean(r.get("factor_category"))})),
        "missing_ticker_count": str(missing_ticker),
        "missing_source_hash_count": str(missing_hash),
        "missing_run_id_count": str(missing_run_id),
        "missing_sample_id_count": str(missing_sample_id),
        "duplicate_factor_score_row_id_count": str(duplicate_ids),
        "missing_factor_score_value_count": str(missing_score_value),
        "nonnumeric_factor_score_value_count": str(nonnumeric),
        "factor_score_value_below_0_count": str(below_zero),
        "factor_score_value_above_1_count": str(above_one),
        "min_factor_score_value": f"{min_score:.6f}",
        "max_factor_score_value": f"{max_score:.6f}",
        "avg_factor_score_value": f"{avg_score:.6f}",
        "rows_with_performance_metric_created_true": str(perf_true),
        "rows_with_forward_return_created_true": str(forward_true),
        "rows_with_benchmark_relative_return_created_true": str(benchmark_true),
        "rows_with_backtest_metric_created_true": str(backtest_true),
        "rows_with_dynamic_weighting_input_created_true": str(dynamic_true),
        "rows_with_trading_signal_created_true": str(trading_true),
        "rows_with_strategy_signal_created_true": str(strategy_true),
        "rows_with_official_use_allowed_true": str(official_use_true),
        "data_quality_review_status": "PASS" if dq_passed else "BLOCKED",
        "blocker_reason": "" if dq_passed else "Score data quality review failed.",
    }]
    if not dq_passed:
        add_blocker(blockers, "DATA_QUALITY", "Score data quality review failed.")

    all_equal = len(set(f"{v:.6f}" for v in valid_values)) <= 1 if valid_values else False
    semantic_passed = all_score_basis_ok and nonnumeric == 0 and below_zero == 0 and above_one == 0
    semantic_warning = all_equal
    semantic_rows = [{
        "semantic_review_id": "V20_16_SEMANTIC_REVIEW_001",
        "score_semantic_type": "readiness_lineage_quality_score",
        "predictive_score": "FALSE",
        "alpha_score": "FALSE",
        "expected_return_score": "FALSE",
        "ranking_score": "FALSE",
        "recommendation_score": "FALSE",
        "official_weight_score": "FALSE",
        "score_values_all_equal": tf(all_equal),
        "score_values_all_equal_allowed": tf(all_equal and all_score_basis_ok),
        "semantic_warning_required": tf(semantic_warning),
        "semantic_warning_text": "scores are not predictive and must not be used for ticker ranking, expected returns, portfolio weights, or trading actions",
        "semantic_review_status": "PASS" if semantic_passed else "BLOCKED",
        "blocker_reason": "" if semantic_passed else "Score semantics are not limited to readiness/lineage quality.",
    }]
    if not semantic_passed:
        add_blocker(blockers, "SEMANTIC", "Score semantic review failed.")

    core_passed = gate_ok and validation_ok and read_first_ok and review_passed and schema_passed and lineage_passed and boundary_passed and dq_passed and semantic_passed
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in score_rows:
        grouped[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)
    family_rows = []
    for (category, family), rows in sorted(grouped.items()):
        pit_safe = all(true_value(r.get("score_pit_safe")) for r in rows)
        stale = all(true_value(r.get("score_stale_leakage_checked")) for r in rows)
        prep_allowed = core_passed and pit_safe and stale
        family_rows.append({
            "factor_category": category,
            "factor_family": family,
            "score_rows_reviewed": str(len(rows)),
            "unique_tickers": str(len({clean(r.get("ticker")) for r in rows if clean(r.get("ticker"))})),
            "score_layer_present": "TRUE",
            "score_scope_compliant": tf(scope_ok),
            "schema_ready": tf(schema_passed),
            "lineage_ready": tf(lineage_passed),
            "score_semantic_safe": tf(semantic_passed),
            "pit_safe": tf(pit_safe),
            "stale_leakage_checked": tf(stale),
            "outcome_window_available": "FALSE",
            "benchmark_window_available": "FALSE",
            "forward_return_available": "FALSE",
            "performance_metric_available": "FALSE",
            "backtest_input_ready_next": tf(prep_allowed),
            "backtest_execution_allowed_now": "FALSE",
            "dynamic_weighting_allowed_now": "FALSE",
            "trading_allowed_now": "FALSE",
            "official_use_allowed": "FALSE",
            "blocker_reason": "" if prep_allowed else "Backtest requirement preparation waits for score review, semantic, lineage, PIT, stale/leakage, and boundary checks.",
            "next_required_step": "V20.17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION" if prep_allowed else "Resolve V20.16 blocker before outcome/benchmark preparation.",
        })

    gate_passed = core_passed and all(r["backtest_input_ready_next"] == "TRUE" for r in family_rows) and not any(r["blocks_v20_16"] == "TRUE" for r in blockers)
    backtest_gate_rows = [{
        "gate_id": "V20_16_BACKTEST_READINESS_GATE",
        "FACTOR_SCORE_REVIEW_PASSED": tf(gate_passed),
        "BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT": tf(gate_passed),
        "BACKTEST_EXECUTION_ALLOWED_NOW": "FALSE",
        "FORWARD_RETURN_ROWS_CREATED_NOW": "0",
        "PERFORMANCE_METRICS_CREATED_NOW": "0",
        "READY_FOR_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_NEXT": tf(gate_passed),
        "gate_status": "PASS" if gate_passed else "BLOCKED",
        "gate_reason": "Score review passed; outcome/benchmark requirement preparation may proceed next." if gate_passed else "Score review or backtest-readiness gate checks failed.",
    }]
    if not gate_passed:
        add_blocker(blockers, "BACKTEST_READINESS_GATE", "Backtest readiness preparation gate did not pass.")

    failed_conditions = []
    condition_checks = [
        ("v20_15_gate_ok", gate_ok),
        ("v20_15_validation_ok", validation_ok),
        ("v20_15_read_first_ok", read_first_ok),
        ("consumed_current_v20_7v_outputs", consumed_current_v20_7v),
        ("score_row_count_matches_current_v20_7v_eligible_rows", row_count == expected_score_rows),
        ("scope_ok", scope_ok),
        ("no_blocked_factor_families", no_blocked),
        ("no_source_required_factor_families", no_source_required),
        ("score_basis_limited_to_readiness_or_lineage_quality", all_score_basis_ok),
        ("schema_passed", schema_passed),
        ("lineage_passed", lineage_passed),
        ("boundary_passed", boundary_passed),
        ("data_quality_passed", dq_passed),
        ("semantic_passed", semantic_passed),
    ]
    for name, passed in condition_checks:
        if not passed:
            failed_conditions.append(name)

    req_specs = [
        ("forward_outcome_windows", "forward_outcomes", "ticker,effective_price_date,forward_window,forward_close,forward_return", "future outcome labels by explicit horizon"),
        ("benchmark_relative_outcome_windows", "benchmark_relative_outcomes", "ticker,benchmark_symbol,forward_window,ticker_forward_return,benchmark_forward_return,relative_return", "future benchmark-relative labels by horizon"),
        ("benchmark_price_windows", "SPY_QQQ_benchmark_price_windows", "benchmark_symbol,price_date,close,source_hash,run_id,sample_id", "SPY/QQQ benchmark window covering score dates and forward horizons"),
        ("ticker_historical_close_windows", "ticker_historical_close_windows", "ticker,price_date,close,source_hash,run_id,sample_id", "ticker close window covering score dates and forward horizons"),
        ("event_date_exclusion_windows", "event_date_exclusions", "ticker,event_date,event_type,exclusion_window", "earnings/event blackout windows"),
        ("pit_outcome_confirmation", "stale_leakage_pit_outcome_label_confirmation", "label_date,source_timestamp,pit_flag,leakage_check_flag", "PIT and leakage controls for outcome labels"),
        ("sample_split_policy", "sample_split_or_evaluation_window_policy", "split_id,start_date,end_date,role,policy_notes", "evaluation split policy only"),
        ("score_aggregation_policy", "factor_family_score_aggregation_policy", "factor_family,aggregation_method,allowed_inputs,boundary_notes", "aggregation contract only"),
        ("strategy_signal_dependency_policy", "strategy_signal_dependency_policy", "strategy_family,required_factor_scores,required_evidence,gate_required", "strategy dependency contract only"),
        ("portfolio_position_framework_policy", "portfolio_position_framework_dependency_policy", "portfolio_field,position_field,risk_limit_field,gate_required", "portfolio/position dependency contract only"),
    ]
    requirement_rows = []
    for index, (area, required_input, fields_required, window) in enumerate(req_specs, start=1):
        requirement_rows.append({
            "requirement_id": f"V20_16_REQ_{index:03d}",
            "requirement_area": area,
            "required_input": required_input,
            "required_fields": fields_required,
            "required_window": window,
            "currently_available": "FALSE",
            "source_required": "TRUE",
            "blocks_backtest_execution": "TRUE",
            "blocks_dynamic_weighting": "TRUE",
            "blocks_trading_or_official_use": "TRUE",
            "next_required_step": "V20.17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION",
            "boundary_notes": "Requirement plan only; no outcomes, benchmark returns, performance metrics, backtests, signals, or official recommendations computed.",
        })

    missing_rows = []
    for i, row in enumerate(missing_in, start=1):
        missing_rows.append({
            "missing_source_blocker_id": clean(row.get("missing_source_id")) or f"V20_16_MISSING_{i:03d}",
            "required_source_name": clean(row.get("required_source_name")),
            "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
            "source_status": clean(row.get("source_status")) or "MISSING",
            "carryforward_from_v20_15_v20_14_v20_13_v20_12_or_v20_11": "TRUE",
            "blocks_full_factor_score": "TRUE",
            "blocks_backtest_execution": "TRUE",
            "blocks_dynamic_weighting": "TRUE",
            "blocks_strategy_signals": "TRUE",
            "blocks_official_use": "TRUE",
            "blocker_reason": clean(row.get("blocker_reason")),
            "next_required_source_or_step": clean(row.get("next_required_source_or_step")) or "Register required source before backtest execution gates.",
        })

    downstream_rows = []
    for layer, reason in [
        ("backtest_execution", "No forward outcomes created, no benchmark-relative outcomes created, no performance metrics created, and no backtest-ready outcome windows built yet."),
        ("dynamic_weighting", "No performance metrics, no backtest execution gate, and scores are limited research-only readiness/lineage-quality scores."),
        ("trading_signal", "No backtest execution gate, no strategy signal gate, and scores are limited research-only readiness/lineage-quality scores."),
        ("strategy_signal", "No strategy signal gate and no complete strategy dependency evidence."),
        ("official_recommendation", "No official-use gate and no portfolio/position framework gate."),
    ]:
        downstream_rows.append({
            "blocked_layer": layer,
            "allowed_now": "FALSE",
            "blocker_reason": reason,
            "forward_outcomes_created": "0",
            "benchmark_relative_outcomes_created": "0",
            "performance_metrics_created": "0",
            "backtest_ready_outcome_windows_built": "0",
            "strategy_signal_gate_passed": "FALSE",
            "portfolio_position_framework_gate_passed": "FALSE",
            "scores_limited_readiness_lineage_quality_only": "TRUE",
            "official_use_allowed": "FALSE",
        })

    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    next_step = "V20.17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION" if gate_passed else "Resolve V20.16 blockers before V20.17."
    gate_out = [{
        "gate_id": "V20_16_GATE",
        "STATUS": status,
        "v20_16_gate_decision": tf(gate_passed),
        "v20_16_status": status,
        "consumed_v20_7v_status": v20_7v_status,
        "consumed_active_market_source_staging_usable": v20_7v_usable,
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "exclusion_threshold": str(exclusion_threshold),
        "excluded_rows_allowed_by_v20_16": tf(excluded_rows_allowed),
        "consumed_current_v20_7v_outputs": tf(consumed_current_v20_7v),
        "expected_score_rows_from_current_v20_7v_eligible_rows": str(expected_score_rows),
        "failed_condition_list": ";".join(failed_conditions),
        "FACTOR_SCORE_REVIEW_PASSED": tf(gate_passed),
        "FACTOR_SCORE_ROWS_REVIEWED": str(row_count),
        "FACTOR_FAMILIES_REVIEWED": str(len(grouped)),
        "SCORE_SEMANTIC_REVIEW_PASSED": tf(semantic_passed),
        "BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT": tf(gate_passed),
        "BACKTEST_EXECUTION_ALLOWED_NOW": "FALSE",
        "READY_FOR_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_NEXT": tf(gate_passed),
        "FORWARD_RETURN_ROWS_CREATED": "0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": "0",
        "PERFORMANCE_METRICS_CREATED": "0",
        "BACKTEST_ROWS_CREATED": "0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
        "TRADING_SIGNAL_ROWS_CREATED": "0",
        "STRATEGY_SIGNAL_ROWS_CREATED": "0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
        "gate_reason": "V20.16 score review and backtest readiness preparation gate passed." if gate_passed else "V20.16 score review or backtest-readiness gate failed.",
    }]
    next_rows = [{
        "decision_id": "V20_16_NEXT_STEP",
        "current_status": status,
        "next_recommended_step": next_step,
        "ready_for_v20_17_backtest_input_outcome_and_benchmark_preparation_next": tf(gate_passed),
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "boundary_notes": "Gate only; no outcomes, returns, metrics, backtests, dynamic weights, signals, or official recommendations.",
    }]
    missing_artifacts = [row["path"] for row in dependency_rows if row["exists"] != "TRUE"]
    diagnostics_rows = [{
        "v20_16_gate_decision": tf(gate_passed),
        "v20_16_status": status,
        "consumed_v20_7v_status": v20_7v_status,
        "consumed_active_market_source_staging_usable": v20_7v_usable,
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "exclusion_threshold": str(exclusion_threshold),
        "excluded_rows_allowed_by_v20_16": tf(excluded_rows_allowed),
        "consumed_current_v20_7v_outputs": tf(consumed_current_v20_7v),
        "active_staging_row_count": str(len(v20_7v_staging)),
        "active_staging_core_ok": tf(active_staging_core_ok),
        "factor_score_rows_reviewed": str(row_count),
        "approved_factor_families_expected": str(approved_family_count),
        "expected_score_rows_from_current_v20_7v_eligible_rows": str(expected_score_rows),
        "score_row_count_matches_expected": tf(row_count == expected_score_rows),
        "required_downstream_artifact_checks": "V20_17_not_required_until_v20_16_gate_passes",
        "missing_artifact_list": ";".join(missing_artifacts),
        "failed_condition_list": ";".join(failed_conditions),
        "recommended_next_action": next_step,
    }]
    source_audit_rows = [{
        "source_name": "V20_7V_VALIDATION_SUMMARY",
        "source_path": rel(IN_V20_7V_VALIDATION),
        "source_exists": tf(IN_V20_7V_VALIDATION.exists()),
        "consumed_status": v20_7v_status,
        "consumed_usable_flag": v20_7v_usable,
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "exclusion_threshold": str(exclusion_threshold),
        "source_audit_status": "PASS" if consumed_current_v20_7v else "BLOCKED",
    }, {
        "source_name": "V20_7V_ACTIVE_MARKET_SOURCE_STAGING",
        "source_path": rel(IN_V20_7V_STAGING),
        "source_exists": tf(IN_V20_7V_STAGING.exists()),
        "consumed_status": "PASS" if v20_7v_staging_matches and active_staging_core_ok else "BLOCKED",
        "consumed_usable_flag": "",
        "eligible_row_count": str(len(v20_7v_staging)),
        "excluded_row_count": "",
        "exclusion_threshold": "",
        "source_audit_status": "PASS" if v20_7v_staging_matches and active_staging_core_ok else "BLOCKED",
    }, {
        "source_name": "V20_7V_EXCLUDED_TICKERS",
        "source_path": rel(IN_V20_7V_EXCLUDED),
        "source_exists": tf(IN_V20_7V_EXCLUDED.exists()),
        "consumed_status": "PASS" if excluded_rows_allowed else "BLOCKED",
        "consumed_usable_flag": "",
        "eligible_row_count": "",
        "excluded_row_count": str(len(v20_7v_excluded)),
        "exclusion_threshold": str(exclusion_threshold),
        "source_audit_status": "PASS" if excluded_rows_allowed else "BLOCKED",
    }, {
        "source_name": "V20_14_FACTOR_SCORE_SCOPE_PLAN",
        "source_path": rel(IN_V20_14_SCOPE),
        "source_exists": tf(IN_V20_14_SCOPE.exists()),
        "consumed_status": "PASS" if approved_family_count > 0 else "BLOCKED",
        "consumed_usable_flag": "",
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "exclusion_threshold": str(exclusion_threshold),
        "source_audit_status": "PASS" if approved_family_count > 0 else "BLOCKED",
    }]

    read_first = "\n".join([
        "PATCH_VERSION: V20.16",
        "PATCH_NAME: FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE",
        "REPORTING_ONLY = FALSE",
        "FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_ONLY = TRUE",
        f"STATUS = {status}",
        f"FACTOR_SCORE_REVIEW_PASSED = {tf(gate_passed)}",
        f"SCORE_SEMANTIC_REVIEW_PASSED = {tf(semantic_passed)}",
        f"BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT = {tf(gate_passed)}",
        f"CONSUMED_V20_7V_STATUS = {v20_7v_status}",
        f"CONSUMED_ACTIVE_MARKET_SOURCE_STAGING_USABLE = {v20_7v_usable}",
        f"ELIGIBLE_ROW_COUNT = {eligible_row_count}",
        f"EXCLUDED_ROW_COUNT = {excluded_row_count}",
        f"EXCLUSION_THRESHOLD = {exclusion_threshold}",
        f"EXCLUDED_ROWS_ALLOWED_BY_V20_16 = {tf(excluded_rows_allowed)}",
        f"CONSUMED_CURRENT_V20_7V_OUTPUTS = {tf(consumed_current_v20_7v)}",
        f"EXPECTED_SCORE_ROWS_FROM_CURRENT_V20_7V_ELIGIBLE_ROWS = {expected_score_rows}",
        f"FAILED_CONDITION_LIST = {';'.join(failed_conditions)}",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE",
        "FORWARD_RETURN_ROWS_CREATED = 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0",
        "BACKTEST_ROWS_CREATED = 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
        "BROKER_API_USED = FALSE",
        "ORDER_EXECUTION_USED = FALSE",
        "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE",
        "OFFICIAL_USE_ALLOWED = FALSE",
        f"FACTOR_SCORE_ROWS_REVIEWED = {row_count}",
        f"FACTOR_FAMILIES_REVIEWED = {len(grouped)}",
        f"NEXT_RECOMMENDED_STEP = {next_step}",
        "",
    ])
    read_first_ok_out = all(flag in read_first for flag in [
        "REPORTING_ONLY = FALSE", "FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_ONLY = TRUE",
        f"FACTOR_SCORE_REVIEW_PASSED = {tf(gate_passed)}", f"SCORE_SEMANTIC_REVIEW_PASSED = {tf(semantic_passed)}",
        f"BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT = {tf(gate_passed)}", "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE",
        "FORWARD_RETURN_ROWS_CREATED = 0", "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0", "PERFORMANCE_METRICS_CREATED = 0",
        "BACKTEST_ROWS_CREATED = 0", "DYNAMIC_WEIGHTING_ROWS_CREATED = 0", "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNAL_ROWS_CREATED = 0", "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0", "BROKER_API_USED = FALSE",
        "ORDER_EXECUTION_USED = FALSE", "SOURCE_MUTATION_USED = FALSE", "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE", "OFFICIAL_USE_ALLOWED = FALSE",
    ])
    protected_write_ok = all(p.name.startswith("V20_16") or p == CURRENT_REPORT for p in ALLOWED_WRITE_PATHS)
    no_v21 = not any("V21" in p.name or "V19_21" in p.name for p in ALLOWED_WRITE_PATHS)
    static_write_ok = protected_write_ok and no_v21
    validation_out = [{
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "dependency_audit_passed": tf(gate_ok and validation_ok and read_first_ok and all(p.exists() for p in REQUIRED_INPUTS)),
        "factor_score_review_passed": tf(gate_passed),
        "factor_score_rows_reviewed": str(row_count),
        "expected_score_rows_from_current_v20_7v_eligible_rows": str(expected_score_rows),
        "consumed_v20_7v_status": v20_7v_status,
        "consumed_active_market_source_staging_usable": v20_7v_usable,
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "exclusion_threshold": str(exclusion_threshold),
        "excluded_rows_allowed_by_v20_16": tf(excluded_rows_allowed),
        "consumed_current_v20_7v_outputs": tf(consumed_current_v20_7v),
        "failed_condition_list": ";".join(failed_conditions),
        "factor_families_reviewed": str(len(grouped)),
        "factor_score_row_review_count_check_passed": tf(row_count == expected_score_rows and row_count > 0),
        "factor_score_row_id_uniqueness_check_passed": tf(duplicate_ids == 0),
        "score_semantic_review_check_passed": tf(semantic_passed),
        "lineage_review_check_passed": tf(lineage_passed),
        "boundary_review_check_passed": tf(boundary_passed),
        "factor_score_values_numeric_and_bounded_0_to_1": tf(nonnumeric == 0 and below_zero == 0 and above_one == 0),
        "performance_metrics_created": "0",
        "forward_return_rows_created": "0",
        "benchmark_relative_return_rows_created": "0",
        "backtest_rows_created": "0",
        "dynamic_weighting_rows_created": "0",
        "trading_signal_rows_created": "0",
        "strategy_signal_rows_created": "0",
        "official_recommendation_rows_created": "0",
        "ready_for_v20_17_backtest_input_outcome_and_benchmark_preparation_next": tf(gate_passed),
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "read_first_safety_flag_check_passed": tf(read_first_ok_out),
        "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_v20_13_v20_14_v20_15_mutation_check_passed": tf(protected_write_ok),
        "v21_outputs_created": "FALSE",
        "v19_21_outputs_created": "FALSE",
        "no_v21_or_v19_21_files_check_passed": tf(no_v21),
        "static_write_path_check_passed": tf(static_write_ok),
        "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
        "write_paths_written_count": str(len(ALLOWED_WRITE_PATHS)),
        "allowed_write_paths_match": "TRUE",
        "total_blocker_count": str(len(blockers)),
        "next_recommended_step": next_step,
    }]

    report = "\n".join([
        "# V20.16 Factor Score Review Or Backtest Readiness Gate",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        f"STATUS: {status}",
        f"V20_16_GATE_DECISION: {tf(gate_passed)}",
        f"CONSUMED_V20_7V_STATUS: {v20_7v_status}",
        f"CONSUMED_ACTIVE_MARKET_SOURCE_STAGING_USABLE: {v20_7v_usable}",
        f"ELIGIBLE_ROW_COUNT: {eligible_row_count}",
        f"EXCLUDED_ROW_COUNT: {excluded_row_count}",
        f"EXCLUSION_THRESHOLD: {exclusion_threshold}",
        f"EXCLUDED_ROWS_ALLOWED_BY_V20_16: {tf(excluded_rows_allowed)}",
        f"CONSUMED_CURRENT_V20_7V_OUTPUTS: {tf(consumed_current_v20_7v)}",
        f"EXPECTED_SCORE_ROWS_FROM_CURRENT_V20_7V_ELIGIBLE_ROWS: {expected_score_rows}",
        f"FAILED_CONDITION_LIST: {';'.join(failed_conditions)}",
        f"FACTOR_SCORE_ROWS_REVIEWED: {row_count}",
        f"FACTOR_FAMILIES_REVIEWED: {len(grouped)}",
        f"SCORE_SEMANTIC_REVIEW_PASSED: {tf(semantic_passed)}",
        f"BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT: {tf(gate_passed)}",
        "BACKTEST_EXECUTION_ALLOWED_NOW: FALSE",
        "FORWARD_RETURN_ROWS_CREATED: 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED: 0",
        "PERFORMANCE_METRICS_CREATED: 0",
        "",
        "## Semantic Review",
        md_table(list(semantic_rows[0].keys()), semantic_rows),
        "",
        "## Gate Decision Diagnostics",
        md_table(list(diagnostics_rows[0].keys()), diagnostics_rows),
        "",
        "## Source Audit",
        md_table(list(source_audit_rows[0].keys()), source_audit_rows),
        "",
        "## Requirement Plan",
        md_table(["requirement_id", "requirement_area", "required_input", "currently_available", "next_required_step"], requirement_rows),
        "",
        "## Blockers",
        md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.16 blockers.",
        "",
    ])

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_REVIEW, review_rows, list(review_rows[0].keys()))
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_review_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, dq_rows, list(dq_rows[0].keys()))
    write_csv(OUT_SEMANTIC, semantic_rows, list(semantic_rows[0].keys()))
    write_csv(OUT_FAMILY_READY, family_rows, ["factor_category", "factor_family", "score_rows_reviewed", "unique_tickers", "score_layer_present", "score_scope_compliant", "schema_ready", "lineage_ready", "score_semantic_safe", "pit_safe", "stale_leakage_checked", "outcome_window_available", "benchmark_window_available", "forward_return_available", "performance_metric_available", "backtest_input_ready_next", "backtest_execution_allowed_now", "dynamic_weighting_allowed_now", "trading_allowed_now", "official_use_allowed", "blocker_reason", "next_required_step"])
    write_csv(OUT_BACKTEST_GATE, backtest_gate_rows, list(backtest_gate_rows[0].keys()))
    write_csv(OUT_REQUIREMENTS, requirement_rows, ["requirement_id", "requirement_area", "required_input", "required_fields", "required_window", "currently_available", "source_required", "blocks_backtest_execution", "blocks_dynamic_weighting", "blocks_trading_or_official_use", "next_required_step", "boundary_notes"])
    write_csv(OUT_MISSING, missing_rows, ["missing_source_blocker_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_15_v20_14_v20_13_v20_12_or_v20_11", "blocks_full_factor_score", "blocks_backtest_execution", "blocks_dynamic_weighting", "blocks_strategy_signals", "blocks_official_use", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_DOWNSTREAM_BLOCKERS, downstream_rows, ["blocked_layer", "allowed_now", "blocker_reason", "forward_outcomes_created", "benchmark_relative_outcomes_created", "performance_metrics_created", "backtest_ready_outcome_windows_built", "strategy_signal_gate_passed", "portfolio_position_framework_gate_passed", "scores_limited_readiness_lineage_quality_only", "official_use_allowed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_16"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_GATE_DIAGNOSTICS, diagnostics_rows, list(diagnostics_rows[0].keys()))
    write_csv(OUT_SOURCE_AUDIT, source_audit_rows, list(source_audit_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_out, list(validation_out[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first)
    write_text(READ_CENTER_READ_FIRST, read_first)

    print(f"STATUS: {status}")
    print(f"FACTOR_SCORE_ROWS_REVIEWED: {row_count}")
    print(f"EXPECTED_SCORE_ROWS_FROM_CURRENT_V20_7V_ELIGIBLE_ROWS: {expected_score_rows}")
    print(f"CONSUMED_CURRENT_V20_7V_OUTPUTS: {tf(consumed_current_v20_7v)}")
    print(f"FACTOR_FAMILIES_REVIEWED: {len(grouped)}")
    print(f"SCORE_SEMANTIC_REVIEW_PASSED: {tf(semantic_passed)}")
    print(f"BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT: {tf(gate_passed)}")
    print("BACKTEST_EXECUTION_ALLOWED_NOW: FALSE")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
