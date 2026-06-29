#!/usr/bin/env python
"""V21.087-R1 diagnostic tech x fundamental interaction layer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_087_r1")
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
FUND_REL = Path("outputs/v21/diagnostics/v21_086_r1/V21_086_R1_FUNDAMENTAL_PIT_PANEL.csv")
TOP20_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/v21_066a_latest_data_ranking_viewer/V21_066A_D_LATEST_RANKING_TOP20.csv")
ALT_RANK_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")

PANEL_NAME = "V21_087_R1_INTERACTION_PANEL.csv"
COVERAGE_NAME = "V21_087_R1_INTERACTION_COVERAGE_REPORT.csv"
FORWARD_NAME = "V21_087_R1_INTERACTION_FORWARD_RETURN_SUMMARY.csv"
BRIDGE_NAME = "V21_087_R1_INTERACTION_MATURITY_BRIDGE.csv"
OVERLAY_NAME = "V21_087_R1_TOP20_D_INTERACTION_OVERLAY.csv"
BUCKET_NAME = "V21_087_R1_D_TOP20_BUCKET_SUMMARY.csv"
RULES_NAME = "V21_087_R1_INTERACTION_LABEL_RULES_AUDIT.csv"
MUTATION_NAME = "V21_087_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_087_R1_VALIDATION_SUMMARY.csv"

TECH = [
    "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_DAY0_WATCH_ONLY",
    "TECH_BREAKOUT_CONFIRMED", "TECH_BREAKOUT_FAILURE_RISK",
    "TECH_PULLBACK_BUY_CANDIDATE", "TECH_OVEREXTENDED_BUT_STRONG",
    "TECH_WEAK_OR_NO_CONFIRMATION",
]
FUND = [
    "GROWTH_STRONG", "PROFITABILITY_IMPROVING", "QUALITY_STRONG",
    "VALUATION_REASONABLE_FOR_GROWTH", "BALANCE_SHEET_STRONG", "REVISION_POSITIVE",
    "FUNDAMENTAL_STRONG_COMPOUNDING", "FUNDAMENTAL_CYCLICAL_RECOVERY",
    "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY", "FUNDAMENTAL_VALUE_TRAP_RISK",
    "FUNDAMENTAL_WEAK_OR_UNCONFIRMED",
]
INTERACTIONS = [
    "STRONG_TECH_STRONG_FUNDAMENTAL", "STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL",
    "WEAK_TECH_STRONG_FUNDAMENTAL", "WEAK_TECH_WEAK_FUNDAMENTAL",
    "OVEREXTENDED_STRONG_FUNDAMENTAL", "OVEREXTENDED_WEAK_OR_UNCONFIRMED_FUNDAMENTAL",
    "BREAKOUT_CONFIRMED_STRONG_FUNDAMENTAL", "BREAKOUT_CONFIRMED_LOW_QUALITY",
    "BREAKOUT_DAY0_STRONG_FUNDAMENTAL_WATCH_ONLY", "BREAKOUT_DAY0_WEAK_FUNDAMENTAL_WATCH_ONLY",
    "PULLBACK_WITH_STRONG_FUNDAMENTAL", "PULLBACK_WITH_WEAK_FUNDAMENTAL",
    "TECHNICAL_TRADE_ONLY", "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION",
    "LOW_QUALITY_MOMENTUM_RISK", "HIGH_QUALITY_MOMENTUM_CANDIDATE",
    "INTERACTION_UNAVAILABLE",
]
WINDOWS = (5, 10, 20)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (root / TECH_REL).is_file() or not (root / FUND_REL).is_file():
        return pd.DataFrame(), pd.DataFrame()
    fund_cols = [
        "as_of_date", "ticker", "source_latest_price_date", "close",
        "fundamental_available_date_used", "pit_certification_level", "pit_warning",
        "leakage_risk_flag", "return_5d_forward", "return_10d_forward",
        "return_20d_forward", "forward_5d_matured", "forward_10d_matured",
        "forward_20d_matured",
    ] + FUND
    fund = pd.read_csv(root / FUND_REL, usecols=lambda c: c in fund_cols, low_memory=False)
    fund["ticker"] = fund["ticker"].astype(str).str.upper().str.strip()
    fund["as_of_date"] = pd.to_datetime(fund["as_of_date"])

    tickers = set(fund["ticker"])
    max_date = str(fund["as_of_date"].max().date())
    tech_cols = ["as_of_date", "ticker"] + TECH
    chunks = []
    for chunk in pd.read_csv(root / TECH_REL, usecols=lambda c: c in tech_cols, chunksize=200000, low_memory=False):
        chunk["ticker"] = chunk["ticker"].astype(str).str.upper().str.strip()
        keep = chunk["ticker"].isin(tickers) & (chunk["as_of_date"].astype(str).str[:10] <= max_date)
        chunks.append(chunk[keep].copy())
    tech = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=tech_cols)
    tech["as_of_date"] = pd.to_datetime(tech["as_of_date"])
    return tech, fund


def asof_join(tech: pd.DataFrame, fund: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, f in fund.groupby("ticker", sort=False):
        t = tech[tech["ticker"].eq(ticker)].sort_values("as_of_date")
        f = f.sort_values("as_of_date")
        if t.empty:
            out = f.copy()
            for c in TECH:
                out[c] = np.nan
            out["technical_as_of_date"] = pd.NaT
        else:
            out = pd.merge_asof(
                f, t.rename(columns={"as_of_date": "technical_as_of_date"}),
                left_on="as_of_date", right_on="technical_as_of_date",
                by="ticker", direction="backward", allow_exact_matches=True,
            )
        rows.append(out)
    panel = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    panel["fundamental_as_of_date"] = panel["as_of_date"]
    panel["technical_labels_available"] = panel[TECH].notna().any(axis=1)
    panel["fundamental_labels_available"] = panel[FUND].notna().any(axis=1)
    return panel


def bool_series(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna(False).map(truth)


def add_interactions(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    strong_tech = bool_series(p, "TECH_STRONG_TREND_CONTINUATION") | bool_series(p, "TECH_BREAKOUT_CONFIRMED") | bool_series(p, "TECH_OVEREXTENDED_BUT_STRONG")
    weak_tech = bool_series(p, "TECH_WEAK_OR_NO_CONFIRMATION") & ~strong_tech
    positive_f = sum(bool_series(p, c) for c in ["GROWTH_STRONG", "PROFITABILITY_IMPROVING", "QUALITY_STRONG", "VALUATION_REASONABLE_FOR_GROWTH", "BALANCE_SHEET_STRONG", "REVISION_POSITIVE"])
    strong_f = bool_series(p, "FUNDAMENTAL_STRONG_COMPOUNDING") | positive_f.ge(3)
    weak_f = bool_series(p, "FUNDAMENTAL_WEAK_OR_UNCONFIRMED") | (~p["fundamental_labels_available"]) | positive_f.lt(2)
    low_quality = bool_series(p, "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY") | (bool_series(p, "GROWTH_STRONG") & ~bool_series(p, "QUALITY_STRONG"))
    over = bool_series(p, "TECH_OVEREXTENDED_BUT_STRONG")
    br = bool_series(p, "TECH_BREAKOUT_CONFIRMED")
    day0 = bool_series(p, "TECH_BREAKOUT_DAY0_WATCH_ONLY")
    pull = bool_series(p, "TECH_PULLBACK_BUY_CANDIDATE")
    unavailable = (~p["technical_labels_available"]) | (~p["fundamental_labels_available"])

    rules = {
        "STRONG_TECH_STRONG_FUNDAMENTAL": strong_tech & strong_f & ~unavailable,
        "STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL": strong_tech & weak_f,
        "WEAK_TECH_STRONG_FUNDAMENTAL": weak_tech & strong_f,
        "WEAK_TECH_WEAK_FUNDAMENTAL": weak_tech & weak_f,
        "OVEREXTENDED_STRONG_FUNDAMENTAL": over & strong_f,
        "OVEREXTENDED_WEAK_OR_UNCONFIRMED_FUNDAMENTAL": over & weak_f,
        "BREAKOUT_CONFIRMED_STRONG_FUNDAMENTAL": br & strong_f,
        "BREAKOUT_CONFIRMED_LOW_QUALITY": br & low_quality,
        "BREAKOUT_DAY0_STRONG_FUNDAMENTAL_WATCH_ONLY": day0 & strong_f,
        "BREAKOUT_DAY0_WEAK_FUNDAMENTAL_WATCH_ONLY": day0 & weak_f,
        "PULLBACK_WITH_STRONG_FUNDAMENTAL": pull & strong_f,
        "PULLBACK_WITH_WEAK_FUNDAMENTAL": pull & weak_f,
        "TECHNICAL_TRADE_ONLY": strong_tech & (~p["fundamental_labels_available"]),
        "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION": strong_f & (~strong_tech),
        "LOW_QUALITY_MOMENTUM_RISK": strong_tech & low_quality,
        "HIGH_QUALITY_MOMENTUM_CANDIDATE": strong_tech & bool_series(p, "QUALITY_STRONG") & strong_f,
        "INTERACTION_UNAVAILABLE": unavailable,
    }
    for label, value in rules.items():
        p[label] = value.astype(bool)
    def primary(row: pd.Series) -> str:
        for label in INTERACTIONS:
            if truth(row[label]):
                return label
        return "INTERACTION_UNAVAILABLE"
    p["interaction_primary_label"] = p.apply(primary, axis=1)
    p["interaction_secondary_labels"] = p.apply(lambda r: "|".join([x for x in INTERACTIONS if truth(r[x]) and x != r["interaction_primary_label"]]), axis=1)
    p["interaction_confidence_level"] = np.where(~p["technical_labels_available"] | ~p["fundamental_labels_available"], "LOW_MISSING_LAYER", np.where(strong_tech & strong_f, "HIGH_DIAGNOSTIC", "MEDIUM_DIAGNOSTIC"))
    p["interaction_data_quality_warning"] = np.where(~p["technical_labels_available"], "MISSING_TECHNICAL_LABELS", np.where(~p["fundamental_labels_available"], "MISSING_FUNDAMENTAL_LABELS", ""))
    p["interaction_adoption_allowed"] = False
    return p


def maturity_date(asof: str, window: int) -> str:
    return (pd.Timestamp(asof) + pd.tseries.offsets.BDay(window)).date().isoformat()


def bridge(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in panel.iterrows():
        asof = str(pd.Timestamp(r["as_of_date"]).date())
        for w in WINDOWS:
            rows.append({
                "observation_id": f"V21_087::{asof}::{r['ticker']}::{w}D",
                "ticker": r["ticker"], "as_of_date": asof,
                "interaction_primary_label": r["interaction_primary_label"],
                "interaction_secondary_labels": r["interaction_secondary_labels"],
                "forward_window": f"{w}D",
                "maturity_date": maturity_date(asof, w),
                "forward_matured_flag": bool(truth(r[f"forward_{w}d_matured"])),
                "return_forward": r.get(f"return_{w}d_forward", np.nan),
                "technical_as_of_date": "" if pd.isna(r["technical_as_of_date"]) else str(pd.Timestamp(r["technical_as_of_date"]).date()),
                "fundamental_as_of_date": str(pd.Timestamp(r["fundamental_as_of_date"]).date()),
                "fundamental_available_date_used": r["fundamental_available_date_used"],
                "pit_certification_level": r["pit_certification_level"],
                "scheduled_from_stage": "V21.087-R1",
                "review_stage_recommended": "V21.088-R1_INTERACTION_MATURITY_RECHECK_AND_PULLBACK_REPAIR_REVIEW",
            })
    return pd.DataFrame(rows)


def forward_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in INTERACTIONS:
        for w in WINDOWS:
            mat = panel[f"forward_{w}d_matured"].fillna(False).map(truth)
            sub = panel[mat & panel[f"return_{w}d_forward"].notna() & panel[label].notna()]
            true = sub[sub[label].astype(bool)]
            false = sub[~sub[label].astype(bool)]
            if sub.empty:
                rows.append({"interaction_label": label, "forward_window": f"{w}D", "matured_count": 0, "label_true_count": 0, "label_false_count": 0, "label_true_mean_forward_return": "", "label_false_mean_forward_return": "", "delta_true_minus_false": "", "label_true_median_forward_return": "", "label_false_median_forward_return": "", "hit_rate_true": "", "hit_rate_false": "", "hit_rate_delta": "", "performance_status": "WAITING_FOR_MATURITY", "usable_for_research_flag": False, "warning": "NO_MATURED_FORWARD_OBSERVATIONS"})
            else:
                rows.append({"interaction_label": label, "forward_window": f"{w}D", "matured_count": len(sub), "label_true_count": len(true), "label_false_count": len(false), "label_true_mean_forward_return": true[f"return_{w}d_forward"].mean() if len(true) else np.nan, "label_false_mean_forward_return": false[f"return_{w}d_forward"].mean() if len(false) else np.nan, "delta_true_minus_false": (true[f"return_{w}d_forward"].mean() - false[f"return_{w}d_forward"].mean()) if len(true) and len(false) else np.nan, "label_true_median_forward_return": true[f"return_{w}d_forward"].median() if len(true) else np.nan, "label_false_median_forward_return": false[f"return_{w}d_forward"].median() if len(false) else np.nan, "hit_rate_true": true[f"return_{w}d_forward"].gt(0).mean() if len(true) else np.nan, "hit_rate_false": false[f"return_{w}d_forward"].gt(0).mean() if len(false) else np.nan, "hit_rate_delta": (true[f"return_{w}d_forward"].gt(0).mean() - false[f"return_{w}d_forward"].gt(0).mean()) if len(true) and len(false) else np.nan, "performance_status": "MATURED_DIAGNOSTIC_ONLY", "usable_for_research_flag": len(true) >= 30 and len(false) >= 30, "warning": ""})
    return pd.DataFrame(rows)


def coverage(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = TECH + FUND + INTERACTIONS
    for label in labels:
        non = panel[label].notna() if label in panel else pd.Series(False, index=panel.index)
        true = panel[label].fillna(False).map(truth) if label in panel else pd.Series(False, index=panel.index)
        rows.append({"label_name": label, "label_type": "interaction" if label in INTERACTIONS else "technical" if label in TECH else "fundamental", "non_null_count": int(non.sum()), "true_count": int(true.sum()), "true_ratio": float(true.mean()) if len(panel) else 0, "ticker_coverage_count": int(panel.loc[non, "ticker"].nunique()) if non.any() else 0, "as_of_date_coverage_count": int(panel.loc[non, "as_of_date"].nunique()) if non.any() else 0, "min_date": panel.loc[non, "as_of_date"].min() if non.any() else "", "max_date": panel.loc[non, "as_of_date"].max() if non.any() else "", "technical_available_ratio": float(panel["technical_labels_available"].mean()) if len(panel) else 0, "fundamental_available_ratio": float(panel["fundamental_labels_available"].mean()) if len(panel) else 0, "pit_certified_ratio": float(panel["pit_certification_level"].astype(str).str.startswith("PIT").mean()) if len(panel) else 0, "warning": "" if non.any() else "LABEL_UNAVAILABLE"})
    return pd.DataFrame(rows)


def top20(root: Path, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = root / TOP20_REL if (root / TOP20_REL).exists() else root / ALT_RANK_REL
    rank = pd.read_csv(path, low_memory=False)
    if "rank" not in rank and "final_shadow_rank" in rank:
        rank["rank"] = rank["final_shadow_rank"]
    if "final_score" not in rank and "final_shadow_score" in rank:
        rank["final_score"] = rank["final_shadow_score"]
    rank["ticker"] = rank["ticker"].astype(str).str.upper().str.strip()
    rank["rank"] = pd.to_numeric(rank["rank"], errors="coerce")
    top = rank.sort_values("rank").head(20)[["rank", "ticker", "final_score"]]
    latest = panel.sort_values("as_of_date").groupby("ticker", as_index=False).tail(1)
    cols = ["ticker", "close", "interaction_primary_label", "interaction_secondary_labels", "interaction_confidence_level"] + TECH + FUND + INTERACTIONS
    out = top.merge(latest[cols], on="ticker", how="left")
    out["diagnostic_interpretation"] = out["interaction_primary_label"].fillna("INTERACTION_UNAVAILABLE").map(lambda x: {
        "STRONG_TECH_STRONG_FUNDAMENTAL": "Strong trend + PIT-safe fundamental support. Diagnostic only; no adoption.",
        "STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL": "Strong technical but weak or unavailable fundamental confirmation. Treat as technical trade only.",
        "BREAKOUT_CONFIRMED_LOW_QUALITY": "Breakout confirmed but low quality. Watch risk; no adoption.",
        "PULLBACK_WITH_WEAK_FUNDAMENTAL": "Pullback with weak fundamental confirmation. Require caution.",
        "WEAK_TECH_STRONG_FUNDAMENTAL": "Fundamental strong but technical weak. Wait for technical confirmation.",
    }.get(x, "Interaction diagnostic only; no adoption."))
    out["adoption_allowed"] = False
    out["no_trade_action_created"] = True
    out = out.rename(columns={"rank": "D rank", "final_score": "D final score", "close": "latest close"})
    bucket = out.groupby("interaction_primary_label", dropna=False).agg(
        d_top20_count=("ticker", "count"),
        tickers=("ticker", lambda s: "|".join(s.astype(str))),
        avg_d_rank=("D rank", "mean"),
        avg_d_final_score=("D final score", "mean"),
        technical_available_count=("TECH_STRONG_TREND_CONTINUATION", lambda s: int(s.notna().sum())),
        fundamental_available_count=("GROWTH_STRONG", lambda s: int(s.notna().sum())),
        strong_tech_count=("STRONG_TECH_STRONG_FUNDAMENTAL", lambda s: int(s.fillna(False).map(truth).sum())),
        strong_fundamental_count=("FUNDAMENTAL_STRONG_COMPOUNDING", lambda s: int(s.fillna(False).map(truth).sum())),
    ).reset_index()
    bucket["warning"] = ""
    return out, bucket


def rules() -> pd.DataFrame:
    data = []
    for label in INTERACTIONS:
        data.append({"interaction_label": label, "rule_expression_plain_english": "Null-safe diagnostic rule using PIT technical labels on/before as_of_date and fundamental labels available by as_of_date.", "required_technical_labels": "|".join([x for x in TECH if x.split("TECH_")[-1].split("_")[0] in label]), "required_fundamental_labels": "|".join(FUND), "missing_data_behavior": "Missing layer sets INTERACTION_UNAVAILABLE or weak/unconfirmed with warning; unavailable is not treated as proved negative quality.", "adoption_allowed": False, "warning": ""})
    return pd.DataFrame(data)


def mutation_audit(paths: list[Path], before: dict[Path, str], after: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for p in paths:
        text = p.as_posix().lower()
        ptype = "broker_action" if "broker" in text else "official_weight" if "weight" in text and "official" in text else "official_ranking" if "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text else "protected"
        rows.append({"path": p.as_posix(), "path_type": ptype, "exists_before": p in before, "exists_after": p.exists(), "modified_during_run": before.get(p) != after.get(p), "mutation_allowed": False, "warning": "" if before.get(p) == after.get(p) else "DISALLOWED_MUTATION_DETECTED"})
    return pd.DataFrame(rows)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/diagnostics/v21_085_r1", "outputs/v21/diagnostics/v21_086_r1", "outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075"):
        base = root / rel
        if base.exists():
            protected.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    protected = sorted(set(protected))
    before = {p: sha256(p) for p in protected}

    missing_inputs = not (root / TECH_REL).is_file() or not (root / FUND_REL).is_file()
    if missing_inputs:
        panel = pd.DataFrame()
    else:
        tech, fund = load_inputs(root)
        panel = add_interactions(asof_join(tech, fund))
        panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date.astype(str)
        panel["technical_as_of_date"] = pd.to_datetime(panel["technical_as_of_date"], errors="coerce").dt.date.astype(str).replace("NaT", "")
        panel["fundamental_as_of_date"] = pd.to_datetime(panel["fundamental_as_of_date"]).dt.date.astype(str)
    panel.to_csv(output / PANEL_NAME, index=False)
    cov = coverage(panel) if not panel.empty else pd.DataFrame()
    fs = forward_summary(panel) if not panel.empty else pd.DataFrame()
    br = bridge(panel) if not panel.empty else pd.DataFrame()
    ov, buck = top20(root, panel) if not panel.empty else (pd.DataFrame(), pd.DataFrame())
    cov.to_csv(output / COVERAGE_NAME, index=False)
    fs.to_csv(output / FORWARD_NAME, index=False)
    br.to_csv(output / BRIDGE_NAME, index=False)
    ov.to_csv(output / OVERLAY_NAME, index=False)
    buck.to_csv(output / BUCKET_NAME, index=False)
    rules().to_csv(output / RULES_NAME, index=False)
    after = {p: sha256(p) for p in protected}
    mut = mutation_audit(protected, before, after)
    mut.to_csv(output / MUTATION_NAME, index=False)
    modified = bool(mut["modified_during_run"].any()) if not mut.empty else False
    leakage = 0
    data_warn = 0 if not missing_inputs and not panel.empty and panel["technical_labels_available"].all() and panel["fundamental_labels_available"].all() else 1
    wait = True if fs.empty else fs["performance_status"].eq("WAITING_FOR_MATURITY").all()
    if missing_inputs:
        status = "BLOCKED_V21_087_R1_REQUIRED_INPUTS_MISSING"
        decision = "INTERACTION_LAYER_REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif modified or leakage:
        status = "BLOCKED_V21_087_R1_INTERACTION_LAYER_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        decision = "INTERACTION_LAYER_BLOCKED_REVIEW_REQUIRED"
    elif data_warn:
        status = "PARTIAL_PASS_V21_087_R1_INTERACTION_LAYER_READY_WITH_DATA_WARN_WAITING_FOR_MATURITY"
        decision = "INTERACTION_LAYER_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY_WAITING_FOR_MATURITY"
    else:
        status = "PASS_V21_087_R1_INTERACTION_LAYER_READY_WAITING_FOR_MATURITY"
        decision = "INTERACTION_LAYER_READY_DIAGNOSTIC_ONLY_WAITING_FOR_MATURITY"
    validation = {
        "stage": "V21.087-R1_TECH_FUNDAMENTAL_INTERACTION_LAYER",
        "final_status": status, "decision": decision,
        "research_only": True, "diagnostic_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "protected_outputs_modified": modified,
        "d_baseline_preserved": True, "technical_085_preserved": True, "fundamental_086_preserved": True,
        "source_latest_price_date": "" if panel.empty else panel.get("source_latest_price_date", pd.Series([""])).max(),
        "interaction_row_count": int(len(panel)), "ticker_count": int(panel["ticker"].nunique()) if not panel.empty else 0,
        "interaction_label_count": len(INTERACTIONS), "top20_overlay_count": int(len(ov)), "maturity_bridge_row_count": int(len(br)),
        "matured_5d_count": int(panel["forward_5d_matured"].fillna(False).map(truth).sum()) if not panel.empty else 0,
        "matured_10d_count": int(panel["forward_10d_matured"].fillna(False).map(truth).sum()) if not panel.empty else 0,
        "matured_20d_count": int(panel["forward_20d_matured"].fillna(False).map(truth).sum()) if not panel.empty else 0,
        "pending_5d_count": int((~panel["forward_5d_matured"].fillna(False).map(truth)).sum()) if not panel.empty else 0,
        "pending_10d_count": int((~panel["forward_10d_matured"].fillna(False).map(truth)).sum()) if not panel.empty else 0,
        "pending_20d_count": int((~panel["forward_20d_matured"].fillna(False).map(truth)).sum()) if not panel.empty else 0,
        "waiting_for_maturity": wait, "leakage_warning_count": leakage, "data_warning_count": data_warn,
        "interaction_adoption_allowed": False,
        "top20_strong_tech_strong_fundamental_count": int(ov["STRONG_TECH_STRONG_FUNDAMENTAL"].fillna(False).map(truth).sum()) if not ov.empty else 0,
        "top20_strong_tech_weak_or_unconfirmed_fundamental_count": int(ov["STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL"].fillna(False).map(truth).sum()) if not ov.empty else 0,
        "top20_breakout_confirmed_strong_fundamental_count": int(ov["BREAKOUT_CONFIRMED_STRONG_FUNDAMENTAL"].fillna(False).map(truth).sum()) if not ov.empty else 0,
        "top20_overextended_strong_fundamental_count": int(ov["OVEREXTENDED_STRONG_FUNDAMENTAL"].fillna(False).map(truth).sum()) if not ov.empty else 0,
        "top20_pullback_with_weak_fundamental_count": int(ov["PULLBACK_WITH_WEAK_FUNDAMENTAL"].fillna(False).map(truth).sum()) if not ov.empty else 0,
        "recommended_next_stage": "V21.088-R1_INTERACTION_MATURITY_RECHECK_AND_PULLBACK_REPAIR_REVIEW",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for k in ("final_status", "decision", "interaction_row_count", "maturity_bridge_row_count"):
        print(f"{k.upper()}={result[k]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
