from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.maintenance import prospective_research_lifecycle as lifecycle


@pytest.fixture
def tmp_path() -> Path:
    """Avoid the known Windows sandbox failure in pytest's mode-0700 temp root."""
    repository = Path(__file__).resolve().parents[2]
    configured = os.environ.get("US_TECH_QUANT_TEST_TMP_ROOT")
    base = Path(configured).resolve() if configured else Path(tempfile.gettempdir()).resolve()
    if base == repository or repository in base.parents:
        pytest.fail(f"PROSPECTIVE_TEST_TEMP_ROOT_INSIDE_REPOSITORY:{base}")
    base.mkdir(parents=True, exist_ok=True)
    path = (base / f"prospective-lifecycle-test-{uuid.uuid4().hex}").resolve(strict=False)
    if path.parent != base or path.exists():
        pytest.fail(f"PROSPECTIVE_TEST_TEMP_PATH_NOT_ISOLATED:{path}")
    path.mkdir()
    try:
        yield path
    finally:
        if path.parent != base:
            pytest.fail(f"PROSPECTIVE_TEST_TEMP_CLEANUP_SCOPE_INVALID:{path}")
        shutil.rmtree(path)


def test_prospective_tmp_path_is_external(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    assert tmp_path != repository
    assert repository not in tmp_path.parents


def research_spec(task_root: Path, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "research_id": "BRANCH_NEW",
        "canonical_name": "new branch",
        "research_family": "event timing",
        "economic_mechanism": "information arrival",
        "target": "cross sectional ranking",
        "information_source": "source alpha",
        "portfolio_role": "selection overlay",
        "hypothesis": "new information may alter selection",
        "task_root": str(task_root.resolve()),
        "code_reference": "git:abc123",
        "config_reference": "config/spec.json",
        "data_reference": "contract://source-alpha",
        "tested_scope": {"variant": "ridge"},
    }
    value.update(changes)
    return lifecycle.normalize_research_spec(value)


def stage_registry(repo: Path) -> None:
    target = repo / "scripts/maintenance/research_registry.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(lifecycle.__file__).with_name("research_registry.py"), target)


def prior_entity(spec: dict[str, object], status: str = "CLOSED_NEGATIVE") -> dict[str, object]:
    return {
        "entity_id": "BRANCH_PRIOR",
        "status": "CLOSED",
        "metadata": {
            "mechanism_key": lifecycle.mechanism_key(spec),
            "final_status": status,
            "final_conclusion_ref": "receipt://prior",
            "reopen_condition_ref": "receipt://prior#reopen",
        },
    }


def registry_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "decision": "PASS_DISTINCT_INFORMATION_SOURCE",
        "matched_entity_ids": [],
        "reasons": ["distinct authoritative information"],
        "registry_head_sha256": "a" * 64,
    }


def storage(tmp_path: Path) -> SimpleNamespace:
    roots = {
        name: tmp_path / name
        for name in ("repo", "data", "envs", "cache", "results")
    }
    for path in roots.values():
        path.mkdir()
    return SimpleNamespace(
        repo_root=roots["repo"], data_root=roots["data"],
        envs_root=roots["envs"], cache_root=roots["cache"],
        results_root=roots["results"],
    )


def receipt(spec: dict[str, object], final_status: str = "CLOSED_NEGATIVE") -> dict[str, object]:
    return {
        "research_id": spec["research_id"],
        "mechanism_key": lifecycle.mechanism_key(spec),
        "hypothesis": spec["hypothesis"],
        "final_status": final_status,
        "key_conclusion": "mechanism closed",
        "key_metrics_summary": {"recorded": True},
        "trial_count": {field: 0 for field in lifecycle.TRIAL_FIELDS},
        "code_commit": "abc123",
        "config_reference": spec["config_reference"],
        "data_reference": spec["data_reference"],
        "stop_reason": "predeclared stop condition",
        "reopen_condition": "new source required",
        "related_branch": "BRANCH_PRIOR",
        "completed_at": "2025-12-31T00:00:00+00:00",
    }


