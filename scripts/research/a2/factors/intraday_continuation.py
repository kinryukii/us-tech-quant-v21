"""Thin conditional intraday-bar characteristic and one-session arithmetic.

No market data readers, model fitting, ranking, portfolio history or simulation.
The fixed panel retains every original key. compute_values=False inspects only
availability, never computes a price ratio, logarithm, score or target return.
Identity/PIT/session qualification is external evidence, not inferred from ticker.
Source-only AST extraction reuses the SHA-pinned MAIN R4 cash/fee definition;
the archived R4 used by old R5 is a different file and lacks this helper.
"""
from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.research.a2.factors.lottery_max_features import _session_index


R4_SOURCE = Path("D:/us-tech-quant/scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py")
R4_SOURCE_SHA256 = "578284ce5563e584eea7b10e9e90b5bcaa35dc5f97c3899441b4bba0ca5237bb"
VALUE_COLUMNS = ("intraday_continuation_score", "next_session_gross_return")
QUALIFICATION_COLUMNS = ("source_qualification", "identity_qualification", "pit_qualification")


def build_intraday_continuation(rawprices: pd.DataFrame, market_calendar: pd.DatetimeIndex,
                                panel: pd.DataFrame, *, compute_values: bool = False) -> pd.DataFrame:
    """Previous COMPLETE calendar month's fixed positive intraday continuation.

    rawprices: ticker,trade_date,open,close, one raw regular-session bar per key.
    panel: exact unique signal_date,ticker keys; optional qualification strings
    are carried verbatim as assertions, never authenticated here. No key is dropped
    or replaced. Signal t uses the calendar month preceding the month of e(t),
    the NEXT canonical market session. Score=sum(log(C)-log(O)), transformed with
    expm1; target is C/O-1 on e(t). Neither includes overnight distributions.

    Full support requires every scheduled session of the measurement month to
    have finite positive O/C; feature availability also needs a current close.
    The first calendar month
    is conservatively boundary-incomplete: calendar must include prior-month
    context to certify the measurement month's beginning. A missing future close
    invalidates the target only; it never changes a prior-close signal score.
    full_support/feature_available concern bar coverage, not economic identity,
    historical publication-PIT, auction execution or survivor completeness.
    """
    if not isinstance(compute_values, (bool, np.bool_)):
        raise ValueError("compute_values must be an explicit bool")
    calendar = _session_index(market_calendar, "market_calendar")
    if len(calendar) < 2:
        raise ValueError("market_calendar requires at least two sessions")
    required = {"ticker", "trade_date", "open", "close"}
    if not required.issubset(rawprices.columns):
        raise ValueError("rawprices require ticker/trade_date/open/close")
    if not {"signal_date", "ticker"}.issubset(panel.columns):
        raise ValueError("panel requires signal_date/ticker")
    frame = rawprices[["ticker", "trade_date", "open", "close"]].copy()
    fixed = panel[["signal_date", "ticker", *[c for c in QUALIFICATION_COLUMNS if c in panel]]].copy()
    for data, date_column in ((frame, "trade_date"), (fixed, "signal_date")):
        data[date_column] = pd.to_datetime(data[date_column], errors="raise")
        if not data[date_column].isin(calendar).all():
            raise ValueError(f"{date_column} outside canonical calendar")
        if data.ticker.isna().any() or data.ticker.astype(str).str.strip().eq("").any():
            raise ValueError("ticker identity required")
        data["ticker"] = data.ticker.astype(str)
        if data.duplicated([date_column, "ticker"]).any():
            raise ValueError(f"duplicate {date_column}/ticker")
    for name in ("open", "close"):
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
    fixed = fixed.reset_index(drop=True)
    fixed["_original_order"] = np.arange(len(fixed))
    for name in QUALIFICATION_COLUMNS:
        if name not in fixed:
            fixed[name] = "UNREVIEWED_NOT_CERTIFIED"
    if fixed.empty:
        return fixed.drop(columns="_original_order").assign(**{c: np.nan for c in VALUE_COLUMNS})

    period = calendar.to_period("M")
    schedule = pd.DataFrame({"session": calendar, "period": period})
    expected = schedule.groupby("period", sort=True).agg(
        expected_session_count=("session", "size"), measurement_start=("session", "min"),
        measurement_end=("session", "max"))
    next_session_map = pd.Series(calendar, index=calendar).shift(-1)
    output = []
    for ticker, keys in fixed.groupby("ticker", sort=False):
        keys = keys.copy()
        history = frame.loc[frame.ticker.eq(ticker)].set_index("trade_date").reindex(calendar)
        valid_open = np.isfinite(history.open) & history.open.gt(0)
        valid_close = np.isfinite(history.close) & history.close.gt(0)
        valid_bar = valid_open & valid_close
        observed = valid_bar.astype(np.int64).groupby(period, sort=True).sum()
        signals = pd.DatetimeIndex(keys.signal_date)
        following = next_session_map.reindex(signals)
        measurement_month = following.dt.to_period("M") - 1
        month_index = pd.PeriodIndex(measurement_month, freq="M")
        meta = expected.reindex(month_index).reset_index(drop=True)
        meta.index = keys.index
        keys["next_market_session"] = following.to_numpy()
        keys["next_session_known"] = following.notna().to_numpy()
        keys["measurement_month"] = measurement_month.astype("string").to_numpy()
        keys["measurement_start"] = meta.measurement_start
        keys["measurement_end"] = meta.measurement_end
        keys["factor_information_end_date"] = meta.measurement_end
        keys["expected_session_count"] = meta.expected_session_count.fillna(0).astype(np.int64)
        keys["observed_session_count"] = observed.reindex(month_index).fillna(0).to_numpy(dtype=np.int64)
        keys["calendar_month_boundary_complete"] = (measurement_month.gt(period.min()) & following.notna()).to_numpy()
        keys["full_support"] = (keys.expected_session_count.gt(0)
                                & keys.observed_session_count.eq(keys.expected_session_count)
                                & keys.calendar_month_boundary_complete
                                & keys.measurement_end.le(keys.signal_date))
        keys["current_close_available"] = valid_close.reindex(signals, fill_value=False).to_numpy()
        keys["feature_available"] = keys.full_support & keys.current_close_available
        future_index = pd.DatetimeIndex(following)
        keys["next_open_available"] = valid_open.reindex(future_index, fill_value=False).fillna(False).to_numpy(dtype=bool)
        keys["next_close_available"] = valid_close.reindex(future_index, fill_value=False).fillna(False).to_numpy(dtype=bool)
        keys["target_available"] = keys.next_session_known & keys.next_open_available & keys.next_close_available
        keys["feature_status"] = np.where(keys.feature_available, "BAR_COVERAGE_COMPLETE", "MEASUREMENT_OR_CURRENT_BAR_INCOMPLETE")
        keys["target_status"] = np.where(keys.target_available, "BAR_COVERAGE_COMPLETE", "NEXT_SESSION_BAR_INCOMPLETE")
        keys["values_computed"] = bool(compute_values)
        keys["intraday_continuation_score"] = np.nan
        keys["next_session_gross_return"] = np.nan
        if compute_values:
            # Mask BEFORE log: invalid observed prices cannot create infinities.
            logs = np.log(history.close.where(valid_bar)) - np.log(history.open.where(valid_bar))
            month_sum = logs.groupby(period, sort=True).sum(min_count=1)
            scores = np.expm1(month_sum.reindex(month_index).to_numpy())
            keys["intraday_continuation_score"] = np.where(keys.feature_available, scores, np.nan)
            targets = (history.close.where(valid_bar) / history.open.where(valid_bar) - 1).reindex(future_index).to_numpy()
            keys["next_session_gross_return"] = np.where(keys.target_available, targets, np.nan)
            for name in VALUE_COLUMNS:
                if np.isinf(keys[name]).any():
                    raise ArithmeticError("nonfinite intraday value")
        if keys.loc[keys.feature_available, "factor_information_end_date"].gt(keys.loc[keys.feature_available, "signal_date"]).any():
            raise ArithmeticError("future information in intraday characteristic")
        output.append(keys)
    out = pd.concat(output, ignore_index=True).sort_values("_original_order", kind="stable").drop(columns="_original_order").reset_index(drop=True)
    if len(out) != len(fixed):
        raise AssertionError("fixed panel cardinality changed")
    return out


