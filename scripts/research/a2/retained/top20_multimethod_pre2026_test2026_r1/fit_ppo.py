"""Fixed PPO experiment on the frozen pre-2026 TOP20 panel.

The Gym environment observes a signal close.  Account.execute alone sees the
following open; the reward is the change in the same account's marked wealth
until the next observation (or the original terminal liquidation).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path

import gymnasium as gym
import joblib
import numpy as np
import pandas as pd
import torch
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from policy_engine import Account, PriceStore, project_capped_simplex

HERE = Path(__file__).resolve().parent
OUT = HERE / "ppo_artifacts"
FEATURES = ["r", "log_sigma20", "u", "u_squared", "v", "v_squared",
            "breadth", "r_times_v", "age_times_v"]
SEEDS = (11, 29, 47)
TIMESTEPS = 32768
FOLDS = {"D1": "2024-01-01", "D2": "2024-07-01",
         "V25": "2025-01-01", "FINAL": "2026-01-01"}
OBS_WIDTH = 20 * (len(FEATURES) + 4) + 2


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def whole_policy_sha(model: PPO) -> str:
    data = io.BytesIO()
    torch.save(model.policy.state_dict(), data)
    return hashlib.sha256(data.getvalue()).hexdigest()


def actor_sha(model: PPO) -> str:
    """Hash the actual action distribution parameters, excluding the critic."""
    digest = hashlib.sha256()
    for prefix, module in (("policy_net", model.policy.mlp_extractor.policy_net),
                           ("action_net", model.policy.action_net)):
        for name, parameter in sorted(module.named_parameters()):
            digest.update(f"{prefix}.{name}".encode("ascii"))
            digest.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    digest.update(b"log_std")
    digest.update(model.policy.log_std.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_days(panel: pd.DataFrame, cutoff_exclusive: str) -> list[dict]:
    cutoff = pd.Timestamp(cutoff_exclusive, tz="UTC")
    # Every candidate date remains in the path.  An unusable feature day uses
    # the shared B0 fallback; it is never erased or given zero market return.
    frame = panel.loc[panel.label_available_at_utc.lt(cutoff)].copy()
    if frame.empty or frame.signal_date.max() >= pd.Timestamp(cutoff_exclusive):
        raise RuntimeError("PPO_TRAIN_CLOCK_INVALID")
    days = []
    for date, block in frame.groupby("signal_date", sort=True):
        block = block.sort_values("raw_a2_rank")
        if len(block) != 20 or block.raw_a2_rank.tolist() != list(range(1, 21)):
            raise RuntimeError(f"PPO_CANDIDATE_CARDINALITY:{date}")
        if block.execution_date.nunique() != 1 or block.label_end_date.nunique() != 1:
            raise RuntimeError(f"PPO_CLOCK_AMBIGUOUS:{date}")
        days.append({"date": pd.Timestamp(date),
                     "execution": pd.Timestamp(block.execution_date.iloc[0]),
                     "terminal": pd.Timestamp(block.label_end_date.iloc[0]),
                     "tickers": block.ticker.astype(str).tolist(),
                     "keys": block.experiment_security_key.astype(str).tolist(),
                     "features": block[FEATURES].to_numpy(float),
                     "usable": bool(block.base_usable_day.all())})
    if days[-1]["terminal"] >= pd.Timestamp(cutoff_exclusive):
        raise RuntimeError("PPO_TERMINAL_CROSSES_TRAIN_CUTOFF")
    return days


class Top20ReplayEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, days: list[dict], prices: PriceStore,
                 scaler: dict, record: bool = False):
        super().__init__()
        if not days or list(scaler["columns"]) != FEATURES:
            raise RuntimeError("PPO_SCALER_OR_DAYS_INVALID")
        self.days = days
        self.prices = prices
        self.scaler = scaler
        self.record = record
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(21,), dtype=np.float32)
        self.observation_space = spaces.Box(low=-5.0, high=5.0,
                                             shape=(OBS_WIDTH,), dtype=np.float32)
        self.account: Account | None = None
        self.i = 0
        self.age: dict[str, int] = {}
        self.basis: dict[str, float] = {}
        self.held_key: dict[str, str] = {}
        self.reward_sum = 0.0
        self.actions: list[dict] = []
        self.transactions: list[dict] = []

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self.account = Account(self.prices)
        self.i = 0
        self.age, self.basis, self.held_key = {}, {}, {}
        self.reward_sum = 0.0
        self.actions, self.transactions = [], []
        return self._observation(), {}

    def _observation(self) -> np.ndarray:
        day = self.days[self.i]
        assert self.account is not None
        state = self.account.signal_state(day["date"], day["tickers"])
        if day["usable"]:
            z = (day["features"] - self.scaler["mean"]) / self.scaler["std"]
            z[:, np.asarray(self.scaler["constant"], bool)] = 0.0
            if not np.isfinite(z).all():
                raise RuntimeError(f"PPO_NONFINITE_FEATURE:{day['date']}")
            z = np.clip(z, -5, 5)
        else:
            z = np.zeros((20, len(FEATURES)), float)
        additional = np.zeros((20, 4), float)
        for j, (ticker, key) in enumerate(zip(day["tickers"], day["keys"])):
            if ticker in self.account.shares and self.held_key.get(ticker) != key:
                raise RuntimeError(f"PPO_HELD_IDENTITY_COLLISION:{day['date']}:{ticker}")
            additional[j, 0] = state["weights"][j]
            additional[j, 1] = min(self.age.get(ticker, 0) / 20.0, 5.0)
            if ticker in self.basis:
                close = self.account._price(self.account.close, day["date"], ticker)
                additional[j, 2] = np.clip(close / self.basis[ticker] - 1, -5, 5)
            additional[j, 3] = float(day["usable"])
        out = np.r_[np.c_[z, additional].reshape(-1),
                    state["cash_weight"], state["out_of_list_weight"]].astype(np.float32)
        assert out.shape == (OBS_WIDTH,) and np.isfinite(out).all()
        return out

    def _update_basis(self, trades: list[dict], day: dict) -> None:
        assert self.account is not None
        key_of = dict(zip(day["tickers"], day["keys"]))
        for trade in trades:
            ticker, quantity = trade["ticker"], float(trade["quantity"])
            price = float(trade["notional"] / quantity)
            if trade["side"] == "BUY":
                before = float(self.account.shares[ticker] - quantity)
                previous = self.basis.get(ticker, price)
                self.basis[ticker] = (before * previous + quantity * price) / (before + quantity)
                self.age.setdefault(ticker, 0)
                self.held_key[ticker] = key_of[ticker]
        for ticker in list(self.basis):
            if ticker not in self.account.shares:
                self.basis.pop(ticker)
                self.age.pop(ticker, None)
                self.held_key.pop(ticker, None)
        for ticker in self.account.shares:
            self.age[ticker] = self.age.get(ticker, 0) + 1

    def step(self, action: np.ndarray):
        if self.account is None:
            raise RuntimeError("PPO_RESET_REQUIRED")
        day = self.days[self.i]
        signal = self.account.signal_state(day["date"], day["tickers"])
        projected = project_capped_simplex(np.asarray(action, float))
        weights = projected[:20] if day["usable"] else np.full(20, .05)
        transaction = self.account.execute(day["date"], day["execution"], day["tickers"], weights)
        self._update_basis(transaction["trades"], day)
        self.i += 1
        terminal = self.i == len(self.days)
        if terminal:
            end = self.account.liquidate(day["terminal"])
            after_nav = float(end["net_nav"])
            self.age, self.basis, self.held_key = {}, {}, {}
            observation = np.zeros(OBS_WIDTH, dtype=np.float32)
        else:
            after_nav = float(self.account.signal_state(
                self.days[self.i]["date"], self.days[self.i]["tickers"])["nav"])
            observation = self._observation()
        reward = float(100.0 * np.log(after_nav / signal["nav"]))
        self.reward_sum += reward
        info = {"signal_date": str(day["date"].date()),
                "execution_date": str(day["execution"].date()),
                "signal_nav": signal["nav"], "after_nav": after_nav,
                "fee": transaction["fee"], "target_stock_weight": float(weights.sum()),
                "execution_cash_weight": float(transaction["cash"] / transaction["net_nav"]),
                "fallback": not day["usable"]}
        if terminal:
            info["terminal_nav"] = after_nav
            info["terminal_fee"] = end["fee"]
            info["terminal_traded_notional"] = end["traded_notional"]
            if abs(self.reward_sum / 100.0 - np.log(after_nav)) > 1e-9:
                raise RuntimeError("PPO_REWARD_LEDGER_MISMATCH")
        if self.record:
            self.actions.append({"signal_date": day["date"],
                                 "tickers": day["tickers"], "keys": day["keys"],
                                 "raw_action": np.asarray(action, float).copy(),
                                 "projected": projected.copy(), "executed_weights": weights.copy(),
                                 "signal_weights": signal["weights"].copy(),
                                 "cash_before": signal["cash_weight"], "fallback": not day["usable"],
                                 "reward": reward, **info})
            self.transactions.append(transaction)
        return observation, reward, terminal, False, info


class StepCounter(BaseCallback):
    def __init__(self):
        super().__init__()
        self.optimizer_steps = 0

    def _on_step(self) -> bool:
        return True

    def _on_rollout_end(self) -> None:
        # Each rollout has n_epochs * (n_steps / batch_size) optimizer steps.
        self.optimizer_steps += int(self.model.n_epochs *
                                    self.model.n_steps // self.model.batch_size)


def input_bundle(fold: str) -> tuple[list[dict], PriceStore, dict, dict]:
    panel_path = HERE / "PRE2026_SHARED_PANEL.parquet"
    price_path = HERE / "PRE2026_PRICE_COORDINATE.parquet"
    scaler_path = HERE / "models" / f"SCALER_{fold}.joblib"
    panel = pd.read_parquet(panel_path)
    prices = PriceStore(pd.read_parquet(price_path))
    scaler = joblib.load(scaler_path)
    days = load_days(panel, FOLDS[fold])
    hashes = {"panel": sha(panel_path), "prices": sha(price_path), "scaler": sha(scaler_path)}
    return days, prices, scaler, hashes


def fit(fold: str, seed: int) -> dict:
    OUT.mkdir(exist_ok=True)
    path = OUT / f"PPO_{fold}_seed{seed}.zip"
    receipt = OUT / f"PPO_{fold}_seed{seed}.json"
    if path.exists() or receipt.exists():
        raise RuntimeError(f"PPO_FIT_ALREADY_EXISTS:{fold}:{seed}")
    days, prices, scaler, hashes = input_bundle(fold)
    env = Top20ReplayEnv(days, prices, scaler)
    env.reset(seed=seed)
    # A complete, unchanged path must be executable before a model sees reward.
    for _ in days:
        env.step(np.full(21, -1.0, dtype=np.float32))
    env = Top20ReplayEnv(days, prices, scaler)
    torch.set_num_threads(1)
    model = PPO("MlpPolicy", env, policy_kwargs={"net_arch": {"pi": [32, 16], "vf": [32, 16]}},
                learning_rate=3e-4, gamma=.99, gae_lambda=.95, clip_range=.2,
                n_steps=128, batch_size=64, n_epochs=5, ent_coef=0,
                max_grad_norm=.5, seed=seed, verbose=0, device="cpu")
    count = sum(p.numel() for p in model.policy.parameters())
    if count > 50000:
        raise RuntimeError(f"PPO_PARAMETER_BUDGET:{count}")
    before = actor_sha(model)
    whole_before = whole_policy_sha(model)
    callback = StepCounter()
    model.learn(total_timesteps=TIMESTEPS, callback=callback, reset_num_timesteps=True,
                progress_bar=False)
    after = actor_sha(model)
    whole_after = whole_policy_sha(model)
    if before == after or model.num_timesteps != TIMESTEPS:
        raise RuntimeError("PPO_NO_UPDATE_OR_WRONG_STEP_BUDGET")
    optimizer_steps = {int(value["step"]) for value in model.policy.optimizer.state.values()
                       if "step" in value}
    if optimizer_steps != {callback.optimizer_steps}:
        raise RuntimeError(f"PPO_OPTIMIZER_STEP_COUNT:{optimizer_steps}:{callback.optimizer_steps}")
    tmp = OUT / f"PPO_{fold}_seed{seed}.tmp.zip"
    model.save(tmp)
    os.replace(tmp, path)
    result = {"status": "FITTED", "fold": fold, "seed": seed,
              "train_cutoff_exclusive": FOLDS[fold], "first_signal": str(days[0]["date"].date()),
              "last_signal": str(days[-1]["date"].date()),
              "last_terminal": str(days[-1]["terminal"].date()),
              "unique_signal_days": len(days), "environment_steps": int(model.num_timesteps),
              "optimizer_steps": optimizer_steps.pop(),
              "actor_before_sha256": before, "actor_after_sha256": after,
              "whole_policy_before_sha256": whole_before,
              "whole_policy_after_sha256": whole_after,
              "parameter_count": count, "model_path": path.name, "model_sha256": sha(path),
              "input_sha256": hashes, "torch": torch.__version__,
              "stable_baselines3": __import__("stable_baselines3").__version__,
              "reward": "100*log(next observation NAV / current signal-close NAV); original fees included",
              "settings": {"n_steps": 128, "batch_size": 64, "n_epochs": 5,
                           "learning_rate": .0003, "gamma": .99, "gae_lambda": .95,
                           "clip_range": .2, "ent_coef": 0, "max_grad_norm": .5,
                           "net_arch": {"pi": [32, 16], "vf": [32, 16]}}}
    atomic_json(receipt, result)
    return result


def backfill_actor_audit(fold: str, seed: int) -> dict:
    """Read-only model recovery plus receipt correction; never call learn()."""
    receipt = OUT / f"PPO_{fold}_seed{seed}.json"
    record = json.loads(receipt.read_text(encoding="utf-8"))
    days, prices, scaler, hashes = input_bundle(fold)
    if hashes != record["input_sha256"]:
        raise RuntimeError("PPO_BACKFILL_INPUT_CHANGED")
    env = Top20ReplayEnv(days, prices, scaler)
    env.reset(seed=seed)
    torch.set_num_threads(1)
    initial = PPO("MlpPolicy", env, policy_kwargs={"net_arch": {"pi": [32, 16], "vf": [32, 16]}},
                  learning_rate=3e-4, gamma=.99, gae_lambda=.95, clip_range=.2,
                  n_steps=128, batch_size=64, n_epochs=5, ent_coef=0,
                  max_grad_norm=.5, seed=seed, verbose=0, device="cpu")
    trained_path = OUT / record["model_path"]
    if sha(trained_path) != record["model_sha256"]:
        raise RuntimeError("PPO_BACKFILL_MODEL_CHANGED")
    trained = PPO.load(trained_path, device="cpu")
    if (whole_policy_sha(initial) != record["actor_before_sha256"] or
            whole_policy_sha(trained) != record["actor_after_sha256"]):
        raise RuntimeError("PPO_BACKFILL_POLICY_MISMATCH")
    record["whole_policy_before_sha256"] = record["actor_before_sha256"]
    record["whole_policy_after_sha256"] = record["actor_after_sha256"]
    record["actor_before_sha256"] = actor_sha(initial)
    record["actor_after_sha256"] = actor_sha(trained)
    if record["actor_before_sha256"] == record["actor_after_sha256"]:
        raise RuntimeError("PPO_ACTOR_NOT_UPDATED")
    record["actor_audit"] = "READ_ONLY_SEEDED_INITIALIZATION_AND_FROZEN_MODEL_RECOVERY"
    atomic_json(receipt, record)
    return {"fold": fold, "seed": seed,
            "actor_before_sha256": record["actor_before_sha256"],
            "actor_after_sha256": record["actor_after_sha256"]}


def validate(fold: str) -> dict:
    """Three fixed seeds decide on one shared actual portfolio state.

    V25 is a fixed confirmation path; FINAL is explicitly fitted-in-path.
    """
    prefix = f"DEVELOPMENT_{fold}" if fold in ("D1", "D2") else (
        "V25" if fold == "V25" else "FINAL_INSAMPLE")
    destination = HERE / f"{prefix}_P10_DAILY.parquet"
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    price = PriceStore(pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet"))
    scaler = joblib.load(HERE / "models" / f"SCALER_{fold}.joblib")
    bounds = {"D1": ("2024-01-01", "2024-06-30"),
              "D2": ("2024-07-01", "2024-12-31"),
              "V25": ("2025-01-01", "2025-12-31")}
    if fold == "FINAL":
        section = panel.loc[panel.label_available_at_utc.lt(pd.Timestamp("2026-01-01", tz="UTC"))]
    else:
        start, end = bounds[fold]
        section = panel.loc[panel.signal_date.between(start, end) &
                            panel.label_end_date.le(pd.Timestamp(end))]
    days = []
    for date, block in section.groupby("signal_date", sort=True):
        block = block.sort_values("raw_a2_rank")
        days.append({"date": pd.Timestamp(date), "execution": pd.Timestamp(block.execution_date.iloc[0]),
                     "terminal": pd.Timestamp(block.label_end_date.iloc[0]),
                     "tickers": block.ticker.astype(str).tolist(),
                     "keys": block.experiment_security_key.astype(str).tolist(),
                     "features": block[FEATURES].to_numpy(float),
                     "usable": bool(block.base_usable_day.all())})
    env = Top20ReplayEnv(days, price, scaler, record=True)
    obs, _ = env.reset()
    models = [PPO.load(OUT / f"PPO_{fold}_seed{s}.zip", device="cpu") for s in SEEDS]
    for model in models:
        model.policy.set_training_mode(False)
    done = False
    while not done:
        actions = [model.predict(obs, deterministic=True)[0] for model in models]
        mean_target = np.mean([project_capped_simplex(a) for a in actions], axis=0)
        # The average of feasible projected points is feasible; project again
        # only to translate that target to this fixed 21-score environment API.
        # A 21-vector already on the simplex is a fixed point of the projection.
        obs, reward, done, _, info = env.step(mean_target.astype(np.float32))
    rows, weights, trades, holdings, actions = [], [], [], [], []
    for item, transaction in zip(env.actions, env.transactions):
        rows.append({"fold": fold, "policy": "P10", "signal_date": item["signal_date"],
                     "execution_date": pd.Timestamp(transaction["execution_date"]),
                     "qualification": not item["fallback"],
                     "fallback": "BASE_INPUT_FALLBACK" if item["fallback"] else "",
                     "net_nav_at_execution": transaction["net_nav"],
                     "cash_at_execution": transaction["cash"], "fee": transaction["fee"],
                     "traded_notional": transaction["traded_notional"],
                     "stock_target_sum": float(item["executed_weights"].sum()),
                     "signal_close_nav": item["signal_nav"]})
        for j, (ticker, key) in enumerate(zip(item["tickers"], item["keys"])):
            weights.append({"fold": fold, "policy": "P10", "signal_date": item["signal_date"],
                            "ticker": ticker, "security_key": key,
                            "signal_weight": item["signal_weights"][j],
                            "target_weight": item["executed_weights"][j],
                            "target_over_5pct": item["executed_weights"][j] / .05,
                            "cash_target": 1 - item["executed_weights"].sum()})
        for trade in transaction["trades"]:
            trades.append({"fold": fold, "policy": "P10", "signal_date": item["signal_date"],
                           "execution_date": transaction["execution_date"], **trade})
        for ticker in sorted(set(item["tickers"]) | set(transaction["shares_before"])):
            before = float(transaction["shares_before"].get(ticker, 0.))
            after = float(transaction["shares_after"].get(ticker, 0.))
            delta = after - before
            if before <= 1e-14 and after <= 1e-14:
                label = "WAIT"
            elif before <= 1e-14:
                label = "BUY"
            elif after <= 1e-14:
                label = "EXIT"
            elif delta > 1e-14:
                label = "ADD"
            elif delta < -1e-14:
                label = "REDUCE"
            else:
                label = "HOLD"
            actions.append({"fold": fold, "policy": "P10", "signal_date": item["signal_date"],
                            "execution_date": pd.Timestamp(transaction["execution_date"]),
                            "ticker": ticker, "action_from_actual_quantity": label,
                            "shares_before": before, "shares_after": after,
                            "quantity_change": delta,
                            "out_of_list": ticker not in set(item["tickers"])})
        for ticker, quantity in transaction["shares_after"].items():
            execution = pd.Timestamp(transaction["execution_date"])
            opening = float(price.open[(execution, ticker)])
            holdings.append({"fold": fold, "policy": "P10",
                             "signal_date": item["signal_date"],
                             "execution_date": execution,
                             "ticker": ticker, "shares_after_execution": quantity,
                             "execution_open": opening,
                             "position_value_after_execution": quantity * opening,
                             "cash_after_execution": transaction["cash"],
                             "nav_after_execution": transaction["net_nav"]})
    last = env.days[-1]
    rows.append({"fold": fold, "policy": "P10", "signal_date": pd.NaT,
                 "execution_date": last["terminal"], "qualification": False,
                 "fallback": "TERMINAL_LIQUIDATION", "net_nav_at_execution": env.account.cash,
                 "cash_at_execution": env.account.cash, "fee": info["terminal_fee"],
                 "traded_notional": info["terminal_traded_notional"],
                 "stock_target_sum": 0., "signal_close_nav": np.nan})
    daily_frame = pd.DataFrame(rows)
    if destination.exists():
        existing = pd.read_parquet(destination)
        if len(existing) != len(daily_frame) or not np.allclose(
                existing.net_nav_at_execution, daily_frame.net_nav_at_execution,
                atol=1e-12, rtol=0):
            raise RuntimeError("P10_DEVELOPMENT_REPLAY_MISMATCH")
    else:
        daily_frame.to_parquet(destination, index=False)
    pd.DataFrame(weights).to_parquet(HERE / f"{prefix}_P10_WEIGHTS.parquet", index=False)
    pd.DataFrame(trades).to_parquet(HERE / f"{prefix}_P10_TRADES.parquet", index=False)
    pd.DataFrame(holdings).to_parquet(HERE / f"{prefix}_P10_HOLDINGS.parquet", index=False)
    pd.DataFrame(actions).to_parquet(HERE / f"{prefix}_P10_ACTIONS.parquet", index=False)
    seed_diagnostics = {}
    for seed, model in zip(SEEDS, models):
        independent = Top20ReplayEnv(days, price, scaler)
        own_obs, _ = independent.reset()
        own_cash = []
        own_done = False
        while not own_done:
            own_action = model.predict(own_obs, deterministic=True)[0]
            own_obs, _, own_done, _, own_info = independent.step(own_action)
            own_cash.append(own_info["execution_cash_weight"])
        seed_diagnostics[str(seed)] = {
            "terminal_nav": float(independent.account.cash),
            "total_fees": float(independent.account.fees),
            "mean_cash_weight_after_execution": float(np.mean(own_cash)),
            "reward_sum": independent.reward_sum,
            "model_sha256": sha(OUT / f"PPO_{fold}_seed{seed}.zip")}
    result = {"fold": fold, "policy": "P10", "scope": (
              "FINAL_FIT_IN_PATH" if fold == "FINAL" else
              "V25_CONFIRMATION" if fold == "V25" else "DEVELOPMENT"),
              "signal_days": len(days),
              "terminal_nav": float(env.account.cash), "reward_sum": env.reward_sum,
              "seed_independent_diagnostics_only": seed_diagnostics,
              "validation_model_sha256": {str(s): sha(OUT / f"PPO_{fold}_seed{s}.zip") for s in SEEDS},
              "source_panel_sha256": sha(HERE / "PRE2026_SHARED_PANEL.parquet")}
    atomic_json(HERE / f"{prefix}_P10_MANIFEST.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold", choices=FOLDS, required=True)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--audit-actor", action="store_true")
    args = parser.parse_args()
    if args.audit_actor:
        if args.seed is None:
            raise SystemExit("--audit-actor requires --seed")
        print(json.dumps(backfill_actor_audit(args.fold, args.seed), indent=2), flush=True)
    elif args.validate:
        print(json.dumps(validate(args.fold), indent=2), flush=True)
    elif args.seed is not None:
        print(json.dumps(fit(args.fold, args.seed), indent=2), flush=True)
    else:
        raise SystemExit("supply --seed or --validate")


if __name__ == "__main__":
    main()
