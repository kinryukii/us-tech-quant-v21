from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
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
    "PROSPECTIVE_LIFECYCLE_APPLICABILITY", "RESEARCH_SPEC_PATH",
    "RESEARCH_SPEC_SHA256", "PROSPECTIVE_RESEARCH_ID", "RESEARCH_TASK_ROOT",
    "RESEARCH_START_DECISION",
    "RESEARCH_MECHANISM_KEY", "RESEARCH_REGISTRY_HEAD_AT_START", "MATCHED_PRIOR_BRANCH",
    "PRIOR_RESEARCH_STATUS",
    "PRIOR_RESEARCH_CONCLUSION", "REOPEN_CONDITION", "REOPEN_JUSTIFICATION",
    "REGISTRY_COMPLETION_STATUS", "REGISTRY_COMPLETION_HEAD_SHA256",
    "RETENTION_MANIFEST_STATUS", "RETENTION_MANIFEST_PATH", "RETENTION_MANIFEST_SHA256",
    "RETENTION_BUDGET",
    "HOST_CLEANUP_STATUS", "HOST_CLEANUP_RECLAIMED_BYTES",
    "HOST_CLEANUP_DEFERRED_ALLOWLIST", "HOST_CLEANUP_DEFERRED_ALLOWLIST_PATH",
    "WORKTREE_RETIREMENT_STATUS", "WORKTREE_RETIREMENT_REASON", "FINAL_REVIEWER_ID",
    "TASK_TEMP_RUNTIME", "TASK_TEMP_RUNTIME_STATUS", "TASK_TEMP_RUNTIME_OWNED",
    "TASK_TEMP_RUNTIME_CLEANUP_STATUS",
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
    "TERMINAL_REASON", "PENDING_AUTONOMOUS_CONTINUATION",
    "STATE_STORAGE_STATUS", "STATE_STORAGE_FAILURE", "STATE_BYTES_LAST_WRITE",
    "STATE_TEXT_ARCHIVES", "COMPACTED_HISTORY_IDENTITIES",
    "START_REPO_HEAD", "START_REPO_TOPLEVEL", "WORKTREE_BASE_HEAD",
    "WORKTREE_ACTUAL_HEAD", "BASE_HEAD_IDENTITY_STATUS",
    "WORKER_COMPLETION_EVIDENCE", "REVIEW_AUTHORITY_EVIDENCE",
    "REVIEW_CLASSIFICATION",
}


@pytest.fixture
def isolated_roots(monkeypatch: pytest.MonkeyPatch):
    external_parent = Path(tempfile.gettempdir()).resolve()
    assert external_parent != REPOSITORY_ROOT and REPOSITORY_ROOT not in external_parent.parents
    root = (external_parent / f"h-{uuid.uuid4().hex}").resolve()
    root.mkdir()
    try:
        assert root.parent == external_parent
        assert root != REPOSITORY_ROOT and REPOSITORY_ROOT not in root.parents
        repository = root / "primary-repository"
        repository.mkdir()
        state = root / "daily" / "harness_r2"
        worktrees = root / "worktrees"
        monkeypatch.setattr(module, "REPO", repository)
        monkeypatch.setattr(
            module, "_capture_start_repo_identity",
            lambda: ("e" * 40, str(repository.resolve())),
        )
        monkeypatch.setenv("USTQ_HARNESS_STATE_ROOT", str(state))
        monkeypatch.setenv("USTQ_HARNESS_WORKTREE_ROOT", str(worktrees))
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


def record_fake_review(
    task_id: str, status: str, findings: str, **extra_fields: object,
) -> str:
    """Persist the same canonical receipt that a real read-only review turn emits."""
    fields = canonical_review_fields(module.load_state(task_id), status, findings)
    classification = str(fields["REVIEW_CLASSIFICATION"])
    module.update_task(task_id, {
        **fields,
        **extra_fields,
    }, new_state="REVIEWING", event="SYNTHETIC_REVIEW_CLASSIFIED",
        detail=classification)
    return classification


def canonical_review_fields(state: dict, status: str, findings: str) -> dict:
    """Build the persisted fields emitted from one complete reviewer message."""
    authoritative_message = f"{findings}\nREVIEW_STATUS={status}"
    evidence = module._ingest_review_authority_evidence(
        state, authoritative_message,
    )
    classification = module._review_classification_with_authority(
        module._review_classification(authoritative_message, 0), evidence,
    )
    evidence["classification"] = classification
    return {
        "LAST_REVIEW_STATUS": classification,
        "REVIEW_FINDINGS": authoritative_message[-module.MAX_TEXT:],
        "REVIEW_AUTHORITY_EVIDENCE": evidence,
        "REVIEW_CLASSIFICATION": classification,
    }


def stale_bounded_blocking_review_fields(state: dict) -> dict:
    """Model a persisted pre-repair PASS whose display tail lost its blocker."""
    authoritative_message = (
        "Blocking finding: duplicate component exists.\n"
        + "x" * 9_000
        + "\nREVIEW_STATUS=PASS"
    )
    evidence = module._ingest_review_authority_evidence(state, authoritative_message)
    evidence["classification"] = "PASS"
    return {
        "LAST_REVIEW_STATUS": "PASS",
        "REVIEW_FINDINGS": authoritative_message[-module.MAX_TEXT:],
        "REVIEW_AUTHORITY_EVIDENCE": evidence,
        "REVIEW_CLASSIFICATION": "PASS",
    }


def use_supervisor_test_storage(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> argparse.Namespace:
    """Keep synthetic storage roots sibling to, never above, the worktree fixture."""
    base = isolated_roots[0].parents[1]
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
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
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


def test_r9_persistence_cannot_create_done_authority_or_dispatch_dependent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    checkpoint = (
        "COMPLETED " + ("A" * 300) + " RETRY " + ("B" * 300) + " VALIDATED"
    )
    dependency = module._new_work_unit("WU-001", "Complete the prerequisite")
    dependency.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": checkpoint, "next_action": "No further action",
    })
    dependent = module._new_work_unit(
        "WU-002", "Run only after the prerequisite", dependencies=["WU-001"],
    )

    assert module._done_worker_result_terminal(dependency) is False
    module.update_task("test-task", {
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "SELECT_WORK", "WORK_UNITS": [dependency, dependent],
    })
    persisted = module.load_state("test-task")
    persisted_dependency = module._unit_by_id(persisted, "WU-001")
    persisted_dependent = module._unit_by_id(persisted, "WU-002")

    assert persisted_dependency is not None and persisted_dependent is not None
    assert persisted_dependency["last_checkpoint"] == checkpoint
    assert "state_compacted" not in persisted_dependency
    assert module._done_worker_result_terminal(persisted_dependency) is False
    assert module._work_unit_counts(persisted)["done"] == 0
    assert module._dependency_satisfied(persisted_dependency) is False
    assert module._runnable_work_units(persisted) == []

    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "p0")
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("worker dispatch crossed a noncanonical dependency")
        ),
    )

    def stop_after_selection(task_id: str) -> tuple[bool, str]:
        raise RuntimeError("STOP_AFTER_R9_SELECTION")

    monkeypatch.setattr(module, "_run_final_validation", stop_after_selection)
    with pytest.raises(RuntimeError, match="STOP_AFTER_R9_SELECTION"):
        module._dispatch("test-task")

    persisted = module.load_state("test-task")
    assert module._unit_by_id(persisted, "WU-002")["status"] == "READY"
    assert module._unit_by_id(persisted, "WU-002")["attempts"] == 0
    assert persisted["ACTIVE_WORK_UNIT_IDS"] == []
    assert persisted["NEXT_ACTION_CODE"] == "FINAL_VALIDATION"


def _r9_positioned_authority_text(
    disqualifier: str, position: str, padding: int,
) -> str:
    left = "A" * padding
    right = "B" * padding
    parts = {
        "head": (disqualifier, "COMPLETED", left, right, "VALIDATED"),
        "middle": ("COMPLETED", left, disqualifier, right, "VALIDATED"),
        "tail": ("COMPLETED", left, right, "VALIDATED", disqualifier),
    }
    return " ".join(parts[position])


@pytest.mark.parametrize("authority_field", ["last_checkpoint", "next_action"])
@pytest.mark.parametrize(
    ("disqualifier", "position", "padding"),
    [
        (disqualifier, position, padding)
        for disqualifier in (
            "RETRY", "WAITING", "RUNNING", "IN_PROGRESS", "WORK_REMAINS",
        )
        for position, padding in (
            ("head", 64), ("middle", 96), ("tail", 300),
        )
    ],
)
def test_r9_authority_fields_are_lossless_across_thresholds_and_positions(
    isolated_roots: tuple[Path, Path],
    authority_field: str,
    disqualifier: str,
    position: str,
    padding: int,
) -> None:
    state = create_state()
    authority_text = _r9_positioned_authority_text(
        disqualifier, position, padding,
    )
    unit = module._new_work_unit("WU-001", "Preserve canonical DONE authority")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further action",
        authority_field: authority_text,
    })
    authority_before = module._done_worker_result_terminal(unit)

    assert authority_before is False
    module.update_task("test-task", {"WORK_UNITS": [unit]})
    first = module.load_state("test-task")["WORK_UNITS"][0]
    assert first[authority_field] == authority_text
    assert module._done_worker_result_terminal(first) is authority_before

    module.update_task("test-task", {"CURRENT_ACTION": "Repeat persistence"})
    second = module.load_state("test-task")["WORK_UNITS"][0]
    assert second[authority_field] == authority_text
    assert module._done_worker_result_terminal(second) is authority_before


def test_r9_persistence_cannot_destroy_canonical_done_authority(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    checkpoint = ("A" * 300) + " COMPLETED " + ("B" * 300)
    unit = module._new_work_unit("WU-001", "Preserve completed authority")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": checkpoint, "next_action": "No further action",
    })

    authority_before = module._done_worker_result_terminal(unit)
    assert authority_before is True
    module.update_task("test-task", {"WORK_UNITS": [unit]})
    persisted = module.load_state("test-task")["WORK_UNITS"][0]

    assert persisted["last_checkpoint"] == checkpoint
    assert module._done_worker_result_terminal(persisted) is authority_before
    assert module._work_unit_counts({"WORK_UNITS": [persisted]})["done"] == 1


@pytest.mark.parametrize(
    "authority_override",
    [
        {"blockers": {"code": "UNRESOLVED"}},
        {"failed_tests": ["targeted validation failed"]},
        {"validation_passed": False},
        {"failed_validation": True},
        {"validation_result": "FAIL"},
    ],
)
def test_r9_storage_failure_snapshot_preserves_nonterminal_authority_evidence(
    isolated_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    authority_override: dict[str, object],
) -> None:
    state = create_state()
    unit = module._new_work_unit("WU-001", "Preserve active authority evidence")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
        **authority_override,
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKER_PID": 4242,
        "ACTIVE_PROCESS_KIND": "WORKER", "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"], "WORK_UNITS": [unit],
        "UNCOMPACTED_STORAGE_NOISE": "x" * 100_000,
    })
    monkeypatch.setattr(module, "MAX_STATE_BYTES", 50_000)
    monkeypatch.setattr(module, "STATE_COMPACTION_TARGET_BYTES", 40_000)

    assert module._done_worker_result_terminal(unit) is False
    module._write_state_unlocked("test-task", state)
    persisted = module.load_state("test-task")
    persisted_unit = persisted["WORK_UNITS"][0]

    assert persisted["STATE_STORAGE_STATUS"] == "COMPACTION_EXHAUSTED"
    for field, value in authority_override.items():
        assert persisted_unit[field] == value
    assert module._done_worker_result_terminal(persisted_unit) is False
    assert module._work_unit_counts(persisted)["done"] == 0


def test_r9_oversized_authority_evidence_rejects_write_losslessly(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    persisted_before = module.state_path("test-task").read_bytes()
    unit = module._new_work_unit("WU-001", "Reject an unsafe authority rewrite")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "COMPLETED " + ("A" * 100_000),
        "next_action": "No further action",
    })
    state["WORK_UNITS"] = [unit]
    monkeypatch.setattr(module, "MAX_STATE_BYTES", 50_000)
    monkeypatch.setattr(module, "STATE_COMPACTION_TARGET_BYTES", 40_000)

    assert module._done_worker_result_terminal(unit) is True
    with pytest.raises(
        module.HarnessError,
        match="WORK_UNIT_COMPLETION_AUTHORITY_CHANGED_DURING_PERSISTENCE",
    ):
        module._write_state_unlocked("test-task", state)

    assert module.state_path("test-task").read_bytes() == persisted_before


