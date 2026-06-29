#!/usr/bin/env python
"""V21.089-R1 D Top20 bucket monitor and low-quality momentum review."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_089_r1")
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
FUND_REL = Path("outputs/v21/diagnostics/v21_086_r1/V21_086_R1_FUNDAMENTAL_PIT_PANEL.csv")
INTERACTION_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_PANEL.csv")
OVERLAY_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_TOP20_D_INTERACTION_OVERLAY.csv")
RISK_REL = Path("outputs/v21/diagnostics/v21_088_r1/V21_088_R1_D_TOP20_RISK_REVIEW.csv")
RISK_SUMMARY_REL = Path("outputs/v21/diagnostics/v21_088_r1/V21_088_R1_D_TOP20_RISK_BUCKET_SUMMARY.csv")
PULLBACK_REL = Path("outputs/v21/diagnostics/v21_088_r1/V21_088_R1_REPAIRED_PULLBACK_FORWARD_SUMMARY.csv")
V088_VALIDATION_REL = Path("outputs/v21/diagnostics/v21_088_r1/V21_088_R1_VALIDATION_SUMMARY.csv")

MONITOR_NAME = "V21_089_R1_D_TOP20_BUCKET_MONITOR.csv"
LOW_QUALITY_NAME = "V21_089_R1_LOW_QUALITY_MOMENTUM_REVIEW.csv"
DATA_GAP_NAME = "V21_089_R1_INTERACTION_DATA_GAP_REVIEW.csv"
WAIT_NAME = "V21_089_R1_WAIT_CONFIRMATION_REVIEW.csv"
DAY0_NAME = "V21_089_R1_DAY0_BREAKOUT_NO_CHASE_REVIEW.csv"
OVEREXTENDED_NAME = "V21_089_R1_OVEREXTENDED_STRONG_FUNDAMENTAL_REVIEW.csv"
WATCHLIST_NAME = "V21_089_R1_D_TOP20_NO_TRADE_DIAGNOSTIC_WATCHLIST.csv"
BUCKET_SUMMARY_NAME = "V21_089_R1_BUCKET_SUMMARY.csv"
PULLBACK_CONFIRM_NAME = "V21_089_R1_PULLBACK_NON_ADOPTION_CONFIRMATION.csv"
MUTATION_NAME = "V21_089_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_089_R1_VALIDATION_SUMMARY.csv"

OUTPUT_NAMES = (
    MONITOR_NAME, LOW_QUALITY_NAME, DATA_GAP_NAME, WAIT_NAME, DAY0_NAME,
    OVEREXTENDED_NAME, WATCHLIST_NAME, BUCKET_SUMMARY_NAME,
    PULLBACK_CONFIRM_NAME, MUTATION_NAME, VALIDATION_NAME,
)

TECH_FLAGS = [
    "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_DAY0_WATCH_ONLY",
    "TECH_BREAKOUT_CONFIRMED", "TECH_BREAKOUT_FAILURE_RISK",
    "TECH_PULLBACK_BUY_CANDIDATE", "TECH_OVEREXTENDED_BUT_STRONG",
    "TECH_WEAK_OR_NO_CONFIRMATION",
]
TECH_FIELDS = TECH_FLAGS + [
    "close_above_ma20", "close_above_ma50", "ma20_slope_5d", "ma50_slope_5d",
    "close_distance_ma20_pct", "close_distance_ma50_pct", "rsi_14",
    "rsi_14_slope_3d", "macd_hist", "macd_hist_slope_3d",
    "bb_midline_failure", "volume_ratio_20d", "pullback_reclaim_ma20",
    "pullback_reclaim_ma50", "breakout_volume_confirmed", "breakout_from_squeeze",
]
FUND_FLAGS = [
    "GROWTH_STRONG", "PROFITABILITY_IMPROVING", "QUALITY_STRONG",
    "VALUATION_REASONABLE_FOR_GROWTH", "BALANCE_SHEET_STRONG", "REVISION_POSITIVE",
    "FUNDAMENTAL_STRONG_COMPOUNDING", "FUNDAMENTAL_CYCLICAL_RECOVERY",
    "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY", "FUNDAMENTAL_VALUE_TRAP_RISK",
    "FUNDAMENTAL_WEAK_OR_UNCONFIRMED",
]
FUND_FIELDS = FUND_FLAGS + [
    "pit_certification_level", "fundamental_available_date_used", "pit_warning",
    "leakage_risk_flag",
]

BUCKET_RULES = {
    "OVEREXTENDED_STRONG_FUNDAMENTAL_MONITOR_EXTENSION_RISK":
        ("STRONG_BUT_EXTENDED", "HIGH", "MONITOR_EXTENSION_RISK"),
    "STRONG_TECH_STRONG_FUNDAMENTAL_CORE_DIAGNOSTIC":
        ("CORE_DIAGNOSTIC", "MEDIUM", "CORE_DIAGNOSTIC_MONITOR"),
    "LOW_QUALITY_MOMENTUM_RISK_REVIEW":
        ("LOW_QUALITY_MOMENTUM_REVIEW", "HIGH", "REVIEW_LOW_QUALITY_MOMENTUM"),
    "INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW":
        ("DATA_GAP_REVIEW", "HIGH", "REVIEW_INTERACTION_DATA_GAP"),
    "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION":
        ("WAIT_FOR_TECH_CONFIRMATION", "MEDIUM", "WAIT_FOR_TECH_CONFIRMATION"),
    "BREAKOUT_DAY0_WATCH_ONLY_NO_CHASE":
        ("DAY0_WATCH_ONLY", "HIGH", "DAY0_NO_CHASE"),
    "WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION":
        ("WEAK_TECH_WAIT_CONFIRMATION", "MEDIUM", "WEAK_TECH_WAIT_CONFIRMATION"),
}

MONITOR_COLUMNS = [
    "as_of_date", "source_latest_price_date", "D_rank", "ticker", "D_final_score",
    "latest_close", "interaction_primary_label", "interaction_secondary_labels",
    "risk_bucket_from_v21_088", "bucket_monitor_status", "bucket_monitor_priority",
    "technical_available", "fundamental_available", "interaction_available",
    "no_trade_action_created", "adoption_allowed",
] + TECH_FIELDS[:23] + FUND_FIELDS + [
    "technical_as_of_date", "fundamental_as_of_date",
    "extension_risk_score", "low_quality_momentum_risk_score",
    "data_unavailable_risk_score", "wait_for_confirmation_score",
    "day0_no_chase_flag", "pullback_not_adoptable_flag",
    "monitor_interpretation", "diagnostic_action",
]


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def num(value: Any) -> float:
    return pd.to_numeric(value, errors="coerce")


def blank(value: Any) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def latest_rows(path: Path, tickers: set[str], columns: list[str], latest_date: str) -> pd.DataFrame:
    use = list(dict.fromkeys(["ticker", "as_of_date"] + columns))
    frames = []
    for chunk in pd.read_csv(path, usecols=lambda c: c in use, chunksize=100000, low_memory=False):
        chunk["ticker"] = chunk["ticker"].astype(str).str.upper().str.strip()
        chunk["as_of_date"] = chunk["as_of_date"].astype(str).str[:10]
        frames.append(chunk[chunk["ticker"].isin(tickers) & chunk["as_of_date"].le(latest_date)].copy())
    if not frames:
        return pd.DataFrame(columns=use)
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["ticker", "as_of_date"]).groupby("ticker", as_index=False).tail(1)
    return panel


def extension_score(row: pd.Series) -> int:
    score = 0
    score += int(num(row.get("close_distance_ma20_pct")) >= 0.10)
    score += int(num(row.get("close_distance_ma50_pct")) >= 0.20)
    score += int(num(row.get("rsi_14")) >= 70)
    score += int(num(row.get("macd_hist_slope_3d")) < 0)
    score += int(num(row.get("volume_ratio_20d")) >= 2.0)
    score += int(truth(row.get("bb_midline_failure")))
    return score


def low_quality_score(row: pd.Series) -> int:
    return sum([
        int(truth(row.get("FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY"))),
        int(not truth(row.get("QUALITY_STRONG"))),
        int(not truth(row.get("PROFITABILITY_IMPROVING"))),
        int(not truth(row.get("BALANCE_SHEET_STRONG"))),
        int(truth(row.get("FUNDAMENTAL_WEAK_OR_UNCONFIRMED"))),
        int(truth(row.get("TECH_OVEREXTENDED_BUT_STRONG"))),
    ])


def wait_score(row: pd.Series) -> int:
    return sum([
        int(not truth(row.get("close_above_ma20"))),
        int(not truth(row.get("close_above_ma50"))),
        int(num(row.get("macd_hist")) <= 0),
        int(num(row.get("rsi_14_slope_3d")) <= 0),
        int(not truth(row.get("TECH_BREAKOUT_CONFIRMED"))),
    ])


def monitor_interpretation(row: pd.Series) -> str:
    action = row["diagnostic_action"]
    text = {
        "MONITOR_EXTENSION_RISK": "Strong trend with fundamental support; monitor extension failure risk only.",
        "CORE_DIAGNOSTIC_MONITOR": "Healthy strong-trend core diagnostic; wait for interaction maturity.",
        "REVIEW_LOW_QUALITY_MOMENTUM": "Momentum is present with a fundamental quality gap; risk review only.",
        "REVIEW_INTERACTION_DATA_GAP": "Interaction label is unavailable; diagnose source coverage or rule matching.",
        "WAIT_FOR_TECH_CONFIRMATION": "Fundamental support is present but technical confirmation is incomplete.",
        "DAY0_NO_CHASE": "Day0 breakout is watch-only and cannot be interpreted as chase permission.",
        "WEAK_TECH_WAIT_CONFIRMATION": "Strong fundamental state with weak technical confirmation; wait.",
        "OTHER_DIAGNOSTIC_MONITOR": "Diagnostic monitoring only; no adoption or trade action.",
    }
    return text[action]


def build_monitor(root: Path) -> tuple[pd.DataFrame, str]:
    risk = pd.read_csv(root / RISK_REL, low_memory=False)
    risk["ticker"] = risk["ticker"].astype(str).str.upper().str.strip()
    risk = risk.sort_values("D_rank").reset_index(drop=True)
    overlay = pd.read_csv(root / OVERLAY_REL, low_memory=False)
    overlay["ticker"] = overlay["ticker"].astype(str).str.upper().str.strip()
    interaction = pd.read_csv(root / INTERACTION_REL, low_memory=False)
    interaction["as_of_date"] = interaction["as_of_date"].astype(str).str[:10]
    latest = str(interaction["source_latest_price_date"].dropna().astype(str).str[:10].max())
    tickers = set(risk["ticker"])
    tech = latest_rows(root / TECH_REL, tickers, TECH_FIELDS, latest).rename(
        columns={"as_of_date": "technical_as_of_date"}
    )
    fund = latest_rows(root / FUND_REL, tickers, FUND_FIELDS, latest).rename(
        columns={"as_of_date": "fundamental_as_of_date"}
    )
    interaction_latest = latest_rows(
        root / INTERACTION_REL, tickers,
        ["interaction_primary_label", "interaction_secondary_labels", "technical_as_of_date",
         "fundamental_as_of_date", "technical_labels_available", "fundamental_labels_available",
         "interaction_data_quality_warning"],
        latest,
    ).rename(columns={"as_of_date": "interaction_as_of_date"})

    if set(overlay["ticker"]) != tickers:
        raise ValueError("V21.087 Top20 overlay tickers do not match V21.088 risk review")
    base = risk.copy()
    base = base.merge(tech, on="ticker", how="left").merge(fund, on="ticker", how="left")
    base = base.merge(interaction_latest, on="ticker", how="left", suffixes=("", "_interaction"))
    base["as_of_date"] = base["interaction_as_of_date"].fillna(latest)
    base["source_latest_price_date"] = latest
    base["risk_bucket_from_v21_088"] = base["risk_bucket"]
    rules = base["risk_bucket"].map(BUCKET_RULES)
    base["bucket_monitor_status"] = rules.map(lambda x: x[0] if isinstance(x, tuple) else "OTHER_DIAGNOSTIC")
    base["bucket_monitor_priority"] = rules.map(lambda x: x[1] if isinstance(x, tuple) else "LOW")
    base["diagnostic_action"] = rules.map(lambda x: x[2] if isinstance(x, tuple) else "OTHER_DIAGNOSTIC_MONITOR")
    base["technical_available"] = base["technical_as_of_date"].notna()
    base["fundamental_available"] = base["fundamental_as_of_date"].notna()
    base["interaction_available"] = ~base["interaction_primary_label"].fillna("").eq("INTERACTION_UNAVAILABLE")
    base["no_trade_action_created"] = True
    base["adoption_allowed"] = False
    base["extension_risk_score"] = base.apply(extension_score, axis=1)
    base["low_quality_momentum_risk_score"] = base.apply(low_quality_score, axis=1)
    base["data_unavailable_risk_score"] = (
        (~base["technical_available"]).astype(int)
        + (~base["fundamental_available"]).astype(int)
        + (~base["interaction_available"]).astype(int)
    )
    base["wait_for_confirmation_score"] = base.apply(wait_score, axis=1)
    base["day0_no_chase_flag"] = base["risk_bucket"].eq("BREAKOUT_DAY0_WATCH_ONLY_NO_CHASE")
    base["pullback_not_adoptable_flag"] = True
    base["monitor_interpretation"] = base.apply(monitor_interpretation, axis=1)
    for col in MONITOR_COLUMNS:
        if col not in base:
            base[col] = np.nan
    return base[MONITOR_COLUMNS].sort_values("D_rank").reset_index(drop=True), latest


def low_quality_review(monitor: pd.DataFrame) -> pd.DataFrame:
    sub = monitor[monitor["risk_bucket_from_v21_088"].eq("LOW_QUALITY_MOMENTUM_RISK_REVIEW")].copy()
    def reason(row: pd.Series) -> str:
        if truth(row.get("TECH_OVEREXTENDED_BUT_STRONG")) and not truth(row.get("QUALITY_STRONG")):
            return "OVEREXTENDED_WITH_LOW_QUALITY"
        if truth(row.get("FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY")):
            return "HIGH_GROWTH_LOW_QUALITY"
        gaps = [
            not truth(row.get("QUALITY_STRONG")),
            not truth(row.get("PROFITABILITY_IMPROVING")),
            not truth(row.get("BALANCE_SHEET_STRONG")),
        ]
        if truth(row.get("TECH_STRONG_TREND_CONTINUATION")) and any(gaps):
            return "MOMENTUM_WITH_FUNDAMENTAL_GAP"
        if gaps[0]: return "QUALITY_UNCONFIRMED"
        if gaps[1]: return "PROFITABILITY_UNCONFIRMED"
        if gaps[2]: return "BALANCE_SHEET_UNCONFIRMED"
        return "MIXED_LOW_QUALITY_SIGNAL"
    sub["risk_bucket"] = sub["risk_bucket_from_v21_088"]
    sub["low_quality_reason"] = sub.apply(reason, axis=1)
    sub["diagnostic_interpretation"] = "Low-quality momentum risk overlay; D rank remains unchanged."
    sub["suggested_diagnostic_action"] = "REVIEW_LOW_QUALITY_MOMENTUM"
    cols = [
        "ticker", "D_rank", "D_final_score", "latest_close", "interaction_primary_label",
        "risk_bucket", "GROWTH_STRONG", "QUALITY_STRONG", "PROFITABILITY_IMPROVING",
        "BALANCE_SHEET_STRONG", "VALUATION_REASONABLE_FOR_GROWTH",
        "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY", "FUNDAMENTAL_WEAK_OR_UNCONFIRMED",
        "TECH_STRONG_TREND_CONTINUATION", "TECH_OVEREXTENDED_BUT_STRONG",
        "TECH_BREAKOUT_CONFIRMED", "TECH_WEAK_OR_NO_CONFIRMATION", "rsi_14",
        "macd_hist_slope_3d", "close_distance_ma20_pct", "close_distance_ma50_pct",
        "volume_ratio_20d", "low_quality_momentum_risk_score", "low_quality_reason",
        "diagnostic_interpretation", "suggested_diagnostic_action", "adoption_allowed",
        "no_trade_action_created",
    ]
    return sub[cols]


def data_gap_review(monitor: pd.DataFrame) -> pd.DataFrame:
    sub = monitor[monitor["risk_bucket_from_v21_088"].eq("INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW")].copy()
    def diagnose(row: pd.Series) -> pd.Series:
        tech, fund = truth(row["technical_available"]), truth(row["fundamental_available"])
        if not tech:
            source = "MISSING_TECHNICAL_ROW"
        elif not fund:
            source = "MISSING_FUNDAMENTAL_ROW"
        elif str(row.get("technical_as_of_date", ""))[:10] != str(row["as_of_date"])[:10] or str(row.get("fundamental_as_of_date", ""))[:10] != str(row["as_of_date"])[:10]:
            source = "AS_OF_DATE_JOIN_MISMATCH"
        else:
            source = "SOURCE_COVERAGE_GAP"
        missing_interaction = (
            "NO_INTERACTION_RULE_MATCH_DESPITE_SOURCE_ROWS"
            if tech and fund else "INTERACTION_SOURCE_INPUT_INCOMPLETE"
        )
        suggestion = (
            "AUDIT_INTERACTION_RULE_COVERAGE_FOR_VALID_TECH_AND_FUND_COMBINATION"
            if source == "SOURCE_COVERAGE_GAP" else "REPAIR_SOURCE_COVERAGE_AND_REBUILD_SHADOW_LAYER"
        )
        return pd.Series({
            "missing_technical_reason": "" if tech else "NO_LATEST_TECHNICAL_ROW",
            "missing_fundamental_reason": "" if fund else "NO_LATEST_FUNDAMENTAL_ROW",
            "missing_interaction_reason": missing_interaction,
            "likely_data_gap_source": source,
            "data_gap_repair_suggestion": suggestion,
            "diagnostic_interpretation": "Interaction remains unavailable; diagnostic repair only, with no adoption.",
        })
    details = sub.apply(diagnose, axis=1)
    sub = pd.concat([sub.reset_index(drop=True), details.reset_index(drop=True)], axis=1)
    cols = [
        "ticker", "D_rank", "D_final_score", "latest_close", "technical_available",
        "fundamental_available", "interaction_available", "technical_as_of_date",
        "fundamental_as_of_date", "fundamental_available_date_used",
        "missing_technical_reason", "missing_fundamental_reason",
        "missing_interaction_reason", "likely_data_gap_source",
        "data_gap_repair_suggestion", "diagnostic_interpretation",
        "adoption_allowed", "no_trade_action_created",
    ]
    return sub[cols]


def confirmation_signal(row: pd.Series) -> str:
    if not truth(row.get("technical_available")):
        return "TECHNICAL_DATA_AVAILABLE"
    if not truth(row.get("close_above_ma20")):
        return "CLOSE_RECLAIM_MA20"
    if not truth(row.get("close_above_ma50")):
        return "CLOSE_RECLAIM_MA50"
    if num(row.get("macd_hist")) <= 0:
        return "MACD_HIST_TURN_POSITIVE"
    if num(row.get("rsi_14_slope_3d")) <= 0:
        return "RSI_SLOPE_RECOVERY"
    if truth(row.get("TECH_BREAKOUT_DAY0_WATCH_ONLY")) and not truth(row.get("TECH_BREAKOUT_CONFIRMED")):
        return "BREAKOUT_CONFIRMATION_DAY1"
    if num(row.get("volume_ratio_20d")) < 1:
        return "VOLUME_CONFIRMATION"
    return "OTHER_CONFIRMATION"


def wait_review(monitor: pd.DataFrame) -> pd.DataFrame:
    buckets = {
        "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION",
        "WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION",
    }
    sub = monitor[monitor["risk_bucket_from_v21_088"].isin(buckets)].copy()
    sub["risk_bucket"] = sub["risk_bucket_from_v21_088"]
    sub["fundamental_strength_flag"] = (
        sub["FUNDAMENTAL_STRONG_COMPOUNDING"].map(truth)
        | sub["QUALITY_STRONG"].map(truth)
        | sub["GROWTH_STRONG"].map(truth)
    )
    sub["technical_confirmation_flag"] = (
        sub["TECH_STRONG_TREND_CONTINUATION"].map(truth)
        | sub["TECH_BREAKOUT_CONFIRMED"].map(truth)
    )
    sub["weak_technical_reason"] = sub.apply(
        lambda r: "TECH_WEAK_OR_NO_CONFIRMATION" if truth(r.get("TECH_WEAK_OR_NO_CONFIRMATION"))
        else "TECHNICAL_CONFIRMATION_INCOMPLETE", axis=1
    )
    sub["wait_confirmation_reason"] = "D bucket requires technical confirmation; rank and baseline are unchanged."
    sub["required_confirmation_signal"] = sub.apply(confirmation_signal, axis=1)
    sub["diagnostic_interpretation"] = "Wait for observable technical confirmation; no trade action."
    cols = [
        "ticker", "D_rank", "D_final_score", "latest_close", "risk_bucket",
        "interaction_primary_label", "fundamental_strength_flag",
        "technical_confirmation_flag", "weak_technical_reason",
        "wait_confirmation_reason", "required_confirmation_signal",
        "diagnostic_interpretation", "adoption_allowed", "no_trade_action_created",
    ]
    return sub[cols]


def day0_review(monitor: pd.DataFrame) -> pd.DataFrame:
    sub = monitor[monitor["risk_bucket_from_v21_088"].eq("BREAKOUT_DAY0_WATCH_ONLY_NO_CHASE")].copy()
    sub["day0_no_chase_reason"] = "DAY0_BREAKOUT_REQUIRES_LATER_CONFIRMATION_NO_CHASE_PERMISSION"
    sub["day1_confirmation_requirements"] = "BREAKOUT_CONFIRMATION_DAY1|VOLUME_CONFIRMATION|NO_BREAKOUT_FAILURE"
    sub["diagnostic_interpretation"] = "Watch-only Day0 breakout; not a buy, chase, or adoption signal."
    cols = [
        "ticker", "D_rank", "D_final_score", "latest_close",
        "TECH_BREAKOUT_DAY0_WATCH_ONLY", "TECH_BREAKOUT_CONFIRMED",
        "breakout_volume_confirmed", "breakout_from_squeeze", "volume_ratio_20d",
        "close_distance_ma20_pct", "close_distance_ma50_pct",
        "day0_no_chase_reason", "day1_confirmation_requirements",
        "diagnostic_interpretation", "adoption_allowed", "no_trade_action_created",
    ]
    return sub[cols]


def extension_reason(row: pd.Series) -> str:
    reasons = []
    if num(row.get("close_distance_ma20_pct")) >= 0.10: reasons.append("FAR_ABOVE_MA20")
    if num(row.get("close_distance_ma50_pct")) >= 0.20: reasons.append("FAR_ABOVE_MA50")
    if num(row.get("rsi_14")) >= 70: reasons.append("RSI_OVERHEATED")
    if num(row.get("macd_hist_slope_3d")) < 0: reasons.append("MACD_DECELERATION")
    if num(row.get("volume_ratio_20d")) >= 2.0: reasons.append("VOLUME_SPIKE_EXTENSION")
    if truth(row.get("bb_midline_failure")): reasons.append("BB_MIDLINE_FAILURE_RISK")
    if not reasons: return "HEALTHY_EXTENSION"
    return reasons[0] if len(reasons) == 1 else "MIXED_EXTENSION_RISK"


def overextended_review(monitor: pd.DataFrame) -> pd.DataFrame:
    sub = monitor[monitor["risk_bucket_from_v21_088"].eq(
        "OVEREXTENDED_STRONG_FUNDAMENTAL_MONITOR_EXTENSION_RISK"
    )].copy()
    sub["extension_risk_reason"] = sub.apply(extension_reason, axis=1)
    sub["healthy_extension_flag"] = (
        sub["extension_risk_score"].le(1)
        & sub["TECH_STRONG_TREND_CONTINUATION"].map(truth)
        & ~sub["bb_midline_failure"].map(truth)
    )
    sub["extension_failure_watch_flag"] = (
        (sub["macd_hist_slope_3d"].map(num) < 0)
        | sub["bb_midline_failure"].map(truth)
        | ~sub["close_above_ma20"].map(truth)
    )
    sub["diagnostic_interpretation"] = "Strong trend/fundamental support with extension risk; monitor, do not adopt."
    sub["suggested_diagnostic_action"] = "MONITOR_EXTENSION_RISK"
    cols = [
        "ticker", "D_rank", "D_final_score", "latest_close",
        "TECH_OVEREXTENDED_BUT_STRONG", "TECH_STRONG_TREND_CONTINUATION",
        "TECH_BREAKOUT_CONFIRMED", "GROWTH_STRONG", "PROFITABILITY_IMPROVING",
        "QUALITY_STRONG", "VALUATION_REASONABLE_FOR_GROWTH",
        "FUNDAMENTAL_STRONG_COMPOUNDING", "rsi_14", "close_distance_ma20_pct",
        "close_distance_ma50_pct", "macd_hist_slope_3d", "volume_ratio_20d",
        "extension_risk_score", "extension_risk_reason", "healthy_extension_flag",
        "extension_failure_watch_flag", "diagnostic_interpretation",
        "suggested_diagnostic_action", "adoption_allowed", "no_trade_action_created",
    ]
    return sub[cols]


def watchlist(monitor: pd.DataFrame) -> pd.DataFrame:
    out = monitor[[
        "ticker", "D_rank", "risk_bucket_from_v21_088",
        "bucket_monitor_priority", "monitor_interpretation", "diagnostic_action",
    ]].copy()
    out.columns = ["ticker", "D_rank", "risk_bucket", "monitor_priority",
                   "one_line_diagnostic", "what_to_watch_next"]
    out["not_a_trade_signal"] = True
    out["adoption_allowed"] = False
    out["no_trade_action_created"] = True
    return out


def bucket_summary(monitor: pd.DataFrame) -> pd.DataFrame:
    out = monitor.groupby(["bucket_monitor_status", "diagnostic_action"], sort=True).agg(
        d_top20_count=("ticker", "count"),
        tickers=("ticker", lambda s: "|".join(s.astype(str))),
        avg_d_rank=("D_rank", "mean"),
        avg_d_final_score=("D_final_score", "mean"),
        high_priority_count=("bucket_monitor_priority", lambda s: int(s.eq("HIGH").sum())),
    ).reset_index()
    out["warning"] = np.where(
        out["bucket_monitor_status"].eq("DATA_GAP_REVIEW"),
        "INTERACTION_DATA_GAP_REQUIRES_DIAGNOSTIC_REVIEW", "",
    )
    return out


def pullback_confirmation(root: Path) -> pd.DataFrame:
    summary = pd.read_csv(root / PULLBACK_REL, low_memory=False)
    v088 = pd.read_csv(root / V088_VALIDATION_REL, low_memory=False).iloc[0]
    r20 = summary[
        summary["forward_window"].astype(str).str.upper().eq("20D")
        & summary["delta_true_minus_false"].notna()
        & ~summary["pullback_label"].eq("TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL")
    ]
    best_label = v088.get("best_repaired_pullback_label_20d", "")
    best_delta = v088.get("best_repaired_pullback_delta_20d", "")
    if (blank(best_label) or blank(best_delta)) and not r20.empty:
        best = r20.sort_values("delta_true_minus_false", ascending=False).iloc[0]
        best_label, best_delta = best["pullback_label"], best["delta_true_minus_false"]
    return pd.DataFrame([{
        "source_stage": "V21.088-R1",
        "original_pullback_delta_20d": v088.get("original_pullback_delta_20d", ""),
        "best_repaired_pullback_label_20d": best_label,
        "best_repaired_pullback_delta_20d": best_delta,
        "pullback_repair_status": v088.get("pullback_repair_status", "PULLBACK_REPAIR_DIAGNOSTIC_READY"),
        "adoption_allowed": False,
        "reason": "Repaired pullback remained negative or was not proven adoption-ready.",
        "recommended_handling": "KEEP_DIAGNOSTIC_ONLY_DO_NOT_PROMOTE",
    }])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for rel in (
        "outputs/v21/diagnostics/v21_085_r1",
        "outputs/v21/diagnostics/v21_086_r1",
        "outputs/v21/diagnostics/v21_087_r1",
        "outputs/v21/diagnostics/v21_088_r1",
    ):
        base = root / rel
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    paths = sorted(set(paths))
    return paths, {p: sha256(p) for p in paths}


def mutation_audit(paths: list[Path], before: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        text = path.as_posix().lower()
        if "broker" in text:
            ptype = "broker_action"
        elif "weight" in text and ("official" in text or "weight_perturbation" in text):
            ptype = "official_weight"
        elif "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text:
            ptype = "official_ranking"
        elif "v21_085_r1" in text: ptype = "v21_085_protected"
        elif "v21_086_r1" in text: ptype = "v21_086_protected"
        elif "v21_087_r1" in text: ptype = "v21_087_protected"
        elif "v21_088_r1" in text: ptype = "v21_088_protected"
        else: ptype = "protected"
        exists_after = path.exists()
        changed = (not exists_after) or before[path] != sha256(path)
        rows.append({
            "path": path.as_posix(), "path_type": ptype, "exists_before": True,
            "exists_after": exists_after, "modified_during_run": changed,
            "mutation_allowed": False,
            "warning": "DISALLOWED_MUTATION_DETECTED" if changed else "",
        })
    return pd.DataFrame(rows, columns=[
        "path", "path_type", "exists_before", "exists_after", "modified_during_run",
        "mutation_allowed", "warning",
    ])


def empty_outputs(output: Path) -> None:
    headers = {
        MONITOR_NAME: MONITOR_COLUMNS,
        LOW_QUALITY_NAME: ["ticker", "D_rank", "adoption_allowed", "no_trade_action_created"],
        DATA_GAP_NAME: ["ticker", "D_rank", "adoption_allowed", "no_trade_action_created"],
        WAIT_NAME: ["ticker", "D_rank", "adoption_allowed", "no_trade_action_created"],
        DAY0_NAME: ["ticker", "D_rank", "adoption_allowed", "no_trade_action_created"],
        OVEREXTENDED_NAME: ["ticker", "D_rank", "adoption_allowed", "no_trade_action_created"],
        WATCHLIST_NAME: ["ticker", "D_rank", "not_a_trade_signal", "adoption_allowed", "no_trade_action_created"],
        BUCKET_SUMMARY_NAME: ["bucket_monitor_status", "diagnostic_action", "d_top20_count",
                              "tickers", "avg_d_rank", "avg_d_final_score",
                              "high_priority_count", "warning"],
        PULLBACK_CONFIRM_NAME: ["source_stage", "original_pullback_delta_20d",
                                "best_repaired_pullback_label_20d",
                                "best_repaired_pullback_delta_20d",
                                "pullback_repair_status", "adoption_allowed",
                                "reason", "recommended_handling"],
    }
    for name, columns in headers.items():
        pd.DataFrame(columns=columns).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute()
              else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    required = [
        TECH_REL, FUND_REL, INTERACTION_REL, OVERLAY_REL, RISK_REL,
        RISK_SUMMARY_REL, PULLBACK_REL, V088_VALIDATION_REL,
    ]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)

    monitor = low = gaps = waits = day0 = extended = no_trade = buckets = pd.DataFrame()
    latest = ""
    if missing:
        empty_outputs(output)
    else:
        monitor, latest = build_monitor(root)
        low = low_quality_review(monitor)
        gaps = data_gap_review(monitor)
        waits = wait_review(monitor)
        day0 = day0_review(monitor)
        extended = overextended_review(monitor)
        no_trade = watchlist(monitor)
        buckets = bucket_summary(monitor)
        pullback = pullback_confirmation(root)
        for frame, name in (
            (monitor, MONITOR_NAME), (low, LOW_QUALITY_NAME), (gaps, DATA_GAP_NAME),
            (waits, WAIT_NAME), (day0, DAY0_NAME), (extended, OVEREXTENDED_NAME),
            (no_trade, WATCHLIST_NAME), (buckets, BUCKET_SUMMARY_NAME),
            (pullback, PULLBACK_CONFIRM_NAME),
        ):
            frame.to_csv(output / name, index=False)

    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    leakage_count = (
        int(monitor["leakage_risk_flag"].map(truth).sum()) if not monitor.empty else 0
    )
    data_warning_count = (
        int((~monitor["technical_available"].map(truth)).sum()
            + (~monitor["fundamental_available"].map(truth)).sum()
            + (~monitor["interaction_available"].map(truth)).sum())
        if not monitor.empty else 0
    )
    any_adoption = any(
        frame.get("adoption_allowed", pd.Series(dtype=bool)).map(truth).any()
        for frame in (monitor, low, gaps, waits, day0, extended, no_trade)
    )
    trade_created = any(
        (~frame.get("no_trade_action_created", pd.Series(dtype=bool)).map(truth)).any()
        for frame in (monitor, low, gaps, waits, day0, extended, no_trade)
        if not frame.empty
    )
    blocked_risk = leakage_count > 0 or mutation_count > 0 or any_adoption or trade_created
    if missing:
        status = "BLOCKED_V21_089_R1_REQUIRED_INPUTS_MISSING"
        decision = "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif blocked_risk:
        status = "BLOCKED_V21_089_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        decision = "D_TOP20_BUCKET_MONITOR_BLOCKED_REVIEW_REQUIRED"
    elif len(monitor) == 20 and data_warning_count == 0:
        status = "PASS_V21_089_R1_D_TOP20_BUCKET_MONITOR_READY"
        decision = "D_TOP20_BUCKET_MONITOR_READY_DIAGNOSTIC_ONLY"
    else:
        status = "PARTIAL_PASS_V21_089_R1_D_TOP20_BUCKET_MONITOR_READY_WITH_DATA_WARN"
        decision = "D_TOP20_BUCKET_MONITOR_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"

    def count_bucket(bucket: str) -> int:
        return int(monitor["risk_bucket_from_v21_088"].eq(bucket).sum()) if not monitor.empty else 0

    validation = {
        "stage": "V21.089-R1_D_TOP20_BUCKET_MONITOR_AND_LOW_QUALITY_MOMENTUM_REVIEW",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "source_latest_price_date": latest, "top20_monitor_rows": len(monitor),
        "low_quality_momentum_review_rows": len(low), "interaction_data_gap_review_rows": len(gaps),
        "wait_confirmation_review_rows": len(waits), "day0_breakout_review_rows": len(day0),
        "overextended_review_rows": len(extended), "no_trade_watchlist_rows": len(no_trade),
        "pullback_adoption_allowed": False, "interaction_adoption_allowed": False,
        "low_quality_momentum_count": count_bucket("LOW_QUALITY_MOMENTUM_RISK_REVIEW"),
        "interaction_unavailable_count": count_bucket("INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW"),
        "wait_for_confirmation_count": count_bucket("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION")
            + count_bucket("WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION"),
        "day0_no_chase_count": count_bucket("BREAKOUT_DAY0_WATCH_ONLY_NO_CHASE"),
        "overextended_strong_fundamental_count":
            count_bucket("OVEREXTENDED_STRONG_FUNDAMENTAL_MONITOR_EXTENSION_RISK"),
        "core_diagnostic_count": count_bucket("STRONG_TECH_STRONG_FUNDAMENTAL_CORE_DIAGNOSTIC"),
        "leakage_warning_count": leakage_count, "data_warning_count": data_warning_count,
        "mutation_warning_count": mutation_count,
        "recommended_next_stage": "V21.090-R1_D_TOP20_MONITOR_SNAPSHOT_ARCHIVE_AND_MATURITY_SCHEDULER",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "missing_inputs": "|".join(missing),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in (
        "final_status", "decision", "source_latest_price_date",
        "top20_monitor_rows", "no_trade_watchlist_rows",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
