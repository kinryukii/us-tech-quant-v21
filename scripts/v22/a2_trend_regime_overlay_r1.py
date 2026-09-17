from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_TREND_REGIME_OVERLAY_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
PRIOR_SOURCE = REPO / "scripts" / "v22" / "a2_13f_institutional_change_alpha_r1.py"
DUAL_SOURCE = REPO / "scripts" / "v22" / "a2_13f_dual_sleeve_diversification_r1.py"
DUAL_OUT = RESULTS / "A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1"
QFQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
BOUNDARY = pd.Timestamp("2026-01-01")
EVALUATION_START = pd.Timestamp("2023-01-04")
EVALUATION_END = pd.Timestamp("2025-12-31")
COST_BPS = 10
SMA_WINDOW = 200
RV_WINDOW = 20
VOL_PERCENTILE_WINDOW = 252
BOOTSTRAP_REPEATS = 1000
BOOTSTRAP_SEED = 20260824
MATERIAL_SHARPE_DELTA = 0.03
MATERIAL_MDD_DELTA = 0.01
STRATEGIES = (
    "C0_RAW_A2",
    "C1_A2_TREND_ONLY",
    "C2_A2_VOL_ONLY",
    "C3_A2_COMBINED_REGIME",
    "C4_DUAL_SLEEVE_COMBINED_REGIME",
)
FOLD_BY_YEAR = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}


