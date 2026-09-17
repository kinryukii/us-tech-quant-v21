"""Exercise replay callbacks and missing observations using synthetic sources only."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from apps.demo_console.adapters.decision_reader import (
    load_history as read_history,
    load_overview as read_overview,
)
from apps.demo_console.components.strategy_profile import strategy_html
from apps.demo_console.components.portfolio_summary import snapshot_brief_html
from apps.demo_console.models import DecisionOverview, HoldingRow, Provenance
from apps.demo_console.tests.test_terminal_interactions import _workspace_action, _assert_healthy, _content, _tables, _tickers


_DATES = ("2025-12-01", "2025-12-02")
_DEBUG = "SYNTHETIC_PRIVATE_HISTORY_DEBUG"


@pytest.fixture
def history_app(make_overview_config, monkeypatch, landing_without_performance):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    config = make_overview_config()
    models = {date: replace(read_overview(date, config=config), debug_error=_DEBUG)
              for date in _DATES}
    before = {date: asdict(model) for date, model in models.items()}
    state = SimpleNamespace(models=models, history_calls=[], transform=lambda model: model)

    def synthetic_history(end_date=None, window=60):
        state.history_calls.append((end_date, window))
        return tuple(state.transform(replace(model, debug_error=_DEBUG))
                     for model in read_history(end_date, window=window, config=config))

    monkeypatch.setattr(decision_reader, "load_overview", lambda date=None: models[date or _DATES[-1]])
    monkeypatch.setattr(decision_reader, "load_history", synthetic_history)
    state.app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    _assert_healthy(state.app)
    yield state
    assert {date: asdict(model) for date, model in models.items()} == before


def _units(spec):
    if "encoding" in spec:
        yield spec
    for key in ("vconcat", "hconcat", "concat", "layer"):
        for child in spec.get(key, []):
            yield from _units(child)


def _charts(app):
    """Read the actual browser payload, including composed chart child domains."""
    charts = {}
    for element in app.get("vega_lite_chart"):
        spec = json.loads(element.proto.spec)
        units = list(_units(spec))
        metric = next(unit["encoding"]["y"]["field"] for unit in units
                      if "field" in unit["encoding"].get("y", {}))
        payloads = [element.proto.data.data,
                    *(dataset.data.data for dataset in element.proto.datasets)]
        records = [row for payload in payloads if payload
                   for row in pa.ipc.open_stream(payload).read_all().to_pylist()]
        assert records, f"Missing serialized observations for {metric}"
        charts[metric] = (units, records)
    assert set(charts) == {"signed_count", "turnover", "rank", "score", "ticker"}
    return charts


def _assert_cutoff(state, date):
    app = state.app
    _assert_healthy(app)
    assert app.radio(key="workspace").value == "History"
    assert app.selectbox(key="decision_date").value == date
    assert app.select_slider(key="replay_date").value == date
    assert state.history_calls[-1][0] == date
    expected = [value for value in _DATES if value <= date]
    for units, records in _charts(app).values():
        assert sorted({row["decision_date"] for row in records}) == expected
        for unit in units:
            assert unit["encoding"]["x"]["scale"]["domain"] == expected
    for table in _history_tables(app):
        assert sorted(table["Decision date"].tolist()) == expected


def _history_tables(app):
    return [element.value for element in app.dataframe
            if "Decision date" in element.value.columns]


def _security_table(app):
    return next(table for table in _history_tables(app) if "Recorded rank" in table.columns)


def _case_context(app):
    contexts = [element.proto.body for element in app.get("html")
                if 'class="uq-case-context"' in element.proto.body]
    assert len(contexts) == 1
    return contexts[0]


def test_history_and_portfolio_selections_follow_the_current_model_case_both_ways(history_app):
    state, app = history_app, history_app.app
    _workspace_action(app, "Machine learning").run()
    app.selectbox(key="ml_engine_ticker").select("SYNTH_07").run()
    _workspace_action(app, "History").run()
    _assert_cutoff(state, _DATES[-1])
    assert app.selectbox(key="history_ticker").value == "SYNTH_07"
    assert "<strong>SYNTH_07</strong>" in _case_context(app)

    app.selectbox(key="history_ticker").select("SYNTH_09").run()
    assert app.session_state["_research_case_ticker"] == "SYNTH_09"
    assert "<strong>SYNTH_09</strong>" in _case_context(app)
    _workspace_action(app, "Portfolio").run()
    assert app.selectbox(key="inspect_ticker").value == "SYNTH_09"
    assert "<strong>SYNTH_09</strong>" in _case_context(app)
    app.selectbox(key="inspect_ticker").select("SYNTH_11").run()
    assert app.session_state["_research_case_ticker"] == "SYNTH_11"
    assert "<strong>SYNTH_11</strong>" in _case_context(app)
    # The original inspector is the first column, so it precedes the full table
    # both in document order and when the native columns stack on a narrow screen.
    nodes = list(app)
    inspector_index = next(index for index, node in enumerate(nodes) if getattr(node, "key", None) == "inspect_ticker")
    table_index = next(index for index, node in enumerate(nodes)
                       if 'class="uq-table-shell"' in str(getattr(getattr(node, "proto", None), "body", "")))
    assert inspector_index < table_index

    _workspace_action(app, "History").run()
    assert app.selectbox(key="history_ticker").value == "SYNTH_11"
    _workspace_action(app, "Machine learning").run()
    assert app.selectbox(key="ml_engine_ticker").value == "SYNTH_11"
    app.selectbox(key="ml_engine_ticker").select("SYNTH_13").run()
    _workspace_action(app, "History").run()
    assert app.selectbox(key="history_ticker").value == "SYNTH_13"
    assert "<strong>SYNTH_13</strong>" in _case_context(app)
    _assert_cutoff(state, _DATES[-1])


def test_outside_current_top20_history_has_its_own_identity_and_keeps_missing_ranks(history_app):
    from apps.demo_console.i18n import language_scope, tr

    state, app = history_app, history_app.app
    _workspace_action(app, "History").run()
    canonical = app.session_state["_research_case_ticker"]
    app.selectbox(key="history_ticker").select("SYNTH_01").run()
    assert app.session_state["_research_case_ticker"] == canonical
    context = _case_context(app)
    assert "<strong>SYNTH_01</strong>" in context and "Historical exploration" in context
    assert "No unambiguous current Top20 record" in context
    assert "2025-12-01 → 2025-12-02" in context
    assert "Execution date" not in context and "2025-12-03" not in context
    records = _security_table(app).set_index("Decision date")
    assert records.loc[_DATES[0], "Recorded rank"] == 1
    assert pd.isna(records.loc[_DATES[-1], "Recorded rank"])
    for language in ("ja", "zh", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="history_ticker").value == "SYNTH_01"
        assert app.session_state["_research_case_ticker"] == canonical
        with language_scope(language):
            assert tr("Historical exploration") in _case_context(app)
            assert tr("No unambiguous current Top20 record") in _case_context(app)
            assert tr("NOT EXPOSED") in _content(app)
        assert "<strong>SYNTH_01</strong>" in _case_context(app)
        assert app.selectbox(key="decision_date").value == _DATES[-1]
    _assert_cutoff(state, _DATES[-1])


def test_portfolio_only_security_uses_actual_inspector_identity_without_a_fake_trace(history_app, monkeypatch):
    from apps.demo_console.adapters import decision_reader

    state, app = history_app, history_app.app
    monkeypatch.setattr(decision_reader, "load_overview", lambda date=None: replace(
        state.models[date or _DATES[-1]],
        holdings=(*state.models[date or _DATES[-1]].holdings, HoldingRow(None, "SYNTH_PORTFOLIO_ONLY"))))
    _workspace_action(app, "Portfolio").run()
    canonical = app.session_state["_research_case_ticker"]
    app.selectbox(key="record_set").select("Historical holdings").run()
    app.selectbox(key="inspect_ticker").select("SYNTH_PORTFOLIO_ONLY").run()
    _assert_healthy(app)
    assert app.session_state["_research_case_ticker"] == canonical
    assert "<strong>SYNTH_PORTFOLIO_ONLY</strong>" in _case_context(app)
    assert "No unambiguous current Top20 record" in _case_context(app)
    app.button(key="open_security_history").click().run()
    _assert_cutoff(state, _DATES[-1])
    assert app.selectbox(key="history_ticker").value == "SYNTH_PORTFOLIO_ONLY"
    assert app.session_state["_research_case_ticker"] == canonical
    assert "<strong>SYNTH_PORTFOLIO_ONLY</strong>" in _case_context(app)
    for metric in ("rank", "score"):
        assert all(row[metric] is None for row in _charts(app)[metric][1])


def test_portfolio_controls_and_history_entry_preserve_date_without_duplicate_overview(history_app):
    state, app = history_app, history_app.app
    date = _DATES[-1]
    _workspace_action(app, "Portfolio").run()
    app.selectbox(key="record_set").select("Historical holdings").run()
    app.selectbox(key="membership_filter").select("Retained").run()
    app.text_input(key="ticker_search").set_value("SYNTH_02").run()
    assert _tickers(_tables(app)[0]) == ["SYNTH_02"]

    app.radio(key="workspace").set_value("Overview").run()
    assert not {"overview_changes", "overview_explore", "overview_history", "demo_tour_start"}.intersection(
        button.key for button in app.button)
    assert not any(element.label == "Selected decision · full portfolio overview"
                   for element in (*app.expander, *app.status))
    assert app.button(key="system_start_tour")
    _workspace_action(app, "Portfolio").run()
    assert app.text_input(key="ticker_search").value == "SYNTH_02"
    app.text_input(key="ticker_search").set_value("").run()
    app.selectbox(key="record_set").select("Raw A2 Top20").run()
    app.selectbox(key="membership_filter").select("Entered").run()
    _assert_healthy(app)
    assert app.radio(key="workspace").value == "Portfolio"
    assert app.selectbox(key="decision_date").value == date
    assert app.text_input(key="ticker_search").value == ""
    assert app.selectbox(key="record_set").value == "Raw A2 Top20"
    assert app.selectbox(key="membership_filter").value == "Entered"
    assert _tickers(_tables(app)[0]) == ["SYNTH_21"]
    assert app.selectbox(key="inspect_ticker").value == "SYNTH_21"
    app.button(key="open_security_history").click().run()
    _assert_cutoff(state, date)
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"

    _workspace_action(app, "Portfolio").run()
    app.selectbox(key="membership_filter").select("All names").run()
    _assert_healthy(app)
    assert app.radio(key="workspace").value == "Portfolio"
    assert app.selectbox(key="decision_date").value == date
    assert app.selectbox(key="membership_filter").value == "All names"
    assert app.selectbox(key="record_set").value == "Raw A2 Top20"
    assert app.text_input(key="ticker_search").value == ""
    assert _tickers(_tables(app)[0]) == [f"SYNTH_{number:02}" for number in range(2, 22)]

    app.button(key="previous_date").click().run()
    app.selectbox(key="membership_filter").select("Entered").run()
    assert "Snapshot membership is not exposed for this date." in _content(app)
    assert not _tables(app), "An unavailable prior comparison is not zero new entries"
    assert not any(widget.key == "inspect_ticker" for widget in app.selectbox)
    _workspace_action(app, "History").run()
    _assert_cutoff(state, _DATES[0])


def test_portfolio_link_replay_slider_and_date_buttons_keep_security_and_cutoff(history_app):
    state, app = history_app, history_app.app
    _workspace_action(app, "Portfolio").run()
    app.selectbox(key="inspect_ticker").select("SYNTH_21").run()
    app.button(key="open_security_history").click().run()
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
    _assert_cutoff(state, "2025-12-02")
    observations = _security_table(app).set_index("Decision date")
    assert observations.loc["2025-12-02", "Recorded rank"] == 20
    assert pd.isna(observations.loc["2025-12-01", "Recorded rank"])
    assert observations.loc["2025-12-01", "Ranking coverage"] == "Outside Top20"

    app.select_slider(key="replay_date").set_value("2025-12-01").run()
    _assert_cutoff(state, "2025-12-01")
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
    assert app.button(key="previous_date").disabled
    for metric in ("rank", "score"):
        records = _charts(app)[metric][1]
        assert all(row[metric] is None for row in records)
        assert all(row["ranking_status"] == "Outside Top20" for row in records)

    app.button(key="next_date").click().run()
    _assert_cutoff(state, "2025-12-02")
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"
    app.button(key="previous_date").click().run()
    _assert_cutoff(state, "2025-12-01")
    assert app.selectbox(key="history_ticker").value == "SYNTH_21"


def test_history_window_controls_forward_limits_and_preserve_selected_date(history_app):
    state, app = history_app, history_app.app
    _workspace_action(app, "History").run()
    for label, limit in (("All available", None), ("20 snapshots", 20)):
        app.selectbox(key="history_window").select(label).run()
        _assert_cutoff(state, "2025-12-02")
        assert state.history_calls[-1] == ("2025-12-02", limit)
    app.select_slider(key="replay_date").set_value("2025-12-01").run()
    _assert_cutoff(state, "2025-12-01")
    assert app.selectbox(key="history_window").value == "20 snapshots"
    assert state.history_calls[-1] == ("2025-12-01", 20)


def test_security_log_tab_preserves_selection_across_language_and_ticker_changes(history_app):
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    from apps.demo_console.i18n import language_scope, tr

    state, app = history_app, history_app.app
    source = "{ticker} · Recorded observations"
    _workspace_action(app, "History").run()
    app.selectbox(key="history_ticker").select("SYNTH_21").run()
    app.select_slider(key="replay_date").set_value("2025-12-01").run()

    def log_container():
        return next(element.proto.tab_container for element in app.get("tab_container")
                    if element.proto.tab_container.id.endswith("-history_log_tabs"))

    def select_tab(label):
        states = app._tree.get_widget_states()
        states.widgets.append(WidgetState(id=log_container().id, string_value=label))
        app._run(states)

    select_tab(source.format(ticker="SYNTH_21"))
    assert log_container().default_tab_index == 1
    for language, ticker in (("zh", "SYNTH_03"), ("ja", "SYNTH_04"), ("en", "SYNTH_05")):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert log_container().default_tab_index == 1
        app.selectbox(key="history_ticker").select(ticker).run()
        assert not app.exception and not app.error
        with language_scope(language):
            label = tr(source, ticker=ticker)
            date_column = tr("Decision date")
        assert log_container().default_tab_index == 1
        assert app.session_state["history_log_tabs"] == label
        assert app.session_state["_localized_tabs:history_log_tabs"] == source
        assert label in [tab.label for tab in app.tabs]
        assert app.selectbox(key="history_ticker").value == ticker
        assert app.selectbox(key="decision_date").value == "2025-12-01"
        assert app.select_slider(key="replay_date").value == "2025-12-01"
        assert all(table.value[date_column].tolist() == ["2025-12-01"]
                   for table in app.dataframe if date_column in table.value.columns)

    # Explicit user navigation still wins after the displayed label changes.
    select_tab("Snapshot log")
    assert log_container().default_tab_index == 0
    assert app.session_state["_localized_tabs:history_log_tabs"] == "Snapshot log"


@pytest.mark.parametrize("missing", ["ranking", "portfolio"])
def test_history_coverage_gaps_remain_missing_in_tables_and_chart_payloads(history_app, missing):
    state, app = history_app, history_app.app

    def with_gap(model):
        if model.decision_date != _DATES[0]:
            return model
        model = replace(model, holdings=(), previous_holdings=None, entered=None,
                        exited=None, retained=None, turnover=None,
                        pipeline=tuple(replace(stage, status="UNAVAILABLE")
                                       if stage.name == "Portfolio" else stage for stage in model.pipeline))
        return (replace(model, ranking=(), error="Synthetic Top20 verification failure")
                if missing == "ranking" else model)

    state.transform = with_gap
    _workspace_action(app, "History").run()
    app.selectbox(key="history_ticker").select("SYNTH_02").run()
    _assert_cutoff(state, _DATES[-1])
    warnings = " ".join(message.value for message in app.warning)
    assert f"{int(missing == 'ranking')} ranking snapshot(s), 1 portfolio snapshot(s) unavailable" in warnings
    snapshot_table = next(table for table in _history_tables(app) if "Coverage" in table.columns)
    early = snapshot_table.set_index("Decision date").loc[_DATES[0]]
    assert early["Coverage"] == ("Ranking unavailable" if missing == "ranking" else "Portfolio unavailable")
    assert all(pd.isna(early[column]) for column in ("Entered", "Exited", "Retained", "Executed turnover"))
    charts = _charts(app)
    for metric in ("signed_count", "turnover"):
        records = [row for row in charts[metric][1] if row["decision_date"] == _DATES[0]]
        assert records and all(row[metric] is None for row in records)
    for metric in ("rank", "score"):
        records = [row for row in charts[metric][1] if row["decision_date"] == _DATES[0]]
        assert records and all(row["held"] is None and row["status"] == "Unavailable" for row in records)
        assert all(row[metric] is None if missing == "ranking" else row[metric] == 2 for row in records)
    observation = _security_table(app).set_index("Decision date").loc[_DATES[0]]
    assert observation["Ranking coverage"] == ("Unavailable" if missing == "ranking" else "Recorded")
    assert observation["Holdings status"] == "Unavailable"
    assert _DEBUG not in _content(app)


def test_history_presentation_privacy_and_debug_provenance_do_not_change_observations(history_app):
    state, app = history_app, history_app.app
    _workspace_action(app, "History").run()
    model = state.models[_DATES[-1]]
    private = [*model.provenance.artifact_sources,
               *(digest for _, digest in model.provenance.artifact_hashes),
               model.provenance.raw_status, _DEBUG]
    private = [value for value in private if value]
    before = [table.copy(deep=True) for table in _history_tables(app)]
    assert len(before) == 2
    assert all(value not in _content(app) for value in private)
    app.toggle(key="presentation_mode").set_value(False).run()
    _assert_cutoff(state, _DATES[-1])
    assert all(value in _content(app) for value in private)
    for original, table in zip(before, _history_tables(app), strict=True):
        pd.testing.assert_frame_equal(original, table)
        content = " ".join(str(cell) for cell in table.to_numpy().flat)
        assert all(value not in content for value in private)
    app.toggle(key="presentation_mode").set_value(True).run()
    assert all(value not in _content(app) for value in private)


def test_unverified_history_has_no_charts_and_debug_is_explicitly_opt_in(history_app):
    state, app = history_app, history_app.app
    state.transform = lambda model: replace(model, ranking=(), holdings=(), error="Synthetic unavailable Top20")
    _workspace_action(app, "History").run()
    assert not app.exception
    assert any("Historical records could not be verified" in message.value for message in app.error)
    assert not app.get("vega_lite_chart") and not _history_tables(app)
    assert _DEBUG not in _content(app)
    app.toggle(key="presentation_mode").set_value(False).run()
    assert not app.exception and _DEBUG in _content(app)
    assert not app.get("vega_lite_chart")


def test_strategy_profile_escapes_config_identity_and_withholds_unverified_claims():
    model = DecisionOverview(available_dates=_DATES,
                             provenance=Provenance(config_identity="<script>alert(1)</script>"))
    markup = strategy_html(model)
    assert "&lt;script&gt;" in markup and "<script>" not in markup
    assert "2025-12-01 → 2025-12-02" in markup
    unavailable = strategy_html(replace(model, error="Synthetic verification failure"))
    assert "unavailable until source verification succeeds" in unavailable
    assert all(claim not in unavailable for claim in
               ("Raw A2 control", "Frozen historical research", "Histogram gradient boosting", "Top 20 equities"))


def test_snapshot_brief_distinguishes_missing_comparison_from_recorded_zero_changes():
    unavailable = snapshot_brief_html(DecisionOverview())
    assert "portfolio is unavailable" in unavailable
    assert "0 holdings" not in unavailable and "0 entered" not in unavailable
    model = DecisionOverview(holdings=(HoldingRow(None, "SYNTH_01"),))
    missing_comparison = snapshot_brief_html(model)
    assert "1 recorded holdings" in missing_comparison
    assert "previous comparison is unavailable" in missing_comparison
    assert "0 retained" not in missing_comparison and "0 entered" not in missing_comparison
    recorded_zero = snapshot_brief_html(replace(model, retained=("SYNTH_01",), entered=(), exited=()))
    assert "1 holdings · 1 retained · 0 entered · 0 exited" in recorded_zero
    invalid = snapshot_brief_html(replace(model, error="Synthetic verification failure"))
    assert "portfolio is unavailable" in invalid and "1 recorded holdings" not in invalid
