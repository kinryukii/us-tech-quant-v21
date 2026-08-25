from __future__ import annotations

import argparse
import hashlib
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
    "JUSTIFIED_CREATED_PATHS", "UNJUSTIFIED_CREATED_PATHS",
    "HARNESS_VERSION", "WORK_UNITS", "ACTIVE_WORK_UNIT_ID", "ACTIVE_WORK_UNIT_IDS",
    "CURRENT_WORK_UNIT", "ACTIVE_BLOCKERS", "LOCAL_BLOCKED_WORK", "RESOLVED_FINDINGS",
    "HISTORICAL_FINDINGS", "RETRY_LEDGER", "REUSE_DISCOVERY_CACHE", "TELEMETRY",
    "TASK_STARTED_AT", "TIME_BUDGET_HOURS", "DEADLINE_AT",
    "LAST_MEANINGFUL_PROGRESS_AT", "LAST_CHECKPOINT", "SUPERVISOR_PID",
    "CONTROLLER_PID", "CONTROLLER_LAUNCH_PID", "CONTROLLER_LAUNCH_TOKEN",
    "CONTROLLER_PARENT_PID", "CONTROLLER_STARTED_AT", "CONTROLLER_READY_AT",
    "CONTROLLER_HEARTBEAT_AT", "CONTROLLER_STARTUP_STATUS", "CONTROLLER_EXIT_CODE",
    "CONTROLLER_EXCEPTION", "CONTROLLER_STDERR_TAIL", "CONTROLLER_BOOTSTRAP_LOG",
    "CONTROLLER_STARTUP_RETRY_SIGNATURE", "CONTROLLER_STARTUP_RETRY_COUNT",
    "SUPERVISOR_LAUNCH_PID", "SUPERVISOR_LAUNCH_TOKEN",
    "SUPERVISOR_PARENT_PID", "SUPERVISOR_STARTED_AT", "SUPERVISOR_READY_AT",
    "SUPERVISOR_HEARTBEAT_AT", "SUPERVISOR_EXIT_CODE", "SUPERVISOR_EXCEPTION",
    "SUPERVISOR_STDERR_TAIL", "SUPERVISOR_STARTUP_STATUS", "SUPERVISOR_BOOTSTRAP_LOG",
    "SUPERVISOR_TRANSIENT_STATE_WRITE_FAILURES", "SUPERVISOR_LAST_TRANSIENT_EXCEPTION",
    "LAST_REVIEW_PROGRESS_HASH", "LAST_REVIEW_FINDING_IDENTITY", "REVIEW_FINDING_LEDGER",
    "REVIEW_CORRECTION_DISPOSITION", "CONVERGENCE_MODE", "CONVERGENCE_STARTED_AT",
    "HARD_DEADLINE_REACHED_AT", "POST_DEADLINE_MACHINE_GRACE_SECONDS",
    "STATE_STORAGE_STATUS", "STATE_STORAGE_FAILURE", "STATE_BYTES_LAST_WRITE",
    "STATE_TEXT_ARCHIVES", "COMPACTED_HISTORY_IDENTITIES",
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


def use_r2_compat_state(state: dict) -> dict:
    """Exercise persisted R2 dispatch semantics without changing R3 defaults."""
    state["HARNESS_VERSION"] = 2
    state["PLAN"] = [
        {"phase": phase, "status": "PENDING", "action": phase, "why": "legacy compatibility"}
        for phase in (
            "R1_PREFLIGHT", "DISCOVER_EXISTING", "CREATE_ISOLATED_WORKTREE",
            "IMPLEMENT", "TARGETED_TEST", "INDEPENDENT_REVIEW", "FINALIZE",
        )
    ]
    module._sync_plan_progress(state)
    return state


