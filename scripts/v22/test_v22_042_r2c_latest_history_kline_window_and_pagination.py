from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("v22_042_option_intraday_etf_direction_gate_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_042_r2c", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class FakeData:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self.rows)


class FakeKLType:
    K_1M = "K_1M"
    K_15M = "K_15M"
    K_60M = "K_60M"


class FakeContext:
    def __init__(self):
        self.calls = []
        self.closed = False

    @staticmethod
    def rows_for(ktype, page):
        base = {
            "K_1M": [
                "2026-07-09 15:58:00",
                "2026-07-09 15:59:00",
                "2026-07-10 09:30:00",
                "2026-07-10 09:31:00",
                "2026-07-10 09:32:00",
                "2026-07-10 09:33:00",
            ],
            "K_15M": [
                "2026-07-09 15:15:00",
                "2026-07-09 15:30:00",
                "2026-07-09 15:45:00",
                "2026-07-10 09:30:00",
                "2026-07-10 09:45:00",
                "2026-07-10 10:00:00",
            ],
            "K_60M": [
                "2026-07-09 13:30:00",
                "2026-07-09 14:30:00",
                "2026-07-09 15:30:00",
                "2026-07-10 09:30:00",
                "2026-07-10 10:30:00",
                "2026-07-10 11:30:00",
            ],
        }[ktype]
        chosen = base[:3] if page == 1 else base[3:]
        return [
            {
                "time_key": value,
                "open": 100.0 + i,
                "high": 100.5 + i,
                "low": 99.5 + i,
                "close": 100.25 + i,
                "volume": 1000 + i,
            }
            for i, value in enumerate(chosen)
        ]

    def request_history_kline(self, **kwargs):
        self.calls.append(dict(kwargs))
        page = 2 if kwargs.get("page_req_key") is not None else 1
        next_key = None if page == 2 else b"next"
        return 0, FakeData(self.rows_for(kwargs["ktype"], page)), next_key

    def close(self):
        self.closed = True


class FakeModule:
    KLType = FakeKLType
    context = FakeContext()

    @classmethod
    def OpenQuoteContext(cls, host, port):
        assert host == "127.0.0.1"
        assert port == 11111
        return cls.context


def test_fetch_pages_to_end_and_keeps_latest_n(monkeypatch, tmp_path):
    FakeModule.context = FakeContext()
    monkeypatch.setattr(module, "opend_port_reachable", lambda *_args, **_kwargs: True)

    bars, connected = module.fetch_intraday_bars(
        tmp_path,
        "127.0.0.1",
        11111,
        4,
        import_func=lambda _name: FakeModule,
    )

    assert connected is True
    assert FakeModule.context.closed is True
    assert len(FakeModule.context.calls) == 18  # 3 symbols x 3 timeframes x 2 pages

    for symbol in module.DIRECTION_UNDERLYINGS:
        assert [row["time_key"] for row in bars[symbol]["1m"]] == [
            "2026-07-10 09:30:00",
            "2026-07-10 09:31:00",
            "2026-07-10 09:32:00",
            "2026-07-10 09:33:00",
        ]
        assert len(bars[symbol]["15m"]) == 4
        assert len(bars[symbol]["1h"]) == 4

    for call in FakeModule.context.calls:
        assert call["start"]
        assert call["end"]
        assert call["max_count"] == module.HISTORY_FETCH_PAGE_SIZE

    second_page_calls = [call for call in FakeModule.context.calls if "page_req_key" in call]
    assert len(second_page_calls) == 9
    assert all(call["page_req_key"] == b"next" for call in second_page_calls)


def test_timeframe_windows_are_explicit_and_sized_for_bar_density():
    one_start, one_end = module.history_request_window("1m")
    fifteen_start, fifteen_end = module.history_request_window("15m")
    hour_start, hour_end = module.history_request_window("1h")

    assert one_end == fifteen_end == hour_end
    one_days = (date.fromisoformat(one_end) - date.fromisoformat(one_start)).days
    fifteen_days = (date.fromisoformat(fifteen_end) - date.fromisoformat(fifteen_start)).days
    hour_days = (date.fromisoformat(hour_end) - date.fromisoformat(hour_start)).days
    assert one_days == 10
    assert fifteen_days == 30
    assert hour_days == 120
    assert one_days < fifteen_days < hour_days


def test_timestamp_provenance_records_latest_fetch_contract(monkeypatch, tmp_path):
    FakeModule.context = FakeContext()
    monkeypatch.setattr(module, "opend_port_reachable", lambda *_args, **_kwargs: True)
    bars, _ = module.fetch_intraday_bars(
        tmp_path,
        "127.0.0.1",
        11111,
        4,
        import_func=lambda _name: FakeModule,
    )
    rows, context = module.build_timestamp_provenance(bars, 4, True, False)

    assert len(rows) == 9
    assert context["direction_timestamp_complete"] is True
    assert context["direction_source_time_trust"] == "HIGH"
    assert context["direction_source_time_utc"].startswith("2026-07-10T")
    assert all(row["history_fetch_contract_version"] == module.HISTORY_FETCH_CONTRACT_VERSION for row in rows)
    assert all(row["history_fetch_policy"] == module.HISTORY_FETCH_POLICY for row in rows)
    assert all(int(row["history_pages_fetched"]) == 2 for row in rows)
    assert all(int(row["history_raw_row_count"]) == 6 for row in rows)
    assert all(int(row["history_selected_latest_row_count"]) == 4 for row in rows)


def test_page_failure_discards_partial_history():
    calls = []

    def method(**kwargs):
        calls.append(kwargs)
        if kwargs.get("page_req_key") is None:
            return 0, FakeData(FakeContext.rows_for("K_1M", 1)), b"next"
        return -1, "simulated failure", None

    rows, metadata = module.latest_history_rows(method, "US.SOXX", "K_1M", "1m", 4)
    assert rows == []
    assert metadata["history_pages_fetched"] == 1
    assert metadata["history_selected_latest_row_count"] == 0
    assert len(calls) == 2


def test_source_contract_prohibits_default_365_day_first_page_fetch():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "V22.042_R2C_LATEST_HISTORY_KLINE_WINDOW_AND_PAGINATION" in source
    assert '"start": start_date' in source
    assert '"end": end_date' in source
    assert 'kwargs["page_req_key"] = page_key' in source
    assert "ordered[-max(int(requested_bar_count), 0):]" in source
