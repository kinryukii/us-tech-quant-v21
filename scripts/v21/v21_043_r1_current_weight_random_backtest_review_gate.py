#!/usr/bin/env python
"""V21.043-R1 current weight random backtest review gate.

Research-only audit of V21.042-R1 random as-of backtest outputs. This stage does
not rerun the backtest and does not mutate official, broker, trade, execution, or
shadow-ranking artifacts.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.043-R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE"

PASS_STATUS = "PASS_V21_043_R1_CURRENT_WEIGHT_REVIEW_READY_FOR_CONTINUED_SHADOW_OBSERVATION"
LIMITED_STATUS = "PARTIAL_PASS_V21_043_R1_CURRENT_WEIGHT_REVIEW_LIMITED_AUDIT"
WARNING_STATUS = "PARTIAL_PASS_V21_043_R1_CURRENT_WEIGHT_REVIEW_WITH_WARNINGS"
BLOCKED_UPSTREAM_STATUS = "BLOCKED_V21_043_R1_UPSTREAM_BACKTEST_NOT_READY"
BLOCKED_LEAKAGE_STATUS = "BLOCKED_V21_043_R1_LEAKAGE_AUDIT_FAILED"
BLOCKED_SOURCE_STATUS = "BLOCKED_V21_043_R1_WEIGHT_SOURCE_UNRESOLVED"

DECISION_ALLOW = "ALLOW_CONTINUED_SHADOW_OBSERVATION_ONLY"
DECISION_ALLOW_SOURCE_WARNING = "ALLOW_CONTINUED_SHADOW_OBSERVATION_WITH_SOURCE_WARNING"
DECISION_MORE_EVIDENCE = "KEEP_BASELINE_AND_COLLECT_MORE_EVIDENCE"
DECISION_REVIEW_SOURCE = "REVIEW_CURRENT_WEIGHT_SOURCE_BEFORE_NEXT_BACKTEST"
DECISION_BLOCK = "BLOCK_SHADOW_OBSERVATION_REVIEW"

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = ROOT / "outputs" / "v21" / "backtest"
OUT_DIR = ROOT / "outputs" / "v21" / "review"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

UPSTREAM_DECISION = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv"
WINDOW_SUMMARY = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
LEAKAGE_AUDIT = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_LEAKAGE_AUDIT.csv"
SAMPLE_MANIFEST = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
SOURCE_AUDIT = BACKTEST_DIR / "V21_042_R1_CURRENT_WEIGHT_SOURCE_AUDIT.csv"
PER_DATE_METRICS = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_PER_DATE_METRICS.csv"
BACKTEST_PANEL = BACKTEST_DIR / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"

UPSTREAM_STATUS_OUT = OUT_DIR / "V21_043_R1_UPSTREAM_STATUS_AUDIT.csv"
SOURCE_SEMANTIC_OUT = OUT_DIR / "V21_043_R1_WEIGHT_SOURCE_SEMANTIC_AUDIT.csv"
WINDOW_OUT = OUT_DIR / "V21_043_R1_WINDOW_CONCENTRATION_AUDIT.csv"
PER_DATE_OUT = OUT_DIR / "V21_043_R1_PER_DATE_STABILITY_AUDIT.csv"
TICKER_OUT = OUT_DIR / "V21_043_R1_TICKER_CONCENTRATION_AUDIT.csv"
RSI_OUT = OUT_DIR / "V21_043_R1_RSI_CANDIDATE_REVIEW.csv"
SAFETY_OUT = OUT_DIR / "V21_043_R1_SAFETY_GUARDRAIL_AUDIT.csv"
DECISION_OUT = OUT_DIR / "V21_043_R1_REVIEW_DECISION_SUMMARY.csv"

REPORT_OUT = READ_CENTER_DIR / "V21_043_R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE_REPORT.md"
CURRENT_REPORT_OUT = READ_CENTER_DIR / "CURRENT_V21_043_R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE_REPORT.md"

TRUE_FALSE_GUARDS = {
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


def yes(value: bool) -> str:
    return "TRUE" if bool(value) else "FALSE"


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.10f}"
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def read_first(path: Path) -> dict[str, str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {}) or {}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def mean_or_blank(values: pd.Series) -> float | str:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return ""
    return float(numeric.mean())


def audit_upstream(summary: dict[str, str]) -> tuple[list[dict[str, object]], bool, list[str]]:
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    if not summary:
        rows.append({
            "audit_check": "upstream_summary_present",
            "expected_value": "TRUE",
            "observed_value": "FALSE",
            "check_passed": "FALSE",
            "severity": "BLOCKING",
            "notes": "Required V21.042-R1 decision summary is missing or empty.",
        })
        return rows, False, warnings

    final_status = clean(summary.get("final_status"))
    status_ok = final_status.startswith("PASS_V21_042_R1") or final_status.startswith("PARTIAL_PASS_V21_042_R1")
    checks = [
        ("upstream_final_status_ready", "PASS_OR_ACCEPTABLE_PARTIAL_PASS", final_status, status_ok, "BLOCKING"),
        ("research_only", "TRUE", clean(summary.get("research_only")).upper(), clean(summary.get("research_only")).upper() == "TRUE", "BLOCKING"),
        ("official_adoption_allowed", "FALSE", clean(summary.get("official_adoption_allowed")).upper(), clean(summary.get("official_adoption_allowed")).upper() == "FALSE", "BLOCKING"),
        ("official_weight_mutation", "FALSE", clean(summary.get("official_weight_mutation")).upper(), clean(summary.get("official_weight_mutation")).upper() == "FALSE", "BLOCKING"),
        ("official_ranking_mutation", "FALSE", clean(summary.get("official_ranking_mutation")).upper(), clean(summary.get("official_ranking_mutation")).upper() == "FALSE", "BLOCKING"),
        ("real_book_action_allowed", "FALSE", clean(summary.get("real_book_action_allowed")).upper(), clean(summary.get("real_book_action_allowed")).upper() == "FALSE", "BLOCKING"),
        ("broker_execution_allowed", "FALSE", clean(summary.get("broker_execution_allowed")).upper(), clean(summary.get("broker_execution_allowed")).upper() == "FALSE", "BLOCKING"),
        ("trade_action_allowed", "FALSE", clean(summary.get("trade_action_allowed")).upper(), clean(summary.get("trade_action_allowed")).upper() == "FALSE", "BLOCKING"),
    ]
    for name, expected, observed, passed, severity in checks:
        rows.append({
            "audit_check": name,
            "expected_value": expected,
            "observed_value": observed,
            "check_passed": yes(passed),
            "severity": severity,
            "notes": "Upstream V21.042-R1 guardrail/status check.",
        })
    return rows, all(row["check_passed"] == "TRUE" for row in rows), warnings


def classify_weight_source(summary: dict[str, str], source_df: pd.DataFrame) -> tuple[list[dict[str, object]], str, str, bool]:
    source_path = clean(summary.get("current_weight_source"))
    lower_path = source_path.lower()
    used = source_df[source_df.get("source_status", pd.Series(dtype=str)).astype(str) == "USED_CURRENT_WEIGHT_SOURCE"] if not source_df.empty else pd.DataFrame()
    resolved_rows = 0
    family_coverage = ""
    full_family_evidence = False

    if not used.empty:
        if "resolved_weight_rows" in used.columns:
            resolved_rows = int(pd.to_numeric(used["resolved_weight_rows"], errors="coerce").fillna(0).max())
        family_cols = [c for c in used.columns if "family" in c.lower()]
        if family_cols:
            family_coverage = "|".join(f"{col}={clean(used.iloc[0].get(col))}" for col in family_cols)
            full_family_evidence = any("full" in clean(used.iloc[0].get(col)).lower() for col in family_cols)

    if not source_path:
        classification = "UNKNOWN_WEIGHT_SOURCE"
        warning = "Current weight source path is missing."
    elif full_family_evidence:
        classification = "FULL_CURRENT_WEIGHT_SOURCE"
        warning = ""
    elif "technical" in lower_path and ("subfactor" in lower_path or "sub_factor" in lower_path):
        classification = "TECHNICAL_SUBFACTOR_ONLY_SOURCE"
        warning = "Source path and audit indicate a technical subfactor weight artifact, not full current-weight family coverage."
    elif "weight" in lower_path and not full_family_evidence:
        classification = "MIXED_OR_AMBIGUOUS_WEIGHT_SOURCE"
        warning = "Weight source exists, but full-family coverage evidence was not found."
    else:
        classification = "UNKNOWN_WEIGHT_SOURCE"
        warning = "Weight source semantics could not be resolved from available metadata."

    rows = [{
        "source_path": source_path,
        "source_classification": classification,
        "source_warning": warning,
        "resolved_weight_rows": resolved_rows,
        "family_coverage": family_coverage,
        "source_audit_available": yes(not source_df.empty),
        "full_current_weight_source_evidence": yes(full_family_evidence),
        "official_adoption_allowed": "FALSE",
        "adoption_block_reason": "" if classification == "FULL_CURRENT_WEIGHT_SOURCE" else "Source is not clearly FULL_CURRENT_WEIGHT_SOURCE.",
    }]
    return rows, classification, warning, classification != "UNKNOWN_WEIGHT_SOURCE"


def audit_windows(window_df: pd.DataFrame, summary: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, object], bool]:
    fields = [
        "metric_scope", "current_weight_excess", "equal_weight_excess", "current_minus_equal",
        "current_beats_equal", "window_concentration_warning", "notes",
    ]
    if window_df.empty:
        return [{
            "metric_scope": "WINDOW_AUDIT_LIMITED",
            "current_weight_excess": "",
            "equal_weight_excess": "",
            "current_minus_equal": "",
            "current_beats_equal": "",
            "window_concentration_warning": "WINDOW_AUDIT_LIMITED",
            "notes": "V21.042-R1 variant window summary is missing.",
        }], {}, True

    df = window_df.copy()
    df["excess"] = pd.to_numeric(df.get("excess_return_top20_vs_universe"), errors="coerce")
    current = df[df["variant_name"] == "CURRENT_WEIGHT"].copy()
    equal = df[df["variant_name"] == "EQUAL_WEIGHT_BASELINE"].copy()
    current_by_window = dict(zip(current["forward_return_window"].astype(str), current["excess"]))
    equal_by_window = dict(zip(equal["forward_return_window"].astype(str), equal["excess"]))
    common_windows = sorted(set(current_by_window) & set(equal_by_window))

    aggregate_current = float(pd.to_numeric(pd.Series([summary.get("current_weight_mean_excess_top20_vs_universe")]), errors="coerce").iloc[0])
    aggregate_equal = float(pd.to_numeric(pd.Series([summary.get("equal_weight_mean_excess_top20_vs_universe")]), errors="coerce").iloc[0])
    balanced_current = float(pd.Series([current_by_window[w] for w in common_windows], dtype="float64").mean()) if common_windows else np.nan
    balanced_equal = float(pd.Series([equal_by_window[w] for w in common_windows], dtype="float64").mean()) if common_windows else np.nan
    no60_windows = [w for w in common_windows if w != "60D"]
    no60_current = float(pd.Series([current_by_window[w] for w in no60_windows], dtype="float64").mean()) if no60_windows else np.nan
    no60_equal = float(pd.Series([equal_by_window[w] for w in no60_windows], dtype="float64").mean()) if no60_windows else np.nan

    aggregate_beats = aggregate_current > aggregate_equal
    balanced_beats = balanced_current > balanced_equal
    no60_beats = no60_current > no60_equal if not math.isnan(no60_current) and not math.isnan(no60_equal) else False
    only_beats_because_60d = bool(aggregate_beats and balanced_beats and "60D" in common_windows and not no60_beats)
    warning = "WINDOW_CONCENTRATION_WARNING" if only_beats_because_60d else "NO_WINDOW_CONCENTRATION_BLOCK"

    rows: list[dict[str, object]] = [
        {
            "metric_scope": "aggregate_upstream_metric",
            "current_weight_excess": aggregate_current,
            "equal_weight_excess": aggregate_equal,
            "current_minus_equal": aggregate_current - aggregate_equal,
            "current_beats_equal": yes(aggregate_beats),
            "window_concentration_warning": warning,
            "notes": "Uses upstream aggregate top20 excess metric.",
        },
        {
            "metric_scope": "window_balanced_mean_excess",
            "current_weight_excess": balanced_current,
            "equal_weight_excess": balanced_equal,
            "current_minus_equal": balanced_current - balanced_equal,
            "current_beats_equal": yes(balanced_beats),
            "window_concentration_warning": warning,
            "notes": "Each available forward window receives equal weight.",
        },
        {
            "metric_scope": "no_60d_mean_excess",
            "current_weight_excess": no60_current,
            "equal_weight_excess": no60_equal,
            "current_minus_equal": no60_current - no60_equal if not math.isnan(no60_current) and not math.isnan(no60_equal) else "",
            "current_beats_equal": yes(no60_beats),
            "window_concentration_warning": warning,
            "notes": "Excludes 60D to test dependence on the longest window.",
        },
    ]
    for w in common_windows:
        rows.append({
            "metric_scope": f"window_{w}",
            "current_weight_excess": current_by_window[w],
            "equal_weight_excess": equal_by_window[w],
            "current_minus_equal": current_by_window[w] - equal_by_window[w],
            "current_beats_equal": yes(current_by_window[w] > equal_by_window[w]),
            "window_concentration_warning": warning,
            "notes": "Window-level current versus equal-weight baseline comparison.",
        })
    metrics = {
        "aggregate_current": aggregate_current,
        "aggregate_equal": aggregate_equal,
        "balanced_current": balanced_current,
        "balanced_equal": balanced_equal,
        "no60_current": no60_current,
        "no60_equal": no60_equal,
        "window_warning": warning,
    }
    return rows, metrics, only_beats_because_60d


def audit_per_date(per_date_df: pd.DataFrame) -> tuple[list[dict[str, object]], str, bool]:
    if per_date_df.empty:
        return [{
            "audit_scope": "PER_DATE_AUDIT_LIMITED",
            "positive_asof_ratio_top20": "",
            "current_weight_beat_ratio_vs_equal": "",
            "median_per_date_excess": "",
            "top3_positive_contribution_share": "",
            "stability_status": "PER_DATE_AUDIT_LIMITED",
            "notes": "V21.042-R1 per-date metrics are unavailable.",
        }], "PER_DATE_AUDIT_LIMITED", True

    df = per_date_df.copy()
    df["excess"] = pd.to_numeric(df.get("excess_return_top20_vs_universe"), errors="coerce")
    current = df[df["variant_name"] == "CURRENT_WEIGHT"].copy()
    equal = df[df["variant_name"] == "EQUAL_WEIGHT_BASELINE"].copy()
    positive_ratio = float((current["excess"] > 0).mean()) if not current.empty else np.nan
    median_excess = float(current["excess"].median()) if current["excess"].notna().any() else np.nan

    merged = current[["as_of_date", "forward_return_window", "excess"]].merge(
        equal[["as_of_date", "forward_return_window", "excess"]],
        on=["as_of_date", "forward_return_window"],
        how="inner",
        suffixes=("_current", "_equal"),
    )
    beat_ratio = float((merged["excess_current"] > merged["excess_equal"]).mean()) if not merged.empty else np.nan
    positive = current[current["excess"] > 0]["excess"].sort_values(ascending=False)
    top3_share = float(positive.head(3).sum() / positive.sum()) if positive.sum() > 0 else 0.0
    concentrated = top3_share > 0.5
    status = "PER_DATE_CONCENTRATION_WARNING" if concentrated else "PER_DATE_STABILITY_REVIEWED"
    rows = [{
        "audit_scope": "CURRENT_WEIGHT_PER_DATE",
        "positive_asof_ratio_top20": positive_ratio,
        "current_weight_beat_ratio_vs_equal": beat_ratio,
        "median_per_date_excess": median_excess,
        "top3_positive_contribution_share": top3_share,
        "stability_status": status,
        "notes": "Concentration warning triggers when the top 3 positive date/window observations exceed 50% of positive excess.",
    }]
    return rows, status, concentrated


def audit_tickers(panel_df: pd.DataFrame) -> tuple[list[dict[str, object]], str, bool]:
    if panel_df.empty:
        return [{
            "audit_scope": "TICKER_CONCENTRATION_AUDIT_LIMITED",
            "current_weight_top20_rows": "",
            "unique_top20_tickers": "",
            "top5_ticker_row_share": "",
            "top5_return_contribution_share": "",
            "top_tickers": "",
            "concentration_status": "TICKER_CONCENTRATION_AUDIT_LIMITED",
            "notes": "V21.042-R1 backtest panel is unavailable.",
        }], "TICKER_CONCENTRATION_AUDIT_LIMITED", True

    df = panel_df.copy()
    df["rank"] = pd.to_numeric(df.get("rank"), errors="coerce")
    df["realized_forward_return"] = pd.to_numeric(df.get("realized_forward_return"), errors="coerce")
    safe_flags = df.get("point_in_time_safe", pd.Series("TRUE", index=df.index)).astype(str).str.upper()
    top20 = df[(df["variant_name"] == "CURRENT_WEIGHT") & (df["rank"] <= 20) & (safe_flags == "TRUE")].copy()
    if top20.empty:
        status = "TICKER_CONCENTRATION_AUDIT_LIMITED"
        return [{
            "audit_scope": "CURRENT_WEIGHT_TOP20_TICKERS",
            "current_weight_top20_rows": 0,
            "unique_top20_tickers": 0,
            "top5_ticker_row_share": "",
            "top5_return_contribution_share": "",
            "top_tickers": "",
            "concentration_status": status,
            "notes": "No CURRENT_WEIGHT top20 rows were found in the panel.",
        }], status, True

    freq = top20["ticker"].astype(str).value_counts()
    top5_row_share = float(freq.head(5).sum() / len(top20))
    contrib = top20.groupby("ticker")["realized_forward_return"].sum().sort_values(ascending=False)
    positive_sum = contrib[contrib > 0].sum()
    top5_return_share = float(contrib.head(5).sum() / positive_sum) if positive_sum > 0 else 0.0
    dominated = int((freq > 0).sum()) < 5 or top5_return_share > 0.75
    status = "TICKER_CONCENTRATION_WARNING" if dominated else "TICKER_CONCENTRATION_REVIEWED"
    rows = [{
        "audit_scope": "CURRENT_WEIGHT_TOP20_TICKERS",
        "current_weight_top20_rows": len(top20),
        "unique_top20_tickers": int(freq.shape[0]),
        "top5_ticker_row_share": top5_row_share,
        "top5_return_contribution_share": top5_return_share,
        "top_tickers": "|".join(f"{ticker}:{count}" for ticker, count in freq.head(10).items()),
        "concentration_status": status,
        "notes": "Dominance warning triggers with fewer than 5 top20 tickers or top5 positive-return contribution above 75%.",
    }]
    return rows, status, dominated


def review_rsi(window_df: pd.DataFrame) -> tuple[list[dict[str, object]], str]:
    if window_df.empty:
        return [{
            "candidate_name": "RSI_CANDIDATES",
            "candidate_present": "FALSE",
            "window_balanced_excess": "",
            "beats_current_weight": "",
            "standalone_adoption_allowed": "FALSE",
            "watchlist_only": "FALSE",
            "review_status": "RSI_CANDIDATE_REVIEW_LIMITED",
            "notes": "Variant window summary unavailable; no RSI formula was recomputed.",
        }], "RSI_CANDIDATE_REVIEW_LIMITED"

    df = window_df.copy()
    df["excess"] = pd.to_numeric(df.get("excess_return_top20_vs_universe"), errors="coerce")
    current_mean = mean_or_blank(df[df["variant_name"] == "CURRENT_WEIGHT"]["excess"])
    rows: list[dict[str, object]] = []
    statuses: list[str] = []
    for candidate in ["GLOBAL_RSI_CANDIDATE", "CURRENT_WEIGHT_PLUS_RSI_CANDIDATE"]:
        cand = df[df["variant_name"] == candidate].copy()
        present = not cand.empty
        cand_mean = mean_or_blank(cand["excess"]) if present else ""
        mixed_signs = bool(present and (cand["excess"] > 0).any() and (cand["excess"] < 0).any())
        beats_current = bool(present and current_mean != "" and cand_mean != "" and float(cand_mean) > float(current_mean))
        if candidate == "GLOBAL_RSI_CANDIDATE":
            status = "STANDALONE_ADOPTION_BLOCKED_MIXED_OR_UNDERPERFORMING" if mixed_signs or not beats_current else "STANDALONE_ADOPTION_BLOCKED_RESEARCH_ONLY"
            watchlist = "FALSE"
        else:
            status = "WATCHLIST_ONLY" if beats_current else "NO_ADOPTION_COLLECT_MORE_EVIDENCE"
            watchlist = yes(beats_current)
        statuses.append(status)
        rows.append({
            "candidate_name": candidate,
            "candidate_present": yes(present),
            "window_balanced_excess": cand_mean,
            "beats_current_weight": yes(beats_current),
            "standalone_adoption_allowed": "FALSE",
            "watchlist_only": watchlist,
            "review_status": status,
            "notes": "Review uses existing V21.042-R1 candidate outputs only; no RSI formulas are defined or recomputed.",
        })
    return rows, "|".join(statuses)


def audit_safety(leakage_df: pd.DataFrame, summary: dict[str, str]) -> tuple[list[dict[str, object]], str, bool]:
    summary_count = int(float(clean(summary.get("leakage_violation_count")) or 0)) if summary else 0
    detailed_available = not leakage_df.empty
    unsafe_count = 0
    safe_count = 0
    if detailed_available and "point_in_time_safe" in leakage_df.columns:
        safe_flags = leakage_df["point_in_time_safe"].astype(str).str.upper()
        safe_count = int((safe_flags == "TRUE").sum())
        unsafe_count = int((safe_flags != "TRUE").sum())
    material_violation = summary_count > 0 or unsafe_count > 0
    status = "LEAKAGE_AUDIT_FAILED" if material_violation else "LEAKAGE_AUDIT_PASSED_ZERO_VIOLATIONS"
    rows = [{
        "audit_check": "leakage_violation_count",
        "summary_leakage_violation_count": summary_count,
        "detailed_safe_rows": safe_count,
        "detailed_unsafe_rows": unsafe_count,
        "detailed_audit_available": yes(detailed_available),
        "audit_status": status,
        "blocks_review": yes(material_violation),
        "notes": "Unsafe rows must be absent from aggregation or the review is blocked.",
    }]
    return rows, status, material_violation


def guardrail_rows(shadow_observation_allowed: bool) -> list[dict[str, object]]:
    rows = []
    for guard, expected in TRUE_FALSE_GUARDS.items():
        rows.append({
            "guardrail": guard,
            "expected_value": expected,
            "actual_value": expected,
            "guardrail_passed": "TRUE",
            "notes": "Research-only V21.043-R1 review gate guardrail.",
        })
    rows.append({
        "guardrail": "shadow_observation_allowed",
        "expected_value": "TRUE only after pass or non-fatal partial pass",
        "actual_value": yes(shadow_observation_allowed),
        "guardrail_passed": "TRUE",
        "notes": "Observation only; shadow adoption remains FALSE.",
    })
    return rows


def decide(
    upstream_ok: bool,
    source_classification: str,
    source_resolved: bool,
    leakage_block: bool,
    limited: bool,
    warnings: list[str],
) -> tuple[str, str, bool]:
    if not upstream_ok:
        return BLOCKED_UPSTREAM_STATUS, DECISION_BLOCK, False
    if leakage_block:
        return BLOCKED_LEAKAGE_STATUS, DECISION_BLOCK, False
    if not source_resolved:
        return BLOCKED_SOURCE_STATUS, DECISION_REVIEW_SOURCE, False
    if source_classification != "FULL_CURRENT_WEIGHT_SOURCE":
        warnings.append("SOURCE_NOT_FULL_CURRENT_WEIGHT")
    if limited:
        return LIMITED_STATUS, DECISION_ALLOW_SOURCE_WARNING if warnings else DECISION_ALLOW, True
    if warnings:
        decision = DECISION_ALLOW_SOURCE_WARNING if "SOURCE_NOT_FULL_CURRENT_WEIGHT" in warnings else DECISION_MORE_EVIDENCE
        return WARNING_STATUS, decision, True
    return PASS_STATUS, DECISION_ALLOW, True


def build_report(summary_row: dict[str, object], report_bits: dict[str, object]) -> str:
    lines = [
        f"# {STAGE}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Summary",
        f"- final_status: {summary_row['final_status']}",
        f"- decision: {summary_row['decision']}",
        f"- upstream V21.042-R1 status: {summary_row['upstream_final_status']}",
        f"- current weight source classification: {summary_row['weight_source_classification']}",
        f"- source warning: {summary_row['source_warning'] or 'NONE'}",
        "",
        "## Current vs Equal-Weight Baseline",
        f"- aggregate upstream current excess: {fmt(report_bits.get('aggregate_current'))}",
        f"- aggregate upstream equal-weight excess: {fmt(report_bits.get('aggregate_equal'))}",
        f"- window-balanced current excess: {fmt(report_bits.get('balanced_current'))}",
        f"- window-balanced equal-weight excess: {fmt(report_bits.get('balanced_equal'))}",
        f"- no-60D current excess: {fmt(report_bits.get('no60_current'))}",
        f"- no-60D equal-weight excess: {fmt(report_bits.get('no60_equal'))}",
        f"- window concentration result: {report_bits.get('window_result')}",
        "",
        "## Stability And Concentration",
        f"- per-date stability result: {report_bits.get('per_date_result')}",
        f"- ticker concentration result: {report_bits.get('ticker_result')}",
        "",
        "## RSI Candidate Review",
        f"- {report_bits.get('rsi_result')}",
        "",
        "## Leakage Audit",
        f"- leakage audit result: {report_bits.get('leakage_result')}",
        f"- leakage safe rows: {summary_row['leakage_safe_rows']}",
        f"- leakage violation count: {summary_row['leakage_violation_count']}",
        "",
        "## Guardrails",
        "research_only = TRUE",
        "official_adoption_allowed = FALSE",
        "official_weight_mutation = FALSE",
        "official_ranking_mutation = FALSE",
        "real_book_action_allowed = FALSE",
        "broker_execution_allowed = FALSE",
        "trade_action_allowed = FALSE",
        "shadow_gate_allowed = FALSE",
        "shadow_adoption_allowed = FALSE",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)

    upstream_summary = read_first(UPSTREAM_DECISION)
    window_df = read_csv(WINDOW_SUMMARY)
    source_df = read_csv(SOURCE_AUDIT)
    per_date_df = read_csv(PER_DATE_METRICS)
    panel_df = read_csv(BACKTEST_PANEL)
    leakage_df = read_csv(LEAKAGE_AUDIT)

    upstream_rows, upstream_ok, upstream_warnings = audit_upstream(upstream_summary)
    source_rows, source_classification, source_warning, source_resolved = classify_weight_source(upstream_summary, source_df)
    window_rows, window_metrics, window_warning = audit_windows(window_df, upstream_summary)
    per_date_rows, per_date_status, per_date_warning = audit_per_date(per_date_df)
    ticker_rows, ticker_status, ticker_warning = audit_tickers(panel_df)
    rsi_rows, rsi_status = review_rsi(window_df)
    leakage_rows, leakage_status, leakage_block = audit_safety(leakage_df, upstream_summary)

    warnings = list(upstream_warnings)
    if source_warning:
        warnings.append("WEIGHT_SOURCE_SEMANTIC_WARNING")
    if window_warning:
        warnings.append("WINDOW_CONCENTRATION_WARNING")
    if per_date_warning and per_date_status != "PER_DATE_AUDIT_LIMITED":
        warnings.append("PER_DATE_CONCENTRATION_WARNING")
    if ticker_warning and ticker_status != "TICKER_CONCENTRATION_AUDIT_LIMITED":
        warnings.append("TICKER_CONCENTRATION_WARNING")

    limited = any(
        row.get("stability_status") == "PER_DATE_AUDIT_LIMITED" for row in per_date_rows
    ) or any(
        row.get("concentration_status") == "TICKER_CONCENTRATION_AUDIT_LIMITED" for row in ticker_rows
    ) or window_df.empty or (not SAMPLE_MANIFEST.exists())

    final_status, decision, shadow_observation_allowed = decide(
        upstream_ok=upstream_ok,
        source_classification=source_classification,
        source_resolved=source_resolved,
        leakage_block=leakage_block,
        limited=limited,
        warnings=warnings,
    )

    safety_rows = guardrail_rows(shadow_observation_allowed) + leakage_rows

    leakage_safe_rows = leakage_rows[0].get("detailed_safe_rows", 0)
    leakage_violation_count = leakage_rows[0].get("summary_leakage_violation_count", 0)
    summary_row = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "upstream_final_status": clean(upstream_summary.get("final_status")),
        "upstream_decision": clean(upstream_summary.get("decision")),
        "research_only": "TRUE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_observation_allowed": yes(shadow_observation_allowed),
        "shadow_adoption_allowed": "FALSE",
        "weight_source_classification": source_classification,
        "source_warning": source_warning,
        "current_weight_source": clean(upstream_summary.get("current_weight_source")),
        "aggregate_current_weight_excess": window_metrics.get("aggregate_current", ""),
        "aggregate_equal_weight_excess": window_metrics.get("aggregate_equal", ""),
        "window_balanced_current_weight_excess": window_metrics.get("balanced_current", ""),
        "window_balanced_equal_weight_excess": window_metrics.get("balanced_equal", ""),
        "no_60d_current_weight_excess": window_metrics.get("no60_current", ""),
        "no_60d_equal_weight_excess": window_metrics.get("no60_equal", ""),
        "window_concentration_result": window_metrics.get("window_warning", "WINDOW_AUDIT_LIMITED"),
        "per_date_stability_result": per_date_status,
        "ticker_concentration_result": ticker_status,
        "rsi_candidate_review": rsi_status,
        "leakage_audit_result": leakage_status,
        "leakage_safe_rows": leakage_safe_rows,
        "leakage_violation_count": leakage_violation_count,
        "warnings": "|".join(sorted(set(warnings))),
    }

    write_csv(UPSTREAM_STATUS_OUT, upstream_rows, ["audit_check", "expected_value", "observed_value", "check_passed", "severity", "notes"])
    write_csv(SOURCE_SEMANTIC_OUT, source_rows, ["source_path", "source_classification", "source_warning", "resolved_weight_rows", "family_coverage", "source_audit_available", "full_current_weight_source_evidence", "official_adoption_allowed", "adoption_block_reason"])
    write_csv(WINDOW_OUT, window_rows, ["metric_scope", "current_weight_excess", "equal_weight_excess", "current_minus_equal", "current_beats_equal", "window_concentration_warning", "notes"])
    write_csv(PER_DATE_OUT, per_date_rows, ["audit_scope", "positive_asof_ratio_top20", "current_weight_beat_ratio_vs_equal", "median_per_date_excess", "top3_positive_contribution_share", "stability_status", "notes"])
    write_csv(TICKER_OUT, ticker_rows, ["audit_scope", "current_weight_top20_rows", "unique_top20_tickers", "top5_ticker_row_share", "top5_return_contribution_share", "top_tickers", "concentration_status", "notes"])
    write_csv(RSI_OUT, rsi_rows, ["candidate_name", "candidate_present", "window_balanced_excess", "beats_current_weight", "standalone_adoption_allowed", "watchlist_only", "review_status", "notes"])
    write_csv(SAFETY_OUT, safety_rows, ["guardrail", "audit_check", "expected_value", "actual_value", "summary_leakage_violation_count", "detailed_safe_rows", "detailed_unsafe_rows", "detailed_audit_available", "audit_status", "blocks_review", "guardrail_passed", "notes"])
    write_csv(DECISION_OUT, [summary_row], list(summary_row.keys()))

    report_text = build_report(summary_row, {
        **window_metrics,
        "window_result": summary_row["window_concentration_result"],
        "per_date_result": per_date_status,
        "ticker_result": ticker_status,
        "rsi_result": rsi_status,
        "leakage_result": leakage_status,
    })
    REPORT_OUT.write_text(report_text, encoding="utf-8")
    CURRENT_REPORT_OUT.write_text(report_text, encoding="utf-8")

    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"upstream_final_status={summary_row['upstream_final_status']}")
    print(f"weight_source_classification={source_classification}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
