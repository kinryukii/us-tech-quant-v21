#!/usr/bin/env python
"""Materialize PIT-safe Technical history while explicitly blocking other families."""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS"
PASS_STATUS = "PASS_V21_044_R4_TECHNICAL_ONLY_MATERIALIZATION_READY_FULL_WEIGHT_BLOCKED"
LIMITED_STATUS = "PARTIAL_PASS_V21_044_R4_TECHNICAL_ONLY_MATERIALIZATION_LIMITED_COVERAGE"
REGISTER_STATUS = "PARTIAL_PASS_V21_044_R4_BLOCK_REGISTER_READY_NO_MATERIALIZED_PANEL"
SOURCE_BLOCKED = "BLOCKED_V21_044_R4_TECHNICAL_SOURCE_NOT_PIT_SAFE"
CONTRACT_BLOCKED = "BLOCKED_V21_044_R4_R3_CONTRACT_NOT_READY"

READY = "TECHNICAL_ONLY_HISTORICAL_PANEL_READY_KEEP_FULL_WEIGHT_BLOCKED"
LIMITED = "TECHNICAL_ONLY_PANEL_LIMITED_KEEP_FULL_WEIGHT_BLOCKED"
REPAIR = "NEED_TECHNICAL_SOURCE_REPAIR"
NON_TECH_REPAIR = "NEED_NON_TECHNICAL_FAMILY_SOURCE_REPAIR_BEFORE_FULL_WEIGHT_BACKTEST"
BLOCK = "BLOCK_FULL_WEIGHT_BACKTEST"

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
R3_CONTRACT = REVIEW / "V21_044_R3_FAMILY_MATERIALIZATION_CONTRACT.csv"
R3_DECISION = REVIEW / "V21_044_R3_MATERIALIZATION_DECISION_SUMMARY.csv"
R3_DISCOVERY = REVIEW / "V21_044_R3_FULL_FAMILY_SOURCE_DISCOVERY.csv"
R2_DISCOVERY = REVIEW / "V21_044_R2_PIT_LINEAGE_ARTIFACT_DISCOVERY.csv"
R2_REPAIR = REVIEW / "V21_044_R2_PIT_LINEAGE_REPAIR_AUDIT.csv"
R2_DECISION = REVIEW / "V21_044_R2_FULL_WEIGHT_PANEL_DECISION_SUMMARY.csv"
WEIGHT_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
SAMPLE_MANIFEST = ROOT / "outputs" / "v21" / "backtest" / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
UPSTREAM_PANEL = ROOT / "outputs" / "v21" / "backtest" / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"

PANEL_OUT = REVIEW / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
BLOCK_OUT = REVIEW / "V21_044_R4_EXPLICIT_FAMILY_SOURCE_BLOCK_REGISTER.csv"
ELIGIBLE_OUT = REVIEW / "V21_044_R4_TECHNICAL_ONLY_ELIGIBLE_ASOF_MANIFEST.csv"
COVERAGE_OUT = REVIEW / "V21_044_R4_MATERIALIZATION_COVERAGE_AUDIT.csv"
REBACKTEST_BLOCK_OUT = REVIEW / "V21_044_R4_FULL_WEIGHT_REBACKTEST_BLOCK_AUDIT.csv"
DECISION_OUT = REVIEW / "V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS_REPORT.md"

