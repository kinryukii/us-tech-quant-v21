"""Synthetic position, price, gap and UI contracts without real artifact reads."""
from dataclasses import replace
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from apps.demo_console.adapters import rx_research_reader
from apps.demo_console.components.selection_price_path import (
    HoldingEpisode, holding_episodes, price_path_chart, window_data, with_raw_quotes,
)
from apps.demo_console.models import DecisionOverview


@pytest.fixture(autouse=True)
def synthetic_selection_catalog(monkeypatch):
    """Unbound display fixtures must never open the real A2/RX artifact tree."""
    def selected(model, *, strategy="A2_HGB", view=None):
        return tuple(row.ticker for row in model.ranking if row.rank <= 20) if strategy == "A2_HGB" else ()
    monkeypatch.setattr(rx_research_reader, "selection_tickers", selected, raising=False)


def _model():
    return DecisionOverview(decision_date="2026-01-09", performance_cutoff_date="2026-01-08",
        sample_start_date="2026-01-01", sample_end_date="2026-12-31", execution_status="PENDING_NEXT_OPEN")


def _evidence():
    def price(day, opening, close, ticker="ABC"):
        return {"date": day, "ticker": ticker, "open": opening, "close": close,
                "adjustment": "PIT_FORWARD_REHAB_INDEX", "source": "SYNTHETIC_ONLY"}
    def position(day, before, after):
        return {"date": day, "ticker": "ABC", "shares_before": before, "shares_after": after}
    def trade(day, side, shares, value):
        return {"date": day, "ticker": "ABC", "side": side, "shares": shares,
                "execution_price": value, "notional": shares * value}
    return {
        "prices": (price("2025-12-31", 99.0, 100.0), price("2026-01-02", 110.0, 111.0),
            price("2026-01-05", 112.0, 114.0), price("2026-01-06", 116.0, 120.0),
            price("2026-01-07", 132.0, 135.0), price("2026-01-08", 148.5, 150.0),
            price("2026-01-09", 999.0, 999.0), price("2026-01-08", 50.0, 51.0, "PEND")),
        "positions": (position("2026-01-02", 0, 10), position("2026-01-05", 10, 11),
            position("2026-01-06", 11, 0), position("2026-01-07", 0, 5),
            position("2026-01-08", 5, 6), position("2026-01-09", 6, 0)),
        "trades": (trade("2026-01-02", "BUY", 10, 110.0), trade("2026-01-06", "SELL", 11, 116.0),
            trade("2026-01-07", "BUY", 5, 132.0), trade("2026-01-09", "SELL", 6, 999.0)),
        "signals": ({"signal_date": "2026-01-02", "ticker": "ABC"},
            {"signal_date": "2026-01-06", "ticker": "ABC"}, {"signal_date": "2026-01-09", "ticker": "ABC"},
            {"signal_date": "2026-01-09", "ticker": "PEND"}),
        "events": ({"ticker": "ABC", "ex_date": "2026-01-07", "action": "SYNTHETIC_SPLIT"},
            {"ticker": "ABC", "event_date": "2026-01-09", "action": "FUTURE"},
            {"ticker": "ABC", "unrecognized_date": "2026-01-07", "action": "NO_RECOGNIZED_DATE"},
            {"ticker": "OTHER", "date": "2026-01-07", "action": "OTHER_STOCK"}),
        "calendar_dates": ("2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06",
            "2026-01-07", "2026-01-08", "2026-01-09"),
        "cutoff": "2026-01-08", "adjustment": "PIT_FORWARD_REHAB_INDEX",
    }


def test_actual_position_episodes_reenter_and_remain_open_at_cutoff():
    evidence = _evidence()
    result = holding_episodes(evidence["positions"], "ABC", "2026-01-08")
    assert result == (HoldingEpisode("2026-01-02", "2026-01-06"), HoldingEpisode("2026-01-07"))
    assert holding_episodes(evidence["positions"], "PEND", "2026-01-08") == ()
    carry = holding_episodes(evidence["positions"][1:], "ABC", "2026-01-08")
    assert carry[0] == HoldingEpisode("2026-01-05", "2026-01-06", entry_known=False)


