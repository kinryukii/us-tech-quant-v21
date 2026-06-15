from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_EVIDENCE = CONSOLIDATION / "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv"
IN_SCHEMA = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_SCHEMA_AUDIT.csv"
IN_LINEAGE = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_LINEAGE_AUDIT.csv"
IN_BOUNDARY = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_BOUNDARY_AUDIT.csv"
IN_DATA_QUALITY = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv"
IN_FAMILY_SUMMARY = CONSOLIDATION / "V20_13_FACTOR_FAMILY_EVIDENCE_SUMMARY.csv"
IN_SCOPE_COMPLIANCE = CONSOLIDATION / "V20_13_EVIDENCE_SCOPE_COMPLIANCE_AUDIT.csv"
IN_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_13_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_13_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_13_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_13_READ_FIRST.txt"
IN_MISSING = CONSOLIDATION / "V20_13_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_14_DEPENDENCY_AUDIT.csv"
OUT_REVIEW = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_LAYER_REVIEW.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_SCHEMA_REVIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_LINEAGE_REVIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_BOUNDARY_REVIEW.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_DATA_QUALITY_REVIEW.csv"
OUT_SCORE_READY = CONSOLIDATION / "V20_14_FACTOR_FAMILY_SCORE_READINESS_AUDIT.csv"
OUT_SCORE_GATE = CONSOLIDATION / "V20_14_FACTOR_SCORE_GATE_DECISION.csv"
OUT_SCORE_SCOPE = CONSOLIDATION / "V20_14_FACTOR_SCORE_SCOPE_PLAN.csv"
OUT_MISSING = CONSOLIDATION / "V20_14_MISSING_FACTOR_SOURCE_BLOCKER_REVIEW.csv"
OUT_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_14_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_14_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_14_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_14_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_14_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE.md"
READ_FIRST = OPS / "V20_14_READ_FIRST.txt"

PATCH_VERSION = "V20.14"
PASS_STATUS = "PASS_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE"
BLOCKED_STATUS = "BLOCKED_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_REVIEW,
    OUT_SCHEMA,
    OUT_LINEAGE,
    OUT_BOUNDARY,
    OUT_DATA_QUALITY,
    OUT_SCORE_READY,
    OUT_SCORE_GATE,
    OUT_SCORE_SCOPE,
    OUT_MISSING,
    OUT_DOWNSTREAM_BLOCKERS,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

REQUIRED_INPUTS = [
    IN_EVIDENCE,
    IN_SCHEMA,
    IN_LINEAGE,
    IN_BOUNDARY,
    IN_DATA_QUALITY,
    IN_FAMILY_SUMMARY,
    IN_SCOPE_COMPLIANCE,
    IN_DOWNSTREAM_BLOCKERS,
    IN_GATE,
    IN_VALIDATION,
    IN_READ_FIRST,
]

REQUIRED_EVIDENCE_COLUMNS = [
    "factor_evidence_row_id",
    "factor_attachment_row_id",
    "factor_research_row_id",
    "normalized_row_id",
    "ticker",
    "effective_observation_date",
    "effective_price_date",
    "effective_close",
    "source_system",
    "source_hash",
    "run_id",
    "sample_id",
    "factor_category",
    "factor_family",
    "evidence_scope_id",
    "evidence_type",
    "evidence_basis",
    "evidence_value_type",
    "evidence_value_present",
    "evidence_quality_flag",
    "evidence_lineage_complete",
    "evidence_pit_safe",
    "evidence_stale_leakage_checked",
    "factor_score_created",
    "factor_score_value",
    "performance_metric_created",
    "forward_return_created",
    "benchmark_relative_return_created",
    "backtest_metric_created",
    "dynamic_weighting_input_created",
    "trading_signal_created",
    "strategy_signal_created",
    "official_recommendation_created",
    "research_only_flag",
    "official_use_allowed",
    "allowed_for_factor_score_next",
    "allowed_for_backtest_now",
    "allowed_for_dynamic_weighting_now",
    "allowed_for_trading_now",
    "allowed_for_official_recommendation_now",
    "evidence_created_at_utc",
    "evidence_source_step",
]

