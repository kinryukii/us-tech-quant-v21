"""Fresh REINFORCE / clipped PPO controls on the common real account engine.

The environment is fast_account.run_many, including its actual units, cash,
next-open fills, cost and capacity rules. Training reads only physically
isolated pre2026 inputs. The stochastic action is a Gaussian latent logit
vector followed by a deterministic constrained target-weight projection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import torch
from torch import nn

from build_inputs import FEATURES
from fast_account import AccountContext, MarketArrays, TargetDecision, run_many

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "models"
SEED = 20260928
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
SPEC = dict(seed=SEED, chronological_epochs=10, first_signal="2023-01-03",
            architecture=[35, 32, 16, 1], learning_rate=0.001, weight_decay=0.0001,
            gamma=0.97, gaussian_logit_sd=0.35, minimum_proposal_weight=0.02,
            max_positions=20, max_weight=0.10, max_invested=0.95,
            initial_cash=1_000_000.0, cost_bps=10.0, capacity_fraction=0.01,
            reinforce_updates_per_episode=1, ppo_clip=0.2,
            ppo_chronological_minibatch_steps=32, ppo_update_passes=1,
            ppo_critic_coefficient=0.5, gradient_norm_cap=2.0,
            objective="discounted untruncated next-open account log return net of actual fills and fees",
            reward="log(pretrade_nav at signal+2 / pretrade_nav at signal+1)",
            value_state="mean of per-security critic outputs on the same 35 observable inputs",
            ppo_ratio_numerical_log_cap=20.0,
            reuse="common account engine implementation only; no old actor or normalizer weights")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                                    allow_nan=False), encoding="utf-8")


def state_digest(model):
    digest = hashlib.sha256()
    for name, value in model.state_dict().items():
        digest.update(name.encode())
        digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


class Actor(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(35, 32), nn.Tanh(), nn.Linear(32, 16),
                                 nn.Tanh(), nn.Linear(16, 1))
        nn.init.constant_(self.net[-1].bias, -0.7)

    def forward(self, features):
        return self.net(features).flatten()


class Critic(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(35, 32), nn.Tanh(), nn.Linear(32, 16),
                                 nn.Tanh(), nn.Linear(16, 1))

    def forward(self, observations):
        return self.net(observations).mean()


def project_logits(logits, upper, budget, slots, tickers):
    """Signal-only projection retaining cash and the original hard TOP20 cap."""
    logits = np.asarray(logits, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if not np.isfinite(logits).all() or slots < 0 or budget < 0:
        raise ValueError("INVALID_RL_SIGNAL_PROJECTION")
    proposal = np.minimum(0.1 / (1.0 + np.exp(-np.clip(logits, -30, 30))), upper)
    proposal[proposal < SPEC["minimum_proposal_weight"]] = 0.0
    order = np.lexsort((np.asarray(tickers, dtype=str), -logits))
    keep = np.zeros(len(logits), dtype=bool)
    keep[order[:min(int(slots), len(order))]] = True
    proposal *= keep
    total = float(proposal.sum())
    if total > budget:
        proposal *= budget / total
    return proposal


def observable_state(context: AccountContext, features, row, mean, scale):
    """Use only signal-close market features and this account's executed state."""
    features = np.asarray(features, dtype=float)
    if features.shape != (len(context.tickers), 32):
        raise ValueError("RL_FEATURE_MATRIX_MUST_BE_N_BY_32")
    explicit = context.decision_mask[row] & np.isfinite(features).all(axis=1)
    current = np.nan_to_num(context.current_weights[row], nan=0.0)
    additionally_reserved = (context.current_units[row] > 1e-10) & ~explicit & ~context.operational_mask[row]
    reserved = context.reserved_mask[row] | additionally_reserved
    budget = max(0.0, context.max_invested - float(current[reserved].sum()))
    slots = max(0, context.max_positions - int(reserved.sum()))
    ids = np.flatnonzero(explicit)
    if not len(ids):
        return ids, None, np.array([]), budget, slots, explicit
    market = np.clip((features[ids] - mean) / scale, -8, 8)
    observations = torch.tensor(np.column_stack([
        market, current[ids], np.repeat(context.cash_weight[row], len(ids)),
        context.current_units[row, ids] > 1e-10,
    ]), dtype=torch.float32)
    upper = np.where(context.buy_allowed[row, ids], context.max_weight,
                     np.minimum(current[ids], context.max_weight))
    return ids, observations, upper, budget, slots, explicit


