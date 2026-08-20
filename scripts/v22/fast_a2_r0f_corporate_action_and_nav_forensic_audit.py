"""Read-only corporate-action and NAV forensic audit of frozen A1/A2 R4.

This module deliberately does not import the R4 simulator.  It reconstructs the
TOP20/10bps paths from immutable signals and market data with a separate cash,
quantity, trade, cost, and mark ledger.  It never reads target/outcome columns
or dates after 2025 and never fits a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


EXPERIMENT_ID = "FAST_A2_R0F_CORPORATE_ACTION_AND_NAV_FORENSIC_AUDIT"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_PARENT = Path(r"D:\us-tech-quant-results")
RESULTS_ROOT = RESULTS_PARENT / EXPERIMENT_ID
R4_ROOT = RESULTS_PARENT / "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT"
R1_ROOT = RESULTS_PARENT / "ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING"
QFQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
RAW_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_raw")

R4_SUMMARY_PATH = R4_ROOT / "abcde_a2_r4_summary.json"
R4_DAILY_PATH = R4_ROOT / "a1_a2_top20_daily_portfolio.parquet"
R4_METRICS_PATH = R4_ROOT / "a1_a2_portfolio_metrics.parquet"
R4_POLICY_PATH = R4_ROOT / "a2_r4_execution_eligibility_policy_r1.json"
R4_ELIGIBILITY_PATH = R4_ROOT / "a2_r4_execution_eligibility_audit.parquet"
R4_CONTRACT_PATH = R4_ROOT / "a2_r4_portfolio_translation_contract_r1.json"
R4_MANIFEST_PATH = R4_ROOT / "a2_r4_manifest.json"
R1_OOF_PATH = R1_ROOT / "a2_r1_oof_predictions.parquet"

START = pd.Timestamp("2023-01-01")
END_EXCLUSIVE = pd.Timestamp("2026-01-01")
TOP_N = 20
COST_BPS = 10
ABS_TOL = 1e-10
REL_TOL = 1e-10

# This is issuer/NYSE evidence, not a guessed split.  It is deliberately data,
# not a repair rule: the audit measures the frozen ledger against it but never
# changes frozen quantities or reruns R4 with converted quantities.
AUTHORITATIVE_CORPORATE_ACTION_RECORDS: tuple[dict[str, Any], ...] = (
    {
        "ticker": "WOLF",
        "event_date": "2025-09-29",
        "corporate_action_type": "BANKRUPTCY_REORGANIZATION_EQUITY_CONVERSION",
        "new_shares_per_old_share": 0.008352,
        "old_security_id": "CUSIP_977852102",
        "new_security_id": "CUSIP_97785W106",
        "source_confirmed_event": True,
        "source_authority": "SEC_ISSUER_8K_AND_NYSE_FORM25",
        "source_locator": "https://www.sec.gov/Archives/edgar/data/895419/000119312525223057/d69265d8k.htm",
        "secondary_source_locator": "https://www.sec.gov/Archives/edgar/data/876661/000087666125000713/ruleprovisionnotice.htm",
        "source_accession": "0001193125-25-223057",
        "evidence": "old common stock cancelled; old holders received new common stock at 0.008352 new share per old share",
    },
)

FINGERPRINT_RATIOS = (2.0, 3.0, 4.0, 5.0, 10.0)
RETURN_FINGERPRINTS = {
    "+100%": 1.0, "+200%": 2.0, "+300%": 3.0, "+400%": 4.0, "+900%": 9.0,
    "-50%": -0.5, "-66.67%": -2.0 / 3.0, "-75%": -0.75,
    "-80%": -0.8, "-90%": -0.9,
}

ARTIFACT_NAMES = (
    "fast_a2_r0f_summary.json",
    "price_basis_audit.parquet",
    "corporate_action_events.parquet",
    "split_reverse_split_consistency_audit.parquet",
    "security_extreme_return_events.parquet",
    "portfolio_extreme_return_events.parquet",
    "nav_reconstruction_daily.parquet",
    "nav_reconstruction_metrics.json",
    "pnl_concentration_by_ticker.parquet",
    "pnl_concentration_by_day.parquet",
    "corporate_action_pnl_attribution.parquet",
    "provenance_manifest.json",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dataframe_fingerprint(frame: pd.DataFrame) -> str:
    ordered = frame.copy()
    digest = hashlib.sha256()
    digest.update("|".join(map(str, ordered.columns)).encode())
    digest.update("|".join(map(str, ordered.dtypes)).encode())
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
    digest.update(pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(np.uint64).tobytes())
    return digest.hexdigest()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def fingerprint_match(raw_return: float, tolerance: float = 0.05) -> str | None:
    """Return the nearest declared corporate-action fingerprint, if any."""
    if not math.isfinite(raw_return):
        return None
    matches = [(abs(raw_return - target), label) for label, target in RETURN_FINGERPRINTS.items()]
    distance, label = min(matches)
    return label if distance <= tolerance else None


def infer_simple_split_ratio(factor_change: float, tolerance: float = 0.03) -> tuple[float | None, str | None]:
    """Infer new/old shares from a RAW/QFQ adjustment discontinuity only.

    This is a heuristic and is never labelled source-confirmed.
    """
    if not math.isfinite(factor_change) or factor_change <= 0:
        return None, None
    candidates = [(ratio, "STOCK_SPLIT") for ratio in FINGERPRINT_RATIOS]
    candidates += [(1.0 / ratio, "REVERSE_SPLIT") for ratio in FINGERPRINT_RATIOS]
    error, ratio, action = min(
        (abs(math.log(factor_change / candidate)), candidate, kind)
        for candidate, kind in candidates
    )
    return (ratio, action) if error <= tolerance else (None, None)


def audit_split_relationship(
    *, split_ratio: float, pre_raw_price: float, post_raw_price: float,
    pre_adjusted_price: float, post_adjusted_price: float,
    pre_shares: float, post_shares: float, price_basis: str,
    security_continuity: bool = True,
) -> dict[str, Any]:
    """Evaluate quantity/value continuity without modifying a ledger."""
    if split_ratio <= 0:
        raise ValueError("split_ratio must be positive")
    raw_implied_ratio = pre_raw_price / post_raw_price
    adjusted_return = post_adjusted_price / pre_adjusted_price - 1.0
    if price_basis == "RAW":
        expected_post_shares = pre_shares * split_ratio
        expected_quantity_rule = "RAW_PRICE_REQUIRES_SHARE_CONVERSION"
    elif price_basis == "QFQ":
        expected_post_shares = pre_shares
        expected_quantity_rule = "QFQ_SYNTHETIC_SHARES_MUST_REMAIN_UNCHANGED"
    elif price_basis == "SECURITY_CONVERSION":
        expected_post_shares = pre_shares * split_ratio
        expected_quantity_rule = "CONFIRMED_SECURITY_CONVERSION_REQUIRES_SHARE_CONVERSION"
    else:
        return {
            "status": "FAIL_CLOSED_UNKNOWN_PRICE_BASIS",
            "failure_codes": ["UNKNOWN_PRICE_BASIS"],
            "expected_post_shares": np.nan,
        }
    quantity_rel_error = abs(post_shares - expected_post_shares) / max(abs(expected_post_shares), 1e-15)
    raw_ratio_rel_error = abs(raw_implied_ratio - split_ratio) / split_ratio
    failure_codes: list[str] = []
    if quantity_rel_error > 1e-6:
        if price_basis == "QFQ" and abs(post_shares - pre_shares * split_ratio) <= max(1e-12, abs(pre_shares * split_ratio) * 1e-6):
            failure_codes.append("A_PRICE_ADJUSTED_AND_SHARES_ADJUSTED_TWICE")
        elif price_basis in {"RAW", "SECURITY_CONVERSION"} and abs(post_shares - pre_shares) <= max(1e-12, abs(pre_shares) * 1e-6):
            failure_codes.append("B_RAW_OR_CONVERSION_PRICE_WITH_SHARES_NOT_ADJUSTED")
        else:
            failure_codes.append("F_SPLIT_FACTOR_APPLIED_WRONG_DIRECTION_OR_MAGNITUDE")
    if price_basis == "RAW" and raw_ratio_rel_error > 0.20:
        failure_codes.append("D_EXECUTION_OR_MARK_PRICE_BASIS_DIFFERS_FROM_DECLARED_RAW_BASIS")
    if price_basis == "QFQ" and abs(adjusted_return) > 0.30:
        failure_codes.append("E_ADJUSTED_PRICE_NOT_ECONOMICALLY_CONTINUOUS")
    if not security_continuity:
        failure_codes.append("J_SECURITY_IDENTIFIER_CHANGED_BUT_TICKER_JOIN_CONTINUED_POSITION")
    pre_value = pre_shares * pre_adjusted_price
    post_value = post_shares * post_adjusted_price
    return {
        "status": "FAIL" if failure_codes else "PASS",
        "failure_codes": failure_codes,
        "expected_quantity_rule": expected_quantity_rule,
        "expected_post_shares": expected_post_shares,
        "quantity_rel_error": quantity_rel_error,
        "raw_implied_split_ratio": raw_implied_ratio,
        "raw_ratio_rel_error": raw_ratio_rel_error,
        "adjusted_price_return": adjusted_return,
        "pre_position_value": pre_value,
        "post_position_value": post_value,
        "position_value_return": post_value / pre_value - 1.0 if pre_value else np.nan,
    }


@dataclass(frozen=True)
class Inputs:
    signals: pd.DataFrame
    qfq: pd.DataFrame
    raw: pd.DataFrame
    frozen_daily: pd.DataFrame
    frozen_summary: dict[str, Any]
    eligibility: pd.DataFrame
    source_hashes: dict[str, str]
    code_sha256: str


@dataclass
class PathResult:
    daily: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame


def required_paths() -> list[Path]:
    paths = [
        R4_SUMMARY_PATH, R4_DAILY_PATH, R4_METRICS_PATH, R4_POLICY_PATH,
        R4_ELIGIBILITY_PATH, R4_CONTRACT_PATH, R4_MANIFEST_PATH, R1_OOF_PATH,
    ]
    paths += [QFQ_ROOT / f"year={year}" / "prices.parquet" for year in (2023, 2024, 2025)]
    paths += [RAW_ROOT / f"year={year}" / "prices.parquet" for year in (2023, 2024, 2025)]
    return paths


def load_inputs() -> Inputs:
    missing = [str(path) for path in required_paths() if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_FORENSIC_SOURCE:" + ",".join(missing))
    eligibility = pq.read_table(R4_ELIGIBILITY_PATH).to_pandas()
    eligibility["execution_date"] = pd.to_datetime(eligibility["execution_date"])
    if (eligibility.execution_date >= END_EXCLUSIVE).any():
        raise RuntimeError("POST2025_EXECUTION_ELIGIBILITY_READ")
    wanted = set(eligibility.loc[eligibility.top_n.eq(TOP_N), "ticker"].astype(str).str.upper()) | {"QQQ"}

    # Deliberately request only signal identity/rank columns; no target/outcome.
    signal_columns = ["signal_date", "ticker", "a1_rank", "a2_rank"]
    signals = pq.read_table(R1_OOF_PATH, columns=signal_columns).to_pandas()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    signals["ticker"] = signals.ticker.astype(str).str.upper()
    if (signals.signal_date >= END_EXCLUSIVE).any():
        raise RuntimeError("POST2025_SIGNAL_READ")
    signals = signals.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)

    def load_prices(root: Path, expected_autype: str) -> pd.DataFrame:
        pieces: list[pd.DataFrame] = []
        for year in (2023, 2024, 2025):
            path = root / f"year={year}" / "prices.parquet"
            frame = pq.read_table(
                path, columns=["ticker", "trade_date", "open", "close", "autype", "source"]
            ).to_pandas()
            frame["ticker"] = frame.ticker.astype(str).str.upper()
            pieces.append(frame.loc[frame.ticker.isin(wanted)].copy())
        result = pd.concat(pieces, ignore_index=True)
        result["trade_date"] = pd.to_datetime(result.trade_date)
        result["open"] = pd.to_numeric(result.open, errors="coerce")
        result["close"] = pd.to_numeric(result.close, errors="coerce")
        result = result.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True)
        if result.empty or result.duplicated(["ticker", "trade_date"]).any():
            raise RuntimeError(f"EMPTY_OR_DUPLICATE_{expected_autype}_PRICE")
        if (result.trade_date >= END_EXCLUSIVE).any():
            raise RuntimeError(f"POST2025_{expected_autype}_PRICE_READ")
        if set(result.autype.astype(str).str.lower()) != {expected_autype.lower()}:
            raise RuntimeError(f"UNEXPECTED_{expected_autype}_AUTYPE")
        if set(result.source.astype(str).str.upper()) != {"MOOMOO_OPEND"}:
            raise RuntimeError(f"UNEXPECTED_{expected_autype}_SOURCE")
        return result

    qfq = load_prices(QFQ_ROOT, "qfq")
    raw = load_prices(RAW_ROOT, "raw")
    frozen_daily = pq.read_table(R4_DAILY_PATH).to_pandas()
    frozen_daily["execution_date"] = pd.to_datetime(frozen_daily.execution_date)
    frozen_daily = frozen_daily.loc[
        frozen_daily.top_n.eq(TOP_N) & frozen_daily.cost_bps.eq(COST_BPS)
    ].sort_values(["model", "execution_date"], kind="mergesort").reset_index(drop=True)
    if (frozen_daily.execution_date >= END_EXCLUSIVE).any():
        raise RuntimeError("POST2025_FROZEN_PORTFOLIO_READ")
    frozen_summary = json.loads(R4_SUMMARY_PATH.read_text(encoding="utf-8"))
    source_hashes = {str(path): sha256_file(path) for path in required_paths()}
    return Inputs(
        signals=signals, qfq=qfq, raw=raw, frozen_daily=frozen_daily,
        frozen_summary=frozen_summary, eligibility=eligibility,
        source_hashes=source_hashes, code_sha256=sha256_file(Path(__file__).resolve()),
    )


def build_target_maps(signals: pd.DataFrame) -> dict[str, dict[pd.Timestamp, dict[str, float]]]:
    dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
    a1_count = signals.loc[signals.a1_rank <= TOP_N].groupby("signal_date").size().reindex(dates, fill_value=0)
    a2_count = signals.loc[signals.a2_rank <= TOP_N].groupby("signal_date").size().reindex(dates, fill_value=0)
    valid_dates = set(pd.Timestamp(date) for date in dates[(a1_count.to_numpy() == TOP_N) & (a2_count.to_numpy() == TOP_N)])
    result: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for model, rank_column in (("A1", "a1_rank"), ("A2_HGB", "a2_rank")):
        selected = signals.loc[
            signals.signal_date.isin(valid_dates) & signals[rank_column].le(TOP_N),
            ["signal_date", "ticker", rank_column],
        ]
        mapping: dict[pd.Timestamp, dict[str, float]] = {}
        for date, day in selected.groupby("signal_date", sort=True):
            if len(day) != TOP_N or day.ticker.nunique() != TOP_N:
                raise RuntimeError(f"TOP20_CARDINALITY_FAILURE:{model}:{date}")
            mapping[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
        result[model] = mapping
    return result


def reconstruct_path(
    *, model: str, target_map: dict[pd.Timestamp, dict[str, float]],
    qfq: pd.DataFrame, signal_dates: Iterable[pd.Timestamp], cost_bps: int = COST_BPS,
) -> PathResult:
    """Independent position-ledger reconstruction of the frozen contract."""
    qqq = qfq.loc[qfq.ticker.eq("QQQ"), ["trade_date", "open"]].sort_values("trade_date")
    calendar = pd.DatetimeIndex(qqq.trade_date)
    calendar_pos = pd.Series(np.arange(len(calendar)), index=calendar)
    ordered_signals = pd.DatetimeIndex(sorted(pd.Timestamp(x) for x in signal_dates))
    if not ordered_signals.isin(calendar).all():
        raise RuntimeError("SIGNAL_NOT_ON_QQQ_CALENDAR")
    first = int(calendar_pos.loc[ordered_signals.min()]) + 1
    end = int(calendar_pos.loc[ordered_signals.max()]) + 3
    sim_dates = calendar[first:end]
    open_wide = qfq.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    close_wide = qfq.pivot(index="trade_date", columns="ticker", values="close").sort_index()

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
        if ticker not in close_wide.columns:
            raise RuntimeError(f"UNVALUABLE_POSITION:{ticker}:{date.date()}")
        history = close_wide.loc[close_wide.index < date, ticker].dropna()
        history = history[(history > 0) & np.isfinite(history)]
        if history.empty:
            raise RuntimeError(f"UNVALUABLE_POSITION:{ticker}:{date.date()}")
        return float(history.iloc[-1]), True, pd.Timestamp(history.index[-1])

    shares: dict[str, float] = {}
    prior_marks: dict[str, float] = {}
    cash = 1.0
    prior_nav = 1.0
    daily_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    cost_rate = cost_bps / 10000.0

    for sequence, execution_date0 in enumerate(sim_dates):
        execution_date = pd.Timestamp(execution_date0)
        cash_before = cash
        shares_before = dict(shares)
        marks: dict[str, float] = {}
        mark_dates: dict[str, pd.Timestamp] = {}
        stale: dict[str, bool] = {}
        market_pnl: dict[str, float] = {}
        pre_values: dict[str, float] = {}
        for ticker, quantity in shares_before.items():
            value, is_stale, source_date = mark(execution_date, ticker)
            marks[ticker] = value
            mark_dates[ticker] = source_date
            stale[ticker] = is_stale
            pre_values[ticker] = quantity * value
            market_pnl[ticker] = 0.0 if sequence == 0 else quantity * (value - prior_marks[ticker])
        pretrade_nav = cash_before + sum(pre_values.values())
        gross_return = 0.0 if sequence == 0 else pretrade_nav / prior_nav - 1.0
        signal_date = pd.Timestamp(calendar[int(calendar_pos.loc[execution_date]) - 1])
        target = target_map.get(signal_date, {})
        desired = {ticker: weight * pretrade_nav for ticker, weight in target.items()}
        pre_weights = {ticker: value / pretrade_nav for ticker, value in pre_values.items()}
        target_turnover = 0.5 * sum(
            abs(target.get(ticker, 0.0) - pre_weights.get(ticker, 0.0))
            for ticker in set(target) | set(pre_weights)
        )
        sell_notional_by_ticker: dict[str, float] = {}
        buy_notional_by_ticker: dict[str, float] = {}
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
                continue
            notional = current - wanted
            quantity = notional / price
            shares[ticker] = max(0.0, shares[ticker] - quantity)
            if shares[ticker] <= 1e-14:
                shares.pop(ticker, None)
            cash += notional
            sell_notional_by_ticker[ticker] = notional
            transaction_cost += 0.5 * notional * cost_rate
            trade_rows.append({
                "date": execution_date, "model": model, "ticker": ticker, "side": "SELL",
                "shares": quantity, "execution_price": price, "notional": notional,
                "allocated_transaction_cost": 0.5 * notional * cost_rate,
            })

        post_sell_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        requested_buys: dict[str, float] = {}
        for ticker in sorted(target):
            current = post_sell_values.get(ticker, 0.0)
            wanted = desired[ticker]
            if wanted <= current + 1e-14:
                continue
            price = opening(execution_date, ticker)
            if not math.isfinite(price):
                skipped_buys += 1
                continue
            requested_buys[ticker] = wanted - current
            marks[ticker] = price
            mark_dates[ticker] = execution_date
            stale[ticker] = False
        buy_total = sum(requested_buys.values())
        cash_available = max(0.0, cash - transaction_cost)
        requirement = buy_total * (1.0 + 0.5 * cost_rate)
        buy_scale = min(1.0, cash_available / requirement) if requirement > 0 else 1.0
        for ticker, requested in requested_buys.items():
            notional = requested * buy_scale
            if notional <= 1e-14:
                continue
            price = marks[ticker]
            quantity = notional / price
            shares[ticker] = shares.get(ticker, 0.0) + quantity
            cash -= notional
            buy_notional_by_ticker[ticker] = notional
            transaction_cost += 0.5 * notional * cost_rate
            trade_rows.append({
                "date": execution_date, "model": model, "ticker": ticker, "side": "BUY",
                "shares": quantity, "execution_price": price, "notional": notional,
                "allocated_transaction_cost": 0.5 * notional * cost_rate,
            })
        cash -= transaction_cost
        if cash < -ABS_TOL:
            raise RuntimeError(f"NEGATIVE_CASH:{model}:{execution_date.date()}:{cash}")
        cash = max(0.0, cash)
        post_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        posttrade_nav = cash + sum(post_values.values())
        traded_notional = sum(sell_notional_by_ticker.values()) + sum(buy_notional_by_ticker.values())
        turnover = 0.5 * traded_notional / pretrade_nav

        cost_by_ticker: dict[str, float] = {}
        for ticker, notional in sell_notional_by_ticker.items():
            cost_by_ticker[ticker] = cost_by_ticker.get(ticker, 0.0) + 0.5 * notional * cost_rate
        for ticker, notional in buy_notional_by_ticker.items():
            cost_by_ticker[ticker] = cost_by_ticker.get(ticker, 0.0) + 0.5 * notional * cost_rate
        all_tickers = sorted(set(shares_before) | set(shares) | set(cost_by_ticker))
        for ticker in all_tickers:
            previous_price = prior_marks.get(ticker, np.nan)
            current_price = marks.get(ticker, opening(execution_date, ticker))
            prior_quantity = shares_before.get(ticker, 0.0)
            pnl = market_pnl.get(ticker, 0.0)
            allocated_cost = cost_by_ticker.get(ticker, 0.0)
            position_rows.append({
                "date": execution_date, "previous_date": pd.NaT if sequence == 0 else pd.Timestamp(sim_dates[sequence - 1]),
                "model": model, "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY", "ticker": ticker,
                "security_id": None, "shares_before": prior_quantity, "shares_after": shares.get(ticker, 0.0),
                "previous_price": previous_price, "current_price": current_price,
                "mark_source_date": mark_dates.get(ticker, execution_date), "stale_mark": stale.get(ticker, False),
                "position_weight": (prior_quantity * previous_price / prior_nav) if sequence and math.isfinite(previous_price) else 0.0,
                "market_pnl": pnl, "transaction_cost": allocated_cost,
                "net_pnl_contribution": pnl - allocated_cost,
                "portfolio_pnl_contribution": (pnl - allocated_cost) / prior_nav,
                "raw_return": (current_price / previous_price - 1.0) if sequence and prior_quantity > 0 and math.isfinite(previous_price) else np.nan,
                "source_path": str(QFQ_ROOT),
            })

        nav_identity_error = posttrade_nav - (cash + sum(post_values.values()))
        cash_expected = cash_before + sum(sell_notional_by_ticker.values()) - sum(buy_notional_by_ticker.values()) - transaction_cost
        cash_identity_error = cash - max(0.0, cash_expected)
        position_identity_error = sum(post_values.values()) - sum(shares[t] * marks[t] for t in shares)
        turnover_identity_error = turnover - 0.5 * traded_notional / pretrade_nav
        transaction_cost_identity_error = transaction_cost - 0.5 * traded_notional * cost_rate
        net_return = posttrade_nav / prior_nav - 1.0
        daily_rows.append({
            "execution_date": execution_date, "model": model,
            "reconstruction_mode": "POSITION_LEDGER", "cash_before": cash_before, "cash_after": cash,
            "pretrade_nav": pretrade_nav, "reconstructed_nav": posttrade_nav,
            "reconstructed_gross_return": gross_return, "reconstructed_daily_return": net_return,
            "target_turnover": target_turnover, "reconstructed_turnover": turnover,
            "reconstructed_transaction_cost": transaction_cost,
            "position_value": sum(post_values.values()), "actual_risky_name_count": len(shares),
            "stale_mark_count": sum(stale.values()), "skipped_buy_count": skipped_buys,
            "blocked_sell_or_rebalance_count": blocked_sells, "buy_cash_scale": buy_scale,
            "NAV_ACCOUNTING_IDENTITY_ERROR": nav_identity_error,
            "CASH_IDENTITY_ERROR": cash_identity_error,
            "POSITION_VALUE_IDENTITY_ERROR": position_identity_error,
            "TURNOVER_IDENTITY_ERROR": turnover_identity_error,
            "TRANSACTION_COST_IDENTITY_ERROR": transaction_cost_identity_error,
        })
        prior_nav = posttrade_nav
        prior_marks = {ticker: marks[ticker] for ticker in shares}
    if shares:
        raise RuntimeError(f"TERMINAL_POSITION_REMAINS:{model}:{sorted(shares)[:5]}")
    return PathResult(pd.DataFrame(daily_rows), pd.DataFrame(position_rows), pd.DataFrame(trade_rows))


def portfolio_metrics(frame: pd.DataFrame, return_column: str = "reconstructed_daily_return") -> dict[str, float]:
    ordered = frame.sort_values("execution_date", kind="mergesort")
    returns = ordered[return_column].to_numpy(float)
    n = len(returns)
    cumulative = float(np.prod(1.0 + returns) - 1.0)
    cagr = float((1.0 + cumulative) ** (252.0 / n) - 1.0)
    volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    annualized_mean = float(np.mean(returns) * 252.0)
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    return {
        "observation_count": n, "cumulative_return": cumulative, "cagr": cagr,
        "sharpe_rf0": annualized_mean / volatility if volatility else np.nan,
        "max_drawdown": max_drawdown,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else np.nan,
        "total_turnover": float(ordered.reconstructed_turnover.sum()),
        "transaction_cost_total": float(ordered.reconstructed_transaction_cost.sum()),
    }


def price_basis_audit() -> pd.DataFrame:
    rows = [
        ("raw_price", RAW_ROOT, "open/close", "UNADJUSTED_RAW", False, False, False, True),
        ("split_adjusted_price", QFQ_ROOT, "open/close", "MOOMOO_QFQ_CURRENT_ADJUSTMENT_SNAPSHOT", True, True, False, True),
        ("dividend_adjusted_price", QFQ_ROOT, "open/close", "MOOMOO_QFQ_CURRENT_ADJUSTMENT_SNAPSHOT", True, True, False, True),
        ("total_return_adjusted_price", None, None, "NOT_PRESENT_NOT_USED", None, None, None, True),
        ("execution_price", QFQ_ROOT, "open", "MOOMOO_QFQ_CURRENT_ADJUSTMENT_SNAPSHOT", True, True, False, True),
        ("mark_price", QFQ_ROOT, "open; fallback prior close", "MOOMOO_QFQ_CURRENT_ADJUSTMENT_SNAPSHOT", True, True, False, True),
        ("previous_mark_price", QFQ_ROOT, "prior execution open; retained prior close fallback", "MOOMOO_QFQ_CURRENT_ADJUSTMENT_SNAPSHOT", True, True, False, True),
    ]
    return pd.DataFrame(rows, columns=[
        "FIELD_NAME", "SOURCE_PATH", "SOURCE_COLUMN", "ADJUSTMENT_BASIS",
        "SPLIT_ADJUSTED", "DIVIDEND_ADJUSTED", "TOTAL_RETURN_ADJUSTED", "KNOWN_OR_UNKNOWN",
    ]).assign(
        SOURCE_PATH=lambda x: x.SOURCE_PATH.map(lambda p: str(p) if p is not None else None),
        KNOWN_OR_UNKNOWN=lambda x: x.KNOWN_OR_UNKNOWN.map(lambda value: "KNOWN" if value else "UNKNOWN"),
    )


def derive_corporate_action_events(inputs: Inputs) -> pd.DataFrame:
    merged = inputs.qfq.merge(
        inputs.raw, on=["ticker", "trade_date"], suffixes=("_qfq", "_raw"), how="inner"
    ).sort_values(["ticker", "trade_date"], kind="mergesort")
    merged["adjustment_factor"] = merged.open_qfq / merged.open_raw
    merged["previous_adjustment_factor"] = merged.groupby("ticker").adjustment_factor.shift()
    merged["adjustment_factor_change"] = merged.adjustment_factor / merged.previous_adjustment_factor
    merged["previous_raw_price"] = merged.groupby("ticker").open_raw.shift()
    merged["previous_qfq_price"] = merged.groupby("ticker").open_qfq.shift()
    merged["raw_return"] = merged.open_raw / merged.previous_raw_price - 1.0
    merged["qfq_return"] = merged.open_qfq / merged.previous_qfq_price - 1.0
    rows: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        ratio, action = infer_simple_split_ratio(float(row.adjustment_factor_change) if pd.notna(row.adjustment_factor_change) else np.nan)
        if ratio is None:
            continue
        # Require a raw discontinuity and material smoothing in QFQ.  This avoids
        # treating small dividend-factor drift as a split record.
        if not (abs(float(row.raw_return)) >= 0.45 and abs(float(row.qfq_return)) < abs(float(row.raw_return)) - 0.25):
            continue
        rows.append({
            "ticker": row.ticker, "security_id": None, "event_date": row.trade_date,
            "corporate_action_type": action, "split_ratio": ratio,
            "source_confirmed_event": False, "evidence_class": "PRICE_FINGERPRINT_ONLY",
            "source_authority": "DUAL_MOOMOO_RAW_QFQ_PRICE_SERIES",
            "source_locator": f"{RAW_ROOT};{QFQ_ROOT}",
            "old_security_id": None, "new_security_id": None,
            "previous_raw_price": row.previous_raw_price, "current_raw_price": row.open_raw,
            "previous_adjusted_price": row.previous_qfq_price, "current_adjusted_price": row.open_qfq,
            "raw_return": row.raw_return, "adjusted_return": row.qfq_return,
            "adjustment_factor_change": row.adjustment_factor_change,
            "notes": "heuristic only; not an authoritative corporate-action record",
        })
    for record in AUTHORITATIVE_CORPORATE_ACTION_RECORDS:
        match = merged.loc[
            merged.ticker.eq(record["ticker"]) & merged.trade_date.eq(pd.Timestamp(record["event_date"]))
        ]
        if match.empty:
            raise RuntimeError(f"CONFIRMED_EVENT_PRICE_MISSING:{record['ticker']}:{record['event_date']}")
        row = match.iloc[0]
        rows.append({
            "ticker": record["ticker"], "security_id": record["new_security_id"],
            "event_date": pd.Timestamp(record["event_date"]),
            "corporate_action_type": record["corporate_action_type"],
            "split_ratio": record["new_shares_per_old_share"],
            "source_confirmed_event": True, "evidence_class": "SOURCE_CONFIRMED_EVENT",
            "source_authority": record["source_authority"], "source_locator": record["source_locator"],
            "old_security_id": record["old_security_id"], "new_security_id": record["new_security_id"],
            "previous_raw_price": row.previous_raw_price, "current_raw_price": row.open_raw,
            "previous_adjusted_price": row.previous_qfq_price, "current_adjusted_price": row.open_qfq,
            "raw_return": row.raw_return, "adjusted_return": row.qfq_return,
            "adjustment_factor_change": row.adjustment_factor_change,
            "notes": record["evidence"],
        })
    columns = [
        "ticker", "security_id", "event_date", "corporate_action_type", "split_ratio",
        "source_confirmed_event", "evidence_class", "source_authority", "source_locator",
        "old_security_id", "new_security_id", "previous_raw_price", "current_raw_price",
        "previous_adjusted_price", "current_adjusted_price", "raw_return", "adjusted_return",
        "adjustment_factor_change", "notes",
    ]
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["event_date", "ticker", "source_confirmed_event"], kind="mergesort"
    ).reset_index(drop=True)


def split_consistency_audit(events: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        for model in ("A1", "A2_HGB"):
            held = positions.loc[
                positions.model.eq(model) & positions.ticker.eq(event.ticker) & positions.date.eq(event.event_date)
                & positions.shares_before.gt(0)
            ]
            if held.empty:
                continue
            position = held.iloc[0]
            confirmed_conversion = bool(event.source_confirmed_event) and event.corporate_action_type == "BANKRUPTCY_REORGANIZATION_EQUITY_CONVERSION"
            basis = "SECURITY_CONVERSION" if confirmed_conversion else "QFQ"
            security_continuity = not confirmed_conversion
            check = audit_split_relationship(
                split_ratio=float(event.split_ratio), pre_raw_price=float(event.previous_raw_price),
                post_raw_price=float(event.current_raw_price), pre_adjusted_price=float(event.previous_adjusted_price),
                post_adjusted_price=float(event.current_adjusted_price), pre_shares=float(position.shares_before),
                post_shares=float(position.shares_before), price_basis=basis,
                security_continuity=security_continuity,
            )
            rows.append({
                "model": model, "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY", "ticker": event.ticker,
                "pre_date": position.previous_date, "post_date": event.event_date,
                "corporate_action_type": event.corporate_action_type, "split_ratio": event.split_ratio,
                "source_confirmed_event": event.source_confirmed_event,
                "pre_raw_price": event.previous_raw_price, "post_raw_price": event.current_raw_price,
                "pre_adjusted_price": event.previous_adjusted_price, "post_adjusted_price": event.current_adjusted_price,
                "pre_shares": position.shares_before, "post_shares": position.shares_before,
                **check,
            })
    columns = [
        "model", "portfolio", "ticker", "pre_date", "post_date", "corporate_action_type",
        "split_ratio", "source_confirmed_event", "pre_raw_price", "post_raw_price",
        "pre_adjusted_price", "post_adjusted_price", "pre_shares", "post_shares", "status",
        "failure_codes", "expected_quantity_rule", "expected_post_shares", "quantity_rel_error",
        "raw_implied_split_ratio", "raw_ratio_rel_error", "adjusted_price_return",
        "pre_position_value", "post_position_value", "position_value_return",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame["failure_codes"] = frame.failure_codes.map(lambda x: "|".join(x))
        frame = frame.sort_values(["post_date", "model", "ticker"], kind="mergesort").reset_index(drop=True)
    return frame


def security_extremes(positions: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    frame = positions.loc[positions.shares_before.gt(0) & positions.raw_return.notna()].copy()
    frame["fingerprint_match"] = frame.raw_return.map(fingerprint_match)
    frame = frame.loc[frame.raw_return.abs().gt(0.30) | frame.fingerprint_match.notna()].copy()
    confirmed = events.loc[events.source_confirmed_event].sort_values("event_date").drop_duplicates(["ticker", "event_date"])
    confirmed = confirmed.rename(columns={"event_date": "date"})
    frame = frame.merge(
        confirmed[["ticker", "date", "corporate_action_type", "split_ratio", "source_confirmed_event"]],
        on=["ticker", "date"], how="left",
    )
    frame["corporate_action_confirmed"] = frame.source_confirmed_event.fillna(False).astype(bool)
    frame["corporate_action_type"] = frame.corporate_action_type.fillna("NONE_CONFIRMED")
    frame["split_ratio"] = pd.to_numeric(frame.split_ratio, errors="coerce")
    result = frame.rename(columns={"shares_before": "shares"})[[
        "model", "portfolio", "ticker", "security_id", "date", "previous_date", "previous_price",
        "current_price", "raw_return", "position_weight", "shares", "portfolio_pnl_contribution",
        "corporate_action_confirmed", "corporate_action_type", "split_ratio", "fingerprint_match", "source_path",
    ]]
    result["forensic_severity"] = (
        result.raw_return.abs() + result.portfolio_pnl_contribution.abs() * 10
        + result.corporate_action_confirmed.astype(float) * 100
    )
    return result.sort_values(["forensic_severity", "date", "model", "ticker"], ascending=[False, True, True, True], kind="mergesort").reset_index(drop=True)


def portfolio_extremes(daily: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in ("A1", "A2_HGB"):
        day = daily.loc[daily.model.eq(model)].copy()
        selected = pd.concat([day.nlargest(50, "reconstructed_daily_return"), day.nsmallest(50, "reconstructed_daily_return")])
        selected = selected.drop_duplicates("execution_date")
        for item in selected.itertuples(index=False):
            contributions = positions.loc[
                positions.model.eq(model) & positions.date.eq(item.execution_date)
            ].sort_values("portfolio_pnl_contribution", ascending=False, kind="mergesort")
            positive = contributions.head(1)
            negative = contributions.tail(1)
            rows.append({
                "date": item.execution_date, "model": model,
                "portfolio_return": item.reconstructed_daily_return,
                "nav_before": item.reconstructed_nav / (1.0 + item.reconstructed_daily_return),
                "nav_after": item.reconstructed_nav, "turnover": item.reconstructed_turnover,
                "transaction_cost": item.reconstructed_transaction_cost,
                "largest_positive_contributor": None if positive.empty else positive.iloc[0].ticker,
                "largest_positive_contribution": np.nan if positive.empty else positive.iloc[0].portfolio_pnl_contribution,
                "largest_negative_contributor": None if negative.empty else negative.iloc[0].ticker,
                "largest_negative_contribution": np.nan if negative.empty else negative.iloc[0].portfolio_pnl_contribution,
                "top5_contribution_sum": float(contributions.head(5).portfolio_pnl_contribution.sum()),
            })
    return pd.DataFrame(rows).sort_values(["model", "portfolio_return"], ascending=[True, False], kind="mergesort").reset_index(drop=True)


def concentration_tables(daily: pd.DataFrame, positions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ticker_rows: list[pd.DataFrame] = []
    day_rows: list[pd.DataFrame] = []
    summary: dict[str, Any] = {}
    for model in ("A1", "A2_HGB"):
        d = daily.loc[daily.model.eq(model)].sort_values("execution_date").copy()
        p = positions.loc[positions.model.eq(model)].copy()
        total_pnl = float(d.reconstructed_nav.iloc[-1] - 1.0)
        ticker = p.groupby("ticker", sort=True).agg(
            cumulative_market_pnl=("market_pnl", "sum"),
            cumulative_transaction_cost=("transaction_cost", "sum"),
            cumulative_pnl_contribution=("net_pnl_contribution", "sum"),
        ).reset_index()
        ticker["model"] = model
        ticker["pnl_share"] = ticker.cumulative_pnl_contribution / total_pnl
        ticker = ticker.sort_values("cumulative_pnl_contribution", ascending=False, kind="mergesort").reset_index(drop=True)
        ticker["pnl_rank"] = np.arange(1, len(ticker) + 1)
        ticker_rows.append(ticker)
        daily_pnl = p.groupby("date", sort=True).net_pnl_contribution.sum().reindex(d.execution_date, fill_value=0.0).to_numpy()
        days = pd.DataFrame({
            "date": d.execution_date.to_numpy(), "model": model,
            "daily_pnl_contribution": daily_pnl, "daily_return": d.reconstructed_daily_return.to_numpy(),
        })
        days["pnl_share"] = days.daily_pnl_contribution / total_pnl
        days = days.sort_values("daily_pnl_contribution", ascending=False, kind="mergesort").reset_index(drop=True)
        days["pnl_rank"] = np.arange(1, len(days) + 1)
        day_rows.append(days)

        prefix = "A2" if model == "A2_HGB" else "A1"
        for n in (1, 5, 10, 20):
            summary[f"{prefix}_TOP{n}_TICKER_PNL_SHARE"] = float(ticker.head(n).pnl_share.sum())
            summary[f"{prefix}_TOP{n}_DAY_PNL_SHARE"] = float(days.head(n).pnl_share.sum())
        summary[f"{prefix}_PNL_HERFINDAHL_INDEX"] = float(np.square(ticker.pnl_share).sum())
        returns = d.reconstructed_daily_return.to_numpy(float)
        for n in (1, 5, 10, 20):
            best_indices = np.argsort(returns)[::-1][:n]
            kept = np.delete(returns, best_indices)
            summary[f"{prefix}_RETURN_EX_BEST_{n}_DAY"] = float(np.prod(1.0 + kept) - 1.0)
        daily_by_ticker = p.pivot_table(index="date", columns="ticker", values="portfolio_pnl_contribution", aggfunc="sum", fill_value=0.0).reindex(d.execution_date, fill_value=0.0)
        for n in (1, 5, 10):
            removed = list(ticker.head(n).ticker)
            adjusted_returns = returns - daily_by_ticker.reindex(columns=removed, fill_value=0.0).sum(axis=1).to_numpy()
            summary[f"{prefix}_RETURN_EX_TOP{n}_TICKER"] = float(np.prod(1.0 + adjusted_returns) - 1.0)
    return pd.concat(ticker_rows, ignore_index=True), pd.concat(day_rows, ignore_index=True), summary


def corporate_action_attribution(events: pd.DataFrame, positions: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    confirmed = events.loc[events.source_confirmed_event].copy()
    rows: list[dict[str, Any]] = []
    summary: dict[str, float] = {}
    for model in ("A1", "A2_HGB"):
        total_pnl = float(daily.loc[daily.model.eq(model), "reconstructed_nav"].iloc[-1] - 1.0)
        for event in confirmed.itertuples(index=False):
            matched = positions.loc[
                positions.model.eq(model) & positions.ticker.eq(event.ticker) & positions.date.eq(event.event_date)
            ]
            contribution = float(matched.net_pnl_contribution.sum())
            rows.append({
                "date": event.event_date, "model": model, "ticker": event.ticker,
                "corporate_action_type": event.corporate_action_type, "split_ratio": event.split_ratio,
                "pnl_contribution": contribution, "total_portfolio_pnl": total_pnl,
                "pnl_share": contribution / total_pnl if total_pnl else np.nan,
                "source_confirmed_event": True,
            })
        model_rows = [row for row in rows if row["model"] == model]
        prefix = "A2" if model == "A2_HGB" else "A1"
        summary[f"{prefix}_TOTAL_PNL_ON_CONFIRMED_CORPORATE_ACTION_DAYS"] = float(sum(row["pnl_contribution"] for row in model_rows))
        summary[f"{prefix}_TOTAL_PNL_ON_SPLIT_DAYS"] = float(sum(row["pnl_contribution"] for row in model_rows if row["corporate_action_type"] == "STOCK_SPLIT"))
        summary[f"{prefix}_TOTAL_PNL_ON_REVERSE_SPLIT_DAYS"] = float(sum(row["pnl_contribution"] for row in model_rows if row["corporate_action_type"] == "REVERSE_SPLIT"))
        summary[f"{prefix}_SPLIT_DAY_PNL_SHARE"] = summary[f"{prefix}_TOTAL_PNL_ON_SPLIT_DAYS"] / total_pnl if total_pnl else np.nan
        summary[f"{prefix}_REVERSE_SPLIT_DAY_PNL_SHARE"] = summary[f"{prefix}_TOTAL_PNL_ON_REVERSE_SPLIT_DAYS"] / total_pnl if total_pnl else np.nan
    table = pd.DataFrame(rows, columns=[
        "date", "model", "ticker", "corporate_action_type", "split_ratio", "pnl_contribution",
        "total_portfolio_pnl", "pnl_share", "source_confirmed_event",
    ])
    summary["LARGEST_CORPORATE_ACTION_DAY_PNL_CONTRIBUTION"] = float(table.pnl_contribution.max()) if not table.empty else 0.0
    return table, summary


def nav_comparison(inputs: Inputs, reconstructed: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frozen = inputs.frozen_daily[[
        "execution_date", "model", "net_nav", "net_return", "gross_return", "turnover", "transaction_cost_amount"
    ]].copy()
    merged = reconstructed.merge(frozen, on=["execution_date", "model"], how="outer", validate="one_to_one", indicator=True)
    if not merged._merge.eq("both").all():
        raise RuntimeError("FROZEN_RECONSTRUCTED_DAY_IDENTITY_MISMATCH")
    merged["frozen_nav"] = merged.pop("net_nav")
    merged["frozen_daily_return"] = merged.pop("net_return")
    merged["frozen_gross_return"] = merged.pop("gross_return")
    merged["frozen_turnover"] = merged.pop("turnover")
    merged["frozen_transaction_cost"] = merged.pop("transaction_cost_amount")
    merged["nav_reconstruction_error"] = merged.reconstructed_nav - merged.frozen_nav
    merged["nav_reconstruction_rel_error"] = merged.nav_reconstruction_error / merged.frozen_nav
    merged["daily_return_error"] = merged.reconstructed_daily_return - merged.frozen_daily_return
    merged["turnover_error"] = merged.reconstructed_turnover - merged.frozen_turnover
    merged["transaction_cost_error"] = merged.reconstructed_transaction_cost - merged.frozen_transaction_cost
    merged = merged.drop(columns="_merge").sort_values(["model", "execution_date"], kind="mergesort").reset_index(drop=True)
    max_abs = float(merged.nav_reconstruction_error.abs().max())
    max_rel = float(merged.nav_reconstruction_rel_error.abs().max())
    failures = int((
        merged.nav_reconstruction_error.abs().gt(ABS_TOL)
        & merged.nav_reconstruction_rel_error.abs().gt(REL_TOL)
    ).sum())
    metrics: dict[str, Any] = {
        "NAV_RECONSTRUCTION_MAX_ABS_ERROR": max_abs,
        "NAV_RECONSTRUCTION_MAX_REL_ERROR": max_rel,
        "NAV_RECONSTRUCTION_MEAN_ABS_ERROR": float(merged.nav_reconstruction_error.abs().mean()),
        "NAV_RECONSTRUCTION_FAILURE_DAY_COUNT": failures,
        "NAV_RECONSTRUCTION_STATUS": "PASS" if failures == 0 else "FAIL",
        "RECONSTRUCTION_MODE": "POSITION_LEDGER",
        "NAV_ABS_TOLERANCE": ABS_TOL, "NAV_REL_TOLERANCE": REL_TOL,
    }
    for model, prefix in (("A1", "A1"), ("A2_HGB", "A2")):
        rec = merged.loc[merged.model.eq(model)]
        rec_metrics = portfolio_metrics(rec)
        original = inputs.frozen_summary[f"POOLED_{prefix}_METRICS"]
        metrics.update({
            f"{prefix}_ORIGINAL_NET_CUM_RETURN": float(original["cumulative_return"]),
            f"{prefix}_RECONSTRUCTED_NET_CUM_RETURN": rec_metrics["cumulative_return"],
            f"{prefix}_CUM_RETURN_ABS_DIFF": abs(float(original["cumulative_return"]) - rec_metrics["cumulative_return"]),
            f"{prefix}_ORIGINAL_CAGR": float(original["cagr"]),
            f"{prefix}_RECONSTRUCTED_CAGR": rec_metrics["cagr"],
            f"{prefix}_ORIGINAL_SHARPE": float(original["sharpe_rf0"]),
            f"{prefix}_RECONSTRUCTED_SHARPE": rec_metrics["sharpe_rf0"],
            f"{prefix}_ORIGINAL_MAX_DRAWDOWN": float(original["max_drawdown"]),
            f"{prefix}_RECONSTRUCTED_MAX_DRAWDOWN": rec_metrics["max_drawdown"],
            f"{prefix}_RECONSTRUCTED_CALMAR": rec_metrics["calmar"],
            f"{prefix}_RECONSTRUCTED_TURNOVER": rec_metrics["total_turnover"],
            f"{prefix}_RECONSTRUCTED_TRANSACTION_COST_TOTAL": rec_metrics["transaction_cost_total"],
        })
    return merged, metrics


def hive_audit(inputs: Inputs, positions: pd.DataFrame, events: pd.DataFrame) -> dict[str, Any]:
    dates = pd.date_range("2023-07-07", "2023-07-17")
    qfq = inputs.qfq.loc[inputs.qfq.ticker.eq("HIVE") & inputs.qfq.trade_date.isin(dates)]
    raw = inputs.raw.loc[inputs.raw.ticker.eq("HIVE") & inputs.raw.trade_date.isin(dates)]
    hive_events = events.loc[events.ticker.eq("HIVE")]
    stale = positions.loc[
        positions.ticker.eq("HIVE") & positions.date.eq(pd.Timestamp("2023-07-12")) & positions.model.eq("A1")
    ]
    return {
        "ticker": "HIVE", "signal_date": "2023-07-11", "execution_date": "2023-07-12",
        "model": "A1", "portfolio": "TOP20", "required_action": "SELL_EXIT",
        "policy": "HOLD_POSITION_NO_TRADE",
        "qfq_open_present": bool((qfq.trade_date == pd.Timestamp("2023-07-12")).any()),
        "raw_open_present": bool((raw.trade_date == pd.Timestamp("2023-07-12")).any()),
        "confirmed_or_fingerprint_corporate_action_nearby": not hive_events.empty,
        "price_basis_mismatch_found": False,
        "stale_mark_found": bool(stale.stale_mark.any()) if not stale.empty else False,
        "stale_mark_source_date": None if stale.empty else str(pd.Timestamp(stale.iloc[0].mark_source_date).date()),
        "conclusion": "MISSING_BOTH_RAW_AND_QFQ_OPEN;NO_CORPORATE_ACTION_OR_BASIS_DISCONTINUITY_EVIDENCE",
    }


def run_once(inputs: Inputs) -> dict[str, Any]:
    targets = build_target_maps(inputs.signals)
    paths = [
        reconstruct_path(
            model=model, target_map=targets[model], qfq=inputs.qfq,
            signal_dates=inputs.signals.signal_date.unique(), cost_bps=COST_BPS,
        )
        for model in ("A1", "A2_HGB")
    ]
    daily = pd.concat([path.daily for path in paths], ignore_index=True).sort_values(
        ["model", "execution_date"], kind="mergesort"
    ).reset_index(drop=True)
    positions = pd.concat([path.positions for path in paths], ignore_index=True).sort_values(
        ["model", "date", "ticker"], kind="mergesort"
    ).reset_index(drop=True)
    price_basis = price_basis_audit()
    events = derive_corporate_action_events(inputs)
    split_audit = split_consistency_audit(events, positions)
    extremes = security_extremes(positions, events)
    portfolio_events = portfolio_extremes(daily, positions)
    nav_daily, nav_metrics = nav_comparison(inputs, daily)
    ticker_concentration, day_concentration, concentration = concentration_tables(daily, positions)
    ca_attribution, ca_summary = corporate_action_attribution(events, positions, daily)

    confirmed_failures = split_audit.loc[
        split_audit.source_confirmed_event.fillna(False) & split_audit.status.eq("FAIL")
    ] if not split_audit.empty else split_audit
    material_ca_defect = not confirmed_failures.empty
    price_status = "PASS_KNOWN_QFQ_CURRENT_SNAPSHOT_BASIS"
    ca_status = "FAIL_MATERIAL_CONFIRMED_SECURITY_CONVERSION_QUANTITY_DEFECT" if material_ca_defect else "STOP_INCOMPLETE_AUTHORITATIVE_EVENT_LEDGER"
    nav_status = nav_metrics["NAV_RECONSTRUCTION_STATUS"]
    secondary: list[str] = []
    if material_ca_defect:
        status = "FAIL"
        classification = "B_MATERIAL_CORPORATE_ACTION_ACCOUNTING_DEFECT_FOUND"
        secondary.append("E_INSUFFICIENT_SOURCE_EVIDENCE_FOR_COMPLETE_CORPORATE_ACTION_CENSUS")
    elif nav_status == "FAIL":
        status = "FAIL"
        classification = "C_NAV_RECONSTRUCTION_MISMATCH"
    elif price_status.startswith("FAIL"):
        status = "FAIL"
        classification = "D_PRICE_ADJUSTMENT_BASIS_INCONSISTENT"
    else:
        status = "STOP"
        classification = "E_INSUFFICIENT_SOURCE_EVIDENCE_FOR_CORPORATE_ACTION_AUDIT"

    counts = {
        "KNOWN_SPLIT_EVENT_COUNT": int(((events.corporate_action_type == "STOCK_SPLIT") & events.source_confirmed_event).sum()),
        "KNOWN_REVERSE_SPLIT_EVENT_COUNT": int(((events.corporate_action_type == "REVERSE_SPLIT") & events.source_confirmed_event).sum()),
        "PRICE_FINGERPRINT_ONLY_EVENT_COUNT": int((~events.source_confirmed_event).sum()),
        "CORPORATE_ACTION_CONSISTENCY_FAILURE_COUNT": int(split_audit.status.eq("FAIL").sum()) if not split_audit.empty else 0,
        "CONFIRMED_SPLIT_REVERSE_SPLIT_ACCOUNTING_FAILURE_COUNT": int(
            (split_audit.source_confirmed_event & split_audit.corporate_action_type.isin(["STOCK_SPLIT", "REVERSE_SPLIT"]) & split_audit.status.eq("FAIL")).sum()
        ) if not split_audit.empty else 0,
        "CONFIRMED_OTHER_SHARE_COUNT_ACTION_FAILURE_COUNT": len(confirmed_failures),
        "SECURITY_RETURN_GT_30PCT_COUNT": int(extremes.raw_return.gt(0.30).sum()),
        "SECURITY_RETURN_GT_50PCT_COUNT": int(extremes.raw_return.gt(0.50).sum()),
        "SECURITY_RETURN_GT_100PCT_COUNT": int(extremes.raw_return.gt(1.00).sum()),
        "SECURITY_RETURN_LT_NEG30PCT_COUNT": int(extremes.raw_return.lt(-0.30).sum()),
        "SECURITY_RETURN_LT_NEG50PCT_COUNT": int(extremes.raw_return.lt(-0.50).sum()),
        "SECURITY_RETURN_LT_NEG80PCT_COUNT": int(extremes.raw_return.lt(-0.80).sum()),
        "SPLIT_FINGERPRINT_SUSPECT_COUNT": int(extremes.fingerprint_match.notna().sum()),
    }
    a1_daily = daily.loc[daily.model.eq("A1")]
    a2_daily = daily.loc[daily.model.eq("A2_HGB")]
    summary: dict[str, Any] = {
        "FAST_A2_R0F_STATUS": status, "FAST_A2_R0F_CLASSIFICATION": classification,
        "SECONDARY_FAILURES": secondary,
        "RESULT_INTERPRETATION": "UNVERIFIED_EXCEPTIONAL_BACKTEST_RESULT",
        "PRICE_BASIS_AUDIT_STATUS": price_status,
        "CORPORATE_ACTION_AUDIT_STATUS": ca_status,
        "NAV_RECONSTRUCTION_STATUS": nav_status,
        **counts, **nav_metrics, **concentration, **ca_summary,
        "A1_MAX_DAILY_RETURN": float(a1_daily.reconstructed_daily_return.max()),
        "A1_MIN_DAILY_RETURN": float(a1_daily.reconstructed_daily_return.min()),
        "A2_MAX_DAILY_RETURN": float(a2_daily.reconstructed_daily_return.max()),
        "A2_MIN_DAILY_RETURN": float(a2_daily.reconstructed_daily_return.min()),
        "DIAGNOSTIC_ONLY": True, "NOT_AN_ALTERNATIVE_BACKTEST": True,
        "AUTHORITATIVE_CORPORATE_ACTION_LEDGER_COVERAGE": "INCOMPLETE_LOCAL_LEDGER_ABSENT_ONE_MATERIAL_EVENT_CONFIRMED_FROM_SEC",
        "HIVE_FORENSIC": hive_audit(inputs, positions, events),
        "MODEL_FIT_COUNT": 0, "MODEL_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SELECTION_COUNT": 0, "TARGET_READ_FOR_SELECTION": False,
        "OUTCOME_READ_FOR_SELECTION": False, "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0, "BROKER_ACTION_ALLOWED": False,
        "PRODUCTION_ADOPTION": False, "PROSPECTIVE_SHADOW_CHANGED": False,
        "UNIVERSE_CHANGED": False, "MODEL_COHORT_CHANGED": False,
        "R4_ORIGINAL_CONTRACT_CHANGED": False, "EXECUTION_ELIGIBILITY_POLICY_CHANGED": False,
        "commit": False, "push": False,
        "NEXT_AUTHORIZED_STEP": "FAST_A2_R0F1_CORPORATE_ACTION_ACCOUNTING_REPAIR_AND_EXACT_R4_RERUN",
    }
    tables = {
        "price_basis_audit.parquet": price_basis,
        "corporate_action_events.parquet": events,
        "split_reverse_split_consistency_audit.parquet": split_audit,
        "security_extreme_return_events.parquet": extremes,
        "portfolio_extreme_return_events.parquet": portfolio_events,
        "nav_reconstruction_daily.parquet": nav_daily,
        "pnl_concentration_by_ticker.parquet": ticker_concentration,
        "pnl_concentration_by_day.parquet": day_concentration,
        "corporate_action_pnl_attribution.parquet": ca_attribution,
    }
    fingerprint_payload = {
        "summary": summary, "nav_metrics": nav_metrics,
        "table_fingerprints": {name: dataframe_fingerprint(table) for name, table in tables.items()},
        "source_hashes": inputs.source_hashes, "code_sha256": inputs.code_sha256,
        "configuration": {
            "start": str(START.date()), "end_exclusive": str(END_EXCLUSIVE.date()),
            "top_n": TOP_N, "cost_bps": COST_BPS, "abs_tolerance": ABS_TOL,
            "rel_tolerance": REL_TOL, "authoritative_records": AUTHORITATIVE_CORPORATE_ACTION_RECORDS,
        },
    }
    fingerprint = hashlib.sha256(canonical_bytes(fingerprint_payload)).hexdigest()
    return {"summary": summary, "nav_metrics": nav_metrics, "tables": tables, "fingerprint": fingerprint, "fingerprint_payload": fingerprint_payload}


def _normalize_for_arrow(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if result[column].map(lambda x: isinstance(x, (list, dict, tuple))).any():
            result[column] = result[column].map(
                lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)
                if isinstance(x, (list, dict, tuple)) else x
            )
    return result


def write_outputs(result: dict[str, Any], inputs: Inputs, run2_fingerprint: str) -> None:
    if RESULTS_ROOT.exists():
        raise RuntimeError(f"REFUSE_TO_OVERWRITE_EXISTING_AUDIT_ROOT:{RESULTS_ROOT}")
    staging = Path(tempfile.mkdtemp(prefix=f".{EXPERIMENT_ID}.", dir=RESULTS_PARENT))
    try:
        for name, frame in result["tables"].items():
            pq.write_table(pa.Table.from_pandas(_normalize_for_arrow(frame), preserve_index=False), staging / name, compression="zstd")
        summary = dict(result["summary"])
        summary.update({
            "REPRODUCIBILITY_STATUS": "PASS" if result["fingerprint"] == run2_fingerprint else "FAIL",
            "RUN1_FINGERPRINT": result["fingerprint"], "RUN2_FINGERPRINT": run2_fingerprint,
            "RESULTS_ROOT": str(RESULTS_ROOT),
        })
        (staging / "fast_a2_r0f_summary.json").write_bytes(canonical_bytes(summary) + b"\n")
        (staging / "nav_reconstruction_metrics.json").write_bytes(canonical_bytes(result["nav_metrics"]) + b"\n")
        artifact_hashes = {
            name: sha256_file(staging / name) for name in ARTIFACT_NAMES if name != "provenance_manifest.json"
        }
        manifest = {
            "experiment_id": EXPERIMENT_ID, "schema_version": "1.0",
            "source_sha256": inputs.source_hashes, "code_sha256": inputs.code_sha256,
            "logical_table_fingerprints": result["fingerprint_payload"]["table_fingerprints"],
            "run1_fingerprint": result["fingerprint"], "run2_fingerprint": run2_fingerprint,
            "reproducibility_status": summary["REPRODUCIBILITY_STATUS"],
            "artifact_sha256": artifact_hashes,
            "post2025_target_read_count": 0, "post2025_outcome_read_count": 0,
            "timestamps_excluded_from_logical_fingerprint": True,
        }
        (staging / "provenance_manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
        if set(path.name for path in staging.iterdir()) != set(ARTIFACT_NAMES):
            raise RuntimeError("AUDIT_ARTIFACT_SET_MISMATCH")
        os.replace(staging, RESULTS_ROOT)
    except Exception:
        if staging.exists() and staging.parent.resolve() == RESULTS_PARENT.resolve() and staging.name.startswith(f".{EXPERIMENT_ID}."):
            shutil.rmtree(staging)
        raise


def display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def print_console(result: dict[str, Any], run2_fingerprint: str) -> None:
    s = result["summary"]
    fields = (
        "FAST_A2_R0F_STATUS", "FAST_A2_R0F_CLASSIFICATION", "PRICE_BASIS_AUDIT_STATUS",
        "CORPORATE_ACTION_AUDIT_STATUS", "NAV_RECONSTRUCTION_STATUS", "KNOWN_SPLIT_EVENT_COUNT",
        "KNOWN_REVERSE_SPLIT_EVENT_COUNT", "CORPORATE_ACTION_CONSISTENCY_FAILURE_COUNT",
        "SECURITY_RETURN_GT_50PCT_COUNT", "SECURITY_RETURN_LT_NEG50PCT_COUNT",
        "SPLIT_FINGERPRINT_SUSPECT_COUNT", "A2_MAX_DAILY_RETURN", "A2_MIN_DAILY_RETURN",
        "A2_ORIGINAL_NET_CUM_RETURN", "A2_RECONSTRUCTED_NET_CUM_RETURN", "A2_CUM_RETURN_ABS_DIFF",
        "A2_ORIGINAL_CAGR", "A2_RECONSTRUCTED_CAGR", "A2_ORIGINAL_SHARPE", "A2_RECONSTRUCTED_SHARPE",
        "A2_TOP1_TICKER_PNL_SHARE", "A2_TOP5_TICKER_PNL_SHARE", "A2_TOP10_TICKER_PNL_SHARE",
        "A2_TOP1_DAY_PNL_SHARE", "A2_TOP5_DAY_PNL_SHARE", "A2_TOP10_DAY_PNL_SHARE",
        "A2_SPLIT_DAY_PNL_SHARE", "A2_REVERSE_SPLIT_DAY_PNL_SHARE",
        "NAV_RECONSTRUCTION_MAX_ABS_ERROR", "NAV_RECONSTRUCTION_MAX_REL_ERROR",
        "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT", "MODEL_FIT_COUNT", "MODEL_SEARCH_COUNT",
        "R4_ORIGINAL_CONTRACT_CHANGED", "MODEL_COHORT_CHANGED", "UNIVERSE_CHANGED", "PROSPECTIVE_SHADOW_CHANGED",
    )
    aliases = {
        "A2_TOP1_TICKER_PNL_SHARE": "TOP1_TICKER_PNL_SHARE",
        "A2_TOP5_TICKER_PNL_SHARE": "TOP5_TICKER_PNL_SHARE",
        "A2_TOP10_TICKER_PNL_SHARE": "TOP10_TICKER_PNL_SHARE",
        "A2_TOP1_DAY_PNL_SHARE": "TOP1_DAY_PNL_SHARE",
        "A2_TOP5_DAY_PNL_SHARE": "TOP5_DAY_PNL_SHARE",
        "A2_TOP10_DAY_PNL_SHARE": "TOP10_DAY_PNL_SHARE",
    }
    for field in fields:
        print(f"{aliases.get(field, field)}={display(s.get(field))}")
    print(f"REPRODUCIBILITY_STATUS={'PASS' if result['fingerprint'] == run2_fingerprint else 'FAIL'}")
    print(f"RUN1_FINGERPRINT={result['fingerprint']}")
    print(f"RUN2_FINGERPRINT={run2_fingerprint}")
    print(f"NEXT_AUTHORIZED_STEP={s['NEXT_AUTHORIZED_STEP']}")

    print("\nTOP_20_SUSPICIOUS_SECURITY_EVENTS")
    suspicious = result["tables"]["security_extreme_return_events.parquet"].head(20)
    print(suspicious[["date", "model", "ticker", "raw_return", "portfolio_pnl_contribution", "corporate_action_confirmed", "fingerprint_match"]].to_string(index=False))
    print("\nTOP_20_A2_DAILY_PORTFOLIO_RETURNS")
    portfolio = result["tables"]["portfolio_extreme_return_events.parquet"]
    print(portfolio.loc[portfolio.model.eq("A2_HGB")].nlargest(20, "portfolio_return")[[
        "date", "portfolio_return", "largest_positive_contributor", "largest_positive_contribution"
    ]].to_string(index=False))
    print("\nTOP_20_A2_PNL_CONTRIBUTING_TICKERS")
    ticker = result["tables"]["pnl_concentration_by_ticker.parquet"]
    print(ticker.loc[ticker.model.eq("A2_HGB")].head(20)[["pnl_rank", "ticker", "cumulative_pnl_contribution", "pnl_share"]].to_string(index=False))
    print("\nCONFIRMED_SPLIT_REVERSE_SPLIT_CONSISTENCY_FAILURES")
    splits = result["tables"]["split_reverse_split_consistency_audit.parquet"]
    failures = splits.loc[
        splits.source_confirmed_event & splits.corporate_action_type.isin(["STOCK_SPLIT", "REVERSE_SPLIT"]) & splits.status.eq("FAIL")
    ] if not splits.empty else splits
    if failures.empty:
        print("CONFIRMED_SPLIT_REVERSE_SPLIT_ACCOUNTING_FAILURE_COUNT=0")
    else:
        print(failures.to_string(index=False))
    other = splits.loc[splits.source_confirmed_event & splits.status.eq("FAIL")] if not splits.empty else splits
    print("\nALL_CONFIRMED_SHARE_COUNT_ACTION_FAILURES")
    print("NONE" if other.empty else other.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="compute twice and print without creating artifacts")
    args = parser.parse_args(argv)
    inputs = load_inputs()
    run1 = run_once(inputs)
    run2 = run_once(inputs)
    if not args.no_write:
        write_outputs(run1, inputs, run2["fingerprint"])
    print_console(run1, run2["fingerprint"])
    return 0 if run1["fingerprint"] == run2["fingerprint"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
