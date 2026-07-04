#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

STAGE = "V21.263_REMAINING_UNTRACKED_FAILURE_QUARANTINE_AUDIT_R1"
OUT_REL = Path("outputs/v21") / STAGE
EXPECTED_COMMIT = "1979b4751ff60a38c690ed21b2735d9e3850fecc"

FAILURE_REASONS = {
    "V20_202_207_FAILED_GROUP": "Dependent V20 random-weight backtest CSV artifacts exist but contain no effective data rows; V20.206 also hit StopIteration.",
    "V21_194_FAILED_GROUP": "Broad-date gate helper/integration depends on missing latest_broad_date_gate.json and missing V20 canonical artifact in current compact repo.",
    "V21_196_R2_FAILED_GROUP": "Vendor export pack/raw CSV normalizer tests depend on missing V20 canonical fixture.",
    "V21_199_R2_R3_FAILED_GROUP": "Completed-date gate behavior diverges from tests and must be reconciled with R4/R4A behavior before commit.",
}

EXPECTED_GROUPS: dict[str, set[str]] = {
    "V20_202_207_FAILED_GROUP": {
        f"scripts/v20/{prefix}_v20_{n}_{suffix}"
        for n, suffix in [
            ("202", "random_weight_effectiveness_aggregator"),
            ("203", "10d_local_edge_and_downside_attribution"),
            ("204", "10d_local_edge_robustness_expansion"),
            ("205", "10d_selected_etf_cluster_dependency_attribution"),
            ("206", "10d_spy_conditional_overlay_validation"),
            ("207", "spy_conditional_observation_integration_plan"),
        ]
        for prefix, ext in [("run", ".ps1"), ("test", ".py"), ("", ".py")]
    },
    "V21_194_FAILED_GROUP": {
        "scripts/v21/run_v21_194_integrate_broad_date_gate_into_daily_chain.ps1",
        "scripts/v21/test_v21_194_integrate_broad_date_gate_into_daily_chain.py",
        "scripts/v21/v21_194_broad_date_gate_utils.py",
        "scripts/v21/v21_194_integrate_broad_date_gate_into_daily_chain.py",
    },
    "V21_196_R2_FAILED_GROUP": {
        "scripts/v21/run_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.ps1",
        "scripts/v21/test_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py",
        "scripts/v21/v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py",
    },
    "V21_199_R2_R3_FAILED_GROUP": {
        "scripts/v21/run_v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate.ps1",
        "scripts/v21/run_v21_199_r3_fetch_loop_trace_and_provider_response_audit.ps1",
        "scripts/v21/test_v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate.py",
        "scripts/v21/test_v21_199_r3_fetch_loop_trace_and_provider_response_audit.py",
        "scripts/v21/v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate.py",
        "scripts/v21/v21_199_r3_fetch_loop_trace_and_provider_response_audit.py",
    },
}

# Fix the V20 generated names for non-run/test scripts.
EXPECTED_GROUPS["V20_202_207_FAILED_GROUP"] = {
    p.replace("scripts/v20/_v20_", "scripts/v20/v20_")
    .replace("scripts/v20/run_v20_", "scripts/v20/run_v20_")
    .replace("scripts/v20/test_v20_", "scripts/v20/test_v20_")
    + (".ps1" if p.startswith("scripts/v20/run_") else ".py")
    for p in EXPECTED_GROUPS["V20_202_207_FAILED_GROUP"]
}

EXPECTED_PATH_TO_GROUP = {path: group for group, paths in EXPECTED_GROUPS.items() for path in paths}
EXPECTED_FAILED_FILE_COUNT = len(EXPECTED_PATH_TO_GROUP)