def prepare_market(panel, prices, cutoff):
    """Purged stage market, with every reward ending strictly before cutoff."""
    cutoff = pd.Timestamp(cutoff)
    if cutoff > pd.Timestamp("2026-01-01") or not panel.signal_date.lt("2026-01-01").all():
        raise ValueError("RL_TRAINING_BOUNDARY")
    if not prices.trade_date.lt("2026-01-01").all():
        raise ValueError("RL_PHYSICAL_PRICE_BOUNDARY")
    mature = panel.signal_date.ge(SPEC["first_signal"]) & panel.signal_date.lt(cutoff)
    mature &= panel.label_available & panel.label_end_date.lt(cutoff)
    mature &= np.isfinite(panel[FEATURES].to_numpy(float)).all(axis=1)
    rows = panel.loc[mature].sort_values(["signal_date", "ticker"]).copy()
    if rows.empty or rows.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("EMPTY_OR_DUPLICATE_RL_STAGE")
    mean = rows[FEATURES].to_numpy(float).mean(axis=0)
    scale = rows[FEATURES].to_numpy(float).std(axis=0)
    scale[scale < 1e-12] = 1.0
    px = prices.loc[prices.trade_date.ge(SPEC["first_signal"]) & prices.trade_date.lt(cutoff)].copy()
    dates = pd.DatetimeIndex(sorted(px.loc[px.ticker.eq("QQQ"), "trade_date"].unique()))
    tickers = np.asarray(sorted(rows.ticker.astype(str).unique()))
    date_map = {d: i for i, d in enumerate(dates)}
    ticker_map = {t: i for i, t in enumerate(tickers)}
    shape = (len(dates), len(tickers))
    feature_cube = np.full((*shape, 32), np.nan, dtype=np.float32)
    adv = np.full(shape, np.nan)
    present = np.zeros(shape, dtype=bool)
    eligible = np.zeros(shape, dtype=bool)
    di = rows.signal_date.map(date_map).to_numpy(int)
    ci = rows.ticker.map(ticker_map).to_numpy(int)
    feature_cube[di, ci] = rows[FEATURES].to_numpy(np.float32)
    adv[di, ci] = rows.avg_dollar_volume_20d.to_numpy(float)
    present[di, ci] = True
    eligible[di, ci] = rows.new_buy_eligible.to_numpy(bool)
    opening = px.pivot(index="trade_date", columns="ticker", values="open").reindex(index=dates, columns=tickers).to_numpy(float)
    closing = px.pivot(index="trade_date", columns="ticker", values="close").reindex(index=dates, columns=tickers).to_numpy(float)
    signal_mask = present.any(axis=1)
    if len(signal_mask) >= 2:
        signal_mask[-2:] = False
    market = MarketArrays(dates=dates, tickers=tickers, open=opening, close=closing,
                          adv=adv, input_present=present, new_buy_eligible=eligible,
                          signal_mask=signal_mask)
    evidence = dict(cutoff_exclusive=str(cutoff.date()), normalization_rows=len(rows),
                    normalization_signal_max=str(rows.signal_date.max().date()),
                    normalization_label_end_max=str(rows.label_end_date.max().date()),
                    price_max=str(px.trade_date.max().date()), signal_days=int(signal_mask.sum()),
                    first_signal=str(dates[np.flatnonzero(signal_mask)[0]].date()),
                    last_signal=str(dates[np.flatnonzero(signal_mask)[-1]].date()),
                    reward_end_max=str(dates[np.flatnonzero(signal_mask)[-1]+2].date()))
    return market, feature_cube, mean, scale, evidence


