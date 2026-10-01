"""Stateful action and bounded sequential challengers for the common account.

No data or model files are loaded. Callers supply PIT inputs and frozen bundles.
The retained RL mathematics is source-bound; the account is never reimplemented.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from dataclasses import replace

from scripts.research.a2.evaluation.continuous_research_account import (
    PersistentPolicyContext, run_continuous_account,
)
from scripts.research.a2.inference.joint_portfolio_policy import (
    EPS, InfeasiblePolicy, _support_projection,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

SPEC = dict(seed=20260928, epochs=4, learning_rate=.001, weight_decay=.0001,
            gaussian_logit_sd=.2, gamma=.99, ppo_clip=.2,
            ppo_ratio_numerical_log_cap=20., gradient_norm_cap=2.,
            chronological_minibatch_steps=32, ppo_critic_coefficient=.5,
            max_optimizer_updates_all_algorithms_and_folds=2048,
            market_features=32, state_features=8, opportunity_scale=.01,
            first_signal="2021-01-01", no_trade_band=.0025,
            minimum_trade_usd=1., hysteresis_uncertainty_multiple=.5)
_RL_SOURCE = Path(__file__).parents[1] / "retained/a2_pto_full_compat_20260928_r2/rl_control.py"
_RL_SHA = "261b9b69ff37a2d00ee3564d488148f3acc0d34c19a0ebf476b7f0dc69a1e273"



TRAINING_PROJECTION = dict(
    source="scripts/research/a2/evaluation/continuous_research_account.py",
    source_sha256="99038f036431c91b1070fe52d5bdbbd057c617356a8b839c295c6c4bf0742d00",
    single_ast_delta="market.dates[0] < Timestamp(2023-01-01) -> Timestamp(2021-01-01)",
    scope="caller-authorized pre-cutoff training only; account engine, CA, 2026 gate unchanged")


def _training_account(*args, **kwargs):
    """Project only the old task's initial-session floor, preserving all gates."""
    from scripts.research.a2.evaluation import continuous_research_account as common
    raw = Path(common.__file__).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRAINING_PROJECTION["source_sha256"]:
        raise ValueError("FROZEN_CONTINUOUS_ADAPTER_CHANGED")
    node = next(n for n in ast.parse(raw.decode("utf-8-sig")).body
                if isinstance(n,ast.FunctionDef) and n.name=="run_continuous_account")
    changed = 0
    for part in ast.walk(node):
        if (isinstance(part,ast.If) and isinstance(part.test,ast.Compare)
            and ast.unparse(part.test.left)=="market.dates[0]"
            and len(part.test.ops)==1 and isinstance(part.test.ops[0],ast.Lt)
            and len(part.test.comparators)==1
            and ast.unparse(part.test.comparators[0])=="pd.Timestamp('2023-01-01')"):
            part.test.comparators[0].args[0].value = SPEC["first_signal"]
            changed += 1
    if changed != 1:
        raise ValueError("INITIAL_SESSION_PROJECTION_NOT_EXACTLY_ONE")
    namespace = dict(common.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 str(common.__file__),"exec"),namespace)
    return namespace["run_continuous_account"](*args,**kwargs)


def _primitives():
    """Load selected pure definitions, excluding every old runner/global path."""
    import torch
    from torch import nn
    raw = _RL_SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _RL_SHA:
        raise ValueError("FROZEN_RL_MATHEMATICS_CHANGED")
    names = {"Actor", "Critic", "state_digest", "clipped_policy_loss"}
    nodes = [n for n in ast.parse(raw.decode("utf-8-sig")).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if {n.name for n in nodes} != names:
        raise ValueError("RL_PRIMITIVE_MISSING")
    namespace = dict(torch=torch, nn=nn, hashlib=hashlib, SPEC=SPEC)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(_RL_SOURCE), "exec"), namespace)
    return namespace


