"""Bounded, worktree-isolated, human-controlled single-task Harness R2."""

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
import tomllib
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence


REPO = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
R1_PREFLIGHT = SCRIPT.with_name("harness_preflight.py")
POLICY = REPO / "configs/anti_bloat_policy.toml"
TERMINAL_STATES = {"STOPPED", "COMPLETED", "FAILED"}
ACTIVE_STATES = {"PLANNING", "RUNNING", "PAUSING", "REVIEWING", "STOPPING"}
STATES = {
    "IDLE", "PLANNING", "RUNNING", "PAUSING", "PAUSED", "REVIEWING",
    "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "FAILED",
}
ALLOWED_TRANSITIONS = {
    "IDLE": {"PLANNING", "BLOCKED"},
    "PLANNING": {"RUNNING", "PAUSING", "PAUSED", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "FAILED"},
    "RUNNING": {"PLANNING", "PAUSING", "PAUSED", "REVIEWING", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "FAILED"},
    "PAUSING": {"PAUSED", "WAITING_HUMAN", "STOPPING", "FAILED"},
    "PAUSED": {"PLANNING", "RUNNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "REVIEWING": {"RUNNING", "PAUSING", "PAUSED", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "FAILED"},
    "WAITING_HUMAN": {"PLANNING", "RUNNING", "REVIEWING", "BLOCKED", "STOPPING", "STOPPED", "FAILED"},
    "BLOCKED": {"PLANNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "STOPPING": {"WAITING_HUMAN", "STOPPED", "FAILED"},
    "STOPPED": {"REVIEWING"},
    "COMPLETED": {"REVIEWING"},
    "FAILED": {"REVIEWING", "STOPPING"},
}
MAX_STATE_BYTES = 131_072
MAX_TIMELINE_BYTES = 262_144
MAX_LIST_ITEMS = 100
MAX_TEXT = 8_000
DEFAULT_MAX_CORRECTIONS = 2
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
    task_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = [
        {"phase": "R1_PREFLIGHT", "status": "PENDING", "action": "Run task-scoped R1 preflight", "why": "Research and Anti-Bloat gates precede autonomous mutation."},
        {"phase": "DISCOVER_EXISTING", "status": "PENDING", "action": "Search relevant repository surfaces", "why": "Reuse evidence is required before creating a component."},
        {"phase": "CREATE_ISOLATED_WORKTREE", "status": "PENDING", "action": "Create an external Git worktree", "why": "The dirty primary tree and concurrent work must remain isolated."},
        {"phase": "IMPLEMENT", "status": "PENDING", "action": "Dispatch one Codex worker turn", "why": "The worker receives the bounded human goal and hard repository contract."},
        {"phase": "TARGETED_TEST", "status": "PENDING", "action": "Verify targeted tests and R1 guards", "why": "Software correctness cannot bypass temporal or storage validity."},
        {"phase": "INDEPENDENT_REVIEW", "status": "PENDING", "action": "Review material changes read-only", "why": "Independent findings gate bounded correction or completion."},
        {"phase": "FINALIZE", "status": "PENDING", "action": "Preserve worktree and report", "why": "R2 never merges, deletes useful work, or starts another task."},
    ]
    state = {
        "TASK_ID": task_id,
        "HARNESS_STATE": "PLANNING",
        "GOAL": goal,
        "GOAL_VERSION": 1,
        "CURRENT_TASK": goal.splitlines()[0][:240],
        "CURRENT_PHASE": "ACCEPT_TASK",
        "CURRENT_ACTION": "Task accepted; preparing R1 preflight",
        "WHY_CURRENT_ACTION": "A single human-authorized goal must pass hard guards before mutation.",
        "PROGRESS_SUMMARY": "0/7 plan steps completed",
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
        "NEXT_ACTION_CODE": "R1_PREFLIGHT",
        "TESTS_RUN": [],
        "TEST_HISTORY_START_INDEX": 0,
        "VALIDATION_RESULTS": [],
        "WORKER_FINDINGS": "",
        "REVIEW_FINDINGS": "",
        "BLOCKERS": [],
        "STEERING_HISTORY": [],
        "PENDING_STEER": [],
        "CORRECTION_ATTEMPTS": 0,
        "MAX_CORRECTION_ATTEMPTS": max_corrections,
        "WORKER_PID": None,
        "WORKER_THREAD_ID": "",
        "ACTIVE_THREAD_ID": "",
        "ACTIVE_PROCESS_KIND": "",
        "CONTROLLER_PID": None,
        "BASE_HEAD": "",
        "BASE_BRANCH": "",
        "REUSE_EVIDENCE": {},
        "NEW_COMPONENT_JUSTIFICATION": "",
        "REVIEW_REQUESTED": False,
        "REPO_BYTES_BEFORE": None,
        "REPO_BYTES_AFTER": None,
        "REPO_SIZE_DELTA_BYTES": None,
        "PRIMARY_REPO_BYTES_AT_START": None,
        "ANTI_BLOAT_BASELINE_RESIDUE": [],
        "ANTI_BLOAT_TASK_DELTA": "PENDING",
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
        if row["phase"] in {"IMPLEMENT", "TARGETED_TEST", "INDEPENDENT_REVIEW"}:
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


def _python_native_discovery(pattern: str) -> tuple[list[str], list[str], list[str]]:
    compiled = re.compile(pattern, re.I)
    names: list[str] = []
    semantic_rows: list[str] = []
    warnings: list[str] = []

    def record_warning(value: str) -> None:
        if len(warnings) < 20:
            warnings.append(value[:300])

    for root_name in DISCOVERY_ROOTS:
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


def _discover_existing(goal: str) -> dict[str, Any]:
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
            name_result = _run([rg, "--files", *DISCOVERY_ROOTS], REPO, 20)
            semantic = _run([
                rg, "-n", "-i", "-m", "1", "--glob", "!**/_backup*/**", "--glob", "!**/legacy/**",
                pattern, *DISCOVERY_ROOTS,
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
            names, semantic_rows, native_warnings = _python_native_discovery(pattern)
            warnings.extend(native_warnings)
    else:
        discovery_tool = "PYTHON_NATIVE_FALLBACK"
        warnings.append("OPTIONAL_DISCOVERY_TOOL_UNAVAILABLE:rg")
        names, semantic_rows, native_warnings = _python_native_discovery(pattern)
        warnings.extend(native_warnings)
    return {
        "tokens": tokens,
        "discovery_tool": discovery_tool,
        "warning_codes": warnings[:20],
        "filename_matches": names,
        "semantic_matches": semantic_rows,
        "match_count_capped": len(names) + len(semantic_rows),
        "classification": "SEARCH_RECORDED; worker must classify AUTHORITATIVE/ACTIVE/FROZEN/SUPERSEDED/EXPERIMENTAL/UNKNOWN",
    }


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
        _plan_update(value, "IMPLEMENT", "IN_PROGRESS")

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


def _worker_prompt(state: dict[str, Any], correction: str = "") -> str:
    steer = "\n".join(f"- {row}" for row in state.get("PENDING_STEER", [])) or "- none"
    correction_text = f"\nCORRECTION CONTEXT:\n{correction[:4_000]}\n" if correction else ""
    return f"""You are the implementation worker for one bounded Harness R2 task.

GOAL (version {state['GOAL_VERSION']}):
{state['GOAL']}

Task scope: {state['TASK_SCOPE']}
Structured task kind: {state['TASK_KIND']} ({state['TASK_KIND_SOURCE']})
Safety flags: {state['SAFETY_FLAGS']}
Human steering currently in force:
{steer}
{correction_text}
Work only in this isolated Git worktree. Use the inherited TEMP/TMP/TMPDIR and USTQ_CACHE_ROOT for disposable runtime files; do not create temp or cache residue in the worktree. Read AGENTS.md first and use repository maps and registries. The controller already ran R1 preflight. Search before create; classify relevant matches; reuse or extend authoritative/active code, reference but never modify frozen code. Do not use 2026+ outcomes for fitting, feature/parameter/threshold/portfolio-rule search, model selection, or winner selection. Preserve PIT ordering, canonical data, external evidence, unrelated work, and the repository-local .venv prohibition. Do not fetch Moomoo history, merge branches, promote to production, or start another task.

Implement the smallest suitable change, run focused tests, inspect your diff, and stop after this goal. Never claim a test passed when it did not; if pytest is blocked by a temporary-path PermissionError, preserve the exact WinError and pytest stack evidence for Controller classification. A research hypothesis failing economically is a valid result; do not tune against exposed holdout feedback. If the goal cannot be completed safely, preserve useful work and report the blocker.

End with these concise machine-readable lines:
TASK_RESULT=COMPLETED|SOFTWARE_FAILURE|RESEARCH_FAILURE|WAITING_HUMAN|BLOCKED
TESTS_RUN=<commands and outcomes, or NONE>
VALIDATION_STATUS=PASS|FAIL|NOT_RUN
REUSE_DECISION=<what was reused/extended>
NEW_COMPONENT_JUSTIFICATION=<why each new persistent implementation was necessary, or NONE>
HOLDOUT_CONTAMINATION_RISK=NONE|<concise risk>
"""


def _review_prompt(state: dict[str, Any]) -> str:
    return f"""Perform an independent READ-ONLY review of the uncommitted changes in this isolated worktree. Do not modify any file. Human goal: {state['GOAL']}

Inspect the diff and relevant repository evidence. Source remains read-only; use the inherited external temporary runtime for harmless test or Python inspection. Worker test status: {state.get('WORKER_TEST_STATUS')}; worker limitation: {state.get('WORKER_TEST_LIMITATION')}; Controller authoritative validation: {state.get('CONTROLLER_VALIDATION_STATUS')} with evidence {state.get('VALIDATION_RESULTS', [])}. If your own pytest execution encounters exactly {WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION}, rely on the Controller-owned test evidence for execution and continue the independent source, scope, safety, Anti-Bloat, and correctness review; do not treat that environment limitation alone as an implementation defect. Assess code correctness, test adequacy, PIT/leakage, exposed-2026-holdout optimization, train/validation/test roles, duplicate implementation, repository/artifact/dependency bloat, frozen assets, and goal alignment. Guard states: overfit={state['OVERFIT_GUARD']}; anti_bloat={state['ANTI_BLOAT']}; reuse={state['REUSE_GUARD']}.

End with exactly one classification line and concise findings:
REVIEW_STATUS=PASS|PASS_WITH_WARNINGS|FIX_REQUIRED|HUMAN_DECISION_REQUIRED
"""


def _parse_marker(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    return match.group(1).strip()[:MAX_TEXT] if match else ""


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


def _run_codex_turn(task_id: str, prompt: str, *, review: bool = False) -> dict[str, Any]:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    assert_registered_isolated_worktree(worktree)
    runtime = _ensure_task_temp_runtime(task_id)
    sandbox = "read-only" if review else "workspace-write"
    command = _codex_exec_command(worktree, sandbox, review, runtime)
    environment = _task_temp_environment(runtime)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
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
    kind = "REVIEW" if review else "WORKER"
    started_fields = {
        "WORKER_STATUS": "REVIEW_RUNNING" if review else "RUNNING",
        "WORKER_PID": process.pid,
        "ACTIVE_PROCESS_KIND": kind,
        "ACTIVE_THREAD_ID": "",
        "CURRENT_PHASE": "INDEPENDENT_REVIEW" if review else "IMPLEMENT",
        "CURRENT_ACTION": f"Codex {kind.lower()} turn is active in the isolated worktree",
        "WHY_CURRENT_ACTION": "Read-only independence is required for review." if review else "The bounded worker may implement only the authorized goal after preflight and reuse discovery.",
        "NEXT_ACTION": f"Complete the bounded Codex {kind.lower()} turn",
        "WHY_NEXT_ACTION": "The completed turn must be classified before another lifecycle action is dispatched.",
    }
    if not review:
        started_fields["TEST_HISTORY_START_INDEX"] = len(state.get("TESTS_RUN", []))
        started_fields["WORKER_TEST_STATUS"] = "NOT_RUN"
        started_fields["WORKER_TEST_LIMITATION"] = ""
        started_fields["WORKER_TEST_EVIDENCE"] = ""
        started_fields["CONTROLLER_VALIDATION_STATUS"] = "NOT_RUN"

    def mark_turn_active(value: dict[str, Any]) -> None:
        _plan_update(value, "INDEPENDENT_REVIEW" if review else "IMPLEMENT", "IN_PROGRESS")

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
            if not review:
                fields["WORKER_THREAD_ID"] = thread_id
            update_task(task_id, fields, event=f"{kind}_THREAD_READY", detail=thread_id)
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final_message = str(item.get("text", ""))[-MAX_TEXT:]
        if event.get("type") in {"error", "turn.failed"}:
            tail.append(json.dumps(event, ensure_ascii=False, default=str)[:2_000])
        if item.get("type") == "command_execution":
            command_text = str(item.get("command", ""))
            phase = _phase_from_command(command_text)
            if phase and phase != seen_phase and not review and event.get("type") == "item.completed":
                seen_phase = phase
                _record_worker_checkpoint(task_id, phase)
            if phase == "TARGETED_TEST" and event.get("type") == "item.completed":
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
    if not review:
        _refresh_changes(task_id, worker_findings=final_message)
    completed_fields = {
        "WORKER_STATUS": f"REVIEW_EXITED_{exit_code}" if review else f"EXITED_{exit_code}",
        "WORKER_PID": None,
        "ACTIVE_PROCESS_KIND": "",
        "ACTIVE_THREAD_ID": "",
        "TESTS_RUN": combined_tests,
        "CURRENT_PHASE": "INDEPENDENT_REVIEW" if review else "IMPLEMENT",
        "CURRENT_ACTION": f"Codex {kind.lower()} turn completed; its result awaits classification",
        "WHY_CURRENT_ACTION": "Process completion is recorded separately from acceptance of its findings.",
        "LAST_COMPLETED": f"{kind}_TURN_COMPLETED",
        "NEXT_ACTION": f"Classify the completed {kind.lower()} result",
        "WHY_NEXT_ACTION": "The controller must choose validation, correction, finalization, or human review from explicit result markers.",
    }
    if review:
        completed_fields["REVIEW_FINDINGS"] = final_message
    else:
        completed_fields["TEST_HISTORY_START_INDEX"] = max(0, len(combined_tests) - min(len(tests), MAX_LIST_ITEMS))
        completed_fields["WORKER_TEST_STATUS"] = worker_test_status
        completed_fields["WORKER_TEST_LIMITATION"] = worker_test_limitation
        completed_fields["WORKER_TEST_EVIDENCE"] = worker_test_evidence

    def mark_turn_completed(value: dict[str, Any]) -> None:
        if not review:
            _plan_update(value, "IMPLEMENT", "COMPLETED")

    update_task(
        task_id, completed_fields, event=f"{kind}_COMPLETED",
        detail=f"exit={exit_code};worker_test_status={worker_test_status if not review else 'REVIEW_NOT_CLASSIFIED'}",
        mutate=mark_turn_completed,
    )
    if exit_code and re.search(r"failed to initialize (?:in-process )?app-server|not logged in|authentication required|usage limit|rate limit", final_message, re.I):
        raise HarnessError(f"CODEX_INTERFACE_UNAVAILABLE:{final_message[-2_000:]}")
    return {"exit_code": exit_code, "message": final_message, "tests": tests}


def _refresh_changes(task_id: str, *, worker_findings: str | None = None) -> dict[str, Any]:
    state = load_state(task_id)
    changes = _git_changes(Path(state["WORKTREE"]))
    findings = state.get("WORKER_FINDINGS", "") if worker_findings is None else worker_findings
    justification = _parse_marker(findings, "NEW_COMPONENT_JUSTIFICATION")
    reuse = "PASS_SEARCH_RECORDED"
    if changes["created"] and (not justification or justification.upper() == "NONE"):
        reuse = "HARD_BLOCKER_NEW_COMPONENT_JUSTIFICATION_MISSING"
    fields = {
        "FILES_CHANGED": changes["changed"],
        "FILES_CREATED": changes["created"],
        "DEPENDENCIES_ADDED": changes["dependencies"],
        "NEW_COMPONENT_JUSTIFICATION": justification,
        "REUSE_GUARD": reuse,
        "WORKTREE_INVENTORY_STATUS": "KNOWN",
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


def _validate_targeted(task_id: str) -> tuple[bool, str]:
    state = load_state(task_id)
    tests = state.get("TESTS_RUN", [])
    worker_report = state.get("WORKER_TEST_STATUS") or _latest_worker_reported_test_status(state)
    worktree = Path(state["WORKTREE"])
    candidates = _candidate_tests(worktree, state.get("FILES_CHANGED", []))
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


def _block(task_id: str, code: str, detail: str) -> None:
    def mutate(state: dict[str, Any]) -> None:
        state["BLOCKERS"] = (state.get("BLOCKERS", []) + [{"code": code, "detail": detail[:2_000]}])[-MAX_LIST_ITEMS:]
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


def _wait_human(task_id: str, code: str, detail: str) -> None:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    if worktree and worktree.is_dir():
        _refresh_changes(task_id)

    def mutate(state: dict[str, Any]) -> None:
        state["BLOCKERS"] = (state.get("BLOCKERS", []) + [{"code": code, "detail": detail[:2_000]}])[-MAX_LIST_ITEMS:]
        _close_active_plan(state, "PENDING")

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
        _plan_update(value, "INDEPENDENT_REVIEW", "IN_PROGRESS")

    update_task(task_id, {
        "WORKER_STATUS": "REVIEW_STARTING",
        "CURRENT_PHASE": "INDEPENDENT_REVIEW",
        "CURRENT_ACTION": "Launching a separate read-only Codex review",
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
        next_code = "WORKER"
    else:
        next_action = "Wait for a human decision on the review findings"
        why_next = "The review could not safely authorize correction or completion autonomously."
        next_code = "WORKER"

    def mark_review_completed(value: dict[str, Any]) -> None:
        _plan_update(value, "INDEPENDENT_REVIEW", "COMPLETED")

    update_task(task_id, {
        "WORKER_STATUS": f"REVIEW_EXITED_{result['exit_code']}",
        "CURRENT_PHASE": "INDEPENDENT_REVIEW",
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


def _dispatch(task_id: str) -> None:
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
            if load_state(task_id)["REUSE_GUARD"].startswith("HARD_BLOCKER"):
                update_task(task_id, {"CONTROLLER_VALIDATION_STATUS": "FAIL"})
                _wait_human(task_id, "NEW_COMPONENT_JUSTIFICATION_REQUIRED", ",".join(changes["created"]))
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


def run_task(task_id: str) -> int:
    update_task(task_id, {"CONTROLLER_PID": os.getpid()}, event="CONTROLLER_STARTED", detail=f"pid={os.getpid()}")
    try:
        _dispatch(task_id)
        return 0
    except Exception as exc:
        try:
            _record_controller_failure(task_id, exc)
        except Exception:
            pass
        return 1
    finally:
        try:
            state = load_state(task_id)
            if state.get("CONTROLLER_PID") == os.getpid():
                update_task(task_id, {"CONTROLLER_PID": None})
        except Exception:
            pass


def _spawn_controller(task_id: str) -> int:
    python = _storage_paths().python_exe
    command = [str(python), "-B", str(SCRIPT), "_run", "--task-id", task_id]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command, cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags,
    )
    update_task(task_id, {"CONTROLLER_PID": process.pid}, event="CONTROLLER_DISPATCHED", detail=f"pid={process.pid}")
    return process.pid


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
    state = _new_state(task_id, goal, scope, args.max_corrections, contract)
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
    pid = _spawn_controller(task_id)
    print(f"TASK_ID={task_id}\nHARNESS_STATE=PLANNING\nCONTROLLER_PID={pid}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    keys = (
        "TASK_ID", "HARNESS_STATE", "GOAL", "CURRENT_TASK", "CURRENT_PHASE", "CURRENT_ACTION",
        "WHY_CURRENT_ACTION", "PROGRESS_SUMMARY", "LAST_COMPLETED", "NEXT_ACTION", "WHY_NEXT_ACTION", "OVERFIT_GUARD",
        "TASK_KIND", "TASK_KIND_SOURCE", "AUTO_SCOPE_SUGGESTION", "TASK_SCOPE", "SAFETY_FLAGS",
        "ANTI_BLOAT", "ANTI_BLOAT_TASK_DELTA", "REUSE_GUARD", "WORKER_STATUS",
        "TASK_TEMP_RUNTIME", "TASK_TEMP_RUNTIME_STATUS",
        "WORKER_TEST_STATUS", "WORKER_TEST_LIMITATION", "CONTROLLER_VALIDATION_STATUS",
        "HUMAN_ATTENTION_REQUIRED", "LAST_UPDATED_AT",
    )
    for key in keys:
        value = str(state.get(key)).replace("\r", "\\r").replace("\n", "\\n")
        print(f"{key}={value}")
    print(f"FILES_CHANGED_COUNT={len(state.get('FILES_CHANGED', []))}")
    print(f"FILES_CREATED_COUNT={len(state.get('FILES_CREATED', []))}")
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
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
    update_task(task_id, {
        "PAUSE_REQUESTED": False, "STOP_REQUESTED": False, "HUMAN_ATTENTION_REQUIRED": False,
        "NEXT_ACTION_CODE": next_code, "CURRENT_ACTION": "Resuming from authoritative task state",
        "WHY_CURRENT_ACTION": f"Continuation begins at {next_code}; prior work and timeline are preserved.",
    }, new_state="PLANNING" if next_code in {"R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_WORKTREE"} else "RUNNING", event="TASK_RESUMED", detail=f"resume_point={next_code}")
    pid = run_task(task_id) if args.foreground else _spawn_controller(task_id)
    print(f"TASK_ID={task_id}\nHARNESS_STATE={load_state(task_id)['HARNESS_STATE']}\nCONTROLLER={pid}")
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
            return run_task(internal.parse_args(raw[1:]).task_id)
        args = build_parser().parse_args(raw)
        return int(args.func(args))
    except (HarnessError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"HARNESS_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
