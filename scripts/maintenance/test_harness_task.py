from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("harness_task.py")
REPOSITORY_ROOT = MODULE_PATH.parents[2].resolve()
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
    with tempfile.TemporaryDirectory(prefix="us-tech-quant-harness-r2-") as directory:
        root = Path(directory).resolve()
        assert root != REPOSITORY_ROOT and REPOSITORY_ROOT not in root.parents
        repository = root / "primary-repository"
        repository.mkdir()
        state = root / "daily" / "harness_r2"
        worktrees = root / "worktrees"
        monkeypatch.setattr(module, "REPO", repository)
        monkeypatch.setenv("USTQ_HARNESS_STATE_ROOT", str(state))
        monkeypatch.setenv("USTQ_HARNESS_WORKTREE_ROOT", str(worktrees))
        yield state, worktrees


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


def test_harness_temp_roots_are_external_to_repository(isolated_roots: tuple[Path, Path]) -> None:
    for root in isolated_roots:
        resolved = root.resolve()
        assert resolved != REPOSITORY_ROOT
        assert REPOSITORY_ROOT not in resolved.parents


@pytest.mark.parametrize(
    "goal",
    [
        "Repair Harness status output; do not perform research.",
        "Maintenance only: do not train models or run backtests.",
        "Reject research tasks; model training is prohibited for this code fix.",
        "Research must not be performed; model training is out of scope.",
        "This maintenance change is not research and will not train models.",
        "Do not perform research, train models, or run backtests.",
        "Maintenance tasks must not be classified as research solely because those words appear.",
        "Models must not be trained and research must not be conducted.",
        "Do not perform modeling or backtesting.",
        "Harness maintenance only: do not use 2026 evaluation, perform research, or train models.",
        "Harness scope correction: pre2026-research is not required and must not influence inference.",
        "Harness maintenance documents labels such as pre2026-research and 2026-evaluation.",
    ],
)
def test_negative_research_constraints_do_not_create_research_scope(goal: str) -> None:
    assert module.infer_scope(goal, "independent-code") == "independent-code"


def test_harness_review_vocabulary_does_not_cross_contaminate_scope() -> None:
    goal = """Harness maintenance classifier correction.
Run the focused pytest suite and inspect the diff.
Add regression coverage for genuine 2026 evaluation and genuine frozen dependency.
The label pre2026-research is explanatory only; do not perform research or training.
"""
    assert module.infer_scope(goal, "independent-code") == "independent-code"


@pytest.mark.parametrize(
    "goal",
    [
        "Conduct research using data through 2025.",
        "Conduct pre-2026 research to train a model using data through 2025.",
        "Repair a loader that depends on model features and backtest outputs.",
        "Perform modeling and backtesting using data through 2025.",
    ],
)
def test_real_research_work_or_dependency_remains_conservative(goal: str) -> None:
    assert module.infer_scope(goal, "independent-code") == "pre2026-research"


def test_real_2026_evaluation_remains_conservative() -> None:
    assert module.infer_scope("Evaluate the frozen 2026 holdout without fitting.", "independent-code") == "2026-evaluation"


def test_unrelated_negation_does_not_hide_real_research_work() -> None:
    goal = "This is not a documentation task, and the requested work is to train a model."
    assert module.infer_scope(goal, "independent-code") == "pre2026-research"


