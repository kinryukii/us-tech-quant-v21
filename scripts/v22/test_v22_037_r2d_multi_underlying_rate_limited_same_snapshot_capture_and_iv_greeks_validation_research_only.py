from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name(
    "v22_037_r2d_multi_underlying_rate_limited_same_snapshot_capture_and_iv_greeks_validation_research_only.py"
)
SPEC = importlib.util.spec_from_file_location("v22_037_r2d", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def option_code(symbol: str, expiry: str, side: str, strike: int) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    return f"US.{symbol}{yymmdd}{side}{strike * 1000:08d}"


class FakeContext:
    def __init__(
        self,
        host="127.0.0.1",
        port=11111,
        *,
        symbols=("QQQ",),
        expiries=("2026-07-17",),
        misaligned=False,
        omit_underlying=False,
        rate_limit_once=False,
        fail_chain_symbols=(),
    ):
        self.host = host
        self.port = port
        self.symbols = tuple(symbols)
        self.expiries = tuple(expiries)
        self.misaligned = misaligned
        self.omit_underlying = omit_underlying
        self.rate_limit_once = rate_limit_once
        self.fail_chain_symbols = set(fail_chain_symbols)
        self.closed = False
        self.chain_calls: list[tuple[str, str, str]] = []
        self.expiration_calls: list[str] = []
        self.snapshot_calls: list[list[str]] = []
        self.rate_limited_already = False

    def _symbol(self, code: str) -> str:
        return code[3:].split("26", 1)[0]

    def get_option_expiration_date(self, code):
        symbol = code.replace("US.", "")
        self.expiration_calls.append(symbol)
        if symbol not in self.symbols:
            return -1, f"unsupported {symbol}"
        rows = []
        base = datetime(2026, 7, 10).date()
        for expiry in self.expiries:
            distance = (datetime.fromisoformat(expiry).date() - base).days
            rows.append({"strike_time": expiry, "option_expiry_date_distance": distance})
        rows.append({"strike_time": "2026-08-21", "option_expiry_date_distance": 42})
        return 0, rows

    def get_option_chain(self, code, start=None, end=None):
        symbol = code.replace("US.", "")
        self.chain_calls.append((symbol, start, end))
        if symbol in self.fail_chain_symbols:
            return -1, "permission denied"
        if self.rate_limit_once and not self.rate_limited_already:
            self.rate_limited_already = True
            return -1, "frequency limit: maximum 10 requests per 30 seconds"
        rows = []
        for expiry in self.expiries:
            if start <= expiry <= end:
                for strike in (700, 710):
                    for side in ("C", "P"):
                        code_value = option_code(symbol, expiry, side, strike)
                        rows.append({
                            "code": code_value,
                            "strike_time": expiry,
                            "strike_price": strike,
                            "option_type": "CALL" if side == "C" else "PUT",
                            "lot_size": 100,
                        })
        return 0, rows

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        if len(codes) == 1:
            symbol = codes[0].replace("US.", "")
            return 0, [{
                "code": f"US.{symbol}",
                "update_time": "2026-07-10 10:00:00",
                "last_price": 712.6,
                "bid_price": 712.59,
                "ask_price": 712.61,
            }]
        symbol = codes[0].replace("US.", "")
        rows = []
        if not self.omit_underlying:
            rows.append({
                "code": f"US.{symbol}",
                "update_time": "2026-07-10 10:00:00",
                "last_price": 712.6,
                "bid_price": 712.59,
                "ask_price": 712.61,
            })
        option_time = "2026-07-10 10:01:00" if self.misaligned else "2026-07-10 10:00:05"
        for code in codes[1:]:
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


def fixed_times(count=20):
    values = iter([
        datetime(2026, 7, 10, 14, 0, i, tzinfo=timezone.utc)
        for i in range(count)
    ])
    return lambda: next(values)


def no_wait_limiter():
    return m.SlidingWindowRateLimiter(100, 30.0, sleep_fn=lambda _: None)


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
    assert value is not None and value.tzinfo == m.ET and value.hour == 10


def test_parse_us_update_time_converts_utc():
    value = m.parse_us_update_time("2026-07-10T14:00:00Z")
    assert value is not None and value.hour == 10


def test_option_type_strike_and_expiration_from_code():
    code = option_code("QQQ", "2026-07-17", "C", 700)
    assert m.parse_option_type("", code) == "CALL"
    assert m.parse_strike("", code) == 700.0
    assert m.parse_expiration_from_code(code).isoformat() == "2026-07-17"


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
    code = option_code("QQQ", "2026-07-17", "P", 710)
    row = m.normalize_chain_row({
        "code": code,
        "strike_time": "2026-07-17",
        "strike_price": 710,
        "option_type": "PUT",
    }, "QQQ")
    assert row is not None and row["option_type"] == "PUT" and row["strike"] == 710


def test_select_contracts_prefers_near_money_within_expiry():
    rows = [
        {"option_code": "A", "expiration": "2026-07-17", "strike": 600, "option_type": "CALL"},
        {"option_code": "B", "expiration": "2026-07-17", "strike": 710, "option_type": "CALL"},
        {"option_code": "C", "expiration": "2026-07-17", "strike": 720, "option_type": "PUT"},
    ]
    selected = m.select_contracts(rows, 712.6, 2)
    assert [row["option_code"] for row in selected] == ["B", "C"]


def test_is_rate_limit_error_recognizes_common_messages():
    assert m.is_rate_limit_error("frequency limit: 10 requests per 30 seconds")
    assert m.is_rate_limit_error("请求太频繁")
    assert not m.is_rate_limit_error("permission denied")


def test_sliding_window_rate_limiter_waits_after_cap():
    clock = [0.0]
    sleeps = []

    def monotonic():
        return clock[0]

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    limiter = m.SlidingWindowRateLimiter(2, 10.0, monotonic_fn=monotonic, sleep_fn=sleep)
    limiter.acquire()
    clock[0] = 1.0
    limiter.acquire()
    clock[0] = 2.0
    waited = limiter.acquire()
    assert waited >= 8.0
    assert limiter.wait_count == 1
    assert sleeps


def test_collect_static_chain_uses_one_range_request_for_multiple_expirations():
    ctx = FakeContext(expiries=("2026-07-13", "2026-07-17"))
    rows, audit, exp_count, request_count, retries = m.collect_static_chain(
        ctx,
        "QQQ",
        datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(),
        0,
        no_wait_limiter(),
        now_fn=fixed_times(),
    )
    assert exp_count == 2
    assert request_count == 1
    assert retries == 0
    assert len(ctx.chain_calls) == 1
    assert ctx.chain_calls[0] == ("QQQ", "2026-07-13", "2026-07-17")
    assert len(rows) == 8
    assert {row["status"] for row in audit} == {"PASS"}


def test_option_chain_rate_limit_is_retried_once():
    ctx = FakeContext(rate_limit_once=True)
    sleeps = []
    rows, audit, exp_count, request_count, retries = m.collect_static_chain(
        ctx,
        "QQQ",
        datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(option_chain_retry_seconds=0.0, option_chain_max_attempts=2),
        0,
        no_wait_limiter(),
        sleep_fn=lambda seconds: sleeps.append(seconds),
        now_fn=fixed_times(),
    )
    assert len(rows) == 4
    assert len(ctx.chain_calls) == 2
    assert retries == 1
    assert request_count == 1
    assert audit[0]["request_attempts"] == 2


def test_non_rate_limit_chain_error_is_not_retried():
    ctx = FakeContext(fail_chain_symbols=("QQQ",))
    rows, audit, _, _, retries = m.collect_static_chain(
        ctx,
        "QQQ",
        datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(option_chain_max_attempts=3),
        0,
        no_wait_limiter(),
        now_fn=fixed_times(),
    )
    assert rows == []
    assert len(ctx.chain_calls) == 1
    assert retries == 0
    assert audit[0]["status"] == "FAIL"


def test_build_capture_row_has_explicit_timestamps_and_alignment():
    chain = {
        "option_code": option_code("QQQ", "2026-07-17", "C", 710),
        "underlying": "QQQ",
        "expiration": "2026-07-17",
        "strike": 710,
        "option_type": "CALL",
    }
    option = {"update_time": "2026-07-10 10:00:05", "bid_price": 5.0, "ask_price": 5.1, "last_price": 5.05}
    under = {"update_time": "2026-07-10 10:00:00", "last_price": 712.6}
    row = m.build_capture_row(
        "cap", "batch", 1, datetime.now(timezone.utc), datetime.now(timezone.utc),
        chain, option, under, m.Config(),
    )
    assert row["option_quote_timestamp_explicit"] is True
    assert row["underlying_quote_timestamp_explicit"] is True
    assert row["quote_alignment_seconds"] == 5
    assert row["timestamp_alignment_pass"] is True


def test_build_capture_row_flags_misalignment():
    chain = {
        "option_code": option_code("QQQ", "2026-07-17", "C", 710),
        "underlying": "QQQ",
        "expiration": "2026-07-17",
        "strike": 710,
        "option_type": "CALL",
    }
    option = {"update_time": "2026-07-10 10:01:00", "bid_price": 5.0, "ask_price": 5.1, "last_price": 5.05}
    under = {"update_time": "2026-07-10 10:00:00", "last_price": 712.6}
    row = m.build_capture_row(
        "cap", "batch", 1, datetime.now(timezone.utc), datetime.now(timezone.utc),
        chain, option, under, m.Config(max_alignment_seconds=15),
    )
    assert row["timestamp_alignment_pass"] is False
    assert "MISALIGNED" in row["reason"]


def test_capture_symbol_returns_same_request_rows():
    ctx = FakeContext()
    rows, batches, chain_audit, static_count, exp_count, requests, retries = m.capture_symbol(
        ctx,
        "QQQ",
        "capture",
        datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        0,
        no_wait_limiter(),
        now_fn=fixed_times(),
    )
    assert len(rows) == 4
    assert len(batches) == 1
    assert all(row["same_snapshot_request"] for row in rows)
    assert all(row["timestamp_alignment_pass"] for row in rows)
    assert static_count == 4 and exp_count == 1 and requests == 1 and retries == 0
    assert chain_audit[0]["status"] == "PASS"


def test_capture_symbol_blocks_batch_without_underlying_row():
    ctx = FakeContext(omit_underlying=True)
    rows, batches, *_ = m.capture_symbol(
        ctx,
        "QQQ",
        "capture",
        datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        0,
        no_wait_limiter(),
        now_fn=fixed_times(),
    )
    assert rows == []
    assert batches[0]["underlying_row_found"] is False


def test_final_status_pass_requires_regular_session_child_eligible_and_alignment():
    status, decision = m.final_status_for(
        100,
        90,
        m.Config(min_alignment_pass_ratio=0.8),
        True,
        0,
        {"final_status": "WARN_CHILD", "synthetic_iv_solved_count": 99, "research_ranking_eligible_count": 50},
        regular_session_pass=True,
    )
    assert status == m.PASS_STATUS and decision == m.PASS_DECISION


def test_final_status_warn_outside_regular_session():
    status, _ = m.final_status_for(
        100,
        100,
        m.Config(),
        True,
        0,
        {"final_status": "WARN_CHILD", "synthetic_iv_solved_count": 99, "research_ranking_eligible_count": 50},
        regular_session_pass=False,
    )
    assert status == m.WARN_STATUS


def test_final_status_warn_partial_underlying():
    status, decision = m.final_status_for(
        100,
        100,
        m.Config(),
        True,
        0,
        {"final_status": "WARN_CHILD", "synthetic_iv_solved_count": 99, "research_ranking_eligible_count": 50},
        underlying_failure_count=1,
        regular_session_pass=True,
    )
    assert status == m.WARN_PARTIAL_STATUS
    assert decision == m.WARN_PARTIAL_DECISION


def test_final_status_fails_child_failure():
    status, _ = m.final_status_for(10, 10, m.Config(), True, 1, {"final_status": "FAIL_X"})
    assert status == m.FAIL_CHILD


def test_execute_multi_underlying_capture_only_writes_isolated_outputs(tmp_path):
    context = FakeContext(symbols=("QQQ", "SOXX"))
    module = FakeModule(context)
    output_root = tmp_path / "out"
    summary = m.execute(
        tmp_path,
        output_root,
        ["QQQ", "SOXX"],
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        run_child=False,
        module=module,
        context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        limiter=no_wait_limiter(),
    )
    run_dir = Path(summary["output_dir"])
    assert summary["captured_option_row_count"] == 8
    assert summary["underlying_success_count"] == 2
    assert summary["underlying_failure_count"] == 0
    assert summary["option_chain_request_count"] == 2
    assert len(context.chain_calls) == 2
    assert context.closed is True
    assert run_dir.parent.name == "runs"
    assert (run_dir / "option_underlying_same_snapshot_capture_research_only.csv").exists()
    assert (run_dir / "underlying_capture_audit.csv").exists()
    assert (run_dir / "v22_037_r2d_summary.json").exists()
    pointer = json.loads((output_root / "latest_run.json").read_text(encoding="utf-8"))
    assert pointer["summary_path"] == str(run_dir / "v22_037_r2d_summary.json")


def test_execute_continues_after_one_underlying_failure(tmp_path):
    context = FakeContext(symbols=("QQQ", "SOXX"), fail_chain_symbols=("SOXX",))
    module = FakeModule(context)
    summary = m.execute(
        tmp_path,
        tmp_path / "out",
        ["QQQ", "SOXX"],
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        run_child=False,
        module=module,
        context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        limiter=no_wait_limiter(),
    )
    assert summary["captured_option_row_count"] == 4
    assert summary["underlying_success_count"] == 1
    assert summary["underlying_failure_count"] == 1
    assert summary["final_status"] == m.WARN_PARTIAL_STATUS
    with Path(summary["underlying_audit_path"]).open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["underlying"]: row["status"] for row in rows} == {"QQQ": "PASS", "SOXX": "FAIL"}