def test_window_excludes_future_other_events_and_preserves_real_execution_prices():
    result = window_data(_evidence(), _model(), "ABC", HoldingEpisode("2026-01-07"))
    assert [row["date"] for row in result["prices"]] == ["2026-01-06", "2026-01-07", "2026-01-08"]
    assert [row["execution_price"] for row in result["trades"]] == [116.0, 132.0]
    assert len(result["events"]) == 1 and result["events"][0]["action"] == "SYNTHETIC_SPLIT"
    assert result["signals"] == ({"date": "2026-01-06"},)
    assert result["end"] == "2026-01-08"
    bounded = window_data(_evidence(), replace(_model(), sample_start_date="2026-01-08"), "ABC")
    assert [row["date"] for row in bounded["prices"]] == ["2026-01-08"]
    assert bounded["trades"] == bounded["events"] == bounded["signals"] == ()


def test_gaps_use_immediately_preceding_calendar_session_and_actual_preopen_position():
    evidence = _evidence()
    rows = {row["date"]: row for row in window_data(evidence, _model(), "ABC")["prices"]}
    assert rows["2026-01-02"]["previous_session"] == "2025-12-31"
    assert rows["2026-01-02"]["previous_close"] == 100.0
    assert rows["2026-01-02"]["overnight_gap"] == pytest.approx(.10)
    assert rows["2026-01-02"]["held_before"] is False
    assert rows["2026-01-02"]["new_buy_at_open"] is True
    assert rows["2026-01-08"]["overnight_gap"] == pytest.approx(.10)
    assert rows["2026-01-08"]["held_before"] is True
    assert rows["2026-01-08"]["new_buy_at_open"] is False
    missing = {**evidence, "prices": tuple(row for row in evidence["prices"] if row["date"] != "2026-01-05")}
    gap = next(row for row in window_data(missing, _model(), "ABC")["prices"] if row["date"] == "2026-01-06")
    assert gap["previous_session"] == "2026-01-05"
    assert gap["previous_close"] is None and gap["overnight_gap"] is None


def test_no_calendar_or_no_position_never_becomes_zero_gap_or_not_held():
    evidence = _evidence()
    missing = {**evidence, "calendar_dates": ()}
    assert all(row["overnight_gap"] is None for row in window_data(missing, _model(), "ABC")["prices"])
    pending = window_data(evidence, _model(), "PEND")
    assert pending["trades"] == ()
    assert pending["prices"][0]["held_before"] is None
    assert pending["prices"][0]["new_buy_at_open"] is False
    spec = price_path_chart(pending).to_dict(validate=True)
    assert not any(layer.get("name") == "selection_executed_trades" for layer in spec["layer"])


def test_chart_uses_actual_fill_values_and_distinct_event_signal_markers():
    window = window_data(_evidence(), _model(), "ABC")
    original = repr(window)
    spec = price_path_chart(window).to_dict(validate=True)
    layers = {layer["name"]: layer for layer in spec["layer"]}
    assert set(layers) == {"selection_price_lines", "selection_signal_dates", "selection_event_dates", "selection_executed_trades"}
    fills = layers["selection_executed_trades"]["data"]["values"]
    assert [(row["side"], row["execution_price"]) for row in fills] == [("BUY", 110.0), ("SELL", 116.0), ("BUY", 132.0)]
    assert len(layers["selection_price_lines"]["data"]["values"]) == 10
    assert repr(window) == original


def test_usd_quotes_do_not_rescale_index_or_fill_and_missing_dates_stay_blank():
    window = window_data(_evidence(), _model(), 'ABC')
    original = repr(window)
    result = with_raw_quotes(window, [dict(date='2026-01-02', raw_open=9.54,
        raw_close=9.85, currency='USD', adjustment='RAW')])
    assert result['prices'][0]['open'] == 110.
    assert result['prices'][0]['raw_open'] == 9.54
    assert result['prices'][1]['raw_open'] is None
    assert result['trades'][0]['execution_price'] == 110.
    assert result['trades'][0]['raw_open'] == 9.54
    spec = price_path_chart(result).to_dict(validate=True)
    assert any(item['field'] == 'raw_open' for item in spec['layer'][0]['encoding']['tooltip'])
    assert repr(window) == original
    with pytest.raises(ValueError):
        with_raw_quotes(window, [dict(date='2026-01-02', raw_open=9.54,
            raw_close=9.85, currency='USD', adjustment='PIT_FORWARD_REHAB_INDEX')])


