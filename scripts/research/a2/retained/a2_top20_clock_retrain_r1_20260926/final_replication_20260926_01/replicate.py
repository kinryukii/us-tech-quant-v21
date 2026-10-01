"""No-test fixed-spec reproduction of the final HGB, MLP and RL weights."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch

ROOT = Path("/bundle")
OUT = Path("/out")
sys.path.insert(0, str(ROOT))
from fit_supervised import FEATURES as SUP_FEATURES, model_for  # noqa: E402
import rl_train  # noqa: E402
from rl_core import build_days  # noqa: E402
from safe_inputs import guarded_parquet  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_arrays(a, b, label: str, tolerance=1e-7) -> float:
    aa, bb = np.asarray(a), np.asarray(b)
    if aa.shape != bb.shape:
        raise RuntimeError(f"SHAPE_MISMATCH:{label}:{aa.shape}:{bb.shape}")
    difference = float(np.max(np.abs(aa.astype(float) - bb.astype(float))))
    if not np.isfinite(difference) or difference > tolerance:
        raise RuntimeError(f"NUMERIC_MISMATCH:{label}:{difference}")
    return difference


def supervised_reproduction(panel: pd.DataFrame) -> list[dict]:
    manifest = json.loads((ROOT / "supervised_manifest.json").read_text())
    cutoff = pd.Timestamp("2026-01-01")
    mature = (panel.label_end_date_5.notna() & np.isfinite(panel.y5)
              & np.isfinite(panel.y5_cost_positive))
    train = panel.loc[panel.signal_date.lt(cutoff) & panel.label_end_date_5.lt(cutoff)
                      & mature]
    if len(train) != 49960 or train.label_end_date_5.max() >= cutoff:
        raise RuntimeError("FINAL_SUPERVISED_BOUNDARY")
    rows = []
    for name, seed in (("HGB", 2026092501), ("MLP", 2026092501),
                       ("MLP", 2026092502)):
        key = f"{name}_{seed}"
        artifact = manifest["artifacts"][key]
        path = ROOT / artifact["path"]
        if sha(path) != artifact["sha256"]:
            raise RuntimeError(f"SEALED_SUPERVISED_MODEL_CHANGED:{key}")
        original = joblib.load(path)
        replica = model_for(name, seed)
        replica.fit(train[SUP_FEATURES], train.y5)
        differences = {"prediction": compare_arrays(
            replica.predict(panel[SUP_FEATURES]), original.predict(panel[SUP_FEATURES]),
            f"{key}:prediction")}
        for step, attribute in (("impute", "statistics_"), ("scale", "mean_"),
                                ("scale", "scale_")):
            differences[f"{step}:{attribute}"] = compare_arrays(
                getattr(replica.named_steps[step], attribute),
                getattr(original.named_steps[step], attribute), f"{key}:{step}:{attribute}")
        if name == "MLP":
            left, right = replica.named_steps["model"], original.named_steps["model"]
            if left.n_iter_ != right.n_iter_:
                raise RuntimeError(f"MLP_ITERATION_MISMATCH:{key}")
            for i, (a, b) in enumerate(zip(left.coefs_, right.coefs_)):
                differences[f"weight_{i}"] = compare_arrays(a, b, f"{key}:weight_{i}")
            for i, (a, b) in enumerate(zip(left.intercepts_, right.intercepts_)):
                differences[f"bias_{i}"] = compare_arrays(a, b, f"{key}:bias_{i}")
        rows.append({"model": key, "train_rows": len(train),
                     "train_last_mature_label": str(train.label_end_date_5.max().date()),
                     "max_numeric_difference": max(differences.values()),
                     "components_compared": differences})
    return rows


def rl_reproduction(panel: pd.DataFrame, prices: pd.DataFrame) -> list[dict]:
    torch.set_num_threads(1)
    receipt = json.loads((ROOT / "rl_artifacts/manifest.json").read_text())
    chosen = next(row["selected_episode"] for row in receipt["chains"] if row["chain"] == "C")
    if chosen not in (1, 8, 16, 24):
        raise RuntimeError("C_CHECKPOINT_OUTSIDE_FROZEN_SET")
    cutoff = pd.Timestamp("2026-01-01")
    mean, scale = rl_train.normalization(panel, cutoff)
    with np.load(ROOT / "rl_artifacts/C_normalization.npz") as original_norm:
        mean_diff = compare_arrays(mean, original_norm["mean"], "C:normalization_mean")
        scale_diff = compare_arrays(scale, original_norm["scale"], "C:normalization_scale")
    days = build_days(panel, mean, scale)
    dates, _ = rl_train.eligible_days(panel, prices, "2021-01-01", cutoff)
    original_updates = [json.loads(line) for line in
                        (ROOT / "rl_artifacts/updates.jsonl").read_text().splitlines()]
    rl_train.OUT = OUT
    rows = []
    for seed in (20260925, 20260926):
        checkpoints, history = rl_train.update_path(
            seed, days, dates, prices, chosen, "C_EXPANDED")
        if len(history) != chosen:
            raise RuntimeError(f"RL_UPDATE_COUNT_CHANGED:{seed}")
        reference_history = [row for row in original_updates
                             if row["chain"] == "C_EXPANDED" and row["seed"] == seed]
        if len(reference_history) != chosen:
            raise RuntimeError(f"RL_RECORDED_UPDATE_COUNT:{seed}")
        for computed, original in zip(history, reference_history):
            for key in ("train_start", "train_last_signal", "environment_steps"):
                if computed[key] != original[key]:
                    raise RuntimeError(f"RL_TRAJECTORY_CHANGED:{seed}:{key}")
            for key in ("loss", "gradient_norm", "train_log_nav", "train_last_nav"):
                compare_arrays([computed[key]], [original[key]], f"RL:{seed}:{key}")
        differences = {"normalization_mean": mean_diff,
                       "normalization_scale": scale_diff}
        for label, index in (("selected", chosen), ("zero", 0)):
            reference = torch.load(ROOT / "rl_artifacts" / f"C_{label}_{seed}.pt",
                                   map_location="cpu", weights_only=True)
            for key, original_weight in reference.items():
                differences[f"{label}:{key}"] = compare_arrays(
                    checkpoints[index][key].detach().numpy(), original_weight.numpy(),
                    f"RL:{seed}:{label}:{key}")
        rows.append({"seed": seed, "selected_episode": chosen,
                     "verification_updates": len(history),
                     "last_training_signal": history[-1]["train_last_signal"],
                     "max_numeric_difference": max(differences.values()),
                     "components_compared": differences})
    return rows


def main() -> None:
    manifest = json.loads((ROOT / "input_manifest.json").read_text())
    if (sha(ROOT / "data/panel.parquet") != manifest["panel_sha256"]
            or sha(ROOT / "data/prices.parquet") != manifest["prices_sha256"]):
        raise RuntimeError("REPRODUCTION_INPUT_HASH_MISMATCH")
    panel = guarded_parquet(ROOT / "data/panel.parquet", "signal_date")
    prices = guarded_parquet(ROOT / "data/prices.parquet", "trade_date")
    supervised = supervised_reproduction(panel)
    rl = rl_reproduction(panel, prices)
    result = {"status": "FINAL_MODEL_NUMERIC_REPRODUCTION_PASS",
              "verification_supervised_fits": len(supervised),
              "verification_rl_updates": sum(row["verification_updates"] for row in rl),
              "supervised": supervised, "rl": rl,
              "scope": "sealed pre-2026 inputs and weights only; no model choice or 2026 data"}
    (OUT / "replication_receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"],
                      "verification_supervised_fits": len(supervised),
                      "verification_rl_updates": result["verification_rl_updates"],
                      "max_supervised_difference": max(row["max_numeric_difference"] for row in supervised),
                      "max_rl_difference": max(row["max_numeric_difference"] for row in rl)}))


if __name__ == "__main__":
    main()
