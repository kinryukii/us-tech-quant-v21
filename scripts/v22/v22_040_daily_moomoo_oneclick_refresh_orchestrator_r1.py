#!/usr/bin/env python
"""V22.040 daily Moomoo one-click research refresh orchestrator R1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.storage_paths import get_daily_root, get_cache_root, get_python_executable, assert_safe_output_path
from common.prerequisite_lifecycle import ensure as ensure_prerequisites, live_preflight


STAGE = "V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1"
OUT_REL = Path("outputs/v22") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
V232_REL = Path("outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN")
V233_REL = Path("outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN")
V234_REL = Path("outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN")
V256_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1")

PASS_STATUS = "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE"
RUNNING_STATUS = "RUNNING_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_IN_PROGRESS"
RUNNING_DECISION = "DAILY_MOOMOO_REFRESH_IN_PROGRESS_RESEARCH_ONLY"
WARN_TARGET = "WARN_TARGET_DATE_NOT_AVAILABLE_USED_LATEST_COMPLETE_DATE"
FAIL_STATUS = "FAIL_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_BLOCKED"
FAIL_CHILD_SUMMARY_MISSING = "FAIL_V22_040_CHILD_SUMMARY_MISSING"
FAIL_CHILD_NONZERO = "FAIL_V22_040_CHILD_NONZERO_EXIT"
DECISION_READY = "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY"
DECISION_BLOCKED = "DAILY_MOOMOO_REFRESH_BLOCKED_RESEARCH_ONLY"

CANON_RAW = "canonical_moomoo_ohlcv_daily_raw.csv"
CANON_QFQ = "canonical_moomoo_ohlcv_daily_qfq.csv"
POINTER_FIELDS = ["key", "value"]

StageRunner = Callable[[str, Path, Path], dict[str, Any]]
DedupRunner = Callable[..., dict[str, Any]]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

def daily_stage(rel: Path, *, allow_migrated: bool = True) -> Path:
    """External daily artifact path; legacy migration fallback is read-only."""
    if _RUNTIME_REPO is not None and _RUNTIME_REPO != default_repo_root().resolve():
        return _RUNTIME_REPO / rel
    current = get_daily_root() / "current" / rel.name
    migrated = get_daily_root() / "migrated_from_repo" / rel
    return current if current.exists() or not allow_migrated else migrated

_RUNTIME_REPO: Path | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def previous_weekday(value: date) -> date:
    value = value.fromordinal(value.toordinal() - 1)
    while value.weekday() >= 5:
        value = value.fromordinal(value.toordinal() - 1)
    return value


def latest_expected_completed_us_trading_date(now: datetime | None = None) -> str:
    ny_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    candidate = ny_now.date()
    if candidate.weekday() >= 5:
        return previous_weekday(candidate).isoformat()
    if ny_now.hour < 18:
        return previous_weekday(candidate).isoformat()
    return candidate.isoformat()


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return int(stat.st_dev), int(stat.st_ino)


def _allocated_size(path: Path) -> int:
    if os.name != "nt":
        stat = path.stat()
        return int(getattr(stat, "st_blocks", 0) * 512 or stat.st_size)
    import ctypes

    ctypes.set_last_error(0)
    high = ctypes.c_ulong(0)
    get_size = ctypes.windll.kernel32.GetCompressedFileSizeW
    get_size.restype = ctypes.c_ulong
    low = get_size(str(path), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        return 0
    return int((high.value << 32) | low)


def _security_fingerprint(path: Path) -> str | None:
    """Return owner/group/DACL identity; unknown metadata fails closed."""
    if os.name != "nt":
        stat = path.stat()
        return f"{stat.st_uid}:{stat.st_gid}:{stat.st_mode}"
    import ctypes

    needed = ctypes.c_ulong(0)
    security_info = 0x00000001 | 0x00000002 | 0x00000004
    get_security = ctypes.windll.advapi32.GetFileSecurityW
    get_security(str(path), security_info, None, 0, ctypes.byref(needed))
    if not needed.value:
        return None
    buffer = ctypes.create_string_buffer(needed.value)
    if not get_security(str(path), security_info, buffer, needed.value, ctypes.byref(needed)):
        return None
    return hashlib.sha256(buffer.raw[: needed.value]).hexdigest()


def _exclusive_read_available(path: Path) -> bool:
    if os.name != "nt":
        return True
    import ctypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.restype = ctypes.c_void_p
    handle = create_file(str(path), 0x80000000, 0, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        return False
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    return True


def _payload_metadata_compatible(source: Path, target: Path) -> bool:
    source_stat, target_stat = source.stat(), target.stat()
    source_attrs = int(getattr(source_stat, "st_file_attributes", 0))
    target_attrs = int(getattr(target_stat, "st_file_attributes", 0))
    unsafe = 0x400 | 0x200 | 0x800 | 0x4000  # reparse, sparse, compressed, encrypted
    if source_attrs & unsafe or target_attrs & unsafe:
        return False
    if source_stat.st_dev != target_stat.st_dev or source_attrs != target_attrs:
        return False
    source_security = _security_fingerprint(source)
    target_security = _security_fingerprint(target)
    return source_security is not None and source_security == target_security


def _historical_promoted_snapshot(path: Path, snapshot_root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        return (
            resolved.parent == snapshot_root.resolve(strict=True)
            and resolved.name.startswith("snapshot_id=v22_040_promoted_")
            and (resolved / "canonical_manifest.json").is_file()
        )
    except (OSError, RuntimeError):
        return False


def _transactional_hardlink_replace(
    source: Path,
    target: Path,
    expected_hash: str,
    *,
    replace: Callable[[Path, Path], Any] = os.replace,
    after_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Replace one independent duplicate without ever leaving no target path."""
    temp_link = target.with_name(f".{target.name}.post_dedup_link.tmp")
    rollback_link = target.with_name(f".{target.name}.post_dedup_rollback.tmp")
    try:
        if rollback_link.exists():
            if not target.exists():
                if sha256_file(rollback_link) != expected_hash:
                    return {"status": "FAIL_INTEGRITY", "reason": "INVALID_INTERRUPTED_ROLLBACK", "bytes_reclaimed": 0}
                replace(rollback_link, target)
            elif sha256_file(target) != expected_hash or sha256_file(rollback_link) != expected_hash:
                return {"status": "FAIL_INTEGRITY", "reason": "INCONSISTENT_INTERRUPTED_TRANSACTION", "bytes_reclaimed": 0}
            elif _file_identity(target) == _file_identity(source):
                if temp_link.exists():
                    temp_link.unlink()
                rollback_link.unlink()
                return {"status": "ALREADY_CONVERTED_RECOVERED", "bytes_reclaimed": 0}
            elif _file_identity(target) == _file_identity(rollback_link):
                if temp_link.exists():
                    temp_link.unlink()
                rollback_link.unlink()
            else:
                return {"status": "FAIL_INTEGRITY", "reason": "UNKNOWN_INTERRUPTED_IDENTITY", "bytes_reclaimed": 0}
        elif temp_link.exists():
            if sha256_file(temp_link) != expected_hash or _file_identity(temp_link) != _file_identity(source):
                return {"status": "FAIL_INTEGRITY", "reason": "INVALID_INTERRUPTED_TEMP_LINK", "bytes_reclaimed": 0}
            temp_link.unlink()
    except PermissionError as exc:
        return {"status": "SKIPPED_PERMISSION", "reason": f"RECOVERY_PERMISSION:{exc}", "bytes_reclaimed": 0}
    except OSError as exc:
        return {"status": "SKIPPED_OPERATIONAL", "reason": f"RECOVERY_IO:{exc}", "bytes_reclaimed": 0}
    allocated = _allocated_size(target)
    preserve_rollback = False
    try:
        os.link(source, temp_link)
        if sha256_file(temp_link) != expected_hash or _file_identity(temp_link) != _file_identity(source):
            raise RuntimeError("TEMP_HARDLINK_VALIDATION_FAILED")
        os.link(target, rollback_link)
        replace(temp_link, target)
        if after_replace is not None:
            after_replace(source, target)
        if not target.exists() or sha256_file(target) != expected_hash or _file_identity(target) != _file_identity(source):
            raise RuntimeError("FINAL_HARDLINK_VALIDATION_FAILED")
        rollback_link.unlink()
        return {"status": "CONVERTED", "bytes_reclaimed": allocated}
    except PermissionError as exc:
        if rollback_link.exists():
            try:
                replace(rollback_link, target)
            except OSError as rollback_exc:
                preserve_rollback = True
                return {"status": "FAIL_INTEGRITY", "reason": f"ROLLBACK_FAILED:{rollback_exc}", "bytes_reclaimed": 0}
        return {"status": "SKIPPED_PERMISSION", "reason": str(exc), "bytes_reclaimed": 0}
    except OSError as exc:
        if rollback_link.exists():
            try:
                replace(rollback_link, target)
            except OSError as rollback_exc:
                preserve_rollback = True
                return {"status": "FAIL_INTEGRITY", "reason": f"ROLLBACK_FAILED:{rollback_exc}", "bytes_reclaimed": 0}
        return {"status": "SKIPPED_OPERATIONAL", "reason": str(exc), "bytes_reclaimed": 0}
    except Exception as exc:
        if rollback_link.exists():
            try:
                replace(rollback_link, target)
            except OSError as rollback_exc:
                preserve_rollback = True
                return {"status": "FAIL_INTEGRITY", "reason": f"ROLLBACK_FAILED:{rollback_exc}", "bytes_reclaimed": 0}
        return {"status": "SKIPPED_ROLLED_BACK", "reason": str(exc), "bytes_reclaimed": 0}
    finally:
        if temp_link.exists():
            try:
                temp_link.unlink()
            except OSError:
                pass
        if rollback_link.exists() and target.exists() and not preserve_rollback:
            try:
                rollback_link.unlink()
            except OSError:
                pass


