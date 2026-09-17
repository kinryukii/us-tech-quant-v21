"""One-time fixed Raw-score probability attenuation application diagnostic."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


TASK_NAME = "A2_RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION_R1"
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_NAME
PRIOR = RESULTS / "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1"
PREDICTIONS = PRIOR / "oos_predictions.parquet"
PRIOR_SUMMARY = PRIOR / "oos_summary.csv"
ANTECEDENT = RESULTS / "A2_RIGHT_TAIL_EVENT_ANTECEDENT_DIAGNOSTIC_R1" / "event_feature_detail.parquet"
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
FREEZE = BASELINE / "audit" / "freeze_r1"
ENGINE = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
EXPECTED_PREDICTIONS_SHA256 = "2e01f050f906b7f0ee1f9db6e9418b0e065c35a2cd12510c22b427761d7fa899"
EXPECTED_PRIOR_SUMMARY_SHA256 = "0d6f4bb19e1b32866479487e8bd99e2d54c5b27f14dcde2a68edf7f5caa852b8"
EXPECTED_ANTECEDENT_SHA256 = "388a25b0abfb5fb76b0e911cbda360dab1cbe3f0040818d3c2c04bf3074cfec9"
EXPECTED_EVENT_COUNT = 625
EXPECTED_TAIL_COUNT = 67
EXPECTED_AUROC = 0.635906489060076
EXPECTED_AP_OVER_BASE = 1.482488951092566
MAX_OUTCOME_DATE = pd.Timestamp("2025-12-31")
PRE2025_EXCLUSIVE = pd.Timestamp("2025-01-01")
COST_BPS = 10
TOL = 1e-12


class DiagnosticFailure(RuntimeError):
    """A fail-closed identity, temporal, or economic application failure."""


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise DiagnosticFailure(f"{code}:{evidence}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "CANONICAL_ENGINE_IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def text_value(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value)).lower()
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return "NA"
        return f"{float(value):.17g}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return str(value)


def display(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        return "NA" if not math.isfinite(float(value)) else f"{float(value):.10f}"
    return text_value(value)


def summary_row(
    section: str, metric: str, scope: str, value: Any, notes: str = "",
) -> dict[str, str]:
    return {
        "section": section,
        "metric": metric,
        "scope": scope,
        "value": text_value(value),
        "notes": notes,
    }


def prior_value(frame: pd.DataFrame, section: str, metric: str, scope: str | None = None) -> str:
    rows = frame.loc[frame.section.eq(section) & frame.metric.eq(metric)]
    if scope is not None:
        rows = rows.loc[rows.scope.eq(scope)]
    require(len(rows) == 1, "PRIOR_SUMMARY_LOOKUP_FAILURE", f"{section}:{metric}:{scope}:{len(rows)}")
    return str(rows.iloc[0].value)


def verify_frozen_paths(paths: list[Path]) -> dict[str, str]:
    verification = json.loads((FREEZE / "freeze_verification.json").read_text(encoding="utf-8"))
    manifest = json.loads((FREEZE / "frozen_baseline_manifest.json").read_text(encoding="utf-8"))
    require(verification["status"] == "PASS", "FROZEN_BASELINE_VERIFICATION_NOT_PASS")
    require(verification["frozen_inputs_modified"] is False, "FROZEN_INPUT_MODIFIED_FLAG")
    require(verification["referenced_artifact_hash_mismatch_count"] == 0, "FROZEN_HASH_MISMATCH_FLAG")
    require(manifest["frozen_baseline_name"] == "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1", "BASELINE_NAME_MISMATCH")
    require(manifest["status"] == "FROZEN_RESEARCH_BASELINE", "BASELINE_STATUS_MISMATCH")
    registry = pd.read_csv(FREEZE / "frozen_artifact_hashes.csv", dtype=str, keep_default_na=False)
    registered = {
        str(Path(row.absolute_path).resolve()).casefold(): str(row.sha256)
        for row in registry.itertuples(index=False)
    }
    identities: dict[str, str] = {}
    for path in paths:
        resolved = path.resolve()
        key = str(resolved).casefold()
        require(key in registered, "FROZEN_ARTIFACT_NOT_REGISTERED", resolved)
        actual = sha256_file(resolved)
        require(actual == registered[key], "FROZEN_ARTIFACT_HASH_MISMATCH", resolved)
        identities[str(resolved)] = actual
    return identities


def load_prior_signal() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, float], list[dict[str, str]]]:
    for path in (PREDICTIONS, PRIOR_SUMMARY, ANTECEDENT):
        require(path.is_file(), "PRIOR_SIGNAL_ARTIFACT_MISSING", path)
    require(sha256_file(PREDICTIONS) == EXPECTED_PREDICTIONS_SHA256, "OOS_PREDICTIONS_HASH_MISMATCH")
    require(sha256_file(PRIOR_SUMMARY) == EXPECTED_PRIOR_SUMMARY_SHA256, "OOS_SUMMARY_HASH_MISMATCH")
    require(sha256_file(ANTECEDENT) == EXPECTED_ANTECEDENT_SHA256, "ANTECEDENT_HASH_MISMATCH")

    predictions = pd.read_parquet(PREDICTIONS)
    summary = pd.read_csv(PRIOR_SUMMARY, dtype=str, keep_default_na=False)
    events = pd.read_parquet(ANTECEDENT)
    date_columns = ("decision_date", "holding_start", "holding_end", "raw_score_available_timestamp")
    for frame in (predictions, events):
        for column in date_columns:
            frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    predictions = predictions.sort_values("decision_date", kind="mergesort").reset_index(drop=True)
    events = events.sort_values("decision_date", kind="mergesort").reset_index(drop=True)

    require(len(predictions) == EXPECTED_EVENT_COUNT, "POOLED_OOS_EVENT_COUNT_MISMATCH", len(predictions))
    require(int(predictions.right_tail.sum()) == EXPECTED_TAIL_COUNT, "POOLED_RIGHT_TAIL_COUNT_MISMATCH")
    require(predictions.decision_date.is_unique, "OOS_DECISION_DATE_DUPLICATE")
    require(predictions.outer_fold.nunique() == 5, "OUTER_FOLD_COUNT_MISMATCH")
    require(predictions.groupby("outer_fold").size().eq(125).all(), "OUTER_FOLD_SIZE_MISMATCH")
    require(predictions.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_USED")
    require((predictions.raw_score_available_timestamp <= predictions.decision_date).all(), "OOS_PREDICTOR_TEMPORAL_FAILURE")
    require(prior_value(summary, "CLASSIFICATION", "PROBABILITY_SIGNAL_CLASSIFICATION") == "SUPPORTED", "PRIOR_PROBABILITY_STATUS_MISMATCH")
    require(prior_value(summary, "CLASSIFICATION", "PAYOFF_SIGNAL_CLASSIFICATION") == "NOT_SUPPORTED", "PRIOR_PAYOFF_STATUS_MISMATCH")

    y = predictions.right_tail.to_numpy(int)
    probability = predictions.predicted_right_tail_probability.to_numpy(float)
    auroc = float(roc_auc_score(y, probability))
    ap_over_base = float(average_precision_score(y, probability) / y.mean())
    require(abs(auroc - EXPECTED_AUROC) <= 1e-14, "PRIOR_AUROC_MISMATCH", auroc)
    require(abs(ap_over_base - EXPECTED_AP_OVER_BASE) <= 1e-14, "PRIOR_AP_OVER_BASE_MISMATCH", ap_over_base)

    a2_daily = pd.read_parquet(BASELINE / "A2" / "portfolio_daily.parquet", columns=["execution_date", "pretrade_nav"])
    a2_daily["holding_start"] = pd.to_datetime(a2_daily.execution_date).dt.normalize()
    events = events.merge(a2_daily[["holding_start", "pretrade_nav"]], on="holding_start", how="left", validate="one_to_one")
    require(events.pretrade_nav.notna().all() and events.pretrade_nav.gt(0).all(), "FULL_EVENT_PRETRADE_NAV_MISSING")
    events["event_active_return"] = events.event_incremental_wealth.astype(float) / events.pretrade_nav.astype(float)
    require(len(events) == 750 and events.decision_date.is_unique, "FULL_EVENT_IDENTITY_FAILURE")

    joined = predictions.merge(
        events[["decision_date", "holding_start", "holding_end", "event_incremental_wealth", "raw_score", "event_active_return"]],
        on=["decision_date", "holding_start", "holding_end"], how="left", suffixes=("", "_full"), validate="one_to_one",
    )
    for column in ("event_incremental_wealth", "raw_score", "event_active_return"):
        error = float(np.max(np.abs(joined[column].to_numpy(float) - joined[f"{column}_full"].to_numpy(float))))
        require(error <= TOL, "PRIOR_EVENT_MAPPING_MISMATCH", f"{column}:{error}")

    base_rates: dict[str, float] = {}
    fold_rows: list[dict[str, str]] = []
    for fold, group in predictions.groupby("outer_fold", sort=True):
        metadata = group.iloc[0]
        for column in (
            "train_q90", "train_count_before_purge", "train_count_after_purge", "purged_event_count",
            "train_max_decision_date", "train_max_holding_end", "test_min_decision_date", "test_min_holding_start",
        ):
            require(group[column].nunique() == 1, "FOLD_METADATA_NOT_CONSTANT", f"{fold}:{column}")
        train_before = events.loc[events.decision_date.lt(metadata.test_min_decision_date)]
        train = train_before.loc[train_before.holding_end.lt(metadata.test_min_holding_start)]
        require(len(train_before) == int(metadata.train_count_before_purge), "TRAIN_BEFORE_PURGE_COUNT_MISMATCH", fold)
        require(len(train) == int(metadata.train_count_after_purge), "TRAIN_AFTER_PURGE_COUNT_MISMATCH", fold)
        require(len(train_before) - len(train) == int(metadata.purged_event_count), "PURGED_EVENT_COUNT_MISMATCH", fold)
        require(train.decision_date.max() == metadata.train_max_decision_date, "TRAIN_MAX_DECISION_DATE_MISMATCH", fold)
        require(train.holding_end.max() == metadata.train_max_holding_end, "TRAIN_MAX_HOLDING_END_MISMATCH", fold)
        train_label = train.event_active_return.gt(float(metadata.train_q90))
        base_rate = float(train_label.mean())
        require(0 < base_rate < 1, "TRAIN_BASE_RATE_INVALID", f"{fold}:{base_rate}")
        base_rates[str(fold)] = base_rate
        fold_rows.append(summary_row("TRAIN_ONLY_BASE_RATE", "TRAIN_BASE_RATE", str(fold), base_rate, "persisted TRAIN_Q90 applied only to exact purged OUTER TRAIN rows"))

    predictions["train_base_rate"] = predictions.outer_fold.map(base_rates)
    predictions["lambda"] = np.clip(
        predictions.predicted_right_tail_probability.astype(float) / predictions.train_base_rate.astype(float), 0.0, 1.0,
    )
    require(predictions["lambda"].between(0.0, 1.0, inclusive="both").all(), "LAMBDA_BOUND_FAILURE")
    identity = {"auroc": auroc, "ap_over_base": ap_over_base}
    return predictions, summary, events, identity, fold_rows


def target_maps_from_frozen() -> tuple[
    dict[str, dict[pd.Timestamp, dict[str, float]]], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, str],
]:
    paths = [
        BASELINE / arm / name
        for arm in ("A", "A2")
        for name in ("top20_selections.parquet", "portfolio_daily.parquet", "position_ledger.parquet", "trade_ledger.parquet")
    ]
    hashes = verify_frozen_paths(paths)
    selections = {arm: pd.read_parquet(BASELINE / arm / "top20_selections.parquet") for arm in ("A", "A2")}
    daily = {arm: pd.read_parquet(BASELINE / arm / "portfolio_daily.parquet") for arm in ("A", "A2")}
    positions = {arm: pd.read_parquet(BASELINE / arm / "position_ledger.parquet") for arm in ("A", "A2")}
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for arm in ("A", "A2"):
        selections[arm]["signal_date"] = pd.to_datetime(selections[arm].signal_date).dt.normalize()
        daily[arm]["execution_date"] = pd.to_datetime(daily[arm].execution_date).dt.normalize()
        positions[arm]["date"] = pd.to_datetime(positions[arm].date).dt.normalize()
        positions[arm]["previous_date"] = pd.to_datetime(positions[arm].previous_date).dt.normalize()
        require(selections[arm].signal_date.nunique() == 750, "BASELINE_SIGNAL_DATE_COUNT_FAILURE", arm)
        require(selections[arm].groupby("signal_date").size().eq(20).all(), "BASELINE_TOP20_CARDINALITY_FAILURE", arm)
        require(not positions[arm].stale_mark.any(), "BASELINE_STALE_MARK_UNSUPPORTED", arm)
        require(int(daily[arm].skipped_buy_count.sum()) == 0, "BASELINE_SKIPPED_BUY_UNSUPPORTED", arm)
        require(int(daily[arm].blocked_sell_or_rebalance_count.sum()) == 0, "BASELINE_BLOCKED_REBALANCE_UNSUPPORTED", arm)
        targets[arm] = {
            pd.Timestamp(date): {str(ticker): 0.05 for ticker in group.ticker}
            for date, group in selections[arm].groupby("signal_date", sort=True)
        }
    return targets, selections, daily, positions, hashes


def frozen_price_panel(
    selections: dict[str, pd.DataFrame], daily: dict[str, pd.DataFrame], positions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for arm in ("A", "A2"):
        rows.append(positions[arm][["date", "ticker", "current_price"]].rename(columns={"date": "trade_date", "current_price": "open"}))
        prior = positions[arm].loc[
            positions[arm].previous_date.notna() & positions[arm].previous_price.notna(),
            ["previous_date", "ticker", "previous_price"],
        ].rename(columns={"previous_date": "trade_date", "previous_price": "open"})
        rows.append(prior)
    prices = pd.concat(rows, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    price_spread = float(prices.groupby(["trade_date", "ticker"]).open.agg(lambda x: float(x.max() - x.min())).max())
    require(price_spread <= TOL, "FROZEN_LEDGER_PRICE_DISAGREEMENT", price_spread)
    prices = prices.groupby(["trade_date", "ticker"], as_index=False).open.first()
    calendar = pd.DatetimeIndex(sorted(set(pd.concat([
        selections["A"].signal_date, selections["A2"].signal_date, daily["A"].execution_date,
    ]))))
    actual_qqq = prices.loc[prices.ticker.eq("QQQ")].set_index("trade_date").open
    qqq = pd.DataFrame({
        "trade_date": calendar,
        "ticker": "QQQ",
        "open": [float(actual_qqq.get(date, 1.0)) for date in calendar],
    })
    prices = pd.concat([prices.loc[~prices.ticker.eq("QQQ")], qqq], ignore_index=True)
    prices["close"] = prices.open
    require(not prices.duplicated(["trade_date", "ticker"]).any(), "FROZEN_PRICE_PANEL_DUPLICATE")
    return prices


def build_c1_targets(
    base: dict[str, dict[pd.Timestamp, dict[str, float]]], predictions: pd.DataFrame,
) -> tuple[dict[pd.Timestamp, dict[str, float]], dict[str, float]]:
    lambda_by_date = predictions.set_index("decision_date")["lambda"].to_dict()
    c1: dict[pd.Timestamp, dict[str, float]] = {}
    max_sum_error = 0.0
    max_endpoint0_error = 0.0
    max_endpoint1_error = 0.0
    max_active_excess = 0.0
    identical_artificial_count = 0
    for date in sorted(base["A2"]):
        a = base["A"][date]
        a2 = base["A2"][date]
        lam = float(lambda_by_date.get(date, 1.0))
        union = sorted(set(a) | set(a2))
        target = {ticker: a.get(ticker, 0.0) + lam * (a2.get(ticker, 0.0) - a.get(ticker, 0.0)) for ticker in union}
        target = {ticker: weight for ticker, weight in target.items() if weight > TOL}
        c1[date] = target
        max_sum_error = max(max_sum_error, abs(sum(target.values()) - 1.0))
        endpoint0 = {ticker: a.get(ticker, 0.0) for ticker in union}
        endpoint1 = {ticker: a2.get(ticker, 0.0) for ticker in union}
        max_endpoint0_error = max(max_endpoint0_error, max(abs(endpoint0[t] - a.get(t, 0.0)) for t in union))
        max_endpoint1_error = max(max_endpoint1_error, max(abs(endpoint1[t] - a2.get(t, 0.0)) for t in union))
        max_active_excess = max(max_active_excess, max(
            abs(target.get(t, 0.0) - a.get(t, 0.0)) - abs(a2.get(t, 0.0) - a.get(t, 0.0)) for t in union
        ))
        if a == a2 and target != a:
            identical_artificial_count += 1
        require(set(target).issubset(set(union)), "C1_HOLDING_OUTSIDE_A_A2_UNION", date)
        require(all(weight >= -TOL for weight in target.values()), "C1_SHORT_WEIGHT", date)
        require(sum(abs(weight) for weight in target.values()) <= 1.0 + TOL, "C1_LEVERAGE_INCREASE", date)
    facts = {
        "max_target_sum_error": max_sum_error,
        "max_endpoint0_error": max_endpoint0_error,
        "max_endpoint1_error": max_endpoint1_error,
        "max_active_exposure_excess": max_active_excess,
        "identical_target_artificial_count": float(identical_artificial_count),
    }
    require(max_sum_error <= TOL, "C1_TARGET_WEIGHT_SUM_FAILURE", max_sum_error)
    require(max_endpoint0_error <= TOL and max_endpoint1_error <= TOL, "C1_ENDPOINT_IDENTITY_FAILURE")
    require(max_active_excess <= TOL, "C1_ACTIVE_EXPOSURE_AMPLIFICATION", max_active_excess)
    require(identical_artificial_count == 0, "IDENTICAL_A_A2_ARTIFICIAL_EVENT")
    return c1, facts


def replay_and_validate(
    engine: Any, targets: dict[str, dict[pd.Timestamp, dict[str, float]]], c1_targets: dict[pd.Timestamp, dict[str, float]],
    selections: dict[str, pd.DataFrame], frozen_daily: dict[str, pd.DataFrame], prices: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, float]]:
    signal_dates = selections["A"].signal_date.unique()
    paths = {
        "A": engine.reconstruct_path(model="A1", target_map=targets["A"], qfq=prices, signal_dates=signal_dates, cost_bps=COST_BPS),
        "A2": engine.reconstruct_path(model="A2_HGB", target_map=targets["A2"], qfq=prices, signal_dates=signal_dates, cost_bps=COST_BPS),
        "C1": engine.reconstruct_path(model="C1_RAW_SCORE_ATTENUATED_A2", target_map=c1_targets, qfq=prices, signal_dates=signal_dates, cost_bps=COST_BPS),
    }
    identity: dict[str, float] = {}
    compare_columns = (
        "pretrade_nav", "reconstructed_nav", "reconstructed_gross_return", "reconstructed_daily_return",
        "target_turnover", "reconstructed_turnover", "reconstructed_transaction_cost", "cash_before", "cash_after", "position_value",
        "NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR", "POSITION_VALUE_IDENTITY_ERROR",
        "TURNOVER_IDENTITY_ERROR", "TRANSACTION_COST_IDENTITY_ERROR",
    )
    for arm in ("A", "A2"):
        got = paths[arm].daily.sort_values("execution_date", kind="mergesort").reset_index(drop=True)
        frozen = frozen_daily[arm].sort_values("execution_date", kind="mergesort").reset_index(drop=True)
        require(got.execution_date.equals(frozen.execution_date), "BASELINE_REPLAY_DATE_MISMATCH", arm)
        max_error = max(float(np.max(np.abs(got[column].to_numpy(float) - frozen[column].to_numpy(float)))) for column in compare_columns)
        require(max_error <= TOL, "BASELINE_REPLAY_VALUE_MISMATCH", f"{arm}:{max_error}")
        identity[f"{arm.lower()}_daily_max_abs_error"] = max_error
    accounting_columns = [column for column in paths["C1"].daily if column.endswith("IDENTITY_ERROR")]
    c1_accounting_error = max(float(paths["C1"].daily[column].abs().max()) for column in accounting_columns)
    require(c1_accounting_error <= TOL, "C1_ACCOUNTING_IDENTITY_FAILURE", c1_accounting_error)
    identity["c1_accounting_max_abs_error"] = c1_accounting_error
    return paths, identity


def event_contributions(path: Any, a_path: Any, predictions: pd.DataFrame) -> pd.DataFrame:
    market = path.positions.groupby("date").market_pnl.sum()
    a_market = a_path.positions.groupby("date").market_pnl.sum()
    costs = path.daily.set_index("execution_date").reconstructed_transaction_cost
    a_costs = a_path.daily.set_index("execution_date").reconstructed_transaction_cost
    turnover = path.daily.set_index("execution_date").reconstructed_turnover
    a_turnover = a_path.daily.set_index("execution_date").reconstructed_turnover
    last_decision = predictions.decision_date.max()
    rows: list[dict[str, Any]] = []
    for event in predictions.itertuples(index=False):
        gross = float(market.get(event.holding_end, 0.0) - a_market.get(event.holding_end, 0.0))
        incremental_cost = float(costs.loc[event.holding_start] - a_costs.loc[event.holding_start])
        event_turnover = float(turnover.loc[event.holding_start])
        event_a_turnover = float(a_turnover.loc[event.holding_start])
        if event.decision_date == last_decision:
            incremental_cost += float(costs.loc[event.holding_end] - a_costs.loc[event.holding_end])
            event_turnover += float(turnover.loc[event.holding_end])
            event_a_turnover += float(a_turnover.loc[event.holding_end])
        net = gross - incremental_cost
        rows.append({
            "decision_date": event.decision_date,
            "gross_active_wealth": gross,
            "incremental_cost_wealth": incremental_cost,
            "net_active_wealth": net,
            "active_return_common_a2_nav": net / float(event.pretrade_nav),
            "turnover": event_turnover,
            "a_turnover": event_a_turnover,
            "cost": float(costs.loc[event.holding_start]) + (
                float(costs.loc[event.holding_end]) if event.decision_date == last_decision else 0.0
            ),
        })
    return pd.DataFrame(rows)


def performance(frame: pd.DataFrame) -> dict[str, float]:
    ordered = frame.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    terminal = float(np.prod(1.0 + returns))
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    annualized_mean = float(np.mean(returns) * 252.0)
    return {
        "observation_count": float(len(returns)),
        "terminal_wealth": terminal,
        "cumulative_return": terminal - 1.0,
        "cagr": terminal ** (252.0 / len(returns)) - 1.0,
        "annualized_volatility": volatility,
        "sharpe": annualized_mean / volatility if volatility else np.nan,
        "max_drawdown": float(drawdown.min()),
        "turnover": float(ordered.reconstructed_turnover.sum()),
        "transaction_cost": float(ordered.reconstructed_transaction_cost.sum()),
    }


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if abs(denominator) > TOL else np.nan


def mechanism_metrics(frame: pd.DataFrame) -> dict[str, float]:
    tail = frame.loc[frame.right_tail.eq(1)]
    nontail = frame.loc[frame.right_tail.eq(0)]
    a2_tail = float(tail.a2_active_return.sum())
    c1_tail = float(tail.c1_active_return.sum())
    a2_nontail = float(nontail.a2_active_return.sum())
    c1_nontail = float(nontail.c1_active_return.sum())
    return {
        "event_count": float(len(frame)),
        "mean_lambda": float(frame["lambda"].mean()),
        "median_lambda": float(frame["lambda"].median()),
        "a2_active_return": float(frame.a2_active_return.sum()),
        "c1_active_return": float(frame.c1_active_return.sum()),
        "c1_minus_a2_active_return": float((frame.c1_active_return - frame.a2_active_return).sum()),
        "a2_tail_active_contribution": a2_tail,
        "c1_tail_active_contribution": c1_tail,
        "tail_contribution_retention_ratio": safe_ratio(c1_tail, a2_tail),
        "a2_nontail_active_contribution": a2_nontail,
        "c1_nontail_active_contribution": c1_nontail,
        "nontail_drag_reduction": c1_nontail - a2_nontail,
        "net_attenuation_value": (c1_tail + c1_nontail) - (a2_tail + a2_nontail),
        "turnover_difference": float((frame.c1_turnover - frame.a2_turnover).sum()),
        "cost_difference": float((frame.c1_cost - frame.a2_cost).sum()),
    }


def analyze(
    predictions: pd.DataFrame, paths: dict[str, Any], replay_identity: dict[str, float], target_identity: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    a2_events = event_contributions(paths["A2"], paths["A"], predictions)
    c1_events = event_contributions(paths["C1"], paths["A"], predictions)
    joined = predictions.merge(a2_events, on="decision_date", validate="one_to_one", suffixes=("", "_a2_replay"))
    joined = joined.merge(c1_events, on="decision_date", validate="one_to_one", suffixes=("_a2", "_c1"))
    a2_wealth_error = float(np.max(np.abs(joined.net_active_wealth_a2.to_numpy(float) - joined.event_incremental_wealth.to_numpy(float))))
    a2_return_error = float(np.max(np.abs(joined.active_return_common_a2_nav_a2.to_numpy(float) - joined.event_active_return.to_numpy(float))))
    require(a2_wealth_error <= TOL, "A2_EVENT_WEALTH_REPLAY_IDENTITY_FAILURE", a2_wealth_error)
    require(a2_return_error <= TOL, "A2_EVENT_ACTIVE_RETURN_REPLAY_IDENTITY_FAILURE", a2_return_error)
    joined = joined.rename(columns={
        "active_return_common_a2_nav_a2": "a2_active_return",
        "active_return_common_a2_nav_c1": "c1_active_return",
        "turnover_a2": "a2_turnover", "turnover_c1": "c1_turnover",
        "cost_a2": "a2_cost", "cost_c1": "c1_cost",
    })
    joined["attenuation_effect"] = joined.c1_active_return - joined.a2_active_return

    first_active = predictions.holding_start.min()
    last_outcome = predictions.holding_end.max()
    window = {
        arm: path.daily.loc[path.daily.execution_date.between(first_active, last_outcome)].copy()
        for arm, path in paths.items()
    }
    require(len({len(frame) for frame in window.values()}) == 1, "COMMON_APPLICATION_WINDOW_LENGTH_MISMATCH")
    portfolio = {arm: performance(frame) for arm, frame in window.items()}
    before = paths["C1"].daily.execution_date.lt(first_active)
    pre_oos_c1_a2_error = float(np.max(np.abs(
        paths["C1"].daily.loc[before, "reconstructed_nav"].to_numpy(float)
        - paths["A2"].daily.loc[before, "reconstructed_nav"].to_numpy(float)
    )))
    require(pre_oos_c1_a2_error <= TOL, "PRE_OOS_C1_INITIALIZATION_MISMATCH", pre_oos_c1_a2_error)

    pooled = mechanism_metrics(joined)
    folds = {str(fold): mechanism_metrics(group) for fold, group in joined.groupby("outer_fold", sort=True)}
    pre = joined.loc[joined.holding_end.lt(PRE2025_EXCLUSIVE)].copy()
    require(len(pre) > 0 and pre.holding_end.max() < PRE2025_EXCLUSIVE, "PRE2025_OUTCOME_FIREWALL_FAILURE")
    pre_metrics = mechanism_metrics(pre)
    years = {str(int(year)): mechanism_metrics(group) for year, group in joined.groupby(joined.holding_end.dt.year, sort=True)}

    positive_folds = sum(values["c1_minus_a2_active_return"] > TOL for values in folds.values())
    negative_folds = sum(values["c1_minus_a2_active_return"] < -TOL for values in folds.values())
    positive_nontail_folds = sum(values["nontail_drag_reduction"] > TOL for values in folds.values())
    positive_years = sum(values["c1_minus_a2_active_return"] > TOL for values in years.values())
    negative_years = sum(values["c1_minus_a2_active_return"] < -TOL for values in years.values())
    portfolio_delta = {metric: portfolio["C1"][metric] - portfolio["A2"][metric] for metric in portfolio["C1"] if metric != "observation_count"}
    terminal_full_delta = float(paths["C1"].daily.reconstructed_nav.iloc[-1] - paths["A2"].daily.reconstructed_nav.iloc[-1])
    event_wealth_delta = float((joined.net_active_wealth_c1 - joined.net_active_wealth_a2).sum())
    require(abs(terminal_full_delta - event_wealth_delta) <= TOL, "C1_A2_EVENT_TERMINAL_RECONCILIATION_FAILURE", terminal_full_delta - event_wealth_delta)

    sufficient = len(joined) == EXPECTED_EVENT_COUNT and len(folds) == 5
    risk_improves = (
        portfolio["C1"]["annualized_volatility"] < portfolio["A2"]["annualized_volatility"]
        or portfolio["C1"]["max_drawdown"] > portfolio["A2"]["max_drawdown"]
    )
    temporal_pass = positive_folds >= 4 and pre_metrics["c1_minus_a2_active_return"] > TOL
    cost_does_not_erase = pooled["net_attenuation_value"] > TOL and event_wealth_delta > TOL
    if not sufficient:
        classification = "INSUFFICIENT_APPLICATION_COVERAGE"
    elif pooled["net_attenuation_value"] <= TOL:
        classification = "RISK_REDUCTION_WITH_NO_NET_ALPHA_GAIN" if risk_improves else "NO_ECONOMIC_IMPROVEMENT"
    elif pooled["tail_contribution_retention_ratio"] < 0.80:
        classification = "NET_POSITIVE_BUT_TAIL_DAMAGE_MATERIAL"
    elif not temporal_pass:
        classification = "UNSTABLE_ACROSS_TIME"
    elif pooled["nontail_drag_reduction"] > TOL and cost_does_not_erase:
        classification = "SUPPORTED_REDUCES_NONTAIL_DRAG_WITH_TAIL_PRESERVATION"
    else:
        classification = "UNSTABLE_ACROSS_TIME"
    prospective = {
        "SUPPORTED_REDUCES_NONTAIL_DRAG_WITH_TAIL_PRESERVATION": "SUPPORTED",
        "NET_POSITIVE_BUT_TAIL_DAMAGE_MATERIAL": "MIXED",
        "RISK_REDUCTION_WITH_NO_NET_ALPHA_GAIN": "MIXED",
        "UNSTABLE_ACROSS_TIME": "MIXED",
    }.get(classification, "NOT_SUPPORTED")
    application_result = (
        "FIXED_ATTENUATION_MECHANISM_SUPPORTED_FOR_PROSPECTIVE_SHADOW_CONSIDERATION"
        if classification == "SUPPORTED_REDUCES_NONTAIL_DRAG_WITH_TAIL_PRESERVATION"
        else "FIXED_RAW_SCORE_ATTENUATION_NOT_SUPPORTED"
    )

    rows: list[dict[str, str]] = []
    rows.extend([
        summary_row("STATUS", "RESEARCH_RESULT_STATUS", "ALL", "COMPLETED_VALID_DIAGNOSTIC"),
        summary_row("STATUS", "EXPERIMENT_STATUS", "ALL", "POST_DISCOVERY_OOS_APPLICATION_DIAGNOSTIC"),
        summary_row("STATUS", "PREDICTION_RESULT", "ALL", "ALREADY_ESTABLISHED_RAW_SCORE_PROBABILITY_SIGNAL"),
        summary_row("STATUS", "APPLICATION_RESULT", "ALL", application_result),
        summary_row("STATUS", "PROSPECTIVE_STATUS", "ALL", "UNVALIDATED_REQUIRES_SEPARATELY_AUTHORIZED_NO_BACKFILL_SHADOW"),
        summary_row("BOUNDARY", "DATE_MAX_OUTCOME_USED", "ALL", predictions.holding_end.max()),
        summary_row("BOUNDARY", "POST_2025_OUTCOME_USED", "ALL", False),
        summary_row("BOUNDARY", "NETWORK_USED", "ALL", False),
        summary_row("BOUNDARY", "MODEL_REFIT_COUNT", "ALL", 0),
        summary_row("BOUNDARY", "PARAMETER_SEARCH_COUNT", "ALL", 0),
        summary_row("BOUNDARY", "NEW_PREDICTOR_COUNT", "ALL", 0),
        summary_row("PRIOR_IDENTITY", "PRIOR_SIGNAL_IDENTITY_STATUS", "ALL", "PASS"),
        summary_row("PRIOR_IDENTITY", "OOS_APPLICATION_EVENT_COUNT", "ALL", len(predictions)),
        summary_row("PRIOR_IDENTITY", "RIGHT_TAIL_EVENT_COUNT", "ALL", int(predictions.right_tail.sum())),
        summary_row("PRIOR_IDENTITY", "AUROC", "ALL", EXPECTED_AUROC),
        summary_row("PRIOR_IDENTITY", "AP_OVER_BASE", "ALL", EXPECTED_AP_OVER_BASE),
        summary_row("PRIOR_IDENTITY", "OOS_PREDICTIONS_SHA256", "ALL", EXPECTED_PREDICTIONS_SHA256),
        summary_row("PRIOR_IDENTITY", "OOS_SUMMARY_SHA256", "ALL", EXPECTED_PRIOR_SUMMARY_SHA256),
        summary_row("REPLAY_IDENTITY", "CANONICAL_ENGINE_REUSED", "ALL", True, str(ENGINE)),
        summary_row("REPLAY_IDENTITY", "A_DAILY_MAX_ABS_ERROR", "ALL", replay_identity["a_daily_max_abs_error"]),
        summary_row("REPLAY_IDENTITY", "A2_DAILY_MAX_ABS_ERROR", "ALL", replay_identity["a2_daily_max_abs_error"]),
        summary_row("REPLAY_IDENTITY", "C1_ACCOUNTING_MAX_ABS_ERROR", "ALL", replay_identity["c1_accounting_max_abs_error"]),
        summary_row("REPLAY_IDENTITY", "A2_EVENT_WEALTH_MAX_ABS_ERROR", "ALL", a2_wealth_error),
        summary_row("REPLAY_IDENTITY", "A2_EVENT_ACTIVE_RETURN_MAX_ABS_ERROR", "ALL", a2_return_error),
        summary_row("REPLAY_IDENTITY", "C1_A2_EVENT_TERMINAL_RECONCILIATION_ERROR", "ALL", terminal_full_delta - event_wealth_delta),
        summary_row("TARGET_IDENTITY", "LAMBDA0_REPRODUCES_A_MAX_ABS_ERROR", "ALL", target_identity["max_endpoint0_error"]),
        summary_row("TARGET_IDENTITY", "LAMBDA1_REPRODUCES_A2_MAX_ABS_ERROR", "ALL", target_identity["max_endpoint1_error"]),
        summary_row("TARGET_IDENTITY", "TARGET_WEIGHT_SUM_MAX_ABS_ERROR", "ALL", target_identity["max_target_sum_error"]),
        summary_row("TARGET_IDENTITY", "ACTIVE_EXPOSURE_EXCESS_MAX", "ALL", target_identity["max_active_exposure_excess"]),
        summary_row("TARGET_IDENTITY", "IDENTICAL_TARGET_ARTIFICIAL_EVENT_COUNT", "ALL", target_identity["identical_target_artificial_count"]),
        summary_row("TARGET_IDENTITY", "PRE_OOS_C1_EQUALS_A2_NAV_MAX_ABS_ERROR", "ALL", pre_oos_c1_a2_error, "A2 initialization only; no pre-OOS probability used or evaluated"),
    ])
    for arm in ("A", "A2", "C1"):
        for metric, value in portfolio[arm].items():
            rows.append(summary_row("PORTFOLIO", metric.upper(), arm, value, f"common execution window {first_active.date()} through {last_outcome.date()}"))
    for metric, value in portfolio_delta.items():
        rows.append(summary_row("PORTFOLIO_DELTA", f"C1_MINUS_A2_{metric.upper()}", "C1_MINUS_A2", value))
    rows.extend([
        summary_row("PORTFOLIO_DELTA", "C1_MINUS_A_TERMINAL_WEALTH", "C1_MINUS_A", portfolio["C1"]["terminal_wealth"] - portfolio["A"]["terminal_wealth"]),
        summary_row("PORTFOLIO_DELTA", "C1_MINUS_A_CUM_RETURN", "C1_MINUS_A", portfolio["C1"]["cumulative_return"] - portfolio["A"]["cumulative_return"]),
    ])
    for metric, value in pooled.items():
        rows.append(summary_row("MECHANISM", metric.upper(), "ALL_OOS", value, "common A2 pretrade-NAV denominator for active contributions"))
    lambda_values = predictions["lambda"].astype(float)
    lambda_metrics = {
        "LAMBDA_COUNT": len(lambda_values), "MEAN_LAMBDA": lambda_values.mean(), "MEDIAN_LAMBDA": lambda_values.median(),
        "LAMBDA_Q10": lambda_values.quantile(.10), "LAMBDA_Q25": lambda_values.quantile(.25),
        "LAMBDA_Q75": lambda_values.quantile(.75), "LAMBDA_Q90": lambda_values.quantile(.90),
        "FULL_A2_LAMBDA1_FRACTION": np.isclose(lambda_values, 1.0, atol=1e-15, rtol=0).mean(),
        "LAMBDA_BELOW1_FRACTION": (lambda_values < 1.0 - 1e-15).mean(),
        "LAMBDA_BELOW_HALF_FRACTION": (lambda_values < 0.5).mean(), "MIN_LAMBDA": lambda_values.min(),
    }
    for metric, value in lambda_metrics.items():
        rows.append(summary_row("LAMBDA_DISTRIBUTION", metric, "ALL_OOS", value))
    for fold, values in folds.items():
        full_fraction = float(np.isclose(joined.loc[joined.outer_fold.eq(fold), "lambda"], 1.0, atol=1e-15, rtol=0).mean())
        rows.append(summary_row("FOLD_STABILITY", "FULL_A2_LAMBDA1_FRACTION", fold, full_fraction))
        for metric, value in values.items():
            rows.append(summary_row("FOLD_STABILITY", metric.upper(), fold, value))
    for metric, value in pre_metrics.items():
        rows.append(summary_row("PRE2025_STABILITY", f"PRE2025_{metric.upper()}", "OUTCOME_BEFORE_2025", value))
    for year, values in years.items():
        for metric in (
            "event_count", "mean_lambda", "a2_active_return", "c1_active_return", "c1_minus_a2_active_return",
            "tail_contribution_retention_ratio", "nontail_drag_reduction",
        ):
            rows.append(summary_row("YEAR_VIEW", metric.upper(), year, values[metric]))
    rows.extend([
        summary_row("STABILITY_COUNTS", "POSITIVE_C1_MINUS_A2_FOLD_COUNT", "ALL", positive_folds),
        summary_row("STABILITY_COUNTS", "NEGATIVE_C1_MINUS_A2_FOLD_COUNT", "ALL", negative_folds),
        summary_row("STABILITY_COUNTS", "POSITIVE_NONTAIL_DRAG_REDUCTION_FOLD_COUNT", "ALL", positive_nontail_folds),
        summary_row("STABILITY_COUNTS", "POSITIVE_C1_MINUS_A2_YEAR_COUNT", "ALL", positive_years),
        summary_row("STABILITY_COUNTS", "NEGATIVE_C1_MINUS_A2_YEAR_COUNT", "ALL", negative_years),
        summary_row("CLASSIFICATION", "ATTENUATION_MECHANISM_CLASSIFICATION", "ALL", classification),
        summary_row("CLASSIFICATION", "PROSPECTIVE_SIZING_SHADOW_JUSTIFICATION", "ALL", prospective),
        summary_row("CLASSIFICATION", "APPLICATION_RESULT", "ALL", application_result),
    ])
    result = {
        "portfolio": portfolio, "portfolio_delta": portfolio_delta, "pooled": pooled, "folds": folds,
        "pre2025": pre_metrics, "years": years, "lambda": lambda_metrics,
        "positive_folds": positive_folds, "negative_folds": negative_folds,
        "positive_nontail_folds": positive_nontail_folds, "positive_years": positive_years,
        "negative_years": negative_years, "classification": classification, "prospective": prospective,
        "application_result": application_result, "first_active": first_active, "last_outcome": last_outcome,
        "event_wealth_delta": event_wealth_delta,
    }
    return result, rows, application_result


def table(rows: list[list[str]], header: list[str]) -> str:
    return "\n".join([
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def build_report(result: dict[str, Any], identity: dict[str, float], engine_hash: str) -> str:
    portfolio_rows = [
        [arm, *[display(result["portfolio"][arm][metric]) for metric in (
            "terminal_wealth", "cumulative_return", "cagr", "annualized_volatility", "sharpe", "max_drawdown", "turnover", "transaction_cost",
        )]] for arm in ("A", "A2", "C1")
    ]
    fold_rows = [[fold, *[display(values[metric]) for metric in (
        "event_count", "mean_lambda", "a2_active_return", "c1_active_return", "c1_minus_a2_active_return",
        "tail_contribution_retention_ratio", "nontail_drag_reduction", "turnover_difference", "cost_difference",
    )]] for fold, values in result["folds"].items()]
    year_rows = [[year, *[display(values[metric]) for metric in (
        "event_count", "mean_lambda", "a2_active_return", "c1_active_return", "c1_minus_a2_active_return",
        "tail_contribution_retention_ratio", "nontail_drag_reduction",
    )]] for year, values in result["years"].items()]
    p = result["pooled"]
    interpretation = (
        "A separately authorized no-backfill prospective shadow may be worthwhile; this diagnostic does not initialize one."
        if result["prospective"] == "SUPPORTED"
        else "The fixed Raw-score attenuation is not supported for prospective shadowing; close this historical sizing branch unless separately authorized."
    )
    return f"""# A2 Raw-score active-deviation attenuation R1