def SequentialActor():
    """Two independent readouts: relative composition and total exposure."""
    p = _primitives()
    torch, nn = p["torch"], p["nn"]

    class Actor(nn.Module):
        def __init__(self):
            super().__init__()
            self.composition = p["Actor"]()
            self.gross = p["Actor"]()
            self.composition.net[0] = nn.Linear(40, 32)
            self.gross.net[0] = nn.Linear(40, 32)

        def forward(self, x):
            return self.composition(x), self.gross(x).mean().reshape(1)
    return Actor()


def _critic():
    p = _primitives()
    model = p["Critic"]()
    model.net[0] = p["nn"].Linear(40, 32)
    return model


def _valid_inputs(features, mu, uncertainty):
    return np.isfinite(features).all(axis=1) & np.isfinite(mu) & np.isfinite(uncertainty) & (uncertainty >= 0)


def observable_state(ctx, row, features, mu, uncertainty, mean, scale, capital):
    """Signal-only state; entry P/L comes from current marked account value."""
    features, mu, uncertainty = np.asarray(features), np.asarray(mu), np.asarray(uncertainty)
    if features.shape != (len(ctx.tickers), 32) or mu.shape != (len(ctx.tickers),) or uncertainty.shape != mu.shape:
        raise ValueError("SEQUENTIAL_INPUT_SHAPE")
    usable = _valid_inputs(features, mu, uncertainty)
    held = ctx.current_units[row] > EPS
    explicit = ctx.decision_mask[row] & usable
    reserved = ctx.reserved_mask[row] | (held & ~explicit & ~ctx.operational_mask[row])
    current = np.asarray(ctx.current_weights[row], float)
    if not np.isfinite(current).all() or not np.isfinite(ctx.nav[row]) or ctx.nav[row] <= 0:
        return np.array([], int), None, explicit & False, reserved, np.zeros(len(current))
    ids = np.flatnonzero(explicit & ~reserved & (ctx.buy_allowed[row] | held))
    upper = np.where(ctx.buy_allowed[row], ctx.max_weight, np.minimum(current, ctx.max_weight))
    upper[reserved | ~explicit] = 0.
    if not len(ids):
        return ids, None, explicit, reserved, upper
    age = np.asarray(ctx.holding_age[row], float) if hasattr(ctx, "holding_age") else np.zeros(len(current))
    entry = np.asarray(ctx.entry_price[row], float) if hasattr(ctx, "entry_price") else np.full(len(current), np.nan)
    mark = np.divide(current * ctx.nav[row], ctx.current_units[row],
                     out=np.full(len(current), np.nan), where=held)
    pnl = np.divide(mark, entry, out=np.ones(len(current)), where=held & np.isfinite(entry) & (entry > 0)) - 1
    states = np.column_stack([
        mu[ids] / SPEC["opportunity_scale"], uncertainty[ids] / SPEC["opportunity_scale"],
        current[ids], np.full(len(ids), ctx.cash_weight[row]),
        np.maximum(age[ids], 0) / 252., np.clip(pnl[ids], -5, 5),
        np.full(len(ids), np.log(ctx.nav[row] / capital)), held[ids].astype(float),
    ])
    obs = np.column_stack([np.clip((features[ids]-mean)/scale, -8, 8), np.clip(states, -8, 8)]).astype(np.float32)
    if not np.isfinite(obs).all():
        raise ValueError("NONFINITE_OBSERVABLE_ACCOUNT_STATE")
    return ids, obs, explicit, reserved, upper


