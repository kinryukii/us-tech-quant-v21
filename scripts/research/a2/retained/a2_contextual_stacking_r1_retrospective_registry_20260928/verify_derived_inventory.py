"""Check the existing inventory adapter preserves legacy cells and accepted knowledge."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"D:\us-tech-quant")
from scripts.maintenance.research_inventory import DERIVED_FIELDS


def read(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--published", action="store_true")
    args = parser.parse_args()
    old_fields, old_rows = read(HERE / "derived_before/research_branch_registry_current.csv")
    new_fields, new_rows = read(HERE / "derived_after/research_branch_registry_current.csv")
    baseline = {row["canonical_branch_id"]: row for row in old_rows}
    current = {row["canonical_branch_id"]: row for row in new_rows}
    legacy_fields = [field for field in old_fields if field not in DERIVED_FIELDS]
    assert set(baseline) == set(current)
    assert all(baseline[key][field] == current[key][field] for key in baseline for field in legacy_fields)
    assert all(baseline[key]["registry_status"] == current[key]["registry_status"] for key in baseline)
    pointer = json.loads(Path(r"D:\us-tech-quant-results\US_TECH_QUANT_RESEARCH_REGISTRY\CURRENT.json").read_text(encoding="utf-8"))
    assert all(row["registry_head_sha256"] == pointer["head_sha256"] for row in new_rows)
    parent = current["THIRTEEN_F_LEVEL_AND_LIFECYCLE_LINEAGE"]
    assert parent["registry_knowledge_ref"] == str(HERE / "REPORT.md")
    for alias in ["A2_MULTIMODEL_JOINT_20260928", "A2_MULTIMODEL_JOINT_REVIEW_20260928", "A2_CONTEXTUAL_STACKING_R1", "A2_CONTEXTUAL_STACKING_R1_20260928"]:
        assert alias in parent["registry_aliases"].split("; ")
    conflicts_before = [key for key, row in baseline.items() if "CONFLICT" in row.get("inventory_status_comparison", "")]
    conflicts_after = [key for key, row in current.items() if "CONFLICT" in row.get("inventory_status_comparison", "")]
    assert conflicts_before == conflicts_after
    result = {
        "status": "PASS", "registry_head_sha256": pointer["head_sha256"],
        "row_count": len(current), "legacy_field_count": len(legacy_fields),
        "all_legacy_cells_preserved": True, "all_registered_statuses_unchanged": True,
        "four_new_aliases_and_latest_knowledge_visible": True,
        "preexisting_status_conflicts_retained": conflicts_after,
        "scope": "Derived navigation only; no new identity authority or lifecycle decision",
        "published": args.published,
    }
    if args.published:
        published_csv = Path(r"D:\us-tech-quant-results\A2_RESEARCH_REGISTRY_CURRENT\research_branch_registry_current.csv")
        published_md = Path(r"D:\us-tech-quant\docs\research\README.md")
        assert sha(published_csv) == sha(HERE / "derived_after/research_branch_registry_current.csv")
        assert sha(published_md) == sha(HERE / "derived_after/README.md")
        manifest = json.loads(Path(r"D:\us-tech-quant-results\A2_RESEARCH_REGISTRY_CURRENT\hash_manifest.json").read_text(encoding="utf-8-sig"))
        assert manifest["registry_head_sha256"] == pointer["head_sha256"]
        assert manifest["artifacts"][published_csv.name]["sha256"] == sha(published_csv)
        result.update({"published_csv": str(published_csv), "published_csv_sha256": sha(published_csv), "published_markdown": str(published_md), "published_markdown_sha256": sha(published_md), "published_manifest": str(Path(r"D:\us-tech-quant-results\A2_RESEARCH_REGISTRY_CURRENT\hash_manifest.json"))})
        receipt_path = HERE / "REGISTRY_UPDATE_RECEIPT.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["derived_inventory_refresh_status"] = "PASS"
        receipt["derived_inventory_verification"] = result
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / ("DERIVED_INVENTORY_VERIFICATION.json" if args.published else "DERIVED_INVENTORY_PREVIEW_CHECK.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
