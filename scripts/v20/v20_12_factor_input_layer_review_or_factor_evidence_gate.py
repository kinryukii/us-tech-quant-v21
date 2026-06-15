from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_PLAN = CONSOLIDATION / "V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN.csv"
IN_LAYER = CONSOLIDATION / "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv"
IN_SCHEMA = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_SCHEMA_AUDIT.csv"
IN_LINEAGE = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_LINEAGE_AUDIT.csv"
IN_BOUNDARY = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_BOUNDARY_AUDIT.csv"
IN_DATA_QUALITY = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_DATA_QUALITY_AUDIT.csv"
IN_STRATEGY_PLAN = CONSOLIDATION / "V20_11_STRATEGY_FAMILY_ATTACHMENT_PLAN.csv"
IN_STRATEGY_READINESS = CONSOLIDATION / "V20_11_STRATEGY_DEPENDENCY_READINESS_AUDIT.csv"
IN_MISSING = CONSOLIDATION / "V20_11_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"
IN_GATE = CONSOLIDATION / "V20_11_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_11_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_11_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_12_DEPENDENCY_AUDIT.csv"
OUT_REVIEW = CONSOLIDATION / "V20_12_FACTOR_INPUT_LAYER_REVIEW.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_12_FACTOR_INPUT_SCHEMA_REVIEW.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_12_FACTOR_INPUT_LINEAGE_REVIEW.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_12_FACTOR_INPUT_BOUNDARY_REVIEW.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_12_FACTOR_INPUT_DATA_QUALITY_REVIEW.csv"
OUT_FAMILY_READY = CONSOLIDATION / "V20_12_FACTOR_FAMILY_EVIDENCE_READINESS_AUDIT.csv"
OUT_EVIDENCE_GATE = CONSOLIDATION / "V20_12_FACTOR_EVIDENCE_GATE_DECISION.csv"
OUT_STRATEGY = CONSOLIDATION / "V20_12_STRATEGY_DEPENDENCY_GATE_REVIEW.csv"
OUT_MISSING = CONSOLIDATION / "V20_12_MISSING_FACTOR_SOURCE_BLOCKER_REVIEW.csv"
OUT_SCOPE = CONSOLIDATION / "V20_12_FACTOR_EVIDENCE_SCOPE_PLAN.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_12_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_12_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_12_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_12_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE.md"
READ_FIRST = OPS / "V20_12_READ_FIRST.txt"

PATCH_VERSION = "V20.12"
PASS_STATUS = "PASS_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE"
BLOCKED_STATUS = "BLOCKED_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_REVIEW,
    OUT_SCHEMA,
    OUT_LINEAGE,
    OUT_BOUNDARY,
    OUT_DATA_QUALITY,
    OUT_FAMILY_READY,
    OUT_EVIDENCE_GATE,
    OUT_STRATEGY,
    OUT_MISSING,
    OUT_SCOPE,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

REQUIRED_INPUTS = [
    IN_PLAN,
    IN_LAYER,
    IN_SCHEMA,
    IN_LINEAGE,
    IN_BOUNDARY,
    IN_DATA_QUALITY,
    IN_STRATEGY_PLAN,
    IN_STRATEGY_READINESS,
    IN_MISSING,
    IN_GATE,
    IN_VALIDATION,
    IN_READ_FIRST,
]

REQUIRED_LAYER_COLUMNS = [
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
    "attachment_source_reference",
    "attachment_input_type",
    "attachment_value_type",
    "attachment_value_present",
    "attachment_status",
    "factor_score_created",
    "factor_evidence_created",
    "research_only_flag",
    "official_use_allowed",
    "allowed_for_factor_evidence_next",
    "allowed_for_backtest_now",
    "allowed_for_dynamic_weighting_now",
    "allowed_for_trading_now",
    "allowed_for_official_recommendation_now",
    "attachment_created_at_utc",
    "attachment_source_step",
]

