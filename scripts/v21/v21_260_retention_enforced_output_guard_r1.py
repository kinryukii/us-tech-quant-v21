#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

STAGE = "V21.260_RETENTION_ENFORCED_OUTPUT_GUARD_R1"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
PROTECTED_DIR_NAMES = {".git", ".venv", ".venv_moomoo_py312", "scripts", "tests", "inputs", "state"}
MOVE_CLASSES = {
    "MOVE_LARGE_ROW_LEVEL_OUTPUT_TO_CACHE",
    "MOVE_LARGE_BACKTEST_RAW_TO_CACHE",
    "MOVE_LARGE_TECHNICAL_PANEL_TO_CACHE",
    "MOVE_LARGE_FORWARD_PANEL_TO_CACHE",
    "MOVE_LARGE_BUCKET_OR_IC_RAW_TO_CACHE",
    "MOVE_CANONICAL_BACKUP_TO_CACHE",
}
GATES = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "factor_promotion_allowed": False,
    "market_data_fetch_allowed": False,
}


def readable_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 6)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def scan_roots(repo: Path, include_v20: bool, include_shared: bool) -> list[Path]:
    roots = [repo / "outputs" / "v21", repo / "outputs" / "_analysis"]
    if include_v20:
        roots.append(repo / "outputs" / "v20")
    if include_shared:
        roots.append(repo / "outputs" / "shared")
    return [p for p in roots if p.exists()]


