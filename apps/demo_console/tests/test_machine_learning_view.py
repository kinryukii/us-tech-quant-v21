"""System and ML navigation using in-memory metadata and historical outputs only."""
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import pyarrow as pa

from apps.demo_console.components.ml_story import FEATURES
from apps.demo_console.i18n import catalog, language_scope
from apps.demo_console.models import (
    DecisionOverview, HoldingRow, LearningProfile, ModelVintage, PipelineStage, Provenance,
)
from apps.demo_console.tests.test_research_view import _synthetic_archive
from apps.demo_console.tests.test_terminal_interactions import _workspace_action, _content

_DATES = ("2025-12-01", "2025-12-02", "2025-12-03")
_PRIVATE = r"C:\synthetic-private\ml\implementation.py"
_DEBUG = "SYNTHETIC_PRIVATE_ML_READER_ERROR"
_FINGERPRINT = "a7" * 32


def _label(source, language):
    return source if language == "en" else catalog()[source][language]


def _control(app, key):
    return next(element for element in app.get("button_group") if element.key == key)


@pytest.fixture
def learning_app(monkeypatch, benchmark_stub):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader, performance_reader
    from apps.demo_console.components import system_overview
    from apps.demo_console.pages import research

    profile = LearningProfile(
        feature_columns=tuple(feature.name for feature in FEATURES),
        parameters=(("max_iter", "321"), ("learning_rate", "0.03")),
        vintages=(ModelVintage(2025, "SYNTHETIC VINTAGE", "2024-11-29", "2024-12-30",
                               "2025-01-02", "2025-12-03", 12345, 6789,
                               "b4" * 32, "NOT_PERSISTED"),),
        source_fingerprint="c8" * 32,
    )
    models = {}
    for index, day in enumerate(_DATES):
        rows = (HoldingRow(1, "SYNTH_ALPHA", .012 + index / 1000),
                HoldingRow(4, "SYNTH_BETA", -.003), HoldingRow(9, "SYNTH_GAMMA", 0))
        symbols = tuple(row.ticker for row in rows)
        models[day] = DecisionOverview(
            decision_date=day, available_dates=_DATES, ranking=rows, holdings=rows,
            previous_holdings=symbols, retained=symbols, entered=(), exited=(), turnover=.1,
            pipeline=(PipelineStage("Portfolio", "AVAILABLE", "Synthetic verified holdings"),),
            provenance=Provenance(decision_date=day, information_as_of=day,
                                  execution_date=f"2025-12-0{index + 2}",
                                  config_identity=_FINGERPRINT, alpha_implementation=_PRIVATE,
                                  artifact_sources=(_PRIVATE,), artifact_hashes=((_PRIVATE, _FINGERPRINT),)),
            learning=profile, debug_error=_DEBUG,
        )
    original = {day: asdict(model) for day, model in models.items()}
    state = SimpleNamespace(models=models, history_calls=[], overview_calls=[], performance_calls=[], landing_calls=[],
                            transform=lambda model: model, performance_transform=lambda history: history,
                            fail_read=False, benchmarks=benchmark_stub)

    def overview(day=None):
        state.overview_calls.append(day)
        if state.fail_read:
            raise ValueError(_DEBUG)
        return state.transform(models[day or _DATES[-1]])

    def history(end_date=None, window=60):
        assert end_date in _DATES
        state.history_calls.append((end_date, window))
        dates = tuple(day for day in _DATES if day <= end_date)
        selected = dates if window is None else dates[-window:]
        return tuple(state.transform(models[day]) for day in selected)

    archive = _synthetic_archive()
    state.archive = archive

    def performance_snapshot(end_date=None):
        assert end_date in {model.provenance.execution_date for model in models.values()}
        points = tuple(point for point in archive.points if point.execution_date <= end_date)
        return state.performance_transform(replace(
            archive, points=points, requested_end_date=end_date,
            effective_end_date=points[-1].execution_date if points else None))

    def performance(end_date=None):
        state.performance_calls.append(end_date)
        return performance_snapshot(end_date)

    def landing_performance(end_date=None):
        state.landing_calls.append(end_date)
        return performance_snapshot(end_date)

    def forbidden(*args, **kwargs):
        raise AssertionError("The ML view test must not use a real performance reader")

    monkeypatch.setattr(decision_reader, "load_overview", overview)
    monkeypatch.setattr(decision_reader, "load_history", history)
    monkeypatch.setattr(research, "read_performance", performance)
    monkeypatch.setattr(system_overview, "read_performance", landing_performance)
    monkeypatch.setattr(performance_reader, "read_performance", forbidden)
    state.app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    assert not state.app.exception and not state.app.error
    assert state.app.radio(key="workspace").value == "Overview"
    assert not state.history_calls and not state.performance_calls
    assert state.landing_calls == ["2025-12-04"]
    state.app.radio(key="workspace").set_value("Machine learning").run()
    assert not state.app.exception and not state.app.error
    yield state
    assert {day: asdict(model) for day, model in models.items()} == original


