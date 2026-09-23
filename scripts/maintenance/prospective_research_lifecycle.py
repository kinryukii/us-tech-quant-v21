"""Prospective research lifecycle helpers for the existing Harness.

This module is task-local: it reuses the authoritative research registry,
creates no registry of its own, and only deletes exact manifest paths.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RESEARCH_SPEC_FIELDS = (
    "research_id", "research_family", "economic_mechanism", "target",
    "information_source", "portfolio_role", "hypothesis", "task_root",
    "code_reference", "config_reference", "data_reference",
)
TRIAL_FIELDS = (
    "hypothesis_trials", "feature_trials", "model_trials",
    "hyperparameter_trials", "portfolio_threshold_trials", "holdout_peeks",
)
RETENTION_CLASSES = {
    "KEEP_DATA", "KEEP_ALGORITHM_REFERENCE", "KEEP_RESEARCH_KNOWLEDGE",
    "KEEP_KEY_EVIDENCE", "KEEP_ACTIVE_OPERATIONAL", "DERIVED_DISPOSABLE",
    "SCRATCH_DISPOSABLE",
}
DISPOSABLE_CLASSES = {"DERIVED_DISPOSABLE", "SCRATCH_DISPOSABLE"}
PROVENANCE_CLASSES = {
    "RAW", "PROVIDER", "PROVIDER_RAW", "ACQUISITION", "SOURCE",
    "SOURCE_DATABASE", "EXTERNAL", "MANUAL_SOURCE",
    "ALGORITHM", "CODE", "CONFIG", "ALGORITHM_REFERENCE",
    "RESEARCH_KNOWLEDGE", "ACTIVE_OPERATIONAL", "TASK_SCRATCH", "SCRATCH",
    "DERIVED",
}
TERMINAL_COMPLETION_STATUSES = {
    "COMPLETED", "CLOSED", "CLOSED_NEGATIVE", "FAILED", "REJECTED",
    "SUPERSEDED", "PARKED", "DEPRIORITIZED", "PROMOTED", "FROZEN",
}
TERMINAL_DUPLICATE_STATUSES = {
    "CLOSED", "CLOSED_NEGATIVE", "FAILED", "TOMBSTONED", "SUPERSEDED",
    "PARKED", "DEPRIORITIZED",
}
REOPEN_BASES = {
    "NEW_DATA_SOURCE", "NEW_ECONOMIC_MECHANISM", "NEW_TARGET_OBJECTIVE",
    "SATISFIED_REOPEN_CONDITION", "PRIOR_DEFECT_INVALIDATION",
    "FORWARD_PREDECLARED_REVISIT",
}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
NORMAL_BUDGET_BYTES = 25 * 1024 * 1024
NEGATIVE_BUDGET_BYTES = 5 * 1024 * 1024


class LifecycleError(RuntimeError):
    """A fail-closed prospective lifecycle condition."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _normalize(value: Any) -> str:
    text = str(value).casefold().strip()
    return "-".join(
        "".join(character if character.isalnum() else " " for character in text).split()
    )


def _required_text(mapping: Mapping[str, Any], field: str) -> str:
    value = str(mapping.get(field, "")).strip()
    if not value:
        raise LifecycleError(f"REQUIRED_FIELD_MISSING:{field}")
    return value


