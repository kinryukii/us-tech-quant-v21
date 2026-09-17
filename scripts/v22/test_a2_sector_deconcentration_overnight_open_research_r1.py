from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


OUT = Path(r"D:\us-tech-quant-results\A2_SECTOR_DECONCENTRATION_OVERNIGHT_OPEN_RESEARCH_R1")


def test_fail_closed_before_search_and_2026_seal():
    metadata = json.loads((OUT / "research_metadata.json").read_text(encoding="utf-8"))
    freeze = json.loads((OUT / "finalist_freeze.json").read_text(encoding="utf-8"))
    assert metadata["task_status"] == "FAIL_CLOSED_SECTOR_TAXONOMY_MATERIALLY_INVALID"
    assert metadata["raw_a2_reconciliation"] == "PASS_EXACT_1E-12"
    assert metadata["taxonomy_valid_security_count"] == 0
    assert metadata["taxonomy_valid_coverage"] == 0.0
    assert metadata["total_trials"] == metadata["model_fit_count"] == 0
    assert metadata["candidate_2025_outcome_read_count"] == 0
    assert metadata["outcome_2026_read_count"] == 0
    assert metadata["parameter_selection_count"] == 0
    assert freeze["freeze_payload"]["finalists"] == []
    assert freeze["freeze_payload"]["2025_candidate_outcome_read_count"] == 0
    assert freeze["freeze_payload"]["2026_outcome_read_count"] == 0


def test_raw_identity_and_dates_are_pre2026():
    metadata = json.loads((OUT / "research_metadata.json").read_text(encoding="utf-8"))
    assert metadata["raw_baseline"]["session_count"] == 751
    assert abs(metadata["raw_baseline"]["sharpe"] - 1.2353699802070324) <= 1e-12
    assert abs(metadata["raw_baseline"]["cagr"] - 0.5070421599044499) <= 1e-12
    assert pd.Timestamp(metadata["raw_date_range"][1]) < pd.Timestamp("2026-01-01")
    folds = pd.read_csv(OUT / "fold_results.csv")
    assert set(folds.year) == {2023, 2024, 2025}
    assert set(folds.evidence_role) == {"AUTHORITATIVE_RAW_REFERENCE_NOT_CANDIDATE_SELECTION"}


def test_taxonomy_evidence_is_material_and_not_silently_imputed():
    audit = pd.read_csv(OUT / "concentration_diagnostics.csv")
    assert {"A2_TRAINING_MATRIX", "13F_PIT_UNIVERSE", "MOOMOO_SECURITY_MASTER", "LOCAL_STOCK_METADATA", "V21_076_CLASSIFICATION_MASTER"}.issubset(set(audit.source))
    assert audit.valid_pre2026_coverage_count.fillna(0).sum() == 0
    assert not (OUT / "trial_ledger.parquet").exists()
    assert not (OUT / "pareto_frontier.csv").exists()
    assert not (OUT / "finalist_summary.csv").exists()
    assert not (OUT / "optional_r6_diagnostic.csv").exists()


def test_hash_manifest_and_artifact_bound():
    manifest = json.loads((OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    files = [path for path in OUT.iterdir() if path.is_file()]
    assert len(files) == 6 <= 10
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    assert manifest["artifact_count_including_manifest"] == 6
    assert manifest["2026_outcome_used"] is False
    for row in manifest["artifacts"]:
        assert hashlib.sha256((OUT / row["name"]).read_bytes()).hexdigest() == row["sha256"]
