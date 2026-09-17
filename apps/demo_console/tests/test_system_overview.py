"""The data-first landing uses only synthetic, cutoff-limited performance records."""
from dataclasses import asdict, replace
import json

import pyarrow as pa
import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetState

from apps.demo_console.components import system_overview
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.models import DecisionOverview, HoldingRow, LearningProfile, PerformanceHistory, Provenance
from apps.demo_console.tests.test_machine_learning_view import learning_app
from apps.demo_console.tests.test_terminal_interactions import _content

_PICK = "system_execution_pick"
_PRIVATE = "SYNTHETIC_PRIVATE_LANDING_ERROR"


@pytest.fixture
def system_app(learning_app):
    state = learning_app
    before = asdict(state.archive)
    state.app.selectbox(key="decision_date").select("2025-12-02").run()
    state.app.radio(key="workspace").set_value("Overview").run()
    assert not state.app.exception and not state.app.error
    yield state
    assert asdict(state.archive) == before


def _records(element):
    payloads = [element.proto.data.data, *(dataset.data.data for dataset in element.proto.datasets)]
    return [row for payload in payloads if payload
            for row in pa.ipc.open_stream(payload).read_all().to_pylist()]


def _wealth(app):
    return next((element for element in app.get("vega_lite_chart")
                 if _PICK in element.proto.selection_mode), None)


def _drawdown(app):
    return next(element for element in app.get("vega_lite_chart")
                if (rows := _records(element)) and set(rows[0]) == {"execution_date", "drawdown"})


def _context(app):
    html = next(element.proto.body for element in app.get("html")
                if 'class="uq-result-context"' in element.proto.body)
    return html.split('<div class="uq-research-metrics">', 1)[0]


def _click(app, day, *, widget_id=None):
    states = app._tree.get_widget_states()
    states.widgets.append(WidgetState(
        id=widget_id or _wealth(app).proto.id,
        string_value=json.dumps({"selection": {_PICK: [{"inspection_date": day}]}})))
    return app._run(states)


def _params(value):
    if isinstance(value, dict):
        yield from value.get("params", [])
        for key, child in value.items():
            if key != "params":
                yield from _params(child)
    elif isinstance(value, list):
        for child in value:
            yield from _params(child)


def _folds(value):
    if isinstance(value, dict):
        if "fold" in value:
            yield value["fold"]
        for child in value.values():
            yield from _folds(child)
    elif isinstance(value, list):
        for child in value:
            yield from _folds(child)


def _assert_canvas(state):
    app = state.app
    assert not app.exception and not app.error
    decision = app.selectbox(key="decision_date").value
    cutoff = state.models[decision].provenance.execution_date
    assert state.landing_calls[-1] == cutoff
    rows = _records(_wealth(app))
    points = tuple(point for point in state.archive.points if point.execution_date <= cutoff)
    expected = summarize_performance(points, initial_wealth=state.archive.initial_nav,
                                     full_history_dates=state.archive.available_dates)
    assert rows == [{**asdict(point), "inspection_date": point.execution_date} for point in expected.wealth]
    assert _records(_drawdown(app)) == [
        {"execution_date": point.execution_date, "drawdown": point.drawdown} for point in expected.wealth]
    assert rows[-1]["execution_date"] == cutoff
    assert all(row["execution_date"] <= cutoff for row in rows)
    assert "2025-12-04" not in {row["execution_date"] for row in rows}
    return rows


