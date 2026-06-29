#!/usr/bin/env python
"""Resolve full factor-family weights and run a PIT-safe rebacktest when possible.

This stage is research-only. It reads local artifacts and never downloads data,
mutates rankings or weights, or creates broker/trade/execution instructions.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.044-R1_FULL_WEIGHT_SOURCE_RESOLUTION_AND_REBACKTEST"
PASS_STATUS = "PASS_V21_044_R1_FULL_WEIGHT_REBACKTEST_READY"
BENCHMARK_WARNING_STATUS = "PARTIAL_PASS_V21_044_R1_FULL_WEIGHT_REBACKTEST_WITH_BENCHMARK_WARNING"
BASELINE_STATUS = "PARTIAL_PASS_V21_044_R1_BASELINE_WEIGHT_FALLBACK_REBACKTEST_READY"
AMBIGUOUS_STATUS = "PARTIAL_PASS_V21_044_R1_FULL_WEIGHT_SOURCE_AMBIGUOUS"
SOURCE_BLOCKED_STATUS = "BLOCKED_V21_044_R1_FULL_WEIGHT_SOURCE_NOT_FOUND"
DATES_BLOCKED_STATUS = "BLOCKED_V21_044_R1_NO_ELIGIBLE_RANDOM_ASOF_DATES"
LEAKAGE_BLOCKED_STATUS = "BLOCKED_V21_044_R1_LEAKAGE_AUDIT_FAILED"

DECISION_SUPPORT = "FULL_CURRENT_WEIGHT_SUPPORTS_CONTINUED_SHADOW_OBSERVATION_ONLY"
DECISION_TECH = "FULL_CURRENT_WEIGHT_LAGS_TECHNICAL_ONLY_KEEP_TECHNICAL_ON_WATCHLIST"
DECISION_QQQ = "FULL_CURRENT_WEIGHT_LAGS_QQQ_KEEP_BASELINE_AND_REVIEW"
DECISION_BASELINE = "BASELINE_WEIGHT_FALLBACK_SUPPORTS_CONTINUED_OBSERVATION_ONLY"
DECISION_RESOLVE = "FULL_WEIGHT_SOURCE_RESOLUTION_REQUIRED_BEFORE_MORE_BACKTESTS"
DECISION_BLOCK = "BLOCK_SHADOW_OBSERVATION_REVIEW"

ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = ROOT / "outputs" / "v21" / "review"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
BACKTEST_DIR = ROOT / "outputs" / "v21" / "backtest"
V20_CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
V20_FACTORS = ROOT / "outputs" / "v20" / "factors"
V21_FACTORS = ROOT / "outputs" / "v21" / "factors"

MANIFEST = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
UPSTREAM_PANEL = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"
UPSTREAM_SUMMARY = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
UPSTREAM_BENCHMARK = BACKTEST_DIR / "V21_042_R2_VARIANT_WINDOW_BENCHMARK_SUMMARY.csv"
UPSTREAM_TECH_WEIGHTS = V21_FACTORS / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
FULL_SCORE_TABLE = V20_CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
PIT_LINEAGE = V20_CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
QQQ_SOURCE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

CANDIDATE_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_SOURCE_CANDIDATE_AUDIT.csv"
SELECTED_OUT = REVIEW_DIR / "V21_044_R1_SELECTED_FULL_WEIGHT_SOURCE_AUDIT.csv"
FAMILY_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_FAMILY_COVERAGE_AUDIT.csv"
PANEL_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_REBACKTEST_PANEL.csv"
SUMMARY_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_VARIANT_WINDOW_SUMMARY.csv"
BENCHMARK_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_BENCHMARK_COMPARISON.csv"
LEAKAGE_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_LEAKAGE_AUDIT.csv"
DECISION_OUT = REVIEW_DIR / "V21_044_R1_FULL_WEIGHT_DECISION_SUMMARY.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_044_R1_FULL_WEIGHT_SOURCE_RESOLUTION_AND_REBACKTEST_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER_DIR / "CURRENT_V21_044_R1_FULL_WEIGHT_SOURCE_RESOLUTION_AND_REBACKTEST_REPORT.md"

EXPECTED_FAMILIES = [
    "FUNDAMENTAL",
    "TECHNICAL",
    "STRATEGY",
    "RISK",
    "MARKET_REGIME",
    "DATA_TRUST",
]
WINDOWS = ["5D", "10D", "20D", "60D"]
RANDOM_SEED = 21042

CANDIDATES = [
    V20_CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv",
    V20_CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    V20_CONSOLIDATION / "V20_98B_R4_RESEARCH_ONLY_BASE_WEIGHT_OPERATOR_APPROVAL_PACKET.csv",
    V20_CONSOLIDATION / "V20_98B_R3_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv",
    V20_FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv",
    V20_FACTORS / "V20_154_LIMITED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
    V20_FACTORS / "V20_157_REDUCED_SHADOW_DYNAMIC_WEIGHT_PROPOSAL.csv",
    UPSTREAM_TECH_WEIGHTS,
]

AUDIT_FIELDS = [
    "candidate_path", "candidate_status", "classification", "row_count",
    "family_column_present", "factor_column_present", "weight_column_present",
    "family_count", "resolved_family_list", "missing_expected_families",
    "weight_sum", "nonzero_weight_count", "data_trust_weight",
    "current_weight_evidence", "baseline_weight_evidence",
    "source_hash_if_available", "selected_as_full_weight_source", "rejection_reason",
]
PANEL_FIELDS = [
    "variant_name", "as_of_date", "ticker", "forward_return_window", "rank", "score",
    "realized_forward_return", "point_in_time_safe", "unsafe_reason",
]
SUMMARY_FIELDS = [
    "variant_name", "forward_return_window", "sampled_asof_count", "total_scored_rows",
    "top20_mean_forward_return", "top20_median_forward_return",
    "top20_hit_rate_vs_universe", "universe_mean_forward_return",
    "top20_excess_vs_universe", "top20_excess_vs_QQQ", "top20_hit_rate_vs_QQQ",
    "positive_asof_ratio_vs_QQQ", "top50_excess_vs_universe", "top50_excess_vs_QQQ",
    "top_decile_excess_vs_universe", "top_decile_excess_vs_QQQ",
    "long_short_top_bottom_decile_spread", "rank_ic_spearman_mean",
    "rank_ic_spearman_median", "leakage_violation_count", "price_missing_count",
    "benchmark_missing_count",
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def normalize_family(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", "_", clean(value).upper()).strip("_")
    aliases = {
        "FUNDAMENTALS": "FUNDAMENTAL",
        "TECHNICALS": "TECHNICAL",
        "STRATEGIES": "STRATEGY",
        "MARKETREGIME": "MARKET_REGIME",
        "REGIME": "MARKET_REGIME",
        "DATA_TRUSTWORTHINESS": "DATA_TRUST",
        "DATATRUST": "DATA_TRUST",
        "TRUST": "DATA_TRUST",
    }
    return aliases.get(text, text)


def detect_column(columns: list[str], exact: list[str], contains: str = "") -> str:
    lower = {column.lower(): column for column in columns}
    for name in exact:
        if name in lower:
            return lower[name]
    if contains:
        for column in columns:
            if contains in column.lower():
                return column
    return ""


def candidate_audit(path: Path) -> tuple[dict[str, object], pd.DataFrame, str, str]:
    base = {
        "candidate_path": relative(path),
        "candidate_status": "CANDIDATE_NOT_FOUND",
        "classification": "INVALID_WEIGHT_SOURCE",
        "row_count": 0,
        "family_column_present": "FALSE",
        "factor_column_present": "FALSE",
        "weight_column_present": "FALSE",
        "family_count": 0,
        "resolved_family_list": "",
        "missing_expected_families": "|".join(EXPECTED_FAMILIES),
        "weight_sum": "",
        "nonzero_weight_count": 0,
        "data_trust_weight": "",
        "current_weight_evidence": "",
        "baseline_weight_evidence": "",
        "source_hash_if_available": "",
        "selected_as_full_weight_source": "FALSE",
        "rejection_reason": "FILE_NOT_FOUND",
    }
    if not path.exists():
        return base, pd.DataFrame(), "", ""
    try:
        df = pd.read_csv(path, low_memory=False)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        base.update({
            "candidate_status": "CANDIDATE_READ_ERROR",
            "source_hash_if_available": sha256(path),
            "rejection_reason": type(exc).__name__,
        })
        return base, pd.DataFrame(), "", ""

    columns = list(df.columns)
    family_col = detect_column(columns, ["factor_family", "family", "family_name"], "family")
    factor_col = detect_column(columns, ["factor_name", "factor_id", "subfactor_name"])
    weight_preferences = [
        "shadow_dynamic_weight", "normalized_shadow_dynamic_weight", "active_research_base_weight",
        "approved_research_base_weight", "proposed_scoring_weight", "reduced_shadow_proposed_weight",
        "shadow_proposed_weight", "variant_weight", "template_weight",
    ]
    weight_col = detect_column(columns, weight_preferences)
    families = []
    if family_col:
        families = sorted({
            normalize_family(value) for value in df[family_col].dropna().tolist()
            if normalize_family(value)
        })
    expected_present = sorted(set(families) & set(EXPECTED_FAMILIES))
    missing = [family for family in EXPECTED_FAMILIES if family not in expected_present]
    numeric = pd.to_numeric(df[weight_col], errors="coerce") if weight_col else pd.Series(dtype=float)
    path_text = relative(path).upper()
    columns_text = "|".join(columns).upper()
    full = not missing and bool(family_col) and bool(weight_col) and numeric.notna().sum() >= 6
    technical_only = (
        "TECHNICAL_SUBFACTOR" in path_text
        or (not family_col and ("SUBFACTOR" in columns_text or "VARIANT_NAME" in columns_text))
    )
    simulation_or_proposal = any(token in path_text for token in ["SIMULATION", "PROPOSAL"])
    current_evidence = ""
    baseline_evidence = ""
    if "SHADOW_DYNAMIC_WEIGHT" in columns_text and not simulation_or_proposal:
        current_evidence = "SHADOW_DYNAMIC_WEIGHT_COLUMN|RESEARCH_ONLY_CURRENT_CONFIGURATION"
    if any(token in columns_text for token in ["ACTIVE_RESEARCH_BASE_WEIGHT", "APPROVED_RESEARCH_BASE_WEIGHT"]):
        baseline_evidence = "ACTIVE_OR_APPROVED_RESEARCH_BASE_WEIGHT_COLUMN"

    if technical_only:
        classification = "TECHNICAL_SUBFACTOR_ONLY_SOURCE"
        reason = "TECHNICAL_SUBFACTOR_SCOPE_ONLY"
    elif full and current_evidence:
        classification = "FULL_CURRENT_WEIGHT_SOURCE"
        reason = ""
    elif full and baseline_evidence and not simulation_or_proposal:
        classification = "FULL_BASELINE_WEIGHT_SOURCE"
        reason = ""
    elif full and simulation_or_proposal:
        classification = "MIXED_OR_AMBIGUOUS_WEIGHT_SOURCE"
        reason = "RESEARCH_SIMULATION_OR_PROPOSAL_NOT_ACTIVE_CURRENT_SOURCE"
    elif expected_present and missing:
        classification = "PARTIAL_FAMILY_WEIGHT_SOURCE"
        reason = "MISSING_EXPECTED_FAMILIES"
    elif family_col or weight_col:
        classification = "MIXED_OR_AMBIGUOUS_WEIGHT_SOURCE"
        reason = "FULL_FAMILY_WEIGHT_SEMANTICS_NOT_PROVEN"
    else:
        classification = "INVALID_WEIGHT_SOURCE"
        reason = "NO_USABLE_FAMILY_AND_WEIGHT_COLUMNS"

    data_trust_weight: object = ""
    if family_col and weight_col:
        normalized = df[family_col].map(normalize_family)
        dt = pd.to_numeric(df.loc[normalized == "DATA_TRUST", weight_col], errors="coerce").dropna()
        if not dt.empty:
            data_trust_weight = float(dt.iloc[0])
    base.update({
        "candidate_status": "CANDIDATE_INSPECTED",
        "classification": classification,
        "row_count": len(df),
        "family_column_present": "TRUE" if family_col else "FALSE",
        "factor_column_present": "TRUE" if factor_col else "FALSE",
        "weight_column_present": "TRUE" if weight_col else "FALSE",
        "family_count": len(expected_present),
        "resolved_family_list": "|".join(expected_present),
        "missing_expected_families": "|".join(missing),
        "weight_sum": float(numeric.sum()) if numeric.notna().any() else "",
        "nonzero_weight_count": int((numeric.fillna(0) != 0).sum()),
        "data_trust_weight": data_trust_weight,
        "current_weight_evidence": current_evidence,
        "baseline_weight_evidence": baseline_evidence,
        "source_hash_if_available": sha256(path),
        "rejection_reason": reason,
    })
    return base, df, family_col, weight_col


def resolve_source() -> tuple[list[dict[str, object]], dict[str, object] | None, pd.DataFrame, str, str]:
    audits: list[dict[str, object]] = []
    loaded: dict[str, tuple[pd.DataFrame, str, str]] = {}
    for path in CANDIDATES:
        row, df, family_col, weight_col = candidate_audit(path)
        audits.append(row)
        loaded[relative(path)] = (df, family_col, weight_col)

    current = [row for row in audits if row["classification"] == "FULL_CURRENT_WEIGHT_SOURCE"]
    baseline = [row for row in audits if row["classification"] == "FULL_BASELINE_WEIGHT_SOURCE"]
    selected = current[0] if current else (baseline[0] if baseline else None)
    if selected:
        selected["selected_as_full_weight_source"] = "TRUE"
        selected["candidate_status"] = "SELECTED_FULL_WEIGHT_SOURCE"
        selected["rejection_reason"] = ""
        df, family_col, weight_col = loaded[str(selected["candidate_path"])]
        return audits, selected, df, family_col, weight_col
    return audits, None, pd.DataFrame(), "", ""


def family_coverage(selected: dict[str, object] | None, df: pd.DataFrame, family_col: str, weight_col: str) -> list[dict[str, object]]:
    rows = []
    selected_path = clean(selected.get("candidate_path")) if selected else ""
    normalized = df[family_col].map(normalize_family) if family_col and not df.empty else pd.Series(dtype=str)
    for family in EXPECTED_FAMILIES:
        mask = normalized == family if not normalized.empty else pd.Series(dtype=bool)
        original = "|".join(sorted({clean(value) for value in df.loc[mask, family_col].tolist()})) if mask.any() else ""
        weights = pd.to_numeric(df.loc[mask, weight_col], errors="coerce").dropna() if mask.any() and weight_col else pd.Series(dtype=float)
        rows.append({
            "selected_source_path": selected_path,
            "expected_family": family,
            "family_present": "TRUE" if mask.any() else "FALSE",
            "original_family_labels": original,
            "resolved_weight": float(weights.iloc[0]) if not weights.empty else "",
            "weight_fabricated": "FALSE",
            "coverage_status": "PRESENT" if mask.any() and not weights.empty else "MISSING",
            "missing_reason": "" if mask.any() and not weights.empty else "NO_SOURCE_ROW_OR_NUMERIC_WEIGHT",
        })
    return rows


def benchmark_audit() -> dict[str, object]:
    row = {
        "benchmark_symbol": "QQQ",
        "benchmark_source_path": relative(QQQ_SOURCE),
        "benchmark_source_status": "BENCHMARK_SOURCE_NOT_FOUND",
        "benchmark_price_field": "",
        "coverage_start": "",
        "coverage_end": "",
        "benchmark_row_count": 0,
        "benchmark_missing_count": "",
        "alignment_warning_count": "",
        "notes": "No download attempted.",
    }
    if not QQQ_SOURCE.exists():
        return row
    df = read_csv(QQQ_SOURCE)
    lower = {column.lower(): column for column in df.columns}
    symbol_col = lower.get("symbol") or lower.get("ticker")
    date_col = lower.get("date") or lower.get("as_of_date")
    adjusted_col = lower.get("adjusted_close") or lower.get("adj_close")
    close_col = lower.get("close")
    if not symbol_col or not date_col or not (adjusted_col or close_col):
        row["benchmark_source_status"] = "BENCHMARK_SOURCE_INVALID_SCHEMA"
        return row
    qqq = df[df[symbol_col].astype(str).str.upper().str.strip() == "QQQ"].copy()
    price_col = adjusted_col or close_col
    qqq["_date"] = pd.to_datetime(qqq[date_col], errors="coerce")
    qqq["_price"] = pd.to_numeric(qqq[price_col], errors="coerce")
    qqq = qqq[qqq["_date"].notna() & (qqq["_price"] > 0)]
    if len(qqq) < 2:
        row["benchmark_source_status"] = "BENCHMARK_SOURCE_NO_VALID_QQQ_ROWS"
        return row
    row.update({
        "benchmark_source_status": "AVAILABLE_LOCAL_QQQ_SOURCE",
        "benchmark_price_field": price_col,
        "coverage_start": qqq["_date"].min().strftime("%Y-%m-%d"),
        "coverage_end": qqq["_date"].max().strftime("%Y-%m-%d"),
        "benchmark_row_count": len(qqq),
        "notes": "Local QQQ source resolved; comparison runs only if full-family PIT scores are eligible.",
    })
    return row


def pit_eligibility() -> tuple[bool, list[dict[str, object]], str]:
    rows: list[dict[str, object]] = []
    if not FULL_SCORE_TABLE.exists():
        rows.append({
            "source_path": relative(FULL_SCORE_TABLE),
            "as_of_date": "",
            "ticker": "",
            "point_in_time_safe": "FALSE",
            "included_in_performance_aggregation": "FALSE",
            "leakage_violation_reason": "FULL_FAMILY_SCORE_TABLE_NOT_FOUND",
        })
        return False, rows, "FULL_FAMILY_SCORE_TABLE_NOT_FOUND"
    scores = read_csv(FULL_SCORE_TABLE)
    date_columns = [column for column in scores.columns if column.lower() in {"as_of_date", "ranking_as_of_date", "feature_date"}]
    if not date_columns:
        rows.append({
            "source_path": relative(FULL_SCORE_TABLE),
            "as_of_date": "",
            "ticker": "",
            "point_in_time_safe": "FALSE",
            "included_in_performance_aggregation": "FALSE",
            "leakage_violation_reason": "FULL_FAMILY_SCORE_TABLE_HAS_NO_AS_OF_DATE",
        })
        if PIT_LINEAGE.exists():
            lineage = read_csv(PIT_LINEAGE)
            unknown = int(
                lineage.get("factor_input_as_of_date", pd.Series(dtype=str))
                .astype(str).str.upper().isin(["", "UNKNOWN", "NAN"]).sum()
            )
            rows.append({
                "source_path": relative(PIT_LINEAGE),
                "as_of_date": "",
                "ticker": "",
                "point_in_time_safe": "FALSE",
                "included_in_performance_aggregation": "FALSE",
                "leakage_violation_reason": f"PIT_LINEAGE_UNKNOWN_FACTOR_DATES={unknown}",
            })
        return False, rows, "NO_DATED_POINT_IN_TIME_FULL_FAMILY_SCORE_PANEL"
    return False, [{
        "source_path": relative(FULL_SCORE_TABLE),
        "as_of_date": "",
        "ticker": "",
        "point_in_time_safe": "FALSE",
        "included_in_performance_aggregation": "FALSE",
        "leakage_violation_reason": "DATED_FULL_FAMILY_PANEL_REQUIRES_EXPLICIT_VALIDATION_NOT_AVAILABLE",
    }], "NO_VALIDATED_POINT_IN_TIME_FULL_FAMILY_SCORE_PANEL"


def selected_audit(selected: dict[str, object] | None, reason: str) -> dict[str, object]:
    return {
        "selected_source_path": clean(selected.get("candidate_path")) if selected else "",
        "selected_source_classification": clean(selected.get("classification")) if selected else "",
        "selection_status": "SELECTED" if selected else "NOT_SELECTED",
        "selection_priority": "FULL_CURRENT_THEN_FULL_BASELINE",
        "full_current_weight_source_found": "TRUE" if selected and selected["classification"] == "FULL_CURRENT_WEIGHT_SOURCE" else "FALSE",
        "full_baseline_fallback_used": "TRUE" if selected and selected["classification"] == "FULL_BASELINE_WEIGHT_SOURCE" else "FALSE",
        "historical_full_family_score_status": reason,
        "rebacktest_allowed": "FALSE",
        "source_hash": clean(selected.get("source_hash_if_available")) if selected else "",
        **guardrails(),
    }


def placeholder_performance(reason: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    panel = [{
        "variant_name": "FULL_CURRENT_WEIGHT",
        "as_of_date": "",
        "ticker": "",
        "forward_return_window": "",
        "rank": "",
        "score": "",
        "realized_forward_return": "",
        "point_in_time_safe": "FALSE",
        "unsafe_reason": reason,
    }]
    summary = []
    for variant in [
        "FULL_CURRENT_WEIGHT",
        "TECHNICAL_SUBFACTOR_CURRENT_WEIGHT",
        "EQUAL_WEIGHT_BASELINE",
        "CURRENT_WEIGHT_PLUS_RSI_CANDIDATE",
        "GLOBAL_RSI_CANDIDATE",
    ]:
        for window in WINDOWS:
            summary.append({
                "variant_name": variant,
                "forward_return_window": window,
                "sampled_asof_count": 0,
                "total_scored_rows": 0,
                "leakage_violation_count": 0,
                "price_missing_count": 0,
                "benchmark_missing_count": 0,
            })
    return panel, summary


def write_report(
    decision: dict[str, object],
    coverage: list[dict[str, object]],
    benchmark: dict[str, object],
) -> None:
    coverage_table = "\n".join(
        f"| {row['expected_family']} | {row['family_present']} | {fmt(row['resolved_weight'])} | {row['original_family_labels']} |"
        for row in coverage
    )
    missing = [row["expected_family"] for row in coverage if row["family_present"] != "TRUE"]
    data_trust = next((row for row in coverage if row["expected_family"] == "DATA_TRUST"), {})
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Decision
- final_status: {decision['final_status']}
- decision: {decision['decision']}
- selected weight source: {decision['selected_weight_source']}
- selected weight source classification: {decision['selected_source_classification']}

## Family Coverage
| Expected family | Present | Weight | Original label |
|---|---:|---:|---|
{coverage_table}

Missing families: {"|".join(missing) if missing else "NONE"}

Data Trust weight: {fmt(data_trust.get("resolved_weight", ""))}. Data Trust is not treated as zero-weight or gate-only by the selected active source.

## Rebacktest Result
- full weight vs previous technical-subfactor source: NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES
- full weight vs equal-weight baseline: NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES
- full weight vs QQQ: NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES
- QQQ source: {benchmark['benchmark_source_path']} ({benchmark['benchmark_source_status']})
- window-balanced result: NOT_AVAILABLE
- no-60D result: NOT_AVAILABLE
- RSI candidate review: UPSTREAM_VARIANTS_AVAILABLE_BUT_NOT_COMPARED_TO_UNRUN_FULL_WEIGHT

## Leakage Audit
{decision['leakage_audit_result']}. Current cross-sectional six-family scores were excluded from historical performance aggregation because their as-of lineage is unknown.

## Limitations
- The six-family current research weights are locally resolvable.
- No dated, point-in-time-safe six-family score panel was found for the V21.042-R1 sample dates.
- Applying the current six-family cross-section retrospectively would fabricate historical scores and create look-ahead bias.
- No missing family weight or return was filled with zero.

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
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report, encoding="utf-8")


def main() -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    audits, selected, selected_df, family_col, weight_col = resolve_source()
    coverage = family_coverage(selected, selected_df, family_col, weight_col)
    benchmark = benchmark_audit()

    if not selected:
        final_status = SOURCE_BLOCKED_STATUS
        decision_value = DECISION_RESOLVE
        pit_reason = "FULL_WEIGHT_SOURCE_NOT_FOUND"
        leakage_rows = [{
            "source_path": "",
            "as_of_date": "",
            "ticker": "",
            "point_in_time_safe": "FALSE",
            "included_in_performance_aggregation": "FALSE",
            "leakage_violation_reason": pit_reason,
        }]
    else:
        eligible, leakage_rows, pit_reason = pit_eligibility()
        if not eligible:
            final_status = DATES_BLOCKED_STATUS
            decision_value = DECISION_BLOCK
        else:
            # Reached only after a future local dated full-family panel passes explicit PIT validation.
            final_status = LEAKAGE_BLOCKED_STATUS
            decision_value = DECISION_BLOCK

    panel_rows, summary_rows = placeholder_performance(pit_reason)
    selected_row = selected_audit(selected, pit_reason)
    benchmark_row = {
        **benchmark,
        "variant_name": "FULL_CURRENT_WEIGHT" if selected and selected["classification"] == "FULL_CURRENT_WEIGHT_SOURCE" else "FULL_BASELINE_WEIGHT_FALLBACK",
        "forward_return_window": "",
        "top20_excess_vs_QQQ": "",
        "top20_hit_rate_vs_QQQ": "",
        "positive_asof_ratio_vs_QQQ": "",
        "comparison_status": "NOT_RUN_NO_ELIGIBLE_PIT_FULL_FAMILY_SCORES",
    }
    sampled_count = 0
    if MANIFEST.exists():
        manifest = read_csv(MANIFEST)
        sampled_count = int(manifest.get("as_of_date", pd.Series(dtype=str)).dropna().nunique())
    data_trust_weight = next(
        (row["resolved_weight"] for row in coverage if row["expected_family"] == "DATA_TRUST"), ""
    )
    decision = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision_value,
        "selected_weight_source": clean(selected.get("candidate_path")) if selected else "",
        "selected_source_classification": clean(selected.get("classification")) if selected else "",
        "family_coverage_result": "ALL_EXPECTED_FAMILIES_PRESENT" if selected and all(row["family_present"] == "TRUE" for row in coverage) else "MISSING_EXPECTED_FAMILIES",
        "missing_families": "|".join(row["expected_family"] for row in coverage if row["family_present"] != "TRUE"),
        "data_trust_weight": data_trust_weight,
        "data_trust_role": "SCORING_WEIGHT_IN_SELECTED_SOURCE" if clean(data_trust_weight) else "UNRESOLVED",
        "random_seed": RANDOM_SEED,
        "upstream_manifest_sampled_asof_count": sampled_count,
        "eligible_full_family_asof_count": 0,
        "full_weight_vs_technical_only_result": "NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES",
        "full_weight_vs_equal_weight_result": "NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES",
        "full_weight_vs_QQQ_result": "NOT_COMPUTED_NO_DATED_PIT_FULL_FAMILY_SCORES",
        "current_plus_rsi_result": "UPSTREAM_AVAILABLE_NOT_COMPARABLE_TO_UNRUN_FULL_WEIGHT",
        "window_balanced_result": "NOT_AVAILABLE",
        "no_60d_result": "NOT_AVAILABLE",
        "benchmark_symbol": "QQQ",
        "benchmark_source_path": benchmark["benchmark_source_path"],
        "benchmark_source_status": benchmark["benchmark_source_status"],
        "leakage_audit_result": "BLOCKED_NO_DATED_PIT_FULL_FAMILY_SCORE_PANEL",
        "unsafe_rows_in_performance_aggregation": 0,
        "notes": pit_reason,
        **guardrails(),
    }

    write_csv(CANDIDATE_OUT, audits, AUDIT_FIELDS)
    write_csv(SELECTED_OUT, [selected_row], list(selected_row.keys()))
    write_csv(FAMILY_OUT, coverage, [
        "selected_source_path", "expected_family", "family_present", "original_family_labels",
        "resolved_weight", "weight_fabricated", "coverage_status", "missing_reason",
    ])
    write_csv(PANEL_OUT, panel_rows, PANEL_FIELDS)
    write_csv(SUMMARY_OUT, summary_rows, SUMMARY_FIELDS)
    write_csv(BENCHMARK_OUT, [benchmark_row], list(benchmark_row.keys()))
    write_csv(LEAKAGE_OUT, leakage_rows, [
        "source_path", "as_of_date", "ticker", "point_in_time_safe",
        "included_in_performance_aggregation", "leakage_violation_reason",
    ])
    write_csv(DECISION_OUT, [decision], list(decision.keys()))
    write_report(decision, coverage, benchmark)

    print(f"final_status={final_status}")
    print(f"decision={decision_value}")
    print(f"selected_source_classification={decision['selected_source_classification']}")
    print(f"selected_source_path={decision['selected_weight_source']}")


if __name__ == "__main__":
    main()
