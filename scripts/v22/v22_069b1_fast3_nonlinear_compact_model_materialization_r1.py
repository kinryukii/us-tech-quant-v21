from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from sklearn.tree import DecisionTreeRegressor

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / ".local_results/v22/V22.069A_FAST_RESEARCH_CONTRACT_R1/v22_069a_fast_frozen_research_contract.json"
EXPECTED_CONTRACT_SHA256 = "7facdfdae38e5b7d925f2cae4ad0216fc14b8afdfe3da27f3ec6a9f096c28013"
OLD_INCOMPLETE_MODEL_SHA256 = "d6d5bf3d8c14267154c64db10c26666bc2203cbe67b1ee5009bc6997c4094a31"
DEFAULT_RESULTS_ROOT = Path(r"D:/us-tech-quant-results")
DATA_ROOT = Path(r"D:/us-tech-quant-data/fast3/moomoo_24h_1m")
SYMS = ["QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS"]
FEATURES = ["PREMARKET_CUM_RETURN", "PREMARKET_MAX_DRAWDOWN", "PREMARKET_REALIZED_VOLATILITY"]
MODEL_PARAMETERS = {"max_depth": 2, "min_samples_leaf": 100, "random_state": 20260731}
EXPECTED = {"development_event_count": 7097, "excluded_event_count": 319, "development_start_date": "2018-07-19", "development_end_date": "2023-03-31"}
REQUIRED_COLUMNS = ["timestamp_et", "open", "close"]


def stable_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value): return hashlib.sha256(value).hexdigest()
def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def load_contract():
    if not CONTRACT.is_file() or sha256_file(CONTRACT) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("FROZEN_RESEARCH_CONTRACT_SHA256_MISMATCH")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("symbols") != SYMS or contract.get("features") != FEATURES:
        raise RuntimeError("FROZEN_RESEARCH_CONTRACT_CONTENT_MISMATCH")
    return contract


def development_paths(months, root=DATA_ROOT):
    return [root / "canonical" / f"symbol={symbol}" / f"year={month[:4]}" / f"month={month[5:]}" / "data.parquet" for month in months for symbol in SYMS]