class EpisodePolicy:
    def __init__(self, actor, critic, feature_cube, mean, scale, noise_seed):
        self.actor, self.critic = actor, critic
        self.feature_cube, self.mean, self.scale = feature_cube, mean, scale
        self.generator = torch.Generator().manual_seed(noise_seed)
        self.experiences = []

    def __call__(self, signal_index, context):
        if len(context.path_ids) != 1:
            raise ValueError("ONE_INDEPENDENT_TRAINING_ACCOUNT_REQUIRED")
        ids, obs, upper, budget, slots, explicit = observable_state(context, self.feature_cube[signal_index], 0, self.mean, self.scale)
        weights = np.zeros_like(context.current_weights)
        if len(ids):
            with torch.no_grad():
                location = self.actor(obs)
                latent = location + SPEC["gaussian_logit_sd"] * torch.randn(location.shape, generator=self.generator)
                log_probability = torch.distributions.Normal(location, SPEC["gaussian_logit_sd"]).log_prob(latent).sum()
                old_value = self.critic(obs) if self.critic is not None else torch.tensor(0.)
            weights[0, ids] = project_logits(latent.numpy(), upper, budget, slots, context.tickers[ids])
            self.experiences.append(dict(signal_index=signal_index, signal_date=context.signal_date,
                                         observations=obs, latent=latent, old_log_probability=log_probability,
                                         old_value=old_value, decision_cash=float(context.cash[0]),
                                         current_units=context.current_units[0].copy(),
                                         target_weight_sum=float(weights.sum()), target_names=int((weights > 0).sum())))
        return TargetDecision(weights, explicit[None, :], raw_evidence_id=f"rl_train|{signal_index}")


def collect_episode(actor, critic, market, features, mean, scale, noise_seed):
    policy = EpisodePolicy(actor, critic, features, mean, scale, noise_seed)
    daily = {}

    def callback(name, frame):
        if name == "daily":
            row = frame.iloc[0]
            daily[pd.Timestamp(row.date)] = {k: row[k] for k in ["pretrade_nav", "cash", "nav", "actual_name_count", "transaction_cost_amount", "stale_count", "unknown_count"]}

    result = run_many(market, ["training"], policy, initial_cash=SPEC["initial_cash"],
                      cost_bps=SPEC["cost_bps"], max_weight=SPEC["max_weight"],
                      max_positions=SPEC["max_positions"], max_invested=SPEC["max_invested"],
                      capacity_fraction=SPEC["capacity_fraction"], collect_ledgers=False,
                      ledger_callback=callback)
    records = []
    for experience in policy.experiences:
        i = experience["signal_index"]
        entry_date, end_date = market.dates[i+1], market.dates[i+2]
        entry = float(daily[entry_date]["pretrade_nav"])
        ending = float(daily[end_date]["pretrade_nav"])
        if not np.isfinite(entry) or not np.isfinite(ending) or min(entry, ending) <= 0:
            raise ValueError("UNKNOWN_ACCOUNT_REWARD_REJECTED")
        experience["reward"] = float(np.log(ending / entry))
        experience["reward_end_date"] = end_date
        records.append(dict(signal_date=experience["signal_date"], execution_date=entry_date,
                            reward_end_date=end_date, reward=experience["reward"],
                            pre_execution_nav=entry, next_open_nav=ending,
                            decision_cash=experience["decision_cash"],
                            target_names=experience["target_names"], target_weight_sum=experience["target_weight_sum"],
                            actual_names=int(daily[entry_date]["actual_name_count"]),
                            actual_cash=float(daily[entry_date]["cash"]),
                            fees=float(daily[entry_date]["transaction_cost_amount"])))
    return policy.experiences, records, result.audit


