import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_180_dram_intraday_confirmation_snapshot_runner as m


def bars(path: Path, n=80, base=69.5):
    times = pd.date_range("2026-06-29 13:30:00", periods=n, freq="min")
    close = [base + i * 0.02 for i in range(n)]
    pd.DataFrame(
        {
            "datetime": times,
            "ticker": "DRAM",
            "interval": "1m",
            "open": close,
            "high": [x + 0.05 for x in close],
            "low": [x - 0.05 for x in close],
            "close": [x + 0.01 for x in close],
            "volume": [1000 + i for i in range(n)],
        }
    ).to_csv(path, index=False)


def plan(path: Path, entry=69.7, no_chase=74.0, stop=63.0, currentness="CURRENT"):
    pd.DataFrame(
        [
            {
                "run_timestamp": "2026-06-30T00:00:00Z",
                "ticker": "DRAM",
                "latest_price_date": "2026-06-29",
                "latest_plan_date": "2026-06-29",
                "trade_plan_currentness": currentness,
                "refresh_required": False,
                "planned_entry_base": entry,
                "no_chase_above": no_chase,
                "stop_loss_base": stop,
                "research_only": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
            }
        ]
    ).to_csv(path, index=False)


def test_completed_bars_only(tmp_path):
    intraday = tmp_path / "bars.csv"
    bars(intraday, n=10)
    raw, completed = m.completed_intraday_snapshot(intraday, as_of=pd.Timestamp("2026-06-29 13:35:00"))
    assert len(raw) == 10
    assert completed["bar_end"].max() <= pd.Timestamp("2026-06-29 13:35:00")


def test_unfinished_current_bar_exclusion(tmp_path):
    intraday = tmp_path / "bars.csv"
    bars(intraday, n=10)
    raw, completed = m.completed_intraday_snapshot(intraday)
    assert len(completed) == len(raw) - 1
    assert completed["datetime"].max() < raw["datetime"].max()


def test_no_chase_hard_block(tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday, n=20, base=75.0)
    plan(p, no_chase=74.0)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [p])
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    assert state["execution_state"] == "NO_CHASE_BLOCK"


def test_stop_hard_block(tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday, n=20, base=62.8)
    plan(p, stop=63.0)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [p])
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    assert state["execution_state"] == "STOP_RISK_ACTIVE"


def test_invalid_daily_plan_block(tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday)
    plan(p, entry=75.0, no_chase=74.0, stop=63.0)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [p])
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    assert state["execution_state"] == "PLAN_BLOCKED_INVALID_BOUNDS"


def test_missing_intraday_data_graceful_failure(tmp_path):
    p = tmp_path / "plan.csv"
    plan(p)
    out = tmp_path / "out"
    summary = m.run_stage(out, tmp_path / "missing.csv", [p])
    assert summary["final_status"] == m.FINAL_PARTIAL
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    assert state["execution_state"] == "INTRADAY_DATA_UNAVAILABLE"


def test_exactly_one_execution_state_output(tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday)
    plan(p)
    out = tmp_path / "out"
    manifest = m.run_stage(out, intraday, [p])
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    assert manifest["exactly_one_execution_state_output"] is True
    assert isinstance(state["execution_state"], str)
    assert state["execution_state"] in m.EXECUTION_STATES


def test_protected_output_mutation_guard(monkeypatch, tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday)
    plan(p)
    calls = {"n": 0}

    def fake_hashes():
        calls["n"] += 1
        return {"outputs/v21/official_rankings.csv": "before" if calls["n"] == 1 else "after"}

    monkeypatch.setattr(m.replay, "protected_hashes", fake_hashes)
    manifest = m.run_stage(tmp_path / "out", intraday, [p])
    assert manifest["protected_outputs_modified"] is True
    assert manifest["final_status"] == m.FINAL_FAIL


def test_broker_action_allowed_remains_false(tmp_path):
    intraday = tmp_path / "bars.csv"
    p = tmp_path / "plan.csv"
    bars(intraday)
    plan(p)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [p])
    state = json.loads((out / "dram_intraday_snapshot_state.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert state["broker_action_allowed"] is False
    assert manifest["broker_action_allowed"] is False
