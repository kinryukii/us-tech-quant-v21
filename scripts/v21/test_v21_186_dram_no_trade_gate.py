import json

import pandas as pd
import pytest

from scripts.v21 import v21_186_dram_no_trade_gate as m


@pytest.fixture(autouse=True)
def no_protected_scan(monkeypatch):
    monkeypatch.setattr(m.replay, "protected_hashes", lambda: {"outputs/v21/official_rankings.csv": "same"})


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def event_row(**overrides):
    row = {
        "ticker": "DRAM",
        "plan_date": "2026-06-30",
        "observed_bar_time": "2026-06-30 10:00:00",
        "event_type": "NO_TRIGGER",
        "event_state_label": "NO_TRIGGER",
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "entry_touched": False,
        "no_chase_touched": False,
        "stop_touched": False,
        "forward_complete": False,
        "source_latest_1m_close": 68.5,
    }
    row.update(overrides)
    return row


def dashboard_row(**overrides):
    row = {
        "ticker": "DRAM",
        "plan_date": "2026-06-30",
        "latest_1m_bar_time": "2026-06-30 10:00:00",
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "latest_1m_close": 68.5,
        "intraday_state_label": "ENTRY_NOT_REACHED",
        "decision_summary_label": "WAIT_ENTRY_NOT_TRIGGERED",
    }
    row.update(overrides)
    return row


def plan_row(**overrides):
    row = {
        "ticker": "DRAM",
        "plan_date": "2026-06-30",
        "trade_plan_currentness": "CURRENT",
        "trade_allowed_current": True,
        "dram_entry": 69.7,
        "dram_no_chase": 74.1,
        "dram_stop": 63.3,
    }
    row.update(overrides)
    return row


def setup_inputs(tmp_path, event=None, dashboard=None, plan=None, with_dashboard=True):
    v185 = tmp_path / "v185"
    v184 = tmp_path / "v184"
    plan_dir = tmp_path / "plan"
    out = tmp_path / "out"
    write_csv(v185 / m.V185_LEDGER_NAME, [event or event_row()])
    write_json(v185 / m.V185_SUMMARY_NAME, {"final_status": "PASS"})
    if with_dashboard:
        write_csv(v184 / m.V184_DASHBOARD_NAME, [dashboard or dashboard_row()])
        write_json(v184 / m.V184_SUMMARY_NAME, {"final_status": "PASS"})
    if plan is not None:
        write_csv(plan_dir / m.PLAN_CSV_NAME, [plan])
    else:
        write_csv(plan_dir / m.PLAN_CSV_NAME, [plan_row()])
    return v185, v184, plan_dir, out


def run_case(tmp_path, event=None, dashboard=None, plan=None, with_dashboard=True):
    v185, v184, plan_dir, out = setup_inputs(tmp_path, event, dashboard, plan, with_dashboard)
    summary = m.run_stage(v185, v184, plan_dir, out, "2026-06-30T00:00:00+00:00")
    latest = pd.read_csv(out / m.LATEST_NAME)
    return summary, latest, v185, v184


def test_missing_v21_185_ledger_returns_fail_and_exit_code_1(tmp_path):
    v185 = tmp_path / "v185"
    v184 = tmp_path / "v184"
    plan_dir = tmp_path / "plan"
    out = tmp_path / "out"
    summary = m.run_stage(v185, v184, plan_dir, out)
    assert summary["final_status"] == m.FINAL_FAIL_MISSING_LEDGER
    assert m.main(["--v185-dir", str(v185), "--v184-dir", str(v184), "--plan-dir", str(plan_dir), "--output-dir", str(tmp_path / "out2")]) == 1


def test_pending_forward_data_returns_partial_pass_and_no_trade(tmp_path):
    event = event_row(event_type="WAIT_FORWARD_DATA", event_state_label="PENDING_FORWARD_DATA", outcome_status="PENDING_FORWARD_DATA")
    summary, latest, _, _ = run_case(tmp_path, event=event)
    assert summary["final_status"] == m.FINAL_PARTIAL_WAIT
    assert summary["final_decision"] == m.DECISION_WAIT
    assert summary["no_trade_gate_label"] == "NO_TRADE_PENDING_FORWARD_DATA_RESEARCH_ONLY"
    assert latest.iloc[0]["gate_state"] == "BLOCK_RESEARCH_ONLY"


def test_stale_plan_returns_stale_no_trade(tmp_path):
    summary, _, _, _ = run_case(tmp_path, plan=plan_row(trade_plan_currentness="STALE"))
    assert summary["no_trade_gate_label"] == "NO_TRADE_STALE_PLAN_RESEARCH_ONLY"


def test_stop_touched_or_price_below_stop_returns_stop_breach(tmp_path):
    summary1, _, _, _ = run_case(tmp_path / "a", event=event_row(stop_touched="true"))
    summary2, _, _, _ = run_case(tmp_path / "b", event=event_row(source_latest_1m_close=60.0))
    assert summary1["no_trade_gate_label"] == "NO_TRADE_STOP_BREACH_RESEARCH_ONLY"
    assert summary2["no_trade_gate_label"] == "NO_TRADE_STOP_BREACH_RESEARCH_ONLY"


