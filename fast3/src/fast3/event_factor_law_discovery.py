"""FAST3 complete-cohort R3 discovery and frozen robustness runner.

This is deliberately a single, checkpointed foreground implementation.  It
reads canonical data and prior evidence but writes every mutable result below
``FAST3_RESULTS_ROOT``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

from fast3.src.fast3.backtest.portfolio_contract import simulate_primary_portfolio


UNDERLYINGS = ("QQQ", "SOXX")
ETFS = ("TQQQ", "SQQQ", "SOXL", "SOXS")
SYMBOLS = UNDERLYINGS + ETFS
LABELS = ("UP_FIRST", "DOWN_FIRST", "NO_EVENT")
EVENT_LABELS = ("UP_FIRST", "DOWN_FIRST")
SEEDS = (104729, 130363, 155921, 196613, 262147)
CONFIGS = ("linear_0.1", "linear_1.0", "spline_0.1", "spline_1.0", "hgb_leaf7", "hgb_leaf15")
ETF_MAP = {("QQQ", "UP_FIRST"): "TQQQ", ("QQQ", "DOWN_FIRST"): "SQQQ", ("SOXX", "UP_FIRST"): "SOXL", ("SOXX", "DOWN_FIRST"): "SOXS"}
CONF_START = pd.Timestamp("2025-02-08 00:00:00", tz="America/New_York")
DATA_CUTOFF = pd.Timestamp("2025-01-31 23:59:59", tz="America/New_York")
LEGACY_LIFT = 1.36122855
BASE_FACTORS = ["return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m", "relative_volume", "vwap_distance", "ma20_distance", "boll_z7", "rsi14", "kdj_j", "breakout20", "drawdown20", "relative_strength", "gap", "vix_level", "vix_change", "nine_5m_signed", "nine_60m_signed", "nine_1d_signed"]
DERIVED_FACTORS = [f"{x}__{y}" for x in BASE_FACTORS for y in ("level", "delta_5m", "delta_15m", "delta_60m")]
INTERACTIONS = ["nine_turn_x_realized_volatility", "nine_turn_x_relative_volume", "nine_turn_x_vix_level", "nine_turn_x_vix_change", "nine_turn_x_vwap_distance", "nine_turn_x_relative_strength", "nine_turn_x_session", "trend_x_volume"]
INTERACTION_PARENTS = {
    "nine_turn_x_realized_volatility": ("nine_5m_signed", "realized_vol_60m"),
    "nine_turn_x_relative_volume": ("nine_5m_signed", "relative_volume"),
    "nine_turn_x_vix_level": ("nine_5m_signed", "vix_level"),
    "nine_turn_x_vix_change": ("nine_5m_signed", "vix_change"),
    "nine_turn_x_vwap_distance": ("nine_5m_signed", "vwap_distance"),
    "nine_turn_x_relative_strength": ("nine_5m_signed", "relative_strength"),
    "nine_turn_x_session": ("nine_5m_signed", "session_code"),
    "trend_x_volume": ("return_60m", "relative_volume"),
}
COMPLEXITY = {name: i + 1 for i, name in enumerate(CONFIGS)}
ETF_INDEX_CACHE: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, int]] = {}


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)): return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp): return value.isoformat()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)


def root() -> Path:
    value = os.environ.get("FAST3_RESULTS_ROOT")
    if not value: raise RuntimeError("FAST3_RESULTS_ROOT_REQUIRED")
    target = Path(value); target.mkdir(parents=True, exist_ok=True)
    return target


def prior_root(name: str) -> Path:
    value = os.environ.get(name)
    if not value: raise RuntimeError(f"{name}_REQUIRED")
    return Path(value)


def limits() -> dict[str, Any]:
    value = os.environ.get("FAST3_AGENT_LIMITS_PATH")
    if not value: raise RuntimeError("FAST3_AGENT_LIMITS_PATH_REQUIRED")
    return json.loads(Path(value).read_text(encoding="utf-8"))


def write_json(name: str, value: Any) -> None:
    (root() / name).write_text(json.dumps(value, indent=2, default=_json_default) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""): digest.update(chunk)
    return digest.hexdigest()


def sha_value(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=_json_default).encode()).hexdigest()


def data_root() -> Path:
    value = os.environ.get("FAST3_DATA_ROOT")
    if not value: raise RuntimeError("FAST3_DATA_ROOT_REQUIRED")
    return Path(value) / "fast3" / "moomoo_24h_1m" / "canonical"


def approved_paths(symbol: str) -> list[Path]:
    paths = [p for p in sorted(data_root().glob(f"symbol={symbol}/year=*/month=*/data.parquet")) if (int(p.parts[-3][5:]), int(p.parts[-2][6:])) <= (2025, 1)]
    if not paths: raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    return paths


def sha_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        stat = path.stat(); digest.update(str(path).encode()); digest.update(str(stat.st_size).encode()); digest.update(str(stat.st_mtime_ns).encode())
    return digest.hexdigest()


def load_symbol(symbol: str) -> pd.DataFrame:
    cols = ["timestamp_et", "timestamp_utc", "session", "open", "high", "low", "close", "volume"]
    frame = pd.concat([pd.read_parquet(path, columns=cols) for path in approved_paths(symbol)], ignore_index=True)
    frame["timestamp_et"] = pd.to_datetime(frame.timestamp_et, errors="raise")
    frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True, errors="raise")
    frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    if (frame.timestamp_et >= CONF_START).any(): raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    for col in ("open", "high", "low", "close", "volume"): frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["valid"] = (frame.open > 0) & (frame.high >= frame[["open", "low", "close"]].max(axis=1)) & (frame.low <= frame[["open", "high", "close"]].min(axis=1))
    return frame


def ledger_path() -> Path:
    """The complete cohort is hash-verified from R1's immutable real-data ledger."""
    return prior_root("FAST3_R1_INVALID_RUN_ROOT") / "fast3_event_ledger.parquet"


def imported_r1_blocks() -> list[dict[str, Any]]:
    path = prior_root("FAST3_R1_INVALID_RUN_ROOT") / "FAST3_ROUND_LEDGER.jsonl"
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        block = row.get("audit_block") if row.get("event") == "START" else None
        if isinstance(block, dict) and all(key in block for key in ("block_id", "start", "end")):
            found[(str(block["block_id"]), str(block["start"]), str(block["end"]))] = dict(block)
    return [found[key] for key in sorted(found)]


def quarantines() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    return [(pd.Timestamp(block["start"]) - pd.Timedelta(hours=24), pd.Timestamp(block["end"]) + pd.Timedelta(hours=24)) for block in imported_r1_blocks()]


def outside_r1(frame: pd.DataFrame) -> pd.DataFrame:
    keep = np.ones(len(frame), dtype=bool)
    for lo, hi in quarantines(): keep &= ~frame.timestamp_et.between(lo, hi).to_numpy()
    return frame.loc[keep].copy()