## Decision

`EXPERIMENT_STATUS=POST_DISCOVERY_OOS_APPLICATION_DIAGNOSTIC`

`ATTENUATION_MECHANISM_CLASSIFICATION={result['classification']}`

`PROSPECTIVE_SIZING_SHADOW_JUSTIFICATION={result['prospective']}`

`APPLICATION_RESULT={result['application_result']}`

{interpretation}

## Fixed mechanism answer

- Non-tail drag reduction: `{display(p['nontail_drag_reduction'])}`.
- Tail contribution retention ratio: `{display(p['tail_contribution_retention_ratio'])}`.
- Net attenuation value: `{display(p['net_attenuation_value'])}`.
- Positive/negative chronological folds: `{result['positive_folds']}/{result['negative_folds']}`; positive non-tail-drag-reduction folds: `{result['positive_nontail_folds']}`.
- Pre-2025 C1-minus-A2 active return: `{display(result['pre2025']['c1_minus_a2_active_return'])}`.

Active contributions use the exact canonical net wealth attribution divided by each event's persisted A2 pretrade NAV, the same common denominator used by the prior strict-OOS event artifact. Canonical net wealth reconciliation is also enforced exactly.

## Common-window portfolio replay

{table(portfolio_rows, ['Arm', 'Terminal wealth', 'Cumulative return', 'CAGR', 'Ann. volatility', 'Sharpe', 'MaxDD', 'Turnover', 'Transaction cost'])}

