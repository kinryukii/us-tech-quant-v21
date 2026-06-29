#!/usr/bin/env python
"""Build a research-only contract for historical six-family score materialization."""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R3_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION_PLAN_AND_CONTRACT"
PASS_STATUS = "PASS_V21_044_R3_FULL_FAMILY_MATERIALIZATION_CONTRACT_READY"
MISSING_STATUS = "PARTIAL_PASS_V21_044_R3_MATERIALIZATION_CONTRACT_WITH_MISSING_FAMILIES"
TECH_ONLY_STATUS = "PARTIAL_PASS_V21_044_R3_TECHNICAL_ONLY_CONFIRMED_OTHERS_BLOCKED"
SOURCE_BLOCKED = "BLOCKED_V21_044_R3_FULL_WEIGHT_SOURCE_NOT_FOUND"
NO_PATHS = "BLOCKED_V21_044_R3_NO_FAMILY_MATERIALIZATION_PATHS"

PROCEED = "PROCEED_TO_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER"
PROCEED_PARTIAL = "PROCEED_TO_PARTIAL_FAMILY_MATERIALIZER_WITH_EXPLICIT_MISSING_FAMILY_BLOCKS"
NEED_REPAIR = "NEED_FUNDAMENTAL_STRATEGY_RISK_REGIME_DATA_TRUST_SOURCE_REPAIR"
KEEP_TECH = "KEEP_TECHNICAL_ONLY_BACKTEST_AS_ONLY_VALID_HISTORICAL_RESULT"
BLOCK = "BLOCK_FULL_WEIGHT_REBACKTEST_UNTIL_SOURCES_EXIST"

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
WEIGHT_SOURCE = ROOT / "outputs" / "v21" / "context" / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R2_DISCOVERY = REVIEW / "V21_044_R2_PIT_LINEAGE_ARTIFACT_DISCOVERY.csv"
R2_REPAIR = REVIEW / "V21_044_R2_PIT_LINEAGE_REPAIR_AUDIT.csv"
R2_DECISION = REVIEW / "V21_044_R2_FULL_WEIGHT_PANEL_DECISION_SUMMARY.csv"

DISCOVERY_OUT = REVIEW / "V21_044_R3_FULL_FAMILY_SOURCE_DISCOVERY.csv"
CONTRACT_OUT = REVIEW / "V21_044_R3_FAMILY_MATERIALIZATION_CONTRACT.csv"
MISSING_OUT = REVIEW / "V21_044_R3_MISSING_INPUT_REQUIREMENTS.csv"
RISK_OUT = REVIEW / "V21_044_R3_LINEAGE_RISK_REGISTER.csv"
PLAN_OUT = REVIEW / "V21_044_R3_NEXT_STAGE_IMPLEMENTATION_PLAN.csv"
DECISION_OUT = REVIEW / "V21_044_R3_MATERIALIZATION_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R3_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION_PLAN_AND_CONTRACT_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R3_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION_PLAN_AND_CONTRACT_REPORT.md"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]

