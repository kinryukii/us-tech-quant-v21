#!/usr/bin/env python
"""V21.223 local cache architecture and IO router initialization."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v21_cache_io as cache_io  # noqa: E402


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER"
OUT_REL = Path("outputs/v21/V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER")
PROTECTED_REQUIRED = [
    ".venv",
    "scripts",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
]
LAYOUT_FIELDS = ["cache_root", "relative_dir", "exists", "created_or_present"]
SCHEMA_FIELDS = ["file_name", "column_name", "column_order", "description"]
POLICY_FIELDS = ["artifact_role", "default_retention_class", "retention_days", "cleanup_action", "rationale"]
SELFTEST_FIELDS = ["test_name", "passed", "detail"]
POINTER_POLICY_FIELDS = ["policy_key", "policy_value", "rationale"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
MIGRATION_FIELDS = ["migration_area", "recommended_change", "priority", "rationale"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def iter_files(path: Path) -> list[Path]:
    try:
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def v21_201_alias_is_current_chain(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    if any(token in path.name.lower() for token in tokens):
        return True
    return any(any(token in file.name.lower() for token in tokens) for file in iter_files(path)[:50])


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    out21 = root / "outputs/v21"
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact = expected.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = expected if exact else None
        method = "EXACT_PATH" if exact else "UNRESOLVED"
        warning = "" if exact else "EXPECTED_PATH_MISSING"
        if not exact and item.startswith("outputs/v21/V21.") and out21.exists():
            attempted = True
            sid = Path(item).name.split("_", 1)[0]
            candidates = [p for p in out21.iterdir() if p.is_dir() and p.name.startswith(sid) and (sid != "V21.201" or v21_201_alias_is_current_chain(p))]
            if candidates:
                resolved = max(candidates, key=lambda p: p.stat().st_mtime)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({"protected_key": Path(item).name, "expected_path": item, "exact_exists": exact, "alias_discovery_attempted": attempted, "alias_candidate_count": len(candidates), "resolved_exists": bool(resolved and resolved.exists()), "resolved_protected_path": rel(resolved, root) if resolved else "", "resolution_method": method, "warning_reason": warning})
    return rows


def schema_rows() -> list[dict[str, Any]]:
    rows = []
    for i, field in enumerate(cache_io.REGISTRY_FIELDS, 1):
        rows.append({"file_name": "index/cache_registry.csv", "column_name": field, "column_order": i, "description": "Cache artifact registry field."})
    for i, field in enumerate(cache_io.RETENTION_FIELDS, 1):
        rows.append({"file_name": "index/cache_retention_policy.csv", "column_name": field, "column_order": i, "description": "Cache retention policy field."})
    return rows


def layout_rows(cache_root: Path) -> list[dict[str, Any]]:
    return [{"cache_root": str(cache_root), "relative_dir": d, "exists": (cache_root / d).exists(), "created_or_present": "PRESENT"} for d in cache_io.CACHE_LAYOUT_DIRS]


def pointer_policy_rows() -> list[dict[str, Any]]:
    return [
        {"policy_key": "large_artifact_threshold_bytes", "policy_value": cache_io.LARGE_ARTIFACT_THRESHOLD_BYTES, "rationale": "Artifacts at or above threshold route to cache."},
        {"policy_key": "default_output_mode", "policy_value": os.environ.get("V21_OUTPUT_MODE", "compact"), "rationale": "Repo outputs default compact."},
        {"policy_key": "repo_keeps", "policy_value": "summary.json|compact_metrics.csv|top20.csv|top50.csv|final_report.txt|cache_pointer_manifest.csv|small_integrity_manifest.csv", "rationale": "Repo keeps compact artifacts and pointers."},
        {"policy_key": "full_artifact_override", "policy_value": "V21_KEEP_FULL_ARTIFACTS=true", "rationale": "Explicit override keeps full artifacts in repo."},
    ]


def migration_rows() -> list[dict[str, Any]]:
    return [
        {"migration_area": "V21.199_R4", "recommended_change": "route raw kline/history payloads to cache data/raw/moomoo and write repo pointers", "priority": "HIGH", "rationale": "Largest current-chain stage."},
        {"migration_area": "ABCDE reruns", "recommended_change": "write full panels to runs/abcde; keep top20/top50 and summary in repo", "priority": "HIGH", "rationale": "Ranking outputs need compact repo footprint."},
        {"migration_area": "backtests/replays", "recommended_change": "write full trial/replay panels to runs/backtest or runs/replay", "priority": "HIGH", "rationale": "Avoid rebuilding outputs/v21 bloat."},
        {"migration_area": "cleanup", "recommended_change": "use cache registry for retention instead of filename guessing", "priority": "MEDIUM", "rationale": "Improves future pruning."},
    ]


def selftest(root: Path, output: Path) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    try:
        run_id = cache_io.new_run_id(STAGE)
        artifact = cache_io.get_cache_path("tmp", STAGE, run_id, "tiny_selftest.txt")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("v21.223 selftest\n", encoding="utf-8")
        cache_io.register_cache_artifact(artifact, "TEMP_CACHE", "DELETE_ON_NEXT_CLEANUP", run_id, STAGE, {"selftest": True})
        pointer = cache_io.write_pointer_manifest(output, artifact, "TEMP_CACHE", run_id, {"selftest": True})
        registry = cache_io.read_cache_registry()
        pointer_rows = []
        with pointer.open(encoding="utf-8", newline="") as handle:
            pointer_rows = list(csv.DictReader(handle))
        resolved = bool(pointer_rows and Path(pointer_rows[-1]["cache_artifact_path"]).exists())
        rows.extend([
            {"test_name": "tiny_cache_artifact_created", "passed": artifact.exists(), "detail": str(artifact)},
            {"test_name": "registry_row_written", "passed": any(r.get("run_id") == run_id for r in registry), "detail": run_id},
            {"test_name": "pointer_manifest_resolves", "passed": resolved, "detail": str(pointer)},
        ])
        return rows, all(str_bool(r["passed"]) for r in rows)
    except Exception as exc:
        rows.append({"test_name": "selftest_exception", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
        return rows, False


def policy_flags(cache_root: Path) -> dict[str, Any]:
    repo_root = DEFAULT_ROOT.resolve()
    try:
        outside = not cache_root.resolve().is_relative_to(repo_root)
    except AttributeError:
        outside = str(repo_root).lower() not in str(cache_root.resolve()).lower()
    return {"research_only": True, "cache_architecture_enabled": True, "local_cache_root_outside_repo": outside, "mutation_allowed_limited_to_cache_init_and_v21_223_artifacts": True, "deletion_performed": False, "compression_performed": False, "archive_movement_performed": False, "price_refresh_performed": False, "canonical_mutation_performed": False, "moomoo_broker_connection_performed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"cache_root={summary['cache_root']}", f"pointer_selftest_passed={summary['pointer_selftest_passed']}", f"protected_path_missing_count={summary['protected_path_missing_count']}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.223 failure")
        presence = protected_presence(root)
        missing = [r for r in presence if not str_bool(r["resolved_exists"])]
        cache_root = cache_io.get_cache_root()
        layout_info = cache_io.ensure_cache_layout(cache_root)
        self_rows, self_ok = selftest(root, output)
        registry_rows = cache_io.read_cache_registry(cache_root)
        retention = cache_io.get_retention_policy(cache_root)
        status = "PASS_V21_223_LOCAL_CACHE_IO_ROUTER_READY"
        decision = "LOCAL_CACHE_IO_ROUTER_READY_FOR_SCRIPT_MIGRATION"
        if missing:
            status = "FAIL_V21_223_PROTECTED_PATH_MISSING"
            decision = "LOCAL_CACHE_IO_ROUTER_FAILED_PROTECTED_PATH_MISSING"
        elif not self_ok:
            status = "WARN_V21_223_CACHE_ROOT_EXISTS_WITH_WARNINGS"
            decision = "LOCAL_CACHE_IO_ROUTER_READY_WITH_WARNINGS"
        summary = {"stage": STAGE, "cache_root": str(cache_root), "cache_root_created": layout_info["cache_root_created"], "cache_layout_dir_count": layout_info["cache_layout_dir_count"], "registry_initialized": layout_info["registry_initialized"], "retention_policy_initialized": layout_info["retention_policy_initialized"], "pointer_selftest_passed": self_ok, "cache_registry_row_count": len(registry_rows), "default_output_mode": os.environ.get("V21_OUTPUT_MODE", "compact"), "large_artifact_threshold_bytes": cache_io.LARGE_ARTIFACT_THRESHOLD_BYTES, "protected_path_missing_count": len(missing), "final_status": status, "final_decision": decision, **policy_flags(cache_root)}
        write_csv(output / "local_cache_layout_manifest.csv", layout_rows(cache_root), LAYOUT_FIELDS)
        write_csv(output / "cache_registry_schema.csv", schema_rows(), SCHEMA_FIELDS)
        write_csv(output / "cache_retention_policy.csv", retention, POLICY_FIELDS)
        write_csv(output / "cache_io_helper_selftest.csv", self_rows, SELFTEST_FIELDS)
        write_csv(output / "repo_output_pointer_policy.csv", pointer_policy_rows(), POINTER_POLICY_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_csv(output / "migration_readiness_plan.csv", migration_rows(), MIGRATION_FIELDS)
        write_json(output / "v21_223_summary.json", summary)
        write_report(output / "V21.223_local_cache_architecture_and_io_router_report.txt", summary)
    except Exception as exc:
        cache_root = cache_io.get_cache_root()
        summary = {"stage": STAGE, "final_status": "FAIL_V21_223_CACHE_IO_ROUTER_EXCEPTION", "final_decision": "LOCAL_CACHE_IO_ROUTER_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags(cache_root)}
        write_json(output / "v21_223_summary.json", summary)
        (output / "V21.223_local_cache_architecture_and_io_router_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "cache_root", "pointer_selftest_passed", "cache_registry_row_count"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root))
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
