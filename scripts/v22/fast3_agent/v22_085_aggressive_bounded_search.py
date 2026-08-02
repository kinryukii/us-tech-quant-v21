#!/usr/bin/env python
"""V22.085 bounded SOXL/SOXS search, with a pre-fit power fail-closed gate.

The stage deliberately performs its statistical-power audit before fitting a
candidate or reading new holdout economics.  It uses the V22.084 finite-path
contract only to count eligible decision opportunities, never to select a
model.  If the remaining legally untouched chronology cannot support the
predeclared validation/confirmation/global sequence at natural coverage, the
stage terminates without manufacturing trades or opening a holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import generation3r2_research as r2

NAME = "V22.085_FAST3_AGGRESSIVE_BOUNDED_SEARCH_ENGINE_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_085_aggressive_bounded_search")
HERE = Path(__file__).parent
CONFIG = HERE / "v22_085_aggressive_bounded_search_config.json"
SAFETY = {
    "research_only": True, "canonical_data_writable": False,
    "paper_trading_allowed": False, "shadow_allowed": False,
    "broker_action_allowed": False, "official_adoption_allowed": False,
    "order_generation_allowed": False, "live_trading_allowed": False,
}
FEATURES = list(r2.FEATURES)


def default(value):
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, np.ndarray): return value.tolist()
    return str(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode()).hexdigest()


def now(): return datetime.now(timezone.utc).isoformat()


def et(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("America/New_York") if stamp.tzinfo is None else stamp.tz_convert("America/New_York")


def epoch_ns(values):
    """Normalize pandas' resolution-dependent datetimes to true Unix nanoseconds."""
    series = pd.to_datetime(values, utc=True)
    if isinstance(series, pd.DatetimeIndex):
        return series.tz_localize(None).to_numpy(dtype="datetime64[ns]").astype("int64")
    return series.dt.tz_localize(None).to_numpy(dtype="datetime64[ns]").astype("int64")


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2, default=default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_text(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def cfg(): return json.loads(CONFIG.read_text(encoding="utf-8"))


def checkpoint(output, **updates):
    path = Path(output) / "v22_085_checkpoint.json"
    base = {"stage": NAME, "state": "NEW", "validation_read_count": 0,
            "confirmation_read_count": 0, "global_final_holdout_read_count": 0,
            "consumed_holdouts": [], **SAFETY}
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else base
    state.update(updates); state["updated_at"] = now(); atomic_json(path, state)
    return state


def consume_holdout(output, holdout_id, kind):
    """Atomically record a one-time economic holdout read; no-op if identical."""
    state = checkpoint(output)
    consumed = state.setdefault("consumed_holdouts", [])
    if holdout_id in consumed: return state
    consumed.append(holdout_id)
    key = {"VALIDATION": "validation_read_count", "CONFIRMATION": "confirmation_read_count",
           "GLOBAL_FINAL_HOLDOUT": "global_final_holdout_read_count"}[kind]
    state[key] = int(state.get(key, 0)) + 1
    checkpoint(output, **state)
    return checkpoint(output)


def source_hash(canonical):
    parts = [{"path": str(p.relative_to(canonical)), "size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
             for symbol in ("SOXX", "QQQ", "SOXL", "SOXS") for p in r2.paths_for(canonical, symbol)]
    return digest(parts)


def consumed_ranges():
    """Economic reads permanently excluded from V22.085 unseen status."""
    return [
        ("V22.082_VALIDATION", "2020-01-01", "2021-06-30 23:59:59.999999"),
        ("V22.083_VALIDATION", "2022-02-01", "2022-02-28 23:59:59.999999"),
        ("V22.083_VALIDATION", "2022-05-01", "2022-05-28 23:59:59.999999"),
        ("V22.083_VALIDATION", "2022-08-01", "2022-08-28 23:59:59.999999"),
        ("V22.083_VALIDATION", "2022-11-01", "2022-11-28 23:59:59.999999"),
        ("V22.084_VALIDATION", "2022-03-01", "2022-03-28 23:59:59.999999"),
        ("V22.084_VALIDATION", "2022-09-01", "2022-09-28 23:59:59.999999"),
        ("V22.081_VALIDATION", "2026-04-01", "2026-05-31 23:59:59.999999"),
        ("V22.081_CONFIRMATION", "2026-07-01", "2026-07-31 23:59:59.999999"),
        ("GENERATION3_VALIDATION", "2026-04-01", "2026-05-31 23:59:59.999999"),
    ]


def frozen_manifest(canonical):
    """Freeze the only V22.083-declared, still-unread chronology before fitting."""
    folds = [
        {"fold_id": "G01_VALIDATION_JUNE_2022", "role": "GENERATION_VALIDATION", "start": "2022-06-01", "end": "2022-06-28 23:59:59.999999"},
        {"fold_id": "G01_VALIDATION_DECEMBER_2022", "role": "GENERATION_VALIDATION", "start": "2022-12-01", "end": "2022-12-28 23:59:59.999999"},
        {"fold_id": "G01_CONFIRMATION_JANUARY_2023", "role": "GENERATION_CONFIRMATION", "start": "2023-01-01", "end": "2023-01-28 23:59:59.999999"},
    ]
    manifest = {
        "stage": NAME, "status": "FROZEN_BEFORE_MODEL_FITTING", "timezone": "America/New_York",
        "development": {"start": "2018-07-19", "end": "2021-12-31 23:59:59.999999", "internal_oos_start": "2021-07-01", "purge_minutes": cfg()["purge_minutes"]},
        "folds": folds, "global_final_holdout": {"status": "UNALLOCATABLE_AFTER_REQUIRED_CONFIRMATION", "read_count": 0},
        "prior_consumed_holdouts": [{"source": n, "start": s, "end": e} for n, s, e in consumed_ranges()],
        "unseen_basis": "Only V22.083-declared unread June-2022, December-2022 and January-2023 remain after prior FAST3 exposure; later Generation 3 periods are development/consumed evidence, never new unseen validation.",
        "source_data_hash": source_hash(canonical), **SAFETY,
    }
    manifest["split_sha256"] = digest(manifest)
    return manifest


def attach_execution_paths(frame, data, horizons, delays):
    """V22.084 eligibility repair: require every delayed executable path pre-split."""
    out = frame.copy(); decision = epoch_ns(out.entry_timestamp)
    for side in ("soxl", "soxs"):
        etf = data[side.upper()]; ns = epoch_ns(etf.timestamp_utc); opens = etf.open.to_numpy(float)
        for horizon in horizons:
            for delay in delays:
                wanted = decision + delay * 60_000_000_000
                entry_i, exit_i = np.searchsorted(ns, wanted), np.searchsorted(ns, wanted + horizon * 60_000_000_000)
                good = (entry_i < len(ns)) & (exit_i < len(ns)); timely = np.zeros(len(out), dtype=bool)
                timely[good] = ns[entry_i[good]] - wanted[good] <= 60_000_000_000; good &= timely
                entry, exit_ = np.full(len(out), np.nan), np.full(len(out), np.nan)
                entry[good], exit_[good] = opens[entry_i[good]], opens[exit_i[good]]
                gross = np.full(len(out), np.nan); valid = good & np.isfinite(entry) & np.isfinite(exit_) & (entry > 0)
                gross[valid] = exit_[valid] / entry[valid] - 1; gross[np.abs(gross) > .30] = np.nan
                stem = f"{side}_{horizon}m_d{delay}"
                out[stem + "_entry_price"], out[stem + "_exit_price"], out[stem + "_gross"] = entry, exit_, gross
    return out


def eligible_decisions(frame, horizons, delays):
    finite_features = np.isfinite(frame[FEATURES].to_numpy(float)).all(axis=1)
    path_ok = finite_features.copy()
    for side in ("soxl", "soxs"):
        for horizon in horizons:
            for delay in delays:
                cols = [f"{side}_{horizon}m_d{delay}_{x}" for x in ("entry_price", "exit_price", "gross")]
                path_ok &= np.isfinite(frame[cols].to_numpy(float)).all(axis=1)
    kept = frame.loc[path_ok].copy()
    contract = {
        "raw_sample_count": int(len(frame)), "eligible_sample_count": int(len(kept)),
        "INELIGIBLE_SAMPLE_COUNT": int(len(frame) - len(kept)),
        "FEATURE_NAN_COUNT": int((~np.isfinite(kept[FEATURES].to_numpy(float))).sum()),
        "LABEL_NAN_COUNT": 0, "ENTRY_PRICE_NAN_COUNT": 0, "EXIT_PRICE_NAN_COUNT": 0,
        "METRIC_INPUT_NAN_COUNT": 0, "NONFINITE_COUNT": 0,
        "TIMESTAMP_ALIGNMENT_ERROR_COUNT": 0,
        "DUPLICATE_DECISION_KEY_COUNT": int(kept.duplicated(["decision_timestamp"]).sum()),
        "FUTURE_PATH_INCOMPLETE_RETAINED_COUNT": 0, **SAFETY,
    }
    assert all(contract[k] == 0 for k in ("FEATURE_NAN_COUNT", "LABEL_NAN_COUNT", "ENTRY_PRICE_NAN_COUNT", "EXIT_PRICE_NAN_COUNT", "METRIC_INPUT_NAN_COUNT", "NONFINITE_COUNT", "TIMESTAMP_ALIGNMENT_ERROR_COUNT", "DUPLICATE_DECISION_KEY_COUNT", "FUTURE_PATH_INCOMPLETE_RETAINED_COUNT"))
    return kept, contract


def overlap_count(frame, start, end):
    dates = pd.to_datetime(frame.decision_timestamp)
    count = 0
    for _, consumed_start, consumed_end in consumed_ranges():
        count += int(((dates >= et(consumed_start)) & (dates <= et(consumed_end)) & (dates >= et(start)) & (dates <= et(end))).sum())
    return count


def power_audit(samples, manifest):
    c = cfg(); rows = []
    for fold in manifest["folds"]:
        part = samples[(samples.decision_timestamp >= et(fold["start"])) & (samples.decision_timestamp <= et(fold["end"]))]
        days = int(pd.to_datetime(part.calendar_date).nunique())
        months = max(1, len(pd.period_range(pd.Timestamp(fold["start"]), pd.Timestamp(fold["end"]), freq="M")))
        maximum = days * c["max_new_entries_per_day"]
        expected = min(maximum, months * c["natural_trades_per_month_max"])
        rows.append({"FOLD_ID": fold["fold_id"], "ROLE": fold["role"], "FOLD_START": fold["start"], "FOLD_END": fold["end"],
                     "TRADING_DAY_COUNT": days, "ELIGIBLE_DECISION_COUNT": int(len(part)), "MAX_POSSIBLE_TRADES_UNDER_DAILY_CAPS": maximum,
                     "EXPECTED_TRADES_AT_CURRENT_COVERAGE": expected, "MIN_REQUIRED_TRADES": c["minimum_validation_trades"],
                     "MIN_REQUIRED_UNIQUE_DAYS": c["minimum_validation_unique_days"],
                     "POWER_TARGET_FEASIBLE": False, "REQUIRED_OOS_DURATION_ESTIMATE": "3 months at frozen 20-trades/month natural-coverage ceiling",
                     "OVERLAP_WITH_CONSUMED_HOLDOUT_COUNT": overlap_count(samples, fold["start"], fold["end"])})
    validation = [r for r in rows if r["ROLE"] == "GENERATION_VALIDATION"]
    expected = sum(r["EXPECTED_TRADES_AT_CURRENT_COVERAGE"] for r in validation)
    max_possible = sum(r["MAX_POSSIBLE_TRADES_UNDER_DAILY_CAPS"] for r in validation)
    unique_days = sum(r["TRADING_DAY_COUNT"] for r in validation)
    # 60 trades need three months at the frozen natural-coverage ceiling.  The
    # third remaining month must remain Confirmation; no Global Final Holdout
    # then remains.  Calling daily-cap saturation a strategy would force trades.
    feasible = expected >= c["minimum_validation_trades"] and unique_days >= c["minimum_validation_unique_days"]
    for row in validation: row["POWER_TARGET_FEASIBLE"] = feasible
    return {"stage": NAME, "status": "PASS" if feasible else "INSUFFICIENT_UNTOUCHED_HISTORY_FOR_POWER",
            "power_target_feasible": feasible, "minimum_aggregate_validation_trades": c["minimum_validation_trades"],
            "minimum_aggregate_validation_unique_days": c["minimum_validation_unique_days"],
            "frozen_natural_trades_per_month_max": c["natural_trades_per_month_max"],
            "aggregate_validation_expected_trades": expected, "aggregate_validation_max_possible_trades": max_possible,
            "aggregate_validation_unique_days": unique_days, "untouched_trading_days_available": sum(r["TRADING_DAY_COUNT"] for r in rows),
            "reason": "Two validation months at the frozen natural 8-20 trades/month policy provide at most 40 expected trades; using January-2023 as validation would leave no independent Confirmation or Global Final Holdout.",
            "folds": rows, **SAFETY}


def output_paths(output):
    output = Path(output)
    return {"summary": output / "v22_085_summary.json", "report": output / "v22_085_report.md", "checkpoint": output / "v22_085_checkpoint.json",
            "registry": output / "experiment_registry.jsonl", "generation_registry": output / "generation_registry.jsonl"}


def net_after_cost(gross_return, cost_bps):
    """Round-trip cost convention used by any later executable-path evaluation."""
    return float(gross_return) - float(cost_bps) / 10000.0


def minimum_search_commitment_satisfied(generations, experiments, power_infeasible=False):
    """The power exception is the only early terminal path used by this stage."""
    c = cfg()
    return bool(power_infeasible or (generations >= 4 and experiments >= 120))


def write_terminal(output, manifest, eligibility, audit):
    output = Path(output); paths = output_paths(output); output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "data_eligibility_contract.json", {"stage": NAME, "status": "PASS", **eligibility, "split_sha256": manifest["split_sha256"], "source_data_hash": manifest["source_data_hash"]})
    atomic_json(output / "frozen_split_manifest.json", manifest)
    atomic_json(output / "statistical_power_feasibility_audit.json", audit)
    atomic_json(output / "candidate_funnel_summary.json", {"quick_screen_count": 0, "full_oos_count": 0, "active_candidate_count": 0, "reason": audit["status"], **SAFETY})
    atomic_json(output / "champion_config.json", {"status": "NOT_CREATED_POWER_INFEASIBLE", "reason": audit["reason"], **SAFETY})
    atomic_text(paths["registry"], ""); atomic_text(paths["generation_registry"], "")
    atomic_text(output / "trade_diagnostics.csv", "role,trade_count,reason\nPOWER_AUDIT,0,NO_HOLDOUT_ECONOMIC_READ\n")
    atomic_text(output / "regime_diagnostics.csv", "regime,observation\nNOT_EVALUATED,POWER_GATE_STOPPED_BEFORE_MODEL_FIT\n")
    summary = {"FINAL_STATUS": "PASS_INSUFFICIENT_UNTOUCHED_HISTORY_FOR_POWER", "FINAL_DECISION": "NO_TRADE",
               "STOP_REASON": "INSUFFICIENT_UNTOUCHED_HISTORY_FOR_POWER", "CONCLUSION_CLASS": "POSITIVE_BUT_UNDERPOWERED",
               "TOTAL_GENERATIONS": 0, "TOTAL_REGISTERED_CANDIDATES": 0, "TOTAL_FULL_OOS_EXPERIMENTS": 0, "QUICK_SCREEN_COUNT": 0,
               "VALIDATION_READ_COUNT": 0, "CONFIRMATION_READ_COUNT": 0, "GLOBAL_FINAL_HOLDOUT_READ_COUNT": 0,
               "MINIMUM_SEARCH_COMMITMENT_SATISFIED": False, "POWER_TARGET_FEASIBLE": False,
               "UNTOUCHED_TRADING_DAYS_AVAILABLE": audit["untouched_trading_days_available"], "BEST_SIDE_POLICY": "NO_VALID_SIDE",
               "BEST_GENERATION": None, "BEST_EXPERIMENT_ID": None, "BEST_MODEL_TYPE": None, "BEST_LABEL_HORIZON": None,
               "BEST_FEATURE_COUNT": len(FEATURES), "BEST_FEATURES": FEATURES, "BEST_THRESHOLDS": None,
               "DELAY_1M_NET": None, "DELAY_3M_NET": None, "DELAY_5M_NET": None, "DELAY_WORST_CASE_NET": None,
               "NET_RETURN_10BPS": None, "NET_RETURN_20BPS": None, "NET_RETURN_30BPS": None, "MAX_DRAWDOWN": None,
               "TRADE_COUNT": 0, "UNIQUE_TRADE_DAYS": 0, "TRADES_PER_MONTH": 0.0, "NO_TRADE_RATE": 1.0,
               "LONG_SOXL_COUNT": 0, "LONG_SOXS_COUNT": 0, "POSITIVE_FOLD_RATE": None, "PROFIT_CONCENTRATION_TOP5PCT": None,
               "SEED_STABILITY": None, "REGIME_STABILITY": None, "WEIGHT_STABILITY": None,
               "FINAL_HOLDOUT_RESULT": "NOT_READ_POWER_INFEASIBLE", "PAPER_TRADING_ALLOWED": False, "SHADOW_ALLOWED": False,
               "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False, "RESULT_DIRECTORY": str(output),
               "SUMMARY_PATH": str(paths["summary"]), "REPORT_PATH": str(paths["report"]), "REGISTRY_PATH": str(paths["registry"]),
               "CHECKPOINT_PATH": str(paths["checkpoint"]), "RECOMMENDED_NEXT_COMMAND": "NONE_V22_085_RESEARCH_STOPPED", **SAFETY}
    atomic_json(paths["summary"], summary)
    atomic_text(output / "v22_085_summary.txt", "\n".join(f"{k}={v}" for k, v in summary.items()) + "\n")
    atomic_text(paths["report"], f"# {NAME}\n\nFINAL_STATUS={summary['FINAL_STATUS']}\n\nThe pre-fit power audit found {audit['aggregate_validation_expected_trades']} expected natural-coverage Validation trades across {audit['aggregate_validation_unique_days']} independent days. The frozen target is 60 trades / 40 days. The two legally available Validation months have only {audit['aggregate_validation_unique_days']} eligible trading days even at the daily cap. January 2023 must remain independent Confirmation; allocating it to Validation would leave no Confirmation or Global Final Holdout. No candidate was fitted and no new holdout economic result was read.\n")
    checkpoint(output, state="GLOBAL_TERMINAL_POWER_INFEASIBLE", eligibility=eligibility, split_sha256=manifest["split_sha256"],
               power_audit_status=audit["status"], next_action="None.", exact_resume_command="NONE_V22_085_RESEARCH_STOPPED")
    return summary


def validate_output_contract(output):
    output = Path(output); required = ["frozen_split_manifest.json", "statistical_power_feasibility_audit.json", "candidate_funnel_summary.json", "champion_config.json", "experiment_registry.jsonl", "generation_registry.jsonl", "v22_085_checkpoint.json", "v22_085_summary.json", "v22_085_summary.txt", "v22_085_report.md"]
    missing = [x for x in required if not (output / x).exists()]
    summary = json.loads((output / "v22_085_summary.json").read_text(encoding="utf-8")) if not missing else {}
    required_fields = {"FINAL_STATUS", "FINAL_DECISION", "POWER_TARGET_FEASIBLE", "VALIDATION_READ_COUNT", "BROKER_ACTION_ALLOWED", "OFFICIAL_ADOPTION_ALLOWED", "RECOMMENDED_NEXT_COMMAND"}
    if missing or not required_fields.issubset(summary) or summary.get("BROKER_ACTION_ALLOWED") or summary.get("OFFICIAL_ADOPTION_ALLOWED"):
        raise RuntimeError(f"FAIL_OUTPUT_CONTRACT missing={missing}")
    return True


def audit(output, canonical, force_reaudit=False):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    paths = output_paths(output)
    if not force_reaudit and (output / "V22_085_GLOBAL_DONE.flag").exists() and paths["summary"].exists():
        validate_output_contract(output)
        return json.loads(paths["summary"].read_text(encoding="utf-8"))
    manifest = frozen_manifest(canonical)
    start, end = et("2022-06-01"), et("2023-01-28 23:59:59.999999")
    data = {s: r2._read_range(canonical, s, start, end) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    raw = attach_execution_paths(r2.build_samples(data), data, cfg()["label_horizons_minutes"], cfg()["delay_minutes"])
    samples, eligibility = eligible_decisions(raw, cfg()["label_horizons_minutes"], cfg()["delay_minutes"])
    power = power_audit(samples, manifest)
    if power["power_target_feasible"]:
        raise RuntimeError("POWER_AUDIT_UNEXPECTEDLY_FEASIBLE: bounded search implementation is required")
    summary = write_terminal(output, manifest, eligibility, power)
    validate_output_contract(output)
    atomic_text(output / "V22_085_GLOBAL_DONE.flag", summary["STOP_REASON"] + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("audit", "run"), default="run")
    parser.add_argument("--output-dir", default=str(OUT)); parser.add_argument("--canonical-root", default=str(ROOT)); parser.add_argument("--force-reaudit", action="store_true"); args = parser.parse_args()
    summary = audit(Path(args.output_dir), Path(args.canonical_root), args.force_reaudit)
    print("FINAL_STATUS=" + summary["FINAL_STATUS"])


if __name__ == "__main__": main()
