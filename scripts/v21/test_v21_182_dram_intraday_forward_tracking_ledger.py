import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_182_dram_intraday_forward_tracking_ledger as m


def snapshot(path: Path, state="WAIT_H1_CONFIRMATION"):
    payload = {
        "stage": "V21.180_DRAM_INTRADAY_CONFIRMATION_SNAPSHOT_RUNNER",
        "execution_state": state,
        "latest_completed_bar_end": "2026-06-29 15:38:00",
        "latest_completed_price": 69.25,
        "DRAM_ENTRY": 69.7,
        "DRAM_NO_CHASE": 74.0,
        "DRAM_STOP": 63.0,
        "latest_price_date_used": "2026-06-29",
        "plan_date": "2026-06-29",
        "trade_plan_currentness": "CURRENT",
        "h1_signal": "H1_NEUTRAL_WAIT" if state == "WAIT_H1_CONFIRMATION" else "H1_BULLISH_CONFIRM",
        "m15_signal": "M15_ENTRY_ZONE_VALID",
        "m1_signal": "M1_TRIGGER_READY",
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "created_at_utc": "2026-06-30T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def signals(path: Path):
    pd.DataFrame(
        [
            {"timeframe": "1h", "signal_state": "H1_NEUTRAL_WAIT", "completed_bar_count": 44},
            {"timeframe": "15m", "signal_state": "M15_ENTRY_ZONE_VALID", "completed_bar_count": 164},
            {"timeframe": "1m", "signal_state": "M1_TRIGGER_READY", "completed_bar_count": 2468},
        ]
    ).to_csv(path, index=False)


def test_append_one_row_per_snapshot(tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s)
    signals(sig)
    out = tmp_path / "out"
    manifest = m.run_stage(out, s, sig)
    ledger = pd.read_csv(out / "dram_intraday_forward_tracking_ledger.csv")
    assert manifest["new_rows_appended"] == 1
    assert len(ledger) == 1


def test_deduplicate_duplicate_snapshot_rows(tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s)
    signals(sig)
    out = tmp_path / "out"
    m.run_stage(out, s, sig)
    manifest = m.run_stage(out, s, sig)
    ledger = pd.read_csv(out / "dram_intraday_forward_tracking_ledger.csv")
    assert manifest["final_status"] == m.FINAL_WARN
    assert manifest["deduplicated_row_count"] == 1
    assert len(ledger) == 1


def test_wait_h1_blocks_downstream_actionability(tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s, "WAIT_H1_CONFIRMATION")
    signals(sig)
    out = tmp_path / "out"
    m.run_stage(out, s, sig)
    row = pd.read_csv(out / "dram_intraday_forward_tracking_ledger.csv").iloc[0]
    assert row["active_gate"] == "H1"
    assert bool(row["downstream_signals_computed_but_not_actionable"]) is True
    assert bool(row["m15_actionable"]) is False
    assert bool(row["m1_actionable"]) is False


def test_entry_allowed_actionable_but_no_broker_action(tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s, "ENTRY_ALLOWED")
    signals(sig)
    out = tmp_path / "out"
    m.run_stage(out, s, sig)
    row = pd.read_csv(out / "dram_intraday_forward_tracking_ledger.csv").iloc[0]
    assert bool(row["actionable_signal"]) is True
    assert bool(row["broker_action_allowed"]) is False


def test_missing_v21_180_snapshot_graceful_failure(tmp_path):
    out = tmp_path / "out"
    manifest = m.run_stage(out, tmp_path / "missing.json", tmp_path / "missing.csv")
    assert manifest["final_status"] == m.FINAL_WARN
    assert manifest["snapshot_loaded"] is False
    assert (out / "dram_intraday_forward_tracking_ledger.csv").exists()


def test_protected_output_mutation_guard(monkeypatch, tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s)
    signals(sig)
    calls = {"n": 0}

    def fake_hashes():
        calls["n"] += 1
        return {"outputs/v21/official_rankings.csv": "before" if calls["n"] == 1 else "after"}

    monkeypatch.setattr(m.replay, "protected_hashes", fake_hashes)
    manifest = m.run_stage(tmp_path / "out", s, sig)
    assert manifest["final_status"] == m.FINAL_FAIL
    assert manifest["protected_outputs_modified"] is True


def test_summary_output_exists(tmp_path):
    s = tmp_path / "snapshot.json"
    sig = tmp_path / "signals.csv"
    snapshot(s)
    signals(sig)
    out = tmp_path / "out"
    m.run_stage(out, s, sig)
    assert (out / "dram_intraday_forward_tracking_summary.csv").exists()
    summary = pd.read_csv(out / "dram_intraday_forward_tracking_summary.csv")
    assert int(summary.iloc[0]["ledger_row_count"]) == 1
