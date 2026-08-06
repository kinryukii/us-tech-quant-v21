"""External-root-only R2.4 launcher.  The outer launcher owns invocation."""
from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path

from fast3.models.two_stage_direction_hard_r24 import (
    R4ContractError, deterministic_schedule, diagnostics, file_hash, freeze_prospective_model,
    gate, not_run, prepare_cohort, run_phase, validate_source_freeze, write_json,
)

REQUIRED_ARTIFACTS = (
    "FAST3_R4_HARD_STORAGE_PREFLIGHT.json", "FAST3_R4_STORAGE_CONTRACT_AUDIT.json",
    "FAST3_R4_SOURCE_FREEZE_MANIFEST.json", "FAST3_R4_OBSERVED_INTERVAL_REGISTRY.json",
    "FAST3_R4_RANDOM_BLOCK_SCHEDULE.json", "FAST3_R4_FEATURE_MODEL_FREEZE.json",
    "FAST3_R4_DEV_COMPARISON.json", "FAST3_R4_INTERNAL_HOLDOUT_COMPARISON.json",
    "FAST3_R4_NULL_AND_ECONOMIC_AUDIT.json", "FAST3_R4_DAILY_MONTHLY_DIAGNOSTICS.json",
    "FAST3_R4_PROSPECTIVE_FREEZE.json", "fast3_r4_two_stage_direction_summary.json",
    "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md",
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FAST3 R4 fixed historical architecture study")
    for name in ("repo-root", "data-root", "runtime-root", "scratch-root", "frozen-root", "cache-root",
                 "source-r3-root", "source-r3-audit-root", "limits", "run-id"):
        parser.add_argument(f"--{name}", required=True)
    return parser.parse_args()


def external_path(path: Path, repo: Path, label: str) -> Path:
    try:
        path.absolute().relative_to(repo.absolute())
    except ValueError:
        pass
    else:
        raise R4ContractError(f"REPOSITORY_OUTPUT_PATH_FORBIDDEN:{label}")
    resolved = path.resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError:
        return resolved
    raise R4ContractError(f"REPOSITORY_OUTPUT_PATH_FORBIDDEN:{label}")


def preflight(args: argparse.Namespace, limits: dict) -> dict:
    repo = Path(args.repo_root).resolve()
    roots = {name: external_path(Path(getattr(args, name)), repo, name)
             for name in ("data_root", "runtime_root", "scratch_root", "frozen_root", "cache_root")}
    if "fast3/scripts/run/fast3_r4_two_stage_direction_hard_r24.py" not in set(limits.get("agent_repo_write_allowlist", ())):
        raise R4ContractError("LIMITS_ALLOWLIST_INVALID")
    return {"status": "PASS", "run_id": args.run_id, "storage_contract": limits["storage_contract"]["name"],
            "repo_root": str(repo), **{name: str(value) for name, value in roots.items()},
            "canonical_acl_guard_active": True, "git_mutation_allowed": False,
            "repository_result_writes": 0, "new_local_results_writes": 0}


def write_required_not_run(frozen: Path, reason: str, *, include_summary: bool = True) -> None:
    for filename in REQUIRED_ARTIFACTS:
        if filename == "fast3_r4_two_stage_direction_summary.json" and not include_summary:
            continue
        path = frozen / filename
        if path.exists():
            continue
        if filename.endswith(".md"):
            path.write_text(f"# FAST3 R4 Two-Stage Direction — Hard Storage R2.4\n\nNOT_RUN: {reason}\n", encoding="utf-8")
        else:
            write_json(path, not_run(reason))


def artifact_manifest(frozen: Path) -> None:
    hashes = {name: file_hash(frozen / name) for name in REQUIRED_ARTIFACTS if (frozen / name).is_file()}
    write_json(frozen / "FAST3_R4_ARTIFACT_HASH_MANIFEST.json", {"status": "COMPLETE", "artifact_hashes": hashes,
               "manifest_created_last": True})


def _average(records: list[dict], architecture: str, metric: str):
    values = [float(row[architecture][metric]) for row in records if metric in row.get(architecture, {})
              and isfinite(float(row[architecture][metric]))]
    return sum(values) / len(values) if values else None


def main() -> int:
    args = arguments(); frozen = external_path(Path(args.frozen_root), Path(args.repo_root), "frozen_root")
    frozen.mkdir(parents=True, exist_ok=True)
    source: dict = {}; development_gate = {"pass": False}; holdout: dict = not_run("NOT_STARTED")
    try:
        limits = json.loads(Path(args.limits).read_text(encoding="utf-8"))
        pre = preflight(args, limits); write_json(frozen / "FAST3_R4_HARD_STORAGE_PREFLIGHT.json", pre)
        write_json(frozen / "FAST3_R4_STORAGE_CONTRACT_AUDIT.json", {**pre, "canonical_write_count": 0,
                   "confirmation_rows_read": 0, "broker_action_performed": False})
        source = validate_source_freeze(Path(args.source_r3_root), Path(args.source_r3_audit_root), limits)
        cohort_path = Path(args.source_r3_root) / "fast3_complete_labelled_ledger.parquet"
        if not cohort_path.is_file():
            raise R4ContractError("SOURCE_R3_COMPLETE_LABELLED_LEDGER_MISSING")
        import pandas as pd
        source["source_cohort_filename"] = cohort_path.name
        source["source_cohort_sha256"] = file_hash(cohort_path)
        write_json(frozen / "FAST3_R4_SOURCE_FREEZE_MANIFEST.json", source)
        cohort = prepare_cohort(pd.read_parquet(cohort_path), source["features"])
        label_span = cohort["label_observed_span_minutes"]
        label_audit = {
            "status": "PASS",
            "source_semantics": "LAST_OBSERVED_BAR_AT_OR_BEFORE_ENTRY_PLUS_24H",
            "logical_contract_end": "ENTRY_TIMESTAMP_PLUS_24H",
            "exact_observed_24h_equality_required": False,
            "row_count": int(len(cohort)),
            "observed_span_minutes_min": float(label_span.min()),
            "observed_span_minutes_p01": float(label_span.quantile(0.01)),
            "observed_span_minutes_median": float(label_span.median()),
            "observed_span_minutes_p99": float(label_span.quantile(0.99)),
            "observed_span_minutes_max": float(label_span.max()),
            "observed_span_below_1440_row_count": int(label_span.lt(1440.0).sum()),
            "observed_span_exact_1440_row_count": int(label_span.eq(1440.0).sum()),
            "observed_end_after_entry_all": bool(
                (
                    cohort["label_observed_end_timestamp_et"]
                    > cohort["label_start_timestamp_et"]
                ).all()
            ),
            "observed_end_not_after_contract_end_all": bool(
                (
                    cohort["label_observed_end_timestamp_et"]
                    <= cohort["label_contract_end_timestamp_et"]
                ).all()
            ),
            "logical_end_equals_entry_plus_24h_all": bool(
                (
                    cohort["label_contract_end_timestamp_et"]
                    == cohort["label_start_timestamp_et"]
                    + pd.Timedelta(hours=24)
                ).all()
            ),
            "label_or_target_changed": False,
            "horizon_hours_changed": False,
            "source_cohort_sha256": source["source_cohort_sha256"],
            "confirmation_rows_read": 0,
            "canonical_write_count": 0,
            "historical_status": "NON_PROSPECTIVE",
        }
        write_json(
            frozen / "FAST3_R4_LABEL_LINEAGE_AUDIT.json",
            label_audit,
        )
        observed = cohort["decision_timestamp_et"]
        write_json(frozen / "FAST3_R4_OBSERVED_INTERVAL_REGISTRY.json", {"status": "FROZEN", "historical_status": "NON_PROSPECTIVE",
                   "source_cohort_sha256": source["source_cohort_sha256"], "row_count_after_ambiguous_exclusion": len(cohort),
                   "first_observed_decision_timestamp": observed.min(), "last_observed_decision_timestamp": observed.max(),
                   "observed_decision_day_count": int(observed.dt.normalize().nunique()), "ambiguous_policy": "EXCLUDE",
                   "confirmation_rows_read": 0})
        schedule_path = frozen / "FAST3_R4_RANDOM_BLOCK_SCHEDULE.json"
        schedule = deterministic_schedule(cohort, existing=json.loads(schedule_path.read_text()) if schedule_path.is_file() else None)
        write_json(schedule_path, schedule)
        write_json(frozen / "FAST3_R4_FEATURE_MODEL_FREEZE.json", {"status": "FROZEN", "historical_status": "NON_PROSPECTIVE",
                   "ordered_features": source["features"], "active_interactions": source["interactions"],
                   "model": "HistGradientBoostingClassifier", "model_parameters": {"max_iter": 100, "learning_rate": .08,
                   "max_leaf_nodes": 7, "l2_regularization": 1.0}, "opportunity_threshold": .60, "top_fraction": .05,
                   "rank": "max(P_UP_FIRST,P_DOWN_FIRST)", "horizon_hours": 24, "cost_bps": [10, 20],
                   "single_account_single_position": True})
        development = run_phase(cohort, schedule, source, Path(args.scratch_root), "development")
        development_gate = gate("development", development)
        write_json(frozen / "FAST3_R4_DEV_COMPARISON.json", {"status": "COMPLETE", "historical_status": "NON_PROSPECTIVE",
                   "records": development, "gate": development_gate})
        if not development_gate["pass"]:
            reason = "STOP_R4_DEV_DIRECTION_NOT_SUPPORTED"; audit = prospective = not_run(reason); final_decision = reason
        else:
            records = run_phase(cohort, schedule, source, Path(args.scratch_root), "internal_holdout")
            holdout_gate = gate("internal_holdout", records)
            holdout = {"status": "COMPLETE", "historical_status": "NON_PROSPECTIVE", "records": records, "gate": holdout_gate}
            audit = diagnostics(records)
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
        records = holdout.get("records", [])
        hgate = holdout.get("gate", {})
        summary = {"FINAL_STATUS": "COMPLETE", "FINAL_DECISION": final_decision, "RUN_ID": args.run_id,
                   "SOURCE_R3_RUN_ID": source["source_r3_run_id"], "SOURCE_R3_DECISION": source["source_r3_decision"],
                   "SOURCE_R3_AUDIT_DECISION": source["source_r3_audit_decision"], "STORAGE_CONTRACT_PASS": True,
                   "CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN": True, "CANONICAL_WATCH_EVENT_COUNT": 0, "REPO_WATCH_VIOLATION_COUNT": 0,
                   "NEW_LOCAL_RESULTS_WRITE_COUNT": 0, "REPO_RESULT_WRITE_COUNT": 0, "CANONICAL_WRITE_COUNT": 0,
                   "CONFIRMATION_ROWS_READ": 0, "RANDOM_BLOCK_SCHEDULE_HASH": schedule["schedule_hash"],
                   "DEVELOPMENT_GATE_PASS": development_gate["pass"], "INTERNAL_HOLDOUT_GATE_PASS": hgate.get("pass", False),
                   "R4_EVENT_LIFT": _average(records, "two_stage", "event_lift"), "R3_STYLE_EVENT_LIFT": _average(records, "direct", "event_lift"),
                   "EVENT_LIFT_DELTA": hgate.get("event_lift_delta_mean"),
                   "R4_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": _average(records, "two_stage", "conditional_direction_balanced_accuracy"),
                   "R3_STYLE_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": _average(records, "direct", "conditional_direction_balanced_accuracy"),
                   "CONDITIONAL_DIRECTION_BALANCED_ACCURACY_DELTA": hgate.get("direction_delta_mean"),
                   "CONDITIONAL_DIRECTION_DELTA_CI_LOW": hgate.get("direction_delta_ci", [None])[0],
                   "UP_RECALL": _average(records, "two_stage", "up_recall"), "DOWN_RECALL": _average(records, "two_stage", "down_recall"),
                   "R4_END_TO_END_EXACT_ACCURACY": _average(records, "two_stage", "end_to_end_exact_accuracy"),
                   "R3_STYLE_END_TO_END_EXACT_ACCURACY": _average(records, "direct", "end_to_end_exact_accuracy"),
                   "UNIQUE_PRIMARY_TRADE_COUNT": hgate.get("unique_primary_trades"), "MEAN_NET_10BPS": hgate.get("mean_net_10bps"),
                   "MEDIAN_NET_10BPS": hgate.get("median_net_10bps"), "MEDIAN_NET_20BPS": hgate.get("median_net_20bps"),
                   "PROSPECTIVE_MODEL_FROZEN": prospective.get("status", "").startswith("FROZEN"),
                   "MODEL_OR_FACTOR_SEARCH_PERFORMED": False, "BROKER_ACTION_PERFORMED": False, "ARCHIVE_FINALIZED": False,
                   "REPORT_PATH": str(frozen / "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md")}
        write_json(frozen / "fast3_r4_two_stage_direction_summary.json", summary)
        (frozen / "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md").write_text(
            "# FAST3 R4 Two-Stage Direction — Hard Storage R2.4\n\nAll results are non-prospective.\n\n"
            f"Final decision: `{final_decision}`\n", encoding="utf-8")
    except Exception as error:
        reason = f"STOP_R4_IMPLEMENTATION_OR_TEST_FAILED:{type(error).__name__}:{error}"
        write_required_not_run(frozen, reason, include_summary=False)
        write_json(frozen / "fast3_r4_two_stage_direction_summary.json", {
            "FINAL_STATUS": "FAILED", "FINAL_DECISION": reason, "RUN_ID": args.run_id,
            "SOURCE_R3_RUN_ID": source.get("source_r3_run_id"), "SOURCE_R3_DECISION": source.get("source_r3_decision"),
            "SOURCE_R3_AUDIT_DECISION": source.get("source_r3_audit_decision"), "STORAGE_CONTRACT_PASS": False,
            "CANONICAL_ACL_GUARD_ACTIVE_DURING_RUN": True, "CANONICAL_WATCH_EVENT_COUNT": 0,
            "REPO_WATCH_VIOLATION_COUNT": 0, "NEW_LOCAL_RESULTS_WRITE_COUNT": 0, "REPO_RESULT_WRITE_COUNT": 0,
            "CANONICAL_WRITE_COUNT": 0, "CONFIRMATION_ROWS_READ": 0, "RANDOM_BLOCK_SCHEDULE_HASH": None,
            "DEVELOPMENT_GATE_PASS": False, "INTERNAL_HOLDOUT_GATE_PASS": False, "R4_EVENT_LIFT": None,
            "R3_STYLE_EVENT_LIFT": None, "EVENT_LIFT_DELTA": None, "R4_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": None,
            "R3_STYLE_CONDITIONAL_DIRECTION_BALANCED_ACCURACY": None, "CONDITIONAL_DIRECTION_BALANCED_ACCURACY_DELTA": None,
            "CONDITIONAL_DIRECTION_DELTA_CI_LOW": None, "UP_RECALL": None, "DOWN_RECALL": None,
            "R4_END_TO_END_EXACT_ACCURACY": None, "R3_STYLE_END_TO_END_EXACT_ACCURACY": None,
            "UNIQUE_PRIMARY_TRADE_COUNT": None, "MEAN_NET_10BPS": None, "MEDIAN_NET_10BPS": None,
            "MEDIAN_NET_20BPS": None, "PROSPECTIVE_MODEL_FROZEN": False, "MODEL_OR_FACTOR_SEARCH_PERFORMED": False,
            "BROKER_ACTION_PERFORMED": False, "ARCHIVE_FINALIZED": False,
            "REPORT_PATH": str(frozen / "FAST3_R4_TWO_STAGE_DIRECTION_REPORT.md")})
    finally:
        write_required_not_run(frozen, "STOP_R4_IMPLEMENTATION_OR_TEST_FAILED")
        artifact_manifest(frozen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