def test_machine_learning_engine_does_not_load_history(learning_app):
    state, app = learning_app, learning_app.app
    assert app.radio(key="workspace").value == "Machine learning"
    assert _control(app, "ml_section").value == "Model engine"
    assert app.selectbox(key="decision_date").value == _DATES[-1]
    html = "\n".join(element.proto.body for element in app.get("html"))
    assert "Recorded score profile" in html and "Focused security" in html
    assert "Mechanism schematic · not a fitted tree" in _content(app)
    assert "Matches the recorded feature schema" in html
    chart = next(element for element in app.get("vega_lite_chart") if "ml_security" in element.proto.selection_mode)
    payloads = [chart.proto.data.data, *(dataset.data.data for dataset in chart.proto.datasets)]
    records = [row for payload in payloads if payload
               for row in pa.ipc.open_stream(payload).read_all().to_pylist()]
    assert {(row["ticker"], row["rank"], row["score"]) for row in records} == {
        (row.ticker, row.rank, row.score) for row in state.models[_DATES[-1]].ranking}
    assert app.selectbox(key="ml_engine_ticker").value == "SYNTH_ALPHA"
    assert not state.history_calls and not state.performance_calls
    assert _PRIVATE not in _content(app) and _DEBUG not in _content(app)
    # AppTest 1.63 parses an icon-bearing expander as Status; both use the
    # native expandable block and preserve its initial collapsed state.
    atlas = next(element for element in (*app.expander, *app.status)
                 if element.label == "Explore all feature definitions")
    assert not atlas.proto.expanded
    assert app.button(key="ml_trace_action").proto.type == "primary"


def test_feature_selection_and_comparison_persist_across_languages_with_same_cutoff(learning_app):
    state, app = learning_app, learning_app.app
    app.selectbox(key="ml_feature_name").select("ret_120d").run()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="ml_feature_name").value == "ret_120d"
        assert app.selectbox(key="decision_date").value == _DATES[-1]
    app.button(key="ml_compare_action").click().run()
    assert _control(app, "ml_section").value == "Compare outputs"
    app.selectbox(key="ml_primary").select("SYNTH_GAMMA").run()
    assert app.session_state["_research_case_ticker"] == "SYNTH_GAMMA"
    app.selectbox(key="ml_secondary").select("SYNTH_ALPHA").run()
    assert app.session_state["_research_case_ticker"] == "SYNTH_GAMMA"
    app.selectbox(key="ml_history_window").select("60 snapshots").run()
    _control(app, "ml_history_metric").select("Model score").run()
    values = [element.value for element in app.metric]
    for language in ("ja", "zh", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="ml_primary").value == "SYNTH_GAMMA"
        assert app.selectbox(key="ml_secondary").value == "SYNTH_ALPHA"
        assert app.session_state["_research_case_ticker"] == "SYNTH_GAMMA"
        assert app.selectbox(key="ml_history_window").value == "60 snapshots"
        assert _control(app, "ml_history_metric").value == "Model score"
        assert [element.value for element in app.metric] == values
        assert state.history_calls[-1] == (_DATES[-1], 60)
    app.selectbox(key="decision_date").select(_DATES[0]).run()
    assert not app.exception and not app.error
    assert state.history_calls[-1] == (_DATES[0], 60)
    assert app.selectbox(key="ml_primary").value == "SYNTH_GAMMA"
    assert not state.performance_calls


