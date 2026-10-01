"""Read-only verification of the handoff and existing canonical registration."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from build_retrospective import OUT, sha
from stage_registry_patch import ENTITY_ID, REGISTRY_ROOT, registry_module


def main():
    registry = registry_module()
    receipt = json.loads((OUT / "REGISTRY_UPDATE_RECEIPT.json").read_text(encoding="utf-8-sig"))
    assert receipt["status"] == "AUTHORITATIVE_REGISTRY_UPDATED"
    before_head = receipt["base_head_sha256"]
    after_head = receipt["new_head_sha256"]
    manifest_before, before, aliases_before = registry._load_snapshot(REGISTRY_ROOT, before_head)
    manifest_after, after, aliases_after = registry._load_snapshot(REGISTRY_ROOT, after_head)
    before_map = {e["entity_id"]: e for e in before}
    after_map = {e["entity_id"]: e for e in after}
    assert set(before_map) == set(after_map)
    assert aliases_before == aliases_after
    changed = [k for k in before_map if before_map[k] != after_map[k]]
    assert changed == [ENTITY_ID]
    original, revised = before_map[ENTITY_ID], after_map[ENTITY_ID]
    for key, value in original.items():
        if key not in {"metadata", "row_hash"}:
            assert revised[key] == value
    for key, value in original["metadata"].items():
        assert revised["metadata"][key] == value
    added = revised["metadata"]["related_task_knowledge_refs"][-1]
    assert added["task_id"] == "TOP20_MULTIMODEL_COOPERATION_20260928_9231"
    for prefix in ["report", "artifact_index", "study_log"]:
        assert sha(Path(added[prefix + "_ref"])) == added[prefix + "_sha256"]
    for native in added["native_batch_refs"]:
        assert sha(Path(native["manifest_ref"])) == native["manifest_sha256"]
    # This assertion is scoped to existing governance semantics, not historical exposure.
    assert revised["post_2025_observation_count"] == original["post_2025_observation_count"] == 0
    content_review = json.loads((OUT / "CONTENT_REVIEW.json").read_text(encoding="utf-8-sig"))
    integrity_review = json.loads((OUT / "SOURCE_INTEGRITY_REVIEW.json").read_text(encoding="utf-8-sig"))
    assert content_review["status"].startswith("PASS")
    assert integrity_review["status"] == "PASS"
    for path, expected in content_review["reviewed_document_sha256"].items():
        assert sha(Path(path)) == expected
    for pending in content_review["pending_delivery_refs"]:
        assert Path(pending["path"]).is_file() or Path(pending["path"]) == OUT / "VERIFICATION.json"
    report_path = OUT / "RETROSPECTIVE_REPORT.md"
    report = report_path.read_text(encoding="utf-8")
    links = sorted(set(re.findall(r"\]\(<([^>]+)>\)", report)))
    missing_links = [p for p in links if not Path(p).is_file() and Path(p) != OUT / "VERIFICATION.json"]
    assert not missing_links, missing_links
    reuse = json.loads((OUT / "REUSE_INDEX.json").read_text(encoding="utf-8"))
    assert len(reuse["entries"]) == 27
    for entry in reuse["entries"]:
        assert sha(Path(entry["path"])) == entry["sha256"]
    ledger = json.loads((OUT / "RESEARCH_LEDGER.json").read_text(encoding="utf-8"))
    assert sha(report_path) == ledger["report_sha256"]
    assert sha(OUT / "REUSE_INDEX.json") == ledger["reuse_index_sha256"]
    keys = [(row["batch_id"], row["policy"], scenario["year"], scenario["cost_bps"]) for row in ledger["method_rows"] for scenario in row["diagnostic_scenarios"]]
    assert len(keys) == len(set(keys)) == 104
    registry_check = registry.validate_registry(REGISTRY_ROOT)
    assert registry_check["status"] == "PASS", registry_check
    assert registry_check["head_sha256"] == after_head, "A concurrent successor needs separate contextual verification."
    query_check = json.loads((OUT / "REGISTRY_DISCOVERY_CHECK.json").read_text(encoding="utf-8-sig"))
    assert query_check["status"] == "PASS"
    outputs = {
        "status": "PASS_DOCUMENTATION_AND_AUTHORITATIVE_REGISTRY_UPDATE",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "report_sha256": sha(report_path),
        "method_rows": len(ledger["method_rows"]),
        "unique_native_scenario_rows": len(keys),
        "reuse_entries": len(reuse["entries"]),
        "markdown_unique_file_links": len(links),
        "missing_links": [],
        "registry": {
            "root": str(REGISTRY_ROOT),
            "base_head_sha256": before_head,
            "new_head_sha256": after_head,
            "changed_entity_ids": changed,
            "entities_before_after": [len(before), len(after)],
            "aliases_before_after": [len(aliases_before), len(aliases_after)],
            "all_original_logical_fields_preserved": True,
            "all_old_metadata_and_references_preserved": True,
            "terminal_entities_unchanged": True,
            "event_chain_and_snapshots": registry_check["status"],
            "discovery_check_ref": str(OUT / "REGISTRY_DISCOVERY_CHECK.json"),
        },
        "source_integrity_review_ref": str(OUT / "SOURCE_INTEGRITY_REVIEW.json"),
        "source_integrity_review_sha256": sha(OUT / "SOURCE_INTEGRITY_REVIEW.json"),
        "content_review_ref": str(OUT / "CONTENT_REVIEW.json"),
        "content_review_sha256": sha(OUT / "CONTENT_REVIEW.json"),
        "current_task_operations": {"fits": 0, "model_predictions": 0, "account_replays": 0, "canonical_registry_patch_events": 1, "new_entities": 0, "new_aliases": 0, "old_batch_mutations": 0},
        "research_limits_preserved": {"formal_data_certification": False, "new_blind_test": False, "stable_champion_established": False},
        "delivery_sha256": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "VERIFICATION.json"},
    }
    (OUT / "VERIFICATION.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert all(Path(p).is_file() for p in links)
    print(json.dumps({k: v for k, v in outputs.items() if k not in {"delivery_sha256", "registry"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
