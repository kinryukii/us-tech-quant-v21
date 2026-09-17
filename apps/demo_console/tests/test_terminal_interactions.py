"""Exercise terminal navigation and filters over the existing synthetic adapter."""

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from apps.demo_console.adapters.decision_reader import load_overview
from apps.demo_console.tests.test_overview_model import _RecordedTables


def _content(app):
    """Include hidden expanders, widget metadata, JSON and dataframe cell values."""
    content = []
    for element in app:
        if hasattr(element, "proto"):
            content.append(str(element.proto))
        try:
            value = element.value
        except AttributeError:
            continue
        if callable(getattr(value, "to_numpy", None)):
            content.extend(str(cell) for cell in value.to_numpy().flat)
        else:
            content.append(str(value))
    return "\n".join(content).replace("\\\\", "\\").replace("\\/", "/")


def _workspace_action(app, view):
    """Return the native action for a route in the five-entry grouped menu."""
    from apps.demo_console.components.demo_tour import workspace_options

    menu = app.radio(key="workspace")
    try:
        previous_subsection = app.session_state["portfolio_workspace"]
    except KeyError:
        previous_subsection = "Portfolio"
    group_route = workspace_options(menu.value, previous_subsection)[2]
    if view in ("Portfolio", "History") and view != group_route:
        if menu.value not in ("Portfolio", "History"):
            menu.set_value(group_route).run()
        return next(control for control in app.get("button_group")
                    if control.key == "portfolio_workspace").select(view)
    return menu.set_value(view)


def _tables(app):
    markup = "\n".join(element.proto.body for element in app.get("html"))
    return [table for table in _RecordedTables(markup).tables
            if table and "Ticker" in table[0]]


def _tickers(table):
    column = table[0].index("Ticker")
    assert not {"RX action", "Final action", "Raw A2 action"}.intersection(table[0])
    return [row[column] for row in table[1:]]


def _assert_healthy(app):
    assert not app.exception and not app.error
    assert "NOT EXPOSED" in _content(app), "The interface lost its unavailable-RX scope"


@pytest.fixture
def terminal_app(make_overview_config, monkeypatch, landing_without_performance):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    config = make_overview_config()
    dates = ("2025-12-01", "2025-12-02")
    models = {date: replace(load_overview(date, config=config),
                           debug_error="SYNTHETIC_PRIVATE_TERMINAL_DEBUG") for date in dates}
    before = {date: asdict(model) for date, model in models.items()}
    monkeypatch.setattr(decision_reader, "load_overview",
                        lambda date=None: models[date or dates[-1]])
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    app.run()
    _assert_healthy(app)
    yield app, models
    assert {date: asdict(model) for date, model in models.items()} == before
    for model in models.values():
        assert model.raw_proposed_changes is model.rx_accepted_changes is model.rx_prevented_changes is None
        assert {stage.name: stage.status for stage in model.pipeline}["RX"] == "NOT_EXPOSED"


def test_portfolio_search_membership_and_inspector_recover_from_empty_results(terminal_app):
    app, _ = terminal_app
    _workspace_action(app, "Portfolio").run()
    _assert_healthy(app)
    expected = [f"SYNTH_{number:02}" for number in range(2, 22)]
    assert _tickers(_tables(app)[0]) == expected
    assert app.selectbox(key="inspect_ticker").options == expected

    app.text_input(key="ticker_search").set_value("  sYnTh_0  ").run()
    searched = [f"SYNTH_{number:02}" for number in range(2, 10)]
    assert _tickers(_tables(app)[0]) == searched
    assert app.selectbox(key="inspect_ticker").options == searched
    app.selectbox(key="inspect_ticker").select("SYNTH_09").run()
    assert any('class="uq-inspector-symbol">SYNTH_09</div>' in element.proto.body
               for element in app.get("html"))

    app.text_input(key="ticker_search").set_value("").run()
    app.selectbox(key="membership_filter").select("Entered").run()
    assert _tickers(_tables(app)[0]) == ["SYNTH_21"]
    assert app.selectbox(key="inspect_ticker").options == ["SYNTH_21"]
    assert app.selectbox(key="inspect_ticker").value == "SYNTH_21"
    app.selectbox(key="membership_filter").select("Retained").run()
    retained = expected[:-1]
    assert _tickers(_tables(app)[0]) == retained
    assert app.selectbox(key="inspect_ticker").options == retained

    app.text_input(key="ticker_search").set_value("NO_SUCH_SYNTHETIC_SYMBOL").run()
    _assert_healthy(app)
    assert not _tables(app)
    assert not any(widget.key == "inspect_ticker" for widget in app.selectbox)
    assert any("No records match these filters" in message.value for message in app.info)
    app.text_input(key="ticker_search").set_value("").run()
    assert _tickers(_tables(app)[0]) == retained
    assert app.selectbox(key="inspect_ticker").value in retained

    app.selectbox(key="membership_filter").select("All names").run()
    app.selectbox(key="record_set").select("Historical holdings").run()
    _assert_healthy(app)
    table = _tables(app)[0]
    assert _tickers(table) == expected
    assert "Score" not in table[0] and "Rank" not in table[0]
    assert app.selectbox(key="inspect_ticker").options == expected


