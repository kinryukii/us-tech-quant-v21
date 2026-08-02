#!/usr/bin/env python
"""Bounded, resumable V22.082 multigeneration FAST3 research engine.

The audit phase reads only source metadata and freezes every outer fold.  Run
performs Development-only contiguous-time experiments until a generation is
complete, then opens its Validation and (only if legal) Confirmation exactly
once.  A failed generation advances; only a global stop writes the done flag.
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

import v22_081_bounded_self_improvement as base
import generation3r2_research as r2


NAME = "V22.082_FAST3_BOUNDED_MULTIGENERATION_AUTOPILOT_R1"
ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
OUT = Path(r"D:\us-tech-quant-results\fast3_v22_082_multigeneration_autopilot")
CONFIG_PATH = Path(__file__).with_name("v22_082_multigeneration_autopilot_config.json")
SAFETY = {"research_only": True, "canonical_data_writable": False, "broker_action_allowed": False,
          "paper_broker_order_allowed": False, "order_generation_allowed": False,
          "official_adoption_allowed": False, "remote_push_allowed": False}


def _default(value):
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, np.ndarray): return value.tolist()
    return str(value)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_default).encode()).hexdigest()


def now() -> str: return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, default=_default) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _et(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("America/New_York") if stamp.tzinfo is None else stamp.tz_convert("America/New_York")


def _month_end(start: pd.Timestamp, months: int) -> pd.Timestamp:
    return (start + pd.DateOffset(months=months)) - pd.Timedelta(microseconds=1)


def build_schedule(common: pd.DatetimeIndex, cfg: dict) -> dict:
    """Create the maximum schedule from metadata only; never inspect OHLC."""
    cursor = _et(cfg["first_validation_month"])
    earliest, latest = common.min(), common.max() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    folds = []
    for index in range(cfg["outer_fold_count_requested"]):
        validation_start, validation_end = cursor, _month_end(cursor, cfg["outer_fold_validation_months"])
        embargo1_start = validation_end + pd.Timedelta(microseconds=1)
        embargo1_end = _month_end(embargo1_start, cfg["outer_fold_embargo_months"])
        confirmation_start = embargo1_end + pd.Timedelta(microseconds=1)
        confirmation_end = _month_end(confirmation_start, cfg["outer_fold_confirmation_months"])
        if validation_start <= earliest or confirmation_end > latest: break
        folds.append({"generation_id": f"G{index + 1:02d}", "outer_fold_id": f"OUTER_{index + 1:02d}",
                      "development_start": _et(cfg["development_start"]), "development_end": validation_start - pd.Timedelta(microseconds=1),
                      "validation_start": validation_start, "validation_end": validation_end,
                      "embargo_start": embargo1_start, "embargo_end": embargo1_end,
                      "confirmation_start": confirmation_start, "confirmation_end": confirmation_end,
                      "validation_consumed": False, "confirmation_consumed": False})
        cursor = confirmation_end + pd.Timedelta(microseconds=1)
    result = {"research_id": NAME, "status": "FROZEN_BEFORE_V22_082_HOLDOUT_ECONOMICS", "timezone": "America/New_York",
              "source_common_start": earliest, "source_common_end": latest, "purge_minutes": cfg["purge_minutes"],
              "maximum_defensible_generations": len(folds), "requested_generations": cfg["outer_fold_count_requested"], "generations": folds,
              "prior_v22_081_consumed_holdouts": {"validation": {"start": "2026-04-01", "end": "2026-05-31", "consumed": True}, "confirmation": {"start": "2026-07-01", "end": "2026-07-28", "consumed": True}},
              "prior_v22_081_conclusion": "FAIL_CONFIRMATION retained as high-level failure diagnostic only", **SAFETY}
    result["schedule_sha256"] = digest(result)
    return result


def checkpoint(output: Path, **updates) -> dict:
    path = output / "v22_082_global_checkpoint.json"
    value = json.loads(path.read_text()) if path.exists() else {"stage": NAME, "state": "NEW", "completed_generations": 0, "total_experiments": 0, "next_action": "Run audit.", **SAFETY}
    value.update(updates); value["updated_at"] = now(); atomic_json(path, value); return value


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def write_rows(path: Path, values: list[dict]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(row, sort_keys=True, default=_default) + "\n" for row in values), encoding="utf-8")
    os.replace(temp, path)


def audit(output: Path, canonical: Path) -> None:
    dates, ends, source = r2.metadata_audit(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[s]) for s in r2.SYMBOLS if s != "SOXX"])))
    schedule = build_schedule(common, load_config())
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "split_schedule.json", schedule)
    (output / "split_schedule_sha256.txt").write_text(schedule["schedule_sha256"] + "\n", encoding="utf-8")
    atomic_json(output / "v22_082_source_metadata_audit.json", {"economic_values_read": False, "source": source, "common_start": common.min(), "common_end": common.max(), "prior_v22_081_audited": True, **SAFETY})
    checkpoint(output, state="SCHEDULE_FROZEN_AWAITING_DEVELOPMENT", schedule_sha256=schedule["schedule_sha256"], max_defensible_generations=schedule["maximum_defensible_generations"], current_generation_id="G01" if schedule["generations"] else None, next_action="Run G01 Development-only bounded contiguous-time experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_082_multigeneration_autopilot.py --phase run --output-dir {output}")


def root_candidate(cfg: dict, seed: int) -> dict:
    rng = np.random.default_rng(seed); features = list(r2.FEATURES)
    if r2.VIX_PATH.is_file(): features += list(r2.VIX_FEATURES)
    n = int(rng.integers(cfg["feature_count_range"][0], min(cfg["feature_count_range"][1], len(features)) + 1))
    return {"model_type": "logistic", "feature_names": sorted(rng.choice(features, n, replace=False).tolist()), "opportunity_threshold": .50, "direction_margin": .04,
            "label_horizon_minutes": cfg["default_label_horizon_minutes"], "exit_rule": "fixed_horizon_next_valid_open", "params": {"c": .4, "l1_ratio": .5, "depth": 3, "min_leaf": 500, "trees": 64, "iterations": 50, "leaves": 9, "l2": 5.0}, "complexity": 1}


def mutate_candidate(parent: dict, reason: str, cfg: dict, seed: int) -> tuple[dict, dict]:
    """One bounded, diagnosis-linked mutation; it never takes dates/trades as input."""
    child = json.loads(json.dumps(parent)); rng = np.random.default_rng(seed); families = cfg["model_families"]
    changes = {"model_family_changes": 0, "hyperparameter_changes": 0, "threshold_changes": 0, "label_horizon_changes": 0, "exit_rule_changes": 0}
    if reason in {"EXCESS_DRAWDOWN", "COST_FRAGILITY", "DELAY_FRAGILITY"}:
        child["opportunity_threshold"] = min(.70, child["opportunity_threshold"] + .05); child["direction_margin"] = min(.12, child["direction_margin"] + .02); changes["threshold_changes"] = 2; mutation = "raise NO_TRADE selectivity and retain fixed-horizon exit"
    elif reason in {"REGIME_INSTABILITY", "WEIGHT_INSTABILITY", "SEED_INSTABILITY"}:
        child["model_type"] = "elastic_net"; child["params"]["c"] = .15; child["params"]["l1_ratio"] = .85; changes["model_family_changes"] = int(parent["model_type"] != "elastic_net"); changes["hyperparameter_changes"] = 2; mutation = "reduce model variance with calibrated elastic-net two-stage models"
    elif reason in {"CONFIRMATION_SIGN_REVERSAL", "VALIDATION_SIGN_REVERSAL", "YEAR_CONCENTRATION", "SESSION_CONCENTRATION"}:
        child["label_horizon_minutes"] = 30 if parent["label_horizon_minutes"] == 60 else 60; child["direction_margin"] = min(.12, child["direction_margin"] + .02); changes["label_horizon_changes"] = 1; changes["threshold_changes"] = 1; mutation = "change predeclared label horizon and strengthen directional abstention"
    else:
        child["model_type"] = families[(families.index(parent["model_type"]) + 1) % len(families)]; child["params"]["min_leaf"] = int(rng.choice([500, 1000])); changes["model_family_changes"] = 1; changes["hyperparameter_changes"] = 1; mutation = "advance one compact model family after Development edge failure"
    child["feature_names"] = child["feature_names"][:cfg["max_active_features"]]; child["complexity"] = families.index(child["model_type"]) + 1
    return child, {"parent_reason": reason, "description": mutation, "changes": changes}


def _read_samples(canonical: Path, start, end) -> pd.DataFrame:
    data = {s: r2._read_range(canonical, s, _et(start), _et(end)) for s in ("SOXX", "QQQ", "SOXL", "SOXS")}
    samples = r2.build_samples(data)
    if r2.VIX_PATH.is_file(): samples = r2._vix_for_development(samples)
    return samples.dropna(subset=["opportunity_60m", "direction_up_conditional"])


def _window(samples: pd.DataFrame, index: int, cfg: dict):
    """Random contiguous as-of window, choosing only feasible declared lengths."""
    dates = np.array(sorted(pd.DatetimeIndex(samples.calendar_date.unique())))
    rng = np.random.default_rng(cfg["random_seeds"][index % len(cfg["random_seeds"])] + index)
    feasible = [(int(train_days), int(oos_days)) for train_days in cfg["inner_train_days"] for oos_days in cfg["inner_oos_days"]
                if train_days + oos_days + 1 <= len(dates)]
    if not feasible: raise RuntimeError("FAIL_DATA_CONTRACT:INSUFFICIENT_DEVELOPMENT_DAYS")
    train_days, oos_days = feasible[int(rng.integers(0, len(feasible)))]
    needed = train_days + oos_days + 1
    start = int(rng.integers(0, len(dates) - needed + 1))
    train_dates, oos_dates = dates[start:start + train_days], dates[start + needed - oos_days:start + needed]
    train, test = samples[samples.calendar_date.isin(train_dates)].copy(), samples[samples.calendar_date.isin(oos_dates)].copy()
    cutoff = test.decision_timestamp.min() - pd.Timedelta(minutes=cfg["purge_minutes"])
    train = train[train.decision_timestamp < cutoff]
    return train, test, {"train_start": train.decision_timestamp.min(), "train_end": train.decision_timestamp.max(), "embargo_start": cutoff, "embargo_end": test.decision_timestamp.min(), "oos_start": test.decision_timestamp.min(), "oos_end": test.decision_timestamp.max()}


def _evaluate(candidate: dict, train: pd.DataFrame, test: pd.DataFrame, seed: int, cfg: dict) -> tuple[dict, dict]:
    # Current authorized horizons share the same real executable 60-minute surface.
    # A 30m mutation is recorded and evaluated with its stricter entry policy while
    # the execution contract remains explicitly fixed at 60m until a 30m surface is added.
    core = {k: candidate[k] for k in ("model_type", "feature_names", "opportunity_threshold", "direction_margin", "params", "complexity")}
    metric, weights = base.evaluate(core, train, test, seed)
    metric["label_horizon_minutes"] = candidate["label_horizon_minutes"]
    metric["hard_drawdown_pass"] = bool(metric["max_drawdown"] is not None and metric["max_drawdown"] <= cfg["hard_max_drawdown"])
    return metric, weights


def _retain(records: list[dict], cfg: dict) -> list[str]:
    viable = [r for r in records if r.get("failure_reason") is None and r.get("trade_count", 0) >= cfg["minimum_development_trades"] and r.get("hard_drawdown_pass") and r.get("mean_net_10bps_delay1", -np.inf) > 0 and r.get("mean_net_20bps_delay1", -np.inf) > 0]
    return [r["experiment_id"] for r in sorted(viable, key=lambda x: (-x.get("score", -9), x["candidate"]["complexity"], x["experiment_id"]))[:cfg["max_active_candidates"]]]


def _failure(metric: dict, stage: str, cfg: dict) -> str:
    if metric.get("max_drawdown") is not None and metric["max_drawdown"] > cfg["hard_max_drawdown"]: return "EXCESS_DRAWDOWN"
    if metric.get("mean_net_20bps_delay1") is None or metric["mean_net_20bps_delay1"] <= 0: return "COST_FRAGILITY" if metric.get("mean_net_10bps_delay1", -1) > 0 else f"{stage}_SIGN_REVERSAL"
    if metric.get("mean_net_10bps_delay5") is None or metric["mean_net_10bps_delay5"] <= 0: return "DELAY_FRAGILITY"
    if metric.get("year_stability", 0) < .5: return "YEAR_CONCENTRATION"
    if metric.get("regime_stability", 0) < .5: return "REGIME_INSTABILITY"
    if metric.get("concentration", 1) >= .25: return "TRADE_CONCENTRATION"
    return f"{stage}_SIGN_REVERSAL"


def _pass(metric: dict, cfg: dict) -> bool:
    return bool(metric.get("trade_count", 0) >= cfg["minimum_holdout_trades"] and metric.get("mean_net_10bps_delay1", -1) > 0 and metric.get("mean_net_20bps_delay1", -1) > 0 and metric.get("mean_net_10bps_delay5", -1) > 0 and metric.get("max_drawdown", 1) <= cfg["hard_max_drawdown"] and metric.get("concentration", 1) < .25 and metric.get("year_stability", 0) >= .60 and metric.get("regime_stability", 0) >= .60)


def _generation_records(output: Path, gid: str) -> list[dict]: return [r for r in rows(output / "experiment_registry.jsonl") if r["generation_id"] == gid]


def _write_report(output: Path, final_status: str | None = None, reason: str | None = None) -> None:
    generations = rows(output / "generation_registry.jsonl"); experiments = rows(output / "experiment_registry.jsonl")
    cp = checkpoint(output)
    summary = {"stage": NAME, "FINAL_STATUS": final_status or "IN_PROGRESS", "GLOBAL_STOP_REASON": reason, "completed_generations": len(generations), "total_experiments": len(experiments), "generations": generations, "prior_v22_081_holdouts_consumed": True, "PROSPECTIVE_SHADOW_ALLOWED": False, **SAFETY}
    atomic_json(output / "v22_082_global_summary.json", summary)
    lines = [f"# {NAME}", "", f"FINAL_STATUS={summary['FINAL_STATUS']}", f"GLOBAL_STOP_REASON={reason or 'NONE'}", f"COMPLETED_GENERATIONS={len(generations)}", f"TOTAL_EXPERIMENTS={len(experiments)}", "", "V22.081 Validation and Confirmation are historical consumed holdouts; its FAIL_CONFIRMATION conclusion was preserved."]
    (output / "v22_082_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _global_stop(output: Path, schedule: dict, budget: dict) -> str | None:
    gens = rows(output / "generation_registry.jsonl"); exps = rows(output / "experiment_registry.jsonl")
    if any(g.get("generation_status") == "PASS_ALL_GATES" for g in gens): return "GENERATION_PASSED_ALL_FROZEN_GATES"
    if len(gens) >= min(budget["max_generations"], schedule["maximum_defensible_generations"]): return "MAX_GENERATIONS_OR_FOLDS_REACHED"
    if len(exps) >= min(budget["max_total_experiments"], budget["max_generations"] * budget["experiments_per_generation"]): return "MAX_TOTAL_EXPERIMENTS_REACHED"
    if len(gens) >= 3 and all(not g.get("material_outer_improvement", False) for g in gens[-3:]): return "THREE_CONSECUTIVE_NO_MATERIAL_OUTER_IMPROVEMENT"
    if len(gens) >= 3 and len({g.get("failure_class") for g in gens[-3:]}) == 1 and gens[-1].get("failure_class", "").startswith("CONFIRMATION"): return "THREE_SAME_CONFIRMATION_FAILURE_CLASS"
    return None


def _close_generation(output: Path, schedule: dict, budget: dict, fold: dict, candidate: dict | None, status: str, failure: str | None, validation_reads: int, confirmation_reads: int, validation_metric: dict | None, confirmation_metric: dict | None, mutation: dict | None) -> None:
    prior = rows(output / "generation_registry.jsonl"); parent = prior[-1]["generation_id"] if prior else None
    metric = confirmation_metric or validation_metric or {}
    improved = bool(not prior or (metric.get("mean_net_20bps_delay1") or -np.inf) > max([(g.get("outer_mean_net_20bps_delay1") or -np.inf) for g in prior]))
    record = {"generation_id": fold["generation_id"], "parent_generation_id": parent, "outer_fold_id": fold["outer_fold_id"], "generation_status": status, "mutation_reason": mutation.get("parent_reason") if mutation else "V22.081_HIGH_LEVEL_FAIL_CONFIRMATION_DIAGNOSTIC", "mutation_plan": mutation, "validation_read_count": validation_reads, "confirmation_read_count": confirmation_reads, "failure_class": failure, "holdout_consumed": {"validation": validation_reads == 1, "confirmation": confirmation_reads == 1}, "material_outer_improvement": improved, "outer_mean_net_20bps_delay1": metric.get("mean_net_20bps_delay1"), "next_generation_action": "ADVANCE_TO_NEXT_PREDECLARED_OUTER_FOLD" if status != "PASS_ALL_GATES" else "ZERO_ORDER_PROSPECTIVE_SHADOW_ONLY", "closed_at": now(), **SAFETY}
    gr = prior + [record]; write_rows(output / "generation_registry.jsonl", gr); atomic_json(output / "latest_generation_summary.json", record)
    stop = _global_stop(output, schedule, budget)
    if stop:
        _write_report(output, "PASS_NEGATIVE_OR_ELIGIBLE_RESEARCH_CONCLUSION", stop); checkpoint(output, state="GLOBAL_TERMINAL", completed_generations=len(gr), total_experiments=len(rows(output / "experiment_registry.jsonl")), next_action="None; legal global stop reached.", exact_resume_command="NONE_V22_082_GLOBAL_RESEARCH_STOPPED", global_stop_reason=stop); (output / "V22_082_GLOBAL_DONE.flag").write_text(stop + "\n", encoding="utf-8")
    else:
        checkpoint(output, state="ADVANCE_TO_NEXT_GENERATION", completed_generations=len(gr), total_experiments=len(rows(output / "experiment_registry.jsonl")), current_generation_id=f"G{len(gr)+1:02d}", next_action="Run next predeclared generation Development-only experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_082_multigeneration_autopilot.py --phase run --output-dir {output}")
        _write_report(output)


def run(output: Path, canonical: Path, max_new: int) -> None:
    if (output / "V22_082_GLOBAL_DONE.flag").exists(): return
    schedule = json.loads((output / "split_schedule.json").read_text(encoding="utf-8-sig")); budget = json.loads((output / "autopilot_budget.json").read_text(encoding="utf-8-sig")); cfg = load_config()
    closed = rows(output / "generation_registry.jsonl"); index = len(closed)
    if index >= schedule["maximum_defensible_generations"]:
        _write_report(output, "PASS_NEGATIVE_RESEARCH_CONCLUSION", "INSUFFICIENT_UNTOUCHED_OUTER_FOLDS"); (output / "V22_082_GLOBAL_DONE.flag").write_text("INSUFFICIENT_UNTOUCHED_OUTER_FOLDS\n"); return
    fold = schedule["generations"][index]; gid = fold["generation_id"]; records = _generation_records(output, gid); limit = budget["experiments_per_generation"]
    if len(records) < limit:
        samples = _read_samples(canonical, fold["development_start"], fold["development_end"])
        for _ in range(min(max_new, limit - len(records))):
            local = len(records); total = len(rows(output / "experiment_registry.jsonl")); seed = cfg["random_seeds"][total % len(cfg["random_seeds"])] + total
            prior_generation = closed[-1] if closed else None
            parent = max((r for r in records if r.get("failure_reason") is None), key=lambda r: r.get("score", -np.inf), default=None)
            if parent:
                candidate, mutation = mutate_candidate(parent["candidate"], "NO_DEVELOPMENT_EDGE", cfg, seed)
            elif prior_generation and prior_generation.get("mutation_plan"):
                candidate, mutation = mutate_candidate(root_candidate(cfg, seed), prior_generation.get("failure_class") or "NO_DEVELOPMENT_EDGE", cfg, seed)
            else: candidate, mutation = root_candidate(cfg, seed), {"parent_reason": "V22.081_HIGH_LEVEL_FAIL_CONFIRMATION_DIAGNOSTIC", "description": "new untouched outer-fold baseline", "changes": {"model_family_changes": 0, "hyperparameter_changes": 0, "threshold_changes": 0, "label_horizon_changes": 0, "exit_rule_changes": 0}}
            eid = f"{gid}_E{local + 1:03d}"
            try:
                train, test, window = _window(samples, total, cfg)
                if len(train) < 2000 or len(test) < 100: raise RuntimeError("INSUFFICIENT_INNER_SAMPLE")
                metric, weights = _evaluate(candidate, train, test, seed, cfg)
                failure = None if metric["hard_drawdown_pass"] else "EXCESS_DRAWDOWN"
            except Exception as exc:
                metric, weights, window, failure = {}, {}, {}, f"DATA_OR_LINEAGE_BLOCKER:{exc}"
            row = {"generation_id": gid, "experiment_id": eid, "parent_generation_id": closed[-1]["generation_id"] if closed else None, "parent_experiment_id": parent.get("experiment_id") if parent else None, "random_seed": seed, "schedule_sha256": schedule["schedule_sha256"], "model_contract_hash": digest(candidate), "candidate": candidate, "mutation_plan": mutation, "cost_bps": cfg["cost_bps"], "delay_minutes": cfg["delay_minutes"], "failure_reason": failure, "decision": "PENDING_RETENTION", **window, **metric, "factor_weights_or_importance": weights, **SAFETY}
            records.append(row); all_records = rows(output / "experiment_registry.jsonl") + [row]; active = _retain(records, cfg)
            for r in all_records:
                if r["generation_id"] == gid: r["decision"] = "FAILURE" if r.get("failure_reason") else ("RETAIN" if r["experiment_id"] in active else "PRUNE_UNSTABLE_OR_INFERIOR")
            write_rows(output / "experiment_registry.jsonl", all_records)
            checkpoint(output, state="DEVELOPMENT_SEARCH_IN_PROGRESS", current_generation_id=gid, total_experiments=len(all_records), completed_generations=len(closed), active_candidates=active, last_experiment_id=eid, next_action="Continue current generation Development-only experiments.", exact_resume_command=f"python scripts/v22/fast3_agent/v22_082_multigeneration_autopilot.py --phase run --output-dir {output}")
        return
    viable = [r for r in records if r.get("decision") == "RETAIN"]
    if not viable:
        _close_generation(output, schedule, budget, fold, None, "FAIL_DEVELOPMENT", "NO_DEVELOPMENT_EDGE", 0, 0, None, None, {"parent_reason": "NO_DEVELOPMENT_EDGE", "description": "advance compact model family", "changes": {"model_family_changes": 1, "hyperparameter_changes": 1, "threshold_changes": 0, "label_horizon_changes": 0, "exit_rule_changes": 0}}); return
    champion = sorted(viable, key=lambda x: (-x.get("score", -9), x["candidate"]["complexity"], x["experiment_id"]))[0]; candidate = champion["candidate"]
    atomic_json(output / "champion_config.json", {"status": "FROZEN_BEFORE_VALIDATION", "generation_id": gid, "experiment_id": champion["experiment_id"], "config": candidate, "config_sha256": digest(candidate), "schedule_sha256": schedule["schedule_sha256"], **SAFETY})
    dev = _read_samples(canonical, fold["development_start"], fold["development_end"]); validation = _read_samples(canonical, fold["validation_start"], fold["validation_end"])
    vm, _ = _evaluate(candidate, dev[dev.decision_timestamp < _et(fold["validation_start"]) - pd.Timedelta(minutes=cfg["purge_minutes"])], validation, 820820 + index, cfg); atomic_json(output / f"{gid.lower()}_validation_metrics.json", {"read_count": 1, "passed": _pass(vm, cfg), "metrics": vm, **SAFETY})
    if not _pass(vm, cfg):
        reason = _failure(vm, "VALIDATION", cfg); _close_generation(output, schedule, budget, fold, candidate, "FAIL_VALIDATION", reason, 1, 0, vm, None, mutate_candidate(candidate, reason, cfg, 820830 + index)[1]); return
    combined = pd.concat([dev, validation], ignore_index=True); confirmation = _read_samples(canonical, fold["confirmation_start"], fold["confirmation_end"]); cm, _ = _evaluate(candidate, combined[combined.decision_timestamp < _et(fold["confirmation_start"]) - pd.Timedelta(minutes=cfg["purge_minutes"])], confirmation, 820840 + index, cfg); atomic_json(output / f"{gid.lower()}_confirmation_metrics.json", {"read_count": 1, "passed": _pass(cm, cfg), "metrics": cm, **SAFETY})
    if not _pass(cm, cfg):
        reason = _failure(cm, "CONFIRMATION", cfg); _close_generation(output, schedule, budget, fold, candidate, "FAIL_CONFIRMATION", reason, 1, 1, vm, cm, mutate_candidate(candidate, reason, cfg, 820850 + index)[1]); return
    _close_generation(output, schedule, budget, fold, candidate, "PASS_ALL_GATES", None, 1, 1, vm, cm, None)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("audit", "run"), required=True); parser.add_argument("--output-dir", default=str(OUT)); parser.add_argument("--canonical-root", default=str(ROOT)); parser.add_argument("--max-new", type=int, default=1); args = parser.parse_args()
    if args.phase == "audit": audit(Path(args.output_dir), Path(args.canonical_root)); print("FINAL_STATUS=SPLIT_FROZEN_AWAITING_DEVELOPMENT")
    else: run(Path(args.output_dir), Path(args.canonical_root), args.max_new); print("FINAL_STATUS=" + checkpoint(Path(args.output_dir)).get("state", "UNKNOWN"))


if __name__ == "__main__": main()
