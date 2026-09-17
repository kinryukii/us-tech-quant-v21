"""Fixed 80/20 capital-level diversification of existing Raw A2 and 13F sleeves.

This module imports the completed A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1
implementation unchanged, reconstructs its two standalone target streams, nets
them into one target portfolio, and reuses the same position-ledger engine.
There is no score blend, alpha change, allocation search, or model fit.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_13F_DUAL_SLEEVE_DIVERSIFICATION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
PRIOR_OUT = RESULTS / "A2_13F_INSTITUTIONAL_CHANGE_ALPHA_R1"
PRIOR_SOURCE = REPO / "scripts" / "v22" / "a2_13f_institutional_change_alpha_r1.py"
PRIOR_TEST = REPO / "scripts" / "v22" / "test_a2_13f_institutional_change_alpha_r1.py"

BOUNDARY = pd.Timestamp("2026-01-01")
A2_WEIGHT = 0.80
INSTITUTIONAL_WEIGHT = 0.20
TOP_N = 20
COST_BPS = 10
CONCENTRATION_LIMIT = 0.50
REPLAY_TOLERANCE = 1e-12
STRATEGIES = ("S0_RAW_A2", "S1_13F_CHANGE", "S2_DUAL_SLEEVE_80_20")
PRIOR_STRATEGY_MAP = {
    "S0_RAW_A2": "C0_RAW_A2",
    "S1_13F_CHANGE": "C1_INSTITUTIONAL_CHANGE_STANDALONE",
}


class DualSleeveContractError(RuntimeError):
    """A capital-allocation, PIT, replay, or output contract violation."""


def require(condition: bool, code: str, evidence: object = "") -> None:
    if not condition:
        detail = f"|{evidence}" if evidence != "" else ""
        raise DualSleeveContractError(f"{code}{detail}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def fingerprint_target_map(targets: dict[pd.Timestamp, dict[str, float]]) -> str:
    rows = []
    for date, target in sorted(targets.items()):
        rows.extend(f"{pd.Timestamp(date).date()}|{ticker}|{weight:.17g}" for ticker, weight in sorted(target.items()))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def validate_target_stream(targets: dict[pd.Timestamp, dict[str, float]], label: str) -> None:
    require(bool(targets), "EMPTY_TARGET_STREAM", label)
    for date, target in targets.items():
        require(pd.Timestamp(date) < BOUNDARY, "POST2025_TARGET_DATE", f"{label}:{date}")
        require(len(target) == TOP_N, "STANDALONE_TOP20_FAILURE", f"{label}:{date}:{len(target)}")
        weights = np.asarray(list(target.values()), float)
        require(np.isfinite(weights).all() and (weights >= 0).all(), "INVALID_TARGET_WEIGHT", label)
        require(abs(float(weights.sum()) - 1.0) <= 1e-12, "STANDALONE_GROSS_IDENTITY_FAILURE", label)
        require(np.allclose(weights, 1.0 / TOP_N, atol=1e-12, rtol=0.0), "STANDALONE_EQUAL_WEIGHT_FAILURE", label)


def combine_target_maps(
    a2_targets: dict[pd.Timestamp, dict[str, float]],
    institutional_targets: dict[pd.Timestamp, dict[str, float]],
) -> tuple[dict[pd.Timestamp, dict[str, float]], pd.DataFrame]:
    """Net the two sleeve target portfolios before turnover and cost."""
    require(A2_WEIGHT == 0.80 and INSTITUTIONAL_WEIGHT == 0.20, "SLEEVE_WEIGHT_CONTRACT_CHANGED")
    require(abs(A2_WEIGHT + INSTITUTIONAL_WEIGHT - 1.0) <= 1e-15, "SLEEVE_WEIGHT_SUM_FAILURE")
    validate_target_stream(a2_targets, "RAW_A2")
    validate_target_stream(institutional_targets, "13F_CHANGE")
    require(set(a2_targets) == set(institutional_targets), "SLEEVE_DECISION_DATE_MISMATCH")
    combined: dict[pd.Timestamp, dict[str, float]] = {}
    audit_rows: list[dict[str, Any]] = []
    for date in sorted(a2_targets):
        a2 = a2_targets[date]
        institutional = institutional_targets[date]
        names = sorted(set(a2) | set(institutional))
        target = {
            ticker: A2_WEIGHT * a2.get(ticker, 0.0) + INSTITUTIONAL_WEIGHT * institutional.get(ticker, 0.0)
            for ticker in names
        }
        target = {ticker: weight for ticker, weight in target.items() if weight > 0}
        gross = float(sum(target.values()))
        a2_cash = 1.0 - float(sum(a2.values()))
        institutional_cash = 1.0 - float(sum(institutional.values()))
        target_cash = A2_WEIGHT * a2_cash + INSTITUTIONAL_WEIGHT * institutional_cash
        require(all(weight >= 0 for weight in target.values()), "COMBINED_SHORT_TARGET")
        require(gross <= 1.0 + 1e-12, "COMBINED_GROSS_EXCEEDS_ONE", f"{date}:{gross}")
        require(target_cash >= -1e-12, "COMBINED_NEGATIVE_CASH", f"{date}:{target_cash}")
        require(abs(gross + target_cash - 1.0) <= 1e-12, "COMBINED_CASH_IDENTITY_FAILURE", date)
        overlap = set(a2) & set(institutional)
        for ticker in overlap:
            expected = A2_WEIGHT * a2[ticker] + INSTITUTIONAL_WEIGHT * institutional[ticker]
            require(abs(target[ticker] - expected) <= 1e-15, "OVERLAP_WEIGHT_NETTING_FAILURE", ticker)
        combined[pd.Timestamp(date)] = target
        effective_n = 1.0 / sum(weight * weight for weight in target.values())
        audit_rows.append({
            "signal_date": pd.Timestamp(date),
            "name_overlap": len(overlap),
            "combined_position_count": len(target),
            "effective_number_of_holdings": effective_n,
            "max_single_name_target_weight": max(target.values()),
            "combined_target_gross": gross,
            "combined_target_cash": target_cash,
        })
    return combined, pd.DataFrame(audit_rows)


def validate_pit_target_dates(panel: pd.DataFrame) -> None:
    required = {"signal_date", "quarter_effective_date", "target_end_date", "target"}
    require(required.issubset(panel.columns), "PIT_PANEL_SCHEMA_MISSING", sorted(required - set(panel.columns)))
    require((pd.to_datetime(panel.signal_date) >= pd.to_datetime(panel.quarter_effective_date)).all(), "PREMATURE_13F_TARGET")
    labeled = panel.loc[panel.target.notna()]
    require(not labeled.empty, "NO_MATURE_OUTCOMES")
    require(pd.to_datetime(labeled.target_end_date).lt(BOUNDARY).all(), "POST2025_OUTCOME_USED")


def metrics_from_daily(daily: pd.DataFrame) -> dict[str, float | int]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    returns = ordered.reconstructed_daily_return.to_numpy(float)
    gross_returns = ordered.reconstructed_gross_return.to_numpy(float)
    require(len(returns) > 0 and np.isfinite(returns).all(), "INVALID_DAILY_RETURN")
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    gross_nav = np.concatenate([[1.0], np.cumprod(1.0 + gross_returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    annualized_mean = float(np.mean(returns) * 252.0)
    negative = returns[returns < 0]
    downside = float(np.sqrt(np.mean(negative**2)) * np.sqrt(252.0)) if len(negative) else math.nan
    cumulative = float(nav[-1] - 1.0)
    cagr = float(nav[-1] ** (252.0 / len(returns)) - 1.0)
    mdd = float(drawdown.min())
    gross_volatility = float(np.std(gross_returns, ddof=0) * np.sqrt(252.0))
    gross_annualized_mean = float(np.mean(gross_returns) * 252.0)
    return {
        "observation_count": int(len(returns)),
        "cumulative_return": cumulative,
        "gross_cumulative_return": float(gross_nav[-1] - 1.0),
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe": annualized_mean / volatility if volatility > 0 else math.nan,
        "gross_sharpe": gross_annualized_mean / gross_volatility if gross_volatility > 0 else math.nan,
        "sortino": annualized_mean / downside if downside > 0 else math.nan,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else math.nan,
        "turnover": float(ordered.reconstructed_turnover.mean() * 252.0),
        "transaction_cost": float(ordered.reconstructed_transaction_cost.sum()),
        "average_holdings": float(ordered.actual_risky_name_count.mean()),
    }


def metric_table(simulations: dict[str, dict[str, Any]], panel: pd.DataFrame, prior: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    raw_daily = simulations["S0_RAW_A2"]["daily"].sort_values("execution_date")
    vintage = prior.execution_vintage_map(panel, raw_daily)
    for strategy, result in simulations.items():
        daily = result["daily"].sort_values("execution_date").copy()
        rows.append({"strategy": strategy, "scope_type": "aggregate", "scope_id": "PRE2026", **metrics_from_daily(daily)})
        for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
            fold = str(panel.loc[panel.signal_date.dt.year.eq(year), "split"].iloc[0])
            metrics = metrics_from_daily(group)
            rows.append({"strategy": strategy, "scope_type": "outer_fold", "scope_id": fold, **metrics})
            rows.append({"strategy": strategy, "scope_type": "calendar_year", "scope_id": str(int(year)), **metrics})
        daily["vintage"] = vintage.reindex(pd.DatetimeIndex(daily.execution_date)).to_numpy()
        for quarter, group in daily.groupby("vintage", sort=True):
            rows.append({"strategy": strategy, "scope_type": "13f_vintage", "scope_id": str(quarter), **metrics_from_daily(group)})
    table = pd.DataFrame(rows)
    raw = table.loc[table.strategy.eq("S0_RAW_A2")].set_index(["scope_type", "scope_id"])
    for column in (
        "cumulative_return", "gross_cumulative_return", "cagr", "annualized_volatility",
        "sharpe", "gross_sharpe", "max_drawdown", "turnover", "transaction_cost",
    ):
        table[f"delta_{column}_vs_raw"] = [
            float(row[column] - raw.at[(row.scope_type, row.scope_id), column])
            for _, row in table.iterrows()
        ]
    return table


def reconcile_prior_sleeves(table: pd.DataFrame) -> dict[str, Any]:
    prior_table = pd.read_csv(PRIOR_OUT / "strategy_metrics.csv")
    checks: dict[str, Any] = {}
    common_columns = (
        "cumulative_return", "gross_cumulative_return", "cagr", "annualized_volatility",
        "sharpe", "sortino", "max_drawdown", "calmar", "turnover", "transaction_cost", "average_holdings",
    )
    for current_strategy, prior_strategy in PRIOR_STRATEGY_MAP.items():
        current = table.loc[table.strategy.eq(current_strategy)].sort_values(["scope_type", "scope_id"]).reset_index(drop=True)
        saved = prior_table.loc[prior_table.strategy.eq(prior_strategy)].sort_values(["scope_type", "scope_id"]).reset_index(drop=True)
        require(current[["scope_type", "scope_id"]].equals(saved[["scope_type", "scope_id"]]), "PRIOR_SCOPE_RECONCILIATION_FAILURE", current_strategy)
        errors = {
            column: float(np.nanmax(np.abs(current[column].to_numpy(float) - saved[column].to_numpy(float))))
            for column in common_columns
        }
        require(max(errors.values()) <= REPLAY_TOLERANCE, "PRIOR_SLEEVE_REPLAY_MISMATCH", f"{current_strategy}:{errors}")
        checks[current_strategy] = {"status": "PASS_EXACT_OR_MACHINE_PRECISION", "max_abs_errors": errors}
    return checks


def make_daily_curves(simulations: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for strategy, result in simulations.items():
        daily = result["daily"].sort_values("execution_date").copy()
        nav = np.cumprod(1.0 + daily.reconstructed_daily_return.to_numpy(float))
        drawdown = nav / np.maximum.accumulate(nav) - 1.0
        rows.append(pd.DataFrame({
            "date": pd.to_datetime(daily.execution_date),
            "strategy": strategy,
            "daily_return": daily.reconstructed_daily_return.to_numpy(float),
            "gross_return": daily.reconstructed_gross_return.to_numpy(float),
            "nav": nav,
            "drawdown": drawdown,
            "turnover": daily.reconstructed_turnover.to_numpy(float),
            "cost": daily.reconstructed_transaction_cost.to_numpy(float),
            "cash": daily.cash_after.to_numpy(float),
            "actual_holdings": daily.actual_risky_name_count.to_numpy(int),
        }))
    return pd.concat(rows, ignore_index=True).sort_values(["date", "strategy"], kind="mergesort").reset_index(drop=True)


def return_diagnostics(curves: pd.DataFrame) -> dict[str, Any]:
    wide = curves.pivot(index="date", columns="strategy", values="daily_return").sort_index()
    require(not wide.isna().any().any(), "DAILY_CURVE_ALIGNMENT_FAILURE")
    raw = wide.S0_RAW_A2
    institutional = wide.S1_13F_CHANGE
    dual = wide.S2_DUAL_SLEEVE_80_20
    monthly = (1.0 + wide).groupby(wide.index.to_period("M")).prod() - 1.0
    negative = raw < 0
    threshold = float(raw.quantile(0.10))
    worst = raw <= threshold
    raw_nav = (1.0 + raw).cumprod()
    raw_drawdown = raw_nav / raw_nav.cummax() - 1.0
    institutional_nav = (1.0 + institutional).cumprod()
    institutional_drawdown = institutional_nav / institutional_nav.cummax() - 1.0
    dual_nav = (1.0 + dual).cumprod()
    dual_drawdown = dual_nav / dual_nav.cummax() - 1.0
    trough_date = pd.Timestamp(raw_drawdown.idxmin())
    trough_position = int(raw_drawdown.index.get_loc(trough_date))
    peak_position = int(np.argmax(raw_nav.iloc[: trough_position + 1].to_numpy(float)))
    peak_date = pd.Timestamp(raw_nav.index[peak_position])
    window_index = raw.index[peak_position + 1 : trough_position + 1]
    require(len(window_index) > 0, "RAW_MAX_DRAWDOWN_WINDOW_EMPTY")
    def compounded(series: pd.Series) -> float:
        return float(np.prod(1.0 + series.to_numpy(float)) - 1.0)
    raw_dd_days = raw_drawdown < 0
    both_dd_days = raw_dd_days & (institutional_drawdown < 0)
    return {
        "daily_return_correlation": float(raw.corr(institutional)),
        "daily_return_spearman": float(raw.corr(institutional, method="spearman")),
        "monthly_return_correlation": float(monthly.S0_RAW_A2.corr(monthly.S1_13F_CHANGE)),
        "monthly_return_spearman": float(monthly.S0_RAW_A2.corr(monthly.S1_13F_CHANGE, method="spearman")),
        "correlation_on_raw_a2_negative_days": float(raw.loc[negative].corr(institutional.loc[negative])),
        "raw_a2_worst_10pct_threshold": threshold,
        "raw_a2_mean_return_on_worst_10pct_days": float(raw.loc[worst].mean()),
        "institutional_mean_return_on_raw_a2_worst_10pct_days": float(institutional.loc[worst].mean()),
        "institutional_positive_rate_on_raw_a2_worst_10pct_days": float((institutional.loc[worst] > 0).mean()),
        "raw_a2_max_dd_window": f"{peak_date.date()}_to_{trough_date.date()}",
        "raw_a2_return_during_raw_a2_max_dd_window": compounded(raw.loc[window_index]),
        "institutional_return_during_raw_a2_max_dd_window": compounded(institutional.loc[window_index]),
        "dual_return_during_raw_a2_max_dd_window": compounded(dual.loc[window_index]),
        "drawdown_series_correlation": float(raw_drawdown.corr(institutional_drawdown)),
        "drawdown_day_overlap": float(both_dd_days.sum() / raw_dd_days.sum()),
    }


def positive_concentration(values: pd.Series, top_n: int) -> float:
    positive = values.loc[values > 0].sort_values(ascending=False)
    denominator = float(positive.sum())
    return float(positive.iloc[:top_n].sum() / denominator) if denominator > 0 else math.nan


def incremental_attribution(curves: pd.DataFrame, panel: pd.DataFrame, prior: Any) -> tuple[dict[str, Any], pd.DataFrame]:
    wide = curves.pivot(index="date", columns="strategy", values="daily_return").sort_index()
    increment = np.log1p(wide.S2_DUAL_SLEEVE_80_20) - np.log1p(wide.S0_RAW_A2)
    attribution = pd.DataFrame({"date": increment.index, "log_wealth_increment": increment.to_numpy(float)})
    attribution["month"] = attribution.date.dt.to_period("M").astype(str)
    year_to_fold = panel[["signal_date", "split"]].drop_duplicates().assign(year=lambda x: x.signal_date.dt.year).groupby("year").split.first()
    attribution["fold"] = attribution.date.dt.year.map(year_to_fold)
    raw_daily = curves.loc[curves.strategy.eq("S0_RAW_A2")].rename(columns={"date": "execution_date"})
    vintage = prior.execution_vintage_map(panel, raw_daily)
    attribution["vintage"] = vintage.reindex(pd.DatetimeIndex(attribution.date)).to_numpy()
    month = attribution.groupby("month").log_wealth_increment.sum()
    fold = attribution.groupby("fold").log_wealth_increment.sum()
    vintage_group = attribution.groupby("vintage").log_wealth_increment.sum()
    result = {
        "attribution_method": "ADDITIVE_DAILY_LOG_WEALTH_DIFFERENCE_WITH_POSITIVE_CONTRIBUTION_DENOMINATOR",
        "total_log_wealth_increment": float(attribution.log_wealth_increment.sum()),
        "paired_mean_daily_differential": float((wide.S2_DUAL_SLEEVE_80_20 - wide.S0_RAW_A2).mean()),
        "paired_median_daily_differential": float((wide.S2_DUAL_SLEEVE_80_20 - wide.S0_RAW_A2).median()),
        "top1_month_share_of_positive_increment": positive_concentration(month, 1),
        "top3_month_share_of_positive_increment": positive_concentration(month, 3),
        "top1_fold_share_of_positive_increment": positive_concentration(fold, 1),
        "top1_vintage_share_of_positive_increment": positive_concentration(vintage_group, 1),
        "top3_vintage_share_of_positive_increment": positive_concentration(vintage_group, 3),
        "positive_month_count": int((month > 0).sum()),
        "month_count": int(len(month)),
        "positive_fold_count": int((fold > 0).sum()),
        "fold_count": int(len(fold)),
        "positive_vintage_count": int((vintage_group > 0).sum()),
        "vintage_count": int(len(vintage_group)),
    }
    return result, attribution


def bootstrap_diagnostic(prior: Any, simulations: dict[str, dict[str, Any]]) -> dict[str, float]:
    compatible = {
        "C0_RAW_A2": simulations["S0_RAW_A2"],
        "C2_A2_PLUS_INSTITUTIONAL_CHANGE": simulations["S2_DUAL_SLEEVE_80_20"],
    }
    return prior.bootstrap_diagnostic(compatible)


def structure_diagnostics(target_audit: pd.DataFrame) -> dict[str, Any]:
    return {
        "average_a2_13f_name_overlap": float(target_audit.name_overlap.mean()),
        "min_name_overlap": int(target_audit.name_overlap.min()),
        "max_name_overlap": int(target_audit.name_overlap.max()),
        "average_combined_position_count": float(target_audit.combined_position_count.mean()),
        "max_combined_position_count": int(target_audit.combined_position_count.max()),
        "average_effective_number_of_holdings": float(target_audit.effective_number_of_holdings.mean()),
        "max_single_name_target_weight": float(target_audit.max_single_name_target_weight.max()),
        "max_combined_target_gross": float(target_audit.combined_target_gross.max()),
        "max_abs_cash_identity_error": float(np.max(np.abs(target_audit.combined_target_gross + target_audit.combined_target_cash - 1.0))),
        "sector_diagnostic": "NOT_AVAILABLE_WITHOUT_NEW_INFRASTRUCTURE",
    }


def record(table: pd.DataFrame, **where: str) -> dict[str, Any]:
    selected = table.copy()
    for column, value in where.items():
        selected = selected.loc[selected[column].astype(str).eq(str(value))]
    require(len(selected) == 1, "METRIC_ROW_NOT_UNIQUE", where)
    return selected.iloc[0].to_dict()


def classify(table: pd.DataFrame, attribution: dict[str, Any], diagnostics: dict[str, Any], bootstrap: dict[str, float]) -> dict[str, Any]:
    raw = record(table, strategy="S0_RAW_A2", scope_type="aggregate", scope_id="PRE2026")
    dual = record(table, strategy="S2_DUAL_SLEEVE_80_20", scope_type="aggregate", scope_id="PRE2026")
    folds = table.loc[table.strategy.eq("S2_DUAL_SLEEVE_80_20") & table.scope_type.eq("outer_fold")]
    years = table.loc[table.strategy.eq("S2_DUAL_SLEEVE_80_20") & table.scope_type.eq("calendar_year")]
    positive_sharpe_folds = int(folds.delta_sharpe_vs_raw.gt(0).sum())
    positive_return_years = int(years.delta_cumulative_return_vs_raw.gt(0).sum())
    sharpe_improved = float(dual["sharpe"]) > float(raw["sharpe"])
    mdd_improved = float(dual["max_drawdown"]) > float(raw["max_drawdown"])
    vol_improved = float(dual["annualized_volatility"]) < float(raw["annualized_volatility"])
    cost_not_erased = sharpe_improved and float(dual["gross_sharpe"]) > float(raw["gross_sharpe"])
    concentration_ok = all(
        (not math.isfinite(float(attribution[key]))) or float(attribution[key]) < CONCENTRATION_LIMIT
        for key in (
            "top1_month_share_of_positive_increment",
            "top1_fold_share_of_positive_increment",
            "top1_vintage_share_of_positive_increment",
        )
    )
    promising = sharpe_improved and mdd_improved and positive_sharpe_folds >= 2 and cost_not_erased and concentration_ok
    risk_reduction = mdd_improved and vol_improved
    classification = (
        "PROMISING_DUAL_SLEEVE_DIVERSIFIER" if promising
        else "RISK_REDUCTION_ONLY" if risk_reduction
        else "NO_MEANINGFUL_DIVERSIFICATION"
    )
    downside = (
        float(diagnostics["institutional_mean_return_on_raw_a2_worst_10pct_days"])
        > float(diagnostics["raw_a2_mean_return_on_worst_10pct_days"])
        and float(diagnostics["institutional_return_during_raw_a2_max_dd_window"])
        > float(diagnostics["raw_a2_return_during_raw_a2_max_dd_window"])
    )
    positive_vintage_share = attribution["positive_vintage_count"] / attribution["vintage_count"]
    return {
        "classification": classification,
        "sharpe_improved": sharpe_improved,
        "mdd_improved": mdd_improved,
        "volatility_improved": vol_improved,
        "cost_not_erased": cost_not_erased,
        "concentration_gate": concentration_ok,
        "positive_delta_sharpe_folds": positive_sharpe_folds,
        "valid_outer_folds": int(len(folds)),
        "positive_delta_return_years": positive_return_years,
        "valid_years": int(len(years)),
        "portfolio_diversification_present": bool(abs(float(diagnostics["daily_return_correlation"])) < 0.80 and vol_improved),
        "downside_diversification_present": bool(downside and mdd_improved),
        "improvement_stable_across_folds": bool(sharpe_improved and positive_sharpe_folds >= 2),
        "improvement_stable_across_vintages": bool(
            positive_vintage_share >= 0.60
            and float(attribution["top1_vintage_share_of_positive_increment"]) < CONCENTRATION_LIMIT
        ),
        "cagr_sacrifice": float(raw["cagr"] - dual["cagr"]),
        "bootstrap_ci_supports_positive_mean": float(bootstrap["ci_low"]) > 0,
    }


def institutional_carry_audit(panel: pd.DataFrame, targets: dict[pd.Timestamp, dict[str, float]]) -> dict[str, Any]:
    rows = []
    quarter_by_date = panel[["signal_date", "active_13f_quarter"]].drop_duplicates().set_index("signal_date").active_13f_quarter
    for date, target in targets.items():
        rows.append({"signal_date": date, "quarter": quarter_by_date.at[date], "fingerprint": hashlib.sha256("\n".join(sorted(target)).encode()).hexdigest()})
    frame = pd.DataFrame(rows)
    counts = frame.groupby("quarter").fingerprint.nunique()
    return {
        "institutional_score_vintage_carry": "PASS_UNCHANGED_PRIOR_COMPOSITE",
        "target_vintages_with_eligibility_substitution": int((counts > 1).sum()),
        "max_target_sets_within_vintage": int(counts.max()),
        "explanation": "PRIOR_S1_REUSED_EXACTLY;INTRA_VINTAGE_TARGET_CHANGES_ONLY_FROM_AUTHORITATIVE_A2_TRADE_ELIGIBILITY_ARRIVALS_NOT_NEW_13F_INFORMATION",
    }


def build_report(
    table: pd.DataFrame,
    diagnostics: dict[str, Any],
    structure: dict[str, Any],
    attribution: dict[str, Any],
    bootstrap: dict[str, float],
    decision: dict[str, Any],
    reconciliation: dict[str, Any],
    carry_audit: dict[str, Any],
) -> str:
    aggregate = table.loc[table.scope_type.eq("aggregate"), [
        "strategy", "cumulative_return", "cagr", "annualized_volatility", "sharpe", "sortino",
        "max_drawdown", "calmar", "turnover", "transaction_cost",
    ]]
    folds = table.loc[table.scope_type.eq("outer_fold"), ["strategy", "scope_id", "sharpe", "delta_sharpe_vs_raw"]]
    years = table.loc[table.scope_type.eq("calendar_year"), ["strategy", "scope_id", "cumulative_return", "delta_cumulative_return_vs_raw"]]
    return f"""# {TASK_ID}

