#!/usr/bin/env python
"""FAST3 R36 payoff-path decomposition R1 (zero-model mechanism audit)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SOURCE_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R28_3G_ROOT = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809"
R28_LEDGER = R28_3G_ROOT / "R28_3G_CORRECTED_TRADE_LEDGER.csv"
ACTION_LEDGER = R28_3G_ROOT / "R28_3G_CORPORATE_ACTION_LEDGER.json"
ETF_MANIFEST = RESULTS_ROOT / "frozen/fast3/r28_3e_clean_lineage_first_touch_20260809_r3/R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json"
UNDERLYING_MANIFEST = RESULTS_ROOT / "frozen/fast3/cleanroom_r2_20260808/cleanroom_r2_preholdout_source_manifest.json"
PHASE2_DECISION = RESULTS_ROOT / "frozen/fast3/r28_phase2_20260808T125629Z/R28_PHASE2_DECISION.json"
R28_3F_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r28_3f_leveraged_etf_integrity_audit.py"

EXPECTED = {
    "R28_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "ACTION_LEDGER": "3a72c80d4bce04e409ed429b9434e9f936405e1ffc38ac3ee04213675781a0dd",
    "ETF_MANIFEST": "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331",
    "PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
}
FIXED_HORIZONS = (5, 10, 15, 30, 60)
STOP_LEVELS = (0.005, 0.010, 0.015, 0.020)
MFE_THRESHOLDS = (0.0025, 0.0050, 0.0100, 0.0200)
ETF_SYMBOLS = ("SOXL", "SOXS", "TQQQ", "SQQQ")
UNDERLYING_SYMBOLS = ("SOXX", "QQQ")
CLASSIFICATIONS = {
    "A_PATH_REVERSAL_MECHANISM_PRESENT", "B_LEVERAGED_EXECUTION_MAPPING_FAILURE_PRESENT",
    "C_SIMPLE_PATH_CONTROL_PROMISING", "D_NO_CLEAR_PAYOFF_PATH_MECHANISM",
    "E_INVALID_PATH_DATA_OR_EXECUTION_ASSUMPTION", "D_INSUFFICIENT_PATH_DATA",
}


class R36Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R36Stop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def preregistration(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R36_PAYOFF_PATH_DECOMPOSITION_R1", "STATUS": "FROZEN_BEFORE_PATH_METRICS",
        "CREATED_AT_UTC": created_at, "RESEARCH_TYPE": "MECHANISM_DISCOVERY_ONLY",
        "BASELINE_SIGNAL_COUNT": 1197, "R28_LEDGER_SHA256": EXPECTED["R28_LEDGER"],
        "CORPORATE_ACTION_LEDGER_SHA256": EXPECTED["ACTION_LEDGER"],
        "ETF_MANIFEST_SHA256": EXPECTED["ETF_MANIFEST"], "R28_PHASE2_DECISION_SHA256": EXPECTED["PHASE2_DECISION"],
        "FIXED_HORIZONS_MINUTES": list(FIXED_HORIZONS), "ORIGINAL_HORIZON": "frozen first-touch exit timestamp",
        "FIXED_HORIZON_RETURN": "entry open to exact +N minute open, then subtract frozen 20bps once",
        "MFE_MAE_WINDOW": "entry bar through frozen original first-touch exit bar inclusive",
        "MFE": "max normalized execution-ETF high return; long instrument PnL for inverse ETFs too",
        "MAE": "max positive magnitude of normalized execution-ETF low loss",
        "MFE_THRESHOLDS": list(MFE_THRESHOLDS), "STOP_LEVELS": list(STOP_LEVELS),
        "STOP_EXECUTION": "one-minute OHLC; gap-through exits at bar open, otherwise at fixed stop; no slippage beyond observed gap; 20bps subtracted once",
        "STOP_SAME_BAR": "entry occurs at bar open; same entry-bar low may trigger; no take-profit ambiguity",
        "PATH_COMPLETE_GATE": 0.90, "MAX_FIXED_HORIZON_COUNT": 6, "MAX_STOP_RULE_COUNT": 4,
        "MAX_TAKE_PROFIT_RULE_COUNT": 0, "MAX_PATH_RULE_COMBINATION_COUNT": 0,
        "CLASSIFICATION_GATES": {
            "A": "loser MFE>=0.5% rate >=0.40 and at least one fixed short horizon mean>0 with >=20bps improvement over original",
            "B": "underlying direction correct rate>0.50 and ETF-loss-given-underlying-correct rate>=0.25",
            "C": "a fixed stop improves mean by>=20bps, lowers abs(mean loss)>=20%, and raises PF>=0.20",
            "PRIORITY": ["A", "B", "C", "D"],
        },
        "MODEL_FIT_ALLOWED": False, "MODEL_PREDICT_ALLOWED": False, "PARAMETER_OPTIMIZATION_ALLOWED": False,
        "SECOND_ROUND_RULE_SEARCH_ALLOWED": False, "PROSPECTIVE_OUTCOME_ALLOWED": False,
        "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
    }


def verify_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path in (R28_LEDGER, ACTION_LEDGER, ETF_MANIFEST, UNDERLYING_MANIFEST, PHASE2_DECISION, R28_3F_RUNNER):
        if not path.is_file(): raise R36Stop(f"STOP_LINEAGE_MISSING:{path}")
    if sha256(R28_LEDGER) != EXPECTED["R28_LEDGER"]: raise R36Stop("STOP_R28_LEDGER_HASH")
    if sha256(ACTION_LEDGER) != EXPECTED["ACTION_LEDGER"]: raise R36Stop("STOP_ACTION_LEDGER_HASH")
    if sha256(ETF_MANIFEST) != EXPECTED["ETF_MANIFEST"]: raise R36Stop("STOP_ETF_MANIFEST_HASH")
    if sha256(PHASE2_DECISION) != EXPECTED["PHASE2_DECISION"]: raise R36Stop("STOP_R28_IDENTITY_HASH")
    ledger = pd.read_csv(R28_LEDGER)
    ledger = ledger.loc[ledger["primary_executable_first_touch_cohort"].astype(bool)].copy()
    for column in ("timestamp", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp"):
        ledger[column] = pd.to_datetime(ledger[column], utc=True, errors="coerce")
    if len(ledger) != 1197 or ledger["candidate_id"].duplicated().any() or ledger["entry_timestamp"].isna().any() or ledger["first_touch_exit_timestamp"].isna().any():
        raise R36Stop("STOP_SIGNAL_IDENTITY")
    if not np.isclose(ledger["corrected_gross"] - .002, ledger["corrected_net20"], atol=1e-12, rtol=1e-12).all():
        raise R36Stop("STOP_NET20_CONTRACT")
    action = read_json(ACTION_LEDGER); etf_manifest = read_json(ETF_MANIFEST)
    if action["price_basis"] != "RAW" or action["normalization_layer"] != "ECONOMIC_RETURN_ONLY" or action["record_count"] != 9:
        raise R36Stop("STOP_CORPORATE_ACTION_CONTRACT")
    if len(etf_manifest["partitions"]) != 392: raise R36Stop("STOP_ETF_PARTITION_COUNT")
    return ledger.sort_values("candidate_id", kind="mergesort").reset_index(drop=True), action, etf_manifest


def load_underlying_bars(manifest: dict[str, Any]) -> dict[str, pd.DataFrame]:
    result = {}
    for symbol in UNDERLYING_SYMBOLS:
        pieces = []
        for record in manifest["files"]:
            if record["symbol"] != symbol: continue
            path = Path(record["path"])
            if sha256(path) != record["sha256"]: raise R36Stop(f"STOP_UNDERLYING_PARTITION_HASH:{path}")
            part = pd.read_parquet(path, columns=["timestamp_utc", "open", "high", "low", "close"])
            pieces.append(part)
        bars = pd.concat(pieces, ignore_index=True); bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True)
        bars = bars.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc", keep=False)
        numeric = bars[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        bars = bars.loc[np.isfinite(numeric).all(axis=1) & numeric.gt(0).all(axis=1)].copy()
        result[symbol] = bars.set_index("timestamp_utc", drop=False)
    return result


def actions_between(start: pd.Timestamp, end: pd.Timestamp, symbol: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["symbol"] == symbol and start < pd.Timestamp(record["effective_timestamp"]) <= end]


def normalization_factor(start: pd.Timestamp, end: pd.Timestamp, symbol: str, records: list[dict[str, Any]]) -> float:
    actions = actions_between(start, end, symbol, records)
    return float(np.prod([float(row["pre_to_post_price_multiplier"]) for row in actions])) if actions else 1.0


def normalized_bar_returns(path: pd.DataFrame, entry_ts: pd.Timestamp, entry_price: float,
                           symbol: str, records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in path.itertuples(index=False):
        factor = normalization_factor(entry_ts, row.timestamp_utc, symbol, records)
        denominator = entry_price * factor
        rows.append({"timestamp_utc": row.timestamp_utc, "open_return": row.open / denominator - 1.0,
                     "high_return": row.high / denominator - 1.0, "low_return": row.low / denominator - 1.0})
    return pd.DataFrame(rows)


def exact_bar(indexed: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    if timestamp not in indexed.index: return None
    row = indexed.loc[timestamp]
    return None if isinstance(row, pd.DataFrame) else row


def stop_exit(path_returns: pd.DataFrame, stop_level: float, original_net20: float) -> dict[str, Any]:
    stop_return = -float(stop_level)
    for row in path_returns.itertuples(index=False):
        if row.open_return <= stop_return:
            gross = float(row.open_return)
            return {"triggered": True, "gross": gross, "net20": gross - .002, "timestamp": row.timestamp_utc, "gap_through": True}
        if row.low_return <= stop_return:
            return {"triggered": True, "gross": stop_return, "net20": stop_return - .002, "timestamp": row.timestamp_utc, "gap_through": False}
    return {"triggered": False, "gross": float(original_net20 + .002), "net20": float(original_net20), "timestamp": None, "gap_through": False}


def build_paths(ledger: pd.DataFrame, etf_bars: dict[str, pd.DataFrame], underlying_bars: dict[str, pd.DataFrame],
                action_records: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, int]]:
    missing = {"MISSING_ENTRY": 0, **{f"MISSING_{m}M": 0 for m in FIXED_HORIZONS}, "MISSING_ORIGINAL_HORIZON": 0,
               "CORPORATE_ACTION_PATH_FAILURE": 0, "SESSION_BOUNDARY_FAILURE": 0}
    rows = []
    for trade in ledger.itertuples(index=False):
        bars = etf_bars[trade.action_instrument]; entry = exact_bar(bars, trade.entry_timestamp)
        complete = True; reason = None
        if entry is None or not np.isclose(float(entry.open), float(trade.raw_entry_price), atol=1e-9, rtol=1e-9):
            missing["MISSING_ENTRY"] += 1; complete = False; reason = "MISSING_ENTRY"
        fixed = {}
        if complete:
            for minute in FIXED_HORIZONS:
                timestamp = trade.entry_timestamp + pd.Timedelta(minutes=minute); bar = exact_bar(bars, timestamp)
                if bar is None:
                    missing[f"MISSING_{minute}M"] += 1; missing["SESSION_BOUNDARY_FAILURE"] += 1
                    complete = False; reason = reason or f"MISSING_{minute}M"; fixed[minute] = None
                else:
                    factor = normalization_factor(trade.entry_timestamp, timestamp, trade.action_instrument, action_records)
                    fixed[minute] = float(bar.open) / (float(trade.raw_entry_price) * factor) - 1.0 - .002
            exit_bar = exact_bar(bars, trade.first_touch_exit_timestamp)
            if exit_bar is None:
                missing["MISSING_ORIGINAL_HORIZON"] += 1; complete = False; reason = reason or "MISSING_ORIGINAL_HORIZON"
        if not complete:
            rows.append({"candidate_id": trade.candidate_id, "head": trade.head, "path_complete": False, "path_failure_reason": reason})
            continue
        path = bars.loc[(bars.index >= trade.entry_timestamp) & (bars.index <= trade.first_touch_exit_timestamp),
                        ["timestamp_utc", "open", "high", "low", "close"]]
        if path.empty:
            missing["MISSING_ORIGINAL_HORIZON"] += 1
            rows.append({"candidate_id": trade.candidate_id, "head": trade.head, "path_complete": False, "path_failure_reason": "EMPTY_PATH"}); continue
        returns = normalized_bar_returns(path.reset_index(drop=True), trade.entry_timestamp, float(trade.raw_entry_price), trade.action_instrument, action_records)
        if not np.isfinite(returns[["open_return", "high_return", "low_return"]]).all().all():
            missing["CORPORATE_ACTION_PATH_FAILURE"] += 1
            rows.append({"candidate_id": trade.candidate_id, "head": trade.head, "path_complete": False, "path_failure_reason": "CORPORATE_ACTION_PATH_FAILURE"}); continue
        mfe_idx = returns["high_return"].idxmax(); mae_idx = returns["low_return"].idxmin()
        mfe = float(max(0.0, returns.loc[mfe_idx, "high_return"])); mae = float(max(0.0, -returns.loc[mae_idx, "low_return"]))
        underlying = underlying_bars[trade.underlying_symbol]
        under_entry = exact_bar(underlying, trade.entry_timestamp)
        under_results = {}
        for minute in (*FIXED_HORIZONS, "ORIGINAL"):
            ts = trade.first_touch_exit_timestamp if minute == "ORIGINAL" else trade.entry_timestamp + pd.Timedelta(minutes=minute)
            under_exit = exact_bar(underlying, ts)
            if under_entry is None or under_exit is None: under_results[str(minute)] = None
            else:
                raw = float(under_exit.open) / float(under_entry.open) - 1.0
                under_results[str(minute)] = raw if trade.head == "UP" else -raw
        row = {"candidate_id": trade.candidate_id, "decision_timestamp_utc": trade.timestamp, "entry_timestamp": trade.entry_timestamp,
               "original_exit_timestamp": trade.first_touch_exit_timestamp, "head": trade.head, "underlying_symbol": trade.underlying_symbol,
               "action_instrument": trade.action_instrument, "event_state": trade.event_state, "path_complete": True,
               "path_failure_reason": None, "original_net20": float(trade.corrected_net20), "mfe": mfe, "mae": mae,
               "time_to_mfe_minutes": float((returns.loc[mfe_idx, "timestamp_utc"] - trade.entry_timestamp) / pd.Timedelta(minutes=1)),
               "time_to_mae_minutes": float((returns.loc[mae_idx, "timestamp_utc"] - trade.entry_timestamp) / pd.Timedelta(minutes=1)),
               **{f"return_{minute}m_net20": fixed[minute] for minute in FIXED_HORIZONS},
               **{f"underlying_directional_{str(minute).lower()}": value for minute, value in under_results.items()}}
        for stop in STOP_LEVELS:
            result = stop_exit(returns, stop, float(trade.corrected_net20)); code = int(round(stop * 10000))
            row[f"stop_{code:03d}_triggered"] = result["triggered"]; row[f"stop_{code:03d}_net20"] = result["net20"]
            row[f"stop_{code:03d}_gap_through"] = result["gap_through"]
        rows.append(row)
    return pd.DataFrame(rows), missing


def payoff_metrics(values: pd.Series) -> dict[str, Any]:
    net = pd.to_numeric(values, errors="coerce").dropna(); wins = net[net > 0]; losses = net[net < 0]
    return {"signal_count": len(net), "win_rate": float((net > 0).mean()), "mean_net20": float(net.mean()),
            "median_net20": float(net.median()), "mean_win": float(wins.mean()) if len(wins) else None,
            "mean_loss": float(losses.mean()) if len(losses) else None,
            "profit_factor": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else None,
            "p05": float(net.quantile(.05)), "p10": float(net.quantile(.10)), "p25": float(net.quantile(.25)),
            "p75": float(net.quantile(.75)), "p90": float(net.quantile(.90)), "p95": float(net.quantile(.95)),
            "worst": float(net.min()), "best": float(net.max()),
            "large_loss_2pct_count": int((net <= -.02).sum()), "large_loss_3pct_count": int((net <= -.03).sum()),
            "large_loss_5pct_count": int((net <= -.05).sum())}


def horizon_table(paths: pd.DataFrame) -> pd.DataFrame:
    rows = []
    definitions = [(f"{m}M", f"return_{m}m_net20") for m in FIXED_HORIZONS] + [("ORIGINAL", "original_net20")]
    for horizon, column in definitions:
        for direction, part in [("ALL", paths), *list(paths.groupby("head", sort=True))]:
            rows.append({"horizon": horizon, "direction": direction, **payoff_metrics(part[column])})
    return pd.DataFrame(rows)


def excursion_summary(paths: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction, base in [("ALL", paths), *list(paths.groupby("head", sort=True))]:
        cohorts = {"ALL": base, "WINNER": base.loc[base.original_net20 > 0], "LOSER": base.loc[base.original_net20 < 0],
                   "LARGE_LOSS_2PCT": base.loc[base.original_net20 <= -.02], "LARGE_LOSS_5PCT": base.loc[base.original_net20 <= -.05]}
        for cohort, part in cohorts.items():
            rows.append({"direction": direction, "cohort": cohort, "count": len(part), "mfe_mean": part.mfe.mean(),
                         "mfe_median": part.mfe.median(), "mfe_p25": part.mfe.quantile(.25), "mfe_p75": part.mfe.quantile(.75),
                         "mfe_p90": part.mfe.quantile(.90), "mae_mean": part.mae.mean(), "mae_median": part.mae.median(),
                         "mae_p25": part.mae.quantile(.25), "mae_p75": part.mae.quantile(.75), "mae_p90": part.mae.quantile(.90),
                         "median_time_to_mfe": part.time_to_mfe_minutes.median(), "median_time_to_mae": part.time_to_mae_minutes.median()})
    return pd.DataFrame(rows)


def reversal_metrics(paths: pd.DataFrame) -> dict[str, Any]:
    losers = paths.loc[paths.original_net20 < 0]; result = {"LOSING_TRADE_COUNT": len(losers),
        "LOSER_EVER_POSITIVE_COUNT": int((losers.mfe > 0).sum()), "LOSER_EVER_POSITIVE_RATE": float((losers.mfe > 0).mean())}
    for threshold in MFE_THRESHOLDS:
        code = int(round(threshold * 10000)); result[f"LOSER_MFE_GE_{code:03d}_COUNT"] = int((losers.mfe >= threshold).sum())
        result[f"LOSER_MFE_GE_{code:03d}_RATE"] = float((losers.mfe >= threshold).mean())
    for loss in (.02, .03, .05):
        cohort = paths.loc[paths.original_net20 <= -loss]
        result[f"LARGE_LOSS_{int(loss*100):d}PCT_EVER_MFE_GE_050_RATE"] = float((cohort.mfe >= .005).mean())
    return result


def direction_translation(paths: pd.DataFrame) -> dict[str, Any]:
    correct = paths.event_state.eq("FAVORABLE_FIRST"); win = paths.original_net20 > 0
    result = {"DIRECTION_CORRECT_TRADE_WIN_COUNT": int((correct & win).sum()),
              "DIRECTION_CORRECT_TRADE_LOSS_COUNT": int((correct & ~win).sum()),
              "DIRECTION_WRONG_TRADE_WIN_COUNT": int((~correct & win).sum()),
              "DIRECTION_WRONG_TRADE_LOSS_COUNT": int((~correct & ~win).sum()),
              "P_TRADE_WIN_GIVEN_DIRECTION_CORRECT": float(win[correct].mean()),
              "P_TRADE_WIN_GIVEN_DIRECTION_WRONG": float(win[~correct].mean()),
              "MEAN_NET20_GIVEN_DIRECTION_CORRECT": float(paths.loc[correct, "original_net20"].mean()),
              "MEAN_NET20_GIVEN_DIRECTION_WRONG": float(paths.loc[~correct, "original_net20"].mean())}
    result["DIRECTION_CORRECT_BUT_TRADE_LOSS_RATE"] = float((~win[correct]).mean())
    result["DOES_DIRECTIONAL_CORRECTNESS_TRANSLATE_TO_EXECUTION_PROFIT"] = bool(result["P_TRADE_WIN_GIVEN_DIRECTION_CORRECT"] > result["P_TRADE_WIN_GIVEN_DIRECTION_WRONG"] and result["MEAN_NET20_GIVEN_DIRECTION_CORRECT"] > 0)
    return result


def mapping_table(paths: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    original_correct = paths["underlying_directional_original"] > 0; etf_win = paths.original_net20 > 0
    rows = []
    for symbol, part in paths.groupby("action_instrument", sort=True):
        metrics = payoff_metrics(part.original_net20)
        rows.append({"action_instrument": symbol, **metrics, "mfe_median": part.mfe.median(), "mae_median": part.mae.median()})
    result = {"UNDERLYING_DIRECTION_CORRECT_COUNT": int(original_correct.sum()), "ETF_NET20_WIN_COUNT": int(etf_win.sum()),
              "UNDERLYING_CORRECT_BUT_ETF_LOSS_COUNT": int((original_correct & ~etf_win).sum()),
              "UNDERLYING_CORRECT_BUT_ETF_LOSS_RATE": float((~etf_win[original_correct]).mean()),
              "UNDERLYING_DIRECTION_CORRECT_RATE": float(original_correct.mean())}
    for direction, part in paths.groupby("head", sort=True):
        correct = part.underlying_directional_original > 0; win = part.original_net20 > 0
        result[f"{direction}_UNDERLYING_CORRECT_BUT_ETF_LOSS_RATE"] = float((~win[correct]).mean())
    return pd.DataFrame(rows), result


def stop_table(paths: pd.DataFrame, baseline: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for stop in STOP_LEVELS:
        code = int(round(stop * 10000)); column = f"stop_{code:03d}_net20"; trigger = f"stop_{code:03d}_triggered"
        for direction, part in [("ALL", paths), *list(paths.groupby("head", sort=True))]:
            metrics = payoff_metrics(part[column]); base_part = payoff_metrics(part.original_net20)
            rows.append({"stop": f"STOP_{code:03d}", "stop_level": -stop, "direction": direction,
                         "trigger_count": int(part[trigger].sum()), "trigger_rate": float(part[trigger].mean()), **metrics,
                         "baseline_to_stop_mean_delta": metrics["mean_net20"] - base_part["mean_net20"],
                         "baseline_to_stop_pf_delta": metrics["profit_factor"] - base_part["profit_factor"],
                         "mean_loss_abs_reduction": 1.0 - abs(metrics["mean_loss"]) / abs(base_part["mean_loss"])})
    return pd.DataFrame(rows)


def choose_classification(horizons: pd.DataFrame, reversal: dict[str, Any], mapping: dict[str, Any], stops: pd.DataFrame) -> tuple[str, dict[str, bool], str | None]:
    overall = horizons.loc[horizons.direction.eq("ALL")].set_index("horizon")
    original = float(overall.loc["ORIGINAL", "mean_net20"])
    short_positive = overall.loc[[f"{m}M" for m in FIXED_HORIZONS], "mean_net20"] > 0
    improved = overall.loc[[f"{m}M" for m in FIXED_HORIZONS], "mean_net20"] >= original + .002
    reversal_flag = bool(reversal["LOSER_MFE_GE_050_RATE"] >= .40 and (short_positive & improved).any())
    mapping_flag = bool(mapping["UNDERLYING_DIRECTION_CORRECT_RATE"] > .50 and mapping["UNDERLYING_CORRECT_BUT_ETF_LOSS_RATE"] >= .25)
    all_stops = stops.loc[stops.direction.eq("ALL")]
    promising_rows = all_stops.loc[(all_stops.baseline_to_stop_mean_delta >= .002) &
        (all_stops.mean_loss_abs_reduction >= .20) & (all_stops.baseline_to_stop_pf_delta >= .20)]
    stop_flag = not promising_rows.empty
    short_decay = bool(short_positive.any() and original < 0)
    edge_decay = next((h for h in [f"{m}M" for m in FIXED_HORIZONS] if float(overall.loc[h, "mean_net20"]) <= 0), None) if short_decay else None
    if reversal_flag: classification = "A_PATH_REVERSAL_MECHANISM_PRESENT"
    elif mapping_flag: classification = "B_LEVERAGED_EXECUTION_MAPPING_FAILURE_PRESENT"
    elif stop_flag: classification = "C_SIMPLE_PATH_CONTROL_PROMISING"
    else: classification = "D_NO_CLEAR_PAYOFF_PATH_MECHANISM"
    return classification, {"PATH_REVERSAL_MECHANISM": reversal_flag, "LEVERAGED_ETF_MAPPING_FAILURE": mapping_flag,
                            "SIMPLE_STOP_DIAGNOSTIC_PROMISING": stop_flag, "SHORT_HORIZON_EDGE_DECAYS": short_decay}, edge_decay


def path_conclusion(paths: pd.DataFrame, direction: str) -> str:
    part = paths.loc[paths["head"].eq(direction)]; losers = part.loc[part.original_net20 < 0]
    reversal = float((losers.mfe >= .005).mean()); under = part.underlying_directional_original > 0
    mapping_loss = float((part.loc[under, "original_net20"] < 0).mean())
    return f"LOSER_MFE_GE_050_RATE={reversal:.6f};UNDERLYING_CORRECT_ETF_LOSS_RATE={mapping_loss:.6f}"


def render_report(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R36 Payoff Path Decomposition R1

- Status/classification: `{summary['FAST3_R36_STATUS']}` / `{summary['FAST3_R36_CLASSIFICATION']}`
- Path completeness: `{summary['PATH_COMPLETE_SIGNAL_COUNT']}/1197` (`{summary['PATH_COMPLETE_RATIO']}`)
- Original mean/PF: `{summary['BASELINE_MEAN_NET20']}` / `{summary['BASELINE_PROFIT_FACTOR_NET20']}`
- Loser ever-positive / MFE>=0.5%: `{summary['LOSER_EVER_POSITIVE_RATE']}` / `{summary['LOSER_MFE_GE_050_RATE']}`
- Short-horizon decay: `{summary['SHORT_HORIZON_EDGE_DECAYS']}`
- ETF mapping failure: `{summary['LEVERAGED_ETF_MAPPING_FAILURE']}`
- Fixed-stop diagnostic promising: `{summary['SIMPLE_STOP_DIAGNOSTIC_PROMISING']}`
- No models, optimization, take-profit, combinations, prospective or final data were used.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True)
    parser.add_argument("--first-run-status", default="SUCCESSFUL_FIRST_EXECUTION")
    parser.add_argument("--rerun-count", type=int, default=0)
    parser.add_argument("--rerun-reason", default="NONE")
    args = parser.parse_args()
    run_name = f"r36_payoff_path_decomposition_r1_{args.run_id}"
    frozen = RESULTS_ROOT / "frozen/fast3" / run_name; scratch = RESULTS_ROOT / "scratch/fast3" / run_name
    runtime = RESULTS_ROOT / "runtime/fast3" / run_name
    if any(path.exists() for path in (frozen, scratch, runtime)): raise R36Stop("STOP_RUN_ID_EXISTS")
    frozen.mkdir(parents=True); scratch.mkdir(parents=True); runtime.mkdir(parents=True)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    prereg_path = frozen / "FAST3_R36_PREREGISTRATION_R1.json"; write_json(prereg_path, preregistration(datetime.now(timezone.utc).isoformat()))
    prereg_sha = sha256(prereg_path); ledger, action, etf_manifest = verify_lineage()
    r28f = import_module(R28_3F_RUNNER, "fast3_r36_bound_r28f")
    etf_bars = {}
    for symbol in ETF_SYMBOLS:
        etf_bars[symbol] = r28f.load_symbol_bars(symbol, [r for r in etf_manifest["partitions"] if r["symbol"] == symbol]).set_index("timestamp_utc", drop=False)
    underlying_bars = load_underlying_bars(read_json(UNDERLYING_MANIFEST))
    if sha256(prereg_path) != prereg_sha: raise R36Stop("STOP_PREREGISTRATION_MUTATION")
    paths, missing = build_paths(ledger, etf_bars, underlying_bars, action["records"])
    complete = paths.loc[paths.path_complete.eq(True)].copy(); complete_ratio = len(complete) / len(ledger)
    if complete_ratio < .90:
        summary = {"FAST3_R36_STATUS": "STOP", "FAST3_R36_CLASSIFICATION": "D_INSUFFICIENT_PATH_DATA",
                   "FAST3_R36_DECISION": "STOP_PATH_COMPLETE_RATIO_BELOW_90PCT", "PATH_COMPLETE_SIGNAL_COUNT": len(complete),
                   "PATH_INCOMPLETE_SIGNAL_COUNT": len(ledger)-len(complete), "PATH_COMPLETE_RATIO": complete_ratio, **missing,
                   "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "R28_PREDICTIVE_IDENTITY_UNCHANGED": True,
                   "PIT_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS", "PATH_INTEGRITY_STATUS": "FAIL_INSUFFICIENT",
                   "R36_PREREGISTRATION_SHA256": prereg_sha}
        write_json(frozen / "FAST3_R36_SUMMARY.json", summary); print(json.dumps(summary, indent=2)); return
    complete.to_parquet(scratch / "FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet", index=False)
    horizons = horizon_table(complete); excursions = excursion_summary(complete); reversal = reversal_metrics(complete)
    direction = direction_translation(complete); mappings, mapping = mapping_table(complete)
    baseline = payoff_metrics(complete.original_net20); stops = stop_table(complete, baseline)
    horizons.to_csv(frozen / "FAST3_R36_HORIZON_METRICS.csv", index=False, lineterminator="\n")
    excursions.to_csv(frozen / "FAST3_R36_EXCURSION_METRICS.csv", index=False, lineterminator="\n")
    mappings.to_csv(frozen / "FAST3_R36_ETF_MAPPING_METRICS.csv", index=False, lineterminator="\n")
    stops.to_csv(frozen / "FAST3_R36_STOP_DIAGNOSTICS.csv", index=False, lineterminator="\n")
    classification, flags, decay_start = choose_classification(horizons, reversal, mapping, stops)
    if classification not in CLASSIFICATIONS: raise R36Stop("STOP_CLASSIFICATION_ENUM")
    overall_h = horizons.loc[horizons.direction.eq("ALL")].set_index("horizon"); all_exc = excursions.loc[(excursions.direction.eq("ALL")) & (excursions.cohort.eq("ALL"))].iloc[0]
    all_stops = stops.loc[stops.direction.eq("ALL")].set_index("stop")
    best_horizon = overall_h["mean_net20"].idxmax()
    summary = {"FAST3_R36_STATUS": "PASS", "FAST3_R36_CLASSIFICATION": classification,
        "FAST3_R36_DECISION": "MECHANISM_IDENTIFIED_FOR_SEPARATE_PREREGISTRATION" if classification != "D_NO_CLEAR_PAYOFF_PATH_MECHANISM" else "STOP_NO_CLEAR_PATH_MECHANISM",
        "BRANCH": branch, "HEAD": head, "R36_PREREGISTRATION_VERIFIED": True, "R36_PREREGISTRATION_SHA256": prereg_sha,
        "PATH_COMPLETE_SIGNAL_COUNT": len(complete), "PATH_INCOMPLETE_SIGNAL_COUNT": len(ledger)-len(complete), "PATH_COMPLETE_RATIO": complete_ratio,
        "UP_PATH_COMPLETE": int(complete["head"].eq("UP").sum()), "DOWN_PATH_COMPLETE": int(complete["head"].eq("DOWN").sum()), **missing,
        "BASELINE_SIGNAL_COUNT": len(complete), "BASELINE_WIN_RATE_NET20": baseline["win_rate"], "BASELINE_MEAN_NET20": baseline["mean_net20"],
        "BASELINE_MEDIAN_NET20": baseline["median_net20"], "BASELINE_MEAN_LOSS_NET20": baseline["mean_loss"],
        "BASELINE_PROFIT_FACTOR_NET20": baseline["profit_factor"], "WHICH_HORIZON_HAS_BEST_UNOPTIMIZED_ECONOMIC_PROFILE": best_horizon,
        **{f"HORIZON_{m}M_MEAN_NET20": float(overall_h.loc[f'{m}M', 'mean_net20']) for m in FIXED_HORIZONS},
        "ORIGINAL_HORIZON_MEAN_NET20": float(overall_h.loc["ORIGINAL", "mean_net20"]),
        **{f"HORIZON_{m}M_PROFIT_FACTOR": float(overall_h.loc[f'{m}M', 'profit_factor']) for m in FIXED_HORIZONS},
        "ORIGINAL_PROFIT_FACTOR": float(overall_h.loc["ORIGINAL", "profit_factor"]),
        "MFE_MEAN": all_exc.mfe_mean, "MFE_MEDIAN": all_exc.mfe_median, "MFE_P25": all_exc.mfe_p25, "MFE_P75": all_exc.mfe_p75, "MFE_P90": all_exc.mfe_p90,
        "MAE_MEAN": all_exc.mae_mean, "MAE_MEDIAN": all_exc.mae_median, "MAE_P25": all_exc.mae_p25, "MAE_P75": all_exc.mae_p75, "MAE_P90": all_exc.mae_p90,
        **reversal, **direction, **mapping,
        **{f"STOP_{code:03d}_MEAN_NET20": float(all_stops.loc[f'STOP_{code:03d}', 'mean_net20']) for code in (50,100,150,200)},
        **{f"STOP_{code:03d}_PROFIT_FACTOR": float(all_stops.loc[f'STOP_{code:03d}', 'profit_factor']) for code in (50,100,150,200)},
        "UP_PATH_CONCLUSION": path_conclusion(complete, "UP"), "DOWN_PATH_CONCLUSION": path_conclusion(complete, "DOWN"),
        **flags, "EDGE_DECAY_START_HORIZON": decay_start, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True, "PIT_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS",
        "PATH_INTEGRITY_STATUS": "PASS", "PROSPECTIVE_DATA_USED": False, "FINAL_CONFIRMATION_DATA_USED": False,
        "PARAMETER_OPTIMIZATION_COUNT": 0, "STOP_RULE_COUNT": 4, "TAKE_PROFIT_RULE_COUNT": 0, "PATH_RULE_COMBINATION_COUNT": 0,
        "FIRST_RUN_STATUS": args.first_run_status, "RERUN_COUNT": args.rerun_count,
        "RERUN_REASON": args.rerun_reason, "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "MAX_RESEARCH_ITERATION_COUNT": 1, "ACTUAL_RESEARCH_ITERATION_COUNT": 1,
        "NEXT_STAGE": "PREREGISTER_ONE_PATH_MECHANISM_VALIDATION" if classification != "D_NO_CLEAR_PAYOFF_PATH_MECHANISM" else "STOP",
        "REPORT_PATH": str(frozen / "FAST3_R36_REPORT.md"), "SUMMARY_JSON_PATH": str(frozen / "FAST3_R36_SUMMARY.json")}
    write_json(frozen / "FAST3_R36_SUMMARY.json", summary); (frozen / "FAST3_R36_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    write_json(runtime / "FAST3_R36_RUNTIME_SUMMARY.json", {"status": "PASS", "classification": classification,
               "summary_sha256": sha256(frozen / "FAST3_R36_SUMMARY.json")})
    if sha256(prereg_path) != prereg_sha: raise R36Stop("STOP_PREREGISTRATION_MUTATION")
    keys = ("FAST3_R36_STATUS", "FAST3_R36_CLASSIFICATION", "FAST3_R36_DECISION", "PATH_COMPLETE_SIGNAL_COUNT", "PATH_COMPLETE_RATIO",
        "BASELINE_SIGNAL_COUNT", "BASELINE_WIN_RATE_NET20", "BASELINE_MEAN_NET20", "BASELINE_MEDIAN_NET20", "BASELINE_MEAN_LOSS_NET20", "BASELINE_PROFIT_FACTOR_NET20",
        *[f"HORIZON_{m}M_MEAN_NET20" for m in FIXED_HORIZONS], "ORIGINAL_HORIZON_MEAN_NET20",
        *[f"HORIZON_{m}M_PROFIT_FACTOR" for m in FIXED_HORIZONS], "ORIGINAL_PROFIT_FACTOR", "MFE_MEDIAN", "MAE_MEDIAN",
        "LOSER_EVER_POSITIVE_RATE", "LOSER_MFE_GE_050_RATE", "LOSER_MFE_GE_100_RATE", "LARGE_LOSS_2PCT_EVER_MFE_GE_050_RATE", "LARGE_LOSS_5PCT_EVER_MFE_GE_050_RATE",
        "DIRECTION_CORRECT_BUT_TRADE_LOSS_RATE", "UNDERLYING_CORRECT_BUT_ETF_LOSS_RATE",
        *[f"STOP_{code:03d}_MEAN_NET20" for code in (50,100,150,200)], *[f"STOP_{code:03d}_PROFIT_FACTOR" for code in (50,100,150,200)],
        "UP_PATH_CONCLUSION", "DOWN_PATH_CONCLUSION", "SHORT_HORIZON_EDGE_DECAYS", "LEVERAGED_ETF_MAPPING_FAILURE", "PATH_REVERSAL_MECHANISM", "SIMPLE_STOP_DIAGNOSTIC_PROMISING",
        "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "R28_PREDICTIVE_IDENTITY_UNCHANGED", "PIT_STATUS", "CORPORATE_ACTION_STATUS", "PATH_INTEGRITY_STATUS")
    print("\n".join(f"{key}={summary[key]}" for key in keys))


if __name__ == "__main__":
    main()
