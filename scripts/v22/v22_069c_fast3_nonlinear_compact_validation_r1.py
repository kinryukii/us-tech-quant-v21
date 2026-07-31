from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parents[2]
DEFAULT_UPSTREAM_ROOT = REPO / ".local_results"
DEFAULT_RESULTS_ROOT = Path(r"D:/us-tech-quant-results")
CONTRACT = REPO / ".local_results/v22/V22.069A_FAST_RESEARCH_CONTRACT_R1/v22_069a_fast_frozen_research_contract.json"
DATA_ROOT = Path(r"D:/us-tech-quant-data/fast3/moomoo_24h_1m")
EXPECTED_MODEL_ARTIFACT_SHA256 = "d92fbddcac00dd3e6e37e76daa3510eda40444cc914d4dc3160c2db0ffd93ce0"
EXPECTED_MODEL_STATE_SHA256 = "e005ee7bb350b768375cf3e11efe968121b60ec370e6222e0693c9374cfe008e"
EXPECTED_CONTRACT_SHA256 = "7facdfdae38e5b7d925f2cae4ad0216fc14b8afdfe3da27f3ec6a9f096c28013"
EXPECTED_PARAMS = {"max_depth": 2, "min_samples_leaf": 100, "random_state": 20260731}
FEATURES = ["PREMARKET_CUM_RETURN", "PREMARKET_MAX_DRAWDOWN", "PREMARKET_REALIZED_VOLATILITY"]
SYMS = ["QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"]
ROUND_TRIP_COST = .001


def stable(value): return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def nullable(value): return float(value) if value is not None and np.isfinite(value) else None


def upstream_dir(root): return Path(root) / "v22/V22.069B1_FAST3_NONLINEAR_COMPACT_MODEL_MATERIALIZATION_R1"
def output_dir(root): return Path(root) / "v22/V22.069C_FAST3_NONLINEAR_COMPACT_VALIDATION_R1"


def load_lineage(root):
    upstream = upstream_dir(root)
    required = [upstream / name for name in ("v22_069b1_summary.json", "frozen_model.joblib", "frozen_model_state.json", "training_contract_manifest.json")]
    if not CONTRACT.is_file() or any(not item.is_file() for item in required): raise RuntimeError("UPSTREAM_EXECUTABLE_MODEL_OR_CONTRACT_MISSING")
    if sha(CONTRACT) != EXPECTED_CONTRACT_SHA256: raise RuntimeError("FROZEN_RESEARCH_CONTRACT_SHA256_MISMATCH")
    if sha(upstream / "frozen_model.joblib") != EXPECTED_MODEL_ARTIFACT_SHA256: raise RuntimeError("MODEL_ARTIFACT_SHA256_MISMATCH")
    if sha(upstream / "frozen_model_state.json") != EXPECTED_MODEL_STATE_SHA256: raise RuntimeError("MODEL_STATE_SHA256_MISMATCH")
    summary = json.loads((upstream / "v22_069b1_summary.json").read_text(encoding="utf-8")); manifest = json.loads((upstream / "training_contract_manifest.json").read_text(encoding="utf-8")); state = json.loads((upstream / "frozen_model_state.json").read_text(encoding="utf-8")); contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if summary.get("final_status") != "PASS" or not summary.get("eligible_for_v22_069c") or summary.get("model_file_sha256") != EXPECTED_MODEL_ARTIFACT_SHA256 or summary.get("model_state_sha256") != EXPECTED_MODEL_STATE_SHA256: raise RuntimeError("UPSTREAM_SUMMARY_NOT_ELIGIBLE")
    if manifest.get("feature_names") != FEATURES or manifest.get("model_parameters") != EXPECTED_PARAMS or manifest.get("frozen_research_contract_sha256") != EXPECTED_CONTRACT_SHA256: raise RuntimeError("UPSTREAM_TRAINING_CONTRACT_MISMATCH")
    model = joblib.load(upstream / "frozen_model.joblib")
    actual = model.get_params(deep=True)
    if not all(actual.get(key) == value for key, value in EXPECTED_PARAMS.items()): raise RuntimeError("MODEL_PARAMETERS_MISMATCH")
    if list(model.feature_names_in_) != FEATURES or state.get("feature_names_in") != FEATURES or state.get("model_type") != "sklearn.tree.DecisionTreeRegressor": raise RuntimeError("FEATURE_SCHEMA_MISMATCH")
    if contract.get("features") != FEATURES or contract.get("symbols") != SYMS: raise RuntimeError("FROZEN_CONTRACT_CONTENT_MISMATCH")
    return contract, model