def dedup_superseded_snapshot(
    superseded_snapshot: Path,
    historical_root: Path,
    current_snapshot: Path,
    dry_run: bool = False,
    *,
    candidate_dirs: list[Path] | None = None,
    metadata_check: Callable[[Path, Path], bool] = _payload_metadata_compatible,
    transaction: Callable[..., dict[str, Any]] = _transactional_hardlink_replace,
) -> dict[str, Any]:
    """Bounded exact-snapshot reuse after promotion; current is always excluded."""
    started = time.perf_counter()
    result: dict[str, Any] = {
        "status": "NO_EXACT_DUPLICATE",
        "candidate_group_count": 0,
        "converted_file_count": 0,
        "would_convert_file_count": 0,
        "physical_bytes_reclaimed": 0,
        "would_reclaim_bytes": 0,
        "skipped_file_count": 0,
        "reason": "",
        "files_hashed": 0,
        "current_canonical_hardlink_participation_count": 0,
        "integrity_anomaly": False,
    }

    def finish(status: str, reason: str = "") -> dict[str, Any]:
        result["status"] = status
        result["reason"] = reason
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    superseded_snapshot = Path(superseded_snapshot)
    historical_root = Path(historical_root)
    current_snapshot = Path(current_snapshot)
    if not _historical_promoted_snapshot(superseded_snapshot, historical_root):
        return finish("SKIPPED_TARGET_NOT_HISTORICAL_PROMOTED")
    try:
        if superseded_snapshot.resolve() == current_snapshot.resolve():
            result["integrity_anomaly"] = True
            return finish("FAIL_INTEGRITY", "SUPERSEDED_EQUALS_CURRENT")
    except OSError:
        return finish("SKIPPED_PATH_UNAVAILABLE")

    payload_names = (CANON_RAW, CANON_QFQ)
    target_paths = [superseded_snapshot / name for name in payload_names]
    current_paths = [current_snapshot / name for name in payload_names]
    if not all(path.is_file() for path in target_paths + current_paths):
        return finish("SKIPPED_REQUIRED_PAYLOAD_MISSING")
    target_sizes = tuple(path.stat().st_size for path in target_paths)
    target_manifest = superseded_snapshot / "canonical_manifest.json"

    if candidate_dirs is None:
        try:
            candidate_dirs = sorted((path for path in historical_root.iterdir() if path.is_dir()), key=lambda p: p.name)
        except OSError as exc:
            return finish("SKIPPED_OPERATIONAL", str(exc))
    candidates: list[Path] = []
    for candidate in sorted(candidate_dirs, key=lambda p: Path(p).name):
        try:
            candidate = Path(candidate)
            if candidate.resolve() in {superseded_snapshot.resolve(), current_snapshot.resolve()}:
                continue
            if not _historical_promoted_snapshot(candidate, historical_root):
                continue
            paths = [candidate / name for name in payload_names]
            if all(path.is_file() for path in paths) and tuple(path.stat().st_size for path in paths) == target_sizes:
                candidates.append(candidate)
        except OSError:
            continue
    if not candidates:
        return finish("NO_EXACT_DUPLICATE", "CHEAP_SIZE_OR_PATH_REJECTION")

    target_manifest_hash = sha256_file(target_manifest)
    target_hashes = [sha256_file(path) for path in target_paths]
    result["files_hashed"] += 1 + len(target_paths)
    exact_source: Path | None = None
    metadata_rejections = 0
    for candidate in candidates:
        source_paths = [candidate / name for name in payload_names]
        source_hashes = [sha256_file(path) for path in source_paths]
        result["files_hashed"] += len(source_paths)
        if source_hashes != target_hashes:
            continue
        if not all(metadata_check(source, target) for source, target in zip(source_paths, target_paths)):
            metadata_rejections += 1
            continue
        exact_source = candidate
        break
    if exact_source is None:
        status = "SKIPPED_METADATA_INCOMPATIBLE" if metadata_rejections else "NO_EXACT_DUPLICATE"
        return finish(status, "NO_METADATA_COMPATIBLE_EXACT_HISTORICAL_SOURCE")

    result["candidate_group_count"] = 1
    result["source_snapshot"] = str(exact_source)
    source_paths = [exact_source / name for name in payload_names]
    current_pre = [(sha256_file(path), _file_identity(path)) for path in current_paths]
    result["files_hashed"] += len(current_paths)
    if any(_file_identity(current) in {_file_identity(source), _file_identity(target)}
           for current, source, target in zip(current_paths, source_paths, target_paths)):
        result["current_canonical_hardlink_participation_count"] = 1
        result["integrity_anomaly"] = True
        return finish("FAIL_INTEGRITY", "CURRENT_CANONICAL_ALREADY_ALIASED")

    operational_statuses: list[str] = []
    for source, target, expected_hash in zip(source_paths, target_paths, target_hashes):
        if _file_identity(source) == _file_identity(target):
            continue
        if not _exclusive_read_available(source) or not _exclusive_read_available(target):
            result["skipped_file_count"] += 1
            continue
        result["would_convert_file_count"] += 1
        result["would_reclaim_bytes"] += _allocated_size(target)
        if dry_run:
            continue
        if sha256_file(source) != expected_hash or sha256_file(target) != expected_hash:
            result["skipped_file_count"] += 1
            continue
        result["files_hashed"] += 2
        action = transaction(source, target, expected_hash)
        if action.get("status") == "CONVERTED":
            result["converted_file_count"] += 1
            result["physical_bytes_reclaimed"] += int(action.get("bytes_reclaimed", 0))
        elif action.get("status") == "ALREADY_CONVERTED_RECOVERED":
            continue
        elif action.get("status") == "FAIL_INTEGRITY":
            result["integrity_anomaly"] = True
            return finish("FAIL_INTEGRITY", str(action.get("reason", "TRANSACTION_INTEGRITY_FAILURE")))
        else:
            result["skipped_file_count"] += 1
            operational_statuses.append(str(action.get("status", "SKIPPED_OPERATIONAL")))

    if sha256_file(target_manifest) != target_manifest_hash:
        result["integrity_anomaly"] = True
        return finish("FAIL_INTEGRITY", "TARGET_MANIFEST_CHANGED")
    result["files_hashed"] += 1
    if any(not path.exists() or sha256_file(path) != expected for path, expected in zip(target_paths, target_hashes)):
        result["integrity_anomaly"] = True
        return finish("FAIL_INTEGRITY", "TARGET_PAYLOAD_CHANGED_OR_MISSING")
    result["files_hashed"] += len(target_paths)
    current_post = [(sha256_file(path), _file_identity(path)) for path in current_paths]
    result["files_hashed"] += len(current_paths)
    if current_post != current_pre:
        result["current_canonical_hardlink_participation_count"] = 1
        result["integrity_anomaly"] = True
        return finish("FAIL_INTEGRITY", "CURRENT_CANONICAL_CHANGED")
    if dry_run:
        return finish("DRY_RUN_EXACT_DUPLICATE")
    if result["converted_file_count"]:
        status = "PASS" if not result["skipped_file_count"] else "PASS_WITH_OPERATIONAL_SKIPS"
        return finish(status, ",".join(sorted(set(operational_statuses))))
    if not result["skipped_file_count"]:
        return finish("ALREADY_SHARED")
    if "SKIPPED_PERMISSION" in operational_statuses:
        return finish("SKIPPED_PERMISSION", ",".join(sorted(set(operational_statuses))))
    return finish("SKIPPED_OPERATIONAL", ",".join(sorted(set(operational_statuses))))


