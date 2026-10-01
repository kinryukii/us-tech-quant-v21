"""Three fixed nested REINFORCE chains on the corrected E5 close/open clock."""
from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch

import ledger
from rl_core import (FEATURES, MAX_EXPOSURE, MAX_NAMES, Policy, build_days,
                     policy_target)
from safe_inputs import guarded_parquet, sha

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "rl_artifacts"
SEEDS = (20260925, 20260926)
CHECKPOINTS = (1, 8, 16, 24)
LENGTH = 120
LR = .001
GAMMA = .99
TIE_TOL = 1e-8
CUTOFF = pd.Timestamp("2026-01-01")
CHAINS = (
    ("A", "2023-01-01", "2024-01-01", "2025-01-01"),
    ("B", "2024-01-01", "2025-01-01", "2026-01-01"),
    ("C", "2025-01-01", "2026-01-01", None),
)


def normalization(panel: pd.DataFrame, stop: pd.Timestamp):
    x = panel.loc[panel.signal_date.lt(stop), FEATURES].to_numpy(float)
    if len(x) == 0:
        raise RuntimeError("EMPTY_RL_TRAINING_PREFIX")
    mean = np.nanmean(x, axis=0)
    scale = np.nanstd(x, axis=0)
    scale[~np.isfinite(scale) | (scale < 1e-8)] = 1.
    return mean, scale


def eligible_days(panel: pd.DataFrame, prices: pd.DataFrame, start, stop):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    following = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    start, stop = pd.Timestamp(start), pd.Timestamp(stop)
    dates = [pd.Timestamp(d) for d in sorted(panel.signal_date.unique())
             if start <= d < stop and d in following and following[d] < stop]
    if not dates:
        raise RuntimeError(f"NO_COMPLETE_RL_DATES:{start}:{stop}")
    return dates, {following[d]: d for d in dates}


def evaluate_one(policy, days, dates, prices, label, training=False):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    following = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    executions = [following[d] for d in dates]
    if max(executions) >= CUTOFF:
        raise RuntimeError("RL_REWARD_CROSSES_2026")
    signals = dict(zip(executions, dates))
    log_probs, actions = [], []

    def callback(signal, shares, values, nav):
        before = len(actions)
        result = policy_target(policy, days[signal], shares, values, nav,
                               training, log_probs, actions)
        for row in actions[before:]:
            row["signal_date"] = signal
        return result

    visible_prices = prices.loc[prices.trade_date.le(max(executions))]
    result = ledger.replay(label, callback, visible_prices, executions, signals)
    nav = result.daily.nav.to_numpy(float)
    rewards = np.log(nav / np.r_[1., nav[:-1]])
    if len(rewards) != len(dates) or (training and len(log_probs) != len(dates)):
        raise RuntimeError("RL_REWARD_ALIGNMENT")
    return result, rewards, log_probs, pd.DataFrame(actions)


def evaluate_ensemble(models, days, dates, prices, label):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    following = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    executions = [following[d] for d in dates]
    if max(executions) >= CUTOFF:
        raise RuntimeError("RL_ENSEMBLE_CROSSES_2026")
    signals = dict(zip(executions, dates))
    target_rows = []

    def callback(signal, shares, values, nav):
        targets = [policy_target(model, days[signal], shares, values, nav, False)
                   for model in models]
        names = set().union(*(set(t) for t in targets))
        combined = {t: float(sum(p.get(t, 0.) for p in targets) / len(targets)) for t in names}
        if len(combined) > MAX_NAMES:
            keep = set(sorted(combined, key=lambda t: (-combined[t], t))[:MAX_NAMES])
            combined = {t: w for t, w in combined.items() if t in keep}
        if sum(combined.values()) > MAX_EXPOSURE + 1e-6:
            raise RuntimeError("RL_TARGET_EXPOSURE")
        for t in sorted(set(shares) | names):
            target_rows.append({"signal_date": signal, "ticker": t,
                                "shares_before": float(shares.get(t, 0.)),
                                "weight_before": float(values.get(t, 0.) / nav),
                                "target_weight": float(combined.get(t, 0.))})
        return combined

    with torch.no_grad():
        visible_prices = prices.loc[prices.trade_date.le(max(executions))]
        result = ledger.replay(label, callback, visible_prices, executions, signals)
    return result, pd.DataFrame(target_rows)


