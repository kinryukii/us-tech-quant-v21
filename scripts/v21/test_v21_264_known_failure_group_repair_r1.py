from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.v21 import v21_264_known_failure_group_repair_r1 as module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_all_groups_repaired_summary_and_manifests(tmp_path):
    def fake_runner(group):
        return {
            "command": f"pytest {group.name}",
            "returncode": 0,
            "stdout_tail": "passed",
            "stderr_tail": "",
        }

    summary = module.run(output_root=tmp_path / "out", runner=fake_runner)
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["repaired_group_count"] == 4
    assert summary["expected_failed_file_count"] == 31
    assert summary["observed_repaired_file_count"] == 31
    assert summary["research_only"] is True
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["market_data_fetch_allowed"] is False
    assert summary["safe_to_git_add_all"] is False
    assert summary["safe_to_git_clean"] is False

    manifest = read_csv(tmp_path / "out" / "known_failure_repair_manifest.csv")
    results = read_csv(tmp_path / "out" / "known_failure_group_test_results.csv")
    assert len(manifest) == 4
    assert len(results) == 4
    assert {row["failure_group"] for row in manifest} == {group.name for group in module.GROUPS}
    assert all(row["repair_status"] == "REPAIRED_READY_FOR_COMMIT_REVIEW" for row in manifest)

    persisted = json.loads((tmp_path / "out" / "v21_264_summary.json").read_text(encoding="utf-8"))
    assert persisted["final_status"] == module.PASS_STATUS


def test_partial_repair_keeps_failed_group_blocked(tmp_path):
    def fake_runner(group):
        return {
            "command": f"pytest {group.name}",
            "returncode": 1 if group.name == "V21_196_R2_FAILED_GROUP" else 0,
            "stdout_tail": "failed" if group.name == "V21_196_R2_FAILED_GROUP" else "passed",
            "stderr_tail": "",
        }

    summary = module.run(output_root=tmp_path / "out", runner=fake_runner)
    assert summary["final_status"] == module.PARTIAL_STATUS
    assert summary["repaired_group_count"] == 3
    assert summary["failed_group_count"] == 1
    manifest = read_csv(tmp_path / "out" / "known_failure_repair_manifest.csv")
    failed = [row for row in manifest if row["failure_group"] == "V21_196_R2_FAILED_GROUP"]
    assert failed[0]["blocked_from_commit_after_repair"] == "TRUE"


def test_summary_schema_stable(tmp_path):
    summary = module.run(
        output_root=tmp_path / "out",
        runner=lambda group: {"command": "pytest", "returncode": 0, "stdout_tail": "", "stderr_tail": ""},
    )
    required = {
        "final_status",
        "final_decision",
        "latest_commit_hash_context",
        "known_failure_group_count",
        "repaired_group_count",
        "failed_group_count",
        "expected_failed_file_count",
        "observed_repaired_file_count",
        "v20_202_207_group_passed",
        "v21_194_group_passed",
        "v21_196_r2_group_passed",
        "v21_199_r2_r3_group_passed",
        "safe_to_git_add_all",
        "safe_to_git_clean",
        "research_only",
        "broker_action_allowed",
        "official_adoption_allowed",
        "market_data_fetch_allowed",
        "git_stage_allowed",
        "git_commit_allowed",
        "git_clean_allowed",
        "output_root",
    }
    assert required <= set(summary)


def test_group_counts_match_v21_263_quarantine():
    assert sum(group.quarantined_file_count for group in module.GROUPS) == 31
    assert {group.name: group.quarantined_file_count for group in module.GROUPS} == {
        "V20_202_207_FAILED_GROUP": 18,
        "V21_194_FAILED_GROUP": 4,
        "V21_196_R2_FAILED_GROUP": 3,
        "V21_199_R2_R3_FAILED_GROUP": 6,
    }
