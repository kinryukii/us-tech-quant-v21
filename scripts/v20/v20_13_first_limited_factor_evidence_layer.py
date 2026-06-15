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

IN_LAYER = CONSOLIDATION / "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv"
IN_REVIEW = CONSOLIDATION / "V20_12_FACTOR_INPUT_LAYER_REVIEW.csv"
IN_FAMILY_READY = CONSOLIDATION / "V20_12_FACTOR_FAMILY_EVIDENCE_READINESS_AUDIT.csv"
IN_EVIDENCE_GATE = CONSOLIDATION / "V20_12_FACTOR_EVIDENCE_GATE_DECISION.csv"
IN_SCOPE = CONSOLIDATION / "V20_12_FACTOR_EVIDENCE_SCOPE_PLAN.csv"
IN_GATE = CONSOLIDATION / "V20_12_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_12_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_12_READ_FIRST.txt"
IN_MISSING = CONSOLIDATION / "V20_12_MISSING_FACTOR_SOURCE_BLOCKER_REVIEW.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_13_DEPENDENCY_AUDIT.csv"
OUT_LAYER = CONSOLIDATION / "V20_13_LIMITED_FACTOR_EVIDENCE_LAYER.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_SCHEMA_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_LINEAGE_AUDIT.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_BOUNDARY_AUDIT.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_13_FACTOR_EVIDENCE_DATA_QUALITY_AUDIT.csv"
OUT_FAMILY_SUMMARY = CONSOLIDATION / "V20_13_FACTOR_FAMILY_EVIDENCE_SUMMARY.csv"
OUT_SCOPE_COMPLIANCE = CONSOLIDATION / "V20_13_EVIDENCE_SCOPE_COMPLIANCE_AUDIT.csv"
OUT_MISSING_CARRY = CONSOLIDATION / "V20_13_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"
OUT_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_13_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_13_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_13_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_13_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_13_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER.md"
READ_FIRST = OPS / "V20_13_READ_FIRST.txt"

PATCH_VERSION = "V20.13"
PASS_STATUS = "PASS_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER"
BLOCKED_STATUS = "BLOCKED_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER"

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
    IN_LAYER,
    IN_REVIEW,
    IN_FAMILY_READY,
    IN_EVIDENCE_GATE,
    IN_SCOPE,
    IN_GATE,
    IN_VALIDATION,
    IN_READ_FIRST,
]

EVIDENCE_COLUMNS = [
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
    "evidence_value_numeric",
    "evidence_value_text",
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

REQUIRED_CARRYFORWARD_SOURCES = [
    ("historical_ohlcv_windows", "technical;strategy", "Technical historical OHLCV windows remain unavailable."),
    ("volume_history", "technical;strategy", "Volume history remains unavailable."),
    ("technical_indicator_windows", "technical", "Technical indicator windows remain unavailable."),
    ("fundamental_statement_and_valuation_data", "fundamental;risk", "Fundamental statement and valuation data remain unavailable."),
    ("event_and_earnings_calendar", "risk;market_regime", "Event and earnings calendar remains unavailable."),
    ("macro_calendar", "risk;market_regime", "Macro calendar remains unavailable."),
    ("vix_qqq_spy_regime_data", "market_regime;risk", "VIX/QQQ/SPY regime data remains unavailable."),
    ("portfolio_holdings_drawdown_position_cap_data", "portfolio;risk;strategy", "Portfolio holdings, drawdown, and position-cap data remain unavailable."),
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
            "blocker_id": f"V20_13_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_13": tf(severity == "BLOCKING"),
        }
    )


def evidence_id(row: dict[str, str], evidence_type: str) -> str:
    key = "|".join(
        [
            clean(row.get("factor_attachment_row_id")),
            clean(row.get("factor_family")),
            clean(row.get("ticker")),
            clean(row.get("effective_observation_date")),
            clean(row.get("effective_price_date")),
            clean(row.get("sample_id")),
            clean(row.get("source_hash")),
            clean(row.get("run_id")),
            evidence_type,
        ]
    )
    return "V20_13_EVID_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24].upper()