def artifact_row(path: Path, retention_class: str, **changes: object) -> dict[str, object]:
    provenance = {
        "KEEP_DATA": "RAW",
        "KEEP_ALGORITHM_REFERENCE": "ALGORITHM_REFERENCE",
        "KEEP_RESEARCH_KNOWLEDGE": "RESEARCH_KNOWLEDGE",
        "KEEP_ACTIVE_OPERATIONAL": "ACTIVE_OPERATIONAL",
        "SCRATCH_DISPOSABLE": "TASK_SCRATCH",
    }.get(retention_class, "DERIVED")
    row: dict[str, object] = {
        "path": str(path.resolve()),
        "object_type": "FILE",
        "size_bytes": path.stat().st_size,
        "retention_class": retention_class,
        "reason": "task lifecycle classification",
        "rebuildable": retention_class in lifecycle.DISPOSABLE_CLASSES,
        "protected": retention_class not in lifecycle.DISPOSABLE_CLASSES,
        "delete_after_completion": retention_class in lifecycle.DISPOSABLE_CLASSES,
        "provenance": provenance,
    }
    if retention_class in lifecycle.DISPOSABLE_CLASSES:
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    row.update(changes)
    return row


def test_closed_negative_mechanism_without_reopen_is_blocked(tmp_path: Path) -> None:
    spec = research_spec(tmp_path / "results" / "task")
    decision = lifecycle.evaluate_start_decision(
        spec, [prior_entity(spec)], registry_pass(),
    )
    assert decision["decision"] == "BLOCK_AS_DUPLICATE_RESEARCH"
    assert decision["matched_prior_branch"] == "BRANCH_PRIOR"


def test_same_family_with_genuinely_new_source_may_proceed(tmp_path: Path) -> None:
    old = research_spec(tmp_path / "results" / "old")
    new = research_spec(
        tmp_path / "results" / "new", information_source="source beta",
        data_reference="contract://source-beta",
    )
    decision = lifecycle.evaluate_start_decision(new, [prior_entity(old)], registry_pass())
    assert lifecycle.mechanism_key(old) != lifecycle.mechanism_key(new)
    assert decision["decision"] == "ALLOW_NEW_RESEARCH"


def test_documented_reopen_condition_is_supported(tmp_path: Path) -> None:
    raw = research_spec(tmp_path / "results" / "task")
    raw["reopen_request"] = {
        "basis": "SATISFIED_REOPEN_CONDITION",
        "condition_satisfied": True,
        "evidence_reference": "contract://new-source",
    }
    decision = lifecycle.evaluate_start_decision(raw, [prior_entity(raw)], registry_pass())
    assert decision["decision"] == "ALLOW_REOPEN"


def test_claimed_new_source_requires_structural_source_delta(tmp_path: Path) -> None:
    spec = research_spec(tmp_path / "results" / "task")
    spec["reopen_request"] = {
        "basis": "NEW_DATA_SOURCE", "evidence_reference": "contract://claim-only",
    }
    prior = prior_entity(spec)
    prior["metadata"]["information_source"] = spec["information_source"]
    decision = lifecycle.evaluate_start_decision(spec, [prior], registry_pass())
    assert decision["decision"] == "BLOCK_AS_DUPLICATE_RESEARCH"


def test_reopen_requires_new_research_id(tmp_path: Path) -> None:
    spec = research_spec(tmp_path / "results" / "task", research_id="BRANCH_PRIOR")
    spec["reopen_request"] = {
        "basis": "SATISFIED_REOPEN_CONDITION",
        "condition_satisfied": True,
        "evidence_reference": "contract://new-source",
    }
    decision = lifecycle.evaluate_start_decision(spec, [prior_entity(spec)], registry_pass())
    assert decision["decision"] == "BLOCK_AS_DUPLICATE_RESEARCH"