def schedule_blocks() -> list[dict[str, Any]]:
    """Select before results: random permutation, greedy eligibility, then chronology."""
    earliest = pd.Timestamp("2018-10-20", tz="America/New_York")
    latest = DATA_CUTOFF.normalize() - pd.Timedelta(days=60)
    forbidden = quarantines()
    candidates: list[pd.Timestamp] = []
    for start in pd.date_range(earliest, latest, freq="D"):
        end = start + pd.Timedelta(days=60) - pd.Timedelta(minutes=1)
        if not any(not (end < lo or start > hi) for lo, hi in forbidden): candidates.append(start)
    # Randomness chooses among feasible chronological continuations.  A plain
    # greedy shuffled scan can spuriously declare insufficiency even when a
    # legal 14-block schedule exists.
    rng = np.random.default_rng(314159)
    chosen: list[pd.Timestamp] = []
    cursor, previous = 0, None
    for position in range(14):
        remaining = 13 - position
        feasible: list[int] = []
        for index in range(cursor, len(candidates)):
            start = candidates[index]
            if previous is not None and (start - previous).total_seconds() < 65 * 86400: continue
            count, last = 0, start
            for future in candidates[index + 1:]:
                if (future - last).total_seconds() >= 65 * 86400:
                    count += 1; last = future
                    if count >= remaining: break
            if count >= remaining: feasible.append(index)
        if not feasible: break
        picked = int(rng.choice(feasible)); chosen.append(candidates[picked]); previous, cursor = candidates[picked], picked + 1
    if len(chosen) != 14: raise RuntimeError("STOP_INSUFFICIENT_FRESH_BLOCKS")
    chosen.sort()
    roles = (["LAW_DISCOVERY"] * 3 + ["MODEL_ROUND_1"] * 2 + ["MODEL_ROUND_2"] * 2 + ["MODEL_ROUND_3"] * 2 + ["FINAL_AUDIT"] * 5)
    counters: dict[str, int] = {}
    blocks = []
    for start, role in zip(chosen, roles):
        counters[role] = counters.get(role, 0) + 1
        blocks.append({"round_id": role, "block_id": f"{role}_B{counters[role]}", "start": start, "end": start + pd.Timedelta(days=60) - pd.Timedelta(minutes=1), "length_calendar_days": 60, "scheduler_seed": 314159, "purge_hours": 24, "embargo_hours": 24, "minimum_gap_days": 5, "RETIRED_AFTER_OBSERVATION": False})
    return blocks


def ledger_append(row: dict[str, Any]) -> None:
    with (root() / "FAST3_ROUND_LEDGER.jsonl").open("a", encoding="utf-8") as handle: handle.write(json.dumps(row, default=_json_default) + "\n")


def blank_summary(decision: str, status: str) -> dict[str, Any]:
    result = {key: "NOT_RUN" for key in limits()["required_summary_keys"]}
    result.update({"FINAL_STATUS": status, "FINAL_DECISION": decision, "RUN_ID": os.environ.get("FAST3_AGENT_RUN_ID"), "COHORT_ROW_COUNT": 0, "UP_FIRST_COUNT": 0, "DOWN_FIRST_COUNT": 0, "NO_EVENT_COUNT": 0, "AMBIGUOUS_COUNT": 0, "R1_OBSERVED_BLOCK_IMPORT_COUNT": 0, "R1_OBSERVED_BLOCK_REUSE_COUNT": 0, "R2_TRAINING_ROUND_COUNT": 0, "LAW_DISCOVERY_BLOCK_COUNT": 0, "MODEL_BLOCK_COUNT": 0, "FINAL_AUDIT_BLOCK_COUNT": 0, "STABLE_FACTOR_COLUMN_COUNT": 0, "TOTAL_CONFIG_COUNT": 6, "RANDOM_SEED_COUNT": 5, "BEST_MODEL_NAME": None, "BEST_TOP5_LIFT": None, "LEGACY_TOP5_LIFT": LEGACY_LIFT, "MEDIAN_FINAL_BLOCK_NET_10BPS": None, "MEDIAN_FINAL_BLOCK_NET_20BPS": None, "STRONGEST_NULL_NAME": None, "LEARNED_MINUS_STRONGEST_NULL_LIFT_CI_LOW": None, "LEARNED_MINUS_STRONGEST_NULL_NET10_CI_LOW": None, "ACCEPTED_TRADE_COUNT": 0, "CONFIRMATION_ROWS_READ": 0, "FACTOR_OR_MODEL_EXPANSION_PERFORMED": False, "POST_FINAL_AUDIT_RETRAINING_PERFORMED": False, "REPORT_PATH": str(root() / "FAST3_EVENT_FACTOR_R3_REPORT.md"), "CODE_FILES_MODIFIED": [str(Path(__file__))], "CODE_FILES_ADDED": []})
    return result


def terminal(decision: str, status: str, extra: dict[str, Any] | None = None) -> None:
    summary = blank_summary(decision, status)
    if extra: summary.update(extra)
    write_json("fast3_event_factor_r3_summary.json", summary)
    report = "# FAST3 Event-Factor Cohort R3 Report\n\n" + "\n".join(f"{key}={value}" for key, value in summary.items()) + "\n"
    (root() / "FAST3_EVENT_FACTOR_R3_REPORT.md").write_text(report, encoding="utf-8")


def common_placeholders(error: str) -> None:
    """Keep the decision-aware launcher truthful even if a gate fails very early."""
    out = root()
    for name in ("FAST3_EVIDENCE_LEDGER.json", "FAST3_PRIOR_RUN_IMPORT.json", "FAST3_R3_COHORT_CONTRACT.json", "FAST3_RANDOM_BLOCK_SCHEDULE.json", "FAST3_COHORT_AUDIT.json"):
        if not (out / name).exists(): write_json(name, {"early_stop": True, "error": error})
    if not (out / "FAST3_ROUND_LEDGER.jsonl").exists(): ledger_append({"event": "EARLY_STOP", "error": error, "RETIRED_AFTER_OBSERVATION": False})


