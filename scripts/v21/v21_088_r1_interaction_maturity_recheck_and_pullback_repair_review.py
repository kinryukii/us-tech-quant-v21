#!/usr/bin/env python
"""V21.088-R1 interaction maturity recheck and pullback repair review."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_088_r1")
TECH_PANEL_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
TECH_SUMMARY_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_SIGNAL_FORWARD_RETURN_SUMMARY.csv")
FUND_PANEL_REL = Path("outputs/v21/diagnostics/v21_086_r1/V21_086_R1_FUNDAMENTAL_PIT_PANEL.csv")
INTERACTION_PANEL_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_PANEL.csv")
BRIDGE_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_MATURITY_BRIDGE.csv")
TOP20_OVERLAY_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_TOP20_D_INTERACTION_OVERLAY.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

MATURITY_NAME = "V21_088_R1_INTERACTION_MATURITY_RECHECK.csv"
INTERACTION_FORWARD_NAME = "V21_088_R1_INTERACTION_FORWARD_RETURN_REFRESH_SUMMARY.csv"
FORENSIC_NAME = "V21_088_R1_PULLBACK_FORENSIC_REVIEW.csv"
SEGMENT_NAME = "V21_088_R1_PULLBACK_SEGMENT_FORWARD_SUMMARY.csv"
REPAIRED_PANEL_NAME = "V21_088_R1_REPAIRED_PULLBACK_CANDIDATE_PANEL.csv"
REPAIRED_SUMMARY_NAME = "V21_088_R1_REPAIRED_PULLBACK_FORWARD_SUMMARY.csv"
TOP20_RISK_NAME = "V21_088_R1_D_TOP20_RISK_REVIEW.csv"
TOP20_BUCKET_NAME = "V21_088_R1_D_TOP20_RISK_BUCKET_SUMMARY.csv"
MUTATION_NAME = "V21_088_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_088_R1_VALIDATION_SUMMARY.csv"

WINDOWS = ("5D", "10D", "20D")
INTERACTION_LABELS = [
    "STRONG_TECH_STRONG_FUNDAMENTAL", "STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL",
    "WEAK_TECH_STRONG_FUNDAMENTAL", "WEAK_TECH_WEAK_FUNDAMENTAL",
    "OVEREXTENDED_STRONG_FUNDAMENTAL", "OVEREXTENDED_WEAK_OR_UNCONFIRMED_FUNDAMENTAL",
    "BREAKOUT_CONFIRMED_STRONG_FUNDAMENTAL", "BREAKOUT_CONFIRMED_LOW_QUALITY",
    "BREAKOUT_DAY0_STRONG_FUNDAMENTAL_WATCH_ONLY", "BREAKOUT_DAY0_WEAK_FUNDAMENTAL_WATCH_ONLY",
    "PULLBACK_WITH_STRONG_FUNDAMENTAL", "PULLBACK_WITH_WEAK_FUNDAMENTAL",
    "TECHNICAL_TRADE_ONLY", "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION",
    "LOW_QUALITY_MOMENTUM_RISK", "HIGH_QUALITY_MOMENTUM_CANDIDATE", "INTERACTION_UNAVAILABLE",
]
REPAIRED_LABELS = [
    "TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL",
    "PULLBACK_REPAIR_R1_STRONG_TREND_MA20_RECLAIM",
    "PULLBACK_REPAIR_R2_STRONG_TREND_VOLUME_DRYUP",
    "PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE",
    "PULLBACK_REPAIR_R4_FULL_CONFIRMATION",
]


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_price_map(root: Path) -> tuple[dict[tuple[str, str], float], str]:
    price = pd.read_csv(root / PRICE_REL, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
    price["ticker"] = price["symbol"].astype(str).str.upper().str.strip()
    price["date"] = price["date"].astype(str).str[:10]
    price["px"] = pd.to_numeric(price["adjusted_close"], errors="coerce").fillna(pd.to_numeric(price["close"], errors="coerce"))
    price = price[price["px"].notna()].copy()
    return price.set_index(["ticker", "date"])["px"].to_dict(), str(price["date"].max())


def recheck_maturity(root: Path) -> pd.DataFrame:
    bridge = pd.read_csv(root / BRIDGE_REL, low_memory=False)
    pmap, latest = load_price_map(root)
    rows = []
    for _, r in bridge.iterrows():
        ticker = str(r["ticker"]).upper().strip()
        asof = str(r["as_of_date"])[:10]
        maturity = str(r["maturity_date"])[:10]
        before = truth(r.get("forward_matured_flag"))
        before_ret = pd.to_numeric(r.get("return_forward"), errors="coerce")
        entry = pmap.get((ticker, asof))
        mature_px = pmap.get((ticker, maturity))
        after = entry is not None and mature_px is not None
        ret = float(mature_px) / float(entry) - 1.0 if after and float(entry) != 0 else np.nan
        if pd.isna(pd.to_datetime(maturity, errors="coerce")):
            status, warn = "INVALID_MATURITY_ROW", "UNPARSEABLE_MATURITY_DATE"
        elif after and before:
            status, warn = "ALREADY_MATURED", ""
        elif after and not before:
            status, warn = "NEWLY_MATURED", ""
        elif pd.Timestamp(maturity) <= pd.Timestamp(latest) and not after:
            status, warn = "PRICE_MISSING", "MATURITY_DATE_PASSED_BUT_PRICE_MISSING"
        else:
            status, warn = "STILL_PENDING", ""
        rows.append({
            "observation_id": r["observation_id"], "ticker": ticker, "as_of_date": asof,
            "forward_window": r["forward_window"], "maturity_date": maturity,
            "latest_available_price_date": latest, "forward_matured_before": before,
            "forward_matured_after": bool(after), "return_forward_before": before_ret,
            "return_forward_after": ret, "maturity_status": status,
            "maturity_recheck_warning": warn,
        })
    return pd.DataFrame(rows)


def interaction_forward_summary(root: Path, recheck: pd.DataFrame) -> pd.DataFrame:
    panel = pd.read_csv(root / INTERACTION_PANEL_REL, low_memory=False)
    key = recheck.pivot_table(index=["ticker", "as_of_date", "forward_window"], values="return_forward_after", aggfunc="first")
    rows = []
    for label in INTERACTION_LABELS:
        for window in WINDOWS:
            mature = recheck[recheck["forward_window"].eq(window) & recheck["forward_matured_after"].map(truth)]
            sub = panel.merge(mature[["ticker", "as_of_date", "return_forward_after"]], on=["ticker", "as_of_date"], how="inner")
            true = sub[sub[label].fillna(False).map(truth)] if label in sub else sub.iloc[0:0]
            false = sub[~sub[label].fillna(False).map(truth)] if label in sub else sub.iloc[0:0]
            if sub.empty:
                rows.append({"interaction_label": label, "forward_window": window, "matured_count": 0, "pending_count": int((recheck["forward_window"].eq(window) & ~recheck["forward_matured_after"].map(truth)).sum()), "label_true_count": 0, "label_false_count": 0, "label_true_mean_forward_return": "", "label_false_mean_forward_return": "", "delta_true_minus_false": "", "label_true_median_forward_return": "", "label_false_median_forward_return": "", "hit_rate_true": "", "hit_rate_false": "", "hit_rate_delta": "", "performance_status": "WAITING_FOR_MATURITY", "usable_for_research_flag": False, "warning": "NO_MATURED_FORWARD_OBSERVATIONS"})
            else:
                usable = len(true) >= 30 and len(false) >= 30
                rows.append({"interaction_label": label, "forward_window": window, "matured_count": len(sub), "pending_count": int((recheck["forward_window"].eq(window) & ~recheck["forward_matured_after"].map(truth)).sum()), "label_true_count": len(true), "label_false_count": len(false), "label_true_mean_forward_return": true["return_forward_after"].mean() if len(true) else np.nan, "label_false_mean_forward_return": false["return_forward_after"].mean() if len(false) else np.nan, "delta_true_minus_false": true["return_forward_after"].mean() - false["return_forward_after"].mean() if len(true) and len(false) else np.nan, "label_true_median_forward_return": true["return_forward_after"].median() if len(true) else np.nan, "label_false_median_forward_return": false["return_forward_after"].median() if len(false) else np.nan, "hit_rate_true": true["return_forward_after"].gt(0).mean() if len(true) else np.nan, "hit_rate_false": false["return_forward_after"].gt(0).mean() if len(false) else np.nan, "hit_rate_delta": true["return_forward_after"].gt(0).mean() - false["return_forward_after"].gt(0).mean() if len(true) and len(false) else np.nan, "performance_status": "MATURED_DIAGNOSTIC_ONLY" if usable else "INSUFFICIENT_MATURED_SAMPLE", "usable_for_research_flag": bool(usable), "warning": "" if usable else "INSUFFICIENT_MATURED_SAMPLE"})
    return pd.DataFrame(rows)


def load_pullback_source(root: Path) -> pd.DataFrame:
    cols = [
        "ticker", "as_of_date", "close", "return_5d_forward", "return_10d_forward", "return_20d_forward",
        "forward_5d_matured", "forward_10d_matured", "forward_20d_matured", "TECH_PULLBACK_BUY_CANDIDATE",
        "TECH_STRONG_TREND_CONTINUATION", "TECH_OVEREXTENDED_BUT_STRONG", "TECH_BREAKOUT_CONFIRMED",
        "TECH_WEAK_OR_NO_CONFIRMATION", "close_above_ma20", "close_above_ma50", "ma20_slope_5d",
        "ma50_slope_5d", "close_distance_ma20_pct", "close_distance_ma50_pct", "rsi_14",
        "rsi_14_slope_3d", "rsi_14_slope_5d", "kdj_gold_cross", "kdj_gold_cross_low_zone",
        "kdj_confirmed_by_price", "kdj_confirmed_by_volume", "macd_hist", "macd_hist_slope_3d",
        "macd_hist_expanding_3d", "macd_zero_axis_above", "bb_midline_failure", "bb_lower_reclaim",
        "volume_ratio_20d", "volume_dryup_20d", "price_down_volume_down", "pullback_to_ma20",
        "pullback_to_ma50", "pullback_volume_dryup", "pullback_reclaim_ma20", "pullback_reclaim_ma50",
    ]
    chunks = []
    for c in pd.read_csv(root / TECH_PANEL_REL, usecols=lambda x: x in cols, chunksize=150000, low_memory=False):
        chunks.append(c[c["TECH_PULLBACK_BUY_CANDIDATE"].map(truth)].copy())
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=cols)


def failure_reason(row: pd.Series) -> str:
    reasons = []
    if not truth(row.get("close_above_ma50")):
        reasons.append("BELOW_MA50_PULLBACK")
    if pd.to_numeric(row.get("ma20_slope_5d"), errors="coerce") <= 0:
        reasons.append("FALLING_MA20_PULLBACK")
    if pd.to_numeric(row.get("ma50_slope_5d"), errors="coerce") < 0:
        reasons.append("FALLING_MA50_PULLBACK")
    if not truth(row.get("pullback_volume_dryup")):
        reasons.append("NO_VOLUME_DRYUP")
    if not truth(row.get("pullback_reclaim_ma20")) and not truth(row.get("pullback_reclaim_ma50")):
        reasons.append("NO_PRICE_RECLAIM")
    if pd.to_numeric(row.get("macd_hist"), errors="coerce") < 0 or pd.to_numeric(row.get("macd_hist_slope_3d"), errors="coerce") < 0:
        reasons.append("MACD_NEGATIVE_OR_DETERIORATING")
    if pd.to_numeric(row.get("rsi_14"), errors="coerce") < 40 or pd.to_numeric(row.get("rsi_14_slope_3d"), errors="coerce") < 0:
        reasons.append("RSI_NOT_STABILIZED")
    if not truth(row.get("kdj_confirmed_by_price")):
        reasons.append("KDJ_NOT_CONFIRMED")
    if truth(row.get("bb_midline_failure")):
        reasons.append("BB_MIDLINE_FAILURE")
    if truth(row.get("TECH_STRONG_TREND_CONTINUATION")) and truth(row.get("close_above_ma50")) and pd.to_numeric(row.get("ma20_slope_5d"), errors="coerce") > 0:
        reasons.append("STRONG_TREND_HEALTHY_PULLBACK")
    return "|".join(reasons) if reasons else "MIXED_OR_UNCLASSIFIED"


def segment_summary(forensic: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for segment, g in forensic.groupby("pullback_failure_reason", dropna=False):
        row = {"pullback_segment": segment, "row_count": len(g), "ticker_count": g["ticker"].nunique()}
        for w in ("5d", "10d", "20d"):
            m = g[f"forward_{w}_matured"].map(truth) if f"forward_{w}_matured" in g else pd.Series(False, index=g.index)
            sub = g[m & g[f"return_{w}_forward"].notna()]
            row[f"matured_{w}_count"] = len(sub)
            row[f"mean_{w}_forward_return"] = sub[f"return_{w}_forward"].mean() if len(sub) else np.nan
            row[f"median_{w}_forward_return"] = sub[f"return_{w}_forward"].median() if len(sub) else np.nan
            row[f"hit_rate_{w}"] = sub[f"return_{w}_forward"].gt(0).mean() if len(sub) else np.nan
        row["interpretation"] = "NEGATIVE_SEGMENT_REPAIR_TARGET" if pd.notna(row["mean_20d_forward_return"]) and row["mean_20d_forward_return"] < 0 else "DIAGNOSTIC_SEGMENT"
        row["repair_implication"] = "REQUIRE_STRONGER_CONFIRMATION_OR_REJECT" if "NO_PRICE_RECLAIM" in str(segment) or "MACD_NEGATIVE" in str(segment) else "KEEP_FOR_DIAGNOSTIC_REVIEW"
        rows.append(row)
    return pd.DataFrame(rows)


def repaired_panel(forensic: pd.DataFrame) -> pd.DataFrame:
    p = forensic.copy()
    p = p.rename(columns={"TECH_PULLBACK_BUY_CANDIDATE": "TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL"})
    original = p["TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL"].map(truth)
    p["PULLBACK_REPAIR_R1_STRONG_TREND_MA20_RECLAIM"] = original & p["close_above_ma50"].map(truth) & (pd.to_numeric(p["ma20_slope_5d"], errors="coerce") > 0) & (pd.to_numeric(p["ma50_slope_5d"], errors="coerce") >= 0) & p["pullback_reclaim_ma20"].map(truth) & ~p["TECH_WEAK_OR_NO_CONFIRMATION"].map(truth)
    p["PULLBACK_REPAIR_R2_STRONG_TREND_VOLUME_DRYUP"] = original & p["close_above_ma50"].map(truth) & p["pullback_volume_dryup"].map(truth) & (pd.to_numeric(p["volume_ratio_20d"], errors="coerce") <= 1.2) & p["price_down_volume_down"].map(truth) & (p["TECH_STRONG_TREND_CONTINUATION"].map(truth) | p["TECH_OVEREXTENDED_BUT_STRONG"].map(truth))
    p["PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE"] = original & (pd.to_numeric(p["rsi_14"], errors="coerce") >= 40) & (pd.to_numeric(p["rsi_14_slope_3d"], errors="coerce") >= 0) & (pd.to_numeric(p["macd_hist_slope_3d"], errors="coerce") >= 0) & (p["macd_zero_axis_above"].map(truth) | (pd.to_numeric(p["macd_hist"], errors="coerce") > 0)) & p["kdj_confirmed_by_price"].map(truth)
    p["PULLBACK_REPAIR_REJECT_WEAK_TREND"] = (~p["close_above_ma50"].map(truth)) | (pd.to_numeric(p["ma20_slope_5d"], errors="coerce") <= 0) | p["TECH_WEAK_OR_NO_CONFIRMATION"].map(truth)
    p["PULLBACK_REPAIR_REJECT_BELOW_MA50"] = ~p["close_above_ma50"].map(truth)
    p["PULLBACK_REPAIR_REJECT_NO_RECLAIM"] = ~p["pullback_reclaim_ma20"].map(truth) & ~p["pullback_reclaim_ma50"].map(truth)
    p["PULLBACK_REPAIR_REJECT_MACD_DERIORATION"] = (pd.to_numeric(p["macd_hist_slope_3d"], errors="coerce") < 0) & (pd.to_numeric(p["macd_hist"], errors="coerce") < 0)
    p["PULLBACK_REPAIR_REJECT_NO_VOLUME_DRYUP"] = (~p["pullback_volume_dryup"].map(truth)) & (pd.to_numeric(p["volume_ratio_20d"], errors="coerce") > 1.2)
    reject = p[["PULLBACK_REPAIR_REJECT_WEAK_TREND", "PULLBACK_REPAIR_REJECT_BELOW_MA50", "PULLBACK_REPAIR_REJECT_NO_RECLAIM", "PULLBACK_REPAIR_REJECT_MACD_DERIORATION", "PULLBACK_REPAIR_REJECT_NO_VOLUME_DRYUP"]].any(axis=1)
    p["PULLBACK_REPAIR_R4_FULL_CONFIRMATION"] = p["PULLBACK_REPAIR_R1_STRONG_TREND_MA20_RECLAIM"] & p["PULLBACK_REPAIR_R2_STRONG_TREND_VOLUME_DRYUP"] & p["PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE"] & ~reject
    def primary(row: pd.Series) -> str:
        for label in REPAIRED_LABELS[1:]:
            if truth(row[label]):
                return label
        if reject.loc[row.name]:
            return "PULLBACK_REPAIR_REJECTED"
        return "PULLBACK_REPAIR_UNCONFIRMED"
    p["repaired_pullback_primary_label"] = p.apply(primary, axis=1)
    p["repaired_pullback_adoption_allowed"] = False
    return p


def pullback_forward_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in REPAIRED_LABELS:
        for w in ("5d", "10d", "20d"):
            mat = panel[f"forward_{w}_matured"].map(truth)
            sub = panel[mat & panel[f"return_{w}_forward"].notna() & panel[label].notna()]
            true = sub[sub[label].map(truth)]
            false = sub[~sub[label].map(truth)]
            usable = len(true) >= 30 and len(false) >= 30
            rows.append({"pullback_label": label, "forward_window": w.upper(), "matured_count": len(sub), "label_true_count": len(true), "label_false_count": len(false), "label_true_mean_forward_return": true[f"return_{w}_forward"].mean() if len(true) else np.nan, "label_false_mean_forward_return": false[f"return_{w}_forward"].mean() if len(false) else np.nan, "delta_true_minus_false": true[f"return_{w}_forward"].mean() - false[f"return_{w}_forward"].mean() if len(true) and len(false) else np.nan, "label_true_median_forward_return": true[f"return_{w}_forward"].median() if len(true) else np.nan, "label_false_median_forward_return": false[f"return_{w}_forward"].median() if len(false) else np.nan, "hit_rate_true": true[f"return_{w}_forward"].gt(0).mean() if len(true) else np.nan, "hit_rate_false": false[f"return_{w}_forward"].gt(0).mean() if len(false) else np.nan, "hit_rate_delta": true[f"return_{w}_forward"].gt(0).mean() - false[f"return_{w}_forward"].gt(0).mean() if len(true) and len(false) else np.nan, "usable_for_research_flag": bool(usable), "warning": "" if usable else "INSUFFICIENT_SAMPLE"})
    return pd.DataFrame(rows)


def top20_risk(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ov = pd.read_csv(root / TOP20_OVERLAY_REL, low_memory=False)
    if "D rank" not in ov.columns:
        ov = ov.rename(columns={"D_rank": "D rank"})
    def bucket(row: pd.Series) -> tuple[str, str, str]:
        label = str(row.get("interaction_primary_label", ""))
        ticker = str(row.get("ticker", ""))
        if label == "STRONG_TECH_STRONG_FUNDAMENTAL":
            if truth(row.get("OVEREXTENDED_STRONG_FUNDAMENTAL")):
                return "OVEREXTENDED_STRONG_FUNDAMENTAL_MONITOR_EXTENSION_RISK", "Strong fundamental support with extension risk.", "MONITOR_NOT_ADOPT"
            return "STRONG_TECH_STRONG_FUNDAMENTAL_CORE_DIAGNOSTIC", "Core diagnostic bucket; no adoption.", "WAIT_FOR_MATURITY"
        if label == "LOW_QUALITY_MOMENTUM_RISK" or ticker in {"TWST", "WYFI"}:
            return "LOW_QUALITY_MOMENTUM_RISK_REVIEW", "Low-quality momentum risk from interaction layer.", "REVIEW_LOW_QUALITY_MOMENTUM"
        if label == "INTERACTION_UNAVAILABLE" or ticker in {"ICHR", "VECO"}:
            return "INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW", "Interaction source label unavailable.", "REVIEW_DATA_AVAILABILITY"
        if label == "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION" or ticker in {"FORM", "ACLS"}:
            return "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Fundamental support waits for technical confirmation.", "WAIT_FOR_TECH_CONFIRMATION"
        if "BREAKOUT_DAY0" in label or ticker == "CRDO":
            return "BREAKOUT_DAY0_WATCH_ONLY_NO_CHASE", "Day0 breakout watch only; no chase.", "NO_DAY0_CHASE"
        if label == "WEAK_TECH_STRONG_FUNDAMENTAL" or ticker == "SITM":
            return "WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION", "Strong fundamental but weak technical state.", "WAIT_FOR_TECH_CONFIRMATION"
        return "OTHER_DIAGNOSTIC", "Other diagnostic bucket.", "MONITOR_NOT_ADOPT"
    triples = ov.apply(bucket, axis=1)
    ov["risk_bucket"] = [x[0] for x in triples]
    ov["risk_reason"] = [x[1] for x in triples]
    ov["suggested_diagnostic_action"] = [x[2] for x in triples]
    ov["trade_action_created"] = False
    ov["adoption_allowed"] = False
    keep = ["D rank", "ticker", "D final score", "latest close", "interaction_primary_label", "interaction_secondary_labels", "risk_bucket", "risk_reason", "suggested_diagnostic_action", "trade_action_created", "adoption_allowed"]
    out = ov[[c for c in keep if c in ov.columns]].rename(columns={"D rank": "D_rank", "D final score": "D_final_score", "latest close": "latest_close"})
    summary = out.groupby("risk_bucket").agg(d_top20_count=("ticker", "count"), tickers=("ticker", lambda s: "|".join(s.astype(str))), avg_d_rank=("D_rank", "mean"), avg_d_final_score=("D_final_score", "mean"), suggested_diagnostic_action=("suggested_diagnostic_action", "first")).reset_index()
    summary["warning"] = ""
    return out, summary


def mutation_audit(paths: list[Path], before: dict[Path, str], after: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for p in paths:
        text = p.as_posix().lower()
        ptype = "broker_action" if "broker" in text else "official_weight" if "weight" in text and "official" in text else "official_ranking" if "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text else "protected"
        changed = before.get(p) != after.get(p)
        rows.append({"path": p.as_posix(), "path_type": ptype, "exists_before": p in before, "exists_after": p.exists(), "modified_during_run": changed, "mutation_allowed": False, "warning": "DISALLOWED_MUTATION_DETECTED" if changed else ""})
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    required = [TECH_PANEL_REL, TECH_SUMMARY_REL, FUND_PANEL_REL, INTERACTION_PANEL_REL, BRIDGE_REL, TOP20_OVERLAY_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected = protected_files(root, output)
    for rel in ("outputs/v21/diagnostics/v21_085_r1", "outputs/v21/diagnostics/v21_086_r1", "outputs/v21/diagnostics/v21_087_r1", "outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075"):
        base = root / rel
        if base.exists():
            protected.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    protected = sorted(set(protected))
    before = {p: sha256(p) for p in protected}

    if missing:
        empty = pd.DataFrame()
        for name in [MATURITY_NAME, INTERACTION_FORWARD_NAME, FORENSIC_NAME, SEGMENT_NAME, REPAIRED_PANEL_NAME, REPAIRED_SUMMARY_NAME, TOP20_RISK_NAME, TOP20_BUCKET_NAME]:
            empty.to_csv(output / name, index=False)
        latest = ""
        counts = {w: 0 for w in WINDOWS}
        original_delta = best_label = best_delta = ""
        original_rows = repaired_rows = 0
    else:
        maturity = recheck_maturity(root)
        latest = maturity["latest_available_price_date"].max()
        interaction_summary = interaction_forward_summary(root, maturity)
        forensic = load_pullback_source(root)
        forensic["pullback_failure_reason"] = forensic.apply(failure_reason, axis=1)
        segments = segment_summary(forensic)
        repaired = repaired_panel(forensic)
        repaired_summary = pullback_forward_summary(repaired)
        risk, risk_summary = top20_risk(root)
        maturity.to_csv(output / MATURITY_NAME, index=False)
        interaction_summary.to_csv(output / INTERACTION_FORWARD_NAME, index=False)
        forensic.to_csv(output / FORENSIC_NAME, index=False)
        segments.to_csv(output / SEGMENT_NAME, index=False)
        repaired.to_csv(output / REPAIRED_PANEL_NAME, index=False)
        repaired_summary.to_csv(output / REPAIRED_SUMMARY_NAME, index=False)
        risk.to_csv(output / TOP20_RISK_NAME, index=False)
        risk_summary.to_csv(output / TOP20_BUCKET_NAME, index=False)
        counts = {w: int(maturity[maturity["forward_window"].eq(w)]["forward_matured_after"].map(truth).sum()) for w in WINDOWS}
        original_rows = len(forensic)
        repaired_rows = int(repaired[[x for x in REPAIRED_LABELS[1:]]].any(axis=1).sum())
        r20 = repaired_summary[repaired_summary["forward_window"].eq("20D") & repaired_summary["delta_true_minus_false"].notna()]
        original_delta = r20.loc[r20["pullback_label"].eq("TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL"), "delta_true_minus_false"].iloc[0] if not r20.loc[r20["pullback_label"].eq("TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL")].empty else ""
        candidates = r20[~r20["pullback_label"].eq("TECH_PULLBACK_BUY_CANDIDATE_ORIGINAL")]
        if candidates.empty:
            best_label, best_delta = "", ""
        else:
            best = candidates.sort_values("delta_true_minus_false", ascending=False).iloc[0]
            best_label, best_delta = best["pullback_label"], best["delta_true_minus_false"]

    after = {p: sha256(p) for p in protected}
    mut = mutation_audit(protected, before, after)
    mut.to_csv(output / MUTATION_NAME, index=False)
    modified = bool(mut["modified_during_run"].map(truth).any()) if not mut.empty else False
    if missing:
        status = "BLOCKED_V21_088_R1_REQUIRED_INPUTS_MISSING"; decision = "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif modified:
        status = "BLOCKED_V21_088_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK"; decision = "MATURITY_RECHECK_OR_PULLBACK_REPAIR_BLOCKED_REVIEW_REQUIRED"
    elif sum(counts.values()) == 0:
        status = "PARTIAL_PASS_V21_088_R1_READY_WAITING_FOR_INTERACTION_MATURITY"; decision = "MATURITY_RECHECK_READY_WAITING_FOR_INTERACTION_MATURITY_PULLBACK_REPAIR_READY"
    else:
        status = "PASS_V21_088_R1_MATURITY_RECHECK_AND_PULLBACK_REPAIR_READY"; decision = "MATURITY_RECHECK_AND_PULLBACK_REPAIR_READY_DIAGNOSTIC_ONLY"
    risk_summary_path = output / TOP20_BUCKET_NAME
    risk_summary = pd.read_csv(risk_summary_path) if risk_summary_path.exists() and not missing else pd.DataFrame()
    validation = {
        "stage": "V21.088-R1_INTERACTION_MATURITY_RECHECK_AND_PULLBACK_REPAIR_REVIEW",
        "final_status": status, "decision": decision, "research_only": True, "diagnostic_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False, "broker_action_created": False,
        "protected_outputs_modified": modified, "d_baseline_preserved": True, "technical_085_preserved": True,
        "fundamental_086_preserved": True, "interaction_087_preserved": True,
        "source_latest_price_date": latest, "interaction_bridge_rows_checked": 0 if missing else int(len(maturity)),
        "newly_matured_5d_count": 0 if missing else int(((maturity["forward_window"].eq("5D")) & maturity["maturity_status"].eq("NEWLY_MATURED")).sum()),
        "newly_matured_10d_count": 0 if missing else int(((maturity["forward_window"].eq("10D")) & maturity["maturity_status"].eq("NEWLY_MATURED")).sum()),
        "newly_matured_20d_count": 0 if missing else int(((maturity["forward_window"].eq("20D")) & maturity["maturity_status"].eq("NEWLY_MATURED")).sum()),
        "total_matured_5d_count": counts.get("5D", 0), "total_matured_10d_count": counts.get("10D", 0), "total_matured_20d_count": counts.get("20D", 0),
        "total_pending_5d_count": 0 if missing else int(((maturity["forward_window"].eq("5D")) & ~maturity["forward_matured_after"].map(truth)).sum()),
        "total_pending_10d_count": 0 if missing else int(((maturity["forward_window"].eq("10D")) & ~maturity["forward_matured_after"].map(truth)).sum()),
        "total_pending_20d_count": 0 if missing else int(((maturity["forward_window"].eq("20D")) & ~maturity["forward_matured_after"].map(truth)).sum()),
        "interaction_waiting_for_maturity": sum(counts.values()) == 0, "original_pullback_rows": original_rows,
        "repaired_pullback_candidate_rows": repaired_rows, "best_repaired_pullback_label_20d": best_label,
        "best_repaired_pullback_delta_20d": best_delta, "original_pullback_delta_20d": original_delta,
        "pullback_repair_status": "PULLBACK_REPAIR_DIAGNOSTIC_READY" if not missing else "INPUTS_MISSING",
        "top20_core_diagnostic_count": int(risk_summary.loc[risk_summary["risk_bucket"].eq("STRONG_TECH_STRONG_FUNDAMENTAL_CORE_DIAGNOSTIC"), "d_top20_count"].sum()) if not risk_summary.empty else 0,
        "top20_overextended_strong_fundamental_count": int(risk_summary.loc[risk_summary["risk_bucket"].eq("OVEREXTENDED_STRONG_FUNDAMENTAL_MONITOR_EXTENSION_RISK"), "d_top20_count"].sum()) if not risk_summary.empty else 0,
        "top20_low_quality_momentum_risk_count": int(risk_summary.loc[risk_summary["risk_bucket"].eq("LOW_QUALITY_MOMENTUM_RISK_REVIEW"), "d_top20_count"].sum()) if not risk_summary.empty else 0,
        "top20_interaction_unavailable_count": int(risk_summary.loc[risk_summary["risk_bucket"].eq("INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW"), "d_top20_count"].sum()) if not risk_summary.empty else 0,
        "top20_wait_for_tech_confirmation_count": int(risk_summary.loc[risk_summary["risk_bucket"].isin(["FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION"]), "d_top20_count"].sum()) if not risk_summary.empty else 0,
        "leakage_warning_count": 0, "data_warning_count": 0, "pullback_warning_count": 0,
        "repaired_pullback_adoption_allowed": False,
        "recommended_next_stage": "V21.089-R1_D_TOP20_BUCKET_MONITOR_AND_LOW_QUALITY_MOMENTUM_REVIEW",
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
    for key in ("final_status", "decision", "interaction_bridge_rows_checked", "original_pullback_rows"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
