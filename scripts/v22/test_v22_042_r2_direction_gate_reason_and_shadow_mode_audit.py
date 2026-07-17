from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_042_r2", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def v41(count=2, fallback=False):
    return {"liquidity_candidate_count": count, "real_readonly_quote_verified": True, "fallback_rows_used": fallback}


def v42(soxx, qqq, spy="MIXED_OR_WAIT"):
    return {"intraday_data_available": True, "soxx_direction_label": soxx, "qqq_confirmation_label": qqq, "spy_confirmation_label": spy}


def cand(underlying, cp):
    return {"contract_id": f"{underlying}_{cp}", "underlying": underlying, "call_put": cp, "expiration": "2026-07-17", "dte": "9", "strike": "50", "bid": "1", "ask": "1.1", "mid": "1.05", "spread_pct": "0.09", "volume": "10"}


def run(tmp_path, soxx, qqq, spy="MIXED_OR_WAIT", count=2, fallback=False, candidates=None):
    return module.run(tmp_path / "repo", execute=True, v22_041_summary=v41(count, fallback), candidates=candidates if candidates is not None else [cand("SOXL", "CALL"), cand("SOXS", "CALL")], v22_042_summary=v42(soxx, qqq, spy))


def read_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_bearish_soxx_qqq_mixed_strict_wait_and_semi_shadow(tmp_path):
    s = run(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    assert s["strict_official_final_direction_label"] == "MIXED_OR_WAIT"
    assert s["primary_wait_reason_code"] == "WAIT_BROAD_CONFIRMATION_MISSING"
    assert s["semiconductor_only_shadow_direction_label"] == "BEAR_SEMICONDUCTOR"
    assert s["semiconductor_only_shadow_candidate_count"] == 1


def test_bullish_soxx_qqq_mixed_strict_wait_and_semi_shadow(tmp_path):
    s = run(tmp_path, "BULLISH", "MIXED_OR_WAIT")
    assert s["semiconductor_only_shadow_direction_label"] == "BULL_SEMICONDUCTOR"
    assert s["semiconductor_only_shadow_candidate_count"] == 1


def test_broad_opposite_blocks_relaxed_broad_shadow(tmp_path):
    s = run(tmp_path, "BEARISH", "BULLISH")
    assert s["qqq_opposite_detected"] is True
    assert s["relaxed_broad_shadow_direction_label"] == "MIXED_OR_WAIT"
    assert s["relaxed_broad_shadow_candidate_count"] == 0


def test_broad_mixed_allows_relaxed_broad_shadow(tmp_path):
    s = run(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    assert s["relaxed_broad_shadow_direction_label"] == "BEAR_SEMICONDUCTOR"
    assert s["relaxed_broad_shadow_candidate_count"] == 1


def test_strict_confirmation_produces_official_candidates(tmp_path):
    s = run(tmp_path, "BULLISH", "BULLISH")
    assert s["final_decision"] == module.DECISION_STRICT
    assert s["strict_official_promoted_candidate_count"] == 1
    rows = read_rows(tmp_path / "repo" / module.OUT_REL / "strict_official_direction_candidates.csv")
    assert rows[0]["shadow_only"] == "False"


def test_missing_v22_041_candidates_blocks_all_promotion(tmp_path):
    s = run(tmp_path, "BULLISH", "BULLISH", count=0, candidates=[])
    assert s["primary_wait_reason_code"] == "WAIT_V22_041_CANDIDATES_MISSING"
    assert s["strict_official_promoted_candidate_count"] == 0
    assert s["semiconductor_only_shadow_candidate_count"] == 0


def test_v22_041_fallback_rows_used_blocks_clean_pass(tmp_path):
    s = run(tmp_path, "BULLISH", "BULLISH", fallback=True)
    assert s["primary_wait_reason_code"] == "WAIT_V22_041_FALLBACK_ROWS_USED"
    assert s["strict_official_promoted_candidate_count"] == 0


def test_reason_codes_are_deterministic(tmp_path):
    a = run(tmp_path / "a", "BEARISH", "MIXED_OR_WAIT")
    b = run(tmp_path / "b", "BEARISH", "MIXED_OR_WAIT")
    assert a["primary_wait_reason_code"] == b["primary_wait_reason_code"]
    assert a["secondary_wait_reason_code"] == b["secondary_wait_reason_code"]


def test_shadow_candidates_marked_shadow_only_and_safe(tmp_path):
    run(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    rows = read_rows(tmp_path / "repo" / module.OUT_REL / "semiconductor_only_shadow_candidates.csv")
    assert rows
    assert all(row["shadow_only"] == "True" for row in rows)
    assert all(row["broker_action_allowed"] == "False" for row in rows)
    assert all(row["official_adoption_allowed"] == "False" for row in rows)


def test_safety_flags_remain_false(tmp_path):
    s = run(tmp_path, "BEARISH", "MIXED_OR_WAIT")
    assert s["broker_action_allowed"] is False
    assert s["official_adoption_allowed"] is False
    assert s["trade_context_used"] is False
    assert s["unlock_trade_called"] is False
    assert s["place_order_called"] is False
    assert s["shadow_only_no_broker_action"] is True


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    s = module.run(repo, execute=True, v22_041_summary=v41(), candidates=[cand("SOXL", "CALL")], v22_042_summary=v42("BULLISH", "BULLISH"))
    payload = json.loads((repo / module.OUT_REL / "v22_042_r2_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in s
        assert field in payload
    for filename in [
        "direction_gate_reason_codes.csv",
        "direction_gate_mode_comparison.csv",
        "strict_official_direction_candidates.csv",
        "semiconductor_only_shadow_candidates.csv",
        "relaxed_broad_shadow_candidates.csv",
        "direction_gate_shadow_rejected_candidates.csv",
        "v22_042_r2_summary.json",
        "V22.042_R2_direction_gate_reason_and_shadow_mode_audit_report.txt",
    ]:
        assert (repo / module.OUT_REL / filename).exists()


def test_deterministic_final_status_and_decision(tmp_path):
    a = run(tmp_path / "a", "BEARISH", "MIXED_OR_WAIT")
    b = run(tmp_path / "b", "BEARISH", "MIXED_OR_WAIT")
    assert a["final_status"] == b["final_status"] == module.PASS_STATUS
    assert a["final_decision"] == b["final_decision"] == module.DECISION_SHADOW


def test_no_trade_context_or_order_behavior_exists():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {"OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden
            if isinstance(func, ast.Name):
                assert func.id not in forbidden
    assert "OpenSecTradeContext" not in MODULE_PATH.read_text(encoding="utf-8")
