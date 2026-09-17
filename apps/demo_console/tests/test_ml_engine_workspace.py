"""Recorded-score workspace interactions using synthetic rows only."""
import json
from pathlib import Path
from unittest.mock import patch

from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest

from apps.demo_console.models import DecisionOverview, HoldingRow, LearningProfile, ModelVintage, Provenance
from apps.demo_console.pages import machine_learning


def _learning_profile():
    return LearningProfile(
        feature_columns=tuple(feature.name for feature in machine_learning.FEATURES),
        target="mean 3/5/10/20 trading-day excess return vs QQQ",
        vintages=(ModelVintage(2025, "SYNTHETIC", "2024-11-29", "2024-12-30",
                              "2025-01-02", "2025-12-31", 123, 456, "ab" * 32, "NOT_PERSISTED"),),
    )


def _app():
    from dataclasses import replace
    import streamlit as st
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, HoldingRow, Provenance
    from apps.demo_console.pages.machine_learning import _render_engine
    from apps.demo_console.tests.test_ml_engine_workspace import _learning_profile

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    day = st.selectbox("Date", ("2025-12-02", "2025-12-03"), key="decision_date")
    empty = st.checkbox("No ranks", key="empty")
    unknown = st.checkbox("Missing scores and holdings", key="unknown")
    st.session_state["ml_section"] = "Model engine"
    rows = (HoldingRow(1, "ALPHA", 0.012, held_before=True),
            HoldingRow(2, "BETA", -0.003, held_before=False),
            HoldingRow(3, "GAMMA", 0.0))
    model = DecisionOverview(decision_date=day, ranking=() if empty else rows,
                             holdings=(rows[0],), previous_holdings=("ALPHA",),
                             provenance=Provenance(execution_date="2025-12-04", config_identity="7f" * 32),
                             learning=_learning_profile())
    if unknown:
        model = replace(model, ranking=tuple(replace(row, score=None, held_before=None) for row in rows),
                        holdings=(), previous_holdings=None)
    with language_scope(language):
        _render_engine(model)


def _start():
    app = AppTest.from_file(str(Path(__file__)), default_timeout=15).run()
    assert not app.exception and not app.error
    return app


def _chart(app):
    return next(chart for chart in app.get("vega_lite_chart") if "ml_security" in chart.proto.selection_mode)


def _click(app, ticker, widget_id=None):
    state = app._tree.get_widget_states()
    state.widgets.append(WidgetState(id=widget_id or _chart(app).proto.id,
        string_value=json.dumps({"selection": {"ml_security": [{"ticker": ticker}]}})))
    return app._run(state)


def test_chart_keeps_every_original_coordinate_zero_and_negative_scores():
    rows = (HoldingRow(3, "ZERO", 0.0), HoldingRow(1, "NEG", -0.3), HoldingRow(2, "POS", 0.7))
    spec = machine_learning.engine_score_chart(rows, "ZERO").to_dict()
    assert [(row["ticker"], row["rank"], row["score"]) for row in spec["data"]["values"]] == [
        ("NEG", 1, -0.3), ("POS", 2, 0.7), ("ZERO", 3, 0.0)]
    assert spec["encoding"]["y"]["scale"]["domain"] == [-0.3, 0.7]
    assert spec["encoding"]["x"]["scale"]["domain"] == [1, 2, 3]
    assert spec["encoding"]["color"]["condition"]["test"] == {"equal": "ZERO", "field": "ticker"}
    assert spec["encoding"]["color"]["condition"]["value"] == "#235c48"
    assert spec["height"] == 240
    assert not spec.get("transform")


def test_native_score_click_and_manual_selection_preserve_date_and_language():
    app = _start()
    first_id = _chart(app).proto.id
    _click(app, "BETA")
    assert not app.exception and not app.error
    assert app.selectbox(key="ml_engine_ticker").value == "BETA"
    assert app.session_state["_research_case_ticker"] == "BETA"
    assert _chart(app).proto.id != first_id
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    app.selectbox(key="ml_engine_ticker").select("GAMMA").run()
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key="ml_engine_ticker").value == "GAMMA"
        assert app.session_state["_research_case_ticker"] == "GAMMA"
        assert app.selectbox(key="decision_date").value == "2025-12-02"
    app.selectbox(key="decision_date").select("2025-12-03").run()
    assert app.selectbox(key="ml_engine_ticker").value == "GAMMA"
    assert "0.0000" in "\n".join(element.proto.body for element in app.get("html"))


def test_engine_actions_carry_the_inspected_ticker_without_changing_the_cutoff():
    app = _start()
    app.selectbox(key="ml_engine_ticker").select("BETA").run()
    app.button(key="ml_trace_action").click().run()
    assert not app.exception and not app.error
    assert app.session_state["ml_trace_ticker"] == "BETA"
    assert app.session_state["inspect_ticker"] == "BETA"
    app.selectbox(key="ml_engine_ticker").select("GAMMA").run()
    app.button(key="ml_compare_action").click().run()
    assert app.session_state["ml_primary"] == "GAMMA"
    assert app.selectbox(key="decision_date").value == "2025-12-02"