def test_worker_checkpoint_keeps_status_observability_consistent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING",
        "WORKTREE": str(worktree),
        "LAST_COMPLETED": "CREATE_ISOLATED_WORKTREE",
        "NEXT_ACTION": "Launch bounded Codex worker",
        "WHY_NEXT_ACTION": "Preflight, reuse search, and isolation gates have passed.",
    })
    for phase in ("R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["scripts/maintenance/harness_task.py", "scripts/maintenance/test_harness_task.py"],
        "created": [],
        "dependencies": [],
        "changed_count": 2,
        "created_count": 0,
    })

    module._record_worker_checkpoint("test-task", "TARGETED_TEST")

    checkpoint = module.load_state("test-task")
    assert checkpoint["CURRENT_PHASE"] == "TARGETED_TEST"
    assert checkpoint["LAST_COMPLETED"] == "WORKER_TARGETED_TEST_CHECKPOINT"
    assert checkpoint["NEXT_ACTION"] == "Finish the worker turn and report its validation"
    assert "controller validation" in checkpoint["WHY_NEXT_ACTION"]
    assert checkpoint["PROGRESS_SUMMARY"] == "3/7 plan steps completed; IMPLEMENT in progress"
    assert len(checkpoint["FILES_CHANGED"]) == 2

    module._record_worker_checkpoint("test-task", "SELF_REVIEW")
    checkpoint = module.load_state("test-task")
    assert checkpoint["CURRENT_PHASE"] == "SELF_REVIEW"
    assert checkpoint["LAST_COMPLETED"] == "WORKER_SELF_REVIEW_CHECKPOINT"
    assert checkpoint["PROGRESS_SUMMARY"] == "3/7 plan steps completed; IMPLEMENT in progress"

    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))
    assert module.command_status(argparse.Namespace(task_id="test-task")) == 0
    output = capsys.readouterr().out
    assert "PROGRESS_SUMMARY=3/7 plan steps completed; IMPLEMENT in progress" in output
    assert "FILES_CHANGED_COUNT=2" in output
    assert "FILES_CREATED_COUNT=0" in output


@pytest.mark.parametrize(
    "command",
    [
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'harness_task|pytest|python|codex' }",
        "Get-Process -Name python,codex -ErrorAction SilentlyContinue | Select-Object Id,CommandLine",
        'rg -n "pytest|git diff|codex" scripts/maintenance',
        "Get-Content scripts/maintenance/test_harness_task.py | Select-String pytest",
        "powershell.exe -Command \"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'pytest|git diff' }\"",
        "git status --short",
    ],
)
def test_event_stream_inspection_and_search_commands_are_not_validation(command: str) -> None:
    assert module._phase_from_command(command) is None


@pytest.mark.parametrize(
    ("command", "phase"),
    [
        ("python -m pytest -q focused_test.py", "TARGETED_TEST"),
        (r"& 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider scripts\maintenance\test_harness_task.py", "TARGETED_TEST"),
        (r'''powershell.exe -Command "& 'D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe' -B -m pytest -q focused_test.py"''', "TARGETED_TEST"),
        ("pytest -q focused_test.py", "TARGETED_TEST"),
        ("python -m unittest tests.test_small", "TARGETED_TEST"),
        ("git diff --check", "SELF_REVIEW"),
    ],
)
def test_event_stream_real_validation_command_heads_are_classified(command: str, phase: str) -> None:
    assert module._phase_from_command(command) == phase


def test_worker_started_and_completed_checkpoints_are_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree)})
    for phase in ("R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    observed_started: list[dict] = []

    class FakeInput:
        def write(self, value: str) -> None:
            assert value

        def close(self) -> None:
            return None

    class FakeOutput:
        def __iter__(self):
            observed_started.append(module.load_state("test-task"))
            yield json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "TASK_RESULT=COMPLETED\nHOLDOUT_CONTAMINATION_RISK=NONE",
                },
            }) + "\n"

    class FakeProcess:
        pid = 4242
        stdin = FakeInput()
        stdout = FakeOutput()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(module, "assert_registered_isolated_worktree", lambda path: None)
    monkeypatch.setattr(module, "_codex_exec_command", lambda worktree, sandbox, review: ["codex"])
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = module._run_codex_turn("test-task", "bounded prompt")

    assert result["exit_code"] == 0
    started = observed_started[0]
    assert started["CURRENT_PHASE"] == "IMPLEMENT"
    assert "active" in started["CURRENT_ACTION"]
    assert started["NEXT_ACTION"] == "Complete the bounded Codex worker turn"
    assert started["PROGRESS_SUMMARY"] == "3/7 plan steps completed; IMPLEMENT in progress"
    assert started["WORKER_STATUS"] == "RUNNING"

    completed = module.load_state("test-task")
    assert completed["CURRENT_PHASE"] == "IMPLEMENT"
    assert "completed" in completed["CURRENT_ACTION"] and "active" not in completed["CURRENT_ACTION"]
    assert completed["LAST_COMPLETED"] == "WORKER_TURN_COMPLETED"
    assert completed["NEXT_ACTION"] == "Classify the completed worker result"
    assert completed["PROGRESS_SUMMARY"] == "4/7 plan steps completed"
    assert completed["WORKER_STATUS"] == "EXITED_0"
    assert completed["ACTIVE_PROCESS_KIND"] == ""


