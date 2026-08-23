from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("harness_task.py")
REPOSITORY_ROOT = MODULE_PATH.parents[2].resolve()
SPEC = importlib.util.spec_from_file_location("harness_task", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)

KNOWN_NESTED_PYTEST_TEMP_FAILURE = r"""
PermissionError: [WinError 5] Access is denied: 'D:\sandbox\pytest-of-user\pytest-0'
  File "site-packages\_pytest\tmpdir.py", line 156, in pytest_configure
  File "site-packages\_pytest\pathlib.py", line 240, in make_numbered_dir
cleanup_dead_symlinks(basetemp)
"""


REQUIRED_STATE_FIELDS = {
    "TASK_ID", "HARNESS_STATE", "GOAL", "GOAL_VERSION", "CURRENT_TASK",
    "CURRENT_PHASE", "CURRENT_ACTION", "WHY_CURRENT_ACTION", "PROGRESS_SUMMARY",
    "LAST_COMPLETED", "NEXT_ACTION", "WHY_NEXT_ACTION", "WORKTREE", "WORKER_STATUS",
    "OVERFIT_GUARD", "ANTI_BLOAT", "REUSE_GUARD", "FILES_CHANGED", "FILES_CREATED",
    "DEPENDENCIES_ADDED", "PAUSE_REQUESTED", "STOP_REQUESTED",
    "HUMAN_ATTENTION_REQUIRED", "LAST_REVIEW_STATUS", "LAST_UPDATED_AT",
    "TEST_HISTORY_START_INDEX", "ANTI_BLOAT_BASELINE_RESIDUE", "ANTI_BLOAT_TASK_DELTA",
    "TASK_KIND", "TASK_KIND_SOURCE", "AUTO_SCOPE_SUGGESTION", "SAFETY_FLAGS", "TASK_SCOPE",
    "TASK_TEMP_RUNTIME", "TASK_TEMP_RUNTIME_STATUS", "TASK_TEMP_RUNTIME_OWNED",
    "WORKER_TEST_STATUS", "WORKER_TEST_LIMITATION", "WORKER_TEST_EVIDENCE",
    "CONTROLLER_VALIDATION_STATUS", "WORKTREE_INVENTORY_STATUS",
}


@pytest.fixture
def isolated_roots(monkeypatch: pytest.MonkeyPatch):
    external_parent = Path(tempfile.gettempdir()).resolve()
    assert external_parent != REPOSITORY_ROOT and REPOSITORY_ROOT not in external_parent.parents
    with tempfile.TemporaryDirectory(prefix="us-tech-quant-harness-r2-") as directory:
        root = Path(directory).resolve()
        assert root.parent == external_parent
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


def test_git_changes_returns_real_inventory() -> None:
    inventory = module._git_changes(REPOSITORY_ROOT)

    assert isinstance(inventory, dict)
    assert {"changed", "created", "dependencies", "changed_count", "created_count"} <= set(inventory)
    assert isinstance(inventory["changed"], list)
    assert isinstance(inventory["created"], list)
    assert isinstance(inventory["dependencies"], list)
    assert inventory["changed_count"] >= len(inventory["changed"])
    assert inventory["created_count"] >= len(inventory["created"])


def test_negative_frozen_constraints_do_not_create_dependency_scope() -> None:
    goal = "Harness-only discovery fix; do not touch frozen outputs; do not modify frozen baselines; avoid canonical data."
    assert module.infer_scope(goal, "independent-code") == "independent-code"


def test_real_frozen_dependency_remains_conservative() -> None:
    goal = "Validate this change against the frozen baseline without modifying it."
    assert module.infer_scope(goal, "independent-code") == "frozen-dependent"


def test_harness_temp_roots_are_external_to_repository(isolated_roots: tuple[Path, Path]) -> None:
    state, worktrees = isolated_roots
    test_root = state.parents[1]
    controller_pytest_temp = (module.task_dir("test-task") / "pytest-temp").resolve()
    for owned_root in (test_root, state, worktrees, controller_pytest_temp):
        resolved = owned_root.resolve()
        for repository in (REPOSITORY_ROOT, module.REPO.resolve()):
            assert resolved != repository
            assert repository not in resolved.parents


def test_task_temp_runtime_is_external_task_specific_and_probe_passes(
    isolated_roots: tuple[Path, Path],
) -> None:
    create_state()
    runtime = module.task_temp_runtime("test-task")
    other = module.task_temp_runtime("other-task")

    assert runtime.parent == isolated_roots[1].resolve()
    assert runtime != other
    assert runtime.name == "harness-runtime-test-task"
    assert runtime != module.REPO.resolve() and module.REPO.resolve() not in runtime.parents

    prepared = module._ensure_task_temp_runtime("test-task")
    assert prepared == runtime
    assert (runtime / module.TASK_TEMP_OWNER_MARKER).is_file()
    assert not list(runtime.glob(".write-probe-*.tmp"))
    assert module.load_state("test-task")["TASK_TEMP_RUNTIME_STATUS"] == "READY"

    module._cleanup_task_temp_runtime("test-task")
    assert not runtime.exists()
    cleaned = module.load_state("test-task")
    assert cleaned["TASK_TEMP_RUNTIME"] == str(runtime)
    assert cleaned["TASK_TEMP_RUNTIME_STATUS"] == "CLEANED"