def test_workspace_purpose_claims_only_exposed_evidence_without_private_identifiers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The workspace introduction must not load additional sources")

    monkeypatch.setattr(system_overview, "read_performance", forbidden)
    model = DecisionOverview(
        ranking=(HoldingRow(1, "SYNTH_ALPHA", score=0.0),),
        holdings=(HoldingRow(None, "SYNTH_ALPHA"),),
        provenance=Provenance(execution_date="2025-12-03", config_identity="PRIVATE_CONFIG_ID",
            artifact_sources=("PRIVATE_SOURCE_PATH",), artifact_hashes=(("PRIVATE_SOURCE_PATH", "PRIVATE_HASH"),)),
        learning=LearningProfile(feature_columns=("PRIVATE_FEATURE_A", "PRIVATE_FEATURE_B"),
            parameters=(("max_iter", "2"),), source_fingerprint="PRIVATE_SOURCE_FINGERPRINT"))
    before = asdict(model)
    markup = system_overview.system_hero_html(model)
    assert markup.count('class="uq-system-capability"') == 3
    assert "Frozen configuration · 2 feature definitions" in markup
    assert "Recorded holdings linked to execution" in markup
    assert "Source files with recorded hashes" in markup
    assert "PRIVATE_" not in markup and asdict(model) == before
    assert all(token not in markup for token in ("PASS", "production-ready", "predictive advantage"))

    incomplete = system_overview.system_hero_html(replace(model, learning=LearningProfile(), holdings=(),
        provenance=replace(model.provenance, artifact_sources=("PRIVATE_SOURCE_PATH", "MISSING_HASH_PATH"))))
    assert "Recorded model outputs · metadata incomplete" in incomplete
    assert "Portfolio linkage unavailable" in incomplete
    assert "Source identity coverage is incomplete" in incomplete
    assert "Frozen configuration" not in incomplete and "0 feature" not in incomplete
    assert "PRIVATE_" not in incomplete and "MISSING_HASH_PATH" not in incomplete

    failed = system_overview.system_hero_html(replace(model, error="Unverified snapshot"))
    assert "Model evidence unavailable" in failed
    assert "Portfolio linkage unavailable" in failed
    assert "Source identity coverage is incomplete" in failed
    assert "Frozen configuration" not in failed and "Source files with recorded hashes" not in failed


def test_landing_shows_original_path_and_first_loss_with_subordinate_capabilities(system_app):
    state, app = system_app, system_app.app
    rows = _assert_canvas(state)
    assert rows[0]["execution_date"] == "2024-12-31"
    assert rows[0]["net_wealth"] == pytest.approx(.99)
    assert rows[0]["drawdown"] == pytest.approx(-.01)
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-03"
    panel = next(element for element in app.expander if element.label == "System mechanisms & research coverage")
    assert not panel.proto.expanded
    assert app.selectbox(key="system_focus_ticker").value in {row.ticker for row in state.models["2025-12-02"].ranking}
    count = len(state.landing_calls)
    app.run()
    assert len(state.landing_calls) == count + 1
    assert not state.history_calls and not state.performance_calls
    selection = next(param for param in _params(json.loads(_wealth(app).proto.spec)) if param["name"] == _PICK)
    assert selection["select"]["fields"] == ["inspection_date"]
    assert selection["select"]["encodings"] == []
    assert selection["select"].get("on") == "click"


def test_system_positioning_precedes_case_and_portfolio_without_extra_navigation(system_app):
    state, app = system_app, system_app.app
    before = _assert_canvas(state)
    selected = app.selectbox(key="system_focus_ticker").value
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        bodies = [item.proto.body for item in app.get("html")]
        purpose_index = next(index for index, body in enumerate(bodies) if 'class="uq-system-purpose"' in body)
        case_index = next(index for index, body in enumerate(bodies) if 'class="uq-case-chain"' in body)
        portfolio_index = next(index for index, body in enumerate(bodies) if 'class="uq-result-context"' in body)
        assert purpose_index < case_index < portfolio_index
        purpose = bodies[purpose_index]
        assert purpose.count('class="uq-system-capability"') == 3
        with language_scope(language):
            for label in ("Learning model", "Portfolio evidence", "Inspectable sources"):
                assert tr(label) in purpose
        assert "<button" not in purpose and "<nav" not in purpose
        assert app.selectbox(key="system_focus_ticker").value == selected
        assert app.selectbox(key="decision_date").value == "2025-12-02"
        assert len([button for button in app.button if button.key == "system_start_tour"]) == 1
        assert app.button(key="system_start_tour").proto.type == "primary"
        assert app.button(key="system_2026")
        assert _assert_canvas(state) == before


