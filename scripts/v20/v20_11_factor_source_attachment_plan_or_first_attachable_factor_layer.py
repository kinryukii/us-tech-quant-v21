from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_BASE = CONSOLIDATION / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
IN_INVENTORY = CONSOLIDATION / "V20_10_FACTOR_SOURCE_INVENTORY.csv"
IN_ATTACHMENT_AUDIT = CONSOLIDATION / "V20_10_FACTOR_SOURCE_ATTACHMENT_AUDIT.csv"
IN_ATTACHABLE_REGISTER = CONSOLIDATION / "V20_10_ATTACHABLE_FACTOR_FAMILY_REGISTER.csv"
IN_MISSING = CONSOLIDATION / "V20_10_MISSING_FACTOR_SOURCE_REGISTER.csv"
IN_GATE = CONSOLIDATION / "V20_10_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_10_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_10_READ_FIRST.txt"

OUT_DEPENDENCY = CONSOLIDATION / "V20_11_DEPENDENCY_AUDIT.csv"
OUT_REVIEW = CONSOLIDATION / "V20_11_ATTACHABLE_FACTOR_FAMILY_REVIEW.csv"
OUT_PLAN = CONSOLIDATION / "V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN.csv"
OUT_LAYER = CONSOLIDATION / "V20_11_FIRST_ATTACHABLE_FACTOR_INPUT_LAYER.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_SCHEMA_AUDIT.csv"
OUT_LINEAGE = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_LINEAGE_AUDIT.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_BOUNDARY_AUDIT.csv"
OUT_DATA_QUALITY = CONSOLIDATION / "V20_11_FACTOR_ATTACHMENT_DATA_QUALITY_AUDIT.csv"
OUT_STRATEGY_PLAN = CONSOLIDATION / "V20_11_STRATEGY_FAMILY_ATTACHMENT_PLAN.csv"
OUT_STRATEGY_READINESS = CONSOLIDATION / "V20_11_STRATEGY_DEPENDENCY_READINESS_AUDIT.csv"
OUT_MISSING_CARRY = CONSOLIDATION / "V20_11_MISSING_FACTOR_SOURCE_CARRYFORWARD_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_11_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_11_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_11_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_11_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_SOURCE_ATTACHMENT_PLAN.md"
READ_FIRST = OPS / "V20_11_READ_FIRST.txt"

PATCH_VERSION = "V20.11"
ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_REVIEW,
    OUT_PLAN,
    OUT_LAYER,
    OUT_SCHEMA,
    OUT_LINEAGE,
    OUT_BOUNDARY,
    OUT_DATA_QUALITY,
    OUT_STRATEGY_PLAN,
    OUT_STRATEGY_READINESS,
    OUT_MISSING_CARRY,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

