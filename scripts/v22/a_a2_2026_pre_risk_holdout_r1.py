"""Frozen A/A2 prospective holdout replay against QQQ.

This runner is inference/evaluation only.  It consumes the immutable
A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1 artifacts, uses the frozen Q1-2026 PIT
universe and frozen feature/portfolio contracts, and never fits a model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")


REPO = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
BASELINE_ROOT = RESULTS_ROOT / "A_VS_A2_QUARTERLY_13F_R1"
FREEZE_ROOT = BASELINE_ROOT / "audit/freeze_r1"
OUTPUT_ROOT = RESULTS_ROOT / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
RAW_ROOT = Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw")
REHAB_PATH = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
BENCHMARK_POINTER = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    r"\canonical_snapshot_pointer.json"
)
ADAPTER_PATH = BASELINE_ROOT / "scripts/run_rebuild.py"
A2_SOURCE = REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
MODEL_PATH = BASELINE_ROOT / "A2/final_full_pre2026_hgb.joblib"
TRAINING_PATH = BASELINE_ROOT / "A2/training_matrix.parquet"
MEMBERS_PATH = BASELINE_ROOT / "universe/quarterly_universe_members.parquet"
QUARTERS_PATH = BASELINE_ROOT / "universe/quarterly_universe_manifest.parquet"
MANAGERS_PATH = BASELINE_ROOT / "audit/authoritative_24_manager_manifest.csv"
AUTHORITATIVE_CONFIG_PATH = REPO / "config/v22/authoritative_24_manager_master_r1.json"

FROZEN_BASELINE_NAME = "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1"
REQUIRED_FREEZE_STATUS = "PASS_FROZEN_IMMUTABLE_RESEARCH_BASELINE"
REQUESTED_START = pd.Timestamp("2026-06-14")
EFFECTIVE_START = pd.Timestamp("2026-06-15")
TOP_N = 20
COST_BPS = 10
ANNUALIZATION = 252.0
EXPECTED_FILES = (
    "a_a2_vs_qqq_20260615_latest_summary.json",
    "a_a2_vs_qqq_20260615_latest_metrics.csv",
    "a_a2_vs_qqq_20260615_latest_daily.parquet",
    "a_a2_vs_qqq_20260615_latest_subperiod.csv",
    "a_a2_vs_qqq_20260615_latest_drawdowns.csv",
    "a_a2_vs_qqq_20260615_latest_equity_curve.png",
    "a_a2_vs_qqq_20260615_latest_drawdown_curve.png",
    "a_a2_vs_qqq_20260615_latest_audit.json",
)


class ContractFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise ContractFailure(f"{code}|{evidence}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def atomic_json(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    os.replace(temp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp.parquet")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def verify_frozen_baseline() -> tuple[dict[str, Any], pd.DataFrame, list[dict[str, Any]]]:
    manifest_path = FREEZE_ROOT / "frozen_baseline_manifest.json"
    verification_path = FREEZE_ROOT / "freeze_verification.json"
    hash_path = FREEZE_ROOT / "frozen_artifact_hashes.csv"
    for path in (manifest_path, verification_path, hash_path):
        require(path.is_file(), "FROZEN_ARTIFACT_MISSING", path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prior_verification = json.loads(verification_path.read_text(encoding="utf-8"))
    require(manifest.get("frozen_baseline_name") == FROZEN_BASELINE_NAME, "BASELINE_NAME_MISMATCH")
    require(manifest.get("status") == "FROZEN_RESEARCH_BASELINE", "BASELINE_NOT_FROZEN")
    require(prior_verification.get("status") == "PASS", "PRIOR_FREEZE_VERIFICATION_FAILED")
    require(manifest["contracts"]["manager"]["authoritative_manager_count"] == 24, "MANAGER_COUNT_FAILURE")
    require(not manifest["contracts"]["manager"]["situational_awareness_included"], "SA_INCLUDED")
    hashes = pd.read_csv(hash_path)
    checks: list[dict[str, Any]] = []
    for row in hashes.itertuples(index=False):
        path = Path(row.absolute_path)
        actual = sha256_file(path) if path.is_file() else None
        checks.append({
            "artifact_id": row.artifact_id,
            "path": str(path),
            "expected_sha256": row.sha256,
            "actual_sha256": actual,
            "match": actual == row.sha256,
        })
    require(len(checks) == int(manifest["artifact_hash_manifest"]["artifact_count"]), "HASH_COUNT_FAILURE")
    require(all(row["match"] for row in checks), "FROZEN_HASH_FAILURE", [x for x in checks if not x["match"]])
    require(AUTHORITATIVE_CONFIG_PATH.is_file(), "AUTHORITATIVE_MANAGER_CONFIG_MISSING")
    manager_config = json.loads(AUTHORITATIVE_CONFIG_PATH.read_text(encoding="utf-8"))
    configured = {str(row["cik"]).zfill(10) for row in manager_config.get("managers", [])}
    frozen_managers = pd.read_csv(MANAGERS_PATH, dtype={"cik": "string"})
    frozen_ciks = {str(value).zfill(10) for value in frozen_managers.cik}
    require(manager_config.get("classification") == "ACTIVE_AUTHORITATIVE", "AUTHORITATIVE_CONFIG_CLASSIFICATION_FAILURE")
    require(manager_config.get("authoritative_for_holdings_ingestion") is True, "AUTHORITATIVE_CONFIG_DISABLED")
    require(manager_config.get("manager_count") == len(configured) == 24, "AUTHORITATIVE_CONFIG_MANAGER_COUNT_FAILURE")
    require(manager_config.get("situational_awareness_included") is False and "0002025719" not in configured, "AUTHORITATIVE_CONFIG_SA_FAILURE")
    require(manager_config.get("per_manager_top_n") == 100, "AUTHORITATIVE_CONFIG_TOP100_FAILURE")
    require(manager_config.get("max_universe_size") == 900, "AUTHORITATIVE_CONFIG_CAP_FAILURE")
    require(configured == frozen_ciks, "AUTHORITATIVE_CONFIG_FROZEN_CIK_MISMATCH")
    require(manager_config.get("source_manifest_sha256") == sha256_file(MANAGERS_PATH), "AUTHORITATIVE_CONFIG_SOURCE_HASH_FAILURE")
    return manifest, hashes, checks


def load_qqq() -> tuple[pd.DataFrame, dict[str, Any]]:
    require(BENCHMARK_POINTER.is_file(), "BENCHMARK_POINTER_MISSING")
    pointer = json.loads(BENCHMARK_POINTER.read_text(encoding="utf-8"))
    require(pointer.get("source_policy") == "MOOMOO_ONLY", "BENCHMARK_SOURCE_POLICY_FAILURE")
    require(pointer.get("source") == "MOOMOO_OPEND", "BENCHMARK_VENDOR_FAILURE")
    require(not pointer.get("external_fallback_used"), "BENCHMARK_EXTERNAL_FALLBACK_USED")
    require(not pointer.get("yahoo_used") and not pointer.get("yfinance_used"), "BENCHMARK_VENDOR_CONTAMINATION")
    path = Path(pointer["canonical_qfq_path"])
    require(path.is_file(), "BENCHMARK_FILE_MISSING", path)
    frame = pd.read_csv(path, usecols=["ticker", "date", "open", "close", "adjustment", "source", "source_policy"])
    frame = frame.loc[frame.ticker.astype(str).str.upper().eq("QQQ")].copy()
    frame["trade_date"] = pd.to_datetime(frame.pop("date")).dt.normalize()
    frame["ticker"] = "QQQ"
    frame = frame.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last")
    require(not frame.empty, "QQQ_MISSING")
    require(frame.adjustment.astype(str).str.lower().eq("qfq").all(), "QQQ_NOT_QFQ")
    require(frame.source_policy.eq("MOOMOO_ONLY").all(), "QQQ_SOURCE_POLICY_MIXED")
    require(np.isfinite(frame[["open", "close"]].to_numpy(float)).all(), "QQQ_NONFINITE")
    pointer["canonical_qfq_sha256"] = sha256_file(path)
    return frame.reset_index(drop=True), pointer


def build_adjusted_equity_prices(adapter, end_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    members = pd.read_parquet(MEMBERS_PATH)
    q1 = members.loc[members.quarter.eq("2026Q1")].copy()
    require(len(q1) == 613 and q1.ticker.nunique() == 613, "Q1_UNIVERSE_IDENTITY_FAILURE")
    require(q1.effective_date.eq(pd.Timestamp("2026-05-22")).all(), "Q1_EFFECTIVE_DATE_FAILURE")
    require(not q1.ticker.eq("WOLF").any(), "UNEXPECTED_WOLF_CURRENT_MEMBER")
    index, read_failures = adapter.raw_file_index()
    require(not read_failures, "RAW_FILE_READ_FAILURE", read_failures)
    require(REHAB_PATH.is_file(), "REHAB_FACTORS_MISSING")
    rehab = pd.read_parquet(REHAB_PATH)
    if len(rehab):
        rehab["code"] = rehab.code.astype(str).str.upper().str.strip()
    adapter.END_EXCLUSIVE = end_date + pd.Timedelta(days=1)
    frames: list[pd.DataFrame] = []
    events: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    latest_by_ticker: dict[str, str] = {}
    dummy_wolf: dict[str, Any] = {"event_date": "2023-12-01", "quantity_multiplier": 1.0}
    for row in q1.sort_values("ticker", kind="mergesort").itertuples(index=False):
        code = str(row.moomoo_transport_code).upper().strip()
        paths = index.get(code, [])
        if not paths:
            unavailable.append({"ticker": row.ticker, "code": code, "reason": "NO_MOOMOO_RAW_HISTORY"})
            continue
        raw = adapter.load_raw_code(code, paths)
        raw = raw.loc[raw.trade_date.le(end_date)].copy()
        if raw.empty:
            unavailable.append({"ticker": row.ticker, "code": code, "reason": "NO_PRICE_ON_OR_BEFORE_END"})
            continue
        adjusted, audit_rows = adapter.adjusted_price_frame(code, row.ticker, raw, rehab, dummy_wolf)
        adjusted = adjusted.loc[adjusted.trade_date.le(end_date)].copy()
        if adjusted.empty:
            unavailable.append({"ticker": row.ticker, "code": code, "reason": "NO_ADJUSTED_PRICE"})
            continue
        latest_by_ticker[str(row.ticker)] = str(pd.Timestamp(adjusted.trade_date.max()).date())
        frames.append(adjusted)
        events.extend(audit_rows)
    require(frames, "NO_EQUITY_PRICE_FRAMES")
    prices = pd.concat(frames, ignore_index=True).sort_values(["ticker", "trade_date"], kind="mergesort")
    require(not prices.duplicated(["ticker", "trade_date"]).any(), "DUPLICATE_EQUITY_PRICE")
    event_frame = pd.DataFrame(events)
    return prices, event_frame, {
        "q1_candidate_count": len(q1),
        "price_history_ticker_count": prices.ticker.nunique(),
        "unavailable_candidate_count": len(unavailable),
        "unavailable_candidates": unavailable,
        "latest_price_by_ticker": latest_by_ticker,
    }


def build_signals(r1, model: Any, prices: pd.DataFrame, qqq: pd.DataFrame, end_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = pd.DatetimeIndex(qqq.trade_date)
    feature_input = prices[["ticker", "trade_date", "close", "volume"]].copy()
    features = r1.build_stock_state_features(feature_input)
    features["signal_date"] = features.trade_date
    position = pd.Series(np.arange(len(calendar)), index=calendar)
    features["calendar_position"] = features.signal_date.map(position)
    features["position_120_prior"] = features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"] = features.groupby("ticker").cumcount() + 1
    features["lookback_121_eligible"] = (
        features.required_observations.ge(121)
        & features.calendar_position.notna()
        & features.position_120_prior.notna()
        & features.calendar_position.sub(features.position_120_prior).eq(120)
    )
    feature_cols = list(r1.FEATURE_COLUMNS)
    features["all_features_available"] = np.isfinite(features[feature_cols].to_numpy(float)).all(axis=1)
    matrix = features.loc[
        features.signal_date.between(EFFECTIVE_START, end_date)
        & features.lookback_121_eligible
        & features.all_features_available,
    ].copy()
    matrix["universe_size"] = matrix.groupby("signal_date").ticker.transform("size").astype(int)
    require(matrix.groupby("signal_date").size().ge(TOP_N).all(), "DAILY_UNIVERSE_BELOW_TOP20")
    expected_dates = calendar[(calendar >= EFFECTIVE_START) & (calendar <= end_date)]
    require(pd.DatetimeIndex(sorted(matrix.signal_date.unique())).equals(expected_dates), "STRATEGY_OBSERVATION_GAP")
    scored = r1.materialize_a1_control(matrix.sort_values(["signal_date", "ticker"], kind="mergesort"))
    scored["a2_prediction"] = model.predict(scored.loc[:, feature_cols].to_numpy(float))
    scored["a2_rank"] = r1._prediction_rank(scored, "a2_prediction")
    signals = scored[[
        "signal_date", "ticker", "universe_size", "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"
    ]].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    for rank_col in ("a1_rank", "a2_rank"):
        counts = signals.loc[signals[rank_col].le(TOP_N)].groupby("signal_date").size()
        require(counts.eq(TOP_N).all() and len(counts) == len(expected_dates), "TOP20_CARDINALITY_FAILURE", rank_col)
    eligibility = matrix.groupby("signal_date", as_index=False).agg(
        final_U_t_count=("ticker", "size"),
        active_13f_quarter=("ticker", lambda _: "2026Q1"),
    )
    return signals, eligibility


def build_target_map(signals: pd.DataFrame, rank_column: str) -> dict[pd.Timestamp, dict[str, float]]:
    selected = signals.loc[signals[rank_column].le(TOP_N), ["signal_date", "ticker"]]
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for date, day in selected.groupby("signal_date", sort=True):
        require(len(day) == TOP_N and day.ticker.nunique() == TOP_N, "TOP20_TARGET_FAILURE", date)
        result[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
    return result


@dataclass
class PathResult:
    daily: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    missing_price_events: list[dict[str, Any]]


def reconstruct_open_ended(
    model_name: str,
    target_map: dict[pd.Timestamp, dict[str, float]],
    prices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    end_date: pd.Timestamp,
) -> PathResult:
    """Frozen daily open execution/accounting, without forced terminal liquidation."""
    open_wide = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    close_wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()

    def opening(date: pd.Timestamp, ticker: str) -> float:
        try:
            value = float(open_wide.at[date, ticker])
        except (KeyError, TypeError, ValueError):
            return np.nan
        return value if math.isfinite(value) and value > 0 else np.nan

    def mark(date: pd.Timestamp, ticker: str) -> tuple[float, bool, pd.Timestamp]:
        value = opening(date, ticker)
        if math.isfinite(value):
            return value, False, date
        history = close_wide.loc[close_wide.index < date, ticker].dropna() if ticker in close_wide else pd.Series(dtype=float)
        history = history[(history > 0) & np.isfinite(history)]
        require(not history.empty, "UNVALUABLE_POSITION", f"{ticker}:{date.date()}")
        return float(history.iloc[-1]), True, pd.Timestamp(history.index[-1])

    shares: dict[str, float] = {}
    prior_marks: dict[str, float] = {}
    cash = 1.0
    prior_nav = 1.0
    daily_rows = [{
        "date": EFFECTIVE_START, "model": model_name, "nav": 1.0, "daily_return": 0.0,
        "turnover": 0.0, "transaction_cost": 0.0, "exposure": 0.0, "holding_count": 0,
        "stale_mark_count": 0, "skipped_buy_count": 0, "blocked_sell_count": 0,
    }]
    position_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    missing_events: list[dict[str, Any]] = []
    cost_rate = COST_BPS / 10000.0
    sim_dates = calendar[(calendar > EFFECTIVE_START) & (calendar <= end_date)]
    for sequence, execution_date0 in enumerate(sim_dates, start=1):
        execution_date = pd.Timestamp(execution_date0)
        signal_date = pd.Timestamp(calendar[calendar.get_loc(execution_date) - 1])
        target = target_map.get(signal_date)
        require(target is not None, "MISSING_STRATEGY_OBSERVATION", signal_date)
        cash_before = cash
        shares_before = dict(shares)
        marks: dict[str, float] = {}
        mark_dates: dict[str, pd.Timestamp] = {}
        stale: dict[str, bool] = {}
        pre_values: dict[str, float] = {}
        market_pnl: dict[str, float] = {}
        for ticker, quantity in shares_before.items():
            value, is_stale, source_date = mark(execution_date, ticker)
            marks[ticker] = value
            mark_dates[ticker] = source_date
            stale[ticker] = is_stale
            pre_values[ticker] = quantity * value
            market_pnl[ticker] = quantity * (value - prior_marks[ticker])
            if is_stale:
                missing_events.append({"date": str(execution_date.date()), "model": model_name, "ticker": ticker, "kind": "STALE_MARK", "source_date": str(source_date.date())})
        pretrade_nav = cash_before + sum(pre_values.values())
        desired = {ticker: weight * pretrade_nav for ticker, weight in target.items()}
        sells: dict[str, float] = {}
        buys: dict[str, float] = {}
        transaction_cost = 0.0
        skipped_buys = 0
        blocked_sells = 0
        for ticker in sorted(set(shares) | set(target)):
            current = pre_values.get(ticker, 0.0)
            wanted = desired.get(ticker, 0.0)
            if current <= wanted + 1e-14:
                continue
            price = opening(execution_date, ticker)
            if not math.isfinite(price):
                blocked_sells += 1
                missing_events.append({"date": str(execution_date.date()), "model": model_name, "ticker": ticker, "kind": "BLOCKED_SELL"})
                continue
            notional = current - wanted
            quantity = notional / price
            shares[ticker] = max(0.0, shares[ticker] - quantity)
            if shares[ticker] <= 1e-14:
                shares.pop(ticker, None)
            cash += notional
            sells[ticker] = notional
            transaction_cost += 0.5 * notional * cost_rate
            trade_rows.append({"date": execution_date, "model": model_name, "ticker": ticker, "side": "SELL", "shares": quantity, "execution_price": price, "notional": notional, "allocated_transaction_cost": 0.5 * notional * cost_rate})
        post_sell_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        requested: dict[str, float] = {}
        for ticker in sorted(target):
            current = post_sell_values.get(ticker, 0.0)
            wanted = desired[ticker]
            if wanted <= current + 1e-14:
                continue
            price = opening(execution_date, ticker)
            if not math.isfinite(price):
                skipped_buys += 1
                missing_events.append({"date": str(execution_date.date()), "model": model_name, "ticker": ticker, "kind": "SKIPPED_BUY"})
                continue
            requested[ticker] = wanted - current
            marks[ticker] = price
            mark_dates[ticker] = execution_date
            stale[ticker] = False
        buy_total = sum(requested.values())
        cash_available = max(0.0, cash - transaction_cost)
        requirement = buy_total * (1.0 + 0.5 * cost_rate)
        scale = min(1.0, cash_available / requirement) if requirement > 0 else 1.0
        for ticker, wanted in requested.items():
            notional = wanted * scale
            if notional <= 1e-14:
                continue
            price = marks[ticker]
            quantity = notional / price
            shares[ticker] = shares.get(ticker, 0.0) + quantity
            cash -= notional
            buys[ticker] = notional
            transaction_cost += 0.5 * notional * cost_rate
            trade_rows.append({"date": execution_date, "model": model_name, "ticker": ticker, "side": "BUY", "shares": quantity, "execution_price": price, "notional": notional, "allocated_transaction_cost": 0.5 * notional * cost_rate})
        cash -= transaction_cost
        require(cash >= -1e-12, "NEGATIVE_CASH", f"{model_name}:{execution_date}:{cash}")
        cash = max(0.0, cash)
        post_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        nav = cash + sum(post_values.values())
        traded_notional = sum(sells.values()) + sum(buys.values())
        turnover = 0.5 * traded_notional / pretrade_nav
        require(abs(transaction_cost - 0.5 * traded_notional * cost_rate) <= 1e-12, "COST_IDENTITY_FAILURE")
        for ticker in sorted(set(shares_before) | set(shares) | set(sells) | set(buys)):
            position_rows.append({
                "date": execution_date, "model": model_name, "ticker": ticker,
                "shares_before": shares_before.get(ticker, 0.0), "shares_after": shares.get(ticker, 0.0),
                "previous_price": prior_marks.get(ticker, np.nan), "current_price": marks.get(ticker, np.nan),
                "mark_source_date": mark_dates.get(ticker, execution_date), "stale_mark": stale.get(ticker, False),
                "market_pnl": market_pnl.get(ticker, 0.0),
                "transaction_cost": 0.5 * cost_rate * (sells.get(ticker, 0.0) + buys.get(ticker, 0.0)),
            })
        daily_rows.append({
            "date": execution_date, "model": model_name, "nav": nav,
            "daily_return": nav / prior_nav - 1.0, "turnover": turnover,
            "transaction_cost": transaction_cost, "exposure": sum(post_values.values()) / nav,
            "holding_count": len(shares), "stale_mark_count": sum(stale.values()),
            "skipped_buy_count": skipped_buys, "blocked_sell_count": blocked_sells,
        })
        prior_nav = nav
        prior_marks = {ticker: marks[ticker] for ticker in shares}
    return PathResult(pd.DataFrame(daily_rows), pd.DataFrame(position_rows), pd.DataFrame(trade_rows), missing_events)


def metric_set(returns: pd.Series, equity: pd.Series, turnover: pd.Series) -> dict[str, float]:
    r = returns.iloc[1:].to_numpy(float)
    n = len(r)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    annual = float((1.0 + total) ** (ANNUALIZATION / n) - 1.0) if n and total > -1 else np.nan
    vol = float(np.std(r, ddof=0) * np.sqrt(ANNUALIZATION)) if n else np.nan
    sharpe = float(np.mean(r) * ANNUALIZATION / vol) if vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1.0
    mdd = float(drawdown.min())
    positives = r[r > 0].sum()
    negatives = r[r < 0].sum()
    return {
        "total_return": total,
        "annualized_return_short_sample": annual,
        "annualized_volatility": vol,
        "sharpe": sharpe,
        "maximum_drawdown": mdd,
        "calmar_short_sample": annual / abs(mdd) if mdd < 0 else np.nan,
        "best_day": float(np.max(r)) if n else np.nan,
        "worst_day": float(np.min(r)) if n else np.nan,
        "positive_day_pct": float(np.mean(r > 0)) if n else np.nan,
        "turnover_total_one_way": float(turnover.iloc[1:].sum()),
        "profit_factor": float(positives / abs(negatives)) if negatives < 0 else np.nan,
        "final_equity": float(equity.iloc[-1]),
    }


def relative_metrics(strategy: pd.Series, benchmark: pd.Series, sm: dict[str, float], bm: dict[str, float]) -> dict[str, float]:
    s = strategy.iloc[1:].to_numpy(float)
    b = benchmark.iloc[1:].to_numpy(float)
    active = s - b
    bvar = float(np.var(b, ddof=0))
    tracking = float(np.std(active, ddof=0) * np.sqrt(ANNUALIZATION))
    up = b > 0
    down = b < 0
    return {
        "total_active_return_vs_qqq": sm["total_return"] - bm["total_return"],
        "annualized_active_return_vs_qqq": sm["annualized_return_short_sample"] - bm["annualized_return_short_sample"],
        "beta_vs_qqq": float(np.cov(s, b, ddof=0)[0, 1] / bvar) if bvar > 0 else np.nan,
        "daily_return_correlation_vs_qqq": float(np.corrcoef(s, b)[0, 1]) if np.std(s) > 0 and np.std(b) > 0 else np.nan,
        "tracking_error_vs_qqq": tracking,
        "information_ratio_vs_qqq": float(np.mean(active) * ANNUALIZATION / tracking) if tracking > 0 else np.nan,
        "upside_capture_vs_qqq": float(np.mean(s[up]) / np.mean(b[up])) if up.any() and np.mean(b[up]) != 0 else np.nan,
        "downside_capture_vs_qqq": float(np.mean(s[down]) / np.mean(b[down])) if down.any() and np.mean(b[down]) != 0 else np.nan,
    }


def drawdown_record(dates: pd.Series, equity: pd.Series, name: str) -> dict[str, Any]:
    values = equity.to_numpy(float)
    peaks = np.maximum.accumulate(values)
    dd = values / peaks - 1.0
    trough_i = int(np.argmin(dd))
    peak_i = int(np.argmax(values[: trough_i + 1]))
    recovery = None
    for i in range(trough_i + 1, len(values)):
        if values[i] >= values[peak_i] - 1e-12:
            recovery = pd.Timestamp(dates.iloc[i])
            break
    return {
        "series": name,
        "max_drawdown": float(dd[trough_i]),
        "drawdown_start": str(pd.Timestamp(dates.iloc[peak_i]).date()),
        "drawdown_trough": str(pd.Timestamp(dates.iloc[trough_i]).date()),
        "recovery_date": str(recovery.date()) if recovery is not None else None,
        "recovered": recovery is not None,
    }


def subperiod_table(daily: pd.DataFrame, end_date: pd.Timestamp) -> pd.DataFrame:
    periods = [
        ("2026-06-15 to 2026-06-30", pd.Timestamp("2026-06-15"), pd.Timestamp("2026-06-30")),
        ("2026-07-01 to 2026-07-31", pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-31")),
        (f"2026-08-01 to {end_date.date()}", pd.Timestamp("2026-08-01"), end_date),
    ]
    rows = []
    for label, start, end in periods:
        part = daily.loc[daily.date.between(start, end)]
        returns = {name: float(np.prod(1.0 + part[f"{name}_daily_return"]) - 1.0) for name in ("A", "A2", "QQQ")}
        rows.append({
            "period": label, "period_start": str(start.date()), "period_end": str(end.date()),
            "A_return": returns["A"], "A2_return": returns["A2"], "QQQ_return": returns["QQQ"],
            "A2_minus_A": returns["A2"] - returns["A"],
            "A_minus_QQQ": returns["A"] - returns["QQQ"],
            "A2_minus_QQQ": returns["A2"] - returns["QQQ"],
        })
    return pd.DataFrame(rows)


def worst_days(daily: pd.DataFrame, signals: pd.DataFrame, column: str, model: str) -> list[dict[str, Any]]:
    rank_col = "a1_rank" if model == "A" else "a2_rank"
    rows = []
    for row in daily.iloc[1:].nsmallest(5, column).itertuples(index=False):
        date = pd.Timestamp(row.date)
        signal_dates = signals.signal_date[signals.signal_date < date]
        signal_date = pd.Timestamp(signal_dates.max()) if len(signal_dates) else None
        selected = signals.loc[(signals.signal_date.eq(signal_date)) & signals[rank_col].le(TOP_N)] if signal_date is not None else signals.iloc[0:0]
        rows.append({
            "date": str(date.date()), "A_return": float(row.A_daily_return), "A2_return": float(row.A2_daily_return),
            "QQQ_return": float(row.QQQ_daily_return), "A_exposure": float(row.A_exposure),
            "A2_exposure": float(row.A2_exposure), "rank_range": "1-20",
            "selected_tickers": selected.sort_values(rank_col).ticker.tolist(),
        })
    return rows


def plot_curves(daily: pd.DataFrame, output: Path) -> None:
    specs = [
        ("a_a2_vs_qqq_20260615_latest_equity_curve.png", ("A_equity", "A2_equity", "QQQ_equity"), "A / A2 vs QQQ — normalized equity", "Equity (2026-06-15 = 100)"),
        ("a_a2_vs_qqq_20260615_latest_drawdown_curve.png", ("A_drawdown", "A2_drawdown", "QQQ_drawdown"), "A / A2 vs QQQ — drawdown", "Drawdown"),
    ]
    colors = {"A": "#1f77b4", "A2": "#ff7f0e", "QQQ": "#2ca02c"}
    for filename, columns, title, ylabel in specs:
        fig, ax = plt.subplots(figsize=(11, 6.2), dpi=160)
        for column in columns:
            label = column.split("_")[0]
            ax.plot(daily.date, daily[column], label=label, color=colors[label], linewidth=2.0)
        ax.set_title(title)
        ax.set_xlabel("Date")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False, ncol=3)
        fig.autofmt_xdate()
        fig.tight_layout()
        temp = output / f".{filename}.{uuid.uuid4().hex}.tmp.png"
        fig.savefig(temp, bbox_inches="tight")
        plt.close(fig)
        os.replace(temp, output / filename)


def classification(metrics: dict[str, dict[str, float]]) -> str:
    a, a2, q = metrics["A"], metrics["A2"], metrics["QQQ"]
    if a["total_return"] < q["total_return"] and a2["total_return"] < q["total_return"]:
        return "D"
    if a2["total_return"] <= a["total_return"]:
        return "C"
    if a2["total_return"] > q["total_return"] and a2["sharpe"] > a["sharpe"] and a2["sharpe"] > q["sharpe"]:
        return "A"
    return "B"


def run(output: Path) -> dict[str, Any]:
    require(str(output.resolve()).startswith(str(RESULTS_ROOT.resolve()) + os.sep), "OUTPUT_NOT_EXTERNAL_RESULTS", output)
    if output.exists():
        require(not any((output / name).exists() for name in EXPECTED_FILES), "AUTHORITATIVE_OUTPUT_ALREADY_EXISTS", output)
    output.mkdir(parents=True, exist_ok=True)
    manifest, hash_manifest, hash_checks = verify_frozen_baseline()
    qqq, benchmark_pointer = load_qqq()
    latest_benchmark = pd.Timestamp(qqq.trade_date.max())
    adapter = import_path("a_a2_frozen_adapter_holdout", ADAPTER_PATH)
    r1 = import_path("a_a2_frozen_r1_holdout", A2_SOURCE)
    equity_prices, ca_events, price_audit = build_adjusted_equity_prices(adapter, latest_benchmark + pd.Timedelta(days=1))
    latest_price = pd.Timestamp(equity_prices.trade_date.max())
    effective_end = min(latest_price, latest_benchmark)
    require(EFFECTIVE_START <= effective_end, "EMPTY_EFFECTIVE_WINDOW")
    model = joblib.load(MODEL_PATH)
    signals, eligibility = build_signals(r1, model, equity_prices, qqq, effective_end)
    latest_a = pd.Timestamp(signals.signal_date.max())
    latest_a2 = latest_a
    effective_end = min(latest_a, latest_a2, latest_price, latest_benchmark)
    require(effective_end == pd.Timestamp("2026-08-13"), "UNEXPECTED_COMMON_END", effective_end)
    calendar = pd.DatetimeIndex(qqq.trade_date)
    all_prices = pd.concat([
        equity_prices.loc[equity_prices.trade_date.le(effective_end)],
        qqq.loc[qqq.trade_date.le(effective_end), ["ticker", "trade_date", "open", "close"]].assign(volume=np.nan, autype="qfq", source="MOOMOO_ONLY_PROMOTED"),
    ], ignore_index=True, sort=False)
    a_path = reconstruct_open_ended("A", build_target_map(signals, "a1_rank"), all_prices, calendar, effective_end)
    a2_path = reconstruct_open_ended("A2", build_target_map(signals, "a2_rank"), all_prices, calendar, effective_end)
    qwin = qqq.loc[qqq.trade_date.between(EFFECTIVE_START, effective_end), ["trade_date", "open"]].copy()
    qwin["QQQ_equity"] = 100.0 * qwin.open / float(qwin.open.iloc[0])
    qwin["QQQ_daily_return"] = qwin.QQQ_equity.pct_change().fillna(0.0)
    daily = a_path.daily.rename(columns={
        "nav": "A_nav", "daily_return": "A_daily_return", "turnover": "A_turnover", "exposure": "A_exposure"
    })[["date", "A_nav", "A_daily_return", "A_turnover", "A_exposure"]]
    daily = daily.merge(a2_path.daily.rename(columns={
        "nav": "A2_nav", "daily_return": "A2_daily_return", "turnover": "A2_turnover", "exposure": "A2_exposure"
    })[["date", "A2_nav", "A2_daily_return", "A2_turnover", "A2_exposure"]], on="date", validate="one_to_one")
    daily = daily.merge(qwin.rename(columns={"trade_date": "date"})[["date", "QQQ_equity", "QQQ_daily_return"]], on="date", validate="one_to_one")
    daily["A_equity"] = 100.0 * daily.A_nav / float(daily.A_nav.iloc[0])
    daily["A2_equity"] = 100.0 * daily.A2_nav / float(daily.A2_nav.iloc[0])
    for name in ("A", "A2", "QQQ"):
        daily[f"{name}_drawdown"] = daily[f"{name}_equity"] / daily[f"{name}_equity"].cummax() - 1.0
    require((daily.loc[0, ["A_equity", "A2_equity", "QQQ_equity"]] == 100.0).all(), "START_EQUITY_FAILURE")
    required_daily = [
        "date", "A_equity", "A2_equity", "QQQ_equity", "A_daily_return", "A2_daily_return", "QQQ_daily_return",
        "A_drawdown", "A2_drawdown", "QQQ_drawdown",
    ]
    metrics = {
        "A": metric_set(daily.A_daily_return, daily.A_equity, daily.A_turnover),
        "A2": metric_set(daily.A2_daily_return, daily.A2_equity, daily.A2_turnover),
        "QQQ": metric_set(daily.QQQ_daily_return, daily.QQQ_equity, pd.Series(np.zeros(len(daily)))),
    }
    relative = {
        "A_vs_QQQ": relative_metrics(daily.A_daily_return, daily.QQQ_daily_return, metrics["A"], metrics["QQQ"]),
        "A2_vs_QQQ": relative_metrics(daily.A2_daily_return, daily.QQQ_daily_return, metrics["A2"], metrics["QQQ"]),
    }
    incremental_names = [
        "total_return", "annualized_return_short_sample", "annualized_volatility", "sharpe",
        "maximum_drawdown", "calmar_short_sample", "turnover_total_one_way", "profit_factor",
    ]
    incremental = {name: metrics["A2"][name] - metrics["A"][name] for name in incremental_names}
    subperiod = subperiod_table(daily, effective_end)
    drawdowns = pd.DataFrame([drawdown_record(daily.date, daily[f"{name}_equity"], name) for name in ("A", "A2", "QQQ")])
    worst_a = worst_days(daily, signals, "A_daily_return", "A")
    worst_a2 = worst_days(daily, signals, "A2_daily_return", "A2")
    missing_events = a_path.missing_price_events + a2_path.missing_price_events
    positions = pd.concat([a_path.positions, a2_path.positions], ignore_index=True)
    flagged = ca_events.loc[ca_events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")].copy() if len(ca_events) else pd.DataFrame()
    if len(flagged):
        flagged["event_date"] = pd.to_datetime(flagged.event_date).dt.normalize()
        held_keys = set(zip(positions.ticker.astype(str), pd.to_datetime(positions.date).dt.normalize()))
        ca_exceptions = [row for row in flagged.to_dict("records") if (str(row["ticker"]), pd.Timestamp(row["event_date"])) in held_keys and EFFECTIVE_START <= pd.Timestamp(row["event_date"]) <= effective_end]
    else:
        ca_exceptions = []
    training = pd.read_parquet(TRAINING_PATH, columns=["signal_date"])
    training_after = int(pd.to_datetime(training.signal_date).gt(pd.Timestamp("2025-12-31")).sum())
    qmanifest = pd.read_parquet(QUARTERS_PATH)
    active_q = qmanifest.loc[qmanifest.quarter.eq("2026Q1")].iloc[0]
    lookahead = int((signals.signal_date < pd.Timestamp(active_q.effective_date)).sum())
    pit_violations = int(not (
        pd.Timestamp(active_q.latest_actual_filing_timestamp) == pd.Timestamp("2026-05-15")
        and pd.Timestamp(active_q.effective_date) == pd.Timestamp("2026-05-22")
        and EFFECTIVE_START >= pd.Timestamp(active_q.effective_date)
    ))
    final_classification = classification(metrics)
    audit = {
        "FROZEN_BASELINE_NAME": FROZEN_BASELINE_NAME,
        "A_A2_CLEAN_BASELINE_FREEZE_STATUS": REQUIRED_FREEZE_STATUS,
        "fresh_frozen_hash_verification": {"required_count": len(hash_checks), "match_count": sum(x["match"] for x in hash_checks), "mismatch_count": sum(not x["match"] for x in hash_checks), "checks": hash_checks},
        "TRAINING_DATA_AFTER_2025_12_31_COUNT": training_after,
        "MODEL_FIT_DURING_THIS_RUN_COUNT": 0,
        "MODEL_PREDICT_DURING_THIS_RUN_COUNT": 1,
        "PARAMETER_SEARCH_COUNT": 0,
        "RISK_OVERLAY_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "PIT_VIOLATION_COUNT": pit_violations,
        "MISSING_PRICE_EVENT_COUNT": len(missing_events),
        "CORPORATE_ACTION_EXCEPTION_COUNT": len(ca_exceptions),
        "missing_price_events": missing_events,
        "corporate_action_exceptions": ca_exceptions,
        "candidate_price_eligibility": price_audit,
        "ordinary_corporate_action_events_in_window": int(pd.to_datetime(ca_events.event_date).between(EFFECTIVE_START, effective_end).sum()) if len(ca_events) else 0,
        "flagged_large_raw_move_rows_in_window": int(pd.to_datetime(flagged.event_date).between(EFFECTIVE_START, effective_end).sum()) if len(flagged) else 0,
        "pit_candidate_pool": {
            "active_quarter": "2026Q1", "holdings_as_of_date": str(pd.Timestamp(active_q.holdings_as_of_date).date()),
            "latest_filing_date": str(pd.Timestamp(active_q.latest_actual_filing_timestamp).date()),
            "effective_date": str(pd.Timestamp(active_q.effective_date).date()), "manager_count": 24,
            "situational_awareness_included": False, "post_cap_universe_count": int(active_q.post_cap_universe_count),
            "universe_fingerprint": active_q.universe_fingerprint,
        },
        "benchmark_source": benchmark_pointer,
        "latest_dates": {"LATEST_A_DATE": str(latest_a.date()), "LATEST_A2_DATE": str(latest_a2.date()), "LATEST_PRICE_DATE": str(latest_price.date()), "LATEST_BENCHMARK_DATE": str(latest_benchmark.date())},
        "eligibility_by_date": eligibility.to_dict("records"),
        "exceptions": {
            "material": missing_events + ca_exceptions,
            "non_material_candidate_exclusions": price_audit["unavailable_candidates"],
        },
        "operations": {"model_fit_count": 0, "parameter_search_count": 0, "risk_overlay_count": 0, "broker_action_count": 0, "source_modification_count": 1, "deletion_count": 0},
    }
    require(training_after == 0 and lookahead == 0 and pit_violations == 0, "PIT_OR_TRAINING_AUDIT_FAILURE")
    require(len(missing_events) == 0 and len(ca_exceptions) == 0, "MATERIAL_EXECUTION_EXCEPTION", {"missing": missing_events, "corporate_actions": ca_exceptions})
    metric_rows = []
    for name in metrics["A"]:
        metric_rows.append({"section": "primary", "metric": name, "A": metrics["A"][name], "A2": metrics["A2"][name], "QQQ": metrics["QQQ"][name], "A2_minus_A": metrics["A2"][name] - metrics["A"][name], "A_vs_QQQ": metrics["A"][name] - metrics["QQQ"][name], "A2_vs_QQQ": metrics["A2"][name] - metrics["QQQ"][name]})
    for name in relative["A_vs_QQQ"]:
        metric_rows.append({"section": "relative", "metric": name, "A": np.nan, "A2": np.nan, "QQQ": np.nan, "A2_minus_A": np.nan, "A_vs_QQQ": relative["A_vs_QQQ"][name], "A2_vs_QQQ": relative["A2_vs_QQQ"][name]})
    summary = {
        "A_A2_2026_PRE_RISK_STATUS": "PASS_VALID_PROSPECTIVE_HOLDOUT",
        "FROZEN_BASELINE_NAME": FROZEN_BASELINE_NAME,
        "A_A2_CLEAN_BASELINE_FREEZE_STATUS": REQUIRED_FREEZE_STATUS,
        "REQUESTED_START_DATE": str(REQUESTED_START.date()), "EFFECTIVE_START_DATE": str(EFFECTIVE_START.date()), "EFFECTIVE_END_DATE": str(effective_end.date()),
        "LATEST_A_DATE": str(latest_a.date()), "LATEST_A2_DATE": str(latest_a2.date()), "LATEST_PRICE_DATE": str(latest_price.date()), "LATEST_BENCHMARK_DATE": str(latest_benchmark.date()),
        "PRIMARY_BENCHMARK": "QQQ", "SECONDARY_BENCHMARK": None, "START_EQUITY": 100.0,
        "metrics": metrics, "A2_incremental_value": incremental,
        "A2_OUTPERFORMANCE_VS_A": metrics["A2"]["total_return"] - metrics["A"]["total_return"],
        "relative_performance": relative, "subperiods": subperiod.to_dict("records"),
        "drawdowns": drawdowns.to_dict("records"), "TOP_5_WORST_A_DAYS": worst_a, "TOP_5_WORST_A2_DAYS": worst_a2,
        "audit_counts": {key: audit[key] for key in (
            "TRAINING_DATA_AFTER_2025_12_31_COUNT", "MODEL_FIT_DURING_THIS_RUN_COUNT", "PARAMETER_SEARCH_COUNT",
            "RISK_OVERLAY_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "PIT_VIOLATION_COUNT", "MISSING_PRICE_EVENT_COUNT",
            "CORPORATE_ACTION_EXCEPTION_COUNT",
        )},
        "methodology": {
            "strategy_return_basis": "frozen close signal to next-session open execution; open-to-open marked NAV; 10bps round-trip cost split equally across buys/sells",
            "benchmark_return_basis": "QQQ QFQ open-to-open on identical dates; no benchmark transaction cost",
            "annualized_return": "geometric annualization from the short holdout sample; 252 sessions",
            "sharpe": "zero-risk-free arithmetic mean daily return * 252 / annualized population volatility",
            "turnover": "total one-way turnover; 0.5 * traded notional / pretrade NAV, summed",
            "capture": "arithmetic mean strategy return / arithmetic mean QQQ return on QQQ up/down days",
            "classification_order": "E integrity failure; D both below QQQ; C A2 not above A; A A2 above A and QQQ with Sharpe above both; otherwise B",
        },
        "FINAL_CLASSIFICATION": final_classification,
    }
    atomic_json(output / EXPECTED_FILES[0], summary)
    atomic_csv(output / EXPECTED_FILES[1], pd.DataFrame(metric_rows))
    atomic_parquet(output / EXPECTED_FILES[2], daily[required_daily])
    atomic_csv(output / EXPECTED_FILES[3], subperiod)
    atomic_csv(output / EXPECTED_FILES[4], drawdowns)
    plot_curves(daily, output)
    atomic_json(output / EXPECTED_FILES[7], audit)
    require(all((output / name).is_file() for name in EXPECTED_FILES), "OUTPUT_ARTIFACT_MISSING")
    summary["artifact_sha256"] = {
        name: sha256_file(output / name) for name in EXPECTED_FILES if name != EXPECTED_FILES[0]
    }
    atomic_json(output / EXPECTED_FILES[0], summary)
    return summary


def display(value: float) -> str:
    return f"{value:.10f}"


def print_final(summary: dict[str, Any]) -> None:
    m = summary["metrics"]
    r = summary["relative_performance"]["A2_vs_QQQ"]
    a = summary["audit_counts"]
    lines = [
        f"A_A2_2026_PRE_RISK_STATUS={summary['A_A2_2026_PRE_RISK_STATUS']}",
        f"EFFECTIVE_START_DATE={summary['EFFECTIVE_START_DATE']}", f"EFFECTIVE_END_DATE={summary['EFFECTIVE_END_DATE']}", "",
        f"A_TOTAL_RETURN={display(m['A']['total_return'])}", f"A2_TOTAL_RETURN={display(m['A2']['total_return'])}", f"QQQ_TOTAL_RETURN={display(m['QQQ']['total_return'])}", "",
        f"A2_MINUS_A_TOTAL_RETURN={display(m['A2']['total_return'] - m['A']['total_return'])}", f"A_MINUS_QQQ_TOTAL_RETURN={display(m['A']['total_return'] - m['QQQ']['total_return'])}", f"A2_MINUS_QQQ_TOTAL_RETURN={display(m['A2']['total_return'] - m['QQQ']['total_return'])}", "",
        f"A_SHARPE={display(m['A']['sharpe'])}", f"A2_SHARPE={display(m['A2']['sharpe'])}", f"QQQ_SHARPE={display(m['QQQ']['sharpe'])}", "",
        f"A_MAX_DRAWDOWN={display(m['A']['maximum_drawdown'])}", f"A2_MAX_DRAWDOWN={display(m['A2']['maximum_drawdown'])}", f"QQQ_MAX_DRAWDOWN={display(m['QQQ']['maximum_drawdown'])}", "",
        f"A2_QQQ_BETA={display(r['beta_vs_qqq'])}", f"A2_QQQ_CORRELATION={display(r['daily_return_correlation_vs_qqq'])}", f"A2_QQQ_INFORMATION_RATIO={display(r['information_ratio_vs_qqq'])}", "",
        f"TRAINING_DATA_AFTER_2025_12_31_COUNT={a['TRAINING_DATA_AFTER_2025_12_31_COUNT']}", f"MODEL_FIT_DURING_THIS_RUN_COUNT={a['MODEL_FIT_DURING_THIS_RUN_COUNT']}", f"PARAMETER_SEARCH_COUNT={a['PARAMETER_SEARCH_COUNT']}", f"RISK_OVERLAY_COUNT={a['RISK_OVERLAY_COUNT']}", f"LOOKAHEAD_VIOLATION_COUNT={a['LOOKAHEAD_VIOLATION_COUNT']}", f"PIT_VIOLATION_COUNT={a['PIT_VIOLATION_COUNT']}", "",
        f"FINAL_CLASSIFICATION={summary['FINAL_CLASSIFICATION']}",
    ]
    print("\n".join(lines))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        summary = run(args.output_root)
    except Exception as exc:
        print("A_A2_2026_PRE_RISK_STATUS=FAIL_CLOSED")
        print(f"FAILURE_REASON={type(exc).__name__}:{exc}")
        print("FINAL_CLASSIFICATION=E")
        return 2
    print_final(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
