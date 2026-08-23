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
    "PAUSING": {"PAUSED", "STOPPING", "FAILED"},
    "PAUSED": {"PLANNING", "RUNNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "REVIEWING": {"RUNNING", "PAUSING", "PAUSED", "WAITING_HUMAN", "BLOCKED", "STOPPING", "STOPPED", "COMPLETED", "FAILED"},
    "WAITING_HUMAN": {"PLANNING", "RUNNING", "REVIEWING", "BLOCKED", "STOPPING", "STOPPED", "FAILED"},
    "BLOCKED": {"PLANNING", "REVIEWING", "WAITING_HUMAN", "STOPPING", "STOPPED", "FAILED"},
    "STOPPING": {"STOPPED", "FAILED"},
    "STOPPED": {"REVIEWING"},
    "COMPLETED": {"REVIEWING"},
    "FAILED": {"REVIEWING"},
}
MAX_STATE_BYTES = 131_072
MAX_TIMELINE_BYTES = 262_144
MAX_LIST_ITEMS = 100
MAX_TEXT = 8_000
DEFAULT_MAX_CORRECTIONS = 2
CODEX_PHASE_COMMANDS = (
    ("TARGETED_TEST", re.compile(r"(?:pytest|unittest|test_[\w.-]+\.py)", re.I)),
    ("SELF_REVIEW", re.compile(r"git\s+(?:diff|status)", re.I)),
)
DEPENDENCY_FILES = {
    "requirements.txt", "requirements.lock.txt", "pyproject.toml", "poetry.lock",
    "pdm.lock", "uv.lock", "environment.yml", "environment.yaml",
}
DISCOVERY_ROOTS = ("scripts", "fast3", "tests", "config", "docs")
DISCOVERY_TEXT_SUFFIXES = {".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml"}


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


def _new_state(task_id: str, goal: str, scope: str, max_corrections: int) -> dict[str, Any]:
    plan = [
        {"phase": "R1_PREFLIGHT", "status": "PENDING", "action": "Run task-scoped R1 preflight", "why": "Research and Anti-Bloat gates precede autonomous mutation."},
        {"phase": "DISCOVER_EXISTING", "status": "PENDING", "action": "Search relevant repository surfaces", "why": "Reuse evidence is required before creating a component."},
        {"phase": "CREATE_ISOLATED_WORKTREE", "status": "PENDING", "action": "Create an external Git worktree", "why": "The dirty primary tree and concurrent work must remain isolated."},
        {"phase": "IMPLEMENT", "status": "PENDING", "action": "Dispatch one Codex worker turn", "why": "The worker receives the bounded human goal and hard repository contract."},
        {"phase": "TARGETED_TEST", "status": "PENDING", "action": "Verify targeted tests and R1 guards", "why": "Software correctness cannot bypass temporal or storage validity."},
        {"phase": "INDEPENDENT_REVIEW", "status": "PENDING", "action": "Review material changes read-only", "why": "Independent findings gate bounded correction or completion."},
        {"phase": "FINALIZE", "status": "PENDING", "action": "Preserve worktree and report", "why": "R2 never merges, deletes useful work, or starts another task."},
    ]
    return {
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
        "WORKER_STATUS": "NOT_STARTED",
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
        "TASK_SCOPE": scope,
        "PLAN": plan,
        "NEXT_ACTION_CODE": "R1_PREFLIGHT",
        "TESTS_RUN": [],
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
    }


def _plan_update(state: dict[str, Any], phase: str, status: str) -> None:
    for row in state["PLAN"]:
        if row["phase"] == phase:
            row["status"] = status
            break
    completed = sum(row["status"] == "COMPLETED" for row in state["PLAN"])
    state["PROGRESS_SUMMARY"] = f"{completed}/{len(state['PLAN'])} plan steps completed"


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


def _negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 35):start].lower()
    return bool(re.search(r"(?:do\s+not|don't|never|forbid|prevent|reject|must\s+not|no)\s*$", prefix))


