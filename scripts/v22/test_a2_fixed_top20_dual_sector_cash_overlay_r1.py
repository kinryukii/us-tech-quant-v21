from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(r"D:\us-tech-quant\scripts\v22\a2_fixed_top20_dual_sector_cash_overlay_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_fixed_top20_cash_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def test_normalized_hhi_is_equity_normalized_not_cash_diluted() -> None:
    labels = ["A", "A", "B", "B"]
    full = np.array([0.25, 0.25, 0.25, 0.25])
    cash_scaled = 0.8 * full
    assert abs(MOD.normalized_hhi(full, labels) - 0.5) <= 1e-15
    assert abs(MOD.normalized_hhi(cash_scaled, labels) - 0.5) <= 1e-15


def _synthetic_day() -> pd.DataFrame:
    ff12 = ["A"] * 12 + ["B"] * 8
    ff48 = ["A1"] * 7 + ["A2"] * 5 + ["B1"] * 5 + ["B2"] * 3
    frame = pd.DataFrame({"ticker": [f"T{i:02d}" for i in range(20)], "ff12": ff12, "ff48": ff48})
    counts = frame.groupby("ff12").ticker.transform("count").astype(float)
    raw_group = frame.groupby("ff12").ticker.count().astype(float) / 20.0
    budget = raw_group.pow(0.75)
    budget /= budget.sum()
    frame["s1_weight"] = [float(budget[group] / count) for group, count in zip(frame.ff12, counts)]
    return frame


def test_solver_is_deterministic_only_downweights_and_obeys_cash_guard() -> None:
    day = _synthetic_day()
    raw = np.full(20, 0.05)
    target12 = min(MOD.normalized_hhi(raw, day.ff12), MOD.normalized_hhi(day.s1_weight, day.ff12))
    target48 = min(MOD.normalized_hhi(raw, day.ff48), MOD.normalized_hhi(day.s1_weight, day.ff48))
    first = MOD.solve_session_weights(day, target12, target48)
    second = MOD.solve_session_weights(day, target12, target48)
    assert first["weights"] == second["weights"]
    values = np.array(list(first["weights"].values()))
    assert values.min() >= -MOD.CONSTRAINT_TOL
    assert values.max() <= 0.05 + MOD.CONSTRAINT_TOL
    assert first["additional_cash"] <= 0.20 + MOD.CONSTRAINT_TOL
    assert abs(first["gross"] + first["additional_cash"] - 1.0) <= 1e-12


def test_contract_has_no_search_and_fixed_four_arms() -> None:
    contract = json.loads((MOD.OUT / "overlay_contract.json").read_text(encoding="utf-8"))
    assert contract["max_additional_cash"] == 0.20
    assert contract["no_parameter_search"] is True
    assert contract["no_model_fit"] is True
    assert contract["2026_outcome_used"] is False
    assert contract["economic_outcome_read_count_at_freeze"] == 0


def test_completed_artifacts_reconcile_and_preserve_identity() -> None:
    result = json.loads((MOD.OUT / "classification.json").read_text(encoding="utf-8"))
    mechanics = result["mechanics"]
    economics = result["economics"]
    assert economics["raw_reconciliation"] == "PASS_EXACT_1E-12"
    assert economics["s1_reconciliation"] == "PASS_EXACT_1E-12"
    assert economics["top20_membership_status"] == "PASS_IDENTICAL_ALL_750_SESSIONS"
    assert result["2026_outcome_used"] is False and result["2026_leakage_count"] == 0
    assert mechanics["max_gross_match_error"] <= 1e-12
    assert mechanics["max_gross_matched_ff12_hhi_error"] <= 1e-12
    assert mechanics["max_gross_matched_ff48_hhi_error"] <= 1e-12
    assert mechanics["max_cash_identity_error"] <= 1e-12
    arms = pd.read_csv(MOD.OUT / "arm_summary.csv")
    assert set(arms.arm) == {"RAW_A2", "S1_SOFT_025", "DUAL_SECTOR_CASH", "RAW_GROSS_MATCHED"}


def test_bootstrap_seed_and_artifact_hashes_are_deterministic() -> None:
    values = np.sin(np.arange(751, dtype=float)) / 1000.0
    assert MOD.paired_inference(values) == MOD.paired_inference(values)
    manifest = json.loads((MOD.OUT / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_count_including_manifest"] <= 7
    assert len(list(MOD.OUT.iterdir())) <= 7
    for row in manifest["artifacts"]:
        assert MOD.sha256_file(MOD.OUT / row["name"]) == row["sha256"]
