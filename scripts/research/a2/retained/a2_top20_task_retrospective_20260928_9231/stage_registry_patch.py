"""Prepare a metadata-only patch using the existing registry implementation."""
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from build_retrospective import A, B, C, OUT, sha

REGISTRY_SOURCE = Path("D:/us-tech-quant/scripts/maintenance/research_registry.py")
REGISTRY_ROOT = Path("D:/us-tech-quant-results/US_TECH_QUANT_RESEARCH_REGISTRY")
ENTITY_ID = "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE"


def registry_module():
    spec = importlib.util.spec_from_file_location("existing_research_registry", REGISTRY_SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    registry = registry_module()
    result = registry.query_registry(REGISTRY_ROOT, entity_id=ENTITY_ID)
    head = result["head_sha256"]
    assert len(result["entities"]) == 1
    original = result["entities"][0]
    assert original["status"] == "OPEN"
    metadata = copy.deepcopy(original["metadata"])
    task_id = "TOP20_MULTIMODEL_COOPERATION_20260928_9231"
    refs = metadata.get("related_task_knowledge_refs", [])
    assert isinstance(refs, list)
    assert not any(ref.get("task_id") == task_id for ref in refs), "Already registered; do not add a duplicate event."
    added = {
        "task_id": task_id,
        "relationship": "RELATED_TASK_EVIDENCE_NOT_CANONICAL_IDENTITY_EQUIVALENCE",
        "source_chat_scope": "9231; only the two named task batches and the acceptance attachment",
        "report_ref": str(OUT / "RETROSPECTIVE_REPORT.md"),
        "report_sha256": sha(OUT / "RETROSPECTIVE_REPORT.md"),
        "artifact_index_ref": str(OUT / "REUSE_INDEX.json"),
        "artifact_index_sha256": sha(OUT / "REUSE_INDEX.json"),
        "study_log_ref": str(OUT / "RESEARCH_LEDGER.json"),
        "study_log_sha256": sha(OUT / "RESEARCH_LEDGER.json"),
        "native_batch_refs": [
            {"batch_id": A.name, "manifest_ref": str(A / "RUN_MANIFEST.json"), "manifest_sha256": sha(A / "RUN_MANIFEST.json")},
            {"batch_id": str(C.relative_to(A.parent)), "manifest_ref": str(C / "ACCEPTANCE_MANIFEST.json"), "manifest_sha256": sha(C / "ACCEPTANCE_MANIFEST.json")},
            {"batch_id": B.name, "manifest_ref": str(B / "COMPLETE_MANIFEST.json"), "manifest_sha256": sha(B / "COMPLETE_MANIFEST.json")},
        ],
        "method_keywords": ["TOP20", "多模型协同", "集成学习", "Ridge", "ElasticNet", "Logistic", "HGB", "Q10", "Q50", "Q90", "MLP", "REINFORCE", "LedoitWolf", "PCA", "KMeans", "IsolationForest", "ensemble_equal", "ensemble_disagreement", "ensemble_stacking", "fusion_fixed_non_equal", "fusion_learned_weights", "NNLS", "fusion_nonlinear_stacking", "fusion_conditional_gate", "fusion_hgb_then_linear", "fusion_linear_then_hgb", "fusion_target_decisions"],
        "read_boundary": "Reports and study log contain previously observed 2026 research outcomes; read only under separately applicable authorization, never for tuning or champion selection.",
        "usage_limits": [
            "Training completion, internal engineering checks, data certification and independent confirmation are separate statuses; detailed conclusions remain external.",
            "Native batches retain original identities and inherited data limitations; this task adds documentary references only.",
            "Reuse frozen experts, temporal OOF and the one account engine; do not create parallel training, allocation or registry systems.",
            "NNLS and old positive Ridge stacking are related solver variants; consult the overlap evidence before claiming new selection diversity.",
            "No automatic model, seed, penalty, blend-weight or horizon expansion based on observed outcomes.",
            "A repair that affects training must use a new explicit batch and rebuild affected dependencies; evaluation-only repair cannot rename an old model as repaired.",
            "This knowledge link neither reopens terminal research branches nor changes production or evaluation authorization.",
        ],
        "related_existing_entity_ids": ["RAW_A2_HGB_BASELINE", "RAW_A2_BROAD_OOF_PREDICTIONS", "ACTION_ML_BUY_SELL_SIZING", "PORTFOLIO_WEIGHTING_VARIANTS", "STOCK_RISK_MODEL_VARIANTS"],
    }
    metadata["related_task_knowledge_refs"] = [*refs, added]
    operations = [{"op": "update_entity", "entity": {"entity_id": ENTITY_ID, "metadata": metadata}}]
    patch = {
        "schema_version": 1,
        "patch_purpose": "STANDARD",
        "expected_base_head_sha256": head,
        "author": "Codex primary /root",
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "validation": {"status": "PASS", "scope": "Append one scoped external knowledge reference; preserve every old metadata field, all identities, lifecycle/temporal statuses, aliases and counters."},
        "operations": operations,
        "operation_count": len(operations),
        "operations_sha256": registry.sha256_value(operations),
    }
    registry._reject_outcome_fields(patch)
    registry._reject_similarity_controls(patch)
    registry._patch_integrity(patch, audited_bootstrap=False)
    _, entities, aliases = registry._load_snapshot(REGISTRY_ROOT, head)
    revised, revised_aliases = registry._apply_operations(entities, aliases, patch, head_sha256=head)
    before = {e["entity_id"]: e for e in entities}
    after = {e["entity_id"]: e for e in revised}
    assert set(before) == set(after) and aliases == revised_aliases
    changed = [key for key in before if before[key] != after[key]]
    assert changed == [ENTITY_ID]
    for key, value in original["metadata"].items():
        assert after[ENTITY_ID]["metadata"][key] == value
    assert after[ENTITY_ID]["metadata"]["related_task_knowledge_refs"][-1] == added
    for key, value in before[ENTITY_ID].items():
        if key not in {"metadata", "row_hash"}:
            assert after[ENTITY_ID][key] == value
    (OUT / "REGISTRY_PATCH_DRAFT.json").write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {
        "status": "PASS_PURE_IN_MEMORY_PATCH_VALIDATION",
        "registry_root": str(REGISTRY_ROOT),
        "registry_source": str(REGISTRY_SOURCE),
        "registry_source_sha256": sha(REGISTRY_SOURCE),
        "base_head_sha256": head,
        "entity_id": ENTITY_ID,
        "changed_entity_ids": changed,
        "entity_count_before": len(entities),
        "entity_count_after": len(revised),
        "alias_count_before": len(aliases),
        "alias_count_after": len(revised_aliases),
        "old_metadata_preserved": True,
        "logical_fields_preserved": True,
        "authority_mutations": 0,
        "independent_review": "PENDING",
    }
    (OUT / "REGISTRY_PREFLIGHT.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(preflight, ensure_ascii=False))


if __name__ == "__main__":
    main()