def discounted_returns(rewards):
    result = np.zeros(len(rewards), dtype=np.float32)
    future = 0.0
    for i in range(len(rewards)-1, -1, -1):
        future = float(rewards[i]) + SPEC["gamma"] * future
        result[i] = future
    return torch.tensor(result)


def log_probabilities(actor, experiences):
    counts = [len(e["latent"]) for e in experiences]
    observations = torch.cat([e["observations"] for e in experiences])
    latent = torch.cat([e["latent"] for e in experiences])
    logp = torch.distributions.Normal(actor(observations), SPEC["gaussian_logit_sd"]).log_prob(latent)
    return torch.stack([block.sum() for block in torch.split(logp, counts)])


def clipped_policy_loss(new_logp, old_logp, advantages):
    ratio = torch.exp(torch.clamp(new_logp-old_logp, -SPEC["ppo_ratio_numerical_log_cap"], SPEC["ppo_ratio_numerical_log_cap"]))
    plain = ratio * advantages
    clipped = torch.clamp(ratio, 1-SPEC["ppo_clip"], 1+SPEC["ppo_clip"]) * advantages
    return -torch.minimum(plain, clipped).mean(), ratio


def update_policy(method, actor, critic, optimizer, experiences):
    if not experiences:
        raise ValueError("EMPTY_RL_TRAJECTORY")
    returns = discounted_returns([e["reward"] for e in experiences])
    old_values = torch.stack([e["old_value"] for e in experiences]).detach()
    advantage = returns if method == "reinforce" else returns-old_values
    advantage = (advantage-advantage.mean()) / advantage.std(unbiased=False).clamp_min(1e-6)
    logs = []
    size = len(experiences) if method == "reinforce" else SPEC["ppo_chronological_minibatch_steps"]
    for start in range(0, len(experiences), size):
        block = experiences[start:start+size]
        new_logp = log_probabilities(actor, block)
        adv = advantage[start:start+len(block)]
        critic_loss = torch.tensor(0.)
        clipped_count = 0
        if method == "reinforce":
            policy_loss = -(new_logp * adv).mean()
        elif method == "ppo":
            old_logp = torch.stack([e["old_log_probability"] for e in block])
            policy_loss, ratio = clipped_policy_loss(new_logp, old_logp, adv)
            values = torch.stack([critic(e["observations"]) for e in block])
            critic_loss = (values-returns[start:start+len(block)]).square().mean()
            clipped_count = int(((ratio < 1-SPEC["ppo_clip"]) | (ratio > 1+SPEC["ppo_clip"])).sum())
        else:
            raise ValueError("UNDECLARED_RL_METHOD")
        loss = policy_loss + SPEC["ppo_critic_coefficient"] * critic_loss
        if not torch.isfinite(loss):
            raise ValueError("NONFINITE_RL_LOSS")
        optimizer.zero_grad()
        loss.backward()
        parameters = list(actor.parameters()) + (list(critic.parameters()) if critic is not None else [])
        gradient = torch.nn.utils.clip_grad_norm_(parameters, SPEC["gradient_norm_cap"])
        if not torch.isfinite(gradient):
            raise ValueError("NONFINITE_RL_GRADIENT")
        optimizer.step()
        logs.append(dict(loss=float(loss.detach()), policy_loss=float(policy_loss.detach()),
                         critic_loss=float(critic_loss.detach()), gradient_norm=float(gradient),
                         ppo_clipped_samples=clipped_count, batch_steps=len(block)))
    return logs