def test_missing_scores_leave_the_inspector_available_without_a_fake_chart():
    app = _start()
    app.checkbox(key="unknown").check().run()
    assert not app.exception and not app.error
    assert not app.get("vega_lite_chart")
    assert app.selectbox(key="ml_engine_ticker").value == "ALPHA"
    assert not app.button(key="ml_trace_action").disabled
    html = "\n".join(element.proto.body for element in app.get("html"))
    assert "Not recorded" in html and "0.0000" not in html
    assert "uq-ml-hero" not in html
    app.checkbox(key="unknown").uncheck().run()
    app.checkbox(key="empty").check().run()
    assert not app.exception and not app.error
    assert app.button(key="ml_trace_action").disabled and app.button(key="ml_compare_action").disabled
    assert not app.get("vega_lite_chart")


def test_chart_callback_rejects_stale_or_noncurrent_tickers():
    state = {"_ml_engine_chart_key": "current", "ml_engine_ticker": "ALPHA"}
    with patch.object(machine_learning.st, "session_state", state):
        for key, event in (("current", None), ("current", {"selection": {"ml_security": []}}),
                           ("current", {"selection": {"ml_security": [{"ticker": "FOREIGN"}]}}),
                           ("old", {"selection": {"ml_security": [{"ticker": "BETA"}]}})):
            state[key] = event
            machine_learning._select_engine_security(("ALPHA", "BETA"), key)
            assert state["ml_engine_ticker"] == "ALPHA"


def test_canonical_case_from_another_page_takes_priority_and_identity_stays_in_details():
    app = _start()
    app.session_state["_research_case_ticker"] = "BETA"
    app.run()
    assert not app.exception and not app.error
    assert app.selectbox(key="ml_engine_ticker").value == "BETA"
    assert any("BETA appears in the recorded ranking and is absent" in item.proto.body for item in app.get("html"))
    method_cards = [item.proto.body for item in app.get("html") if 'class="uq-ml-method-card"' in item.proto.body]
    assert len(method_cards) == 1
    assert 'class="uq-ml-method-sheet"' in method_cards[0]
    assert method_cards[0].count('class="uq-ml-method-card"') == 4
    assert all("Configuration identity" not in card and "7f" * 6 not in card for card in method_cards)
    mechanism = next(item for item in app.expander if item.label == "Model mechanism and objective")
    assert not mechanism.proto.expanded
    assert any("7f" * 6 in item.value for item in mechanism.caption)
    assert app.selectbox(key="decision_date").value == "2025-12-02"


def test_output_snapshot_keeps_original_coordinates_without_repeating_dates_and_membership():
    from dataclasses import replace
    from apps.demo_console.components.decision_trace import trace_facts

    model = DecisionOverview(decision_date="2025-12-02",
        ranking=(HoldingRow(4, "SYNTH", 0.0, held_before=False),),
        holdings=(HoldingRow(None, "SYNTH"),),
        provenance=Provenance(information_as_of="2025-12-01", execution_date="2025-12-03"))
    html = machine_learning.output_snapshot_html(trace_facts(model, "SYNTH"))
    assert 'data-ticker="SYNTH"' in html and html.count("<strong>") == 2
    assert "#4" in html and "0.0000" in html
    assert "2025-12-02" not in html and "2025-12-03" not in html
    assert "Before execution" not in html and "After execution" not in html
    assert "buy" not in html.lower() and "approved" not in html.lower()
    unknown = replace(model, ranking=(HoldingRow(None, "SYNTH"),), holdings=(), provenance=Provenance())
    html = machine_learning.output_snapshot_html(trace_facts(unknown, "SYNTH"))
    assert html.count("Not recorded") == 2
    assert "0.0000" not in html and "Not held" not in html
    assert machine_learning.output_snapshot_html(None) == ""


def test_output_snapshot_escapes_the_ticker_at_the_render_boundary():
    from apps.demo_console.components.decision_trace import trace_facts

    ticker = '<img src=x onerror="bad">'
    model = DecisionOverview(decision_date="<script>date</script>", ranking=(HoldingRow(1, ticker, .1),))
    html = machine_learning.output_snapshot_html(trace_facts(model, ticker))
    assert "<img" not in html and "<script>" not in html
    assert "&lt;img" in html and "date" not in html


