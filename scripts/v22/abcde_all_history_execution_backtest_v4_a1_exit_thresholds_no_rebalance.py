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

    # A1 hysteresis: enter when ranked in Top 5; retain while ranked in Top 10.
    # The portfolio has five slots. A new Top-5 name enters only when a current
    # holding has fallen outside A1 Top 10, avoiding forced replacement of a
    # still-valid buffered holding.
    held_a1: List[str] = []
    targets = {}
    for d in dates:
        x = rankings[
            (rankings.signal_date == d) & (rankings.strategy == "A1")
        ].sort_values("rank")
        order = x["ticker"].tolist()
        rank_pos = {t: i + 1 for i, t in enumerate(order)}

        # Exit only after the name is outside current A1 Top 10.
        held_a1 = [t for t in held_a1 if rank_pos.get(t, 10_000) <= 10]

        # Fill any open slots using current A1 Top 5 in rank order.
        for t in order[:5]:
            if t not in held_a1 and len(held_a1) < 5:
                held_a1.append(t)

        # Defensive fallback for incomplete ranking snapshots.
        for t in order[5:10]:
            if t not in held_a1 and len(held_a1) < 5:
                held_a1.append(t)

        held_a1 = sorted(held_a1, key=lambda t: rank_pos.get(t, 10_000))[:5]
        targets[d] = equal_weights(held_a1, 1.0)
        audit_rows.append({
            "policy": "A1_TOP5_HYST_EXIT10_EQ",
            "signal_date": d,
            "selected": ",".join(held_a1),
        })
    policies["A1_TOP5_HYST_EXIT10_EQ"] = targets

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