def validation_paths(months):
    return [DATA_ROOT / "canonical" / f"symbol={symbol}" / f"year={month[:4]}" / f"month={month[5:]}" / "data.parquet" for month in months for symbol in SYMS]


def build_validation_events(months, model):
    events, excluded, reads, allowed = [], [], 0, set(months)
    for path in validation_paths(months):
        if not path.is_file(): raise RuntimeError(f"VALIDATION_PARTITION_MISSING:{path}")
        frame = pq.read_table(path, columns=["timestamp_et", "open", "close"]).to_pandas(); reads += len(frame)
        timestamp = pd.to_datetime(frame.timestamp_et, utc=True).dt.tz_convert("America/New_York")
        frame = frame.assign(timestamp=timestamp).dropna(subset=["timestamp", "open", "close"]); frame["date"] = frame.timestamp.dt.date.astype(str)
        # UTC partition boundaries can contain adjacent New York calendar dates; they are not Validation events.
        frame = frame[frame.date.str[:7].isin(allowed)]
        symbol = path.parents[2].name.split("=", 1)[1]
        for date, day in frame.groupby("date", sort=True):
            day = day.sort_values("timestamp"); pre = day[(day.timestamp.dt.time >= pd.Timestamp("04:00").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:25").time())]
            if pre.timestamp.dt.floor("min").nunique() / 326 < .80: excluded.append("PREMARKET_COVERAGE_LT_80_PERCENT"); continue
            entry = day[(day.timestamp.dt.time >= pd.Timestamp("09:30").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:32").time())]; exit_ = day[(day.timestamp.dt.time >= pd.Timestamp("15:58").time()) & (day.timestamp.dt.time <= pd.Timestamp("16:00").time())]
            if entry.empty: excluded.append("MISSING_ENTRY"); continue
            if exit_.empty: excluded.append("MISSING_EXIT"); continue
            closes = pre.close.astype(float).to_numpy(); row = {"PREMARKET_CUM_RETURN": float(closes[-1] / closes[0] - 1), "PREMARKET_MAX_DRAWDOWN": float(np.min(closes / np.maximum.accumulate(closes) - 1)), "PREMARKET_REALIZED_VOLATILITY": float(np.std(np.diff(np.log(closes)), ddof=0))}
            prediction = float(model.predict(pd.DataFrame([row], columns=FEATURES))[0])
            events.append({"date": date, "symbol": symbol, **row, "target_return": float(exit_.iloc[-1].close) / float(entry.iloc[0].open) - 1, "prediction": prediction})
    return pd.DataFrame(events).sort_values(["date", "symbol"]).reset_index(drop=True), reads, excluded


def buckets(target, prediction):
    if len(target) < 5: return {"top_mean": None, "bottom_mean": None, "gross": None, "net": None, "count": 0}
    count = max(1, math.ceil(len(target) * .2)); order = np.lexsort((np.arange(len(prediction)), prediction)); target = np.asarray(target)
    gross = float(target[order[-count:]].mean() - target[order[:count]].mean())
    return {"top_mean": float(target[order[-count:]].mean()), "bottom_mean": float(target[order[:count]].mean()), "gross": gross, "net": gross - ROUND_TRIP_COST, "count": count}


def summarize(events):
    target, prediction = events.target_return.to_numpy(), events.prediction.to_numpy(); b = buckets(target, prediction)
    ic = spearmanr(target, prediction).statistic if len(events) >= 2 else np.nan
    monthly = []
    for month, group in events.groupby(events.date.str[:7], sort=True):
        mb = buckets(group.target_return, group.prediction); monthly.append({"month": month, "event_count": len(group), "top_bottom_spread_net_10bps": mb["net"], "spearman_ic": nullable(spearmanr(group.target_return, group.prediction).statistic)})
    symbols = [{"symbol": symbol, "event_count": len(group), "spearman_ic": nullable(spearmanr(group.target_return, group.prediction).statistic), "top_bottom_spread_net_10bps": buckets(group.target_return, group.prediction)["net"]} for symbol, group in events.groupby("symbol", sort=True)]
    positive = [row["top_bottom_spread_net_10bps"] > 0 for row in monthly if row["top_bottom_spread_net_10bps"] is not None]
    profits = np.maximum(0, target[np.lexsort((np.arange(len(prediction)), prediction))[-b["count"]:]]) if b["count"] else np.array([])
    concentration = lambda n: nullable(np.sort(profits)[-n:].sum() / profits.sum()) if profits.sum() > 0 else None
    return {"validation_spearman_ic": nullable(ic), "validation_top_mean_return_gross": b["top_mean"], "validation_bottom_mean_return_gross": b["bottom_mean"], "validation_top_bottom_spread_gross": b["gross"], "validation_top_bottom_spread_net_10bps": b["net"], "validation_top_bucket_event_count": b["count"], "validation_bottom_bucket_event_count": b["count"], "validation_month_count": len(monthly), "validation_valid_month_count": len(positive), "validation_positive_month_ratio": float(np.mean(positive)) if positive else None, "validation_profit_concentration_top5_dates": concentration(5), "validation_profit_concentration_top10_events": concentration(10), "valid_symbol_count": len(symbols)}, pd.DataFrame(monthly), pd.DataFrame(symbols)


def safe_base():
    return {"development_training_row_read_count": 0, "confirmation_row_read_count": 0, "fit_call_count": 0, "hyperparameter_search_count": 0, "data_leakage_detected": False, "broker_action_allowed": False, "paper_trading_allowed": False, "official_adoption_allowed": False, "live_trading_allowed": False, "order_output_count": 0, "position_output_count": 0, "broker_connection_count": 0}


def run(upstream_root=DEFAULT_UPSTREAM_ROOT, results_root=DEFAULT_RESULTS_ROOT):
    out = output_dir(results_root); stage = Path(tempfile.mkdtemp(prefix=".069c_", dir=out.parent)) if out.parent.exists() else None
    if stage is None: out.parent.mkdir(parents=True, exist_ok=True); stage = Path(tempfile.mkdtemp(prefix=".069c_", dir=out.parent))
    try:
        contract, model = load_lineage(upstream_root); events, reads, excluded = build_validation_events(contract["split"]["validation_months"], model)
        if events.empty or reads == 0: raise RuntimeError("VALIDATION_EVENTS_UNAVAILABLE")
        measures, monthly, symbols = summarize(events)
        acceptance = bool(measures["validation_spearman_ic"] is not None and measures["validation_spearman_ic"] > 0 and measures["validation_top_bottom_spread_net_10bps"] is not None and measures["validation_top_bottom_spread_net_10bps"] > 0 and measures["validation_positive_month_ratio"] is not None and measures["validation_positive_month_ratio"] >= .5)
        summary = {**safe_base(), **measures, "model_artifact_sha256": EXPECTED_MODEL_ARTIFACT_SHA256, "model_state_sha256": EXPECTED_MODEL_STATE_SHA256, "model_artifact_sha256_match": True, "model_state_sha256_match": True, "model_parameters_match": True, "feature_schema_match": True, "training_contract_match": True, "validation_event_count": len(events), "validation_row_read_count": reads, "validation_start_date": min(events.date), "validation_end_date": max(events.date), "validation_excluded_event_count": len(excluded), "final_status": "PASS", "final_decision": "NONLINEAR_COMPACT_MODEL_VALIDATED_FOR_V22_069D" if acceptance else "NONLINEAR_COMPACT_MODEL_REJECTED_ON_VALIDATION", "eligible_for_v22_069d": acceptance}
        (stage / "validation_event_scores.csv").write_text(events.to_csv(index=False), encoding="utf-8"); (stage / "validation_metrics.json").write_bytes(stable({"summary": summary, "monthly": monthly.to_dict("records"), "symbols": symbols.to_dict("records")})); (stage / "v22_069c_summary.json").write_bytes(stable(summary))
        if out.exists(): shutil.rmtree(out)
        os.replace(stage, out); return summary, out
    except Exception as error:
        summary = {**safe_base(), "final_status": "FAIL", "final_decision": str(error), "eligible_for_v22_069d": False, "validation_event_count": 0, "validation_row_read_count": 0}
        (stage / "v22_069c_summary.json").write_bytes(stable(summary));
        if out.exists(): shutil.rmtree(out)
        os.replace(stage, out); return summary, out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); parser.add_argument("--upstream-results-root"); parser.add_argument("--results-root")
    args = parser.parse_args()
    if args.execute:
        result, location = run(args.upstream_results_root or DEFAULT_UPSTREAM_ROOT, args.results_root or DEFAULT_RESULTS_ROOT)
        print(json.dumps({**result, "summary_path": str(location / "v22_069c_summary.json")}, sort_keys=True))
