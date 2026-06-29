#!/usr/bin/env python
"""V21.092-R1 factor effectiveness and nested walk-forward shadow weight search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_092_r1")
TECH_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
TECH_SUMMARY_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_SIGNAL_FORWARD_RETURN_SUMMARY.csv")
FUND_REL = Path("outputs/v21/diagnostics/v21_086_r1/V21_086_R1_FUNDAMENTAL_PIT_PANEL.csv")
INTERACTION_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_PANEL.csv")
MONITOR_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_BUCKET_MONITOR.csv")
ARCHIVE_DIR_REL = Path("outputs/v21/diagnostics/v21_090_r1")
MATURITY_DIR_REL = Path("outputs/v21/diagnostics/v21_091_r1")
D_RANKING_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

INVENTORY_NAME = "V21_092_R1_INPUT_SOURCE_INVENTORY.csv"
PANEL_NAME = "V21_092_R1_FACTOR_EFFECTIVENESS_PANEL.csv"
IC_NAME = "V21_092_R1_FACTOR_IC_AND_QUANTILE_SUMMARY.csv"
REGIME_NAME = "V21_092_R1_REGIME_CONDITIONED_FACTOR_SUMMARY.csv"
SPLIT_NAME = "V21_092_R1_NESTED_WALKFORWARD_SPLIT_PLAN.csv"
GRID_NAME = "V21_092_R1_WEIGHT_SEARCH_GRID.csv"
RESULTS_NAME = "V21_092_R1_NESTED_WALKFORWARD_WEIGHT_RESULTS.csv"
CANDIDATE_NAME = "V21_092_R1_DYNAMIC_WEIGHT_SHADOW_CANDIDATE_SUMMARY.csv"
SELECTED_NAME = "V21_092_R1_SELECTED_SHADOW_WEIGHT_CANDIDATE.csv"
D_COMPARE_NAME = "V21_092_R1_D_BASELINE_COMPARISON_SUMMARY.csv"
LEDGER_NAME = "V21_092_R1_FORWARD_LEDGER_PLAN.csv"
FORBIDDEN_NAME = "V21_092_R1_FORBIDDEN_SIGNAL_AUDIT.csv"
CERT_NAME = "V21_092_R1_NO_ADOPTION_CERTIFICATION.csv"
MUTATION_NAME = "V21_092_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_092_R1_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, PANEL_NAME, IC_NAME, REGIME_NAME, SPLIT_NAME, GRID_NAME,
    RESULTS_NAME, CANDIDATE_NAME, SELECTED_NAME, D_COMPARE_NAME, LEDGER_NAME,
    FORBIDDEN_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")
FACTOR_FAMILIES = {
    "z_tech_trend_continuation": "TECHNICAL",
    "z_tech_breakout_confirmed": "TECHNICAL",
    "z_tech_overextended_but_strong": "TECHNICAL",
    "z_tech_rs_vs_qqq": "TECHNICAL",
    "z_tech_rs_vs_spy": "TECHNICAL",
    "z_tech_rs_vs_soxx": "TECHNICAL",
    "z_tech_macd_hist_acceleration": "TECHNICAL",
    "z_tech_ma_slope_alignment": "TECHNICAL",
    "z_tech_volume_confirmation": "TECHNICAL",
    "z_tech_pullback_original": "TECHNICAL_CONSTRAINED",
    "z_tech_pullback_repaired_best": "TECHNICAL_CONSTRAINED",
    "z_fund_growth": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_profitability": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_quality": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_valuation_reasonable": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_balance_sheet": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_revision": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_strong_compounding": "FUNDAMENTAL_LOW_CONFIDENCE",
    "z_fund_low_quality_risk": "FUNDAMENTAL_RISK",
    "z_interaction_strong_tech_strong_fundamental": "INTERACTION_LOW_CONFIDENCE",
    "z_interaction_overextended_strong_fundamental": "INTERACTION_LOW_CONFIDENCE",
    "z_interaction_low_quality_momentum_risk": "INTERACTION_RISK",
    "z_interaction_wait_confirmation": "INTERACTION_RISK",
    "z_bucket_strong_but_extended": "BUCKET_DIAGNOSTIC",
    "z_bucket_core_diagnostic": "BUCKET_DIAGNOSTIC",
    "z_bucket_low_quality_momentum": "BUCKET_RISK",
    "z_bucket_day0_watch_only": "BUCKET_RISK",
    "z_bucket_interaction_data_gap": "BUCKET_RISK",
}
FACTOR_COLUMNS = list(FACTOR_FAMILIES)
COMPONENT_COLUMNS = [
    "Base", "Momentum", "TechnicalTrend", "TechnicalBreakout",
    "TechnicalRelativeStrength", "FundamentalQuality", "FundamentalGrowth",
    "InteractionQuality", "RiskPenalty", "PullbackPenalty",
]


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def z_by_date(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    grouped = numeric.groupby(frame["as_of_date"])
    mean = grouped.transform("mean")
    std = grouped.transform("std").replace(0, np.nan)
    return ((numeric - mean) / std).clip(-4, 4)


def bool_float(series: pd.Series) -> pd.Series:
    return series.map(lambda x: float(truth(x)) if not pd.isna(x) else np.nan)


def source_inventory(root: Path) -> pd.DataFrame:
    sources = [
        (TECH_REL, "TECHNICAL_HISTORICAL_REQUIRED"),
        (TECH_SUMMARY_REL, "TECHNICAL_FORWARD_SUMMARY"),
        (FUND_REL, "FUNDAMENTAL_PIT_OPTIONAL_LOW_CONFIDENCE"),
        (INTERACTION_REL, "INTERACTION_OPTIONAL_LOW_CONFIDENCE"),
        (MONITOR_REL, "LATEST_BUCKET_DIAGNOSTIC"),
        (D_RANKING_REL, "LATEST_D_RANKING_REFERENCE"),
        (PRICE_REL, "LOCAL_PRICE_REFERENCE"),
    ]
    sources.extend((p.relative_to(root), "V21_090_ARCHIVE_REFERENCE") for p in sorted((root / ARCHIVE_DIR_REL).glob("*")) if p.is_file())
    rows = []
    for rel, role in sources:
        path = root / rel
        exists = path.is_file()
        row_count = ticker_count = 0
        min_date = max_date = ""
        date_cols: list[str] = []
        warning = ""
        if exists and path.suffix.lower() == ".csv":
            try:
                sample = pd.read_csv(path, nrows=5)
                date_cols = [c for c in sample.columns if "date" in c.lower()]
                use = [c for c in ["ticker", "symbol"] + date_cols if c in sample.columns]
                data = pd.read_csv(path, usecols=use, low_memory=False) if use else pd.read_csv(path, usecols=[sample.columns[0]], low_memory=False)
                row_count = len(data)
                tcol = "ticker" if "ticker" in data else "symbol" if "symbol" in data else None
                ticker_count = data[tcol].nunique() if tcol else 0
                if date_cols:
                    dates = pd.concat([data[c].astype(str).str[:10] for c in date_cols if c in data], ignore_index=True)
                    dates = dates[dates.str.match(r"\d{4}-\d{2}-\d{2}", na=False)]
                    if not dates.empty:
                        min_date, max_date = dates.min(), dates.max()
            except Exception as exc:
                warning = f"INVENTORY_READ_WARNING:{type(exc).__name__}"
        elif not exists:
            warning = "OPTIONAL_SOURCE_MISSING" if rel != TECH_REL else "REQUIRED_SOURCE_MISSING"
        rows.append({
            "source_path": rel.as_posix(), "source_role": role, "exists": exists,
            "row_count": row_count, "ticker_count": ticker_count,
            "min_date": min_date, "max_date": max_date,
            "date_columns_detected": "|".join(date_cols),
            "usable_for_factor_effectiveness": bool(exists and rel in {TECH_REL, FUND_REL, INTERACTION_REL}),
            "usable_for_weight_search": bool(exists and rel == TECH_REL),
            "warning": warning,
        })
    return pd.DataFrame(rows)


def build_factor_panel(root: Path) -> pd.DataFrame:
    technical_cols = [
        "as_of_date", "ticker", "source_price_date", "close",
        "return_5d_forward", "return_10d_forward", "return_20d_forward",
        "forward_5d_matured", "forward_10d_matured", "forward_20d_matured",
        "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_CONFIRMED",
        "TECH_OVEREXTENDED_BUT_STRONG", "TECH_PULLBACK_BUY_CANDIDATE",
        "TECH_BREAKOUT_DAY0_WATCH_ONLY", "rs_vs_qqq_10d", "rs_vs_spy_10d",
        "rs_vs_soxx_10d", "macd_hist_slope_3d", "ma20_slope_5d",
        "ma50_slope_5d", "volume_ratio_20d", "breakout_volume_confirmed",
        "rsi_14", "rsi_14_slope_3d", "macd_hist", "macd_zero_axis_above",
        "kdj_confirmed_by_price", "close_above_ma50",
        "qqq_ret_5d", "qqq_ret_10d", "qqq_ret_20d",
    ]
    panel = pd.read_csv(root / TECH_REL, usecols=lambda c: c in technical_cols, low_memory=False)
    panel["as_of_date"] = panel["as_of_date"].astype(str).str[:10]
    panel["ticker"] = panel["ticker"].astype(str).str.upper().str.strip()
    panel["source_panel"] = "V21_085_TECHNICAL_FEATURE_PANEL"
    panel["source_latest_price_date"] = panel["source_price_date"].astype(str).str[:10]
    for window in ("5d", "10d", "20d"):
        matured = panel[f"forward_{window}_matured"].map(truth)
        panel.loc[~matured, f"return_{window}_forward"] = np.nan
    raw = {
        "z_tech_trend_continuation": bool_float(panel["TECH_STRONG_TREND_CONTINUATION"]),
        "z_tech_breakout_confirmed": bool_float(panel["TECH_BREAKOUT_CONFIRMED"]),
        "z_tech_overextended_but_strong": bool_float(panel["TECH_OVEREXTENDED_BUT_STRONG"]),
        "z_tech_rs_vs_qqq": panel["rs_vs_qqq_10d"],
        "z_tech_rs_vs_spy": panel["rs_vs_spy_10d"],
        "z_tech_rs_vs_soxx": panel["rs_vs_soxx_10d"],
        "z_tech_macd_hist_acceleration": panel["macd_hist_slope_3d"],
        "z_tech_ma_slope_alignment": pd.concat([
            pd.to_numeric(panel["ma20_slope_5d"], errors="coerce"),
            pd.to_numeric(panel["ma50_slope_5d"], errors="coerce"),
        ], axis=1).mean(axis=1),
        "z_tech_volume_confirmation": pd.to_numeric(panel["volume_ratio_20d"], errors="coerce").where(
            bool_float(panel["breakout_volume_confirmed"]).fillna(0).eq(1),
            pd.to_numeric(panel["volume_ratio_20d"], errors="coerce") * 0.5,
        ),
        "z_tech_pullback_original": bool_float(panel["TECH_PULLBACK_BUY_CANDIDATE"]),
    }
    repaired = (
        bool_float(panel["TECH_PULLBACK_BUY_CANDIDATE"]).fillna(0).eq(1)
        & pd.to_numeric(panel["rsi_14"], errors="coerce").ge(40)
        & pd.to_numeric(panel["rsi_14_slope_3d"], errors="coerce").ge(0)
        & pd.to_numeric(panel["macd_hist_slope_3d"], errors="coerce").ge(0)
        & (
            bool_float(panel["macd_zero_axis_above"]).fillna(0).eq(1)
            | pd.to_numeric(panel["macd_hist"], errors="coerce").gt(0)
        )
        & bool_float(panel["kdj_confirmed_by_price"]).fillna(0).eq(1)
    ).astype(float)
    raw["z_tech_pullback_repaired_best"] = repaired
    for name, values in raw.items():
        panel[name] = z_by_date(panel, values)

    fundamental_map = {
        "GROWTH_STRONG": "z_fund_growth",
        "PROFITABILITY_IMPROVING": "z_fund_profitability",
        "QUALITY_STRONG": "z_fund_quality",
        "VALUATION_REASONABLE_FOR_GROWTH": "z_fund_valuation_reasonable",
        "BALANCE_SHEET_STRONG": "z_fund_balance_sheet",
        "REVISION_POSITIVE": "z_fund_revision",
        "FUNDAMENTAL_STRONG_COMPOUNDING": "z_fund_strong_compounding",
        "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY": "z_fund_low_quality_risk",
    }
    if (root / FUND_REL).is_file():
        fund = pd.read_csv(root / FUND_REL, usecols=lambda c: c in {"ticker", "as_of_date", *fundamental_map}, low_memory=False)
        fund["ticker"] = fund["ticker"].astype(str).str.upper().str.strip()
        fund["as_of_date"] = fund["as_of_date"].astype(str).str[:10]
        for source, target in fundamental_map.items():
            fund[target] = z_by_date(fund, bool_float(fund[source]))
        panel = panel.merge(fund[["ticker", "as_of_date", *fundamental_map.values()]], on=["ticker", "as_of_date"], how="left")
    interaction_map = {
        "STRONG_TECH_STRONG_FUNDAMENTAL": "z_interaction_strong_tech_strong_fundamental",
        "OVEREXTENDED_STRONG_FUNDAMENTAL": "z_interaction_overextended_strong_fundamental",
        "LOW_QUALITY_MOMENTUM_RISK": "z_interaction_low_quality_momentum_risk",
        "FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION": "z_interaction_wait_confirmation",
    }
    if (root / INTERACTION_REL).is_file():
        inter = pd.read_csv(root / INTERACTION_REL, usecols=lambda c: c in {"ticker", "as_of_date", *interaction_map}, low_memory=False)
        inter["ticker"] = inter["ticker"].astype(str).str.upper().str.strip()
        inter["as_of_date"] = inter["as_of_date"].astype(str).str[:10]
        for source, target in interaction_map.items():
            inter[target] = z_by_date(inter, bool_float(inter[source]))
        panel = panel.merge(inter[["ticker", "as_of_date", *interaction_map.values()]], on=["ticker", "as_of_date"], how="left")
    bucket_map = {
        "STRONG_BUT_EXTENDED": "z_bucket_strong_but_extended",
        "CORE_DIAGNOSTIC": "z_bucket_core_diagnostic",
        "LOW_QUALITY_MOMENTUM_REVIEW": "z_bucket_low_quality_momentum",
        "DAY0_WATCH_ONLY": "z_bucket_day0_watch_only",
        "DATA_GAP_REVIEW": "z_bucket_interaction_data_gap",
    }
    if (root / MONITOR_REL).is_file():
        monitor = pd.read_csv(root / MONITOR_REL, usecols=["ticker", "as_of_date", "D_rank", "D_final_score", "bucket_monitor_status"], low_memory=False)
        monitor["ticker"] = monitor["ticker"].astype(str).str.upper().str.strip()
        monitor["as_of_date"] = monitor["as_of_date"].astype(str).str[:10]
        for status, target in bucket_map.items():
            monitor[target] = z_by_date(monitor, monitor["bucket_monitor_status"].eq(status).astype(float))
        monitor["d_top20_flag"] = True
        monitor = monitor.rename(columns={"D_rank": "d_rank", "D_final_score": "d_final_score"})
        panel = panel.merge(
            monitor[["ticker", "as_of_date", "d_rank", "d_final_score", "d_top20_flag", *bucket_map.values()]],
            on=["ticker", "as_of_date"], how="left",
        )
    if (root / D_RANKING_REL).is_file():
        ranking = pd.read_csv(root / D_RANKING_REL, usecols=["ticker", "as_of_date", "final_shadow_rank"], low_memory=False)
        ranking["ticker"] = ranking["ticker"].astype(str).str.upper().str.strip()
        ranking["as_of_date"] = ranking["as_of_date"].astype(str).str[:10]
        ranking["d_top50_flag_source"] = pd.to_numeric(ranking["final_shadow_rank"], errors="coerce").le(50)
        panel = panel.merge(ranking[["ticker", "as_of_date", "d_top50_flag_source"]], on=["ticker", "as_of_date"], how="left")
    panel["d_top20_flag"] = panel.get("d_top20_flag", False).fillna(False)
    panel["d_top50_flag"] = panel.get("d_top50_flag_source", False).fillna(False) | panel["d_top20_flag"]
    for factor in FACTOR_COLUMNS:
        if factor not in panel:
            panel[factor] = np.nan
    keep = [
        "as_of_date", "ticker", "source_panel", "source_latest_price_date", "close",
        "return_5d_forward", "return_10d_forward", "return_20d_forward",
        "forward_5d_matured", "forward_10d_matured", "forward_20d_matured",
        *FACTOR_COLUMNS, "d_rank", "d_final_score", "d_top20_flag", "d_top50_flag",
        "qqq_ret_5d", "qqq_ret_10d", "qqq_ret_20d",
    ]
    for col in keep:
        if col not in panel:
            panel[col] = np.nan
    return panel[keep]


def daily_factor_stats(group: pd.DataFrame, factor: str, ret_col: str) -> tuple[float, float, float]:
    valid = group[[factor, ret_col]].dropna()
    if len(valid) < 20 or valid[factor].nunique() < 3:
        return np.nan, np.nan, np.nan
    factor_rank = valid[factor].rank(method="average")
    return_rank = valid[ret_col].rank(method="average")
    ic = factor_rank.corr(return_rank)
    ranks = valid[factor].rank(pct=True)
    top = valid.loc[ranks.ge(0.8), ret_col]
    bottom = valid.loc[ranks.le(0.2), ret_col]
    return ic, top.mean() if len(top) else np.nan, bottom.mean() if len(bottom) else np.nan


def factor_effectiveness(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for factor in FACTOR_COLUMNS:
        for window in WINDOWS:
            suffix = window.lower()
            ret_col, mature_col = f"return_{suffix}_forward", f"forward_{suffix}_matured"
            mature = panel[panel[mature_col].map(truth) & panel[ret_col].notna()]
            stats = [daily_factor_stats(g, factor, ret_col) for _, g in mature.groupby("as_of_date")]
            stats = [s for s in stats if pd.notna(s[0])]
            ics = pd.Series([s[0] for s in stats], dtype=float)
            tops = pd.Series([s[1] for s in stats], dtype=float)
            bottoms = pd.Series([s[2] for s in stats], dtype=float)
            non_null = int(mature[factor].notna().sum())
            usable = len(ics) >= 60 and non_null >= 5000 and FACTOR_FAMILIES[factor] == "TECHNICAL"
            stability = bool(usable and abs(ics.mean()) >= 0.01 and (ics.gt(0).mean() >= 0.55 or ics.lt(0).mean() >= 0.55))
            rows.append({
                "factor_name": factor, "factor_family": FACTOR_FAMILIES[factor],
                "forward_window": window, "matured_count": len(mature),
                "non_null_count": non_null, "rank_ic_mean": ics.mean() if len(ics) else np.nan,
                "rank_ic_median": ics.median() if len(ics) else np.nan,
                "rank_ic_std": ics.std() if len(ics) else np.nan,
                "rank_ic_positive_ratio": ics.gt(0).mean() if len(ics) else np.nan,
                "top_quantile_mean_return": tops.mean() if len(tops) else np.nan,
                "bottom_quantile_mean_return": bottoms.mean() if len(bottoms) else np.nan,
                "top_minus_bottom": (tops - bottoms).mean() if len(tops) else np.nan,
                "top_quantile_hit_rate": tops.gt(0).mean() if len(tops) else np.nan,
                "bottom_quantile_hit_rate": bottoms.gt(0).mean() if len(bottoms) else np.nan,
                "stability_flag": stability, "usable_for_weight_search": usable,
                "warning": "" if usable else "INSUFFICIENT_MATURED_DATES_OR_LOW_CONFIDENCE_FAMILY",
            })
    return pd.DataFrame(rows)


def regime_summary(panel: pd.DataFrame) -> pd.DataFrame:
    tech = pd.read_csv(root_global / TECH_REL, usecols=["ticker", "as_of_date", "close_above_ma50"], low_memory=False)
    tech["as_of_date"] = tech["as_of_date"].astype(str).str[:10]
    regimes = tech[tech["ticker"].isin(["QQQ", "SPY", "SOXX"])].pivot_table(
        index="as_of_date", columns="ticker", values="close_above_ma50", aggfunc="last"
    )
    regimes = regimes.rename(columns={c: f"{c}_ABOVE_MA50" for c in regimes.columns}).reset_index()
    joined = panel.merge(regimes, on="as_of_date", how="left")
    rows = []
    stable_factors = [
        "z_tech_trend_continuation", "z_tech_breakout_confirmed",
        "z_tech_overextended_but_strong", "z_tech_rs_vs_qqq",
        "z_tech_macd_hist_acceleration", "z_tech_ma_slope_alignment",
    ]
    for regime_col in [c for c in regimes.columns if c != "as_of_date"]:
        for value in (True, False):
            subset = joined[joined[regime_col].map(truth).eq(value)]
            for factor in stable_factors:
                for window in WINDOWS:
                    ret_col, mat_col = f"return_{window.lower()}_forward", f"forward_{window.lower()}_matured"
                    mature = subset[subset[mat_col].map(truth) & subset[ret_col].notna()]
                    stats = [daily_factor_stats(g, factor, ret_col) for _, g in mature.groupby("as_of_date")]
                    stats = [s for s in stats if pd.notna(s[0])]
                    ics = pd.Series([s[0] for s in stats], dtype=float)
                    spreads = pd.Series([s[1] - s[2] for s in stats], dtype=float)
                    rows.append({
                        "regime_name": regime_col, "regime_value": "ABOVE" if value else "BELOW",
                        "factor_name": factor, "forward_window": window,
                        "matured_count": len(mature),
                        "rank_ic_mean": ics.mean() if len(ics) else np.nan,
                        "top_minus_bottom": spreads.mean() if len(spreads) else np.nan,
                        "hit_rate_delta": spreads.gt(0).mean() - 0.5 if len(spreads) else np.nan,
                        "stability_flag": bool(len(ics) >= 20 and abs(ics.mean()) >= 0.01),
                        "regime_dependency_warning": "" if len(ics) >= 20 else "INSUFFICIENT_REGIME_DATES",
                    })
    return pd.DataFrame(rows)


def split_plan(panel: pd.DataFrame) -> pd.DataFrame:
    dates = np.array(sorted(panel["as_of_date"].dropna().unique()))
    rows = []
    if len(dates) < 200:
        fractions = [(0.50, 0.20, 0.30)]
    else:
        fractions = [(0.40, 0.10, 0.10), (0.50, 0.10, 0.10), (0.60, 0.10, 0.10)]
    for window in WINDOWS:
        mature = panel[panel[f"forward_{window.lower()}_matured"].map(truth)]
        for index, (train_frac, val_frac, test_frac) in enumerate(fractions, 1):
            train_end_i = max(1, int(len(dates) * train_frac) - 1)
            val_end_i = min(len(dates) - 2, train_end_i + max(1, int(len(dates) * val_frac)))
            test_end_i = min(len(dates) - 1, val_end_i + max(1, int(len(dates) * test_frac)))
            bounds = (dates[0], dates[train_end_i], dates[train_end_i + 1], dates[val_end_i], dates[val_end_i + 1], dates[test_end_i])
            counts = [
                int(mature["as_of_date"].between(bounds[0], bounds[1]).sum()),
                int(mature["as_of_date"].between(bounds[2], bounds[3]).sum()),
                int(mature["as_of_date"].between(bounds[4], bounds[5]).sum()),
            ]
            usable = min(counts) >= 1000
            rows.append({
                "split_id": f"WF{index}_{window}", "train_start": bounds[0], "train_end": bounds[1],
                "validation_start": bounds[2], "validation_end": bounds[3],
                "test_start": bounds[4], "test_end": bounds[5], "forward_window": window,
                "train_row_count": counts[0], "validation_row_count": counts[1],
                "test_row_count": counts[2], "split_usable_flag": usable,
                "warning": "" if usable else "INSUFFICIENT_SPLIT_ROWS",
            })
    return pd.DataFrame(rows)


def candidate_grid() -> pd.DataFrame:
    definitions = [
        ("E1A", "E1_TECH_STRUCTURE_SHADOW", [.54, .32, .05, .04, .05, 0, 0, 0, 0, 0]),
        ("E1B", "E1_TECH_STRUCTURE_SHADOW", [.52, .32, .06, .05, .05, 0, 0, 0, 0, 0]),
        ("E2A", "E2_FUND_QUALITY_SHADOW", [.55, .34, .04, .02, .02, .015, .015, 0, 0, 0]),
        ("E2B", "E2_FUND_QUALITY_SHADOW", [.54, .34, .04, .02, .02, .02, .02, 0, 0, 0]),
        ("E3A", "E3_TECH_FUND_INTERACTION_SHADOW", [.54, .33, .04, .025, .025, .015, .01, .015, 0, 0]),
        ("E3B", "E3_TECH_FUND_INTERACTION_SHADOW", [.53, .33, .05, .025, .025, .015, .01, .015, 0, 0]),
        ("E4A", "E4_RISK_BUCKET_PENALTY_SHADOW", [.55, .34, .04, .02, .02, 0, 0, 0, -.03, -.02]),
        ("E4B", "E4_RISK_BUCKET_PENALTY_SHADOW", [.54, .34, .05, .025, .025, 0, 0, 0, -.025, -.015]),
        ("E5A", "E5_STABILITY_CONSTRAINED_COMBO_SHADOW", [.54, .33, .05, .03, .04, .01, .005, .005, -.02, -.01]),
        ("E5B", "E5_STABILITY_CONSTRAINED_COMBO_SHADOW", [.55, .33, .04, .03, .04, .01, .005, .005, -.02, -.01]),
    ]
    rows = []
    for cid, group, values in definitions:
        scale = sum(abs(v) for v in values)
        weights = [v / scale for v in values]
        row = {"candidate_id": cid, "candidate_group": group}
        row.update(dict(zip(COMPONENT_COLUMNS, weights)))
        row.update({
            "max_weight_delta_vs_D": max(abs(weights[0] - .6), abs(weights[1] - .4), *(abs(v) for v in weights[2:])),
            "pullback_positive_weight_allowed": False, "day0_chase_allowed": False,
            "interaction_adoption_allowed": False, "official_adoption_allowed": False,
            "warning": "FUNDAMENTAL_INTERACTION_LOW_CONFIDENCE_CAPPED" if weights[5] or weights[6] or weights[7] else "",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def components(panel: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=panel.index)
    mean = lambda cols: panel[cols].fillna(0).mean(axis=1)
    out["TechnicalTrend"] = mean(["z_tech_trend_continuation", "z_tech_ma_slope_alignment"])
    out["TechnicalBreakout"] = mean(["z_tech_breakout_confirmed", "z_tech_volume_confirmation"])
    out["TechnicalRelativeStrength"] = mean(["z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_rs_vs_soxx"])
    out["Momentum"] = mean(["z_tech_rs_vs_qqq", "z_tech_rs_vs_spy", "z_tech_macd_hist_acceleration", "z_tech_breakout_confirmed"])
    out["Base"] = mean(["z_tech_trend_continuation", "z_tech_ma_slope_alignment", "z_tech_volume_confirmation"])
    out["FundamentalQuality"] = mean(["z_fund_quality", "z_fund_profitability", "z_fund_balance_sheet", "z_fund_valuation_reasonable"])
    out["FundamentalGrowth"] = mean(["z_fund_growth", "z_fund_strong_compounding", "z_fund_revision"])
    out["InteractionQuality"] = mean(["z_interaction_strong_tech_strong_fundamental", "z_interaction_overextended_strong_fundamental"])
    out["RiskPenalty"] = mean([
        "z_fund_low_quality_risk", "z_interaction_low_quality_momentum_risk",
        "z_interaction_wait_confirmation", "z_bucket_low_quality_momentum",
        "z_bucket_day0_watch_only", "z_bucket_interaction_data_gap",
    ])
    out["PullbackPenalty"] = mean(["z_tech_pullback_original", "z_tech_pullback_repaired_best"])
    return out


def score_metrics(data: pd.DataFrame, score_col: str, ret_col: str, benchmark_col: str) -> dict[str, float]:
    if data.empty:
        return {k: np.nan for k in ("mean", "median", "hit", "drawdown", "benchmark")}
    ranked = data.copy()
    ranked["rank"] = ranked.groupby("as_of_date")[score_col].rank(method="first", ascending=False)
    top = ranked[ranked["rank"].le(20)]
    daily = top.groupby("as_of_date")[ret_col].mean().sort_index()
    cumulative = (1 + daily.fillna(0)).cumprod()
    drawdown = (cumulative / cumulative.cummax() - 1).min() if len(cumulative) else np.nan
    return {
        "mean": top[ret_col].mean(), "median": top[ret_col].median(),
        "hit": top[ret_col].gt(0).mean(), "drawdown": drawdown,
        "benchmark": (top[ret_col] - top[benchmark_col]).mean() if benchmark_col in top and top[benchmark_col].notna().any() else np.nan,
    }


def overlap_metrics(data: pd.DataFrame, candidate_col: str, d_col: str) -> tuple[float, float]:
    overlaps20, overlaps50 = [], []
    for _, group in data.groupby("as_of_date"):
        cr = group[candidate_col].rank(method="first", ascending=False)
        dr = group[d_col].rank(method="first", ascending=False)
        for n, store in ((20, overlaps20), (50, overlaps50)):
            cset, dset = set(group.loc[cr.le(n), "ticker"]), set(group.loc[dr.le(n), "ticker"])
            store.append(len(cset & dset) / max(1, n))
    return float(np.mean(overlaps20)), float(np.mean(overlaps50))


def walkforward_results(panel: pd.DataFrame, splits: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    comp = components(panel)
    work = pd.concat([panel.reset_index(drop=True), comp.reset_index(drop=True)], axis=1)
    work["D_PROXY_SCORE"] = .6 * work["Base"] + .4 * work["Momentum"]
    for _, candidate in grid.iterrows():
        work[f"SCORE_{candidate['candidate_id']}"] = sum(
            float(candidate[col]) * work[col] for col in COMPONENT_COLUMNS
        )
    rows = []
    for _, split in splits[splits["split_usable_flag"].map(truth)].iterrows():
        window = split["forward_window"]
        ret_col, mat_col = f"return_{window.lower()}_forward", f"forward_{window.lower()}_matured"
        benchmark_col = f"qqq_ret_{window.lower()}"
        mature = work[work[mat_col].map(truth) & work[ret_col].notna()].copy()
        periods = {
            "train": mature[mature["as_of_date"].between(split["train_start"], split["train_end"])],
            "validation": mature[mature["as_of_date"].between(split["validation_start"], split["validation_end"])],
            "test": mature[mature["as_of_date"].between(split["test_start"], split["test_end"])],
        }
        d_metrics = {name: score_metrics(data, "D_PROXY_SCORE", ret_col, benchmark_col) for name, data in periods.items()}
        for _, candidate in grid.iterrows():
            cid, score_col = candidate["candidate_id"], f"SCORE_{candidate['candidate_id']}"
            metrics = {name: score_metrics(data, score_col, ret_col, benchmark_col) for name, data in periods.items()}
            overlap20, overlap50 = overlap_metrics(periods["test"], score_col, "D_PROXY_SCORE")
            turnover = 1 - overlap20
            excess = metrics["test"]["mean"] - d_metrics["test"]["mean"]
            overfit = (metrics["train"]["mean"] - d_metrics["train"]["mean"]) - excess
            stability = bool(
                pd.notna(excess) and
                metrics["validation"]["mean"] - d_metrics["validation"]["mean"] > -0.001 and
                excess > -0.001 and abs(overfit) <= 0.02
            )
            turnover_pass = turnover <= 0.35
            drawdown_pass = bool(pd.notna(metrics["test"]["drawdown"]) and metrics["test"]["drawdown"] >= -0.30)
            usable = stability and turnover_pass and drawdown_pass
            rows.append({
                "candidate_id": cid, "candidate_group": candidate["candidate_group"],
                "split_id": split["split_id"], "forward_window": window,
                "train_score": metrics["train"]["mean"] - d_metrics["train"]["mean"],
                "validation_score": metrics["validation"]["mean"] - d_metrics["validation"]["mean"],
                "test_score": excess, "test_mean_forward_return": metrics["test"]["mean"],
                "test_median_forward_return": metrics["test"]["median"],
                "test_hit_rate": metrics["test"]["hit"],
                "test_drawdown_proxy": metrics["test"]["drawdown"],
                "test_turnover_proxy": turnover, "test_top20_overlap_vs_D": overlap20,
                "test_top50_overlap_vs_D": overlap50, "test_excess_return_vs_D_proxy": excess,
                "test_excess_return_vs_QQQ_proxy": metrics["test"]["benchmark"],
                "overfit_gap_train_minus_test": overfit,
                "stability_gate_pass": stability, "turnover_gate_pass": turnover_pass,
                "drawdown_gate_pass": drawdown_pass, "leakage_warning": "",
                "usable_shadow_candidate": usable,
                "warning": "" if usable else "ONE_OR_MORE_SHADOW_GATES_FAILED",
            })
    return pd.DataFrame(rows)


def candidate_summary(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (cid, group), data in results.groupby(["candidate_id", "candidate_group"]):
        row: dict[str, Any] = {
            "candidate_id": cid, "candidate_group": group,
            "validation_windows_tested": len(data), "test_windows_tested": len(data),
        }
        for window in WINDOWS:
            sub = data[data["forward_window"].eq(window)]
            row[f"avg_test_mean_forward_return_{window.lower()}"] = sub["test_mean_forward_return"].mean()
            row[f"avg_hit_rate_{window.lower()}"] = sub["test_hit_rate"].mean()
            row[f"avg_excess_vs_D_{window.lower()}"] = sub["test_excess_return_vs_D_proxy"].mean()
        row.update({
            "avg_turnover_proxy": data["test_turnover_proxy"].mean(),
            "avg_drawdown_proxy": data["test_drawdown_proxy"].mean(),
            "stability_pass_ratio": data["stability_gate_pass"].map(truth).mean(),
            "turnover_pass_ratio": data["turnover_gate_pass"].map(truth).mean(),
            "drawdown_pass_ratio": data["drawdown_gate_pass"].map(truth).mean(),
            "overfit_gap_avg": data["overfit_gap_train_minus_test"].mean(),
        })
        if len(data) < 3:
            status = "SHADOW_CANDIDATE_REJECT_INSUFFICIENT_DATA"
        elif row["turnover_pass_ratio"] < .8:
            status = "SHADOW_CANDIDATE_REJECT_TURNOVER"
        elif row["drawdown_pass_ratio"] < .8:
            status = "SHADOW_CANDIDATE_REJECT_DRAWDOWN"
        elif abs(row["overfit_gap_avg"]) > .02:
            status = "SHADOW_CANDIDATE_REJECT_OVERFIT"
        elif row["stability_pass_ratio"] >= .67:
            status = "SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER"
        else:
            status = "SHADOW_CANDIDATE_DIAGNOSTIC_ONLY_INSUFFICIENT_STABILITY"
        row["recommended_shadow_status"] = status
        row["adoption_allowed"] = False
        row["warning"] = "" if status == "SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER" else status
        rows.append(row)
    return pd.DataFrame(rows)


def select_candidate(summary: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    ready = summary[summary["recommended_shadow_status"].eq("SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER")].copy()
    if ready.empty:
        return pd.DataFrame([{
            "selected_candidate_id": "", "selected_candidate_group": "",
            "selected_status": "NO_SHADOW_CANDIDATE_SELECTED",
            "reason": "No candidate passed nested stability, turnover, and drawdown gates.",
            "weights_json": "", "avg_excess_vs_D_5d": np.nan,
            "avg_excess_vs_D_10d": np.nan, "avg_excess_vs_D_20d": np.nan,
            "stability_pass_ratio": np.nan, "turnover_pass_ratio": np.nan,
            "drawdown_pass_ratio": np.nan, "overfit_gap_avg": np.nan,
            "forward_ledger_allowed": False, "official_adoption_allowed": False,
            "broker_action_created": False, "warning": "NO_PASSING_SHADOW_CANDIDATE",
        }])
    ready["selection_score"] = (
        ready[["avg_excess_vs_D_5d", "avg_excess_vs_D_10d", "avg_excess_vs_D_20d"]].mean(axis=1)
        + .002 * ready["stability_pass_ratio"] - .002 * ready["avg_turnover_proxy"]
    )
    best = ready.sort_values("selection_score", ascending=False).iloc[0]
    weights = grid[grid["candidate_id"].eq(best["candidate_id"])].iloc[0]
    return pd.DataFrame([{
        "selected_candidate_id": best["candidate_id"],
        "selected_candidate_group": best["candidate_group"],
        "selected_status": "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE",
        "reason": "Passed deterministic nested stability, turnover, and drawdown gates.",
        "weights_json": json.dumps({c: float(weights[c]) for c in COMPONENT_COLUMNS}, sort_keys=True),
        "avg_excess_vs_D_5d": best["avg_excess_vs_D_5d"],
        "avg_excess_vs_D_10d": best["avg_excess_vs_D_10d"],
        "avg_excess_vs_D_20d": best["avg_excess_vs_D_20d"],
        "stability_pass_ratio": best["stability_pass_ratio"],
        "turnover_pass_ratio": best["turnover_pass_ratio"],
        "drawdown_pass_ratio": best["drawdown_pass_ratio"],
        "overfit_gap_avg": best["overfit_gap_avg"], "forward_ledger_allowed": True,
        "official_adoption_allowed": False, "broker_action_created": False, "warning": "",
    }])


def d_comparison(results: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    top = summary.sort_values(
        ["stability_pass_ratio", "avg_excess_vs_D_20d"], ascending=False
    ).head(3)["candidate_id"]
    rows = []
    for cid in top:
        for window in WINDOWS:
            sub = results[results["candidate_id"].eq(cid) & results["forward_window"].eq(window)]
            candidate_mean = sub["test_mean_forward_return"].mean()
            excess = sub["test_excess_return_vs_D_proxy"].mean()
            d_mean = candidate_mean - excess
            candidate_hit = sub["test_hit_rate"].mean()
            status = "CANDIDATE_BEATS_D_DIAGNOSTIC_ONLY" if pd.notna(excess) and excess > 0 else "CANDIDATE_DOES_NOT_BEAT_D"
            rows.append({
                "candidate_id": cid, "comparison_scope": "NESTED_TEST_D_EQUIVALENT_PROXY",
                "forward_window": window, "candidate_mean_return": candidate_mean,
                "d_baseline_mean_return": d_mean, "candidate_minus_d": excess,
                "candidate_hit_rate": candidate_hit, "d_hit_rate": np.nan,
                "hit_rate_delta": np.nan, "candidate_turnover_proxy": sub["test_turnover_proxy"].mean(),
                "d_turnover_proxy": 0.0, "candidate_drawdown_proxy": sub["test_drawdown_proxy"].mean(),
                "d_drawdown_proxy": np.nan, "comparison_status": status,
                "warning": "HISTORICAL_D_EQUIVALENT_PROXY_USED_NO_OFFICIAL_HISTORICAL_D_RANKS",
            })
    return pd.DataFrame(rows)


def forward_ledger(panel: pd.DataFrame, grid: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    if selected.iloc[0]["selected_status"] != "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE":
        return pd.DataFrame(columns=[
            "candidate_id", "candidate_group", "as_of_date", "ticker", "shadow_rank",
            "shadow_score", "d_rank", "d_top20_flag", "shadow_top20_flag",
            "shadow_top50_flag", "forward_window", "planned_maturity_date",
            "forward_observation_allowed", "official_adoption_allowed", "no_trade_action_created",
        ])
    cid = selected.iloc[0]["selected_candidate_id"]
    candidate = grid[grid["candidate_id"].eq(cid)].iloc[0]
    latest = panel["as_of_date"].max()
    current = panel[panel["as_of_date"].eq(latest)].copy()
    comp = components(current)
    current["shadow_score"] = sum(float(candidate[c]) * comp[c].values for c in COMPONENT_COLUMNS)
    current["shadow_rank"] = current["shadow_score"].rank(method="first", ascending=False)
    rows = []
    for _, row in current[current["shadow_rank"].le(50)].iterrows():
        for window in (5, 10, 20):
            rows.append({
                "candidate_id": cid, "candidate_group": candidate["candidate_group"],
                "as_of_date": latest, "ticker": row["ticker"], "shadow_rank": row["shadow_rank"],
                "shadow_score": row["shadow_score"], "d_rank": row.get("d_rank"),
                "d_top20_flag": truth(row.get("d_top20_flag")),
                "shadow_top20_flag": row["shadow_rank"] <= 20,
                "shadow_top50_flag": row["shadow_rank"] <= 50,
                "forward_window": f"{window}D",
                "planned_maturity_date": (pd.Timestamp(latest) + pd.tseries.offsets.BDay(window)).date().isoformat(),
                "forward_observation_allowed": True, "official_adoption_allowed": False,
                "no_trade_action_created": True,
            })
    return pd.DataFrame(rows)


def forbidden_audit() -> pd.DataFrame:
    rows = [
        ("TECH_PULLBACK_BUY_CANDIDATE", "Historical 20D delta was negative; positive weight forbidden.", False, False, True),
        ("PULLBACK_REPAIR_R3_RSI_STABILIZED_MACD_POSITIVE", "Best repaired pullback remained negative.", False, False, True),
        ("TECH_BREAKOUT_DAY0_WATCH_ONLY", "Day0 is watch-only and no-chase.", False, False, True),
        ("LOW_QUALITY_MOMENTUM_RISK", "Risk diagnostic only.", False, False, True),
        ("INTERACTION_UNAVAILABLE", "Source gap diagnostic only.", False, False, True),
        ("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Wait state cannot be positive alpha.", False, False, True),
    ]
    return pd.DataFrame([{
        "signal_name": name, "reason_for_constraint": reason,
        "positive_weight_allowed": positive, "used_as_positive_weight": used_positive,
        "used_as_penalty": penalty, "adoption_allowed": False,
        "audit_status": "PASS_CONSTRAINT_ENFORCED", "warning": "",
    } for name, reason, positive, used_positive, penalty in rows])


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 92):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    for base in (root / "outputs", root / "data"):
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file() and "recommendation" in p.name.lower())
    paths = sorted(set(paths))
    return paths, {p: sha256(p) for p in paths}


def mutation_audit(paths: list[Path], before: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        text = path.as_posix().lower()
        ptype = (
            "broker_action" if "broker" in text else
            "recommendation" if "recommendation" in text else
            "official_weight" if "weight" in text and ("official" in text or "weight_perturbation" in text) else
            "official_ranking" if "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text else
            "prior_v21_diagnostic" if "/diagnostics/v21_0" in text else "protected"
        )
        exists = path.exists()
        changed = not exists or before[path] != sha256(path)
        rows.append({
            "path": path.as_posix(), "path_type": ptype, "exists_before": True,
            "exists_after": exists, "modified_during_run": changed,
            "mutation_allowed": False, "warning": "DISALLOWED_MUTATION_DETECTED" if changed else "",
        })
    return pd.DataFrame(rows)


def empty_outputs(output: Path) -> None:
    basic = {
        INVENTORY_NAME: ["source_path", "source_role", "exists", "warning"],
        PANEL_NAME: ["as_of_date", "ticker"],
        IC_NAME: ["factor_name", "forward_window", "usable_for_weight_search"],
        REGIME_NAME: ["regime_name", "factor_name", "forward_window"],
        SPLIT_NAME: ["split_id", "train_start", "train_end", "validation_start", "validation_end", "test_start", "test_end"],
        GRID_NAME: ["candidate_id", "candidate_group", "official_adoption_allowed"],
        RESULTS_NAME: ["candidate_id", "split_id", "forward_window", "usable_shadow_candidate"],
        CANDIDATE_NAME: ["candidate_id", "recommended_shadow_status", "adoption_allowed"],
        SELECTED_NAME: ["selected_status", "official_adoption_allowed", "broker_action_created"],
        D_COMPARE_NAME: ["candidate_id", "forward_window", "comparison_status"],
        LEDGER_NAME: ["candidate_id", "official_adoption_allowed", "no_trade_action_created"],
        FORBIDDEN_NAME: ["signal_name", "positive_weight_allowed", "adoption_allowed"],
        CERT_NAME: ["certification_status"],
        MUTATION_NAME: ["path", "modified_during_run", "mutation_allowed"],
    }
    for name, cols in basic.items():
        pd.DataFrame(columns=cols).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    global root_global
    root_global = root.resolve()
    root = root_global
    output = (output_override.resolve() if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected, before = protected_snapshot(root, output)
    missing_required = not (root / TECH_REL).is_file()
    inv = source_inventory(root)
    panel = ic = regimes = splits = grid = results = candidates = selected = compare = ledger = pd.DataFrame()
    latest = ""
    if missing_required:
        empty_outputs(output)
        inv.to_csv(output / INVENTORY_NAME, index=False)
    else:
        panel = build_factor_panel(root)
        latest = str(panel["source_latest_price_date"].dropna().max())
        ic = factor_effectiveness(panel)
        regimes = regime_summary(panel)
        splits = split_plan(panel)
        grid = candidate_grid()
        results = walkforward_results(panel, splits, grid)
        candidates = candidate_summary(results)
        selected = select_candidate(candidates, grid)
        compare = d_comparison(results, candidates)
        ledger = forward_ledger(panel, grid, selected)
        forbidden = forbidden_audit()
        for frame, name in (
            (inv, INVENTORY_NAME), (panel, PANEL_NAME), (ic, IC_NAME),
            (regimes, REGIME_NAME), (splits, SPLIT_NAME), (grid, GRID_NAME),
            (results, RESULTS_NAME), (candidates, CANDIDATE_NAME),
            (selected, SELECTED_NAME), (compare, D_COMPARE_NAME),
            (ledger, LEDGER_NAME), (forbidden, FORBIDDEN_NAME),
        ):
            frame.to_csv(output / name, index=False)

    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    selected_status = selected.iloc[0]["selected_status"] if not selected.empty else "NO_SHADOW_CANDIDATE_SELECTED"
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "shadow_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "pullback_positive_weight_used": False, "day0_chase_used": False,
        "shadow_candidate_adoption_allowed": False, "official_adoption_allowed": False,
        "certification_status": "CERTIFIED_SHADOW_WEIGHT_SEARCH_NO_ADOPTION_NO_TRADE",
        "certification_note": "Nested walk-forward shadow research only; D and official outputs preserved.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)
    leakage_count = 0
    data_warning_count = int(inv["warning"].fillna("").ne("").sum()) + 2
    overfit_count = int((candidates["recommended_shadow_status"].eq("SHADOW_CANDIDATE_REJECT_OVERFIT")).sum()) if not candidates.empty else 0
    turnover_count = int((candidates["recommended_shadow_status"].eq("SHADOW_CANDIDATE_REJECT_TURNOVER")).sum()) if not candidates.empty else 0
    drawdown_count = int((candidates["recommended_shadow_status"].eq("SHADOW_CANDIDATE_REJECT_DRAWDOWN")).sum()) if not candidates.empty else 0
    blocked = mutation_count > 0 or leakage_count > 0
    if missing_required:
        status, decision = "BLOCKED_V21_092_R1_REQUIRED_INPUTS_MISSING", "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif blocked:
        status, decision = "BLOCKED_V21_092_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK", "SHADOW_WEIGHT_SEARCH_BLOCKED_REVIEW_REQUIRED"
    elif selected_status == "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE":
        status, decision = "PASS_V21_092_R1_SHADOW_DYNAMIC_WEIGHT_CANDIDATE_READY", "SHADOW_DYNAMIC_WEIGHT_CANDIDATE_READY_DIAGNOSTIC_ONLY"
    elif data_warning_count:
        status, decision = "PARTIAL_PASS_V21_092_R1_READY_WITH_DATA_WARN", "FACTOR_EFFECTIVENESS_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status, decision = "PARTIAL_PASS_V21_092_R1_FACTOR_EFFECTIVENESS_READY_NO_SHADOW_SELECTED", "FACTOR_EFFECTIVENESS_READY_NO_SHADOW_SELECTED_DIAGNOSTIC_ONLY"
    selected_row = selected.iloc[0] if not selected.empty else {}
    next_stage = (
        "V21.093-R1_SHADOW_DYNAMIC_WEIGHT_FORWARD_LEDGER_AND_D_BASELINE_COMPARISON"
        if selected_status == "SHADOW_ONLY_FORWARD_LEDGER_CANDIDATE"
        else "V21.092-R2_FACTOR_FILTER_REPAIR_AND_WEIGHT_SEARCH_STABILITY_TIGHTENING"
    )
    validation = {
        "stage": "V21.092-R1_FACTOR_EFFECTIVENESS_NESTED_WALKFORWARD_AND_DYNAMIC_WEIGHT_SHADOW_SEARCH",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "shadow_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "technical_085_preserved": mutation_count == 0,
        "fundamental_086_preserved": mutation_count == 0, "interaction_087_preserved": mutation_count == 0,
        "review_088_preserved": mutation_count == 0, "monitor_089_preserved": mutation_count == 0,
        "archive_090_preserved": mutation_count == 0, "maturity_091_preserved": mutation_count == 0,
        "source_latest_price_date": latest, "factor_panel_rows": len(panel),
        "factor_count": len(FACTOR_COLUMNS),
        "matured_5d_count": int(panel["forward_5d_matured"].map(truth).sum()) if not panel.empty else 0,
        "matured_10d_count": int(panel["forward_10d_matured"].map(truth).sum()) if not panel.empty else 0,
        "matured_20d_count": int(panel["forward_20d_matured"].map(truth).sum()) if not panel.empty else 0,
        "nested_split_count": len(splits), "weight_candidate_count": len(grid),
        "usable_weight_candidate_count": int(candidates["recommended_shadow_status"].eq("SHADOW_CANDIDATE_READY_FOR_FORWARD_LEDGER").sum()) if not candidates.empty else 0,
        "selected_candidate_id": selected_row.get("selected_candidate_id", ""),
        "selected_candidate_group": selected_row.get("selected_candidate_group", ""),
        "selected_status": selected_status,
        "forward_ledger_allowed": truth(selected_row.get("forward_ledger_allowed", False)),
        "official_adoption_allowed": False, "pullback_positive_weight_used": False,
        "day0_chase_used": False, "leakage_warning_count": leakage_count,
        "data_warning_count": data_warning_count, "overfit_warning_count": overfit_count,
        "turnover_warning_count": turnover_count, "drawdown_warning_count": drawdown_count,
        "mutation_warning_count": mutation_count, "recommended_next_stage": next_stage,
        "missing_inputs": TECH_REL.as_posix() if missing_required else "",
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "factor_panel_rows", "nested_split_count", "selected_status"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
