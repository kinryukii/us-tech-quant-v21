from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

P = Path(__file__).with_name("v21_260_retention_enforced_output_guard_r1.py")
S = importlib.util.spec_from_file_location("m260", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def make_file(path: Path, size: int = 2048, text: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if text is not None else (b"x" * size))
    return path


def rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    make_file(repo / "outputs/v21/V21.246/technical_subfactor_panel_long.csv")
    make_file(repo / "outputs/v21/V21.246/forward_return_panel_aligned.csv")
    make_file(repo / "outputs/v21/V21.200/random_backtest_trials.csv")
    make_file(repo / "outputs/v21/V21.200/v21_200_summary.json", text=b"{}" * 2000)
    make_file(repo / "outputs/v21/V21.246/technical_subfactor_panel_long.csv.MOVED_TO_CACHE.pointer.txt", text=b"pointer" * 400)
    make_file(repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN/raw_big.csv")
    make_file(repo / "outputs/v21/protected/scripts/big.csv")
    make_file(repo / "outputs/v21/protected/tests/big.csv")
    make_file(repo / "outputs/v21/protected/inputs/big.csv")
    make_file(repo / "outputs/v21/protected/state/big.csv")
    make_file(repo / "outputs/v21/protected/.git/big.csv")
    make_file(repo / "outputs/v21/protected/.venv/big.csv")
    return repo, cache


def test_dryrun_does_not_mutate_files(tmp_path):
    repo, cache = seed(tmp_path)
    target = repo / "outputs/v21/V21.246/technical_subfactor_panel_long.csv"
    before = sha(target)
    s = m.run(repo, cache, large_file_threshold_mb=0.0001)
    assert s["run_mode"] == "DryRun"
    assert target.exists()
    assert sha(target) == before


def test_large_technical_panel_classified(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    row = next(r for r in data if r["repo_relative_path"].endswith("technical_subfactor_panel_long.csv"))
    assert row["classification"] == "MOVE_LARGE_TECHNICAL_PANEL_TO_CACHE"


def test_large_forward_panel_classified(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    row = next(r for r in data if r["repo_relative_path"].endswith("forward_return_panel_aligned.csv"))
    assert row["classification"] == "MOVE_LARGE_FORWARD_PANEL_TO_CACHE"


def test_large_backtest_trial_classified(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    row = next(r for r in data if r["repo_relative_path"].endswith("random_backtest_trials.csv"))
    assert row["classification"] == "MOVE_LARGE_BACKTEST_RAW_TO_CACHE"


def test_summary_and_pointer_are_kept(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    summary = next(r for r in data if r["repo_relative_path"].endswith("v21_200_summary.json"))
    pointer = next(r for r in data if r["repo_relative_path"].endswith(".MOVED_TO_CACHE.pointer.txt"))
    assert summary["classification"] == "KEEP_SUMMARY_REPORT"
    assert pointer["classification"] == "KEEP_POINTER_MANIFEST"


def test_v21_233_protected_unless_allowed(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    row = next(r for r in data if "V21.233_MOOMOO_ONLY_ABCDE_RERUN" in r["repo_relative_path"])
    assert row["classification"] == "PROTECTED_USER_ARCHIVE_REVIEW_REQUIRED"
    m.run(repo, cache, large_file_threshold_mb=0.0001, allow_user_archive_move=True)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    row = next(r for r in data if "V21.233_MOOMOO_ONLY_ABCDE_RERUN" in r["repo_relative_path"])
    assert row["classification"].startswith("MOVE_")


def test_execute_copies_verifies_removes_and_writes_pointer(tmp_path):
    repo, cache = seed(tmp_path)
    src = repo / "outputs/v21/V21.246/forward_return_panel_aligned.csv"
    before = sha(src)
    s = m.run(repo, cache, mode="Execute", large_file_threshold_mb=0.0001)
    pointer = src.with_name(src.name + ".MOVED_TO_CACHE.pointer.txt")
    target = cache / "large_outputs/v21/V21.246/forward_return_panel_aligned.csv"
    assert s["moved_file_count"] >= 1
    assert not src.exists()
    assert pointer.exists()
    assert target.exists()
    assert sha(target) == before


def test_hash_mismatch_prevents_deletion(tmp_path):
    repo, cache = seed(tmp_path)
    src = repo / "outputs/v21/V21.246/technical_subfactor_panel_long.csv"

    def bad_copy(source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"bad")

    s = m.run(repo, cache, mode="Execute", large_file_threshold_mb=0.0001, copy_func=bad_copy)
    assert s["final_status"] == "FAIL_V21_260_RETENTION_ENFORCEMENT_ERROR"
    assert src.exists()


def test_scripts_tests_inputs_state_git_venv_are_protected(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    data = rows(repo / m.OUT_REL / "retention_scan_manifest.csv")
    protected = [r for r in data if "/protected/" in r["repo_relative_path"]]
    assert protected
    assert {r["classification"] for r in protected} == {"PROTECTED_STATE_OR_INPUT_REFERENCE"}


def test_summary_schema_stable(tmp_path):
    repo, cache = seed(tmp_path)
    m.run(repo, cache, large_file_threshold_mb=0.0001)
    payload = json.loads((repo / m.OUT_REL / "v21_260_summary.json").read_text(encoding="utf-8"))
    for key in ["final_status", "final_decision", "run_mode", "scanned_file_count", "oversized_file_count", "movable_candidate_count", "protected_candidate_count", "violation_count", "moved_file_count", "estimated_reclaimable_mb", "research_only", "broker_action_allowed", "official_adoption_allowed", "market_data_fetch_allowed", "output_root"]:
        assert key in payload


def test_wrapper_dryrun_exits_zero():
    proc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\v21\\run_v21_260_retention_enforced_output_guard_r1.ps1", "-DryRun", "-LargeFileThresholdMB", "100000"],
        cwd=Path(__file__).parents[2],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0