def test_completed_task_marks_computational_payload_disposable(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    retained = task_root / "retained"
    scratch = task_root / "scratch"
    retained.mkdir(parents=True)
    scratch.mkdir()
    receipt_path = retained / "result_receipt.json"
    receipt_path.write_text("{}", encoding="utf-8")
    payloads = []
    for name in ("predictions.parquet", "feature_matrix.parquet", "model.bin"):
        path = scratch / name
        path.write_bytes(name.encode("ascii"))
        payloads.append(path)
    spec = research_spec(task_root)
    manifest = {
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [
            artifact_row(receipt_path, "KEEP_RESEARCH_KNOWLEDGE"),
            *(artifact_row(path, "DERIVED_DISPOSABLE") for path in payloads),
        ],
    }
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validated = lifecycle.validate_retention_manifest(manifest_path, spec, paths)
    assert sum(
        row["retention_class"] == "DERIVED_DISPOSABLE" for row in validated["rows"]
    ) == 3
    assert any(row["retention_class"] == "KEEP_RESEARCH_KNOWLEDGE" for row in validated["rows"])


@pytest.mark.parametrize("provenance", ["RAW", "PROVIDER", "SOURCE_DATABASE", "EXTERNAL"])
def test_raw_or_provider_data_is_never_disposable(provenance: str) -> None:
    assert lifecycle.artifact_retention(provenance=provenance) == "KEEP_DATA"


def test_forward_decision_evidence_is_retained() -> None:
    assert lifecycle.artifact_retention(
        provenance="DERIVED", forward_decision=True,
    ) == "KEEP_KEY_EVIDENCE"


def test_manifest_cannot_dispose_source_data(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    source = task_root / "provider.sqlite"
    source.write_bytes(b"source")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(
            source, "DERIVED_DISPOSABLE", provenance="PROVIDER",
        )],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="RETENTION_CLASS_CONTRADICTS_PROVENANCE"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_manifest_cannot_dispose_forward_evidence(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    decision = task_root / "decision.json"
    decision.write_text("{}", encoding="utf-8")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(
            decision, "DERIVED_DISPOSABLE", forward_decision=True,
            key_evidence_justification="pre-outcome decision evidence",
        )],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="RETENTION_CLASS_CONTRADICTS_PROVENANCE"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_manifest_requires_actual_json_booleans(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    payload = task_root / "payload.bin"
    payload.write_bytes(b"payload")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(payload, "DERIVED_DISPOSABLE", rebuildable="false")],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="BOOLEAN_FIELD_INVALID:rebuildable"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_manifest_rejects_unknown_provenance(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    payload = task_root / "payload.bin"
    payload.write_bytes(b"payload")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(payload, "DERIVED_DISPOSABLE", provenance="typo")],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="UNKNOWN_ARTIFACT_PROVENANCE"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_manifest_rejects_missing_retained_evidence(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    evidence = task_root / "receipt.json"
    evidence.write_text("{}", encoding="utf-8")
    row = artifact_row(evidence, "KEEP_RESEARCH_KNOWLEDGE")
    evidence.unlink()
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1, "task_id": spec["research_id"], "artifacts": [row],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="RETENTION_ARTIFACT_MISSING"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_superseded_canonical_payload_is_manifest_governed(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    canonical = paths.cache_root / "canonical" / "snapshot-2" / "payload.bin"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"derived snapshot")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(
            canonical,
            "DERIVED_DISPOSABLE",
            artifact_role="CANONICAL_SNAPSHOT_PAYLOAD",
            snapshot_id="snapshot-2",
            source_data_fingerprint="source-fingerprint",
            producer_commit="abc123",
            config_hash="config-fingerprint",
            output_fingerprint="output-fingerprint",
            status="SUPERSEDED_REBUILDABLE",
            supersedes="snapshot-1",
        )],
    }), encoding="utf-8")
    validated = lifecycle.validate_retention_manifest(manifest_path, spec, paths)
    assert validated["rows"][0]["retention_class"] == "DERIVED_DISPOSABLE"


def test_completed_clean_preserved_worktree_requests_retirement() -> None:
    assert lifecycle.worktree_retirement_decision(
        completed=True, clean=True, head_preserved=True, active=False,
    ) == "RETIRE"
    assert lifecycle.worktree_retirement_decision(
        completed=True, clean=False, head_preserved=True, active=False,
    ) == "REVIEW"