def test_r9_blocker_authority_semantics_are_lossless_across_persistence(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    blocker = {
        "kind": "LOCAL", "code": "LOCAL_BLOCKER",
        "detail": "environment " + ("A" * 300) + " task-caused " + ("B" * 300),
    }
    unit = module._new_work_unit("WU-001", "Preserve blocker authority")
    unit.update({
        "status": "DEFERRED", "validation_state": "NOT_RUN",
        "blocker": blocker, "last_checkpoint": "DEFERRED_BY_DEPENDENCY",
    })
    state["WORK_UNITS"] = [unit]

    assert module._local_environment_only(unit) is False
    module.update_task("test-task", {"WORK_UNITS": [unit]})
    persisted = module.load_state("test-task")["WORK_UNITS"][0]

    assert persisted["blocker"] == blocker
    assert module._done_worker_result_terminal(persisted) is False
    assert module._local_environment_only(persisted) is False


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


def test_missing_or_invalid_active_unit_results_are_retried_not_completed() -> None:
    state = module._new_state("test-task", "Complete bounded units", "independent-code", 2)
    units = [
        module._new_work_unit(
            f"WU-{index:03d}", f"Complete bounded unit {index}",
            reuse_decision="EXTEND", reuse_evidence=["existing Harness component"],
        )
        for index in range(1, 4)
    ]
    for unit in units:
        unit["status"] = "RUNNING"
    state.update({
        "WORK_UNITS": units,
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001", "WU-002", "WU-003"],
    })
    reported = [{
        "id": "WU-001", "status": "BLOCKED_LOCAL", "produced_outputs": [],
        "validation_state": "NOT_RUN",
        "blocker": {"code": "SOURCE_UNAVAILABLE", "detail": "Canonical source is absent"},
        "last_checkpoint": "SOURCE_AUDITED", "next_action": "Wait for the canonical source",
        "reuse_decision": "EXTEND", "reuse_evidence": ["existing Harness component"],
    }, {
        "id": "WU-002", "status": "RUNNING",
    }]
    message = f"WORK_UNIT_RESULTS_JSON={json.dumps(reported, separators=(',', ':'))}"

    results = module._pending_unit_results(state, message)

    assert [row["status"] for row in results] == ["BLOCKED_LOCAL", "RETRY", "RETRY"]
    for row in results[1:]:
        assert row["validation_state"] == "WORKER_RESULT_MISSING"
        assert row["blocker"]["code"] == "WORKER_RESULT_MISSING"
        assert row["reuse_decision"] == "EXTEND"
        assert row["reuse_evidence"] == ["existing Harness component"]


def _active_structured_result_state() -> dict:
    state = module._new_state("test-task", "Complete one bounded unit", "independent-code", 2)
    unit = module._new_work_unit(
        "WU-001", "Complete one bounded unit",
        reuse_decision="EXTEND", reuse_evidence=["existing Harness component"],
    )
    unit["status"] = "RUNNING"
    state.update({
        "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
    })
    return state


def _structured_worker_result(
    status: str = "DONE",
    *,
    validation_state: str = "PASS",
    blocker: dict | None = None,
    **extra: object,
) -> dict:
    row = {
        "id": "WU-001", "status": status, "produced_outputs": ["authorized-output.py"],
        "validation_state": validation_state, "blocker": {} if blocker is None else blocker,
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further worker action",
        "reuse_decision": "EXTEND", "reuse_evidence": ["existing Harness component"],
    }
    row.update(extra)
    return row


def _worker_completion_message(
    *,
    task_result: str = "COMPLETED",
    rows: list[dict] | None = None,
    contamination: str = "NONE",
    blocker_kind: str = "NONE",
    changed_paths: list[str] | None = None,
    justification: str = "NONE",
) -> str:
    return "\n".join([
        f"TASK_RESULT={task_result}",
        f"HOLDOUT_CONTAMINATION_RISK={contamination}",
        f"BLOCKER_KIND={blocker_kind}",
        f"WORK_UNIT_RESULTS_JSON={json.dumps(rows or [], separators=(',', ':'))}",
        f"CHANGED_PATHS_JSON={json.dumps(changed_paths or [], separators=(',', ':'))}",
        f"NEW_COMPONENT_JUSTIFICATION={justification}",
    ])


@pytest.mark.parametrize(
    "statuses",
    [("DONE", "RETRY"), ("DONE", "FAIL"), ("DONE", "DONE")],
    ids=["done-retry", "done-fail", "identical-done"],
)
def test_duplicate_structured_results_are_rejected_independent_of_order(
    statuses: tuple[str, str],
) -> None:
    outcomes = []
    for ordered_statuses in (statuses, tuple(reversed(statuses))):
        rows = [
            _structured_worker_result(
                status,
                validation_state="PASS" if status == "DONE" else status,
            )
            for status in ordered_statuses
        ]
        state = _active_structured_result_state()
        message = (
            "TASK_RESULT=COMPLETED\n"
            f"WORK_UNIT_RESULTS_JSON={json.dumps(rows, separators=(',', ':'))}"
        )
        parsed = module._pending_unit_results(state, message)
        state["PENDING_UNIT_RESULTS"] = rows
        module._apply_validated_unit_results(state)
        outcomes.append((
            parsed[0]["status"], parsed[0]["blocker"]["code"],
            state["WORK_UNITS"][0]["status"], state["WORK_UNITS"][0]["blocker"]["code"],
        ))

    assert outcomes == [
        ("RETRY", "WORKER_RESULT_DUPLICATE", "RETRY", "WORKER_RESULT_DUPLICATE"),
        ("RETRY", "WORKER_RESULT_DUPLICATE", "RETRY", "WORKER_RESULT_DUPLICATE"),
    ]


@pytest.mark.parametrize(
    "statuses",
    [("DONE", "RETRY"), ("RETRY", "DONE"), ("DONE", "DONE")],
    ids=["done-then-retry", "retry-then-done", "identical-done"],
)
def test_repeated_worker_result_markers_reject_the_entire_message(
    statuses: tuple[str, str],
) -> None:
    marker_lines = []
    for status in statuses:
        row = _structured_worker_result(
            status, validation_state="PASS" if status == "DONE" else status,
        )
        marker_lines.append(
            f"WORK_UNIT_RESULTS_JSON={json.dumps([row], separators=(',', ':'))}"
        )
    state = _active_structured_result_state()
    state["WORKER_FINDINGS"] = "\n".join(marker_lines)

    parsed = module._pending_unit_results(state)

    assert parsed[0]["status"] == "RETRY"
    assert parsed[0]["blocker"]["code"] == "WORKER_RESULT_MISSING"
    state["PENDING_UNIT_RESULTS"] = []
    module._apply_validated_unit_results(state)
    assert state["WORK_UNITS"][0]["status"] == "RETRY"
    assert state["WORK_UNITS"][0]["blocker"]["code"] == "WORKER_RESULT_MISSING"


@pytest.mark.parametrize(
    "extra_marker",
    ["WORK_UNIT_RESULTS_JSON=", "WORK_UNIT_RESULTS_JSON={not-json}"],
    ids=["empty-extra-marker", "malformed-extra-marker"],
)
def test_any_extra_worker_result_marker_makes_the_message_ambiguous(
    extra_marker: str,
) -> None:
    row = _structured_worker_result()
    valid_marker = f"WORK_UNIT_RESULTS_JSON={json.dumps([row], separators=(',', ':'))}"
    state = _active_structured_result_state()

    parsed = module._pending_unit_results(
        state, f"{extra_marker}\n{valid_marker}",
    )

    assert parsed[0]["status"] == "RETRY"
    assert parsed[0]["blocker"]["code"] == "WORKER_RESULT_MISSING"


def test_duplicate_json_keys_at_top_level_or_nested_fail_closed() -> None:
    compact = json.dumps([_structured_worker_result()], separators=(",", ":"))
    ambiguous_payloads = [
        compact.replace('"status":"DONE"', '"status":"RETRY","status":"DONE"', 1),
        compact.replace('"status":"DONE"', '"status":"DONE","status":"RETRY"', 1),
        compact.replace(
            '"validation_state":"PASS"',
            '"validation_state":"PASS","validation_state":"FAIL"',
            1,
        ),
        compact.replace(
            '"validation_state":"PASS"',
            '"validation_state":"FAIL","validation_state":"PASS"',
            1,
        ),
        compact.replace(
            '"blocker":{}',
            '"blocker":{"context":{"code":"FIRST","code":"SECOND"}}',
            1,
        ),
    ]

    for payload in ambiguous_payloads:
        state = _active_structured_result_state()
        parsed = module._pending_unit_results(
            state, f"WORK_UNIT_RESULTS_JSON={payload}",
        )

        assert parsed[0]["status"] == "RETRY"
        assert parsed[0]["blocker"]["code"] == "WORKER_RESULT_MISSING"


@pytest.mark.parametrize(
    "contradiction",
    [
        {"validation_state": "FAIL"},
        {"validation_state": "NOT_RUN"},
        {"validation_state": "TESTS_NOT_RUN"},
        {"validation_state": "UNKNOWN"},
        {"validation_state": "CANCELLED"},
        {"validation_state": "TASK_TESTS_PASS_GLOBAL_GUARD_FAIL"},
        {"validation_state": "WORKER_CHECKPOINT"},
        {"validation_state": "ENVIRONMENT_LIMITED"},
        {"validation_state": "pass"},
        {"blocker": {"code": "VALIDATION_FAILED", "detail": "Focused validation failed"}},
        {"blockers": [{"code": "VALIDATION_FAILED"}]},
        {"validation_passed": False},
        {"validation_failed": True},
        {"failed_validation": True},
        {"tests_failed": 1},
        {"validation_errors": ["focused validation failed"]},
        {"validation_result": "FAIL"},
        {"validation_result": "PASSED"},
        {"last_checkpoint": "VALIDATION_FAILED"},
        {"last_checkpoint": ""},
        {"last_checkpoint": "RUNNING"},
        {"last_checkpoint": "IN_PROGRESS"},
        {"last_checkpoint": "WORKING"},
        {"last_checkpoint": "WAITING"},
        {"last_checkpoint": "RETRY"},
        {"last_checkpoint": "WORKER_CHECKPOINT"},
        {"last_checkpoint": "NOT_COMPLETED"},
        {"last_checkpoint": "IMPLEMENTATION_COMPLETE_NEEDS_MORE_WORK"},
        {"next_action": ""},
        {"next_action": "Continue implementation"},
        {"next_action": "Run validation"},
        {"next_action": "Controller validation"},
        {"next_action": "Run remaining tests"},
        {"next_action": "Controller validation then continue implementation"},
    ],
    ids=[
        "validation-fail", "validation-not-run", "composite-not-run",
        "ambiguous-validation", "cancelled-validation", "composite-terminal-fail",
        "checkpoint-validation-is-not-pass", "environment-limited-validation-is-not-pass",
        "lowercase-pass-is-not-canonical",
        "blocker", "blockers", "explicit-validation-false", "validation-failed-true",
        "failed-validation-true", "tests-failed-one", "validation-errors",
        "explicit-validation-result", "noncanonical-passed-result", "failed-checkpoint",
        "missing-checkpoint", "running-checkpoint", "in-progress-checkpoint",
        "working-checkpoint", "waiting-checkpoint", "retry-checkpoint",
        "checkpoint-only-checkpoint", "negated-completed-checkpoint",
        "completed-but-needs-more-work-checkpoint",
        "missing-next-action", "continuing-next-action", "run-validation-next-action",
        "controller-validation-next-action", "remaining-tests-next-action",
        "handoff-then-continue-next-action",
    ],
)
def test_done_with_structured_contradiction_is_retried_despite_success_prose(
    contradiction: dict,
) -> None:
    row = _structured_worker_result()
    row.update(contradiction)
    state = _active_structured_result_state()
    message = (
        "TASK_RESULT=COMPLETED\nCOMPLETED_WORK=All work is complete and successful.\n"
        f"WORK_UNIT_RESULTS_JSON={json.dumps([row], separators=(',', ':'))}"
    )

    parsed = module._pending_unit_results(state, message)
    assert parsed[0]["status"] == "RETRY"
    assert parsed[0]["blocker"]["code"] == "WORKER_RESULT_CONTRADICTORY"

    state["PENDING_UNIT_RESULTS"] = [row]
    module._apply_validated_unit_results(state)
    assert state["WORK_UNITS"][0]["status"] == "RETRY"
    assert state["WORK_UNITS"][0]["blocker"]["code"] == "WORKER_RESULT_CONTRADICTORY"


@pytest.mark.parametrize(
    ("last_checkpoint", "next_action"),
    [
        ("IMPLEMENTATION_COMPLETE", "No further action"),
        ("VALIDATED", "No further worker action"),
        ("WORK_COMPLETED", "No more worker work remains"),
        ("DONE", "NONE"),
    ],
)
def test_single_done_pass_without_blocker_remains_valid_structured_completion(
    last_checkpoint: str, next_action: str,
) -> None:
    row = _structured_worker_result(
        last_checkpoint=last_checkpoint, next_action=next_action,
    )
    state = _active_structured_result_state()
    message = f"WORK_UNIT_RESULTS_JSON={json.dumps([row], separators=(',', ':'))}"

    parsed = module._pending_unit_results(state, message)
    assert parsed == [row]

    state["PENDING_UNIT_RESULTS"] = [row]
    module._apply_validated_unit_results(state)
    unit = state["WORK_UNITS"][0]
    assert unit["status"] == "DONE"
    assert unit["validation_state"] == "PASS"
    assert unit["blocker"] == {}


@pytest.mark.parametrize(
    "contradiction",
    [
        {"validation_state": "WORKER_CHECKPOINT"},
        {"last_checkpoint": ""},
        {"last_checkpoint": "RUNNING"},
        {"last_checkpoint": "IN_PROGRESS"},
        {"last_checkpoint": "WORKING"},
        {"last_checkpoint": "WAITING"},
        {"last_checkpoint": "RETRY"},
        {"last_checkpoint": "IMPLEMENTATION_COMPLETE_NEEDS_MORE_WORK"},
        {"next_action": ""},
        {"next_action": "Continue implementation"},
        {"next_action": "Run validation"},
        {"next_action": "Controller validation"},
    ],
)
def test_complete_contract_and_downstream_apply_reject_nonterminal_done_authority(
    contradiction: dict,
) -> None:
    state = _active_structured_result_state()
    row = _structured_worker_result(**contradiction)
    evidence = module._ingest_worker_completion_evidence(
        state, _worker_completion_message(rows=[row]),
    )
    state.update(module._worker_completion_state_fields(evidence))

    assert evidence["structured_contract_valid"] is False
    assert evidence["task_result"] == "RETRY"
    assert evidence["work_unit_results"][0]["status"] == "RETRY"
    assert module._worker_result(state, 0) == "RETRY"

    # Even a raw/stale pending row cannot bypass the canonical terminality
    # predicate when Controller validation later applies unit results.
    state["PENDING_UNIT_RESULTS"] = [row]
    module._apply_validated_unit_results(state)
    unit = state["WORK_UNITS"][0]
    assert unit["status"] == "RETRY"
    assert unit["blocker"]["code"] == "WORKER_RESULT_CONTRADICTORY"


def test_malformed_worker_result_marker_does_not_complete_active_unit() -> None:
    state = module._new_state("test-task", "Complete one bounded unit", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete one bounded unit")
    unit["status"] = "RUNNING"
    state.update({
        "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
    })

    result = module._pending_unit_results(state, "WORK_UNIT_RESULTS_JSON={not-json}")

    assert result[0]["status"] == "RETRY"
    assert result[0]["last_checkpoint"] == "WORKER_RESULT_MISSING"
    state["PENDING_UNIT_RESULTS"] = result
    module._apply_validated_unit_results(state)
    assert state["WORK_UNITS"][0]["status"] == "RETRY"
    assert state["WORK_UNITS"][0]["validation_state"] == "WORKER_RESULT_MISSING"

    persisted = module._new_state("test-task", "Complete one bounded unit", "independent-code", 2)
    persisted_units = [
        module._new_work_unit(f"WU-{index:03d}", f"Complete bounded unit {index}")
        for index in range(1, 3)
    ]
    for persisted_unit in persisted_units:
        persisted_unit["status"] = "RUNNING"
    persisted.update({
        "WORK_UNITS": persisted_units,
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001", "WU-002"],
        "PENDING_UNIT_RESULTS": [{"id": "WU-001", "status": "RUNNING"}],
    })

    module._apply_validated_unit_results(persisted)

    assert [unit["status"] for unit in persisted["WORK_UNITS"]] == ["RETRY", "RETRY"]
    for persisted_unit in persisted["WORK_UNITS"]:
        assert persisted_unit["blocker"]["code"] == "WORKER_RESULT_MISSING"


def test_incomplete_done_worker_result_is_retried_not_completed() -> None:
    state = module._new_state("test-task", "Complete one bounded unit", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete one bounded unit")
    unit["status"] = "RUNNING"
    state.update({
        "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
    })
    incomplete = {"id": "WU-001", "status": "DONE"}
    message = f"WORK_UNIT_RESULTS_JSON={json.dumps([incomplete], separators=(',', ':'))}"

    parsed = module._pending_unit_results(state, message)

    assert parsed[0]["status"] == "RETRY"
    assert parsed[0]["blocker"]["code"] == "WORKER_RESULT_MISSING"

    state["PENDING_UNIT_RESULTS"] = [incomplete]
    module._apply_validated_unit_results(state)

    assert state["WORK_UNITS"][0]["status"] == "RETRY"
    assert state["WORK_UNITS"][0]["validation_state"] == "WORKER_RESULT_MISSING"


@pytest.mark.parametrize("worker_findings", ["", "TASK_RESULT=RUNNING", "TASK_RESULT=unknown"])
def test_absent_or_nonterminal_task_result_retries_fail_closed(worker_findings: str) -> None:
    state = module._new_state("test-task", "Complete one bounded unit", "independent-code", 2)
    state["WORKER_FINDINGS"] = worker_findings

    assert module._worker_result(state, 0) == "RETRY"


def test_complete_worker_message_is_ingested_before_display_truncation(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete one bounded unit")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_ID": "WU-001",
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
    })
    module._write_state_unlocked("test-task", state)
    retry_row = _structured_worker_result("RETRY", validation_state="RETRY")
    done_row = _structured_worker_result()
    authoritative_message = (
        "TASK_RESULT=BLOCKED\n"
        "HOLDOUT_CONTAMINATION_RISK=possible holdout exposure\n"
        "BLOCKER_KIND=SAFETY\n"
        "CHANGED_PATHS_JSON=[\"scripts/maintenance/harness_task.py\"]\n"
        "NEW_COMPONENT_JUSTIFICATION=Existing Harness authority was extended\n"
        f"WORK_UNIT_RESULTS_JSON={json.dumps([retry_row], separators=(',', ':'))}\n"
        + "x" * 9_000
        + "\n"
        + f"WORK_UNIT_RESULTS_JSON={json.dumps([done_row], separators=(',', ':'))}"
    )

    class FakeInput:
        def write(self, value: str) -> None:
            assert value

        def close(self) -> None:
            return None

    class FakeOutput:
        def __iter__(self):
            yield json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": authoritative_message},
            }) + "\n"

    class FakeProcess:
        pid = 4242
        stdin = FakeInput()
        stdout = FakeOutput()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(module, "assert_registered_isolated_worktree", lambda path: None)
    monkeypatch.setattr(
        module, "_codex_exec_command",
        lambda worktree, sandbox, review, writable_runtime=None: ["codex"],
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })

    result = module._run_codex_turn("test-task", "bounded prompt")
    stored = module.load_state("test-task")
    evidence = stored["WORKER_COMPLETION_EVIDENCE"]

    assert result["message"] == authoritative_message[-module.MAX_TEXT:]
    assert "TASK_RESULT=BLOCKED" not in result["message"]
    assert evidence["marker_counts"]["WORK_UNIT_RESULTS_JSON"] == 2
    assert evidence["task_result"] == "BLOCKED"
    assert evidence["holdout_contamination_risk"] == "possible holdout exposure"
    assert evidence["blocker_kind"] == "SAFETY"
    assert evidence["changed_paths"] == ["scripts/maintenance/harness_task.py"]
    assert evidence["new_component_justification"] == "Existing Harness authority was extended"
    assert stored["PENDING_UNIT_RESULTS"][0]["status"] == "RETRY"
    assert stored["PENDING_UNIT_RESULTS"][0]["blocker"]["code"] == "WORKER_RESULT_MISSING"
    assert module._worker_result(stored, 0) == "BLOCKED"
    assert module._pending_unit_results(stored)[0]["status"] == "RETRY"
    assert module._pending_unit_results(stored, result["message"])[0]["status"] == "DONE"


def test_compacted_worker_findings_never_replace_canonical_unit_results() -> None:
    state = _active_structured_result_state()
    retry_row = _structured_worker_result("RETRY", validation_state="RETRY")
    done_row = _structured_worker_result()
    message = (
        "x" * 2_800
        + "\n"
        + f"WORK_UNIT_RESULTS_JSON={json.dumps([retry_row], separators=(',', ':'))}\n"
        + "y" * 2_800
        + "\n"
        + f"WORK_UNIT_RESULTS_JSON={json.dumps([done_row], separators=(',', ':'))}"
    )
    evidence = module._ingest_worker_completion_evidence(state, message)
    state.update(module._worker_completion_state_fields(evidence))
    state.update({
        "WORKER_FINDINGS": message, "NEXT_ACTION_CODE": "UNIT_VALIDATE",
        "ACTIVE_PROCESS_KIND": "", "WORKER_PID": None,
    })

    module._compact_state_for_write("test-task", state)

    assert len(state["WORKER_FINDINGS"].encode("utf-8")) <= 3_200
    assert module._pending_unit_results(state)[0]["status"] == "RETRY"
    assert module._pending_unit_results(
        state, state["WORKER_FINDINGS"],
    )[0]["status"] == "DONE"
    module._apply_validated_unit_results(state)
    assert state["WORK_UNITS"][0]["status"] == "RETRY"


def test_display_only_done_marker_cannot_fill_an_empty_canonical_checkpoint() -> None:
    state = _active_structured_result_state()
    done_row = _structured_worker_result()
    state["WORKER_FINDINGS"] = (
        f"WORK_UNIT_RESULTS_JSON={json.dumps([done_row], separators=(',', ':'))}"
    )
    state["PENDING_UNIT_RESULTS"] = []
    state["WORKER_COMPLETION_EVIDENCE"] = {}

    module._apply_validated_unit_results(state)

    assert state["WORK_UNITS"][0]["status"] == "RETRY"
    assert state["WORK_UNITS"][0]["blocker"]["code"] == "WORKER_RESULT_MISSING"


def test_structured_safety_blocker_overrides_completed_and_done_evidence() -> None:
    state = _active_structured_result_state()
    message = _worker_completion_message(
        rows=[_structured_worker_result()], blocker_kind="SAFETY",
    )

    evidence = module._ingest_worker_completion_evidence(state, message)
    state.update(module._worker_completion_state_fields(evidence))

    assert evidence["structured_contract_valid"] is False
    assert "CONTRADICTORY_TASK_RESULT_AND_BLOCKER_KIND" in evidence["validation_issues"]
    assert evidence["requires_human_boundary"] is True
    assert evidence["task_result"] == "BLOCKED"
    assert evidence["work_unit_results"][0]["status"] == "RETRY"
    assert module._worker_result(state, 0) == "BLOCKED"


def test_ambiguous_blocker_markers_cannot_authorize_done_checkpoint() -> None:
    state = _active_structured_result_state()
    message = _worker_completion_message(rows=[_structured_worker_result()]).replace(
        "BLOCKER_KIND=NONE",
        "BLOCKER_KIND=SAFETY\nBLOCKER_KIND=NONE",
    )

    evidence = module._ingest_worker_completion_evidence(state, message)
    state.update(module._worker_completion_state_fields(evidence))

    assert evidence["structured_contract_valid"] is False
    assert evidence["task_result"] == "RETRY"
    assert evidence["marker_counts"]["BLOCKER_KIND"] == 2
    assert evidence["work_unit_results"][0]["status"] == "RETRY"
    assert module._worker_result(state, 0) == "RETRY"


def test_missing_completion_safety_markers_invalidate_done_checkpoint() -> None:
    state = _active_structured_result_state()
    message = (
        "TASK_RESULT=COMPLETED\n"
        f"WORK_UNIT_RESULTS_JSON={json.dumps([_structured_worker_result()], separators=(',', ':'))}"
    )

    evidence = module._ingest_worker_completion_evidence(state, message)

    assert evidence["structured_contract_valid"] is False
    assert evidence["task_result"] == "RETRY"
    assert evidence["work_unit_results"][0]["status"] == "RETRY"


def test_waiting_human_requires_canonical_human_blocker_not_display_prose() -> None:
    state = _active_structured_result_state()
    message = (
        "Authorization is required before continuing.\n"
        + "x" * 9_000
        + "\n"
        + _worker_completion_message(
            task_result="WAITING_HUMAN",
            rows=[_structured_worker_result("RETRY", validation_state="RETRY")],
            blocker_kind="NONE",
        )
    )

    evidence = module._ingest_worker_completion_evidence(state, message)

    assert evidence["structured_contract_valid"] is False
    assert "CONTRADICTORY_TASK_RESULT_AND_BLOCKER_KIND" in evidence["validation_issues"]
    assert evidence["task_result"] == "RETRY"
    assert evidence["requires_human_boundary"] is False


def test_pause_checkpoint_cannot_erase_canonical_worker_boundary(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete one authorized repair")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "PAUSING", "WORKTREE": str(worktree),
        "PAUSE_REQUESTED": True, "NEXT_ACTION_CODE": "WORKER",
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
    })
    message = _worker_completion_message(
        task_result="BLOCKED",
        rows=[_structured_worker_result("RETRY", validation_state="RETRY")],
        blocker_kind="AUTHORIZATION",
    )
    evidence = module._ingest_worker_completion_evidence(state, message)
    state.update(module._worker_completion_state_fields(evidence))
    module._write_state_unlocked("test-task", state)

    assert module._control_checkpoint("test-task") is True
    paused = module.load_state("test-task")
    assert paused["HARNESS_STATE"] == "WAITING_HUMAN"
    assert paused["WORKER_COMPLETION_EVIDENCE"]["requires_human_boundary"] is True
    assert paused["ACTIVE_BLOCKERS"][-1]["code"] == (
        "WORKER_CANONICAL_BOUNDARY_AT_PAUSE"
    )


