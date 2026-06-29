#!/usr/bin/env python
"""Contract tests for V21.067-R3 component gap closure."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_067_r3_component_gap_closure_liquidity_and_regime_explainability_repair.py"
SPEC = importlib.util.spec_from_file_location("v21_067_r3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth(value: object) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def test_repository_run() -> None:
    r2_path, _, paths = MODULE.discover_r2(ROOT)
    protected = MODULE.protected_files(ROOT, ROOT / MODULE.OUT_REL, [r2_path, *paths.values()])
    before = {path: digest(path) for path in protected}
    result = MODULE.run_stage(ROOT)
    assert not str(result["final_status"]).startswith("BLOCKED_"), result
    output = ROOT / MODULE.OUT_REL
    required = [
        MODULE.GAP_NAME, MODULE.QQQ_NAME, MODULE.LIQUIDITY_NAME,
        MODULE.LEDGER_NAME, MODULE.SUMMARY_NAME, MODULE.VALIDATION_NAME,
    ]
    assert all((output / name).is_file() for name in required)
    ledger = pd.read_csv(output / MODULE.LEDGER_NAME, low_memory=False)
    summary = pd.read_csv(output / MODULE.SUMMARY_NAME)
    validation = pd.read_csv(output / MODULE.VALIDATION_NAME).iloc[0]
    assert set(MODULE.R3_COLUMNS).issubset(ledger.columns)
    assert set(MODULE.SUMMARY_COLUMNS).issubset(summary.columns)
    assert truth(validation["source_ranking_hash_verified"])
    assert truth(validation["research_only"])
    assert not truth(validation["official_mutation"])
    assert not truth(validation["protected_outputs_modified"])
    assert int(validation["r3_repaired_rows"]) == int(validation["r2_enriched_rows"])
    assert int(validation["r3_repaired_rows"]) == int(validation["ranking_rows"])
    assert truth(validation["row_count_integrity_pass"])
    assert truth(validation["pass_gate"])
    assert str(validation["final_status"]).startswith(("PASS_", "PARTIAL_PASS_"))
    assert before == {path: digest(path) for path in protected}


def test_source_hash_mismatch_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        r2_path, _, _ = MODULE.discover_r2(ROOT)
        fake = pd.read_csv(r2_path)
        fake.loc[0, "source_ranking_hash"] = "0" * 64
        fake_path = Path(temporary) / "r2.csv"
        fake.to_csv(fake_path, index=False)
        result = MODULE.run_stage(ROOT, fake_path, Path(temporary) / "output")
        assert result["final_status"] == "BLOCKED_V21_067_R3_SOURCE_HASH_MISMATCH"


def test_future_dated_component_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        future = Path(temporary) / "future_qqq.csv"
        pd.DataFrame([{
            "observation_date": "2999-01-01", "qqq_state": "ABOVE_MA50",
            "qqq_price": 1, "qqq_ma50": 1,
        }]).to_csv(future, index=False)
        result = MODULE.run_stage(
            ROOT, output_override=Path(temporary) / "output", qqq_override=future
        )
        assert result["final_status"] == "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK"


def test_many_to_many_ambiguity_blocked() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        _, r2, paths = MODULE.discover_r2(ROOT)
        ranking = pd.read_csv(paths["source"])
        ticker = str(ranking.iloc[0]["ticker"])
        date = str(ranking.iloc[0]["latest_price_date"])
        ambiguous = Path(temporary) / "ambiguous_family.csv"
        pd.DataFrame([
            {"ticker": ticker, "as_of_date": date, "technical_score_raw": 10},
            {"ticker": ticker, "as_of_date": date, "technical_score_raw": 90},
        ]).to_csv(ambiguous, index=False)
        result = MODULE.run_stage(
            ROOT, output_override=Path(temporary) / "output",
            family_override=ambiguous,
        )
        assert result["final_status"] == "BLOCKED_V21_067_R3_COMPONENT_MERGE_INTEGRITY_RISK"


if __name__ == "__main__":
    test_repository_run()
    test_source_hash_mismatch_blocked()
    test_future_dated_component_blocked()
    test_many_to_many_ambiguity_blocked()
    print("PASS test_v21_067_r3_component_gap_closure_liquidity_and_regime_explainability_repair")
