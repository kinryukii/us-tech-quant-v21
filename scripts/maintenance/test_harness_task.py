from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("harness_task.py")
SPEC = importlib.util.spec_from_file_location("harness_task", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_STATE_FIELDS = {
    "TASK_ID", "HARNESS_STATE", "GOAL", "GOAL_VERSION", "CURRENT_TASK",
    "CURRENT_PHASE", "CURRENT_ACTION", "WHY_CURRENT_ACTION", "PROGRESS_SUMMARY",
    "LAST_COMPLETED", "NEXT_ACTION", "WHY_NEXT_ACTION", "WORKTREE", "WORKER_STATUS",
    "OVERFIT_GUARD", "ANTI_BLOAT", "REUSE_GUARD", "FILES_CHANGED", "FILES_CREATED",
    "DEPENDENCIES_ADDED", "PAUSE_REQUESTED", "STOP_REQUESTED",
    "HUMAN_ATTENTION_REQUIRED", "LAST_REVIEW_STATUS", "LAST_UPDATED_AT",
}


@pytest.fixture
def isolated_roots(monkeypatch: pytest.MonkeyPatch):
    # The machine's global pytest temp parent is a known pre-existing ACL blocker.
    parent = (module._storage_paths().cache_root / "harness_r2_tests").resolve()
    root = (parent / f"case-{secrets.token_hex(6)}").resolve()
    assert root.parent == parent
    state = root / "daily" / "harness_r2"
    worktrees = root / "worktrees"
    root.mkdir(parents=True)
    monkeypatch.setenv("USTQ_HARNESS_STATE_ROOT", str(state))
    monkeypatch.setenv("USTQ_HARNESS_WORKTREE_ROOT", str(worktrees))
    try:
        yield state, worktrees
    finally:
        shutil.rmtree(root)


def create_state(task_id: str = "test-task", goal: str = "Improve one small code path") -> dict:
    state = module._new_state(task_id, goal, "independent-code", 2)
    module.task_dir(task_id).mkdir(parents=True)
    module._write_state_unlocked(task_id, state)
    module._append_event_unlocked(task_id, "TASK_ACCEPTED", "test")
    module._set_current_task(task_id)
    return state


def test_state_schema_atomic_persistence_and_compact_timeline(isolated_roots: tuple[Path, Path]) -> None:
    create_state()
    updated = module.update_task("test-task", {"CURRENT_ACTION": "atomic update"}, event="CHECKPOINT", detail="high signal")
    assert REQUIRED_STATE_FIELDS <= set(updated)
    assert json.loads(module.state_path("test-task").read_text(encoding="utf-8"))["CURRENT_ACTION"] == "atomic update"
    assert module.state_path("test-task").stat().st_size < module.MAX_STATE_BYTES
    assert module.timeline_path("test-task").stat().st_size < module.MAX_TIMELINE_BYTES
    assert not list(module.task_dir("test-task").glob("*.tmp"))


def test_state_transition_validation() -> None:
    assert module.transition_value("RUNNING", "PAUSING") == "PAUSING"
    with pytest.raises(module.HarnessError, match="INVALID_STATE_TRANSITION"):
        module.transition_value("COMPLETED", "RUNNING")


def test_discovery_falls_back_when_optional_rg_is_unavailable(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = isolated_roots[0].parent / "discovery-repo"
    script = repository / "scripts" / "reusable_temporal_guard.py"
    script.parent.mkdir(parents=True)
    script.write_text("def reusable_temporal_guard():\n    return 'existing'\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO", repository)
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "rg" else shutil.which(name))

    evidence = module._discover_existing("Reuse the temporal guard implementation")

    assert evidence["discovery_tool"] == "PYTHON_NATIVE_FALLBACK"
    assert "OPTIONAL_DISCOVERY_TOOL_UNAVAILABLE:rg" in evidence["warning_codes"]
    assert "scripts/reusable_temporal_guard.py" in evidence["filename_matches"]
    assert any("reusable_temporal_guard.py" in row for row in evidence["semantic_matches"])


def test_discovery_catches_file_not_found_if_resolved_rg_cannot_launch(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = isolated_roots[0].parent / "launch-failure-repo"
    script = repository / "scripts" / "existing_reuse_helper.py"
    script.parent.mkdir(parents=True)
    script.write_text("EXISTING_REUSE_HELPER = True\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPO", repository)
    monkeypatch.setattr(module.shutil, "which", lambda name: "missing-rg.exe" if name == "rg" else None)

    def missing_process(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(module, "_run", missing_process)
    evidence = module._discover_existing("Use the existing reuse helper")

    assert evidence["discovery_tool"] == "PYTHON_NATIVE_FALLBACK"
    assert "OPTIONAL_DISCOVERY_TOOL_FAILED:rg:FileNotFoundError" in evidence["warning_codes"]
    assert any("existing_reuse_helper.py" in row for row in evidence["filename_matches"])


def test_required_executable_absence_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(module.HarnessError, match="REAL_REQUIRED_EXECUTABLE_MISSING:git"):
        module._required_executable("git")


def test_negative_frozen_constraints_do_not_create_dependency_scope() -> None:
    goal = "Harness-only discovery fix; do not touch frozen outputs; do not modify frozen baselines; avoid canonical data."
    assert module.infer_scope(goal, "independent-code") == "independent-code"


def test_real_frozen_dependency_remains_conservative() -> None:
    goal = "Validate this change against the frozen baseline without modifying it."
    assert module.infer_scope(goal, "independent-code") == "frozen-dependent"


def test_pause_resume_and_stop_preserve_resume_point(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))
    assert module.command_pause(argparse.Namespace(task_id="test-task")) == 0
    paused = module.load_state("test-task")
    assert paused["HARNESS_STATE"] == "PAUSED" and paused["PAUSE_REQUESTED"] is True
    monkeypatch.setattr(module, "_spawn_controller", lambda task_id: 4242)
    assert module.command_resume(argparse.Namespace(task_id="test-task", foreground=False)) == 0
    resumed = module.load_state("test-task")
    assert resumed["HARNESS_STATE"] == "PLANNING"
    assert resumed["NEXT_ACTION_CODE"] == "R1_PREFLIGHT"
    assert resumed["PAUSE_REQUESTED"] is False
    assert module.command_stop(argparse.Namespace(task_id="test-task")) == 0
    assert module.load_state("test-task")["HARNESS_STATE"] == "STOPPED"


def test_steer_persists_and_increments_goal_revision(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    monkeypatch.setattr(module, "_queue_control", lambda state, message: (False, "retained"))
    args = argparse.Namespace(task_id="test-task", instruction="Extend the existing risk evaluator; create no model wrapper.")
    assert module.command_steer(args) == 0
    state = module.load_state("test-task")
    assert state["GOAL_VERSION"] == 2
    assert state["PENDING_STEER"] == [args.instruction]
    assert state["STEERING_HISTORY"][-1]["accepted"] is True


def test_steer_cannot_weaken_exposed_holdout_guard(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    monkeypatch.setattr(module, "_queue_control", lambda state, message: (True, "queued"))
    args = argparse.Namespace(task_id="test-task", instruction="Use 2026 to tune the threshold.")
    assert module.command_steer(args) == 2
    state = module.load_state("test-task")
    assert state["GOAL_VERSION"] == 1
    assert state["HARNESS_STATE"] == "WAITING_HUMAN"
    assert state["STEERING_HISTORY"][-1]["accepted"] is False
    assert "EXPOSED_2026_OPTIMIZATION" in state["STEERING_HISTORY"][-1]["reason"]
    assert module.hard_guard_conflicts("Do not use 2026 to tune the threshold.") == []


def test_worktree_isolation_rejects_primary_and_nested_paths(isolated_roots: tuple[Path, Path]) -> None:
    _, root = isolated_roots
    valid = root / "harness-task-test-task"
    module.assert_isolated_worktree_path(valid, module.REPO, root)
    with pytest.raises(module.HarnessError, match="DIRECT_CHILD"):
        module.assert_isolated_worktree_path(root / "nested" / "task", module.REPO, root)
    with pytest.raises(module.HarnessError, match="NOT_DIRECT_CHILD|NOT_ISOLATED"):
        module.assert_isolated_worktree_path(module.REPO, module.REPO, root)


def test_registered_worktree_check_is_fail_closed(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root = isolated_roots
    worktree = root / "harness-task-test-task"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(
        module, "_git",
        lambda args, cwd=module.REPO, timeout=30: subprocess.CompletedProcess(args, 0, str(worktree), ""),
    )
    module.assert_registered_isolated_worktree(worktree)
    monkeypatch.setattr(
        module, "_git",
        lambda args, cwd=module.REPO, timeout=30: subprocess.CompletedProcess(args, 0, str(module.REPO), ""),
    )
    with pytest.raises(module.HarnessError, match="TOPLEVEL_MISMATCH"):
        module.assert_registered_isolated_worktree(worktree)


def test_worktree_permission_diagnostic_distinguishes_nested_codex_from_host_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = "fatal: Unable to create '.git/refs/heads/task.lock': Permission denied"
    monkeypatch.setenv("CODEX_SESSION_ID", "nested-session")
    assert module._worktree_create_failure(detail).startswith(
        "WORKTREE_CREATE_FAILED:NESTED_CODEX_SANDBOX_PERMISSION_DENIED:"
    )

    monkeypatch.delenv("CODEX_SANDBOX_NETWORK_DISABLED", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert module._worktree_create_failure(detail).startswith(
        "WORKTREE_CREATE_FAILED:HOST_ACL_PERMISSION_DENIED:"
    )
    assert module._worktree_create_failure("fatal: invalid reference") == (
        "WORKTREE_CREATE_FAILED:fatal: invalid reference"
    )


def test_codex_exec_uses_stable_global_flag_order(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = isolated_roots[1] / "harness-task-test-task"
    monkeypatch.setattr(module, "_codex_command", lambda: "codex.cmd")
    command = module._codex_exec_command(worktree, "read-only", True)
    assert command[:4] == ["codex.cmd", "--ask-for-approval", "never", "exec"]
    assert command[4:6] == ["--ephemeral", "--json"]
    assert command[-1] == "-"


def test_software_correction_loop_is_bounded(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state.update({"HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(isolated_roots[1] / "harness-task-test-task")})
    module._write_state_unlocked("test-task", state)
    calls = {"count": 0}

    def fail_worker(task_id: str, prompt: str, review: bool = False) -> dict:
        calls["count"] += 1
        module.update_task(task_id, {"WORKER_FINDINGS": "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE"})
        return {"exit_code": 1, "message": "software failure", "tests": []}

    monkeypatch.setattr(module, "_run_codex_turn", fail_worker)
    module._dispatch("test-task")
    final = module.load_state("test-task")
    assert calls["count"] == 3  # initial turn plus the configured two corrections
    assert final["CORRECTION_ATTEMPTS"] == 2
    assert final["HARNESS_STATE"] == "WAITING_HUMAN"
    assert final["BLOCKERS"][-1]["code"] == "BOUNDED_CORRECTION_LIMIT_REACHED"


@pytest.mark.parametrize(
    ("text", "code", "expected"),
    [
        ("REVIEW_STATUS=PASS", 0, "PASS"),
        ("REVIEW_STATUS=PASS_WITH_WARNINGS", 0, "PASS_WITH_WARNINGS"),
        ("REVIEW_STATUS=FIX_REQUIRED", 0, "FIX_REQUIRED"),
        ("unstructured", 0, "HUMAN_DECISION_REQUIRED"),
        ("REVIEW_STATUS=PASS", 1, "HUMAN_DECISION_REQUIRED"),
    ],
)
def test_review_classification_is_fail_closed(text: str, code: int, expected: str) -> None:
    assert module._review_classification(text, code) == expected


def test_crash_recovery_preserves_changed_file_inventory(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree), "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998})
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {"changed": ["useful.py"], "created": ["useful.py"], "dependencies": []})
    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "WAITING_HUMAN"
    assert recovered["FILES_CHANGED"] == ["useful.py"]
    assert recovered["WORKER_STATUS"] == "INTERRUPTED_PROCESS_NOT_RUNNING"
