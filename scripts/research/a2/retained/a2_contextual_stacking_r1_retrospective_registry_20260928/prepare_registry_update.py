"""Prepare a reviewed metadata amendment; never writes the registry or fits models."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
REPO = Path(r"D:\us-tech-quant")
sys.path.insert(0, str(REPO))
from scripts.maintenance import research_inventory as inventory


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    registry, root = inventory.load_registry(REPO)
    state = registry.current_state(root)
    head = state["head_sha256"]
    context = inventory.accepted_context(registry, root, head)
    identity = "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE"
    before = next(row for row in context["entities"] if row["entity_id"] == identity)
    write("REGISTRY_CONTEXT_BEFORE.json", {
        "role": "HASH_PINNED_READ_ONLY_CONTEXT_NOT_AUTHORITY",
        "registry_root": str(root), "registry_head_sha256": head,
        "entity": before,
        "aliases": [row for row in context["aliases"] if row["entity_id"] == identity],
        "canonical_registry_code_sha256": sha(REPO / "scripts/maintenance/research_registry.py"),
        "read_method": "Existing inventory.accepted_context; public query and manifest-pinned accepted aliases",
    })
    specs = [
        ("TRAINING", "a2_multimodel_joint_20260928", "RESEARCH_MODEL_INVENTORY", "MODEL_REGISTRY.json", "Frozen batch inventory; not global identity authority"),
        ("TRAINING", "a2_multimodel_joint_20260928", "TEMPORAL_AND_EXECUTION_CONTRACT", "EXPERIMENT_CONTRACT.md", "Original point-in-time source limits remain"),
        ("TRAINING", "a2_multimodel_joint_20260928", "FUSION_POSITION_CONTRACT", "ENSEMBLE_CONTRACT.md", "Final-target averaging differs from action-score stacking"),
        ("TRAINING", "a2_multimodel_joint_20260928", "COMPLETION", "COMPLETION.json", "Training completion does not certify whole-pool investment results"),
        ("TRAINING", "a2_multimodel_joint_20260928", "NUMERICAL_CONVERGENCE_REPAIR", "value_artifacts/FIT_RECEIPT.json", "Same-objective/data continuation is recorded separately from final model count"),
        ("TRAINING", "a2_multimodel_joint_20260928", "EARLY_CONVERGENCE_REPAIR", "ensemble_artifacts/early_values/FIT_RECEIPT.json", "Same-objective/data continuation is not a new economic specification"),
        ("TRAINING", "a2_multimodel_joint_20260928", "PARALLEL_SOURCE_RECOVERY", "audit/RISK_SOURCE_RESTORATION.json", "Unattributed overwrite; exact training source restored without refit"),
        ("TRAINING", "a2_multimodel_joint_20260928", "SHARED_ALLOCATION_REUSE", "values.py", "Single-step label approximation; original discrete actions and reserves"),
        ("TRAINING", "a2_multimodel_joint_20260928", "EXECUTION_ENGINE_REUSE", "engine_v2.py", "Original price-index coordinate, cost and capacity assumptions"),
        ("TRAINING", "a2_multimodel_joint_20260928", "SOURCE_QUALIFICATION_LIMITS", "audit/INPUT_AUDIT.json", "Does not prove all vendor arrival clocks or price truth"),
        ("TRAINING", "a2_multimodel_joint_20260928", "FROZEN_RESULTS", "ALL_RESULTS.csv", "Already-observed retrospective diagnostics; no selection from test year"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "RESULT_QUALIFIERS", "RESULT_LABELS.json", "Retains missing original per-strategy runtime receipt"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "STACK_REPRODUCTION", "stack_evidence/RESULT.json", "Posthoc exact reproduction; no backdated receipt"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "STAGE_HASH_MAPPING", "stack_evidence/meta_stage_hash_mapping.csv", "Validation and final cannot be interchanged"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "CASH_STAGE_DECOMPOSITION", "cash_attribution/REPORT.md", "Paired signal dates and full valuation dates differ"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "COMPARABLE_COMPLEMENTARITY", "complementarity/REPORT.md", "Local errors and disagreement do not establish tradable ensemble gain"),
        ("REVIEW", "a2_multimodel_joint_review_20260928", "COMPLETION", "COMPLETION.json", "No fits or whole portfolio replay in review"),
        ("R1", "a2_contextual_stacking_r1_20260928", "FROZEN_CONTRACT", "EXPERIMENT_CONTRACT.md", "Only conditional meta relation changes; same allocator and engine"),
        ("R1", "a2_contextual_stacking_r1_20260928", "PRE_FIT_LOCK", "PRE_FIT_LOCK.json", "Exact old inputs; no base expert refit"),
        ("R1", "a2_contextual_stacking_r1_20260928", "FEASIBLE_ACCOUNT_PANEL", "panel_artifacts/PANEL_RECEIPT.json", "Date/path weights; full rank is insufficient joint support evidence"),
        ("R1", "a2_contextual_stacking_r1_20260928", "PANEL_VALIDATION", "panel_artifacts/PANEL_VALIDATION.json", "Frozen value experts retain original state extrapolation limits"),
        ("R1", "a2_contextual_stacking_r1_20260928", "LABEL_WARNING_RECORD", "panel_artifacts/LABEL_WARNING_RECEIPT.json", "Boolean warning is not external price verification"),
        ("R1", "a2_contextual_stacking_r1_20260928", "META_IMPLEMENTATION_REUSE", "meta.py", "Coefficients are effect and calibration units, not funding percentages"),
        ("R1", "a2_contextual_stacking_r1_20260928", "MODEL_SCALER_MATURITY_BINDING", "meta_artifacts/FIT_RECEIPT.json", "Train-only stage scalers; no final backfill"),
        ("R1", "a2_contextual_stacking_r1_20260928", "LIMITED_INTERNAL_SELECTION", "meta_artifacts/INTERNAL_SELECTION.json", "Only predeclared train-year candidates"),
        ("R1", "a2_contextual_stacking_r1_20260928", "INDEPENDENT_STAGE_AUDIT", "independent_audit/META_CONTRACT_AUDIT.json", "Engineering binding audit does not certify source economics"),
        ("R1", "a2_contextual_stacking_r1_20260928", "PREDICTION_EFFECT_INTERPRETATION", "meta_artifacts/INTERPRETATION_SUPPLEMENT.md", "Absolute utility and action-minus-zero differ; joint similar-expert contribution"),
        ("R1", "a2_contextual_stacking_r1_20260928", "PAIRED_FULL_LEDGER_RESULTS", "paired_analysis/ALL_RESULTS.csv", "Main validation disposition cannot be rescued using diagnostics"),
        ("R1", "a2_contextual_stacking_r1_20260928", "CASH_AND_CONCENTRATION", "cash_diagnostic/CASH_DIAGNOSTIC_RECEIPT.json", "Cash feedback was not isolated by a single-variable intervention"),
        ("R1", "a2_contextual_stacking_r1_20260928", "SELECTED_SUPPORT", "paired_analysis/2025_SELECTED_STATE_SUPPORT.json", "Candidate-wide and selected nonzero-target denominators are distinct"),
        ("R1", "a2_contextual_stacking_r1_20260928", "COMMON_ACCOUNT_DIAGNOSTIC", "paired_analysis/SAME_ACCOUNT_DIAGNOSTIC.json", "Hypothetical targets were not an alternative executed portfolio"),
        ("R1", "a2_contextual_stacking_r1_20260928", "INDEPENDENT_LEDGER_CHECKS", "INDEPENDENT_LEDGER_CHECKS.json", "Cash/nav accounting does not validate external prices"),
        ("R1", "a2_contextual_stacking_r1_20260928", "RECOVERY_PREFIX_PROOF", "evaluation_2025/cost_10/RECOVERY_PREFIX_PROOF.json", "Preserved implementation failures; no economic parameter changes"),
        ("R1", "a2_contextual_stacking_r1_20260928", "LOCKED_DISPOSITION", "RESEARCH_DISPOSITION.json", "Early remaining-work snapshot superseded by final completion; garbled text is not repaired"),
        ("R1", "a2_contextual_stacking_r1_20260928", "FINAL_COMPLETION", "COMPLETION.json", "Complete and frozen; not adopted"),
        ("R1", "a2_contextual_stacking_r1_20260928", "FROZEN_FILE_MANIFEST", "ARTIFACT_MANIFEST.json", "Sealed directory is never extended by this documentation task"),
        ("R1", "a2_contextual_stacking_r1_20260928", "HUMAN_READABLE_EXPORTS", "delivery_tables/README.md", "Final all-cash positions are an empty table"),
    ]
    rows = []
    for phase, directory, role, relative, limits in specs:
        path = WORKSPACE / directory / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append({"phase": phase, "purpose": role, "path": str(path), "sha256": sha(path), "limitations": limits})
    write("EVIDENCE_REUSE_INDEX.json", {
        "schema_version": 1, "role": "EXTERNAL_EVIDENCE_NAVIGATION_NOT_IDENTITY_AUTHORITY",
        "identity_authority": str(root), "scope": "This thread only; frozen training, review and R1",
        "new_fits": 0, "new_portfolio_replays": 0, "entries": rows,
    })
    metadata = copy.deepcopy(before["metadata"])
    old_ref = metadata["research_knowledge_ref"]
    old_hash = metadata["research_knowledge_sha256"]
    if sha(Path(old_ref)) != old_hash:
        raise ValueError("PRIOR_KNOWLEDGE_REFERENCE_HASH_MISMATCH")
    history = list(metadata.get("research_knowledge_history", []))
    prior = {"scope": "PRIOR_SCOPED_TASK", "document_ref": old_ref, "document_sha256": old_hash}
    if prior not in history:
        history.append(prior)
    report = HERE / "REPORT.md"
    latest = {"scope": "MULTIMODEL_TO_CONTEXTUAL_STACKING_THREAD", "document_ref": str(report), "document_sha256": sha(report)}
    if latest not in history:
        history.append(latest)
    metadata.update({
        "research_knowledge_history": history,
        "research_knowledge_ref": str(report), "research_knowledge_sha256": sha(report),
        "scoped_reuse_ref": str(HERE / "EVIDENCE_REUSE_INDEX.json"),
        "scoped_reuse_sha256": sha(HERE / "EVIDENCE_REUSE_INDEX.json"),
        "scoped_trial_notes_ref": str(HERE / "TRIALS_AND_REOPEN_RULES.md"),
        "scoped_trial_notes_sha256": sha(HERE / "TRIALS_AND_REOPEN_RULES.md"),
        "scoped_knowledge_boundary": "Specific frozen attempts only; parent lifecycle and source qualification remain unchanged",
    })
    records = list(metadata.get("scoped_research_records", []))
    for key, directory, label in [
        ("A2_MULTIMODEL_JOINT_20260928", "a2_multimodel_joint_20260928", "TRAINING_AND_RESEARCH_EVALUATION_COMPLETE"),
        ("A2_MULTIMODEL_JOINT_REVIEW_20260928", "a2_multimodel_joint_review_20260928", "REVIEW_COMPLETE_WITH_EXPLICIT_EVIDENCE_LIMITS"),
        ("A2_CONTEXTUAL_STACKING_R1", "a2_contextual_stacking_r1_20260928", "FROZEN_R1_NOT_ADOPTED"),
    ]:
        path = WORKSPACE / directory / "COMPLETION.json"
        records.append({
            "experiment_key": key, "scoped_disposition": label,
            "completion_ref": str(path), "completion_sha256": sha(path),
            "report_ref": str(WORKSPACE / directory / "REPORT.md"),
            "report_sha256": sha(WORKSPACE / directory / "REPORT.md"),
            "knowledge_ref": str(report), "knowledge_sha256": sha(report),
            "scope": "Retrospective frozen research; no production adoption or parent lifecycle change",
        })
    metadata["scoped_research_records"] = records
    governance = copy.deepcopy(metadata.get("governance_metadata", {}))
    refs = [str(WORKSPACE / directory / relative) for directory, relative in [
        ("a2_multimodel_joint_20260928", "EXPERIMENT_CONTRACT.md"),
        ("a2_multimodel_joint_20260928", "ENSEMBLE_CONTRACT.md"),
        ("a2_multimodel_joint_review_20260928", "REVIEW_CONTRACT.md"),
        ("a2_contextual_stacking_r1_20260928", "EXPERIMENT_CONTRACT.md"),
        ("a2_contextual_stacking_r1_20260928", "PRE_FIT_LOCK.json"),
        ("a2_contextual_stacking_r1_20260928", "panel_artifacts/PANEL_RECEIPT.json"),
    ]]
    for ref in refs:
        if not Path(ref).is_file():
            raise FileNotFoundError(ref)
    governance["authoritative_artifact_refs"] = list(dict.fromkeys([*governance.get("authoritative_artifact_refs", []), *refs]))
    governance["information_source"] = list(dict.fromkeys([*([governance["information_source"]] if isinstance(governance.get("information_source"), str) else governance.get("information_source", [])), "EXISTING_FROZEN_MULTIMODEL_EXPERT_OUTPUTS", "FEASIBLE_HISTORICAL_ACCOUNT_STATE_OOF_PANEL"]))
    governance["feature_input_family"] = list(dict.fromkeys([*([governance["feature_input_family"]] if isinstance(governance.get("feature_input_family"), str) else governance.get("feature_input_family", [])), "EXPERT_SEMANTIC_OUTPUTS_AND_ORIGINAL_ACCOUNT_STATE"]))
    governance["scoped_identity_note"] = "Overlap navigation for frozen attempts; not certification of distinct economic information"
    metadata["governance_metadata"] = governance
    aliases = ["A2_MULTIMODEL_JOINT_20260928", "A2_MULTIMODEL_JOINT_REVIEW_20260928", "A2_CONTEXTUAL_STACKING_R1", "A2_CONTEXTUAL_STACKING_R1_20260928"]
    operations = [{"op": "update_entity", "entity": {"entity_id": identity, "metadata": metadata}}]
    operations += [{"op": "add_alias", "entity_id": identity, "alias": alias} for alias in aliases]
    patch = {
        "schema_version": registry.SCHEMA_VERSION, "patch_purpose": "STANDARD",
        "expected_base_head_sha256": head, "author": "Codex primary /root",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "validation": {"status": "PASS", "scope": "Metadata knowledge amendment and exact aliases; no identity or lifecycle transition"},
        "operations": operations, "operation_count": len(operations),
        "operations_sha256": registry.sha256_value(operations),
    }
    registry._reject_outcome_fields(patch)
    registry._reject_similarity_controls(patch)
    registry._patch_integrity(patch, audited_bootstrap=False)
    entities_after, aliases_after = registry._apply_operations(context["entities"], context["aliases"], patch, head_sha256=head, audited_inventory_bootstrap=False)
    after = next(row for row in entities_after if row["entity_id"] == identity)
    stable_fields = [key for key in before if key not in {"metadata", "row_hash"}]
    assert all(before[key] == after[key] for key in stable_fields)
    stable_metadata = [key for key in before["metadata"] if key not in {"research_knowledge_ref", "research_knowledge_sha256"}]
    assert all(before["metadata"][key] == after["metadata"][key] for key in stable_metadata)
    assert all(row == next(item for item in entities_after if item["entity_id"] == row["entity_id"]) for row in context["entities"] if row["entity_id"] != identity)
    assert after["post_2025_observation_count"] == 0
    write("REGISTRY_PATCH_DRAFT.json", patch)
    write("REGISTRY_PATCH_PREVIEW.json", {
        "status": "PASS", "role": "IN_MEMORY_PREVIEW_NO_REGISTRY_WRITES",
        "expected_base_head_sha256": head, "operations_sha256": patch["operations_sha256"],
        "entity_count_before": len(context["entities"]), "entity_count_after": len(entities_after),
        "alias_count_before": len(context["aliases"]), "alias_count_after": len(aliases_after),
        "changed_entity_ids": [identity], "added_aliases": aliases,
        "nonmetadata_entity_fields_unchanged": True,
        "prior_metadata_fields_preserved_except_latest_knowledge_pointer": True,
        "previous_knowledge_reference_retained_in_history": True,
        "other_entities_unchanged": True, "economic_results_not_embedded": True,
        "after_entity": after,
    })
    print(json.dumps({"status": "PASS", "patch": str(HERE / "REGISTRY_PATCH_DRAFT.json"), "operation_count": len(operations), "evidence_entries": len(rows), "registry_written": False}))


if __name__ == "__main__":
    main()