def initialized(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    return Policy(len(FEATURES) + 4)


def update_path(seed, days, train_dates, prices, max_updates, label):
    policy = initialized(seed)
    optimizer = torch.optim.Adam(policy.parameters(), lr=LR)
    rng = np.random.default_rng(seed)
    history = []
    checkpoints = {0: {k: v.detach().clone() for k, v in policy.state_dict().items()}}
    if len(train_dates) <= LENGTH + 1:
        raise RuntimeError("RL_INSUFFICIENT_EPISODE_DATES")
    for episode in range(1, max_updates + 1):
        first = int(rng.integers(0, len(train_dates) - LENGTH - 1))
        subset = train_dates[first:first + LENGTH]
        policy.train()
        result, rewards, log_probs, _ = evaluate_one(policy, days, subset, prices,
                                                      f"{label}_{seed}_{episode}", True)
        returns = np.empty_like(rewards)
        future = 0.
        for i in range(len(rewards) - 1, -1, -1):
            future = rewards[i] + GAMMA * future
            returns[i] = future
        advantage = (returns - returns.mean()) / (returns.std() + 1e-6)
        loss = -torch.stack([p * float(a) for p, a in zip(log_probs, advantage)]).mean()
        optimizer.zero_grad()
        loss.backward()
        grad = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), 2.))
        optimizer.step()
        history.append({"chain": label, "seed": seed, "episode": episode,
                        "train_start": str(subset[0].date()), "train_last_signal": str(subset[-1].date()),
                        "environment_steps": len(rewards), "parameter_updates": episode,
                        "loss": float(loss.detach()), "gradient_norm": grad,
                        "train_log_nav": float(rewards.sum()),
                        "train_last_nav": float(result.daily.nav.iloc[-1])})
        with (OUT / "updates.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(history[-1], default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if episode in CHECKPOINTS:
            checkpoints[episode] = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    return checkpoints, history


def model_at(state):
    model = Policy(len(FEATURES) + 4)
    model.load_state_dict(state)
    model.eval()
    return model


def run():
    if os.environ.get("R1_VERIFIED_ISOLATION") != "1":
        raise RuntimeError("ISOLATED_RUNTIME_REQUIRED")
    if OUT.exists():
        raise RuntimeError("RL_ARTIFACTS_ALREADY_EXIST")
    torch.set_num_threads(1)
    manifest = json.loads((ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    if sha(ROOT / "data" / "panel.parquet") != manifest["panel_sha256"]:
        raise RuntimeError("RL_PANEL_HASH")
    panel = guarded_parquet(ROOT / "data" / "panel.parquet", "signal_date")
    prices = guarded_parquet(ROOT / "data" / "prices.parquet", "trade_date")
    if panel.duplicated(["signal_date", "ticker"]).any() or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("RL_PANEL_IDENTITY")
    OUT.mkdir()
    rows, decisions = [], []
    total_updates = 0
    for name, select_train_stop, valid_stop, outer_stop in CHAINS:
        select_train_stop = pd.Timestamp(select_train_stop)
        valid_stop = pd.Timestamp(valid_stop)
        mean, scale = normalization(panel, select_train_stop)
        days = build_days(panel, mean, scale)
        train_dates, _ = eligible_days(panel, prices, "2021-01-01", select_train_stop)
        valid_dates, _ = eligible_days(panel, prices, select_train_stop, valid_stop)
        generated = {}
        zero_models = []
        for seed in SEEDS:
            checkpoints, history = update_path(seed, days, train_dates, prices, 24, f"{name}_SELECT")
            generated[seed] = checkpoints
            zero_models.append(model_at(checkpoints[0]))
            rows.extend(history)
            total_updates += 24
        zero, _ = evaluate_ensemble(zero_models, days, valid_dates, prices, f"{name}_ZERO_VALID")
        candidates = []
        for episode in CHECKPOINTS:
            models = [model_at(generated[seed][episode]) for seed in SEEDS]
            result, _ = evaluate_ensemble(models, days, valid_dates, prices,
                                          f"{name}_ENSEMBLE_VALID_{episode}")
            log_nav = float(np.log(result.daily.nav.iloc[-1]))
            candidates.append((episode, log_nav))
            rows.append({"chain": name, "phase": "ensemble_validation", "episode": episode,
                         "validation_last_signal": str(valid_dates[-1].date()),
                         "validation_last_nav": float(result.daily.nav.iloc[-1]),
                         "validation_log_nav": log_nav})
        best = max(score for _, score in candidates)
        chosen = min(k for k, score in candidates if best - score <= TIE_TOL)
        decisions.append({"chain": name, "selected_episode": chosen,
                          "selection_object": "two-seed target-mean ensemble on one account",
                          "validation_zero_update_nav": float(zero.daily.nav.iloc[-1]),
                          "validation_candidates": candidates, "tie_tolerance_log_nav": TIE_TOL})
        expanded_mean, expanded_scale = normalization(panel, valid_stop)
        expanded_days = build_days(panel, expanded_mean, expanded_scale)
        expanded_dates, _ = eligible_days(panel, prices, "2021-01-01", valid_stop)
        final_models, expanded_zero = [], []
        for seed in SEEDS:
            checkpoints, history = update_path(seed, expanded_days, expanded_dates,
                                               prices, chosen, f"{name}_EXPANDED")
            rows.extend(history)
            total_updates += chosen
            final_models.append(model_at(checkpoints[chosen]))
            expanded_zero.append(model_at(checkpoints[0]))
            for label, model in (("selected", final_models[-1]), ("zero", expanded_zero[-1])):
                torch.save(model.state_dict(), OUT / f"{name}_{label}_{seed}.pt")
        np.savez(OUT / f"{name}_normalization.npz", mean=expanded_mean, scale=expanded_scale)
        if outer_stop is not None:
            outer_dates, _ = eligible_days(panel, prices, valid_stop, outer_stop)
            for label, models in (("selected", final_models), ("zero", expanded_zero)):
                result, targets = evaluate_ensemble(models, expanded_days, outer_dates, prices,
                                                     f"{name}_{label}_OUTER")
                result.daily.to_parquet(OUT / f"{name}_{label}_outer_daily.parquet", index=False)
                targets.to_parquet(OUT / f"{name}_{label}_outer_targets.parquet", index=False)
                rows.append({"chain": name, "phase": "outer", "policy": label,
                             "outer_last_signal": str(outer_dates[-1].date()),
                             "outer_last_nav": float(result.daily.nav.iloc[-1])})
        print(f"CHAIN {name} k={chosen} updates_cumulative={total_updates}", flush=True)
    if total_updates > 288:
        raise RuntimeError("RL_UPDATE_BUDGET")
    pd.DataFrame(rows).to_csv(OUT / "trials.csv", index=False)
    record = {"status": "PRE2026_TRAINED", "chains": decisions, "seeds": SEEDS,
              "checkpoints": CHECKPOINTS, "total_updates": total_updates,
              "original_ledger_sha256": manifest["original_e5_sha256"],
              "corrected_ledger_sha256": sha(ROOT / "ledger.py"),
              "panel_sha256": manifest["panel_sha256"],
              "prices_sha256": manifest["prices_sha256"]}
    (OUT / "manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
