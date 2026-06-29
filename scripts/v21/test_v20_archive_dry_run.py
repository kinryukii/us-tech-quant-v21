#!/usr/bin/env python
"""Tests for V20_ARCHIVE_DRY_RUN."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v20_archive_dry_run.py"
spec = importlib.util.spec_from_file_location("v20_archive_dry_run", SCRIPT)
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


def fixture(
    root: Path,
    *,
    isolation: bool = True,
    active_script: bool = False,
    active_output: bool = False,
    active_stale: bool = False,
    summary_history_count: int = 2,
) -> dict[str, Path]:
    migration = root / "outputs/v21/migration"
    (root / "scripts/v20").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/diagnostics").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/staging").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/read_center").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/price_history").mkdir(parents=True, exist_ok=True)
    (root / "outputs/shared/manifest").mkdir(parents=True, exist_ok=True)

    write_rows(migration / module.SOURCE_SUMMARY, [{
        "final_status": "PARTIAL_PASS_V21_054_R1_SOURCE_ISOLATION_CONFIRMED_HISTORICAL_REFERENCES_REMAIN",
        "source_isolation_pass": module.tf(isolation),
        "ready_for_v20_archive_dry_run": module.tf(isolation),
        "v21_active_current_reads_v20_scripts": module.tf(active_script),
        "v21_active_current_reads_v20_outputs": module.tf(active_output),
        "v21_active_current_reads_v20_8_to_v20_16_stale_downstream": module.tf(active_stale),
        "harmless_historical_v20_reference_count": str(summary_history_count),
        "v20_outputs_mutated": "FALSE",
        "v21_current_outputs_mutated": "FALSE",
        "protected_outputs_mutated": "FALSE",
    }])
    active_rows = [{
        "file_path": "",
        "reference_type": "",
        "classification": "PASS",
        "reference": "",
        "reason": "No active dependency.",
    }]
    if active_script:
        active_rows = [{"file_path": "scripts/v21/current.py", "reference_type": "V20_SCRIPT", "classification": "ACTIVE_CURRENT_V20_SCRIPT_DEPENDENCY", "reference": "scripts/v20/legacy.py", "reason": "active"}]
    elif active_output:
        active_rows = [{"file_path": "scripts/v21/current.py", "reference_type": "V20_OUTPUT", "classification": "ACTIVE_CURRENT_V20_OUTPUT_DEPENDENCY", "reference": "outputs/v20/diagnostics/V20_10_AUDIT.csv", "reason": "active"}]
    elif active_stale:
        active_rows = [{"file_path": "scripts/v21/current.py", "reference_type": "V20_STALE_DOWNSTREAM", "classification": "ACTIVE_STALE_DOWNSTREAM_DEPENDENCY", "reference": "outputs/v20/diagnostics/V20_10_AUDIT.csv", "reason": "active"}]
    write_rows(migration / module.SOURCE_ACTIVE_AUDIT, active_rows)
    write_rows(migration / module.SOURCE_HISTORY_AUDIT, [
        {"file_path": "outputs/v21/read_center/old.md", "reference_type": "V20_OUTPUT", "classification": "HARMLESS_HISTORICAL_REFERENCE", "reference": "outputs/v20", "reason": "history"},
        {"file_path": "scripts/v21/old.py", "reference_type": "V20_SCRIPT", "classification": "HARMLESS_HISTORICAL_REFERENCE", "reference": "scripts/v20", "reason": "history"},
    ])

    shared = root / "outputs/shared/manifest/A.csv"
    shared.write_text("a\n", encoding="utf-8")
    write_rows(migration / module.TARGET_HASH_MANIFEST, [{"target_path": "outputs/shared/manifest/A.csv", "source_path": "outputs/v20/diagnostics/V20_10_AUDIT.csv", "target_hash": sha(shared)}])
    write_rows(migration / module.ROLLBACK_MANIFEST, [{"copied_file_path": "outputs/shared/manifest/A.csv", "original_source_path": "outputs/v20/diagnostics/V20_10_AUDIT.csv", "rollback_action": "RESTORE"}])

    legacy_script = root / "scripts/v20/legacy.py"
    legacy_script.write_text("VALUE = 1\n", encoding="utf-8")
    archive = root / "outputs/v20/diagnostics/V20_10_AUDIT.csv"
    archive.write_text("x\n1\n", encoding="utf-8")
    keep = root / "outputs/v20/read_center/V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_REPORT.md"
    keep.write_text("# closeout\n", encoding="utf-8")
    future_delete = root / "outputs/v20/staging/V20_SMOKE_TEST_DRY_RUN.csv"
    future_delete.write_text("x\n", encoding="utf-8")
    protected = root / "outputs/v20/price_history/V20_RAW_PRICE_HISTORY.csv"
    protected.write_text("date,close\n", encoding="utf-8")
    official = root / "outputs/v20/V20_OFFICIAL_RANKING.csv"
    official.write_text("ticker,rank\nA,1\n", encoding="utf-8")
    return {
        "legacy_script": legacy_script, "archive": archive, "keep": keep,
        "future_delete": future_delete, "protected": protected,
        "official": official, "shared": shared,
    }


def test_source_isolation_and_active_dependencies_block() -> None:
    with tempfile.TemporaryDirectory() as temp:
        summary, _ = module.run_archive_dry_run(Path(temp))
        assert summary["final_status"] == module.BLOCKED_INPUT
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, isolation=False)
        summary, _ = module.run_archive_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_INPUT
    for option, field in (
        ("active_script", "v21_active_current_reads_v20_scripts"),
        ("active_output", "v21_active_current_reads_v20_outputs"),
        ("active_stale", "v21_active_current_reads_v20_8_to_v20_16_stale_downstream"),
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fixture(root, **{option: True})
            summary, _ = module.run_archive_dry_run(root)
            assert summary["final_status"] in {module.BLOCKED_INPUT, module.BLOCKED_ACTIVE}
            assert summary[field] == "TRUE"


def test_reconciliation_classification_and_packages() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_archive_dry_run(root)
        assert summary["harmless_historical_v20_reference_count_from_summary"] == 2
        assert summary["harmless_historical_v20_reference_count_from_audit_file"] == 2
        assert summary["harmless_historical_reference_count_reconciled"] == "TRUE"
        archive_paths = {row["file_path"] for row in rows["archive"]}
        keep_paths = {row["file_path"] for row in rows["keep"]}
        protected_paths = {row["file_path"] for row in rows["protected"]}
        delete_paths = {row["file_path"] for row in rows["future_delete"]}
        assert "scripts/v20/legacy.py" in archive_paths
        assert "outputs/v20/diagnostics/V20_10_AUDIT.csv" in archive_paths
        assert any("V20_16_R4" in path for path in keep_paths)
        assert not keep_paths & archive_paths
        assert any("PRICE_HISTORY" in path for path in protected_paths)
        assert any("OFFICIAL_RANKING" in path for path in protected_paths)
        assert not protected_paths & archive_paths
        assert any("SMOKE_TEST" in path for path in delete_paths)
        assert not delete_paths & archive_paths
        assert rows["packages"]
        assert summary["archive_package_count"] == len(rows["packages"])
        assert summary["ready_for_v20_delete_candidate_dry_run"] == "FALSE"

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, summary_history_count=1)
        summary, rows = module.run_archive_dry_run(root)
        assert summary["harmless_historical_reference_count_reconciled"] == "FALSE"
        assert summary["final_status"] == module.PARTIAL_REVIEW
        assert any(row["risk_id"] == "HISTORICAL_COUNT" and row["status"] == "REVIEW" for row in rows["risks"])


def test_no_mutations_permissions_fields_and_repeat_safety() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before = {name: sha(path) for name, path in paths.items()}
        first, _ = module.run_archive_dry_run(root)
        after = {name: sha(path) for name, path in paths.items()}
        assert before == after
        for field in (
            "files_deleted_or_moved", "files_archived", "files_copied",
            "source_files_mutated", "v20_outputs_mutated",
            "v21_current_outputs_mutated", "protected_outputs_mutated",
            "archive_allowed", "deletion_allowed", "migration_allowed",
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert first[field] == "FALSE"
        assert set(module.SUMMARY_FIELDS).issubset(first)
        for name in module.OUTPUT_NAMES:
            assert (root / "outputs/v21/migration" / name).exists()
        assert (root / "outputs/v21/read_center" / module.REPORT_NAME).exists()
        second, _ = module.run_archive_dry_run(root)
        assert first["final_status"] == second["final_status"]
        assert first["archive_candidate_count"] == second["archive_candidate_count"]


def test_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_dry_run(root, mutation_hook=lambda: paths["archive"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_V20
        assert summary["v20_outputs_mutated"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_dry_run(root, mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
        assert summary["protected_outputs_mutated"] == "TRUE"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_archive_dry_run(root, mutation_hook=lambda: paths["shared"].write_text("changed\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


if __name__ == "__main__":
    test_source_isolation_and_active_dependencies_block()
    test_reconciliation_classification_and_packages()
    test_no_mutations_permissions_fields_and_repeat_safety()
    test_mutation_detection()
    print("PASS test_v20_archive_dry_run")
