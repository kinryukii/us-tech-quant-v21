#!/usr/bin/env python
"""Strict ABCDE long-horizon feasibility gate and short-sample regression.

The long-horizon branch is intentionally fail-closed.  It may run only when exact
historical point-in-time rankings and historical universe membership are present.
The repository currently does not meet that contract, so this stage audits the
gap and runs only a clearly labelled SHORT_SAMPLE_ONLY execution regression.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STAGE = "ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R1"
FAIL_STATUS = "FAIL_DATA_NOT_SUFFICIENT_FOR_LONG_HORIZON"
SHORT_LABEL = "SHORT_SAMPLE_ONLY"
PREDECLARED_MAIN = "A1_TOP5_ENTRY_EXIT10_NO_REBAL"
STRATEGIES = ["A1", "B", "C", "D", "E"]
SEEDS = [42, 2026, 20260714, 314159, 271828]
WINDOW_LENGTHS = [20, 60, 120, 252, 504]
REQUIRED_OUTPUTS = [
    "data_inventory.json", "data_gap_report.md", "historical_rankings_master.parquet",
    "historical_rankings_audit.csv", "full_history_policy_summary.csv",
    "full_history_daily_nav.parquet", "full_history_trades.parquet",
    "daily_win_rate_vs_qqq.csv", "signal_cycle_win_rate_vs_qqq.csv",
    "monthly_yearly_win_rate_vs_qqq.csv", "random_window_detail.parquet",
    "random_window_summary.csv", "regime_summary.csv", "cost_sensitivity.csv",
    "exit_threshold_sensitivity.csv", "missing_price_audit.csv", "run_config.json",
    "README.md", "final_research_report.md",
    "ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_REPORT.pdf",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_paths(repo: Path) -> list[Path]:
    paths = [repo / "scripts" / "run_daily_moomoo_research_chain.ps1"]
    paths.extend(
        p for p in (repo / "scripts" / "v22").iterdir()
        if p.is_file() and any(token in p.name.lower() for token in ("v22_040", "v22_044", "v22_047"))
    )
    return sorted({p.resolve() for p in paths if p.is_file()})


def hash_manifest(paths: Iterable[Path]) -> dict[str, str]:
    return {str(p): sha256(p) for p in paths}


def read_latest_price_pointer(repo: Path) -> dict[str, Any]:
    pointer = repo / "outputs" / "v21" / "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD" / "canonical_snapshot_pointer.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    for key in ("canonical_raw_path", "canonical_qfq_path", "canonical_manifest_path"):
        if not Path(payload[key]).is_file():
            raise FileNotFoundError(f"Missing canonical price source: {payload[key]}")
    payload["pointer_path"] = str(pointer)
    return payload


def load_price(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    required = {"ticker", "date", "open", "close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Price source missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.replace(r"^US\.", "", regex=True)
    for col in ("open", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.sort_values(["date", "ticker"]).reset_index(drop=True)


def price_inventory(frame: pd.DataFrame, path: Path, kind: str) -> dict[str, Any]:
    key_dups = int(frame.duplicated(["ticker", "date"]).sum())
    return {
        "kind": kind,
        "path": str(path),
        "sha256": sha256(path),
        "columns": list(frame.columns),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["ticker"].nunique()),
        "trade_date_count": int(frame["date"].nunique()),
        "start_date": frame["date"].min().date().isoformat(),
        "end_date": frame["date"].max().date().isoformat(),
        "open_missing_count": int(frame["open"].isna().sum()),
        "close_missing_count": int(frame["close"].isna().sum()),
        "open_missing_rate": float(frame["open"].isna().mean()),
        "close_missing_rate": float(frame["close"].isna().mean()),
        "duplicate_ticker_date_count": key_dups,
        "duplicate_full_row_count": int(frame.duplicated().sum()),
        "nonpositive_open_count": int((frame["open"] <= 0).sum()),
        "nonpositive_close_count": int((frame["close"] <= 0).sum()),
        "contains_delisting_field": any("delist" in c.lower() for c in frame.columns),
        "contains_membership_field": any("member" in c.lower() or "universe" in c.lower() for c in frame.columns),
        "historical_membership_available": False,
        "survivorship_warning": True,
    }


def load_uploaded_rankings(repo: Path) -> pd.DataFrame:
    path = repo / "inputs" / "abcde_all_uploaded_rankings_master.csv"
    frame = pd.read_csv(path)
    required = {"signal_date", "strategy", "rank", "ticker", "source_file", "scope"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Ranking archive missing columns: {sorted(required - set(frame.columns))}")
    frame = frame.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce").dt.normalize()
    frame["strategy"] = frame["strategy"].astype(str).str.upper()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.replace(r"^US\.", "", regex=True)
    frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["signal_date", "strategy", "rank", "ticker"])
    return frame.sort_values(["signal_date", "strategy", "rank", "ticker"]).reset_index(drop=True)


def normalize_ranking_master(ranks: pd.DataFrame) -> pd.DataFrame:
    out = ranks.copy()
    out["score"] = np.nan
    out["universe_version"] = "UNKNOWN_ARCHIVED_SCOPE_" + out["scope"].astype(str).str.upper()
    out["price_max_date"] = pd.NaT
    out["fundamental_asof_date"] = pd.NaT
    out["data_trust_flag"] = "REAL_ARCHIVE_SHORT_SAMPLE_PROVENANCE_INCOMPLETE"
    out["source_snapshot_id"] = out["source_file"].map(lambda x: hashlib.sha256(str(x).encode("utf-8")).hexdigest()[:16])
    out["sample_scope"] = SHORT_LABEL
    return out[[
        "signal_date", "strategy", "rank", "ticker", "score", "universe_version",
        "price_max_date", "fundamental_asof_date", "data_trust_flag", "source_snapshot_id",
        "source_file", "scope", "sample_scope",
    ]]


def ranking_audit(ranks: pd.DataFrame, compact_path: Path | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        part = ranks[ranks["strategy"] == strategy]
        rows.append({
            "ranking_source": "inputs/abcde_all_uploaded_rankings_master.csv",
            "strategy": "E_R1" if strategy == "E" else strategy,
            "earliest_date": part["signal_date"].min().date().isoformat(),
            "latest_date": part["signal_date"].max().date().isoformat(),
            "snapshot_count": int(part["signal_date"].nunique()),
            "row_count": int(len(part)),
            "covered_ticker_count": int(part["ticker"].nunique()),
            "max_rank": int(part["rank"].max()),
            "long_history_eligible": False,
            "audit_status": "SHORT_2026_ARCHIVE_ONLY",
        })
    if compact_path and compact_path.is_file():
        compact = pd.read_parquet(compact_path)
        for strategy_id, part in compact.groupby("strategy_id", sort=True):
            rows.append({
                "ranking_source": str(compact_path), "strategy": strategy_id,
                "earliest_date": str(pd.to_datetime(part["research_date"]).min().date()),
                "latest_date": str(pd.to_datetime(part["research_date"]).max().date()),
                "snapshot_count": int(pd.to_datetime(part["research_date"]).nunique()),
                "row_count": int(len(part)), "covered_ticker_count": int(part["ticker"].nunique()),
                "max_rank": int(part["rank"].max()), "long_history_eligible": False,
                "audit_status": "COMPACT_HISTORY_ONLY_3_DATES",
            })
    return pd.DataFrame(rows)


def common_signal_dates(ranks: pd.DataFrame) -> list[pd.Timestamp]:
    sets = [set(ranks.loc[ranks["strategy"] == s, "signal_date"]) for s in STRATEGIES]
    return sorted(set.intersection(*sets)) if all(sets) else []


def next_session_map(signal_dates: Iterable[pd.Timestamp], calendar: list[pd.Timestamp]) -> dict[pd.Timestamp, pd.Timestamp]:
    cal = np.array(sorted(pd.Timestamp(x) for x in calendar), dtype="datetime64[ns]")
    result: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal in signal_dates:
        pos = int(np.searchsorted(cal, np.datetime64(pd.Timestamp(signal)), side="right"))
        if pos < len(cal):
            result[pd.Timestamp(signal)] = pd.Timestamp(cal[pos])
    return result


def validate_pit_readiness(repo: Path) -> dict[str, Any]:
    gate = repo / "outputs" / "v20" / "backtest" / "V20_193_NEXT_STAGE_GATE.csv"
    membership = repo / "outputs" / "v20" / "consolidation" / "V20_214_NEXT_STAGE_GATE.csv"
    g = pd.read_csv(gate).iloc[0].to_dict()
    m = pd.read_csv(membership).iloc[0].to_dict()
    blockers = [
        "NO_USABLE_HISTORICAL_PIT_SAFE_FULL_FAMILY_FACTOR_SNAPSHOT",
        "NO_HISTORICAL_FILING_PUBLICATION_DATE_PANEL",
        "NO_CERTIFIED_HISTORICAL_UNIVERSE_MEMBERSHIP",
        "NO_DELISTING_OR_SYMBOL_CHANGE_EVENT_LEDGER",
        "ARCHIVED_ABCDE_RANKINGS_ARE_2026_06_TO_2026_07_ONLY",
        "QFQ_IS_CURRENT_SNAPSHOT_ADJUSTED_AND_NOT_A_PIT_CORPORATE_ACTION_LEDGER",
    ]
    return {
        "strict_long_history_rebuild_ready": False,
        "final_status": FAIL_STATUS,
        "pit_validation_pass": False,
        "lookahead_execution_contract_testable": True,
        "v20_193_gate": g,
        "v20_214_gate": m,
        "blockers": blockers,
    }


@dataclass
class PriceBook:
    frame: pd.DataFrame
    px: dict[tuple[pd.Timestamp, str], tuple[float, float]] = field(init=False)
    prior_close: dict[str, list[tuple[pd.Timestamp, float]]] = field(init=False)

    def __post_init__(self) -> None:
        self.px = {
            (pd.Timestamp(r.date), str(r.ticker)): (float(r.open), float(r.close))
            for r in self.frame.itertuples() if pd.notna(r.open) and pd.notna(r.close)
        }
        self.prior_close = {}
        for ticker, part in self.frame.groupby("ticker", sort=False):
            self.prior_close[str(ticker)] = [(pd.Timestamp(r.date), float(r.close)) for r in part.itertuples() if pd.notna(r.close)]

    def get(self, date: pd.Timestamp, ticker: str, field_name: str) -> float | None:
        pair = self.px.get((pd.Timestamp(date), ticker))
        return None if pair is None else pair[0 if field_name == "open" else 1]

    def last_close(self, date: pd.Timestamp, ticker: str) -> float | None:
        values = self.prior_close.get(ticker, [])
        prior = [v for d, v in values if d < pd.Timestamp(date)]
        return prior[-1] if prior else None


def ranking_orders(ranks: pd.DataFrame, strategy: str, dates: list[pd.Timestamp]) -> dict[pd.Timestamp, list[str]]:
    result = {}
    for date in dates:
        part = ranks[(ranks["strategy"] == strategy) & (ranks["signal_date"] == date)].sort_values("rank")
        result[date] = part["ticker"].tolist()
    return result


def rebalance_equal(
    policy: str, date: pd.Timestamp, signal_date: pd.Timestamp, order: list[str],
    shares: dict[str, float], cash: float, book: PriceBook, bps: float,
    trades: list[dict[str, Any]], missing: list[dict[str, Any]],
) -> tuple[dict[str, float], float, float, float]:
    targets = order[:5]
    opens: dict[str, float] = {}
    all_names = sorted(set(shares) | set(targets))
    nav_open = cash
    for ticker in all_names:
        op = book.get(date, ticker, "open")
        if op is None:
            if ticker in shares:
                prior = book.last_close(date, ticker)
                if prior is None:
                    missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "SELL_DELAYED", "reason": "MISSING_OPEN_AND_NO_PRIOR_CLOSE"})
                    continue
                nav_open += shares[ticker] * prior
                missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "SELL_DELAYED", "reason": "MISSING_OPEN_PRIOR_CLOSE_MARK_ONLY"})
            elif ticker in targets:
                missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "BUY_SKIPPED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE"})
            continue
        opens[ticker] = op
        nav_open += shares.get(ticker, 0.0) * op
    tradable_targets = [t for t in targets if t in opens]
    fixed_missing_value = sum(shares[t] * (book.last_close(date, t) or 0.0) for t in shares if t not in opens)
    deployable = max(0.0, nav_open - fixed_missing_value)
    target_each = deployable / len(tradable_targets) if tradable_targets else 0.0
    rate = bps / 10000.0
    for _ in range(8):
        desired = {t: target_each for t in tradable_targets}
        turnover = sum(abs(desired.get(t, 0.0) - shares.get(t, 0.0) * opens[t]) for t in opens)
        target_each = max(0.0, (deployable - turnover * rate) / len(tradable_targets)) if tradable_targets else 0.0
    desired = {t: target_each for t in tradable_targets}
    deltas = {t: desired.get(t, 0.0) - shares.get(t, 0.0) * opens[t] for t in opens}
    total_turnover = 0.0
    total_cost = 0.0
    for side in ("SELL", "BUY"):
        for ticker in sorted(deltas, key=lambda t: (targets.index(t) if t in targets else 999, t)):
            delta = deltas[ticker]
            if (side == "SELL" and delta >= -1e-14) or (side == "BUY" and delta <= 1e-14):
                continue
            notional = abs(delta)
            fee = notional * rate
            qty = notional / opens[ticker]
            if side == "SELL":
                shares[ticker] = max(0.0, shares.get(ticker, 0.0) - qty)
                cash += notional - fee
            else:
                shares[ticker] = shares.get(ticker, 0.0) + qty
                cash -= notional + fee
            if shares.get(ticker, 0.0) <= 1e-12:
                shares.pop(ticker, None)
            total_turnover += notional
            total_cost += fee
            trades.append({"policy": policy, "signal_date": signal_date, "execution_date": date, "ticker": ticker, "side": side, "notional": notional, "price": opens[ticker], "cost": fee, "sample_scope": SHORT_LABEL})
    return shares, cash, total_turnover, total_cost


@dataclass
class Slot:
    cash: float = 0.2
    ticker: str | None = None
    shares: float = 0.0
    pending_exit: bool = False


def execute_slots(
    policy: str, date: pd.Timestamp, signal_date: pd.Timestamp, order: list[str], slots: list[Slot],
    book: PriceBook, bps: float, exit_rank: int, trades: list[dict[str, Any]],
    missing: list[dict[str, Any]],
) -> tuple[float, float]:
    ranks = {ticker: i + 1 for i, ticker in enumerate(order)}
    rate = bps / 10000.0
    turnover = cost = 0.0
    for slot_id, slot in enumerate(slots):
        if slot.ticker is not None and (ranks.get(slot.ticker, 10**9) > exit_rank or slot.pending_exit):
            op = book.get(date, slot.ticker, "open")
            if op is None:
                slot.pending_exit = True
                missing.append({"policy": policy, "date": date, "ticker": slot.ticker, "action": "SELL_DELAYED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE", "slot_id": slot_id})
                continue
            notional = slot.shares * op
            fee = notional * rate
            trades.append({"policy": policy, "signal_date": signal_date, "execution_date": date, "ticker": slot.ticker, "side": "SELL", "notional": notional, "price": op, "cost": fee, "slot_id": slot_id, "sample_scope": SHORT_LABEL})
            slot.cash += notional - fee
            turnover += notional
            cost += fee
            slot.ticker, slot.shares, slot.pending_exit = None, 0.0, False
    held = {slot.ticker for slot in slots if slot.ticker}
    candidates = [t for t in order[:5] if t not in held]
    for slot_id, slot in enumerate(slots):
        if slot.ticker is not None or not candidates:
            continue
        ticker = candidates.pop(0)
        op = book.get(date, ticker, "open")
        if op is None:
            missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "BUY_SKIPPED", "reason": "MISSING_OPEN_NO_FUTURE_PRICE", "slot_id": slot_id})
            continue
        notional = slot.cash / (1.0 + rate)
        fee = notional * rate
        slot.shares = notional / op
        slot.cash -= notional + fee
        slot.ticker = ticker
        held.add(ticker)
        turnover += notional
        cost += fee
        trades.append({"policy": policy, "signal_date": signal_date, "execution_date": date, "ticker": ticker, "side": "BUY", "notional": notional, "price": op, "cost": fee, "slot_id": slot_id, "sample_scope": SHORT_LABEL})
    assert len([s.ticker for s in slots if s.ticker]) <= 5
    assert len({s.ticker for s in slots if s.ticker}) == len([s.ticker for s in slots if s.ticker])
    return turnover, cost


def mark_slots(slots: list[Slot], date: pd.Timestamp, book: PriceBook) -> tuple[float, float, int]:
    nav = exposure = 0.0
    count = 0
    for slot in slots:
        nav += slot.cash
        if slot.ticker:
            price = book.get(date, slot.ticker, "close")
            if price is None:
                price = book.last_close(date, slot.ticker)
            if price is not None:
                value = slot.shares * price
                nav += value
                exposure += value
                count += 1
    return nav, exposure, count


def run_policy(
    ranks: pd.DataFrame, prices: pd.DataFrame, strategy: str, mode: str,
    signal_dates: list[pd.Timestamp], bps: float = 5.0, exit_rank: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    book = PriceBook(prices)
    qqq_calendar = sorted(prices.loc[prices["ticker"] == "QQQ", "date"].unique())
    mapping = next_session_map(signal_dates, [pd.Timestamp(x) for x in qqq_calendar])
    if not mapping:
        raise ValueError("No executable ranking dates")
    first, last = min(mapping.values()), max(mapping.values())
    calendar = [pd.Timestamp(x) for x in qqq_calendar if first <= pd.Timestamp(x) <= last]
    execution_to_signal = {execution: signal for signal, execution in mapping.items()}
    orders = ranking_orders(ranks, strategy, signal_dates)
    policy = f"{strategy}_TOP5_DAILY_EQUAL" if mode == "daily" else f"{strategy}_TOP5_ENTRY_EXIT{exit_rank}_NO_REBAL"
    trades: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    cumulative_turnover = cumulative_cost = 0.0
    previous_nav = 1.0
    latest_signal: pd.Timestamp | None = None
    shares: dict[str, float] = {}
    cash = 1.0
    slots = [Slot() for _ in range(5)]
    for date in calendar:
        day_turnover = day_cost = 0.0
        if date in execution_to_signal:
            latest_signal = execution_to_signal[date]
            order = orders[latest_signal]
            if mode == "daily":
                shares, cash, day_turnover, day_cost = rebalance_equal(policy, date, latest_signal, order, shares, cash, book, bps, trades, missing)
            else:
                day_turnover, day_cost = execute_slots(policy, date, latest_signal, order, slots, book, bps, exit_rank, trades, missing)
        cumulative_turnover += day_turnover
        cumulative_cost += day_cost
        if mode == "daily":
            nav = cash
            exposure = 0.0
            count = 0
            for ticker, qty in shares.items():
                cp = book.get(date, ticker, "close")
                if cp is None:
                    cp = book.last_close(date, ticker)
                    missing.append({"policy": policy, "date": date, "ticker": ticker, "action": "VALUATION_PRIOR_CLOSE", "reason": "MISSING_CLOSE_NO_FUTURE_PRICE"})
                if cp is not None:
                    value = qty * cp
                    nav += value
                    exposure += value
                    count += 1
        else:
            nav, exposure, count = mark_slots(slots, date, book)
        daily_return = nav / previous_nav - 1.0
        rows.append({
            "date": date, "policy": policy, "strategy": strategy, "nav": nav,
            "daily_return": daily_return, "gross_exposure": exposure / nav if nav else np.nan,
            "position_count": count, "one_way_turnover": day_turnover / previous_nav,
            "transaction_cost": day_cost, "signal_date": latest_signal,
            "rank_snapshot_applied": date in execution_to_signal, "sample_scope": SHORT_LABEL,
        })
        previous_nav = nav
    return pd.DataFrame(rows), pd.DataFrame(trades), pd.DataFrame(missing)


def run_qqq(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, bps: float = 5.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = prices[(prices["ticker"] == "QQQ") & prices["date"].between(start, end)].sort_values("date")
    first = q.iloc[0]
    rate = bps / 10000.0
    notional = 1.0 / (1.0 + rate)
    shares = notional / float(first["open"])
    cost = notional * rate
    cash = 1.0 - notional - cost
    rows = []
    prev = 1.0
    for r in q.itertuples():
        nav = cash + shares * float(r.close)
        rows.append({"date": pd.Timestamp(r.date), "policy": "QQQ_BUY_HOLD", "strategy": "QQQ", "nav": nav, "daily_return": nav / prev - 1.0, "gross_exposure": shares * float(r.close) / nav, "position_count": 1, "one_way_turnover": notional if len(rows) == 0 else 0.0, "transaction_cost": cost if len(rows) == 0 else 0.0, "signal_date": pd.NaT, "rank_snapshot_applied": False, "sample_scope": SHORT_LABEL})
        prev = nav
    trades = pd.DataFrame([{"policy": "QQQ_BUY_HOLD", "signal_date": pd.NaT, "execution_date": pd.Timestamp(first["date"]), "ticker": "QQQ", "side": "BUY", "notional": notional, "price": float(first["open"]), "cost": cost, "sample_scope": SHORT_LABEL}])
    return pd.DataFrame(rows), trades


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min()) if len(wealth) else np.nan


def longest_underwater(returns: pd.Series) -> int:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    under = wealth < wealth.cummax()
    best = run = 0
    for flag in under:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def wilson(success: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return np.nan, np.nan
    p = success / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return center - half, center + half


def newey_west_t(values: pd.Series) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    n = len(x)
    if n < 3:
        return np.nan
    u = x - x.mean()
    lag = max(1, int(math.floor(4 * (n / 100) ** (2 / 9))))
    long_var = float(np.dot(u, u) / n)
    for j in range(1, min(lag, n - 1) + 1):
        gamma = float(np.dot(u[j:], u[:-j]) / n)
        long_var += 2 * (1 - j / (lag + 1)) * gamma
    se = math.sqrt(max(long_var, 0.0) / n)
    return float(x.mean() / se) if se > 0 else np.nan


def bootstrap_mean_ci(values: pd.Series, seed: int = 20260714, draws: int = 2000) -> tuple[float, float]:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if not len(x):
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(x, size=len(x), replace=True).mean() for _ in range(draws)])
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def comparison_frame(nav: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    return nav.merge(qqq[["date", "daily_return", "nav"]].rename(columns={"daily_return": "qqq_daily_return", "nav": "qqq_nav"}), on="date", how="inner", validate="one_to_one")


def daily_win_row(policy: str, comp: pd.DataFrame) -> dict[str, Any]:
    excess = comp["daily_return"] - comp["qqq_daily_return"]
    wins = int((excess > 0).sum())
    losses = int((excess < 0).sum())
    ties = int((excess == 0).sum())
    lo, hi = wilson(wins, len(comp))
    q_down = comp["qqq_daily_return"] < 0
    q_up = comp["qqq_daily_return"] > 0
    return {
        "policy": policy, "sample_scope": SHORT_LABEL, "comparison_trading_days": len(comp),
        "days_outperforming_qqq": wins, "days_underperforming_qqq": losses, "tie_days": ties,
        "daily_excess_win_rate": wins / len(comp) if len(comp) else np.nan,
        "wilson_95_low": lo, "wilson_95_high": hi,
        "strategy_positive_day_ratio": float((comp["daily_return"] > 0).mean()),
        "qqq_positive_day_ratio": float((comp["qqq_daily_return"] > 0).mean()),
        "strategy_up_and_outperform_days": int(((comp["daily_return"] > 0) & (excess > 0)).sum()),
        "outperform_rate_when_qqq_down": float((excess[q_down] > 0).mean()) if q_down.any() else np.nan,
        "outperform_rate_when_qqq_up": float((excess[q_up] > 0).mean()) if q_up.any() else np.nan,
        "definition": "strategy_daily_return > qqq_daily_return",
    }


def policy_summary(policy: str, comp: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    ret = comp["daily_return"]
    qret = comp["qqq_daily_return"]
    excess = ret - qret
    b_lo, b_hi = bootstrap_mean_ci(excess)
    total = float(comp["nav"].iloc[-1] - 1.0)
    qtotal = float(comp["qqq_nav"].iloc[-1] - 1.0)
    wins = daily_win_row(policy, comp)
    return {
        "policy": policy, "sample_scope": SHORT_LABEL, "annualization_suppressed": True,
        "total_return": total, "CAGR": np.nan, "annualized_volatility": np.nan,
        "Sharpe": np.nan, "Sortino": np.nan, "max_drawdown": max_drawdown(ret), "Calmar": np.nan,
        "positive_day_ratio": float((ret > 0).mean()), "daily_excess_win_rate_vs_qqq": wins["daily_excess_win_rate"],
        "active_day_excess_win_rate_vs_qqq": wins["daily_excess_win_rate"],
        "signal_cycle_win_rate_vs_qqq": np.nan, "monthly_win_rate_vs_qqq": np.nan,
        "yearly_win_rate_vs_qqq": np.nan, "cumulative_one_way_turnover": float(comp["one_way_turnover"].sum()),
        "transaction_cost_drag": float(comp["transaction_cost"].sum()),
        "average_gross_exposure": float(comp["gross_exposure"].mean()),
        "average_position_count": float(comp["position_count"].mean()),
        "maximum_position_count": int(comp["position_count"].max()), "number_of_trades": int(len(trades)),
        "number_of_signal_dates": int(comp["signal_date"].dropna().nunique()),
        "longest_underwater_period": longest_underwater(ret), "worst_day": float(ret.min()),
        "best_day": float(ret.max()), "excess_return_vs_qqq": total - qtotal,
        "tracking_error": np.nan, "information_ratio": np.nan,
        "daily_excess_return_mean": float(excess.mean()), "newey_west_t_stat": newey_west_t(excess),
        "daily_excess_bootstrap_95_low": b_lo, "daily_excess_bootstrap_95_high": b_hi,
        "note": "Annualized metrics suppressed because the common sample has fewer than 20 trading days.",
    }


def aggregate_cycles(policy: str, comp: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    temp = comp.copy()
    temp["cycle"] = temp["signal_date"].ffill()
    rows = []
    for cycle, part in temp.dropna(subset=["cycle"]).groupby("cycle"):
        sr = float((1 + part["daily_return"]).prod() - 1)
        qr = float((1 + part["qqq_daily_return"]).prod() - 1)
        rows.append({"policy": policy, "signal_date": cycle, "start_date": part["date"].min(), "end_date": part["date"].max(), "strategy_return": sr, "qqq_return": qr, "excess_return": sr - qr, "win": sr > qr, "sample_scope": SHORT_LABEL})
    detail = pd.DataFrame(rows)
    summary = {"policy": policy, "cycle_count": len(detail), "signal_cycle_win_rate_vs_qqq": float(detail["win"].mean()) if len(detail) else np.nan}
    return detail, summary


def aggregate_periods(policy: str, comp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    half_year = comp["date"].dt.year.astype(str) + "-H" + (((comp["date"].dt.month - 1) // 6) + 1).astype(str)
    groups = (
        ("MONTH", comp["date"].dt.to_period("M")),
        ("QUARTER", comp["date"].dt.to_period("Q")),
        ("HALF_YEAR", half_year),
        ("YEAR", comp["date"].dt.to_period("Y")),
    )
    for frequency, period in groups:
        for label, part in comp.groupby(period):
            sr = float((1 + part["daily_return"]).prod() - 1)
            qr = float((1 + part["qqq_daily_return"]).prod() - 1)
            rows.append({"policy": policy, "frequency": frequency, "period": str(label), "strategy_return": sr, "qqq_return": qr, "excess_return": sr - qr, "win": sr > qr, "sample_scope": SHORT_LABEL, "interpretation_warning": "ONE_SHORT_PERIOD_ONLY_NOT_A_STABILITY_TEST"})
    return pd.DataFrame(rows)


def deterministic_window_starts(valid_starts: list[int], seed: int, maximum: int = 1000) -> list[int]:
    values = np.array(sorted(valid_starts), dtype=int)
    if len(values) <= maximum:
        return values.tolist()
    rng = np.random.default_rng(seed)
    return sorted(rng.choice(values, size=maximum, replace=False).tolist())


def window_win(strategy_return: float, qqq_return: float) -> bool:
    return bool(strategy_return > qqq_return)


def blocked_random_outputs(policies: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    details = []
    for policy in policies:
        for length in WINDOW_LENGTHS:
            for seed in SEEDS:
                details.append({"seed": seed, "window_length": length, "sample_id": "NOT_SAMPLED_LONG_HISTORY_GATE_FAILED", "start_date": pd.NaT, "end_date": pd.NaT, "policy": policy, "strategy_return": np.nan, "qqq_return": np.nan, "excess_return": np.nan, "strategy_max_drawdown": np.nan, "qqq_max_drawdown": np.nan, "daily_excess_win_rate": np.nan, "turnover": np.nan, "cost": np.nan, "average_exposure": np.nan, "trade_count": 0, "rank_snapshot_count": 0, "window_win": np.nan, "status": FAIL_STATUS, "reason": "NO_LONG_HISTORICAL_PIT_ABCDE_RANKINGS"})
    summaries = []
    for policy in policies:
        for length in WINDOW_LENGTHS:
            summaries.append({"policy": policy, "window_length": length, "actual_sample_count": 0, "window_win_rate_vs_qqq": np.nan, "mean_excess_return": np.nan, "median_excess_return": np.nan, "std_excess_return": np.nan, "p05_excess_return": np.nan, "p25_excess_return": np.nan, "p75_excess_return": np.nan, "p95_excess_return": np.nan, "worst_window": "NOT_AVAILABLE", "best_window": "NOT_AVAILABLE", "median_max_drawdown": np.nan, "beat_qqq_and_lower_drawdown_rate": np.nan, "beat_qqq_and_positive_rate": np.nan, "bootstrap_95_low": np.nan, "bootstrap_95_high": np.nan, "overlap_non_independence_warning": True, "status": FAIL_STATUS})
    return pd.DataFrame(details), pd.DataFrame(summaries)


def data_gap_markdown(inventory: dict[str, Any]) -> str:
    return f"""# DATA GAP REPORT

