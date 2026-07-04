from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
from pathlib import Path

P = Path(__file__).with_name("v21_262_git_worktree_dirty_state_triage_r1.py")
S = importlib.util.spec_from_file_location("m262", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def make(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def fake_runner(status_text: str):
    def runner(repo: Path, args: list[str]):
        joined = " ".join(args)
        if "status --porcelain" in joined:
            return 0, status_text, ""
        if "log -1" in joined:
            return 0, "a4af37343d8def1eb248597e04095f0a3a80479e\tAdd V21.260 retention enforcement and V21.261 daily wiring", ""
        if "branch --show-current" in joined:
            return 0, "main\n", ""
        if "status -sb" in joined:
            return 0, "## main...origin/main\n", ""
        return 0, "", ""
    return runner


def test_parse_deleted_tracked_file(tmp_path):
    repo = tmp_path / "repo"
    s = m.run(repo, command_runner=fake_runner(" D docs/V20_CURRENT_STATUS.md\n"))
    data = rows(repo / m.OUT_REL / "dirty_file_triage_manifest.csv")
    assert data[0]["status_family"] == "DELETED"
    assert data[0]["recommended_action"] == "RESTORE_FROM_GIT_UNLESS_USER_APPROVES_DELETE"
    assert s["restore_candidate_count"] == 1


def test_parse_modified_tracked_file(tmp_path):
    repo = tmp_path / "repo"
    make(repo / "scripts/v20/a.py")
    m.run(repo, command_runner=fake_runner(" M scripts/v20/a.py\n"))
    row = rows(repo / m.OUT_REL / "dirty_file_triage_manifest.csv")[0]
    assert row["status_family"] == "MODIFIED"
    assert row["recommended_action"] == "REVIEW_DIFF_BEFORE_COMMIT_OR_RESTORE"


def test_parse_untracked_script_triplet_commit_candidate(tmp_path):
    repo = tmp_path / "repo"
    for p in ["scripts/v21/v21_262_x.py", "scripts/v21/test_v21_262_x.py", "scripts/v21/run_v21_262_x.ps1"]:
        make(repo / p)
    status = "?? scripts/v21/v21_262_x.py\n?? scripts/v21/test_v21_262_x.py\n?? scripts/v21/run_v21_262_x.ps1\n"
    m.run(repo, command_runner=fake_runner(status))
    data = rows(repo / m.OUT_REL / "commit_candidate_manifest.csv")
    assert len(data) == 3
    assert {r["recommended_action"] for r in data} == {"POSSIBLE_COMMIT_AFTER_TARGETED_VALIDATION"}


def test_untracked_doc_commit_candidate(tmp_path):
    repo = tmp_path / "repo"
    make(repo / "docs/DAILY_CHAIN_RUNBOOK.md")
    m.run(repo, command_runner=fake_runner("?? docs/DAILY_CHAIN_RUNBOOK.md\n"))
    row = rows(repo / m.OUT_REL / "commit_candidate_manifest.csv")[0]
    assert row["recommended_action"] == "POSSIBLE_COMMIT_AFTER_REVIEW"


def test_temp_anomaly_1e12_ignore(tmp_path):
    repo = tmp_path / "repo"
    make(repo / "1E-12")
    m.run(repo, command_runner=fake_runner("?? 1E-12\n"))
    row = rows(repo / m.OUT_REL / "ignore_candidate_manifest.csv")[0]
    assert row["recommended_action"] == "IGNORE_OR_DELETE_LOCAL_ONLY"


def test_cache_env_temp_ignore(tmp_path):
    repo = tmp_path / "repo"
    status = "?? .venv/x.py\n?? .pytest_cache/y\n?? tmp/z\n"
    for p in [".venv/x.py", ".pytest_cache/y", "tmp/z"]:
        make(repo / p)
    m.run(repo, command_runner=fake_runner(status))
    data = rows(repo / m.OUT_REL / "ignore_candidate_manifest.csv")
    assert len(data) == 3


def test_tracked_deletion_not_commit_candidate(tmp_path):
    repo = tmp_path / "repo"
    m.run(repo, command_runner=fake_runner(" D scripts/v20/old.py\n"))
    assert rows(repo / m.OUT_REL / "restore_candidate_manifest.csv")
    assert not rows(repo / m.OUT_REL / "commit_candidate_manifest.csv")


def test_no_triplet_not_commit_candidate(tmp_path):
    repo = tmp_path / "repo"
    make(repo / "scripts/v21/v21_262_lonely.py")
    m.run(repo, command_runner=fake_runner("?? scripts/v21/v21_262_lonely.py\n"))
    assert not rows(repo / m.OUT_REL / "commit_candidate_manifest.csv")
    assert rows(repo / m.OUT_REL / "user_review_required_manifest.csv")


def test_no_mutation_commands_called_static():
    repo = Path("unused")
    seen: list[list[str]] = []

    def runner(r: Path, args: list[str]):
        seen.append(args)
        if args[:2] == ["git", "status"]:
            return 0, "", ""
        if args[:2] == ["git", "log"]:
            return 0, "a\tb", ""
        if args[:2] == ["git", "branch"]:
            return 0, "main\n", ""
        return 0, "", ""

    m.run(repo, command_runner=runner)
    forbidden = {"add", "commit", "restore", "clean", "rm"}
    assert not any(len(cmd) > 1 and cmd[0] == "git" and cmd[1] in forbidden for cmd in seen)


def test_summary_schema_stable(tmp_path):
    repo = tmp_path / "repo"
    m.run(repo, command_runner=fake_runner("?? docs/a.md\n"))
    payload = json.loads((repo / m.OUT_REL / "v21_262_summary.json").read_text(encoding="utf-8"))
    for key in ["latest_commit_hash", "latest_commit_subject", "branch_name", "origin_tracking_status", "dirty_total_count", "tracked_deletion_count", "tracked_modification_count", "untracked_count", "staged_count", "restore_candidate_count", "commit_candidate_count", "ignore_candidate_count", "user_review_required_count", "large_file_candidate_count", "highest_risk_class", "safe_to_git_add_all", "safe_to_git_clean", "recommended_next_step"]:
        assert key in payload


def test_wrapper_dryrun_exits_zero():
    proc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\v21\\run_v21_262_git_worktree_dirty_state_triage_r1.ps1", "-DryRun", "-MaxRows", "100000"],
        cwd=Path(__file__).parents[2],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0