The common economic window is {result['first_active'].date()} through {result['last_outcome'].date()}. C1 uses A2 only as a pre-application state initializer; no pre-OOS probability is supplied or evaluated.

## Lambda distribution

The sole mapping is `lambda = clip(persisted strict-OOS probability / exact purged OUTER TRAIN label base rate, 0, 1)`. N={result['lambda']['LAMBDA_COUNT']}, mean={display(result['lambda']['MEAN_LAMBDA'])}, median={display(result['lambda']['MEDIAN_LAMBDA'])}, Q10/Q25/Q75/Q90={display(result['lambda']['LAMBDA_Q10'])}/{display(result['lambda']['LAMBDA_Q25'])}/{display(result['lambda']['LAMBDA_Q75'])}/{display(result['lambda']['LAMBDA_Q90'])}, full-A2 fraction={display(result['lambda']['FULL_A2_LAMBDA1_FRACTION'])}, below-one fraction={display(result['lambda']['LAMBDA_BELOW1_FRACTION'])}, below-half fraction={display(result['lambda']['LAMBDA_BELOW_HALF_FRACTION'])}, minimum={display(result['lambda']['MIN_LAMBDA'])}.

## Fold stability

{table(fold_rows, ['Fold', 'N', 'Mean lambda', 'A2 active', 'C1 active', 'C1-A2', 'Tail retention', 'Non-tail reduction', 'Turnover diff', 'Cost diff'])}

