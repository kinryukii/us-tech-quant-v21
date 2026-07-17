from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).with_name(
    "v22_037_r2c_option_underlying_same_snapshot_capture_and_iv_greeks_validation_research_only.py"
)
SPEC = importlib.util.spec_from_file_location("v22_037_r2c", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def option_code(expiry: str, side: str, strike: int) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    return f"US.QQQ{yymmdd}{side}{strike * 1000:08d}"


class FakeContext:
    def __init__(self, host="127.0.0.1", port=11111, *, misaligned=False, omit_underlying=False):
        self.host = host
        self.port = port
        self.misaligned = misaligned
        self.omit_underlying = omit_underlying
        self.closed = False
        self.expiry = "2026-07-17"
        self.codes = [
            option_code(self.expiry, "C", 700),
            option_code(self.expiry, "P", 700),
            option_code(self.expiry, "C", 710),
            option_code(self.expiry, "P", 710),
        ]

    def get_option_expiration_date(self, code):
        assert code == "US.QQQ"
        return 0, [
            {"strike_time": self.expiry, "option_expiry_date_distance": 7},
            {"strike_time": "2026-08-21", "option_expiry_date_distance": 42},
        ]

    def get_option_chain(self, code, start=None, end=None):
        assert code == "US.QQQ"
        assert start == self.expiry and end == self.expiry
        rows = []
        for code_value in self.codes:
            rows.append({
                "code": code_value,
                "strike_time": self.expiry,
                "strike_price": 700 if "00700000" in code_value else 710,
                "option_type": "CALL" if "C" in code_value[-9:] else "PUT",
                "lot_size": 100,
            })
        return 0, rows

    def get_market_snapshot(self, codes):
        if codes == ["US.QQQ"]:
            return 0, [{
                "code": "US.QQQ", "update_time": "2026-07-10 10:00:00",
                "last_price": 712.6, "bid_price": 712.59, "ask_price": 712.61,
            }]
        rows = []
        if not self.omit_underlying:
            rows.append({
                "code": "US.QQQ", "update_time": "2026-07-10 10:00:00",
                "last_price": 712.6, "bid_price": 712.59, "ask_price": 712.61,
            })
        option_time = "2026-07-10 10:01:00" if self.misaligned else "2026-07-10 10:00:05"
        for code in codes:
            if code == "US.QQQ":
                continue
            is_call = "C" in code[-9:]
            strike = 700 if "00700000" in code else 710
            intrinsic = max(712.6 - strike, 0) if is_call else max(strike - 712.6, 0)
            price = intrinsic + 4.0
            rows.append({
                "code": code,
                "update_time": option_time,
                "last_price": price,
                "bid_price": max(price - 0.05, 0.01),
                "ask_price": price + 0.05,
                "volume": 100,
                "option_open_interest": 200,
                "option_implied_volatility": 0.25,
                "option_delta": 0.5 if is_call else -0.5,
                "option_gamma": 0.01,
                "option_theta": -0.10,
                "option_vega": 0.20,
                "option_rho": 0.10 if is_call else -0.10,
            })
        return 0, rows

    def close(self):
        self.closed = True


class FakeModule:
    RET_OK = 0

    def __init__(self, context):
        self.context = context

    def OpenQuoteContext(self, host, port):
        self.context.host = host
        self.context.port = port
        return self.context


def fixed_times():
    values = iter([
        datetime(2026, 7, 10, 14, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 10, 14, 0, 1, tzinfo=timezone.utc),
    ])
    return lambda: next(values)


def test_parse_underlyings_deduplicates_and_normalizes():
    assert m.parse_underlyings("qqq, US.QQQ;soxx") == ["QQQ", "SOXX"]


def test_parse_underlyings_requires_value():
    with pytest.raises(ValueError):
        m.parse_underlyings(" , ")


def test_invalid_underlying_rejected():
    with pytest.raises(ValueError):
        m.normalize_underlying_symbol("QQQ;DROP")


def test_underlying_code():
    assert m.underlying_code("qqq") == "US.QQQ"


def test_parse_us_update_time_assumes_et_for_naive_timestamp():
    value = m.parse_us_update_time("2026-07-10 10:00:00")
    assert value is not None
    assert value.tzinfo == m.ET
    assert value.hour == 10


def test_parse_us_update_time_converts_utc():
    value = m.parse_us_update_time("2026-07-10T14:00:00Z")
    assert value is not None
    assert value.hour == 10


def test_option_type_from_code():
    assert m.parse_option_type("", option_code("2026-07-17", "C", 700)) == "CALL"
    assert m.parse_option_type("", option_code("2026-07-17", "P", 700)) == "PUT"


def test_strike_from_code():
    assert m.parse_strike("", option_code("2026-07-17", "C", 700)) == 700.0


def test_expiration_from_code():
    assert m.parse_expiration_from_code(option_code("2026-07-17", "C", 700)).isoformat() == "2026-07-17"



def test_actual_moomoo_six_digit_strike_code_parsing():
    code = "US.QQQ260706C495000"
    assert m.parse_option_type("", code) == "CALL"
    assert m.parse_strike("", code) == 495.0
    assert m.parse_expiration_from_code(code).isoformat() == "2026-07-06"

def test_chunked_enforces_positive_size():
    with pytest.raises(ValueError):
        m.chunked(["a"], 0)


def test_chunked_splits_values():
    assert m.chunked(["a", "b", "c"], 2) == [["a", "b"], ["c"]]


def test_select_expirations_filters_expired_and_out_of_range():
    rows = [
        {"strike_time": "2026-07-09", "option_expiry_date_distance": -1},
        {"strike_time": "2026-07-10", "option_expiry_date_distance": 0},
        {"strike_time": "2026-07-17", "option_expiry_date_distance": 7},
        {"strike_time": "2026-08-21", "option_expiry_date_distance": 42},
    ]
    as_of = datetime(2026, 7, 10, 10, 0, tzinfo=m.ET)
    result = m.select_expirations(rows, as_of, 0, 14)
    assert [item[0].isoformat() for item in result] == ["2026-07-10", "2026-07-17"]


def test_select_expirations_rejects_same_day_after_close():
    rows = [{"strike_time": "2026-07-10", "option_expiry_date_distance": 0}]
    as_of = datetime(2026, 7, 10, 16, 1, tzinfo=m.ET)
    assert m.select_expirations(rows, as_of, 0, 14) == []


def test_normalize_chain_row():
    code = option_code("2026-07-17", "P", 710)
    row = m.normalize_chain_row({"code": code, "strike_time": "2026-07-17", "strike_price": 710, "option_type": "PUT"}, "QQQ")
    assert row is not None
    assert row["option_type"] == "PUT"
    assert row["strike"] == 710


def test_select_contracts_prefers_near_money_within_expiry():
    rows = [
        {"option_code": "A", "expiration": "2026-07-17", "strike": 600, "option_type": "CALL"},
        {"option_code": "B", "expiration": "2026-07-17", "strike": 710, "option_type": "CALL"},
        {"option_code": "C", "expiration": "2026-07-17", "strike": 720, "option_type": "PUT"},
    ]
    selected = m.select_contracts(rows, 712.6, 2)
    assert [row["option_code"] for row in selected] == ["B", "C"]


def test_build_capture_row_has_explicit_timestamps_and_alignment():
    chain = {"option_code": option_code("2026-07-17", "C", 710), "underlying": "QQQ", "expiration": "2026-07-17", "strike": 710, "option_type": "CALL"}
    option = {"update_time": "2026-07-10 10:00:05", "bid_price": 5.0, "ask_price": 5.1, "last_price": 5.05}
    under = {"update_time": "2026-07-10 10:00:00", "last_price": 712.6}
    row = m.build_capture_row("cap", "batch", 1, datetime.now(timezone.utc), datetime.now(timezone.utc), chain, option, under, m.Config())
    assert row["option_quote_timestamp_explicit"] is True
    assert row["underlying_quote_timestamp_explicit"] is True
    assert row["quote_alignment_seconds"] == 5
    assert row["timestamp_alignment_pass"] is True
    assert row["same_snapshot_request"] is True


def test_build_capture_row_flags_misalignment():
    chain = {"option_code": option_code("2026-07-17", "C", 710), "underlying": "QQQ", "expiration": "2026-07-17", "strike": 710, "option_type": "CALL"}
    option = {"update_time": "2026-07-10 10:01:00", "bid_price": 5.0, "ask_price": 5.1, "last_price": 5.05}
    under = {"update_time": "2026-07-10 10:00:00", "last_price": 712.6}
    row = m.build_capture_row("cap", "batch", 1, datetime.now(timezone.utc), datetime.now(timezone.utc), chain, option, under, m.Config(max_alignment_seconds=15))
    assert row["timestamp_alignment_pass"] is False
    assert "MISALIGNED" in row["reason"]


def test_capture_symbol_returns_same_request_rows():
    ctx = FakeContext()
    rows, batches, chain_audit, static_count, exp_count = m.capture_symbol(
        ctx, "QQQ", "capture", datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4), 0,
        now_fn=fixed_times(),
    )
    assert len(rows) == 4
    assert len(batches) == 1
    assert all(row["same_snapshot_request"] for row in rows)
    assert all(row["timestamp_alignment_pass"] for row in rows)
    assert static_count == 4
    assert exp_count == 1
    assert chain_audit[0]["status"] == "PASS"