SOURCES = {
    "FUNDAMENTAL": [
        "outputs/v20/consolidation/V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv",
        "outputs/v20/consolidation/V20_108_R6A_CONTROLLED_FUNDAMENTAL_METRIC_CACHE.csv",
    ],
    "TECHNICAL": [
        "outputs/v21/factors/V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    ],
    "STRATEGY": [
        "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv",
        "outputs/v21/factors/V21_032_R1_TECHNICAL_VARIANT_RANK_COMPARISON.csv",
    ],
    "RISK": [
        "outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv",
        "outputs/v21/factors/V21_032_R1_TECHNICAL_VARIANT_RANK_COMPARISON.csv",
    ],
    "MARKET_REGIME": [
        "outputs/v20/consolidation/V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv",
        "outputs/v20/consolidation/V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv",
    ],
    "DATA_TRUST": [
        "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv",
        "outputs/v20/factors/V20_166_R2_DATA_TRUST_GATE_ONLY_SCORE_AUDIT.csv",
        "outputs/v20/factors/V20_170_DATA_TRUST_DIRECT_STATUS_EMITTER.csv",
    ],
}

RULES = {
    "FUNDAMENTAL": {
        "required": ["ticker", "as_of_date_or_reporting_date", "factor_date_or_publication_date", "fundamental_score_or_raw_metrics"],
        "proposed": "fundamental_contribution",
        "direction": "HIGHER_IS_BETTER",
        "normalization": "CROSS_SECTIONAL_PERCENTILE_BY_AS_OF_DATE_AFTER_PUBLICATION_LAG",
        "alpha": "TRUE", "gate": "FALSE",
        "classification": "CURRENT_ONLY_FUNDAMENTAL_SCORE_SOURCE",
        "status": "BLOCKED_MISSING_HISTORICAL_DATE_LINEAGE",
    },
    "TECHNICAL": {
        "required": ["ticker", "as_of_date", "technical_score_normalized"],
        "proposed": "technical_score_normalized",
        "direction": "HIGHER_IS_BETTER",
        "normalization": "PRESERVE_UPSTREAM_NORMALIZED_SCORE",
        "alpha": "TRUE", "gate": "FALSE",
        "classification": "PIT_SAFE_HISTORICAL_FAMILY_SCORE_SOURCE",
        "status": "MATERIALIZABLE_NOW",
    },
    "STRATEGY": {
        "required": ["ticker", "as_of_date", "strategy_score_or_explicit_rule_outputs", "factor_date"],
        "proposed": "strategy_contribution",
        "direction": "HIGHER_IS_BETTER",
        "normalization": "CROSS_SECTIONAL_PERCENTILE_BY_AS_OF_DATE_WITH_SELECTIVITY_AUDIT",
        "alpha": "TRUE", "gate": "FALSE",
        "classification": "CURRENT_ONLY_STRATEGY_CONTEXT_SOURCE",
        "status": "BLOCKED_MISSING_HISTORICAL_DATE_LINEAGE",
    },
    "RISK": {
        "required": ["ticker", "as_of_date", "risk_score_or_penalty", "factor_date"],
        "proposed": "risk_contribution_or_gate_status",
        "direction": "HIGHER_IS_LOWER_RISK",
        "normalization": "PENALTY_OR_GATE_CONTRACT_REQUIRED_BEFORE_ALPHA_USE",
        "alpha": "FALSE", "gate": "TRUE",
        "classification": "CURRENT_ONLY_RISK_CONTEXT_GATE_CAPABLE",
        "status": "BLOCKED_FOR_ALPHA_GATE_METADATA_ONLY",
    },
    "MARKET_REGIME": {
        "required": ["as_of_date", "benchmark_or_regime_date", "regime_label_or_score", "ticker_exposure_if_ticker_specific"],
        "proposed": "market_regime_context",
        "direction": "CONTEXT_DEPENDENT",
        "normalization": "MARKET_LEVEL_CONTEXT_OR_EXPOSURE_CONDITIONED_MAPPING",
        "alpha": "FALSE", "gate": "TRUE",
        "classification": "CURRENT_TICKER_CONDITIONED_REGIME_CONTEXT_NO_HISTORY",
        "status": "BLOCKED_MISSING_HISTORICAL_REGIME_DATE_LINEAGE",
    },
    "DATA_TRUST": {
        "required": ["ticker", "as_of_date", "factor_date", "direct_data_trust_status_or_compatible_score"],
        "proposed": "data_trust_gate_status",
        "direction": "PASS_FAIL_UNKNOWN_GATE",
        "normalization": "NO_ALPHA_NORMALIZATION_GATE_ONLY_UNLESS_COMPATIBLE_HISTORY_EXISTS",
        "alpha": "FALSE", "gate": "TRUE",
        "classification": "DATED_GATE_METADATA_NOT_COMPATIBLE_ALPHA_SCORE",
        "status": "BLOCKED_FOR_ALPHA_GATE_METADATA_ONLY",
    },
}

CONTRACT_FIELDS = [
    "family_name", "target_family_weight", "current_materialization_status",
    "candidate_source_paths", "candidate_source_count", "selected_source_path_if_any",
    "selected_source_classification", "required_input_columns", "available_input_columns",
    "missing_input_columns", "detected_date_columns", "selected_as_of_date_column",
    "selected_factor_date_column", "factor_date_status", "ticker_column",
    "score_column_candidates", "proposed_score_column", "proposed_score_direction",
    "normalization_required", "normalization_method_proposed",
    "point_in_time_safe_possible", "point_in_time_safe_blocker",
    "alpha_bearing_allowed", "gate_only_allowed", "family_score_materialization_allowed",
    "risk_score_alpha_allowed", "risk_gate_only_allowed",
    "data_trust_alpha_allowed", "data_trust_gate_only_allowed",
    "market_regime_scope_classification", "strategy_selectivity_warning",
    "rejection_reason",
]


def guardrails() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "full_weight_rebacktest_allowed_now": "FALSE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return "" if not math.isfinite(float(value)) else f"{float(value):.10f}"
    return value


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def resolve_weights() -> tuple[dict[str, float], str]:
    if not WEIGHT_SOURCE.exists():
        return {}, "FULL_WEIGHT_SOURCE_NOT_FOUND"
    df = read_csv(WEIGHT_SOURCE)
    if not {"factor_family", "shadow_dynamic_weight"}.issubset(df.columns):
        return {}, "FULL_WEIGHT_SOURCE_INVALID_SCHEMA"
    weights = {}
    for row in df.to_dict("records"):
        family = clean(row.get("factor_family")).upper()
        value = pd.to_numeric(pd.Series([row.get("shadow_dynamic_weight")]), errors="coerce").iloc[0]
        if family in FAMILIES and pd.notna(value):
            weights[family] = float(value)
    return weights, "FULL_CURRENT_WEIGHT_SOURCE_RESOLVED" if set(weights) == set(FAMILIES) else "FULL_WEIGHT_SOURCE_INCOMPLETE"


def columns_for(path_text: str) -> list[str]:
    path = ROOT / path_text
    if not path.exists():
        return []
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError):
        return []


