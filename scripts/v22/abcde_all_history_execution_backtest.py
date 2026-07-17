#!/usr/bin/env python3
"""ABCDE execution-policy backtest using the uploaded historical ranking archive.

Signal convention: ranking is known after the signal-date close and is executed at
next available market-session open. Positions are marked at daily close. No
future data are used to form a target portfolio.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

STRATEGY_ORDER = ["A1", "B", "C", "D", "E"]


def normalize_ticker(value: object) -> str:
    s = str(value).strip().upper()
    if "." in s:
        # Moomoo commonly stores US.AAPL; Yahoo-like tickers can contain BRK.B.
        parts = s.split(".")
        if parts[0] in {"US", "NYSE", "NASDAQ", "AMEX"} and len(parts) >= 2:
            s = ".".join(parts[1:])
    return s.replace("-", ".")


def find_column(columns: Sequence[str], candidates: Sequence[str], *, required: bool = True) -> Optional[str]:
    lower = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    # fuzzy fallback
    for candidate in candidates:
        for key, original in lower.items():
            if candidate.lower() in key:
                return original
    if required:
        raise ValueError(f"Cannot find any of columns {candidates}; available={list(columns)}")
    return None


def load_prices(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    ticker_col = find_column(raw.columns, ["ticker", "symbol", "code", "stock_code", "instrument", "security"])
    date_col = find_column(raw.columns, ["date", "time_key", "datetime", "timestamp", "trade_date", "price_date"])
    open_col = find_column(raw.columns, ["open", "open_price", "qfq_open"])
    close_col = find_column(raw.columns, ["close", "adj_close", "adjusted_close", "close_price", "qfq_close"])
    high_col = find_column(raw.columns, ["high", "high_price", "qfq_high"], required=False)
    low_col = find_column(raw.columns, ["low", "low_price", "qfq_low"], required=False)
    vol_col = find_column(raw.columns, ["volume", "vol"], required=False)

    out = pd.DataFrame({
        "ticker": raw[ticker_col].map(normalize_ticker),
        "date": pd.to_datetime(raw[date_col], errors="coerce").dt.tz_localize(None).dt.normalize(),
        "open": pd.to_numeric(raw[open_col], errors="coerce"),
        "close": pd.to_numeric(raw[close_col], errors="coerce"),
    })
    out["high"] = pd.to_numeric(raw[high_col], errors="coerce") if high_col else np.nan
    out["low"] = pd.to_numeric(raw[low_col], errors="coerce") if low_col else np.nan
    out["volume"] = pd.to_numeric(raw[vol_col], errors="coerce") if vol_col else np.nan
    out = out.dropna(subset=["ticker", "date", "open", "close"])
    out = out[(out["open"] > 0) & (out["close"] > 0)]
    out = out.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    return out.reset_index(drop=True)


def load_rankings(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    needed = {"signal_date", "strategy", "rank", "ticker"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Ranking file missing columns: {sorted(missing)}")
    df = df.copy()
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce").dt.normalize()
    df["strategy"] = df["strategy"].astype(str).str.upper().replace({
        "A1_CONTROL": "A1", "A1_BASELINE_CONTROL": "A1",
        "B_STATIC_MOMENTUM": "B", "B_STATIC_MOMENTUM_BLEND": "B",
        "C_DYNAMIC_MOMENTUM": "C", "C_DYNAMIC_MOMENTUM_BLEND": "C",
        "D_WEIGHT_OPTIMIZED_REFERENCE": "D", "D_WEIGHT_OPTIMIZED_R1": "D",
        "E_R1_DEFENSIVE_REFERENCE": "E", "E_R1": "E",
    })
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce").astype("Int64")
    df["ticker"] = df["ticker"].map(normalize_ticker)
    df = df.dropna(subset=["signal_date", "strategy", "rank", "ticker"])
    df = df.sort_values(["signal_date", "strategy", "rank"]).drop_duplicates(
        ["signal_date", "strategy", "rank"], keep="last"
    )
    return df.reset_index(drop=True)


def next_session(signal_date: pd.Timestamp, sessions: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    pos = sessions.searchsorted(signal_date, side="right")
    return sessions[pos] if pos < len(sessions) else None


def consensus_table(day: pd.DataFrame, top_cutoff: int = 20) -> pd.DataFrame:
    day = day[day["rank"] <= top_cutoff].copy()
    n_strategies = day["strategy"].nunique()
    if n_strategies == 0:
        return pd.DataFrame(columns=["ticker", "score", "coverage", "count", "avg_rank"])
    day["points"] = top_cutoff + 1 - day["rank"].astype(float)
    g = day.groupby("ticker", as_index=False).agg(
        points=("points", "sum"), count=("strategy", "nunique"), avg_rank=("rank", "mean")
    )
    g["score"] = g["points"] / (top_cutoff * n_strategies)
    g["coverage"] = g["count"] / n_strategies
    return g.sort_values(["score", "count", "avg_rank", "ticker"], ascending=[False, False, True, True])


def select_consensus(day: pd.DataFrame, n: int, min_coverage: float = 0.60) -> List[str]:
    tab = consensus_table(day)
    eligible = tab[tab["coverage"] >= min_coverage]
    if len(eligible) < n:
        eligible = tab
    return eligible.head(n)["ticker"].tolist()


def two_snapshot_tables(rankings: pd.DataFrame, min_coverage: float = 0.60) -> Dict[pd.Timestamp, pd.DataFrame]:
    result: Dict[pd.Timestamp, pd.DataFrame] = {}
    prev_scores: Optional[pd.Series] = None
    for d in sorted(rankings["signal_date"].unique()):
        d = pd.Timestamp(d)
        day = rankings[rankings["signal_date"] == d]
        cur = consensus_table(day).set_index("ticker")
        cur_scores = cur["score"]
        if prev_scores is None:
            smooth = cur_scores.copy()
        else:
            names = cur_scores.index.union(prev_scores.index)
            smooth = (cur_scores.reindex(names, fill_value=0.0) + prev_scores.reindex(names, fill_value=0.0)) / 2.0
        tab = pd.DataFrame({"two_score": smooth})
        tab["current_score"] = cur_scores.reindex(tab.index, fill_value=0.0)
        tab["coverage"] = cur["coverage"].reindex(tab.index, fill_value=0.0)
        tab["count"] = cur["count"].reindex(tab.index, fill_value=0.0)
        eligible = tab[tab["coverage"] >= min_coverage]
        if eligible.empty:
            eligible = tab
        result[d] = eligible.sort_values(
            ["two_score", "count", "current_score"], ascending=[False, False, False]
        )
        prev_scores = cur_scores
    return result


def equal_weights(tickers: Sequence[str], exposure: float = 1.0) -> Dict[str, float]:
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return {}
    w = exposure / len(tickers)
    return {t: w for t in tickers}


def rank_weights(tickers: Sequence[str], raw_weights: Sequence[float]) -> Dict[str, float]:
    tickers = list(dict.fromkeys(tickers))
    weights = np.asarray(raw_weights[: len(tickers)], dtype=float)
    weights = weights / weights.sum()
    return dict(zip(tickers, weights.tolist()))


def add_core(weights: Mapping[str, float], qqq_weight: float, total_stock_exposure: Optional[float] = None) -> Dict[str, float]:
    w = dict(weights)
    if total_stock_exposure is not None and w:
        total = sum(w.values())
        w = {k: v * total_stock_exposure / total for k, v in w.items()}
    w["QQQ"] = w.get("QQQ", 0.0) + qqq_weight
    return w


def build_policy_targets(rankings: pd.DataFrame) -> Tuple[Dict[str, Dict[pd.Timestamp, Dict[str, float]]], pd.DataFrame]:
    dates = [pd.Timestamp(x) for x in sorted(rankings["signal_date"].unique())]
    policies: Dict[str, Dict[pd.Timestamp, Dict[str, float]]] = {}
    audit_rows: List[dict] = []

    # Per-strategy portfolios.
    for strategy in STRATEGY_ORDER:
        for n in (3, 5, 10, 20):
            name = f"{strategy}_TOP{n}_EQ"
            targets = {}
            for d in dates:
                x = rankings[(rankings.signal_date == d) & (rankings.strategy == strategy)].sort_values("rank")
                if x.empty:
                    targets[d] = {}  # stays in cash before E exists
                else:
                    selected = x[x["rank"] <= n]["ticker"].tolist()
                    targets[d] = equal_weights(selected, 1.0)
                    audit_rows.append({"policy": name, "signal_date": d, "selected": ",".join(selected)})
            policies[name] = targets

    # Single-snapshot consensus variants.
    for n in (3, 5, 10):
        name = f"CONSENSUS_TOP{n}_EQ"
        targets = {}
        for d in dates:
            day = rankings[rankings.signal_date == d]
            selected = select_consensus(day, n)
            targets[d] = equal_weights(selected, 1.0)
            audit_rows.append({"policy": name, "signal_date": d, "selected": ",".join(selected)})
        policies[name] = targets

    targets = {}
    for d in dates:
        selected = select_consensus(rankings[rankings.signal_date == d], 5)
        targets[d] = rank_weights(selected, [30, 25, 20, 15, 10])
        audit_rows.append({"policy": "CONSENSUS_TOP5_RANK_WEIGHT", "signal_date": d, "selected": ",".join(selected)})
    policies["CONSENSUS_TOP5_RANK_WEIGHT"] = targets

    # Core/satellite risk budgets.
    for stock_exposure, qqq_weight, label in [
        (0.25, 0.50, "CONSENSUS_TOP5_5PCT_QQQ50_CASH25"),
        (0.50, 0.50, "CONSENSUS_TOP5_10PCT_QQQ50"),
    ]:
        targets = {}
        for d in dates:
            selected = select_consensus(rankings[rankings.signal_date == d], 5)
            satellite = equal_weights(selected, stock_exposure)
            targets[d] = add_core(satellite, qqq_weight)
            audit_rows.append({"policy": label, "signal_date": d, "selected": ",".join(selected)})
        policies[label] = targets

    # Two-snapshot confirmation variants.
    two = two_snapshot_tables(rankings)
    for stock_exposure, qqq_weight, label in [
        (1.00, 0.00, "TWO_SNAPSHOT_TOP5_EQ"),
        (0.25, 0.50, "TWO_SNAPSHOT_TOP5_5PCT_QQQ50_CASH25"),
        (0.50, 0.50, "TWO_SNAPSHOT_TOP5_10PCT_QQQ50"),
    ]:
        targets = {}
        for d in dates:
            selected = two[d].head(5).index.tolist()
            satellite = equal_weights(selected, stock_exposure)
            targets[d] = add_core(satellite, qqq_weight) if qqq_weight else satellite
            audit_rows.append({"policy": label, "signal_date": d, "selected": ",".join(selected)})
        policies[label] = targets

    # Hysteresis: enter top 5, keep while top 10, target five names.
    held: List[str] = []
    targets = {}
    for d in dates:
        order = two[d].index.tolist()
        top5, top10 = order[:5], set(order[:10])
        held = [t for t in held if t in top10]
        for t in top5:
            if t not in held and len(held) < 5:
                held.append(t)
        # If still short, fill by current order.
        for t in order:
            if t not in held and len(held) < 5:
                held.append(t)
        # If more than five due to future modifications, rank-prune.
        rank_pos = {t: i for i, t in enumerate(order)}
        held = sorted(held, key=lambda t: rank_pos.get(t, 10_000))[:5]
        satellite = equal_weights(held, 0.25)
        targets[d] = add_core(satellite, 0.50)
        audit_rows.append({"policy": "TWO_SNAPSHOT_HYST_TOP5_EXIT10_QQQ50_CASH25", "signal_date": d, "selected": ",".join(held)})
    policies["TWO_SNAPSHOT_HYST_TOP5_EXIT10_QQQ50_CASH25"] = targets

    # Benchmarks.
    policies["QQQ_BUY_HOLD"] = {d: {"QQQ": 1.0} for d in dates}
    policies["CASH"] = {d: {} for d in dates}
    return policies, pd.DataFrame(audit_rows)


@dataclass
class BacktestResult:
    summary: dict
    nav: pd.DataFrame
    trades: pd.DataFrame
    target_audit: pd.DataFrame
    missing: pd.DataFrame


def run_policy(
    name: str,
    targets_by_signal: Mapping[pd.Timestamp, Mapping[str, float]],
    prices: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    cost_bps: float,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    missing_policy: str = "redistribute",
) -> BacktestResult:
    px = prices.set_index(["date", "ticker"])[["open", "close"]].sort_index()
    exec_targets: Dict[pd.Timestamp, Tuple[pd.Timestamp, Dict[str, float]]] = {}
    for signal_date, target in targets_by_signal.items():
        ex = next_session(pd.Timestamp(signal_date), sessions)
        if ex is not None and start_date <= ex <= end_date:
            exec_targets[ex] = (pd.Timestamp(signal_date), dict(target))

    cash = 1.0
    shares: Dict[str, float] = {}
    nav_rows, trade_rows, missing_rows, target_rows = [], [], [], []
    previous_close_nav = 1.0
    total_turnover = 0.0
    total_cost = 0.0
    rebalance_count = 0
    active_start = None

    for date in sessions[(sessions >= start_date) & (sessions <= end_date)]:
        date = pd.Timestamp(date)
        # Current prices; if held ticker is missing, use latest prior close for marking but flag.
        def get_price(ticker: str, field: str, fallback_prior: bool = True) -> Optional[float]:
            try:
                val = float(px.loc[(date, ticker), field])
                if np.isfinite(val) and val > 0:
                    return val
            except KeyError:
                pass
            if fallback_prior:
                hist = prices[(prices.ticker == ticker) & (prices.date < date)]
                if not hist.empty:
                    val = float(hist.sort_values("date").iloc[-1]["close"])
                    if np.isfinite(val) and val > 0:
                        missing_rows.append({"policy": name, "date": date, "ticker": ticker, "field": field, "action": "prior_close_mark"})
                        return val
            return None

        if date in exec_targets:
            signal_date, raw_target = exec_targets[date]
            # Drop invalid/negative weights and aggregate.
            target = {normalize_ticker(k): float(v) for k, v in raw_target.items() if float(v) > 0}
            # Ensure target total <= 1.
            total_w = sum(target.values())
            if total_w > 1.0000001:
                target = {k: v / total_w for k, v in target.items()}
                total_w = 1.0

            available = {}
            missing_target = []
            for t, w in target.items():
                op = get_price(t, "open", fallback_prior=False)
                if op is None:
                    missing_target.append(t)
                else:
                    available[t] = (w, op)
            for t in missing_target:
                missing_rows.append({"policy": name, "date": date, "ticker": t, "field": "open", "action": missing_policy})

            if missing_target and missing_policy == "error":
                raise ValueError(f"{name} missing open prices on {date.date()}: {missing_target}")
            if missing_target and missing_policy == "redistribute" and available:
                wanted = sum(target.values())
                avail_sum = sum(w for w, _ in available.values())
                available = {t: (w * wanted / avail_sum, op) for t, (w, op) in available.items()}
            elif missing_target and missing_policy == "cash":
                pass

            # Mark old portfolio at open.
            pre_nav = cash
            old_open_values = {}
            for t, sh in shares.items():
                op = get_price(t, "open", fallback_prior=True)
                if op is None:
                    continue
                old_open_values[t] = sh * op
                pre_nav += old_open_values[t]

            preliminary_targets = {t: pre_nav * w for t, (w, _) in available.items()}
            all_names = set(old_open_values) | set(preliminary_targets)
            traded_notional = sum(abs(preliminary_targets.get(t, 0.0) - old_open_values.get(t, 0.0)) for t in all_names)
            cost = traded_notional * cost_bps / 10_000.0
            post_nav = max(0.0, pre_nav - cost)
            final_target_values = {t: post_nav * w for t, (w, _) in available.items()}
            new_shares = {t: final_target_values[t] / available[t][1] for t in final_target_values}
            invested = sum(final_target_values.values())
            new_cash = post_nav - invested

            for t in all_names:
                old_v = old_open_values.get(t, 0.0)
                new_v = final_target_values.get(t, 0.0)
                delta = new_v - old_v
                if abs(delta) > 1e-12:
                    trade_rows.append({
                        "policy": name, "signal_date": signal_date, "execution_date": date,
                        "ticker": t, "side": "BUY" if delta > 0 else "SELL",
                        "notional": abs(delta), "open_price": get_price(t, "open", fallback_prior=True),
                        "cost_allocated": cost * abs(delta) / traded_notional if traded_notional > 0 else 0.0,
                    })
            for t, (w, _) in available.items():
                target_rows.append({"policy": name, "signal_date": signal_date, "execution_date": date, "ticker": t, "target_weight": w})
            target_rows.append({"policy": name, "signal_date": signal_date, "execution_date": date, "ticker": "CASH", "target_weight": max(0.0, 1.0 - sum(w for w, _ in available.values()))})

            shares, cash = new_shares, new_cash
            total_turnover += traded_notional / pre_nav if pre_nav > 0 else 0.0
            total_cost += cost
            rebalance_count += 1
            if active_start is None and available:
                active_start = date

        close_nav = cash
        gross_exposure = 0.0
        for t, sh in shares.items():
            cp = get_price(t, "close", fallback_prior=True)
            if cp is None:
                continue
            val = sh * cp
            close_nav += val
            gross_exposure += val
        daily_ret = close_nav / previous_close_nav - 1.0 if nav_rows else close_nav - 1.0
        nav_rows.append({
            "policy": name, "date": date, "nav": close_nav, "daily_return": daily_ret,
            "cash": cash, "gross_exposure": gross_exposure,
            "gross_exposure_pct": gross_exposure / close_nav if close_nav > 0 else np.nan,
        })
        previous_close_nav = close_nav

    nav = pd.DataFrame(nav_rows)
    if nav.empty:
        raise ValueError(f"No sessions for policy {name}")
    nav["peak"] = nav["nav"].cummax()
    nav["drawdown"] = nav["nav"] / nav["peak"] - 1.0
    rets = nav["daily_return"]
    ann_vol = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 else np.nan
    ann_ret = float((nav.iloc[-1].nav / nav.iloc[0].nav) ** (252 / max(len(nav) - 1, 1)) - 1) if nav.iloc[0].nav > 0 else np.nan
    sharpe = float(rets.mean() / rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 and rets.std(ddof=1) > 0 else np.nan
    summary = {
        "policy": name,
        "start_date": nav.iloc[0].date,
        "active_start_date": active_start,
        "end_date": nav.iloc[-1].date,
        "start_nav": 1.0,
        "end_nav": float(nav.iloc[-1].nav),
        "total_return": float(nav.iloc[-1].nav - 1.0),
        "max_drawdown": float(nav["drawdown"].min()),
        "annualized_volatility": ann_vol,
        "annualized_return_short_sample": ann_ret,
        "sharpe_zero_rf_short_sample": sharpe,
        "positive_day_ratio": float((rets > 0).mean()),
        "rebalance_count": rebalance_count,
        "cumulative_one_way_turnover": total_turnover,
        "total_transaction_cost_nav": total_cost,
        "average_gross_exposure": float(nav["gross_exposure_pct"].mean()),
    }
    return BacktestResult(
        summary=summary,
        nav=nav.drop(columns=["peak"]),
        trades=pd.DataFrame(trade_rows),
        target_audit=pd.DataFrame(target_rows),
        missing=pd.DataFrame(missing_rows),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest ABCDE execution policies on all uploaded ranking history")
    ap.add_argument("--rankings", required=True, type=Path)
    ap.add_argument("--prices", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--start-date", default="2026-06-17")
    ap.add_argument("--end-date", default="2026-07-13")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="one-way transaction cost in basis points")
    ap.add_argument("--missing-price-policy", choices=["redistribute", "cash", "error"], default="redistribute")
    args = ap.parse_args()

    rankings = load_rankings(args.rankings)
    prices = load_prices(args.prices)
    start_date = pd.Timestamp(args.start_date)
    end_date = pd.Timestamp(args.end_date)
    prices = prices[(prices.date >= rankings.signal_date.min()) & (prices.date <= end_date)].copy()
    sessions = pd.DatetimeIndex(sorted(prices[prices.ticker == "QQQ"].date.unique()))
    if sessions.empty:
        # fallback: dates with broadest ticker coverage
        counts = prices.groupby("date").ticker.nunique()
        sessions = pd.DatetimeIndex(sorted(counts[counts >= max(2, int(counts.max() * 0.25))].index))
    sessions = sessions[(sessions >= start_date) & (sessions <= end_date)]
    if sessions.empty:
        raise ValueError("No trading sessions found in requested period")

    policies, selection_audit = build_policy_targets(rankings)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries, navs, trades, targets, missing = [], [], [], [], []
    for name, policy_targets in policies.items():
        result = run_policy(
            name, policy_targets, prices, sessions, args.cost_bps,
            start_date, end_date, args.missing_price_policy,
        )
        summaries.append(result.summary)
        navs.append(result.nav)
        if not result.trades.empty: trades.append(result.trades)
        if not result.target_audit.empty: targets.append(result.target_audit)
        if not result.missing.empty: missing.append(result.missing)

    summary = pd.DataFrame(summaries)
    # Benchmark-relative metrics.
    qqq_ret = float(summary.loc[summary.policy == "QQQ_BUY_HOLD", "total_return"].iloc[0]) if (summary.policy == "QQQ_BUY_HOLD").any() else np.nan
    summary["excess_vs_qqq"] = summary["total_return"] - qqq_ret
    summary = summary.sort_values(["total_return", "max_drawdown"], ascending=[False, False])

    summary.to_csv(args.output_dir / "policy_summary.csv", index=False)
    pd.concat(navs, ignore_index=True).to_csv(args.output_dir / "daily_nav.csv", index=False)
    (pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()).to_csv(args.output_dir / "trades.csv", index=False)
    (pd.concat(targets, ignore_index=True) if targets else pd.DataFrame()).to_csv(args.output_dir / "executed_target_weights.csv", index=False)
    (pd.concat(missing, ignore_index=True) if missing else pd.DataFrame()).to_csv(args.output_dir / "missing_price_audit.csv", index=False)
    selection_audit.to_csv(args.output_dir / "selection_audit.csv", index=False)

    config = {
        "rankings": str(args.rankings), "prices": str(args.prices),
        "start_date": str(start_date.date()), "end_date": str(end_date.date()),
        "cost_bps_one_way": args.cost_bps, "missing_price_policy": args.missing_price_policy,
        "signal_execution": "signal date close -> next available session open",
        "ranking_dates": [str(pd.Timestamp(x).date()) for x in sorted(rankings.signal_date.unique())],
        "ranking_rows": int(len(rankings)), "unique_ranking_tickers": int(rankings.ticker.nunique()),
        "price_rows_used": int(len(prices)), "price_tickers_used": int(prices.ticker.nunique()),
        "sessions": [str(pd.Timestamp(x).date()) for x in sessions],
    }
    (args.output_dir / "run_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    cols = ["policy", "total_return", "max_drawdown", "excess_vs_qqq", "cumulative_one_way_turnover", "rebalance_count", "average_gross_exposure"]
    print("\n=== ABCDE ALL-HISTORY EXECUTION BACKTEST ===")
    print(summary[cols].to_string(index=False, formatters={
        "total_return": "{:.4%}".format,
        "max_drawdown": "{:.4%}".format,
        "excess_vs_qqq": "{:.4%}".format,
        "cumulative_one_way_turnover": "{:.3f}x".format,
        "average_gross_exposure": "{:.2%}".format,
    }))
    print(f"\nOutputs: {args.output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
