"""Autonomous, reuse-first, worktree-isolated single-task Harness R3."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
import traceback
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence


REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
R1_PREFLIGHT = SCRIPT.with_name("harness_preflight.py")
POLICY = REPO / "configs/anti_bloat_policy.toml"
TERMINAL_STATES = {"STOPPED", "COMPLETED", "COMPLETED_WITH_DEFERRED_WORK", "FAILED"}
ACTIVE_STATES = {"PLANNING", "RUNNING", "PAUSING", "REVIEWING", "STOPPING"}
STATES = {
    "IDLE", "PLANNING", "RUNNING", "PAUSING", "PAUSED", "REVIEWING",
    "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED",
    "COMPLETED_WITH_DEFERRED_WORK", "FAILED",
}
ALLOWED_TRANSITIONS = {
    "IDLE": {"PLANNING", "BLOCKED"},
    "PLANNING": {"RUNNING", "PAUSING", "PAUSED", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "FAILED"},
    "RUNNING": {"PLANNING", "PAUSING", "PAUSED", "REVIEWING", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "COMPLETED_WITH_DEFERRED_WORK", "FAILED"},
    "PAUSING": {"PAUSED", "WAITING_HUMAN", "STOPPING", "FAILED"},
    "PAUSED": {"PLANNING", "RUNNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "REVIEWING": {"RUNNING", "PAUSING", "PAUSED", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "COMPLETED_WITH_DEFERRED_WORK", "FAILED"},
    "WAITING_HUMAN": {"PLANNING", "RUNNING", "REVIEWING", "BLOCKED", "STOPPING", "STOPPED", "FAILED"},
    "BLOCKED": {"PLANNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "STOPPING": {"WAITING_HUMAN", "STOPPED", "FAILED"},
    "STOPPED": {"REVIEWING"},
    "COMPLETED": {"REVIEWING"},
    "COMPLETED_WITH_DEFERRED_WORK": {"REVIEWING"},
    "FAILED": {"REVIEWING", "STOPPING"},
}
MAX_STATE_BYTES = 131_072
MAX_TIMELINE_BYTES = 262_144
MAX_LIST_ITEMS = 100
MAX_TEXT = 8_000
DEFAULT_MAX_CORRECTIONS = 2
DEFAULT_FAILURE_RETRY_LIMIT = 2
DEFAULT_PLANNER_RETRY_LIMIT = 1
MAX_WORK_UNITS = 30
MAX_WORKER_BATCH = 3
WORK_UNIT_STATUSES = {
    "READY", "RUNNING", "DONE", "RETRY", "BLOCKED_LOCAL", "DEFERRED",
    "SKIPPED_WITH_REASON",
}
WORK_UNIT_TERMINAL_STATUSES = {"DONE", "BLOCKED_LOCAL", "DEFERRED", "SKIPPED_WITH_REASON"}
HUMAN_BOUNDARY_KINDS = {
    "AUTHORIZATION", "SAFETY", "DESTRUCTIVE", "PROTECTED_PERMISSION", "PAUSE", "EXHAUSTED",
}
TASK_KIND_SCOPES = {
    "maintenance": "independent-code",
    "independent-code": "independent-code",
    "pre2026-research": "pre2026-research",
    "2026-evaluation": "2026-evaluation",
}
TASK_KINDS = ("auto", *TASK_KIND_SCOPES)
SCOPE_SAFETY_RANK = {
    "independent-code": 0,
    "historical-fetch": 1,
    "pre2026-research": 2,
    "frozen-dependent": 3,
    "2026-evaluation": 4,
    "2026-optimization": 5,
    "all": 6,
}
DEPENDENCY_FILES = {
    "requirements.txt", "requirements.lock.txt", "pyproject.toml", "poetry.lock",
    "pdm.lock", "uv.lock", "environment.yml", "environment.yaml",
}
DISCOVERY_ROOTS = ("scripts", "fast3", "tests", "config", "docs")
DISCOVERY_TEXT_SUFFIXES = {".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml"}
TASK_TEMP_RUNTIME_PREFIX = "harness-runtime-"
TASK_TEMP_OWNER_MARKER = ".harness-runtime-owner.json"
WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION = "WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_WINERROR5"
SUPERVISOR_STARTUP_TIMEOUT_SECONDS = 10.0
SUPERVISOR_STARTUP_POLL_SECONDS = 0.1
SUPERVISOR_BOOTSTRAP_LOG_NAME = "supervisor-bootstrap.stderr.log"
MAX_SUPERVISOR_DIAGNOSTIC_BYTES = 16_384
CONTROLLER_STARTUP_TIMEOUT_SECONDS = 10.0
CONTROLLER_STARTUP_RETRY_LIMIT = 2
CONTROLLER_STARTUP_BACKOFF_SECONDS = 0.5
CONTROLLER_BOOTSTRAP_LOG_NAME = "controller-bootstrap.stderr.log"


class HarnessError(RuntimeError):
    """A fail-closed Harness condition with a concise operator-facing reason."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_r1():
    spec = importlib.util.spec_from_file_location("harness_r1_preflight", R1_PREFLIGHT)
    if spec is None or spec.loader is None:
        raise HarnessError(f"R1_PREFLIGHT_UNAVAILABLE:{R1_PREFLIGHT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _storage_paths():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts.common.storage_paths import resolve

    return resolve(REPO)


def state_root() -> Path:
    override = os.environ.get("USTQ_HARNESS_STATE_ROOT")
    root = Path(override).resolve() if override else (_storage_paths().daily_root / "harness_r2").resolve()
    if REPO == root or REPO in root.parents:
        raise HarnessError(f"STATE_ROOT_INSIDE_REPOSITORY:{root}")
    return root


def worktree_root() -> Path:
    override = os.environ.get("USTQ_HARNESS_WORKTREE_ROOT")
    if override:
        return Path(override).resolve()
    policy = tomllib.loads(POLICY.read_text(encoding="utf-8"))
    value = policy.get("storage", {}).get("worktrees_root")
    if not value:
        raise HarnessError("WORKTREE_ROOT_MISSING_FROM_ANTI_BLOAT_POLICY")
    return Path(value).resolve()


def task_dir(task_id: str) -> Path:
    validate_task_id(task_id)
    return state_root() / "tasks" / task_id


def task_temp_runtime(task_id: str) -> Path:
    """Return the task-owned disposable runtime beside, never inside, worktrees."""
    validate_task_id(task_id)
    root = worktree_root().resolve()
    runtime = (root / f"{TASK_TEMP_RUNTIME_PREFIX}{task_id}").resolve(strict=False)
    if runtime.parent != root:
        raise HarnessError(f"WORKER_TEMP_RUNTIME_NOT_TASK_SCOPED:{runtime}")
    paths = _storage_paths()
    protected = {
        REPO.resolve(), paths.data_root.resolve(), paths.cache_root.resolve(),
        paths.daily_root.resolve(), paths.backtest_root.resolve(),
        paths.results_root.resolve(), paths.envs_root.resolve(),
    }
    for protected_root in protected:
        if runtime == protected_root or protected_root in runtime.parents:
            raise HarnessError(f"WORKER_TEMP_RUNTIME_PROTECTED_ROOT:{runtime}:{protected_root}")
    return runtime


def state_path(task_id: str) -> Path:
    return task_dir(task_id) / "state.json"


def timeline_path(task_id: str) -> Path:
    return task_dir(task_id) / "timeline.jsonl"


def supervisor_bootstrap_log_path(task_id: str) -> Path:
    """Keep bootstrap diagnostics with compact external task state, not source/runtime."""
    return task_dir(task_id) / SUPERVISOR_BOOTSTRAP_LOG_NAME


def controller_bootstrap_log_path(task_id: str) -> Path:
    """Keep Controller bootstrap diagnostics beside the existing compact task state."""
    return task_dir(task_id) / CONTROLLER_BOOTSTRAP_LOG_NAME


def _diagnostic_tail(path: Path, limit: int = MAX_SUPERVISOR_DIAGNOSTIC_BYTES) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read(limit).decode("utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _bound_bootstrap_log(path: Path) -> None:
    """Bound diagnostics before a restart while preserving the most recent evidence."""
    if not path.exists() or path.stat().st_size <= MAX_SUPERVISOR_DIAGNOSTIC_BYTES:
        return
    tail = _diagnostic_tail(path)
    path.write_text(tail, encoding="utf-8")


def _launch_token_adoption(state: dict[str, Any], kind: str, token: str) -> bool:
    prefix = kind.upper()
    return bool(
        token
        and state.get(f"{prefix}_STARTUP_STATUS") == "STARTING"
        and secrets.compare_digest(str(state.get(f"{prefix}_LAUNCH_TOKEN", "")), token)
    )


def _background_process_modes() -> list[tuple[str, int]]:
    if os.name != "nt":
        return [("STANDARD", 0)]
    detached = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    return [
        (
            "WINDOWS_DETACHED_BREAKAWAY",
            detached | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0),
        ),
        ("WINDOWS_DETACHED_FALLBACK", detached),
    ]


def _launch_background_process(
    command: Sequence[str], *, environment: dict[str, str], log_path: Path,
) -> tuple[subprocess.Popen[Any], str]:
    """Launch one detached child using the shared Windows-safe bootstrap contract."""
    _bound_bootstrap_log(log_path)
    errors: list[str] = []
    modes = _background_process_modes()
    for index, (mode, flags) in enumerate(modes):
        try:
            with log_path.open("ab", buffering=0) as stderr_handle:
                process = subprocess.Popen(
                    list(command), cwd=str(REPO.resolve()), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=stderr_handle, close_fds=True,
                    creationflags=flags, env=environment,
                )
            return process, mode
        except OSError as exc:
            errors.append(f"{mode}:{type(exc).__name__}:{exc}")
            if index + 1 >= len(modes) or getattr(exc, "winerror", None) not in {5, 87}:
                break
    raise HarnessError("BACKGROUND_CREATE_PROCESS_FAILED:" + " | ".join(errors))


def validate_task_id(task_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", task_id):
        raise HarnessError("TASK_ID_MUST_BE_LOWERCASE_ALNUM_HYPHEN_MAX63")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _runtime_owner(task_id: str, runtime: Path) -> dict[str, str]:
    marker = runtime / TASK_TEMP_OWNER_MARKER
    if not marker.is_file():
        raise HarnessError(f"WORKER_TEMP_RUNTIME_OWNER_MISSING:{marker}")
    try:
        owner = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"WORKER_TEMP_RUNTIME_OWNER_INVALID:{type(exc).__name__}:{exc}") from exc
    expected = {"task_id": task_id, "runtime": str(runtime)}
    if owner != expected:
        raise HarnessError(f"WORKER_TEMP_RUNTIME_OWNER_MISMATCH:{marker}")
    return owner


def _probe_temp_runtime(runtime: Path) -> None:
    probe = runtime / f".write-probe-{os.getpid()}-{secrets.token_hex(3)}.tmp"
    payload = secrets.token_bytes(16)
    try:
        with probe.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if probe.read_bytes() != payload:
            raise OSError("temporary runtime probe readback mismatch")
    finally:
        if probe.exists():
            probe.unlink()


def _prepare_task_temp_runtime(task_id: str) -> Path:
    runtime = task_temp_runtime(task_id)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    marker = runtime / TASK_TEMP_OWNER_MARKER
    if runtime.exists():
        if not runtime.is_dir():
            raise HarnessError(f"WORKER_TEMP_RUNTIME_NOT_DIRECTORY:{runtime}")
        _runtime_owner(task_id, runtime)
    else:
        runtime.mkdir()
        _atomic_write(marker, _json_bytes({"task_id": task_id, "runtime": str(runtime)}))
    (runtime / "cache").mkdir(exist_ok=True)
    _probe_temp_runtime(runtime)
    return runtime


def _ensure_task_temp_runtime(task_id: str) -> Path:
    state = load_state(task_id)
    recorded = state.get("TASK_TEMP_RUNTIME")
    expected: Path | None = None
    try:
        expected = task_temp_runtime(task_id)
        if recorded and Path(recorded).resolve(strict=False) != expected:
            raise HarnessError(f"WORKER_TEMP_RUNTIME_STATE_MISMATCH:{recorded}:{expected}")
        runtime = _prepare_task_temp_runtime(task_id)
    except (HarnessError, OSError, ValueError) as exc:
        update_task(task_id, {
            "TASK_TEMP_RUNTIME": str(expected or recorded or ""),
            "TASK_TEMP_RUNTIME_STATUS": "UNAVAILABLE",
            "TASK_TEMP_RUNTIME_OWNED": False,
        }, event="TASK_TEMP_RUNTIME_UNAVAILABLE", detail=f"{type(exc).__name__}:{exc}")
        raise HarnessError(f"WORKER_TEMP_RUNTIME_UNAVAILABLE:{type(exc).__name__}:{exc}") from exc
    update_task(task_id, {
        "TASK_TEMP_RUNTIME": str(runtime),
        "TASK_TEMP_RUNTIME_STATUS": "READY",
        "TASK_TEMP_RUNTIME_OWNED": True,
    }, event="TASK_TEMP_RUNTIME_READY", detail=f"root={runtime};write_probe=PASS")
    return runtime


def _task_temp_environment(runtime: Path) -> dict[str, str]:
    resolved = runtime.resolve()
    environment = os.environ.copy()
    for name in ("TEMP", "TMP", "TMPDIR"):
        environment[name] = str(resolved)
    environment["USTQ_CACHE_ROOT"] = str(resolved / "cache")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    return environment


def _cleanup_task_temp_runtime(task_id: str) -> None:
    state = load_state(task_id)
    recorded = state.get("TASK_TEMP_RUNTIME")
    expected: Path | None = None
    try:
        expected = task_temp_runtime(task_id)
        if recorded and Path(recorded).resolve(strict=False) != expected:
            raise HarnessError(f"WORKER_TEMP_RUNTIME_STATE_MISMATCH:{recorded}:{expected}")
        if expected.exists():
            if not expected.is_dir():
                raise HarnessError(f"WORKER_TEMP_RUNTIME_NOT_DIRECTORY:{expected}")
            _runtime_owner(task_id, expected)
            shutil.rmtree(expected)
        update_task(task_id, {
            "TASK_TEMP_RUNTIME": str(expected),
            "TASK_TEMP_RUNTIME_STATUS": "CLEANED",
            "TASK_TEMP_RUNTIME_OWNED": False,
        }, event="TASK_TEMP_RUNTIME_CLEANED", detail=str(expected))
    except (HarnessError, OSError, ValueError) as exc:
        update_task(task_id, {
            "TASK_TEMP_RUNTIME": str(expected or recorded or ""),
            "TASK_TEMP_RUNTIME_STATUS": "CLEANUP_FAILED",
            "HUMAN_ATTENTION_REQUIRED": True,
        }, event="TASK_TEMP_RUNTIME_CLEANUP_FAILED", detail=f"{type(exc).__name__}:{exc}")
        raise HarnessError(f"WORKER_TEMP_RUNTIME_CLEANUP_FAILED:{type(exc).__name__}:{exc}") from exc


@contextmanager
def _task_lock(task_id: str) -> Iterator[None]:
    directory = task_dir(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".state.lock"
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - repository runtime is Windows
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_state(task_id: str) -> dict[str, Any]:
    path = state_path(task_id)
    if not path.is_file():
        raise HarnessError(f"TASK_STATE_NOT_FOUND:{task_id}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("TASK_ID") != task_id or value.get("HARNESS_STATE") not in STATES:
        raise HarnessError(f"TASK_STATE_INVALID:{task_id}")
    return value


def _write_state_unlocked(task_id: str, state: dict[str, Any]) -> None:
    state["LAST_UPDATED_AT"] = utc_now()
    payload = _json_bytes(state)
    if len(payload) > MAX_STATE_BYTES:
        raise HarnessError(f"STATE_TOO_LARGE:{len(payload)}>{MAX_STATE_BYTES}")
    _atomic_write(state_path(task_id), payload)


def _append_event_unlocked(task_id: str, event: str, detail: str) -> None:
    path = timeline_path(task_id)
    row = {"at": utc_now(), "event": event[:80], "detail": detail[:1_000]}
    encoded = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    current_size = path.stat().st_size if path.exists() else 0
    if current_size + len(encoded) > MAX_TIMELINE_BYTES:
        raise HarnessError(f"TIMELINE_TOO_LARGE:{current_size}+{len(encoded)}")
    with path.open("ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def transition_value(old: str, new: str) -> str:
    if old == new:
        return new
    if new not in STATES or new not in ALLOWED_TRANSITIONS.get(old, set()):
        raise HarnessError(f"INVALID_STATE_TRANSITION:{old}->{new}")
    return new


def update_task(
    task_id: str,
    changes: dict[str, Any] | None = None,
    *,
    new_state: str | None = None,
    event: str | None = None,
    detail: str = "",
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    with _task_lock(task_id):
        state = load_state(task_id)
        if new_state:
            state["HARNESS_STATE"] = transition_value(state["HARNESS_STATE"], new_state)
        if changes:
            state.update(changes)
        if mutate:
            mutate(state)
        _write_state_unlocked(task_id, state)
        if event:
            _append_event_unlocked(task_id, event, detail)
        return state


def _new_state(
    task_id: str, goal: str, scope: str, max_corrections: int,
    task_contract: dict[str, Any] | None = None, max_hours: float | None = None,
) -> dict[str, Any]:
    started_at = utc_now()
    deadline_at = (
        (datetime.fromisoformat(started_at) + timedelta(hours=max_hours)).isoformat()
        if max_hours is not None else ""
    )
    plan = [
        {"phase": "HARD_PREFLIGHT", "status": "PENDING", "action": "Run task-scoped hard preflight", "why": "Research and Anti-Bloat gates precede autonomous mutation."},
        {"phase": "DISCOVER_REUSE", "status": "PENDING", "action": "Build one task-local reuse cache", "why": "Reuse evidence is required before material creation."},
        {"phase": "CREATE_ISOLATED_WORKTREE", "status": "PENDING", "action": "Create an external Git worktree", "why": "The dirty primary tree and concurrent work must remain isolated."},
        {"phase": "PLAN", "status": "PENDING", "action": "Decompose the authorized goal into persistent work units", "why": "Independent branches must remain runnable after local failures."},
        {"phase": "AUTONOMOUS_EXECUTION_LOOP", "status": "PENDING", "action": "Execute, validate, repair, and checkpoint work units", "why": "Substantive related work is batched while local blockers remain local."},
        {"phase": "FINAL_VALIDATION", "status": "PENDING", "action": "Run authoritative machine validation", "why": "No worker report substitutes for controller validation."},
        {"phase": "FINAL_INDEPENDENT_REVIEW", "status": "PENDING", "action": "Run a fresh read-only final review", "why": "One independent review gates completion."},
        {"phase": "FINALIZE", "status": "PENDING", "action": "Preserve worktree and report", "why": "Harness never merges or deletes useful task work."},
    ]
    state = {
        "HARNESS_VERSION": 3,
        "TASK_ID": task_id,
        "HARNESS_STATE": "PLANNING",
        "GOAL": goal,
        "GOAL_VERSION": 1,
        "CURRENT_TASK": goal.splitlines()[0][:240],
        "CURRENT_PHASE": "ACCEPT_TASK",
        "CURRENT_ACTION": "Task accepted; preparing R1 preflight",
        "WHY_CURRENT_ACTION": "A single human-authorized goal must pass hard guards before mutation.",
        "PROGRESS_SUMMARY": f"0/{len(plan)} plan steps completed",
        "LAST_COMPLETED": "TASK_ACCEPTED",
        "NEXT_ACTION": "Run task-scoped R1 preflight",
        "WHY_NEXT_ACTION": "R1 guards are authoritative for overfit, frozen-asset, and Anti-Bloat safety.",
        "WORKTREE": "",
        "TASK_TEMP_RUNTIME": "",
        "TASK_TEMP_RUNTIME_STATUS": "NOT_PROVISIONED",
        "TASK_TEMP_RUNTIME_OWNED": False,
        "WORKER_STATUS": "NOT_STARTED",
        "WORKER_TEST_STATUS": "NOT_RUN",
        "WORKER_TEST_LIMITATION": "",
        "WORKER_TEST_EVIDENCE": "",
        "CONTROLLER_VALIDATION_STATUS": "NOT_RUN",
        "WORKTREE_INVENTORY_STATUS": "UNKNOWN",
        "OVERFIT_GUARD": "PENDING",
        "ANTI_BLOAT": "PENDING",
        "REUSE_GUARD": "PENDING",
        "FILES_CHANGED": [],
        "FILES_CREATED": [],
        "DEPENDENCIES_ADDED": [],
        "PAUSE_REQUESTED": False,
        "STOP_REQUESTED": False,
        "HUMAN_ATTENTION_REQUIRED": False,
        "LAST_REVIEW_STATUS": "NOT_RUN",
        "LAST_UPDATED_AT": utc_now(),
        "TASK_KIND": scope if scope in TASK_KINDS else "independent-code",
        "TASK_KIND_SOURCE": "LEGACY_TASK_SCOPE",
        "AUTO_SCOPE_SUGGESTION": scope,
        "SAFETY_FLAGS": {},
        "TASK_SCOPE": scope,
        "PLAN": plan,
        "NEXT_ACTION_CODE": "HARD_PREFLIGHT",
        "TESTS_RUN": [],
        "TEST_HISTORY_START_INDEX": 0,
        "VALIDATION_RESULTS": [],
        "WORKER_FINDINGS": "",
        "REVIEW_FINDINGS": "",
        "BLOCKERS": [],
        "ACTIVE_BLOCKERS": [],
        "LOCAL_BLOCKED_WORK": [],
        "RESOLVED_FINDINGS": [],
        "HISTORICAL_FINDINGS": [],
        "STEERING_HISTORY": [],
        "PENDING_STEER": [],
        "CORRECTION_ATTEMPTS": 0,
        "MAX_CORRECTION_ATTEMPTS": max_corrections,
        "RETRY_LEDGER": {},
        "CURRENT_RETRY_SIGNATURE": "",
        "CURRENT_RETRY_COUNT": 0,
        "WORKER_PID": None,
        "WORKER_THREAD_ID": "",
        "ACTIVE_THREAD_ID": "",
        "ACTIVE_PROCESS_KIND": "",
        "CONTROLLER_PID": None,
        "CONTROLLER_LAUNCH_PID": None,
        "CONTROLLER_LAUNCH_TOKEN": "",
        "CONTROLLER_PARENT_PID": None,
        "CONTROLLER_STARTED_AT": "",
        "CONTROLLER_READY_AT": "",
        "CONTROLLER_STARTUP_STATUS": "NOT_STARTED",
        "CONTROLLER_EXIT_CODE": None,
        "CONTROLLER_EXCEPTION": "",
        "CONTROLLER_STDERR_TAIL": "",
        "CONTROLLER_BOOTSTRAP_LOG": str(controller_bootstrap_log_path(task_id)),
        "CONTROLLER_SPAWN_MODE": "",
        "CONTROLLER_STARTUP_RETRY_SIGNATURE": "",
        "CONTROLLER_STARTUP_RETRY_COUNT": 0,
        "CONTROLLER_STARTUP_RETRY_BACKOFF_SECONDS": 0.0,
        "SUPERVISOR_PID": None,
        "SUPERVISOR_LAUNCH_PID": None,
        "SUPERVISOR_LAUNCH_TOKEN": "",
        "SUPERVISOR_PARENT_PID": None,
        "SUPERVISOR_STARTED_AT": "",
        "SUPERVISOR_READY_AT": "",
        "SUPERVISOR_HEARTBEAT_AT": "",
        "SUPERVISOR_EXIT_CODE": None,
        "SUPERVISOR_EXCEPTION": "",
        "SUPERVISOR_STDERR_TAIL": "",
        "SUPERVISOR_STARTUP_STATUS": "NOT_STARTED",
        "SUPERVISOR_BOOTSTRAP_LOG": str(supervisor_bootstrap_log_path(task_id)),
        "SUPERVISOR_SPAWN_MODE": "",
        "CONTROLLER_HEARTBEAT_AT": "",
        "BASE_HEAD": "",
        "BASE_BRANCH": "",
        "REUSE_EVIDENCE": {},
        "REUSE_DISCOVERY_CACHE": {},
        "NEW_COMPONENT_JUSTIFICATION": "",
        "JUSTIFIED_CREATED_PATHS": [],
        "UNJUSTIFIED_CREATED_PATHS": [],
        "REVIEW_REQUESTED": False,
        "REPO_BYTES_BEFORE": None,
        "REPO_BYTES_AFTER": None,
        "REPO_SIZE_DELTA_BYTES": None,
        "PRIMARY_REPO_BYTES_AT_START": None,
        "ANTI_BLOAT_BASELINE_RESIDUE": [],
        "ANTI_BLOAT_TASK_DELTA": "PENDING",
        "WORK_UNITS": [],
        "ACTIVE_WORK_UNIT_ID": "",
        "ACTIVE_WORK_UNIT_IDS": [],
        "CURRENT_WORK_UNIT": "",
        "PLANNER_FINDINGS": "",
        "WORKER_BATCH_BASE_PATHS": [],
        "WORKER_REPORTED_CHANGED_PATHS": [],
        "PENDING_UNIT_RESULTS": [],
        "FINAL_REVIEW_ATTEMPTS": 0,
        "TASK_STARTED_AT": started_at,
        "TIME_BUDGET_HOURS": max_hours,
        "DEADLINE_AT": deadline_at,
        "LAST_MEANINGFUL_PROGRESS_AT": started_at,
        "LAST_CHECKPOINT": "TASK_ACCEPTED",
        "WAITING_STARTED_AT": "",
        "TERMINAL_OUTCOME": "",
        "TELEMETRY": {
            "total_wall_seconds": 0.0,
            "worker_wall_seconds": 0.0,
            "reviewer_wall_seconds": 0.0,
            "machine_validation_wall_seconds": 0.0,
            "waiting_human_wall_seconds": 0.0,
            "worker_turns": 0,
            "reviewer_turns": 0,
            "planner_turns": 0,
            "work_units_completed": 0,
            "repeated_work_prevented": 0,
            "reuse_hits": 0,
            "new_components_created": 0,
            "local_blockers_bypassed": 0,
            "crash_recoveries": 0,
            "duplicate_planned_work_rejected": 0,
            "discovery_full_scans": 0,
            "discovery_incremental_refreshes": 0,
        },
    }
    if task_contract:
        state.update(task_contract)
    return state


def _plan_update(state: dict[str, Any], phase: str, status: str) -> None:
    for row in state["PLAN"]:
        if row["phase"] == phase:
            row["status"] = status
            break
    _sync_plan_progress(state)


def _sync_plan_progress(state: dict[str, Any]) -> None:
    completed = sum(row["status"] == "COMPLETED" for row in state["PLAN"])
    state["PROGRESS_SUMMARY"] = f"{completed}/{len(state['PLAN'])} plan steps completed"
    active = next((row["phase"] for row in state["PLAN"] if row["status"] == "IN_PROGRESS"), "")
    if active:
        state["PROGRESS_SUMMARY"] += f"; {active} in progress"


def _reset_correction_plan(state: dict[str, Any]) -> None:
    for row in state["PLAN"]:
        if row["phase"] in {
            "IMPLEMENT", "TARGETED_TEST", "INDEPENDENT_REVIEW",
            "AUTONOMOUS_EXECUTION_LOOP", "FINAL_VALIDATION", "FINAL_INDEPENDENT_REVIEW",
        }:
            row["status"] = "PENDING"
    _sync_plan_progress(state)


def _close_active_plan(state: dict[str, Any], status: str) -> None:
    changed = False
    for row in state["PLAN"]:
        if row["status"] == "IN_PROGRESS":
            row["status"] = status
            changed = True
    if changed:
        _sync_plan_progress(state)


def _seconds_since(value: str, *, now: datetime | None = None) -> float:
    if not value:
        return 0.0
    try:
        started = datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    return max(0.0, ((now or datetime.now(timezone.utc)) - started).total_seconds())


def _remaining_budget_seconds(state: dict[str, Any], *, now: datetime | None = None) -> float | None:
    deadline = state.get("DEADLINE_AT")
    if not deadline:
        return None
    try:
        deadline_value = datetime.fromisoformat(str(deadline))
    except ValueError:
        return 0.0
    return max(0.0, (deadline_value - (now or datetime.now(timezone.utc))).total_seconds())


def _telemetry_add(state: dict[str, Any], **increments: float | int) -> None:
    telemetry = state.setdefault("TELEMETRY", {})
    for key, amount in increments.items():
        telemetry[key] = telemetry.get(key, 0) + amount
    telemetry["total_wall_seconds"] = _seconds_since(str(state.get("TASK_STARTED_AT", "")))


def _meaningful_progress(state: dict[str, Any], checkpoint: str) -> None:
    state["LAST_MEANINGFUL_PROGRESS_AT"] = utc_now()
    state["LAST_CHECKPOINT"] = checkpoint[:500]


def _unit_identity(value: str) -> str:
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in {
            "a", "an", "and", "the", "to", "for", "of", "in", "on", "with",
            "new", "final", "r1", "r2", "r3", "component", "work", "unit",
        }
    ]
    return "-".join(sorted(dict.fromkeys(tokens)))[:240]


def _new_work_unit(
    unit_id: str,
    objective: str,
    *,
    dependencies: Sequence[str] = (),
    parent_id: str = "",
    subsystem: str = "general",
    relevant_paths: Sequence[str] = (),
    required_inputs: Sequence[str] = (),
    optional: bool = False,
    reuse_decision: str = "UNKNOWN",
    reuse_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "id": unit_id[:80],
        "parent_id": parent_id[:80],
        "dependencies": list(dict.fromkeys(str(value)[:80] for value in dependencies))[:20],
        "objective": objective.strip()[:1_000],
        "canonical_identity": _unit_identity(objective),
        "status": "READY",
        "subsystem": (subsystem or "general")[:120],
        "relevant_paths": list(dict.fromkeys(str(value).replace("\\", "/") for value in relevant_paths))[:30],
        "reuse_decision": reuse_decision if reuse_decision in {"REUSE", "EXTEND", "CREATE", "UNKNOWN"} else "UNKNOWN",
        "reuse_evidence": list(dict.fromkeys(str(value)[:500] for value in reuse_evidence))[:20],
        "required_inputs": list(dict.fromkeys(str(value)[:300] for value in required_inputs))[:20],
        "produced_outputs": [],
        "validation_state": "NOT_RUN",
        "blocker": {},
        "retry_history": [],
        "failure_signature": "",
        "last_checkpoint": "PLANNED",
        "next_action": "Execute this authorized work unit",
        "optional": bool(optional),
        "attempts": 0,
    }


def _default_work_units(goal: str) -> list[dict[str, Any]]:
    candidates = [
        match.group(1).strip()
        for line in goal.splitlines()
        if (match := re.match(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$", line))
        and len(match.group(1).strip()) >= 16
        and not re.match(r"(?i)do not\b", match.group(1).strip())
    ]
    objectives = candidates[:12] if 2 <= len(candidates) <= 12 else [goal.splitlines()[0].strip()[:1_000]]
    return [
        _new_work_unit(f"WU-{index:03d}", objective)
        for index, objective in enumerate(objectives, 1)
    ]


def _normalize_work_unit_plan(raw_units: Any, goal: str) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(raw_units, list):
        return _default_work_units(goal), 0
    units: list[dict[str, Any]] = []
    identities: set[str] = set()
    rejected = 0
    for index, raw in enumerate(raw_units[:MAX_WORK_UNITS], 1):
        if not isinstance(raw, dict) or not str(raw.get("objective", "")).strip():
            rejected += 1
            continue
        unit = _new_work_unit(
            str(raw.get("id") or f"WU-{index:03d}"),
            str(raw["objective"]),
            dependencies=raw.get("dependencies", []),
            parent_id=str(raw.get("parent_id", "")),
            subsystem=str(raw.get("subsystem", "general")),
            relevant_paths=raw.get("relevant_paths", []),
            required_inputs=raw.get("required_inputs", []),
            optional=bool(raw.get("optional", False)),
            reuse_decision=str(raw.get("reuse_decision", "UNKNOWN")).upper(),
            reuse_evidence=raw.get("reuse_evidence", []),
        )
        explicit_identity = _unit_identity(str(raw.get("identity", "")))
        identity = explicit_identity or unit["canonical_identity"]
        if identity and identity in identities:
            rejected += 1
            continue
        identities.add(identity)
        unit["canonical_identity"] = identity
        units.append(unit)
    if not units:
        return _default_work_units(goal), rejected
    ids = {unit["id"] for unit in units}
    seen_ids: set[str] = set()
    for index, unit in enumerate(units, 1):
        if unit["id"] in seen_ids:
            unit["id"] = f"WU-{index:03d}"
            rejected += 1
        seen_ids.add(unit["id"])
    ids = {unit["id"] for unit in units}
    for unit in units:
        unit["dependencies"] = [
            dependency for dependency in unit["dependencies"]
            if dependency in ids and dependency != unit["id"]
        ]
    return units, rejected


def _unit_by_id(state: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    return next((unit for unit in state.get("WORK_UNITS", []) if unit.get("id") == unit_id), None)


def _work_unit_counts(state: dict[str, Any]) -> dict[str, int]:
    units = state.get("WORK_UNITS", [])
    return {
        "total": len(units),
        "done": sum(unit.get("status") == "DONE" for unit in units),
        "runnable": len(_runnable_work_units(state)),
        "local_blocked": sum(unit.get("status") == "BLOCKED_LOCAL" for unit in units),
        "deferred": sum(unit.get("status") == "DEFERRED" for unit in units),
    }


def _runnable_work_units(state: dict[str, Any]) -> list[dict[str, Any]]:
    units = state.get("WORK_UNITS", [])
    by_id = {unit.get("id"): unit for unit in units}
    runnable: list[dict[str, Any]] = []
    for unit in units:
        if unit.get("status") not in {"READY", "RETRY"}:
            continue
        dependencies = [by_id.get(value) for value in unit.get("dependencies", [])]
        if all(dependency and dependency.get("status") == "DONE" for dependency in dependencies):
            runnable.append(unit)
    return runnable


def _defer_dependency_blocked_units(state: dict[str, Any]) -> int:
    by_id = {unit.get("id"): unit for unit in state.get("WORK_UNITS", [])}
    deferred = 0
    for unit in state.get("WORK_UNITS", []):
        if unit.get("status") not in {"READY", "RETRY"}:
            continue
        blocking = [
            dependency for dependency in unit.get("dependencies", [])
            if by_id.get(dependency, {}).get("status") in {"BLOCKED_LOCAL", "DEFERRED", "SKIPPED_WITH_REASON"}
        ]
        if blocking:
            unit["status"] = "DEFERRED"
            unit["blocker"] = {"code": "DEPENDENCY_UNAVAILABLE", "dependencies": blocking}
            unit["last_checkpoint"] = "DEFERRED_BY_DEPENDENCY"
            unit["next_action"] = "Continue only if the blocked dependency becomes available"
            deferred += 1
    return deferred


def _select_work_unit_batch(state: dict[str, Any]) -> list[str]:
    _defer_dependency_blocked_units(state)
    runnable = _runnable_work_units(state)
    if not runnable:
        state["ACTIVE_WORK_UNIT_IDS"] = []
        state["ACTIVE_WORK_UNIT_ID"] = ""
        state["CURRENT_WORK_UNIT"] = ""
        return []
    remaining = _remaining_budget_seconds(state)
    if remaining is not None and remaining <= 900:
        non_optional = [unit for unit in runnable if not unit.get("optional")]
        if non_optional:
            runnable = non_optional
    first = runnable[0]
    related = [unit for unit in runnable if unit.get("subsystem") == first.get("subsystem")]
    batch = (related + [unit for unit in runnable if unit not in related])[:MAX_WORKER_BATCH]
    ids = [str(unit["id"]) for unit in batch]
    for unit in batch:
        unit["status"] = "RUNNING"
        unit["attempts"] = int(unit.get("attempts", 0)) + 1
        unit["last_checkpoint"] = "DISPATCHED"
        unit["next_action"] = "Complete or checkpoint this unit in the active worker batch"
    state["ACTIVE_WORK_UNIT_IDS"] = ids
    state["ACTIVE_WORK_UNIT_ID"] = ids[0]
    state["CURRENT_WORK_UNIT"] = " | ".join(
        f"{unit['id']}:{unit['objective'][:120]}" for unit in batch
    )
    return ids


def _failure_signature(kind: str, detail: str) -> str:
    normalized = re.sub(r"[A-Za-z]:[/\\][^\s:]+", "<path>", detail.casefold())
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()[:500]
    return f"{kind.upper()}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _record_unit_failure(
    state: dict[str, Any], unit_ids: Sequence[str], kind: str, detail: str,
    progress_hash: str, *, retry_limit: int = DEFAULT_FAILURE_RETRY_LIMIT,
) -> bool:
    signature = _failure_signature(kind, detail)
    ledger = state.setdefault("RETRY_LEDGER", {})
    all_blocked = True
    for unit_id in unit_ids:
        unit = _unit_by_id(state, unit_id)
        if unit is None:
            continue
        key = f"{unit_id}:{signature}"
        prior = ledger.get(key, {})
        count = int(prior.get("count", 0)) + 1 if prior.get("progress_hash") == progress_hash else 1
        ledger[key] = {
            "count": count,
            "progress_hash": progress_hash,
            "last_attempted_remedy": kind[:200],
            "last_detail": detail[:1_000],
            "updated_at": utc_now(),
        }
        history = unit.setdefault("retry_history", [])
        history.append({"signature": signature, "count": count, "at": utc_now(), "progress_hash": progress_hash})
        unit["retry_history"] = history[-20:]
        unit["failure_signature"] = signature
        unit["validation_state"] = "FAIL"
        if count > retry_limit:
            unit["status"] = "BLOCKED_LOCAL"
            unit["blocker"] = {"code": kind.upper(), "detail": detail[:1_000], "signature": signature}
            unit["last_checkpoint"] = "RETRY_BUDGET_EXHAUSTED"
            unit["next_action"] = "Deferred unless a later independent change resolves this signature"
        else:
            unit["status"] = "RETRY"
            unit["last_checkpoint"] = "RETRY_SCHEDULED"
            unit["next_action"] = f"Retry with a different remedy for {signature}"
            all_blocked = False
    state["CURRENT_RETRY_SIGNATURE"] = signature
    state["CURRENT_RETRY_COUNT"] = max(
        (int(ledger.get(f"{unit_id}:{signature}", {}).get("count", 0)) for unit_id in unit_ids),
        default=0,
    )
    state["ACTIVE_WORK_UNIT_IDS"] = []
    state["ACTIVE_WORK_UNIT_ID"] = ""
    state["CURRENT_WORK_UNIT"] = ""
    return all_blocked


def _current_task_id(explicit: str | None) -> str:
    if explicit:
        validate_task_id(explicit)
        return explicit
    pointer = state_root() / "current_task.txt"
    if not pointer.is_file():
        raise HarnessError("NO_CURRENT_TASK; pass --task-id")
    task_id = pointer.read_text(encoding="utf-8").strip()
    validate_task_id(task_id)
    return task_id


def _set_current_task(task_id: str) -> None:
    _atomic_write(state_root() / "current_task.txt", (task_id + "\n").encode("utf-8"))


def _negated(text: str, start: int, end: int | None = None) -> bool:
    prefix = text[max(0, start - 48):start].lower()
    suffix = text[end if end is not None else start:min(len(text), (end or start) + 40)].lower()
    return bool(
        re.search(
            r"(?:(?:do(?:es|ne)?|did|must|should|will|can(?:not)?|is|are|was|were)\s+not(?:\s+be)?|"
            r"don't|can't|cannot|never|without|avoid|exclude|reject|forbid|prevent)"
            r"\s+(?:[a-z][\w-]*\s+){0,3}$|"
            r"\bno(?:\s+[a-z][\w-]*){0,2}\s*$",
            prefix,
        )
        or re.match(r"\s+(?:is|are|was|were)\s+(?:not\s+required|prohibited|forbidden|disallowed|out\s+of\s+scope)\b", suffix)
    )


def hard_guard_conflicts(instruction: str) -> list[str]:
    text = " ".join(instruction.split())
    conflicts: list[str] = []
    action_pattern = (
        r"\b(?:(?:re)?train\w*|fit\w*|refit\w*|tun\w*|optim\w*|select\w*|"
        r"choos\w*|search\w*|adjust\w*)\b"
    )
    unsafe_action = re.compile(action_pattern, re.I)
    safe_pre2026 = re.compile(
        r"\bpre[- ]?2026\b|\bbefore\s+(?:the\s+start\s+of\s+)?2026(?:-01-01)?\b|"
        r"\b(?:strictly\s+)?earlier\s+than\s+2026(?:-01-01)?\b|"
        r"\bprior\s+to\s+2026(?:-01-01)?\b|<\s*2026-01-01\b",
        re.I,
    )
    unsafe_year = r"\b2026(?:\+)?\b"
    data_role = r"\b(?:data|inputs?|samples?|labels?|outcomes?|performance|results?|holdout)\b"
    ambiguous_request = re.compile(
        rf"^\s*(?:please\s+)?{action_pattern}|"
        rf"\b(?:need|plan|intend|want|must|should|will)\s+to\s+{action_pattern}|"
        r"\b(?:perform|run|start|continue)\s+(?:a\s+)?(?:model\s+)?training\b",
        re.I,
    )
    for clause in re.split(r"[.;\n]+|\b(?:and|but)\b", text, flags=re.I):
        has_safe_pre2026 = bool(safe_pre2026.search(clause))
        scoped = safe_pre2026.sub("PRE2026", clause)
        actions = [
            match for match in unsafe_action.finditer(scoped)
            if not _negated(scoped, match.start(), match.end())
        ]
        if not actions:
            continue
        unsafe = False
        for action in actions:
            tail = scoped[action.end():action.end() + 120]
            if re.search(
                rf"[^.;]{{0,70}}\b(?:on|using|with|from|against|based\s+on)\b"
                rf"[^.;]{{0,35}}{unsafe_year}",
                tail,
                re.I,
            ):
                unsafe = True
                break
            prefix_start = max(0, action.start() - 160)
            prefix = scoped[prefix_start:action.start()]
            for source in re.finditer(
                rf"\b(?:use|using)\b[^.;]{{0,40}}{unsafe_year}(?:[^.;]{{0,35}}{data_role})?"
                r"[^.;]{0,35}\b(?:to|for)\b\s*(?:the\s+)?(?:model|threshold|parameters?)?\s*$",
                prefix,
                re.I,
            ):
                source_start = prefix_start + source.start()
                if not _negated(scoped, source_start, source_start + len(source.group(0).split()[0])):
                    unsafe = True
                    break
            if unsafe:
                break
        if unsafe:
            conflicts.append("EXPOSED_2026_OPTIMIZATION")
            break
        if not has_safe_pre2026 and ambiguous_request.search(scoped):
            conflicts.append("AMBIGUOUS_TRAINING_TEMPORAL_SCOPE")
            break
    patterns = (
        ("FROZEN_ASSET_MUTATION", r"(?:modify|overwrite|delete|unfreeze)\s+(?:a\s+)?frozen"),
        ("CANONICAL_DATA_MUTATION", r"(?:modify|overwrite|delete|write\s+to)\s+(?:the\s+)?canonical\s+(?:market\s+)?data"),
        ("REPO_LOCAL_VENV", r"(?:create|install|build)\s+(?:a\s+)?(?:repo(?:sitory)?[- ]local\s+)?\.venv"),
        ("AUTO_MERGE_OR_PRODUCTION_PROMOTION", r"(?:auto(?:matically)?[- ]merge|promote\s+(?:it\s+)?to\s+production|authorize\s+production)"),
    )
    for code, pattern in patterns:
        if any(
            not _negated(text, found.start(), found.end())
            for found in re.finditer(pattern, text, re.I)
        ):
            conflicts.append(code)
    return conflicts


def _has_positive_scope_action(text: str, target: str, action: str) -> bool:
    """Match a target to its nearest requested action without deleting negated text."""
    for segment in text.splitlines():
        actions = list(re.finditer(action, segment, re.I))
        for subject in re.finditer(target, segment, re.I):
            if not actions:
                continue
            distance = lambda match: min(abs(match.end() - subject.start()), abs(subject.end() - match.start()))
            nearest_distance = min(distance(match) for match in actions)
            nearest = [match for match in actions if distance(match) == nearest_distance]
            if any(not _negated(segment, match.start(), match.end()) for match in nearest):
                return True
    return False


def _task_scope_evidence(goal: str) -> dict[str, bool]:
    scope_text = re.sub(
        r"\b(?:pre[- ]?2026(?:-research)?|2026-(?:evaluation|optimization)|frozen-dependent|"
        r"independent-code|historical-fetch)\b",
        " ",
        goal,
        flags=re.I,
    )
    segments = [segment.strip() for segment in re.split(
        r"[.,;\n]+|\b(?:and|but)\b", scope_text, flags=re.I,
    ) if segment.strip()]
    segments = [
        segment for segment in segments
        if not re.search(
            r"\b(?:classification|classified)\b[^.;]{0,80}\b(?:tasks?|words?|language)\b|"
            r"\b(?:tasks?|words?|language)\b[^.;]{0,80}\b(?:classification|classified)\b",
            segment,
            re.I,
        )
    ]
    task_text = "\n".join(segments)

    research_action = (
        r"\b(?:conduct|perform|run|execute|start|continue|undertake|train\w*|fit\w*|refit\w*|"
        r"tun\w*|optim\w*|backtest\w*|depend(?:s|ed|ing)?\s+on|"
        r"rely(?:ies|ied|ing)?\s+on|requires?|use|fix|repair|audit|implement|extend|build)\b"
    )
    patterns = (
        ("MODEL_TRAINING_OR_SELECTION", r"\b(?:models?|features?|parameters?|thresholds?|train(?:ing|ed)?)\b", r"\b(?:train\w*|fit\w*|refit\w*|tun\w*|optim\w*|select\w*|choos\w*|search\w*)\b"),
        ("PRE2026_RESEARCH_OR_BACKTEST", r"\b(?:research(?:ing|ed)?|models?|modeling|features?|backtests?|backtesting|train(?:ing|ed)?|pit|leakage)\b", research_action),
        ("EVALUATES_2026_OR_HOLDOUT", r"(?<!pre-)(?<!pre )\b2026\+?\b|\b(?:holdout|prospective|forward(?:-monitoring)?|evaluation)\b", r"\b(?:use|run|evaluate|validate|assess|analy[sz]e|measure|monitor|test|compare)\w*\b"),
        ("PIT_OR_LEAKAGE_SENSITIVE", r"\b(?:pit|leakage)\b", research_action),
        ("FROZEN_ASSET_DEPENDENCY", r"\bfrozen\b", r"\b(?:use|run|evaluate|validate|assess|test|compare|read|touch|modify|overwrite|delete|unfreeze|depend(?:s|ed|ing)?\s+on|rely(?:ies|ied|ing)?\s+on|requires?)\b"),
        ("HISTORICAL_FETCH", r"\bhistorical\b", r"\b(?:fetch|download)\w*\b"),
    )
    return {name: _has_positive_scope_action(task_text, target, action) for name, target, action in patterns}


def _strongest_scope(*scopes: str) -> str:
    unknown = [scope for scope in scopes if scope not in SCOPE_SAFETY_RANK]
    if unknown:
        raise HarnessError(f"UNKNOWN_TASK_SCOPE:{unknown[0]}")
    return max(scopes, key=SCOPE_SAFETY_RANK.__getitem__)


def _scope_from_evidence(evidence: dict[str, bool], requested: str) -> str:
    scopes = [requested]
    for flag, scope in (
        ("EVALUATES_2026_OR_HOLDOUT", "2026-evaluation"),
        ("FROZEN_ASSET_DEPENDENCY", "frozen-dependent"),
        ("PRE2026_RESEARCH_OR_BACKTEST", "pre2026-research"),
        ("HISTORICAL_FETCH", "historical-fetch"),
    ):
        if evidence[flag]:
            scopes.append(scope)
    return _strongest_scope(*scopes)


def infer_scope(goal: str, requested: str) -> str:
    """Return the conservative AUTO scope suggestion, never the hard-guard decision."""
    return _scope_from_evidence(_task_scope_evidence(goal), requested)


def _task_contract(goal: str, task_kind: str, requested_scope: str) -> dict[str, Any]:
    if task_kind not in TASK_KINDS:
        raise HarnessError(f"INVALID_TASK_KIND:{task_kind}")
    evidence = _task_scope_evidence(goal)
    suggestion = _scope_from_evidence(evidence, requested_scope)
    evidence["EXPOSED_2026_OR_HOLDOUT_OPTIMIZATION"] = (
        "EXPOSED_2026_OPTIMIZATION" in hard_guard_conflicts(goal)
    )
    if task_kind == "auto":
        resolved_kind = {
            "2026-evaluation": "2026-evaluation", "2026-optimization": "2026-evaluation",
            "pre2026-research": "pre2026-research", "frozen-dependent": "pre2026-research",
            "historical-fetch": "pre2026-research",
        }.get(suggestion, "maintenance" if re.search(r"\b(?:harness|maintenance)\b", goal, re.I) else "independent-code")
        source = "AUTO"
    else:
        resolved_kind = task_kind
        source = "EXPLICIT"
    declared_scope = TASK_KIND_SCOPES.get(resolved_kind, "independent-code")
    safety_scope = "2026-optimization" if evidence["EXPOSED_2026_OR_HOLDOUT_OPTIMIZATION"] else suggestion
    effective_scope = _strongest_scope(declared_scope, requested_scope, safety_scope)
    return {
        "TASK_KIND": resolved_kind,
        "TASK_KIND_SOURCE": source,
        "AUTO_SCOPE_SUGGESTION": suggestion,
        "SAFETY_FLAGS": evidence,
        "TASK_SCOPE": effective_scope,
    }


def _run(args: Sequence[str], cwd: Path = REPO, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=timeout,
    )


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise HarnessError(f"REAL_REQUIRED_EXECUTABLE_MISSING:{name}")
    return executable


def _git(args: Sequence[str], cwd: Path = REPO, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run([_required_executable("git"), *args], cwd, timeout)


def _repo_status_fingerprint(repo: Path) -> dict[str, Any]:
    result = _git(["status", "--porcelain=v1", "-z"], repo)
    raw = result.stdout.encode("utf-8", errors="replace")
    return {"entry_count": raw.count(b"\0"), "sha256": hashlib.sha256(raw).hexdigest()}


def _python_native_discovery(
    pattern: str, roots: Sequence[str] = DISCOVERY_ROOTS,
) -> tuple[list[str], list[str], list[str]]:
    compiled = re.compile(pattern, re.I)
    names: list[str] = []
    semantic_rows: list[str] = []
    warnings: list[str] = []

    def record_warning(value: str) -> None:
        if len(warnings) < 20:
            warnings.append(value[:300])

    for root_name in roots:
        root = REPO / root_name
        if not root.is_dir():
            record_warning(f"OPTIONAL_DISCOVERY_PATH_UNAVAILABLE:{root_name}")
            continue

        def onerror(exc: OSError) -> None:
            record_warning(f"OPTIONAL_DISCOVERY_PATH_UNREADABLE:{root_name}:{type(exc).__name__}")

        for current, directories, filenames in os.walk(root, onerror=onerror):
            directories[:] = [
                name for name in directories
                if name != "__pycache__" and name != "legacy" and not name.startswith("_backup")
            ]
            for filename in filenames:
                path = Path(current) / filename
                relative = path.relative_to(REPO).as_posix()
                if len(names) < 20 and compiled.search(relative):
                    names.append(relative)
                if len(semantic_rows) >= 20 or path.suffix.lower() not in DISCOVERY_TEXT_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > 1_048_576:
                        continue
                    with path.open("r", encoding="utf-8", errors="ignore") as handle:
                        for line_number, line in enumerate(handle, 1):
                            if compiled.search(line):
                                semantic_rows.append(f"{relative}:{line_number}:{line.rstrip()[:500]}")
                                break
                except OSError as exc:
                    record_warning(f"OPTIONAL_DISCOVERY_FILE_UNREADABLE:{relative}:{type(exc).__name__}")
    return names, semantic_rows, warnings


def _discover_existing(goal: str, roots: Sequence[str] | None = None) -> dict[str, Any]:
    selected_roots = tuple(dict.fromkeys(roots or DISCOVERY_ROOTS))
    words = [
        word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", goal)
        if word.lower() not in {
            "this", "that", "with", "from", "into", "task", "implement", "create",
            "build", "repository", "please", "should", "must", "using", "existing",
        }
    ]
    tokens = list(dict.fromkeys(words))[:8] or ["harness"]
    pattern = "|".join(re.escape(token) for token in tokens)
    discovery_tool = "RIPGREP"
    warnings: list[str] = []
    rg = shutil.which("rg")
    if rg:
        try:
            name_result = _run([rg, "--files", *selected_roots], REPO, 20)
            semantic = _run([
                rg, "-n", "-i", "-m", "1", "--glob", "!**/_backup*/**", "--glob", "!**/legacy/**",
                pattern, *selected_roots,
            ], REPO, 30)
            if name_result.returncode != 0 or semantic.returncode not in {0, 1}:
                raise HarnessError(
                    f"rg_exit:name={name_result.returncode},semantic={semantic.returncode}"
                )
            names = [line for line in name_result.stdout.splitlines() if re.search(pattern, line, re.I)][:20]
            semantic_rows = semantic.stdout.splitlines()[:20]
        except (OSError, subprocess.SubprocessError, HarnessError) as exc:
            discovery_tool = "PYTHON_NATIVE_FALLBACK"
            warnings.append(f"OPTIONAL_DISCOVERY_TOOL_FAILED:rg:{type(exc).__name__}")
            names, semantic_rows, native_warnings = _python_native_discovery(pattern, selected_roots)
            warnings.extend(native_warnings)
    else:
        discovery_tool = "PYTHON_NATIVE_FALLBACK"
        warnings.append("OPTIONAL_DISCOVERY_TOOL_UNAVAILABLE:rg")
        names, semantic_rows, native_warnings = _python_native_discovery(pattern, selected_roots)
        warnings.extend(native_warnings)
    return {
        "tokens": tokens,
        "discovery_tool": discovery_tool,
        "warning_codes": warnings[:20],
        "filename_matches": names,
        "semantic_matches": semantic_rows,
        "roots": list(selected_roots),
        "match_count_capped": len(names) + len(semantic_rows),
        "candidate_classifications": {
            row.split(":", 1)[0]: "UNKNOWN"
            for row in [*names, *semantic_rows]
        },
        "classification": "SEARCH_RECORDED; classify AUTHORITATIVE/ACTIVE/FROZEN/EXPERIMENTAL/SUPERSEDED/REJECTED/UNKNOWN",
    }


def _initial_reuse_cache(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "initial": evidence,
        "incremental": [],
        "covered_created_paths": [],
        "last_created_hash": hashlib.sha256(b"[]").hexdigest(),
        "initialized_at": utc_now(),
    }


def _refresh_reuse_discovery_for_changes(
    task_id: str, changes: dict[str, Any], unit_ids: Sequence[str],
) -> bool:
    state = load_state(task_id)
    cache = dict(state.get("REUSE_DISCOVERY_CACHE") or _initial_reuse_cache(state.get("REUSE_EVIDENCE", {})))
    created = sorted(set(str(path) for path in changes.get("created", [])))
    created_hash = hashlib.sha256(json.dumps(created, separators=(",", ":")).encode("utf-8")).hexdigest()
    covered = set(cache.get("covered_created_paths", []))
    new_created = [path for path in created if path not in covered]
    if not new_created or created_hash == cache.get("last_created_hash"):
        return False
    units = [unit for unit_id in unit_ids if (unit := _unit_by_id(state, unit_id))]
    query = " ".join([
        *(Path(path).stem.replace("_", " ") for path in new_created),
        *(str(unit.get("objective", "")) for unit in units),
    ])[:2_000]
    roots = [
        root for root in DISCOVERY_ROOTS
        if any(path == root or path.startswith(root + "/") for path in new_created)
    ] or list(DISCOVERY_ROOTS)
    evidence = _discover_existing(query or state["GOAL"], roots)
    refreshes = list(cache.get("incremental", []))
    refreshes.append({
        "at": utc_now(), "created_paths": new_created, "evidence": evidence,
        "work_unit_ids": list(unit_ids),
    })
    cache.update({
        "incremental": refreshes[-20:],
        "covered_created_paths": sorted(covered | set(new_created)),
        "last_created_hash": created_hash,
    })

    def record(value: dict[str, Any]) -> None:
        value["REUSE_DISCOVERY_CACHE"] = cache
        _telemetry_add(value, discovery_incremental_refreshes=1)

    update_task(
        task_id,
        event="REUSE_DISCOVERY_INCREMENTAL_REFRESH",
        detail=f"created={','.join(new_created)};roots={','.join(roots)}",
        mutate=record,
    )
    return True


def assert_isolated_worktree_path(path: Path, main_repo: Path = REPO, root: Path | None = None) -> None:
    candidate = path.resolve()
    main = main_repo.resolve()
    allowed = (root or worktree_root()).resolve()
    if candidate.parent != allowed:
        raise HarnessError(f"WORKTREE_NOT_DIRECT_CHILD_OF_POLICY_ROOT:{candidate}")
    if candidate == main or main in candidate.parents or candidate in main.parents:
        raise HarnessError(f"WORKTREE_NOT_ISOLATED_FROM_PRIMARY:{candidate}")


def assert_registered_isolated_worktree(path: Path) -> None:
    assert_isolated_worktree_path(path)
    result = _git(["rev-parse", "--show-toplevel"], path)
    if result.returncode or Path(result.stdout.strip()).resolve() != path.resolve():
        raise HarnessError(f"WORKTREE_NOT_REGISTERED_OR_TOPLEVEL_MISMATCH:{path}")


def _worktree_create_failure(detail: str) -> str:
    if re.search(r"permission denied|access (?:is )?denied", detail, re.I):
        nested_codex = any(
            os.environ.get(name)
            for name in ("CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_SESSION_ID", "CODEX_THREAD_ID")
        )
        origin = "NESTED_CODEX_SANDBOX_PERMISSION_DENIED" if nested_codex else "HOST_ACL_PERMISSION_DENIED"
        return f"WORKTREE_CREATE_FAILED:{origin}:{detail}"
    return f"WORKTREE_CREATE_FAILED:{detail}"


def _create_worktree(task_id: str) -> tuple[Path, str, str]:
    root = worktree_root()
    path = root / f"harness-task-{task_id}"
    assert_isolated_worktree_path(path, REPO, root)
    if path.exists():
        raise HarnessError(f"WORKTREE_PATH_ALREADY_EXISTS_PRESERVE_FOR_REVIEW:{path}")
    branch = f"harness-task-{task_id}"
    head = _git(["rev-parse", "HEAD"], REPO).stdout.strip()
    if not head:
        raise HarnessError("PRIMARY_HEAD_UNAVAILABLE")
    existing = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], REPO)
    if existing.returncode == 0:
        raise HarnessError(f"WORKTREE_BRANCH_ALREADY_EXISTS_PRESERVE_FOR_REVIEW:{branch}")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HarnessError(f"EXTERNAL_WORKTREE_ROOT_UNAVAILABLE:{type(exc).__name__}:{exc}") from exc
    result = _git(["worktree", "add", "-b", branch, str(path), head], REPO, 120)
    if result.returncode or not path.is_dir():
        raise HarnessError(_worktree_create_failure(result.stderr.strip() or result.stdout.strip()))
    return path, branch, head


def _git_changes(worktree: Path) -> dict[str, Any]:
    status = _git(["status", "--porcelain=v1"], worktree).stdout.splitlines()
    changed: list[str] = []
    created: list[str] = []
    for row in status:
        if len(row) < 4:
            continue
        code, name = row[:2], row[3:]
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        name = name.strip('"').replace("\\", "/")
        changed.append(name)
        if code == "??" or "A" in code:
            created.append(name)
    dependency_lines: list[str] = []
    for name in changed:
        if Path(name).name.lower() not in DEPENDENCY_FILES:
            continue
        path = worktree / name
        if name in created and path.is_file():
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            additions = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        else:
            diff = _git(["diff", "--unified=0", "HEAD", "--", name], worktree).stdout.splitlines()
            additions = [line[1:].strip() for line in diff if line.startswith("+") and not line.startswith("+++") and line[1:].strip()]
        dependency_lines += [f"{name}:{line}" for line in additions]
    state = {
        "changed": sorted(set(changed))[:MAX_LIST_ITEMS],
        "created": sorted(set(created))[:MAX_LIST_ITEMS],
        "dependencies": dependency_lines[:MAX_LIST_ITEMS],
        "changed_count": len(set(changed)),
        "created_count": len(set(created)),
    }
    return state


def _worktree_progress_hash(worktree: Path) -> str:
    changes = _git_changes(worktree)
    digest = hashlib.sha256()
    digest.update(json.dumps(changes, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    diff = _git(["diff", "--no-ext-diff", "--binary", "HEAD"], worktree, 60)
    digest.update(diff.stdout.encode("utf-8", errors="replace"))
    for name in changes["created"]:
        path = worktree / name
        try:
            if path.is_file() and path.stat().st_size <= 2_000_000:
                digest.update(name.encode("utf-8"))
                digest.update(path.read_bytes())
        except OSError:
            digest.update(f"UNREADABLE:{name}".encode("utf-8"))
    return digest.hexdigest()


def _record_worker_checkpoint(task_id: str, phase: str) -> None:
    descriptions = {
        "TARGETED_TEST": (
            "Worker completed a focused-test checkpoint and remains active",
            "Focused tests provide worker-side evidence before controller validation.",
            "WORKER_TARGETED_TEST_CHECKPOINT",
        ),
        "SELF_REVIEW": (
            "Worker completed a diff-inspection checkpoint and remains active",
            "Worker self-review checks scope, correctness, reuse, and bloat before handoff.",
            "WORKER_SELF_REVIEW_CHECKPOINT",
        ),
    }
    if phase not in descriptions:
        raise HarnessError(f"UNKNOWN_WORKER_CHECKPOINT:{phase}")
    state = load_state(task_id)
    changes = _git_changes(Path(state["WORKTREE"]))
    current_action, why_current, last_completed = descriptions[phase]

    def mark_implementation_active(value: dict[str, Any]) -> None:
        _plan_update(
            value,
            "AUTONOMOUS_EXECUTION_LOOP" if int(value.get("HARNESS_VERSION", 2)) >= 3 else "IMPLEMENT",
            "IN_PROGRESS",
        )
        for unit_id in value.get("ACTIVE_WORK_UNIT_IDS", []):
            unit = _unit_by_id(value, unit_id)
            if unit is not None:
                unit["last_checkpoint"] = phase
                unit["next_action"] = "Continue the active worker batch"
        value["LAST_CHECKPOINT"] = f"WORKER_{phase}"

    update_task(task_id, {
        "CURRENT_PHASE": phase,
        "CURRENT_ACTION": current_action,
        "WHY_CURRENT_ACTION": why_current,
        "LAST_COMPLETED": last_completed,
        "NEXT_ACTION": "Finish the worker turn and report its validation",
        "WHY_NEXT_ACTION": "The worker must report tests and safety markers before controller validation.",
        "FILES_CHANGED": changes["changed"],
        "FILES_CREATED": changes["created"],
        "DEPENDENCIES_ADDED": changes["dependencies"],
    }, event=f"WORKER_{phase}", detail=(
        f"changed={changes['changed_count']};created={changes['created_count']};"
        "high-signal phase inferred from Codex event stream"
    ), mutate=mark_implementation_active)


def _codex_command() -> str:
    override = os.environ.get("USTQ_CODEX_COMMAND")
    if override:
        return override
    candidate = shutil.which("codex.cmd") if os.name == "nt" else shutil.which("codex")
    if not candidate:
        candidate = shutil.which("codex")
    if not candidate:
        raise HarnessError("CODEX_CLI_NOT_FOUND")
    return candidate


def _queue_control(state: dict[str, Any], message: str) -> tuple[bool, str]:
    thread_id = state.get("ACTIVE_THREAD_ID")
    if not thread_id:
        return False, "NO_ACTIVE_CODEX_THREAD; instruction retained in authoritative state"
    command = [_codex_command(), "queue", "--thread", thread_id, "--message", message]
    result = _run(command, Path(state.get("WORKTREE") or REPO), 30)
    detail = (result.stdout or result.stderr).strip()[:1_000]
    return result.returncode == 0, detail or f"exit={result.returncode}"


def _codex_exec_command(
    worktree: Path, sandbox: str, review: bool, writable_runtime: Path | None = None,
) -> list[str]:
    command = [_codex_command(), "--ask-for-approval", "never", "exec"]
    if review:
        command.append("--ephemeral")
    command += ["--json", "--sandbox", sandbox, "--cd", str(worktree)]
    if writable_runtime is not None:
        command += ["--add-dir", str(writable_runtime)]
    command.append("-")
    return command


def _planner_prompt(state: dict[str, Any]) -> str:
    reuse = json.dumps(state.get("REUSE_DISCOVERY_CACHE", {}), ensure_ascii=False, separators=(",", ":"))[:5_000]
    return f"""You are the read-only planning turn for one Harness R3 task. Do not modify files.

AUTHORIZED GOAL:
{state['GOAL']}

Task scope={state['TASK_SCOPE']}; task kind={state['TASK_KIND']}; safety flags={state['SAFETY_FLAGS']}.
Initial reuse evidence={reuse}

Inspect only relevant repository evidence and produce a compact plan of substantive work units. Batch closely related activity; do not create one unit per tiny edit or hypothesis. Units may be independent or dependency-linked. Prefer reuse/extension of AUTHORITATIVE or ACTIVE components; label FROZEN, EXPERIMENTAL, SUPERSEDED, REJECTED, or UNKNOWN evidence conservatively. Do not plan any action outside the authorized goal or hard research/storage boundaries.

End with two single-line markers. WORK_UNITS_JSON must be a compact JSON array of objects with: id, objective, dependencies, subsystem, relevant_paths, required_inputs, optional, reuse_decision, reuse_evidence. Use 2-12 units when the goal is genuinely decomposable; otherwise one substantive unit.
PLAN_STATUS=READY|FALLBACK_REQUIRED
WORK_UNITS_JSON=<compact single-line JSON array>
"""


def _consume_pending_steer(task_id: str) -> list[str]:
    state = load_state(task_id)
    pending = [str(value) for value in state.get("PENDING_STEER", [])]
    if not pending:
        return []

    def consume(value: dict[str, Any]) -> None:
        now = utc_now()
        history = list(value.get("STEERING_HISTORY", []))
        for instruction in pending:
            matching = next(
                (
                    row for row in reversed(history)
                    if row.get("instruction") == instruction and row.get("accepted") is True
                ),
                None,
            )
            if matching is not None:
                matching["applied"] = True
                matching["applied_at"] = now
            else:
                history.append({
                    "instruction": instruction, "accepted": True,
                    "applied": True, "applied_at": now,
                })
        value["STEERING_HISTORY"] = history[-20:]
        value["PENDING_STEER"] = []

    update_task(
        task_id, event="PENDING_STEER_CONSUMED",
        detail=f"count={len(pending)}", mutate=consume,
    )
    return pending


def _worker_prompt(
    state: dict[str, Any], correction: str = "", steering: Sequence[str] = (),
) -> str:
    steer = "\n".join(f"- {row}" for row in steering) or "- none"
    active = [
        unit for unit_id in state.get("ACTIVE_WORK_UNIT_IDS", [])
        if (unit := _unit_by_id(state, unit_id))
    ]
    active_json = json.dumps(active, ensure_ascii=False, separators=(",", ":"))[:8_000]
    reuse = json.dumps(state.get("REUSE_DISCOVERY_CACHE", {}), ensure_ascii=False, separators=(",", ":"))[:4_000]
    first_turn = int(state.get("TELEMETRY", {}).get("worker_turns", 0)) == 0
    goal = state["GOAL"] if first_turn else state["CURRENT_TASK"]
    correction_text = f"\nCORRECTION CONTEXT:\n{correction[:4_000]}\n" if correction else ""
    return f"""You are a substantive implementation worker for one authorized Harness R3 task.

AUTHORIZED GOAL {'(full)' if first_turn else '(compact summary)'} version {state['GOAL_VERSION']}:
{goal}

Task scope: {state['TASK_SCOPE']}
Structured task kind: {state['TASK_KIND']} ({state['TASK_KIND_SOURCE']})
Safety flags: {state['SAFETY_FLAGS']}
Applied human steering for this turn:
{steer}
{correction_text}

ACTIVE WORK-UNIT BATCH:
{active_json}

TASK-LOCAL REUSE CACHE:
{reuse}

Work only in this isolated Git worktree and already-authorized task-owned external runtime/cache/result roots. Ordinary mutation there is pre-authorized: do not request human approval for it. Use inherited external TEMP/TMP/TMPDIR and USTQ_CACHE_ROOT; create no worktree temp/cache residue. Never change ACLs, ownership, Windows permissions, writable-root configuration, or privilege level, and never use icacls/takeown. If one path is unwritable, use an already-authorized external task/runtime/cache/result root where valid; otherwise block only that work unit and continue independent authorized units. Read AGENTS.md and relevant maps. Search the named subsystem before any materially new component, but reuse the task-local cache instead of repeating a full repository scan. Classify candidates AUTHORITATIVE/ACTIVE/FROZEN/EXPERIMENTAL/SUPERSEDED/REJECTED/UNKNOWN. Extend, parameterize, call, repair, or consolidate before creating. Never create version-suffix families for an existing responsibility.

Do not use 2026+ outcomes for fitting, feature/parameter/threshold/portfolio-rule search, model selection, or winner selection. Preserve PIT ordering, canonical data, frozen assets, external evidence, unrelated work, and the repository-local .venv prohibition. Do not fetch Moomoo history, merge branches, promote to production, or start another task.

Complete as many closely related active units as practical in this turn. Run focused tests and inspect the diff. Only report PROTECTED_PERMISSION when the goal truly requires writing a protected/frozen/canonical asset, no authorized alternative exists, and actual permission-boundary expansion is required. An ordinary unwritable path is a local blocker. A local source/quota/coverage/test/permission failure blocks only its unit; continue another unit in this batch when independent. If context ends, checkpoint honestly. Never claim a test passed when it did not. If pytest is blocked by the known nested temporary-path WinError, preserve exact evidence for Controller classification. A negative research result is valid; never tune against exposed holdout feedback.

End with these concise markers. JSON values must be compact single-line JSON. Each WORK_UNIT_RESULTS_JSON object uses id, status (DONE|RETRY|BLOCKED_LOCAL|DEFERRED|SKIPPED_WITH_REASON), produced_outputs, validation_state, blocker, last_checkpoint, next_action, reuse_decision, reuse_evidence.
TASK_RESULT=COMPLETED|SOFTWARE_FAILURE|RESEARCH_FAILURE|WAITING_HUMAN|BLOCKED
TESTS_RUN=<commands and outcomes, or NONE>
VALIDATION_STATUS=PASS|FAIL|NOT_RUN
REUSE_DECISION=<what was reused/extended>
NEW_COMPONENT_JUSTIFICATION=<why each new persistent implementation was necessary, or NONE>
HOLDOUT_CONTAMINATION_RISK=NONE|<concise risk>
BLOCKER_KIND=NONE|LOCAL|AUTHORIZATION|SAFETY|DESTRUCTIVE|PROTECTED_PERMISSION
WORK_UNIT_RESULTS_JSON=<compact single-line JSON array>
CHANGED_PATHS_JSON=<compact single-line JSON array>
COMPLETED_WORK=<compact summary>
CURRENT_WORK=<compact summary or NONE>
REMAINING_WORK=<compact summary or NONE>
LOCAL_BLOCKERS=<compact summary or NONE>
TEST_STATE=<compact summary>
IMPORTANT_EVIDENCE=<compact summary>
REUSE_DECISIONS=<compact summary>
NEXT_BEST_ACTION=<compact summary>
"""


def _review_prompt(state: dict[str, Any]) -> str:
    unit_summary = json.dumps(state.get("WORK_UNITS", []), ensure_ascii=False, separators=(",", ":"))[:8_000]
    return f"""Perform the final independent READ-ONLY Harness R3 review of the uncommitted changes in this isolated worktree. Do not modify any file. Human goal: {state['GOAL']}

Work-unit summary: {unit_summary}

Inspect the final diff and relevant repository evidence. Source remains read-only; use inherited external temporary runtime for harmless inspection. Worker test status: {state.get('WORKER_TEST_STATUS')}; worker limitation: {state.get('WORKER_TEST_LIMITATION')}; Controller authoritative validation: {state.get('CONTROLLER_VALIDATION_STATUS')} with evidence {state.get('VALIDATION_RESULTS', [])}. If your pytest encounters exactly {WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION}, rely on Controller test evidence and continue source/scope/safety/reuse review. Assess goal completion, correctness, tests, PIT/leakage, exposed-2026 boundaries, declared data roles, Anti-Bloat, duplicate identities/implementations, frozen assets, unresolved local work, and whether deferred work invalidates completed outputs. Guard states: overfit={state['OVERFIT_GUARD']}; anti_bloat={state['ANTI_BLOAT']}; reuse={state['REUSE_GUARD']}.

End with exactly one classification line and concise findings:
REVIEW_STATUS=PASS|PASS_WITH_WARNINGS|FIX_REQUIRED|HUMAN_DECISION_REQUIRED
"""


def _parse_marker(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    return match.group(1).strip()[:MAX_TEXT] if match else ""


def _parse_json_marker(text: str, key: str, default: Any) -> Any:
    value = _parse_marker(text, key)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _pending_unit_results(
    state: dict[str, Any], message: str | None = None,
) -> list[dict[str, Any]]:
    raw = _parse_json_marker(
        state.get("WORKER_FINDINGS", "") if message is None else message,
        "WORK_UNIT_RESULTS_JSON", [],
    )
    if not isinstance(raw, list):
        raw = []
    by_id = {unit.get("id"): unit for unit in state.get("WORK_UNITS", [])}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = WORK_UNIT_STATUSES - {"READY", "RUNNING"}
    for row in raw:
        if not isinstance(row, dict):
            continue
        unit_id = str(row.get("id", ""))
        status = str(row.get("status", "")).upper()
        if unit_id not in by_id or unit_id in seen or status not in allowed:
            continue
        seen.add(unit_id)
        results.append({
            "id": unit_id,
            "status": status,
            "produced_outputs": list(row.get("produced_outputs", []))[:30],
            "validation_state": str(row.get("validation_state", "NOT_RUN"))[:100],
            "blocker": row.get("blocker", {}) if isinstance(row.get("blocker", {}), dict) else {"detail": str(row.get("blocker", ""))[:1_000]},
            "last_checkpoint": str(row.get("last_checkpoint", "WORKER_REPORTED"))[:500],
            "next_action": str(row.get("next_action", ""))[:1_000],
            "reuse_decision": str(row.get("reuse_decision", "UNKNOWN")).upper(),
            "reuse_evidence": list(row.get("reuse_evidence", []))[:20],
        })
    for unit_id in state.get("ACTIVE_WORK_UNIT_IDS", []):
        if unit_id not in seen:
            results.append({
                "id": unit_id, "status": "DONE", "produced_outputs": [],
                "validation_state": "WORKER_REPORTED_COMPLETE", "blocker": {},
                "last_checkpoint": "WORKER_TURN_COMPLETED", "next_action": "Controller validation",
                "reuse_decision": "UNKNOWN", "reuse_evidence": [],
            })
    return results


def _phase_from_command(command: str) -> str | None:
    text = command.strip()
    for _ in range(3):
        if text.startswith("&"):
            text = text[1:].lstrip()
        match = re.match(r'''(?x)(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))(.*)\Z''', text, re.S)
        if not match:
            return None
        executable = next(value for value in match.groups()[:3] if value is not None)
        arguments = match.group(4).strip()
        head = re.split(r"[\\/]", executable)[-1].lower()
        if head in {"powershell", "powershell.exe", "pwsh", "pwsh.exe", "cmd", "cmd.exe", "bash", "sh"}:
            shell_command = re.search(r"(?:^|\s)(?:-command|-c|/c)\s+(.+)\Z", arguments, re.I | re.S)
            if not shell_command:
                return None
            text = shell_command.group(1).strip()
            if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
                text = text[1:-1].strip()
            continue
        if re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", head):
            if re.search(r"(?:^|\s)-m\s+(?:pytest|unittest)(?:\s|\Z)", arguments, re.I):
                return "TARGETED_TEST"
            return None
        if re.fullmatch(r"pytest(?:\.exe)?", head):
            return "TARGETED_TEST"
        if re.fullmatch(r"git(?:\.exe)?", head) and re.match(r"diff(?:\s|\Z)", arguments, re.I):
            return "SELF_REVIEW"
        return None
    return None


def _known_windows_codex_pytest_temp_limitation(evidence: str) -> bool:
    """Recognize only the reproduced nested-Windows pytest temp ACL signature."""
    permission = re.search(r"PermissionError", evidence, re.I) and re.search(
        r"(?:\[?WinError\s*5\]?|Access is denied)", evidence, re.I,
    )
    pytest_temp_frame = re.search(r"_pytest[\\/](?:tmpdir|pathlib)\.py", evidence, re.I)
    temp_operation = re.search(
        r"pytest-of-|tmp_path|--basetemp|\bbasetemp\b|cleanup_dead_symlinks|make_numbered_dir",
        evidence,
        re.I,
    )
    real_failure = re.search(
        r"AssertionError|SyntaxError|ImportError|ModuleNotFoundError",
        evidence,
        re.I,
    )
    return bool(permission and pytest_temp_frame and temp_operation and not real_failure)


def _command_event_output(item: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("aggregated_output", "output", "stdout", "stderr"):
        value = item.get(key)
        if value in (None, ""):
            continue
        chunks.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str))
    return "\n".join(chunks)[-4_000:]


def _classify_worker_test_execution(
    test_results: Sequence[dict[str, Any]], final_message: str, worker_exit_code: int,
) -> tuple[str, str, str]:
    if not test_results:
        return "NOT_RUN", "", ""
    failures = [row for row in test_results if str(row.get("exit_code")) != "0"]
    if not failures:
        return "PASS", "", ""
    evidence_rows = [
        f"{row.get('command', '')}\n{row.get('output', '')}\n{final_message}"
        for row in failures
    ]
    evidence = "\n\n".join(evidence_rows)[-MAX_TEXT:]
    if worker_exit_code == 0 and all(
        _known_windows_codex_pytest_temp_limitation(row) for row in evidence_rows
    ):
        return "ENVIRONMENT_LIMITED", WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION, evidence
    return "REAL_TEST_FAILURE", "", evidence


def _run_codex_turn(
    task_id: str, prompt: str, *, review: bool = False, role: str = "",
) -> dict[str, Any]:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    assert_registered_isolated_worktree(worktree)
    runtime = _ensure_task_temp_runtime(task_id)
    kind = "REVIEW" if review else (role.upper() or "WORKER")
    if kind not in {"WORKER", "PLANNER", "REVIEW"}:
        raise HarnessError(f"UNKNOWN_CODEX_TURN_ROLE:{kind}")
    mutating_worker = kind == "WORKER"
    read_only = not mutating_worker
    sandbox = "read-only" if read_only else "workspace-write"
    command = _codex_exec_command(worktree, sandbox, read_only, runtime)
    environment = _task_temp_environment(runtime)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    turn_started = time.monotonic()
    try:
        process = subprocess.Popen(
            command, cwd=str(worktree), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=flags, env=environment,
        )
    except OSError as exc:
        raise HarnessError(f"CODEX_LAUNCH_FAILED:{type(exc).__name__}:{exc}") from exc
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()
    lifecycle_phase = {
        "WORKER": "AUTONOMOUS_EXECUTION_LOOP",
        "PLANNER": "PLAN",
        "REVIEW": "FINAL_INDEPENDENT_REVIEW",
    }[kind]
    worker_status = {"WORKER": "RUNNING", "PLANNER": "PLANNER_RUNNING", "REVIEW": "REVIEW_RUNNING"}[kind]
    started_fields = {
        "WORKER_STATUS": worker_status,
        "WORKER_PID": process.pid,
        "ACTIVE_PROCESS_KIND": kind,
        "ACTIVE_THREAD_ID": "",
        "CURRENT_PHASE": lifecycle_phase,
        "CURRENT_ACTION": f"Codex {kind.lower()} turn is active in the isolated worktree",
        "WHY_CURRENT_ACTION": (
            "Read-only independence is required for final review." if kind == "REVIEW"
            else "Read-only decomposition uses repository evidence without mutation." if kind == "PLANNER"
            else "The worker may execute only the selected authorized work-unit batch."
        ),
        "NEXT_ACTION": f"Complete the Codex {kind.lower()} turn",
        "WHY_NEXT_ACTION": "A completed turn is a checkpoint, not a human lifecycle boundary.",
    }
    if mutating_worker:
        started_fields["TEST_HISTORY_START_INDEX"] = len(state.get("TESTS_RUN", []))
        started_fields["WORKER_TEST_STATUS"] = "NOT_RUN"
        started_fields["WORKER_TEST_LIMITATION"] = ""
        started_fields["WORKER_TEST_EVIDENCE"] = ""
        started_fields["CONTROLLER_VALIDATION_STATUS"] = "NOT_RUN"

    def mark_turn_active(value: dict[str, Any]) -> None:
        _plan_update(value, lifecycle_phase, "IN_PROGRESS")

    update_task(
        task_id, started_fields, event=f"{kind}_STARTED",
        detail=f"pid={process.pid};sandbox={sandbox};temp_runtime={runtime}", mutate=mark_turn_active,
    )

    tail: deque[str] = deque(maxlen=20)
    final_message = ""
    tests: list[str] = []
    test_results: list[dict[str, Any]] = []
    seen_phase = ""
    for raw in process.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            tail.append(line[:1_000])
            continue
        if event.get("type") == "thread.started":
            thread_id = str(event.get("thread_id", ""))
            fields = {"ACTIVE_THREAD_ID": thread_id}
            if mutating_worker:
                fields["WORKER_THREAD_ID"] = thread_id
            update_task(task_id, fields, event=f"{kind}_THREAD_READY", detail=thread_id)
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final_message = str(item.get("text", ""))[-MAX_TEXT:]
            if mutating_worker and _parse_marker(final_message, "WORK_UNIT_RESULTS_JSON"):
                checkpoint_state = load_state(task_id)
                checkpoint_results = _pending_unit_results(checkpoint_state, final_message)

                def persist_checkpoint(value: dict[str, Any]) -> None:
                    value["PENDING_UNIT_RESULTS"] = checkpoint_results
                    value["LAST_CHECKPOINT"] = "WORKER_STRUCTURED_CHECKPOINT"
                    for result_row in checkpoint_results:
                        unit = _unit_by_id(value, str(result_row.get("id", "")))
                        if unit is not None:
                            unit["last_checkpoint"] = str(result_row.get("last_checkpoint", "WORKER_STRUCTURED_CHECKPOINT"))

                update_task(
                    task_id, event="WORKER_STRUCTURED_CHECKPOINT",
                    detail=f"units={','.join(str(row.get('id')) for row in checkpoint_results)}",
                    mutate=persist_checkpoint,
                )
        if event.get("type") in {"error", "turn.failed"}:
            tail.append(json.dumps(event, ensure_ascii=False, default=str)[:2_000])
        if item.get("type") == "command_execution":
            command_text = str(item.get("command", ""))
            command_phase = _phase_from_command(command_text)
            if command_phase and command_phase != seen_phase and mutating_worker and event.get("type") == "item.completed":
                seen_phase = command_phase
                _record_worker_checkpoint(task_id, command_phase)
            if command_phase == "TARGETED_TEST" and event.get("type") == "item.completed":
                command_exit = item.get("exit_code", "UNKNOWN")
                tests.append(f"{command_text[:500]} | exit={command_exit}")
                test_results.append({
                    "command": command_text[:1_000],
                    "exit_code": command_exit,
                    "output": _command_event_output(item),
                })
        current = load_state(task_id)
        if current["PAUSE_REQUESTED"] or current["STOP_REQUESTED"]:
            # The control command queues a cooperative checkpoint message. Never kill a writer.
            continue
    exit_code = process.wait()
    if not final_message and tail:
        final_message = "\n".join(tail)[-MAX_TEXT:]
    worker_test_status, worker_test_limitation, worker_test_evidence = _classify_worker_test_execution(
        test_results, final_message, exit_code,
    )
    history = load_state(task_id).get("TESTS_RUN", [])
    combined_tests = (history + tests)[-MAX_LIST_ITEMS:]
    if mutating_worker:
        _refresh_changes(task_id, worker_findings=final_message)
    elapsed = max(0.0, time.monotonic() - turn_started)
    completed_fields = {
        "WORKER_STATUS": f"{kind}_EXITED_{exit_code}" if kind != "WORKER" else f"EXITED_{exit_code}",
        "WORKER_PID": None,
        "ACTIVE_PROCESS_KIND": "",
        "ACTIVE_THREAD_ID": "",
        "TESTS_RUN": combined_tests,
        "CURRENT_PHASE": lifecycle_phase,
        "CURRENT_ACTION": f"Codex {kind.lower()} turn completed; its result awaits classification",
        "WHY_CURRENT_ACTION": "Process completion is recorded separately from acceptance of its findings.",
        "LAST_COMPLETED": f"{kind}_TURN_COMPLETED",
        "NEXT_ACTION": f"Classify the completed {kind.lower()} result",
        "WHY_NEXT_ACTION": "The controller must choose validation, correction, finalization, or human review from explicit result markers.",
    }
    if kind == "REVIEW":
        completed_fields["REVIEW_FINDINGS"] = final_message
    elif kind == "PLANNER":
        completed_fields["PLANNER_FINDINGS"] = final_message
    else:
        completed_fields["TEST_HISTORY_START_INDEX"] = max(0, len(combined_tests) - min(len(tests), MAX_LIST_ITEMS))
        completed_fields["WORKER_TEST_STATUS"] = worker_test_status
        completed_fields["WORKER_TEST_LIMITATION"] = worker_test_limitation
        completed_fields["WORKER_TEST_EVIDENCE"] = worker_test_evidence

    def mark_turn_completed(value: dict[str, Any]) -> None:
        if kind == "WORKER":
            _telemetry_add(value, worker_wall_seconds=elapsed, worker_turns=1)
        elif kind == "REVIEW":
            _telemetry_add(value, reviewer_wall_seconds=elapsed, reviewer_turns=1)
        else:
            _telemetry_add(value, planner_turns=1)
        _meaningful_progress(value, f"{kind}_TURN_COMPLETED")

    update_task(
        task_id, completed_fields, event=f"{kind}_COMPLETED",
        detail=f"exit={exit_code};worker_test_status={worker_test_status if mutating_worker else kind + '_NOT_CLASSIFIED'}",
        mutate=mark_turn_completed,
    )
    if exit_code and re.search(r"failed to initialize (?:in-process )?app-server|not logged in|authentication required|usage limit|rate limit", final_message, re.I):
        raise HarnessError(f"CODEX_INTERFACE_UNAVAILABLE:{final_message[-2_000:]}")
    return {"exit_code": exit_code, "message": final_message, "tests": tests}


def _valid_component_justification(value: str) -> bool:
    return bool(value.strip()) and value.strip().upper() != "NONE"


def _deduplicated_blockers(blockers: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        normalized = {
            "code": str(blocker.get("code", "")),
            "detail": str(blocker.get("detail", ""))[:2_000],
        }
        key = (normalized["code"], normalized["detail"])
        if key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique[-MAX_LIST_ITEMS:]


def _legacy_justified_created_paths(
    task_id: str, state: dict[str, Any], current_created: Sequence[str],
) -> set[str]:
    """Recover only created paths proven to predate a correction in legacy state."""
    if "JUSTIFIED_CREATED_PATHS" in state:
        return set()
    prior_justification = str(state.get("NEW_COMPONENT_JUSTIFICATION", ""))
    if _valid_component_justification(prior_justification):
        return {str(path) for path in state.get("FILES_CREATED", [])}
    if (
        not current_created
        or int(state.get("CORRECTION_ATTEMPTS", 0)) < 1
        or state.get("LAST_REVIEW_STATUS") != "FIX_REQUIRED"
    ):
        return set()

    try:
        rows = [
            json.loads(line)
            for line in timeline_path(task_id).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return set()
    correction_index = next(
        (
            index for index, row in enumerate(rows)
            if str(row.get("event", "")).endswith("_CORRECTION_REQUESTED")
        ),
        None,
    )
    if correction_index is None:
        return set()
    before_correction = rows[:correction_index]
    validation_passed = any(
        row.get("event") == "TARGETED_VALIDATION_COMPLETED"
        and str(row.get("detail", "")).startswith("tests=PASS;")
        for row in before_correction
    )
    review_required_correction = any(
        row.get("event") == "REVIEW_CLASSIFIED"
        and row.get("detail") == "FIX_REQUIRED"
        for row in before_correction
    )
    created_counts = [
        int(match.group(1))
        for row in before_correction
        if row.get("event") == "CHANGE_INVENTORY"
        if (match := re.search(r"(?:^|;)created=(\d+)(?:;|$)", str(row.get("detail", ""))))
    ]
    if (
        not validation_passed
        or not review_required_correction
        or not created_counts
        or created_counts[-1] != len(current_created)
    ):
        return set()

    worktree = str(state.get("WORKTREE", "")).replace("\\", "/").rstrip("/")
    review_evidence = str(state.get("REVIEW_FINDINGS", "")).replace("\\", "/").casefold()
    if not worktree or not review_evidence:
        return set()
    current = {str(path) for path in current_created}
    reviewed_paths = {
        f"{worktree}/{path.replace(chr(92), '/')}".casefold()
        for path in current
    }
    if all(
        re.search(rf"{re.escape(path)}:\d+(?=$|[\s>)])", review_evidence)
        for path in reviewed_paths
    ):
        return current
    return set()


def _refresh_changes(task_id: str, *, worker_findings: str | None = None) -> dict[str, Any]:
    state = load_state(task_id)
    changes = _git_changes(Path(state["WORKTREE"]))
    prior_justification = str(state.get("NEW_COMPONENT_JUSTIFICATION", ""))
    reported_justification = (
        _parse_marker(worker_findings, "NEW_COMPONENT_JUSTIFICATION")
        if worker_findings is not None else ""
    )
    justified = {str(path) for path in state.get("JUSTIFIED_CREATED_PATHS", [])}
    if "JUSTIFIED_CREATED_PATHS" not in state:
        justified.update(_legacy_justified_created_paths(task_id, state, changes["created"]))
    if _valid_component_justification(reported_justification):
        justified.update(str(path) for path in changes["created"])
        justification = reported_justification
    elif _valid_component_justification(prior_justification):
        justification = prior_justification
    elif justified:
        justification = "INHERITED_VALIDATED_PRE_CORRECTION_JUSTIFICATION"
    else:
        justification = reported_justification
    unjustified = sorted(set(changes["created"]) - justified)
    reuse = (
        "HARD_BLOCKER_NEW_COMPONENT_JUSTIFICATION_MISSING"
        if unjustified else "PASS_SEARCH_RECORDED"
    )
    fields = {
        "FILES_CHANGED": changes["changed"],
        "FILES_CREATED": changes["created"],
        "DEPENDENCIES_ADDED": changes["dependencies"],
        "NEW_COMPONENT_JUSTIFICATION": justification,
        "JUSTIFIED_CREATED_PATHS": sorted(justified),
        "UNJUSTIFIED_CREATED_PATHS": unjustified,
        "REUSE_GUARD": reuse,
        "WORKTREE_INVENTORY_STATUS": "KNOWN",
        "BLOCKERS": _deduplicated_blockers(state.get("BLOCKERS", [])),
    }
    if worker_findings is not None:
        fields["WORKER_FINDINGS"] = worker_findings
    update_task(
        task_id,
        fields,
        event="CHANGE_INVENTORY",
        detail=f"changed={changes['changed_count']};created={changes['created_count']};dependencies={len(changes['dependencies'])}",
    )
    return changes


def _candidate_tests(worktree: Path, changed: Sequence[str]) -> list[str]:
    candidates: list[str] = []
    for name in changed:
        path = Path(name)
        if path.suffix.lower() != ".py":
            continue
        if path.name.startswith("test_"):
            candidates.append(path.as_posix())
            continue
        paired = path.with_name(f"test_{path.name}")
        if (worktree / paired).is_file():
            candidates.append(paired.as_posix())
    return list(dict.fromkeys(candidates))[:10]


def _latest_worker_reported_test_status(state: dict[str, Any]) -> str:
    tests = state.get("TESTS_RUN", [])
    start = max(0, min(int(state.get("TEST_HISTORY_START_INDEX", 0)), len(tests)))
    latest: dict[str, bool] = {}
    for row in tests[start:]:
        outcome = re.search(r"\|\s*exit=([^\s|]+)", row, re.I)
        if not outcome:
            continue
        command = row[:outcome.start()].strip()
        normalized = re.sub(r"\s+", " ", command).casefold()
        if normalized:
            latest[normalized] = outcome.group(1) == "0"
    if any(not passed for passed in latest.values()):
        return "REAL_TEST_FAILURE"
    if latest:
        return "PASS"
    return "NOT_RUN"


def _validate_targeted(
    task_id: str, changed: Sequence[str] | None = None,
) -> tuple[bool, str]:
    state = load_state(task_id)
    tests = state.get("TESTS_RUN", [])
    worker_report = state.get("WORKER_TEST_STATUS") or _latest_worker_reported_test_status(state)
    worktree = Path(state["WORKTREE"])
    candidates = _candidate_tests(worktree, changed if changed is not None else state.get("FILES_CHANGED", []))
    if not candidates:
        return True, (
            "Controller found no paired automatic test mapping; independent review must assess validation. "
            f"Worker test status={worker_report} is recorded but is not authoritative."
        )
    python = _storage_paths().python_exe
    base_temp = (task_dir(task_id) / "pytest-temp").resolve()
    if REPO == base_temp or REPO in base_temp.parents:
        raise HarnessError(f"PYTEST_TEMP_ROOT_INSIDE_REPOSITORY:{base_temp}")
    result = _run(
        [
            str(python), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--basetemp", str(base_temp), *candidates,
        ],
        worktree,
        300,
    )
    summary = (result.stdout + "\n" + result.stderr).strip()[-4_000:]
    row = f"{' '.join(candidates)} | exit={result.returncode} | {summary}"
    update_task(task_id, {"TESTS_RUN": (tests + [row])[-MAX_LIST_ITEMS:]})
    detail = summary or f"exit={result.returncode}"
    return result.returncode == 0, f"Controller-owned focused pytest: {detail}"


def _guard_summary(preflight: dict[str, Any]) -> tuple[str, str]:
    applicable = preflight["applicable_hard_blocker_count"]
    overfit_codes = {
        "A2_2026_HOLDOUT_ALREADY_EXPOSED", "OBVIOUS_CHANGED_TRAINING_BOUNDARY",
        "RESEARCH_REGISTRY_2026_REUSE", "SUCCESSOR_TRAINING_BOUNDARY",
        "FORWARD_SHADOW_UNSAFE_CAPABILITY", "TRIAL_JUDGE_GATE_WEAKENED",
    }
    overfit = "HARD_BLOCKER" if any(
        row["level"] == "HARD_BLOCKER" and row["code"] in overfit_codes
        and ("all" in row["blocks"] or preflight["task_scope"] in row["blocks"])
        for row in preflight["findings"]
    ) else "PASS"
    anti_rows = [row for row in preflight["findings"] if row["code"].startswith("ANTI_BLOAT") or row["code"].startswith("FROZEN_LEGACY")]
    anti_hard = any(row["level"] == "HARD_BLOCKER" and ("all" in row["blocks"] or preflight["task_scope"] in row["blocks"]) for row in anti_rows)
    anti_warn = any(row["level"] == "SOFT_WARNING" for row in anti_rows)
    anti = "HARD_BLOCKER" if anti_hard else "PASS_WITH_KNOWN_SCOPED_WARNING" if anti_warn else "PASS"
    if applicable and overfit == "PASS" and anti == "PASS":
        overfit = "HARD_BLOCKER_OTHER_R1_GUARD"
    return overfit, anti


def _accounting_residue(preflight: dict[str, Any]) -> list[str]:
    return sorted({
        path.strip()
        for row in preflight["findings"]
        if row["level"] == "HARD_BLOCKER" and row["code"] == "ANTI_BLOAT_ACCOUNTING_INCOMPLETE"
        for path in row["detail"].split(",")
        if path.strip()
    })[:MAX_LIST_ITEMS]


def _run_preflight_for(task_id: str, repo: Path, *, baseline_checkpoint: bool = False) -> dict[str, Any]:
    state = load_state(task_id)
    result = _load_r1().run_preflight(repo=repo, task_scope=state["TASK_SCOPE"])
    overfit, anti = _guard_summary(result)
    residue = _accounting_residue(result)
    applicable_hard = [
        row for row in result["findings"]
        if row["level"] == "HARD_BLOCKER"
        and ("all" in row["blocks"] or result["task_scope"] in row["blocks"])
    ]
    anti_hard = [
        row for row in applicable_hard
        if row["code"].startswith("ANTI_BLOAT") or row["code"].startswith("FROZEN_LEGACY")
    ]
    budget = next((row["detail"] for row in result["findings"] if row["code"] == "ANTI_BLOAT_BUDGET"), "")
    match = re.search(r"worktree_bytes=(\d+)", budget)
    bytes_value = int(match.group(1)) if match else None
    budget_passed = any(
        row["level"] == "PASS" and row["code"] == "ANTI_BLOAT_BUDGET"
        for row in result["findings"]
    )
    anti_delta = "PASS" if anti != "HARD_BLOCKER" else "FAIL_UNATTRIBUTED_HARD_BLOCKER"
    accounting_only_repository_blocker = (
        anti == "HARD_BLOCKER"
        and residue
        and anti_hard
        and all(row["code"] == "ANTI_BLOAT_ACCOUNTING_INCOMPLETE" for row in anti_hard)
        and budget_passed
        and not state.get("DEPENDENCIES_ADDED")
    )
    pre_existing_accounting = False
    if accounting_only_repository_blocker:
        # Preserve the repository-level accounting evidence independently of
        # whether this task's baseline proves that its own delta is clean.
        anti = "PRE_EXISTING_ACCOUNTING_RESIDUE"
        baseline = set(state.get("ANTI_BLOAT_BASELINE_RESIDUE", []))
        if baseline_checkpoint or not (set(residue) - baseline):
            anti_delta = "PASS"
            pre_existing_accounting = True
        else:
            anti = "HARD_BLOCKER_NEW_TASK_CAUSED_BLOAT"
            anti_delta = "FAIL_NEW_TASK_CAUSED_BLOAT"
    task_blocker_count = sum(
        not (pre_existing_accounting and row["code"] == "ANTI_BLOAT_ACCOUNTING_INCOMPLETE")
        for row in applicable_hard
    )
    return {
        "result": result,
        "overfit": overfit,
        "anti": anti,
        "anti_delta": anti_delta,
        "accounting_residue": residue,
        "bytes": bytes_value,
        "task_blocker_count": task_blocker_count,
    }


def _control_checkpoint(task_id: str) -> bool:
    state = load_state(task_id)
    if state["STOP_REQUESTED"]:
        update_task(task_id, {
            "CURRENT_PHASE": "STOPPED",
            "CURRENT_ACTION": "Autonomous execution stopped; useful worktree preserved",
            "WHY_CURRENT_ACTION": "Human stop has precedence and R2 never deletes or merges useful changes.",
            "NEXT_ACTION": "Human inspects or integrates the preserved worktree",
            "WHY_NEXT_ACTION": "Further work requires a new explicit human command.",
            "HUMAN_ATTENTION_REQUIRED": True,
        }, new_state="STOPPED", event="TASK_STOPPED", detail="No new autonomous action dispatched")
        return True
    if state["PAUSE_REQUESTED"]:
        update_task(task_id, {
            "CURRENT_PHASE": "PAUSED",
            "CURRENT_ACTION": "Paused at a safe dispatch checkpoint",
            "WHY_CURRENT_ACTION": "Human pause prevents dispatch of the next autonomous action.",
            "NEXT_ACTION": state.get("NEXT_ACTION", "Resume from authoritative state"),
            "WHY_NEXT_ACTION": "Resume continues from NEXT_ACTION_CODE without discarding the worktree.",
        }, new_state="PAUSED", event="TASK_PAUSED", detail=f"resume_point={state.get('NEXT_ACTION_CODE')}")
        return True
    return False


def _append_unique_blocker(state: dict[str, Any], code: str, detail: str) -> None:
    candidate = {"code": code, "detail": detail[:2_000]}
    state["BLOCKERS"] = _deduplicated_blockers([*state.get("BLOCKERS", []), candidate])


def _blocker_identity(code: str, detail: str, scope: str = "GLOBAL") -> str:
    normalized = re.sub(r"\s+", " ", detail.casefold()).strip()[:1_000]
    payload = f"{scope}:{code}:{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _append_active_blocker(
    state: dict[str, Any], code: str, detail: str, boundary_kind: str,
) -> None:
    identity = _blocker_identity(code, detail)
    rows = [
        row for row in state.get("ACTIVE_BLOCKERS", [])
        if row.get("identity") != identity
    ]
    rows.append({
        "identity": identity,
        "code": code[:120],
        "detail": detail[:2_000],
        "boundary_kind": boundary_kind,
        "first_seen_at": next(
            (
                row.get("first_seen_at") for row in state.get("ACTIVE_BLOCKERS", [])
                if row.get("identity") == identity
            ),
            utc_now(),
        ),
    })
    state["ACTIVE_BLOCKERS"] = rows[-MAX_LIST_ITEMS:]
    _append_unique_blocker(state, code, detail)


def _resolve_active_blockers(state: dict[str, Any], *, code: str | None = None) -> None:
    resolved: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for row in state.get("ACTIVE_BLOCKERS", []):
        if code is None or row.get("code") == code:
            resolved.append({**row, "resolved_at": utc_now()})
        else:
            active.append(row)
    state["ACTIVE_BLOCKERS"] = active
    state["RESOLVED_FINDINGS"] = [
        *state.get("RESOLVED_FINDINGS", []), *resolved,
    ][-MAX_LIST_ITEMS:]


def _record_local_blocker(
    task_id: str, unit_ids: Sequence[str], code: str, detail: str,
    *, progress_hash: str = "",
) -> None:
    def mutate(state: dict[str, Any]) -> None:
        _record_unit_failure(
            state, unit_ids, code, detail, progress_hash,
            retry_limit=0,
        )
        rows = list(state.get("LOCAL_BLOCKED_WORK", []))
        for unit_id in unit_ids:
            identity = _blocker_identity(code, detail, unit_id)
            rows = [row for row in rows if row.get("identity") != identity]
            rows.append({
                "identity": identity, "work_unit_id": unit_id,
                "code": code[:120], "detail": detail[:2_000], "at": utc_now(),
            })
        state["LOCAL_BLOCKED_WORK"] = rows[-MAX_LIST_ITEMS:]
        if _runnable_work_units(state):
            _telemetry_add(state, local_blockers_bypassed=1)
        _meaningful_progress(state, f"LOCAL_BLOCKER:{code}")

    update_task(
        task_id, event="WORK_UNIT_BLOCKED_LOCAL",
        detail=f"units={','.join(unit_ids)};code={code};{detail[:500]}", mutate=mutate,
    )


def _apply_validated_unit_results(state: dict[str, Any]) -> None:
    pending = state.get("PENDING_UNIT_RESULTS", []) or _pending_unit_results(state)
    active_ids = set(state.get("ACTIVE_WORK_UNIT_IDS", []))
    completed = 0
    reuse_hits = 0
    newly_local_blocked = 0
    local_rows = list(state.get("LOCAL_BLOCKED_WORK", []))
    for result in pending:
        if result.get("id") not in active_ids:
            continue
        unit = _unit_by_id(state, str(result["id"]))
        if unit is None:
            continue
        prior_status = unit.get("status")
        status = str(result.get("status", "DONE"))
        unit.update({
            "status": status,
            "produced_outputs": list(dict.fromkeys([
                *unit.get("produced_outputs", []), *result.get("produced_outputs", []),
            ]))[:30],
            "validation_state": "PASS" if status == "DONE" else result.get("validation_state", "NOT_RUN"),
            "blocker": result.get("blocker", {}),
            "last_checkpoint": result.get("last_checkpoint", "CONTROLLER_VALIDATED"),
            "next_action": result.get("next_action", "") or (
                "No further action" if status == "DONE" else "Reconsider when prerequisites change"
            ),
        })
        reuse_decision = str(result.get("reuse_decision", "UNKNOWN")).upper()
        if reuse_decision in {"REUSE", "EXTEND", "CREATE", "UNKNOWN"}:
            unit["reuse_decision"] = reuse_decision
        unit["reuse_evidence"] = list(dict.fromkeys([
            *unit.get("reuse_evidence", []), *result.get("reuse_evidence", []),
        ]))[:20]
        if prior_status != "DONE" and status == "DONE":
            completed += 1
        if reuse_decision in {"REUSE", "EXTEND"}:
            reuse_hits += 1
        if status == "BLOCKED_LOCAL":
            newly_local_blocked += int(prior_status != "BLOCKED_LOCAL")
            blocker = unit.get("blocker", {})
            detail = str(blocker.get("detail", blocker))
            identity = _blocker_identity(str(blocker.get("code", "LOCAL_BLOCKER")), detail, str(unit["id"]))
            local_rows = [row for row in local_rows if row.get("identity") != identity]
            local_rows.append({
                "identity": identity, "work_unit_id": unit["id"],
                "code": str(blocker.get("code", "LOCAL_BLOCKER")),
                "detail": detail[:2_000], "at": utc_now(),
            })
    state["LOCAL_BLOCKED_WORK"] = local_rows[-MAX_LIST_ITEMS:]
    state["PENDING_UNIT_RESULTS"] = []
    state["ACTIVE_WORK_UNIT_IDS"] = []
    state["ACTIVE_WORK_UNIT_ID"] = ""
    state["CURRENT_WORK_UNIT"] = ""
    state["CURRENT_RETRY_SIGNATURE"] = ""
    state["CURRENT_RETRY_COUNT"] = 0
    _telemetry_add(
        state,
        work_units_completed=completed,
        reuse_hits=reuse_hits,
        local_blockers_bypassed=(newly_local_blocked if _runnable_work_units(state) else 0),
    )
    _meaningful_progress(state, f"WORK_UNITS_VALIDATED:{completed}")


def _queue_correction_work_unit(
    state: dict[str, Any], source: str, detail: str, progress_hash: str,
    relevant_paths: Sequence[str] = (),
) -> bool:
    signature = _failure_signature(source, detail)
    existing = next(
        (
            unit for unit in state.get("WORK_UNITS", [])
            if unit.get("failure_signature") == signature
            and unit.get("status") in {"READY", "RETRY", "RUNNING"}
        ),
        None,
    )
    if existing is not None:
        _telemetry_add(state, repeated_work_prevented=1)
        return True
    key = f"FINAL:{signature}"
    prior = state.setdefault("RETRY_LEDGER", {}).get(key, {})
    count = int(prior.get("count", 0)) + 1 if prior.get("progress_hash") == progress_hash else 1
    state["RETRY_LEDGER"][key] = {
        "count": count, "progress_hash": progress_hash,
        "last_attempted_remedy": source[:200], "last_detail": detail[:1_000],
        "updated_at": utc_now(),
    }
    state["CURRENT_RETRY_SIGNATURE"] = signature
    state["CURRENT_RETRY_COUNT"] = count
    if count > DEFAULT_FAILURE_RETRY_LIMIT:
        return False
    next_number = 1 + sum(str(unit.get("id", "")).startswith("FIX-") for unit in state.get("WORK_UNITS", []))
    unit = _new_work_unit(
        f"FIX-{next_number:03d}",
        f"Correct the in-scope {source.lower()} finding: {detail[:700]}",
        subsystem="correction",
        relevant_paths=relevant_paths,
        reuse_decision="EXTEND",
        reuse_evidence=[f"Correction extends the existing task diff; signature={signature}"],
    )
    unit["failure_signature"] = signature
    unit["last_checkpoint"] = "CORRECTION_GENERATED"
    state.setdefault("WORK_UNITS", []).append(unit)
    state["FINAL_REVIEW_ATTEMPTS"] = int(state.get("FINAL_REVIEW_ATTEMPTS", 0)) + int(source == "FINAL_REVIEW")
    _meaningful_progress(state, f"CORRECTION_WORK_UNIT:{unit['id']}")
    return True


def _block(task_id: str, code: str, detail: str) -> None:
    def mutate(state: dict[str, Any]) -> None:
        _append_active_blocker(state, code, detail, "SAFETY")
        _close_active_plan(state, "FAILED")

    update_task(task_id, {
        "CURRENT_PHASE": "BLOCKED",
        "CURRENT_ACTION": "Execution blocked; state and useful work are preserved",
        "WHY_CURRENT_ACTION": detail[:MAX_TEXT],
        "NEXT_ACTION": "Human inspects blocker and explicitly resumes or stops",
        "WHY_NEXT_ACTION": "Fail-closed continuation prevents unsafe mutation or invalid research.",
        "HUMAN_ATTENTION_REQUIRED": True,
        "WORKER_STATUS": "BLOCKED",
    }, new_state="BLOCKED", event="HARD_BLOCKER", detail=f"{code}:{detail}", mutate=mutate)


def _wait_human(
    task_id: str, code: str, detail: str, *, boundary_kind: str = "EXHAUSTED",
) -> None:
    if boundary_kind not in HUMAN_BOUNDARY_KINDS:
        raise HarnessError(f"INVALID_HUMAN_BOUNDARY_KIND:{boundary_kind}")
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    if worktree and worktree.is_dir():
        _refresh_changes(task_id)

    def mutate(state: dict[str, Any]) -> None:
        _append_active_blocker(state, code, detail, boundary_kind)
        _close_active_plan(state, "PENDING")
        state["WAITING_STARTED_AT"] = utc_now()

    update_task(task_id, {
        "CURRENT_PHASE": "WAITING_HUMAN",
        "CURRENT_ACTION": "Waiting for human decision",
        "WHY_CURRENT_ACTION": detail[:MAX_TEXT],
        "NEXT_ACTION": "Human steers, reviews, resumes, or stops",
        "WHY_NEXT_ACTION": "The bounded autonomous loop cannot safely choose beyond this point.",
        "HUMAN_ATTENTION_REQUIRED": True,
        "WORKER_STATUS": "WAITING_HUMAN",
    }, new_state="WAITING_HUMAN", event="WAITING_HUMAN", detail=f"{code}:{detail}", mutate=mutate)


def _request_correction(task_id: str, source: str, detail: str) -> None:
    state = load_state(task_id)
    attempt = state["CORRECTION_ATTEMPTS"] + 1
    update_task(task_id, {
        "CURRENT_PHASE": "CORRECTION_REQUESTED",
        "CURRENT_ACTION": "A bounded correction is requested; worker redispatch is pending",
        "WHY_CURRENT_ACTION": f"{source} found a software defect within the authorized task.",
        "LAST_COMPLETED": f"{source}_CORRECTION_REQUESTED",
        "NEXT_ACTION": "Dispatch the bounded correction worker",
        "WHY_NEXT_ACTION": "The preserved worktree must be corrected before validation and review can pass.",
        "NEXT_ACTION_CODE": "WORKER",
        "CORRECTION_ATTEMPTS": attempt,
        "WORKER_STATUS": "CORRECTION_PENDING",
    }, new_state="RUNNING", event=f"{source}_CORRECTION_REQUESTED", detail=(
        f"attempt={attempt};{detail[:1_000]}"
    ), mutate=_reset_correction_plan)


def _review_classification(message: str, exit_code: int) -> str:
    value = _parse_marker(message, "REVIEW_STATUS").upper()
    allowed = {"PASS", "PASS_WITH_WARNINGS", "FIX_REQUIRED", "HUMAN_DECISION_REQUIRED"}
    if exit_code != 0:
        return "HUMAN_DECISION_REQUIRED"
    return value if value in allowed else "HUMAN_DECISION_REQUIRED"


def _perform_review(task_id: str) -> str:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    _refresh_changes(task_id)
    before = _repo_status_fingerprint(worktree)
    def mark_review_active(value: dict[str, Any]) -> None:
        _plan_update(value, "FINAL_INDEPENDENT_REVIEW", "IN_PROGRESS")

    update_task(task_id, {
        "WORKER_STATUS": "REVIEW_STARTING",
        "CURRENT_PHASE": "FINAL_INDEPENDENT_REVIEW",
        "CURRENT_ACTION": "Launching the final separate read-only Codex review",
        "WHY_CURRENT_ACTION": "The reviewer must assess correctness and all three R1 pillars without modifying code.",
        "NEXT_ACTION": "Complete and classify the independent review",
        "WHY_NEXT_ACTION": "Only a completed read-only review can authorize finalization or a bounded correction.",
    }, new_state="REVIEWING", event="REVIEW_STARTED", detail="sandbox=read-only;new ephemeral context", mutate=mark_review_active)
    result = _run_codex_turn(task_id, _review_prompt(load_state(task_id)), review=True)
    after = _repo_status_fingerprint(worktree)
    _refresh_changes(task_id)
    if before != after:
        _block(task_id, "READ_ONLY_REVIEW_MUTATED_WORKTREE", f"before={before};after={after}")
        return "HUMAN_DECISION_REQUIRED"
    classification = _review_classification(result["message"], result["exit_code"])
    if classification in {"PASS", "PASS_WITH_WARNINGS"}:
        next_action = "Finalize and preserve the reviewed worktree"
        why_next = "The independent review accepted the bounded change."
        next_code = "FINALIZE"
    elif classification == "FIX_REQUIRED":
        next_action = "Request a bounded correction worker"
        why_next = "The independent review found a correctable defect within scope."
        next_code = "SELECT_WORK"
    else:
        next_action = "Wait for a human decision on the review findings"
        why_next = "The review could not safely authorize correction or completion autonomously."
        next_code = "FINAL_REVIEW"

    def mark_review_completed(value: dict[str, Any]) -> None:
        _plan_update(value, "FINAL_INDEPENDENT_REVIEW", "COMPLETED")

    update_task(task_id, {
        "WORKER_STATUS": f"REVIEW_EXITED_{result['exit_code']}",
        "CURRENT_PHASE": "FINAL_INDEPENDENT_REVIEW",
        "CURRENT_ACTION": f"Independent review completed with {classification}",
        "WHY_CURRENT_ACTION": "The read-only review turn ended and its explicit classification was recorded.",
        "LAST_REVIEW_STATUS": classification,
        "REVIEW_REQUESTED": False,
        "LAST_COMPLETED": "INDEPENDENT_REVIEW_COMPLETED",
        "NEXT_ACTION": next_action,
        "WHY_NEXT_ACTION": why_next,
        "NEXT_ACTION_CODE": next_code,
    }, event="REVIEW_CLASSIFIED", detail=classification, mutate=mark_review_completed)
    return classification


def _worker_result(state: dict[str, Any], exit_code: int) -> str:
    if exit_code != 0:
        return "SOFTWARE_FAILURE"
    value = _parse_marker(state.get("WORKER_FINDINGS", ""), "TASK_RESULT").upper()
    allowed = {"COMPLETED", "SOFTWARE_FAILURE", "RESEARCH_FAILURE", "WAITING_HUMAN", "BLOCKED"}
    return value if value in allowed else "COMPLETED"


def _worker_test_environment_delegation_allowed(
    state: dict[str, Any], worker_exit_code: int,
) -> tuple[bool, str]:
    if state.get("WORKER_TEST_STATUS") != "ENVIRONMENT_LIMITED":
        return False, "WORKER_TEST_STATUS_NOT_ENVIRONMENT_LIMITED"
    if state.get("WORKER_TEST_LIMITATION") != WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION:
        return False, "WORKER_TEST_LIMITATION_NOT_RECOGNIZED"
    if worker_exit_code != 0 or state.get("WORKER_STATUS") != "EXITED_0":
        return False, "WORKER_DID_NOT_EXIT_NORMALLY"
    worker_pid = state.get("WORKER_PID")
    if worker_pid or state.get("ACTIVE_THREAD_ID") or state.get("ACTIVE_PROCESS_KIND"):
        liveness = _pid_alive(worker_pid) if worker_pid else None
        return False, f"ACTIVE_OR_ORPHAN_WORKER_IDENTITY_PRESENT:liveness={liveness}"
    worktree = Path(state.get("WORKTREE", ""))
    if state.get("WORKTREE_INVENTORY_STATUS") != "KNOWN" or not worktree.is_dir():
        return False, "WORKTREE_INVENTORY_NOT_KNOWN"
    for field in ("OVERFIT_GUARD", "ANTI_BLOAT", "REUSE_GUARD"):
        if not str(state.get(field, "")).startswith("PASS"):
            return False, f"SAFETY_GUARD_NOT_PASS:{field}={state.get(field)}"
    return True, "CONTROLLER_AUTHORITATIVE_VALIDATION_REQUIRED"


def _component_name_key(path: str) -> str:
    stem = Path(path).stem.casefold()
    stem = re.sub(r"(?:[_-](?:r|v)\d+(?:[_-]\d+)*|[_-]final\d*|[_-]patched\d*)+$", "", stem)
    stem = re.sub(r"^test[_-]", "", stem)
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")


def _parallel_component_conflicts(state: dict[str, Any], changes: dict[str, Any]) -> list[str]:
    cache = state.get("REUSE_DISCOVERY_CACHE", {})
    evidence_rows: list[str] = []
    initial = cache.get("initial", {}) if isinstance(cache, dict) else {}
    evidence_rows.extend(initial.get("filename_matches", []))
    for refresh in cache.get("incremental", []) if isinstance(cache, dict) else []:
        evidence_rows.extend(refresh.get("evidence", {}).get("filename_matches", []))
    existing = {
        _component_name_key(str(path)): str(path)
        for path in evidence_rows
        if _component_name_key(str(path))
    }
    conflicts: list[str] = []
    for created in changes.get("created", []):
        if Path(created).name.startswith("test_"):
            continue
        key = _component_name_key(str(created))
        match = existing.get(key)
        if match and Path(match).as_posix().casefold() != Path(created).as_posix().casefold():
            conflicts.append(f"{created} duplicates identity of existing {match}")
    return sorted(set(conflicts))[:20]


def _record_global_retry(
    state: dict[str, Any], kind: str, detail: str, progress_hash: str,
    *, retry_limit: int = DEFAULT_FAILURE_RETRY_LIMIT,
) -> bool:
    signature = _failure_signature(kind, detail)
    key = f"GLOBAL:{signature}"
    prior = state.setdefault("RETRY_LEDGER", {}).get(key, {})
    count = int(prior.get("count", 0)) + 1 if prior.get("progress_hash") == progress_hash else 1
    state["RETRY_LEDGER"][key] = {
        "count": count, "progress_hash": progress_hash,
        "last_attempted_remedy": kind[:200], "last_detail": detail[:1_000],
        "updated_at": utc_now(),
    }
    state["CURRENT_RETRY_SIGNATURE"] = signature
    state["CURRENT_RETRY_COUNT"] = count
    return count <= retry_limit


def _run_unit_validation(task_id: str) -> tuple[bool, str]:
    started = time.monotonic()
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    changes = _refresh_changes(task_id)
    _refresh_reuse_discovery_for_changes(task_id, changes, state.get("ACTIVE_WORK_UNIT_IDS", []))
    state = load_state(task_id)
    reported_paths = _parse_json_marker(state.get("WORKER_FINDINGS", ""), "CHANGED_PATHS_JSON", [])
    if not isinstance(reported_paths, list):
        reported_paths = []
    targeted_paths = list(dict.fromkeys([
        *(str(path) for path in reported_paths),
        *(
            str(path)
            for unit_id in state.get("ACTIVE_WORK_UNIT_IDS", [])
            if (unit := _unit_by_id(state, unit_id))
            for path in unit.get("relevant_paths", [])
        ),
        *changes.get("created", []),
    ])) or changes["changed"]
    problems: list[str] = []
    if state.get("UNJUSTIFIED_CREATED_PATHS"):
        problems.append(
            "NEW_COMPONENT_JUSTIFICATION_REQUIRED:" + ",".join(state["UNJUSTIFIED_CREATED_PATHS"])
        )
    duplicate_conflicts = _parallel_component_conflicts(state, changes)
    if duplicate_conflicts:
        problems.append("DUPLICATE_COMPONENT_IDENTITY:" + " | ".join(duplicate_conflicts))
    diff_check = _git(["diff", "--check"], worktree, 60)
    if diff_check.returncode:
        problems.append("GIT_DIFF_CHECK_FAILED:" + (diff_check.stdout + diff_check.stderr)[-2_000:])
    passed, validation = _validate_targeted(task_id, targeted_paths)
    if not passed:
        problems.append("TARGETED_VALIDATION_FAILED:" + validation)
    elapsed = max(0.0, time.monotonic() - started)

    def record(value: dict[str, Any]) -> None:
        value["PENDING_UNIT_RESULTS"] = _pending_unit_results(value)
        value["CONTROLLER_VALIDATION_STATUS"] = "FAIL" if problems else "PASS"
        value["VALIDATION_RESULTS"] = [
            *value.get("VALIDATION_RESULTS", []),
            (";".join(problems) if problems else validation)[:4_000],
        ][-MAX_LIST_ITEMS:]
        _telemetry_add(value, machine_validation_wall_seconds=elapsed)

    update_task(
        task_id, event="WORK_UNIT_VALIDATION_COMPLETED",
        detail=("FAIL:" + ";".join(problems))[:1_000] if problems else "PASS",
        mutate=record,
    )
    return not problems, ";".join(problems) if problems else validation


def _run_final_validation(task_id: str) -> tuple[bool, str]:
    started = time.monotonic()
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    changes = _refresh_changes(task_id)
    problems: list[str] = []
    if load_state(task_id).get("UNJUSTIFIED_CREATED_PATHS"):
        problems.append(
            "NEW_COMPONENT_JUSTIFICATION_REQUIRED:"
            + ",".join(load_state(task_id)["UNJUSTIFIED_CREATED_PATHS"])
        )
    duplicate_conflicts = _parallel_component_conflicts(load_state(task_id), changes)
    if duplicate_conflicts:
        problems.append("DUPLICATE_COMPONENT_IDENTITY:" + " | ".join(duplicate_conflicts))
    passed, validation = _validate_targeted(task_id, changes["changed"])
    if not passed:
        problems.append("FINAL_TARGETED_VALIDATION_FAILED:" + validation)
    diff_check = _git(["diff", "--check"], worktree, 60)
    if diff_check.returncode:
        problems.append("GIT_DIFF_CHECK_FAILED:" + (diff_check.stdout + diff_check.stderr)[-2_000:])
    post = _run_preflight_for(task_id, worktree)
    if post["task_blocker_count"]:
        problems.append("POST_CHANGE_R1_HARD_BLOCKER:" + post["result"]["preflight_status"])
    elapsed = max(0.0, time.monotonic() - started)
    final_passed = not problems

    def record(value: dict[str, Any]) -> None:
        value.update({
            "OVERFIT_GUARD": post["overfit"],
            "ANTI_BLOAT": post["anti"],
            "ANTI_BLOAT_TASK_DELTA": post["anti_delta"],
            "CONTROLLER_VALIDATION_STATUS": "PASS" if final_passed else "FAIL",
            "REPO_BYTES_AFTER": post["bytes"],
            "REPO_SIZE_DELTA_BYTES": (
                post["bytes"] - value.get("REPO_BYTES_BEFORE")
                if post["bytes"] is not None and value.get("REPO_BYTES_BEFORE") is not None
                else None
            ),
            "VALIDATION_RESULTS": [
                *value.get("VALIDATION_RESULTS", []),
                (";".join(problems) if problems else validation)[:4_000],
                post["result"]["preflight_status"],
            ][-MAX_LIST_ITEMS:],
        })
        _telemetry_add(value, machine_validation_wall_seconds=elapsed)
        if final_passed:
            _plan_update(value, "FINAL_VALIDATION", "COMPLETED")
            _meaningful_progress(value, "FINAL_VALIDATION_PASS")
        else:
            _plan_update(value, "FINAL_VALIDATION", "PENDING")

    update_task(
        task_id, event="FINAL_VALIDATION_COMPLETED",
        detail=("PASS" if final_passed else "FAIL:" + ";".join(problems))[:1_000],
        mutate=record,
    )
    return final_passed, ";".join(problems) if problems else validation


def _defer_for_expired_budget(state: dict[str, Any]) -> int:
    deferred = 0
    for unit in state.get("WORK_UNITS", []):
        if unit.get("status") in {"READY", "RETRY"}:
            unit["status"] = "DEFERRED"
            unit["blocker"] = {"code": "TIME_BUDGET_EXPIRED", "detail": "Task converged at its wall-clock boundary"}
            unit["last_checkpoint"] = "TIME_BUDGET_EXPIRED"
            unit["next_action"] = "Continuation plan preserved for a future authorized task"
            deferred += 1
    return deferred


def _dispatch_r2_compat(task_id: str) -> None:
    while True:
        if _control_checkpoint(task_id):
            return
        state = load_state(task_id)
        action = state["NEXT_ACTION_CODE"]
        if action == "R1_PREFLIGHT":
            update_task(task_id, {
                "CURRENT_PHASE": "R1_PREFLIGHT", "CURRENT_ACTION": "Running R1 task-scoped preflight",
                "WHY_CURRENT_ACTION": "Autonomy is subordinate to leakage, frozen-asset, and Anti-Bloat gates.",
            }, event="R1_PREFLIGHT_STARTED", detail=f"scope={state['TASK_SCOPE']}")
            result = _run_preflight_for(task_id, REPO, baseline_checkpoint=True)
            def complete_preflight(value: dict[str, Any]) -> None:
                _plan_update(value, "R1_PREFLIGHT", "COMPLETED")
            update_task(task_id, {
                "OVERFIT_GUARD": result["overfit"], "ANTI_BLOAT": result["anti"],
                "ANTI_BLOAT_BASELINE_RESIDUE": result["accounting_residue"],
                "ANTI_BLOAT_TASK_DELTA": result["anti_delta"],
                "PRIMARY_REPO_BYTES_AT_START": result["bytes"], "LAST_COMPLETED": "R1_PREFLIGHT",
                "NEXT_ACTION": "Search existing implementations", "WHY_NEXT_ACTION": "Reuse evidence is mandatory before material implementation.",
                "NEXT_ACTION_CODE": "DISCOVER_EXISTING",
            }, event="R1_PREFLIGHT_COMPLETED", detail=result["result"]["preflight_status"], mutate=complete_preflight)
            if result["task_blocker_count"]:
                _block(task_id, "R1_PREFLIGHT_APPLICABLE_HARD_BLOCKER", result["result"]["preflight_status"])
                return
        elif action == "DISCOVER_EXISTING":
            update_task(task_id, {
                "CURRENT_PHASE": "DISCOVER_EXISTING", "CURRENT_ACTION": "Searching mapped repository surfaces for reusable work",
                "WHY_CURRENT_ACTION": "A targeted filename and semantic search prevents duplicate implementations.",
            }, event="DISCOVERY_STARTED", detail="scripts/fast3/tests/config/docs")
            evidence = _discover_existing(state["GOAL"])
            def complete_discovery(value: dict[str, Any]) -> None:
                _plan_update(value, "DISCOVER_EXISTING", "COMPLETED")
            update_task(task_id, {
                "REUSE_EVIDENCE": evidence, "REUSE_GUARD": "PASS_SEARCH_RECORDED",
                "LAST_COMPLETED": "DISCOVER_EXISTING", "NEXT_ACTION": "Create isolated external worktree",
                "WHY_NEXT_ACTION": "The primary worktree is dirty and concurrent activity is present.",
                "NEXT_ACTION_CODE": "CREATE_WORKTREE",
            }, event="DISCOVERY_COMPLETED", detail=f"matches_capped={evidence['match_count_capped']}", mutate=complete_discovery)
        elif action == "CREATE_WORKTREE":
            update_task(task_id, {
                "CURRENT_PHASE": "CREATE_ISOLATED_WORKTREE", "CURRENT_ACTION": "Creating task branch and external Git worktree",
                "WHY_CURRENT_ACTION": "Autonomous mutations must not enter the dirty primary working tree.",
            }, event="WORKTREE_CREATE_STARTED", detail=str(worktree_root()))
            try:
                path, branch, head = _create_worktree(task_id)
            except HarnessError as exc:
                _block(task_id, "AUTONOMOUS_MUTATION_WORKTREE_UNAVAILABLE", str(exc))
                return
            isolated_preflight = _run_preflight_for(task_id, path, baseline_checkpoint=True)
            if isolated_preflight["task_blocker_count"]:
                update_task(task_id, {
                    "WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head,
                    "OVERFIT_GUARD": isolated_preflight["overfit"], "ANTI_BLOAT": isolated_preflight["anti"],
                    "ANTI_BLOAT_BASELINE_RESIDUE": isolated_preflight["accounting_residue"],
                    "ANTI_BLOAT_TASK_DELTA": isolated_preflight["anti_delta"],
                })
                _block(task_id, "ISOLATED_WORKTREE_R1_HARD_BLOCKER", isolated_preflight["result"]["preflight_status"])
                return
            def complete_worktree(value: dict[str, Any]) -> None:
                _plan_update(value, "CREATE_ISOLATED_WORKTREE", "COMPLETED")
            update_task(task_id, {
                "WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head,
                "OVERFIT_GUARD": isolated_preflight["overfit"], "ANTI_BLOAT": isolated_preflight["anti"],
                "ANTI_BLOAT_BASELINE_RESIDUE": isolated_preflight["accounting_residue"],
                "ANTI_BLOAT_TASK_DELTA": isolated_preflight["anti_delta"],
                "REPO_BYTES_BEFORE": isolated_preflight["bytes"],
                "LAST_COMPLETED": "CREATE_ISOLATED_WORKTREE", "NEXT_ACTION": "Launch bounded Codex worker",
                "WHY_NEXT_ACTION": "Preflight, reuse search, and isolation gates have passed.",
                "NEXT_ACTION_CODE": "WORKER",
            }, new_state="RUNNING", event="WORKTREE_CREATED", detail=f"{path};branch={branch};head={head}", mutate=complete_worktree)
        elif action == "WORKER":
            state = load_state(task_id)
            correction = ""
            if state["CORRECTION_ATTEMPTS"]:
                correction = f"Prior validation/review: {state.get('VALIDATION_RESULTS', [])[-2:]}\n{state.get('REVIEW_FINDINGS', '')[-2500:]}"
            update_task(task_id, {
                "CURRENT_PHASE": "IMPLEMENT", "CURRENT_ACTION": "Dispatching the bounded implementation worker",
                "WHY_CURRENT_ACTION": "Only the authorized task may be changed in the isolated worktree.",
            }, new_state="RUNNING")
            try:
                result = _run_codex_turn(task_id, _worker_prompt(load_state(task_id), correction))
            except HarnessError as exc:
                code = "WORKER_TEMP_RUNTIME_UNAVAILABLE" if str(exc).startswith("WORKER_TEMP_RUNTIME_UNAVAILABLE:") else "CODEX_WORKER_INTERFACE_FAILURE"
                _wait_human(task_id, code, str(exc))
                return
            if _control_checkpoint(task_id):
                return
            state = load_state(task_id)
            outcome = _worker_result(state, result["exit_code"])
            contamination = _parse_marker(state.get("WORKER_FINDINGS", ""), "HOLDOUT_CONTAMINATION_RISK")
            if contamination and contamination.upper() != "NONE":
                _wait_human(task_id, "HOLDOUT_CONTAMINATION_RISK", contamination)
                return
            if state.get("WORKER_TEST_STATUS") == "REAL_TEST_FAILURE":
                outcome = "SOFTWARE_FAILURE"
            environment_delegated = False
            if state.get("WORKER_TEST_STATUS") == "ENVIRONMENT_LIMITED" and outcome in {"COMPLETED", "SOFTWARE_FAILURE"}:
                allowed, reason = _worker_test_environment_delegation_allowed(state, result["exit_code"])
                if not allowed:
                    _wait_human(task_id, "WORKER_TEST_ENVIRONMENT_DELEGATION_UNSAFE", reason)
                    return
                environment_delegated = True
                outcome = "COMPLETED"
                update_task(task_id, {
                    "CURRENT_ACTION": "Worker pytest was environment-limited; Controller validation is required",
                    "WHY_CURRENT_ACTION": WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
                    "NEXT_ACTION": "Run Controller-owned authoritative focused validation",
                    "WHY_NEXT_ACTION": "The worker exited normally and the narrow nested pytest temp limitation is not implementation evidence.",
                }, event="WORKER_TEST_ENVIRONMENT_LIMITATION_DELEGATED", detail=reason)
            elif state.get("WORKER_TEST_STATUS") == "ENVIRONMENT_LIMITED" and outcome == "RESEARCH_FAILURE":
                _wait_human(
                    task_id,
                    "WORKER_TEST_ENVIRONMENT_NOT_SOLE_LIMITATION",
                    "Worker reported a research failure in addition to the pytest environment limitation.",
                )
                return
            if outcome in {"WAITING_HUMAN", "BLOCKED"}:
                _wait_human(task_id, f"WORKER_{outcome}", load_state(task_id).get("WORKER_FINDINGS", ""))
                return
            if outcome == "SOFTWARE_FAILURE":
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", f"attempts={state['CORRECTION_ATTEMPTS']}")
                    return
                _request_correction(task_id, "SOFTWARE", "Worker reported software failure")
            else:
                update_task(task_id, {
                    "CURRENT_PHASE": "IMPLEMENT",
                    "CURRENT_ACTION": f"Worker turn completed and {outcome.lower().replace('_', ' ')} was accepted",
                    "WHY_CURRENT_ACTION": "The worker process exited and its explicit safety/result markers were classified.",
                    "LAST_COMPLETED": "WORKER_TURN_COMPLETED",
                    "NEXT_ACTION": "Run targeted validation and post-change guards",
                    "WHY_NEXT_ACTION": "Worker output is not accepted without mechanical validation.",
                    "NEXT_ACTION_CODE": "VALIDATE",
                }, event="WORKER_RESULT_ACCEPTED", detail=(
                    "ENVIRONMENT_LIMITED_TO_CONTROLLER_VALIDATION" if environment_delegated else outcome
                ))
        elif action == "VALIDATE":
            def mark_validation_active(value: dict[str, Any]) -> None:
                _plan_update(value, "TARGETED_TEST", "IN_PROGRESS")

            update_task(task_id, {
                "CURRENT_PHASE": "TARGETED_TEST", "CURRENT_ACTION": "Inventorying diff and running targeted validation",
                "WHY_CURRENT_ACTION": "Changed code, R1 guards, dependencies, and creation justification must be checked before review.",
                "NEXT_ACTION": "Complete targeted tests and post-change guards",
                "WHY_NEXT_ACTION": "Both mechanical tests and applicable R1 guards must complete before review.",
                "CONTROLLER_VALIDATION_STATUS": "RUNNING",
            }, event="TARGETED_VALIDATION_STARTED", detail="No data fetch or retraining is launched by the controller", mutate=mark_validation_active)
            changes = _refresh_changes(task_id)
            inventory_state = load_state(task_id)
            if inventory_state["REUSE_GUARD"].startswith("HARD_BLOCKER"):
                update_task(task_id, {"CONTROLLER_VALIDATION_STATUS": "FAIL"})
                missing = inventory_state.get("UNJUSTIFIED_CREATED_PATHS", changes["created"])
                _wait_human(task_id, "NEW_COMPONENT_JUSTIFICATION_REQUIRED", ",".join(missing))
                return
            passed, validation = _validate_targeted(task_id)
            post = _run_preflight_for(task_id, Path(load_state(task_id)["WORKTREE"]))
            _refresh_changes(task_id)
            validation_passed = passed and not post["task_blocker_count"]
            def complete_validation(value: dict[str, Any]) -> None:
                _plan_update(value, "TARGETED_TEST", "COMPLETED" if validation_passed else "FAILED")
            update_task(task_id, {
                "CURRENT_PHASE": "TARGETED_TEST",
                "CURRENT_ACTION": f"Targeted validation completed with {'PASS' if validation_passed else 'FAIL'}",
                "WHY_CURRENT_ACTION": "The controller recorded focused tests and the post-change R1 guard result.",
                "OVERFIT_GUARD": post["overfit"], "ANTI_BLOAT": post["anti"],
                "ANTI_BLOAT_TASK_DELTA": post["anti_delta"],
                "CONTROLLER_VALIDATION_STATUS": "PASS" if validation_passed else "FAIL",
                "REPO_BYTES_AFTER": post["bytes"],
                "REPO_SIZE_DELTA_BYTES": (post["bytes"] - state.get("REPO_BYTES_BEFORE")) if post["bytes"] is not None and state.get("REPO_BYTES_BEFORE") is not None else None,
                "VALIDATION_RESULTS": (load_state(task_id).get("VALIDATION_RESULTS", []) + [validation[:4_000], post["result"]["preflight_status"]])[-MAX_LIST_ITEMS:],
                "LAST_COMPLETED": "TARGETED_VALIDATION_COMPLETED",
                "NEXT_ACTION": "Run independent read-only review" if validation_passed else "Request a bounded correction or report the hard blocker",
                "WHY_NEXT_ACTION": "Material changes require correctness, leakage, reuse, and bloat assessment." if validation_passed else "Failed validation cannot advance to acceptance.",
                "NEXT_ACTION_CODE": "REVIEW" if validation_passed else "WORKER",
            }, event="TARGETED_VALIDATION_COMPLETED", detail=f"tests={'PASS' if passed else 'FAIL'};preflight={post['result']['preflight_status']}", mutate=complete_validation)
            if post["task_blocker_count"]:
                _block(task_id, "POST_CHANGE_R1_HARD_BLOCKER", post["result"]["preflight_status"])
                return
            if not passed:
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", validation)
                    return
                _request_correction(task_id, "TARGETED_VALIDATION", validation)
        elif action == "REVIEW":
            changes = _refresh_changes(task_id)
            if not changes["changed"] and state["TASK_SCOPE"] == "independent-code" and not state["REVIEW_REQUESTED"]:
                def skip_review(value: dict[str, Any]) -> None:
                    _plan_update(value, "INDEPENDENT_REVIEW", "COMPLETED")
                update_task(task_id, {
                    "CURRENT_PHASE": "INDEPENDENT_REVIEW",
                    "CURRENT_ACTION": "Independent review was not warranted because the worktree has no changes",
                    "WHY_CURRENT_ACTION": "A no-change independent-code task has no material diff to review.",
                    "LAST_REVIEW_STATUS": "NOT_WARRANTED_NO_CHANGES", "LAST_COMPLETED": "REVIEW_SKIPPED_NO_CHANGES",
                    "NEXT_ACTION": "Finalize and preserve the no-change worktree",
                    "WHY_NEXT_ACTION": "All applicable lifecycle checks are complete.",
                    "NEXT_ACTION_CODE": "FINALIZE",
                }, event="REVIEW_NOT_WARRANTED", detail="No worktree changes", mutate=skip_review)
                continue
            try:
                classification = _perform_review(task_id)
            except HarnessError as exc:
                code = "WORKER_TEMP_RUNTIME_UNAVAILABLE" if str(exc).startswith("WORKER_TEMP_RUNTIME_UNAVAILABLE:") else "INDEPENDENT_REVIEW_INTERFACE_FAILURE"
                _wait_human(task_id, code, str(exc))
                return
            if _control_checkpoint(task_id):
                return
            if classification == "FIX_REQUIRED":
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", state.get("REVIEW_FINDINGS", ""))
                    return
                _request_correction(task_id, "REVIEW", state.get("REVIEW_FINDINGS", ""))
            elif classification == "HUMAN_DECISION_REQUIRED":
                _wait_human(task_id, "REVIEW_HUMAN_DECISION_REQUIRED", load_state(task_id).get("REVIEW_FINDINGS", ""))
                return
        elif action == "FINALIZE":
            changes = _refresh_changes(task_id)
            try:
                _cleanup_task_temp_runtime(task_id)
            except HarnessError as exc:
                _wait_human(task_id, "WORKER_TEMP_RUNTIME_CLEANUP_FAILED", str(exc))
                return
            def complete_all(value: dict[str, Any]) -> None:
                _plan_update(value, "FINALIZE", "COMPLETED")
            update_task(task_id, {
                "CURRENT_PHASE": "COMPLETED", "CURRENT_ACTION": "Task complete; isolated worktree preserved for human integration",
                "WHY_CURRENT_ACTION": "R2 stops after one goal and never auto-merges or deletes useful changes.",
                "LAST_COMPLETED": "AUTHORIZED_TASK_COMPLETED", "NEXT_ACTION": "Human reviews the diff and chooses whether to integrate",
                "WHY_NEXT_ACTION": "Integration into the primary tree requires explicit human action.",
                "NEXT_ACTION_CODE": "DONE", "HUMAN_ATTENTION_REQUIRED": False,
                "WORKER_STATUS": "COMPLETED", "WORKER_PID": None,
                "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
                "FILES_CHANGED": changes["changed"], "FILES_CREATED": changes["created"], "DEPENDENCIES_ADDED": changes["dependencies"],
            }, new_state="COMPLETED", event="TASK_COMPLETED", detail=f"worktree_preserved={state['WORKTREE']}", mutate=complete_all)
            return
        elif action == "DONE":
            return
        else:
            _block(task_id, "UNKNOWN_NEXT_ACTION", str(action))
            return


def _dispatch_r3(task_id: str) -> None:
    while True:
        if _control_checkpoint(task_id):
            return
        update_task(task_id, {"CONTROLLER_HEARTBEAT_AT": utc_now()})
        state = load_state(task_id)
        action = str(state.get("NEXT_ACTION_CODE", "HARD_PREFLIGHT"))
        if action in {"R1_PREFLIGHT", "HARD_PREFLIGHT"}:
            update_task(task_id, {
                "CURRENT_PHASE": "HARD_PREFLIGHT",
                "CURRENT_ACTION": "Running task-scoped hard preflight",
                "WHY_CURRENT_ACTION": "PIT, holdout, frozen-asset, worktree, and Anti-Bloat boundaries gate mutation.",
            }, event="HARD_PREFLIGHT_STARTED", detail=f"scope={state['TASK_SCOPE']}")
            result = _run_preflight_for(task_id, REPO, baseline_checkpoint=True)

            def complete_preflight(value: dict[str, Any]) -> None:
                _plan_update(value, "HARD_PREFLIGHT", "COMPLETED")
                _meaningful_progress(value, "HARD_PREFLIGHT_COMPLETED")

            update_task(task_id, {
                "OVERFIT_GUARD": result["overfit"],
                "ANTI_BLOAT": result["anti"],
                "ANTI_BLOAT_BASELINE_RESIDUE": result["accounting_residue"],
                "ANTI_BLOAT_TASK_DELTA": result["anti_delta"],
                "PRIMARY_REPO_BYTES_AT_START": result["bytes"],
                "LAST_COMPLETED": "HARD_PREFLIGHT",
                "NEXT_ACTION": "Build the task-local reuse cache",
                "WHY_NEXT_ACTION": "One bounded initial discovery prevents repeated full scans.",
                "NEXT_ACTION_CODE": "DISCOVER_REUSE",
            }, event="HARD_PREFLIGHT_COMPLETED", detail=result["result"]["preflight_status"], mutate=complete_preflight)
            if result["task_blocker_count"]:
                _block(task_id, "R1_PREFLIGHT_APPLICABLE_HARD_BLOCKER", result["result"]["preflight_status"])
                return
        elif action in {"DISCOVER_EXISTING", "DISCOVER_REUSE"}:
            update_task(task_id, {
                "CURRENT_PHASE": "DISCOVER_REUSE",
                "CURRENT_ACTION": "Building the task-local targeted reuse cache",
                "WHY_CURRENT_ACTION": "Discovery is reused across turns and refreshed only for materially new paths.",
            }, event="DISCOVERY_STARTED", detail="initial targeted task discovery")
            evidence = _discover_existing(state["GOAL"])

            def complete_discovery(value: dict[str, Any]) -> None:
                value["REUSE_EVIDENCE"] = evidence
                value["REUSE_DISCOVERY_CACHE"] = _initial_reuse_cache(evidence)
                value["REUSE_GUARD"] = "PASS_SEARCH_RECORDED"
                _plan_update(value, "DISCOVER_REUSE", "COMPLETED")
                _telemetry_add(value, discovery_full_scans=1)
                _meaningful_progress(value, "REUSE_DISCOVERY_CACHED")

            update_task(task_id, {
                "LAST_COMPLETED": "DISCOVER_REUSE",
                "NEXT_ACTION": "Create the isolated external worktree",
                "WHY_NEXT_ACTION": "All autonomous mutations remain outside the primary tree.",
                "NEXT_ACTION_CODE": "CREATE_WORKTREE",
            }, event="DISCOVERY_COMPLETED", detail=f"matches_capped={evidence['match_count_capped']}", mutate=complete_discovery)
        elif action == "CREATE_WORKTREE":
            update_task(task_id, {
                "CURRENT_PHASE": "CREATE_ISOLATED_WORKTREE",
                "CURRENT_ACTION": "Creating task branch and external Git worktree",
                "WHY_CURRENT_ACTION": "Autonomous mutation never enters the dirty primary worktree.",
            }, event="WORKTREE_CREATE_STARTED", detail=str(worktree_root()))
            try:
                path, branch, head = _create_worktree(task_id)
            except HarnessError as exc:
                _wait_human(
                    task_id, "AUTONOMOUS_MUTATION_WORKTREE_UNAVAILABLE", str(exc),
                    boundary_kind="EXHAUSTED",
                )
                return
            isolated_preflight = _run_preflight_for(task_id, path, baseline_checkpoint=True)
            if isolated_preflight["task_blocker_count"]:
                update_task(task_id, {
                    "WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head,
                    "OVERFIT_GUARD": isolated_preflight["overfit"],
                    "ANTI_BLOAT": isolated_preflight["anti"],
                    "ANTI_BLOAT_BASELINE_RESIDUE": isolated_preflight["accounting_residue"],
                    "ANTI_BLOAT_TASK_DELTA": isolated_preflight["anti_delta"],
                })
                _block(task_id, "ISOLATED_WORKTREE_R1_HARD_BLOCKER", isolated_preflight["result"]["preflight_status"])
                return

            def complete_worktree(value: dict[str, Any]) -> None:
                _plan_update(value, "CREATE_ISOLATED_WORKTREE", "COMPLETED")
                _meaningful_progress(value, "ISOLATED_WORKTREE_CREATED")

            update_task(task_id, {
                "WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head,
                "OVERFIT_GUARD": isolated_preflight["overfit"],
                "ANTI_BLOAT": isolated_preflight["anti"],
                "ANTI_BLOAT_BASELINE_RESIDUE": isolated_preflight["accounting_residue"],
                "ANTI_BLOAT_TASK_DELTA": isolated_preflight["anti_delta"],
                "REPO_BYTES_BEFORE": isolated_preflight["bytes"],
                "LAST_COMPLETED": "CREATE_ISOLATED_WORKTREE",
                "NEXT_ACTION": "Decompose the authorized goal into persistent work units",
                "WHY_NEXT_ACTION": "A compact plan enables independent branches and local failure isolation.",
                "NEXT_ACTION_CODE": "PLAN",
            }, new_state="RUNNING", event="WORKTREE_CREATED", detail=f"{path};branch={branch};head={head}", mutate=complete_worktree)
        elif action == "PLAN":
            state = load_state(task_id)
            if state.get("WORK_UNITS"):
                update_task(task_id, {"NEXT_ACTION_CODE": "SELECT_WORK"})
                continue
            worktree = Path(state["WORKTREE"])
            before = _repo_status_fingerprint(worktree)
            result: dict[str, Any] = {"exit_code": 1, "message": "", "tests": []}
            planner_error = ""
            try:
                result = _run_codex_turn(task_id, _planner_prompt(state), role="PLANNER")
            except HarnessError as exc:
                planner_error = f"{type(exc).__name__}:{exc}"
            after = _repo_status_fingerprint(worktree)
            if before != after:
                _block(task_id, "READ_ONLY_PLANNER_MUTATED_WORKTREE", f"before={before};after={after}")
                return
            raw_units = _parse_json_marker(result.get("message", ""), "WORK_UNITS_JSON", [])
            units, rejected = _normalize_work_unit_plan(raw_units, state["GOAL"])
            fallback = result.get("exit_code") != 0 or not isinstance(raw_units, list) or not raw_units

            def complete_plan(value: dict[str, Any]) -> None:
                value["WORK_UNITS"] = units
                if fallback:
                    value["HISTORICAL_FINDINGS"] = [
                        *value.get("HISTORICAL_FINDINGS", []),
                        {
                            "code": "PLANNER_FALLBACK_USED",
                            "detail": planner_error or "Planner did not return a valid compact plan",
                            "at": utc_now(),
                        },
                    ][-MAX_LIST_ITEMS:]
                _plan_update(value, "PLAN", "COMPLETED")
                _telemetry_add(value, duplicate_planned_work_rejected=rejected)
                _meaningful_progress(value, f"WORK_PLAN_READY:{len(units)}")

            update_task(task_id, {
                "CURRENT_PHASE": "PLAN",
                "CURRENT_ACTION": f"Persistent work plan contains {len(units)} substantive units",
                "WHY_CURRENT_ACTION": "Duplicate identities were rejected and dependencies were normalized.",
                "LAST_COMPLETED": "WORK_PLAN_READY",
                "NEXT_ACTION": "Select the next runnable related work-unit batch",
                "WHY_NEXT_ACTION": "Local blockers cannot stop independent authorized work.",
                "NEXT_ACTION_CODE": "SELECT_WORK",
            }, event="WORK_PLAN_READY", detail=f"units={len(units)};fallback={fallback};duplicates_rejected={rejected}", mutate=complete_plan)
        elif action == "SELECT_WORK":
            def select(value: dict[str, Any]) -> None:
                if _remaining_budget_seconds(value) == 0:
                    deferred = _defer_for_expired_budget(value)
                    if deferred:
                        value["HISTORICAL_FINDINGS"] = [
                            *value.get("HISTORICAL_FINDINGS", []),
                            {"code": "TIME_BUDGET_EXPIRED", "detail": f"deferred={deferred}", "at": utc_now()},
                        ][-MAX_LIST_ITEMS:]
                ids = _select_work_unit_batch(value)
                if ids:
                    value["NEXT_ACTION_CODE"] = "WORKER"
                    value["CURRENT_PHASE"] = "AUTONOMOUS_EXECUTION_LOOP"
                    value["CURRENT_ACTION"] = f"Selected work-unit batch: {','.join(ids)}"
                    value["NEXT_ACTION"] = "Run a substantive batched worker turn"
                    _plan_update(value, "AUTONOMOUS_EXECUTION_LOOP", "IN_PROGRESS")
                else:
                    value["NEXT_ACTION_CODE"] = "FINAL_VALIDATION"
                    value["CURRENT_PHASE"] = "AUTONOMOUS_EXECUTION_LOOP"
                    value["CURRENT_ACTION"] = "No runnable authorized work units remain"
                    value["NEXT_ACTION"] = "Run final authoritative machine validation"

            selected = update_task(task_id, event="WORK_UNIT_SELECTION", detail="scheduler checkpoint", mutate=select)
            if selected.get("ACTIVE_WORK_UNIT_IDS"):
                continue
            if selected.get("ACTIVE_BLOCKERS"):
                blocker = selected["ACTIVE_BLOCKERS"][0]
                _wait_human(
                    task_id, str(blocker["code"]), str(blocker["detail"]),
                    boundary_kind=str(blocker.get("boundary_kind", "EXHAUSTED")),
                )
                return
        elif action == "WORKER":
            state = load_state(task_id)
            unit_ids = list(state.get("ACTIVE_WORK_UNIT_IDS", []))
            if not unit_ids:
                update_task(task_id, {"NEXT_ACTION_CODE": "SELECT_WORK"})
                continue
            steering = _consume_pending_steer(task_id)
            worktree = Path(state["WORKTREE"])
            before_hash = _worktree_progress_hash(worktree)
            correction = "\n".join(
                f"{unit_id}: {(_unit_by_id(state, unit_id) or {}).get('next_action', '')}"
                for unit_id in unit_ids
                if (_unit_by_id(state, unit_id) or {}).get("status") == "RETRY"
            )
            update_task(task_id, {
                "WORKER_BATCH_BASE_PATHS": state.get("FILES_CHANGED", []),
                "CURRENT_PHASE": "AUTONOMOUS_EXECUTION_LOOP",
                "CURRENT_ACTION": f"Dispatching substantive worker batch {','.join(unit_ids)}",
                "WHY_CURRENT_ACTION": "Related runnable units share one useful Codex context.",
            }, new_state="RUNNING", event="WORKER_BATCH_DISPATCHED", detail=",".join(unit_ids))
            try:
                result = _run_codex_turn(
                    task_id, _worker_prompt(load_state(task_id), correction, steering),
                )
            except HarnessError as exc:
                detail = f"{type(exc).__name__}:{exc}"
                progress_hash = _worktree_progress_hash(worktree)

                def failed_launch(value: dict[str, Any]) -> None:
                    _record_unit_failure(value, unit_ids, "WORKER_PROCESS_FAILURE", detail, progress_hash)
                    value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                    value["HISTORICAL_FINDINGS"] = [
                        *value.get("HISTORICAL_FINDINGS", []),
                        {"code": "WORKER_PROCESS_FAILURE", "detail": detail[:1_000], "at": utc_now()},
                    ][-MAX_LIST_ITEMS:]

                update_task(task_id, event="WORKER_PROCESS_FAILURE_RETRY", detail=detail, mutate=failed_launch)
                continue
            if _control_checkpoint(task_id):
                return
            state = load_state(task_id)
            outcome = _worker_result(state, result["exit_code"])
            contamination = _parse_marker(state.get("WORKER_FINDINGS", ""), "HOLDOUT_CONTAMINATION_RISK")
            if contamination and contamination.upper() != "NONE":
                _wait_human(task_id, "HOLDOUT_CONTAMINATION_RISK", contamination, boundary_kind="SAFETY")
                return
            worker_pid = state.get("WORKER_PID")
            worker_identity_present = bool(
                worker_pid or state.get("ACTIVE_THREAD_ID") or state.get("ACTIVE_PROCESS_KIND")
            )
            if worker_identity_present and (
                not worker_pid or _pid_alive(worker_pid) is not False
            ):
                update_task(task_id, {
                    "CURRENT_PHASE": "AUTOMATIC_RECOVERY",
                    "CURRENT_ACTION": "Worker result returned while its live identity remains preserved",
                    "WHY_CURRENT_ACTION": "A replacement worker cannot start until liveness is resolved.",
                    "NEXT_ACTION": "Supervisor waits for the recorded worker before controller recovery",
                    "WHY_NEXT_ACTION": "No duplicate mutating worker may be dispatched.",
                    "WORKER_STATUS": "ORPHANED_RUNNING",
                    "HUMAN_ATTENTION_REQUIRED": False,
                }, event="LIVE_WORKER_PREVENTED_REDISPATCH", detail=f"pid={worker_pid}")
                return
            delegated, delegation_detail = _worker_test_environment_delegation_allowed(
                state, result["exit_code"],
            )
            if delegated:
                outcome = "COMPLETED"
                update_task(task_id, {
                    "CURRENT_ACTION": "Known nested pytest temp limitation delegated to Controller validation",
                    "WHY_CURRENT_ACTION": "The worker exited normally and all delegation safety conditions passed.",
                    "NEXT_ACTION": "Run authoritative Controller-owned validation without consuming a retry",
                }, event="WORKER_TEST_ENVIRONMENT_LIMITATION_DELEGATED", detail=delegation_detail)
                state = load_state(task_id)
            progress_hash = _worktree_progress_hash(worktree)
            blocker_kind = _parse_marker(state.get("WORKER_FINDINGS", ""), "BLOCKER_KIND").upper() or "NONE"
            if state.get("WORKER_TEST_STATUS") == "REAL_TEST_FAILURE" or outcome == "SOFTWARE_FAILURE":
                if state.get("PENDING_UNIT_RESULTS"):
                    update_task(task_id, {
                        "NEXT_ACTION_CODE": "UNIT_VALIDATE",
                        "CURRENT_ACTION": "Worker failed after a structured checkpoint; partial completed work will be validated",
                        "WHY_CURRENT_ACTION": "Validated completed units must not be rerun because a later unit or process failed.",
                        "NEXT_ACTION": "Controller validates the persisted checkpoint before scheduling retries",
                    }, event="WORKER_FAILURE_CHECKPOINT_RECOVERED", detail=f"units={','.join(unit_ids)}")
                    continue
                detail = state.get("WORKER_TEST_EVIDENCE") or state.get("WORKER_FINDINGS", "") or "Worker software failure"

                def retry_worker(value: dict[str, Any]) -> None:
                    _record_unit_failure(value, unit_ids, "WORKER_SOFTWARE_FAILURE", detail, progress_hash)
                    value["NEXT_ACTION_CODE"] = "SELECT_WORK"

                update_task(task_id, event="WORK_UNIT_RETRY_SCHEDULED", detail=detail[:1_000], mutate=retry_worker)
                continue
            if outcome in {"WAITING_HUMAN", "BLOCKED"}:
                detail = state.get("WORKER_FINDINGS", "")
                if blocker_kind in HUMAN_BOUNDARY_KINDS - {"EXHAUSTED", "PAUSE"}:
                    def boundary(value: dict[str, Any]) -> None:
                        _record_unit_failure(value, unit_ids, f"{blocker_kind}_BOUNDARY", detail, progress_hash, retry_limit=0)
                        _append_active_blocker(value, f"WORKER_{blocker_kind}_BOUNDARY", detail, blocker_kind)
                        value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                    update_task(task_id, event="WORK_UNIT_HUMAN_BOUNDARY_ISOLATED", detail=detail[:1_000], mutate=boundary)
                elif state.get("PENDING_UNIT_RESULTS"):
                    update_task(task_id, {
                        "NEXT_ACTION_CODE": "UNIT_VALIDATE",
                        "CURRENT_ACTION": "Local blocker checkpoint preserved completed independent unit results",
                        "WHY_CURRENT_ACTION": "Controller validation must accept completed units without rerunning them.",
                        "NEXT_ACTION": "Validate and apply the structured per-unit checkpoint",
                    }, event="WORKER_LOCAL_BLOCKER_CHECKPOINT_RECOVERED", detail=f"units={','.join(unit_ids)}")
                else:
                    _record_local_blocker(task_id, unit_ids, "WORKER_LOCAL_BLOCKER", detail, progress_hash=progress_hash)
                    update_task(task_id, {"NEXT_ACTION_CODE": "SELECT_WORK"})
                continue
            pending = _pending_unit_results(state)
            changed_paths = _parse_json_marker(state.get("WORKER_FINDINGS", ""), "CHANGED_PATHS_JSON", [])
            update_task(task_id, {
                "PENDING_UNIT_RESULTS": pending,
                "WORKER_REPORTED_CHANGED_PATHS": changed_paths if isinstance(changed_paths, list) else [],
                "NEXT_ACTION_CODE": "UNIT_VALIDATE",
                "CURRENT_ACTION": "Worker batch checkpoint accepted; Controller validation is next",
                "NEXT_ACTION": "Run targeted machine validation for the active unit batch",
            }, event="WORKER_BATCH_CHECKPOINT_ACCEPTED", detail=f"units={','.join(unit_ids)};outcome={outcome};progress={before_hash != progress_hash}")
        elif action == "UNIT_VALIDATE":
            state = load_state(task_id)
            unit_ids = list(state.get("ACTIVE_WORK_UNIT_IDS", []))
            if not unit_ids:
                update_task(task_id, {"NEXT_ACTION_CODE": "SELECT_WORK"})
                continue
            passed, detail = _run_unit_validation(task_id)
            progress_hash = _worktree_progress_hash(Path(state["WORKTREE"]))
            if passed:
                def accept(value: dict[str, Any]) -> None:
                    _apply_validated_unit_results(value)
                    value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                    value["LAST_COMPLETED"] = "WORK_UNIT_BATCH_VALIDATED"
                update_task(task_id, event="WORK_UNIT_BATCH_ACCEPTED", detail=",".join(unit_ids), mutate=accept)
            else:
                def retry(value: dict[str, Any]) -> None:
                    _record_unit_failure(value, unit_ids, "UNIT_VALIDATION", detail, progress_hash)
                    value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                update_task(task_id, event="WORK_UNIT_VALIDATION_RETRY", detail=detail[:1_000], mutate=retry)
        elif action in {"VALIDATE", "FINAL_VALIDATION"}:
            update_task(task_id, {
                "CURRENT_PHASE": "FINAL_VALIDATION",
                "CURRENT_ACTION": "Running final Controller-owned machine validation",
                "WHY_CURRENT_ACTION": "All completed and deferred branches must reconcile with hard guards.",
            }, event="FINAL_VALIDATION_STARTED", detail="authoritative controller validation", mutate=lambda value: _plan_update(value, "FINAL_VALIDATION", "IN_PROGRESS"))
            passed, detail = _run_final_validation(task_id)
            if not passed:
                state = load_state(task_id)
                progress_hash = _worktree_progress_hash(Path(state["WORKTREE"]))
                queued = {"value": False}
                def correction(value: dict[str, Any]) -> None:
                    queued["value"] = _queue_correction_work_unit(
                        value, "FINAL_VALIDATION", detail, progress_hash,
                        value.get("FILES_CHANGED", []),
                    )
                    if queued["value"]:
                        value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                        _plan_update(value, "AUTONOMOUS_EXECUTION_LOOP", "IN_PROGRESS")
                update_task(task_id, event="FINAL_VALIDATION_CORRECTION_DECISION", detail=detail[:1_000], mutate=correction)
                if not queued["value"]:
                    _wait_human(task_id, "FINAL_VALIDATION_NO_PROGRESS", detail, boundary_kind="EXHAUSTED")
                    return
                continue
            update_task(task_id, {
                "NEXT_ACTION_CODE": "FINAL_REVIEW",
                "NEXT_ACTION": "Launch one fresh read-only final reviewer",
                "WHY_NEXT_ACTION": "Machine validation passed; independent goal/safety/reuse review remains.",
            })
        elif action in {"REVIEW", "FINAL_REVIEW"}:
            state = load_state(task_id)
            worktree = Path(state["WORKTREE"])
            progress_hash = _worktree_progress_hash(worktree)
            try:
                classification = _perform_review(task_id)
            except HarnessError as exc:
                detail = f"{type(exc).__name__}:{exc}"
                retry = {"value": False}
                def reviewer_retry(value: dict[str, Any]) -> None:
                    retry["value"] = _record_global_retry(value, "REVIEWER_PROCESS_FAILURE", detail, progress_hash)
                    value["NEXT_ACTION_CODE"] = "FINAL_REVIEW"
                    _plan_update(value, "FINAL_INDEPENDENT_REVIEW", "PENDING")
                update_task(task_id, event="FINAL_REVIEW_PROCESS_RETRY", detail=detail, mutate=reviewer_retry)
                if not retry["value"]:
                    _wait_human(task_id, "FINAL_REVIEW_INTERFACE_EXHAUSTED", detail, boundary_kind="EXHAUSTED")
                    return
                continue
            if _control_checkpoint(task_id):
                return
            if classification == "FIX_REQUIRED":
                state = load_state(task_id)
                findings = state.get("REVIEW_FINDINGS", "")
                queued = {"value": False}
                def review_correction(value: dict[str, Any]) -> None:
                    queued["value"] = _queue_correction_work_unit(
                        value, "FINAL_REVIEW", findings, progress_hash,
                        value.get("FILES_CHANGED", []),
                    )
                    if queued["value"]:
                        value["NEXT_ACTION_CODE"] = "SELECT_WORK"
                        value["HARNESS_STATE"] = transition_value(value["HARNESS_STATE"], "RUNNING")
                        _plan_update(value, "FINAL_INDEPENDENT_REVIEW", "PENDING")
                update_task(task_id, event="FINAL_REVIEW_CORRECTION_GENERATED", detail=findings[:1_000], mutate=review_correction)
                if not queued["value"]:
                    _wait_human(task_id, "FINAL_REVIEW_DEFECT_NO_PROGRESS", findings, boundary_kind="EXHAUSTED")
                    return
                continue
            if classification == "HUMAN_DECISION_REQUIRED":
                findings = load_state(task_id).get("REVIEW_FINDINGS", "")
                retry = {"value": False}
                def unclassified_retry(value: dict[str, Any]) -> None:
                    retry["value"] = _record_global_retry(value, "REVIEW_UNCLASSIFIED", findings, progress_hash, retry_limit=1)
                    value["NEXT_ACTION_CODE"] = "FINAL_REVIEW"
                    value["HARNESS_STATE"] = transition_value(value["HARNESS_STATE"], "RUNNING")
                    _plan_update(value, "FINAL_INDEPENDENT_REVIEW", "PENDING")
                update_task(task_id, event="FINAL_REVIEW_UNCLASSIFIED_RETRY", detail=findings[:1_000], mutate=unclassified_retry)
                if not retry["value"]:
                    _wait_human(task_id, "FINAL_REVIEW_HUMAN_BOUNDARY", findings, boundary_kind="EXHAUSTED")
                    return
                continue
            update_task(task_id, {
                "NEXT_ACTION_CODE": "FINALIZE",
                "NEXT_ACTION": "Finalize the validated and independently reviewed task",
                "WHY_NEXT_ACTION": "Final review accepted the preserved worktree.",
            })
        elif action == "FINALIZE":
            state = load_state(task_id)
            if state.get("ACTIVE_BLOCKERS"):
                blocker = state["ACTIVE_BLOCKERS"][0]
                _wait_human(
                    task_id, str(blocker["code"]), str(blocker["detail"]),
                    boundary_kind=str(blocker.get("boundary_kind", "EXHAUSTED")),
                )
                return
            changes = _refresh_changes(task_id)
            cleanup_warning = ""
            try:
                _cleanup_task_temp_runtime(task_id)
            except HarnessError as exc:
                cleanup_warning = str(exc)
            state = load_state(task_id)
            deferred = [
                unit for unit in state.get("WORK_UNITS", [])
                if unit.get("status") in {"BLOCKED_LOCAL", "DEFERRED"}
            ]
            terminal = "COMPLETED_WITH_DEFERRED_WORK" if deferred or cleanup_warning else "COMPLETED"

            def complete_all(value: dict[str, Any]) -> None:
                if cleanup_warning:
                    value["HISTORICAL_FINDINGS"] = [
                        *value.get("HISTORICAL_FINDINGS", []),
                        {"code": "TEMP_CLEANUP_WARNING", "detail": cleanup_warning[:1_000], "at": utc_now()},
                    ][-MAX_LIST_ITEMS:]
                _plan_update(value, "AUTONOMOUS_EXECUTION_LOOP", "COMPLETED")
                _plan_update(value, "FINALIZE", "COMPLETED")
                _telemetry_add(value, new_components_created=len(changes["created"]))
                _meaningful_progress(value, terminal)

            update_task(task_id, {
                "CURRENT_PHASE": terminal,
                "CURRENT_ACTION": "Autonomous task complete; isolated worktree preserved",
                "WHY_CURRENT_ACTION": "Final machine validation and independent review passed; unresolved local work is explicitly deferred.",
                "LAST_COMPLETED": terminal,
                "NEXT_ACTION": "Human may inspect and optionally integrate the preserved worktree",
                "WHY_NEXT_ACTION": "Harness never auto-merges or deletes useful work.",
                "NEXT_ACTION_CODE": "DONE",
                "HUMAN_ATTENTION_REQUIRED": False,
                "WORKER_STATUS": terminal,
                "WORKER_PID": None,
                "ACTIVE_PROCESS_KIND": "",
                "ACTIVE_THREAD_ID": "",
                "FILES_CHANGED": changes["changed"],
                "FILES_CREATED": changes["created"],
                "DEPENDENCIES_ADDED": changes["dependencies"],
                "TERMINAL_OUTCOME": terminal,
            }, new_state=terminal, event="TASK_COMPLETED", detail=f"outcome={terminal};worktree_preserved={state['WORKTREE']};deferred={len(deferred)}", mutate=complete_all)
            return
        elif action == "DONE":
            return
        else:
            _block(task_id, "UNKNOWN_NEXT_ACTION", action)
            return


def _dispatch(task_id: str) -> None:
    state = load_state(task_id)
    if int(state.get("HARNESS_VERSION", 2)) < 3:
        _dispatch_r2_compat(task_id)
        return
    _dispatch_r3(task_id)


def _pid_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                text=True, capture_output=True, check=False, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def recover_if_interrupted(task_id: str) -> dict[str, Any]:
    state = load_state(task_id)
    if state["HARNESS_STATE"] not in ACTIVE_STATES:
        return state
    controller_alive = _pid_alive(state.get("CONTROLLER_PID"))
    worker_alive = _pid_alive(state.get("WORKER_PID"))
    if controller_alive is not False or worker_alive is not False:
        return state
    if not state.get("CONTROLLER_PID") and not state.get("WORKER_PID"):
        updated = datetime.fromisoformat(state["LAST_UPDATED_AT"])
        if (datetime.now(timezone.utc) - updated).total_seconds() < 10:
            return state
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    changes = _git_changes(worktree) if worktree and worktree.is_dir() else {"changed": [], "created": [], "dependencies": []}
    if state["HARNESS_STATE"] == "STOPPING" or state.get("STOP_REQUESTED"):
        def stop_mutate(value: dict[str, Any]) -> None:
            _close_active_plan(value, "PENDING")

        return update_task(task_id, {
            "WORKER_STATUS": "STOPPED_PROCESS_NOT_RUNNING", "WORKER_PID": None, "CONTROLLER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "", "CURRENT_PHASE": "STOPPED",
            "CURRENT_ACTION": "Cooperative stop completed; no recorded process remains active",
            "WHY_CURRENT_ACTION": "The stop request is preserved and both recorded process identities are confirmed inactive.",
            "NEXT_ACTION": "Human inspects the preserved state and worktree",
            "WHY_NEXT_ACTION": "R2 never deletes or merges useful work during stop recovery.",
            "FILES_CHANGED": changes["changed"], "FILES_CREATED": changes["created"], "DEPENDENCIES_ADDED": changes["dependencies"],
            "HUMAN_ATTENTION_REQUIRED": True,
        }, new_state="STOPPED", event="STOP_RECOVERY_COMPLETED", detail=(
            f"changed={len(changes['changed'])};recorded processes inactive"
        ), mutate=stop_mutate)
    if state.get("PAUSE_REQUESTED"):
        return update_task(task_id, {
            "WORKER_STATUS": "PAUSED_PROCESS_NOT_RUNNING",
            "WORKER_PID": None,
            "CONTROLLER_PID": None,
            "ACTIVE_THREAD_ID": "",
            "ACTIVE_PROCESS_KIND": "",
            "CURRENT_PHASE": "PAUSED",
            "CURRENT_ACTION": "Pause completed after interrupted process exit",
            "WHY_CURRENT_ACTION": "The explicit human pause remains authoritative.",
            "NEXT_ACTION": "Resume from the persisted checkpoint when requested",
            "WHY_NEXT_ACTION": "No autonomous process remains active.",
        }, new_state="PAUSED", event="PAUSE_RECOVERY_COMPLETED", detail=(
            f"resume_point={state.get('NEXT_ACTION_CODE')}"
        ))
    if int(state.get("HARNESS_VERSION", 2)) >= 3:
        active_kind = str(state.get("ACTIVE_PROCESS_KIND", ""))
        running_ids = [
            str(unit.get("id")) for unit in state.get("WORK_UNITS", [])
            if unit.get("status") == "RUNNING"
        ]
        has_structured_checkpoint = bool(state.get("PENDING_UNIT_RESULTS"))
        if has_structured_checkpoint and running_ids:
            next_code = "UNIT_VALIDATE"
        elif active_kind == "REVIEW":
            next_code = "FINAL_REVIEW"
        elif active_kind == "PLANNER":
            next_code = "PLAN"
        elif active_kind == "WORKER":
            next_code = "SELECT_WORK"
        else:
            next_code = str(state.get("NEXT_ACTION_CODE", "SELECT_WORK"))

        def recover(value: dict[str, Any]) -> None:
            if running_ids and next_code != "UNIT_VALIDATE":
                for unit_id in running_ids:
                    unit = _unit_by_id(value, unit_id)
                    if unit is not None:
                        unit["status"] = "RETRY"
                        unit["last_checkpoint"] = (
                            "WORKER_INTERRUPTED_WITH_CHANGES"
                            if changes["changed"] else "WORKER_INTERRUPTED_NO_CHANGES"
                        )
                        unit["next_action"] = "Automatically retry from the persisted unit checkpoint"
                value["ACTIVE_WORK_UNIT_IDS"] = []
                value["ACTIVE_WORK_UNIT_ID"] = ""
                value["CURRENT_WORK_UNIT"] = ""
            value["CONTROLLER_PID"] = None
            value["WORKER_PID"] = None
            value["ACTIVE_THREAD_ID"] = ""
            value["ACTIVE_PROCESS_KIND"] = ""
            value["NEXT_ACTION_CODE"] = next_code
            value["WORKER_STATUS"] = "AUTOMATIC_CRASH_RECOVERY_PENDING"
            value["CURRENT_PHASE"] = "AUTOMATIC_RECOVERY"
            value["CURRENT_ACTION"] = "Interrupted process recovered from persisted R3 checkpoint"
            value["WHY_CURRENT_ACTION"] = "Both recorded processes are inactive; the supervisor may safely restart one controller."
            value["NEXT_ACTION"] = f"Continue automatically at {next_code}"
            value["WHY_NEXT_ACTION"] = "Completed units remain terminal and are never rerun."
            value["FILES_CHANGED"] = changes["changed"]
            value["FILES_CREATED"] = changes["created"]
            value["DEPENDENCIES_ADDED"] = changes["dependencies"]
            value["HUMAN_ATTENTION_REQUIRED"] = False
            _close_active_plan(value, "PENDING")
            _telemetry_add(value, crash_recoveries=1)
            _meaningful_progress(value, f"AUTOMATIC_CRASH_RECOVERY:{next_code}")

        return update_task(
            task_id, new_state="RUNNING", event="AUTOMATIC_CRASH_RECOVERY",
            detail=f"resume_point={next_code};kind={active_kind};changed={len(changes['changed'])}",
            mutate=recover,
        )
    def mutate(value: dict[str, Any]) -> None:
        _close_active_plan(value, "PENDING")

    return update_task(task_id, {
        "WORKER_STATUS": "INTERRUPTED_PROCESS_NOT_RUNNING", "WORKER_PID": None, "CONTROLLER_PID": None,
        "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "", "CURRENT_PHASE": "WAITING_HUMAN",
        "CURRENT_ACTION": "Recovered interrupted task state; no partial work was discarded",
        "WHY_CURRENT_ACTION": "Neither recorded controller nor worker PID is active; human review is required before redispatch.",
        "NEXT_ACTION": "Human inspects the recovered state and explicitly resumes, reviews, or stops",
        "WHY_NEXT_ACTION": "No controller or worker remains active; autonomous work cannot safely continue without a human decision.",
        "FILES_CHANGED": changes["changed"], "FILES_CREATED": changes["created"], "DEPENDENCIES_ADDED": changes["dependencies"],
        "HUMAN_ATTENTION_REQUIRED": True,
    }, new_state="WAITING_HUMAN", event="CRASH_RECOVERY", detail=f"resume_point={state.get('NEXT_ACTION_CODE')};changed={len(changes['changed'])}", mutate=mutate)


def _record_controller_failure(task_id: str, exc: Exception) -> dict[str, Any]:
    state = load_state(task_id)
    worker_pid = state.get("WORKER_PID")
    worker_liveness = _pid_alive(worker_pid)
    worker_has_identity = isinstance(worker_pid, int) and worker_pid > 0
    worker_may_be_alive = worker_has_identity and worker_liveness is not False
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    inventory_error = ""
    if worktree and worktree.is_dir():
        try:
            _refresh_changes(task_id)
        except Exception as inventory_exc:
            inventory_error = f";inventory={type(inventory_exc).__name__}:{inventory_exc}"[:2_000]
    detail = f"{type(exc).__name__}:{exc}{inventory_error}"[:MAX_TEXT]
    trace_tail = traceback.format_exc()[-MAX_SUPERVISOR_DIAGNOSTIC_BYTES:]

    if int(state.get("HARNESS_VERSION", 2)) >= 3:
        def r3_recovery(value: dict[str, Any]) -> None:
            value["CONTROLLER_EXIT_CODE"] = 1
            value["CONTROLLER_EXCEPTION"] = detail
            value["CONTROLLER_STDERR_TAIL"] = trace_tail
            value["CONTROLLER_STARTUP_STATUS"] = "RUNTIME_FAILED"
            value["WORKER_STATUS"] = (
                "ORPHANED_RUNNING" if worker_liveness is True
                else "ORPHANED_STATUS_UNKNOWN" if worker_may_be_alive
                else "CONTROLLER_RECOVERY_PENDING"
            )
            value["CURRENT_PHASE"] = "AUTOMATIC_RECOVERY"
            value["CURRENT_ACTION"] = (
                "Controller failed; live worker identity is preserved"
                if worker_may_be_alive else "Controller failed; supervisor restart is pending"
            )
            value["WHY_CURRENT_ACTION"] = detail
            value["NEXT_ACTION"] = (
                "Supervisor waits for the recorded worker to exit before controller replacement"
                if worker_may_be_alive else "Supervisor starts one replacement controller from persisted state"
            )
            value["WHY_NEXT_ACTION"] = "Process liveness and the state lock prevent duplicate controller or worker dispatch."
            value["HUMAN_ATTENTION_REQUIRED"] = False
            _close_active_plan(value, "PENDING")

        return update_task(
            task_id, new_state="RUNNING", event=(
                "CONTROLLER_FAILED_WORKER_PRESERVED" if worker_may_be_alive
                else "CONTROLLER_AUTOMATIC_RECOVERY_PENDING"
            ), detail=f"worker_pid={worker_pid};liveness={worker_liveness};{detail}",
            mutate=r3_recovery,
        )

    if worker_may_be_alive:
        def preserve_active_worker(value: dict[str, Any]) -> None:
            _close_active_plan(value, "PENDING")

        liveness = "ALIVE" if worker_liveness is True else "UNKNOWN_FAIL_CLOSED"
        return update_task(task_id, {
            "WORKER_STATUS": "INTERRUPTED_CONTROLLER_WORKER_ALIVE" if worker_liveness is True else "INTERRUPTED_CONTROLLER_WORKER_STATUS_UNKNOWN",
            "CONTROLLER_PID": None,
            "CURRENT_PHASE": "WAITING_HUMAN",
            "CURRENT_ACTION": "Controller failed while the recorded worker may still be active",
            "WHY_CURRENT_ACTION": detail,
            "NEXT_ACTION": "Human stops or recovers the orphaned worker, then reviews the preserved worktree",
            "WHY_NEXT_ACTION": "Worker identity is preserved because controller failure cannot prove the mutating process is inactive.",
            "HUMAN_ATTENTION_REQUIRED": True,
        }, new_state="WAITING_HUMAN", event="CONTROLLER_FAILED_WORKER_PRESERVED", detail=(
            f"worker_pid={worker_pid};liveness={liveness};{detail}"
        ), mutate=preserve_active_worker)

    def mark_controller_failed(value: dict[str, Any]) -> None:
        _close_active_plan(value, "FAILED")

    return update_task(task_id, {
        "WORKER_STATUS": "CONTROLLER_FAILED", "WORKER_PID": None, "CONTROLLER_PID": None,
        "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "", "CURRENT_PHASE": "FAILED",
        "CURRENT_ACTION": "Controller failed; state and worktree preserved",
        "WHY_CURRENT_ACTION": detail,
        "NEXT_ACTION": "Human inspects the preserved state or runs a read-only review",
        "WHY_NEXT_ACTION": "The worker is confirmed inactive, so terminal controller failure does not hide a mutating process.",
        "HUMAN_ATTENTION_REQUIRED": True,
    }, new_state="FAILED", event="CONTROLLER_FAILED", detail=detail, mutate=mark_controller_failed)


def _record_controller_startup_failure(
    task_id: str, reason: str, *, pid: int | None, exit_code: int | None,
) -> dict[str, Any]:
    current = load_state(task_id)
    signature = _failure_signature("CONTROLLER_BOOTSTRAP", reason)
    key = signature
    prior = current.setdefault("RETRY_LEDGER", {}).get(key, {})
    count = int(prior.get("count", 0)) + 1
    retry_allowed = count <= CONTROLLER_STARTUP_RETRY_LIMIT
    backoff = min(8.0, CONTROLLER_STARTUP_BACKOFF_SECONDS * (2 ** (count - 1)))
    effective_exit = exit_code if exit_code is not None else current.get("CONTROLLER_EXIT_CODE")
    tail = _diagnostic_tail(controller_bootstrap_log_path(task_id)) or str(
        current.get("CONTROLLER_STDERR_TAIL", "")
    )

    def record(value: dict[str, Any]) -> None:
        value.setdefault("RETRY_LEDGER", {})[key] = {
            "count": count,
            "progress_hash": "CONTROLLER_NOT_READY",
            "last_attempted_remedy": "AUTONOMOUS_CONTROLLER_RESTART",
            "last_detail": reason[:1_000],
            "updated_at": utc_now(),
        }
        value["CONTROLLER_PID"] = None
        value["CONTROLLER_LAUNCH_TOKEN"] = ""
        value["CONTROLLER_EXIT_CODE"] = effective_exit
        value["CONTROLLER_EXCEPTION"] = reason[:MAX_TEXT]
        value["CONTROLLER_STDERR_TAIL"] = tail[-MAX_SUPERVISOR_DIAGNOSTIC_BYTES:]
        value["CONTROLLER_STARTUP_RETRY_SIGNATURE"] = signature
        value["CONTROLLER_STARTUP_RETRY_COUNT"] = count
        value["CONTROLLER_STARTUP_RETRY_BACKOFF_SECONDS"] = backoff if retry_allowed else 0.0
        value["CURRENT_RETRY_SIGNATURE"] = signature
        value["CURRENT_RETRY_COUNT"] = count
        value["CONTROLLER_STARTUP_STATUS"] = "RETRY" if retry_allowed else "FAILED"
        value["WORKER_STATUS"] = (
            "CONTROLLER_STARTUP_RETRY" if retry_allowed else "CONTROLLER_STARTUP_FAILED"
        )
        value["CURRENT_PHASE"] = (
            "CONTROLLER_STARTUP_RETRY" if retry_allowed else "CONTROLLER_STARTUP_FAILED"
        )
        value["CURRENT_ACTION"] = (
            "Controller bootstrap failed; bounded automatic retry scheduled"
            if retry_allowed else
            "Controller bootstrap repeatedly failed before autonomous execution"
        )
        value["WHY_CURRENT_ACTION"] = reason[:MAX_TEXT]
        value["NEXT_ACTION"] = (
            f"Retry Controller bootstrap after {backoff:.1f}s"
            if retry_allowed else
            "Inspect the preserved Controller bootstrap diagnostics"
        )
        value["WHY_NEXT_ACTION"] = (
            "The normalized startup signature remains within its bounded retry budget."
            if retry_allowed else
            "The same deterministic startup failure exhausted its autonomous retry budget."
        )
        value["HUMAN_ATTENTION_REQUIRED"] = False
        if not retry_allowed:
            value["LAST_COMPLETED"] = "CONTROLLER_STARTUP_FAILED"
            value["TERMINAL_OUTCOME"] = "CONTROLLER_STARTUP_FAILED"
            _close_active_plan(value, "FAILED")

    result = update_task(
        task_id, new_state=(None if retry_allowed else "FAILED"),
        event=("CONTROLLER_STARTUP_RETRY" if retry_allowed else "CONTROLLER_STARTUP_FAILED"),
        detail=f"signature={signature};count={count};pid={pid};exit={effective_exit};{reason[:500]}",
        mutate=record,
    )
    return result


def run_task(task_id: str, *, launch_token: str = "") -> int:
    bootstrap_state = load_state(task_id)
    prior = bootstrap_state.get("CONTROLLER_PID")
    token_adoption = _launch_token_adoption(bootstrap_state, "CONTROLLER", launch_token)
    if prior not in (None, os.getpid()) and _pid_alive(prior) is not False and not token_adoption:
        raise HarnessError(
            f"DUPLICATE_CONTROLLER_PREVENTED:recorded={prior};current={os.getpid()}"
        )
    exit_code = 1
    ready = False
    try:
        started_at = utc_now()
        update_task(task_id, {
            "CONTROLLER_PID": os.getpid(),
            "CONTROLLER_LAUNCH_TOKEN": "",
            "CONTROLLER_PARENT_PID": os.getppid(),
            "CONTROLLER_STARTED_AT": started_at,
            "CONTROLLER_STARTUP_STATUS": "STARTED",
            "CONTROLLER_EXIT_CODE": None,
            "CONTROLLER_EXCEPTION": "",
        }, event="CONTROLLER_STARTED", detail=f"pid={os.getpid()};parent={os.getppid()}")
        ready_at = utc_now()
        update_task(task_id, {
            "CONTROLLER_READY_AT": ready_at,
            "CONTROLLER_HEARTBEAT_AT": ready_at,
            "CONTROLLER_STARTUP_STATUS": "READY",
            "CONTROLLER_STARTUP_RETRY_SIGNATURE": "",
            "CONTROLLER_STARTUP_RETRY_COUNT": 0,
            "CONTROLLER_STARTUP_RETRY_BACKOFF_SECONDS": 0.0,
            "CURRENT_RETRY_SIGNATURE": "",
            "CURRENT_RETRY_COUNT": 0,
        }, event="CONTROLLER_READY", detail=f"pid={os.getpid()};heartbeat={ready_at}")
        ready = True
        _dispatch(task_id)
        exit_code = 0
    except Exception as exc:
        exception_text = f"{type(exc).__name__}:{exc}"[:MAX_TEXT]
        trace_tail = traceback.format_exc()[-MAX_SUPERVISOR_DIAGNOSTIC_BYTES:]
        control_state = load_state(task_id)
        controlled_transition_exit = bool(
            isinstance(exc, HarnessError)
            and str(exc).startswith("INVALID_STATE_TRANSITION:")
            and (
                (
                    control_state.get("STOP_REQUESTED")
                    and control_state.get("HARNESS_STATE") in {"STOPPING", "STOPPED"}
                )
                or (
                    control_state.get("PAUSE_REQUESTED")
                    and control_state.get("HARNESS_STATE") == "PAUSED"
                )
            )
        )
        if controlled_transition_exit:
            exit_code = 0
            update_task(task_id, {
                "CONTROLLER_EXCEPTION": "",
                "CONTROLLER_STDERR_TAIL": "",
            }, event="CONTROLLER_CONTROL_BOUNDARY_EXIT", detail=(
                f"state={control_state.get('HARNESS_STATE')};{exception_text}"
            ))
        else:
            try:
                if ready:
                    _record_controller_failure(task_id, exc)
                    update_task(task_id, {
                        "CONTROLLER_EXIT_CODE": 1,
                        "CONTROLLER_EXCEPTION": exception_text,
                        "CONTROLLER_STDERR_TAIL": trace_tail,
                        "CONTROLLER_STARTUP_STATUS": "RUNTIME_FAILED",
                    })
                else:
                    update_task(task_id, {
                        "CONTROLLER_EXIT_CODE": 1,
                        "CONTROLLER_EXCEPTION": exception_text,
                        "CONTROLLER_STDERR_TAIL": trace_tail,
                        "CONTROLLER_STARTUP_STATUS": "FAILED",
                    }, event="CONTROLLER_INITIALIZATION_FAILED", detail=exception_text)
            except Exception:
                pass
            traceback.print_exc(file=sys.stderr)
    finally:
        try:
            current = load_state(task_id)
            if current.get("CONTROLLER_PID") == os.getpid():
                status = str(current.get("CONTROLLER_STARTUP_STATUS", ""))
                update_task(task_id, {
                    "CONTROLLER_EXIT_CODE": exit_code,
                    "CONTROLLER_STARTUP_STATUS": (
                        status if status in {"FAILED", "RUNTIME_FAILED"} else "EXITED"
                    ),
                    "CONTROLLER_STDERR_TAIL": (
                        current.get("CONTROLLER_STDERR_TAIL") or
                        _diagnostic_tail(controller_bootstrap_log_path(task_id))
                    ),
                }, event="CONTROLLER_EXITED", detail=f"pid={os.getpid()};exit={exit_code}")
        except Exception:
            pass
    return exit_code


def _wait_for_controller_startup(
    task_id: str, process: subprocess.Popen[Any], *, timeout: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        exit_code = process.poll()
        state = load_state(task_id)
        runtime_pid = state.get("CONTROLLER_PID")
        runtime_alive = (
            exit_code is None
            if runtime_pid == process.pid
            else _pid_alive(runtime_pid) is not False
        )
        if (
            state.get("CONTROLLER_LAUNCH_PID") == process.pid
            and state.get("CONTROLLER_STARTUP_STATUS") == "READY"
            and state.get("CONTROLLER_STARTED_AT")
            and state.get("CONTROLLER_HEARTBEAT_AT")
            and runtime_alive
        ):
            return state
        launcher_exit_without_adoption = (
            exit_code is not None and runtime_pid in {None, process.pid}
        )
        failed_and_inactive = (
            state.get("CONTROLLER_STARTUP_STATUS") in {"FAILED", "RUNTIME_FAILED", "EXITED"}
            and runtime_alive is False
        )
        if launcher_exit_without_adoption or failed_and_inactive:
            reason = state.get("CONTROLLER_EXCEPTION") or "Controller exited before READY"
            _record_controller_startup_failure(
                task_id, str(reason), pid=int(runtime_pid or process.pid), exit_code=exit_code,
            )
            return None
        time.sleep(SUPERVISOR_STARTUP_POLL_SECONDS)
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass
    reason = f"Controller did not emit READY within {timeout:.1f}s"
    _record_controller_startup_failure(
        task_id, reason, pid=process.pid, exit_code=process.poll(),
    )
    return None


def _spawn_controller(
    task_id: str, *, startup_timeout: float = CONTROLLER_STARTUP_TIMEOUT_SECONDS,
) -> int | None:
    state = load_state(task_id)
    if state["HARNESS_STATE"] not in ACTIVE_STATES:
        return None
    existing = state.get("CONTROLLER_PID")
    if existing and _pid_alive(existing) is not False:
        return int(existing)
    try:
        runtime = _ensure_task_temp_runtime(task_id)
        environment = _task_temp_environment(runtime)
        log_path = controller_bootstrap_log_path(task_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (HarnessError, OSError) as exc:
        _record_controller_startup_failure(
            task_id,
            f"CONTROLLER_BOOTSTRAP_RUNTIME_UNAVAILABLE:{type(exc).__name__}:{exc}",
            pid=None, exit_code=None,
        )
        return None
    launch_token = secrets.token_hex(16)
    update_task(task_id, {
        "CONTROLLER_PID": None,
        "CONTROLLER_LAUNCH_PID": None,
        "CONTROLLER_LAUNCH_TOKEN": launch_token,
        "CONTROLLER_PARENT_PID": os.getpid(),
        "CONTROLLER_STARTED_AT": "",
        "CONTROLLER_READY_AT": "",
        "CONTROLLER_HEARTBEAT_AT": "",
        "CONTROLLER_EXIT_CODE": None,
        "CONTROLLER_EXCEPTION": "",
        "CONTROLLER_STDERR_TAIL": "",
        "CONTROLLER_STARTUP_STATUS": "STARTING",
        "CONTROLLER_BOOTSTRAP_LOG": str(log_path),
    }, event="CONTROLLER_STARTUP_BEGIN", detail=f"parent={os.getpid()};runtime={runtime}")
    python = _storage_paths().python_exe.resolve()
    command = [
        str(python), "-B", str(SCRIPT.resolve()), "_run",
        "--task-id", task_id, "--launch-token", launch_token,
    ]
    try:
        process, mode = _launch_background_process(
            command, environment=environment, log_path=log_path,
        )
    except HarnessError as exc:
        _record_controller_startup_failure(
            task_id, f"CONTROLLER_CREATE_PROCESS_FAILED:{exc}",
            pid=None, exit_code=None,
        )
        return None

    def record_dispatched(value: dict[str, Any]) -> None:
        value["CONTROLLER_LAUNCH_PID"] = process.pid
        value["CONTROLLER_SPAWN_MODE"] = mode
        if value.get("CONTROLLER_STARTUP_STATUS") not in {"STARTED", "READY"}:
            value["CONTROLLER_PID"] = process.pid
            value["CONTROLLER_STARTUP_STATUS"] = "STARTING"

    update_task(
        task_id, event="CONTROLLER_DISPATCHED",
        detail=f"pid={process.pid};parent={os.getpid()};mode={mode}",
        mutate=record_dispatched,
    )
    ready_state = _wait_for_controller_startup(task_id, process, timeout=startup_timeout)
    if ready_state is None:
        return None
    runtime_pid = int(ready_state["CONTROLLER_PID"])
    update_task(task_id, event="CONTROLLER_STARTUP_HANDSHAKE_PASSED", detail=(
        f"pid={runtime_pid};launch_pid={process.pid};"
        f"started={ready_state['CONTROLLER_STARTED_AT']};"
        f"heartbeat={ready_state['CONTROLLER_HEARTBEAT_AT']}"
    ))
    return runtime_pid


def run_supervisor(
    task_id: str, *, poll_seconds: float = 2.0, launch_token: str = "",
) -> int:
    """Own one task until quiescence and always persist initialization/exit evidence."""
    exit_code = 1
    initialized = False
    try:
        bootstrap_state = load_state(task_id)
        prior = bootstrap_state.get("SUPERVISOR_PID")
        token_adoption = _launch_token_adoption(bootstrap_state, "SUPERVISOR", launch_token)
        if prior not in (None, os.getpid()) and _pid_alive(prior) is not False and not token_adoption:
            raise HarnessError(
                f"DUPLICATE_SUPERVISOR_PREVENTED:recorded={prior};current={os.getpid()}"
            )
        started_at = utc_now()
        update_task(task_id, {
            "SUPERVISOR_PID": os.getpid(),
            "SUPERVISOR_LAUNCH_TOKEN": "",
            "SUPERVISOR_PARENT_PID": os.getppid(),
            "SUPERVISOR_STARTED_AT": started_at,
            "SUPERVISOR_STARTUP_STATUS": "STARTED",
            "SUPERVISOR_EXIT_CODE": None,
            "SUPERVISOR_EXCEPTION": "",
        }, event="SUPERVISOR_STARTED", detail=f"pid={os.getpid()};parent={os.getppid()}")
        ready_at = utc_now()
        update_task(task_id, {
            "SUPERVISOR_READY_AT": ready_at,
            "SUPERVISOR_HEARTBEAT_AT": ready_at,
            "SUPERVISOR_STARTUP_STATUS": "READY",
        }, event="SUPERVISOR_READY", detail=f"pid={os.getpid()};heartbeat={ready_at}")
        initialized = True
        exit_code = 0
        last_heartbeat = time.monotonic()
        while True:
            state = load_state(task_id)
            if state["HARNESS_STATE"] in TERMINAL_STATES | {"PAUSED", "WAITING_HUMAN", "BLOCKED"}:
                break
            now = time.monotonic()
            if now - last_heartbeat >= 30:
                update_task(task_id, {"SUPERVISOR_HEARTBEAT_AT": utc_now()})
                last_heartbeat = now
                state = load_state(task_id)
            controller_alive = _pid_alive(state.get("CONTROLLER_PID"))
            worker_alive = _pid_alive(state.get("WORKER_PID"))
            if controller_alive is not False:
                time.sleep(poll_seconds)
                continue
            if worker_alive is not False:
                # Quiet workers are valid. No replacement controller starts while
                # the recorded mutating/reviewer process may still be alive.
                time.sleep(poll_seconds)
                continue
            if state.get("CONTROLLER_PID") or state.get("WORKER_PID"):
                try:
                    recover_if_interrupted(task_id)
                except HarnessError:
                    # A cooperative stop may become authoritative between this
                    # loop's liveness read and recovery's state transition.
                    if load_state(task_id)["HARNESS_STATE"] in TERMINAL_STATES | {
                        "PAUSED", "WAITING_HUMAN", "BLOCKED",
                    }:
                        break
                    raise
                state = load_state(task_id)
            if state["HARNESS_STATE"] in ACTIVE_STATES:
                _spawn_controller(task_id)
            latest = load_state(task_id)
            backoff = (
                float(latest.get("CONTROLLER_STARTUP_RETRY_BACKOFF_SECONDS", 0.0) or 0.0)
                if latest.get("CONTROLLER_STARTUP_STATUS") == "RETRY" else 0.0
            )
            time.sleep(max(poll_seconds, backoff))
    except BaseException as exc:
        exit_code = 1
        exception_text = f"{type(exc).__name__}:{exc}"[:MAX_TEXT]
        trace_tail = traceback.format_exc()[-MAX_SUPERVISOR_DIAGNOSTIC_BYTES:]
        try:
            update_task(task_id, {
                "SUPERVISOR_EXIT_CODE": exit_code,
                "SUPERVISOR_EXCEPTION": exception_text,
                "SUPERVISOR_STDERR_TAIL": trace_tail,
                "SUPERVISOR_STARTUP_STATUS": "FAILED" if not initialized else "RUNTIME_FAILED",
            }, event=(
                "SUPERVISOR_INITIALIZATION_FAILED" if not initialized else "SUPERVISOR_RUNTIME_FAILED"
            ), detail=exception_text)
        except Exception:
            pass
        traceback.print_exc(file=sys.stderr)
    finally:
        try:
            current = load_state(task_id)
            if current.get("SUPERVISOR_PID") == os.getpid():
                status = str(current.get("SUPERVISOR_STARTUP_STATUS", ""))
                update_task(task_id, {
                    "SUPERVISOR_EXIT_CODE": exit_code,
                    "SUPERVISOR_STARTUP_STATUS": (
                        status if status in {"FAILED", "RUNTIME_FAILED"} else "EXITED"
                    ),
                    "SUPERVISOR_STDERR_TAIL": (
                        current.get("SUPERVISOR_STDERR_TAIL") or
                        _diagnostic_tail(supervisor_bootstrap_log_path(task_id))
                    ),
                }, event="SUPERVISOR_EXITED", detail=f"pid={os.getpid()};exit={exit_code}")
        except Exception:
            pass
    return exit_code


def _record_supervisor_startup_failure(
    task_id: str, reason: str, *, pid: int | None, exit_code: int | None,
) -> None:
    log_path = supervisor_bootstrap_log_path(task_id)
    tail = _diagnostic_tail(log_path)
    current = load_state(task_id)
    target_state = None if current["HARNESS_STATE"] in TERMINAL_STATES else "FAILED"

    def mark_failed(value: dict[str, Any]) -> None:
        _close_active_plan(value, "FAILED")

    update_task(task_id, {
        "SUPERVISOR_PID": pid,
        "SUPERVISOR_EXIT_CODE": exit_code,
        "SUPERVISOR_EXCEPTION": reason[:MAX_TEXT],
        "SUPERVISOR_STDERR_TAIL": tail,
        "SUPERVISOR_STARTUP_STATUS": "FAILED",
        "CURRENT_PHASE": "SUPERVISOR_STARTUP_FAILED",
        "CURRENT_ACTION": "Supervisor failed before autonomous execution became authoritative",
        "WHY_CURRENT_ACTION": reason[:MAX_TEXT],
        "LAST_COMPLETED": "SUPERVISOR_STARTUP_FAILED",
        "NEXT_ACTION": "Correct the Supervisor bootstrap defect, then start a new task",
        "WHY_NEXT_ACTION": "This start attempt is terminal and no Supervisor owns the task.",
        "HUMAN_ATTENTION_REQUIRED": True,
        "WORKER_STATUS": "SUPERVISOR_STARTUP_FAILED",
        "TERMINAL_OUTCOME": "SUPERVISOR_STARTUP_FAILED",
    }, new_state=target_state, event="SUPERVISOR_STARTUP_FAILED", detail=(
        f"pid={pid};exit={exit_code};{reason[:700]}"
    ), mutate=mark_failed)


def _wait_for_supervisor_startup(
    task_id: str, process: subprocess.Popen[Any], *, timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        exit_code = process.poll()
        # poll() and the child can advance concurrently; read authoritative
        # persisted startup state only after observing the launcher status.
        state = load_state(task_id)
        runtime_pid = state.get("SUPERVISOR_PID")
        runtime_alive = (
            exit_code is None
            if runtime_pid == process.pid
            else _pid_alive(runtime_pid) is not False
        )
        if (
            state.get("SUPERVISOR_LAUNCH_PID") == process.pid
            and state.get("SUPERVISOR_STARTUP_STATUS") == "READY"
            and state.get("SUPERVISOR_STARTED_AT")
            and state.get("SUPERVISOR_HEARTBEAT_AT")
            and runtime_alive
        ):
            return state
        launcher_exit_without_adoption = (
            exit_code is not None and runtime_pid in {None, process.pid}
        )
        if launcher_exit_without_adoption or state.get("SUPERVISOR_STARTUP_STATUS") in {"FAILED", "RUNTIME_FAILED", "EXITED"}:
            reason = state.get("SUPERVISOR_EXCEPTION") or "Supervisor exited before READY"
            _record_supervisor_startup_failure(
                task_id, str(reason), pid=int(runtime_pid or process.pid), exit_code=exit_code,
            )
            raise HarnessError(
                f"SUPERVISOR_STARTUP_FAILED:{task_id}:pid={process.pid}:exit={exit_code}:{reason}"
            )
        time.sleep(SUPERVISOR_STARTUP_POLL_SECONDS)
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass
    exit_code = process.poll()
    reason = f"Supervisor did not emit READY within {timeout:.1f}s"
    _record_supervisor_startup_failure(
        task_id, reason, pid=process.pid, exit_code=exit_code,
    )
    raise HarnessError(
        f"SUPERVISOR_STARTUP_FAILED:{task_id}:pid={process.pid}:exit={exit_code}:timeout={timeout:.1f}s"
    )


def _spawn_supervisor(
    task_id: str, *, startup_timeout: float = SUPERVISOR_STARTUP_TIMEOUT_SECONDS,
) -> int:
    existing_state = load_state(task_id)
    existing = existing_state.get("SUPERVISOR_PID")
    if existing and _pid_alive(existing) is not False:
        if (
            existing_state.get("SUPERVISOR_STARTUP_STATUS") == "READY"
            and existing_state.get("SUPERVISOR_HEARTBEAT_AT")
        ):
            return int(existing)
        raise HarnessError(f"SUPERVISOR_STARTUP_ALREADY_IN_PROGRESS:{existing}")
    log_path = supervisor_bootstrap_log_path(task_id)
    try:
        runtime = _ensure_task_temp_runtime(task_id)
        environment = _task_temp_environment(runtime)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _bound_bootstrap_log(log_path)
    except (HarnessError, OSError) as exc:
        reason = f"SUPERVISOR_BOOTSTRAP_RUNTIME_UNAVAILABLE:{type(exc).__name__}:{exc}"
        _record_supervisor_startup_failure(task_id, reason, pid=None, exit_code=None)
        raise HarnessError(f"SUPERVISOR_STARTUP_FAILED:{task_id}:{reason}") from exc
    launch_token = secrets.token_hex(16)
    update_task(task_id, {
        "SUPERVISOR_PID": None,
        "SUPERVISOR_LAUNCH_PID": None,
        "SUPERVISOR_LAUNCH_TOKEN": launch_token,
        "SUPERVISOR_PARENT_PID": os.getpid(),
        "SUPERVISOR_STARTED_AT": "",
        "SUPERVISOR_READY_AT": "",
        "SUPERVISOR_HEARTBEAT_AT": "",
        "SUPERVISOR_EXIT_CODE": None,
        "SUPERVISOR_EXCEPTION": "",
        "SUPERVISOR_STDERR_TAIL": "",
        "SUPERVISOR_STARTUP_STATUS": "STARTING",
        "SUPERVISOR_BOOTSTRAP_LOG": str(log_path),
    }, event="SUPERVISOR_STARTUP_BEGIN", detail=f"parent={os.getpid()};runtime={runtime}")
    python = _storage_paths().python_exe.resolve()
    command = [
        str(python), "-B", str(SCRIPT.resolve()), "_supervise",
        "--task-id", task_id, "--launch-token", launch_token,
    ]
    try:
        process, mode = _launch_background_process(
            command, environment=environment, log_path=log_path,
        )
        update_task(task_id, {"SUPERVISOR_SPAWN_MODE": mode})
    except HarnessError as exc:
        reason = f"SUPERVISOR_CREATE_PROCESS_FAILED:{exc}"
        _record_supervisor_startup_failure(task_id, reason, pid=None, exit_code=None)
        raise HarnessError(f"SUPERVISOR_STARTUP_FAILED:{task_id}:{reason}")

    def record_dispatched(value: dict[str, Any]) -> None:
        value["SUPERVISOR_LAUNCH_PID"] = process.pid
        if value.get("SUPERVISOR_STARTUP_STATUS") not in {"STARTED", "READY"}:
            value["SUPERVISOR_PID"] = process.pid
            value["SUPERVISOR_STARTUP_STATUS"] = "STARTING"

    update_task(
        task_id, event="SUPERVISOR_DISPATCHED",
        detail=f"pid={process.pid};parent={os.getpid()};mode={load_state(task_id).get('SUPERVISOR_SPAWN_MODE')}",
        mutate=record_dispatched,
    )
    ready = _wait_for_supervisor_startup(task_id, process, timeout=startup_timeout)
    runtime_pid = int(ready["SUPERVISOR_PID"])
    update_task(task_id, event="SUPERVISOR_STARTUP_HANDSHAKE_PASSED", detail=(
        f"pid={runtime_pid};launch_pid={process.pid};"
        f"started={ready['SUPERVISOR_STARTED_AT']};heartbeat={ready['SUPERVISOR_HEARTBEAT_AT']}"
    ))
    return runtime_pid


def _positive_hours(value: str) -> float:
    hours = float(value)
    if not (0 < hours <= 168):
        raise argparse.ArgumentTypeError("--max-hours must be greater than 0 and at most 168")
    return hours


def command_start(args: argparse.Namespace) -> int:
    goal = args.goal.strip()
    if not goal or len(goal) > MAX_TEXT:
        raise HarnessError(f"GOAL_REQUIRED_MAX_{MAX_TEXT}_CHARS")
    task_id = args.task_id or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    validate_task_id(task_id)
    pointer = state_root() / "current_task.txt"
    if pointer.is_file():
        prior_id = pointer.read_text(encoding="utf-8").strip()
        if prior_id and state_path(prior_id).is_file() and load_state(prior_id)["HARNESS_STATE"] not in TERMINAL_STATES:
            raise HarnessError(f"ACTIVE_TASK_EXISTS:{prior_id}")
    if task_dir(task_id).exists():
        raise HarnessError(f"TASK_ID_ALREADY_EXISTS_PRESERVE_STATE:{task_id}")
    contract = _task_contract(goal, args.task_kind, args.task_scope)
    scope = contract["TASK_SCOPE"]
    state = _new_state(
        task_id, goal, scope, args.max_corrections, contract,
        max_hours=getattr(args, "max_hours", None),
    )
    task_dir(task_id).mkdir(parents=True, exist_ok=False)
    _write_state_unlocked(task_id, state)
    _append_event_unlocked(
        task_id, "TASK_ACCEPTED",
        f"task_kind={contract['TASK_KIND']};source={contract['TASK_KIND_SOURCE']};scope={scope};goal_version=1",
    )
    _set_current_task(task_id)
    conflicts = hard_guard_conflicts(goal)
    if conflicts:
        _block(task_id, "HARD_GUARD_CONFLICT", ",".join(conflicts))
        print(f"TASK_ID={task_id}\nHARNESS_STATE=BLOCKED\nHARD_GUARD_CONFLICT={','.join(conflicts)}")
        return 2
    if args.foreground:
        code = run_task(task_id)
        command_status(argparse.Namespace(task_id=task_id))
        return code
    pid = _spawn_supervisor(task_id)
    print(f"TASK_ID={task_id}\nHARNESS_STATE=PLANNING\nSUPERVISOR_PID={pid}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = load_state(task_id)
    counts = _work_unit_counts(state)
    remaining = _remaining_budget_seconds(state)
    keys = (
        "TASK_ID", "HARNESS_STATE", "CURRENT_PHASE", "CURRENT_ACTION", "PROGRESS_SUMMARY",
        "LAST_COMPLETED", "NEXT_ACTION", "OVERFIT_GUARD", "ANTI_BLOAT",
        "ANTI_BLOAT_TASK_DELTA", "REUSE_GUARD", "WORKER_STATUS",
        "ACTIVE_PROCESS_KIND", "CURRENT_WORK_UNIT", "LAST_MEANINGFUL_PROGRESS_AT",
        "CURRENT_RETRY_SIGNATURE", "CURRENT_RETRY_COUNT", "LAST_CHECKPOINT",
        "CONTROLLER_VALIDATION_STATUS", "CONTROLLER_PID", "CONTROLLER_LAUNCH_PID",
        "CONTROLLER_PARENT_PID", "CONTROLLER_STARTUP_STATUS", "CONTROLLER_STARTED_AT",
        "CONTROLLER_READY_AT", "CONTROLLER_HEARTBEAT_AT", "CONTROLLER_EXIT_CODE",
        "CONTROLLER_EXCEPTION", "CONTROLLER_STDERR_TAIL",
        "CONTROLLER_STARTUP_RETRY_SIGNATURE", "CONTROLLER_STARTUP_RETRY_COUNT",
        "SUPERVISOR_PID", "SUPERVISOR_LAUNCH_PID",
        "SUPERVISOR_PARENT_PID",
        "SUPERVISOR_STARTUP_STATUS", "SUPERVISOR_STARTED_AT", "SUPERVISOR_READY_AT",
        "SUPERVISOR_HEARTBEAT_AT", "SUPERVISOR_EXIT_CODE", "SUPERVISOR_EXCEPTION",
        "SUPERVISOR_STDERR_TAIL", "HUMAN_ATTENTION_REQUIRED", "LAST_UPDATED_AT",
    )
    for key in keys:
        value = str(state.get(key)).replace("\r", "\\r").replace("\n", "\\n")
        print(f"{key}={value}")
    print(f"ELAPSED_SECONDS={_seconds_since(str(state.get('TASK_STARTED_AT', ''))):.1f}")
    print(f"REMAINING_BUDGET_SECONDS={'UNBOUNDED' if remaining is None else f'{remaining:.1f}'}")
    print(f"SUPERVISOR_ALIVE={_pid_alive(state.get('SUPERVISOR_PID'))}")
    print(f"CONTROLLER_ALIVE={_pid_alive(state.get('CONTROLLER_PID'))}")
    print(f"ACTIVE_WORKER_OR_REVIEWER_ALIVE={_pid_alive(state.get('WORKER_PID'))}")
    print(f"WORK_UNITS_DONE={counts['done']}")
    print(f"WORK_UNITS_TOTAL={counts['total']}")
    print(f"WORK_UNITS_RUNNABLE={counts['runnable']}")
    print(f"WORK_UNITS_LOCAL_BLOCKED={counts['local_blocked']}")
    print(f"ACTIVE_BLOCKERS={json.dumps(state.get('ACTIVE_BLOCKERS', []), ensure_ascii=False, separators=(',', ':'))}")
    print(f"FILES_CHANGED_COUNT={len(state.get('FILES_CHANGED', []))}")
    print(f"FILES_CREATED_COUNT={len(state.get('FILES_CREATED', []))}")
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = load_state(task_id)
    if state.get("WORKTREE") and Path(state["WORKTREE"]).is_dir():
        state = dict(state)
        state["WORKTREE_STATUS"] = _git(["status", "--short", "--branch"], Path(state["WORKTREE"])).stdout.splitlines()[:MAX_LIST_ITEMS]
        state["HUMAN_INTEGRATION_COMMAND"] = f"git -C {state['WORKTREE']} diff --stat && git -C {state['WORKTREE']} diff"
    print(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def command_timeline(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    path = timeline_path(task_id)
    if not path.is_file():
        raise HarnessError(f"TIMELINE_NOT_FOUND:{task_id}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows[-args.limit:]:
        print(f"{row['at']} | {row['event']} | {row['detail']}")
    return 0


def command_pause(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    if state["HARNESS_STATE"] in TERMINAL_STATES | {"PAUSED"}:
        print(f"TASK_ID={task_id}\nHARNESS_STATE={state['HARNESS_STATE']}")
        return 0
    if state["HARNESS_STATE"] in {"BLOCKED", "WAITING_HUMAN"}:
        print(f"TASK_ID={task_id}\nHARNESS_STATE={state['HARNESS_STATE']}\nAUTONOMY_ALREADY_QUIESCENT=True")
        return 0
    target = "PAUSING" if state.get("WORKER_PID") else "PAUSED"
    updated = update_task(task_id, {
        "PAUSE_REQUESTED": True, "CURRENT_ACTION": "Pause requested; no new action will dispatch",
        "WHY_CURRENT_ACTION": "The current process may finish only to a safe checkpoint; files will not be killed mid-write.",
    }, new_state=target, event="PAUSE_REQUESTED", detail=f"active_kind={state.get('ACTIVE_PROCESS_KIND')}")
    queued, detail = _queue_control(updated, "HARNESS CONTROL: Pause requested. Reach the nearest safe checkpoint, start no new actions, summarize current state, and end this turn without discarding changes.")
    update_task(task_id, event="PAUSE_SIGNAL", detail=f"queued={queued};{detail}")
    print(f"TASK_ID={task_id}\nHARNESS_STATE={target}\nCOOPERATIVE_SIGNAL_QUEUED={queued}")
    return 0


def command_resume(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    if state["HARNESS_STATE"] not in {"PAUSED", "WAITING_HUMAN", "BLOCKED"}:
        raise HarnessError(f"RESUME_NOT_ALLOWED_FROM:{state['HARNESS_STATE']}")
    if state["HARNESS_STATE"] == "BLOCKED" and any(row.get("code") in {"HARD_GUARD_CONFLICT", "R1_PREFLIGHT_APPLICABLE_HARD_BLOCKER", "POST_CHANGE_R1_HARD_BLOCKER"} for row in state.get("BLOCKERS", [])):
        raise HarnessError("RESUME_REJECTED_UNRESOLVED_HARD_INVARIANT")
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    if state["WORKER_STATUS"] == "INTERRUPTED_PROCESS_NOT_RUNNING" and worktree and worktree.is_dir() and _git_changes(worktree)["changed"]:
        next_code = "VALIDATE"
    else:
        next_code = state.get("NEXT_ACTION_CODE", "R1_PREFLIGHT")
    waited = _seconds_since(str(state.get("WAITING_STARTED_AT", "")))
    def resume_mutate(value: dict[str, Any]) -> None:
        if waited:
            _telemetry_add(value, waiting_human_wall_seconds=waited)
        value["WAITING_STARTED_AT"] = ""
        _resolve_active_blockers(value)

    update_task(task_id, {
        "PAUSE_REQUESTED": False, "STOP_REQUESTED": False, "HUMAN_ATTENTION_REQUIRED": False,
        "NEXT_ACTION_CODE": next_code, "CURRENT_ACTION": "Resuming from authoritative task state",
        "WHY_CURRENT_ACTION": f"Continuation begins at {next_code}; prior work and timeline are preserved.",
    }, new_state="PLANNING" if next_code in {"R1_PREFLIGHT", "HARD_PREFLIGHT", "DISCOVER_EXISTING", "DISCOVER_REUSE", "CREATE_WORKTREE"} else "RUNNING", event="TASK_RESUMED", detail=f"resume_point={next_code}", mutate=resume_mutate)
    pid = run_task(task_id) if args.foreground else _spawn_supervisor(task_id)
    print(f"TASK_ID={task_id}\nHARNESS_STATE={load_state(task_id)['HARNESS_STATE']}\n{'CONTROLLER' if args.foreground else 'SUPERVISOR'}={pid}")
    return 0 if args.foreground else 0


def command_steer(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    instruction = args.instruction.strip()
    if not instruction or len(instruction) > 2_000:
        raise HarnessError("STEER_REQUIRED_MAX_2000_CHARS")
    conflicts = hard_guard_conflicts(instruction)
    state = recover_if_interrupted(task_id)
    if state["HARNESS_STATE"] in TERMINAL_STATES:
        raise HarnessError(f"STEER_NOT_ALLOWED_AFTER_TASK_{state['HARNESS_STATE']}; start a new authorized task")
    if conflicts:
        def rejected(value: dict[str, Any]) -> None:
            value["STEERING_HISTORY"] = (value.get("STEERING_HISTORY", []) + [{"at": utc_now(), "instruction": instruction, "accepted": False, "reason": conflicts}])[-20:]
        target = "PAUSING" if state.get("WORKER_PID") else "WAITING_HUMAN"
        updated = update_task(task_id, {
            "PAUSE_REQUESTED": True, "HUMAN_ATTENTION_REQUIRED": True,
            "CURRENT_ACTION": "Human steer conflicts with a hard Harness invariant",
            "WHY_CURRENT_ACTION": ",".join(conflicts),
        }, new_state=target, event="STEER_HARD_GUARD_CONFLICT", detail=f"{conflicts}:{instruction}", mutate=rejected)
        _queue_control(updated, "HARNESS CONTROL: Stop at the nearest safe checkpoint. A new human steer conflicts with hard repository invariants; do not apply it.")
        print(f"TASK_ID={task_id}\nHARD_GUARD_CONFLICT={','.join(conflicts)}\nHARNESS_STATE={target}")
        return 2
    def accepted(value: dict[str, Any]) -> None:
        value["GOAL_VERSION"] += 1
        value["STEERING_HISTORY"] = (value.get("STEERING_HISTORY", []) + [{"at": utc_now(), "instruction": instruction, "accepted": True}])[-20:]
        value["PENDING_STEER"] = (value.get("PENDING_STEER", []) + [instruction])[-20:]
    updated = update_task(task_id, {
        "NEXT_ACTION": "Apply recorded human steering at the next safe action boundary",
        "WHY_NEXT_ACTION": "Human direction has precedence over the task plan while hard invariants remain fixed.",
    }, event="HUMAN_STEER_ACCEPTED", detail=instruction, mutate=accepted)
    queued, detail = _queue_control(updated, f"HARNESS HUMAN STEER (goal revision {updated['GOAL_VERSION']}): {instruction}")
    update_task(task_id, event="STEER_SIGNAL", detail=f"queued={queued};{detail}")
    print(f"TASK_ID={task_id}\nGOAL_VERSION={updated['GOAL_VERSION']}\nQUEUED_TO_ACTIVE_WORKER={queued}")
    return 0


def command_review(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    if not state.get("WORKTREE"):
        raise HarnessError("REVIEW_REQUIRES_CREATED_WORKTREE")
    if state["HARNESS_STATE"] in ACTIVE_STATES:
        update_task(task_id, {"REVIEW_REQUESTED": True}, event="HUMAN_REVIEW_REQUESTED", detail="Will run at the next safe review boundary")
        print(f"TASK_ID={task_id}\nREVIEW_STATUS=QUEUED")
        return 0
    previous = state["HARNESS_STATE"]
    classification = _perform_review(task_id)
    current = load_state(task_id)
    if current["PAUSE_REQUESTED"] or current["STOP_REQUESTED"]:
        _control_checkpoint(task_id)
        print(f"TASK_ID={task_id}\nREVIEW_STATUS={classification}\nHARNESS_STATE={load_state(task_id)['HARNESS_STATE']}")
        return 0 if classification in {"PASS", "PASS_WITH_WARNINGS"} else 2
    if current["HARNESS_STATE"] != "BLOCKED":
        if classification in {"FIX_REQUIRED", "HUMAN_DECISION_REQUIRED"}:
            _wait_human(task_id, f"HUMAN_REVIEW_{classification}", current.get("REVIEW_FINDINGS", ""))
        else:
            update_task(task_id, {
                "CURRENT_PHASE": "INDEPENDENT_REVIEW",
                "CURRENT_ACTION": f"Human-requested independent review completed with {classification}",
                "WHY_CURRENT_ACTION": "The additional read-only review was explicitly requested and is now complete.",
                "NEXT_ACTION": "Human inspects the preserved worktree and review result",
                "WHY_NEXT_ACTION": "A manual review command does not merge, delete, or redispatch the task.",
                "HUMAN_ATTENTION_REQUIRED": False,
            }, new_state=previous, event="HUMAN_REVIEW_COMPLETED", detail=classification)
            if previous == "COMPLETED":
                try:
                    _cleanup_task_temp_runtime(task_id)
                except HarnessError as exc:
                    classification = "HUMAN_DECISION_REQUIRED"
                    update_task(task_id, {
                        "NEXT_ACTION": "Human inspects the preserved reviewer runtime and cleanup failure",
                        "WHY_NEXT_ACTION": str(exc),
                        "HUMAN_ATTENTION_REQUIRED": True,
                    })
    print(f"TASK_ID={task_id}\nREVIEW_STATUS={classification}\nHARNESS_STATE={load_state(task_id)['HARNESS_STATE']}")
    return 0 if classification in {"PASS", "PASS_WITH_WARNINGS"} else 2


def command_stop(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    worker_pid = state.get("WORKER_PID")
    worker_has_identity = isinstance(worker_pid, int) and worker_pid > 0
    worker_may_be_alive = worker_has_identity and _pid_alive(worker_pid) is not False
    if state["HARNESS_STATE"] in TERMINAL_STATES and not worker_may_be_alive:
        print(f"TASK_ID={task_id}\nHARNESS_STATE={state['HARNESS_STATE']}")
        return 0
    target = "STOPPING" if worker_may_be_alive or state.get("CONTROLLER_PID") else "STOPPED"
    updated = update_task(task_id, {
        "STOP_REQUESTED": True, "PAUSE_REQUESTED": False,
        "CURRENT_ACTION": "Safe stop requested; no new autonomous action will dispatch",
        "WHY_CURRENT_ACTION": "The active turn may reach a checkpoint; useful worktree changes are preserved.",
        "HUMAN_ATTENTION_REQUIRED": True,
    }, new_state=target, event="STOP_REQUESTED", detail=f"active_kind={state.get('ACTIVE_PROCESS_KIND')}")
    queued, detail = _queue_control(updated, "HARNESS CONTROL: Safe stop requested. Reach the nearest safe checkpoint, start no new actions, summarize partial work, and end without discarding changes.")
    update_task(task_id, event="STOP_SIGNAL", detail=f"queued={queued};{detail}")
    print(f"TASK_ID={task_id}\nHARNESS_STATE={target}\nCOOPERATIVE_SIGNAL_QUEUED={queued}\nWORKTREE_PRESERVED={state.get('WORKTREE', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Accept and run one bounded task")
    start.add_argument("--goal", required=True)
    start.add_argument("--task-id")
    start.add_argument("--task-kind", choices=TASK_KINDS, default="auto")
    start.add_argument("--task-scope", choices=_load_r1().TASK_SCOPES, default="independent-code")
    start.add_argument("--max-corrections", type=int, choices=range(0, 6), default=DEFAULT_MAX_CORRECTIONS)
    start.add_argument("--max-hours", type=_positive_hours)
    start.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    start.set_defaults(func=command_start)
    for name, func in (("status", command_status), ("inspect", command_inspect), ("pause", command_pause), ("stop", command_stop)):
        sub = commands.add_parser(name)
        sub.add_argument("--task-id")
        sub.set_defaults(func=func)
    timeline = commands.add_parser("timeline")
    timeline.add_argument("--task-id")
    timeline.add_argument("--limit", type=int, default=50)
    timeline.set_defaults(func=command_timeline)
    resume = commands.add_parser("resume")
    resume.add_argument("--task-id")
    resume.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    resume.set_defaults(func=command_resume)
    steer = commands.add_parser("steer")
    steer.add_argument("instruction")
    steer.add_argument("--task-id")
    steer.set_defaults(func=command_steer)
    review = commands.add_parser("review")
    review.add_argument("--task-id")
    review.set_defaults(func=command_review)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        raw = list(sys.argv[1:] if argv is None else argv)
        if raw[:1] == ["_run"]:
            internal = argparse.ArgumentParser(add_help=False)
            internal.add_argument("--task-id", required=True)
            internal.add_argument("--launch-token", default="")
            internal_args = internal.parse_args(raw[1:])
            return run_task(
                internal_args.task_id, launch_token=internal_args.launch_token,
            )
        if raw[:1] == ["_supervise"]:
            internal = argparse.ArgumentParser(add_help=False)
            internal.add_argument("--task-id", required=True)
            internal.add_argument("--launch-token", default="")
            internal_args = internal.parse_args(raw[1:])
            return run_supervisor(
                internal_args.task_id, launch_token=internal_args.launch_token,
            )
        args = build_parser().parse_args(raw)
        return int(args.func(args))
    except (HarnessError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"HARNESS_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
