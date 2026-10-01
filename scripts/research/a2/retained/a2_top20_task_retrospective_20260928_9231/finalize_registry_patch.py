"""Attach an actual independent review to the prepared canonical patch."""
from __future__ import annotations

import json

from build_retrospective import OUT, sha
from stage_registry_patch import ENTITY_ID, REGISTRY_ROOT, registry_module


def main():
    draft_path = OUT / "REGISTRY_PATCH_DRAFT.json"
    review_path = OUT / "REGISTRY_REVIEW.json"
    review = json.loads(review_path.read_text(encoding="utf-8-sig"))
    assert review["status"] == "PASS" and review["independent"] is True
    assert review["reviewer"] == "/root/audit_data"
    assert review["patch_sha256"] == sha(draft_path), "Independent review must pin this exact patch."
    patch = json.loads(draft_path.read_text(encoding="utf-8-sig"))
    registry = registry_module()
    current = registry.current_state(REGISTRY_ROOT)
    assert current["head_sha256"] == patch["expected_base_head_sha256"], "Head changed: reread, merge and re-review."
    added = patch["operations"][0]["entity"]["metadata"]["related_task_knowledge_refs"][-1]
    for prefix in ["report", "artifact_index", "study_log"]:
        assert sha(__import__("pathlib").Path(added[prefix + "_ref"])) == added[prefix + "_sha256"]
    patch["independent_review"] = {"status": "PASS", "independent": True, "reviewer": review["reviewer"], "source_ref": str(review_path), "source_sha256": sha(review_path)}
    patch["validation"]["independent_document_check_ref"] = str(OUT / "CONTENT_REVIEW.json")
    patch["validation"]["independent_document_check_sha256"] = sha(OUT / "CONTENT_REVIEW.json")
    registry._reject_outcome_fields(patch)
    registry._reject_similarity_controls(patch)
    registry._patch_integrity(patch, audited_bootstrap=False)
    registry._review_gate(patch)
    destination = OUT / "REGISTRY_PATCH_REVIEWED.json"
    destination.write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_READY_TO_APPLY_EXISTING_CANONICAL_TOOL", "entity_id": ENTITY_ID, "head_sha256": current["head_sha256"], "patch_ref": str(destination), "patch_sha256": sha(destination), "authority_mutations": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