## Pre-2025

N={int(result['pre2025']['event_count'])}; mean lambda={display(result['pre2025']['mean_lambda'])}; A2 active={display(result['pre2025']['a2_active_return'])}; C1 active={display(result['pre2025']['c1_active_return'])}; C1-A2={display(result['pre2025']['c1_minus_a2_active_return'])}; tail retention={display(result['pre2025']['tail_contribution_retention_ratio'])}; non-tail drag reduction={display(result['pre2025']['nontail_drag_reduction'])}.

## Descriptive year view

{table(year_rows, ['Year', 'N', 'Mean lambda', 'A2 active', 'C1 active', 'C1-A2', 'Tail retention', 'Non-tail reduction'])}

## Identity and interpretation

- Prior 625-event identity: PASS; right-tail N=67; AUROC={identity['auroc']:.10f}; AP/base={identity['ap_over_base']:.10f}.
- A and A2 canonical daily replay maximum errors: zero at 1e-12 tolerance.
- Existing canonical replay engine: `{ENGINE}` (`sha256={engine_hash}`).
- Model refits, new predictors, parameter searches, alternative mappings, and network calls: zero.
- Maximum outcome date: 2025-12-31; post-2025 outcomes used: false.

`PREDICTION_RESULT=ALREADY_ESTABLISHED_RAW_SCORE_PROBABILITY_SIGNAL`

