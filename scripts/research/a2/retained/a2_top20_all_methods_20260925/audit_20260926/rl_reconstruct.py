"""Read-only RL lineage and zero-update control; writes only into this audit directory."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import rl_policy as rl  # noqa: E402


def compare_state(a, b):
    return {
        "max_abs": max(float((a[k] - b[k]).abs().max()) for k in a),
        "exact": all(torch.equal(a[k], b[k]) for k in a),
        "parameters": sum(x.numel() for x in a.values()),
    }


def make_initial(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    return rl.Policy(len(rl.FEATURES) + 4)


def main():
    torch.set_num_threads(1)
    manifest = json.loads((rl.OUT / "manifest.json").read_text(encoding="utf-8"))
    safe = rl.load_module("audit_rl_safe", rl.OLD / "safe_inputs.py")
    _, prices, _, _ = safe.load_inputs()
    panel, _ = rl.load_research_panel()
    train = panel.loc[panel.signal_date.lt(rl.TRAIN_END)]
    valid = panel.loc[panel.signal_date.ge(rl.TRAIN_END)]
    mean = np.nanmean(train[rl.FEATURES].to_numpy(float), axis=0)
    scale = np.nanstd(train[rl.FEATURES].to_numpy(float), axis=0)
    scale[~np.isfinite(scale) | (scale < 1e-8)] = 1.
    norm = np.load(rl.OUT / "normalization.npz")
    days = rl.build_days(panel, mean, scale)
    e5 = rl.load_module("audit_rl_e5", rl.E5)
    replay = rl.dynamic_e5_replay(e5)
    train_dates = sorted(train.signal_date.unique())
    valid_dates = sorted(valid.signal_date.unique())
    rows = []
    for seed in rl.SEEDS:
        policy = make_initial(seed)
        initial = {k: v.detach().clone() for k, v in policy.state_dict().items()}
        initial_state_sha = {k: __import__("hashlib").sha256(v.numpy().tobytes()).hexdigest() for k, v in initial.items()}
        policy.eval()
        with torch.no_grad():
            init_val, _, _, _ = rl.evaluate(policy, days, valid_dates, prices, replay,
                                             f"AUDIT_RL_INIT_{seed}")
        rng = np.random.default_rng(seed)
        first = int(rng.integers(0, len(train_dates) - rl.LENGTH - 1))
        subset = train_dates[first:first + rl.LENGTH]
        optimizer = torch.optim.Adam(policy.parameters(), lr=rl.LR)
        policy.train()
        result, reward, logs, _ = rl.evaluate(policy, days, subset, prices, replay,
                                              f"AUDIT_RL_EP1_{seed}", training=True)
        returns = np.empty_like(reward)
        future = 0.
        for i in range(len(reward) - 1, -1, -1):
            future = reward[i] + rl.GAMMA * future
            returns[i] = future
        advantage = (returns - returns.mean()) / (returns.std() + 1e-6)
        loss = -torch.stack([p * float(a) for p, a in zip(logs, advantage)]).mean()
        optimizer.zero_grad()
        loss.backward()
        grad = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), 2.))
        optimizer.step()
        saved = torch.load(rl.OUT / f"checkpoint_{seed}_1.pt", map_location="cpu", weights_only=True)
        cmp = compare_state(policy.state_dict(), saved)
        delta = torch.cat([(saved[k] - initial[k]).flatten() for k in initial])
        policy.eval()
        with torch.no_grad():
            val, _, _, _ = rl.evaluate(policy, days, valid_dates, prices, replay,
                                        f"AUDIT_RL_REBUILT_{seed}")
        stored_daily = pd.read_parquet(rl.OUT / f"validation_{seed}_daily.parquet")
        nav_error = float(np.max(np.abs(val.daily.nav.to_numpy() - stored_daily.nav.to_numpy())))
        rows.append({"seed": seed, "initial_validation_final_nav": float(init_val.daily.nav.iloc[-1]),
                     "selected_validation_final_nav": float(stored_daily.nav.iloc[-1]),
                     "first_episode_start": str(pd.Timestamp(subset[0]).date()),
                     "first_episode_end": str(pd.Timestamp(subset[-1]).date()),
                     "first_episode_reward_log_sum": float(reward.sum()),
                     "first_episode_loss": float(loss.detach()),
                     "first_episode_grad_norm": grad,
                     "checkpoint1_exact_rebuild": cmp["exact"],
                     "checkpoint1_max_abs_tensor_diff": cmp["max_abs"],
                     "parameter_update_l2": float(delta.norm()),
                     "parameter_update_max_abs": float(delta.abs().max()),
                     "validation_nav_max_abs_diff": nav_error,
                     "parameters": cmp["parameters"],
                     "initial_state_tensor_sha256": json.dumps(initial_state_sha, sort_keys=True)})
    pd.DataFrame(rows).to_csv(OUT / "rl_initial_reconstruction.csv", index=False)
    output = {"normalization_mean_exact": bool(np.array_equal(norm["mean"], mean)),
              "normalization_scale_exact": bool(np.array_equal(norm["scale"], scale)),
              "train_rows": len(train), "validation_rows": len(valid),
              "train_max_signal": str(train.signal_date.max()),
              "validation_min_signal": str(valid.signal_date.min()),
              "validation_max_signal": str(valid.signal_date.max()),
              "selected_episode": manifest["selected_episode"]}
    (OUT / "rl_reconstruction_meta.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(pd.DataFrame(rows).drop(columns="initial_state_tensor_sha256").to_string(index=False))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