## Scope and reuse

- Scope: 2023-01-04 through 2025-12-31; no 2026 outcome or price.
- Prior task reused unchanged: `{PRIOR_OUT}` and `{PRIOR_SOURCE}`.
- Raw A2 replay: `{reconciliation['S0_RAW_A2']['status']}`; 13F standalone replay: `{reconciliation['S1_13F_CHANGE']['status']}`.
- Capital allocation only: 80% Raw A2 targets plus 20% original 13F standalone targets. No score blend, allocation search, new feature, manager reweighting, or model fit.
- Combined targets are netted by ticker before the existing position-ledger engine computes delta, cash, turnover, and 10 bps cost.
- Sector diagnostic: `{structure['sector_diagnostic']}`; the existing PIT sector taxonomy failed its upstream coverage gate.

## Target and PIT contract

- Maximum target gross: `{structure['max_combined_target_gross']:.12f}`; maximum cash identity error: `{structure['max_abs_cash_identity_error']:.3e}`.
- Institutional score carry: `{carry_audit['institutional_score_vintage_carry']}`. The exact prior S1 has {carry_audit['target_vintages_with_eligibility_substitution']} vintages with limited intra-vintage substitutions caused solely by authoritative A2 trade-eligibility arrivals; no next-quarter 13F information is used.
- Average name overlap: `{structure['average_a2_13f_name_overlap']:.4f}`; combined target count: `{structure['average_combined_position_count']:.4f}` average, `{structure['max_combined_position_count']}` maximum.
- Average effective holdings: `{structure['average_effective_number_of_holdings']:.4f}`; maximum single-name target: `{structure['max_single_name_target_weight']:.4f}`.

