"""Language switches preserve the active analysis state over synthetic artifacts."""

from apps.demo_console.i18n import catalog
from apps.demo_console.tests.test_history_view import _charts, history_app
from apps.demo_console.tests.test_terminal_interactions import _workspace_action, _content


def _label(source, language):
    return source if language == "en" else catalog()[source][language]


def _healthy(app):
    assert not app.exception and not app.error


def _private_values(model):
    return [value for value in (
        *model.provenance.artifact_sources,
        *(digest for _, digest in model.provenance.artifact_hashes),
        model.provenance.raw_status, model.debug_error,
    ) if value]


def _history_values(app):
    """Compare economic coordinates, excluding intentionally translated labels."""
    fields = ("decision_date", "execution_date", "signed_count", "turnover", "rank", "score", "held")
    return {metric: [tuple(row.get(field) for field in fields) for row in records]
            for metric, (_, records) in _charts(app).items()}


def test_language_round_trip_preserves_portfolio_filters_inspector_and_debug_mode(history_app):
    state, app = history_app, history_app.app
    assert app.selectbox(key="language").value == "en"
    _workspace_action(app, "Portfolio").run()
    app.toggle(key="presentation_mode").set_value(False).run()
    app.selectbox(key="record_set").select("Historical holdings").run()
    app.selectbox(key="membership_filter").select("Retained").run()
    app.text_input(key="ticker_search").set_value("sYnTh_0").run()
    app.selectbox(key="inspect_ticker").select("SYNTH_09").run()
    _healthy(app)
    before = {
        "workspace": app.radio(key="workspace").value,
        "date": app.selectbox(key="decision_date").value,
        "presentation": app.toggle(key="presentation_mode").value,
        "search": app.text_input(key="ticker_search").value,
        "record_set": app.selectbox(key="record_set").value,
        "membership": app.selectbox(key="membership_filter").value,
        "inspector": app.selectbox(key="inspect_ticker").value,
    }
    expected_symbols = [f"SYNTH_{number:02}" for number in range(2, 10)]
    private = _private_values(state.models[before["date"]])
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _healthy(app)
        assert app.selectbox(key="language").value == language
        assert app.radio(key="workspace").proto.set_value
        assert {
            "workspace": app.radio(key="workspace").value,
            "date": app.selectbox(key="decision_date").value,
            "presentation": app.toggle(key="presentation_mode").value,
            "search": app.text_input(key="ticker_search").value,
            "record_set": app.selectbox(key="record_set").value,
            "membership": app.selectbox(key="membership_filter").value,
            "inspector": app.selectbox(key="inspect_ticker").value,
        } == before
        assert app.text_input(key="ticker_search").label == _label("Search ticker", language)
        assert app.selectbox(key="inspect_ticker").options == expected_symbols
        assert app.selectbox(key="record_set").value == "Historical holdings"
        assert app.selectbox(key="membership_filter").value == "Retained"
        # The browser must replace its selected input text, not only its menu.
        for key, source in (("record_set", "Historical holdings"), ("membership_filter", "Retained")):
            widget = app.selectbox(key=key)
            assert widget.proto.set_value
            assert widget.proto.raw_value == _label(source, language)
        assert any('class="uq-inspector-symbol">SYNTH_09</div>' in element.proto.body
                   for element in app.get("html"))
        content = _content(app)
        assert all(value in content for value in private), "Language changed the explicit debug disclosure state"


def test_language_round_trip_preserves_history_window_focus_cutoff_and_private_mode(history_app):
    state, app = history_app, history_app.app
    _workspace_action(app, "History").run()
    app.selectbox(key="history_ticker").select("SYNTH_21").run()
    app.selectbox(key="history_window").select("All available").run()
    app.select_slider(key="replay_date").set_value("2025-12-01").run()
    _healthy(app)
    before_values = _history_values(app)
    private = _private_values(state.models["2025-12-01"])
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        _healthy(app)
        assert app.selectbox(key="language").value == language
        assert app.radio(key="workspace").proto.set_value
        assert app.radio(key="workspace").value == "History"
        assert app.selectbox(key="decision_date").value == "2025-12-01"
        assert app.select_slider(key="replay_date").value == "2025-12-01"
        assert app.selectbox(key="history_window").value == "All available"
        assert app.selectbox(key="history_ticker").value == "SYNTH_21"
        assert app.session_state["_history_focus"] == "SYNTH_21"
        assert app.toggle(key="presentation_mode").value is True
        assert app.button(key="previous_date").disabled
        assert state.history_calls[-1] == ("2025-12-01", None)
        assert app.selectbox(key="history_window").label == _label("History window", language)
        assert app.selectbox(key="history_window").proto.set_value
        assert app.selectbox(key="history_window").proto.raw_value == _label("All available", language)
        assert _history_values(app) == before_values
        content = _content(app)
        assert all(value not in content for value in private), "Language revealed hidden provenance"
        date_column = _label("Decision date", language)
        logs = [element.value for element in app.dataframe if date_column in element.value.columns]
        assert len(logs) == 2
        assert all(table[date_column].tolist() == ["2025-12-01"] for table in logs)
