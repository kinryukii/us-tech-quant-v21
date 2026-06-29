#!/usr/bin/env python
"""Research-only PIT lineage diagnosis and full-family historical panel builder."""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R2_FULL_WEIGHT_PIT_LINEAGE_REPAIR_AND_HISTORICAL_SCORE_PANEL_BUILDER"
PASS_STATUS = "PASS_V21_044_R2_FULL_WEIGHT_PIT_PANEL_READY"
LIMITED_STATUS = "PARTIAL_PASS_V21_044_R2_FULL_WEIGHT_PIT_PANEL_LIMITED_COVERAGE"
DIAGNOSIS_STATUS = "PARTIAL_PASS_V21_044_R2_LINEAGE_DIAGNOSIS_READY_PANEL_NOT_BUILT"
NO_ROWS_STATUS = "BLOCKED_V21_044_R2_NO_PIT_SAFE_HISTORICAL_FULL_FAMILY_ROWS"
SOURCE_STATUS = "BLOCKED_V21_044_R2_FULL_WEIGHT_SOURCE_NOT_FOUND"
UNSAFE_STATUS = "BLOCKED_V21_044_R2_LINEAGE_REPAIR_UNSAFE"

ALLOW_NEXT = "FULL_WEIGHT_REBACKTEST_ALLOWED_NEXT"
ALLOW_LIMITED = "FULL_WEIGHT_REBACKTEST_ALLOWED_WITH_LIMITED_COVERAGE"
NEED_DATES = "NEED_HISTORICAL_FACTOR_DATE_MATERIALIZATION"
NEED_SCORES = "NEED_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION"
BLOCK = "BLOCK_FULL_WEIGHT_REBACKTEST_UNTIL_PIT_LINEAGE_FIXED"

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
WEIGHT_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R1_DECISION = REVIEW / "V21_044_R1_FULL_WEIGHT_DECISION_SUMMARY.csv"
R1_SELECTED = REVIEW / "V21_044_R1_SELECTED_FULL_WEIGHT_SOURCE_AUDIT.csv"
SAMPLE_MANIFEST = ROOT / "outputs" / "v21" / "backtest" / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
TECHNICAL_SNAPSHOT = ROOT / "outputs" / "v21" / "factors" / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
TECHNICAL_SUMMARY = ROOT / "outputs" / "v21" / "factors" / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"
FULL_SCORE_TABLE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
PIT_LINEAGE = ROOT / "outputs" / "v20" / "consolidation" / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
LIMITED_SCORE_LAYER = ROOT / "outputs" / "v20" / "consolidation" / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
BACKTEST_INPUT_LAYER = ROOT / "outputs" / "v20" / "consolidation" / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"

DISCOVERY_OUT = REVIEW / "V21_044_R2_PIT_LINEAGE_ARTIFACT_DISCOVERY.csv"
REPAIR_OUT = REVIEW / "V21_044_R2_PIT_LINEAGE_REPAIR_AUDIT.csv"
PANEL_OUT = REVIEW / "V21_044_R2_FULL_WEIGHT_HISTORICAL_SCORE_PANEL.csv"
ELIGIBLE_OUT = REVIEW / "V21_044_R2_FULL_WEIGHT_PANEL_ELIGIBLE_ASOF_MANIFEST.csv"
COVERAGE_OUT = REVIEW / "V21_044_R2_FULL_WEIGHT_PANEL_COVERAGE_AUDIT.csv"
DECISION_OUT = REVIEW / "V21_044_R2_FULL_WEIGHT_PANEL_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER / "V21_044_R2_FULL_WEIGHT_PIT_LINEAGE_REPAIR_AND_PANEL_BUILDER_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER / "CURRENT_V21_044_R2_FULL_WEIGHT_PIT_LINEAGE_REPAIR_AND_PANEL_BUILDER_REPORT.md"