def train_one(method, market, features, mean, scale, *, epochs=10):
    torch.manual_seed(SEED)
    actor = Actor()
    initial = {k: v.detach().clone() for k, v in actor.state_dict().items()}
    initial_digest = state_digest(actor)
    critic = Critic() if method == "ppo" else None
    parameters = list(actor.parameters()) + (list(critic.parameters()) if critic is not None else [])
    optimizer = torch.optim.Adam(parameters, lr=SPEC["learning_rate"], weight_decay=SPEC["weight_decay"])
    epoch_logs, last_records = [], []
    for epoch in range(epochs):
        started = time.monotonic()
        experiences, records, audit = collect_episode(actor, critic, market, features, mean, scale, SEED+epoch)
        updates = update_policy(method, actor, critic, optimizer, experiences)
        row = dict(epoch=epoch+1, seconds=time.monotonic()-started, days=len(records),
                   actual_parameter_updates=len(updates),
                   loss_mean=float(np.mean([u["loss"] for u in updates])),
                   policy_loss_mean=float(np.mean([u["policy_loss"] for u in updates])),
                   critic_loss_mean=float(np.mean([u["critic_loss"] for u in updates])),
                   ppo_clipped_samples=sum(u["ppo_clipped_samples"] for u in updates),
                   reward_sum=float(sum(e["reward"] for e in experiences)), common_account_audit=audit)
        epoch_logs.append(row)
        last_records = records
        print(json.dumps({"method": method, **row}, ensure_ascii=False), flush=True)
    delta = float(sum((actor.state_dict()[k]-v).square().sum().item() for k, v in initial.items())**0.5)
    if delta <= 0 or not all(np.isfinite(v.detach().numpy()).all() for v in actor.state_dict().values()):
        raise ValueError("RL_NO_FINITE_ACTOR_PARAMETER_UPDATE")
    return actor, critic, initial, dict(initial_actor_digest=initial_digest, final_actor_digest=state_digest(actor),
                                      actor_parameter_delta_l2=delta, actual_parameter_updates=sum(v["actual_parameter_updates"] for v in epoch_logs),
                                      chronological_epochs=epochs, logs=epoch_logs), last_records


def train():
    if (ROOT / "FROZEN_BEFORE_2026.json").exists():
        raise RuntimeError("RL_FIT_FORBIDDEN_AFTER_BATCH_FREEZE")
    if (OUT / "RL_TRAIN_RECEIPT.json").exists():
        raise FileExistsError("RL_TRAINING_ALREADY_COMPLETED")
    torch.set_num_threads(2)
    bindings = json.loads((ROOT / "input_paths.json").read_text(encoding="utf-8"))
    pre_path, price_path = Path(bindings["pre_panel"]), Path(bindings["pre_prices"])
    contract = ROOT / "EXPERIMENT_CONTRACT.md"
    sources = {str(p): sha(p) for p in [pre_path, price_path, contract, Path(__file__), ROOT / "fast_account.py", ROOT / "input_paths.json"]}
    panel = pd.read_parquet(pre_path)
    prices = pd.read_parquet(price_path)
    OUT.mkdir(exist_ok=True)
    write_json(OUT / "RL_PRE_FIT_CONTRACT.json", dict(spec=SPEC, stages=STAGES, features=FEATURES,
               source_sha256=sources, numeric_2026_prices_read=False, old_actor_reused=False,
               created_utc=datetime.now(timezone.utc).isoformat()))
    receipts = []
    for stage, cutoff in STAGES.items():
        market, features, mean, scale, evidence = prepare_market(panel, prices, cutoff)
        np.savez(OUT / f"rl_{stage}_normalization.npz", mean=mean, scale=scale)
        for method in ["reinforce", "ppo"]:
            actor, critic, initial, metrics, records = train_one(method, market, features, mean, scale, epochs=SPEC["chronological_epochs"])
            zero_path = OUT / f"rl_{stage}_{method}_zero.pt"
            path = OUT / f"rl_{stage}_{method}.pt"
            payload = dict(actor_state=actor.state_dict(), mean=torch.tensor(mean), scale=torch.tensor(scale),
                           stage=stage, method=method, spec=SPEC, features=FEATURES,
                           critic_state=critic.state_dict() if critic is not None else None)
            zero = dict(payload, actor_state=initial, critic_state=None)
            torch.save(zero, zero_path)
            torch.save(payload, path)
            episode_path = OUT / f"rl_{stage}_{method}_last_episode.parquet"
            pd.DataFrame(records).to_parquet(episode_path, index=False)
            zero_model = Actor(); zero_model.load_state_dict(initial)
            if state_digest(zero_model) != metrics["initial_actor_digest"]:
                raise ValueError("ZERO_ACTOR_NOT_MATCHED_TO_INITIALIZATION")
            receipt = dict(stage=stage, method=method, seed=SEED, status="TRAINED", **evidence, **metrics,
                           path=str(path.resolve()), sha256=sha(path), zero_path=str(zero_path.resolve()),
                           zero_sha256=sha(zero_path), zero_actor_digest=state_digest(zero_model),
                           zero_actual_parameter_updates=0, zero_parameter_delta_l2=0.0,
                           last_episode_path=str(episode_path.resolve()), last_episode_sha256=sha(episode_path),
                           source_sha256=sources, numeric_2026_prices_read=False)
            write_json(OUT / f"rl_{stage}_{method}_receipt.json", receipt)
            receipts.append(receipt)
    for path, digest in sources.items():
        if sha(path) != digest:
            raise RuntimeError(f"RL_SOURCE_CHANGED_DURING_FIT:{path}")
    write_json(OUT / "RL_TRAIN_RECEIPT.json", dict(status="COMPLETE", spec=SPEC, fits=receipts,
               actual_fit_count=4, zero_control_count=4, old_actor_reused=False, fit_2026_rows=0,
               numeric_2026_prices_read=False, source_sha256_unchanged=True,
               limitations=["Research affine index coordinate and previously exposed holdout.",
                            "Stochastic latent target projections and hard TOP20; no differentiable execution assumption.",
                            "REINFORCE has one full-trajectory gradient per episode; PPO has one fixed chronological minibatch pass per episode, so update counts differ.",
                            "No candidate, epoch, seed, reward or policy-threshold search."]))