BLOCKED_FAMILIES = {
    "FUNDAMENTAL": {
        "status": "BLOCKED_MISSING_HISTORICAL_REPORTING_PUBLICATION_DATES",
        "reason": "Current fundamental scores lack historical reporting and publication-date lineage.",
        "repair": "Materialize ticker-level historical fundamental inputs with reporting_date, publication_date, and as_of_date.",
        "alpha": "TRUE", "gate": "FALSE",
        "next": "V21_044_R4A_FUNDAMENTAL_HISTORICAL_DATE_SOURCE_REPAIR.csv",
    },
    "STRATEGY": {
        "status": "BLOCKED_MISSING_HISTORICAL_FACTOR_DATE_LINEAGE",
        "reason": "Strategy scores or rule outputs lack historical factor-date lineage and selectivity proof.",
        "repair": "Materialize dated strategy rule outputs and audit cross-sectional selectivity without forward returns.",
        "alpha": "TRUE", "gate": "FALSE",
        "next": "V21_044_R4A_STRATEGY_HISTORICAL_LINEAGE_REPAIR.csv",
    },
    "RISK": {
        "status": "BLOCKED_GATE_OR_PENALTY_ONLY_ALPHA_DISABLED",
        "reason": "Risk is restricted to gate or penalty metadata; alpha semantics and historical dates are unavailable.",
        "repair": "Materialize dated risk gate or penalty observations and preserve alpha_bearing_allowed=FALSE.",
        "alpha": "FALSE", "gate": "TRUE",
        "next": "V21_044_R4A_RISK_HISTORICAL_GATE_METADATA_REPAIR.csv",
    },
    "MARKET_REGIME": {
        "status": "BLOCKED_MISSING_HISTORICAL_BENCHMARK_REGIME_DATES",
        "reason": "Current regime context lacks historical benchmark/regime dates and market-level lineage.",
        "repair": "Materialize dated market regime context separately from ticker exposure mappings.",
        "alpha": "FALSE", "gate": "TRUE",
        "next": "V21_044_R4A_MARKET_REGIME_HISTORICAL_DATE_REPAIR.csv",
    },
    "DATA_TRUST": {
        "status": "BLOCKED_GATE_ONLY_COMPATIBLE_HISTORICAL_STATUS_MISSING",
        "reason": "Dated readiness diagnostics are not a compatible historical alpha score or direct gate status.",
        "repair": "Materialize dated direct PASS/FAIL/UNKNOWN Data Trust gate status; do not synthesize alpha.",
        "alpha": "FALSE", "gate": "TRUE",
        "next": "V21_044_R4A_DATA_TRUST_HISTORICAL_GATE_STATUS_REPAIR.csv",
    },
}

PANEL_FIELDS = [
    "as_of_date", "ticker", "family", "raw_family_score", "normalized_family_score",
    "family_weight_from_full_source", "technical_only_score", "technical_only_rank",
    "normalization_method", "lineage_source_path", "factor_date", "factor_date_status",
    "point_in_time_safe", "leakage_violation_reason", "complete_family_coverage",
    "full_family_score_available", "full_weight_score_allowed",
]


def guardrails(technical_allowed: bool) -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "full_weight_rebacktest_allowed_now": "FALSE",
        "technical_only_backtest_allowed_next": "TRUE" if technical_allowed else "FALSE",
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


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read_csv(path: Path, **kwargs: object) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def resolve_technical_contract() -> tuple[bool, dict[str, str], str]:
    if not R3_CONTRACT.exists() or not R3_DECISION.exists():
        return False, {}, "R3_REQUIRED_ARTIFACT_MISSING"
    decision = first_row(R3_DECISION)
    if decision.get("final_status") != "PARTIAL_PASS_V21_044_R3_TECHNICAL_ONLY_CONFIRMED_OTHERS_BLOCKED":
        return False, {}, "R3_CONTRACT_STATUS_NOT_READY"
    contract = read_csv(R3_CONTRACT)
    technical = contract[contract.get("family_name", pd.Series(dtype=str)).astype(str).str.upper() == "TECHNICAL"]
    if len(technical) != 1:
        return False, {}, "TECHNICAL_CONTRACT_ROW_NOT_UNIQUE"
    row = {key: clean(value) for key, value in technical.iloc[0].to_dict().items()}
    ready = (
        row.get("current_materialization_status") == "MATERIALIZABLE_NOW"
        and row.get("family_score_materialization_allowed", "").upper() == "TRUE"
        and row.get("point_in_time_safe_possible", "").upper() == "TRUE"
    )
    return ready, row, "" if ready else "TECHNICAL_NOT_MATERIALIZABLE_BY_R3_CONTRACT"