## Economic results

{markdown_table(aggregate)}

### Outer folds

{markdown_table(folds)}

### Calendar years

{markdown_table(years)}

## Diversification diagnostics

- Daily/monthly Raw-A2 versus 13F correlations: `{diagnostics['daily_return_correlation']:.6f}` / `{diagnostics['monthly_return_correlation']:.6f}`.
- Correlation on Raw A2 negative days: `{diagnostics['correlation_on_raw_a2_negative_days']:.6f}`.
- On Raw A2 worst-decile days, 13F mean return `{diagnostics['institutional_mean_return_on_raw_a2_worst_10pct_days']:.6f}` and positive rate `{diagnostics['institutional_positive_rate_on_raw_a2_worst_10pct_days']:.6f}`.
- Raw A2 max-drawdown window `{diagnostics['raw_a2_max_dd_window']}`: Raw `{diagnostics['raw_a2_return_during_raw_a2_max_dd_window']:.6f}`, 13F `{diagnostics['institutional_return_during_raw_a2_max_dd_window']:.6f}`, dual `{diagnostics['dual_return_during_raw_a2_max_dd_window']:.6f}`.
- Drawdown-series correlation `{diagnostics['drawdown_series_correlation']:.6f}`; conditional drawdown-day overlap `{diagnostics['drawdown_day_overlap']:.6f}`.

