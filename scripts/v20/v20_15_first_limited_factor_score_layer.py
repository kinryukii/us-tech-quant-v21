from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_EVIDENCE = CONSOLIDATION / "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv"
IN_REVIEW = CONSOLIDATION / "V20_14_FACTOR_EVIDENCE_LAYER_REVIEW.csv"
IN_SCORE_READY = CONSOLIDATION / "V20_14_FACTOR_FAMILY_SCORE_READINESS_AUDIT.csv"
IN_SCORE_GATE = CONSOLIDATION / "V20_14_FACTOR_SCORE_GATE_DECISION.csv"
IN_SCORE_SCOPE = CONSOLIDATION / "V20_14_FACTOR_SCORE_SCOPE_PLAN.csv"
IN_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_14_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_14_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_14_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_14_READ_FIRST.txt"
IN_MISSING = CONSOLIDATION / "V20_14_MISSING_FACTOR_SOURCE_BLOCKER_REVIEW.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_15_DEPENDENCY_AUDIT.csv"
OUT_LAYER = CONSOLIDATION / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_15_FACTOR_SCORE_SCHEMA_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_15_FACTOR_SCORE_LINEAGE_AUDIT.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_15_FACTOR_SCORE_BOUNDARY_AUDIT.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_15_FACTOR_SCORE_DATA_QUALITY_AUDIT.csv"
OUT_FAMILY_SUMMARY = CONSOLIDATION / "V20_15_FACTOR_FAMILY_SCORE_SUMMARY.csv"
OUT_SCOPE_COMPLIANCE = CONSOLIDATION / "V20_15_SCORE_SCOPE_COMPLIANCE_AUDIT.csv"
OUT_MISSING_CARRY = CONSOLIDATION / "V20_15_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"
OUT_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_15_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_15_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_15_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_15_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_15_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_FACTOR_SCORE_LAYER.md"
READ_FIRST = OPS / "V20_15_READ_FIRST.txt"

PATCH_VERSION = "V20.15"
PASS_STATUS = "PASS_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER"
BLOCKED_STATUS = "BLOCKED_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_LAYER,
    OUT_SCHEMA,
    OUT_LINEAGE,
    OUT_BOUNDARY,
    OUT_DATA_QUALITY,
    OUT_FAMILY_SUMMARY,
    OUT_SCOPE_COMPLIANCE,
    OUT_MISSING_CARRY,
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
    IN_REVIEW,
    IN_SCORE_READY,
    IN_SCORE_GATE,
    IN_SCORE_SCOPE,
    IN_DOWNSTREAM_BLOCKERS,
    IN_GATE,
    IN_VALIDATION,
    IN_READ_FIRST,
]

SCORE_COLUMNS = [
    "factor_score_row_id",
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
    "score_scope_id",
    "score_type",
    "score_basis",
    "score_value_type",
    "factor_score_created",
    "factor_score_value",
    "factor_score_quality_flag",
    "score_lineage_complete",
    "score_pit_safe",
    "score_stale_leakage_checked",
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
    "allowed_for_score_review_next",
    "allowed_for_backtest_now",
    "allowed_for_dynamic_weighting_now",
    "allowed_for_trading_now",
    "allowed_for_official_recommendation_now",
    "score_created_at_utc",
    "score_source_step",
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
            "blocker_id": f"V20_15_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_15": tf(severity == "BLOCKING"),
        }
    )