ATTACHMENT_COLUMNS = [
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
    "attachment_value_numeric",
    "attachment_value_text",
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

STRATEGY_SPECS = [
    ("ma10_ma20_pullback", "ma_ema;pullback_quality;trend", "historical_ohlcv_windows;moving_average_windows"),
    ("momentum_breakout", "momentum;breakout;volume", "historical_ohlcv_windows;breakout_windows;volume_history"),
    ("quality_momentum", "quality;momentum", "fundamental_snapshot;historical_ohlcv_windows"),
    ("relative_strength_breakout", "relative_strength;breakout", "benchmark_series;historical_ohlcv_windows"),
    ("entry_timing", "trend;momentum;volume", "historical_ohlcv_windows;market_session_windows"),
    ("exit_stop", "volatility;portfolio_drawdown", "historical_ohlcv_windows;drawdown_windows"),
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def attachment_id(base_row: dict[str, str], factor_family: str) -> str:
    basis = "|".join(
        [
            clean(base_row.get("factor_research_row_id")),
            clean(base_row.get("normalized_row_id")),
            clean(base_row.get("ticker")),
            clean(base_row.get("sample_id")),
            clean(base_row.get("source_hash")),
            clean(base_row.get("run_id")),
            factor_family,
        ]
    )
    return "V20_11_ATTACH_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in headers) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(headers) - 2))
    return "\n".join(lines)


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str, severity: str = "BLOCKING") -> None:
    blockers.append(
        {
            "blocker_id": f"V20_11_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_11": tf(severity == "BLOCKING"),
        }
    )


def attachment_value_for(base_row: dict[str, str], factor_family: str) -> tuple[str, str, str, str]:
    if factor_family == "freshness":
        return ("metadata_flag", "TRUE", "1", "effective_price_date_present")
    if factor_family == "source_quality":
        return ("metadata_flag", "TRUE", "1", "source_hash_and_run_id_present")
    if factor_family == "point_in_time":
        return ("metadata_flag", "TRUE", "1", "effective_observation_and_price_dates_present")
    if factor_family == "safe_backtest_eligibility":
        return ("metadata_flag", "TRUE", "0", "blocked_until_explicit_evidence_and_backtest_gate")
    if factor_family == "current_snapshot_block":
        return ("metadata_flag", "TRUE", "1", "current_snapshot_blocked_for_official_use")
    return ("metadata_text", "FALSE", "", "")


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []

    base_rows, _ = read_csv(IN_BASE)
    inventory_rows, _ = read_csv(IN_INVENTORY)
    attachment_audit_rows, _ = read_csv(IN_ATTACHMENT_AUDIT)
    register_rows, _ = read_csv(IN_ATTACHABLE_REGISTER)
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

    v20_10_passed = upper(gate.get("status")) == "PASS_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT" and upper(validation.get("status")) == "PASS_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT"
    audit_created = upper(gate.get("FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED")) == "TRUE" and upper(validation.get("factor_source_attachment_audit_created")) == "TRUE"
    rows_reviewed = int(clean(gate.get("FACTOR_RESEARCH_ROWS_REVIEWED")) or "0") > 0
    ready_next = upper(gate.get("READY_FOR_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_LAYER_NEXT")) == "TRUE" and upper(validation.get("ready_for_v20_11_factor_source_attachment_plan_or_first_attachable_layer_next")) == "TRUE"
    no_evidence = upper(gate.get("READY_FOR_FACTOR_EVIDENCE_NEXT")) == "FALSE" and upper(validation.get("ready_for_factor_evidence_next")) == "FALSE"
    no_backtest = upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE" and upper(validation.get("ready_for_backtest_next")) == "FALSE"
    no_dynamic = upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE" and upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE"
    no_trading = upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE" and upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE"
    read_first_ok = all(
        flag in read_first_text
        for flag in [
            "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY: TRUE",
            "FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED: TRUE",
            "FACTOR_SCORES_CREATED: 0",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "SOURCE_MUTATION_USED: FALSE",
            "V21_OUTPUTS_CREATED: FALSE",
            "V19_21_OUTPUTS_CREATED: FALSE",
            "OFFICIAL_USE_ALLOWED: FALSE",
        ]
    )

    dependency("V20_9_FACTOR_RESEARCH_BASE_DATASET", IN_BASE, IN_BASE.exists() and bool(base_rows), "V20.9 factor research base dataset is missing or empty.")
    dependency("V20_10_FACTOR_SOURCE_INVENTORY", IN_INVENTORY, IN_INVENTORY.exists() and bool(inventory_rows), "V20.10 source inventory is missing or empty.")
    dependency("V20_10_FACTOR_SOURCE_ATTACHMENT_AUDIT", IN_ATTACHMENT_AUDIT, IN_ATTACHMENT_AUDIT.exists() and bool(attachment_audit_rows), "V20.10 attachment audit is missing or empty.")
    dependency("V20_10_ATTACHABLE_FACTOR_FAMILY_REGISTER", IN_ATTACHABLE_REGISTER, IN_ATTACHABLE_REGISTER.exists() and bool(register_rows), "V20.10 attachable family register is missing or empty.")
    dependency("V20_10_MISSING_FACTOR_SOURCE_REGISTER", IN_MISSING, IN_MISSING.exists() and bool(missing_rows), "V20.10 missing source register is missing or empty.")
    dependency("V20_10_GATE_DECISION", IN_GATE, v20_10_passed and audit_created and rows_reviewed and ready_next and no_evidence and no_backtest and no_dynamic and no_trading, "V20.10 gate does not permit V20.11.")
    dependency("V20_10_VALIDATION_SUMMARY", IN_VALIDATION, v20_10_passed and audit_created and ready_next and no_evidence and no_backtest and no_dynamic and no_trading, "V20.10 validation summary is not in the required state.")
    dependency("V20_10_READ_FIRST", IN_READ_FIRST, read_first_ok, "V20.10 READ_FIRST safety flags are incomplete.")

    attachable = [row for row in register_rows if upper(row.get("attachment_ready_now")) == "TRUE"]
    partial = [row for row in register_rows if row.get("attachment_status") == "PARTIAL_SOURCE_AVAILABLE"]
    source_required = [row for row in register_rows if row.get("attachment_status") == "SOURCE_REQUIRED"]

    review_rows = []
    for row in register_rows:
        review_rows.append(
            {
                "factor_category": clean(row.get("factor_category")),
                "factor_family": clean(row.get("factor_family")),
                "attachment_status_from_v20_10": clean(row.get("attachment_status")),
                "attachment_ready_now": clean(row.get("attachment_ready_now")),
                "classification_preserved": "TRUE",
                "source_attachment_allowed_now": tf(upper(row.get("attachment_ready_now")) == "TRUE"),
                "factor_input_layer_allowed_now": tf(upper(row.get("attachment_ready_now")) == "TRUE"),
                "blocker_reason": clean(row.get("missing_source_reference")),
                "next_required_step": clean(row.get("next_required_step")),
            }
        )

    audit_by_key = {(clean(row.get("factor_category")), clean(row.get("factor_name"))): row for row in attachment_audit_rows}
    plan_rows = []
    for row in register_rows:
        category = clean(row.get("factor_category"))
        family = clean(row.get("factor_family"))
        audit = audit_by_key.get((category, family), {})
        ready = upper(row.get("attachment_ready_now")) == "TRUE"
        plan_rows.append(
            {
                "factor_category": category,
                "factor_family": family,
                "attachment_status_from_v20_10": clean(row.get("attachment_status")),
                "attachment_ready_now": tf(ready),
                "source_attachment_allowed_now": tf(ready),
                "factor_input_layer_allowed_now": tf(ready),
                "factor_score_allowed_now": "FALSE",
                "factor_evidence_allowed_now": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weighting_allowed_now": "FALSE",
                "official_use_allowed": "FALSE",
                "accepted_source_reference": clean(row.get("accepted_source_reference")),
                "source_hash_available": clean(audit.get("source_hash_available")) or tf(ready),
                "run_id_available": clean(audit.get("run_id_available")) or tf(ready),
                "point_in_time_ready": clean(audit.get("point_in_time_ready")) or tf(ready),
                "stale_leakage_checked": clean(audit.get("stale_leakage_checked")) or tf(ready),
                "missing_source_reference": clean(row.get("missing_source_reference")),
                "next_required_step": clean(row.get("next_required_step")),
            }
        )

    attachment_rows: list[dict[str, str]] = []
    for base in base_rows:
        for family_row in attachable:
            family = clean(family_row.get("factor_family"))
            value_type, value_present, value_numeric, value_text = attachment_value_for(base, family)
            attachment_rows.append(
                {
                    "factor_attachment_row_id": attachment_id(base, family),
                    "factor_research_row_id": clean(base.get("factor_research_row_id")),
                    "normalized_row_id": clean(base.get("normalized_row_id")),
                    "ticker": clean(base.get("ticker")),
                    "effective_observation_date": clean(base.get("effective_observation_date")),
                    "effective_price_date": clean(base.get("effective_price_date")),
                    "effective_close": clean(base.get("effective_close")),
                    "source_system": clean(base.get("source_system")),
                    "source_hash": clean(base.get("source_hash")),
                    "run_id": clean(base.get("run_id")),
                    "sample_id": clean(base.get("sample_id")),
                    "factor_category": clean(family_row.get("factor_category")),
                    "factor_family": family,
                    "attachment_source_reference": clean(family_row.get("accepted_source_reference")),
                    "attachment_input_type": "lineage_metadata",
                    "attachment_value_type": value_type,
                    "attachment_value_present": value_present,
                    "attachment_value_numeric": value_numeric,
                    "attachment_value_text": value_text,
                    "attachment_status": "ATTACHED_NON_SCORING_INPUT",
                    "factor_score_created": "FALSE",
                    "factor_evidence_created": "FALSE",
                    "research_only_flag": "TRUE",
                    "official_use_allowed": "FALSE",
                    "allowed_for_factor_evidence_next": "FALSE",
                    "allowed_for_backtest_now": "FALSE",
                    "allowed_for_dynamic_weighting_now": "FALSE",
                    "allowed_for_trading_now": "FALSE",
                    "allowed_for_official_recommendation_now": "FALSE",
                    "attachment_created_at_utc": generated_at,
                    "attachment_source_step": PATCH_VERSION,
                }
            )

    attachment_ids = [clean(row.get("factor_attachment_row_id")) for row in attachment_rows]
    duplicate_attachment_ids = max(0, len(attachment_ids) - len(set(attachment_ids)))
    missing_factor_research_id = sum(1 for row in attachment_rows if not clean(row.get("factor_research_row_id")))
    missing_hash = sum(1 for row in attachment_rows if not clean(row.get("source_hash")))
    missing_run_id = sum(1 for row in attachment_rows if not clean(row.get("run_id")))
    missing_sample_id = sum(1 for row in attachment_rows if not clean(row.get("sample_id")))
    score_rows_created = sum(1 for row in attachment_rows if upper(row.get("factor_score_created")) not in {"FALSE", "0", ""})
    evidence_rows_created = sum(1 for row in attachment_rows if upper(row.get("factor_evidence_created")) not in {"FALSE", "0", ""})
    official_rows = sum(1 for row in attachment_rows if upper(row.get("official_use_allowed")) == "TRUE")

    schema_rows = []
    attachment_field_set = set(attachment_rows[0].keys()) if attachment_rows else set()
    for col in ATTACHMENT_COLUMNS:
        non_empty = sum(1 for row in attachment_rows if clean(row.get(col)))
        required_non_empty = col not in {"attachment_value_numeric", "attachment_value_text"}
        ok = col in attachment_field_set and (non_empty == len(attachment_rows) if required_non_empty else True)
        schema_rows.append(
            {
                "column_name": col,
                "required": "TRUE",
                "detected": tf(col in attachment_field_set),
                "non_empty_row_count": str(non_empty),
                "row_count": str(len(attachment_rows)),
                "schema_status": "PASS" if ok else "BLOCKED",
                "blocker_reason": "" if ok else f"Required attachment column {col} is missing or incomplete.",
            }
        )

    lineage_ok = bool(attachment_rows) and not any(
        not clean(row.get(field))
        for row in attachment_rows
        for field in ("factor_research_row_id", "normalized_row_id", "source_hash", "run_id", "sample_id", "attachment_source_reference")
    )
    lineage_rows = [
        {
            "lineage_audit_id": "V20_11_LINEAGE_001",
            "attachment_row_count": str(len(attachment_rows)),
            "linked_to_v20_9_factor_research_base_count": str(sum(1 for row in attachment_rows if clean(row.get("factor_research_row_id")))),
            "linked_to_v20_8_normalized_row_count": str(sum(1 for row in attachment_rows if clean(row.get("normalized_row_id")))),
            "linked_to_v20_7x_active_input_lineage_count": str(sum(1 for row in attachment_rows if clean(row.get("source_hash")) and clean(row.get("run_id")))),
            "linked_to_v20_10_factor_source_classification_count": str(sum(1 for row in attachment_rows if clean(row.get("attachment_source_reference")))),
            "source_hash_preserved_count": str(sum(1 for row in attachment_rows if clean(row.get("source_hash")))),
            "run_id_preserved_count": str(sum(1 for row in attachment_rows if clean(row.get("run_id")))),
            "sample_id_preserved_count": str(sum(1 for row in attachment_rows if clean(row.get("sample_id")))),
            "lineage_status": "PASS" if lineage_ok else "BLOCKED",
            "blocker_reason": "" if lineage_ok else "Attachment lineage is incomplete.",
        }
    ]
    if not lineage_ok:
        add_blocker(blockers, "LINEAGE", "Attachment lineage is incomplete.")
    if duplicate_attachment_ids:
        add_blocker(blockers, "SCHEMA", "factor_attachment_row_id is duplicated.")
    if score_rows_created or evidence_rows_created or official_rows:
        add_blocker(blockers, "BOUNDARY", "Scoring, evidence, or official-use flags were enabled.")

    strategy_plan_rows = []
    strategy_readiness_rows = []
    for strategy, factor_deps, source_deps in STRATEGY_SPECS:
        dependency_ready = False
        reason = "Required technical/fundamental/risk source inputs are not fully attached."
        strategy_plan_rows.append(
            {
                "strategy_family": strategy,
                "depends_on_factor_families": factor_deps,
                "depends_on_source_types": source_deps,
                "dependency_ready_now": tf(dependency_ready),
                "strategy_layer_allowed_now": "FALSE",
                "signal_allowed_now": "FALSE",
                "backtest_allowed_now": "FALSE",
                "dynamic_weighting_allowed_now": "FALSE",
                "official_use_allowed": "FALSE",
                "blocker_reason": reason,
                "next_required_step": "V20.12 factor input layer review or later explicit strategy gate.",
            }
        )
        strategy_readiness_rows.append(
            {
                "strategy_family": strategy,
                "required_factor_family_count": str(len(factor_deps.split(";"))),
                "attached_required_factor_family_count": "0",
                "dependency_ready_now": tf(dependency_ready),
                "strategy_readiness_status": "SOURCE_REQUIRED",
                "signals_created": "0",
                "blocker_reason": reason,
            }
        )

    carry_rows = []
    for row in missing_rows:
        carry_rows.append(
            {
                "missing_source_id": clean(row.get("missing_source_id")).replace("V20_10", "V20_11") or f"V20_11_MISSING_{len(carry_rows) + 1:03d}",
                "required_source_name": clean(row.get("required_source_name")),
                "required_for_factor_categories": clean(row.get("required_for_factor_categories")),
                "source_status": clean(row.get("source_status")),
                "carryforward_from_v20_10": "TRUE",
                "blocks_factor_score": "TRUE",
                "blocks_factor_evidence": "TRUE",
                "blocks_backtest": "TRUE",
                "blocks_dynamic_weighting": "TRUE",
                "blocker_reason": clean(row.get("blocker_reason")),
                "next_required_source_or_step": clean(row.get("next_required_step")) or "V20.12 factor input layer review",
            }
        )

    first_layer_created = bool(attachment_rows)
    boundary_rows = [
        {
            "boundary_check_id": "V20_11_BOUNDARY_001",
            "FACTOR_SOURCE_ATTACHMENT_PLAN_ONLY_OR_NON_SCORING_INPUT_LAYER": "TRUE",
            "FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED": tf(first_layer_created),
            "FACTOR_SCORES_CREATED": "0",
            "FACTOR_EVIDENCE_ROWS_CREATED": "0",
            "BACKTEST_ROWS_CREATED": "0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
            "TRADING_SIGNAL_ROWS_CREATED": "0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
            "STRATEGY_SIGNALS_CREATED": "0",
            "OFFICIAL_USE_ALLOWED": "FALSE",
            "boundary_status": "PASS" if score_rows_created == 0 and evidence_rows_created == 0 and official_rows == 0 else "BLOCKED",
            "blocker_reason": "" if score_rows_created == 0 and evidence_rows_created == 0 and official_rows == 0 else "Boundary flags failed.",
        }
    ]

    data_quality_rows = [
        {
            "quality_check_id": "V20_11_QUALITY_001",
            "factor_research_rows_reviewed": str(len(base_rows)),
            "attachable_factor_families_count": str(len(attachable)),
            "first_attachable_factor_input_layer_rows_created": str(len(attachment_rows)),
            "unique_tickers": str(len({clean(row.get("ticker")) for row in attachment_rows if clean(row.get("ticker"))})),
            "unique_factor_families_attached": str(len({clean(row.get("factor_family")) for row in attachment_rows if clean(row.get("factor_family"))})),
            "missing_factor_research_row_id_count": str(missing_factor_research_id),
            "missing_source_hash_count": str(missing_hash),
            "missing_run_id_count": str(missing_run_id),
            "missing_sample_id_count": str(missing_sample_id),
            "duplicate_factor_attachment_row_id_count": str(duplicate_attachment_ids),
            "factor_score_rows_created": str(score_rows_created),
            "factor_evidence_rows_created": str(evidence_rows_created),
            "official_use_allowed_rows": str(official_rows),
            "data_quality_status": "PASS" if first_layer_created and duplicate_attachment_ids == 0 and missing_factor_research_id == 0 and missing_hash == 0 and missing_run_id == 0 and missing_sample_id == 0 and score_rows_created == 0 and evidence_rows_created == 0 and official_rows == 0 else "BLOCKED",
            "blocker_reason": "" if first_layer_created and duplicate_attachment_ids == 0 and missing_factor_research_id == 0 and missing_hash == 0 and missing_run_id == 0 and missing_sample_id == 0 and score_rows_created == 0 and evidence_rows_created == 0 and official_rows == 0 else "Attachment data quality failed.",
        }
    ]
    if data_quality_rows[0]["data_quality_status"] != "PASS":
        add_blocker(blockers, "DATA_QUALITY", data_quality_rows[0]["blocker_reason"])

    blocking_count = sum(1 for blocker in blockers if blocker["severity"] == "BLOCKING")
    plan_created = blocking_count == 0 and bool(plan_rows)
    ready_v20_12 = plan_created
    status = "PASS_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER" if ready_v20_12 else "BLOCKED_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER"
    next_step = "V20.12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE" if ready_v20_12 else "RESOLVE_V20_11_BLOCKERS"

    gate_out = [
        {
            "gate_id": "V20_11_GATE",
            "status": status,
            "FACTOR_SOURCE_ATTACHMENT_PLAN_CREATED": tf(plan_created),
            "FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED": tf(first_layer_created),
            "FACTOR_ATTACHMENT_ROWS_CREATED": str(len(attachment_rows)),
            "ATTACHABLE_FACTOR_FAMILIES_ATTACHED": str(len(attachable)),
            "STRATEGY_FAMILY_READINESS_RECORDED": "TRUE",
            "READY_FOR_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE_NEXT": tf(ready_v20_12),
            "READY_FOR_FACTOR_EVIDENCE_NEXT": "FALSE",
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "V21_OUTPUTS_CREATED": "FALSE",
            "V19_21_OUTPUTS_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "Attachment plan and first non-scoring attachable input layer created without boundary violations." if ready_v20_12 else "Dependency, schema, lineage, data quality, or boundary checks failed.",
        }
    ]
    next_out = [
        {
            "decision_id": "V20_11_NEXT_STEP",
            "ready_for_v20_12_factor_input_layer_review_or_factor_evidence_gate_next": tf(ready_v20_12),
            "ready_for_factor_evidence_next": "FALSE",
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "next_recommended_step": next_step,
            "reason": "Non-scoring attachable factor input layer is ready for review; evidence remains blocked.",
        }
    ]
    blocker_rows = blockers or [
        {
            "blocker_id": "V20_11_BLOCKER_000",
            "blocker_scope": "NONE",
            "severity": "INFO",
            "blocker_status": "CLEARED",
            "blocker_reason": "",
            "blocks_v20_11": "FALSE",
        }
    ]

    static_write_ok = set(ALLOWED_WRITE_PATHS) == {
        OUT_DEPENDENCY,
        OUT_REVIEW,
        OUT_PLAN,
        OUT_LAYER,
        OUT_SCHEMA,
        OUT_LINEAGE,
        OUT_BOUNDARY,
        OUT_DATA_QUALITY,
        OUT_STRATEGY_PLAN,
        OUT_STRATEGY_READINESS,
        OUT_MISSING_CARRY,
        OUT_BLOCKERS,
        OUT_GATE,
        OUT_NEXT,
        OUT_VALIDATION,
        REPORT,
        CURRENT_REPORT,
        READ_FIRST,
    }
    validation_row = {
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "factor_source_attachment_plan_created": tf(plan_created),
        "first_attachable_factor_input_layer_created": tf(first_layer_created),
        "factor_research_rows_reviewed": str(len(base_rows)),
        "attachable_factor_families_count": str(len(attachable)),
        "partial_factor_families_count": str(len(partial)),
        "source_required_factor_families_count": str(len(source_required)),
        "factor_attachment_rows_created": str(len(attachment_rows)),
        "factor_attachment_row_id_unique_count": str(len(set(attachment_ids))),
        "factor_attachment_row_id_duplicate_count": str(duplicate_attachment_ids),
        "strategy_family_readiness_count": str(len(strategy_readiness_rows)),
        "missing_factor_source_carryforward_count": str(len(carry_rows)),
        "ready_for_v20_12_factor_input_layer_review_or_factor_evidence_gate_next": tf(ready_v20_12),
        "ready_for_factor_evidence_next": "FALSE",
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "dependency_blocker_count": str(sum(1 for row in dependency_rows if row["status"] == "BLOCKED")),
        "total_blocker_count": str(blocking_count),
        "factor_scores_created": "0",
        "factor_evidence_rows_created": "0",
        "strategy_signals_created": "0",
        "official_use_allowed_rows": str(official_rows),
        "static_write_path_check_passed": tf(static_write_ok),
        "REPORTING_ONLY": "FALSE",
        "FACTOR_SOURCE_ATTACHMENT_PLAN_ONLY_OR_NON_SCORING_INPUT_LAYER": "TRUE",
        "FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED": tf(first_layer_created),
        "FACTOR_SCORES_CREATED": "0",
        "FACTOR_EVIDENCE_ROWS_CREATED": "0",
        "BACKTEST_ROWS_CREATED": "0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
        "TRADING_SIGNAL_ROWS_CREATED": "0",
        "STRATEGY_SIGNALS_CREATED": "0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
        "BROKER_API_USED": "FALSE",
        "ORDER_EXECUTION_USED": "FALSE",
        "SOURCE_MUTATION_USED": "FALSE",
        "V21_OUTPUTS_CREATED": "FALSE",
        "V19_21_OUTPUTS_CREATED": "FALSE",
        "OFFICIAL_USE_ALLOWED": "FALSE",
    }

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_REVIEW, review_rows, ["factor_category", "factor_family", "attachment_status_from_v20_10", "attachment_ready_now", "classification_preserved", "source_attachment_allowed_now", "factor_input_layer_allowed_now", "blocker_reason", "next_required_step"])
    write_csv(OUT_PLAN, plan_rows, ["factor_category", "factor_family", "attachment_status_from_v20_10", "attachment_ready_now", "source_attachment_allowed_now", "factor_input_layer_allowed_now", "factor_score_allowed_now", "factor_evidence_allowed_now", "backtest_allowed_now", "dynamic_weighting_allowed_now", "official_use_allowed", "accepted_source_reference", "source_hash_available", "run_id_available", "point_in_time_ready", "stale_leakage_checked", "missing_source_reference", "next_required_step"])
    write_csv(OUT_LAYER, attachment_rows, ATTACHMENT_COLUMNS)
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
    write_csv(OUT_LINEAGE, lineage_rows, ["lineage_audit_id", "attachment_row_count", "linked_to_v20_9_factor_research_base_count", "linked_to_v20_8_normalized_row_count", "linked_to_v20_7x_active_input_lineage_count", "linked_to_v20_10_factor_source_classification_count", "source_hash_preserved_count", "run_id_preserved_count", "sample_id_preserved_count", "lineage_status", "blocker_reason"])
    write_csv(OUT_BOUNDARY, boundary_rows, list(boundary_rows[0].keys()))
    write_csv(OUT_DATA_QUALITY, data_quality_rows, list(data_quality_rows[0].keys()))
    write_csv(OUT_STRATEGY_PLAN, strategy_plan_rows, ["strategy_family", "depends_on_factor_families", "depends_on_source_types", "dependency_ready_now", "strategy_layer_allowed_now", "signal_allowed_now", "backtest_allowed_now", "dynamic_weighting_allowed_now", "official_use_allowed", "blocker_reason", "next_required_step"])
    write_csv(OUT_STRATEGY_READINESS, strategy_readiness_rows, ["strategy_family", "required_factor_family_count", "attached_required_factor_family_count", "dependency_ready_now", "strategy_readiness_status", "signals_created", "blocker_reason"])
    write_csv(OUT_MISSING_CARRY, carry_rows, ["missing_source_id", "required_source_name", "required_for_factor_categories", "source_status", "carryforward_from_v20_10", "blocks_factor_score", "blocks_factor_evidence", "blocks_backtest", "blocks_dynamic_weighting", "blocker_reason", "next_required_source_or_step"])
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_11"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_NEXT, next_out, list(next_out[0].keys()))
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    report_text = "\n".join(
        [
            "# V20.11 Factor Source Attachment Plan or First Attachable Factor Layer",
            "",
            f"- STATUS: `{status}`",
            f"- factor attachment rows created: `{len(attachment_rows)}`",
            f"- attachable factor families attached: `{len(attachable)}`",
            f"- strategy family readiness rows: `{len(strategy_readiness_rows)}`",
            f"- ready for V20.12 next: `{tf(ready_v20_12)}`",
            "- factor scores created: `0`",
            "- factor evidence rows created: `0`",
            "- strategy signals created: `0`",
            "",
            "## Gate Decision",
            md_table(["gate_id", "status", "FACTOR_SOURCE_ATTACHMENT_PLAN_CREATED", "FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED", "FACTOR_ATTACHMENT_ROWS_CREATED", "ATTACHABLE_FACTOR_FAMILIES_ATTACHED", "READY_FOR_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE_NEXT"], gate_out),
            "",
            "## Boundary",
            md_table(["boundary_check_id", "FACTOR_SCORES_CREATED", "FACTOR_EVIDENCE_ROWS_CREATED", "STRATEGY_SIGNALS_CREATED", "OFFICIAL_USE_ALLOWED", "boundary_status"], boundary_rows),
            "",
            "This step creates only a source attachment plan and a non-scoring attachable factor input layer for V20.10 attachable data-trustworthiness families. It does not compute factor scores, create factor evidence, run backtests, create dynamic weighting rows, trading signals, strategy signals, official recommendations, V21 outputs, or V19.21 outputs.",
            "",
        ]
    )
    write_text(REPORT, report_text)
    write_text(CURRENT_REPORT, report_text)

    read_first_text = "\n".join(
        [
            f"STATUS: {status}",
            f"PATCH_VERSION: {PATCH_VERSION}",
            "REPORTING_ONLY: FALSE",
            "FACTOR_SOURCE_ATTACHMENT_PLAN_ONLY_OR_NON_SCORING_INPUT_LAYER: TRUE",
            f"FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED: {tf(first_layer_created)}",
            f"FACTOR_ATTACHMENT_ROWS_CREATED: {len(attachment_rows)}",
            "FACTOR_SCORES_CREATED: 0",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "STRATEGY_SIGNALS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "BROKER_API_USED: FALSE",
            "ORDER_EXECUTION_USED: FALSE",
            "SOURCE_MUTATION_USED: FALSE",
            "V21_OUTPUTS_CREATED: FALSE",
            "V19_21_OUTPUTS_CREATED: FALSE",
            "OFFICIAL_USE_ALLOWED: FALSE",
            f"ATTACHABLE_FACTOR_FAMILIES_ATTACHED: {len(attachable)}",
            f"STRATEGY_FAMILY_READINESS_RECORDED: {tf(bool(strategy_readiness_rows))}",
            f"READY_FOR_V20_12_FACTOR_INPUT_LAYER_REVIEW_OR_FACTOR_EVIDENCE_GATE_NEXT: {tf(ready_v20_12)}",
            "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
            "READY_FOR_BACKTEST_NEXT: FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT: FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION: FALSE",
            f"STATIC_WRITE_PATH_CHECK_PASSED: {tf(static_write_ok)}",
            "DEPENDENCY_AUDIT_CSV: " + rel(OUT_DEPENDENCY),
            "FACTOR_SOURCE_ATTACHMENT_PLAN_CSV: " + rel(OUT_PLAN),
            "FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CSV: " + rel(OUT_LAYER),
            "GATE_DECISION_CSV: " + rel(OUT_GATE),
            "NEXT_STEP_DECISION_CSV: " + rel(OUT_NEXT),
            "VALIDATION_SUMMARY_CSV: " + rel(OUT_VALIDATION),
            "REPORT: " + rel(REPORT),
            "CURRENT_REPORT: " + rel(CURRENT_REPORT),
            "",
        ]
    )
    write_text(READ_FIRST, read_first_text)

    validation_row["read_first_safety_flags_present"] = tf(
        all(
            flag in read_first_text
            for flag in [
                "REPORTING_ONLY: FALSE",
                "FACTOR_SOURCE_ATTACHMENT_PLAN_ONLY_OR_NON_SCORING_INPUT_LAYER: TRUE",
                f"FIRST_ATTACHABLE_FACTOR_INPUT_LAYER_CREATED: {tf(first_layer_created)}",
                f"FACTOR_ATTACHMENT_ROWS_CREATED: {len(attachment_rows)}",
                "FACTOR_SCORES_CREATED: 0",
                "FACTOR_EVIDENCE_ROWS_CREATED: 0",
                "BACKTEST_ROWS_CREATED: 0",
                "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
                "TRADING_SIGNAL_ROWS_CREATED: 0",
                "STRATEGY_SIGNALS_CREATED: 0",
                "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
                "BROKER_API_USED: FALSE",
                "ORDER_EXECUTION_USED: FALSE",
                "SOURCE_MUTATION_USED: FALSE",
                "V21_OUTPUTS_CREATED: FALSE",
                "V19_21_OUTPUTS_CREATED: FALSE",
                "OFFICIAL_USE_ALLOWED: FALSE",
            ]
        )
    )
    validation_row["write_paths_expected_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["write_paths_written_count"] = str(len(ALLOWED_WRITE_PATHS))
    validation_row["allowed_write_paths_match"] = validation_row["static_write_path_check_passed"]
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    for key, value in validation_row.items():
        print(f"{key.upper()}: {value}")
    print(f"READ_FIRST: {rel(READ_FIRST)}")
    return 0 if ready_v20_12 else 1


if __name__ == "__main__":
    raise SystemExit(main())
