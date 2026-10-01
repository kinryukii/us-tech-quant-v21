"""One task adapter over the existing registry and inventory APIs.

prepare/stage write only this C: handoff directory. apply is the sole mode
that writes the exact, user-authorized authoritative and derived D: paths.
This file creates no identities, governance rules, or training/replay engine.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
REPO = Path("D:/us-tech-quant")
AUTHORITY = Path("D:/us-tech-quant-results/US_TECH_QUANT_RESEARCH_REGISTRY")
CSV_PATH = Path("D:/us-tech-quant-results/A2_RESEARCH_REGISTRY_CURRENT/research_branch_registry_current.csv")
MANIFEST_PATH = CSV_PATH.with_name("hash_manifest.json")
MARKDOWN_PATH = REPO / "docs/research/README.md"
REGISTRY_CODE = REPO / "scripts/maintenance/research_registry.py"
INVENTORY_CODE = REPO / "scripts/maintenance/research_inventory.py"
IDS = (
    "RAW_A2_HGB_BASELINE", "RAW_A2_BROAD_OOF_PREDICTIONS",
    "A2_COST_NAV_REPLAY_ENGINE", "A2_TEMPORAL_PIT_FEATURE_CONTRACT",
    "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE",
)
DOCS = {
    "task_research_handoff": "TASK_RESEARCH_REPORT.md",
    "task_experiment_index": "EXPERIMENT_INDEX.json",
    "task_reuse_components": "REUSE_COMPONENTS.json",
    "task_repeat_guidance": "REPEAT_GUARD.json",
    "task_training_lessons": "TRAINING_LESSONS_NOTES.md",
    "task_development_handoff": "DEVELOPMENT_HANDOFF_NOTES.md",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def modules():
    return load("task_registry_api", REGISTRY_CODE), load("task_inventory_api", INVENTORY_CODE)


def files_below(directory):
    return {p.relative_to(directory).as_posix(): sha(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def document_pins():
    return {str(HERE / name): sha(HERE / name) for name in DOCS.values()}


def capture():
    registry, _ = modules()
    discovery = read(HERE / "REGISTRY_DISCOVERY.json")
    head = registry.current_state(AUTHORITY)["head_sha256"]
    validation = registry.validate_registry(AUTHORITY, validate_all=True)
    chain = registry.validate_event_chain(AUTHORITY)
    stable_head = registry.current_state(AUTHORITY)["head_sha256"]
    output = {
        "status": "PASS" if validation["status"] == chain["status"] == "PASS" and head == stable_head else "FAIL",
        "authority_root": str(AUTHORITY), "head_sha256": head,
        "first_discovery_head_sha256": discovery["authoritative_head_sha256"],
        "validation": validation, "event_chain": chain,
        "first_discovery_to_current_diff": registry.diff_snapshots(
            AUTHORITY, discovery["authoritative_head_sha256"], head),
        "base_event_count": chain["event_count"], "authority_mutated": False,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    write(HERE / "REGISTRY_CURRENT_BASE_RECEIPT.json", output)
    return {"status": output["status"], "head_sha256": head, "base_event_count": chain["event_count"],
            "errors": validation["errors"]}


def prepare():
    registry, _ = modules()
    base_receipt = read(HERE / "REGISTRY_CURRENT_BASE_RECEIPT.json")
    require(base_receipt["status"] == "PASS", "LATEST_BASE_VALIDATION_REQUIRED")
    validation = registry.validate_registry(AUTHORITY, validate_all=False)
    write(HERE / "PREPARE_AUTHORITY_VALIDATION.json", validation)
    require(validation["status"] == "PASS", "AUTHORITY_VALIDATION_FAILED")
    state = registry.current_state(AUTHORITY)
    head = state["head_sha256"]
    require(head == base_receipt["head_sha256"], "HEAD_CHANGED_REPREPARE_AND_REVIEW_REQUIRED")
    report_review = read(HERE / "HANDOFF_REPORT_REVIEW.json")
    require(report_review.get("status", "").startswith("PASS"), "REPORT_REVIEW_REQUIRED")
    require(report_review["report_sha256"] == sha(HERE / "TASK_RESEARCH_REPORT.md"), "REPORT_REVIEW_SHA_MISMATCH")
    operations = []
    for identity in IDS:
        row = registry.query_registry(AUTHORITY, entity_id=identity)["entities"][0]
        require(row["status"] not in registry.TERMINAL_STATUSES, "TERMINAL_ENTITY_NOT_UPDATABLE")
        metadata = copy.deepcopy(row["metadata"])
        refs = copy.deepcopy(metadata.get("authoritative_artifact_refs", []))
        require(isinstance(refs, list), "EXISTING_REFERENCE_LIST_TYPE_REQUIRED")
        for key, name in DOCS.items():
            path = HERE / name
            require(key + "_ref" not in metadata and key + "_sha256" not in metadata,
                    "TASK_REFERENCE_ALREADY_PRESENT")
            metadata[key + "_ref"] = path.as_posix()
            metadata[key + "_sha256"] = sha(path)
            if path.as_posix() not in refs:
                refs.append(path.as_posix())
        metadata["authoritative_artifact_refs"] = refs
        # Neutral navigation terms make the saved attempts discoverable through
        # the existing inventory query; these are not aliases or new identities.
        require("task_handoff_topics" not in metadata, "TASK_TOPICS_ALREADY_PRESENT")
        metadata["task_handoff_topics"] = [
            "A2 多模型协同 集成学习 买点 卖点 现金 权重 折外 防泄漏",
            "fixed fusion 固定融合", "learned fixed weights 学习固定权重",
            "stacking 堆叠集成", "conditional gate mixture experts 条件门控 混合专家",
            "residual correction 分层修正", "target portfolio decision blend 目标仓位 决策级融合",
            "fixed_pred", "learned_fixed", "stack_ridge", "stack_mlp", "conditional_gate",
            "ridge_then_hgb", "hgb_then_ridge", "decision_blend",
        ]
        if not metadata.get("research_knowledge_ref"):
            metadata["research_knowledge_ref"] = (HERE / "TASK_RESEARCH_REPORT.md").as_posix()
            metadata["research_knowledge_sha256"] = sha(HERE / "TASK_RESEARCH_REPORT.md")
        operations.append({"op": "update_entity", "entity": {"entity_id": identity, "metadata": metadata}})
    draft = {
        "schema_version": 1, "patch_purpose": "STANDARD",
        "expected_base_head_sha256": head, "author": "/root",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "validation": {"status": "PENDING", "scope": "metadata references only"},
        "independent_review": {"status": "PENDING", "independent": True,
                               "reviewer": "/root/qualification_controls"},
        "operations": operations, "operation_count": len(operations),
        "operations_sha256": registry.sha256_value(operations),
    }
    # Outcome firewall is reused without weakening or encoding around it.
    registry._reject_outcome_fields(draft)
    before = HERE / "registry_before"
    require(not before.exists(), "BEFORE_COPY_ALREADY_EXISTS")
    before_hashes = files_below(AUTHORITY)
    shutil.copytree(AUTHORITY, before)
    require(files_below(before) == before_hashes, "REGISTRY_BEFORE_COPY_MISMATCH")
    require(registry.current_state(AUTHORITY)["head_sha256"] == head, "HEAD_CHANGED_DURING_PREPARE")
    backup_dir = HERE / "before_derived"
    backup_dir.mkdir(exist_ok=False)
    for source, name in ((MARKDOWN_PATH, "README.md"), (MANIFEST_PATH, "hash_manifest.json")):
        shutil.copyfile(source, backup_dir / name)
    write(HERE / "REGISTRY_PATCH_DRAFT.json", draft)
    receipt = {
        "status": "PASS_PREPARED_NOT_APPLIED", "authority_root": str(AUTHORITY),
        "base_head_sha256": head, "updated_entity_ids": list(IDS),
        "base_event_count": base_receipt["base_event_count"],
        "document_sha256": document_pins(), "code_sha256": {
            str(REGISTRY_CODE): sha(REGISTRY_CODE), str(INVENTORY_CODE): sha(INVENTORY_CODE),
            str(HERE / "update_task_registry.py"): sha(HERE / "update_task_registry.py")},
        "registry_before_file_sha256": before_hashes,
        "derived_before_sha256": {str(p): sha(p) for p in (CSV_PATH, MARKDOWN_PATH, MANIFEST_PATH)},
        "draft_file_sha256": sha(HERE / "REGISTRY_PATCH_DRAFT.json"),
        "operations_sha256": draft["operations_sha256"], "authority_mutated": False,
    }
    write(HERE / "REGISTRY_PREPARE_RECEIPT.json", receipt)
    return {"status": receipt["status"], "operation_count": len(operations), "base_head_sha256": head}


def pinned_inputs():
    receipt = read(HERE / "REGISTRY_PREPARE_RECEIPT.json")
    for path, expected in {**receipt["document_sha256"], **receipt["code_sha256"]}.items():
        require(sha(path) == expected, "PIN_CHANGED:" + path)
    require(files_below(HERE / "registry_before") == receipt["registry_before_file_sha256"],
            "BEFORE_REGISTRY_CHANGED")
    return receipt


def validate_change(registry, root, before, after, patch):
    validation = registry.validate_registry(root, validate_all=True)
    chain = registry.validate_event_chain(root)
    require(validation["status"] == chain["status"] == "PASS", "REGISTRY_VALIDATION_FAILED")
    diff = registry.diff_snapshots(root, before, after)
    require(set(diff["entities_changed"]) == set(IDS), "UNEXPECTED_CHANGED_ENTITIES")
    for key in ("entities_added", "entities_removed", "aliases_added", "aliases_removed", "aliases_remapped"):
        require(not diff[key], "UNEXPECTED_IDENTITY_CHANGE:" + key)
    old_rows = {r["entity_id"]: r for r in registry.query_registry(root, snapshot=before)["entities"]}
    new_rows = {r["entity_id"]: r for r in registry.query_registry(root, snapshot=after)["entities"]}
    patch_metadata = {op["entity"]["entity_id"]: op["entity"]["metadata"] for op in patch["operations"]}
    for identity, old in old_rows.items():
        new = new_rows[identity]
        if identity not in IDS:
            require(new == old, "UNTOUCHED_ENTITY_CHANGED:" + identity)
            continue
        require({k: v for k, v in new.items() if k not in {"metadata", "row_hash"}}
                == {k: v for k, v in old.items() if k not in {"metadata", "row_hash"}},
                "NON_METADATA_CHANGE:" + identity)
        require(new["metadata"] == patch_metadata[identity], "PATCH_METADATA_MISMATCH:" + identity)
        for key, value in old["metadata"].items():
            if key == "authoritative_artifact_refs":
                require(all(ref in new["metadata"][key] for ref in value), "OLD_REFERENCE_LOST")
            elif key in {"research_knowledge_ref", "research_knowledge_sha256"} and not value:
                continue
            else:
                require(new["metadata"].get(key) == value, "OLD_METADATA_LOST:" + identity + ":" + key)
    baseline_files = read(HERE / "REGISTRY_PREPARE_RECEIPT.json")["registry_before_file_sha256"]
    for relative, expected in baseline_files.items():
        if relative.startswith("snapshots/") or relative == "retired_artifacts.json":
            require(sha(root / relative) == expected, "HISTORICAL_BYTES_CHANGED:" + relative)
    require((root / "events.jsonl").read_bytes().startswith((HERE / "registry_before/events.jsonl").read_bytes()),
            "HISTORICAL_EVENTS_CHANGED")
    require(len(old_rows) == len(new_rows) == 60, "ENTITY_COUNT_CHANGED")
    require(chain["event_count"] == read(HERE / "REGISTRY_PREPARE_RECEIPT.json")["base_event_count"] + 1,
            "UNEXPECTED_EVENT_COUNT")
    return {"status": "PASS", "registry_validation": validation, "event_chain": chain,
            "diff": diff, "entity_count": len(new_rows), "identity_status_temporal_contracts_preserved": True,
            "terminal_entities_unchanged": True, "old_metadata_and_history_preserved": True}


def refresh_view(inventory, registry, root, stage):
    if stage:
        inventory.load_registry = lambda repo_root: (registry, root)
        directory = HERE / "proposed_derived"
        csv_output = directory / CSV_PATH.name
        markdown_output = directory / "RESEARCH_INVENTORY.md"
        manifest_output = directory / "hash_manifest.json"
        backup = None
    else:
        csv_output, markdown_output, manifest_output = CSV_PATH, MARKDOWN_PATH, MANIFEST_PATH
        backup = HERE / "before_derived" / CSV_PATH.name
    args = argparse.Namespace(repo_root=REPO, legacy_table=CSV_PATH, output=csv_output,
                              markdown_output=markdown_output, manifest_output=manifest_output,
                              backup_output=backup, path_map=None)
    result = inventory.refresh(args)
    old_reader = csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8-sig") if stage
                                           else backup.read_text(encoding="utf-8-sig")))
    old_fields, old_rows = old_reader.fieldnames, list(old_reader)
    new_rows = list(csv.DictReader(io.StringIO(csv_output.read_text(encoding="utf-8-sig"))))
    old_map = {r["canonical_branch_id"]: r for r in old_rows}
    new_map = {r["canonical_branch_id"]: r for r in new_rows}
    require(len(old_rows) == len(new_rows) == 60 and set(old_map) == set(new_map), "DERIVED_ROWS_CHANGED")
    preserve_fields = [field for field in old_fields if field not in inventory.DERIVED_FIELDS]
    require(all(old_map[key][field] == new_map[key][field] for key in old_map for field in preserve_fields),
            "LEGACY_CELL_CHANGED")
    for identity in IDS:
        row = next(r for r in new_rows if r["registry_entity_id"] == identity)
        require((HERE / "TASK_RESEARCH_REPORT.md").as_posix() in row["registry_source_refs"],
                "HANDOFF_NOT_DISCOVERABLE:" + identity)
    head = registry.current_state(root)["head_sha256"]
    require(all(row["registry_head_sha256"] == head for row in new_rows), "DERIVED_HEAD_MISMATCH")
    manifest = read(manifest_output)
    require(manifest["registry_head_sha256"] == head, "DERIVED_MANIFEST_HEAD_MISMATCH")
    require(manifest["artifacts"][csv_output.name]["sha256"] == sha(csv_output), "DERIVED_CSV_SHA_MISMATCH")
    return {**result, "legacy_non_derived_cells_preserved": True, "task_refs_discoverable_in_five_entities": True,
            "output_sha256": {str(p): sha(p) for p in (csv_output, markdown_output, manifest_output)}}


def stage():
    receipt = pinned_inputs()
    registry, inventory = modules()
    patch = read(HERE / "REGISTRY_PATCH.json")
    review = read(HERE / "REGISTRY_PATCH_REVIEW.json")
    require(review.get("status", "").startswith("PASS"), "PATCH_REVIEW_REQUIRED")
    require(patch["operations_sha256"] == receipt["operations_sha256"], "REVIEWED_OPERATIONS_CHANGED")
    require(patch["independent_review"]["status"] == "PASS", "INDEPENDENT_REVIEW_REQUIRED")
    stage_root = HERE / "staging_registry"
    require(not stage_root.exists(), "STAGE_ALREADY_EXISTS")
    shutil.copytree(HERE / "registry_before", stage_root)
    result = registry.apply_patch(stage_root, patch)
    head = registry.current_state(stage_root)["head_sha256"]
    checks = validate_change(registry, stage_root, receipt["base_head_sha256"], head, patch)
    derived = refresh_view(inventory, registry, stage_root, True)
    output = {"status": "PASS_STAGE_ONLY_NOT_AUTHORITY", "stage_root": str(stage_root),
              "base_head_sha256": receipt["base_head_sha256"], "new_head_sha256": head,
              "reviewed_patch_file_sha256": sha(HERE / "REGISTRY_PATCH.json"),
              "patch_canonical_sha256": registry.sha256_value(patch), "apply_result": result,
              "checks": checks, "derived_view": derived, "authority_mutated": False}
    write(HERE / "STAGING_REGISTRY_RECEIPT.json", output)
    return {"status": output["status"], "new_head_sha256": head, "derived_rows": derived["output_row_count"]}


def apply():
    receipt = pinned_inputs()
    registry, inventory = modules()
    staged = read(HERE / "STAGING_REGISTRY_RECEIPT.json")
    require(staged["status"] == "PASS_STAGE_ONLY_NOT_AUTHORITY", "STAGE_PASS_REQUIRED")
    require(sha(HERE / "REGISTRY_PATCH.json") == staged["reviewed_patch_file_sha256"], "REVIEWED_PATCH_CHANGED")
    require(not (HERE / "REGISTRY_UPDATE_RECEIPT.json").exists(), "UPDATE_RECEIPT_ALREADY_EXISTS")
    require(registry.current_state(AUTHORITY)["head_sha256"] == receipt["base_head_sha256"],
            "HEAD_CHANGED_REPREPARE_AND_REVIEW_REQUIRED")
    for path, expected in receipt["derived_before_sha256"].items():
        require(sha(path) == expected, "DERIVED_INPUT_CHANGED:" + path)
    patch = read(HERE / "REGISTRY_PATCH.json")
    result = registry.apply_patch(AUTHORITY, patch)
    write(HERE / "AUTHORITY_APPLY_RESULT.json", result)
    head = registry.current_state(AUTHORITY)["head_sha256"]
    require(head == staged["new_head_sha256"], "AUTHORITY_HEAD_DIFFERS_FROM_REVIEWED_STAGE")
    checks = validate_change(registry, AUTHORITY, receipt["base_head_sha256"], head, patch)
    try:
        derived = refresh_view(inventory, registry, AUTHORITY, False)
    except Exception as exc:
        write(HERE / "REGISTRY_UPDATE_RECEIPT.json", {
            "status": "AUTHORITY_APPLIED_DERIVED_REFRESH_INCOMPLETE", "authority_root": str(AUTHORITY),
            "base_head_sha256": receipt["base_head_sha256"], "new_head_sha256": head,
            "checks": checks, "error": str(exc), "apply_result": result})
        raise
    require(sha(CSV_PATH) == sha(HERE / "proposed_derived" / CSV_PATH.name), "STAGE_AND_AUTHORITY_CSV_DIFFER")
    require(sha(MARKDOWN_PATH) == sha(HERE / "proposed_derived/RESEARCH_INVENTORY.md"), "STAGE_AND_AUTHORITY_MARKDOWN_DIFFER")
    output = {
        "status": "PASS_AUTHORITY_UPDATED_AND_DERIVED_VIEWS_SYNCED", "completed_utc": datetime.now(timezone.utc).isoformat(),
        "authority_root": str(AUTHORITY), "base_head_sha256": receipt["base_head_sha256"], "new_head_sha256": head,
        "updated_entity_ids": list(IDS), "new_entity_count": 0, "new_alias_count": 0,
        "reviewed_patch_file_sha256": sha(HERE / "REGISTRY_PATCH.json"),
        "patch_canonical_sha256": registry.sha256_value(patch), "document_sha256": receipt["document_sha256"],
        "independent_patch_review_ref": str(HERE / "REGISTRY_PATCH_REVIEW.json"),
        "independent_patch_review_sha256": sha(HERE / "REGISTRY_PATCH_REVIEW.json"),
        "checks": checks, "derived_view": derived, "apply_result": result,
        "backups": {"authority_before": str(HERE / "registry_before"), "derived_before": str(HERE / "before_derived")},
        "fit_calls": 0, "prediction_calls": 0, "replay_calls": 0, "downloads": 0,
        "limitations": ["metadata and evidence navigation only; no research reopening or qualification promotion",
                        "2026 remains observed and economically uncertified; frozen study files untouched"],
    }
    write(HERE / "REGISTRY_UPDATE_RECEIPT.json", output)
    return {"status": output["status"], "new_head_sha256": head, "entity_count": checks["entity_count"],
            "event_count": checks["event_chain"]["event_count"], "derived_rows": derived["output_row_count"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "prepare", "stage", "apply"))
    arguments = parser.parse_args()
    print(json.dumps({"capture": capture, "prepare": prepare, "stage": stage, "apply": apply}[arguments.mode](), ensure_ascii=False))