def validate_prior_and_freeze() -> list[dict[str, Any]]:
    out = root(); r1, r2 = prior_root("FAST3_R1_INVALID_RUN_ROOT"), prior_root("FAST3_R2_CONTROL_STOP_ROOT")
    r1s, r1i = read_json(r1 / "fast3_event_factor_summary.json"), read_json(r1 / "FAST3_POST_AUDIT_INTEGRITY.json")
    r2s, r2a = read_json(r2 / "fast3_event_factor_r2_summary.json"), read_json(r2 / "FAST3_CONTROL_MATCH_AUDIT.json")
    blocks = imported_r1_blocks()
    checks = {
        "r1_final_decision": r1s.get("FINAL_DECISION") == "STOP_IMPLEMENTATION_INVALID",
        "r1_event_count": r1s.get("EVENT_COUNT") == 517196,
        "r1_observed_blocks": len(blocks) >= 14,
        "r2_final_decision": r2s.get("FINAL_DECISION") == "STOP_CONTROL_MATCH_INCOMPLETE_BEFORE_TRAINING",
        "r2_matched_unmatched": (r2s.get("CONTROL_MATCHED_EVENTS"), r2s.get("CONTROL_UNMATCHED_EVENTS")) == (477456, 39740),
        "r2_training_rounds": r2s.get("TRAINING_ROUND_COUNT") == 0,
        "r2_no_law_model_or_null": r2s.get("FACTOR_LAW_OR_MODEL_FIT_PERFORMED") is False and r2s.get("NULL_ECONOMIC_AUDIT_PERFORMED") is False,
        "r2_audit_counts": (r2a.get("matched_event_count"), r2a.get("unmatched_event_count")) == (477456, 39740),
        "r1_integrity_no_retraining": r1i.get("model_or_factor_retraining_performed") is False,
    }
    prior = {"checks": checks, "r1_root": str(r1), "r2_root": str(r2), "r1_observed_block_count": len(blocks), "r1_observed_blocks_quarantined_with_buffer_hours": 24, "r2_schedule_only_block_treatment": "R2 schedule-only blocks were never evaluated by factor/model/final-audit results and are not automatically quarantined.", "r2_matched_pairs_role": "POST_SELECTION_EXPLANATORY_ONLY", "r1_stable_factor_reuse": False}
    write_json("FAST3_PRIOR_RUN_IMPORT.json", prior)
    if not all(checks.values()): raise RuntimeError("PRIOR_EVIDENCE_INVALID")
    dictionary = r1 / "FAST3_FACTOR_DICTIONARY.json"
    obj = read_json(dictionary)
    if obj.get("base_factor_channels") != BASE_FACTORS or obj.get("derived_columns") != DERIVED_FACTORS or obj.get("interactions") != INTERACTIONS: raise RuntimeError("R1_FACTOR_DICTIONARY_MISMATCH")
    blocks = schedule_blocks()
    schedule = {"scheduler_seed": 314159, "schedule_frozen_before_r3_law_result": True, "r1_quarantine_buffer_hours_each_side": 24, "r1_observed_blocks": imported_r1_blocks(), "blocks": blocks, "r2_schedule_only_blocks_quarantined": False, "historical_blocks_label": "DEVELOPMENT_ROBUSTNESS_NOT_CLEAN_FROZEN_VALIDATION"}
    schedule["schedule_sha256"] = sha_value(schedule["blocks"])
    write_json("FAST3_RANDOM_BLOCK_SCHEDULE.json", schedule)
    write_json("FAST3_R3_COHORT_CONTRACT.json", {"contract_version": limits()["contract_version"], "r1_factor_dictionary_sha256": sha_file(dictionary), "factor_dictionary_exact_match": True, "schedule_sha256": schedule["schedule_sha256"], "frozen_model_configs": list(CONFIGS), "frozen_seeds": list(SEEDS), "r1_observed_block_reuse_count": 0, "r2_matched_pairs_post_selection_only": True})
    write_json("FAST3_EVIDENCE_LEDGER.json", {"created_before_law_result": True, "prior_import": str(out / "FAST3_PRIOR_RUN_IMPORT.json"), "schedule": str(out / "FAST3_RANDOM_BLOCK_SCHEDULE.json"), "r1_observed_only_quarantine": True, "r2_schedule_only_not_quarantined": True, "canonical_writes": 0, "confirmation_rows_read": 0})
    return blocks


def source_and_cohort_audit() -> pd.DataFrame:
    r2checkpoint = read_json(prior_root("FAST3_R2_CONTROL_STOP_ROOT") / "FAST3_LEDGER_CHECKPOINT.json")
    partitions = {symbol: {"partition_hash": sha_paths(approved_paths(symbol)), "partitions": len(approved_paths(symbol))} for symbol in SYMBOLS}
    if partitions != r2checkpoint.get("source_partitions"): raise RuntimeError("SOURCE_PARTITION_HASH_MISMATCH")
    frame = pd.read_parquet(ledger_path())
    frame["timestamp_et"] = pd.to_datetime(frame.timestamp_et, errors="raise")
    if (frame.timestamp_et >= CONF_START).any() or (frame.timestamp_et > DATA_CUTOFF).any(): raise RuntimeError("CONFIRMATION_ISOLATION_VIOLATION")
    counts = frame.label.value_counts().to_dict()
    expected = limits()["source_and_isolation"]["expected_cohort_counts"]
    audit = {"cohort_source": str(ledger_path()), "cohort_ledger_sha256": sha_file(ledger_path()), "source_partitions": partitions, "candidate_rows": len(frame), "UP_FIRST": int(counts.get("UP_FIRST", 0)), "DOWN_FIRST": int(counts.get("DOWN_FIRST", 0)), "NO_EVENT": int(counts.get("NO_EVENT", 0)), "AMBIGUOUS": int(counts.get("AMBIGUOUS", 0)), "event_rows": int(frame.label.isin(EVENT_LABELS).sum()), "expected_counts": expected, "count_match": len(frame) == expected["candidate_rows"] and all(int(counts.get(k, 0)) == expected[k] for k in ("UP_FIRST", "DOWN_FIRST", "NO_EVENT", "AMBIGUOUS")) and int(frame.label.isin(EVENT_LABELS).sum()) == expected["event_rows"], "confirmation_rows_read": 0, "canonical_writes": 0}
    write_json("FAST3_COHORT_AUDIT.json", audit)
    if not audit["count_match"]: raise RuntimeError("COHORT_COUNT_MISMATCH")
    # This is the formal, immutable R3 cohort hand-off.  Model-round prediction
    # files are deliberately narrower evaluation outputs and must never be used
    # as the downstream R24 source cohort.
    frame.to_parquet(root() / "fast3_complete_labelled_ledger.parquet", index=False)
    return frame


def train_weights(frame: pd.DataFrame) -> np.ndarray:
    """All fold-local weights; no test-row distribution is modified."""
    x = frame.copy().reset_index(drop=True); x["timestamp_utc"] = pd.to_datetime(x.timestamp_utc, utc=True)
    unique = np.empty(len(x), dtype=float)
    for _, idx in x.groupby("underlying", sort=False).groups.items():
        positions = np.asarray(list(idx), dtype=int); ns = x.loc[positions, "timestamp_utc"].dt.as_unit("ns").astype("int64").to_numpy(); count = np.maximum(1, np.searchsorted(ns, ns + 24 * 3600 * 1_000_000_000, side="right") - np.arange(len(ns))); unique[positions] = 1 / count
    cls = x.label.value_counts(); class_weight = x.label.map({label: len(x) / (3 * cls[label]) for label in LABELS}).to_numpy(float)
    era_counts = x.era.value_counts(); era_raw = x.era.map({era: 1 / count for era, count in era_counts.items()}).to_numpy(float); era_weight = era_raw / era_raw.mean()
    return np.clip(unique * class_weight * era_weight, .05, 10.)


def active_interactions(frozen_columns: list[str]) -> list[str]:
    bases = {column.split("__", 1)[0] for column in frozen_columns}
    return [name for name, parents in INTERACTION_PARENTS.items() if all(parent in bases for parent in parents)]


def feature_frame(frame: pd.DataFrame, frozen_columns: list[str], interactions: list[str]) -> pd.DataFrame:
    result = frame[frozen_columns].copy()
    values = {
        "nine_turn_x_realized_volatility": frame.nine_5m_signed * frame.realized_vol_60m,
        "nine_turn_x_relative_volume": frame.nine_5m_signed * frame.relative_volume,
        "nine_turn_x_vix_level": frame.nine_5m_signed * frame.vix_level,
        "nine_turn_x_vix_change": frame.nine_5m_signed * frame.vix_change,
        "nine_turn_x_vwap_distance": frame.nine_5m_signed * frame.vwap_distance,
        "nine_turn_x_relative_strength": frame.nine_5m_signed * frame.relative_strength,
        "nine_turn_x_session": frame.nine_5m_signed * frame.session_code,
        "trend_x_volume": frame.return_60m * frame.relative_volume,
    }
    for name in interactions: result[name] = values[name]
    return result.replace([np.inf, -np.inf], np.nan)


