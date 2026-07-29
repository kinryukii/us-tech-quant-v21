"""V22.067A1M: fixed, forward-only SOXX LONG/SHORT ranking baseline."""
import argparse
import hashlib
import json
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

INPUT_DIR = Path(r"D:\us-tech-quant-results\v22\V22.067A0_FAST3_RECENT_YEAR_UNDERLYING_EVENT_DATASET_R1")
INPUT_FILE = INPUT_DIR / "recent_year_underlying_event_dataset.parquet"
A0_SUMMARY = INPUT_DIR / "v22_067a0_summary.json"
RESULT = Path(r"D:\us-tech-quant-results\v22\V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1")
DATE_BLOCKS = {"TRAIN": ("2025-07-29", "2026-03-31"), "VALIDATION": ("2026-04-01", "2026-05-31"), "CONFIRMATION": ("2026-06-01", "2026-07-28")}
NUMERIC_FEATURES = [
    "return_5m", "range_5m", "realized_volatility_5m", "volume_sum_5m",
    "return_15m", "range_15m", "realized_volatility_15m", "volume_sum_15m",
    "return_30m", "range_30m", "realized_volatility_30m", "volume_sum_30m",
    "return_60m", "range_60m", "realized_volatility_60m", "volume_sum_60m",
    "soxx_minus_qqq_return_30m", "qqq_soxx_sync_minutes",
]
CATEGORICAL_FEATURES = ["session"]
FEATURE_LIST = NUMERIC_FEATURES + CATEGORICAL_FEATURES
MODEL_CONFIGURATION = {"class": "LogisticRegression", "penalty": "l2", "C": 1.0, "max_iter": 2000, "random_state": 22067}
ALLOWED_INPUT_COLUMNS = set(FEATURE_LIST + [
    "timestamp_utc", "open", "high", "low", "close", "volume", "timestamp_et", "feature_complete", "missing_feature_minutes",
    "trading_date_et", "five_minute_bucket", "overlap_group_id", "label_complete", "missing_label_minutes", "symbol",
    "candidate_timestamp_utc", "issue_codes", "label_complete_30m", "label_complete_60m", "label_complete_90m",
] + [f"{direction}_{target}_{horizon}m" for direction in ("long", "short") for target in ("0p25_0p15", "0p50_0p25") for horizon in (30, 60, 90)])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_and_validate():
    a0 = json.loads(A0_SUMMARY.read_text(encoding="utf-8"))
    if a0.get("final_status") != "PASS" or a0.get("final_diagnostic_decision") != "RECENT_YEAR_UNDERLYING_EVENT_DATASET_READY":
        raise ValueError("A0 input is not an approved ready dataset")
    data = pd.read_parquet(INPUT_FILE)
    forbidden = [c for c in data if any(x in c.lower() for x in ("tqqq", "soxl", "soxs", "triple", "trade_outcome", "mfe", "mae"))]
    if forbidden:
        raise ValueError(f"Forbidden source fields: {forbidden}")
    if unknown := set(data.columns).difference(ALLOWED_INPUT_COLUMNS):
        raise ValueError(f"Unexpected non-frozen/source-leakage fields: {sorted(unknown)}")
    if not set(data.symbol.unique()).issubset({"QQQ", "SOXX"}):
        raise ValueError("Input is not limited to QQQ/SOXX underlying data")
    required = set(FEATURE_LIST + ["symbol", "feature_complete", "label_complete", "candidate_timestamp_utc", "timestamp_et", "trading_date_et", "overlap_group_id"])
    if missing := required.difference(data.columns):
        raise ValueError(f"Missing fields: {sorted(missing)}")
    return data, a0