def hard_guard_conflicts(instruction: str) -> list[str]:
    text = " ".join(instruction.split())
    conflicts: list[str] = []
    unsafe_2026 = re.compile(
        r"(?:use|using|against|on)\s+(?:the\s+)?(?:exposed\s+)?2026(?:\+)?[^.]{0,90}(?:train|fit|refit|tun|optim|select|threshold|winner)|"
        r"(?:train|fit|refit|tun|optim|select|threshold|winner)[^.]{0,90}(?:using|against|on)\s+(?:the\s+)?(?:exposed\s+)?2026(?:\+)?",
        re.I,
    )
    match = unsafe_2026.search(text)
    if match and not _negated(text, match.start()):
        conflicts.append("EXPOSED_2026_OPTIMIZATION")
    patterns = (
        ("FROZEN_ASSET_MUTATION", r"(?:modify|overwrite|delete|unfreeze)\s+(?:a\s+)?frozen"),
        ("CANONICAL_DATA_MUTATION", r"(?:modify|overwrite|delete|write\s+to)\s+(?:the\s+)?canonical\s+(?:market\s+)?data"),
        ("REPO_LOCAL_VENV", r"(?:create|install|build)\s+(?:a\s+)?(?:repo(?:sitory)?[- ]local\s+)?\.venv"),
        ("AUTO_MERGE_OR_PRODUCTION_PROMOTION", r"(?:auto(?:matically)?[- ]merge|promote\s+(?:it\s+)?to\s+production|authorize\s+production)"),
    )
    for code, pattern in patterns:
        found = re.search(pattern, text, re.I)
        if found and not _negated(text, found.start()):
            conflicts.append(code)
    return conflicts


def _has_real_frozen_dependency(goal: str) -> bool:
    """Treat prohibitions as constraints while keeping real frozen use conservative."""
    for clause in re.split(r"[.;\n]+", goal.lower()):
        if "frozen" not in clause:
            continue
        before_frozen = clause.split("frozen", 1)[0]
        if re.search(
            r"\b(?:do\s+not|don't|never|must\s+not|should\s+not|avoid|without|preserve|protect)\b",
            before_frozen,
        ):
            continue
        if re.search(
            r"\bfrozen\b.{0,80}\b(?:do\s+not|must\s+not|should\s+not|cannot|can't)\b"
            r".{0,40}\b(?:touch|modify|overwrite|delete)\b",
            clause,
        ):
            continue
        return True
    return False


def infer_scope(goal: str, requested: str) -> str:
    low = goal.lower()
    governance_words = re.search(r"prevent|forbid|guard|detect|reject|ensure|test|audit|protect", low)
    if hard_guard_conflicts(goal) or ("2026" in low and re.search(r"tun|optim|select|threshold|train|fit", low) and not governance_words):
        return "2026-optimization"
    if "2026" in low or "holdout" in low or "prospective" in low or "forward" in low:
        return "2026-evaluation"
    if "historical" in low and re.search(r"fetch|download|moomoo|quota", low):
        return "historical-fetch"
    if _has_real_frozen_dependency(goal):
        return "frozen-dependent"
    if re.search(r"research|model|feature|backtest|training|pit|leakage", low):
        return "pre2026-research"
    return requested


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
    return {
        "changed": sorted(set(changed))[:MAX_LIST_ITEMS],
        "created": sorted(set(created))[:MAX_LIST_ITEMS],
        "dependencies": dependency_lines[:MAX_LIST_ITEMS],
        "changed_count": len(set(changed)),
        "created_count": len(set(created)),
    }


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


def _codex_exec_command(worktree: Path, sandbox: str, review: bool) -> list[str]:
    command = [_codex_command(), "--ask-for-approval", "never", "exec"]
    if review:
        command.append("--ephemeral")
    command += ["--json", "--sandbox", sandbox, "--cd", str(worktree), "-"]
    return command


