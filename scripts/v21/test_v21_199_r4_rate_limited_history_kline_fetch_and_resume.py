from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts.v21 import v21_199_r4_rate_limited_history_kline_fetch_and_resume as r4


RATE_MSG = "获取历史K线频率太高，请求失败，每30秒最多60次。"


class FakeCtx:
    def __init__(self, fail=None):
        self.fail = fail or {}
        self.calls = {}
    def request_history_kline(self, **params):
        sym = params["code"].split(".")[-1]
        mode = str(params.get("autype")).upper()
        key = (sym, mode)
        self.calls[key] = self.calls.get(key, 0) + 1
        behavior = self.fail.get(key, self.fail.get(sym, "ok"))
        if behavior == "rate_once" and self.calls[key] == 1:
            return -1, RATE_MSG, None
        if behavior == "rate_always":
            return -1, RATE_MSG, None
        if behavior == "empty":
            return 0, pd.DataFrame(), None
        if behavior == "missing_latest":
            return 0, pd.DataFrame([
                {"time_key": "2026-06-30 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            ]), None
        return 0, pd.DataFrame([
            {"time_key": "2026-06-30 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"time_key": "2026-07-01 00:00:00", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 11},
        ]), None


class FakeClient:
    module = SimpleNamespace(RET_OK=0)
    def __init__(self, ctx=None, state="CLOSED"):
        self.ctx = ctx or FakeCtx()
        self.state = state
    def health_check(self):
        return {"minimal_quote_function_ok": True}
    def checked_call(self, name, *args, **kwargs):
        if name == "get_market_state":
            return pd.DataFrame({"code": ["US.DRAM", "US.QQQ", "US.AAPL"], "market_state": [self.state] * 3})
        raise AssertionError(name)
    def close(self):
        pass


def write_canonical(path, symbols):
    pd.DataFrame([{"symbol": s, "date": "2026-06-29", "open": 1, "high": 1, "low": 1, "close": 1, "adjusted_close": 1, "volume": 1} for s in symbols]).to_csv(path, index=False)


def run_tmp(tmp_path, symbols, client=None, **kwargs):
    canonical = tmp_path / "canonical.csv"; raw = tmp_path / "raw.csv"
    write_canonical(canonical, symbols)
    limiter = kwargs.pop("limiter", r4.HistoryKlineRateLimiter(max_calls_per_window=1000, window_seconds=30, sleep_enabled=False))
    return r4.run(client=client or FakeClient(), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw, limiter=limiter, sleep_enabled=False, **kwargs)


def test_rate_limiter_allows_at_most_configured_window():
    limiter = r4.HistoryKlineRateLimiter(max_calls_per_window=2, window_seconds=30, sleep_enabled=False)
    limiter.acquire("QFQ", "A"); limiter.acquire("QFQ", "B"); limiter.acquire("RAW", "C")
    assert max(r["calls_in_window_after_acquire"] for r in limiter.audit_rows) <= 3
    assert limiter.audit_rows[-1]["slept_seconds"] > 0


def test_qfq_and_raw_share_same_limiter(tmp_path):
    limiter = r4.HistoryKlineRateLimiter(max_calls_per_window=1000, window_seconds=30, sleep_enabled=False)
    run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], limiter=limiter)
    modes = [r["adjustment_mode"] for r in limiter.audit_rows]
    assert "QFQ" in modes and "RAW" in modes


def test_rate_limit_message_triggers_retry(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail={"AAPL": "rate_once"})))
    assert summary["qfq_rate_limit_retry_count"] >= 1
    assert summary["dram_qfq_status"] == "SUCCESS_NONEMPTY"


def test_retry_exhaustion_rate_limit_final(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail={"AAPL": "rate_always"})))
    qfq = pd.read_csv(tmp_path / "out/moomoo_qfq_fetch_per_symbol_audit_r4.csv")
    assert "RATE_LIMIT_ERROR" in set(qfq["status_classification"])


def test_checkpoint_skips_qfq_symbol(tmp_path, monkeypatch):
    cp = tmp_path / "out/checkpoints/QFQ/DRAM.csv"; cp.parent.mkdir(parents=True)
    pd.DataFrame([{"source": "MOOMOO", "internal_symbol": "DRAM", "moomoo_code": "US.DRAM", "date": "2026-06-30", "time_key": "2026-06-30", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, "turnover": 1, "last_close": 1, "adjustment_mode": "QFQ", "fetch_timestamp_utc": "x"}]).to_csv(cp, index=False)
    run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    audit = pd.read_csv(tmp_path / "out/moomoo_qfq_fetch_per_symbol_audit_r4.csv")
    assert audit[audit["internal_symbol"].eq("DRAM")]["checkpoint_reused"].astype(bool).iloc[0]


def test_checkpoint_skips_raw_symbol(tmp_path):
    cp = tmp_path / "out/checkpoints/RAW/QQQ.csv"; cp.parent.mkdir(parents=True)
    pd.DataFrame([{"source": "MOOMOO", "internal_symbol": "QQQ", "moomoo_code": "US.QQQ", "date": "2026-06-30", "time_key": "2026-06-30", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, "turnover": 1, "last_close": 1, "adjustment_mode": "RAW", "fetch_timestamp_utc": "x"}]).to_csv(cp, index=False)
    run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    audit = pd.read_csv(tmp_path / "out/moomoo_raw_fetch_per_symbol_audit_r4.csv")
    assert audit[audit["internal_symbol"].eq("QQQ")]["checkpoint_reused"].astype(bool).iloc[0]