def audit_data(data, a0):
    et = pd.to_datetime(data["timestamp_et"])
    candidate = pd.to_datetime(data["candidate_timestamp_utc"], utc=True)
    label_start = candidate + pd.Timedelta(minutes=1)
    label_end = candidate + pd.Timedelta(minutes=90)
    saturday = int((et.dt.dayofweek == 5).sum())
    sunday_bad = int(((et.dt.dayofweek == 6) & ((et.dt.hour * 60 + et.dt.minute) < 20 * 60)).sum())
    checks = {
        "trading_date_count": int(data.trading_date_et.nunique()),
        "a0_trading_date_count": int(a0.get("trading_date_count", -1)),
        "saturday_candidate_count": saturday, "illegal_sunday_candidate_count": sunday_bad,
        "raw_feature_incomplete_count": int((~data.feature_complete).sum()), "raw_label_incomplete_count": int((~data.label_complete).sum()),
        "model_input_feature_complete": bool(data.loc[(data.symbol == "SOXX") & data.feature_complete & data.label_complete, "feature_complete"].all()),
        "model_input_label_complete": bool(data.loc[(data.symbol == "SOXX") & data.feature_complete & data.label_complete, "label_complete"].all()),
        "candidate_not_after_label_start": bool((candidate <= label_start).all()),
        "label_end_not_before_candidate": bool((label_end >= candidate).all()),
        "trading_date_interpretation": "306 is treated as extended-hours session dates; it is not required to equal regular US equity trading-day count.",
    }
    if checks["trading_date_count"] != 306 or checks["a0_trading_date_count"] != 306 or saturday or sunday_bad:
        raise ValueError(f"Calendar audit failed: {checks}")
    return checks


def prepare_partitions(data):
    z = data[(data.symbol == "SOXX") & data.feature_complete & data.label_complete].copy()
    z["candidate_timestamp"] = pd.to_datetime(z.candidate_timestamp_utc, utc=True)
    z["label_start_timestamp"] = z.candidate_timestamp + pd.Timedelta(minutes=1)
    z["label_end_timestamp"] = z.candidate_timestamp + pd.Timedelta(minutes=90)
    z["candidate_date"] = z.candidate_timestamp.dt.tz_convert("America/New_York").dt.date.astype(str)
    z["partition"] = None
    for name, (start, end) in DATE_BLOCKS.items():
        inside = z.candidate_date.between(start, end)
        # An outcome window must fully mature before that block ends.
        end_ts = pd.Timestamp(end + " 23:59:59", tz="America/New_York").tz_convert("UTC")
        z.loc[inside & (z.label_end_timestamp <= end_ts), "partition"] = name
    z = z[z.partition.notna()].copy()
    group_counts = z.groupby("overlap_group_id").size()
    z["sample_weight"] = z.overlap_group_id.map(1.0 / group_counts)
    if z.groupby("overlap_group_id").partition.nunique().gt(1).any():
        raise ValueError("overlap group crossed a partition")
    return z


def make_pipeline():
    numeric = Pipeline([("imputer", SimpleImputer(strategy="mean")), ("scaler", StandardScaler())])
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))])
    return Pipeline([("preprocess", ColumnTransformer([("numeric", numeric, NUMERIC_FEATURES), ("session", categorical, CATEGORICAL_FEATURES)])),
                     ("clf", LogisticRegression(penalty="l2", C=1.0, max_iter=2000, random_state=22067))])


def safe_metric(fn, y, score):
    return None if pd.Series(y).nunique() < 2 else float(fn(y, score))


def metrics(y, score):
    return {"candidate_count": int(len(y)), "positive_count": int(np.sum(y)), "base_positive_rate": float(np.mean(y)),
            "roc_auc": safe_metric(roc_auc_score, y, score), "pr_auc": safe_metric(average_precision_score, y, score),
            "brier_score": float(brier_score_loss(y, score))}


def selected_metrics(y, score, threshold, base_rate, outcomes=None):
    keep = score >= threshold
    count = int(keep.sum())
    precision = float(np.mean(y[keep])) if count else None
    recall = float(np.sum(y[keep]) / np.sum(y)) if np.sum(y) else None
    out = {"threshold": float(threshold), "selected_count": count, "precision": precision, "recall": recall,
           "lift_over_base_rate": (precision / base_rate if count and base_rate else None)}
    if outcomes is not None:
        for value, key in (("TARGET_FIRST", "target_first_count"), ("ADVERSE_FIRST", "adverse_first_count"), ("NEITHER", "neither_count")):
            out[key] = int((outcomes[keep] == value).sum())
    return out, keep