def test_worker_temp_environment_supports_real_tempfile_and_pytest_tmp_path(
    isolated_roots: tuple[Path, Path],
) -> None:
    create_state()
    runtime = module._ensure_task_temp_runtime("test-task")
    environment = module._task_temp_environment(runtime)

    for name in ("TEMP", "TMP", "TMPDIR"):
        assert Path(environment[name]).resolve() == runtime
    assert Path(environment["USTQ_CACHE_ROOT"]).resolve() == runtime / "cache"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTEST_ADDOPTS"] == "-p no:cacheprovider"

    python_probe = subprocess.run(
        [
            sys.executable, "-B", "-c",
            "import tempfile; from pathlib import Path; "
            "root=Path(tempfile.gettempdir()).resolve(); "
            "handle=tempfile.NamedTemporaryFile(delete=False); name=Path(handle.name); "
            "handle.write(b'ok'); handle.close(); print(root); name.unlink()",
        ],
        cwd=runtime, env=environment, text=True, capture_output=True, check=False, timeout=30,
    )
    assert python_probe.returncode == 0, python_probe.stderr
    assert Path(python_probe.stdout.strip()).resolve() == runtime

    probe_dir = runtime / "pytest-probe"
    probe_dir.mkdir()
    probe_test = probe_dir / "test_temp_runtime.py"
    probe_test.write_text(
        "import tempfile\nfrom pathlib import Path\n\n"
        "def test_external_tmp_path(tmp_path):\n"
        "    assert Path(tempfile.gettempdir()).resolve() == Path(__file__).parents[1].resolve()\n"
        "    (tmp_path / 'writable.txt').write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    pytest_probe = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-q",
            "--basetemp", str(runtime / "pytest-basetemp"), str(probe_test),
        ],
        cwd=runtime, env=environment, text=True, capture_output=True, check=False, timeout=60,
    )
    assert pytest_probe.returncode == 0, pytest_probe.stdout + pytest_probe.stderr
    assert not (runtime / ".pytest_cache").exists()
    assert not (module.REPO / ".pytest_cache").exists()
    assert not list(module.REPO.glob("pytest-cache-files-*"))

    module._cleanup_task_temp_runtime("test-task")
    assert not runtime.exists()


def test_normal_finalization_cleans_controller_owned_task_temp_runtime(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    runtime = module._ensure_task_temp_runtime("test-task")
    state = module.load_state("test-task")
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })

    module._dispatch("test-task")

    completed = module.load_state("test-task")
    assert completed["HARNESS_STATE"] == "COMPLETED"
    assert completed["TASK_TEMP_RUNTIME_STATUS"] == "CLEANED"
    assert completed["TASK_TEMP_RUNTIME_OWNED"] is False
    assert not runtime.exists()


def test_unwritable_task_temp_runtime_is_scoped_blocker_before_worker_launch(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree), "NEXT_ACTION_CODE": "WORKER"})
    module._write_state_unlocked("test-task", state)
    launched = {"value": False}
    real_probe = module._probe_temp_runtime

    def deny_probe(path: Path) -> None:
        raise PermissionError(f"write denied: {path}")

    monkeypatch.setattr(module, "assert_registered_isolated_worktree", lambda path: None)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_probe_temp_runtime", deny_probe)
    monkeypatch.setattr(
        module.subprocess, "Popen",
        lambda *args, **kwargs: launched.update(value=True),
    )
    module._dispatch("test-task")

    blocked = module.load_state("test-task")
    assert launched["value"] is False
    assert blocked["HARNESS_STATE"] == "WAITING_HUMAN"
    assert blocked["BLOCKERS"][-1]["code"] == "WORKER_TEMP_RUNTIME_UNAVAILABLE"
    assert blocked["TASK_TEMP_RUNTIME_STATUS"] == "UNAVAILABLE"
    assert "HOST_ACL_FAILURE" not in blocked["BLOCKERS"][-1]["detail"]

    monkeypatch.setattr(module, "_probe_temp_runtime", real_probe)
    module._cleanup_task_temp_runtime("test-task")


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("No model training.", "independent-code"),
        ("Do not perform quantitative research.", "independent-code"),
        ("Harness maintenance: inspect research outputs.", "independent-code"),
        ("Summarize existing research outputs without running research.", "independent-code"),
        ("Without using 2026 outcomes, train a model.", "pre2026-research"),
        ("Train a model and do not use 2026 outcomes.", "pre2026-research"),
        ("Run a pre-2026 backtest.", "pre2026-research"),
        ("Evaluate the frozen model on 2026 holdout.", "2026-evaluation"),
        ("pre2026-research is a label used by the Harness.", "independent-code"),
        ("Do not train a model; modify Harness status only.", "independent-code"),
        ("Harness maintenance: run a backtest on pre-2026 data.", "pre2026-research"),
    ],
)
def test_scope_inference_distinguishes_requested_actions_from_constraints(goal: str, expected: str) -> None:
    assert module.infer_scope(goal, "independent-code") == expected