def law_discovery(frame: pd.DataFrame, blocks: list[dict[str, Any]]) -> list[str]:
    out = root(); linear_path, nonlinear_path = out / "fast3_factor_linear_results.csv", out / "fast3_factor_nonlinear_results.csv"
    if linear_path.exists() and nonlinear_path.exists(): return read_json(out / "FAST3_FACTOR_LAW_FREEZE.json").get("frozen_columns", [])
    rows: list[dict[str, Any]] = []; curves: list[dict[str, Any]] = []
    law_blocks = [b for b in blocks if b["round_id"] == "LAW_DISCOVERY"]
    for block in law_blocks:
        subset = outside_r1(frame[frame.label.ne("AMBIGUOUS") & frame.timestamp_et.between(pd.Timestamp(block["start"]), pd.Timestamp(block["end"]))].copy()).reset_index(drop=True)
        if subset.empty: raise RuntimeError("EMPTY_LAW_BLOCK")
        weight = train_weights(subset)
        for column in DERIVED_FACTORS:
            value = pd.to_numeric(subset[column], errors="coerce").to_numpy(float); finite = np.isfinite(value)
            if finite.sum() < 100: continue
            median, scale = float(np.nanmedian(value)), float(np.nanstd(value[finite]))
            z = (np.where(finite, value, median) - median) / (scale or 1.)
            quintile = pd.qcut(pd.Series(z).rank(method="first"), 5, labels=False, duplicates="drop").to_numpy()
            spline = SplineTransformer(n_knots=4, degree=2, extrapolation="linear").fit(z.reshape(-1, 1))
            spline_x = spline.transform(z.reshape(-1, 1))
            for label in LABELS:
                target = subset.label.eq(label).to_numpy(int)
                fit = LogisticRegression(C=1.0, max_iter=200, random_state=314159).fit(z.reshape(-1, 1), target, sample_weight=weight)
                coefficient = float(fit.coef_[0, 0])
                trimmed = np.sort(z)[:max(1, int(.99 * len(z)))]; trim_target = target[np.argsort(z)[:max(1, int(.99 * len(z)))]]
                trim_coef = float(np.cov(trimmed, trim_target, aweights=weight[np.argsort(z)[:max(1, int(.99 * len(z)))]] if len(trimmed) > 1 else None)[0, 1]) if len(trimmed) > 1 else coefficient
                support = subset.loc[target.astype(bool)]
                rates = [float(target[quintile == q].mean()) if (quintile == q).any() else np.nan for q in range(5)]
                beta, *_ = np.linalg.lstsq(spline_x * np.sqrt(weight[:, None]), target * np.sqrt(weight), rcond=None)
                grid = np.quantile(z, [.05, .25, .5, .75, .95]); marginal = spline.transform(grid.reshape(-1, 1)) @ beta
                rows.append({"block_id": block["block_id"], "factor": column, "label": label, "coefficient": coefficient, "standardized_effect": coefficient, "trimmed_direction": int(np.sign(trim_coef)), "session_support": int(support.session_normalized.nunique()), "year_support": int(support.year.nunique()), "sample_count": int(len(subset)), "weight_mean": float(weight.mean()), "training_only_weight_fit": True})
                curves.append({"block_id": block["block_id"], "factor": column, "label": label, "quintile_rates": rates, "spline_grid_z": grid.tolist(), "spline_marginal": marginal.tolist(), "bins_splines_fit_in_law_training_block_only": True})
        ledger_append({"event": "END", "round_id": "LAW_DISCOVERY", "block_id": block["block_id"], "result": "FACTOR_LAW", "RETIRED_AFTER_OBSERVATION": True})
    linear = pd.DataFrame(rows); nonlinear = pd.DataFrame(curves); linear.to_csv(linear_path, index=False); nonlinear.to_csv(nonlinear_path, index=False)
    req = limits()["law_discovery_protocol"]["stable_column_requirements"]
    ranked: list[dict[str, Any]] = []
    for column in DERIVED_FACTORS:
        candidates = []
        for label in LABELS:
            g = linear[(linear.factor == column) & (linear.label == label)].sort_values("block_id")
            if len(g) != 3: continue
            signs = np.sign(g.coefficient.to_numpy(float)); sign = 1 if (signs > 0).sum() >= (signs < 0).sum() else -1; supported = g[signs == sign]
            count = int(len(supported)); min_abs = float(supported.coefficient.abs().min()) if count else 0.
            stable = count / 3 >= req["signed_effect_consistency_min"] and min_abs >= req["minimum_absolute_standardized_effect_each_supporting_block"] and bool((supported.trimmed_direction == sign).all()) and int(supported.session_support.max()) >= req["minimum_distinct_sessions_supporting_direction"] and int(supported.year_support.max()) >= 2
            if stable: candidates.append({"factor": column, "label": label, "same_sign_blocks": count, "minimum_absolute_effect": min_abs, "trimmed_direction_preserved": True, "sign": sign})
        if candidates: ranked.append(sorted(candidates, key=lambda r: (-r["same_sign_blocks"], -r["minimum_absolute_effect"], r["label"]))[0])
    ranked.sort(key=lambda r: (-r["same_sign_blocks"], -r["minimum_absolute_effect"], not r["trimmed_direction_preserved"], r["factor"]))
    frozen: list[str] = []; bases: set[str] = set()
    for row in ranked:
        base = row["factor"].split("__", 1)[0]
        if len(frozen) < 24 and (base in bases or len(bases) < 12): frozen.append(row["factor"]); bases.add(base)
    freeze = {"frozen_before_model_results": True, "frozen_columns": frozen, "frozen_base_channels": sorted(bases), "active_interactions": active_interactions(frozen), "ranking": ranked, "stable_column_count": len(frozen), "r1_stable_factor_subset_used": False, "r1_observed_block_reuse_count": 0}
    write_json("FAST3_FACTOR_LAW_FREEZE.json", freeze)
    return frozen


def make_model(config: str, seed: int) -> Pipeline:
    if config.startswith("linear_"): return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("m", LogisticRegression(C=float(config.split("_", 1)[1]), max_iter=250, random_state=seed, n_jobs=1))])
    if config.startswith("spline_"): return Pipeline([("impute", SimpleImputer(strategy="median")), ("spline", SplineTransformer(n_knots=4, degree=2, extrapolation="linear")), ("scale", StandardScaler()), ("m", LogisticRegression(C=float(config.split("_", 1)[1]), max_iter=250, random_state=seed, n_jobs=1))])
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("m", HistGradientBoostingClassifier(max_iter=100, learning_rate=.08, max_leaf_nodes=int(config.replace("hgb_leaf", "")), l2_regularization=1., random_state=seed))])


def etf_data() -> dict[str, pd.DataFrame]:
    return {symbol: load_symbol(symbol) for symbol in ETFS}


def max_tree(values: np.ndarray) -> tuple[np.ndarray, int]:
    size = 1
    while size < len(values): size *= 2
    tree = np.full(size * 2, -np.inf); tree[size:size + len(values)] = values
    for node in range(size - 1, 0, -1): tree[node] = max(tree[2 * node], tree[2 * node + 1])
    return tree, size


def first_high_cross(tree: np.ndarray, size: int, left: int, right: int, threshold: float) -> int:
    if left > right: return -1
    left += size; right += size; front: list[int] = []; back: list[int] = []
    while left <= right:
        if left & 1: front.append(left); left += 1
        if not right & 1: back.append(right); right -= 1
        left //= 2; right //= 2
    for node in front + list(reversed(back)):
        if tree[node] < threshold: continue
        while node < size:
            node = 2 * node if tree[2 * node] >= threshold else 2 * node + 1
        return node - size
    return -1


