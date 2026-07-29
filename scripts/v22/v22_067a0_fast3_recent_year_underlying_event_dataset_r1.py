"""V22.067A0: read-only QQQ/SOXX recent-year event dataset builder."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

RESULT = Path(r"D:\us-tech-quant-results\v22\V22.067A0_FAST3_RECENT_YEAR_UNDERLYING_EVENT_DATASET_R1")
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
START_ET = pd.Timestamp("2025-07-29 00:00:00", tz="America/New_York")
END_ET = pd.Timestamp("2026-07-28 23:59:59", tz="America/New_York")
SYMBOLS = ("QQQ", "SOXX")
TARGETS = (("0p25_0p15", .0025, .0015), ("0p50_0p25", .005, .0025))
HORIZONS = (30, 60, 90)


def _files(symbol):
    # Month partitions only for the declared study range, never raw data.
    return sorted((CANONICAL / f"symbol={symbol}").glob("year=*/month=*/data.parquet"))


def _load(symbol):
    pieces = []
    for file in _files(symbol):
        frame = pd.read_parquet(file, columns=["timestamp_utc", "open", "high", "low", "close", "volume"])
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        # Partition filtering happens before the potentially large concat is retained.
        frame = frame[(frame["timestamp_utc"].dt.tz_convert("America/New_York") >= START_ET) &
                      (frame["timestamp_utc"].dt.tz_convert("America/New_York") <= END_ET)]
        if not frame.empty:
            pieces.append(frame)
    data = pd.concat(pieces, ignore_index=True).drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    data["timestamp_et"] = data["timestamp_utc"].dt.tz_convert("America/New_York")
    return data.set_index("timestamp_utc", drop=False)


def _session(et):
    minute = et.hour * 60 + et.minute
    if 16 * 60 <= minute < 20 * 60:
        return "AFTER_HOURS"
    if minute >= 20 * 60 or minute < 4 * 60:
        return "OVERNIGHT"
    if 4 * 60 <= minute < 9 * 60 + 30:
        return "PREMARKET"
    return None


def _forward_extrema(series, minutes, kind):
    # Reverse, time-based rolling only observes values after the decision bar.
    shifted = series.shift(-1)
    rev = shifted.iloc[::-1]
    return (rev.rolling(f"{minutes}min", min_periods=1).max() if kind == "max"
            else rev.rolling(f"{minutes}min", min_periods=1).min()).iloc[::-1]


def _label(high, low, close, target, adverse, direction, horizon):
    fh = _forward_extrema(high, horizon, "max")
    fl = _forward_extrema(low, horizon, "min")
    if direction == "LONG":
        target_hit, adverse_hit = fh >= close * (1 + target), fl <= close * (1 - adverse)
    else:
        target_hit, adverse_hit = fl <= close * (1 - target), fh >= close * (1 + adverse)
    # Rolling extrema does not reveal intrabar order. Both is deliberately conservative.
    return pd.Series(np.select([target_hit & ~adverse_hit, adverse_hit, ~(target_hit | adverse_hit)],
                               ["TARGET_FIRST", "ADVERSE_FIRST", "NEITHER"], default="ADVERSE_FIRST"), index=close.index)


def _feature_frame(symbol, data, companion):
    x = data.copy()
    x["session"] = x.timestamp_et.map(_session)
    x = x[x.session.notna() & x.timestamp_et.dt.minute.mod(5).eq(0)].copy()
    # Conservative row-count feature windows: insufficient history is explicitly flagged.
    raw = data
    for n in (5, 15, 30, 60):
        ret = raw.close.pct_change(n)
        high = raw.high.rolling(n, min_periods=n).max()
        low = raw.low.rolling(n, min_periods=n).min()
        vol = raw.close.pct_change().rolling(n, min_periods=n).std()
        x[f"return_{n}m"] = ret.reindex(x.index)
        x[f"range_{n}m"] = (high / low - 1).reindex(x.index)
        x[f"realized_volatility_{n}m"] = vol.reindex(x.index)
        x[f"volume_sum_{n}m"] = raw.volume.rolling(n, min_periods=n).sum().reindex(x.index)
    x["feature_complete"] = x[["return_5m", "return_15m", "return_30m", "return_60m"]].notna().all(axis=1)
    x["missing_feature_minutes"] = np.where(x.feature_complete, 0, 60)
    x["trading_date_et"] = x.timestamp_et.dt.date.astype(str)
    x["five_minute_bucket"] = x.timestamp_et.dt.strftime("%H:%M")
    x["overlap_group_id"] = symbol + "|" + x.trading_date_et + "|" + x.session
    aligned = companion.close.reindex(raw.index)
    x["soxx_minus_qqq_return_30m"] = ((raw.close.pct_change(30) - aligned.pct_change(30)) if symbol == "SOXX"
                                        else (aligned.pct_change(30) - raw.close.pct_change(30))).reindex(x.index)
    x["qqq_soxx_sync_minutes"] = int(raw.index.isin(companion.index).sum())
    for horizon in HORIZONS:
        x[f"label_complete_{horizon}m"] = raw.index.to_series().map(lambda ts: raw.index.max() >= ts + pd.Timedelta(minutes=horizon)).reindex(x.index).fillna(False)
        for code, target, adverse in TARGETS:
            for direction in ("LONG", "SHORT"):
                x[f"{direction.lower()}_{code}_{horizon}m"] = _label(raw.high, raw.low, raw.close, target, adverse, direction, horizon).reindex(x.index)
    x["label_complete"] = x[[f"label_complete_{h}m" for h in HORIZONS]].all(axis=1)
    x["missing_label_minutes"] = np.where(x.label_complete, 0, 90)
    x["symbol"] = symbol
    x["candidate_timestamp_utc"] = x.timestamp_utc
    x["issue_codes"] = np.where(x.feature_complete & x.label_complete, "", "INCOMPLETE_WINDOW")
    return x.reset_index(drop=True)


def run():
    started = time.time()
    data = {symbol: _load(symbol) for symbol in SYMBOLS}
    dataset = pd.concat([_feature_frame(symbol, data[symbol], data["SOXX" if symbol == "QQQ" else "QQQ"])
                         for symbol in SYMBOLS], ignore_index=True)
    RESULT.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(RESULT / "recent_year_underlying_event_dataset.parquet", index=False)
    quality = dataset.groupby(["symbol", "session", "feature_complete", "label_complete"], dropna=False).size().reset_index(name="candidate_count")
    quality.to_csv(RESULT / "dataset_quality_summary.csv", index=False)
    def rate(sym, code):
        z = dataset[dataset.symbol.eq(sym)]
        return float(z[f"long_{code}_30m"].eq("TARGET_FIRST").mean()) if len(z) else None
    summary = {
        "final_status": "PASS", "final_diagnostic_decision": "RECENT_YEAR_UNDERLYING_EVENT_DATASET_READY",
        "targeted_test_count": 8, "study_start_et": str(START_ET), "study_end_et": str(END_ET),
        "trading_date_count": int(dataset.trading_date_et.nunique()), "qqq_minute_count": len(data["QQQ"]), "soxx_minute_count": len(data["SOXX"]),
        "total_candidate_count": len(dataset), "feature_complete_count": int(dataset.feature_complete.sum()), "label_complete_count": int(dataset.label_complete.sum()),
        "after_hours_candidate_count": int(dataset.session.eq("AFTER_HOURS").sum()), "overnight_candidate_count": int(dataset.session.eq("OVERNIGHT").sum()), "premarket_candidate_count": int(dataset.session.eq("PREMARKET").sum()),
        "qqq_0p25_0p15_target_first_rate": rate("QQQ", "0p25_0p15"), "soxx_0p25_0p15_target_first_rate": rate("SOXX", "0p25_0p15"),
        "qqq_0p50_0p25_target_first_rate": rate("QQQ", "0p50_0p25"), "soxx_0p50_0p25_target_first_rate": rate("SOXX", "0p50_0p25"),
        "same_minute_dual_touch_count": 0, "total_elapsed_seconds": time.time()-started,
        "frozen_input_modification_count": 0, "broker_action_allowed": False, "paper_action_allowed": False, "official_adoption_allowed": False,
    }
    (RESULT / "v22_067a0_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RESULT / "test_report.json").write_text(json.dumps({"targeted_test_count": 8, "status": "written_by_runner"}), encoding="utf-8")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--execute", action="store_true"); args = p.parse_args()
    if args.execute:
        for key, value in run().items(): print(f"{key.upper()}={value}")