@pytest.mark.parametrize(
    ("task_kind", "goal", "expected_kind", "expected_scope"),
    [
        ("pre2026-research", "Train a model on pre-2026 data.", "pre2026-research", "pre2026-research"),
        ("maintenance", "Set the 2026 evaluation status field.", "maintenance", "independent-code"),
        ("maintenance", "Inspect existing research outputs.", "maintenance", "independent-code"),
        ("maintenance", "Use 2026 holdout outcomes to tune the threshold.", "maintenance", "2026-optimization"),
        ("maintenance", "Audit PIT leakage in the model pipeline.", "maintenance", "pre2026-research"),
        ("auto", "Fix a research model.", "pre2026-research", "pre2026-research"),
        ("auto", "Audit PIT leakage.", "pre2026-research", "pre2026-research"),
        ("auto", "Harness maintenance: inspect research outputs.", "maintenance", "independent-code"),
        ("auto", "Set the 2026 evaluation status field.", "independent-code", "independent-code"),
    ],
)
def test_structured_task_contract_applies_a_promoting_safety_floor(
    task_kind: str, goal: str, expected_kind: str, expected_scope: str,
) -> None:
    contract = module._task_contract(goal, task_kind, "independent-code")
    assert contract["TASK_KIND"] == expected_kind
    assert contract["TASK_SCOPE"] == expected_scope


def test_explicit_task_kind_cannot_lower_requested_safety_scope() -> None:
    contract = module._task_contract(
        "Inspect a frozen evaluation contract.", "maintenance", "frozen-dependent",
    )
    assert contract["TASK_KIND"] == "maintenance"
    assert contract["TASK_SCOPE"] == "frozen-dependent"


def test_structured_task_contract_is_persisted(isolated_roots: tuple[Path, Path]) -> None:
    goal = "Train a model on pre-2026 data."
    contract = module._task_contract(goal, "pre2026-research", "independent-code")
    state = module._new_state("test-task", goal, contract["TASK_SCOPE"], 2, contract)
    module.task_dir("test-task").mkdir(parents=True)
    module._write_state_unlocked("test-task", state)
    stored = module.load_state("test-task")
    assert stored["TASK_KIND"] == "pre2026-research"
    assert stored["TASK_KIND_SOURCE"] == "EXPLICIT"
    assert stored["SAFETY_FLAGS"]["MODEL_TRAINING_OR_SELECTION"] is True
    assert stored["TASK_SCOPE"] == "pre2026-research"
    parsed = module.build_parser().parse_args([
        "start", "--goal", "Inspect existing research outputs.", "--task-kind", "maintenance",
    ])
    assert parsed.task_kind == "maintenance"


def test_exact_dogfood_goal_uses_structured_maintenance_kind() -> None:
    goal = (
        "R2 real-execution closeout dogfood. Correct two existing Harness R2 observability/classification "
        "defects using the existing harness_task.py implementation and focused tests. First, a Harness "
        "maintenance task whose constraints say 'do not perform research', 'do not train models', or similar "
        "negative/prohibitive language must not be classified as pre2026-research solely because those words "
        "appear; preserve conservative classification for tasks that genuinely perform or depend on research. "
        "Second, keep status observability internally consistent so CURRENT_PHASE, LAST_COMPLETED, NEXT_ACTION, "
        "WHY_NEXT_ACTION, progress, and file-change counts reflect meaningful lifecycle checkpoints instead of "
        "remaining stale after the worker has advanced. Keep the patch minimal: modify at most "
        "scripts/maintenance/harness_task.py and scripts/maintenance/test_harness_task.py, add no dependency, "
        "create no new persistent component, do not touch A2/FAST/13F/canonical data/frozen outputs, do not "
        "perform model training or quantitative research, preserve all overfit/anti-bloat/reuse guards, run "
        "focused tests, complete the real isolated worker lifecycle and independent read-only review, do not "
        "auto-merge into the primary working tree, and stop after this single task."
    )
    contract = module._task_contract(goal, "maintenance", "independent-code")
    assert contract["TASK_KIND"] == "maintenance"
    assert contract["TASK_KIND_SOURCE"] == "EXPLICIT"
    assert contract["TASK_SCOPE"] == "independent-code"


def test_real_research_dependency_remains_conservative() -> None:
    goal = "Repair a loader that depends on model features and backtest outputs."
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


def test_known_nested_windows_pytest_temp_failure_is_environment_limited() -> None:
    results = [{
        "command": "python -m pytest -q --basetemp D:\\sandbox\\pytest-base focused_test.py",
        "exit_code": 1,
        "output": KNOWN_NESTED_PYTEST_TEMP_FAILURE,
    }]

    status, limitation, evidence = module._classify_worker_test_execution(results, "", 0)

    assert module._known_windows_codex_pytest_temp_limitation(evidence) is True
    assert status == "ENVIRONMENT_LIMITED"
    assert limitation == module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION
    assert module._classify_worker_test_execution(results, "", 1)[0] == "REAL_TEST_FAILURE"