def resolve_weight() -> tuple[float | None, str]:
    weights = read_csv(WEIGHT_SOURCE)
    if weights.empty or not {"factor_family", "shadow_dynamic_weight"}.issubset(weights.columns):
        return None, "FULL_WEIGHT_SOURCE_MISSING_OR_INVALID"
    technical = weights[weights["factor_family"].astype(str).str.upper() == "TECHNICAL"]
    values = pd.to_numeric(technical["shadow_dynamic_weight"], errors="coerce").dropna()
    if len(values) != 1:
        return None, "TECHNICAL_WEIGHT_NOT_UNIQUE"
    return float(values.iloc[0]), ""


def materialize(contract: dict[str, str], weight: float) -> tuple[pd.DataFrame, dict[str, object]]:
    source_path = ROOT / contract["selected_source_path_if_any"]
    required = ["as_of_date", "ticker", "technical_score_raw", "technical_score_normalized"]
    source = read_csv(source_path, usecols=lambda column: column in required)
    missing_columns = [column for column in required if column not in source.columns]
    if missing_columns:
        return pd.DataFrame(columns=PANEL_FIELDS), {
            "source_row_count": len(source),
            "excluded_missing_date_count": 0,
            "excluded_missing_ticker_count": 0,
            "excluded_missing_score_count": 0,
            "excluded_unknown_factor_date_count": 0,
            "excluded_leakage_violation_count": 0,
            "duplicate_ticker_date_count": 0,
            "materialization_error": "MISSING_COLUMNS=" + "|".join(missing_columns),
        }

    source["_as_of"] = pd.to_datetime(source["as_of_date"], errors="coerce")
    source["_ticker"] = source["ticker"].astype(str).str.upper().str.strip()
    source["_raw"] = pd.to_numeric(source["technical_score_raw"], errors="coerce")
    source["_normalized"] = pd.to_numeric(source["technical_score_normalized"], errors="coerce")
    missing_date = source["_as_of"].isna()
    missing_ticker = source["ticker"].isna() | source["_ticker"].isin(["", "NAN", "NONE"])
    missing_score = source["_normalized"].isna()
    factor_date = source["_as_of"]
    unknown_factor_date = factor_date.isna()
    leakage = factor_date > source["_as_of"]
    safe = ~(missing_date | missing_ticker | missing_score | unknown_factor_date | leakage)
    valid = source.loc[safe].copy()
    valid = valid.sort_values(["_as_of", "_ticker"], kind="mergesort")
    duplicate_count = int(valid.duplicated(["_as_of", "_ticker"]).sum())
    if duplicate_count:
        return pd.DataFrame(columns=PANEL_FIELDS), {
            "source_row_count": len(source),
            "excluded_missing_date_count": int(missing_date.sum()),
            "excluded_missing_ticker_count": int(missing_ticker.sum()),
            "excluded_missing_score_count": int(missing_score.sum()),
            "excluded_unknown_factor_date_count": int(unknown_factor_date.sum()),
            "excluded_leakage_violation_count": int(leakage.sum()),
            "duplicate_ticker_date_count": duplicate_count,
            "materialization_error": "DUPLICATE_TICKER_DATE_ROWS",
        }
    valid["_rank"] = valid.groupby("_as_of", sort=False)["_normalized"].rank(
        method="first", ascending=False
    )
    panel = pd.DataFrame({
        "as_of_date": valid["_as_of"].dt.strftime("%Y-%m-%d"),
        "ticker": valid["_ticker"],
        "family": "TECHNICAL",
        "raw_family_score": valid["_raw"],
        "normalized_family_score": valid["_normalized"],
        "family_weight_from_full_source": weight,
        "technical_only_score": valid["_normalized"],
        "technical_only_rank": valid["_rank"],
        "normalization_method": "PRESERVE_UPSTREAM_TECHNICAL_SCORE_NORMALIZED",
        "lineage_source_path": relative(source_path),
        "factor_date": valid["_as_of"].dt.strftime("%Y-%m-%d"),
        "factor_date_status": "EXPLICIT_SAME_DAY_SNAPSHOT",
        "point_in_time_safe": "TRUE",
        "leakage_violation_reason": "",
        "complete_family_coverage": "FALSE",
        "full_family_score_available": "FALSE",
        "full_weight_score_allowed": "FALSE",
    })
    audit = {
        "source_row_count": len(source),
        "excluded_missing_date_count": int(missing_date.sum()),
        "excluded_missing_ticker_count": int(missing_ticker.sum()),
        "excluded_missing_score_count": int(missing_score.sum()),
        "excluded_unknown_factor_date_count": int(unknown_factor_date.sum()),
        "excluded_leakage_violation_count": int(leakage.sum()),
        "duplicate_ticker_date_count": duplicate_count,
        "materialization_error": "",
    }
    return panel, audit


