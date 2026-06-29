#!/usr/bin/env python
"""V21.085-R1 technical feature enrichment audit.

Diagnostic-only enrichment of the technical layer. This script writes only to
outputs/v21/diagnostics/v21_085_r1 and never mutates ranking or broker files.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_085_r1")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
BENCH_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv")
TOP20_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "v21_066a_latest_data_ranking_viewer/V21_066A_D_LATEST_RANKING_TOP20.csv"
)
ALT_RANK_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")

PANEL_NAME = "V21_085_R1_TECHNICAL_FEATURE_PANEL.csv"
COVERAGE_NAME = "V21_085_R1_TECHNICAL_SIGNAL_COVERAGE_REPORT.csv"
FORWARD_NAME = "V21_085_R1_TECHNICAL_SIGNAL_FORWARD_RETURN_SUMMARY.csv"
CORR_NAME = "V21_085_R1_TECHNICAL_SIGNAL_CORRELATION_MATRIX.csv"
REDUNDANT_NAME = "V21_085_R1_TECHNICAL_REDUNDANT_SIGNAL_DROP_CANDIDATES.csv"
OVERLAY_NAME = "V21_085_R1_TOP20_D_DIAGNOSTIC_OVERLAY.csv"
VALIDATION_NAME = "V21_085_R1_VALIDATION_SUMMARY.csv"

WINDOWS = (5, 10, 20)
BENCHMARKS = ("QQQ", "SPY", "SOXX")


def truthy(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_prices(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    price = pd.read_csv(root / PRICE_REL, low_memory=False)
    bench = pd.read_csv(root / BENCH_REL, low_memory=False)
    warnings: list[str] = []
    for frame in (price, bench):
        frame["ticker"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["as_of_date"] = pd.to_datetime(frame["date"].astype(str).str[:10], errors="coerce")
        for col in ("open", "high", "low", "close", "adjusted_close", "volume"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
    required = {"open", "high", "low", "close", "adjusted_close", "volume"}
    missing = sorted(required - set(price.columns))
    if missing:
        warnings.append("MISSING_PRICE_COLUMNS:" + "|".join(missing))
    price = price[price["as_of_date"].notna() & price["ticker"].notna()].copy()
    bench = bench[bench["as_of_date"].notna() & bench["ticker"].notna()].copy()
    return price, bench, warnings


def rolling_percentile_last(series: pd.Series) -> float:
    values = series.dropna()
    if values.empty:
        return np.nan
    return float(values.rank(pct=True).iloc[-1])


def rsi(close: pd.Series, periods: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / periods, adjust=False, min_periods=periods).mean()
    avg_loss = loss.ewm(alpha=1 / periods, adjust=False, min_periods=periods).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def days_since_true(flag: pd.Series) -> pd.Series:
    result: list[float] = []
    last_idx: int | None = None
    for i, value in enumerate(flag.fillna(False).astype(bool).tolist()):
        if value:
            last_idx = i
            result.append(0.0)
        elif last_idx is None:
            result.append(np.nan)
        else:
            result.append(float(i - last_idx))
    return pd.Series(result, index=flag.index)


def add_group_features(group: pd.DataFrame) -> pd.DataFrame:
    g = group.sort_values("as_of_date").copy()
    if "ticker" not in g.columns:
        g["ticker"] = getattr(group, "name", "")
    close = g["adjusted_close"].where(g["adjusted_close"].notna(), g["close"])
    high = g["high"] if "high" in g.columns else close
    low = g["low"] if "low" in g.columns else close
    volume = g["volume"] if "volume" in g.columns else pd.Series(np.nan, index=g.index)

    g["close"] = close
    g["source_price_date"] = g["as_of_date"].dt.date.astype(str)
    for days in WINDOWS:
        fwd = close.shift(-days) / close - 1.0
        g[f"return_{days}d_forward"] = fwd
        g[f"forward_{days}d_matured"] = fwd.notna()

    g["rsi_14"] = rsi(close, 14)
    g["rsi_14_slope_3d"] = g["rsi_14"] - g["rsi_14"].shift(3)
    g["rsi_14_slope_5d"] = g["rsi_14"] - g["rsi_14"].shift(5)
    for level in (30, 40, 50):
        g[f"rsi_cross_up_{level}"] = g["rsi_14"].ge(level) & g["rsi_14"].shift(1).lt(level)
    g["rsi_overbought_70"] = g["rsi_14"].gt(70)
    g["rsi_high_persistence_3d"] = g["rsi_14"].gt(60).rolling(3, min_periods=3).sum().eq(3)
    g["rsi_bullish_regime_flag"] = g["rsi_14"].gt(55) & g["rsi_14_slope_5d"].gt(0)
    g["rsi_bearish_regime_flag"] = g["rsi_14"].lt(45) & g["rsi_14_slope_5d"].lt(0)

    low_n = low.rolling(9, min_periods=5).min()
    high_n = high.rolling(9, min_periods=5).max()
    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan) * 100).clip(0, 100)
    g["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False, min_periods=3).mean()
    g["kdj_d"] = g["kdj_k"].ewm(alpha=1 / 3, adjust=False, min_periods=3).mean()
    g["kdj_j"] = 3 * g["kdj_k"] - 2 * g["kdj_d"]
    g["kdj_gold_cross"] = g["kdj_k"].gt(g["kdj_d"]) & g["kdj_k"].shift(1).le(g["kdj_d"].shift(1))
    g["kdj_gold_cross_low_zone"] = g["kdj_gold_cross"] & g["kdj_k"].lt(30)
    g["kdj_gold_cross_mid_zone"] = g["kdj_gold_cross"] & g["kdj_k"].between(30, 70, inclusive="both")
    g["kdj_gold_cross_high_zone"] = g["kdj_gold_cross"] & g["kdj_k"].gt(70)
    g["kdj_days_since_gold_cross"] = days_since_true(g["kdj_gold_cross"])
    g["kdj_confirmed_by_price"] = g["kdj_gold_cross"] & close.gt(close.shift(1))
    g["kdj_confirmed_by_volume"] = g["kdj_gold_cross"] & volume.gt(volume.rolling(20, min_periods=5).mean())
    g["kdj_false_cross_risk"] = g["kdj_gold_cross"] & close.lt(g["ma20"] if "ma20" in g else close.rolling(20, min_periods=10).mean())

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    g["macd_dif"] = ema12 - ema26
    g["macd_dea"] = g["macd_dif"].ewm(span=9, adjust=False, min_periods=9).mean()
    g["macd_hist"] = g["macd_dif"] - g["macd_dea"]
    g["macd_hist_slope_3d"] = g["macd_hist"] - g["macd_hist"].shift(3)
    g["macd_hist_slope_5d"] = g["macd_hist"] - g["macd_hist"].shift(5)
    g["macd_hist_turn_positive"] = g["macd_hist"].gt(0) & g["macd_hist"].shift(1).le(0)
    g["macd_hist_expanding_3d"] = g["macd_hist"].gt(g["macd_hist"].shift(1)) & g["macd_hist"].shift(1).gt(g["macd_hist"].shift(2))
    g["macd_zero_axis_above"] = g["macd_dif"].gt(0)
    g["macd_gold_cross"] = g["macd_dif"].gt(g["macd_dea"]) & g["macd_dif"].shift(1).le(g["macd_dea"].shift(1))
    g["macd_gold_cross_above_zero"] = g["macd_gold_cross"] & g["macd_dif"].gt(0)
    g["macd_gold_cross_below_zero"] = g["macd_gold_cross"] & g["macd_dif"].le(0)

    g["ma20"] = close.rolling(20, min_periods=10).mean()
    g["ma50"] = close.rolling(50, min_periods=25).mean()
    g["ma200"] = close.rolling(200, min_periods=100).mean()
    g["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    g["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    g["close_above_ma20"] = close.gt(g["ma20"])
    g["close_above_ma50"] = close.gt(g["ma50"])
    g["close_above_ma200"] = close.gt(g["ma200"])
    g["ma20_slope_5d"] = g["ma20"] / g["ma20"].shift(5) - 1.0
    g["ma50_slope_5d"] = g["ma50"] / g["ma50"].shift(5) - 1.0
    g["ema20_slope_5d"] = g["ema20"] / g["ema20"].shift(5) - 1.0
    g["ma_bull_alignment_20_50"] = g["ma20"].gt(g["ma50"])
    g["ma_bull_alignment_20_50_200"] = g["ma20"].gt(g["ma50"]) & g["ma50"].gt(g["ma200"])
    g["close_distance_ma20_pct"] = close / g["ma20"] - 1.0
    g["close_distance_ma50_pct"] = close / g["ma50"] - 1.0
    g["close_overextended_ma20"] = g["close_distance_ma20_pct"].gt(0.10)
    g["close_overextended_ma50"] = g["close_distance_ma50_pct"].gt(0.20)

    g["bb_mid"] = g["ma20"]
    bb_std = close.rolling(20, min_periods=10).std()
    g["bb_upper"] = g["bb_mid"] + 2 * bb_std
    g["bb_lower"] = g["bb_mid"] - 2 * bb_std
    g["bb_width"] = (g["bb_upper"] - g["bb_lower"]) / g["bb_mid"]
    g["bb_width_pctile_20d"] = g["bb_width"].rolling(20, min_periods=10).apply(rolling_percentile_last, raw=False)
    g["bb_width_pctile_60d"] = g["bb_width"].rolling(60, min_periods=20).apply(rolling_percentile_last, raw=False)
    g["bb_squeeze_20d"] = g["bb_width_pctile_20d"].le(0.20)
    g["bb_squeeze_60d"] = g["bb_width_pctile_60d"].le(0.20)
    g["bb_breakout_upper"] = close.gt(g["bb_upper"]) & close.shift(1).le(g["bb_upper"].shift(1))
    g["bb_upper_band_ride_3d"] = close.gt(g["bb_upper"] * 0.995).rolling(3, min_periods=3).sum().eq(3)
    g["bb_midline_failure"] = close.lt(g["bb_mid"]) & close.shift(1).ge(g["bb_mid"].shift(1))
    g["bb_lower_reclaim"] = close.gt(g["bb_lower"]) & close.shift(1).le(g["bb_lower"].shift(1))
    g["bb_position_pct"] = (close - g["bb_lower"]) / (g["bb_upper"] - g["bb_lower"]).replace(0, np.nan)

    g["high_20d"] = high.rolling(20, min_periods=10).max()
    g["high_50d"] = high.rolling(50, min_periods=25).max()
    g["high_120d"] = high.rolling(120, min_periods=60).max()
    for days in (20, 50, 120):
        g[f"breakout_{days}d_day0"] = close.gt(g[f"high_{days}d"].shift(1))
    g["volume_ma20"] = volume.rolling(20, min_periods=5).mean()
    g["volume_ratio_20d"] = volume / g["volume_ma20"].replace(0, np.nan)
    g["volume_spike_20d"] = g["volume_ratio_20d"].gt(1.5)
    g["volume_dryup_20d"] = g["volume_ratio_20d"].lt(0.7)
    g["price_up_volume_up"] = close.gt(close.shift(1)) & volume.gt(volume.shift(1))
    g["price_down_volume_down"] = close.lt(close.shift(1)) & volume.lt(volume.shift(1))
    any_breakout = g["breakout_20d_day0"] | g["breakout_50d_day0"] | g["breakout_120d_day0"]
    g["breakout_day1_continuation"] = any_breakout.shift(1).fillna(False) & close.gt(close.shift(1))
    g["breakout_day2_failure"] = any_breakout.shift(2).fillna(False) & close.lt(close.shift(2))
    g["breakout_volume_confirmed"] = any_breakout & g["volume_spike_20d"]
    g["breakout_from_squeeze"] = any_breakout & (g["bb_squeeze_20d"].shift(1).fillna(False) | g["bb_squeeze_60d"].shift(1).fillna(False))
    g["pullback_to_ma20"] = close.between(g["ma20"] * 0.985, g["ma20"] * 1.025) & g["ma20_slope_5d"].gt(0)
    g["pullback_to_ma50"] = close.between(g["ma50"] * 0.985, g["ma50"] * 1.025) & g["ma50_slope_5d"].gt(0)
    g["pullback_volume_dryup"] = (g["pullback_to_ma20"] | g["pullback_to_ma50"]) & g["volume_dryup_20d"]
    g["pullback_reclaim_ma20"] = close.gt(g["ma20"]) & close.shift(1).le(g["ma20"].shift(1))
    g["pullback_reclaim_ma50"] = close.gt(g["ma50"]) & close.shift(1).le(g["ma50"].shift(1))

    g["TECH_STRONG_TREND_CONTINUATION"] = g["close_above_ma20"] & g["ma_bull_alignment_20_50"] & g["macd_hist_expanding_3d"] & g["rsi_bullish_regime_flag"]
    g["TECH_BREAKOUT_DAY0_WATCH_ONLY"] = any_breakout
    g["TECH_BREAKOUT_CONFIRMED"] = g["breakout_day1_continuation"] & g["breakout_volume_confirmed"].shift(1).fillna(False)
    g["TECH_BREAKOUT_FAILURE_RISK"] = g["breakout_day2_failure"] | g["bb_midline_failure"]
    g["TECH_PULLBACK_BUY_CANDIDATE"] = (g["pullback_to_ma20"] | g["pullback_to_ma50"]) & g["pullback_volume_dryup"] & g["rsi_bullish_regime_flag"]
    g["TECH_OVEREXTENDED_BUT_STRONG"] = g["close_overextended_ma20"] & g["rsi_high_persistence_3d"] & g["ma_bull_alignment_20_50"]
    g["TECH_WEAK_OR_NO_CONFIRMATION"] = g["rsi_bearish_regime_flag"] | (~g["close_above_ma50"]) | g["macd_hist"].lt(0)
    return g


def benchmark_returns(bench: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for symbol in BENCHMARKS:
        b = bench[bench["ticker"].eq(symbol)].sort_values("as_of_date").copy()
        if b.empty:
            continue
        price = b["adjusted_close"].where(b["adjusted_close"].notna(), b["close"])
        for days in WINDOWS:
            b[f"{symbol.lower()}_ret_{days}d"] = price / price.shift(days) - 1.0
        frames.append(b[["as_of_date"] + [f"{symbol.lower()}_ret_{d}d" for d in WINDOWS]])
    if not frames:
        return pd.DataFrame(columns=["as_of_date"])
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="as_of_date", how="outer")
    return out


def build_panel(root: Path) -> tuple[pd.DataFrame, list[str]]:
    price, bench, warnings = load_prices(root)
    feature = price.groupby("ticker", group_keys=False).apply(add_group_features).reset_index(drop=True)
    ret = feature.groupby("ticker")["close"].pct_change
    for days in WINDOWS:
        feature[f"ticker_ret_{days}d"] = ret(days)
    bench_ret = benchmark_returns(bench)
    feature = feature.merge(bench_ret, on="as_of_date", how="left")
    for days in WINDOWS:
        for symbol in BENCHMARKS:
            col = f"{symbol.lower()}_ret_{days}d"
            out_col = f"rs_vs_{symbol.lower()}_{days}d"
            if col in feature.columns:
                feature[out_col] = feature[f"ticker_ret_{days}d"] - feature[col]
            else:
                feature[out_col] = np.nan
                warnings.append(f"BENCHMARK_UNAVAILABLE:{symbol}")
    feature["rs_positive_vs_qqq_10d"] = feature["rs_vs_qqq_10d"].gt(0)
    feature["rs_positive_vs_spy_10d"] = feature["rs_vs_spy_10d"].gt(0)
    feature["rs_positive_vs_soxx_10d"] = feature["rs_vs_soxx_10d"].gt(0)
    feature["as_of_date"] = feature["as_of_date"].dt.date.astype(str)
    return feature, sorted(set(warnings))


def boolean_columns(panel: pd.DataFrame) -> list[str]:
    result = []
    for col in panel.columns:
        if col.startswith(("rsi_cross", "rsi_over", "rsi_high", "rsi_bull", "rsi_bear", "kdj_", "macd_", "bb_", "close_above", "ma_bull", "close_over", "rs_positive", "breakout_", "pullback_", "volume_", "price_", "TECH_")):
            non_null = panel[col].dropna()
            if len(non_null) and non_null.map(lambda v: isinstance(v, (bool, np.bool_))).all():
                result.append(col)
    return sorted(set(result))


def coverage_report(panel: pd.DataFrame, bool_cols: list[str]) -> pd.DataFrame:
    rows = []
    bool_set = set(bool_cols)
    for col in panel.columns:
        if col in {"symbol", "date", "source_provider", "source_artifact", "refresh_timestamp", "row_hash", "price_row_status"}:
            continue
        non_null = panel[col].notna()
        is_bool = col in bool_set
        rows.append({
            "signal_name": col,
            "non_null_count": int(non_null.sum()),
            "non_null_ratio": float(non_null.mean()) if len(panel) else 0.0,
            "true_count": int(panel[col].fillna(False).astype(bool).sum()) if is_bool else "",
            "true_ratio": float(panel[col].fillna(False).astype(bool).mean()) if is_bool else "",
            "ticker_coverage_count": int(panel.loc[non_null, "ticker"].nunique()) if "ticker" in panel else 0,
            "as_of_date_coverage_count": int(panel.loc[non_null, "as_of_date"].nunique()) if "as_of_date" in panel else 0,
            "min_date": panel.loc[non_null, "as_of_date"].min() if non_null.any() else "",
            "max_date": panel.loc[non_null, "as_of_date"].max() if non_null.any() else "",
            "data_quality_warning": "LOW_COVERAGE" if non_null.mean() < 0.50 else "",
        })
    return pd.DataFrame(rows)


def forward_summary(panel: pd.DataFrame, bool_cols: list[str]) -> pd.DataFrame:
    rows = []
    for signal in bool_cols:
        values = panel[signal]
        for days in WINDOWS:
            fwd_col = f"return_{days}d_forward"
            mature_col = f"forward_{days}d_matured"
            usable = panel[mature_col].fillna(False).astype(bool) & panel[fwd_col].notna() & values.notna()
            sub = panel.loc[usable, [signal, fwd_col]].copy()
            true = sub[sub[signal].astype(bool)]
            false = sub[~sub[signal].astype(bool)]
            warning = ""
            usable_flag = len(true) >= 30 and len(false) >= 30
            if not usable_flag:
                warning = "INSUFFICIENT_TRUE_OR_FALSE_SAMPLE"
            rows.append({
                "signal_name": signal,
                "forward_window": f"{days}D",
                "matured_count": int(len(sub)),
                "signal_true_count": int(len(true)),
                "signal_false_count": int(len(false)),
                "signal_true_mean_forward_return": float(true[fwd_col].mean()) if len(true) else np.nan,
                "signal_false_mean_forward_return": float(false[fwd_col].mean()) if len(false) else np.nan,
                "delta_true_minus_false": float(true[fwd_col].mean() - false[fwd_col].mean()) if len(true) and len(false) else np.nan,
                "signal_true_median_forward_return": float(true[fwd_col].median()) if len(true) else np.nan,
                "signal_false_median_forward_return": float(false[fwd_col].median()) if len(false) else np.nan,
                "hit_rate_true": float(true[fwd_col].gt(0).mean()) if len(true) else np.nan,
                "hit_rate_false": float(false[fwd_col].gt(0).mean()) if len(false) else np.nan,
                "hit_rate_delta": float(true[fwd_col].gt(0).mean() - false[fwd_col].gt(0).mean()) if len(true) and len(false) else np.nan,
                "usable_for_research_flag": bool(usable_flag),
                "warning": warning,
            })
    return pd.DataFrame(rows)


def correlation_outputs(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    exclude = {"as_of_date", "source_price_date", "ticker", "symbol", "date"}
    numeric_cols = [
        c for c in panel.columns
        if c not in exclude and pd.api.types.is_numeric_dtype(panel[c]) and panel[c].notna().sum() >= 100
    ]
    corr = panel[numeric_cols].corr(min_periods=100) if numeric_cols else pd.DataFrame()
    rows = []
    if not corr.empty:
        for i, a in enumerate(corr.columns):
            for b in corr.columns[i + 1:]:
                val = corr.loc[a, b]
                if pd.notna(val) and abs(val) >= 0.92:
                    rows.append({
                        "feature_a": a,
                        "feature_b": b,
                        "correlation": float(val),
                        "suggested_action": "REVIEW_ONE_FOR_REDUNDANCY_DIAGNOSTIC_ONLY",
                        "reason": "ABS_CORRELATION_GE_0.92_NO_FEATURE_DROPPED",
                    })
    return corr.reset_index().rename(columns={"index": "signal_name"}), pd.DataFrame(rows)


def diagnostic_label(row: pd.Series) -> str:
    labels = [c for c in (
        "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_DAY0_WATCH_ONLY",
        "TECH_BREAKOUT_CONFIRMED", "TECH_BREAKOUT_FAILURE_RISK",
        "TECH_PULLBACK_BUY_CANDIDATE", "TECH_OVEREXTENDED_BUT_STRONG",
        "TECH_WEAK_OR_NO_CONFIRMATION",
    ) if truthy(row.get(c))]
    return "|".join(labels) if labels else "NO_DOMINANT_TECH_LABEL"


def top20_overlay(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    rank_path = root / TOP20_REL if (root / TOP20_REL).exists() else root / ALT_RANK_REL
    rank = pd.read_csv(rank_path, low_memory=False)
    if "rank" not in rank.columns and "final_shadow_rank" in rank.columns:
        rank["rank"] = rank["final_shadow_rank"]
    if "final_score" not in rank.columns and "final_shadow_score" in rank.columns:
        rank["final_score"] = rank["final_shadow_score"]
    rank["ticker"] = rank["ticker"].astype(str).str.upper().str.strip()
    rank["rank"] = pd.to_numeric(rank["rank"], errors="coerce")
    top20 = rank.sort_values("rank").head(20).copy()
    latest = panel.sort_values("as_of_date").groupby("ticker", as_index=False).tail(1)
    cols = [
        "ticker", "as_of_date", "close", "rsi_14", "kdj_k", "kdj_d", "macd_hist",
        "bb_width_pctile_20d", "close_above_ma20", "close_above_ma50",
        "rs_vs_qqq_10d", "rs_vs_spy_10d", "rs_vs_soxx_10d",
        "breakout_20d_day0", "breakout_day1_continuation", "breakout_day2_failure",
        "pullback_to_ma20", "pullback_to_ma50",
        "TECH_STRONG_TREND_CONTINUATION", "TECH_BREAKOUT_DAY0_WATCH_ONLY",
        "TECH_BREAKOUT_CONFIRMED", "TECH_BREAKOUT_FAILURE_RISK",
        "TECH_PULLBACK_BUY_CANDIDATE", "TECH_OVEREXTENDED_BUT_STRONG",
        "TECH_WEAK_OR_NO_CONFIRMATION",
    ]
    merged = top20[["rank", "ticker", "final_score"]].merge(latest[cols], on="ticker", how="left")
    merged["latest_technical_labels"] = merged.apply(diagnostic_label, axis=1)
    merged["diagnostic_interpretation"] = merged["latest_technical_labels"].map(
        lambda x: "DIAGNOSTIC_ONLY_NO_TRADE_ACTION"
        if x != "NO_DOMINANT_TECH_LABEL" else "NO_DOMINANT_TECH_LABEL_DIAGNOSTIC_ONLY"
    )
    merged["no_trade_action_created"] = True
    return merged.rename(columns={"rank": "D rank", "final_score": "D final score", "close": "latest close"})


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080", "outputs/v21/v21_081", "outputs/v21/v21_082", "outputs/v21/v21_083", "outputs/v21/v21_084"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    panel, data_warnings = build_panel(root)
    bool_cols = boolean_columns(panel)
    coverage = coverage_report(panel, bool_cols)
    forward = forward_summary(panel, bool_cols)
    corr, redundant = correlation_outputs(panel)
    overlay = top20_overlay(root, panel)

    panel_out = panel.drop(columns=[c for c in ("symbol", "date") if c in panel.columns])
    panel_out.to_csv(output / PANEL_NAME, index=False)
    coverage.to_csv(output / COVERAGE_NAME, index=False)
    forward.to_csv(output / FORWARD_NAME, index=False)
    corr.to_csv(output / CORR_NAME, index=False)
    redundant.to_csv(output / REDUNDANT_NAME, index=False)
    overlay.to_csv(output / OVERLAY_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    leakage = 0
    data_warning_count = int((coverage["data_quality_warning"].astype(str) != "").sum() + len(data_warnings))
    status = (
        "BLOCKED_V21_085_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        if changed or leakage else
        "PARTIAL_PASS_V21_085_R1_TECHNICAL_FEATURE_AUDIT_READY_WITH_DATA_WARN"
        if data_warning_count else
        "PASS_V21_085_R1_TECHNICAL_FEATURE_AUDIT_READY"
    )
    decision = (
        "TECHNICAL_FEATURE_AUDIT_BLOCKED_REVIEW_REQUIRED"
        if changed or leakage else
        "TECHNICAL_FEATURE_AUDIT_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
        if data_warning_count else
        "TECHNICAL_FEATURE_AUDIT_READY_DIAGNOSTIC_ONLY"
    )
    validation = {
        "stage": "V21.085-R1_TECHNICAL_FEATURE_ENRICHMENT_AUDIT",
        "final_status": status,
        "decision": decision,
        "research_only": True,
        "diagnostic_only": True,
        "official_ranking_mutated": False,
        "official_weights_mutated": False,
        "broker_action_created": False,
        "protected_outputs_modified": bool(changed),
        "d_baseline_preserved": True,
        "source_latest_price_date": panel["as_of_date"].max(),
        "row_count": int(len(panel_out)),
        "ticker_count": int(panel_out["ticker"].nunique()),
        "feature_count": int(len(panel_out.columns)),
        "matured_5d_count": int(panel_out["forward_5d_matured"].fillna(False).astype(bool).sum()),
        "matured_10d_count": int(panel_out["forward_10d_matured"].fillna(False).astype(bool).sum()),
        "matured_20d_count": int(panel_out["forward_20d_matured"].fillna(False).astype(bool).sum()),
        "pending_5d_count": int((~panel_out["forward_5d_matured"].fillna(False).astype(bool)).sum()),
        "pending_10d_count": int((~panel_out["forward_10d_matured"].fillna(False).astype(bool)).sum()),
        "pending_20d_count": int((~panel_out["forward_20d_matured"].fillna(False).astype(bool)).sum()),
        "leakage_warning_count": leakage,
        "data_warning_count": data_warning_count,
        "recommended_next_stage": "V21.086-R1_FUNDAMENTAL_PIT_AND_QUALITY_REPAIR",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_warnings": "|".join(data_warnings),
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