def use_supervisor_test_storage(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> argparse.Namespace:
    """Keep synthetic storage roots sibling to, never above, the worktree fixture."""
    base = isolated_roots[0].parents[1].parent
    storage = argparse.Namespace(
        python_exe=Path(sys.executable),
        data_root=base / "supervisor-test-data",
        cache_root=base / "supervisor-test-cache",
        daily_root=base / "supervisor-test-daily",
        backtest_root=base / "supervisor-test-backtests",
        results_root=base / "supervisor-test-results",
        envs_root=base / "supervisor-test-envs",
    )
    monkeypatch.setattr(module, "_storage_paths", lambda: storage)
    return storage


def test_state_schema_atomic_persistence_and_compact_timeline(isolated_roots: tuple[Path, Path]) -> None:
    create_state()
    updated = module.update_task("test-task", {"CURRENT_ACTION": "atomic update"}, event="CHECKPOINT", detail="high signal")
    assert REQUIRED_STATE_FIELDS <= set(updated)
    assert json.loads(module.state_path("test-task").read_text(encoding="utf-8"))["CURRENT_ACTION"] == "atomic update"
    assert module.state_path("test-task").stat().st_size < module.MAX_STATE_BYTES
    assert module.timeline_path("test-task").stat().st_size < module.MAX_TIMELINE_BYTES
    assert not list(module.task_dir("test-task").glob("*.tmp"))


def test_timeline_renders_unrepresentable_unicode_under_strict_gbk(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    module._append_event_unlocked("test-task", "UNICODE", "replacement=\ufffd; emoji=\U0001f642")

    class StrictGbkWriter:
        encoding = "gbk"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def write(self, value: str) -> int:
            value.encode(self.encoding, errors="strict")
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            pass

    output = StrictGbkWriter()
    monkeypatch.setattr(module.sys, "stdout", output)

    assert module.command_timeline(argparse.Namespace(task_id="test-task", limit=1)) == 0
    rendered = "".join(output.parts)
    assert "UNICODE" in rendered
    assert "\\ufffd" in rendered
    assert "\\U0001f642" in rendered


def test_state_compaction_deduplicates_hundreds_of_review_corrections(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state["HARNESS_STATE"] = "RUNNING"
    state["WORK_UNITS"] = [
        module._new_work_unit(
            "WU-001", "Repair repository-root containment in the storage resolver",
            relevant_paths=["scripts/common/storage_paths.ps1"],
        )
    ]
    state["WORK_UNITS"][0]["status"] = "BLOCKED_LOCAL"
    for index in range(300):
        wording = (
            "The storage resolver containment parity defect still permits repository root equality "
            f"in scripts/common/storage_paths.ps1; reviewer wording variant {index}."
        )
        module._queue_correction_work_unit(
            state, "FINAL_REVIEW", wording, "same-progress",
            ["scripts/common/storage_paths.ps1"],
        )
    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")
    corrections = [
        unit for unit in compact["WORK_UNITS"] if unit["id"].startswith("FIX-")
    ]

    assert len(corrections) == 1
    assert len(compact["REVIEW_FINDING_LEDGER"]) == 1
    assert corrections[0]["review_finding_id"] in compact["REVIEW_FINDING_LEDGER"]
    assert "wording variant" not in corrections[0]["objective"]
    assert compact["TELEMETRY"]["review_bodies_deduplicated"] == 300
    assert compact["TELEMETRY"]["duplicate_planned_work_rejected"] == 299
    assert module.state_path("test-task").stat().st_size < 80_000


def test_large_findings_are_bounded_deterministically_and_archived(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "FINALIZE",
        "LAST_REVIEW_STATUS": "PASS", "REVIEW_CORRECTION_DISPOSITION": "ACCEPTED",
    })
    review = "review-head\n" + ("material-review-evidence-" * 300) + "\nreview-tail"
    worker = "worker-head\n" + ("material-worker-evidence-" * 300) + "\nworker-tail"
    state["REVIEW_FINDINGS"] = review
    state["WORKER_FINDINGS"] = worker
    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")

    for field, original in (("REVIEW_FINDINGS", review), ("WORKER_FINDINGS", worker)):
        value = compact[field]
        assert value.startswith(original[:100])
        assert value.endswith(original[-100:])
        assert hashlib.sha256(original.encode("utf-8")).hexdigest() in value
    assert compact["TELEMETRY"]["text_fields_truncated"] >= 2
    archive_hashes = {row["sha256"] for row in compact["STATE_TEXT_ARCHIVES"]}
    assert hashlib.sha256(review.encode("utf-8")).hexdigest() in archive_hashes
    timeline = module.timeline_path("test-task").read_text(encoding="utf-8")
    assert "STATE_TEXT_EVIDENCE" in timeline
    assert "review-head" in timeline and "review-tail" in timeline
    first = module._bounded_state_text(review, 1_600)
    second = module._bounded_state_text(review, 1_600)
    assert first == second


def test_completed_units_remain_recoverable_and_deduplicable_after_compaction(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    unit = module._new_work_unit(
        "FIX-001", "Correct normalized final_review finding [STORAGE_CONTAINMENT_PARITY]",
        relevant_paths=["scripts/common/storage_paths.ps1"],
        required_inputs=["resolver contract " + "x" * 500],
        reuse_evidence=[f"reuse evidence {index} " + "x" * 400 for index in range(12)],
    )
    unit.update({
        "status": "DONE", "validation_state": "PASS",
        "failure_signature": "FINAL_REVIEW:stable-signature",
        "review_finding_id": "FINAL_REVIEW:stable-signature",
        "produced_outputs": ["scripts/common/storage_paths.ps1"],
        "resolved_by": "FIX-001", "retry_history": [
            {"signature": "stable", "count": index, "at": f"t{index}"}
            for index in range(20)
        ],
    })
    state["WORK_UNITS"] = [unit]
    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")
    recovered = module._unit_by_id(compact, "FIX-001")

    assert recovered is not None
    assert recovered["status"] == "DONE"
    assert recovered["failure_signature"] == "FINAL_REVIEW:stable-signature"
    assert recovered["review_finding_id"] == "FINAL_REVIEW:stable-signature"
    assert recovered["produced_outputs"] == ["scripts/common/storage_paths.ps1"]
    assert recovered["validation_state"] == "PASS"
    assert recovered["required_input_count"] == 1
    assert recovered["reuse_evidence_count"] == 12
    assert recovered["retry_history_count"] == 20
    assert 1 <= len(recovered["retry_history"]) <= 5
    assert module._runnable_work_units(compact) == []


def test_active_running_unit_and_pending_worker_markers_survive_compaction(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    active = module._new_work_unit("WU-001", "Active recovery objective")
    active.update({"status": "RUNNING", "objective": "active-" + "x" * 6_000})
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER",
        "ACTIVE_PROCESS_KIND": "WORKER", "WORKER_PID": 4242,
        "ACTIVE_WORK_UNIT_ID": "WU-001", "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "WORK_UNITS": [active],
        "WORKER_FINDINGS": "TASK_RESULT=COMPLETED\n" + "worker-marker-" * 500,
        "PENDING_UNIT_RESULTS": [{"id": "WU-001", "status": "DONE"}],
        "HISTORICAL_FINDINGS": [
            {"identity": f"old-{index}", "detail": "history-" + "z" * 2_000}
            for index in range(100)
        ],
    })
    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")

    assert compact["WORKER_PID"] == 4242
    assert compact["ACTIVE_WORK_UNIT_IDS"] == ["WU-001"]
    assert compact["PENDING_UNIT_RESULTS"] == [{"id": "WU-001", "status": "DONE"}]
    assert compact["WORKER_FINDINGS"].startswith("TASK_RESULT=COMPLETED")
    assert compact["WORKER_FINDINGS"] == state["WORKER_FINDINGS"]
    assert compact["WORK_UNITS"][0]["objective"] == active["objective"]
    assert len(compact["HISTORICAL_FINDINGS"]) == module.STATE_HISTORY_RETAIN


def test_retry_signature_and_compacted_historical_identity_remain_effective(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    unit = module._new_work_unit(
        "WU-001", "Repair one tracked source",
        relevant_paths=["scripts/common/storage_paths.py"],
    )
    state["WORK_UNITS"] = [unit]
    message = r"apply_patch denied for scripts/common/storage_paths.py: PermissionError [WinError 5]"
    module._record_unit_failure(state, ["WU-001"], "WORKER_LOCAL_BLOCKER", message, "p0")
    state["HISTORICAL_FINDINGS"] = [
        {"identity": "PREEXISTING_BASELINE_RESIDUE", "code": "PREEXISTING_BASELINE_RESIDUE", "detail": "old"},
        *({"identity": f"history-{index}", "detail": "x" * 1_000} for index in range(100)),
    ]
    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")
    key = next(iter(compact["RETRY_LEDGER"]))
    count = compact["RETRY_LEDGER"][key]["count"]

    module._record_unit_failure(
        compact, ["WU-001"], "WORKER_LOCAL_BLOCKER",
        "System.UnauthorizedAccessException writing scripts/common/storage_paths.py", "p0",
    )
    assert compact["RETRY_LEDGER"][key]["count"] == count + 1
    before = len(compact["HISTORICAL_FINDINGS"])
    compact["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    assert module._queue_correction_work_unit(
        compact, "FINAL_REVIEW",
        "Pre-existing Anti-Bloat baseline residue outside this task is unchanged by the task.",
        "p0",
    ) is False
    assert len(compact["HISTORICAL_FINDINGS"]) == before


def test_state_near_hard_limit_compacts_before_failure(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state.update({"HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "FINALIZE"})
    state["HISTORICAL_FINDINGS"] = [
        {"identity": f"history-{index}", "detail": f"entry-{index}-" + "h" * 2_000}
        for index in range(100)
    ]
    state["VALIDATION_RESULTS"] = [f"validation-{index}-" + "v" * 3_000 for index in range(100)]
    state["TESTS_RUN"] = [f"test-{index}-" + "t" * 1_000 for index in range(100)]
    state["TEST_HISTORY_START_INDEX"] = 100
    assert len(module._json_bytes(state)) > module.MAX_STATE_BYTES

    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")
    size = module.state_path("test-task").stat().st_size
    assert size < module.STATE_COMPACTION_TARGET_BYTES
    assert compact["STATE_STORAGE_STATUS"] == "COMPACTED"
    assert compact["TELEMETRY"]["state_compactions"] >= 1
    assert compact["TELEMETRY"]["state_bytes_before_compaction"] > module.MAX_STATE_BYTES
    assert compact["TELEMETRY"]["state_bytes_after_compaction"] < module.MAX_STATE_BYTES
    assert compact["TELEMETRY"]["historical_entries_compacted"] > 100


def test_state_compaction_exhaustion_persists_terminal_diagnostic(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "tiny-state"
    module.task_dir(task_id).mkdir(parents=True)
    state = module._new_state(task_id, "g" * 20_000, "independent-code", 2)
    monkeypatch.setattr(module, "MAX_STATE_BYTES", 2_048)
    monkeypatch.setattr(module, "STATE_COMPACTION_TARGET_BYTES", 1_500)

    module._write_state_unlocked(task_id, state)
    diagnostic = module.load_state(task_id)
    assert diagnostic["HARNESS_STATE"] == "FAILED"
    assert diagnostic["NEXT_ACTION_CODE"] == "DONE"
    assert diagnostic["STATE_STORAGE_STATUS"] == "COMPACTION_EXHAUSTED"
    assert diagnostic["STATE_STORAGE_FAILURE"].startswith("STATE_COMPACTION_EXHAUSTED:")
    assert module.state_path(task_id).stat().st_size < 2_048
    module._dispatch_r3(task_id)


def test_longrun_synthetic_state_growth_stays_well_below_hard_limit(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state.update({
        "HARNESS_STATE": "COMPLETED_WITH_DEFERRED_WORK", "NEXT_ACTION_CODE": "DONE",
        "LAST_REVIEW_STATUS": "PASS_WITH_WARNINGS", "TERMINAL_OUTCOME": "COMPLETED_WITH_DEFERRED_WORK",
    })
    units = []
    for index in range(module.MAX_WORK_UNITS):
        unit = module._new_work_unit(
            f"WU-{index:03d}", f"Historical objective {index} " + "o" * 900,
            required_inputs=["input-" + "i" * 500 for _ in range(10)],
            reuse_evidence=["reuse-" + "r" * 500 for _ in range(10)],
        )
        unit.update({
            "status": ("DONE", "BLOCKED_LOCAL", "DEFERRED")[index % 3],
            "validation_state": "PASS" if index % 3 == 0 else "NOT_RUN",
            "blocker": {"code": "LOCAL", "detail": "b" * 2_000} if index % 3 else {},
            "failure_signature": f"signature-{index}",
            "retry_history": [{"signature": f"s-{index}", "count": retry} for retry in range(20)],
        })
        units.append(unit)
    state["WORK_UNITS"] = units
    for index in range(300):
        module._queue_correction_work_unit(
            state, "FINAL_REVIEW",
            f"Storage containment parity defect in scripts/common/storage_paths.ps1 wording {index}",
            "same-progress", ["scripts/common/storage_paths.ps1"],
        )
    state["HISTORICAL_FINDINGS"] = [
        {"identity": f"historical-{index}", "detail": "h" * 2_000} for index in range(400)
    ]
    state["RESOLVED_FINDINGS"] = [
        {"identity": f"resolved-{index}", "detail": "r" * 1_000} for index in range(300)
    ]
    state["VALIDATION_RESULTS"] = ["validation-" + "v" * 3_000 for _ in range(200)]
    state["TESTS_RUN"] = ["pytest-" + "t" * 1_000 for _ in range(200)]
    state["TEST_HISTORY_START_INDEX"] = 200
    state["REVIEW_FINDINGS"] = "review-" + "q" * 8_000
    state["WORKER_FINDINGS"] = "worker-" + "w" * 8_000
    raw_size = len(module._json_bytes(state))
    assert raw_size > 1_000_000

    module._write_state_unlocked("test-task", state)
    compact = module.load_state("test-task")
    size = module.state_path("test-task").stat().st_size
    assert size < 90_000
    assert compact["HARNESS_STATE"] == "COMPLETED_WITH_DEFERRED_WORK"
    assert compact["NEXT_ACTION_CODE"] == "DONE"
    assert len(compact["WORK_UNITS"]) == module.MAX_WORK_UNITS + 1
    assert len([unit for unit in compact["WORK_UNITS"] if unit["id"].startswith("FIX-")]) == 1
    assert module._unit_by_id(compact, "WU-000")["status"] == "DONE"
    assert module._unit_by_id(compact, "WU-001")["failure_signature"] == "signature-1"
    assert len(compact["REVIEW_FINDING_LEDGER"]) == 1
    assert compact["TELEMETRY"]["state_compactions"] >= 1
    assert compact["TELEMETRY"]["historical_entries_compacted"] > 500
    assert compact["TELEMETRY"]["review_bodies_deduplicated"] == 300


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


def test_new_component_justification_survives_same_path_correction(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state["WORKTREE"] = str(worktree)
    module._write_state_unlocked("test-task", state)
    artifact = "docs/new-component.md"
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [artifact], "created": [artifact], "dependencies": [],
        "changed_count": 1, "created_count": 1,
    })

    module._refresh_changes(
        "test-task",
        worker_findings=(
            "TASK_RESULT=COMPLETED\n"
            "NEW_COMPONENT_JUSTIFICATION=No authoritative component existed"
        ),
    )
    initial = module.load_state("test-task")
    assert initial["REUSE_GUARD"] == "PASS_SEARCH_RECORDED"
    assert initial["JUSTIFIED_CREATED_PATHS"] == [artifact]

    module._refresh_changes(
        "test-task",
        worker_findings="TASK_RESULT=COMPLETED\nNEW_COMPONENT_JUSTIFICATION=NONE",
    )
    corrected = module.load_state("test-task")
    assert corrected["REUSE_GUARD"] == "PASS_SEARCH_RECORDED"
    assert corrected["NEW_COMPONENT_JUSTIFICATION"] == "No authoritative component existed"
    assert corrected["JUSTIFIED_CREATED_PATHS"] == [artifact]
    assert corrected["UNJUSTIFIED_CREATED_PATHS"] == []


def test_correction_with_new_unjustified_path_fails_closed(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state["WORKTREE"] = str(worktree)
    module._write_state_unlocked("test-task", state)
    created = ["docs/component-a.md"]
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": list(created), "created": list(created), "dependencies": [],
        "changed_count": len(created), "created_count": len(created),
    })
    module._refresh_changes(
        "test-task",
        worker_findings="NEW_COMPONENT_JUSTIFICATION=Component A had no reusable predecessor",
    )

    created.append("docs/component-b.md")
    module._refresh_changes(
        "test-task", worker_findings="NEW_COMPONENT_JUSTIFICATION=NONE",
    )
    corrected = module.load_state("test-task")
    assert corrected["REUSE_GUARD"] == "HARD_BLOCKER_NEW_COMPONENT_JUSTIFICATION_MISSING"
    assert corrected["JUSTIFIED_CREATED_PATHS"] == ["docs/component-a.md"]
    assert corrected["UNJUSTIFIED_CREATED_PATHS"] == ["docs/component-b.md"]


def test_initial_unjustified_component_behavior_remains_fail_closed(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state["WORKTREE"] = str(worktree)
    module._write_state_unlocked("test-task", state)
    artifact = "scripts/new_component.py"
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [artifact], "created": [artifact], "dependencies": [],
        "changed_count": 1, "created_count": 1,
    })

    module._refresh_changes(
        "test-task", worker_findings="NEW_COMPONENT_JUSTIFICATION=NONE",
    )
    current = module.load_state("test-task")
    assert current["REUSE_GUARD"] == "HARD_BLOCKER_NEW_COMPONENT_JUSTIFICATION_MISSING"
    assert current["JUSTIFIED_CREATED_PATHS"] == []
    assert current["UNJUSTIFIED_CREATED_PATHS"] == [artifact]


def test_legacy_corrected_state_recovers_only_prevalidated_reviewed_path(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    artifact = "docs/existing-task-artifact.md"
    state.pop("JUSTIFIED_CREATED_PATHS")
    state.pop("UNJUSTIFIED_CREATED_PATHS")
    state.update({
        "WORKTREE": str(worktree),
        "FILES_CREATED": [artifact],
        "NEW_COMPONENT_JUSTIFICATION": "NONE",
        "CORRECTION_ATTEMPTS": 1,
        "LAST_REVIEW_STATUS": "FIX_REQUIRED",
        "REVIEW_FINDINGS": f"Review of {worktree / artifact}:12 requires correction",
    })
    module._write_state_unlocked("test-task", state)
    module._append_event_unlocked("test-task", "CHANGE_INVENTORY", "changed=1;created=1;dependencies=0")
    module._append_event_unlocked(
        "test-task", "TARGETED_VALIDATION_COMPLETED", "tests=PASS;preflight=PASS",
    )
    module._append_event_unlocked("test-task", "REVIEW_CLASSIFIED", "FIX_REQUIRED")
    module._append_event_unlocked("test-task", "REVIEW_CORRECTION_REQUESTED", "attempt=1")
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [artifact], "created": [artifact], "dependencies": [],
        "changed_count": 1, "created_count": 1,
    })

    module._refresh_changes("test-task")
    recovered = module.load_state("test-task")
    assert recovered["REUSE_GUARD"] == "PASS_SEARCH_RECORDED"
    assert recovered["JUSTIFIED_CREATED_PATHS"] == [artifact]
    assert recovered["NEW_COMPONENT_JUSTIFICATION"] == (
        "INHERITED_VALIDATED_PRE_CORRECTION_JUSTIFICATION"
    )


def test_repeated_identical_blocker_is_deduplicated(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    duplicate = {
        "code": "NEW_COMPONENT_JUSTIFICATION_REQUIRED", "detail": "docs/a.md",
    }
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "BLOCKERS": [duplicate, duplicate.copy()],
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["docs/a.md"], "created": ["docs/a.md"], "dependencies": [],
        "changed_count": 1, "created_count": 1,
    })

    module._wait_human("test-task", "NEW_COMPONENT_JUSTIFICATION_REQUIRED", "docs/a.md")
    module._wait_human("test-task", "NEW_COMPONENT_JUSTIFICATION_REQUIRED", "docs/a.md")
    blockers = module.load_state("test-task")["BLOCKERS"]
    assert blockers == [{
        "code": "NEW_COMPONENT_JUSTIFICATION_REQUIRED", "detail": "docs/a.md",
    }]


def test_r3_plan_rejects_duplicate_identity_under_different_wording() -> None:
    units, rejected = module._normalize_work_unit_plan([
        {
            "id": "WU-001", "objective": "Repair the existing market calendar loader",
            "identity": "market-calendar-loader", "reuse_decision": "EXTEND",
        },
        {
            "id": "WU-002", "objective": "Build another calendar ingestion utility",
            "identity": "market calendar loader", "reuse_decision": "CREATE",
        },
    ], "Repair the loader")

    assert [unit["id"] for unit in units] == ["WU-001"]
    assert units[0]["reuse_decision"] == "EXTEND"
    assert rejected == 1


def test_r3_reuse_cache_refreshes_only_for_materially_new_created_paths(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state["WORK_UNITS"] = [module._new_work_unit("WU-001", "Extend the existing task runner")]
    state["REUSE_DISCOVERY_CACHE"] = module._initial_reuse_cache({
        "filename_matches": ["scripts/maintenance/harness_task.py"],
        "semantic_matches": [], "candidate_classifications": [],
    })
    module._write_state_unlocked("test-task", state)
    calls: list[tuple[str, tuple[str, ...]]] = []

    def discover(query: str, roots=None) -> dict:
        calls.append((query, tuple(roots or ())))
        return {
            "filename_matches": ["scripts/maintenance/harness_task.py"],
            "semantic_matches": [], "candidate_classifications": [],
        }

    monkeypatch.setattr(module, "_discover_existing", discover)
    unchanged = {"created": [], "changed": ["scripts/maintenance/harness_task.py"]}
    first = {"created": ["scripts/maintenance/new_helper.py"], "changed": []}
    second = {"created": ["scripts/maintenance/new_helper.py", "scripts/maintenance/other_helper.py"], "changed": []}

    assert module._refresh_reuse_discovery_for_changes("test-task", unchanged, ["WU-001"]) is False
    assert module._refresh_reuse_discovery_for_changes("test-task", first, ["WU-001"]) is True
    assert module._refresh_reuse_discovery_for_changes("test-task", first, ["WU-001"]) is False
    assert module._refresh_reuse_discovery_for_changes("test-task", second, ["WU-001"]) is True
    refreshed = module.load_state("test-task")
    assert len(calls) == 2
    assert all(roots == ("scripts",) for _, roots in calls)
    assert refreshed["TELEMETRY"]["discovery_incremental_refreshes"] == 2
    assert refreshed["REUSE_DISCOVERY_CACHE"]["covered_created_paths"] == [
        "scripts/maintenance/new_helper.py", "scripts/maintenance/other_helper.py",
    ]


def test_r3_parallel_version_suffix_component_is_rejected_for_reuse() -> None:
    state = module._new_state("test-task", "Extend foo", "independent-code", 2)
    state["REUSE_DISCOVERY_CACHE"] = module._initial_reuse_cache({
        "filename_matches": ["scripts/foo.py"], "semantic_matches": [],
    })
    conflicts = module._parallel_component_conflicts(state, {
        "created": ["scripts/foo_r3.py"], "changed": ["scripts/foo_r3.py"],
    })

    assert conflicts == ["scripts/foo_r3.py duplicates identity of existing scripts/foo.py"]


def test_r3_failure_retries_are_per_signature_and_leave_independent_work_runnable() -> None:
    state = module._new_state("test-task", "Repair two independent areas", "independent-code", 2)
    state["WORK_UNITS"] = [
        module._new_work_unit("WU-001", "Repair source-dependent loader"),
        module._new_work_unit("WU-002", "Improve independent parser"),
    ]
    state["ACTIVE_WORK_UNIT_IDS"] = ["WU-001"]
    state["WORK_UNITS"][0]["status"] = "RUNNING"
    for _ in range(module.DEFAULT_FAILURE_RETRY_LIMIT + 1):
        state["ACTIVE_WORK_UNIT_IDS"] = ["WU-001"]
        state["WORK_UNITS"][0]["status"] = "RUNNING"
        module._record_unit_failure(
            state, ["WU-001"], "SOURCE_UNAVAILABLE", "SEC endpoint unavailable", "same-progress",
        )

    assert state["WORK_UNITS"][0]["status"] == "BLOCKED_LOCAL"
    assert [unit["id"] for unit in module._runnable_work_units(state)] == ["WU-002"]
    assert state["HARNESS_STATE"] == "PLANNING"


def test_r3_permission_failure_is_local_without_acl_or_human_escalation(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    blocked = module._new_work_unit("WU-001", "Write one source-specific artifact")
    independent = module._new_work_unit("WU-002", "Repair an independent parser")
    blocked["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORK_UNITS": [blocked, independent],
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"], "ACTIVE_WORK_UNIT_ID": "WU-001",
    })
    module._write_state_unlocked("test-task", state)

    module._record_local_blocker(
        "test-task", ["WU-001"], "PATH_NOT_WRITABLE",
        "No valid authorized fallback exists for this unit", progress_hash="unchanged",
    )

    current = module.load_state("test-task")
    assert current["WORK_UNITS"][0]["status"] == "BLOCKED_LOCAL"
    assert [unit["id"] for unit in module._runnable_work_units(current)] == ["WU-002"]
    assert current["HARNESS_STATE"] == "RUNNING"
    assert current["ACTIVE_BLOCKERS"] == []
    assert current["HUMAN_ATTENTION_REQUIRED"] is False
    assert current["TELEMETRY"]["local_blockers_bypassed"] == 1
    assert "PERMISSION" not in module.HUMAN_BOUNDARY_KINDS
    assert "PROTECTED_PERMISSION" in module.HUMAN_BOUNDARY_KINDS


def test_r3_review_finding_deduplicates_wording_without_new_correction() -> None:
    state = module._new_state("test-task", "Repair storage containment", "independent-code", 2)
    parent = module._new_work_unit(
        "WU-001", "Repair storage containment parity",
        relevant_paths=["scripts/common/storage_paths.py", "scripts/common/storage_paths.ps1"],
    )
    parent["status"] = "BLOCKED_LOCAL"
    state["WORK_UNITS"] = [parent]
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    first = (
        "The explicit RepoRoot containment is defective in scripts/common/storage_paths.ps1; "
        "repository-root equality is accepted. The inherited Anti-Bloat CRLF baseline residue is outside this diff."
    )
    second = (
        "High: scripts/common/storage_paths.ps1 permits the repo root as external, breaking storage resolver parity. "
        "All Anti-Bloat hashes match Git blobs; that pre-existing residue is unchanged by this task."
    )

    assert module._queue_correction_work_unit(
        state, "FINAL_REVIEW", first, "same-progress", ["scripts/common/storage_paths.ps1"],
    ) is True
    assert module._queue_correction_work_unit(
        state, "FINAL_REVIEW", second, "same-progress", ["scripts/common/storage_paths.ps1"],
    ) is True

    corrections = [unit for unit in state["WORK_UNITS"] if unit["id"].startswith("FIX-")]
    assert len(corrections) == 1
    assert corrections[0]["review_finding_identity"] == "STORAGE_CONTAINMENT_PARITY|scripts/common/storage_paths"
    assert state["TELEMETRY"]["repeated_work_prevented"] == 1
    assert state["TELEMETRY"]["duplicate_planned_work_rejected"] == 1


def test_r3_final_review_identity_is_canonical_across_entrypoints() -> None:
    state = module._new_state("test-task", "Repair one path", "independent-code", 2)
    relevant_paths = ["scripts/common/storage_paths.py"]
    detail = "Reviewer write was denied with Access Denied."

    finding = module._review_finding_identity(state, detail, relevant_paths)
    signature = module._failure_signature(
        "FINAL_REVIEW", detail, relevant_paths, state=state,
    )
    assert finding["identity"] == (
        "PERMISSION:WRITE|scripts/common/storage_paths.py|ACCESS_DENIED"
    )
    assert signature == finding["signature"]

    assert module._queue_correction_work_unit(
        state, "FINAL_REVIEW", detail, "same-progress", relevant_paths,
    ) is True
    correction = state["WORK_UNITS"][-1]
    assert correction["failure_signature"] == signature
    assert correction["review_finding_identity"] == finding["identity"]
    assert state["LAST_REVIEW_FINDING_IDENTITY"] == finding["identity"]
    assert set(state["REVIEW_FINDING_LEDGER"]) == {signature}


def test_r3_nonactionable_review_identities_do_not_share_empty_signature() -> None:
    complete = module._new_state("complete", "Complete audit", "independent-code", 2)
    done = module._new_work_unit("WU-001", "Complete audit")
    done["status"] = "DONE"
    complete["WORK_UNITS"] = [done]
    incomplete = module._new_state("incomplete", "Complete required work", "independent-code", 2)
    baseline = module._new_state("baseline", "Audit task delta", "independent-code", 2)
    baseline["ANTI_BLOAT_TASK_DELTA"] = "PASS"

    findings = [
        module._review_finding_identity(
            complete, "No reviewable diff; the clean worktree has zero files changed.",
        ),
        module._review_finding_identity(
            incomplete, "Task incomplete: no reviewable output and mandatory work remains blocked.",
        ),
        module._review_finding_identity(
            baseline,
            "The inherited Anti-Bloat CRLF baseline residue is unchanged by this task.",
        ),
    ]

    assert [finding["identity"] for finding in findings] == [
        "VALID_ZERO_DIFF_COMPLETION",
        "TASK_INCOMPLETE",
        "PREEXISTING_BASELINE_RESIDUE",
    ]
    assert len({finding["signature"] for finding in findings}) == 3


def test_r3_validated_correction_reconciles_parent_and_reopens_dependency() -> None:
    state = module._new_state("test-task", "Repair storage containment", "independent-code", 2)
    parent = module._new_work_unit(
        "WU-001", "Repair storage containment parity",
        relevant_paths=["scripts/common/storage_paths.ps1"],
    )
    parent.update({"status": "BLOCKED_LOCAL", "blocker": {"code": "ACCESS_DENIED"}})
    dependent = module._new_work_unit(
        "WU-002", "Validate the repaired storage chain", dependencies=["WU-001"],
    )
    dependent.update({
        "status": "DEFERRED",
        "blocker": {"code": "DEPENDENCY_UNAVAILABLE", "dependencies": ["WU-001"]},
    })
    state["WORK_UNITS"] = [parent, dependent]
    assert module._queue_correction_work_unit(
        state, "FINAL_REVIEW",
        "RepoRoot containment in scripts/common/storage_paths.ps1 accepts repository equality.",
        "progress-a", ["scripts/common/storage_paths.ps1"],
    ) is True
    correction = state["WORK_UNITS"][-1]
    correction["status"] = "RUNNING"
    state["ACTIVE_WORK_UNIT_IDS"] = [correction["id"]]
    state["PENDING_UNIT_RESULTS"] = [{
        "id": correction["id"], "status": "DONE", "produced_outputs": [],
        "validation_state": "PASS", "blocker": {}, "last_checkpoint": "VALIDATED",
        "next_action": "", "reuse_decision": "EXTEND", "reuse_evidence": [],
    }]

    module._apply_validated_unit_results(state)

    assert parent["status"] == "DONE"
    assert parent["resolved_by"] == correction["id"]
    assert dependent["status"] == "READY"
    assert dependent["last_checkpoint"] == "DEPENDENCY_RESOLVED"
    assert any(row.get("work_unit_id") == "WU-001" for row in state["RESOLVED_FINDINGS"])


def test_r3_permission_failure_signature_uses_operation_target_and_error_class() -> None:
    messages = [
        r"apply_patch write denied for scripts/common/storage_paths.py: PermissionError [WinError 5]",
        r"System.UnauthorizedAccessException while writing D:\repo\scripts\common\storage_paths.py",
        r"Absolute and relative writes to scripts/common/storage_paths.py were denied with access denied",
    ]
    signatures = {module._failure_signature("WORKER_LOCAL_BLOCKER", message) for message in messages}
    assert signatures == {"PERMISSION:WRITE|scripts/common/storage_paths.py|ACCESS_DENIED"}

    state = module._new_state("test-task", "Repair one path", "independent-code", 2)
    unit = module._new_work_unit(
        "WU-001", "Repair one tracked source path",
        relevant_paths=["scripts/common/storage_paths.py"],
    )
    state["WORK_UNITS"] = [unit]
    for message in [*messages, "Tracked resolver files reject writes with UnauthorizedAccessException"]:
        module._record_unit_failure(state, ["WU-001"], "WORKER_LOCAL_BLOCKER", message, "unchanged")
    assert unit["status"] == "BLOCKED_LOCAL"
    assert len(state["RETRY_LEDGER"]) == 1
    assert state["ACTIVE_BLOCKERS"] == []
    assert state["HARNESS_STATE"] == "PLANNING"


def test_r3_preexisting_anti_bloat_residue_does_not_generate_task_correction() -> None:
    state = module._new_state("test-task", "Audit one active path", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    state["FILES_CHANGED"] = ["scripts/common/storage_paths.py"]
    residue = (
        "The Anti-Bloat guard reports 30 inherited CRLF baseline violations outside this diff; "
        "all hashes match Git blobs and the issue is unchanged by the task."
    )
    assert module._queue_correction_work_unit(state, "FINAL_REVIEW", residue, "p1") is False
    assert not state["WORK_UNITS"]
    assert state["LAST_REVIEW_FINDING_IDENTITY"] == "PREEXISTING_BASELINE_RESIDUE"
    assert state["HISTORICAL_FINDINGS"][-1]["code"] == "PREEXISTING_BASELINE_RESIDUE"

    task_delta = "Anti-Bloat task delta violation: a task-created .venv must be removed."
    assert module._queue_correction_work_unit(state, "FINAL_REVIEW", task_delta, "p1") is True
    assert len(state["WORK_UNITS"]) == 1
    mixed = "The inherited CRLF baseline is unchanged, but this task-created .venv is a new Anti-Bloat violation."
    assert module._review_finding_analysis(state, mixed)["baseline_residue"] is False


def test_r3_zero_diff_completion_and_incomplete_zero_diff_converge_without_correction() -> None:
    complete = module._new_state("complete", "Audit and make no change if unwarranted", "independent-code", 2)
    audit = module._new_work_unit("WU-001", "Complete the authorized audit")
    audit["status"] = "DONE"
    complete["WORK_UNITS"] = [audit]
    assert module._queue_correction_work_unit(
        complete, "FINAL_REVIEW", "No reviewable diff; the clean worktree has zero files changed.", "p0",
    ) is False
    assert complete["REVIEW_CORRECTION_DISPOSITION"] == "VALID_ZERO_DIFF_COMPLETION"
    assert complete["LAST_REVIEW_FINDING_IDENTITY"] == "VALID_ZERO_DIFF_COMPLETION"
    assert len(complete["WORK_UNITS"]) == 1

    incomplete = module._new_state("incomplete", "Complete required work", "independent-code", 2)
    blocked = module._new_work_unit("WU-001", "Required blocked work")
    blocked["status"] = "BLOCKED_LOCAL"
    incomplete["WORK_UNITS"] = [blocked]
    assert module._queue_correction_work_unit(
        incomplete, "FINAL_REVIEW", "Task incomplete: no reviewable output and mandatory work remains blocked.", "p0",
    ) is False
    assert incomplete["REVIEW_CORRECTION_DISPOSITION"] == "INCOMPLETE_NO_RUNNABLE_REMEDY"
    assert incomplete["LAST_REVIEW_FINDING_IDENTITY"] == "TASK_INCOMPLETE"
    assert len(incomplete["WORK_UNITS"]) == 1


def test_r3_pending_steer_is_consumed_once_at_safe_boundary(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state["PENDING_STEER"] = ["Prefer the existing parser."]
    state["STEERING_HISTORY"] = [{
        "instruction": "Prefer the existing parser.", "accepted": True,
    }]
    module._write_state_unlocked("test-task", state)

    assert module._consume_pending_steer("test-task") == ["Prefer the existing parser."]
    assert module._consume_pending_steer("test-task") == []
    consumed = module.load_state("test-task")
    assert consumed["PENDING_STEER"] == []
    assert consumed["STEERING_HISTORY"][0]["applied"] is True


def test_r3_reviewer_crash_recovers_without_rerunning_completed_units(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    done = module._new_work_unit("WU-001", "Complete implementation")
    done["status"] = "DONE"
    state.update({
        "HARNESS_STATE": "REVIEWING", "WORKTREE": str(worktree),
        "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998,
        "ACTIVE_PROCESS_KIND": "REVIEW", "WORK_UNITS": [done],
        "NEXT_ACTION_CODE": "FINAL_REVIEW",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["scripts/existing.py"], "created": [], "dependencies": [],
    })

    recovered = module.recover_if_interrupted("test-task")

    assert recovered["HARNESS_STATE"] == "RUNNING"
    assert recovered["NEXT_ACTION_CODE"] == "FINAL_REVIEW"
    assert recovered["WORK_UNITS"][0]["status"] == "DONE"
    assert recovered["HUMAN_ATTENTION_REQUIRED"] is False


def test_r3_duplicate_controller_dispatch_is_prevented(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state.update({
        "CONTROLLER_PID": 4242,
        "CONTROLLER_LAUNCH_PID": 4242,
        "CONTROLLER_LAUNCH_TOKEN": "a" * 32,
        "CONTROLLER_STARTUP_STATUS": "STARTING",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(
        module.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("duplicate spawned")),
    )

    assert module._spawn_controller("test-task") == 4242


def test_controller_launch_token_adopts_runtime_pid_and_wrong_token_is_rejected(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    token = "b" * 32
    state.update({
        "HARNESS_STATE": "STOPPED",
        "CONTROLLER_PID": 6101,
        "CONTROLLER_LAUNCH_PID": 6101,
        "CONTROLLER_LAUNCH_TOKEN": token,
        "CONTROLLER_STARTUP_STATUS": "STARTING",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 6101)
    monkeypatch.setattr(module, "_dispatch", lambda task_id: None)

    assert module.run_task("test-task", launch_token=token) == 0
    adopted = module.load_state("test-task")
    assert adopted["CONTROLLER_LAUNCH_PID"] == 6101
    assert adopted["CONTROLLER_PID"] == module.os.getpid()
    assert adopted["CONTROLLER_PARENT_PID"] == module.os.getppid()
    assert adopted["CONTROLLER_LAUNCH_TOKEN"] == ""
    assert adopted["CONTROLLER_STARTUP_STATUS"] == "EXITED"
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("CONTROLLER_STARTED") == 1
    assert events.count("CONTROLLER_READY") == 1

    adopted.update({
        "CONTROLLER_PID": 6101,
        "CONTROLLER_LAUNCH_TOKEN": "c" * 32,
        "CONTROLLER_STARTUP_STATUS": "STARTING",
    })
    module._write_state_unlocked("test-task", adopted)
    with pytest.raises(module.HarnessError, match="DUPLICATE_CONTROLLER_PREVENTED"):
        module.run_task("test-task", launch_token="wrong-token")
    rejected = module.load_state("test-task")
    assert rejected["CONTROLLER_PID"] == 6101
    assert rejected["CONTROLLER_LAUNCH_TOKEN"] == "c" * 32


def test_controller_ready_handshake_uses_one_shared_windows_safe_launch(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    use_supervisor_test_storage(isolated_roots, monkeypatch)
    for name in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(name, raising=False)
    observed: dict = {"launches": 0}

    class ReadyController:
        pid = 6201

        def poll(self):
            if not module.load_state("test-task").get("CONTROLLER_READY_AT"):
                started = module.utc_now()
                module.update_task("test-task", {
                    "CONTROLLER_PID": 7201,
                    "CONTROLLER_STARTED_AT": started,
                    "CONTROLLER_STARTUP_STATUS": "STARTED",
                }, event="CONTROLLER_STARTED", detail="simulated runtime adoption")
                ready = module.utc_now()
                module.update_task("test-task", {
                    "CONTROLLER_READY_AT": ready,
                    "CONTROLLER_HEARTBEAT_AT": ready,
                    "CONTROLLER_STARTUP_STATUS": "READY",
                }, event="CONTROLLER_READY", detail="simulated runtime ready")
            return 0

        def terminate(self):
            raise AssertionError("ready runtime must remain alive")

        def wait(self, timeout=None):
            return 0

    def launch(*args, **kwargs):
        observed.update({"args": args, **kwargs})
        observed["launches"] += 1
        return ReadyController()

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 7201)

    assert module._spawn_controller("test-task", startup_timeout=0.5) == 7201
    assert module._spawn_controller("test-task", startup_timeout=0.5) == 7201
    ready = module.load_state("test-task")
    runtime = module.task_temp_runtime("test-task")
    command = observed["args"][0]
    assert observed["launches"] == 1
    assert ready["CONTROLLER_LAUNCH_PID"] == 6201
    assert ready["CONTROLLER_PID"] == 7201
    assert ready["CONTROLLER_STARTUP_STATUS"] == "READY"
    assert ready["CONTROLLER_HEARTBEAT_AT"]
    assert command[3:6] == ["_run", "--task-id", "test-task"]
    assert command[6] == "--launch-token" and len(command[7]) == 32
    assert Path(observed["cwd"]).resolve() == module.REPO.resolve()
    assert all(Path(observed["env"][name]).resolve() == runtime for name in ("TEMP", "TMP", "TMPDIR"))
    if module.os.name == "nt":
        assert observed["creationflags"] & module.subprocess.DETACHED_PROCESS
        assert observed["creationflags"] & module.subprocess.CREATE_BREAKAWAY_FROM_JOB
        assert ready["CONTROLLER_SPAWN_MODE"] == "WINDOWS_DETACHED_BREAKAWAY"
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("CONTROLLER_DISPATCHED") == 1
    assert events.count("CONTROLLER_STARTED") == 1
    assert events.count("CONTROLLER_READY") == 1
    assert events.count("CONTROLLER_STARTUP_HANDSHAKE_PASSED") == 1


def test_controller_exit_before_started_retries_by_signature_then_fails_terminally(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    use_supervisor_test_storage(isolated_roots, monkeypatch)
    launched: list[int] = []

    class ExitedController:
        def __init__(self, pid: int):
            self.pid = pid

        def poll(self):
            return 17

        def terminate(self):
            raise AssertionError("already exited")

        def wait(self, timeout=None):
            return 17

    def launch(*args, **kwargs):
        pid = 6300 + len(launched)
        launched.append(pid)
        kwargs["stderr"].write(b"controller bootstrap failed before started\n")
        kwargs["stderr"].flush()
        return ExitedController(pid)

    monkeypatch.setattr(module.subprocess, "Popen", launch)

    assert module._spawn_controller("test-task", startup_timeout=0.2) is None
    first = module.load_state("test-task")
    assert first["HARNESS_STATE"] == "PLANNING"
    assert first["CONTROLLER_STARTUP_STATUS"] == "RETRY"
    assert first["CONTROLLER_STARTUP_RETRY_COUNT"] == 1
    signature = first["CONTROLLER_STARTUP_RETRY_SIGNATURE"]
    assert signature.startswith("CONTROLLER_BOOTSTRAP:")
    assert first["CONTROLLER_STARTUP_RETRY_BACKOFF_SECONDS"] > 0

    assert module._spawn_controller("test-task", startup_timeout=0.2) is None
    assert module._spawn_controller("test-task", startup_timeout=0.2) is None
    failed = module.load_state("test-task")
    assert failed["HARNESS_STATE"] == "FAILED"
    assert failed["CONTROLLER_STARTUP_STATUS"] == "FAILED"
    assert failed["CONTROLLER_STARTUP_RETRY_COUNT"] == 3
    assert failed["CONTROLLER_STARTUP_RETRY_SIGNATURE"] == signature
    assert failed["CONTROLLER_EXIT_CODE"] == 17
    assert "controller bootstrap failed" in failed["CONTROLLER_STDERR_TAIL"]
    assert failed["TERMINAL_OUTCOME"] == "CONTROLLER_STARTUP_FAILED"
    assert failed["HUMAN_ATTENTION_REQUIRED"] is False
    assert len(launched) == 3
    assert module._spawn_controller("test-task", startup_timeout=0.2) is None
    assert len(launched) == 3
    ledger = failed["RETRY_LEDGER"][signature]
    assert ledger["count"] == 3


def test_ready_controller_crash_recovers_progress_without_human_boundary(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    done = module._new_work_unit("WU-001", "Already completed unit")
    done["status"] = "DONE"
    state.update({"HARNESS_STATE": "RUNNING", "WORK_UNITS": [done]})
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(
        module, "_dispatch",
        lambda task_id: (_ for _ in ()).throw(RuntimeError("controller runtime crash")),
    )
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)

    assert module.run_task("test-task") == 1
    crashed = module.load_state("test-task")
    assert crashed["HARNESS_STATE"] == "RUNNING"
    assert crashed["CONTROLLER_STARTUP_STATUS"] == "RUNTIME_FAILED"
    assert crashed["CONTROLLER_EXIT_CODE"] == 1
    assert crashed["CONTROLLER_PID"] == module.os.getpid()
    assert crashed["WORK_UNITS"][0]["status"] == "DONE"
    assert crashed["HUMAN_ATTENTION_REQUIRED"] is False

    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "RUNNING"
    assert recovered["CONTROLLER_PID"] is None
    assert recovered["WORK_UNITS"][0]["status"] == "DONE"
    assert recovered["HUMAN_ATTENTION_REQUIRED"] is False


def test_controller_explicit_stop_wins_stale_running_transition_cleanly(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state["HARNESS_STATE"] = "RUNNING"
    module._write_state_unlocked("test-task", state)

    def stop_then_stale_transition(task_id: str) -> None:
        module.update_task(task_id, {
            "STOP_REQUESTED": True,
        }, new_state="STOPPING", event="STOP_REQUESTED")
        raise module.HarnessError("INVALID_STATE_TRANSITION:STOPPING->RUNNING")

    monkeypatch.setattr(module, "_dispatch", stop_then_stale_transition)

    assert module.run_task("test-task") == 0
    stopped = module.load_state("test-task")
    assert stopped["HARNESS_STATE"] == "STOPPING"
    assert stopped["CONTROLLER_STARTUP_STATUS"] == "EXITED"
    assert stopped["CONTROLLER_EXIT_CODE"] == 0
    assert stopped["CONTROLLER_EXCEPTION"] == ""
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert "CONTROLLER_CONTROL_BOUNDARY_EXIT" in events


def test_supervisor_spawn_exit_before_started_fails_handshake_with_diagnostics(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    use_supervisor_test_storage(isolated_roots, monkeypatch)
    observed: dict = {}

    class ExitedSupervisor:
        pid = 5101

        def poll(self):
            return 17

        def terminate(self):
            raise AssertionError("already exited")

        def wait(self, timeout=None):
            return 17

    def launch(*args, **kwargs):
        observed.update({"args": args, **kwargs})
        kwargs["stderr"].write(b"fatal bootstrap traceback\n")
        kwargs["stderr"].flush()
        return ExitedSupervisor()

    monkeypatch.setattr(module.subprocess, "Popen", launch)

    with pytest.raises(module.HarnessError, match="SUPERVISOR_STARTUP_FAILED"):
        module._spawn_supervisor("test-task", startup_timeout=0.5)

    failed = module.load_state("test-task")
    assert failed["HARNESS_STATE"] == "FAILED"
    assert failed["CURRENT_PHASE"] == "SUPERVISOR_STARTUP_FAILED"
    assert failed["SUPERVISOR_STARTUP_STATUS"] == "FAILED"
    assert failed["SUPERVISOR_PID"] == 5101
    assert failed["SUPERVISOR_PARENT_PID"] == module.os.getpid()
    assert failed["SUPERVISOR_EXIT_CODE"] == 17
    assert "exited before READY" in failed["SUPERVISOR_EXCEPTION"]
    assert "fatal bootstrap traceback" in failed["SUPERVISOR_STDERR_TAIL"]
    assert failed["TERMINAL_OUTCOME"] == "SUPERVISOR_STARTUP_FAILED"
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["stdout"] is subprocess.DEVNULL


def test_supervisor_ready_child_outlives_start_parent_contract_and_uses_stable_invocation(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    use_supervisor_test_storage(isolated_roots, monkeypatch)
    observed: dict = {}

    class ReadySupervisor:
        pid = 5102
        terminated = False

        def poll(self):
            if not module.load_state("test-task").get("SUPERVISOR_READY_AT"):
                now = module.utc_now()
                module.update_task("test-task", {
                    "SUPERVISOR_PID": 6102,
                    "SUPERVISOR_STARTED_AT": now,
                    "SUPERVISOR_READY_AT": now,
                    "SUPERVISOR_HEARTBEAT_AT": now,
                    "SUPERVISOR_STARTUP_STATUS": "READY",
                }, event="SUPERVISOR_READY", detail="simulated child ready")
            return 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return None

    process = ReadySupervisor()

    def launch(*args, **kwargs):
        observed.update({"args": args, **kwargs})
        return process

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 6102)

    assert module._spawn_supervisor("test-task", startup_timeout=0.5) == 6102

    ready = module.load_state("test-task")
    command = observed["args"][0]
    runtime = module.task_temp_runtime("test-task")
    assert ready["SUPERVISOR_STARTUP_STATUS"] == "READY"
    assert ready["SUPERVISOR_STARTED_AT"] and ready["SUPERVISOR_HEARTBEAT_AT"]
    assert ready["SUPERVISOR_LAUNCH_PID"] == 5102
    assert ready["SUPERVISOR_PID"] == 6102
    assert process.terminated is False
    assert Path(command[0]).resolve() == module._storage_paths().python_exe.resolve()
    assert Path(command[2]).resolve() == module.SCRIPT.resolve()
    assert command[3:6] == ["_supervise", "--task-id", "test-task"]
    assert command[6] == "--launch-token" and len(command[7]) == 32
    assert Path(observed["cwd"]).resolve() == module.REPO.resolve()
    assert observed["close_fds"] is True
    for name in ("TEMP", "TMP", "TMPDIR"):
        assert Path(observed["env"][name]).resolve() == runtime
    if module.os.name == "nt":
        assert observed["creationflags"] & module.subprocess.DETACHED_PROCESS
        assert observed["creationflags"] & module.subprocess.CREATE_NEW_PROCESS_GROUP
        assert observed["creationflags"] & module.subprocess.CREATE_BREAKAWAY_FROM_JOB
        assert ready["SUPERVISOR_SPAWN_MODE"] == "WINDOWS_DETACHED_BREAKAWAY"
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert "SUPERVISOR_STARTUP_HANDSHAKE_PASSED" in events


def test_supervisor_missing_host_temp_uses_external_task_runtime_without_permission_change(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state()
    use_supervisor_test_storage(isolated_roots, monkeypatch)
    for name in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(name, raising=False)
    observed: dict = {}

    class ReadySupervisor:
        pid = 5103

        def poll(self):
            if module.load_state("test-task")["SUPERVISOR_STARTUP_STATUS"] != "READY":
                now = module.utc_now()
                module.update_task("test-task", {
                    "SUPERVISOR_PID": self.pid, "SUPERVISOR_STARTED_AT": now,
                    "SUPERVISOR_READY_AT": now, "SUPERVISOR_HEARTBEAT_AT": now,
                    "SUPERVISOR_STARTUP_STATUS": "READY",
                })
            return None

        def terminate(self):
            raise AssertionError("ready Supervisor must remain alive")

        def wait(self, timeout=None):
            return None

    def launch(*args, **kwargs):
        observed.update(kwargs)
        return ReadySupervisor()

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    assert module._spawn_supervisor("test-task", startup_timeout=0.5) == 5103

    runtime = module.task_temp_runtime("test-task")
    assert runtime.is_dir()
    assert module.REPO.resolve() not in runtime.parents
    assert module.load_state("test-task")["TASK_TEMP_RUNTIME_STATUS"] == "READY"
    assert all(Path(observed["env"][name]).resolve() == runtime for name in ("TEMP", "TMP", "TMPDIR"))
    source = module._worker_prompt(module.load_state("test-task"))
    assert "Never change ACLs" in source and "icacls/takeown" in source


def test_supervisor_initialization_exception_is_persisted(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state.update({
        "SUPERVISOR_PID": module.os.getpid(),
        "SUPERVISOR_PARENT_PID": 4000,
        "SUPERVISOR_STARTUP_STATUS": "STARTING",
    })
    module._write_state_unlocked("test-task", state)
    real_update = module.update_task
    injected = {"value": False}

    def fail_initialization(*args, **kwargs):
        if kwargs.get("event") == "SUPERVISOR_STARTED" and not injected["value"]:
            injected["value"] = True
            raise RuntimeError("initialization boom")
        return real_update(*args, **kwargs)

    monkeypatch.setattr(module, "update_task", fail_initialization)

    assert module.run_supervisor("test-task", poll_seconds=0) == 1

    failed = module.load_state("test-task")
    assert failed["SUPERVISOR_STARTUP_STATUS"] == "FAILED"
    assert failed["SUPERVISOR_EXIT_CODE"] == 1
    assert failed["SUPERVISOR_EXCEPTION"] == "RuntimeError:initialization boom"
    assert "initialization boom" in failed["SUPERVISOR_STDERR_TAIL"]


def test_supervisor_launch_token_adopts_runtime_pid_without_weakening_duplicate_guard(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    token = "a" * 32
    state.update({
        "HARNESS_STATE": "STOPPED", "SUPERVISOR_PID": 5105,
        "SUPERVISOR_LAUNCH_PID": 5105, "SUPERVISOR_LAUNCH_TOKEN": token,
        "SUPERVISOR_PARENT_PID": 4000, "SUPERVISOR_STARTUP_STATUS": "STARTING",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 5105)

    assert module.run_supervisor("test-task", poll_seconds=0, launch_token=token) == 0

    adopted = module.load_state("test-task")
    assert adopted["SUPERVISOR_LAUNCH_PID"] == 5105
    assert adopted["SUPERVISOR_PID"] == module.os.getpid()
    assert adopted["SUPERVISOR_PARENT_PID"] == module.os.getppid()
    assert adopted["SUPERVISOR_LAUNCH_TOKEN"] == ""
    assert adopted["SUPERVISOR_EXIT_CODE"] == 0
    assert adopted["SUPERVISOR_STARTUP_STATUS"] == "EXITED"
    assert adopted["SUPERVISOR_EXCEPTION"] == ""


def test_supervisor_startup_does_not_spawn_duplicate_and_completed_task_is_unchanged(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    now = module.utc_now()
    state.update({
        "SUPERVISOR_PID": 5104, "SUPERVISOR_STARTED_AT": now,
        "SUPERVISOR_READY_AT": now, "SUPERVISOR_HEARTBEAT_AT": now,
        "SUPERVISOR_STARTUP_STATUS": "READY",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 5104)
    monkeypatch.setattr(
        module.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("duplicate Supervisor spawned")),
    )
    assert module._spawn_supervisor("test-task", startup_timeout=0.1) == 5104

    completed = module.load_state("test-task")
    completed["HARNESS_STATE"] = "COMPLETED"
    completed["TERMINAL_OUTCOME"] = "COMPLETED"
    module._write_state_unlocked("test-task", completed)
    before = module.load_state("test-task")
    after = module.recover_if_interrupted("test-task")
    assert after == before
    assert module._spawn_controller("test-task", startup_timeout=0.1) is None


def test_supervisor_cooperative_stop_wins_recovery_race_cleanly(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state["CONTROLLER_PID"] = 5200
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)

    def stop_during_recovery(task_id: str) -> dict:
        module.update_task(task_id, new_state="STOPPED", event="STOP_REQUESTED")
        raise module.HarnessError("INVALID_STATE_TRANSITION:STOPPED->RUNNING")

    monkeypatch.setattr(module, "recover_if_interrupted", stop_during_recovery)

    assert module.run_supervisor("test-task", poll_seconds=0) == 0
    stopped = module.load_state("test-task")
    assert stopped["HARNESS_STATE"] == "STOPPED"
    assert stopped["SUPERVISOR_STARTUP_STATUS"] == "EXITED"
    assert stopped["SUPERVISOR_EXIT_CODE"] == 0
    assert stopped["SUPERVISOR_EXCEPTION"] == ""


def test_r3_expired_budget_defers_remaining_work_with_continuation_plan() -> None:
    state = module._new_state("test-task", "Finish bounded work", "independent-code", 2, max_hours=1)
    state["WORK_UNITS"] = [
        module._new_work_unit("WU-001", "Required unfinished work"),
        module._new_work_unit("WU-002", "Optional unfinished work", optional=True),
    ]
    state["DEADLINE_AT"] = "2000-01-01T00:00:00+00:00"

    assert module._remaining_budget_seconds(state) == 0
    assert module._defer_for_expired_budget(state) == 2
    assert {unit["status"] for unit in state["WORK_UNITS"]} == {"DEFERRED"}
    assert all("future authorized task" in unit["next_action"] for unit in state["WORK_UNITS"])


def test_r3_hard_deadline_dispatches_no_codex_and_terminalizes(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "SELECT_WORK", "DEADLINE_AT": "2000-01-01T00:00:00+00:00",
        "TIME_BUDGET_HOURS": 1.0,
        "WORK_UNITS": [module._new_work_unit("WU-001", "Required unfinished work")],
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Codex started after deadline")),
    )
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["HARD_DEADLINE_REACHED_AT"]
    assert final["WORK_UNITS"][0]["status"] == "DEFERRED"
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "HARD_DEADLINE_NO_NEW_LLM_WORK"


def test_r3_review_near_deadline_is_deferred_without_expensive_turn(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    done = module._new_work_unit("WU-001", "Complete useful work")
    done["status"] = "DONE"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINAL_REVIEW", "WORK_UNITS": [done],
        "DEADLINE_AT": (module.datetime.now(module.timezone.utc) + module.timedelta(seconds=120)).isoformat(),
        "TIME_BUDGET_HOURS": 1.0,
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(
        module, "_perform_review",
        lambda task_id: (_ for _ in ()).throw(AssertionError("late reviewer started")),
    )
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "stable")
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] in module.TERMINAL_STATES
    assert final["CONVERGENCE_MODE"] is True
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "REVIEW_DEFERRED_INSUFFICIENT_CONVERGENCE_BUDGET"
    assert final["TELEMETRY"]["reviewer_turns"] == 0


def test_r3_no_progress_final_review_is_not_launched_again(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    done = module._new_work_unit("WU-001", "Complete useful work")
    done["status"] = "DONE"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINAL_REVIEW", "WORK_UNITS": [done],
        "LAST_REVIEW_STATUS": "FIX_REQUIRED",
    })
    state["LAST_REVIEW_PROGRESS_HASH"] = module._review_progress_hash(state, "same-diff")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "same-diff")
    monkeypatch.setattr(
        module, "_perform_review",
        lambda task_id: (_ for _ in ()).throw(AssertionError("duplicate reviewer started")),
    )
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] in module.TERMINAL_STATES
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "REVIEW_SKIPPED_NO_MATERIAL_PROGRESS"
    assert final["TELEMETRY"]["repeated_work_prevented"] == 1


def test_r3_incomplete_zero_diff_review_terminalizes_without_correction_loop(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    blocked = module._new_work_unit("WU-001", "Mandatory work with no authorized remedy")
    blocked["status"] = "BLOCKED_LOCAL"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINAL_REVIEW", "WORK_UNITS": [blocked],
    })
    module._write_state_unlocked("test-task", state)
    reviews = {"count": 0}

    def incomplete_review(task_id: str) -> str:
        reviews["count"] += 1
        module.update_task(task_id, {
            "LAST_REVIEW_STATUS": "FIX_REQUIRED",
            "REVIEW_FINDINGS": "Task incomplete: no reviewable output and mandatory work remains blocked.",
        }, new_state="REVIEWING")
        return "FIX_REQUIRED"

    monkeypatch.setattr(module, "_perform_review", incomplete_review)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "zero-diff")
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert reviews["count"] == 1
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "INCOMPLETE_NO_RUNNABLE_REMEDY"
    assert not any(unit["id"].startswith("FIX-") for unit in final["WORK_UNITS"])


def test_atomic_state_replace_retries_transient_windows_access_denial(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    real_replace = module.os.replace
    calls = {"count": 0}

    def transient_replace(source, target):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError(13, "transient sharing violation", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", transient_replace)
    state["CURRENT_ACTION"] = "retry atomic state replace"
    module._write_state_unlocked("test-task", state)

    assert calls["count"] == 2
    assert module.load_state("test-task")["CURRENT_ACTION"] == "retry atomic state replace"
    assert not list(module.task_dir("test-task").glob(".state.json.*.tmp"))


def test_supervisor_remains_watchdog_through_extended_nonterminal_interval(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    state.update({"HARNESS_STATE": "RUNNING", "CONTROLLER_PID": 4242})
    module._write_state_unlocked("test-task", state)
    sleeps = {"count": 0}
    clock = {"value": 0.0}

    def monotonic() -> float:
        clock["value"] += 31.0
        return clock["value"]

    def bounded_sleep(seconds: float) -> None:
        sleeps["count"] += 1
        if sleeps["count"] == 4:
            module.update_task("test-task", new_state="STOPPED", event="SYNTHETIC_TERMINAL")

    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(module.time, "monotonic", monotonic)
    monkeypatch.setattr(module.time, "sleep", bounded_sleep)

    assert module.run_supervisor("test-task", poll_seconds=0) == 0
    final = module.load_state("test-task")
    assert sleeps["count"] == 4
    assert final["HARNESS_STATE"] == "STOPPED"
    assert final["SUPERVISOR_HEARTBEAT_AT"]
    assert final["SUPERVISOR_STARTUP_STATUS"] == "EXITED"
    assert final["SUPERVISOR_EXIT_CODE"] == 0


def test_r3_deterministic_long_task_chaos_scenario_completes_without_human_control(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state(goal="Complete ten bounded independent engineering work units")
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    raw_units = [
        {
            "id": f"WU-{index:03d}",
            "objective": (
                "Repair storage containment parity capability 9"
                if index == 9 else f"Implement bounded subsystem capability {index}"
            ),
            "identity": f"subsystem-capability-{index}",
            "subsystem": "shared",
            "dependencies": ["WU-009"] if index == 10 else [],
            "optional": index == 10,
            "relevant_paths": ["scripts/common/storage_paths.ps1"] if index == 9 else [],
            "reuse_decision": "REUSE" if index == 4 else "EXTEND" if index == 7 else "UNKNOWN",
            "reuse_evidence": ["existing shared utility"] if index in {4, 7} else [],
        }
        for index in range(1, 11)
    ]
    raw_units.append({
        "id": "WU-011", "objective": "Create duplicate wording for capability four",
        "identity": "subsystem capability 4", "subsystem": "shared",
    })
    units, rejected = module._normalize_work_unit_plan(raw_units, state["GOAL"])
    assert len(units) == 10 and rejected == 1
    state.update({
        "HARNESS_STATE": "RUNNING", "CURRENT_PHASE": "AUTONOMOUS_EXECUTION_LOOP",
        "NEXT_ACTION_CODE": "SELECT_WORK", "WORKTREE": str(worktree),
        "WORK_UNITS": units, "OVERFIT_GUARD": "PASS", "ANTI_BLOAT": "PASS",
        "ANTI_BLOAT_TASK_DELTA": "PASS", "REUSE_GUARD": "PASS_SEARCH_RECORDED",
        "REUSE_DISCOVERY_CACHE": module._initial_reuse_cache({
            "filename_matches": ["scripts/existing_shared_utility.py"],
            "semantic_matches": [], "candidate_classifications": [],
        }),
    })
    state["TELEMETRY"]["duplicate_planned_work_rejected"] = rejected
    for phase in ("HARD_PREFLIGHT", "DISCOVER_REUSE", "CREATE_ISOLATED_WORKTREE", "PLAN"):
        module._plan_update(state, phase, "COMPLETED")
    module._write_state_unlocked("test-task", state)

    worker_batches: list[list[str]] = []
    validation_calls = {"unit": 0, "final": 0, "review": 0, "cleanup": 0}

    def result_row(unit_id: str, status: str, *, blocker: dict | None = None) -> dict:
        current = module.load_state("test-task")
        unit = module._unit_by_id(current, unit_id) or {}
        return {
            "id": unit_id, "status": status, "produced_outputs": [f"checkpoint/{unit_id}"],
            "validation_state": "WORKER_CHECKPOINT", "blocker": blocker or {},
            "last_checkpoint": f"TURN_{len(worker_batches) + 1}",
            "next_action": "Retry differently" if status == "RETRY" else "No further action",
            "reuse_decision": unit.get("reuse_decision", "UNKNOWN"),
            "reuse_evidence": unit.get("reuse_evidence", []),
        }

    def worker_turn(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        current = module.load_state(task_id)
        active = list(current["ACTIVE_WORK_UNIT_IDS"])
        worker_batches.append(active)
        turn = len(worker_batches)
        expected = {
            1: ["WU-001", "WU-002", "WU-003"],
            2: ["WU-002", "WU-004", "WU-005"],
            3: ["WU-006", "WU-007", "WU-008"],
            4: ["WU-006", "WU-009"],
            5: ["FIX-001"],
        }
        assert active == expected[turn]
        if turn == 1:
            rows = [
                result_row("WU-001", "DONE"), result_row("WU-002", "RETRY"),
                result_row("WU-003", "DONE"),
            ]
            task_result, exit_code = "SOFTWARE_FAILURE", 1  # worker dies after a safe checkpoint
        elif turn == 2:
            rows = [
                result_row("WU-002", "BLOCKED_LOCAL", blocker={
                    "code": "PATH_NOT_WRITABLE",
                    "detail": "apply_patch write denied for scripts/common/storage_paths.py: PermissionError [WinError 5]",
                }),
                result_row("WU-004", "DONE"),
                result_row("WU-005", "BLOCKED_LOCAL", blocker={
                    "code": "SOURCE_QUOTA_EXHAUSTED", "detail": "Moomoo quota exhausted for this branch",
                }),
            ]
            task_result, exit_code = "BLOCKED", 0
        elif turn == 3:
            rows = [
                result_row("WU-006", "RETRY", blocker={
                    "code": "TARGETED_TEST_FAILURE", "detail": "one focused assertion failed",
                }),
                result_row("WU-007", "DONE"), result_row("WU-008", "DONE"),
            ]
            task_result, exit_code = "COMPLETED", 0
        elif turn == 4:
            rows = [
                result_row("WU-006", "DONE"),
                result_row("WU-009", "BLOCKED_LOCAL", blocker={
                    "code": "FIXABLE_LOCAL_DEFECT", "detail": "storage containment parity remains incomplete",
                }),
            ]
            task_result, exit_code = "COMPLETED", 0
        else:
            rows = [result_row("FIX-001", "DONE")]
            task_result, exit_code = "COMPLETED", 0
        message = (
            f"TASK_RESULT={task_result}\nHOLDOUT_CONTAMINATION_RISK=NONE\n"
            f"WORK_UNIT_RESULTS_JSON={json.dumps(rows, separators=(',', ':'))}\n"
            "CHANGED_PATHS_JSON=[\"scripts/existing_shared_utility.py\"]"
        )
        module.update_task(task_id, {
            "WORKER_FINDINGS": message, "PENDING_UNIT_RESULTS": rows,
            "WORKER_STATUS": f"EXITED_{exit_code}", "WORKER_PID": None,
            "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
            "WORKER_TEST_STATUS": "PASS" if exit_code == 0 else "NOT_RUN",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": exit_code, "message": message, "tests": []}

    def unit_validation(task_id: str) -> tuple[bool, str]:
        validation_calls["unit"] += 1
        return True, "targeted controller validation passed"

    def final_validation(task_id: str) -> tuple[bool, str]:
        validation_calls["final"] += 1
        module.update_task(task_id, {"CONTROLLER_VALIDATION_STATUS": "PASS"})
        return True, "all final machine validation passed"

    def final_review(task_id: str) -> str:
        validation_calls["review"] += 1
        classification = "FIX_REQUIRED"
        findings = (
            "RepoRoot equality remains accepted by scripts/common/storage_paths.ps1; the inherited Anti-Bloat CRLF residue is outside this diff."
            if validation_calls["review"] == 1
            else "Storage resolver parity still permits the repository root as external in scripts/common/storage_paths.ps1. All baseline hashes match Git blobs; that residue is pre-existing."
        )
        module.update_task(task_id, {
            "LAST_REVIEW_STATUS": classification, "REVIEW_FINDINGS": findings,
            "CURRENT_PHASE": "FINAL_INDEPENDENT_REVIEW",
        }, new_state="REVIEWING", event="REVIEW_CLASSIFIED", detail=classification)
        return classification

    def cleanup(task_id: str) -> None:
        validation_calls["cleanup"] += 1

    inventory = {
        "changed": ["scripts/common/storage_paths.ps1"], "created": [],
        "dependencies": [], "changed_count": 1, "created_count": 0,
    }
    monkeypatch.setattr(module, "_run_codex_turn", worker_turn)
    monkeypatch.setattr(module, "_run_unit_validation", unit_validation)
    monkeypatch.setattr(module, "_run_final_validation", final_validation)
    monkeypatch.setattr(module, "_perform_review", final_review)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "stable-progress")
    monkeypatch.setattr(
        module, "_in_convergence_window",
        lambda value, now=None: any(
            unit.get("id") == "FIX-001" and unit.get("status") == "DONE"
            for unit in value.get("WORK_UNITS", [])
        ),
    )
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: inventory)
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", cleanup)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_OUTCOME"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False
    assert validation_calls == {"unit": 5, "final": 2, "review": 2, "cleanup": 1}
    assert len(final["WORK_UNITS"]) == 11
    assert module._work_unit_counts(final) == {
        "total": 11, "done": 8, "runnable": 0, "local_blocked": 2, "deferred": 1,
    }
    assert "WU-001" not in worker_batches[1:] and "WU-003" not in worker_batches[1:]
    assert worker_batches.count(["FIX-001"]) == 1
    assert final["TELEMETRY"]["duplicate_planned_work_rejected"] == 2
    assert final["TELEMETRY"]["reuse_hits"] == 3  # two planned reuse hits plus the in-place correction
    assert final["TELEMETRY"]["local_blockers_bypassed"] == 2
    assert final["TELEMETRY"]["repeated_work_prevented"] == 1
    correction = next(unit for unit in final["WORK_UNITS"] if unit["id"] == "FIX-001")
    assert final["LAST_REVIEW_FINDING_IDENTITY"] == correction["review_finding_identity"]
    convergence_finding = next(
        row for row in final["HISTORICAL_FINDINGS"]
        if row.get("code") == "CONVERGENCE_REVIEW_FINDING"
    )
    assert convergence_finding["identity"] == correction["review_finding_identity"]
    assert not final["ACTIVE_BLOCKERS"]
    assert final["HUMAN_ATTENTION_REQUIRED"] is False
    assert worktree.is_dir()
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert "WORKER_FAILURE_CHECKPOINT_RECOVERED" in events
    assert "FINAL_REVIEW_CORRECTION_GENERATED" in events
    assert "CONVERGENCE_MODE_STARTED" in events
    assert "WAITING_HUMAN" not in events


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
        "NEXT_ACTION_CODE": "FINALIZE", "LAST_REVIEW_STATUS": "PASS",
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


def test_r31_historical_pilot_semantic_replay_reconciles_local_residue(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    blocker = {
        "kind": "LOCAL",
        "conditions": [
            "FAST3 guard reports inherited frozen-baseline identity failures outside this diff",
            "pytest-created task cache is inaccessible and cleanup was rejected before execution",
        ],
    }
    unit = module._new_work_unit("FIX-002", "Complete the reviewed maintenance correction")
    unit.update({
        "status": "BLOCKED_LOCAL",
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": "TASK_TESTS_PASS_GLOBAL_GUARD_FAIL",
        "blocker": blocker,
        "last_checkpoint": "CORRECTION_IMPLEMENTED_AND_FOCUSED_TESTS_PASS",
    })
    local_evidence = {
        "identity": "historical-local-residue", "work_unit_id": "FIX-002",
        "code": "LOCAL_BLOCKER", "detail": str(blocker), "at": module.utc_now(),
    }
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
        "LAST_REVIEW_STATUS": "PASS_WITH_WARNINGS",
        "REVIEW_FINDINGS": "No blocking findings. The residue is local/pre-existing and outputs are complete.",
        "LOCAL_BLOCKED_WORK": [local_evidence],
    })
    module._write_state_unlocked("test-task", state)
    changes = {
        "changed": ["scripts/maintenance/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    }
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: changes)
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    reconciled = final["WORK_UNITS"][0]
    assert final["HARNESS_STATE"] == "COMPLETED"
    assert final["TERMINAL_OUTCOME"] == "COMPLETED"
    assert final["TERMINAL_SUCCESS"] is True
    assert reconciled["status"] == "DONE"
    assert reconciled["blocker"] == blocker
    assert final["LOCAL_BLOCKED_WORK"] == [local_evidence]
    assert final["TELEMETRY"]["local_blockers_bypassed"] == 1


@pytest.mark.parametrize(
    "negative_evidence",
    ["NOT_COMPLETED", "NOT_PASSED", "NOT_IMPLEMENTED", "NOT_VALIDATED", "INCOMPLETE", "FAILED"],
)
def test_r311_substantive_output_rejects_negative_completion_evidence(
    negative_evidence: str,
) -> None:
    unit = module._new_work_unit("WU-001", "Produce one substantive output")
    unit.update({
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": negative_evidence,
    })

    assert module._substantive_output_completed(unit) is False


def test_r31_incomplete_local_environment_work_is_deferred(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete work requiring a locally unavailable source")
    unit.update({
        "status": "BLOCKED_LOCAL", "blocker": {
            "kind": "LOCAL", "conditions": ["Local source outage in the sandbox environment"],
        },
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS", "LAST_REVIEW_STATUS": "PASS_WITH_WARNINGS",
        "REVIEW_FINDINGS": "No blocking findings; the incomplete unit is safely deferable.",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "COMPLETED_WITH_DEFERRED_WORK"
    assert final["WORK_UNITS"][0]["status"] == "DEFERRED"
    assert final["TELEMETRY"]["local_blockers_bypassed"] == 0


def test_r311_optional_blocked_local_does_not_fail_completed_mandatory_work(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    mandatory = module._new_work_unit("WU-001", "Complete the mandatory repair")
    mandatory.update({"status": "DONE", "validation_state": "PASS"})
    optional = module._new_work_unit("WU-002", "Run an optional diagnostic", optional=True)
    optional.update({
        "status": "BLOCKED_LOCAL",
        "blocker": {"code": "OPTIONAL_DIAGNOSTIC_UNAVAILABLE", "detail": "Diagnostic cannot run"},
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [mandatory, optional],
        "CONTROLLER_VALIDATION_STATUS": "PASS", "LAST_REVIEW_STATUS": "PASS_WITH_WARNINGS",
        "REVIEW_FINDINGS": "No blocking findings; the optional diagnostic remains unavailable.",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "COMPLETED_WITH_DEFERRED_WORK"
    assert final["TERMINAL_SUCCESS"] is True
    assert final["WORK_UNITS"][0]["status"] == "DONE"
    assert final["WORK_UNITS"][1]["status"] == "BLOCKED_LOCAL"


@pytest.mark.parametrize(
    ("controller", "review", "validation_state", "blocker"),
    [
        ("FAIL", "PASS_WITH_WARNINGS", "TASK_TESTS_PASS", {"kind": "LOCAL", "conditions": ["sandbox access denied"]}),
        ("PASS", "FIX_REQUIRED", "TASK_TESTS_PASS", {"kind": "LOCAL", "conditions": ["sandbox access denied"]}),
        ("PASS", "PASS", "INVALID_REQUIRED_OUTPUT", {"kind": "LOCAL", "conditions": ["sandbox access denied"]}),
        ("PASS", "PASS", "NOT_RUN", {"code": "FIXABLE_LOCAL_DEFECT", "detail": "task-caused defect remains incomplete"}),
    ],
)
def test_r31_terminal_reconciliation_keeps_real_failures_failed(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
    controller: str, review: str, validation_state: str, blocker: dict,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Required output must be valid")
    unit.update({
        "status": "BLOCKED_LOCAL", "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": validation_state, "blocker": blocker,
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": controller, "LAST_REVIEW_STATUS": review,
        "REVIEW_FINDINGS": "Blocking finding remains." if review == "FIX_REQUIRED" else "No blocking findings.",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["WORK_UNITS"][0]["status"] == "BLOCKED_LOCAL"


def test_unwritable_task_temp_runtime_is_scoped_blocker_before_worker_launch(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = use_r2_compat_state(create_state())
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
    "goal",
    [
        "No later-dated outcome, return, label, forward/shadow ledger, evaluation result or strategy performance may be read or used.",
        "No 2026 outcomes may be used.",
        "Do not evaluate later-period performance.",
        "Later-period evaluation is a separate future task.",
        "Post-2025 outcomes are forbidden.",
        "pre2026-research",
        "evaluation",
    ],
)
def test_negated_or_deferred_future_language_is_not_positive_evaluation_evidence(goal: str) -> None:
    evidence = module._task_scope_evidence(goal)
    assert evidence["EVALUATES_2026_OR_HOLDOUT"] is False
    assert module.infer_scope(goal, "independent-code") != "2026-evaluation"


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
    for phase in ("HARD_PREFLIGHT", "DISCOVER_REUSE", "CREATE_ISOLATED_WORKTREE", "PLAN"):
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
    assert checkpoint["PROGRESS_SUMMARY"] == "4/8 plan steps completed; AUTONOMOUS_EXECUTION_LOOP in progress"
    assert len(checkpoint["FILES_CHANGED"]) == 2

    module._record_worker_checkpoint("test-task", "SELF_REVIEW")
    checkpoint = module.load_state("test-task")
    assert checkpoint["CURRENT_PHASE"] == "SELF_REVIEW"
    assert checkpoint["LAST_COMPLETED"] == "WORKER_SELF_REVIEW_CHECKPOINT"
    assert checkpoint["PROGRESS_SUMMARY"] == "4/8 plan steps completed; AUTONOMOUS_EXECUTION_LOOP in progress"

    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))
    assert module.command_status(argparse.Namespace(task_id="test-task")) == 0
    output = capsys.readouterr().out
    assert "PROGRESS_SUMMARY=4/8 plan steps completed; AUTONOMOUS_EXECUTION_LOOP in progress" in output
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
    for phase in ("HARD_PREFLIGHT", "DISCOVER_REUSE", "CREATE_ISOLATED_WORKTREE", "PLAN"):
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
    assert started["CURRENT_PHASE"] == "AUTONOMOUS_EXECUTION_LOOP"
    assert "active" in started["CURRENT_ACTION"]
    assert started["NEXT_ACTION"] == "Complete the Codex worker turn"
    assert started["PROGRESS_SUMMARY"] == "4/8 plan steps completed; AUTONOMOUS_EXECUTION_LOOP in progress"
    assert started["WORKER_STATUS"] == "RUNNING"
    assert started["TEST_HISTORY_START_INDEX"] == 1

    completed = module.load_state("test-task")
    assert completed["CURRENT_PHASE"] == "AUTONOMOUS_EXECUTION_LOOP"
    assert "completed" in completed["CURRENT_ACTION"] and "active" not in completed["CURRENT_ACTION"]
    assert completed["LAST_COMPLETED"] == "WORKER_TURN_COMPLETED"
    assert completed["NEXT_ACTION"] == "Classify the completed worker result"
    assert completed["PROGRESS_SUMMARY"] == "4/8 plan steps completed; AUTONOMOUS_EXECUTION_LOOP in progress"
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
    state = use_r2_compat_state(create_state())
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
    state = use_r2_compat_state(create_state())
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
    for phase in (
        "HARD_PREFLIGHT", "DISCOVER_REUSE", "CREATE_ISOLATED_WORKTREE", "PLAN",
        "AUTONOMOUS_EXECUTION_LOOP", "FINAL_VALIDATION",
    ):
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
    assert started["CURRENT_PHASE"] == "FINAL_INDEPENDENT_REVIEW"
    assert started["WORKER_STATUS"] == "REVIEW_STARTING"
    assert started["PROGRESS_SUMMARY"] == "6/8 plan steps completed; FINAL_INDEPENDENT_REVIEW in progress"
    assert started["NEXT_ACTION"] == "Complete and classify the independent review"
    assert started["FILES_CHANGED"] == ["reviewed.py"]

    reviewed = module.load_state("test-task")
    assert reviewed["CURRENT_ACTION"] == "Independent review completed with PASS"
    assert reviewed["LAST_COMPLETED"] == "INDEPENDENT_REVIEW_COMPLETED"
    assert reviewed["NEXT_ACTION"] == "Finalize and preserve the reviewed worktree"
    assert reviewed["PROGRESS_SUMMARY"] == "7/8 plan steps completed"
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
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: 4242)
    assert module.command_resume(argparse.Namespace(task_id="test-task", foreground=False)) == 0
    resumed = module.load_state("test-task")
    assert resumed["HARNESS_STATE"] == "PLANNING"
    assert resumed["NEXT_ACTION_CODE"] == "HARD_PREFLIGHT"
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
        "Use 2026 returns\nto select the best model.",
        'The instruction is "use 2026 outcomes to train a model".',
    ],
)
def test_hard_guard_detects_unsafe_2026_feedback_actions(goal: str) -> None:
    assert module.hard_guard_conflicts(goal) == ["EXPOSED_2026_OPTIMIZATION"]


def test_hard_guard_allows_explicitly_negated_2026_training_and_tuning() -> None:
    assert module.hard_guard_conflicts("Do not use 2026 outcomes to train or tune the model.") == []


def test_ambiguous_real_training_request_fails_closed() -> None:
    assert module.hard_guard_conflicts("Train a model.") == ["AMBIGUOUS_TRAINING_TEMPORAL_SCOPE"]


def _explicit_legal_temporal_contract(action: str = "Train and select the model.") -> str:
    return f"""{action}
TRAINING_SELECTION_OUTCOME_CUTOFF=2025-12-31.
All features and observations must be PIT-safe with no lookahead at each decision timestamp.
A training observation is legal only when its complete forward label has matured by the cutoff.
Post-cutoff outcomes and performance are forbidden for fitting, tuning, feature selection,
model selection, finalist selection, and strategy selection.
"""


REAL_PRE2026_DISCOVERY_GOAL = """TASK=A2_OPEN_ML_DISCOVERY_R1

Train and select candidate models using only the legal pre-cutoff inputs.

TRAINING_SELECTION_OUTCOME_CUTOFF=2025-12-31
FEATURE_ASOF_CUTOFF=2025-12-31
LABEL_REALIZATION_CUTOFF=2025-12-31
OUTCOME_CUTOFF=2025-12-31

Every input must be PIT-available at decision time.
Every complete forward label must be realized by 2025-12-31.
Late-2025 samples whose label matures later or crosses the cutoff are excluded.
No later-dated outcome, return, label, forward/shadow ledger, evaluation result or strategy performance may be read or used, even diagnostically.

This task ends after finalists are frozen.
Any later-period evaluation is a separate future task.
Do not evaluate later-period performance in this task.
Use chronological expanding/rolling validation.
Algorithm family is unrestricted.
FINAL TRAINING / FREEZE
"""


@pytest.fixture
def local_persisted_start_roots(monkeypatch: pytest.MonkeyPatch):
    token = hashlib.sha256(str(id(monkeypatch)).encode("ascii")).hexdigest()[:12]
    root = (REPOSITORY_ROOT / f".harness-real-goal-test-{token}").resolve()
    assert root.parent == REPOSITORY_ROOT
    root.mkdir()
    try:
        repository = root / "primary-repository"
        repository.mkdir()
        monkeypatch.setattr(module, "REPO", repository)
        monkeypatch.setenv("USTQ_HARNESS_STATE_ROOT", str(root / "daily" / "harness_r2"))
        monkeypatch.setenv("USTQ_HARNESS_WORKTREE_ROOT", str(root / "worktrees"))
        yield root
    finally:
        assert root.parent == REPOSITORY_ROOT
        shutil.rmtree(root)


def test_real_goal_start_and_preflight_persist_legal_pre2026_contract(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = module.build_parser().parse_args([
        "start", "--task-id", "real-goal", "--goal", REAL_PRE2026_DISCOVERY_GOAL,
        "--task-kind", "pre2026-research", "--max-hours", "8",
    ])
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: 4242)

    assert module.command_start(args) == 0
    stored = module.load_state("real-goal")
    assert stored["TASK_KIND"] == "pre2026-research"
    assert stored["TASK_KIND_SOURCE"] == "EXPLICIT"
    assert stored["AUTO_SCOPE_SUGGESTION"] == "pre2026-research"
    assert stored["TASK_SCOPE"] == "pre2026-research"
    assert stored["SAFETY_FLAGS"]["EVALUATES_2026_OR_HOLDOUT"] is False
    assert stored["SAFETY_FLAGS"]["EXPOSED_2026_OR_HOLDOUT_OPTIMIZATION"] is False
    assert "AMBIGUOUS_TRAINING_TEMPORAL_SCOPE" not in module.hard_guard_conflicts(
        REAL_PRE2026_DISCOVERY_GOAL,
    )

    observed_scopes: list[str] = []

    class PassingR1:
        @staticmethod
        def run_preflight(repo: Path, task_scope: str) -> dict:
            observed_scopes.append(task_scope)
            return {
                "task_scope": task_scope,
                "applicable_hard_blocker_count": 0,
                "preflight_status": "PASS",
                "findings": [
                    {
                        "level": "PASS",
                        "code": "ANTI_BLOAT_BUDGET",
                        "detail": "worktree_bytes=100;preferred=PASS;local_venv=False",
                        "blocks": (),
                    },
                ],
            }

    monkeypatch.setattr(module, "_load_r1", lambda: PassingR1)
    preflight = module._run_preflight_for("real-goal", module.REPO)
    assert observed_scopes == ["pre2026-research"]
    assert preflight["task_blocker_count"] == 0


def test_real_goal_start_still_blocks_explicit_2026_model_selection(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_goal = REAL_PRE2026_DISCOVERY_GOAL + "\nUse 2026 returns to select the best model."
    args = module.build_parser().parse_args([
        "start", "--task-id", "unsafe-real-goal", "--goal", unsafe_goal,
        "--task-kind", "pre2026-research", "--max-hours", "8",
    ])
    monkeypatch.setattr(
        module,
        "_spawn_supervisor",
        lambda task_id: pytest.fail("unsafe task must block before supervisor dispatch"),
    )

    assert module.command_start(args) == 2
    stored = module.load_state("unsafe-real-goal")
    assert stored["HARNESS_STATE"] == "BLOCKED"
    assert stored["AUTO_SCOPE_SUGGESTION"] == "2026-evaluation"
    assert stored["TASK_SCOPE"] == "2026-optimization"
    assert stored["SAFETY_FLAGS"]["EVALUATES_2026_OR_HOLDOUT"] is True
    assert stored["SAFETY_FLAGS"]["EXPOSED_2026_OR_HOLDOUT_OPTIMIZATION"] is True
    assert "EXPOSED_2026_OPTIMIZATION" in module.hard_guard_conflicts(unsafe_goal)


@pytest.mark.parametrize("cutoff", ["2025-12-31", "2024-06-30"])
def test_explicit_legal_iso_training_cutoff_contract_is_unambiguous(cutoff: str) -> None:
    goal = _explicit_legal_temporal_contract().replace("2025-12-31", cutoff)
    assert module.hard_guard_conflicts(goal) == []


def test_forward_label_maturity_by_explicit_cutoff_is_legal() -> None:
    goal = _explicit_legal_temporal_contract("Fit the model and choose finalists.")
    assert "complete forward label has matured by the cutoff" in goal
    assert module.hard_guard_conflicts(goal) == []


@pytest.mark.parametrize(
    "goal",
    [
        "Train a model. TRAINING_SELECTION_CUTOFF=2025-12-31.",
        "Train a model. Do not train on later data.",
        _explicit_legal_temporal_contract().replace(
            "Post-cutoff outcomes and performance are forbidden for fitting, tuning, feature selection,\n"
            "model selection, finalist selection, and strategy selection.",
            "Post-cutoff outcomes are forbidden for reporting.",
        ),
    ],
)
def test_incomplete_or_negated_later_data_language_does_not_authorize_training(goal: str) -> None:
    assert "AMBIGUOUS_TRAINING_TEMPORAL_SCOPE" in module.hard_guard_conflicts(goal)


@pytest.mark.parametrize(
    "goal",
    [
        _explicit_legal_temporal_contract().replace("2025-12-31", "2026-01-15", 1),
        _explicit_legal_temporal_contract()
        + " Training may also use outcomes through 2026-01-15.",
        _explicit_legal_temporal_contract()
        + " Post-cutoff outcomes may be used to tune model selection.",
        _explicit_legal_temporal_contract()
        + " PIT-safe and no-lookahead constraints are not required.",
        _explicit_legal_temporal_contract()
        + " Forward labels may mature after the cutoff.",
        "Use the exposed 2026 holdout performance to select model hyperparameters.",
        "Inspect the 2026 holdout, then tune the model threshold.",
    ],
)
def test_post_cutoff_or_holdout_informed_optimization_remains_blocked(goal: str) -> None:
    assert module.hard_guard_conflicts(goal)


def test_contradictory_training_cutoffs_remain_blocked() -> None:
    goal = _explicit_legal_temporal_contract() + " OUTCOME_CUTOFF=2026-02-01 for model selection."
    assert module.hard_guard_conflicts(goal)


def _temporally_incomplete_training_goal() -> str:
    return """Train and select the model.
TRAINING_SELECTION_OUTCOME_CUTOFF=2025-12-31.
All features and observations must be PIT-safe with no lookahead at each decision timestamp.
Post-cutoff outcomes and performance are forbidden for fitting, tuning, feature selection,
model selection, finalist selection, and strategy selection.
"""


def _safe_label_maturity_steering() -> str:
    return """FEATURE_ASOF_CUTOFF=2025-12-31.
LABEL_REALIZATION_CUTOFF=2025-12-31.
OUTCOME_CUTOFF=2025-12-31.
A training observation is legal only when its complete forward label has matured by the cutoff.
""".strip()


def _create_temporally_blocked_state(goal: str | None = None) -> dict:
    goal = goal or _temporally_incomplete_training_goal()
    assert module.hard_guard_conflicts(goal) == ["AMBIGUOUS_TRAINING_TEMPORAL_SCOPE"]
    contract = module._task_contract(goal, "pre2026-research", "pre2026-research")
    state = module._new_state("test-task", goal, contract["TASK_SCOPE"], 2, contract)
    module.task_dir("test-task").mkdir(parents=True)
    module._write_state_unlocked("test-task", state)
    module._append_event_unlocked("test-task", "TASK_ACCEPTED", "test")
    module._set_current_task("test-task")
    module._block(
        "test-task", "HARD_GUARD_CONFLICT", "AMBIGUOUS_TRAINING_TEMPORAL_SCOPE",
    )
    return module.load_state("test-task")


def test_blocked_safe_temporal_steer_revalidates_before_resume(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_temporally_blocked_state()
    monkeypatch.setattr(module, "_queue_control", lambda state, message: (False, "retained"))
    steering = _safe_label_maturity_steering()
    assert module.command_steer(
        argparse.Namespace(task_id="test-task", instruction=steering),
    ) == 0
    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: 4242)

    assert module.command_resume(argparse.Namespace(task_id="test-task", foreground=False)) == 0

    resumed = module.load_state("test-task")
    assert resumed["HARNESS_STATE"] == "PLANNING"
    assert resumed["NEXT_ACTION_CODE"] == "HARD_PREFLIGHT"
    assert resumed["PENDING_STEER"] == [steering]
    assert resumed["STEERING_HISTORY"][-1]["accepted"] is True
    assert resumed["STEERING_HISTORY"][-1].get("applied") is not True
    assert not any(
        row["code"] == "HARD_GUARD_CONFLICT" for row in resumed["ACTIVE_BLOCKERS"]
    )
    assert any(
        row["code"] == "HARD_GUARD_CONFLICT" for row in resumed["BLOCKERS"]
    )


def test_blocked_unsafe_temporal_steer_keeps_resume_fail_closed(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_temporally_blocked_state()
    monkeypatch.setattr(module, "_queue_control", lambda state, message: (False, "retained"))
    steering = "Clarification: OUTCOME_CUTOFF=2026-01-15."
    assert module.command_steer(
        argparse.Namespace(task_id="test-task", instruction=steering),
    ) == 0
    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))

    with pytest.raises(module.HarnessError, match="RESUME_REJECTED_UNRESOLVED_HARD_INVARIANT"):
        module.command_resume(argparse.Namespace(task_id="test-task", foreground=False))

    blocked = module.load_state("test-task")
    assert blocked["HARNESS_STATE"] == "BLOCKED"
    assert blocked["PENDING_STEER"] == [steering]
    assert any(
        row["code"] == "HARD_GUARD_CONFLICT" for row in blocked["ACTIVE_BLOCKERS"]
    )


def test_temporal_revalidation_does_not_clear_unrelated_hard_blocker(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _create_temporally_blocked_state()
    module._append_active_blocker(
        state, "R1_PREFLIGHT_APPLICABLE_HARD_BLOCKER", "FROZEN_ASSET_UNAVAILABLE", "SAFETY",
    )
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_queue_control", lambda value, message: (False, "retained"))
    steering = _safe_label_maturity_steering()
    assert module.command_steer(
        argparse.Namespace(task_id="test-task", instruction=steering),
    ) == 0
    monkeypatch.setattr(module, "recover_if_interrupted", lambda task_id: module.load_state(task_id))

    with pytest.raises(module.HarnessError, match="RESUME_REJECTED_UNRESOLVED_HARD_INVARIANT"):
        module.command_resume(argparse.Namespace(task_id="test-task", foreground=False))

    blocked = module.load_state("test-task")
    assert any(
        row["code"] == "R1_PREFLIGHT_APPLICABLE_HARD_BLOCKER"
        for row in blocked["ACTIVE_BLOCKERS"]
    )


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
    state = use_r2_compat_state(create_state())
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


@pytest.mark.parametrize("controller_passes", [True, False])
def test_r3_environment_limited_worker_uses_authoritative_controller_without_retry_budget(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
    controller_passes: bool,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Repair the focused implementation")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree),
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "ACTIVE_WORK_UNIT_ID": "WU-001", "OVERFIT_GUARD": "PASS", "ANTI_BLOAT": "PASS",
        "REUSE_GUARD": "PASS_SEARCH_RECORDED", "WORKTREE_INVENTORY_STATUS": "KNOWN",
    })
    module._write_state_unlocked("test-task", state)

    def environment_limited(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        module.update_task(task_id, {
            "WORKER_FINDINGS": "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE",
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_TEST_EVIDENCE": KNOWN_NESTED_PYTEST_TEMP_FAILURE,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": "environment limited", "tests": []}

    def controller_validation(task_id: str) -> tuple[bool, str]:
        module.update_task(task_id, {
            "CONTROLLER_VALIDATION_STATUS": "PASS" if controller_passes else "FAIL",
            "STOP_REQUESTED": True,
        })
        return controller_passes, "controller validation result"

    monkeypatch.setattr(module, "_run_codex_turn", environment_limited)
    monkeypatch.setattr(module, "_run_unit_validation", controller_validation)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "same-progress")

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "STOPPED"
    assert final["CORRECTION_ATTEMPTS"] == 0
    assert final["WORK_UNITS"][0]["status"] == ("DONE" if controller_passes else "RETRY")
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("WORKER_TEST_ENVIRONMENT_LIMITATION_DELEGATED") == 1
    if controller_passes:
        assert final["RETRY_LEDGER"] == {}
        assert not final["WORK_UNITS"][0]["retry_history"]
    else:
        assert len(final["RETRY_LEDGER"]) == 1


def test_r3_live_worker_identity_prevents_redispatch_without_waiting_human(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Repair one implementation")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree),
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
    })
    module._write_state_unlocked("test-task", state)

    def orphaned(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        module.update_task(task_id, {
            "WORKER_FINDINGS": "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE",
            "WORKER_PID": 4242, "ACTIVE_THREAD_ID": "thread-live",
            "ACTIVE_PROCESS_KIND": "WORKER", "WORKER_STATUS": "RUNNING",
        })
        return {"exit_code": 1, "message": "controller lost worker handoff", "tests": []}

    validated = {"called": False}
    monkeypatch.setattr(module, "_run_codex_turn", orphaned)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(
        module, "_run_unit_validation",
        lambda task_id: (validated.update(called=True) or True, "unexpected"),
    )
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "same-progress")

    module._dispatch("test-task")

    current = module.load_state("test-task")
    assert validated["called"] is False
    assert current["HARNESS_STATE"] == "RUNNING"
    assert current["CURRENT_PHASE"] == "AUTOMATIC_RECOVERY"
    assert current["WORKER_STATUS"] == "ORPHANED_RUNNING"
    assert current["WORKER_PID"] == 4242
    assert current["HUMAN_ATTENTION_REQUIRED"] is False


def test_real_worker_test_failure_uses_correction_path(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = use_r2_compat_state(create_state())
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
    state = use_r2_compat_state(create_state())
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
    state = use_r2_compat_state(create_state())
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
    unit = module._new_work_unit("WU-001", "Repair the interrupted implementation")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998,
        "ACTIVE_PROCESS_KIND": "WORKER",
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "CURRENT_PHASE": "TARGETED_TEST", "CURRENT_ACTION": "Running targeted tests",
        "LAST_COMPLETED": "IMPLEMENTATION_WORKER_EXITED", "NEXT_ACTION": "Review the test result",
    })
    module._plan_update(state, "TARGETED_TEST", "IN_PROGRESS")
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {"changed": ["useful.py"], "created": ["useful.py"], "dependencies": []})
    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "RUNNING"
    assert recovered["CURRENT_PHASE"] == "AUTOMATIC_RECOVERY"
    assert "persisted R3 checkpoint" in recovered["CURRENT_ACTION"]
    assert "Both recorded processes are inactive" in recovered["WHY_CURRENT_ACTION"]
    assert recovered["LAST_COMPLETED"] == "IMPLEMENTATION_WORKER_EXITED"
    assert recovered["LAST_CHECKPOINT"] == "AUTOMATIC_CRASH_RECOVERY:SELECT_WORK"
    assert recovered["NEXT_ACTION"] == "Continue automatically at SELECT_WORK"
    assert "never rerun" in recovered["WHY_NEXT_ACTION"]
    assert "TARGETED_TEST in progress" not in recovered["PROGRESS_SUMMARY"]
    assert recovered["FILES_CHANGED"] == ["useful.py"]
    assert recovered["WORKER_STATUS"] == "AUTOMATIC_CRASH_RECOVERY_PENDING"
    assert recovered["HUMAN_ATTENTION_REQUIRED"] is False
    assert recovered["TELEMETRY"]["crash_recoveries"] == 1
    assert recovered["WORK_UNITS"][0]["status"] == "RETRY"
    assert recovered["WORK_UNITS"][0]["last_checkpoint"] == "WORKER_INTERRUPTED_WITH_CHANGES"


def test_crash_recovery_validates_only_a_persisted_structured_checkpoint(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete checkpointed implementation")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "CONTROLLER_PID": 999_999, "WORKER_PID": 999_998,
        "ACTIVE_PROCESS_KIND": "WORKER", "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"], "ACTIVE_WORK_UNIT_ID": "WU-001",
        "PENDING_UNIT_RESULTS": [{"id": "WU-001", "status": "DONE"}],
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["checkpointed.py"], "created": [], "dependencies": [],
    })

    recovered = module.recover_if_interrupted("test-task")

    assert recovered["NEXT_ACTION_CODE"] == "UNIT_VALIDATE"
    assert recovered["WORK_UNITS"][0]["status"] == "RUNNING"
    assert recovered["ACTIVE_WORK_UNIT_IDS"] == ["WU-001"]


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
        "ACTIVE_PROCESS_KIND": "WORKER",
        "CURRENT_PHASE": "IMPLEMENT", "CURRENT_ACTION": "Worker is active",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })

    recovered = module.recover_if_interrupted("test-task")
    assert recovered["HARNESS_STATE"] == "RUNNING"
    assert recovered["CURRENT_PHASE"] == "AUTOMATIC_RECOVERY"
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
    assert failed["HARNESS_STATE"] == "RUNNING"
    assert failed["CURRENT_PHASE"] == "AUTOMATIC_RECOVERY"
    assert failed["CURRENT_ACTION"] == "Controller failed; supervisor restart is pending"
    assert failed["WHY_CURRENT_ACTION"] == "RuntimeError:controller lost"
    assert failed["LAST_COMPLETED"] == "IMPLEMENTATION_WORKER_EXITED"
    assert failed["NEXT_ACTION"] == "Supervisor starts one replacement controller from persisted state"
    assert "prevent duplicate" in failed["WHY_NEXT_ACTION"]
    assert "TARGETED_TEST in progress" not in failed["PROGRESS_SUMMARY"]
    assert failed["WORKER_STATUS"] == "CONTROLLER_RECOVERY_PENDING"
    assert failed["FILES_CHANGED"] == ["preserved.py"]
    assert failed["HUMAN_ATTENTION_REQUIRED"] is False


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
    assert orphaned["HARNESS_STATE"] == "RUNNING"
    assert orphaned["CURRENT_PHASE"] == "AUTOMATIC_RECOVERY"
    assert orphaned["WORKER_STATUS"] == "ORPHANED_RUNNING"
    assert orphaned["WORKER_PID"] == 4242
    assert orphaned["ACTIVE_THREAD_ID"] == "thread-live"
    assert orphaned["ACTIVE_PROCESS_KIND"] == "WORKER"
    assert orphaned["HUMAN_ATTENTION_REQUIRED"] is False
    assert "waits for the recorded worker" in orphaned["NEXT_ACTION"]
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