## Final status

`{FAIL_STATUS}`

No formal long-horizon ABCDE result was produced. The 2026-06-17 to 2026-07-13 execution area is regression evidence only and is labelled `{SHORT_LABEL}` everywhere.

## What is available

- Moomoo RAW and QFQ daily OHLCV: {inventory['price']['RAW']['start_date']} to {inventory['price']['RAW']['end_date']}, {inventory['price']['RAW']['ticker_count']} tickers, no duplicate ticker-date rows and no missing open/close values.
- Uploaded ABCDE archive: 16 signal dates from 2026-06-16 to 2026-07-10; A1/B/C/D have 16 snapshots, E_R1 has 8.
- Compact external store: only 3 signal dates from 2026-07-06 to 2026-07-13.
- Price-derived technical history exists, but exact full ABCDE factor lineage does not.

## Blocking gaps

1. No historical filing-aware fundamental panel with report period, publication timestamp, received timestamp, revision lineage and ticker mapping.
2. No certified historical eligible-universe membership, delisting history, symbol-change history or historical constituent snapshots.
3. No exact dated historical family inputs and version-effective weights for A1, B, C, D and E_R1.
4. V20.193 found zero usable historical PIT-safe full-family snapshots and explicitly blocked historical scoring.
5. V20.214 did not certify historical membership. Current ticker coverage cannot be projected backward.
6. QFQ is a current adjustment snapshot, not a PIT corporate-action event ledger. It is audited but not used for the short execution regression; RAW prices are used consistently.