class RuleStatefulPolicy:
    """PTO action gate before joint risk/q/G, with an execution no-trade gate.

    The base policy remains the single joint optimizer. This gate is a declared
    rule, not a trained action model. It preserves exact units for close calls.
    """
    def __init__(self, base_policy, opportunity=None, uncertainty=None, *,
                 no_trade_band=SPEC["no_trade_band"], minimum_trade_usd=SPEC["minimum_trade_usd"],
                 hysteresis=SPEC["hysteresis_uncertainty_multiple"], on_diagnostics=None):
        self.base = base_policy
        self.mu = np.asarray(opportunity if opportunity is not None else base_policy.mu)
        self.uncertainty = np.asarray(uncertainty if uncertainty is not None else base_policy.uncertainty)
        self.band, self.minimum, self.hysteresis = float(no_trade_band), float(minimum_trade_usd), float(hysteresis)
        if min(self.band, self.minimum, self.hysteresis) < 0:
            raise ValueError("NEGATIVE_ACTION_GATE")
        self.callback = on_diagnostics

    def __call__(self, day, ctx):
        reserved = ctx.reserved_mask.copy()
        held = ctx.current_units > EPS
        for r in range(len(ctx.path_ids)):
            mu, uncertainty = self.mu[day, r], self.uncertainty[day, r]
            known = np.isfinite(mu) & np.isfinite(uncertainty) & (uncertainty >= 0)
            candidate = ctx.decision_mask[r] & known & (ctx.buy_allowed[r] | held[r])
            scores = np.sort(mu[candidate])[::-1]
            cutoff = scores[min(ctx.max_positions, len(scores))-1] if len(scores) else np.inf
            hold = held[r] & candidate & (mu >= cutoff-self.hysteresis*uncertainty)
            hold &= ctx.current_weights[r] <= ctx.max_weight+EPS
            reserved[r] |= hold & ~ctx.operational_mask[r]
        common = ctx.common if isinstance(ctx, PersistentPolicyContext) else ctx
        weight = np.where(reserved, ctx.current_weights, 0.).sum(axis=1)
        gated = replace(common, reserved_mask=reserved, reserved_weight=weight,
                        reserved_slots=reserved.sum(axis=1),
                        available_budget=np.maximum(0, ctx.max_invested-weight),
                        available_slots=np.maximum(0, ctx.max_positions-reserved.sum(axis=1)),
                        decision_mask=ctx.decision_mask & ~reserved)
        if isinstance(ctx, PersistentPolicyContext):
            gated = replace(ctx, common=gated)
        decision = self.base(day, gated)
        target = decision.weights.copy()
        explicit = decision.explicit_mask.copy()
        delta = target-ctx.current_weights
        tiny = explicit & ((np.abs(delta) < self.band) | (np.abs(delta)*ctx.nav[:, None] < self.minimum))
        explicit[tiny & held] = False
        target[tiny] = 0.
        if self.callback is not None:
            rows = []
            for r, path in enumerate(ctx.path_ids):
                for c in np.flatnonzero(held[r] | (target[r] > EPS)):
                    action = ("HOLD" if not explicit[r,c] else "SELL" if target[r,c] <= EPS
                              else "BUY" if not held[r,c] else "REDUCE" if delta[r,c] < -EPS
                              else "ADD" if delta[r,c] > EPS else "HOLD")
                    rows.append(dict(path_id=path, signal_date=ctx.signal_date, ticker=str(ctx.tickers[c]),
                                     action=action, current_weight=float(ctx.current_weights[r,c]),
                                     target_weight=float(target[r,c] if explicit[r,c] else ctx.current_weights[r,c]), explicit_model_decision=bool(explicit[r,c]),
                                     rule_action=True))
            self.callback(pd.DataFrame(rows))
        return TargetDecision(target, explicit, "V24_RULE_STATEFUL")


