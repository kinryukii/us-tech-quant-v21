"""Joint stock/state/action value learning, with causal pre-2026 labels only.

This is an offline one-step counterfactual value approximation, not a solution
of the full sequential portfolio-control problem. A single scorer evaluates
all stocks and all actions together; exact constrained allocation uses those
joint scores without a prior return-based TOP20 screen.
"""
from __future__ import annotations
import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
from sklearn.metrics import mean_squared_error, roc_auc_score, log_loss, mean_pinball_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
OUT = HERE / "joint_linear_tree_artifacts_r2"
FEATURES = json.loads((HERE / "models/model_registry.json").read_text(encoding="utf-8"))["feature_order"]
ACTIONS = np.array([0, .025, .05, .075, .1], dtype=float)
STATE_GRID = ((0., .95, 0.), (.05, .5, 10.), (.1, .05, 40.))
SEED = 20260927
MAX_ROWS = 200000
COST = .001
RISK_AVERSION = 4.
NAMES = ("ridge", "elastic_net", "logistic", "hgb", "q10", "q50", "q90")
TREE = dict(max_iter=100, max_leaf_nodes=15, max_depth=3, min_samples_leaf=150,
            learning_rate=.05, l2_regularization=10., early_stopping=False, random_state=SEED)
SPECS = {"ridge": {"alpha": 100.}, "elastic_net": {"alpha": .000001, "l1_ratio": .35, "max_iter": 2500},
         "logistic": {"C": .3, "max_iter": 400}, "hgb": TREE,
         "q10": {**TREE, "loss": "quantile", "quantile": .1},
         "q50": {**TREE, "loss": "quantile", "quantile": .5},
         "q90": {**TREE, "loss": "quantile", "quantile": .9}}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def mapped_features(x, current, cash, age, action):
    """Fixed interactions let a linear scorer learn stock-dependent actions."""
    x = np.asarray(x, dtype=float)
    current, cash, age, action = [np.asarray(a, dtype=float).reshape(-1) for a in (current, cash, age, action)]
    volatility = x[:, FEATURES.index("realized_vol_20d")]
    return np.column_stack([x, current, cash, np.minimum(age, 252.) / 252., action,
                            action * action, np.abs(action-current), action-current,
                            x * action[:, None], x * (action-current)[:, None],
                            action * cash, action * current, action * volatility * volatility])


def select_dates(frame, maximum_base_rows):
    """Systematic whole-date subsample; never split rows randomly in time."""
    counts = frame.groupby("signal_date", sort=True).size()
    if int(counts.sum()) <= maximum_base_rows:
        return frame.copy(), counts.index
    # Reserve enough space for the densest day; every selected date is whole.
    count = max(1, maximum_base_rows // int(counts.max()))
    indices = np.unique(np.linspace(0, len(counts)-1, num=min(count, len(counts)), dtype=int))
    chosen = counts.index[indices]
    selected = frame[frame.signal_date.isin(chosen)].copy()
    if len(selected) > maximum_base_rows:
        raise RuntimeError("WHOLE_DATE_SAMPLING_BUDGET_EXCEEDED")
    return selected, chosen


def counterfactual(frame, robust_training=False):
    x = frame[FEATURES].to_numpy(float)
    forward = frame.joint_return.to_numpy(float)
    if robust_training:
        forward = np.clip(forward, -.20, .20)
    vol = frame.realized_vol_20d.to_numpy(float)
    assert np.isfinite(x).all() and np.isfinite(forward).all()
    parts, rewards, groups = [], [], []
    for current, cash, age in STATE_GRID:
        for action in ACTIONS:
            n = len(frame)
            parts.append(mapped_features(x, np.full(n, current), np.full(n, cash), np.full(n, age), np.full(n, action)))
            rewards.append(action * forward - COST * abs(action-current) - .5 * RISK_AVERSION * vol**2 * action**2)
            groups.append(np.full(n, action))
    return np.concatenate(parts), np.concatenate(rewards), np.concatenate(groups)


def estimator(name):
    if name == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=100., solver="lsqr", tol=1e-6))
    if name == "elastic_net":
        return make_pipeline(StandardScaler(), ElasticNet(**SPECS[name], tol=1e-5, selection="cyclic", random_state=SEED))
    if name == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(**SPECS[name], solver="lbfgs", random_state=SEED))
    return HistGradientBoostingRegressor(**SPECS[name])