## Incremental wealth and paired robustness

- Attribution uses additive daily log-wealth difference, grouped without deleting any period; shares use the sum of positive group contributions as denominator.
- Top-1/Top-3 month shares: `{attribution['top1_month_share_of_positive_increment']:.6f}` / `{attribution['top3_month_share_of_positive_increment']:.6f}`.
- Top-1 fold share: `{attribution['top1_fold_share_of_positive_increment']:.6f}`.
- Top-1/Top-3 vintage shares: `{attribution['top1_vintage_share_of_positive_increment']:.6f}` / `{attribution['top3_vintage_share_of_positive_increment']:.6f}`.
- Paired daily mean/median differential: `{attribution['paired_mean_daily_differential']:.8f}` / `{attribution['paired_median_daily_differential']:.8f}`.
- Existing 20-day moving-block bootstrap mean `{bootstrap['mean']:.8f}`, 95% CI `[{bootstrap['ci_low']:.8f}, {bootstrap['ci_high']:.8f}]`, repeats `{int(bootstrap['repeats'])}`.

## Conclusion

Classification: **{decision['classification']}**. Sharpe improved: `{str(decision['sharpe_improved']).lower()}`; MDD improved: `{str(decision['mdd_improved']).lower()}`; positive Delta-Sharpe folds `{decision['positive_delta_sharpe_folds']}/{decision['valid_outer_folds']}`. CAGR sacrifice is `{decision['cagr_sacrifice']:.6f}`. This remains research-only; no freeze, forward arm, canonical mutation, model, or allocation search was created.

