#!/usr/bin/env python
"""V22.081 bounded, resumable Development-only self-improvement engine.

The audit command is metadata-only.  `run` may read Development economics only
until its bounded search is over; it then opens Validation and (only if legal)
Confirmation exactly once.  It never creates broker or paper orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

import generation3r2_research as r2


NAME = "V22.081_FAST3_BOUNDED_SELF_IMPROVEMENT_ENGINE_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_081_bounded_self_improvement")
CONFIG_PATH = Path(__file__).with_name("v22_081_bounded_self_improvement_config.json")
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
FEATURES = list(r2.FEATURES)
VIX_FEATURES = list(r2.VIX_FEATURES)
SAFETY = {"research_only": True, "canonical_data_writable": False, "broker_action_allowed": False,
          "paper_broker_order_allowed": False, "order_generation_allowed": False,
          "official_adoption_allowed": False, "remote_push_allowed": False}


def _default(value):
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, np.ndarray): return value.tolist()
    return str(value)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=_default) + "\n", encoding="utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default).encode()).hexdigest()


def now() -> str: return datetime.now(timezone.utc).isoformat()


def et(value: str) -> pd.Timestamp:
    """Parse contract literals in their declared America/New_York timezone."""
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("America/New_York") if stamp.tzinfo is None else stamp.tz_convert("America/New_York")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def contract_from_metadata(canonical: Path, config: dict) -> tuple[dict, list[dict]]:
    dates, ends, audit = r2.metadata_audit(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[x]) for x in SYMBOLS if x != "SOXX"])))
    ranges = config["time_contract"]
    for role in ("development", "validation", "confirmation"):
        start, end = pd.Timestamp(ranges[role]["start"], tz="America/New_York"), pd.Timestamp(ranges[role]["end"], tz="America/New_York")
        if len(common[(common >= start) & (common <= end)]) < ranges[role]["minimum_metadata_days"]:
            raise RuntimeError(f"FAIL_DATA_CONTRACT:INADEQUATE_{role.upper()}_COVERAGE")
    c = {"research_id": NAME, "contract_status": "FROZEN_BEFORE_ECONOMIC_READS", "timezone": "America/New_York",
         "development_start": ranges["development"]["start"], "development_end": ranges["development"]["end"],
         "first_embargo_start": ranges["first_embargo"]["start"], "first_embargo_end": ranges["first_embargo"]["end"],
         "validation_start": ranges["validation"]["start"], "validation_end": ranges["validation"]["end"],
         "second_embargo_start": ranges["second_embargo"]["start"], "second_embargo_end": ranges["second_embargo"]["end"],
         "confirmation_start": ranges["confirmation"]["start"], "confirmation_end": ranges["confirmation"]["end"],
         "purge_minutes": config["purge_minutes"], "maximum_label_horizon_minutes": config["exit_horizon_minutes"],
         "random_seeds": config["random_seeds"], "max_complete_experiments": config["max_complete_experiments"],
         "confirmation_read_count": 0, "validation_read_count": 0, "vix_local_path": str(r2.VIX_PATH), **SAFETY}
    c["contract_sha256"] = digest(c)
    return c, audit


def status(output: Path, **updates) -> dict:
    path = output / "v22_081_status.json"; value = json.loads(path.read_text()) if path.exists() else {"stage": NAME, **SAFETY}
    value.update(updates); value["updated_at"] = now(); write_json(path, value); return value


def checkpoint(output: Path, **updates) -> dict:
    path = output / "v22_081_checkpoint.json"; value = json.loads(path.read_text()) if path.exists() else {"stage": NAME, "completed_experiments": 0, "validation_read_count": 0, "confirmation_read_count": 0, "active_candidates": [], **SAFETY}
    value.update(updates); value["updated_at"] = now(); write_json(path, value); return value


def append_registry(output: Path, row: dict) -> None:
    row = {"created_at": now(), **row, **SAFETY}
    with (output / "experiment_registry.jsonl").open("a", encoding="utf-8") as handle: handle.write(json.dumps(row, default=_default, sort_keys=True) + "\n")


def write_registry(output: Path, rows: list[dict]) -> None:
    """Atomically reconcile retention state: at most three rows say RETAIN."""
    temporary = output / "experiment_registry.jsonl.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows: handle.write(json.dumps(row, default=_default, sort_keys=True) + "\n")
    temporary.replace(output / "experiment_registry.jsonl")


def registry(output: Path) -> list[dict]:
    path = output / "experiment_registry.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def audit(output: Path, canonical: Path) -> None:
    config = load_config(); contract, source = contract_from_metadata(canonical, config); output.mkdir(parents=True, exist_ok=True)
    write_json(output / "v22_081_split_contract.json", contract)
    (output / "v22_081_split_contract_sha256.txt").write_text(contract["contract_sha256"] + "\n", encoding="utf-8")
    write_json(output / "v22_081_feature_contract.json", {"features": FEATURES + VIX_FEATURES, "maximum_source_timestamp": "decision_timestamp - 1 minute", "completed_bar_only": True, "VIX": "prior-day local PIT features only when audit passes", **SAFETY})
    write_json(output / "v22_081_label_contract.json", {"opportunity": "real SOXL/SOXS 60-minute best net return after 10bps > 0.003", "direction": "SOXX 60-minute direction conditional on opportunity", "execution": "LONG=SOXL, SHORT=SOXS, FLAT=NO_TRADE; real ETF next valid open", "cost_bps": config["cost_bps"], "delay_minutes": config["delay_minutes"], **SAFETY})
    write_json(output / "v22_081_source_metadata_audit.json", {"economic_values_read": False, "all_six_symbols": source, "vix_available": r2.VIX_PATH.is_file(), "vix_blocker": None if r2.VIX_PATH.is_file() else "LOCAL_PRIOR_DAY_VIX_FEATURES_MISSING", **SAFETY})
    checkpoint(output, state="SPLIT_FROZEN_AWAITING_DEVELOPMENT", contract_sha256=contract["contract_sha256"], next_exact_action="Run bounded Development-only experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_081_bounded_self_improvement.py --phase run --output-dir {output}")
    status(output, state="SPLIT_FROZEN", final_status=None, validation_read_count=0, confirmation_read_count=0, contract_sha256=contract["contract_sha256"])


def _pipeline(kind: str, seed: int, params: dict) -> Pipeline:
    if kind == "logistic": model = LogisticRegression(C=params["c"], max_iter=250, random_state=seed)
    elif kind == "elastic_net": model = LogisticRegression(C=params["c"], penalty="elasticnet", solver="saga", l1_ratio=params["l1_ratio"], max_iter=300, random_state=seed)
    elif kind == "tree": model = DecisionTreeClassifier(max_depth=params["depth"], min_samples_leaf=params["min_leaf"], random_state=seed)
    elif kind == "random_forest": model = RandomForestClassifier(n_estimators=params["trees"], max_depth=params["depth"], min_samples_leaf=params["min_leaf"], max_features=.75, n_jobs=-1, random_state=seed)
    elif kind == "hgb": model = HistGradientBoostingClassifier(max_iter=params["iterations"], max_leaf_nodes=params["leaves"], min_samples_leaf=params["min_leaf"], learning_rate=.05, l2_regularization=params["l2"], random_state=seed)
    else: raise ValueError(kind)
    steps = [("impute", SimpleImputer(strategy="median"))]
    if kind in ("logistic", "elastic_net"): steps.append(("scale", StandardScaler()))
    return Pipeline(steps + [("model", model)])


def _fit_prob(kind: str, seed: int, params: dict, train: pd.DataFrame, test: pd.DataFrame, features: list[str], label: str) -> tuple[np.ndarray, dict]:
    y = train[label].astype(int)
    if y.nunique() < 2: return np.full(len(test), float(y.mean() if len(y) else 0.0)), {"constant": True}
    stride = max(1, int(np.ceil(len(train) / 45_000))); fitted = train.iloc[::stride]
    model = _pipeline(kind, seed, params); model.fit(fitted[features], fitted[label].astype(int)); p = model.predict_proba(test[features])[:, 1]
    final = model.named_steps["model"]; importance = getattr(final, "coef_", getattr(final, "feature_importances_", np.zeros(len(features))))
    importance = np.asarray(importance).reshape(-1); return p, {f: float(v) for f, v in zip(features, importance)}


def make_action(frame: pd.DataFrame, p_opp: np.ndarray, p_up: np.ndarray, cfg: dict) -> pd.DataFrame:
    out = frame[["decision_timestamp", "calendar_date", "soxx_vol_60m"] + [f"{s}_gross_60m_delay{d}" for s in ("soxl", "soxs") for d in (0, 1, 3, 5)]].copy()
    out["p_opportunity"], out["p_direction_up"] = p_opp, p_up
    long = (p_opp >= cfg["opportunity_threshold"]) & (p_up >= .5 + cfg["direction_margin"])
    short = (p_opp >= cfg["opportunity_threshold"]) & (p_up <= .5 - cfg["direction_margin"])
    out["action"] = np.where(long, "LONG", np.where(short, "SHORT", "FLAT")); out["execution_etf"] = np.where(long, "SOXL", np.where(short, "SOXS", None))
    for delay in (0, 1, 3, 5): out[f"gross_delay{delay}"] = np.where(long, out[f"soxl_gross_60m_delay{delay}"], np.where(short, out[f"soxs_gross_60m_delay{delay}"], np.nan))
    return out


def nonoverlap(frame: pd.DataFrame, horizon: int = 60) -> pd.DataFrame:
    source = frame[frame.action.ne("FLAT") & frame.gross_delay1.notna()].sort_values("decision_timestamp", kind="mergesort")
    keep, next_free = [], pd.Timestamp.min.tz_localize("America/New_York")
    for index, row in source.iterrows():
        if row.decision_timestamp >= next_free: keep.append(index); next_free = row.decision_timestamp + pd.Timedelta(minutes=horizon)
    return source.loc[keep].copy()


def metrics(frame: pd.DataFrame, cfg: dict, weights: dict) -> dict:
    raw_count = int(frame.action.ne("FLAT").sum()); trades = nonoverlap(frame); no_trade = 1.0 - raw_count / len(frame) if len(frame) else 1.0
    base = {"trade_count": int(len(trades)), "no_trade_rate": no_trade, "turnover": raw_count / max(len(frame), 1), "net_expectancy": None, "median_net_return": None, "max_drawdown": None, "concentration": None, "year_stability": None, "regime_stability": None, "top_signal_lift": None}
    for cost in (5, 10, 20, 30):
        for delay in (0, 1, 3, 5):
            series = trades[f"gross_delay{delay}"] - cost / 10_000 if len(trades) else pd.Series(dtype=float)
            base[f"mean_net_{cost}bps_delay{delay}"] = float(series.mean()) if len(series) else None
    if trades.empty: return {**base, "seed_stability": 0.0, "weight_stability": 0.0, "calibration_score": None, "score": -9.0}
    ret = trades.gross_delay1 - .001; daily = ret.groupby(trades.calendar_date).sum(); dd = (daily.cumsum() - daily.cumsum().cummax()).min()
    positive = ret.clip(lower=0); total_pos = positive.sum(); monthly = ret.groupby(pd.to_datetime(trades.calendar_date).dt.to_period("M")).sum(); annual = ret.groupby(pd.to_datetime(trades.calendar_date).dt.year).sum()
    regime = trades.soxx_vol_60m >= trades.soxx_vol_60m.median(); reg = ret.groupby(regime).mean()
    actual = frame.get("actual_opportunity", pd.Series(0, index=frame.index)); top = frame.p_opportunity >= frame.p_opportunity.quantile(.90)
    lift = actual[top].mean() / actual.mean() if top.any() and actual.mean() else None
    base.update({"net_expectancy": float(ret.mean()), "median_net_return": float(monthly.median()), "max_drawdown": float(abs(dd)), "concentration": float(positive.nlargest(5).sum() / total_pos) if total_pos else 1.0, "year_stability": float((annual > 0).mean()), "regime_stability": float((reg > 0).mean()), "top_signal_lift": float(lift) if lift is not None else None})
    base["calibration_score"] = float(np.mean((frame.p_opportunity - actual) ** 2))
    base["weight_stability"] = float(np.mean(np.abs(list(weights.values())) > 1e-10)) if weights else 0.0
    stress = [base[f"mean_net_{c}bps_delay{d}"] for c in (10, 20) for d in (1, 3, 5) if base[f"mean_net_{c}bps_delay{d}"] is not None]
    base["seed_stability"] = float(np.mean(np.asarray(stress) > 0)) if stress else 0.0
    base["score"] = float(100 * base["median_net_return"] + 30 * base["net_expectancy"] + 0.35 * base["year_stability"] + .20 * base["regime_stability"] + .10 * base["seed_stability"] - .8 * base["max_drawdown"] - .25 * base["concentration"] - .01 * cfg["complexity"])
    return base


def mutation(index: int, completed: list[dict], config: dict) -> dict:
    rng = np.random.default_rng(config["random_seeds"][index % len(config["random_seeds"])] + index)
    parent = max((x for x in completed if x.get("decision") == "RETAIN"), key=lambda x: x.get("score", -9), default=None)
    families = config["model_families"]; kind = families[index % len(families)] if parent is None or index % 4 == 0 else parent["model_type"]
    grids = {"c": [.05, .15, .4, 1.], "l1_ratio": [.15, .5, .85], "depth": [2, 3, 4], "min_leaf": [250, 500, 1000], "trees": [32, 64], "iterations": [30, 50, 70], "leaves": [5, 9, 13], "l2": [1., 5., 10.]}
    if parent is None:
        n = int(rng.integers(config["feature_count_range"][0], config["feature_count_range"][1] + 1)); chosen = sorted(rng.choice(FEATURES, size=min(n, len(FEATURES)), replace=False).tolist())
        use_vix = bool(r2.VIX_PATH.is_file() and index % 5 == 0)
        if use_vix: chosen += VIX_FEATURES
        params = {key: float(rng.choice(values)) if key in ("c", "l1_ratio", "l2") else int(rng.choice(values)) for key, values in grids.items()}
        opportunity, margin = float(rng.choice([.35, .40, .45, .50])), float(rng.choice([.02, .04, .06, .08]))
        changed = {"root_configuration": True}
    else:
        # A child starts with its parent's complete contract.  It changes no
        # more than one model family, three hyperparameters, two thresholds,
        # and one feature switch, all from Development internal OOS evidence.
        chosen, params = list(parent["feature_names"]), dict(parent["params"])
        keys = rng.choice(list(grids), size=min(3, len(grids)), replace=False)
        for key in keys: params[key] = float(rng.choice(grids[key])) if key in ("c", "l1_ratio", "l2") else int(rng.choice(grids[key]))
        if chosen and rng.random() < .5:
            chosen[int(rng.integers(0, len(chosen)))] = str(rng.choice(FEATURES))
            chosen = list(dict.fromkeys(chosen))[:40]
        opportunity, margin = float(rng.choice([.35, .40, .45, .50])), float(rng.choice([.02, .04, .06, .08]))
        changed = {"model_family_changes": int(kind != parent["model_type"]), "hyperparameter_changes": len(keys), "threshold_changes": 2, "feature_switches": 1}
    return {"model_type": kind, "feature_names": chosen[:40], "opportunity_threshold": opportunity, "direction_margin": margin, "params": params, "complexity": families.index(kind) + 1 + int(any(x in VIX_FEATURES for x in chosen)), "parent_experiment_id": parent.get("experiment_id") if parent else None, "selection_source": "DEVELOPMENT_INTERNAL_CHRONOLOGICAL_OOS_MUTATION", "mutation_contract_version": "R1_BOUNDED_1_FAMILY_3_PARAMS_2_THRESHOLDS_1_FEATURE", "mutation_changes": changed}


def experiment_window(samples: pd.DataFrame, index: int, config: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    dates = np.array(sorted(pd.DatetimeIndex(samples.calendar_date.unique())))
    rng = np.random.default_rng(config["random_seeds"][index % len(config["random_seeds"])] + index)
    train_days = int(rng.choice(config["inner_train_days"])); oos_days = int(rng.choice(config["inner_oos_days"])); needed = train_days + config["purge_minutes"] // 60 // 6 + oos_days
    if len(dates) < needed: raise RuntimeError("FAIL_DATA_CONTRACT:INSUFFICIENT_DEVELOPMENT_DAYS")
    start = int(rng.integers(0, len(dates) - needed + 1)); train_days_index = dates[start:start + train_days]; oos_dates = dates[start + needed - oos_days:start + needed]
    train = samples[samples.calendar_date.isin(train_days_index)].copy(); test = samples[samples.calendar_date.isin(oos_dates)].copy()
    # Purge future labels at the train/OOS boundary, independently of sampled day granularity.
    cutoff = test.decision_timestamp.min() - pd.Timedelta(minutes=config["purge_minutes"]); train = train[train.decision_timestamp < cutoff]
    return train, test, {"train_start": train.decision_timestamp.min(), "train_end": train.decision_timestamp.max(), "embargo_start": cutoff, "embargo_end": test.decision_timestamp.min(), "oos_start": test.decision_timestamp.min(), "oos_end": test.decision_timestamp.max()}


def evaluate(cfg: dict, train: pd.DataFrame, test: pd.DataFrame, seed: int) -> tuple[dict, dict]:
    features = cfg["feature_names"]; p_opp, iw_opp = _fit_prob(cfg["model_type"], seed, cfg["params"], train, test, features, "opportunity_60m")
    eligible = train[train.opportunity_60m.eq(1)]; p_up, iw_dir = _fit_prob(cfg["model_type"], seed + 17, cfg["params"], eligible, test, features, "direction_up_conditional")
    frame = make_action(test, p_opp, p_up, cfg); frame["actual_opportunity"] = test.opportunity_60m.to_numpy(); weights = {f: (iw_opp.get(f, 0.0) + iw_dir.get(f, 0.0)) / 2 for f in features}
    return metrics(frame, cfg, weights), weights


def retain(records: list[dict]) -> list[str]:
    eligible = [x for x in records if x.get("failure_reason") is None and x.get("trade_count", 0) >= 20]
    return [x["experiment_id"] for x in sorted(eligible, key=lambda x: (-x.get("score", -9), x["complexity"], x["experiment_id"]))[:3]]


def _development_data(contract: dict, canonical: Path) -> tuple[pd.DataFrame, str | None]:
    start, end = et(contract["development_start"]), et(contract["development_end"])
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}; samples = r2.build_samples(data); blocker = None
    if r2.VIX_PATH.is_file(): samples = r2._vix_for_development(samples)
    else: blocker = "LOCAL_PRIOR_DAY_VIX_FEATURES_MISSING; VIX family excluded without substitution"
    return samples, blocker


def development(output: Path, canonical: Path, max_new: int) -> bool:
    contract = json.loads((output / "v22_081_split_contract.json").read_text(encoding="utf-8")); config = load_config(); state = checkpoint(output)
    if state.get("validation_read_count", 0) or state.get("confirmation_read_count", 0): raise RuntimeError("FAIL_LEAKAGE_DETECTED:HOLDOUT_ALREADY_OPENED")
    records = registry(output)
    invalid_reason = "INVALID_IMPLEMENTATION_DEFECT: pre-R1 mutation did not enforce the bounded-change contract; preserved but ineligible for champion selection"
    changed_prior = False
    for record in records:
        if record.get("mutation_contract_version") is None and record.get("failure_reason") is None:
            record["failure_reason"], record["decision"], changed_prior = invalid_reason, "FAILURE", True
    if changed_prior:
        write_registry(output, records)
        checkpoint(output, state="DEVELOPMENT_SEARCH_IN_PROGRESS", completed_experiments=len(records), active_candidates=[], known_failures=[invalid_reason], next_exact_action="Run compliant bounded mutations after preserved invalid rows.")
    complete = records
    remaining = max(0, config["max_complete_experiments"] - len(records)); target = min(remaining, max_new)
    if target:
        samples, vix_blocker = _development_data(contract, canonical)
        for offset in range(target):
            i = len(complete); seed = config["random_seeds"][i % len(config["random_seeds"])] + i; cfg = mutation(i, complete, config); eid = f"E{i + 1:03d}"
            try:
                train, test, window = experiment_window(samples, i, config)
                if len(train) < 2000 or len(test) < 100: raise RuntimeError("INSUFFICIENT_INNER_SAMPLE")
                result, weights = evaluate(cfg, train, test, seed); row = {"experiment_id": eid, "random_seed": seed, **window, "label_contract_hash": digest(json.loads((output / "v22_081_label_contract.json").read_text())), "feature_contract_hash": digest(json.loads((output / "v22_081_feature_contract.json").read_text())), "model_contract_hash": digest(cfg), "feature_count": len(cfg["feature_names"]), "model_type": cfg["model_type"], "factor_weights_or_importance": weights, "thresholds": {"opportunity": cfg["opportunity_threshold"], "direction_margin": cfg["direction_margin"]}, "cost_bps": config["cost_bps"], "delay_minutes": config["delay_minutes"], **cfg, **result, "failure_reason": None, "decision": "PENDING_RETENTION", "vix_blocker": vix_blocker}
            except Exception as exc:
                row = {"experiment_id": eid, "parent_experiment_id": cfg.get("parent_experiment_id"), "random_seed": seed, "feature_count": len(cfg["feature_names"]), "model_type": cfg["model_type"], "factor_weights_or_importance": {}, "thresholds": {"opportunity": cfg["opportunity_threshold"], "direction_margin": cfg["direction_margin"]}, "cost_bps": config["cost_bps"], "delay_minutes": config["delay_minutes"], "failure_reason": str(exc), "decision": "FAILURE", **cfg}
            complete.append(row); active = retain(complete)
            for record in complete:
                record["decision"] = "FAILURE" if record.get("failure_reason") else ("RETAIN" if record["experiment_id"] in active else "PRUNE_UNSTABLE_OR_INFERIOR")
            write_registry(output, complete)
            checkpoint(output, state="DEVELOPMENT_SEARCH_IN_PROGRESS", completed_experiments=len(complete), active_candidates=active, last_experiment_id=eid, vix_blocker=vix_blocker, next_exact_action="Continue Development internal OOS experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_081_bounded_self_improvement.py --phase run --output-dir {output}")
            status(output, state="DEVELOPMENT_SEARCH_IN_PROGRESS", final_status=None, validation_read_count=0, confirmation_read_count=0, completed_experiments=len(complete), active_candidates=active)
    return len(complete) >= config["max_complete_experiments"]


def holdout_samples(canonical: Path, contract: dict, role: str) -> pd.DataFrame:
    start, end = et(contract[f"{role}_start"]), et(contract[f"{role}_end"]); data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}; samples = r2.build_samples(data)
    return r2._vix_for_development(samples) if r2.VIX_PATH.is_file() else samples


def champion_and_holdouts(output: Path, canonical: Path) -> None:
    contract = json.loads((output / "v22_081_split_contract.json").read_text()); records = registry(output); viable = [x for x in records if x.get("decision") == "RETAIN"]
    if not viable: terminal(output, "FAIL_NO_ROBUST_EDGE", "NO_RETAINED_DEVELOPMENT_CANDIDATE", None, 0, 0); return
    best = sorted(viable, key=lambda x: (-x["score"], x["complexity"], x["experiment_id"]))[0]; cfg = {k: best[k] for k in ("model_type", "feature_names", "opportunity_threshold", "direction_margin", "params", "complexity")}; write_json(output / "champion_config.json", {"status": "FROZEN_BEFORE_VALIDATION", "experiment_id": best["experiment_id"], "config": cfg, "config_sha256": digest(cfg), "contract_sha256": contract["contract_sha256"], **SAFETY})
    dev, _ = _development_data(contract, canonical); validation = holdout_samples(canonical, contract, "validation"); metric, weights = evaluate(cfg, dev[dev.decision_timestamp < et(contract["development_end"]) - pd.Timedelta(minutes=contract["purge_minutes"])], validation, 20260881)
    validation_pass = bool(metric["trade_count"] >= 100 and metric["mean_net_10bps_delay1"] is not None and metric["mean_net_10bps_delay1"] > 0 and metric["year_stability"] >= .50 and metric["regime_stability"] >= .50 and metric["mean_net_20bps_delay1"] is not None and metric["mean_net_20bps_delay1"] > -.001 and metric["max_drawdown"] <= .25 and metric["concentration"] < .70)
    write_json(output / "v22_081_validation_metrics.json", {"read_count": 1, "candidate": best["experiment_id"], "metrics": metric, "weights": weights, "passed": validation_pass, **SAFETY}); checkpoint(output, validation_read_count=1, state="VALIDATION_OPENED_ONCE")
    if not validation_pass: terminal(output, "FAIL_NO_ROBUST_EDGE", "ONE_TIME_VALIDATION_FAILED", best, 1, 0, metric); return
    combined = pd.concat([dev, validation], ignore_index=True); confirmation = holdout_samples(canonical, contract, "confirmation"); cm, cw = evaluate(cfg, combined[combined.decision_timestamp < et(contract["confirmation_start"]) - pd.Timedelta(minutes=contract["purge_minutes"])], confirmation, 20260981)
    cp = bool(cm["trade_count"] >= 100 and cm["mean_net_10bps_delay1"] is not None and cm["mean_net_10bps_delay1"] > 0 and cm["mean_net_20bps_delay1"] is not None and cm["mean_net_20bps_delay1"] > -.001 and cm["max_drawdown"] <= .25 and cm["concentration"] < .70)
    write_json(output / "v22_081_confirmation_metrics.json", {"read_count": 1, "metrics": cm, "weights": cw, "passed": cp, **SAFETY}); terminal(output, "PASS_V22_081_CONFIRMATION_ACCEPTED" if cp else "FAIL_CONFIRMATION", "CONFIRMATION_ACCEPTED_ZERO_ORDER_SHADOW_ELIGIBLE" if cp else "ONE_TIME_CONFIRMATION_FAILED", best, 1, 1, cm)


def terminal(output: Path, final_status: str, decision: str, best: dict | None, validation_count: int, confirmation_count: int, final_metrics: dict | None = None) -> None:
    records = registry(output); best = best or {}; final_metrics = final_metrics or {}
    validation = json.loads((output / "v22_081_validation_metrics.json").read_text()) if (output / "v22_081_validation_metrics.json").exists() else {}
    confirmation = json.loads((output / "v22_081_confirmation_metrics.json").read_text()) if (output / "v22_081_confirmation_metrics.json").exists() else {}
    validation_result = "PASS" if validation.get("passed") is True else ("FAIL" if validation_count else "NOT_OPENED")
    confirmation_result = "PASS" if confirmation.get("passed") is True else ("FAIL" if confirmation_count else "NOT_OPENED")
    summary = {"FINAL_STATUS": final_status, "FINAL_DECISION": decision, "STOP_REASON": decision, "EXPERIMENT_COUNT": len(records), "BEST_MODEL_TYPE": best.get("model_type"), "BEST_FEATURE_COUNT": best.get("feature_count"), "BEST_FEATURES": best.get("feature_names", []), "BEST_FACTOR_WEIGHTS": best.get("factor_weights_or_importance", {}), "BEST_THRESHOLDS": best.get("thresholds", {}), "DEVELOPMENT_OOS_METRICS": {k: best.get(k) for k in ("net_expectancy", "median_net_return", "max_drawdown", "top_signal_lift", "trade_count", "seed_stability", "regime_stability", "weight_stability")}, "VALIDATION_READ_COUNT": validation_count, "VALIDATION_RESULT": validation_result, "CONFIRMATION_READ_COUNT": confirmation_count, "CONFIRMATION_RESULT": confirmation_result, "MEDIAN_NET_RETURN_10BPS": final_metrics.get("median_net_return", best.get("median_net_return")), "MEDIAN_NET_RETURN_20BPS": final_metrics.get("mean_net_20bps_delay1", best.get("mean_net_20bps_delay1")), "MAX_DRAWDOWN": final_metrics.get("max_drawdown", best.get("max_drawdown")), "TOP_SIGNAL_LIFT": final_metrics.get("top_signal_lift", best.get("top_signal_lift")), "TRADE_COUNT": final_metrics.get("trade_count", best.get("trade_count", 0)), "NO_TRADE_RATE": final_metrics.get("no_trade_rate", best.get("no_trade_rate")), "SEED_STABILITY": final_metrics.get("seed_stability", best.get("seed_stability")), "REGIME_STABILITY": final_metrics.get("regime_stability", best.get("regime_stability")), "WEIGHT_STABILITY": final_metrics.get("weight_stability", best.get("weight_stability")), "PAPER_SHADOW_ALLOWED": final_status == "PASS_V22_081_CONFIRMATION_ACCEPTED", "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False, "RESULT_DIRECTORY": str(output), "SUMMARY_PATH": str(output / "v22_081_summary.json"), "RECOMMENDED_NEXT_COMMAND": "NONE_V22_081_RESEARCH_STOPPED", **SAFETY}
    write_json(output / "v22_081_summary.json", summary); (output / "v22_081_report.md").write_text(f"# {NAME}\n\nFINAL_STATUS={final_status}\n\nFINAL_DECISION={decision}\n\nExperiments recorded: {len(records)}. Validation reads: {validation_count}. Confirmation reads: {confirmation_count}.\n", encoding="utf-8")
    checkpoint(output, state="TERMINAL", completed_experiments=len(records), validation_read_count=validation_count, confirmation_read_count=confirmation_count, next_exact_action="None; legal terminal condition reached.", exact_resume_command="NONE_V22_081_RESEARCH_STOPPED")
    status(output, state="TERMINAL", final_status=final_status, final_decision=decision, validation_read_count=validation_count, confirmation_read_count=confirmation_count)
    (output / "V22_081_DONE.flag").write_text(final_status + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("audit", "run"), required=True); p.add_argument("--output-dir", default=str(OUT)); p.add_argument("--canonical-root", default=str(ROOT)); p.add_argument("--max-new", type=int, default=5); args = p.parse_args(); output = Path(args.output_dir)
    if args.phase == "audit": audit(output, Path(args.canonical_root)); print("FINAL_STATUS=SPLIT_FROZEN_AWAITING_DEVELOPMENT")
    else:
        if not (output / "v22_081_split_contract.json").exists(): raise RuntimeError("SPLIT_CONTRACT_MISSING_RUN_AUDIT_FIRST")
        done = development(output, Path(args.canonical_root), args.max_new)
        if done: champion_and_holdouts(output, Path(args.canonical_root))
        print("FINAL_STATUS=" + (json.loads((output / "v22_081_status.json").read_text()).get("final_status") or "DEVELOPMENT_SEARCH_IN_PROGRESS"))


if __name__ == "__main__": main()