def test_worker_process_error_cannot_reset_persisted_canonical_boundary(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete one authorized repair")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "WORKER", "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"], "ACTIVE_WORK_UNIT_ID": "WU-001",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "stable")

    def boundary_then_error(*args, **kwargs) -> dict:
        current = module.load_state("test-task")
        message = _worker_completion_message(
            task_result="BLOCKED",
            rows=[_structured_worker_result("RETRY", validation_state="RETRY")],
            blocker_kind="AUTHORIZATION",
        )
        evidence = module._ingest_worker_completion_evidence(current, message)
        module.update_task("test-task", {
            **module._worker_completion_state_fields(evidence),
            "WORKER_FINDINGS": message[-module.MAX_TEXT:],
            "WORKER_STATUS": "EXITED_1", "WORKER_PID": None,
            "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
        })
        raise module.HarnessError(
            "CODEX_INTERFACE_UNAVAILABLE:authentication required"
        )

    monkeypatch.setattr(module, "_run_codex_turn", boundary_then_error)

    module._dispatch("test-task")

    failed = module.load_state("test-task")
    assert failed["HARNESS_STATE"] == "WAITING_HUMAN"
    assert failed["WORKER_COMPLETION_EVIDENCE"]["requires_human_boundary"] is True
    assert failed["ACTIVE_BLOCKERS"][-1]["code"] == (
        "WORKER_CANONICAL_BOUNDARY_AFTER_PROCESS_ERROR"
    )
    assert failed["NEXT_ACTION_CODE"] == "WORKER"


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
            "blocker": {"code": "LOCAL", "detail": "local environment blocker"} if index % 3 else {},
            "last_checkpoint": "VALIDATED" if index % 3 == 0 else "PLANNED",
            "next_action": "No further action" if index % 3 == 0 else "Execute this authorized work unit",
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

    findings = _worker_completion_message(
        changed_paths=[artifact],
        justification="No authoritative component existed",
    )
    module._refresh_changes(
        "test-task", worker_findings=findings,
        worker_completion_evidence=module._ingest_worker_completion_evidence(
            module.load_state("test-task"), findings,
        ),
    )
    initial = module.load_state("test-task")
    assert initial["REUSE_GUARD"] == "PASS_SEARCH_RECORDED"
    assert initial["JUSTIFIED_CREATED_PATHS"] == [artifact]

    findings = _worker_completion_message(changed_paths=[artifact])
    module._refresh_changes(
        "test-task", worker_findings=findings,
        worker_completion_evidence=module._ingest_worker_completion_evidence(
            module.load_state("test-task"), findings,
        ),
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
    findings = _worker_completion_message(
        changed_paths=list(created),
        justification="Component A had no reusable predecessor",
    )
    module._refresh_changes(
        "test-task", worker_findings=findings,
        worker_completion_evidence=module._ingest_worker_completion_evidence(
            module.load_state("test-task"), findings,
        ),
    )

    created.append("docs/component-b.md")
    findings = _worker_completion_message(changed_paths=list(created))
    module._refresh_changes(
        "test-task", worker_findings=findings,
        worker_completion_evidence=module._ingest_worker_completion_evidence(
            module.load_state("test-task"), findings,
        ),
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

    findings = _worker_completion_message(changed_paths=[artifact])
    module._refresh_changes(
        "test-task", worker_findings=findings,
        worker_completion_evidence=module._ingest_worker_completion_evidence(
            module.load_state("test-task"), findings,
        ),
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


def test_r3_final_review_safety_pass_language_is_not_an_actionable_identity() -> None:
    state = module._new_state("test-task", "Repair worker result handling", "2026-evaluation", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    detail = (
        "Blocking: activation did not occur because the registry is unchanged. "
        "Material Harness inconsistency: structured BLOCKED_LOCAL/FAIL results were later "
        "represented as DONE/PASS; unparsed active results default to DONE. "
        "Safety is intact: no duplicate implementation or frozen-asset modification occurred. "
        "Anti-Bloat checks are passing with no task-created violation."
    )

    finding = module._review_finding_identity(
        state, detail, ["scripts/maintenance/harness_task.py"],
    )

    assert finding["identities"] == ["WORKER_RESULT_COMPLETION_INFERENCE"]
    assert "ANTI_BLOAT_TASK_DELTA" not in finding["identity"]
    assert "DUPLICATE_COMPONENT_IDENTITY" not in finding["identity"]
    assert module._review_finding_analysis(
        state, "A duplicate implementation was introduced by this change.",
    )["identities"] == ["DUPLICATE_COMPONENT_IDENTITY"]
    assert module._review_finding_analysis(
        state, "Anti-Bloat task delta violation: a task-created .venv was found.",
    )["identities"] == ["ANTI_BLOAT_TASK_DELTA"]
    for safe_detail in (
        "No Anti-Bloat violation or duplicate implementation was introduced.",
        "Anti-Bloat checks found no violation and zero duplicate component identities.",
        "Anti-Bloat checks pass with no task-created violation.",
        "A duplicate implementation was not introduced by this change.",
        "The change is free of duplicate implementation.",
        "Anti-Bloat violation was not introduced by this change.",
        "Unparsed active results do not default to DONE anymore.",
        "Malformed worker results must not be inferred as complete.",
    ):
        assert module._review_finding_analysis(state, safe_detail)["identities"] == [
            "GENERIC_CORRECTNESS|general",
        ]


@pytest.mark.parametrize(
    "detail",
    [
        "Duplicate component does not exist.",
        "Duplicate component cannot be found.",
        "Duplicate component was not found.",
        "No duplicate component was found.",
        "Duplicate component is absent.",
        "Duplicate component doesn't exist.",
        "Duplicate component can't be found.",
        "Duplicate component could not be found.",
        "Duplicate component couldn't be found.",
        "The reviewer could not find a duplicate component.",
        "The reviewer couldn't find duplicate component.",
    ],
)
def test_r3_common_negated_duplicate_forms_are_not_actionable(detail: str) -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)

    identities = module._review_finding_analysis(state, detail)["identities"]

    assert "DUPLICATE_COMPONENT_IDENTITY" not in identities


def test_r3_duplicate_negation_is_clause_local_with_positive_controls() -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)
    for detail in (
        "Duplicate component exists.",
        "Duplicate component does not exist, but duplicate implementation exists.",
        "Duplicate component exists, but duplicate implementation cannot be found.",
        "No tests failed and duplicate component exists.",
        "No tests failed, duplicate component exists.",
        "Duplicate component A does not exist and duplicate component B exists.",
        "Duplicate component A exists and duplicate component B does not exist.",
        "Duplicate component A exists and duplicate component B couldn't be found.",
        "No concerns about timing and duplicate component exists.",
        "The reviewer could not confirm timing and duplicate component exists.",
        "This note is not about timing because duplicate component exists.",
        "No timing issue exists; duplicate component exists.",
        "Duplicate component A does not exist, but duplicate component B exists.",
        "The reviewer cannot confirm timing because duplicate component exists.",
        "The reviewer could not confirm timing because duplicate component exists.",
        "The reviewer did not find a duplicate component, and duplicate implementation exists.",
        "No Anti-Bloat violation, and duplicate component exists.",
        "No duplicate component, and duplicate implementation exists.",
    ):
        assert "DUPLICATE_COMPONENT_IDENTITY" in module._review_finding_analysis(
            state, detail,
        )["identities"]
    for detail in (
        "Duplicate component A and duplicate component B do not exist.",
        "No duplicate component A and duplicate component B were found.",
        "Duplicate component A and duplicate component B couldn't be found.",
    ):
        assert "DUPLICATE_COMPONENT_IDENTITY" not in module._review_finding_analysis(
            state, detail,
        )["identities"]


@pytest.mark.parametrize(
    "detail",
    [
        "No duplicate component, duplicate implementation, or parallel component was found.",
        "Anti-Bloat violation, and duplicate component, were not found.",
        "Duplicate component: not found.",
        "No duplicate component\nduplicate implementation\nor parallel component was found.",
        "Anti-Bloat violation\nand duplicate component\nwere not found.",
        "Neither duplicate component nor duplicate implementation was found.",
        "Duplicate component and duplicate implementation were never found.",
        "Duplicate component and duplicate implementation have not been found.",
        "Anti-Bloat violation and duplicate component had not been detected.",
        "Duplicate component or parallel component has not been observed.",
        "No duplicate component, duplicate implementation, nor parallel component was found.",
    ],
)
def test_r3_negation_scope_survives_coordinating_punctuation(detail: str) -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)

    identities = module._review_finding_analysis(state, detail)["identities"]

    assert "DUPLICATE_COMPONENT_IDENTITY" not in identities
    assert "ANTI_BLOAT_TASK_DELTA" not in identities


def test_r3_shared_negation_stops_at_affirmative_coordinated_finding() -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"

    duplicate_clause = module._review_finding_analysis(
        state, "No Anti-Bloat violation, and duplicate component exists.",
    )["identities"]
    anti_bloat_clause = module._review_finding_analysis(
        state, "No duplicate component, and Anti-Bloat violation exists.",
    )["identities"]

    assert "DUPLICATE_COMPONENT_IDENTITY" in duplicate_clause
    assert "ANTI_BLOAT_TASK_DELTA" not in duplicate_clause
    assert "ANTI_BLOAT_TASK_DELTA" in anti_bloat_clause
    assert "DUPLICATE_COMPONENT_IDENTITY" not in anti_bloat_clause

    emphasized = module._review_finding_analysis(
        state, "No Anti-Bloat violation, and duplicate component clearly exists.",
    )["identities"]
    assert "DUPLICATE_COMPONENT_IDENTITY" in emphasized
    assert "ANTI_BLOAT_TASK_DELTA" not in emphasized


@pytest.mark.parametrize(
    "detail",
    [
        "Anti-Bloat violation does not exist.",
        "Anti-Bloat violation cannot be found.",
        "Anti-Bloat violation was not found.",
        "No Anti-Bloat violation was found.",
        "Anti-Bloat violation is absent.",
        "Anti-Bloat violation doesn't exist.",
        "Anti-Bloat violation can't be found.",
        "Anti-Bloat violation could not be found.",
        "Anti-Bloat violation couldn't be found.",
        "The reviewer could not find an Anti-Bloat violation.",
        "The reviewer couldn't find Anti-Bloat violation.",
    ],
)
def test_r3_common_negated_anti_bloat_forms_are_not_actionable(detail: str) -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"

    identities = module._review_finding_analysis(state, detail)["identities"]

    assert "ANTI_BLOAT_TASK_DELTA" not in identities


def test_r3_anti_bloat_negation_is_clause_local_with_positive_controls() -> None:
    state = module._new_state("test-task", "Review task delta", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    for detail in (
        "Anti-Bloat violation exists.",
        "Anti-Bloat violation does not exist, but an Anti-Bloat breach exists.",
        "Anti-Bloat violation exists, but an Anti-Bloat breach cannot be found.",
        "No tests failed and Anti-Bloat violation exists.",
        "No tests failed, Anti-Bloat violation exists.",
        "Anti-Bloat violation A does not exist and Anti-Bloat violation B exists.",
        "Anti-Bloat violation A exists and duplicate component B does not exist.",
        "Anti-Bloat violation A exists and duplicate component B couldn't be found.",
        "No concerns about timing and Anti-Bloat violation exists.",
        "The reviewer could not confirm timing and Anti-Bloat violation exists.",
        "This note is not about timing because Anti-Bloat violation exists.",
        "The reviewer cannot confirm timing because Anti-Bloat violation exists.",
        "The reviewer could not confirm timing because Anti-Bloat violation exists.",
        "Anti-Bloat review is not about timing because a violation exists.",
    ):
        assert "ANTI_BLOAT_TASK_DELTA" in module._review_finding_analysis(
            state, detail,
        )["identities"]
    for detail in (
        "Anti-Bloat violation and duplicate component do not exist.",
        "No Anti-Bloat violation and duplicate component were found.",
        "Anti-Bloat violation and duplicate component couldn't be found.",
    ):
        identities = module._review_finding_analysis(state, detail)["identities"]
        assert "ANTI_BLOAT_TASK_DELTA" not in identities
        assert "DUPLICATE_COMPONENT_IDENTITY" not in identities


def test_r3_nonactionable_review_identities_do_not_share_empty_signature() -> None:
    complete = module._new_state("complete", "Complete audit", "independent-code", 2)
    done = module._new_work_unit("WU-001", "Complete audit")
    done.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
    })
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
        "next_action": "No further worker action", "reuse_decision": "EXTEND",
        "reuse_evidence": [],
    }]

    module._apply_validated_unit_results(state)

    assert module._done_worker_result_terminal(correction) is True
    assert parent["status"] == "DONE"
    assert module._done_worker_result_terminal(parent) is True
    assert parent["resolved_by"] == correction["id"]
    assert dependent["status"] == "READY"
    assert dependent["last_checkpoint"] == "DEPENDENCY_RESOLVED"
    assert any(row.get("work_unit_id") == "WU-001" for row in state["RESOLVED_FINDINGS"])


def test_r6_correction_parent_done_requires_canonical_candidate() -> None:
    state = module._new_state("test-task", "Repair storage containment", "independent-code", 2)
    parent = module._new_work_unit("WU-001", "Repair storage containment parity")
    blocker = {"kind": "LOCAL", "conditions": ["Sandbox access denied"]}
    parent.update({
        "status": "BLOCKED_LOCAL", "blocker": blocker,
        "test_failures": ["targeted validation still fails"],
    })
    correction = module._new_work_unit(
        "FIX-001", "Complete the validated correction", parent_id="WU-001",
    )
    correction.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
    })
    state["WORK_UNITS"] = [parent, correction]

    assert module._done_worker_result_terminal(correction) is True
    assert module._reconcile_correction_parents(state, correction) == 0
    assert parent["status"] == "BLOCKED_LOCAL"
    assert parent["blocker"] == blocker
    assert module._done_worker_result_terminal({
        **parent,
        "status": "DONE",
        "validation_state": "PASS",
        "blocker": {},
        "last_checkpoint": "RESOLVED_BY_VALIDATED_CORRECTION",
        "next_action": "No further action",
    }) is False


@pytest.mark.parametrize(
    "reconciler",
    [
        module._reconcile_terminal_local_environment_units,
        module._reconcile_correction_parents,
    ],
)
def test_r6_reconciliation_done_synthesis_uses_canonical_predicate(reconciler: object) -> None:
    source = inspect.getsource(reconciler)

    assert '"status": "DONE"' in source
    assert "_done_worker_result_terminal(candidate)" in source


def test_r6_validated_done_merge_requires_canonical_candidate() -> None:
    state = module._new_state("test-task", "Complete one bounded repair", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete the required repair")
    unit["failed_tests"] = ["targeted validation still fails"]
    state.update({
        "WORK_UNITS": [unit],
        "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "PENDING_UNIT_RESULTS": [{
            "id": "WU-001", "status": "DONE",
            "produced_outputs": ["scripts/maintenance/existing.py"],
            "validation_state": "PASS", "blocker": {},
            "last_checkpoint": "IMPLEMENTATION_COMPLETE",
            "next_action": "No further action", "reuse_decision": "REUSE",
            "reuse_evidence": ["scripts/maintenance/existing.py"],
        }],
    })

    module._apply_validated_unit_results(state)

    applied = state["WORK_UNITS"][0]
    assert applied["status"] == "RETRY"
    assert applied["blocker"]["code"] == "WORKER_RESULT_CONTRADICTORY"
    assert module._done_worker_result_terminal(applied) is False
    assert state["TELEMETRY"]["work_units_completed"] == 0


@pytest.mark.parametrize(
    ("overrides", "expected_done"),
    [
        ({
            "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
            "next_action": "Retry validation",
        }, 0),
        ({
            "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
        }, 0),
        ({"next_action": "Complete remaining work"}, 0),
        ({"validation_state": "WORKER_CHECKPOINT"}, 0),
        ({"last_checkpoint": "RUNNING"}, 0),
        ({}, 1),
    ],
)
def test_r7_work_unit_done_count_requires_canonical_terminality(
    overrides: dict[str, object], expected_done: int,
) -> None:
    unit = module._new_work_unit("WU-001", "Complete the required repair")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further action",
    })
    unit.update(overrides)

    counts = module._work_unit_counts({"WORK_UNITS": [unit]})

    assert module._done_worker_result_terminal(unit) is bool(expected_done)
    assert counts == {
        "total": 1,
        "done": expected_done,
        "runnable": 0,
        "local_blocked": 0,
        "deferred": 0,
    }


def test_r7_mixed_work_unit_counts_only_canonical_done() -> None:
    canonical = module._new_work_unit("WU-001", "Complete the canonical repair")
    canonical.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
    })
    noncanonical = module._new_work_unit("WU-002", "Complete the unresolved repair")
    noncanonical.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    retry = module._new_work_unit("WU-003", "Retry the remaining repair")
    retry.update({
        "status": "RETRY", "validation_state": "NOT_RUN",
        "last_checkpoint": "RETRY_PENDING", "next_action": "Retry validation",
    })
    state = {"WORK_UNITS": [canonical, noncanonical, retry]}

    counts = module._work_unit_counts(state)

    assert module._done_worker_result_terminal(canonical) is True
    assert module._done_worker_result_terminal(noncanonical) is False
    assert module._done_worker_result_terminal(retry) is False
    assert counts["done"] == 1
    assert counts["total"] == 3
    assert counts["runnable"] == 1
    assert noncanonical["status"] == "DONE"


def test_r7_command_status_reports_only_canonical_done(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    state = module._new_state("test-task", "Report one unresolved repair", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete the unresolved repair")
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS",
        "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    state["WORK_UNITS"] = [unit]
    before = json.loads(json.dumps(state["WORK_UNITS"]))
    monkeypatch.setattr(module, "load_state", lambda task_id: state)

    assert module.command_status(argparse.Namespace(task_id="test-task")) == 0
    output = capsys.readouterr().out

    assert module._done_worker_result_terminal(unit) is False
    assert "WORK_UNITS_DONE=0" in output
    assert "WORK_UNITS_TOTAL=1" in output
    assert "WORK_UNITS_DONE=1" not in output
    assert state["WORK_UNITS"][0]["status"] == "DONE"
    assert state["WORK_UNITS"] == before
    assert state["PROGRESS_SUMMARY"] == "0/8 plan steps completed"


def test_r7_zero_diff_completion_reporting_requires_canonical_done() -> None:
    state = module._new_state("test-task", "Review one unresolved repair", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete the unresolved repair")
    unit.update({
        "status": "DONE", "validation_state": "PASS",
        "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    state["WORK_UNITS"] = [unit]
    detail = "No reviewable diff; the clean worktree has zero files changed."

    finding = module._review_finding_identity(state, detail)

    assert module._done_worker_result_terminal(unit) is False
    assert finding["identity"] == "TASK_INCOMPLETE"
    assert finding["identity"] != "VALID_ZERO_DIFF_COMPLETION"
    assert (
        module._queue_correction_work_unit(
            state,
            "FINAL_REVIEW",
            detail,
            "p0",
        )
        is False
    )
    assert (
        state["REVIEW_CORRECTION_DISPOSITION"]
        == "INCOMPLETE_NO_RUNNABLE_REMEDY"
    )


def _r8_canonical_done_unit(unit_id: str, objective: str) -> dict:
    unit = module._new_work_unit(unit_id, objective)
    unit.update({
        "status": "DONE", "produced_outputs": ["existing.py"],
        "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further action",
    })
    return unit


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
            "next_action": "Retry validation",
        },
        {"blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"}},
        {"next_action": "Complete remaining work"},
        {"validation_state": "WORKER_CHECKPOINT"},
        {"last_checkpoint": "RUNNING"},
    ],
    ids=[
        "exact-reviewer-reproducer", "nonempty-blocker", "remaining-work",
        "nonterminal-validation", "nonterminal-checkpoint",
    ],
)
def test_r8_noncanonical_done_dependency_is_not_runnable_or_selected(
    overrides: dict[str, object],
) -> None:
    dependency = _r8_canonical_done_unit("WU-001", "Complete the prerequisite")
    dependency.update(overrides)
    dependent = module._new_work_unit(
        "WU-002", "Run only after the prerequisite", dependencies=["WU-001"],
    )
    state = {"WORK_UNITS": [dependency, dependent]}
    dependency_before = json.loads(json.dumps(dependency))

    assert module._done_worker_result_terminal(dependency) is False
    assert module._dependency_satisfied(dependency) is False
    assert module._runnable_work_units(state) == []
    assert module._recoverable_required_unit_ids(state) == []
    assert module._select_work_unit_batch(state) == []
    assert dependent["status"] == "READY"
    assert dependent["attempts"] == 0
    assert state["ACTIVE_WORK_UNIT_IDS"] == []
    assert dependency == dependency_before


def test_r8_select_work_does_not_dispatch_noncanonical_done_dependent(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    dependency = _r8_canonical_done_unit("WU-001", "Complete the prerequisite")
    dependency.update({
        "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
        "next_action": "Retry validation",
    })
    dependent = module._new_work_unit(
        "WU-002", "Run only after the prerequisite", dependencies=["WU-001"],
    )
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "SELECT_WORK", "WORK_UNITS": [dependency, dependent],
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "p0")
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("worker dispatch bypassed a noncanonical dependency"),
        ),
    )

    def stop_after_selection(task_id: str) -> tuple[bool, str]:
        raise RuntimeError("STOP_AFTER_DEPENDENCY_SELECTION")

    monkeypatch.setattr(module, "_run_final_validation", stop_after_selection)

    with pytest.raises(RuntimeError, match="STOP_AFTER_DEPENDENCY_SELECTION"):
        module._dispatch("test-task")

    persisted = module.load_state("test-task")
    assert [unit["id"] for unit in persisted["WORK_UNITS"]] == ["WU-001", "WU-002"]
    assert persisted["WORK_UNITS"][1]["status"] == "READY"
    assert persisted["WORK_UNITS"][1]["attempts"] == 0
    assert persisted["ACTIVE_WORK_UNIT_IDS"] == []
    assert persisted["NEXT_ACTION_CODE"] == "FINAL_VALIDATION"


def test_r8_canonical_done_dependency_is_runnable_and_selected() -> None:
    dependency = _r8_canonical_done_unit("WU-001", "Complete the prerequisite")
    dependent = module._new_work_unit(
        "WU-002", "Run only after the prerequisite", dependencies=["WU-001"],
    )
    state = {"WORK_UNITS": [dependency, dependent]}

    assert module._done_worker_result_terminal(dependency) is True
    assert module._dependency_satisfied(dependency) is True
    assert [unit["id"] for unit in module._runnable_work_units(state)] == ["WU-002"]
    assert module._select_work_unit_batch(state) == ["WU-002"]
    assert dependent["status"] == "RUNNING"


def test_r8_all_multiple_dependencies_must_be_canonical_done() -> None:
    first = _r8_canonical_done_unit("WU-A", "Complete the first prerequisite")
    second = _r8_canonical_done_unit("WU-B", "Complete the second prerequisite")
    second["next_action"] = "Retry validation"
    dependent = module._new_work_unit(
        "WU-C", "Run after both prerequisites", dependencies=["WU-A", "WU-B"],
    )
    state = {"WORK_UNITS": [first, second, dependent]}

    assert module._done_worker_result_terminal(first) is True
    assert module._done_worker_result_terminal(second) is False
    assert module._runnable_work_units(state) == []

    second["next_action"] = "No further action"

    assert module._done_worker_result_terminal(second) is True
    assert [unit["id"] for unit in module._runnable_work_units(state)] == ["WU-C"]