@lru_cache(maxsize=1)
def load_pinned_weight_rebalance():
    """Read only source bytes, verify MAIN R4, and compile ONE pure definition.

    Do not import/execute the full R4 module or its readers/module-level code.
    No market or result data is read. The returned definition is the existing
    implementation, not a reimplementation of its cost/long-only logic.
    """
    payload = R4_SOURCE.read_bytes()
    if hashlib.sha256(payload).hexdigest() != R4_SOURCE_SHA256:
        raise RuntimeError("MAIN_R4_SOURCE_HASH_MISMATCH")
    tree = ast.parse(payload.decode("utf-8-sig"), filename=str(R4_SOURCE))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "calculate_weight_rebalance"]
    if len(definitions) != 1 or definitions[0].decorator_list:
        raise RuntimeError("MAIN_R4_PURE_DEFINITION_NOT_UNIQUE")
    namespace = {"np": np, "Any": Any}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(R4_SOURCE), "exec"), namespace)
    return namespace["calculate_weight_rebalance"]


def one_session_group_return(gross_returns: pd.Series, *, cost_bps: int = 10) -> dict[str, Any]:
    """One fixed 20-name long-only group, flat -> equal buys -> same-close flat.

    gross_returns: exactly 20 unique ticker-indexed arithmetic C/O-1 observations.
    This is a conditional bar-price fee scenario, not actual fills. NaN/nonfinite
    values leave the group unavailable; no name is dropped. Allowed costs are
    frozen 10-bps primary and 20-bps stress on HALF gross traded notional.
    Every call starts from cash and charges both legs, even for unchanged names.
    """
    if isinstance(cost_bps, bool) or cost_bps not in (10, 20):
        raise ValueError("only preregistered 10 primary / 20 stress cost allowed")
    if not isinstance(gross_returns, pd.Series) or len(gross_returns) != 20:
        raise ValueError("group requires exactly 20 ticker-indexed returns")
    names = pd.Index(gross_returns.index.map(str)).str.upper()
    if gross_returns.index.isna().any() or names.has_duplicates or any(not name.strip() for name in names):
        raise ValueError("20 unique nonempty ticker identities required")
    values = pd.to_numeric(gross_returns, errors="raise").to_numpy(dtype=float)
    out = {"status": "UNAVAILABLE_GROUP_BAR", "name_count": 20, "cost_bps_half_notional": cost_bps,
           "gross_bar_return": np.nan, "bar_return_cost_scenario": np.nan,
           "entry_cost_initial_capital": np.nan, "exit_cost_initial_capital": np.nan,
           "total_cost_initial_capital": np.nan, "buy_scale": np.nan,
           "closing_pretrade_nav": np.nan, "ending_cash": np.nan,
           "entry_cash_after": np.nan, "ending_stock_exposure": np.nan,
           "main_r4_source_sha256": R4_SOURCE_SHA256}
    if not np.isfinite(values).all() or (values <= -1).any():
        return out
    rebalance = load_pinned_weight_rebalance()
    targets = {ticker: 1.0 / 20 for ticker in names}
    entry = rebalance({}, targets, cost_bps=cost_bps)
    entry_values = np.full(20, entry["buy_scale"] / 20)
    close_values = entry_values * (1 + values)
    cash = entry["cash_after_fraction"]
    closing_nav = float(close_values.sum() + cash)
    close_weights = {ticker: float(value / closing_nav) for ticker, value in zip(names, close_values)}
    exit_ = rebalance(close_weights, {}, cost_bps=cost_bps)
    exit_fee = closing_nav * exit_["transaction_cost_fraction"]
    ending_cash = closing_nav * exit_["cash_after_fraction"]
    net = ending_cash - 1
    c = .5 * cost_bps / 10000
    closed_form = (1 - c) / (1 + c) * float(np.mean(1 + values)) - 1
    if not np.isclose(net, closed_form, rtol=1e-12, atol=1e-12):
        raise AssertionError("R4_DOUBLE_LEG_VS_CLOSED_FORM_MISMATCH")
    if cash < -1e-12 or not 0 <= entry["buy_scale"] <= 1 + 1e-12 or ending_cash < 0:
        raise AssertionError("INTRADAY_IMPLICIT_LEVERAGE")
    out.update(status="CONDITIONAL_BAR_FEE_SCENARIO", gross_bar_return=float(np.mean(values)),
               bar_return_cost_scenario=net, entry_cost_initial_capital=entry["transaction_cost_fraction"],
               exit_cost_initial_capital=exit_fee,
               total_cost_initial_capital=entry["transaction_cost_fraction"] + exit_fee,
               buy_scale=entry["buy_scale"], closing_pretrade_nav=closing_nav,
               ending_cash=ending_cash, entry_cash_after=cash, ending_stock_exposure=0.0)
    return out