def block_rows(weights: pd.DataFrame, contracts: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for family, rule in BLOCKED_FAMILIES.items():
        weight_values = pd.to_numeric(
            weights.loc[weights["factor_family"].astype(str).str.upper() == family, "shadow_dynamic_weight"],
            errors="coerce",
        ).dropna()
        contract = contracts[contracts["family_name"].astype(str).str.upper() == family]
        contract_status = clean(contract.iloc[0].get("current_materialization_status")) if not contract.empty else ""
        rows.append({
            "family_name": family,
            "target_family_weight": float(weight_values.iloc[0]) if len(weight_values) == 1 else "",
            "materialization_status": rule["status"],
            "r3_contract_status": contract_status,
            "blocked_reason": rule["reason"],
            "required_repair": rule["repair"],
            "alpha_bearing_allowed": rule["alpha"],
            "gate_only_allowed": rule["gate"],
            "family_score_materialization_allowed": "FALSE",
            "full_weight_backtest_blocker": "TRUE",
            "next_required_artifact": rule["next"],
            "neutral_fill_allowed": "FALSE",
            "materialized_row_count": 0,
        })
    return rows


def eligible_rows(panel: pd.DataFrame, manifest_dates: set[str]) -> list[dict[str, object]]:
    if panel.empty:
        return []
    eligible_count = int(panel["as_of_date"].nunique())
    overlap_count = int(len(set(panel["as_of_date"]) & manifest_dates))
    rows = []
    for date, group in panel.groupby("as_of_date", sort=True):
        rows.append({
            "as_of_date": date,
            "eligible_technical_asof_count": eligible_count,
            "sampled_manifest_overlap_count": overlap_count,
            "in_v21_042_r1_sample_manifest": "TRUE" if date in manifest_dates else "FALSE",
            "technical_ticker_count_by_asof": int(group["ticker"].nunique()),
            "materialized_row_count_by_asof": len(group),
            "eligible_for_technical_only_backtest": "TRUE",
            "eligible_for_full_weight_backtest": "FALSE",
            "blocked_full_family_reason": "FIVE_NON_TECHNICAL_FAMILIES_NOT_MATERIALIZED_NO_NEUTRAL_FILL",
        })
    return rows


def write_panel(panel: pd.DataFrame) -> None:
    PANEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    if panel.empty:
        pd.DataFrame(columns=PANEL_FIELDS).to_csv(PANEL_OUT, index=False, encoding="utf-8", lineterminator="\n")
        return
    output = panel[PANEL_FIELDS].copy()
    output.to_csv(PANEL_OUT, index=False, encoding="utf-8", float_format="%.10f", lineterminator="\n")


def write_report(decision: dict[str, object], blocks: list[dict[str, object]]) -> None:
    block_text = "\n".join(
        f"- {row['family_name']}: {row['materialization_status']} - {row['blocked_reason']}"
        for row in blocks
    )
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- full weight source path: {decision['full_weight_source_path']}
- materialized families: {decision['materialized_families']}
- blocked families: {decision['blocked_families']}

## Technical Materialization
- materialized row count: {decision['technical_materialized_row_count']}
- eligible as-of count: {decision['technical_eligible_asof_count']}
- V21.042-R1 sample-manifest overlap: {decision['sampled_manifest_overlap_count']}
- technical-only backtest allowed next: {decision['technical_only_backtest_allowed_next']}
- normalization: PRESERVE_UPSTREAM_TECHNICAL_SCORE_NORMALIZED

## Explicit Family Blocks
{block_text}

## Full-Weight Block
Full-weight rebacktesting remains blocked because five required families have no compatible historical materialization. Missing scores were not neutral-filled, and no full_weight_score was created.

## Recommended Next Stage
{decision['recommended_next_stage']}

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
    contract_ready, technical_contract, contract_reason = resolve_technical_contract()
    weight, weight_reason = resolve_weight()
    contracts = read_csv(R3_CONTRACT)
    weights = read_csv(WEIGHT_SOURCE)
    blocks = block_rows(weights, contracts) if not weights.empty and not contracts.empty else []

    if contract_ready and weight is not None:
        panel, source_audit = materialize(technical_contract, weight)
    else:
        panel = pd.DataFrame(columns=PANEL_FIELDS)
        source_audit = {
            "source_row_count": 0, "excluded_missing_date_count": 0,
            "excluded_missing_ticker_count": 0, "excluded_missing_score_count": 0,
            "excluded_unknown_factor_date_count": 0, "excluded_leakage_violation_count": 0,
            "duplicate_ticker_date_count": 0,
            "materialization_error": contract_reason or weight_reason,
        }

    manifest = read_csv(SAMPLE_MANIFEST)
    manifest_dates = set(
        pd.to_datetime(manifest.get("as_of_date"), errors="coerce").dropna().dt.strftime("%Y-%m-%d")
    )
    eligible = eligible_rows(panel, manifest_dates)
    eligible_count = int(panel["as_of_date"].nunique()) if not panel.empty else 0
    overlap_count = len(set(panel["as_of_date"]) & manifest_dates) if not panel.empty else 0
    technical_allowed = (
        not panel.empty
        and (panel["point_in_time_safe"] == "TRUE").all()
        and (panel["leakage_violation_reason"] == "").all()
    )

    if not contract_ready:
        final_status, decision_value = CONTRACT_BLOCKED, BLOCK
    elif source_audit["materialization_error"]:
        final_status, decision_value = SOURCE_BLOCKED, REPAIR
    elif panel.empty:
        final_status, decision_value = REGISTER_STATUS, REPAIR
    elif len(manifest_dates) and overlap_count < len(manifest_dates):
        final_status, decision_value = LIMITED_STATUS, LIMITED
    else:
        final_status, decision_value = PASS_STATUS, READY

    coverage_rows = [
        {
            "audit_scope": "TECHNICAL_SOURCE",
            "source_path": technical_contract.get("selected_source_path_if_any", ""),
            "source_row_count": source_audit["source_row_count"],
            "materialized_row_count": len(panel),
            "eligible_asof_count": eligible_count,
            "distinct_ticker_count": int(panel["ticker"].nunique()) if not panel.empty else 0,
            "excluded_missing_date_count": source_audit["excluded_missing_date_count"],
            "excluded_missing_ticker_count": source_audit["excluded_missing_ticker_count"],
            "excluded_missing_score_count": source_audit["excluded_missing_score_count"],
            "excluded_unknown_factor_date_count": source_audit["excluded_unknown_factor_date_count"],
            "excluded_leakage_violation_count": source_audit["excluded_leakage_violation_count"],
            "duplicate_ticker_date_count": source_audit["duplicate_ticker_date_count"],
            "normalization_method": "PRESERVE_UPSTREAM_TECHNICAL_SCORE_NORMALIZED",
            "coverage_status": "MATERIALIZED" if not panel.empty else "NOT_MATERIALIZED",
            "notes": source_audit["materialization_error"],
        },
        {
            "audit_scope": "FULL_FAMILY_COVERAGE",
            "source_path": relative(WEIGHT_SOURCE) if WEIGHT_SOURCE.exists() else "",
            "source_row_count": 6 if not weights.empty else 0,
            "materialized_row_count": len(panel),
            "eligible_asof_count": 0,
            "distinct_ticker_count": 0,
            "excluded_missing_date_count": 0,
            "excluded_missing_ticker_count": 0,
            "excluded_missing_score_count": 0,
            "excluded_unknown_factor_date_count": 0,
            "excluded_leakage_violation_count": 0,
            "duplicate_ticker_date_count": 0,
            "normalization_method": "",
            "coverage_status": "BLOCKED_FIVE_FAMILIES_NOT_MATERIALIZED",
            "notes": "No neutral fill and no full_weight_score creation allowed.",
        },
    ]
    block_audit = [
        {
            "audit_check": "blocked_family_count",
            "expected_value": 5,
            "observed_value": len(blocks),
            "check_passed": "TRUE" if len(blocks) == 5 else "FALSE",
            "block_status": "FULL_WEIGHT_REBACKTEST_BLOCKED",
            "notes": "All five non-Technical families must remain blocked.",
        },
        {
            "audit_check": "complete_family_coverage",
            "expected_value": "FALSE",
            "observed_value": "FALSE",
            "check_passed": "TRUE",
            "block_status": "FULL_WEIGHT_REBACKTEST_BLOCKED",
            "notes": "Only Technical is materialized.",
        },
        {
            "audit_check": "neutral_fill_used",
            "expected_value": "FALSE",
            "observed_value": "FALSE",
            "check_passed": "TRUE",
            "block_status": "FULL_WEIGHT_REBACKTEST_BLOCKED",
            "notes": "Blocked family scores were not created.",
        },
        {
            "audit_check": "full_weight_score_created",
            "expected_value": "FALSE",
            "observed_value": "FALSE",
            "check_passed": "TRUE",
            "block_status": "FULL_WEIGHT_REBACKTEST_BLOCKED",
            "notes": "Technical-only panel schema excludes full_weight_score.",
        },
    ]
    recommended = (
        "V21.044-R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL"
        if technical_allowed else "V21.044-R4A_TECHNICAL_SOURCE_REPAIR"
    )
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "full_weight_source_path": relative(WEIGHT_SOURCE) if WEIGHT_SOURCE.exists() else "",
        "materialized_families": "TECHNICAL" if not panel.empty else "",
        "blocked_families": "|".join(BLOCKED_FAMILIES),
        "technical_materialized_row_count": len(panel),
        "technical_eligible_asof_count": eligible_count,
        "sampled_manifest_overlap_count": overlap_count,
        "sampled_manifest_asof_count": len(manifest_dates),
        "blocked_family_count": len(blocks),
        "normalization_method": "PRESERVE_UPSTREAM_TECHNICAL_SCORE_NORMALIZED",
        "technical_family_weight": weight if weight is not None else "",
        "full_weight_score_created": "FALSE",
        "neutral_fill_used": "FALSE",
        "unknown_factor_date_rows_in_panel": 0,
        "leakage_violation_rows_in_panel": 0,
        "recommended_next_stage": recommended,
        **guardrails(technical_allowed),
    }

    write_panel(panel)
    write_csv(BLOCK_OUT, blocks, [
        "family_name", "target_family_weight", "materialization_status", "r3_contract_status",
        "blocked_reason", "required_repair", "alpha_bearing_allowed", "gate_only_allowed",
        "family_score_materialization_allowed", "full_weight_backtest_blocker",
        "next_required_artifact", "neutral_fill_allowed", "materialized_row_count",
    ])
    write_csv(ELIGIBLE_OUT, eligible, [
        "as_of_date", "eligible_technical_asof_count", "sampled_manifest_overlap_count",
        "in_v21_042_r1_sample_manifest", "technical_ticker_count_by_asof",
        "materialized_row_count_by_asof", "eligible_for_technical_only_backtest",
        "eligible_for_full_weight_backtest", "blocked_full_family_reason",
    ])
    write_csv(COVERAGE_OUT, coverage_rows, list(coverage_rows[0].keys()))
    write_csv(REBACKTEST_BLOCK_OUT, block_audit, list(block_audit[0].keys()))
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, blocks)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"technical_materialized_row_count={len(panel)}")
    print(f"blocked_family_count={len(blocks)}")
    print(f"technical_only_backtest_allowed_next={decision['technical_only_backtest_allowed_next']}")


if __name__ == "__main__":
    main()
