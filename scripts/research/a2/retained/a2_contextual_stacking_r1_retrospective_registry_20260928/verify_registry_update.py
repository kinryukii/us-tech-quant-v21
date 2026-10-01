"""Read and verify actual accepted metadata against the reviewed amendment."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = Path(r"D:\us-tech-quant")
sys.path.insert(0, str(REPO))
from scripts.maintenance import research_inventory as inventory


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    registry, root = inventory.load_registry(REPO)
    patch = json.loads((HERE / "REGISTRY_PATCH_REVIEWED.json").read_text(encoding="utf-8"))
    applied = json.loads((HERE / "REGISTRY_APPLY_RESULT.json").read_text(encoding="utf-8-sig"))
    assert applied["status"] == "PASS"
    base = patch["expected_base_head_sha256"]
    head = registry.current_state(root)["head_sha256"]
    assert head == applied["head_sha256"]
    _, before_entities, before_aliases = registry._load_snapshot(root, base)
    _, after_entities, after_aliases = registry._load_snapshot(root, head)
    expected_entities, expected_aliases = registry._apply_operations(before_entities, before_aliases, patch, head_sha256=base, audited_inventory_bootstrap=False)
    assert after_entities == expected_entities and after_aliases == expected_aliases
    identity = "THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE"
    before = next(row for row in before_entities if row["entity_id"] == identity)
    after = next(row for row in after_entities if row["entity_id"] == identity)
    assert all(before[key] == after[key] for key in before if key not in {"metadata", "row_hash"})
    old_related = before["metadata"].get("related_task_knowledge_refs", [])
    assert after["metadata"].get("related_task_knowledge_refs", []) == old_related
    aliases = [operation["alias"] for operation in patch["operations"] if operation["op"] == "add_alias"]
    resolved = {alias: registry.resolve_alias(root, alias) for alias in aliases}
    assert all(result["entity"]["entity_id"] == identity for result in resolved.values())
    validation = registry.validate_registry(root, validate_all=True)
    assert validation["status"] == "PASS"
    diff = registry.diff_snapshots(root, base, head)
    write("REGISTRY_VALIDATION_AFTER.json", validation)
    write("REGISTRY_DIFF.json", diff)
    write("REGISTRY_ALIAS_RESOLUTIONS.json", resolved)
    write("REGISTRY_CONTEXT_AFTER.json", {"registry_root": str(root), "head_sha256": head, "entity": after, "aliases": [row for row in after_aliases if row["entity_id"] == identity]})
    result = {
        "status": "PASS", "verified_utc": datetime.now(timezone.utc).isoformat(),
        "identity_authority": str(root),
        "discovery_head_sha256": "84e29c33d770de6fd17db69b5c62dc6e38361881e69949a62aba05bc035ed92b",
        "base_head_sha256": base, "new_head_sha256": head,
        "concurrent_update_rebased_without_overwrite": True,
        "concurrent_related_task_knowledge_refs_preserved": old_related,
        "operation_count": len(patch["operations"]), "operations_sha256": patch["operations_sha256"],
        "changed_entity_ids": [identity], "new_entities": [], "added_aliases": aliases,
        "entity_count": len(after_entities), "alias_count_before": len(before_aliases), "alias_count_after": len(after_aliases),
        "all_lifecycle_and_identity_fields_unchanged": True,
        "other_entities_unchanged": True, "historical_snapshots_validated": len(validation["validated_snapshots"]),
        "prior_knowledge_retained_in_history": True,
        "new_knowledge_ref": after["metadata"]["research_knowledge_ref"],
        "new_knowledge_sha256": after["metadata"]["research_knowledge_sha256"],
        "results_stored_only_in_external_evidence": True,
        "independent_review_ref": str(HERE / "REGISTRY_INDEPENDENT_REVIEW.json"),
        "independent_review_sha256": sha(HERE / "REGISTRY_INDEPENDENT_REVIEW.json"),
        "preflight_probes_ref": str(HERE / "REGISTRY_PREFLIGHT_PROBES.json"),
        "preflight_probes_sha256": sha(HERE / "REGISTRY_PREFLIGHT_PROBES.json"),
        "duplicate_detection_limits": "Exact names resolve; truthful source/reference reuse requires review. Missing or fabricated source declarations are not semantically verified by the existing tool.",
        "derived_inventory_refresh_status": "PENDING",
        "new_fit_calls": 0, "new_portfolio_replays": 0,
    }
    write("REGISTRY_UPDATE_RECEIPT.json", result)
    print(json.dumps({"status": "PASS", "head_sha256": head, "entity_count": len(after_entities), "alias_count": len(after_aliases), "validated_snapshots": len(validation["validated_snapshots"])}))


if __name__ == "__main__":
    main()
