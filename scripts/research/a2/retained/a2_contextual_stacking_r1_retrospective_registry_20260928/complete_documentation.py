"""Verify and seal the new documentation package after actual registry acceptance."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
REPO = Path(r"D:\us-tech-quant")
sys.path.insert(0, str(REPO))
from scripts.maintenance import research_inventory as inventory


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    receipt = json.loads((HERE / "REGISTRY_UPDATE_RECEIPT.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    frozen = json.loads((HERE / "FROZEN_SOURCE_VERIFICATION.json").read_text(encoding="utf-8"))
    assert frozen["status"] == "PASS"
    write("COMPLETION.json", {"status": "FINALIZATION_IN_PROGRESS", "remaining_required_work": "Documentation validation and sealing"})
    checks = []
    broken = []
    markdown_files = sorted(HERE.rglob("*.md"))
    # Snapshotted derived README contains historical navigation and is checked by its adapter,
    # not converted into new claims that old paths are available.
    markdown_files = [p for p in markdown_files if "derived_before" not in p.parts and "derived_after" not in p.parts]
    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        assert "\ufffd" not in text, str(path)
        for target in re.findall(r"\]\(([^)]+)\)", text):
            target = target.strip("<>")
            if re.match(r"^[CD]:[/\\]", target, re.I):
                clean = re.sub(r":\d+$", "", target)
                exists = Path(clean).exists()
                checks.append({"document": str(path), "target": target, "exists": exists})
                if not exists:
                    broken.append(checks[-1])
    assert not broken, broken
    evidence = json.loads((HERE / "EVIDENCE_REUSE_INDEX.json").read_text(encoding="utf-8"))
    assert all(sha(Path(row["path"])) == row["sha256"] for row in evidence["entries"])
    registry, root = inventory.load_registry(REPO)
    state = registry.current_state(root)
    assert state["head_sha256"] == receipt["new_head_sha256"]
    entity = registry.query_registry(root, entity_id="THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE")["entities"][0]
    assert entity["metadata"]["research_knowledge_ref"] == str(HERE / "REPORT.md")
    assert entity["metadata"]["research_knowledge_sha256"] == sha(HERE / "REPORT.md")
    assert entity["metadata"]["scoped_reuse_sha256"] == sha(HERE / "EVIDENCE_REUSE_INDEX.json")
    assert entity["metadata"]["scoped_trial_notes_sha256"] == sha(HERE / "TRIALS_AND_REOPEN_RULES.md")
    review = json.loads((HERE / "REGISTRY_INDEPENDENT_REVIEW.json").read_text(encoding="utf-8"))
    assert review["status"] == "PASS"
    report_review = (HERE / "docs/REPORT_INDEPENDENT_REVIEW.md").read_text(encoding="utf-8")
    assert "FINAL_REVIEW_PASS" in report_review
    for path in HERE.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8-sig"))
    qa = {
        "status": "PASS", "utf8_markdown_files_checked": len(markdown_files),
        "local_links_checked": len(checks), "broken_links": broken,
        "evidence_hashes_checked": len(evidence["entries"]),
        "current_registered_knowledge_hash_matches": True,
        "scope": "Documentation, links, evidence references and accepted registry attachment; no economic retest",
    }
    write("DOCUMENTATION_QA.json", qa)
    files = {}
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and path.name not in {"ARTIFACT_MANIFEST.json", "COMPLETION.json"} and "__pycache__" not in path.parts:
            files[str(path.relative_to(HERE))] = {"sha256": sha(path), "bytes": path.stat().st_size}
    write("ARTIFACT_MANIFEST.json", {"role": "DOCUMENTATION_DELIVERY_INVENTORY_NOT_RESEARCH_IDENTITY_AUTHORITY", "files": files})
    result = {
        "status": "DOCUMENTATION_AND_AUTHORITATIVE_REGISTRY_UPDATE_COMPLETE",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "new_fit_calls": 0, "new_portfolio_replays": 0,
        "uses_2026_for_selection": False, "original_frozen_files_unchanged": True,
        "remaining_required_work": 0,
        "registry_root": str(root), "accepted_head_sha256": state["head_sha256"],
        "registered_scope": "Knowledge and exact aliases only; parent lifecycle unchanged",
        "report_path": str(HERE / "REPORT.md"), "report_sha256": sha(HERE / "REPORT.md"),
        "registry_update_receipt_sha256": sha(HERE / "REGISTRY_UPDATE_RECEIPT.json"),
        "frozen_source_verification_sha256": sha(HERE / "FROZEN_SOURCE_VERIFICATION.json"),
        "document_qa": qa,
        "artifact_count": len(files), "manifest_sha256": sha(HERE / "ARTIFACT_MANIFEST.json"),
        "limitations": ["Original retrospective price and source limits retained", "Scoped R1 failure; no production adoption", "Preflight is not a semantic duplicate detector or external source verifier"],
    }
    write("COMPLETION.json", result)
    print(json.dumps({"status": result["status"], "artifact_count": len(files), "local_links_checked": len(checks), "head_sha256": state["head_sha256"]}))


if __name__ == "__main__":
    main()
