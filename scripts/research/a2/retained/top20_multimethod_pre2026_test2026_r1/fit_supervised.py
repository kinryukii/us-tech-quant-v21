"""Bounded, resumable fits of the frozen nine-feature TOP20 development folds."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from torch import nn

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
PRED = HERE / "predictions"
MODELS.mkdir(exist_ok=True)
PRED.mkdir(exist_ok=True)
FEATURES = ["r", "log_sigma20", "u", "u_squared", "v", "v_squared",
            "breadth", "r_times_v", "age_times_v"]
NO13F = [0, 1]
SEEDS = [11, 29, 47]
FOLDS = {
    "D1": ("2023-12-31", "2024-01-01", "2024-06-30"),
    "D2": ("2024-06-30", "2024-07-01", "2024-12-31"),
    "V25": ("2024-12-31", "2025-01-01", "2025-12-31"),
    "FINAL": ("2025-12-31", None, None),
}
GRIDS = {
    "RIDGE": [{"alpha": 1}, {"alpha": 10}],
    "ELASTIC": [{"alpha": .001}, {"alpha": .01}],
    "LOGISTIC": [{"C": .1}, {"C": 1}],
    "HGB": [{"max_leaf_nodes": 7}, {"max_leaf_nodes": 15}],
    "MLP": [{"hidden": (16,)}, {"hidden": (32, 16)}],
    "QUANTILE": [{"max_leaf_nodes": 7}, {"max_leaf_nodes": 15}],
}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_joblib(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(value, tmp)
    os.replace(tmp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def append_fit(record: dict) -> None:
    path = HERE / "FIT_LOG.csv"
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    new = pd.concat([old, pd.DataFrame([record])], ignore_index=True)
    atomic_parquet(HERE / "FIT_LOG_CHECKPOINT.parquet", new)
    tmp = path.with_suffix(".csv.tmp")
    new.to_csv(tmp, index=False)
    os.replace(tmp, path)


def load_fold(panel: pd.DataFrame, fold: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff, start, end = FOLDS[fold]
    if panel.signal_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("2026_SIGNAL_IN_TRAINING_PANEL")
    if panel.label_available_at_utc.max() >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise RuntimeError("2026_LABEL_IN_TRAINING_PANEL")
    bound = pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1)
    train = panel.loc[panel.base_usable_day & panel.signal_date.le(pd.Timestamp(cutoff)) &
                      panel.label_end_date.le(pd.Timestamp(cutoff)) &
                      panel.label_available_at_utc.lt(bound)].copy()
    val = panel.iloc[0:0].copy() if start is None else panel.loc[
        panel.base_usable_day & panel.signal_date.between(start, end) &
        panel.label_end_date.le(pd.Timestamp(end))].copy()
    assert len(train) and train.label_available_at_utc.max() < bound
    assert len(train) % 20 == 0 and len(val) % 20 == 0
    assert not (train.signal_date.isin(val.signal_date)).any()
    return train, val


def scaler_for(fold: str, train: pd.DataFrame) -> dict:
    path = MODELS / f"SCALER_{fold}.joblib"
    if path.exists():
        value = joblib.load(path)
        assert value["columns"] == FEATURES and value["train_rows"] == len(train)
        return value
    x = train[FEATURES].to_numpy(float)
    assert np.isfinite(x).all()
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    constant = std < 1e-12
    value = {"columns": FEATURES, "mean": mean, "std": std,
             "constant": constant, "train_rows": len(train),
             "train_last_label_available_at": str(train.label_available_at_utc.max())}
    atomic_joblib(path, value)
    return value


def scale(frame: pd.DataFrame, scaler: dict, no13f: bool = False) -> np.ndarray:
    x = frame[FEATURES].to_numpy(float)
    safe = np.where(scaler["constant"], 1.0, scaler["std"])
    out = np.clip((x - scaler["mean"]) / safe, -5.0, 5.0)
    out[:, scaler["constant"]] = 0.0
    assert np.isfinite(out).all()
    return out[:, NO13F] if no13f else out


class Net(nn.Module):
    def __init__(self, width: tuple[int, ...], input_size: int = len(FEATURES)):
        super().__init__()
        sizes = (input_size, *width, 1)
        layers: list[nn.Module] = []
        for i in range(len(sizes) - 1):
            layers.append(nn.Linear(sizes[i], sizes[i + 1]))
            if i < len(sizes) - 2:
                layers.append(nn.ReLU())
        self.layers = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x).squeeze(-1)


def model_key(fold: str, family: str, config: dict, seed: int | None = None,
              quantile: float | None = None) -> str:
    token = "_".join(f"{k}{str(v).replace(' ', '').replace('.', 'p')}" for k, v in config.items())
    return "_".join(str(x) for x in (fold, family, token,
                    f"q{int(quantile * 100)}" if quantile is not None else None,
                    f"seed{seed}" if seed is not None else None) if x is not None)


def predict_saved(path: Path, family: str, x: np.ndarray, config: dict) -> np.ndarray:
    if family == "MLP":
        artifact = torch.load(path, map_location="cpu", weights_only=True)
        net = Net(tuple(config["hidden"]))
        net.load_state_dict(artifact["model"])
        net.eval()
        with torch.no_grad():
            return net(torch.as_tensor(x, dtype=torch.float32)).numpy() / 100.0
    model = joblib.load(path)
    if family == "LOGISTIC":
        return model.predict_proba(x)[:, 1]
    return model.predict(x) / 100.0


def fit_one(fold: str, family: str, config: dict, train: pd.DataFrame,
            val: pd.DataFrame, scaler: dict, *, seed: int | None = None,
            quantile: float | None = None) -> tuple[str, np.ndarray]:
    key = model_key(fold, family, config, seed, quantile)
    suffix = ".pt" if family == "MLP" else ".joblib"
    path = MODELS / f"{key}{suffix}"
    meta_path = MODELS / f"{key}.json"
    x = scale(train, scaler, family == "HGB_NO13F")
    xv = scale(val, scaler, family == "HGB_NO13F")
    y = train.gross_return_decimal.to_numpy(float)
    if not path.exists():
        if family == "RIDGE":
            model = Ridge(alpha=config["alpha"], fit_intercept=True)
        elif family == "ELASTIC":
            model = ElasticNet(alpha=config["alpha"], l1_ratio=.5,
                               max_iter=10000, tol=1e-5)
        elif family == "LOGISTIC":
            if len(np.unique(train.up_label)) != 2:
                raise RuntimeError(f"LOGISTIC_ONE_CLASS:{fold}")
            model = LogisticRegression(C=config["C"], penalty="l2", max_iter=2000)
        elif family in ("HGB", "HGB_NO13F", "QUANTILE"):
            kwargs = dict(max_leaf_nodes=config["max_leaf_nodes"], max_iter=100,
                          learning_rate=.05, min_samples_leaf=100,
                          l2_regularization=1, random_state=11,
                          early_stopping=False, warm_start=False)
            model = HistGradientBoostingRegressor(
                loss="quantile" if family == "QUANTILE" else "squared_error",
                quantile=quantile if family == "QUANTILE" else None, **kwargs)
        elif family == "MLP":
            assert seed in SEEDS
            torch.manual_seed(seed)
            torch.set_num_threads(2)
            model = Net(tuple(config["hidden"]))
            params = sum(p.numel() for p in model.parameters())
            assert params <= 50000
            optimizer = torch.optim.Adam(model.parameters(), lr=.001,
                                         weight_decay=.001)
            xt = torch.as_tensor(x, dtype=torch.float32)
            yt = torch.as_tensor(100.0 * y, dtype=torch.float32)
            generator = torch.Generator().manual_seed(seed)
            model.train()
            steps = 0
            for _ in range(100):
                for indices in torch.randperm(len(xt), generator=generator).split(256):
                    optimizer.zero_grad(set_to_none=True)
                    loss = torch.mean((model(xt[indices]) - yt[indices]) ** 2)
                    loss.backward()
                    optimizer.step()
                    steps += 1
            tmp = path.with_suffix(".pt.tmp")
            torch.save({"model": model.state_dict(), "width": tuple(config["hidden"]),
                        "seed": seed, "epochs": 100, "optimizer_steps": steps,
                        "parameter_count": params}, tmp)
            os.replace(tmp, path)
            model = None
        else:
            raise ValueError(family)
        if family != "MLP":
            target = train.up_label.to_numpy(int) if family == "LOGISTIC" else 100.0 * y
            model.fit(x, target)
            atomic_joblib(path, model)
        meta = {"fold": fold, "family": family, "config": config, "seed": seed,
                "quantile": quantile, "features": [FEATURES[i] for i in NO13F] if family == "HGB_NO13F" else FEATURES,
                "target_unit": "binary_return_positive" if family == "LOGISTIC" else "100_times_decimal_gross_return",
                "output_unit": "probability" if family == "LOGISTIC" else "decimal_gross_return",
                "train_rows": len(train), "train_days": train.signal_date.nunique(),
                "train_last_signal": str(train.signal_date.max().date()),
                "train_last_label_available_at": str(train.label_available_at_utc.max()),
                "scaler_sha256": sha(MODELS / f"SCALER_{fold}.joblib"),
                "model_sha256": sha(path), "library_versions": {
                    "sklearn": __import__("sklearn").__version__, "torch": torch.__version__}}
        if family == "LOGISTIC":
            meta["m_positive_decimal"] = float(y[train.up_label.to_numpy(bool)].mean())
            meta["m_nonpositive_decimal"] = float(y[~train.up_label.to_numpy(bool)].mean())
        atomic_json(meta_path, meta)
        append_fit({"key": key, "fold": fold, "family": family, "config": json.dumps(config),
                    "seed": seed, "quantile": quantile, "fit_calls": 1,
                    "train_rows": len(train), "train_last_label_available_at": meta["train_last_label_available_at"],
                    "model_sha256": meta["model_sha256"]})
    else:
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["model_sha256"] == sha(path)
    pred = predict_saved(path, family, xv, config) if len(val) else np.empty(0, dtype=float)
    output = val[["signal_date", "ticker", "experiment_security_key",
                  "gross_return_decimal", "up_label"]].copy()
    output["prediction"] = pred
    output["model_key"] = key
    atomic_parquet(PRED / f"{key}.parquet", output)
    return key, pred


def daily_loss(family: str, val: pd.DataFrame, pred: np.ndarray,
               quantile: float | None = None) -> float:
    y = val.gross_return_decimal.to_numpy(float)
    if family == "LOGISTIC":
        p = np.clip(pred, 1e-9, 1 - 1e-9)
        up = val.up_label.to_numpy(float)
        loss = -(up * np.log(p) + (1 - up) * np.log(1 - p))
    elif family == "QUANTILE":
        err = y - pred
        loss = np.maximum(quantile * err, (quantile - 1) * err)
    else:
        loss = (y - pred) ** 2
    return float(pd.DataFrame({"day": val.signal_date, "loss": loss})
                 .groupby("day").loss.mean().mean())


def family_prediction(fold: str, family: str, config: dict,
                      train: pd.DataFrame, val: pd.DataFrame,
                      scaler: dict) -> tuple[list[str], float]:
    if family == "MLP":
        fits = [fit_one(fold, family, config, train, val, scaler, seed=seed)
                for seed in SEEDS]
        predictions = np.mean([p for _, p in fits], axis=0)
        keys = [key for key, _ in fits]
    elif family == "QUANTILE":
        fits = [fit_one(fold, family, config, train, val, scaler, quantile=q)
                for q in (.1, .5, .9)]
        predictions = np.column_stack([p for _, p in fits])
        keys = [key for key, _ in fits]
    else:
        key, predictions = fit_one(fold, family, config, train, val, scaler)
        keys = [key]
    if not len(val):
        return keys, float("nan")
    if family == "QUANTILE":
        metric = float(np.mean([daily_loss(family, val, predictions[:, i], q)
                                for i, q in enumerate((.1, .5, .9))]))
    else:
        metric = daily_loss(family, val, predictions)
    return keys, metric


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["development", "post_selection"])
    args = parser.parse_args()
    manifest = json.loads((HERE / "PRE2026_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    assert sha(HERE / "PRE2026_SHARED_PANEL.parquet") == manifest["artifacts"]["PRE2026_SHARED_PANEL.parquet"]
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    panel["label_available_at_utc"] = pd.to_datetime(panel.label_available_at_utc, utc=True)
    summary_path = HERE / "DEVELOPMENT_METRICS.csv"
    if args.stage == "development":
        records = []
        for fold in ("D1", "D2"):
            train, val = load_fold(panel, fold)
            scaler = scaler_for(fold, train)
            for family, configs in GRIDS.items():
                for config in configs:
                    keys, metric = family_prediction(fold, family, config, train, val, scaler)
                    records.append({"fold": fold, "family": family,
                                    "config": json.dumps(config), "metric": metric,
                                    "validation_days": val.signal_date.nunique(),
                                    "model_keys": "|".join(keys)})
                    print(f"{fold} {family} {config} daily_loss={metric:.8g}", flush=True)
        summary = pd.DataFrame(records)
        tmp = summary_path.with_suffix(".csv.tmp")
        summary.to_csv(tmp, index=False)
        os.replace(tmp, summary_path)
        selected = {}
        for family, configs in GRIDS.items():
            sub = summary.loc[summary.family.eq(family)]
            scores = []
            for index, config in enumerate(configs):
                rows = sub.loc[sub.config.eq(json.dumps(config))]
                assert len(rows) == 2
                score = float(np.average(rows.metric, weights=rows.validation_days))
                if family in ("RIDGE", "ELASTIC"):
                    tie_rank = -config["alpha"]
                elif family == "LOGISTIC":
                    tie_rank = config["C"]
                elif family == "MLP":
                    tie_rank = sum(config["hidden"])
                else:
                    tie_rank = config["max_leaf_nodes"]
                scores.append((score, tie_rank, index, config))
            selected[family] = min(scores, key=lambda z: (z[0], z[1], z[2]))[3]
        selected["HGB_NO13F"] = selected["HGB"]
        atomic_json(HERE / "DEVELOPMENT_SELECTION.json", {
            "selection_only_D1_D2": selected,
            "metric_contract": "equal stocks within day, equal validation days; D1+D2 pooled by day count",
            "tie_rule": "first grid entry; simpler or stronger regularization",
            "no_2025_or_2026_used": True})
        for fold in ("D1", "D2"):
            train, val = load_fold(panel, fold)
            scaler = scaler_for(fold, train)
            family_prediction(fold, "HGB_NO13F", selected["HGB"], train, val, scaler)
    else:
        if not (HERE / "PRIMARY_SELECTION.json").is_file():
            raise RuntimeError("PRIMARY_SELECTION_MUST_BE_FROZEN_FROM_D1_D2_POLICY_PATHS")
        selected = json.loads((HERE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"]
        for fold in ("V25", "FINAL"):
            train, val = load_fold(panel, fold)
            scaler = scaler_for(fold, train)
            for family in ("RIDGE", "ELASTIC", "LOGISTIC", "HGB", "MLP", "QUANTILE", "HGB_NO13F"):
                family_prediction(fold, family, selected[family], train, val, scaler)
                print(f"{fold} {family} complete", flush=True)


if __name__ == "__main__":
    main()
