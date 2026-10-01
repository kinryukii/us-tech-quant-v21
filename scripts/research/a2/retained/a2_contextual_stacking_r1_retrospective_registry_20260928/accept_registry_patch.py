"""Bind the completed independent review to the exact local draft; no registry writes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"D:\us-tech-quant")
from scripts.maintenance import research_inventory as inventory


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    registry, root = inventory.load_registry(Path(r"D:\us-tech-quant"))
    draft_path = HERE / "REGISTRY_PATCH_DRAFT.json"
    review_path = HERE / "REGISTRY_INDEPENDENT_REVIEW.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["status"] == "PASS" and review["independent"] is True
    assert review["patch_file_sha256"] == sha(draft_path)
    assert review["operations_sha256"] == registry.sha256_value(draft["operations"])
    assert registry.current_state(root)["head_sha256"] == draft["expected_base_head_sha256"]
    draft["independent_review"] = {
        "status": "PASS", "independent": True, "reviewer": review["reviewer"],
        "review_ref": str(review_path), "review_sha256": sha(review_path),
        "operations_sha256": draft["operations_sha256"],
    }
    registry._reject_outcome_fields(draft)
    registry._reject_similarity_controls(draft)
    registry._patch_integrity(draft, audited_bootstrap=False)
    registry._review_gate(draft)
    (HERE / "REGISTRY_PATCH_REVIEWED.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "reviewed_patch_file_sha256": sha(HERE / "REGISTRY_PATCH_REVIEWED.json"), "operations_sha256": draft["operations_sha256"], "registry_written": False}))


if __name__ == "__main__":
    main()
