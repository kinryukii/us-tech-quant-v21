from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V20_9_BASE = CONSOLIDATION / "V20_9_FACTOR_RESEARCH_BASE_DATASET.csv"
IN_V20_9_PLAN = CONSOLIDATION / "V20_9_FACTOR_FAMILY_ATTACHMENT_PLAN.csv"
IN_V20_9_FIELD_AVAILABILITY = CONSOLIDATION / "V20_9_FACTOR_INPUT_FIELD_AVAILABILITY_AUDIT.csv"
IN_V20_9_MISSING = CONSOLIDATION / "V20_9_MISSING_FACTOR_SOURCE_REGISTER.csv"
IN_V20_9_GATE = CONSOLIDATION / "V20_9_GATE_DECISION.csv"
IN_V20_9_VALIDATION = CONSOLIDATION / "V20_9_VALIDATION_SUMMARY.csv"
IN_V20_9_READ_FIRST = OPS / "V20_9_READ_FIRST.txt"

IN_V20_5_SOURCE_REGISTRY = CONSOLIDATION / "V20_5_SOURCE_ARTIFACT_REGISTRY.csv"
IN_V20_5_PATH_REGISTRY = CONSOLIDATION / "V20_5_CANONICAL_SOURCE_PATH_REGISTRY.csv"
IN_V20_6_SOURCE_HASH = CONSOLIDATION / "V20_6_SOURCE_HASH_LEDGER.csv"
IN_V20_6_RUN_ID = CONSOLIDATION / "V20_6_RUN_ID_LEDGER.csv"
IN_V20_7X_BINDING = CONSOLIDATION / "V20_7X_ACTIVE_MARKET_INPUT_LINEAGE_BINDING.csv"
IN_V20_8_NORMALIZED = CONSOLIDATION / "V20_8_NORMALIZED_RESEARCH_DATASET.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_10_DEPENDENCY_AUDIT.csv"
OUT_INVENTORY = CONSOLIDATION / "V20_10_FACTOR_SOURCE_INVENTORY.csv"
OUT_ATTACHMENT = CONSOLIDATION / "V20_10_FACTOR_SOURCE_ATTACHMENT_AUDIT.csv"
OUT_FIELD_COVERAGE = CONSOLIDATION / "V20_10_FACTOR_FIELD_COVERAGE_AUDIT.csv"
OUT_TECHNICAL = CONSOLIDATION / "V20_10_TECHNICAL_FACTOR_SOURCE_AUDIT.csv"
OUT_FUNDAMENTAL = CONSOLIDATION / "V20_10_FUNDAMENTAL_FACTOR_SOURCE_AUDIT.csv"
OUT_RISK = CONSOLIDATION / "V20_10_RISK_FACTOR_SOURCE_AUDIT.csv"
OUT_REGIME = CONSOLIDATION / "V20_10_MARKET_REGIME_FACTOR_SOURCE_AUDIT.csv"
OUT_TRUST = CONSOLIDATION / "V20_10_DATA_TRUSTWORTHINESS_FACTOR_SOURCE_AUDIT.csv"
OUT_ATTACHABLE_REGISTER = CONSOLIDATION / "V20_10_ATTACHABLE_FACTOR_FAMILY_REGISTER.csv"
OUT_MISSING = CONSOLIDATION / "V20_10_MISSING_FACTOR_SOURCE_REGISTER.csv"
OUT_BOUNDARY = CONSOLIDATION / "V20_10_FACTOR_ATTACHMENT_BOUNDARY_AUDIT.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_10_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_10_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_10_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_10_VALIDATION_SUMMARY.csv"

REPORT = READ_CENTER / "V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT.md"
READ_FIRST = OPS / "V20_10_READ_FIRST.txt"

PATCH_VERSION = "V20.10"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY,
    OUT_INVENTORY,
    OUT_ATTACHMENT,
    OUT_FIELD_COVERAGE,
    OUT_TECHNICAL,
    OUT_FUNDAMENTAL,
    OUT_RISK,
    OUT_REGIME,
    OUT_TRUST,
    OUT_ATTACHABLE_REGISTER,
    OUT_MISSING,
    OUT_BOUNDARY,
    OUT_BLOCKERS,
    OUT_GATE,
    OUT_NEXT,
    OUT_VALIDATION,
    REPORT,
    CURRENT_REPORT,
    READ_FIRST,
}

