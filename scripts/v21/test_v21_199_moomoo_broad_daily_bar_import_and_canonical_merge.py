from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts.data_sources.moomoo_canonical_merger import merge_canonical, quality_gate
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import fetch_history_daily
from scripts.data_sources.moomoo_snapshot_fetcher import batches


class FakeClient:
    module = SimpleNamespace(
        RET_OK=0,
        AuType=SimpleNamespace(QFQ="qfq", NONE="none"),
        KLType=SimpleNamespace(K_DAY="K_DAY"),
    )

    def __init__(self):
        self.calls = []

    def checked_call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "request_history_kline":
            key = kwargs.get("page_req_key")
            if key is None:
                return (
                    pd.DataFrame([{"time_key": "2026-06-29 00:00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]),
                    "NEXT",
                )
            return (
                pd.DataFrame([{"time_key": "2026-06-30 00:00:00", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 11}]),
                None,
            )
        raise AssertionError(name)


def staging(rows):
    return pd.DataFrame(rows)


def good_rows(date="2026-06-30"):
    return [
        {"internal_symbol": "AAPL", "date": date, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"internal_symbol": "QQQ", "date": date, "open": 20, "high": 21, "low": 19, "close": 20.5, "volume": 100},
        {"internal_symbol": "DRAM", "date": date, "open": 30, "high": 31, "low": 29, "close": 30.5, "volume": 100},
    ]


def test_pagination_handling():
    client = FakeClient()
    frame = fetch_history_daily(client, "AAPL", "US.AAPL", adjustment_mode="QFQ")
    assert list(frame["date"]) == ["2026-06-29", "2026-06-30"]
    assert client.calls[1][1]["page_req_key"] == "NEXT"


def test_duplicate_symbol_date_detection():
    rows = good_rows() + [good_rows()[0]]
    passed, summary, _coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.95)
    assert passed is False
    assert summary["duplicate_symbol_date_rows"] == 1


def test_broad_date_coverage_insufficient():
    rows = [good_rows()[0]]
    passed, summary, coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.95)
    assert passed is False
    assert summary["latest_moomoo_broad_honest_date"] == ""
    assert coverage["coverage_ratio"].iloc[0] < 0.95


def test_dram_stale_or_missing():
    rows = good_rows("2026-06-30")
    rows[-1]["date"] = "2026-06-29"
    passed, summary, _coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.66)
    assert passed is False
    assert summary["dram_latest_date"] == "2026-06-29"
    assert summary["dram_present_and_current"] is False


def test_raw_max_date_later_than_broad_honest_latest_date():
    rows = good_rows("2026-06-30") + [{"internal_symbol": "AAPL", "date": "2026-07-01", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}]
    passed, summary, _coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.95)
    assert passed is False
    assert summary["raw_max_date"] == "2026-07-01"
    assert summary["latest_moomoo_broad_honest_date"] == "2026-06-30"
    assert summary["raw_max_date_later_than_broad_honest_latest_date"] is True


def test_adjusted_ohlc_envelope_anomaly_is_diagnostic_not_blocking():
    rows = good_rows("2026-07-01")
    rows[0]["high"] = rows[0]["open"] - 0.01
    passed, summary, _coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.95)
    assert passed is True
    assert summary["ohlc_sanity_failure_rows"] == 1
    assert summary["ohlcv_required_field_failure_rows"] == 0


def test_required_ohlcv_null_blocks_gate():
    rows = good_rows("2026-07-01")
    rows[0]["volume"] = pd.NA
    passed, summary, _coverage = quality_gate(staging(rows), ["AAPL", "QQQ", "DRAM"], min_coverage_ratio=0.95)
    assert passed is False
    assert summary["ohlcv_required_field_failure_rows"] == 1


def test_snapshot_batching_lte_400():
    chunks = batches([f"US.X{i}" for i in range(801)], batch_size=400)
    assert [len(c) for c in chunks] == [400, 400, 1]


def test_no_canonical_mutation_when_gates_fail(tmp_path):
    canonical = tmp_path / "canonical.csv"
    canonical.write_text("symbol,date,open,high,low,close,adjusted_close,volume\nAAPL,2026-06-28,1,1,1,1,1,1\n", encoding="utf-8")
    before = canonical.read_text(encoding="utf-8")
    result = merge_canonical(staging([good_rows()[0]]), staging([good_rows()[0]]), ["AAPL", "QQQ", "DRAM"], research_canonical_path=canonical, trade_plan_canonical_path=tmp_path / "raw.csv")
    assert result["canonical_updated"] is False
    assert canonical.read_text(encoding="utf-8") == before


def test_backup_versioned_canonical_mutation_when_gates_pass(tmp_path):
    canonical = tmp_path / "canonical.csv"
    raw = tmp_path / "raw.csv"
    canonical.write_text("symbol,date,open,high,low,close,adjusted_close,volume\nAAPL,2026-06-28,1,1,1,1,1,1\n", encoding="utf-8")
    result = merge_canonical(
        staging(good_rows()),
        staging(good_rows()),
        ["AAPL", "QQQ", "DRAM"],
        research_canonical_path=canonical,
        trade_plan_canonical_path=raw,
        backup_dir=tmp_path / "backups",
    )
    assert result["canonical_updated"] is True
    assert result["research_backup_path"]
    assert pd.read_csv(canonical)["date"].max() == "2026-06-30"