def test_force_refetch_ignores_checkpoint(tmp_path, monkeypatch):
    cp = tmp_path / "out/checkpoints/QFQ/DRAM.csv"; cp.parent.mkdir(parents=True)
    pd.DataFrame([{"date": "2026-06-30"}]).to_csv(cp, index=False)
    monkeypatch.setenv("MOOMOO_FORCE_REFETCH", "true")
    run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    audit = pd.read_csv(tmp_path / "out/moomoo_qfq_fetch_per_symbol_audit_r4.csv")
    assert not audit[audit["internal_symbol"].eq("DRAM")]["checkpoint_reused"].astype(bool).iloc[0]


def test_priority_symbols_fetched_first():
    m = r4.priority_first_mapping(["MSFT", "AAPL", "DRAM", "QQQ"])
    assert m["internal_symbol"].tolist()[:3] == ["DRAM", "QQQ", "AAPL"]


def test_dram_qfq_success_preserved(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    assert summary["dram_qfq_status"] == "SUCCESS_NONEMPTY"


def test_qqq_qfq_success_preserved(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    assert summary["qqq_qfq_status"] == "SUCCESS_NONEMPTY"


def test_raw_empty_triggers_explicit_failure(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail={("AAPL", "NONE"): "empty", ("QQQ", "NONE"): "empty", ("DRAM", "NONE"): "empty"})))
    assert summary["final_status"] == "FAIL_V21_199_R4_TRADE_PLAN_RATE_LIMIT_OR_RAW_FETCH_FAILED"
    assert summary["trade_plan_failure_reason"]


def test_open_session_current_date_excluded(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(state="OPEN"), current_exchange_date="2026-07-01")
    assert summary["latest_raw_max_date"] == "2026-07-01"
    assert summary["latest_completed_candidate_date"] == "2026-06-30"
    assert summary["open_session_excluded_dates"] == ["2026-07-01"]


def test_prior_raw_max_completed_when_current_exchange_date_is_later(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(state="OPEN"), current_exchange_date="2026-07-02")
    assert summary["latest_raw_max_date"] == "2026-07-01"
    assert summary["latest_completed_candidate_date"] == "2026-07-01"
    assert summary["open_session_excluded_dates"] == []
    assert summary["canonical_latest_date_after"] == "2026-07-01"


def test_incomplete_latest_coverage_blocks_canonical_promotion(tmp_path):
    summary = run_tmp(
        tmp_path,
        ["AAPL", "QQQ", "DRAM"],
        client=FakeClient(FakeCtx(fail={"AAPL": "missing_latest"}), state="OPEN"),
        current_exchange_date="2026-07-02",
    )
    assert summary["latest_raw_max_date"] == "2026-07-01"
    assert summary["latest_completed_candidate_date"] == "2026-07-01"
    assert summary["latest_moomoo_broad_honest_date"] == "2026-06-30"
    assert summary["raw_max_date_later_than_broad_honest_latest_date"] is True
    assert summary["final_status"] == "FAIL_V21_199_R4_DATA_QUALITY_GATE_FAILED"
    assert not summary["canonical_mutated"]
    assert summary["canonical_latest_date_after"] != "2026-07-01"


def test_completed_research_frame_keeps_existing_20260630_closed_behavior():
    frame = pd.DataFrame([
        {"internal_symbol": "AAPL", "date": "2026-06-30", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
    ])
    completed, gate = r4.completed_research_frame(frame, market_open=False, current_exchange_date="2026-07-01")
    assert gate["latest_raw_max_date"] == "2026-06-30"
    assert gate["latest_completed_candidate_date"] == "2026-06-30"
    assert gate["open_session_excluded_dates"] == []
    assert completed["date"].astype(str).tolist() == ["2026-06-30"]


def test_canonical_not_mutated_on_qfq_only_success_raw_failure(tmp_path):
    canonical = tmp_path / "canonical.csv"; raw = tmp_path / "raw.csv"
    symbols = ["AAPL", "QQQ", "DRAM"]; write_canonical(canonical, symbols)
    before = canonical.read_text(encoding="utf-8")
    summary = r4.run(client=FakeClient(FakeCtx(fail={("AAPL", "NONE"): "empty", ("QQQ", "NONE"): "empty", ("DRAM", "NONE"): "empty"})), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw, limiter=r4.HistoryKlineRateLimiter(1000, 30, False), sleep_enabled=False)
    assert not summary["canonical_mutated"]
    assert canonical.read_text(encoding="utf-8") == before


def test_canonical_updates_only_when_all_gates_pass(tmp_path):
    canonical = tmp_path / "canonical.csv"; raw = tmp_path / "raw.csv"
    symbols = ["AAPL", "QQQ", "DRAM"]; write_canonical(canonical, symbols)
    summary = r4.run(client=FakeClient(), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw, limiter=r4.HistoryKlineRateLimiter(1000, 30, False), sleep_enabled=False)
    assert summary["final_status"] == "PASS_V21_199_R4_MOOMOO_CANONICAL_UPDATED"
    assert summary["canonical_mutated"]


def test_no_trade_api_called(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"])
    assert summary["trade_api_called"] is False