@pytest.fixture
def price_app():
    # Ordinary mkdir avoids the managed Windows temporary-directory ACL issue.
    root = Path(__file__).resolve().parents[3]
    folder = root / ("selection-price-test-" + uuid4().hex)
    folder.mkdir()
    script = folder / "app.py"
    script.write_text('''import streamlit as st
from apps.demo_console.models import DecisionOverview, HoldingRow
from apps.demo_console.adapters.rx_research_reader import RXView
from apps.demo_console.components.selection_price_path import render_selection_price_path
model = DecisionOverview(decision_date="2026-01-09", performance_cutoff_date="2026-01-08",
    sample_start_date="2026-01-01", sample_end_date="2026-12-31", execution_status="PENDING_NEXT_OPEN",
    ranking=(HoldingRow(1, "ABC"), HoldingRow(2, "PEND")) if st.session_state.get("synthetic_a2_rankings") else ())
view = (RXView(error="SYNTHETIC_RX_UNAVAILABLE") if st.session_state.get("synthetic_rx_missing")
        else RXView(calendar={"execution_status": "PENDING_NEXT_OPEN"}))
if st.session_state.get("synthetic_via_rx_portfolio"):
    from apps.demo_console.components.rx_portfolio import render_rx_portfolio
    render_rx_portfolio(model)
else:
    render_selection_price_path(model, view)
st.write("Portfolio remains visible")
''', encoding="utf-8")
    yield script
    resolved = folder.resolve()
    if resolved.parent != root.resolve() or not resolved.name.startswith("selection-price-test-"):
        raise AssertionError("Synthetic app cleanup escaped its assigned root")
    shutil.rmtree(resolved)


def test_app_reads_one_strategy_and_never_invents_pending_fill(monkeypatch, price_app):
    from apps.demo_console.components import selection_price_path
    monkeypatch.setattr(selection_price_path, 'render_stock_holders', lambda *a, **kw: None)
    calls = []
    def evidence(view, model, *, strategy):
        calls.append(strategy)
        return _evidence()
    monkeypatch.setattr(rx_research_reader, "price_evidence", evidence)
    app = AppTest.from_file(str(price_app), default_timeout=10).run()
    assert not app.exception
    assert calls == ["A2_HGB"]
    app.selectbox(key="selection_price_ticker_A2_HGB").select("PEND").run()
    assert not app.exception and calls == ["A2_HGB", "A2_HGB"]
    assert any("Pending selection" in item.value for item in app.caption)
    assert not any(expander.label == "Recorded executions" for expander in app.expander)
    app.session_state["selection_price_strategy"] = "A2_RX"
    app.run()
    assert not app.exception and calls == ["A2_HGB", "A2_HGB", "A2_RX"]
    assert any(item.value == "Portfolio remains visible" for item in app.markdown)


def _holders_page():
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.components.selection_price_path import render_stock_holders
    from apps.demo_console.i18n import language_scope
    def read(model, ticker, mode):
        st.session_state['queried_13f'] = (model.decision_date, ticker, mode)
        return {'status': 'PARTIAL', 'quarter': '2025Q3' if mode == 'AS_OF_SIGNAL' else '2026Q2',
            'effective_date': '2025-11-21' if mode == 'AS_OF_SIGNAL' else '2026-08-21',
            'filing_as_of': '2025-11-14' if mode == 'AS_OF_SIGNAL' else '2026-08-14',
            'rows': [{'institution_name':'Synthetic registered institution', 'notable_person':'Registry label',
                'shares':123.,'reported_value':456.,'filing_date':'2025-11-14','source_url':'https://www.sec.gov/fixture'}],
            'limitations':['SYNTHETIC_PARTIAL_SCOPE']}
    with patch.dict(sys.modules, {'apps.demo_console.adapters.stock_13f_reader': SimpleNamespace(read_stock_holders=read)}), language_scope('en'):
        render_stock_holders(DecisionOverview(decision_date='2026-01-09'), 'ABC')


def test_stock_13f_modes_keep_the_same_security_and_signal_with_explicit_scope():
    app = AppTest.from_function(_holders_page, default_timeout=10).run()
    assert not app.exception
    assert app.session_state['queried_13f'] == ('2026-01-09','ABC','AS_OF_SIGNAL')
    assert len(app.dataframe[0].value) == 1
    assert any('not evidence of personal-account holdings' in row.value for row in app.caption)
    app.session_state['stock_13f_scope'] = 'LATEST_DISCLOSED'
    app.run()
    assert not app.exception
    assert app.session_state['queried_13f'] == ('2026-01-09','ABC','LATEST_DISCLOSED')
    assert any('do not change historical stock selection' in row.value for row in app.caption)
    assert any('2026Q2' in row.value for row in app.caption)


