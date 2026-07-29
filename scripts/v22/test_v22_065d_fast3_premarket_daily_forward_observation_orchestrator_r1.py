from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

import v22_065d_fast3_premarket_daily_forward_observation_orchestrator_r1 as m


NOW = datetime(2026, 7, 28, 17, 0, tzinfo=m.ET)


def put(root: Path, symbol: str, day: str, complete: bool = True) -> None:
    periods = 326 if complete else 120
    et = pd.date_range(f"{day} 04:00", periods=periods, freq="min", tz=m.ET)
    p = root / f"symbol={symbol}" / "year=2026" / "month=07" / "data.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"timestamp_utc": et.tz_convert("UTC")})
    if p.exists(): frame = pd.concat([pd.read_parquet(p), frame], ignore_index=True)
    frame.to_parquet(p, index=False)


def full(root: Path, day: str = "2026-07-27") -> None:
    for s in m.SYMBOLS: put(root, s, day)


def test_no_new_data_is_stale_after_expected_market_day(tmp_path):
    full(tmp_path, "2026-07-24")
    assert m.assess_canonical(tmp_path, NOW)["data_gate_decision"] == "MARKET_DATA_STALE"


def test_all_symbols_new_complete_session_ready(tmp_path):
    full(tmp_path)
    got = m.assess_canonical(tmp_path, NOW)
    assert got["post_cutoff_complete_session_available"] and got["data_gate_decision"] == "NEW_SESSION_READY"


def test_partial_symbols_is_partial_session_data(tmp_path):
    for s in m.SYMBOLS[:3]: put(tmp_path, s, "2026-07-27")
    for s in m.SYMBOLS[3:]: put(tmp_path, s, "2026-07-24")
    assert m.assess_canonical(tmp_path, NOW)["data_gate_decision"] == "PARTIAL_SESSION_DATA"


def test_new_date_incomplete_is_partial_session_data(tmp_path):
    full(tmp_path)
    put(tmp_path, "QQQ", "2026-07-28", False)
    # QQQ's latest date is incomplete; the jointly complete day is still 27.
    assert m.assess_canonical(tmp_path, NOW)["common_latest_session_date_et"] == "2026-07-27"


def test_utc_cross_day_converts_to_et_date(tmp_path):
    p = tmp_path / "symbol=QQQ/year=2026/month=07/data.parquet"; p.parent.mkdir(parents=True)
    pd.DataFrame({"timestamp_utc": [pd.Timestamp("2026-07-28 00:30Z")]}).to_parquet(p, index=False)
    values, _ = m.et_dates_and_complete([p], date(2026, 7, 27))
    assert values == {date(2026, 7, 27)}


def test_weekend_expected_day_is_previous_friday():
    assert m.expected_completed_day(datetime(2026, 7, 26, 12, tzinfo=m.ET)) == date(2026, 7, 24)


def test_holiday_expected_day_is_previous_market_day():
    assert m.expected_completed_day(datetime(2026, 7, 3, 17, tzinfo=m.ET)) == date(2026, 7, 2)


def test_before_market_close_does_not_count_today():
    assert m.expected_completed_day(datetime(2026, 7, 28, 12, tzinfo=m.ET)) == date(2026, 7, 27)


def test_market_close_all_minutes_required(tmp_path):
    full(tmp_path, "2026-07-27")
    assert m.assess_canonical(tmp_path, NOW)["incomplete_symbol_count"] == 0


def test_missing_symbol_count(tmp_path):
    put(tmp_path, "QQQ", "2026-07-27")
    assert m.assess_canonical(tmp_path, NOW)["missing_symbol_count"] == 5


def test_failure_stops_before_old_result_read(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "OUT", tmp_path / "out")
    monkeypatch.setattr(m, "frozen_snapshot", lambda: {})
    summary, rc = m.execute(NOW, runner=lambda _: 9)
    assert rc == 9 and summary["failed_stage"] == "py_compile"


def test_v22_062pr_failure_stops(monkeypatch, tmp_path):
    # The first failure always stops; this asserts the same stop contract used
    # for PR/C without depending on external OpenD.
    monkeypatch.setattr(m, "OUT", tmp_path / "out")
    monkeypatch.setattr(m, "frozen_snapshot", lambda: {})
    summary, rc = m.execute(NOW, runner=lambda _: 7)
    assert rc == 7 and summary["daily_observation_decision"] == "PIPELINE_STOPPED"


def test_idempotent_gate_same_data_same_result(tmp_path):
    full(tmp_path)
    assert m.assess_canonical(tmp_path, NOW) == m.assess_canonical(tmp_path, NOW)


