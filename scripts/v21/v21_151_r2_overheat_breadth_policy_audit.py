from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT"
OUT = Path("outputs/v21/V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT")
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
POLICIES = [
    "EXEC_BASELINE",
    "OVERHEAT_SKIP_ENTERED_ONLY_REWEIGHT",
    "OVERHEAT_SKIP_CASH_HELD",
    "OVERHEAT_SKIP_TOP50_FILL",
    "OVERHEAT_SOFT_CAP_R1",
    "OVERHEAT_RELAXED_THRESHOLD_R1",
]
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}
BUCKETS = {"Top20": 20, "Top50": 50}
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0
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


def load_rankings() -> dict[str, pd.DataFrame]:
    out = {}
    for strategy, path in RANKINGS.items():
        if not path.exists():
            continue
        df = pd.read_csv(path)
        tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
        rcol = first_col(df, ["rank", "adjusted_rank"])
        scol = first_col(df, ["E_final_score", "final_score", "score"])
        df["ticker"] = df[tcol].map(norm)
        df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
        df["score"] = pd.to_numeric(df[scol], errors="coerce") if scol else np.nan
        out[strategy] = df[df["ticker"].ne("")].drop_duplicates("ticker").sort_values("rank")
    return out


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
    g["ma50"] = c.rolling(50, min_periods=50).mean()
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    return g.set_index("date", drop=False)


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    use = set(tickers) | {"QQQ"}
    raw = pd.read_csv(PRICE, usecols=lambda c: c in {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"})
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(use)].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    for c in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw["adj_close"] = raw["adjusted_close"].fillna(raw["close"])
    data = {sym: add_indicators(g.drop(columns=["symbol"])) for sym, g in raw.groupby("symbol")}
    dates = [pd.Timestamp(d) for d in sorted(raw["date"].dropna().unique())]
    global DATE_POS
    DATE_POS = {d: i for i, d in enumerate(dates)}
    return data, dates, str(max(dates).date())


def eligible_dates(dates: list[pd.Timestamp], data: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    qqq = data.get("QQQ")
    available = [d for i, d in enumerate(dates) if i >= 80 and i < len(dates) - 25 and qqq is not None and d in qqq.index]
    if len(available) <= 20:
        return available
    idx = np.linspace(0, len(available) - 1, 20).round().astype(int)
    return [available[i] for i in sorted(set(idx))]


def row_at(data: dict[str, pd.DataFrame], ticker: str, d: pd.Timestamp) -> pd.Series | None:
    df = data.get(ticker)
    if df is None or d not in df.index:
        return None
    row = df.loc[d]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def date_offset(dates: list[pd.Timestamp], d: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    i = DATE_POS.get(d)
    if i is None or i + offset >= len(dates):
        return None
    return dates[i + offset]


def overheat(sig: pd.Series | None, relaxed: bool = False) -> tuple[bool, str]:
    if sig is None:
        return True, "MISSING_SIGNAL"
    rsi_th, k_th, dist_th, gap_th = (82, 92, 0.15, 0.10) if relaxed else (78, 88, 0.12, 0.08)
    flags = []
    if sf(sig.get("rsi14")) is not None and sig["rsi14"] > rsi_th:
        flags.append(f"RSI_GT_{rsi_th}")
    if sf(sig.get("kdj_k")) is not None and sig["kdj_k"] > k_th:
        flags.append(f"KDJ_K_GT_{k_th}")
    if sf(sig.get("ma20")) not in (None, 0) and sig["adj_close"] / sig["ma20"] - 1 > dist_th:
        flags.append("PRICE_EXTENDED_ABOVE_MA20")
    if sf(sig.get("ret1")) is not None and sig["ret1"] > gap_th:
        flags.append("GAP_UP_PROXY_EXCESSIVE")
    return bool(flags), "|".join(flags)


def ticker_return(data: dict[str, pd.DataFrame], ticker: str, dates: list[pd.Timestamp], asof: pd.Timestamp, hdays: int) -> float | None:
    entry_date = date_offset(dates, asof, 1)
    exit_date = date_offset(dates, asof, 1 + hdays)
    if entry_date is None or exit_date is None:
        return None
    a = row_at(data, ticker, entry_date)
    b = row_at(data, ticker, exit_date)
    if a is None or b is None or pd.isna(a["adj_close"]) or pd.isna(b["adj_close"]):
        return None
    return float(b["adj_close"] / a["adj_close"] - 1 - ROUND_TRIP_COST)


def build_weights(policy: str, ranking: pd.DataFrame, bucket_n: int, asof: pd.Timestamp, data: dict[str, pd.DataFrame]) -> tuple[dict[str, float], dict]:
    top = ranking.head(bucket_n)
    universe = ranking.head(50)
    base_w = 1 / bucket_n
    overheated = {}
    for _, row in universe.iterrows():
        oh, flags = overheat(row_at(data, row["ticker"], asof), relaxed=(policy == "OVERHEAT_RELAXED_THRESHOLD_R1"))
        overheated[row["ticker"]] = (oh, flags, row["rank"])
    if policy == "EXEC_BASELINE":
        return {t: base_w for t in top["ticker"]}, {"skipped": 0, "cash_weight": 0.0, "fill_count": 0, "fill_detail": [], "soft_cap_rows": [], "relaxed_threshold_fixed": False}
    if policy == "OVERHEAT_SKIP_ENTERED_ONLY_REWEIGHT":
        entered = [t for t in top["ticker"] if not overheated[t][0]]
        w = 1 / len(entered) if entered else 0
        return {t: w for t in entered}, {"skipped": bucket_n - len(entered), "cash_weight": 0.0, "fill_count": 0, "fill_detail": [], "soft_cap_rows": [], "relaxed_threshold_fixed": False}
    if policy == "OVERHEAT_SKIP_CASH_HELD":
        entered = [t for t in top["ticker"] if not overheated[t][0]]
        return {t: base_w for t in entered}, {"skipped": bucket_n - len(entered), "cash_weight": (bucket_n - len(entered)) * base_w, "fill_count": 0, "fill_detail": [], "soft_cap_rows": [], "relaxed_threshold_fixed": False}
    if policy == "OVERHEAT_SKIP_TOP50_FILL":
        entered = [t for t in top["ticker"] if not overheated[t][0]]
        fill_detail = []
        for _, row in universe.iloc[bucket_n:].iterrows():
            if len(entered) >= bucket_n:
                break
            t = row["ticker"]
            if not overheated[t][0]:
                entered.append(t)
                fill_detail.append({"fill_ticker": t, "original_rank": row["rank"], "fill_reason": "NON_OVERHEATED_RANK_21_50"})
        w = 1 / len(entered) if entered else 0
        return {t: w for t in entered}, {"skipped": bucket_n - sum(not overheated[t][0] for t in top["ticker"]), "cash_weight": 0.0, "fill_count": len(fill_detail), "fill_detail": fill_detail, "soft_cap_rows": [], "relaxed_threshold_fixed": False}
    if policy == "OVERHEAT_SOFT_CAP_R1":
        cap = base_w * 0.5
        weights = {}
        hot = [t for t in top["ticker"] if overheated[t][0]]
        cool = [t for t in top["ticker"] if not overheated[t][0]]
        freed = len(hot) * (base_w - cap)
        add = freed / len(cool) if cool else 0
        audit = []
        for t in top["ticker"]:
            weights[t] = cap if t in hot else base_w + add
            audit.append({"ticker": t, "overheated": t in hot, "assigned_weight": weights[t], "cap_weight": cap})
        return weights, {"skipped": 0, "cash_weight": 0.0, "fill_count": 0, "fill_detail": [], "soft_cap_rows": audit, "relaxed_threshold_fixed": False}
    if policy == "OVERHEAT_RELAXED_THRESHOLD_R1":
        entered = [t for t in top["ticker"] if not overheated[t][0]]
        w = 1 / len(entered) if entered else 0
        return {t: w for t in entered}, {"skipped": bucket_n - len(entered), "cash_weight": 0.0, "fill_count": 0, "fill_detail": [], "soft_cap_rows": [], "relaxed_threshold_fixed": True}
    return {}, {"skipped": bucket_n, "cash_weight": 1.0, "fill_count": 0, "fill_detail": [], "soft_cap_rows": [], "relaxed_threshold_fixed": False}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rankings = load_rankings()
    tickers = {t for df in rankings.values() for t in df["ticker"].head(50)}
    data, dates, latest = load_prices(tickers)
    asofs = eligible_dates(dates, data)
    rows, fill_rows, soft_rows, relaxed_rows = [], [], [], []
    for strategy, ranking in rankings.items():
        for bucket, n in BUCKETS.items():
            for horizon, hdays in HORIZONS.items():
                for policy in POLICIES:
                    for asof in asofs:
                        weights, audit = build_weights(policy, ranking, n, asof, data)
                        rets = {t: ticker_return(data, t, dates, asof, hdays) for t in weights}
                        valid = {t: r for t, r in rets.items() if r is not None}
                        port_ret = sum(weights[t] * valid[t] for t in valid)
                        qret = ticker_return(data, "QQQ", dates, asof, hdays)
                        concentration = sum(w * w for w in weights.values())
                        rows.append(
                            {
                                "strategy_id": strategy,
                                "bucket": bucket,
                                "horizon": horizon,
                                "policy_variant": policy,
                                "asof_date": str(asof.date()),
                                "effective_holding_count": len(valid),
                                "average_cash_weight": audit["cash_weight"],
                                "concentration_proxy": concentration,
                                "portfolio_return": port_ret if valid or audit["cash_weight"] > 0 else np.nan,
                                "QQQ_return": qret,
                                "win_vs_QQQ": port_ret > qret if qret is not None and valid else False,
                                "turnover_proxy": sum(weights.values()),
                                "skipped_count": audit["skipped"],
                                "fill_count": audit["fill_count"],
                                "insufficient_eligible_replacements": policy == "OVERHEAT_SKIP_TOP50_FILL" and len(weights) < n,
                                "transaction_cost_slippage_impact": ROUND_TRIP_COST * sum(1 for t in weights if t in valid),
                                "diagnostic_only": strategy == "E_R1_REPAIRED",
                            }
                        )
                        for f in audit["fill_detail"]:
                            fill_rows.append({"strategy_id": strategy, "bucket": bucket, "horizon": horizon, "asof_date": str(asof.date()), **f})
                        for s in audit["soft_cap_rows"]:
                            soft_rows.append({"strategy_id": strategy, "bucket": bucket, "horizon": horizon, "asof_date": str(asof.date()), **s})
                        if audit["relaxed_threshold_fixed"]:
                            relaxed_rows.append({"strategy_id": strategy, "bucket": bucket, "horizon": horizon, "asof_date": str(asof.date()), "RSI_threshold": 82, "KDJ_K_threshold": 92, "MA20_extension_threshold": 0.15, "gap_proxy_threshold": 0.10, "optimized_on_forward_returns": False, "effective_holding_count": len(valid)})
    trial = pd.DataFrame(rows)
    base = trial[trial["policy_variant"].eq("EXEC_BASELINE")][["strategy_id", "bucket", "horizon", "asof_date", "portfolio_return"]].rename(columns={"portfolio_return": "baseline_return"})
    trial = trial.merge(base, on=["strategy_id", "bucket", "horizon", "asof_date"], how="left")
    trial["return_delta_vs_baseline"] = trial["portfolio_return"] - trial["baseline_return"]
    trial["win_vs_baseline_strategy"] = trial["return_delta_vs_baseline"] > 0
    metrics = []
    for keys, g in trial.groupby(["strategy_id", "bucket", "horizon", "policy_variant"], dropna=False):
        r = g["portfolio_return"].dropna()
        b = g["baseline_return"].dropna()
        metrics.append(
            {
                "strategy_id": keys[0],
                "bucket": keys[1],
                "horizon": keys[2],
                "policy_variant": keys[3],
                "trial_count": len(g),
                "effective_holding_count": sf(g["effective_holding_count"].mean()),
                "average_cash_weight": sf(g["average_cash_weight"].mean()),
                "concentration_proxy": sf(g["concentration_proxy"].mean()),
                "mean_return": sf(r.mean()),
                "median_return": sf(r.median()),
                "p10_return": sf(r.quantile(0.10)) if len(r) else None,
                "p5_return": sf(r.quantile(0.05)) if len(r) else None,
                "p1_return": sf(r.quantile(0.01)) if len(r) else None,
                "return_delta_vs_baseline": sf((r.mean() - b.mean())) if len(r) and len(b) else None,
                "p5_delta_vs_baseline": sf(r.quantile(0.05) - b.quantile(0.05)) if len(r) and len(b) else None,
                "p1_delta_vs_baseline": sf(r.quantile(0.01) - b.quantile(0.01)) if len(r) and len(b) else None,
                "win_rate_vs_QQQ": sf(g["win_vs_QQQ"].mean()),
                "win_rate_vs_baseline_strategy": sf(g["win_vs_baseline_strategy"].mean()),
                "turnover_proxy": sf(g["turnover_proxy"].mean()),
                "skipped_count": sf(g["skipped_count"].mean()),
                "fill_count": sf(g["fill_count"].mean()),
                "average_original_rank_of_filled_names": None,
                "dates_effective_holdings_below_threshold": int((g["effective_holding_count"] < (15 if keys[1] == "Top20" else 35)).sum()),
                "dates_insufficient_eligible_replacements": int(g["insufficient_eligible_replacements"].sum()),
                "transaction_cost_slippage_impact": sf(g["transaction_cost_slippage_impact"].mean()),
                "diagnostic_only": keys[0] == "E_R1_REPAIRED",
            }
        )
    metrics_df = pd.DataFrame(metrics)
    fills = pd.DataFrame(fill_rows)
    if not fills.empty:
        fill_avg = fills.groupby(["strategy_id", "bucket", "horizon"])["original_rank"].mean().to_dict()
        for idx, row in metrics_df.iterrows():
            if row["policy_variant"] == "OVERHEAT_SKIP_TOP50_FILL":
                metrics_df.at[idx, "average_original_rank_of_filled_names"] = fill_avg.get((row["strategy_id"], row["bucket"], row["horizon"]))
    primary = metrics_df[
        metrics_df["strategy_id"].eq("B_STATIC_MOMENTUM_BLEND")
        & metrics_df["bucket"].eq("Top20")
        & metrics_df["horizon"].eq("10D")
    ].copy()
    entered = primary[primary["policy_variant"].eq("OVERHEAT_SKIP_ENTERED_ONLY_REWEIGHT")].iloc[0]
    topfill = primary[primary["policy_variant"].eq("OVERHEAT_SKIP_TOP50_FILL")].iloc[0]
    cash = primary[primary["policy_variant"].eq("OVERHEAT_SKIP_CASH_HELD")].iloc[0]
    soft = primary[primary["policy_variant"].eq("OVERHEAT_SOFT_CAP_R1")].iloc[0]
    relaxed = primary[primary["policy_variant"].eq("OVERHEAT_RELAXED_THRESHOLD_R1")].iloc[0]
    if topfill["effective_holding_count"] >= 15 and topfill["p5_delta_vs_baseline"] > 0:
        final_status = "PARTIAL_PASS_V21_151_R2_TOP50_FILL_PROMISING"
        decision = "FORWARD_TRACK_TOP50_FILL"
    elif soft["effective_holding_count"] >= 15 and soft["p5_delta_vs_baseline"] > 0:
        final_status = "PASS_V21_151_R2_BREADTH_POLICY_REPAIRED"
        decision = "FORWARD_TRACK_SOFT_CAP"
    elif relaxed["effective_holding_count"] >= 15 and relaxed["p5_delta_vs_baseline"] > 0:
        final_status = "PASS_V21_151_R2_BREADTH_POLICY_REPAIRED"
        decision = "FORWARD_TRACK_RELAXED_THRESHOLD"
    elif cash["p5_delta_vs_baseline"] > 0 and cash["return_delta_vs_baseline"] <= 0:
        final_status = "PARTIAL_PASS_V21_151_R2_CASH_POLICY_LEFT_TAIL_ONLY"
        decision = "FORWARD_TRACK_CASH_HELD"
    elif entered["p5_delta_vs_baseline"] > 0 and entered["effective_holding_count"] < 15:
        final_status = "PARTIAL_PASS_V21_151_R2_ENTERED_ONLY_CONCENTRATION_WARN"
        decision = "KEEP_CURRENT_WITH_LOW_BREADTH_WARN"
    elif primary["p5_delta_vs_baseline"].max() <= 0:
        final_status = "FAIL_V21_151_R2_OVERHEAT_EDGE_NOT_ROBUST"
        decision = "REJECT_OVERHEAT_OVERLAY"
    else:
        final_status = "WARN_V21_151_R2_NO_BREADTH_SAFE_POLICY"
        decision = "KEEP_DIAGNOSTIC_ONLY"
    summary = pd.DataFrame(
        [
            {
                "FINAL_STATUS": final_status,
                "DECISION": decision,
                "current_v21_151_policy": "OVERHEAT_SKIP_ENTERED_ONLY_REWEIGHT_WITH_SKIPPED_AS_INVALID_EXCLUDED",
                "skipped_entries_treated_as_cash": False,
                "implicit_padding_or_filling_applied": False,
                "latest_price_date_used": latest,
                "E_R1_diagnostic_only": True,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "protected_outputs_modified": False,
                "research_only": True,
            }
        ]
    )
    breadth = metrics_df[["strategy_id", "bucket", "horizon", "policy_variant", "effective_holding_count", "concentration_proxy", "dates_effective_holdings_below_threshold", "dates_insufficient_eligible_replacements"]]
    cash_audit = metrics_df[["strategy_id", "bucket", "horizon", "policy_variant", "average_cash_weight", "turnover_proxy", "return_delta_vs_baseline"]]
    soft_df = pd.DataFrame(soft_rows)
    relaxed_df = pd.DataFrame(relaxed_rows)
    if fills.empty:
        fills = pd.DataFrame(columns=["strategy_id", "bucket", "horizon", "asof_date", "fill_ticker", "original_rank", "fill_reason"])
    if soft_df.empty:
        soft_df = pd.DataFrame(columns=["strategy_id", "bucket", "horizon", "asof_date", "ticker", "overheated", "assigned_weight", "cap_weight"])
    if relaxed_df.empty:
        relaxed_df = pd.DataFrame(columns=["strategy_id", "bucket", "horizon", "asof_date", "RSI_threshold", "KDJ_K_threshold", "MA20_extension_threshold", "gap_proxy_threshold", "optimized_on_forward_returns", "effective_holding_count"])
    left_tail = metrics_df[["strategy_id", "bucket", "horizon", "policy_variant", "p10_return", "p5_return", "p1_return", "p5_delta_vs_baseline", "p1_delta_vs_baseline"]]
    summary.to_csv(OUT / "overheat_breadth_policy_summary.csv", index=False)
    metrics_df.to_csv(OUT / "policy_variant_metrics_by_strategy_bucket_horizon.csv", index=False)
    primary.to_csv(OUT / "primary_candidate_policy_comparison.csv", index=False)
    breadth.to_csv(OUT / "effective_holdings_breadth_comparison.csv", index=False)
    cash_audit.to_csv(OUT / "cash_weight_exposure_audit.csv", index=False)
    fills.to_csv(OUT / "top50_fill_detail.csv", index=False)
    soft_df.to_csv(OUT / "soft_cap_weight_audit.csv", index=False)
    relaxed_df.to_csv(OUT / "relaxed_threshold_breadth_audit.csv", index=False)
    left_tail.to_csv(OUT / "left_tail_policy_comparison.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|10D",
        "current_v21_151_policy=entered-only reweight with skipped names invalid/excluded",
        f"entered_only_effective_holding_count={entered['effective_holding_count']}",
        f"cash_policy_p5_delta_vs_baseline={cash['p5_delta_vs_baseline']}",
        f"top50_fill_effective_holding_count={topfill['effective_holding_count']}",
        f"top50_fill_p5_delta_vs_baseline={topfill['p5_delta_vs_baseline']}",
        f"soft_cap_effective_holding_count={soft['effective_holding_count']}",
        f"relaxed_threshold_effective_holding_count={relaxed['effective_holding_count']}",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.151_R2_OVERHEAT_BREADTH_POLICY_AUDIT_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"recommended_forward_policy={decision}",
        f"entered_only_effective_holding_count={entered['effective_holding_count']}",
        f"top50_fill_effective_holding_count={topfill['effective_holding_count']}",
        f"soft_cap_effective_holding_count={soft['effective_holding_count']}",
        f"relaxed_threshold_effective_holding_count={relaxed['effective_holding_count']}",
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