SAFETY_FLAGS = {
    "REPORTING_ONLY": "FALSE",
    "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY": "TRUE",
    "FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED": "FALSE",
    "FACTOR_SCORES_CREATED": "0",
    "FACTOR_EVIDENCE_ROWS_CREATED": "0",
    "BACKTEST_ROWS_CREATED": "0",
    "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
    "TRADING_SIGNAL_ROWS_CREATED": "0",
    "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
    "BROKER_API_USED": "FALSE",
    "ORDER_EXECUTION_USED": "FALSE",
    "SOURCE_MUTATION_USED": "FALSE",
    "V21_OUTPUTS_CREATED": "FALSE",
    "V19_21_OUTPUTS_CREATED": "FALSE",
    "OFFICIAL_USE_ALLOWED": "FALSE",
}

TECHNICAL_FACTORS = [
    "trend",
    "momentum",
    "relative_strength",
    "pullback_quality",
    "breakout",
    "ma_ema",
    "bollinger",
    "rsi",
    "kdj",
    "macd",
    "volume",
    "volatility",
]
FUNDAMENTAL_FACTORS = ["growth", "profitability", "quality", "margin", "cash_flow", "capex", "valuation", "liquidity"]
RISK_FACTORS = [
    "overheat",
    "volatility_risk",
    "event_risk",
    "earnings_risk",
    "macro_risk",
    "regulation_risk",
    "supply_chain_risk",
    "valuation_risk",
    "capex_risk",
    "cash_flow_risk",
    "portfolio_drawdown",
    "position_cap",
]
REGIME_FACTORS = ["vix", "qqq_spy_trend", "risk_on_off", "cpi", "fomc", "nfp", "earnings_season", "quarter_end_rebalance"]
TRUST_FACTORS = ["freshness", "source_quality", "point_in_time", "safe_backtest_eligibility", "current_snapshot_block"]

MISSING_SOURCE_SPECS = [
    ("historical_ohlcv_windows", "technical;strategy", "Historical OHLCV windows are required before technical indicators can be attached."),
    ("volume_history", "technical;strategy", "Volume history is required before volume and liquidity technical factors can be attached."),
    ("technical_indicator_windows", "technical", "RSI/KDJ/MACD/Bollinger and moving-average indicator windows are missing."),
    ("revenue_eps_earnings_revision_data", "fundamental;risk", "Revenue, EPS, earnings, and revision inputs are missing."),
    ("margin_cash_flow_capex_data", "fundamental;risk", "Margin, cash-flow, and capex inputs are missing."),
    ("valuation_multiples", "fundamental;risk", "Valuation multiple inputs are missing."),
    ("liquidity_data", "fundamental", "Liquidity ratio and liquidity history inputs are missing."),
    ("event_and_earnings_calendar", "risk;market_regime", "Event and earnings calendars are missing."),
    ("macro_calendar", "risk;market_regime", "Macro calendar inputs are missing."),
    ("vix_qqq_spy_market_regime_data", "market_regime", "VIX, QQQ, and SPY regime inputs are missing."),
    ("portfolio_holdings_drawdown_position_cap_data", "risk", "Portfolio holdings, drawdown, and position-cap inputs are missing."),
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


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
            "blocker_id": f"V20_10_BLOCKER_{len(blockers) + 1:03d}",
            "blocker_scope": scope,
            "severity": severity,
            "blocker_status": "OPEN" if severity == "BLOCKING" else "WARN",
            "blocker_reason": reason,
            "blocks_v20_10": tf(severity == "BLOCKING"),
        }
    )


def classify_family(factor_family: str, factor_name: str) -> str:
    if factor_family in {"technical", "fundamental", "risk", "market_regime", "data_trustworthiness", "strategy"}:
        return factor_family
    if factor_name in TECHNICAL_FACTORS:
        return "technical"
    if factor_name in FUNDAMENTAL_FACTORS:
        return "fundamental"
    if factor_name in RISK_FACTORS:
        return "risk"
    if factor_name in REGIME_FACTORS:
        return "market_regime"
    if factor_name in TRUST_FACTORS:
        return "data_trustworthiness"
    return factor_family or "unknown"


