from __future__ import annotations

import ast
import csv
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_043_r1a_forward_outcome_data_fetch_and_maturity_updater.py")
SPEC = importlib.util.spec_from_file_location("v22_043_r1a", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_csv(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def setup_source(repo: Path, event_ts="2026-07-08T15:00:00Z"):
    root = repo / module.V22_043_REL
    event = {"event_id": "E1", "event_timestamp": event_ts, "event_market_date": event_ts[:10]}
    write_csv(root / "direction_gate_event_ledger.csv", ["event_id", "event_timestamp", "event_market_date"], [event])
    pending = []
    for horizon in ["15m", "30m", "60m", "120m", "end_of_session", "next_completed_session"]:
        pending.append({"event_id": "E1", "gate_mode": "semiconductor_only_shadow_gate", "target_type": "underlying", "target_id": "SOXX", "horizon": horizon, "event_timestamp": event_ts, "due_timestamp": "", "start_price": "", "end_price": "", "forward_return": "", "outcome_status": "PENDING_FORWARD_DATA", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
    pending.append({"event_id": "E1", "gate_mode": "semiconductor_only_shadow_gate", "target_type": "option_candidate", "target_id": "SOXS_CALL", "horizon": "15m", "event_timestamp": event_ts, "due_timestamp": "", "start_price": "", "end_price": "", "forward_return": "", "outcome_status": "PENDING_FORWARD_DATA", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
    pending.append({"event_id": "E1", "gate_mode": "relaxed_broad_shadow_gate", "target_type": "option_candidate", "target_id": "SOXS_CALL", "horizon": "15m", "event_timestamp": event_ts, "due_timestamp": "", "start_price": "", "end_price": "", "forward_return": "", "outcome_status": "PENDING_FORWARD_DATA", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
    write_csv(root / "direction_gate_forward_outcome_pending.csv", module.OUTCOME_FIELDS, pending)
    write_csv(root / "direction_gate_forward_outcome_completed.csv", module.OUTCOME_FIELDS, [])


def read_rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_duplicate_event_is_not_rearchived_scope(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    summary = module.run(repo, execute=False)
    assert summary["event_count_evaluated"] == 1
    assert len(read_rows(repo / module.V22_043_REL / "direction_gate_event_ledger.csv")) == 1


def test_utc_to_us_eastern_timestamp_conversion():
    et = module.utc_to_et("2026-07-08T18:55:01Z")
    assert et is not None
    assert et.tzinfo is not None
    assert et.hour == 14
    assert et.minute == 55


def test_15_30_60_120_maturity_checks():
    event_et = module.utc_to_et("2026-07-08T15:00:00Z")
    now = module.utc_to_et("2026-07-08T16:01:00Z")
    assert all(module.is_mature(event_et, h, now)[0] for h in ["15m", "30m", "60m"])
    assert module.is_mature(event_et, "120m", now)[0] is False


def test_end_of_session_maturity_check():
    event_et = module.utc_to_et("2026-07-08T15:00:00Z")
    assert module.is_mature(event_et, "end_of_session", module.utc_to_et("2026-07-08T19:59:00Z"))[0] is False
    assert module.is_mature(event_et, "end_of_session", module.utc_to_et("2026-07-08T20:01:00Z"))[0] is True


def test_next_session_maturity_check():
    event_et = module.utc_to_et("2026-07-08T15:00:00Z")
    assert module.is_mature(event_et, "next_completed_session", module.utc_to_et("2026-07-09T19:59:00Z"))[0] is False
    assert module.is_mature(event_et, "next_completed_session", module.utc_to_et("2026-07-09T20:01:00Z"))[0] is True


def test_missing_bars_remain_pending(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    summary = module.run(repo, execute=False, now_utc=datetime(2026, 7, 8, 17, 30, tzinfo=timezone.utc))
    assert summary["newly_completed_outcome_count"] == 0
    assert summary["remaining_pending_outcome_count"] > 0
    assert summary["primary_unavailable_reason"] in {"FORWARD_BARS_MISSING", "MARKET_SESSION_NOT_COMPLETED"}


def test_available_bars_complete_outcomes(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    bars = {"SOXX": [{"time": "2026-07-08T11:00:00-04:00", "time_et": module.utc_to_et("2026-07-08T15:00:00Z"), "close": 100}, {"time": "2026-07-08T11:15:00-04:00", "time_et": module.utc_to_et("2026-07-08T15:15:00Z"), "close": 101}]}
    summary = module.run(repo, execute=False, injected_bars=bars, now_utc=datetime(2026, 7, 8, 15, 20, tzinfo=timezone.utc))
    assert summary["newly_completed_outcome_count"] >= 1
    assert summary["forward_data_available"] is True


def test_unavailable_reason_classification(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo, event_ts="bad")
    summary = module.run(repo, execute=False)
    assert summary["primary_unavailable_reason"] == "EVENT_TIMEZONE_ALIGNMENT_ISSUE"


def test_scorecard_only_when_comparable_completed_outcomes_exist(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    bars = {"SOXS_CALL": [{"time": "2026-07-08T11:00:00-04:00", "time_et": module.utc_to_et("2026-07-08T15:00:00Z"), "close": 1.0}, {"time": "2026-07-08T11:15:00-04:00", "time_et": module.utc_to_et("2026-07-08T15:15:00Z"), "close": 1.2}]}
    summary = module.run(repo, execute=False, injected_bars=bars, now_utc=datetime(2026, 7, 8, 15, 20, tzinfo=timezone.utc))
    assert summary["scorecard_available"] is True


def test_safety_flags_remain_false(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    summary = module.run(repo, execute=False)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["trade_context_used"] is False
    assert summary["unlock_trade_called"] is False
    assert summary["place_order_called"] is False
    assert summary["research_only"] is True


def test_summary_schema_stability(tmp_path):
    repo = tmp_path / "repo"
    setup_source(repo)
    summary = module.run(repo, execute=False)
    payload = json.loads((repo / module.OUT_REL / "v22_043_r1a_summary.json").read_text(encoding="utf-8"))
    for field in module.SUMMARY_FIELDS:
        assert field in summary
        assert field in payload
    for filename in ["forward_outcome_maturity_audit.csv", "forward_bar_fetch_audit.csv", "forward_outcome_pending_updated.csv", "forward_outcome_completed_updated.csv", "shadow_vs_strict_scorecard_updated.csv", "v22_043_r1a_summary.json", "V22.043_R1A_forward_outcome_data_fetch_and_maturity_updater_report.txt"]:
        assert (repo / module.OUT_REL / filename).exists()


def test_deterministic_final_status_and_decision(tmp_path):
    repo_a = tmp_path / "a" / "repo"
    repo_b = tmp_path / "b" / "repo"
    setup_source(repo_a)
    setup_source(repo_b)
    a = module.run(repo_a, execute=False, now_utc=datetime(2026, 7, 8, 15, 1, tzinfo=timezone.utc))
    b = module.run(repo_b, execute=False, now_utc=datetime(2026, 7, 8, 15, 1, tzinfo=timezone.utc))
    assert a["final_status"] == b["final_status"]
    assert a["final_decision"] == b["final_decision"]


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