def predict_values(model, name, values):
    with threadpool_limits(limits=2):
        result = model.predict_proba(values)[:, 1] if name == "logistic" else model.predict(values)
    if not np.isfinite(result).all():
        raise RuntimeError("NONFINITE_ACTION_VALUE")
    return result


def allocate_joint_scores(scores, tickers, max_names=20, max_units=38, allowed=None):
    """Exact 0/1 multiple-choice knapsack, 2.5% units and <=20 names.

    An action-zero baseline is retained for each stock, including exit cost.
    Returns feasible weights and selected action indices. No stock prescreen.
    """
    scores = np.asarray(scores, dtype=float)
    assert scores.shape == (len(tickers), len(ACTIONS)) and np.isfinite(scores).all()
    gains = scores - scores[:, :1]
    if allowed is not None:
        assert np.asarray(allowed).shape == scores.shape
        gains = np.where(allowed, gains, -np.inf)
    dp = np.full((max_names + 1, max_units + 1), -np.inf)
    dp[0, 0] = 0.
    choices = np.zeros((len(tickers), max_names + 1, max_units + 1), dtype=np.uint8)
    for i in range(len(tickers)):
        prior = dp.copy()
        for action_idx in range(1, len(ACTIONS)):
            candidate = prior[:-1, :-action_idx] + gains[i, action_idx]
            destination = dp[1:, action_idx:]
            improves = candidate > destination + 1e-12
            destination[improves] = candidate[improves]
            choices[i, 1:, action_idx:][improves] = action_idx
    names, units = np.unravel_index(int(np.argmax(dp)), dp.shape)
    selected = np.zeros(len(tickers), dtype=np.int8)
    for i in range(len(tickers)-1, -1, -1):
        action_idx = int(choices[i, names, units])
        selected[i] = action_idx
        if action_idx:
            names -= 1
            units -= action_idx
    assert names == units == 0
    weights = {str(t): float(ACTIONS[a]) for t, a in zip(tickers, selected) if a > 0}
    assert len(weights) <= max_names and sum(weights.values()) <= max_units * .025 + 1e-12
    return weights, selected


