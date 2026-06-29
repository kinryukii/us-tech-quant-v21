#!/usr/bin/env python
"""Tests for V21.050-R1 V20 dependency migration cleanup dry run."""

from __future__ import annotations

import csv
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_050_r1_v20_dependency_migration_and_cleanup_dry_run.py"
spec = importlib.util.spec_from_file_location("v21_050_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture(root: Path, *, stale_ref: bool = False) -> Path:
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/context").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/staging/tmp").mkdir(parents=True, exist_ok=True)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    write_rows(root / "outputs/v20/diagnostics/V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_SUMMARY.csv", [{
        "final_status": "PARTIAL_PASS_V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_DOCUMENTED_NO_LONGER_BLOCKING_DAILY_RESEARCH",
    }])
    write_rows(root / "outputs/v21/context/V21_048_R1_CONTEXT_SELECTIVITY_AUDIT_SUMMARY.csv", [{
        "final_status": "PASS_V21_048_R1_CONTEXT_SELECTIVITY_REPAIRED",
    }])
    write_rows(root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv", [{
        "final_status": "PASS_V21_049_R1_REPAIRED_CONTEXT_MATURITY_SCAFFOLD_PENDING_MATURITY",
    }])
    write_rows(root / "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/staging/tmp/V20_8_TMP.csv", [{"ticker": "A"}])
    write_rows(root / "data/raw/price_universe.csv", [{"ticker": "A"}])
    protected = root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
    write_rows(protected, [{"ticker": "A", "rank": "1"}])
    ref = "outputs/v20/consolidation/V20_8_NORMALIZED_RESEARCH_DATASET.csv" if stale_ref else "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
    (root / "scripts/v21/v21_test_reader.py").write_text(
        f"SOURCE = '{ref}'\nRAW = 'data/raw/price_universe.csv'\n",
        encoding="utf-8",
    )
    return protected


def test_v21_references_to_outputs_v20_detected_and_migration_classified() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_dry_run(root)
        assert summary["v21_reads_v20_outputs"] == "TRUE"
        assert int(summary["migration_candidate_count"]) >= 1
        assert any(row["classification"] == "MIGRATE_TO_V21" for row in rows)


def test_stale_v20_8_to_v20_16_reference_high_risk_and_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, stale_ref=True)
        summary, rows = module.run_dry_run(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["v21_reads_v20_8_to_v20_16_stale_downstream"] == "TRUE"
        assert any(row["stale_lineage_risk"] == "HIGH" for row in rows)


def test_shared_raw_data_dependency_not_treated_as_stale() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_dry_run(root)
        assert summary["shared_data_dependency_found"] == "TRUE"
        assert summary["v21_reads_v20_8_to_v20_16_stale_downstream"] == "FALSE"


def test_archive_delete_and_protected_classifications() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, rows = module.run_dry_run(root)
        assert int(summary["archive_candidate_count"]) >= 1
        assert int(summary["delete_candidate_count"]) >= 1
        assert any(row["classification"] == "DELETE_CANDIDATE_TEMP_OR_STAGING" for row in rows)
        assert any(row["classification"] == "NEVER_DELETE_PROTECTED_OFFICIAL" for row in rows)
        assert all(not row["classification"].startswith("DELETE") for row in rows if "OFFICIAL" in row["file_path"])


def test_no_files_deleted_or_moved_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        before = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        first, _ = module.run_dry_run(root)
        second, _ = module.run_dry_run(root)
        after = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        assert set(before).issubset(set(after))
        assert first["final_status"] == second["final_status"]


def test_protected_mutation_detection() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); protected = fixture(root)
        summary, _ = module.run_dry_run(root, protected_mutation_hook=lambda: protected.write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED


def test_permissions_false_and_required_summary_fields_present() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, _ = module.run_dry_run(root)
        assert set(module.SUMMARY_FIELDS).issubset(summary)
        for field in (
            "official_activation_allowed", "official_recommendation_allowed",
            "official_ranking_mutation_allowed", "official_weight_mutation_allowed",
            "broker_execution_allowed", "trade_action_allowed",
        ):
            assert summary[field] == "FALSE"
        assert summary["deletion_allowed"] == "FALSE"
        assert summary["cleanup_dry_run_only"] == "TRUE"


if __name__ == "__main__":
    test_v21_references_to_outputs_v20_detected_and_migration_classified()
    test_stale_v20_8_to_v20_16_reference_high_risk_and_blocked()
    test_shared_raw_data_dependency_not_treated_as_stale()
    test_archive_delete_and_protected_classifications()
    test_no_files_deleted_or_moved_and_repeat_safe()
    test_protected_mutation_detection()
    test_permissions_false_and_required_summary_fields_present()
    print("PASS test_v21_050_r1_v20_dependency_migration_and_cleanup_dry_run")