def test_language_relabeling_and_ml_actions_do_not_log_duplicate_defaults(learning_app, monkeypatch, caplog):
    from streamlit.elements.lib import policies

    app = learning_app.app

    def run_without_warning(action):
        monkeypatch.setattr(policies, "_shown_default_value_warning", False)
        caplog.clear()
        action.run()
        assert not app.exception and not app.error
        assert not any("was created with a default value but also had" in record.getMessage()
                       for record in caplog.records)

    run_without_warning(app.selectbox(key="ml_feature_name").select("ret_120d"))
    for language in ("zh", "ja", "en"):
        run_without_warning(app.selectbox(key="language").select(language))
        assert app.selectbox(key="ml_feature_name").value == "ret_120d"
    run_without_warning(app.button(key="ml_compare_action").click())
    for language in ("ja", "zh", "en"):
        run_without_warning(app.selectbox(key="language").select(language))
        assert _control(app, "ml_section").value == "Compare outputs"
        assert app.selectbox(key="ml_primary").value != app.selectbox(key="ml_secondary").value
    run_without_warning(_control(app, "ml_section").select("Model engine"))
    run_without_warning(app.button(key="ml_lineage_action").click())
    assert _control(app, "ml_section").value == "Training lineage"


def test_native_section_switch_uses_engine_case_and_keeps_comparison_secondary(learning_app):
    state, app = learning_app, learning_app.app
    selected = _DATES[1]
    app.selectbox(key="decision_date").select(selected).run()
    _control(app, "ml_section").select("Compare outputs").run()
    assert app.selectbox(key="ml_primary").value == "SYNTH_ALPHA"
    app.selectbox(key="ml_secondary").select("SYNTH_GAMMA").run()
    _control(app, "ml_section").select("Model engine").run()
    app.selectbox(key="ml_engine_ticker").select("SYNTH_BETA").run()
    assert app.session_state["_research_case_ticker"] == "SYNTH_BETA"
    assert app.session_state["ml_primary"] == "SYNTH_ALPHA", "Retain the old comparison to exercise the regression"
    # A direct native subview selection does not invoke visit_section().
    _control(app, "ml_section").select("Compare outputs").run()
    assert app.selectbox(key="ml_primary").value == "SYNTH_BETA"
    assert app.selectbox(key="ml_secondary").value == "SYNTH_GAMMA"
    assert [metric.value for metric in app.metric][:4] == ["#4", "-0.003", "#9", "0"]
    app.selectbox(key="ml_secondary").select("SYNTH_ALPHA").run()
    for language in ("ja", "zh", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="ml_primary").value == "SYNTH_BETA"
        assert app.selectbox(key="ml_secondary").value == "SYNTH_ALPHA"
        assert app.session_state["_research_case_ticker"] == "SYNTH_BETA"
        assert app.selectbox(key="decision_date").value == selected
    _control(app, "ml_section").select("Model engine").run()
    assert app.selectbox(key="ml_engine_ticker").value == "SYNTH_BETA"
    assert all(date == selected for date, _ in state.history_calls)
    assert not state.performance_calls


def test_training_lineage_keeps_private_identity_hidden_until_debug_mode(learning_app):
    app = learning_app.app
    app.button(key="ml_lineage_action").click().run()
    assert not app.exception and not app.error
    assert _control(app, "ml_section").value == "Training lineage"
    content = _content(app)
    assert "2024-11-29" in content and "2024-12-30" in content
    assert "12,345" in content and "321" in content
    assert "Historical stage models were not persisted" in content
    assert _FINGERPRINT not in content and _PRIVATE not in content
    app.toggle(key="presentation_mode").set_value(False).run()
    assert not app.exception and not app.error
    assert _FINGERPRINT in _content(app) and _PRIVATE in _content(app)
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert _control(app, "ml_section").value == "Training lineage"
        assert "2024-11-29" in _content(app)


def test_validation_map_routes_to_research_and_evidence_at_selected_date(learning_app):
    state, app = learning_app, learning_app.app
    selected = _DATES[0]
    app.selectbox(key="decision_date").select(selected).run()
    _control(app, "ml_section").select("Validation map").run()
    assert not app.exception and not app.error
    content = _content(app)
    assert "Single-stock attribution" in content and "Not exposed" in content
    assert "Predictive quality" in content and "Not evaluated here" in content
    assert "not a model-quality score" in content
    app.button(key="ml_open_research").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Research"
    assert state.performance_calls[-1] == "2025-12-02"
    assert app.selectbox(key="decision_date").value == selected
    app.radio(key="workspace").set_value("Machine learning").run()
    assert _control(app, "ml_section").value == "Validation map"
    app.button(key="ml_open_evidence").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Evidence"
    assert app.selectbox(key="decision_date").value == selected


