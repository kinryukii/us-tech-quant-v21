"""Pre-2026 policy-gradient sizing research using the existing E5 share/cash replay."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "rl_artifacts"
OLD = ROOT.parent / "a2_top20_action_nn_20260925"
E5 = Path(r"D:\us-tech-quant-results\A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS\run_a2_execution_efficiency_r2.py")
PANEL = ROOT / "pre2026_panel.parquet"
PANEL_MANIFEST = ROOT / "pre2026_manifest.json"
CUTOFF = pd.Timestamp("2026-01-01")
TRAIN_END = pd.Timestamp("2025-01-01")
FEATURES = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d", "ret_20d",
            "realized_vol_20d", "downside_vol_20d", "max_drawdown_20d",
            "volume_ratio_5d_20d", "price_vs_ma20", "distance_from_high_20d"]
SEEDS = (20260925, 20260926)
EPISODES = 24
LENGTH = 120
MAX_WEIGHT = .10
MAX_EXPOSURE = .95
MAX_NAMES = 30
ZERO_GATE = .30
NOISE_STD = .45
LR = .001
GAMMA = .99


def sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_research_panel() -> tuple[pd.DataFrame, dict]:
    provenance = json.loads(PANEL_MANIFEST.read_text(encoding="utf-8"))
    if sha(PANEL) != provenance["panel_sha256"]:
        raise RuntimeError("PRE2026_PANEL_HASH_MISMATCH")
    panel = pd.read_parquet(PANEL)
    if panel.signal_date.max() >= CUTOFF or panel.signal_date.min() < pd.Timestamp("2021-01-01"):
        raise RuntimeError("RL_SIGNAL_BOUNDARY")
    if panel.duplicated(["signal_date", "ticker"]).any() or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("RL_PANEL_IDENTITY_OR_CARDINALITY")
    return panel, provenance


def dynamic_e5_replay(e5):
    source = inspect.getsource(e5.replay)
    old = "target = targets.get(signal, {}) if signal is not None else {}"
    new = "target = targets(signal, shares.copy(), pre_values.copy(), pretrade_nav) if signal is not None else {}"
    if source.count(old) != 1:
        raise RuntimeError("E5_TARGET_LOOKUP_SEAM_CHANGED")
    source = source.replace("def replay(", "def dynamic_replay(", 1).replace(old, new, 1)
    stale_execution = "price = marks.get(ticker, opening(date, ticker))"
    if source.count(stale_execution) != 2:
        raise RuntimeError("E5_EXECUTION_PRICE_SEAM_CHANGED")
    # A stale close is valid for marking NAV, never for filling a new order.
    source = source.replace(stale_execution, "price = opening(date, ticker)")
    exec(compile(source, str(E5), "exec"), vars(e5))
    return e5.dynamic_replay


class Policy(nn.Module):
    def __init__(self, inputs: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(inputs, 24), nn.Tanh(), nn.Linear(24, 1))
        nn.init.constant_(self.net[-1].bias, -.7)

    def forward(self, x):
        return self.net(x).flatten()


def build_days(panel: pd.DataFrame, mean: np.ndarray, scale: np.ndarray):
    days = {}
    for date, group in panel.groupby("signal_date", sort=True):
        g = group.sort_values(["raw_rank", "ticker"])
        values = np.nan_to_num((g[FEATURES].to_numpy(float) - mean) / scale,
                               nan=0., posinf=0., neginf=0.).clip(-8, 8)
        days[pd.Timestamp(date)] = (g.ticker.astype(str).tolist(),
                                    g.raw_rank.to_numpy(int), values)
    return days


def policy_target(policy, day, shares, pre_values, nav, training, log_probs=None, records=None):
    names, ranks, features = day
    lookup = {t: i for i, t in enumerate(names)}
    selected = [t for t, r in zip(names, ranks) if r <= 20]
    selected += sorted(set(shares) - set(selected))
    cash_weight = max(0., 1. - sum(pre_values.values()) / nav)
    rows = []
    for ticker in selected:
        i = lookup.get(ticker)
        base = features[i] if i is not None else np.zeros(len(FEATURES))
        old_w = pre_values.get(ticker, 0.) / nav
        rows.append(np.r_[base, old_w, cash_weight, float(ticker in shares), float(i is not None and ranks[i] <= 20)])
    obs = torch.tensor(np.asarray(rows, dtype=np.float32))
    mean_logit = policy(obs)
    if training:
        dist = torch.distributions.Normal(mean_logit, NOISE_STD)
        raw = dist.sample()
        assert log_probs is not None
        log_probs.append(dist.log_prob(raw).sum())
    else:
        raw = mean_logit
    tentative = torch.where(torch.sigmoid(raw) >= ZERO_GATE,
                            MAX_WEIGHT * torch.sigmoid(raw), torch.zeros_like(raw))
    if len(selected) > MAX_NAMES:
        keep = torch.topk(tentative, MAX_NAMES).indices
        mask = torch.zeros_like(tentative)
        mask[keep] = 1.
        tentative = tentative * mask
    gross = float(tentative.detach().sum())
    target = tentative * min(1., MAX_EXPOSURE / gross) if gross > 0 else tentative
    weights = target.detach().numpy()
    answer = {t: float(w) for t, w in zip(selected, weights) if w > 0}
    if records is not None:
        for t, r, w in zip(selected, raw.detach().numpy(), weights):
            records.append({"ticker": t, "raw_action_logit": float(r),
                            "pretrade_weight": float(pre_values.get(t, 0.) / nav),
                            "target_weight": float(w), "eligible_new": t in names[:20],
                            "held_before": t in shares, "cash_weight_before": cash_weight})
    assert sum(answer.values()) <= MAX_EXPOSURE + 1e-6
    assert len(answer) <= MAX_NAMES
    assert all(0 < w <= MAX_WEIGHT + 1e-6 for w in answer.values())
    return answer


def evaluate(policy, days, dates, prices, replay, label, training=False):
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    next_day = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    dates = [pd.Timestamp(d) for d in dates if pd.Timestamp(d) in next_day]
    executions = [next_day[d] for d in dates]
    assert not executions or max(executions) < CUTOFF
    signal_by_execution = dict(zip(executions, dates))
    logs, records = [], []
    def target(signal, shares, pre_values, nav):
        start = len(records)
        result = policy_target(policy, days[signal], shares, pre_values, nav, training, logs, records)
        for row in records[start:]:
            row["signal_date"] = signal
        return result
    # The E5 replay is the only execution, fee and wealth engine in this route.
    result = replay(label, target, prices, executions, signal_by_execution)
    frame = result.daily
    reward = np.log(frame.nav.to_numpy(float) / np.r_[1., frame.nav.to_numpy(float)[:-1]])
    return result, reward, logs, pd.DataFrame(records)


def train() -> None:
    start_time = time.time()
    torch.set_num_threads(1)
    OUT.mkdir(parents=True, exist_ok=True)
    safe = load_module("a2_rl_safe", OLD / "safe_inputs.py")
    _, prices, _, lineage = safe.load_inputs()
    panel, panel_provenance = load_research_panel()
    assert panel.signal_date.max() < CUTOFF and prices.trade_date.max() < CUTOFF
    train_panel = panel.loc[panel.signal_date.lt(TRAIN_END)]
    valid_panel = panel.loc[panel.signal_date.ge(TRAIN_END)]
    mean = np.nanmean(train_panel[FEATURES].to_numpy(float), axis=0)
    scale = np.nanstd(train_panel[FEATURES].to_numpy(float), axis=0)
    scale[~np.isfinite(scale) | (scale < 1e-8)] = 1.
    days = build_days(panel, mean, scale)
    train_dates = sorted(train_panel.signal_date.unique())
    valid_dates = sorted(valid_panel.signal_date.unique())
    e5 = load_module("a2_rl_e5", E5)
    replay = dynamic_e5_replay(e5)
    trials = []
    models = {}
    for seed in SEEDS:
        random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
        policy = Policy(len(FEATURES) + 4)
        optimizer = torch.optim.Adam(policy.parameters(), lr=LR)
        rng = np.random.default_rng(seed)
        for episode in range(1, EPISODES + 1):
            first = int(rng.integers(0, len(train_dates) - LENGTH - 1))
            subset = train_dates[first:first + LENGTH]
            policy.train()
            result, reward, logs, _ = evaluate(policy, days, subset, prices, replay,
                                                f"RL_{seed}_E{episode}", training=True)
            assert len(logs) == len(reward) == LENGTH
            returns = np.empty_like(reward)
            future = 0.
            for i in range(len(reward) - 1, -1, -1):
                future = reward[i] + GAMMA * future
                returns[i] = future
            advantage = (returns - returns.mean()) / (returns.std() + 1e-6)
            loss = -torch.stack([p * float(a) for p, a in zip(logs, advantage)]).mean()
            optimizer.zero_grad(); loss.backward()
            grad = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), 2.))
            optimizer.step()
            trials.append({"seed": seed, "episode": episode, "phase": "train", "start_signal": subset[0],
                           "end_signal": subset[-1], "environment_steps": len(reward),
                           "parameter_updates": episode, "loss": float(loss.detach()), "gradient_norm": grad,
                           "unshaped_log_growth": float(reward.sum()),
                           "net_return": float(result.daily.nav.iloc[-1] - 1),
                           "cash_mean": float(result.daily.cash_weight.mean()),
                           "turnover": float(result.daily.turnover.sum())})
            if episode in (1, 8, 16, 24):
                policy.eval()
                with torch.no_grad():
                    val, val_reward, _, actions = evaluate(policy, days, valid_dates, prices, replay,
                                                             f"RL_{seed}_VALID_{episode}")
                x = val.daily
                trials.append({"seed": seed, "episode": episode, "phase": "validation",
                               "start_signal": valid_dates[0], "end_signal": valid_dates[-1],
                               "environment_steps": len(x), "parameter_updates": episode,
                               "unshaped_log_growth": float(val_reward.sum()),
                               "net_return": float(x.nav.iloc[-1] - 1),
                               "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
                               "cash_mean": float(x.cash_weight.mean()),
                               "turnover": float(x.turnover.sum()),
                               "nonzero_targets": int(actions.target_weight.gt(0).sum()),
                               "zero_targets": int(actions.target_weight.eq(0).sum())})
                torch.save(policy.state_dict(), OUT / f"checkpoint_{seed}_{episode}.pt")
                print(f"RL seed={seed} episode={episode} train={reward.sum():.3f} valid={val_reward.sum():.3f}", flush=True)
        models[seed] = policy
    table = pd.DataFrame(trials)
    table.to_csv(OUT / "trials.csv", index=False)
    valid = table.loc[table.phase.eq("validation")]
    # One checkpoint shared across seeds; pre-2026 validation selects episode only.
    choice = int(valid.groupby("episode").unshaped_log_growth.mean().idxmax())
    final_files = {}
    for seed in SEEDS:
        source = OUT / f"checkpoint_{seed}_{choice}.pt"
        final_files[str(seed)] = {"path": source.name, "sha256": sha(source)}
    np.savez(OUT / "normalization.npz", mean=mean, scale=scale)
    validation_files = {}
    for seed in SEEDS:
        policy = Policy(len(FEATURES) + 4)
        policy.load_state_dict(torch.load(OUT / final_files[str(seed)]["path"], map_location="cpu", weights_only=True))
        policy.eval()
        with torch.no_grad():
            val, _, _, actions = evaluate(policy, days, valid_dates, prices, replay,
                                          f"RL_{seed}_SELECTED_VALID")
        for label, frame in (("daily", val.daily), ("trades", val.trades), ("targets", actions)):
            path = OUT / f"validation_{seed}_{label}.parquet"
            frame.to_parquet(path, index=False)
            validation_files[f"{seed}_{label}"] = {"path": path.name, "sha256": sha(path), "rows": len(frame)}
    record = {"status": "PRE2026_FROZEN", "cutoff_exclusive": str(CUTOFF.date()),
              "train_signal_max": str(train_panel.signal_date.max()),
              "validation_signal_min": str(valid_panel.signal_date.min()),
              "validation_signal_max": str(valid_panel.signal_date.max()),
              "source_scope": "pre2026_panel.parquet full 1253-day historical Top40 opportunity panel; RL uses no supervised future label",
              "source_lineage": lineage, "panel_sha256": sha(PANEL),
              "panel_manifest_sha256": sha(PANEL_MANIFEST),
              "panel_rows": len(panel), "panel_dates": panel.signal_date.nunique(),
              "panel_unmatured_supervised_rows_retained_for_rl": panel_provenance["unmatured_rows"],
              "source_code_sha256": sha(Path(__file__)),
              "e5_source_sha256": sha(E5), "seeds": SEEDS, "episodes_per_seed": EPISODES,
              "e5_adapter": "two execution-price lookups require current open; missing open blocks buy/sell while stale prior close remains NAV mark",
              "episode_length": LENGTH, "independent_train_dates": len(train_dates),
              "validation_dates": len(valid_dates), "selected_episode": choice,
              "selected_checkpoints": final_files,
              "selected_validation": validation_files,
              "normalization_sha256": sha(OUT / "normalization.npz"),
              "trials_sha256": sha(OUT / "trials.csv"),
              "policy": {"method": "episodic REINFORCE with Gaussian continuous logits",
                         "network": "shared 15-input 24-tanh-1 policy applied by ticker",
                         "max_weight": MAX_WEIGHT, "max_exposure": MAX_EXPOSURE,
                         "max_names": MAX_NAMES,
                         "zero_gate": ZERO_GATE, "noise_std_train_only": NOISE_STD,
                         "gamma": GAMMA, "learning_rate": LR,
                         "inference": "deterministic mean logit; no optimizer or normalization update",
                         "state": "current date Top40 features, true ticker-keyed share/value state, cash, top20 eligibility",
                         "reward": "unshaped daily net log NAV growth after E5 fees; no terminal free liquidation"},
              "fit_seconds": time.time() - start_time,
              "risk_note": "historical price-coordinate simulation; no future label enters RL state or reward"}
    (OUT / "manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"FROZEN RL selected episode={choice} seconds={time.time()-start_time:.1f}", flush=True)


def load_frozen(seed: int):
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    item = manifest["selected_checkpoints"][str(seed)]
    assert sha(OUT / item["path"]) == item["sha256"]
    assert sha(OUT / "normalization.npz") == manifest["normalization_sha256"]
    model = Policy(len(FEATURES) + 4)
    model.load_state_dict(torch.load(OUT / item["path"], map_location="cpu", weights_only=True))
    model.eval()
    norm = np.load(OUT / "normalization.npz")
    return model, norm["mean"], norm["scale"]


def frozen_callback(days: dict[pd.Timestamp, tuple[list[str], np.ndarray, np.ndarray]],
                    seed: int | None = None, records: list[dict] | None = None):
    """Return an E5 dynamic-target callback; days must be built from signal-time rows.

    With seed=None, average the two frozen policy target vectors before E5 executes.
    Both policies use the same frozen training normalization; no parameter update occurs.
    """
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    chosen = (seed,) if seed is not None else tuple(manifest["seeds"])
    loaded = [load_frozen(s) for s in chosen]
    models = [item[0] for item in loaded]

    def callback(signal, shares, pre_values, nav):
        targets = []
        for model in models:
            with torch.no_grad():
                targets.append(policy_target(model, days[pd.Timestamp(signal)], shares,
                                             pre_values, nav, False))
        names = set().union(*(set(t) for t in targets))
        result = {t: float(sum(p.get(t, 0.) for p in targets) / len(targets)) for t in names}
        if len(result) > MAX_NAMES:
            retained = set(sorted(result, key=lambda t: (-result[t], t))[:MAX_NAMES])
            result = {t: w for t, w in result.items() if t in retained}
        if records is not None:
            for t in sorted(set(shares) | names):
                records.append({"signal_date": pd.Timestamp(signal), "ticker": t,
                                "pretrade_shares": float(shares.get(t, 0.)),
                                "pretrade_weight": float(pre_values.get(t, 0.) / nav),
                                "target_weight": float(result.get(t, 0.)),
                                "cash_weight_before": float(1. - sum(pre_values.values()) / nav),
                                "held_before": t in shares})
        assert sum(result.values()) <= MAX_EXPOSURE + 1e-6
        assert len(result) <= MAX_NAMES
        return result
    return callback


def finalize_ensemble_validation() -> None:
    """Evaluate the deployed two-seed target average on 2025 before any 2026 read."""
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    safe = load_module("a2_rl_safe_finalize", OLD / "safe_inputs.py")
    _, prices, _, _ = safe.load_inputs()
    panel, _ = load_research_panel()
    norm = np.load(OUT / "normalization.npz")
    days = build_days(panel, norm["mean"], norm["scale"])
    valid_dates = sorted(panel.loc[panel.signal_date.ge(TRAIN_END), "signal_date"].unique())
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    next_day = {pd.Timestamp(a): pd.Timestamp(b) for a, b in zip(calendar[:-1], calendar[1:])}
    execution = [next_day[pd.Timestamp(d)] for d in valid_dates if pd.Timestamp(d) in next_day]
    by_exec = {next_day[pd.Timestamp(d)]: pd.Timestamp(d) for d in valid_dates if pd.Timestamp(d) in next_day}
    e5 = load_module("a2_rl_e5_finalize", E5)
    replay = dynamic_e5_replay(e5)
    rows = []
    target_fn = frozen_callback(days, seed=None)

    def callback(signal, shares, pre_values, nav):
        result = target_fn(signal, shares, pre_values, nav)
        for ticker in sorted(set(shares) | set(result)):
            rows.append({"signal_date": signal, "ticker": ticker,
                         "pretrade_shares": shares.get(ticker, 0.),
                         "pretrade_weight": pre_values.get(ticker, 0.) / nav,
                         "target_weight": result.get(ticker, 0.)})
        return result

    result = replay("RL_TWO_SEED_TARGET_MEAN_VALID", callback, prices, execution, by_exec)
    files = {}
    for label, frame in (("daily", result.daily), ("trades", result.trades),
                         ("targets", pd.DataFrame(rows))):
        path = OUT / f"validation_ensemble_{label}.parquet"
        frame.to_parquet(path, index=False)
        files[label] = {"path": path.name, "sha256": sha(path), "rows": len(frame)}
    x = result.daily
    single = {str(seed): float(pd.read_parquet(OUT / f"validation_{seed}_daily.parquet").nav.iloc[-1] - 1)
              for seed in SEEDS}
    manifest["ensemble_validation"] = {
        "files": files, "net_return": float(x.nav.iloc[-1] - 1),
        "mean_cash_weight": float(x.cash_weight.mean()),
        "max_drawdown": float((x.nav / x.nav.cummax() - 1).min()),
        "turnover": float(x.turnover.sum()), "single_seed_net_returns": single,
        "policy_selection": "two-seed target-vector mean designated primary before ensemble validation; singles diagnostic",
        "mean_targets_not_mean_returns": True,
    }
    uncapped = OUT / "trials_uncapped_pretest.csv"
    if uncapped.is_file():
        manifest["pretest_revision"] = {
            "trial_path": uncapped.name, "trial_sha256": sha(uncapped),
            "reason": "uncapped old holdings accumulated many micro-positions in 2025; added 30-name projection before any 2026 test",
            "scope": "earlier two-seed 24-episode pretest with missing-open E5 correction; checkpoint files superseded; trial history retained",
        }
    label_truncated = OUT / "trials_label_truncated_pretest.csv"
    if label_truncated.is_file():
        manifest["pretest_revision_label_scope"] = {
            "trial_path": label_truncated.name, "trial_sha256": sha(label_truncated),
            "reason": "RL does not use supervised labels; switch to the full pre2026_panel opportunity history including late-2025 signals",
            "scope": "earlier capped two-seed 24-episode pretest on old 20-day-label-mature intersection; checkpoint files superseded; trial history retained",
        }
    unprojected = OUT / "validation_ensemble_unprojected_pretest_daily.parquet"
    if unprojected.is_file():
        manifest["pretest_revision_ensemble_projection"] = {
            "daily_path": unprojected.name, "daily_sha256": sha(unprojected),
            "reason": "mean of two separately 30-name-constrained target vectors can hold more than 30 distinct names; apply the same 30-name cap after averaging",
            "scope": "pre2026 validation only; no 2026 outcome read",
        }
    manifest["source_code_sha256"] = sha(Path(__file__))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print("ENSEMBLE_PRE2026_VALIDATION", manifest["ensemble_validation"], flush=True)


if __name__ == "__main__":
    train()