`APPLICATION_RESULT={result['application_result']}`

`PROSPECTIVE_STATUS=UNVALIDATED_REQUIRES_SEPARATELY_AUTHORIZED_NO_BACKFILL_SHADOW`

The Raw-score probabilities are strict chronological OOS. The attenuation rule is fixed and parameter-free, but its application was designed after historical OOS results were observed. This is not an independent holdout, does not promote a strategy, and cannot initialize a forward arm.
"""


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_csv(temporary, index=False, lineterminator="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def console_summary(result: dict[str, Any]) -> str:
    p = result["portfolio"]
    d = result["portfolio_delta"]
    m = result["pooled"]
    pre = result["pre2025"]
    lam = result["lambda"]
    next_question = (
        "SEPARATELY_AUTHORIZED_NO_BACKFILL_PROSPECTIVE_SHADOW"
        if result["prospective"] == "SUPPORTED"
        else "NONE_CLOSE_HISTORICAL_SIZING_BRANCH_UNLESS_SEPARATELY_AUTHORIZED"
    )
    return f"""============================================================
A2_RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION_R1_FINAL
============================================================

RESEARCH_RESULT_STATUS=COMPLETED_VALID_DIAGNOSTIC
EXECUTION_STATUS=PASS
REPOSITORY_POLICY_STATUS=PASS_RESEARCH_ONLY_NO_PROMOTION