EXPECTED = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
SEARCH_ROOTS = [
    ROOT / "outputs" / "v21" / "factors",
    ROOT / "outputs" / "v21" / "consolidation",
    ROOT / "outputs" / "v21" / "backtest",
    ROOT / "outputs" / "v21" / "review",
    ROOT / "outputs" / "v20" / "factors",
    ROOT / "outputs" / "v20" / "consolidation",
    ROOT / "outputs" / "v20" / "price_history",
]

DISCOVERY_FIELDS = [
    "candidate_path", "row_count", "column_count", "detected_date_columns",
    "detected_as_of_columns", "detected_factor_date_columns",
    "detected_snapshot_date_columns", "detected_ticker_columns",
    "detected_family_columns", "detected_factor_columns", "detected_score_columns",
    "detected_weight_columns", "min_detected_date", "max_detected_date",
    "distinct_as_of_count", "distinct_ticker_count", "family_coverage_count",
    "expected_family_coverage", "usable_for_pit_lineage",
    "usable_for_full_family_panel", "rejection_reason",
]
PANEL_FIELDS = [
    "as_of_date", "ticker", "family", "raw_family_score", "normalized_family_score",
    "family_weight", "weighted_family_score", "full_weight_score", "full_weight_rank",
    "lineage_source_path", "factor_date", "factor_date_status", "source_strength",
    "point_in_time_safe", "leakage_violation_reason",
    "complete_family_coverage_per_ticker_date", "missing_expected_families",
    "data_trust_role",
]


def guardrails() -> dict[str, str]:
    return {
        "research_only": "TRUE",
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


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def read_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, nrows=nrows)