def run_a1_hyst_fixed_initial_notional(
    rankings: pd.DataFrame,
    prices: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    cost_bps: float,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    entry_fraction_initial: float = 0.10,
) -> BacktestResult:
    """Event-driven A1 policy with no routine rebalancing.

    Rules:
    - Enter only from the current A1 Top 5.
    - Keep an existing position while it remains in A1 Top 10.
    - Sell the entire position after it falls outside A1 Top 10.
    - Each new entry uses exactly ``entry_fraction_initial`` of the original
      starting NAV, not current NAV and not sale proceeds.
    - Existing positions are never resized merely to restore equal weights.
    - Maximum number of concurrent positions is five.
    """
    name = "A1_TOP5_HYST_EXIT10_FIXED_INITIAL_10PCT"
    initial_nav = 1.0
    fixed_entry_notional = initial_nav * float(entry_fraction_initial)
    cost_rate = float(cost_bps) / 10_000.0

    px = prices.set_index(["date", "ticker"])[["open", "close"]].sort_index()

    # Ranking observed after signal-date close, executed next available session open.
    exec_signals: Dict[pd.Timestamp, Tuple[pd.Timestamp, List[str]]] = {}
    a1 = rankings[rankings["strategy"] == "A1"].copy()
    for signal_date, day in a1.groupby("signal_date", sort=True):
        order = day.sort_values("rank")["ticker"].tolist()
        ex = next_session(pd.Timestamp(signal_date), sessions)
        if ex is not None and start_date <= ex <= end_date:
            exec_signals[pd.Timestamp(ex)] = (pd.Timestamp(signal_date), order)

    cash = initial_nav
    shares: Dict[str, float] = {}
    nav_rows: List[dict] = []
    trade_rows: List[dict] = []
    missing_rows: List[dict] = []
    target_rows: List[dict] = []

    previous_close_nav = initial_nav
    total_turnover = 0.0
    total_cost = 0.0
    trade_date_count = 0
    signal_evaluation_count = 0
    active_start = None

    def get_price(date: pd.Timestamp, ticker: str, field: str, fallback_prior: bool = True) -> Optional[float]:
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
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": field,
                        "action": "prior_close_mark",
                    })
                    return val
        return None

    for date in sessions[(sessions >= start_date) & (sessions <= end_date)]:
        date = pd.Timestamp(date)

        if date in exec_signals:
            signal_evaluation_count += 1
            signal_date, order = exec_signals[date]
            top5 = order[:5]
            top10 = set(order[:10])
            rank_pos = {ticker: idx + 1 for idx, ticker in enumerate(order)}

            # NAV immediately before execution, using session open.
            pre_nav = cash
            for ticker, qty in shares.items():
                op = get_price(date, ticker, "open", fallback_prior=True)
                if op is not None:
                    pre_nav += qty * op

            traded_notional_today = 0.0
            cost_today = 0.0
            trades_before = len(trade_rows)

            # 1) Full exit only when outside current Top 10.
            exits = [ticker for ticker in list(shares) if ticker not in top10]
            for ticker in exits:
                op = get_price(date, ticker, "open", fallback_prior=True)
                if op is None:
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": "open",
                        "action": "exit_deferred_missing_open",
                    })
                    continue

                qty = shares.pop(ticker)
                notional = qty * op
                cost = notional * cost_rate
                cash += notional - cost
                traded_notional_today += notional
                cost_today += cost
                trade_rows.append({
                    "policy": name,
                    "signal_date": signal_date,
                    "execution_date": date,
                    "ticker": ticker,
                    "side": "SELL",
                    "notional": notional,
                    "open_price": op,
                    "shares": qty,
                    "cost_allocated": cost,
                    "entry_notional_rule": "FULL_EXIT_OUTSIDE_TOP10",
                    "a1_rank": rank_pos.get(ticker),
                })

            # 2) Fill vacant slots from current Top 5.
            # Every entry is exactly 10% of ORIGINAL NAV, provided cash is sufficient.
            vacancies = max(0, 5 - len(shares))
            candidates = [ticker for ticker in top5 if ticker not in shares]
            for ticker in candidates[:vacancies]:
                op = get_price(date, ticker, "open", fallback_prior=False)
                if op is None:
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": "open",
                        "action": "entry_skipped_missing_open",
                    })
                    continue

                required_cash = fixed_entry_notional * (1.0 + cost_rate)
                if cash + 1e-12 < required_cash:
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": "cash",
                        "action": "entry_skipped_insufficient_cash",
                        "required_cash": required_cash,
                        "available_cash": cash,
                    })
                    continue

                qty = fixed_entry_notional / op
                cost = fixed_entry_notional * cost_rate
                cash -= fixed_entry_notional + cost
                shares[ticker] = qty
                traded_notional_today += fixed_entry_notional
                cost_today += cost
                trade_rows.append({
                    "policy": name,
                    "signal_date": signal_date,
                    "execution_date": date,
                    "ticker": ticker,
                    "side": "BUY",
                    "notional": fixed_entry_notional,
                    "open_price": op,
                    "shares": qty,
                    "cost_allocated": cost,
                    "entry_notional_rule": "10PCT_OF_INITIAL_NAV",
                    "a1_rank": rank_pos.get(ticker),
                })
                if active_start is None:
                    active_start = date

            if len(trade_rows) > trades_before:
                trade_date_count += 1
            total_turnover += traded_notional_today / pre_nav if pre_nav > 0 else 0.0
            total_cost += cost_today

            # Post-trade position audit. These are actual weights, not rebalance targets.
            post_trade_nav_open = cash
            open_values: Dict[str, float] = {}
            for ticker, qty in shares.items():
                op = get_price(date, ticker, "open", fallback_prior=True)
                if op is not None:
                    value = qty * op
                    open_values[ticker] = value
                    post_trade_nav_open += value

            for ticker, value in open_values.items():
                target_rows.append({
                    "policy": name,
                    "signal_date": signal_date,
                    "execution_date": date,
                    "ticker": ticker,
                    "target_weight": value / post_trade_nav_open if post_trade_nav_open > 0 else np.nan,
                    "actual_position_notional_open": value,
                    "a1_rank": rank_pos.get(ticker),
                    "fixed_entry_notional": fixed_entry_notional,
                })
            target_rows.append({
                "policy": name,
                "signal_date": signal_date,
                "execution_date": date,
                "ticker": "CASH",
                "target_weight": cash / post_trade_nav_open if post_trade_nav_open > 0 else np.nan,
                "actual_position_notional_open": cash,
                "a1_rank": np.nan,
                "fixed_entry_notional": fixed_entry_notional,
            })

        close_nav = cash
        gross_exposure = 0.0
        for ticker, qty in shares.items():
            cp = get_price(date, ticker, "close", fallback_prior=True)
            if cp is None:
                continue
            value = qty * cp
            close_nav += value
            gross_exposure += value

        daily_ret = close_nav / previous_close_nav - 1.0 if nav_rows else close_nav - initial_nav
        nav_rows.append({
            "policy": name,
            "date": date,
            "nav": close_nav,
            "daily_return": daily_ret,
            "cash": cash,
            "gross_exposure": gross_exposure,
            "gross_exposure_pct": gross_exposure / close_nav if close_nav > 0 else np.nan,
            "position_count": len(shares),
        })
        previous_close_nav = close_nav

    nav = pd.DataFrame(nav_rows)
    if nav.empty:
        raise ValueError(f"No sessions for policy {name}")

    nav["peak"] = nav["nav"].cummax()
    nav["drawdown"] = nav["nav"] / nav["peak"] - 1.0
    rets = nav["daily_return"]
    ann_vol = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 else np.nan
    ann_ret = (
        float((nav.iloc[-1].nav / nav.iloc[0].nav) ** (252 / max(len(nav) - 1, 1)) - 1)
        if nav.iloc[0].nav > 0
        else np.nan
    )
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(252))
        if len(rets) > 1 and rets.std(ddof=1) > 0
        else np.nan
    )

    summary = {
        "policy": name,
        "start_date": nav.iloc[0].date,
        "active_start_date": active_start,
        "end_date": nav.iloc[-1].date,
        "start_nav": initial_nav,
        "end_nav": float(nav.iloc[-1].nav),
        "total_return": float(nav.iloc[-1].nav - initial_nav),
        "max_drawdown": float(nav["drawdown"].min()),
        "annualized_volatility": ann_vol,
        "annualized_return_short_sample": ann_ret,
        "sharpe_zero_rf_short_sample": sharpe,
        "positive_day_ratio": float((rets > 0).mean()),
        "rebalance_count": trade_date_count,
        "signal_evaluation_count": signal_evaluation_count,
        "cumulative_one_way_turnover": total_turnover,
        "total_transaction_cost_nav": total_cost,
        "average_gross_exposure": float(nav["gross_exposure_pct"].mean()),
        "average_position_count": float(nav["position_count"].mean()),
        "fixed_entry_fraction_initial_nav": float(entry_fraction_initial),
        "routine_rebalancing": False,
    }

    return BacktestResult(
        summary=summary,
        nav=nav.drop(columns=["peak"]),
        trades=pd.DataFrame(trade_rows),
        target_audit=pd.DataFrame(target_rows),
        missing=pd.DataFrame(missing_rows),
    )


