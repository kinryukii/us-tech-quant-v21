#!/usr/bin/env python
"""Tests for V21.053-R2 shared dependency migration commit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_053_r2_shared_dependency_migration_commit.py"
spec = importlib.util.spec_from_file_location("v21_053_r2", SCRIPT)
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


def plan_row(source: str, target: str) -> dict[str, str]:
    return {
        "source_path": source,
        "source_type": "output",
        "dependency_class": "SHARED_DATA_MANIFEST",
        "current_reference_locations": "scripts/v21/v21_active.py|outputs/v21/read_center/history.csv",
        "proposed_target_path": target,
        "proposed_action": "PLAN_COPY_TO_SHARED_MANIFEST",
        "proposed_reference_after_migration": target,
        "migration_required": "TRUE",
        "copy_required": "TRUE",
        "source_rewrite_required": "TRUE",
        "delete_required": "FALSE",
        "protected_path": "FALSE",
        "risk_level": "LOW",
        "reason": "fixture",
    }


def rewrite_row(ref_file: str, old: str, new: str, *, safe: str = "TRUE") -> dict[str, str]:
    return {
        "referencing_file": ref_file,
        "old_reference": old,
        "new_reference": new,
        "rewrite_required": "TRUE",
        "rewrite_safe": safe,
        "reason": "fixture",
    }


def fixture(root: Path, *, ready: bool = True, duplicate_conflict: bool = False, duplicate_same: bool = False, active_bad: str = "") -> dict[str, Path]:
    out = root / "outputs/v21/migration"
    out.mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/read_center").mkdir(parents=True, exist_ok=True)
    write_rows(out / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_SUMMARY.csv", [{
        "final_status": "PASS_V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_READY" if ready else "BLOCKED",
        "ready_for_shared_dependency_migration_commit": "TRUE" if ready else "FALSE",
        "protected_path_conflict_count": "0",
        "unsafe_migration_candidate_count": "0",
        "active_stale_downstream_dependency_reintroduced": "FALSE",
        "true_v20_script_dependency_reintroduced": "FALSE",
        "true_v20_output_dependency_reintroduced": "FALSE",
        "planned_delete_count": "0",
    }])
    src1 = root / "outputs/v20/consolidation/V20_A.csv"
    src2 = root / "outputs/v20/consolidation/V20_B.csv"
    src1.write_text("alpha\n", encoding="utf-8")
    src2.write_text("alpha\n" if duplicate_same else "beta\n", encoding="utf-8")
    target1 = "outputs/shared/manifest/A.csv"
    target2 = "outputs/shared/manifest/B.csv"
    rows = [plan_row("outputs/v20/consolidation/V20_A.csv", target1)]
    if duplicate_conflict or duplicate_same:
        rows.append(plan_row("outputs/v20/consolidation/V20_B.csv", target1))
    else:
        rows.append(plan_row("outputs/v20/consolidation/V20_B.csv", target2))
    write_rows(out / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_PLAN.csv", rows)
    active = root / "scripts/v21/v21_active.py"
    active.write_text('SRC = "outputs/v20/consolidation/V20_A.csv"\n', encoding="utf-8")
    hist = root / "outputs/v21/read_center/history.csv"
    hist.write_text("outputs/v20/consolidation/V20_A.csv\n", encoding="utf-8")
    if active_bad == "script":
        active.write_text('BAD = "scripts/v20/helper.py"\n', encoding="utf-8")
    if active_bad == "output":
        active.write_text('BAD = "outputs/v20/consolidation/V20_7X.csv"\n', encoding="utf-8")
    if active_bad == "stale":
        active.write_text('BAD = "outputs/v20/consolidation/V20_16_GATE_DECISION.csv"\n', encoding="utf-8")
    write_rows(out / "V21_053_R1_REFERENCE_REWRITE_PLAN.csv", [
        rewrite_row("scripts/v21/v21_active.py", "outputs/v20/consolidation/V20_A.csv", target1),
        rewrite_row("outputs/v21/read_center/history.csv", "outputs/v20/consolidation/V20_A.csv", target1),
    ])
    official = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    official.write_text("ticker,rank\nA,1\n", encoding="utf-8")
    v21_current = out / "V21_053_R1_SHARED_DEPENDENCY_MIGRATION_DRY_RUN_SUMMARY.csv"
    return {"src1": src1, "src2": src2, "active": active, "hist": hist, "official": official, "v21_current": v21_current}


def test_ready_state_required_and_duplicate_conflicts() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, ready=False)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, duplicate_conflict=True)
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_DUPLICATE
        assert summary["duplicate_target_path_conflict_count"] == 1


def test_duplicate_safe_dedup_allowed_files_copied_not_moved_or_deleted() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root, duplicate_same=True)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        summary, logs = module.run_commit(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert summary["duplicate_target_path_count"] == 1
        assert summary["duplicate_target_path_conflict_count"] == 0
        assert summary["copy_success_count"] == 1
        assert (root / "outputs/shared/manifest/A.csv").exists()
        assert before_files.issubset(after_files)
        assert paths["src1"].exists() and paths["src2"].exists()
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert any(log["success"] == "TRUE" for log in logs)


def test_reference_rewrite_only_approved_active_source_preserves_historical() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_commit(root)
        assert 'outputs/shared/manifest/A.csv' in paths["active"].read_text(encoding="utf-8")
        assert 'outputs/v20/consolidation/V20_A.csv' in paths["hist"].read_text(encoding="utf-8")
        assert summary["reference_rewrite_success_count"] == 1
        assert summary["source_modification_count"] == 1


def test_post_migration_audit_detects_reintroduced_dependencies() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_bad="script")
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_TRUE_V20
        assert summary["post_migration_v21_reads_v20_scripts"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_bad="output")
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_TRUE_V20
        assert summary["post_migration_v21_reads_v20_outputs_as_current_source"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_bad="stale")
        summary, _ = module.run_commit(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["active_stale_downstream_dependency_reintroduced"] == "TRUE"


def test_manifests_mutation_guards_permissions_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before = (sha(paths["src1"]), sha(paths["official"]), sha(paths["v21_current"]))
        summary, _ = module.run_commit(root)
        after = (sha(paths["src1"]), sha(paths["official"]), sha(paths["v21_current"]))
        assert before == after
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"
        for name in (
            "V21_053_R2_ROLLBACK_MANIFEST.csv",
            "V21_053_R2_TARGET_HASH_MANIFEST.csv",
            "V21_053_R2_POST_MIGRATION_DEPENDENCY_AUDIT.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()
        first = summary
        second, _ = module.run_commit(root)
        assert set(module.SUMMARY_FIELDS).issubset(second)
        assert first["final_status"] == second["final_status"]
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert second[field] == "FALSE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_commit(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_ready_state_required_and_duplicate_conflicts()
    test_duplicate_safe_dedup_allowed_files_copied_not_moved_or_deleted()
    test_reference_rewrite_only_approved_active_source_preserves_historical()
    test_post_migration_audit_detects_reintroduced_dependencies()
    test_manifests_mutation_guards_permissions_and_repeat_safe()
    print("PASS test_v21_053_r2_shared_dependency_migration_commit")