def test_r8_mixed_graph_runs_only_unrelated_ready_unit() -> None:
    dependency = _r8_canonical_done_unit("WU-A", "Complete the prerequisite")
    dependency["blocker"] = {"code": "LOCAL_BLOCKER", "detail": "unresolved"}
    dependent = module._new_work_unit(
        "WU-B", "Run after the prerequisite", dependencies=["WU-A"], optional=True,
    )
    unrelated = module._new_work_unit("WU-C", "Run independent authorized work")
    already_running = module._new_work_unit("WU-D", "Continue already-running work")
    already_running["status"] = "RUNNING"
    state = {"WORK_UNITS": [dependency, dependent, unrelated, already_running]}

    assert [unit["id"] for unit in module._runnable_work_units(state)] == ["WU-C"]
    assert module._select_work_unit_batch(state) == ["WU-C"]
    assert dependent["status"] == "READY"
    assert dependent["attempts"] == 0
    assert unrelated["status"] == "RUNNING"
    assert already_running["status"] == "RUNNING"


def test_r8_deferred_dependency_reopens_only_for_canonical_done() -> None:
    dependency = _r8_canonical_done_unit("WU-001", "Complete the prerequisite")
    dependency.update({
        "blocker": {"code": "LOCAL_BLOCKER", "detail": "unresolved"},
        "next_action": "Retry validation",
    })
    dependent = module._new_work_unit(
        "WU-002", "Run only after the prerequisite", dependencies=["WU-001"],
    )
    dependent.update({
        "status": "DEFERRED",
        "blocker": {"code": "DEPENDENCY_UNAVAILABLE", "dependencies": ["WU-001"]},
        "last_checkpoint": "DEFERRED_BY_DEPENDENCY",
    })
    state = {"WORK_UNITS": [dependency, dependent]}
    blocker_before = dict(dependent["blocker"])

    assert module._reconsider_dependency_deferred_units(state) == 0
    assert dependent["status"] == "DEFERRED"
    assert dependent["blocker"] == blocker_before

    dependency["blocker"] = {}
    dependency["next_action"] = "No further action"

    assert module._done_worker_result_terminal(dependency) is True
    assert module._reconsider_dependency_deferred_units(state) == 1
    assert dependent["status"] == "READY"
    assert dependent["blocker"] == {}


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
    audit.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
    })
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
    assert all(
        Path(observed["env"][name]).resolve() == runtime / "temp"
        for name in ("TEMP", "TMP", "TMPDIR")
    )
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
        assert Path(observed["env"][name]).resolve() == runtime / "temp"
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
    assert all(
        Path(observed["env"][name]).resolve() == runtime / "temp"
        for name in ("TEMP", "TMP", "TMPDIR")
    )
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


def _contract_lifecycle_state(
    isolated_roots: tuple[Path, Path], *, minimum_hours: float = 4.0,
    substantive_hours: float = 1.5, remaining_hours: float = 4.0,
) -> tuple[dict, Path]:
    state = create_state(
        goal=f"Run bounded pre-2026 research\nMIN_SUBSTANTIVE_RESEARCH_HOURS={minimum_hours:g}"
    )
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True, exist_ok=True)
    done = module._new_work_unit("WU-001", "Complete the initial authorized research")
    done.update({
        "status": "DONE", "validation_state": "PASS",
        "last_checkpoint": "COMPLETED", "next_action": "No further action",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "CURRENT_PHASE": "AUTONOMOUS_EXECUTION_LOOP",
        "NEXT_ACTION_CODE": "SELECT_WORK", "WORKTREE": str(worktree),
        "WORK_UNITS": [done], "MIN_SUBSTANTIVE_RUNTIME_HOURS": minimum_hours,
        "DEADLINE_AT": (
            module.datetime.now(module.timezone.utc)
            + module.timedelta(hours=remaining_hours)
        ).isoformat(),
        "TIME_BUDGET_HOURS": max(remaining_hours, minimum_hours),
    })
    state["TELEMETRY"]["worker_wall_seconds"] = substantive_hours * 3600.0
    state["TELEMETRY"]["substantive_worker_seconds"] = substantive_hours * 3600.0
    module._write_state_unlocked("test-task", state)
    return state, worktree


def _stop_on_dispatched_worker(
    observed: list[dict], task_id: str, prompt: str, review: bool = False, role: str = "",
) -> dict:
    current = module.load_state(task_id)
    observed.append({
        "phase": current["CURRENT_PHASE"],
        "active": list(current["ACTIVE_WORK_UNIT_IDS"]),
        "prompt": prompt,
    })
    module.update_task(task_id, {
        "STOP_REQUESTED": True, "WORKER_PID": None, "ACTIVE_PROCESS_KIND": "",
        "ACTIVE_THREAD_ID": "", "WORKER_FINDINGS": "TASK_RESULT=COMPLETED\nBLOCKER_KIND=NONE",
    })
    return {"exit_code": 0, "message": "stopped at synthetic checkpoint", "tests": []}


def test_substantive_runtime_uses_only_canonical_worker_accounting() -> None:
    state = {
        "GOAL": "MIN_SUBSTANTIVE_RESEARCH_HOURS=4",
        "MIN_SUBSTANTIVE_RUNTIME_HOURS": 4.0,
        "WORKER_FINDINGS": "Caller claims SUBSTANTIVE_RUNTIME_HOURS=99.0",
        "TELEMETRY": {
            "worker_wall_seconds": 14_400.0,
            "substantive_worker_seconds": 5_400.0,
            "reviewer_wall_seconds": 3_600.0,
            "planner_wall_seconds": 1_800.0,
            "worker_idle_seconds": 1_200.0,
            "worker_validation_seconds": 6_000.0,
        },
    }
    assert module._canonical_substantive_worker_seconds(state) == 5_400.0
    assert module._runtime_contract_remaining_seconds(state) == 9_000.0
    assert module._non_substantive_worker_command_kind("Start-Sleep -Seconds 3600") == "IDLE"
    assert module._non_substantive_worker_command_kind("python -m pytest -q tests/test_x.py") == "VALIDATION"
    assert module._non_substantive_worker_command_kind("git diff --check") == "VALIDATION"


def test_runtime_unmet_with_time_remaining_dispatches_productive_continuation_without_human_wait(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _contract_lifecycle_state(isolated_roots)
    observed: list[dict] = []
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "runtime-progress")
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda task_id, prompt, review=False, role="": _stop_on_dispatched_worker(
            observed, task_id, prompt, review, role,
        ),
    )

    module._dispatch("test-task")

    final = module.load_state("test-task")
    continuation = next(unit for unit in final["WORK_UNITS"] if unit.get("continuation_kind"))
    assert observed and observed[0]["phase"] == "AUTONOMOUS_EXECUTION_LOOP"
    assert observed[0]["active"] == [continuation["id"]]
    assert continuation["continuation_kind"] == "MIN_SUBSTANTIVE_RUNTIME_UNMET"
    assert "materially distinct" in continuation["required_next_work"]
    assert "do not sleep" in continuation["required_next_work"]
    assert final["WORK_UNITS"][0]["status"] == "DONE"
    assert final["HARNESS_STATE"] == "STOPPED"
    assert "WAITING_HUMAN" not in module.timeline_path("test-task").read_text(encoding="utf-8")


def test_research_breadth_unmet_queues_autonomous_continuation(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _ = _contract_lifecycle_state(
        isolated_roots, minimum_hours=1.0, substantive_hours=1.0,
    )
    state["NEXT_ACTION_CODE"] = "FINAL_REVIEW"
    module._write_state_unlocked("test-task", state)
    observed: list[dict] = []

    def breadth_review(task_id: str) -> str:
        return record_fake_review(
            task_id, "FIX_REQUIRED",
            "RESEARCH_BREADTH_UNMET: mechanism families and information-set categories "
            "remain below the authorized contract; add distinct in-scope research.",
        )

    monkeypatch.setattr(module, "_perform_review", breadth_review)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "breadth-progress")
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda task_id, prompt, review=False, role="": _stop_on_dispatched_worker(
            observed, task_id, prompt, review, role,
        ),
    )

    module._dispatch("test-task")

    final = module.load_state("test-task")
    continuation = next(unit for unit in final["WORK_UNITS"] if unit.get("continuation_kind"))
    assert continuation["continuation_kind"] == "RESEARCH_BREADTH_UNMET"
    assert observed and observed[0]["active"] == [continuation["id"]]
    assert final["HARNESS_STATE"] == "STOPPED"


def test_reviewer_fix_required_runs_correction_before_another_final_review(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _ = _contract_lifecycle_state(
        isolated_roots, minimum_hours=1.0, substantive_hours=1.0,
    )
    state["NEXT_ACTION_CODE"] = "FINAL_REVIEW"
    module._write_state_unlocked("test-task", state)
    calls = {"review": 0, "worker": 0}

    def fix_review(task_id: str) -> str:
        calls["review"] += 1
        return record_fake_review(
            task_id, "FIX_REQUIRED",
            "AssertionError in scripts/maintenance/harness_task.py requires an in-scope correction.",
        )

    def correction_worker(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        calls["worker"] += 1
        return _stop_on_dispatched_worker([], task_id, prompt, review, role)

    monkeypatch.setattr(module, "_perform_review", fix_review)
    monkeypatch.setattr(module, "_run_codex_turn", correction_worker)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "fix-progress")

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert calls == {"review": 1, "worker": 1}
    assert any(unit["id"].startswith("FIX-") and unit["status"] == "RUNNING" for unit in final["WORK_UNITS"])
    events = [
        json.loads(row)["event"]
        for row in module.timeline_path("test-task").read_text(encoding="utf-8").splitlines()
    ]
    assert events.index("FINAL_REVIEW_CORRECTION_GENERATED") < events.index("TASK_STOPPED")


def test_genuine_authorization_boundary_still_waits_for_human(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Perform an action that may exceed authorization")
    unit["status"] = "RUNNING"
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER", "WORKTREE": str(worktree),
        "WORK_UNITS": [unit], "ACTIVE_WORK_UNIT_IDS": ["WU-001"],
        "ACTIVE_WORK_UNIT_ID": "WU-001",
    })
    module._write_state_unlocked("test-task", state)

    def authorization_boundary(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        findings = (
            "TASK_RESULT=BLOCKED\nBLOCKER_KIND=SAFETY\n"
            "Human authorization is required because the requested action exceeds the user-approved scope."
        )
        module.update_task(task_id, {
            "WORKER_FINDINGS": findings, "WORKER_PID": None,
            "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
        })
        return {"exit_code": 0, "message": findings, "tests": []}

    monkeypatch.setattr(module, "_run_codex_turn", authorization_boundary)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "authorization-progress")
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })

    module._dispatch("test-task")

    waiting = module.load_state("test-task")
    assert waiting["HARNESS_STATE"] == "WAITING_HUMAN"
    assert waiting["HUMAN_ATTENTION_REQUIRED"] is True
    assert waiting["ACTIVE_BLOCKERS"][0]["boundary_kind"] == "SAFETY"


def test_runtime_unmet_that_cannot_fit_deadline_fails_honestly_without_dispatch(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _contract_lifecycle_state(isolated_roots, remaining_hours=1.0)
    calls = {"worker": 0, "review": 0}
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda *args, **kwargs: calls.update(worker=calls["worker"] + 1),
    )
    monkeypatch.setattr(
        module, "_perform_review",
        lambda task_id: calls.update(review=calls["review"] + 1),
    )
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert calls == {"worker": 0, "review": 0}
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_REASON"] == "CONTRACT_UNSATISFIED_AT_DEADLINE"
    assert final["TERMINAL_SUCCESS"] is False
    assert final["HUMAN_ATTENTION_REQUIRED"] is False


def test_repeated_identical_runtime_continuation_without_progress_converges_non_successfully(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _contract_lifecycle_state(isolated_roots)
    calls = {"worker": 0}

    def no_progress_worker(task_id: str, prompt: str, review: bool = False, role: str = "") -> dict:
        calls["worker"] += 1
        current = module.load_state(task_id)
        unit_id = current["ACTIVE_WORK_UNIT_IDS"][0]
        row = {
            "id": unit_id, "status": "RETRY", "produced_outputs": [],
            "validation_state": "PASS",
            "blocker": {
                "kind": "LOCAL", "signature": "MIN_SUBSTANTIVE_RUNTIME_UNMET",
                "detail": "MIN_SUBSTANTIVE_RUNTIME_UNMET: canonical productive work did not advance",
            },
            "last_checkpoint": "NO_CANONICAL_PROGRESS",
            "next_action": "Try a materially different productive mechanism",
            "reuse_decision": "EXTEND", "reuse_evidence": ["existing task"],
        }
        findings = (
            "TASK_RESULT=BLOCKED\nHOLDOUT_CONTAMINATION_RISK=NONE\nBLOCKER_KIND=LOCAL\n"
            f"WORK_UNIT_RESULTS_JSON={json.dumps([row], separators=(',', ':'))}\n"
            "CHANGED_PATHS_JSON=[]\nNEW_COMPONENT_JUSTIFICATION=NONE\n"
            "MIN_SUBSTANTIVE_RUNTIME_UNMET"
        )
        module.update_task(task_id, {
            "WORKER_FINDINGS": findings, "PENDING_UNIT_RESULTS": [row],
            "WORKER_PID": None, "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
            "WORKER_TEST_STATUS": "PASS",
        })
        return {"exit_code": 0, "message": findings, "tests": []}

    monkeypatch.setattr(module, "_run_codex_turn", no_progress_worker)
    monkeypatch.setattr(module, "_run_unit_validation", lambda task_id: (True, "PASS"))
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "unchanged")
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [], "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert 1 < calls["worker"] <= module.DEFAULT_FAILURE_RETRY_LIMIT + 2
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "NO_PROGRESS_RETRY_EXHAUSTED"
    assert final["TERMINAL_REASON"] == "AUTONOMOUS_CORRECTION_NO_PROGRESS"
    assert final["HUMAN_ATTENTION_REQUIRED"] is False