def test_case_leads_the_portfolio_and_security_selection_never_changes_its_path(system_app):
    state, app = system_app, system_app.app
    # Different recorded memberships make a stale or purely cosmetic ticker
    # update observable, while the independent portfolio path stays fixed.
    state.transform = lambda model: replace(
        model, holdings=(model.ranking[0],), previous_holdings=("SYNTH_BETA",))
    app.selectbox(key="system_focus_ticker").select("SYNTH_ALPHA").run()

    def case_markup():
        return next(item.proto.body for item in app.get("html") if 'class="uq-case-chain"' in item.proto.body)

    alpha = case_markup()
    assert 'data-ticker="SYNTH_ALPHA"' in alpha
    assert "Recorded rank · #1" in alpha and "<strong>0.0130</strong>" in alpha
    assert "Not held → Held" in alpha and "Entered the recorded holdings" in alpha
    original_path = _assert_canvas(state)
    portfolio_context = _context(app)
    nodes = list(app)
    case_index = next(index for index, node in enumerate(nodes)
                      if getattr(getattr(node, "proto", None), "body", None) == alpha)
    result_index = next(index for index, node in enumerate(nodes)
                        if 'class="uq-result-context"' in getattr(getattr(node, "proto", None), "body", ""))
    result_markup = nodes[result_index].proto.body
    assert case_index < result_index
    assert result_markup.index('class="uq-result-context"') < result_markup.index('class="uq-research-metrics"')

    keys = [button.key for button in app.button]
    assert keys.count("system_start_tour") == 1
    assert "demo_tour_start" not in keys
    assert not any(str(key).startswith("system_map_") for key in keys)
    assert not any(button.key == "system_start_tour" for button in app.sidebar.button)

    app.selectbox(key="system_focus_ticker").select("SYNTH_BETA").run()
    beta = case_markup()
    assert 'data-ticker="SYNTH_BETA"' in beta and "SYNTH_ALPHA" not in beta
    assert "Recorded rank · #4" in beta and "<strong>-0.0030</strong>" in beta
    assert "Held → Not held" in beta and "Not retained in recorded holdings" in beta
    assert app.session_state["_research_case_ticker"] == "SYNTH_BETA"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-03"
    assert _context(app) == portfolio_context and _assert_canvas(state) == original_path
    assert not state.history_calls and not state.performance_calls


def test_result_basis_stays_with_metrics_before_charts_and_cutoff_does_not_follow_inspection(system_app):
    state, app = system_app, system_app.app
    before = _assert_canvas(state)
    context = _context(app)
    assert "2024-12-31 → 2025-12-03" in context
    assert "Selected execution cutoff: 2025-12-03" in context
    assert "Both net paths include recorded execution fees." in context
    assert "Same-study A control; not an independent alpha test." in context
    assert "2025-12-04" not in context
    markup = next(element.proto.body for element in app.get("html") if context in element.proto.body)
    assert markup.index('class="uq-result-context"') < markup.index('class="uq-research-metrics"')
    nodes = list(app)
    context_index = next(index for index, node in enumerate(nodes)
                         if getattr(getattr(node, "proto", None), "body", None) == markup)
    wealth_index = next(index for index, node in enumerate(nodes)
                        if getattr(getattr(node, "proto", None), "id", None) == _wealth(app).proto.id)
    drawdown_index = next(index for index, node in enumerate(nodes) if node is _drawdown(app))
    action_index = next(index for index, node in enumerate(nodes) if getattr(node, "key", None) == "system_start_tour")
    assert action_index < context_index < wealth_index < drawdown_index
    assert app.button(key="system_start_tour").proto.type == "primary"
    assert app.button(key="system_trace").proto.type != "primary"
    assert app.button(key="system_risk").proto.type != "primary"
    assert app.button(key="system_focus_trace").proto.type != "primary"
    app.selectbox(key="system_inspect_execution").select("2024-12-31").run()
    assert _context(app) == context and _assert_canvas(state) == before
    app.button(key="previous_date").click().run()
    context = _context(app)
    assert "2024-12-31 → 2025-12-02" in context and "Selected execution cutoff: 2025-12-02" in context
    assert "2025-12-03" not in context


def test_results_to_evidence_tour_keeps_the_current_cutoff_and_local_inspection(system_app):
    state, app = system_app, system_app.app
    app.selectbox(key="system_inspect_execution").select("2024-12-31").run()
    before = _assert_canvas(state)
    app.button(key="system_start_tour").click().run()
    assert not app.exception and not app.error
    assert app.session_state["_demo_tour_active"]
    assert app.radio(key="workspace").value == "Overview"
    assert app.selectbox(key="system_inspect_execution").value == "2024-12-31"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert _assert_canvas(state) == before
    app.button(key="demo_tour_next").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Machine learning"
    assert app.selectbox(key="decision_date").value == "2025-12-02"


