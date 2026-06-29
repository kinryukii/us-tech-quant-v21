from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST"
OUT = Path("outputs/v21/V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST")
START = pd.Timestamp("2026-06-16")
V115 = Path("outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625/asof_2026-06-16")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
RANKINGS = {
    "A1_BASELINE_CONTROL": V115 / "A1_BASELINE_CONTROL_ranking_2026-06-16.csv",
    "B_STATIC_MOMENTUM_BLEND": V115 / "B_STATIC_MOMENTUM_BLEND_ranking_2026-06-16.csv",
    "C_DYNAMIC_MOMENTUM_BLEND": V115 / "C_DYNAMIC_MOMENTUM_BLEND_ranking_2026-06-16.csv",
    "D_WEIGHT_OPTIMIZED_R1": V115 / "D_WEIGHT_OPTIMIZED_R1_ranking_2026-06-16.csv",
    "E_R1_REPAIRED": E_R1,
}
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, cols: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for c in cols:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_ranking(path: Path, strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    scol = first_col(df, ["E_final_score", "final_score", "score"])
    dcol = first_col(df, ["latest_price_date", "latest_price_date_used", "ranking_date"])
    df["ticker"] = df[tcol].map(norm)
    df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    df["score"] = pd.to_numeric(df[scol], errors="coerce") if scol else np.nan
    df["ranking_source_date"] = str(df[dcol].dropna().iloc[0]) if dcol and df[dcol].notna().any() else ("2026-06-16" if strategy != "E_R1_REPAIRED" else "2026-06-26")
    return df[df["ticker"].ne("")].drop_duplicates("ticker").sort_values("rank")


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    c = g["adj_close"]
    g["ret1"] = c.pct_change()
    g["ma20"] = c.rolling(20, min_periods=20).mean()
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    return g.set_index("date", drop=False)


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    raw = pd.read_csv(PRICE, usecols=lambda c: c in {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"})
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(set(tickers) | {"QQQ", "^IXIC", "IXIC", "SOXX", "SMH"})].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    for c in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw["adj_close"] = raw["adjusted_close"].fillna(raw["close"])
    data = {sym: add_indicators(g.drop(columns=["symbol"])) for sym, g in raw.groupby("symbol")}
    dates = [pd.Timestamp(d) for d in sorted(raw["date"].dropna().unique())]
    return data, dates, str(max(dates).date())


def row_at(data: dict[str, pd.DataFrame], ticker: str, d: pd.Timestamp) -> pd.Series | None:
    df = data.get(ticker)
    if df is None or d not in df.index:
        return None
    row = df.loc[d]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def overheat(sig: pd.Series | None) -> tuple[bool, str]:
    if sig is None:
        return False, "MISSING_SIGNAL"
    flags = []
    if sf(sig.get("rsi14")) is not None and sig["rsi14"] > 78:
        flags.append("RSI_GT_78")
    if sf(sig.get("kdj_k")) is not None and sig["kdj_k"] > 88:
        flags.append("KDJ_K_GT_88")
    if sf(sig.get("ma20")) not in (None, 0) and sig["adj_close"] / sig["ma20"] - 1 > 0.12:
        flags.append("PRICE_EXTENDED_ABOVE_MA20")
    if sf(sig.get("ret1")) is not None and sig["ret1"] > 0.08:
        flags.append("GAP_UP_PROXY_EXCESSIVE")
    return bool(flags), "|".join(flags)


def weights_for(strategy: str, ranking: pd.DataFrame, bucket_n: int, policy: str, data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict]]:
    top = ranking.head(bucket_n).copy()
    base_w = 1 / bucket_n
    top["overheat_flag"] = False
    top["overheat_flags"] = ""
    for idx, row in top.iterrows():
        oh, flags = overheat(row_at(data, row["ticker"], START))
        top.at[idx, "overheat_flag"] = oh
        top.at[idx, "overheat_flags"] = flags
    top["original_weight"] = base_w
    top["capped_weight"] = base_w
    top["redistributed_weight_received"] = 0.0
    if policy == "EXEC_BASELINE":
        top["final_weight"] = base_w
    elif policy == "EXEC_OVERHEAT_SKIP":
        top = top[~top["overheat_flag"]].copy()
        top["final_weight"] = 1 / len(top) if len(top) else 0.0
        top["redistributed_weight_received"] = top["final_weight"] - top["original_weight"]
    elif policy == "OVERHEAT_SOFT_CAP_R1":
        cap = base_w * 0.5
        hot = top["overheat_flag"]
        freed = float((top.loc[hot, "original_weight"] - cap).sum())
        cool_count = int((~hot).sum())
        add = freed / cool_count if cool_count else 0.0
        top.loc[hot, "capped_weight"] = cap
        top.loc[hot, "final_weight"] = cap
        top.loc[~hot, "redistributed_weight_received"] = add
        top.loc[~hot, "final_weight"] = top.loc[~hot, "original_weight"] + add
    top["final_weight_sum_check"] = top["final_weight"].sum()
    invalid = []
    if len(top) == 0:
        invalid.append({"strategy_id": strategy, "policy": policy, "reason": "NO_VALID_HOLDINGS_AFTER_POLICY"})
    return top, invalid


def window_dates(dates: list[pd.Timestamp], latest: str) -> tuple[list[pd.Timestamp], pd.Timestamp, pd.Timestamp]:
    available = [d for d in dates if START <= d <= pd.Timestamp(latest)]
    entry = min([d for d in available if d > START])
    end = max(available)
    return [d for d in available if entry <= d <= end], entry, end


def price_series(data: dict[str, pd.DataFrame], ticker: str, dates: list[pd.Timestamp]) -> pd.Series:
    vals = {}
    for d in dates:
        row = row_at(data, ticker, d)
        vals[d] = np.nan if row is None else row["adj_close"]
    return pd.Series(vals, dtype=float)


def max_drawdown(cum: pd.Series) -> float | None:
    if cum.empty:
        return None
    peak = cum.cummax()
    dd = cum / peak - 1
    return sf(dd.min())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings = {s: load_ranking(p, s) for s, p in RANKINGS.items() if p.exists()}
    tickers = {t for df in rankings.values() for t in df["ticker"].head(50)}
    data, all_dates, latest = load_prices(tickers)
    dates, entry_date, end_date = window_dates(all_dates, latest)
    qqq_px = price_series(data, "QQQ", dates)
    qqq_daily = qqq_px.pct_change().dropna()
    qqq_cum = qqq_px.iloc[-1] / qqq_px.iloc[0] - 1 - ROUND_TRIP_COST
    ixic_symbol = "^IXIC" if "^IXIC" in data else ("IXIC" if "IXIC" in data else None)
    ixic_available = ixic_symbol is not None
    ixic_cum = None
    if ixic_available:
        ix = price_series(data, ixic_symbol, dates)
        ixic_cum = sf(ix.iloc[-1] / ix.iloc[0] - 1 - ROUND_TRIP_COST) if ix.notna().all() else None
    semi_symbol = "SOXX" if "SOXX" in data else ("SMH" if "SMH" in data else None)
    rows, daily_rows, invalid_rows, overheat_rows = [], [], [], []
    configs = []
    for s in rankings:
        for b in [20, 50]:
            configs.append((s, f"Top{b}", "EXEC_BASELINE"))
            configs.append((s, f"Top{b}", "OVERHEAT_SOFT_CAP_R1"))
    configs.append(("B_STATIC_MOMENTUM_BLEND", "Top20", "EXEC_OVERHEAT_SKIP"))
    configs.append(("B_STATIC_MOMENTUM_BLEND", "Top50", "EXEC_OVERHEAT_SKIP"))
    for strategy, bucket, policy in configs:
        n = int(bucket.replace("Top", ""))
        ranking = rankings[strategy]
        weights, invalid = weights_for(strategy, ranking, n, policy, data)
        invalid_rows.extend(invalid)
        valid_returns = []
        weighted_daily = pd.Series(0.0, index=dates[1:])
        gross_cum = 0.0
        for _, h in weights.iterrows():
            px = price_series(data, h["ticker"], dates)
            if px.isna().any():
                invalid_rows.append({"strategy_id": strategy, "bucket": bucket, "policy": policy, "ticker": h["ticker"], "reason": "MISSING_PRICE_IN_REALIZED_WINDOW"})
                continue
            gross = px.iloc[-1] / px.iloc[0] - 1
            net = gross - ROUND_TRIP_COST
            gross_cum += h["final_weight"] * gross
            valid_returns.append(h["final_weight"] * net)
            weighted_daily = weighted_daily.add(px.pct_change().dropna() * h["final_weight"], fill_value=0.0)
            if strategy == "B_STATIC_MOMENTUM_BLEND" and policy == "OVERHEAT_SOFT_CAP_R1":
                overheat_rows.append(
                    {
                        "ticker": h["ticker"],
                        "overheat_flag": bool(h["overheat_flag"]),
                        "original_weight": h["original_weight"],
                        "final_weight": h["final_weight"],
                        "weight_reduction": h["original_weight"] - h["final_weight"],
                        "window_return_net": net,
                    }
                )
        net_cum = sum(valid_returns)
        weighted_daily_net = weighted_daily.copy()
        if len(weighted_daily_net):
            weighted_daily_net.iloc[0] -= ROUND_TRIP_COST * weights["final_weight"].sum()
        cum_curve = (1 + weighted_daily_net).cumprod()
        q_align = qqq_daily.reindex(weighted_daily_net.index)
        q_down = q_align < 0
        choppy = q_align.abs() > q_align.abs().median()
        b_baseline = None
        rows.append(
            {
                "strategy_id": strategy,
                "variant": policy,
                "bucket": bucket,
                "start_date": str(START.date()),
                "entry_date": str(entry_date.date()),
                "end_date": str(end_date.date()),
                "latest_price_date_used": latest,
                "number_of_trading_days": len(dates),
                "effective_holding_count": int(len(weights)),
                "invalid_holding_count": int(sum(1 for r in invalid_rows if r.get("strategy_id") == strategy and r.get("policy") == policy)),
                "average_weight": sf(weights["final_weight"].mean()),
                "max_single_name_weight": sf(weights["final_weight"].max()),
                "concentration_proxy": sf((weights["final_weight"] ** 2).sum()),
                "cumulative_return_gross": sf(gross_cum),
                "cumulative_return_net": sf(net_cum),
                "QQQ_cumulative_return_net": sf(qqq_cum),
                "Nasdaq_cumulative_return_net": ixic_cum,
                "excess_return_vs_QQQ": sf(net_cum - qqq_cum),
                "excess_return_vs_Nasdaq": sf(net_cum - ixic_cum) if ixic_cum is not None else None,
                "daily_mean_return": sf(weighted_daily_net.mean()),
                "daily_median_return": sf(weighted_daily_net.median()),
                "daily_volatility": sf(weighted_daily_net.std()),
                "max_drawdown_proxy": max_drawdown(cum_curve),
                "p10_daily_return": sf(weighted_daily_net.quantile(0.10)),
                "p5_daily_return": sf(weighted_daily_net.quantile(0.05)),
                "p1_daily_return": sf(weighted_daily_net.quantile(0.01)),
                "worst_single_day_return": sf(weighted_daily_net.min()),
                "best_single_day_return": sf(weighted_daily_net.max()),
                "up_day_capture_vs_QQQ": sf(weighted_daily_net[q_align > 0].mean() / q_align[q_align > 0].mean()) if (q_align > 0).any() else None,
                "down_day_defense_vs_QQQ": sf(weighted_daily_net[q_down].mean() - q_align[q_down].mean()) if q_down.any() else None,
                "win_rate_vs_QQQ_daily": sf((weighted_daily_net > q_align).mean()),
                "number_of_days_outperforming_QQQ": int((weighted_daily_net > q_align).sum()),
                "number_of_days_underperforming_QQQ": int((weighted_daily_net < q_align).sum()),
                "return_delta_vs_B_baseline": b_baseline,
                "drawdown_delta_vs_B_baseline": None,
                "left_tail_delta_vs_B_baseline": None,
                "transaction_cost_impact": TRANSACTION_COST_BPS,
                "slippage_impact": SLIPPAGE_BPS,
                "diagnostic_only": strategy == "E_R1_REPAIRED",
                "ranking_source_date": ranking["ranking_source_date"].iloc[0],
                "ranking_source_after_start_warn": pd.Timestamp(ranking["ranking_source_date"].iloc[0]) > START,
            }
        )
        for d, ret in weighted_daily_net.items():
            daily_rows.append({"date": str(d.date()), "strategy_id": strategy, "variant": policy, "bucket": bucket, "daily_return": ret, "QQQ_daily_return": q_align.loc[d]})
    comp = pd.DataFrame(rows)
    bbase = comp[(comp["strategy_id"].eq("B_STATIC_MOMENTUM_BLEND")) & (comp["variant"].eq("EXEC_BASELINE")) & (comp["bucket"].eq("Top20"))].iloc[0]
    comp["return_delta_vs_B_baseline"] = comp["cumulative_return_net"] - bbase["cumulative_return_net"]
    comp["drawdown_delta_vs_B_baseline"] = comp["max_drawdown_proxy"] - bbase["max_drawdown_proxy"]
    comp["left_tail_delta_vs_B_baseline"] = comp["p5_daily_return"] - bbase["p5_daily_return"]
    daily = pd.DataFrame(daily_rows)
    choppy_rows = []
    down_rows = []
    qabs_med = qqq_daily.abs().median()
    for keys, g in daily.groupby(["strategy_id", "variant", "bucket"]):
        chop = g[g["QQQ_daily_return"].abs() > qabs_med]
        down = g[g["QQQ_daily_return"] < 0]
        choppy_rows.append({"strategy_id": keys[0], "variant": keys[1], "bucket": keys[2], "choppy_day_win_rate_vs_QQQ": sf((chop["daily_return"] > chop["QQQ_daily_return"]).mean()), "choppy_day_excess_return_vs_QQQ": sf((chop["daily_return"] - chop["QQQ_daily_return"]).mean())})
        down_rows.append({"strategy_id": keys[0], "variant": keys[1], "bucket": keys[2], "avg_return_on_QQQ_down_days": sf(down["daily_return"].mean()), "avg_QQQ_down_day_return": sf(down["QQQ_daily_return"].mean()), "down_day_defense_vs_QQQ": sf((down["daily_return"] - down["QQQ_daily_return"]).mean())})
    overheat_df = pd.DataFrame(overheat_rows)
    if not overheat_df.empty:
        overheat_df["overheated_names_underperformed"] = overheat_df.groupby("overheat_flag")["window_return_net"].transform("mean")
    semi = []
    if semi_symbol:
        spx = price_series(data, semi_symbol, dates)
        sret = spx.iloc[-1] / spx.iloc[0] - 1 - ROUND_TRIP_COST if spx.notna().all() else np.nan
        for _, row in comp.iterrows():
            semi.append({"strategy_id": row["strategy_id"], "variant": row["variant"], "bucket": row["bucket"], "semis_benchmark_available": True, "semi_benchmark_symbol": semi_symbol, "excess_return_vs_semis": row["cumulative_return_net"] - sret})
    else:
        semi.append({"semis_benchmark_available": False})
    primary = comp[(comp["strategy_id"].eq("B_STATIC_MOMENTUM_BLEND")) & (comp["variant"].eq("OVERHEAT_SOFT_CAP_R1")) & (comp["bucket"].eq("Top20"))].iloc[0]
    if len(dates) < 3:
        final_status = "WAIT_V21_153_INSUFFICIENT_WINDOW_DATA"
        decision = "REJECT_RECENT_WINDOW_EVIDENCE_AS_INSUFFICIENT"
    elif primary["cumulative_return_net"] > bbase["cumulative_return_net"] and primary["max_drawdown_proxy"] >= bbase["max_drawdown_proxy"]:
        final_status = "PASS_V21_153_SOFT_CAP_OUTPERFORMED_RECENT_WINDOW"
        decision = "SOFT_CAP_RECENT_WINDOW_SUPPORTIVE_WAIT_MATURITY"
    elif primary["max_drawdown_proxy"] >= bbase["max_drawdown_proxy"]:
        final_status = "PARTIAL_PASS_V21_153_SOFT_CAP_BETTER_DEFENSE_RETURN_MIXED"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING"
    elif primary["cumulative_return_net"] > bbase["cumulative_return_net"]:
        final_status = "PARTIAL_PASS_V21_153_SOFT_CAP_RETURN_BETTER_LEFT_TAIL_MIXED"
        decision = "SOFT_CAP_RECENT_WINDOW_SUPPORTIVE_WAIT_MATURITY"
    elif bbase["cumulative_return_net"] > primary["cumulative_return_net"]:
        final_status = "PARTIAL_PASS_V21_153_BASELINE_BETTER_SOFT_CAP_DEFENSIVE_ONLY"
        decision = "BASELINE_RECENT_WINDOW_BETTER_WAIT_MATURITY"
    else:
        final_status = "FAIL_V21_153_SOFT_CAP_NO_RECENT_WINDOW_EDGE"
        decision = "REJECT_RECENT_WINDOW_EVIDENCE_AS_INSUFFICIENT"
    comp.to_csv(OUT / "realized_window_strategy_comparison.csv", index=False)
    daily.to_csv(OUT / "realized_window_daily_returns.csv", index=False)
    comp[["strategy_id", "variant", "bucket", "excess_return_vs_QQQ", "win_rate_vs_QQQ_daily", "number_of_days_outperforming_QQQ"]].to_csv(OUT / "realized_window_vs_QQQ_comparison.csv", index=False)
    comp[["strategy_id", "variant", "bucket", "Nasdaq_cumulative_return_net", "excess_return_vs_Nasdaq"]].to_csv(OUT / "realized_window_vs_Nasdaq_comparison.csv", index=False)
    comp[["strategy_id", "variant", "bucket", "max_drawdown_proxy", "drawdown_delta_vs_B_baseline"]].to_csv(OUT / "realized_window_drawdown_comparison.csv", index=False)
    comp[["strategy_id", "variant", "bucket", "p10_daily_return", "p5_daily_return", "p1_daily_return", "left_tail_delta_vs_B_baseline"]].to_csv(OUT / "realized_window_left_tail_comparison.csv", index=False)
    pd.DataFrame(choppy_rows).to_csv(OUT / "choppy_day_diagnostic.csv", index=False)
    pd.DataFrame(down_rows).to_csv(OUT / "down_day_defense_diagnostic.csv", index=False)
    overheat_df.to_csv(OUT / "overheat_contribution_audit.csv", index=False)
    pd.DataFrame(semi).to_csv(OUT / "semiconductor_benchmark_diagnostic.csv", index=False)
    pd.DataFrame(invalid_rows if invalid_rows else [{"reason": "NO_INVALID_HOLDINGS"}]).to_csv(OUT / "invalid_holding_audit.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"start_date={START.date()}",
        f"end_date={end_date.date()}",
        f"latest_price_date_used={latest}",
        "primary_benchmark=QQQ",
        f"benchmark_ixic_available={str(ixic_available).lower()}",
        "intraday_data_available=false",
        "soft_cap_weights_not_retuned=true",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"start_date={START.date()}",
        f"end_date={end_date.date()}",
        f"latest_price_date_used={latest}",
        f"B_baseline_return={bbase['cumulative_return_net']}",
        f"B_soft_cap_return={primary['cumulative_return_net']}",
        f"B_soft_cap_excess_vs_QQQ={primary['excess_return_vs_QQQ']}",
        f"benchmark_ixic_available={str(ixic_available).lower()}",
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
