#!/usr/bin/env python
"""Tests for V21.052-R2 manual review reference classifier."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_052_r2_manual_review_reference_classifier.py"
spec = importlib.util.spec_from_file_location("v21_052_r2", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manual_row(
    file_path: str,
    *,
    ref_type: str = "V20_OUTPUT",
    referenced_by: str = "",
    active: str = "FALSE",
    historical: str = "FALSE",
    shared: str = "FALSE",
    stale_risk: str = "LOW",
) -> dict[str, str]:
    return {
        "file_path": file_path,
        "file_type": "output" if file_path.startswith("outputs") else "script",
        "size_mb": "0.001000",
        "last_modified": "2026-06-19T00:00:00+00:00",
        "referenced_by_v21": referenced_by,
        "reference_type": ref_type,
        "active_current_dependency": active,
        "historical_report_reference": historical,
        "manual_review_reference": "TRUE",
        "shared_dependency": shared,
        "dependency_risk": "MEDIUM",
        "stale_lineage_risk": stale_risk,
        "classification": "MANUAL_REVIEW_REQUIRED",
        "proposed_action": "MANUAL_REVIEW_HISTORICAL_REFERENCE",
        "proposed_destination": "",
        "reason": "test row",
    }


def fixture(root: Path, *, active_stale: bool = False) -> dict[str, Path]:
    (root / "outputs/v21/migration").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/read_center").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    write_rows(root / "outputs/v21/migration/V21_052_R1_V20_DEPENDENCY_MIGRATION_RECHECK_SUMMARY.csv", [{
        "final_status": "PARTIAL_PASS_V21_052_R1_MANUAL_REVIEW_REFERENCES_REMAIN",
        "manual_review_reference_count": "7",
    }])
    rows = [
        manual_row(
            "outputs/v20/consolidation/V20_10_GATE_DECISION.csv",
            referenced_by="outputs/v21/read_center/V21_HISTORICAL_REPORT.md",
            historical="TRUE",
            stale_risk="MEDIUM",
        ),
        manual_row(
            "scripts/v20/v20_common_hash_helper.py",
            ref_type="V20_SCRIPT",
            referenced_by="scripts/v21/v21_active_current.py",
            active="TRUE",
        ),
        manual_row(
            "outputs/v20/consolidation/V20_7X_CERTIFIED_INPUT.csv",
            ref_type="V20_OUTPUT",
            referenced_by="scripts/v21/v21_active_current.py",
            active="TRUE",
        ),
        manual_row(
            "data/raw/price_universe.csv",
            ref_type="NONE",
            referenced_by="scripts/v21/v21_active_current.py",
            active="TRUE",
            shared="TRUE",
        ),
        manual_row(
            "outputs/v20/consolidation/V20_108_FACTOR.csv",
            ref_type="V20_OUTPUT",
            referenced_by="outputs/v21/audit/V21_AUDIT.csv",
            historical="TRUE",
        ),
        manual_row(
            "outputs/v20/consolidation/V20_166_FACTOR.csv",
            ref_type="V20_OUTPUT",
            referenced_by="outputs/v21/audit/V21_AUDIT.csv",
            historical="TRUE",
        ),
    ]
    if active_stale:
        rows.append(manual_row(
            "outputs/v20/consolidation/V20_16_GATE_DECISION.csv",
            ref_type="V20_OUTPUT",
            referenced_by="scripts/v21/v21_active_current.py",
            active="TRUE",
            stale_risk="HIGH",
        ))
    write_rows(root / "outputs/v21/migration/V21_052_R1_MANUAL_REVIEW_REFERENCES.csv", rows)
    write_rows(root / "outputs/v20/consolidation/V20_10_GATE_DECISION.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv", [{"ticker": "A"}])
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(official, [{"ticker": "A", "rank": "1"}])
    current = root / "outputs/v21/migration/V21_052_R1_V20_DEPENDENCY_MIGRATION_RECHECK_SUMMARY.csv"
    return {"official": official, "v20": root / "outputs/v20/consolidation/V20_10_GATE_DECISION.csv", "v21_current": current}


def test_count_reconciliation_and_required_fields() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_classifier(root)
        assert summary["manual_review_reference_count_from_summary"] == "7"
        assert summary["manual_review_reference_count_from_file"] == 6
        assert summary["manual_review_count_reconciled"] == "FALSE"
        assert summary["total_manual_review_references_classified"] == 6
        assert set(module.SUMMARY_FIELDS).issubset(summary)
        assert all(row["primary_classification"] for row in rows)


def test_classification_buckets_and_exact_stage_matching() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_classifier(root)
        classes = {row["file_path"]: row["primary_classification"] for row in rows}
        assert classes["outputs/v20/consolidation/V20_10_GATE_DECISION.csv"] == "HARMLESS_HISTORICAL_REFERENCE"
        assert classes["scripts/v20/v20_common_hash_helper.py"] == "TRUE_V20_SCRIPT_DEPENDENCY"
        assert classes["outputs/v20/consolidation/V20_7X_CERTIFIED_INPUT.csv"] == "TRUE_V20_OUTPUT_DEPENDENCY"
        assert classes["data/raw/price_universe.csv"] == "SHARED_HELPER_OR_DATA_DEPENDENCY"
        assert classes["outputs/v20/consolidation/V20_108_FACTOR.csv"] == "HARMLESS_HISTORICAL_REFERENCE"
        assert classes["outputs/v20/consolidation/V20_166_FACTOR.csv"] == "HARMLESS_HISTORICAL_REFERENCE"
        assert not module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_108_FACTOR.csv")
        assert not module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_166_FACTOR.csv")
        assert summary["active_stale_downstream_dependency_count"] == 0


def test_active_stale_dependency_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_stale=True)
        summary, _ = module.run_classifier(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["stale_downstream_dependency_found"] == "TRUE"
        assert summary["active_stale_downstream_dependency_count"] == 1


def test_no_files_deleted_or_moved_and_outputs_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(paths["v20"]), sha(paths["official"]), sha(paths["v21_current"]))
        summary, _ = module.run_classifier(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert before_hashes == (sha(paths["v20"]), sha(paths["official"]), sha(paths["v21_current"]))
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_protected_mutation_permissions_outputs_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_classifier(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_classifier(root)
        second, _ = module.run_classifier(root)
        assert first["final_status"] == second["final_status"]
        for name in (
            "V21_052_R2_CLASSIFIED_MANUAL_REVIEW_REFERENCES.csv",
            "V21_052_R2_TRUE_V20_SCRIPT_DEPENDENCIES.csv",
            "V21_052_R2_TRUE_V20_OUTPUT_DEPENDENCIES.csv",
            "V21_052_R2_HARMLESS_HISTORICAL_REFERENCES.csv",
            "V21_052_R2_SHARED_HELPER_OR_DATA_DEPENDENCIES.csv",
            "V21_052_R2_STALE_DOWNSTREAM_ACTIVE_DEPENDENCY_AUDIT.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()
        assert second["deletion_allowed"] == "FALSE"
        assert second["migration_allowed"] == "FALSE"
        assert second["archive_allowed"] == "FALSE"
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


if __name__ == "__main__":
    test_count_reconciliation_and_required_fields()
    test_classification_buckets_and_exact_stage_matching()
    test_active_stale_dependency_blocks()
    test_no_files_deleted_or_moved_and_outputs_not_mutated()
    test_protected_mutation_permissions_outputs_and_repeat_safe()
    print("PASS test_v21_052_r2_manual_review_reference_classifier")
