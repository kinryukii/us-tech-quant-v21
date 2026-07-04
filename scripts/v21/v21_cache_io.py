"""V21 local cache IO router.

Large and rebuildable artifacts should live in the local cache. Repo outputs
should stay compact and contain summaries, reports, and pointer manifests.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
LARGE_ARTIFACT_THRESHOLD_BYTES = 5 * 1024 * 1024
CACHE_LAYOUT_DIRS = [
    "data/raw/moomoo",
    "data/raw/legacy_external_diagnostic",
    "data/raw/manual_import",
    "data/canonical/ohlcv",
    "data/canonical/kline",
    "data/asof_snapshots",
    "features/technical",
    "features/momentum",
    "features/risk",
    "features/strategy",
    "runs/daily_chain",
    "runs/abcde",
    "runs/dram",
    "runs/backtest",
    "runs/replay",
    "runs/diagnostics",
    "results/latest",
    "results/compact",
    "results/reports",
    "manifests/file_manifest",
    "manifests/run_manifest",
    "manifests/dependency_edges",
    "index",
    "tmp",
    "trash_pending_delete",
]
REGISTRY_FIELDS = [
    "cache_artifact_path",
    "artifact_role",
    "retention_class",
    "run_id",
    "source_stage",
    "registered_time",
    "size_bytes",
    "metadata_json",
]
RETENTION_FIELDS = ["artifact_role", "default_retention_class", "retention_days", "cleanup_action", "rationale"]
POINTER_FIELDS = ["cache_artifact_path", "artifact_role", "run_id", "metadata_json", "pointer_created_time", "cache_artifact_exists"]
RETENTION_DEFAULTS = [
    ("CURRENT_CHAIN_DATA", "PIN_CURRENT", "", "KEEP", "Current daily-chain input/output data."),
    ("CANONICAL_DATA", "PIN_CANONICAL", "", "KEEP", "Canonical source data."),
    ("RAW_BROKER_DATA", "HOT_14D", "14", "REVIEW_OR_PRUNE", "Raw broker pulls are hot cache."),
    ("FEATURE_CACHE", "WARM_60D", "60", "PRUNE_AFTER_RETENTION", "Rebuildable feature cache."),
    ("FAST_BACKTEST_CACHE", "DELETE_AFTER_30D", "30", "DELETE_AFTER_RETENTION", "Backtest acceleration cache."),
    ("REPLAY_CACHE", "DELETE_AFTER_30D", "30", "DELETE_AFTER_RETENTION", "Replay cache."),
    ("RUN_RESULT_FULL", "COLD_180D", "180", "PRUNE_AFTER_RETENTION", "Full run results retained outside repo."),
    ("RUN_RESULT_COMPACT", "WARM_60D", "60", "KEEP_COMPACT", "Compact results."),
    ("DECISION_ARTIFACT", "PIN_CURRENT", "", "KEEP", "Decision artifacts."),
    ("REPORT", "WARM_60D", "60", "KEEP_COMPACT", "Reports."),
    ("MANIFEST", "WARM_60D", "60", "KEEP", "Manifests."),
    ("TEMP_CACHE", "DELETE_ON_NEXT_CLEANUP", "0", "DELETE", "Temporary cache."),
    ("REBUILDABLE_CACHE", "DELETE_AFTER_7D", "7", "DELETE_AFTER_RETENTION", "Rebuildable cache."),
    ("LOW_VALUE_HISTORY", "MANUAL_REVIEW", "", "REVIEW", "Low-value history."),
]


def get_cache_root() -> Path:
    return Path(os.environ.get("V21_CACHE_ROOT", str(DEFAULT_CACHE_ROOT))).resolve()


def safe_relative_path(path: str | Path) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        raise ValueError("absolute paths are not allowed")
    parts = raw.parts
    if any(part in {"..", ""} for part in parts):
        raise ValueError("path traversal is not allowed")
    return raw


def ensure_cache_layout(cache_root: Path | None = None) -> dict[str, Any]:
    root = (cache_root or get_cache_root()).resolve()
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    for rel_dir in CACHE_LAYOUT_DIRS:
        (root / rel_dir).mkdir(parents=True, exist_ok=True)
    registry_initialized, registry_reason = _init_csv_if_missing_or_empty(root / "index/cache_registry.csv", REGISTRY_FIELDS)
    retention_initialized, retention_reason = _init_retention(root / "index/cache_retention_policy.csv")
    return {
        "cache_root": str(root),
        "cache_root_created": created,
        "cache_layout_dir_count": len(CACHE_LAYOUT_DIRS),
        "registry_initialized": registry_initialized,
        "registry_overwrite_reason": registry_reason,
        "retention_policy_initialized": retention_initialized,
        "retention_policy_overwrite_reason": retention_reason,
    }


def _init_csv_if_missing_or_empty(path: Path, fields: list[str]) -> tuple[bool, str]:
    if path.exists() and path.stat().st_size > 0:
        return False, ""
    reason = "EMPTY_INITIALIZATION" if path.exists() else "MISSING_INITIALIZATION"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
    return True, reason


def _init_retention(path: Path) -> tuple[bool, str]:
    if path.exists() and path.stat().st_size > 0:
        return False, ""
    reason = "EMPTY_INITIALIZATION" if path.exists() else "MISSING_INITIALIZATION"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RETENTION_FIELDS, lineterminator="\n")
        writer.writeheader()
        for role, retention, days, action, rationale in RETENTION_DEFAULTS:
            writer.writerow({
                "artifact_role": role,
                "default_retention_class": retention,
                "retention_days": days,
                "cleanup_action": action,
                "rationale": rationale,
            })
    return True, reason


def new_run_id(stage_name: str, asof_date: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_stage = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stage_name)
    return f"{safe_stage}__{asof_date}__{stamp}" if asof_date else f"{safe_stage}__{stamp}"


def get_cache_path(category: str, stage_name: str | None = None, run_id: str | None = None, filename: str | None = None) -> Path:
    root = get_cache_root()
    path = root / safe_relative_path(category)
    if stage_name:
        path = path / safe_relative_path(stage_name)
    if run_id:
        path = path / safe_relative_path(run_id)
    if filename:
        path = path / safe_relative_path(filename)
    return path


def classify_artifact_size(path_or_size: str | Path | int) -> str:
    size = int(path_or_size) if isinstance(path_or_size, int) else Path(path_or_size).stat().st_size
    if size >= LARGE_ARTIFACT_THRESHOLD_BYTES:
        return "LARGE"
    if size >= 512 * 1024:
        return "MEDIUM"
    return "SMALL"


def should_write_to_cache(artifact_name: str, size_bytes: int | None = None, artifact_role: str | None = None) -> bool:
    if os.environ.get("V21_KEEP_FULL_ARTIFACTS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    role = artifact_role or ""
    if role in {"RUN_RESULT_FULL", "RAW_BROKER_DATA", "FEATURE_CACHE", "FAST_BACKTEST_CACHE", "REPLAY_CACHE"}:
        return True
    if size_bytes is not None and size_bytes >= LARGE_ARTIFACT_THRESHOLD_BYTES:
        return True
    name = artifact_name.lower()
    if any(token in name for token in ["full", "panel", "ledger", "replay", "kline", "raw", "matrix", "seed"]):
        return True
    return False


def write_pointer_manifest(repo_output_dir: str | Path, cache_artifact_path: str | Path, artifact_role: str, run_id: str, metadata: dict[str, Any] | None = None) -> Path:
    repo_dir = Path(repo_output_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_artifact_path)
    pointer_path = repo_dir / "cache_pointer_manifest.csv"
    row = {
        "cache_artifact_path": str(cache_path),
        "artifact_role": artifact_role,
        "run_id": run_id,
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
        "pointer_created_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cache_artifact_exists": cache_path.exists(),
    }
    exists = pointer_path.exists()
    with pointer_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINTER_FIELDS, lineterminator="\n")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    return pointer_path


def register_cache_artifact(cache_artifact_path: str | Path, artifact_role: str, retention_class: str, run_id: str, source_stage: str, metadata: dict[str, Any] | None = None) -> Path:
    root = get_cache_root()
    ensure_cache_layout(root)
    path = Path(cache_artifact_path)
    registry = root / "index/cache_registry.csv"
    row = {
        "cache_artifact_path": str(path),
        "artifact_role": artifact_role,
        "retention_class": retention_class,
        "run_id": run_id,
        "source_stage": source_stage,
        "registered_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
    }
    with registry.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REGISTRY_FIELDS, lineterminator="\n")
        writer.writerow(row)
    return registry


def read_cache_registry(cache_root: Path | None = None) -> list[dict[str, str]]:
    root = cache_root or get_cache_root()
    path = root / "index/cache_registry.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_cache_registry_snapshot(output_path: str | Path, cache_root: Path | None = None) -> Path:
    rows = read_cache_registry(cache_root)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REGISTRY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return output


def get_retention_policy(cache_root: Path | None = None) -> list[dict[str, str]]:
    root = cache_root or get_cache_root()
    path = root / "index/cache_retention_policy.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