def test_all_six_workspaces_remain_available_without_changing_date(learning_app):
    app = learning_app.app
    selected = _DATES[1]
    app.selectbox(key="decision_date").select(selected).run()
    for view in ("Overview", "Portfolio", "History", "Research", "Evidence", "Machine learning"):
        _workspace_action(app, view).run()
        assert not app.exception and not app.error
        assert app.radio(key="workspace").value == view
        assert app.selectbox(key="decision_date").value == selected


def test_comparison_case_context_follows_all_pages_and_stays_portfolio_scoped_for_risk(learning_app):
    state, app = learning_app, learning_app.app
    selected = _DATES[1]
    app.selectbox(key="decision_date").select(selected).run()
    app.button(key="ml_compare_action").click().run()
    app.selectbox(key="ml_primary").select("SYNTH_GAMMA").run()
    app.selectbox(key="ml_secondary").select("SYNTH_ALPHA").run()
    for view in ("Machine learning", "Portfolio", "History", "Research", "Evidence", "Overview"):
        _workspace_action(app, view).run()
        for language in ("ja", "zh", "en"):
            app.selectbox(key="language").select(language).run()
            assert not app.exception and not app.error
            contexts = [element.proto.body for element in app.get("html")
                        if 'class="uq-case-context"' in element.proto.body]
            if view == "Overview":
                assert not contexts
                assert app.button(key="system_start_tour")
                assert not any(button.key == "demo_tour_start" for button in app.button)
            else:
                assert len(contexts) == 1
                assert all(value in contexts[0] for value in ("SYNTH_GAMMA", selected, "2025-12-03"))
                assert _label("Recorded case", language) in contexts[0]
                assert (_label("Portfolio context", language) in contexts[0]) == (view == "Research")
                assert "<button" not in contexts[0]
            assert app.session_state["_research_case_ticker"] == "SYNTH_GAMMA"
            assert app.selectbox(key="decision_date").value == selected
    assert all(date == selected for date, _ in state.history_calls)
    assert all(date == "2025-12-03" for date in state.performance_calls)


def test_case_context_escapes_record_fields_and_suppresses_unavailable_case(monkeypatch):
    from apps.demo_console.pages import overview

    ticker = '<SYNTH_"&>'
    model = DecisionOverview(decision_date="2025-12-01", ranking=(HoldingRow(1, ticker, .1),),
                             provenance=Provenance(execution_date=None))
    monkeypatch.setattr(overview.st, "session_state", {"language": "en"})
    with language_scope("en"):
        context = overview.case_context_html(model, "Research")
    assert "&lt;SYNTH_&quot;&amp;&gt;" in context and ticker not in context
    assert "Not recorded" in context and "Portfolio context" in context
    assert overview.case_context_html(replace(model, ranking=()), "Research") == ""
    assert overview.case_context_html(replace(model, error="Unavailable"), "Research") == ""


def test_portfolio_inspector_shows_known_held_only_membership_and_retains_unknown(monkeypatch):
    from apps.demo_console.pages import overview

    html = []
    monkeypatch.setattr(overview.st, "html", html.append)
    held = HoldingRow(None, "SYNTH_HELD_ONLY")
    with language_scope("en"):
        overview._render_inspector(DecisionOverview(holdings=(held,)), held.ticker)
        overview._render_inspector(DecisionOverview(ranking=(HoldingRow(1, "SYNTH_RANKED", .1),)), "SYNTH_RANKED")
    assert "<dt>Subsequent holding</dt><dd>Yes</dd>" in html[0]
    assert "<dt>Subsequent holding</dt><dd>N/A</dd>" in html[1]


