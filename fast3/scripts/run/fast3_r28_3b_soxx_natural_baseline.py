"""FAST3 R28.3B SOXX frozen natural-baseline and event-geometry audit.

Only frozen R28.3 ledgers and the R2-manifested canonical SOXX source are
read.  No model object is loaded, fitted, or used to produce a score.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
P2 = RESULTS / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
LEDGERS = RESULTS / "scratch" / "fast3" / "r28_phase2_20260808T125629Z" / "ledgers"
FREEZE = RESULTS / "frozen" / "fast3" / "cleanroom_r2_20260808"
R1_PATH = REPO / "fast3" / "scripts" / "run" / "fast3_cleanroom_r1_preholdout.py"
OUT = RESULTS / "frozen" / "fast3" / "r28_3b_soxx_natural_baseline_20260809"
EXPECTED_R1_SHA = "6a41a129d8580c72c5dbbdc35799486f4b90e9265beba757ba9a491e8fa7d297"
HORIZON = pd.Timedelta(hours=24)
THRESHOLD = .01
SCORE_BINS = (("TOP_1PCT", .00, .01, 9), ("PCT_1_TO_2", .01, .02, 8),
              ("PCT_2_TO_5", .02, .05, 7), ("PCT_5_TO_10", .05, .10, 6),
              ("PCT_10_TO_20", .10, .20, 5), ("PCT_20_TO_40", .20, .40, 4),
              ("PCT_40_TO_60", .40, .60, 3), ("PCT_60_TO_80", .60, .80, 2),
              ("BOTTOM_20PCT", .80, 1.00, 1))
MIN_CONDITIONAL_STRATUM = 20
CONDITIONAL_LEVELS = (("L0", ["weekday", "session", "calendar_month"]),
                      ("L1", ["session", "calendar_month"]),
                      ("L2", ["weekday", "session"]), ("L3", ["session"]))


class AuditStop(RuntimeError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("r28_3b_frozen_r1", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_contract():
    manifest = json.loads((FREEZE / "cleanroom_r2_freeze_manifest.json").read_text(encoding="utf-8"))
    if sha(R1_PATH) != EXPECTED_R1_SHA or manifest["r1_source_sha256"] != EXPECTED_R1_SHA:
        raise AuditStop("STOP_FROZEN_LABEL_CONTRACT_MISMATCH")
    if manifest["target_definition"] != "directional underlying +/-1% first-touch from entry open within 24 natural hours; same-minute dual touch is AMBIGUOUS and excluded":
        raise AuditStop("STOP_FROZEN_LABEL_CONTRACT_MISMATCH")
    r1 = load_module(R1_PATH)
    if r1.LABEL_HORIZON != HORIZON:
        raise AuditStop("STOP_FROZEN_HORIZON_MISMATCH")
    return manifest, r1


def load_frozen_scores() -> pd.DataFrame:
    lineage = json.loads((P2 / "R28_PHASE2_LINEAGE.json").read_text(encoding="utf-8"))
    ledgers = {}
    for head in ("UP", "DOWN"):
        path = LEDGERS / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
        if sha(path) != lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head]:
            raise AuditStop("STOP_FROZEN_R28_3_LEDGER_IDENTITY_MISMATCH")
        x = pd.read_parquet(path)
        required = {"decision_timestamp_utc", "underlying_symbol", "target_first", "probability", "head"}
        if required.difference(x) or x.probability.isna().any() or not x["head"].eq(head).all():
            raise AuditStop("STOP_FROZEN_SCORE_MISSING")
        ledgers[head] = x.loc[x.underlying_symbol.eq("SOXX")].copy()
    up, down = ledgers["UP"], ledgers["DOWN"]
    keys = ["decision_timestamp_utc", "underlying_symbol"]
    joined = up[keys + ["target_first", "probability"]].merge(down[keys + ["target_first", "probability"]], on=keys,
        suffixes=("_up", "_down"), how="outer", validate="one_to_one", indicator=True)
    if not joined._merge.eq("both").all() or joined.decision_timestamp_utc.duplicated().any():
        raise AuditStop("STOP_FROZEN_SCORE_COHORT_MISMATCH")
    joined = joined.drop(columns="_merge")
    joined["timestamp"] = pd.to_datetime(joined.decision_timestamp_utc, utc=True)
    if joined.timestamp.max() > pd.Timestamp("2025-02-01T05:00:00Z"):
        raise AuditStop("STOP_PROSPECTIVE_DATA_USE")
    return joined.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def load_canonical() -> pd.DataFrame:
    source = json.loads((FREEZE / "cleanroom_r2_preholdout_source_manifest.json").read_text(encoding="utf-8"))
    records = [item for item in source["files"] if item["symbol"] == "SOXX"]
    if not records:
        raise AuditStop("STOP_CANONICAL_SOXX_SOURCE_MISSING")
    frames = []
    for item in records:
        path = Path(item["path"])
        if DATA not in path.parents or not path.is_file() or sha(path) != item["sha256"]:
            raise AuditStop("STOP_CANONICAL_SOURCE_IDENTITY_MISMATCH")
        frames.append(pd.read_parquet(path, columns=["timestamp_et", "timestamp_utc", "session", "open", "high", "low", "close", "volume"]))
    raw = pd.concat(frames, ignore_index=True)
    raw["timestamp_utc"] = pd.to_datetime(raw.timestamp_utc, utc=True)
    raw["timestamp_et"] = pd.to_datetime(raw.timestamp_et, utc=True).dt.tz_convert("America/New_York")
    raw = raw.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["valid"] = ((raw.open > 0) & (raw.high >= raw[["open", "low", "close"]].max(axis=1)) &
                    (raw.low <= raw[["open", "high", "close"]].min(axis=1)))
    return raw


def sparse_extrema(values: np.ndarray, maximum: bool) -> list[np.ndarray]:
    levels = [np.asarray(values, dtype=float)]
    width = 1
    while width * 2 <= len(values):
        prior = levels[-1]
        levels.append(np.maximum(prior[:-width], prior[width:]) if maximum else np.minimum(prior[:-width], prior[width:]))
        width *= 2
    return levels


def query_extrema(levels: list[np.ndarray], left: np.ndarray, right: np.ndarray, maximum: bool) -> np.ndarray:
    length = right - left + 1; level = np.floor(np.log2(length)).astype(int); width = 1 << level
    first = np.fromiter((levels[k][i] for k, i in zip(level, left)), dtype=float, count=len(left))
    second = np.fromiter((levels[k][i - w + 1] for k, i, w in zip(level, right, width)), dtype=float, count=len(left))
    return np.maximum(first, second) if maximum else np.minimum(first, second)


def first_touch_labels(up_touch: np.ndarray, down_touch: np.ndarray) -> np.ndarray:
    return np.where((up_touch >= 0) & (up_touch == down_touch), "AMBIGUOUS", np.where((up_touch >= 0) & ((down_touch < 0) | (up_touch < down_touch)), "UP_FIRST", np.where(down_touch >= 0, "DOWN_FIRST", "NO_EVENT")))


def geometry(cohort: pd.DataFrame, raw: pd.DataFrame, r1) -> pd.DataFrame:
    ns = raw.timestamp_utc.astype("int64").to_numpy()
    decision = cohort.timestamp.astype("int64").to_numpy()
    decision_i = np.searchsorted(ns, decision)
    if (decision_i >= len(raw)).any() or not np.array_equal(ns[decision_i], decision):
        raise AuditStop("STOP_FROZEN_CANDIDATE_NOT_IN_CANONICAL_SOURCE")
    valid_i = np.flatnonzero(raw.valid.to_numpy(bool))
    entry_i = valid_i[np.searchsorted(valid_i, decision_i + 1)]
    deadline = ns[entry_i] + HORIZON.value
    coverage_i, horizon_i = np.searchsorted(ns, deadline, side="left"), np.searchsorted(ns, deadline, side="right") - 1
    valid_horizon = (coverage_i < len(raw)) & (horizon_i > entry_i) & (raw.timestamp_et.iloc[coverage_i].to_numpy() <= r1.DEVELOPMENT_END)
    if not valid_horizon.all():
        raise AuditStop("STOP_FROZEN_CANDIDATE_HORIZON_INCOMPLETE")
    high_tree, high_size = r1.build_tree(raw.high.to_numpy(float), True)
    low_tree, low_size = r1.build_tree(raw.low.to_numpy(float), False)
    entry = raw.open.to_numpy(float)[entry_i]
    up_touch = np.fromiter((r1.first_cross(high_tree, high_size, int(a), int(b), float(p * (1 + THRESHOLD)), True) for a, b, p in zip(entry_i, horizon_i, entry)), dtype=int, count=len(cohort))
    down_touch = np.fromiter((r1.first_cross(low_tree, low_size, int(a), int(b), float(p * (1 - THRESHOLD)), False) for a, b, p in zip(entry_i, horizon_i, entry)), dtype=int, count=len(cohort))
    labels = first_touch_labels(up_touch, down_touch)
    expected_up, expected_down = labels == "UP_FIRST", labels == "DOWN_FIRST"
    if not (np.array_equal(expected_up.astype(int), cohort.target_first_up.to_numpy(int)) and np.array_equal(expected_down.astype(int), cohort.target_first_down.to_numpy(int))):
        raise AuditStop("STOP_FROZEN_LABEL_RECONCILIATION_FAILURE")
    highs, lows = sparse_extrema(raw.high.to_numpy(float), True), sparse_extrema(raw.low.to_numpy(float), False)
    out = cohort.copy(); out["entry_timestamp"] = raw.timestamp_utc.iloc[entry_i].to_numpy(); out["horizon_timestamp"] = raw.timestamp_utc.iloc[horizon_i].to_numpy()
    out["reference_price"] = entry; out["mfe_24h"] = query_extrema(highs, entry_i, horizon_i, True) / entry - 1; out["mae_24h"] = query_extrema(lows, entry_i, horizon_i, False) / entry - 1
    out["terminal_return_24h"] = raw.close.to_numpy(float)[horizon_i] / entry - 1; out["label"] = labels
    out["any_up_24h"] = out.mfe_24h > 0; out["any_down_24h"] = out.mae_24h < 0; out["plus_threshold_24h"] = out.mfe_24h >= THRESHOLD; out["minus_threshold_24h"] = out.mae_24h <= -THRESHOLD
    touch = np.where(labels == "UP_FIRST", up_touch, np.where(labels == "DOWN_FIRST", down_touch, -1))
    out["time_to_event_minutes"] = np.where(touch >= 0, (ns[np.maximum(touch, 0)] - decision) / 60_000_000_000, np.nan)
    local = out.timestamp.dt.tz_convert("America/New_York"); out["weekday"] = local.dt.day_name(); out["calendar_month"] = local.dt.strftime("%Y-%m"); out["calendar_year"] = local.dt.year.astype(str)
    out["session"] = raw.session.iloc[decision_i].astype(str).to_numpy(); out["hour_bucket"] = (local.dt.hour // 4 * 4).map(lambda hour: f"{hour:02d}-{hour + 3:02d}")
    return out


def rate(value) -> float:
    return float(pd.Series(value).mean())


def natural_summary(x: pd.DataFrame) -> pd.DataFrame:
    rows = [{"metric": "TOTAL_ELIGIBLE_SOXX_CANDIDATES", "count": len(x), "rate": 1.0}]
    for name, mask in (("ANY_UP_24H", x.any_up_24h), ("ANY_DOWN_24H", x.any_down_24h), ("PLUS_THRESHOLD_24H", x.plus_threshold_24h), ("MINUS_THRESHOLD_24H", x.minus_threshold_24h), ("UP_FIRST", x.label.eq("UP_FIRST")), ("DOWN_FIRST", x.label.eq("DOWN_FIRST")), ("NO_EVENT", x.label.eq("NO_EVENT")), ("TIE_OR_AMBIGUOUS", x.label.eq("AMBIGUOUS"))):
        rows.append({"metric": name, "count": int(mask.sum()), "rate": rate(mask)})
    return pd.DataFrame(rows)


def bucket_baseline(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dimension in ("weekday", "session", "hour_bucket", "calendar_year", "calendar_month"):
        for key, part in x.groupby(dimension, sort=True):
            rows.append({"dimension": dimension, "bucket": str(key), "candidate_count": len(part), "any_up_rate": rate(part.any_up_24h), "any_down_rate": rate(part.any_down_24h), "plus_threshold_rate": rate(part.plus_threshold_24h), "minus_threshold_rate": rate(part.minus_threshold_24h), "up_first_rate": rate(part.label.eq("UP_FIRST")), "down_first_rate": rate(part.label.eq("DOWN_FIRST")), "no_event_rate": rate(part.label.eq("NO_EVENT"))})
    return pd.DataFrame(rows)


def ranked(x: pd.DataFrame, score: str) -> pd.DataFrame:
    out = x.copy(); out["score_rank_pct"] = np.nan
    order = out.sort_values([score, "timestamp"], ascending=[False, True], kind="mergesort").index
    out.loc[order, "score_rank_pct"] = np.arange(1, len(out) + 1) / len(out)
    return out


def top(x: pd.DataFrame, score: str, fraction: float) -> pd.DataFrame:
    return x.sort_values([score, "timestamp"], ascending=[False, True], kind="mergesort").head(int(np.ceil(len(x) * fraction)))


def score_event_table(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, summary = [], {}
    for head, score, label in (("UP", "probability_up", "UP_FIRST"), ("DOWN", "probability_down", "DOWN_FIRST")):
        z, base = ranked(x, score), rate(x.label.eq(label))
        for name, lower, upper, ordinal in SCORE_BINS:
            part = z.loc[(z.score_rank_pct > lower) & (z.score_rank_pct <= upper)]
            event = rate(part.label.eq(label)); rows.append({"head": head, "bucket": name, "bucket_ordinal": ordinal, "candidate_count": len(part), "event_count": int(part.label.eq(label).sum()), "event_rate": event, "natural_base_rate": base, "absolute_probability_gain": event - base, "relative_lift": event / base})
        summary[head] = {"natural_base_rate": base, **{f"top{int(f * 100)}_event_rate": rate(top(x, score, f).label.eq(label)) for f in (.01, .05, .10, .20)}}
    table = pd.DataFrame(rows); return table, summary


def event_geometry(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, output = [], {}
    for head, score, label, sign in (("UP", "probability_up", "UP_FIRST", 1), ("DOWN", "probability_down", "DOWN_FIRST", -1)):
        z = ranked(x, score); events = z.loc[z.label.eq(label)]
        for name, lower, upper, ordinal in SCORE_BINS:
            part = events.loc[(events.score_rank_pct > lower) & (events.score_rank_pct <= upper)].time_to_event_minutes
            rows.append({"head": head, "bucket": name, "bucket_ordinal": ordinal, "count": len(part), "median_time_to_event": float(part.median()), "mean_time_to_event": float(part.mean()), "p10": float(part.quantile(.10)), "p25": float(part.quantile(.25)), "p75": float(part.quantile(.75)), "p90": float(part.quantile(.90))})
        output[head] = float(events[[score, "time_to_event_minutes"]].corr(method="spearman").iloc[0, 1] * -1)
    return pd.DataFrame(rows), output


def magnitude_table(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, metrics = [], {}
    for head, score in (("UP", "probability_up"), ("DOWN", "probability_down")):
        z = ranked(x, score)
        for name, lower, upper, ordinal in SCORE_BINS:
            part = z.loc[(z.score_rank_pct > lower) & (z.score_rank_pct <= upper)]
            rows.append({"head": head, "bucket": name, "bucket_ordinal": ordinal, "candidate_count": len(part), "mean_mfe": float(part.mfe_24h.mean()), "median_mfe": float(part.mfe_24h.median()), "mean_mae": float(part.mae_24h.mean()), "median_mae": float(part.mae_24h.median()), "mean_terminal_return": float(part.terminal_return_24h.mean()), "median_terminal_return": float(part.terminal_return_24h.median())})
        metrics[head] = {"mfe_spearman": float(z[[score, "mfe_24h"]].corr(method="spearman").iloc[0, 1]), "mae_spearman": float(-z[[score, "mae_24h"]].corr(method="spearman").iloc[0, 1]), "terminal_return_spearman": float(z[[score, "terminal_return_24h"]].corr(method="spearman").iloc[0, 1])}
    metrics["DOWN"]["terminal_return_spearman"] *= -1
    return pd.DataFrame(rows), metrics


def conditional_baseline(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for head, score, label in (("UP", "probability_up", "UP_FIRST"), ("DOWN", "probability_down", "DOWN_FIRST")):
        selected, baseline, levels = top(x, score, .05).copy(), x.copy(), []
        selected["conditional_base_rate"] = np.nan
        for level, fields in CONDITIONAL_LEVELS:
            pools = baseline.groupby(fields).label.apply(lambda y: rate(y.eq(label))).rename("base").to_frame()
            counts = baseline.groupby(fields).size().rename("count").to_frame()
            lookup = pools.join(counts)
            key = pd.MultiIndex.from_frame(selected[fields]); values = lookup.reindex(key)
            use = selected.conditional_base_rate.isna().to_numpy() & (values["count"].to_numpy() >= MIN_CONDITIONAL_STRATUM)
            selected.loc[selected.index[use], "conditional_base_rate"] = values["base"].to_numpy()[use]; levels.extend([level] * int(use.sum()))
        if selected.conditional_base_rate.isna().any(): raise AuditStop("STOP_CONDITIONAL_BASELINE_UNMATCHED")
        event = rate(selected.label.eq(label)); base = float(selected.conditional_base_rate.mean())
        rows.append({"head": head, "selected_top5_count": len(selected), "selected_event_rate": event, "conditional_natural_base_rate": base, "conditional_absolute_gain": event - base, "conditional_lift": event / base, **{f"conditional_match_{level}_count": levels.count(level) for level, _ in CONDITIONAL_LEVELS}, "conditional_unmatched_count": 0})
    return pd.DataFrame(rows)


def classify(events: pd.DataFrame, times: dict, magnitude: dict, conditional: pd.DataFrame) -> tuple[str, dict]:
    erho = events.groupby("head").apply(lambda x: x[["bucket_ordinal", "event_rate"]].corr(method="spearman").iloc[0, 1], include_groups=False).to_dict()
    event_ok, speed_ok = all(v >= .70 for v in erho.values()), all(v >= .10 for v in times.values())
    magnitude_ok = magnitude["UP"]["mfe_spearman"] >= .10 and magnitude["DOWN"]["mae_spearman"] >= .10 and all(v["terminal_return_spearman"] >= .10 for v in (magnitude["UP"], magnitude["DOWN"]))
    raw_top = {head: float(events.loc[(events["head"] == head) & (events.bucket == "TOP_1PCT"), "relative_lift"].iloc[0]) for head in ("UP", "DOWN")}
    conditional_lift = dict(zip(conditional["head"], conditional.conditional_lift))
    time_explains = all(conditional_lift[h] <= 1 + .25 * (raw_top[h] - 1) for h in ("UP", "DOWN"))
    if time_explains: label = "E_TIME_STRUCTURE_EXPLAINS_MOST_PREDICTIVE_LIFT"
    elif event_ok and speed_ok and magnitude_ok: label = "D_EVENT_PROBABILITY_SPEED_AND_MAGNITUDE_EDGE"
    elif event_ok and magnitude_ok: label = "C_EVENT_PROBABILITY_AND_MAGNITUDE_EDGE"
    elif event_ok and speed_ok: label = "A_EVENT_PROBABILITY_AND_SPEED_EDGE"
    elif event_ok: label = "B_EVENT_PROBABILITY_ONLY"
    else: label = "F_INCOMPLETE_OR_INVALID"
    return label, {"event_rate_spearman": erho, "event_probability": event_ok, "event_speed": speed_ok, "event_magnitude": magnitude_ok, "terminal_return": magnitude_ok, "time_structure_explains": time_explains}


def run() -> dict:
    contract, r1 = load_contract(); cohort, raw = load_frozen_scores(), load_canonical(); x = geometry(cohort, raw, r1)
    natural, time_table = natural_summary(x), bucket_baseline(x); events, score_summary = score_event_table(x); timing, time_rho = event_geometry(x); magnitude, magnitude_rho = magnitude_table(x); conditional = conditional_baseline(x)
    counts = x.label.value_counts(); reconciliation = int(counts.sum()) == len(x) and int(counts.get("UP_FIRST", 0) + counts.get("DOWN_FIRST", 0) + counts.get("NO_EVENT", 0) + counts.get("AMBIGUOUS", 0)) == len(x)
    if not reconciliation or counts.get("AMBIGUOUS", 0): raise AuditStop("STOP_FROZEN_LABEL_RECONCILIATION_FAILURE")
    classification, claims = classify(events, time_rho, magnitude_rho, conditional)
    if OUT.exists(): raise AuditStop("STOP_R28_3B_OUTPUT_PATH_EXISTS")
    OUT.mkdir(parents=True)
    for name, table in (("R28_3B_SOXX_NATURAL_BASELINE.csv", natural), ("R28_3B_SOXX_NATURAL_BASELINE_BY_BUCKET.csv", time_table), ("R28_3B_SCORE_VS_EVENT_RATE.csv", events), ("R28_3B_SCORE_VS_TIME_TO_EVENT.csv", timing), ("R28_3B_SCORE_VS_EVENT_GEOMETRY.csv", magnitude), ("R28_3B_CONDITIONAL_BASELINE.csv", conditional)):
        table.to_csv(OUT / name, index=False)
    result = {"status": "PASS", "classification": classification, "candidate_universe_source": str(LEDGERS), "label_contract_source": str(R1_PATH), "price_source": str(FREEZE / "cleanroom_r2_preholdout_source_manifest.json"), "timezone": "America/New_York", "horizon": "24 natural hours from first subsequent valid one-minute open", "up_threshold": THRESHOLD, "down_threshold": -THRESHOLD, "constraints": {"model_retrain_count": 0, "post_freeze_rescoring_count": 0, "prospective_data_used": False, "data_root_write_count": 0, "live_trading_allowed": False}, "total_eligible_soxx_candidates": len(x), "dropped_row_count": 0, "dropped_row_reasons": {}, "reconciliation_pass": reconciliation, "natural_baseline": natural.to_dict(orient="records"), "score_summary": score_summary, "time_to_event_spearman": time_rho, "magnitude_spearman": magnitude_rho, "conditional": conditional.to_dict(orient="records"), "claims": claims, "r29_allowed_to_resume": False, "live_trading_allowed": False}
    (OUT / "R28_3B_SUMMARY.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUT / "R28_3B_REPORT.md").write_text("# FAST3 R28.3B SOXX Natural Baseline and Event Geometry Audit\n\n" + json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    try: print(json.dumps(run(), indent=2))
    except AuditStop as exc: print(str(exc)); raise SystemExit(2)
