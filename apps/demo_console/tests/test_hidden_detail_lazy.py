"""Synthetic native detail events: closed panels do not build hidden payloads."""
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest


def _set_detail(app, key, opened):
    panel = next(node for node in app.expander if node.proto.id.endswith("-" + key))
    from apps.demo_console.i18n import language_scope
    with language_scope(app.session_state["test_language"]):
        states = app._tree.get_widget_states()
    state = next((item for item in states.widgets if item.id == panel.proto.id), None)
    if state is None:
        state = states.widgets.add(id=panel.proto.id)
    state.bool_value = opened
    with language_scope(app.session_state["test_language"]):
        app._run(states)
    assert not app.exception
    return app


def _language(app, language):
    from apps.demo_console.i18n import language_scope
    with language_scope(app.session_state["test_language"]):
        app.selectbox(key="test_language").select(language).run()


def _detail_app():
    import streamlit as st
    from apps.demo_console.components.localized_tabs import localized_expander
    from apps.demo_console.i18n import language_scope
    language = st.selectbox("Language", ("en", "zh", "ja"), key="test_language")
    if st.checkbox("Show details", value=True, key="show_details"):
        with language_scope(language):
            with localized_expander("Recorded executions", key="synthetic_detail") as detail:
                if detail.open:
                    st.text("Original details")


def _selection_app():
    import streamlit as st
    from dataclasses import replace
    from apps.demo_console.tests.test_selection_price_path import _model
    from apps.demo_console.components.selection_price_path import render_selection_price_path
    from apps.demo_console.i18n import language_scope
    language = st.selectbox("Language", ("en", "zh", "ja"), key="test_language")
    with language_scope(language):
        model = replace(_model(), source_manifest_path="SYNTHETIC_ONLY", source_manifest_sha256="0" * 64)
        render_selection_price_path(model, None)


def _stock_app():
    import streamlit as st
    from apps.demo_console.tests.test_stock_history_search import fixture_applied_history
    from apps.demo_console.components.stock_history_search import render_applied_stock_history
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.i18n import language_scope
    language = st.selectbox("Language", ("en", "zh", "ja"), key="test_language")
    with language_scope(language):
        render_applied_stock_history(DecisionOverview(), {}, "2026-01-07", history=fixture_applied_history())


def test_native_detail_preserves_open_and_closed_choices_across_language_and_absence():
    app = AppTest.from_function(_detail_app).run()
    assert not app.exception and not app.text
    _set_detail(app, "synthetic_detail", True)
    assert [row.value for row in app.text] == ["Original details"]
    for language in ("zh", "ja", "en"):
        _language(app, language)
        assert not app.exception and len(app.text) == 1
    _set_detail(app, "synthetic_detail", False)
    _language(app, "ja")
    assert not app.text
    app.checkbox(key="show_details").uncheck().run()
    app.checkbox(key="show_details").check().run()
    assert not app.exception and not app.text
    _set_detail(app, "synthetic_detail", True)
    app.checkbox(key="show_details").uncheck().run()
    _language(app, "zh")
    app.checkbox(key="show_details").check().run()
    assert not app.exception and len(app.text) == 1


def test_closed_quote_details_skip_renderer_open_uses_original_rows_and_keeps_basis(monkeypatch):
    import streamlit as st
    from apps.demo_console.adapters import rx_research_reader, raw_stock_price_reader, stock_identity_display
    from apps.demo_console.components import selection_price_path, stock_quote_chart
    from apps.demo_console.tests.test_selection_price_path import _evidence
    evidence = _evidence()
    raw = {"rows": [{"date": row["date"], "raw_open": row["open"], "raw_close": row["close"],
                     "adjustment": "RAW", "currency": "USD"} for row in evidence["prices"] if row["ticker"] == "ABC"]}
    calls, reads = [], []
    monkeypatch.setattr(rx_research_reader, "selection_tickers", lambda *a, **k: ("ABC",))
    monkeypatch.setattr(rx_research_reader, "price_evidence", lambda *a, **k: evidence)
    monkeypatch.setattr(stock_identity_display, "read_identity_chain", lambda *a, **k: {"status": "UNKNOWN"})
    def read(*args, **kwargs):
        reads.append(args)
        return raw
    monkeypatch.setattr(raw_stock_price_reader, "read_raw_stock_prices", read)
    monkeypatch.setattr(selection_price_path, "render_stock_holders", lambda *a, **k: None)
    monkeypatch.setattr(selection_price_path, "render_chart", lambda *a, **k: None)
    def render(rows, *, key):
        calls.append(rows)
        st.segmented_control("Synthetic quote basis", ("RAW", "SPLIT"), default="RAW", required=True, key=key)
    monkeypatch.setattr(stock_quote_chart, "render_quote_history", render)
    app = AppTest.from_function(_selection_app).run()
    assert not app.exception and reads and not calls
    assert not app.dataframe
    _set_detail(app, "selection_quote_details", True)
    assert calls == [raw]
    key = "selection_quote_basis_A2_HGB_ABC"
    app.session_state[key] = "SPLIT"
    app.run()
    assert app.session_state[key] == "SPLIT"
    _set_detail(app, "selection_quote_details", False)
    calls.clear()
    _language(app, "zh")
    assert not app.exception and not calls and app.session_state[key] == "SPLIT"
    _set_detail(app, "selection_quote_details", True)
    assert calls == [raw] and app.session_state[key] == "SPLIT"
    calls.clear()
    _language(app, "ja")
    assert not app.exception and calls == [raw] and app.session_state[key] == "SPLIT"
    _set_detail(app, "selection_daily_price_details", True)
    assert any("2026-01-08" in frame.value.to_string() for frame in app.dataframe)


def test_closed_main_details_skip_row_builder_open_preserves_original_records(monkeypatch):
    from apps.demo_console.adapters import workspace_reader
    from apps.demo_console.components import stock_history_search
    from apps.demo_console.tests.test_stock_history_search import fixture_applied_query
    calls = []
    def query(*args, **kwargs):
        result = fixture_applied_query(*args, **kwargs)
        for day in result.get("daily", ()):
            for row in day["strategies"].values():
                row.update(native_action="SYNTHETIC_HOLD", research_weight=.125,
                           planned_execution_date="2026-01-08", research_orders=[{"status": "SYNTHETIC"}])
        return result
    monkeypatch.setattr(workspace_reader, "query_applied_stock_history", query)
    monkeypatch.setattr(stock_history_search, "render_chart", lambda *a, **k: None)
    original = stock_history_search._native_stock_rows
    def build(records):
        result = original(records)
        calls.append(result)
        return result
    monkeypatch.setattr(stock_history_search, "_native_stock_rows", build)
    app = AppTest.from_function(_stock_app).run()
    app.selectbox(key="applied_stock_ticker").set_value("ALPHA").run()
    assert not app.exception and not calls
    _set_detail(app, "applied_stock_native_records", True)
    assert len(calls) == 1 and len(calls[0]) == 9
    assert all(row["native_action"] == "SYNTHETIC_HOLD" and row["research_weight"] == .125
               and row["planned_execution_date"] == "2026-01-08" for row in calls[0])
    assert any("native_action" in frame.value.columns for frame in app.dataframe)
    calls.clear()
    _language(app, "zh")
    assert not app.exception and len(calls) == 1
    _set_detail(app, "applied_stock_native_records", False)
    calls.clear()
    _language(app, "ja")
    assert not app.exception and not calls
    _set_detail(app, "applied_stock_native_records", True)
    assert len(calls) == 1