def test_unverified_snapshot_suppresses_model_ui_and_propagates_no_history_read(learning_app):
    state, app = learning_app, learning_app.app
    app.button(key="ml_compare_action").click().run()
    calls = len(state.history_calls)
    state.transform = lambda model: replace(model, error="Synthetic record unavailable")
    app.run()
    assert not app.exception and app.error
    assert not app.get("button_group") and not app.metric and not app.get("vega_lite_chart")
    assert len(state.history_calls) == calls
    assert "SYNTH_ALPHA" not in _content(app)
    assert _DEBUG not in _content(app)
    state.transform = lambda model: model
    app.run()
    assert not app.exception and not app.error
    assert _control(app, "ml_section").value == "Compare outputs"


def test_raising_reader_uses_safe_error_in_all_languages(learning_app):
    state, app = learning_app, learning_app.app
    state.fail_read = True
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and app.error
        assert _DEBUG not in _content(app) and _PRIVATE not in _content(app)
        assert not app.metric and not app.get("vega_lite_chart")
        assert _label("Overview unavailable. The existing artifact could not be displayed safely.", language) in _content(app)


def test_decision_trace_carries_security_to_history_and_risk_tab_without_changing_cutoff(learning_app):
    from apps.demo_console.tests.test_history_view import _charts as history_charts
    from apps.demo_console.tests.test_research_view import _charts as research_charts

    state, app = learning_app, learning_app.app
    selected = _DATES[1]
    app.selectbox(key="decision_date").select(selected).run()
    app.button(key="ml_trace_action").click().run()
    assert _control(app, "ml_section").value == "Decision trace"
    app.selectbox(key="ml_trace_ticker").select("SYNTH_GAMMA").run()
    assert not state.history_calls and not state.performance_calls
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="ml_trace_ticker").value == "SYNTH_GAMMA"
        assert app.selectbox(key="ml_trace_ticker").label == _label("Security to trace", language)
        assert app.selectbox(key="decision_date").value == selected
        trace = next(element.proto.body for element in app.get("html")
                     if 'class="uq-trace ' in element.proto.body)
        assert "SYNTH_GAMMA" in trace and "#9" in trace and "0.0000" in trace
        assert "2025-12-03" in trace
        assert _PRIVATE not in _content(app) and _FINGERPRINT not in _content(app)

    app.button(key="ml_trace_history").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "History"
    assert app.selectbox(key="history_ticker").value == "SYNTH_GAMMA"
    assert app.selectbox(key="history_window").value == "60 snapshots"
    assert app.selectbox(key="decision_date").value == selected
    assert state.history_calls[-1] == (selected, 60)
    expected_dates = set(_DATES[:2])
    for units, records in history_charts(app).values():
        assert {row["decision_date"] for row in records} == expected_dates
        assert all(unit["encoding"]["x"]["scale"]["domain"] == list(_DATES[:2]) for unit in units)

    app.radio(key="workspace").set_value("Machine learning").run()
    assert _control(app, "ml_section").value == "Decision trace"
    assert app.selectbox(key="ml_trace_ticker").value == "SYNTH_GAMMA"
    app.button(key="ml_trace_recovery").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Research"
    assert app.selectbox(key="decision_date").value == selected
    assert state.performance_calls[-1] == "2025-12-03"
    assert app.session_state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
    assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 1
    charts = research_charts(app)
    assert charts["wealth"][1][-1]["execution_date"] == "2025-12-03"
    assert all(row["execution_date"] <= "2025-12-03" for row in charts["episode"][1])


def test_trace_repairs_stale_security_and_preserves_unknown_holdings(learning_app):
    state, app = learning_app, learning_app.app
    app.button(key="ml_trace_action").click().run()
    app.selectbox(key="ml_trace_ticker").select("SYNTH_GAMMA").run()
    state.transform = lambda model: replace(
        model, ranking=tuple(replace(row, held_before=None) for row in model.ranking
                             if row.ticker != "SYNTH_GAMMA"),
        holdings=(), previous_holdings=None, retained=None, entered=None, exited=None)
    app.selectbox(key="decision_date").select(_DATES[0]).run()
    assert not app.exception and not app.error
    assert app.selectbox(key="ml_trace_ticker").value == "SYNTH_ALPHA"
    assert not app.button(key="ml_trace_history").disabled
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        trace = next(element.proto.body for element in app.get("html")
                     if 'class="uq-trace ' in element.proto.body)
        assert trace.count(_label("Not recorded", language)) >= 3
        assert _label("Not held", language) not in trace
        assert _label("Subsequent holdings are unavailable; membership and set overlap remain unknown.", language) in _content(app)
        assert app.selectbox(key="decision_date").value == _DATES[0]
    state.transform = lambda model: replace(model, ranking=())
    app.run()
    assert not app.exception and not app.error
    assert not any(element.key == "ml_trace_ticker" for element in app.selectbox)
    assert app.button(key="ml_trace_history").disabled
    assert not state.history_calls and not state.performance_calls