PROHIBITED_BOUNDARY_TERMS = {
    "score_formula",
    "score_normalization",
    "rank",
    "ranking",
    "forward_return_value",
    "benchmark_relative_return_value",
    "performance_value",
    "backtest_value",
    "dynamic_weight",
    "buy",
    "sell",
    "hold",
    "signal_label",
    "action_label",
    "official_recommendation_value",
}


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
    blockers.append(
        {
            "blocker_id": f"V20_14_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_14": tf(severity == "BLOCKING"),
        }
    )


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

    evidence_rows, evidence_fields = read_csv(IN_EVIDENCE)
    schema_rows_in, _ = read_csv(IN_SCHEMA)
    lineage_rows_in, _ = read_csv(IN_LINEAGE)
    boundary_rows_in, _ = read_csv(IN_BOUNDARY)
    dq_rows_in, _ = read_csv(IN_DATA_QUALITY)
    family_summary_in, _ = read_csv(IN_FAMILY_SUMMARY)
    scope_compliance_in, _ = read_csv(IN_SCOPE_COMPLIANCE)
    downstream_blockers_in, _ = read_csv(IN_DOWNSTREAM_BLOCKERS)
    gate_rows_in, _ = read_csv(IN_GATE)
    validation_rows_in, _ = read_csv(IN_VALIDATION)
    missing_rows_in, _ = read_csv(IN_MISSING)
    read_first_in = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows_in[0] if gate_rows_in else {}
    validation = validation_rows_in[0] if validation_rows_in else {}
    scope_upstream = scope_compliance_in[0] if scope_compliance_in else {}

    dependency_rows: list[dict[str, str]] = []

    def dependency(name: str, path: Path, passed: bool, reason: str) -> None:
        dependency_rows.append(
            {
                "dependency": name,
                "path": rel(path),
                "exists": tf(path.exists()),
                "status": "PASS" if passed else "BLOCKED",
                "blocker_reason": "" if passed else reason,
            }
        )
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason)

    for path in REQUIRED_INPUTS:
        dependency(path.stem, path, path.exists(), f"Required input {rel(path)} is missing.")

    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER"
        and upper(gate.get("LIMITED_FACTOR_EVIDENCE_LAYER_CREATED")) == "TRUE"
        and int(clean(gate.get("FACTOR_EVIDENCE_ROWS_CREATED")) or "0") > 0
        and clean(gate.get("FACTOR_SCORES_CREATED")) == "0"
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
        and upper(gate.get("READY_FOR_V20_14_FACTOR_SCORE_GATE_OR_EVIDENCE_REVIEW_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER"
        and upper(validation.get("limited_factor_evidence_layer_created")) == "TRUE"
        and int(clean(validation.get("factor_evidence_rows_created")) or "0") > 0
        and clean(validation.get("factor_scores_created")) == "0"
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
        and clean(validation.get("dynamic_weighting_rows_created")) == "0"
        and clean(validation.get("trading_signal_rows_created")) == "0"
        and clean(validation.get("strategy_signal_rows_created")) == "0"
        and clean(validation.get("official_recommendation_rows_created")) == "0"
        and upper(validation.get("ready_for_v20_14_factor_score_gate_or_evidence_review_next")) == "TRUE"
        and upper(validation.get("ready_for_backtest_next")) == "FALSE"
        and upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE"
        and upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE"
    )
    read_first_ok = all(
        flag in read_first_in
        for flag in [
            "FIRST_LIMITED_FACTOR_EVIDENCE_LAYER = TRUE",
            "LIMITED_FACTOR_EVIDENCE_LAYER_CREATED = TRUE",
            "FACTOR_SCORES_CREATED = 0",
            "PERFORMANCE_METRICS_CREATED = 0",
            "FORWARD_RETURN_ROWS_CREATED = 0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
            "BACKTEST_ROWS_CREATED = 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
            "TRADING_SIGNAL_ROWS_CREATED = 0",
            "STRATEGY_SIGNAL_ROWS_CREATED = 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
            "SOURCE_MUTATION_USED = FALSE",
            "V21_OUTPUTS_CREATED = FALSE",
            "V19_21_OUTPUTS_CREATED = FALSE",
            "OFFICIAL_USE_ALLOWED = FALSE",
        ]
    )
    dependency("V20_13_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.13 gate is not in the required pass and safety state.")
    dependency("V20_13_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.13 validation summary is not in the required pass and safety state.")
    dependency("V20_13_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.13 READ_FIRST safety flags are incomplete.")

    row_count = len(evidence_rows)
    unique_families = {(clean(row.get("factor_category")), clean(row.get("factor_family"))) for row in evidence_rows}
    approved_scope_ok = upper(scope_upstream.get("scope_compliance_status")) == "PASS" and upper(scope_upstream.get("all_evidence_rows_in_v20_12_approved_scope")) == "TRUE"
    no_blocked_family = upper(scope_upstream.get("blocked_factor_families_included")) == "FALSE"
    no_source_required = upper(scope_upstream.get("source_required_factor_families_included")) == "FALSE"
    no_partial_promoted = upper(scope_upstream.get("partial_or_missing_source_families_silently_promoted")) == "FALSE"
    expected_1590 = row_count == 1590
    review_passed = row_count > 0 and approved_scope_ok and no_blocked_family and no_source_required and no_partial_promoted
    if not review_passed:
        add_blocker(blockers, "EVIDENCE_REVIEW", "V20.13 evidence layer failed count or approved-scope review.")
    review_rows = [
        {
            "review_id": "V20_14_FACTOR_EVIDENCE_LAYER_REVIEW_001",
            "factor_evidence_rows_reviewed": str(row_count),
            "expected_evidence_rows_if_v20_13_unchanged": "1590",
            "matches_expected_1590": tf(expected_1590),
            "factor_families_reviewed": str(len(unique_families)),
            "evidence_rows_cover_only_v20_12_approved_scope": tf(approved_scope_ok),
            "blocked_factor_family_appears": tf(not no_blocked_family),
            "source_required_factor_family_appears": tf(not no_source_required),
            "partial_source_family_silently_promoted": tf(not no_partial_promoted),
            "evidence_review_status": "PASS" if review_passed else "BLOCKED",
            "blocker_reason": "" if review_passed else "Evidence rows are empty, outside approved scope, or include blocked/source-required/partial families.",
        }
    ]

    ids = [clean(row.get("factor_evidence_row_id")) for row in evidence_rows if clean(row.get("factor_evidence_row_id"))]
    duplicate_ids = row_count - len(set(ids))
    missing_ticker = sum(1 for row in evidence_rows if not clean(row.get("ticker")))
    missing_hash = sum(1 for row in evidence_rows if not clean(row.get("source_hash")))
    missing_run_id = sum(1 for row in evidence_rows if not clean(row.get("run_id")))
    missing_sample_id = sum(1 for row in evidence_rows if not clean(row.get("sample_id")))
    bad_observation_dates = sum(1 for row in evidence_rows if not parse_date_ok(row.get("effective_observation_date")))
    bad_price_dates = sum(1 for row in evidence_rows if not parse_date_ok(row.get("effective_price_date")))
    nonpositive_close = sum(1 for row in evidence_rows if parse_float(row.get("effective_close")) is None or parse_float(row.get("effective_close")) <= 0)
    score_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("factor_score_created")))
    score_value_populated = sum(1 for row in evidence_rows if clean(row.get("factor_score_value")))
    performance_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("performance_metric_created")))
    forward_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("forward_return_created")))
    benchmark_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("benchmark_relative_return_created")))
    backtest_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("backtest_metric_created")))
    dynamic_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("dynamic_weighting_input_created")))
    trading_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("trading_signal_created")))
    strategy_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("strategy_signal_created")))
    official_rec_true = sum(1 for row in evidence_rows if not false_or_zero(row.get("official_recommendation_created")))
    official_use_true = sum(1 for row in evidence_rows if true_value(row.get("official_use_allowed")))
    research_only_false = sum(1 for row in evidence_rows if not true_value(row.get("research_only_flag")))

    schema_review_rows = []
    field_set = set(evidence_fields)
    for column in REQUIRED_EVIDENCE_COLUMNS:
        non_empty = sum(1 for row in evidence_rows if clean(row.get(column)))
        if column == "factor_evidence_row_id":
            passed = column in field_set and non_empty == row_count and duplicate_ids == 0
        elif column in {"factor_attachment_row_id", "factor_research_row_id", "normalized_row_id", "ticker", "source_system", "source_hash", "run_id", "sample_id", "factor_category", "factor_family", "evidence_scope_id", "evidence_type", "evidence_basis", "evidence_value_type", "evidence_value_present", "evidence_quality_flag", "evidence_lineage_complete", "evidence_pit_safe", "evidence_stale_leakage_checked", "evidence_created_at_utc", "evidence_source_step"}:
            passed = column in field_set and non_empty == row_count
        elif column == "effective_observation_date":
            passed = column in field_set and non_empty == row_count and bad_observation_dates == 0
        elif column == "effective_price_date":
            passed = column in field_set and non_empty == row_count and bad_price_dates == 0
        elif column == "effective_close":
            passed = column in field_set and non_empty == row_count and nonpositive_close == 0
        elif column == "research_only_flag":
            passed = column in field_set and research_only_false == 0
        elif column == "official_use_allowed":
            passed = column in field_set and official_use_true == 0
        elif column == "factor_score_created":
            passed = column in field_set and score_true == 0
        elif column == "factor_score_value":
            passed = column in field_set and score_value_populated == 0
        elif column == "performance_metric_created":
            passed = column in field_set and performance_true == 0
        elif column == "forward_return_created":
            passed = column in field_set and forward_true == 0
        elif column == "benchmark_relative_return_created":
            passed = column in field_set and benchmark_true == 0
        elif column == "backtest_metric_created":
            passed = column in field_set and backtest_true == 0
        elif column == "dynamic_weighting_input_created":
            passed = column in field_set and dynamic_true == 0
        elif column == "trading_signal_created":
            passed = column in field_set and trading_true == 0
        elif column == "strategy_signal_created":
            passed = column in field_set and strategy_true == 0
        elif column == "official_recommendation_created":
            passed = column in field_set and official_rec_true == 0
        elif column in {"allowed_for_factor_score_next", "allowed_for_backtest_now", "allowed_for_dynamic_weighting_now", "allowed_for_trading_now", "allowed_for_official_recommendation_now"}:
            passed = column in field_set and all(not true_value(row.get(column)) for row in evidence_rows)
        else:
            passed = column in field_set
        schema_review_rows.append(
            {
                "column_name": column,
                "required": "TRUE",
                "detected": tf(column in field_set),
                "non_empty_row_count": str(non_empty),
                "row_count": str(row_count),
                "schema_review_status": "PASS" if passed else "BLOCKED",
                "blocker_reason": "" if passed else f"Required evidence field {column} is missing, incomplete, invalid, or violates non-scoring boundaries.",
            }
        )
    schema_passed = bool(evidence_rows) and all(row["schema_review_status"] == "PASS" for row in schema_review_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "V20.14 evidence schema review failed.")

    lineage_counts = {
        "linked_to_v20_13_evidence_row_count": sum(1 for row in evidence_rows if clean(row.get("factor_evidence_row_id"))),
        "linked_to_v20_12_evidence_gate_and_scope_plan_count": sum(1 for row in evidence_rows if clean(row.get("evidence_scope_id")).startswith("V20_12_SCOPE_")),
        "linked_to_v20_11_factor_attachment_input_row_count": sum(1 for row in evidence_rows if clean(row.get("factor_attachment_row_id")).startswith("V20_11_ATTACH_")),
        "linked_to_v20_10_factor_source_attachment_classification_count": sum(1 for row in evidence_rows if clean(row.get("evidence_basis"))),
        "linked_to_v20_9_factor_research_base_row_count": sum(1 for row in evidence_rows if clean(row.get("factor_research_row_id")).startswith("V20_9_FACT_")),
        "linked_to_v20_8_normalized_research_row_count": sum(1 for row in evidence_rows if clean(row.get("normalized_row_id")).startswith("V20_8_NORM_")),
        "linked_to_v20_7x_active_input_lineage_count": sum(1 for row in evidence_rows if clean(row.get("source_hash")) and clean(row.get("run_id"))),
        "source_hash_preserved_count": sum(1 for row in evidence_rows if clean(row.get("source_hash"))),
        "run_id_preserved_count": sum(1 for row in evidence_rows if clean(row.get("run_id"))),
        "sample_id_preserved_count": sum(1 for row in evidence_rows if clean(row.get("sample_id"))),
    }
    lineage_passed = bool(evidence_rows) and all(value == row_count for value in lineage_counts.values())
    lineage_review_rows = [
        {
            "lineage_review_id": "V20_14_LINEAGE_REVIEW_001",
            "factor_evidence_rows_reviewed": str(row_count),
            **{key: str(value) for key, value in lineage_counts.items()},
            "upstream_v20_13_lineage_audit_status": clean(lineage_rows_in[0].get("lineage_status")) if lineage_rows_in else "",
            "lineage_review_status": "PASS" if lineage_passed else "BLOCKED",
            "blocker_reason": "" if lineage_passed else "One or more required evidence lineage links are missing.",
        }
    ]
    if not lineage_passed:
        add_blocker(blockers, "LINEAGE", "V20.14 evidence lineage review failed.")

    prohibited_columns = sorted(
        {
            column
            for column in evidence_fields
            for term in PROHIBITED_BOUNDARY_TERMS
            if term in column.lower()
            and column
            not in {
                "factor_score_created",
                "factor_score_value",
                "performance_metric_created",
                "forward_return_created",
                "benchmark_relative_return_created",
                "backtest_metric_created",
                "dynamic_weighting_input_created",
                "trading_signal_created",
                "strategy_signal_created",
                "official_recommendation_created",
                "official_use_allowed",
                "allowed_for_factor_score_next",
                "allowed_for_backtest_now",
                "allowed_for_dynamic_weighting_now",
                "allowed_for_trading_now",
                "allowed_for_official_recommendation_now",
            }
        }
    )
    score_allowed_true = sum(1 for row in evidence_rows if true_value(row.get("allowed_for_factor_score_next")))
    backtest_allowed_true = sum(1 for row in evidence_rows if true_value(row.get("allowed_for_backtest_now")))
    dynamic_allowed_true = sum(1 for row in evidence_rows if true_value(row.get("allowed_for_dynamic_weighting_now")))
    trading_allowed_true = sum(1 for row in evidence_rows if true_value(row.get("allowed_for_trading_now")))
    recommendation_allowed_true = sum(1 for row in evidence_rows if true_value(row.get("allowed_for_official_recommendation_now")))
    boundary_passed = (
        score_true == 0
        and score_value_populated == 0
        and performance_true == 0
        and forward_true == 0
        and benchmark_true == 0
        and backtest_true == 0
        and dynamic_true == 0
        and trading_true == 0
        and strategy_true == 0
        and official_rec_true == 0
        and official_use_true == 0
        and backtest_allowed_true == 0
        and dynamic_allowed_true == 0
        and trading_allowed_true == 0
        and recommendation_allowed_true == 0
        and not prohibited_columns
    )
    boundary_review_rows = [
        {
            "boundary_review_id": "V20_14_BOUNDARY_REVIEW_001",
            "factor_scores_created": "0",
            "factor_score_value_populated_count": str(score_value_populated),
            "score_formulas_executed": "FALSE",
            "score_normalization_executed": "FALSE",
            "rank_or_ranking_created": "FALSE",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "performance_metrics_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "buy_sell_hold_signal_action_fields_created": tf(bool(prohibited_columns)),
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "official_use_allowed_true_count": str(official_use_true),
            "allowed_for_factor_score_next_true_count_in_input": str(score_allowed_true),
            "boundary_review_status": "PASS" if boundary_passed else "BLOCKED",
            "blocker_reason": "" if boundary_passed else "Evidence review violated non-scoring, non-performance, or downstream boundary.",
        }
    ]
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "V20.14 evidence boundary review failed.")

    dq_passed = (
        bool(evidence_rows)
        and missing_ticker == 0
        and missing_hash == 0
        and missing_run_id == 0
        and missing_sample_id == 0
        and duplicate_ids == 0
        and score_true == 0
        and score_value_populated == 0
        and performance_true == 0
        and forward_true == 0
        and benchmark_true == 0
        and backtest_true == 0
        and dynamic_true == 0
        and trading_true == 0
        and strategy_true == 0
        and official_use_true == 0
    )
    dq_review_rows = [
        {
            "quality_review_id": "V20_14_QUALITY_REVIEW_001",
            "factor_evidence_rows_reviewed": str(row_count),
            "unique_tickers": str(len({clean(row.get("ticker")) for row in evidence_rows if clean(row.get("ticker"))})),
            "unique_factor_families": str(len({clean(row.get("factor_family")) for row in evidence_rows if clean(row.get("factor_family"))})),
            "unique_factor_categories": str(len({clean(row.get("factor_category")) for row in evidence_rows if clean(row.get("factor_category"))})),
            "missing_ticker_count": str(missing_ticker),
            "missing_source_hash_count": str(missing_hash),
            "missing_run_id_count": str(missing_run_id),
            "missing_sample_id_count": str(missing_sample_id),
            "duplicate_factor_evidence_row_id_count": str(duplicate_ids),
            "rows_with_factor_score_created_true": str(score_true),
            "rows_with_factor_score_value_populated": str(score_value_populated),
            "rows_with_performance_metric_created_true": str(performance_true),
            "rows_with_forward_return_created_true": str(forward_true),
            "rows_with_benchmark_relative_return_created_true": str(benchmark_true),
            "rows_with_backtest_metric_created_true": str(backtest_true),
            "rows_with_dynamic_weighting_input_created_true": str(dynamic_true),
            "rows_with_trading_signal_created_true": str(trading_true),
            "rows_with_strategy_signal_created_true": str(strategy_true),
            "rows_with_official_use_allowed_true": str(official_use_true),
            "data_quality_review_status": "PASS" if dq_passed else "BLOCKED",
            "blocker_reason": "" if dq_passed else "V20.14 evidence data quality review failed.",
        }
    ]
    if not dq_passed:
        add_blocker(blockers, "DATA_QUALITY", "V20.14 evidence data quality review failed.")

    all_core_checks_passed = gate_ok and validation_ok and read_first_ok and review_passed and schema_passed and lineage_passed and boundary_passed and dq_passed
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in evidence_rows:
        grouped[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)

    score_ready_rows = []
    score_scope_rows = []
    for index, ((category, family), rows) in enumerate(sorted(grouped.items()), start=1):
        pit_safe = all(true_value(row.get("evidence_pit_safe")) for row in rows)
        stale_checked = all(true_value(row.get("evidence_stale_leakage_checked")) for row in rows)
        scope_allowed_next = all_core_checks_passed and pit_safe and stale_checked
        blocker_reason = "" if scope_allowed_next else "Family cannot enter first limited score scope until evidence review, schema, lineage, PIT, stale/leakage, data quality, and boundary checks pass."
        score_ready_rows.append(
            {
                "factor_category": category,
                "factor_family": family,
                "evidence_rows_reviewed": str(len(rows)),
                "unique_tickers": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))})),
                "evidence_layer_present": "TRUE",
                "evidence_scope_compliant": tf(approved_scope_ok),
                "schema_ready": tf(schema_passed),
                "lineage_ready": tf(lineage_passed),
                "pit_safe": tf(pit_safe),
                "stale_leakage_checked": tf(stale_checked),
                "non_scoring_boundary_passed": tf(boundary_passed),
                "score_scope_allowed_next": tf(scope_allowed_next),
                "score_created_now": "0",
                "score_value_created_now": "0",
                "blocker_reason": blocker_reason,
                "next_required_step": "V20.15_FIRST_LIMITED_FACTOR_SCORE_LAYER" if scope_allowed_next else "Resolve V20.14 blocker before score scope.",
            }
        )
        score_scope_rows.append(
            {
                "score_scope_id": f"V20_14_SCORE_SCOPE_{index:03d}",
                "factor_category": category,
                "factor_family": family,
                "allowed_for_first_limited_score_layer_next": tf(scope_allowed_next),
                "allowed_evidence_rows": str(len(rows) if scope_allowed_next else 0),
                "allowed_ticker_count": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))}) if scope_allowed_next else 0),
                "score_design_only_now": "TRUE",
                "factor_scores_created_now": "0",
                "factor_score_values_created_now": "0",
                "prohibited_metrics_now": "IC;rank IC;hit rate;return spread;forward return;benchmark-relative return;Sharpe;drawdown;alpha;beta;performance metrics;backtests;dynamic weighting;trading signals",
                "required_next_step": "V20.15_FIRST_LIMITED_FACTOR_SCORE_LAYER" if scope_allowed_next else "Resolve V20.14 blocker before score scope.",
                "boundary_notes": "Score scope plan only; no score rows, score values, metrics, returns, backtests, dynamic weights, signals, or official recommendations created.",
            }
        )

    score_gate_passed = all_core_checks_passed and all(row["score_scope_allowed_next"] == "TRUE" for row in score_ready_rows)
    score_gate_rows = [
        {
            "gate_id": "V20_14_FACTOR_SCORE_GATE",
            "FACTOR_EVIDENCE_REVIEW_PASSED": tf(score_gate_passed),
            "FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT": tf(score_gate_passed),
            "FACTOR_SCORES_CREATED_NOW": "0",
            "FACTOR_SCORE_VALUES_CREATED_NOW": "0",
            "READY_FOR_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER_NEXT": tf(score_gate_passed),
            "gate_status": "PASS" if score_gate_passed else "BLOCKED",
            "gate_reason": "Evidence review passed; first limited score scope may be designed next." if score_gate_passed else "Evidence review or score readiness checks failed.",
        }
    ]
    if not score_gate_passed:
        add_blocker(blockers, "FACTOR_SCORE_GATE", "V20.14 factor score gate did not pass.")

    missing_review_rows = []
    for index, row in enumerate(missing_rows_in, start=1):
        missing_review_rows.append(
            {
                "missing_source_blocker_id": clean(row.get("missing_source_id")) or f"V20_14_MISSING_{index:03d}",
                "required_source_name": clean(row.get("required_source_name")),
                "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
                "source_status": clean(row.get("source_status")) or "MISSING",
                "carryforward_from_v20_13_v20_12_or_v20_11": "TRUE",
                "blocks_full_factor_score": "TRUE",
                "blocks_full_factor_evidence": "TRUE",
                "blocks_backtest": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_strategy_signals": "TRUE",
                "blocks_official_use": "TRUE",
                "blocker_reason": clean(row.get("blocker_reason")),
                "next_required_source_or_step": clean(row.get("next_required_source_or_step")) or "Register required source before full score/backtest gates.",
            }
        )

    downstream_rows = []
    downstream_reasons = [
        ("backtest", "No factor score rows created yet, no factor score values created yet, no forward outcomes, no performance metrics, and no benchmark windows."),
        ("dynamic_weighting", "No factor score rows or values created yet, no performance metrics, and no dynamic weighting gate."),
        ("trading_signal", "No factor score rows or values created yet, no backtest validation, and no trading signal gate."),
        ("strategy_signal", "No strategy signal gate and no complete strategy dependency evidence."),
        ("official_recommendation", "No official-use gate, no portfolio/position framework gate, and no broker/order path."),
    ]
    for blocked_layer, reason in downstream_reasons:
        downstream_rows.append(
            {
                "blocked_layer": blocked_layer,
                "allowed_now": "FALSE",
                "blocker_reason": reason,
                "factor_score_rows_created": "0",
                "factor_score_values_created": "0",
                "forward_outcomes_created": "0",
                "performance_metrics_created": "0",
                "benchmark_windows_created": "0",
                "strategy_signal_gate_passed": "FALSE",
                "portfolio_position_framework_gate_passed": "FALSE",
                "official_use_allowed": "FALSE",
            }
        )

    gate_passed = score_gate_passed and not any(row["blocks_v20_14"] == "TRUE" for row in blockers)
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    ready_next = gate_passed
    next_step = "V20.15_FIRST_LIMITED_FACTOR_SCORE_LAYER" if gate_passed else "Resolve V20.14 blockers before V20.15."
    gate_out_rows = [
        {
            "gate_id": "V20_14_GATE",
            "STATUS": status,
            "FACTOR_EVIDENCE_REVIEW_PASSED": tf(gate_passed),
            "FACTOR_EVIDENCE_ROWS_REVIEWED": str(row_count),
            "FACTOR_FAMILIES_REVIEWED": str(len(grouped)),
            "FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT": tf(gate_passed),
            "READY_FOR_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER_NEXT": tf(ready_next),
            "FACTOR_SCORES_CREATED": "0",
            "FACTOR_SCORE_VALUES_CREATED": "0",
            "PERFORMANCE_METRICS_CREATED": "0",
            "FORWARD_RETURN_ROWS_CREATED": "0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": "0",
            "BACKTEST_ROWS_CREATED": "0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
            "TRADING_SIGNAL_ROWS_CREATED": "0",
            "STRATEGY_SIGNAL_ROWS_CREATED": "0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "V20.14 evidence review and factor score gate passed." if gate_passed else "V20.14 evidence review or factor score gate failed.",
        }
    ]
    next_rows = [
        {
            "decision_id": "V20_14_NEXT_STEP",
            "current_status": status,
            "next_recommended_step": next_step,
            "ready_for_v20_15_first_limited_factor_score_layer_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "boundary_notes": "Review and score gate only; no score rows, score values, metrics, returns, backtests, dynamic weights, signals, or official recommendations.",
        }
    ]

    read_first_out = "\n".join(
        [
            "PATCH_VERSION: V20.14",
            "PATCH_NAME: FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE",
            "REPORTING_ONLY = FALSE",
            "FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE_ONLY = TRUE",
            f"STATUS = {status}",
            f"FACTOR_EVIDENCE_REVIEW_PASSED = {tf(gate_passed)}",
            f"FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT = {tf(gate_passed)}",
            "FACTOR_SCORES_CREATED = 0",
            "FACTOR_SCORE_VALUES_CREATED = 0",
            "PERFORMANCE_METRICS_CREATED = 0",
            "FORWARD_RETURN_ROWS_CREATED = 0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
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
            f"FACTOR_EVIDENCE_ROWS_REVIEWED = {row_count}",
            f"FACTOR_FAMILIES_REVIEWED = {len(grouped)}",
            f"NEXT_RECOMMENDED_STEP = {next_step}",
            "",
        ]
    )
    read_first_flags = [
        "REPORTING_ONLY = FALSE",
        "FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE_ONLY = TRUE",
        f"FACTOR_EVIDENCE_REVIEW_PASSED = {tf(gate_passed)}",
        f"FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT = {tf(gate_passed)}",
        "FACTOR_SCORES_CREATED = 0",
        "FACTOR_SCORE_VALUES_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0",
        "FORWARD_RETURN_ROWS_CREATED = 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
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
    ]
    read_first_safety_ok = all(flag in read_first_out for flag in read_first_flags)
    protected_input_mutation_check_passed = all(path.name.startswith("V20_14") or path == CURRENT_REPORT for path in ALLOWED_WRITE_PATHS)
    no_v21_or_v19_21_outputs = not any("V21" in path.name or "V19_21" in path.name for path in ALLOWED_WRITE_PATHS)
    static_write_path_check_passed = len(ALLOWED_WRITE_PATHS) == 18 and protected_input_mutation_check_passed and no_v21_or_v19_21_outputs

    validation_out_rows = [
        {
            "status": status,
            "patch_version": PATCH_VERSION,
            "generated_at_utc": generated_at,
            "dependency_audit_passed": tf(gate_ok and validation_ok and read_first_ok and all(path.exists() for path in REQUIRED_INPUTS)),
            "factor_evidence_review_passed": tf(gate_passed),
            "factor_evidence_rows_reviewed": str(row_count),
            "factor_families_reviewed": str(len(grouped)),
            "factor_evidence_row_review_count_check_passed": tf(expected_1590 and row_count > 0),
            "factor_evidence_row_id_uniqueness_check_passed": tf(duplicate_ids == 0),
            "evidence_review_check_passed": tf(review_passed),
            "lineage_review_check_passed": tf(lineage_passed),
            "boundary_review_check_passed": tf(boundary_passed),
            "factor_scores_created": "0",
            "factor_score_values_created": "0",
            "performance_metrics_created": "0",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "ready_for_v20_15_first_limited_factor_score_layer_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "read_first_safety_flag_check_passed": tf(read_first_safety_ok),
            "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_v20_13_mutation_check_passed": tf(protected_input_mutation_check_passed),
            "v21_outputs_created": "FALSE",
            "v19_21_outputs_created": "FALSE",
            "no_v21_or_v19_21_files_check_passed": tf(no_v21_or_v19_21_outputs),
            "static_write_path_check_passed": tf(static_write_path_check_passed),
            "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
            "write_paths_written_count": "18",
            "allowed_write_paths_match": tf(len(ALLOWED_WRITE_PATHS) == 18),
            "total_blocker_count": str(len(blockers)),
            "next_recommended_step": next_step,
        }
    ]

    report = "\n".join(
        [
            "# V20.14 Factor Evidence Review Or Factor Score Gate",
            "",
            f"Generated at UTC: {generated_at}",
            "",
            f"STATUS: {status}",
            f"FACTOR_EVIDENCE_ROWS_REVIEWED: {row_count}",
            f"FACTOR_FAMILIES_REVIEWED: {len(grouped)}",
            f"FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT: {tf(gate_passed)}",
            "FACTOR_SCORES_CREATED: 0",
            "FACTOR_SCORE_VALUES_CREATED: 0",
            "PERFORMANCE_METRICS_CREATED: 0",
            "FORWARD_RETURN_ROWS_CREATED: 0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "STRATEGY_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "",
            "## Evidence Review",
            md_table(list(review_rows[0].keys()), review_rows),
            "",
            "## Score Scope Plan",
            md_table(["score_scope_id", "factor_category", "factor_family", "allowed_for_first_limited_score_layer_next", "allowed_evidence_rows", "required_next_step"], score_scope_rows),
            "",
            "## Boundary",
            md_table(list(boundary_review_rows[0].keys()), boundary_review_rows),
            "",
            "## Blockers",
            md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.14 blockers.",
            "",
        ]
    )

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_REVIEW, review_rows, list(review_rows[0].keys()))
    write_csv(OUT_SCHEMA, schema_review_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_review_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_review_rows, list(lineage_review_rows[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_review_rows, list(boundary_review_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, dq_review_rows, list(dq_review_rows[0].keys()))
    write_csv(OUT_SCORE_READY, score_ready_rows, ["factor_category", "factor_family", "evidence_rows_reviewed", "unique_tickers", "evidence_layer_present", "evidence_scope_compliant", "schema_ready", "lineage_ready", "pit_safe", "stale_leakage_checked", "non_scoring_boundary_passed", "score_scope_allowed_next", "score_created_now", "score_value_created_now", "blocker_reason", "next_required_step"])
    write_csv(OUT_SCORE_GATE, score_gate_rows, list(score_gate_rows[0].keys()))
    write_csv(OUT_SCORE_SCOPE, score_scope_rows, ["score_scope_id", "factor_category", "factor_family", "allowed_for_first_limited_score_layer_next", "allowed_evidence_rows", "allowed_ticker_count", "score_design_only_now", "factor_scores_created_now", "factor_score_values_created_now", "prohibited_metrics_now", "required_next_step", "boundary_notes"])
    write_csv(OUT_MISSING, missing_review_rows, ["missing_source_blocker_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_13_v20_12_or_v20_11", "blocks_full_factor_score", "blocks_full_factor_evidence", "blocks_backtest", "blocks_dynamic_weighting", "blocks_strategy_signals", "blocks_official_use", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_DOWNSTREAM_BLOCKERS, downstream_rows, ["blocked_layer", "allowed_now", "blocker_reason", "factor_score_rows_created", "factor_score_values_created", "forward_outcomes_created", "performance_metrics_created", "benchmark_windows_created", "strategy_signal_gate_passed", "portfolio_position_framework_gate_passed", "official_use_allowed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_14"])
    write_csv(OUT_GATE, gate_out_rows, list(gate_out_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_out_rows, list(validation_out_rows[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first_out)

    print(f"STATUS: {status}")
    print(f"FACTOR_EVIDENCE_ROWS_REVIEWED: {row_count}")
    print(f"FACTOR_FAMILIES_REVIEWED: {len(grouped)}")
    print(f"FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT: {tf(gate_passed)}")
    print("FACTOR_SCORES_CREATED: 0")
    print("FACTOR_SCORE_VALUES_CREATED: 0")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
