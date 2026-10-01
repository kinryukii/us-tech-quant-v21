"""V24 annual sequential challenger fits over the existing continuous account.

This entry point owns no feature, label, execution or account implementation.
A caller must acquire the shared task writer lease. Every annual learner sees
only the full earlier calendar prefix and earlier chronological OOF forecasts.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.research.a2.data.joint_input_binding import load_held_features
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.evaluation.joint_method_coverage import JointMethodCoverage
from scripts.research.a2.evaluation.joint_method_stages import prepare_market, task_writer
from scripts.research.a2.inference import joint_stateful_policy as sequential
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import runtime_bootstrap

YEARS = (2023, 2024, 2025)
METHODS = (("reinforce", "M030", 4), ("ppo", "M031", 5))
EXPECTED_COMPONENT_SHA = "9d97879a1686f52e311621599de619f193cbddadb940f755bf350ab187135abe"
TORCH_RUNTIME = Path("D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages")
REUSED_DEPENDENCIES = Path("D:/us-tech-quant-envs/frozen_dependency_snapshots/a2_predict_then_optimize_20260928_r1/third_party")
REWARD = "actual persistent account pretrade NAV log return from next execution Open to following Open; both qualified endpoints strictly before fold cutoff"
MAX_UPDATES = sequential.SPEC["max_optimizer_updates_all_algorithms_and_folds"]


def bind_runtime():
    """Parameterize the existing append-only bootstrap; never install packages."""
    if not TORCH_RUNTIME.is_dir() or not REUSED_DEPENDENCIES.is_dir():
        raise RuntimeError("Approved frozen dependency snapshot missing")
    old_local, old_reused = runtime_bootstrap.LOCAL_VENDOR, runtime_bootstrap.REUSED_VENDOR
    try:
        runtime_bootstrap.LOCAL_VENDOR = TORCH_RUNTIME
        runtime_bootstrap.REUSED_VENDOR = REUSED_DEPENDENCIES
        info = runtime_bootstrap.bootstrap()
    finally:
        runtime_bootstrap.LOCAL_VENDOR, runtime_bootstrap.REUSED_VENDOR = old_local, old_reused
    if info["modules"]["torch"]["status"] != "AVAILABLE":
        raise RuntimeError("Frozen Torch runtime unavailable")
    import torch
    torch.set_num_threads(2)
    # No interop global is changed: an already-initialized process remains valid.
    return info


def prefix_inputs(inputs, cutoff):
    """Slice every dated input to the same complete earlier calendar prefix."""
    cutoff = pd.Timestamp(cutoff)
    market = inputs["market"]
    if cutoff > pd.Timestamp("2026-01-01") or market.dates[-1] >= pd.Timestamp("2026-01-01"):
        raise ValueError("Physical sequential input crosses training boundary")
    count = int(market.dates.searchsorted(cutoff, side="left"))
    if count < 3 or market.dates[0] < pd.Timestamp(sequential.SPEC["first_signal"]):
        raise ValueError("No legal mature calendar prefix")
    arrays = ("open", "close", "quality", "adv", "input_present", "new_buy_eligible",
              "signal_mask", "buy_restricted", "sell_restricted", "row_present")
    changes = {name: getattr(market, name)[:count] for name in arrays}
    changes.update(dates=market.dates[:count], signal_asof=market.signal_asof[:count],
                   operational_exits={d: e for d, e in market.operational_exits.items()
                                      if pd.Timestamp(d) < cutoff})
    if market.known_restrictions_evidence is not None:
        evidence = pd.DataFrame(market.known_restrictions_evidence).copy()
        changes["known_restrictions_evidence"] = evidence.loc[
            pd.to_datetime(evidence.signal_date).lt(cutoff)].copy()
    prior = replace(market, **changes)
    events = inputs.get("replay_kwargs", {})
    actions = tuple(e for e in events.get("corporate_actions", ())
                    if pd.Timestamp(e.effective_date) < cutoff)
    fingerprints = {e.event_fingerprint for e in actions}
    known = {k: v for k, v in events.get("corporate_action_known_at", {}).items()
             if k in fingerprints}
    unsupported = tuple(e for e in events.get("unsupported_events", ())
                        if pd.Timestamp(e["effective_date"]) < cutoff)
    kwargs = dict(corporate_actions=actions, corporate_action_known_at=known,
                  unsupported_events=unsupported)
    features = inputs["feature_cube"][:count]
    mu = inputs["mu"]["EQUAL"][:count]
    sigma = inputs["sigma"]["EQUAL"][:count]
    if features.shape != (count, len(prior.tickers), 32) or mu.shape != sigma.shape or mu.shape != features.shape[:2]:
        raise ValueError("Sliced sequential input shapes do not align")
    identity = {
        "calendar_first": str(prior.dates[0].date()),
        "calendar_last": str(prior.dates[-1].date()),
        "calendar_sessions": count, "ticker_count": len(prior.tickers),
        "calendar_sha256": hashlib.sha256(prior.dates.asi8.tobytes()).hexdigest(),
        "feature_values_sha256": hashlib.sha256(np.ascontiguousarray(features).tobytes()).hexdigest(),
        "equal_mu_sha256": hashlib.sha256(np.ascontiguousarray(mu).tobytes()).hexdigest(),
        "equal_sigma_sha256": hashlib.sha256(np.ascontiguousarray(sigma).tobytes()).hexdigest(),
        "corporate_action_fingerprints": sorted(fingerprints),
        "corporate_action_known_at": {k: str(v) for k, v in sorted(known.items())},
        "unsupported_events": list(unsupported),
        "signal_sampling": False, "candidate_sampling": False,
        "fitted_state_future_rows": 0,
    }
    return prior, features, mu, sigma, kwargs, identity


def reward_audit_summary(audits):
    result = []
    for number, frame in enumerate(audits, 1):
        valid = frame.valid_learning_reward.astype(bool) if len(frame) else pd.Series([], dtype=bool)
        mature = frame.loc[valid, "reward_end_date"] if len(frame) else pd.Series([], dtype="datetime64[ns]")
        result.append({
            "rollout": number, "signal_steps": len(frame),
            "qualified_reward_steps": int(valid.sum()),
            "masked_reward_steps": int((~valid).sum()),
            "mask_reason_counts": {str(k): int(v) for k, v in frame.mask_reason.value_counts().items()} if len(frame) else {},
            "qualified_reward_endpoint_max": str(mature.max()) if len(mature) else None,
        })
    return result


def count_completed_updates(task, kind, year, updates):
    """Checkpoint an artifact's update count once, including after direct reuse."""
    if not isinstance(updates, int) or not 0 <= updates <= MAX_UPDATES:
        raise ValueError("Invalid completed optimizer count")
    records = [r for r in task.status["records"]
               if r["identity"]["kind"] == kind
               and r["identity"]["cutoff_exclusive"] == f"{year}-01-01"
               and r["status"] == "FIT_COMPLETE"]
    if len(records) != 1:
        raise RuntimeError("Sequential artifact does not have one canonical fit record")
    record = records[0]
    if record.get("rl_updates_counted"):
        if record.get("actual_parameter_updates") != updates:
            raise RuntimeError("Canonical optimizer count changed")
        return
    total = int(task.status["rl_optimizer_updates"]) + updates
    if total > MAX_UPDATES:
        raise RuntimeError("Shared optimizer budget exceeded")
    record.update(rl_updates_counted=True, actual_parameter_updates=updates)
    task.status["rl_optimizer_updates"] = total
    task.checkpoint()