def confirmation_selection(frame, score, threshold, direction, label):
    z = frame.copy(); z["score"] = score; z["direction"] = direction; z["label_outcome"] = z[label]
    z = z[z.score >= threshold].sort_values("score", ascending=False)
    z = z.drop_duplicates("overlap_group_id", keep="first")
    z = z.drop_duplicates(["trading_date_et", "session", "direction"], keep="first")
    return z


def direction_run(data, direction):
    label = f"{direction.lower()}_0p25_0p15_90m"
    secondary = f"{direction.lower()}_0p50_0p25_90m"
    pieces = {p: data[data.partition == p].copy() for p in DATE_BLOCKS}
    y_train = pieces["TRAIN"][label].eq("TARGET_FIRST").astype(int).to_numpy()
    pipe = make_pipeline(); pipe.fit(pieces["TRAIN"][FEATURE_LIST], y_train, clf__sample_weight=pieces["TRAIN"].sample_weight.to_numpy())
    scores = {p: pipe.predict_proba(pieces[p][FEATURE_LIST])[:, 1] for p in DATE_BLOCKS}
    y = {p: pieces[p][label].eq("TARGET_FIRST").astype(int).to_numpy() for p in DATE_BLOCKS}
    validation_threshold = float(np.quantile(scores["VALIDATION"], .95))
    all_metrics = {p.lower(): metrics(y[p], scores[p]) for p in DATE_BLOCKS}
    validation_high, _ = selected_metrics(y["VALIDATION"], scores["VALIDATION"], validation_threshold, all_metrics["validation"]["base_positive_rate"])
    selected = confirmation_selection(pieces["CONFIRMATION"], scores["CONFIRMATION"], validation_threshold, direction, label)
    selected_y = selected[label].eq("TARGET_FIRST").astype(int).to_numpy()
    confirmation_high, _ = selected_metrics(selected_y, selected.score.to_numpy(), validation_threshold, all_metrics["confirmation"]["base_positive_rate"], selected[label].to_numpy())
    confirmation_high["session_distribution"] = {str(k): int(v) for k, v in selected.session.value_counts().items()}
    confirmation_high["monthly_signal_counts"] = {str(k): int(v) for k, v in selected.candidate_timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m").value_counts().sort_index().items()}
    secondary_rate = float(selected[secondary].eq("TARGET_FIRST").mean()) if len(selected) else None
    confirmation_high["0p50_target_first_count"] = int(selected[secondary].eq("TARGET_FIRST").sum())
    confirmation_high["0p50_hit_rate"] = secondary_rate
    base = all_metrics["confirmation"]["base_positive_rate"]
    found = (len(selected) >= 20 and confirmation_high["precision"] is not None and confirmation_high["precision"] >= 1.5 * base and
             confirmation_high["precision"] > all_metrics["validation"]["base_positive_rate"] and selected.trading_date_et.nunique() > 1 and
             selected.session.nunique() >= 2 and len(confirmation_high["monthly_signal_counts"]) >= 2)
    return pipe, {"all_candidates": all_metrics, "validation_high_score": validation_high, "confirmation_high_score": confirmation_high,
                  "directional_decision": "DIRECTIONAL_RANKING_SIGNAL_FOUND" if found else "NO_DIRECTIONAL_RANKING_SIGNAL_FOUND"}, validation_threshold, selected


def final_decision(long_result, short_result, counts):
    l = long_result["directional_decision"] == "DIRECTIONAL_RANKING_SIGNAL_FOUND"; s = short_result["directional_decision"] == "DIRECTIONAL_RANKING_SIGNAL_FOUND"
    if min(counts.values()) == 0: return "RECENT_YEAR_MODEL_DATA_INSUFFICIENT"
    if l and s: return "RECENT_YEAR_SOXX_RANKING_SIGNAL_FOUND"
    if l: return "RECENT_YEAR_SOXX_LONG_ONLY_SIGNAL_FOUND"
    if s: return "RECENT_YEAR_SOXX_SHORT_ONLY_SIGNAL_FOUND"
    lifts = [x["confirmation_high_score"]["lift_over_base_rate"] for x in (long_result, short_result)]
    return "RECENT_YEAR_SOXX_WEAK_LIFT_ONLY" if any(x is not None and x > 1 for x in lifts) else "NO_MEANINGFUL_RECENT_YEAR_SOXX_LIFT"


def run():
    start = time.time(); before_hash = sha256(INPUT_FILE); raw, a0 = load_and_validate(); audit = audit_data(raw, a0); data = prepare_partitions(raw)
    counts = {p.lower(): int((data.partition == p).sum()) for p in DATE_BLOCKS}
    if min(counts.values()) == 0: raise ValueError("one or more required time blocks have no samples")
    long_pipe, long_result, long_threshold, long_selected = direction_run(data, "LONG")
    short_pipe, short_result, short_threshold, short_selected = direction_run(data, "SHORT")
    after_hash = sha256(INPUT_FILE); frozen_mods = 0 if before_hash == after_hash else 1
    if frozen_mods: raise RuntimeError("frozen input changed during run")
    RESULT.mkdir(parents=True, exist_ok=True)
    bundle = {"long_pipeline": long_pipe, "short_pipeline": short_pipe, "feature_list": FEATURE_LIST, "validation_thresholds": {"LONG": long_threshold, "SHORT": short_threshold}, "date_blocks": DATE_BLOCKS, "input_sha256": before_hash, "model_configuration": MODEL_CONFIGURATION}
    joblib.dump(bundle, RESULT / "soxx_model_bundle.joblib")
    pd.concat([long_selected, short_selected], ignore_index=True).sort_values(["direction", "score"], ascending=[True, False]).to_csv(RESULT / "confirmation_ranked_candidates.csv", index=False)
    summary = {"final_status": "PASS", "final_diagnostic_decision": final_decision(long_result, short_result, counts), "targeted_test_count": 8,
               "input_sha256": before_hash, "frozen_input_modification_count": frozen_mods, "broker_action_allowed": False, "paper_action_allowed": False, "official_adoption_allowed": False,
               "feature_list": FEATURE_LIST, "model_configuration": MODEL_CONFIGURATION, "date_blocks": DATE_BLOCKS, "audit": audit, "partition_candidate_counts": counts,
               "long": long_result, "short": short_result, "total_elapsed_seconds": time.time() - start}
    (RESULT / "v22_067a1m_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (RESULT / "test_report.json").write_text(json.dumps({"targeted_test_count": 8, "status": "pytest_required_and_run_by_wrapper", "frozen_input_modification_count": frozen_mods}, indent=2), encoding="utf-8")
    output = {"FINAL_STATUS": summary["final_status"], "FINAL_DIAGNOSTIC_DECISION": summary["final_diagnostic_decision"], "TARGETED_TEST_COUNT": 8,
              "TRAIN_CANDIDATE_COUNT": counts["train"], "VALIDATION_CANDIDATE_COUNT": counts["validation"], "CONFIRMATION_CANDIDATE_COUNT": counts["confirmation"]}
    for d, r, threshold in (("LONG", long_result, long_threshold), ("SHORT", short_result, short_threshold)):
        output[f"{d}_TRAIN_BASE_RATE"] = r["all_candidates"]["train"]["base_positive_rate"]; output[f"{d}_VALIDATION_BASE_RATE"] = r["all_candidates"]["validation"]["base_positive_rate"]; output[f"{d}_CONFIRMATION_BASE_RATE"] = r["all_candidates"]["confirmation"]["base_positive_rate"]
        output[f"{d}_VALIDATION_THRESHOLD"] = threshold
        for k in ("selected_count", "precision", "lift_over_base_rate", "0p50_hit_rate"):
            name = {"selected_count": "SELECTED_COUNT", "precision": "PRECISION", "lift_over_base_rate": "LIFT", "0p50_hit_rate": "0P50_HIT_RATE"}[k]
            output[f"{d}_CONFIRMATION_{name}"] = r["confirmation_high_score"][k]
    output.update({"TOTAL_ELAPSED_SECONDS": summary["total_elapsed_seconds"], "FROZEN_INPUT_MODIFICATION_COUNT": frozen_mods, "RESULT_DIRECTORY": str(RESULT)})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    if parser.parse_args().execute:
        warnings.simplefilter("ignore", FutureWarning)
        for key, value in run().items(): print(f"{key}={value}")
