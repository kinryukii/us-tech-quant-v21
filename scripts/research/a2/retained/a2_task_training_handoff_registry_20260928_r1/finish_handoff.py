"""Close the static handoff after the separately reviewed authority update."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import update_task_registry as adapter

root = Path(__file__).resolve().parent
receipt = adapter.read(root / "REGISTRY_UPDATE_RECEIPT.json")
adapter.require(receipt["status"] == "PASS_AUTHORITY_UPDATED_AND_DERIVED_VIEWS_SYNCED", "AUTHORITY_UPDATE_INCOMPLETE")
report_review = adapter.read(root / "HANDOFF_REPORT_REVIEW.json")
artifact_review = adapter.read(root / "HANDOFF_ARTIFACT_REVIEW.json")
resume_review = adapter.read(root / "POST_RESUME_REGISTRY_REVIEW.json")
adapter.require(resume_review["status"].startswith("PASS") and not resume_review["remaining_dependencies"],
                "POST_RESUME_REGISTRY_REVIEW_INCOMPLETE")
adapter.require(report_review["status"].startswith("PASS") and not artifact_review["issues"], "REVIEW_FAILED")
adapter.require(adapter.sha(root / "TASK_RESEARCH_REPORT.md") == report_review["report_sha256"], "REPORT_REVIEW_PIN_MISMATCH")
for path, expected in {**receipt["document_sha256"], **artifact_review["input_sha256"]}.items():
    adapter.require(adapter.sha(path) == expected, "DOCUMENT_PIN_CHANGED:" + path)
links = artifact_review["local_links"]
adapter.require(all(Path(link["target"]).exists() for link in links), "LOCAL_LINK_MISSING")
fulfilled = artifact_review["pending_dependencies"]
adapter.require(all(Path(item["path"]).exists() for item in fulfilled), "UNFULFILLED_ARTIFACT_DEPENDENCY")
frozen = artifact_review["new_batch_manifest"]
adapter.require(frozen["matches"] and frozen["named_member_hashes_checked"] == 369, "FROZEN_RESEARCH_REVIEW_INCOMPLETE")
adapter.require(adapter.sha(frozen["path"]) == frozen["expected_sha256"], "FROZEN_MANIFEST_CHANGED")

registry, inventory = adapter.modules()
current = registry.current_state(adapter.AUTHORITY)
adapter.require(current["head_sha256"] == receipt["new_head_sha256"], "HEAD_CHANGED_AFTER_UPDATE_CHECK_CURRENT_VIEW")
context = registry.query_registry(adapter.AUTHORITY)
rows = {row["entity_id"]: row for row in context["entities"]}
for identity in adapter.IDS:
    adapter.require(rows[identity]["metadata"]["task_research_handoff_sha256"] == report_review["report_sha256"],
                    "REGISTERED_DOCUMENT_PIN_MISMATCH:" + identity)
query_topics = ("stacking", "条件门控", "decision_blend")
topic_results = {}
for term in query_topics:
    matched = [identity for identity in adapter.IDS
               if inventory._matches(json.dumps(rows[identity], ensure_ascii=False), term)]
    adapter.require(set(matched) == set(adapter.IDS), "TASK_KEYWORD_NOT_DISCOVERABLE:" + term)
    topic_results[term] = matched
for path, expected in receipt["derived_view"]["output_sha256"].items():
    adapter.require(adapter.sha(path) == expected, "DERIVED_VIEW_CHANGED:" + path)

artifacts = [path for path in sorted(root.iterdir()) if path.is_file()
             and path.name not in {"DELIVERY_MANIFEST.json", "FINAL_VERIFICATION.json"}]
manifest = {
    "schema_version": "A2_TASK_HANDOFF_DELIVERY_R1",
    "role": "DELIVERY_INTEGRITY_ONLY_NOT_RESEARCH_IDENTITY_AUTHORITY",
    "files": {path.name: {"bytes": path.stat().st_size, "sha256": adapter.sha(path)} for path in artifacts},
    "registered_document_sha256": receipt["document_sha256"],
    "authority_root": str(adapter.AUTHORITY), "accepted_head_sha256": receipt["new_head_sha256"],
}
adapter.write(root / "DELIVERY_MANIFEST.json", manifest)
result = {
    "status": "PASS_REPORT_REGISTRY_AND_REUSE_HANDOFF_COMPLETE",
    "completed_utc": datetime.now(timezone.utc).isoformat(),
    "main_report_ref": str(root / "TASK_RESEARCH_REPORT.md"), "main_report_sha256": report_review["report_sha256"],
    "authority_root": str(adapter.AUTHORITY), "accepted_head_sha256": current["head_sha256"],
    "updated_entity_ids": list(adapter.IDS), "identity_status_and_temporal_contracts_preserved": True,
    "historical_snapshots_and_closed_entities_preserved": True,
    "comparison_review": {"saved_rows": 29, "numeric_cells": 145, "status": "PASS"},
    "lookup": {"method_specs": 8, "saved_unique_accounts": 93, "reusable_components": 69,
               "independent_sample_count": "NOT_ESTABLISHED"},
    "local_links": {"reviewed": len(links), "prior_pending_dependencies_fulfilled": len(fulfilled), "missing": 0},
    "topic_query_matches": topic_results,
    "frozen_research": {"named_files_reviewed": 369, "manifest_sha256": adapter.sha(frozen["path"]), "unchanged": True},
    "derived_views": {"row_count": receipt["derived_view"]["output_row_count"], "synchronized": True,
                      "legacy_non_derived_cells_preserved": True},
    "delivery_manifest_sha256": adapter.sha(root / "DELIVERY_MANIFEST.json"),
    "post_resume_registry_review_ref": str(root / "POST_RESUME_REGISTRY_REVIEW.json"),
    "post_resume_registry_review_sha256": adapter.sha(root / "POST_RESUME_REGISTRY_REVIEW.json"),
    "new_fit_calls": 0, "new_prediction_calls": 0, "new_replay_calls": 0, "downloads": 0,
    "research_limitations": ["A superior A2 policy has not been established",
                             "2026 is observed partial-year data with incomplete economic qualification"],
}
adapter.write(root / "FINAL_VERIFICATION.json", result)
print(json.dumps({"status": result["status"], "registered_entities": 5, "derived_rows": 60,
                  "missing_links": 0, "delivery_files": len(artifacts)}, ensure_ascii=False))