class SequentialPolicy:
    """Frozen or sampled DirectSequential policy over the existing account API."""
    def __init__(self, bundle, features, opportunity, uncertainty, *, sampled=False,
                 noise_seed=20260928, capture=False, on_diagnostics=None):
        p = _primitives()
        self.torch = p["torch"]
        self.actor = SequentialActor()
        self.actor.load_state_dict(bundle["actor_state"])
        self.actor.eval()
        self.mean, self.scale = np.asarray(bundle["mean"]), np.asarray(bundle["scale"])
        self.capital = float(bundle["capital"])
        self.features, self.mu, self.sigma = map(np.asarray, (features, opportunity, uncertainty))
        if self.features.ndim != 3 or self.features.shape[2] != 32 or self.mu.shape != self.features.shape[:2] or self.sigma.shape != self.mu.shape:
            raise ValueError("SEQUENTIAL_CUBE_SHAPE")
        self.sampled, self.capture, self.callback = sampled, capture, on_diagnostics
        self.generator = self.torch.Generator().manual_seed(noise_seed)
        self.experiences = []

    def __call__(self, day, ctx):
        torch = self.torch
        targets = np.zeros_like(ctx.current_weights)
        masks = np.zeros_like(ctx.decision_mask)
        for row, path in enumerate(ctx.path_ids):
            ids, obs, explicit, reserved, upper = observable_state(
                ctx, row, self.features[day], self.mu[day], self.sigma[day],
                self.mean, self.scale, self.capital)
            record = dict(path_id=path, signal_index=day, signal_date=ctx.signal_date,
                          observations=obs, latent=None, old_logprob=0., old_value=0.,
                          current_units=ctx.current_units[row].copy(), decision_cash=float(ctx.cash[row]),
                          holding_age=np.asarray(ctx.holding_age[row]).copy() if hasattr(ctx,"holding_age") else None,
                          entry_execution_open=np.asarray(ctx.entry_execution_open[row]).copy() if hasattr(ctx,"entry_execution_open") else None,
                          modeled_tickers=ctx.tickers[ids].tolist())
            if len(ids):
                with torch.no_grad():
                    location = torch.cat(self.actor(torch.from_numpy(obs)))
                    latent = location + SPEC["gaussian_logit_sd"] * torch.randn(location.shape, generator=self.generator) if self.sampled else location
                    logp = torch.distributions.Normal(location, SPEC["gaussian_logit_sd"]).log_prob(latent).sum()
                scores = np.zeros(len(ctx.tickers))
                scores[ids] = 1/(1+np.exp(-np.clip(latent[:-1].numpy(), -30, 30)))
                held_mass = float(np.where(reserved, ctx.current_weights[row], 0.).sum())
                slots = ctx.max_positions-int(reserved.sum())
                gross_head = float(1/(1+np.exp(-np.clip(float(latent[-1]), -30, 30))))
                requested = held_mass+(ctx.max_invested-held_mass)*gross_head
                capacity = np.sort(upper[ids])[-max(0, slots):].sum() if slots > 0 else 0.
                gross = min(requested, held_mass+float(capacity))
                try:
                    ranks = np.argsort(np.argsort(ctx.tickers, kind="stable"), kind="stable")
                    targets[row] = _support_projection(scores, upper, max(0., gross-held_mass), slots, ranks)
                    masks[row] = explicit & ~reserved
                    total = targets[row]+np.where(reserved, ctx.current_weights[row], 0.)
                    composition = total/gross if gross > EPS else np.zeros_like(total)
                    if gross > EPS and not np.isclose(composition.sum(), 1., atol=1e-8):
                        raise InfeasiblePolicy("SEQUENTIAL_Q_MASS")
                    record.update(gross_requested=requested, gross_target=gross, q=composition,
                                  old_logprob=float(logp), latent=latent.clone(), status="TARGET_COMPLETE")
                except InfeasiblePolicy as exc:
                    record.update(status="FALLBACK_PRESERVE_UNITS", reason=str(exc))
            else:
                record.update(status="NO_POLICY_INPUT_PRESERVE_UNITS", gross_target=np.nan)
            if self.capture:
                self.experiences.append(record)
            if self.callback is not None:
                self.callback(record)
        return TargetDecision(targets, masks, "V24_DIRECT_SEQUENTIAL")


def _returns(rewards, valid):
    out = np.zeros(len(rewards), np.float32)
    future = 0.
    for i in range(len(rewards)-1, -1, -1):
        future = float(rewards[i])+SPEC["gamma"]*future if valid[i] else 0.
        out[i] = future
    return out