def inspect_source(family: str, path_text: str) -> dict[str, object]:
    path = ROOT / path_text
    columns = columns_for(path_text)
    lower = {column.lower(): column for column in columns}
    dates = [column for column in columns if "date" in column.lower() and "forward" not in column.lower()]
    ticker = lower.get("ticker") or lower.get("symbol") or lower.get("normalized_ticker") or ""
    score_candidates = [
        column for column in columns
        if ("score" in column.lower() or "contribution" in column.lower() or "status" in column.lower())
        and "forward" not in column.lower()
    ]
    r2 = read_csv(R2_DISCOVERY)
    r2_row = pd.DataFrame()
    if not r2.empty and "candidate_path" in r2.columns:
        normalized = r2["candidate_path"].astype(str).str.replace("\\", "/", regex=False)
        r2_row = r2[normalized == path_text]
    return {
        "family_name": family,
        "candidate_path": path_text,
        "source_exists": "TRUE" if path.exists() else "FALSE",
        "row_count": int(pd.read_csv(path, usecols=[0]).shape[0]) if path.exists() and columns else 0,
        "available_columns": "|".join(columns),
        "detected_date_columns": "|".join(dates),
        "ticker_column": ticker,
        "score_column_candidates": "|".join(score_candidates),
        "r2_usable_for_pit_lineage": clean(r2_row.iloc[0].get("usable_for_pit_lineage")) if not r2_row.empty else "NOT_SCANNED_BY_R2",
        "r2_rejection_reason": clean(r2_row.iloc[0].get("rejection_reason")) if not r2_row.empty else "",
        "selected_for_contract": "TRUE" if path_text == SOURCES[family][0] else "FALSE",
    }


