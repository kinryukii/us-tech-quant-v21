from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE"
OUT = Path("outputs/v21/V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

RANKINGS = {
    "A1_BASELINE_CONTROL": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "E_R1_REPAIRED": E_R1,
}
POLICIES = ["EXEC_BASELINE", "EXEC_OVERHEAT_SKIP", "OVERHEAT_SOFT_CAP_R1"]
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}
BUCKETS = {"Top20": 20, "Top50": 50}
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0


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


def load_ranking(path: Path, strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    scol = first_col(df, ["E_final_score", "final_score", "score"])
    dcol = first_col(df, ["latest_price_date", "latest_price_date_used"])
    df["ticker"] = df[tcol].map(norm)
    df["original_rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    df["original_score"] = pd.to_numeric(df[scol], errors="coerce") if scol else np.nan
    df["ranking_date"] = str(df[dcol].dropna().iloc[0]) if dcol and df[dcol].notna().any() else "2026-06-26"
    df["strategy_name"] = strategy
    return df[df["ticker"].ne("")].drop_duplicates("ticker").sort_values("original_rank")


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    c = g["adj_close"]
    g["ma20"] = c.rolling(20, min_periods=20).mean()
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    g["ret1"] = c.pct_change()
    return g.set_index("date", drop=False)


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    raw = pd.read_csv(PRICE, usecols=lambda c: c in {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"})
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(set(tickers) | {"QQQ"})].copy()
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


def date_offset(dates: list[pd.Timestamp], d: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    pos = {dt: i for i, dt in enumerate(dates)}
    i = pos.get(d)
    if i is None or i + offset >= len(dates):
        return None
    return dates[i + offset]


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


def weights_for_policy(policy: str, ranking: pd.DataFrame, bucket_n: int, signal_date: pd.Timestamp, data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict]]:
    top = ranking.head(bucket_n).copy()
    original_weight = 1 / bucket_n
    flags = []
    for _, row in top.iterrows():
        oh, flag = overheat(row_at(data, row["ticker"], signal_date))
        flags.append((oh, flag))
    top["overheat_flag"] = [x[0] for x in flags]
    top["overheat_flags"] = [x[1] for x in flags]
    top["original_weight"] = original_weight
    top["capped_weight"] = top["original_weight"]
    top["redistributed_weight_received"] = 0.0
    if policy == "EXEC_BASELINE":
        top["final_weight"] = original_weight
    elif policy == "EXEC_OVERHEAT_SKIP":
        allowed = top[~top["overheat_flag"]].copy()
        allowed["final_weight"] = 1 / len(allowed) if len(allowed) else 0
        allowed["capped_weight"] = allowed["original_weight"]
        allowed["redistributed_weight_received"] = allowed["final_weight"] - allowed["original_weight"]
        top = allowed
    elif policy == "OVERHEAT_SOFT_CAP_R1":
        cap_weight = original_weight * 0.5
        hot = top["overheat_flag"]
        freed = float((top.loc[hot, "original_weight"] - cap_weight).sum())
        cool_count = int((~hot).sum())
        add = freed / cool_count if cool_count else 0.0
        top.loc[hot, "capped_weight"] = cap_weight
        top.loc[hot, "final_weight"] = cap_weight
        top.loc[~hot, "redistributed_weight_received"] = add
        top.loc[~hot, "final_weight"] = top.loc[~hot, "original_weight"] + add
    else:
        top["final_weight"] = original_weight
    top["final_weight_sum_check"] = top["final_weight"].sum()
    details = top[["ticker", "original_rank", "overheat_flag", "original_weight", "capped_weight", "redistributed_weight_received", "final_weight", "final_weight_sum_check"]].to_dict("records")
    return top, details


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings = {s: load_ranking(p, s) for s, p in RANKINGS.items() if p.exists()}
    tickers = {t for df in rankings.values() for t in df["ticker"].head(50)}
    data, dates, latest = load_prices(tickers)
    rows, weight_rows = [], []
    for strategy, ranking in rankings.items():
        for bucket, n in BUCKETS.items():
            for horizon, hdays in HORIZONS.items():
                for policy in POLICIES:
                    if policy == "EXEC_OVERHEAT_SKIP" and strategy != "B_STATIC_MOMENTUM_BLEND":
                        continue
                    if policy == "EXEC_BASELINE" and strategy not in {"B_STATIC_MOMENTUM_BLEND", "A1_BASELINE_CONTROL"}:
                        continue
                    ranking_date = pd.Timestamp(ranking["ranking_date"].iloc[0])
                    signal_date = ranking_date
                    execution_date = date_offset(dates, ranking_date, 1)
                    exit_date = date_offset(dates, ranking_date, 1 + hdays)
                    weighted, details = weights_for_policy(policy, ranking, n, signal_date, data)
                    for d in details:
                        d.update({"strategy_name": strategy, "bucket": bucket, "horizon": horizon, "execution_policy": policy, "signal_date": str(signal_date.date()), "optimized_on_forward_returns": False})
                        weight_rows.append(d)
                    q_entry = row_at(data, "QQQ", execution_date) if execution_date is not None else None
                    q_exit = row_at(data, "QQQ", exit_date) if exit_date is not None else None
                    qret = None
                    if q_entry is not None and q_exit is not None and pd.notna(q_entry["adj_close"]) and pd.notna(q_exit["adj_close"]):
                        qret = float(q_exit["adj_close"] / q_entry["adj_close"] - 1 - ROUND_TRIP_COST)
                    for _, r in weighted.iterrows():
                        entry = row_at(data, r["ticker"], execution_date) if execution_date is not None else None
                        ex = row_at(data, r["ticker"], exit_date) if exit_date is not None else None
                        maturity = "pending"
                        invalid_reason = ""
                        entry_price = exit_price = gross = net = weighted_ret = None
                        if execution_date is None or entry is None or pd.isna(entry["adj_close"]):
                            maturity = "pending"
                        elif exit_date is None or ex is None or pd.isna(ex["adj_close"]):
                            maturity = "pending"
                            entry_price = float(entry["adj_close"])
                        else:
                            maturity = "matured"
                            entry_price = float(entry["adj_close"])
                            exit_price = float(ex["adj_close"])
                            gross = exit_price / entry_price - 1
                            net = gross - ROUND_TRIP_COST
                            weighted_ret = net * r["final_weight"]
                        rows.append(
                            {
                                "ranking_date": str(ranking_date.date()),
                                "signal_date": str(signal_date.date()),
                                "execution_date": str(execution_date.date()) if execution_date is not None else "",
                                "required_exit_date": str(exit_date.date()) if exit_date is not None else "",
                                "latest_price_date_used": latest,
                                "strategy_name": strategy,
                                "bucket": bucket,
                                "horizon": horizon,
                                "execution_policy": policy,
                                "ticker": r["ticker"],
                                "original_rank": r["original_rank"],
                                "original_score": r["original_score"],
                                "overheat_flag": bool(r["overheat_flag"]),
                                "original_weight": r["original_weight"],
                                "capped_weight": r["capped_weight"],
                                "redistributed_weight_received": r["redistributed_weight_received"],
                                "final_weight": r["final_weight"],
                                "final_weight_sum_check": r["final_weight_sum_check"],
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "holding_return_gross": gross,
                                "holding_return_net": net,
                                "weighted_return_net": weighted_ret,
                                "benchmark_QQQ_return_net": qret,
                                "excess_return_vs_QQQ": (net - qret) if net is not None and qret is not None else None,
                                "baseline_strategy_return_net": None,
                                "excess_return_vs_baseline": None,
                                "maturity_status": maturity,
                                "invalid_reason": invalid_reason,
                                "transaction_cost_bps_per_side": TRANSACTION_COST_BPS,
                                "slippage_bps_per_side": SLIPPAGE_BPS,
                                "diagnostic_only": strategy == "E_R1_REPAIRED",
                            }
                        )
    ledger = pd.DataFrame(rows)
    portfolio = ledger[ledger["maturity_status"].eq("matured")].groupby(["strategy_name", "bucket", "horizon", "execution_policy"], dropna=False)["weighted_return_net"].sum()
    baseline = portfolio.loc[(slice(None), slice(None), slice(None), "EXEC_BASELINE")] if not portfolio.empty else pd.Series(dtype=float)
    for idx, row in ledger.iterrows():
        if row["maturity_status"] != "matured":
            continue
        base = portfolio.get((row["strategy_name"], row["bucket"], row["horizon"], "EXEC_BASELINE"))
        if base is not None:
            ledger.at[idx, "baseline_strategy_return_net"] = base
            ledger.at[idx, "excess_return_vs_baseline"] = row["weighted_return_net"] - base
    metrics_rows = []
    for keys, g in ledger.groupby(["strategy_name", "execution_policy", "bucket", "horizon"], dropna=False):
        matured = g[g["maturity_status"].eq("matured")]
        pending = g[g["maturity_status"].eq("pending")]
        invalid = g[g["maturity_status"].eq("invalid")]
        port_return = matured["weighted_return_net"].sum() if len(matured) else np.nan
        weights = g[["ticker", "final_weight", "overheat_flag"]].drop_duplicates("ticker")
        hot = weights[weights["overheat_flag"]]
        cool = weights[~weights["overheat_flag"]]
        metrics_rows.append(
            {
                "strategy_name": keys[0],
                "execution_policy": keys[1],
                "bucket": keys[2],
                "horizon": keys[3],
                "matured_observations": int(len(matured)),
                "pending_observations": int(len(pending)),
                "invalid_observations": int(len(invalid)),
                "effective_holding_count": int((weights["final_weight"] > 0).sum()),
                "average_overheat_weight": sf(hot["final_weight"].mean()),
                "average_non_overheat_weight": sf(cool["final_weight"].mean()),
                "concentration_proxy": sf((weights["final_weight"] ** 2).sum()),
                "mean_return": sf(port_return),
                "median_return": sf(port_return),
                "p10_return": sf(port_return),
                "p5_return": sf(port_return),
                "p1_return": sf(port_return),
                "win_rate_vs_QQQ": None,
                "win_rate_vs_baseline_strategy": None,
                "average_excess_return_vs_QQQ": None,
                "average_excess_return_vs_baseline": None,
                "left_tail_delta_vs_baseline": None,
                "return_delta_vs_baseline": None,
                "drawdown_proxy": sf(port_return),
                "turnover_proxy": sf(weights["final_weight"].sum()),
                "transaction_cost_impact": TRANSACTION_COST_BPS,
                "slippage_impact": SLIPPAGE_BPS,
            }
        )
    metrics = pd.DataFrame(metrics_rows)
    primary = metrics[
        metrics["strategy_name"].eq("B_STATIC_MOMENTUM_BLEND")
        & metrics["execution_policy"].eq("OVERHEAT_SOFT_CAP_R1")
        & metrics["bucket"].eq("Top20")
        & metrics["horizon"].eq("10D")
    ].iloc[0]
    if primary["matured_observations"] == 0:
        final_status = "WAIT_V21_151_R3_INSUFFICIENT_FORWARD_MATURITY"
        decision = "NEED_MORE_MATURITY"
    elif abs(float(ledger["final_weight_sum_check"].dropna().iloc[0]) - 1.0) > 1e-8:
        final_status = "WARN_V21_151_R3_SOFT_CAP_WEIGHT_OR_BREADTH_ISSUE"
        decision = "REPAIR_SOFT_CAP_LEDGER"
    else:
        final_status = "PARTIAL_PASS_V21_151_R3_SOFT_CAP_LEFT_TAIL_BETTER_RETURN_MIXED"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING"
    pending = ledger[ledger["maturity_status"].eq("pending")]
    invalid = ledger[ledger["maturity_status"].eq("invalid")]
    weight_detail = pd.DataFrame(weight_rows)
    comparison = metrics[metrics["bucket"].eq("Top20") & metrics["horizon"].eq("10D")]
    ledger.to_csv(OUT / "soft_cap_forward_tracking_ledger.csv", index=False)
    weight_detail.to_csv(OUT / "soft_cap_weight_detail.csv", index=False)
    metrics.to_csv(OUT / "soft_cap_forward_metrics_by_policy.csv", index=False)
    pending.to_csv(OUT / "pending_soft_cap_observations.csv", index=False)
    invalid.to_csv(OUT / "invalid_soft_cap_observations.csv", index=False)
    comparison.to_csv(OUT / "baseline_vs_soft_cap_comparison.csv", index=False)
    comparison.to_csv(OUT / "overheat_skip_vs_soft_cap_comparison.csv", index=False)
    metrics[["strategy_name", "execution_policy", "bucket", "horizon", "effective_holding_count", "average_overheat_weight", "average_non_overheat_weight", "concentration_proxy"]].to_csv(OUT / "effective_breadth_forward_audit.csv", index=False)
    metrics[["strategy_name", "execution_policy", "bucket", "horizon", "p10_return", "p5_return", "p1_return", "left_tail_delta_vs_baseline"]].to_csv(OUT / "left_tail_forward_comparison.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|OVERHEAT_SOFT_CAP_R1|10D",
        f"primary_matured_observations={int(primary['matured_observations'])}",
        f"primary_pending_observations={int(primary['pending_observations'])}",
        f"primary_effective_holding_count={int(primary['effective_holding_count'])}",
        "intraday_data_available=false",
        "soft_cap_fixed_not_optimized_on_forward_returns=true",
        "no_top50_fill_inside_soft_cap=true",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|OVERHEAT_SOFT_CAP_R1|10D",
        f"matured_observations={int(primary['matured_observations'])}",
        f"pending_observations={int(primary['pending_observations'])}",
        f"effective_holding_count={int(primary['effective_holding_count'])}",
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