def run_cmd(repo: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=str(repo), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def is_self_artifact(path: str) -> bool:
    return "v21_263_remaining_untracked_failure_quarantine_audit_r1" in path.lower() or "V21.263_REMAINING_UNTRACKED_FAILURE_QUARANTINE_AUDIT_R1" in path


def parse_status_short(raw: str) -> list[dict[str, str]]:
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        xy = line[:2]
        path = line[3:] if len(line) > 3 else ""
        if xy == "??" and not is_self_artifact(path):
            rows.append({"xy_status": xy, "path": path})
    return rows


def classify_path(path: str) -> dict[str, Any]:
    group = EXPECTED_PATH_TO_GROUP.get(path, "UNEXPECTED_UNTRACKED")
    expected = group != "UNEXPECTED_UNTRACKED"
    return {
        "path": path,
        "failure_group": group,
        "is_expected_known_failure": expected,
        "blocked_from_commit": expected,
        "recommended_action": "KEEP_UNTRACKED_DO_NOT_COMMIT_UNTIL_FAILURE_FIXED" if expected else "USER_REVIEW_REQUIRED_UNEXPECTED_UNTRACKED",
        "failure_reason": FAILURE_REASONS.get(group, "Unexpected untracked file outside known failed groups."),
        "research_only": True,
    }


def group_summary(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for group, expected_paths in EXPECTED_GROUPS.items():
        observed = [r for r in manifest if r["failure_group"] == group]
        rows.append({
            "failure_group": group,
            "expected_count": len(expected_paths),
            "observed_count": len(observed),
            "missing_expected_count": len(expected_paths) - len(observed),
            "blocked_from_commit_count": sum(1 for r in observed if r["blocked_from_commit"]),
            "failure_reason": FAILURE_REASONS[group],
        })
    unexpected = [r for r in manifest if r["failure_group"] == "UNEXPECTED_UNTRACKED"]
    rows.append({
        "failure_group": "UNEXPECTED_UNTRACKED",
        "expected_count": 0,
        "observed_count": len(unexpected),
        "missing_expected_count": 0,
        "blocked_from_commit_count": 0,
        "failure_reason": "Unexpected untracked files require user review.",
    })
    return rows


def build_summary(latest_hash: str, manifest: list[dict[str, Any]]) -> dict[str, Any]:
    unexpected = sum(1 for r in manifest if not r["is_expected_known_failure"])
    observed = sum(1 for r in manifest if r["is_expected_known_failure"])
    status = "PASS_V21_263_REMAINING_FAILURES_QUARANTINED" if unexpected == 0 else "WARN_V21_263_UNEXPECTED_UNTRACKED_REMAIN"
    return {
        "final_status": status,
        "final_decision": "REMAINING_UNTRACKED_KNOWN_FAILURES_BLOCKED_FROM_COMMIT" if unexpected == 0 else "UNEXPECTED_UNTRACKED_REQUIRES_REVIEW",
        "latest_commit_hash": latest_hash,
        "dirty_total_count": len(manifest),
        "remaining_untracked_count": len(manifest),
        "expected_failed_file_count": EXPECTED_FAILED_FILE_COUNT,
        "observed_failed_file_count": observed,
        "unexpected_untracked_count": unexpected,
        "blocked_from_commit_count": sum(1 for r in manifest if r["blocked_from_commit"]),
        "safe_to_git_add_all": False,
        "safe_to_git_clean": False,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_allowed": False,
    }


def write_outputs(repo: Path, summary: dict[str, Any], manifest: list[dict[str, Any]], groups: list[dict[str, Any]]) -> None:
    out = repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "v21_263_summary.json", summary)
    write_csv(out / "remaining_untracked_failure_quarantine_manifest.csv", manifest, ["path", "failure_group", "is_expected_known_failure", "blocked_from_commit", "recommended_action", "failure_reason", "research_only"])
    write_csv(out / "remaining_untracked_group_summary.csv", groups, ["failure_group", "expected_count", "observed_count", "missing_expected_count", "blocked_from_commit_count", "failure_reason"])
    report = "\n".join([
        STAGE,
        f"final_status={summary['final_status']}",
        f"latest_commit_hash={summary['latest_commit_hash']}",
        f"remaining_untracked_count={summary['remaining_untracked_count']}",
        f"unexpected_untracked_count={summary['unexpected_untracked_count']}",
        "No git add, commit, clean, restore, delete, move, market data fetch, broker action, or official adoption was performed.",
    ]) + "\n"
    (out / "v21_263_remaining_untracked_failure_quarantine_report.txt").write_text(report, encoding="utf-8")


def run(repo: Path, command_runner: Callable[[Path, list[str]], tuple[int, str, str]] = run_cmd) -> dict[str, Any]:
    try:
        code, raw, err = command_runner(repo, ["git", "status", "--short"])
        c2, commit_raw, _ = command_runner(repo, ["git", "log", "-1", "--pretty=format:%H"])
        if code != 0:
            raise RuntimeError(err or "git status failed")
        latest_hash = commit_raw.strip()
        parsed = parse_status_short(raw)
        manifest = [classify_path(r["path"]) for r in parsed]
        summary = build_summary(latest_hash, manifest)
        write_outputs(repo, summary, manifest, group_summary(manifest))
        return summary
    except Exception as exc:
        summary = {
            "final_status": "FAIL_V21_263_GIT_OR_MANIFEST_ERROR",
            "final_decision": f"GIT_OR_MANIFEST_ERROR: {exc}",
            "latest_commit_hash": "",
            "dirty_total_count": 0,
            "remaining_untracked_count": 0,
            "expected_failed_file_count": EXPECTED_FAILED_FILE_COUNT,
            "observed_failed_file_count": 0,
            "unexpected_untracked_count": 0,
            "blocked_from_commit_count": 0,
            "safe_to_git_add_all": False,
            "safe_to_git_clean": False,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "market_data_fetch_allowed": False,
        }
        write_outputs(repo, summary, [], group_summary([]))
        return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--dry-run", action="store_true", default=True)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve())
    for k in ["final_status", "final_decision", "latest_commit_hash", "dirty_total_count", "remaining_untracked_count", "expected_failed_file_count", "observed_failed_file_count", "unexpected_untracked_count", "blocked_from_commit_count", "safe_to_git_add_all", "safe_to_git_clean", "research_only", "broker_action_allowed", "official_adoption_allowed", "market_data_fetch_allowed"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