def _required_bool(mapping: Mapping[str, Any], field: str, *, default: bool | None = None) -> bool:
    if field not in mapping:
        if default is not None:
            return default
        raise LifecycleError(f"BOOLEAN_FIELD_MISSING:{field}")
    value = mapping[field]
    if not isinstance(value, bool):
        raise LifecycleError(f"BOOLEAN_FIELD_INVALID:{field}")
    return value


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def load_small_json(path: Path, *, maximum_bytes: int = 262_144) -> dict[str, Any]:
    try:
        if path.stat().st_size > maximum_bytes:
            raise LifecycleError(f"SMALL_JSON_BUDGET_EXCEEDED:{path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"SMALL_JSON_UNREADABLE:{path}:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise LifecycleError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def normalize_research_spec(raw: Mapping[str, Any]) -> dict[str, Any]:
    spec = {field: _required_text(raw, field) for field in RESEARCH_SPEC_FIELDS}
    task_root = Path(spec["task_root"])
    if not task_root.is_absolute():
        raise LifecycleError("TASK_ROOT_MUST_BE_ABSOLUTE")
    spec["task_root"] = str(_absolute_lexical(task_root))
    spec["canonical_name"] = str(raw.get("canonical_name", spec["research_id"])).strip()
    spec["tested_scope"] = raw.get("tested_scope", {})
    spec["aliases"] = [str(value).strip() for value in raw.get("aliases", []) if str(value).strip()]
    spec["excluded_source_refs"] = [
        str(value).strip() for value in raw.get("excluded_source_refs", []) if str(value).strip()
    ]
    spec["temporal_evidence_limitations"] = [
        str(value).strip() for value in raw.get("temporal_evidence_limitations", [])
        if str(value).strip()
    ]
    reopen = raw.get("reopen_request", {})
    if reopen is not None and not isinstance(reopen, Mapping):
        raise LifecycleError("REOPEN_REQUEST_MUST_BE_OBJECT")
    spec["reopen_request"] = dict(reopen or {})
    return spec


def mechanism_key(spec: Mapping[str, Any]) -> str:
    identity = {
        field: _normalize(_required_text(spec, field))
        for field in (
            "research_family", "economic_mechanism", "target",
            "information_source", "portfolio_role",
        )
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _registry_module(repo: Path):
    source = repo / "scripts/maintenance/research_registry.py"
    module_spec = importlib.util.spec_from_file_location(
        "ustq_authoritative_research_registry", source,
    )
    if module_spec is None or module_spec.loader is None:
        raise LifecycleError(f"AUTHORITATIVE_REGISTRY_UTILITY_UNAVAILABLE:{source}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _registry_root(repo: Path) -> Path:
    config = load_small_json(repo / "config" / "research_registry.json", maximum_bytes=16_384)
    value = _required_text(config, "registry_root")
    root = Path(value)
    return root.resolve(strict=False) if root.is_absolute() else (repo / root).resolve(strict=False)


def registry_candidate(spec: Mapping[str, Any]) -> dict[str, Any]:
    key = mechanism_key(spec)
    specification = {
        "mechanism_key": key,
        "tested_scope": spec.get("tested_scope", {}),
        "config_reference": spec["config_reference"],
    }
    information_source = _normalize(spec["information_source"])
    mechanism = {
        "family": _normalize(spec["research_family"]),
        "mechanism": _normalize(spec["economic_mechanism"]),
        "target": _normalize(spec["target"]),
        "portfolio_role": _normalize(spec["portfolio_role"]),
    }
    return {
        "entity_id": spec["research_id"],
        "canonical_name": spec["canonical_name"],
        "aliases": list(spec.get("aliases", [])),
        "entity_type": "RESEARCH_BRANCH",
        "specification": specification,
        "specification_fingerprint": hashlib.sha256(_canonical_json(specification)).hexdigest(),
        "information_source": information_source,
        "information_source_fingerprint": hashlib.sha256(
            _canonical_json(information_source)
        ).hexdigest(),
        "mechanism": mechanism,
        "mechanism_fingerprint": hashlib.sha256(_canonical_json(mechanism)).hexdigest(),
        "decision_layer": _normalize(spec["portfolio_role"]),
        "information_family": _normalize(spec["information_source"]),
        "source_contract_ref": spec["data_reference"],
        "mechanism_key": key,
    }


def _entity_metadata(entity: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = entity.get("metadata", {})
    return metadata if isinstance(metadata, Mapping) else {}


def evaluate_start_decision(
    spec: Mapping[str, Any],
    entities: Sequence[Mapping[str, Any]],
    registry_decision: Mapping[str, Any],
) -> dict[str, Any]:
    key = mechanism_key(spec)
    exact = [
        entity for entity in entities
        if str(_entity_metadata(entity).get("mechanism_key", "")) == key
    ]
    matched_ids = list(registry_decision.get("matched_entity_ids", []))
    by_id = {str(entity.get("entity_id", "")): entity for entity in entities}
    matched = exact or [by_id[value] for value in matched_ids if value in by_id]
    prior = matched[0] if matched else {}
    metadata = _entity_metadata(prior)
    prior_status = str(metadata.get("final_status", prior.get("status", ""))).upper()
    prior_conclusion = str(
        metadata.get("final_conclusion", metadata.get("final_conclusion_ref", ""))
    )
    reopen_condition = str(
        metadata.get("reopen_condition", metadata.get("reopen_condition_ref", ""))
    )
    reopen = spec.get("reopen_request", {})
    basis = str(reopen.get("basis", "")).upper() if isinstance(reopen, Mapping) else ""
    evidence = (
        str(reopen.get("evidence_reference", "")).strip()
        if isinstance(reopen, Mapping) else ""
    )
    condition_satisfied = (
        bool(reopen.get("condition_satisfied")) if isinstance(reopen, Mapping) else False
    )
    terminal_match = bool(matched and prior_status in TERMINAL_DUPLICATE_STATUSES)

    if terminal_match:
        reopen_allowed = basis in REOPEN_BASES and bool(evidence)
        prior_information_source = str(
            metadata.get("information_source", prior.get("information_source", ""))
        )
        prior_mechanism = str(
            metadata.get("economic_mechanism", prior.get("economic_mechanism", ""))
        )
        prior_target = str(metadata.get("target", prior.get("target", "")))
        if basis == "NEW_DATA_SOURCE":
            reopen_allowed = (
                reopen_allowed
                and bool(prior_information_source)
                and _normalize(spec["information_source"]) != _normalize(prior_information_source)
            )
        elif basis == "NEW_ECONOMIC_MECHANISM":
            reopen_allowed = (
                reopen_allowed
                and bool(prior_mechanism)
                and _normalize(spec["economic_mechanism"]) != _normalize(prior_mechanism)
            )
        elif basis == "NEW_TARGET_OBJECTIVE":
            reopen_allowed = (
                reopen_allowed
                and bool(prior_target)
                and _normalize(spec["target"]) != _normalize(prior_target)
            )
        if basis == "SATISFIED_REOPEN_CONDITION":
            reopen_allowed = reopen_allowed and bool(reopen_condition) and condition_satisfied
        if reopen_allowed and str(spec["research_id"]) == str(prior.get("entity_id", "")):
            reopen_allowed = False
        decision = "ALLOW_REOPEN" if reopen_allowed else "BLOCK_AS_DUPLICATE_RESEARCH"
        justification = (
            f"documented_reopen_basis={basis};evidence={evidence}"
            if reopen_allowed
            else "terminal equivalent mechanism exists and no documented reopen gate is satisfied"
        )
    elif str(registry_decision.get("status", "")).upper() == "PASS":
        decision = "ALLOW_NEW_RESEARCH"
        justification = ";".join(str(value) for value in registry_decision.get("reasons", []))
    elif str(registry_decision.get("status", "")).upper() == "BLOCKED":
        decision = "BLOCK_AS_DUPLICATE_RESEARCH"
        justification = ";".join(str(value) for value in registry_decision.get("reasons", []))
    else:
        decision = "REVIEW_REQUIRED"
        justification = ";".join(str(value) for value in registry_decision.get("reasons", []))

    return {
        "mechanism_key": key,
        "matched_prior_branch": str(
            prior.get("entity_id", matched_ids[0] if matched_ids else "")
        ),
        "prior_status": prior_status,
        "prior_conclusion": prior_conclusion,
        "reopen_condition": reopen_condition,
        "decision": decision,
        "justification": justification or "registry classified the proposal",
        "registry_head_sha256": str(registry_decision.get("registry_head_sha256", "")),
    }


def research_start_gate(repo: Path, spec_path: Path, *, storage: Any | None = None) -> dict[str, Any]:
    spec = normalize_research_spec(load_small_json(spec_path))
    task_root = Path(spec["task_root"])
    if storage is not None:
        results_root = _absolute_lexical(Path(storage.results_root))
        if not _is_within(task_root, results_root) or task_root == results_root:
            raise LifecycleError(f"TASK_ROOT_OUTSIDE_RESULTS_ROOT:{task_root}")
        if _has_reparse_component(task_root, results_root):
            raise LifecycleError(f"PROSPECTIVE_TASK_ROOT_REPARSE_REQUIRED_REVIEW:{task_root}")
    if task_root.exists():
        if not task_root.is_dir():
            raise LifecycleError(f"PROSPECTIVE_TASK_ROOT_NOT_DIRECTORY:{task_root}")
        try:
            with os.scandir(task_root) as entries:
                if next(entries, None) is not None:
                    raise LifecycleError(f"PROSPECTIVE_TASK_ROOT_NOT_EMPTY:{task_root}")
        except OSError as exc:
            raise LifecycleError(
                f"PROSPECTIVE_TASK_ROOT_UNENUMERABLE:{task_root}:{type(exc).__name__}"
            ) from exc
    registry = _registry_module(repo)
    root = _registry_root(repo)
    for _ in range(2):
        query = registry.query_registry(root)
        decision = registry.preflight_proposal(root, {"candidate": registry_candidate(spec)})
        if query["head_sha256"] == decision.get("registry_head_sha256"):
            return {
                "spec": spec,
                "decision": evaluate_start_decision(spec, query["entities"], decision),
            }
    raise LifecycleError("REGISTRY_HEAD_DRIFT_DURING_START_GATE")


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse_artifact(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _has_reparse_component(path: Path, boundary: Path | None = None) -> bool:
    current = path
    boundary = _absolute_lexical(boundary) if boundary is not None else None
    while True:
        if _is_reparse_artifact(current):
            return True
        if current == boundary or current.parent == current:
            return False
        current = current.parent


def protected_roots(storage: Any) -> tuple[Path, ...]:
    cache = Path(storage.cache_root).resolve(strict=False)
    roots = [
        Path(storage.repo_root).resolve(strict=False),
        Path(storage.data_root).resolve(strict=False),
        Path(storage.envs_root).resolve(strict=False),
        Path(r"D:\us-tech-quant-external-data").resolve(strict=False),
        cache / "raw", cache / "provider", cache / "acquisition",
        cache / "migrated_from_repo",
    ]
    return tuple(root.resolve(strict=False) for root in roots)


def validate_trial_count(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise LifecycleError("TRIAL_COUNT_OBJECT_REQUIRED")
    result: dict[str, int] = {}
    for field in TRIAL_FIELDS:
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise LifecycleError(f"NONNEGATIVE_TRIAL_COUNT_REQUIRED:{field}")
        result[field] = raw
    return result


def validate_completion_receipt(
    receipt: Mapping[str, Any], spec: Mapping[str, Any],
) -> dict[str, Any]:
    required = (
        "research_id", "mechanism_key", "hypothesis", "final_status",
        "key_conclusion", "key_metrics_summary", "trial_count", "code_commit",
        "config_reference", "data_reference", "stop_reason", "reopen_condition",
        "completed_at",
    )
    for field in required:
        if field not in receipt or receipt[field] in (None, ""):
            raise LifecycleError(f"COMPLETION_RECEIPT_FIELD_MISSING:{field}")
    if str(receipt["research_id"]) != str(spec["research_id"]):
        raise LifecycleError("COMPLETION_RECEIPT_RESEARCH_ID_MISMATCH")
    if str(receipt["mechanism_key"]) != mechanism_key(spec):
        raise LifecycleError("COMPLETION_RECEIPT_MECHANISM_KEY_MISMATCH")
    final_status = str(receipt["final_status"]).strip().upper()
    if final_status not in TERMINAL_COMPLETION_STATUSES:
        raise LifecycleError(f"COMPLETION_RECEIPT_STATUS_NOT_TERMINAL:{final_status}")
    validate_trial_count(receipt["trial_count"])
    try:
        datetime.fromisoformat(str(receipt["completed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("COMPLETION_RECEIPT_TIME_INVALID") from exc
    return dict(receipt)


def validate_retention_manifest(
    manifest_path: Path, spec: Mapping[str, Any], storage: Any,
) -> dict[str, Any]:
    manifest = load_small_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise LifecycleError("RETENTION_MANIFEST_SCHEMA_INVALID")
    if str(manifest.get("task_id", "")) != str(spec["research_id"]):
        raise LifecycleError("RETENTION_MANIFEST_TASK_ID_MISMATCH")
    task_root = _absolute_lexical(Path(spec["task_root"]))
    results_root = _absolute_lexical(Path(storage.results_root))
    canonical_root = _absolute_lexical(Path(storage.cache_root) / "canonical")
    if not _is_within(task_root, results_root) or task_root == results_root:
        raise LifecycleError(f"TASK_ROOT_OUTSIDE_RESULTS_ROOT:{task_root}")
    rows = manifest.get("artifacts")
    if not isinstance(rows, list):
        raise LifecycleError("RETENTION_MANIFEST_ARTIFACTS_REQUIRED")
    protected = protected_roots(storage)
    indexed: dict[Path, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise LifecycleError("RETENTION_ARTIFACT_OBJECT_REQUIRED")
        path = Path(_required_text(raw, "path"))
        if not path.is_absolute():
            raise LifecycleError(f"RETENTION_PATH_NOT_ABSOLUTE:{path}")
        path = _absolute_lexical(path)
        artifact_role = str(raw.get("artifact_role", "")).strip().upper()
        canonical_payload = artifact_role == "CANONICAL_SNAPSHOT_PAYLOAD"
        inside_task_root = _is_within(path, task_root) and path != task_root
        inside_canonical_root = (
            canonical_payload and _is_within(path, canonical_root) and path != canonical_root
        )
        if not inside_task_root and not inside_canonical_root:
            raise LifecycleError(f"RETENTION_PATH_OUTSIDE_TASK_ROOT:{path}")
        boundary = canonical_root if inside_canonical_root else task_root
        if _has_reparse_component(path, boundary):
            raise LifecycleError(f"REPARSE_ARTIFACT_REVIEW_REQUIRED:{path}")
        if path in indexed:
            raise LifecycleError(f"RETENTION_PATH_DUPLICATE:{path}")
        retention = str(raw.get("retention_class", ""))
        if retention not in RETENTION_CLASSES:
            raise LifecycleError(f"RETENTION_CLASS_MISSING_OR_INVALID:{path}")
        if any(_is_within(path, root) for root in protected):
            raise LifecycleError(f"PROTECTED_PATH_IN_RETENTION_MANIFEST:{path}")
        row = dict(raw)
        row["path"] = str(path)
        row["retention_class"] = retention
        row["delete_after_completion"] = _required_bool(raw, "delete_after_completion")
        row["protected"] = _required_bool(raw, "protected")
        row["rebuildable"] = _required_bool(raw, "rebuildable")
        forward_decision = _required_bool(raw, "forward_decision", default=False)
        object_type = str(raw.get("object_type", "")).strip().upper()
        if object_type not in {"FILE", "DIRECTORY"}:
            raise LifecycleError(f"RETENTION_OBJECT_TYPE_INVALID:{path}")
        row["object_type"] = object_type
        if not path.exists():
            raise LifecycleError(f"RETENTION_ARTIFACT_MISSING:{path}")
        if (object_type == "FILE" and not path.is_file()) or (
            object_type == "DIRECTORY" and not path.is_dir()
        ):
            raise LifecycleError(f"RETENTION_ARTIFACT_TYPE_MISMATCH:{path}:{object_type}")
        expected_size = raw.get("size_bytes")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise LifecycleError(f"ARTIFACT_SIZE_REQUIRED:{path}")
        if object_type == "FILE" and path.stat().st_size != expected_size:
            raise LifecycleError(f"ARTIFACT_SIZE_DRIFT:{path}")
        row["size_bytes"] = expected_size
        provenance = _required_text(raw, "provenance").upper()
        row["provenance"] = provenance
        if not str(raw.get("reason", "")).strip():
            raise LifecycleError(f"RETENTION_REASON_REQUIRED:{path}")
        if (
            retention == "KEEP_KEY_EVIDENCE"
            and not str(raw.get("key_evidence_justification", "")).strip()
        ):
            raise LifecycleError(f"KEY_EVIDENCE_JUSTIFICATION_REQUIRED:{path}")
        expected_retention = artifact_retention(
            provenance=provenance,
            key_evidence_reason=str(raw.get("key_evidence_justification", "")),
            forward_decision=forward_decision,
        )
        if canonical_payload:
            required_snapshot_fields = (
                "snapshot_id", "source_data_fingerprint", "producer_commit",
                "config_hash", "output_fingerprint", "status", "supersedes",
            )
            missing_snapshot = [
                field for field in required_snapshot_fields
                if field not in raw or (field != "supersedes" and not str(raw[field]).strip())
            ]
            if missing_snapshot:
                raise LifecycleError(f"CANONICAL_SNAPSHOT_METADATA_MISSING:{missing_snapshot}")
            snapshot_status = str(raw["status"]).strip().upper()
            if snapshot_status not in {
                "CURRENT", "PROMOTED", "FROZEN_REQUIRED", "FORWARD_REQUIRED",
                "SUPERSEDED_REBUILDABLE",
            }:
                raise LifecycleError(f"CANONICAL_SNAPSHOT_STATUS_INVALID:{snapshot_status}")
            snapshot_policy = canonical_snapshot_policy(
                current=snapshot_status == "CURRENT",
                promoted=snapshot_status == "PROMOTED",
                frozen_required=snapshot_status == "FROZEN_REQUIRED",
                forward_required=snapshot_status == "FORWARD_REQUIRED",
                rebuildable=snapshot_status == "SUPERSEDED_REBUILDABLE" and row["rebuildable"],
            )
            snapshot_retention = snapshot_policy["payload"]
            if snapshot_retention == "REVIEW":
                raise LifecycleError(f"CANONICAL_SNAPSHOT_REVIEW_REQUIRED:{path}")
            if expected_retention != "KEEP_DATA":
                expected_retention = snapshot_retention
        if retention != expected_retention:
            raise LifecycleError(
                f"RETENTION_CLASS_CONTRADICTS_PROVENANCE:{path}:{retention}:{expected_retention}"
            )
        if retention in DISPOSABLE_CLASSES:
            if row["protected"] or not row["rebuildable"] or not row["delete_after_completion"]:
                raise LifecycleError(f"DISPOSABLE_GATE_INCOMPLETE:{path}")
            expected_hash = str(raw.get("sha256", "")).lower()
            if object_type == "FILE" and not HEX_SHA256.fullmatch(expected_hash):
                raise LifecycleError(f"DISPOSABLE_SHA256_REQUIRED:{path}")
        indexed[path] = row

    if task_root.exists():
        for current, directories, files in os.walk(task_root):
            current_path = Path(current)
            for name in directories:
                if _is_reparse_artifact(current_path / name):
                    raise LifecycleError(f"REPARSE_ARTIFACT_REVIEW_REQUIRED:{current_path / name}")
            for name in files:
                path = _absolute_lexical(current_path / name)
                if path == _absolute_lexical(manifest_path):
                    continue
                if path not in indexed:
                    raise LifecycleError(f"UNCLASSIFIED_TASK_ARTIFACT:{path}")

    retained_bytes = sum(
        int(row.get("size_bytes", 0) or 0)
        for row in indexed.values()
        if row["retention_class"] not in DISPOSABLE_CLASSES
    )
    return {
        "manifest": manifest,
        "rows": list(indexed.values()),
        "retained_bytes": retained_bytes,
    }


def retention_budget(
    receipt: Mapping[str, Any], validated_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    final_status = str(receipt.get("final_status", "")).upper()
    limit = (
        NEGATIVE_BUDGET_BYTES
        if final_status in {"CLOSED_NEGATIVE", "FAILED", "REJECTED"}
        else NORMAL_BUDGET_BYTES
    )
    retained = int(validated_manifest.get("retained_bytes", 0))
    return {
        "retained_bytes": retained,
        "budget_bytes": limit,
        "status": "PASS" if retained <= limit else "KEY_EVIDENCE_JUSTIFICATION_REQUIRED",
    }


def apply_registry_completion(
    repo: Path, spec: Mapping[str, Any], receipt: Mapping[str, Any],
    receipt_path: Path, *, reviewer: str,
) -> dict[str, Any]:
    """Append one reviewed compact knowledge row to the existing registry."""
    registry = _registry_module(repo)
    root = _registry_root(repo)
    receipt_path = _absolute_lexical(receipt_path)
    task_root = _absolute_lexical(Path(spec["task_root"]))
    if not _is_within(receipt_path, task_root) or receipt_path == task_root:
        raise LifecycleError(f"COMPLETION_RECEIPT_OUTSIDE_TASK_ROOT:{receipt_path}")
    if _has_reparse_component(receipt_path, task_root):
        raise LifecycleError(f"COMPLETION_RECEIPT_REPARSE_REQUIRED_REVIEW:{receipt_path}")
    if not receipt_path.is_file():
        raise LifecycleError(f"COMPLETION_RECEIPT_MISSING:{receipt_path}")
    receipt_sha256 = _sha256_file(receipt_path)
    try:
        query = registry.query_registry(root, entity_id=str(spec["research_id"]))
    except registry.RegistryError as exc:
        if str(exc) != "REGISTRY_EMPTY":
            raise
        query = {"count": 0, "entities": [], "head_sha256": registry.GENESIS}
    key = mechanism_key(spec)
    final_status = str(receipt["final_status"]).upper()
    receipt_reference = f"receipt://sha256/{receipt_sha256}"
    terminal_status = "SUPERSEDED" if final_status == "SUPERSEDED" else "CLOSED"
    completion_metadata = {
        "mechanism_key": key,
        "research_family": spec["research_family"],
        "economic_mechanism": spec["economic_mechanism"],
        "target": spec["target"],
        "information_source": _normalize(spec["information_source"]),
        "portfolio_role": spec["portfolio_role"],
        "hypothesis_fingerprint": hashlib.sha256(
            str(spec["hypothesis"]).encode("utf-8")
        ).hexdigest(),
        "final_status": final_status,
        "research_knowledge_ref": receipt_reference,
        "research_knowledge_sha256": receipt_sha256,
        "final_conclusion_ref": receipt_reference,
        "key_result_summary_ref": receipt_reference,
        "stop_reason_ref": receipt_reference,
        "reopen_condition_ref": receipt_reference,
        "code_reference": receipt["code_commit"],
        "config_reference": receipt["config_reference"],
        "data_reference": receipt["data_reference"],
        "trial_count": validate_trial_count(receipt["trial_count"]),
        "related_branch": receipt.get("related_branch", ""),
        "completed_at": receipt["completed_at"],
        "retention_class": "KEEP_RESEARCH_KNOWLEDGE",
    }
    if query["count"]:
        prior = query["entities"][0]
        metadata = dict(_entity_metadata(prior))
        if str(metadata.get("mechanism_key", "")) != key:
            raise LifecycleError("REGISTRY_ENTITY_ID_COLLISION")
        if str(prior.get("status", "")).upper() in {"CLOSED", "TOMBSTONED", "SUPERSEDED"}:
            if (
                str(prior.get("status", "")).upper() == terminal_status
                and all(_canonical_json(metadata.get(field)) == _canonical_json(value)
                        for field, value in completion_metadata.items())
            ):
                return {"status": "ALREADY_APPLIED", "head_sha256": query["head_sha256"]}
            raise LifecycleError("TERMINAL_REGISTRY_COMPLETION_DRIFT")
        operations = [{
            "op": "update_entity",
            "entity": {
                "entity_id": spec["research_id"],
                "status": terminal_status,
                "metadata": {**metadata, **completion_metadata},
            },
        }]
    else:
        candidate = registry_candidate(spec)
        entity = {
            **candidate,
            "status": terminal_status,
            "evidence_source_temporal_status": "STRUCTURAL_GOVERNANCE_METADATA_ONLY",
            "excluded_source_refs": list(spec.get("excluded_source_refs", [])),
            "temporal_evidence_limitations": list(spec.get("temporal_evidence_limitations", [])),
            "metadata": completion_metadata,
        }
        operations = [{"op": "add_entity", "entity": entity}]
    patch = {
        "schema_version": 1,
        "expected_base_head_sha256": query["head_sha256"],
        "author": f"harness-worker:{spec['research_id']}",
        "event_time_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "validation": {"status": "PASS", "post_2025_observation_count": 0},
        "independent_review": {
            "status": "PASS", "independent": True, "reviewer": reviewer,
        },
        "operations": operations,
        "operation_count": 1,
        "operations_sha256": registry.sha256_value(operations),
    }
    result = registry.apply_patch(root, patch)
    return {"status": "APPLIED", "head_sha256": result["head_sha256"]}


def host_cleanup(
    rows: Sequence[Mapping[str, Any]], *, task_completed: bool, worker_active: bool,
    task_root: Path | None = None, storage: Any | None = None,
) -> dict[str, Any]:
    """Delete only hash-stable exact disposable files, then exact empty dirs."""
    if not task_completed or worker_active:
        raise LifecycleError("HOST_CLEANUP_REQUIRES_COMPLETED_INACTIVE_TASK")
    deleted: list[str] = []
    deferred: list[dict[str, str]] = []
    reclaimed = 0
    normalized_task_root = _absolute_lexical(task_root) if task_root is not None else None
    canonical_root = (
        _absolute_lexical(Path(storage.cache_root) / "canonical")
        if storage is not None else None
    )

    def deletion_boundary(row: Mapping[str, Any], path: Path) -> Path | None:
        role = str(row.get("artifact_role", "")).strip().upper()
        if role == "CANONICAL_SNAPSHOT_PAYLOAD" and canonical_root is not None:
            if _is_within(path, canonical_root) and path != canonical_root:
                return canonical_root
            return None
        if normalized_task_root is not None:
            if _is_within(path, normalized_task_root) and path != normalized_task_root:
                return normalized_task_root
            return None
        return path.anchor and Path(path.anchor) or None

    def deletion_path_safe(row: Mapping[str, Any], path: Path) -> bool:
        boundary = deletion_boundary(row, path)
        if boundary is None or _has_reparse_component(path, boundary):
            return False
        if storage is not None and any(_is_within(path, root) for root in protected_roots(storage)):
            return False
        return True
    files = [
        row for row in rows if str(row.get("object_type", "FILE")).upper() == "FILE"
    ]
    directories = [
        row for row in rows
        if str(row.get("object_type", "FILE")).upper() == "DIRECTORY"
    ]
    for row in files:
        if row.get("retention_class") not in DISPOSABLE_CLASSES:
            continue
        path = _absolute_lexical(Path(str(row["path"])))
        try:
            if not deletion_path_safe(row, path):
                deferred.append({"path": str(path), "reason": "CLEANUP_PATH_SAFETY_DRIFT"})
                continue
            if not path.exists():
                continue
            expected_size = int(row.get("size_bytes", -1))
            expected_hash = str(row.get("sha256", "")).lower()
            if path.stat().st_size != expected_size or _sha256_file(path) != expected_hash:
                deferred.append({"path": str(path), "reason": "MANIFEST_DRIFT"})
                continue
            path.unlink()
            if path.exists():
                raise OSError("PATH_STILL_EXISTS")
            deleted.append(str(path))
            reclaimed += expected_size
        except OSError as exc:
            deferred.append({"path": str(path), "reason": f"{type(exc).__name__}:{exc}"})
    for row in sorted(
        directories, key=lambda value: len(Path(str(value["path"])).parts), reverse=True,
    ):
        if row.get("retention_class") not in DISPOSABLE_CLASSES:
            continue
        path = _absolute_lexical(Path(str(row["path"])))
        try:
            if not deletion_path_safe(row, path):
                deferred.append({"path": str(path), "reason": "CLEANUP_PATH_SAFETY_DRIFT"})
                continue
            if path.exists():
                path.rmdir()
            if not path.exists():
                deleted.append(str(path))
        except OSError as exc:
            deferred.append({"path": str(path), "reason": f"{type(exc).__name__}:{exc}"})
    return {
        "status": "HOST_CLEANUP_DEFERRED" if deferred else "PASS",
        "deleted_paths": deleted,
        "reclaimed_bytes": reclaimed,
        "deferred": deferred,
    }


def cache_retention_class(
    *, provenance: str, producer_declared: bool, site_packages: bool = False,
) -> str:
    if site_packages:
        return "PERSISTENT_SOURCE"
    normalized = provenance.upper()
    if normalized in {"PROVIDER", "RAW", "ACQUISITION", "SOURCE_DATABASE", "MANUAL_SOURCE"}:
        return "PERSISTENT_SOURCE"
    if normalized == "TASK_SCRATCH":
        return "TASK_SCRATCH"
    if normalized == "DERIVED" and producer_declared:
        return "ACTIVE_DERIVED"
    raise LifecycleError("CACHE_RETENTION_CLASS_REQUIRED_BEFORE_PERSISTENCE")


def canonical_snapshot_policy(
    *, current: bool = False, promoted: bool = False,
    frozen_required: bool = False, forward_required: bool = False,
    rebuildable: bool = False,
) -> dict[str, str]:
    if current or promoted or frozen_required or forward_required:
        return {"metadata": "KEEP", "payload": "KEEP_KEY_EVIDENCE"}
    if rebuildable:
        return {"metadata": "KEEP", "payload": "DERIVED_DISPOSABLE"}
    return {"metadata": "KEEP", "payload": "REVIEW"}


def artifact_retention(
    *, provenance: str, key_evidence_reason: str = "",
    forward_decision: bool = False,
) -> str:
    normalized = provenance.upper()
    if normalized not in PROVENANCE_CLASSES:
        raise LifecycleError(f"UNKNOWN_ARTIFACT_PROVENANCE:{provenance}")
    if normalized in {
        "RAW", "PROVIDER", "PROVIDER_RAW", "ACQUISITION", "SOURCE",
        "SOURCE_DATABASE", "EXTERNAL", "MANUAL_SOURCE",
    }:
        return "KEEP_DATA"
    if normalized in {"ALGORITHM", "CODE", "CONFIG", "ALGORITHM_REFERENCE"}:
        return "KEEP_ALGORITHM_REFERENCE"
    if normalized == "RESEARCH_KNOWLEDGE":
        return "KEEP_RESEARCH_KNOWLEDGE"
    if normalized == "ACTIVE_OPERATIONAL":
        return "KEEP_ACTIVE_OPERATIONAL"
    if forward_decision or key_evidence_reason.strip():
        return "KEEP_KEY_EVIDENCE"
    if normalized in {"TASK_SCRATCH", "SCRATCH"}:
        return "SCRATCH_DISPOSABLE"
    return "DERIVED_DISPOSABLE"


def worktree_retirement_decision(
    *, completed: bool, clean: bool, head_preserved: bool, active: bool,
) -> str:
    if active:
        return "KEEP_ACTIVE"
    if not clean or not head_preserved:
        return "REVIEW"
    return "RETIRE" if completed else "KEEP_ACTIVE"


def _git(arguments: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if not executable:
        raise LifecycleError("GIT_UNAVAILABLE")
    return subprocess.run(
        [executable, *arguments], cwd=str(cwd), text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False, timeout=60,
    )


def retire_completed_worktree(
    repo: Path, worktree: Path, *, task_completed: bool, active: bool,
) -> dict[str, Any]:
    """Retire one exact registered worktree without force or direct deletion."""
    worktree = worktree.resolve(strict=False)
    listing = _git(["worktree", "list", "--porcelain"], repo)
    worktree_key = str(worktree).replace("\\", "/").rstrip("/").casefold()
    registered_block = next((
        block for block in listing.stdout.split("\n\n")
        if any(
            line.startswith("worktree ")
            and line.removeprefix("worktree ").replace("\\", "/").rstrip("/").casefold()
            == worktree_key
            for line in block.splitlines()
        )
    ), "")
    registered = bool(registered_block)
    if listing.returncode or not registered:
        return {"status": "WORKTREE_RETIREMENT_DEFERRED", "reason": "NOT_REGISTERED"}
    status = _git(["status", "--porcelain=v1"], worktree)
    head = _git(["rev-parse", "HEAD"], worktree)
    integration_head = _git(["rev-parse", "HEAD"], repo)
    branch = _git(["symbolic-ref", "-q", "HEAD"], worktree)
    git_dir = _git(["rev-parse", "--git-dir"], worktree)
    git_dir_path = Path(git_dir.stdout.strip()) if git_dir.returncode == 0 else None
    if git_dir_path is not None and not git_dir_path.is_absolute():
        git_dir_path = (worktree / git_dir_path).resolve(strict=False)
    administrative_lock = False
    if git_dir_path is not None and git_dir_path.exists():
        try:
            administrative_lock = any(
                child.is_file() and child.name.casefold().endswith(".lock")
                for child in git_dir_path.iterdir()
            )
        except OSError:
            administrative_lock = True
    locked = bool(
        (
            git_dir_path is not None
            and ((git_dir_path / "index.lock").exists() or (git_dir_path / "locked").exists())
        )
        or administrative_lock
        or any(line == "locked" or line.startswith("locked ") for line in registered_block.splitlines())
    )
    branch_ref = branch.stdout.strip()
    preserved = bool(
        head.returncode == 0
        and branch.returncode == 0
        and branch_ref
        and _git(["show-ref", "--verify", "--quiet", branch_ref], repo).returncode == 0
        and _git(["rev-parse", branch_ref], repo).stdout.strip() == head.stdout.strip()
        and integration_head.returncode == 0
        and _git(
            ["merge-base", "--is-ancestor", head.stdout.strip(), integration_head.stdout.strip()],
            repo,
        ).returncode == 0
    )
    decision = worktree_retirement_decision(
        completed=task_completed, clean=status.returncode == 0 and not status.stdout,
        head_preserved=preserved, active=active or locked,
    )
    if decision != "RETIRE":
        return {"status": "WORKTREE_RETIREMENT_DEFERRED", "reason": decision}
    removal = _git(["worktree", "remove", str(worktree)], repo)
    if removal.returncode:
        return {
            "status": "WORKTREE_RETIREMENT_DEFERRED",
            "reason": f"GIT_REMOVE_EXIT_{removal.returncode}",
            "stderr": removal.stderr[-2000:],
        }
    prune = _git(["worktree", "prune"], repo)
    return {
        "status": "RETIRED",
        "reason": "" if prune.returncode == 0 else f"GIT_PRUNE_DEFERRED_EXIT_{prune.returncode}",
        "prune_status": "PASS" if prune.returncode == 0 else "DEFERRED",
    }