def test_no_chase_touched_or_price_above_no_chase_returns_breach(tmp_path):
    summary1, _, _, _ = run_case(tmp_path / "a", event=event_row(no_chase_touched="true"))
    summary2, _, _, _ = run_case(tmp_path / "b", event=event_row(source_latest_1m_close=80.0))
    assert summary1["no_trade_gate_label"] == "NO_TRADE_NO_CHASE_BREACH_RESEARCH_ONLY"
    assert summary2["no_trade_gate_label"] == "NO_TRADE_NO_CHASE_BREACH_RESEARCH_ONLY"


def test_structure_broken_returns_structure_broken(tmp_path):
    summary1, _, _, _ = run_case(tmp_path / "a", event=event_row(structure_broken="yes"))
    summary2, _, _, _ = run_case(tmp_path / "b", event=event_row(structure_status="BROKEN"))
    assert summary1["no_trade_gate_label"] == "NO_TRADE_STRUCTURE_BROKEN_RESEARCH_ONLY"
    assert summary2["no_trade_gate_label"] == "NO_TRADE_STRUCTURE_BROKEN_RESEARCH_ONLY"


def test_entry_touched_but_not_complete_returns_wait_confirmation(tmp_path):
    summary, _, _, _ = run_case(tmp_path, event=event_row(event_type="ENTRY_TOUCH", event_state_label="WAIT_CONFIRMATION", entry_touched=True))
    assert summary["no_trade_gate_label"] == "WAIT_CONFIRMATION_RESEARCH_ONLY"
    assert summary["gate_state"] == "WAIT_RESEARCH_ONLY"


def test_current_plan_valid_price_can_allow_limit_entry(tmp_path):
    summary, _, _, _ = run_case(tmp_path, event=event_row(source_latest_1m_close=68.0))
    assert summary["no_trade_gate_label"] == "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY"
    assert summary["gate_state"] == "ALLOW_RESEARCH_ONLY"


def test_pullback_only_case_returns_pullback_only(tmp_path):
    summary, _, _, _ = run_case(tmp_path, event=event_row(source_latest_1m_close=71.0))
    assert summary["no_trade_gate_label"] == "ALLOW_PULLBACK_ONLY_RESEARCH_ONLY"
    assert summary["gate_state"] == "ALLOW_RESEARCH_ONLY"


def test_unknown_state_returns_no_trade_unknown(tmp_path):
    event = {"ticker": "DRAM", "event_type": "", "event_state_label": "", "entry": 69.7, "no_chase": 74.1, "stop": 63.3}
    summary, _, _, _ = run_case(tmp_path, event=event)
    assert summary["no_trade_gate_label"] == "NO_TRADE_UNKNOWN_STATE_RESEARCH_ONLY"
    assert summary["gate_state"] == "BLOCK_RESEARCH_ONLY"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("TRUE", "WAIT_CONFIRMATION_RESEARCH_ONLY"),
        ("true", "WAIT_CONFIRMATION_RESEARCH_ONLY"),
        ("1", "WAIT_CONFIRMATION_RESEARCH_ONLY"),
        ("yes", "WAIT_CONFIRMATION_RESEARCH_ONLY"),
        ("FALSE", "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY"),
        ("false", "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY"),
        ("0", "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY"),
        ("no", "ALLOW_LIMIT_ENTRY_RESEARCH_ONLY"),
    ],
)
def test_boolean_like_strings_are_parsed_correctly(tmp_path, value, expected):
    summary, _, _, _ = run_case(tmp_path, event=event_row(entry_touched=value, event_type="NO_TRIGGER", event_state_label="NO_TRIGGER", source_latest_1m_close=68.0))
    assert summary["no_trade_gate_label"] == expected


def test_original_v21_184_and_v21_185_inputs_are_not_mutated(tmp_path):
    summary, _, v185, v184 = run_case(tmp_path)
    paths = [v185 / m.V185_LEDGER_NAME, v185 / m.V185_SUMMARY_NAME, v184 / m.V184_DASHBOARD_NAME, v184 / m.V184_SUMMARY_NAME]
    before = {path: path.read_bytes() for path in paths}
    m.run_stage(v185, v184, tmp_path / "plan", tmp_path / "out_again")
    assert summary["final_status"] == m.FINAL_PASS
    assert {path: path.read_bytes() for path in paths} == before


def test_policy_flags_are_always_research_only(tmp_path):
    event = event_row(research_only=False, broker_action_allowed=True, official_adoption_allowed=True, protected_outputs_modified=True)
    summary, latest, _, _ = run_case(tmp_path, event=event)
    assert summary["research_only"] is True
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert bool(latest.iloc[0]["research_only"]) is True
    assert bool(latest.iloc[0]["broker_action_allowed"]) is False
    assert bool(latest.iloc[0]["official_adoption_allowed"]) is False
    assert bool(latest.iloc[0]["protected_outputs_modified"]) is False


def test_missing_v21_184_dashboard_proceeds_with_warning_if_v185_ledger_exists(tmp_path):
    summary, _, _, _ = run_case(tmp_path, with_dashboard=False)
    assert summary["final_status"] == m.FINAL_PASS
    assert any("dashboard missing" in warning for warning in summary["warnings"])
