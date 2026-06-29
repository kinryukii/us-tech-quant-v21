#!/usr/bin/env python
"""Tests for V21.052-R3 manual review resolution."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_052_r3_manual_review_resolution.py"
spec = importlib.util.spec_from_file_location("v21_052_r3", SCRIPT)
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


def row(file_path: str, final_class: str, *, ref_type: str = "NONE", refs: str = "", active: str = "FALSE", hist: str = "FALSE", shared: str = "FALSE") -> dict[str, str]:
    return {
        "file_path": file_path,
        "file_type": "output" if file_path.startswith("outputs") else "script",
        "size_mb": "0.001000",
        "last_modified": "2026-06-19T00:00:00+00:00",
        "referenced_by_v21": refs,
        "reference_type": ref_type,
        "active_current_dependency": active,
        "historical_report_reference": hist,
        "manual_review_reference": "TRUE",
        "shared_dependency": shared,
        "dependency_risk": "MEDIUM",
        "stale_lineage_risk": "LOW",
        "r1_classification": "MANUAL_REVIEW_REQUIRED",
        "r1_proposed_action": "MANUAL_REVIEW_REQUIRED",
        "r1_reason": "fixture",
        "primary_classification": final_class,
        "proposed_action": "MANUAL_REVIEW_REQUIRED" if final_class == "UNKNOWN_REQUIRES_MANUAL_REVIEW" else "KEEP_AS_HISTORICAL_REFERENCE",
        "requires_migration": "FALSE",
        "archive_only": "FALSE",
        "safe_to_ignore": "FALSE",
        "requires_manual_review_after_r2": "TRUE" if final_class == "UNKNOWN_REQUIRES_MANUAL_REVIEW" else "FALSE",
        "active_stale_downstream_dependency": "FALSE",
        "classification_reason": "fixture",
    }


def fixture(root: Path, *, active_stale: bool = False, true_active: bool = False) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    out.mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    write_rows(out / "V21_052_R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER_SUMMARY.csv", [{
        "final_status": "PARTIAL_PASS_V21_052_R2_MANUAL_REFERENCES_CLASSIFIED_REVIEW_REMAINING",
        "references_requiring_manual_review_after_r2": "3",
    }])
    rows = [
        row("outputs/v21/migration/V21_052_R1_ARCHIVE_CANDIDATES.csv", "UNKNOWN_REQUIRES_MANUAL_REVIEW"),
        row("outputs/v21/read_center/V21_HISTORICAL_REPORT.md", "UNKNOWN_REQUIRES_MANUAL_REVIEW", refs="outputs/v21/read_center/V21_INDEX.md", hist="TRUE"),
        row("data/raw/price_universe.csv", "UNKNOWN_REQUIRES_MANUAL_REVIEW", refs="scripts/v21/v21_active.py", shared="TRUE"),
        row("outputs/v20/consolidation/V20_7X_CERTIFIED_INPUT.csv", "SHARED_HELPER_OR_DATA_DEPENDENCY", shared="TRUE"),
    ]
    if active_stale:
        rows.append(row(
            "outputs/v20/consolidation/V20_16_GATE_DECISION.csv",
            "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            ref_type="V20_OUTPUT",
            refs="scripts/v21/v21_active.py",
        ))
    if true_active:
        rows.append(row(
            "scripts/v20/v20_shared_helper.py",
            "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            ref_type="V20_SCRIPT",
            refs="scripts/v21/v21_active.py",
        ))
    write_rows(out / "V21_052_R2_CLASSIFIED_MANUAL_REVIEW_REFERENCES.csv", rows)
    v20 = root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(v20, [{"ticker": "A"}])
    write_rows(official, [{"ticker": "A", "rank": "1"}])
    return {"v20": v20, "official": official, "v21_current": out / "V21_052_R2_MANUAL_REVIEW_REFERENCE_CLASSIFIER_SUMMARY.csv"}


def test_unknown_references_resolved_and_outputs_exist() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_resolution(root)
        assert summary["unresolved_manual_review_count_before"] == 3
        assert summary["unresolved_manual_review_count_after"] == 0
        assert summary["newly_classified_as_harmless_historical_count"] == 2
        assert summary["newly_classified_as_shared_dependency_count"] == 1
        assert summary["ready_for_shared_dependency_migration_dry_run"] == "TRUE"
        assert all(row["requires_manual_review_after_r3"] == "FALSE" for row in rows)
        for name in (
            "V21_052_R3_RESOLVED_MANUAL_REVIEW_REFERENCES.csv",
            "V21_052_R3_FINAL_SHARED_DEPENDENCY_MIGRATION_QUEUE.csv",
            "V21_052_R3_FINAL_HARMLESS_HISTORICAL_REFERENCES.csv",
            "V21_052_R3_FINAL_BLOCKING_DEPENDENCY_AUDIT.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()


def test_active_stale_and_true_active_dependencies_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_stale=True)
        summary, _ = module.run_resolution(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["final_active_stale_downstream_dependency_count"] == 1
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, true_active=True)
        summary, _ = module.run_resolution(root)
        assert summary["final_status"] == module.BLOCKED_TRUE_ACTIVE
        assert summary["final_true_v20_script_dependency_count"] == 1


def test_no_files_deleted_or_moved_and_outputs_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(paths["v20"]), sha(paths["official"]), sha(paths["v21_current"]))
        summary, _ = module.run_resolution(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert before_hashes == (sha(paths["v20"]), sha(paths["official"]), sha(paths["v21_current"]))
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_protected_mutation_permissions_required_fields_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_resolution(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_resolution(root)
        second, _ = module.run_resolution(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
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
    test_unknown_references_resolved_and_outputs_exist()
    test_active_stale_and_true_active_dependencies_block()
    test_no_files_deleted_or_moved_and_outputs_not_mutated()
    test_protected_mutation_permissions_required_fields_and_repeat_safe()
    print("PASS test_v21_052_r3_manual_review_resolution")