EXPERIMENT_STATUS=POST_DISCOVERY_OOS_APPLICATION_DIAGNOSTIC

DATE_MAX_OUTCOME_USED=2025-12-31
POST_2025_OUTCOME_USED=false
NETWORK_USED=false

PRIOR_SIGNAL_IDENTITY_STATUS=PASS
OOS_APPLICATION_EVENT_COUNT={EXPECTED_EVENT_COUNT}

LAMBDA_DEFINITION=clip(PERSISTED_OOS_PROBABILITY/TRAIN_FOLD_BASE_RATE,0,1)
MEAN_LAMBDA={display(lam['MEAN_LAMBDA'])}
MEDIAN_LAMBDA={display(lam['MEDIAN_LAMBDA'])}
FULL_A2_LAMBDA1_FRACTION={display(lam['FULL_A2_LAMBDA1_FRACTION'])}
LAMBDA_BELOW1_FRACTION={display(lam['LAMBDA_BELOW1_FRACTION'])}
LAMBDA_BELOW_HALF_FRACTION={display(lam['LAMBDA_BELOW_HALF_FRACTION'])}

A_TERMINAL_WEALTH={display(p['A']['terminal_wealth'])}
A2_TERMINAL_WEALTH={display(p['A2']['terminal_wealth'])}
C1_TERMINAL_WEALTH={display(p['C1']['terminal_wealth'])}

