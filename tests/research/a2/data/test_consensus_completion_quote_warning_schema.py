"""Generated quote schema regression through the original pure market adapter."""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays


ADAPTER = Path("D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/selector_replay.py")
ADAPTER_SHA = "b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb"
BEFORE = Path("D:/us-tech-quant-cache/_maintenance/CONSENSUS100_PTO_3000_20261012_R1/consensus_account_inputs_before_optional_quote_warning_fix.py")
BEFORE_SHA = "272877bc2bff6f7dd053e143b4e7c3aba6d875c0196d7cc4f6f742e750654055"
DAYS = pd.DatetimeIndex(["2023-01-03", "2023-01-04"])


def _function(path, name, *, expected_sha=None):
    source = path.read_bytes()
    if expected_sha:
        assert hashlib.sha256(source).hexdigest() == expected_sha
    tree = ast.parse(source.decode("utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(selected) == 1

    def require(ok, reason):
        if not ok:
            raise ValueError(reason)

    namespace = dict(pd=pd, np=np, require=require)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture
def merge():
    path = Path(__file__).resolve().parents[4] / "scripts/research/a2/data/consensus_account_inputs.py"
    return _function(path, "merge_raw_price_projections")


def _quotes(ticker, days=DAYS, **optional):
    frame = pd.DataFrame(dict(ticker=ticker, trade_date=days, open=10.0, close=11.0))
    for key, value in optional.items():
        frame[key] = value
    return frame


def _market(prices, tickers):
    pool = pd.DataFrame([(day, ticker) for day in DAYS for ticker in tickers], columns=["signal_date", "ticker"])
    make_market = _function(ADAPTER, "make_market", expected_sha=ADAPTER_SHA)
    return make_market(SimpleNamespace(MarketArrays=MarketArrays), prices, pool, DAYS)


def test_absent_warning_column_retains_original_adapter_default(merge):
    original = _quotes("OLD")
    additional = _quotes("NEW", price_quality_warning=False)
    saved_original, saved_additional = original.copy(), additional.copy()
    # Reproduce the actual old schema failure with generated quotes only.
    old_merge = _function(BEFORE, "merge_raw_price_projections", expected_sha=BEFORE_SHA)
    old_market = _market(old_merge(original, additional), ["OLD", "NEW"])
    old_column = list(old_market.tickers).index("OLD")
    assert old_market.quality[:, old_column].all()
    assert not old_market.input_present[:, old_column].any()

    market = _market(merge(original, additional), ["OLD", "NEW"])
    assert isinstance(market, MarketArrays)
    assert market.row_present.all() and market.input_present.all()
    assert not market.quality.any()
    pd.testing.assert_frame_equal(original, saved_original)
    pd.testing.assert_frame_equal(additional, saved_additional)


def test_explicit_warning_null_and_missing_quote_remain_blocked(merge):
    original = _quotes("OLD")
    additional = pd.concat([
        _quotes("TRUE", DAYS[:1], price_quality_warning=True),
        _quotes("NULL", DAYS[:1], price_quality_warning=None),
        _quotes("NEW", price_quality_warning=False),
    ], ignore_index=True)
    merged = merge(original, additional)
    assert merged.loc[merged.ticker.eq("NULL"), "price_quality_warning"].isna().all()
    market = _market(merged, ["OLD", "TRUE", "NULL", "NEW", "ABSENT"])
    lookup = {ticker: i for i, ticker in enumerate(market.tickers)}
    for ticker in ("TRUE", "NULL"):
        col = lookup[ticker]
        assert market.quality[:, col].all()
        assert not market.input_present[:, col].any()
        assert market.row_present[:, col].tolist() == [True, False]
    absent = lookup["ABSENT"]
    assert market.quality[:, absent].all()
    assert not market.row_present[:, absent].any()
    assert not market.input_present[:, absent].any()
    for ticker in ("OLD", "NEW"):
        col = lookup[ticker]
        assert not market.quality[:, col].any()
        assert market.row_present[:, col].all() and market.input_present[:, col].all()


@pytest.mark.parametrize("warning", [True, None])
def test_duplicate_quote_cannot_clear_known_or_unknown_warning(merge, warning):
    original = _quotes("OLD", DAYS[:1])
    additional = _quotes("OLD", DAYS[:1], price_quality_warning=warning)
    with pytest.raises(ValueError, match="RAW_QUOTE_WARNING_CONFLICT"):
        merge(original, additional)
    with pytest.raises(ValueError, match="RAW_QUOTE_WARNING_CONFLICT"):
        merge(additional, original)