def _worker_prompt(state: dict[str, Any], correction: str = "") -> str:
    steer = "\n".join(f"- {row}" for row in state.get("PENDING_STEER", [])) or "- none"
    correction_text = f"\nCORRECTION CONTEXT:\n{correction[:4_000]}\n" if correction else ""
    return f"""You are the implementation worker for one bounded Harness R2 task.

GOAL (version {state['GOAL_VERSION']}):
{state['GOAL']}

Task scope: {state['TASK_SCOPE']}
Human steering currently in force:
{steer}
{correction_text}
Work only in this isolated Git worktree. Read AGENTS.md first and use repository maps and registries. The controller already ran R1 preflight. Search before create; classify relevant matches; reuse or extend authoritative/active code, reference but never modify frozen code. Do not use 2026+ outcomes for fitting, feature/parameter/threshold/portfolio-rule search, model selection, or winner selection. Preserve PIT ordering, canonical data, external evidence, unrelated work, and the repository-local .venv prohibition. Do not fetch Moomoo history, merge branches, promote to production, or start another task.

Implement the smallest suitable change, run focused tests, inspect your diff, and stop after this goal. A research hypothesis failing economically is a valid result; do not tune against exposed holdout feedback. If the goal cannot be completed safely, preserve useful work and report the blocker.

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

Inspect the diff and relevant repository evidence. Assess code correctness, test adequacy, PIT/leakage, exposed-2026-holdout optimization, train/validation/test roles, duplicate implementation, repository/artifact/dependency bloat, frozen assets, and goal alignment. Validation recorded by the controller: {state.get('VALIDATION_RESULTS', [])}. Guard states: overfit={state['OVERFIT_GUARD']}; anti_bloat={state['ANTI_BLOAT']}; reuse={state['REUSE_GUARD']}.

End with exactly one classification line and concise findings:
REVIEW_STATUS=PASS|PASS_WITH_WARNINGS|FIX_REQUIRED|HUMAN_DECISION_REQUIRED
"""


def _parse_marker(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    return match.group(1).strip()[:MAX_TEXT] if match else ""


def _phase_from_command(command: str) -> str | None:
    for phase, pattern in CODEX_PHASE_COMMANDS:
        if pattern.search(command):
            return phase
    return None


def _run_codex_turn(task_id: str, prompt: str, *, review: bool = False) -> dict[str, Any]:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    assert_registered_isolated_worktree(worktree)
    sandbox = "read-only" if review else "workspace-write"
    command = _codex_exec_command(worktree, sandbox, review)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command, cwd=str(worktree), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=flags,
        )
    except OSError as exc:
        raise HarnessError(f"CODEX_LAUNCH_FAILED:{type(exc).__name__}:{exc}") from exc
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()
    kind = "REVIEW" if review else "WORKER"
    update_task(task_id, {
        "WORKER_STATUS": "REVIEW_RUNNING" if review else "RUNNING",
        "WORKER_PID": process.pid,
        "ACTIVE_PROCESS_KIND": kind,
        "ACTIVE_THREAD_ID": "",
        "CURRENT_ACTION": f"Codex {kind.lower()} turn is active in the isolated worktree",
        "WHY_CURRENT_ACTION": "Read-only independence is required for review." if review else "The bounded worker may implement only the authorized goal after preflight and reuse discovery.",
    }, event=f"{kind}_STARTED", detail=f"pid={process.pid};sandbox={sandbox}")

    tail: deque[str] = deque(maxlen=20)
    final_message = ""
    tests: list[str] = []
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
            if phase and phase != seen_phase and not review:
                seen_phase = phase
                update_task(task_id, {
                    "CURRENT_PHASE": phase,
                    "CURRENT_ACTION": "Worker is running targeted tests" if phase == "TARGETED_TEST" else "Worker is inspecting its diff",
                    "WHY_CURRENT_ACTION": "Focused validation is required before review." if phase == "TARGETED_TEST" else "Self-review catches defects, leakage, duplication, and bloat before independent review.",
                }, event=f"WORKER_{phase}", detail="High-signal phase inferred from Codex event stream")
            if re.search(r"(?:pytest|unittest|test_[\w.-]+\.py)", command_text, re.I) and event.get("type") == "item.completed":
                tests.append(f"{command_text[:500]} | exit={item.get('exit_code', 'UNKNOWN')}")
        current = load_state(task_id)
        if current["PAUSE_REQUESTED"] or current["STOP_REQUESTED"]:
            # The control command queues a cooperative checkpoint message. Never kill a writer.
            continue
    exit_code = process.wait()
    if not final_message and tail:
        final_message = "\n".join(tail)[-MAX_TEXT:]
    update_task(task_id, {
        "WORKER_STATUS": f"EXITED_{exit_code}",
        "WORKER_PID": None,
        "ACTIVE_PROCESS_KIND": "",
        "ACTIVE_THREAD_ID": "",
        "WORKER_FINDINGS" if not review else "REVIEW_FINDINGS": final_message,
        "TESTS_RUN": (load_state(task_id).get("TESTS_RUN", []) + tests)[-MAX_LIST_ITEMS:],
    }, event=f"{kind}_COMPLETED", detail=f"exit={exit_code}")
    if exit_code and re.search(r"failed to initialize (?:in-process )?app-server|not logged in|authentication required|usage limit|rate limit", final_message, re.I):
        raise HarnessError(f"CODEX_INTERFACE_UNAVAILABLE:{final_message[-2_000:]}")
    return {"exit_code": exit_code, "message": final_message, "tests": tests}