C1_MINUS_A2_CUM_RETURN={display(d['cumulative_return'])}
C1_MINUS_A2_SHARPE={display(d['sharpe'])}
C1_MINUS_A2_MAXDD_CHANGE={display(d['max_drawdown'])}
C1_MINUS_A2_TURNOVER_CHANGE={display(d['turnover'])}
C1_MINUS_A2_COST_CHANGE={display(d['transaction_cost'])}

A2_TAIL_ACTIVE_CONTRIBUTION={display(m['a2_tail_active_contribution'])}
C1_TAIL_ACTIVE_CONTRIBUTION={display(m['c1_tail_active_contribution'])}
TAIL_CONTRIBUTION_RETENTION_RATIO={display(m['tail_contribution_retention_ratio'])}

A2_NONTAIL_ACTIVE_CONTRIBUTION={display(m['a2_nontail_active_contribution'])}
C1_NONTAIL_ACTIVE_CONTRIBUTION={display(m['c1_nontail_active_contribution'])}
NONTAIL_DRAG_REDUCTION={display(m['nontail_drag_reduction'])}

NET_ATTENUATION_VALUE={display(m['net_attenuation_value'])}

POSITIVE_C1_MINUS_A2_FOLD_COUNT={result['positive_folds']}
NEGATIVE_C1_MINUS_A2_FOLD_COUNT={result['negative_folds']}
POSITIVE_NONTAIL_DRAG_REDUCTION_FOLD_COUNT={result['positive_nontail_folds']}

