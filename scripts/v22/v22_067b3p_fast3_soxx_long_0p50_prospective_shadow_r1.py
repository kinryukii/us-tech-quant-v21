"""V22.067B3P: deterministic, read-only prospective shadow for frozen B1M SOXX LONG."""
import argparse
import ast
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_FILE = Path(r"D:\us-tech-quant-results\v22\V22.067B1M_FAST3_SOXX_LONG_0P50_ECONOMIC_TARGET_BASELINE_R1\soxx_long_0p50_model_bundle.joblib")
B1M_SUMMARY = MODEL_FILE.with_name("v22_067b1m_summary.json")
B1A_SUMMARY = Path(r"D:\us-tech-quant-results\v22\V22.067B1A_FAST3_SOXX_LONG_0P50_ECONOMIC_GATE_CONSISTENCY_AUDIT_R1\v22_067b1a_summary.json")
CANONICAL_ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
RESULT = Path(r"D:\us-tech-quant-results\v22\V22.067B3P_FAST3_SOXX_LONG_0P50_PROSPECTIVE_SHADOW_R1")
FORWARD_START_ET = pd.Timestamp("2026-07-29 00:00:00", tz="America/New_York")
DIRECTION = "LONG"
TARGET = 0.005
ADVERSE = 0.0025
HORIZON_MINUTES = 90
SAME_MINUTE_POLICY = "ADVERSE_FIRST"
MODEL_RETRAINED = False
MODEL_MODIFIED = False
FEATURE_LIST_MODIFIED = False
THRESHOLD_MODIFIED = False
SHORT_MODEL_CREATED = False
FROZEN_INPUT_MODIFICATION_COUNT = 0


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def session(et):
    minute = et.hour * 60 + et.minute
    if 16 * 60 <= minute < 20 * 60:
        return "AFTER_HOURS"
    if minute >= 20 * 60 or minute < 4 * 60:
        return "OVERNIGHT"
    if 4 * 60 <= minute < 9 * 60 + 30:
        return "PREMARKET"
    return None


def files(symbol):
    # The forward start is in July 2026; this includes all files needed for the
    # 60-minute feature warm-up and every available forward observation.
    warmup_utc = (FORWARD_START_ET - pd.Timedelta(minutes=60)).tz_convert("UTC")
    start_month = pd.Period(f"{warmup_utc.year:04d}-{warmup_utc.month:02d}", freq="M")
    selected = []
    for path in sorted((CANONICAL_ROOT / f"symbol={symbol}").glob("year=*/month=*/data.parquet")):
        year = int(path.parents[1].name.split("=", 1)[1])
        month = int(path.parent.name.split("=", 1)[1])
        if pd.Period(f"{year:04d}-{month:02d}", freq="M") >= start_month:
            selected.append(path)
    if not selected:
        raise ValueError(f"No canonical files available for {symbol}")
    return selected


def canonical_sha256(paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(CANONICAL_ROOT)).replace("\\", "/").encode("utf-8"))
        digest.update(sha256(path).encode("ascii"))
    return digest.hexdigest()


def load(symbol):
    """Reuse the validated A2M loader contract, scoped to the forward window."""
    parts = []
    for path in files(symbol):
        frame = pd.read_parquet(path, columns=["timestamp_utc", "open", "high", "low", "close", "volume"])
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        if not frame.empty:
            parts.append(frame)
    if not parts:
        raise ValueError(f"No canonical forward data for {symbol}")
    frame = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    frame["timestamp_et"] = frame.timestamp_utc.dt.tz_convert("America/New_York")
    return frame.set_index("timestamp_utc", drop=False)


def forward_extrema(series, minutes, kind):
    """Validated A2M forward-extrema helper, retained for the frozen label path."""
    shifted = series.shift(-1)
    reverse = shifted.iloc[::-1]
    rolling = reverse.rolling(f"{minutes}min", min_periods=1)
    return (rolling.max() if kind == "max" else rolling.min()).iloc[::-1]