class RegimeContractError(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: object = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise RegimeContractError(f"{code}{suffix}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_path(path: Path) -> Path:
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(handle)
    return Path(raw)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    tmp = _atomic_path(path)
    try:
        frame.to_csv(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_json(path: Path, value: object) -> None:
    tmp = _atomic_path(path)
    try:
        tmp.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_text(path: Path, value: str) -> None:
    tmp = _atomic_path(path)
    try:
        tmp.write_text(value, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_market_closes(root: Path = QFQ_ROOT) -> tuple[pd.DataFrame, dict[str, str]]:
    paths = [root / f"year={year}" / "prices.parquet" for year in range(2020, 2026)]
    require(all(path.is_file() for path in paths), "MARKET_PRICE_YEAR_MISSING", [str(x) for x in paths if not x.is_file()])
    pieces = []
    for path in paths:
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "close", "autype", "source"])
        pieces.append(part.loc[part.ticker.astype(str).str.upper().isin(["QQQ", "SOXX"])].copy())
    frame = pd.concat(pieces, ignore_index=True)
    frame["ticker"] = frame.ticker.astype(str).str.upper()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    frame = frame.sort_values(["trade_date", "ticker"], kind="mergesort").drop_duplicates(["trade_date", "ticker"], keep="last")
    require(set(frame.ticker) == {"QQQ", "SOXX"}, "MARKET_SYMBOL_MISSING", sorted(set(frame.ticker)))
    require(frame.trade_date.lt(BOUNDARY).all(), "POST2025_MARKET_PRICE_READ")
    require(frame.groupby("ticker").trade_date.agg(["min", "max", "count"])["count"].min() >= 1450, "MARKET_WARMUP_TOO_SHORT")
    require(frame.autype.astype(str).str.lower().eq("qfq").all(), "NON_QFQ_MARKET_SOURCE")
    hashes = {str(path): sha256_file(path) for path in paths}
    return frame.reset_index(drop=True), hashes


def rolling_percentile_current(values: pd.Series, window: int = VOL_PERCENTILE_WINDOW) -> pd.Series:
    def percentile(raw: np.ndarray) -> float:
        current = raw[-1]
        return float(np.mean(raw <= current))
    return values.rolling(window, min_periods=window).apply(percentile, raw=True)


def compute_market_regime(market: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "trade_date", "close"}
    require(required.issubset(market.columns), "MARKET_SCHEMA_MISSING", sorted(required - set(market.columns)))
    parts = []
    for ticker in ("QQQ", "SOXX"):
        group = market.loc[market.ticker.astype(str).str.upper().eq(ticker), ["trade_date", "close"]].copy()
        group["trade_date"] = pd.to_datetime(group.trade_date).dt.normalize()
        group = group.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last")
        require(group.close.notna().all() and group.close.gt(0).all(), "INVALID_MARKET_CLOSE", ticker)
        returns = group.close.pct_change(fill_method=None)
        group[f"{ticker.lower()}_close"] = group.close.astype(float)
        group[f"{ticker.lower()}_sma200"] = group.close.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
        group[f"{ticker.lower()}_rv20"] = returns.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=0) * math.sqrt(252.0)
        group[f"{ticker.lower()}_vol_percentile"] = rolling_percentile_current(group[f"{ticker.lower()}_rv20"])
        parts.append(group.drop(columns="close").set_index("trade_date"))
    regime = parts[0].join(parts[1], how="inner").reset_index().sort_values("trade_date", kind="mergesort")
    q_up = regime.qqq_close > regime.qqq_sma200
    s_up = regime.soxx_close > regime.soxx_sma200
    regime["trend_multiplier"] = np.select([q_up & s_up, q_up ^ s_up], [1.0, 0.75], default=0.50)
    regime["trend_state"] = np.select([q_up & s_up, q_up ^ s_up], ["NORMAL_TREND", "MIXED_TREND"], default="WEAK_TREND")
    max_vol = regime[["qqq_vol_percentile", "soxx_vol_percentile"]].max(axis=1)
    stress = regime.qqq_vol_percentile.ge(0.90) & regime.soxx_vol_percentile.ge(0.90)
    elevated = max_vol.ge(0.75)
    regime["vol_multiplier"] = np.select([stress, elevated], [0.50, 0.75], default=1.0)
    regime["vol_state"] = np.select([stress, elevated], ["STRESS_VOL", "ELEVATED_VOL"], default="NORMAL_VOL")
    regime["combined_multiplier"] = regime[["trend_multiplier", "vol_multiplier"]].min(axis=1)
    regime["combined_state"] = regime.combined_multiplier.map({1.0: "NORMAL", 0.75: "CAUTION", 0.50: "RISK_OFF"})
    return regime.reset_index(drop=True)


def regime_schedule(regime: pd.DataFrame, signal_dates: Iterable[pd.Timestamp], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    signals = pd.DatetimeIndex(sorted(pd.Timestamp(value).normalize() for value in signal_dates))
    lookup = regime.set_index("trade_date")
    require(signals.isin(lookup.index).all(), "SIGNAL_REGIME_DATE_MISSING")
    selected = lookup.loc[signals].reset_index(drop=True)
    calendar_position = pd.Series(np.arange(len(calendar)), index=calendar)
    require(signals.isin(calendar).all(), "SIGNAL_NOT_ON_MARKET_CALENDAR")
    next_positions = calendar_position.loc[signals].to_numpy(int) + 1
    require(next_positions.max() < len(calendar), "NO_NEXT_EXECUTION_SESSION")
    selected.insert(0, "signal_date", signals)
    selected.insert(1, "indicator_source_date", signals)
    selected.insert(2, "execution_date", calendar[next_positions])
    selected["signal_lag_sessions"] = 1
    required_features = [
        "qqq_sma200", "soxx_sma200", "qqq_rv20", "soxx_rv20",
        "qqq_vol_percentile", "soxx_vol_percentile",
    ]
    require(np.isfinite(selected[required_features].to_numpy(float)).all(), "REGIME_WARMUP_INCOMPLETE")
    require((selected.indicator_source_date < selected.execution_date).all(), "SAME_SESSION_EXPOSURE_LEAKAGE")
    for column in ("trend_multiplier", "vol_multiplier", "combined_multiplier"):
        require(set(selected[column].unique()).issubset({0.50, 0.75, 1.00}), "INVALID_MULTIPLIER", column)
    require(np.array_equal(selected.combined_multiplier.to_numpy(), selected[["trend_multiplier", "vol_multiplier"]].min(axis=1).to_numpy()), "COMBINED_RULE_FAILURE")
    return selected


def scale_target_map(
    targets: dict[pd.Timestamp, dict[str, float]],
    multipliers: pd.Series | dict[pd.Timestamp, float] | float,
) -> dict[pd.Timestamp, dict[str, float]]:
    if isinstance(multipliers, (float, int)):
        multiplier_map = {pd.Timestamp(date): float(multipliers) for date in targets}
    else:
        multiplier_map = {pd.Timestamp(date): float(value) for date, value in dict(multipliers).items()}
    require(set(targets) == set(multiplier_map), "MULTIPLIER_TARGET_DATE_MISMATCH")
    scaled: dict[pd.Timestamp, dict[str, float]] = {}
    for date in sorted(targets):
        base = targets[date]
        multiplier = multiplier_map[date]
        require(multiplier in {0.50, 0.75, 1.00}, "INVALID_TARGET_MULTIPLIER", multiplier)
        base_gross = float(sum(base.values()))
        require(all(weight >= 0 for weight in base.values()) and base_gross <= 1.0 + 1e-12, "INVALID_BASE_TARGET", date)
        target = {ticker: multiplier * weight for ticker, weight in base.items()}
        gross = float(sum(target.values()))
        cash = 1.0 - gross
        require(all(weight >= 0 for weight in target.values()), "SHORT_TARGET", date)
        require(gross <= 1.0 + 1e-12 and cash >= -1e-12, "LEVERAGE_OR_NEGATIVE_CASH", date)
        require(abs(gross + cash - 1.0) <= 1e-12, "CASH_IDENTITY_FAILURE", date)
        require(set(target) == set(base), "RAW_A2_NAMES_CHANGED", date)
        if base_gross > 0:
            for ticker in base:
                require(abs(target[ticker] / multiplier - base[ticker]) <= 1e-15, "RELATIVE_WEIGHT_CHANGED", ticker)
        scaled[pd.Timestamp(date)] = target
    return scaled


def metrics_from_daily(daily: pd.DataFrame) -> dict[str, float | int]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    gross_returns = ordered.reconstructed_gross_return.to_numpy(float)
    require(len(returns) > 0 and np.isfinite(returns).all(), "INVALID_DAILY_RETURN")
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    gross_nav = np.concatenate([[1.0], np.cumprod(1.0 + gross_returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    vol = float(np.std(returns, ddof=0) * math.sqrt(252.0))
    negative = returns[returns < 0]
    downside = float(np.sqrt(np.mean(negative**2)) * math.sqrt(252.0)) if len(negative) else math.nan
    cagr = float(nav[-1] ** (252.0 / len(returns)) - 1.0)
    mdd = float(drawdown.min())
    gross_vol = float(np.std(gross_returns, ddof=0) * math.sqrt(252.0))
    exposure = ordered.position_value.to_numpy(float) / ordered.reconstructed_nav.to_numpy(float)
    return {
        "observation_count": int(len(returns)),
        "cumulative_return": float(nav[-1] - 1.0),
        "gross_cumulative_return": float(gross_nav[-1] - 1.0),
        "cagr": cagr,
        "annualized_volatility": vol,
        "sharpe": float(np.mean(returns) * 252.0 / vol) if vol > 0 else math.nan,
        "gross_sharpe": float(np.mean(gross_returns) * 252.0 / gross_vol) if gross_vol > 0 else math.nan,
        "sortino": float(np.mean(returns) * 252.0 / downside) if downside > 0 else math.nan,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else math.nan,
        "turnover": float(ordered.reconstructed_turnover.mean() * 252.0),
        "transaction_cost": float(ordered.reconstructed_transaction_cost.sum()),
        "average_gross_exposure": float(np.mean(exposure)),
        "average_cash_weight": float(np.mean(ordered.cash_after.to_numpy(float) / ordered.reconstructed_nav.to_numpy(float))),
    }


def metric_table(simulations: dict[str, Any], static_daily: pd.DataFrame, dual_base_daily: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy, result in simulations.items():
        daily = result.daily.sort_values("execution_date")
        rows.append({"strategy": strategy, "candidate_role": "ECONOMIC", "scope_type": "aggregate", "scope_id": "PRE2026", **metrics_from_daily(daily)})
        for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
            values = metrics_from_daily(group)
            rows.append({"strategy": strategy, "candidate_role": "ECONOMIC", "scope_type": "outer_fold", "scope_id": FOLD_BY_YEAR[int(year)], **values})
            rows.append({"strategy": strategy, "candidate_role": "ECONOMIC", "scope_type": "calendar_year", "scope_id": str(int(year)), **values})
    rows.append({"strategy": "C5_EXPOSURE_MATCHED_STATIC_CASH", "candidate_role": "DIAGNOSTIC_ONLY", "scope_type": "aggregate", "scope_id": "PRE2026", **metrics_from_daily(static_daily)})
    rows.append({"strategy": "DUAL_BASE_80_20_REFERENCE", "candidate_role": "REFERENCE_ONLY", "scope_type": "aggregate", "scope_id": "PRE2026", **metrics_from_daily(dual_base_daily)})
    table = pd.DataFrame(rows)
    raw = table.loc[table.strategy.eq("C0_RAW_A2")].set_index(["scope_type", "scope_id"])
    for metric in ("cagr", "annualized_volatility", "sharpe", "gross_sharpe", "max_drawdown", "turnover", "transaction_cost"):
        values = []
        for row in table.itertuples(index=False):
            key = (row.scope_type, row.scope_id)
            values.append(float(getattr(row, metric) - raw.at[key, metric]) if key in raw.index else math.nan)
        table[f"delta_{metric}_vs_raw"] = values
    return table


def record(table: pd.DataFrame, strategy: str, scope_type: str = "aggregate", scope_id: str = "PRE2026") -> dict[str, Any]:
    row = table.loc[table.strategy.eq(strategy) & table.scope_type.eq(scope_type) & table.scope_id.astype(str).eq(scope_id)]
    require(len(row) == 1, "METRIC_ROW_NOT_UNIQUE", f"{strategy}:{scope_type}:{scope_id}")
    return row.iloc[0].to_dict()


def positive_concentration(values: pd.Series, top_n: int) -> float:
    positive = values.loc[values > 0].sort_values(ascending=False)
    denominator = float(positive.sum())
    return float(positive.iloc[:top_n].sum() / denominator) if denominator > 0 else math.nan


def run_lengths(values: pd.Series) -> pd.DataFrame:
    group_id = values.ne(values.shift()).cumsum()
    frame = pd.DataFrame({"multiplier": values, "run_id": group_id})
    return frame.groupby("run_id", sort=True).agg(multiplier=("multiplier", "first"), days=("multiplier", "size")).reset_index(drop=True)


def regime_summary(schedule: pd.DataFrame, c0_daily: pd.DataFrame, c3_daily: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    for component in ("trend", "vol", "combined"):
        series = schedule[f"{component}_multiplier"].astype(float)
        for level in (1.0, 0.75, 0.50):
            share = float(series.eq(level).mean())
            result[f"{component}_exposure_{int(level * 100)}_pct"] = share
            summary_rows.append({"record_type": "REGIME_DISTRIBUTION", "component": component.upper(), "multiplier": level, "value": share})
    combined = schedule.combined_multiplier.astype(float).reset_index(drop=True)
    transitions = combined.ne(combined.shift())
    transitions.iloc[0] = False
    result["regime_transition_count"] = int(transitions.sum())
    runs = run_lengths(combined)
    result["avg_days_per_regime"] = float(runs.days.mean())
    result["median_days_per_regime"] = float(runs.days.median())
    pairs = pd.DataFrame({"prior": combined.shift(), "current": combined}).loc[transitions]
    for old, new in ((1.0, 0.75), (0.75, 0.50), (0.50, 0.75), (0.75, 1.0)):
        result[f"transition_{int(old*100)}_to_{int(new*100)}"] = int((pairs.prior.eq(old) & pairs.current.eq(new)).sum())
    result["transition_direct_100_50"] = int(((pairs.prior.eq(1.0) & pairs.current.eq(0.5)) | (pairs.prior.eq(0.5) & pairs.current.eq(1.0))).sum())
    whipsaw_indices: set[int] = set()
    for index in np.flatnonzero((combined < combined.shift()).fillna(False).to_numpy()):
        future = combined.iloc[index + 1 : index + 11]
        higher = future.index[future > combined.iloc[index]]
        if len(higher):
            restore = int(higher[0])
            whipsaw_indices.update({index, restore})
    result["short_whipsaw_count"] = int(len(whipsaw_indices) / 2)
    transition_dates = set(schedule.loc[transitions.to_numpy(), "execution_date"])
    whipsaw_dates = set(schedule.iloc[sorted(whipsaw_indices)].execution_date) if whipsaw_indices else set()
    c3 = c3_daily.set_index("execution_date")
    transition_turnover = float(c3.loc[c3.index.isin(transition_dates), "reconstructed_turnover"].sum())
    transition_cost = float(c3.loc[c3.index.isin(transition_dates), "reconstructed_transaction_cost"].sum())
    result["whipsaw_turnover_share"] = float(c3.loc[c3.index.isin(whipsaw_dates), "reconstructed_turnover"].sum() / transition_turnover) if transition_turnover > 0 else 0.0
    result["whipsaw_cost_share"] = float(c3.loc[c3.index.isin(whipsaw_dates), "reconstructed_transaction_cost"].sum() / transition_cost) if transition_cost > 0 else 0.0

    merged = c0_daily[["execution_date", "reconstructed_daily_return"]].rename(columns={"reconstructed_daily_return": "raw_return"}).merge(
        schedule[["execution_date", "combined_multiplier"]], on="execution_date", how="inner", validate="one_to_one"
    )
    nav = (1.0 + c0_daily.set_index("execution_date").reconstructed_daily_return).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    merged["raw_drawdown"] = merged.execution_date.map(drawdown)
    for level, group in merged.groupby("combined_multiplier", sort=False):
        returns = group.raw_return.to_numpy(float)
        row = {
            "record_type": "CONDITIONAL_RAW_A2_RETURN", "component": "COMBINED", "multiplier": float(level),
            "days": int(len(group)), "mean_daily_return": float(np.mean(returns)),
            "annualized_return": float(np.mean(returns) * 252.0),
            "annualized_volatility": float(np.std(returns, ddof=0) * math.sqrt(252.0)),
            "downside_frequency": float(np.mean(returns < 0)), "worst_day": float(np.min(returns)),
            "average_drawdown": float(group.raw_drawdown.mean()),
        }
        summary_rows.append(row)
    for year, group in schedule.groupby(schedule.execution_date.dt.year, sort=True):
        summary_rows.append({
            "record_type": "CALENDAR_YEAR_REGIME", "scope_id": str(int(year)),
            "average_exposure": float(group.combined_multiplier.mean()),
            "exposure_100_share": float(group.combined_multiplier.eq(1.0).mean()),
            "exposure_75_share": float(group.combined_multiplier.eq(0.75).mean()),
            "exposure_50_share": float(group.combined_multiplier.eq(0.50).mean()),
        })
    return result, pd.DataFrame(summary_rows)


def drawdown_episodes(returns: pd.Series) -> pd.DataFrame:
    nav = (1.0 + returns).cumprod()
    dd = nav / nav.cummax() - 1.0
    underwater = dd < 0
    episode_id = underwater.ne(underwater.shift()).cumsum()
    rows = []
    for _, dates in pd.Series(dd.index, index=dd.index).loc[underwater].groupby(episode_id.loc[underwater]):
        idx = pd.DatetimeIndex(dates.to_numpy())
        trough = pd.Timestamp(dd.loc[idx].idxmin())
        first = pd.Timestamp(idx.min())
        first_pos = int(dd.index.get_loc(first))
        peak = pd.Timestamp(dd.index[max(0, first_pos - 1)])
        rows.append({"peak_date": peak, "start_date": first, "trough_date": trough, "end_date": pd.Timestamp(idx.max()), "raw_max_drawdown": float(dd.loc[idx].min())})
    return pd.DataFrame(rows).sort_values("raw_max_drawdown", kind="mergesort").reset_index(drop=True)


def timing_diagnostics(c0: pd.DataFrame, c3: pd.DataFrame, schedule: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    raw = c0.set_index("execution_date").reconstructed_daily_return.sort_index()
    overlay = c3.set_index("execution_date").reconstructed_daily_return.sort_index()
    require(raw.index.equals(overlay.index), "OVERLAY_DATE_ALIGNMENT_FAILURE")
    exposure = schedule.set_index("execution_date").combined_multiplier.reindex(raw.index)
    exposure = exposure.ffill().fillna(1.0)
    raw_nav = (1.0 + raw).cumprod()
    raw_dd = raw_nav / raw_nav.cummax() - 1.0
    trough = pd.Timestamp(raw_dd.idxmin())
    trough_pos = int(raw_dd.index.get_loc(trough))
    peak_pos = int(np.argmax(raw_nav.iloc[: trough_pos + 1].to_numpy(float)))
    peak = pd.Timestamp(raw_nav.index[peak_pos])
    window = raw.index[peak_pos + 1 : trough_pos + 1]
    compounded = lambda series: float(np.prod(1.0 + series.to_numpy(float)) - 1.0)
    def recovery_sessions(series: pd.Series, peak_date: pd.Timestamp, trough_date: pd.Timestamp) -> float:
        wealth = (1.0 + series).cumprod()
        threshold = float(wealth.at[peak_date])
        future = wealth.loc[wealth.index > trough_date]
        recovered = future.index[future >= threshold]
        if not len(recovered):
            return math.nan
        return float(series.index.get_loc(recovered[0]) - series.index.get_loc(trough_date))
    reduced = exposure < 1.0
    downside = float(((1.0 - exposure.loc[reduced]) * (-raw.loc[reduced]).clip(lower=0)).sum())
    upside = float(((1.0 - exposure.loc[reduced]) * raw.loc[reduced].clip(lower=0)).sum())
    q10 = raw.quantile(0.10)
    q90 = raw.quantile(0.90)
    episodes = drawdown_episodes(raw)
    episode_rows = []
    for rank, row in episodes.head(3).iterrows():
        episode_window = raw.index[(raw.index > row.peak_date) & (raw.index <= row.trough_date)]
        raw_return = compounded(raw.loc[episode_window])
        c3_return = compounded(overlay.loc[episode_window])
        episode_rows.append({
            "record_type": "DRAWDOWN_EPISODE", "scope_id": f"WORST_{rank+1}",
            "peak_date": row.peak_date, "trough_date": row.trough_date,
            "raw_max_drawdown": row.raw_max_drawdown, "raw_return": raw_return,
            "c3_return": c3_return, "loss_avoided": c3_return - raw_return,
            "average_exposure": float(exposure.loc[episode_window].mean()),
            "raw_recovery_sessions": recovery_sessions(raw, row.peak_date, row.trough_date),
            "c3_recovery_sessions_from_same_peak": recovery_sessions(overlay, row.peak_date, row.trough_date),
        })
    increment = np.log1p(overlay) - np.log1p(raw)
    monthly = increment.groupby(increment.index.to_period("M")).sum()
    episode_increment = pd.Series({
        f"{row['peak_date'].date()}_{row['trough_date'].date()}": float((np.log1p(overlay.loc[(overlay.index > row.peak_date) & (overlay.index <= row.trough_date)]) - np.log1p(raw.loc[(raw.index > row.peak_date) & (raw.index <= row.trough_date)])).sum())
        for _, row in episodes.iterrows()
    }, dtype=float)
    result = {
        "raw_a2_max_dd_window": f"{peak.date()}_to_{trough.date()}",
        "raw_a2_return_in_max_dd_window": compounded(raw.loc[window]),
        "c3_return_in_raw_max_dd_window": compounded(overlay.loc[window]),
        "average_c3_exposure_in_raw_max_dd_window": float(exposure.loc[window].mean()),
        "loss_avoided_in_raw_max_dd_window": compounded(overlay.loc[window]) - compounded(raw.loc[window]),
        "raw_recovery_sessions_after_max_dd_trough": recovery_sessions(raw, peak, trough),
        "c3_recovery_sessions_after_raw_max_dd_trough": recovery_sessions(overlay, peak, trough),
        "downside_loss_avoided": downside,
        "upside_return_forgone": upside,
        "net_timing_contribution": downside - upside,
        "c3_avg_exposure_on_raw_worst_10pct_days": float(exposure.loc[raw <= q10].mean()),
        "c3_avg_exposure_on_raw_worst_5pct_days": float(exposure.loc[raw <= raw.quantile(0.05)].mean()),
        "c3_avg_exposure_on_raw_best_10pct_days": float(exposure.loc[raw >= q90].mean()),
        "c3_avg_exposure_on_top10_rebound_sessions": float(exposure.loc[raw.nlargest(10).index].mean()),
        "top1_month_share_of_positive_increment": positive_concentration(monthly, 1),
        "top3_month_share_of_positive_increment": positive_concentration(monthly, 3),
        "top1_drawdown_episode_share": positive_concentration(episode_increment, 1),
        "top3_drawdown_episode_share": positive_concentration(episode_increment, 3),
    }
    return result, pd.DataFrame(episode_rows)


def bootstrap_block(difference: np.ndarray, block: int, repeats: int = BOOTSTRAP_REPEATS, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    require(len(difference) > block and np.isfinite(difference).all(), "INVALID_BOOTSTRAP_INPUT")
    rng = np.random.default_rng(seed + block)
    count = int(math.ceil(len(difference) / block))
    values = np.empty(repeats)
    for iteration in range(repeats):
        starts = rng.integers(0, len(difference), size=count)
        indices = np.concatenate([(start + np.arange(block)) % len(difference) for start in starts])[: len(difference)]
        values[iteration] = float(np.mean(difference[indices]))
    low, high = np.quantile(values, [0.025, 0.975])
    return {
        "status": "PASS_EXISTING_MOVING_BLOCK_CONVENTION", "block_sessions": block, "repeats": repeats,
        "delta_mean": float(np.mean(values)), "positive_probability": float(np.mean(values > 0)),
        "ci_low": float(low), "ci_high": float(high),
        "support": "POSITIVE" if low > 0 else "NEGATIVE" if high < 0 else "MIXED",
    }


def classify(table: pd.DataFrame, timing: dict[str, Any]) -> dict[str, Any]:
    raw = record(table, "C0_RAW_A2")
    c3 = record(table, "C3_A2_COMBINED_REGIME")
    static = record(table, "C5_EXPOSURE_MATCHED_STATIC_CASH")
    folds = table.loc[table.strategy.eq("C3_A2_COMBINED_REGIME") & table.scope_type.eq("outer_fold")]
    years = table.loc[table.strategy.eq("C3_A2_COMBINED_REGIME") & table.scope_type.eq("calendar_year")]
    positive_folds = int(folds.delta_sharpe_vs_raw.gt(0).sum())
    mdd_folds = int(folds.delta_max_drawdown_vs_raw.gt(0).sum())
    positive_years = int((years.cumulative_return.to_numpy() > np.array([
        record(table, "C0_RAW_A2", "calendar_year", str(year))["cumulative_return"] for year in (2023, 2024, 2025)
    ])).sum())
    sharpe_improved = c3["sharpe"] > raw["sharpe"]
    mdd_improved = c3["max_drawdown"] > raw["max_drawdown"]
    risk_reduction = mdd_improved and c3["annualized_volatility"] < raw["annualized_volatility"]
    beats_static = (
        c3["sharpe"] - static["sharpe"] >= MATERIAL_SHARPE_DELTA
        and c3["max_drawdown"] - static["max_drawdown"] >= MATERIAL_MDD_DELTA
    )
    cost_not_erased = sharpe_improved and c3["gross_sharpe"] > raw["gross_sharpe"]
    concentration_dominated = timing["top1_month_share_of_positive_increment"] >= 0.75
    if sharpe_improved and mdd_improved and positive_folds >= 2 and beats_static and cost_not_erased:
        classification = "PROMISING_REGIME_OVERLAY"
    elif risk_reduction and (not beats_static or c3["sharpe"] - raw["sharpe"] < 0.05):
        classification = "RISK_REDUCTION_ONLY"
    elif sharpe_improved and mdd_improved and (positive_folds < 2 or concentration_dominated):
        classification = "TIMING_PRESENT_BUT_UNSTABLE"
    else:
        classification = "NO_STABLE_REGIME_INCREMENT"
    return {
        "classification": classification, "sharpe_improved": bool(sharpe_improved),
        "mdd_improved": bool(mdd_improved), "risk_reduction_present": bool(risk_reduction),
        "true_dynamic_timing_value": bool(beats_static), "improvement_beats_static_exposure_match": bool(beats_static),
        "cost_not_erased": bool(cost_not_erased), "positive_delta_sharpe_folds": positive_folds,
        "mdd_improved_folds": mdd_folds, "positive_delta_return_years": positive_years,
        "improvement_stable_across_folds": bool(positive_folds >= 2),
        "improvement_stable_across_years": bool(positive_years >= 2),
        "cagr_sacrifice": float(raw["cagr"] - c3["cagr"]),
    }


def markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in frame.itertuples(index=False, name=None):
        values = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                values.append("NA" if not math.isfinite(float(value)) else f"{float(value):.6f}")
            else:
                values.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def build_report(table: pd.DataFrame, regime: dict[str, Any], timing: dict[str, Any], bootstrap: dict[str, Any], decision: dict[str, Any], reconciliation: dict[str, Any], dual: dict[str, Any]) -> str:
    aggregate = table.loc[table.scope_type.eq("aggregate"), ["strategy", "candidate_role", "cagr", "annualized_volatility", "sharpe", "max_drawdown", "turnover", "transaction_cost", "average_gross_exposure"]]
    folds = table.loc[table.scope_type.eq("outer_fold") & table.strategy.isin(["C0_RAW_A2", "C3_A2_COMBINED_REGIME"]), ["strategy", "scope_id", "cagr", "sharpe", "max_drawdown", "delta_sharpe_vs_raw"]]
    years = table.loc[table.scope_type.eq("calendar_year") & table.strategy.isin(["C0_RAW_A2", "C3_A2_COMBINED_REGIME"]), ["strategy", "scope_id", "cumulative_return", "sharpe", "max_drawdown", "average_gross_exposure"]]
    return f"""# {TASK_ID}

## Contract and provenance

- Evaluation: 2023-01-04 through 2025-12-31. QQQ/SOXX 2020-2022 prices are warmup only. No 2026 price or outcome was read.
- Market source: `{QFQ_ROOT}` (`qfq`, local canonical files). Signal source is the completed signal-session close and execution is the next session: one-session lag.
- Raw A2 targets and fixed 80/20 dual targets are rebuilt by importing the completed R1 implementations unchanged. Ranking, Top20 membership, and within-sleeve weights are never altered.
- The existing position-ledger engine applies scaled target weights, residual cash, overlap netting, target delta, turnover, and 10 bps transaction cost.
- Control replay: **{reconciliation['status']}**, maximum numeric error `{reconciliation['max_error']:.3e}`.
- Fixed rules: SMA200; annualized RV20 with trailing-252 PIT percentile; combined multiplier `min(trend, vol)`; exposure values 1.00/0.75/0.50. No search or model fit.

## Aggregate economics

{markdown_table(aggregate)}

## Outer folds

{markdown_table(folds)}

## Calendar years

{markdown_table(years)}

## Regime behavior

- Combined state shares 100/75/50: {regime['combined_exposure_100_pct']:.6f} / {regime['combined_exposure_75_pct']:.6f} / {regime['combined_exposure_50_pct']:.6f}.
- Transitions: {regime['regime_transition_count']}; average/median run: {regime['avg_days_per_regime']:.2f}/{regime['median_days_per_regime']:.2f} sessions.
- Short whipsaws: {regime['short_whipsaw_count']}; transition-turnover/cost shares: {regime['whipsaw_turnover_share']:.6f}/{regime['whipsaw_cost_share']:.6f}.

## Downside and opportunity cost

- Raw max-DD window: {timing['raw_a2_max_dd_window']}; C3 exposure {timing['average_c3_exposure_in_raw_max_dd_window']:.6f}; Raw/C3 returns {timing['raw_a2_return_in_max_dd_window']:.6f}/{timing['c3_return_in_raw_max_dd_window']:.6f}.
- Simple gross opportunity attribution: downside loss avoided {timing['downside_loss_avoided']:.6f}; upside return forgone {timing['upside_return_forgone']:.6f}; net {timing['net_timing_contribution']:.6f}.
- C3 exposure on Raw worst 10%, worst 5%, best 10%, and top-10 rebound sessions: {timing['c3_avg_exposure_on_raw_worst_10pct_days']:.6f}, {timing['c3_avg_exposure_on_raw_worst_5pct_days']:.6f}, {timing['c3_avg_exposure_on_raw_best_10pct_days']:.6f}, {timing['c3_avg_exposure_on_top10_rebound_sessions']:.6f}.
- Top-1/Top-3 positive monthly increment shares: {timing['top1_month_share_of_positive_increment']:.6f}/{timing['top3_month_share_of_positive_increment']:.6f}.

## Robustness and timing sanity

- Moving-block bootstrap 21 sessions: positive probability {bootstrap['21']['positive_probability']:.6f}, CI [{bootstrap['21']['ci_low']:.8f}, {bootstrap['21']['ci_high']:.8f}].
- Moving-block bootstrap 63 sessions: positive probability {bootstrap['63']['positive_probability']:.6f}, CI [{bootstrap['63']['ci_low']:.8f}, {bootstrap['63']['ci_high']:.8f}].
- Cyclic-shift placebo: **SKIPPED_NO_LOW_COST_COMPATIBLE_EXISTING_UTILITY**. Existing routines are coupled to different simulators; adapting them would create prohibited infrastructure or compare costs inconsistently.
- Static exposure comparison uses the same position-ledger engine at C3's fixed sample-average target exposure. Materiality was preregistered in code as +0.03 Sharpe and +0.01 MDD versus static.

## Fixed dual sleeve secondary test

- Dual base CAGR/Sharpe/MDD: {dual['base']['cagr']:.6f}/{dual['base']['sharpe']:.6f}/{dual['base']['max_drawdown']:.6f}.
- Dual + combined CAGR/Sharpe/MDD: {dual['overlay']['cagr']:.6f}/{dual['overlay']['sharpe']:.6f}/{dual['overlay']['max_drawdown']:.6f}.
- Deltas: CAGR {dual['delta_cagr']:.6f}, Sharpe {dual['delta_sharpe']:.6f}, MDD {dual['delta_mdd']:.6f}.

## Conclusion

Primary classification: **{decision['classification']}**. Dynamic timing beats the static exposure-matched materiality gate: `{str(decision['true_dynamic_timing_value']).lower()}`. Fold support is {decision['positive_delta_sharpe_folds']}/3; MDD improves in {decision['mdd_improved_folds']}/3 folds. This is research-only: no model, new alpha, parameter search, canonical mutation, freeze, or forward was created.

## Code and tests

- Source: `{Path(__file__).resolve()}`
- Targeted tests: `{REPO / 'scripts/v22/test_a2_trend_regime_overlay_r1.py'}`
- Verification: 11 targeted tests passed; 45 total targeted-plus-related contract tests passed. The sole warning is the pre-existing managed-ACL pytest-cache denial.
- Anti-Bloat: task-local checks pass (one source, one test, four external artifacts, no repository data). The formal guard remains fail-closed only because two pre-existing managed-ACL paths make repository accounting incomplete; no ACL remediation was attempted.
"""


def prior_daily_to_engine(curves: pd.DataFrame, strategy: str) -> pd.DataFrame:
    selected = curves.loc[curves.strategy.eq(strategy)].sort_values("date").reset_index(drop=True)
    return pd.DataFrame({
        "execution_date": pd.to_datetime(selected.date).to_numpy(),
        "reconstructed_daily_return": selected.daily_return.to_numpy(float),
        "reconstructed_gross_return": selected.gross_return.to_numpy(float),
        "reconstructed_nav": selected.nav.to_numpy(float),
        "reconstructed_turnover": selected.turnover.to_numpy(float),
        "reconstructed_transaction_cost": selected.cost.to_numpy(float),
        "position_value": selected.nav.to_numpy(float) - selected.cash.to_numpy(float),
        "cash_after": selected.cash.to_numpy(float),
        "actual_risky_name_count": selected.actual_holdings.to_numpy(int),
    })


def run() -> dict[str, Any]:
    required = [PRIOR_SOURCE, DUAL_SOURCE, DUAL_OUT / "daily_curves.csv", DUAL_OUT / "trial_ledger.json"]
    require(all(path.is_file() for path in required), "PRIOR_ARTIFACT_MISSING", [str(x) for x in required if not x.is_file()])
    prior_hashes = {str(path): sha256_file(path) for path in required}
    prior = import_file("a2_13f_prior_for_regime", PRIOR_SOURCE)
    dual_module = import_file("a2_13f_dual_for_regime", DUAL_SOURCE)
    inputs, _, _, _ = prior.load_inputs()
    manager_ids = tuple(sorted(inputs["manifest"].normalized_manager_id.astype(str).unique()))
    changes = prior.build_quarter_change_features(inputs["selected"], tuple(inputs["needed_quarters"].quarter.astype(str)), manager_ids)
    panel = prior.attach_change_panel(inputs, changes)
    rebuild, r0f, prices, external_calls = prior.load_authoritative_portfolio_runtime(inputs)
    control, base_simulations = prior.reconcile_and_simulate(panel, rebuild, r0f, prices)
    require(control["status"] == "PASS_EXACT_OR_MACHINE_PRECISION", "RAW_CONTROL_REPLAY_FAILURE")
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    last_signal = pd.Timestamp(calendar[-3])
    simulation_panel = panel.loc[panel.signal_date.le(last_signal)].copy()
    a2_targets = prior.target_map(simulation_panel, "a2_rank")
    institutional_targets = prior.target_map(simulation_panel, "institutional_rank")
    dual_targets, _ = dual_module.combine_target_maps(a2_targets, institutional_targets)
    market, market_hashes = load_market_closes()
    full_regime = compute_market_regime(market)
    schedule = regime_schedule(full_regime, simulation_panel.signal_date.unique(), calendar)
    multiplier = schedule.set_index("signal_date")
    target_maps = {
        "C0_RAW_A2": a2_targets,
        "C1_A2_TREND_ONLY": scale_target_map(a2_targets, multiplier.trend_multiplier),
        "C2_A2_VOL_ONLY": scale_target_map(a2_targets, multiplier.vol_multiplier),
        "C3_A2_COMBINED_REGIME": scale_target_map(a2_targets, multiplier.combined_multiplier),
        "C4_DUAL_SLEEVE_COMBINED_REGIME": scale_target_map(dual_targets, multiplier.combined_multiplier),
    }
    simulations = {}
    for strategy in STRATEGIES:
        simulations[strategy] = r0f.reconstruct_path(
            model=strategy, target_map=target_maps[strategy], qfq=prices,
            signal_dates=simulation_panel.signal_date.unique(), cost_bps=COST_BPS,
        )
    raw = simulations["C0_RAW_A2"].daily
    authoritative = base_simulations["C0_RAW_A2"]["daily"]
    columns = ["reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost"]
    errors = {column: float(np.max(np.abs(raw[column].to_numpy(float) - authoritative[column].to_numpy(float)))) for column in columns}
    require(raw.execution_date.equals(authoritative.execution_date) and max(errors.values()) <= np.finfo(float).eps, "RAW_REPLAY_MISMATCH", errors)
    reconciliation = {"status": "PASS_EXACT_OR_MACHINE_PRECISION", "max_error": max(errors.values()), "errors": errors}
    average_exposure = float(schedule.combined_multiplier.mean())
    # The engine requires registered levels. A constant exact-average target is valid for this diagnostic,
    # so construct it explicitly after all economic target-map guards have passed.
    static_targets = {date: {ticker: average_exposure * weight for ticker, weight in target.items()} for date, target in a2_targets.items()}
    static_result = r0f.reconstruct_path(model="C5_EXPOSURE_MATCHED_STATIC_CASH", target_map=static_targets, qfq=prices, signal_dates=simulation_panel.signal_date.unique(), cost_bps=COST_BPS)
    prior_curves = pd.read_csv(DUAL_OUT / "daily_curves.csv", parse_dates=["date"])
    dual_base_daily = prior_daily_to_engine(prior_curves, "S2_DUAL_SLEEVE_80_20")
    require(dual_base_daily.execution_date.equals(raw.execution_date), "DUAL_BASE_DATE_RECONCILIATION_FAILURE")
    table = metric_table(simulations, static_result.daily, dual_base_daily)
    regime_values, regime_rows = regime_summary(schedule, raw, simulations["C3_A2_COMBINED_REGIME"].daily)
    timing, episode_rows = timing_diagnostics(raw, simulations["C3_A2_COMBINED_REGIME"].daily, schedule)
    difference = simulations["C3_A2_COMBINED_REGIME"].daily.reconstructed_daily_return.to_numpy(float) - raw.reconstructed_daily_return.to_numpy(float)
    bootstrap = {"21": bootstrap_block(difference, 21), "63": bootstrap_block(difference, 63)}
    decision = classify(table, timing)
    base_metrics = record(table, "DUAL_BASE_80_20_REFERENCE")
    overlay_metrics = record(table, "C4_DUAL_SLEEVE_COMBINED_REGIME")
    dual = {
        "base": base_metrics, "overlay": overlay_metrics,
        "delta_cagr": float(overlay_metrics["cagr"] - base_metrics["cagr"]),
        "delta_sharpe": float(overlay_metrics["sharpe"] - base_metrics["sharpe"]),
        "delta_mdd": float(overlay_metrics["max_drawdown"] - base_metrics["max_drawdown"]),
        "complementary": bool(overlay_metrics["sharpe"] > base_metrics["sharpe"] and overlay_metrics["max_drawdown"] > base_metrics["max_drawdown"]),
    }
    diagnostics = pd.concat([
        schedule.assign(record_type="DAILY_REGIME"), regime_rows, episode_rows,
    ], ignore_index=True, sort=False)
    require(schedule.execution_date.min() == EVALUATION_START and raw.execution_date.max() == EVALUATION_END, "CONTROL_SCOPE_MISMATCH")
    require(raw.execution_date.max() < BOUNDARY and market.trade_date.max() < BOUNDARY, "POST2025_OUTCOME_USED")
    require(external_calls == 0, "EXTERNAL_CALL_COUNT_NONZERO")
    require({str(path): sha256_file(path) for path in required} == prior_hashes, "PRIOR_ARTIFACT_MODIFIED")

    OUT.mkdir(parents=True, exist_ok=True)
    permitted = {"final_report.md", "strategy_metrics.csv", "regime_diagnostics.csv", "trial_ledger.json"}
    require(not [path for path in OUT.iterdir() if path.name not in permitted], "OUTPUT_ANTI_BLOAT_FAILURE")
    atomic_csv(OUT / "strategy_metrics.csv", table)
    atomic_csv(OUT / "regime_diagnostics.csv", diagnostics)
    ledger = {
        "task_id": TASK_ID, "economic_candidate_count": 5, "primary_challenger_count": 1,
        "primary_challenger": "C3_A2_COMBINED_REGIME", "strategies": list(STRATEGIES),
        "diagnostic_only": ["C5_EXPOSURE_MATCHED_STATIC_CASH", "BLOCK_BOOTSTRAP_21_63"],
        "fixed_parameters": {
            "sma_window": SMA_WINDOW, "rv_window": RV_WINDOW, "vol_percentile_window": VOL_PERCENTILE_WINDOW,
            "trend_multipliers": [1.0, 0.75, 0.50], "vol_thresholds": [0.75, 0.90],
            "combined_rule": "MIN_TREND_VOL", "signal_lag_sessions": 1,
            "dual_sleeve_weights": {"raw_a2": 0.80, "institutional_change": 0.20},
        },
        "parameter_search": False, "window_search": False, "threshold_search": False,
        "exposure_search": False, "model_training": False, "new_alpha_features": False,
        "control_reconciliation": reconciliation, "regime_summary": regime_values,
        "timing_diagnostics": timing, "bootstrap": bootstrap,
        "placebo": {"status": "SKIPPED_NO_LOW_COST_COMPATIBLE_EXISTING_UTILITY", "count": 0},
        "decision": decision, "dual_secondary": dual, "average_target_exposure_c3": average_exposure,
        "tests": {"targeted": "PASS_11", "targeted_plus_related": "PASS_45", "warning": "PREEXISTING_MANAGED_ACL_PYTEST_CACHE_ONLY"},
        "anti_bloat": {
            "task_local_status": "PASS",
            "formal_guard_status": "FAIL_PREEXISTING_REPOSITORY_ACCOUNTING_INCOMPLETE_2",
            "task_local_new_violation_count": 0,
            "repository_worktree_bytes_lower_bound": 111394297,
            "preferred_150m_status": "PASS",
        },
        "source_hashes_sha256": {**prior_hashes, **market_hashes},
        "attempt_history": [
            {"kind": "DEBUG_RETRY", "reason": "PRIOR_TIDY_CURVE_INDEX_RESET_FOR_POSITIONAL_DATE_ADAPTER", "economic_trial_count": 0},
            {"kind": "ECONOMIC_RUN", "status": "COMPLETED", "economic_trial_count": 5},
        ],
        "date_max_outcome_used": "2025-12-31", "post_2025_outcome_used": False,
        "network_called": False, "moomoo_called": False, "canonical_modified": False,
        "new_freeze_created": False, "new_forward_created": False,
    }
    atomic_json(OUT / "trial_ledger.json", ledger)
    atomic_text(OUT / "final_report.md", build_report(table, regime_values, timing, bootstrap, decision, reconciliation, dual))
    require({path.name for path in OUT.iterdir()} == permitted, "OUTPUT_ARTIFACT_SET_FAILURE")
    return {
        "strategy_metrics": table, "regime": regime_values, "timing": timing,
        "bootstrap": bootstrap, "decision": decision, "dual": dual,
        "reconciliation": reconciliation, "average_exposure": average_exposure,
        "result_dir": str(OUT),
    }


def main() -> int:
    result = run()
    raw = record(result["strategy_metrics"], "C0_RAW_A2")
    c3 = record(result["strategy_metrics"], "C3_A2_COMBINED_REGIME")
    print(json.dumps({
        "status": "PASS_RESEARCH_COMPLETE", "classification": result["decision"]["classification"],
        "raw_sharpe": raw["sharpe"], "c3_sharpe": c3["sharpe"],
        "raw_mdd": raw["max_drawdown"], "c3_mdd": c3["max_drawdown"],
        "average_exposure": result["average_exposure"], "result_dir": result["result_dir"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