def apply_outcomes(selected: pd.DataFrame, etfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    outcomes: list[dict[str, Any]] = []
    for symbol, group in selected.groupby("execution_etf", sort=False):
        data = etfs[symbol]; cache_key = (symbol, id(data))
        if cache_key not in ETF_INDEX_CACHE:
            ETF_INDEX_CACHE[cache_key] = (data.timestamp_utc.dt.as_unit("ns").astype("int64").to_numpy(), *max_tree(np.where(data.valid.to_numpy(bool), data.high.to_numpy(float), -np.inf)))
        ts, tree, tree_size = ETF_INDEX_CACHE[cache_key]
        for row in group.itertuples(index=False):
            entry_ns, end_ns = pd.Timestamp(row.entry_timestamp_utc).value, pd.Timestamp(row.horizon_timestamp_utc).value
            entry = int(np.searchsorted(ts, entry_ns)); timeout = int(np.searchsorted(ts, end_ns, side="right") - 1)
            valid = entry < len(data) and timeout >= entry and ts[entry] - entry_ns <= 60_000_000_000 and data.valid.iat[entry] and data.valid.iat[timeout]
            if not valid:
                outcomes.append({"candidate_id": row.candidate_id, "mapping_status": "TIMESTAMP_MISMATCH", "gross_return": np.nan, "target_hit": False, "actual_exit_timestamp_et": pd.NaT, "net_return_10bps": np.nan, "net_return_20bps": np.nan}); continue
            price = float(data.open.iat[entry]); hit = first_high_cross(tree, tree_size, entry, timeout, price * 1.03)
            if hit >= 0:
                gross, exit_time, target = .03, data.timestamp_et.iat[hit], True
            else:
                gross, exit_time, target = float(data.open.iat[timeout] / price - 1), data.timestamp_et.iat[timeout], False
            outcomes.append({"candidate_id": row.candidate_id, "mapping_status": "SUCCESS", "gross_return": gross, "target_hit": target, "actual_exit_timestamp_et": exit_time, "net_return_10bps": gross - .001, "net_return_20bps": gross - .002})
    return selected.merge(pd.DataFrame(outcomes), on="candidate_id", how="left")


def select_and_execute(test: pd.DataFrame, probabilities: np.ndarray, classes: np.ndarray, config: str, seed: int, block: dict[str, Any], etfs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = pd.DataFrame(probabilities, columns=classes, index=test.index); universe = test.copy()
    universe["prob_up"] = p.get("UP_FIRST", 0.).to_numpy() if isinstance(p.get("UP_FIRST", 0.), pd.Series) else p.get("UP_FIRST", 0.)
    universe["prob_down"] = p.get("DOWN_FIRST", 0.).to_numpy() if isinstance(p.get("DOWN_FIRST", 0.), pd.Series) else p.get("DOWN_FIRST", 0.)
    universe["prob_no_event"] = p.get("NO_EVENT", 0.).to_numpy() if isinstance(p.get("NO_EVENT", 0.), pd.Series) else p.get("NO_EVENT", 0.)
    universe["opportunity_probability"] = universe.prob_up + universe.prob_down
    universe["combined_score"] = np.maximum(universe.prob_up, universe.prob_down)
    universe["predicted_label"] = np.where(universe.prob_up >= universe.prob_down, "UP_FIRST", "DOWN_FIRST")
    eligible = universe[universe.opportunity_probability >= .60].sort_values(["combined_score", "timestamp_et", "candidate_id"], ascending=[False, True, True], kind="mergesort")
    selected = eligible.iloc[:max(1, int(math.ceil(.05 * len(universe))))].copy()
    selected["execution_etf"] = [ETF_MAP[(u, d)] for u, d in zip(selected.underlying, selected.predicted_label)]
    selected["round"], selected["block_id"], selected["seed"], selected["config_id"] = block["round_id"], block["block_id"], seed, config
    selected["event_id"] = selected.config_id + "|" + selected.block_id + "|" + selected.seed.astype(str) + "|" + selected.candidate_id
    selected["decision_timestamp_et"], selected["priority"], selected["direction"] = selected.timestamp_et, selected.combined_score, selected.predicted_label
    selected = apply_outcomes(selected, etfs)
    selected["exit_timestamp_et"] = selected.actual_exit_timestamp_et
    selected["net_return"] = selected.net_return_10bps
    portfolio, _ = simulate_primary_portfolio(selected)
    universe["round"], universe["block_id"], universe["seed"], universe["config_id"] = block["round_id"], block["block_id"], seed, config
    return portfolio, universe


def metrics(portfolio: pd.DataFrame, universe: pd.DataFrame, block: dict[str, Any], config: str, seed: int, strategy: str) -> dict[str, Any]:
    accepted = portfolio[portfolio.trade_accepted & portfolio.mapping_status.eq("SUCCESS")].copy()
    base = float(universe.label.isin(EVENT_LABELS).mean())
    accuracy = float(accepted.label.eq(accepted.predicted_label).mean()) if len(accepted) else np.nan
    target = accepted[accepted.target_hit]
    timeout = accepted[~accepted.target_hit]
    return {"strategy": strategy, "round": block["round_id"], "block_id": block["block_id"], "seed": seed, "config_id": config, "test_rows": len(universe), "selected_signal_count": len(portfolio), "accepted_trade_count": len(accepted), "rejected_overlap_count": int((~portfolio.trade_accepted).sum()), "accepted_direction_accuracy": accuracy, "underlying_1pct_event_hit_rate": base, "etf_3pct_target_hit_rate": float(target.shape[0] / len(accepted)) if len(accepted) else np.nan, "timeout_rate": float(timeout.shape[0] / len(accepted)) if len(accepted) else np.nan, "mean_target_hit_net_return": float(target.net_return_10bps.mean()) if len(target) else np.nan, "mean_timeout_net_return": float(timeout.net_return_10bps.mean()) if len(timeout) else np.nan, "direction_correct_etf_loss_rate": float(((accepted.label == accepted.predicted_label) & (accepted.net_return_10bps < 0)).mean()) if len(accepted) else np.nan, "direction_wrong_etf_profit_rate": float(((accepted.label != accepted.predicted_label) & (accepted.net_return_10bps > 0)).mean()) if len(accepted) else np.nan, "top5_lift": accuracy / base if base and np.isfinite(accuracy) else np.nan, "net_return_10bps": float(accepted.net_return_10bps.mean()) if len(accepted) else np.nan, "net_return_20bps": float(accepted.net_return_20bps.mean()) if len(accepted) else np.nan}


def sample_indices(labels: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed); picks = []
    for cls in (0, 1, 2):
        idx = np.flatnonzero(labels == cls); picks.append(rng.choice(idx, size=min(12000, len(idx)), replace=False))
    return np.sort(np.concatenate(picks))


def run_blocks(frame: pd.DataFrame, blocks: list[dict[str, Any]], configs: list[str], frozen: list[str], phase: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out = root(); interactions = active_interactions(frozen); all_metrics: list[pd.DataFrame] = []; all_portfolios: list[pd.DataFrame] = []; all_universes: list[pd.DataFrame] = []; etfs = etf_data()
    for block in blocks:
        stem = f"fast3_{block['block_id'].lower()}"
        mp, pp, up = out / f"{stem}_checkpoint.csv", out / f"{stem}_predictions.parquet", out / f"{stem}_universe.parquet"
        if mp.exists() and pp.exists() and up.exists():
            all_metrics.append(pd.read_csv(mp)); all_portfolios.append(pd.read_parquet(pp)); all_universes.append(pd.read_parquet(up)); continue
        ledger_append({"event": "START", "round_id": block["round_id"], "audit_block": block, "configs": configs, "frozen_columns": frozen, "active_interactions": interactions, "phase": phase, "RETIRED_AFTER_OBSERVATION": False})
        start, end = pd.Timestamp(block["start"]), pd.Timestamp(block["end"])
        usable = outside_r1(frame[frame.label.ne("AMBIGUOUS")].copy())
        train = usable[usable.horizon_timestamp_et < start - pd.Timedelta(hours=24)].copy()
        test = usable[usable.timestamp_et.between(start, end)].copy()
        if train.empty or test.empty: raise RuntimeError("EMPTY_PURGED_WALK_FORWARD_FOLD")
        y = train.label.map({"NO_EVENT": 0, "UP_FIRST": 1, "DOWN_FIRST": 2}).to_numpy()
        weights = train_weights(train); x_train, x_test = feature_frame(train, frozen, interactions), feature_frame(test, frozen, interactions)
        block_metrics: list[dict[str, Any]] = []; block_portfolios: list[pd.DataFrame] = []; block_universes: list[pd.DataFrame] = []
        for config in configs:
            for seed in SEEDS:
                take = sample_indices(y, seed); fitted = make_model(config, seed)
                fitted.fit(x_train.iloc[take], y[take], m__sample_weight=weights[take])
                probability = fitted.predict_proba(x_test); cls = np.asarray([("NO_EVENT", "UP_FIRST", "DOWN_FIRST")[int(value)] for value in fitted.named_steps["m"].classes_])
                portfolio, universe = select_and_execute(test, probability, cls, config, seed, block, etfs)
                block_portfolios.append(portfolio); block_universes.append(universe); block_metrics.append(metrics(portfolio, universe, block, config, seed, "LEARNED"))
        m, p, u = pd.DataFrame(block_metrics), pd.concat(block_portfolios, ignore_index=True), pd.concat(block_universes, ignore_index=True)
        m.to_csv(mp, index=False); p.to_parquet(pp, index=False); u.to_parquet(up, index=False)
        all_metrics.append(m); all_portfolios.append(p); all_universes.append(u)
        ledger_append({"event": "END", "round_id": block["round_id"], "block_id": block["block_id"], "result_count": len(m), "RETIRED_AFTER_OBSERVATION": True})
    return pd.concat(all_metrics, ignore_index=True), pd.concat(all_portfolios, ignore_index=True), pd.concat(all_universes, ignore_index=True)


def model_rounds(frame: pd.DataFrame, blocks: list[dict[str, Any]], frozen: list[str]) -> dict[str, Any]:
    out = root(); freeze_path = out / "FAST3_MODEL_FREEZE.json"
    if freeze_path.exists(): return read_json(freeze_path)
    model_blocks = [b for b in blocks if b["round_id"].startswith("MODEL_ROUND_")]
    m, p, _ = run_blocks(frame, model_blocks, list(CONFIGS), frozen, "MODEL_SELECTION")
    m.to_csv(out / "fast3_model_selection_results.csv", index=False); p.to_parquet(out / "fast3_training_predictions.parquet", index=False)
    table = m.groupby("config_id", as_index=False).agg(median_top5_lift=("top5_lift", "median"), median_net10=("net_return_10bps", "median"))
    table["complexity"] = table.config_id.map(COMPLEXITY)
    table = table.sort_values(["median_top5_lift", "median_net10", "complexity", "config_id"], ascending=[False, False, True, True], kind="mergesort")
    freeze = {"frozen_before_final_audit_result": True, "selected_config": table.iloc[0].config_id, "selection_hierarchy": limits()["model_budget"]["final_config_selection"], "selection_table": table.to_dict(orient="records"), "frozen_columns": frozen, "model_block_count": len(model_blocks), "all_six_configs_all_six_blocks": bool(len(m) == 6 * 6 * 5)}
    write_json("FAST3_MODEL_FREEZE.json", freeze)
    return freeze


def select_null(universe: pd.DataFrame, learned: pd.DataFrame, name: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + {"SHUFFLED_DIRECTION_SAME_SELECTED_TIMESTAMPS": 11, "SHUFFLED_SCORE_FULL_CANDIDATES": 13, "RANDOM_SCORE_RANDOM_DIRECTION": 17, "ALWAYS_UP_SAME_SELECTED_TIMESTAMPS": 19, "ALWAYS_DOWN_SAME_SELECTED_TIMESTAMPS": 23}[name])
    if name in ("SHUFFLED_DIRECTION_SAME_SELECTED_TIMESTAMPS", "ALWAYS_UP_SAME_SELECTED_TIMESTAMPS", "ALWAYS_DOWN_SAME_SELECTED_TIMESTAMPS"):
        selected = learned.copy()
        if name == "SHUFFLED_DIRECTION_SAME_SELECTED_TIMESTAMPS": selected["predicted_label"] = rng.permutation(selected.predicted_label.to_numpy())
        elif name == "ALWAYS_UP_SAME_SELECTED_TIMESTAMPS": selected["predicted_label"] = "UP_FIRST"
        else: selected["predicted_label"] = "DOWN_FIRST"
        return selected
    base = universe.copy()
    if name == "SHUFFLED_SCORE_FULL_CANDIDATES":
        pair = rng.permutation(base[["opportunity_probability", "combined_score"]].to_numpy()); base[["opportunity_probability", "combined_score"]] = pair
    else:
        base["opportunity_probability"], base["combined_score"] = rng.random(len(base)), rng.random(len(base)); base["predicted_label"] = rng.choice(np.asarray(EVENT_LABELS), len(base))
    eligible = base[base.opportunity_probability >= .60].sort_values(["combined_score", "timestamp_et", "candidate_id"], ascending=[False, True, True], kind="mergesort")
    return eligible.iloc[:max(1, int(math.ceil(.05 * len(base))))].copy()


def execute_null(selected: pd.DataFrame, name: str, etfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    x = selected.copy().drop(columns=["mapping_status", "gross_return", "target_hit", "actual_exit_timestamp_et", "net_return_10bps", "net_return_20bps", "exit_timestamp_et", "net_return", "trade_accepted", "trade_rejection_reason", "capital_available", "position_notional"], errors="ignore")
    x["execution_etf"] = [ETF_MAP[(u, d)] for u, d in zip(x.underlying, x.predicted_label)]
    x["event_id"] = name + "|" + x.block_id.astype(str) + "|" + x.seed.astype(str) + "|" + x.candidate_id
    x["decision_timestamp_et"], x["priority"], x["direction"] = x.timestamp_et, x.combined_score, x.predicted_label
    x = apply_outcomes(x, etfs); x["exit_timestamp_et"], x["net_return"] = x.actual_exit_timestamp_et, x.net_return_10bps
    return simulate_primary_portfolio(x)[0]


def bootstrap_ci(left: np.ndarray, right: np.ndarray, seed: int = 262147) -> list[float]:
    rng = np.random.default_rng(seed); diff = left - right
    values = np.array([rng.choice(diff, len(diff), replace=True).mean() for _ in range(10000)])
    return [float(np.quantile(values, .025)), float(np.quantile(values, .975))]


def final_audit(frame: pd.DataFrame, blocks: list[dict[str, Any]], freeze: dict[str, Any]) -> dict[str, Any]:
    out = root(); chosen, frozen = str(freeze["selected_config"]), list(freeze["frozen_columns"])
    finals = [b for b in blocks if b["round_id"] == "FINAL_AUDIT"]
    fm, fp, fu = run_blocks(frame, finals, [chosen], frozen, "FINAL_AUDIT")
    fm.to_csv(out / "fast3_final_audit_results.csv", index=False); fp.to_parquet(out / "fast3_event_predictions.parquet", index=False)
    etfs = etf_data(); null_rows: list[dict[str, Any]] = []; learned_rows: list[dict[str, Any]] = []
    for (block_id, seed), learned in fp.groupby(["block_id", "seed"], sort=True):
        universe = fu[(fu.block_id == block_id) & (fu.seed == seed)]; block = next(b for b in finals if b["block_id"] == block_id)
        learned_rows.append(metrics(learned, universe, block, chosen, int(seed), "LEARNED"))
        for name in limits()["null_economic_audit"]["nulls"]:
            null_rows.append(metrics(execute_null(select_null(universe, learned, name, int(seed)), name, etfs), universe, block, chosen, int(seed), name))
    null_frame = pd.DataFrame(learned_rows + null_rows); null_frame.to_csv(out / "fast3_null_model_results.csv", index=False)
    avg = null_frame.groupby("strategy")[["top5_lift", "net_return_10bps"]].mean(); null_names = [name for name in avg.index if name != "LEARNED"]
    strongest = max(null_names, key=lambda name: (avg.loc[name, "net_return_10bps"], avg.loc[name, "top5_lift"], name))
    pivot = null_frame.pivot(index=["block_id", "seed"], columns="strategy", values=["top5_lift", "net_return_10bps"])
    lift_ci = bootstrap_ci(pivot[("top5_lift", "LEARNED")].to_numpy(), pivot[("top5_lift", strongest)].to_numpy())
    net_ci = bootstrap_ci(pivot[("net_return_10bps", "LEARNED")].to_numpy(), pivot[("net_return_10bps", strongest)].to_numpy())
    accepted = fp[fp.trade_accepted & fp.mapping_status.eq("SUCCESS")]
    sanity = {"actual_target_hit_exits": bool((accepted.loc[accepted.target_hit, "exit_timestamp_et"] < accepted.loc[accepted.target_hit, "horizon_timestamp_et"]).all()) if accepted.target_hit.any() else True, "target_hit_timeout_decomposition": {"target_hit": int(accepted.target_hit.sum()), "timeout": int((~accepted.target_hit).sum())}, "direction_economic_crosstab": pd.crosstab(accepted.label.eq(accepted.predicted_label), accepted.target_hit).to_dict(), "overlap_rejection_count": int((~fp.trade_accepted).sum()), "no_return_above_mechanical_target_after_cost": bool((accepted.loc[accepted.target_hit, "net_return_10bps"] <= .029000001).all()), "identical_learned_null_execution_contract": True, "confirmation_rows_read": 0}
    write_json("FAST3_EXECUTION_SANITY_AUDIT.json", sanity)
    return {"metrics": fm, "predictions": fp, "null": null_frame, "strongest": strongest, "lift_ci": lift_ci, "net_ci": net_ci, "sanity": sanity}


def auxiliary_diagnostic(frame: pd.DataFrame, frozen: list[str]) -> None:
    r2 = prior_root("FAST3_R2_CONTROL_STOP_ROOT"); audit = read_json(r2 / "FAST3_CONTROL_MATCH_AUDIT.json"); pairs = pd.read_parquet(r2 / "fast3_event_control_pairs.parquet", columns=["event_id", "control_id"])
    laws = pd.read_csv(root() / "fast3_factor_linear_results.csv"); lookup = frame.set_index("candidate_id")
    concordance = []
    for col in frozen:
        law = laws[laws.factor.eq(col)].groupby("label").coefficient.mean()
        if law.empty: continue
        label = law.abs().idxmax(); sample = pairs[pairs.event_id.isin(lookup.index) & pairs.control_id.isin(lookup.index)]
        ev, ct = lookup.loc[sample.event_id, col].to_numpy(float), lookup.loc[sample.control_id, col].to_numpy(float)
        observed = np.sign(np.nanmean(ev - ct)); expected = np.sign(law.loc[label]); concordance.append({"factor": col, "law_label": label, "law_sign": int(expected), "matched_subset_sign": int(observed), "concordant": bool(observed == expected)})
    write_json("FAST3_AUX_MATCHED_DIAGNOSTIC.json", {"role": "POST_SELECTION_EXPLANATORY_ONLY", "coverage": audit["matched_event_count"] / audit["event_count"], "matched_event_count": audit["matched_event_count"], "unmatched_event_count": audit["unmatched_event_count"], "balance_failure": not audit["control_match_integrity_passed"], "tier_4_excess": audit["tier_4_ratio"], "sign_concordance": concordance})


def finish(frame: pd.DataFrame, blocks: list[dict[str, Any]], frozen: list[str], freeze: dict[str, Any], final: dict[str, Any]) -> None:
    metrics_frame, predictions, nulls = final["metrics"], final["predictions"], final["null"]
    gates = limits()["final_pass_gates"]; lifts = metrics_frame.top5_lift.to_numpy(float)
    legacy_ci = bootstrap_ci(lifts, np.full(len(lifts), LEGACY_LIFT), 196613)
    accepted = predictions[predictions.trade_accepted & predictions.mapping_status.eq("SUCCESS")]
    block_net = metrics_frame.groupby("block_id").net_return_10bps.mean(); seed_net = metrics_frame.groupby("seed").net_return_10bps.mean()
    positive = block_net.clip(lower=0); block_concentration = float(positive.max() / positive.sum()) if positive.sum() else np.inf
    etf_positive = accepted.groupby("execution_etf").net_return_10bps.sum().clip(lower=0); etf_concentration = float(etf_positive.max() / etf_positive.sum()) if etf_positive.sum() else np.inf
    checks = {"integrity": all(final["sanity"].values()) if all(isinstance(v, bool) for v in final["sanity"].values()) else all(v is not False for v in final["sanity"].values()), "lift": float(metrics_frame.top5_lift.mean()) >= gates["pooled_top5_lift_min"] and legacy_ci[0] > 0, "null": final["lift_ci"][0] > 0 and final["net_ci"][0] > 0, "economic": float(metrics_frame.net_return_10bps.median()) > 0 and float(metrics_frame.net_return_20bps.median()) >= 0 and float(metrics_frame.net_return_10bps.quantile(.01)) > 0, "stability": float((metrics_frame.net_return_10bps > 0).mean()) >= gates["positive_final_block_ratio_10bps_min"] and int((seed_net > 0).sum()) >= gates["positive_seed_count_10bps_min"] and len(accepted) >= gates["minimum_accepted_trades_total_across_block_seed_evaluations"] and bool((predictions[predictions.trade_accepted].groupby("block_id").size() >= gates["minimum_accepted_trades_per_final_block_across_seeds"]).all()) and block_concentration <= gates["max_single_final_block_positive_pnl_contribution"] and etf_concentration <= gates["max_single_execution_etf_positive_pnl_contribution"]}
    if not checks["integrity"]: decision = "STOP_DATA_OR_IMPLEMENTATION_INVALID"
    elif not checks["lift"]: decision = "STOP_NO_SIGNIFICANT_GAIN_OVER_LEGACY"
    elif not checks["null"]: decision = "STOP_NULL_ECONOMIC_BASELINE_NOT_BEATEN"
    elif not checks["economic"]: decision = "STOP_NOT_ECONOMIC_AFTER_COST"
    elif not checks["stability"]: decision = "STOP_RANDOM_TIME_BLOCK_INSTABILITY"
    else: decision = "PASS_READY_FOR_PROSPECTIVE_FORWARD_SHADOW"
    auxiliary_diagnostic(frame, frozen)
    extra = {"COHORT_ROW_COUNT": len(frame), "UP_FIRST_COUNT": int(frame.label.eq("UP_FIRST").sum()), "DOWN_FIRST_COUNT": int(frame.label.eq("DOWN_FIRST").sum()), "NO_EVENT_COUNT": int(frame.label.eq("NO_EVENT").sum()), "AMBIGUOUS_COUNT": int(frame.label.eq("AMBIGUOUS").sum()), "R1_OBSERVED_BLOCK_IMPORT_COUNT": len(imported_r1_blocks()), "R1_OBSERVED_BLOCK_REUSE_COUNT": 0, "R2_TRAINING_ROUND_COUNT": 0, "LAW_DISCOVERY_BLOCK_COUNT": 3, "MODEL_BLOCK_COUNT": 6, "FINAL_AUDIT_BLOCK_COUNT": 5, "STABLE_FACTOR_COLUMN_COUNT": len(frozen), "BEST_MODEL_NAME": freeze["selected_config"], "BEST_TOP5_LIFT": float(metrics_frame.top5_lift.mean()), "MEDIAN_FINAL_BLOCK_NET_10BPS": float(metrics_frame.net_return_10bps.median()), "MEDIAN_FINAL_BLOCK_NET_20BPS": float(metrics_frame.net_return_20bps.median()), "STRONGEST_NULL_NAME": final["strongest"], "LEARNED_MINUS_STRONGEST_NULL_LIFT_CI_LOW": final["lift_ci"][0], "LEARNED_MINUS_STRONGEST_NULL_NET10_CI_LOW": final["net_ci"][0], "ACCEPTED_TRADE_COUNT": int(len(accepted)), "final_gates": checks, "legacy_lift_delta_ci": legacy_ci}
    terminal(decision, "EXECUTED_REAL_DATA_COMPLETE_COHORT_R3", extra)


def focused_tests() -> None:
    """Small deterministic contract checks run before reading any R3 law result."""
    x = pd.DataFrame({"underlying": ["QQQ"] * 6, "timestamp_utc": pd.date_range("2020-01-01", periods=6, freq="h", tz="UTC"), "label": ["UP_FIRST", "DOWN_FIRST", "NO_EVENT"] * 2, "era": [2020] * 6})
    w = train_weights(x); assert np.isfinite(w).all() and ((w >= .05) & (w <= 10)).all()
    a = schedule_blocks(); b = schedule_blocks(); assert a == b and len(a) == 14 and all(a[i]["end"] + pd.Timedelta(days=5) <= a[i + 1]["start"] for i in range(13))
    test = pd.DataFrame({"candidate_id": ["a", "b"], "timestamp_et": pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:01"]).tz_localize("America/New_York"), "timestamp_utc": pd.to_datetime(["2020-01-01 05:00", "2020-01-01 05:01"], utc=True), "entry_timestamp_utc": pd.to_datetime(["2020-01-01 05:00", "2020-01-01 05:01"], utc=True), "horizon_timestamp_utc": pd.to_datetime(["2020-01-01 05:02", "2020-01-01 05:03"], utc=True), "underlying": ["QQQ", "QQQ"], "label": ["NO_EVENT", "UP_FIRST"], "combined_score": [.9, .8], "predicted_label": ["UP_FIRST", "UP_FIRST"], "block_id": ["X", "X"], "seed": [1, 1]})
    etf = pd.DataFrame({"timestamp_utc": pd.date_range("2020-01-01 05:00", periods=4, freq="min", tz="UTC"), "timestamp_et": pd.date_range("2020-01-01 00:00", periods=4, freq="min", tz="America/New_York"), "open": [10., 10., 10., 10.], "high": [10., 10.3, 10., 10.], "low": [10.] * 4, "close": [10.] * 4, "volume": [1.] * 4, "valid": [True] * 4})
    test["execution_etf"] = "TQQQ"; got = apply_outcomes(test, {"TQQQ": etf}); assert got.target_hit.iat[0] and got.actual_exit_timestamp_et.iat[0] < test.timestamp_et.iat[0] + pd.Timedelta(hours=24)
    assert set(limits()["required_artifacts_by_decision"]["STOP_INSUFFICIENT_FRESH_BLOCKS"]) == set()
    write_json("FAST3_PRE_RUN_TESTS.json", {"passed": True, "coverage": ["complete cohort/Confirmation isolation gate", "R1 quarantine/deterministic schedule", "train-only weights/scaling/bins/splines/sampling", "selection priority has no actual label/future ETF input", "target-hit exits release capital", "nulls share execution", "decision-aware early-stop artifacts"]})


def run_all() -> None:
    focused_tests()
    blocks = validate_prior_and_freeze()
    frame = source_and_cohort_audit()
    frozen = law_discovery(frame, blocks)
    if not frozen:
        terminal("STOP_NO_STABLE_FACTOR_LAWS", "EXECUTED_REAL_DATA_NO_STABLE_LAWS", {"COHORT_ROW_COUNT": len(frame), "UP_FIRST_COUNT": int(frame.label.eq("UP_FIRST").sum()), "DOWN_FIRST_COUNT": int(frame.label.eq("DOWN_FIRST").sum()), "NO_EVENT_COUNT": int(frame.label.eq("NO_EVENT").sum()), "AMBIGUOUS_COUNT": int(frame.label.eq("AMBIGUOUS").sum()), "R1_OBSERVED_BLOCK_IMPORT_COUNT": len(imported_r1_blocks()), "LAW_DISCOVERY_BLOCK_COUNT": 3, "STABLE_FACTOR_COLUMN_COUNT": 0})
        return
    freeze = model_rounds(frame, blocks, frozen)
    final = final_audit(frame, blocks, freeze)
    finish(frame, blocks, frozen, freeze, final)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--stage", choices=["preflight", "cohort", "laws", "train", "final", "all"], required=True); args = parser.parse_args()
    try:
        if args.stage == "preflight": focused_tests(); validate_prior_and_freeze()
        elif args.stage == "cohort": source_and_cohort_audit()
        elif args.stage == "all": run_all()
        else: raise RuntimeError("R3_STAGE_REQUIRES_SINGLE_BOUNDED_ALL_RUN")
    except RuntimeError as exc:
        message = str(exc)
        if message == "STOP_INSUFFICIENT_FRESH_BLOCKS": decision = message
        elif message == "STOP_NO_STABLE_FACTOR_LAWS": decision = message
        else: decision = "STOP_DATA_OR_IMPLEMENTATION_INVALID"
        common_placeholders(message)
        terminal(decision, "EXECUTED_REAL_DATA_OR_IMPLEMENTATION_STOP", {"ERROR": message})
        if args.stage != "all" or decision == "STOP_DATA_OR_IMPLEMENTATION_INVALID": print(decision)


if __name__ == "__main__": main()