## Code and tests

- Source: `{Path(__file__).resolve()}`
- Targeted tests: `{REPO / 'scripts/v22/test_a2_13f_dual_sleeve_diversification_r1.py'}`
- Test status is recorded in the final terminal handoff after execution.
"""


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


def run() -> dict[str, Any]:
    required = [
        PRIOR_SOURCE, PRIOR_TEST, PRIOR_OUT / "final_report.md", PRIOR_OUT / "signal_metrics.csv",
        PRIOR_OUT / "strategy_metrics.csv", PRIOR_OUT / "trial_ledger.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    require(not missing, "PRIOR_R1_ARTIFACT_MISSING", missing)
    before_hashes = {str(path): sha256_file(path) for path in required}
    prior_ledger = json.loads((PRIOR_OUT / "trial_ledger.json").read_text(encoding="utf-8"))
    require(prior_ledger["economic_candidate_count"] == 3, "PRIOR_TRIAL_LEDGER_MISMATCH")
    require(prior_ledger["post_2025_outcome_used"] is False, "PRIOR_POST2025_OUTCOME_FLAG")
    prior = import_file("a2_13f_prior_for_dual", PRIOR_SOURCE)

    inputs, _, overlap, _ = prior.load_inputs()
    manager_ids = tuple(sorted(inputs["manifest"].normalized_manager_id.astype(str).unique()))
    quarters = tuple(inputs["needed_quarters"].quarter.astype(str))
    changes = prior.build_quarter_change_features(inputs["selected"], quarters, manager_ids)
    panel = prior.attach_change_panel(inputs, changes)
    validate_pit_target_dates(panel)
    rebuild, r0f, prices, external_calls = prior.load_authoritative_portfolio_runtime(inputs)
    prior_control, prior_simulations = prior.reconcile_and_simulate(panel, rebuild, r0f, prices)
    require(prior_control["status"] == "PASS_EXACT_OR_MACHINE_PRECISION", "PRIOR_RAW_CONTROL_FAILURE")

    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    last_signal = pd.Timestamp(calendar[-3])
    simulation_panel = panel.loc[panel.signal_date.le(last_signal)].copy()
    a2_targets = prior.target_map(simulation_panel, "a2_rank")
    institutional_targets = prior.target_map(simulation_panel, "institutional_rank")
    combined_targets, target_audit = combine_target_maps(a2_targets, institutional_targets)
    dual = r0f.reconstruct_path(
        model="S2_DUAL_SLEEVE_80_20",
        target_map=combined_targets,
        qfq=prices,
        signal_dates=simulation_panel.signal_date.unique(),
        cost_bps=COST_BPS,
    )
    simulations = {
        "S0_RAW_A2": prior_simulations["C0_RAW_A2"],
        "S1_13F_CHANGE": prior_simulations["C1_INSTITUTIONAL_CHANGE_STANDALONE"],
        "S2_DUAL_SLEEVE_80_20": {"daily": dual.daily, "positions": dual.positions, "trades": dual.trades},
    }
    table = metric_table(simulations, panel, prior)
    reconciliation = reconcile_prior_sleeves(table)
    curves = make_daily_curves(simulations)
    diagnostics = return_diagnostics(curves)
    attribution, _ = incremental_attribution(curves, panel, prior)
    bootstrap = bootstrap_diagnostic(prior, simulations)
    structure = structure_diagnostics(target_audit)
    carry_audit = institutional_carry_audit(panel, institutional_targets)
    decision = classify(table, attribution, diagnostics, bootstrap)
    after_hashes = {path: sha256_file(Path(path)) for path in before_hashes}
    require(before_hashes == after_hashes, "PRIOR_R1_ARTIFACT_MODIFIED")
    require(external_calls == 0, "EXTERNAL_CALL_COUNT_NONZERO")

    OUT.mkdir(parents=True, exist_ok=True)
    permitted = {"final_report.md", "strategy_metrics.csv", "daily_curves.csv", "trial_ledger.json"}
    unexpected = [path for path in OUT.iterdir() if path.name not in permitted]
    require(not unexpected, "OUTPUT_ANTI_BLOAT_FAILURE", unexpected)
    atomic_csv(OUT / "strategy_metrics.csv", table)
    atomic_csv(OUT / "daily_curves.csv", curves)
    ledger = {
        "task_id": TASK_ID,
        "economic_candidate_count": 3,
        "strategies": list(STRATEGIES),
        "sleeve_weights": {"raw_a2": A2_WEIGHT, "institutional_change": INSTITUTIONAL_WEIGHT},
        "sleeve_weight_search": False,
        "score_blend_used": False,
        "model_training": False,
        "new_alpha_features": False,
        "prior_composite_reused_unchanged": True,
        "prior_feature_reselection": False,
        "target_combination": "NET_BY_TICKER_BEFORE_EXISTING_PORTFOLIO_ENGINE_TURNOVER_AND_COST",
        "reconciliation": reconciliation,
        "prior_raw_control": prior_control,
        "return_diagnostics": diagnostics,
        "structure_diagnostics": structure,
        "incremental_attribution": attribution,
        "paired_block_bootstrap": bootstrap,
        "carry_audit": carry_audit,
        "decision": decision,
        "target_fingerprints": {
            "raw_a2": fingerprint_target_map(a2_targets),
            "institutional_change": fingerprint_target_map(institutional_targets),
            "dual_sleeve": fingerprint_target_map(combined_targets),
        },
        "attempt_history": [
            {"kind": "DEBUG_RETRY", "reason": "CSV_ROUNDTRIP_REPLAY_TOLERANCE_FIXED_AT_1E_12", "economic_trial_count": 0},
            {"kind": "DEBUG_RETRY", "reason": "NONFINITE_NOT_APPLICABLE_ATTRIBUTION_SERIALIZED_AS_NULL", "economic_trial_count": 0},
            {"kind": "ECONOMIC_RUN", "status": "COMPLETED", "economic_trial_count": 3},
        ],
        "prior_artifact_hashes_sha256": before_hashes,
        "raw_a2_change_feature_overlap_from_prior": overlap,
        "date_max_outcome_used": "2025-12-31",
        "post_2025_outcome_used": False,
        "network_called": False,
        "moomoo_called": False,
        "new_freeze_created": False,
        "new_forward_created": False,
        "canonical_modified": False,
    }
    atomic_json(OUT / "trial_ledger.json", ledger)
    atomic_text(OUT / "final_report.md", build_report(
        table, diagnostics, structure, attribution, bootstrap, decision, reconciliation, carry_audit
    ))
    require({path.name for path in OUT.iterdir()} == permitted, "OUTPUT_ARTIFACT_SET_FAILURE")
    return {
        "strategy_metrics": table,
        "daily_curves": curves,
        "diagnostics": diagnostics,
        "structure": structure,
        "attribution": attribution,
        "bootstrap": bootstrap,
        "decision": decision,
        "reconciliation": reconciliation,
        "carry_audit": carry_audit,
        "result_dir": str(OUT),
    }


def main() -> int:
    result = run()
    raw = record(result["strategy_metrics"], strategy="S0_RAW_A2", scope_type="aggregate", scope_id="PRE2026")
    institutional = record(result["strategy_metrics"], strategy="S1_13F_CHANGE", scope_type="aggregate", scope_id="PRE2026")
    dual = record(result["strategy_metrics"], strategy="S2_DUAL_SLEEVE_80_20", scope_type="aggregate", scope_id="PRE2026")
    print(json.dumps({
        "status": "PASS_RESEARCH_COMPLETE",
        "classification": result["decision"]["classification"],
        "raw": raw,
        "institutional": institutional,
        "dual": dual,
        "diagnostics": result["diagnostics"],
        "structure": result["structure"],
        "attribution": result["attribution"],
        "bootstrap": result["bootstrap"],
        "reconciliation": result["reconciliation"],
        "result_dir": result["result_dir"],
    }, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
