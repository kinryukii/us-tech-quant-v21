import pandas as pd

from scripts.v21 import v21_183_dram_intraday_forward_outcome_updater as m


def bars(path, n=70, start="2026-06-29 15:38:00", base=100.0, step=0.1):
    times = pd.date_range(start, periods=n, freq="min")
    close = [base + i * step for i in range(n)]
    pd.DataFrame(
        {
            "datetime": times,
            "ticker": "DRAM",
            "open": close,
            "high": [x + 0.2 for x in close],
            "low": [x - 0.2 for x in close],
            "close": close,
            "volume": [1000] * n,
        }
    ).to_csv(path, index=False)


def ledger(path, state="WAIT_H1_CONFIRMATION", price=100.0):
    pd.DataFrame(
        [
            {
                "snapshot_run_id": "abc123",
                "ticker": "DRAM",
                "latest_completed_bar_end": "2026-06-29 15:38:00",
                "latest_completed_price": price,
                "execution_state": state,
                "active_gate": "ENTRY" if state == "ENTRY_ALLOWED" else "H1",
                "entry": 99.0,
                "no_chase": 104.0,
                "stop": 97.0,
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
        ]
    ).to_csv(path, index=False)


def complete_ledger(path):
    pd.DataFrame(
        [
            {
                "snapshot_run_id": "complete1",
                "ticker": "DRAM",
                "latest_completed_bar_end": "2026-06-29 15:38:00",
                "latest_completed_price": 100.0,
                "execution_state": "ENTRY_ALLOWED",
                "entry": 99.0,
                "no_chase": 104.0,
                "stop": 97.0,
                "forward_30m_return": 0.123,
                "forward_60m_return": 0.234,
                "eod_return": 0.345,
                "next_day_return": 0.456,
                "outcome_status": "COMPLETE",
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
        ]
    ).to_csv(path, index=False)


def test_future_bars_only_and_no_same_bar_leakage(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=31)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert df.iloc[0]["forward_30m_return"] > 0
    assert abs(df.iloc[0]["forward_30m_return"] - ((100.0 + 30 * 0.1) / 100.0 - 1)) < 1e-9


def test_partial_30m_fill_pending_60m(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=31)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert pd.notna(df.iloc[0]["forward_30m_return"])
    assert pd.isna(df.iloc[0]["forward_60m_return"])
    assert df.iloc[0]["outcome_status"] == "PARTIAL_30M_AVAILABLE_PENDING_60M"


def test_pending_60m_handling(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=20)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert pd.isna(df.iloc[0]["forward_30m_return"])
    assert df.iloc[0]["outcome_status"] == "PENDING_FORWARD_DATA"


def test_eod_outcome_calculation(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=70)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert pd.notna(df.iloc[0]["eod_return"])


def test_next_day_return_calculated_when_next_day_bars_exist(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    first = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-06-29 15:38:00", periods=70, freq="min"),
            "ticker": "DRAM",
            "open": [100 + i * 0.1 for i in range(70)],
            "high": [100.2 + i * 0.1 for i in range(70)],
            "low": [99.8 + i * 0.1 for i in range(70)],
            "close": [100 + i * 0.1 for i in range(70)],
            "volume": [1000] * 70,
        }
    )
    second = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-06-30 13:30:00", periods=3, freq="min"),
            "ticker": "DRAM",
            "open": [110, 111, 112],
            "high": [110.2, 111.2, 112.2],
            "low": [109.8, 110.8, 111.8],
            "close": [110, 111, 112],
            "volume": [1000, 1000, 1000],
        }
    )
    pd.concat([first, second], ignore_index=True).to_csv(b, index=False)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert abs(df.iloc[0]["next_day_return"] - 0.12) < 1e-9


def test_stop_no_chase_hit_detection(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=70, step=0.2)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert bool(df.iloc[0]["hit_no_chase_after_snapshot"]) is True
    assert bool(df.iloc[0]["hit_stop_after_snapshot"]) is False


def test_wait_state_correctness_flag_logic(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=70, step=-0.01)
    ledger(l, state="WAIT_15M_SETUP")
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert bool(df.iloc[0]["wait_state_was_correct_flag"]) is True
    assert bool(df.iloc[0]["missed_move_flag"]) is False


def test_entry_allowed_followthrough_flag_logic(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=70, step=0.1)
    ledger(l, state="ENTRY_ALLOWED")
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert bool(df.iloc[0]["entry_allowed_followthrough_flag"]) is True
    assert bool(df.iloc[0]["broker_action_allowed"]) is False


def test_protected_output_mutation_guard(monkeypatch, tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b)
    ledger(l)
    calls = {"n": 0}

    def fake_hashes():
        calls["n"] += 1
        return {"outputs/v21/official_rankings.csv": "before" if calls["n"] == 1 else "after"}

    monkeypatch.setattr(m.replay, "protected_hashes", fake_hashes)
    manifest = m.run_stage(tmp_path / "out", l, b)
    assert manifest["final_status"] == m.FINAL_FAIL
    assert manifest["protected_outputs_modified"] is True


def test_fail_status_exits_nonzero(monkeypatch):
    monkeypatch.setattr(m, "run_stage", lambda: {"final_status": m.FINAL_FAIL})
    assert m.main() == 1


def test_broker_action_allowed_remains_false(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b)
    ledger(l)
    out = tmp_path / "out"
    manifest = m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert manifest["broker_action_allowed"] is False
    assert bool(df.iloc[0]["broker_action_allowed"]) is False


def test_empty_ledger_warns_no_rows_to_update(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b)
    pd.DataFrame().to_csv(l, index=False)
    manifest = m.run_stage(tmp_path / "out", l, b)
    assert manifest["final_status"] == m.FINAL_WARN


def test_no_future_bars_produces_pending_forward_data(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=1)
    ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert df.iloc[0]["outcome_status"] == "PENDING_FORWARD_DATA"


def test_existing_complete_rows_not_overwritten(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=90, step=1)
    complete_ledger(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    df = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert df.iloc[0]["forward_30m_return"] == 0.123
    assert df.iloc[0]["outcome_status"] == "COMPLETE"


def test_original_v21_182_columns_preserved_in_derived_ledger(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b)
    ledger(l)
    original = pd.read_csv(l)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    derived = pd.read_csv(out / "dram_intraday_forward_tracking_ledger_with_outcomes.csv")
    assert set(original.columns).issubset(set(derived.columns))


def test_original_input_ledger_not_modified(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b)
    ledger(l)
    before = l.read_bytes()
    m.run_stage(tmp_path / "out", l, b)
    assert l.read_bytes() == before


def test_pending_rows_output_only_contains_pending_status(tmp_path):
    b = tmp_path / "bars.csv"
    l = tmp_path / "ledger.csv"
    bars(b, n=31)
    wait = pd.read_csv(l) if l.exists() else pd.DataFrame()
    ledger(l)
    existing = pd.read_csv(l)
    complete = existing.copy()
    complete["snapshot_run_id"] = "complete2"
    complete["latest_completed_bar_end"] = "2026-06-29 15:39:00"
    complete["forward_30m_return"] = 0.1
    complete["forward_60m_return"] = 0.2
    complete["eod_return"] = 0.3
    complete["next_day_return"] = 0.4
    complete["outcome_status"] = "COMPLETE"
    pd.concat([existing, complete], ignore_index=True).to_csv(l, index=False)
    out = tmp_path / "out"
    m.run_stage(out, l, b)
    pending = pd.read_csv(out / "dram_intraday_forward_pending_rows.csv")
    assert not pending.empty
    assert pending["outcome_status"].astype(str).str.contains("PENDING").all()
