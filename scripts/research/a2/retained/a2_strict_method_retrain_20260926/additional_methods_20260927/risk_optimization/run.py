"""Separate pre-2026 PCA alpha, shrunk risk and cost-budget portfolio research.

This module never reads 2026 outcomes. It does not modify the four frozen A2
models or the original source ledger. Validation is strictly forward by year.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
SOURCE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
PARENT = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
PRODUCER = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
ACCOUNTING = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
TRAIN = SOURCE / "A2/training_matrix.parquet"
FULL = SOURCE / "A/score_rank_ledger.parquet"
PRICE = PARENT / "pre2026_original_price_coordinate.parquet"
REF_KEYS = SOURCE / "A2/oof_predictions.parquet"
SEED = 20260816
N_FACTORS = 8
RIDGE_ALPHA = 10.0
RISK_AVERSION = 5.0
RISK_HORIZON_SESSIONS = 10.0
RISK_LOOKBACK_RETURNS = 60
TOP_N = 20
MAX_WEIGHT = 0.10
COST_BPS = 10
EX_ANTE_COST_BUDGET_BPS = 10.0


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def estimator() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=N_FACTORS, svd_solver="randomized", random_state=SEED)),
        ("ridge", Ridge(alpha=RIDGE_ALPHA, solver="lsqr", tol=1e-6, max_iter=10000)),
    ])


def covariance_for_day(close_wide: pd.DataFrame, date: pd.Timestamp, tickers: list[str]) -> tuple[np.ndarray, float]:
    history = close_wide.loc[close_wide.index <= date, tickers].tail(RISK_LOOKBACK_RETURNS + 1)
    if len(history) != RISK_LOOKBACK_RETURNS + 1 or history.isna().any().any() or (history <= 0).any().any():
        raise RuntimeError(f"RISK_HISTORY_INCOMPLETE:{date.date()}:{tickers}")
    returns = history.pct_change(fill_method=None).iloc[1:].to_numpy(dtype=float)
    if not np.isfinite(returns).all():
        raise RuntimeError(f"RISK_RETURNS_NONFINITE:{date.date()}")
    shrink = LedoitWolf(assume_centered=False).fit(returns)
    cov = np.asarray(shrink.covariance_, float) * RISK_HORIZON_SESSIONS
    cov = 0.5 * (cov + cov.T)
    return cov, float(shrink.shrinkage_)


def feasible_seed(tickers: list[str], previous: dict[str, float]) -> np.ndarray:
    n = len(tickers)
    w = np.array([previous.get(ticker, 0.0) for ticker in tickers], dtype=float)
    missing = 1.0 - w.sum()
    for i in range(n):
        add = min(MAX_WEIGHT - w[i], missing)
        if add > 0:
            w[i] += add
            missing -= add
        if missing < 1e-12:
            break
    if missing > 1e-8:
        raise RuntimeError("NO_FEASIBLE_WEIGHT_SEED")
    return w


def optimize_weights(tickers: list[str], mu: np.ndarray, cov: np.ndarray, previous: dict[str, float]) -> tuple[np.ndarray, dict[str, object]]:
    n = len(tickers)
    prev = np.array([previous.get(ticker, 0.0) for ticker in tickers], dtype=float)
    forced_exit = sum(weight for ticker, weight in previous.items() if ticker not in set(tickers))
    if not (len(tickers) == TOP_N and np.isfinite(mu).all() and np.isfinite(cov).all()):
        raise RuntimeError("INVALID_OPTIMIZER_INPUT")
    w0 = feasible_seed(tickers, previous)
    t0 = np.abs(w0 - prev) + 1e-10
    # Original accounting charges half the 10 bps rate on each buy/sell notional.
    # A full basket replacement therefore costs 10 bps. This ceiling is exactly
    # the original contract's full-replacement cost, with no extra 8 bps cap.
    budget_turnover = max(EX_ANTE_COST_BUDGET_BPS / COST_BPS, float(forced_exit))
    max_aux_sum = 2.0 * budget_turnover - forced_exit
    if t0.sum() > max_aux_sum + 1e-7:
        raise RuntimeError("COST_BUDGET_SEED_INFEASIBLE")
    cost_rate = COST_BPS / 10000.0

    def obj(z: np.ndarray) -> float:
        w, aux = z[:n], z[n:]
        return float(-mu @ w + 0.5 * RISK_AVERSION * (w @ cov @ w) + 0.5 * cost_rate * (aux.sum() + forced_exit))

    def jac(z: np.ndarray) -> np.ndarray:
        return np.r_[-mu + RISK_AVERSION * cov @ z[:n], np.full(n, 0.5 * cost_rate)]

    constraints = [
        {"type": "eq", "fun": lambda z: z[:n].sum() - 1.0, "jac": lambda z: np.r_[np.ones(n), np.zeros(n)]},
        {"type": "ineq", "fun": lambda z: z[n:] - z[:n] + prev, "jac": lambda z: np.c_[-np.eye(n), np.eye(n)]},
        {"type": "ineq", "fun": lambda z: z[n:] + z[:n] - prev, "jac": lambda z: np.c_[np.eye(n), np.eye(n)]},
        {"type": "ineq", "fun": lambda z: max_aux_sum - z[n:].sum(), "jac": lambda z: np.r_[np.zeros(n), -np.ones(n)]},
    ]
    result = minimize(obj, np.r_[w0, t0], jac=jac, method="SLSQP",
                      bounds=[(0, MAX_WEIGHT)] * n + [(0, 1)] * n,
                      constraints=constraints, options={"ftol": 1e-9, "maxiter": 200})
    if not result.success:
        raise RuntimeError(f"OPTIMIZER_FAILURE:{result.message}")
    w = np.clip(result.x[:n], 0, MAX_WEIGHT)
    turnover = 0.5 * (np.abs(w - prev).sum() + forced_exit)
    if abs(w.sum() - 1.0) > 1e-6 or turnover > budget_turnover + 1e-6:
        raise RuntimeError("OPTIMIZER_CONSTRAINT_FAILURE")
    return w, {"solver_success": bool(result.success), "solver_status": int(result.status),
               "solver_iterations": int(result.nit), "objective": float(result.fun),
               "ex_ante_turnover": float(turnover), "ex_ante_cost_bps": float(turnover * COST_BPS),
               "cost_budget_bps": float(budget_turnover * COST_BPS), "forced_exit_weight": float(forced_exit),
               "risk_quadratic": float(w @ cov @ w), "factor_expected_target": float(mu @ w)}


def main() -> None:
    OUT.mkdir(exist_ok=True, parents=True)
    producer = import_file("risk_opt_original_producer", PRODUCER)
    account = import_file("risk_opt_original_account", ACCOUNTING)
    features = list(producer.FEATURE_COLUMNS)
    common = json.loads((PARENT / "common_frozen.json").read_text(encoding="utf-8"))
    assert features == common["feature_order"]
    source_sha = {str(p): sha(p) for p in [TRAIN, FULL, PRICE, REF_KEYS, PRODUCER, ACCOUNTING, PARENT / "common_frozen.json"]}
    assert source_sha[str(TRAIN)] == common["source_sha256"][str(TRAIN)]
    assert source_sha[str(FULL)] == common["source_sha256"][str(FULL)]
    write_json(OUT / "SOURCE_BINDING.json", source_sha)
    write_json(OUT / "FROZEN_METHOD_SPEC.json", {"method": "PCA8_RIDGE_FACTOR_LEDWOLF60_COST8_TOP20",
        "feature_order": features, "n_factors": N_FACTORS, "ridge_alpha": RIDGE_ALPHA,
        "risk_lookback_returns": RISK_LOOKBACK_RETURNS, "risk_horizon_sessions": RISK_HORIZON_SESSIONS,
        "risk_aversion": RISK_AVERSION, "max_weight": MAX_WEIGHT, "top_n": TOP_N,
        "original_cost_bps": COST_BPS, "ex_ante_cost_budget_bps": EX_ANTE_COST_BUDGET_BPS,
        "budget_forced_exit_rule": "max(10bps, forced_exit_weight*10bps); full-replacement ceiling", "seed": SEED,
        "coordinate": "parent pre2026_original_price_coordinate.parquet; original adjusted open and close",
        "fit_split": "original stage_rows: prior signal year, mature target_end before first validation signal"})

    matrix = pd.read_parquet(TRAIN).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    full = pd.read_parquet(FULL, columns=["signal_date", "ticker", *features])
    ref = pd.read_parquet(REF_KEYS, columns=["signal_date", "ticker", "target"])
    price = pd.read_parquet(PRICE)
    close_wide = price.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    calendar = pd.DatetimeIndex(price.loc[price.ticker.eq("QQQ"), "trade_date"].sort_values())
    terminal = pd.Timestamp(calendar[-3])
    all_predictions = []
    all_weights = []
    all_diagnostics = []
    fit_logs = []
    daily_paths = []
    for stage, year in producer.STAGES:
        training, _, audit = producer.stage_rows(matrix, year)
        eval_frame = full.loc[full.signal_date.dt.year.eq(year)].sort_values(["signal_date", "ticker"], kind="mergesort").copy()
        model = estimator()
        model.fit(training[features].to_numpy(float), training.target.to_numpy(float))
        artifact = OUT / f"{stage.lower()}_{year}_factor_model.joblib"
        joblib.dump(model, artifact, compress=3)
        eval_frame["factor_prediction"] = model.predict(eval_frame[features].to_numpy(float))
        eval_frame["rank"] = producer._prediction_rank(eval_frame, "factor_prediction")
        eval_frame["stage"] = stage
        prediction = eval_frame[["signal_date", "ticker", "stage", "factor_prediction", "rank"]]
        all_predictions.append(prediction)
        fit_logs.append({**audit, "stage": stage, "estimator_fit_calls": 1, "scaler_fit_calls": 1,
                         "pca_fit_calls": 1, "ridge_fit_calls": 1,
                         "pca_explained_variance_ratio": model["pca"].explained_variance_ratio_.tolist(),
                         "model_artifact": str(artifact), "model_sha256": sha(artifact)})
        previous: dict[str, float] = {}
        target_map: dict[pd.Timestamp, dict[str, float]] = {}
        year_weights = []
        year_diag = []
        for date, g in prediction.loc[prediction.signal_date.le(terminal)].groupby("signal_date", sort=True):
            top = g.loc[g["rank"].le(TOP_N)].sort_values("rank")
            if len(top) != TOP_N:
                raise RuntimeError(f"TOP20_INCOMPLETE:{date}")
            tickers = top.ticker.tolist()
            mu = top.factor_prediction.to_numpy(float)
            cov, shrinkage = covariance_for_day(close_wide, pd.Timestamp(date), tickers)
            weights, diagnostic = optimize_weights(tickers, mu, cov, previous)
            target_map[pd.Timestamp(date)] = {ticker: float(weight) for ticker, weight in zip(tickers, weights) if weight > 1e-10}
            for ticker, rank, pred, weight in zip(tickers, top["rank"], mu, weights):
                year_weights.append({"signal_date": date, "ticker": ticker, "rank": int(rank),
                                     "factor_prediction": float(pred), "target_weight": float(weight), "stage": stage})
            year_diag.append({"signal_date": date, "stage": stage, "shrinkage": shrinkage,
                              "covariance_observations": RISK_LOOKBACK_RETURNS, **diagnostic})
            previous = target_map[pd.Timestamp(date)]
        weight_frame = pd.DataFrame(year_weights)
        diag_frame = pd.DataFrame(year_diag)
        all_weights.append(weight_frame)
        all_diagnostics.append(diag_frame)
        # Original adjusted-price accounting, kept as an independent new strategy.
        path = account.reconstruct_path(model="pca_risk_cost", target_map=target_map, qfq=price,
                                        signal_dates=weight_frame.signal_date.unique(), cost_bps=COST_BPS)
        for name, frame in [("daily", path.daily), ("positions", path.positions), ("trades", path.trades)]:
            frame.to_parquet(OUT / f"{stage.lower()}_{year}_{name}.parquet", index=False)
        daily_paths.append(path.daily.assign(stage=stage))
        print(f"{stage} {year}: fit 1, covariance {len(diag_frame)}, optimize {len(diag_frame)}", flush=True)

    predictions = pd.concat(all_predictions, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    key = ref[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    assert predictions[["signal_date", "ticker"]].equals(key)
    predictions.to_parquet(OUT / "pre2026_oof_factor_predictions.parquet", index=False)
    weights = pd.concat(all_weights, ignore_index=True)
    diagnostics = pd.concat(all_diagnostics, ignore_index=True)
    weights.to_parquet(OUT / "pre2026_oof_optimized_weights.parquet", index=False)
    diagnostics.to_parquet(OUT / "pre2026_oof_risk_cost_diagnostics.parquet", index=False)
    daily = pd.concat(daily_paths, ignore_index=True)
    daily.to_parquet(OUT / "pre2026_oof_portfolio_daily.parquet", index=False)
    labeled = predictions.merge(ref, on=["signal_date", "ticker"], validate="one_to_one")
    labeled = labeled.loc[labeled.target.notna()].copy()
    prediction_metrics = labeled.groupby("stage").apply(lambda x: pd.Series({
        "labeled_rows": len(x), "mse": ((x.factor_prediction - x.target) ** 2).mean(),
        "mae": (x.factor_prediction - x.target).abs().mean(),
        "mean_daily_rank_ic": x.groupby("signal_date").apply(
            lambda g: g.factor_prediction.rank().corr(g.target.rank()), include_groups=False).mean(),
    }), include_groups=False).to_dict("index")
    performance = {}
    for stage, g in daily.groupby("stage"):
        ret = g.sort_values("execution_date").reconstructed_daily_return.to_numpy(float)
        nav = np.r_[1.0, np.cumprod(1.0 + ret)]
        performance[stage] = {"daily_rows": len(ret), "net_return": float(nav[-1] - 1.0),
                              "max_drawdown": float(np.min(nav / np.maximum.accumulate(nav) - 1.0)),
                              "volatility_annual": float(np.std(ret, ddof=1) * math.sqrt(252)),
                              "sharpe_annual": float(np.mean(ret) / np.std(ret, ddof=1) * math.sqrt(252)),
                              "turnover_sum": float(g.reconstructed_turnover.sum()),
                              "transaction_cost_sum": float(g.reconstructed_transaction_cost.sum())}
    final = estimator()
    final.fit(matrix[features].to_numpy(float), matrix.target.to_numpy(float))
    final_artifact = OUT / "final_full_pre2026_factor_model.joblib"
    joblib.dump(final, final_artifact, compress=3)
    fit_logs.append({"stage": "FULL_PRE2026", "train_rows": len(matrix), "estimator_fit_calls": 1,
                     "scaler_fit_calls": 1, "pca_fit_calls": 1, "ridge_fit_calls": 1,
                     "model_artifact": str(final_artifact), "model_sha256": sha(final_artifact),
                     "pca_explained_variance_ratio": final["pca"].explained_variance_ratio_.tolist()})
    write_json(OUT / "FIT_LOG.json", fit_logs)
    write_json(OUT / "VALIDATION.json", {"prediction": prediction_metrics, "portfolio": performance,
        "covariance_fit_calls": len(diagnostics), "optimizer_solve_calls": len(diagnostics),
        "estimator_fit_calls": 4, "preprocessor_fit_calls": 4,
        "terminal_pre2026_signal": str(terminal.date()), "training_data_max_target_end": str(matrix.target_end_date.max().date()),
        "python": platform.python_version(), "pandas": pd.__version__, "sklearn": sklearn.__version__, "scipy": scipy.__version__,
        "completed_utc": datetime.now(timezone.utc).isoformat()})
    print("DONE", len(predictions), len(weights), len(diagnostics), flush=True)


if __name__ == "__main__":
    main()