def test_worker_pytest_assertion_failure_is_real_test_failure() -> None:
    results = [{
        "command": "python -m pytest -q focused_test.py",
        "exit_code": 1,
        "output": "FAILED focused_test.py::test_value - AssertionError: assert 1 == 2",
    }]

    status, limitation, _ = module._classify_worker_test_execution(results, "", 0)

    assert status == "REAL_TEST_FAILURE"
    assert limitation == ""


def test_generic_winerror5_is_not_treated_as_pytest_temp_limitation() -> None:
    evidence = "PermissionError: [WinError 5] Access is denied: D:\\protected\\application.log"
    results = [{"command": "python tool.py", "exit_code": 1, "output": evidence}]

    status, limitation, _ = module._classify_worker_test_execution(results, "", 0)

    assert module._known_windows_codex_pytest_temp_limitation(evidence) is False
    assert status == "REAL_TEST_FAILURE"
    assert limitation == ""


def test_latest_same_test_command_wins_within_current_attempt(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state["TESTS_RUN"] = [
        "python -m pytest -q focused_test.py | exit=1",
        "PYTHON   -m pytest -q focused_test.py | exit=0",
    ]
    state["TEST_HISTORY_START_INDEX"] = 0
    module._write_state_unlocked("test-task", state)

    assert module._latest_worker_reported_test_status(module.load_state("test-task")) == "PASS"


def test_worker_attempt_boundary_and_final_exit_inventory_are_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING",
        "WORKTREE": str(worktree),
        "TESTS_RUN": ["python -m pytest -q focused_test.py | exit=1"],
    })
    for phase in ("R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    observed_started: list[dict] = []
    final_edit = {"made": False}

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
                    "type": "command_execution",
                    "command": "python -m pytest -q focused_test.py",
                    "exit_code": 0,
                },
            }) + "\n"
            final_edit["made"] = True
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
    observed_popen: dict = {}

    def fake_popen(*args, **kwargs):
        observed_popen.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(
        module, "_codex_exec_command",
        lambda worktree, sandbox, review, writable_runtime=None: ["codex"],
    )
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["final_edit.py"] if final_edit["made"] else [],
        "created": [],
        "dependencies": [],
        "changed_count": int(final_edit["made"]),
        "created_count": 0,
    })

    result = module._run_codex_turn("test-task", "bounded prompt")

    assert result["exit_code"] == 0
    runtime = module.task_temp_runtime("test-task")
    for name in ("TEMP", "TMP", "TMPDIR"):
        assert Path(observed_popen["env"][name]).resolve() == runtime
    assert Path(observed_popen["env"]["USTQ_CACHE_ROOT"]).resolve() == runtime / "cache"
    started = observed_started[0]
    assert started["CURRENT_PHASE"] == "IMPLEMENT"
    assert "active" in started["CURRENT_ACTION"]
    assert started["NEXT_ACTION"] == "Complete the bounded Codex worker turn"
    assert started["PROGRESS_SUMMARY"] == "3/7 plan steps completed; IMPLEMENT in progress"
    assert started["WORKER_STATUS"] == "RUNNING"
    assert started["TEST_HISTORY_START_INDEX"] == 1

    completed = module.load_state("test-task")
    assert completed["CURRENT_PHASE"] == "IMPLEMENT"
    assert "completed" in completed["CURRENT_ACTION"] and "active" not in completed["CURRENT_ACTION"]
    assert completed["LAST_COMPLETED"] == "WORKER_TURN_COMPLETED"
    assert completed["NEXT_ACTION"] == "Classify the completed worker result"
    assert completed["PROGRESS_SUMMARY"] == "4/7 plan steps completed"
    assert completed["WORKER_STATUS"] == "EXITED_0"
    assert completed["ACTIVE_PROCESS_KIND"] == ""
    assert completed["FILES_CHANGED"] == ["final_edit.py"]
    assert completed["TESTS_RUN"][0].endswith("exit=1")
    assert completed["TESTS_RUN"][1].endswith("exit=0")
    assert completed["WORKER_TEST_STATUS"] == "PASS"
    validation_passed, validation_detail = module._validate_targeted("test-task")
    assert validation_passed is True
    assert "not authoritative" in validation_detail


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
        "anti_delta": "PASS",
        "bytes": 0,
        "task_blocker_count": 0,
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
    assert validated["CONTROLLER_VALIDATION_STATUS"] == "PASS"

    completed = snapshots["TASK_COMPLETED"]
    assert completed["HARNESS_STATE"] == "COMPLETED"
    assert completed["CURRENT_PHASE"] == "COMPLETED"
    assert completed["LAST_COMPLETED"] == "AUTHORIZED_TASK_COMPLETED"
    assert completed["NEXT_ACTION"] == "Human reviews the diff and chooses whether to integrate"
    assert completed["PROGRESS_SUMMARY"] == "7/7 plan steps completed"
    assert completed["WORKER_STATUS"] == "COMPLETED"


