from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v22" / "ABCDE_PRICE_PROXY_LONG_HORIZON_RESEARCH_R1"
POINTER = ROOT / "outputs" / "v21" / "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD" / "canonical_snapshot_pointer.json"
STRICT_OUT = ROOT / "outputs" / "v22" / "ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R1"
STATUS = "PASS_PRICE_PROXY_LONG_HORIZON_RESEARCH_ONLY"
STRICT_STATUS = "FAIL_DATA_NOT_SUFFICIENT_FOR_LONG_HORIZON"
LABELS = {
    "original_abcde_flag": "NOT_ORIGINAL_ABCDE",
    "universe_bias_flag": "CURRENT_UNIVERSE_SURVIVORSHIP_BIASED",
    "proxy_type_flag": "PRICE_ONLY_OR_PRICE_DOMINANT_PROXY",
    "research_flag": "RESEARCH_ONLY",
    "trading_approval_flag": "NOT_APPROVED_FOR_TRADING",
}
SOURCE_ABCD = "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
SOURCE_E = "scripts/v21/v21_133_e_conservative_adaptive_momentum_r1.py"
SOURCE_FAMILY = "scripts/v21/v21_255_detailed_strategy_backtest_factor_weight_comparison.py"
WINDOWS = [20, 60, 120, 252, 504]
RANDOM_SEED = 20260714
COSTS = [0.0, 5.0, 10.0, 20.0]
PROXY_STRATEGIES = ["A1_PRICE_PROXY", "B_PRICE_PROXY", "C_PRICE_PROXY", "D_PRICE_PROXY", "E_PRICE_PROXY"]
FAMILY_WEIGHTS = {
    "A1": {"Fundamental": .15, "Technical": .34, "Strategy": .18, "Risk": .18, "Market Regime": .10, "Data Trust": .05},
    "B": {"Fundamental": .10, "Technical": .45, "Strategy": .20, "Risk": .10, "Market Regime": .10, "Data Trust": .05},
    "C": {"Fundamental": .12, "Technical": .42, "Strategy": .21, "Risk": .10, "Market Regime": .10, "Data Trust": .05},
    "D": {"Fundamental": .10, "Technical": .50, "Strategy": .22, "Risk": .03, "Market Regime": .10, "Data Trust": .05},
    "E_R1": {"Fundamental": .12, "Technical": .30, "Strategy": .18, "Risk": .25, "Market Regime": .10, "Data Trust": .05},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_paths() -> list[Path]:
    result: list[Path] = []
    for pattern in ["scripts/v22/*22_040*", "scripts/v22/*22_044*", "scripts/v22/*22_047*", "scripts/**/*daily*", "outputs/v22/V22.040*/*", "outputs/v22/V22.044*/*", "outputs/v22/V22.047*/*"]:
        result.extend(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted(set(result))


def hash_manifest(paths: Iterable[Path]) -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths}


def factor_audit() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(strategy: str, factor: str, required: str, available: bool, rebuildable: bool,
            original_weight: Any, action: str, proxy_weight: Any, reason: str, source: str,
            classification: str = "PARTIALLY_REBUILDABLE_PRICE_PROXY") -> None:
        rows.append({
            "strategy": strategy, "classification": classification, "factor": factor,
            "required_input": required, "historical_input_available": available,
            "rebuildable_from_price_only": rebuildable, "original_weight": original_weight,
            "proxy_action": action, "proxy_weight": proxy_weight, "reason": reason,
            "source_code": source, **LABELS,
        })

    for strategy in ["A1", "B", "C", "D"]:
        for family, weight in FAMILY_WEIGHTS[strategy].items():
            price_capable = family in {"Technical", "Market Regime"}
            add(strategy, f"STRICT_FAMILY::{family}",
                "historical OHLCV" if price_capable else "historical PIT fundamentals/strategy/risk/trust inputs",
                price_capable, price_capable, weight,
                "MAPPED_TO_VERSIONED_PRICE_PROXY" if price_capable else "EXCLUDED_NO_BACKFILL",
                "SEE_PRICE_PROXY_CONTRACT" if price_capable else 0.0,
                "Family weight documents the original full-family strategy; missing families are not imputed.", SOURCE_FAMILY)
        tech = {
            "rsi14_position": .12, "ma20_ma50_trend": .18, "macd_histogram": .14,
            "bollinger_position": .10, "volume_ratio_20d": .08, "volatility_20d": .10,
            "breakout_63d": .14, "pullback_from_20d_high": .14,
        }
        momentum = {
            "absolute_momentum_63d": .35, "relative_momentum_63d_vs_QQQ": .30,
            "momentum_acceleration_20d_vs_63d": .20, "trend_persistence_ma20_ma50": .10,
            "rsi_exhaustion_guard": .05,
        }
        blend = {"A1": "technical=1.00,momentum=0.00", "B": "technical=0.80,momentum=0.20",
                 "C": "technical=0.75/0.85/0.95,momentum=0.25/0.15/0.05 by QQQ PIT regime",
                 "D": "technical=0.60,momentum=0.40"}[strategy]
        add(strategy, "PRICE_PROXY_BLEND", "raw OHLCV through signal close; QQQ through signal close", True, True,
            "VERSIONED_V21.114_PROXY_DEFINITION", "APPLY_VERSIONED_PRICE_PROXY", "1.0",
            f"Applied blend: {blend}.", SOURCE_ABCD)
        tech_scale = {"A1": 1.0, "B": .8, "C": "0.75/0.85/0.95", "D": .6}[strategy]
        mom_scale = {"A1": 0.0, "B": .2, "C": "0.25/0.15/0.05", "D": .4}[strategy]
        for factor, weight in tech.items():
            add(strategy, factor, "raw close/high/low/volume history", True, True, weight,
                "REBUILD_EXACT_PRICE_FORMULA_ON_RAW_PANEL", f"{weight} * technical_blend({tech_scale})",
                "Cross-sectional ranks are computed independently on each signal date.", SOURCE_ABCD)
        for factor, weight in momentum.items():
            add(strategy, factor, "raw close history and QQQ history", True, True, weight,
                "REBUILD_EXACT_PRICE_FORMULA_ON_RAW_PANEL", f"{weight} * momentum_blend({mom_scale})",
                "No full-sample normalization; QQQ regime is contemporaneous only.", SOURCE_ABCD)

    for family, weight in FAMILY_WEIGHTS["E_R1"].items():
        price_capable = family in {"Technical", "Market Regime"}
        add("E_R1", f"STRICT_FAMILY::{family}",
            "historical OHLCV" if price_capable else "historical PIT fundamentals/strategy/risk/trust inputs",
            price_capable, price_capable, weight,
            "MAPPED_TO_E_PRICE_OVERLAYS" if price_capable else "EXCLUDED_NO_BACKFILL", 0.0 if not price_capable else "SEE_E_PROXY",
            "Original E_R1 full-family input is unavailable historically and is never fabricated.", SOURCE_FAMILY)
    e_components = [
        ("A1_baseline_anchor", "A1 price-proxy score", True, .80, .80 / .97, "REPLACE_UNAVAILABLE_HISTORICAL_A1_SCORE_WITH_EXPLICIT_A1_PRICE_PROXY"),
        ("context_relative_strength_vs_QQQ_SOXX", "raw close 60d", True, .12 * .35, .12 * .35 / .97, "REBUILD"),
        ("context_price_momentum_20d_60d", "raw close 20d/60d", True, .12 * .30, .12 * .30 / .97, "REBUILD"),
        ("context_volume_confirmed_momentum", "raw close and volume 20d/60d", True, .12 * .15, .12 * .15 / .97, "REBUILD"),
        ("context_pullback_after_strength", "raw close 1d/20d/60d", True, .12 * .10, .12 * .10 / .97, "REBUILD"),
        ("context_breakout_follow_through", "raw close and prior rolling high", True, .12 * .10, .12 * .10 / .97, "REBUILD"),
        ("technical_RSI_KDJ_MACD_Bollinger_MA_EMA_volume", "raw OHLCV 14d/20d/50d", True, .04, .04 / .97, "REBUILD"),
        ("risk_left_tail_252d", "raw close trailing 252 observations", True, .04 * .25, .04 * .25 / .97, "REBUILD"),
        ("risk_repeated_loser_avoidance", "historical forward-outcome diagnostic", False, .04 * .30, 0.0, "EXCLUDED_NO_BACKFILL"),
        ("risk_concentration_avoidance", "historical PIT sector/industry membership", False, .04 * .25, 0.0, "EXCLUDED_NO_BACKFILL"),
        ("risk_data_quality_maturity", "historical run-quality metadata", False, .04 * .20, 0.0, "EXCLUDED_NO_BACKFILL"),
    ]
    for factor, req, avail, ow, pw, action in e_components:
        add("E_R1", factor, req, avail, avail, ow, action, pw,
            "Available price contributions total 0.97 and are explicitly renormalized; excluded 0.03 is not imputed.", SOURCE_E)
    return pd.DataFrame(rows)


def write_audit_phase() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "strategy_factor_rebuildability.csv").exists():
        raise FileExistsError("Audit artifact already exists; refusing to overwrite it.")
    audit = factor_audit()
    audit.to_csv(OUT / "strategy_factor_rebuildability.csv", index=False)
    manifest = hash_manifest(protected_paths())
    (OUT / "protected_files_before.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    classifications = audit.groupby("strategy")["classification"].first().to_dict()
    payload = {
        "phase": "FACTOR_REBUILDABILITY_AUDIT_COMPLETE_BACKTEST_NOT_STARTED",
        "strict_abcde_status_unchanged": STRICT_STATUS,
        "proxy_branch_target_status": STATUS,
        "strategy_classifications": classifications,
        "proxy_strategies_authorized_by_audit": PROXY_STRATEGIES,
        "labels": LABELS,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "audit_phase_status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return payload


def load_raw_prices() -> tuple[pd.DataFrame, dict[str, Any]]:
    pointer = json.loads(POINTER.read_text(encoding="utf-8"))
    path = Path(pointer["canonical_raw_path"])
    use = ["ticker", "date", "open", "high", "low", "close", "volume", "adjustment", "snapshot_id"]
    frame = pd.read_csv(path, usecols=use, low_memory=False)
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame[frame["date"].between("2019-01-02", "2026-07-13")].sort_values(["ticker", "date"]).reset_index(drop=True)
    duplicate_count = int(frame.duplicated(["ticker", "date"]).sum())
    if duplicate_count:
        raise ValueError(f"Duplicate ticker/date rows: {duplicate_count}")
    if not {"QQQ", "SPY"}.issubset(set(frame["ticker"])):
        raise ValueError("QQQ or SPY missing from canonical raw price panel")
    inventory = {
        "canonical_raw_path": str(path), "source_snapshot_id": pointer.get("snapshot_id", ""),
        "price_start": frame["date"].min().strftime("%Y-%m-%d"),
        "price_end": frame["date"].max().strftime("%Y-%m-%d"),
        "row_count": len(frame), "ticker_count": int(frame["ticker"].nunique()),
        "duplicate_ticker_date_rows": duplicate_count,
        "missing_rate": {c: float(frame[c].isna().mean()) for c in ["open", "high", "low", "close", "volume"]},
        "price_basis": "RAW_UNADJUSTED_ONLY_TO_AVOID_CURRENT_QFQ_SNAPSHOT_LOOKAHEAD",
        "corporate_action_limit": "DIVIDENDS_AND_SPLITS_NOT_RECONSTRUCTED; RAW_PRICE_JUMPS_CAN_DISTORT_SIGNALS_AND_RETURNS",
        "universe": "CURRENT_UNIVERSE_SURVIVORSHIP_BIASED_PROXY",
        "candidate_rule": "CURRENT_326_SYMBOL_PANEL_EXCLUDING_FORMAL_BENCHMARKS_QQQ_AND_SPY",
        "labels": LABELS,
    }
    return frame, inventory


def roll(s: pd.Series, window: int, op: str) -> pd.Series:
    grouped = s.groupby(level=0, sort=False)
    obj = grouped.rolling(window, min_periods=window)
    out = getattr(obj, op)().reset_index(level=0, drop=True)
    return out.reindex(s.index)


def trailing_max_drawdown(values: np.ndarray, window: int = 252) -> np.ndarray:
    result = np.full(len(values), np.nan)
    if len(values) < window:
        return result
    windows = np.lib.stride_tricks.sliding_window_view(values, window)
    peaks = np.maximum.accumulate(windows, axis=1)
    result[window - 1:] = np.nanmin(windows / peaks - 1.0, axis=1)
    return result


def pct_rank_by_date(frame: pd.DataFrame, column: str, ascending: bool = True) -> pd.Series:
    return frame.groupby("date", sort=False)[column].rank(method="average", pct=True, ascending=ascending) * 100.0


def score_rsi(values: pd.Series) -> pd.Series:
    return np.select(
        [values.between(45, 65), values.between(35, 75), values.between(25, 85)],
        [85.0, 70.0, 50.0], default=25.0,
    )


def score_stochastic(k: pd.Series, d: pd.Series) -> pd.Series:
    return np.select(
        [(k >= d) & k.between(40, 80), (k >= d) & (k < 40), (k >= d) & (k > 80), k >= d],
        [85.0, 75.0, 60.0, 65.0], default=35.0,
    )


def score_bollinger(close: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    mid = (upper + lower) / 2.0
    width = (upper - lower).replace(0, np.nan)
    position = (close - lower) / width
    return np.select(
        [position.between(.45, .80), position.between(.25, 1.0), position.between(0, 1)],
        [85.0, 70.0, 50.0], default=30.0,
    )


def compute_features_and_rankings(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    f = prices.copy().sort_values(["ticker", "date"]).reset_index(drop=True)
    g = f.groupby("ticker", sort=False)
    f["obs_count"] = g.cumcount() + 1
    f["ret1"] = g["close"].pct_change(1, fill_method=None)
    for n in [5, 20, 60, 63, 126]:
        f[f"ret{n}"] = g["close"].pct_change(n, fill_method=None)
    f["volatility20"] = g["ret1"].transform(lambda x: x.rolling(20, min_periods=20).std()) * math.sqrt(252)
    for n in [20, 50]:
        f[f"ma{n}"] = g["close"].transform(lambda x, n=n: x.rolling(n, min_periods=n).mean())
    f["ema12"] = g["close"].transform(lambda x: x.ewm(span=12, adjust=False).mean())
    f["ema20"] = g["close"].transform(lambda x: x.ewm(span=20, adjust=False).mean())
    f["ema26"] = g["close"].transform(lambda x: x.ewm(span=26, adjust=False).mean())
    f["macd"] = f["ema12"] - f["ema26"]
    f["macd_signal"] = f.groupby("ticker")["macd"].transform(lambda x: x.ewm(span=9, adjust=False).mean())
    f["macd_hist"] = f["macd"] - f["macd_signal"]
    f["macd_direction"] = f.groupby("ticker")["macd_hist"].diff()
    delta = g["close"].diff()
    gain = delta.clip(lower=0).groupby(f["ticker"]).transform(lambda x: x.rolling(14, min_periods=14).mean())
    loss = (-delta.clip(upper=0)).groupby(f["ticker"]).transform(lambda x: x.rolling(14, min_periods=14).mean())
    f["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    low9 = g["low"].transform(lambda x: x.rolling(9, min_periods=9).min())
    high9 = g["high"].transform(lambda x: x.rolling(9, min_periods=9).max())
    f["kdj_k9"] = (f["close"] - low9) / (high9 - low9).replace(0, np.nan) * 100
    f["kdj_d9"] = f.groupby("ticker")["kdj_k9"].transform(lambda x: x.rolling(3, min_periods=3).mean())
    low14 = g["low"].transform(lambda x: x.rolling(14, min_periods=14).min())
    high14 = g["high"].transform(lambda x: x.rolling(14, min_periods=14).max())
    f["kdj_k14"] = (f["close"] - low14) / (high14 - low14).replace(0, np.nan) * 100
    f["kdj_d14"] = f.groupby("ticker")["kdj_k14"].transform(lambda x: x.rolling(3, min_periods=3).mean())
    sd20 = g["close"].transform(lambda x: x.rolling(20, min_periods=20).std())
    f["bb_upper"] = f["ma20"] + 2 * sd20
    f["bb_lower"] = f["ma20"] - 2 * sd20
    f["bb_position"] = (f["close"] - f["bb_lower"]) / (f["bb_upper"] - f["bb_lower"]).replace(0, np.nan)
    f["volume_ma20"] = g["volume"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    f["volume_ma60"] = g["volume"].transform(lambda x: x.rolling(60, min_periods=60).mean())
    f["volume_ratio20"] = f["volume"] / f["volume_ma20"].replace(0, np.nan)
    f["volume_ratio20_60"] = f["volume_ma20"] / f["volume_ma60"].replace(0, np.nan)
    high63 = g["high"].transform(lambda x: x.rolling(63, min_periods=63).max())
    high20 = g["high"].transform(lambda x: x.rolling(20, min_periods=20).max())
    prior20 = g["close"].transform(lambda x: x.shift(1).rolling(20, min_periods=20).max())
    f["breakout63"] = f["close"] / high63.replace(0, np.nan) - 1
    f["pullback20"] = f["close"] / high20.replace(0, np.nan) - 1
    f["is_breakout"] = f["close"] > prior20
    f["breakout_follow"] = 0.0
    for _, idx in f.groupby("ticker", sort=False).groups.items():
        positions: list[float] = []
        vals = np.zeros(len(idx), dtype=float)
        part = f.loc[idx]
        for j, row in enumerate(part.itertuples()):
            if bool(row.is_breakout) and pd.notna(prior20.loc[row.Index]):
                positions.append(float(prior20.loc[row.Index]))
            if len(positions) >= 2:
                vals[j] = 1.0 if row.close >= positions[-2] else 0.0
            elif len(positions) == 1:
                vals[j] = 0.0
            else:
                vals[j] = .25 if pd.notna(row.ret20) and row.ret20 > 0 else 0.0
        f.loc[idx, "breakout_follow"] = vals
    for _, idx in f.groupby("ticker", sort=False).groups.items():
        f.loc[idx, "max_drawdown252"] = trailing_max_drawdown(f.loc[idx, "close"].to_numpy(float), 252)

    bench = f[f["ticker"].isin(["QQQ", "SOXX"])][["ticker", "date", "ret60", "ret63", "close", "ma20", "ma50", "ret20"]]
    qqq = bench[bench["ticker"] == "QQQ"].drop(columns="ticker").rename(columns={c: f"qqq_{c}" for c in ["ret60", "ret63", "close", "ma20", "ma50", "ret20"]})
    soxx = bench[bench["ticker"] == "SOXX"][["date", "ret60"]].rename(columns={"ret60": "soxx_ret60"})
    f = f.merge(qqq, on="date", how="left").merge(soxx, on="date", how="left")
    f["relative_strength63"] = f["ret63"] - f["qqq_ret63"]
    f["e_benchmark_ret60"] = f[["qqq_ret60", "soxx_ret60"]].mean(axis=1)
    f["e_relative_strength60"] = f["ret60"] - f["e_benchmark_ret60"]
    candidates = f[~f["ticker"].isin(["QQQ", "SPY"])].copy()

    candidates["rsi_score"] = (100 - (candidates["rsi14"] - 55).abs() * 2).clip(0, 100)
    candidates["trend_score"] = ((candidates["close"] / candidates["ma20"] - 1) * 400 + (candidates["close"] / candidates["ma50"] - 1) * 300 + 50).clip(0, 100)
    candidates["macd_score"] = pct_rank_by_date(candidates, "macd_hist")
    candidates["bb_score"] = (100 - (candidates["bb_position"] - .65).abs() * 130).clip(0, 100)
    candidates["volume_score"] = (candidates["volume_ratio20"] * 50).clip(0, 100)
    candidates["volatility_score"] = 100 - pct_rank_by_date(candidates, "volatility20")
    candidates["breakout_score"] = pct_rank_by_date(candidates, "breakout63")
    candidates["pullback_score"] = ((candidates["pullback20"] + .20) * 350).clip(0, 100)
    candidates["technical_score"] = (.12*candidates.rsi_score + .18*candidates.trend_score + .14*candidates.macd_score + .10*candidates.bb_score + .08*candidates.volume_score + .10*candidates.volatility_score + .14*candidates.breakout_score + .14*candidates.pullback_score)
    candidates["absolute_momentum_score"] = pct_rank_by_date(candidates, "ret63")
    candidates["relative_momentum_score"] = pct_rank_by_date(candidates, "relative_strength63")
    candidates["momentum_acceleration_raw"] = candidates["ret20"] - candidates["ret63"] / 3
    candidates["momentum_acceleration_score"] = pct_rank_by_date(candidates, "momentum_acceleration_raw")
    candidates["trend_persistence_raw"] = (candidates.close > candidates.ma20).astype(float) + (candidates.ma20 > candidates.ma50).astype(float)
    candidates["trend_persistence_score"] = pct_rank_by_date(candidates, "trend_persistence_raw")
    candidates["exhaustion_risk_score"] = 100 - (candidates["rsi14"] - 70).clip(0, 100) * 2
    candidates["momentum_score"] = (.35*candidates.absolute_momentum_score + .30*candidates.relative_momentum_score + .20*candidates.momentum_acceleration_score + .10*candidates.trend_persistence_score + .05*candidates.exhaustion_risk_score)
    candidates["c_momentum_weight"] = np.select(
        [(candidates.qqq_close > candidates.qqq_ma20) & (candidates.qqq_ma20 > candidates.qqq_ma50) & (candidates.qqq_ret20 > 0), candidates.qqq_close < candidates.qqq_ma50],
        [.25, .05], default=.15,
    )
    candidates["A1_PRICE_PROXY"] = candidates.technical_score
    candidates["B_PRICE_PROXY"] = .8*candidates.technical_score + .2*candidates.momentum_score
    candidates["C_PRICE_PROXY"] = (1-candidates.c_momentum_weight)*candidates.technical_score + candidates.c_momentum_weight*candidates.momentum_score
    candidates["D_PRICE_PROXY"] = .6*candidates.technical_score + .4*candidates.momentum_score

    candidates["e_a1_norm"] = pct_rank_by_date(candidates, "A1_PRICE_PROXY")
    candidates["e_price_momentum_raw"] = .45*candidates.ret20 + .55*candidates.ret60
    candidates["e_volume_confirmed_raw"] = np.where(candidates.ret20 > 0, candidates.ret20*candidates.volume_ratio20_60, 0.0)
    candidates["e_pullback_strength_raw"] = np.where(candidates.ret60 > .05, candidates.ret60 - candidates.ret1.clip(lower=0), np.nan)
    for raw, norm in [("e_relative_strength60", "e_rs_norm"), ("e_price_momentum_raw", "e_momentum_norm"), ("e_volume_confirmed_raw", "e_volume_norm"), ("e_pullback_strength_raw", "e_pullback_norm"), ("breakout_follow", "e_breakout_norm")]:
        candidates[norm] = pct_rank_by_date(candidates, raw).fillna(50.0)
    candidates["e_context"] = .35*candidates.e_rs_norm + .30*candidates.e_momentum_norm + .15*candidates.e_volume_norm + .10*candidates.e_pullback_norm + .10*candidates.e_breakout_norm
    candidates["e_rsi"] = score_rsi(candidates.rsi14)
    candidates["e_kdj"] = score_stochastic(candidates.kdj_k14, candidates.kdj_d14)
    candidates["e_macd"] = pct_rank_by_date(candidates, "macd_direction").fillna(50.0)
    candidates["e_bb"] = score_bollinger(candidates.close, candidates.bb_upper, candidates.bb_lower)
    candidates["e_ma_raw"] = ((candidates.close > candidates.ma20).astype(float) + (candidates.close > candidates.ma50).astype(float) + (candidates.close > candidates.ema20).astype(float) + (candidates.volume_ratio20_60 >= .95).astype(float))
    candidates["e_ma"] = candidates.e_ma_raw / 4 * 100
    candidates["e_technical"] = .2*(candidates.e_rsi + candidates.e_kdj + candidates.e_macd + candidates.e_bb + candidates.e_ma)
    candidates["e_left_tail"] = pct_rank_by_date(candidates, "max_drawdown252")
    candidates["E_PRICE_PROXY"] = (.80*candidates.e_a1_norm + .12*candidates.e_context + .04*candidates.e_technical + .01*candidates.e_left_tail) / .97

    abcd_required = ["rsi14", "ma20", "ma50", "macd_hist", "bb_position", "volume_ratio20", "volatility20", "breakout63", "pullback20", "ret63", "relative_strength63", "ret20"]
    e_required = ["E_PRICE_PROXY", "max_drawdown252", "kdj_k14", "kdj_d14"]
    rank_rows: list[pd.DataFrame] = []
    for strategy in PROXY_STRATEGIES:
        req = e_required if strategy == "E_PRICE_PROXY" else abcd_required
        eligible = candidates[candidates[req].notna().all(axis=1)].copy()
        eligible["score"] = eligible[strategy]
        eligible["rank"] = eligible.groupby("date")["score"].rank(method="first", ascending=False)
        eligible = eligible[eligible["rank"] <= 20].copy()
        eligible["strategy"] = strategy
        eligible["signal_date"] = eligible["date"]
        eligible["price_max_date"] = eligible["date"]
        eligible["minimum_history_observations"] = np.where(strategy == "E_PRICE_PROXY", 252, 127)
        eligible["universe_version"] = "CURRENT_UNIVERSE_SURVIVORSHIP_BIASED_PROXY"
        eligible["source_snapshot_id"] = prices["snapshot_id"].iloc[0]
        for k, v in LABELS.items(): eligible[k] = v
        rank_rows.append(eligible[["signal_date", "strategy", "rank", "ticker", "score", "universe_version", "price_max_date", "minimum_history_observations", "source_snapshot_id", *LABELS]])
    rankings = pd.concat(rank_rows, ignore_index=True).sort_values(["signal_date", "strategy", "rank"])
    rankings["rank"] = rankings["rank"].astype(int)
    diag = {
        s: {"first_signal_date": p.signal_date.min().strftime("%Y-%m-%d"), "last_signal_date": p.signal_date.max().strftime("%Y-%m-%d"), "signal_date_count": int(p.signal_date.nunique()), "ranking_ticker_count": int(p.ticker.nunique())}
        for s, p in rankings.groupby("strategy")
    }
    return candidates, rankings, diag


@dataclass
class Slot:
    cash: float = .2
    ticker: str | None = None
    shares: float = 0.0
    pending_exit: bool = False


class BacktestEngine:
    def __init__(self, prices: pd.DataFrame, rankings: pd.DataFrame):
        self.prices = prices
        self.calendar = [pd.Timestamp(x) for x in sorted(prices.loc[prices.ticker == "QQQ", "date"].unique())]
        self.cal_index = {d: i for i, d in enumerate(self.calendar)}
        self.px = {(pd.Timestamp(r.date), str(r.ticker)): (float(r.open), float(r.close)) for r in prices.itertuples() if pd.notna(r.open) and pd.notna(r.close)}
        self.last_close_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for ticker, part in prices.dropna(subset=["close"]).groupby("ticker", sort=False):
            self.last_close_map[str(ticker)] = (part.date.to_numpy("datetime64[ns]"), part.close.to_numpy(float))
        self.orders: dict[str, dict[pd.Timestamp, list[str]]] = {}
        for (strategy, date), part in rankings.groupby(["strategy", "signal_date"], sort=False):
            self.orders.setdefault(str(strategy), {})[pd.Timestamp(date)] = part.sort_values("rank").ticker.astype(str).tolist()

    def price(self, date: pd.Timestamp, ticker: str, field: str) -> float | None:
        pair = self.px.get((pd.Timestamp(date), ticker))
        return None if pair is None else pair[0 if field == "open" else 1]

    def last_close(self, date: pd.Timestamp, ticker: str) -> float | None:
        if ticker not in self.last_close_map: return None
        dates, values = self.last_close_map[ticker]
        pos = int(np.searchsorted(dates, np.datetime64(date), side="left")) - 1
        return float(values[pos]) if pos >= 0 else None

    def valid_execution_dates(self, strategy: str) -> list[pd.Timestamp]:
        signals = self.orders[strategy]
        return [d for i, d in enumerate(self.calendar) if i > 0 and self.calendar[i-1] in signals]

    def simulate(self, strategy: str, mode: str, bps: float, exit_rank: int,
                 start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        valid = self.valid_execution_dates(strategy)
        if not valid: raise ValueError(f"No executable signals for {strategy}")
        start = pd.Timestamp(start or valid[0]); end = pd.Timestamp(end or valid[-1])
        dates = [d for d in self.calendar if start <= d <= end]
        rate = bps / 10000
        policy = f"{strategy}_{'DAILY_TOP5_EQUAL' if mode == 'daily' else f'TOP5_ENTRY_EXIT{exit_rank}_NO_REBAL'}"
        shares: dict[str, float] = {}; cash = 1.0; slots = [Slot() for _ in range(5)]
        trades: list[dict[str, Any]] = []; missing: list[dict[str, Any]] = []; rows: list[dict[str, Any]] = []
        prev_nav = 1.0
        for date in dates:
            i = self.cal_index[date]; signal = self.calendar[i-1] if i > 0 else None
            order = self.orders[strategy].get(signal, []) if signal is not None else []
            turnover = cost = 0.0
            if order and mode == "slots":
                ranks = {t: j+1 for j, t in enumerate(order)}
                for slot_id, slot in enumerate(slots):
                    if slot.ticker and (slot.pending_exit or ranks.get(slot.ticker, 10**9) > exit_rank):
                        op = self.price(date, slot.ticker, "open")
                        if op is None:
                            slot.pending_exit = True
                            missing.append({"policy": policy, "date": date, "ticker": slot.ticker, "action": "SELL_DELAYED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE", "slot_id": slot_id})
                            continue
                        notional = slot.shares * op; fee = notional * rate
                        trades.append({"policy": policy, "signal_date": signal, "execution_date": date, "ticker": slot.ticker, "side": "SELL", "notional": notional, "price": op, "cost": fee, "slot_id": slot_id})
                        slot.cash += notional-fee; turnover += notional; cost += fee
                        slot.ticker = None; slot.shares = 0.0; slot.pending_exit = False
                held = {s.ticker for s in slots if s.ticker}
                candidates = [t for t in order[:5] if t not in held]
                for slot_id, slot in enumerate(slots):
                    if slot.ticker or not candidates: continue
                    ticker = candidates.pop(0); op = self.price(date, ticker, "open")
                    if op is None:
                        missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "BUY_SKIPPED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE", "slot_id": slot_id})
                        continue
                    notional = slot.cash/(1+rate); fee=notional*rate
                    slot.shares=notional/op; slot.cash-=notional+fee; slot.ticker=ticker
                    turnover+=notional; cost+=fee; held.add(ticker)
                    trades.append({"policy": policy, "signal_date": signal, "execution_date": date, "ticker": ticker, "side": "BUY", "notional": notional, "price": op, "cost": fee, "slot_id": slot_id})
            elif order and mode == "daily":
                targets = order[:5]
                opens = {t: self.price(date, t, "open") for t in set(shares)|set(targets)}
                for t in targets:
                    if opens.get(t) is None and t not in shares:
                        missing.append({"policy": policy, "date": date, "ticker": t, "action": "BUY_SKIPPED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE"})
                tradable = [t for t in targets if opens.get(t) is not None]
                locked = sum(q*(self.last_close(date,t) or 0) for t,q in shares.items() if opens.get(t) is None)
                nav_open = cash + locked + sum(q*opens[t] for t,q in shares.items() if opens.get(t) is not None)
                deployable=max(0.0,nav_open-locked); each=deployable/len(tradable) if tradable else 0.0
                for _ in range(8):
                    tv=sum(abs((each if t in tradable else 0)-shares.get(t,0)*opens[t]) for t in opens if opens[t] is not None)
                    each=max(0.0,(deployable-tv*rate)/len(tradable)) if tradable else 0.0
                deltas={t:(each if t in tradable else 0)-shares.get(t,0)*opens[t] for t in opens if opens[t] is not None}
                for side in ["SELL","BUY"]:
                    for t,delta in sorted(deltas.items()):
                        if (side=="SELL" and delta>=-1e-14) or (side=="BUY" and delta<=1e-14): continue
                        notional=abs(delta); fee=notional*rate; qty=notional/opens[t]
                        if side=="SELL": shares[t]=max(0.0,shares.get(t,0)-qty); cash+=notional-fee
                        else: shares[t]=shares.get(t,0)+qty; cash-=notional+fee
                        if shares.get(t,0)<=1e-12: shares.pop(t,None)
                        turnover+=notional; cost+=fee
                        trades.append({"policy":policy,"signal_date":signal,"execution_date":date,"ticker":t,"side":side,"notional":notional,"price":opens[t],"cost":fee,"slot_id":np.nan})
            if mode == "daily":
                nav=cash; exposure=0.0; count=0
                for t,q in shares.items():
                    cp=self.price(date,t,"close")
                    if cp is None: cp=self.last_close(date,t)
                    if cp is not None: nav+=q*cp; exposure+=q*cp; count+=1
            else:
                nav=exposure=0.0; count=0
                for s in slots:
                    nav+=s.cash
                    if s.ticker:
                        cp=self.price(date,s.ticker,"close") or self.last_close(date,s.ticker)
                        if cp is not None: nav+=s.shares*cp; exposure+=s.shares*cp; count+=1
            rows.append({"date":date,"policy":policy,"strategy":strategy,"nav":nav,"daily_return":nav/prev_nav-1,"gross_exposure":exposure/nav if nav else np.nan,"position_count":count,"one_way_turnover":turnover/prev_nav,"transaction_cost":cost,"signal_date":signal if order else pd.NaT,"rank_snapshot_applied":bool(order),"cost_bps":bps,"exit_rank":exit_rank})
            prev_nav=nav
        nav=pd.DataFrame(rows); tr=pd.DataFrame(trades); miss=pd.DataFrame(missing)
        for df in [nav,tr,miss]:
            for k,v in LABELS.items(): df[k]=v
        return nav,tr,miss

    def buy_hold(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp, bps: float=5.0) -> tuple[pd.DataFrame,pd.DataFrame]:
        dates=[d for d in self.calendar if start<=d<=end]; rate=bps/10000
        op=self.price(dates[0],ticker,"open")
        if op is None: raise ValueError(f"{ticker} missing first open")
        notional=1/(1+rate); fee=notional*rate; shares=notional/op; cash=1-notional-fee; prev=1.0; rows=[]
        for j,d in enumerate(dates):
            cp=self.price(d,ticker,"close") or self.last_close(d,ticker)
            nav=cash+shares*cp
            rows.append({"date":d,"policy":f"{ticker}_BUY_HOLD","strategy":ticker,"nav":nav,"daily_return":nav/prev-1,"gross_exposure":shares*cp/nav,"position_count":1,"one_way_turnover":notional if j==0 else 0.0,"transaction_cost":fee if j==0 else 0.0,"signal_date":pd.NaT,"rank_snapshot_applied":False,"cost_bps":bps,"exit_rank":np.nan})
            prev=nav
        nav=pd.DataFrame(rows); tr=pd.DataFrame([{"policy":f"{ticker}_BUY_HOLD","signal_date":pd.NaT,"execution_date":dates[0],"ticker":ticker,"side":"BUY","notional":notional,"price":op,"cost":fee,"slot_id":np.nan}])
        for df in [nav,tr]:
            for k,v in LABELS.items(): df[k]=v
        return nav,tr


def max_drawdown(returns: pd.Series) -> float:
    wealth=(1+returns.fillna(0)).cumprod(); return float((wealth/wealth.cummax()-1).min()) if len(wealth) else np.nan


def longest_underwater(returns: pd.Series) -> int:
    wealth=(1+returns.fillna(0)).cumprod(); under=wealth<wealth.cummax(); best=run=0
    for x in under: run=run+1 if x else 0; best=max(best,run)
    return best


def wilson(success: int, total: int, z: float=1.95996398454) -> tuple[float,float]:
    if total<=0:return np.nan,np.nan
    p=success/total; den=1+z*z/total; center=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return center-half,center+half


def newey_west_t(values: pd.Series) -> float:
    x=pd.to_numeric(values,errors="coerce").dropna().to_numpy(float); n=len(x)
    if n<3:return np.nan
    u=x-x.mean(); lag=max(1,int(math.floor(4*(n/100)**(2/9)))); lv=float(u@u/n)
    for j in range(1,min(lag,n-1)+1): lv+=2*(1-j/(lag+1))*float(u[j:]@u[:-j]/n)
    se=math.sqrt(max(lv,0)/n); return float(x.mean()/se) if se else np.nan


def bootstrap_ci(values: Iterable[float], seed: int=RANDOM_SEED, draws: int=2000, statistic: str="mean") -> tuple[float,float]:
    x=np.asarray(list(values),float); x=x[np.isfinite(x)]
    if not len(x):return np.nan,np.nan
    rng=np.random.default_rng(seed); stats=[]
    for _ in range(draws):
        sample=rng.choice(x,len(x),replace=True); stats.append(sample.mean() if statistic=="mean" else np.mean(sample>0))
    return float(np.quantile(stats,.025)),float(np.quantile(stats,.975))


def compare(nav: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    return nav.merge(qqq[["date","daily_return","nav"]].rename(columns={"daily_return":"qqq_daily_return","nav":"qqq_nav"}),on="date",how="inner",validate="one_to_one")


def daily_win(policy: str, comp: pd.DataFrame) -> dict[str,Any]:
    ex=comp.daily_return-comp.qqq_daily_return; wins=int((ex>0).sum()); losses=int((ex<0).sum()); ties=int((ex==0).sum()); lo,hi=wilson(wins,len(comp)); up=comp.qqq_daily_return>0; down=comp.qqq_daily_return<0
    return {"policy":policy,"comparison_days":len(comp),"win_days":wins,"loss_days":losses,"tie_days":ties,"daily_win_rate":wins/len(comp),"wilson_95_ci_lower":lo,"wilson_95_ci_upper":hi,"strategy_positive_day_rate":float((comp.daily_return>0).mean()),"qqq_positive_day_rate":float((comp.qqq_daily_return>0).mean()),"qqq_up_day_relative_win_rate":float((ex[up]>0).mean()) if up.any() else np.nan,"qqq_down_day_relative_win_rate":float((ex[down]>0).mean()) if down.any() else np.nan,"definition":"strategy_daily_return > qqq_daily_return",**LABELS}


def summarize(policy: str, comp: pd.DataFrame, trades: pd.DataFrame) -> dict[str,Any]:
    r=comp.daily_return; qr=comp.qqq_daily_return; ex=r-qr; years=len(comp)/252; total=float(comp.nav.iloc[-1]-1); qtotal=float(comp.qqq_nav.iloc[-1]-1); annvol=float(r.std(ddof=1)*math.sqrt(252)); neg=r[r<0]; cagr=(1+total)**(1/years)-1 if years>0 and total>-1 else np.nan; mdd=max_drawdown(r); blo,bhi=bootstrap_ci(ex)
    dw=daily_win(policy,comp)
    return {"policy":policy,"start_date":comp.date.min(),"end_date":comp.date.max(),"total_return":total,"CAGR":cagr,"annualized_volatility":annvol,"Sharpe":float(r.mean()/r.std(ddof=1)*math.sqrt(252)) if r.std(ddof=1)>0 else np.nan,"Sortino":float(r.mean()/neg.std(ddof=1)*math.sqrt(252)) if len(neg)>1 and neg.std(ddof=1)>0 else np.nan,"max_drawdown":mdd,"Calmar":cagr/abs(mdd) if mdd<0 else np.nan,"positive_day_ratio":float((r>0).mean()),"daily_excess_win_rate_vs_qqq":dw["daily_win_rate"],"cumulative_one_way_turnover":float(comp.one_way_turnover.sum()),"transaction_cost_drag":float(comp.transaction_cost.sum()),"average_gross_exposure":float(comp.gross_exposure.mean()),"average_position_count":float(comp.position_count.mean()),"maximum_position_count":int(comp.position_count.max()),"number_of_trades":len(trades),"number_of_signal_dates":int(comp.signal_date.nunique()),"longest_underwater_period":longest_underwater(r),"worst_day":float(r.min()),"best_day":float(r.max()),"qqq_total_return":qtotal,"excess_return_vs_qqq":total-qtotal,"tracking_error":float(ex.std(ddof=1)*math.sqrt(252)),"information_ratio":float(ex.mean()/ex.std(ddof=1)*math.sqrt(252)) if ex.std(ddof=1)>0 else np.nan,"daily_excess_return_mean":float(ex.mean()),"newey_west_t_stat":newey_west_t(ex),"daily_excess_bootstrap_95_lower":blo,"daily_excess_bootstrap_95_upper":bhi,**LABELS}


def random_windows(policy: str, comp: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    details=[]
    for length in WINDOWS:
        starts=list(range(0,len(comp)-length+1)); rng=np.random.default_rng(RANDOM_SEED+length)
        selected=starts if len(starts)<=1000 else sorted(rng.choice(starts,1000,replace=False).tolist())
        for sample_id,start in enumerate(selected,1):
            part=comp.iloc[start:start+length]; sr=float((1+part.daily_return).prod()-1); qr=float((1+part.qqq_daily_return).prod()-1); ex=part.daily_return-part.qqq_daily_return
            details.append({"seed":RANDOM_SEED,"window_length":length,"sample_id":sample_id,"start_date":part.date.iloc[0],"end_date":part.date.iloc[-1],"policy":policy,"strategy_return":sr,"qqq_return":qr,"excess_return":sr-qr,"strategy_max_drawdown":max_drawdown(part.daily_return),"qqq_max_drawdown":max_drawdown(part.qqq_daily_return),"daily_excess_win_rate":float((ex>0).mean()),"turnover":float(part.one_way_turnover.sum()),"cost":float(part.transaction_cost.sum()),"average_exposure":float(part.gross_exposure.mean()),"trade_count_proxy":np.nan,"rank_snapshot_count":int(part.rank_snapshot_applied.sum()),"window_win":sr>qr,"window_path_contract":"CONTINUOUS_FULL_HISTORY_POLICY_PATH_SLICE_NO_RETURN_SHUFFLING","overlap_independence_warning":"OVERLAPPING_WINDOWS_ARE_NOT_INDEPENDENT",**LABELS})
    detail=pd.DataFrame(details); summary=[]
    for length,part in detail.groupby("window_length"):
        lo,hi=bootstrap_ci(part.excess_return,statistic="win")
        worst=part.loc[part.excess_return.idxmin()]; best=part.loc[part.excess_return.idxmax()]
        summary.append({"policy":policy,"window_length":length,"actual_sample_count":len(part),"window_win_rate_vs_qqq":float(part.window_win.mean()),"mean_excess_return":float(part.excess_return.mean()),"median_excess_return":float(part.excess_return.median()),"std_excess_return":float(part.excess_return.std(ddof=1)),"p05_excess_return":float(part.excess_return.quantile(.05)),"p25_excess_return":float(part.excess_return.quantile(.25)),"p75_excess_return":float(part.excess_return.quantile(.75)),"p95_excess_return":float(part.excess_return.quantile(.95)),"worst_window_start":worst.start_date,"worst_window_excess_return":worst.excess_return,"best_window_start":best.start_date,"best_window_excess_return":best.excess_return,"median_strategy_max_drawdown":float(part.strategy_max_drawdown.median()),"outperform_and_lower_drawdown_rate":float((part.window_win & (part.strategy_max_drawdown>part.qqq_max_drawdown)).mean()),"outperform_and_positive_return_rate":float((part.window_win & (part.strategy_return>0)).mean()),"bootstrap_95_ci_lower":lo,"bootstrap_95_ci_upper":hi,"overlap_independence_warning":"OVERLAPPING_WINDOWS_ARE_NOT_INDEPENDENT",**LABELS})
    return detail,pd.DataFrame(summary)


def coverage_audits(prices: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker=="QQQ","date"].unique()))
    ticker_rows=[]
    for ticker,part in prices.groupby("ticker"):
        first=part.date.min(); last=part.date.max(); expected=int(((calendar>=first)&(calendar<=last)).sum()); actual=int(part.date.nunique())
        ticker_rows.append({"ticker":ticker,"first_price_date":first,"last_price_date":last,"actual_price_sessions":actual,"expected_qqq_sessions_between_first_last":expected,"missing_sessions_between_first_last":expected-actual,"pre_listing_rows_backfilled":0,"universe_flag":"CURRENT_UNIVERSE_SURVIVORSHIP_BIASED_PROXY",**LABELS})
    yearly=[]
    temp=prices.copy(); temp["year"]=temp.date.dt.year
    for year,part in temp.groupby("year"):
        yearly.append({"year":year,"ticker_count_with_any_price":int(part.ticker.nunique()),"first_date":part.date.min(),"last_date":part.date.max(),"row_count":len(part),"universe_flag":"CURRENT_UNIVERSE_SURVIVORSHIP_BIASED_PROXY",**LABELS})
    return pd.DataFrame(ticker_rows),pd.DataFrame(yearly)


def audit_markdown(inv: dict[str,Any], diag: dict[str,Any], ticker_cov: pd.DataFrame, yearly: pd.DataFrame, jump_count: int) -> str:
    ranklines="\n".join(f"- {s}: {v['first_signal_date']} to {v['last_signal_date']}; {v['signal_date_count']} signal dates; {v['ranking_ticker_count']} ever ranked tickers" for s,v in diag.items())
    yearlines="\n".join(f"- {int(r.year)}: {int(r.ticker_count_with_any_price)} tickers with at least one raw price" for r in yearly.itertuples())
    return f"""# Proxy data audit

Strict ABCDE status remains **{STRICT_STATUS}**. This branch status target is **{STATUS}**.

## Mandatory labels

- NOT_ORIGINAL_ABCDE
- CURRENT_UNIVERSE_SURVIVORSHIP_BIASED
- PRICE_ONLY_OR_PRICE_DOMINANT_PROXY
- RESEARCH_ONLY
- NOT_APPROVED_FOR_TRADING

## Price panel

- Source: `{inv['canonical_raw_path']}`
- Snapshot: `{inv['source_snapshot_id']}`
- Coverage: {inv['price_start']} to {inv['price_end']}
- Rows / tickers: {inv['row_count']:,} / {inv['ticker_count']}
- Duplicate ticker-date rows: {inv['duplicate_ticker_date_rows']}
- Basis: **RAW OHLCV only**. The current QFQ snapshot is deliberately not used because it is not a PIT corporate-action ledger.
- Limitation: dividends and splits are not reconstructed. {jump_count} absolute raw close-to-close moves exceed 40%, so corporate actions or genuine jumps can distort this research proxy.
- QQQ and SPY are formal benchmarks and excluded from candidate rankings; all other symbols in the current 326-symbol panel remain candidates.

## Survivorship and availability

The fixed current universe is explicitly survivorship-biased. No symbol is present in rankings before it has enough observed history. IPO/pre-listing dates are never backfilled. A missing execution open is skipped for buys or delays a sale; no future price is substituted.

{yearlines}

## Rebuilt rankings

{ranklines}

A1-D require every mapped feature and at least the effective 127-observation history implied by the 126-day return. E requires its trailing-252-day left-tail input and therefore at least 252 observations. Scores are normalized cross-sectionally per signal date only.

## No-leakage execution contract

Every ranking uses rows dated on or before `signal_date`. The signal is formed after that close and can execute only at the next QQQ trading-session open. Random windows preserve chronological order and are slices of the continuous fully simulated policy path; overlapping windows are not independent.
"""


def report_markdown(inv: dict[str,Any], summary: pd.DataFrame, random_summary: pd.DataFrame) -> str:
    main=summary[summary.policy.str.endswith("TOP5_ENTRY_EXIT10_NO_REBAL")].sort_values("total_return",ascending=False)
    lines="\n".join(f"- {r.policy}: total {r.total_return:.2%}, CAGR {r.CAGR:.2%}, max drawdown {r.max_drawdown:.2%}, daily QQQ win {r.daily_excess_win_rate_vs_qqq:.2%}" for r in main.itertuples())
    wins=random_summary[random_summary.policy.str.endswith("TOP5_ENTRY_EXIT10_NO_REBAL")]
    winlines="\n".join(f"- {r.policy}, {int(r.window_length)}d: {r.window_win_rate_vs_qqq:.2%} ({int(r.actual_sample_count)} windows)" for r in wins.itertuples())
    return f"""# ABCDE price-proxy long-horizon report

**{STATUS}**  
Strict ABCDE conclusion unchanged: **{STRICT_STATUS}**

This is not an original ABCDE historical backtest. It is a price-only or price-dominant research proxy on a current-universe, survivorship-biased panel and is not approved for trading.

## Coverage and method

- Raw price coverage: {inv['price_start']} to {inv['price_end']}; {inv['ticker_count']} current-panel symbols.
- Signals use same-day-and-earlier raw OHLCV, are formed after close, and execute next session open.
- Formal transaction cost is 5 bps one way; 0/5/10/20 bps sensitivity is supplied.
- Main execution rule is Top5 entry, Top10 exit, five independent drifting slots. Top8 is sensitivity only.
- Current-universe survivorship bias, missing historical fundamentals/membership, and absent PIT corporate-action adjustment prevent interpretation as original ABCDE performance.

## Predeclared Top10 proxy policies

{lines}

## Random continuous-window QQQ win rates

{winlines}

Overlapping windows are non-independent. Window results are chronological slices of the continuous simulated policy path, not shuffled returns and not independent restarts.

## Interpretation boundary

Do not use these estimates to reverse the strict failure conclusion. They answer only whether versioned price-factor mappings plus the requested execution mechanism would have behaved differently on the surviving present-day universe under raw-price accounting.
"""


def write_pdf(path: Path, inv: dict[str,Any], summary: pd.DataFrame, random_summary: pd.DataFrame, nav: pd.DataFrame) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    import matplotlib.pyplot as plt
    chart=OUT/"proxy_nav_chart.png"; plt.figure(figsize=(10,5))
    show=nav[nav.policy.str.endswith("TOP5_ENTRY_EXIT10_NO_REBAL")]
    for policy,part in show.groupby("policy"): plt.plot(part.date,part.nav,label=policy.replace("_PRICE_PROXY","")[:22])
    plt.yscale("log"); plt.title("Top5 entry / Top10 exit proxy NAV (5 bps)"); plt.grid(alpha=.2); plt.legend(fontsize=7,ncol=2); plt.tight_layout(); plt.savefig(chart,dpi=160); plt.close()
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="Center",parent=styles["Title"],alignment=TA_CENTER,textColor=colors.HexColor("#17365D")))
    doc=SimpleDocTemplate(str(path),pagesize=landscape(A4),rightMargin=14*mm,leftMargin=14*mm,topMargin=12*mm,bottomMargin=12*mm)
    story=[Paragraph("ABCDE Price-Proxy Long-Horizon Research Report",styles["Center"]),Spacer(1,5*mm),Paragraph(STATUS,styles["Heading2"]),Paragraph(f"Strict ABCDE conclusion unchanged: {STRICT_STATUS}",styles["Heading2"]),Spacer(1,3*mm),Paragraph("NOT_ORIGINAL_ABCDE | CURRENT_UNIVERSE_SURVIVORSHIP_BIASED | PRICE_ONLY_OR_PRICE_DOMINANT_PROXY | RESEARCH_ONLY | NOT_APPROVED_FOR_TRADING",styles["BodyText"]),Spacer(1,4*mm),Paragraph(f"Raw OHLCV: {inv['price_start']} to {inv['price_end']}; {inv['ticker_count']} current-panel symbols. Signals are after-close and execute next-session open. Current QFQ is not used because it is not a PIT corporate-action ledger.",styles["BodyText"]),Spacer(1,4*mm),Image(str(chart),width=245*mm,height=120*mm),PageBreak()]
    cols=["policy","total_return","CAGR","max_drawdown","daily_excess_win_rate_vs_qqq","cumulative_one_way_turnover"]
    tab=summary[summary.policy.str.endswith("TOP5_ENTRY_EXIT10_NO_REBAL")][cols].copy()
    for c in cols[1:]: tab[c]=tab[c].map(lambda x:f"{x:.2%}")
    data=[["Policy","Total","CAGR","Max DD","Daily QQQ win","Turnover"]]+tab.values.tolist()
    t=Table(data,colWidths=[92*mm,25*mm,25*mm,25*mm,30*mm,28*mm]); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#17365D")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.grey),("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story += [Paragraph("Predeclared Top10 proxy comparison",styles["Heading1"]),t,Spacer(1,6*mm)]
    rw=random_summary[random_summary.policy.str.endswith("TOP5_ENTRY_EXIT10_NO_REBAL")].pivot(index="policy",columns="window_length",values="window_win_rate_vs_qqq").reset_index()
    for c in WINDOWS:
        if c in rw: rw[c]=rw[c].map(lambda x:f"{x:.1%}")
    t2=Table([["Policy",*map(str,WINDOWS)]]+rw[["policy",*WINDOWS]].values.tolist(),colWidths=[92*mm]+[28*mm]*5); t2.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#4F81BD")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.grey),("FONTSIZE",(0,0),(-1,-1),8)]))
    story += [Paragraph("Random chronological window win rate vs QQQ",styles["Heading1"]),t2,Spacer(1,5*mm),Paragraph("Windows retain chronological order and may overlap; they are not independent. Top8 and costs 0/5/10/20 bps are sensitivity analyses only. Raw prices omit dividend/split reconstruction, and the fixed present-day universe creates survivorship bias. Results are research-only and not approved for trading.",styles["BodyText"])]
    doc.build(story)
    chart.unlink(missing_ok=True)


def run_backtest() -> dict[str,Any]:
    audit_path=OUT/"strategy_factor_rebuildability.csv"
    if not audit_path.is_file(): raise FileNotFoundError("Factor audit must be produced first")
    strict=json.loads((STRICT_OUT/"run_config.json").read_text(encoding="utf-8"))
    if strict.get("final_status")!=STRICT_STATUS: raise AssertionError("Strict conclusion changed or missing")
    before=json.loads((OUT/"protected_files_before.json").read_text(encoding="utf-8")); now=hash_manifest(protected_paths())
    if before!=now: raise AssertionError("Protected V22.040/V22.044/V22.047/daily files changed before proxy run")
    prices,inv=load_raw_prices(); ticker_cov,yearly=coverage_audits(prices)
    raw_ret=prices.groupby("ticker").close.pct_change(fill_method=None); jump_count=int((raw_ret.abs()>.40).sum())
    _,rankings,diag=compute_features_and_rankings(prices)
    if not (rankings.price_max_date<=rankings.signal_date).all(): raise AssertionError("PIT date violation")
    rankings.to_parquet(OUT/"proxy_rankings_daily.parquet",index=False)
    ticker_cov.to_csv(OUT/"proxy_ticker_coverage_audit.csv",index=False); yearly.to_csv(OUT/"proxy_yearly_ticker_coverage.csv",index=False)
    (OUT/"proxy_data_audit.md").write_text(audit_markdown(inv,diag,ticker_cov,yearly,jump_count),encoding="utf-8")
    engine=BacktestEngine(prices,rankings); main_runs={}; navs=[]; trades=[]; missing=[]; summaries=[]; wins=[]; cost_rows=[]
    for strategy in PROXY_STRATEGIES:
        for mode,exit_rank in [("daily",10),("slots",10),("slots",8)]:
            nav,tr,miss=engine.simulate(strategy,mode,5.0,exit_rank); q,_=engine.buy_hold("QQQ",nav.date.min(),nav.date.max(),5.0); comp=compare(nav,q)
            main_runs[nav.policy.iloc[0]]=(nav,tr,comp); navs.append(nav); trades.append(tr); missing.append(miss); summaries.append(summarize(nav.policy.iloc[0],comp,tr)); wins.append(daily_win(nav.policy.iloc[0],comp))
        for bps in COSTS:
            for mode,exit_rank in [("daily",10),("slots",10),("slots",8)]:
                policy=f"{strategy}_{'DAILY_TOP5_EQUAL' if mode=='daily' else f'TOP5_ENTRY_EXIT{exit_rank}_NO_REBAL'}"
                if bps==5.0: nav,tr,comp=main_runs[policy]
                else:
                    nav,tr,_=engine.simulate(strategy,mode,bps,exit_rank); q,_=engine.buy_hold("QQQ",nav.date.min(),nav.date.max(),bps); comp=compare(nav,q)
                row=summarize(policy,comp,tr); row["cost_bps"]=bps; cost_rows.append(row)
    full_nav=pd.concat(navs,ignore_index=True); full_trades=pd.concat([x for x in trades if len(x)],ignore_index=True); missing_df=pd.concat([x for x in missing if len(x)],ignore_index=True) if any(len(x) for x in missing) else pd.DataFrame(columns=["policy","date","ticker","action","reason",*LABELS])
    summary=pd.DataFrame(summaries); daily=pd.DataFrame(wins); costs=pd.DataFrame(cost_rows)
    common_start=max(engine.valid_execution_dates(s)[0] for s in PROXY_STRATEGIES); common_end=min(engine.valid_execution_dates(s)[-1] for s in PROXY_STRATEGIES)
    for ticker in ["QQQ","SPY"]:
        nav,tr=engine.buy_hold(ticker,common_start,common_end,5.0); q,_=engine.buy_hold("QQQ",common_start,common_end,5.0); comp=compare(nav,q); navs.append(nav); trades.append(tr); summary=pd.concat([summary,pd.DataFrame([summarize(nav.policy.iloc[0],comp,tr)])],ignore_index=True); daily=pd.concat([daily,pd.DataFrame([daily_win(nav.policy.iloc[0],comp)])],ignore_index=True)
    cash=pd.DataFrame({"date":[d for d in engine.calendar if common_start<=d<=common_end]}); cash["policy"]="CASH"; cash["strategy"]="CASH"; cash["nav"]=1.0; cash["daily_return"]=0.0; cash["gross_exposure"]=0.0; cash["position_count"]=0; cash["one_way_turnover"]=0.0; cash["transaction_cost"]=0.0; cash["signal_date"]=pd.NaT; cash["rank_snapshot_applied"]=False; cash["cost_bps"]=0.0; cash["exit_rank"]=np.nan
    for k,v in LABELS.items():cash[k]=v
    q,_=engine.buy_hold("QQQ",common_start,common_end,5.0); comp=compare(cash,q); summary=pd.concat([summary,pd.DataFrame([summarize("CASH",comp,pd.DataFrame())])],ignore_index=True); daily=pd.concat([daily,pd.DataFrame([daily_win("CASH",comp)])],ignore_index=True); navs.append(cash)
    full_nav=pd.concat(navs,ignore_index=True); full_trades=pd.concat([x for x in trades if len(x)],ignore_index=True)
    random_d=[]; random_s=[]
    for policy,(nav,tr,comp) in main_runs.items():
        d,s=random_windows(policy,comp); random_d.append(d); random_s.append(s)
    random_detail=pd.concat(random_d,ignore_index=True); random_summary=pd.concat(random_s,ignore_index=True)
    exit_sens=summary[summary.policy.str.contains("ENTRY_EXIT(8|10)_NO_REBAL",regex=True)].copy(); exit_sens["predeclared_main_parameter"]=exit_sens.policy.str.contains("EXIT10")
    full_nav.to_parquet(OUT/"proxy_daily_nav.parquet",index=False); full_trades.to_parquet(OUT/"proxy_trades.parquet",index=False); missing_df.to_csv(OUT/"proxy_missing_price_audit.csv",index=False)
    summary.to_csv(OUT/"proxy_full_history_summary.csv",index=False); daily.to_csv(OUT/"proxy_daily_win_rate_vs_qqq.csv",index=False); random_detail.to_parquet(OUT/"proxy_random_window_detail.parquet",index=False); random_summary.to_csv(OUT/"proxy_random_window_summary.csv",index=False); costs.to_csv(OUT/"proxy_cost_sensitivity.csv",index=False); exit_sens.to_csv(OUT/"proxy_exit_threshold_sensitivity.csv",index=False)
    report=report_markdown(inv,summary,random_summary); (OUT/"proxy_report.md").write_text(report,encoding="utf-8")
    write_pdf(OUT/"ABCDE_PRICE_PROXY_LONG_HORIZON_REPORT.pdf",inv,summary,random_summary,full_nav)
    protected_after=hash_manifest(protected_paths()); unchanged=before==protected_after
    (OUT/"protected_files_after.json").write_text(json.dumps(protected_after,indent=2),encoding="utf-8")
    config={"final_status":STATUS,"strict_abcde_status_unchanged":strict["final_status"],"data_start":inv["price_start"],"data_end":inv["price_end"],"ticker_count":inv["ticker_count"],"ranking_diagnostics":diag,"random_seed":RANDOM_SEED,"window_lengths":WINDOWS,"max_windows_per_length":1000,"cost_bps":COSTS,"main_cost_bps":5.0,"predeclared_main_execution":"TOP5_ENTRY_EXIT10_NO_REBAL","sensitivity_execution":"TOP5_ENTRY_EXIT8_NO_REBAL","random_window_contract":"CONTINUOUS_FULL_HISTORY_POLICY_PATH_SLICE_NO_RETURN_SHUFFLING","price_basis":inv["price_basis"],"protected_files_unchanged":unchanged,"labels":LABELS,"created_at_utc":datetime.now(timezone.utc).isoformat()}
    (OUT/"run_config.json").write_text(json.dumps(config,indent=2,default=str),encoding="utf-8")
    print(json.dumps(config,indent=2,default=str)); return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["audit", "backtest", "all"], default="all")
    args = parser.parse_args()
    if args.phase == "audit":
        write_audit_phase()
        return 0
    if args.phase == "all" and not (OUT / "strategy_factor_rebuildability.csv").exists():
        write_audit_phase()
    run_backtest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