def _refresh_changes(task_id: str) -> dict[str, Any]:
    state = load_state(task_id)
    changes = _git_changes(Path(state["WORKTREE"]))
    justification = _parse_marker(state.get("WORKER_FINDINGS", ""), "NEW_COMPONENT_JUSTIFICATION")
    reuse = "PASS_SEARCH_RECORDED"
    if changes["created"] and (not justification or justification.upper() == "NONE"):
        reuse = "HARD_BLOCKER_NEW_COMPONENT_JUSTIFICATION_MISSING"
    update_task(task_id, {
        "FILES_CHANGED": changes["changed"],
        "FILES_CREATED": changes["created"],
        "DEPENDENCIES_ADDED": changes["dependencies"],
        "NEW_COMPONENT_JUSTIFICATION": justification,
        "REUSE_GUARD": reuse,
    }, event="CHANGE_INVENTORY", detail=f"changed={changes['changed_count']};created={changes['created_count']};dependencies={len(changes['dependencies'])}")
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


def _validate_targeted(task_id: str) -> tuple[bool, str]:
    state = load_state(task_id)
    tests = state.get("TESTS_RUN", [])
    observed_fail = any(re.search(r"exit=(?!0\b)\S+", row) for row in tests)
    observed_pass = any(re.search(r"exit=0\b", row) for row in tests)
    if observed_fail:
        return False, "Worker-reported targeted test command failed."
    if observed_pass:
        return True, "Worker-reported targeted tests passed."
    worktree = Path(state["WORKTREE"])
    candidates = _candidate_tests(worktree, state.get("FILES_CHANGED", []))
    if not candidates:
        return True, "No paired automatic test mapping; independent review must assess worker validation."
    python = _storage_paths().python_exe
    result = _run([str(python), "-B", "-m", "pytest", "-q", *candidates], worktree, 300)
    summary = (result.stdout + "\n" + result.stderr).strip()[-4_000:]
    row = f"{' '.join(candidates)} | exit={result.returncode} | {summary}"
    update_task(task_id, {"TESTS_RUN": (tests + [row])[-MAX_LIST_ITEMS:]})
    return result.returncode == 0, summary or f"exit={result.returncode}"


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


def _run_preflight_for(task_id: str, repo: Path) -> dict[str, Any]:
    state = load_state(task_id)
    result = _load_r1().run_preflight(repo=repo, task_scope=state["TASK_SCOPE"])
    overfit, anti = _guard_summary(result)
    budget = next((row["detail"] for row in result["findings"] if row["code"] == "ANTI_BLOAT_BUDGET"), "")
    match = re.search(r"worktree_bytes=(\d+)", budget)
    bytes_value = int(match.group(1)) if match else None
    return {"result": result, "overfit": overfit, "anti": anti, "bytes": bytes_value}


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

    update_task(task_id, {
        "CURRENT_ACTION": "Execution blocked; state and useful work are preserved",
        "WHY_CURRENT_ACTION": detail[:MAX_TEXT],
        "NEXT_ACTION": "Human inspects blocker and explicitly resumes or stops",
        "WHY_NEXT_ACTION": "Fail-closed continuation prevents unsafe mutation or invalid research.",
        "HUMAN_ATTENTION_REQUIRED": True,
        "WORKER_STATUS": "BLOCKED",
    }, new_state="BLOCKED", event="HARD_BLOCKER", detail=f"{code}:{detail}", mutate=mutate)


