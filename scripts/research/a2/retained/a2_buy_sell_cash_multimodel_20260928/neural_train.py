"""Fresh fixed-budget MLP/RL fits using the audited capacity-aware simulator.

Every dependency is hash-bound before fitting. This module does not open any
2026 data or old learned weights. Account, fill and locked-holding semantics
come from the previous capacity experiment, whose source remains read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent / "a2_latest_effective_joint_20260927"
SOURCE = UPSTREAM / "data/pre2026_joint_context.parquet"
BASE_PATH = ROOT.parent / "a2_capacity_in_training_paired_20260927/rl_capacity_train.py"
PRICE = ROOT.parent / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
REGISTRY = UPSTREAM / "models/model_registry.json"
CONTRACT = ROOT / "EXPERIMENT_CONTRACT.md"
OUT = ROOT / "neural_artifacts"
DIRECT_SEED = 20260928
SEEDS = (20260928, 20260929)
DIRECT_EPOCHS = 6
RL_EPOCHS = 4
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}

_spec = importlib.util.spec_from_file_location("a2_multimodel_capacity_environment", BASE_PATH)
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
FEATURES = _base.FEATURES
JointPolicy = _base.JointPolicy
Market = _base.Market
project = _base.project
execute_targets = _base.execute_targets
torch.set_num_threads(2)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                                    allow_nan=False, default=str), encoding="utf-8")


def fit_normalization(panel, cutoff):
    """Fit only on signal-known states before the requested stage boundary."""
    part = panel.loc[panel.signal_date.ge("2023-01-01") & panel.signal_date.lt(cutoff)]
    if part.empty:
        raise RuntimeError("NO_STAGE_SCALER_ROWS")
    values = part[FEATURES].to_numpy(float)
    if not np.isfinite(values).all():
        raise RuntimeError("NONFINITE_SCALER_INPUT")
    mean, scale = values.mean(axis=0), values.std(axis=0)
    scale[scale < 1e-12] = 1.
    return mean, scale, dict(rows=len(part), signal_min=str(part.signal_date.min().date()),
                             signal_max=str(part.signal_date.max().date()), cutoff_exclusive=cutoff)


def frozen_sources():
    return {name: {"path": str(path), "sha256": sha(path)} for name, path in {
        "panel": SOURCE, "prices": PRICE, "feature_registry": REGISTRY,
        "environment_source": BASE_PATH, "training_source": Path(__file__),
        "experiment_contract": CONTRACT}.items()}


def train():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("EXISTING_NEURAL_OUTPUT_PRESERVED")
    bindings = frozen_sources()
    panel = pd.read_parquet(SOURCE)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    if panel.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_TRAINING_KEY")
    if (panel.signal_date.isna().any() or not panel.signal_date.lt("2026-01-01").all()
            or not panel.label_end_date.dropna().lt("2026-01-01").all()):
        raise RuntimeError("TRAINING_DATE_BOUNDARY_FAILURE")
    if (not np.isfinite(panel[FEATURES].to_numpy(float)).all()
            or not panel.avg_dollar_volume_20d.gt(0).all()):
        raise RuntimeError("BAD_PRE2026_FEATURE_OR_ADV")
    dates = pd.read_parquet(PRICE, columns=["trade_date"])
    price_dates = pd.to_datetime(dates.trade_date)
    if not price_dates.lt("2026-01-01").all():
        raise RuntimeError("PRICE_SOURCE_NOT_PHYSICALLY_PRE2026")
    OUT.mkdir()
    normalizers = {stage: fit_normalization(panel, cutoff) for stage, cutoff in STAGES.items()}
    contract = dict(status="PRE_FIT_LOCKED", created_utc=datetime.now(timezone.utc).isoformat(),
        frozen_sources=bindings, architecture=[len(FEATURES)+3,32,16,1], feature_order=FEATURES,
        direct_epochs=DIRECT_EPOCHS, direct_seed=DIRECT_SEED, rl_epochs=RL_EPOCHS,
        rl_seeds=list(SEEDS), learning_rate=.0005, weight_decay=.001, risk_aversion=5,
        max_names=20, max_weight=.1, max_exposure=.95, zero_threshold=.02,
        cost_bps_per_side=10, capacity_fraction=.01, initial_cash_dollars=1_000_000.,
        stages={stage: audit for stage, (_, _, audit) in normalizers.items()},
        rl_gamma=.97, rl_block_steps=32, gradient_clip=2., hyperparameter_search_count=0,
        fit_2026_rows=0, previous_learned_weights_loaded=0, normalization="fresh per stage",
        selection="fixed epochs/seeds; no economic validation/test selection",
        reward="one execution-open to following-open log return less target-weight volatility penalty",
        limitations=["Direct MLP uses one-step gradients and detached prior portfolio state.",
                    "RL uses 32-step truncated REINFORCE returns.",
                    "Risk penalty uses target weights, while PnL and next states use actual capped fills.",
                    "Hard TOP20 uses gradient through selected proposals with fixed exploration noise.",
                    "Training reward NAV proxy is diagnostic; independent ledger is the evaluation source."])
    write_json(OUT / "PRE_FIT_CONTRACT.json", contract)
    logs, artifacts, normalization_receipts = [], [], {}
    for stage, cutoff in STAGES.items():
        mean, scale, audit = normalizers[stage]
        normalization = OUT / f"{stage}_normalization.npz"
        np.savez(normalization, mean=mean, scale=scale)
        normalization_receipts[stage] = dict(path=str(normalization), sha256=sha(normalization), **audit)
        # Universe identity and all policy states used for fitting also stop at
        # the stage boundary; the simulator excludes immature two-open rewards.
        train_panel = panel.loc[panel.signal_date.ge("2023-01-01") & panel.signal_date.lt(cutoff)].copy()
        last = str((pd.Timestamp(cutoff) - pd.Timedelta(days=1)).date())
        market = Market(train_panel, "2023-01-01", last, mean, scale)
        if not market.days or any(pd.Timestamp(day["date"]) >= pd.Timestamp(cutoff) for day in market.days):
            raise RuntimeError("TRAINING_MARKET_BOUNDARY_FAILURE")
        for method, seeds, epochs in (("direct", [DIRECT_SEED], DIRECT_EPOCHS), ("rl", SEEDS, RL_EPOCHS)):
            for seed in seeds:
                torch.manual_seed(seed)
                model = JointPolicy()
                initial = {k: v.clone() for k, v in model.state_dict().items()}
                zero = OUT / f"{stage}_{method}_{seed}_zero.pt"
                torch.save(initial, zero)
                optimizer = torch.optim.Adam(model.parameters(), lr=.0005, weight_decay=.001)
                model_updates = 0
                for epoch in range(epochs):
                    start = time.monotonic()
                    info, records = market.episode(model, optimizer, method, seed+epoch)
                    row = dict(stage=stage, method=method, seed=seed, epoch=epoch+1,
                               seconds=time.monotonic()-start, **info)
                    logs.append(row)
                    model_updates += info["updates"]
                    with (OUT / "training.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, allow_nan=False) + "\n")
                    print(json.dumps(row, allow_nan=False), flush=True)
                path = OUT / f"{stage}_{method}_{seed}.pt"
                torch.save(model.state_dict(), path)
                delta = float(sum((value - initial[key]).square().sum().item()
                                  for key, value in model.state_dict().items()) ** .5)
                if not np.isfinite(delta) or delta <= 0 or model_updates <= 0:
                    raise RuntimeError("MODEL_DID_NOT_LEARN_FINITE_PARAMETERS")
                if any(not torch.isfinite(v).all() for v in model.state_dict().values()):
                    raise RuntimeError("NONFINITE_FITTED_MODEL")
                episode_file = OUT / f"{stage}_{method}_{seed}_last_train_episode.parquet"
                pd.DataFrame(records).to_parquet(episode_file, index=False)
                artifacts.append(dict(stage=stage, method=method, seed=seed, epochs=epochs,
                    path=str(path), sha256=sha(path), zero_path=str(zero), zero_sha256=sha(zero),
                    parameter_delta_l2=delta, updates=model_updates,
                    parameters=sum(p.numel() for p in model.parameters()),
                    train_signal_max=market.days[-1]["date"], reward_end_before=cutoff,
                    normalization_sha256=sha(normalization), last_episode_sha256=sha(episode_file)))
                write_json(OUT / "TRAIN_RECEIPT.partial.json", dict(status="RUNNING", artifacts=artifacts,
                    normalization=normalization_receipts, completed_models=len(artifacts), fit_2026_rows=0))
    if bindings != frozen_sources():
        raise RuntimeError("FROZEN_SOURCE_DRIFT_AFTER_FIT")
    write_json(OUT / "TRAIN_RECEIPT.json", dict(status="PASS", specification=contract,
        pre_fit_contract_sha256=sha(OUT / "PRE_FIT_CONTRACT.json"), artifacts=artifacts,
        normalization=normalization_receipts, logs=logs, completed_models=len(artifacts),
        actual_parameter_updates=sum(a["updates"] for a in artifacts),
        training_signal_max=str(panel.signal_date.max().date()),
        training_label_end_max=str(panel.label_end_date.max().date()),
        max_price_source_date=str(price_dates.max().date()), fit_2026_rows=0,
        validation_economic_outputs_read=0, source_hashes_unchanged=True))
    print(json.dumps({"status":"PASS", "completed_models":len(artifacts)}), flush=True)


class NeuralAdapter:
    """Load a frozen stage's policy; exposes mean/scale/models to account adapter."""
    def __init__(self, method="direct", zero=False, stage="final", seed=None):
        if method not in ("direct", "rl") or stage not in STAGES:
            raise ValueError("UNKNOWN_METHOD_OR_STAGE")
        receipt = json.loads((OUT / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
        if receipt["status"] != "PASS" or receipt["completed_models"] != 6:
            raise RuntimeError("INCOMPLETE_NEURAL_TRAINING")
        normalization = receipt["normalization"][stage]
        if sha(normalization["path"]) != normalization["sha256"]:
            raise RuntimeError("SCALER_HASH_MISMATCH")
        a = np.load(normalization["path"])
        self.mean, self.scale = a["mean"], a["scale"]
        seeds = [DIRECT_SEED] if method == "direct" else list(SEEDS)
        if seed is not None:
            if seed not in seeds:
                raise ValueError("UNKNOWN_FIXED_SEED")
            seeds = [seed]
        self.models = []
        self.stage, self.method, self.seeds = stage, method, seeds
        for member_seed in seeds:
            record = next(r for r in receipt["artifacts"] if r["stage"] == stage
                          and r["method"] == method and r["seed"] == member_seed)
            path_key, hash_key = ("zero_path", "zero_sha256") if zero else ("path", "sha256")
            if sha(record[path_key]) != record[hash_key]:
                raise RuntimeError("MODEL_HASH_MISMATCH")
            model = JointPolicy()
            model.load_state_dict(torch.load(record[path_key], weights_only=True, map_location="cpu"))
            model.eval()
            self.models.append(model)

    def __call__(self, day, weights, cash, *, max_names=20, max_exposure=.95):
        if day.empty:
            return {}
        day = day.loc[day.new_buy_eligible.astype(bool) | day.ticker.map(weights).fillna(0).gt(0)]
        day = day.sort_values("ticker", kind="stable")
        if day.empty:
            return {}
        x = np.clip((day[FEATURES].to_numpy(float)-self.mean)/self.scale, -8, 8)
        current = day.ticker.map(weights).fillna(0).to_numpy(float)
        obs = torch.tensor(np.column_stack([x, current, np.repeat(cash, len(day)), current > 0]), dtype=torch.float32)
        upper = torch.tensor(np.where(day.new_buy_eligible.to_numpy(bool), .1, np.minimum(current, .1)), dtype=torch.float32)
        with torch.no_grad():
            w = torch.stack([project(m(obs), upper=upper, max_names=max_names,
                                     max_exposure=max_exposure) for m in self.models]).mean(dim=0).numpy()
        keep = np.argsort(-w, kind="stable")[:max_names]
        mask = np.zeros(len(w)); mask[keep] = 1; w *= mask
        if w.sum() > max_exposure:
            w *= max_exposure/w.sum()
        return {str(t):float(v) for t,v in zip(day.ticker,w) if v > 1e-8}


if __name__ == "__main__":
    train()
