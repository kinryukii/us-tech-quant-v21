#!/usr/bin/env python
"""Contract tests for V21.067-R2 lineage resolution and enrichment."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_067_r2_factor_component_lineage_resolver_and_explainability_rerun.py"
SPEC = importlib.util.spec_from_file_location("v21_067_r2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_run() -> None:
    r1_validation, r1_ledger, r1 = MODULE.discover_r1(ROOT)
    source = ROOT / str(r1["source_ranking_path"])
    protected = MODULE.protected_files(ROOT, ROOT / MODULE.OUT_REL, [r1_validation, r1_ledger, source])
    before = {path: digest(path) for path in protected}
    result = MODULE.run_stage(ROOT)
    assert not str(result["final_status"]).startswith("BLOCKED_"), result
    output = ROOT / MODULE.OUT_REL
    required = [
        MODULE.CATALOG_NAME, MODULE.MAP_NAME, MODULE.LEDGER_NAME,
        MODULE.SUMMARY_NAME, MODULE.MATRIX_NAME, MODULE.VALIDATION_NAME,
    ]
    assert all((output / name).is_file() for name in required)
    ledger = pd.read_csv(output / MODULE.LEDGER_NAME, low_memory=False)
    summary = pd.read_csv(output / MODULE.SUMMARY_NAME)
    validation = pd.read_csv(output / MODULE.VALIDATION_NAME).iloc[0]
    assert set(MODULE.ENRICHMENT_COLUMNS).issubset(ledger.columns)
    assert set(MODULE.EXPECTED).issubset(ledger.columns)
    assert set(MODULE.SUMMARY_COLUMNS).issubset(summary.columns)
    assert as_bool(validation["research_only"])
    assert not as_bool(validation["official_mutation"])
    assert not as_bool(validation["protected_outputs_modified"])
    assert as_bool(validation["source_ranking_hash_verified"])
    assert int(validation["enriched_ledger_rows"]) == int(validation["r1_ledger_rows"])
    assert int(validation["enriched_ledger_rows"]) == int(validation["ranking_rows"])
    assert as_bool(validation["row_count_integrity_pass"])
    assert as_bool(validation["pass_gate"])
    assert str(validation["final_status"]).startswith(("PASS_", "PARTIAL_PASS_"))
    assert before == {path: digest(path) for path in protected}


def as_bool(value: object) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def test_source_hash_mismatch_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "hash"
        r1_validation, _, r1 = MODULE.discover_r1(ROOT)
        modified = pd.read_csv(r1_validation)
        modified.loc[0, "source_ranking_hash"] = "0" * 64
        fake = Path(temporary) / "r1_validation.csv"
        modified.to_csv(fake, index=False)
        result = MODULE.run_stage(ROOT, fake, output)
        assert result["final_status"] == "BLOCKED_V21_067_R2_SOURCE_HASH_MISMATCH"


def test_duplicate_many_to_many_ambiguity_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        candidate_root = temporary_path / "candidates"
        candidate_root.mkdir()
        r1_validation, _, r1 = MODULE.discover_r1(ROOT)
        ranking = pd.read_csv(ROOT / str(r1["source_ranking_path"]))
        ticker = str(ranking.iloc[0]["ticker"])
        date = str(ranking.iloc[0]["latest_price_date"])
        pd.DataFrame([
            {"ticker": ticker, "as_of_date": date, "rsi_14": 20},
            {"ticker": ticker, "as_of_date": date, "rsi_14": 80},
        ]).to_csv(candidate_root / "ambiguous.csv", index=False)
        output = temporary_path / "output"
        result = MODULE.run_stage(ROOT, r1_validation, output, candidate_root)
        assert result["final_status"] == "BLOCKED_V21_067_R2_COMPONENT_MERGE_INTEGRITY_RISK"
        assert int(result["ambiguous_component_count"]) >= 1


if __name__ == "__main__":
    test_repository_run()
    test_source_hash_mismatch_blocked()
    test_duplicate_many_to_many_ambiguity_blocked()
    print("PASS test_v21_067_r2_factor_component_lineage_resolver_and_explainability_rerun")