def test_validation_and_completion_checkpoints_are_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING",
        "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "VALIDATE",
        "REUSE_GUARD": "PASS_SEARCH_RECORDED",
        "WORKER_STATUS": "EXITED_0",
        "REPO_BYTES_BEFORE": 0,
    })
    for phase in ("R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE", "IMPLEMENT"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    snapshots: dict[str, dict] = {}
    real_update = module.update_task

    def capture_update(*args, **kwargs):
        updated = real_update(*args, **kwargs)
        event = kwargs.get("event")
        if event in {"TARGETED_VALIDATION_STARTED", "TARGETED_VALIDATION_COMPLETED", "TASK_COMPLETED"}:
            snapshots[event] = json.loads(json.dumps(updated))
        return updated

    empty_changes = {"changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0}
    monkeypatch.setattr(module, "update_task", capture_update)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: empty_changes)
    monkeypatch.setattr(module, "_validate_targeted", lambda task_id: (True, "38 passed"))
    monkeypatch.setattr(module, "_run_preflight_for", lambda task_id, repo: {
        "result": {"applicable_hard_blocker_count": 0, "preflight_status": "PASS"},
        "overfit": "PASS",
        "anti": "PASS",
        "bytes": 0,
    })
    monkeypatch.setattr(module, "_git_changes", lambda path: empty_changes)

    module._dispatch("test-task")

    started = snapshots["TARGETED_VALIDATION_STARTED"]
    assert started["CURRENT_PHASE"] == "TARGETED_TEST"
    assert started["PROGRESS_SUMMARY"] == "4/7 plan steps completed; TARGETED_TEST in progress"
    assert started["NEXT_ACTION"] == "Complete targeted tests and post-change guards"

    validated = snapshots["TARGETED_VALIDATION_COMPLETED"]
    assert validated["CURRENT_ACTION"] == "Targeted validation completed with PASS"
    assert validated["LAST_COMPLETED"] == "TARGETED_VALIDATION_COMPLETED"
    assert validated["NEXT_ACTION"] == "Run independent read-only review"
    assert validated["PROGRESS_SUMMARY"] == "5/7 plan steps completed"

    completed = snapshots["TASK_COMPLETED"]
    assert completed["HARNESS_STATE"] == "COMPLETED"
    assert completed["CURRENT_PHASE"] == "COMPLETED"
    assert completed["LAST_COMPLETED"] == "AUTHORIZED_TASK_COMPLETED"
    assert completed["NEXT_ACTION"] == "Human reviews the diff and chooses whether to integrate"
    assert completed["PROGRESS_SUMMARY"] == "7/7 plan steps completed"
    assert completed["WORKER_STATUS"] == "COMPLETED"


def test_correction_and_waiting_human_checkpoints_are_coherent(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state["HARNESS_STATE"] = "REVIEWING"
    for phase in (
        "R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE", "IMPLEMENT",
        "TARGETED_TEST", "INDEPENDENT_REVIEW",
    ):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)

    module._request_correction("test-task", "REVIEW", "fix the classifier")
    correction = module.load_state("test-task")
    assert correction["HARNESS_STATE"] == "RUNNING"
    assert correction["CURRENT_PHASE"] == "CORRECTION_REQUESTED"
    assert correction["LAST_COMPLETED"] == "REVIEW_CORRECTION_REQUESTED"
    assert correction["NEXT_ACTION"] == "Dispatch the bounded correction worker"
    assert correction["PROGRESS_SUMMARY"] == "3/7 plan steps completed"
    assert correction["WORKER_STATUS"] == "CORRECTION_PENDING"

    module.update_task(
        "test-task",
        mutate=lambda value: module._plan_update(value, "INDEPENDENT_REVIEW", "IN_PROGRESS"),
    )
    module._wait_human("test-task", "BOUNDED_CORRECTION_LIMIT_REACHED", "limit reached")
    waiting = module.load_state("test-task")
    assert waiting["HARNESS_STATE"] == "WAITING_HUMAN"
    assert waiting["CURRENT_PHASE"] == "WAITING_HUMAN"
    assert waiting["CURRENT_ACTION"] == "Waiting for human decision"
    assert waiting["LAST_COMPLETED"] == "REVIEW_CORRECTION_REQUESTED"
    assert waiting["NEXT_ACTION"] == "Human steers, reviews, resumes, or stops"
    assert waiting["PROGRESS_SUMMARY"] == "3/7 plan steps completed"
    assert waiting["WORKER_STATUS"] == "WAITING_HUMAN"


def test_independent_review_started_and_completed_checkpoints_are_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree), "WORKER_STATUS": "EXITED_0"})
    for phase in ("R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE", "IMPLEMENT", "TARGETED_TEST"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    observed_started: list[dict] = []
    fingerprint = {"entry_count": 2, "sha256": "abc"}
    monkeypatch.setattr(module, "_repo_status_fingerprint", lambda path: fingerprint)

    def complete_review(task_id: str, prompt: str, review: bool = False) -> dict:
        observed_started.append(module.load_state(task_id))
        return {"exit_code": 0, "message": "REVIEW_STATUS=PASS", "tests": []}

    monkeypatch.setattr(module, "_run_codex_turn", complete_review)
    assert module._perform_review("test-task") == "PASS"

    started = observed_started[0]
    assert started["HARNESS_STATE"] == "REVIEWING"
    assert started["CURRENT_PHASE"] == "INDEPENDENT_REVIEW"
    assert started["WORKER_STATUS"] == "REVIEW_STARTING"
    assert started["PROGRESS_SUMMARY"] == "5/7 plan steps completed; INDEPENDENT_REVIEW in progress"
    assert started["NEXT_ACTION"] == "Complete and classify the independent review"

    reviewed = module.load_state("test-task")
    assert reviewed["CURRENT_ACTION"] == "Independent review completed with PASS"
    assert reviewed["LAST_COMPLETED"] == "INDEPENDENT_REVIEW_COMPLETED"
    assert reviewed["NEXT_ACTION"] == "Finalize and preserve the reviewed worktree"
    assert reviewed["PROGRESS_SUMMARY"] == "6/7 plan steps completed"
    assert reviewed["WORKER_STATUS"] == "REVIEW_EXITED_0"


def test_controller_targeted_pytest_disables_cache_provider(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"WORKTREE": str(worktree), "FILES_CHANGED": ["scripts/maintenance/harness_task.py"]})
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_candidate_tests", lambda worktree, changed: ["focused_test.py"])
    monkeypatch.setattr(module, "_storage_paths", lambda: argparse.Namespace(python_exe=Path("python.exe")))
    observed: list[str] = []

    def successful_run(args, cwd=module.REPO, timeout=30):
        observed.extend(args)
        return subprocess.CompletedProcess(args, 0, "passed", "")

    monkeypatch.setattr(module, "_run", successful_run)
    assert module._validate_targeted("test-task")[0] is True
    assert observed[observed.index("-p"):observed.index("-p") + 2] == ["-p", "no:cacheprovider"]


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
    isolation_check = module.assert_isolated_worktree_path
    monkeypatch.setattr(
        module,
        "assert_isolated_worktree_path",
        lambda path: isolation_check(path, root.parent / "primary-repository", root),
    )
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