def update_coverage(task, stages):
    coverage = pd.read_csv(task.out("METHOD_COVERAGE.csv"))
    for method, method_id, _ in METHODS:
        rows = [r for r in stages if r["method"] == method]
        statuses = [r["status"] for r in rows]
        if len(rows) == len(YEARS) and all(s == "FIT_COMPLETE" for s in statuses):
            status = "REAL_RL_FIT_AND_ZERO_PAIR_COMPLETE"
        elif any(s.startswith("BLOCKED") for s in statuses):
            status = "PARTIAL_RL_FIT_WITH_DOCUMENTED_BLOCK"
        else:
            status = "RL_STAGE_IN_PROGRESS"
        mask = coverage.method_id.eq(method_id)
        if int(mask.sum()) != 1:
            raise RuntimeError("RL coverage row is not unique")
        coverage.loc[mask, "status"] = status
        coverage.loc[mask, "evidence"] = "receipts/REAL_RL_TRAINING.json"
    coverage.to_csv(task.out("METHOD_COVERAGE.csv"), index=False)


def run(root):
    """The CLI acquires task_writer before any global state read or mutation."""
    task = JointMethodCoverage(root)
    if task.status.get("rl_optimizer_update_count_unknown"):
        raise RuntimeError("Prior failed RL update count is unknown; engineering review required")
    component_sha = digest(sequential.__file__)
    if component_sha != EXPECTED_COMPONENT_SHA:
        raise RuntimeError("Sequential component source changed after synthetic freeze")
    runtime = bind_runtime()
    inputs = prepare_market(root)
    market_receipt = task.read("receipts/MARKET_INPUTS.json")
    binding = task.read("INPUT_BINDING.json")
    held = load_held_features(binding)
    held.signal_date = pd.to_datetime(held.signal_date)
    if held.signal_date.ge("2026-01-01").any():
        raise ValueError("Held feature input crosses physical training boundary")
    freeze = {
        "status": "SOURCE_SPEC_INPUT_FROZEN_BEFORE_REAL_SEQUENTIAL_FIT",
        "runner_source": str(Path(__file__).resolve()),
        "runner_source_sha256": digest(__file__),
        "component_source_sha256": component_sha,
        "shared_account_source_sha256": digest("D:/us-tech-quant/scripts/research/a2/evaluation/continuous_research_account.py"),
        "runtime_bootstrap_source_sha256": digest(runtime_bootstrap.__file__),
        "input_binding_sha256": task.input_sha,
        "run_config_sha256": digest(task.out("RUN_CONFIG.json")),
        "market_cache_sha256": market_receipt["sha256"],
        "spec": dict(sequential.SPEC), "years": list(YEARS), "methods": [m[0] for m in METHODS],
        "reward_definition": REWARD, "opportunity_return_horizon_sessions": 5,
        "rl_reward_horizon_sessions": 1, "global_optimizer_update_cap": MAX_UPDATES,
        "fit_state_counts": {m: count for m, _, count in METHODS},
        "complete_prior_calendar": True, "future_open_in_policy_input": False,
        "normalizer_eligible_rows": "all earlier finite features and causal EQUAL calibrated mu/sigma; uncalibrated 2021 naturally masked",
        "runtime": runtime, "test2026_reads": 0,
    }
    freeze_rel = "receipts/SEQUENTIAL_FIT_FREEZE.json"
    if task.out(freeze_rel).exists():
        if task.read(freeze_rel) != freeze:
            raise RuntimeError("Real sequential freeze changed after attempt")
    else:
        task.write(freeze_rel, freeze)
    receipt_rel = "receipts/REAL_RL_TRAINING.json"
    stages = task.read(receipt_rel).get("stages", []) if task.out(receipt_rel).exists() else []
    for method, method_id, state_count in METHODS:
        kind = "sequential_" + method
        for year in YEARS:
            cutoff = pd.Timestamp(year, 1, 1)
            market, features, mu, sigma, kwargs, prefix = prefix_inputs(inputs, cutoff)
            frame = held.loc[held.signal_date.isin(market.dates)].copy()
            if frame.empty:
                raise RuntimeError("No source-backed held features for legal calendar prefix")
            prior_oof = {str(y): market_receipt["build_dependencies"]["oof"][str(y)]
                         for y in range(2021, year)}
            key = {
                "algorithm": method, "spec": dict(sequential.SPEC),
                "reward_definition": REWARD, "reward_horizon_sessions": 1,
                "opportunity_horizon_sessions": 5,
                "component_sha256": component_sha, "runner_sha256": digest(__file__),
                "cache_sha256": market_receipt["sha256"], "prior_oof_sha256": prior_oof,
                "cutoff": str(cutoff.date()), "prefix": prefix,
                "label_columns_fabricated": False, "fit_scope": "state-only existing held feature rows",
                "global_optimizer_update_cap": MAX_UPDATES,
            }
            old = next((r for r in task.status["records"]
                        if r["identity"]["kind"] == kind
                        and r["identity"]["cutoff_exclusive"] == str(cutoff.date())), None)
            remaining = MAX_UPDATES - int(task.status["rl_optimizer_updates"])
            if remaining <= 0 and old is None:
                stage = {"method": method, "method_id": method_id, "year": year,
                         "status": "BLOCKED_UPDATE_BUDGET_BEFORE_FIT", "actual_parameter_updates": 0,
                         "prefix": prefix, "trained_pair_available": False}
            else:
                attempted = False
                def creator():
                    nonlocal attempted
                    attempted = True
                    return sequential.train_sequential(
                        method, market, features, mu, sigma, inputs["account"],
                        cutoff=cutoff, replay_kwargs=kwargs,
                        epochs=sequential.SPEC["epochs"], seed=sequential.SPEC["seed"],
                        max_optimizer_updates=remaining)
                try:
                    bundle = task.fit_state(kind, year, key, frame, creator, state_count)
                except Exception as exc:
                    if attempted:
                        task.status["rl_optimizer_update_count_unknown"] = True
                    task.status["status"] = "RL_STAGE_FAILED_RETAINED"
                    task.checkpoint()
                    task.write(receipt_rel, {
                        "status": "RL_STAGE_FAILED_RETAINED", "freeze": freeze_rel, "stages": stages,
                        "failure": {"method": method, "year": year, "error": repr(exc),
                                    "update_count_unknown": attempted},
                        "actual_parameter_updates": task.status["rl_optimizer_updates"],
                        "test2026_reads": 0})
                    raise
                updates = int(bundle.get("actual_parameter_updates", 0))
                count_completed_updates(task, kind, year, updates)
                stage = {
                    "method": method, "method_id": method_id, "year": year, "status": bundle["status"],
                    "artifact": str(task.out(f"models/{kind}_{year}.joblib")),
                    "artifact_sha256": digest(task.out(f"models/{kind}_{year}.joblib")),
                    "actual_parameter_updates": updates, "prefix": prefix,
                    "normalization_rows": bundle.get("normalization_rows"),
                    "normalization_signal_max": bundle.get("normalization_signal_max"),
                    "initial_actor_sha256": bundle.get("initial_actor_sha256"),
                    "final_actor_sha256": bundle.get("final_actor_sha256"),
                    "actor_parameter_delta_l2": bundle.get("actor_parameter_delta_l2"),
                    "zero_pair_available": "zero_bundle" in bundle,
                    "trained_pair_available": "trained_bundle" in bundle,
                    "partial_bundle_available": "partial_bundle" in bundle,
                    "full_rollout_logs": bundle.get("logs", []),
                    "reward_audits": reward_audit_summary(bundle.get("reward_audits", [])),
                    "training_projection": bundle.get("training_projection"),
                    "failure_reason": bundle.get("reason"),
                    "fit_2026_rows": int(bundle.get("fit_2026_rows", 0)),
                }
            stages = [r for r in stages if not (r["method"] == method and r["year"] == year)] + [stage]
            task.write(receipt_rel, {
                "status": "REAL_RL_FITS_IN_PROGRESS", "freeze": freeze_rel, "stages": stages,
                "actual_parameter_updates": task.status["rl_optimizer_updates"],
                "optimizer_update_cap": MAX_UPDATES, "test2026_reads": 0})
            update_coverage(task, stages)
            task.checkpoint()
            print(json.dumps({"status": "SEQUENTIAL_FOLD_COMPLETE", "method": method,
                              "year": year, "fit_status": stage["status"],
                              "actual_parameter_updates": stage["actual_parameter_updates"],
                              "shared_parameter_updates": task.status["rl_optimizer_updates"]}), flush=True)
    complete = len(stages) == len(METHODS) * len(YEARS) and all(r["status"] == "FIT_COMPLETE" for r in stages)
    task.status["status"] = "REAL_RL_FITS_AND_ZERO_PAIRS_COMPLETE" if complete else "REAL_RL_FITS_WITH_DOCUMENTED_BLOCKS"
    task.write(receipt_rel, {
        "status": task.status["status"], "freeze": freeze_rel, "stages": stages,
        "actual_parameter_updates": task.status["rl_optimizer_updates"],
        "optimizer_update_cap": MAX_UPDATES, "test2026_reads": 0})
    task.checkpoint()
    return stages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True)
    args = parser.parse_args()
    with task_writer(args.task_root):
        run(args.task_root)


if __name__ == "__main__":
    main()