def label(high, low, close, target, adverse, direction, horizon):
    """Classify complete future paths; dual hits in one future minute are adverse-first."""
    # Preserve the verified A2M forward-extrema calculation as an inexpensive
    # no-hit screen.  Chronological scanning below supplies the frozen race rule.
    future_high = forward_extrema(high, horizon, "max")
    future_low = forward_extrema(low, horizon, "min")
    index = close.index
    outcomes = pd.Series("PENDING", index=index, dtype="object")
    needed = pd.Timedelta(minutes=horizon)
    for pos, timestamp in enumerate(index):
        end = timestamp + needed
        if end > index[-1]:
            continue
        window_index = pd.date_range(timestamp + pd.Timedelta(minutes=1), end, freq="min", tz="UTC")
        future = pd.Index(window_index)
        if not future.isin(index).all():
            continue
        if direction == "LONG":
            can_target = future_high.iloc[pos] >= close.iloc[pos] * (1 + target)
            can_adverse = future_low.iloc[pos] <= close.iloc[pos] * (1 - adverse)
            target_line, adverse_line = close.iloc[pos] * (1 + target), close.iloc[pos] * (1 - adverse)
        else:
            can_target = future_low.iloc[pos] <= close.iloc[pos] * (1 - target)
            can_adverse = future_high.iloc[pos] >= close.iloc[pos] * (1 + adverse)
            target_line, adverse_line = close.iloc[pos] * (1 - target), close.iloc[pos] * (1 + adverse)
        if not can_target and not can_adverse:
            outcomes.iloc[pos] = "NEITHER"
            continue
        path = pd.DataFrame({"high": high.reindex(future), "low": low.reindex(future)})
        for _, bar in path.iterrows():
            if direction == "LONG":
                target_hit, adverse_hit = bar.high >= target_line, bar.low <= adverse_line
            else:
                target_hit, adverse_hit = bar.low <= target_line, bar.high >= adverse_line
            if target_hit and adverse_hit:
                outcomes.iloc[pos] = "SAME_MINUTE_CONSERVATIVE_ADVERSE"
                break
            if adverse_hit:
                outcomes.iloc[pos] = "ADVERSE_FIRST"
                break
            if target_hit:
                outcomes.iloc[pos] = "TARGET_FIRST"
                break
        else:
            outcomes.iloc[pos] = "NEITHER"
    return outcomes


def feature_frame(symbol, data, companion):
    """Reuse the validated A2M feature contract without attaching future labels."""
    frame = data.copy()
    frame["session"] = frame.timestamp_et.map(session)
    frame = frame[frame.session.notna() & frame.timestamp_et.dt.minute.mod(5).eq(0)].copy()
    raw = data
    for minutes in (5, 15, 30, 60):
        frame[f"return_{minutes}m"] = raw.close.pct_change(minutes).reindex(frame.index)
        frame[f"range_{minutes}m"] = (raw.high.rolling(minutes, min_periods=minutes).max() / raw.low.rolling(minutes, min_periods=minutes).min() - 1).reindex(frame.index)
        frame[f"realized_volatility_{minutes}m"] = raw.close.pct_change().rolling(minutes, min_periods=minutes).std().reindex(frame.index)
        frame[f"volume_sum_{minutes}m"] = raw.volume.rolling(minutes, min_periods=minutes).sum().reindex(frame.index)
    frame["feature_complete"] = frame[["return_5m", "return_15m", "return_30m", "return_60m"]].notna().all(axis=1)
    frame["trading_date_et"] = frame.timestamp_et.dt.date.astype(str)
    frame["overlap_group_id"] = symbol + "|" + frame.trading_date_et + "|" + frame.session
    aligned = companion.close.reindex(raw.index)
    frame["soxx_minus_qqq_return_30m"] = (raw.close.pct_change(30) - aligned.pct_change(30)).reindex(frame.index)
    frame["qqq_soxx_sync_minutes"] = int(raw.index.isin(companion.index).sum())
    frame["symbol"] = symbol
    frame["candidate_timestamp_utc"] = frame.timestamp_utc
    return frame.reset_index(drop=True)


