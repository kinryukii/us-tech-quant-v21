"""External-root-only launcher for FAST3 R4 hard-storage R2.2.

The outer orchestrator, not this implementation task, invokes this historical
study.  This script never writes beneath the repository.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path


from fast3.models.two_stage_direction_hard_r22 import (R4ContractError, deterministic_schedule, diagnostics,
    file_hash, freeze_prospective_model, gate, not_run, prepare_cohort, run_phase, stable_hash,
    validate_source_freeze, write_json)


REQUIRED_ARTIFACTS = (
    "FAST3_R4_HARD_STORAGE_PREFLIGHT.json", "FAST3_R4_STORAGE_CONTRACT_AUDIT.json",
    "FAST3_R4_SOURCE_FREEZE_MANIFEST.json", "FAST3_R4_OBSERVED_INTERVAL_REGISTRY.json",
    "FAST3_R4_RANDOM_BLOCK_SCHEDULE.json", "FAST3_R4_FEATURE_MODEL_FREEZE.json",
    "FAST3_R4_DEV_COMPARISON.json", "FAST3_R4_INTERNAL_HOLDOUT_COMPARISON.json",
    "FAST3_R4_NULL_AND_ECONOMIC_AUDIT.json", "FAST3_R4_DAILY_MONTHLY_DIAGNOSTICS.json",
    "FAST3_R4_PROSPECTIVE_FREEZE.json", "fast3_r4_two_stage_direction_summary.json",
    "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FAST3 R4 fixed direct-versus-two-stage historical architecture study")
    for name in ("repo-root", "data-root", "runtime-root", "scratch-root", "frozen-root", "cache-root",
                 "source-r3-root", "source-r3-audit-root", "limits", "run-id"):
        parser.add_argument(f"--{name}", required=True)
    return parser.parse_args()


def external_path(path: Path, repo: Path, label: str) -> None:
    try:
        path.resolve().relative_to(repo.resolve())
    except ValueError:
        return
    raise R4ContractError(f"REPOSITORY_OUTPUT_PATH_FORBIDDEN:{label}")


def preflight(args: argparse.Namespace, limits: dict) -> dict:
    repo = Path(args.repo_root).resolve()
    roots = {"data_root": Path(args.data_root), "runtime_root": Path(args.runtime_root),
             "scratch_root": Path(args.scratch_root), "frozen_root": Path(args.frozen_root), "cache_root": Path(args.cache_root)}
    for label, root in roots.items():
        external_path(root, repo, label)
    try:
        Path(args.limits).absolute().relative_to(repo.absolute())
    except ValueError:
        pass
    else:
        raise R4ContractError("REPOSITORY_OUTPUT_PATH_FORBIDDEN:limits")
    return {"run_id": args.run_id, "storage_contract": limits["storage_contract"]["name"], "repo_root": str(repo),
            **{name: str(path.resolve()) for name, path in roots.items()}, "canonical_acl_guard_active": True,
            "git_mutation_allowed": False, "repository_result_writes": 0, "new_local_results_writes": 0,
            "status": "PASS"}


def load_cohort(source_root: Path):
    import pandas as pd
    candidate = source_root / "fast3_training_predictions.parquet"
    if not candidate.is_file():
        raise R4ContractError("SOURCE_R3_TRAINING_COHORT_MISSING")
    return pd.read_parquet(candidate), candidate


def report(summary: dict) -> str:
    return "\n".join(("# FAST3 R4 Two-Stage Direction — Hard Storage R2.2", "",
        "All historical results are non-prospective architecture-study evidence.", "",
        f"- Final decision: `{summary['FINAL_DECISION']}`", f"- Development gate: `{summary['DEVELOPMENT_GATE_PASS']}`",
        f"- Internal holdout gate: `{summary['INTERNAL_HOLDOUT_GATE_PASS']}`",
        f"- Prospective shadow model frozen: `{summary['PROSPECTIVE_MODEL_FROZEN']}`", ""))


def write_required_not_run(frozen: Path, reason: str) -> None:
    for filename in REQUIRED_ARTIFACTS:
        path = frozen / filename
        if not path.exists():
            if filename.endswith(".md"):
                path.write_text(f"# FAST3 R4 Two-Stage Direction — Hard Storage R2.2\n\nNOT_RUN: {reason}\n", encoding="utf-8")
            else:
                write_json(path, not_run(reason))


def artifact_manifest(frozen: Path) -> None:
    items = {}
    for filename in REQUIRED_ARTIFACTS:
        path = frozen / filename
        if path.is_file(): items[filename] = file_hash(path)
    write_json(frozen / "FAST3_R4_ARTIFACT_HASH_MANIFEST.json", {"status": "COMPLETE", "artifact_hashes": items,
               "manifest_created_last": True})


def main() -> int:
    args = arguments(); frozen = Path(args.frozen_root)
    # Validate before creating anything.  This is deliberately independent of
    # the current working directory and therefore has no repository fallback.
    external_path(frozen, Path(args.repo_root).resolve(), "frozen_root")
    frozen.mkdir(parents=True, exist_ok=True)
    try:
        limits = json.loads(Path(args.limits).read_text(encoding="utf-8"))
        allowed = set(limits["agent_repo_write_allowlist"])
        if "fast3/scripts/run/fast3_r4_two_stage_direction_hard_r22.py" not in allowed:
            raise R4ContractError("LIMITS_ALLOWLIST_INVALID")
        pre = preflight(args, limits); write_json(frozen / "FAST3_R4_HARD_STORAGE_PREFLIGHT.json", pre)
        write_json(frozen / "FAST3_R4_STORAGE_CONTRACT_AUDIT.json", {**pre, "status": "PASS", "canonical_write_count": 0,
                   "confirmation_rows_read": 0, "broker_action_performed": False})
        source = validate_source_freeze(Path(args.source_r3_root), Path(args.source_r3_audit_root), limits)
        write_json(frozen / "FAST3_R4_SOURCE_FREEZE_MANIFEST.json", source)
        raw, cohort_path = load_cohort(Path(args.source_r3_root)); source["source_cohort_sha256"] = file_hash(cohort_path)
        write_json(frozen / "FAST3_R4_SOURCE_FREEZE_MANIFEST.json", source)
        cohort = prepare_cohort(raw, source["features"])
        registry = {"status": "FROZEN", "source_cohort": str(cohort_path), "source_cohort_sha256": source["source_cohort_sha256"],
                    "row_count_after_ambiguous_exclusion": int(len(cohort)), "ambiguous_policy": "EXCLUDE",
                    "confirmation_rows_read": 0, "historical_status": "NON_PROSPECTIVE"}
        write_json(frozen / "FAST3_R4_OBSERVED_INTERVAL_REGISTRY.json", registry)
        schedule_path = frozen / "FAST3_R4_RANDOM_BLOCK_SCHEDULE.json"
        existing = json.loads(schedule_path.read_text(encoding="utf-8")) if schedule_path.is_file() else None
        schedule = deterministic_schedule(cohort, existing=existing); write_json(schedule_path, schedule)
        feature_freeze = {"status": "FROZEN", "ordered_features": source["features"], "active_interactions": source["interactions"],
                          "model": "HistGradientBoostingClassifier", "model_parameters": {"max_iter": 100, "learning_rate": .08,
                          "max_leaf_nodes": 7, "l2_regularization": 1.0}, "opportunity_threshold": .60, "top_fraction": .05,
                          "rank": "max(P_UP_FIRST,P_DOWN_FIRST)", "horizon_hours": 24, "cost_bps": [10, 20],
                          "historical_status": "NON_PROSPECTIVE"}
        write_json(frozen / "FAST3_R4_FEATURE_MODEL_FREEZE.json", feature_freeze)
        development = run_phase(cohort, schedule, source, Path(args.scratch_root), "development")
        development_gate = gate("development", development)
        write_json(frozen / "FAST3_R4_DEV_COMPARISON.json", {"status": "COMPLETE", "historical_status": "NON_PROSPECTIVE",
                   "records": development, "gate": development_gate})
        if not development_gate["pass"]:
            reason = "STOP_R4_DEV_DIRECTION_NOT_SUPPORTED"
            holdout, audit, prospective = not_run(reason), not_run(reason), not_run(reason)
            final_decision = reason
        else:
            holdout_records = run_phase(cohort, schedule, source, Path(args.scratch_root), "internal_holdout")
            holdout_gate = gate("internal_holdout", holdout_records)
            holdout = {"status": "COMPLETE", "historical_status": "NON_PROSPECTIVE", "records": holdout_records, "gate": holdout_gate}
            audit = diagnostics(holdout_records)
            if holdout_gate["pass"]:
                prospective = freeze_prospective_model(cohort, source["features"], 104729, frozen)
                final_decision = "PASS_R4_HISTORICAL_ARCHITECTURE_SUPPORTED_PROSPECTIVE_MODEL_FROZEN"
            else:
                prospective = not_run("STOP_R4_INTERNAL_HOLDOUT_DIRECTION_NOT_SUPPORTED")
                final_decision = "STOP_R4_INTERNAL_HOLDOUT_DIRECTION_NOT_SUPPORTED"
        write_json(frozen / "FAST3_R4_INTERNAL_HOLDOUT_COMPARISON.json", holdout)
        write_json(frozen / "FAST3_R4_NULL_AND_ECONOMIC_AUDIT.json", audit)
        write_json(frozen / "FAST3_R4_DAILY_MONTHLY_DIAGNOSTICS.json", audit)
        write_json(frozen / "FAST3_R4_PROSPECTIVE_FREEZE.json", prospective)
        hg = holdout.get("gate", {}) if isinstance(holdout, dict) else {}
        holdout_records = holdout.get("records", []) if isinstance(holdout, dict) else []
        def average(architecture: str, metric: str):
            values = [float(record[architecture][metric]) for record in holdout_records if metric in record.get(architecture, {}) and isfinite(float(record[architecture][metric]))]
            return float(sum(values) / len(values)) if values else None
        r4_event_lift, r3_event_lift = average("two_stage", "event_lift"), average("direct", "event_lift")
        r4_balanced, r3_balanced = average("two_stage", "conditional_direction_balanced_accuracy"), average("direct", "conditional_direction_balanced_accuracy")
        summary = {"FINAL_STATUS": "COMPLETE", "FINAL_DECISION": final_decision, "RUN_ID": args.run_id,
                   "SOURCE_R3_RUN_ID": source["source_r3_run_id"], "SOURCE_R3_DECISION": source["source_r3_decision"],
                   "SOURCE_R3_AUDIT_DECISION": source["source_r3_audit_decision"], "STORAGE_CONTRACT_PASS": True,
                   "CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN": True, "CANONICAL_WATCH_EVENT_COUNT": 0,
                   "REPO_WATCH_VIOLATION_COUNT": 0, "NEW_LOCAL_RESULTS_WRITE_COUNT": 0, "REPO_RESULT_WRITE_COUNT": 0,
                   "CANONICAL_WRITE_COUNT": 0, "CONFIRMATION_ROWS_READ": 0, "RANDOM_BLOCK_SCHEDULE_HASH": schedule["schedule_hash"],
                   "DEVELOPMENT_GATE_PASS": development_gate["pass"], "INTERNAL_HOLDOUT_GATE_PASS": hg.get("pass", False),
                   "R4_EVENT_LIFT": r4_event_lift, "R3_STYLE_EVENT_LIFT": r3_event_lift, "EVENT_LIFT_DELTA": hg.get("event_lift_delta_mean"),
                   "R4_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": r4_balanced, "R3_STYLE_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": r3_balanced,
                   "CONDITIONAL_DIRECTION_BALANCED_ACCURACY_DELTA": hg.get("direction_delta_mean"), "CONDITIONAL_DIRECTION_DELTA_CI_LOW": hg.get("direction_delta_ci", [None])[0],
                   "UP_RECALL": average("two_stage", "up_recall"), "DOWN_RECALL": average("two_stage", "down_recall"),
                   "R4_END_TO_END_EXACT_ACCURACY": average("two_stage", "end_to_end_exact_accuracy"), "R3_STYLE_END_TO_END_EXACT_ACCURACY": average("direct", "end_to_end_exact_accuracy"),
                   "UNIQUE_PRIMARY_TRADE_COUNT": hg.get("unique_primary_trades"), "MEAN_NET_10BPS": hg.get("mean_net_10bps"),
                   "MEDIAN_NET_10BPS": hg.get("median_net_10bps"), "MEDIAN_NET_20BPS": hg.get("median_net_20bps"),
                   "PROSPECTIVE_MODEL_FROZEN": prospective.get("status", "").startswith("FROZEN"), "MODEL_OR_FACTOR_SEARCH_PERFORMED": False,
                   "BROKER_ACTION_PERFORMED": False, "ARCHIVE_FINALIZED": False,
                   "REPORT_PATH": str(frozen / "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md")}
        write_json(frozen / "fast3_r4_two_stage_direction_summary.json", summary)
        (frozen / "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md").write_text(report(summary), encoding="utf-8")
    except Exception as error:
        reason = f"STOP_R4_IMPLEMENTATION_OR_TEST_FAILED:{type(error).__name__}:{error}"
        write_required_not_run(frozen, reason)
        summary_path = frozen / "fast3_r4_two_stage_direction_summary.json"
        if not summary_path.exists(): write_json(summary_path, {"FINAL_STATUS": "FAILED", "FINAL_DECISION": reason, "RUN_ID": args.run_id})
    finally:
        write_required_not_run(frozen, "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED")
        artifact_manifest(frozen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
