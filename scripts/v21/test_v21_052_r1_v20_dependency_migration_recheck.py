#!/usr/bin/env python
"""Tests for V21.052-R1 V20 dependency migration recheck."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_052_r1_v20_dependency_migration_recheck.py"
spec = importlib.util.spec_from_file_location("v21_052_r1", SCRIPT)
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


def fixture(root: Path, *, active_stale: bool = False) -> dict[str, Path]:
    (root / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (root / "scripts/v20").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/context").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/migration").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v21/review").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/consolidation").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/staging/tmp").mkdir(parents=True, exist_ok=True)
    (root / "outputs/v20/read_center").mkdir(parents=True, exist_ok=True)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)

    write_rows(root / "outputs/v21/migration/V21_050_R1_V20_DEPENDENCY_MIGRATION_AND_CLEANUP_DRY_RUN_SUMMARY.csv", [{
        "final_status": "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND",
        "decision": "BLOCK_V21_READS_V20_STALE_DOWNSTREAM_DEPENDENCY",
    }])
    write_rows(root / "outputs/v21/migration/V21_051_R1_REMOVE_V20_STALE_DOWNSTREAM_DEPENDENCY_SUMMARY.csv", [{
        "final_status": "PARTIAL_PASS_V21_051_R1_STALE_DEPENDENCY_REDUCED_MANUAL_REVIEW_REMAINING",
        "decision": "STALE_ACTIVE_DEPENDENCY_REMOVED_HISTORICAL_MANUAL_REVIEW_REMAINING",
    }])
    write_rows(root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v21/context/V21_049_R1_REPAIRED_CONTEXT_MATURITY_EVALUATION_SUMMARY.csv", [{"status": "PENDING"}])
    write_rows(root / "outputs/v20/consolidation/V20_108_FACTOR.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_166_FACTOR.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_10_GATE_DECISION.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_16_GATE_DECISION.csv", [{"ticker": "A"}])
    write_rows(root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv", [{"ticker": "A", "rank": "1"}])
    write_rows(root / "outputs/v20/read_center/V20_16_R4_LEGACY_DOWNSTREAM_STALE_LINEAGE_CLOSEOUT_REPORT.md", [{"line": "closeout"}])
    write_rows(root / "outputs/v20/staging/tmp/V20_8_TMP.csv", [{"ticker": "A"}])
    write_rows(root / "data/raw/price_universe.csv", [{"ticker": "A"}])

    active = root / "scripts/v21/v21_active_current.py"
    active_text = (
        'SAFE_108 = "outputs/v20/consolidation/V20_108_FACTOR.csv"\n'
        'SAFE_166 = "outputs/v20/consolidation/V20_166_FACTOR.csv"\n'
        'RAW = "data/raw/price_universe.csv"\n'
    )
    if active_stale:
        active_text += 'STALE = "outputs/v20/consolidation/V20_10_GATE_DECISION.csv"\n'
    active.write_text(active_text, encoding="utf-8")
    (root / "scripts/v20/v20_shared_helper.py").write_text("# legacy helper\n", encoding="utf-8")
    write_rows(root / "outputs/v21/review/V21_HISTORICAL_REPORT.csv", [{
        "source": "outputs/v20/consolidation/V20_16_GATE_DECISION.csv",
    }])
    return {
        "v20_108": root / "outputs/v20/consolidation/V20_108_FACTOR.csv",
        "v20_166": root / "outputs/v20/consolidation/V20_166_FACTOR.csv",
        "v20_10": root / "outputs/v20/consolidation/V20_10_GATE_DECISION.csv",
        "official": root / "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        "v21_current": root / "outputs/v21/context/V21_048_R1_REPAIRED_CONTEXT_OBSERVATION_LEDGER.csv",
    }


def test_corrected_matching_does_not_misclassify_adjacent_stage_numbers() -> None:
    assert not module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_108_FACTOR.csv")
    assert not module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_166_FACTOR.csv")
    assert module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_10_GATE_DECISION.csv")
    assert module.corrected_stale_stage_reference("outputs/v20/consolidation/V20_16_GATE_DECISION.csv")


def test_recheck_classifies_historical_shared_and_candidate_manifests() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        summary, audit = module.run_recheck(root)
        assert summary["source_v21_050_status"] == "BLOCKED_V21_050_R1_V20_STALE_DOWNSTREAM_DEPENDENCY_FOUND"
        assert summary["source_v21_051_status"] == "PARTIAL_PASS_V21_051_R1_STALE_DEPENDENCY_REDUCED_MANUAL_REVIEW_REMAINING"
        assert summary["corrected_stage_matching_used"] == "TRUE"
        assert summary["v21_active_current_reads_v20_8_to_v20_16_stale_downstream"] == "FALSE"
        assert summary["v21_reads_v20_outputs"] == "TRUE"
        assert summary["shared_data_dependency_found"] == "TRUE"
        assert int(summary["manual_review_reference_count"]) >= 1
        assert int(summary["migration_candidate_count"]) >= 1
        for name in (
            "V21_052_R1_RECHECK_DEPENDENCY_AUDIT_BY_FILE.csv",
            "V21_052_R1_SHARED_DEPENDENCY_CANDIDATES.csv",
            "V21_052_R1_MIGRATION_CANDIDATES.csv",
            "V21_052_R1_ARCHIVE_CANDIDATES.csv",
            "V21_052_R1_DELETE_CANDIDATES_DRY_RUN.csv",
            "V21_052_R1_MANUAL_REVIEW_REFERENCES.csv",
            "V21_052_R1_PROTECTED_NEVER_DELETE_MANIFEST.csv",
        ):
            assert (root / "outputs/v21/migration" / name).exists()
        assert any(row["classification"] == "KEEP_SHARED_DATA" for row in audit)
        assert any(row["classification"] == "DELETE_CANDIDATE_TEMP_OR_STAGING" for row in audit)


def test_active_exact_stale_dependency_blocks() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root, active_stale=True)
        summary, _ = module.run_recheck(root)
        assert summary["final_status"] == module.BLOCKED_STALE
        assert summary["v21_active_current_reads_v20_8_to_v20_16_stale_downstream"] == "TRUE"


def test_no_files_deleted_or_moved_and_outputs_not_mutated() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        before_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        before_hashes = (sha(paths["v20_10"]), sha(paths["official"]), sha(paths["v21_current"]))
        summary, _ = module.run_recheck(root)
        after_files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        assert before_files.issubset(after_files)
        assert summary["files_deleted_or_moved"] == "FALSE"
        assert before_hashes == (sha(paths["v20_10"]), sha(paths["official"]), sha(paths["v21_current"]))
        assert summary["v20_outputs_mutated"] == "FALSE"
        assert summary["v21_current_outputs_mutated"] == "FALSE"
        assert summary["protected_outputs_mutated"] == "FALSE"


def test_protected_files_never_delete_permissions_and_repeat_safe() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); paths = fixture(root)
        summary, _ = module.run_recheck(root, protected_mutation_hook=lambda: paths["official"].write_text("ticker,rank\nA,2\n", encoding="utf-8"))
        assert summary["final_status"] == module.BLOCKED_PROTECTED
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); fixture(root)
        first, _ = module.run_recheck(root)
        second, _ = module.run_recheck(root)
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
        protected_manifest = root / "outputs/v21/migration/V21_052_R1_PROTECTED_NEVER_DELETE_MANIFEST.csv"
        text = protected_manifest.read_text(encoding="utf-8")
        assert "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv" in text


if __name__ == "__main__":
    test_corrected_matching_does_not_misclassify_adjacent_stage_numbers()
    test_recheck_classifies_historical_shared_and_candidate_manifests()
    test_active_exact_stale_dependency_blocks()
    test_no_files_deleted_or_moved_and_outputs_not_mutated()
    test_protected_files_never_delete_permissions_and_repeat_safe()
    print("PASS test_v21_052_r1_v20_dependency_migration_recheck")
