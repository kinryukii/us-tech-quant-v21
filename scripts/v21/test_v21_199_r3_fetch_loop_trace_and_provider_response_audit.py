from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts.v21 import v21_199_r3_fetch_loop_trace_and_provider_response_audit as r3


class FakeCtx:
    def __init__(self, mode="all", fail_symbols=None):
        self.mode = mode
        self.fail_symbols = fail_symbols or {}

    def request_history_kline(self, **params):
        code = params["code"]
        sym = code.split(".")[-1]
        behavior = self.fail_symbols.get(sym, self.mode)
        if behavior == "api_error":
            return -1, "NO_RIGHT_OR_NO_DATA", None
        if behavior == "exception":
            raise RuntimeError("boom")
        if behavior == "empty":
            return 0, pd.DataFrame(), None
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
        return {"minimal_quote_function_ok": True, "opend_reachable": True}

    def checked_call(self, name, *args, **kwargs):
        if name == "get_market_state":
            return pd.DataFrame({"code": ["US.DRAM", "US.QQQ", "US.AAPL"], "market_state": [self.state] * 3})
        if name == "get_history_kl_quota":
            return {"used_quota": 1, "remain_quota": 99, "detail_list": []}
        raise AssertionError(name)

    def close(self):
        pass


def write_canonical(path, symbols):
    pd.DataFrame([{"symbol": s, "date": "2026-06-29", "open": 1, "high": 1, "low": 1, "close": 1, "adjusted_close": 1, "volume": 1} for s in symbols]).to_csv(path, index=False)


def run_tmp(tmp_path, symbols, client=None, **kwargs):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    write_canonical(canonical, symbols)
    return r3.run(client=client or FakeClient(), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw, **kwargs)


def test_planned_fetch_list_creates_one_audit_row_per_planned_symbol(tmp_path):
    symbols = ["AAPL", "QQQ", "DRAM", "MSFT"]
    summary = run_tmp(tmp_path, symbols, apply_merge=False)
    audit = pd.read_csv(tmp_path / "out/moomoo_fetch_loop_per_symbol_audit.csv")
    assert len(audit) == summary["planned_fetch_symbol_count"] == 4


def test_priority_symbols_are_first_in_fetch_order():
    mapping = r3.priority_first_mapping(["MSFT", "AAPL", "QQQ", "DRAM"])
    assert mapping["internal_symbol"].tolist()[:3] == ["DRAM", "QQQ", "AAPL"]


def test_loop_stops_early_triggers_not_all_attempted(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM", "MSFT"], stop_after=2, apply_merge=False)
    assert summary["final_status"] == "FAIL_V21_199_R3_FETCH_LOOP_DID_NOT_ATTEMPT_ALL_SYMBOLS"


def test_all_attempted_but_most_empty_or_error_triggers_provider_failure(tmp_path):
    symbols = ["AAPL", "QQQ", "DRAM"] + [f"S{i}" for i in range(10)]
    fail = {s: "empty" for s in symbols}
    fail["AAPL"] = "all"
    summary = run_tmp(tmp_path, symbols, client=FakeClient(FakeCtx(fail_symbols=fail)), apply_merge=False)
    assert summary["final_status"] == "FAIL_V21_199_R3_PROVIDER_EMPTY_OR_ERROR_FOR_MOST_SYMBOLS"


def test_nonempty_but_staging_only_60_triggers_accumulation_truncated(tmp_path):
    symbols = [f"S{i}" for i in range(100)] + ["AAPL", "QQQ", "DRAM"]
    summary = run_tmp(tmp_path, symbols, force_drop_after_fetch=60, apply_merge=False)
    assert summary["staging_distinct_symbol_count"] < int(summary["nonempty_response_symbol_count"] * 0.80)
    assert summary["final_status"] == "FAIL_V21_199_R3_STAGING_ACCUMULATION_TRUNCATED"


def test_dram_missing_after_main_loop_triggers_fallback(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail_symbols={"DRAM": "empty"})), apply_merge=False)
    assert summary["dram_fallback_attempted"] is True


def test_dram_fallback_success_enters_staging(tmp_path):
    class FlipCtx(FakeCtx):
        def __init__(self):
            super().__init__()
            self.count = 0
        def request_history_kline(self, **params):
            if params["code"] == "US.DRAM":
                self.count += 1
                if self.count == 1:
                    return 0, pd.DataFrame(), None
            return super().request_history_kline(**params)
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FlipCtx()), apply_merge=False)
    assert summary["dram_fallback_status"] == "SUCCESS_NONEMPTY"
    assert summary["dram_fallback_row_count"] > 0


def test_dram_fallback_failure_records_ret_code_msg(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail_symbols={"DRAM": "api_error"})), apply_merge=False)
    fb = pd.read_csv(tmp_path / "out/dram_fetch_fallback_audit.csv")
    assert summary["dram_fallback_status"] == "API_ERROR"
    assert str(fb["api_return_code"].iloc[0]) == "-1"
    assert "NO_RIGHT" in str(fb["api_return_message"].iloc[0])


def test_qqq_missing_after_main_loop_triggers_fallback(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(FakeCtx(fail_symbols={"QQQ": "empty"})), apply_merge=False)
    assert summary["qqq_fallback_attempted"] is True


def test_raw_trade_plan_empty_has_explicit_reason(tmp_path):
    class RawEmptyCtx(FakeCtx):
        def request_history_kline(self, **params):
            if str(params.get("autype")).lower() == "none":
                return 0, pd.DataFrame(), None
            return super().request_history_kline(**params)
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(RawEmptyCtx()), apply_merge=False)
    assert summary["trade_plan_candidate_rows"] == 0
    assert "SUCCESS_EMPTY" in summary["trade_plan_failure_reason"]


def test_open_session_keeps_completed_raw_max_when_not_current_session(tmp_path):
    summary = run_tmp(tmp_path, ["AAPL", "QQQ", "DRAM"], client=FakeClient(state="OPEN"), apply_merge=False)
    assert summary["latest_raw_max_date"] == "2026-07-01"
    assert summary["latest_completed_candidate_date"] == "2026-07-01"
    assert summary["latest_moomoo_broad_honest_date"] == "2026-07-01"


def test_canonical_not_mutated_on_failure(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    symbols = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, symbols)
    before = canonical.read_text(encoding="utf-8")
    summary = r3.run(client=FakeClient(FakeCtx(mode="empty")), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw)
    assert summary["canonical_mutated"] is False
    assert canonical.read_text(encoding="utf-8") == before


def test_canonical_updates_only_when_all_gates_pass(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    symbols = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, symbols)
    summary = r3.run(client=FakeClient(), out_dir=tmp_path / "out", eligible_symbols=symbols, research_canonical_path=canonical, trade_plan_canonical_path=raw)
    assert summary["final_status"] == "PASS_V21_199_R3_MOOMOO_CANONICAL_UPDATED"
    assert summary["canonical_mutated"] is True
    assert pd.read_csv(canonical)["date"].max() == "2026-07-01"