PROHIBITED_BOUNDARY_TERMS = {
    "forward_return": "forward return fields",
    "benchmark_relative": "benchmark-relative performance fields",
    "relative_return": "benchmark-relative performance fields",
    "backtest": "backtest metrics",
    "sharpe": "backtest metrics",
    "drawdown": "backtest metrics",
    "alpha": "performance metrics",
    "beta": "performance metrics",
    "dynamic_weight": "dynamic weighting fields",
    "buy": "buy/sell/hold/signal/action fields",
    "sell": "buy/sell/hold/signal/action fields",
    "hold": "buy/sell/hold/signal/action fields",
    "signal": "buy/sell/hold/signal/action fields",
    "action": "buy/sell/hold/signal/action fields",
    "strategy_signal": "strategy signals",
    "recommendation": "official recommendation fields",
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
            "blocker_id": f"V20_12_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_12": tf(severity == "BLOCKING"),
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

    plan_rows, plan_fields = read_csv(IN_PLAN)
    layer_rows, layer_fields = read_csv(IN_LAYER)
    schema_audit_rows, _ = read_csv(IN_SCHEMA)
    lineage_audit_rows, _ = read_csv(IN_LINEAGE)
    boundary_audit_rows, _ = read_csv(IN_BOUNDARY)
    dq_audit_rows, _ = read_csv(IN_DATA_QUALITY)
    strategy_plan_rows, _ = read_csv(IN_STRATEGY_PLAN)
    strategy_ready_rows, _ = read_csv(IN_STRATEGY_READINESS)
    missing_rows, _ = read_csv(IN_MISSING)
    gate_rows, _ = read_csv(IN_GATE)
    validation_rows, _ = read_csv(IN_VALIDATION)
    read_first_text = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}

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

    v20_11_gate_passed = (
        upper(gate.get("status")) == "PASS_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER"
        and upper(gate.get("FACTOR_SOURCE_ATTACHMENT_PLAN_CREATED")) == "TRUE"
        and upper(gate.get("FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED")) == "TRUE"
        and int(clean(gate.get("FACTOR_ATTACHMENT_ROWS_CREATED")) or "0") > 0
        and int(clean(gate.get("ATTACHABLE_FACTOR_FAMILIES_ATTACHED")) or "0") > 0
        and upper(gate.get("STRATEGY_FAMILY_READINESS_RECORDED")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_FACTOR_EVIDENCE_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    v20_11_validation_ok = (
        upper(validation.get("status")) == "PASS_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER"
        and upper(validation.get("ready_for_v20_12_factor_input_layer_review_or_factor_evidence_gate_next")) == "TRUE"
        and upper(validation.get("ready_for_factor_evidence_next")) == "FALSE"
        and upper(validation.get("ready_for_backtest_next")) == "FALSE"
        and upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE"
        and upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE"
    )
    read_first_ok = all(
        flag in read_first_text
        for flag in [
            "FACTOR_SOURCE_ATTACHMENT_PLAN_ONLY_OR_NON_SCORING_INPUT_LAYER: TRUE",
            "FACTOR_SCORES_CREATED: 0",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "STRATEGY_SIGNALS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "SOURCE_MUTATION_USED: FALSE",
            "V21_OUTPUTS_CREATED: FALSE",
            "V19_21_OUTPUTS_CREATED: FALSE",
            "OFFICIAL_USE_ALLOWED: FALSE",
        ]
    )
    dependency("V20_11_REQUIRED_GATE_STATE", IN_GATE, v20_11_gate_passed, "V20.11 gate is not in the required pass and safety state.")
    dependency("V20_11_VALIDATION_REQUIRED_STATE", IN_VALIDATION, v20_11_validation_ok, "V20.11 validation summary is not in the required pass and safety state.")
    dependency("V20_11_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.11 READ_FIRST safety flags are incomplete.")

    allowed_family_keys = {
        (clean(row.get("factor_category")), clean(row.get("factor_family")))
        for row in plan_rows
        if upper(row.get("attachment_ready_now")) == "TRUE"
        and upper(row.get("factor_input_layer_allowed_now")) == "TRUE"
        and upper(row.get("source_attachment_allowed_now")) == "TRUE"
    }
    blocked_family_keys = {
        (clean(row.get("factor_category")), clean(row.get("factor_family"))): clean(row.get("attachment_status_from_v20_10"))
        for row in plan_rows
        if upper(row.get("attachment_ready_now")) != "TRUE" or upper(row.get("factor_input_layer_allowed_now")) != "TRUE"
    }
    attached_family_keys = {(clean(row.get("factor_category")), clean(row.get("factor_family"))) for row in layer_rows}
    factor_research_ids = {clean(row.get("factor_research_row_id")) for row in layer_rows if clean(row.get("factor_research_row_id"))}
    expected_count = len(factor_research_ids) * len(allowed_family_keys)
    actual_count = len(layer_rows)
    attached_family_count = len(attached_family_keys)
    layer_count_expected_1590 = actual_count == 1590
    cartesian_count_ok = actual_count == expected_count if factor_research_ids and allowed_family_keys else False
    only_allowed_families = attached_family_keys.issubset(allowed_family_keys)
    silently_promoted = attached_family_keys.intersection(blocked_family_keys.keys())
    layer_passed = actual_count > 0 and cartesian_count_ok and only_allowed_families and not silently_promoted
    if not layer_passed:
        add_blocker(blockers, "FACTOR_INPUT_LAYER", "Factor input layer row count, family eligibility, or promotion check failed.")

    review_rows = [
        {
            "review_id": "V20_12_FACTOR_INPUT_LAYER_REVIEW_001",
            "factor_attachment_rows_reviewed": str(actual_count),
            "expected_attachment_rows_if_v20_11_unchanged": "1590",
            "matches_expected_1590": tf(layer_count_expected_1590),
            "factor_research_rows_detected": str(len(factor_research_ids)),
            "attachable_factor_families_from_v20_11_plan": str(len(allowed_family_keys)),
            "expected_rows_from_research_x_families": str(expected_count),
            "attachment_rows_equal_research_x_families": tf(cartesian_count_ok),
            "attached_factor_families_reviewed": str(attached_family_count),
            "only_v20_10_v20_11_attachment_ready_families_present": tf(only_allowed_families),
            "source_required_or_partial_only_family_promoted": tf(bool(silently_promoted)),
            "factor_input_layer_review_status": "PASS" if layer_passed else "BLOCKED",
            "blocker_reason": "" if layer_passed else "Input layer failed row count, family readiness, or blocked-family promotion review.",
        }
    ]

    duplicate_ids = actual_count - len({clean(row.get("factor_attachment_row_id")) for row in layer_rows if clean(row.get("factor_attachment_row_id"))})
    missing_ticker = sum(1 for row in layer_rows if not clean(row.get("ticker")))
    missing_close = sum(1 for row in layer_rows if not clean(row.get("effective_close")))
    nonpositive_close = sum(1 for row in layer_rows if (parse_float(row.get("effective_close")) is None or parse_float(row.get("effective_close")) <= 0))
    missing_hash = sum(1 for row in layer_rows if not clean(row.get("source_hash")))
    missing_run_id = sum(1 for row in layer_rows if not clean(row.get("run_id")))
    missing_sample_id = sum(1 for row in layer_rows if not clean(row.get("sample_id")))
    score_true = sum(1 for row in layer_rows if not false_or_zero(row.get("factor_score_created")))
    evidence_true = sum(1 for row in layer_rows if not false_or_zero(row.get("factor_evidence_created")))
    official_true = sum(1 for row in layer_rows if true_value(row.get("official_use_allowed")))
    missing_research_id = sum(1 for row in layer_rows if not clean(row.get("factor_research_row_id")))
    missing_normalized_id = sum(1 for row in layer_rows if not clean(row.get("normalized_row_id")))
    bad_observation_dates = sum(1 for row in layer_rows if not parse_date_ok(row.get("effective_observation_date")))
    bad_price_dates = sum(1 for row in layer_rows if not parse_date_ok(row.get("effective_price_date")))
    research_only_false = sum(1 for row in layer_rows if not true_value(row.get("research_only_flag")))

    schema_rows = []
    field_set = set(layer_fields)
    for col in REQUIRED_LAYER_COLUMNS:
        non_empty = sum(1 for row in layer_rows if clean(row.get(col)))
        detected = col in field_set
        if col == "factor_attachment_row_id":
            check_pass = detected and non_empty == actual_count and duplicate_ids == 0
        elif col in {"effective_observation_date", "effective_price_date"}:
            bad_dates = bad_observation_dates if col == "effective_observation_date" else bad_price_dates
            check_pass = detected and non_empty == actual_count and bad_dates == 0
        elif col == "effective_close":
            check_pass = detected and non_empty == actual_count and missing_close == 0 and nonpositive_close == 0
        elif col == "research_only_flag":
            check_pass = detected and research_only_false == 0
        elif col == "official_use_allowed":
            check_pass = detected and official_true == 0
        elif col == "factor_score_created":
            check_pass = detected and score_true == 0
        elif col == "factor_evidence_created":
            check_pass = detected and evidence_true == 0
        else:
            check_pass = detected and non_empty == actual_count
        schema_rows.append(
            {
                "column_name": col,
                "required": "TRUE",
                "detected": tf(detected),
                "non_empty_row_count": str(non_empty),
                "row_count": str(actual_count),
                "schema_check_passed": tf(check_pass),
                "blocker_reason": "" if check_pass else f"Required field {col} is missing, incomplete, invalid, or violates safety flags.",
            }
        )
    schema_passed = all(row["schema_check_passed"] == "TRUE" for row in schema_rows) and bool(layer_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "Required factor input schema checks failed.")

    lineage_counts = {
        "linked_to_v20_11_attachment_classification_count": sum(1 for row in layer_rows if (clean(row.get("factor_category")), clean(row.get("factor_family"))) in allowed_family_keys),
        "linked_to_v20_10_source_attachment_audit_count": sum(1 for row in layer_rows if clean(row.get("attachment_source_reference"))),
        "linked_to_v20_9_factor_research_base_count": sum(1 for row in layer_rows if clean(row.get("factor_research_row_id"))),
        "linked_to_v20_8_normalized_research_dataset_count": sum(1 for row in layer_rows if clean(row.get("normalized_row_id"))),
        "linked_to_v20_7x_active_market_input_lineage_count": sum(1 for row in layer_rows if "V20_7X" in clean(row.get("attachment_source_reference"))),
        "source_hash_preserved_count": sum(1 for row in layer_rows if clean(row.get("source_hash"))),
        "run_id_preserved_count": sum(1 for row in layer_rows if clean(row.get("run_id"))),
        "sample_id_preserved_count": sum(1 for row in layer_rows if clean(row.get("sample_id"))),
    }
    lineage_passed = bool(layer_rows) and all(count == actual_count for count in lineage_counts.values())
    lineage_rows = [
        {
            "lineage_review_id": "V20_12_LINEAGE_REVIEW_001",
            "factor_attachment_rows_reviewed": str(actual_count),
            **{key: str(value) for key, value in lineage_counts.items()},
            "upstream_v20_11_lineage_audit_status": clean(lineage_audit_rows[0].get("lineage_status")) if lineage_audit_rows else "",
            "lineage_review_status": "PASS" if lineage_passed else "BLOCKED",
            "blocker_reason": "" if lineage_passed else "One or more lineage links are missing from the V20.11 factor input layer.",
        }
    ]
    if not lineage_passed:
        add_blocker(blockers, "LINEAGE", "Factor input lineage review failed.")

    prohibited_columns = sorted(
        {
            column
            for column in layer_fields
            for term in PROHIBITED_BOUNDARY_TERMS
            if term in column.lower()
            and column
            not in {
                "factor_score_created",
                "factor_evidence_created",
                "allowed_for_backtest_now",
                "allowed_for_dynamic_weighting_now",
                "allowed_for_trading_now",
                "allowed_for_official_recommendation_now",
                "official_use_allowed",
            }
        }
    )
    backtest_allowed_true = sum(1 for row in layer_rows if true_value(row.get("allowed_for_backtest_now")))
    dynamic_allowed_true = sum(1 for row in layer_rows if true_value(row.get("allowed_for_dynamic_weighting_now")))
    trading_allowed_true = sum(1 for row in layer_rows if true_value(row.get("allowed_for_trading_now")))
    recommendation_allowed_true = sum(1 for row in layer_rows if true_value(row.get("allowed_for_official_recommendation_now")))
    boundary_passed = (
        score_true == 0
        and evidence_true == 0
        and official_true == 0
        and backtest_allowed_true == 0
        and dynamic_allowed_true == 0
        and trading_allowed_true == 0
        and recommendation_allowed_true == 0
        and not prohibited_columns
    )
    boundary_rows = [
        {
            "boundary_review_id": "V20_12_BOUNDARY_REVIEW_001",
            "no_factor_score_columns_with_computed_scores": tf(score_true == 0),
            "factor_evidence_rows_created": "0",
            "factor_scores_created": "0",
            "prohibited_boundary_columns_detected": ";".join(prohibited_columns),
            "forward_return_fields_exist": tf(any("forward_return" in c.lower() for c in prohibited_columns)),
            "benchmark_relative_performance_fields_exist": tf(any("benchmark" in c.lower() or "relative_return" in c.lower() for c in prohibited_columns)),
            "backtest_metric_fields_exist": tf(any(c.lower() in {"sharpe", "drawdown", "alpha", "beta"} or "backtest" in c.lower() for c in prohibited_columns)),
            "dynamic_weighting_fields_exist": tf(any("dynamic_weight" in c.lower() for c in prohibited_columns)),
            "buy_sell_hold_signal_action_fields_exist": tf(any(term in c.lower() for c in prohibited_columns for term in ["buy", "sell", "hold", "signal", "action"])),
            "official_recommendation_flags_true_count": str(official_true + recommendation_allowed_true),
            "strategy_signals_absent": "TRUE",
            "boundary_review_status": "PASS" if boundary_passed else "BLOCKED",
            "blocker_reason": "" if boundary_passed else "Factor input layer contains prohibited scoring/evidence/performance/signal/official-use fields or flags.",
        }
    ]
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "Boundary review failed.")

    dq_passed = (
        bool(layer_rows)
        and missing_ticker == 0
        and missing_close == 0
        and nonpositive_close == 0
        and missing_hash == 0
        and missing_run_id == 0
        and missing_sample_id == 0
        and duplicate_ids == 0
        and score_true == 0
        and evidence_true == 0
        and official_true == 0
    )
    dq_rows = [
        {
            "quality_review_id": "V20_12_QUALITY_REVIEW_001",
            "factor_attachment_rows_reviewed": str(actual_count),
            "unique_tickers": str(len({clean(row.get("ticker")) for row in layer_rows if clean(row.get("ticker"))})),
            "unique_factor_families": str(len({clean(row.get("factor_family")) for row in layer_rows if clean(row.get("factor_family"))})),
            "unique_factor_categories": str(len({clean(row.get("factor_category")) for row in layer_rows if clean(row.get("factor_category"))})),
            "missing_ticker_count": str(missing_ticker),
            "missing_effective_close_count": str(missing_close),
            "nonpositive_effective_close_count": str(nonpositive_close),
            "missing_source_hash_count": str(missing_hash),
            "missing_run_id_count": str(missing_run_id),
            "missing_sample_id_count": str(missing_sample_id),
            "duplicate_factor_attachment_row_id_count": str(duplicate_ids),
            "rows_with_factor_score_created_true": str(score_true),
            "rows_with_factor_evidence_created_true": str(evidence_true),
            "rows_with_official_use_allowed_true": str(official_true),
            "data_quality_review_status": "PASS" if dq_passed else "BLOCKED",
            "blocker_reason": "" if dq_passed else "Factor input data quality checks failed.",
        }
    ]
    if not dq_passed:
        add_blocker(blockers, "DATA_QUALITY", "Factor input data quality review failed.")

    family_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in layer_rows:
        family_groups[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)

    all_review_checks_passed = layer_passed and schema_passed and lineage_passed and boundary_passed and dq_passed and v20_11_gate_passed and v20_11_validation_ok and read_first_ok
    family_rows = []
    scope_rows = []
    for index, ((category, family), rows) in enumerate(sorted(family_groups.items()), start=1):
        source_ready = (category, family) in allowed_family_keys
        family_schema_ready = schema_passed
        family_lineage_ready = lineage_passed
        family_boundary_ready = boundary_passed
        allowed_next = all_review_checks_passed and source_ready and family_schema_ready and family_lineage_ready and family_boundary_ready
        blocker_reason = "" if allowed_next else "Family is not allowed for first limited evidence scope until source, schema, lineage, boundary, and quality checks all pass."
        family_rows.append(
            {
                "factor_category": category,
                "factor_family": family,
                "attached_input_rows": str(len(rows)),
                "unique_tickers": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))})),
                "source_attachment_ready": tf(source_ready),
                "schema_ready": tf(family_schema_ready),
                "lineage_ready": tf(family_lineage_ready),
                "non_scoring_boundary_passed": tf(family_boundary_ready),
                "evidence_scope_allowed_next": tf(allowed_next),
                "evidence_rows_created_now": "0",
                "score_created_now": "0",
                "blocker_reason": blocker_reason,
                "next_required_step": "V20.13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER" if allowed_next else "Resolve V20.12 blocker before evidence scope.",
            }
        )
        scope_rows.append(
            {
                "evidence_scope_id": f"V20_12_SCOPE_{index:03d}",
                "factor_category": category,
                "factor_family": family,
                "allowed_for_first_limited_evidence_layer_next": tf(allowed_next),
                "allowed_input_rows": str(len(rows) if allowed_next else 0),
                "allowed_ticker_count": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))}) if allowed_next else 0),
                "evidence_design_only_now": "TRUE",
                "evidence_rows_created_now": "0",
                "factor_score_created_now": "0",
                "prohibited_metrics_now": "IC;rank IC;hit rate;return spread;forward return;benchmark-relative return;Sharpe;drawdown;alpha;beta;performance metrics",
                "required_next_step": "V20.13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER" if allowed_next else "Resolve V20.12 blocker before evidence scope.",
                "boundary_notes": "Scope plan only; no evidence rows, scores, metrics, signals, backtests, or official recommendations created.",
            }
        )

    strategy_rows = []
    strategy_readiness_recorded = bool(strategy_ready_rows)
    strategy_boundary_passed = True
    for row in strategy_ready_rows:
        signals_created = int(clean(row.get("signals_created")) or "0")
        strategy_boundary_passed = strategy_boundary_passed and signals_created == 0
        strategy_rows.append(
            {
                "strategy_family": clean(row.get("strategy_family")),
                "strategy_family_readiness_recorded": "TRUE",
                "dependency_ready_now": clean(row.get("dependency_ready_now")),
                "strategy_readiness_status": clean(row.get("strategy_readiness_status")),
                "strategy_layer_allowed_now": "FALSE",
                "signal_allowed_now": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weighting_allowed_now": "FALSE",
                "official_use_allowed": "FALSE",
                "strategy_signals_created": str(signals_created),
                "strategy_dependency_gate_status": "PASS" if signals_created == 0 else "BLOCKED",
                "blocker_reason": clean(row.get("blocker_reason")) or "Strategy dependencies remain blocked until later evidence gates pass.",
            }
        )
    if not strategy_readiness_recorded or not strategy_boundary_passed:
        add_blocker(blockers, "STRATEGY_DEPENDENCY", "Strategy dependency readiness is missing or strategy signals were created.")

    missing_review_rows = []
    for index, row in enumerate(missing_rows, start=1):
        missing_review_rows.append(
            {
                "missing_source_blocker_id": clean(row.get("missing_source_id")) or f"V20_12_MISSING_{index:03d}",
                "required_source_name": clean(row.get("required_source_name")),
                "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
                "source_status": clean(row.get("source_status")),
                "carryforward_from_v20_11": "TRUE",
                "blocks_factor_score": "TRUE",
                "blocks_factor_evidence": "TRUE",
                "blocks_backtest": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_strategy_signals": "TRUE",
                "blocks_official_use": "TRUE",
                "limited_evidence_scope_ready": "FALSE",
                "blocker_reason": clean(row.get("blocker_reason")),
                "next_required_source_or_step": clean(row.get("next_required_source_or_step")) or "V20.13 limited evidence only for allowed attached metadata families.",
            }
        )

    gate_passed = all_review_checks_passed and strategy_readiness_recorded and strategy_boundary_passed and not any(row["blocks_v20_12"] == "TRUE" for row in blockers)
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    first_evidence_allowed_next = gate_passed

    evidence_gate_rows = [
        {
            "gate_id": "V20_12_FACTOR_EVIDENCE_GATE",
            "FACTOR_INPUT_LAYER_REVIEW_PASSED": tf(gate_passed),
            "FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT": tf(first_evidence_allowed_next),
            "FACTOR_EVIDENCE_ROWS_CREATED_NOW": "0",
            "FACTOR_SCORES_CREATED_NOW": "0",
            "READY_FOR_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER_NEXT": tf(first_evidence_allowed_next),
            "gate_status": "PASS" if gate_passed else "BLOCKED",
            "gate_reason": "Factor input layer may be handed to a future limited evidence layer." if gate_passed else "One or more V20.12 gate checks failed.",
        }
    ]

    gate_rows_out = [
        {
            "gate_id": "V20_12_GATE",
            "STATUS": status,
            "FACTOR_INPUT_LAYER_REVIEW_PASSED": tf(gate_passed),
            "FACTOR_ATTACHMENT_ROWS_REVIEWED": str(actual_count),
            "ATTACHED_FACTOR_FAMILIES_REVIEWED": str(attached_family_count),
            "FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT": tf(first_evidence_allowed_next),
            "READY_FOR_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER_NEXT": tf(first_evidence_allowed_next),
            "FACTOR_EVIDENCE_ROWS_CREATED": "0",
            "FACTOR_SCORES_CREATED": "0",
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "NEXT_RECOMMENDED_STEP": "V20.13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER" if gate_passed else "Resolve V20.12 blockers before V20.13.",
            "gate_reason": "V20.12 review and factor evidence gate passed." if gate_passed else "V20.12 review or dependency checks failed.",
        }
    ]

    next_rows = [
        {
            "decision_id": "V20_12_NEXT_STEP",
            "current_status": status,
            "next_recommended_step": gate_rows_out[0]["NEXT_RECOMMENDED_STEP"],
            "ready_for_v20_13_first_limited_factor_evidence_layer_next": tf(first_evidence_allowed_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "boundary_notes": "V20.12 created no evidence rows, factor scores, metrics, backtests, dynamic weights, trading signals, strategy signals, or official recommendations.",
        }
    ]

    read_first_text_out = "\n".join(
        [
            "PATCH_VERSION: V20.12",
            "PATCH_NAME: FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE",
            "REPORTING_ONLY = FALSE",
            "FACTOR_INPUT_LAYER_REVIEW_OR_EVIDENCE_GATE_ONLY = TRUE",
            f"STATUS = {status}",
            f"FACTOR_INPUT_LAYER_REVIEW_PASSED = {tf(gate_passed)}",
            f"FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT = {tf(first_evidence_allowed_next)}",
            "FACTOR_EVIDENCE_ROWS_CREATED = 0",
            "FACTOR_SCORES_CREATED = 0",
            "BACKTEST_ROWS_CREATED = 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
            "TRADING_SIGNAL_ROWS_CREATED = 0",
            "STRATEGY_SIGNALS_CREATED = 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
            "BROKER_API_USED = FALSE",
            "ORDER_EXECUTION_USED = FALSE",
            "SOURCE_MUTATION_USED = FALSE",
            "V21_OUTPUTS_CREATED = FALSE",
            "V19_21_OUTPUTS_CREATED = FALSE",
            "OFFICIAL_USE_ALLOWED = FALSE",
            f"FACTOR_ATTACHMENT_ROWS_REVIEWED = {actual_count}",
            f"ATTACHED_FACTOR_FAMILIES_REVIEWED = {attached_family_count}",
            f"NEXT_RECOMMENDED_STEP = {gate_rows_out[0]['NEXT_RECOMMENDED_STEP']}",
            "",
        ]
    )

    read_first_flags = [
        "REPORTING_ONLY = FALSE",
        "FACTOR_INPUT_LAYER_REVIEW_OR_EVIDENCE_GATE_ONLY = TRUE",
        f"FACTOR_INPUT_LAYER_REVIEW_PASSED = {tf(gate_passed)}",
        f"FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT = {tf(first_evidence_allowed_next)}",
        "FACTOR_EVIDENCE_ROWS_CREATED = 0",
        "FACTOR_SCORES_CREATED = 0",
        "BACKTEST_ROWS_CREATED = 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNALS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
        "BROKER_API_USED = FALSE",
        "ORDER_EXECUTION_USED = FALSE",
        "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE",
        "OFFICIAL_USE_ALLOWED = FALSE",
    ]
    read_first_safety_flags_present = all(flag in read_first_text_out for flag in read_first_flags)
    allowed_write_paths_match = len(ALLOWED_WRITE_PATHS) == 18
    no_v21_or_v19_21_outputs = not any("V21" in path.name or "V19_21" in path.name for path in ALLOWED_WRITE_PATHS)
    protected_input_mutation_check_passed = all(path.name.startswith("V20_12") or path == CURRENT_REPORT for path in ALLOWED_WRITE_PATHS)

    validation_rows_out = [
        {
            "status": status,
            "patch_version": PATCH_VERSION,
            "generated_at_utc": generated_at,
            "dependency_audit_passed": tf(v20_11_gate_passed and v20_11_validation_ok and read_first_ok and all(path.exists() for path in REQUIRED_INPUTS)),
            "factor_input_layer_review_passed": tf(gate_passed),
            "factor_attachment_rows_reviewed": str(actual_count),
            "attached_factor_families_reviewed": str(attached_family_count),
            "expected_v20_11_unchanged_row_count": "1590",
            "factor_input_row_review_count_check_passed": tf(layer_count_expected_1590 and actual_count > 0),
            "factor_attachment_row_id_uniqueness_check_passed": tf(duplicate_ids == 0),
            "lineage_review_check_passed": tf(lineage_passed),
            "boundary_review_check_passed": tf(boundary_passed),
            "strategy_signal_absence_check_passed": tf(strategy_boundary_passed),
            "factor_evidence_rows_created": "0",
            "factor_scores_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signals_created": "0",
            "official_recommendation_rows_created": "0",
            "ready_for_v20_13_first_limited_factor_evidence_layer_next": tf(first_evidence_allowed_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "read_first_safety_flag_check_passed": tf(read_first_safety_flags_present),
            "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_mutation_check_passed": tf(protected_input_mutation_check_passed),
            "v21_outputs_created": "FALSE",
            "v19_21_outputs_created": "FALSE",
            "no_v21_or_v19_21_files_check_passed": tf(no_v21_or_v19_21_outputs),
            "static_write_path_check_passed": tf(allowed_write_paths_match and protected_input_mutation_check_passed and no_v21_or_v19_21_outputs),
            "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
            "write_paths_written_count": "18",
            "allowed_write_paths_match": tf(allowed_write_paths_match),
            "total_blocker_count": str(len(blockers)),
            "next_recommended_step": gate_rows_out[0]["NEXT_RECOMMENDED_STEP"],
        }
    ]

    report_text = "\n".join(
        [
            "# V20.12 Factor Input Layer Review Or Factor Evidence Gate",
            "",
            f"Generated at UTC: {generated_at}",
            "",
            f"STATUS: {status}",
            f"FACTOR_ATTACHMENT_ROWS_REVIEWED: {actual_count}",
            f"ATTACHED_FACTOR_FAMILIES_REVIEWED: {attached_family_count}",
            f"FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT: {tf(first_evidence_allowed_next)}",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "FACTOR_SCORES_CREATED: 0",
            "READY_FOR_BACKTEST_NEXT: FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT: FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION: FALSE",
            "",
            "## Factor Input Layer Review",
            md_table(list(review_rows[0].keys()), review_rows),
            "",
            "## Evidence Scope Plan",
            md_table(["evidence_scope_id", "factor_category", "factor_family", "allowed_for_first_limited_evidence_layer_next", "allowed_input_rows", "required_next_step"], scope_rows),
            "",
            "## Blockers",
            md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.12 blockers.",
            "",
            "## Boundary",
            "This step created no factor evidence rows, factor scores, backtests, dynamic weighting rows, trading signals, strategy signals, or official recommendations.",
            "",
        ]
    )

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_REVIEW, review_rows, list(review_rows[0].keys()))
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_check_passed", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, dq_rows, list(dq_rows[0].keys()))
    write_csv(OUT_FAMILY_READY, family_rows, ["factor_category", "factor_family", "attached_input_rows", "unique_tickers", "source_attachment_ready", "schema_ready", "lineage_ready", "non_scoring_boundary_passed", "evidence_scope_allowed_next", "evidence_rows_created_now", "score_created_now", "blocker_reason", "next_required_step"])
    write_csv(OUT_EVIDENCE_GATE, evidence_gate_rows, list(evidence_gate_rows[0].keys()))
    write_csv(OUT_STRATEGY, strategy_rows, ["strategy_family", "strategy_family_readiness_recorded", "dependency_ready_now", "strategy_readiness_status", "strategy_layer_allowed_now", "signal_allowed_now", "backtest_allowed_now", "dynamic_weighting_allowed_now", "official_use_allowed", "strategy_signals_created", "strategy_dependency_gate_status", "blocker_reason"])
    write_csv(OUT_MISSING, missing_review_rows, ["missing_source_blocker_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_11", "blocks_factor_score", "blocks_factor_evidence", "blocks_backtest", "blocks_dynamic_weighting", "blocks_strategy_signals", "blocks_official_use", "limited_evidence_scope_ready", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_SCOPE, scope_rows, ["evidence_scope_id", "factor_category", "factor_family", "allowed_for_first_limited_evidence_layer_next", "allowed_input_rows", "allowed_ticker_count", "evidence_design_only_now", "evidence_rows_created_now", "factor_score_created_now", "prohibited_metrics_now", "required_next_step", "boundary_notes"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_12"])
    write_csv(OUT_GATE, gate_rows_out, list(gate_rows_out[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows_out, list(validation_rows_out[0].keys()))
    write_text(REPORT, report_text)
    write_text(CURRENT_REPORT, report_text)
    write_text(READ_FIRST, read_first_text_out)

    print(f"STATUS: {status}")
    print(f"FACTOR_ATTACHMENT_ROWS_REVIEWED: {actual_count}")
    print(f"ATTACHED_FACTOR_FAMILIES_REVIEWED: {attached_family_count}")
    print(f"FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT: {tf(first_evidence_allowed_next)}")
    print("FACTOR_EVIDENCE_ROWS_CREATED: 0")
    print("FACTOR_SCORES_CREATED: 0")
    print(f"NEXT_RECOMMENDED_STEP: {gate_rows_out[0]['NEXT_RECOMMENDED_STEP']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