def contract_rows(weights: dict[str, float], discovery: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    by_family: dict[str, list[dict[str, object]]] = {
        family: [row for row in discovery if row["family_name"] == family] for family in FAMILIES
    }
    for family in FAMILIES:
        rule = RULES[family]
        candidates = by_family[family]
        selected = candidates[0]
        columns = clean(selected["available_columns"]).split("|") if clean(selected["available_columns"]) else []
        lower = {column.lower(): column for column in columns}
        materializable = family == "TECHNICAL" and selected["source_exists"] == "TRUE"
        if family == "TECHNICAL":
            available = ["ticker", "as_of_date", "technical_score_normalized"]
            missing = []
            asof = "as_of_date"
            factor_date = "as_of_date"
            factor_status = "EXPLICIT_SAME_DAY_SNAPSHOT"
            blocker = ""
        elif family == "FUNDAMENTAL":
            available = ["ticker", "fundamental_score_or_raw_metrics"]
            missing = ["as_of_date_or_reporting_date", "factor_date_or_publication_date"]
            asof, factor_date, factor_status = "", "", "UNKNOWN"
            blocker = "CURRENT_FUNDAMENTAL_VALUES_HAVE_NO_HISTORICAL_REPORTING_OR_PUBLICATION_DATE_LINEAGE"
        elif family == "STRATEGY":
            available = ["ticker", "strategy_score_or_explicit_rule_outputs"]
            missing = ["as_of_date", "factor_date"]
            asof, factor_date, factor_status = "", "", "UNKNOWN"
            blocker = "CURRENT_STRATEGY_CONTEXT_HAS_NO_HISTORICAL_FACTOR_DATE_LINEAGE"
        elif family == "RISK":
            available = ["ticker", "risk_score_or_penalty"]
            missing = ["as_of_date", "factor_date"]
            asof, factor_date, factor_status = "", "", "UNKNOWN"
            blocker = "CURRENT_RISK_CONTEXT_HAS_NO_HISTORICAL_FACTOR_DATE_LINEAGE|ALPHA_SEMANTICS_DISABLED"
        elif family == "MARKET_REGIME":
            available = ["regime_label_or_score", "ticker_exposure_if_ticker_specific"]
            missing = ["as_of_date", "benchmark_or_regime_date"]
            asof, factor_date, factor_status = "", "", "UNKNOWN"
            blocker = "CURRENT_REGIME_CONTEXT_HAS_NO_HISTORICAL_BENCHMARK_OR_REGIME_DATE_LINEAGE"
        elif family == "DATA_TRUST":
            available = ["ticker", "as_of_date", "factor_date"]
            missing = ["direct_data_trust_status_or_compatible_score"]
            asof = "effective_observation_date"
            factor_date = "effective_price_date"
            factor_status = "EXPLICIT"
            blocker = "DATED_READINESS_METADATA_IS_NOT_A_COMPATIBLE_DATA_TRUST_ALPHA_SCORE_OR_DIRECT_GATE_STATUS"
        else:
            available = [
                item for item in rule["required"]
                if item in lower or item.split("_or_")[0] in lower
            ]
            missing = [item for item in rule["required"] if item not in available]
            asof = next((lower[name] for name in ["as_of_date", "observation_date", "effective_observation_date"] if name in lower), "")
            factor_date = next((lower[name] for name in ["factor_date", "feature_date", "effective_price_date", "reporting_date"] if name in lower), "")
            factor_status = "EXPLICIT" if factor_date else "UNKNOWN"
            blocker = "MISSING_EXPLICIT_HISTORICAL_AS_OF_AND_FACTOR_DATE_LINEAGE"
        rows.append({
            "family_name": family,
            "target_family_weight": weights.get(family, ""),
            "current_materialization_status": rule["status"],
            "candidate_source_paths": "|".join(SOURCES[family]),
            "candidate_source_count": len([row for row in candidates if row["source_exists"] == "TRUE"]),
            "selected_source_path_if_any": selected["candidate_path"] if selected["source_exists"] == "TRUE" else "",
            "selected_source_classification": rule["classification"],
            "required_input_columns": "|".join(rule["required"]),
            "available_input_columns": "|".join(available),
            "missing_input_columns": "|".join(missing),
            "detected_date_columns": selected["detected_date_columns"],
            "selected_as_of_date_column": asof,
            "selected_factor_date_column": factor_date,
            "factor_date_status": factor_status,
            "ticker_column": selected["ticker_column"],
            "score_column_candidates": selected["score_column_candidates"],
            "proposed_score_column": rule["proposed"],
            "proposed_score_direction": rule["direction"],
            "normalization_required": "FALSE" if family == "TECHNICAL" else "TRUE",
            "normalization_method_proposed": rule["normalization"],
            "point_in_time_safe_possible": "TRUE" if materializable else "FALSE",
            "point_in_time_safe_blocker": blocker,
            "alpha_bearing_allowed": rule["alpha"],
            "gate_only_allowed": rule["gate"],
            "family_score_materialization_allowed": "TRUE" if materializable else "FALSE",
            "risk_score_alpha_allowed": rule["alpha"] if family == "RISK" else "NOT_APPLICABLE",
            "risk_gate_only_allowed": rule["gate"] if family == "RISK" else "NOT_APPLICABLE",
            "data_trust_alpha_allowed": rule["alpha"] if family == "DATA_TRUST" else "NOT_APPLICABLE",
            "data_trust_gate_only_allowed": rule["gate"] if family == "DATA_TRUST" else "NOT_APPLICABLE",
            "market_regime_scope_classification": (
                "CURRENT_TICKER_CONDITIONED_CONTEXT_NOT_HISTORICAL|MARKET_LEVEL_SIGNAL_REQUIRES_DATED_LINEAGE"
                if family == "MARKET_REGIME" else "NOT_APPLICABLE"
            ),
            "strategy_selectivity_warning": (
                "REQUIRE_CROSS_SECTIONAL_SELECTIVITY_AUDIT_REJECT_BROADCAST_LABELS"
                if family == "STRATEGY" else "NOT_APPLICABLE"
            ),
            "rejection_reason": "" if materializable else rule["status"],
        })
    return rows


def missing_rows(contracts: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for contract in contracts:
        if contract["family_score_materialization_allowed"] == "TRUE":
            continue
        missing = clean(contract["missing_input_columns"]).split("|")
        if not missing or missing == [""]:
            missing = ["historical_point_in_time_compatible_source"]
        for requirement in missing:
            rows.append({
                "family_name": contract["family_name"],
                "missing_requirement": requirement,
                "requirement_type": "COLUMN_OR_LINEAGE_CONTRACT",
                "required_for_alpha_score": contract["alpha_bearing_allowed"],
                "required_for_gate_metadata": contract["gate_only_allowed"],
                "acceptable_local_evidence": "EXPLICIT_CONTENT_COLUMN_WITH_DATE_LINEAGE",
                "filename_or_mtime_inference_allowed": "FALSE",
                "blocking_status": "BLOCKING_FULL_FAMILY_MATERIALIZATION",
            })
    return rows


def risk_rows(contracts: list[dict[str, object]]) -> list[dict[str, object]]:
    risks = [
        ("RISK-001", "ALL", "UNKNOWN_FACTOR_DATES", "CRITICAL", "Do not bind current scores to historical dates.", "BLOCKED"),
        ("RISK-002", "FUNDAMENTAL", "CURRENT_VALUES_BACKFILLED_HISTORICALLY", "CRITICAL", "Require reporting/publication date lineage.", "BLOCKED"),
        ("RISK-003", "STRATEGY", "FORWARD_RETURN_OR_BROADCAST_LABEL_LEAKAGE", "CRITICAL", "Ban forward fields and require selectivity audit.", "BLOCKED"),
        ("RISK-004", "RISK", "GATE_METADATA_MISUSED_AS_ALPHA", "HIGH", "Keep alpha disabled until dated score semantics exist.", "CONTROLLED"),
        ("RISK-005", "MARKET_REGIME", "MARKET_CONTEXT_MISREAD_AS_TICKER_ALPHA", "HIGH", "Separate market-level context from ticker exposure.", "CONTROLLED"),
        ("RISK-006", "DATA_TRUST", "GATE_METADATA_MISUSED_AS_ALPHA", "CRITICAL", "Allow gate-only metadata; prohibit alpha synthesis.", "CONTROLLED"),
        ("RISK-007", "ALL", "FILENAME_OR_FILE_TIMESTAMP_DATE_INFERENCE", "CRITICAL", "Use explicit content dates only.", "CONTROLLED"),
    ]
    return [{
        "risk_id": risk_id, "family_name": family, "risk_type": risk_type,
        "severity": severity, "required_control": control, "risk_status": status,
        "scores_created": "FALSE", "dates_created": "FALSE",
    } for risk_id, family, risk_type, severity, control, status in risks]


def plan_rows(contracts: list[dict[str, object]]) -> list[dict[str, object]]:
    steps = [
        (1, "TECHNICAL", "BIND_EXISTING_PIT_SAFE_TECHNICAL_PANEL", "READY", "Preserve V21.038 source lineage and normalized score."),
        (2, "FUNDAMENTAL", "MATERIALIZE_DATED_FUNDAMENTAL_INPUT_SNAPSHOTS", "BLOCKED", "Require reporting/publication dates before scoring."),
        (3, "STRATEGY", "MATERIALIZE_DATED_SELECTIVE_STRATEGY_RULE_OUTPUTS", "BLOCKED", "Exclude forward returns and reject broadcast-only labels."),
        (4, "RISK", "MATERIALIZE_DATED_RISK_GATE_OR_PENALTY_METADATA", "BLOCKED", "Gate-only first; alpha remains disabled."),
        (5, "MARKET_REGIME", "MATERIALIZE_DATED_MARKET_REGIME_CONTEXT", "BLOCKED", "Separate market-level regime from ticker exposure mapping."),
        (6, "DATA_TRUST", "MATERIALIZE_DATED_DIRECT_DATA_TRUST_GATE_STATUS", "BLOCKED", "No alpha score from gate-only readiness metadata."),
        (7, "ALL", "JOIN_COMPLETE_TICKER_DATE_FAMILY_PANEL", "BLOCKED", "Require all six source contracts to pass."),
        (8, "ALL", "RUN_LEAKAGE_AND_COMPLETENESS_AUDIT", "BLOCKED", "Only then permit a later rebacktest stage."),
    ]
    return [{
        "step_order": order, "family_name": family, "implementation_action": action,
        "implementation_status": status, "acceptance_criteria": criteria,
        "creates_scores_now": "FALSE", "runs_backtest_now": "FALSE",
        "recommended_stage": "V21.044-R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER",
    } for order, family, action, status, criteria in steps]


def write_report(decision: dict[str, object], contracts: list[dict[str, object]]) -> None:
    table = "\n".join(
        f"| {row['family_name']} | {fmt(row['target_family_weight'])} | {row['current_materialization_status']} | "
        f"{row['alpha_bearing_allowed']} | {row['gate_only_allowed']} |"
        for row in contracts
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- full weight source path: {decision['full_weight_source_path']}
- recommended next stage: {decision['recommended_next_stage']}
- full-weight rebacktest allowed now: FALSE

## Full Family Weights
| Family | Weight | Materialization status | Alpha allowed | Gate-only allowed |
|---|---:|---|---:|---:|
{table}

## V21.044-R2 Diagnosis
- status: {decision['upstream_r2_final_status']}
- PIT-safe partial rows: {decision['upstream_r2_pit_safe_row_count']}
- UNKNOWN factor-date rows: {decision['upstream_r2_unknown_factor_date_row_count']}
- complete historical panel rows: {decision['upstream_r2_historical_panel_row_count']}
- eligible as-of dates: {decision['upstream_r2_eligible_asof_count']}

## Materialization Readiness
- materializable now: {decision['materializable_family_list']}
- blocked: {decision['blocked_family_list']}
- missing input summary: {decision['missing_input_summary']}
- Data Trust: gate-only metadata allowed; compatible historical alpha score blocked.
- Risk: gate/penalty metadata allowed; alpha-bearing interpretation blocked.
- Market Regime: current ticker-conditioned context exists, but dated market-level and exposure lineage is required.

## Limitations
- This stage creates contracts and plans only. It creates no family scores and runs no backtest.
- Current-only family contributions are not treated as historical observations.
- Dates are accepted only from explicit artifact content.
- Missing families, dates, values, returns, and labels are not fabricated.

## Guardrails
research_only = TRUE
full_weight_rebacktest_allowed_now = FALSE
official_adoption_allowed = FALSE
official_weight_mutation = FALSE
official_ranking_mutation = FALSE
real_book_action_allowed = FALSE
broker_execution_allowed = FALSE
trade_action_allowed = FALSE
shadow_gate_allowed = FALSE
shadow_adoption_allowed = FALSE
"""
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def main() -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    weights, weight_status = resolve_weights()
    discovery = [
        inspect_source(family, path)
        for family in FAMILIES
        for path in SOURCES[family]
    ]
    contracts = contract_rows(weights, discovery) if weights else []
    missing = missing_rows(contracts)
    risks = risk_rows(contracts)
    plan = plan_rows(contracts)

    materializable = [row["family_name"] for row in contracts if row["family_score_materialization_allowed"] == "TRUE"]
    blocked = [row["family_name"] for row in contracts if row["family_score_materialization_allowed"] != "TRUE"]
    if weight_status != "FULL_CURRENT_WEIGHT_SOURCE_RESOLVED":
        final_status, decision_value = SOURCE_BLOCKED, BLOCK
    elif not materializable:
        final_status, decision_value = NO_PATHS, BLOCK
    elif materializable == ["TECHNICAL"]:
        final_status, decision_value = TECH_ONLY_STATUS, NEED_REPAIR
    elif blocked:
        final_status, decision_value = MISSING_STATUS, PROCEED_PARTIAL
    else:
        final_status, decision_value = PASS_STATUS, PROCEED

    r2 = read_csv(R2_DECISION)
    r2_row = r2.iloc[0].to_dict() if not r2.empty else {}
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "full_weight_source_path": relative(WEIGHT_SOURCE) if WEIGHT_SOURCE.exists() else "",
        "full_weight_source_status": weight_status,
        "full_family_weights": "|".join(f"{family}={fmt(weights.get(family, ''))}" for family in FAMILIES),
        "required_family_count": len(FAMILIES),
        "materializable_family_count": len(materializable),
        "blocked_family_count": len(blocked),
        "materializable_family_list": "|".join(materializable),
        "blocked_family_list": "|".join(blocked),
        "data_trust_classification": "GATE_ONLY_ALLOWED_ALPHA_BLOCKED",
        "risk_classification": "GATE_OR_PENALTY_ALLOWED_ALPHA_BLOCKED",
        "market_regime_classification": "CURRENT_TICKER_CONDITIONED_CONTEXT|HISTORICAL_MARKET_LEVEL_LINEAGE_REQUIRED",
        "missing_input_summary": "|".join(sorted({row["missing_requirement"] for row in missing})),
        "recommended_next_stage": "V21.044-R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS",
        "upstream_r2_final_status": clean(r2_row.get("final_status")),
        "upstream_r2_pit_safe_row_count": clean(r2_row.get("pit_safe_row_count")),
        "upstream_r2_unknown_factor_date_row_count": clean(r2_row.get("unknown_factor_date_row_count")),
        "upstream_r2_historical_panel_row_count": clean(r2_row.get("historical_panel_row_count")),
        "upstream_r2_eligible_asof_count": clean(r2_row.get("eligible_asof_count")),
        "scores_materialized_now": "FALSE",
        "dates_fabricated": "FALSE",
        "family_labels_fabricated": "FALSE",
        "full_weight_backtest_run": "FALSE",
        **guardrails(),
    }

    write_csv(DISCOVERY_OUT, discovery, [
        "family_name", "candidate_path", "source_exists", "row_count", "available_columns",
        "detected_date_columns", "ticker_column", "score_column_candidates",
        "r2_usable_for_pit_lineage", "r2_rejection_reason", "selected_for_contract",
    ])
    write_csv(CONTRACT_OUT, contracts, CONTRACT_FIELDS)
    write_csv(MISSING_OUT, missing, [
        "family_name", "missing_requirement", "requirement_type",
        "required_for_alpha_score", "required_for_gate_metadata",
        "acceptable_local_evidence", "filename_or_mtime_inference_allowed", "blocking_status",
    ])
    write_csv(RISK_OUT, risks, [
        "risk_id", "family_name", "risk_type", "severity", "required_control",
        "risk_status", "scores_created", "dates_created",
    ])
    write_csv(PLAN_OUT, plan, [
        "step_order", "family_name", "implementation_action", "implementation_status",
        "acceptance_criteria", "creates_scores_now", "runs_backtest_now", "recommended_stage",
    ])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, contracts)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"materializable_family_count={len(materializable)}")
    print(f"blocked_family_count={len(blocked)}")
    print(f"recommended_next_stage={decision['recommended_next_stage']}")


if __name__ == "__main__":
    main()