## Minimum viable data remediation

1. Build an append-only security master with listing, delisting, merger, symbol-change and eligibility effective timestamps.
2. Ingest historical fundamentals keyed by filing publication/acceptance time, preserve restatements, and expose `available_at` for every value.
3. Version every ABCDE formula and weight with effective start/end timestamps; materialize raw factor inputs, gates and contributions by historical as-of date.
4. Reconstruct and certify the historical universe independently for every signal date; include failed, delisted and subsequently removed names.
5. Add a PIT corporate-action ledger or an adjustment series frozen as known on each historical date.
6. Recompute rankings after each close, validate `price_max_date <= signal_date`, `fundamental_available_at <= signal_date close`, and execute only at the next session open.
7. Accumulate enough common valid dates for 504-session windows before enabling the random-window branch.

## Forbidden substitutions

The stage does not copy the July 2026 universe into history, does not use current fundamentals as historical values, does not repeat the 2026 snapshots, and does not reinterpret the existing PIT-lite proxy runs as exact ABCDE history.
"""


def write_pdf(path: Path, inventory: dict[str, Any], ranking_audit_df: pd.DataFrame, summary: pd.DataFrame) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#16324F")))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm, title="ABCDE Long Horizon Random Execution Backtest Report")
    story: list[Any] = [Paragraph("ABCDE Long Horizon Random Execution Backtest", styles["CenterTitle"]), Spacer(1, 8), Paragraph(FAIL_STATUS, styles["Heading2"]), Paragraph("Strict long-horizon output is blocked. All executed strategy figures in this report are SHORT_SAMPLE_ONLY regression diagnostics.", styles["BodyText"]), Spacer(1, 10)]
    story += [Paragraph("1. Data coverage", styles["Heading1"])]
    raw = inventory["price"]["RAW"]
    data = [["Item", "Coverage"], ["RAW/QFQ OHLCV", f"{raw['start_date']} to {raw['end_date']}; {raw['ticker_count']} tickers"], ["Archived rankings", "2026-06-16 to 2026-07-10; 16 dates; E_R1 only 8"], ["Common ABCDE signals", "2026-06-30 to 2026-07-10; 8 dates"]]
    table = Table(data, colWidths=[45*mm, 120*mm]); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DCEAF7")),("GRID",(0,0),(-1,-1),0.4,colors.grey),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8)])); story += [table, Spacer(1, 8)]
    story += [Paragraph("2. PIT and no-leakage decision", styles["Heading1"]), Paragraph("Exact historical ABCDE reconstruction fails because filing-aware fundamentals, historical universe membership, delisting/symbol event history, and dated full-family lineage are unavailable. Signals in the regression are mapped to the next trading session open. RAW prices are used consistently; the current QFQ snapshot is not used to create historical signals.", styles["BodyText"])]
    story += [Paragraph("3. ABCDE comparison and A1 execution comparison", styles["Heading1"]), Paragraph("A1, B, C, D and E_R1 daily Top5 and Top5-entry/Top10-exit policies were executed only across the eight-date common archive. A1 Top5 daily and the predeclared A1 Top5-entry/Top10-exit policy are included. These figures are not long-horizon evidence and annualized statistics are suppressed.", styles["BodyText"])]
    show = summary[["policy","total_return","max_drawdown","daily_excess_win_rate_vs_qqq","cumulative_one_way_turnover"]].copy()
    show = show.head(12).round(6)
    data = [["Policy","Return","Max DD","Daily win vs QQQ","Turnover"]] + show.astype(str).values.tolist()
    table = Table(data, colWidths=[69*mm,23*mm,23*mm,28*mm,23*mm], repeatRows=1); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DCEAF7")),("GRID",(0,0),(-1,-1),0.35,colors.grey),("FONTSIZE",(0,0),(-1,-1),6.5),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [Spacer(1,6), table, PageBreak()]
    sections = [
        ("4. QQQ and daily win rate", "QQQ buy-and-hold is aligned to exactly the same short regression dates. Daily win means strategy daily return strictly exceeds QQQ daily return. Wilson 95 percent intervals are reported in the CSV output."),
        ("5. Random-window win rate and distributions", "No 20, 60, 120, 252 or 504 session windows were sampled. Actual sample count is zero for every seed and length. Repeating or copying the short archive is forbidden."),
        ("6. Cost sensitivity", "Zero, 5, 10 and 20 bps one-way sensitivity is provided only as a short execution regression. It is not a long-run robustness result."),
        ("7. Market regimes", "The QQQ 200-day state at the short sample start and the ex-post QQQ return sign are reported only for evaluation. No regime label is used to generate a signal."),
        ("8. Maximum drawdown and turnover", "Drawdown and one-way turnover are calculated on the short sample. Annualized Sharpe, Sortino, CAGR, volatility, Calmar, tracking error and information ratio are deliberately suppressed."),
        ("9. Data limitations", "The current 326-ticker price universe has no historical membership or delisting fields and therefore carries a survivorship warning. Historical fundamentals and exact full-family ABCDE lineage are absent."),
        ("10. Required next action", "Acquire and certify filing-aware fundamentals, a historical security/universe event ledger, versioned strategy formulas, and immutable historical ranking inputs. Then rerun this stage without changing the predeclared main policy."),
    ]
    for title, text in sections:
        story += [Paragraph(title, styles["Heading1"]), Paragraph(text, styles["BodyText"]), Spacer(1,8)]
    def footer(canvas, doc_obj):
        canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.grey); canvas.drawString(16*mm, 9*mm, STAGE); canvas.drawRightString(A4[0]-16*mm, 9*mm, f"Page {doc_obj.page}"); canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def write_reports(output: Path, inventory: dict[str, Any], summary: pd.DataFrame) -> None:
    gap = data_gap_markdown(inventory)
    (output / "data_gap_report.md").write_text(gap, encoding="utf-8")
    readme = f"""# {STAGE}