def test_capture_symbol_blocks_batch_without_underlying_row():
    ctx = FakeContext(omit_underlying=True)
    rows, batches, *_ = m.capture_symbol(
        ctx, "QQQ", "capture", datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4), 0,
        now_fn=fixed_times(),
    )
    assert rows == []
    assert batches[0]["underlying_row_found"] is False


def test_final_status_pass_requires_child_eligible_and_alignment():
    status, decision = m.final_status_for(
        100, 90, m.Config(min_alignment_pass_ratio=0.8), True, 0,
        {"final_status": "WARN_CHILD", "synthetic_iv_solved_count": 99, "research_ranking_eligible_count": 50},
    )
    assert status == m.PASS_STATUS
    assert decision == m.PASS_DECISION


def test_final_status_warn_when_no_eligible_child_rows():
    status, _ = m.final_status_for(
        100, 100, m.Config(), True, 0,
        {"final_status": "WARN_CHILD", "synthetic_iv_solved_count": 99, "research_ranking_eligible_count": 0},
    )
    assert status == m.WARN_STATUS


def test_final_status_fails_child_failure():
    status, _ = m.final_status_for(10, 10, m.Config(), True, 1, {"final_status": "FAIL_X"})
    assert status == m.FAIL_CHILD


def test_execute_capture_only_writes_outputs_and_closes_context(tmp_path):
    context = FakeContext()
    module = FakeModule(context)
    output = tmp_path / "out"
    summary = m.execute(
        tmp_path, output, ["QQQ"],
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        run_child=False, module=module, context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
    )
    assert summary["captured_option_row_count"] == 4
    assert summary["explicit_option_quote_timestamp_count"] == 4
    assert summary["timestamp_alignment_pass_count"] == 4
    assert summary["final_status"] == m.WARN_STATUS
    assert context.closed is True
    assert (output / "option_underlying_same_snapshot_capture_research_only.csv").exists()
    assert (output / "same_snapshot_batch_audit.csv").exists()
    assert (output / "v22_037_r2c_summary.json").exists()
    with (output / "option_underlying_same_snapshot_capture_research_only.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["option_quote_timestamp"]
    assert rows[0]["underlying_quote_timestamp"]
    assert rows[0]["broker_action_allowed"] == "False"


def test_regular_session_clock_pass():
    assert m.regular_session_clock_pass(datetime(2026, 7, 10, 10, 0, tzinfo=m.ET)) is True
    assert m.regular_session_clock_pass(datetime(2026, 7, 11, 10, 0, tzinfo=m.ET)) is False
    assert m.regular_session_clock_pass(datetime(2026, 7, 10, 8, 0, tzinfo=m.ET)) is False


def test_hard_policy_constants_remain_closed():
    assert m.RESEARCH_ONLY is True
    assert m.OFFICIAL_ADOPTION_ALLOWED is False
    assert m.BROKER_ACTION_ALLOWED is False