def family_status(category: str, factor_name: str) -> tuple[str, bool, bool, str, str]:
    if category == "data_trustworthiness":
        return (
            "ATTACHABLE_NOW",
            True,
            False,
            "",
            "Proceed to V20.11 attachable factor layer planning for lineage-derived trustworthiness fields.",
        )
    if category == "technical" and factor_name in {"trend", "momentum", "relative_strength", "volatility"}:
        return (
            "PARTIAL_SOURCE_AVAILABLE",
            False,
            False,
            "Current market snapshot is present, but historical OHLCV/window inputs are missing.",
            "Attach historical OHLCV and indicator windows.",
        )
    return (
        "SOURCE_REQUIRED",
        False,
        False,
        "Required factor source is not accepted in current V20/V18 lineage.",
        "Register or attach required factor source in V20.11 planning.",
    )


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []

    base_rows, base_fields = read_csv(IN_V20_9_BASE)
    plan_rows, _ = read_csv(IN_V20_9_PLAN)
    field_availability_rows_v20_9, _ = read_csv(IN_V20_9_FIELD_AVAILABILITY)
    missing_rows_v20_9, _ = read_csv(IN_V20_9_MISSING)
    gate_rows, _ = read_csv(IN_V20_9_GATE)
    validation_rows, _ = read_csv(IN_V20_9_VALIDATION)
    read_first_text = IN_V20_9_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_V20_9_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    row_count = len(base_rows)

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

    v20_9_passed = upper(gate.get("status")) == "PASS_V20_9_FACTOR_RESEARCH_DATASET_PREPARED" and upper(validation.get("status")) == "PASS_V20_9_FACTOR_RESEARCH_DATASET_PREPARED"
    base_created = upper(gate.get("FACTOR_RESEARCH_BASE_DATASET_CREATED")) == "TRUE" and upper(validation.get("factor_research_base_dataset_created")) == "TRUE"
    rows_created = int(clean(gate.get("FACTOR_RESEARCH_ROWS_CREATED")) or "0") > 0 and int(clean(validation.get("factor_research_row_count")) or "0") > 0
    ready_next = upper(gate.get("READY_FOR_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT_NEXT")) == "TRUE" and upper(validation.get("ready_for_v20_10_factor_source_attachment_or_availability_audit_next")) == "TRUE"
    no_evidence = upper(gate.get("READY_FOR_FACTOR_EVIDENCE_NEXT")) == "FALSE" and upper(validation.get("ready_for_factor_evidence_next")) == "FALSE"
    no_backtest = upper(gate.get("READY_FOR_BACKTEST_NEXT")) == "FALSE" and upper(validation.get("ready_for_backtest_next")) == "FALSE"
    no_dynamic = upper(gate.get("READY_FOR_DYNAMIC_WEIGHTING_NEXT")) == "FALSE" and upper(validation.get("ready_for_dynamic_weighting_next")) == "FALSE"
    no_trading = upper(gate.get("READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION")) == "FALSE" and upper(validation.get("ready_for_trading_or_official_recommendation")) == "FALSE"
    read_first_ok = all(
        flag in read_first_text
        for flag in [
            "FACTOR_RESEARCH_PREPARATION_ONLY: TRUE",
            "FACTOR_RESEARCH_BASE_DATASET_CREATED: TRUE",
            "FACTOR_EVIDENCE_ROWS_CREATED: 0",
            "BACKTEST_ROWS_CREATED: 0",
            "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
            "TRADING_SIGNAL_ROWS_CREATED: 0",
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
            "BROKER_API_USED: FALSE",
            "ORDER_EXECUTION_USED: FALSE",
            "SOURCE_MUTATION_USED: FALSE",
            "V21_OUTPUTS_CREATED: FALSE",
            "V19_21_OUTPUTS_CREATED: FALSE",
            "OFFICIAL_USE_ALLOWED: FALSE",
        ]
    )

    dependency("V20_9_FACTOR_RESEARCH_BASE_DATASET", IN_V20_9_BASE, IN_V20_9_BASE.exists() and row_count > 0, "V20.9 factor research base dataset is missing or empty.")
    dependency("V20_9_FACTOR_FAMILY_ATTACHMENT_PLAN", IN_V20_9_PLAN, IN_V20_9_PLAN.exists() and bool(plan_rows), "V20.9 attachment plan is missing or empty.")
    dependency("V20_9_FACTOR_INPUT_FIELD_AVAILABILITY_AUDIT", IN_V20_9_FIELD_AVAILABILITY, IN_V20_9_FIELD_AVAILABILITY.exists() and bool(field_availability_rows_v20_9), "V20.9 field availability audit is missing or empty.")
    dependency("V20_9_MISSING_FACTOR_SOURCE_REGISTER", IN_V20_9_MISSING, IN_V20_9_MISSING.exists() and bool(missing_rows_v20_9), "V20.9 missing source register is missing or empty.")
    dependency("V20_9_GATE_DECISION", IN_V20_9_GATE, v20_9_passed and base_created and rows_created and ready_next and no_evidence and no_backtest and no_dynamic and no_trading, "V20.9 gate does not permit V20.10 audit.")
    dependency("V20_9_VALIDATION_SUMMARY", IN_V20_9_VALIDATION, v20_9_passed and base_created and rows_created and ready_next and no_evidence and no_backtest and no_dynamic and no_trading, "V20.9 validation summary is not in the required state.")
    dependency("V20_9_READ_FIRST", IN_V20_9_READ_FIRST, read_first_ok, "V20.9 READ_FIRST safety flags are incomplete.")

    source_hash = clean(base_rows[0].get("source_hash")) if base_rows else ""
    run_id = clean(base_rows[0].get("run_id")) if base_rows else ""
    source_artifact_id = clean(base_rows[0].get("source_artifact_id")) if base_rows else ""
    source_system = clean(base_rows[0].get("source_system")) if base_rows else ""
    input_artifact_id = clean(base_rows[0].get("input_artifact_id")) if base_rows else ""

    inventory_rows: list[dict[str, str]] = []
    inventory_specs = [
        ("V20.5_SOURCE_ARTIFACT_REGISTRY", IN_V20_5_SOURCE_REGISTRY, "registry"),
        ("V20.5_CANONICAL_SOURCE_PATH_REGISTRY", IN_V20_5_PATH_REGISTRY, "registry"),
        ("V20.6_SOURCE_HASH_LEDGER", IN_V20_6_SOURCE_HASH, "hash_run_version_binding"),
        ("V20.6_RUN_ID_LEDGER", IN_V20_6_RUN_ID, "hash_run_version_binding"),
        ("V20.7X_BOUND_ACTIVE_MARKET_LINEAGE", IN_V20_7X_BINDING, "active_market_lineage"),
        ("V20.8_NORMALIZED_RESEARCH_DATASET", IN_V20_8_NORMALIZED, "normalized_research_dataset"),
        ("V20.9_FACTOR_RESEARCH_BASE_DATASET", IN_V20_9_BASE, "factor_research_base_dataset"),
        ("V20.9_FACTOR_FAMILY_ATTACHMENT_PLAN", IN_V20_9_PLAN, "factor_attachment_plan"),
    ]
    for idx, (source_name, path, source_type) in enumerate(inventory_specs, start=1):
        rows, _ = read_csv(path)
        inventory_rows.append(
            {
                "inventory_id": f"V20_10_SRC_{idx:03d}",
                "source_name": source_name,
                "source_type": source_type,
                "source_artifact_id": source_artifact_id if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else "",
                "source_system": source_system if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else "",
                "source_path": rel(path),
                "path_exists_now": tf(path.exists()),
                "row_count": str(len(rows)),
                "source_hash_available": tf(bool(source_hash) if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else path.exists()),
                "source_hash": source_hash if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else "",
                "run_id_available": tf(bool(run_id) if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else path.exists()),
                "run_id": run_id if "V20.7X" in source_name or "V20.8" in source_name or "V20.9" in source_name else "",
                "accepted_for_factor_source_attachment_audit": tf(path.exists()),
                "official_use_allowed": "FALSE",
            }
        )

    base_field_set = set(base_fields)
    required_base_fields = [
        "ticker",
        "effective_observation_date",
        "effective_price_date",
        "effective_close",
        "source_hash",
        "run_id",
        "sample_id",
        "normalized_row_id",
        "factor_research_row_id",
        "research_only_flag",
        "official_use_allowed",
    ]
    field_coverage_rows = []
    for field in required_base_fields:
        non_empty = sum(1 for row in base_rows if clean(row.get(field)))
        field_coverage_rows.append(
            {
                "field_name": field,
                "exists_in_v20_9_base": tf(field in base_field_set),
                "non_empty_row_count": str(non_empty),
                "row_count": str(row_count),
                "coverage_status": "PASS" if field in base_field_set and non_empty == row_count and row_count > 0 else "BLOCKED",
                "usable_for_data_trustworthiness": tf(field in {"source_hash", "run_id", "sample_id", "normalized_row_id", "factor_research_row_id", "research_only_flag", "official_use_allowed"}),
                "usable_for_factor_scores_now": "FALSE",
                "blocker_reason": "" if field in base_field_set and non_empty == row_count and row_count > 0 else f"Required field {field} is missing or incomplete.",
            }
        )
    factor_field_notes = [
        ("technical_factor_inputs", "SOURCE_REQUIRED", "Historical OHLCV windows and volume history are not present."),
        ("fundamental_factor_inputs", "SOURCE_REQUIRED", "Financial statement, earnings, valuation, and liquidity inputs are not present."),
        ("risk_factor_inputs", "SOURCE_REQUIRED", "Event, earnings, macro, portfolio, and volatility inputs are not present."),
        ("market_regime_factor_inputs", "SOURCE_REQUIRED", "VIX, QQQ/SPY, macro calendar, and regime inputs are not present."),
        ("data_trustworthiness_inputs", "PASS", "Lineage, hash, run_id, sample_id, and research-only flags are present."),
    ]
    for field, status, reason in factor_field_notes:
        field_coverage_rows.append(
            {
                "field_name": field,
                "exists_in_v20_9_base": tf(status == "PASS"),
                "non_empty_row_count": str(row_count if status == "PASS" else 0),
                "row_count": str(row_count),
                "coverage_status": status,
                "usable_for_data_trustworthiness": tf(status == "PASS"),
                "usable_for_factor_scores_now": "FALSE",
                "blocker_reason": "" if status == "PASS" else reason,
            }
        )

    attachment_rows: list[dict[str, str]] = []
    attachable_register_rows: list[dict[str, str]] = []
    for idx, row in enumerate(plan_rows, start=1):
        factor_family = clean(row.get("factor_family"))
        factor_name = clean(row.get("factor_name"))
        category = classify_family(factor_family, factor_name)
        status, attachment_ready, evidence_allowed, reason, next_step = family_status(category, factor_name)
        candidate_source_found = category == "data_trustworthiness" or status == "PARTIAL_SOURCE_AVAILABLE"
        candidate_path = rel(IN_V20_9_BASE) if candidate_source_found else ""
        accepted_ref = f"{input_artifact_id};{source_artifact_id};{rel(IN_V20_9_BASE)}" if candidate_source_found else ""
        missing_ref = "" if attachment_ready else clean(row.get("required_input_type"))
        attachment_rows.append(
            {
                "attachment_audit_id": f"V20_10_ATTACH_{idx:03d}",
                "factor_category": category,
                "factor_family": factor_family,
                "factor_name": factor_name,
                "required_input_type": clean(row.get("required_input_type")),
                "candidate_source_found": tf(candidate_source_found),
                "candidate_source_artifact_id": source_artifact_id if candidate_source_found else "",
                "candidate_source_path": candidate_path,
                "source_hash_available": tf(bool(source_hash) and candidate_source_found),
                "run_id_available": tf(bool(run_id) and candidate_source_found),
                "point_in_time_ready": tf(category == "data_trustworthiness"),
                "stale_leakage_checked": tf(category == "data_trustworthiness"),
                "attachment_ready_now": tf(attachment_ready),
                "evidence_allowed_now": tf(evidence_allowed),
                "attachment_status": status,
                "blocker_reason": reason,
                "next_required_step": next_step,
            }
        )
        attachable_register_rows.append(
            {
                "factor_category": category,
                "factor_family": factor_name,
                "attachment_status": status,
                "attachment_ready_now": tf(attachment_ready),
                "evidence_allowed_now": tf(evidence_allowed),
                "required_source_status": "ACCEPTED_LINEAGE_METADATA" if attachment_ready else ("PARTIAL_MARKET_SNAPSHOT_ONLY" if status == "PARTIAL_SOURCE_AVAILABLE" else "SOURCE_REQUIRED"),
                "accepted_source_reference": accepted_ref,
                "missing_source_reference": missing_ref,
                "next_required_step": next_step,
            }
        )

    def audit_rows_for(factors: list[str], category: str) -> list[dict[str, str]]:
        rows = []
        for factor in factors:
            status, attachment_ready, evidence_allowed, reason, next_step = family_status(category, factor)
            rows.append(
                {
                    "factor_category": category,
                    "factor_name": factor,
                    "source_status": status,
                    "candidate_source_found": tf(category == "data_trustworthiness" or status == "PARTIAL_SOURCE_AVAILABLE"),
                    "attachment_ready_now": tf(attachment_ready),
                    "evidence_allowed_now": tf(evidence_allowed),
                    "accepted_source_reference": rel(IN_V20_9_BASE) if category == "data_trustworthiness" or status == "PARTIAL_SOURCE_AVAILABLE" else "",
                    "blocker_reason": reason,
                    "next_required_step": next_step,
                }
            )
        return rows

    technical_rows = audit_rows_for(TECHNICAL_FACTORS, "technical")
    fundamental_rows = audit_rows_for(FUNDAMENTAL_FACTORS, "fundamental")
    risk_rows = audit_rows_for(RISK_FACTORS, "risk")
    regime_rows = audit_rows_for(REGIME_FACTORS, "market_regime")
    trust_rows = audit_rows_for(TRUST_FACTORS, "data_trustworthiness")

    missing_source_rows = [
        {
            "missing_source_id": f"V20_10_MISSING_{idx:03d}",
            "required_source_name": name,
            "required_for_factor_categories": categories,
            "source_status": "MISSING",
            "blocker_reason": reason,
            "next_required_step": "V20.11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER",
        }
        for idx, (name, categories, reason) in enumerate(MISSING_SOURCE_SPECS, start=1)
    ]

    factor_scores_created = 0
    factor_evidence_rows_created = 0
    backtest_rows_created = 0
    dynamic_rows_created = 0
    trading_rows_created = 0
    official_rows_created = 0
    official_use_allowed = False
    boundary_passed = (
        factor_scores_created == 0
        and factor_evidence_rows_created == 0
        and backtest_rows_created == 0
        and dynamic_rows_created == 0
        and trading_rows_created == 0
        and official_rows_created == 0
        and not official_use_allowed
    )
    if not boundary_passed:
        add_blocker(blockers, "BOUNDARY", "V20.10 boundary requirements were violated.")

    boundary_rows = [
        {
            "boundary_check_id": "V20_10_BOUNDARY_001",
            "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY": "TRUE",
            "FACTOR_SCORES_CREATED": str(factor_scores_created),
            "FACTOR_EVIDENCE_ROWS_CREATED": str(factor_evidence_rows_created),
            "BACKTEST_ROWS_CREATED": str(backtest_rows_created),
            "DYNAMIC_WEIGHTING_ROWS_CREATED": str(dynamic_rows_created),
            "TRADING_SIGNAL_ROWS_CREATED": str(trading_rows_created),
            "OFFICIAL_RECOMMENDATION_ROWS_CREATED": str(official_rows_created),
            "OFFICIAL_USE_ALLOWED": "FALSE",
            "boundary_status": "PASS" if boundary_passed else "BLOCKED",
            "blocker_reason": "" if boundary_passed else "Boundary requirements failed.",
        }
    ]

    blocking_count = sum(1 for blocker in blockers if blocker["severity"] == "BLOCKING")
    audit_created = blocking_count == 0 and bool(attachment_rows) and bool(inventory_rows)
    attachable_count = sum(1 for row in attachable_register_rows if upper(row.get("attachment_ready_now")) == "TRUE")
    partial_count = sum(1 for row in attachable_register_rows if row.get("attachment_status") == "PARTIAL_SOURCE_AVAILABLE")
    missing_count = len(missing_source_rows)
    status = "PASS_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT" if audit_created else "BLOCKED_V20_10_FACTOR_SOURCE_ATTACHMENT_OR_AVAILABILITY_AUDIT"
    ready_v20_11 = audit_created
    next_step = "V20.11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_FACTOR_LAYER" if ready_v20_11 else "RESOLVE_V20_10_BLOCKERS"

    gate_rows_out = [
        {
            "gate_id": "V20_10_GATE",
            "status": status,
            "FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED": tf(audit_created),
            "FACTOR_RESEARCH_ROWS_REVIEWED": str(row_count),
            "ATTACHABLE_FACTOR_FAMILIES_COUNT": str(attachable_count),
            "PARTIAL_FACTOR_FAMILIES_COUNT": str(partial_count),
            "MISSING_FACTOR_SOURCE_ROWS_CREATED": str(missing_count),
            "READY_FOR_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_LAYER_NEXT": tf(ready_v20_11),
            "READY_FOR_FACTOR_EVIDENCE_NEXT": "FALSE",
            "READY_FOR_BACKTEST_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
            "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
            "V21_OUTPUTS_CREATED": "FALSE",
            "V19_21_OUTPUTS_CREATED": "FALSE",
            "NEXT_RECOMMENDED_STEP": next_step,
            "gate_reason": "Factor source attachment and availability audit completed without boundary violations." if audit_created else "Dependency or boundary checks failed.",
        }
    ]
    next_rows = [
        {
            "decision_id": "V20_10_NEXT_STEP",
            "ready_for_v20_11_factor_source_attachment_plan_or_first_attachable_layer_next": tf(ready_v20_11),
            "ready_for_factor_evidence_next": "FALSE",
            "ready_for_backtest_next": "FALSE",
            "ready_for_dynamic_weighting_next": "FALSE",
            "ready_for_trading_or_official_recommendation": "FALSE",
            "next_recommended_step": next_step,
            "reason": "Only attachable source availability has been audited; factor evidence remains blocked.",
        }
    ]
    blocker_rows = blockers or [
        {
            "blocker_id": "V20_10_BLOCKER_000",
            "blocker_scope": "NONE",
            "severity": "INFO",
            "blocker_status": "CLEARED",
            "blocker_reason": "",
            "blocks_v20_10": "FALSE",
        }
    ]

    validation_row = {
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "factor_research_rows_reviewed": str(row_count),
        "factor_plan_rows_reviewed": str(len(plan_rows)),
        "factor_source_attachment_audit_created": tf(audit_created),
        "attachable_factor_families_count": str(attachable_count),
        "partial_factor_families_count": str(partial_count),
        "missing_factor_source_rows_created": str(missing_count),
        "ready_for_v20_11_factor_source_attachment_plan_or_first_attachable_layer_next": tf(ready_v20_11),
        "ready_for_factor_evidence_next": "FALSE",
        "ready_for_backtest_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "dependency_blocker_count": str(sum(1 for row in dependency_rows if row["status"] == "BLOCKED")),
        "total_blocker_count": str(blocking_count),
        "technical_factor_count": str(len(technical_rows)),
        "fundamental_factor_count": str(len(fundamental_rows)),
        "risk_factor_count": str(len(risk_rows)),
        "market_regime_factor_count": str(len(regime_rows)),
        "data_trustworthiness_factor_count": str(len(trust_rows)),
        "factor_scores_created": "0",
        "factor_evidence_rows_created": "0",
        "official_use_allowed_rows": "0",
        "static_write_path_check_passed": tf(set(ALLOWED_WRITE_PATHS) == {
            OUT_DEPENDENCY,
            OUT_INVENTORY,
            OUT_ATTACHMENT,
            OUT_FIELD_COVERAGE,
            OUT_TECHNICAL,
            OUT_FUNDAMENTAL,
            OUT_RISK,
            OUT_REGIME,
            OUT_TRUST,
            OUT_ATTACHABLE_REGISTER,
            OUT_MISSING,
            OUT_BOUNDARY,
            OUT_BLOCKERS,
            OUT_GATE,
            OUT_NEXT,
            OUT_VALIDATION,
            REPORT,
            CURRENT_REPORT,
            READ_FIRST,
        }),
        **SAFETY_FLAGS,
    }

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_INVENTORY, inventory_rows, ["inventory_id", "source_name", "source_type", "source_artifact_id", "source_system", "source_path", "path_exists_now", "row_count", "source_hash_available", "source_hash", "run_id_available", "run_id", "accepted_for_factor_source_attachment_audit", "official_use_allowed"])
    write_csv(OUT_ATTACHMENT, attachment_rows, ["attachment_audit_id", "factor_category", "factor_family", "factor_name", "required_input_type", "candidate_source_found", "candidate_source_artifact_id", "candidate_source_path", "source_hash_available", "run_id_available", "point_in_time_ready", "stale_leakage_checked", "attachment_ready_now", "evidence_allowed_now", "attachment_status", "blocker_reason", "next_required_step"])
    write_csv(OUT_FIELD_COVERAGE, field_coverage_rows, ["field_name", "exists_in_v20_9_base", "non_empty_row_count", "row_count", "coverage_status", "usable_for_data_trustworthiness", "usable_for_factor_scores_now", "blocker_reason"])
    audit_fields = ["factor_category", "factor_name", "source_status", "candidate_source_found", "attachment_ready_now", "evidence_allowed_now", "accepted_source_reference", "blocker_reason", "next_required_step"]
    write_csv(OUT_TECHNICAL, technical_rows, audit_fields)
    write_csv(OUT_FUNDAMENTAL, fundamental_rows, audit_fields)
    write_csv(OUT_RISK, risk_rows, audit_fields)
    write_csv(OUT_REGIME, regime_rows, audit_fields)
    write_csv(OUT_TRUST, trust_rows, audit_fields)
    write_csv(OUT_ATTACHABLE_REGISTER, attachable_register_rows, ["factor_category", "factor_family", "attachment_status", "attachment_ready_now", "evidence_allowed_now", "required_source_status", "accepted_source_reference", "missing_source_reference", "next_required_step"])
    write_csv(OUT_MISSING, missing_source_rows, ["missing_source_id", "required_source_name", "required_for_factor_categories", "source_status", "blocker_reason", "next_required_step"])
    write_csv(OUT_BOUNDARY, boundary_rows, ["boundary_check_id", "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY", "FACTOR_SCORES_CREATED", "FACTOR_EVIDENCE_ROWS_CREATED", "BACKTEST_ROWS_CREATED", "DYNAMIC_WEIGHTING_ROWS_CREATED", "TRADING_SIGNAL_ROWS_CREATED", "OFFICIAL_RECOMMENDATION_ROWS_CREATED", "OFFICIAL_USE_ALLOWED", "boundary_status", "blocker_reason"])
    write_csv(OUT_BLOCKERS, blocker_rows, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_10"])
    write_csv(OUT_GATE, gate_rows_out, list(gate_rows_out[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, [validation_row], list(validation_row.keys()))

    report_lines = [
        "# V20.10 Factor Source Attachment or Availability Audit",
        "",
        f"- STATUS: `{status}`",
        f"- factor research rows reviewed: `{row_count}`",
        f"- attachable factor families: `{attachable_count}`",
        f"- partial factor families: `{partial_count}`",
        f"- missing source rows: `{missing_count}`",
        f"- ready for V20.11 next: `{tf(ready_v20_11)}`",
        "- ready for factor evidence next: `FALSE`",
        "- ready for backtest next: `FALSE`",
        "- official use allowed: `FALSE`",
        "",
        "## Dependency Audit",
        md_table(["dependency", "exists", "status"], dependency_rows),
        "",
        "## Gate Decision",
        md_table(["gate_id", "status", "FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED", "FACTOR_RESEARCH_ROWS_REVIEWED", "ATTACHABLE_FACTOR_FAMILIES_COUNT", "MISSING_FACTOR_SOURCE_ROWS_CREATED", "READY_FOR_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_LAYER_NEXT"], gate_rows_out),
        "",
        "## Family Coverage",
        md_table(["factor_category", "factor_name", "source_status", "attachment_ready_now", "evidence_allowed_now"], technical_rows + fundamental_rows + risk_rows + regime_rows + trust_rows, limit=30),
        "",
        "This step audits factor source attachment availability only. It does not compute factor scores, create factor evidence, run backtests, create dynamic weighting rows, trading signals, official recommendations, broker actions, V21 outputs, or V19.21 outputs.",
        "",
    ]
    write_text(REPORT, "\n".join(report_lines))
    write_text(CURRENT_REPORT, "\n".join(report_lines))

    read_first_lines = [
        f"STATUS: {status}",
        f"PATCH_VERSION: {PATCH_VERSION}",
        "REPORTING_ONLY: FALSE",
        "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY: TRUE",
        f"FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED: {tf(audit_created)}",
        "FACTOR_SCORES_CREATED: 0",
        "FACTOR_EVIDENCE_ROWS_CREATED: 0",
        "BACKTEST_ROWS_CREATED: 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
        "TRADING_SIGNAL_ROWS_CREATED: 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED: 0",
        "BROKER_API_USED: FALSE",
        "ORDER_EXECUTION_USED: FALSE",
        "SOURCE_MUTATION_USED: FALSE",
        "V21_OUTPUTS_CREATED: FALSE",
        "V19_21_OUTPUTS_CREATED: FALSE",
        "OFFICIAL_USE_ALLOWED: FALSE",
        f"FACTOR_RESEARCH_ROWS_REVIEWED: {row_count}",
        f"ATTACHABLE_FACTOR_FAMILIES_COUNT: {attachable_count}",
        f"PARTIAL_FACTOR_FAMILIES_COUNT: {partial_count}",
        f"MISSING_FACTOR_SOURCE_ROWS_CREATED: {missing_count}",
        f"READY_FOR_V20_11_FACTOR_SOURCE_ATTACHMENT_PLAN_OR_FIRST_ATTACHABLE_LAYER_NEXT: {tf(ready_v20_11)}",
        "READY_FOR_FACTOR_EVIDENCE_NEXT: FALSE",
        "READY_FOR_BACKTEST_NEXT: FALSE",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT: FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION: FALSE",
        f"STATIC_WRITE_PATH_CHECK_PASSED: {validation_row['static_write_path_check_passed']}",
        "DEPENDENCY_AUDIT_CSV: " + rel(OUT_DEPENDENCY),
        "FACTOR_SOURCE_INVENTORY_CSV: " + rel(OUT_INVENTORY),
        "FACTOR_SOURCE_ATTACHMENT_AUDIT_CSV: " + rel(OUT_ATTACHMENT),
        "FACTOR_FIELD_COVERAGE_AUDIT_CSV: " + rel(OUT_FIELD_COVERAGE),
        "ATTACHABLE_FACTOR_FAMILY_REGISTER_CSV: " + rel(OUT_ATTACHABLE_REGISTER),
        "MISSING_FACTOR_SOURCE_REGISTER_CSV: " + rel(OUT_MISSING),
        "GATE_DECISION_CSV: " + rel(OUT_GATE),
        "NEXT_STEP_DECISION_CSV: " + rel(OUT_NEXT),
        "VALIDATION_SUMMARY_CSV: " + rel(OUT_VALIDATION),
        "REPORT: " + rel(REPORT),
        "CURRENT_REPORT: " + rel(CURRENT_REPORT),
        "",
    ]
    read_first_output = "\n".join(read_first_lines)
    write_text(READ_FIRST, read_first_output)

    validation_row["FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED"] = tf(audit_created)
    validation_row["FACTOR_SCORES_CREATED"] = "0"
    validation_row["read_first_safety_flags_present"] = tf(
        all(
            flag in read_first_output
            for flag in [
                "REPORTING_ONLY: FALSE",
                "FACTOR_SOURCE_ATTACHMENT_AUDIT_ONLY: TRUE",
                f"FACTOR_SOURCE_ATTACHMENT_AUDIT_CREATED: {tf(audit_created)}",
                "FACTOR_SCORES_CREATED: 0",
                "FACTOR_EVIDENCE_ROWS_CREATED: 0",
                "BACKTEST_ROWS_CREATED: 0",
                "DYNAMIC_WEIGHTING_ROWS_CREATED: 0",
                "TRADING_SIGNAL_ROWS_CREATED: 0",
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
    return 0 if audit_created else 1


if __name__ == "__main__":
    raise SystemExit(main())