def test_worktree_retirement_uses_git_without_force_or_direct_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()
    worktree.mkdir()
    calls: list[list[str]] = []

    def fake_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments == ["worktree", "list", "--porcelain"]:
            value = str(worktree.resolve()).replace("\\", "/")
            return subprocess.CompletedProcess(arguments, 0, f"worktree {value}\n", "")
        if arguments == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["rev-parse", "HEAD"]:
            value = "main456\n" if cwd == repo else "abc123\n"
            return subprocess.CompletedProcess(arguments, 0, value, "")
        if arguments == ["symbolic-ref", "-q", "HEAD"]:
            return subprocess.CompletedProcess(arguments, 0, "refs/heads/task\n", "")
        if arguments == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(arguments, 0, ".git\n", "")
        if arguments[:3] == ["show-ref", "--verify", "--quiet"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["rev-parse", "refs/heads/task"]:
            return subprocess.CompletedProcess(arguments, 0, "abc123\n", "")
        if arguments == ["merge-base", "--is-ancestor", "abc123", "main456"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(lifecycle, "_git", fake_git)
    result = lifecycle.retire_completed_worktree(
        repo, worktree, task_completed=True, active=False,
    )
    assert result["status"] == "RETIRED"
    assert ["worktree", "remove", str(worktree.resolve())] in calls
    assert all("--force" not in arguments for arguments in calls)


def test_clean_unmerged_worktree_is_review_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()
    worktree.mkdir()
    calls: list[list[str]] = []

    def fake_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments == ["worktree", "list", "--porcelain"]:
            value = str(worktree.resolve()).replace("\\", "/")
            return subprocess.CompletedProcess(arguments, 0, f"worktree {value}\n", "")
        if arguments == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["rev-parse", "HEAD"]:
            value = "main456\n" if cwd == repo else "task789\n"
            return subprocess.CompletedProcess(arguments, 0, value, "")
        if arguments == ["symbolic-ref", "-q", "HEAD"]:
            return subprocess.CompletedProcess(arguments, 0, "refs/heads/task\n", "")
        if arguments == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(arguments, 0, ".git\n", "")
        if arguments[:3] == ["show-ref", "--verify", "--quiet"]:
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments == ["rev-parse", "refs/heads/task"]:
            return subprocess.CompletedProcess(arguments, 0, "task789\n", "")
        if arguments == ["merge-base", "--is-ancestor", "task789", "main456"]:
            return subprocess.CompletedProcess(arguments, 1, "", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(lifecycle, "_git", fake_git)
    result = lifecycle.retire_completed_worktree(
        repo, worktree, task_completed=True, active=False,
    )
    assert result == {"status": "WORKTREE_RETIREMENT_DEFERRED", "reason": "REVIEW"}
    assert not any(arguments[:2] == ["worktree", "remove"] for arguments in calls)


def test_dirty_worktree_never_reaches_git_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()
    worktree.mkdir()
    calls: list[list[str]] = []

    def fake_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments == ["worktree", "list", "--porcelain"]:
            value = str(worktree.resolve()).replace("\\", "/")
            return subprocess.CompletedProcess(arguments, 0, f"worktree {value}\n", "")
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
    result = lifecycle.retire_completed_worktree(
        repo, worktree, task_completed=True, active=False,
    )
    assert result == {"status": "WORKTREE_RETIREMENT_DEFERRED", "reason": "REVIEW"}
    assert not any(arguments[:2] == ["worktree", "remove"] for arguments in calls)


def test_site_packages_is_never_generic_cache_cleanup_candidate() -> None:
    assert lifecycle.cache_retention_class(
        provenance="DERIVED", producer_declared=True, site_packages=True,
    ) == "PERSISTENT_SOURCE"


def test_superseded_rebuildable_snapshot_keeps_metadata_only() -> None:
    assert lifecycle.canonical_snapshot_policy(rebuildable=True) == {
        "metadata": "KEEP", "payload": "DERIVED_DISPOSABLE",
    }
    assert lifecycle.canonical_snapshot_policy(forward_required=True)["payload"] == "KEEP_KEY_EVIDENCE"


def test_missing_retention_classification_fails_closed(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    unclassified = task_root / "prediction.parquet"
    unclassified.write_bytes(b"derived")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1, "task_id": spec["research_id"], "artifacts": [],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="UNCLASSIFIED_TASK_ARTIFACT"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_key_evidence_requires_explicit_justification(tmp_path: Path) -> None:
    paths = storage(tmp_path)
    task_root = paths.results_root / "task"
    task_root.mkdir()
    evidence = task_root / "series.parquet"
    evidence.write_bytes(b"series")
    spec = research_spec(task_root)
    manifest_path = task_root / "retention_manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "task_id": spec["research_id"],
        "artifacts": [artifact_row(evidence, "KEEP_KEY_EVIDENCE")],
    }), encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="KEY_EVIDENCE_JUSTIFICATION_REQUIRED"):
        lifecycle.validate_retention_manifest(manifest_path, spec, paths)


def test_host_cleanup_is_exact_and_hash_gated(tmp_path: Path) -> None:
    disposable = tmp_path / "prediction.bin"
    disposable.write_bytes(b"prediction")
    kept = tmp_path / "receipt.json"
    kept.write_text("{}", encoding="utf-8")
    result = lifecycle.host_cleanup(
        [
            artifact_row(disposable, "DERIVED_DISPOSABLE"),
            artifact_row(kept, "KEEP_RESEARCH_KNOWLEDGE"),
        ],
        task_completed=True,
        worker_active=False,
    )
    assert result["status"] == "PASS"
    assert not disposable.exists()
    assert kept.exists()


def test_previous_physical_completion_references_violate_registry_firewall() -> None:
    registry = lifecycle._registry_module(Path(lifecycle.__file__).resolve().parents[2])
    physical_reference = (
        "D:/synthetic/holdout-sharpe-1/retained/result_receipt.json"
    )
    reference_fields = (
        "research_knowledge_ref", "final_conclusion_ref",
        "key_result_summary_ref", "stop_reason_ref", "reopen_condition_ref",
    )
    operations = [{
        "op": "add_entity",
        "entity": {
            "metadata": {field: physical_reference for field in reference_fields},
        },
    }]

    with pytest.raises(
        registry.RegistryError, match="PERFORMANCE_METRIC_VALUES_FORBIDDEN",
    ) as raised:
        registry._reject_outcome_fields({"operations": operations})

    for field in reference_fields:
        assert f"operations[0].entity.metadata.{field}" in str(raised.value)


def test_completion_uses_content_addressed_receipt_reference(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    registry_root = tmp_path / "registry"
    (repo / "config").mkdir(parents=True)
    stage_registry(repo)
    (repo / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    task_root = tmp_path / "holdout-sharpe-1" / "results" / "task"
    task_root.mkdir(parents=True)
    spec = research_spec(task_root)
    knowledge = task_root / "result_receipt.json"
    knowledge.write_text("{}", encoding="utf-8")
    completed = receipt(spec)
    registry = lifecycle._registry_module(repo)

    result = lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    stored = registry.query_registry(
        registry_root, entity_id=str(spec["research_id"]),
    )["entities"][0]
    metadata = stored["metadata"]
    expected_sha256 = hashlib.sha256(knowledge.read_bytes()).hexdigest()
    expected_reference = f"receipt://sha256/{expected_sha256}"
    reference_fields = (
        "research_knowledge_ref", "final_conclusion_ref",
        "key_result_summary_ref", "stop_reason_ref", "reopen_condition_ref",
    )

    assert result["status"] == "APPLIED"
    assert metadata["research_knowledge_sha256"] == expected_sha256
    assert all(metadata[field] == expected_reference for field in reference_fields)
    assert str(knowledge.resolve()) not in json.dumps(metadata, sort_keys=True)
    assert registry._performance_value_paths(metadata) == []
    assert registry.validate_registry(registry_root)["status"] == "PASS"


def test_existing_immutable_registry_accepts_compact_completion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    registry_root = tmp_path / "registry"
    (repo / "config").mkdir(parents=True)
    stage_registry(repo)
    (repo / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    task_root = tmp_path / "results" / "task"
    task_root.mkdir(parents=True)
    spec = research_spec(task_root)
    knowledge = task_root / "result_receipt.json"
    knowledge.write_text("{}", encoding="utf-8")
    completed = receipt(spec)
    result = lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    repeated = lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    assert result["status"] == "APPLIED"
    assert repeated["status"] == "ALREADY_APPLIED"


def test_existing_active_registry_row_is_closed_with_completion_knowledge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    registry_root = tmp_path / "registry"
    (repo / "config").mkdir(parents=True)
    stage_registry(repo)
    (repo / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    task_root = tmp_path / "results" / "task"
    task_root.mkdir(parents=True)
    spec = research_spec(task_root)
    registry = lifecycle._registry_module(repo)
    active = {
        **lifecycle.registry_candidate(spec),
        "status": "ACTIVE",
        "evidence_source_temporal_status": "STRUCTURAL_GOVERNANCE_METADATA_ONLY",
        "excluded_source_refs": [],
        "temporal_evidence_limitations": [],
        "metadata": {"mechanism_key": lifecycle.mechanism_key(spec), "prior_note": "keep"},
    }
    operations = [{"op": "add_entity", "entity": active}]
    registry.apply_patch(registry_root, {
        "schema_version": 1,
        "expected_base_head_sha256": registry.GENESIS,
        "author": "synthetic-test",
        "event_time_utc": "2025-12-30T00:00:00+00:00",
        "validation": {"status": "PASS", "post_2025_observation_count": 0},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": "test-reviewer"},
        "operations": operations,
        "operation_count": 1,
        "operations_sha256": registry.sha256_value(operations),
    })
    knowledge = task_root / "result_receipt.json"
    knowledge.write_text("{}", encoding="utf-8")
    completed = receipt(spec)
    result = lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    stored = registry.query_registry(registry_root, entity_id=str(spec["research_id"]))["entities"][0]
    assert result["status"] == "APPLIED"
    assert stored["status"] == "CLOSED"
    assert stored["metadata"]["prior_note"] == "keep"
    expected_sha256 = hashlib.sha256(knowledge.read_bytes()).hexdigest()
    assert stored["metadata"]["research_knowledge_ref"] == (
        f"receipt://sha256/{expected_sha256}"
    )
    assert stored["metadata"]["research_knowledge_sha256"] == expected_sha256


def test_terminal_completion_idempotency_rejects_receipt_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    registry_root = tmp_path / "registry"
    (repo / "config").mkdir(parents=True)
    stage_registry(repo)
    (repo / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    task_root = tmp_path / "results" / "task"
    task_root.mkdir(parents=True)
    spec = research_spec(task_root)
    knowledge = task_root / "result_receipt.json"
    knowledge.write_text("{}", encoding="utf-8")
    completed = receipt(spec)
    lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    drifted = {**completed, "completed_at": "2025-12-30T00:00:00+00:00"}
    with pytest.raises(lifecycle.LifecycleError, match="TERMINAL_REGISTRY_COMPLETION_DRIFT"):
        lifecycle.apply_registry_completion(
            repo, spec, drifted, knowledge, reviewer="independent-reviewer",
        )


def test_terminal_completion_pins_receipt_hash(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    registry_root = tmp_path / "registry"
    (repo / "config").mkdir(parents=True)
    stage_registry(repo)
    (repo / "config" / "research_registry.json").write_text(json.dumps({
        "schema_version": 1, "registry_root": str(registry_root),
    }), encoding="utf-8")
    task_root = tmp_path / "results" / "task"
    task_root.mkdir(parents=True)
    spec = research_spec(task_root)
    knowledge = task_root / "result_receipt.json"
    knowledge.write_text("{}", encoding="utf-8")
    completed = receipt(spec)
    lifecycle.apply_registry_completion(
        repo, spec, completed, knowledge, reviewer="independent-reviewer",
    )
    knowledge.write_text('{"drift":true}', encoding="utf-8")
    with pytest.raises(lifecycle.LifecycleError, match="TERMINAL_REGISTRY_COMPLETION_DRIFT"):
        lifecycle.apply_registry_completion(
            repo, spec, completed, knowledge, reviewer="independent-reviewer",
        )


def test_completion_receipt_requires_terminal_status(tmp_path: Path) -> None:
    spec = research_spec(tmp_path / "results" / "task")
    with pytest.raises(lifecycle.LifecycleError, match="COMPLETION_RECEIPT_STATUS_NOT_TERMINAL"):
        lifecycle.validate_completion_receipt(receipt(spec, final_status="ACTIVE"), spec)


def test_closed_negative_budget_is_five_mib() -> None:
    report = lifecycle.retention_budget(
        {"final_status": "CLOSED_NEGATIVE"}, {"retained_bytes": 6 * 1024 * 1024},
    )
    assert report == {
        "retained_bytes": 6 * 1024 * 1024,
        "budget_bytes": 5 * 1024 * 1024,
        "status": "KEY_EVIDENCE_JUSTIFICATION_REQUIRED",
    }