def test_execute_all_underlyings_fail_is_fail_capture(tmp_path):
    context = FakeContext(symbols=("QQQ", "SOXX"), fail_chain_symbols=("QQQ", "SOXX"))
    module = FakeModule(context)
    summary = m.execute(
        tmp_path,
        tmp_path / "out",
        ["QQQ", "SOXX"],
        m.Config(),
        run_child=False,
        module=module,
        context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        limiter=no_wait_limiter(),
    )
    assert summary["captured_option_row_count"] == 0
    assert summary["underlying_failure_count"] == 2
    assert summary["final_status"] == m.FAIL_CAPTURE


def test_execute_two_runs_do_not_overwrite_each_other(tmp_path):
    output_root = tmp_path / "out"
    for _ in range(2):
        context = FakeContext()
        module = FakeModule(context)
        summary = m.execute(
            tmp_path,
            output_root,
            ["QQQ"],
            m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
            run_child=False,
            module=module,
            context_factory=module.OpenQuoteContext,
            as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
            limiter=no_wait_limiter(),
        )
        assert Path(summary["output_dir"]).exists()
    run_dirs = [path for path in (output_root / "runs").iterdir() if path.is_dir()]
    assert len(run_dirs) == 2



def test_execute_rate_limit_retry_recovers(tmp_path):
    context = FakeContext(rate_limit_once=True)
    module = FakeModule(context)
    summary = m.execute(
        tmp_path,
        tmp_path / "out",
        ["QQQ"],
        m.Config(
            max_contracts_per_underlying=4,
            snapshot_option_batch_size=4,
            option_chain_retry_seconds=0.0,
            option_chain_max_attempts=2,
        ),
        run_child=False,
        module=module,
        context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        limiter=no_wait_limiter(),
        sleep_fn=lambda _: None,
    )
    assert summary["captured_option_row_count"] == 4
    assert summary["rate_limit_retry_count"] == 1
    assert len(context.chain_calls) == 2