def _reward_rows(replay, records, dates, cutoff):
    rows = []
    daily = replay.daily.set_index(["path_id", "date"])
    for record in records:
        i = record["signal_index"]
        valid, reason, reward = False, "NO_POLICY_INPUT", 0.
        execution = endpoint = pd.NaT
        if i+2 < len(dates):
            execution, endpoint = dates[i+1], dates[i+2]
            if not record["signal_date"] < execution < endpoint < cutoff:
                reason = "UNMATURED_REWARD_ENDPOINT"
            elif record["latent"] is not None:
                first, last = daily.loc[(record["path_id"],execution)], daily.loc[(record["path_id"],endpoint)]
                nav = np.array([first.pretrade_nav, last.pretrade_nav],float)
                quality = all(bool(x.accounting_qualified) and x.open_stale_count == 0 and x.open_unknown_count == 0 for x in (first,last))
                valid = quality and np.isfinite(nav).all() and (nav > 0).all()
                reason = "AVAILABLE" if valid else "UNKNOWN_STALE_OR_UNQUALIFIED_ACCOUNT_REWARD"
                reward = float(np.log(nav[1]/nav[0])) if valid else 0.
        rows.append(dict(signal_date=record["signal_date"], execution_date=execution,
                         reward_end_date=endpoint, valid_learning_reward=bool(valid),
                         log_net_reward=reward, mask_reason=reason))
    return pd.DataFrame(rows)