def _wait_human(task_id: str, code: str, detail: str) -> None:
    def mutate(state: dict[str, Any]) -> None:
        state["BLOCKERS"] = (state.get("BLOCKERS", []) + [{"code": code, "detail": detail[:2_000]}])[-MAX_LIST_ITEMS:]

    update_task(task_id, {
        "CURRENT_ACTION": "Waiting for human decision",
        "WHY_CURRENT_ACTION": detail[:MAX_TEXT],
        "NEXT_ACTION": "Human steers, reviews, resumes, or stops",
        "WHY_NEXT_ACTION": "The bounded autonomous loop cannot safely choose beyond this point.",
        "HUMAN_ATTENTION_REQUIRED": True,
    }, new_state="WAITING_HUMAN", event="WAITING_HUMAN", detail=f"{code}:{detail}", mutate=mutate)


def _review_classification(message: str, exit_code: int) -> str:
    value = _parse_marker(message, "REVIEW_STATUS").upper()
    allowed = {"PASS", "PASS_WITH_WARNINGS", "FIX_REQUIRED", "HUMAN_DECISION_REQUIRED"}
    if exit_code != 0:
        return "HUMAN_DECISION_REQUIRED"
    return value if value in allowed else "HUMAN_DECISION_REQUIRED"


def _perform_review(task_id: str) -> str:
    state = load_state(task_id)
    worktree = Path(state["WORKTREE"])
    before = _repo_status_fingerprint(worktree)
    update_task(task_id, {
        "CURRENT_PHASE": "INDEPENDENT_REVIEW",
        "CURRENT_ACTION": "Launching a separate read-only Codex review",
        "WHY_CURRENT_ACTION": "The reviewer must assess correctness and all three R1 pillars without modifying code.",
    }, new_state="REVIEWING", event="REVIEW_STARTED", detail="sandbox=read-only;new ephemeral context")
    result = _run_codex_turn(task_id, _review_prompt(load_state(task_id)), review=True)
    after = _repo_status_fingerprint(worktree)
    if before != after:
        _block(task_id, "READ_ONLY_REVIEW_MUTATED_WORKTREE", f"before={before};after={after}")
        return "HUMAN_DECISION_REQUIRED"
    classification = _review_classification(result["message"], result["exit_code"])
    update_task(task_id, {
        "LAST_REVIEW_STATUS": classification,
        "REVIEW_REQUESTED": False,
        "LAST_COMPLETED": "INDEPENDENT_REVIEW_COMPLETED",
        "NEXT_ACTION_CODE": "FINALIZE" if classification in {"PASS", "PASS_WITH_WARNINGS"} else "WORKER",
    }, event="REVIEW_CLASSIFIED", detail=classification)
    return classification


