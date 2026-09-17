"""Synthetic raw/event reader boundaries; never calls the real-data entrypoint."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pytest

from scripts.research.a2.factors import economic_return_inputs as reader


def raw_rows(dates=("2025-12-30", "2025-12-31", "2026-01-02"), code="US.TEST"):
    return pd.DataFrame({"code": code, "time_key": [day + " 00:00:00" for day in dates],
                         "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0, "volume": 1000.0})


def spying_factory(date_column, observations, *, lower=None):
    original_dataset = ds.dataset

    class FilteredTable:
        def __init__(self, table):
            self.table = table

        def to_pandas(self):
            # This checks the Arrow table BEFORE any pandas materialization.
            dates = self.table.column(date_column).to_pylist()
            assert all(day[:10] < "2026-01-01" for day in dates)
            if lower is not None:
                assert all(day[:10] >= lower for day in dates)
            observations.append({"stage": "BEFORE_PANDAS", "rows": len(dates)})
            return self.table.to_pandas()

    class FilteredDataset:
        def __init__(self, path, **kwargs):
            self.dataset = original_dataset(path, **kwargs)

        def to_table(self, *, filter=None, **kwargs):
            assert filter is not None
            return FilteredTable(self.dataset.to_table(filter=filter, **kwargs))

    return FilteredDataset


def test_frozen_r5_stock_reader_filters_2026_and_wrong_code_before_pandas(tmp_path, monkeypatch):
    path = tmp_path / "raw.parquet"
    rows = pd.concat([raw_rows(), raw_rows(("2025-12-30",), code="US.OTHER")], ignore_index=True)
    rows.loc[rows.time_key.str.startswith("2026"), "close"] = 1e8
    rows.to_parquet(path, index=False)
    r5, _, _ = reader.load_tail_definitions().load_sources()
    observations = []
    factory = spying_factory("time_key", observations)
    # Scoped test instrumentation of the existing helper, no production patch.
    monkeypatch.setattr(r5.pads, "dataset", factory)
    result = reader.read_stock({"ticker": "TEST", "moomoo_transport_code": "US.TEST", "raw_source_path": str(path)}, r5)
    assert len(result) == 2
    assert result.ticker.eq("TEST").all() and result.code.eq("US.TEST").all()
    assert result.close.eq(101).all()
    assert observations == [{"stage": "BEFORE_PANDAS", "rows": 2}]


def test_qqq_reader_applies_both_date_bounds_before_pandas(tmp_path):
    path = tmp_path / "qqq.parquet"
    rows = raw_rows(("2019-12-31", "2020-01-02", "2025-12-31", "2026-01-02")).drop(columns="code")
    rows["date"] = rows.pop("time_key").str[:10]
    rows["ticker"], rows["moomoo_symbol"] = "QQQ", "US.QQQ"
    rows.to_parquet(path, index=False)
    observations = []
    result = reader.read_qqq({"ticker": "QQQ", "moomoo_transport_code": "US.QQQ", "raw_source_path": str(path)},
                             dataset_factory=spying_factory("date", observations, lower="2020-01-01"))
    assert len(result) == 2 and result.autype.eq("RAW_UNADJUSTED").all()
    assert observations == [{"stage": "BEFORE_PANDAS", "rows": 2}]


def test_events_filter_dates_and_codes_preserving_all_action_fields(tmp_path):
    path = tmp_path / "events.parquet"
    events = pd.DataFrame({"code": ["US.TEST", "US.TEST", "US.TEST", "US.OTHER"],
        "ex_div_date": ["2019-12-31", "2025-12-31", "2026-01-02", "2025-12-31"],
        "per_cash_div": [2.0] * 4, "special_dividend": [4.5] * 4, "split_ratio": [3.0] * 4,
        "split_base": [1.0] * 4, "split_ert": [3.0] * 4, "join_base": [None] * 4,
        "join_ert": [None] * 4, "spin_off_ratio": [0.1] * 4, "uninterpreted_vendor_field": [123] * 4})
    events.to_parquet(path, index=False)
    observations = []
    result = reader.read_events(path, {"US.TEST"}, dataset_factory=spying_factory("ex_div_date", observations, lower="2020-01-01"))
    assert len(result) == 1 and result.iloc[0].uninterpreted_vendor_field == 123
    assert result.iloc[0].per_cash_div == 2.0 and result.iloc[0].special_dividend == 4.5
    assert result.iloc[0].split_ratio == 3.0
    assert observations == [{"stage": "BEFORE_PANDAS", "rows": 1}]


@pytest.mark.parametrize("problem", ["wrong_code", "duplicate", "zero", "infinite", "negative_volume", "2026", "invalid_high"])
def test_post_read_identity_price_and_date_fail_closed(problem):
    frame = raw_rows(("2025-12-30", "2025-12-31"))
    frame["trade_date"] = pd.to_datetime(frame.time_key)
    if problem == "wrong_code":
        frame.loc[0, "code"] = "US.OTHER"
    elif problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif problem == "zero":
        frame.loc[0, "close"] = 0.0
    elif problem == "infinite":
        frame.loc[0, "close"] = np.inf
    elif problem == "negative_volume":
        frame.loc[0, "volume"] = -1.0
    elif problem == "2026":
        frame.loc[0, "trade_date"] = pd.Timestamp("2026-01-02")
    else:
        frame.loc[0, "high"] = 90
    with pytest.raises(RuntimeError):
        reader.normalize_raw(frame, ticker="TEST", code="US.TEST")


def test_frozen_stock_reader_rejects_conflicting_duplicates(tmp_path):
    path = tmp_path / "duplicate.parquet"
    frame = raw_rows(("2025-12-30", "2025-12-30"))
    frame.loc[1, "close"] = 100.5
    frame.to_parquet(path, index=False)
    r5, _, _ = reader.load_tail_definitions().load_sources()
    with pytest.raises(RuntimeError, match="CONFLICTING_RAW_DUPLICATE"):
        reader.read_stock({"ticker": "TEST", "moomoo_transport_code": "US.TEST", "raw_source_path": str(path)}, r5)


def test_calendar_guard_requires_exact_qqq_sessions_and_preserves_stock_gaps():
    calendar = pd.bdate_range("2025-12-29", periods=3)
    raw = pd.DataFrame({"ticker": ["QQQ"] * 3 + ["TEST"] * 2,
                        "trade_date": [*calendar, calendar[0], calendar[2]]})
    reader.validate_calendar(raw, calendar, {"TEST"})
    assert len(raw) == 5  # No manufactured missing stock observation.
    with pytest.raises(RuntimeError, match="RAW_QQQ_CALENDAR_MISMATCH"):
        reader.validate_calendar(raw.iloc[1:], calendar, {"TEST"})


def test_contract_and_hash_tampering_fail_before_body_access(tmp_path):
    bindings = tmp_path / "bindings.json"
    bindings.write_text(json.dumps({"status": "PASS_STRUCTURAL_BINDINGS_NOT_RETURN_CERTIFICATION",
        "equity_count": 644, "equities": [{}] * 644, "failures": []}), encoding="utf-8")
    contract_path = tmp_path / "contract.json"
    contract = {"status": "FROZEN_PRE2026_RAW_READ", "cutoff_exclusive": "2026-01-01",
                "start_inclusive": "2020-01-01", "oldtarget_retained_as_reference_only": True,
                "reader_source_sha256": reader.sha(Path(reader.__file__)), "bindings_sha256": reader.sha(bindings)}
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    reader.read_contract(contract_path, bindings)
    bindings.write_text(bindings.read_text() + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="RAW_BINDINGS_NOT_FROZEN"):
        reader.read_contract(contract_path, bindings)
    with pytest.raises(RuntimeError, match="RAW_INPUT_HASH_MISMATCH"):
        reader.check_hashes({str(bindings): contract["bindings_sha256"]})
