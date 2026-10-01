"""Fixed REINFORCE/PPO policies using the same real account replay engine.

The optimizer never observes a future price as an input. Rollout rewards are
read only after the shared engine has produced its pre-open accounting ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
import common
import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ENGINE_SOURCE = HERE.parent / "a2_buy_sell_cash_multimodel_20260928" / "engine_v2.py"
_spec = importlib.util.spec_from_file_location("a2_pto_frozen_rl_engine", ENGINE_SOURCE)
engine = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = engine
_spec.loader.exec_module(engine)
torch.set_num_threads(2)
FEATURES = common.FEATURES
GRID = np.array([0., .025, .05, .075, .1])
POLICIES = ("reinforce_updated", "reinforce_zero", "ppo_updated", "ppo_zero")
CUTOFFS = {"validation": "2025-01-01", "final": "2026-01-01"}
SEED = common.SEED
EPOCHS = 4
GAMMA = .97
CLIP = .2
MAX_CANDIDATES = 80
PROTOCOL = HERE / "RL_PROTOCOL.md"
MODEL_ROOT = HERE / "models" / "rl"
PREDICTION_ROOT = HERE / "predictions" / "rl"


def sha(path):
    return common.sha(path)


def write_json(path, value):
    common.write_json(path, value)


class ActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.hidden = nn.Linear(len(FEATURES) + 3, 32)
        self.actor = nn.Linear(32, len(GRID))
        self.value = nn.Linear(32, 1)

    def forward(self, x):
        z = torch.tanh(self.hidden(x))
        return self.actor(z), self.value(z).flatten()


def select_observations(day, context, limit=MAX_CANDIDATES):
    """Fixed full-pool hash candidates plus every observable actual holding."""
    if day.ticker.duplicated().any():
        raise ValueError("RL_DUPLICATE_DECISION_KEYS")
    if len(day) == 0:
        return day.copy()
    usable = np.isfinite(day[FEATURES].to_numpy(float)).all(axis=1)
    part = day.loc[usable].copy()
    held = set(context.current_units)
    eligible = part.new_buy_eligible.fillna(False).astype(bool) if "new_buy_eligible" in part else pd.Series(True, index=part.index)
    date = pd.Timestamp(context.signal_date).strftime("%Y-%m-%d")
    part["_key"] = [hashlib.sha256(f"{date}|{t}|{SEED}".encode()).hexdigest() for t in part.ticker]
    new = part.loc[eligible & ~part.ticker.isin(held)].sort_values(["_key", "ticker"], kind="mergesort").head(limit)
    already = part.loc[part.ticker.isin(held)]
    selected = pd.concat([new, already]).drop_duplicates("ticker").sort_values("ticker", kind="mergesort")
    return selected.drop(columns="_key")


def returns_to_go(rewards, valid, gamma=GAMMA):
    rewards = np.asarray(rewards, float)
    valid = np.asarray(valid, bool)
    if rewards.shape != valid.shape:
        raise ValueError("RL_REWARD_MASK_SHAPE")
    output = np.zeros(len(rewards))
    accumulated = 0.
    for i in range(len(rewards) - 1, -1, -1):
        # A missing account reward breaks the return chain, rather than
        # pretending unknown/stale prices generated a zero economic return.
        accumulated = rewards[i] + gamma * accumulated if valid[i] else 0.
        output[i] = accumulated
    return output


class _Policy:
    def __init__(self, model, scaler, *, sampled=False, generator=None, capture=False):
        self.model, self.scaler = model, scaler
        self.sampled, self.generator, self.capture = sampled, generator, capture
        self.records = []
        self.ages = {}
        self.previous_held = set()

    def __call__(self, day, context):
        held = set(context.current_units)
        for ticker in list(self.ages):
            if ticker not in held:
                del self.ages[ticker]
        for ticker in held:
            self.ages[ticker] = self.ages.get(ticker, -1) + 1
        selected = select_observations(day, context)
        tickers = selected.ticker.astype(str).tolist()
        if len(selected):
            features = np.clip(self.scaler.transform(selected[FEATURES].to_numpy(float)), -8., 8.)
            states = np.column_stack([
                [context.current_weights.get(t, 0.) for t in tickers],
                np.full(len(tickers), context.cash_weight),
                [min(self.ages.get(t, 0), 252) / 252. for t in tickers],
            ])
            observations = np.column_stack([features, states]).astype(np.float32)
            if not np.isfinite(observations).all():
                raise ValueError("RL_NONFINITE_SIGNAL_OBSERVATION")
            with torch.no_grad():
                logits, value = self.model(torch.from_numpy(observations))
                probabilities = torch.softmax(logits, dim=1)
                if self.sampled:
                    actions = torch.multinomial(probabilities, 1, generator=self.generator).flatten()
                else:
                    actions = logits.argmax(dim=1)
                categorical = torch.distributions.Categorical(logits=logits)
                old_logprob = float(categorical.log_prob(actions).sum())
                old_value = float(value.mean())
            action_array = actions.numpy()
            output = {ticker: float(GRID[action]) for ticker, action in zip(tickers, action_array)}
            raw = {ticker: {"action_index": int(action), "raw_target": float(GRID[action]),
                            "probabilities": probabilities[i].numpy().astype(float).tolist(),
                            "current_weight": float(states[i, 0]), "cash_weight": float(states[i, 1]),
                            "age_normalized": float(states[i, 2])}
                   for i, (ticker, action) in enumerate(zip(tickers, action_array))}
        else:
            observations = np.empty((0, len(FEATURES) + 3), dtype=np.float32)
            action_array = np.empty(0, dtype=np.int64)
            old_logprob = old_value = 0.
            output = raw = {}
        if self.capture:
            self.records.append({"signal_date": pd.Timestamp(context.signal_date),
                                 "decision_id": day.attrs.get("decision_id"), "tickers": tickers,
                                 "observations": observations, "actions": action_array,
                                 "old_logprob": old_logprob, "old_value": old_value,
                                 "signal_nav": float(context.nav), "signal_cash": float(context.cash),
                                 "reserved_slots": int(context.reserved_slots)})
        return engine.HoldingAwareDecision(model_decisions=output, raw_model_outputs=raw)


def reward_ledger(result, records, calendar, cutoff):
    daily = result.daily.set_index("date")
    calendar = pd.DatetimeIndex(calendar)
    locations = {d: i for i, d in enumerate(calendar)}
    rows = []
    for record in records:
        signal = record["signal_date"]
        index = locations[signal]
        if index + 2 >= len(calendar):
            raise ValueError("RL_REWARD_END_NOT_IN_CALENDAR")
        execution, end = calendar[index + 1], calendar[index + 2]
        if not signal < execution < end < pd.Timestamp(cutoff):
            raise ValueError("RL_REWARD_BOUNDARY_VIOLATION")
        first, last = daily.loc[execution], daily.loc[end]
        denominator, numerator = float(first.open_pretrade_nav), float(last.open_pretrade_nav)
        price_valid = all(int(row.open_stale_count) == int(row.open_unknown_count) == 0
                          for row in [first, last])
        nav_valid = np.isfinite([denominator, numerator]).all() and min(denominator, numerator) > 0
        valid = bool(price_valid and nav_valid and len(record["tickers"]) > 0)
        reward = float(np.log(numerator / denominator)) if valid else 0.
        rows.append({"signal_date": signal, "execution_date": execution, "reward_end_date": end,
                     "decision_id": record["decision_id"], "valid_learning_reward": valid,
                     "mask_reason": "AVAILABLE" if valid else "UNKNOWN_OR_STALE_OPEN_NAV_OR_NO_ACTION_INPUT",
                     "log_net_reward": reward, "denominator_preopen_nav": denominator,
                     "numerator_preopen_nav": numerator,
                     "action_execution_fees": float(first.transaction_cost_amount),
                     "actual_names_after_execution": int(first.actual_name_count),
                     "execution_close_cash": float(first.cash),
                     "target_count": len(record["tickers"]),
                     "old_joint_logprob": record["old_logprob"], "old_value": record["old_value"]})
    frame = pd.DataFrame(rows)
    if frame.empty or not frame.valid_learning_reward.any():
        raise ValueError("RL_NO_VALID_REWARDS")
    return frame


def _flat_observations(records):
    matrices, actions, groups = [], [], []
    for i, record in enumerate(records):
        if len(record["tickers"]):
            matrices.append(record["observations"])
            actions.append(record["actions"])
            groups.append(np.full(len(record["tickers"]), i, dtype=np.int64))
    if not matrices:
        raise ValueError("RL_NO_OBSERVATIONS")
    return torch.from_numpy(np.concatenate(matrices)), torch.from_numpy(np.concatenate(actions)), torch.from_numpy(np.concatenate(groups))


def _statistics(model, flat, n_steps):
    observations, actions, groups = flat
    logits, values = model(observations)
    categorical = torch.distributions.Categorical(logits=logits)
    logprobs = torch.zeros(n_steps).index_add(0, groups, categorical.log_prob(actions))
    entropy = torch.zeros(n_steps).index_add(0, groups, categorical.entropy())
    counts = torch.zeros(n_steps).index_add(0, groups, torch.ones(len(groups))).clamp_min(1.)
    value = torch.zeros(n_steps).index_add(0, groups, values) / counts
    return logprobs, entropy, value


def _normalize(values, valid):
    values = np.asarray(values, float)
    active = values[valid]
    if len(active) == 0:
        raise ValueError("RL_EMPTY_ADVANTAGE")
    return (values - active.mean()) / max(float(active.std()), 1e-8)


def optimize_rollout(model, optimizer, records, rewards, method, epochs=1):
    if method not in ("reinforce", "ppo") or epochs not in (1, EPOCHS):
        raise ValueError("RL_UNREGISTERED_OPTIMIZATION_BUDGET")
    flat = _flat_observations(records)
    valid_np = rewards.valid_learning_reward.to_numpy(bool, copy=True)
    valid = torch.from_numpy(valid_np)
    returns = returns_to_go(rewards.log_net_reward.to_numpy(float), valid_np)
    old_values = np.array([r["old_value"] for r in records])
    advantages = returns if method == "reinforce" else returns * 100. - old_values
    advantage = torch.tensor(_normalize(advantages, valid_np), dtype=torch.float32)
    target_values = torch.tensor(returns * 100., dtype=torch.float32)
    old_logprob = torch.tensor([r["old_logprob"] for r in records], dtype=torch.float32)
    logs = []
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        current_logprob, entropy, value = _statistics(model, flat, len(records))
        if method == "reinforce":
            policy_loss = -(current_logprob[valid] * advantage[valid]).mean()
            value_loss = value.sum() * 0.
            clip_fraction = 0.
            approx_kl = 0.
            numeric_ratio_clamps = 0
        else:
            log_ratio = current_logprob - old_logprob
            numeric_ratio_clamps = int((log_ratio.abs() > 20).sum())
            ratio = torch.exp(log_ratio.clamp(-20., 20.))
            unclipped, clipped = ratio * advantage, ratio.clamp(1. - CLIP, 1. + CLIP) * advantage
            policy_loss = -torch.minimum(unclipped[valid], clipped[valid]).mean()
            value_loss = ((value[valid] - target_values[valid]) ** 2).mean()
            clip_fraction = float(((ratio[valid] - 1.).abs() > CLIP).float().mean().detach())
            approx_kl = float((old_logprob[valid] - current_logprob[valid]).mean().detach())
        loss = policy_loss + .5 * value_loss - .001 * entropy[valid].mean()
        if not torch.isfinite(loss):
            raise ValueError("RL_NONFINITE_OBJECTIVE")
        loss.backward()
        gradient_norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 2.))
        if not np.isfinite(gradient_norm):
            raise ValueError("RL_NONFINITE_GRADIENT")
        optimizer.step()
        if any(not torch.isfinite(p).all() for p in model.parameters()):
            raise ValueError("RL_NONFINITE_FITTED_PARAMETERS")
        logs.append({"optimization_epoch": epoch + 1, "method": method,
                     "loss": float(loss.detach()), "policy_loss": float(policy_loss.detach()),
                     "value_loss": float(value_loss.detach()), "gradient_norm_before_clip": gradient_norm,
                     "clip_fraction": clip_fraction, "approx_kl": approx_kl,
                     "numeric_log_ratio_clamp_count": numeric_ratio_clamps,
                     "valid_learning_steps": int(valid_np.sum()), "masked_learning_steps": int((~valid_np).sum()),
                     "rollout_reuse_count": epoch + 1,
                     "optimizer_steps_this_epoch": 1})
    return logs


def _save_rollout(directory, result, policy, rewards):
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("daily", "trades", "positions", "target_decisions", "diagnostics", "raw_model_outputs",
                 "signal_contexts", "operational_actions", "execution_results", "valuation_intervals"):
        getattr(result, name).to_parquet(directory / f"{name}.parquet", index=False)
    rewards.to_parquet(directory / "learning_rewards.parquet", index=False)
    rows = []
    for record in policy.records:
        for i, ticker in enumerate(record["tickers"]):
            row = {"signal_date": record["signal_date"], "decision_id": record["decision_id"],
                   "ticker": ticker, "action_index": int(record["actions"][i]),
                   "raw_target_weight": float(GRID[record["actions"][i]])}
            row.update({f"obs_{j}": float(v) for j, v in enumerate(record["observations"][i])})
            rows.append(row)
    pd.DataFrame(rows).to_parquet(directory / "sampled_actions_and_observations.parquet", index=False)
    write_json(directory / "REPLAY_METADATA.json", result.metadata)


def _stage_market(frame, prices, calendar, cutoff):
    if not frame.signal_date.lt("2026-01-01").all() or not prices.trade_date.lt("2026-01-01").all():
        raise ValueError("RL_INPUT_NOT_PHYSICALLY_PRE2026")
    cal = pd.DatetimeIndex(calendar)
    cal = cal[(cal >= pd.Timestamp("2023-01-01")) & (cal < pd.Timestamp(cutoff))]
    if len(cal) < 10:
        raise ValueError("RL_STAGE_HISTORY_TOO_SHORT")
    part = frame.loc[frame.signal_date.isin(cal[:-2])].copy()
    price_part = prices.loc[prices.trade_date.isin(cal)].copy()
    if part.empty:
        raise ValueError("RL_NO_MATURE_STAGE_SIGNALS")
    return part, price_part, cal


def train_stage(stage):
    if stage not in CUTOFFS:
        raise ValueError("UNKNOWN_RL_STAGE")
    directory = MODEL_ROOT / stage
    receipt_path = directory / "TRAIN_RECEIPT.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["status"] != "PASS":
            raise RuntimeError("EXISTING_RL_STAGE_FAILURE_PRESERVED")
        for name, expected in receipt["artifacts_sha256"].items():
            if sha(directory / name) != expected:
                raise RuntimeError("RL_EXISTING_ARTIFACT_CHANGED")
        return receipt
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError("RL_PARTIAL_STAGE_PRESERVED")
    cutoff = CUTOFFS[stage]
    paths = [HERE / "data" / "pre.parquet", HERE / "data" / "pre_prices.parquet",
             HERE / "data" / "pre_calendar.parquet", Path(__file__), PROTOCOL,
             HERE / "common.py", ENGINE_SOURCE]
    bindings = {str(path): sha(path) for path in paths}
    frame = pd.read_parquet(paths[0])
    prices = pd.read_parquet(paths[1])
    calendar = pd.read_parquet(paths[2]).trade_date
    sample = common.training_sample(frame, cutoff)
    part, price_part, cal = _stage_market(frame, prices, calendar, cutoff)
    if sample.empty or not sample.label_end_date.lt(cutoff).all():
        raise ValueError("RL_SCALER_BOUNDARY_INVALID")
    with threadpool_limits(limits=2):
        scaler = StandardScaler().fit(sample[FEATURES].to_numpy(float))
    directory.mkdir(parents=True, exist_ok=False)
    sample[["signal_date", "ticker", "label_end_date"]].to_parquet(directory / "SCALER_SAMPLE_KEYS.parquet", index=False)
    joblib.dump(scaler, directory / "scaler.joblib", compress=3)
    specification = {"status": "PRE_FIT_LOCKED", "stage": stage, "cutoff_exclusive": cutoff,
                     "source_sha256": bindings, "protocol_sha256": sha(PROTOCOL), "seed": SEED,
                     "features": FEATURES, "account_features": ["current_weight", "cash_weight", "age_252"],
                     "feature_standardized_clip": [-8., 8.], "architecture": [35, 32, 5],
                     "activation": "tanh", "additional_value_head": 1,
                     "grid": GRID.tolist(), "policies": list(POLICIES), "axes": ["joint"],
                     "reinforce_rollouts": 4, "ppo_rollouts": 1, "optimization_epochs_each": 4,
                     "ppo_clip": CLIP, "gamma": GAMMA, "learning_rate": .001,
                     "gradient_clip": 2., "entropy_coefficient": .001, "ppo_value_coefficient": .5,
                     "maximum_new_candidates_per_signal": MAX_CANDIDATES,
                     "new_candidate_selection": "SHA256(date|ticker|seed), held observations always included",
                     "scaler_training_rows": len(sample), "scaler_label_end_max": str(sample.label_end_date.max().date()),
                     "signal_first": str(part.signal_date.min().date()),
                     "signal_last": str(part.signal_date.max().date()), "reward_end_last": str(cal[-1].date()),
                     "rewards": "actual following-open pretrade NAV / next-open pretrade NAV, including next-open action fees",
                     "unknown_reward_behavior": "preserve real account path; break return chain and mask learning reward",
                     "cost_bps": 10., "capacity_fraction": .01, "initial_cash": 1_000_000.,
                     "max_positions": 20, "max_weight": .1, "max_invested": .95,
                     "terminal_liquidation": False, "test2026_rows_read": 0, "hyperparameter_search_count": 0,
                     "all_prediction_inputs_from_fitted_predictors": False,
                     "scaler_sample_keys_sha256": sha(directory / "SCALER_SAMPLE_KEYS.parquet")}
    write_json(directory / "PRE_FIT_CONTRACT.json", specification)
    stage_logs, learned, artifacts = [], [], []
    started = time.monotonic()
    for method in ("reinforce", "ppo"):
        torch.manual_seed(SEED)
        model = ActorCritic()
        initial = {k: v.detach().clone() for k, v in model.state_dict().items()}
        zero_path = directory / f"{method}_zero.pt"
        torch.save(initial, zero_path)
        generator = torch.Generator().manual_seed(SEED)
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        n_rollouts = EPOCHS if method == "reinforce" else 1
        last_rewards = None
        for rollout in range(n_rollouts):
            policy = _Policy(model, scaler, sampled=True, generator=generator, capture=True)
            candidate = f"rl_train_{stage}_{method}_rollout{rollout + 1}"
            result = engine.run_replay(price_part, cal, part, policy, candidate=candidate,
                                      initial_cash=1_000_000., cost_bps=10., max_positions=20,
                                      max_weight=.1, max_invested=.95, capacity_fraction=.01,
                                      signal_start=part.signal_date.min(), signal_end=part.signal_date.max())
            rewards = reward_ledger(result, policy.records, cal, cutoff)
            _save_rollout(PREDICTION_ROOT / stage / method / f"rollout_{rollout + 1}", result, policy, rewards)
            logs = optimize_rollout(model, optimizer, policy.records, rewards, method,
                                    epochs=1 if method == "reinforce" else EPOCHS)
            for log in logs:
                log.update(stage=stage, rollout=rollout + 1,
                           cumulative_optimization_epoch=len(stage_logs) + 1,
                           reward_end_max=str(rewards.reward_end_date.max().date()),
                           reward_net_log_sum=float(rewards.loc[rewards.valid_learning_reward, "log_net_reward"].sum()),
                           rollout_transaction_cost=float(result.daily.transaction_cost_amount.sum()),
                           actual_account_final_nav=float(result.daily.nav.iloc[-1]),
                           actual_account_final_cash=float(result.daily.cash.iloc[-1]))
                stage_logs.append(log)
                print(json.dumps(log), flush=True)
            last_rewards = rewards
            del result, policy
        final_path = directory / f"{method}_updated.pt"
        torch.save(model.state_dict(), final_path)
        delta = float(sum((v.detach() - initial[k]).square().sum().item()
                          for k, v in model.state_dict().items()) ** .5)
        actor_delta = float(sum((v.detach() - initial[k]).square().sum().item()
                                for k, v in model.state_dict().items() if not k.startswith("value.")) ** .5)
        if not np.isfinite(delta) or min(delta, actor_delta) <= 0:
            raise RuntimeError("RL_ACTOR_DID_NOT_UPDATE")
        learned.append({"method": method, "rollouts": n_rollouts, "optimization_epochs": EPOCHS,
                        "parameter_delta_l2": delta, "actor_parameter_delta_l2": actor_delta,
                        "parameter_count": sum(p.numel() for p in model.parameters()),
                        "reward_end_max": str(last_rewards.reward_end_date.max().date()),
                        "zero_artifact": zero_path.name, "final_artifact": final_path.name,
                        "zero_sha256": sha(zero_path), "final_sha256": sha(final_path)})
        artifacts.extend([zero_path.name, final_path.name])
    pd.DataFrame(stage_logs).to_csv(directory / "TRAINING_CURVE.csv", index=False)
    artifacts.extend(["scaler.joblib", "SCALER_SAMPLE_KEYS.parquet", "PRE_FIT_CONTRACT.json", "TRAINING_CURVE.csv"])
    if not all(sha(Path(path)) == value for path, value in bindings.items()):
        raise RuntimeError("RL_FROZEN_SOURCE_DRIFT")
    receipt = {**specification, "status": "PASS", "fits": learned,
               "optimizer_steps": sum(r["optimizer_steps_this_epoch"] for r in stage_logs),
               "reinforce_optimizer_steps": sum(r["method"] == "reinforce" for r in stage_logs),
               "ppo_optimizer_steps": sum(r["method"] == "ppo" for r in stage_logs),
               "ppo_rollout_reused_exactly_four_epochs": True,
               "ppo_clip_fractions": [r["clip_fraction"] for r in stage_logs if r["method"] == "ppo"],
               "artifacts_sha256": {name: sha(directory / name) for name in artifacts},
               "torch": torch.__version__, "fit_seconds": time.monotonic() - started}
    write_json(receipt_path, receipt)
    return receipt


class RLPolicy(_Policy):
    """Frozen deterministic policy for an independent shared-engine account."""
    def __init__(self, name="reinforce_updated", stage="final"):
        if name not in POLICIES or stage not in CUTOFFS:
            raise ValueError("UNKNOWN_RL_POLICY_OR_STAGE")
        directory = MODEL_ROOT / stage
        receipt = json.loads((directory / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
        if receipt["status"] != "PASS" or receipt["test2026_rows_read"] != 0:
            raise ValueError("RL_RECEIPT_INVALID")
        for filename in [f"{name}.pt", "scaler.joblib"]:
            if sha(directory / filename) != receipt["artifacts_sha256"][filename]:
                raise ValueError(f"RL_MODEL_HASH_MISMATCH:{filename}")
        model = ActorCritic()
        model.load_state_dict(torch.load(directory / f"{name}.pt", map_location="cpu", weights_only=True))
        model.eval()
        super().__init__(model, joblib.load(directory / "scaler.joblib"))
        self.name, self.stage, self.receipt = name, stage, receipt


def register():
    path = HERE / "RL_REGISTRY.json"
    registry = {"status": "REGISTERED_BEFORE_RL_FITS", "protocol_sha256": sha(PROTOCOL),
                "seed": SEED, "axes": ["joint"], "crosses_pto_risk_optimizer": False,
                "policies": [{"strategy": f"rl_{name}__joint", "policy": name,
                              "axis": "joint", "initial_cash": 1_000_000.,
                              "updated": name.endswith("updated"),
                              "zero_update_match": name.replace("updated", "zero") if name.endswith("updated") else None}
                             for name in POLICIES],
                "training_stages": CUTOFFS, "policies_per_evaluation_window": 4,
                "reinforce_rollouts": 4, "ppo_rollouts": 1,
                "optimization_epochs_each": 4, "added_seed_searches": 0,
                "source_sha256": sha(Path(__file__))}
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != registry:
            raise RuntimeError("RL_REGISTRY_CHANGED")
    else:
        write_json(path, registry)
    return registry


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=[*CUTOFFS, "all"], default="all")
    args = parser.parse_args()
    register()
    for requested in CUTOFFS if args.stage == "all" else [args.stage]:
        train_stage(requested)
