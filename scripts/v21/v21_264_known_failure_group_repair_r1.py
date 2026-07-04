#!/usr/bin/env python
"""V21.264 known failure group repair verifier.

This stage validates the previously quarantined failure groups after targeted
test/code repair. It does not stage, commit, delete, restore, move, fetch data,
or touch protected outputs.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


VERSION = "V21.264_KNOWN_FAILURE_GROUP_REPAIR_R1"
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "outputs" / "v21" / VERSION

PASS_STATUS = "PASS_V21_264_KNOWN_FAILURE_GROUPS_REPAIRED"
PARTIAL_STATUS = "PARTIAL_PASS_V21_264_SOME_GROUPS_REPAIRED_REMAINDER_BLOCKED"
FAIL_STATUS = "FAIL_V21_264_REPAIR_VALIDATION_FAILED"


@dataclass(frozen=True)
class RepairGroup:
    name: str
    quarantined_file_count: int
    test_paths: tuple[str, ...]


GROUPS: tuple[RepairGroup, ...] = (
    RepairGroup(
        "V20_202_207_FAILED_GROUP",
        18,
        (
            "scripts/v20/test_v20_202_random_weight_effectiveness_aggregator.py",
            "scripts/v20/test_v20_203_10d_local_edge_and_downside_attribution.py",
            "scripts/v20/test_v20_204_10d_local_edge_robustness_expansion.py",
            "scripts/v20/test_v20_205_10d_selected_etf_cluster_dependency_attribution.py",
            "scripts/v20/test_v20_206_10d_spy_conditional_overlay_validation.py",
            "scripts/v20/test_v20_207_spy_conditional_observation_integration_plan.py",
        ),
    ),
    RepairGroup(
        "V21_194_FAILED_GROUP",
        4,
        ("scripts/v21/test_v21_194_integrate_broad_date_gate_into_daily_chain.py",),
    ),
    RepairGroup(
        "V21_196_R2_FAILED_GROUP",
        3,
        ("scripts/v21/test_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py",),
    ),
    RepairGroup(
        "V21_199_R2_R3_FAILED_GROUP",
        6,
        (
            "scripts/v21/test_v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate.py",
            "scripts/v21/test_v21_199_r3_fetch_loop_trace_and_provider_response_audit.py",
        ),
    ),
)


def tail(text: str, max_chars: int = 4000) -> str:
    text = text or ""
    return text[-max_chars:]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def run_pytest(group: RepairGroup) -> dict[str, object]:
    command = [sys.executable, "-m", "pytest", "-q", *group.test_paths]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "command": " ".join(command),
        "returncode": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    }


def build_manifest_rows(results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in results:
        repaired = bool(result["returncode"] == 0)
        rows.append(
            {
                "failure_group": result["failure_group"],
                "quarantined_file_count": result["quarantined_file_count"],
                "test_file_count": result["test_file_count"],
                "repair_status": "REPAIRED_READY_FOR_COMMIT_REVIEW" if repaired else "REPAIR_VALIDATION_FAILED",
                "blocked_from_commit_after_repair": "FALSE" if repaired else "TRUE",
                "research_only": "TRUE",
                "broker_action_allowed": "FALSE",
                "official_adoption_allowed": "FALSE",
                "market_data_fetch_allowed": "FALSE",
                "reason": "Group pytest subset passed." if repaired else "Group pytest subset failed; keep blocked from commit.",
            }
        )
    return rows


def run(
    output_root: Path = OUTPUT_ROOT,
    runner: Callable[[RepairGroup], dict[str, object]] = run_pytest,
) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    test_rows: list[dict[str, object]] = []
    results: list[dict[str, object]] = []

    for group in GROUPS:
        outcome = runner(group)
        row = {
            "failure_group": group.name,
            "quarantined_file_count": group.quarantined_file_count,
            "test_file_count": len(group.test_paths),
            "test_paths": ";".join(group.test_paths),
            "pytest_command": outcome.get("command", ""),
            "returncode": int(outcome.get("returncode", 1)),
            "pytest_passed": bool(int(outcome.get("returncode", 1)) == 0),
            "stdout_tail": outcome.get("stdout_tail", ""),
            "stderr_tail": outcome.get("stderr_tail", ""),
        }
        test_rows.append(row)
        results.append(row)

    manifest_rows = build_manifest_rows(results)
    repaired_count = sum(1 for row in test_rows if row["pytest_passed"])
    failed_count = len(test_rows) - repaired_count
    observed_file_count = sum(group.quarantined_file_count for group in GROUPS)

    if failed_count == 0:
        final_status = PASS_STATUS
        final_decision = "KNOWN_FAILURE_GROUPS_REPAIRED_READY_FOR_TARGETED_COMMIT_REVIEW"
    elif repaired_count:
        final_status = PARTIAL_STATUS
        final_decision = "SOME_KNOWN_FAILURE_GROUPS_REPAIRED_REMAINDER_BLOCKED"
    else:
        final_status = FAIL_STATUS
        final_decision = "KNOWN_FAILURE_GROUP_REPAIR_VALIDATION_FAILED"

    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "latest_commit_hash_context": "0b10aaf74067889023761728feb56918132d1b33",
        "known_failure_group_count": len(GROUPS),
        "repaired_group_count": repaired_count,
        "failed_group_count": failed_count,
        "expected_failed_file_count": observed_file_count,
        "observed_repaired_file_count": observed_file_count if failed_count == 0 else sum(
            int(row["quarantined_file_count"]) for row in test_rows if row["pytest_passed"]
        ),
        "v20_202_207_group_passed": any(row["failure_group"] == "V20_202_207_FAILED_GROUP" and row["pytest_passed"] for row in test_rows),
        "v21_194_group_passed": any(row["failure_group"] == "V21_194_FAILED_GROUP" and row["pytest_passed"] for row in test_rows),
        "v21_196_r2_group_passed": any(row["failure_group"] == "V21_196_R2_FAILED_GROUP" and row["pytest_passed"] for row in test_rows),
        "v21_199_r2_r3_group_passed": any(row["failure_group"] == "V21_199_R2_R3_FAILED_GROUP" and row["pytest_passed"] for row in test_rows),
        "safe_to_git_add_all": False,
        "safe_to_git_clean": False,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_allowed": False,
        "git_stage_allowed": False,
        "git_commit_allowed": False,
        "git_clean_allowed": False,
        "output_root": str(output_root),
    }

    write_csv(
        output_root / "known_failure_repair_manifest.csv",
        [
            "failure_group",
            "quarantined_file_count",
            "test_file_count",
            "repair_status",
            "blocked_from_commit_after_repair",
            "research_only",
            "broker_action_allowed",
            "official_adoption_allowed",
            "market_data_fetch_allowed",
            "reason",
        ],
        manifest_rows,
    )
    write_csv(
        output_root / "known_failure_group_test_results.csv",
        [
            "failure_group",
            "quarantined_file_count",
            "test_file_count",
            "test_paths",
            "pytest_command",
            "returncode",
            "pytest_passed",
            "stdout_tail",
            "stderr_tail",
        ],
        test_rows,
    )
    (output_root / "v21_264_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_root / "v21_264_known_failure_group_repair_report.txt").write_text(
        "\n".join(
            [
                "V21.264 Known Failure Group Repair",
                f"final_status={final_status}",
                f"final_decision={final_decision}",
                f"repaired_group_count={repaired_count}",
                f"failed_group_count={failed_count}",
                "No git add, commit, clean, restore, delete, provider fetch, broker action, or official adoption was performed.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    summary = run()
    for key in [
        "final_status",
        "final_decision",
        "known_failure_group_count",
        "repaired_group_count",
        "failed_group_count",
        "expected_failed_file_count",
        "observed_repaired_file_count",
        "research_only",
        "broker_action_allowed",
        "official_adoption_allowed",
        "market_data_fetch_allowed",
        "output_root",
    ]:
        print(f"{key}={summary[key]}")
    return 0 if summary["final_status"] in {PASS_STATUS, PARTIAL_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