class RLRuntime:
    """Frozen policy API for one or multiple common AccountContext accounts.

    ``runtime(signal_index, context, feature_matrix) -> TargetDecision``.
    Alternatively supply a [D,N,32] feature cube to the constructor and use it
    directly as the common engine's two-argument policy callback.
    """
    def __init__(self, stage="final", feature_cube=None, model_dir=OUT):
        if stage not in STAGES:
            raise ValueError("UNDECLARED_RL_STAGE")
        self.stage, self.feature_cube = stage, feature_cube
        self.models = {}
        for method in ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]:
            path = Path(model_dir) / f"rl_{stage}_{method}.pt"
            payload = torch.load(path, map_location="cpu", weights_only=True)
            actor = Actor(); actor.load_state_dict(payload["actor_state"]); actor.eval()
            self.models[method] = (actor, payload["mean"].numpy(), payload["scale"].numpy())

    def __call__(self, signal_index, context, features=None):
        if features is None:
            if self.feature_cube is None:
                raise ValueError("RL_RUNTIME_REQUIRES_SIGNAL_FEATURES")
            features = self.feature_cube[signal_index]
        weights = np.zeros_like(context.current_weights)
        explicit_mask = np.zeros_like(context.decision_mask)
        for row, path_id in enumerate(context.path_ids):
            method = path_id.removeprefix("rl_")
            if method not in self.models:
                raise ValueError(f"UNDECLARED_RL_PATH:{path_id}")
            if not np.isfinite(context.nav[row]) or context.nav[row] <= 0 or not np.isfinite(context.cash_weight[row]):
                # Common execution reserves this account; another healthy row
                # must remain independently callable in the same batch.
                continue
            actor, mean, scale = self.models[method]
            ids, observations, upper, budget, slots, explicit = observable_state(context, features, row, mean, scale)
            explicit_mask[row] = explicit
            if len(ids):
                with torch.no_grad():
                    logits = actor(observations).numpy()
                weights[row, ids] = project_logits(logits, upper, budget, slots, context.tickers[ids])
        return TargetDecision(weights, explicit_mask, raw_evidence_id=f"rl_frozen|{self.stage}|{signal_index}")


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    train()
