"""Bounded pre-2026 Raw A2 action study. Never reads 2026 inputs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
REPO = Path(r"D:\us-tech-quant")
sys.path.insert(0, str(REPO))
from scripts.research.a2.factors.tail_research_inputs import load_inputs  # noqa: E402

ASOF_UTC = "2026-09-25T14:48:51Z"
CUTOFF = pd.Timestamp("2026-01-01")
FEATURES = (
    "raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d", "ret_20d",
    "realized_vol_20d", "downside_vol_20d", "max_drawdown_20d",
    "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d",
    *(f"lag_ret_{i:02d}" for i in range(10)),
)
SEEDS = (20260925, 20260926)
FOLDS = (("2024", pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")),
         ("2025", pd.Timestamp("2025-01-01"), CUTOFF))
E5 = Path(r"D:\us-tech-quant-results\A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS\run_a2_execution_efficiency_r2.py")


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False) + "\n", encoding="utf-8")


def estimator(name: str, seed: int) -> Pipeline:
    if name == "RIDGE":
        core = Ridge(alpha=100.0)
    elif name == "HGB":
        core = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15,
                                             min_samples_leaf=100, l2_regularization=10.0,
                                             learning_rate=0.04, early_stopping=False, random_state=seed)
    elif name == "MLP":
        core = MLPRegressor(hidden_layer_sizes=(64, 32), activation="relu",
                            solver="adam", alpha=0.01, learning_rate_init=0.001,
                            batch_size=256, max_iter=80, early_stopping=False,
                            shuffle=True, random_state=seed, tol=1e-5, n_iter_no_change=80)
    else:
        raise ValueError(name)
    return Pipeline([("impute", SimpleImputer(strategy="median")),
                     ("scale", StandardScaler()), ("model", core)])


def make_panel(panel: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    assert panel.signal_date.max() < CUTOFF and panel.target_end_date.max() < CUTOFF
    assert prices.trade_date.max() < CUTOFF
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    cal = pd.DataFrame({"signal_date": calendar,
                        "entry_date": pd.Series(calendar).shift(-1),
                        "label_end_date_exec": pd.Series(calendar).shift(-21)})
    px = prices[["ticker", "trade_date", "open", "close"]].sort_values(["ticker", "trade_date"]).copy()
    one = px.groupby("ticker", sort=False).close.pct_change(fill_method=None)
    for k in range(10):
        px[f"lag_ret_{k:02d}"] = one.groupby(px.ticker, sort=False).shift(k)
    lagcols = ["ticker", "trade_date", *(f"lag_ret_{i:02d}" for i in range(10))]
    decision = panel.merge(px[lagcols].rename(columns={"trade_date": "signal_date"}),
                           on=["ticker", "signal_date"], how="left", validate="one_to_one")
    decision = decision.merge(cal, on="signal_date", how="left", validate="many_to_one")
    top = decision.loc[decision.raw_rank.le(20), ["signal_date", "ticker"]].copy()
    top["next_signal_date"] = top.signal_date.map(
        pd.Series(pd.DatetimeIndex(sorted(decision.signal_date.unique())).to_series().shift(-1).to_numpy(),
                  index=sorted(decision.signal_date.unique())))
    previous = top[["next_signal_date", "ticker"]].rename(columns={"next_signal_date": "signal_date"})
    previous["prior_raw_held"] = True
    decision = decision.merge(previous, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    decision["prior_raw_held"] = decision.prior_raw_held.fillna(False).astype(bool)
    decision = decision.loc[decision.raw_rank.le(20) | decision.prior_raw_held].copy()
    opens = px[["ticker", "trade_date", "open"]]
    decision = decision.merge(opens.rename(columns={"trade_date": "entry_date", "open": "entry_open"}),
                              on=["ticker", "entry_date"], how="left", validate="one_to_one")
    decision = decision.merge(opens.rename(columns={"trade_date": "label_end_date_exec", "open": "exit_open"}),
                              on=["ticker", "label_end_date_exec"], how="left", validate="one_to_one")
    decision["y_exec20"] = decision.exit_open / decision.entry_open - 1.0
    decision.loc[~np.isfinite(decision.y_exec20), "y_exec20"] = np.nan
    assert decision.signal_date.max() < CUTOFF
    assert not decision.duplicated(["signal_date", "ticker"]).any()
    return decision, prices


def day_ic(frame: pd.DataFrame) -> float:
    vals = []
    for _, x in frame.groupby("signal_date"):
        if len(x) >= 8 and x.prediction.nunique() > 1 and x.y_exec20.nunique() > 1:
            vals.append(float(spearmanr(x.prediction, x.y_exec20).statistic))
    return float(np.mean(vals)) if vals else float("nan")


def replay(name: str, pred: pd.DataFrame, prices: pd.DataFrame, e5: object,
           mode: str = "JOINT") -> tuple[dict, pd.DataFrame]:
    dates = sorted(pred.signal_date.unique())
    cal = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    next_date = {pd.Timestamp(cal[i]): pd.Timestamp(cal[i + 1]) for i in range(len(cal) - 1)}
    execution = [next_date[pd.Timestamp(d)] for d in dates if pd.Timestamp(d) in next_date]
    signals = {next_date[pd.Timestamp(d)]: pd.Timestamp(d) for d in dates if pd.Timestamp(d) in next_date}
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    held: set[str] = set()
    for d, day in pred.groupby("signal_date", sort=True):
        raw = set(day.loc[day.raw_rank.le(20), "ticker"])
        proposed: set[str] = set()
        for r in day.itertuples():
            new = r.ticker in raw and r.ticker not in held
            old = r.ticker in held
            if mode == "BUY_ONLY" and old:
                allow = r.ticker in raw
            elif mode == "EXIT_ONLY" and new:
                allow = True
            else:
                allow = (new and r.prediction > 0.001) or (old and r.prediction > 0.0005)
            if allow and (new or old):
                proposed.add(r.ticker)
        if mode == "RAW":
            proposed = raw
        targets[pd.Timestamp(d)] = {t: 0.05 for t in sorted(proposed)}
        held = proposed
    result = e5.replay(name, targets, prices, execution, signals)
    x = result.daily
    stats = {"last_nav": float(x.nav.iloc[-1]), "net_return": float(x.nav.iloc[-1] - 1),
             "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
             "turnover_sum": float(x.turnover.sum()),
             "cost_sum_nav_fraction": float(x.transaction_cost_fraction.sum()),
             "mean_cash_weight": float(x.cash_weight.mean()),
             "skipped_buys": int(x.skipped_buy_count.sum()),
             "blocked_sells": int(x.blocked_sell_count.sum()),
             "sessions": len(x)}
    return stats, x


def main() -> None:
    started = time.time()
    panel, prices, _, lineage = load_inputs()
    frame, prices = make_panel(panel, prices)
    e5_spec = importlib.util.spec_from_file_location("a2_action_e5", E5)
    assert e5_spec and e5_spec.loader
    e5 = importlib.util.module_from_spec(e5_spec)
    sys.modules[e5_spec.name] = e5
    e5_spec.loader.exec_module(e5)
    X = list(FEATURES)
    assert set(X).issubset(frame.columns) and not any("target" in f or "future" in f for f in X)
    rows = []
    predictions = []
    models = ("RIDGE", "HGB", "MLP")
    for fold, start, end in FOLDS:
        train = frame.loc[frame.signal_date.lt(start) & frame.label_end_date_exec.lt(start) & frame.y_exec20.notna()].copy()
        valid = frame.loc[frame.signal_date.ge(start) & frame.signal_date.lt(end)].copy()
        assert len(train) and len(valid) and train.label_end_date_exec.max() < start
        assert valid.signal_date.min() >= start and valid.signal_date.max() < end
        for family in models:
            for seed in (SEEDS if family == "MLP" else SEEDS[:1]):
                t = time.time()
                model = estimator(family, seed)
                model.fit(train[X], train.y_exec20)
                fitted = model.named_steps["model"]
                if family == "MLP":
                    assert all(np.isfinite(w).all() for w in fitted.coefs_)
                    assert getattr(fitted, "n_iter_", 0) > 0
                pred = valid[["signal_date", "ticker", "raw_rank", "y_exec20"]].copy()
                pred["prediction"] = model.predict(valid[X])
                pred["family"] = family
                pred["seed"] = seed
                pred["fold"] = fold
                stats, _ = replay(f"{family}_{seed}_{fold}", pred, prices, e5)
                scored = pred.loc[pred.y_exec20.notna() & valid.label_end_date_exec.lt(CUTOFF).to_numpy()].copy()
                rows.append({"fold": fold, "family": family, "seed": seed, "train_rows": len(train),
                             "train_dates": train.signal_date.nunique(), "valid_rows": len(valid),
                             "valid_dates": valid.signal_date.nunique(),
                             "train_max_signal": train.signal_date.max(), "train_max_label_end": train.label_end_date_exec.max(),
                             "valid_max_label_end": valid.label_end_date_exec.max(),
                             "mature_scored_rows": len(scored),
                             "mae": float(np.mean(np.abs(scored.prediction - scored.y_exec20))),
                             "daily_ic": day_ic(scored), "fit_seconds": time.time() - t,
                             "trainable_parameter_count": int(sum(w.size for w in fitted.coefs_)) if family == "MLP" else None,
                             "mlp_iterations": int(fitted.n_iter_) if family == "MLP" else None,
                             **stats})
                predictions.append(pred)
                print(f"FIT {fold} {family} {seed} rows={len(train)} seconds={time.time()-t:.1f}", flush=True)
    oof = pd.concat(predictions, ignore_index=True)
    oof.to_parquet(ROOT / "pre2026_oof_predictions.parquet", index=False)
    trial = pd.DataFrame(rows)
    trial.to_csv(ROOT / "trials.csv", index=False)
    # Selection is a single predeclared rule: beats Raw in both 2024 and 2025,
    # then largest mean net-return delta; seeds are averaged, never cherry-picked.
    baselines = {}
    for fold, start, end in FOLDS:
        probe = frame.loc[frame.signal_date.ge(start) & frame.signal_date.lt(end),
                          ["signal_date", "ticker", "raw_rank", "y_exec20"]].copy()
        probe["prediction"] = 0.0
        baselines[fold], _ = replay(f"RAW_{fold}", probe, prices, e5, mode="RAW")
    family_metric = trial.groupby(["fold", "family"]).net_return.mean().unstack()
    deltas = {name: {fold: float(family_metric.at[fold, name] - baselines[fold]["net_return"])
                     for fold, _, _ in FOLDS} for name in models}
    qualified = [name for name in models if all(v > 0 for v in deltas[name].values())]
    main_name = max(qualified, key=lambda n: np.mean(list(deltas[n].values()))) if qualified else "RAW"
    final = frame.loc[frame.label_end_date_exec.lt(CUTOFF) & frame.y_exec20.notna()].copy()
    artifacts = {}
    for family in models:
        for seed in (SEEDS if family == "MLP" else SEEDS[:1]):
            t = time.time()
            model = estimator(family, seed)
            model.fit(final[X], final.y_exec20)
            path = ROOT / f"model_{family}_{seed}.joblib"
            joblib.dump(model, path, compress=3)
            artifacts[f"{family}_{seed}"] = {"path": path.name, "sha256": digest(path),
                                              "fit_seconds": time.time() - t,
                                              "train_rows": len(final), "train_max_signal": final.signal_date.max(),
                                              "train_max_label_end": final.label_end_date_exec.max()}
            print(f"FINAL {family} {seed} seconds={time.time()-t:.1f}", flush=True)
    write_json(ROOT / "freeze.json", {
        "status": "PRE2026_FROZEN_BEFORE_2026_ECONOMIC_READ", "test_asof_utc": ASOF_UTC,
        "test_last_completed_session_et": "2026-09-24", "train_cutoff_exclusive": str(CUTOFF.date()),
        "features": X, "label": "next XNYS open to open 20 sessions later on PIT_FORWARD_REHAB_INDEX; diagnostic price coordinate",
        "decision": "signal date close; next XNYS open execution", "action": {
            "new_buy": "rank<=20 and predicted gross 20-session return>0.001",
            "wait": "otherwise recheck next signal date, no reserved slot",
            "hold": "held and rank<=40 and predicted return>0.0005",
            "exit": "otherwise, next XNYS open; reentry allowed if later raw rank<=20",
            "weight": "0.05 per allowed name, residual cash, no outside-Top20 new purchases"},
        "cost": "E5 replay COST_RATE=0.001, 0.0005 per buy/sell notional",
        "initial_state": "cash=1.0, no shares at first 2026 execution session",
        "primary_selection": main_name, "selection_rule": "positive net proxy delta vs Raw in both 2024 and 2025; then mean delta; otherwise Raw",
        "test_candidates": ["RAW", "RIDGE", "HGB", "MLP_TWO_SEED_MEAN"],
        "ablations": ["BUY_ONLY", "EXIT_ONLY", "JOINT"],
        "source_lineage": lineage, "trial_deltas": deltas, "raw_fold_metrics": baselines,
        "models": artifacts, "oof_sha256": digest(ROOT / "pre2026_oof_predictions.parquet"),
        "trial_table_sha256": digest(ROOT / "trials.csv"), "training_seconds": time.time() - started,
        "historical_2026_exposure": "A2 project previously viewed later outcomes; no pristine holdout claim",
        "current_round_2026_used_for_selection": False,
    })
    print(f"FROZEN main={main_name} elapsed={time.time()-started:.1f}", flush=True)


if __name__ == "__main__":
    main()