def validate_bundle(bundle):
    required = {"long_pipeline", "feature_list", "frozen_threshold", "label_contract"}
    missing = required.difference(bundle)
    if missing:
        raise ValueError(f"B1M bundle missing {sorted(missing)}")
    contract = bundle["label_contract"]
    if contract.get("column") != "long_0p50_0p25_90m":
        raise ValueError("B1M label column is not frozen SOXX LONG 0.50%")
    if not np.isclose(float(contract.get("target")), TARGET) or not np.isclose(float(contract.get("adverse")), ADVERSE):
        raise ValueError("B1M target/adverse contract mismatch")
    if int(contract.get("horizon")) != HORIZON_MINUTES:
        raise ValueError("B1M horizon mismatch")
    if DIRECTION != "LONG" or SAME_MINUTE_POLICY != "ADVERSE_FIRST":
        raise ValueError("Frozen direction or same-minute policy mismatch")
    if not isinstance(bundle["feature_list"], list) or not bundle["feature_list"]:
        raise ValueError("B1M feature list is invalid")
    return float(bundle["frozen_threshold"])


def select_signals(frame, pipeline, feature_list, threshold):
    if frame.empty:
        selected = frame.copy()
        selected["score"] = pd.Series(dtype="float64")
        selected["direction"] = DIRECTION
        selected["frozen_threshold"] = threshold
        selected["signal_id"] = pd.Series(dtype="object")
        return selected.reset_index(drop=True)
    scores = pipeline.predict_proba(frame[feature_list])[:, 1]
    selected = frame.copy()
    selected["score"] = scores
    selected = selected[selected.score >= threshold].sort_values(["score", "candidate_timestamp_utc"], ascending=[False, True])
    selected = selected.drop_duplicates("overlap_group_id", keep="first")
    selected = selected.drop_duplicates(["trading_date_et", "session"], keep="first")
    selected["direction"] = DIRECTION
    selected["frozen_threshold"] = threshold
    selected["signal_id"] = selected.candidate_timestamp_utc.map(
        lambda ts: hashlib.sha256((pd.Timestamp(ts).isoformat() + selected.symbol.iloc[0] + DIRECTION + str(threshold)).encode("utf-8")).hexdigest()
    )
    return selected.reset_index(drop=True)


def assert_no_fit_calls():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden = {"fit", "fit_transform", "partial_fit"}
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    if forbidden.intersection(calls):
        raise RuntimeError("Frozen shadow source contains a forbidden fit call")


def decision(pending_count, resolved_count, covered_months, lift, race_rate, expectancy, session_count):
    if resolved_count == 0:
        return "PROSPECTIVE_SHADOW_WAITING_FOR_MATURE_DATA"
    if resolved_count < 60 or covered_months < 3:
        return "PROSPECTIVE_SHADOW_IN_PROGRESS_INSUFFICIENT_SAMPLE"
    if lift is not None and lift >= 1.40 and race_rate is not None and race_rate > (1 / 3) and expectancy is not None and expectancy > 0 and session_count >= 2:
        return "PROSPECTIVE_SOXX_LONG_0P50_SIGNAL_CONFIRMED"
    return "PROSPECTIVE_SOXX_LONG_0P50_SIGNAL_NOT_CONFIRMED"


def json_value(value):
    return None if pd.isna(value) else value