def _worker_result(state: dict[str, Any], exit_code: int) -> str:
    if exit_code != 0:
        return "SOFTWARE_FAILURE"
    value = _parse_marker(state.get("WORKER_FINDINGS", ""), "TASK_RESULT").upper()
    allowed = {"COMPLETED", "SOFTWARE_FAILURE", "RESEARCH_FAILURE", "WAITING_HUMAN", "BLOCKED"}
    return value if value in allowed else "COMPLETED"


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
            result = _run_preflight_for(task_id, REPO)
            def complete_preflight(value: dict[str, Any]) -> None:
                _plan_update(value, "R1_PREFLIGHT", "COMPLETED")
            update_task(task_id, {
                "OVERFIT_GUARD": result["overfit"], "ANTI_BLOAT": result["anti"],
                "PRIMARY_REPO_BYTES_AT_START": result["bytes"], "LAST_COMPLETED": "R1_PREFLIGHT",
                "NEXT_ACTION": "Search existing implementations", "WHY_NEXT_ACTION": "Reuse evidence is mandatory before material implementation.",
                "NEXT_ACTION_CODE": "DISCOVER_EXISTING",
            }, event="R1_PREFLIGHT_COMPLETED", detail=result["result"]["preflight_status"], mutate=complete_preflight)
            if result["result"]["applicable_hard_blocker_count"]:
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
            isolated_preflight = _run_preflight_for(task_id, path)
            if isolated_preflight["result"]["applicable_hard_blocker_count"]:
                update_task(task_id, {"WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head})
                _block(task_id, "ISOLATED_WORKTREE_R1_HARD_BLOCKER", isolated_preflight["result"]["preflight_status"])
                return
            def complete_worktree(value: dict[str, Any]) -> None:
                _plan_update(value, "CREATE_ISOLATED_WORKTREE", "COMPLETED")
            update_task(task_id, {
                "WORKTREE": str(path), "BASE_BRANCH": branch, "BASE_HEAD": head,
                "OVERFIT_GUARD": isolated_preflight["overfit"], "ANTI_BLOAT": isolated_preflight["anti"],
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
                _wait_human(task_id, "CODEX_WORKER_INTERFACE_FAILURE", str(exc))
                return
            def complete_worker(value: dict[str, Any]) -> None:
                _plan_update(value, "IMPLEMENT", "COMPLETED")
            update_task(task_id, {
                "LAST_COMPLETED": "WORKER_TURN_COMPLETED", "NEXT_ACTION": "Run targeted validation and post-change guards",
                "WHY_NEXT_ACTION": "Worker output is not accepted without mechanical validation.",
                "NEXT_ACTION_CODE": "VALIDATE",
            }, mutate=complete_worker)
            if _control_checkpoint(task_id):
                return
            outcome = _worker_result(load_state(task_id), result["exit_code"])
            contamination = _parse_marker(load_state(task_id).get("WORKER_FINDINGS", ""), "HOLDOUT_CONTAMINATION_RISK")
            if contamination and contamination.upper() != "NONE":
                _wait_human(task_id, "HOLDOUT_CONTAMINATION_RISK", contamination)
                return
            if outcome in {"WAITING_HUMAN", "BLOCKED"}:
                _wait_human(task_id, f"WORKER_{outcome}", load_state(task_id).get("WORKER_FINDINGS", ""))
                return
            if outcome == "SOFTWARE_FAILURE":
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", f"attempts={state['CORRECTION_ATTEMPTS']}")
                    return
                update_task(task_id, {"CORRECTION_ATTEMPTS": state["CORRECTION_ATTEMPTS"] + 1, "NEXT_ACTION_CODE": "WORKER"}, event="SOFTWARE_CORRECTION_REQUESTED", detail="Worker reported software failure")
            elif outcome == "RESEARCH_FAILURE":
                update_task(task_id, {"NEXT_ACTION_CODE": "VALIDATE"}, event="RESEARCH_FAILURE_ACCEPTED", detail="No automatic parameter or model tuning will be dispatched")
        elif action == "VALIDATE":
            update_task(task_id, {
                "CURRENT_PHASE": "TARGETED_TEST", "CURRENT_ACTION": "Inventorying diff and running targeted validation",
                "WHY_CURRENT_ACTION": "Changed code, R1 guards, dependencies, and creation justification must be checked before review.",
            }, event="TARGETED_VALIDATION_STARTED", detail="No data fetch or retraining is launched by the controller")
            changes = _refresh_changes(task_id)
            if load_state(task_id)["REUSE_GUARD"].startswith("HARD_BLOCKER"):
                _wait_human(task_id, "NEW_COMPONENT_JUSTIFICATION_REQUIRED", ",".join(changes["created"]))
                return
            passed, validation = _validate_targeted(task_id)
            post = _run_preflight_for(task_id, Path(load_state(task_id)["WORKTREE"]))
            def complete_validation(value: dict[str, Any]) -> None:
                _plan_update(value, "TARGETED_TEST", "COMPLETED" if passed and not post["result"]["applicable_hard_blocker_count"] else "FAILED")
            update_task(task_id, {
                "OVERFIT_GUARD": post["overfit"], "ANTI_BLOAT": post["anti"],
                "REPO_BYTES_AFTER": post["bytes"],
                "REPO_SIZE_DELTA_BYTES": (post["bytes"] - state.get("REPO_BYTES_BEFORE")) if post["bytes"] is not None and state.get("REPO_BYTES_BEFORE") is not None else None,
                "VALIDATION_RESULTS": (load_state(task_id).get("VALIDATION_RESULTS", []) + [validation[:4_000], post["result"]["preflight_status"]])[-MAX_LIST_ITEMS:],
                "LAST_COMPLETED": "TARGETED_VALIDATION_COMPLETED", "NEXT_ACTION": "Run independent read-only review",
                "WHY_NEXT_ACTION": "Material changes require correctness, leakage, reuse, and bloat assessment.",
                "NEXT_ACTION_CODE": "REVIEW",
            }, event="TARGETED_VALIDATION_COMPLETED", detail=f"tests={'PASS' if passed else 'FAIL'};preflight={post['result']['preflight_status']}", mutate=complete_validation)
            if post["result"]["applicable_hard_blocker_count"]:
                _block(task_id, "POST_CHANGE_R1_HARD_BLOCKER", post["result"]["preflight_status"])
                return
            if not passed:
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", validation)
                    return
                update_task(task_id, {
                    "CORRECTION_ATTEMPTS": state["CORRECTION_ATTEMPTS"] + 1, "NEXT_ACTION_CODE": "WORKER",
                }, event="SOFTWARE_CORRECTION_REQUESTED", detail=validation[:1_000])
        elif action == "REVIEW":
            changes = _git_changes(Path(state["WORKTREE"]))
            if not changes["changed"] and state["TASK_SCOPE"] == "independent-code" and not state["REVIEW_REQUESTED"]:
                def skip_review(value: dict[str, Any]) -> None:
                    _plan_update(value, "INDEPENDENT_REVIEW", "COMPLETED")
                update_task(task_id, {
                    "LAST_REVIEW_STATUS": "NOT_WARRANTED_NO_CHANGES", "LAST_COMPLETED": "REVIEW_SKIPPED_NO_CHANGES",
                    "NEXT_ACTION_CODE": "FINALIZE",
                }, event="REVIEW_NOT_WARRANTED", detail="No worktree changes", mutate=skip_review)
                continue
            try:
                classification = _perform_review(task_id)
            except HarnessError as exc:
                _wait_human(task_id, "INDEPENDENT_REVIEW_INTERFACE_FAILURE", str(exc))
                return
            def complete_review(value: dict[str, Any]) -> None:
                _plan_update(value, "INDEPENDENT_REVIEW", "COMPLETED")
            update_task(task_id, mutate=complete_review)
            if _control_checkpoint(task_id):
                return
            if classification == "FIX_REQUIRED":
                state = load_state(task_id)
                if state["CORRECTION_ATTEMPTS"] >= state["MAX_CORRECTION_ATTEMPTS"]:
                    _wait_human(task_id, "BOUNDED_CORRECTION_LIMIT_REACHED", state.get("REVIEW_FINDINGS", ""))
                    return
                update_task(task_id, {
                    "CORRECTION_ATTEMPTS": state["CORRECTION_ATTEMPTS"] + 1, "NEXT_ACTION_CODE": "WORKER",
                }, new_state="RUNNING", event="REVIEW_CORRECTION_REQUESTED", detail=f"attempt={state['CORRECTION_ATTEMPTS'] + 1}")
            elif classification == "HUMAN_DECISION_REQUIRED":
                _wait_human(task_id, "REVIEW_HUMAN_DECISION_REQUIRED", load_state(task_id).get("REVIEW_FINDINGS", ""))
                return
        elif action == "FINALIZE":
            changes = _refresh_changes(task_id)
            def complete_all(value: dict[str, Any]) -> None:
                _plan_update(value, "FINALIZE", "COMPLETED")
            update_task(task_id, {
                "CURRENT_PHASE": "FINALIZE", "CURRENT_ACTION": "Task complete; isolated worktree preserved for human integration",
                "WHY_CURRENT_ACTION": "R2 stops after one goal and never auto-merges or deletes useful changes.",
                "LAST_COMPLETED": "AUTHORIZED_TASK_COMPLETED", "NEXT_ACTION": "Human reviews the diff and chooses whether to integrate",
                "WHY_NEXT_ACTION": "Integration into the primary tree requires explicit human action.",
                "NEXT_ACTION_CODE": "DONE", "HUMAN_ATTENTION_REQUIRED": False,
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
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], text=True, capture_output=True, check=False, timeout=10)
            return result.returncode == 0 and f'"{pid}"' in result.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def recover_if_interrupted(task_id: str) -> dict[str, Any]:
    state = load_state(task_id)
    if state["HARNESS_STATE"] not in ACTIVE_STATES:
        return state
    controller_alive = _pid_alive(state.get("CONTROLLER_PID"))
    worker_alive = _pid_alive(state.get("WORKER_PID"))
    if controller_alive or worker_alive:
        return state
    if not state.get("CONTROLLER_PID") and not state.get("WORKER_PID"):
        updated = datetime.fromisoformat(state["LAST_UPDATED_AT"])
        if (datetime.now(timezone.utc) - updated).total_seconds() < 10:
            return state
    worktree = Path(state["WORKTREE"]) if state.get("WORKTREE") else None
    changes = _git_changes(worktree) if worktree and worktree.is_dir() else {"changed": [], "created": [], "dependencies": []}
    return update_task(task_id, {
        "WORKER_STATUS": "INTERRUPTED_PROCESS_NOT_RUNNING", "WORKER_PID": None, "CONTROLLER_PID": None,
        "CURRENT_ACTION": "Recovered interrupted task state; no partial work was discarded",
        "WHY_CURRENT_ACTION": "Neither recorded controller nor worker PID is active; human review is required before redispatch.",
        "FILES_CHANGED": changes["changed"], "FILES_CREATED": changes["created"], "DEPENDENCIES_ADDED": changes["dependencies"],
        "HUMAN_ATTENTION_REQUIRED": True,
    }, new_state="WAITING_HUMAN", event="CRASH_RECOVERY", detail=f"resume_point={state.get('NEXT_ACTION_CODE')};changed={len(changes['changed'])}")


def run_task(task_id: str) -> int:
    update_task(task_id, {"CONTROLLER_PID": os.getpid()}, event="CONTROLLER_STARTED", detail=f"pid={os.getpid()}")
    try:
        _dispatch(task_id)
        return 0
    except Exception as exc:
        try:
            update_task(task_id, {
                "WORKER_STATUS": "CONTROLLER_FAILED", "CONTROLLER_PID": None,
                "CURRENT_ACTION": "Controller failed; state and worktree preserved",
                "WHY_CURRENT_ACTION": f"{type(exc).__name__}:{exc}"[:MAX_TEXT],
                "HUMAN_ATTENTION_REQUIRED": True,
            }, new_state="FAILED", event="CONTROLLER_FAILED", detail=f"{type(exc).__name__}:{exc}")
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
    scope = infer_scope(goal, args.task_scope)
    state = _new_state(task_id, goal, scope, args.max_corrections)
    task_dir(task_id).mkdir(parents=True, exist_ok=False)
    _write_state_unlocked(task_id, state)
    _append_event_unlocked(task_id, "TASK_ACCEPTED", f"scope={scope};goal_version=1")
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
        "WHY_CURRENT_ACTION", "LAST_COMPLETED", "NEXT_ACTION", "WHY_NEXT_ACTION", "OVERFIT_GUARD",
        "ANTI_BLOAT", "REUSE_GUARD", "WORKER_STATUS", "HUMAN_ATTENTION_REQUIRED", "LAST_UPDATED_AT",
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
        target = "WAITING_HUMAN" if classification in {"FIX_REQUIRED", "HUMAN_DECISION_REQUIRED"} else previous
        update_task(task_id, {"HUMAN_ATTENTION_REQUIRED": target == "WAITING_HUMAN"}, new_state=target, event="HUMAN_REVIEW_COMPLETED", detail=classification)
    print(f"TASK_ID={task_id}\nREVIEW_STATUS={classification}\nHARNESS_STATE={load_state(task_id)['HARNESS_STATE']}")
    return 0 if classification in {"PASS", "PASS_WITH_WARNINGS"} else 2


def command_stop(args: argparse.Namespace) -> int:
    task_id = _current_task_id(args.task_id)
    state = recover_if_interrupted(task_id)
    if state["HARNESS_STATE"] in TERMINAL_STATES:
        print(f"TASK_ID={task_id}\nHARNESS_STATE={state['HARNESS_STATE']}")
        return 0
    target = "STOPPING" if state.get("WORKER_PID") or state.get("CONTROLLER_PID") else "STOPPED"
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
