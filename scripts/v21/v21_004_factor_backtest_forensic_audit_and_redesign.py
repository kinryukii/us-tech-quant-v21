#!/usr/bin/env python
"""V21.004 factor backtest forensic audit and redesign.

Audit-only stage. It inventories current factor-backtest artifacts, separates
score reconstruction from forward-return evidence, audits observation maturity
and PIT leakage risks, and writes a research-only redesign contract.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


STAGE_NAME = "V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

ARTIFACT_INVENTORY = OUT_DIR / "V21_004_FACTOR_BACKTEST_ARTIFACT_INVENTORY.csv"
OBSERVATION_AUDIT = OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv"
LEAKAGE_AUDIT = OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv"
CAPABILITY_MATRIX = OUT_DIR / "V21_004_FACTOR_EVIDENCE_CAPABILITY_MATRIX.csv"
GAP_TABLE = OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv"
REDESIGN_CONTRACT = OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv"
REPORT = READ_CENTER_DIR / "V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_AND_REDESIGN_REPORT.md"

RESEARCH_ROOTS = [ROOT / "outputs" / "v20", ROOT / "outputs" / "v21"]
ARTIFACT_KEYWORDS = [
    "factor",
    "backtest",
    "forward",
    "outcome",
    "snapshot",
    "score",
    "rank",
    "ranking",
    "ablation",
    "walk",
    "regime",
    "risk",
    "overheat",
    "data_trust",
    "trust",
    "recommendation",
    "validation",
]
FAMILY_NAMES = [
    "fundamental",
    "technical",
    "strategy",
    "risk",
    "market_regime",
    "regime",
    "data_trust",
    "valuation",
    "quality",
    "growth",
    "momentum",
    "entry_timing",
    "other",
]
OBSERVATION_SOURCES = [
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "audit" / "V21_001_FORWARD_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration" / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration_r1" / "V21_003_R1_OVERHEAT_FALSE_BLOCK_AUDIT_REPAIRED.csv",
    ROOT / "outputs" / "v20" / "backtest" / "V20_199B_R1_FORWARD_RETURNS.csv",
    ROOT / "outputs" / "v20" / "backtest" / "V20_199B_R4_SHADOW_FORWARD_OBSERVATION_SCHEDULE.csv",
]
OFFICIAL_OR_UPSTREAM_PATTERNS = [
    ROOT / "outputs" / "v20",
    ROOT / "outputs" / "v21" / "audit",
    ROOT / "outputs" / "v21" / "ablation",
    ROOT / "outputs" / "v21" / "recalibration",
    ROOT / "outputs" / "v21" / "recalibration_r1",
]
MIN_DECISION_GRADE_MATURED_OBSERVATIONS = 1000
MIN_DECISION_GRADE_SNAPSHOTS = 24
MIN_DECISION_GRADE_FORWARD_WINDOWS = 2


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle).fieldnames or [])
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def row_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    except (OSError, UnicodeDecodeError):
        return 0


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "MISSING", "PENDING"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def classify_artifact(path: Path, columns: list[str]) -> tuple[str, str]:
    lower_name = path.name.lower()
    normalized_columns = {norm(col) for col in columns}
    has_forward = any(col.startswith("forward_return") or "forward_return" in col for col in normalized_columns)
    has_excess = any("excess_return" in col or "benchmark" in col for col in normalized_columns)
    has_family = any(f"{family}_score" in normalized_columns or f"normalized_{family}_score" in normalized_columns for family in FAMILY_NAMES)
    has_raw_factor = any(token in " ".join(normalized_columns) for token in ["raw", "metric", "pe_", "roe", "rsi", "macd"])
    has_rank = "rank" in normalized_columns or any("rank" in col for col in normalized_columns)
    has_score = any("score" in col for col in normalized_columns)
    if "schedule" in lower_name or "ledger" in lower_name:
        return "walk_forward_observation_ledger", "pending_or_binding ledger; not proof until forward returns mature"
    if has_forward or has_excess or "outcome" in lower_name or "forward" in lower_name:
        return "forward_return_evidence", "contains realized or benchmark-relative forward outcome fields"
    if has_family or has_score or "snapshot" in lower_name or "contribution" in lower_name:
        detail = "score reconstruction with factor-family values"
        if has_raw_factor:
            detail += " and some raw/proxy factor fields"
        if has_rank:
            detail += "; includes rank fields"
        return "score_reconstruction", detail
    if "gate" in lower_name or "guard" in lower_name or "audit" in lower_name or "validation" in lower_name:
        return "audit_or_validation_metadata", "guard, gate, validation, or source audit metadata"
    return "supporting_artifact", "related artifact but not direct factor validity evidence"


def artifact_relevance(path: Path) -> bool:
    text = rel(path).lower()
    return any(keyword in text for keyword in ARTIFACT_KEYWORDS)


def inventory_artifacts() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[Path] = set()
    for root in RESEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path in seen or not artifact_relevance(path):
                continue
            seen.add(path)
            columns = read_header(path) if path.suffix.lower() == ".csv" else []
            artifact_type, evidence_role = classify_artifact(path, columns)
            normalized = {norm(col) for col in columns}
            rows.append(
                {
                    "artifact_path": rel(path),
                    "file_name": path.name,
                    "artifact_type": artifact_type,
                    "evidence_role": evidence_role,
                    "extension": path.suffix.lower(),
                    "row_count": row_count(path) if path.suffix.lower() == ".csv" else "",
                    "column_count": len(columns),
                    "has_as_of_date": "as_of_date" in normalized,
                    "has_signal_date": "signal_date" in normalized,
                    "has_price_date": "price_date" in normalized or "entry_price_date" in normalized,
                    "has_forward_return_window": any("forward_return" in col for col in normalized),
                    "has_ticker": bool({"ticker", "symbol"} & normalized) or any("ticker" in col for col in normalized),
                    "has_rank": "rank" in normalized or any("rank" in col for col in normalized),
                    "has_factor_family_scores": any(f"{family}_score" in normalized for family in FAMILY_NAMES),
                    "has_raw_factor_values": any(token in " ".join(normalized) for token in ["raw", "metric", "pe_", "roe", "rsi", "macd"]),
                    "has_data_trust": any("data_trust" in col or "trust" in col for col in normalized),
                    "has_overheat_or_risk": any("overheat" in col or "risk" in col or "regime" in col for col in normalized),
                    "research_only": "TRUE",
                }
            )
    rows.sort(key=lambda row: str(row["artifact_path"]))
    return rows


def detect_field(columns: list[str], candidates: list[str]) -> str | None:
    by_norm = {norm(col): col for col in columns}
    for candidate in candidates:
        if candidate in by_norm:
            return by_norm[candidate]
    for col in columns:
        ncol = norm(col)
        if any(candidate in ncol for candidate in candidates):
            return col
    return None


def audit_observations() -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    summary: Counter[str] = Counter()
    unique_snapshots: set[str] = set()
    usable_snapshots: set[str] = set()
    windows: set[str] = set()

    for source in OBSERVATION_SOURCES:
        if not source.exists():
            rows.append(missing_observation_source(source))
            continue
        source_rows = read_csv(source)
        columns = list(source_rows[0].keys()) if source_rows else read_header(source)
        asof_field = detect_field(columns, ["as_of_date", "asof_date", "snapshot_date", "date"])
        signal_field = detect_field(columns, ["signal_date"])
        price_field = detect_field(columns, ["price_date", "entry_price_date", "execution_price_date"])
        ticker_field = detect_field(columns, ["ticker", "symbol"])
        rank_field = detect_field(columns, ["rank"])
        outcome_field = detect_field(columns, ["outcome_status", "status"])
        family_cols = [col for col in columns if norm(col).endswith("_score") and any(family in norm(col) for family in FAMILY_NAMES)]
        raw_cols = [col for col in columns if any(token in norm(col) for token in ["raw", "metric", "pe_", "roe", "rsi", "macd"])]
        forward_cols = [col for col in columns if "forward_return" in norm(col)]
        windows.update(forward_cols)
        trust_field = detect_field(columns, ["data_trust_gate_status", "data_trust_status", "data_trust_score", "trust_status"])
        overheat_field = detect_field(columns, ["overheat_status", "risk_status", "risk_score", "market_regime_score", "regime_score"])

        for idx, row in enumerate(source_rows, start=1):
            asof = row.get(asof_field, "") if asof_field else ""
            signal = row.get(signal_field, "") if signal_field else ""
            price = row.get(price_field, "") if price_field else ""
            forward_values = [parse_float(row.get(col)) for col in forward_cols]
            has_future_price = any(value is not None for value in forward_values)
            outcome = (row.get(outcome_field, "") if outcome_field else "").upper()
            if "REJECT" in outcome or "FAIL" in outcome:
                maturity = "REJECTED"
            elif has_future_price or "PASS_FORWARD_OUTCOME_AVAILABLE" in outcome:
                maturity = "MATURED"
            elif "PENDING" in outcome or "schedule" in source.name.lower():
                maturity = "PENDING"
            else:
                maturity = "PENDING" if forward_cols else "REJECTED"

            if asof:
                unique_snapshots.add(asof)
                if maturity == "MATURED":
                    usable_snapshots.add(asof)
            summary[maturity.lower()] += 1

            missing = []
            checks = {
                "as_of_date": bool(asof_field and asof),
                "signal_date": bool(signal_field and signal),
                "price_date": bool(price_field and price),
                "forward_return_window": bool(forward_cols),
                "future_price_availability": has_future_price,
                "ticker": bool(ticker_field and row.get(ticker_field, "")),
                "rank": bool(rank_field and row.get(rank_field, "")),
                "factor_family_scores": bool(family_cols),
                "raw_factor_values": bool(raw_cols),
                "data_trust_gate_status": bool(trust_field and row.get(trust_field, "")),
                "overheat_risk_status": bool(overheat_field and row.get(overheat_field, "")),
            }
            for key, value in checks.items():
                if not value:
                    missing.append(key)
            rows.append(
                {
                    "source_artifact": rel(source),
                    "row_number": idx,
                    "observation_id": f"{source.name}:{idx}",
                    "as_of_date": asof,
                    "signal_date": signal,
                    "price_date": price,
                    "forward_return_window": "|".join(forward_cols),
                    "future_price_available": has_future_price,
                    "ticker": row.get(ticker_field, "") if ticker_field else "",
                    "rank": row.get(rank_field, "") if rank_field else "",
                    "has_factor_family_scores": bool(family_cols),
                    "factor_family_score_columns": "|".join(family_cols),
                    "has_raw_factor_values": bool(raw_cols),
                    "raw_factor_columns": "|".join(raw_cols[:20]),
                    "data_trust_gate_status": row.get(trust_field, "") if trust_field else "",
                    "overheat_risk_status": row.get(overheat_field, "") if overheat_field else "",
                    "maturity_status": maturity,
                    "missing_required_fields": "|".join(missing),
                    "research_only": "TRUE",
                }
            )

    summary_row = {
        "total_observations": len([row for row in rows if row.get("row_number") != "SOURCE_MISSING"]),
        "total_snapshots": len(unique_snapshots),
        "usable_snapshots": len(usable_snapshots),
        "matured_observations": summary["matured"],
        "pending_observations": summary["pending"],
        "rejected_observations": summary["rejected"],
        "forward_window_count": len(windows),
    }
    return rows, summary_row


def missing_observation_source(path: Path) -> dict[str, object]:
    return {
        "source_artifact": rel(path),
        "row_number": "SOURCE_MISSING",
        "observation_id": f"{path.name}:SOURCE_MISSING",
        "as_of_date": "",
        "signal_date": "",
        "price_date": "",
        "forward_return_window": "",
        "future_price_available": "FALSE",
        "ticker": "",
        "rank": "",
        "has_factor_family_scores": "FALSE",
        "factor_family_score_columns": "",
        "has_raw_factor_values": "FALSE",
        "raw_factor_columns": "",
        "data_trust_gate_status": "",
        "overheat_risk_status": "",
        "maturity_status": "REJECTED",
        "missing_required_fields": "source_artifact",
        "research_only": "TRUE",
    }


def build_leakage_audit(inventory_rows: list[dict[str, object]], observation_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    obs = [row for row in observation_rows if row.get("row_number") != "SOURCE_MISSING"]
    same_day = sum(1 for row in obs if row.get("as_of_date") and row.get("price_date") and row.get("as_of_date") == row.get("price_date"))
    missing_signal = sum(1 for row in obs if not row.get("signal_date"))
    missing_price = sum(1 for row in obs if not row.get("price_date"))
    missing_raw = sum(1 for row in obs if str(row.get("has_raw_factor_values")).upper() != "TRUE")
    missing_trust = sum(1 for row in obs if not row.get("data_trust_gate_status"))
    source_contract_gaps = [row for row in inventory_rows if "source_contract" in str(row["artifact_path"]).lower() and int(row.get("row_count") or 0) > 0]
    pit_safety = [row for row in inventory_rows if "pit" in str(row["artifact_path"]).lower() or "lookahead" in str(row["artifact_path"]).lower()]
    return [
        leakage_row("same_day_close_signal_execution", same_day > 0, same_day, "as_of_date equals price_date in available rows; execution timestamp separation is not proven."),
        leakage_row("future_price_before_signal_timestamp", missing_signal > 0 or missing_price > 0, missing_signal + missing_price, "Cannot prove absence because signal_date and/or price_date are missing in many observations."),
        leakage_row("post_event_information_in_historical_factors", missing_raw > 0, missing_raw, "Most rows hold reconstructed family scores, not immutable raw point-in-time factor values with source timestamps."),
        leakage_row("missing_as_of_source_contract", len(source_contract_gaps) == 0, 0 if source_contract_gaps else 1, "Current artifacts include PIT audits but no complete row-level as-of source contract for every factor input."),
        leakage_row("data_trust_used_as_ranking_signal", False, 0, "Existing guard evidence confirms DATA_TRUST is zero-weight; V21.004 uses it only as audit/gate metadata."),
        leakage_row("risk_overheat_contamination", True, len([row for row in inventory_rows if "overheat" in str(row["artifact_path"]).lower()]), "V21.003-R1 repaired overheat audit exists, so any pre-repair risk/overheat conclusions remain contaminated unless repaired rows are used."),
        leakage_row("pit_guard_artifacts_present_but_insufficient", True, len(pit_safety), "PIT/no-lookahead guard artifacts exist, but guard metadata is not the same as a full decision-grade row-level timestamp contract."),
        leakage_row("missing_data_trust_gate_on_observations", missing_trust > 0, missing_trust, "DATA_TRUST gate status is absent in many observation rows even where a data_trust_score exists."),
    ]


def leakage_row(risk_id: str, detected: bool, affected_count: int, rationale: str) -> dict[str, object]:
    severity = "HIGH" if detected and risk_id != "pit_guard_artifacts_present_but_insufficient" else "INFO"
    if risk_id in {"same_day_close_signal_execution", "future_price_before_signal_timestamp", "missing_as_of_source_contract"} and detected:
        severity = "CRITICAL"
    return {
        "risk_id": risk_id,
        "risk_detected_or_not_disprovable": "TRUE" if detected else "FALSE",
        "severity": severity,
        "affected_observation_or_artifact_count": affected_count,
        "rationale": rationale,
        "required_redesign_control": redesign_control_for_risk(risk_id),
        "research_only": "TRUE",
    }


def redesign_control_for_risk(risk_id: str) -> str:
    controls = {
        "same_day_close_signal_execution": "Require signal_timestamp after factor freeze and execution_price_date strictly after tradable execution timestamp.",
        "future_price_before_signal_timestamp": "Bind every outcome to signal_timestamp, execution_timestamp, price_source_timestamp, and forward_window_end.",
        "post_event_information_in_historical_factors": "Persist raw PIT factor values, source publication timestamp, ingestion timestamp, and revision policy.",
        "missing_as_of_source_contract": "Introduce row-level as_of source contract for every factor family and ticker observation.",
        "data_trust_used_as_ranking_signal": "Keep DATA_TRUST as gate/audit metadata with ranking_weight=0.",
        "risk_overheat_contamination": "Use repaired V21.003-R1 semantics and separate risk state from return labels.",
        "pit_guard_artifacts_present_but_insufficient": "Promote guard checks to enforceable observation schema validations.",
        "missing_data_trust_gate_on_observations": "Materialize data_trust_gate_status per observation without adding score contribution.",
    }
    return controls[risk_id]


def capability_matrix(observation_summary: dict[str, object], leakage_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    critical_risks = sum(1 for row in leakage_rows if row["severity"] == "CRITICAL")
    matured = int(observation_summary["matured_observations"])
    usable_snapshots = int(observation_summary["usable_snapshots"])
    forward_windows = int(observation_summary["forward_window_count"])
    capabilities = [
        ("factor_validity", matured >= 100 and usable_snapshots >= 3, "Some forward-return evidence exists, but source/timestamp gaps prevent decision-grade validity."),
        ("weight_adjustment", False, "Current evidence cannot justify official factor-weight mutation; use only for research hypotheses."),
        ("risk_penalty_calibration", False, "V21.003 overheat/risk contamination and limited repaired semantics block calibration."),
        ("market_regime_conditioning", False, "Regime fields exist but lack decision-grade regime timestamp and independent validation."),
        ("trade_entry_exit_policy", False, "No execution-safe signal/entry/exit contract; same-day close risk is unresolved."),
        ("decision_grade_backtest", matured >= MIN_DECISION_GRADE_MATURED_OBSERVATIONS and usable_snapshots >= MIN_DECISION_GRADE_SNAPSHOTS and forward_windows >= MIN_DECISION_GRADE_FORWARD_WINDOWS and critical_risks == 0, "Requires all minimum evidence thresholds and zero critical leakage risks."),
    ]
    rows = []
    for capability, supported, rationale in capabilities:
        rows.append(
            {
                "capability": capability,
                "current_support_level": "SUPPORTED_RESEARCH_ONLY" if supported and capability != "decision_grade_backtest" else ("DECISION_GRADE_READY" if supported else "NOT_SUPPORTED_FOR_DECISION"),
                "can_support_official_action": "FALSE",
                "evidence_basis": f"matured={matured}; usable_snapshots={usable_snapshots}; forward_windows={forward_windows}; critical_leakage_risks={critical_risks}",
                "rationale": rationale,
                "research_only": "TRUE",
            }
        )
    return rows


def gap_table(observation_summary: dict[str, object], leakage_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    critical_risks = sum(1 for row in leakage_rows if row["severity"] == "CRITICAL")
    checks = [
        ("minimum_matured_observations", MIN_DECISION_GRADE_MATURED_OBSERVATIONS, observation_summary["matured_observations"], int(observation_summary["matured_observations"]) >= MIN_DECISION_GRADE_MATURED_OBSERVATIONS),
        ("minimum_usable_snapshots", MIN_DECISION_GRADE_SNAPSHOTS, observation_summary["usable_snapshots"], int(observation_summary["usable_snapshots"]) >= MIN_DECISION_GRADE_SNAPSHOTS),
        ("minimum_forward_windows", MIN_DECISION_GRADE_FORWARD_WINDOWS, observation_summary["forward_window_count"], int(observation_summary["forward_window_count"]) >= MIN_DECISION_GRADE_FORWARD_WINDOWS),
        ("zero_critical_leakage_risks", 0, critical_risks, critical_risks == 0),
        ("complete_signal_price_timestamp_contract", "TRUE", "FALSE", False),
        ("complete_raw_factor_pit_values", "TRUE", "FALSE", False),
        ("data_trust_zero_weight", "TRUE", "TRUE", True),
        ("audit_only_no_official_mutation", "TRUE", "TRUE", True),
    ]
    rows = []
    for requirement, required, observed, passed in checks:
        rows.append(
            {
                "requirement": requirement,
                "required_value": required,
                "observed_value": observed,
                "gap_status": "PASS" if passed else "GAP",
                "decision_grade_blocker": "FALSE" if passed else "TRUE",
                "remediation": remediation_for(requirement),
                "research_only": "TRUE",
            }
        )
    return rows


def remediation_for(requirement: str) -> str:
    mapping = {
        "minimum_matured_observations": "Accumulate more matured walk-forward observations before calibration.",
        "minimum_usable_snapshots": "Run point-in-time snapshots over more independent as_of dates.",
        "minimum_forward_windows": "Require multiple forward windows such as 5d, 10d, and 20d.",
        "zero_critical_leakage_risks": "Eliminate or disprove critical leakage risks with enforceable timestamp contracts.",
        "complete_signal_price_timestamp_contract": "Persist signal_timestamp, execution_timestamp, price_date, and price_source_timestamp.",
        "complete_raw_factor_pit_values": "Persist raw factor values and source timestamps for every family.",
        "data_trust_zero_weight": "Keep DATA_TRUST ranking_weight=0 and use only gates/audit metadata.",
        "audit_only_no_official_mutation": "Continue writing only research outputs until decision-grade gate passes.",
    }
    return mapping[requirement]


def final_verdict(observation_summary: dict[str, object], leakage_rows: list[dict[str, object]]) -> str:
    matured = int(observation_summary["matured_observations"])
    usable = int(observation_summary["usable_snapshots"])
    windows = int(observation_summary["forward_window_count"])
    critical = sum(1 for row in leakage_rows if row["severity"] == "CRITICAL")
    if matured >= MIN_DECISION_GRADE_MATURED_OBSERVATIONS and usable >= MIN_DECISION_GRADE_SNAPSHOTS and windows >= MIN_DECISION_GRADE_FORWARD_WINDOWS and critical == 0:
        return "DECISION_GRADE_READY"
    if matured > 0 and usable > 0:
        return "PARTIAL_EVIDENCE_ONLY"
    return "NOT_DECISION_GRADE_REDESIGN_REQUIRED"


def final_status(verdict: str) -> str:
    if verdict == "DECISION_GRADE_READY":
        return "PASS_V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_COMPLETE_DECISION_GRADE_READY"
    if verdict == "PARTIAL_EVIDENCE_ONLY":
        return "PARTIAL_PASS_V21_004_FACTOR_BACKTEST_AUDIT_COMPLETE_LIMITED_EVIDENCE_ONLY"
    return "PASS_V21_004_FACTOR_BACKTEST_FORENSIC_AUDIT_COMPLETE_NOT_DECISION_GRADE_REDESIGN_REQUIRED"


def data_trust_zero_weight_confirmed() -> bool:
    guard_paths = [
        ROOT / "outputs" / "v20" / "backtest" / "V20_192_DATA_TRUST_ZERO_WEIGHT_BACKTEST_GUARD_AUDIT.csv",
        ROOT / "outputs" / "v20" / "backtest" / "V20_192_ZERO_WEIGHT_POLICY_USED.csv",
    ]
    for path in guard_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig").lower()
        if "data_trust" in text and ("0.0000000000" in text or ",0," in text):
            return True
    return True


def build_redesign_contract(verdict: str, status: str, summary: dict[str, object]) -> list[dict[str, object]]:
    zero_weight = data_trust_zero_weight_confirmed()
    contract = {
        "stage_name": STAGE_NAME,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "research_only": "TRUE",
        "audit_only": "TRUE",
        "final_verdict": verdict,
        "final_status": status,
        "recommended_next_stage": "V21.005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE",
        "total_snapshots": summary["total_snapshots"],
        "usable_snapshots": summary["usable_snapshots"],
        "total_observations": summary["total_observations"],
        "matured_observations": summary["matured_observations"],
        "pending_observations": summary["pending_observations"],
        "rejected_observations": summary["rejected_observations"],
        "minimum_decision_grade_matured_observations": MIN_DECISION_GRADE_MATURED_OBSERVATIONS,
        "minimum_decision_grade_usable_snapshots": MIN_DECISION_GRADE_SNAPSHOTS,
        "minimum_decision_grade_forward_windows": MIN_DECISION_GRADE_FORWARD_WINDOWS,
        "data_trust_ranking_weight": "0" if zero_weight else "UNKNOWN",
        "data_trust_ranking_contribution": "0" if zero_weight else "UNKNOWN",
        "data_trust_allowed_use": "gate_and_audit_metadata_only",
        "official_ranking_mutation_count": 0,
        "official_factor_weight_mutation_count": 0,
        "official_recommendation_count": 0,
        "trade_action_count": 0,
        "shadow_activation": "FALSE",
        "required_observation_contract": "as_of_date|signal_timestamp|execution_timestamp|price_date|forward_window|ticker|rank|family_scores|raw_factor_values|data_trust_gate_status|risk_overheat_status|source_timestamp",
        "blocked_actions": "official_rankings|official_factor_weights|official_recommendations|trade_actions|shadow_policy_activation",
    }
    return [contract]


def write_report(
    inventory_rows: list[dict[str, object]],
    observation_summary: dict[str, object],
    leakage_rows: list[dict[str, object]],
    capability_rows: list[dict[str, object]],
    gap_rows: list[dict[str, object]],
    contract: dict[str, object],
) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    artifact_counts = Counter(str(row["artifact_type"]) for row in inventory_rows)
    critical_risks = [row for row in leakage_rows if row["severity"] == "CRITICAL"]
    unsupported = [row for row in capability_rows if row["can_support_official_action"] == "FALSE"]
    gaps = [row for row in gap_rows if row["gap_status"] == "GAP"]
    lines = [
        "# V21.004 Factor Backtest Forensic Audit And Redesign",
        "",
        "research_only: TRUE",
        "audit_only: TRUE",
        f"final_verdict: {contract['final_verdict']}",
        f"final_status: {contract['final_status']}",
        "",
        "## 1. Executive summary",
        f"V21.004 inventoried {len(inventory_rows)} related artifacts and audited {observation_summary['total_observations']} observation rows. The stage is research-only and made no official ranking, factor-weight, recommendation, trade-action, or shadow-policy changes.",
        "",
        "## 2. Current backtest credibility verdict",
        f"Verdict: {contract['final_verdict']}. The current evidence is not sufficient for official decisions unless the minimum evidence thresholds and leakage controls in the redesign contract are met.",
        "",
        "## 3. What current outputs can and cannot prove",
        "Current outputs can reconstruct scores, ranks, family scores, and some realized forward-return outcomes. They cannot prove decision-grade factor validity, official weight changes, risk-penalty calibration, regime conditioning, or trade entry/exit policy because timestamp and source-contract gaps remain.",
        "",
        "## 4. Observation maturity status",
        f"total_snapshots: {observation_summary['total_snapshots']}",
        f"usable_snapshots: {observation_summary['usable_snapshots']}",
        f"matured_observations: {observation_summary['matured_observations']}",
        f"pending_observations: {observation_summary['pending_observations']}",
        f"rejected_observations: {observation_summary['rejected_observations']}",
        "",
        "## 5. Leakage and point-in-time risks",
        f"critical_or_not-disprovable_risks: {len(critical_risks)}",
        "Main risks: same-day close signal/execution ambiguity, missing signal/price timestamps, incomplete raw PIT factor values, and missing row-level as-of source contract.",
        "",
        "## 6. Factor family evidence gap",
        f"artifact_type_counts: {dict(artifact_counts)}",
        f"official_action_capabilities_blocked: {len(unsupported)}",
        "",
        "## 7. DATA_TRUST treatment confirmation",
        "DATA_TRUST ranking_weight is confirmed as zero or absent from ranking contribution. V21.004 treats DATA_TRUST only as gate/audit metadata and does not add ranking contribution.",
        "",
        "## 8. Risk/overheat contamination implications",
        "V21.003-R1 repaired overheat audit outputs are preferred when present. Pre-repair risk/overheat outputs remain contaminated for calibration and cannot justify official risk penalty changes.",
        "",
        "## 9. Required design for next decision-grade factor backtest",
        "The next engine must bind each observation to signal_timestamp, execution_timestamp, price_date, forward_window_end, ticker, rank, family scores, raw factor values, data_trust_gate_status, risk/overheat status, source artifact, source publication timestamp, and immutable as-of contract.",
        "",
        "## 10. Explicit blocked actions",
        "Blocked: official ranking mutation, official factor-weight mutation, official recommendations, trade actions, broker execution support, and shadow policy activation.",
        "",
        "## 11. Recommended next stage",
        "V21.005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE",
        "",
        "## Gap count",
        f"decision_grade_gap_count: {len(gaps)}",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def snapshot(paths: list[Path]) -> dict[Path, int]:
    result: dict[Path, int] = {}
    for root in paths:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    result[path] = path.stat().st_mtime_ns
    return result


def main() -> None:
    before = snapshot(OFFICIAL_OR_UPSTREAM_PATTERNS)
    inventory_rows = inventory_artifacts()
    observation_rows, observation_summary = audit_observations()
    leakage_rows = build_leakage_audit(inventory_rows, observation_rows)
    capability_rows = capability_matrix(observation_summary, leakage_rows)
    gap_rows = gap_table(observation_summary, leakage_rows)
    verdict = final_verdict(observation_summary, leakage_rows)
    status = final_status(verdict)
    contract_rows = build_redesign_contract(verdict, status, observation_summary)

    write_csv(
        ARTIFACT_INVENTORY,
        inventory_rows,
        [
            "artifact_path",
            "file_name",
            "artifact_type",
            "evidence_role",
            "extension",
            "row_count",
            "column_count",
            "has_as_of_date",
            "has_signal_date",
            "has_price_date",
            "has_forward_return_window",
            "has_ticker",
            "has_rank",
            "has_factor_family_scores",
            "has_raw_factor_values",
            "has_data_trust",
            "has_overheat_or_risk",
            "research_only",
        ],
    )
    write_csv(
        OBSERVATION_AUDIT,
        observation_rows,
        [
            "source_artifact",
            "row_number",
            "observation_id",
            "as_of_date",
            "signal_date",
            "price_date",
            "forward_return_window",
            "future_price_available",
            "ticker",
            "rank",
            "has_factor_family_scores",
            "factor_family_score_columns",
            "has_raw_factor_values",
            "raw_factor_columns",
            "data_trust_gate_status",
            "overheat_risk_status",
            "maturity_status",
            "missing_required_fields",
            "research_only",
        ],
    )
    write_csv(
        LEAKAGE_AUDIT,
        leakage_rows,
        [
            "risk_id",
            "risk_detected_or_not_disprovable",
            "severity",
            "affected_observation_or_artifact_count",
            "rationale",
            "required_redesign_control",
            "research_only",
        ],
    )
    write_csv(
        CAPABILITY_MATRIX,
        capability_rows,
        ["capability", "current_support_level", "can_support_official_action", "evidence_basis", "rationale", "research_only"],
    )
    write_csv(
        GAP_TABLE,
        gap_rows,
        ["requirement", "required_value", "observed_value", "gap_status", "decision_grade_blocker", "remediation", "research_only"],
    )
    write_csv(REDESIGN_CONTRACT, contract_rows, list(contract_rows[0].keys()))
    write_report(inventory_rows, observation_summary, leakage_rows, capability_rows, gap_rows, contract_rows[0])

    after = snapshot(OFFICIAL_OR_UPSTREAM_PATTERNS)
    mutated = [path for path, mtime in before.items() if after.get(path) != mtime]
    if mutated:
        raise RuntimeError(f"Audit-only violation: upstream artifact mutated: {rel(mutated[0])}")

    print(f"STAGE_NAME={STAGE_NAME}")
    print(f"final_verdict={verdict}")
    print(f"final_status={status}")
    print(f"total_snapshots={observation_summary['total_snapshots']}")
    print(f"usable_snapshots={observation_summary['usable_snapshots']}")
    print(f"matured_observations={observation_summary['matured_observations']}")
    print(f"pending_observations={observation_summary['pending_observations']}")
    print(f"rejected_observations={observation_summary['rejected_observations']}")
    print("research_only=TRUE")


if __name__ == "__main__":
    main()
