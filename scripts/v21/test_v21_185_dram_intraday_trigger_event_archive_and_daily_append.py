import json

import pandas as pd
import pytest

from scripts.v21 import v21_185_dram_intraday_trigger_event_archive_and_daily_append as m


@pytest.fixture(autouse=True)
def no_protected_scan(monkeypatch):
    monkeypatch.setattr(m.replay, "protected_hashes", lambda: {"outputs/v21/official_rankings.csv": "same"})


def write_dashboard(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def write_summary(path):
    path.write_text(json.dumps({"final_status": "PASS_V21_184_DRAM_INTRADAY_DASHBOARD_READY"}) + "\n", encoding="utf-8")


def base_row(**overrides):
    row = {
        "ticker": "DRAM",
        "plan_date": "2026-06-30",
        "latest_1m_bar_time": "2026-06-30 10:00:00",
        "entry": 69.7,
        "no_chase": 74.1,
        "stop": 63.3,
        "intraday_state_label": "ENTRY_NOT_REACHED",
        "decision_summary_label": "WAIT_ENTRY_NOT_TRIGGERED",
        "forward_status": "PARTIAL",
        "hit_entry": False,
        "hit_no_chase": False,
        "hit_stop": False,
    }
    row.update(overrides)
    return row


def run_case(tmp_path, rows, with_summary=True):
    input_dir = tmp_path / "v184"
    out = tmp_path / "out"
    dashboard = input_dir / m.DASHBOARD_NAME
    summary = input_dir / m.SUMMARY_NAME
    write_dashboard(dashboard, rows)
    if with_summary:
        write_summary(summary)
    result = m.run_stage(input_dir=input_dir, output_dir=out, asof_ts="2026-06-30T00:00:00+00:00")
    ledger = pd.read_csv(out / m.LEDGER_NAME)
    return result, ledger, dashboard, out


def test_missing_dashboard_returns_fail_and_exit_code_1(tmp_path):
    input_dir = tmp_path / "missing"
    out = tmp_path / "out"
    summary = m.run_stage(input_dir=input_dir, output_dir=out)
    assert summary["final_status"] == m.FINAL_FAIL_MISSING_DASHBOARD
    assert m.main(["--input-dir", str(input_dir), "--output-dir", str(tmp_path / "out2")]) == 1


def test_pending_forward_data_returns_partial_pass_and_exit_code_0(tmp_path):
    input_dir = tmp_path / "v184"
    out = tmp_path / "out"
    write_dashboard(input_dir / m.DASHBOARD_NAME, [base_row(intraday_state_label="PENDING_FORWARD_DATA", forward_status="PENDING_FORWARD_DATA")])
    write_summary(input_dir / m.SUMMARY_NAME)
    assert m.main(["--input-dir", str(input_dir), "--output-dir", str(out)]) == 0
    summary = json.loads((out / m.SUMMARY_OUT_NAME).read_text())
    assert summary["final_status"] == m.FINAL_PARTIAL_WAIT
    assert summary["latest_event_type"] == "WAIT_FORWARD_DATA"
    assert summary["latest_event_state_label"] == "PENDING_FORWARD_DATA"


def test_complete_forward_row_returns_pass_and_complete_event(tmp_path):
    summary, ledger, _, _ = run_case(tmp_path, [base_row(forward_status="COMPLETE", intraday_state_label="COMPLETE_OUTCOME_AVAILABLE")])
    assert summary["final_status"] == m.FINAL_PASS
    assert ledger.iloc[-1]["event_type"] == "ENTRY_AND_FORWARD_COMPLETE"
    assert ledger.iloc[-1]["event_state_label"] == "COMPLETE"


def test_existing_ledger_is_preserved_and_appended(tmp_path):
    summary1, ledger1, _, out = run_case(tmp_path, [base_row(plan_date="2026-06-30")])
    assert len(ledger1) == 1
    input_dir = tmp_path / "v184"
    write_dashboard(input_dir / m.DASHBOARD_NAME, [base_row(plan_date="2026-07-01", latest_1m_bar_time="2026-07-01 10:00:00", hit_entry=True)])
    summary2 = m.run_stage(input_dir=input_dir, output_dir=out)
    ledger2 = pd.read_csv(out / m.LEDGER_NAME)
    assert summary1["final_ledger_rows"] == 1
    assert summary2["previous_ledger_rows"] == 1
    assert summary2["appended_event_rows"] == 1
    assert len(ledger2) == 2


def test_duplicate_rerun_does_not_duplicate_rows(tmp_path):
    summary1, _, _, out = run_case(tmp_path, [base_row()])
    input_dir = tmp_path / "v184"
    summary2 = m.run_stage(input_dir=input_dir, output_dir=out)
    ledger = pd.read_csv(out / m.LEDGER_NAME)
    assert summary1["final_ledger_rows"] == 1
    assert summary2["duplicate_rows_removed"] == 1
    assert summary2["appended_event_rows"] == 0
    assert len(ledger) == 1


def test_original_v21_184_dashboard_is_not_mutated(tmp_path):
    _, _, dashboard, out = run_case(tmp_path, [base_row()])
    before = dashboard.read_bytes()
    m.run_stage(input_dir=tmp_path / "v184", output_dir=out)
    assert dashboard.read_bytes() == before


def test_missing_summary_json_proceeds_with_warning(tmp_path):
    summary, ledger, _, _ = run_case(tmp_path, [base_row()], with_summary=False)
    assert len(ledger) == 1
    assert summary["warning_count"] == 1
    assert "summary JSON missing" in summary["warnings"][0]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("TRUE", "ENTRY_TOUCH"),
        ("true", "ENTRY_TOUCH"),
        ("1", "ENTRY_TOUCH"),
        ("yes", "ENTRY_TOUCH"),
        ("FALSE", "NO_TRIGGER"),
        ("false", "NO_TRIGGER"),
        ("0", "NO_TRIGGER"),
        ("no", "NO_TRIGGER"),
    ],
)
def test_boolean_like_strings_are_parsed_correctly(tmp_path, value, expected):
    _, ledger, _, _ = run_case(tmp_path, [base_row(hit_entry=value, intraday_state_label="", forward_status="")])
    assert ledger.iloc[-1]["event_type"] == expected


def test_unknown_state_is_classified_unknown(tmp_path):
    row = {
        "ticker": "DRAM",
        "plan_date": "2026-06-30",
        "observed_bar_time": "2026-06-30 10:00:00",
        "latest_intraday_state_label": "STRANGE_STATE",
    }
    _, ledger, _, _ = run_case(tmp_path, [row])
    assert ledger.iloc[-1]["event_type"] == "UNKNOWN_EVENT_STATE"
    assert ledger.iloc[-1]["event_state_label"] == "UNKNOWN"


def test_policy_flags_are_always_research_only(tmp_path):
    summary, ledger, _, _ = run_case(
        tmp_path,
        [
            base_row(
                research_only=False,
                broker_action_allowed=True,
                official_adoption_allowed=True,
                protected_outputs_modified=True,
            )
        ],
    )
    assert summary["research_only"] is True
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False
    assert bool(ledger.iloc[-1]["research_only"]) is True
    assert bool(ledger.iloc[-1]["broker_action_allowed"]) is False
    assert bool(ledger.iloc[-1]["official_adoption_allowed"]) is False
    assert bool(ledger.iloc[-1]["protected_outputs_modified"]) is False