def test_focused_decision_opens_comparison_with_same_security_and_cutoff(system_app):
    state, app = system_app, system_app.app
    original = _assert_canvas(state)
    app.selectbox(key="system_inspect_execution").select("2024-12-31").run()
    app.session_state["ml_primary"] = "SYNTH_BETA"
    app.session_state["ml_secondary"] = "SYNTH_GAMMA"
    app.selectbox(key="system_focus_ticker").select("SYNTH_GAMMA").run()
    landing_calls = len(state.landing_calls)
    app.button(key="system_focus_compare").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Machine learning"
    assert app.session_state["ml_section"] == "Compare outputs"
    assert app.selectbox(key="ml_primary").value == "SYNTH_GAMMA"
    assert app.selectbox(key="ml_secondary").value != "SYNTH_GAMMA"
    assert app.session_state["inspect_ticker"] == "SYNTH_GAMMA"
    assert app.session_state["ml_trace_ticker"] == "SYNTH_GAMMA"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert state.history_calls[-1] == ("2025-12-02", 20)
    assert len(state.landing_calls) == landing_calls and not state.performance_calls
    app.radio(key="workspace").set_value("Overview").run()
    assert app.selectbox(key="system_focus_ticker").value == "SYNTH_GAMMA"
    assert app.selectbox(key="system_inspect_execution").value == "2024-12-31"
    assert _assert_canvas(state) == original


def test_curve_click_manual_selection_and_languages_never_move_cutoff_or_replay_old_events(system_app):
    state, app = system_app, system_app.app
    original = _assert_canvas(state)
    old_id = _wealth(app).proto.id
    _click(app, "2024-12-31")
    assert app.selectbox(key="system_inspect_execution").value == "2024-12-31"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert _assert_canvas(state) == original
    return_html = next(element.proto.body for element in app.get("html")
                       if 'class="uq-execution-return"' in element.proto.body)
    assert "-1.00%" in return_html
    selected_id = _wealth(app).proto.id
    assert selected_id != old_id
    app.selectbox(key="system_inspect_execution").select("2025-12-02").run()
    assert _wealth(app).proto.id not in (old_id, selected_id)
    _click(app, "2024-12-31", widget_id=selected_id)
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-02"
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert app.selectbox(key="system_inspect_execution").value == "2025-12-02"
        assert app.selectbox(key="decision_date").value == "2025-12-02"
        assert _assert_canvas(state) == original
        assert _PRIVATE not in _content(app)


def test_cutoff_change_repairs_now_unavailable_local_date_and_rejects_old_chart_event(system_app):
    state, app = system_app, system_app.app
    old_id = _wealth(app).proto.id
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-03"
    app.button(key="previous_date").click().run()
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-02"
    before = _assert_canvas(state)
    _click(app, "2025-12-03", widget_id=old_id)
    assert app.selectbox(key="system_inspect_execution").value == "2025-12-02"
    assert _assert_canvas(state) == before


def test_missing_reference_preserves_a2_coordinates_and_displays_unknown_comparison(system_app):
    state, app = system_app, system_app.app
    original = _records(_wealth(app))
    def missing_reference(history):
        return replace(history, reference_available=False, reference_identity=None,
            reference_error="Frozen A reference is unavailable; A2 remains independently available.",
            points=tuple(replace(point, reference_nav=None, reference_net_return=None,
                                 reference_gross_return=None, reference_transaction_cost=None)
                         for point in history.points))
    state.performance_transform = missing_reference
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        rows = _records(_wealth(app))
        assert all(row["reference_net_wealth"] is None and row["reference_gross_wealth"] is None for row in rows)
        assert [{key: value for key, value in row.items() if not key.startswith("reference_")} for row in rows] == [
            {key: value for key, value in row.items() if not key.startswith("reference_")} for row in original]
        # Paths, endpoint leaders and labels share the visible-series fold.
        # An unavailable A control must be absent from every layer.
        folds = list(_folds(json.loads(_wealth(app).proto.spec)))
        assert folds and all(fields == ["net_wealth"] for fields in folds)
        with language_scope(language):
            absent_claim = tr("Same-study A control; not an independent alpha test.")
            absent_fees = tr("Both net paths include recorded execution fees.")
            available_fees = tr("Raw A2 includes recorded execution fees.")
            unavailable = tr("Frozen A comparison unavailable.")
        context = _context(app)
        assert absent_claim not in context and absent_fees not in context
        assert available_fees in context and unavailable in context
        assert any("—" in element.proto.body for element in app.get("html")
                   if 'class="uq-research-metrics"' in element.proto.body)