@pytest.mark.parametrize("failure", (False, True))
def test_empty_or_unavailable_evidence_preserves_portfolio(monkeypatch, price_app, failure):
    def evidence(*args, **kwargs):
        if failure:
            raise ValueError("SYNTHETIC_MISSING_PRICE_EVIDENCE")
        return {**_evidence(), "positions": (), "signals": ()}
    monkeypatch.setattr(rx_research_reader, "price_evidence", evidence)
    app = AppTest.from_file(str(price_app), default_timeout=10).run()
    assert not app.exception and not app.get("vega_lite_chart")
    assert any(item.value == "Portfolio remains visible" for item in app.markdown)


@pytest.mark.parametrize("via_portfolio", (False, True))
@pytest.mark.parametrize("failure", ("missing", "empty"))
def test_unavailable_rx_and_prices_keep_a2_stock_choices_and_13f(monkeypatch, price_app, via_portfolio, failure):
    from apps.demo_console.components import selection_price_path
    import streamlit as st

    price_calls, holder_calls, selection_calls = [], [], []
    unavailable = rx_research_reader.RXView(error="SYNTHETIC_RX_UNAVAILABLE")
    monkeypatch.setattr(rx_research_reader, "read", lambda model: unavailable)

    def selected(model, *, strategy="A2_HGB", view=None):
        assert strategy == "A2_HGB" and view.error == unavailable.error
        selection_calls.append((model.decision_date, strategy))
        return tuple(row.ticker for row in model.ranking if row.rank <= 20)

    def prices(view, model, *, strategy):
        assert strategy == "A2_HGB" and view.error == unavailable.error
        price_calls.append(strategy)
        if failure == "missing":
            raise ValueError("SYNTHETIC_PRICE_PUBLICATION_MISSING")
        return {**_evidence(), "prices": (), "positions": (), "signals": (), "trades": (), "events": ()}

    def holders(model, ticker):
        holder_calls.append((model.decision_date, ticker, tuple(row.ticker for row in model.ranking)))
        st.caption("Synthetic 13F for " + ticker)

    monkeypatch.setattr(rx_research_reader, "selection_tickers", selected)
    monkeypatch.setattr(rx_research_reader, "price_evidence", prices)
    monkeypatch.setattr(selection_price_path, "render_stock_holders", holders)
    app = AppTest.from_file(str(price_app), default_timeout=10)
    for key, value in {"synthetic_rx_missing": True, "synthetic_a2_rankings": True,
                       "synthetic_via_rx_portfolio": via_portfolio}.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception and not app.get("vega_lite_chart")
    assert app.selectbox(key="selection_price_ticker_A2_HGB").options == ["ABC", "PEND"]
    assert holder_calls == [("2026-01-09", "ABC", ("ABC", "PEND"))]
    assert price_calls == ["A2_HGB"] and selection_calls
    assert any("price" in item.value.lower() and ("unavailable" in item.value.lower() or "no verified" in item.value.lower())
               for item in app.caption)
    assert any(item.value == "Portfolio remains visible" for item in app.markdown)
    app.selectbox(key="selection_price_ticker_A2_HGB").select("PEND").run()
    assert not app.exception and not app.get("vega_lite_chart")
    assert holder_calls[-1] == ("2026-01-09", "PEND", ("ABC", "PEND"))
    assert price_calls == ["A2_HGB", "A2_HGB"]
    assert any(item.value == "Synthetic 13F for PEND" for item in app.caption)


def test_rx_publication_failure_still_allows_independent_a2_price_chart(monkeypatch, price_app):
    from apps.demo_console.components import selection_price_path

    calls, holder_calls = [], []
    unavailable = rx_research_reader.RXView(error="SYNTHETIC_RX_UNAVAILABLE")
    monkeypatch.setattr(rx_research_reader, "read", lambda model: unavailable)

    def prices(view, model, *, strategy):
        assert view.error == unavailable.error and strategy == "A2_HGB"
        calls.append(strategy)
        return _evidence()

    monkeypatch.setattr(rx_research_reader, "price_evidence", prices)
    monkeypatch.setattr(selection_price_path, "render_stock_holders", lambda model, ticker: holder_calls.append(ticker))
    app = AppTest.from_file(str(price_app), default_timeout=10)
    for key in ("synthetic_rx_missing", "synthetic_a2_rankings", "synthetic_via_rx_portfolio"):
        app.session_state[key] = True
    app.run()
    assert not app.exception and app.get("vega_lite_chart")
    assert calls == ["A2_HGB"] and holder_calls == ["ABC"]
    assert any(item.value == unavailable.error for item in app.info)
    assert any(item.value == "Portfolio remains visible" for item in app.markdown)
