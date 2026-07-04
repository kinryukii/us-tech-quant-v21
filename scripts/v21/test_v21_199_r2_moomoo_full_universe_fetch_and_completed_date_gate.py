from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts.v21 import v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate as r2


class FakeClient:
    module = SimpleNamespace(RET_OK=0)

    def __init__(self, state: str = "CLOSED"):
        self.state = state

    def health_check(self):
        return {"minimal_quote_function_ok": True, "opend_reachable": True}

    def checked_call(self, name, *args, **kwargs):
        if name == "get_market_state":
            return pd.DataFrame({"code": ["US.DRAM", "US.QQQ", "US.AAPL"], "market_state": [self.state, self.state, self.state]})
        if name == "get_history_kl_quota":
            return {"used_quota": 1, "remain_quota": 99, "detail_list": []}
        raise AssertionError(name)

    def close(self):
        pass


def rows(symbols, dates=("2026-06-30",), omit=()):
    data = []
    for sym in symbols:
        if sym in omit:
            continue
        for date in dates:
            data.append({
                "source": "MOOMOO",
                "internal_symbol": sym,
                "moomoo_code": f"US.{sym}",
                "date": date,
                "time_key": date,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "turnover": 1000,
                "last_close": 10,
                "adjustment_mode": "QFQ",
                "fetch_timestamp_utc": "2026-07-01T00:00:00+00:00",
            })
    return pd.DataFrame(data)


def make_fetcher(symbols_to_return=None, dates=("2026-06-30",), empty=False, omit=()):
    def fetcher(client, mapping, adjustment_mode="QFQ", **kwargs):
        if empty:
            return pd.DataFrame(), pd.DataFrame()
        symbols = symbols_to_return or mapping["internal_symbol"].astype(str).tolist()
        frame = rows(symbols, dates=dates, omit=omit)
        frame["adjustment_mode"] = adjustment_mode.upper()
        audit = pd.DataFrame([{"internal_symbol": s, "fetch_status": "PASS"} for s in symbols])
        return frame, audit
    return fetcher


def write_canonical(path, symbols):
    pd.DataFrame([{"symbol": s, "date": "2026-06-29", "open": 1, "high": 1, "low": 1, "close": 1, "adjusted_close": 1, "volume": 1} for s in symbols]).to_csv(path, index=False)


def test_production_fetch_list_must_not_be_truncated_to_60():
    eligible = [f"S{i}" for i in range(316)]
    fetch = r2.build_fetch_universe(eligible)
    assert len(fetch) == 319
    assert fetch[:61] != fetch[:60]
    assert {"DRAM", "QQQ", "AAPL"}.issubset(set(fetch))


def test_mock_mode_symbol_cap_only_when_explicitly_requested():
    eligible = [f"S{i}" for i in range(100)]
    assert len(r2.build_fetch_universe(eligible)) == 103
    capped = r2.build_fetch_universe(eligible, explicit_symbol_cap=10)
    assert len(capped) == 13
    assert capped[:10] == eligible[:10]


def test_priority_symbols_always_appended_even_if_not_eligible_universe():
    fetch = r2.build_fetch_universe(["MSFT"])
    assert fetch == ["MSFT", "DRAM", "QQQ", "AAPL"]


def test_dram_priority_symbol_cannot_be_dropped_by_truncation():
    fetch = r2.build_fetch_universe([f"S{i}" for i in range(100)], explicit_symbol_cap=1)
    assert "DRAM" in fetch
    assert fetch == ["S0", "DRAM", "QQQ", "AAPL"]


def test_staging_distinct_below_mapped_count_triggers_truncated(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = [f"S{i}" for i in range(100)]
    write_canonical(canonical, eligible)
    summary = r2.run(
        client=FakeClient(),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(["S0", "S1", "DRAM", "QQQ", "AAPL"]),
        trade_fetcher=make_fetcher(["S0", "S1", "DRAM", "QQQ", "AAPL"]),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["final_status"] == "FAIL_V21_199_R2_FETCH_UNIVERSE_TRUNCATED"
    assert summary["canonical_mutated"] is False


def test_dram_mapping_pass_but_no_dram_staging_rows_triggers_missing(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = ["AAPL", "QQQ"]
    write_canonical(canonical, eligible)
    summary = r2.run(
        client=FakeClient(),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(["AAPL", "QQQ"]),
        trade_fetcher=make_fetcher(["AAPL", "QQQ"]),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["dram_mapped"] is True
    assert summary["final_status"] == "FAIL_V21_199_R2_DRAM_PRIORITY_FETCH_MISSING"


def test_regular_session_open_excludes_current_raw_max_date_from_completed_eligibility():
    staging = rows(["AAPL", "QQQ", "DRAM"], dates=("2026-06-30", "2026-07-01"))
    completed, audit = r2.completed_research_frame(staging, market_open=True, current_exchange_date="2026-07-01")
    assert audit["latest_raw_max_date"] == "2026-07-01"
    assert audit["latest_completed_candidate_date"] == "2026-06-30"
    assert "2026-07-01" not in set(completed["date"])


def test_regular_session_open_keeps_prior_completed_raw_max_date():
    staging = rows(["AAPL", "QQQ", "DRAM"], dates=("2026-06-30", "2026-07-01"))
    completed, audit = r2.completed_research_frame(staging, market_open=True, current_exchange_date="2026-07-05")
    assert audit["latest_raw_max_date"] == "2026-07-01"
    assert audit["latest_completed_candidate_date"] == "2026-07-01"
    assert "2026-07-01" in set(completed["date"])


def test_completed_broad_date_keeps_completed_raw_max_when_open_state_is_later_session(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, eligible)
    summary = r2.run(
        client=FakeClient("OPEN"),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(eligible, dates=("2026-06-30", "2026-07-01")),
        trade_fetcher=make_fetcher(eligible, dates=("2026-06-30", "2026-07-01")),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["latest_raw_max_date"] == "2026-07-01"
    assert summary["latest_completed_candidate_date"] == "2026-07-01"
    assert summary["latest_moomoo_broad_honest_date"] == "2026-07-01"


def test_trade_plan_candidate_empty_triggers_failure(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, eligible)
    summary = r2.run(
        client=FakeClient(),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(eligible),
        trade_fetcher=make_fetcher(empty=True),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["final_status"] == "FAIL_V21_199_R2_TRADE_PLAN_RAW_PANEL_EMPTY"


def test_canonical_not_mutated_on_any_failure(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, eligible)
    before = canonical.read_text(encoding="utf-8")
    summary = r2.run(
        client=FakeClient(),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(eligible, omit=("DRAM",)),
        trade_fetcher=make_fetcher(eligible),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["final_status"] == "FAIL_V21_199_R2_DRAM_PRIORITY_FETCH_MISSING"
    assert canonical.read_text(encoding="utf-8") == before


def test_canonical_backed_up_and_updated_only_when_all_r2_gates_pass(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    eligible = ["AAPL", "QQQ", "DRAM"]
    write_canonical(canonical, eligible)
    summary = r2.run(
        client=FakeClient(),
        out_dir=tmp_path / "out",
        eligible_symbols=eligible,
        research_fetcher=make_fetcher(eligible),
        trade_fetcher=make_fetcher(eligible),
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
    )
    assert summary["final_status"] == "PASS_V21_199_R2_MOOMOO_CANONICAL_UPDATED"
    assert summary["canonical_mutated"] is True
    assert summary["research_backup_path"]
    assert pd.read_csv(canonical)["date"].max() == "2026-06-30"