@pytest.mark.parametrize("mode", ["empty", "error", "after_cutoff"])
def test_unavailable_or_out_of_cutoff_path_has_no_canvas_but_retains_verified_decision(system_app, mode):
    state, app = system_app, system_app.app
    if mode == "empty":
        state.performance_transform = lambda history: replace(history, points=())
    elif mode == "error":
        state.performance_transform = lambda history: PerformanceHistory(
            error="Frozen performance is unavailable. Check the source evidence in Debug mode.", debug_error=_PRIVATE)
    else:
        state.performance_transform = lambda history: replace(history, points=state.archive.points)
    app.run()
    assert not app.exception
    assert _wealth(app) is None
    assert not any('class="uq-result-context"' in element.proto.body for element in app.get("html"))
    assert not any(element.key == "system_inspect_execution" for element in app.selectbox)
    assert app.session_state["_system_chart_key"] is None
    assert "SYNTH_ALPHA" in _content(app) and not app.button(key="system_trace").disabled
    assert _PRIVATE not in _content(app)
    if mode == "error":
        app.toggle(key="presentation_mode").set_value(False).run()
        assert not app.exception and _PRIVATE in _content(app)
    state.performance_transform = lambda history: history
    app.toggle(key="presentation_mode").set_value(True).run()
    _assert_canvas(state)


def test_ambiguous_ranked_names_disable_case_actions_without_hiding_verified_portfolio(system_app):
    state, app = system_app, system_app.app
    original_path = _assert_canvas(state)
    assert app.selectbox(key="system_focus_ticker").value == "SYNTH_ALPHA"
    # Keep the ranking nonempty and the former focus present, but make every
    # identity ambiguous. The verified execution and portfolio data stay valid.
    state.transform = lambda model: replace(model, ranking=(
        model.ranking[0], replace(model.ranking[1], ticker=model.ranking[0].ticker)))
    app.run()
    assert not app.exception and not app.error
    assert not any(item.key == "system_focus_ticker" for item in app.selectbox)
    assert not any('class="uq-case-chain"' in item.proto.body or 'class="uq-case-lead"' in item.proto.body
                   for item in app.get("html"))
    assert any("A verified Top20 record is required" in item.value for item in app.info)
    case_actions = ("system_start_tour", "system_focus_trace", "system_trace", "system_focus_compare")
    assert all(app.button(key=key).disabled for key in case_actions)
    assert not app.button(key="system_risk").disabled
    assert _assert_canvas(state) == original_path
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert not state.history_calls and not state.performance_calls

    state.performance_transform = lambda history: replace(history, points=())
    app.run()
    assert not app.exception and not app.error and _wealth(app) is None
    assert all(app.button(key=key).disabled for key in case_actions)
    assert 'The recorded case remains available.' not in _content(app)
    assert any('Frozen performance is unavailable.' in item.value for item in app.info)

    state.performance_transform = lambda history: history
    state.transform = lambda model: model
    app.run()
    assert not app.exception and not app.error
    assert app.selectbox(key="system_focus_ticker").value == "SYNTH_ALPHA"
    assert all(not app.button(key=key).disabled for key in case_actions)
    assert _assert_canvas(state) == original_path


def test_missing_execution_and_failed_snapshot_never_request_performance(system_app):
    state, app = system_app, system_app.app
    calls = len(state.landing_calls)
    state.transform = lambda model: replace(model, provenance=replace(model.provenance, execution_date=None))
    app.run()
    assert not app.exception and not app.error
    assert len(state.landing_calls) == calls and _wealth(app) is None
    assert "SYNTH_ALPHA" in _content(app)
    state.transform = lambda model: replace(model, error="Synthetic decision unavailable")
    app.run()
    assert not app.exception and app.error
    assert len(state.landing_calls) == calls and _wealth(app) is None
    assert "SYNTH_ALPHA" not in _content(app)


def test_selection_callback_rejects_stale_malformed_or_out_of_window_payloads(monkeypatch):
    state = {"_system_chart_key": "current", "system_inspect_execution": "2025-12-02",
             "decision_date": "2025-12-03"}
    monkeypatch.setattr(system_overview.st, "session_state", state)
    invalid_rows = ([], [{"inspection_date": "2025-12-03"}], [{"inspection_date": 1764633600000}],
                    [{"execution_date": "2025-12-01"}],
                    [{"inspection_date": "2025-12-01"}, {"inspection_date": "2025-12-02"}])
    for rows in invalid_rows:
        state["current"] = {"selection": {_PICK: rows}}
        system_overview._select_execution(("2025-12-01", "2025-12-02"), "current")
        assert state["system_inspect_execution"] == "2025-12-02"
    state["old"] = {"selection": {_PICK: [{"inspection_date": "2025-12-01"}]}}
    system_overview._select_execution(("2025-12-01", "2025-12-02"), "old")
    assert state["system_inspect_execution"] == "2025-12-02"
    state["current"] = state["old"]
    system_overview._select_execution(("2025-12-01", "2025-12-02"), "current")
    assert state["system_inspect_execution"] == "2025-12-01"
    assert state["decision_date"] == "2025-12-03"
