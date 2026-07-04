#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

STAGE = "V21.262_GIT_WORKTREE_DIRTY_STATE_TRIAGE_R1"
OUT_REL = Path("outputs/v21") / STAGE
PUSHED_COMMIT = "a4af37343d8def1eb248597e04095f0a3a80479e"
PUSHED_SUBJECT = "Add V21.260 retention enforcement and V21.261 daily wiring"
RISK_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def run_cmd(repo: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=str(repo), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def parse_porcelain_line(line: str) -> dict[str, str]:
    xy = line[:2]
    rest = line[3:] if len(line) > 3 else ""
    old_path = ""
    path = rest
    if " -> " in rest:
        old_path, path = rest.split(" -> ", 1)
    index, worktree = xy[0], xy[1]
    if xy == "??":
        family, tracked = "UNTRACKED", "UNTRACKED"
    elif "R" in xy:
        family, tracked = "RENAMED", "STAGED" if index != " " else "MIXED"
    elif "C" in xy:
        family, tracked = "COPIED", "STAGED" if index != " " else "MIXED"
    elif "D" in xy:
        family, tracked = "DELETED", "TRACKED" if index == " " else "MIXED"
    elif "M" in xy:
        family, tracked = "MODIFIED", "TRACKED" if index == " " else "MIXED"
    elif "A" in xy:
        family, tracked = "ADDED_STAGED", "STAGED"
    else:
        family, tracked = "OTHER", "MIXED"
    return {"xy_status": xy, "index_status": index, "worktree_status": worktree, "path": path, "old_path": old_path, "status_family": family, "tracked_state": tracked}


def version_family(path: str) -> str:
    low = path.lower()
    m = re.search(r"v(16|17|18|20|21)[_/.-]", low)
    if m:
        return f"V{m.group(1)}"
    if low.startswith("docs/"):
        return "DOCS"
    if "data_source" in low or "data_sources" in low:
        return "DATA_SOURCE"
    return "OTHER"


def version_number(path: str) -> int:
    m = re.search(r"v21[_\.-](\d+)|v21_(\d+)", path.lower())
    if not m:
        m = re.search(r"v20[_\.-](\d+)|v20_(\d+)", path.lower())
    if not m:
        return -1
    return int(next(g for g in m.groups() if g))


def script_triplet_exists(path: str, all_paths: set[str], repo: Path) -> bool:
    p = Path(path)
    name = p.name
    parent = p.parent.as_posix()
    if name.startswith("v") and name.endswith(".py"):
        stem = name[:-3]
        needed = {f"{parent}/test_{stem}.py", f"{parent}/run_{stem}.ps1"}
    elif name.startswith("test_") and name.endswith(".py"):
        stem = name[len("test_"):-3]
        needed = {f"{parent}/{stem}.py", f"{parent}/run_{stem}.ps1"}
    elif name.startswith("run_") and name.endswith(".ps1"):
        stem = name[len("run_"):-4]
        needed = {f"{parent}/{stem}.py", f"{parent}/test_{stem}.py"}
    else:
        return False
    return all(n in all_paths or (repo / n).exists() for n in needed)


def is_temp_or_anomaly(path: str) -> bool:
    low = path.lower()
    name = Path(path).name.lower()
    return name in {"1e-12"} or low.startswith("tmp/") or any(tok in low for tok in [".pytest_cache", "__pycache__", "/tmp/", "\\tmp\\", "/temp/", ".tmp"])


def is_cache_or_env(path: str) -> bool:
    low = path.lower()
    return any(tok in low for tok in [".venv", ".venv_moomoo_py312", ".pytest_cache", "__pycache__", "node_modules", "/cache/", "\\cache\\"])


def classify(row: dict[str, Any], all_paths: set[str], repo: Path, large_threshold_mb: float) -> dict[str, Any]:
    path = row["path"]
    p = repo / path
    exists = p.exists()
    size = p.stat().st_size if exists and p.is_file() else 0
    ext = p.suffix.lower()
    low = path.lower()
    top = Path(path).parts[0] if Path(path).parts else ""
    is_script = low.startswith("scripts/") and ext in {".py", ".ps1"}
    is_test = "/test_" in low or Path(path).name.startswith("test_")
    is_wrapper = Path(path).name.startswith("run_") or ext == ".ps1"
    is_backup = ".bak" in low or "backup" in low or "before_" in low
    is_doc = low.startswith("docs/") or ext in {".md", ".txt", ".rst"}
    temp = is_temp_or_anomaly(path)
    cache_env = is_cache_or_env(path)
    large = size > large_threshold_mb * 1024 * 1024
    family = row["status_family"]
    tracked_before = row["tracked_state"] != "UNTRACKED"
    recommended = "USER_REVIEW_REQUIRED"
    risk = "HIGH"
    reason = "Ambiguous dirty worktree entry."
    if temp or cache_env:
        recommended, risk, reason = "IGNORE_OR_DELETE_LOCAL_ONLY", "LOW", "Local temp/cache/env artifact."
    elif family == "DELETED" and tracked_before:
        recommended, risk, reason = "RESTORE_FROM_GIT_UNLESS_USER_APPROVES_DELETE", "HIGH", "Tracked deletion of historical/doc/script asset."
    elif family == "MODIFIED" and (low.startswith("scripts/") or low.startswith("docs/")):
        recommended, risk, reason = "REVIEW_DIFF_BEFORE_COMMIT_OR_RESTORE", "MEDIUM", "Tracked script/doc modification requires targeted diff review."
    elif family == "UNTRACKED" and low.startswith(("scripts/v21/", "scripts/v20/")) and ext in {".py", ".ps1"} and script_triplet_exists(path, all_paths, repo) and (version_number(path) >= 179 or "scripts/v20/" in low):
        recommended, risk, reason = "POSSIBLE_COMMIT_AFTER_TARGETED_VALIDATION", "MEDIUM", "Untracked script/test/wrapper appears to have matching sibling set."
    elif family == "UNTRACKED" and low.startswith("docs/"):
        recommended, risk, reason = "POSSIBLE_COMMIT_AFTER_REVIEW", "LOW", "Untracked docs file."
    return {
        **row,
        "file_exists": exists,
        "size_bytes": size,
        "size_kb": round(size / 1024, 3),
        "extension": ext,
        "top_level_dir": top,
        "version_family": version_family(path),
        "is_script": is_script,
        "is_test": is_test,
        "is_wrapper": is_wrapper,
        "is_backup": is_backup,
        "is_doc": is_doc,
        "is_cache_or_env": cache_env,
        "is_temp_or_anomaly": temp,
        "is_large_file": large,
        "git_tracked_before": tracked_before,
        "recommended_action": recommended,
        "action_risk": risk,
        "reason": reason,
    }


def parse_and_classify(status_text: str, repo: Path, large_threshold_mb: float, max_rows: int) -> list[dict[str, Any]]:
    lines = [ln for ln in status_text.splitlines() if ln.strip()][:max_rows]
    parsed = [parse_porcelain_line(ln) for ln in lines]
    all_paths = {r["path"] for r in parsed}
    return [classify(r, all_paths, repo, large_threshold_mb) for r in parsed]


def manifest_splits(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    restore = [r for r in rows if r["recommended_action"] == "RESTORE_FROM_GIT_UNLESS_USER_APPROVES_DELETE"]
    commit = [r for r in rows if r["recommended_action"] in {"POSSIBLE_COMMIT_AFTER_TARGETED_VALIDATION", "POSSIBLE_COMMIT_AFTER_REVIEW"}]
    ignore = [r for r in rows if r["recommended_action"] == "IGNORE_OR_DELETE_LOCAL_ONLY"]
    review = [r for r in rows if r["recommended_action"] in {"USER_REVIEW_REQUIRED", "REVIEW_DIFF_BEFORE_COMMIT_OR_RESTORE"}]
    return restore, commit, ignore, review


def highest_risk(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "LOW"
    return max((r["action_risk"] for r in rows), key=lambda r: RISK_RANK.get(r, 0))


def summary(repo: Path, rows: list[dict[str, Any]], latest_hash: str, subject: str, branch: str, tracking: str, error: bool = False) -> dict[str, Any]:
    restore, commit, ignore, review = manifest_splits(rows)
    dirty = len(rows)
    return {
        "final_status": "FAIL_V21_262_GIT_WORKTREE_TRIAGE_ERROR" if error else ("PASS_V21_262_GIT_WORKTREE_TRIAGE_READY" if dirty == 0 else "WARN_V21_262_DIRTY_WORKTREE_REQUIRES_REVIEW"),
        "final_decision": "GIT_WORKTREE_TRIAGE_READY_REVIEW_MANIFESTS_BEFORE_ACTION",
        "latest_commit_hash": latest_hash,
        "latest_commit_subject": subject,
        "branch_name": branch,
        "origin_tracking_status": tracking,
        "dirty_total_count": dirty,
        "tracked_deletion_count": sum(1 for r in rows if r["status_family"] == "DELETED"),
        "tracked_modification_count": sum(1 for r in rows if r["status_family"] == "MODIFIED"),
        "untracked_count": sum(1 for r in rows if r["status_family"] == "UNTRACKED"),
        "staged_count": sum(1 for r in rows if r["tracked_state"] == "STAGED"),
        "restore_candidate_count": len(restore),
        "commit_candidate_count": len(commit),
        "ignore_candidate_count": len(ignore),
        "user_review_required_count": len(review),
        "large_file_candidate_count": sum(1 for r in rows if r["is_large_file"]),
        "highest_risk_class": highest_risk(rows),
        "safe_to_git_add_all": False,
        "safe_to_git_clean": False,
        "recommended_next_step": "Review restore_candidate_manifest.csv first; do not use git add -A or git clean -fd.",
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_allowed": False,
        "output_root": str(repo / OUT_REL),
    }


FIELDS = ["xy_status", "index_status", "worktree_status", "path", "old_path", "status_family", "tracked_state", "file_exists", "size_bytes", "size_kb", "extension", "top_level_dir", "version_family", "is_script", "is_test", "is_wrapper", "is_backup", "is_doc", "is_cache_or_env", "is_temp_or_anomaly", "is_large_file", "git_tracked_before", "recommended_action", "action_risk", "reason"]


def write_outputs(repo: Path, raw: str, rows: list[dict[str, Any]], summ: dict[str, Any]) -> None:
    out = repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    (out / "git_status_raw.txt").write_text(raw, encoding="utf-8")
    write_csv(out / "git_status_porcelain_v1.csv", rows, FIELDS)
    write_csv(out / "dirty_file_triage_manifest.csv", rows, FIELDS)
    write_csv(out / "dirty_file_action_recommendation.csv", [{"recommended_action": r["recommended_action"], "action_risk": r["action_risk"], "path": r["path"], "reason": r["reason"]} for r in rows], ["recommended_action", "action_risk", "path", "reason"])
    restore, commit, ignore, review = manifest_splits(rows)
    write_csv(out / "restore_candidate_manifest.csv", restore, FIELDS)
    write_csv(out / "commit_candidate_manifest.csv", commit, FIELDS)
    write_csv(out / "ignore_candidate_manifest.csv", ignore, FIELDS)
    write_csv(out / "user_review_required_manifest.csv", review, FIELDS)
    write_json(out / "v21_262_summary.json", summ)
    report = "\n".join([
        STAGE,
        f"final_status={summ['final_status']}",
        f"dirty_total_count={summ['dirty_total_count']}",
        f"restore_candidate_count={summ['restore_candidate_count']}",
        f"commit_candidate_count={summ['commit_candidate_count']}",
        "",
        f"V21.260/V21.261 are already pushed in commit {PUSHED_COMMIT[:8]} ({PUSHED_SUBJECT}).",
        "Current dirty state is local-only and should not be pushed wholesale.",
        "git add . / git add -A / git clean -fd are not allowed at this stage.",
        "First likely safe remediation is restoring tracked deletions only after manifest review; V21.262 does not do this automatically.",
    ]) + "\n"
    (out / "v21_262_git_worktree_triage_report.txt").write_text(report, encoding="utf-8")


def origin_tracking(status_sb: str) -> str:
    first = status_sb.splitlines()[0] if status_sb.splitlines() else ""
    if "..." in first:
        return first.split("...", 1)[1].strip("[] ")
    return ""


def run(repo: Path, large_file_threshold_mb: float = 5.0, max_rows: int = 100000, include_untracked_hash: bool = False, command_runner: Callable[[Path, list[str]], tuple[int, str, str]] = run_cmd) -> dict[str, Any]:
    code, raw, err = command_runner(repo, ["git", "status", "--porcelain=v1"])
    c2, commit_line, _ = command_runner(repo, ["git", "log", "-1", "--pretty=format:%H%x09%s"])
    c3, branch, _ = command_runner(repo, ["git", "branch", "--show-current"])
    c4, sb, _ = command_runner(repo, ["git", "status", "-sb"])
    latest_hash, subject = "", ""
    if "\t" in commit_line:
        latest_hash, subject = commit_line.strip().split("\t", 1)
    rows = parse_and_classify(raw if code == 0 else "", repo, large_file_threshold_mb, max_rows)
    summ = summary(repo, rows, latest_hash, subject, branch.strip(), origin_tracking(sb), error=code != 0)
    write_outputs(repo, raw if code == 0 else err, rows, summ)
    return summ


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--large-file-threshold-mb", type=float, default=5.0)
    p.add_argument("--include-untracked-content-hash", action="store_true")
    p.add_argument("--max-rows", type=int, default=100000)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.large_file_threshold_mb, a.max_rows, a.include_untracked_content_hash)
    for k in ["final_status", "latest_commit_hash", "latest_commit_subject", "branch_name", "origin_tracking_status", "dirty_total_count", "tracked_deletion_count", "tracked_modification_count", "untracked_count", "restore_candidate_count", "commit_candidate_count", "ignore_candidate_count", "user_review_required_count", "highest_risk_class", "safe_to_git_add_all", "safe_to_git_clean", "recommended_next_step", "output_root"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
