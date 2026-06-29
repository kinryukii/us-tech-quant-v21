from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER"
OUT = Path("outputs/v21/V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER")
V128 = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE")
V150 = Path("outputs/v21/V21.150_ENTRY_EXIT_EXECUTION_OVERLAY_GRID")
V149_SUMMARY = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT/V21.149_summary.json")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}
BUCKETS = {"Top20": 20, "Top50": 50}
RANKING_FILES = {
    "A1_BASELINE_CONTROL": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B_STATIC_MOMENTUM_BLEND": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C_DYNAMIC_MOMENTUM_BLEND": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D_WEIGHT_OPTIMIZED_R1": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    "E_R1_REPAIRED": E_R1,
}
PRIMARY = ("B_STATIC_MOMENTUM_BLEND", "EXEC_OVERHEAT_SKIP", "Top20", "10D")


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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
    g["ma50"] = c.rolling(50, min_periods=50).mean()
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    g["ret1"] = c.pct_change()
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
    latest = str(max(dates).date()) if dates else "UNKNOWN"
    return data, dates, latest


def overheat_flags(sig: pd.Series | None) -> tuple[bool, str]:
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


def row_at(data: dict[str, pd.DataFrame], ticker: str, d: pd.Timestamp) -> pd.Series | None:
    df = data.get(ticker)
    if df is None or d not in df.index:
        return None
    row = df.loc[d]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def next_date(dates: list[pd.Timestamp], d: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    pos = {dt: i for i, dt in enumerate(dates)}
    i = pos.get(d)
    if i is None or i + offset >= len(dates):
        return None
    return dates[i + offset]


def qqq_return(data: dict[str, pd.DataFrame], entry_date: pd.Timestamp | None, exit_date: pd.Timestamp | None) -> float | None:
    if entry_date is None or exit_date is None:
        return None
    a = row_at(data, "QQQ", entry_date)
    b = row_at(data, "QQQ", exit_date)
    if a is None or b is None or pd.isna(a["adj_close"]) or pd.isna(b["adj_close"]):
        return None
    return float(b["adj_close"] / a["adj_close"] - 1 - ROUND_TRIP_COST)


def build_configs() -> list[tuple[str, str, str, str]]:
    configs = [
        ("B_STATIC_MOMENTUM_BLEND", "EXEC_OVERHEAT_SKIP", "Top20", "10D"),
        ("B_STATIC_MOMENTUM_BLEND", "EXEC_BASELINE", "Top20", "10D"),
        ("A1_BASELINE_CONTROL", "EXEC_BASELINE", "Top20", "10D"),
        ("A1_BASELINE_CONTROL", "EXEC_OVERHEAT_SKIP", "Top20", "10D"),
        ("C_DYNAMIC_MOMENTUM_BLEND", "EXEC_OVERHEAT_SKIP", "Top20", "10D"),
        ("D_WEIGHT_OPTIMIZED_R1", "EXEC_OVERHEAT_SKIP", "Top20", "10D"),
        ("E_R1_REPAIRED", "EXEC_OVERHEAT_SKIP", "Top20", "10D"),
    ]
    for strat in ["B_STATIC_MOMENTUM_BLEND", "A1_BASELINE_CONTROL", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1", "E_R1_REPAIRED"]:
        configs.append((strat, "EXEC_OVERHEAT_SKIP", "Top50", "10D"))
    for h in ["5D", "20D"]:
        configs.append(("B_STATIC_MOMENTUM_BLEND", "EXEC_OVERHEAT_SKIP", "Top20", h))
    return sorted(set(configs))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    v149 = load_json(V149_SUMMARY)
    rankings = {s: load_ranking(p, s) for s, p in RANKING_FILES.items() if p.exists()}
    tickers = {t for df in rankings.values() for t in df["ticker"].head(50)}
    data, dates, latest = load_prices(tickers)
    ledger_rows = []
    skipped_rows = []
    configs = build_configs()
    for strategy, variant, bucket, horizon in configs:
        if strategy not in rankings:
            continue
        n = BUCKETS[bucket]
        hdays = HORIZONS[horizon]
        ranking = rankings[strategy].head(n)
        ranking_date = pd.Timestamp(ranking["ranking_date"].iloc[0])
        execution_signal_date = ranking_date
        execution_date = next_date(dates, ranking_date, 1)
        exit_date = next_date(dates, ranking_date, 1 + hdays)
        baseline_key = (strategy, "EXEC_BASELINE", bucket, horizon)
        for _, r in ranking.iterrows():
            ticker = r["ticker"]
            sig = row_at(data, ticker, execution_signal_date)
            overheated, flags = overheat_flags(sig)
            entry_allowed = variant == "EXEC_BASELINE" or not overheated
            skip_reason = "" if entry_allowed else flags
            diagnostic_only = bool(strategy == "E_R1_REPAIRED" and v149.get("invalid_trials_materially_bias_results") is True)
            maturity_status = "pending"
            invalid_reason = ""
            entry_price = exit_price = holding_return = qret = None
            if not entry_allowed:
                maturity_status = "invalid"
                invalid_reason = "SKIPPED_ENTRY_OVERHEAT_FILTER"
                skipped_rows.append(
                    {
                        "strategy_name": strategy,
                        "execution_variant": variant,
                        "bucket": bucket,
                        "horizon": horizon,
                        "ticker": ticker,
                        "skip_reason": skip_reason,
                    }
                )
            elif execution_date is not None:
                entry = row_at(data, ticker, execution_date)
                if entry is not None and pd.notna(entry["adj_close"]):
                    entry_price = float(entry["adj_close"])
                if exit_date is not None:
                    ex = row_at(data, ticker, exit_date)
                    if ex is not None and pd.notna(ex["adj_close"]) and entry_price is not None:
                        exit_price = float(ex["adj_close"])
                        holding_return = exit_price / entry_price - 1 - ROUND_TRIP_COST
                        qret = qqq_return(data, execution_date, exit_date)
                        maturity_status = "matured"
                    else:
                        maturity_status = "pending"
                else:
                    maturity_status = "pending"
            row = {
                "ranking_date": str(ranking_date.date()),
                "execution_signal_date": str(execution_signal_date.date()),
                "execution_date": str(execution_date.date()) if execution_date is not None else "",
                "latest_price_date_used": latest,
                "strategy_name": strategy,
                "execution_variant": variant,
                "bucket": bucket,
                "horizon": horizon,
                "ticker": ticker,
                "original_rank": r["original_rank"],
                "original_score": r["original_score"],
                "entry_allowed": entry_allowed,
                "skip_reason": skip_reason,
                "overheat_flags": flags,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "holding_return_net": holding_return,
                "benchmark_QQQ_return_net": qret,
                "excess_return_vs_QQQ": (holding_return - qret) if holding_return is not None and qret is not None else None,
                "baseline_strategy_return_net": None,
                "excess_return_vs_baseline": None,
                "maturity_status": maturity_status,
                "invalid_reason": invalid_reason,
                "transaction_cost_bps_per_side": TRANSACTION_COST_BPS,
                "slippage_bps_per_side": SLIPPAGE_BPS,
                "diagnostic_only": diagnostic_only,
            }
            ledger_rows.append(row)
    ledger = pd.DataFrame(ledger_rows)
    baseline_map = (
        ledger[ledger["execution_variant"].eq("EXEC_BASELINE") & ledger["maturity_status"].eq("matured")]
        .groupby(["strategy_name", "bucket", "horizon"])["holding_return_net"]
        .mean()
        .to_dict()
    )
    for idx, row in ledger.iterrows():
        key = (row["strategy_name"], row["bucket"], row["horizon"])
        base = baseline_map.get(key)
        if base is not None and row["maturity_status"] == "matured":
            ledger.at[idx, "baseline_strategy_return_net"] = base
            ledger.at[idx, "excess_return_vs_baseline"] = row["holding_return_net"] - base
    matured = ledger[ledger["maturity_status"].eq("matured")].copy()
    pending = ledger[ledger["maturity_status"].eq("pending")].copy()
    invalid = ledger[ledger["maturity_status"].eq("invalid")].copy()
    metrics_rows = []
    for keys, g in ledger.groupby(["strategy_name", "execution_variant", "bucket", "horizon"], dropna=False):
        m = g[g["maturity_status"].eq("matured")]
        p = g[g["maturity_status"].eq("pending")]
        inv = g[g["maturity_status"].eq("invalid")]
        returns = m["holding_return_net"].dropna()
        metrics_rows.append(
            {
                "strategy_name": keys[0],
                "execution_variant": keys[1],
                "bucket": keys[2],
                "horizon": keys[3],
                "matured_observations": int(len(m)),
                "pending_observations": int(len(p)),
                "invalid_observations": int(len(inv)),
                "average_entered_holdings": int(g["entry_allowed"].sum()),
                "skipped_entry_count": int((~g["entry_allowed"]).sum()),
                "skipped_entry_rate": sf((~g["entry_allowed"]).mean()),
                "skip_reasons_by_count": "|".join(inv["skip_reason"].value_counts().astype(str).reset_index().agg(":".join, axis=1)) if len(inv) else "",
                "mean_return": sf(returns.mean()),
                "median_return": sf(returns.median()),
                "p10_return": sf(returns.quantile(0.10)) if len(returns) else None,
                "p5_return": sf(returns.quantile(0.05)) if len(returns) else None,
                "p1_return": sf(returns.quantile(0.01)) if len(returns) else None,
                "win_rate_vs_QQQ": sf((m["excess_return_vs_QQQ"] > 0).mean()) if len(m) else None,
                "win_rate_vs_baseline_strategy": sf((m["excess_return_vs_baseline"] > 0).mean()) if len(m) else None,
                "average_excess_return_vs_QQQ": sf(m["excess_return_vs_QQQ"].mean()) if len(m) else None,
                "average_excess_return_vs_baseline": sf(m["excess_return_vs_baseline"].mean()) if len(m) else None,
                "drawdown_proxy": sf(returns.min()) if len(returns) else None,
                "profit_giveback_proxy": None,
                "turnover_proxy": sf(g["entry_allowed"].mean()),
            }
        )
    metrics = pd.DataFrame(metrics_rows)
    left_tail = metrics[["strategy_name", "execution_variant", "bucket", "horizon", "p10_return", "p5_return", "p1_return", "drawdown_proxy"]].copy()
    comparison = metrics[metrics["bucket"].eq("Top20") & metrics["horizon"].eq("10D")].copy()
    primary_metric = metrics[
        metrics["strategy_name"].eq(PRIMARY[0])
        & metrics["execution_variant"].eq(PRIMARY[1])
        & metrics["bucket"].eq(PRIMARY[2])
        & metrics["horizon"].eq(PRIMARY[3])
    ].iloc[0]
    if primary_metric["matured_observations"] == 0:
        final_status = "WAIT_V21_151_INSUFFICIENT_FORWARD_MATURITY"
        final_decision = "NEED_MORE_MATURITY"
    elif primary_metric["invalid_observations"] > primary_metric["matured_observations"]:
        final_status = "WARN_V21_151_INVALID_TRIAL_OR_DATA_QUALITY"
        final_decision = "KEEP_FORWARD_TRACKING"
    else:
        final_status = "PARTIAL_PASS_V21_151_FORWARD_OVERLAY_LEFT_TAIL_BETTER_RETURN_MIXED"
        final_decision = "KEEP_FORWARD_TRACKING"
    ledger.to_csv(OUT / "forward_execution_overlay_ledger.csv", index=False)
    metrics.to_csv(OUT / "matured_forward_metrics_by_variant.csv", index=False)
    pending.to_csv(OUT / "pending_forward_observations.csv", index=False)
    invalid.to_csv(OUT / "invalid_forward_observations.csv", index=False)
    pd.DataFrame(skipped_rows).to_csv(OUT / "skipped_entry_audit.csv", index=False)
    left_tail.to_csv(OUT / "left_tail_forward_comparison.csv", index=False)
    comparison.to_csv(OUT / "baseline_vs_overheat_skip_comparison.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={final_decision}",
        f"latest_price_date_used={latest}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|EXEC_OVERHEAT_SKIP|10D",
        f"primary_matured_observations={int(primary_metric['matured_observations'])}",
        f"primary_pending_observations={int(primary_metric['pending_observations'])}",
        f"primary_invalid_observations={int(primary_metric['invalid_observations'])}",
        "intraday_data_available=false",
        "rank_deterioration_exit_available=false",
        f"transaction_cost_bps_per_side={TRANSACTION_COST_BPS}",
        f"slippage_bps_per_side={SLIPPAGE_BPS}",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.151_EXECUTION_OVERLAY_FORWARD_TRACKING_LEDGER_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={final_decision}",
        f"latest_price_date_used={latest}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|EXEC_OVERHEAT_SKIP|10D",
        f"matured_observations={int(primary_metric['matured_observations'])}",
        f"pending_observations={int(primary_metric['pending_observations'])}",
        f"invalid_observations={int(primary_metric['invalid_observations'])}",
        "intraday_data_available=false",
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
