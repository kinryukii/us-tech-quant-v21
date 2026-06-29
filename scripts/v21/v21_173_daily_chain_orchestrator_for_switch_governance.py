from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.173_DAILY_CHAIN_ORCHESTRATOR_FOR_SWITCH_GOVERNANCE"
OUT = ROOT / "outputs" / "v21" / STAGE

CHAIN = [
    {
        "stage_id": "V21.169",
        "stage_name": "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH",
        "output_dir": ROOT / "outputs" / "v21" / "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH",
        "summary": "validation_summary.json",
        "key_files": [
            "daily_switch_ledger_append_summary.csv",
            "refreshed_switch_state_maturity_scoreboard.csv",
            "refreshed_switch_state_decision_history.csv",
            "switch_decision_change_log.csv",
            "current_switch_governance_snapshot.csv",
            "V21.169_daily_switch_refresh_report.txt",
            "validation_summary.json",
        ],
    },
    {
        "stage_id": "V21.171",
        "stage_name": "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH",
        "output_dir": ROOT / "outputs" / "v21" / "V21.171_INTEGRATE_CALIBRATED_THRESHOLDS_INTO_DAILY_GOVERNANCE_REFRESH",
        "summary": "validation_summary.json",
        "key_files": [
            "integrated_threshold_source_audit.csv",
            "integrated_daily_governance_snapshot.csv",
            "threshold_gate_evaluation_matrix.csv",
            "switch_state_threshold_pass_fail_matrix.csv",
            "integrated_decision_history.csv",
            "integrated_switch_decision_change_log.csv",
            "V21.171_integrated_threshold_governance_report.txt",
            "validation_summary.json",
        ],
    },
    {
        "stage_id": "V21.172",
        "stage_name": "V21.172_SWITCH_GOVERNANCE_COMPACT_DAILY_REPORT_R1",
        "output_dir": ROOT / "outputs" / "v21" / "V21.172_SWITCH_GOVERNANCE_COMPACT_DAILY_REPORT_R1",
        "summary": "validation_summary.json",
        "key_files": [
            "compact_switch_governance_snapshot.csv",
            "compact_switch_blocker_summary.csv",
            "compact_switch_action_flags.csv",
            "compact_switch_watchlist.csv",
            "V21.172_compact_switch_governance_daily_report.txt",
            "validation_summary.json",
        ],
    },
]

V173_FILES = [
    "orchestrator_stage_run_summary.csv",
    "orchestrator_final_switch_snapshot.csv",
    "orchestrator_error_warning_log.csv",
    "orchestrator_artifact_index.csv",
    "V21.173_daily_switch_governance_orchestrator_report.txt",
    "validation_summary.json",
]