def test_previous_next_replace_snapshot_and_persist_date_across_workspaces(terminal_app):
    app, models = terminal_app
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert app.button(key="next_date").disabled
    _workspace_action(app, "Portfolio").run()
    app.button(key="previous_date").click().run()
    _assert_healthy(app)
    assert app.radio(key="workspace").value == "Portfolio"
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    early = [f"SYNTH_{number:02}" for number in range(1, 21)]
    assert _tickers(_tables(app)[0]) == early
    assert app.selectbox(key="inspect_ticker").options == early
    assert app.button(key="previous_date").disabled
    assert not app.button(key="next_date").disabled

    app.radio(key="workspace").set_value("Evidence").run()
    _assert_healthy(app)
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    facts = app.dataframe[0].value.set_index("Field")["Value"].to_dict()
    assert facts["Decision date"] == "2025-12-01"
    assert facts["Execution date / epoch"] == models["2025-12-01"].provenance.execution_date
    app.button(key="next_date").click().run()
    assert app.radio(key="workspace").value == "Evidence"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    facts = app.dataframe[0].value.set_index("Field")["Value"].to_dict()
    assert facts["Decision date"] == "2025-12-02"
    assert facts["Execution date / epoch"] == "2025-12-03"

    app.radio(key="workspace").set_value("Overview").run()
    _assert_healthy(app)
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    late = [f"SYNTH_{number:02}" for number in range(2, 22)]
    assert not _tables(app)
    assert app.button(key="next_date").disabled
    assert not app.button(key="previous_date").disabled
    _workspace_action(app, "Portfolio").run()
    _assert_healthy(app)
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert _tickers(_tables(app)[0]) == late


def test_selected_snapshot_is_read_once_per_navigation_filter_and_language_rerun(terminal_app, monkeypatch):
    from apps.demo_console.adapters import decision_reader

    app, models = terminal_app
    calls = []

    def counted_overview(date=None):
        calls.append(date)
        return models[date or "2025-12-02"]

    monkeypatch.setattr(decision_reader, "load_overview", counted_overview)

    def expect_one(action, date):
        calls.clear()
        action.run()
        assert not app.exception and not app.error
        assert calls == [date]
        assert app.selectbox(key="decision_date").value == date

    expect_one(app.selectbox(key="decision_date").select("2025-12-01"), "2025-12-01")
    expect_one(_workspace_action(app, "Portfolio"), "2025-12-01")
    expect_one(app.selectbox(key="membership_filter").select("Retained"), "2025-12-01")
    expect_one(app.text_input(key="ticker_search").set_value("SYNTH_0"), "2025-12-01")
    expect_one(app.button(key="next_date").click(), "2025-12-02")
    expect_one(app.button(key="previous_date").click(), "2025-12-01")
    for language in ("zh", "ja", "en"):
        expect_one(app.selectbox(key="language").select(language), "2025-12-01")
        assert app.radio(key="workspace").value == "Portfolio"
        assert app.selectbox(key="membership_filter").value == "Retained"
        assert app.text_input(key="ticker_search").value == "SYNTH_0"
    expect_one(app, "2025-12-01")


@pytest.mark.parametrize("selected,expected_calls,displayed", [
    (None, [None], "2025-12-02"),
    ("2025-12-01", ["2025-12-01"], "2025-12-01"),
    ("2025-11-30", ["2025-11-30", "2025-12-02"], "2025-12-02"),
    ("invalid-date", ["invalid-date"], None),
    ("2026-01-01", ["2026-01-01"], None),
])
def test_initial_date_uses_reader_calendar_for_fallback_or_remains_blocked(
        make_overview_config, monkeypatch, landing_without_performance, selected, expected_calls, displayed):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    # Use the real bounded adapter against synthetic files. Invalid dates
    # cannot acquire an alternate calendar from an implicit latest-day read.
    config = make_overview_config()
    calls = []

    def counted_overview(date=None):
        calls.append(date)
        return load_overview(date, config=config)

    monkeypatch.setattr(decision_reader, "load_overview", counted_overview)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    if selected is not None:
        app.session_state["decision_date"] = selected
    app.run()
    assert not app.exception
    assert calls == expected_calls
    if displayed is None:
        assert app.error and not _tables(app)
        assert not any(widget.key == "decision_date" for widget in app.selectbox)
    else:
        _assert_healthy(app)
        assert app.selectbox(key="decision_date").value == displayed


def test_selected_snapshot_failure_is_not_hidden_by_a_latest_snapshot(terminal_app, monkeypatch):
    from apps.demo_console.adapters import decision_reader

    app, models = terminal_app
    calls = []
    failed = replace(models["2025-12-01"], ranking=(), holdings=(),
                     error="Synthetic selected snapshot failed verification")

    def counted_overview(date=None):
        calls.append(date)
        return failed if date == "2025-12-01" else models["2025-12-02"]

    monkeypatch.setattr(decision_reader, "load_overview", counted_overview)
    app.selectbox(key="decision_date").select("2025-12-01").run()
    assert not app.exception
    assert calls == ["2025-12-01"]
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    assert app.error[0].value == failed.error
    assert not _tables(app)


def test_presentation_privacy_covers_every_workspace_and_hidden_content(terminal_app):
    app, models = terminal_app
    model = models["2025-12-02"]
    private = [*model.provenance.artifact_sources,
               *(digest for _, digest in model.provenance.artifact_hashes),
               model.debug_error, model.provenance.raw_status]
    private = [value for value in private if value]
    for view in ("Overview", "Portfolio", "Evidence"):
        _workspace_action(app, view).run()
        _assert_healthy(app)
        assert app.toggle(key="presentation_mode").value is True
        content = _content(app)
        assert all(value not in content for value in private), view
    assert any("RX accepted changes: N/A" in value.value for value in app.markdown)
    assert any("RX prevented changes: N/A" in value.value for value in app.markdown)

    app.toggle(key="presentation_mode").set_value(False).run()
    _assert_healthy(app)
    assert app.radio(key="workspace").value == "Evidence"
    debug_content = _content(app)
    assert all(value in debug_content for value in private)
    app.toggle(key="presentation_mode").set_value(True).run()
    assert all(value not in _content(app) for value in private)
