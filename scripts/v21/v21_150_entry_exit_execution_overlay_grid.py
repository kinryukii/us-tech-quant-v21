from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID"
OUT = Path("outputs/v21/V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
V149_SUMMARY = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT/V21.149_summary.json")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

STRATEGY_FILES = {
    "A1_BASELINE_CONTROL": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "E_R1_REPAIRED": E_R1,
}
VARIANTS = [
    "EXEC_BASELINE",
    "EXEC_PULLBACK_SAFE",
    "EXEC_BREAKOUT_CONFIRM",
    "EXEC_REVERSAL_EARLY",
    "EXEC_OVERHEAT_SKIP",
    "EXEC_COMBINED_R1",
]
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}
BUCKETS = {"Top20": 20, "Top50": 50}
CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
    "overlay_adoption_allowed": False,
    "adoption_grade_backtest": False,
}
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2.0 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0
DATE_POS: dict[pd.Timestamp, int] = {}


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_rankings() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for strategy, path in STRATEGY_FILES.items():
        if not path.exists():
            continue
        df = pd.read_csv(path)
        tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
        rcol = first_col(df, ["rank", "adjusted_rank"])
        scol = first_col(df, ["E_final_score", "final_score", "score"])
        df["ticker_norm"] = df[tcol].map(norm)
        df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
        df["score"] = pd.to_numeric(df[scol], errors="coerce") if scol else np.nan
        df = df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("rank")
        df["strategy_id"] = strategy
        df["source_path"] = str(path).replace("\\", "/")
        out[strategy] = df
    return out


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    g = df.sort_values("date").copy()
    c = g["adj_close"]
    g["ret1"] = c.pct_change()
    g["ma20"] = c.rolling(20, min_periods=20).mean()
    g["ma50"] = c.rolling(50, min_periods=50).mean()
    std20 = c.rolling(20, min_periods=20).std()
    g["bb_mid"] = g["ma20"]
    g["bb_upper"] = g["ma20"] + 2 * std20
    g["bb_lower"] = g["ma20"] - 2 * std20
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    g["kdj_d"] = g["kdj_k"].rolling(3, min_periods=3).mean()
    ema12 = c.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = c.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    g["macd_hist"] = macd - signal
    g["volume_ma20"] = g["volume"].rolling(20, min_periods=20).mean()
    g["prior_20d_high"] = g["high"].shift(1).rolling(20, min_periods=20).max()
    g["prev_breakout"] = (g["close"].shift(1) > g["prior_20d_high"].shift(1)) | (g["close"].shift(1) > g["bb_upper"].shift(1))
    return g


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    use = set(tickers) | {"QQQ", "SOXX", "SPY"}
    cols = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]
    raw = pd.read_csv(PRICE, usecols=lambda c: c in cols)
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(use)].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["adj_close"] = pd.to_numeric(raw["adjusted_close"], errors="coerce").fillna(pd.to_numeric(raw["close"], errors="coerce"))
    for c in ["open", "high", "low", "close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    data = {}
    for sym, g in raw.groupby("symbol"):
        ind = add_indicators(g.drop(columns=["symbol"]))
        data[sym] = ind.set_index("date", drop=False)
    dates = sorted(raw["date"].dropna().unique())
    latest = str(pd.Timestamp(max(dates)).date()) if dates else "UNKNOWN"
    out_dates = [pd.Timestamp(d) for d in dates]
    global DATE_POS
    DATE_POS = {d: i for i, d in enumerate(out_dates)}
    return data, out_dates, latest


def eligible_dates(dates: list[pd.Timestamp], data: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    if not dates:
        return []
    max_idx = len(dates) - max(HORIZONS.values()) - 2
    qqq = data.get("QQQ")
    available = []
    for i, d in enumerate(dates):
        if i < 80 or i > max_idx:
            continue
        if qqq is not None and d in qqq.index:
            available.append(d)
    if len(available) <= 20:
        return available
    idx = np.linspace(0, len(available) - 1, 20).round().astype(int)
    return [available[i] for i in sorted(set(idx))]


def row_at(df: pd.DataFrame, d: pd.Timestamp) -> pd.Series | None:
    if d not in df.index:
        return None
    row = df.loc[d]
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def next_idx(dates: list[pd.Timestamp], d: pd.Timestamp) -> int | None:
    i = DATE_POS.get(d)
    if i is None:
        return None
    return i + 1 if i + 1 < len(dates) else None


def overheat(sig: pd.Series) -> tuple[bool, str]:
    reasons = []
    if sf(sig.get("rsi14")) is not None and sig["rsi14"] > 78:
        reasons.append("RSI_GT_78")
    if sf(sig.get("kdj_k")) is not None and sig["kdj_k"] > 88:
        reasons.append("KDJ_K_GT_88")
    if sf(sig.get("ma20")) not in (None, 0) and sig["adj_close"] / sig["ma20"] - 1 > 0.12:
        reasons.append("PRICE_EXTENDED_ABOVE_MA20")
    if sf(sig.get("ret1")) is not None and sig["ret1"] > 0.08:
        reasons.append("GAP_UP_PROXY_EXCESSIVE")
    return bool(reasons), "|".join(reasons)


def entry_allowed(variant: str, sig: pd.Series | None) -> tuple[bool, str]:
    if sig is None:
        return False, "MISSING_SIGNAL_DATE"
    oh, oh_reason = overheat(sig)
    if variant == "EXEC_BASELINE":
        return True, ""
    if variant == "EXEC_OVERHEAT_SKIP":
        return (not oh), oh_reason
    if oh:
        return False, oh_reason
    close = sig["adj_close"]
    rsi_v = sf(sig.get("rsi14"))
    ma20 = sf(sig.get("ma20"))
    ma50 = sf(sig.get("ma50"))
    bb_mid = sf(sig.get("bb_mid"))
    bb_upper = sf(sig.get("bb_upper"))
    k = sf(sig.get("kdj_k"))
    d = sf(sig.get("kdj_d"))
    macd = sf(sig.get("macd_hist"))
    prev_break = bool(sig.get("prev_breakout")) if not pd.isna(sig.get("prev_breakout")) else False
    vol_ok = True if pd.isna(sig.get("volume_ma20")) else sig.get("volume", 0) >= sig.get("volume_ma20", 0)
    pullback = bool(ma50 and close > ma50 and ma20 and abs(close / ma20 - 1) <= 0.05 and rsi_v is not None and 40 <= rsi_v <= 65)
    breakout = bool(prev_break and (bb_upper is None or close >= min(sig.get("prior_20d_high", close), bb_upper)) and vol_ok and (rsi_v is None or rsi_v <= 78))
    reversal = bool(rsi_v is not None and 35 <= rsi_v <= 60 and ((k is not None and d is not None and k > d and k < 75) or (macd is not None and macd > 0)) and ((ma20 and close >= ma20) or (bb_mid and close >= bb_mid)))
    if variant == "EXEC_PULLBACK_SAFE":
        return pullback, "PULLBACK_ENTRY_RULE_NOT_MET"
    if variant == "EXEC_BREAKOUT_CONFIRM":
        return breakout, "BREAKOUT_CONFIRM_RULE_NOT_MET"
    if variant == "EXEC_REVERSAL_EARLY":
        return reversal, "REVERSAL_ENTRY_RULE_NOT_MET"
    if variant == "EXEC_COMBINED_R1":
        return pullback or breakout or reversal, "COMBINED_ENTRY_RULE_NOT_MET"
    return False, "UNKNOWN_VARIANT"


def simulate_ticker(
    variant: str,
    df: pd.DataFrame | None,
    dates: list[pd.Timestamp],
    asof: pd.Timestamp,
    horizon_days: int,
) -> dict:
    if df is None:
        return {"valid": False, "reason": "MISSING_TICKER_PRICE_HISTORY"}
    sig = row_at(df, asof)
    allowed, skip_reason = entry_allowed(variant, sig)
    if not allowed:
        return {"valid": False, "reason": skip_reason}
    i = next_idx(dates, asof)
    if i is None:
        return {"valid": False, "reason": "MISSING_NEXT_EXECUTION_BAR"}
    entry_date = dates[i]
    fixed_i = i + horizon_days
    if fixed_i >= len(dates):
        return {"valid": False, "reason": "MISSING_HORIZON_EXIT_BAR"}
    entry = row_at(df, entry_date)
    if entry is None or pd.isna(entry["adj_close"]):
        return {"valid": False, "reason": "ENTRY_PRICE_MISSING"}
    entry_px = entry["adj_close"]
    exit_i = fixed_i
    exit_reason = "FIXED_HOLD"
    max_ret = -999.0
    stop = -0.08 if variant in {"EXEC_PULLBACK_SAFE", "EXEC_BREAKOUT_CONFIRM", "EXEC_REVERSAL_EARLY", "EXEC_COMBINED_R1"} else None
    for j in range(i + 1, fixed_i + 1):
        day = row_at(df, dates[j])
        if day is None or pd.isna(day["adj_close"]):
            continue
        ret = day["adj_close"] / entry_px - 1
        max_ret = max(max_ret, ret)
        if stop is not None and ret <= stop:
            exit_i, exit_reason = j, "STOP_LOSS"
            break
        if variant in {"EXEC_BREAKOUT_CONFIRM", "EXEC_COMBINED_R1"} and max_ret >= 0.12 and ret <= max_ret - 0.055:
            exit_i, exit_reason = j, "TRAILING_PROFIT"
            break
        if variant in {"EXEC_COMBINED_R1", "EXEC_REVERSAL_EARLY"} and j - i >= 5 and ret < 0:
            exit_i, exit_reason = j, "TIME_STOP"
            break
        if variant == "EXEC_COMBINED_R1" and j - i >= 2:
            tech = row_at(df, dates[j])
            if tech is not None and sf(tech.get("ma20")) and tech["adj_close"] < tech["ma20"] and sf(tech.get("macd_hist")) is not None and tech["macd_hist"] < 0:
                exit_i, exit_reason = j, "TECHNICAL_BREAK"
                break
    exit_day = row_at(df, dates[exit_i])
    if exit_day is None or pd.isna(exit_day["adj_close"]):
        return {"valid": False, "reason": "EXIT_PRICE_MISSING"}
    gross_ret = exit_day["adj_close"] / entry_px - 1
    net_ret = gross_ret - ROUND_TRIP_COST
    mfe = max(max_ret, gross_ret)
    giveback = mfe - gross_ret
    return {
        "valid": True,
        "entry_date": str(entry_date.date()),
        "exit_date": str(dates[exit_i].date()),
        "return": net_ret,
        "gross_return": gross_ret,
        "mfe": mfe,
        "profit_giveback": giveback,
        "exit_reason": exit_reason,
    }


def portfolio_trial(strategy: str, bucket: str, tickers: list[str], variant: str, horizon: str, asof: pd.Timestamp, data: dict[str, pd.DataFrame], dates: list[pd.Timestamp]) -> tuple[dict, list[dict], list[dict]]:
    hdays = HORIZONS[horizon]
    detail = []
    skipped = []
    returns = []
    exits = []
    for t in tickers:
        res = simulate_ticker(variant, data.get(t), dates, asof, hdays)
        if res["valid"]:
            returns.append(res["return"])
            exits.append(res["exit_reason"])
            detail.append({"ticker_norm": t, **res})
        else:
            skipped.append({"strategy_id": strategy, "portfolio_size": bucket, "execution_variant": variant, "horizon": horizon, "asof_date": str(asof.date()), "ticker_norm": t, "skip_reason": res["reason"]})
    min_valid = 15 if bucket == "Top20" else 35
    valid = len(returns) >= min_valid
    qqq = simulate_ticker("EXEC_BASELINE", data.get("QQQ"), dates, asof, hdays)
    pret = float(np.mean(returns)) if valid else np.nan
    row = {
        "strategy_id": strategy,
        "portfolio_size": bucket,
        "execution_variant": variant,
        "horizon": horizon,
        "asof_date": str(asof.date()),
        "valid_trial": valid,
        "valid_holding_count": len(returns),
        "invalid_holding_count": len(tickers) - len(returns),
        "portfolio_return": pret,
        "QQQ_return": qqq.get("return") if qqq.get("valid") else np.nan,
        "win_vs_QQQ": bool(pret > qqq.get("return")) if valid and qqq.get("valid") else False,
        "avg_profit_giveback": float(np.mean([d["profit_giveback"] for d in detail])) if detail else np.nan,
        "turnover": 1.0 if valid else np.nan,
        "stop_loss_hit_rate": exits.count("STOP_LOSS") / len(exits) if exits else 0.0,
        "trailing_stop_hit_rate": exits.count("TRAILING_PROFIT") / len(exits) if exits else 0.0,
        "technical_exit_hit_rate": exits.count("TECHNICAL_BREAK") / len(exits) if exits else 0.0,
        "rank_exit_hit_rate": np.nan,
        "time_stop_hit_rate": exits.count("TIME_STOP") / len(exits) if exits else 0.0,
        "invalid_reason": "" if valid else "INSUFFICIENT_VALID_HOLDINGS",
    }
    return row, skipped, detail


def summarize(trials: pd.DataFrame) -> pd.DataFrame:
    base = trials[trials["execution_variant"].eq("EXEC_BASELINE")][["strategy_id", "portfolio_size", "horizon", "asof_date", "portfolio_return"]].rename(columns={"portfolio_return": "baseline_return"})
    merged = trials.merge(base, on=["strategy_id", "portfolio_size", "horizon", "asof_date"], how="left")
    merged["win_vs_hold_only"] = merged["portfolio_return"] > merged["baseline_return"]
    rows = []
    for keys, g in merged.groupby(["strategy_id", "portfolio_size", "execution_variant", "horizon"], dropna=False):
        valid = g[g["valid_trial"]]
        r = valid["portfolio_return"].dropna()
        rows.append(
            {
                "strategy_id": keys[0],
                "portfolio_size": keys[1],
                "execution_variant": keys[2],
                "horizon": keys[3],
                "valid_trials": int(g["valid_trial"].sum()),
                "invalid_trials": int((~g["valid_trial"]).sum()),
                "avg_entered_holdings": sf(valid["valid_holding_count"].mean()),
                "mean_return": sf(r.mean()),
                "median_return": sf(r.median()),
                "win_rate_vs_hold_only": sf(valid["win_vs_hold_only"].mean()),
                "win_rate_vs_QQQ": sf(valid["win_vs_QQQ"].mean()),
                "p10_left_tail_return": sf(r.quantile(0.10)) if len(r) else None,
                "p5_left_tail_return": sf(r.quantile(0.05)) if len(r) else None,
                "p1_left_tail_return": sf(r.quantile(0.01)) if len(r) else None,
                "max_drawdown_proxy": sf(r.min()) if len(r) else None,
                "profit_giveback": sf(valid["avg_profit_giveback"].mean()),
                "turnover": sf(valid["turnover"].mean()),
                "stop_loss_hit_rate": sf(valid["stop_loss_hit_rate"].mean()),
                "trailing_stop_hit_rate": sf(valid["trailing_stop_hit_rate"].mean()),
                "technical_exit_hit_rate": sf(valid["technical_exit_hit_rate"].mean()),
                "rank_exit_hit_rate": None,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings = load_rankings()
    all_tickers = {t for df in rankings.values() for t in df["ticker_norm"].head(50)}
    data, dates, latest = load_prices(all_tickers)
    asofs = eligible_dates(dates, data)
    rows, skipped_rows, invalid_rows = [], [], []
    holdings = {}
    for strategy, df in rankings.items():
        for bucket, n in BUCKETS.items():
            holdings[(strategy, bucket)] = df.head(n)["ticker_norm"].tolist()
    for asof in asofs:
        for strategy in rankings:
            for bucket, tickers in holdings.items():
                if bucket[0] != strategy:
                    continue
                for variant in VARIANTS:
                    for horizon in HORIZONS:
                        row, skipped, _detail = portfolio_trial(strategy, bucket[1], tickers, variant, horizon, asof, data, dates)
                        rows.append(row)
                        skipped_rows.extend(skipped)
                        if not row["valid_trial"]:
                            invalid_rows.append(row.copy())
    trials = pd.DataFrame(rows)
    metrics = summarize(trials)
    invalid = pd.DataFrame(invalid_rows)
    if invalid.empty:
        invalid = pd.DataFrame(columns=["strategy_id", "portfolio_size", "execution_variant", "horizon", "asof_date", "invalid_reason", "valid_holding_count", "invalid_holding_count"])
    skipped = pd.DataFrame(skipped_rows)
    if skipped.empty:
        skipped = pd.DataFrame(columns=["strategy_id", "portfolio_size", "execution_variant", "horizon", "asof_date", "ticker_norm", "skip_reason"])
    skipped_audit = skipped.groupby(["strategy_id", "portfolio_size", "execution_variant", "horizon", "skip_reason"], dropna=False).size().reset_index(name="skipped_entry_count")
    invalid_audit = invalid.groupby(["strategy_id", "portfolio_size", "execution_variant", "horizon", "invalid_reason"], dropna=False).size().reset_index(name="invalid_trial_count")
    top20 = metrics[metrics["portfolio_size"].eq("Top20")].copy()
    top50 = metrics[metrics["portfolio_size"].eq("Top50")].copy()
    left_tail = metrics[["strategy_id", "portfolio_size", "execution_variant", "horizon", "p10_left_tail_return", "p5_left_tail_return", "p1_left_tail_return", "max_drawdown_proxy"]].copy()
    giveback = metrics[["strategy_id", "portfolio_size", "execution_variant", "horizon", "profit_giveback", "trailing_stop_hit_rate", "stop_loss_hit_rate", "technical_exit_hit_rate"]].copy()
    baseline = metrics[metrics["execution_variant"].eq("EXEC_BASELINE")][["strategy_id", "portfolio_size", "horizon", "mean_return", "p5_left_tail_return"]].rename(columns={"mean_return": "baseline_mean_return", "p5_left_tail_return": "baseline_p5_left_tail_return"})
    joined = metrics.merge(baseline, on=["strategy_id", "portfolio_size", "horizon"], how="left")
    joined["return_delta_vs_baseline"] = joined["mean_return"] - joined["baseline_mean_return"]
    joined["p5_delta_vs_baseline"] = joined["p5_left_tail_return"] - joined["baseline_p5_left_tail_return"]
    candidates = joined[~joined["execution_variant"].eq("EXEC_BASELINE")].copy()
    enough_valid = bool((metrics["valid_trials"] >= 20).any())
    best_tail = candidates.sort_values(["p5_delta_vs_baseline", "return_delta_vs_baseline"], ascending=False).head(1)
    tail_better = bool(not best_tail.empty and best_tail.iloc[0]["p5_delta_vs_baseline"] > 0)
    return_better = bool(not best_tail.empty and best_tail.iloc[0]["return_delta_vs_baseline"] > 0)
    if not enough_valid:
        final_status = "WARN_V21_150_EXECUTION_OVERLAY_INSUFFICIENT_VALID_TRIALS"
        recommendation = "NEED_MORE_MATURITY"
    elif tail_better and return_better:
        final_status = "PASS_V21_150_EXECUTION_OVERLAY_IMPROVES_LEFT_TAIL"
        recommendation = "CANDIDATE_FOR_FORWARD_TRACKING"
    elif tail_better:
        final_status = "PARTIAL_PASS_V21_150_EXECUTION_OVERLAY_RETURN_MIXED_LEFT_TAIL_BETTER"
        recommendation = "CANDIDATE_FOR_FORWARD_TRACKING"
    elif return_better:
        final_status = "PARTIAL_PASS_V21_150_EXECUTION_OVERLAY_RETURN_BETTER_LEFT_TAIL_WORSE"
        recommendation = "KEEP_DIAGNOSTIC_ONLY"
    else:
        final_status = "FAIL_V21_150_EXECUTION_OVERLAY_NO_EDGE"
        recommendation = "REJECT_EXECUTION_OVERLAY"
    e_diag = True
    v149 = load_json(V149_SUMMARY)
    if v149.get("invalid_trials_materially_bias_results") is True:
        e_diag = True
    summary = pd.DataFrame(
        [
            {
                "FINAL_STATUS": final_status,
                "recommendation": recommendation,
                "latest_price_date_used": latest,
                "intraday_data_available": False,
                "price_source_path": str(PRICE).replace("\\", "/"),
                "asof_date_count": len(asofs),
                "strategy_count": len(rankings),
                "execution_variant_count": len(VARIANTS),
                "transaction_cost_bps_per_side": TRANSACTION_COST_BPS,
                "slippage_bps_per_side": SLIPPAGE_BPS,
                "E_R1_diagnostic_only_unresolved_invalid_replay_lineage": e_diag,
                "rank_deterioration_exit_available": False,
                "protected_outputs_modified": False,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "research_only": True,
            }
        ]
    )
    summary.to_csv(OUT / "execution_overlay_summary.csv", index=False)
    metrics.to_csv(OUT / "strategy_by_execution_variant_metrics.csv", index=False)
    top20.to_csv(OUT / "top20_execution_comparison.csv", index=False)
    top50.to_csv(OUT / "top50_execution_comparison.csv", index=False)
    invalid_audit.to_csv(OUT / "invalid_trial_audit.csv", index=False)
    skipped_audit.to_csv(OUT / "skipped_entry_reason_audit.csv", index=False)
    left_tail.to_csv(OUT / "left_tail_comparison.csv", index=False)
    giveback.to_csv(OUT / "profit_giveback_comparison.csv", index=False)
    best_line = best_tail.iloc[0].to_dict() if not best_tail.empty else {}
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"recommendation={recommendation}",
        f"latest_price_date_used={latest}",
        f"price_source_path={str(PRICE).replace(chr(92), '/')}",
        "intraday_data_available=false",
        f"transaction_cost_bps_per_side={TRANSACTION_COST_BPS}",
        f"slippage_bps_per_side={SLIPPAGE_BPS}",
        "rank_deterioration_exit_available=false",
        "E_R1_diagnostic_only=true",
        "",
        "Best non-baseline overlay:",
        json.dumps(best_line, indent=2, default=str),
        "",
        "Controls: protected_outputs_modified=false; official_adoption_allowed=false; broker_action_allowed=false; research_only=true.",
    ]
    (OUT / "V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"recommendation={recommendation}",
        f"latest_price_date_used={latest}",
        f"strategies_tested={'|'.join(rankings)}",
        f"execution_variants={'|'.join(VARIANTS)}",
        f"best_variant={best_line.get('execution_variant', 'NONE')}",
        f"best_strategy={best_line.get('strategy_id', 'NONE')}",
        f"best_bucket={best_line.get('portfolio_size', 'NONE')}",
        f"best_horizon={best_line.get('horizon', 'NONE')}",
        f"best_p5_delta_vs_baseline={best_line.get('p5_delta_vs_baseline', 'NA')}",
        f"best_return_delta_vs_baseline={best_line.get('return_delta_vs_baseline', 'NA')}",
        "E_R1_diagnostic_only=true",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"output directory={str(OUT).replace(chr(92), '/')}",
    ]
    (OUT / "compact_readable_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")
    for line in compact:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
