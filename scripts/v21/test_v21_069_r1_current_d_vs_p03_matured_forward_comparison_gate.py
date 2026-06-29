#!/usr/bin/env python
"""Contract tests for V21.069-R1 current D versus P03 maturity gate."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_069_r1_current_d_vs_p03_matured_forward_comparison_gate.py"
SPEC = importlib.util.spec_from_file_location("v21_069_r1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth(value: object) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def test_repository_run() -> None:
    validation_path, _, paths = MODULE.discover_068(ROOT)
    forwards = MODULE.forward_candidates(ROOT, None)
    protected = MODULE.protected_files(
        ROOT, ROOT / MODULE.OUT_REL, [validation_path, *paths.values(), *forwards]
    )
    before = {path: digest(path) for path in protected}
    result = MODULE.run_stage(ROOT)
    assert not str(result["final_status"]).startswith("BLOCKED_"), result
    output = ROOT / MODULE.OUT_REL
    required = [
        MODULE.CANDIDATE_NAME, MODULE.MATURITY_NAME,
        MODULE.COMPARISON_NAME, MODULE.DECISION_NAME, MODULE.VALIDATION_NAME,
    ]
    assert all((output / name).is_file() for name in required)
    candidates = pd.read_csv(output / MODULE.CANDIDATE_NAME)
    comparison = pd.read_csv(output / MODULE.COMPARISON_NAME)
    decision = pd.read_csv(output / MODULE.DECISION_NAME).iloc[0]
    validation = pd.read_csv(output / MODULE.VALIDATION_NAME).iloc[0]
    assert set(MODULE.CANDIDATE_COLUMNS).issubset(candidates.columns)
    assert set(MODULE.COMPARISON_COLUMNS).issubset(comparison.columns)
    assert truth(validation["source_ranking_hash_verified"])
    assert truth(validation["research_only"])
    assert truth(validation["current_d_preserved"])
    assert not truth(validation["ranking_mutation"])
    assert not truth(validation["official_mutation"])
    assert not truth(validation["protected_outputs_modified"])
    assert not truth(validation["forward_ledger_mutation"])
    assert truth(validation["current_d_candidate_available"])
    assert truth(validation["p03_candidate_available"])
    assert not truth(decision["adoption_allowed"])
    assert not truth(decision["official_adoption_allowed"])
    if not truth(validation["matured_forward_available"]):
        assert validation["final_status"] == (
            "PARTIAL_PASS_V21_069_R1_WAITING_FOR_MATURED_FORWARD_OBSERVATIONS"
        )
    else:
        assert {"TOP20", "TOP50"}.issubset(set(comparison["top_n"]))
    assert before == {path: digest(path) for path in protected}


def test_source_hash_mismatch_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        validation_path, _, _ = MODULE.discover_068(ROOT)
        fake = pd.read_csv(validation_path)
        fake.loc[0, "source_ranking_hash"] = "0" * 64
        fake_path = Path(temporary) / "validation.csv"
        fake.to_csv(fake_path, index=False)
        result = MODULE.run_stage(
            ROOT, fake_path, Path(temporary) / "output"
        )
        assert result["final_status"] == "BLOCKED_V21_069_R1_SOURCE_HASH_MISMATCH"


def test_missing_p03_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        _, _, paths = MODULE.discover_068(ROOT)
        rankings = pd.read_csv(paths["rankings"])
        rankings = rankings[rankings["perturbation_id"] != MODULE.P03_ID]
        rankings_path = Path(temporary) / "rankings.csv"
        rankings.to_csv(rankings_path, index=False)
        result = MODULE.run_stage(
            ROOT, output_override=Path(temporary) / "output",
            rankings_override=rankings_path,
        )
        assert result["final_status"] == (
            "BLOCKED_V21_069_R1_MISSING_068_INPUTS_OR_CANDIDATES"
        )


def test_future_forward_label_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        future = Path(temporary) / "future.csv"
        pd.DataFrame([{
            "variant_id": "D_WEIGHT_OPTIMIZED_R1", "as_of_date": "2999-01-01",
            "ticker": "X", "forward_window": "5D",
            "scheduled_maturity_date": "2999-01-10",
            "maturity_status": "MATURED", "realized_forward_return": 0.1,
        }]).to_csv(future, index=False)
        result = MODULE.run_stage(
            ROOT, output_override=Path(temporary) / "output",
            forward_override=future,
        )
        assert result["final_status"] == (
            "BLOCKED_V21_069_R1_FORWARD_LABEL_OR_LINEAGE_RISK"
        )


if __name__ == "__main__":
    test_repository_run()
    test_source_hash_mismatch_blocked()
    test_missing_p03_blocked()
    test_future_forward_label_blocked()
    print("PASS test_v21_069_r1_current_d_vs_p03_matured_forward_comparison_gate")