def test_already_valid_completed_contract_has_no_lifecycle_regression(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _ = _contract_lifecycle_state(
        isolated_roots, minimum_hours=1.0, substantive_hours=1.0,
    )
    state["NEXT_ACTION_CODE"] = "FINAL_VALIDATION"
    module._write_state_unlocked("test-task", state)
    calls = {"validation": 0, "review": 0}

    def final_validation(task_id: str) -> tuple[bool, str]:
        calls["validation"] += 1
        module.update_task(task_id, {"CONTROLLER_VALIDATION_STATUS": "PASS"})
        return True, "PASS"

    def final_review(task_id: str) -> str:
        calls["review"] += 1
        return record_fake_review(task_id, "PASS", "No blocking findings.")

    monkeypatch.setattr(module, "_run_final_validation", final_validation)
    monkeypatch.setattr(module, "_perform_review", final_review)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "valid-progress")
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/harness_task.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert calls == {"validation": 1, "review": 1}
    assert final["HARNESS_STATE"] == "COMPLETED"
    assert final["TERMINAL_SUCCESS"] is True
    assert not any(unit.get("continuation_kind") for unit in final["WORK_UNITS"])


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
        return record_fake_review(
            task_id, "FIX_REQUIRED",
            "Task incomplete: no reviewable output and mandatory work remains blocked.",
        )

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
        done = status == "DONE"
        return {
            "id": unit_id, "status": status, "produced_outputs": [f"checkpoint/{unit_id}"],
            "validation_state": "PASS" if done else "WORKER_CHECKPOINT",
            "blocker": blocker or {},
            "last_checkpoint": (
                f"TURN_{len(worker_batches) + 1}_COMPLETED"
                if done else f"TURN_{len(worker_batches) + 1}"
            ),
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
            5: ["WU-009"],
            6: ["WU-010"],
            7: ["FIX-001"],
            8: ["FIX-002"],
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
        elif turn == 5:
            rows = [result_row("WU-009", "DONE")]
            task_result, exit_code = "COMPLETED", 0
        elif turn == 6:
            rows = [result_row("WU-010", "DONE")]
            task_result, exit_code = "COMPLETED", 0
        else:
            rows = [result_row(active[0], "DONE")]
            task_result, exit_code = "COMPLETED", 0
        message = (
            f"TASK_RESULT={task_result}\nHOLDOUT_CONTAMINATION_RISK=NONE\n"
            f"BLOCKER_KIND={'LOCAL' if task_result == 'BLOCKED' else 'NONE'}\n"
            f"WORK_UNIT_RESULTS_JSON={json.dumps(rows, separators=(',', ':'))}\n"
            "CHANGED_PATHS_JSON=[\"scripts/existing_shared_utility.py\"]\n"
            "NEW_COMPONENT_JUSTIFICATION=NONE"
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
        return record_fake_review(
            task_id, classification, findings,
            CURRENT_PHASE="FINAL_INDEPENDENT_REVIEW",
        )

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
    assert validation_calls == {"unit": 8, "final": 2, "review": 1, "cleanup": 1}
    assert len(final["WORK_UNITS"]) == 12
    assert module._work_unit_counts(final) == {
        "total": 12, "done": 11, "runnable": 0, "local_blocked": 1, "deferred": 0,
    }
    assert "WU-001" not in worker_batches[1:] and "WU-003" not in worker_batches[1:]
    assert worker_batches.count(["FIX-001"]) == 1
    assert worker_batches.count(["FIX-002"]) == 1
    assert final["TELEMETRY"]["duplicate_planned_work_rejected"] == 1
    assert final["TELEMETRY"]["reuse_hits"] == 4  # planned reuse plus two in-place corrections
    assert final["TELEMETRY"]["local_blockers_bypassed"] == 2
    assert final["TELEMETRY"]["repeated_work_prevented"] == 1
    correction = next(unit for unit in final["WORK_UNITS"] if unit["id"] == "FIX-002")
    assert final["LAST_REVIEW_FINDING_IDENTITY"] == correction["review_finding_identity"]
    assert final["REVIEW_CORRECTION_DISPOSITION"] == "REVIEW_SKIPPED_NO_MATERIAL_PROGRESS"
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
    assert "FINAL_REVIEW_SKIPPED_NO_MATERIAL_PROGRESS" in events
    assert "WAITING_HUMAN" not in events


@pytest.mark.parametrize(
    "goal",
    [
        "Run synthetic tests using 2026 dates.",
        "Run synthetic 2026 timestamp tests.",
        "Run mock fixtures with 2026-01-01 dates.",
    ],
)
def test_synthetic_dates_do_not_require_a_real_evaluation_contract(goal: str) -> None:
    contract = module._task_contract(goal, "auto", "independent-code")
    assert contract["TASK_SCOPE"] == "independent-code"
    assert contract["TASK_KIND"] == "independent-code"
    assert module.hard_guard_conflicts(goal) == []


def test_synthetic_fixture_context_does_not_hide_real_outcome_selection() -> None:
    goal = (
        "Run synthetic tests using 2026 dates; "
        "use 2026 outcomes to select the model."
    )
    contract = module._task_contract(goal, "maintenance", "independent-code")
    assert contract["TASK_SCOPE"] == "2026-optimization"
    assert module.hard_guard_conflicts(goal) == ["EXPOSED_2026_OPTIMIZATION"]
    assert module.infer_scope(
        "Run synthetic tests using real 2026 outcomes.", "independent-code",
    ) == "2026-evaluation"


@pytest.mark.parametrize(
    "goal",
    [
        "Run synthetic 2026 fixtures on canonical market data.",
        "Run synthetic tests using 2026 dates from actual market returns.",
        "Run synthetic 2026 tests using a mixed-year file.",
        "Run synthetic tests using 2026 dates from an unknown source.",
        "Run synthetic tests using 2026 dates; read the existing returns file.",
    ],
)
def test_synthetic_date_source_qualifications_keep_evaluation_scope(goal: str) -> None:
    assert module.infer_scope(goal, "independent-code") == "2026-evaluation"


@pytest.mark.parametrize(
    ("goal", "expected_code", "expected_scope"),
    [
        ("Run synthetic tests using 2026 dates.", 0, "independent-code"),
        ("Run synthetic 2026 timestamp tests.", 0, "independent-code"),
        ("Run mock fixtures with 2026-01-01 dates.", 0, "independent-code"),
        ("Run synthetic 2026 fixtures on canonical market data.", 2, "2026-evaluation"),
        ("Run synthetic tests using 2026 dates from actual market returns.", 2, "2026-evaluation"),
        ("Run synthetic 2026 tests using a mixed-year file.", 2, "2026-evaluation"),
        ("Run synthetic tests using 2026 dates from an unknown source.", 2, "2026-evaluation"),
        ("Run synthetic tests using 2026 dates; use 2026 outcomes to select the model.", 2, "2026-optimization"),
    ],
)
def test_governance_date_request_real_start_stops_before_external_execution(
    goal: str, expected_code: int, expected_scope: str,
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Execute the real public start handler and state writes in existing external
    # fixtures; sentinels protect the handoff, not arbitrary operating-system I/O.
    for name in (
        "_load_prospective_lifecycle", "_load_r1", "_storage_paths",
        "_discover_existing", "_create_worktree", "_run_codex_turn", "run_task",
    ):
        monkeypatch.setattr(module, name, lambda *args, _name=name, **kwargs: pytest.fail(_name))
    launches: list[str] = []
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: launches.append(task_id) or 4242)
    args = argparse.Namespace(
        goal=goal, task_id="governance-date-start", task_kind="auto",
        task_scope="independent-code", max_corrections=2, foreground=False,
    )
    assert module.command_start(args) == expected_code
    state = module.load_state(args.task_id)
    assert state["TASK_SCOPE"] == expected_scope
    if expected_code == 0:
        assert launches == [args.task_id]
        assert state["RESEARCH_START_DECISION"] == "NOT_APPLICABLE_NON_RESEARCH_TASK"
    else:
        assert launches == []
        assert state["HARNESS_STATE"] == "BLOCKED"


@pytest.mark.parametrize("scope", ["pre2026-research", "2026-evaluation", "2026-optimization", "all"])
def test_effective_research_scope_cannot_skip_lifecycle_with_maintenance_kind(
    scope: str, isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: pytest.fail("no research spec was supplied"))
    monkeypatch.setattr(module, "_spawn_supervisor", lambda *args: pytest.fail("research gate must block"))
    args = argparse.Namespace(
        goal="Inspect the requested task contract.", task_id="scope-gate",
        task_kind="maintenance", task_scope=scope,
        max_corrections=2, foreground=False,
    )
    assert module.command_start(args) == 2
    state = module.load_state(args.task_id)
    assert state["TASK_KIND"] == "maintenance"
    assert state["TASK_SCOPE"] == scope
    assert state["HARNESS_STATE"] == "BLOCKED"
    assert not module._research_start_gate_passed(state)
    state["RESEARCH_START_DECISION"] = "ALLOW_NEW_RESEARCH"
    assert module._research_start_gate_passed(state)
    assert "PROSPECTIVE RESEARCH COMPLETION CONTRACT" in module._worker_prompt(state)


@pytest.mark.parametrize("requested_scope", ["independent-code", "frozen-dependent"])
def test_actual_training_action_cannot_use_maintenance_kind_to_skip_start_gate(
    requested_scope: str, isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: pytest.fail("missing spec must block first"))
    monkeypatch.setattr(module, "_spawn_supervisor", lambda *args: pytest.fail("research cannot dispatch"))
    monkeypatch.setattr(module, "_run_codex_turn", lambda *args, **kwargs: pytest.fail("research cannot dispatch"))
    args = argparse.Namespace(
        goal="Train a model on pre-2026 data.", task_id="maintenance-training",
        task_kind="maintenance", task_scope=requested_scope,
        max_corrections=2, foreground=False,
    )
    assert module.command_start(args) == 2
    state = module.load_state(args.task_id)
    expected_scope = "frozen-dependent" if requested_scope == "frozen-dependent" else "pre2026-research"
    assert state["TASK_SCOPE"] == expected_scope
    assert state["SAFETY_FLAGS"]["MODEL_TRAINING_OR_SELECTION"] is True
    assert not module._research_start_gate_passed(state)
    with pytest.raises(module.HarnessError, match="RESEARCH_START_GATE_NOT_PASSED_AT_FINALIZATION"):
        module._prepare_prospective_completion(args.task_id)
    state.update({"HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "WORKER"})
    module._write_state_unlocked(args.task_id, state)
    module._dispatch(args.task_id)
    blocked = module.load_state(args.task_id)
    assert blocked["HARNESS_STATE"] == "BLOCKED"
    assert any(row["code"] == "RESEARCH_START_GATE_NOT_PASSED" for row in blocked["ACTIVE_BLOCKERS"])


def test_frozen_hash_only_engineering_does_not_require_research_lifecycle(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: pytest.fail("engineering task must not load research lifecycle"))
    calls: list[str] = []
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: calls.append(task_id) or 4242)
    args = argparse.Namespace(
        goal="Validate frozen baseline hashes.", task_id="frozen-hash-engineering",
        task_kind="maintenance", task_scope="frozen-dependent",
        max_corrections=2, foreground=False,
    )
    assert module.command_start(args) == 0
    state = module.load_state(args.task_id)
    assert state["TASK_SCOPE"] == "frozen-dependent"
    assert state["RESEARCH_START_DECISION"] == "NOT_APPLICABLE_NON_RESEARCH_TASK"
    assert calls == [args.task_id]
    assert module._prepare_prospective_completion(args.task_id) is None


def test_unknown_scope_cannot_skip_start_or_dispatch_gate(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_spawn_supervisor", lambda *args: pytest.fail("unknown scope cannot dispatch"))
    args = argparse.Namespace(
        goal="Inspect one parser.", task_id="unknown-scope", task_kind="maintenance",
        task_scope="unrecognized-scope", max_corrections=2, foreground=False,
    )
    with pytest.raises(module.HarnessError, match="UNKNOWN_TASK_SCOPE"):
        module.command_start(args)
    assert not module.task_dir(args.task_id).exists()
    with pytest.raises(module.HarnessError, match="UNKNOWN_TASK_SCOPE"):
        module._research_start_gate_passed({"TASK_KIND": "maintenance", "TASK_SCOPE": "unrecognized-scope"})


def test_outcome_blind_preflight_optimization_blocker_is_classified_as_overfit() -> None:
    overfit, _ = module._guard_summary({
        "task_scope": "2026-optimization", "applicable_hard_blocker_count": 1,
        "findings": [{
            "level": "HARD_BLOCKER", "code": "2026_OPTIMIZATION_FORBIDDEN",
            "blocks": ["2026-optimization"], "detail": "No outcome read is needed.",
        }],
    })
    assert overfit == "HARD_BLOCKER"


def test_unchecked_research_content_is_not_reported_as_overfit_pass() -> None:
    overfit, anti = module._guard_summary({
        "task_scope": "independent-code", "applicable_hard_blocker_count": 0,
        "findings": [{"level": "INFORMATIONAL", "code": "RESEARCH_CONTENT_CHECKS_NOT_CHECKED",
                      "detail": "not checked", "blocks": []}],
    })
    assert overfit == "NOT_CHECKED_FOR_SCOPE"
    assert anti == "PASS"


def test_all_harness_roles_route_to_the_same_project_instructions() -> None:
    state = module._new_state("test-task", "Repair one parser", "independent-code", 2)
    for prompt in (
        module._planner_prompt(state), module._worker_prompt(state),
        module._review_prompt(state),
    ):
        assert module.PROJECT_INSTRUCTION_ROUTING in prompt
        assert prompt.count(module.PROJECT_INSTRUCTION_ROUTING) == 1
    worker = module._worker_prompt(state)
    assert "Report RETRY when repair remains" in worker
    assert "never weaken a guard or frozen expectation" in worker


def test_negative_frozen_constraints_do_not_create_dependency_scope() -> None:
    goal = "Harness-only discovery fix; do not touch frozen outputs; do not modify frozen baselines; avoid canonical data."
    assert module.infer_scope(goal, "independent-code") == "independent-code"


def test_real_frozen_dependency_remains_conservative() -> None:
    goal = "Validate this change against the frozen baseline without modifying it."
    assert module.infer_scope(goal, "independent-code") == "frozen-dependent"


def test_harness_temp_roots_are_external_to_repository(isolated_roots: tuple[Path, Path]) -> None:
    state, worktrees = isolated_roots
    test_root = state.parents[1]
    runtime = module.task_temp_runtime("test-task")
    layout = module._task_runtime_paths(runtime)
    for owned_root in (test_root, state, worktrees, runtime, *layout.values()):
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
    layout = module._task_runtime_paths(runtime)
    assert prepared == runtime
    assert (runtime / module.TASK_TEMP_OWNER_MARKER).is_file()
    assert all(path.is_dir() for path in layout.values())
    assert layout == {
        "temp": runtime / "temp",
        "cache": runtime / "cache",
        "pytest_cache": runtime / "pytest" / "cache",
        "pytest_basetemp": runtime / "pytest" / "basetemp",
    }
    assert not list(runtime.glob(".write-probe-*.tmp"))
    assert not list(runtime.rglob(".write-probe-*.tmp"))
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
    layout = module._task_runtime_paths(runtime)

    for name in ("TEMP", "TMP", "TMPDIR"):
        assert Path(environment[name]).resolve() == layout["temp"]
    assert Path(environment["USTQ_CACHE_ROOT"]).resolve() == layout["cache"]
    assert Path(environment["US_TECH_QUANT_TEST_TMP_ROOT"]).resolve() == layout["temp"]
    assert Path(environment["USTQ_HARNESS_RUNTIME_ROOT"]).resolve() == runtime
    assert Path(environment["USTQ_HARNESS_PYTEST_CACHE_ROOT"]).resolve() == layout["pytest_cache"]
    assert Path(environment["USTQ_HARNESS_PYTEST_BASETEMP_ROOT"]).resolve() == layout["pytest_basetemp"]
    assert Path(environment["PYTEST_DEBUG_TEMPROOT"]).resolve() == layout["temp"]
    assert "scripts.maintenance.harness_task" in environment["PYTEST_PLUGINS"].split(",")
    assert str(module.SCRIPT.resolve().parents[2]) in environment["PYTHONPATH"].split(module.os.pathsep)
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTEST_ADDOPTS"] == (
        f"--basetemp={layout['pytest_basetemp'].as_posix()} "
        f"-o=cache_dir={layout['pytest_cache'].as_posix()}"
    )

    python_probe = subprocess.run(
        [
            sys.executable, "-B", "-c",
            "import tempfile; from pathlib import Path; "
            "root=Path(tempfile.gettempdir()).resolve(); "
            "handle=tempfile.NamedTemporaryFile(delete=False); name=Path(handle.name); "
            "handle.write(b'ok'); handle.close(); print(root); print(name.resolve().parent); name.unlink()",
        ],
        cwd=runtime, env=environment, text=True, capture_output=True, check=False, timeout=30,
    )
    assert python_probe.returncode == 0, python_probe.stderr
    python_paths = [Path(value).resolve() for value in python_probe.stdout.splitlines()]
    assert python_paths == [layout["temp"], layout["temp"]]

    probe_dir = runtime / "pytest-probe"
    probe_dir.mkdir()
    probe_test = probe_dir / "test_temp_runtime.py"
    probe_test.write_text(
        "import os\nimport tempfile\nfrom pathlib import Path\n\n"
        "def test_external_tmp_path(tmp_path):\n"
        "    assert Path(tempfile.gettempdir()).resolve() == Path(os.environ['TEMP']).resolve()\n"
        "    (tmp_path / 'writable.txt').write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    pytest_probe = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-q", str(probe_test),
        ],
        cwd=runtime, env=environment, text=True, capture_output=True, check=False, timeout=60,
    )
    assert pytest_probe.returncode == 0, pytest_probe.stdout + pytest_probe.stderr
    assert (layout["pytest_cache"] / "v" / "cache" / "nodeids").is_file()
    assert list(layout["pytest_basetemp"].rglob("writable.txt"))
    assert not (runtime / ".pytest_cache").exists()
    assert not (module.REPO / ".pytest_cache").exists()
    assert not list(module.REPO.glob("pytest-cache-files-*"))

    rejected_basetemp = runtime / "pytest" / "forbidden-override"
    rejected = subprocess.run(
        [
            sys.executable, "-B", "-m", "pytest", "-q",
            "--basetemp", str(rejected_basetemp), str(probe_test),
        ],
        cwd=runtime, env=environment, text=True, capture_output=True, check=False, timeout=60,
    )
    assert rejected.returncode != 0
    assert "PYTEST_RUNTIME_OVERRIDE_REJECTED" in rejected.stdout + rejected.stderr
    assert not rejected_basetemp.exists()

    module._cleanup_task_temp_runtime("test-task")
    assert not runtime.exists()


def test_nested_subprocess_inherits_task_temp_environment(
    isolated_roots: tuple[Path, Path],
) -> None:
    create_state()
    runtime = module._ensure_task_temp_runtime("test-task")
    environment = module._task_temp_environment(runtime)
    layout = module._task_runtime_paths(runtime)
    grandchild = (
        "import json, os, tempfile; from pathlib import Path; "
        "handle=tempfile.NamedTemporaryFile(delete=False); name=Path(handle.name).resolve(); "
        "handle.write(b'nested'); handle.close(); "
        "print(json.dumps({'temp': str(name), 'TEMP': os.environ['TEMP'], "
        "'TMP': os.environ['TMP'], 'TMPDIR': os.environ['TMPDIR']})); name.unlink()"
    )
    parent = (
        "import subprocess, sys; "
        f"result=subprocess.run([sys.executable, '-B', '-c', {grandchild!r}], "
        "text=True, capture_output=True, check=False); "
        "print(result.stdout.strip()); print(result.stderr, file=sys.stderr); "
        "raise SystemExit(result.returncode)"
    )

    result = subprocess.run(
        [sys.executable, "-B", "-c", parent], cwd=runtime, env=environment,
        text=True, capture_output=True, check=False, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert Path(observed["temp"]).resolve().parent == layout["temp"]
    assert {
        Path(observed[name]).resolve() for name in ("TEMP", "TMP", "TMPDIR")
    } == {layout["temp"]}
    module._cleanup_task_temp_runtime("test-task")


def test_parallel_task_runtime_isolation_and_task_scoped_cleanup(
    isolated_roots: tuple[Path, Path],
) -> None:
    synthetic_task_ids = {
        "TEMP_GOV_TEST_A": "temp-gov-test-a",
        "TEMP_GOV_TEST_B": "temp-gov-test-b",
    }
    for task_id in synthetic_task_ids.values():
        create_state(task_id)

    runtime_a = module._ensure_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_A"])
    runtime_b = module._ensure_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_B"])
    layout_a = module._task_runtime_paths(runtime_a)
    layout_b = module._task_runtime_paths(runtime_b)
    assert runtime_a != runtime_b
    assert all(layout_a[name] != layout_b[name] for name in layout_a)

    keep_a = layout_a["temp"] / "TEMP_GOV_TEST_A.keep"
    keep_b = layout_b["temp"] / "TEMP_GOV_TEST_B.keep"
    keep_a.write_text("A", encoding="utf-8")
    keep_b.write_text("B", encoding="utf-8")
    module._cleanup_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_A"])
    assert not runtime_a.exists()
    assert keep_b.read_text(encoding="utf-8") == "B"

    runtime_a = module._ensure_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_A"])
    keep_a = module._task_runtime_paths(runtime_a)["temp"] / "TEMP_GOV_TEST_A.keep"
    keep_a.write_text("A", encoding="utf-8")
    module._cleanup_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_B"])
    assert not runtime_b.exists()
    assert keep_a.read_text(encoding="utf-8") == "A"
    module._cleanup_task_temp_runtime(synthetic_task_ids["TEMP_GOV_TEST_A"])


def test_foreign_runtime_owner_prevents_cleanup(
    isolated_roots: tuple[Path, Path],
) -> None:
    create_state()
    runtime = module._ensure_task_temp_runtime("test-task")
    marker = runtime / module.TASK_TEMP_OWNER_MARKER
    marker.write_text(
        json.dumps({"task_id": "other-task", "runtime": str(runtime)}), encoding="utf-8",
    )

    with pytest.raises(module.HarnessError, match="WORKER_TEMP_RUNTIME_CLEANUP_FAILED"):
        module._cleanup_task_temp_runtime("test-task")
    assert runtime.is_dir()

    module._atomic_write(
        marker, module._json_bytes({"task_id": "test-task", "runtime": str(runtime)}),
    )
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
    unit = module._new_work_unit("WU-001", "Complete the bounded repair")
    unit.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further action",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
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


def test_r6_finalization_rejects_missing_work_unit_evidence(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [],
        "dependencies": [], "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_OUTCOME"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False


def test_r6_terminal_local_reconciliation_rejects_nonterminal_done_candidate() -> None:
    state = module._new_state("test-task", "Complete one bounded repair", "independent-code", 2)
    blocker = {
        "kind": "LOCAL",
        "conditions": ["Local validation retry remains unresolved in the sandbox environment"],
    }
    unit = module._new_work_unit("WU-001", "Complete the reviewed maintenance correction")
    unit.update({
        "status": "BLOCKED_LOCAL",
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": "PASS",
        "blocker": blocker,
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    state.update({
        "WORK_UNITS": [unit], "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking review findings."))

    completed, deferred = module._reconcile_terminal_local_environment_units(state)

    assert (completed, deferred) == (0, 0)
    assert unit["status"] == "BLOCKED_LOCAL"
    assert unit["blocker"] == blocker
    assert unit["next_action"] == "Retry validation"
    assert module._done_worker_result_terminal({**unit, "status": "DONE"}) is False


def test_r6_finalization_cannot_override_nonterminal_local_unit(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    blocker = {
        "kind": "LOCAL",
        "conditions": ["Local validation retry remains unresolved in the sandbox environment"],
    }
    unit = module._new_work_unit("FIX-002", "Complete the reviewed maintenance correction")
    unit.update({
        "status": "BLOCKED_LOCAL",
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": "PASS",
        "blocker": blocker,
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    local_evidence = {
        "identity": "historical-local-residue", "work_unit_id": "FIX-002",
        "code": "LOCAL_BLOCKER", "detail": str(blocker), "at": module.utc_now(),
    }
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
        "LOCAL_BLOCKED_WORK": [local_evidence],
    })
    state.update(canonical_review_fields(
        state, "PASS",
        "No blocking findings.",
    ))
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
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_OUTCOME"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False
    assert reconciled["status"] == "BLOCKED_LOCAL"
    assert reconciled["blocker"] == blocker
    assert reconciled["next_action"] == "Retry validation"
    assert final["LOCAL_BLOCKED_WORK"] == [local_evidence]
    assert final["TELEMETRY"]["local_blockers_bypassed"] == 0


def test_r6_r2_compat_finalization_rejects_nonterminal_structured_unit(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = use_r2_compat_state(create_state())
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    blocker = {
        "kind": "LOCAL",
        "conditions": ["Local validation retry remains unresolved"],
    }
    unit = module._new_work_unit("WU-001", "Complete the required repair")
    unit.update({
        "status": "BLOCKED_LOCAL",
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": "PASS", "blocker": blocker,
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "Retry validation",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [],
        "dependencies": [], "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "BLOCKED"
    assert final["ACTIVE_BLOCKERS"][0]["code"] == "INCOMPLETE_REQUIRED_WORK_UNITS"
    assert final["WORK_UNITS"][0]["status"] == "BLOCKED_LOCAL"
    assert final["WORK_UNITS"][0]["blocker"] == blocker
    assert final["WORK_UNITS"][0]["next_action"] == "Retry validation"


def test_r6_finalization_rejects_noncanonical_persisted_done(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete the required repair")
    unit.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE", "next_action": "Retry validation",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert module._done_worker_result_terminal(final["WORK_UNITS"][0]) is False
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_OUTCOME"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False


def test_r6_controller_and_review_pass_cannot_override_required_retry(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete the required repair")
    unit.update({
        "status": "RETRY", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE", "next_action": "Retry validation",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [unit],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["WORK_UNITS"][0]["status"] == "RETRY"
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_OUTCOME"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False


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
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(
        state, "PASS_WITH_WARNINGS",
        "No blocking findings; the incomplete unit is safely deferable.",
    ))
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
    mandatory.update({
        "status": "DONE", "validation_state": "PASS",
        "last_checkpoint": "VALIDATED", "next_action": "No further action",
    })
    optional = module._new_work_unit("WU-002", "Run an optional diagnostic", optional=True)
    optional.update({
        "status": "BLOCKED_LOCAL",
        "blocker": {"code": "OPTIONAL_DIAGNOSTIC_UNAVAILABLE", "detail": "Diagnostic cannot run"},
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [mandatory, optional],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
    })
    state.update(canonical_review_fields(
        state, "PASS_WITH_WARNINGS",
        "No blocking findings; the optional diagnostic remains unavailable.",
    ))
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
        "CONTROLLER_VALIDATION_STATUS": controller,
    })
    state.update(canonical_review_fields(
        state, review,
        "Blocking finding remains." if review == "FIX_REQUIRED" else "No blocking findings.",
    ))
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


def test_unwritable_pytest_basetemp_fails_closed_before_worker_launch(
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
        if path.name == "basetemp":
            raise PermissionError(f"write denied: {path}")
        real_probe(path)

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
    assert "FAIL_EXTERNAL_TEMP_ROOT_UNAVAILABLE" in blocked["BLOCKERS"][-1]["detail"]
    assert str(module.task_temp_runtime("test-task") / "pytest" / "basetemp") in blocked["BLOCKERS"][-1]["detail"]
    assert "HOST_ACL_FAILURE" not in blocked["BLOCKERS"][-1]["detail"]

    monkeypatch.setattr(module, "_probe_temp_runtime", real_probe)
    module._cleanup_task_temp_runtime("test-task")


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("No model training.", "independent-code"),
        ("Maintain launch scripts; no real research or model training.", "independent-code"),
        ("Maintain launch scripts; do not perform research or train a model.", "independent-code"),
        ("No real research or model training, but train a model on pre-2026 data.", "pre2026-research"),
        ("Do not perform research or train a model, but use 2026 holdout outcomes to tune a threshold.", "2026-evaluation"),
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


def test_complete_command_output_precedes_environment_limitation_classification() -> None:
    complete_output = (
        "FAILED focused_test.py::test_value - AssertionError: assert 1 == 2\n"
        + "x" * 9_000
        + "\n"
        + KNOWN_NESTED_PYTEST_TEMP_FAILURE
    )
    event = {"aggregated_output": complete_output}
    captured = module._command_event_output(event)
    results = [{
        "command": "python -m pytest -q focused_test.py",
        "exit_code": 1,
        "output": captured,
    }]

    status, limitation, _ = module._classify_worker_test_execution(results, "", 0)

    assert captured == complete_output
    assert status == "REAL_TEST_FAILURE"
    assert limitation == ""


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
        assert Path(observed_popen["env"][name]).resolve() == runtime / "temp"
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
        return {
            "exit_code": 0, "message": "REVIEW_STATUS=PASS", "tests": [],
            "review_classification": "PASS",
        }

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


@pytest.mark.parametrize("status", ["PASS", "FIX_REQUIRED"])
def test_complete_review_human_boundary_dominates_status_for_all_dispatch_versions(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({"HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree)})
    module._write_state_unlocked("test-task", state)
    fingerprint = {"entry_count": 1, "sha256": "same"}
    monkeypatch.setattr(module, "_repo_status_fingerprint", lambda path: fingerprint)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["reviewed.py"], "created": [], "dependencies": [],
        "changed_count": 1, "created_count": 0,
    })
    authoritative_message = (
        "Human authorization is required before this correction may proceed.\n"
        + "x" * 9_000
        + f"\nREVIEW_STATUS={status}"
    )
    evidence = module._ingest_review_authority_evidence(state, authoritative_message)
    evidence["classification"] = status
    monkeypatch.setattr(module, "_run_codex_turn", lambda *args, **kwargs: {
        "exit_code": 0,
        "message": authoritative_message[-module.MAX_TEXT:],
        "tests": [],
        "review_classification": status,
        "review_authority_evidence": evidence,
    })

    assert module._perform_review("test-task") == "HUMAN_DECISION_REQUIRED"
    reviewed = module.load_state("test-task")
    assert reviewed["REVIEW_AUTHORITY_EVIDENCE"]["requires_human_boundary"] is True
    assert reviewed["REVIEW_CLASSIFICATION"] == "HUMAN_DECISION_REQUIRED"
    assert reviewed["NEXT_ACTION_CODE"] == "FINAL_REVIEW"


def test_controller_targeted_pytest_uses_task_runtime_cache_and_basetemp(
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
    observed: dict = {}

    def successful_run(args, cwd=module.REPO, timeout=30, environment=None):
        observed.update(args=list(args), cwd=cwd, timeout=timeout, environment=environment)
        return subprocess.CompletedProcess(args, 0, "passed", "")

    monkeypatch.setattr(module, "_run", successful_run)
    passed, detail = module._validate_targeted("test-task")
    assert passed is True
    assert detail.startswith("Controller-owned focused pytest:")
    args = observed["args"]
    runtime = module.task_temp_runtime("test-task")
    layout = module._task_runtime_paths(runtime)
    assert "-p" not in args
    base_temp = Path(args[args.index("--basetemp") + 1]).resolve()
    assert base_temp == layout["pytest_basetemp"]
    assert args[args.index("-o") + 1] == f"cache_dir={layout['pytest_cache']}"
    assert module.REPO != base_temp and module.REPO not in base_temp.parents
    environment = observed["environment"]
    assert Path(environment["TEMP"]).resolve() == layout["temp"]
    assert layout["pytest_basetemp"].as_posix() in environment["PYTEST_ADDOPTS"]
    assert layout["pytest_cache"].as_posix() in environment["PYTEST_ADDOPTS"]


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
    assert module.hard_guard_conflicts("Do not attempt to modify frozen asset.") == []
    assert module.hard_guard_conflicts("Do not try to write to canonical data.") == []
    assert module.hard_guard_conflicts(
        "Do not plan to use 2026 outcomes to tune the threshold."
    ) == []


def test_negation_scope_cannot_hide_unrelated_authority_or_safety_actions() -> None:
    assert module._explicit_human_boundary_evidence(
        "No timing issue can arise, human authorization is required."
    ) is True
    assert module.hard_guard_conflicts(
        "This note is not about timing because modify frozen asset."
    ) == ["FROZEN_ASSET_MUTATION"]
    assert module.hard_guard_conflicts(
        "No timing issue can arise, modify canonical data."
    ) == ["CANONICAL_DATA_MUTATION"]
    for instruction in (
        "This note is not about timing because use 2026 outcomes to tune the threshold.",
        "No timing issue can arise, use 2026 outcomes to tune the threshold.",
    ):
        assert module.hard_guard_conflicts(instruction) == ["EXPOSED_2026_OPTIMIZATION"]
    assert module.hard_guard_conflicts(
        "No timing issue, operator can directly modify frozen asset."
    ) == ["FROZEN_ASSET_MUTATION"]
    assert module.hard_guard_conflicts(
        "No timing issue, the worker may modify canonical data."
    ) == ["CANONICAL_DATA_MUTATION"]
    for actor in ("operator", "a worker", "automation", "tooling"):
        assert module.hard_guard_conflicts(
            f"No timing issue and {actor} can modify frozen asset."
        ) == ["FROZEN_ASSET_MUTATION"]
    assert module.hard_guard_conflicts(
        "No timing issue remains, schedule looks clear, and automation can modify frozen asset."
    ) == ["FROZEN_ASSET_MUTATION"]
    assert module.hard_guard_conflicts(
        "No timing concern persists, schedule stayed stable, and tooling may modify canonical data."
    ) == ["CANONICAL_DATA_MUTATION"]
    assert module.hard_guard_conflicts(
        "No timing issue because we can use 2026 outcomes to tune the threshold."
    ) == ["EXPOSED_2026_OPTIMIZATION"]
    assert module.hard_guard_conflicts(
        "No timing issue: we can directly promote it to production."
    ) == ["AUTO_MERGE_OR_PRODUCTION_PROMOTION"]
    for separator in (
        "although", "and", "(", "\u2014",
    ):
        instruction = (
            f"No timing issue {separator} we can modify frozen asset."
            if separator != "(" else
            "No timing issue (we can modify frozen asset)."
        )
        assert module.hard_guard_conflicts(instruction) == ["FROZEN_ASSET_MUTATION"]


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
def local_persisted_start_roots(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
):
    # Reuse the existing external fixture; start-handler tests create no repo temp.
    monkeypatch.setattr(
        module, "_capture_start_repo_identity",
        lambda: ("f" * 40, str(module.REPO.resolve())),
    )
    yield isolated_roots[0].parents[1]


@pytest.mark.parametrize("goal_length", [9_155, 12_000])
def test_start_goal_uses_dedicated_length_limit(
    goal_length: int, local_persisted_start_roots: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    goal = "x" * goal_length
    args = argparse.Namespace(
        goal=goal, task_id=f"goal-{goal_length}", task_kind="maintenance",
        task_scope="independent-code", max_corrections=2, max_hours=None,
        foreground=False,
    )
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: 4242)

    assert module.command_start(args) == 0
    stored = module.load_state(f"goal-{goal_length}")
    assert stored["GOAL"] == goal
    assert stored["START_REPO_HEAD"] == "f" * 40
    assert stored["START_REPO_TOPLEVEL"] == str(module.REPO.resolve())
    assert stored["WORKTREE_BASE_HEAD"] == ""
    assert stored["WORKTREE_ACTUAL_HEAD"] == ""
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "PENDING"


@pytest.mark.parametrize("goal", ["", "x" * 12_001])
def test_start_goal_rejects_empty_or_over_dedicated_limit(goal: str) -> None:
    with pytest.raises(module.HarnessError, match="^GOAL_REQUIRED_MAX_12000_CHARS$"):
        module.command_start(argparse.Namespace(goal=goal))


def test_generic_text_and_steer_limits_remain_unchanged() -> None:
    assert module.MAX_TEXT == 8_000
    assert module.MAX_GOAL_CHARS == 12_000
    with pytest.raises(module.HarnessError, match="^STEER_REQUIRED_MAX_2000_CHARS$"):
        module.command_steer(
            argparse.Namespace(task_id="test-task", instruction="x" * 2_001),
        )


def test_real_goal_start_and_preflight_persist_legal_pre2026_contract(
    local_persisted_start_roots: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    research_spec = local_persisted_start_roots / "legal-research-spec.json"
    research_spec.write_text("{}", encoding="utf-8")
    args = module.build_parser().parse_args([
        "start", "--task-id", "real-goal", "--goal", REAL_PRE2026_DISCOVERY_GOAL,
        "--task-kind", "pre2026-research", "--research-spec", str(research_spec),
        "--max-hours", "8",
    ])
    monkeypatch.setattr(module, "_spawn_supervisor", lambda task_id: 4242)
    monkeypatch.setattr(
        module, "_prospective_start_gate",
        lambda task_id, spec: "ALLOW_NEW_RESEARCH",
    )

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


def _install_pinned_worktree_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    start_head: str,
    mutable_primary_head: str,
    snapshots: dict[str, dict[str, str]],
) -> list[tuple[list[str], Path]]:
    calls: list[tuple[list[str], Path]] = []
    created_source = {"head": ""}

    def fake_git(
        arguments: list[str], cwd: Path = module.REPO, timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(arguments), Path(cwd)))
        if arguments == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(arguments, 0, str(Path(cwd).resolve()), "")
        if arguments == ["rev-parse", "--verify", f"{start_head}^{{commit}}"]:
            return subprocess.CompletedProcess(arguments, 0, start_head + "\n", "")
        if arguments[:3] == ["show-ref", "--verify", "--quiet"]:
            return subprocess.CompletedProcess(arguments, 1, "", "")
        if arguments[:2] == ["worktree", "add"]:
            worktree = Path(arguments[4])
            source = arguments[-1]
            created_source["head"] = source
            worktree.mkdir(parents=True)
            for relative_path, content in snapshots[source].items():
                target = worktree / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return subprocess.CompletedProcess(arguments, 0, "created", "")
        if arguments == ["rev-parse", "HEAD"]:
            value = (
                mutable_primary_head
                if Path(cwd).resolve() == module.REPO.resolve()
                else created_source["head"]
            )
            return subprocess.CompletedProcess(arguments, 0, value + "\n", "")
        if arguments == ["rev-parse", "--git-common-dir"]:
            return subprocess.CompletedProcess(arguments, 0, str(module.REPO / ".git"), "")
        raise AssertionError(f"unexpected git call: {arguments} in {cwd}")

    monkeypatch.setattr(module, "_git", fake_git)
    return calls


def test_worktree_creation_uses_task_start_head_when_primary_advances(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_head = "a" * 40
    advanced_head = "b" * 40
    state = create_state(task_id="pinned-advance")
    state.update({
        "START_REPO_HEAD": start_head,
        "START_REPO_TOPLEVEL": str(module.REPO.resolve()),
    })
    module._write_state_unlocked("pinned-advance", state)
    calls = _install_pinned_worktree_git(
        monkeypatch,
        start_head=start_head,
        mutable_primary_head=advanced_head,
        snapshots={
            start_head: {"at-start.txt": "pinned\n"},
            advanced_head: {"at-start.txt": "pinned\n", "after-start.txt": "mutable head\n"},
        },
    )

    worktree, _, base_head = module._create_worktree("pinned-advance")

    stored = module.load_state("pinned-advance")
    assert base_head == start_head
    assert stored["START_REPO_HEAD"] == start_head
    assert stored["WORKTREE_BASE_HEAD"] == start_head
    assert stored["WORKTREE_ACTUAL_HEAD"] == start_head
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "PASS"
    assert (worktree / "at-start.txt").read_text(encoding="utf-8") == "pinned\n"
    assert not (worktree / "after-start.txt").exists()
    add_call = next(arguments for arguments, _ in calls if arguments[:2] == ["worktree", "add"])
    assert add_call[-1] == start_head
    assert not any(
        arguments == ["rev-parse", "HEAD"] and cwd.resolve() == module.REPO.resolve()
        for arguments, cwd in calls
    )


def test_stale_primary_head_cannot_replace_newer_task_start_head(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_head = "a" * 40
    start_head = "b" * 40
    state = create_state(task_id="pinned-stale")
    state.update({
        "START_REPO_HEAD": start_head,
        "START_REPO_TOPLEVEL": str(module.REPO.resolve()),
    })
    module._write_state_unlocked("pinned-stale", state)
    calls = _install_pinned_worktree_git(
        monkeypatch,
        start_head=start_head,
        mutable_primary_head=old_head,
        snapshots={
            old_head: {"old.txt": "old\n"},
            start_head: {"old.txt": "old\n", "introduced-at-start.txt": "visible\n"},
        },
    )

    worktree, _, _ = module._create_worktree("pinned-stale")

    stored = module.load_state("pinned-stale")
    assert stored["START_REPO_HEAD"] == start_head
    assert stored["WORKTREE_BASE_HEAD"] == start_head
    assert stored["WORKTREE_ACTUAL_HEAD"] == start_head
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "PASS"
    assert (worktree / "introduced-at-start.txt").read_text(encoding="utf-8") == "visible\n"
    add_call = next(arguments for arguments, _ in calls if arguments[:2] == ["worktree", "add"])
    assert add_call[-1] == start_head
    assert not any(
        arguments == ["rev-parse", "HEAD"] and cwd.resolve() == module.REPO.resolve()
        for arguments, cwd in calls
    )


def test_actual_worktree_head_mismatch_is_persisted_and_rejected(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_head = "a" * 40
    actual_head = "b" * 40
    state = create_state(task_id="actual-mismatch")
    state.update({
        "START_REPO_HEAD": start_head,
        "START_REPO_TOPLEVEL": str(module.REPO.resolve()),
    })
    module._write_state_unlocked("actual-mismatch", state)
    calls: list[tuple[list[str], Path]] = []

    def fake_git(
        arguments: list[str], cwd: Path = module.REPO, timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(arguments), Path(cwd)))
        if arguments == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(arguments, 0, str(Path(cwd).resolve()), "")
        if arguments == ["rev-parse", "--verify", f"{start_head}^{{commit}}"]:
            return subprocess.CompletedProcess(arguments, 0, start_head + "\n", "")
        if arguments[:3] == ["show-ref", "--verify", "--quiet"]:
            return subprocess.CompletedProcess(arguments, 1, "", "")
        if arguments[:2] == ["worktree", "add"]:
            Path(arguments[4]).mkdir(parents=True)
            return subprocess.CompletedProcess(arguments, 0, "created", "")
        if arguments == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(arguments, 0, actual_head + "\n", "")
        if arguments == ["rev-parse", "--git-common-dir"]:
            return subprocess.CompletedProcess(arguments, 0, str(module.REPO / ".git"), "")
        raise AssertionError(f"unexpected git call: {arguments} in {cwd}")

    monkeypatch.setattr(module, "_git", fake_git)

    with pytest.raises(module.HarnessError, match="^BLOCKED_HARNESS_BASE_HEAD_MISMATCH:"):
        module._create_worktree("actual-mismatch")

    stored = module.load_state("actual-mismatch")
    assert stored["WORKTREE_BASE_HEAD"] == start_head
    assert stored["WORKTREE_ACTUAL_HEAD"] == actual_head
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "BLOCKED_HARNESS_BASE_HEAD_MISMATCH"
    add_call = next(arguments for arguments, _ in calls if arguments[:2] == ["worktree", "add"])
    assert add_call[-1] == start_head


def test_start_repo_toplevel_mismatch_blocks_before_worktree_add(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state(task_id="toplevel-mismatch")
    state.update({
        "START_REPO_HEAD": "a" * 40,
        "START_REPO_TOPLEVEL": str((module.REPO.parent / "different-repository").resolve()),
    })
    module._write_state_unlocked("toplevel-mismatch", state)
    calls: list[list[str]] = []

    def fake_git(
        arguments: list[str], cwd: Path = module.REPO, timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(arguments))
        if arguments == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(arguments, 0, str(module.REPO.resolve()), "")
        raise AssertionError(f"unexpected git call after toplevel mismatch: {arguments}")

    monkeypatch.setattr(module, "_git", fake_git)

    with pytest.raises(module.HarnessError, match="^BLOCKED_HARNESS_BASE_HEAD_MISMATCH:"):
        module._create_worktree("toplevel-mismatch")

    stored = module.load_state("toplevel-mismatch")
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "BLOCKED_HARNESS_BASE_HEAD_MISMATCH"
    assert calls == [["rev-parse", "--show-toplevel"]]
    assert not any(arguments[:2] == ["worktree", "add"] for arguments in calls)


def test_legacy_state_missing_start_identity_blocks_without_recapturing_head(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state(task_id="legacy-no-start-head")
    monkeypatch.setattr(
        module, "_git",
        lambda *args, **kwargs: pytest.fail("legacy state must not recapture mutable primary HEAD"),
    )

    with pytest.raises(module.HarnessError, match="^BLOCKED_HARNESS_BASE_HEAD_MISMATCH:"):
        module._create_worktree("legacy-no-start-head")

    stored = module.load_state("legacy-no-start-head")
    assert stored["BASE_HEAD_IDENTITY_STATUS"] == "BLOCKED_HARNESS_BASE_HEAD_MISMATCH"
    assert stored["WORKTREE_ACTUAL_HEAD"] == ""


@pytest.mark.parametrize("harness_version", [2, 3])
def test_base_head_mismatch_dispatch_blocks_exactly_and_skips_preflight(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
    harness_version: int,
) -> None:
    state = create_state(task_id=f"dispatch-mismatch-{harness_version}")
    if harness_version == 2:
        use_r2_compat_state(state)
    state.update({
        "HARNESS_VERSION": harness_version,
        "HARNESS_STATE": "PLANNING",
        "NEXT_ACTION_CODE": "CREATE_WORKTREE",
    })
    module._write_state_unlocked(state["TASK_ID"], state)
    monkeypatch.setattr(
        module, "_create_worktree",
        lambda task_id: (_ for _ in ()).throw(
            module.HarnessError("BLOCKED_HARNESS_BASE_HEAD_MISMATCH:synthetic mismatch")
        ),
    )
    monkeypatch.setattr(
        module, "_run_preflight_for",
        lambda *args, **kwargs: pytest.fail("base mismatch must block before isolated preflight"),
    )

    module._dispatch(state["TASK_ID"])

    blocked = module.load_state(state["TASK_ID"])
    assert blocked["HARNESS_STATE"] == "BLOCKED"
    assert blocked["ACTIVE_BLOCKERS"][0]["code"] == "BLOCKED_HARNESS_BASE_HEAD_MISMATCH"


def test_base_head_mismatch_cannot_be_resumed(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_state(task_id="base-mismatch-resume")
    module._block(
        "base-mismatch-resume", "BLOCKED_HARNESS_BASE_HEAD_MISMATCH",
        "start/base/actual identity failed",
    )
    monkeypatch.setattr(
        module, "recover_if_interrupted", lambda task_id: module.load_state(task_id),
    )

    with pytest.raises(module.HarnessError, match="RESUME_REJECTED_UNRESOLVED_HARD_INVARIANT"):
        module.command_resume(argparse.Namespace(task_id="base-mismatch-resume", foreground=False))


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
        findings = _worker_completion_message(task_result="SOFTWARE_FAILURE")
        module.update_task(task_id, {
            "WORKER_FINDINGS": findings,
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_TEST_EVIDENCE": KNOWN_NESTED_PYTEST_TEMP_FAILURE,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": findings, "tests": ["pytest | exit=1"]}

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
    state["OVERFIT_GUARD"] = "NOT_CHECKED_FOR_SCOPE"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is True
    for research_scope in ("pre2026-research", "frozen-dependent", "2026-evaluation", "all", "UNKNOWN"):
        state["TASK_SCOPE"] = research_scope
        assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False
    state["TASK_SCOPE"] = "independent-code"
    state["TASK_KIND"] = "pre2026-research"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False
    state["TASK_KIND"] = "independent-code"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is True
    state["OVERFIT_GUARD"] = "HARD_BLOCKER"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False
    state["OVERFIT_GUARD"] = "PASS"
    state["WORKTREE_INVENTORY_STATUS"] = "UNKNOWN"
    assert module._worker_test_environment_delegation_allowed(state, 0)[0] is False


def test_canonical_worker_boundary_precedes_environment_limited_delegation(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state.update({
        "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
        "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
        "WORKER_STATUS": "EXITED_0",
        "WORKER_COMPLETION_EVIDENCE": {
            "schema_version": 1,
            "task_result": "BLOCKED",
            "requires_human_boundary": True,
        },
    })

    allowed, reason = module._worker_test_environment_delegation_allowed(state, 0)

    assert allowed is False
    assert reason == "CANONICAL_WORKER_BOUNDARY_PRECEDES_TEST_DELEGATION"


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
        unit_results = [{
            "id": "WU-001", "status": "DONE", "produced_outputs": [],
            "validation_state": "PASS", "blocker": {},
            "last_checkpoint": "IMPLEMENTATION_COMPLETE",
            "next_action": "No further worker action",
            "reuse_decision": "EXTEND", "reuse_evidence": ["existing Harness implementation"],
        }]
        findings = (
            "TASK_RESULT=SOFTWARE_FAILURE\nHOLDOUT_CONTAMINATION_RISK=NONE\n"
            "BLOCKER_KIND=NONE\n"
            f"WORK_UNIT_RESULTS_JSON={json.dumps(unit_results, separators=(',', ':'))}\n"
            "CHANGED_PATHS_JSON=[]\nNEW_COMPONENT_JUSTIFICATION=NONE"
        )
        module.update_task(task_id, {
            "WORKER_FINDINGS": findings,
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_TEST_EVIDENCE": KNOWN_NESTED_PYTEST_TEMP_FAILURE,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": None,
            "ACTIVE_THREAD_ID": "", "ACTIVE_PROCESS_KIND": "",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": findings, "tests": []}

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
        findings = _worker_completion_message(task_result="SOFTWARE_FAILURE")
        module.update_task(task_id, {
            "WORKER_FINDINGS": findings,
            "WORKER_TEST_STATUS": "ENVIRONMENT_LIMITED",
            "WORKER_TEST_LIMITATION": module.WINDOWS_CODEX_SANDBOX_PYTEST_TEMP_LIMITATION,
            "WORKER_STATUS": "EXITED_0", "WORKER_PID": 4242,
            "ACTIVE_THREAD_ID": "thread-live", "ACTIVE_PROCESS_KIND": "WORKER",
            "WORKTREE_INVENTORY_STATUS": "KNOWN",
        })
        return {"exit_code": 0, "message": findings, "tests": ["pytest | exit=1"]}

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


def test_conflicting_review_markers_cannot_become_pass_after_tail_truncation() -> None:
    authoritative_message = (
        "REVIEW_STATUS=FIX_REQUIRED\n" + "x" * 9_000 + "\nREVIEW_STATUS=PASS"
    )

    assert module._review_classification(authoritative_message, 0) == "HUMAN_DECISION_REQUIRED"
    assert module._review_classification(
        authoritative_message[-module.MAX_TEXT:], 0,
    ) == "PASS"


def test_complete_review_evidence_drives_correction_identity_before_display_truncation() -> None:
    state = module._new_state("test-task", "Review one repair", "independent-code", 2)
    state["FILES_CHANGED"] = ["scripts/maintenance/harness_task.py"]
    authoritative_message = (
        "Duplicate component exists in scripts/maintenance/harness_task.py.\n"
        + "x" * 9_000
        + "\nThe inherited Anti-Bloat baseline residue is unchanged by this task.\n"
        + "REVIEW_STATUS=FIX_REQUIRED"
    )

    evidence = module._ingest_review_authority_evidence(state, authoritative_message)
    bounded_display = authoritative_message[-module.MAX_TEXT:]

    assert "DUPLICATE_COMPONENT_IDENTITY" in evidence["finding_analysis"]["identities"]
    assert "DUPLICATE_COMPONENT_IDENTITY" not in module._review_finding_analysis(
        state, bounded_display,
    )["identities"]
    assert module._queue_correction_work_unit(
        state, "FINAL_REVIEW", bounded_display, "p1",
        state["FILES_CHANGED"], review_analysis=evidence["finding_analysis"],
    ) is True
    assert "DUPLICATE_COMPONENT_IDENTITY" in state["WORK_UNITS"][-1][
        "review_finding_identity"
    ]


def test_complete_review_authorization_boundary_precedes_display_truncation() -> None:
    state = module._new_state("test-task", "Review one repair", "independent-code", 2)
    authoritative_message = (
        "Human authorization is required before this correction may proceed.\n"
        + "x" * 9_000
        + "\nREVIEW_STATUS=FIX_REQUIRED"
    )

    evidence = module._ingest_review_authority_evidence(state, authoritative_message)

    assert evidence["requires_human_boundary"] is True
    assert module._review_classification_with_authority("PASS", evidence) == (
        "HUMAN_DECISION_REQUIRED"
    )
    assert module._explicit_human_boundary_evidence(
        authoritative_message[-module.MAX_TEXT:],
    ) is False


@pytest.mark.parametrize(
    ("authoritative_message", "blocking_identity"),
    [
        (
            "Duplicate component exists.\n" + "x" * 9_000 + "\nREVIEW_STATUS=PASS",
            "DUPLICATE_COMPONENT_IDENTITY",
        ),
        (
            "REVIEW_STATUS=PASS\n" + "x" * 9_000 + "\nDuplicate component exists.",
            "DUPLICATE_COMPONENT_IDENTITY",
        ),
        (
            "y" * 2_800 + "\nAnti-Bloat violation exists.\n"
            + "z" * 2_800 + "\nREVIEW_STATUS=PASS",
            "ANTI_BLOAT_TASK_DELTA",
        ),
    ],
)
def test_complete_review_blocker_overrides_pass_regardless_of_order_or_compaction(
    authoritative_message: str, blocking_identity: str,
) -> None:
    state = module._new_state("test-task", "Review one repair", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"

    evidence = module._ingest_review_authority_evidence(state, authoritative_message)
    classification = module._review_classification_with_authority(
        module._review_classification(authoritative_message, 0), evidence,
    )

    assert evidence["reported_status"] == "PASS"
    assert blocking_identity in evidence["blocking_identities"]
    assert evidence["has_blocking_finding"] is True
    assert classification == "FIX_REQUIRED"


@pytest.mark.parametrize(
    "safe_finding",
    [
        "No duplicate component, duplicate implementation, or parallel component was found.",
        "Anti-Bloat violation, and duplicate component, were not found.",
    ],
)
def test_complete_review_negated_findings_remain_pass_before_long_padding(
    safe_finding: str,
) -> None:
    state = module._new_state("test-task", "Review one repair", "independent-code", 2)
    state["ANTI_BLOAT_TASK_DELTA"] = "PASS"
    authoritative_message = (
        safe_finding + "\n" + "x" * 9_000 + "\nREVIEW_STATUS=PASS"
    )

    evidence = module._ingest_review_authority_evidence(state, authoritative_message)

    assert evidence["blocking_identities"] == []
    assert evidence["has_blocking_finding"] is False
    assert module._review_classification_with_authority(
        module._review_classification(authoritative_message, 0), evidence,
    ) == "PASS"


def test_bounded_review_findings_cannot_reconcile_local_unit_to_done() -> None:
    state = module._new_state("test-task", "Review one repair", "independent-code", 2)
    unit = module._new_work_unit("WU-001", "Complete the reviewed correction")
    unit.update({
        "status": "BLOCKED_LOCAL",
        "produced_outputs": ["scripts/maintenance/existing.py"],
        "validation_state": "TASK_TESTS_PASS_GLOBAL_GUARD_FAIL",
        "blocker": {"kind": "LOCAL", "conditions": ["inherited residue outside this diff"]},
        "last_checkpoint": "CORRECTION_IMPLEMENTED_AND_FOCUSED_TESTS_PASS",
    })
    state.update({
        "WORK_UNITS": [unit], "CONTROLLER_VALIDATION_STATUS": "PASS",
        **stale_bounded_blocking_review_fields(state),
    })

    assert "duplicate component" not in state["REVIEW_FINDINGS"].casefold()
    assert module._canonical_persisted_review_classification(state) == "FIX_REQUIRED"
    assert module._accepted_nonblocking_review(state) is False
    assert module._reconcile_terminal_local_environment_units(state) == (0, 0)
    assert unit["status"] == "BLOCKED_LOCAL"


def test_finalization_cannot_complete_from_bounded_review_display(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    done = module._new_work_unit("WU-001", "Complete the bounded repair")
    done["status"] = "DONE"
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "WORK_UNITS": [done],
        "CONTROLLER_VALIDATION_STATUS": "PASS",
        **stale_bounded_blocking_review_fields(state),
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": ["scripts/maintenance/existing.py"], "created": [],
        "dependencies": [], "changed_count": 1, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", lambda task_id: None)

    module._dispatch("test-task")

    final = module.load_state("test-task")
    assert final["HARNESS_STATE"] == "FAILED"
    assert final["TERMINAL_SUCCESS"] is False
    assert module._canonical_persisted_review_classification(final) == "FIX_REQUIRED"


def test_pause_checkpoint_cannot_preserve_finalize_after_canonical_review_blocker(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state()
    state.update({
        "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "FINALIZE",
        "PAUSE_REQUESTED": True,
        **stale_bounded_blocking_review_fields(state),
    })
    module._write_state_unlocked("test-task", state)

    assert module._control_checkpoint("test-task") is True

    paused = module.load_state("test-task")
    assert paused["HARNESS_STATE"] == "PAUSED"
    assert paused["NEXT_ACTION_CODE"] == "FINAL_REVIEW"
    assert paused["LAST_REVIEW_STATUS"] == "FIX_REQUIRED"


def test_crash_recovery_cannot_resume_finalize_after_canonical_review_blocker(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    state.update({
        "HARNESS_STATE": "RUNNING", "WORKTREE": str(worktree),
        "NEXT_ACTION_CODE": "FINALIZE", "CONTROLLER_PID": 999_999,
        **stale_bounded_blocking_review_fields(state),
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["scripts/maintenance/existing.py"], "created": [],
        "dependencies": [], "changed_count": 1, "created_count": 0,
    })

    recovered = module.recover_if_interrupted("test-task")

    assert recovered["HARNESS_STATE"] == "RUNNING"
    assert recovered["NEXT_ACTION_CODE"] == "FINAL_REVIEW"
    assert recovered["LAST_REVIEW_STATUS"] == "FIX_REQUIRED"


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


def test_crash_recovery_cannot_bypass_canonical_worker_safety_boundary(
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
    })
    evidence = module._ingest_worker_completion_evidence(
        state,
        _worker_completion_message(
            rows=[_structured_worker_result()],
            contamination="possible exposed holdout use",
            blocker_kind="SAFETY",
        ),
    )
    state.update(module._worker_completion_state_fields(evidence))
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": ["checkpointed.py"], "created": [], "dependencies": [],
    })

    recovered = module.recover_if_interrupted("test-task")

    assert recovered["HARNESS_STATE"] == "WAITING_HUMAN"
    assert recovered["NEXT_ACTION_CODE"] != "UNIT_VALIDATE"
    assert recovered["HUMAN_ATTENTION_REQUIRED"] is True
    assert recovered["WORK_UNITS"][0]["status"] == "RETRY"
    assert recovered["PENDING_UNIT_RESULTS"] == []
    assert recovered["ACTIVE_BLOCKERS"][0]["boundary_kind"] == "SAFETY"


def test_new_batch_clears_prior_turn_authority_before_crash_inventory(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state()
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    prior_path = "docs/component-a.md"
    new_path = "docs/component-b.md"
    unit = module._new_work_unit("WU-001", "Repair the next bounded unit")
    state.update({
        "WORKTREE": str(worktree), "WORK_UNITS": [unit],
        "JUSTIFIED_CREATED_PATHS": [prior_path],
        "NEW_COMPONENT_JUSTIFICATION": "Prior turn justification",
        "WORKER_COMPLETION_EVIDENCE": {
            "schema_version": 1,
            "new_component_justification": "Prior turn justification",
            "work_unit_results": [{"id": "OLD", "status": "DONE"}],
        },
        "PENDING_UNIT_RESULTS": [{"id": "OLD", "status": "DONE"}],
        "WORKER_REPORTED_CHANGED_PATHS": [prior_path],
    })

    assert module._select_work_unit_batch(state) == ["WU-001"]
    assert state["WORKER_COMPLETION_EVIDENCE"] == {}
    assert state["PENDING_UNIT_RESULTS"] == []
    assert state["WORKER_REPORTED_CHANGED_PATHS"] == []
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(module, "_git_changes", lambda path: {
        "changed": [prior_path, new_path], "created": [prior_path, new_path],
        "dependencies": [], "changed_count": 2, "created_count": 2,
    })

    module._refresh_changes("test-task")
    recovered = module.load_state("test-task")

    assert recovered["JUSTIFIED_CREATED_PATHS"] == [prior_path]
    assert recovered["UNJUSTIFIED_CREATED_PATHS"] == [new_path]


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


def _prospective_spec(task_root: Path, research_id: str = "prospective-e2e") -> dict:
    return {
        "research_id": research_id,
        "research_family": "synthetic lifecycle",
        "economic_mechanism": "synthetic registry gate",
        "target": "synthetic target",
        "information_source": "synthetic source",
        "portfolio_role": "test only",
        "hypothesis": "Harness orders existing lifecycle calls without economic evaluation.",
        "task_root": str(task_root),
        "code_reference": "synthetic-commit",
        "config_reference": "synthetic-config.json",
        "data_reference": "synthetic-fingerprint",
        "reopen_request": {},
    }


def test_prospective_duplicate_negative_blocks_before_real_entrypoint_worker(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = use_supervisor_test_storage(isolated_roots, monkeypatch)
    storage.repo_root = module.REPO
    task_root = storage.results_root / "duplicate-negative"
    spec_path = isolated_roots[0].parent / "duplicate-negative-spec.json"
    spec = _prospective_spec(task_root, "duplicate-negative")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    worker_calls = {"count": 0}

    class DuplicateLifecycle:
        @staticmethod
        def research_start_gate(repo: Path, path: Path, *, storage=None) -> dict:
            assert path == spec_path.resolve()
            return {
                "spec": spec,
                "decision": {
                    "mechanism_key": "a" * 64,
                    "matched_prior_branch": "prior-negative",
                    "prior_status": "CLOSED_NEGATIVE",
                    "prior_conclusion": "existing concise negative conclusion",
                    "reopen_condition": "genuinely new source",
                    "decision": "BLOCK_AS_DUPLICATE_RESEARCH",
                    "justification": "no qualifying reopen basis",
                    "registry_head_sha256": "b" * 64,
                },
            }

    def forbidden_worker(task_id: str) -> int:
        worker_calls["count"] += 1
        pytest.fail("duplicate research must terminate before the Harness worker")

    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: DuplicateLifecycle)
    monkeypatch.setattr(module, "hard_guard_conflicts", lambda goal: [])
    monkeypatch.setattr(module, "run_task", forbidden_worker)

    assert module.main([
        "start", "--task-id", "duplicate-negative", "--foreground",
        "--goal", "Synthetic registered pre-2026 research fixture.",
        "--task-kind", "pre2026-research", "--research-spec", str(spec_path),
    ]) == 0
    state = module.load_state("duplicate-negative")
    assert worker_calls["count"] == 0
    assert state["HARNESS_STATE"] == "COMPLETED"
    assert state["TERMINAL_OUTCOME"] == "BLOCK_AS_DUPLICATE_RESEARCH"
    assert state["MATCHED_PRIOR_BRANCH"] == "prior-negative"
    assert state["PRIOR_RESEARCH_STATUS"] == "CLOSED_NEGATIVE"
    assert state["PRIOR_RESEARCH_CONCLUSION"] == "existing concise negative conclusion"


def test_prospective_valid_reopen_reaches_worker_and_persists_justification(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = use_supervisor_test_storage(isolated_roots, monkeypatch)
    storage.repo_root = module.REPO
    spec_path = isolated_roots[0].parent / "valid-reopen-spec.json"
    spec = _prospective_spec(storage.results_root / "valid-reopen", "valid-reopen")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    worker_calls = {"count": 0}

    class ReopenLifecycle:
        @staticmethod
        def research_start_gate(repo: Path, path: Path, *, storage=None) -> dict:
            return {
                "spec": spec,
                "decision": {
                    "mechanism_key": "c" * 64,
                    "matched_prior_branch": "prior-closed",
                    "prior_status": "CLOSED_NEGATIVE",
                    "prior_conclusion": "negative on prior source",
                    "reopen_condition": "new source arrives",
                    "decision": "ALLOW_REOPEN",
                    "justification": "documented new source evidence",
                    "registry_head_sha256": "d" * 64,
                },
            }

    def synthetic_worker(task_id: str) -> int:
        worker_calls["count"] += 1
        return 0

    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: ReopenLifecycle)
    monkeypatch.setattr(module, "hard_guard_conflicts", lambda goal: [])
    monkeypatch.setattr(module, "run_task", synthetic_worker)

    assert module.main([
        "start", "--task-id", "valid-reopen", "--foreground",
        "--goal", "Synthetic registered reopen fixture.",
        "--task-kind", "pre2026-research", "--research-spec", str(spec_path),
    ]) == 0
    state = module.load_state("valid-reopen")
    assert worker_calls["count"] == 1
    assert state["RESEARCH_START_DECISION"] == "ALLOW_REOPEN"
    assert state["REOPEN_JUSTIFICATION"] == "documented new source evidence"
    assert state["REOPEN_CONDITION"] == "new source arrives"


@pytest.mark.parametrize("task_kind", ["maintenance", "auto"])
def test_non_research_real_entrypoint_is_not_false_blocked(
    task_kind: str, isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"worker": 0}

    def synthetic_worker(task_id: str) -> int:
        calls["worker"] += 1
        return 0

    monkeypatch.setattr(
        module, "_load_prospective_lifecycle",
        lambda: pytest.fail("non-research task must not load research governance"),
    )
    monkeypatch.setattr(module, "run_task", synthetic_worker)
    task_id = f"maintenance-not-research-{task_kind}"
    assert module.main([
        "start", "--task-id", task_id, "--foreground",
        "--goal", "Harness maintenance: repair one lifecycle fixture; do not perform economic research.",
        "--task-kind", task_kind,
    ]) == 0
    state = module.load_state(task_id)
    assert calls["worker"] == 1
    assert state["TASK_KIND"] == "maintenance"
    assert state["RESEARCH_START_DECISION"] == "NOT_APPLICABLE_NON_RESEARCH_TASK"
    assert state["PROSPECTIVE_LIFECYCLE_APPLICABILITY"] == "NOT_APPLICABLE_NON_RESEARCH_TASK"


def test_non_research_finalization_never_invokes_prospective_retirement(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state(goal="Harness maintenance fixture")
    worktree = isolated_roots[1] / "harness-task-test-task"
    worktree.mkdir(parents=True)
    unit = module._new_work_unit("WU-001", "Complete the maintenance fixture")
    unit.update({
        "status": "DONE", "validation_state": "PASS", "blocker": {},
        "last_checkpoint": "IMPLEMENTATION_COMPLETE",
        "next_action": "No further action",
    })
    state.update({
        "HARNESS_STATE": "RUNNING", "TASK_KIND": "maintenance",
        "WORKTREE": str(worktree), "NEXT_ACTION_CODE": "FINALIZE",
        "CONTROLLER_VALIDATION_STATUS": "PASS", "WORK_UNITS": [unit],
    })
    state.update(canonical_review_fields(state, "PASS", "No blocking findings."))
    module._write_state_unlocked("test-task", state)
    cleanup_calls: list[str] = []

    def terminal_temp_cleanup(task_id: str) -> None:
        assert module.load_state(task_id)["HARNESS_STATE"] == "COMPLETED"
        cleanup_calls.append(task_id)

    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", terminal_temp_cleanup)
    monkeypatch.setattr(
        module, "_run_prospective_post_completion",
        lambda *args, **kwargs: pytest.fail("non-research worktree retirement is out of scope"),
    )
    monkeypatch.setattr(
        module, "_load_prospective_lifecycle",
        lambda: pytest.fail("non-research finalization must not load research governance"),
    )

    module._dispatch("test-task")

    completed = module.load_state("test-task")
    assert completed["HARNESS_STATE"] == "COMPLETED"
    assert completed["WORKTREE_RETIREMENT_STATUS"] == "NOT_APPLICABLE"
    assert cleanup_calls == ["test-task"]


def test_worker_prompt_declares_exact_prospective_completion_schema(
    isolated_roots: tuple[Path, Path],
) -> None:
    state = create_state(goal="Synthetic prospective prompt fixture")
    state.update({
        "TASK_KIND": "pre2026-research", "RESEARCH_START_DECISION": "ALLOW_NEW_RESEARCH",
        "RESEARCH_MECHANISM_KEY": "a" * 64, "PROSPECTIVE_RESEARCH_ID": "RESEARCH-001",
        "RESEARCH_TASK_ROOT": str(isolated_roots[0].parent / "prospective-prompt"),
    })
    prompt = module._worker_prompt(state)
    assert "CLOSED_NEGATIVE, FAILED, REJECTED, SUPERSEDED" in prompt
    assert '"schema_version":1,"task_id":"RESEARCH-001","artifacts":[...]' in prompt
    assert "object_type (FILE or DIRECTORY)" in prompt
    assert "delete_after_completion, protected, rebuildable, and forward_decision" in prompt
    assert "disposable FILE also requires its whole-file lowercase SHA256" in prompt
    assert "one exact KEEP_RESEARCH_KNOWLEDGE row" in prompt


def test_prospective_real_entrypoint_orders_finalize_cleanup_and_retirement(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = use_supervisor_test_storage(isolated_roots, monkeypatch)
    storage.repo_root = module.REPO
    (module.REPO / "config").mkdir(parents=True)
    registry_relative = Path("scripts/maintenance/research_registry.py")
    (module.REPO / registry_relative).parent.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / registry_relative, module.REPO / registry_relative)
    registry_root = storage.results_root / "synthetic-existing-registry"
    (module.REPO / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    lifecycle = module._load_prospective_lifecycle()
    prior_spec = lifecycle.normalize_research_spec({
        **_prospective_spec(storage.results_root / "prior-prospective-e2e", "prior-prospective-e2e"),
        "research_family": "distinct prior family",
        "economic_mechanism": "distinct prior mechanism",
        "target": "distinct prior target",
        "information_source": "distinct prior source",
        "data_reference": "contract://distinct-prior-source",
        "portfolio_role": "distinct prior role",
    })
    registry = lifecycle._registry_module(module.REPO)
    active = {
        **lifecycle.registry_candidate(prior_spec),
        "status": "ACTIVE",
        "evidence_source_temporal_status": "STRUCTURAL_GOVERNANCE_METADATA_ONLY",
        "excluded_source_refs": [],
        "temporal_evidence_limitations": [],
        "metadata": {"mechanism_key": lifecycle.mechanism_key(prior_spec)},
    }
    operations = [{"op": "add_entity", "entity": active}]
    registry.apply_patch(registry_root, {
        "schema_version": 1,
        "expected_base_head_sha256": registry.GENESIS,
        "author": "synthetic-harness-e2e",
        "event_time_utc": "2025-12-30T00:00:00+00:00",
        "validation": {"status": "PASS", "post_2025_observation_count": 0},
        "independent_review": {
            "status": "PASS", "independent": True, "reviewer": "synthetic-fixture",
        },
        "operations": operations,
        "operation_count": 1,
        "operations_sha256": registry.sha256_value(operations),
    })
    task_root = storage.results_root / "prospective-e2e"
    retained = task_root / "retained"
    scratch_dir = task_root / "scratch"
    receipt_path = retained / "result_receipt.json"
    source_marker = retained / "source-reference.json"
    forward_evidence = retained / "forward-decision.json"
    scratch = scratch_dir / "derived.tmp"
    manifest_path = task_root / "retention_manifest.json"
    spec = _prospective_spec(task_root)
    spec_path = isolated_roots[0].parent / "prospective-e2e-spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    worktree = isolated_roots[1] / "harness-task-prospective-e2e"
    worktree.mkdir(parents=True)
    order: list[str] = []

    real_start_gate = lifecycle.research_start_gate
    real_receipt_validation = lifecycle.validate_completion_receipt
    real_registry_update = lifecycle.apply_registry_completion
    real_manifest_validation = lifecycle.validate_retention_manifest

    def observed_start_gate(repo: Path, path: Path, *, storage=None) -> dict:
        order.append("START_GATE")
        assert not task_root.exists()
        return real_start_gate(repo, path, storage=storage)

    def observed_receipt_validation(receipt: dict, received_spec: dict) -> dict:
        order.append("RECEIPT_VALIDATION")
        return real_receipt_validation(receipt, received_spec)

    def observed_registry_update(
        repo: Path, received_spec: dict, receipt: dict, path: Path, *, reviewer: str,
    ) -> dict:
        order.append("REGISTRY_UPDATE")
        assert reviewer == "harness-final-independent-review:review-thread-e2e"
        return real_registry_update(repo, received_spec, receipt, path, reviewer=reviewer)

    def observed_manifest_validation(
        path: Path, received_spec: dict, received_storage,
    ) -> dict:
        order.append("RETENTION_MANIFEST")
        assert path == manifest_path.resolve()
        return real_manifest_validation(path, received_spec, received_storage)

    def deferred_host_cleanup(
        received_rows, *, task_completed: bool, worker_active: bool,
        task_root: Path, storage,
    ) -> dict:
        order.append("HOST_CLEANUP")
        assert module.load_state("prospective-e2e")["HARNESS_STATE"] == "COMPLETED"
        assert task_completed and not worker_active
        assert next(
            row for row in received_rows if row["path"] == str(source_marker.resolve())
        )["retention_class"] == "KEEP_DATA"
        assert next(
            row for row in received_rows if row["path"] == str(forward_evidence.resolve())
        )["retention_class"] == "KEEP_KEY_EVIDENCE"
        return {
            "status": "HOST_CLEANUP_DEFERRED", "deleted_paths": [],
            "reclaimed_bytes": 0,
            "deferred": [{"path": str(scratch.resolve()), "reason": "PermissionError:synthetic"}],
        }

    def deferred_worktree_retirement(
        repo: Path, path: Path, *, task_completed: bool, active: bool,
    ) -> dict:
        order.append("WORKTREE_RETIREMENT")
        assert task_completed and not active and path == worktree.resolve()
        return {"status": "WORKTREE_RETIREMENT_DEFERRED", "reason": "REVIEW"}

    monkeypatch.setattr(lifecycle, "research_start_gate", observed_start_gate)
    monkeypatch.setattr(lifecycle, "validate_completion_receipt", observed_receipt_validation)
    monkeypatch.setattr(lifecycle, "apply_registry_completion", observed_registry_update)
    monkeypatch.setattr(lifecycle, "validate_retention_manifest", observed_manifest_validation)
    monkeypatch.setattr(lifecycle, "host_cleanup", deferred_host_cleanup)
    monkeypatch.setattr(lifecycle, "retire_completed_worktree", deferred_worktree_retirement)

    def synthetic_run_task(task_id: str) -> int:
        order.append("WORKER")
        retained.mkdir(parents=True)
        scratch_dir.mkdir(parents=True)
        normalized_spec = lifecycle.normalize_research_spec(spec)
        receipt_path.write_text(json.dumps({
            "research_id": normalized_spec["research_id"],
            "mechanism_key": lifecycle.mechanism_key(normalized_spec),
            "hypothesis": normalized_spec["hypothesis"],
            "final_status": "CLOSED_NEGATIVE",
            "key_conclusion": "synthetic non-economic lifecycle conclusion",
            "key_metrics_summary": {"synthetic_count": 1},
            "trial_count": {field: 0 for field in lifecycle.TRIAL_FIELDS},
            "code_commit": "synthetic-commit",
            "config_reference": normalized_spec["config_reference"],
            "data_reference": normalized_spec["data_reference"],
            "stop_reason": "synthetic fixture completed",
            "reopen_condition": "documented fixture change",
            "related_branch": "",
            "completed_at": "2025-12-31T00:00:00+00:00",
        }), encoding="utf-8")
        source_marker.write_text("synthetic source reference", encoding="utf-8")
        forward_evidence.write_text("synthetic pre-outcome decision", encoding="utf-8")
        scratch.write_text("synthetic disposable payload", encoding="utf-8")

        def artifact_row(
            path: Path, retention_class: str, provenance: str, reason: str,
            *, forward_decision: bool = False, key_evidence_justification: str = "",
        ) -> dict:
            disposable = retention_class in lifecycle.DISPOSABLE_CLASSES
            row = {
                "path": str(path.resolve()), "retention_class": retention_class,
                "object_type": "FILE", "size_bytes": path.stat().st_size,
                "provenance": provenance, "reason": reason,
                "delete_after_completion": disposable, "protected": not disposable,
                "rebuildable": disposable, "forward_decision": forward_decision,
            }
            if disposable:
                row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if key_evidence_justification:
                row["key_evidence_justification"] = key_evidence_justification
            return row

        manifest_path.write_text(json.dumps({
            "schema_version": 1,
            "task_id": normalized_spec["research_id"],
            "artifacts": [
                artifact_row(
                    receipt_path, "KEEP_RESEARCH_KNOWLEDGE", "RESEARCH_KNOWLEDGE",
                    "compact terminal research receipt",
                ),
                artifact_row(
                    source_marker, "KEEP_DATA", "RAW", "synthetic source identity",
                ),
                artifact_row(
                    forward_evidence, "KEEP_KEY_EVIDENCE", "DERIVED",
                    "synthetic forward decision evidence", forward_decision=True,
                    key_evidence_justification="pre-outcome decision evidence",
                ),
                artifact_row(
                    scratch, "DERIVED_DISPOSABLE", "DERIVED",
                    "locally reproducible synthetic payload",
                ),
            ],
        }), encoding="utf-8")
        state = module.load_state(task_id)
        state.update({
            "HARNESS_STATE": "RUNNING", "NEXT_ACTION_CODE": "FINAL_VALIDATION",
            "WORKTREE": str(worktree), "CONTROLLER_VALIDATION_STATUS": "NOT_RUN",
                "WORK_UNITS": [{
                    "id": "WU-001", "status": "DONE", "optional": False,
                    "produced_outputs": [str(receipt_path)],
                    "validation_state": "PASS", "last_checkpoint": "COMPLETED",
                    "next_action": "No further action",
                }],
        })
        module._write_state_unlocked(task_id, state)
        module._dispatch(task_id)
        return 0

    def final_validation(task_id: str) -> tuple[bool, str]:
        order.append("FINAL_VALIDATION")
        module.update_task(task_id, {"CONTROLLER_VALIDATION_STATUS": "PASS"})
        return True, "synthetic controller validation passed"

    def final_review(task_id: str) -> str:
        order.append("FINAL_REVIEW")
        return record_fake_review(
            task_id, "PASS", "No blocking findings.",
            FINAL_REVIEWER_ID="review-thread-e2e",
        )

    def post_terminal_temp_cleanup(task_id: str) -> None:
        order.append("TEMP_CLEANUP")
        assert module.load_state(task_id)["HARNESS_STATE"] == "COMPLETED"

    monkeypatch.setattr(module, "_load_prospective_lifecycle", lambda: lifecycle)
    monkeypatch.setattr(module, "hard_guard_conflicts", lambda goal: [])
    monkeypatch.setattr(module, "run_task", synthetic_run_task)
    monkeypatch.setattr(module, "_run_final_validation", final_validation)
    monkeypatch.setattr(module, "_perform_review", final_review)
    monkeypatch.setattr(module, "_worktree_progress_hash", lambda path: "synthetic-progress")
    monkeypatch.setattr(module, "_git", lambda args, cwd=module.REPO, timeout=30: subprocess.CompletedProcess(
        args, 0, stdout="refs/heads/main\n", stderr="",
    ))
    monkeypatch.setattr(module, "_refresh_changes", lambda task_id: {
        "changed": [], "created": [], "dependencies": [],
        "changed_count": 0, "created_count": 0,
    })
    monkeypatch.setattr(module, "_cleanup_task_temp_runtime", post_terminal_temp_cleanup)

    assert module.main([
        "start", "--task-id", "prospective-e2e", "--foreground",
        "--goal", "Synthetic prospective lifecycle integration fixture.",
        "--task-kind", "pre2026-research", "--research-spec", str(spec_path),
    ]) == 0
    state = module.load_state("prospective-e2e")
    assert order == [
        "START_GATE", "WORKER", "FINAL_VALIDATION", "FINAL_REVIEW",
        "RECEIPT_VALIDATION", "REGISTRY_UPDATE", "RETENTION_MANIFEST",
        "TEMP_CLEANUP", "HOST_CLEANUP", "WORKTREE_RETIREMENT",
    ]
    assert state["HARNESS_STATE"] == "COMPLETED"
    assert state["REGISTRY_COMPLETION_STATUS"] == "APPLIED"
    assert state["RETENTION_MANIFEST_STATUS"] == "PASS"
    assert state["HOST_CLEANUP_STATUS"] == "HOST_CLEANUP_DEFERRED"
    assert state["HOST_CLEANUP_DEFERRED_ALLOWLIST"] == [str(scratch.resolve())]
    assert state["WORKTREE_RETIREMENT_STATUS"] == "WORKTREE_RETIREMENT_DEFERRED"
    assert state["WORKTREE_RETIREMENT_REASON"] == "REVIEW"
    allowlist = json.loads(
        Path(state["HOST_CLEANUP_DEFERRED_ALLOWLIST_PATH"]).read_text(encoding="utf-8")
    )
    assert [row["path"] for row in allowlist["exact_paths"]] == [str(scratch.resolve())]
    assert source_marker.is_file() and forward_evidence.is_file() and scratch.is_file()
    assert worktree.is_dir()
    stored = registry.query_registry(
        registry_root, entity_id="prospective-e2e",
    )["entities"][0]
    assert stored["status"] == "CLOSED"
    assert stored["metadata"]["retention_class"] == "KEEP_RESEARCH_KNOWLEDGE"
    receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    expected_reference = f"receipt://sha256/{receipt_sha256}"
    assert stored["metadata"]["research_knowledge_sha256"] == receipt_sha256
    for field in (
        "research_knowledge_ref", "final_conclusion_ref",
        "key_result_summary_ref", "stop_reason_ref", "reopen_condition_ref",
    ):
        assert stored["metadata"][field] == expected_reference
    assert str(receipt_path.resolve()) not in json.dumps(
        stored["metadata"], sort_keys=True,
    )
    assert registry._performance_value_paths(stored["metadata"]) == []
    events = [
        json.loads(line)["event"]
        for line in module.timeline_path("prospective-e2e").read_text(encoding="utf-8").splitlines()
    ]
    assert events.index("RESEARCH_START_GATE_COMPLETED") < events.index("FINAL_VALIDATION_STARTED")
    assert events.index("TASK_COMPLETED") < events.index("HOST_CLEANUP_COMPLETED")


def test_prospective_post_completion_exception_is_terminal_fail_safe(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state(goal="Synthetic post-terminal fail-safe fixture")
    state.update({
        "HARNESS_STATE": "COMPLETED", "TERMINAL_OUTCOME": "COMPLETED",
        "TERMINAL_SUCCESS": True, "TASK_KIND": "pre2026-research",
    })
    module._write_state_unlocked("test-task", state)
    evidence_root = isolated_roots[0].parent / "post-terminal-fail-safe"
    evidence_root.mkdir()
    manifest_path = evidence_root / "retention_manifest.json"
    receipt_path = evidence_root / "result_receipt.json"
    disposable = evidence_root / "scratch.bin"
    for path in (manifest_path, receipt_path, disposable):
        path.write_bytes(b"synthetic")

    class Lifecycle:
        DISPOSABLE_CLASSES = {"DERIVED_DISPOSABLE", "SCRATCH_DISPOSABLE"}

        @staticmethod
        def host_cleanup(*args, **kwargs):
            pytest.fail("hash failure must prevent destructive cleanup")

        @staticmethod
        def retire_completed_worktree(*args, **kwargs):
            pytest.fail("hash failure must prevent retirement")

    context = {
        "lifecycle": Lifecycle,
        "rows": [{
            "path": str(disposable.resolve()), "retention_class": "DERIVED_DISPOSABLE",
            "object_type": "FILE", "size_bytes": disposable.stat().st_size,
            "sha256": hashlib.sha256(disposable.read_bytes()).hexdigest(),
        }],
        "manifest_path": manifest_path, "manifest_sha256": "a" * 64,
        "receipt_path": receipt_path, "receipt_sha256": "b" * 64,
        "task_root": evidence_root, "storage": argparse.Namespace(),
    }
    monkeypatch.setattr(
        module, "_whole_file_sha256",
        lambda path: (_ for _ in ()).throw(OSError("synthetic post-terminal hash failure")),
    )

    module._run_prospective_post_completion("test-task", context)

    completed = module.load_state("test-task")
    assert completed["HARNESS_STATE"] == "COMPLETED"
    assert completed["TERMINAL_OUTCOME"] == "COMPLETED"
    assert completed["TERMINAL_SUCCESS"] is True
    assert completed["HOST_CLEANUP_STATUS"] == "HOST_CLEANUP_DEFERRED"
    assert completed["WORKTREE_RETIREMENT_STATUS"] == "WORKTREE_RETIREMENT_DEFERRED"
    assert "POST_COMPLETION_FAIL_SAFE:OSError" in completed["WORKTREE_RETIREMENT_REASON"]
    assert completed["HOST_CLEANUP_DEFERRED_ALLOWLIST"] == [str(disposable.resolve())]


def test_prospective_post_completion_dirty_worktree_never_reaches_git_remove(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = use_supervisor_test_storage(isolated_roots, monkeypatch)
    storage.repo_root = module.REPO
    lifecycle = module._load_prospective_lifecycle()
    task_root = storage.results_root / "dirty-worktree-post-completion"
    retained = task_root / "retained"
    retained.mkdir(parents=True)
    receipt_path = retained / "result_receipt.json"
    manifest_path = task_root / "retention_manifest.json"
    receipt_path.write_bytes(b"synthetic retained receipt")
    manifest_path.write_bytes(b"synthetic stable manifest")
    worktree = isolated_roots[1] / "harness-task-dirty-retirement"
    worktree.mkdir(parents=True)
    state = create_state(goal="Synthetic dirty worktree retirement fixture")
    state.update({
        "HARNESS_STATE": "COMPLETED", "TERMINAL_OUTCOME": "COMPLETED",
        "TERMINAL_SUCCESS": True, "TASK_KIND": "pre2026-research",
        "WORKTREE": str(worktree), "WORKER_PID": None,
        "ACTIVE_PROCESS_KIND": "", "ACTIVE_THREAD_ID": "",
    })
    module._write_state_unlocked("test-task", state)
    git_calls: list[list[str]] = []

    def fake_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        git_calls.append(arguments)
        if arguments[:2] == ["worktree", "remove"]:
            pytest.fail("dirty worktree must never reach git worktree remove")
        if arguments == ["worktree", "list", "--porcelain"]:
            normalized = str(worktree.resolve()).replace("\\", "/")
            return subprocess.CompletedProcess(
                arguments, 0,
                f"worktree {normalized}\nHEAD abc123\nbranch refs/heads/task\n\n", "",
            )
        if arguments == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(arguments, 0, "?? scratch.tmp\n", "")
        if arguments == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(arguments, 0, "abc123\n", "")
        if arguments == ["symbolic-ref", "-q", "HEAD"]:
            return subprocess.CompletedProcess(arguments, 0, "refs/heads/task\n", "")
        if arguments == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(arguments, 0, ".git\n", "")
        if arguments[:3] == ["show-ref", "--verify", "--quiet"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["rev-parse", "refs/heads/task"]:
            return subprocess.CompletedProcess(arguments, 0, "abc123\n", "")
        if arguments == ["merge-base", "--is-ancestor", "abc123", "abc123"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(lifecycle, "_git", fake_git)
    context = {
        "lifecycle": lifecycle,
        "rows": [{
            "path": str(receipt_path.resolve()),
            "retention_class": "KEEP_RESEARCH_KNOWLEDGE",
            "object_type": "FILE", "size_bytes": receipt_path.stat().st_size,
        }],
        "manifest_path": manifest_path,
        "manifest_sha256": module._whole_file_sha256(manifest_path),
        "receipt_path": receipt_path,
        "receipt_sha256": module._whole_file_sha256(receipt_path),
        "task_root": task_root, "storage": storage,
    }

    module._run_prospective_post_completion("test-task", context)

    completed = module.load_state("test-task")
    assert completed["HOST_CLEANUP_STATUS"] == "PASS"
    assert completed["WORKTREE_RETIREMENT_STATUS"] == "WORKTREE_RETIREMENT_DEFERRED"
    assert completed["WORKTREE_RETIREMENT_REASON"] == "REVIEW"
    assert ["status", "--porcelain=v1"] in git_calls
    assert not any(arguments[:2] == ["worktree", "remove"] for arguments in git_calls)


def test_research_dispatch_defense_in_depth_blocks_missing_start_gate(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_state(goal="Synthetic research bypass fixture")
    state.update({
        "HARNESS_STATE": "RUNNING", "TASK_KIND": "pre2026-research",
        "NEXT_ACTION_CODE": "WORKER", "RESEARCH_START_DECISION": "NOT_RUN",
    })
    module._write_state_unlocked("test-task", state)
    monkeypatch.setattr(
        module, "_run_codex_turn",
        lambda *args, **kwargs: pytest.fail("worker must not dispatch without research start gate"),
    )
    module._dispatch("test-task")
    blocked = module.load_state("test-task")
    assert blocked["HARNESS_STATE"] == "BLOCKED"
    assert blocked["ACTIVE_BLOCKERS"][0]["code"] == "RESEARCH_START_GATE_NOT_PASSED"