PRE2025_EVENT_COUNT={int(pre['event_count'])}
PRE2025_C1_MINUS_A2_ACTIVE_RETURN={display(pre['c1_minus_a2_active_return'])}
PRE2025_TAIL_CONTRIBUTION_RETENTION_RATIO={display(pre['tail_contribution_retention_ratio'])}
PRE2025_NONTAIL_DRAG_REDUCTION={display(pre['nontail_drag_reduction'])}

POSITIVE_C1_MINUS_A2_YEAR_COUNT={result['positive_years']}
NEGATIVE_C1_MINUS_A2_YEAR_COUNT={result['negative_years']}

ATTENUATION_MECHANISM_CLASSIFICATION={result['classification']}
PROSPECTIVE_SIZING_SHADOW_JUSTIFICATION={result['prospective']}

SOURCE_MODIFICATION_COUNT=1
RESULT_ARTIFACT_COUNT=2
TEMP_FILE_REMAINS=0

NEXT_RESEARCH_QUESTION={next_question}"""


def main() -> None:
    predictions, _, _, identity, train_rows = load_prior_signal()
    targets, selections, frozen_daily, positions, hashes = target_maps_from_frozen()
    prices = frozen_price_panel(selections, frozen_daily, positions)
    c1_targets, target_identity = build_c1_targets(targets, predictions)
    engine = load_module("a2_attenuation_canonical_r0f", ENGINE)
    paths, replay_identity = replay_and_validate(
        engine, targets, c1_targets, selections, frozen_daily, prices,
    )
    require(predictions.pretrade_nav.notna().all(), "OOS_PRETRADE_NAV_MAPPING_FAILURE")
    result, rows, _ = analyze(predictions, paths, replay_identity, target_identity)
    rows.extend(train_rows)
    for path, digest in sorted(hashes.items()):
        rows.append(summary_row("FROZEN_INPUT_IDENTITY", "SHA256", path, digest))
    rows.append(summary_row("REPLAY_IDENTITY", "CANONICAL_ENGINE_SHA256", str(ENGINE), sha256_file(ENGINE)))
    report = build_report(result, identity, sha256_file(ENGINE))
    allowed = {"final_report.md", "attenuation_summary.csv"}
    if OUT.exists():
        unexpected = sorted(path.name for path in OUT.iterdir() if path.name not in allowed)
        require(not unexpected, "UNEXPECTED_TARGET_RESULT_ARTIFACT", unexpected)
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_csv(OUT / "attenuation_summary.csv", pd.DataFrame(rows))
    atomic_text(OUT / "final_report.md", report)
    artifacts = sorted(path.name for path in OUT.iterdir() if path.is_file())
    require(artifacts == sorted(allowed), "RESULT_ARTIFACT_SET_FAILURE", artifacts)
    require(not list(OUT.glob(".*.tmp")), "TEMP_FILE_REMAINS")
    print(console_summary(result))


if __name__ == "__main__":
    main()
