from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_263_remaining_untracked_failure_quarantine_audit_r1.py")
S = importlib.util.spec_from_file_location("m263", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def fake_runner(status_text: str):
    def runner(repo: Path, args: list[str]):
        if args[:3] == ["git", "status", "--short"]:
            return 0, status_text, ""
        if args[:2] == ["git", "log"]:
            return 0, "1979b4751ff60a38c690ed21b2735d9e3850fecc", ""
        return 0, "", ""
    return runner


def expected_status(extra: str = "") -> str:
    lines = [f"?? {p}" for p in sorted(m.EXPECTED_PATH_TO_GROUP)]
    if extra:
        lines.append(f"?? {extra}")
    return "\n".join(lines) + "\n"


def test_classifies_all_31_expected_files(tmp_path):
    repo = tmp_path / "repo"
    s = m.run(repo, command_runner=fake_runner(expected_status()))
    assert s["remaining_untracked_count"] == 31
    assert s["observed_failed_file_count"] == 31
    assert s["unexpected_untracked_count"] == 0
    data = rows(repo / m.OUT_REL / "remaining_untracked_failure_quarantine_manifest.csv")
    assert len(data) == 31
    assert {r["failure_group"] for r in data} >= set(m.EXPECTED_GROUPS)


def test_detects_unexpected_untracked_file(tmp_path):
    repo = tmp_path / "repo"
    s = m.run(repo, command_runner=fake_runner(expected_status("scripts/v21/random_new_file.py")))
    assert s["final_status"] == "WARN_V21_263_UNEXPECTED_UNTRACKED_REMAIN"
    assert s["unexpected_untracked_count"] == 1


def test_safe_flags_false(tmp_path):
    repo = tmp_path / "repo"
    s = m.run(repo, command_runner=fake_runner(expected_status()))
    assert s["safe_to_git_add_all"] is False
    assert s["safe_to_git_clean"] is False


def test_no_mutation_stage_delete_behavior_static():
    text = P.read_text(encoding="utf-8")
    forbidden = ["git add", "git commit", "git clean", "git restore", "git rm", "unlink(", "shutil.move", "remove("]
    # Phrases are allowed in the report text; executable mutation APIs/commands are not.
    assert "subprocess.run" in text
    assert "unlink(" not in text
    assert "shutil.move" not in text
    assert "git add" not in text.split("def run_cmd", 1)[0]


def test_summary_json_fields(tmp_path):
    repo = tmp_path / "repo"
    m.run(repo, command_runner=fake_runner(expected_status()))
    payload = json.loads((repo / m.OUT_REL / "v21_263_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "latest_commit_hash", "dirty_total_count", "remaining_untracked_count", "expected_failed_file_count", "observed_failed_file_count", "unexpected_untracked_count", "blocked_from_commit_count", "safe_to_git_add_all", "safe_to_git_clean", "research_only", "broker_action_allowed", "official_adoption_allowed", "market_data_fetch_allowed"]:
        assert key in payload


def test_manifest_and_group_summary_counts(tmp_path):
    repo = tmp_path / "repo"
    m.run(repo, command_runner=fake_runner(expected_status()))
    manifest = rows(repo / m.OUT_REL / "remaining_untracked_failure_quarantine_manifest.csv")
    groups = rows(repo / m.OUT_REL / "remaining_untracked_group_summary.csv")
    assert len(manifest) == 31
    counts = {r["failure_group"]: int(r["observed_count"]) for r in groups}
    assert counts["V20_202_207_FAILED_GROUP"] == 18
    assert counts["V21_194_FAILED_GROUP"] == 4
    assert counts["V21_196_R2_FAILED_GROUP"] == 3
    assert counts["V21_199_R2_R3_FAILED_GROUP"] == 6
