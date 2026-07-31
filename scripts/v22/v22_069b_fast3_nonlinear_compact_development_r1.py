from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor, export_text

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / ".local_results" / "v22" / "V22.069A_FAST_RESEARCH_CONTRACT_R1" / "v22_069a_fast_frozen_research_contract.json"
EXPECTED_CONTRACT_SHA256 = "7facdfdae38e5b7d925f2cae4ad0216fc14b8afdfe3da27f3ec6a9f096c28013"
OUT = REPO / ".local_results" / "v22" / "V22.069B_FAST3_NONLINEAR_COMPACT_DEVELOPMENT_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m")
SYMS = ["QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"]
FEATURES = ["PREMARKET_CUM_RETURN", "PREMARKET_MAX_DRAWDOWN", "PREMARKET_REALIZED_VOLATILITY"]
REQUIRED_COLUMNS = ["timestamp_et", "open", "close"]
ROUND_TRIP_COST = 0.001


def stable_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def load_contract():
    if not CONTRACT.is_file() or sha256_file(CONTRACT) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("FROZEN_RESEARCH_CONTRACT_SHA256_MISMATCH")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("symbols") != SYMS or contract.get("features") != FEATURES:
        raise RuntimeError("FROZEN_RESEARCH_CONTRACT_CONTENT_MISMATCH")
    return contract


def development_paths(months):
    paths = []
    for month in months:
        year, number = month.split("-")
        for symbol in SYMS:
            paths.append(ROOT / "canonical" / f"symbol={symbol}" / f"year={year}" / f"month={number}" / "data.parquet")
    return paths


def numeric(value):
    return pd.api.types.is_numeric_dtype(value)