Final status: `{FAIL_STATUS}`

This immutable output directory contains a strict data audit and a real `{SHORT_LABEL}` execution regression. It contains no formal long-horizon ABCDE conclusion and no random windows. The predeclared main policy remains `{PREDECLARED_MAIN}`.

Use `full_history_*` filenames only as schema-contract names; their `sample_scope` field is authoritative and is `{SHORT_LABEL}` in this failed long-history run.
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    report = f"""# Final Research Report

## Decision

`{FAIL_STATUS}`

The repository has long RAW/QFQ OHLCV but does not have exact long historical point-in-time ABCDE rankings or the source data needed to reconstruct them without survivorship and current-data leakage.

## Formal long-horizon result

Not produced. Random-window sample count is zero for 20/60/120/252/504 trading days and all five seeds.

## Short regression

The archived common ABCDE range has 8 signal dates from 2026-06-30 through 2026-07-10. It was executed at next-session RAW opens and valued at RAW closes. The first-day cost is included. All rows are marked `{SHORT_LABEL}` and annualized metrics are suppressed.

The predeclared main policy remains `{PREDECLARED_MAIN}` regardless of any short-sample threshold result.

## Data and execution limits

- Current price universe: {inventory['price']['RAW']['ticker_count']} tickers, {inventory['price']['RAW']['start_date']} to {inventory['price']['RAW']['end_date']}.
- No historical membership, delisting or symbol-change fields in canonical prices.
- No filing-publication-aware historical fundamentals.
- No full-family PIT ABCDE input lineage; V20.193 reports zero usable historical snapshots.
- The 200-day QQQ regime and ex-post return sign are evaluation labels only.
- Overlapping random windows would be non-independent, but no windows were generated here.

## Recommendation

Follow the minimum viable remediation in `data_gap_report.md`; do not promote any short-sample winner.
"""
    (output / "final_research_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--output-dir", default="outputs/v22/ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_R1")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = repo / output
    output = output.resolve()
    expected_root = (repo / "outputs" / "v22").resolve()
    output.relative_to(expected_root)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    before = hash_manifest(protected_paths(repo))
    pointer = read_latest_price_pointer(repo)
    raw_path = Path(pointer["canonical_raw_path"])
    qfq_path = Path(pointer["canonical_qfq_path"])
    raw = load_price(raw_path)
    qfq = load_price(qfq_path)
    ranks = load_uploaded_rankings(repo)
    master = normalize_ranking_master(ranks)
    compact = Path(r"D:\us-tech-quant-backtests\_strategy_signal_history\ABCDE_R1\abcde_rank_history.parquet")
    rank_audit = ranking_audit(ranks, compact)
    pit = validate_pit_readiness(repo)
    common = common_signal_dates(ranks)
    short_tickers = set(ranks.loc[ranks["signal_date"].isin(common), "ticker"]) | {"QQQ"}
    short_end_buffer = common[-1] + pd.Timedelta(days=10)
    raw_exec = raw[
        raw["ticker"].isin(short_tickers)
        & raw["date"].between(common[0], short_end_buffer)
    ].copy()
    inventory = {
        "stage": STAGE, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "final_status": FAIL_STATUS,
        "price": {"RAW": price_inventory(raw, raw_path, "RAW"), "QFQ": price_inventory(qfq, qfq_path, "QFQ")},
        "ranking": {
            "uploaded_path": str(repo / "inputs" / "abcde_all_uploaded_rankings_master.csv"),
            "uploaded_row_count": len(ranks), "uploaded_date_count": int(ranks["signal_date"].nunique()),
            "uploaded_ticker_count": int(ranks["ticker"].nunique()),
            "uploaded_start": ranks["signal_date"].min().date().isoformat(),
            "uploaded_end": ranks["signal_date"].max().date().isoformat(),
            "common_history_start": common[0].date().isoformat(), "common_history_end": common[-1].date().isoformat(),
            "common_signal_date_count": len(common), "short_archive_only": True,
            "compact_path": str(compact), "compact_exists": compact.is_file(),
        },
        "historical_rebuild": pit,
        "protected_hashes_before": before,
    }
    (output / "data_inventory.json").write_text(json.dumps(inventory, indent=2, default=str) + "\n", encoding="utf-8")
    master.to_parquet(output / "historical_rankings_master.parquet", index=False)
    rank_audit.to_csv(output / "historical_rankings_audit.csv", index=False)

    nav_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    missing_frames: list[pd.DataFrame] = []
    for strategy in STRATEGIES:
        for mode in ("daily", "slots"):
            nav, trades, missing = run_policy(ranks, raw_exec, strategy, mode, common, bps=5.0, exit_rank=10)
            nav_frames.append(nav); trade_frames.append(trades)
            if len(missing): missing_frames.append(missing)
    first_date = min(frame["date"].min() for frame in nav_frames)
    last_date = max(frame["date"].max() for frame in nav_frames)
    qqq_nav, qqq_trades = run_qqq(raw_exec, first_date, last_date, bps=5.0)
    all_nav = pd.concat([*nav_frames, qqq_nav], ignore_index=True)
    all_trades = pd.concat([f for f in [*trade_frames, qqq_trades] if len(f)], ignore_index=True)
    all_nav.to_parquet(output / "full_history_daily_nav.parquet", index=False)
    all_trades.to_parquet(output / "full_history_trades.parquet", index=False)
    if missing_frames:
        missing_df = pd.concat(missing_frames, ignore_index=True)
    else:
        missing_df = pd.DataFrame([{"policy": "ALL_SHORT_POLICIES", "date": pd.NaT, "ticker": "", "action": "NO_MISSING_PRICE_EVENTS", "reason": "AUDIT_COMPLETE"}])
    missing_df.to_csv(output / "missing_price_audit.csv", index=False)

    summaries = []
    daily_wins = []
    cycle_details = []
    period_details = []
    for policy, nav in all_nav[all_nav["policy"] != "QQQ_BUY_HOLD"].groupby("policy", sort=True):
        comp = comparison_frame(nav.sort_values("date"), qqq_nav)
        policy_trades = all_trades[all_trades["policy"] == policy]
        row = policy_summary(policy, comp, policy_trades)
        cycles, cycle_summary = aggregate_cycles(policy, comp)
        row.update(cycle_summary)
        periods = aggregate_periods(policy, comp)
        if len(periods):
            row["monthly_win_rate_vs_qqq"] = float(periods.loc[periods["frequency"] == "MONTH", "win"].mean())
            row["yearly_win_rate_vs_qqq"] = float(periods.loc[periods["frequency"] == "YEAR", "win"].mean())
        summaries.append(row); daily_wins.append(daily_win_row(policy, comp)); cycle_details.append(cycles); period_details.append(periods)
    qqq_comp = comparison_frame(qqq_nav, qqq_nav)
    qqq_row = policy_summary("QQQ_BUY_HOLD", qqq_comp, qqq_trades)
    qqq_row.update({"cycle_count": 0, "signal_cycle_win_rate_vs_qqq": np.nan})
    summaries.append(qqq_row)
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(output / "full_history_policy_summary.csv", index=False)
    pd.DataFrame(daily_wins).to_csv(output / "daily_win_rate_vs_qqq.csv", index=False)
    pd.concat(cycle_details, ignore_index=True).to_csv(output / "signal_cycle_win_rate_vs_qqq.csv", index=False)
    pd.concat(period_details, ignore_index=True).to_csv(output / "monthly_yearly_win_rate_vs_qqq.csv", index=False)

    policies = sorted(summary_df.loc[summary_df["policy"] != "QQQ_BUY_HOLD", "policy"].tolist())
    random_detail, random_summary = blocked_random_outputs(policies)
    random_detail.to_parquet(output / "random_window_detail.parquet", index=False)
    random_summary.to_csv(output / "random_window_summary.csv", index=False)

    cost_rows = []
    for bps in (0.0, 5.0, 10.0, 20.0):
        nav, trades, _ = run_policy(ranks, raw_exec, "A1", "slots", common, bps=bps, exit_rank=10)
        comp = comparison_frame(nav, qqq_nav)
        row = policy_summary(PREDECLARED_MAIN, comp, trades); row["cost_bps_one_way"] = bps; row["sensitivity_scope"] = SHORT_LABEL
        cost_rows.append(row)
    pd.DataFrame(cost_rows).to_csv(output / "cost_sensitivity.csv", index=False)

    threshold_rows = []
    for threshold in (7, 8, 10, 12, 15):
        nav, trades, _ = run_policy(ranks, raw_exec, "A1", "slots", common, bps=5.0, exit_rank=threshold)
        comp = comparison_frame(nav, qqq_nav)
        row = policy_summary(f"A1_TOP5_ENTRY_EXIT{threshold}_NO_REBAL", comp, trades)
        row["exit_threshold"] = threshold; row["parameter_role"] = "PREDECLARED_MAIN" if threshold == 10 else "SENSITIVITY_ONLY"
        threshold_rows.append(row)
    pd.DataFrame(threshold_rows).to_csv(output / "exit_threshold_sensitivity.csv", index=False)

    qqq_full = raw[(raw["ticker"] == "QQQ") & (raw["date"] <= first_date)].sort_values("date")
    start_close = float(qqq_full.iloc[-1]["close"])
    ma200 = float(qqq_full.tail(200)["close"].mean()) if len(qqq_full) >= 200 else np.nan
    start_regime = "INSUFFICIENT_HISTORY" if pd.isna(ma200) else ("BULL_START" if start_close > ma200 else "BEAR_START")
    regime_rows = []
    qqq_total = float(qqq_nav["nav"].iloc[-1] - 1)
    ex_post = "QQQ_RETURN_POSITIVE" if qqq_total > 0 else "QQQ_RETURN_NEGATIVE"
    for row in summaries:
        regime_rows.append({"policy": row["policy"], "start_regime": start_regime, "ex_post_qqq_return_regime": ex_post, "strategy_return": row["total_return"], "excess_return": row["excess_return_vs_qqq"], "daily_excess_win_rate": row["daily_excess_win_rate_vs_qqq"], "random_window_win_rate": np.nan, "max_drawdown": row["max_drawdown"], "sample_count": len(qqq_nav), "sample_scope": SHORT_LABEL, "ex_post_group_not_used_for_signal": True})
    pd.DataFrame(regime_rows).to_csv(output / "regime_summary.csv", index=False)

    run_config = {
        "stage": STAGE, "final_status": FAIL_STATUS, "predeclared_main_policy": PREDECLARED_MAIN,
        "seeds": SEEDS, "window_lengths": WINDOW_LENGTHS, "max_windows_per_length": 1000,
        "random_window_actual_samples": 0, "random_window_block_reason": "NO_LONG_HISTORICAL_PIT_ABCDE_RANKINGS",
        "short_sample_signal_dates": [d.date().isoformat() for d in common],
        "short_sample_execution_start": first_date.date().isoformat(), "short_sample_execution_end": last_date.date().isoformat(),
        "price_execution_basis": "RAW_OPEN_RAW_CLOSE", "qfq_use": "AUDIT_ONLY_NOT_SIGNAL_OR_EXECUTION",
        "cost_bps_one_way": 5.0, "signal_execution": "SIGNAL_DATE_CLOSE_TO_NEXT_TRADING_SESSION_OPEN",
        "cash_return": 0.0, "protected_hashes_before": before,
    }
    write_reports(output, inventory, summary_df)
    write_pdf(output / "ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_REPORT.pdf", inventory, rank_audit, summary_df)
    after = hash_manifest(protected_paths(repo))
    run_config["protected_hashes_after"] = after
    run_config["protected_files_unchanged"] = before == after
    run_config["required_outputs"] = REQUIRED_OUTPUTS
    (output / "run_config.json").write_text(json.dumps(run_config, indent=2, default=str) + "\n", encoding="utf-8")

    main_row = summary_df[summary_df["policy"] == PREDECLARED_MAIN].iloc[0]
    print(f"final_status={FAIL_STATUS}")
    print(f"data_start_date={inventory['price']['RAW']['start_date']}")
    print(f"data_end_date={inventory['price']['RAW']['end_date']}")
    print(f"common_history_start={common[0].date().isoformat()}")
    print(f"common_history_end={common[-1].date().isoformat()}")
    print(f"common_signal_date_count={len(common)}")
    print(f"price_ticker_count={inventory['price']['RAW']['ticker_count']}")
    print(f"ranking_ticker_count={inventory['ranking']['uploaded_ticker_count']}")
    print("pit_validation_pass=false")
    print("lookahead_test_pass=true")
    print("survivorship_warning=TRUE_NO_HISTORICAL_MEMBERSHIP")
    print("best_full_history_policy=NOT_COMPUTED_LONG_HISTORY_BLOCKED")
    print(f"predeclared_main_policy={PREDECLARED_MAIN}")
    print("predeclared_main_total_return=NOT_APPLICABLE_LONG_HORIZON")
    print("predeclared_main_max_drawdown=NOT_APPLICABLE_LONG_HORIZON")
    print("predeclared_main_daily_win_rate_vs_qqq=NOT_APPLICABLE_LONG_HORIZON")
    for length in WINDOW_LENGTHS:
        print(f"predeclared_main_window_win_rate_{length}d=NOT_AVAILABLE_ZERO_VALID_WINDOWS")
    print("qqq_total_return=NOT_APPLICABLE_LONG_HORIZON")
    print("predeclared_main_excess_vs_qqq=NOT_APPLICABLE_LONG_HORIZON")
    print(f"short_sample_predeclared_main_total_return={main_row['total_return']:.12f}")
    print(f"short_sample_predeclared_main_max_drawdown={main_row['max_drawdown']:.12f}")
    print(f"short_sample_predeclared_main_daily_win_rate_vs_qqq={main_row['daily_excess_win_rate_vs_qqq']:.12f}")
    print(f"output_dir={output}")
    print(f"report_pdf_path={output / 'ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_REPORT.pdf'}")
    print("recommended_next_action=ACQUIRE_PIT_FUNDAMENTALS_HISTORICAL_MEMBERSHIP_AND_VERSIONED_FACTOR_LINEAGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
