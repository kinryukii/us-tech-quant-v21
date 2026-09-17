from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


OUT = Path(r"D:\us-tech-quant-results\A2_PIT_SECTOR_TAXONOMY_AND_DECONCENTRATION_RESUME_R1")


def read(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_raw_a2_exact_and_pre2026():
    metadata = read("research_metadata.json")
    assert metadata["raw_a2_reconciliation"] == "PASS_EXACT_1E-12"
    assert metadata["raw_baseline"]["session_count"] == 751
    assert abs(metadata["raw_baseline"]["sharpe"] - 1.2353699802070324) <= 1e-12
    assert pd.Timestamp(metadata["raw_date_range"][1]) < pd.Timestamp("2026-01-01")
    assert metadata["outcome_2026_read_count"] == 0


def test_identity_mapping_is_deterministic_and_no_fuzzy_mapping():
    metadata = read("research_metadata.json")
    assert metadata["a2_unique_securities"] == 375
    assert metadata["a2_security_dates"] == 15000
    assert metadata["security_id_mapped_securities"] == 259
    assert metadata["security_id_conflict_count"] == 0
    assert metadata["cik_mapped_securities"] == 0


def test_taxonomy_pit_gate_no_backfill_and_no_trial():
    contract = read("taxonomy_contract.json")
    metadata = read("research_metadata.json")
    freeze = read("finalist_freeze.json")
    assert contract["backward_fill_forbidden"] is True
    assert contract["current_sic_backfill_forbidden"] is True
    assert "acceptance_timestamp <= authoritative information cutoff" in contract["pit_rule"]
    assert metadata["ff12_security_date_coverage"] == metadata["ff48_security_date_coverage"] == 0.0
    assert metadata["unknown_security_date_pct"] == 1.0
    assert metadata["max_unknown_portfolio_weight"] == 1.0
    assert metadata["future_filing_violation_count"] == 0
    assert metadata["total_trials"] == metadata["model_fit_count"] == 0
    assert metadata["candidate_2025_outcome_read_count"] == 0
    assert freeze["finalists"] == []
    assert not (OUT / "pit_sector_taxonomy.parquet").exists()
    assert not (OUT / "trial_ledger.parquet").exists()


def test_hashes_and_artifact_bound():
    manifest = read("hash_manifest.json")
    files = [path for path in OUT.iterdir() if path.is_file()]
    assert len(files) == manifest["artifact_count_including_manifest"] == 6 <= 10
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    assert manifest["2026_outcome_used"] is False
    for row in manifest["artifacts"]:
        assert hashlib.sha256((OUT / row["name"]).read_bytes()).hexdigest() == row["sha256"]