def build_events(months):
    events, exclusions = [], []
    for path in development_paths(months):
        if not path.is_file():
            exclusions.append({"reason": "MISSING_DEVELOPMENT_PARTITION", "count": 1})
            continue
        symbol = path.parents[2].name.split("=", 1)[1]
        table = pq.read_table(path, columns=REQUIRED_COLUMNS)
        frame = table.to_pandas()
        if not all(column in frame for column in REQUIRED_COLUMNS) or not numeric(frame["open"]) or not numeric(frame["close"]):
            exclusions.append({"reason": "INVALID_DEVELOPMENT_SCHEMA", "count": 1})
            continue
        timestamp = pd.to_datetime(frame["timestamp_et"], utc=True).dt.tz_convert("America/New_York")
        frame = frame.assign(timestamp=timestamp).dropna(subset=["timestamp", "open", "close"])
        frame["date"] = frame.timestamp.dt.date.astype(str)
        for date, day in frame.groupby("date", sort=True):
            day = day.sort_values("timestamp")
            pre = day[(day.timestamp.dt.time >= pd.Timestamp("04:00").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:25").time())]
            coverage = pre.timestamp.dt.floor("min").nunique() / 326
            if coverage < 0.80:
                exclusions.append({"reason": "PREMARKET_COVERAGE_LT_80_PERCENT", "count": 1})
                continue
            entry = day[(day.timestamp.dt.time >= pd.Timestamp("09:30").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:32").time())]
            exit_ = day[(day.timestamp.dt.time >= pd.Timestamp("15:58").time()) & (day.timestamp.dt.time <= pd.Timestamp("16:00").time())]
            if entry.empty:
                exclusions.append({"reason": "MISSING_ENTRY", "count": 1})
                continue
            if exit_.empty:
                exclusions.append({"reason": "MISSING_EXIT", "count": 1})
                continue
            closes = pre.close.astype(float).to_numpy()
            log_returns = np.diff(np.log(closes))
            events.append({"date": date, "symbol": symbol, "PREMARKET_CUM_RETURN": closes[-1] / closes[0] - 1, "PREMARKET_MAX_DRAWDOWN": np.min(closes / np.maximum.accumulate(closes) - 1), "PREMARKET_REALIZED_VOLATILITY": float(np.std(log_returns, ddof=0)), "target_return": float(exit_.iloc[-1].close) / float(entry.iloc[0].open) - 1})
    event_frame = pd.DataFrame(events)
    exclusions = pd.DataFrame(exclusions).groupby("reason", as_index=False)["count"].sum() if exclusions else pd.DataFrame(columns=["reason", "count"])
    return event_frame.sort_values(["date", "symbol"]).reset_index(drop=True), exclusions


def expanding_folds(dates):
    blocks = np.array_split(np.array(sorted(dates)), 6)
    return [(index + 1, list(np.concatenate(blocks[:index + 1])), list(blocks[index + 1])) for index in range(5) if len(blocks[index + 1])]


def candidate_specs():
    yield "Ridge", {"alpha": 1.0}
    for depth in (1, 2, 3):
        for leaf in (20, 50, 100):
            yield "DecisionTreeRegressor", {"max_depth": depth, "min_samples_leaf": leaf, "random_state": 20260731}


def make_model(name, params):
    return make_pipeline(StandardScaler(), Ridge(**params)) if name == "Ridge" else DecisionTreeRegressor(**params)


def fold_spread(target, prediction):
    if len(target) < 5:
        return np.nan
    order = np.lexsort((np.arange(len(prediction)), prediction))
    quintile = max(1, math.ceil(len(prediction) * .2))
    return float(np.mean(target[order[-quintile:]]) - np.mean(target[order[:quintile]]))


def score_candidates(events):
    dates = sorted(events.date.unique())
    folds = expanding_folds(dates)
    rows = []
    for name, params in candidate_specs():
        fold_metrics = []
        for fold_id, train_dates, test_dates in folds:
            train = events[events.date.isin(train_dates)]
            test = events[events.date.isin(test_dates)]
            if len(train) < 100 or len(test) < 5:
                continue
            model = make_model(name, params).fit(train[FEATURES], train.target_return)
            prediction = model.predict(test[FEATURES])
            ic = spearmanr(test.target_return, prediction).statistic
            fold_metrics.append({"fold_id": fold_id, "ic": float(ic) if np.isfinite(ic) else np.nan, "spread_gross": fold_spread(test.target_return.to_numpy(), prediction), "train_event_count": len(train), "test_event_count": len(test), "train_end_date": max(train_dates), "test_start_date": min(test_dates), "test_end_date": max(test_dates)})
        valid = [metric for metric in fold_metrics if np.isfinite(metric["ic"])]
        rows.append({"model_family": name, "parameters": json.dumps(params, sort_keys=True), "mean_oof_spearman_ic": float(np.mean([metric["ic"] for metric in valid])) if valid else np.nan, "mean_oof_top_bottom_spread_gross": float(np.mean([metric["spread_gross"] for metric in valid])) if valid else np.nan, "mean_oof_top_bottom_spread_net_10bps": float(np.mean([metric["spread_gross"] - ROUND_TRIP_COST for metric in valid])) if valid else np.nan, "valid_fold_count": len(valid), "fold_metrics": fold_metrics})
    return rows, folds


def best_tree(metrics):
    trees = [row for row in metrics if row["model_family"] == "DecisionTreeRegressor"]
    return sorted(trees, key=lambda row: (-np.nan_to_num(row["mean_oof_spearman_ic"], nan=-np.inf), -np.nan_to_num(row["mean_oof_top_bottom_spread_gross"], nan=-np.inf), json.loads(row["parameters"])["max_depth"], -json.loads(row["parameters"])["min_samples_leaf"]))[0]


def tree_json(events, metric):
    params = json.loads(metric["parameters"])
    model = DecisionTreeRegressor(**params).fit(events[FEATURES], events.target_return)
    return {"model_family": "DecisionTreeRegressor", "parameters": params, "feature_names": FEATURES, "tree_text": export_text(model, feature_names=FEATURES), "node_count": int(model.tree_.node_count), "full_development_event_count": len(events)}


def publish(stage):
    if OUT.exists(): shutil.rmtree(OUT)
    os.replace(stage, OUT)


def run():
    contract = load_contract()
    months = contract["split"]["development_months"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".069b_", dir=OUT.parent))
    try:
        events, exclusions = build_events(months)
        metrics, folds = score_candidates(events) if not events.empty else ([], [])
        best = best_tree(metrics) if metrics else None
        pass_gate = bool(best and best["mean_oof_spearman_ic"] > 0 and best["mean_oof_top_bottom_spread_net_10bps"] > 0 and best["valid_fold_count"] >= 3)
        model = tree_json(events, best) if best else {"model_family": None, "parameters": {}, "feature_names": FEATURES, "tree_text": "", "node_count": 0, "full_development_event_count": len(events)}
        model_hash = sha256_bytes(stable_bytes(model))
        fold_rows = [{"fold_id": fold_id, "train_start_date": min(train), "train_end_date": max(train), "test_start_date": min(test), "test_end_date": max(test)} for fold_id, train, test in folds]
        identity = [{"relative_path": str(path.relative_to(ROOT)), "file_size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns} for path in development_paths(months) if path.is_file()]
        summary = {"final_status": "PASS" if pass_gate else "FAIL", "final_decision": "DEVELOPMENT_NONLINEAR_COMPACT_MODEL_FROZEN_FOR_V22_069C" if pass_gate else "DEVELOPMENT_EDGE_NOT_ESTABLISHED", "development_event_count": len(events), "excluded_event_count": int(exclusions["count"].sum()) if not exclusions.empty else 0, "exclusion_reason_counts": dict(zip(exclusions.reason, exclusions["count"])) if not exclusions.empty else {}, "development_start_date": min(events.date) if not events.empty else None, "development_end_date": max(events.date) if not events.empty else None, "ridge_oof_spearman_ic": next((row["mean_oof_spearman_ic"] for row in metrics if row["model_family"] == "Ridge"), None), "best_model_parameters": model["parameters"], "best_model_oof_spearman_ic": best["mean_oof_spearman_ic"] if best else None, "best_model_oof_top_bottom_spread_gross": best["mean_oof_top_bottom_spread_gross"] if best else None, "best_model_oof_top_bottom_spread_net_10bps": best["mean_oof_top_bottom_spread_net_10bps"] if best else None, "valid_fold_count": best["valid_fold_count"] if best else 0, "validation_row_read_count": 0, "confirmation_row_read_count": 0, "best_model_sha256": model_hash, "eligible_for_v22_069c": pass_gate, "prospective_shadow_allowed": False, "paper_action_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "order_output_count": 0}
        feature_contract = {"frozen_research_contract_path": str(CONTRACT), "frozen_research_contract_sha256": EXPECTED_CONTRACT_SHA256, "development_months": months, "features": FEATURES, "premarket_window_et": "04:00-09:25", "entry_window_et": "09:30-09:32 first valid open", "exit_window_et": "15:58-16:00 last valid close", "round_trip_cost": ROUND_TRIP_COST, "validation_row_read_count": 0, "confirmation_row_read_count": 0}
        manifest = {"allowed_outputs": ["summary.json", "manifest.json", "readme.txt", "event_build_summary.csv", "fold_definition.csv", "candidate_metrics.csv", "best_model.json", "best_model.sha256", "feature_contract.json", "development_data_fingerprint.json", "integrity_checks.csv"], "contract_sha256_verified": True, "development_partition_count": len(identity), "no_event_dataset_output": True, "no_row_prediction_output": True}
        checks = [{"check": "contract_sha256", "passed": True, "detail": EXPECTED_CONTRACT_SHA256}, {"check": "development_only", "passed": True, "detail": f"{len(months)} contract development months only"}, {"check": "validation_rows_read", "passed": True, "detail": "0"}, {"check": "confirmation_rows_read", "passed": True, "detail": "0"}, {"check": "all_trading_permissions_false", "passed": True, "detail": "true"}]
        (stage / "summary.json").write_bytes(stable_bytes(summary)); (stage / "manifest.json").write_bytes(stable_bytes(manifest)); (stage / "readme.txt").write_text("Development-only compact nonlinear research. No Validation, embargo, or Confirmation rows were read. V22.069C may consume only this frozen best-model JSON and contract summaries; no trading action is allowed.\n", encoding="utf-8")
        exclusions.to_csv(stage / "event_build_summary.csv", index=False); pd.DataFrame(fold_rows).to_csv(stage / "fold_definition.csv", index=False); pd.DataFrame([{key: value for key, value in row.items() if key != "fold_metrics"} for row in metrics]).to_csv(stage / "candidate_metrics.csv", index=False)
        (stage / "best_model.json").write_bytes(stable_bytes(model)); (stage / "best_model.sha256").write_text(model_hash + "\n", encoding="utf-8"); (stage / "feature_contract.json").write_bytes(stable_bytes(feature_contract)); (stage / "development_data_fingerprint.json").write_bytes(stable_bytes({"partition_identity_method": "relative_path+file_size+mtime_ns", "sha256": sha256_bytes(stable_bytes(sorted(identity, key=lambda row: row["relative_path"]))), "partitions": identity})); pd.DataFrame(checks).to_csv(stage / "integrity_checks.csv", index=False)
        publish(stage)
        return summary
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    if parser.parse_args().execute: print(run())