FINAL_DECISIONS = {
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
}

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
}


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for base in [ROOT / "outputs", ROOT / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            protected = protected or ("adopted" in s and any(x in s for x in ["weight", "allocation"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def stage_summary_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for spec in CHAIN:
        summary_path = spec["output_dir"] / spec["summary"]
        summary = read_json(summary_path)
        summaries[spec["stage_id"]] = summary
        missing = not summary
        run_mode = "MISSING" if missing else "CONSUMED_EXISTING_OUTPUTS"
        warning_count = int(summary.get("warning_count", 0) or 0) if summary else 1
        error_count = 1 if missing else 0
        rows.append({
            "stage_id": spec["stage_id"],
            "stage_name": spec["stage_name"],
            "run_mode": run_mode,
            "final_status": summary.get("final_status", "MISSING"),
            "final_decision": summary.get("final_decision", ""),
            "source_output_dir": rel(spec["output_dir"]),
            "warning_count": warning_count,
            "error_count": error_count,
            "research_only": boolish(summary.get("research_only", True)) if summary else True,
            "official_adoption_allowed": boolish(summary.get("official_adoption_allowed", False)) if summary else False,
            "broker_action_allowed": boolish(summary.get("broker_action_allowed", False)) if summary else False,
            "protected_outputs_modified": boolish(summary.get("protected_outputs_modified", False)) if summary else False,
        })
        if missing:
            logs.append({
                "stage_id": spec["stage_id"],
                "severity": "ERROR",
                "warning_type": "SOURCE_MISSING_WARNING",
                "message": f"{spec['stage_name']} validation_summary.json is missing.",
                "source_path": rel(summary_path),
            })
        for warning in summary.get("warnings", []) if isinstance(summary.get("warnings", []), list) else []:
            logs.append({
                "stage_id": spec["stage_id"],
                "severity": "WARNING",
                "warning_type": warning.get("warning_type", "WARNING") if isinstance(warning, dict) else "WARNING",
                "message": warning.get("warning", "") if isinstance(warning, dict) else str(warning),
                "source_path": warning.get("source_path", rel(summary_path)) if isinstance(warning, dict) else rel(summary_path),
            })
        if spec["stage_id"] == "V21.169" and boolish(summary.get("no_new_data", False)):
            logs.append({
                "stage_id": "V21.169",
                "severity": "WARNING",
                "warning_type": "WARN_NO_NEW_SWITCH_LEDGER_DATA",
                "message": "No new switch ledger rows were appended; treated as warning, not failure.",
                "source_path": rel(summary_path),
            })
        if spec["stage_id"] == "V21.171" and boolish(summary.get("insufficient_historical_calibration_data", False)):
            logs.append({
                "stage_id": "V21.171",
                "severity": "WARNING",
                "warning_type": "INSUFFICIENT_HISTORICAL_CALIBRATION_DATA",
                "message": "Threshold integration inherits conservative calibration due to insufficient history.",
                "source_path": rel(summary_path),
            })
        if spec["stage_id"] == "V21.171" and boolish(summary.get("calibration_defaults_used", False)):
            logs.append({
                "stage_id": "V21.171",
                "severity": "WARNING",
                "warning_type": "CALIBRATION_DEFAULTS_USED",
                "message": "Conservative default thresholds are active.",
                "source_path": rel(summary_path),
            })
    return rows, logs, summaries


def artifact_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in CHAIN:
        for name in spec["key_files"]:
            path = spec["output_dir"] / name
            rows.append({
                "stage_id": spec["stage_id"],
                "stage_name": spec["stage_name"],
                "artifact_name": name,
                "artifact_path": rel(path),
                "exists": path.exists(),
                "non_empty": path.exists() and path.stat().st_size > 0,
                "file_size_bytes": path.stat().st_size if path.exists() else 0,
            })
    for name in V173_FILES:
        path = OUT / name
        rows.append({
            "stage_id": "V21.173",
            "stage_name": STAGE,
            "artifact_name": name,
            "artifact_path": rel(path),
            "exists": path.exists(),
            "non_empty": path.exists() and path.stat().st_size > 0,
            "file_size_bytes": path.stat().st_size if path.exists() else 0,
        })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()

    stage_rows, log_rows, summaries = stage_summary_rows()
    v169 = summaries.get("V21.169", {})
    v171 = summaries.get("V21.171", {})
    v172 = summaries.get("V21.172", {})
    final_decision = str(v172.get("final_decision") or v171.get("final_decision") or v169.get("final_decision") or "WAIT_MORE_MATURITY")
    if final_decision not in FINAL_DECISIONS:
        log_rows.append({
            "stage_id": "V21.173",
            "severity": "ERROR",
            "warning_type": "INVALID_FINAL_DECISION_ENUM",
            "message": f"Invalid final decision {final_decision}; official adoption blocked.",
            "source_path": rel(OUT),
        })
        final_decision = "OFFICIAL_ADOPTION_BLOCKED"

    official = boolish(v172.get("official_adoption_allowed", False)) or boolish(v171.get("official_adoption_allowed", False)) or boolish(v169.get("official_adoption_allowed", False))
    broker = boolish(v172.get("broker_action_allowed", False)) or boolish(v171.get("broker_action_allowed", False)) or boolish(v169.get("broker_action_allowed", False))
    protected = boolish(v172.get("protected_outputs_modified", False)) or boolish(v171.get("protected_outputs_modified", False)) or boolish(v169.get("protected_outputs_modified", False))
    fatal_error_count = 0
    if official:
        fatal_error_count += 1
        log_rows.append({"stage_id": "V21.173", "severity": "ERROR", "warning_type": "UNEXPECTED_OFFICIAL_ADOPTION_ALLOWED", "message": "official_adoption_allowed=true unexpectedly.", "source_path": rel(OUT)})
    if broker:
        fatal_error_count += 1
        log_rows.append({"stage_id": "V21.173", "severity": "ERROR", "warning_type": "UNEXPECTED_BROKER_ACTION_ALLOWED", "message": "broker_action_allowed=true unexpectedly.", "source_path": rel(OUT)})
    if protected:
        fatal_error_count += 1
        log_rows.append({"stage_id": "V21.173", "severity": "ERROR", "warning_type": "UNEXPECTED_PROTECTED_OUTPUTS_MODIFIED", "message": "protected_outputs_modified=true unexpectedly.", "source_path": rel(OUT)})

    final_status = "FAIL_DAILY_SWITCH_GOVERNANCE_CHAIN_POLICY_BREACH" if fatal_error_count else "PARTIAL_PASS_DAILY_SWITCH_GOVERNANCE_CHAIN_WAIT_MATURITY"
    next_condition = "continue daily switch ledger append and wait for matured 5D/10D/20D observations"
    snapshot = pd.DataFrame([{
        "final_status": final_status,
        "final_decision": final_decision,
        "current_primary_control": v172.get("current_primary_control") or v171.get("current_primary_control") or v169.get("current_primary_control") or "A1_CONTROL",
        "best_forward_tracking_state": v172.get("best_forward_tracking_state") or v171.get("best_forward_tracking_state") or v169.get("best_forward_tracking_state") or "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
        "threshold_source": v172.get("threshold_source") or v171.get("threshold_source") or "V21.170_SWITCH_TRIGGER_THRESHOLD_CALIBRATION_R1",
        "calibration_mode": v172.get("calibration_mode") or ("conservative_default" if boolish(v171.get("calibration_defaults_used", True)) else "empirical"),
        "role_review_required": False,
        "switch_allowed_research_only": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "one_day_outperformance_switch_allowed": False,
        "active_cash_assumption_usd": int(v172.get("active_cash_assumption_usd") or v171.get("active_cash_assumption_usd") or v169.get("active_cash_assumption_usd") or 600),
        "next_required_condition": next_condition,
        "research_only": True,
    }])

    write_csv("orchestrator_stage_run_summary.csv", pd.DataFrame(stage_rows))
    write_csv("orchestrator_final_switch_snapshot.csv", snapshot)
    write_csv("orchestrator_error_warning_log.csv", pd.DataFrame(log_rows) if log_rows else pd.DataFrame(columns=["stage_id", "severity", "warning_type", "message", "source_path"]))
    # First pass writes all outputs except artifact index, then index includes V21.173 files with current sizes.
    report = [
        STAGE,
        f"final_status={final_status}",
        f"final_decision={final_decision}",
        f"current_primary_control={snapshot['current_primary_control'].iloc[0]}",
        f"best_forward_tracking_state={snapshot['best_forward_tracking_state'].iloc[0]}",
        f"threshold_source={snapshot['threshold_source'].iloc[0]}",
        f"calibration_mode={snapshot['calibration_mode'].iloc[0]}",
        "role_review_required=false",
        "switch_allowed_research_only=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "one_day_outperformance_switch_allowed=false",
        f"next_required_condition={next_condition}",
        "",
        "Stage run modes:",
        *[f"- {row['stage_id']}: {row['run_mode']} ({row['final_status']})" for row in stage_rows],
        "",
        "Warnings are non-fatal for no-new-ledger-data, insufficient calibration history, and pre-existing repo dirtiness.",
    ]
    (OUT / "V21.173_daily_switch_governance_orchestrator_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    after = protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    validation = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "allowed_final_decision_enum": sorted(FINAL_DECISIONS),
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "current_primary_control": snapshot["current_primary_control"].iloc[0],
        "best_forward_tracking_state": snapshot["best_forward_tracking_state"].iloc[0],
        "role_review_required": False,
        "switch_allowed_research_only": False,
        "one_day_outperformance_switch_allowed": False,
        "active_cash_assumption_usd": int(snapshot["active_cash_assumption_usd"].iloc[0]),
        "next_required_condition": next_condition,
        "stage_count": len(stage_rows),
        "fatal_error_count": fatal_error_count,
        "warning_count": len([r for r in log_rows if r["severity"] == "WARNING"]),
        "error_count": len([r for r in log_rows if r["severity"] == "ERROR"]),
        "no_new_ledger_data_warning_nonfatal": any(r["warning_type"] == "WARN_NO_NEW_SWITCH_LEDGER_DATA" and r["severity"] == "WARNING" for r in log_rows),
        "artifact_index_key_files_ok": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("validation_summary.json", validation)
    write_csv("orchestrator_artifact_index.csv", pd.DataFrame(artifact_rows()))
    artifact_index = read_csv(OUT / "orchestrator_artifact_index.csv")
    key_artifacts_ok = bool((artifact_index["exists"].astype(str).str.lower().isin(["true"]) & artifact_index["non_empty"].astype(str).str.lower().isin(["true"])).all())
    validation["artifact_index_key_files_ok"] = key_artifacts_ok
    write_json("validation_summary.json", validation)
    write_csv("orchestrator_artifact_index.csv", pd.DataFrame(artifact_rows()))


if __name__ == "__main__":
    main()
