from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_042_option_intraday_etf_direction_gate_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_042", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def bars(start: float, step: float, count: int = 30):
    return [
        {"time_key": f"t{i}", "open": start + step * i, "high": start + step * i + 0.2, "low": start + step * i - 0.2, "close": start + step * i, "volume": 100 + i}
        for i in range(count)
    ]


def bars_by(direction: str):
    step = 0.2 if direction == "bull" else -0.2 if direction == "bear" else 0.0
    return {sym: {"1m": bars(100, step), "15m": bars(100, step), "1h": bars(100, step)} for sym in ["SOXX", "QQQ", "SPY"]}


def candidate(underlying: str, call_put: str):
    return {
        "contract_id": f"{underlying}_{call_put}",
        "underlying": underlying,
        "expiration": "2026-07-17",
        "dte": "9",
        "strike": "50",
        "call_put": call_put,
        "bid": "1",
        "ask": "1.1",
        "mid": "1.05",
        "spread_pct": "0.095",
        "volume": "10",
    }


def good_v41(count: int = 2):
    return {"liquidity_candidate_count": count, "real_readonly_quote_verified": True, "fallback_rows_used": False}


def run_gate(tmp_path, bar_data, summary=None, candidates=None):
    return module.run(
        tmp_path / "repo",
        execute=True,
        bars_by_symbol=bar_data,
        v22_041_summary=summary or good_v41(),
        v22_041_candidates=candidates if candidates is not None else [candidate("SOXL", "CALL"), candidate("SOXS", "CALL")],
    )


def read_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_bullish_soxx_with_confirmation_promotes_soxl_calls(tmp_path):
    summary = run_gate(tmp_path, bars_by("bull"), candidates=[candidate("SOXL", "CALL"), candidate("SOXS", "CALL")])
    assert summary["final_direction_label"] == "BULL_SEMICONDUCTOR_CONFIRMED"
    assert summary["promoted_candidate_count"] == 1
    promoted = read_rows(tmp_path / "repo" / module.OUT_REL / "etf_option_candidates_direction_filtered.csv")
    assert promoted[0]["underlying"] == "SOXL"
    assert promoted[0]["call_put"] == "CALL"


def test_bearish_soxx_with_confirmation_promotes_soxs_calls(tmp_path):
    summary = run_gate(tmp_path, bars_by("bear"), candidates=[candidate("SOXL", "CALL"), candidate("SOXS", "CALL")])
    assert summary["final_direction_label"] == "BEAR_SEMICONDUCTOR_CONFIRMED"
    promoted = read_rows(tmp_path / "repo" / module.OUT_REL / "etf_option_candidates_direction_filtered.csv")
    assert promoted[0]["underlying"] == "SOXS"
    assert promoted[0]["call_put"] == "CALL"


def test_mixed_signals_produce_wait_state(tmp_path):
    data = bars_by("bull")
    data["QQQ"] = {"1m": bars(100, -0.2), "15m": bars(100, -0.2), "1h": bars(100, -0.2)}
    summary = run_gate(tmp_path, data)
    assert summary["final_direction_label"] == "MIXED_OR_WAIT"
    assert summary["wait_state"] is True
    assert summary["promoted_candidate_count"] == 0


def test_missing_intraday_bars_warn_not_fabricated_direction(tmp_path):
    summary = run_gate(tmp_path, {})
    assert summary["final_status"] == module.WARN_DATA_STATUS
    assert summary["final_direction_label"] == "INTRADAY_DATA_INSUFFICIENT"
    assert summary["intraday_data_insufficient"] is True


def test_v22_041_fallback_rows_used_blocks_clean_pass(tmp_path):
    summary = run_gate(tmp_path, bars_by("bull"), summary={"liquidity_candidate_count": 2, "real_readonly_quote_verified": True, "fallback_rows_used": True})
    assert summary["final_status"] == module.WARN_CANDIDATES_STATUS
    assert summary["direction_gate_passed"] is True


def test_v22_041_zero_liquidity_blocks_promotion(tmp_path):
    summary = run_gate(tmp_path, bars_by("bull"), summary=good_v41(0), candidates=[])
    assert summary["final_status"] == module.WARN_CANDIDATES_STATUS
    assert summary["promoted_candidate_count"] == 0


def test_direction_filter_does_not_mutate_v22_041_outputs(tmp_path):
    repo = tmp_path / "repo"
    v41_dir = repo / module.V22_041_REL
    v41_dir.mkdir(parents=True)
    target = v41_dir / "etf_option_liquidity_candidates.csv"
    original = "contract_id,underlying,call_put\nA,SOXL,CALL\n"
    target.write_text(original, encoding="utf-8")
    module.run(repo, execute=True, bars_by_symbol=bars_by("bull"), v22_041_summary=good_v41(1), v22_041_candidates=[candidate("SOXL", "CALL")])
    assert target.read_text(encoding="utf-8") == original


def test_safety_flags_remain_false(tmp_path):
    summary = run_gate(tmp_path, bars_by("bull"))
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["research_only"] is True


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, execute=True, bars_by_symbol=bars_by("bull"), v22_041_summary=good_v41(), v22_041_candidates=[candidate("SOXL", "CALL")])
    payload = json.loads((repo / module.OUT_REL / "v22_042_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in [
        "etf_intraday_direction_snapshot.csv",
        "etf_intraday_indicator_audit.csv",
        "etf_direction_gate_decision.csv",
        "etf_option_candidates_direction_filtered.csv",
        "etf_option_candidates_rejected_by_direction.csv",
        "v22_042_summary.json",
        "V22.042_option_intraday_etf_direction_gate_report.txt",
    ]:
        assert (repo / module.OUT_REL / filename).exists()


def test_deterministic_final_status_and_decision(tmp_path):
    first = run_gate(tmp_path / "a", bars_by("bull"))
    second = run_gate(tmp_path / "b", bars_by("bull"))
    assert first["final_status"] == second["final_status"] == module.PASS_STATUS
    assert first["final_decision"] == second["final_decision"] == module.PASS_DECISION


def test_no_trade_context_or_order_behavior_exists():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_names = {"OpenSecTradeContext", "unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden_names
            if isinstance(func, ast.Name):
                assert func.id not in forbidden_names
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in text
