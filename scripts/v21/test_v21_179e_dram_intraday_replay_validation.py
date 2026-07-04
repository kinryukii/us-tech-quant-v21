import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_179e_dram_intraday_replay_validation as m


def minute_bars(start="2026-06-29 13:30:00", n=90, base=69.5):
    times = pd.date_range(start, periods=n, freq="min")
    close = [base + i * 0.035 for i in range(n)]
    return pd.DataFrame(
        {
            "datetime": times,
            "ticker": "DRAM",
            "interval": "1m",
            "open": close,
            "high": [x + 0.08 for x in close],
            "low": [x - 0.08 for x in close],
            "close": [x + 0.02 for x in close],
            "volume": [1000 + i for i in range(n)],
        }
    )


def plan_file(path: Path, replay_date="2026-06-29", source_stage="V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1"):
    pd.DataFrame(
        [
            {
                "plan_date": "2026-06-26",
                "target_trade_session": f"NEXT_DAILY_SESSION_AFTER_{replay_date}",
                "ticker": "DRAM",
                "planned_entry_base": 69.7,
                "no_chase_above": 74.0,
                "stop_loss_base": 63.0,
                "latest_price_date_used": "2026-06-26",
                "source_stage": source_stage,
            }
        ]
    ).to_csv(path, index=False)


def test_no_future_bars_used_in_completed_aggregation():
    bars = m.normalize_intraday(minute_bars(n=31))
    as_of = pd.Timestamp("2026-06-29 14:00:00")
    agg = m.aggregate_completed(bars, as_of, "15min")
    assert not agg.empty
    assert agg["bar_end"].max() <= as_of
    assert pd.Timestamp("2026-06-29 14:00:00") not in set(agg["datetime"])


def test_no_unfinished_hour_bar_used():
    bars = m.normalize_intraday(minute_bars(n=61))
    agg = m.aggregate_completed(bars, pd.Timestamp("2026-06-29 14:15:00"), "60min")
    assert len(agg) == 0
    agg2 = m.aggregate_completed(bars, pd.Timestamp("2026-06-29 14:30:00"), "60min")
    assert len(agg2) == 1
    assert str(agg2.iloc[0]["bar_end"]) == "2026-06-29 14:30:00"


def test_next_bar_execution_policy(tmp_path):
    intraday = tmp_path / "intraday.csv"
    plans = tmp_path / "plans.csv"
    minute_bars(n=120).to_csv(intraday, index=False)
    plan_file(plans)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [plans])
    ledger = pd.read_csv(out / "dram_intraday_replay_ledger.csv")
    entries = ledger[pd.to_numeric(ledger["entry_price"], errors="coerce").notna()]
    assert not entries.empty
    assert (pd.to_datetime(entries["entry_timestamp"]) > pd.to_datetime(entries["signal_timestamp"])).all()


def test_no_chase_hard_block():
    assert m.hard_execution_state(74.5, no_chase=74.0, stop=63.0, config=m.ReplayConfig()) == "NO_CHASE_BLOCK"


def test_stop_hard_block():
    assert m.hard_execution_state(63.1, no_chase=74.0, stop=63.0, config=m.ReplayConfig(stop_buffer_pct=0.003)) == "STOP_RISK_ACTIVE"


def test_baseline_comparison_output(tmp_path):
    intraday = tmp_path / "intraday.csv"
    plans = tmp_path / "plans.csv"
    minute_bars(n=120).to_csv(intraday, index=False)
    plan_file(plans)
    out = tmp_path / "out"
    summary = m.run_stage(out, intraday, [plans])
    comp = pd.read_csv(out / "dram_intraday_baseline_comparison.csv")
    assert set(comp["baseline"]) == set(m.BASELINES)
    assert summary["research_only"] is True
    assert summary["broker_action_allowed"] is False


def test_missing_intraday_data_graceful_failure(tmp_path):
    intraday = tmp_path / "missing.csv"
    plans = tmp_path / "plans.csv"
    plan_file(plans)
    out = tmp_path / "out"
    summary = m.run_stage(out, intraday, [plans])
    assert summary["final_status"] == m.FINAL_WARN
    assert (out / "dram_intraday_data_quality_report.csv").exists()
    assert (out / "dram_intraday_replay_ledger.csv").exists()


def test_pit_lite_and_diagnostic_only_labeling(tmp_path):
    strict = tmp_path / "strict.csv"
    diag = tmp_path / "diag.csv"
    plan_file(strict, source_stage="V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1")
    plan_file(diag, source_stage="")
    assert m.load_plans([strict])[1] == "PIT_LITE"
    assert m.load_plans([diag])[1] == "DIAGNOSTIC_ONLY"


def test_protected_output_mutation_guard(monkeypatch, tmp_path):
    intraday = tmp_path / "intraday.csv"
    plans = tmp_path / "plans.csv"
    minute_bars(n=120).to_csv(intraday, index=False)
    plan_file(plans)
    calls = {"n": 0}

    def fake_hashes():
        calls["n"] += 1
        return {"outputs/v21/official_rankings.csv": "before" if calls["n"] == 1 else "after"}

    monkeypatch.setattr(m, "protected_hashes", fake_hashes)
    summary = m.run_stage(tmp_path / "out", intraday, [plans])
    assert summary["protected_outputs_modified"] is True
    assert summary["final_status"] == m.FINAL_FAIL


def test_manifest_policy_flags_written(tmp_path):
    intraday = tmp_path / "intraday.csv"
    plans = tmp_path / "plans.csv"
    minute_bars(n=10).to_csv(intraday, index=False)
    plan_file(plans)
    out = tmp_path / "out"
    m.run_stage(out, intraday, [plans])
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["official_adoption_allowed"] is False
    assert manifest["broker_action_allowed"] is False
    assert manifest["research_only"] is True