def test_learning_design_precedes_outputs_and_shows_only_the_recorded_chronology():
    app = _start()
    nodes = list(app)
    cards = [(index, node.proto.body) for index, node in enumerate(nodes)
             if 'class="uq-ml-method-card"' in getattr(getattr(node, "proto", None), "body", "")]
    chart_index = next(index for index, node in enumerate(nodes) if node is _chart(app))
    assert len(cards) == 1 and max(index for index, _ in cards) < chart_index
    summary = "\n".join(body for _, body in cards)
    assert 'class="uq-ml-method-sheet"' in summary
    top, dates = summary.split('<div class="uq-ml-method-dates">')
    assert 'class="uq-ml-method-top"' in top
    assert top.count('class="uq-ml-method-card"') == dates.count('class="uq-ml-method-card"') == 2
    assert "Mean return relative to QQQ" in summary and "3 / 5 / 10 / 20 trading days" in summary
    assert "32 recorded feature definitions" in summary and "Momentum" in summary
    assert "2024-11-29" in summary and "Labels mature through 2024-12-30" in summary
    assert "2025-01-02 → 2025-12-31" in summary
    assert any("independent validation still require separate evidence" in item.value for item in app.caption)
    assert "uq-ml-case-strip" not in "\n".join(item.proto.body for item in app.get("html"))


def test_learning_brief_does_not_guess_missing_targets_schemas_or_matching_vintages():
    from dataclasses import replace

    missing = machine_learning.learning_brief(DecisionOverview(decision_date="2025-12-02"))
    assert all(value == "Not recorded" for _, value, _ in missing)
    model = DecisionOverview(decision_date="2025-12-02", learning=_learning_profile())
    assert all(value == "Not recorded" for _, value, _ in machine_learning.learning_brief(replace(model, error="bad")))
    for profile in (replace(model.learning, vintages=()),
                    replace(model.learning, vintages=(replace(model.learning.vintages[0], year=2024),)),
                    replace(model.learning, vintages=model.learning.vintages * 2)):
        brief = machine_learning.learning_brief(replace(model, learning=profile))
        assert brief[2][1] == brief[3][1] == "Not recorded"
        assert "2024-11-29" not in str(brief) and "2025-01-02" not in str(brief)
    alternative = replace(model.learning, target="SYNTHETIC_ALTERNATE_TARGET", feature_columns=("unknown_input",))
    brief = machine_learning.learning_brief(replace(model, learning=alternative))
    assert brief[0][1] == "SYNTHETIC_ALTERNATE_TARGET" and "3 / 5 / 10 / 20" not in str(brief)
    assert brief[1][1] == "1 recorded feature definitions" and "Momentum" not in str(brief)


def test_case_explanation_distinguishes_observed_membership_from_unavailable_records():
    from dataclasses import replace
    from apps.demo_console.components.decision_trace import trace_facts

    model = DecisionOverview(ranking=(HoldingRow(1, "SYNTH", 0),), holdings=(HoldingRow(None, "SYNTH"),))
    assert "appears in both" in machine_learning.case_explanation(trace_facts(model, "SYNTH"))
    absent = replace(model, holdings=(HoldingRow(None, "OTHER"),))
    assert "is absent" in machine_learning.case_explanation(trace_facts(absent, "SYNTH"))
    unknown = replace(model, holdings=())
    assert "unavailable" in machine_learning.case_explanation(trace_facts(unknown, "SYNTH"))
    assert machine_learning.case_explanation(None) is None


def test_unvalidated_claims_never_move_into_observed_records():
    model = DecisionOverview(ranking=(HoldingRow(1, "SYNTH", .99),),
                             holdings=(HoldingRow(None, "SYNTH"),),
                             provenance=Provenance(config_identity="synthetic"))
    observed, unestablished = machine_learning.validation_groups(model)
    names = {row[0] for row in observed}
    assert {"Historical model outputs", "Historical holdings", "Model identity"} <= names
    unsupported = {"Predictive quality", "Single-stock attribution", "Incremental model advantage", "Independent confirmation"}
    assert not unsupported & names
    assert unsupported <= {row[0] for row in unestablished}
    assert not machine_learning.validation_groups(DecisionOverview(error="unverified"))[0]
    empty = DecisionOverview(learning=LearningProfile())
    assert not machine_learning.validation_groups(empty)[0]


def test_case_routes_preserve_the_selected_date_and_do_not_attribute_portfolio_drawdowns():
    app = _start()
    app.selectbox(key="ml_engine_ticker").select("BETA").run()
    app.button(key="ml_case_recovery").click().run()
    assert not app.exception and not app.error
    assert app.session_state["workspace"] == "Research"
    assert app.session_state["_localized_tabs:research_tabs"] == "Drawdown & recovery"
    assert app.selectbox(key="decision_date").value == "2025-12-02"
    assert app.selectbox(key="ml_engine_ticker").value == "BETA"
    assert any("not this stock's contribution" in item.value for item in app.caption)
    app.button(key="ml_case_evidence").click().run()
    assert not app.exception and not app.error
    assert app.session_state["workspace"] == "Evidence"
    assert app.selectbox(key="decision_date").value == "2025-12-02"


if __name__ == "__main__":
    _app()