def is_protected_path(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return True
    parts = {p.lower() for p in rel.parts}
    return any(name.lower() in parts for name in PROTECTED_DIR_NAMES)


def classify_file(path: Path, repo: Path, threshold_mb: float, allow_user_archive_move: bool) -> tuple[str, str]:
    rel = path.relative_to(repo).as_posix()
    name = path.name.lower()
    rel_lower = rel.lower()
    size_mb = readable_size_mb(path)
    if is_protected_path(path, repo):
        return "PROTECTED_STATE_OR_INPUT_REFERENCE", "Protected path."
    if "v21.233_moomoo_only_abcde_rerun" in rel_lower and not allow_user_archive_move:
        return "PROTECTED_USER_ARCHIVE_REVIEW_REQUIRED", "V21.233 archive requires explicit separate approval."
    if name.endswith(".moved_to_cache.pointer.txt") or "pointer_manifest" in name:
        return "KEEP_POINTER_MANIFEST", "Pointer artifact."
    if name.endswith(".json") and ("summary" in name or "manifest" in name):
        return "KEEP_SUMMARY_REPORT", "Summary or JSON manifest."
    if name.endswith(".txt") and ("report" in name or "summary" in name):
        return "KEEP_SUMMARY_REPORT", "Report text."
    if size_mb <= threshold_mb:
        if "latest" in name:
            return "KEEP_LATEST_SMALL_TABLE", "Small latest table."
        if "topn" in name or "top_" in name or "top50" in name:
            return "KEEP_TOPN_SMALL_TABLE", "Small top-N table."
        return "OBSERVE_ONLY", "Below threshold."
    if "technical" in name and ("panel" in name or "subfactor" in name or "join" in name):
        return "MOVE_LARGE_TECHNICAL_PANEL_TO_CACHE", "Large technical panel."
    if "forward" in name and ("panel" in name or "return" in name):
        return "MOVE_LARGE_FORWARD_PANEL_TO_CACHE", "Large forward-return panel."
    if any(tok in name for tok in ["backtest", "trial", "replay", "simulation", "random_asof"]):
        return "MOVE_LARGE_BACKTEST_RAW_TO_CACHE", "Large raw backtest/trial output."
    if any(tok in name for tok in ["bucket", "ic_timeseries", "rank_ic", "raw_ic"]):
        return "MOVE_LARGE_BUCKET_OR_IC_RAW_TO_CACHE", "Large bucket/IC raw output."
    if "backup" in name or "canonical" in name:
        return "MOVE_CANONICAL_BACKUP_TO_CACHE", "Large canonical backup."
    return "MOVE_LARGE_ROW_LEVEL_OUTPUT_TO_CACHE", "Large row-level output."


def cache_target(cache_root: Path, repo: Path, source: Path) -> Path:
    rel = source.relative_to(repo)
    parts = rel.parts
    if parts and parts[0].lower() == "outputs":
        rel = Path(*parts[1:])
    return cache_root / "large_outputs" / rel


def pointer_text(source: Path, target: Path, sha: str, size_bytes: int) -> str:
    return "\n".join([
        "MOVED_TO_CACHE",
        f"source_path={source}",
        f"cache_path={target}",
        f"sha256={sha}",
        f"byte_size={size_bytes}",
        f"stage={STAGE}",
    ]) + "\n"


def build_scan(repo: Path, threshold_mb: float, include_v20: bool, include_shared: bool, allow_user_archive_move: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    scan_rows: list[dict[str, Any]] = []
    protected_rows: list[dict[str, Any]] = []
    violation_rows: list[dict[str, Any]] = []
    for root in scan_roots(repo, include_v20, include_shared):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo).as_posix()
            size_mb = readable_size_mb(path)
            classification, reason = classify_file(path, repo, threshold_mb, allow_user_archive_move)
            oversized = size_mb > threshold_mb
            movable = classification in MOVE_CLASSES
            row = {
                "repo_relative_path": rel,
                "size_mb": size_mb,
                "large_file_threshold_mb": threshold_mb,
                "oversized": oversized,
                "classification": classification,
                "movable_candidate": movable,
                "reason": reason,
            }
            scan_rows.append(row)
            if classification.startswith("PROTECTED"):
                protected_rows.append(row)
            if oversized and (movable or classification.startswith("PROTECTED")):
                violation_rows.append({**row, "violation_type": "MOVABLE_LARGE_FILE" if movable else "PROTECTED_LARGE_FILE"})
    return scan_rows, protected_rows, violation_rows


def execute_moves(repo: Path, cache_root: Path, scan_rows: list[dict[str, Any]], hash_func: Callable[[Path], str] = sha256_file, copy_func: Callable[[Path, Path], Any] = shutil.copy2) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    move_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in scan_rows:
        if row["classification"] not in MOVE_CLASSES:
            continue
        source = repo / row["repo_relative_path"]
        if not source.exists():
            continue
        target = cache_target(cache_root, repo, source)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = hash_func(source)
        status = "PENDING"
        msg = ""
        try:
            copy_func(source, target)
            after = hash_func(target)
            if before != after:
                status = "FAIL_HASH_MISMATCH_SOURCE_RETAINED"
                msg = "Copied hash does not match source hash."
                errors.append({**row, "violation_type": status})
            else:
                size_bytes = source.stat().st_size
                source.unlink()
                pointer = source.with_name(source.name + ".MOVED_TO_CACHE.pointer.txt")
                pointer.write_text(pointer_text(source, target, before, size_bytes), encoding="utf-8")
                status = "MOVED_TO_CACHE_VERIFIED"
        except Exception as exc:
            after = ""
            status = "FAIL_MOVE_ERROR_SOURCE_RETAINED"
            msg = str(exc)
            errors.append({**row, "violation_type": status})
        move_rows.append({
            "repo_relative_path": row["repo_relative_path"],
            "cache_path": str(target),
            "classification": row["classification"],
            "size_mb": row["size_mb"],
            "source_sha256": before,
            "cache_sha256": after if "after" in locals() else "",
            "move_status": status,
            "message": msg,
        })
    return move_rows, errors


def summarize(mode: str, out: Path, scan_rows: list[dict[str, Any]], move_rows: list[dict[str, Any]], protected_rows: list[dict[str, Any]], violation_rows: list[dict[str, Any]], errors: list[dict[str, Any]], fail_on_violation: bool, max_allowed_repo_outputs_mb: float | None) -> dict[str, Any]:
    movable_count = sum(1 for r in scan_rows if r["movable_candidate"] and r["oversized"])
    estimated_reclaimable_mb = round(sum(float(r["size_mb"]) for r in scan_rows if r["movable_candidate"] and r["oversized"]), 6)
    moved_count = sum(1 for r in move_rows if r["move_status"] == "MOVED_TO_CACHE_VERIFIED")
    repo_outputs_mb = round(sum(float(r["size_mb"]) for r in scan_rows), 6)
    status = "PASS_V21_260_RETENTION_GUARD_DRYRUN_READY" if mode == "DryRun" and movable_count == 0 else "WARN_V21_260_RETENTION_VIOLATIONS_FOUND_DRYRUN_READY" if mode == "DryRun" else "PASS_V21_260_RETENTION_ENFORCEMENT_COMPLETED"
    if errors or (fail_on_violation and mode == "Execute" and movable_count != moved_count) or (max_allowed_repo_outputs_mb is not None and repo_outputs_mb > max_allowed_repo_outputs_mb):
        status = "FAIL_V21_260_RETENTION_ENFORCEMENT_ERROR"
    return {
        "final_status": status,
        "final_decision": "RETENTION_GUARD_DRYRUN_READY" if mode == "DryRun" else "RETENTION_ENFORCEMENT_COMPLETED" if status.startswith("PASS") else "RETENTION_ENFORCEMENT_REVIEW_REQUIRED",
        "run_mode": mode,
        "output_root": str(out),
        "scanned_file_count": len(scan_rows),
        "oversized_file_count": sum(1 for r in scan_rows if r["oversized"]),
        "movable_candidate_count": movable_count,
        "protected_candidate_count": len(protected_rows),
        "violation_count": len(violation_rows) + len(errors),
        "moved_file_count": moved_count,
        "move_error_count": len(errors),
        "estimated_reclaimable_mb": estimated_reclaimable_mb,
        "repo_outputs_scanned_mb": repo_outputs_mb,
        **GATES,
    }


def write_outputs(out: Path, summary: dict[str, Any], scan_rows: list[dict[str, Any]], move_rows: list[dict[str, Any]], protected_rows: list[dict[str, Any]], violation_rows: list[dict[str, Any]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    scan_fields = ["repo_relative_path", "size_mb", "large_file_threshold_mb", "oversized", "classification", "movable_candidate", "reason"]
    write_csv(out / "retention_scan_manifest.csv", scan_rows, scan_fields)
    write_csv(out / "retention_move_manifest.csv", move_rows, ["repo_relative_path", "cache_path", "classification", "size_mb", "source_sha256", "cache_sha256", "move_status", "message"])
    write_csv(out / "retention_protected_manifest.csv", protected_rows, scan_fields)
    write_csv(out / "retention_violation_manifest.csv", violation_rows, scan_fields + ["violation_type"])
    write_json(out / "v21_260_summary.json", summary)
    report = "\n".join([
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"run_mode={summary['run_mode']}",
        f"movable_candidate_count={summary['movable_candidate_count']}",
        f"moved_file_count={summary['moved_file_count']}",
        f"estimated_reclaimable_mb={summary['estimated_reclaimable_mb']}",
        "research_only=True",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "market_data_fetch_allowed=False",
    ]) + "\n"
    (out / "v21_260_retention_guard_report.txt").write_text(report, encoding="utf-8")


def run(
    repo: Path,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    output_dir: Path | None = None,
    mode: str = "DryRun",
    large_file_threshold_mb: float = 5.0,
    include_v20: bool = False,
    include_shared: bool = False,
    allow_user_archive_move: bool = False,
    fail_on_violation: bool = False,
    max_allowed_repo_outputs_mb: float | None = None,
    hash_func: Callable[[Path], str] = sha256_file,
    copy_func: Callable[[Path, Path], Any] = shutil.copy2,
) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    scan_rows, protected_rows, violation_rows = build_scan(repo, large_file_threshold_mb, include_v20, include_shared, allow_user_archive_move)
    move_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if mode == "Execute":
        move_rows, errors = execute_moves(repo, cache_root, scan_rows, hash_func, copy_func)
        violation_rows.extend(errors)
    summary = summarize(mode, out, scan_rows, move_rows, protected_rows, violation_rows, errors, fail_on_violation, max_allowed_repo_outputs_mb)
    write_outputs(out, summary, scan_rows, move_rows, protected_rows, violation_rows)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--mode", choices=["DryRun", "Execute"], default="DryRun")
    p.add_argument("--large-file-threshold-mb", type=float, default=5.0)
    p.add_argument("--include-v20", action="store_true")
    p.add_argument("--include-shared", action="store_true")
    p.add_argument("--allow-user-archive-move", action="store_true")
    p.add_argument("--fail-on-violation", action="store_true")
    p.add_argument("--max-allowed-repo-outputs-mb", type=float)
    a = p.parse_args(argv)
    s = run(a.repo_root.resolve(), a.cache_root, a.output_dir, a.mode, a.large_file_threshold_mb, a.include_v20, a.include_shared, a.allow_user_archive_move, a.fail_on_violation, a.max_allowed_repo_outputs_mb)
    for k in ["final_status", "final_decision", "run_mode", "scanned_file_count", "oversized_file_count", "movable_candidate_count", "protected_candidate_count", "violation_count", "moved_file_count", "move_error_count", "estimated_reclaimable_mb", "repo_outputs_scanned_mb", "research_only", "broker_action_allowed", "official_adoption_allowed", "market_data_fetch_allowed", "output_root"]:
        print(f"{k}={s.get(k)}")
    return 1 if str(s.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