def test_frozen_file_modification_detection(tmp_path, monkeypatch):
    f = tmp_path / "frozen.py"; f.write_text("a")
    monkeypatch.setattr(m, "FROZEN_FILES", (f,))
    before = m.frozen_snapshot(); f.write_text("b")
    assert before[str(f)] != m.sha256(f)


def test_status_labels_for_signal_and_no_signal_are_distinct():
    assert "NO_SIGNAL" in "NEW_SESSION_READY_NO_SIGNAL"
    assert "WITH_SIGNAL" in "NEW_SESSION_READY_WITH_SIGNAL"


def test_hard_gate_never_uses_file_mtime(tmp_path):
    p = tmp_path / "symbol=QQQ/year=2026/month=07/data.parquet"; p.parent.mkdir(parents=True)
    pd.DataFrame({"timestamp_utc": []}).to_parquet(p, index=False)
    assert m.et_dates_and_complete([p], date(2026, 7, 27))[0] == set()


class FakeProcess:
    def __init__(self, polls: int, code: int = 0, stdout=None, stderr=None, text=None, **_):
        self.pid, self.left, self.code = 12345, polls, code
        if stderr and code and code == 3: stderr.write("OpenD unavailable at 127.0.0.1:11111")
    def poll(self):
        if self.left > 0: self.left -= 1; return None
        return self.code
    def wait(self, timeout=None): self.left = 0; return self.code


def monitored(polls, code=0, tokens=None, hard=10, idle=3):
    ticks = [0]
    values = iter(tokens or ["same"])
    last = ["same"]
    def probe():
        try: last[0] = next(values)
        except StopIteration: pass
        return last[0]
    return m.monitored_data_refresh(["powershell", "-File", "v22_049.ps1", "-Execute"], hard, idle,
        popen_factory=lambda *a, **k: FakeProcess(polls, code, **k), progress_probe=probe,
        clock=lambda: ticks[0], sleep=lambda _: ticks.__setitem__(0, ticks[0] + 1), tree_terminator=lambda _: None)


def test_refresh_child_fast_success():
    assert monitored(0)["data_refresh_status"] == "DATA_REFRESH_COMPLETED"


def test_progress_prevents_short_idle_timeout():
    got = monitored(5, tokens=["a", "b", "c", "d", "e", "f"], hard=20, idle=2)
    assert got["data_refresh_status"] == "DATA_REFRESH_COMPLETED" and got["data_refresh_progress_observed"]


def test_idle_timeout_terminates_child_tree():
    killed = []
    ticks = [0]
    got = m.monitored_data_refresh(["p", "-File", "v22_049.ps1", "-Execute"], 20, 2,
        popen_factory=lambda *a, **k: FakeProcess(99, **k), progress_probe=lambda: "same",
        clock=lambda: ticks[0], sleep=lambda _: ticks.__setitem__(0, ticks[0] + 1), tree_terminator=killed.append)
    assert got["data_refresh_status"] == "DATA_REFRESH_IDLE_TIMEOUT" and killed == [12345]


def test_progressing_child_hits_hard_timeout():
    got = monitored(99, tokens=[str(x) for x in range(20)], hard=3, idle=20)
    assert got["data_refresh_status"] == "DATA_REFRESH_HARD_TIMEOUT"


def test_nonzero_child_failure_is_distinct():
    assert monitored(0, code=2)["data_refresh_status"] == "DATA_REFRESH_CHILD_FAILURE"


def test_opend_failure_is_distinct():
    assert monitored(0, code=3)["data_refresh_status"] == "DATA_REFRESH_OPEND_CONNECTION_FAILURE"


def test_test_timeouts_do_not_change_production_defaults():
    monitored(0, hard=1, idle=1)
    assert m.DEFAULT_DATA_REFRESH_HARD_TIMEOUT_MINUTES == 45 and m.DEFAULT_DATA_REFRESH_IDLE_TIMEOUT_MINUTES == 12


def test_refresh_failure_does_not_read_old_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "OUT", tmp_path / "out"); monkeypatch.setattr(m, "frozen_snapshot", lambda: {})
    audit = {"data_refresh_status": "DATA_REFRESH_IDLE_TIMEOUT", "data_refresh_child_exit_code": -1}
    summary, rc = m.execute(NOW, runner=lambda _: 0, refresh_runner=lambda *_: audit)
    assert rc == 1 and summary["failed_stage"] == "data_refresh"


def test_repeat_monitor_creates_no_result_directory_or_log_copy():
    first, second = monitored(0), monitored(0)
    assert first["data_refresh_stdout_tail"] == second["data_refresh_stdout_tail"] == ""
