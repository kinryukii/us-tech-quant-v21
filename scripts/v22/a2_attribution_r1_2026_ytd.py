"""Forensic attribution of the frozen authoritative A2-HGB 2026 YTD path.

This runner never fits, tunes, selects, or changes a portfolio.  It consumes the
hash-verified R2A retrospective predictions and replays only the frozen daily
accounting function so that security contributions can be reconciled to the
authoritative economic summary before any diagnosis is emitted.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


RUN_ID = "A2_ATTRIBUTION_R1_2026_YTD"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / RUN_ID
R2A_OUT = RESULTS / "A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR"
R2A_SOURCE = REPO / "scripts/v22/a2_algorithm_r2a_2026_retrospective_and_forward_shadow_anchor.py"
EXECUTION_SOURCE = REPO / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
ANTI_BLOAT_POLICY = REPO / "docs/governance/ANTI_BLOAT_POLICY.md"
TOP_N = 20
MODEL = "M0_A2_HGB"
EVIDENCE_STATUS = "RETROSPECTIVE_WITH_PRIOR_OUTCOME_EXPOSURE"
SECTOR_STATUS = "SKIPPED_INSUFFICIENT_AUTHORITATIVE_SECTOR_LINEAGE"
MARKET_STATUS = "PASS_CANONICAL_MOOMOO_ONLY_QQQ"
REQUIRED_OUTPUTS = (
    "attribution_contract.json",
    "a2_identity_audit.json",
    "security_pnl_attribution.csv",
    "date_level_attribution.csv",
    "sector_attribution.csv",
    "13f_vintage_attribution.csv",
    "winner_loser_attribution.csv",
    "execution_cost_attribution.csv",
    "concentration_diagnostics.csv",
    "max_drawdown_security_contribution.csv",
    "max_drawdown_date_contribution.csv",
    "max_drawdown_sector_contribution.csv",
    "max_drawdown_forensic.md",
    "risk_source_taxonomy.csv",
    "attribution_report.md",
    "status.json",
)


class ContractFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise ContractFailure(f"{code}|{evidence}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def atomic_json(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False, default=str),
        encoding="utf-8",
    )
    os.replace(temp, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    os.replace(temp, path)


def import_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return np.nan
    return result if math.isfinite(result) else np.nan


def positive_share(values: Iterable[float], n: int) -> float:
    series = pd.Series(values, dtype=float)
    series = series[series > 0].sort_values(ascending=False)
    return float(series.head(n).sum() / series.sum()) if series.sum() > 0 else np.nan


def negative_share(values: Iterable[float], n: int) -> float:
    series = -pd.Series(values, dtype=float)
    series = series[series > 0].sort_values(ascending=False)
    return float(series.head(n).sum() / series.sum()) if series.sum() > 0 else np.nan


def metric_set(returns: pd.Series) -> dict[str, float]:
    r = returns.to_numpy(float)
    nav = pd.Series(np.r_[1.0, np.cumprod(1.0 + r)])
    total = float(nav.iloc[-1] - 1.0)
    vol = float(np.std(r, ddof=0) * np.sqrt(252)) if len(r) else np.nan
    sharpe = float(np.mean(r) * 252 / vol) if vol > 0 else np.nan
    dd = nav / nav.cummax() - 1.0
    return {
        "cumulative_return": total,
        "sharpe": sharpe,
        "max_drawdown": float(dd.min()),
    }


def link_contributions(frame: pd.DataFrame, return_column: str, columns: list[str]) -> pd.DataFrame:
    """Frongello-link additive daily contributions to an exact cumulative return."""
    out = frame.copy()
    daily = out[["economic_date", return_column]].drop_duplicates("economic_date").sort_values("economic_date")
    require(not daily.economic_date.duplicated().any(), "DUPLICATE_LINK_DATE")
    future = np.ones(len(daily), dtype=float)
    running = 1.0
    returns = daily[return_column].to_numpy(float)
    for index in range(len(daily) - 1, -1, -1):
        future[index] = running
        running *= 1.0 + returns[index]
    multiplier = pd.Series(future, index=pd.DatetimeIndex(daily.economic_date))
    out["link_multiplier"] = out.economic_date.map(multiplier)
    for column in columns:
        out[f"linked_{column}"] = out[column] * out.link_multiplier
    return out


def verify_r2a_manifest() -> tuple[dict[str, Any], dict[str, str]]:
    require(R2A_OUT.is_dir(), "AUTHORITATIVE_R2A_DIRECTORY_MISSING", R2A_OUT)
    manifest_path = R2A_OUT / "manifest.json"
    require(manifest_path.is_file(), "AUTHORITATIVE_R2A_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("artifacts", [])
    require(len(rows) == manifest.get("artifact_count_excluding_self"), "R2A_MANIFEST_COUNT_MISMATCH")
    hashes: dict[str, str] = {}
    for row in rows:
        path = R2A_OUT / row["artifact"]
        require(path.is_file(), "R2A_ARTIFACT_MISSING", path)
        actual = sha256(path)
        require(actual == row["sha256"], "R2A_ARTIFACT_HASH_MISMATCH", path.name)
        hashes[path.name] = actual
    for required in (
        "status.json",
        "retrospective_contract.json",
        "2026_retrospective_predictions.parquet",
        "2026_retrospective_top20.csv",
        "2026_universe_coverage_by_date.csv",
        "2026_retrospective_economic_metrics.csv",
    ):
        require(required in hashes, "R2A_REQUIRED_LINEAGE_NOT_MANIFESTED", required)
    return manifest, hashes


def load_authoritative_inputs() -> dict[str, Any]:
    manifest, hashes = verify_r2a_manifest()
    status = json.loads((R2A_OUT / "status.json").read_text(encoding="utf-8"))
    contract = json.loads((R2A_OUT / "retrospective_contract.json").read_text(encoding="utf-8"))
    predictions = pd.read_parquet(R2A_OUT / "2026_retrospective_predictions.parquet")
    top20 = pd.read_csv(R2A_OUT / "2026_retrospective_top20.csv")
    coverage = pd.read_csv(R2A_OUT / "2026_universe_coverage_by_date.csv")
    economic = pd.read_csv(R2A_OUT / "2026_retrospective_economic_metrics.csv")
    for frame in (predictions, top20, coverage):
        for column in ("prediction_date", "13f_effective_date"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    if "target_end_date" in predictions:
        predictions["target_end_date"] = pd.to_datetime(predictions.target_end_date).dt.normalize()
    model_predictions = predictions.loc[predictions.model.eq(MODEL)].copy()
    model_top20 = top20.loc[top20.model.eq(MODEL)].copy()
    require(status["2026_YTD_EVIDENCE_STATUS"] == EVIDENCE_STATUS, "R2A_EVIDENCE_STATUS_MISMATCH")
    require(status["2026_TRAINING_ROWS"] == 0 and status["2026_PARAMETER_SEARCH_COUNT"] == 0, "R2A_FORBIDDEN_SEARCH_OR_TRAINING")
    require(int(model_predictions.target.notna().sum()) == status["MATURED_2026_PREDICTION_ROW_COUNT"], "R2A_ROW_COUNT_MISMATCH")
    dates = pd.DatetimeIndex(sorted(model_predictions.prediction_date.unique()))
    require(len(dates) == status["MATURED_2026_PREDICTION_DATE_COUNT"], "R2A_DATE_COUNT_MISMATCH")
    require(str(dates.min().date()) == status["FIRST_2026_ELIGIBLE_PREDICTION_DATE"], "R2A_FIRST_DATE_MISMATCH")
    require(str(dates.max().date()) == status["LAST_2026_MATURED_PREDICTION_DATE"], "R2A_LAST_DATE_MISMATCH")
    derived_top = model_predictions.loc[model_predictions.selected_top20].sort_values(["prediction_date", "rank", "ticker"])
    stored_top = model_top20.sort_values(["prediction_date", "rank", "ticker"])
    keys = ["prediction_date", "ticker", "rank", "score", "13f_vintage", "13f_effective_date"]
    pd.testing.assert_frame_equal(derived_top[keys].reset_index(drop=True), stored_top[keys].reset_index(drop=True), check_dtype=False)
    require(model_top20.groupby("prediction_date").size().eq(TOP_N).all(), "TOP20_CARDINALITY_MISMATCH")
    require(int(coverage.PIT_13F_TEMPORAL_VIOLATION.sum()) == 0, "PIT_13F_TEMPORAL_VIOLATION")
    require((coverage.prediction_date >= coverage["13f_effective_date"]).all(), "PIT_13F_TEMPORAL_VIOLATION")
    return {
        "manifest": manifest,
        "hashes": hashes,
        "status": status,
        "contract": contract,
        "predictions": model_predictions,
        "top20": model_top20,
        "coverage": coverage,
        "economic": economic.loc[economic.model.eq(MODEL)].iloc[0],
        "dates": dates,
    }


def replay_economic_path(inputs: dict[str, Any]) -> dict[str, Any]:
    source_hash_before = sha256(R2A_SOURCE)
    execution_hash_before = sha256(EXECUTION_SOURCE)
    r2a = import_path("a2_attribution_r2a_lineage", R2A_SOURCE)
    old = import_path("a2_attribution_execution_lineage", EXECUTION_SOURCE)
    qqq, pointer = r2a.load_qqq()
    latest = pd.Timestamp(qqq.trade_date.max())
    require(str(latest.date()) == inputs["status"]["LATEST_2026_AVAILABLE_MARKET_DATE"], "LATEST_MARKET_DATE_MISMATCH")
    _active, members = r2a.validate_pit_manifest(qqq)
    adapter = import_path("a2_attribution_price_adapter", r2a.ADAPTER)
    prices, price_audit = r2a.load_equity_prices(adapter, members, latest)
    selected = inputs["top20"]
    target_map: dict[pd.Timestamp, dict[str, float]] = {}
    for date, day in selected.groupby("prediction_date", sort=True):
        require(len(day) == TOP_N and day.ticker.nunique() == TOP_N, "TOP20_TARGET_FAILURE", date)
        target_map[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
    calendar = pd.DatetimeIndex(qqq.trade_date)
    first_date = inputs["dates"].min()
    last_date = inputs["dates"].max()
    require(first_date in calendar and last_date in calendar, "PREDICTION_DATE_NOT_IN_QQQ_CALENDAR")
    execution_end = pd.Timestamp(calendar[calendar.get_loc(last_date) + 1])
    old.EFFECTIVE_START = first_date
    old.COST_BPS = int(inputs["contract"]["transaction_cost_bps"])
    all_prices = pd.concat(
        [
            prices.loc[prices.trade_date.le(execution_end)],
            qqq.loc[qqq.trade_date.le(execution_end), ["ticker", "trade_date", "open", "close", "volume"]],
        ],
        ignore_index=True,
        sort=False,
    )
    result = old.reconstruct_open_ended(MODEL, target_map, all_prices, calendar, execution_end)
    require(not result.missing_price_events, "EXECUTION_MISSING_PRICE_EVENT", result.missing_price_events[:5])
    replay_metrics = r2a.economic_metrics(old, {MODEL: result}).iloc[0]
    frozen = inputs["economic"]
    columns = [
        "cumulative_return",
        "annualized_return_partial_year",
        "volatility",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "profit_factor",
        "turnover_annualized",
        "turnover_total_one_way",
        "transaction_cost",
        "average_holdings",
        "rebalance_count",
    ]
    differences = {column: finite_float(replay_metrics[column]) - finite_float(frozen[column]) for column in columns}
    max_error = max(abs(value) for value in differences.values() if math.isfinite(value))
    require(max_error <= 5e-12, "FAIL_CLOSED_A2_ECONOMIC_PATH_MISMATCH", differences)
    daily = result.daily.copy()
    expected_daily_dates = pd.DatetimeIndex([first_date, *list(calendar[(calendar > first_date) & (calendar <= execution_end)])])
    require(pd.DatetimeIndex(daily.date).equals(expected_daily_dates), "A2_ECONOMIC_DATE_IDENTITY_MISMATCH")
    require(abs(float(daily.nav.iloc[-1]) - (1.0 + float(frozen.cumulative_return))) <= 5e-12, "A2_NAV_IDENTITY_MISMATCH")
    require(abs(float(daily.turnover.sum()) - float(frozen.turnover_total_one_way)) <= 5e-12, "A2_TURNOVER_IDENTITY_MISMATCH")
    require(abs(float(daily.transaction_cost.sum()) - float(frozen.transaction_cost)) <= 5e-12, "A2_COST_IDENTITY_MISMATCH")
    require(source_hash_before == sha256(R2A_SOURCE), "R2A_SOURCE_CHANGED_DURING_RUN")
    require(execution_hash_before == sha256(EXECUTION_SOURCE), "EXECUTION_SOURCE_CHANGED_DURING_RUN")
    return {
        "r2a": r2a,
        "old": old,
        "qqq": qqq,
        "pointer": pointer,
        "prices": prices,
        "price_audit": price_audit,
        "path": result,
        "metrics": replay_metrics,
        "differences": differences,
        "max_error": max_error,
        "execution_end": execution_end,
        "r2a_source_sha256": source_hash_before,
        "execution_source_sha256": execution_hash_before,
    }


def selection_streaks(top20: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[tuple[pd.Timestamp, str], int]:
    selected = {date: set(top20.loc[top20.prediction_date.eq(date), "ticker"].astype(str)) for date in dates}
    running: dict[str, int] = {}
    result: dict[tuple[pd.Timestamp, str], int] = {}
    for date in dates:
        current = selected[date]
        for ticker in list(running):
            if ticker not in current:
                running[ticker] = 0
        for ticker in current:
            running[ticker] = running.get(ticker, 0) + 1
            result[(date, ticker)] = running[ticker]
    return result


def build_security_and_dates(inputs: dict[str, Any], replay: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = replay["path"].daily.copy()
    positions = replay["path"].positions.copy()
    daily["date"] = pd.to_datetime(daily.date).dt.normalize()
    positions["date"] = pd.to_datetime(positions.date).dt.normalize()
    economic_dates = pd.DatetimeIndex(daily.date.iloc[1:])
    prediction_dates = inputs["dates"]
    require(len(economic_dates) == len(prediction_dates), "PREDICTION_EXECUTION_DATE_COUNT_MISMATCH")
    execution_to_prediction = pd.Series(prediction_dates, index=economic_dates)
    prediction_to_execution = pd.Series(economic_dates, index=prediction_dates)
    previous_prediction = {prediction_dates[i]: prediction_dates[i - 1] if i else pd.NaT for i in range(len(prediction_dates))}
    daily_index = daily.set_index("date")
    prior_nav = daily_index.nav.shift(1)
    positions["economic_date"] = positions.pop("date")
    positions["prediction_date"] = positions.economic_date.map(execution_to_prediction)
    positions["gross_source_prediction_date"] = positions.prediction_date.map(previous_prediction)
    positions["prior_nav"] = positions.economic_date.map(prior_nav)
    positions["pretrade_nav"] = positions.groupby("economic_date").market_pnl.transform("sum") + positions.prior_nav
    positions["gross_return_contribution"] = positions.market_pnl / positions.prior_nav
    positions["cost_return_contribution"] = -positions.transaction_cost / positions.prior_nav
    positions["net_return_contribution"] = positions.gross_return_contribution + positions.cost_return_contribution
    positions["capital_weight_before"] = positions.shares_before * positions.current_price / positions.pretrade_nav
    positions["capital_weight_after"] = positions.shares_after * positions.current_price / positions.economic_date.map(daily_index.nav)
    positions["holding_open_to_open_return"] = np.where(
        positions.shares_before.gt(0) & positions.previous_price.gt(0),
        positions.current_price / positions.previous_price - 1.0,
        np.nan,
    )
    current = inputs["top20"][[
        "prediction_date", "ticker", "rank", "score", "target", "target_end_date",
        "13f_vintage", "13f_effective_date", "eligible_count",
    ]].rename(columns={
        "rank": "entry_rank", "score": "entry_score", "target": "forward_target_return",
    })
    positions = positions.merge(current, on=["prediction_date", "ticker"], how="left", validate="many_to_one")
    prior = inputs["top20"][["prediction_date", "ticker", "rank", "score", "13f_vintage"]].rename(columns={
        "prediction_date": "gross_source_prediction_date", "rank": "gross_source_rank",
        "score": "gross_source_score", "13f_vintage": "gross_source_13f_vintage",
    })
    positions = positions.merge(prior, on=["gross_source_prediction_date", "ticker"], how="left", validate="many_to_one")
    positions["selected_current_top20"] = positions.entry_rank.notna()
    positions["selected_previous_top20"] = positions.gross_source_rank.notna()
    positions["entry_exit_status"] = np.select(
        [
            positions.selected_current_top20 & ~positions.selected_previous_top20,
            ~positions.selected_current_top20 & positions.selected_previous_top20,
            positions.selected_current_top20 & positions.selected_previous_top20,
        ],
        ["ENTRY", "EXIT", "HOLD"],
        default="ACCOUNTING_ONLY",
    )
    streaks = selection_streaks(inputs["top20"], prediction_dates)
    positions["holding_duration_sessions"] = [streaks.get((date, str(ticker)), 0) for date, ticker in zip(positions.prediction_date, positions.ticker)]
    positions["sector"] = "NA_UNAVAILABLE"
    positions["sector_lineage_status"] = SECTOR_STATUS
    positions["tail_loss_flag"] = positions.holding_open_to_open_return.le(-0.10)
    positions["return_contribution_definition"] = "PNL_DIVIDED_BY_PRIOR_NAV"
    positions["capital_weight_definition"] = "MARKED_CAPITAL_DIVIDED_BY_NAV_NOT_RETURN_CONTRIBUTION"
    check = positions.groupby("economic_date")[["gross_return_contribution", "cost_return_contribution", "net_return_contribution"]].sum()
    exact = daily_index.loc[economic_dates]
    gross_daily = check.gross_return_contribution
    cost_effect = -exact.transaction_cost / prior_nav.loc[economic_dates]
    require(float((check.cost_return_contribution - cost_effect).abs().max()) <= 2e-12, "DAILY_COST_CONTRIBUTION_IDENTITY_MISMATCH")
    require(float((check.net_return_contribution - exact.daily_return).abs().max()) <= 2e-12, "DAILY_RETURN_CONTRIBUTION_IDENTITY_MISMATCH")
    positions = link_contributions(
        positions,
        "daily_net_return",
        ["gross_return_contribution", "cost_return_contribution", "net_return_contribution"],
    ) if False else positions
    # Link with the authoritative daily return after retaining one row per security.
    positions["daily_net_return"] = positions.economic_date.map(daily_index.daily_return)
    daily_returns = exact.daily_return
    future = np.ones(len(economic_dates), dtype=float)
    running = 1.0
    for index in range(len(economic_dates) - 1, -1, -1):
        future[index] = running
        running *= 1.0 + float(daily_returns.iloc[index])
    multiplier = pd.Series(future, index=economic_dates)
    positions["full_sample_link_multiplier"] = positions.economic_date.map(multiplier)
    for column in ("gross_return_contribution", "cost_return_contribution", "net_return_contribution"):
        positions[f"linked_{column}_full_sample"] = positions[column] * positions.full_sample_link_multiplier
    linked_total = float(positions.linked_net_return_contribution_full_sample.sum())
    require(abs(linked_total - float(exact.nav.iloc[-1] / daily.nav.iloc[0] - 1.0)) <= 3e-12, "FULL_SAMPLE_LINKED_CONTRIBUTION_MISMATCH")

    qopen = pd.Series(replay["qqq"].open.to_numpy(float), index=pd.DatetimeIndex(replay["qqq"].trade_date))
    qqq_return = qopen.pct_change()
    coverage = inputs["coverage"].set_index("prediction_date")
    date_rows: list[dict[str, Any]] = []
    turnover_q90 = float(exact.turnover.quantile(0.90))
    for economic_date, prediction_date in zip(economic_dates, prediction_dates):
        sec = positions.loc[positions.economic_date.eq(economic_date)]
        selected = sec.loc[sec.selected_current_top20].sort_values("capital_weight_after", ascending=False)
        top_weights = selected.capital_weight_after.fillna(0.0).sort_values(ascending=False)
        scores = selected.entry_score.dropna().sort_values(ascending=False)
        gross_contrib = sec.gross_return_contribution
        cov = coverage.loc[prediction_date]
        row = exact.loc[economic_date]
        date_rows.append({
            "prediction_date": prediction_date,
            "execution_date": economic_date,
            "nav": float(row.nav),
            "portfolio_gross_return": float(gross_contrib.sum()),
            "transaction_cost": float(row.transaction_cost),
            "cost_effect_return": float(-row.transaction_cost / prior_nav.loc[economic_date]),
            "portfolio_net_return": float(row.daily_return),
            "turnover": float(row.turnover),
            "high_turnover_period": bool(row.turnover >= turnover_q90),
            "eligible_universe_size": int(cov.eligible_count),
            "13f_vintage": str(cov["13f_vintage"]),
            "13f_effective_date": cov["13f_effective_date"],
            "top20_capital_weight": float(top_weights.sum()),
            "top1_capital_weight_share": float(top_weights.head(1).sum()),
            "top5_capital_weight_share": float(top_weights.head(5).sum()),
            "top10_capital_weight_share": float(top_weights.head(10).sum()),
            "security_weight_hhi": float(np.square(top_weights).sum()),
            "sector_concentration": np.nan,
            "sector_concentration_status": SECTOR_STATUS,
            "winner_count": int(gross_contrib.gt(0).sum()),
            "loser_count": int(gross_contrib.lt(0).sum()),
            "simultaneous_severe_loss_count": int(sec.tail_loss_flag.sum()),
            "worst_holding_ticker": str(sec.loc[gross_contrib.idxmin(), "ticker"]) if len(sec) else "NA",
            "worst_holding_contribution": float(gross_contrib.min()) if len(sec) else np.nan,
            "best_holding_ticker": str(sec.loc[gross_contrib.idxmax(), "ticker"]) if len(sec) else "NA",
            "best_holding_contribution": float(gross_contrib.max()) if len(sec) else np.nan,
            "qqq_open_to_open_return": finite_float(qqq_return.get(economic_date, np.nan)),
            "score_top1_vs_top20_spread": float(scores.iloc[0] - scores.iloc[-1]) if len(scores) == TOP_N else np.nan,
            "score_top5_abs_share": float(scores.head(5).abs().sum() / scores.abs().sum()) if len(scores) and scores.abs().sum() > 0 else np.nan,
            "score_dispersion": float(scores.std(ddof=0)) if len(scores) else np.nan,
        })
    date_frame = pd.DataFrame(date_rows)
    date_frame["best_period_rank"] = date_frame.portfolio_net_return.rank(method="first", ascending=False).astype(int)
    date_frame["worst_period_rank"] = date_frame.portfolio_net_return.rank(method="first", ascending=True).astype(int)
    date_frame["top10_best_period"] = date_frame.best_period_rank.le(10)
    date_frame["top10_worst_period"] = date_frame.worst_period_rank.le(10)
    return positions.sort_values(["economic_date", "ticker"]).reset_index(drop=True), date_frame


def winner_loser_attribution(predictions: pd.DataFrame) -> tuple[pd.DataFrame, str, dict[str, float]]:
    rows: list[dict[str, Any]] = []
    for date, day0 in predictions.groupby("prediction_date", sort=True):
        day = day0.loc[np.isfinite(day0.target)].copy()
        require(len(day) >= TOP_N, "WINNER_LOSER_DATE_BELOW_TOP20", date)
        day["realized_percentile"] = day.target.rank(method="first", pct=True)
        day["upper_decile"] = day.realized_percentile.gt(0.90)
        day["lower_decile"] = day.realized_percentile.le(0.10)
        top = day.loc[day.selected_top20]
        upper_count = int(day.upper_decile.sum())
        lower_count = int(day.lower_decile.sum())
        top_upper = int(top.upper_decile.sum())
        top_lower = int(top.lower_decile.sum())
        rows.append({
            "prediction_date": date,
            "13f_vintage": str(day["13f_vintage"].iloc[0]),
            "eligible_universe_size": len(day),
            "top20_mean_forward_target_return": float(top.target.mean()),
            "top20_median_forward_target_return": float(top.target.median()),
            "eligible_mean_forward_target_return": float(day.target.mean()),
            "eligible_median_forward_target_return": float(day.target.median()),
            "eligible_q10_forward_target_return": float(day.target.quantile(0.10)),
            "eligible_q90_forward_target_return": float(day.target.quantile(0.90)),
            "top20_vs_universe_spread": float(top.target.mean() - day.target.mean()),
            "top20_winner_hit_rate": float(top.target.gt(0).mean()),
            "top20_loser_rate": float(top.target.lt(0).mean()),
            "eligible_winner_hit_rate": float(day.target.gt(0).mean()),
            "upper_decile_winner_count": upper_count,
            "upper_decile_winner_capture_count": top_upper,
            "upper_decile_winner_capture_rate": float(top_upper / upper_count) if upper_count else np.nan,
            "top20_upper_decile_exposure": float(top_upper / TOP_N),
            "lower_decile_loser_count": lower_count,
            "lower_decile_loser_inclusion_count": top_lower,
            "lower_decile_loser_inclusion_rate": float(top_lower / lower_count) if lower_count else np.nan,
            "top20_lower_decile_exposure": float(top_lower / TOP_N),
            "winner_inclusion_excess_vs_10pct": float(top_upper / TOP_N - 0.10),
            "loser_avoidance_excess_vs_10pct": float(0.10 - top_lower / TOP_N),
        })
    frame = pd.DataFrame(rows)
    winner_signal = float(frame.top20_upper_decile_exposure.mean() - 0.10)
    avoidance_signal = float(0.10 - frame.top20_lower_decile_exposure.mean())
    spread = float(frame.top20_vs_universe_spread.mean())
    if winner_signal > 0 and avoidance_signal > 0:
        characterization = "BOTH"
    elif winner_signal > 0 and avoidance_signal <= 0:
        characterization = "WINNER_INCLUSION"
    elif winner_signal <= 0 and avoidance_signal > 0:
        characterization = "LOSER_AVOIDANCE"
    elif spread > 0:
        characterization = "DIFFUSE_EDGE"
    else:
        characterization = "INCONCLUSIVE"
    summary = {"winner_signal": winner_signal, "avoidance_signal": avoidance_signal, "mean_spread": spread}
    return frame, characterization, summary


def drawdown_forensic(security: pd.DataFrame, dates: pd.DataFrame) -> dict[str, Any]:
    nav = dates.set_index("execution_date").nav.sort_index()
    running_peak = nav.cummax()
    drawdown = nav / running_peak - 1.0
    trough = pd.Timestamp(drawdown.idxmin())
    peak = pd.Timestamp(nav.loc[:trough].idxmax())
    peak_nav = float(nav.loc[peak])
    recovery_dates = nav.loc[nav.index > trough]
    recovered = recovery_dates.loc[recovery_dates.ge(peak_nav - 1e-12)]
    recovery = pd.Timestamp(recovered.index[0]) if len(recovered) else None
    mask = dates.execution_date.gt(peak) & dates.execution_date.le(trough)
    dd_dates = dates.loc[mask].copy()
    require(len(dd_dates) > 0, "EMPTY_MAX_DRAWDOWN_WINDOW")
    dd_security = security.loc[security.economic_date.isin(dd_dates.execution_date)].copy()
    dd_returns = dd_dates.set_index("execution_date").portfolio_net_return
    future = np.ones(len(dd_returns), dtype=float)
    running = 1.0
    values = dd_returns.to_numpy(float)
    for index in range(len(values) - 1, -1, -1):
        future[index] = running
        running *= 1.0 + values[index]
    multiplier = pd.Series(future, index=pd.DatetimeIndex(dd_returns.index))
    dd_security["drawdown_link_multiplier"] = dd_security.economic_date.map(multiplier)
    for column in ("gross_return_contribution", "cost_return_contribution", "net_return_contribution"):
        dd_security[f"linked_{column}_drawdown"] = dd_security[column] * dd_security.drawdown_link_multiplier
    dd_date_rows = dd_security.groupby("economic_date", as_index=False).agg(
        gross_contribution=("linked_gross_return_contribution_drawdown", "sum"),
        cost_contribution=("linked_cost_return_contribution_drawdown", "sum"),
        net_contribution=("linked_net_return_contribution_drawdown", "sum"),
        simultaneous_losers=("gross_return_contribution", lambda x: int((x < 0).sum())),
        severe_individual_losses=("tail_loss_flag", "sum"),
    )
    dd_date_rows = dd_date_rows.merge(
        dd_dates[["execution_date", "prediction_date", "13f_vintage", "turnover", "security_weight_hhi", "top1_capital_weight_share", "top5_capital_weight_share", "score_top1_vs_top20_spread", "qqq_open_to_open_return"]],
        left_on="economic_date", right_on="execution_date", how="left", validate="one_to_one",
    ).drop(columns="execution_date")
    dd_security_group = dd_security.groupby("ticker", as_index=False).agg(
        gross_contribution=("linked_gross_return_contribution_drawdown", "sum"),
        cost_contribution=("linked_cost_return_contribution_drawdown", "sum"),
        net_contribution=("linked_net_return_contribution_drawdown", "sum"),
        selected_period_count=("selected_previous_top20", "sum"),
        severe_loss_count=("tail_loss_flag", "sum"),
        average_capital_weight=("capital_weight_before", "mean"),
    ).sort_values("net_contribution")
    depth = float(nav.loc[trough] / nav.loc[peak] - 1.0)
    require(abs(float(dd_security_group.net_contribution.sum()) - depth) <= 3e-12, "DRAWDOWN_LINKED_CONTRIBUTION_MISMATCH")
    qqq_move = float(np.prod(1.0 + dd_dates.qqq_open_to_open_return.fillna(0.0)) - 1.0)
    corr = float(dd_dates.portfolio_net_return.corr(dd_dates.qqq_open_to_open_return))
    qvar = float(np.var(dd_dates.qqq_open_to_open_return.to_numpy(float), ddof=0))
    beta = float(np.cov(dd_dates.portfolio_net_return, dd_dates.qqq_open_to_open_return, ddof=0)[0, 1] / qvar) if qvar > 0 else np.nan
    negative_security_share_top5 = negative_share(dd_security_group.net_contribution, 5)
    negative_date_share_top5 = negative_share(dd_date_rows.net_contribution, 5)
    cost_share = abs(float(dd_security_group.cost_contribution.sum())) / abs(depth) if depth < 0 else np.nan
    broad_failure = float(dd_date_rows.simultaneous_losers.mean() / TOP_N)
    if corr >= 0.60 and qqq_move < 0 and broad_failure >= 0.55:
        classification = "A_BROAD_MARKET_SYSTEMATIC_DRAWDOWN" if negative_security_share_top5 < 0.50 else "F_MIXED"
    elif negative_security_share_top5 >= 0.50:
        classification = "C_FEW_STOCK_TAIL_LOSSES"
    elif broad_failure >= 0.55:
        classification = "D_BROAD_TOP20_SELECTION_FAILURE"
    elif cost_share >= 0.20:
        classification = "E_TURNOVER_EXECUTION_DRAG"
    else:
        classification = "F_MIXED"
    summary = {
        "peak_date": peak,
        "trough_date": trough,
        "drawdown_depth": depth,
        "recovery_date": recovery,
        "gross_loss_contribution": float(dd_security_group.gross_contribution.sum()),
        "cost_contribution": float(dd_security_group.cost_contribution.sum()),
        "net_loss_contribution": float(dd_security_group.net_contribution.sum()),
        "average_turnover": float(dd_dates.turnover.mean()),
        "turnover_spike_count": int(dd_dates.high_turnover_period.sum()),
        "average_simultaneous_losers": float(dd_date_rows.simultaneous_losers.mean()),
        "severe_individual_stock_loss_count": int(dd_date_rows.severe_individual_losses.sum()),
        "qqq_move": qqq_move,
        "portfolio_qqq_correlation": corr,
        "beta_like_vs_qqq": beta,
        "top5_losing_security_share": negative_security_share_top5,
        "top5_losing_date_share": negative_date_share_top5,
        "cost_share_of_drawdown": cost_share,
        "broad_loser_fraction": broad_failure,
        "classification": classification,
    }
    sector = pd.DataFrame([{
        "sector": "NA_UNAVAILABLE", "status": SECTOR_STATUS,
        "gross_contribution": np.nan, "cost_contribution": np.nan, "net_contribution": np.nan,
    }])
    return {"summary": summary, "security": dd_security_group, "dates": dd_date_rows, "sector": sector}


def sector_attribution() -> pd.DataFrame:
    return pd.DataFrame([{
        "sector": "NA_UNAVAILABLE",
        "status": SECTOR_STATUS,
        "average_portfolio_weight": np.nan,
        "cumulative_gross_contribution": np.nan,
        "cumulative_net_contribution": np.nan,
        "contribution_to_positive_pnl": np.nan,
        "contribution_to_negative_pnl": np.nan,
        "contribution_during_max_drawdown": np.nan,
        "top20_selection_count": np.nan,
        "average_forward_return": np.nan,
        "hit_rate": np.nan,
        "worst_tail_rate": np.nan,
        "concentration": np.nan,
        "exposure_vs_realization_diagnostic": "SKIPPED",
    }])


def vintage_attribution(security: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for vintage, day in dates.groupby("13f_vintage", sort=False):
        metrics = metric_set(day.portfolio_net_return)
        sec = security.loc[security.prediction_date.isin(day.prediction_date)]
        contributors = sec.groupby("ticker").linked_net_return_contribution_full_sample.sum().sort_values()
        rows.append({
            "13f_vintage": vintage,
            "effective_date_start": str(day["13f_effective_date"].min().date()),
            "prediction_date_start": str(day.prediction_date.min().date()),
            "prediction_date_end": str(day.prediction_date.max().date()),
            "prediction_date_count": len(day),
            "average_eligible_universe_size": float(day.eligible_universe_size.mean()),
            "cumulative_return": metrics["cumulative_return"],
            "sharpe": metrics["sharpe"] if len(day) >= 20 else np.nan,
            "max_drawdown": metrics["max_drawdown"],
            "hit_rate": float(day.portfolio_net_return.gt(0).mean()),
            "average_turnover": float(day.turnover.mean()),
            "average_security_weight_hhi": float(day.security_weight_hhi.mean()),
            "average_sector_concentration": np.nan,
            "sector_concentration_status": SECTOR_STATUS,
            "best_contributor": str(contributors.index[-1]) if len(contributors) else "NA",
            "best_contributor_linked_return": float(contributors.iloc[-1]) if len(contributors) else np.nan,
            "worst_contributor": str(contributors.index[0]) if len(contributors) else "NA",
            "worst_contributor_linked_return": float(contributors.iloc[0]) if len(contributors) else np.nan,
        })
    return pd.DataFrame(rows)


def execution_attribution(dates: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    frame = dates[[
        "prediction_date", "execution_date", "portfolio_gross_return", "transaction_cost",
        "cost_effect_return", "portfolio_net_return", "turnover", "high_turnover_period",
    ]].copy()
    frame["gross_nav"] = (1.0 + frame.portfolio_gross_return).cumprod()
    frame["net_nav"] = (1.0 + frame.portfolio_net_return).cumprod()
    frame["compounded_cost_drag"] = frame.gross_nav - frame.net_nav
    gross_cumulative = float(frame.gross_nav.iloc[-1] - 1.0)
    net_cumulative = float(frame.net_nav.iloc[-1] - 1.0)
    drag = gross_cumulative - net_cumulative
    correlation = float(frame.turnover.corr(frame.portfolio_net_return))
    summary = {
        "gross_cumulative_return": gross_cumulative,
        "net_cumulative_return": net_cumulative,
        "compounded_cost_drag": drag,
        "transaction_cost_share_of_gross_edge": float(drag / gross_cumulative) if gross_cumulative > 0 else np.nan,
        "total_turnover": float(frame.turnover.sum()),
        "average_turnover": float(frame.turnover.mean()),
        "high_turnover_period_count": int(frame.high_turnover_period.sum()),
        "turnover_net_return_correlation": correlation,
    }
    return frame, summary


def concentration_diagnostics(security: pd.DataFrame, dates: pd.DataFrame, dd: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, float]]:
    ticker = security.groupby("ticker").linked_net_return_contribution_full_sample.sum()
    date_values = dates.set_index("prediction_date").portfolio_net_return
    held = security.loc[security.shares_before.gt(0) & security.holding_open_to_open_return.notna()]
    metrics = {
        "top1_positive_security_contribution_share": positive_share(ticker, 1),
        "top5_positive_security_contribution_share": positive_share(ticker, 5),
        "top10_positive_security_contribution_share": positive_share(ticker, 10),
        "top1_negative_security_loss_share": negative_share(ticker, 1),
        "top5_negative_security_loss_share": negative_share(ticker, 5),
        "top10_negative_security_loss_share": negative_share(ticker, 10),
        "top1_positive_date_contribution_share": positive_share(date_values, 1),
        "top5_positive_date_contribution_share": positive_share(date_values, 5),
        "top10_positive_date_contribution_share": positive_share(date_values, 10),
        "top1_negative_date_loss_share": negative_share(date_values, 1),
        "top5_negative_date_loss_share": negative_share(date_values, 5),
        "top10_negative_date_loss_share": negative_share(date_values, 10),
        "median_security_linked_contributor": float(ticker.median()),
        "winner_hit_rate": float(held.holding_open_to_open_return.gt(0).mean()),
        "loser_rate": float(held.holding_open_to_open_return.lt(0).mean()),
        "tail_loss_frequency_le_minus_10pct": float(held.holding_open_to_open_return.le(-0.10).mean()),
        "average_top1_capital_weight_share": float(dates.top1_capital_weight_share.mean()),
        "average_top5_capital_weight_share": float(dates.top5_capital_weight_share.mean()),
        "average_top10_capital_weight_share": float(dates.top10_capital_weight_share.mean()),
        "average_security_weight_hhi": float(dates.security_weight_hhi.mean()),
        "average_score_top1_vs_top20_spread": float(dates.score_top1_vs_top20_spread.mean()),
        "average_score_top5_abs_share": float(dates.score_top5_abs_share.mean()),
        "average_score_dispersion": float(dates.score_dispersion.mean()),
        "top_sector_loss_share": np.nan,
        "max_drawdown_top5_security_loss_share": dd["summary"]["top5_losing_security_share"],
        "max_drawdown_top5_date_loss_share": dd["summary"]["top5_losing_date_share"],
    }
    rows = []
    for name, value in metrics.items():
        dimension = "SECURITY" if "security" in name else "DATE" if "date" in name else "SCORE" if "score" in name else "SECTOR" if "sector" in name else "OTHER"
        rows.append({"dimension": dimension, "metric": name, "value": value, "status": SECTOR_STATUS if dimension == "SECTOR" else "PASS"})
    return pd.DataFrame(rows), metrics


def risk_taxonomy(
    concentration: dict[str, float],
    dd: dict[str, Any],
    execution: dict[str, float],
    edge: dict[str, float],
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    d = dd["summary"]
    rows = [
        {
            "risk_source": "INDIVIDUAL_STOCK_TAIL",
            "evidence_strength": "HIGH" if d["top5_losing_security_share"] >= 0.40 else "MEDIUM",
            "estimated_contribution": d["top5_losing_security_share"],
            "contribution_unit": "TOP5_SHARE_OF_DRAWDOWN_SECURITY_LOSSES",
            "frequency": concentration["tail_loss_frequency_le_minus_10pct"],
            "severity": d["severe_individual_stock_loss_count"],
            "persistence": "EPISODIC",
            "pre_event_predictability": "UNKNOWN_REQUIRES_SEPARATE_PRE_EVENT_TEST",
            "potentially_controllable_without_destroying_winners": "UNKNOWN",
            "evidence": f"MaxDD top5 losing securities share={d['top5_losing_security_share']:.6f}; <=-10% holding events={d['severe_individual_stock_loss_count']}",
        },
        {
            "risk_source": "SECTOR_CONCENTRATION",
            "evidence_strength": "LOW",
            "estimated_contribution": np.nan,
            "contribution_unit": "NA",
            "frequency": np.nan,
            "severity": np.nan,
            "persistence": "UNKNOWN",
            "pre_event_predictability": "NOT_ASSESSED",
            "potentially_controllable_without_destroying_winners": "NOT_ASSESSED",
            "evidence": SECTOR_STATUS,
        },
        {
            "risk_source": "MARKET_SYSTEMATIC",
            "evidence_strength": "HIGH" if d["portfolio_qqq_correlation"] >= 0.60 and d["qqq_move"] < 0 else "MEDIUM" if d["qqq_move"] < 0 else "LOW",
            "estimated_contribution": d["qqq_move"],
            "contribution_unit": "QQQ_MOVE_DURING_A2_MAXDD_NOT_CAUSAL_DECOMPOSITION",
            "frequency": float(d["portfolio_qqq_correlation"]),
            "severity": d["beta_like_vs_qqq"],
            "persistence": "MAXDD_WINDOW",
            "pre_event_predictability": "MARKET_STATE_OBSERVABLE_CONTEMPORANEOUSLY_NOT_PREDICTIVELY_TESTED",
            "potentially_controllable_without_destroying_winners": "UNKNOWN",
            "evidence": f"QQQ move={d['qqq_move']:.6f}; correlation={d['portfolio_qqq_correlation']:.6f}; beta-like={d['beta_like_vs_qqq']:.6f}",
        },
        {
            "risk_source": "CROSS_SECTIONAL_SELECTION_ERROR",
            "evidence_strength": "HIGH" if d["broad_loser_fraction"] >= 0.55 else "MEDIUM",
            "estimated_contribution": d["broad_loser_fraction"],
            "contribution_unit": "MEAN_SIMULTANEOUS_LOSER_FRACTION_DURING_MAXDD",
            "frequency": d["average_simultaneous_losers"],
            "severity": d["drawdown_depth"],
            "persistence": "MAXDD_WINDOW",
            "pre_event_predictability": "UNKNOWN_REQUIRES_FROZEN_PRE_EVENT_DIAGNOSTIC",
            "potentially_controllable_without_destroying_winners": "UNKNOWN",
            "evidence": f"Mean simultaneous loser fraction={d['broad_loser_fraction']:.6f}; forward-target spread={edge['mean_spread']:.6f}",
        },
        {
            "risk_source": "PORTFOLIO_CONCENTRATION",
            "evidence_strength": "MEDIUM" if concentration["top5_negative_security_loss_share"] >= 0.40 else "LOW",
            "estimated_contribution": concentration["top5_negative_security_loss_share"],
            "contribution_unit": "TOP5_SHARE_OF_FULL_SAMPLE_SECURITY_LOSSES",
            "frequency": concentration["average_top5_capital_weight_share"],
            "severity": concentration["top5_positive_security_contribution_share"],
            "persistence": "DAILY_EQUAL_WEIGHT_TARGET_WITH_REALIZED_PNL_CONCENTRATION",
            "pre_event_predictability": "CAPITAL_WEIGHT_OBSERVABLE; PNL_CONCENTRATION_NOT_KNOWN_PRE_EVENT",
            "potentially_controllable_without_destroying_winners": "UNKNOWN_AND_WINNER_DAMAGE_RISK_MATERIAL",
            "evidence": f"Avg top5 capital={concentration['average_top5_capital_weight_share']:.6f}; top5 loss share={concentration['top5_negative_security_loss_share']:.6f}",
        },
        {
            "risk_source": "TURNOVER_EXECUTION",
            "evidence_strength": "HIGH" if execution["transaction_cost_share_of_gross_edge"] >= 0.50 else "MEDIUM" if execution["transaction_cost_share_of_gross_edge"] >= 0.20 else "LOW",
            "estimated_contribution": execution["transaction_cost_share_of_gross_edge"],
            "contribution_unit": "COMPOUNDED_COST_DRAG_SHARE_OF_GROSS_EDGE",
            "frequency": execution["average_turnover"],
            "severity": d["cost_share_of_drawdown"],
            "persistence": "DAILY",
            "pre_event_predictability": "TURNOVER_AND_FROZEN_COST_CONVENTION_OBSERVABLE",
            "potentially_controllable_without_destroying_winners": "UNKNOWN_REQUIRES_SEPARATE_CAUSAL_TEST",
            "evidence": f"Gross-edge cost share={execution['transaction_cost_share_of_gross_edge']:.6f}; MaxDD cost share={d['cost_share_of_drawdown']:.6f}",
        },
        {
            "risk_source": "DATA_COVERAGE",
            "evidence_strength": "LOW",
            "estimated_contribution": 0.0,
            "contribution_unit": "IDENTIFIED_ECONOMIC_MISMATCH_COUNT",
            "frequency": 0.0,
            "severity": 0.0,
            "persistence": "NO_IDENTIFIED_ECONOMIC_OR_PIT_VIOLATION",
            "pre_event_predictability": "AUDITABLE",
            "potentially_controllable_without_destroying_winners": "NOT_APPLICABLE",
            "evidence": "Economic identity, eligible mask, price events, and PIT checks passed; sector metadata remains unavailable for attribution only.",
        },
        {
            "risk_source": "OTHER",
            "evidence_strength": "LOW",
            "estimated_contribution": np.nan,
            "contribution_unit": "NA",
            "frequency": np.nan,
            "severity": np.nan,
            "persistence": "UNKNOWN",
            "pre_event_predictability": "UNKNOWN",
            "potentially_controllable_without_destroying_winners": "UNKNOWN",
            "evidence": "No separate residual cause defensibly identified.",
        },
    ]
    frame = pd.DataFrame(rows)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    frame["evidence_order"] = frame.evidence_strength.map(order)
    frame = frame.sort_values(["evidence_order", "risk_source"]).drop(columns="evidence_order").reset_index(drop=True)
    supported = frame.loc[frame.evidence_strength.ne("LOW")].risk_source.tolist()
    hypotheses: list[dict[str, str]] = []
    for index, risk in enumerate(supported[:3], start=1):
        evidence_text = str(frame.loc[frame.risk_source.eq(risk), "evidence"].iloc[0])
        hypotheses.append({
            "id": f"H{index}",
            "risk_source": risk,
            "evidence": evidence_text,
            "why_it_matters": "This source is material in the frozen attribution and may explain instability without changing the A2 model in this study.",
            "what_must_be_tested_next": "Run a separately authorized, pre-specified pre-event diagnostic using only information available before each event and measure winner damage explicitly.",
            "what_must_not_yet_be_concluded": "No deployable threshold, cap, gate, stop, blend, or model change is supported by this retrospective attribution alone.",
        })
    return frame, hypotheses


def format_hypotheses(hypotheses: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for item in hypotheses:
        lines += [
            f"### {item['id']}", "",
            f"Risk source: {item['risk_source']}", "",
            f"Evidence: {item['evidence']}", "",
            f"Why it matters: {item['why_it_matters']}", "",
            f"What must be tested next: {item['what_must_be_tested_next']}", "",
            f"What must NOT yet be concluded: {item['what_must_not_yet_be_concluded']}", "",
        ]
    return lines


def render_drawdown_report(summary: dict[str, Any], hypotheses: list[dict[str, str]]) -> str:
    recovery = str(summary["recovery_date"].date()) if summary["recovery_date"] is not None else "NOT_RECOVERED"
    lines = [
        "# A2-HGB 2026 maximum drawdown forensic", "",
        f"Evidence status: `{EVIDENCE_STATUS}`. This is retrospective attribution, not a pristine holdout.", "",
        "## Automatically identified episode", "",
        f"- Peak: {summary['peak_date'].date()}",
        f"- Trough: {summary['trough_date'].date()}",
        f"- Depth: {summary['drawdown_depth']:.10f}",
        f"- Recovery: {recovery}",
        f"- Classification: `{summary['classification']}`", "",
        "## Compounding-aware decomposition", "",
        f"- Linked gross contribution: {summary['gross_loss_contribution']:.10f}",
        f"- Linked transaction-cost contribution: {summary['cost_contribution']:.10f}",
        f"- Linked net contribution: {summary['net_loss_contribution']:.10f}",
        f"- Cost share of drawdown magnitude: {summary['cost_share_of_drawdown']:.6f}",
        f"- Top-5 losing securities share: {summary['top5_losing_security_share']:.6f}",
        f"- Top-5 losing dates share: {summary['top5_losing_date_share']:.6f}", "",
        "## Breadth, turnover, and market co-movement", "",
        f"- Average simultaneous losers: {summary['average_simultaneous_losers']:.3f} of {TOP_N}",
        f"- Severe individual holding losses (open-to-open <= -10%): {summary['severe_individual_stock_loss_count']}",
        f"- Average turnover: {summary['average_turnover']:.6f}",
        f"- Full-sample top-decile turnover spike count inside MaxDD: {summary['turnover_spike_count']}",
        f"- Canonical QQQ move: {summary['qqq_move']:.10f}",
        f"- A2/QQQ daily correlation: {summary['portfolio_qqq_correlation']:.6f}",
        f"- Beta-like covariance diagnostic: {summary['beta_like_vs_qqq']:.6f}", "",
        "Sector decomposition is skipped because no authoritative/PIT sector lineage was available. This absence is not evidence that sector crowding did or did not matter.", "",
        "## Next research hypotheses (not rules)", "",
        *format_hypotheses(hypotheses),
    ]
    return "\n".join(lines)


def render_main_report(
    status: dict[str, Any],
    replay: dict[str, Any],
    concentration: dict[str, float],
    execution: dict[str, float],
    dd: dict[str, Any],
    vintage: pd.DataFrame,
    hypotheses: list[dict[str, str]],
) -> str:
    d = dd["summary"]
    top = pd.read_csv(R2A_OUT / "2026_retrospective_predictive_metrics.csv").set_index("model").loc[MODEL]
    recovery = str(d["recovery_date"].date()) if d["recovery_date"] is not None else "NOT_RECOVERED"
    lines = [
        "# A2 Attribution R1 — 2026 YTD", "",
        f"Status: `{status['A2_ATTRIBUTION_R1_2026_YTD_STATUS']}`. Evidence status: `{EVIDENCE_STATUS}`.", "",
        "This report explains the frozen authoritative A2-HGB path. It performs no model fitting, parameter search, risk-rule search, eligibility change, or deployment action.", "",
        "## Frozen identity", "",
        f"The deterministic accounting replay matched the frozen R2A summary with maximum numeric error {replay['max_error']:.3e}. Cumulative return is {replay['metrics'].cumulative_return:.6%}, Sharpe {replay['metrics'].sharpe:.6f}, MaxDD {replay['metrics'].max_drawdown:.6%}, Rank IC {top.rank_ic:.6f}, and NDCG@20 {top.ndcg_at_20:.6f}.", "",
        "## Where gains and losses came from", "",
        f"Top-5 positive securities supplied {concentration['top5_positive_security_contribution_share']:.2%} of positive linked security contribution; top-5 losing securities supplied {concentration['top5_negative_security_loss_share']:.2%} of linked security losses. Top-5 losing dates supplied {concentration['top5_negative_date_loss_share']:.2%} of negative daily return mass.", "",
        f"The edge characterization is `{status['A2_EDGE_CHARACTERIZATION']}`. Mean Top20-minus-universe frozen forward-target spread is {status['WINNER_LOSER_MEAN_SPREAD']:.6f}; this is descriptive realized-outcome evidence, not a selection rule.", "",
        "## Maximum drawdown", "",
        f"The automatic peak-to-trough episode ran {d['peak_date'].date()} to {d['trough_date'].date()}, reached {d['drawdown_depth']:.6%}, and recovery was {recovery}. The episode is classified `{d['classification']}` under the fixed diagnostic rubric.", "",
        f"QQQ moved {d['qqq_move']:.6%} in the same interval, A2/QQQ daily correlation was {d['portfolio_qqq_correlation']:.3f}, mean simultaneous losers were {d['average_simultaneous_losers']:.2f}, and top-5 losing securities accounted for {d['top5_losing_security_share']:.2%} of drawdown security losses.", "",
        "## Execution and concentration", "",
        f"Gross compounded return was {execution['gross_cumulative_return']:.6%}; net compounded return was {execution['net_cumulative_return']:.6%}; compounded cost drag was {execution['compounded_cost_drag']:.6%}, or {execution['transaction_cost_share_of_gross_edge']:.2%} of gross edge.", "",
        f"Average Top5 capital weight was {concentration['average_top5_capital_weight_share']:.2%}. Capital weight is reported separately from return contribution throughout; equal-ish capital allocation did not imply equal realized PnL contribution.", "",
        "## 13F vintage", "",
        "| Vintage | Dates | Cumulative return | Sharpe | MaxDD | Worst contributor |", "|---|---:|---:|---:|---:|---|",
    ]
    for row in vintage.itertuples(index=False):
        lines.append(f"| {row._0 if hasattr(row, '_0') else row[0]} | {row.prediction_date_count} | {row.cumulative_return:.6f} | {row.sharpe:.6f} | {row.max_drawdown:.6f} | {row.worst_contributor} |")
    lines += [
        "", "Sector attribution is explicitly skipped due to insufficient authoritative sector lineage. No sector conclusion is inferred from `UNCLASSIFIED` placeholders.", "",
        "## Risk source taxonomy", "",
        f"Primary: `{status['PRIMARY_RISK_SOURCE']}`; secondary: `{status['SECONDARY_RISK_SOURCE']}`; tertiary: `{status['TERTIARY_RISK_SOURCE']}`.", "",
        "## Next research hypotheses (maximum three; not deployable rules)", "",
        *format_hypotheses(hypotheses),
        "## Stop condition", "",
        "`NEXT_AUTHORIZED_STEP=STOP_AND_REVIEW_ATTRIBUTION_R1`. No risk control, A2 change, R2 work, or deployment follows from this run.", "",
    ]
    return "\n".join(lines)


def run(output: Path) -> dict[str, Any]:
    require(ANTI_BLOAT_POLICY.is_file(), "ANTI_BLOAT_POLICY_MISSING")
    require(str(output.resolve()).startswith(str(RESULTS.resolve()) + os.sep), "OUTPUT_NOT_APPROVED_EXTERNAL_RESULTS_ROOT", output)
    require(not output.exists(), "AUTHORITATIVE_OUTPUT_ALREADY_EXISTS", output)
    inputs = load_authoritative_inputs()
    replay = replay_economic_path(inputs)
    security, dates = build_security_and_dates(inputs, replay)
    winner_loser, edge_characterization, edge_summary = winner_loser_attribution(inputs["predictions"])
    dd = drawdown_forensic(security, dates)
    sectors = sector_attribution()
    vintages = vintage_attribution(security, dates)
    execution, execution_summary = execution_attribution(dates)
    concentration, concentration_summary = concentration_diagnostics(security, dates, dd)
    taxonomy, hypotheses = risk_taxonomy(concentration_summary, dd, execution_summary, edge_summary)

    worst_vintage = str(vintages.sort_values(["cumulative_return", "13f_vintage"]).iloc[0]["13f_vintage"])
    ranked_risks = taxonomy.loc[taxonomy.evidence_strength.ne("LOW"), "risk_source"].tolist()
    ranked_risks += [risk for risk in taxonomy.risk_source if risk not in ranked_risks]
    primary, secondary, tertiary = (ranked_risks + ["NA", "NA", "NA"])[:3]
    full_positive = security.groupby("ticker").linked_net_return_contribution_full_sample.sum().sort_values(ascending=False)
    full_negative = full_positive.sort_values()
    dominant_positive_ticker = str(full_positive.index[0])
    dominant_negative_ticker = str(full_negative.index[0])
    date_concentrated = bool(concentration_summary["top5_negative_date_loss_share"] >= 0.50 or concentration_summary["top5_positive_date_contribution_share"] >= 0.50)
    dd_summary = dd["summary"]
    recovery_text = str(dd_summary["recovery_date"].date()) if dd_summary["recovery_date"] is not None else "NOT_RECOVERED"

    contract = {
        "run_id": RUN_ID,
        "task_type": "FORENSIC_ATTRIBUTION_DIAGNOSTIC_RESEARCH_ONLY",
        "evidence_status": EVIDENCE_STATUS,
        "authoritative_source": str(R2A_OUT),
        "authoritative_source_manifest_sha256": sha256(R2A_OUT / "manifest.json"),
        "model": MODEL,
        "economic_path": "EXACT_REPLAY_OF_FROZEN_R2A_TOP20_WITH_FROZEN_EXECUTION_ACCOUNTING",
        "security_contribution": "DAILY_MARKET_PNL_AND_ALLOCATED_COST_DIVIDED_BY_PRIOR_NAV; FRONGELLO_LINKED_FOR_CUMULATIVE_DECOMPOSITION",
        "capital_weight": "MARKED_SECURITY_CAPITAL_DIVIDED_BY_PRE_OR_POST_TRADE_NAV; NEVER_SUBSTITUTED_FOR_RETURN_CONTRIBUTION",
        "winner_loser_framework": "WITHIN_DATE_FIXED_TOP_DECILE_AND_BOTTOM_DECILE_OF_FROZEN_MATURED_FORWARD_TARGET; NO_QUANTILE_SEARCH",
        "drawdown": "AUTOMATIC_NAV_CUMULATIVE_PEAK_TO_GLOBAL_MINIMUM_DRAWDOWN_WITH_FIRST_SUBSEQUENT_RECOVERY",
        "tail_loss_definition": "HOLDING_OPEN_TO_OPEN_RETURN_LE_MINUS_10_PERCENT_FIXED_DESCRIPTIVE_RULE",
        "high_turnover_definition": "FULL_SAMPLE_EMPIRICAL_TOP_DECILE_FIXED_DESCRIPTIVE_SUMMARY_NOT_A_TRADING_RULE",
        "sector_attribution_status": SECTOR_STATUS,
        "market_attribution_status": MARKET_STATUS,
        "prohibitions": ["model_fit", "parameter_search", "risk_rule_search", "feature_selection", "eligibility_change", "deployment"],
        "2026_training_rows": 0,
        "model_fit_count": 0,
        "parameter_search_count": 0,
        "risk_rule_search_count": 0,
    }
    identity = {
        "A2_ECONOMIC_PATH_IDENTITY_STATUS": "PASS_EXACT_DETERMINISTIC_REPLAY_AGAINST_FROZEN_R2A_SUMMARY",
        "return_identity_max_abs_error": replay["max_error"],
        "final_nav": float(replay["path"].daily.nav.iloc[-1]),
        "frozen_cumulative_return": float(inputs["economic"].cumulative_return),
        "replayed_cumulative_return": float(replay["metrics"].cumulative_return),
        "turnover_total_frozen": float(inputs["economic"].turnover_total_one_way),
        "turnover_total_replayed": float(replay["path"].daily.turnover.sum()),
        "transaction_cost_frozen": float(inputs["economic"].transaction_cost),
        "transaction_cost_replayed": float(replay["path"].daily.transaction_cost.sum()),
        "prediction_date_start": str(inputs["dates"].min().date()),
        "prediction_date_end": str(inputs["dates"].max().date()),
        "execution_date_end": str(replay["execution_end"].date()),
        "date_count": len(inputs["dates"]),
        "metric_differences": replay["differences"],
        "r2a_manifest_sha256": sha256(R2A_OUT / "manifest.json"),
        "r2a_artifact_hashes": inputs["hashes"],
        "r2a_source_sha256": replay["r2a_source_sha256"],
        "execution_source_sha256": replay["execution_source_sha256"],
        "canonical_qqq_path": replay["pointer"]["canonical_qfq_path"],
        "canonical_qqq_snapshot_sha256": replay["pointer"]["canonical_qfq_sha256"],
        "pit_13f_temporal_violation_count": 0,
        "future_information_violation_count": 0,
        "eligibility_mask_change_count": 0,
        "missing_execution_price_event_count": 0,
    }
    status = {
        "A2_ATTRIBUTION_R1_2026_YTD_STATUS": "PASS_FORENSIC_ATTRIBUTION_COMPLETE",
        "A2_ECONOMIC_PATH_IDENTITY_STATUS": identity["A2_ECONOMIC_PATH_IDENTITY_STATUS"],
        "2026_YTD_EVIDENCE_STATUS": EVIDENCE_STATUS,
        "ATTRIBUTION_WINDOW_START": str(inputs["dates"].min().date()),
        "ATTRIBUTION_WINDOW_END": str(inputs["dates"].max().date()),
        "MAX_DRAWDOWN_PEAK_DATE": str(dd_summary["peak_date"].date()),
        "MAX_DRAWDOWN_TROUGH_DATE": str(dd_summary["trough_date"].date()),
        "MAX_DRAWDOWN_DEPTH": dd_summary["drawdown_depth"],
        "MAX_DRAWDOWN_RECOVERY_DATE": recovery_text,
        "MAX_DRAWDOWN_CLASSIFICATION": dd_summary["classification"],
        "TOP5_POSITIVE_SECURITY_CONTRIBUTION_SHARE": concentration_summary["top5_positive_security_contribution_share"],
        "TOP5_NEGATIVE_SECURITY_LOSS_SHARE": concentration_summary["top5_negative_security_loss_share"],
        "TOP5_NEGATIVE_DATE_LOSS_SHARE": concentration_summary["top5_negative_date_loss_share"],
        "TOP5_POSITIVE_DATE_CONTRIBUTION_SHARE": concentration_summary["top5_positive_date_contribution_share"],
        "DOMINANT_POSITIVE_SECURITY": dominant_positive_ticker,
        "DOMINANT_NEGATIVE_SECURITY": dominant_negative_ticker,
        "DOMINANT_POSITIVE_SECTOR": "NA_SKIPPED",
        "DOMINANT_NEGATIVE_SECTOR": "NA_SKIPPED",
        "SECTOR_ATTRIBUTION_STATUS": SECTOR_STATUS,
        "MARKET_ATTRIBUTION_STATUS": MARKET_STATUS,
        "WORST_13F_VINTAGE": worst_vintage,
        "A2_EDGE_CHARACTERIZATION": edge_characterization,
        "WINNER_LOSER_MEAN_SPREAD": edge_summary["mean_spread"],
        "TRANSACTION_COST_SHARE_OF_GROSS_EDGE": execution_summary["transaction_cost_share_of_gross_edge"],
        "DATE_CONCENTRATED_RISK": date_concentrated,
        "PRIMARY_RISK_SOURCE": primary,
        "SECONDARY_RISK_SOURCE": secondary,
        "TERTIARY_RISK_SOURCE": tertiary,
        "NEXT_RESEARCH_HYPOTHESIS_COUNT": len(hypotheses),
        "NEXT_RESEARCH_HYPOTHESES": hypotheses,
        "2026_TRAINING_ROWS": 0,
        "MODEL_FIT_COUNT": 0,
        "PARAMETER_SEARCH_COUNT": 0,
        "RISK_RULE_SEARCH_COUNT": 0,
        "ELIGIBILITY_MASK_CHANGE_COUNT": 0,
        "FUTURE_INFORMATION_VIOLATION_COUNT": 0,
        "PIT_13F_TEMPORAL_VIOLATION_COUNT": 0,
        "SHARED_SOURCE_CHANGE_REQUIRED": False,
        "DEPLOYMENT_STATUS": "NOT_AUTHORIZED",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_ATTRIBUTION_R1",
    }

    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "attribution_contract.json", contract)
    atomic_json(output / "a2_identity_audit.json", identity)
    security_output_columns = [
        "prediction_date", "economic_date", "gross_source_prediction_date", "ticker", "entry_exit_status",
        "selected_current_top20", "selected_previous_top20", "entry_rank", "entry_score", "gross_source_rank",
        "gross_source_score", "forward_target_return", "target_end_date", "13f_vintage", "13f_effective_date",
        "gross_source_13f_vintage", "eligible_count", "holding_duration_sessions", "shares_before", "shares_after",
        "capital_weight_before", "capital_weight_after", "holding_open_to_open_return", "market_pnl", "transaction_cost",
        "gross_return_contribution", "cost_return_contribution", "net_return_contribution",
        "linked_gross_return_contribution_full_sample", "linked_cost_return_contribution_full_sample",
        "linked_net_return_contribution_full_sample", "tail_loss_flag", "sector", "sector_lineage_status",
        "return_contribution_definition", "capital_weight_definition",
    ]
    atomic_csv(output / "security_pnl_attribution.csv", security[security_output_columns])
    atomic_csv(output / "date_level_attribution.csv", dates)
    atomic_csv(output / "sector_attribution.csv", sectors)
    atomic_csv(output / "13f_vintage_attribution.csv", vintages)
    atomic_csv(output / "winner_loser_attribution.csv", winner_loser)
    atomic_csv(output / "execution_cost_attribution.csv", execution)
    atomic_csv(output / "concentration_diagnostics.csv", concentration)
    atomic_csv(output / "max_drawdown_security_contribution.csv", dd["security"])
    atomic_csv(output / "max_drawdown_date_contribution.csv", dd["dates"])
    atomic_csv(output / "max_drawdown_sector_contribution.csv", dd["sector"])
    atomic_csv(output / "risk_source_taxonomy.csv", taxonomy)
    (output / "max_drawdown_forensic.md").write_text(render_drawdown_report(dd_summary, hypotheses), encoding="utf-8")
    (output / "attribution_report.md").write_text(
        render_main_report(status, replay, concentration_summary, execution_summary, dd, vintages, hypotheses), encoding="utf-8"
    )
    atomic_json(output / "status.json", status)
    require(all((output / name).is_file() for name in REQUIRED_OUTPUTS), "REQUIRED_OUTPUT_MISSING")
    entries = [
        {"artifact": name, "sha256": sha256(output / name), "bytes": (output / name).stat().st_size}
        for name in REQUIRED_OUTPUTS
    ]
    atomic_json(output / "manifest.json", {
        "run_id": RUN_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_count_excluding_self": len(entries),
        "self_hash_excluded_because_recursive": True,
        "artifacts": entries,
        "model_fit_count": 0,
        "parameter_search_count": 0,
        "risk_rule_search_count": 0,
        "eligibility_mask_change_count": 0,
        "shared_source_change_required": False,
    })
    return status


def print_status(status: dict[str, Any]) -> None:
    keys = (
        "A2_ATTRIBUTION_R1_2026_YTD_STATUS",
        "A2_ECONOMIC_PATH_IDENTITY_STATUS",
        "ATTRIBUTION_WINDOW_START",
        "ATTRIBUTION_WINDOW_END",
        "MAX_DRAWDOWN_PEAK_DATE",
        "MAX_DRAWDOWN_TROUGH_DATE",
        "MAX_DRAWDOWN_DEPTH",
        "MAX_DRAWDOWN_RECOVERY_DATE",
        "TOP5_POSITIVE_SECURITY_CONTRIBUTION_SHARE",
        "TOP5_NEGATIVE_SECURITY_LOSS_SHARE",
        "TOP5_NEGATIVE_DATE_LOSS_SHARE",
        "DOMINANT_POSITIVE_SECTOR",
        "DOMINANT_NEGATIVE_SECTOR",
        "WORST_13F_VINTAGE",
        "A2_EDGE_CHARACTERIZATION",
        "TRANSACTION_COST_SHARE_OF_GROSS_EDGE",
        "PRIMARY_RISK_SOURCE",
        "SECONDARY_RISK_SOURCE",
        "TERTIARY_RISK_SOURCE",
        "NEXT_RESEARCH_HYPOTHESIS_COUNT",
        "MODEL_FIT_COUNT",
        "PARAMETER_SEARCH_COUNT",
        "RISK_RULE_SEARCH_COUNT",
        "ELIGIBILITY_MASK_CHANGE_COUNT",
        "FUTURE_INFORMATION_VIOLATION_COUNT",
        "PIT_13F_TEMPORAL_VIOLATION_COUNT",
        "SHARED_SOURCE_CHANGE_REQUIRED",
        "NEXT_AUTHORIZED_STEP",
    )
    for key in keys:
        value = status[key]
        if isinstance(value, bool):
            value = str(value).upper()
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        status = run(args.output)
    except Exception as exc:
        print(f"A2_ATTRIBUTION_R1_2026_YTD_STATUS=FAIL_CLOSED_{type(exc).__name__.upper()}")
        if "A2_ECONOMIC_PATH_MISMATCH" in str(exc):
            print("A2_ECONOMIC_PATH_IDENTITY_STATUS=FAIL_CLOSED_A2_ECONOMIC_PATH_MISMATCH")
        else:
            print("A2_ECONOMIC_PATH_IDENTITY_STATUS=NOT_ESTABLISHED")
        print(f"FAILURE={exc}")
        print("MODEL_FIT_COUNT=0")
        print("PARAMETER_SEARCH_COUNT=0")
        print("RISK_RULE_SEARCH_COUNT=0")
        print("SHARED_SOURCE_CHANGE_REQUIRED=FALSE")
        print("NEXT_AUTHORIZED_STEP=STOP_AND_REVIEW_ATTRIBUTION_R1")
        return 1
    print_status(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
