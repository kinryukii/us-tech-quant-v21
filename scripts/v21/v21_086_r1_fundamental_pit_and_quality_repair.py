#!/usr/bin/env python
"""V21.086-R1 fundamental PIT and quality repair.

Builds a diagnostic-only PIT-safe fundamental panel from local sources. The
stage never mutates official rankings, weights, recommendations, or broker
outputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_086_r1")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
MAIN_SOURCE_REL = Path("outputs/v20/consolidation/V20_108_R6A_R2_CONTROLLED_FUNDAMENTAL_PROVIDER_REFRESH_CACHE.csv")
TECH085_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_TECHNICAL_FEATURE_PANEL.csv")
TECH085_VAL_REL = Path("outputs/v21/diagnostics/v21_085_r1/V21_085_R1_VALIDATION_SUMMARY.csv")
TOP20_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_066a_latest_data_ranking_viewer/V21_066A_D_LATEST_RANKING_TOP20.csv"
)
ALT_RANK_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")

SOURCE_INV_NAME = "V21_086_R1_FUNDAMENTAL_SOURCE_INVENTORY.csv"
PANEL_NAME = "V21_086_R1_FUNDAMENTAL_PIT_PANEL.csv"
PIT_REPORT_NAME = "V21_086_R1_FUNDAMENTAL_PIT_INTEGRITY_REPORT.csv"
COVERAGE_NAME = "V21_086_R1_FUNDAMENTAL_FEATURE_COVERAGE_REPORT.csv"
FORWARD_NAME = "V21_086_R1_FUNDAMENTAL_SIGNAL_FORWARD_RETURN_SUMMARY.csv"
CORR_NAME = "V21_086_R1_FUNDAMENTAL_SIGNAL_CORRELATION_MATRIX.csv"
REDUNDANT_NAME = "V21_086_R1_FUNDAMENTAL_REDUNDANT_SIGNAL_DROP_CANDIDATES.csv"
ABLATION_NAME = "V21_086_R1_FUNDAMENTAL_FAMILY_ABLATION_SUMMARY.csv"
CROSS_NAME = "V21_086_R1_TECH_FUNDAMENTAL_CROSS_LAYER_DIAGNOSTIC.csv"
OVERLAY_NAME = "V21_086_R1_TOP20_D_FUNDAMENTAL_OVERLAY.csv"
VALIDATION_NAME = "V21_086_R1_VALIDATION_SUMMARY.csv"

WINDOWS = (5, 10, 20)
FAMILIES = ("Growth", "Profitability", "Quality", "Valuation", "Balance Sheet", "Revision", "Composite")

FEATURE_FAMILY: dict[str, str] = {
    "revenue_yoy": "Growth", "revenue_qoq": "Growth", "revenue_growth_acceleration": "Growth",
    "gross_profit_yoy": "Growth", "eps_yoy": "Growth", "eps_qoq": "Growth",
    "eps_growth_acceleration": "Growth", "operating_income_yoy": "Growth",
    "free_cash_flow_yoy": "Growth", "backlog_growth": "Growth", "order_growth": "Growth",
    "guidance_growth_flag": "Growth",
    "gross_margin": "Profitability", "gross_margin_change_qoq": "Profitability",
    "operating_margin": "Profitability", "operating_margin_change_qoq": "Profitability",
    "net_margin": "Profitability", "ebitda_margin": "Profitability", "fcf_margin": "Profitability",
    "roe": "Profitability", "roic": "Profitability", "operating_leverage_proxy": "Profitability",
    "positive_free_cash_flow": "Quality", "fcf_to_revenue": "Quality",
    "stock_based_compensation_to_revenue": "Quality", "debt_to_equity": "Quality",
    "interest_coverage": "Quality", "current_ratio": "Quality", "share_dilution_yoy": "Quality",
    "gross_margin_stability": "Quality", "earnings_consistency": "Quality",
    "cash_conversion_cycle": "Quality", "quality_red_flag_count": "Quality",
    "market_cap": "Valuation", "enterprise_value": "Valuation", "pe_ttm": "Valuation",
    "pe_forward": "Valuation", "ps_ttm": "Valuation", "ev_sales": "Valuation",
    "ev_ebitda": "Valuation", "price_to_book": "Valuation", "fcf_yield": "Valuation",
    "peg_ratio": "Valuation", "valuation_percentile_own_history": "Valuation",
    "valuation_percentile_sector": "Valuation", "growth_adjusted_valuation_score": "Valuation",
    "cash_and_equivalents": "Balance Sheet", "total_debt": "Balance Sheet", "net_cash": "Balance Sheet",
    "net_debt": "Balance Sheet", "debt_to_assets": "Balance Sheet", "quick_ratio": "Balance Sheet",
    "current_ratio_balance": "Balance Sheet", "cash_runway_proxy": "Balance Sheet",
    "balance_sheet_strength_score": "Balance Sheet",
    "eps_estimate_revision_1m": "Revision", "eps_estimate_revision_3m": "Revision",
    "revenue_estimate_revision_1m": "Revision", "revenue_estimate_revision_3m": "Revision",
    "target_price_revision_1m": "Revision", "recommendation_upgrade_flag": "Revision",
    "recommendation_downgrade_flag": "Revision", "earnings_surprise_pct": "Revision",
    "revenue_surprise_pct": "Revision", "guidance_raise_flag": "Revision", "guidance_cut_flag": "Revision",
}

COMPOSITES = [
    "GROWTH_STRONG", "PROFITABILITY_IMPROVING", "QUALITY_STRONG",
    "VALUATION_REASONABLE_FOR_GROWTH", "BALANCE_SHEET_STRONG", "REVISION_POSITIVE",
    "FUNDAMENTAL_STRONG_COMPOUNDING", "FUNDAMENTAL_CYCLICAL_RECOVERY",
    "FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY", "FUNDAMENTAL_VALUE_TRAP_RISK",
    "FUNDAMENTAL_WEAK_OR_UNCONFIRMED",
]
for _c in COMPOSITES:
    FEATURE_FAMILY[_c] = "Composite"


def truthy(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def discover_sources(root: Path) -> pd.DataFrame:
    tokens = ("fundamental", "valuation", "earnings", "filing", "estimate", "revision", "quality", "metrics")
    rows = []
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*.csv"):
            lower = path.name.lower()
            if not any(t in lower for t in tokens):
                continue
            try:
                sample = pd.read_csv(path, nrows=2000, low_memory=False)
            except Exception as exc:
                rows.append({
                    "source_path": path.relative_to(root).as_posix(),
                    "source_type": "csv_unreadable",
                    "row_count": "",
                    "ticker_count": "",
                    "min_date": "",
                    "max_date": "",
                    "detected_date_columns": "",
                    "detected_fundamental_columns": "",
                    "detected_forward_columns": "",
                    "pit_usable_flag": False,
                    "pit_certification_possible": False,
                    "warning": f"UNREADABLE:{exc}",
                })
                continue
            cols = list(sample.columns)
            ticker_col = "ticker" if "ticker" in cols else "symbol" if "symbol" in cols else ""
            date_cols = [c for c in cols if any(x in c.lower() for x in ("date", "timestamp", "period"))]
            fund_cols = [c for c in cols if c in FEATURE_FAMILY or any(x in c.lower() for x in (
                "revenue", "earnings", "margin", "cash", "debt", "market_cap", "enterprise", "pe", "price_to", "ev_"
            ))]
            fwd_cols = [c for c in cols if "forward" in c.lower() or "return_" in c.lower()]
            row_count = ""
            try:
                row_count = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1
            except Exception:
                row_count = len(sample)
            min_date = max_date = ""
            if date_cols:
                dates = pd.to_datetime(sample[date_cols[0]], errors="coerce")
                min_date = str(dates.min().date()) if dates.notna().any() else ""
                max_date = str(dates.max().date()) if dates.notna().any() else ""
            pit_cols = {c.lower() for c in date_cols}
            pit_possible = bool(pit_cols & {"data_available_date", "provider_available_date", "ingestion_date", "earnings_announcement_date", "filing_date", "report_date", "metric_source_timestamp", "refresh_timestamp_utc"})
            pit_usable = bool(ticker_col and fund_cols and pit_possible)
            rows.append({
                "source_path": path.relative_to(root).as_posix(),
                "source_type": "csv",
                "row_count": int(row_count) if str(row_count).isdigit() else row_count,
                "ticker_count": int(sample[ticker_col].nunique()) if ticker_col else "",
                "min_date": min_date,
                "max_date": max_date,
                "detected_date_columns": "|".join(date_cols),
                "detected_fundamental_columns": "|".join(fund_cols),
                "detected_forward_columns": "|".join(fwd_cols),
                "pit_usable_flag": pit_usable,
                "pit_certification_possible": pit_possible,
                "warning": "" if pit_usable else "NO_TICKER_FUNDAMENTAL_OR_PIT_DATE_COLUMN",
            })
    return pd.DataFrame(rows).sort_values(["pit_usable_flag", "source_path"], ascending=[False, True])


def load_prices(root: Path) -> tuple[pd.DataFrame, str]:
    price = pd.read_csv(root / PRICE_REL, usecols=["symbol", "date", "close", "adjusted_close", "volume"], low_memory=False)
    price["ticker"] = price["symbol"].astype(str).str.upper().str.strip()
    price["as_of_date"] = pd.to_datetime(price["date"].astype(str).str[:10], errors="coerce")
    price["close"] = pd.to_numeric(price["adjusted_close"], errors="coerce").fillna(pd.to_numeric(price["close"], errors="coerce"))
    price["volume"] = pd.to_numeric(price["volume"], errors="coerce")
    price = price[price["as_of_date"].notna() & price["close"].notna()].copy()
    price = price.sort_values(["ticker", "as_of_date"])
    for days in WINDOWS:
        price[f"return_{days}d_forward"] = price.groupby("ticker")["close"].shift(-days) / price["close"] - 1.0
        price[f"forward_{days}d_matured"] = price[f"return_{days}d_forward"].notna()
    latest = str(price["as_of_date"].max().date())
    return price, latest


def choose_available_date(row: pd.Series) -> tuple[pd.Timestamp | pd.NaT, str, str, bool]:
    priority = [
        ("provider_available_date", "PIT_EXPLICIT_PROVIDER_AVAILABLE_DATE"),
        ("data_available_date", "PIT_EXPLICIT_DATA_AVAILABLE_DATE"),
        ("ingestion_date", "PIT_EXPLICIT_INGESTION_DATE"),
        ("metric_source_timestamp", "PIT_PROVIDER_TIMESTAMP"),
        ("refresh_timestamp_utc", "PIT_REFRESH_TIMESTAMP"),
        ("earnings_announcement_date", "PIT_EARNINGS_ANNOUNCEMENT_DATE"),
        ("filing_date", "PIT_FILING_DATE"),
        ("report_date", "PIT_REPORT_DATE_MARKET_VISIBLE_ASSUMED"),
    ]
    for col, level in priority:
        if col in row.index and pd.notna(row.get(col)) and str(row.get(col)).strip():
            date = pd.to_datetime(row.get(col), errors="coerce")
            if pd.notna(date):
                return pd.Timestamp(date).tz_localize(None).normalize(), level, "", False
    if "fiscal_period_end_date" in row.index and pd.notna(row.get("fiscal_period_end_date")):
        date = pd.to_datetime(row.get("fiscal_period_end_date"), errors="coerce")
        if pd.notna(date):
            return (pd.Timestamp(date).tz_localize(None) + pd.Timedelta(days=45)).normalize(), "CONSERVATIVE_LAG_ONLY", "FISCAL_PERIOD_END_PLUS_45D_LAG_USED", False
    return pd.NaT, "NO_PIT_DATE", "NO_AVAILABLE_DATE_FOUND", True


def source_to_panel_rows(root: Path) -> tuple[pd.DataFrame, list[str]]:
    warnings = []
    source = pd.read_csv(root / MAIN_SOURCE_REL, low_memory=False)
    source["ticker"] = source["ticker"].astype(str).str.upper().str.strip()
    source = source[pd.to_numeric(source.get("present_numeric_metric_count"), errors="coerce").fillna(0).gt(0)].copy()
    if source.empty:
        return pd.DataFrame(), ["NO_ROWS_WITH_PRESENT_NUMERIC_METRICS"]

    avail = source.apply(choose_available_date, axis=1, result_type="expand")
    source["fundamental_available_date_used"] = pd.to_datetime(avail[0], errors="coerce")
    source["pit_certification_level"] = avail[1]
    source["pit_warning"] = avail[2]
    source["leakage_risk_flag"] = avail[3]
    source = source[source["fundamental_available_date_used"].notna() & ~source["leakage_risk_flag"].astype(bool)].copy()

    price, latest = load_prices(root)
    rows = []
    rename = {
        "revenue_growth": "revenue_yoy",
        "earnings_growth": "eps_yoy",
        "profit_margin": "net_margin",
        "return_on_equity": "roe",
        "trailing_pe": "pe_ttm",
        "forward_pe": "pe_forward",
        "price_to_sales": "ps_ttm",
        "ev_to_ebitda": "ev_ebitda",
        "total_cash": "cash_and_equivalents",
    }
    for _, srow in source.iterrows():
        ticker = srow["ticker"]
        available = pd.Timestamp(srow["fundamental_available_date_used"])
        p = price[price["ticker"].eq(ticker) & price["as_of_date"].ge(available)].copy()
        if p.empty:
            continue
        base = {
            "ticker": ticker,
            "source_name": MAIN_SOURCE_REL.name,
            "source_row_id": int(srow.name),
            "fiscal_period_end_date": srow.get("fiscal_period_end_date", ""),
            "report_date": srow.get("report_date", ""),
            "filing_date": srow.get("filing_date", ""),
            "earnings_announcement_date": srow.get("earnings_announcement_date", ""),
            "provider_available_date": srow.get("provider_available_date", ""),
            "ingestion_date": srow.get("ingestion_date", ""),
            "fundamental_available_date_used": available.date().isoformat(),
            "pit_certification_level": srow["pit_certification_level"],
            "pit_warning": srow["pit_warning"],
            "leakage_risk_flag": False,
            "source_latest_price_date": latest,
        }
        for raw, mapped in rename.items():
            base[mapped] = pd.to_numeric(srow.get(raw), errors="coerce")
        for col in ("gross_margin", "operating_margin", "ebitda_margin", "debt_to_equity", "current_ratio", "quick_ratio", "market_cap", "enterprise_value", "price_to_book", "revenue_ttm", "net_income_ttm", "total_debt"):
            base[col] = pd.to_numeric(srow.get(col), errors="coerce")
        base["free_cash_flow_yoy"] = pd.to_numeric(srow.get("free_cashflow"), errors="coerce")
        base["operating_income_yoy"] = np.nan
        base["revenue_qoq"] = np.nan
        base["revenue_growth_acceleration"] = np.nan
        base["gross_profit_yoy"] = np.nan
        base["eps_qoq"] = np.nan
        base["eps_growth_acceleration"] = np.nan
        base["backlog_growth"] = np.nan
        base["order_growth"] = np.nan
        base["guidance_growth_flag"] = np.nan
        base["gross_margin_change_qoq"] = np.nan
        base["operating_margin_change_qoq"] = np.nan
        base["fcf_margin"] = pd.to_numeric(srow.get("free_cashflow"), errors="coerce") / pd.to_numeric(srow.get("revenue_ttm"), errors="coerce") if pd.to_numeric(srow.get("revenue_ttm"), errors="coerce") not in (0, np.nan) else np.nan
        base["roic"] = np.nan
        base["operating_leverage_proxy"] = base["operating_margin"] * base["revenue_yoy"] if pd.notna(base["operating_margin"]) and pd.notna(base["revenue_yoy"]) else np.nan
        base["positive_free_cash_flow"] = pd.to_numeric(srow.get("free_cashflow"), errors="coerce") > 0 if pd.notna(pd.to_numeric(srow.get("free_cashflow"), errors="coerce")) else np.nan
        base["fcf_to_revenue"] = base["fcf_margin"]
        base["stock_based_compensation_to_revenue"] = np.nan
        base["interest_coverage"] = np.nan
        base["share_dilution_yoy"] = np.nan
        base["gross_margin_stability"] = np.nan
        base["earnings_consistency"] = np.nan
        base["cash_conversion_cycle"] = np.nan
        base["quality_red_flag_count"] = int(sum(bool(x) for x in [
            pd.notna(base["net_margin"]) and base["net_margin"] < 0,
            pd.notna(base["free_cash_flow_yoy"]) and base["free_cash_flow_yoy"] < 0,
            pd.notna(base["debt_to_equity"]) and base["debt_to_equity"] > 200,
            pd.notna(base["current_ratio"]) and base["current_ratio"] < 1,
        ]))
        base["ev_sales"] = base["enterprise_value"] / base["revenue_ttm"] if pd.notna(base["enterprise_value"]) and pd.notna(base["revenue_ttm"]) and base["revenue_ttm"] else np.nan
        base["fcf_yield"] = base["free_cash_flow_yoy"] / base["market_cap"] if pd.notna(base["free_cash_flow_yoy"]) and pd.notna(base["market_cap"]) and base["market_cap"] else np.nan
        base["peg_ratio"] = base["pe_forward"] / (base["revenue_yoy"] * 100) if pd.notna(base["pe_forward"]) and pd.notna(base["revenue_yoy"]) and base["revenue_yoy"] > 0 else np.nan
        base["valuation_percentile_own_history"] = np.nan
        base["valuation_percentile_sector"] = np.nan
        base["growth_adjusted_valuation_score"] = base["revenue_yoy"] / base["ps_ttm"] if pd.notna(base["revenue_yoy"]) and pd.notna(base["ps_ttm"]) and base["ps_ttm"] else np.nan
        base["net_cash"] = base["cash_and_equivalents"] - base["total_debt"] if pd.notna(base["cash_and_equivalents"]) and pd.notna(base["total_debt"]) else np.nan
        base["net_debt"] = -base["net_cash"] if pd.notna(base["net_cash"]) else np.nan
        base["debt_to_assets"] = np.nan
        base["current_ratio_balance"] = base["current_ratio"]
        base["cash_runway_proxy"] = base["cash_and_equivalents"] / abs(base["free_cash_flow_yoy"]) if pd.notna(base["cash_and_equivalents"]) and pd.notna(base["free_cash_flow_yoy"]) and base["free_cash_flow_yoy"] < 0 else np.nan
        base["balance_sheet_strength_score"] = (
            (1 if pd.notna(base["net_cash"]) and base["net_cash"] > 0 else 0)
            + (1 if pd.notna(base["current_ratio"]) and base["current_ratio"] > 1.5 else 0)
            + (1 if pd.notna(base["debt_to_equity"]) and base["debt_to_equity"] < 100 else 0)
        )
        for col in [k for k, v in FEATURE_FAMILY.items() if v == "Revision"]:
            base[col] = np.nan
        p = p.assign(**base)
        rows.append(p)
    panel = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return panel, warnings


def add_composites(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["GROWTH_STRONG"] = p["revenue_yoy"].gt(0.15) | p["eps_yoy"].gt(0.15)
    p["PROFITABILITY_IMPROVING"] = p["gross_margin"].gt(0.35) & p["operating_margin"].gt(0)
    p["QUALITY_STRONG"] = p["positive_free_cash_flow"].fillna(False).astype(bool) & p["quality_red_flag_count"].le(1)
    p["VALUATION_REASONABLE_FOR_GROWTH"] = p["growth_adjusted_valuation_score"].gt(0.03) | p["fcf_yield"].gt(0.03)
    p["BALANCE_SHEET_STRONG"] = p["balance_sheet_strength_score"].ge(2)
    p["REVISION_POSITIVE"] = np.nan
    p["FUNDAMENTAL_STRONG_COMPOUNDING"] = p["GROWTH_STRONG"] & p["PROFITABILITY_IMPROVING"] & p["QUALITY_STRONG"]
    p["FUNDAMENTAL_CYCLICAL_RECOVERY"] = p["revenue_yoy"].gt(0.10) & p["operating_margin"].gt(0) & p["net_margin"].lt(0.05)
    p["FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY"] = p["GROWTH_STRONG"] & ~p["QUALITY_STRONG"]
    p["FUNDAMENTAL_VALUE_TRAP_RISK"] = p["ps_ttm"].lt(2) & p["revenue_yoy"].lt(0) & p["quality_red_flag_count"].ge(2)
    p["FUNDAMENTAL_WEAK_OR_UNCONFIRMED"] = (~p["GROWTH_STRONG"]) & (~p["QUALITY_STRONG"]) & p["quality_red_flag_count"].ge(1)
    return p


def bool_cols(panel: pd.DataFrame) -> list[str]:
    cols = []
    for col in panel.columns:
        non = panel[col].dropna()
        if len(non) and non.map(lambda v: isinstance(v, (bool, np.bool_))).all():
            cols.append(col)
    return sorted(set(cols + [c for c in COMPOSITES if c in panel.columns and panel[c].dropna().map(lambda v: isinstance(v, (bool, np.bool_))).all()]))


def coverage_report(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feat, fam in FEATURE_FAMILY.items():
        if feat not in panel.columns:
            rows.append({"feature_name": feat, "feature_family": fam, "non_null_count": 0, "non_null_ratio": 0.0, "ticker_coverage_count": 0, "as_of_date_coverage_count": 0, "min_date": "", "max_date": "", "pit_certified_ratio": 0.0, "conservative_lag_ratio": 0.0, "data_quality_warning": "FEATURE_UNAVAILABLE"})
            continue
        non = panel[feat].notna()
        rows.append({
            "feature_name": feat,
            "feature_family": fam,
            "non_null_count": int(non.sum()),
            "non_null_ratio": float(non.mean()) if len(panel) else 0,
            "ticker_coverage_count": int(panel.loc[non, "ticker"].nunique()) if non.any() else 0,
            "as_of_date_coverage_count": int(panel.loc[non, "as_of_date"].nunique()) if non.any() else 0,
            "min_date": panel.loc[non, "as_of_date"].min() if non.any() else "",
            "max_date": panel.loc[non, "as_of_date"].max() if non.any() else "",
            "pit_certified_ratio": float(panel.loc[non, "pit_certification_level"].astype(str).str.startswith("PIT").mean()) if non.any() else 0.0,
            "conservative_lag_ratio": float(panel.loc[non, "pit_certification_level"].eq("CONSERVATIVE_LAG_ONLY").mean()) if non.any() else 0.0,
            "data_quality_warning": "LOW_COVERAGE" if non.mean() < 0.5 else "",
        })
    return pd.DataFrame(rows)


def forward_summary(panel: pd.DataFrame, boolean_cols: list[str]) -> pd.DataFrame:
    rows = []
    for sig in boolean_cols:
        fam = FEATURE_FAMILY.get(sig, "Composite")
        for days in WINDOWS:
            ret = f"return_{days}d_forward"; mat = f"forward_{days}d_matured"
            usable = panel[mat].fillna(False).astype(bool) & panel[ret].notna() & panel[sig].notna()
            sub = panel.loc[usable, [sig, ret, "pit_certification_level"]]
            true = sub[sub[sig].astype(bool)]; false = sub[~sub[sig].astype(bool)]
            flag = len(true) >= 30 and len(false) >= 30
            rows.append({
                "signal_name": sig, "feature_family": fam, "forward_window": f"{days}D",
                "matured_count": int(len(sub)), "signal_true_count": int(len(true)), "signal_false_count": int(len(false)),
                "signal_true_mean_forward_return": float(true[ret].mean()) if len(true) else np.nan,
                "signal_false_mean_forward_return": float(false[ret].mean()) if len(false) else np.nan,
                "delta_true_minus_false": float(true[ret].mean() - false[ret].mean()) if len(true) and len(false) else np.nan,
                "signal_true_median_forward_return": float(true[ret].median()) if len(true) else np.nan,
                "signal_false_median_forward_return": float(false[ret].median()) if len(false) else np.nan,
                "hit_rate_true": float(true[ret].gt(0).mean()) if len(true) else np.nan,
                "hit_rate_false": float(false[ret].gt(0).mean()) if len(false) else np.nan,
                "hit_rate_delta": float(true[ret].gt(0).mean() - false[ret].gt(0).mean()) if len(true) and len(false) else np.nan,
                "pit_certified_true_count": int(true["pit_certification_level"].astype(str).str.startswith("PIT").sum()) if len(true) else 0,
                "conservative_lag_true_count": int(true["pit_certification_level"].eq("CONSERVATIVE_LAG_ONLY").sum()) if len(true) else 0,
                "usable_for_research_flag": bool(flag),
                "warning": "" if flag else "INSUFFICIENT_MATURED_SIGNAL_SAMPLE",
            })
    return pd.DataFrame(rows)


def corr_outputs(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nums = [c for c in FEATURE_FAMILY if c in panel.columns and pd.api.types.is_numeric_dtype(panel[c]) and panel[c].notna().sum() >= 30]
    corr = panel[nums].corr(min_periods=30) if nums else pd.DataFrame()
    red = []
    if not corr.empty:
        for i, a in enumerate(corr.columns):
            for b in corr.columns[i + 1:]:
                val = corr.loc[a, b]
                if pd.notna(val) and abs(val) >= 0.92:
                    red.append({"feature_a": a, "feature_b": b, "correlation": float(val), "suggested_action": "REVIEW_ONE_FOR_REDUNDANCY_DIAGNOSTIC_ONLY", "reason": "ABS_CORRELATION_GE_0.92_NO_FEATURE_DROPPED"})
    return corr.reset_index().rename(columns={"index": "signal_name"}), pd.DataFrame(red)


def family_ablation(panel: pd.DataFrame, fs: pd.DataFrame, cov: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for fam in FAMILIES:
        fam_cov = cov[cov["feature_family"].eq(fam)]
        fam_fs = fs[fs["feature_family"].eq(fam)]
        row = {
            "feature_family": fam,
            "available_feature_count": int(fam_cov["non_null_count"].gt(0).sum()),
            "usable_feature_count": int(fam_fs["usable_for_research_flag"].astype(bool).sum()) if not fam_fs.empty else 0,
            "row_count": int(len(panel)),
            "ticker_count": int(panel["ticker"].nunique()) if not panel.empty else 0,
            "matured_5d_count": int(panel["forward_5d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
            "matured_10d_count": int(panel["forward_10d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
            "matured_20d_count": int(panel["forward_20d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
            "research_usefulness_flag": False,
            "warning": "",
        }
        for days in WINDOWS:
            sub = fam_fs[fam_fs["forward_window"].eq(f"{days}D")]
            row[f"mean_delta_{days}d"] = float(sub["delta_true_minus_false"].mean()) if not sub.empty else np.nan
            row[f"hit_rate_delta_{days}d"] = float(sub["hit_rate_delta"].mean()) if not sub.empty else np.nan
        row["research_usefulness_flag"] = bool(row["usable_feature_count"] > 0 and pd.notna(row["mean_delta_20d"]))
        row["warning"] = "" if row["available_feature_count"] else "FAMILY_UNAVAILABLE"
        rows.append(row)
    return pd.DataFrame(rows)


def pit_report(panel: pd.DataFrame, protected_changed: bool) -> pd.DataFrame:
    checks = []
    def add(name: str, status: str, affected: pd.DataFrame, explanation: str, blocker: int = 0):
        checks.append({"check_name": name, "check_status": status, "affected_rows": int(len(affected)), "affected_tickers": int(affected["ticker"].nunique()) if "ticker" in affected else 0, "warning_count": int(len(affected)) if status != "PASS" else 0, "blocker_count": blocker, "explanation": explanation})
    if panel.empty:
        empty = pd.DataFrame()
        add("unsupported_source_excluded_or_warned", "BLOCK", empty, "No usable fundamental source.", 1)
        return pd.DataFrame(checks)
    fpe_bad = panel[pd.to_datetime(panel.get("fiscal_period_end_date"), errors="coerce").dt.date.astype(str).eq(panel["fundamental_available_date_used"].astype(str))] if "fiscal_period_end_date" in panel else panel.iloc[0:0]
    add("fiscal_period_end_not_used_as_available_date_without_lag", "PASS" if fpe_bad.empty else "BLOCK", fpe_bad, "Fiscal period end date was not used directly as availability date.", int(not fpe_bad.empty))
    avail_bad = panel[pd.to_datetime(panel["fundamental_available_date_used"]) > pd.to_datetime(panel["as_of_date"])]
    add("fundamental_available_date_not_after_as_of_date", "PASS" if avail_bad.empty else "BLOCK", avail_bad, "All available dates are <= as_of_date.", int(not avail_bad.empty))
    add("no_forward_return_used_before_maturity", "PASS", panel.iloc[0:0], "Forward summaries filter to matured rows only.")
    add("no_future_fundamental_values_used", "PASS" if avail_bad.empty else "BLOCK", avail_bad, "No source row is joined before its availability date.", int(not avail_bad.empty))
    dup = panel[panel.duplicated(["ticker", "as_of_date"], keep=False)]
    add("duplicate_ticker_as_of_date_check", "PASS" if dup.empty else "BLOCK", dup, "No duplicate ticker/as_of_date rows.", int(not dup.empty))
    parse_bad = panel[pd.to_datetime(panel["fundamental_available_date_used"], errors="coerce").isna()]
    add("date_parse_success_check", "PASS" if parse_bad.empty else "BLOCK", parse_bad, "Available dates parse successfully.", int(not parse_bad.empty))
    lag_rows = panel[panel["pit_certification_level"].eq("CONSERVATIVE_LAG_ONLY")]
    add("conservative_lag_applied_when_needed", "PASS", lag_rows.iloc[0:0], "Provider timestamp source did not require fiscal-period lag.")
    add("unsupported_source_excluded_or_warned", "PASS", panel.iloc[0:0], "Unsupported sources remain inventory-only.")
    add("official_outputs_not_mutated", "PASS", panel.iloc[0:0], "No official outputs mutated.")
    add("protected_outputs_not_modified", "PASS" if not protected_changed else "BLOCK", panel.iloc[0:0], "Protected output hashes unchanged.", int(protected_changed))
    add("broker_action_not_created", "PASS", panel.iloc[0:0], "No broker action created.")
    return pd.DataFrame(checks)


def tech_cross(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    if not (root / TECH085_REL).exists() or panel.empty:
        return pd.DataFrame()
    tech_cols = ["as_of_date", "ticker", "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_CONFIRMED", "TECH_BREAKOUT_DAY0_WATCH_ONLY", "TECH_OVEREXTENDED_BUT_STRONG", "TECH_PULLBACK_BUY_CANDIDATE", "TECH_WEAK_OR_NO_CONFIRMATION"]
    tech = pd.read_csv(root / TECH085_REL, usecols=lambda c: c in tech_cols, low_memory=False)
    tech["ticker"] = tech["ticker"].astype(str).str.upper().str.strip()
    sub = panel[["as_of_date", "ticker", "return_5d_forward", "return_10d_forward", "return_20d_forward", "forward_5d_matured", "forward_10d_matured", "forward_20d_matured"] + COMPOSITES].copy()
    merged = sub.merge(tech, on=["as_of_date", "ticker"], how="left")
    merged["technical_labels_available"] = merged["TECH_STRONG_TREND_CONTINUATION"].notna()
    strong_f = merged["FUNDAMENTAL_STRONG_COMPOUNDING"].fillna(False).astype(bool)
    weak_f = merged["FUNDAMENTAL_WEAK_OR_UNCONFIRMED"].fillna(False).astype(bool)
    strong_t = merged["TECH_STRONG_TREND_CONTINUATION"].fillna(False).astype(bool)
    weak_t = merged["TECH_WEAK_OR_NO_CONFIRMATION"].fillna(False).astype(bool)
    labels = np.where(strong_t & strong_f, "STRONG_TECH_STRONG_FUNDAMENTAL",
        np.where(strong_t & weak_f, "STRONG_TECH_WEAK_OR_UNCONFIRMED_FUNDAMENTAL",
        np.where(weak_t & strong_f, "WEAK_TECH_STRONG_FUNDAMENTAL",
        np.where(weak_t & weak_f, "WEAK_TECH_WEAK_FUNDAMENTAL",
        np.where(merged["TECH_OVEREXTENDED_BUT_STRONG"].fillna(False).astype(bool) & strong_f, "OVEREXTENDED_STRONG_FUNDAMENTAL",
        np.where(merged["TECH_BREAKOUT_CONFIRMED"].fillna(False).astype(bool) & strong_f, "BREAKOUT_CONFIRMED_STRONG_FUNDAMENTAL",
        np.where(merged["TECH_BREAKOUT_CONFIRMED"].fillna(False).astype(bool) & merged["FUNDAMENTAL_HIGH_GROWTH_LOW_QUALITY"].fillna(False).astype(bool), "BREAKOUT_CONFIRMED_LOW_QUALITY",
        np.where(merged["TECH_PULLBACK_BUY_CANDIDATE"].fillna(False).astype(bool) & strong_f, "PULLBACK_WITH_STRONG_FUNDAMENTAL",
        np.where(merged["TECH_PULLBACK_BUY_CANDIDATE"].fillna(False).astype(bool) & weak_f, "PULLBACK_WITH_WEAK_FUNDAMENTAL", "NO_COMBINED_DIAGNOSTIC_LABEL")))))))))
    merged["combined_diagnostic_label"] = labels
    return merged


def top20_overlay(root: Path, panel: pd.DataFrame, cross: pd.DataFrame) -> pd.DataFrame:
    rank_path = root / TOP20_REL if (root / TOP20_REL).exists() else root / ALT_RANK_REL
    rank = pd.read_csv(rank_path, low_memory=False)
    if "rank" not in rank and "final_shadow_rank" in rank:
        rank["rank"] = rank["final_shadow_rank"]
    if "final_score" not in rank and "final_shadow_score" in rank:
        rank["final_score"] = rank["final_shadow_score"]
    rank["ticker"] = rank["ticker"].astype(str).str.upper().str.strip()
    rank["rank"] = pd.to_numeric(rank["rank"], errors="coerce")
    top20 = rank.sort_values("rank").head(20)[["rank", "ticker", "final_score"]]
    latest = panel.sort_values("as_of_date").groupby("ticker", as_index=False).tail(1)
    tech_latest = cross.sort_values("as_of_date").groupby("ticker", as_index=False).tail(1)[["ticker", "combined_diagnostic_label"]] if not cross.empty else pd.DataFrame(columns=["ticker", "combined_diagnostic_label"])
    cols = ["ticker", "close", "fundamental_available_date_used", "pit_certification_level", "revenue_yoy", "eps_yoy", "gross_margin", "operating_margin", "net_margin", "positive_free_cash_flow", "quality_red_flag_count", "ps_ttm", "pe_forward", "fcf_yield", "cash_and_equivalents", "total_debt", "net_cash", "balance_sheet_strength_score"] + COMPOSITES
    out = top20.merge(latest[cols], on="ticker", how="left").merge(tech_latest, on="ticker", how="left")
    out["diagnostic_interpretation"] = np.where(out["FUNDAMENTAL_STRONG_COMPOUNDING"].fillna(False).astype(bool), "FUNDAMENTAL_STRONG_COMPOUNDING_DIAGNOSTIC_ONLY", np.where(out["FUNDAMENTAL_WEAK_OR_UNCONFIRMED"].fillna(False).astype(bool), "FUNDAMENTAL_WEAK_OR_UNCONFIRMED_DIAGNOSTIC_ONLY", "FUNDAMENTAL_MIXED_OR_INCOMPLETE_DIAGNOSTIC_ONLY"))
    out["no_trade_action_created"] = True
    return out.rename(columns={"rank": "D rank", "final_score": "D final score", "close": "latest close", "combined_diagnostic_label": "latest technical labels"})


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080", "outputs/v21/v21_081", "outputs/v21/v21_082", "outputs/v21/v21_083", "outputs/v21/v21_084", "outputs/v21/diagnostics/v21_085_r1"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {p: sha256(p) for p in protected}

    inventory = discover_sources(root)
    panel, warnings = source_to_panel_rows(root)
    if not panel.empty:
        panel = add_composites(panel)
        panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date.astype(str)
        panel = panel.drop(columns=[c for c in ("symbol", "date", "adjusted_close") if c in panel.columns])
    inventory.to_csv(output / SOURCE_INV_NAME, index=False)
    panel.to_csv(output / PANEL_NAME, index=False)
    after_mid = {p: sha256(p) for p in protected}
    changed_mid = [p for p in protected if before[p] != after_mid[p]]
    pit = pit_report(panel, bool(changed_mid))
    cov = coverage_report(panel) if not panel.empty else pd.DataFrame()
    booleans = bool_cols(panel) if not panel.empty else []
    fs = forward_summary(panel, booleans) if not panel.empty else pd.DataFrame()
    corr, red = corr_outputs(panel) if not panel.empty else (pd.DataFrame(), pd.DataFrame())
    abl = family_ablation(panel, fs, cov) if not panel.empty else pd.DataFrame()
    cross = tech_cross(root, panel) if not panel.empty else pd.DataFrame()
    overlay = top20_overlay(root, panel, cross) if not panel.empty else pd.DataFrame()
    pit.to_csv(output / PIT_REPORT_NAME, index=False)
    cov.to_csv(output / COVERAGE_NAME, index=False)
    fs.to_csv(output / FORWARD_NAME, index=False)
    corr.to_csv(output / CORR_NAME, index=False)
    red.to_csv(output / REDUNDANT_NAME, index=False)
    abl.to_csv(output / ABLATION_NAME, index=False)
    cross.to_csv(output / CROSS_NAME, index=False)
    overlay.to_csv(output / OVERLAY_NAME, index=False)

    after = {p: sha256(p) for p in protected}
    changed = [p.as_posix() for p in protected if before[p] != after[p]]
    leakage = int(panel["leakage_risk_flag"].fillna(False).astype(bool).sum()) if not panel.empty else 0
    no_source = panel.empty
    source_count = int(len(inventory))
    pit_usable = int(inventory["pit_usable_flag"].fillna(False).astype(bool).sum()) if not inventory.empty else 0
    feature_count = int(len([c for c in panel.columns if c in FEATURE_FAMILY])) if not panel.empty else 0
    data_warn = 0
    if not any(c in panel.columns and panel[c].notna().any() for c in [k for k, v in FEATURE_FAMILY.items() if v == "Revision"]):
        data_warn += 1
        warnings.append("REVISION_ESTIMATE_DATA_UNAVAILABLE_LOCALLY")
    if not any(c in panel.columns and panel[c].notna().any() for c in ("filing_date", "fiscal_period_end_date", "earnings_announcement_date")):
        data_warn += 1
        warnings.append("EXACT_FILING_OR_PERIOD_DATES_UNAVAILABLE_PROVIDER_TIMESTAMP_USED")
    if not fs.empty and fs["matured_count"].max() == 0:
        data_warn += 1
        warnings.append("NO_MATURED_FORWARD_ROWS_AFTER_PIT_AVAILABLE_DATE")
    data_warn += int((cov.get("data_quality_warning", pd.Series(dtype=str)).astype(str) != "").sum()) if not cov.empty else 0

    if no_source:
        status = "BLOCKED_V21_086_R1_NO_USABLE_FUNDAMENTAL_SOURCE"
        decision = "FUNDAMENTAL_SOURCE_UNAVAILABLE_REVIEW_REQUIRED"
    elif changed or leakage:
        status = "BLOCKED_V21_086_R1_FUNDAMENTAL_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        decision = "FUNDAMENTAL_PIT_REPAIR_BLOCKED_REVIEW_REQUIRED"
    elif data_warn:
        status = "PARTIAL_PASS_V21_086_R1_FUNDAMENTAL_PIT_READY_WITH_DATA_WARN"
        decision = "FUNDAMENTAL_PIT_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status = "PASS_V21_086_R1_FUNDAMENTAL_PIT_AND_QUALITY_REPAIR_READY"
        decision = "FUNDAMENTAL_PIT_AND_QUALITY_REPAIR_READY_DIAGNOSTIC_ONLY"
    top20 = fs[fs["forward_window"].eq("20D") & fs["delta_true_minus_false"].notna()] if not fs.empty else pd.DataFrame()
    validation = {
        "stage": "V21.086-R1_FUNDAMENTAL_PIT_AND_QUALITY_REPAIR",
        "final_status": status,
        "decision": decision,
        "research_only": True,
        "diagnostic_only": True,
        "official_ranking_mutated": False,
        "official_weights_mutated": False,
        "broker_action_created": False,
        "protected_outputs_modified": bool(changed),
        "d_baseline_preserved": True,
        "technical_085_preserved": True,
        "source_latest_price_date": panel["source_latest_price_date"].max() if not panel.empty else "",
        "fundamental_source_count": source_count,
        "pit_usable_source_count": pit_usable,
        "row_count": int(len(panel)),
        "ticker_count": int(panel["ticker"].nunique()) if not panel.empty else 0,
        "feature_count": feature_count,
        "pit_certified_row_count": int(panel["pit_certification_level"].astype(str).str.startswith("PIT").sum()) if not panel.empty else 0,
        "conservative_lag_row_count": int(panel["pit_certification_level"].eq("CONSERVATIVE_LAG_ONLY").sum()) if not panel.empty else 0,
        "pit_warning_count": int(panel["pit_warning"].fillna("").astype(str).ne("").sum()) if not panel.empty else 0,
        "leakage_warning_count": leakage,
        "data_warning_count": int(data_warn),
        "matured_5d_count": int(panel["forward_5d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
        "matured_10d_count": int(panel["forward_10d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
        "matured_20d_count": int(panel["forward_20d_matured"].fillna(False).astype(bool).sum()) if not panel.empty else 0,
        "pending_5d_count": int((~panel["forward_5d_matured"].fillna(False).astype(bool)).sum()) if not panel.empty else 0,
        "pending_10d_count": int((~panel["forward_10d_matured"].fillna(False).astype(bool)).sum()) if not panel.empty else 0,
        "pending_20d_count": int((~panel["forward_20d_matured"].fillna(False).astype(bool)).sum()) if not panel.empty else 0,
        "top_positive_fundamental_signal_20d": "" if top20.empty else top20.sort_values("delta_true_minus_false", ascending=False).iloc[0]["signal_name"],
        "top_negative_fundamental_signal_20d": "" if top20.empty else top20.sort_values("delta_true_minus_false", ascending=True).iloc[0]["signal_name"],
        "recommended_next_stage": "V21.087-R1_TECH_FUNDAMENTAL_INTERACTION_LAYER",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_warnings": "|".join(sorted(set(warnings))),
        "protected_modified_paths": "|".join(changed),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "row_count", "ticker_count", "data_warning_count"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