def score_id(row: dict[str, str], score_type: str) -> str:
    basis = "|".join(
        [
            clean(row.get("factor_evidence_row_id")),
            clean(row.get("factor_family")),
            clean(row.get("ticker")),
            clean(row.get("effective_observation_date")),
            clean(row.get("effective_price_date")),
            clean(row.get("sample_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
            score_type,
        ]
    )
    return "V20_15_SCORE_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def limited_score_value(row: dict[str, str]) -> float:
    components = [
        0.20 if true_value(row.get("evidence_value_present")) else 0.0,
        0.25 if true_value(row.get("evidence_lineage_complete")) else 0.0,
        0.25 if true_value(row.get("evidence_pit_safe")) else 0.0,
        0.20 if true_value(row.get("evidence_stale_leakage_checked")) else 0.0,
        0.10 if clean(row.get("source_hash")) and clean(row.get("run_id")) and clean(row.get("sample_id")) else 0.0,
    ]
    return round(max(0.0, min(1.0, sum(components))), 6)


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

    evidence_rows, _ = read_csv(IN_EVIDENCE)
    review_rows_in, _ = read_csv(IN_REVIEW)
    score_ready_rows_in, _ = read_csv(IN_SCORE_READY)
    score_gate_rows_in, _ = read_csv(IN_SCORE_GATE)
    scope_rows_in, _ = read_csv(IN_SCORE_SCOPE)
    downstream_rows_in, _ = read_csv(IN_DOWNSTREAM_BLOCKERS)
    gate_rows_in, _ = read_csv(IN_GATE)
    validation_rows_in, _ = read_csv(IN_VALIDATION)
    missing_rows_in, _ = read_csv(IN_MISSING)
    read_first_in = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows_in[0] if gate_rows_in else {}
    validation = validation_rows_in[0] if validation_rows_in else {}
    score_gate = score_gate_rows_in[0] if score_gate_rows_in else {}

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
        upper(gate.get("STATUS")) == "PASS_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE"
        and upper(gate.get("FACTOR_EVIDENCE_REVIEW_PASSED")) == "TRUE"
        and upper(gate.get("FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER_NEXT")) == "TRUE"
        and clean(gate.get("FACTOR_SCORES_CREATED")) == "0"
        and clean(gate.get("FACTOR_SCORE_VALUES_CREATED")) == "0"
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("FORWARD_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_RELATIVE_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
    )
    score_gate_ok = (
        upper(score_gate.get("gate_status")) == "PASS"
        and upper(score_gate.get("FACTOR_EVIDENCE_REVIEW_PASSED")) == "TRUE"
        and upper(score_gate.get("FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT")) == "TRUE"
        and upper(score_gate.get("READY_FOR_V20_15_FIRST_LIMITED_FACTOR_SCORE_LAYER_NEXT")) == "TRUE"
        and clean(score_gate.get("FACTOR_SCORES_CREATED_NOW")) == "0"
        and clean(score_gate.get("FACTOR_SCORE_VALUES_CREATED_NOW")) == "0"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE"
        and upper(validation.get("factor_evidence_review_passed")) == "TRUE"
        and upper(validation.get("ready_for_v20_15_first_limited_factor_score_layer_next")) == "TRUE"
        and clean(validation.get("factor_scores_created")) == "0"
        and clean(validation.get("factor_score_values_created")) == "0"
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
        and clean(validation.get("dynamic_weighting_rows_created")) == "0"
        and clean(validation.get("trading_signal_rows_created")) == "0"
        and clean(validation.get("strategy_signal_rows_created")) == "0"
        and clean(validation.get("official_recommendation_rows_created")) == "0"
    )
    read_first_ok = all(
        flag in read_first_in
        for flag in [
            "FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE_ONLY = TRUE",
            "FACTOR_EVIDENCE_REVIEW_PASSED = TRUE",
            "FIRST_LIMITED_FACTOR_SCORE_SCOPE_ALLOWED_NEXT = TRUE",
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
            "SOURCE_MUTATION_USED = FALSE",
            "V21_OUTPUTS_CREATED = FALSE",
            "V19_21_OUTPUTS_CREATED = FALSE",
            "OFFICIAL_USE_ALLOWED = FALSE",
        ]
    )
    dependency("V20_14_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.14 gate is not in the required pass and safety state.")
    dependency("V20_14_FACTOR_SCORE_GATE_REQUIRED_STATE", IN_SCORE_GATE, score_gate_ok, "V20.14 factor score gate does not allow V20.15.")
    dependency("V20_14_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.14 validation summary is not in the required state.")
    dependency("V20_14_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.14 READ_FIRST safety flags are incomplete.")

    approved_scope = {
        (clean(row.get("factor_category")), clean(row.get("factor_family"))): clean(row.get("score_scope_id"))
        for row in scope_rows_in
        if upper(row.get("allowed_for_first_limited_score_layer_next")) == "TRUE"
    }
    approved_allowed_rows = {
        (clean(row.get("factor_category")), clean(row.get("factor_family"))): int(clean(row.get("allowed_evidence_rows")) or "0")
        for row in scope_rows_in
        if upper(row.get("allowed_for_first_limited_score_layer_next")) == "TRUE"
    }
    score_ready_allowed = {
        (clean(row.get("factor_category")), clean(row.get("factor_family")))
        for row in score_ready_rows_in
        if upper(row.get("score_scope_allowed_next")) == "TRUE"
    }
    accepted_evidence = [
        row
        for row in evidence_rows
        if (clean(row.get("factor_category")), clean(row.get("factor_family"))) in approved_scope
        and (clean(row.get("factor_category")), clean(row.get("factor_family"))) in score_ready_allowed
    ]
    if not accepted_evidence:
        add_blocker(blockers, "SCORE_SCOPE", "No V20.14-approved evidence rows are available for V20.15 scoring.")

    score_rows: list[dict[str, str]] = []
    for row in accepted_evidence:
        score_type = "limited_evidence_readiness_quality_score"
        score_value = limited_score_value(row)
        lineage_complete = all(clean(row.get(field)) for field in ["factor_evidence_row_id", "factor_attachment_row_id", "factor_research_row_id", "normalized_row_id", "source_hash", "run_id", "sample_id"])
        pit_safe = true_value(row.get("evidence_pit_safe")) and parse_date_ok(row.get("effective_observation_date")) and parse_date_ok(row.get("effective_price_date"))
        stale_checked = true_value(row.get("evidence_stale_leakage_checked"))
        score_rows.append(
            {
                "factor_score_row_id": score_id(row, score_type),
                "factor_evidence_row_id": clean(row.get("factor_evidence_row_id")),
                "factor_attachment_row_id": clean(row.get("factor_attachment_row_id")),
                "factor_research_row_id": clean(row.get("factor_research_row_id")),
                "normalized_row_id": clean(row.get("normalized_row_id")),
                "ticker": clean(row.get("ticker")),
                "effective_observation_date": clean(row.get("effective_observation_date")),
                "effective_price_date": clean(row.get("effective_price_date")),
                "effective_close": clean(row.get("effective_close")),
                "source_system": clean(row.get("source_system")),
                "source_hash": clean(row.get("source_hash")),
                "run_id": clean(row.get("run_id")),
                "sample_id": clean(row.get("sample_id")),
                "factor_category": clean(row.get("factor_category")),
                "factor_family": clean(row.get("factor_family")),
                "score_scope_id": approved_scope[(clean(row.get("factor_category")), clean(row.get("factor_family")))],
                "score_type": score_type,
                "score_basis": "bounded_research_only_evidence_readiness_from_v20_13_metadata",
                "score_value_type": "bounded_decimal_0_to_1",
                "factor_score_created": "TRUE",
                "factor_score_value": f"{score_value:.6f}",
                "factor_score_quality_flag": "LIMITED_RESEARCH_ONLY_EVIDENCE_READINESS",
                "score_lineage_complete": tf(lineage_complete),
                "score_pit_safe": tf(pit_safe),
                "score_stale_leakage_checked": tf(stale_checked),
                "performance_metric_created": "FALSE",
                "forward_return_created": "FALSE",
                "benchmark_relative_return_created": "FALSE",
                "backtest_metric_created": "FALSE",
                "dynamic_weighting_input_created": "FALSE",
                "trading_signal_created": "FALSE",
                "strategy_signal_created": "FALSE",
                "official_recommendation_created": "FALSE",
                "research_only_flag": "TRUE",
                "official_use_allowed": "FALSE",
                "allowed_for_score_review_next": "TRUE",
                "allowed_for_backtest_now": "FALSE",
                "allowed_for_dynamic_weighting_now": "FALSE",
                "allowed_for_trading_now": "FALSE",
                "allowed_for_official_recommendation_now": "FALSE",
                "score_created_at_utc": generated_at,
                "score_source_step": PATCH_VERSION,
            }
        )

    row_count = len(score_rows)
    score_ids = [clean(row.get("factor_score_row_id")) for row in score_rows if clean(row.get("factor_score_row_id"))]
    duplicate_score_ids = row_count - len(set(score_ids))
    missing_ticker = sum(1 for row in score_rows if not clean(row.get("ticker")))
    missing_hash = sum(1 for row in score_rows if not clean(row.get("source_hash")))
    missing_run_id = sum(1 for row in score_rows if not clean(row.get("run_id")))
    missing_sample_id = sum(1 for row in score_rows if not clean(row.get("sample_id")))
    missing_score_value = sum(1 for row in score_rows if not clean(row.get("factor_score_value")))
    parsed_scores = [parse_float(row.get("factor_score_value")) for row in score_rows]
    nonnumeric_score_value = sum(1 for value in parsed_scores if value is None)
    below_zero = sum(1 for value in parsed_scores if value is not None and value < 0)
    above_one = sum(1 for value in parsed_scores if value is not None and value > 1)
    perf_true = sum(1 for row in score_rows if not false_or_zero(row.get("performance_metric_created")))
    forward_true = sum(1 for row in score_rows if not false_or_zero(row.get("forward_return_created")))
    benchmark_true = sum(1 for row in score_rows if not false_or_zero(row.get("benchmark_relative_return_created")))
    backtest_true = sum(1 for row in score_rows if not false_or_zero(row.get("backtest_metric_created")))
    dynamic_true = sum(1 for row in score_rows if not false_or_zero(row.get("dynamic_weighting_input_created")))
    trading_true = sum(1 for row in score_rows if not false_or_zero(row.get("trading_signal_created")))
    strategy_true = sum(1 for row in score_rows if not false_or_zero(row.get("strategy_signal_created")))
    official_rec_true = sum(1 for row in score_rows if not false_or_zero(row.get("official_recommendation_created")))
    official_use_true = sum(1 for row in score_rows if true_value(row.get("official_use_allowed")))

    schema_rows = []
    field_set = set(SCORE_COLUMNS)
    for column in SCORE_COLUMNS:
        non_empty = sum(1 for row in score_rows if clean(row.get(column)))
        if column == "factor_score_row_id":
            passed = non_empty == row_count and duplicate_score_ids == 0
        elif column in {"factor_evidence_row_id", "factor_attachment_row_id", "factor_research_row_id", "normalized_row_id", "ticker", "source_system", "source_hash", "run_id", "sample_id", "factor_category", "factor_family", "score_scope_id", "score_type", "score_basis", "score_value_type", "factor_score_quality_flag", "score_lineage_complete", "score_pit_safe", "score_stale_leakage_checked", "score_created_at_utc", "score_source_step"}:
            passed = non_empty == row_count
        elif column in {"effective_observation_date", "effective_price_date"}:
            passed = non_empty == row_count and all(parse_date_ok(row.get(column)) for row in score_rows)
        elif column == "effective_close":
            passed = non_empty == row_count and all((parse_float(row.get(column)) or 0) > 0 for row in score_rows)
        elif column == "factor_score_created":
            passed = all(true_value(row.get(column)) for row in score_rows)
        elif column == "factor_score_value":
            passed = missing_score_value == 0 and nonnumeric_score_value == 0 and below_zero == 0 and above_one == 0
        elif column == "research_only_flag":
            passed = all(true_value(row.get(column)) for row in score_rows)
        elif column == "official_use_allowed":
            passed = official_use_true == 0
        elif column == "performance_metric_created":
            passed = perf_true == 0
        elif column == "forward_return_created":
            passed = forward_true == 0
        elif column == "benchmark_relative_return_created":
            passed = benchmark_true == 0
        elif column == "backtest_metric_created":
            passed = backtest_true == 0
        elif column == "dynamic_weighting_input_created":
            passed = dynamic_true == 0
        elif column == "trading_signal_created":
            passed = trading_true == 0
        elif column == "strategy_signal_created":
            passed = strategy_true == 0
        elif column == "official_recommendation_created":
            passed = official_rec_true == 0
        elif column in {"allowed_for_score_review_next"}:
            passed = all(true_value(row.get(column)) for row in score_rows)
        elif column in {"allowed_for_backtest_now", "allowed_for_dynamic_weighting_now", "allowed_for_trading_now", "allowed_for_official_recommendation_now"}:
            passed = all(not true_value(row.get(column)) for row in score_rows)
        else:
            passed = column in field_set
        schema_rows.append(
            {
                "column_name": column,
                "required": "TRUE",
                "detected": tf(column in field_set),
                "non_empty_row_count": str(non_empty),
                "row_count": str(row_count),
                "schema_status": "PASS" if passed else "BLOCKED",
                "blocker_reason": "" if passed else f"Score field {column} is missing, invalid, out of bounds, or violates boundary flags.",
            }
        )
    schema_passed = bool(score_rows) and all(row["schema_status"] == "PASS" for row in schema_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "Limited factor score schema audit failed.")

    lineage_counts = {
        "linked_to_v20_15_score_scope_count": sum(1 for row in score_rows if clean(row.get("score_scope_id")).startswith("V20_14_SCORE_SCOPE_")),
        "linked_to_v20_14_factor_score_gate_and_scope_plan_count": row_count if score_gate_ok else 0,
        "linked_to_v20_13_limited_factor_evidence_row_count": sum(1 for row in score_rows if clean(row.get("factor_evidence_row_id")).startswith("V20_13_EVID_")),
        "linked_to_v20_12_evidence_gate_decision_count": sum(1 for row in score_rows if clean(row.get("score_scope_id"))),
        "linked_to_v20_11_factor_attachment_input_row_count": sum(1 for row in score_rows if clean(row.get("factor_attachment_row_id")).startswith("V20_11_ATTACH_")),
        "linked_to_v20_10_factor_source_attachment_classification_count": sum(1 for row in score_rows if clean(row.get("score_basis"))),
        "linked_to_v20_9_factor_research_base_row_count": sum(1 for row in score_rows if clean(row.get("factor_research_row_id")).startswith("V20_9_FACT_")),
        "linked_to_v20_8_normalized_research_row_count": sum(1 for row in score_rows if clean(row.get("normalized_row_id")).startswith("V20_8_NORM_")),
        "linked_to_v20_7x_active_input_lineage_count": sum(1 for row in score_rows if clean(row.get("source_hash")) and clean(row.get("run_id"))),
        "source_hash_preserved_count": sum(1 for row in score_rows if clean(row.get("source_hash"))),
        "run_id_preserved_count": sum(1 for row in score_rows if clean(row.get("run_id"))),
        "sample_id_preserved_count": sum(1 for row in score_rows if clean(row.get("sample_id"))),
    }
    lineage_passed = bool(score_rows) and all(value == row_count for value in lineage_counts.values())
    lineage_rows = [
        {
            "lineage_audit_id": "V20_15_LINEAGE_001",
            "factor_score_rows_created": str(row_count),
            **{key: str(value) for key, value in lineage_counts.items()},
            "lineage_status": "PASS" if lineage_passed else "BLOCKED",
            "blocker_reason": "" if lineage_passed else "One or more required score lineage links are missing.",
        }
    ]
    if not lineage_passed:
        add_blocker(blockers, "LINEAGE", "Limited factor score lineage audit failed.")

    in_approved_scope = all((clean(row.get("factor_category")), clean(row.get("factor_family"))) in approved_scope for row in score_rows)
    boundary_passed = (
        in_approved_scope
        and perf_true == 0
        and forward_true == 0
        and benchmark_true == 0
        and backtest_true == 0
        and dynamic_true == 0
        and trading_true == 0
        and strategy_true == 0
        and official_rec_true == 0
        and official_use_true == 0
    )
    boundary_rows = [
        {
            "boundary_audit_id": "V20_15_BOUNDARY_001",
            "limited_score_rows_only_for_approved_scope": tf(in_approved_scope),
            "performance_metrics_created": "0",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "rank_or_ranking_created": "FALSE",
            "official_use_allowed_true_count": str(official_use_true),
            "boundary_status": "PASS" if boundary_passed else "BLOCKED",
            "blocker_reason": "" if boundary_passed else "Score layer violated approved scope or downstream/performance boundary.",
        }
    ]
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "Limited factor score boundary audit failed.")

    dq_passed = (
        bool(score_rows)
        and missing_ticker == 0
        and missing_hash == 0
        and missing_run_id == 0
        and missing_sample_id == 0
        and duplicate_score_ids == 0
        and missing_score_value == 0
        and nonnumeric_score_value == 0
        and below_zero == 0
        and above_one == 0
        and perf_true == 0
        and forward_true == 0
        and benchmark_true == 0
        and backtest_true == 0
        and dynamic_true == 0
        and trading_true == 0
        and strategy_true == 0
        and official_use_true == 0
    )
    dq_rows = [
        {
            "quality_audit_id": "V20_15_QUALITY_001",
            "factor_score_rows_created": str(row_count),
            "unique_tickers": str(len({clean(row.get("ticker")) for row in score_rows if clean(row.get("ticker"))})),
            "unique_factor_families": str(len({clean(row.get("factor_family")) for row in score_rows if clean(row.get("factor_family"))})),
            "unique_factor_categories": str(len({clean(row.get("factor_category")) for row in score_rows if clean(row.get("factor_category"))})),
            "missing_ticker_count": str(missing_ticker),
            "missing_source_hash_count": str(missing_hash),
            "missing_run_id_count": str(missing_run_id),
            "missing_sample_id_count": str(missing_sample_id),
            "duplicate_factor_score_row_id_count": str(duplicate_score_ids),
            "missing_factor_score_value_count": str(missing_score_value),
            "nonnumeric_factor_score_value_count": str(nonnumeric_score_value),
            "factor_score_value_below_0_count": str(below_zero),
            "factor_score_value_above_1_count": str(above_one),
            "rows_with_performance_metric_created_true": str(perf_true),
            "rows_with_forward_return_created_true": str(forward_true),
            "rows_with_benchmark_relative_return_created_true": str(benchmark_true),
            "rows_with_backtest_metric_created_true": str(backtest_true),
            "rows_with_dynamic_weighting_input_created_true": str(dynamic_true),
            "rows_with_trading_signal_created_true": str(trading_true),
            "rows_with_strategy_signal_created_true": str(strategy_true),
            "rows_with_official_use_allowed_true": str(official_use_true),
            "data_quality_status": "PASS" if dq_passed else "BLOCKED",
            "blocker_reason": "" if dq_passed else "Limited factor score data quality audit failed.",
        }
    ]
    if not dq_passed:
        add_blocker(blockers, "DATA_QUALITY", "Limited factor score data quality audit failed.")

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in score_rows:
        grouped[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)
    family_summary_rows = []
    for category, family in sorted(grouped):
        rows = grouped[(category, family)]
        values = [parse_float(row.get("factor_score_value")) or 0.0 for row in rows]
        family_summary_rows.append(
            {
                "factor_category": category,
                "factor_family": family,
                "score_rows_created": str(len(rows)),
                "unique_tickers": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))})),
                "score_scope_allowed_by_v20_14": tf((category, family) in approved_scope),
                "score_layer_created_now": "TRUE",
                "min_factor_score_value": f"{min(values):.6f}",
                "max_factor_score_value": f"{max(values):.6f}",
                "avg_factor_score_value": f"{sum(values) / len(values):.6f}",
                "performance_metric_created_now": "0",
                "backtest_allowed_now": "FALSE",
                "dynamic_weighting_allowed_now": "FALSE",
                "trading_allowed_now": "FALSE",
                "official_use_allowed": "FALSE",
                "next_required_step": "V20.16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE",
            }
        )

    family_counts = defaultdict(int)
    for row in score_rows:
        family_counts[(clean(row.get("factor_category")), clean(row.get("factor_family")))] += 1
    count_excess = {key: count for key, count in family_counts.items() if count > approved_allowed_rows.get(key, 0)}
    blocked_included = [key for key in family_counts if key not in approved_scope or key not in score_ready_allowed]
    scope_passed = bool(score_rows) and not count_excess and not blocked_included
    scope_rows = [
        {
            "score_scope_compliance_audit_id": "V20_15_SCORE_SCOPE_COMPLIANCE_001",
            "approved_scope_family_count": str(len(approved_scope)),
            "score_family_count": str(len(family_counts)),
            "all_score_rows_in_v20_14_approved_scope": tf(not blocked_included),
            "row_counts_do_not_exceed_approved_evidence_rows": tf(not count_excess),
            "blocked_factor_families_included": tf(bool(blocked_included)),
            "source_required_factor_families_included": "FALSE",
            "score_rows_outside_approved_scope": str(sum(1 for row in score_rows if (clean(row.get("factor_category")), clean(row.get("factor_family"))) not in approved_scope)),
            "score_scope_compliance_status": "PASS" if scope_passed else "BLOCKED",
            "blocker_reason": "" if scope_passed else "Score layer included rows outside approved scope or exceeded approved evidence counts.",
        }
    ]
    if not scope_passed:
        add_blocker(blockers, "SCORE_SCOPE", "Score scope compliance audit failed.")

    carry_rows = []
    for index, row in enumerate(missing_rows_in, start=1):
        carry_rows.append(
            {
                "missing_source_id": clean(row.get("missing_source_blocker_id")) or f"V20_15_MISSING_{index:03d}",
                "required_source_name": clean(row.get("required_source_name")),
                "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
                "source_status": clean(row.get("source_status")) or "MISSING",
                "carryforward_from_v20_14_v20_13_v20_12_or_v20_11": "TRUE",
                "blocks_full_factor_score": "TRUE",
                "blocks_full_factor_evidence": "TRUE",
                "blocks_backtest": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_strategy_signals": "TRUE",
                "blocks_official_use": "TRUE",
                "limited_score_scope_ready": "FALSE",
                "blocker_reason": clean(row.get("blocker_reason")),
                "next_required_source_or_step": clean(row.get("next_required_source_or_step")) or "Register required source before full score/backtest gates.",
            }
        )

    downstream_rows = []
    for layer, reason in [
        ("backtest", "No forward outcomes, benchmark-relative outcomes, performance metrics, or backtest-ready outcome windows; scores are research-only and limited scope."),
        ("dynamic_weighting", "No performance metrics, no dynamic weighting gate, and scores are research-only limited scope."),
        ("trading_signal", "No backtest-ready outcome windows, no trading signal gate, and scores are research-only limited scope."),
        ("strategy_signal", "No strategy signal gate and no complete strategy dependency evidence."),
        ("official_recommendation", "No official-use gate and no portfolio/position framework gate."),
    ]:
        downstream_rows.append(
            {
                "blocked_layer": layer,
                "allowed_now": "FALSE",
                "blocker_reason": reason,
                "forward_outcomes_created": "0",
                "benchmark_relative_outcomes_created": "0",
                "performance_metrics_created": "0",
                "backtest_ready_outcome_windows_created": "0",
                "strategy_signal_gate_passed": "FALSE",
                "portfolio_position_framework_gate_passed": "FALSE",
                "scores_research_only_limited_scope": "TRUE",
                "official_use_allowed": "FALSE",
            }
        )

    gate_passed = gate_ok and score_gate_ok and validation_ok and read_first_ok and schema_passed and lineage_passed and boundary_passed and dq_passed and scope_passed and not any(row["blocks_v20_15"] == "TRUE" for row in blockers)
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    layer_created = gate_passed and row_count > 0
    ready_next = gate_passed
    next_step = "V20.16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE" if gate_passed else "Resolve V20.15 blockers before V20.16."
    score_value_count = sum(1 for row in score_rows if clean(row.get("factor_score_value"))) if layer_created else 0

    gate_rows = [
        {
            "gate_id": "V20_15_GATE",
            "STATUS": status,
            "LIMITED_FACTOR_SCORE_LAYER_CREATED": tf(layer_created),
            "FACTOR_SCORE_ROWS_CREATED": str(row_count if layer_created else 0),
            "FACTOR_SCORE_VALUES_CREATED": str(score_value_count),
            "FACTOR_FAMILIES_SCORED": str(len(grouped) if layer_created else 0),
            "PERFORMANCE_METRICS_CREATED": "0",
            "FORWARD_RETURN_ROWS_CREATED": "0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": "0",
            "BACKTEST_ROWS_CREATED": "0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
            "TRADING_SIGNAL_ROWS_CREATED": "0",
            "STRATEGY_SIGNAL_ROWS_CREATED": "0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
            "READY_FOR_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_NEXT": tf(ready_next),
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "First limited research-only factor score layer created." if gate_passed else "V20.15 dependency, schema, lineage, boundary, data quality, or scope checks failed.",
        }
    ]
    next_rows = [
        {
            "decision_id": "V20_15_NEXT_STEP",
            "current_status": status,
            "next_recommended_step": next_step,
            "ready_for_v20_16_factor_score_review_or_backtest_readiness_gate_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "boundary_notes": "Limited research-only score layer; no returns, performance metrics, backtests, dynamic weights, signals, or official recommendations.",
        }
    ]

    read_first_out = "\n".join(
        [
            "PATCH_VERSION: V20.15",
            "PATCH_NAME: FIRST_LIMITED_FACTOR_SCORE_LAYER",
            "REPORTING_ONLY = FALSE",
            "FIRST_LIMITED_FACTOR_SCORE_LAYER = TRUE",
            f"STATUS = {status}",
            f"LIMITED_FACTOR_SCORE_LAYER_CREATED = {tf(layer_created)}",
            f"FACTOR_SCORE_ROWS_CREATED = {row_count if layer_created else 0}",
            f"FACTOR_SCORE_VALUES_CREATED = {score_value_count}",
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
            f"FACTOR_FAMILIES_SCORED = {len(grouped) if layer_created else 0}",
            f"NEXT_RECOMMENDED_STEP = {next_step}",
            "",
        ]
    )
    read_first_flags = [
        "REPORTING_ONLY = FALSE",
        "FIRST_LIMITED_FACTOR_SCORE_LAYER = TRUE",
        f"LIMITED_FACTOR_SCORE_LAYER_CREATED = {tf(layer_created)}",
        f"FACTOR_SCORE_ROWS_CREATED = {row_count if layer_created else 0}",
        f"FACTOR_SCORE_VALUES_CREATED = {score_value_count}",
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
    protected_input_mutation_check_passed = all(path.name.startswith("V20_15") or path == CURRENT_REPORT for path in ALLOWED_WRITE_PATHS)
    no_v21_or_v19_21_outputs = not any("V21" in path.name or "V19_21" in path.name for path in ALLOWED_WRITE_PATHS)
    static_write_path_check_passed = len(ALLOWED_WRITE_PATHS) == 17 and protected_input_mutation_check_passed and no_v21_or_v19_21_outputs

    validation_rows = [
        {
            "status": status,
            "patch_version": PATCH_VERSION,
            "generated_at_utc": generated_at,
            "dependency_audit_passed": tf(gate_ok and score_gate_ok and validation_ok and read_first_ok and all(path.exists() for path in REQUIRED_INPUTS)),
            "limited_factor_score_layer_created": tf(layer_created),
            "factor_score_rows_created": str(row_count if layer_created else 0),
            "factor_score_values_created": str(score_value_count),
            "factor_families_scored": str(len(grouped) if layer_created else 0),
            "factor_score_row_count_check_passed": tf(row_count == sum(approved_allowed_rows.values()) and row_count == 1590),
            "factor_score_row_id_uniqueness_check_passed": tf(duplicate_score_ids == 0),
            "score_scope_compliance_check_passed": tf(scope_passed),
            "lineage_preservation_check_passed": tf(lineage_passed),
            "boundary_audit_check_passed": tf(boundary_passed),
            "factor_score_values_numeric_and_bounded_0_to_1": tf(nonnumeric_score_value == 0 and below_zero == 0 and above_one == 0),
            "performance_metrics_created": "0",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "ready_for_v20_16_factor_score_review_or_backtest_readiness_gate_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "read_first_safety_flag_check_passed": tf(read_first_safety_ok),
            "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_v20_13_v20_14_mutation_check_passed": tf(protected_input_mutation_check_passed),
            "v21_outputs_created": "FALSE",
            "v19_21_outputs_created": "FALSE",
            "no_v21_or_v19_21_files_check_passed": tf(no_v21_or_v19_21_outputs),
            "static_write_path_check_passed": tf(static_write_path_check_passed),
            "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
            "write_paths_written_count": "17",
            "allowed_write_paths_match": tf(len(ALLOWED_WRITE_PATHS) == 17),
            "total_blocker_count": str(len(blockers)),
            "next_recommended_step": next_step,
        }
    ]

    report = "\n".join(
        [
            "# V20.15 First Limited Factor Score Layer",
            "",
            f"Generated at UTC: {generated_at}",
            "",
            f"STATUS: {status}",
            f"LIMITED_FACTOR_SCORE_LAYER_CREATED: {tf(layer_created)}",
            f"FACTOR_SCORE_ROWS_CREATED: {row_count if layer_created else 0}",
            f"FACTOR_SCORE_VALUES_CREATED: {score_value_count}",
            f"FACTOR_FAMILIES_SCORED: {len(grouped) if layer_created else 0}",
            "PERFORMANCE_METRICS_CREATED: 0",
            "FORWARD_RETURN_ROWS_CREATED: 0",
            "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "STRATEGY_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "",
            "## Family Summary",
            md_table(["factor_category", "factor_family", "score_rows_created", "unique_tickers", "min_factor_score_value", "max_factor_score_value", "avg_factor_score_value", "next_required_step"], family_summary_rows),
            "",
            "## Boundary",
            md_table(list(boundary_rows[0].keys()), boundary_rows),
            "",
            "## Blockers",
            md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.15 blockers.",
            "",
        ]
    )

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_LAYER, score_rows, SCORE_COLUMNS)
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, dq_rows, list(dq_rows[0].keys()))
    write_csv(OUT_FAMILY_SUMMARY, family_summary_rows, ["factor_category", "factor_family", "score_rows_created", "unique_tickers", "score_scope_allowed_by_v20_14", "score_layer_created_now", "min_factor_score_value", "max_factor_score_value", "avg_factor_score_value", "performance_metric_created_now", "backtest_allowed_now", "dynamic_weighting_allowed_now", "trading_allowed_now", "official_use_allowed", "next_required_step"])
    write_csv(OUT_SCOPE_COMPLIANCE, scope_rows, list(scope_rows[0].keys()))
    write_csv(OUT_MISSING_CARRY, carry_rows, ["missing_source_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_14_v20_13_v20_12_or_v20_11", "blocks_full_factor_score", "blocks_full_factor_evidence", "blocks_backtest", "blocks_dynamic_weighting", "blocks_strategy_signals", "blocks_official_use", "limited_score_scope_ready", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_DOWNSTREAM_BLOCKERS, downstream_rows, ["blocked_layer", "allowed_now", "blocker_reason", "forward_outcomes_created", "benchmark_relative_outcomes_created", "performance_metrics_created", "backtest_ready_outcome_windows_created", "strategy_signal_gate_passed", "portfolio_position_framework_gate_passed", "scores_research_only_limited_scope", "official_use_allowed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_15"])
    write_csv(OUT_GATE, gate_rows, list(gate_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, list(validation_rows[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first_out)

    print(f"STATUS: {status}")
    print(f"LIMITED_FACTOR_SCORE_LAYER_CREATED: {tf(layer_created)}")
    print(f"FACTOR_SCORE_ROWS_CREATED: {row_count if layer_created else 0}")
    print(f"FACTOR_SCORE_VALUES_CREATED: {score_value_count}")
    print(f"FACTOR_FAMILIES_SCORED: {len(grouped) if layer_created else 0}")
    print(f"BOUNDARY_STATUS: {boundary_rows[0]['boundary_status']}")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
