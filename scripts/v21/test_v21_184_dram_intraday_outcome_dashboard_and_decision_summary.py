import json

import pandas as pd

from scripts.v21 import v21_184_dram_intraday_outcome_dashboard_and_decision_summary as m


def write_ledger(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def base_row(**overrides):
    row = {
        "plan_date": "2026-06-30",
        "snapshot_time": "2026-06-30 10:00:00",
        "ticker": "DRAM",
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "latest_1m_bar_time": "2026-06-30 10:01:00",
        "latest_1m_close": 70.0,
        "forward_status": "COMPLETE",
        "hit_entry": False,
        "hit_no_chase": False,
        "hit_stop": False,
        "max_favorable_move": 0.02,
        "max_adverse_move": -0.01,
    }
    row.update(overrides)
    return row


def run_with_row(tmp_path, row, strict=False):
    ledger = tmp_path / "ledger.csv"
    out = tmp_path / "out"
    write_ledger(ledger, [row])
    summary = m.run_stage(ledger, out, "2026-06-30T00:00:00+00:00", strict=strict)
    dashboard = pd.read_csv(out / "dram_intraday_outcome_dashboard.csv")
    return summary, dashboard, out, ledger


def test_happy_path_with_complete_row(tmp_path):
    summary, dashboard, _, _ = run_with_row(tmp_path, base_row())
    assert summary["final_status"] == m.FINAL_PASS
    assert summary["final_decision"] == m.DECISION_READY
    assert dashboard.iloc[0]["intraday_state_label"] == "COMPLETE_OUTCOME_AVAILABLE"
    assert dashboard.iloc[0]["decision_summary_label"] == "OUTCOME_COMPLETE_REVIEW_ONLY"


def test_pending_forward_data_row(tmp_path):
    summary, dashboard, _, _ = run_with_row(tmp_path, base_row(forward_status="PENDING_FORWARD_DATA"))
    assert summary["final_decision"] == m.DECISION_WAIT
    assert dashboard.iloc[0]["intraday_state_label"] == "PENDING_FORWARD_DATA"
    assert dashboard.iloc[0]["decision_summary_label"] == "WAIT_FOR_FORWARD_DATA"


def test_hit_entry_true_maps_to_entry_zone(tmp_path):
    _, dashboard, _, _ = run_with_row(tmp_path, base_row(forward_status="PARTIAL", hit_entry=True))
    assert dashboard.iloc[0]["intraday_state_label"] == "ENTRY_TOUCHED_ACTIVE"
    assert dashboard.iloc[0]["decision_summary_label"] == "ENTRY_ZONE_ACTIVE_RESEARCH_ONLY"


def test_hit_no_chase_true_maps_to_do_not_chase(tmp_path):
    _, dashboard, _, _ = run_with_row(tmp_path, base_row(forward_status="PARTIAL", hit_entry=True, hit_no_chase=True))
    assert dashboard.iloc[0]["intraday_state_label"] == "NO_CHASE_TOUCHED"
    assert dashboard.iloc[0]["decision_summary_label"] == "NO_CHASE_ZONE_REACHED_DO_NOT_CHASE_RESEARCH_ONLY"


def test_hit_stop_true_maps_to_stop_risk(tmp_path):
    _, dashboard, _, _ = run_with_row(tmp_path, base_row(forward_status="PARTIAL", hit_no_chase=True, hit_stop=True))
    assert dashboard.iloc[0]["intraday_state_label"] == "STOP_TOUCHED"
    assert dashboard.iloc[0]["decision_summary_label"] == "STOP_RISK_TRIGGERED_RESEARCH_ONLY"


def test_latest_close_below_entry_maps_to_wait_entry(tmp_path):
    _, dashboard, _, _ = run_with_row(tmp_path, base_row(forward_status="PARTIAL", latest_1m_close=68.0))
    assert dashboard.iloc[0]["intraday_state_label"] == "ENTRY_NOT_REACHED"
    assert dashboard.iloc[0]["decision_summary_label"] == "WAIT_ENTRY_NOT_TRIGGERED"


def test_missing_latest_close_produces_nan_distances_and_warning(tmp_path):
    row = base_row()
    row.pop("latest_1m_close")
    summary, dashboard, _, _ = run_with_row(tmp_path, row)
    assert pd.isna(dashboard.iloc[0]["distance_to_entry_pct"])
    assert any("latest_1m_close missing" in warning for warning in summary["warnings"])


def test_missing_optional_columns_do_not_crash(tmp_path):
    row = {
        "ticker": "DRAM",
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "forward_status": "COMPLETE",
    }
    summary, dashboard, _, _ = run_with_row(tmp_path, row)
    assert len(dashboard) == 1
    assert summary["final_status"] == m.FINAL_PARTIAL
    assert any("plan_date missing" in warning for warning in summary["warnings"])


def test_strict_mode_fails_when_required_core_columns_missing(tmp_path):
    ledger = tmp_path / "ledger.csv"
    out = tmp_path / "out"
    write_ledger(ledger, [{"ticker": "DRAM", "entry": 1.0}])
    summary = m.run_stage(ledger, out, strict=True)
    assert summary["final_status"] == m.FINAL_FAIL_SCHEMA
    assert m.main(["--input-ledger", str(ledger), "--output-dir", str(tmp_path / "out2"), "--strict"]) == 1


def test_no_input_ledger_found_returns_fail_exit_code_1(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "discover_latest_ledger", lambda: None)
    out = tmp_path / "out"
    assert m.main(["--output-dir", str(out)]) == 1
    summary = json.loads((out / "v21_184_summary.json").read_text())
    assert summary["final_status"] == m.FINAL_FAIL_NOT_FOUND


def test_empty_ledger_returns_warn_and_exit_code_0(tmp_path):
    ledger = tmp_path / "empty.csv"
    ledger.write_text("", encoding="utf-8")
    out = tmp_path / "out"
    summary = m.run_stage(ledger, out)
    assert summary["final_status"] == m.FINAL_WARN_NO_ROWS
    assert m.main(["--input-ledger", str(ledger), "--output-dir", str(tmp_path / "out2")]) == 0


def test_output_csv_json_and_report_are_created(tmp_path):
    summary, _, out, _ = run_with_row(tmp_path, base_row())
    assert (out / "dram_intraday_outcome_dashboard.csv").exists()
    assert (out / "v21_184_summary.json").exists()
    assert (out / "V21.184_dram_intraday_outcome_dashboard_report.txt").exists()
    assert json.loads((out / "v21_184_summary.json").read_text())["final_status"] == summary["final_status"]


def test_governance_fields_are_research_only(tmp_path):
    summary, dashboard, _, _ = run_with_row(tmp_path, base_row())
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert bool(dashboard.iloc[0]["action_allowed_research_only"]) is True
    assert bool(dashboard.iloc[0]["broker_action_allowed"]) is False


def test_source_ledger_is_not_mutated(tmp_path):
    _, _, _, ledger = run_with_row(tmp_path, base_row())
    before = ledger.read_bytes()
    m.run_stage(ledger, tmp_path / "out_again")
    assert ledger.read_bytes() == before


def test_original_source_protected_outputs_are_not_modified(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_hashes():
        calls["n"] += 1
        return {"outputs/v21/official_rankings.csv": "same"}

    monkeypatch.setattr(m.replay, "protected_hashes", fake_hashes)
    summary, dashboard, _, _ = run_with_row(tmp_path, base_row())
    assert calls["n"] >= 2
    assert summary["protected_outputs_modified"] is False
    assert bool(dashboard.iloc[0]["protected_outputs_modified"]) is False


def test_v183_alias_columns_are_accepted(tmp_path):
    row = {
        "ticker": "DRAM",
        "latest_completed_bar_end": "2026-06-29 15:38:00",
        "latest_completed_price": 69.25,
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "plan_date": "2026-06-29",
        "outcome_status": "PENDING_FORWARD_DATA",
        "hit_no_chase_after_snapshot": False,
        "hit_stop_after_snapshot": False,
        "entry_allowed_followthrough_flag": False,
    }
    summary, dashboard, _, _ = run_with_row(tmp_path, row)
    assert summary["latest_forward_status"] == "PENDING_FORWARD_DATA"
    assert dashboard.iloc[0]["latest_1m_bar_time"] == "2026-06-29 15:38:00"