def test_system_capabilities_preserve_global_date_language_and_read_scope(learning_app):
    state, app = learning_app, learning_app.app
    selected = _DATES[0]
    app.selectbox(key="decision_date").select(selected).run()
    app.radio(key="workspace").set_value("Overview").run()
    capabilities = ("Information timing", "Model lineage", "Execution mechanics",
                    "Risk inspection", "Research discipline", "Storage separation")
    for capability in capabilities:
        _control(app, "system_capability").select(capability).run()
        for language in ("zh", "ja", "en"):
            app.selectbox(key="language").select(language).run()
            assert not app.exception and not app.error
            assert app.radio(key="workspace").value == "Overview"
            assert _control(app, "system_capability").value == capability
            assert app.selectbox(key="decision_date").value == selected
            assert state.landing_calls[-1] == "2025-12-02"
            assert _PRIVATE not in _content(app) and _DEBUG not in _content(app)
            assert _FINGERPRINT not in _content(app)
    assert not state.history_calls and not state.performance_calls


def test_system_trace_and_risk_routes_keep_the_selected_cutoff(learning_app):
    state, app = learning_app, learning_app.app
    selected = _DATES[1]
    app.selectbox(key="decision_date").select(selected).run()
    app.radio(key="workspace").set_value("Overview").run()
    landing_reads = len(state.landing_calls)
    app.button(key="system_trace").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Machine learning"
    assert _control(app, "ml_section").value == "Decision trace"
    assert app.selectbox(key="decision_date").value == selected
    assert not state.history_calls and not state.performance_calls
    assert len(state.landing_calls) == landing_reads
    app.radio(key="workspace").set_value("Overview").run()
    assert len(state.landing_calls) == landing_reads + 1
    app.button(key="system_risk").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Research"
    assert app.selectbox(key="decision_date").value == selected
    assert app.session_state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
    assert app.get("tab_container")[0].proto.tab_container.default_tab_index == 1
    assert state.performance_calls[-1] == "2025-12-03"
    assert len(state.landing_calls) == landing_reads + 1
    assert not state.history_calls


def test_system_evidence_counts_use_model_metadata_and_keep_unknowns_unknown(learning_app):
    state, app = learning_app, learning_app.app
    app.radio(key="workspace").set_value("Overview").run()

    def evidence_strip():
        return next(element.proto.body for element in app.get("html")
                    if 'class="uq-system-evidence-strip"' in element.proto.body)

    strip = evidence_strip()
    assert all(f"<strong>{value}</strong>" in strip for value in (3, 32, 1))
    assert "CURRENT FROZEN REPLAY" in strip
    landing_reads = len(state.landing_calls)
    state.transform = lambda model: replace(
        model, learning=LearningProfile(), ranking=(), holdings=(), previous_holdings=None,
        provenance=replace(model.provenance, execution_date=None))
    app.run()
    assert not app.exception and not app.error
    strip = evidence_strip()
    assert "<strong>3</strong>" in strip
    assert strip.count("<strong>—</strong>") == 2
    assert "<strong>0</strong>" not in strip
    assert app.button(key="system_trace").disabled and app.button(key="system_risk").disabled
    assert len(state.landing_calls) == landing_reads
    state.transform = lambda model: replace(model, error="Synthetic record unavailable")
    app.run()
    assert not app.exception and app.error
    assert evidence_strip().count("<strong>—</strong>") == 3
    assert app.button(key="system_trace").disabled and app.button(key="system_risk").disabled
    assert len(state.landing_calls) == landing_reads
    assert "SYNTH_ALPHA" not in _content(app)
    assert _PRIVATE not in _content(app) and _DEBUG not in _content(app)
    assert not state.history_calls and not state.performance_calls
