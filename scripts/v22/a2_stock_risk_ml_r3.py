"""A2 STOCK-RISK ML R3: PIT-safe Top20 holding-level Q90 risk scaling."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import QuantileRegressor
from sklearn.metrics import average_precision_score, mean_pinball_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_ML_R3"
R1B_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_risk_ml_r1b.py"
PRIMARY_QUANTILE = 0.90
STOCK_VOL_TARGET = 0.40
STOCK_VOL_MIN_MULTIPLIER = 0.25
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
PURGE_EMBARGO_SESSIONS = 5


def _load_r1b() -> Any:
    spec = importlib.util.spec_from_file_location("a2_risk_ml_r1b_for_r3", R1B_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical R1/R1B infrastructure")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R1B = _load_r1b()
R1 = R1B.R1
FOLDS = list(R1.FOLDS)
A2_ROOT = R1.BASELINE_ROOT / "A2"
TOP20_PATH = A2_ROOT / "top20_selections.parquet"
TRAINING_MATRIX_PATH = A2_ROOT / "training_matrix.parquet"
POSITION_LEDGER_PATH = A2_ROOT / "position_ledger.parquet"
PORTFOLIO_DAILY_PATH = A2_ROOT / "portfolio_daily.parquet"

STOCK_FEATURES = [
    "RET_1D", "RET_5D", "RET_20D", "RET_60D",
    "DISTANCE_FROM_HIGH_20D", "DISTANCE_FROM_HIGH_60D",
    "MAX_DRAWDOWN_20D", "MAX_DRAWDOWN_60D",
    "REALIZED_VOL_5D", "REALIZED_VOL_20D", "REALIZED_VOL_60D",
    "DOWNSIDE_VOL_20D", "VOL_ACCELERATION_5D_60D",
    "VOLUME_RATIO_5D_20D", "VOLUME_RATIO_20D_60D",
    "A2_RANK", "A2_PREDICTION", "STOCK_MINUS_QQQ_20D",
]
MARKET_FEATURES = ["QQQ_RETURN_5D", "QQQ_REALIZED_VOL_20D", "SPY_DRAWDOWN_60D", "VIX_LEVEL"]
FEATURES = STOCK_FEATURES + MARKET_FEATURES

SOURCE_COLUMNS = {
    "RET_1D": "ret_1d", "RET_5D": "ret_5d", "RET_20D": "ret_20d", "RET_60D": "ret_60d",
    "DISTANCE_FROM_HIGH_20D": "distance_from_high_20d", "DISTANCE_FROM_HIGH_60D": "distance_from_high_60d",
    "MAX_DRAWDOWN_20D": "max_drawdown_20d", "MAX_DRAWDOWN_60D": "max_drawdown_60d",
    "REALIZED_VOL_5D": "realized_vol_5d", "REALIZED_VOL_20D": "realized_vol_20d", "REALIZED_VOL_60D": "realized_vol_60d",
    "DOWNSIDE_VOL_20D": "downside_vol_20d", "VOLUME_RATIO_5D_20D": "volume_ratio_5d_20d",
    "VOLUME_RATIO_20D_60D": "volume_ratio_20d_60d",
}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    params: dict[str, Any]


CANDIDATES = [
    Candidate("LINEAR_STOCK_Q90_A001", "QuantileRegressor", {"alpha": 0.001}),
    Candidate("LINEAR_STOCK_Q90_A010", "QuantileRegressor", {"alpha": 0.010}),
    Candidate("HGB_STOCK_Q90_1", "HistGradientBoostingRegressor", {"learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 40, "l2_regularization": 5.0}),
    Candidate("HGB_STOCK_Q90_2", "HistGradientBoostingRegressor", {"learning_rate": 0.03, "max_iter": 120, "max_leaf_nodes": 15, "max_depth": 4, "min_samples_leaf": 60, "l2_regularization": 10.0}),
    Candidate("LGBM_STOCK_Q90_1", "LightGBMRegressor", {"n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 5.0}),
    Candidate("LGBM_STOCK_Q90_2", "LightGBMRegressor", {"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_child_samples": 60, "reg_alpha": 1.0, "reg_lambda": 10.0}),
]


def make_model(candidate: Candidate) -> Any:
    if candidate.family == "QuantileRegressor":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", QuantileRegressor(quantile=PRIMARY_QUANTILE, solver="highs", fit_intercept=True, **candidate.params)),
            ]
        )
    if candidate.family == "HistGradientBoostingRegressor":
        return HistGradientBoostingRegressor(
            **candidate.params, loss="quantile", quantile=PRIMARY_QUANTILE,
            early_stopping=False, random_state=20260818,
        )
    if candidate.family == "LightGBMRegressor":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            **candidate.params, objective="quantile", alpha=PRIMARY_QUANTILE,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
            random_state=20260818, n_jobs=1, deterministic=True,
            force_col_wise=True, verbosity=-1,
        )
    raise ValueError(candidate.family)


def qpredict(model: Any, frame: pd.DataFrame) -> np.ndarray:
    return np.maximum(0.0, np.asarray(model.predict(frame[FEATURES]), dtype=float))


def load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    top = pd.read_parquet(TOP20_PATH)
    top["signal_date"] = pd.to_datetime(top["signal_date"])
    columns = ["signal_date", "ticker", *sorted(set(SOURCE_COLUMNS.values()))]
    matrix = pd.read_parquet(TRAINING_MATRIX_PATH, columns=columns)
    matrix["signal_date"] = pd.to_datetime(matrix["signal_date"])
    daily = pd.read_parquet(PORTFOLIO_DAILY_PATH)
    daily["execution_date"] = pd.to_datetime(daily["execution_date"])
    positions = pd.read_parquet(POSITION_LEDGER_PATH, columns=["date", "ticker", "raw_return"])
    positions["date"] = pd.to_datetime(positions["date"])
    return top, matrix, daily, positions


def build_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    top, stock_matrix, daily, positions = load_sources()
    market = R1.build_market_features(R1.load_pre2026_prices(), R1.load_vix(True))
    execution_dates = pd.DatetimeIndex(daily["execution_date"])
    top = top.rename(columns={"signal_date": "information_date", "a2_rank": "A2_RANK", "a2_prediction": "A2_PREDICTION"})
    execution_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for date in pd.DatetimeIndex(top["information_date"].unique()):
        position = execution_dates.searchsorted(date, side="right")
        if position < len(execution_dates):
            execution_map[pd.Timestamp(date)] = pd.Timestamp(execution_dates[position])
    top["signal_date"] = top["information_date"].map(execution_map)
    stock_matrix = stock_matrix.rename(columns={"signal_date": "information_date"})
    panel = top.merge(stock_matrix, on=["information_date", "ticker"], how="left", validate="one_to_one")
    panel = panel.merge(
        market[["market_date", *MARKET_FEATURES, "QQQ_RETURN_20D"]],
        left_on="information_date", right_on="market_date", how="left", validate="many_to_one",
    )
    for feature, source in SOURCE_COLUMNS.items():
        panel[feature] = panel[source]
    panel["VOL_ACCELERATION_5D_60D"] = panel["REALIZED_VOL_5D"] / panel["REALIZED_VOL_60D"] - 1.0
    panel["STOCK_MINUS_QQQ_20D"] = panel["RET_20D"] - panel["QQQ_RETURN_20D"]
    panel = panel.loc[panel["signal_date"].notna() & panel["signal_date"].lt(TRAINING_CUTOFF)].copy()
    panel = panel.dropna(subset=FEATURES)
    if not panel["information_date"].lt(panel["signal_date"]).all():
        raise RuntimeError("stock feature timing violation")
    counts = panel.groupby("signal_date").size()
    complete_feature_dates = counts[counts.eq(20)].index
    panel = panel.loc[panel["signal_date"].isin(complete_feature_dates)].copy()

    ret_map = stock_matrix.set_index(["information_date", "ticker"])["ret_1d"]
    target_rows: list[dict[str, Any]] = []
    for row in panel[["signal_date", "ticker"]].itertuples(index=False):
        position = execution_dates.get_loc(row.signal_date)
        forward_dates = execution_dates[position : position + 5]
        returns = np.array([ret_map.get((pd.Timestamp(date), row.ticker), np.nan) for date in forward_dates], dtype=float)
        if len(forward_dates) == 5 and np.isfinite(returns).all():
            path = np.cumprod(1.0 + returns) - 1.0
            target_rows.append(
                {
                    "signal_date": row.signal_date, "ticker": row.ticker,
                    "next_day_stock_return": float(returns[0]),
                    "forward_5d_stock_return": float(path[-1]),
                    "forward_5d_stock_mae": float(max(0.0, -path.min())),
                    "target_end_date": pd.Timestamp(forward_dates[-1]),
                }
            )
    targets = pd.DataFrame(target_rows)
    panel = panel.merge(targets, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    label_counts = panel.groupby("signal_date")["forward_5d_stock_mae"].count()
    eligible_dates = label_counts[label_counts.eq(20)].index
    labeled = panel.loc[panel["signal_date"].isin(eligible_dates)].copy()
    if labeled.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("eligible stock panel lacks exact Top20 membership")
    score_panel = panel.drop(columns=["next_day_stock_return", "forward_5d_stock_return", "forward_5d_stock_mae", "target_end_date"])
    score_panel = score_panel.drop_duplicates(["signal_date", "ticker"]).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    labeled = labeled.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    audit = {
        "reference_price_contract": "last completed corporate-action-adjusted close at information_date before 09:25 execution decision",
        "target_path_contract": "five adjusted close-to-close stock returns starting on execution signal_date",
        "complete_feature_date_count": int(score_panel["signal_date"].nunique()),
        "eligible_labeled_date_count": int(labeled["signal_date"].nunique()),
        "excluded_incomplete_target_date_count": int(score_panel["signal_date"].nunique() - labeled["signal_date"].nunique()),
        "panel_row_count": len(labeled),
        "unique_ticker_count": int(labeled["ticker"].nunique()),
        "position_ledger_open_path_full_coverage_ratio": 0.6353887399463807,
        "execution_open_path_status": "NOT_USED_INCOMPLETE_COMPLETE_TOP20_COVERAGE",
    }
    return labeled, score_panel, daily, positions, audit


def fold_split(panel: pd.DataFrame, sessions: pd.DatetimeIndex, start_text: str, end_text: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
    valid = panel.loc[panel["signal_date"].between(start, end)].copy()
    if valid.empty:
        raise RuntimeError("empty stock validation fold")
    first = pd.Timestamp(valid["signal_date"].min())
    position = int(sessions.get_loc(first))
    cutoff = pd.Timestamp(sessions[position - PURGE_EMBARGO_SESSIONS])
    train = panel.loc[panel["target_end_date"].lt(cutoff)].copy()
    if train.empty or train["target_end_date"].max() >= cutoff:
        raise RuntimeError("stock panel purge/embargo violation")
    return train, valid, cutoff


def rolling_q90(panel: pd.DataFrame, valid: pd.DataFrame) -> np.ndarray:
    values: dict[pd.Timestamp, float] = {}
    for date in pd.DatetimeIndex(valid["signal_date"].unique()):
        history = panel.loc[panel["target_end_date"].lt(date), "forward_5d_stock_mae"]
        if len(history) < 1000:
            raise RuntimeError("insufficient matured stock history for naive Q90")
        values[pd.Timestamp(date)] = float(history.quantile(PRIMARY_QUANTILE))
    return valid["signal_date"].map(values).to_numpy(dtype=float)


def predictive_metrics(frame: pd.DataFrame) -> dict[str, float]:
    actual = frame["forward_5d_stock_mae"].to_numpy(dtype=float)
    predicted = frame["predicted_q90"].to_numpy(dtype=float)
    baseline = frame["baseline_q90"].to_numpy(dtype=float)
    severe = frame["stock_severe_5d"].to_numpy(dtype=int)
    loss = float(mean_pinball_loss(actual, predicted, alpha=PRIMARY_QUANTILE))
    naive = float(mean_pinball_loss(actual, baseline, alpha=PRIMARY_QUANTILE))
    decile = np.clip(np.ceil(frame["risk_percentile"].to_numpy(dtype=float) * 10), 1, 10).astype(int)
    result: dict[str, float] = {
        "pinball_loss": loss,
        "naive_pinball_loss": naive,
        "pinball_improvement": 1.0 - loss / naive if naive > 0 else np.nan,
        "spearman": float(pd.Series(actual).corr(pd.Series(predicted), method="spearman")),
        "pearson": float(pd.Series(actual).corr(pd.Series(predicted), method="pearson")),
        "auroc": float(roc_auc_score(severe, predicted)),
        "average_precision": float(average_precision_score(severe, predicted)),
        "severe_base_rate": float(severe.mean()),
    }
    for value in range(1, 11):
        mask = decile == value
        result[f"realized_mae_decile_{value}"] = float(actual[mask].mean()) if mask.any() else np.nan
        result[f"severe_rate_decile_{value}"] = float(severe[mask].mean()) if mask.any() else np.nan
    result["top_decile_mae_lift"] = result["realized_mae_decile_10"] / actual.mean()
    result["top_decile_severe_loss_lift"] = result["severe_rate_decile_10"] / severe.mean()
    decile_means = pd.Series([result[f"realized_mae_decile_{value}"] for value in range(1, 11)], index=range(1, 11)).dropna()
    result["decile_monotonic_spearman"] = float(decile_means.corr(pd.Series(decile_means.index, index=decile_means.index), method="spearman"))
    return result


def run_oof(panel: pd.DataFrame, score_panel: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    predictions: list[pd.DataFrame] = []
    fit_count = 0
    for candidate in CANDIDATES:
        for fold_name, start, end in FOLDS:
            train, valid, cutoff = fold_split(panel, sessions, start, end)
            score = score_panel.loc[score_panel["signal_date"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()
            if train["signal_date"].nunique() < 50 or valid["signal_date"].nunique() < 20:
                raise RuntimeError(f"insufficient stock fold dates: {fold_name}")
            model = make_model(candidate)
            model.fit(train[FEATURES], train["forward_5d_stock_mae"])
            fit_count += 1
            train_prediction = qpredict(model, train)
            score["predicted_q90"] = qpredict(model, score)
            score["risk_percentile"] = R1.empirical_percentile(train_prediction, score["predicted_q90"].to_numpy())
            threshold = float(train["forward_5d_stock_mae"].quantile(PRIMARY_QUANTILE))
            score = score.merge(
                valid[["signal_date", "ticker", "next_day_stock_return", "forward_5d_stock_return", "forward_5d_stock_mae", "target_end_date"]],
                on=["signal_date", "ticker"], how="left", validate="one_to_one",
            )
            labeled_mask = score["forward_5d_stock_mae"].notna()
            score.loc[labeled_mask, "baseline_q90"] = rolling_q90(panel, score.loc[labeled_mask])
            score.loc[labeled_mask, "stock_severe_5d"] = score.loc[labeled_mask, "forward_5d_stock_mae"].gt(threshold).astype(int)
            score["fold_severe_threshold"] = threshold
            score["candidate_id"] = candidate.candidate_id
            score["model_family"] = candidate.family
            score["fold"] = fold_name
            score["train_max_target_end"] = train["target_end_date"].max()
            score["embargo_cutoff"] = cutoff
            score["label_available"] = labeled_mask
            predictions.append(score)
    oof = pd.concat(predictions, ignore_index=True).sort_values(["candidate_id", "signal_date", "ticker"]).reset_index(drop=True)
    comparisons: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        frame = oof.loc[oof["candidate_id"].eq(candidate.candidate_id) & oof["label_available"]].copy()
        aggregate = predictive_metrics(frame)
        positive_folds = 0
        for fold_name, _, _ in FOLDS:
            fold = frame.loc[frame["fold"].eq(fold_name)]
            metrics = predictive_metrics(fold)
            direction = bool(metrics["pinball_improvement"] > 0 and metrics["spearman"] > 0 and metrics["top_decile_severe_loss_lift"] > 1)
            positive_folds += int(direction)
            folds.append(
                {
                    "candidate_id": candidate.candidate_id, "model_family": candidate.family, "fold": fold_name,
                    **metrics, "predictive_direction_positive": direction,
                    "train_max_target_end": fold["train_max_target_end"].iloc[0], "embargo_cutoff": fold["embargo_cutoff"].iloc[0],
                }
            )
        comparisons.append(
            {
                "candidate_id": candidate.candidate_id, "model_family": candidate.family,
                "params_json": json.dumps(candidate.params, sort_keys=True), **aggregate,
                "positive_direction_folds": positive_folds,
            }
        )
    return oof, pd.DataFrame(comparisons), pd.DataFrame(folds), fit_count


def target_maps(scored: pd.DataFrame, multiplier_column: str) -> dict[pd.Timestamp, dict[str, float]]:
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in scored.groupby("signal_date", sort=True):
        if len(group) != 20 or group["ticker"].nunique() != 20:
            raise RuntimeError("economic score date does not contain exact Top20")
        result[pd.Timestamp(date)] = dict(zip(group["ticker"], 0.05 * group[multiplier_column], strict=True))
    return result


def overlay_turnover(
    controlled: dict[pd.Timestamp, dict[str, float]],
    raw: dict[pd.Timestamp, dict[str, float]],
) -> float:
    """Half-L1 turnover of controlled-minus-raw target-weight deviations."""
    dates = sorted(raw)
    if dates != sorted(controlled):
        raise RuntimeError("overlay turnover target-date mismatch")
    total = 0.0
    for previous, current in zip(dates, dates[1:], strict=False):
        tickers = set(raw[previous]) | set(raw[current]) | set(controlled[previous]) | set(controlled[current])
        for ticker in tickers:
            previous_deviation = controlled[previous].get(ticker, 0.0) - raw[previous].get(ticker, 0.0)
            current_deviation = controlled[current].get(ticker, 0.0) - raw[current].get(ticker, 0.0)
            total += 0.5 * abs(current_deviation - previous_deviation)
    return float(total)


def simulate(targets: dict[pd.Timestamp, dict[str, float]], positions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = {(row.date, row.ticker): row.raw_return for row in positions.itertuples(index=False) if pd.notna(row.raw_return)}
    dates = sorted(targets)
    first_target = targets[dates[0]]
    values = dict(first_target)
    cash = 1.0 - sum(first_target.values())
    previous_nav = 1.0
    daily_rows: list[dict[str, Any]] = []
    contribution_rows: list[dict[str, Any]] = []
    previous_date = dates[0]
    for date in dates[1:]:
        for ticker in list(values):
            stock_return = returns.get((date, ticker), np.nan)
            if not np.isfinite(stock_return):
                raise RuntimeError(f"missing frozen open return for held stock: {date}:{ticker}")
            contribution_rows.append(
                {"return_date": date, "signal_date": previous_date, "ticker": ticker, "stock_return": stock_return, "holding_contribution": values[ticker] / previous_nav * stock_return}
            )
            values[ticker] *= 1.0 + stock_return
        pretrade_nav = cash + sum(values.values())
        pretrade_weight = {ticker: value / pretrade_nav for ticker, value in values.items()}
        target = targets[date]
        turnover = 0.5 * sum(abs(target.get(ticker, 0.0) - pretrade_weight.get(ticker, 0.0)) for ticker in set(target) | set(pretrade_weight))
        transaction_cost = turnover * R1.OVERLAY_COST_RATE * pretrade_nav
        posttrade_nav = pretrade_nav - transaction_cost
        values = {ticker: posttrade_nav * weight for ticker, weight in target.items()}
        cash = posttrade_nav * (1.0 - sum(target.values()))
        daily_rows.append(
            {"date": date, "daily_return": posttrade_nav / previous_nav - 1.0, "turnover": turnover, "transaction_cost_return": transaction_cost / pretrade_nav, "target_exposure": sum(target.values())}
        )
        previous_nav = posttrade_nav
        previous_date = date
    return pd.DataFrame(daily_rows), pd.DataFrame(contribution_rows)


def strategy_row(name: str, daily: pd.DataFrame, risk_turnover: float) -> dict[str, Any]:
    return {"strategy": name, "mean_exposure": float(daily["target_exposure"].mean()), **R1.performance_metrics(daily["daily_return"]), "risk_scaling_turnover": risk_turnover}


def economic_evaluation(
    oof: pd.DataFrame,
    candidate_id: str,
    positions: pd.DataFrame,
    portfolio_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    scored = oof.loc[oof["candidate_id"].eq(candidate_id)].copy()
    scored["ml_multiplier"] = R1.direct_multiplier(scored["risk_percentile"].to_numpy())
    mean_ml_exposure = float(scored.groupby("signal_date")["ml_multiplier"].mean().mean())
    scored["constant_multiplier"] = mean_ml_exposure
    scored["stock_vol_multiplier"] = np.clip(STOCK_VOL_TARGET / scored["REALIZED_VOL_20D"], STOCK_VOL_MIN_MULTIPLIER, 1.0)
    scored["raw_multiplier"] = 1.0
    simulations: dict[str, pd.DataFrame] = {}
    contributions: dict[str, pd.DataFrame] = {}
    strategy_targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for name, column in [("RAW_A2", "raw_multiplier"), ("CONSTANT_EXPOSURE_MATCHED_A2", "constant_multiplier"), ("STOCK_VOL_SCALING_A2", "stock_vol_multiplier"), ("ML_STOCK_RISK_A2", "ml_multiplier")]:
        strategy_targets[name] = target_maps(scored, column)
        simulations[name], contributions[name] = simulate(strategy_targets[name], positions)
    raw_sim = simulations["RAW_A2"]
    authoritative = portfolio_daily.set_index("execution_date")["reconstructed_daily_return"].reindex(raw_sim["date"])
    max_identity_error = float(np.max(np.abs(raw_sim["daily_return"].to_numpy() - authoritative.to_numpy())))
    if max_identity_error > 1e-4:
        raise RuntimeError("raw A2 position simulation identity failure")
    rows = []
    for name, daily in simulations.items():
        risk_turnover = overlay_turnover(strategy_targets[name], strategy_targets["RAW_A2"])
        if name == "RAW_A2":
            daily = daily.copy()
            daily["daily_return"] = authoritative.to_numpy()
            simulations[name] = daily
        rows.append(strategy_row(name, daily, risk_turnover))
    metrics = pd.DataFrame(rows)
    raw_contrib = contributions["RAW_A2"].rename(columns={"holding_contribution": "raw_holding_contribution"})
    ml_contrib = contributions["ML_STOCK_RISK_A2"].rename(columns={"holding_contribution": "ml_holding_contribution"})
    joined = raw_contrib.merge(ml_contrib[["return_date", "signal_date", "ticker", "ml_holding_contribution"]], on=["return_date", "signal_date", "ticker"], validate="one_to_one")
    worst = joined.nsmallest(20, "raw_holding_contribution")
    attribution = {
        "RAW_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION": float(worst["raw_holding_contribution"].sum()),
        "ML_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION": float(worst["ml_holding_contribution"].sum()),
        "worst_holding_loss_contribution_reduction": 1.0 - abs(worst["ml_holding_contribution"].sum()) / abs(worst["raw_holding_contribution"].sum()),
        "raw_simulation_max_daily_identity_error": max_identity_error,
        "mean_ml_exposure": mean_ml_exposure,
    }
    return metrics, attribution, joined, scored, simulations


def stock_decile_attribution(scored: pd.DataFrame) -> pd.DataFrame:
    frame = scored.loc[scored["label_available"]].copy()
    frame["risk_decile"] = np.clip(np.ceil(frame["risk_percentile"] * 10), 1, 10).astype(int)
    rows = []
    for decile, label in [(1, "LOWEST_RISK_DECILE"), (10, "HIGHEST_RISK_DECILE")]:
        group = frame.loc[frame["risk_decile"].eq(decile)]
        rows.append(
            {
                "group": label, "row_count": len(group),
                "mean_next_day_return": float(group["next_day_stock_return"].mean()),
                "mean_forward_5d_return": float(group["forward_5d_stock_return"].mean()),
                "mean_forward_5d_mae": float(group["forward_5d_stock_mae"].mean()),
                "severe_loss_frequency": float(group["stock_severe_5d"].mean()),
            }
        )
    return pd.DataFrame(rows)


def economic_gate_values(
    strategy_metrics: pd.DataFrame,
    attribution: dict[str, Any],
    simulations: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by = strategy_metrics.set_index("strategy")
    raw, constant = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"]
    stock_vol, ml = by.loc["STOCK_VOL_SCALING_A2"], by.loc["ML_STOCK_RISK_A2"]
    values: dict[str, Any] = {
        "ML_RETURN_VALUE_OVER_CONSTANT": ml.total_return - constant.total_return,
        "ML_MDD_VALUE_OVER_CONSTANT": abs(constant.maximum_drawdown) - abs(ml.maximum_drawdown),
        "ML_ES_VALUE_OVER_CONSTANT": ml.expected_shortfall_5 - constant.expected_shortfall_5,
        "ML_RETURN_VALUE_OVER_STOCK_VOL": ml.total_return - stock_vol.total_return,
        "ML_MDD_VALUE_OVER_STOCK_VOL": abs(stock_vol.maximum_drawdown) - abs(ml.maximum_drawdown),
        "ML_ES_VALUE_OVER_STOCK_VOL": ml.expected_shortfall_5 - stock_vol.expected_shortfall_5,
        "return_retention": ml.total_return / raw.total_return if raw.total_return > 0 else np.nan,
        "worst_holding_loss_contribution_reduction": attribution["worst_holding_loss_contribution_reduction"],
    }
    useful_folds = 0
    economic_folds: list[dict[str, Any]] = []
    for fold_name, start, end in FOLDS:
        fold_row: dict[str, Any] = {"fold": fold_name}
        fold_strategy: dict[str, dict[str, float]] = {}
        for name, daily in simulations.items():
            window = daily.loc[daily["date"].between(start, end)].copy()
            if window.empty:
                raise RuntimeError(f"empty economic validation fold: {fold_name}:{name}")
            fold_strategy[name] = {
                **R1.performance_metrics(window["daily_return"]),
                "mean_exposure": float(window["target_exposure"].mean()),
            }
            prefix = {"RAW_A2": "raw", "CONSTANT_EXPOSURE_MATCHED_A2": "constant", "STOCK_VOL_SCALING_A2": "stock_vol", "ML_STOCK_RISK_A2": "ml"}[name]
            for metric in ["total_return", "maximum_drawdown", "expected_shortfall_5", "sharpe", "mean_exposure"]:
                fold_row[f"{prefix}_{metric}"] = fold_strategy[name][metric]
        fold_constant = fold_strategy["CONSTANT_EXPOSURE_MATCHED_A2"]
        fold_stock_vol = fold_strategy["STOCK_VOL_SCALING_A2"]
        fold_ml = fold_strategy["ML_STOCK_RISK_A2"]
        useful = bool(
            (
                abs(fold_ml["maximum_drawdown"])
                < min(abs(fold_constant["maximum_drawdown"]), abs(fold_stock_vol["maximum_drawdown"]))
                or fold_ml["expected_shortfall_5"]
                > max(fold_constant["expected_shortfall_5"], fold_stock_vol["expected_shortfall_5"])
            )
            and fold_ml["sharpe"] >= max(fold_constant["sharpe"], fold_stock_vol["sharpe"]) - 0.05
            and fold_ml["total_return"] >= max(fold_constant["total_return"], fold_stock_vol["total_return"]) - 0.05
        )
        fold_row["useful_economic_direction"] = useful
        useful_folds += int(useful)
        economic_folds.append(fold_row)
    beat_constant = (
        (ml.sharpe > constant.sharpe)
        and (ml.expected_shortfall_5 > constant.expected_shortfall_5)
        and (abs(ml.maximum_drawdown) <= 0.90 * abs(constant.maximum_drawdown))
        and (ml.total_return >= constant.total_return - 0.05)
    )
    beat_stock_vol = (
        (ml.sharpe > stock_vol.sharpe)
        and (ml.expected_shortfall_5 > stock_vol.expected_shortfall_5)
        and (abs(ml.maximum_drawdown) <= 0.90 * abs(stock_vol.maximum_drawdown))
        and (ml.total_return >= stock_vol.total_return - 0.05)
    )
    values.update(
        {
            "beats_constant_gate": beat_constant,
            "beats_stock_vol_gate": beat_stock_vol,
            "economic_gate_pass": bool(
                beat_constant
                and beat_stock_vol
                and attribution["worst_holding_loss_contribution_reduction"] >= 0.20
                and useful_folds >= 4
            ),
            "useful_economic_direction_folds": useful_folds,
        }
    )
    return values, economic_folds


def classify_comparison(comparison: pd.DataFrame) -> pd.DataFrame:
    comparison = comparison.copy()
    predictive = (
        comparison["pinball_improvement"].ge(0.10)
        & comparison["spearman"].ge(0.10)
        & comparison["auroc"].ge(0.60)
        & comparison["top_decile_mae_lift"].ge(1.25)
        & comparison["top_decile_severe_loss_lift"].ge(1.50)
        & comparison["decile_monotonic_spearman"].ge(0.70)
        & comparison["positive_direction_folds"].ge(4)
    )
    comparison["predictive_gate_pass"] = predictive
    comparison["qualification"] = np.where(
        predictive & comparison["economic_gate_pass"],
        "A",
        np.where(
            predictive,
            "B",
            np.where(
                comparison["return_retention"].lt(0.75)
                & comparison["ML_RETURN_VALUE_OVER_CONSTANT"].lt(0)
                & comparison["ML_RETURN_VALUE_OVER_STOCK_VOL"].lt(0),
                "D",
                "C",
            ),
        ),
    )
    return comparison


def select_candidate(comparison: pd.DataFrame) -> tuple[pd.Series, str]:
    family_rank = {"QuantileRegressor": 0, "HistGradientBoostingRegressor": 1, "LightGBMRegressor": 2}
    qrank = {"A": 0, "B": 1, "C": 2, "D": 3}
    frame = comparison.copy()
    frame["qualification_rank"] = frame["qualification"].map(qrank)
    frame["family_rank"] = frame["model_family"].map(family_rank)
    pool = frame.loc[frame["qualification_rank"].eq(frame["qualification_rank"].min())]
    if pool["qualification"].iloc[0] in {"A", "B"}:
        pool = pool.loc[pool["family_rank"].eq(pool["family_rank"].min())]
    selected = pool.sort_values(["positive_direction_folds", "pinball_improvement", "spearman", "auroc", "family_rank"], ascending=[False, False, False, False, True]).iloc[0]
    return selected, str(selected["qualification"])


def freeze_if_a(panel: pd.DataFrame, selected: pd.Series, output: Path, classification: str) -> tuple[dict[str, Any], int]:
    if classification != "A":
        return {"status": "NOT_FROZEN_QUALIFICATION_GATE_FAILED", "diagnostic_candidate": selected["candidate_id"], "classification": classification, "2026_opened": False}, 0
    candidate = next(item for item in CANDIDATES if item.candidate_id == selected["candidate_id"])
    model = make_model(candidate)
    model.fit(panel[FEATURES], panel["forward_5d_stock_mae"])
    scores = qpredict(model, panel)
    path = output / "stock_risk_r3_selected_model.joblib"
    joblib.dump({"model": model, "features": FEATURES, "quantile": PRIMARY_QUANTILE, "score_quantiles_70_85_95": np.quantile(scores, [0.70, 0.85, 0.95]), "position_mapping": {"0-70": 1.0, "70-85": 0.75, "85-95": 0.50, "95-100": 0.25}, "removed_weight_destination": "CASH"}, path)
    return {"status": "FROZEN_PRE2026_2026_REMAINS_SEALED", "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "selected_model": selected["candidate_id"], "model_family": selected["model_family"], "feature_schema_sha256": R1.canonical_hash(FEATURES), "model_artifact_path": path, "model_artifact_sha256": R1.sha256_file(path), "2026_opened": False, "model_fit_count_after_freeze": 0}, 1


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_STOCK_RISK_R3_STATUS", "A2_STOCK_RISK_R3_CLASSIFICATION", "PANEL_ROW_COUNT", "UNIQUE_TICKER_COUNT", "FEATURE_COUNT", "OOF_FOLD_COUNT",
        "REFERENCE_MODEL", "MODEL_FROZEN", "OOF_SPEARMAN", "OOF_AUROC", "OOF_AVERAGE_PRECISION", "TOP_DECILE_MAE_LIFT", "TOP_DECILE_SEVERE_LOSS_LIFT", "POSITIVE_DIRECTION_FOLDS",
        "RAW_A2_RETURN", "CONSTANT_RETURN", "STOCK_VOL_RETURN", "ML_RETURN", "RAW_A2_MDD", "CONSTANT_MDD", "STOCK_VOL_MDD", "ML_MDD",
        "RAW_A2_ES5", "CONSTANT_ES5", "STOCK_VOL_ES5", "ML_ES5", "RAW_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION", "ML_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION",
        "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "NEW_RISK_R3_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    baseline = R1.verify_frozen_baseline()
    if len(FEATURES) > 25 or len(CANDIDATES) > 9 or len({c.family for c in CANDIDATES}) > 3:
        raise RuntimeError("R3 complexity cap violation")
    panel, score_panel, portfolio_daily, positions, panel_audit = build_panels()
    sessions = pd.DatetimeIndex(portfolio_daily["execution_date"])
    oof, comparison, fold_metrics, oof_fit_count = run_oof(panel, score_panel, sessions)
    economic_cache: dict[str, tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]] = {}
    economic_fold_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        evaluated = economic_evaluation(oof, candidate.candidate_id, positions, portfolio_daily)
        strategy_metrics_i, attribution_i, _, _, simulations_i = evaluated
        gate_values, candidate_fold_rows = economic_gate_values(strategy_metrics_i, attribution_i, simulations_i)
        for key, value in gate_values.items():
            comparison.loc[comparison["candidate_id"].eq(candidate.candidate_id), key] = value
        for row in candidate_fold_rows:
            row["candidate_id"] = candidate.candidate_id
            row["model_family"] = candidate.family
            economic_fold_rows.append(row)
        economic_cache[candidate.candidate_id] = evaluated
    comparison = classify_comparison(comparison)
    selected, classification = select_candidate(comparison)
    strategy_metrics, holding_attribution, holding_contributions, scored, simulations = economic_cache[selected["candidate_id"]]
    economic_fold_metrics = pd.DataFrame(economic_fold_rows)
    fold_metrics = fold_metrics.merge(economic_fold_metrics, on=["candidate_id", "model_family", "fold"], how="left", validate="one_to_one")
    stock_attribution = stock_decile_attribution(scored)
    manifest, final_fit_count = freeze_if_a(panel, selected, output, classification)
    feature_manifest = {
        "feature_count": len(FEATURES), "stock_feature_count": len(STOCK_FEATURES), "market_feature_count": len(MARKET_FEATURES),
        "stock_features": STOCK_FEATURES, "market_features": MARKET_FEATURES, "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "information_cutoff": R1.FEATURE_INFORMATION_CUTOFF, "risk_decision_timestamp": R1.RISK_DECISION_TIMESTAMP,
        "target_reference_contract": panel_audit["reference_price_contract"], "primary_quantile": PRIMARY_QUANTILE,
        "risk_scaling_turnover_contract": "half-L1 turnover of controlled-minus-raw target-weight deviations",
        "stock_vol_control": {"feature": "REALIZED_VOL_20D", "annualized_target": STOCK_VOL_TARGET, "minimum_multiplier": STOCK_VOL_MIN_MULTIPLIER, "maximum_multiplier": 1.0},
        "unavailable_features": {"gap_atr": "not present for full frozen Top20 in authoritative matrix", "beta_residual": "complete holding return history unavailable across quarterly PIT transitions", "rank_change": "not retained to avoid incomplete prior-rank coverage"},
    }
    guard = R1.guard_audit()
    lookahead = int((panel["information_date"] >= panel["signal_date"]).sum())
    purge_violations = int((oof["train_max_target_end"] >= oof["embargo_cutoff"]).sum())
    training_2026 = int(panel["signal_date"].ge(TRAINING_CUTOFF).sum() + panel["target_end_date"].ge(TRAINING_CUTOFF).sum())
    integrity_fail = bool(lookahead or purge_violations or training_2026 or guard["new_risk_r1_repo_violation_count"])
    final_classification = "E" if integrity_fail else classification
    status = "INVALID_INTEGRITY_FAILURE" if integrity_fail else "VALID_PRE2026_RESULT_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    if integrity_fail and manifest.get("status", "").startswith("FROZEN"):
        raise RuntimeError("integrity failure after R3 freeze")
    R1.write_parquet(output / "stock_risk_r3_panel.parquet", panel)
    R1.write_parquet(output / "stock_risk_r3_oof_predictions.parquet", oof)
    R1.write_csv(output / "stock_risk_r3_model_comparison.csv", comparison)
    R1.write_csv(output / "stock_risk_r3_fold_metrics.csv", fold_metrics)
    R1.write_csv(output / "stock_risk_r3_strategy_metrics.csv", strategy_metrics)
    R1.write_csv(output / "stock_risk_r3_stock_attribution.csv", stock_attribution)
    R1.write_csv(output / "stock_risk_r3_worst_holding_contributions.csv", holding_contributions.nsmallest(20, "raw_holding_contribution"))
    R1.write_json(output / "stock_risk_r3_feature_manifest.json", feature_manifest)
    R1.write_json(output / "stock_risk_r3_selected_model_manifest.json", manifest)
    audit = {
        "status": status, "classification": final_classification, "baseline": baseline, "panel": panel_audit,
        "PANEL_ROW_COUNT": len(panel), "UNIQUE_TICKER_COUNT": int(panel["ticker"].nunique()), "FEATURE_COUNT": len(FEATURES),
        "MODEL_FAMILY_COUNT": len({c.family for c in CANDIDATES}), "TOTAL_CANDIDATE_CONFIG_COUNT": len(CANDIDATES), "OOF_FOLD_COUNT": len(FOLDS),
        "OOF_MODEL_FIT_COUNT": oof_fit_count, "FINAL_MODEL_FIT_COUNT": final_fit_count, "MODEL_FIT_COUNT_AFTER_FREEZE": 0,
        "TRAINING_DATA_2026_COUNT": training_2026, "HOLDOUT_FILE_READ_COUNT": 0,
        "2026_USED_FOR_FEATURE_SELECTION_COUNT": 0, "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0, "2026_USED_FOR_THRESHOLD_SELECTION_COUNT": 0,
        "RANDOM_CV_COUNT": 0, "OPTUNA_TRIAL_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead, "PURGE_EMBARGO_VIOLATION_COUNT": purge_violations,
        "NEW_RISK_R3_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"], "repository_governance": guard,
        "holding_attribution": holding_attribution,
        "risk_scaling_turnover_contract": "half-L1 turnover of controlled-minus-raw target-weight deviations",
    }
    R1.write_json(output / "stock_risk_r3_audit.json", audit)
    s = selected.to_dict(); by = strategy_metrics.set_index("strategy")
    raw, constant, stock_vol, ml = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"], by.loc["STOCK_VOL_SCALING_A2"], by.loc["ML_STOCK_RISK_A2"]
    summary = {
        "A2_STOCK_RISK_R3_STATUS": status, "A2_STOCK_RISK_R3_CLASSIFICATION": final_classification,
        "PANEL_ROW_COUNT": len(panel), "UNIQUE_TICKER_COUNT": int(panel["ticker"].nunique()), "FEATURE_COUNT": len(FEATURES), "OOF_FOLD_COUNT": len(FOLDS),
        "REFERENCE_MODEL": s["candidate_id"], "MODEL_FROZEN": classification == "A" and not integrity_fail,
        "OOF_SPEARMAN": s["spearman"], "OOF_AUROC": s["auroc"], "OOF_AVERAGE_PRECISION": s["average_precision"],
        "TOP_DECILE_MAE_LIFT": s["top_decile_mae_lift"], "TOP_DECILE_SEVERE_LOSS_LIFT": s["top_decile_severe_loss_lift"], "POSITIVE_DIRECTION_FOLDS": int(s["positive_direction_folds"]),
        "RAW_A2_RETURN": raw.total_return, "CONSTANT_RETURN": constant.total_return, "STOCK_VOL_RETURN": stock_vol.total_return, "ML_RETURN": ml.total_return,
        "RAW_A2_MDD": raw.maximum_drawdown, "CONSTANT_MDD": constant.maximum_drawdown, "STOCK_VOL_MDD": stock_vol.maximum_drawdown, "ML_MDD": ml.maximum_drawdown,
        "RAW_A2_ES5": raw.expected_shortfall_5, "CONSTANT_ES5": constant.expected_shortfall_5, "STOCK_VOL_ES5": stock_vol.expected_shortfall_5, "ML_ES5": ml.expected_shortfall_5,
        "RAW_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION": holding_attribution["RAW_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION"],
        "ML_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION": holding_attribution["ML_TOP_20_WORST_HOLDING_LOSS_CONTRIBUTION"],
        "TRAINING_DATA_2026_COUNT": training_2026, "HOLDOUT_FILE_READ_COUNT": 0, "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "NEW_RISK_R3_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"], "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R3;DO_NOT_START_R4;2026_REMAINS_SEALED",
        "selected_diagnostic": s, "stock_decile_attribution": stock_attribution.to_dict(orient="records"), "holding_attribution": holding_attribution, "results_root": output,
    }
    R1.write_json(output / "stock_risk_r3_summary.json", summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_STOCK_RISK_R3_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_STOCK_RISK_R3_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
