from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_043_direction_gate_forward_outcome_tracker_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_043", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def r2_summary():
    return {
        "soxx_direction_label": "BEARISH",
        "qqq_confirmation_label": "MIXED_OR_WAIT",
        "spy_confirmation_label": "MIXED_OR_WAIT",
        "strict_official_final_direction_label": "MIXED_OR_WAIT",
        "strict_official_wait_state": True,
        "strict_official_promoted_candidate_count": 0,
        "semiconductor_only_shadow_direction_label": "BEAR_SEMICONDUCTOR",
        "semiconductor_only_shadow_candidate_count": 1,
        "relaxed_broad_shadow_direction_label": "BEAR_SEMICONDUCTOR",
        "relaxed_broad_shadow_candidate_count": 1,
        "primary_wait_reason_code": "WAIT_BROAD_CONFIRMATION_MISSING",
        "secondary_wait_reason_code": "WAIT_QQQ_MIXED",
        "generated_at_utc": "2026-07-08T15:00:00Z",
    }


def cand(cid):
    return {"contract_id": cid, "underlying": "SOXS", "call_put": "CALL"}


def run(tmp_path, forward_prices=None):
    return module.run(
        tmp_path / "repo",
        execute=True,
        injected_r2_summary=r2_summary(),
        injected_strict=[],
        injected_semi=[cand("SOXS_CALL")],
        injected_relaxed=[cand("SOXS_CALL")],
        forward_prices=forward_prices,
    )


def read_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_event_ledger_append(tmp_path):
    summary = run(tmp_path)
    rows = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_event_ledger.csv")
    assert summary["event_archived"] is True
    assert len(rows) == 1
    assert rows[0]["event_id"] == summary["event_id"]


def test_duplicate_event_handling(tmp_path):
    first = run(tmp_path)
    second = run(tmp_path)
    rows = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_event_ledger.csv")
    assert first["event_id"] == second["event_id"]
    assert second["event_archived"] is False
    assert len(rows) == 1


def test_strict_wait_event_is_preserved(tmp_path):
    run(tmp_path)
    latest = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_event_latest.csv")[0]
    assert latest["strict_official_final_direction_label"] == "MIXED_OR_WAIT"
    assert latest["strict_official_wait_state"] == "True"


def test_semiconductor_shadow_event_is_preserved(tmp_path):
    run(tmp_path)
    latest = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_event_latest.csv")[0]
    assert latest["semiconductor_only_shadow_direction_label"] == "BEAR_SEMICONDUCTOR"
    assert latest["semiconductor_shadow_candidate_ids"] == "SOXS_CALL"


def test_relaxed_broad_shadow_event_is_preserved(tmp_path):
    run(tmp_path)
    latest = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_event_latest.csv")[0]
    assert latest["relaxed_broad_shadow_direction_label"] == "BEAR_SEMICONDUCTOR"
    assert latest["relaxed_shadow_candidate_ids"] == "SOXS_CALL"


def test_pending_outcome_when_forward_bars_not_available(tmp_path):
    summary = run(tmp_path)
    assert summary["final_status"] == module.PASS_PENDING_STATUS
    assert summary["pending_outcome_count"] > 0
    assert summary["completed_outcome_count"] == 0


def test_completed_outcome_when_forward_bars_available(tmp_path):
    prices = {"SOXS_CALL|15m": {"start": 1.0, "end": 1.2}}
    summary = run(tmp_path, prices)
    assert summary["final_status"] == module.PASS_UPDATED_STATUS
    assert summary["completed_outcome_count"] == 2  # semi and relaxed same candidate/mode rows
    completed = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_forward_outcome_completed.csv")
    assert all(row["outcome_status"] == "COMPLETED" for row in completed)


def test_shadow_vs_strict_scorecard_calculation(tmp_path):
    run(tmp_path, {"SOXS_CALL|15m": {"start": 1.0, "end": 1.2}})
    rows = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_shadow_vs_strict_scorecard.csv")
    semi = next(row for row in rows if row["gate_mode"] == "semiconductor_only_shadow_gate")
    assert semi["completed_outcome_count"] == "1"
    assert float(semi["average_forward_return"]) > 0


def test_no_official_promotion_from_shadow_results(tmp_path):
    run(tmp_path, {"SOXS_CALL|15m": {"start": 1.0, "end": 1.2}})
    scores = read_rows(tmp_path / "repo" / module.OUT_REL / "direction_gate_shadow_vs_strict_scorecard.csv")
    assert all(row["official_adoption_allowed"] == "False" for row in scores)


def test_safety_flags_remain_false(tmp_path):
    summary = run(tmp_path)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["research_only"] is True


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    summary = module.run(repo, execute=True, injected_r2_summary=r2_summary(), injected_semi=[cand("SOXS_CALL")], injected_relaxed=[cand("SOXS_CALL")])
    payload = json.loads((repo / module.OUT_REL / "v22_043_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in [
        "direction_gate_event_ledger.csv",
        "direction_gate_event_latest.csv",
        "direction_gate_forward_outcome_pending.csv",
        "direction_gate_forward_outcome_completed.csv",
        "direction_gate_shadow_vs_strict_scorecard.csv",
        "v22_043_summary.json",
        "V22.043_direction_gate_forward_outcome_tracker_report.txt",
    ]:
        assert (repo / module.OUT_REL / filename).exists()


def test_deterministic_final_status_and_decision(tmp_path):
    a = run(tmp_path / "a")
    b = run(tmp_path / "b")
    assert a["final_status"] == b["final_status"] == module.PASS_PENDING_STATUS
    assert a["final_decision"] == b["final_decision"] == module.PENDING_DECISION


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
