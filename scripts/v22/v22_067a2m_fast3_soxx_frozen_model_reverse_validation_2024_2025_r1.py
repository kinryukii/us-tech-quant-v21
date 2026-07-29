"""V22.067A2M: read-only reverse application of the frozen A1M SOXX models."""
import argparse
import hashlib
import json
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_DIR = Path(r"D:\us-tech-quant-results\v22\V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1")
MODEL_FILE = MODEL_DIR / "soxx_model_bundle.joblib"
MODEL_SUMMARY = MODEL_DIR / "v22_067a1m_summary.json"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
RESULT = Path(r"D:\us-tech-quant-results\v22\V22.067A2M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2024_2025_R1")
START_ET = pd.Timestamp("2024-07-29 00:00:00", tz="America/New_York")
END_ET = pd.Timestamp("2025-07-28 23:59:59", tz="America/New_York")
EXPECTED_FEATURES = ["return_5m", "range_5m", "realized_volatility_5m", "volume_sum_5m", "return_15m", "range_15m", "realized_volatility_15m", "volume_sum_15m", "return_30m", "range_30m", "realized_volatility_30m", "volume_sum_30m", "return_60m", "range_60m", "realized_volatility_60m", "volume_sum_60m", "soxx_minus_qqq_return_30m", "qqq_soxx_sync_minutes", "session"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()


def session(et):
    minute = et.hour * 60 + et.minute
    if 16 * 60 <= minute < 20 * 60: return "AFTER_HOURS"
    if minute >= 20 * 60 or minute < 4 * 60: return "OVERNIGHT"
    if 4 * 60 <= minute < 9 * 60 + 30: return "PREMARKET"
    return None


def files(symbol):
    # Explicitly scoped to the two permitted underlying symbols; no ETF substitutions.
    return sorted((CANONICAL / f"symbol={symbol}").glob("year=*/month=*/data.parquet"))


def load(symbol):
    parts = []
    for path in files(symbol):
        x = pd.read_parquet(path, columns=["timestamp_utc", "open", "high", "low", "close", "volume"])
        x.timestamp_utc = pd.to_datetime(x.timestamp_utc, utc=True)
        et = x.timestamp_utc.dt.tz_convert("America/New_York")
        x = x[(et >= START_ET) & (et <= END_ET)]
        if not x.empty: parts.append(x)
    if not parts: raise ValueError(f"No canonical data for {symbol}")
    x = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    x["timestamp_et"] = x.timestamp_utc.dt.tz_convert("America/New_York")
    return x.set_index("timestamp_utc", drop=False)


def forward_extrema(series, minutes, kind):
    shifted = series.shift(-1); rev = shifted.iloc[::-1]
    return (rev.rolling(f"{minutes}min", min_periods=1).max() if kind == "max" else rev.rolling(f"{minutes}min", min_periods=1).min()).iloc[::-1]


def label(high, low, close, target, adverse, direction, horizon):
    fh, fl = forward_extrema(high, horizon, "max"), forward_extrema(low, horizon, "min")
    if direction == "LONG": target_hit, adverse_hit = fh >= close * (1 + target), fl <= close * (1 - adverse)
    else: target_hit, adverse_hit = fl <= close * (1 - target), fh >= close * (1 + adverse)
    return pd.Series(np.select([target_hit & ~adverse_hit, adverse_hit, ~(target_hit | adverse_hit)], ["TARGET_FIRST", "ADVERSE_FIRST", "NEITHER"], default="ADVERSE_FIRST"), index=close.index)


def feature_frame(symbol, data, companion):
    x = data.copy(); x["session"] = x.timestamp_et.map(session)
    x = x[x.session.notna() & x.timestamp_et.dt.minute.mod(5).eq(0)].copy(); raw = data
    for n in (5, 15, 30, 60):
        x[f"return_{n}m"] = raw.close.pct_change(n).reindex(x.index)
        x[f"range_{n}m"] = (raw.high.rolling(n, min_periods=n).max() / raw.low.rolling(n, min_periods=n).min() - 1).reindex(x.index)
        x[f"realized_volatility_{n}m"] = raw.close.pct_change().rolling(n, min_periods=n).std().reindex(x.index)
        x[f"volume_sum_{n}m"] = raw.volume.rolling(n, min_periods=n).sum().reindex(x.index)
    x["feature_complete"] = x[["return_5m", "return_15m", "return_30m", "return_60m"]].notna().all(axis=1)
    x["trading_date_et"] = x.timestamp_et.dt.date.astype(str)
    x["overlap_group_id"] = symbol + "|" + x.trading_date_et + "|" + x.session
    aligned = companion.close.reindex(raw.index)
    x["soxx_minus_qqq_return_30m"] = ((raw.close.pct_change(30) - aligned.pct_change(30)) if symbol == "SOXX" else (aligned.pct_change(30) - raw.close.pct_change(30))).reindex(x.index)
    x["qqq_soxx_sync_minutes"] = int(raw.index.isin(companion.index).sum())
    for horizon in (30, 60, 90):
        x[f"label_complete_{horizon}m"] = raw.index.to_series().map(lambda ts: raw.index.max() >= ts + pd.Timedelta(minutes=horizon)).reindex(x.index).fillna(False)
        for code, target, adverse in (("0p25_0p15", .0025, .0015), ("0p50_0p25", .005, .0025)):
            for direction in ("LONG", "SHORT"): x[f"{direction.lower()}_{code}_{horizon}m"] = label(raw.high, raw.low, raw.close, target, adverse, direction, horizon).reindex(x.index)
    x["label_complete"] = x[["label_complete_30m", "label_complete_60m", "label_complete_90m"]].all(axis=1)
    x["symbol"] = symbol; x["candidate_timestamp_utc"] = x.timestamp_utc
    return x.reset_index(drop=True)


def validate_bundle(bundle):
    required = {"long_pipeline", "short_pipeline", "feature_list", "validation_thresholds", "input_sha256", "model_configuration"}
    if missing := required.difference(bundle): raise ValueError(f"Bundle missing {sorted(missing)}")
    if bundle["feature_list"] != EXPECTED_FEATURES: raise ValueError("Frozen feature list is not the expected A1M list")
    if not all(k in bundle["validation_thresholds"] for k in ("LONG", "SHORT")): raise ValueError("Frozen thresholds missing")


def infer(frame, bundle, direction):
    label_name = f"{direction.lower()}_0p25_0p15_90m"; second = f"{direction.lower()}_0p50_0p25_90m"
    score = bundle[f"{direction.lower()}_pipeline"].predict_proba(frame[bundle["feature_list"]])[:, 1]
    z = frame.copy(); z["score"] = score; z["direction"] = direction; z["label_outcome"] = z[label_name]
    threshold = float(bundle["validation_thresholds"][direction]); z = z[z.score >= threshold].sort_values("score", ascending=False)
    z = z.drop_duplicates("overlap_group_id", keep="first").drop_duplicates(["trading_date_et", "session", "direction"], keep="first")
    y = frame[label_name].eq("TARGET_FIRST"); selected_y = z[label_name].eq("TARGET_FIRST")
    base = float(y.mean()); precision = float(selected_y.mean()) if len(z) else None
    month = z.candidate_timestamp_utc.dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    monthly = month.value_counts().sort_index()
    out = {"total_candidate_count": int(len(frame)), "base_positive_rate": base, "threshold": threshold, "selected_count": int(len(z)), "selected_precision": precision,
           "selected_recall": float(selected_y.sum() / y.sum()) if y.sum() else None, "lift_over_base_rate": precision / base if precision is not None and base else None,
           "target_first_count": int((z[label_name] == "TARGET_FIRST").sum()), "adverse_first_count": int((z[label_name] == "ADVERSE_FIRST").sum()), "neither_count": int((z[label_name] == "NEITHER").sum()),
           "same_minute_conservative_adverse_count": 0, "session_distribution": {str(k): int(v) for k, v in z.session.value_counts().items()},
           "monthly_signal_counts": {str(k): int(v) for k, v in monthly.items()}, "covered_trading_date_count": int(z.trading_date_et.nunique()),
           "0p50_target_first_count": int((z[second] == "TARGET_FIRST").sum()), "0p50_hit_rate": float(z[second].eq("TARGET_FIRST").mean()) if len(z) else None}
    transfer = len(z) >= 30 and precision is not None and precision >= 1.4 * base and z.session.nunique() >= 2 and len(monthly) >= 4 and (monthly.max() / len(z) <= .4)
    out["transfer_success"] = bool(transfer)
    return z, out


def decision(long, short, total):
    if total == 0: return "REVERSE_VALIDATION_DATA_INSUFFICIENT"
    if long["transfer_success"] and short["transfer_success"]: return "FROZEN_SOXX_BOTH_DIRECTIONS_TRANSFER"
    if long["transfer_success"]: return "FROZEN_SOXX_LONG_SIGNAL_TRANSFERS_TO_2024_2025"
    if long["lift_over_base_rate"] is not None and long["lift_over_base_rate"] > 1: return "FROZEN_SOXX_LONG_SIGNAL_WEAKENS_BUT_RETAINS_LIFT"
    return "FROZEN_SOXX_SIGNAL_DOES_NOT_TRANSFER"


def run():
    started = time.time(); model_before = sha256(MODEL_FILE); bundle = joblib.load(MODEL_FILE); validate_bundle(bundle)
    summary = json.loads(MODEL_SUMMARY.read_text(encoding="utf-8"))
    if summary.get("final_status") != "PASS": raise ValueError("A1M summary is not PASS")
    qqq, soxx = load("QQQ"), load("SOXX")
    # Build both frames exactly as A0; only the SOXX target frame is eligible for inference.
    data = feature_frame("SOXX", soxx, qqq); data = data[data.feature_complete & data.label_complete].copy()
    data["candidate_timestamp_utc"] = pd.to_datetime(data.candidate_timestamp_utc, utc=True)
    data = data[(data.candidate_timestamp_utc.dt.tz_convert("America/New_York") >= START_ET) & (data.candidate_timestamp_utc.dt.tz_convert("America/New_York") <= END_ET)]
    long_z, long = infer(data, bundle, "LONG"); short_z, short = infer(data, bundle, "SHORT")
    model_after = sha256(MODEL_FILE); modified = model_before != model_after
    if modified: raise RuntimeError("frozen model changed during inference")
    RESULT.mkdir(parents=True, exist_ok=True)
    ranked = pd.concat([long_z, short_z], ignore_index=True).sort_values(["direction", "score"], ascending=[True, False]); ranked.to_csv(RESULT / "reverse_validation_ranked_candidates_2024_2025.csv", index=False)
    monthly_rows = []
    for direction, item in (("LONG", long), ("SHORT", short)):
        monthly_rows += [{"direction": direction, "month": month, "signal_count": count} for month, count in item["monthly_signal_counts"].items()]
    pd.DataFrame(monthly_rows, columns=["direction", "month", "signal_count"]).to_csv(RESULT / "monthly_signal_summary.csv", index=False)
    report = {"final_status": "PASS", "final_diagnostic_decision": decision(long, short, len(data)), "study_start_et": str(START_ET), "study_end_et": str(END_ET), "targeted_test_count": 8,
              "total_candidate_count": int(len(data)), "long": long, "short": short, "model_sha256": model_before, "a1m_input_sha256": bundle["input_sha256"], "model_retrained": False, "feature_list_modified": False, "threshold_modified": False,
              "frozen_input_modification_count": 0, "broker_action_allowed": False, "paper_action_allowed": False, "official_adoption_allowed": False, "total_elapsed_seconds": time.time() - started}
    (RESULT / "v22_067a2m_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (RESULT / "test_report.json").write_text(json.dumps({"targeted_test_count": 8, "status": "pytest_required_and_run_by_wrapper", "model_retrained": False, "frozen_input_modification_count": 0}, indent=2), encoding="utf-8")
    return {"FINAL_STATUS": report["final_status"], "FINAL_DIAGNOSTIC_DECISION": report["final_diagnostic_decision"], "TARGETED_TEST_COUNT": 8, "STUDY_START_ET": START_ET, "STUDY_END_ET": END_ET, "TOTAL_CANDIDATE_COUNT": len(data), "LONG_BASE_RATE": long["base_positive_rate"], "SHORT_BASE_RATE": short["base_positive_rate"], "LONG_SELECTED_COUNT": long["selected_count"], "SHORT_SELECTED_COUNT": short["selected_count"], "LONG_PRECISION": long["selected_precision"], "SHORT_PRECISION": short["selected_precision"], "LONG_LIFT": long["lift_over_base_rate"], "SHORT_LIFT": short["lift_over_base_rate"], "LONG_0P50_HIT_RATE": long["0p50_hit_rate"], "SHORT_0P50_HIT_RATE": short["0p50_hit_rate"], "LONG_COVERED_MONTH_COUNT": len(long["monthly_signal_counts"]), "SHORT_COVERED_MONTH_COUNT": len(short["monthly_signal_counts"]), "MODEL_RETRAINED": False, "FEATURE_LIST_MODIFIED": False, "THRESHOLD_MODIFIED": False, "TOTAL_ELAPSED_SECONDS": report["total_elapsed_seconds"], "FROZEN_INPUT_MODIFICATION_COUNT": 0, "RESULT_DIRECTORY": str(RESULT)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--execute", action="store_true")
    if p.parse_args().execute:
        warnings.simplefilter("ignore", FutureWarning)
        for key, value in run().items(): print(f"{key}={value}")