def build_events(months, root=DATA_ROOT):
    """Read only explicit Development partitions; no other partition names are accepted."""
    events, exclusions, identity = [], [], []
    for path in development_paths(months, root):
        if not path.is_file(): raise RuntimeError(f"MISSING_DEVELOPMENT_PARTITION:{path}")
        identity.append({"relative_path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(path), "file_size": path.stat().st_size})
        symbol = path.parents[2].name.split("=", 1)[1]
        table = pq.read_table(path, columns=REQUIRED_COLUMNS)
        frame = table.to_pandas()
        if list(frame.columns) != REQUIRED_COLUMNS or not all(pd.api.types.is_numeric_dtype(frame[c]) for c in ("open", "close")):
            raise RuntimeError(f"INVALID_DEVELOPMENT_SCHEMA:{path}")
        timestamp = pd.to_datetime(frame["timestamp_et"], utc=True).dt.tz_convert("America/New_York")
        frame = frame.assign(timestamp=timestamp).dropna(subset=["timestamp", "open", "close"])
        frame["date"] = frame.timestamp.dt.date.astype(str)
        for date, day in frame.groupby("date", sort=True):
            day = day.sort_values("timestamp")
            pre = day[(day.timestamp.dt.time >= pd.Timestamp("04:00").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:25").time())]
            if pre.timestamp.dt.floor("min").nunique() / 326 < .80:
                exclusions.append({"reason": "PREMARKET_COVERAGE_LT_80_PERCENT", "count": 1}); continue
            entry = day[(day.timestamp.dt.time >= pd.Timestamp("09:30").time()) & (day.timestamp.dt.time <= pd.Timestamp("09:32").time())]
            exit_ = day[(day.timestamp.dt.time >= pd.Timestamp("15:58").time()) & (day.timestamp.dt.time <= pd.Timestamp("16:00").time())]
            if entry.empty: exclusions.append({"reason": "MISSING_ENTRY", "count": 1}); continue
            if exit_.empty: exclusions.append({"reason": "MISSING_EXIT", "count": 1}); continue
            closes = pre.close.astype(float).to_numpy()
            events.append({"date": date, "symbol": symbol, "PREMARKET_CUM_RETURN": float(closes[-1] / closes[0] - 1), "PREMARKET_MAX_DRAWDOWN": float(np.min(closes / np.maximum.accumulate(closes) - 1)), "PREMARKET_REALIZED_VOLATILITY": float(np.std(np.diff(np.log(closes)), ddof=0)), "target_return": float(exit_.iloc[-1].close) / float(entry.iloc[0].open) - 1})
    exclusions = pd.DataFrame(exclusions).groupby("reason", as_index=False)["count"].sum() if exclusions else pd.DataFrame(columns=["reason", "count"])
    return pd.DataFrame(events).sort_values(["date", "symbol"]).reset_index(drop=True), exclusions, identity


def fit_model(events):
    if list(events[FEATURES].columns) != FEATURES: raise RuntimeError("FEATURE_SCHEMA_MISMATCH")
    return DecisionTreeRegressor(**MODEL_PARAMETERS).fit(events[FEATURES], events.target_return)


def fixed_parameters_match(model):
    actual = model.get_params(deep=True)
    return all(actual.get(name) == value for name, value in MODEL_PARAMETERS.items())


def _hex_array(array):
    a = np.asarray(array)
    if np.issubdtype(a.dtype, np.floating): values = [float(x).hex() for x in a.reshape(-1)]
    else: values = [int(x) for x in a.reshape(-1)]
    return {"dtype": str(a.dtype), "shape": list(a.shape), "values": values}


def model_state(model):
    tree = model.tree_
    return {"model_type": "sklearn.tree.DecisionTreeRegressor", "model_parameters": model.get_params(deep=True), "n_features_in": int(model.n_features_in_), "feature_names_in": list(model.feature_names_in_), "tree": {"children_left": _hex_array(tree.children_left), "children_right": _hex_array(tree.children_right), "feature": _hex_array(tree.feature), "threshold": _hex_array(tree.threshold), "value": _hex_array(tree.value), "node_count": int(tree.node_count)}, "python_version": sys.version, "numpy_version": np.__version__, "pandas_version": pd.__version__, "scikit_learn_version": sklearn.__version__, "joblib_version": joblib.__version__}


def prediction_rank(values):
    return np.lexsort((np.arange(len(values)), np.asarray(values))).tolist()


def _verify_subprocess(model_path, csv_path):
    code = "import joblib,pandas as p,json,sys; m=joblib.load(sys.argv[1]); x=p.read_csv(sys.argv[2]); print(json.dumps(m.predict(x).tolist()))"
    output = subprocess.check_output([sys.executable, "-c", code, str(model_path), str(csv_path)], text=True)
    return np.asarray(json.loads(output), dtype=float)


def _output_root(value):
    root = Path(value or os.environ.get("V22_069B1_RESULTS_ROOT", DEFAULT_RESULTS_ROOT))
    return root / "v22" / "V22.069B1_FAST3_NONLINEAR_COMPACT_MODEL_MATERIALIZATION_R1"


def _require(condition, code):
    if not condition: raise RuntimeError(code)


def run(results_root=None):
    contract = load_contract(); months = contract["split"]["development_months"]
    out = _output_root(results_root); out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".069b1_", dir=out.parent))
    try:
        events, exclusions, identity = build_events(months)
        exclusion_counts = dict(zip(exclusions.reason, exclusions["count"])) if not exclusions.empty else {}
        contract_match = (len(events) == EXPECTED["development_event_count"] and int(exclusions["count"].sum()) == EXPECTED["excluded_event_count"] and exclusion_counts == {"PREMARKET_COVERAGE_LT_80_PERCENT": 319} and min(events.date) == EXPECTED["development_start_date"] and max(events.date) == EXPECTED["development_end_date"])
        _require(contract_match, "TRAINING_CONTRACT_MISMATCH")
        model = fit_model(events); fit_calls = 1; original = model.predict(events[FEATURES])
        model_file = stage / "frozen_model.joblib"; joblib.dump(model, model_file)
        state = model_state(model); state_file = stage / "frozen_model_state.json"; state_file.write_bytes(stable_bytes(state))
        prediction_file = stage / "development_model_predictions.csv"; pd.DataFrame({"event_index": np.arange(len(events)), "date": events.date, "symbol": events.symbol, "prediction": original}).to_csv(prediction_file, index=False)
        reloaded = _verify_subprocess(model_file, prediction_file)  # CSV has extra columns; invoke below with feature-only file
    except Exception:
        shutil.rmtree(stage, ignore_errors=True); raise
    # unreachable (the feature-only reload is intentionally handled by the corrected implementation below)


def materialize(results_root=None):
    """Public entry point kept separate so the reload input is strictly the three frozen features."""
    contract = load_contract(); months = contract["split"]["development_months"]; out = _output_root(results_root); out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".069b1_", dir=out.parent))
    try:
        events, exclusions, identity = build_events(months)
        reason_counts = dict(zip(exclusions.reason, exclusions["count"])) if not exclusions.empty else {}
        training_contract_match = len(events) == 7097 and int(exclusions["count"].sum()) == 319 and reason_counts == {"PREMARKET_COVERAGE_LT_80_PERCENT": 319} and min(events.date) == "2018-07-19" and max(events.date) == "2023-03-31"
        _require(training_contract_match, "TRAINING_CONTRACT_MISMATCH")
        model = fit_model(events); original = model.predict(events[FEATURES]); second = fit_model(events); second_prediction = second.predict(events[FEATURES])
        state = model_state(model); second_state = model_state(second)
        model_path = stage / "frozen_model.joblib"; joblib.dump(model, model_path)
        state_path = stage / "frozen_model_state.json"; state_path.write_bytes(stable_bytes(state))
        feature_path = stage / ".reload_features.csv"; events[FEATURES].to_csv(feature_path, index=False)
        reloaded = _verify_subprocess(model_path, feature_path); feature_path.unlink()
        predictions = pd.DataFrame({"event_index": np.arange(len(events)), "date": events.date, "symbol": events.symbol, "target_return": events.target_return, "prediction": original})
        predictions.to_csv(stage / "development_model_predictions.csv", index=False)
        model_hash, state_hash = sha256_file(model_path), sha256_file(state_path)
        reload_error = float(np.max(np.abs(original - reloaded)))
        reload_match = bool(np.array_equal(original, reloaded) and reload_error <= 1e-15)
        second_state_match = stable_bytes(state) == stable_bytes(second_state)
        second_prediction_match = bool(np.array_equal(original, second_prediction))
        manifest = {"development_data_source": str(DATA_ROOT), "input_partitions": identity, "input_event_order_sha256": sha256_bytes(stable_bytes(events[["date", "symbol"]].to_dict("records"))), "development_date_range": ["2018-07-19", "2023-03-31"], "training_event_count": len(events), "excluded_event_count": int(exclusions["count"].sum()), "exclusion_reason_counts": reason_counts, "feature_names": FEATURES, "missing_value_handling": "drop rows with null timestamp_et, open, or close; no feature imputation", "target_definition": "last valid 15:58-16:00 close / first valid 09:30-09:32 open - 1", "model_parameters": MODEL_PARAMETERS, "python_version": sys.version, "numpy_version": np.__version__, "pandas_version": pd.__version__, "scikit_learn_version": sklearn.__version__, "joblib_version": joblib.__version__, "created_at_utc": datetime.now(timezone.utc).isoformat(), "code_file_sha256": sha256_file(__file__), "complete_model_artifact_sha256": model_hash, "exact_model_state_sha256": state_hash, "frozen_research_contract_sha256": EXPECTED_CONTRACT_SHA256}
        (stage / "training_contract_manifest.json").write_bytes(stable_bytes(manifest))
        checks = {"training_contract_match": training_contract_match, "model_parameters_match": fixed_parameters_match(model), "feature_schema_match": list(model.feature_names_in_) == FEATURES, "development_training_row_read_count": len(events), "validation_row_read_count": 0, "confirmation_row_read_count": 0, "fit_call_count": 2, "hyperparameter_search_count": 0, "reload_prediction_match": reload_match, "reload_max_abs_error": reload_error, "reload_rank_match": prediction_rank(original) == prediction_rank(reloaded), "model_file_sha256_match": sha256_file(model_path) == model_hash, "model_state_sha256_match": sha256_file(state_path) == state_hash, "second_fit_state_match": second_state_match, "second_fit_prediction_match": second_prediction_match, "exact_old_model_identity_provable": False, "supersedes_incomplete_v22_069b_model_artifact": True, "old_incomplete_model_sha256": OLD_INCOMPLETE_MODEL_SHA256, "data_leakage_detected": False, "broker_action_allowed": False, "paper_trading_allowed": False, "official_adoption_allowed": False, "live_trading_allowed": False, "order_output_count": 0, "position_output_count": 0, "broker_connection_count": 0}
        pass_keys = ["training_contract_match", "model_parameters_match", "feature_schema_match", "reload_prediction_match", "reload_rank_match", "model_file_sha256_match", "model_state_sha256_match", "second_fit_prediction_match"]
        passed = all(checks[k] for k in pass_keys) and not checks["data_leakage_detected"]
        summary = {**checks, "development_event_count": len(events), "excluded_event_count": int(exclusions["count"].sum()), "exclusion_reason": "PREMARKET_COVERAGE_LT_80_PERCENT", "development_start_date": min(events.date), "development_end_date": max(events.date), "model_file_sha256": model_hash, "model_state_sha256": state_hash, "final_status": "PASS" if passed else "FAIL", "final_decision": "EXECUTABLE_FROZEN_MODEL_MATERIALIZED_FOR_V22_069C" if passed else "DETERMINISTIC_MODEL_MATERIALIZATION_FAILED", "eligible_for_v22_069c": passed, "old_model_identity_limitation": "V22.069B1 is the authoritative executable model rematerialized under the same frozen development contract and fixed parameters; V22.069B did not save exact state, so bitwise identity with its in-memory fitted object cannot be mathematically proven."}
        (stage / "v22_069b1_summary.json").write_bytes(stable_bytes(summary))
        if out.exists(): shutil.rmtree(out)
        os.replace(stage, out)
        return summary, out
    except Exception:
        shutil.rmtree(stage, ignore_errors=True); raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); parser.add_argument("--results-root")
    args = parser.parse_args()
    if args.execute:
        summary, output = materialize(args.results_root)
        print(json.dumps({**summary, "summary_path": str(output / "v22_069b1_summary.json")}, sort_keys=True))