def test_correction_and_waiting_human_checkpoints_are_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "REVIEWING", "WORKTREE": str(worktree)})
    for phase in (
        "R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE", "IMPLEMENT",
        "TARGETED_TEST", "INDEPENDENT_REVIEW",
    ):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["waiting.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })

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
    assert waiting["WHY_CURRENT_ACTION"] == "limit reached"
    assert waiting["LAST_COMPLETED"] == "REVIEW_CORRECTION_REQUESTED"
    assert waiting["NEXT_ACTION"] == "Human steers, reviews, resumes, or stops"
    assert "cannot safely choose" in waiting["WHY_NEXT_ACTION"]
    assert waiting["PROGRESS_SUMMARY"] == "3/7 plan steps completed"
    assert waiting["WORKER_STATUS"] == "WAITING_HUMAN"
    assert waiting["HUMAN_ATTENTION_REQUIRED"] is True
    assert waiting["FILES_CHANGED"] == ["waiting.py"]


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
    inventory = {
        "changed": ["reviewed.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    }
    monkeypatch.setattr(module, "_repo_status_fingerprint", lambda path: fingerprint)
    monkeypatch.setattr(module, "_git_changes", lambda path: inventory)

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
    assert started["FILES_CHANGED"] == ["reviewed.py"]

    reviewed = module.load_state("test-task")
    assert reviewed["CURRENT_ACTION"] == "Independent review completed with PASS"
    assert reviewed["LAST_COMPLETED"] == "INDEPENDENT_REVIEW_COMPLETED"
    assert reviewed["NEXT_ACTION"] == "Finalize and preserve the reviewed worktree"
    assert reviewed["PROGRESS_SUMMARY"] == "6/7 plan steps completed"
    assert reviewed["WORKER_STATUS"] == "REVIEW_EXITED_0"
    assert "active" not in reviewed["CURRENT_ACTION"].lower()
    assert reviewed["FILES_CHANGED"] == ["reviewed.py"]


def test_controller_targeted_pytest_disables_cache_provider(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "WORKTREE": str(worktree),
        "FILES_CHANGED": ["scripts/maintenance/harness_task.py"],
        "WORKER_TEST_STATUS": "PASS",
        "TESTS_RUN": ["python -m pytest -q focused_test.py | exit=0"],
        "TEST_HISTORY_START_INDEX": 0,
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_candidate_tests", lambda worktree, changed: ["focused_test.py"])
    monkeypatch.setattr(module, "_storage_paths", lambda: argparse.Namespace(python_exe=Path("python.exe")))
    observed: list[str] = []

    def successful_run(args, cwd=module.REPO, timeout=30):
        observed.extend(args)
        return subprocess.CompletedProcess(args, 0, "passed", "")

    monkeypatch.setattr(module, "_run", successful_run)
    passed, detail = module._validate_targeted("test-task")
    assert passed is True
    assert detail.startswith("Controller-owned focused pytest:")
    assert observed[observed.index("-p"):observed.index("-p") + 2] == ["-p", "no:cacheprovider"]
    base_temp = Path(observed[observed.index("--basetemp") + 1]).resolve()
    assert base_temp == (module.task_dir("test-task") / "pytest-temp").resolve()
    assert module.REPO != base_temp and module.REPO not in base_temp.parents


def test_anti_bloat_status_distinguishes_pre_existing_residue_from_task_delta(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    module._write_state_unlocked("test-task", state)
    residue_detail = {"value": "pytest-cache-files-known"}

    class FakeR1:
        @staticmethod
        def run_preflight(repo: Path, task_scope: str) -> dict:
            return {
                "task_scope": task_scope,
                "applicable_hard_blocker_count": 1,
                "preflight_status": "HARD_BLOCKER",
                "findings": [
                    {
                        "level": "HARD_BLOCKER",
                        "code": "ANTI_BLOAT_ACCOUNTING_INCOMPLETE",
                        "detail": residue_detail["value"],
                        "blocks": ("all",),
                    },
                    {
                        "level": "PASS",
                        "code": "ANTI_BLOAT_BUDGET",
                        "detail": "worktree_bytes=100;preferred=PASS;local_venv=False",
                        "blocks": (),
                    },
                ],
            }

    monkeypatch.setattr(module, "_load_r1", lambda: FakeR1)
    scoped = module._run_preflight_for("test-task", isolated_roots[1], baseline_checkpoint=True)
    assert scoped["result"]["applicable_hard_blocker_count"] == 1
    assert scoped["result"]["preflight_status"] == "HARD_BLOCKER"
    assert scoped["result"]["findings"][0]["code"] == "ANTI_BLOAT_ACCOUNTING_INCOMPLETE"
    assert scoped["task_blocker_count"] == 0
    assert scoped["anti"] == "PRE_EXISTING_ACCOUNTING_RESIDUE"
    assert scoped["anti_delta"] == "PASS"
    assert scoped["accounting_residue"] == ["pytest-cache-files-known"]

    state = module.load_state("test-task")
    state["ANTI_BLOAT_BASELINE_RESIDUE"] = scoped["accounting_residue"]
    module._write_state_unlocked("test-task", state)
    residue_detail["value"] += ",pytest-cache-files-new"
    caused = module._run_preflight_for("test-task", isolated_roots[1])
    assert caused["task_blocker_count"] == 1
    assert caused["anti"] == "HARD_BLOCKER_NEW_TASK_CAUSED_BLOAT"
    assert caused["anti_delta"] == "FAIL_NEW_TASK_CAUSED_BLOAT"


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
    assert module.hard_guard_conflicts('The instruction is "use 2026 outcomes to tune the threshold".') == [
        "EXPOSED_2026_OPTIMIZATION"
    ]


def test_task_kind_does_not_gate_raw_goal_safety_detection() -> None:
    goal = "Harness maintenance. Use 2026 outcomes to tune the threshold."
    assert module.infer_scope(goal, "independent-code") == "2026-evaluation"
    assert module.hard_guard_conflicts(goal) == ["EXPOSED_2026_OPTIMIZATION"]
    contract = module._task_contract(goal, "maintenance", "independent-code")
    assert contract["TASK_KIND"] == "maintenance"
    assert contract["TASK_SCOPE"] == "2026-optimization"
    assert contract["SAFETY_FLAGS"]["EXPOSED_2026_OR_HOLDOUT_OPTIMIZATION"] is True


def test_hard_guard_targets_unsafe_feedback_not_benign_2026_text() -> None:
    assert module.hard_guard_conflicts("Train a model on pre-2026 data.") == []
    assert module.hard_guard_conflicts("Use outcomes dated before 2026 to train a model.") == []
    assert module.hard_guard_conflicts("Set the 2026 evaluation status field.") == []
    assert module.hard_guard_conflicts("Evaluate the frozen model on the 2026 holdout.") == []
    assert module.hard_guard_conflicts(
        "Evaluate on 2026 data and train the model on pre-2026 data."
    ) == []
    evaluation = module._task_contract(
        "Evaluate the frozen model on the 2026 holdout.", "maintenance", "independent-code",
    )
    assert evaluation["TASK_SCOPE"] == "2026-evaluation"


@pytest.mark.parametrize(
    "goal",
    [
        "Train a model on 2026 data.",
        "Use 2026 data to fit a model.",
        "Use 2026 outcomes to train a model.",
        "Fit the model based on 2026 holdout performance.",
        "Refit using 2026 evaluation results.",
        "Use 2026 outcomes to tune the threshold.",
        'The instruction is "use 2026 outcomes to train a model".',
    ],
)
def test_hard_guard_detects_unsafe_2026_feedback_actions(goal: str) -> None:
    assert module.hard_guard_conflicts(goal) == ["EXPOSED_2026_OPTIMIZATION"]


def test_hard_guard_allows_explicitly_negated_2026_training_and_tuning() -> None:
    assert module.hard_guard_conflicts("Do not use 2026 outcomes to train or tune the model.") == []


def test_ambiguous_real_training_request_fails_closed() -> None:
    assert module.hard_guard_conflicts("Train a model.") == ["AMBIGUOUS_TRAINING_TEMPORAL_SCOPE"]


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
    runtime = module.task_temp_runtime("test-task")
    monkeypatch.setattr(module, "_codex_command", lambda: "codex.cmd")
    reviewer = module._codex_exec_command(worktree, "read-only", True, runtime)
    worker = module._codex_exec_command(worktree, "workspace-write", False, runtime)
    assert reviewer[:4] == ["codex.cmd", "--ask-for-approval", "never", "exec"]
    assert reviewer[4:6] == ["--ephemeral", "--json"]
    assert reviewer[reviewer.index("--sandbox") + 1] == "read-only"
    assert worker[worker.index("--sandbox") + 1] == "workspace-write"
    assert "--ephemeral" not in worker
    for command in (reviewer, worker):
        assert command[command.index("--cd") + 1] == str(worktree)
        assert command[command.index("--add-dir") + 1] == str(runtime)
        assert command[-1] == "-"


@pytest.mark.parametrize("controller_passes", [True, False])
def test_environment_limited_worker_delegates_to_authoritative_controller_validation(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
    controller_passes: bool,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree),
        "OVERFIT_GUARD": "PASS", "ANTI_BLOAT": "PASS", "REUSE_GUARD": "PASS_SEARCH_RECORDED",
        "REPO_BYTES_BEFORE": 0,
    })
    module._write_state_unlocked("test-task", state)
    empty_changes = {
        "changed": ["scripts/maintenance/harness_task.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    }
    review_seen: list[dict] = []

    def environment_limited_worker(task_id: str, prompt: str, review: bool = False) -> dict:
        module.update_task(task_id, {
            "WORKER_FINDINGS": "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE",
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_TEST_EVIDENCE": KNOWN_NESTED_PYTEST_TEMP_FAILURE,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": "environment limited", "tests": ["pytest | exit=1"]}

    def controller_validation(task_id: str) -> tuple[bool, str]:
        if not controller_passes:
            module.update_task(task_id, {"STOP_REQUESTED": True})
        return controller_passes, "controller tests passed" if controller_passes else "controller assertion failed"

    def review(task_id: str) -> str:
        review_seen.append(module.load_state(task_id))
        return "HUMAN_DECISION_REQUIRED"

    monkeypatch.setattr(module, "_run_codex_turn", environment_limited_worker)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: empty_changes)
    monkeypatch.setattr(module, "_validate_targeted", controller_validation)
    monkeypatch.setattr(module, "_perform_review", review)
    monkeypatch.setattr(module, "_run_preflight_for", lambda task_id, repo: {
        "result": {"applicable_hard_blocker_count": 0, "preflight_status": "PASS"},
        "overfit": "PASS", "anti": "PASS", "anti_delta": "PASS",
        "bytes": 0, "task_blocker_count": 0,
    })

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["WORKER_TEST_STATUS"] == "ENVIRONMENT_LIMITED"
    assert final["WORKER_TEST_LIMITATION"] == module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION
    if controller_passes:
        assert review_seen and review_seen[0]["CONTROLLER_VALIDATION_STATUS"] == "PASS"
        assert final["CORRECTION_ATTEMPTS"] == 0
        events = [json.loads(row)["event"] for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()]
        assert "WORKER_TEST_ENVIRONMENT_LIMITATION_DELEGATED" in events
    else:
        assert not review_seen
        assert final["CONTROLLER_VALIDATION_STATUS"] == "FAIL"
        assert final["CORRECTION_ATTEMPTS"] == 1


def test_environment_limited_delegation_requires_known_inventory_and_passed_guards(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
        "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
        "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
        "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
        "WORKTREE_INVENTORY_STATUS": "KNOWN",
        "OVERFIT_GUARD": "PASS", "ANTI_BLOAT": "PASS", "REUSE_GUARD": "PASS_SEARCH_RECORDED",
    })

    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is True
    state["OVERFIT_GUARD"] = "HARD_BLOCKER"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False
    state["OVERFIT_GUARD"] = "PASS"
    state["WORKTREE_INVENTORY_STATUS"] = "UNKNOWN"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False


def test_real_worker_test_failure_uses_correction_path(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree)})
    module._write_state_unlocked("test-task", state)

    def failed_worker(task_id: str, prompt: str, review: bool = False) -> dict:
        module.update_task(task_id, {
            "WORKER_FINDINGS": "TASK_RESULT=COMPLETED\nHOLDOUT_CONTAMINATION_RISK=NONE",
            "WORKER_TEST_STATUS": "REAL_TEST_FAILURE",
            "WORKER_TEST_EVIDENCE": "AssertionError: assert 1 == 2",
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": "assertion failed", "tests": ["pytest | exit=1"]}

    controller_called = {"value": False}
    real_request_correction = module._request_correction

    def request_then_stop(task_id: str, source: str, detail: str) -> None:
        real_request_correction(task_id, source, detail)
        module.update_task(task_id, {"STOP_REQUESTED": True})

    monkeypatch.setattr(module, "_run_codex_turn", failed_worker)
    monkeypatch.setattr(module, "_request_correction", request_then_stop)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(
        module, "_validate_targeted",
        lambda task_id: (controller_called.update(value=True) or True, "unexpected"),
    )

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert controller_called["value"] is False
    assert final["CORRECTION_ATTEMPTS"] == 1
    assert final["CONTROLLER_VALIDATION_STATUS"] == "NOT_RUN"


def test_live_or_orphan_worker_prevents_environment_limited_delegation(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree),
        "OVERFIT_GUARD": "PASS", "ANTI_BLOAT": "PASS", "REUSE_GUARD": "PASS_SEARCH_RECORDED",
    })
    module._write_state_unlocked("test-task", state)

    def orphaned_result(task_id: str, prompt: str, review: bool = False) -> dict:
        module.update_task(task_id, {
            "WORKER_FINDINGS": "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE",
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": 4242,
            "ACTIVE_THREAD_ID": "thread-live", "ACTIVE_PROCESS_KIND": "WORKER",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": "environment limited", "tests": ["pytest | exit=1"]}

    controller_called = {"value": False}
    monkeypatch.setattr(module, "_run_codex_turn", orphaned_result)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(
        module, "_validate_targeted",
        lambda task_id: (controller_called.update(value=True) or True, "unexpected"),
    )

    module._dispatch("test-task")

    waiting = module.load_state("test-task")
    assert controller_called["value"] is False
    assert waiting["HARNESS_STATE"] == "WAITING_HUMAN"
    assert waiting["WORKER_PID"] == 4242
    assert waiting["BLOCKERS"][-1]["code"] == "WORKER_TEST_ENVIRONMENT_DELEGATION_UNSAFE"
    assert waiting["CORRECTION_ATTEMPTS"] == 0


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
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998,
        "CURRENT_PHASE": "TARGETED_TEST", "CURRENT_ACTION": "Running targeted tests",
        "LAST_COMPLETED": "IMPLEMENTATION_WORKER_EXITED", "NEXT_ACTION": "Review the test result",
    })
    module._plan_update(state, "TARGETED_TEST", "IN_PROGRESS")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {"changed": ["useful.py"], "created": ["useful.py"], "dependencies": []})
    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "WAITING_HUMAN"
    assert recovered["CURRENT_PHASE"] == "WAITING_HUMAN"
    assert "Recovered interrupted" in recovered["CURRENT_ACTION"]
    assert "Neither recorded controller nor worker PID is active" in recovered["WHY_CURRENT_ACTION"]
    assert recovered["LAST_COMPLETED"] == "IMPLEMENTATION_WORKER_EXITED"
    assert recovered["NEXT_ACTION"].startswith("Human inspects")
    assert "cannot safely continue" in recovered["WHY_NEXT_ACTION"]
    assert "TARGETED_TEST in progress" not in recovered["PROGRESS_SUMMARY"]
    assert recovered["FILES_CHANGED"] == ["useful.py"]
    assert recovered["WORKER_STATUS"] == "INTERRUPTED_PROCESS_NOT_RUNNING"
    assert recovered["HUMAN_ATTENTION_REQUIRED"] is True


def test_interruption_preserves_task_temp_runtime_identity(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    runtime = module._ensure_task_temp_runtime("test-task")
    state = module.load_state("test-task")
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998,
        "CURRENT_PHASE": "IMPLEMENT", "CURRENT_ACTION": "Worker is active",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })

    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "WAITING_HUMAN"
    assert recovered["TASK_ID"] == "test-task"
    assert Path(recovered["TASK_TEMP_RUNTIME"]).resolve() == runtime
    assert recovered["TASK_TEMP_RUNTIME_STATUS"] == "READY"
    assert recovered["TASK_TEMP_RUNTIME_OWNED"] is True
    assert runtime.is_dir()

    module._cleanup_task_temp_runtime("test-task")
    assert not runtime.exists()