def first_row(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def normalize_family(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", "_", clean(value).upper()).strip("_")
    aliases = {
        "FUNDAMENTALS": "FUNDAMENTAL",
        "TECHNICALS": "TECHNICAL",
        "STRATEGIES": "STRATEGY",
        "REGIME": "MARKET_REGIME",
        "MARKETREGIME": "MARKET_REGIME",
        "DATA_TRUSTWORTHINESS": "DATA_TRUST",
        "DATATRUST": "DATA_TRUST",
        "TRUST": "DATA_TRUST",
    }
    return aliases.get(text, text)


def list_text(values: list[str]) -> str:
    return "|".join(values)


def parse_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_localize(None)


def classify_columns(columns: list[str]) -> dict[str, list[str]]:
    lower = {column: column.lower() for column in columns}
    date_cols = [
        column for column, name in lower.items()
        if "date" in name and not any(token in name for token in ["forward", "maturity", "exit"])
    ]
    asof_cols = [
        column for column, name in lower.items()
        if name in {
            "as_of_date", "effective_observation_date", "observation_date",
            "data_as_of_date", "run_as_of_date", "ranking_as_of_date",
        }
    ]
    factor_date_cols = [
        column for column, name in lower.items()
        if name in {"factor_date", "factor_input_as_of_date", "feature_date", "effective_price_date"}
    ]
    snapshot_cols = [
        column for column, name in lower.items()
        if name in {"snapshot_date", "price_date", "signal_date", "latest_price_date"}
    ]
    return {
        "date": date_cols,
        "asof": asof_cols,
        "factor_date": factor_date_cols,
        "snapshot": snapshot_cols,
        "ticker": [column for column, name in lower.items() if name in {"ticker", "symbol", "normalized_ticker"}],
        "family": [column for column, name in lower.items() if name in {"factor_family", "factor_category", "family", "family_name"}],
        "factor": [column for column, name in lower.items() if name in {"factor_name", "factor_id", "subfactor_name", "factor_input_name"}],
        "score": [
            column for column, name in lower.items()
            if ("score" in name or "contribution" in name)
            and not any(token in name for token in [
                "forward", "future", "benchmark_relative", "weight", "allowed",
                "created", "status", "count", "coverage",
            ])
        ],
        "weight": [column for column, name in lower.items() if "weight" in name],
    }


def candidate_paths() -> list[Path]:
    explicit = {
        WEIGHT_SOURCE, R1_DECISION, R1_SELECTED, SAMPLE_MANIFEST, TECHNICAL_SNAPSHOT,
        TECHNICAL_SUMMARY, FULL_SCORE_TABLE, PIT_LINEAGE, LIMITED_SCORE_LAYER,
        BACKTEST_INPUT_LAYER,
    }
    discovered: set[Path] = set(explicit)
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            try:
                header = next(csv.reader(path.open("r", encoding="utf-8-sig", newline="")), [])
            except (OSError, UnicodeDecodeError, StopIteration):
                continue
            names = [column.lower() for column in header]
            has_date = any("date" in name for name in names)
            has_ticker = any(name in {"ticker", "symbol", "normalized_ticker"} for name in names)
            has_factor_semantics = (
                any("factor" in name or "family" in name for name in names)
                or any(any(family.lower() in name for family in EXPECTED) for name in names)
            )
            has_score = any("score" in name or "contribution" in name for name in names)
            if has_date and has_ticker and has_factor_semantics and has_score:
                discovered.add(path)
    return sorted(discovered, key=lambda path: relative(path).lower())


def artifact_discovery(path: Path) -> dict[str, object]:
    base = {field: "" for field in DISCOVERY_FIELDS}
    base["candidate_path"] = relative(path)
    if not path.exists():
        base["rejection_reason"] = "FILE_NOT_FOUND"
        return base
    try:
        df = read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        base["rejection_reason"] = f"READ_ERROR_{type(exc).__name__}"
        return base
    kinds = classify_columns(list(df.columns))
    date_series = pd.Series(dtype="datetime64[ns]")
    selected_asof = (kinds["asof"] or kinds["snapshot"] or kinds["date"])[:1]
    if selected_asof:
        date_series = parse_dates(df[selected_asof[0]])
    family_values: set[str] = set()
    for column in kinds["family"]:
        family_values |= {
            normalize_family(value) for value in df[column].dropna().unique()
            if normalize_family(value) in EXPECTED
        }
    for column in df.columns:
        upper = normalize_family(column)
        for family in EXPECTED:
            if family in upper and ("SCORE" in upper or "CONTRIBUTION" in upper):
                family_values.add(family)
    explicit_asof = bool(kinds["asof"] or kinds["snapshot"])
    explicit_factor_date = bool(kinds["factor_date"])
    known_snapshot = path == TECHNICAL_SNAPSHOT and "as_of_date" in df.columns
    ticker_ok = bool(kinds["ticker"])
    score_ok = any(pd.to_numeric(df[column], errors="coerce").notna().any() for column in kinds["score"])
    family_ok = bool(family_values)
    factor_series = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    if kinds["factor_date"]:
        factor_series = parse_dates(df[kinds["factor_date"][0]])
    elif known_snapshot:
        factor_series = date_series.copy()
    valid_date_pairs = (
        date_series.notna()
        & factor_series.notna()
        & (factor_series <= date_series)
    ) if len(date_series) == len(df) else pd.Series(False, index=df.index)
    pit_usable = (
        explicit_asof and ticker_ok and score_ok and family_ok
        and (explicit_factor_date or known_snapshot) and valid_date_pairs.any()
    )
    full_usable = pit_usable and set(EXPECTED).issubset(family_values)
    reasons = []
    if not explicit_asof:
        reasons.append("NO_EXPLICIT_AS_OF_OR_SNAPSHOT_DATE")
    if not ticker_ok:
        reasons.append("NO_EXPLICIT_TICKER")
    if not score_ok:
        reasons.append("NO_EXPLICIT_SCORE")
    if not family_ok:
        reasons.append("NO_EXPECTED_FAMILY_MAPPING")
    if not explicit_factor_date and not known_snapshot:
        reasons.append("FACTOR_DATE_UNKNOWN")
    elif not valid_date_pairs.any():
        reasons.append("NO_VALID_FACTOR_DATE_ON_OR_BEFORE_AS_OF_DATE")
    if family_ok and not set(EXPECTED).issubset(family_values):
        reasons.append("INCOMPLETE_EXPECTED_FAMILY_COVERAGE")
    base.update({
        "row_count": len(df),
        "column_count": len(df.columns),
        "detected_date_columns": list_text(kinds["date"]),
        "detected_as_of_columns": list_text(kinds["asof"]),
        "detected_factor_date_columns": list_text(kinds["factor_date"]),
        "detected_snapshot_date_columns": list_text(kinds["snapshot"]),
        "detected_ticker_columns": list_text(kinds["ticker"]),
        "detected_family_columns": list_text(kinds["family"]),
        "detected_factor_columns": list_text(kinds["factor"]),
        "detected_score_columns": list_text(kinds["score"]),
        "detected_weight_columns": list_text(kinds["weight"]),
        "min_detected_date": date_series.min().strftime("%Y-%m-%d") if date_series.notna().any() else "",
        "max_detected_date": date_series.max().strftime("%Y-%m-%d") if date_series.notna().any() else "",
        "distinct_as_of_count": int(date_series.dropna().dt.normalize().nunique()),
        "distinct_ticker_count": int(df[kinds["ticker"][0]].dropna().astype(str).nunique()) if ticker_ok else 0,
        "family_coverage_count": len(family_values),
        "expected_family_coverage": list_text(sorted(family_values)),
        "usable_for_pit_lineage": "TRUE" if pit_usable else "FALSE",
        "usable_for_full_family_panel": "TRUE" if full_usable else "FALSE",
        "rejection_reason": "|".join(reasons),
    })
    return base


def resolve_weights() -> tuple[dict[str, float], str]:
    if not WEIGHT_SOURCE.exists():
        return {}, "SOURCE_NOT_FOUND"
    df = read_csv(WEIGHT_SOURCE)
    required = {"factor_family", "shadow_dynamic_weight"}
    if not required.issubset(df.columns):
        return {}, "SOURCE_SCHEMA_INVALID"
    weights = {
        normalize_family(row["factor_family"]): float(row["shadow_dynamic_weight"])
        for row in df.to_dict("records")
        if normalize_family(row.get("factor_family")) in EXPECTED
        and pd.notna(pd.to_numeric(pd.Series([row.get("shadow_dynamic_weight")]), errors="coerce").iloc[0])
    }
    if set(weights) != set(EXPECTED):
        return weights, "SOURCE_FAMILY_COVERAGE_INCOMPLETE"
    return weights, "FULL_CURRENT_WEIGHT_SOURCE_RESOLVED"


def diagnose_repair(weights: dict[str, float]) -> tuple[list[dict[str, object]], pd.DataFrame, int, int]:
    rows: list[dict[str, object]] = []
    technical = read_csv(TECHNICAL_SNAPSHOT)
    technical["as_of_date_parsed"] = pd.to_datetime(technical.get("as_of_date"), errors="coerce")
    technical["score_numeric"] = pd.to_numeric(technical.get("technical_score_normalized"), errors="coerce")
    technical_safe = technical[
        technical["as_of_date_parsed"].notna()
        & technical.get("ticker", pd.Series(index=technical.index, dtype=object)).notna()
        & technical["score_numeric"].notna()
    ].copy()
    rows.append({
        "source_path": relative(TECHNICAL_SNAPSHOT),
        "source_role": "PARTIAL_HISTORICAL_TECHNICAL_FAMILY_SOURCE",
        "row_count": len(technical),
        "mapped_family": "TECHNICAL",
        "as_of_date_column": "as_of_date",
        "factor_date_column": "as_of_date",
        "factor_date_status": "EXPLICIT_SAME_DAY_SNAPSHOT",
        "source_strength": "STRONG_EXPLICIT_CONTENT_DATE",
        "point_in_time_safe_row_count": len(technical_safe),
        "unknown_factor_date_row_count": 0,
        "usable_full_family_panel_row_count": 0,
        "future_return_input_used": "FALSE",
        "missing_expected_families": list_text([f for f in EXPECTED if f != "TECHNICAL"]),
        "repair_action": "DATE_LINEAGE_ACCEPTED_FOR_TECHNICAL_ONLY",
        "rejection_reason": "INCOMPLETE_EXPECTED_FAMILY_COVERAGE",
    })

    lineage = read_csv(PIT_LINEAGE)
    factor_dates = lineage.get("factor_input_as_of_date", pd.Series(index=lineage.index, dtype=object)).astype(str).str.strip()
    unknown = factor_dates.str.upper().isin(["", "UNKNOWN", "NAN", "NAT"]).sum()
    explicit = len(lineage) - int(unknown)
    rows.append({
        "source_path": relative(PIT_LINEAGE),
        "source_role": "SIX_FAMILY_CURRENT_SCORE_LINEAGE",
        "row_count": len(lineage),
        "mapped_family": list_text(EXPECTED),
        "as_of_date_column": "ranking_as_of_date",
        "factor_date_column": "factor_input_as_of_date",
        "factor_date_status": "UNKNOWN" if unknown else "EXPLICIT",
        "source_strength": "EXPLICIT_COLUMNS_UNKNOWN_VALUES",
        "point_in_time_safe_row_count": explicit,
        "unknown_factor_date_row_count": int(unknown),
        "usable_full_family_panel_row_count": 0,
        "future_return_input_used": "FALSE",
        "missing_expected_families": "",
        "repair_action": "NO_DATE_REPAIR_POSSIBLE_FROM_LOCAL_COLUMNS",
        "rejection_reason": "UNKNOWN_FACTOR_DATE_ROWS_NOT_PIT_SAFE",
    })

    full = read_csv(FULL_SCORE_TABLE)
    rows.append({
        "source_path": relative(FULL_SCORE_TABLE),
        "source_role": "SIX_FAMILY_CURRENT_CROSS_SECTION",
        "row_count": len(full),
        "mapped_family": list_text(EXPECTED),
        "as_of_date_column": "",
        "factor_date_column": "",
        "factor_date_status": "UNKNOWN",
        "source_strength": "NO_EXPLICIT_DATE_LINEAGE",
        "point_in_time_safe_row_count": 0,
        "unknown_factor_date_row_count": len(full),
        "usable_full_family_panel_row_count": 0,
        "future_return_input_used": "FALSE",
        "missing_expected_families": "",
        "repair_action": "EXCLUDED_UNDATED_CURRENT_CROSS_SECTION",
        "rejection_reason": "NO_EXPLICIT_AS_OF_DATE_OR_FACTOR_DATE",
    })

    limited = read_csv(LIMITED_SCORE_LAYER)
    limited_dates = pd.to_datetime(limited.get("effective_observation_date"), errors="coerce")
    limited_scores = pd.to_numeric(limited.get("factor_score_value"), errors="coerce")
    limited_pit = limited.get("score_pit_safe", pd.Series(index=limited.index, dtype=object)).astype(str).str.upper() == "TRUE"
    limited_safe = int((limited_dates.notna() & limited_scores.notna() & limited_pit).sum())
    rows.append({
        "source_path": relative(LIMITED_SCORE_LAYER),
        "source_role": "DATED_DATA_TRUST_READINESS_DIAGNOSTIC",
        "row_count": len(limited),
        "mapped_family": "DATA_TRUST",
        "as_of_date_column": "effective_observation_date",
        "factor_date_column": "effective_price_date",
        "factor_date_status": "EXPLICIT",
        "source_strength": "STRONG_EXPLICIT_CONTENT_DATE",
        "point_in_time_safe_row_count": limited_safe,
        "unknown_factor_date_row_count": 0,
        "usable_full_family_panel_row_count": 0,
        "future_return_input_used": "FALSE",
        "missing_expected_families": list_text([f for f in EXPECTED if f != "DATA_TRUST"]),
        "repair_action": "PRESERVED_AS_DIAGNOSTIC_ONLY",
        "rejection_reason": "READINESS_DIAGNOSTIC_NOT_ALPHA_FAMILY_CONTRIBUTION|ALLOWED_FOR_BACKTEST_FALSE",
    })
    pit_safe_count = len(technical_safe) + limited_safe + explicit
    return rows, technical_safe, pit_safe_count, int(unknown)


def coverage_audit(technical_safe: pd.DataFrame, manifest_dates: set[str]) -> list[dict[str, object]]:
    rows = []
    if technical_safe.empty:
        return [{
            "as_of_date": "",
            "ticker_count_by_asof": 0,
            "complete_ticker_count_by_asof": 0,
            "family_coverage_count": 0,
            "resolved_family_list": "",
            "missing_expected_families": list_text(EXPECTED),
            "complete_family_coverage_asof": "FALSE",
            "in_v21_042_r1_sample_manifest": "FALSE",
            "eligible_for_full_weight_rebacktest": "FALSE",
            "rejection_reason": "NO_PIT_SAFE_FAMILY_ROWS",
        }]
    for date, group in technical_safe.groupby(technical_safe["as_of_date_parsed"].dt.strftime("%Y-%m-%d")):
        rows.append({
            "as_of_date": date,
            "ticker_count_by_asof": int(group["ticker"].astype(str).nunique()),
            "complete_ticker_count_by_asof": 0,
            "family_coverage_count": 1,
            "resolved_family_list": "TECHNICAL",
            "missing_expected_families": list_text([family for family in EXPECTED if family != "TECHNICAL"]),
            "complete_family_coverage_asof": "FALSE",
            "in_v21_042_r1_sample_manifest": "TRUE" if date in manifest_dates else "FALSE",
            "eligible_for_full_weight_rebacktest": "FALSE",
            "rejection_reason": "MISSING_FUNDAMENTAL_STRATEGY_RISK_MARKET_REGIME_DATA_TRUST",
        })
    return rows


def write_report(decision: dict[str, object], discovery: list[dict[str, object]], repair: list[dict[str, object]]) -> None:
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- full weight source path: {decision['full_weight_source_path']}
- full weight family coverage: {decision['full_weight_family_coverage']}
- full-weight rebacktest allowed next: {decision['full_weight_rebacktest_allowed_next']}

## Why V21.044-R1 Was Blocked
The six-family current score table has no explicit historical as-of date. Its {decision['unknown_factor_date_row_count']} lineage rows retain UNKNOWN factor dates, so they cannot be attached to prior sample dates without fabrication.

## Artifact Discovery
- candidate artifacts inspected: {len(discovery)}
- artifacts usable for PIT lineage: {sum(row['usable_for_pit_lineage'] == 'TRUE' for row in discovery)}
- artifacts usable for a complete six-family panel: {sum(row['usable_for_full_family_panel'] == 'TRUE' for row in discovery)}
- PIT-safe diagnostic rows: {decision['pit_safe_row_count']}
- UNKNOWN factor_date rows: {decision['unknown_factor_date_row_count']}

## Historical Panel
- built historical panel row count: {decision['historical_panel_row_count']}
- eligible as-of count: {decision['eligible_asof_count']}
- overlap with V21.042-R1 sample manifest: {decision['sampled_manifest_overlap_count']}
- partial technical as-of count: {decision['partial_technical_asof_count']}
- partial technical manifest overlap: {decision['partial_technical_manifest_overlap_count']}
- missing family summary: {decision['missing_family_summary']}

## Limitations
- V21.038 provides explicit same-day technical snapshots only; five required families remain absent.
- V20.15 provides Data Trust readiness diagnostics, not the Data Trust family contribution used by the full score model.
- Current six-family V20.108 rows remain undated and were excluded.
- File names and file modification timestamps were not used to create factor dates.
- No missing date, family score, return, or benchmark value was fabricated or zero-filled.

## Guardrails
research_only = TRUE
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
    discovery = [artifact_discovery(path) for path in candidate_paths()]

    manifest = read_csv(SAMPLE_MANIFEST)
    manifest_dates = set(
        pd.to_datetime(manifest.get("as_of_date"), errors="coerce").dropna().dt.strftime("%Y-%m-%d")
    )

    if weight_status != "FULL_CURRENT_WEIGHT_SOURCE_RESOLVED":
        repair: list[dict[str, object]] = []
        technical_safe = pd.DataFrame()
        pit_safe_count = 0
        unknown_count = 0
        final_status = SOURCE_STATUS
        decision_value = BLOCK
    else:
        repair, technical_safe, pit_safe_count, unknown_count = diagnose_repair(weights)
        final_status = DIAGNOSIS_STATUS
        decision_value = NEED_SCORES

    coverage = coverage_audit(technical_safe, manifest_dates)
    partial_dates = {
        row["as_of_date"] for row in coverage
        if clean(row.get("as_of_date")) and row.get("family_coverage_count") == 1
    }
    partial_overlap = len(partial_dates & manifest_dates)

    # A full-weight panel is intentionally empty until all six families coexist
    # for a ticker/date with explicit PIT-safe lineage.
    panel_rows: list[dict[str, object]] = []
    eligible_rows: list[dict[str, object]] = []
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "full_weight_source_path": relative(WEIGHT_SOURCE) if WEIGHT_SOURCE.exists() else "",
        "full_weight_source_status": weight_status,
        "full_weight_family_coverage": list_text(sorted(weights)),
        "full_weight_family_coverage_count": len(weights),
        "pit_safe_row_count": pit_safe_count,
        "unknown_factor_date_row_count": unknown_count,
        "historical_panel_row_count": len(panel_rows),
        "eligible_asof_count": len(eligible_rows),
        "sampled_manifest_overlap_count": 0,
        "full_family_complete_asof_count": 0,
        "rejected_asof_count": len(partial_dates),
        "partial_technical_asof_count": len(partial_dates),
        "partial_technical_manifest_overlap_count": partial_overlap,
        "missing_family_summary": "FUNDAMENTAL|STRATEGY|RISK|MARKET_REGIME|DATA_TRUST",
        "data_trust_weight": weights.get("DATA_TRUST", ""),
        "data_trust_role": "ALPHA_BEARING_IN_FULL_WEIGHT_SOURCE|HISTORICAL_FAMILY_SCORE_NOT_MATERIALIZED",
        "full_weight_rebacktest_allowed_next": "FALSE",
        "v21_044_r1_block_reason": "NO_DATED_POINT_IN_TIME_FULL_FAMILY_SCORE_PANEL",
        "file_modified_time_used_for_factor_date": "FALSE",
        "factor_dates_fabricated": "FALSE",
        "family_scores_fabricated": "FALSE",
        **guardrails(),
    }

    write_csv(DISCOVERY_OUT, discovery, DISCOVERY_FIELDS)
    write_csv(REPAIR_OUT, repair, [
        "source_path", "source_role", "row_count", "mapped_family",
        "as_of_date_column", "factor_date_column", "factor_date_status",
        "source_strength", "point_in_time_safe_row_count",
        "unknown_factor_date_row_count", "usable_full_family_panel_row_count",
        "future_return_input_used", "missing_expected_families", "repair_action",
        "rejection_reason",
    ])
    write_csv(PANEL_OUT, panel_rows, PANEL_FIELDS)
    write_csv(ELIGIBLE_OUT, eligible_rows, [
        "as_of_date", "eligible_asof_count", "sampled_manifest_overlap_count",
        "full_family_complete_asof_count", "ticker_count_by_asof",
        "complete_ticker_count_by_asof", "rejected_asof_count", "rejection_reason",
    ])
    write_csv(COVERAGE_OUT, coverage, [
        "as_of_date", "ticker_count_by_asof", "complete_ticker_count_by_asof",
        "family_coverage_count", "resolved_family_list", "missing_expected_families",
        "complete_family_coverage_asof", "in_v21_042_r1_sample_manifest",
        "eligible_for_full_weight_rebacktest", "rejection_reason",
    ])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, discovery, repair)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"pit_safe_row_count={pit_safe_count}")
    print(f"built_panel_row_count={len(panel_rows)}")
    print(f"eligible_asof_count={len(eligible_rows)}")


if __name__ == "__main__":
    main()
