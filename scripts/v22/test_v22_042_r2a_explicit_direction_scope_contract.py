from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parent
    / "v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py"
)


def load_module():
    name = "v22_042_r2a_under_test"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def v41():
    return {
        "liquidity_candidate_count": 2,
        "real_readonly_quote_verified": True,
        "fallback_rows_used": False,
    }


def v42(soxx: str, qqq: str, spy: str = "MIXED_OR_WAIT"):
    return {
        "intraday_data_available": True,
        "soxx_direction_label": soxx,
        "qqq_confirmation_label": qqq,
        "spy_confirmation_label": spy,
    }


def cand(underlying: str):
    return {
        "contract_id": f"{underlying}_CALL",
        "underlying": underlying,
        "expiration": "2026-07-17",
        "dte": "5",
        "strike": "50",
        "call_put": "CALL",
        "bid": "1",
        "ask": "1.1",
        "mid": "1.05",
        "spread_pct": "0.09",
        "volume": "10",
    }


def run_case(tmp_path: Path, soxx: str, qqq: str):
    module = load_module()
    repo = tmp_path / "repo"
    summary = module.run(
        repo,
        execute=True,
        v22_041_summary=v41(),
        candidates=[cand("SOXL"), cand("SOXS")],
        v22_042_summary=v42(soxx, qqq),
    )
    mode_path = repo / module.OUT_REL / "direction_gate_mode_comparison.csv"
    with mode_path.open(encoding="utf-8", newline="") as handle:
        modes = list(csv.DictReader(handle))
    return summary, {row["gate_mode"]: row for row in modes}


def test_mixed_broad_emits_explicit_semiconductor_shadow_scopes(tmp_path):
    summary, modes = run_case(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    assert modes["strict_official_gate"]["direction_scope"] == "ALL"
    assert modes["semiconductor_only_shadow_gate"]["direction_scope"] == "SEMICONDUCTOR"
    assert modes["relaxed_broad_shadow_gate"]["direction_scope"] == "SEMICONDUCTOR"
    assert modes["relaxed_broad_shadow_gate"]["direction_scope_policy_reason"] == (
        "RELAXED_BROAD_REFERS_TO_CONFIRMATION_NOT_TRADABLE_UNIVERSE"
    )
    assert summary["direction_scope_contract_version"] == (
        "V22.042_R2A_EXPLICIT_DIRECTION_SCOPE_CONTRACT"
    )


def test_strict_confirmed_semiconductor_scope(tmp_path):
    summary, modes = run_case(tmp_path, "BULLISH", "BULLISH")
    assert modes["strict_official_gate"]["direction_label"] == (
        "BULL_SEMICONDUCTOR_CONFIRMED"
    )
    assert modes["strict_official_gate"]["direction_scope"] == "SEMICONDUCTOR"
    assert summary["strict_official_direction_scope"] == "SEMICONDUCTOR"


def test_relaxed_opposite_wait_retains_semiconductor_policy_scope(tmp_path):
    summary, modes = run_case(tmp_path, "BEARISH", "BULLISH")
    relaxed = modes["relaxed_broad_shadow_gate"]
    assert relaxed["direction_label"] == "MIXED_OR_WAIT"
    assert relaxed["wait_state"] == "True"
    assert relaxed["direction_scope"] == "SEMICONDUCTOR"
    assert summary["relaxed_broad_shadow_candidate_count"] == 0


def test_scope_contract_preserves_safety_flags(tmp_path):
    summary, modes = run_case(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    assert all(row["direction_scope_source"] == "EXPLICIT_GATE_POLICY" for row in modes.values())
    assert all(row["broker_action_allowed"] == "False" for row in modes.values())
    assert all(row["official_adoption_allowed"] == "False" for row in modes.values())
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