def python_exe(repo_root: Path) -> str:
    return str(get_python_executable())


def powershell_exe() -> str:
    return "powershell"


def run_subprocess(cmd: list[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    log_path.write_text(
        (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""),
        encoding="utf-8",
    )
    return proc.returncode


def child_summary_path(repo_root: Path, stage: str) -> Path:
    if stage == "V21.231":
        return daily_stage(V231_REL, allow_migrated=False) / "v21_231_summary.json"
    if stage == "V21.232":
        return daily_stage(V232_REL, allow_migrated=False) / "v21_232_summary.json"
    if stage == "V21.233":
        return daily_stage(V233_REL, allow_migrated=False) / "v21_233_summary.json"
    if stage == "V21.234":
        return daily_stage(V234_REL, allow_migrated=False) / "v21_234_summary.json"
    if stage == "V21.256":
        return daily_stage(V256_REL, allow_migrated=False) / "v21_256_summary.json"
    raise ValueError(stage)


def log_path(out: Path, stage: str) -> Path:
    return out / f"{stage.lower().replace('.', '_')}_execute.log"


def child_command(repo_root: Path, stage: str, target_date: str | None, cache_root: Path | None, no_network: bool) -> list[str]:
    if stage == "V21.231":
        cmd = [
            python_exe(repo_root),
            str(repo_root / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"),
            "--repo-root", str(repo_root),
            "--output-dir", str(daily_stage(V231_REL, allow_migrated=False)),
            "--end-date", str(target_date or ""),
        ]
        if cache_root is not None:
            cmd.extend(["--cache-root", str(cache_root)])
        if no_network:
            cmd.append("--no-network")
        return cmd
    wrappers = {
        "V21.232": repo_root / "scripts/v21/run_v21_232_moomoo_only_dram_daily_and_intraday_plan.ps1",
        "V21.233": repo_root / "scripts/v21/run_v21_233_moomoo_only_abcde_rerun.ps1",
        "V21.234": repo_root / "scripts/v21/run_v21_234_minimal_moomoo_only_daily_research_chain.ps1",
        "V21.256": repo_root / "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1",
    }
    cmd = [powershell_exe(), "-ExecutionPolicy", "Bypass", "-File", str(wrappers[stage])]
    if stage == "V21.256":
        cmd.extend(["-RepoRoot", str(repo_root), "-Execute"])
    return cmd


def running_summary(repo_root: Path, out: Path, target_date: str, run_start_utc: str) -> dict[str, Any]:
    return {
        "target_date": target_date,
        "revision": "V22.040_R1A",
        "latest_available_date": "",
        "canonical_snapshot_id": "",
        "canonical_latest_date": "",
        "abcde_latest_date": "",
        "dram_latest_price_date": "",
        "same_date_comparable_all_strategies": False,
        "canonical_complete_universe_date": "",
        "target_date_ticker_count": 0,
        "expected_universe_count": 0,
        "legally_excluded_count": 0,
        "eligible_universe_count": 0,
        "target_date_coverage_ratio": 0.0,
        "gross_target_date_coverage_ratio": 0.0,
        "eligible_target_date_coverage_ratio": 0.0,
        "stale_ticker_count": 0,
        "excluded_ticker_count": 0,
        "missing_target_date_tickers": [],
        "raw_qfq_ticker_set_exact_match": False,
        "raw_qfq_target_date_ticker_set_exact_match": False,
        "data_gap_days": 0,
        "final_status": RUNNING_STATUS,
        "final_decision": RUNNING_DECISION,
        "repo_root": str(repo_root),
        "output_dir": str(out),
        "run_start_utc": run_start_utc,
        "last_heartbeat_utc": run_start_utc,
        "last_completed_stage": "STARTED",
        "current_stage": "INITIALIZING",
        "stage_attempted": False,
        "child_exit_codes": {},
        "child_summary_paths": {},
        "child_final_statuses": {},
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_attempted": False,
        "canonical_pointer_updated": False,
        "post_supersession_dedup_enabled": True,
        "post_supersession_dedup_status": "NOT_RUN",
        "post_supersession_dedup_source_snapshot": "",
        "post_supersession_dedup_target_snapshot": "",
        "post_supersession_dedup_converted_file_count": 0,
        "post_supersession_dedup_physical_bytes_reclaimed": 0,
        "post_supersession_dedup_skipped_file_count": 0,
        "post_supersession_dedup_reason": "",
        "post_supersession_dedup_files_hashed": 0,
        "post_supersession_dedup_duration_ms": 0.0,
        "post_supersession_dedup_integrity_anomaly": False,
        "abcde_rerun_succeeded": False,
        "dram_rerun_succeeded": False,
        "research_only": True,
        "warning_count": 0,
        "error_count": 0,
    }


def persist_summary(out: Path, summary: dict[str, Any]) -> None:
    write_json_atomic(out / "v22_040_summary.json", summary)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]
    except Exception:
        return []


def date_key(value: str) -> str:
    return str(value or "")[:10]


def csv_stats(path: Path) -> dict[str, Any]:
    rows = read_csv_rows(path)
    dates = [date_key(row.get("date", "")) for row in rows if date_key(row.get("date", ""))]
    tickers = {row.get("ticker", "") for row in rows if row.get("ticker")}
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "ticker_count": len(tickers),
        "max_date": max(dates) if dates else "",
        "rows": rows,
    }


def approved_exclusions(v231_dir: Path, target_date: str) -> set[str]:
    """Only a recorded, explicit exclusion can reduce the ABCDE universe."""
    rows = read_csv_rows(v231_dir / "abcde_daily_exclusion_ledger.csv") or read_csv_rows(v231_dir / "abcde_exclusion_ledger.csv")
    return {r.get("ticker", "") for r in rows if r.get("ticker") and (r.get("allowed", "").lower() == "true" or r.get("status", "").upper() in {"APPROVED", "VALID", "ACTIVE"}) and (not str(r.get("effective_date") or r.get("target_date") or "")[:10] or str(r.get("effective_date") or r.get("target_date") or "")[:10] <= target_date)}


def expected_universe(v231_dir: Path, raw: dict[str, Any], qfq: dict[str, Any]) -> set[str]:
    # The immutable planned-universe manifest is authoritative.  The coverage
    # ledger records a fetch outcome and must never shrink the required pool.
    manifest = read_csv_rows(v231_dir / "abcde_expected_universe.csv")
    planned_manifest = {r.get("ticker", "") for r in manifest if r.get("ticker")}
    if planned_manifest:
        return planned_manifest
    ledger = read_csv_rows(v231_dir / "ticker_coverage_audit.csv")
    planned = {r.get("ticker", "") for r in ledger if r.get("ticker")}
    return planned or ({r.get("ticker", "") for r in raw["rows"] + qfq["rows"] if r.get("ticker")})


def snapshot_coverage(raw: dict[str, Any], qfq: dict[str, Any], expected: set[str], exclusions: list[dict[str, Any]]) -> dict[str, Any]:
    raw_set = {r.get("ticker", "") for r in raw["rows"] if r.get("ticker")}
    qfq_set = {r.get("ticker", "") for r in qfq["rows"] if r.get("ticker")}
    target = raw["max_date"]
    excluded = ({r.get("ticker", "") for r in exclusions if r.get("ticker") and (r.get("allowed", "").lower() == "true" or r.get("status", "").upper() in {"APPROVED", "VALID", "ACTIVE"}) and (not str(r.get("effective_date") or r.get("target_date") or "")[:10] or str(r.get("effective_date") or r.get("target_date") or "")[:10] <= target)} & expected)
    usable = expected - excluded
    # A complete-universe date means every usable ticker has that date in both views.
    common_dates = sorted({date_key(r.get("date", "")) for r in raw["rows"] if r.get("ticker") in usable} & {date_key(r.get("date", "")) for r in qfq["rows"] if r.get("ticker") in usable}, reverse=True)
    complete_date = ""
    for candidate in common_dates:
        raw_at = {r.get("ticker", "") for r in raw["rows"] if date_key(r.get("date", "")) == candidate}
        qfq_at = {r.get("ticker", "") for r in qfq["rows"] if date_key(r.get("date", "")) == candidate}
        if usable <= raw_at and usable <= qfq_at:
            complete_date = candidate
            break
    raw_target = {r.get("ticker", "") for r in raw["rows"] if date_key(r.get("date", "")) == target}
    qfq_target = {r.get("ticker", "") for r in qfq["rows"] if date_key(r.get("date", "")) == target}
    missing = sorted((usable - raw_target) | (usable - qfq_target))
    return {"expected_universe": expected, "excluded": excluded, "usable": usable, "raw_set": raw_set, "qfq_set": qfq_set,
            "complete_date": complete_date, "target_date": target, "raw_target": raw_target, "qfq_target": qfq_target,
            "missing": missing, "target_count": len(raw_target & qfq_target & usable),
            "gross_ratio": len(raw_target & qfq_target & usable) / len(expected) if expected else 0.0,
            "eligible_ratio": len(raw_target & qfq_target & usable) / len(usable) if usable else 0.0}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_stage_runner(stage: str, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    code = run_subprocess(child_command(repo_root, stage, None, None, False), repo_root, log_path(daily_stage(OUT_REL, allow_migrated=False), stage))
    summary_path = child_summary_path(repo_root, stage)
    summary = read_json(summary_path)
    summary["_exit_code"] = code
    summary["_summary_path"] = str(summary_path)
    return summary


def run_fetch_stage(
    repo_root: Path,
    output_dir: Path,
    target_date: str | None,
    cache_root: Path | None,
    no_network: bool,
    fetch_runner: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    if fetch_runner is not None:
        return fetch_runner(repo_root=repo_root, target_date=target_date, cache_root=cache_root, no_network=no_network)
    code = run_subprocess(
        child_command(repo_root, "V21.231", target_date, cache_root, no_network),
        repo_root,
        log_path(output_dir, "V21.231"),
    )
    summary_path = child_summary_path(repo_root, "V21.231")
    summary = read_json(summary_path)
    summary["_exit_code"] = code
    summary["_summary_path"] = str(summary_path)
    return summary


def candidate_dirs(repo_root: Path, cache_root: Path, v231_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    pointer = read_json(v231_dir / "canonical_snapshot_pointer.json")
    for raw in [pointer.get("canonical_snapshot_dir"), read_json(v231_dir / "v21_231_summary.json").get("canonical_snapshot_dir")]:
        if raw:
            path = Path(raw)
            if path.exists() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    canonical_root = cache_root / "canonical/moomoo_ohlcv"
    if canonical_root.exists():
        for path in sorted(canonical_root.glob("snapshot_id=*")):
            if path.is_dir() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    local_root = repo_root / "cache/canonical/moomoo_ohlcv"
    if local_root.exists():
        for path in sorted(local_root.glob("snapshot_id=*")):
            if path.is_dir() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    return out


def complete_candidates(repo_root: Path, cache_root: Path, v231_dir: Path) -> list[dict[str, Any]]:
    rows = []
    v231_summary = read_json(v231_dir / "v21_231_summary.json")
    for index, directory in enumerate(candidate_dirs(repo_root, cache_root, v231_dir)):
        raw_path = directory / CANON_RAW
        qfq_path = directory / CANON_QFQ
        raw = csv_stats(raw_path)
        qfq = csv_stats(qfq_path)
        exclusions = read_csv_rows(v231_dir / "abcde_daily_exclusion_ledger.csv") or read_csv_rows(v231_dir / "abcde_exclusion_ledger.csv")
        cov = snapshot_coverage(raw, qfq, expected_universe(v231_dir, raw, qfq), exclusions)
        target = raw["max_date"]
        complete = raw["exists"] and qfq["exists"] and raw["row_count"] > 0 and qfq["row_count"] > 0 and raw["max_date"] == qfq["max_date"] and cov["raw_set"] == cov["qfq_set"] and bool(cov["complete_date"])
        rows.append({
            "snapshot_id": directory.name.replace("snapshot_id=", ""),
            "canonical_snapshot_dir": str(directory),
            "raw_path": str(raw_path),
            "qfq_path": str(qfq_path),
            "raw_max_date": raw["max_date"],
            "qfq_max_date": qfq["max_date"],
            "raw_row_count": raw["row_count"],
            "qfq_row_count": qfq["row_count"],
            "raw_ticker_count": raw["ticker_count"],
            "qfq_ticker_count": qfq["ticker_count"],
            "expected_universe_count": len(cov["expected_universe"]),
            "excluded_ticker_count": len(cov["excluded"]),
            "legally_excluded_count": len(cov["excluded"]),
            "eligible_universe_count": len(cov["usable"]),
            "target_date_ticker_count": cov["target_count"],
            "target_date_coverage_ratio": len(cov["usable"] & cov["raw_target"] & cov["qfq_target"]) / len(cov["usable"]) if cov["usable"] else 0.0,
            "gross_target_date_coverage_ratio": cov["gross_ratio"],
            "eligible_target_date_coverage_ratio": cov["eligible_ratio"],
            "stale_ticker_count": len(cov["missing"]),
            "missing_target_date_tickers": cov["missing"],
            "raw_qfq_ticker_set_exact_match": cov["raw_set"] == cov["qfq_set"],
            "raw_qfq_target_date_ticker_set_exact_match": cov["raw_target"] == cov["qfq_target"],
            "canonical_complete_universe_date": cov["complete_date"],
            "complete": complete and cov["raw_target"] == cov["qfq_target"],
        })
        # A just-completed V21.231 pointer already carries a full-universe
        # coverage proof.  Prefer it directly instead of re-parsing every
        # immutable historical CSV; fall back to the full scan for stale or
        # incomplete pointers (including repair scenarios).
        if (index == 0 and rows[-1]["complete"] and v231_summary.get("final_status", "").startswith("PASS")
                and v231_summary.get("canonical_complete_universe_date") == raw["max_date"]
                and int(v231_summary.get("stale_ticker_count", -1)) == 0):
            return rows
    return rows


def select_latest_complete(candidates: list[dict[str, Any]], target_date: str | None) -> dict[str, Any]:
    complete = [row for row in candidates if row["complete"]]
    if not complete:
        raise RuntimeError("NO_COMPLETE_CANONICAL_SNAPSHOT_CANDIDATE")
    if target_date:
        exact = [row for row in complete if row["raw_max_date"] == target_date and row["stale_ticker_count"] == 0]
        if exact:
            return sorted(exact, key=lambda r: (r["raw_max_date"], r["snapshot_id"]))[-1]
        partial = [row for row in candidates if row["raw_max_date"] == target_date]
        if partial:
            missing = sorted({ticker for row in partial for ticker in row["missing_target_date_tickers"]})
            raise RuntimeError(f"TARGET_DATE_UNIVERSE_INCOMPLETE:{target_date}:stale_ticker_count={len(missing)}:missing_target_date_tickers={','.join(missing)}")
    return sorted(complete, key=lambda r: (r["raw_max_date"], r["snapshot_id"]))[-1]


def promote_snapshot(cache_root: Path, selected: dict[str, Any]) -> tuple[str, Path]:
    snapshot_id = "v22_040_promoted_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target_dir = cache_root / "canonical/moomoo_ohlcv" / f"snapshot_id={snapshot_id}"
    target_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(selected["raw_path"], target_dir / CANON_RAW)
    shutil.copy2(selected["qfq_path"], target_dir / CANON_QFQ)
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at_utc": utc_now(),
        "promoted_from_snapshot_id": selected["snapshot_id"],
        "canonical_raw_path": str(target_dir / CANON_RAW),
        "canonical_qfq_path": str(target_dir / CANON_QFQ),
        "latest_date": selected["raw_max_date"],
    }
    write_json_atomic(target_dir / "canonical_manifest.json", manifest)
    return snapshot_id, target_dir


def pointer_payload(cache_root: Path, snapshot_id: str, canonical_dir: Path, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "policy_version": "V21.231",
        "snapshot_id": snapshot_id,
        "created_at_utc": utc_now(),
        "cache_root": str(cache_root),
        "canonical_snapshot_dir": str(canonical_dir),
        "canonical_raw_path": str(canonical_dir / CANON_RAW),
        "canonical_qfq_path": str(canonical_dir / CANON_QFQ),
        "canonical_manifest_path": str(canonical_dir / "canonical_manifest.json"),
        "source_policy": "MOOMOO_ONLY",
        "source": "MOOMOO_OPEND",
        "yfinance_used": False,
        "yahoo_used": False,
        "external_fallback_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    if coverage:
        payload.update({k: coverage[k] for k in ["expected_universe_count", "excluded_ticker_count", "legally_excluded_count", "eligible_universe_count", "target_date_ticker_count", "target_date_coverage_ratio", "gross_target_date_coverage_ratio", "eligible_target_date_coverage_ratio", "stale_ticker_count", "missing_target_date_tickers", "raw_qfq_ticker_set_exact_match", "raw_qfq_target_date_ticker_set_exact_match", "canonical_complete_universe_date"]})
    return payload


def update_v231_pointer(v231_dir: Path, pointer: dict[str, Any]) -> None:
    write_json_atomic(v231_dir / "canonical_snapshot_pointer.json", pointer)
    write_csv_atomic(v231_dir / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], POINTER_FIELDS)


def validate_pointer(pointer: dict[str, Any], v231_dir: Path | None = None) -> dict[str, Any]:
    raw_path = Path(pointer.get("canonical_raw_path", ""))
    qfq_path = Path(pointer.get("canonical_qfq_path", ""))
    raw = csv_stats(raw_path)
    qfq = csv_stats(qfq_path)
    expected = expected_universe(v231_dir, raw, qfq) if v231_dir else {r.get("ticker", "") for r in raw["rows"] + qfq["rows"] if r.get("ticker")}
    exclusions = read_csv_rows(v231_dir / "abcde_daily_exclusion_ledger.csv") or read_csv_rows(v231_dir / "abcde_exclusion_ledger.csv") if v231_dir else []
    cov = snapshot_coverage(raw, qfq, expected, exclusions) if raw["exists"] and qfq["exists"] else snapshot_coverage(raw, qfq, set(), [])
    ok = raw["exists"] and qfq["exists"] and raw["row_count"] > 0 and qfq["row_count"] > 0 and raw["max_date"] == qfq["max_date"] and cov["raw_set"] == cov["qfq_set"] and bool(cov["complete_date"])
    return {
        "ok": ok,
        "raw": raw,
        "qfq": qfq,
        "canonical_latest_date": cov["complete_date"],
        "coverage": cov,
        "pointer_expected_universe_count": len(cov["expected_universe"]),
        "pointer_eligible_universe_count": len(cov["usable"]),
        "pointer_raw_target_date_ticker_count": len(cov["raw_target"] & cov["usable"]),
        "pointer_qfq_target_date_ticker_count": len(cov["qfq_target"] & cov["usable"]),
        "pointer_missing_eligible_raw_tickers": sorted(cov["usable"] - cov["raw_target"]),
        "pointer_missing_eligible_qfq_tickers": sorted(cov["usable"] - cov["qfq_target"]),
    }


def days_gap(target_date: str | None, latest_available: str) -> int:
    if not target_date or not latest_available:
        return 0
    try:
        return (date.fromisoformat(target_date) - date.fromisoformat(latest_available)).days
    except ValueError:
        return 0


def permission_ok(*summaries: dict[str, Any]) -> bool:
    for summary in summaries:
        if summary.get("broker_action_allowed") is not False:
            return False
        if summary.get("official_adoption_allowed") is not False:
            return False
        if summary.get("trade_allowed") is True or summary.get("trade_unlock_used") is True:
            return False
    return True


def run(
    repo_root: Path,
    output_dir: Path | None = None,
    target_date: str | None = None,
    cache_root: Path | None = None,
    no_network: bool = False,
    run_id: str = "",
    fetch_runner: Callable[..., dict[str, Any]] | None = None,
    stage_runner: StageRunner | None = None,
    dedup_runner: DedupRunner | None = None,
    post_supersession_dedup_enabled: bool = True,
) -> dict[str, Any]:
    global _RUNTIME_REPO
    repo_root = repo_root.resolve()
    _RUNTIME_REPO = repo_root
    out = output_dir or daily_stage(OUT_REL, allow_migrated=False)
    assert_safe_output_path(out)
    out.mkdir(parents=True, exist_ok=True)
    target_date = target_date or latest_expected_completed_us_trading_date()
    v231_dir = daily_stage(V231_REL)
    run_start = time.perf_counter()
    run_start_utc = utc_now()
    summary = running_summary(repo_root, out, target_date, run_start_utc)
    summary["post_supersession_dedup_enabled"] = post_supersession_dedup_enabled
    summary["run_id"] = run_id
    persist_summary(out, summary)
    stage_ledger: list[dict[str, Any]] = []
    failed_stage = ""
    forced_fail_status = ""
    market_data_fetch_attempted = False

    def before_stage(stage: str) -> None:
        nonlocal market_data_fetch_attempted
        summary["current_stage"] = stage
        summary["last_heartbeat_utc"] = utc_now()
        summary["stage_attempted"] = True
        if stage == "V21.231":
            market_data_fetch_attempted = True
            summary["market_data_fetch_attempted"] = True
        persist_summary(out, summary)

    def after_stage(stage: str, child_summary: dict[str, Any], exit_code: int) -> None:
        child_path = child_summary_path(repo_root, stage)
        child_status = child_summary.get("final_status", "")
        summary["last_completed_stage"] = stage
        summary["last_heartbeat_utc"] = utc_now()
        summary["child_exit_codes"][stage] = exit_code
        summary["child_summary_paths"][stage] = str(child_path)
        summary["child_final_statuses"][stage] = child_status
        stage_ledger.append({
            "stage_name": stage,
            "attempted": True,
            "succeeded": exit_code == 0 and not str(child_status).startswith("FAIL"),
            "final_status": child_status,
            "notes": "child stage completed",
        })
        persist_summary(out, summary)

    def execute_stage(stage: str) -> dict[str, Any]:
        before_stage(stage)
        if stage == "V21.231":
            child_summary = run_fetch_stage(repo_root, out, target_date, cache_root, no_network, fetch_runner)
        elif stage_runner is not None:
            child_summary = stage_runner(stage, repo_root, {
                "V21.232": daily_stage(V232_REL, allow_migrated=False),
                "V21.233": daily_stage(V233_REL, allow_migrated=False),
                "V21.234": daily_stage(V234_REL, allow_migrated=False),
                "V21.256": daily_stage(V256_REL, allow_migrated=False),
            }[stage])
        else:
            exit_code = run_subprocess(child_command(repo_root, stage, target_date, cache_root, no_network), repo_root, log_path(out, stage))
            child_summary = read_json(child_summary_path(repo_root, stage))
            child_summary["_exit_code"] = exit_code
            child_summary["_summary_path"] = str(child_summary_path(repo_root, stage))
        exit_code = int(child_summary.get("_exit_code", 0) or 0)
        summary_path = child_summary_path(repo_root, stage)
        disk_summary = read_json(summary_path)
        if not disk_summary:
            nonlocal_failed[0] = stage
            nonlocal_forced[0] = FAIL_CHILD_SUMMARY_MISSING
            after_stage(stage, child_summary, exit_code)
            raise RuntimeError(f"CHILD_SUMMARY_MISSING:{stage}:{summary_path}")
        child_summary = {**disk_summary, **{k: v for k, v in child_summary.items() if k.startswith("_")}}
        if stage == "V21.231":
            summary.update({
                "child_failure_category": child_summary.get("failure_category", ""),
                "child_failure_reason": child_summary.get("failure_reason", ""),
                "child_expected_universe_count": child_summary.get("expected_universe_count", 0),
                "child_eligible_universe_count": child_summary.get("eligible_universe_count", 0),
                "child_target_date_ticker_count": child_summary.get("target_date_ticker_count", 0),
                "child_missing_target_date_tickers": child_summary.get("missing_target_date_tickers", []),
                "child_unresolved_api_error_count": child_summary.get("unresolved_api_error_count", 0),
            })
        after_stage(stage, child_summary, exit_code)
        if exit_code != 0:
            nonlocal_failed[0] = stage
            nonlocal_forced[0] = FAIL_CHILD_NONZERO
            raise RuntimeError(f"CHILD_NONZERO_EXIT:{stage}:{exit_code}")
        return child_summary

    nonlocal_failed = [""]
    nonlocal_forced = [""]

    try:
        # Bootstrap only if protected, validated prerequisites are unavailable.
        # This runs before V21.231 and cannot mutate canonical current data.
        if repo_root == default_repo_root().resolve():
            ensure_prerequisites(repo_root)
            preflight = live_preflight()
            summary["live_preflight"] = preflight
            if preflight["live_preflight_status"] != "PASS_V21_230_R1_LIVE_PREFLIGHT":
                raise RuntimeError(preflight["live_preflight_status"] + ":" + preflight.get("error_message", ""))
        if cache_root is None:
            cache_root = get_cache_root()
        # V21.231 writes its own fresh pointer, so the just-superseded identity
        # must be captured before that child runs.
        pre_refresh_pointer = read_json(v231_dir / "canonical_snapshot_pointer.json")
        fetch_summary = execute_stage("V21.231")
        if str(fetch_summary.get("final_status", "")).startswith("FAIL"):
            nonlocal_failed[0] = "V21.231"
            raise RuntimeError(f"V21_231_FETCH_STAGE_FAILED:{fetch_summary.get('final_status')}")
        pointer_before = read_json(v231_dir / "canonical_snapshot_pointer.json")
        effective_cache_root = Path(cache_root or pointer_before.get("cache_root") or fetch_summary.get("cache_root") or (repo_root / "cache"))
        candidates = complete_candidates(repo_root, effective_cache_root, v231_dir)
        selected = select_latest_complete(candidates, target_date)
        warning = WARN_TARGET if selected["raw_max_date"] != target_date else ""
        promoted_id, promoted_dir = promote_snapshot(effective_cache_root, selected)
        pointer = pointer_payload(effective_cache_root, promoted_id, promoted_dir, selected)
        update_v231_pointer(v231_dir, pointer)
        canonical_pointer_updated = True
        validation = validate_pointer(pointer, v231_dir)
        if not validation["ok"]:
            raise RuntimeError("PROMOTED_CANONICAL_POINTER_VALIDATION_FAILED")
        if post_supersession_dedup_enabled:
            previous_value = str(pre_refresh_pointer.get("canonical_snapshot_dir", ""))
            previous_dir = Path(previous_value) if previous_value else Path()
            if not previous_value:
                dedup_result: dict[str, Any] = {
                    "status": "SKIPPED_NO_PREVIOUS_CURRENT",
                    "reason": "PRE_REFRESH_POINTER_MISSING",
                }
            else:
                try:
                    dedup_result = (dedup_runner or dedup_superseded_snapshot)(
                        superseded_snapshot=previous_dir,
                        historical_root=effective_cache_root / "canonical/moomoo_ohlcv",
                        current_snapshot=promoted_dir,
                        dry_run=False,
                    )
                except BaseException as dedup_exc:
                    # Storage closeout is operationally isolated from the
                    # already committed canonical promotion.
                    dedup_result = {
                        "status": "SKIPPED_OPERATIONAL_EXCEPTION",
                        "reason": f"{type(dedup_exc).__name__}:{dedup_exc}",
                        "integrity_anomaly": False,
                    }
            summary.update({
                "post_supersession_dedup_status": dedup_result.get("status", "UNKNOWN"),
                "post_supersession_dedup_source_snapshot": dedup_result.get("source_snapshot", ""),
                "post_supersession_dedup_target_snapshot": previous_value,
                "post_supersession_dedup_converted_file_count": int(dedup_result.get("converted_file_count", 0)),
                "post_supersession_dedup_physical_bytes_reclaimed": int(dedup_result.get("physical_bytes_reclaimed", 0)),
                "post_supersession_dedup_skipped_file_count": int(dedup_result.get("skipped_file_count", 0)),
                "post_supersession_dedup_reason": str(dedup_result.get("reason", "")),
                "post_supersession_dedup_files_hashed": int(dedup_result.get("files_hashed", 0)),
                "post_supersession_dedup_duration_ms": float(dedup_result.get("duration_ms", 0.0)),
                "post_supersession_dedup_integrity_anomaly": bool(dedup_result.get("integrity_anomaly", False)),
            })
        else:
            summary["post_supersession_dedup_status"] = "DISABLED"
        summary.update({
            "latest_available_date": selected["raw_max_date"],
            "canonical_snapshot_id": promoted_id,
            "canonical_latest_date": validation["canonical_latest_date"],
            "data_gap_days": max(days_gap(target_date, selected["raw_max_date"]), 0),
            "canonical_pointer_updated": True,
            "raw_row_count": validation["raw"]["row_count"],
            "raw_ticker_count": validation["raw"]["ticker_count"],
            "qfq_row_count": validation["qfq"]["row_count"],
            "qfq_ticker_count": validation["qfq"]["ticker_count"],
            "qfq_raw_max_date_equal": validation["raw"]["max_date"] == validation["qfq"]["max_date"],
            "canonical_raw_path_exists": validation["raw"]["exists"],
            "canonical_qfq_path_exists": validation["qfq"]["exists"],
            "expected_universe_count": selected["expected_universe_count"],
            "legally_excluded_count": selected["legally_excluded_count"],
            "eligible_universe_count": selected["eligible_universe_count"],
            "target_date_ticker_count": selected["target_date_ticker_count"],
            "target_date_coverage_ratio": selected["target_date_coverage_ratio"],
            "gross_target_date_coverage_ratio": selected["gross_target_date_coverage_ratio"],
            "eligible_target_date_coverage_ratio": selected["eligible_target_date_coverage_ratio"],
            "stale_ticker_count": selected["stale_ticker_count"],
            "excluded_ticker_count": selected["excluded_ticker_count"],
            "missing_target_date_tickers": selected["missing_target_date_tickers"],
            "raw_qfq_ticker_set_exact_match": selected["raw_qfq_ticker_set_exact_match"],
            "raw_qfq_target_date_ticker_set_exact_match": selected["raw_qfq_target_date_ticker_set_exact_match"],
            "canonical_complete_universe_date": selected["canonical_complete_universe_date"],
            "pointer_expected_universe_count": validation["pointer_expected_universe_count"],
            "pointer_eligible_universe_count": validation["pointer_eligible_universe_count"],
            "pointer_raw_target_date_ticker_count": validation["pointer_raw_target_date_ticker_count"],
            "pointer_qfq_target_date_ticker_count": validation["pointer_qfq_target_date_ticker_count"],
            "pointer_missing_eligible_raw_tickers": validation["pointer_missing_eligible_raw_tickers"],
            "pointer_missing_eligible_qfq_tickers": validation["pointer_missing_eligible_qfq_tickers"],
        })
        persist_summary(out, summary)

        s232 = execute_stage("V21.232")
        s233 = execute_stage("V21.233")
        s234 = execute_stage("V21.234")
        s256 = execute_stage("V21.256")

        abcde_latest = str(s233.get("canonical_latest_date", ""))
        dram_latest = str(s232.get("latest_price_date", ""))
        canonical_latest = validation["canonical_latest_date"]
        same_date = abcde_latest == canonical_latest and dram_latest == canonical_latest and str(s233.get("same_date_comparable_all_strategies", "")).lower() in {"true", "1"}
        abcde_ok = not str(s233.get("final_status", "")).startswith("FAIL") and abcde_latest == canonical_latest
        dram_ok = not str(s232.get("final_status", "")).startswith("FAIL") and dram_latest == canonical_latest
        wrappers_ok = all(not str(s.get("final_status", "")).startswith("FAIL") for s in [s234, s256])
        gates_ok = permission_ok(fetch_summary, s232, s233, s234, s256)
        final_status = PASS_STATUS
        final_decision = DECISION_READY
        error_count = 0
        warning_count = 1 if warning else 0
        if not (abcde_ok and dram_ok and wrappers_ok and same_date and gates_ok):
            final_status = FAIL_STATUS
            final_decision = DECISION_BLOCKED
            error_count = 1
        elif warning:
            final_status = warning
        summary = {
            **summary,
            "revision": "V22.040_R1A",
            "target_date": target_date,
            "latest_available_date": selected["raw_max_date"],
            "canonical_snapshot_id": promoted_id,
            "canonical_latest_date": canonical_latest,
            "abcde_latest_date": abcde_latest,
            "dram_latest_price_date": dram_latest,
            "same_date_comparable_all_strategies": same_date,
            "data_gap_days": max(days_gap(target_date, selected["raw_max_date"]), 0),
            "final_status": final_status,
            "final_decision": final_decision,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "market_data_fetch_attempted": market_data_fetch_attempted,
            "canonical_pointer_updated": canonical_pointer_updated,
            "abcde_rerun_succeeded": abcde_ok,
            "dram_rerun_succeeded": dram_ok,
            "warning_code": warning,
            "raw_row_count": validation["raw"]["row_count"],
            "raw_ticker_count": validation["raw"]["ticker_count"],
            "qfq_row_count": validation["qfq"]["row_count"],
            "qfq_ticker_count": validation["qfq"]["ticker_count"],
            "qfq_raw_max_date_equal": validation["raw"]["max_date"] == validation["qfq"]["max_date"],
            "canonical_raw_path_exists": validation["raw"]["exists"],
            "canonical_qfq_path_exists": validation["qfq"]["exists"],
            "expected_universe_count": selected["expected_universe_count"],
            "legally_excluded_count": selected["legally_excluded_count"],
            "eligible_universe_count": selected["eligible_universe_count"],
            "target_date_ticker_count": selected["target_date_ticker_count"],
            "target_date_coverage_ratio": selected["target_date_coverage_ratio"],
            "gross_target_date_coverage_ratio": selected["gross_target_date_coverage_ratio"],
            "eligible_target_date_coverage_ratio": selected["eligible_target_date_coverage_ratio"],
            "stale_ticker_count": selected["stale_ticker_count"],
            "excluded_ticker_count": selected["excluded_ticker_count"],
            "missing_target_date_tickers": selected["missing_target_date_tickers"],
            "raw_qfq_ticker_set_exact_match": selected["raw_qfq_ticker_set_exact_match"],
            "raw_qfq_target_date_ticker_set_exact_match": selected["raw_qfq_target_date_ticker_set_exact_match"],
            "canonical_complete_universe_date": selected["canonical_complete_universe_date"],
            "research_only": True,
            "warning_count": warning_count,
            "error_count": error_count,
            "current_stage": "COMPLETE",
            "run_end_utc": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - run_start, 3),
        }
    except BaseException as exc:
        failed_stage = nonlocal_failed[0] or summary.get("current_stage", "")
        forced_fail_status = nonlocal_forced[0]
        summary = {
            **summary,
            "revision": "V22.040_R1A",
            "target_date": target_date,
            "latest_available_date": summary.get("latest_available_date", ""),
            "canonical_snapshot_id": summary.get("canonical_snapshot_id", ""),
            "canonical_latest_date": summary.get("canonical_latest_date", ""),
            "abcde_latest_date": summary.get("abcde_latest_date", ""),
            "dram_latest_price_date": summary.get("dram_latest_price_date", ""),
            "same_date_comparable_all_strategies": summary.get("same_date_comparable_all_strategies", False),
            "data_gap_days": summary.get("data_gap_days", 0),
            "final_status": forced_fail_status or FAIL_STATUS,
            "final_decision": DECISION_BLOCKED,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "market_data_fetch_attempted": market_data_fetch_attempted,
            "canonical_pointer_updated": bool(summary.get("canonical_pointer_updated", False)),
            "abcde_rerun_succeeded": False,
            "dram_rerun_succeeded": False,
            "exception_type": type(exc).__name__,
            "error_message": str(exc),
            "exception_message": str(exc),
            "failed_stage": failed_stage,
            "run_end_utc": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - run_start, 3),
            "research_only": True,
            "warning_count": 0,
            "error_count": 1,
        }

    write_json_atomic(out / "v22_040_summary.json", summary)
    write_csv(out / "v22_040_stage_ledger.csv", stage_ledger, ["stage_name", "attempted", "succeeded", "final_status", "notes"])
    write_csv(out / "v22_040_final_summary.csv", [{"key": k, "value": v} for k, v in summary.items()], ["key", "value"])
    report_keys = [
        "target_date", "latest_available_date", "canonical_snapshot_id", "canonical_latest_date",
        "abcde_latest_date", "dram_latest_price_date", "same_date_comparable_all_strategies", "canonical_complete_universe_date", "target_date_ticker_count", "expected_universe_count", "legally_excluded_count", "eligible_universe_count", "stale_ticker_count", "gross_target_date_coverage_ratio", "eligible_target_date_coverage_ratio", "excluded_ticker_count", "missing_target_date_tickers",
        "data_gap_days", "final_status", "final_decision", "broker_action_allowed",
        "official_adoption_allowed", "market_data_fetch_attempted", "canonical_pointer_updated",
        "post_supersession_dedup_status", "post_supersession_dedup_converted_file_count",
        "post_supersession_dedup_physical_bytes_reclaimed", "post_supersession_dedup_skipped_file_count",
        "post_supersession_dedup_reason", "post_supersession_dedup_integrity_anomaly",
        "abcde_rerun_succeeded", "dram_rerun_succeeded",
    ]
    (out / "V22.040_daily_moomoo_oneclick_refresh_orchestrator_r1_report.txt").write_text(
        "\n".join([STAGE, *[f"{k}={summary.get(k)}" for k in report_keys]]) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--target-date", default=None)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--no-network", action="store_true", default=False)
    parser.add_argument("--path-replay", action="store_true", default=False)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--no-post-supersession-dedup", action="store_true", default=False)
    args = parser.parse_args(argv)
    if args.path_replay:
        v231 = daily_stage(V231_REL) / "v21_231_summary.json"; v233 = daily_stage(V233_REL) / "v21_233_summary.json"
        required = [v231, v233, Path(get_cache_root())]
        missing = [str(p) for p in required if not p.exists()]
        if missing: raise RuntimeError("PATH_REPLAY_MISSING_INPUT:" + ",".join(missing))
        out = get_daily_root() / "validation" / "r2a" / datetime.now().strftime("%Y%m%d_%H%M%S")
        assert_safe_output_path(out); out.mkdir(parents=True, exist_ok=False)
        payload={"final_status":"PASS_V22_040_DAILY_PATH_REPLAY","network_accessed":False,"broker_action_allowed":False,"official_adoption_allowed":False,"promotion_attempted":False,"canonical_write_attempted":False,"v231_summary":str(v231),"v233_summary":str(v233),"output_dir":str(out)}
        write_json_atomic(out / "path_replay_summary.json", payload); print(json.dumps(payload)); return 0
    summary = run(
        args.repo_root,
        args.output_dir,
        args.target_date,
        args.cache_root,
        args.no_network,
        args.run_id,
        post_supersession_dedup_enabled=not args.no_post_supersession_dedup,
    )
    for key in [
        "target_date", "latest_available_date", "canonical_snapshot_id", "canonical_latest_date",
        "abcde_latest_date", "dram_latest_price_date", "same_date_comparable_all_strategies",
        "canonical_complete_universe_date", "target_date_ticker_count", "expected_universe_count", "legally_excluded_count", "eligible_universe_count", "stale_ticker_count", "gross_target_date_coverage_ratio", "eligible_target_date_coverage_ratio", "excluded_ticker_count", "missing_target_date_tickers",
        "data_gap_days", "final_status", "final_decision", "broker_action_allowed",
        "official_adoption_allowed", "market_data_fetch_attempted", "canonical_pointer_updated",
        "post_supersession_dedup_status", "post_supersession_dedup_converted_file_count",
        "post_supersession_dedup_physical_bytes_reclaimed", "post_supersession_dedup_integrity_anomaly",
        "abcde_rerun_succeeded", "dram_rerun_succeeded",
    ]:
        print(f"{key}={summary.get(key)}")
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