def train_sequential(method, market, feature_cube, opportunity, uncertainty, account_config, *,
                     cutoff, replay_kwargs=None, epochs=4, seed=20260928, max_optimizer_updates=2048):
    """One configuration/seed; full legal trajectories, no date/security sampling.

    The supplied market and OOF forecasts must already satisfy their PIT lineage.
    This function enforces physical pre-cutoff bounds and reward maturity too.
    No files are written. The caller retains failed trials and saves the bundles.
    """
    if method not in {"reinforce","ppo"} or epochs != SPEC["epochs"] or seed != SPEC["seed"]:
        raise ValueError("UNREGISTERED_SEQUENTIAL_SEARCH_BUDGET")
    if not 0 < max_optimizer_updates <= SPEC["max_optimizer_updates_all_algorithms_and_folds"]:
        raise ValueError("INVALID_SHARED_RL_UPDATE_BUDGET")
    cutoff = pd.Timestamp(cutoff)
    if cutoff > pd.Timestamp("2026-01-01") or market.dates[-1] >= cutoff or market.dates[0] < pd.Timestamp(SPEC["first_signal"]):
        raise ValueError("SEQUENTIAL_TRAINING_BOUNDARY")
    features, mu, sigma = map(np.asarray, (feature_cube, opportunity, uncertainty))
    shape = (len(market.dates),len(market.tickers))
    if features.shape != (*shape,32) or mu.shape != shape or sigma.shape != shape:
        raise ValueError("SEQUENTIAL_TRAIN_INPUT_SHAPE")
    usable = np.isfinite(features).all(axis=2) & np.isfinite(mu) & np.isfinite(sigma) & (sigma>=0) & market.input_present
    # Fit on every physically isolated legal input row; no label required to
    # decide eligibility at inference, and no fitted state from later dates.
    x = features[usable]
    if not len(x):
        return dict(status="BLOCKED_INPUT", reason="NO_LEGAL_NORMALIZATION_ROWS", method=method, spec=dict(SPEC))
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 1e-12,scale,1.)
    p = _primitives()
    torch = p["torch"]
    torch.manual_seed(seed)
    actor, critic = SequentialActor(), _critic() if method=="ppo" else None
    initial = {k:v.detach().clone() for k,v in actor.state_dict().items()}
    initial_hash = p["state_digest"](actor)
    parameters = list(actor.parameters())+(list(critic.parameters()) if critic is not None else [])
    optimizer = torch.optim.Adam(parameters,lr=SPEC["learning_rate"],weight_decay=SPEC["weight_decay"])
    zero = dict(actor_state=initial,mean=mean,scale=scale,capital=account_config["initial_nav"],
                method=method+"_zero",frozen=True,source_sha256=_RL_SHA)
    logs, reward_audits, updates = [], [], 0
    for epoch in range(epochs):
        bundle = {**zero,"actor_state":{k:v.detach().clone() for k,v in actor.state_dict().items()}}
        policy = SequentialPolicy(bundle,features,mu,sigma,sampled=True,noise_seed=seed+epoch,capture=True)
        replay = _training_account(market,["training"],policy,account_config,**(replay_kwargs or {}))
        records = policy.experiences
        rewards = _reward_rows(replay,records,market.dates,cutoff)
        valid = rewards.valid_learning_reward.to_numpy(bool) if len(rewards) else np.zeros(0,bool)
        if not valid.any():
            return dict(status="BLOCKED_REWARD",method=method,zero_bundle=zero,spec=dict(SPEC),
                        normalization_rows=len(x),actual_parameter_updates=updates,reward_audits=reward_audits+[rewards])
        returns = torch.tensor(_returns(rewards.log_net_reward.to_numpy(float),valid))
        # No stale/unknown segment can carry future credit through the mask.
        indices = np.flatnonzero(valid)
        old_values = torch.zeros(len(records))
        if critic is not None:
            with torch.no_grad():
                for i in indices:
                    old_values[i] = critic(torch.from_numpy(records[i]["observations"]))
        advantage = returns-old_values if critic is not None else returns
        active = advantage[indices]
        advantage = (advantage-active.mean())/active.std(unbiased=False).clamp_min(1e-6)
        size = len(records) if method=="reinforce" else SPEC["chronological_minibatch_steps"]
        for start in range(0,len(records),size):
            ids = [i for i in range(start,min(start+size,len(records))) if valid[i]]
            if not ids:
                continue
            new_logp, values = [], []
            for i in ids:
                obs = torch.from_numpy(records[i]["observations"])
                location = torch.cat(actor(obs))
                new_logp.append(torch.distributions.Normal(location,SPEC["gaussian_logit_sd"]).log_prob(records[i]["latent"]).sum())
                if critic is not None:
                    values.append(critic(obs))
            new = torch.stack(new_logp)
            if method=="ppo":
                old = torch.tensor([records[i]["old_logprob"] for i in ids])
                policy_loss,_ = p["clipped_policy_loss"](new,old,advantage[ids])
                value_loss = (torch.stack(values)-returns[ids]).square().mean()
            else:
                policy_loss = -(new*advantage[ids]).mean()
                value_loss = new.sum()*0
            loss = policy_loss+SPEC["ppo_critic_coefficient"]*value_loss
            if not torch.isfinite(loss):
                raise ValueError("NONFINITE_SEQUENTIAL_OBJECTIVE")
            if updates >= max_optimizer_updates:
                partial = {**zero,"method":method,"actor_state":{k:v.detach().clone() for k,v in actor.state_dict().items()}}
                return dict(status="BLOCKED_UPDATE_BUDGET",method=method,partial_bundle=partial,
                            zero_bundle=zero,actual_parameter_updates=updates,spec=dict(SPEC),
                            reward_audits=reward_audits+[rewards],logs=logs)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            gradient = torch.nn.utils.clip_grad_norm_(parameters,SPEC["gradient_norm_cap"])
            if not torch.isfinite(gradient):
                raise ValueError("NONFINITE_SEQUENTIAL_GRADIENT")
            optimizer.step()
            updates += 1
        logs.append(dict(epoch=epoch+1,trajectory_signal_steps=len(records),legal_reward_steps=int(valid.sum()),
                         masked_reward_steps=int((~valid).sum()),optimizer_updates_cumulative=updates))
        reward_audits.append(rewards)
    delta = float(sum((actor.state_dict()[k]-v).square().sum().item() for k,v in initial.items())**.5)
    trained = {**zero,"method":method,"actor_state":{k:v.detach().clone() for k,v in actor.state_dict().items()},
               "critic_state":None if critic is None else critic.state_dict(),"cutoff":str(cutoff.date())}
    return dict(status="FIT_COMPLETE" if delta > 0 else "FIT_NO_POLICY_SIGNAL",method=method,
                trained_bundle=trained,zero_bundle=zero,spec=dict(SPEC),normalization_rows=len(x),
                normalization_signal_max=str(market.dates[np.where(usable.any(axis=1))[0][-1]].date()),
                initial_actor_sha256=initial_hash,final_actor_sha256=p["state_digest"](actor),
                actor_parameter_delta_l2=delta,actual_parameter_updates=updates,logs=logs,
                reward_audits=reward_audits,fit_2026_rows=0,source_sha256=_RL_SHA,
                training_projection=dict(TRAINING_PROJECTION))