class JointActionValuePolicy:
    """One joint value model -> TOP20 membership and target sizing."""
    def __init__(self, name, stage="final"):
        self.name = name
        self.stage = stage
        names = ("q10", "q50", "q90") if name == "quantile_risk" else (name,)
        self.models = {}
        for model_name in names:
            receipt = json.loads((OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
            record = next(r for r in receipt["fits"] if r["stage"] == stage and r["name"] == model_name)
            repairs = [r for r in receipt.get("numerical_repairs", []) if r["stage"] == stage and r["name"] == model_name and r["used_for_policy"]]
            if repairs:
                record = repairs[-1]
            path = Path(record["artifact"])
            assert sha(path) == record["artifact_sha256"]
            self.models[model_name] = joblib.load(path)
        self.last_actions = None

    def __call__(self, day, weights, cash, held_age=None):
        return self.policy(day, weights, cash, held_age)

    def policy(self, day, weights, cash, held_age=None):
        if day.empty or day.signal_date.nunique() != 1 or day.ticker.duplicated().any():
            raise ValueError("Expected one unique full eligible signal-day pool")
        day = day.sort_values("ticker", kind="mergesort").reset_index(drop=True)
        x = day[FEATURES].to_numpy(float)
        assert np.isfinite(x).all()
        if not np.isfinite(cash) or cash < -1e-8 or cash > 1 + 1e-8:
            raise ValueError("Invalid account cash weight")
        current = day.ticker.map(weights).fillna(0).to_numpy(float)
        age = day.ticker.map(held_age or {}).fillna(0).to_numpy(float)
        action = np.tile(ACTIONS, len(day))
        values = mapped_features(np.repeat(x, len(ACTIONS), axis=0), np.repeat(current, len(ACTIONS)),
                                 np.full(len(action), cash), np.repeat(age, len(ACTIONS)), action)
        if self.name == "quantile_risk":
            quantiles = np.column_stack([predict_values(self.models[n], n, values) for n in ("q10", "q50", "q90")])
            quantiles.sort(axis=1)
            flat = quantiles[:, 1] - .25 * (quantiles[:, 1] - quantiles[:, 0])
        else:
            flat = predict_values(self.models[self.name], self.name, values)
        score = flat.reshape(len(day), len(ACTIONS))
        eligible = day.new_buy_eligible.to_numpy(bool) if "new_buy_eligible" in day else np.ones(len(day), dtype=bool)
        allowed = eligible[:, None] | (ACTIONS[None, :] <= current[:, None] + 1e-10)
        targets, selected = allocate_joint_scores(score, day.ticker.tolist(), allowed=allowed)
        self.last_actions = day[["signal_date", "ticker"]].copy()
        self.last_actions["current_weight"] = current
        self.last_actions["target_weight"] = ACTIONS[selected]
        self.last_actions["selected_action_value"] = score[np.arange(len(day)), selected]
        self.last_actions["action_zero_value"] = score[:, 0]
        return targets


def load_policy(name, stage="final"):
    return JointActionValuePolicy(name, stage)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--return-column", default="joint_return")
    parser.add_argument("--end-column", default="label_end_date")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if (OUT / "FIT_RECEIPT.json").exists():
        raise RuntimeError("COMPLETED_JOINT_FITS_EXIST: preserve them")
    frame = pd.read_parquet(args.data)
    frame = frame.rename(columns={args.return_column: "joint_return", args.end_column: "label_end_date"})
    required = ["signal_date", "ticker", "joint_return", "label_end_date", *FEATURES]
    assert set(required).issubset(frame.columns)
    input_rows = len(frame)
    if "label_available" in frame:
        frame = frame.loc[frame.label_available].copy()
    if "new_buy_eligible" in frame:
        frame = frame.loc[frame.new_buy_eligible].copy()
    price_warning_count = int(frame.label_price_warning.sum()) if "label_price_warning" in frame else None
    frame = frame[required].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert not frame.duplicated(["signal_date", "ticker"]).any()
    assert frame.signal_date.lt("2026-01-01").all() and frame.label_end_date.lt("2026-01-01").all()
    assert frame.label_end_date.gt(frame.signal_date).all()
    assert np.isfinite(frame[[*FEATURES, "joint_return"]].to_numpy(float)).all()
    contract = {"cutoff_exclusive": "2026-01-01", "source": str(args.data.resolve()), "source_sha256": sha(args.data),
        "method": "offline_one_step_joint_state_action_value", "features": FEATURES, "parameters": SPECS,
        "action_grid": ACTIONS.tolist(), "counterfactual_states_current_cash_age": STATE_GRID,
        "feature_map": "raw32,current,cash,age/252,action,action^2,abs(action-current),action-current,action*raw32,(action-current)*raw32,action*cash,action*current,action*vol20^2",
        "reward": "action*next_open_to_following_open_return - 0.001*abs(action-current) - 0.5*4*vol20^2*action^2",
        "reward_horizon": "one execution-to-following-open session", "train_years": [2023,2024], "validation_years": [2025],
        "training_loss_robustness": "Only fitting reward clips underlying one-session return to [-0.20,0.20]; validation labels and portfolio PnL are never clipped",
        "candidate_rule": "Use latest 13F quarter publicly filed and effective at signal time; retain prior effective quarter until successor effective; no outcome-based candidate screening",
        "input_rows": input_rows, "retained_mature_eligible_rows": len(frame), "retained_price_warning_rows": price_warning_count,
        "final_train_years": [2023,2024,2025], "maximum_counterfactual_rows_per_fit": MAX_ROWS,
        "split": "date-prefix with label maturity purge; deterministic whole-date subsampling; no random temporal split",
        "hyperparameter_search_count": 0, "validation_usage": "report fixed-spec metrics only; no retuning or architecture selection",
        "action_solver": "exact multiple-choice knapsack over all candidates, <=20 positive stocks, <=38 units of 2.5%",
        "logistic_readout": "unitless positive-net-reward probability as joint action utility; never reported as a return",
        "quantile_readout": "conditional one-step reward quantiles; quantile_risk uses sorted Q50 - .25*(Q50-Q10)",
        "scope": "Counterfactual account states, one-step partial-equilibrium rewards; not trajectory-optimal RL and not a causal claim."}
    write(OUT / "PRE_FIT_CONTRACT.json", contract)
    validation = frame[(frame.signal_date.dt.year == 2025) & (frame.label_end_date < "2026-01-01")]
    validation, validation_dates = select_dates(validation, MAX_ROWS // (len(ACTIONS)*len(STATE_GRID)))
    vx, vy, _ = counterfactual(validation)
    receipt = {"status": "RUNNING", "fits": [], "test_rows_read": 0, "hyperparameter_search_count": 0,
               "source_sha256": contract["source_sha256"], "validation_metrics": {}, "sampling": {}}
    for stage, end in (("validation", "2025-01-01"), ("final", "2026-01-01")):
        train = frame[(frame.signal_date >= "2023-01-01") & (frame.signal_date < end) & (frame.label_end_date < end)]
        train, dates = select_dates(train, MAX_ROWS // (len(ACTIONS)*len(STATE_GRID)))
        tx, ty, _ = counterfactual(train, robust_training=True)
        assert len(tx) <= MAX_ROWS and train.label_end_date.max() < pd.Timestamp(end)
        receipt["sampling"][stage] = {"base_rows": len(train), "counterfactual_rows": len(tx), "dates": [str(d.date()) for d in dates],
                                      "train_signal_max": str(train.signal_date.max().date()), "train_label_end_max": str(train.label_end_date.max().date())}
        for name in NAMES:
            start = time.monotonic()
            model = estimator(name)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model.fit(tx, (ty > 0).astype(int) if name == "logistic" else ty)
            path = OUT / f"{stage}_{name}.joblib"
            joblib.dump(model, path, compress=3)
            record = {"stage": stage, "name": name, "train_rows": len(tx), "fit_seconds": time.monotonic()-start,
                      "train_signal_max": str(train.signal_date.max().date()), "train_label_end_max": str(train.label_end_date.max().date()),
                      "artifact": str(path), "artifact_sha256": sha(path)}
            last_estimator = model[-1] if hasattr(model, "steps") else model
            iterations = getattr(last_estimator, "n_iter_", None)
            record["iterations"] = np.asarray(iterations).tolist() if iterations is not None else None
            record["fit_warnings"] = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
            record["converged"] = not any(w.category.__name__ == "ConvergenceWarning" for w in caught)
            receipt["fits"].append(record)
            if stage == "validation":
                pred = predict_values(model, name, vx)
                if name == "logistic":
                    metric = {"roc_auc": float(roc_auc_score(vy>0,pred)), "log_loss": float(log_loss(vy>0,pred))}
                elif name.startswith("q"):
                    metric = {"pinball_loss": float(mean_pinball_loss(vy,pred,alpha=float(name[1:])/100))}
                else:
                    metric = {"mse": float(mean_squared_error(vy,pred))}
                receipt["validation_metrics"][name] = metric
            write(OUT / "FIT_RECEIPT.partial.json", receipt)
            print(json.dumps(record), flush=True)
    receipt["status"] = "PASS"
    receipt["fit_calls"] = len(receipt["fits"])
    receipt["validation_dates"] = [str(d.date()) for d in validation_dates]
    receipt["validation_counterfactual_rows"] = len(vx)
    write(OUT / "FIT_RECEIPT.json", receipt)
    print(json.dumps({"status": "PASS", "fits": len(receipt["fits"])}), flush=True)


if __name__ == "__main__":
    main()