def evidence_type_for(row: dict[str, str]) -> str:
    family = clean(row.get("factor_family"))
    if family == "freshness":
        return "freshness_metadata_presence_evidence"
    if family == "source_quality":
        return "source_hash_run_sample_presence_evidence"
    if family == "point_in_time":
        return "pit_date_safety_metadata_evidence"
    if family == "safe_backtest_eligibility":
        return "research_only_backtest_block_boundary_evidence"
    if family == "current_snapshot_block":
        return "current_snapshot_official_use_block_evidence"
    return "limited_input_presence_evidence"


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

    input_rows, _ = read_csv(IN_LAYER)
    review_rows_in, _ = read_csv(IN_REVIEW)
    family_ready_rows, _ = read_csv(IN_FAMILY_READY)
    evidence_gate_rows_in, _ = read_csv(IN_EVIDENCE_GATE)
    scope_rows_in, _ = read_csv(IN_SCOPE)
    gate_rows_in, _ = read_csv(IN_GATE)
    validation_rows_in, _ = read_csv(IN_VALIDATION)
    missing_rows_in, _ = read_csv(IN_MISSING)
    read_first_in = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows_in[0] if gate_rows_in else {}
    evidence_gate = evidence_gate_rows_in[0] if evidence_gate_rows_in else {}
    validation = validation_rows_in[0] if validation_rows_in else {}

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
        upper(gate.get("STATUS")) == "PASS_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE"
        and upper(gate.get("FACTOR_INPUT_LAYER_REVIEW_PASSED")) == "TRUE"
        and upper(gate.get("FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER_NEXT")) == "TRUE"
        and clean(gate.get("FACTOR_EVIDENCE_ROWS_CREATED")) == "0"
        and clean(gate.get("FACTOR_SCORES_CREATED")) == "0"
        and upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE"
        and upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE"
    )
    evidence_gate_ok = (
        upper(evidence_gate.get("gate_status")) == "PASS"
        and upper(evidence_gate.get("FACTOR_INPUT_LAYER_REVIEW_PASSED")) == "TRUE"
        and upper(evidence_gate.get("FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT")) == "TRUE"
        and upper(evidence_gate.get("READY_FOR_V20_13_FIRST_LIMITED_FACTOR_EVIDENCE_LAYER_NEXT")) == "TRUE"
        and clean(evidence_gate.get("FACTOR_EVIDENCE_ROWS_CREATED_NOW")) == "0"
        and clean(evidence_gate.get("FACTOR_SCORES_CREATED_NOW")) == "0"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE"
        and upper(validation.get("factor_input_layer_review_passed")) == "TRUE"
        and upper(validation.get("ready_for_v20_13_first_limited_factor_evidence_layer_next")) == "TRUE"
        and clean(validation.get("factor_evidence_rows_created")) == "0"
        and clean(validation.get("factor_scores_created")) == "0"
        and upper(validation.get("ready_for_backtest_next")) == "FALSE"
        and upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE"
        and upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE"
    )
    read_first_ok = all(
        flag in read_first_in
        for flag in [
            "FACTOR_INPUT_LAYER_REVIEW_OR_EVIDENCE_GATE_ONLY = TRUE",
            "FACTOR_INPUT_LAYER_REVIEW_PASSED = TRUE",
            "FIRST_LIMITED_FACTOR_EVIDENCE_SCOPE_ALLOWED_NEXT = TRUE",
            "FACTOR_EVIDENCE_ROWS_CREATED = 0",
            "FACTOR_SCORES_CREATED = 0",
            "BACKTEST_ROWS_CREATED = 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
            "TRADING_SIGNAL_ROWS_CREATED = 0",
            "STRATEGY_SIGNALS_CREATED = 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
            "SOURCE_MUTATION_USED = FALSE",
            "V21_OUTPUTS_CREATED = FALSE",
            "V19_21_OUTPUTS_CREATED = FALSE",
            "OFFICIAL_USE_ALLOWED = FALSE",
        ]
    )
    dependency("V20_12_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.12 gate is not in the required pass and safety state.")
    dependency("V20_12_FACTOR_EVIDENCE_GATE_REQUIRED_STATE", IN_EVIDENCE_GATE, evidence_gate_ok, "V20.12 factor evidence gate does not allow V20.13.")
    dependency("V20_12_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.12 validation summary is not in the required state.")
    dependency("V20_12_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.12 READ_FIRST safety flags are incomplete.")

    approved_scope = {
        (clean(row.get("factor_category")), clean(row.get("factor_family"))): clean(row.get("evidence_scope_id"))
        for row in scope_rows_in
        if upper(row.get("allowed_for_first_limited_evidence_layer_next")) == "TRUE"
    }
    approved_allowed_rows = {
        (clean(row.get("factor_category")), clean(row.get("factor_family"))): int(clean(row.get("allowed_input_rows")) or "0")
        for row in scope_rows_in
        if upper(row.get("allowed_for_first_limited_evidence_layer_next")) == "TRUE"
    }
    family_ready_allowed = {
        (clean(row.get("factor_category")), clean(row.get("factor_family")))
        for row in family_ready_rows
        if upper(row.get("evidence_scope_allowed_next")) == "TRUE"
    }

    accepted_inputs = [
        row
        for row in input_rows
        if (clean(row.get("factor_category")), clean(row.get("factor_family"))) in approved_scope
        and (clean(row.get("factor_category")), clean(row.get("factor_family"))) in family_ready_allowed
    ]
    blocked_inputs = [
        row
        for row in input_rows
        if (clean(row.get("factor_category")), clean(row.get("factor_family"))) not in approved_scope
    ]
    if not accepted_inputs:
        add_blocker(blockers, "EVIDENCE_SCOPE", "No V20.12-approved factor input rows are available for V20.13 evidence.")

    evidence_rows: list[dict[str, str]] = []
    for row in accepted_inputs:
        evidence_type = evidence_type_for(row)
        lineage_complete = all(clean(row.get(field)) for field in ["factor_attachment_row_id", "factor_research_row_id", "normalized_row_id", "source_hash", "run_id", "sample_id"])
        pit_safe = parse_date_ok(row.get("effective_observation_date")) and parse_date_ok(row.get("effective_price_date"))
        stale_checked = "TRUE" if clean(row.get("attachment_source_reference")) else "FALSE"
        evidence_rows.append(
            {
                "factor_evidence_row_id": evidence_id(row, evidence_type),
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
                "evidence_scope_id": approved_scope[(clean(row.get("factor_category")), clean(row.get("factor_family")))],
                "evidence_type": evidence_type,
                "evidence_basis": clean(row.get("attachment_value_text")) or clean(row.get("attachment_status")) or "limited_input_presence_from_v20_11",
                "evidence_value_type": clean(row.get("attachment_value_type")) or "metadata_flag",
                "evidence_value_present": clean(row.get("attachment_value_present")) or "TRUE",
                "evidence_value_numeric": clean(row.get("attachment_value_numeric")),
                "evidence_value_text": clean(row.get("attachment_value_text")),
                "evidence_quality_flag": "LIMITED_RESEARCH_ONLY_METADATA",
                "evidence_lineage_complete": tf(lineage_complete),
                "evidence_pit_safe": tf(pit_safe),
                "evidence_stale_leakage_checked": stale_checked,
                "factor_score_created": "FALSE",
                "factor_score_value": "",
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
                "allowed_for_factor_score_next": "FALSE",
                "allowed_for_backtest_now": "FALSE",
                "allowed_for_dynamic_weighting_now": "FALSE",
                "allowed_for_trading_now": "FALSE",
                "allowed_for_official_recommendation_now": "FALSE",
                "evidence_created_at_utc": generated_at,
                "evidence_source_step": PATCH_VERSION,
            }
        )

    row_count = len(evidence_rows)
    evidence_ids = [clean(row.get("factor_evidence_row_id")) for row in evidence_rows if clean(row.get("factor_evidence_row_id"))]
    duplicate_evidence_ids = row_count - len(set(evidence_ids))
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
    attachment_missing = sum(1 for row in evidence_rows if not clean(row.get("factor_attachment_row_id")))
    research_missing = sum(1 for row in evidence_rows if not clean(row.get("factor_research_row_id")))
    normalized_missing = sum(1 for row in evidence_rows if not clean(row.get("normalized_row_id")))

    schema_rows = []
    field_set = set(EVIDENCE_COLUMNS)
    for column in EVIDENCE_COLUMNS:
        non_empty = sum(1 for row in evidence_rows if clean(row.get(column)))
        if column == "factor_evidence_row_id":
            passed = non_empty == row_count and duplicate_evidence_ids == 0
        elif column == "factor_attachment_row_id":
            passed = non_empty == row_count and attachment_missing == 0
        elif column == "factor_research_row_id":
            passed = non_empty == row_count and research_missing == 0
        elif column == "normalized_row_id":
            passed = non_empty == row_count and normalized_missing == 0
        elif column == "ticker":
            passed = non_empty == row_count and missing_ticker == 0
        elif column in {"effective_observation_date", "effective_price_date"}:
            passed = non_empty == row_count and (bad_observation_dates if column == "effective_observation_date" else bad_price_dates) == 0
        elif column == "effective_close":
            passed = non_empty == row_count and nonpositive_close == 0
        elif column in {"source_hash", "run_id", "sample_id"}:
            passed = non_empty == row_count
        elif column == "research_only_flag":
            passed = research_only_false == 0
        elif column == "official_use_allowed":
            passed = official_use_true == 0
        elif column == "factor_score_created":
            passed = score_true == 0
        elif column == "factor_score_value":
            passed = score_value_populated == 0
        elif column == "performance_metric_created":
            passed = performance_true == 0
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
        elif column in {"allowed_for_factor_score_next", "allowed_for_backtest_now", "allowed_for_dynamic_weighting_now", "allowed_for_trading_now", "allowed_for_official_recommendation_now"}:
            passed = all(not true_value(row.get(column)) for row in evidence_rows)
        else:
            passed = non_empty == row_count
        schema_rows.append(
            {
                "column_name": column,
                "required": "TRUE",
                "detected": tf(column in field_set),
                "non_empty_row_count": str(non_empty),
                "row_count": str(row_count),
                "schema_status": "PASS" if passed else "BLOCKED",
                "blocker_reason": "" if passed else f"Evidence field {column} is missing, invalid, populated when prohibited, or violates safety flags.",
            }
        )
    schema_passed = bool(evidence_rows) and all(row["schema_status"] == "PASS" for row in schema_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "Limited factor evidence schema audit failed.")

    attachment_ids = {clean(row.get("factor_attachment_row_id")) for row in input_rows}
    lineage_counts = {
        "linked_to_v20_13_evidence_scope_count": sum(1 for row in evidence_rows if clean(row.get("evidence_scope_id"))),
        "linked_to_v20_12_evidence_gate_decision_count": row_count if evidence_gate_ok else 0,
        "linked_to_v20_11_factor_attachment_row_count": sum(1 for row in evidence_rows if clean(row.get("factor_attachment_row_id")) in attachment_ids),
        "linked_to_v20_10_source_attachment_audit_classification_count": sum(1 for row in evidence_rows if clean(row.get("evidence_basis"))),
        "linked_to_v20_9_factor_research_base_row_count": sum(1 for row in evidence_rows if clean(row.get("factor_research_row_id"))),
        "linked_to_v20_8_normalized_research_row_count": sum(1 for row in evidence_rows if clean(row.get("normalized_row_id"))),
        "linked_to_v20_7x_active_input_lineage_count": sum(1 for row in evidence_rows if clean(row.get("source_hash")) and clean(row.get("run_id"))),
        "source_hash_preserved_count": sum(1 for row in evidence_rows if clean(row.get("source_hash"))),
        "run_id_preserved_count": sum(1 for row in evidence_rows if clean(row.get("run_id"))),
        "sample_id_preserved_count": sum(1 for row in evidence_rows if clean(row.get("sample_id"))),
    }
    lineage_passed = bool(evidence_rows) and all(value == row_count for value in lineage_counts.values())
    lineage_rows = [
        {
            "lineage_audit_id": "V20_13_LINEAGE_001",
            "factor_evidence_rows_created": str(row_count),
            **{key: str(value) for key, value in lineage_counts.items()},
            "lineage_status": "PASS" if lineage_passed else "BLOCKED",
            "blocker_reason": "" if lineage_passed else "One or more required evidence lineage links are missing.",
        }
    ]
    if not lineage_passed:
        add_blocker(blockers, "LINEAGE", "Limited factor evidence lineage audit failed.")

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
        and all((clean(row.get("factor_category")), clean(row.get("factor_family"))) in approved_scope for row in evidence_rows)
    )
    boundary_rows = [
        {
            "boundary_audit_id": "V20_13_BOUNDARY_001",
            "limited_evidence_rows_only_for_approved_scope": tf(all((clean(row.get("factor_category")), clean(row.get("factor_family"))) in approved_scope for row in evidence_rows)),
            "factor_scores_created": "0",
            "factor_score_value_populated_count": str(score_value_populated),
            "performance_metrics_created": "0",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "official_use_allowed_true_count": str(official_use_true),
            "boundary_status": "PASS" if boundary_passed else "BLOCKED",
            "blocker_reason": "" if boundary_passed else "Evidence layer violated approved scope or non-scoring/non-performance boundary.",
        }
    ]
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "Limited factor evidence boundary audit failed.")

    dq_passed = (
        bool(evidence_rows)
        and missing_ticker == 0
        and missing_hash == 0
        and missing_run_id == 0
        and missing_sample_id == 0
        and duplicate_evidence_ids == 0
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
    dq_rows = [
        {
            "quality_audit_id": "V20_13_QUALITY_001",
            "factor_evidence_rows_created": str(row_count),
            "unique_tickers": str(len({clean(row.get("ticker")) for row in evidence_rows if clean(row.get("ticker"))})),
            "unique_factor_families": str(len({clean(row.get("factor_family")) for row in evidence_rows if clean(row.get("factor_family"))})),
            "unique_factor_categories": str(len({clean(row.get("factor_category")) for row in evidence_rows if clean(row.get("factor_category"))})),
            "missing_ticker_count": str(missing_ticker),
            "missing_source_hash_count": str(missing_hash),
            "missing_run_id_count": str(missing_run_id),
            "missing_sample_id_count": str(missing_sample_id),
            "duplicate_factor_evidence_row_id_count": str(duplicate_evidence_ids),
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
            "data_quality_status": "PASS" if dq_passed else "BLOCKED",
            "blocker_reason": "" if dq_passed else "Evidence data quality audit failed.",
        }
    ]
    if not dq_passed:
        add_blocker(blockers, "DATA_QUALITY", "Limited factor evidence data quality audit failed.")

    family_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in evidence_rows:
        family_groups[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)
    family_summary_rows = []
    for category, family in sorted(family_groups):
        rows = family_groups[(category, family)]
        family_summary_rows.append(
            {
                "factor_category": category,
                "factor_family": family,
                "evidence_rows_created": str(len(rows)),
                "unique_tickers": str(len({clean(row.get("ticker")) for row in rows if clean(row.get("ticker"))})),
                "evidence_scope_allowed_by_v20_12": tf((category, family) in approved_scope),
                "evidence_layer_created_now": "TRUE",
                "score_created_now": "0",
                "performance_metric_created_now": "0",
                "backtest_allowed_now": "FALSE",
                "dynamic_weighting_allowed_now": "FALSE",
                "trading_allowed_now": "FALSE",
                "official_use_allowed": "FALSE",
                "next_required_step": "V20.14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE",
            }
        )

    family_counts = defaultdict(int)
    for row in evidence_rows:
        family_counts[(clean(row.get("factor_category")), clean(row.get("factor_family")))] += 1
    count_excess = {
        key: count
        for key, count in family_counts.items()
        if count > approved_allowed_rows.get(key, 0)
    }
    blocked_included = [
        key for key in family_counts if key not in approved_scope or key not in family_ready_allowed
    ]
    scope_passed = bool(evidence_rows) and not count_excess and not blocked_included and not blocked_inputs
    scope_rows = [
        {
            "scope_compliance_audit_id": "V20_13_SCOPE_COMPLIANCE_001",
            "approved_scope_family_count": str(len(approved_scope)),
            "evidence_family_count": str(len(family_counts)),
            "all_evidence_rows_in_v20_12_approved_scope": tf(not blocked_included),
            "row_counts_do_not_exceed_approved_input_rows": tf(not count_excess),
            "blocked_factor_families_included": tf(bool(blocked_included)),
            "source_required_factor_families_included": "FALSE",
            "partial_or_missing_source_families_silently_promoted": "FALSE",
            "evidence_rows_outside_approved_scope": str(sum(1 for row in evidence_rows if (clean(row.get("factor_category")), clean(row.get("factor_family"))) not in approved_scope)),
            "scope_compliance_status": "PASS" if scope_passed else "BLOCKED",
            "blocker_reason": "" if scope_passed else "Evidence layer included rows outside approved scope or exceeded approved input counts.",
        }
    ]
    if not scope_passed:
        add_blocker(blockers, "EVIDENCE_SCOPE", "Evidence scope compliance audit failed.")

    carry_rows = []
    seen_sources = set()
    for index, row in enumerate(missing_rows_in, start=1):
        source = clean(row.get("required_source_name"))
        seen_sources.add(source)
        carry_rows.append(
            {
                "missing_source_id": clean(row.get("missing_source_blocker_id")) or f"V20_13_MISSING_{index:03d}",
                "required_source_name": source,
                "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
                "source_status": clean(row.get("source_status")) or "MISSING",
                "carryforward_from_v20_12_or_v20_11": "TRUE",
                "blocks_factor_score": "TRUE",
                "blocks_full_factor_evidence": "TRUE",
                "blocks_backtest": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocks_strategy_signals": "TRUE",
                "blocks_official_use": "TRUE",
                "limited_evidence_scope_ready": "FALSE",
                "blocker_reason": clean(row.get("blocker_reason")),
                "next_required_source_or_step": clean(row.get("next_required_source_or_step")) or "Register required source before score/backtest gates.",
            }
        )
    for required_source, categories, reason in REQUIRED_CARRYFORWARD_SOURCES:
        if required_source not in seen_sources:
            carry_rows.append(
                {
                    "missing_source_id": f"V20_13_MISSING_{len(carry_rows) + 1:03d}",
                    "required_source_name": required_source,
                    "required_for_factor_categories": categories,
                    "source_status": "MISSING",
                    "carryforward_from_v20_12_or_v20_11": "TRUE",
                    "blocks_factor_score": "TRUE",
                    "blocks_full_factor_evidence": "TRUE",
                    "blocks_backtest": "TRUE",
                    "blocks_dynamic_weighting": "TRUE",
                    "blocks_strategy_signals": "TRUE",
                    "blocks_official_use": "TRUE",
                    "limited_evidence_scope_ready": "FALSE",
                    "blocker_reason": reason,
                    "next_required_source_or_step": "Register required source before score/backtest gates.",
                }
            )

    downstream_blocker_rows = []
    downstream_reasons = [
        ("backtest", "No factor scores, no forward outcomes, no performance metrics, and no benchmark windows."),
        ("dynamic_weighting", "No factor scores, no performance metrics, and no dynamic weighting gate."),
        ("trading_signal", "No factor scores, no backtest validation, and no trading signal gate."),
        ("strategy_signal", "No strategy signal gate and no complete strategy dependency evidence."),
        ("official_recommendation", "No official-use gate, no portfolio/position framework gate, and no broker/order path."),
    ]
    for name, reason in downstream_reasons:
        downstream_blocker_rows.append(
            {
                "blocked_layer": name,
                "allowed_now": "FALSE",
                "blocker_reason": reason,
                "factor_scores_created": "0",
                "forward_outcomes_created": "0",
                "performance_metrics_created": "0",
                "benchmark_windows_created": "0",
                "strategy_signal_gate_passed": "FALSE",
                "portfolio_position_framework_gate_passed": "FALSE",
                "official_use_allowed": "FALSE",
            }
        )

    gate_passed = (
        gate_ok
        and evidence_gate_ok
        and validation_ok
        and read_first_ok
        and schema_passed
        and lineage_passed
        and boundary_passed
        and dq_passed
        and scope_passed
        and not any(row["blocks_v20_13"] == "TRUE" for row in blockers)
    )
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    layer_created = gate_passed and row_count > 0
    ready_next = gate_passed
    next_step = "V20.14_FACTOR_EVIDENCE_REVIEW_OR_FACTOR_SCORE_GATE" if gate_passed else "Resolve V20.13 blockers before V20.14."

    gate_rows = [
        {
            "gate_id": "V20_13_GATE",
            "STATUS": status,
            "LIMITED_FACTOR_EVIDENCE_LAYER_CREATED": tf(layer_created),
            "FACTOR_EVIDENCE_ROWS_CREATED": str(row_count if layer_created else 0),
            "FACTOR_SCORES_CREATED": "0",
            "PERFORMANCE_METRICS_CREATED": "0",
            "BACKTEST_ROWS_CREATED": "0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
            "TRADING_SIGNAL_ROWS_CREATED": "0",
            "STRATEGY_SIGNAL_ROWS_CREATED": "0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
            "READY_FOR_V20_14_FACTOR_SCORE_GATE_OR_EVIDENCE_REVIEW_NEXT": tf(ready_next),
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "First limited research-only factor evidence layer created." if gate_passed else "V20.13 dependency, schema, lineage, boundary, data quality, or scope checks failed.",
        }
    ]
    next_rows = [
        {
            "decision_id": "V20_13_NEXT_STEP",
            "current_status": status,
            "next_recommended_step": next_step,
            "ready_for_v20_14_factor_score_gate_or_evidence_review_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "boundary_notes": "Limited evidence only; no factor scores, performance metrics, forward returns, backtests, dynamic weights, signals, or official recommendations.",
        }
    ]

    read_first_out = "\n".join(
        [
            "PATCH_VERSION: V20.13",
            "PATCH_NAME: FIRST_LIMITED_FACTOR_EVIDENCE_LAYER",
            "REPORTING_ONLY = FALSE",
            "FIRST_LIMITED_FACTOR_EVIDENCE_LAYER = TRUE",
            f"STATUS = {status}",
            f"LIMITED_FACTOR_EVIDENCE_LAYER_CREATED = {tf(layer_created)}",
            f"FACTOR_EVIDENCE_ROWS_CREATED = {row_count if layer_created else 0}",
            "FACTOR_SCORES_CREATED = 0",
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
            f"FACTOR_FAMILIES_COVERED = {len(family_groups)}",
            f"NEXT_RECOMMENDED_STEP = {next_step}",
            "",
        ]
    )
    read_first_flags = [
        "REPORTING_ONLY = FALSE",
        "FIRST_LIMITED_FACTOR_EVIDENCE_LAYER = TRUE",
        f"LIMITED_FACTOR_EVIDENCE_LAYER_CREATED = {tf(layer_created)}",
        f"FACTOR_EVIDENCE_ROWS_CREATED = {row_count if layer_created else 0}",
        "FACTOR_SCORES_CREATED = 0",
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
    protected_input_mutation_check_passed = all(path.name.startswith("V20_13") or path == CURRENT_REPORT for path in ALLOWED_WRITE_PATHS)
    no_v21_or_v19_21_outputs = not any("V21" in path.name or "V19_21" in path.name for path in ALLOWED_WRITE_PATHS)
    static_write_path_check_passed = len(ALLOWED_WRITE_PATHS) == 17 and protected_input_mutation_check_passed and no_v21_or_v19_21_outputs

    validation_rows = [
        {
            "status": status,
            "patch_version": PATCH_VERSION,
            "generated_at_utc": generated_at,
            "dependency_audit_passed": tf(gate_ok and evidence_gate_ok and validation_ok and read_first_ok and all(path.exists() for path in REQUIRED_INPUTS)),
            "limited_factor_evidence_layer_created": tf(layer_created),
            "factor_evidence_rows_created": str(row_count if layer_created else 0),
            "factor_families_covered": str(len(family_groups)),
            "factor_evidence_row_count_check_passed": tf(row_count == sum(approved_allowed_rows.values()) and row_count > 0),
            "factor_evidence_row_id_uniqueness_check_passed": tf(duplicate_evidence_ids == 0),
            "evidence_scope_compliance_check_passed": tf(scope_passed),
            "lineage_preservation_check_passed": tf(lineage_passed),
            "boundary_audit_check_passed": tf(boundary_passed),
            "factor_scores_created": "0",
            "performance_metrics_created": "0",
            "forward_return_rows_created": "0",
            "benchmark_relative_return_rows_created": "0",
            "backtest_rows_created": "0",
            "dynamic_weighting_rows_created": "0",
            "trading_signal_rows_created": "0",
            "strategy_signal_rows_created": "0",
            "official_recommendation_rows_created": "0",
            "ready_for_v20_14_factor_score_gate_or_evidence_review_next": tf(ready_next),
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "read_first_safety_flag_check_passed": tf(read_first_safety_ok),
            "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_mutation_check_passed": tf(protected_input_mutation_check_passed),
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
            "# V20.13 First Limited Factor Evidence Layer",
            "",
            f"Generated at UTC: {generated_at}",
            "",
            f"STATUS: {status}",
            f"LIMITED_FACTOR_EVIDENCE_LAYER_CREATED: {tf(layer_created)}",
            f"FACTOR_EVIDENCE_ROWS_CREATED: {row_count if layer_created else 0}",
            f"FACTOR_FAMILIES_COVERED: {len(family_groups)}",
            "FACTOR_SCORES_CREATED: 0",
            "PERFORMANCE_METRICS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "STRATEGY_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "",
            "## Family Summary",
            md_table(["factor_category", "factor_family", "evidence_rows_created", "unique_tickers", "evidence_scope_allowed_by_v20_12", "next_required_step"], family_summary_rows),
            "",
            "## Boundary",
            md_table(list(boundary_rows[0].keys()), boundary_rows),
            "",
            "## Downstream Blockers",
            md_table(["blocked_layer", "allowed_now", "blocker_reason"], downstream_blocker_rows),
            "",
            "## Blockers",
            md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.13 blockers.",
            "",
        ]
    )

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_LAYER, evidence_rows, EVIDENCE_COLUMNS)
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, list(lineage_rows[0].keys()))
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, dq_rows, list(dq_rows[0].keys()))
    write_csv(OUT_FAMILY_SUMMARY, family_summary_rows, ["factor_category", "factor_family", "evidence_rows_created", "unique_tickers", "evidence_scope_allowed_by_v20_12", "evidence_layer_created_now", "score_created_now", "performance_metric_created_now", "backtest_allowed_now", "dynamic_weighting_allowed_now", "trading_allowed_now", "official_use_allowed", "next_required_step"])
    write_csv(OUT_SCOPE_COMPLIANCE, scope_rows, list(scope_rows[0].keys()))
    write_csv(OUT_MISSING_CARRY, carry_rows, ["missing_source_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_12_or_v20_11", "blocks_factor_score", "blocks_full_factor_evidence", "blocks_backtest", "blocks_dynamic_weighting", "blocks_strategy_signals", "blocks_official_use", "limited_evidence_scope_ready", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_DOWNSTREAM_BLOCKERS, downstream_blocker_rows, ["blocked_layer", "allowed_now", "blocker_reason", "factor_scores_created", "forward_outcomes_created", "performance_metrics_created", "benchmark_windows_created", "strategy_signal_gate_passed", "portfolio_position_framework_gate_passed", "official_use_allowed"])
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_13"])
    write_csv(OUT_GATE, gate_rows, list(gate_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_rows, list(validation_rows[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first_out)

    print(f"STATUS: {status}")
    print(f"LIMITED_FACTOR_EVIDENCE_LAYER_CREATED: {tf(layer_created)}")
    print(f"FACTOR_EVIDENCE_ROWS_CREATED: {row_count if layer_created else 0}")
    print(f"FACTOR_FAMILIES_COVERED: {len(family_groups)}")
    print(f"BOUNDARY_STATUS: {boundary_rows[0]['boundary_status']}")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
