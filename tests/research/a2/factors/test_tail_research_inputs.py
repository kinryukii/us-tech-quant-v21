"""Meaningful boundaries: reject unsafe physical input and filter before pandas."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.research.a2.factors import tail_research_inputs as inputs


def test_source_imports_do_not_read_market_or_result_tables():
    with patch.object(pd, "read_parquet", side_effect=AssertionError("unexpected parquet read")), patch.object(pd, "read_csv", side_effect=AssertionError("unexpected csv read")), patch.object(inputs.pads, "dataset", side_effect=AssertionError("unexpected Arrow read")):
        inputs.load_sources()


def test_physical_gate_rejects_mixed_year_before_body_read(tmp_path):
    path = tmp_path / "mixed.parquet"
    pq.write_table(pa.table({"date": [pd.Timestamp("2025-12-31"), pd.Timestamp("2026-01-02")], "close": [1., 1e99]}), path)
    with patch.object(pd, "read_parquet", side_effect=AssertionError("body read")):
        with pytest.raises(RuntimeError, match="PHYSICAL_POST2025_DATE"):
            inputs.footer_dates(path, ("date",), physical_pre2026=True)


def test_hash_change_rejected(tmp_path):
    path = tmp_path / "source.py"
    path.write_text("original")
    original = inputs.sha256_file(path)
    path.write_text("changed")
    with pytest.raises(RuntimeError, match="INPUT_HASH_MISMATCH"):
        inputs.verify_hash(path, original)


def test_existing_benchmark_reader_filters_before_conversion(tmp_path, monkeypatch):
    r5, _, _ = inputs.load_sources()
    benchmark = tmp_path / "benchmark.parquet"
    pq.write_table(pa.table({"date": ["2025-12-30", "2025-12-31", "2026-01-02"], **{c: [10., 11., 1e99] for c in ["open", "high", "low", "close", "volume"]}}), benchmark)
    rehab = tmp_path / "rehab.parquet"
    pq.write_table(pa.table({"code": ["US.QQQ", "US.QQQ"], "ex_div_date": ["2025-12-31", "2026-01-02"], "forward_adj_factorA": [1., 1e99]}), rehab)
    monkeypatch.setattr(r5, "BENCHMARK_RAW", {"QQQ": benchmark})
    monkeypatch.setattr(r5, "REHAB_FACTORS", rehab)
    conversions = []
    real_dataset = r5.pads.dataset

    class TableProxy:
        def __init__(self, table): self.table = table
        def to_pandas(self):
            # Inspect Arrow columns BEFORE the pandas boundary: a post-cutoff
            # canary would fail here even if a later pandas filter removed it.
            field = "date" if "date" in self.table.column_names else "ex_div_date"
            assert max(self.table[field].to_pylist()) < "2026-01-01"
            conversions.append(field)
            return self.table.to_pandas()

    class DatasetProxy:
        def __init__(self, dataset): self.dataset = dataset
        def to_table(self, **kwargs):
            assert kwargs.get("filter") is not None
            return TableProxy(self.dataset.to_table(**kwargs))

    monkeypatch.setattr(r5.pads, "dataset", lambda *a, **k: DatasetProxy(real_dataset(*a, **k)))
    result, _ = r5.load_raw_rehab_benchmarks()
    assert conversions == ["ex_div_date", "date"]
    assert len(result) == 2
    assert result.close.max() < 100


def test_wrong_price_adjustment_rejected():
    prices = pd.DataFrame({"ticker": ["QQQ"], "trade_date": [pd.Timestamp("2025-01-02")], "open": [1.], "high": [1.], "low": [1.], "close": [1.], "autype": ["CURRENT_QFQ"], "source": ["MOOMOO_OPEND_RAW_PLUS_REHAB"]})
    with pytest.raises(RuntimeError, match="PRICE_ADJUSTMENT_IDENTITY_FAILURE"):
        inputs._validate_prices(prices, {"QQQ"})


def test_authoritative_join_rejects_one_missing_member():
    day = pd.Timestamp("2025-01-02")
    checkpoint = pd.DataFrame({"signal_date": [day] * 40, "ticker": [f"T{i}" for i in range(40)], "raw_rank": range(1, 41)})
    research = pd.DataFrame({"signal_date": [day] * 39, "ticker": [f"T{i}" for i in range(39)]})
    with pytest.raises(RuntimeError, match="CARDINALITY_FAILURE"):
        inputs._join_authoritative_panel(checkpoint, research, SimpleNamespace())


def test_authoritative_join_rejects_postcutoff_label():
    day = pd.Timestamp("2025-12-01")
    checkpoint = pd.DataFrame({"signal_date": [day] * 40, "ticker": [f"T{i}" for i in range(40)], "raw_rank": range(1, 41)})
    research = checkpoint[["signal_date", "ticker"]].copy()
    research["target_end_date"] = pd.Timestamp("2026-01-02")
    with pytest.raises(RuntimeError, match="PANEL_DATE_FAILURE"):
        inputs._join_authoritative_panel(checkpoint, research, SimpleNamespace())


def test_authoritative_join_rejects_entire_missing_internal_date():
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    checkpoint = pd.DataFrame([{"signal_date": day, "ticker": f"T{i}", "raw_rank": i+1}
                               for day in dates for i in range(40)])
    research = checkpoint.loc[checkpoint.signal_date.ne(dates[1]), ["signal_date", "ticker"]].copy()
    with pytest.raises(RuntimeError, match="INTERNAL_CHECKPOINT_DATE_DROPPED"):
        inputs._join_authoritative_panel(checkpoint, research, SimpleNamespace())