def test_controller_failure_with_dead_worker_is_terminal_and_coherent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "CURRENT_PHASE": "TARGETED_TEST", "CURRENT_ACTION": "Running targeted tests",
        "LAST_COMPLETED": "IMPLEMENTATION_WORKER_EXITED", "NEXT_ACTION": "Review the test result",
    })
    module._plan_update(state, "TARGETED_TEST", "IN_PROGRESS")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_dispatch", lambda task_id: (_ for _ in ()).throw(RuntimeError("controller lost")))
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["preserved.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })

    assert module.run_task("test-task") == 1
    failed = module.load_state("test-task")
    assert failed["HARNESS_STATE"] == "FAILED"
    assert failed["CURRENT_PHASE"] == "FAILED"
    assert failed["CURRENT_ACTION"] == "Controller failed; state and worktree preserved"
    assert failed["WHY_CURRENT_ACTION"] == "RuntimeError:controller lost"
    assert failed["LAST_COMPLETED"] == "IMPLEMENTATION_WORKER_EXITED"
    assert failed["NEXT_ACTION"].startswith("Human inspects")
    assert "confirmed inactive" in failed["WHY_NEXT_ACTION"]
    assert "TARGETED_TEST in progress" not in failed["PROGRESS_SUMMARY"]
    assert failed["WORKER_STATUS"] == "CONTROLLER_FAILED"
    assert failed["FILES_CHANGED"] == ["preserved.py"]
    assert failed["HUMAN_ATTENTION_REQUIRED"] is True


def test_controller_failure_preserves_live_worker_and_stop_remains_effective(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "WORKER_PID": 4242, "WORKER_STATUS": "RUNNING",
        "ACTIVE_THREAD_ID": "thread-live", "ACTIVE_PROCESS_KIND": "WORKER",
        "CURRENT_PHASE": "IMPLEMENT", "CURRENT_ACTION": "Worker is active",
    })
    module._plan_update(state, "IMPLEMENT", "IN_PROGRESS")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_dispatch", lambda task_id: (_ for _ in ()).throw(RuntimeError("controller lost")))
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["preserved.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })

    assert module.run_task("test-task") == 1
    orphaned = module.load_state("test-task")
    assert orphaned["HARNESS_STATE"] == "WAITING_HUMAN"
    assert orphaned["CURRENT_PHASE"] == "WAITING_HUMAN"
    assert orphaned["WORKER_STATUS"] == "INTERRUPTED_CONTROLLER_WORKER_ALIVE"
    assert orphaned["WORKER_PID"] == 4242
    assert orphaned["ACTIVE_THREAD_ID"] == "thread-live"
    assert orphaned["ACTIVE_PROCESS_KIND"] == "WORKER"
    assert orphaned["HUMAN_ATTENTION_REQUIRED"] is True
    assert "stops or recovers the orphaned worker" in orphaned["NEXT_ACTION"]
    assert "IMPLEMENT in progress" not in orphaned["PROGRESS_SUMMARY"]

    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module, "_queue_control",
        lambda current, message: (queued.append((current["ACTIVE_THREAD_ID"], message)) or True, "queued"),
    )
    assert module.command_stop(argparse.Namespace(task_id="test-task")) == 0
    stopping = module.load_state("test-task")
    assert stopping["HARNESS_STATE"] == "STOPPING"
    assert stopping["STOP_REQUESTED"] is True
    assert stopping["WORKER_PID"] == 4242
    assert queued and queued[0][0] == "thread-live"

    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    stopped = module.recover_if_interrupted("test-task")
    assert stopped["HARNESS_STATE"] == "STOPPED"
    assert stopped["WORKER_PID"] is None
    assert stopped["WORKER_STATUS"] == "STOPPED_PROCESS_NOT_RUNNING"