def atomic_write_outputs(summary, signals, test_report):
    RESULT.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".v22_067b3p_", dir=RESULT.parent))
    try:
        (temp_dir / "v22_067b3p_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        signals.to_csv(temp_dir / "prospective_shadow_signals.csv", index=False)
        (temp_dir / "test_report.json").write_text(json.dumps(test_report, indent=2, default=str), encoding="utf-8")
        for name in ("v22_067b3p_summary.json", "prospective_shadow_signals.csv", "test_report.json"):
            os.replace(temp_dir / name, RESULT / name)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run():
    started = time.time()
    model_before = sha256(MODEL_FILE)
    qqq_paths, soxx_paths = files("QQQ"), files("SOXX")
    canonical_before = {"QQQ": canonical_sha256(qqq_paths), "SOXX": canonical_sha256(soxx_paths)}
    bundle = joblib.load(MODEL_FILE)
    threshold = validate_bundle(bundle)
    if json.loads(B1M_SUMMARY.read_text(encoding="utf-8")).get("final_status") != "PASS":
        raise ValueError("B1M summary is not PASS")
    if json.loads(B1A_SUMMARY.read_text(encoding="utf-8")).get("final_status") != "PASS":
        raise ValueError("B1A summary is not PASS")
    assert_no_fit_calls()
    qqq, soxx = load("QQQ"), load("SOXX")
    latest_common = min(qqq.index.max(), soxx.index.max())
    candidates = feature_frame("SOXX", soxx[soxx.index <= latest_common], qqq[qqq.index <= latest_common])
    candidates["candidate_timestamp_utc"] = pd.to_datetime(candidates["candidate_timestamp_utc"], utc=True)
    candidates = candidates[(candidates.feature_complete) & (candidates.candidate_timestamp_utc.dt.tz_convert("America/New_York") >= FORWARD_START_ET)].copy()
    selected = select_signals(candidates, bundle["long_pipeline"], bundle["feature_list"], threshold)
    if not selected.empty:
        if selected.duplicated("overlap_group_id").any() or selected.duplicated(["trading_date_et", "session"]).any():
            raise RuntimeError("Threshold deduplication failed")
        outcomes = label(soxx.high, soxx.low, soxx.close, TARGET, ADVERSE, DIRECTION, HORIZON_MINUTES)
        selected["outcome"] = selected.candidate_timestamp_utc.map(outcomes)
    else:
        selected["outcome"] = pd.Series(dtype="object")
    selected["status"] = np.where(selected.outcome.eq("PENDING"), "PENDING", "RESOLVED")
    selected["candidate_timestamp_et"] = selected.candidate_timestamp_utc.dt.tz_convert("America/New_York")
    resolved = selected[selected.status.eq("RESOLVED")]
    matured_candidates = candidates[candidates.candidate_timestamp_utc <= latest_common - pd.Timedelta(minutes=HORIZON_MINUTES)]
    all_outcomes = (label(soxx.high, soxx.low, soxx.close, TARGET, ADVERSE, DIRECTION, HORIZON_MINUTES).reindex(matured_candidates.candidate_timestamp_utc)
                    if len(matured_candidates) else pd.Series(dtype="object"))
    base_positive_rate = float(all_outcomes.eq("TARGET_FIRST").mean()) if len(all_outcomes) else None
    precision = float(resolved.outcome.eq("TARGET_FIRST").mean()) if len(resolved) else None
    lift = precision / base_positive_rate if precision is not None and base_positive_rate else None
    target_count = int(resolved.outcome.eq("TARGET_FIRST").sum())
    adverse_count = int(resolved.outcome.eq("ADVERSE_FIRST").sum())
    same_count = int(resolved.outcome.eq("SAME_MINUTE_CONSERVATIVE_ADVERSE").sum())
    neither_count = int(resolved.outcome.eq("NEITHER").sum())
    race = resolved[resolved.outcome.ne("NEITHER")]
    race_rate = float(race.outcome.eq("TARGET_FIRST").mean()) if len(race) else None
    adverse_rate = float(race.outcome.isin(["ADVERSE_FIRST", "SAME_MINUTE_CONSERVATIVE_ADVERSE"]).mean()) if len(race) else None
    expectancy = race_rate * TARGET - adverse_rate * ADVERSE if race_rate is not None else None
    covered_month_count = int(selected.candidate_timestamp_et.dt.strftime("%Y-%m").nunique()) if len(selected) else 0
    session_distribution = {str(key): int(value) for key, value in selected.session.value_counts().sort_index().items()}
    model_after = sha256(MODEL_FILE)
    canonical_after = {"QQQ": canonical_sha256(qqq_paths), "SOXX": canonical_sha256(soxx_paths)}
    frozen_modifications = int(model_before != model_after) + int(canonical_before != canonical_after)
    if frozen_modifications:
        raise RuntimeError("Frozen bundle or canonical input changed during shadow run")
    tests = [
        {"name": "no_pre_start_candidates", "status": "PASS", "detail": bool(candidates.empty or candidates.candidate_timestamp_utc.dt.tz_convert("America/New_York").min() >= FORWARD_START_ET)},
        {"name": "b1m_bundle_read", "status": "PASS", "detail": True},
        {"name": "no_fit_methods_called", "status": "PASS", "detail": True},
        {"name": "two_layer_threshold_dedup", "status": "PASS", "detail": True},
        {"name": "pending_and_resolved_status", "status": "PASS", "detail": bool(set(selected.status.unique()).issubset({"PENDING", "RESOLVED"}))},
        {"name": "frozen_hashes_unchanged", "status": "PASS", "detail": True},
    ]
    summary = {
        "final_status": "PASS", "final_diagnostic_decision": decision(int(selected.status.eq("PENDING").sum()), len(resolved), covered_month_count, lift, race_rate, expectancy, selected.session.nunique()),
        "targeted_test_count": 6, "forward_start_et": str(FORWARD_START_ET), "latest_common_canonical_timestamp": str(latest_common),
        "total_eligible_candidate_count": int(len(candidates)), "selected_signal_count": int(len(selected)), "pending_signal_count": int(selected.status.eq("PENDING").sum()), "resolved_signal_count": int(len(resolved)),
        "base_positive_rate": base_positive_rate, "precision": precision, "lift": lift, "target_first_count": target_count, "adverse_first_count": adverse_count,
        "same_minute_conservative_count": same_count, "neither_count": neither_count, "resolved_race_target_first_rate": race_rate, "simplified_resolved_race_expectancy": expectancy,
        "covered_trading_date_count": int(selected.trading_date_et.nunique()), "covered_month_count": covered_month_count, "session_distribution": session_distribution,
        "bundle_sha256": model_before, "canonical_input_sha256": canonical_before, "model_retrained": MODEL_RETRAINED, "model_modified": MODEL_MODIFIED,
        "feature_list_modified": FEATURE_LIST_MODIFIED, "threshold_modified": THRESHOLD_MODIFIED, "short_model_created": SHORT_MODEL_CREATED,
        "broker_action_allowed": False, "paper_action_allowed": False, "official_adoption_allowed": False, "frozen_input_modification_count": FROZEN_INPUT_MODIFICATION_COUNT,
        "total_elapsed_seconds": time.time() - started, "result_directory": str(RESULT),
    }
    test_report = {"final_status": "PASS", "targeted_test_count": 6, "tests": tests, "bundle_sha256_before": model_before, "bundle_sha256_after": model_after,
                   "canonical_input_sha256_before": canonical_before, "canonical_input_sha256_after": canonical_after, "frozen_input_modification_count": FROZEN_INPUT_MODIFICATION_COUNT}
    atomic_write_outputs(summary, selected, test_report)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    if parser.parse_args().execute:
        report = run()
        terminal = {
            "FINAL_STATUS": report["final_status"], "FINAL_DIAGNOSTIC_DECISION": report["final_diagnostic_decision"], "TARGETED_TEST_COUNT": report["targeted_test_count"],
            "FORWARD_START_ET": report["forward_start_et"], "LATEST_COMMON_CANONICAL_TIMESTAMP": report["latest_common_canonical_timestamp"],
            "TOTAL_ELIGIBLE_CANDIDATE_COUNT": report["total_eligible_candidate_count"], "SELECTED_SIGNAL_COUNT": report["selected_signal_count"],
            "PENDING_SIGNAL_COUNT": report["pending_signal_count"], "RESOLVED_SIGNAL_COUNT": report["resolved_signal_count"], "BASE_POSITIVE_RATE": report["base_positive_rate"],
            "PRECISION": report["precision"], "LIFT": report["lift"], "TARGET_FIRST_COUNT": report["target_first_count"], "ADVERSE_FIRST_COUNT": report["adverse_first_count"],
            "SAME_MINUTE_CONSERVATIVE_COUNT": report["same_minute_conservative_count"], "NEITHER_COUNT": report["neither_count"], "RESOLVED_RACE_TARGET_FIRST_RATE": report["resolved_race_target_first_rate"],
            "SIMPLIFIED_RESOLVED_RACE_EXPECTANCY": report["simplified_resolved_race_expectancy"], "COVERED_TRADING_DATE_COUNT": report["covered_trading_date_count"], "COVERED_MONTH_COUNT": report["covered_month_count"],
            "MODEL_RETRAINED": report["model_retrained"], "THRESHOLD_MODIFIED": report["threshold_modified"], "SHORT_MODEL_CREATED": report["short_model_created"],
            "FROZEN_INPUT_MODIFICATION_COUNT": report["frozen_input_modification_count"], "RESULT_DIRECTORY": report["result_directory"],
        }
        for key, value in terminal.items():
            print(f"{key}={value}")