def run_a1_top5_exit_threshold_no_rebalance(
    rankings: pd.DataFrame,
    prices: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    cost_bps: float,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    exit_rank: int,
) -> BacktestResult:
    """A1 Top-5 entry / rank-threshold exit with five independent sleeves.

    Execution rules:
    - Rankings are observed after the signal-date close and executed at the next
      available session open.
    - Start with five equal sleeves, each holding 20% of initial NAV in cash.
    - Empty sleeves buy the highest-ranked current A1 Top-5 names not already held.
    - A held name is sold only after its A1 rank is greater than ``exit_rank``
      or it disappears from the available A1 ranking.
    - Sale proceeds remain in the same sleeve and are used for the replacement.
    - Existing holdings are never resized merely to restore equal weights.
    - Therefore there is no routine daily rebalancing.
    """
    exit_rank = int(exit_rank)
    if exit_rank < 5:
        raise ValueError("exit_rank must be at least 5")

    name = f"A1_TOP5_EXIT{exit_rank}_NO_REBAL"
    initial_nav = 1.0
    slot_count = 5
    initial_slot_cash = initial_nav / slot_count
    cost_rate = float(cost_bps) / 10_000.0

    px = prices.set_index(["date", "ticker"])[["open", "close"]].sort_index()

    exec_signals: Dict[pd.Timestamp, Tuple[pd.Timestamp, List[str]]] = {}
    a1 = rankings[rankings["strategy"] == "A1"].copy()
    for signal_date, day in a1.groupby("signal_date", sort=True):
        order = day.sort_values("rank")["ticker"].tolist()
        ex = next_session(pd.Timestamp(signal_date), sessions)
        if ex is not None and start_date <= ex <= end_date:
            exec_signals[pd.Timestamp(ex)] = (pd.Timestamp(signal_date), order)

    # Each sleeve evolves independently, preventing hidden equal-weight resets.
    slots: List[dict] = [
        {"slot_id": i + 1, "ticker": None, "shares": 0.0, "cash": initial_slot_cash}
        for i in range(slot_count)
    ]

    nav_rows: List[dict] = []
    trade_rows: List[dict] = []
    missing_rows: List[dict] = []
    target_rows: List[dict] = []

    previous_close_nav = initial_nav
    total_turnover = 0.0
    total_cost = 0.0
    trade_date_count = 0
    signal_evaluation_count = 0
    active_start = None

    def get_price(
        date: pd.Timestamp,
        ticker: str,
        field: str,
        fallback_prior: bool = True,
    ) -> Optional[float]:
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
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": field,
                        "action": "prior_close_mark",
                    })
                    return val
        return None

    for date in sessions[(sessions >= start_date) & (sessions <= end_date)]:
        date = pd.Timestamp(date)

        if date in exec_signals:
            signal_evaluation_count += 1
            signal_date, order = exec_signals[date]
            top5 = order[:5]
            rank_pos = {ticker: idx + 1 for idx, ticker in enumerate(order)}

            # Portfolio NAV at the execution open, before trades.
            pre_nav = 0.0
            for slot in slots:
                pre_nav += float(slot["cash"])
                if slot["ticker"] is not None:
                    op = get_price(date, slot["ticker"], "open", fallback_prior=True)
                    if op is not None:
                        pre_nav += float(slot["shares"]) * op

            traded_notional_today = 0.0
            cost_today = 0.0
            trades_before = len(trade_rows)

            # 1) Exit only when outside the specified threshold.
            for slot in slots:
                ticker = slot["ticker"]
                if ticker is None:
                    continue

                current_rank = rank_pos.get(ticker, 10_000)
                if current_rank <= exit_rank:
                    continue

                op = get_price(date, ticker, "open", fallback_prior=True)
                if op is None:
                    missing_rows.append({
                        "policy": name,
                        "date": date,
                        "ticker": ticker,
                        "field": "open",
                        "action": "exit_deferred_missing_open",
                        "slot_id": slot["slot_id"],
                    })
                    continue

                qty = float(slot["shares"])
                notional = qty * op
                cost = notional * cost_rate
                slot["cash"] = float(slot["cash"]) + notional - cost
                slot["ticker"] = None
                slot["shares"] = 0.0

                traded_notional_today += notional
                cost_today += cost
                trade_rows.append({
                    "policy": name,
                    "signal_date": signal_date,
                    "execution_date": date,
                    "slot_id": slot["slot_id"],
                    "ticker": ticker,
                    "side": "SELL",
                    "notional": notional,
                    "open_price": op,
                    "shares": qty,
                    "cost_allocated": cost,
                    "a1_rank": None if current_rank == 10_000 else current_rank,
                    "rule": f"EXIT_OUTSIDE_TOP{exit_rank}",
                })

            # 2) Fill empty sleeves from current Top 5 only.
            held = {
                slot["ticker"]
                for slot in slots
                if slot["ticker"] is not None
            }
            candidates = [ticker for ticker in top5 if ticker not in held]
            candidate_idx = 0

            for slot in slots:
                if slot["ticker"] is not None:
                    continue

                while candidate_idx < len(candidates):
                    ticker = candidates[candidate_idx]
                    candidate_idx += 1
                    op = get_price(date, ticker, "open", fallback_prior=False)
                    if op is None:
                        missing_rows.append({
                            "policy": name,
                            "date": date,
                            "ticker": ticker,
                            "field": "open",
                            "action": "entry_skipped_missing_open",
                            "slot_id": slot["slot_id"],
                        })
                        continue

                    available_cash = float(slot["cash"])
                    if available_cash <= 1e-12:
                        break

                    # Spend the sleeve cash including transaction cost.
                    buy_notional = available_cash / (1.0 + cost_rate)
                    cost = buy_notional * cost_rate
                    qty = buy_notional / op

                    slot["ticker"] = ticker
                    slot["shares"] = qty
                    slot["cash"] = max(0.0, available_cash - buy_notional - cost)
                    held.add(ticker)

                    traded_notional_today += buy_notional
                    cost_today += cost
                    trade_rows.append({
                        "policy": name,
                        "signal_date": signal_date,
                        "execution_date": date,
                        "slot_id": slot["slot_id"],
                        "ticker": ticker,
                        "side": "BUY",
                        "notional": buy_notional,
                        "open_price": op,
                        "shares": qty,
                        "cost_allocated": cost,
                        "a1_rank": rank_pos.get(ticker),
                        "rule": "ENTER_CURRENT_TOP5_USING_SLEEVE_PROCEEDS",
                    })
                    if active_start is None:
                        active_start = date
                    break

            if len(trade_rows) > trades_before:
                trade_date_count += 1

            total_turnover += traded_notional_today / pre_nav if pre_nav > 0 else 0.0
            total_cost += cost_today

            # Actual post-trade open weights; no target equal-weight reset.
            post_trade_nav_open = 0.0
            slot_open_values: List[Tuple[dict, float]] = []
            for slot in slots:
                value = float(slot["cash"])
                if slot["ticker"] is not None:
                    op = get_price(date, slot["ticker"], "open", fallback_prior=True)
                    if op is not None:
                        value += float(slot["shares"]) * op
                slot_open_values.append((slot, value))
                post_trade_nav_open += value

            for slot, slot_value in slot_open_values:
                target_rows.append({
                    "policy": name,
                    "signal_date": signal_date,
                    "execution_date": date,
                    "slot_id": slot["slot_id"],
                    "ticker": slot["ticker"] if slot["ticker"] is not None else "CASH",
                    "target_weight": (
                        slot_value / post_trade_nav_open
                        if post_trade_nav_open > 0
                        else np.nan
                    ),
                    "actual_slot_value_open": slot_value,
                    "a1_rank": (
                        rank_pos.get(slot["ticker"])
                        if slot["ticker"] is not None
                        else np.nan
                    ),
                    "exit_rank": exit_rank,
                    "routine_rebalancing": False,
                })

        close_nav = 0.0
        gross_exposure = 0.0
        position_count = 0

        for slot in slots:
            close_nav += float(slot["cash"])
            ticker = slot["ticker"]
            if ticker is None:
                continue

            cp = get_price(date, ticker, "close", fallback_prior=True)
            if cp is None:
                continue

            value = float(slot["shares"]) * cp
            close_nav += value
            gross_exposure += value
            position_count += 1

        daily_ret = (
            close_nav / previous_close_nav - 1.0
            if nav_rows
            else close_nav - initial_nav
        )
        nav_rows.append({
            "policy": name,
            "date": date,
            "nav": close_nav,
            "daily_return": daily_ret,
            "cash": close_nav - gross_exposure,
            "gross_exposure": gross_exposure,
            "gross_exposure_pct": (
                gross_exposure / close_nav if close_nav > 0 else np.nan
            ),
            "position_count": position_count,
            "exit_rank": exit_rank,
        })
        previous_close_nav = close_nav

    nav = pd.DataFrame(nav_rows)
    if nav.empty:
        raise ValueError(f"No sessions for policy {name}")

    nav["peak"] = nav["nav"].cummax()
    nav["drawdown"] = nav["nav"] / nav["peak"] - 1.0
    rets = nav["daily_return"]

    ann_vol = (
        float(rets.std(ddof=1) * np.sqrt(252))
        if len(rets) > 1
        else np.nan
    )
    ann_ret = (
        float(
            (nav.iloc[-1].nav / nav.iloc[0].nav)
            ** (252 / max(len(nav) - 1, 1))
            - 1
        )
        if nav.iloc[0].nav > 0
        else np.nan
    )
    sharpe = (
        float(rets.mean() / rets.std(ddof=1) * np.sqrt(252))
        if len(rets) > 1 and rets.std(ddof=1) > 0
        else np.nan
    )

    summary = {
        "policy": name,
        "start_date": nav.iloc[0].date,
        "active_start_date": active_start,
        "end_date": nav.iloc[-1].date,
        "start_nav": initial_nav,
        "end_nav": float(nav.iloc[-1].nav),
        "total_return": float(nav.iloc[-1].nav - initial_nav),
        "max_drawdown": float(nav["drawdown"].min()),
        "annualized_volatility": ann_vol,
        "annualized_return_short_sample": ann_ret,
        "sharpe_zero_rf_short_sample": sharpe,
        "positive_day_ratio": float((rets > 0).mean()),
        "rebalance_count": trade_date_count,
        "signal_evaluation_count": signal_evaluation_count,
        "cumulative_one_way_turnover": total_turnover,
        "total_transaction_cost_nav": total_cost,
        "average_gross_exposure": float(nav["gross_exposure_pct"].mean()),
        "average_position_count": float(nav["position_count"].mean()),
        "exit_rank": exit_rank,
        "routine_rebalancing": False,
        "initial_slot_fraction": initial_slot_cash,
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

    # Event-driven fixed-notional A1 test requested by the user.
    fixed_result = run_a1_hyst_fixed_initial_notional(
        rankings=rankings,
        prices=prices,
        sessions=sessions,
        cost_bps=args.cost_bps,
        start_date=start_date,
        end_date=end_date,
        entry_fraction_initial=0.10,
    )
    summaries.append(fixed_result.summary)
    navs.append(fixed_result.nav)
    if not fixed_result.trades.empty: trades.append(fixed_result.trades)
    if not fixed_result.target_audit.empty: targets.append(fixed_result.target_audit)
    if not fixed_result.missing.empty: missing.append(fixed_result.missing)

    # A1 Top-5 entry with no routine rebalancing.
    # Compare several exit buffers using identical five-sleeve capital handling.
    for exit_rank in (7, 8, 10, 12, 15):
        threshold_result = run_a1_top5_exit_threshold_no_rebalance(
            rankings=rankings,
            prices=prices,
            sessions=sessions,
            cost_bps=args.cost_bps,
            start_date=start_date,
            end_date=end_date,
            exit_rank=exit_rank,
        )
        summaries.append(threshold_result.summary)
        navs.append(threshold_result.nav)
        if not threshold_result.trades.empty:
            trades.append(threshold_result.trades)
        if not threshold_result.target_audit.empty:
            targets.append(threshold_result.target_audit)
        if not threshold_result.missing.empty:
            missing.append(threshold_result.missing)

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