def test_execute_with_eligible_child_can_pass(tmp_path, monkeypatch):
    context = FakeContext()
    module = FakeModule(context)

    def fake_child(repo_root, capture_input, child_output_dir, config):
        return 0, {
            "final_status": "WARN_CHILD",
            "final_decision": "CHILD_RESEARCH_ONLY",
            "synthetic_iv_solved_count": 4,
            "synthetic_iv_coverage_ratio": 1.0,
            "greeks_valid_count": 4,
            "research_ranking_eligible_count": 4,
            "research_ranking_eligible_ratio": 1.0,
            "quality_tier_a_count": 4,
            "quality_tier_b_count": 0,
            "quality_tier_c_count": 0,
            "quality_rejected_count": 0,
        }, child_output_dir / "v22_037_r2b_summary.json"

    monkeypatch.setattr(m, "run_iv_child", fake_child)
    summary = m.execute(
        tmp_path,
        tmp_path / "out",
        ["QQQ"],
        m.Config(max_contracts_per_underlying=4, snapshot_option_batch_size=4),
        run_child=True,
        module=module,
        context_factory=module.OpenQuoteContext,
        as_of_et=datetime(2026, 7, 10, 10, 0, tzinfo=m.ET),
        limiter=no_wait_limiter(),
    )
    assert summary["final_status"] == m.PASS_STATUS
    assert summary["research_ranking_eligible_count"] == 4
    assert summary["quality_tier_a_count"] == 4

def test_regular_session_clock_pass():
    assert m.regular_session_clock_pass(datetime(2026, 7, 10, 10, 0, tzinfo=m.ET)) is True
    assert m.regular_session_clock_pass(datetime(2026, 7, 11, 10, 0, tzinfo=m.ET)) is False
    assert m.regular_session_clock_pass(datetime(2026, 7, 10, 8, 0, tzinfo=m.ET)) is False


def test_render_report_includes_rate_limit_metrics():
    text = m.render_report({
        "revision": m.REVISION,
        "final_status": m.WARN_STATUS,
        "final_decision": m.WARN_DECISION,
        "underlyings_requested": "QQQ,SOXX",
        "underlying_success_count": 2,
        "underlying_failure_count": 0,
        "option_chain_request_count": 2,
        "rate_limit_retry_count": 1,
        "timestamp_alignment_pass_ratio": 0.0,
    })
    assert "Option-chain requests: 2" in text
    assert "Rate-limit retries: 1" in text


def test_hard_policy_constants_remain_closed():
    assert m.RESEARCH_ONLY is True
    assert m.OFFICIAL_ADOPTION_ALLOWED is False
    assert m.BROKER_ACTION_ALLOWED is False
