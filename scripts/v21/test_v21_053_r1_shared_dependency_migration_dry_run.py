#!/usr/bin/env python
"""Tests for V21.053-R1 shared dependency migration dry run."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_053_r1_shared_dependency_migration_dry_run.py"
spec = importlib.util.spec_from_file_location("v21_053_r1", SCRIPT)
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


def queue_row(path: str, *, refs: str = "scripts/v21/v21_active.py", shared: str = "TRUE") -> dict[str, str]:
    return {
        "file_path": path,
        "file_type": "script" if path.startswith("scripts") else "data" if path.startswith("data") else "output",
        "size_mb": "0.001000",
        "last_modified": "2026-06-19T00:00:00+00:00",
        "referenced_by_v21": refs,
        "reference_type": "V20_SCRIPT" if path.startswith("scripts/v20") else "V20_OUTPUT",
        "active_current_dependency": "FALSE",
        "historical_report_reference": "FALSE",
        "manual_review_reference": "TRUE",
        "shared_dependency": shared,
        "dependency_risk": "MEDIUM",
        "stale_lineage_risk": "LOW",
        "r2_primary_classification": "SHARED_HELPER_OR_DATA_DEPENDENCY",
        "r2_proposed_action": "MIGRATE_HELPER_TO_SHARED_OR_V21",
        "r2_classification_reason": "fixture",
        "final_classification": "SHARED_HELPER_OR_DATA_DEPENDENCY",
        "final_proposed_action": "MIGRATE_HELPER_TO_SHARED_OR_V21",
        "requires_migration": "TRUE",
        "archive_only": "FALSE",
        "safe_to_ignore": "FALSE",
        "requires_manual_review_after_r3": "FALSE",
        "active_stale_downstream_dependency": "FALSE",
        "newly_classified_by_r3": "FALSE",
        "resolution_reason": "fixture",
    }


def fixture(root: Path, *, ready: bool = True, protected: bool = False, unsafe: bool = False) -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    out.mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "scripts/v20").mkdir(parents=True, exist_ok=True)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    write_rows(out / "V21_052_R3_MANUAL_REVIEW_RESOLUTION_SUMMARY.csv", [{
        "final_status": "PASS_V21_052_R3_MANUAL_REVIEW_RESOLVED_READY_FOR_SHARED_MIGRATION_DRY_RUN" if ready else "PARTIAL",
        "dependency_resolution_complete": "TRUE" if ready else "FALSE",
        "ready_for_shared_dependency_migration_dry_run": "TRUE" if ready else "FALSE",
        "final_active_stale_downstream_dependency_count": "0",
        "final_true_v20_script_dependency_count": "0",
        "final_true_v20_output_dependency_count": "0",
    }])
    rows = [
        queue_row("scripts/v20/v20_hash_helper.py"),
        queue_row("outputs/v20/consolidation/V20_10_FACTOR_FIELD_CONTRACT.csv"),
        queue_row("outputs/v20/consolidation/V20_10_FACTOR_SOURCE_REGISTER.csv"),
        queue_row("data/raw/price_universe.csv"),
    ]
    if protected:
        rows.append(queue_row("outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"))
    if unsafe:
        rows.append(queue_row("misc/unknown_dependency.bin", shared="FALSE"))
    write_rows(out / "V21_052_R3_FINAL_SHARED_DEPENDENCY_MIGRATION_QUEUE.csv", rows)
    v20 = root / "outputs/v20/consolidation/V20_10_FACTOR_SOURCE_REGISTER.csv"
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    source = root / "scripts/v20/v20_hash_helper.py"
    write_rows(v20, [{"ticker": "A"}])
    write_rows(official, [{"ticker": "A", "rank": "1"}])
    source.write_text("# helper\n", encoding="utf-8")
    return {"v20": v20, "official": official, "source": source, "v21_current": out / "V21_052_R3_MANUAL_REVIEW_RESOLUTION_SUMMARY.csv"}


def test_ready_state_required() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, ready=False)
        summary, _ = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_INPUT


def test_migration_plan_targets_and_raw_data_manifest_handling() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, plan = module.run_dry_run(root)
        targets = {row["source_path"]: row["proposed_target_path"] for row in plan}
        classes = {row["source_path"]: row["dependency_class"] for row in plan}
        assert targets["scripts/v20/v20_hash_helper.py"].startswith("scripts/shared/")
        assert targets["outputs/v20/consolidation/V20_10_FACTOR_FIELD_CONTRACT.csv"].startswith("scripts/shared/contracts/")
        assert targets["outputs/v20/consolidation/V20_10_FACTOR_SOURCE_REGISTER.csv"].startswith("outputs/shared/manifest/")
        assert targets["data/raw/price_universe.csv"].startswith("data/manifests/")
        assert classes["data/raw/price_universe.csv"] == "SHARED_PRICE_OR_UNIVERSE_SOURCE"
        raw_plan = next(row for row in plan if row["source_path"] == "data/raw/price_universe.csv")
        assert raw_plan["copy_required"] == "FALSE"
        assert summary["migration_plan_row_count"] == 4
        assert int(summary["reference_rewrite_count"]) >= 4


def test_protected_and_unsafe_candidates_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, protected=True)
        summary, _ = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_PROTECTED_PATH
        assert summary["protected_path_conflict_count"] == 1
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, unsafe=True)
        summary, _ = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_UNSAFE
        assert summary["unsafe_migration_candidate_count"] == 1


def test_no_stale_or_true_v20_dependency_reintroduced() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, plan = module.run_dry_run(root)
        assert summary["active_stale_downstream_dependency_reintroduced"] == "FALSE"
        assert summary["true_v20_script_dependency_reintroduced"] == "FALSE"
        assert summary["true_v20_output_dependency_reintroduced"] == "FALSE"
        assert all(not row["proposed_reference_after_migration"].startswith(("scripts/v20/", "outputs/v20/")) for row in plan)


def test_no_file_operations_or_mutations() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(paths["v20"]), sha(paths["official"]), sha(paths["source"]), sha(paths["v21_current"]))
        summary, _ = module.run_dry_run(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert before_hashes == (sha(paths["v20"]), sha(paths["official"]), sha(paths["source"]), sha(paths["v21_current"]))
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert summary["files_copied"] == "FALSE"
        assert summary["source_files_mutated"] == "FALSE"
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_protected_mutation_permissions_required_fields_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_dry_run(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED_MUTATION
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_dry_run(root)
        second, _ = module.run_dry_run(root)
        assert first["final_status"] == second["final_status"]
        assert set(module.SUMMARY_FIELDS).issubset(second)
        for name in (
            "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_PLAN.csv",
            "V21_053_R1_REFERENCE_REWRITE_PLAN.csv",
            "V21_053_R1_MIGRATION_RISK_AUDIT.csv",
            "V21_053_R1_PROTECTED_PATH_AUDIT.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"


if __name__ == "__main__":
    test_ready_state_required()
    test_migration_plan_targets_and_raw_data_manifest_handling()
    test_protected_and_unsafe_candidates_block()
    test_no_stale_or_true_v20_dependency_reintroduced()
    test_no_file_operations_or_mutations()
    test_protected_mutation_permissions_required_fields_and_repeat_safe()
    print("PASS test_v21_053_r1_shared_dependency_migration_dry_run")
