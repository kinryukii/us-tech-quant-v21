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


def test_learning_design_in_mechanism_details_shows_only_the_recorded_chronology():
    app = _start()
    nodes = list(app)
    cards = [(index, node.proto.body) for index, node in enumerate(nodes)
             if 'class="uq-ml-method-card"' in getattr(getattr(node, "proto", None), "body", "")]
    chart_index = next(index for index, node in enumerate(nodes) if node is _chart(app))
    assert len(cards) == 1 and chart_index < min(index for index, _ in cards)
    mechanism = next(item for item in app.expander if item.label == "Model mechanism and objective")
    assert not mechanism.proto.expanded
    assert any("uq-ml-method-sheet" in item.proto.body for item in mechanism.get("html"))
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


_NATIVE_IDS = ("RAW_A2", "HGB_DIAG_5", "R10_DIRECT_MEAN4_ELASTICNET_MID",
               "R10_DIRECT_H5_RIDGE_MID", "R7_GROSS_LINEAR")


def _native_workspace(strategy_id, day="2025-12-02", *, empty=False, missing=False):
    kind = ("RANK_SCORE" if strategy_id in _NATIVE_IDS[:2] else
            "GROSS_EXPOSURE" if strategy_id == _NATIVE_IDS[-1] else "ACTION_VALUE")
    rows = [{"ticker": ticker, "rank": index if kind == "RANK_SCORE" else None,
             "score": None if missing or kind != "RANK_SCORE" else value,
             "native_action_score": None if missing or kind != "ACTION_VALUE" else value,
             "target_weight": None if missing else weight, "action": action,
             "raw_rank": 30 + index, "raw_score": .777, "weight_before": 0., "hold_units": 0.}
            for index, (ticker, value, weight, action) in enumerate(
                (("NATIVE_A", -.25, 0., "SELL_OR_REDUCE"),
                 ("NATIVE_B", .5, .2, "HOLD"), ("NATIVE_ZERO", 0., .05, "BUY")), 1)]
    return {"strategy_id": strategy_id, "output_kind": kind, "rows": [] if empty else rows,
        "score_date": day, "target_date": day, "record_basis": "RECORDED_MODEL_OUTPUT",
        "learning": LearningProfile(target="SYNTHETIC_NATIVE_TARGET", feature_columns=("native_feature",)),
        "model_identity": {"fit_cutoff_exclusive": "2025-01-01",
            "label_maturity_cutoff_exclusive": "2024-12-31", "feature_count": 1},
        "provenance": {"strategy_id": strategy_id, "fixture": "SYNTHETIC_ONLY"},
        "target": {"status": "READY", "kind": "CURRENT_ACCOUNT_TARGET", "signal_date": day,
            "requested_gross": None if missing else 0., "previous_requested_gross": None if missing else .8},
        "error": "SYNTHETIC_MISSING" if empty else None}


def _native_app():
    import streamlit as st
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.models import DecisionOverview, HoldingRow
    from apps.demo_console.pages.machine_learning import render_machine_learning
    from apps.demo_console.tests.test_ml_engine_workspace import _NATIVE_IDS, _native_workspace

    strategy = st.selectbox("Strategy", _NATIVE_IDS, key="native_strategy")
    language = st.selectbox("Language", ("en", "zh", "ja"), key="native_language")
    day = st.selectbox("Date", ("2025-12-02", "2025-12-03"), key="native_day")
    empty = st.checkbox("No native rows", key="native_empty")
    missing = st.checkbox("Missing native values", key="native_missing")
    # A populated Raw model is deliberately unrelated: selected strategies must
    # consume only their explicit workspace, without borrowing Raw values.
    model = DecisionOverview(decision_date=day, ranking=(HoldingRow(1, "RAW_SENTINEL", 99.),))
    with language_scope(language):
        render_machine_learning(model, workspace=_native_workspace(strategy, day, empty=empty, missing=missing))


def _native_start():
    app = AppTest.from_function(_native_app, default_timeout=15).run()
    assert not app.exception and not app.error
    return app


def _visible_text(app):
    return "\n".join([*(item.proto.body for item in app.get("html")),
                       *(item.value for item in app.caption), *(item.value for item in app.info),
                       *(item.value for item in app.markdown),
                       *(item.label for item in app.metric), *(item.value for item in app.metric),
                       *(str(item.value.to_dict()) for item in app.dataframe)])


def test_every_strategy_has_native_engine_comparison_lineage_trace_and_evidence():
    for strategy in _NATIVE_IDS:
        app = _native_start()
        app.selectbox(key="native_strategy").select(strategy).run()
        for section in machine_learning.SECTIONS:
            app.button_group(key="ml_section").set_value(section).run()
            assert not app.exception and not app.error
            text = _visible_text(app)
            assert "RAW_SENTINEL" not in text and "99" not in text
            assert app.selectbox(key="native_day").value == "2025-12-02"
            if section == "Model engine":
                assert _chart(app) is not None
                assert app.selectbox(key="ml_engine_ticker").value == "NATIVE_A"
            elif section == "Compare outputs":
                assert list(app.dataframe[0].value.columns) == ["Field", "NATIVE_A", "NATIVE_B"]
            elif section == "Training lineage":
                assert "SYNTHETIC_NATIVE_TARGET" in text and "native_feature" in text
                assert "2025-01-01" in text and "2024-12-31" in text
            elif section == "Decision trace":
                assert "0.777" in text and "2025-12-02" in text
            else:
                assert "Historical model outputs" in text and "Recorded" in text


def test_native_chart_preserves_zero_negative_and_original_units():
    for strategy in _NATIVE_IDS:
        workspace = _native_workspace(strategy)
        chart, label = machine_learning.workspace_output_chart(workspace, "NATIVE_ZERO")
        spec = chart.to_dict()
        kind = workspace["output_kind"]
        expected = [0., .2, .05] if kind == "GROSS_EXPOSURE" else [-.25, .5, 0.]
        assert [row["value"] for row in spec["data"]["values"]] == expected
        assert label == {"RANK_SCORE": "Recorded model score", "ACTION_VALUE": "Recorded action value",
                         "GROSS_EXPOSURE": "Target weight"}[kind]
        assert spec["encoding"]["y"]["scale"]["domain"] == [min(0., *expected), max(0., *expected)]
        if kind != "RANK_SCORE":
            assert all(row["rank"] is None for row in spec["data"]["values"])
        assert .777 not in expected


def test_native_chart_click_and_strategy_changes_keep_date_language_and_current_focus():
    app = _native_start()
    _click(app, "NATIVE_B")
    assert app.selectbox(key="ml_engine_ticker").value == "NATIVE_B"
    old_id = _chart(app).proto.id
    app.selectbox(key="native_strategy").select(_NATIVE_IDS[3]).run()
    assert app.selectbox(key="ml_engine_ticker").value == "NATIVE_B"
    assert _chart(app).proto.id != old_id
    app.selectbox(key="native_language").select("ja").run()
    app.selectbox(key="native_day").select("2025-12-03").run()
    assert not app.exception and not app.error
    assert app.selectbox(key="ml_engine_ticker").value == "NATIVE_B"
    assert app.selectbox(key="native_language").value == "ja"
    app.button(key="ml_trace_action").click().run()
    assert app.session_state["ml_section"] == "Decision trace"
    assert app.selectbox(key="ml_trace_ticker").value == "NATIVE_B"
    assert app.selectbox(key="native_day").value == "2025-12-03"


def test_native_missing_values_and_empty_records_do_not_invent_raw_scores_or_targets():
    for strategy in (_NATIVE_IDS[0], _NATIVE_IDS[3], _NATIVE_IDS[4]):
        app = _native_start()
        app.selectbox(key="native_strategy").select(strategy).run()
        app.checkbox(key="native_missing").check().run()
        assert not app.exception and not app.error
        assert not app.get("vega_lite_chart")
        assert "Not recorded" in _visible_text(app)
        assert not app.button(key="ml_trace_action").disabled
        app.checkbox(key="native_empty").check().run()
        assert not app.exception and not app.error
        assert not app.get("vega_lite_chart")
        assert not app.metric
        assert "ml_engine_ticker" not in [item.key for item in app.selectbox]
        assert not {"ml_trace_action", "ml_compare_action"}.intersection(item.key for item in app.button)
        assert len(app.info) == 1
        assert len(app.get("bidi_component"))==1
        assert json.loads(app.get("bidi_component")[0].proto.json)["strategy_id"]==strategy
        assert "0 recorded securities" not in _visible_text(app)
        assert "RAW_SENTINEL" not in _visible_text(app)
        app.button_group(key="ml_section").set_value("Compare outputs").run()
        assert any("Two recorded securities" in item.value for item in app.info)


def test_native_action_workspace_translates_semantics_units_and_sections_without_changing_values():
    from apps.demo_console.i18n import catalog

    app = _native_start()
    app.selectbox(key="native_strategy").select(_NATIVE_IDS[3]).run()
    expected_headers = {
        "Model engine": "Recorded action value", "Compare outputs": "Compare outputs",
        "Training lineage": "Training lineage", "Decision trace": "Decision trace", "Validation map": "Validation map"}
    for language in ("zh", "ja", "en"):
        app.selectbox(key="native_language").select(language).run()
        for section, header in expected_headers.items():
            app.button_group(key="ml_section").set_value(section).run()
            assert not app.exception and not app.error
            text = _visible_text(app)
            translated = header if language == "en" else catalog()[header][language]
            assert translated in text
            basis = "RECORDED_MODEL_OUTPUT" if language == "en" else catalog()["RECORDED_MODEL_OUTPUT"][language]
            assert basis in text
            assert app.selectbox(key="native_day").value == "2025-12-02"
            if section == "Model engine":
                assert "-0.25" in text and app.metric[0].value == "0.00%"



def test_native_trace_aliases_keep_recorded_zero_and_prefer_explicit_values():
    original = _native_workspace

    def aliased(*args, **kwargs):
        workspace = original(*args, **kwargs)
        for row, (weight, research, units, exact) in zip(workspace["rows"],
                ((None, 0., None, 0.), (0., .8, 0., 17.), (None, .4, None, 3.5))):
            row.update(weight_before=weight, research_weight_before=research,
                       hold_units=units, exact_hold_units=exact)
        return workspace

    with patch("apps.demo_console.tests.test_ml_engine_workspace._native_workspace", side_effect=aliased):
        app = _native_start()
        app.selectbox(key="native_strategy").select(_NATIVE_IDS[3]).run()
        app.button_group(key="ml_section").set_value("Decision trace").run()
        for ticker, expected in (("NATIVE_A", ("0.00%", "0")), ("NATIVE_B", ("0.00%", "0")),
                                 ("NATIVE_ZERO", ("40.00%", "3.5"))):
            app.selectbox(key="ml_trace_ticker").select(ticker).run()
            assert not app.exception and not app.error
            values = dict(zip(app.dataframe[0].value["Field"], app.dataframe[0].value["Value"]))
            assert (values["Previous weight"], values["Recorded HOLD units"]) == expected


def test_native_comparison_tracks_new_engine_focus_and_preserves_manual_same_context():
    app = _native_start()
    app.selectbox(key="native_strategy").select(_NATIVE_IDS[3]).run()
    app.selectbox(key="ml_engine_ticker").select("NATIVE_B").run()
    app.button(key="ml_compare_action").click().run()
    assert app.selectbox(key="ml_native_primary").value == "NATIVE_B"
    app.selectbox(key="ml_native_primary").select("NATIVE_A").run()
    app.selectbox(key="native_language").select("ja").run()
    assert app.selectbox(key="ml_native_primary").value == "NATIVE_A"
    app.button_group(key="ml_section").set_value("Model engine").run()
    app.selectbox(key="ml_engine_ticker").select("NATIVE_ZERO").run()
    app.button_group(key="ml_section").set_value("Compare outputs").run()
    assert app.selectbox(key="ml_native_primary").value == "NATIVE_ZERO"
    app.selectbox(key="ml_native_primary").select("NATIVE_A").run()
    app.selectbox(key="native_day").select("2025-12-03").run()
    assert app.selectbox(key="ml_native_primary").value == "NATIVE_ZERO"
    app.button_group(key="ml_section").set_value("Model engine").run()
    app.selectbox(key="ml_engine_ticker").select("NATIVE_B").run()
    app.button(key="ml_compare_action").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="ml_native_primary").value == "NATIVE_B"
    assert app.selectbox(key="native_day").value == "2025-12-03"
    assert app.selectbox(key="native_language").value == "ja"


def test_native_empty_engine_invalidates_previous_chart_and_rejects_its_event():
    app = _native_start()
    old_key = app.session_state["_ml_engine_chart_key"]
    assert old_key is not None and _chart(app) is not None
    app.checkbox(key="native_empty").check().run()
    assert not app.exception and not app.error
    assert not app.get("vega_lite_chart")
    assert app.session_state["_ml_engine_chart_key"] is None
    state = {"_ml_engine_chart_key": app.session_state["_ml_engine_chart_key"],
             "ml_engine_ticker": app.session_state["ml_engine_ticker"],
             old_key: {"selection": {"ml_security": [{"ticker": "NATIVE_B"}]}}}
    before = state["ml_engine_ticker"]
    with patch.object(machine_learning.st, "session_state", state):
        machine_learning._select_engine_security(("NATIVE_A", "NATIVE_B", "NATIVE_ZERO"), old_key)
    assert state["ml_engine_ticker"] == before


if __name__ == "__main__":
    _app()

def _historical_method_app():
    from contextlib import ExitStack
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.adapters import applied_account_reader as accounts
    from apps.demo_console.adapters import workspace_reader as workspace
    from apps.demo_console.adapters import selected_strategies_reader as selected
    from apps.demo_console.adapters import new_strategy_replay_reader as replay
    from apps.demo_console.models import DecisionOverview
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages import selected_strategies as page
    ids=("HGB_DIAG_5","R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR")
    st.selectbox("Strategy",ids,key="workspace_strategy")
    language=st.selectbox("Language",("en","zh","ja"),key="historical_language")
    st.session_state.setdefault("decision_date","2025-12-02")
    st.session_state["workspace_sample"]="historical"
    def forbidden(*args,**kwargs):
        raise AssertionError("Historical method presentation must not read records")
    with ExitStack() as stack,language_scope(language):
        for owner,name in ((accounts,"load_state"),(selected,"load_package"),(replay,"load_views"),
                           (workspace,"load_active_strategies"),(workspace,"load_active_rankings"),
                           (workspace,"load_overview"),(page,"_verified_raw_model")):
            stack.enter_context(patch.object(owner,name,forbidden))
        page.render_workspace(DecisionOverview(decision_date="2025-12-02",error="RAW_SENTINEL_ERROR"),
            {},view="Machine learning")


def test_historical_nonraw_methods_show_their_principle_and_boundary_with_explicit_empty_records():
    app=AppTest.from_function(_historical_method_app,default_timeout=15).run()
    for sid in _NATIVE_IDS[1:]:
        app.selectbox(key="workspace_strategy").select(sid).run()
        assert not app.exception and not app.error
        text=_visible_text(app)
        assert len(app.get("bidi_component"))==1
        assert json.loads(app.get("bidi_component")[0].proto.json)["strategy_id"]==sid
        assert "Training and development stay before 2026-01-01" in text
        assert "No verified native output is available for this observation." in text
        assert "RAW_SENTINEL_ERROR" not in text
        assert "selected HGB policies have no published training-period replay" not in text
        assert app.session_state["decision_date"]=="2025-12-02"
        assert not app.get("vega_lite_chart")
        assert not app.metric
        assert len(app.info) == 1
        assert "0 recorded securities" not in text
        assert "ml_engine_ticker" not in [item.key for item in app.selectbox]
        assert not {"ml_trace_action", "ml_compare_action"}.intersection(item.key for item in app.button)
        app.button_group(key="ml_section").set_value("Training lineage").run()
        assert not app.exception and not app.error
        assert "Training boundary" in _visible_text(app)
        app.button_group(key="ml_section").set_value("Validation map").run()
        assert not app.exception and not app.error
        assert "Evidence status" in app.dataframe[0].value.columns
        app.button_group(key="ml_section").set_value("Model engine").run()
    for language in ("zh","ja","en"):
        app.selectbox(key="historical_language").select(language).run()
        assert not app.exception and not app.error
        assert app.session_state["decision_date"]=="2025-12-02"
        assert len(app.get("bidi_component"))==1
        assert json.loads(app.get("bidi_component")[0].proto.json)["strategy_id"]=="R7_GROSS_LINEAR"

def test_native_main_case_selection_syncs_both_directions_without_comparison_pollution():
    app=_native_start()
    app.selectbox(key="native_strategy").select(_NATIVE_IDS[3]).run()
    app.selectbox(key="ml_engine_ticker").select("NATIVE_B").run()
    assert app.session_state["_research_case_ticker"]=="NATIVE_B"
    app.button_group(key="ml_section").set_value("Decision trace").run()
    assert app.selectbox(key="ml_trace_ticker").value=="NATIVE_B"
    app.selectbox(key="ml_trace_ticker").select("NATIVE_ZERO").run()
    assert app.session_state["_research_case_ticker"]=="NATIVE_ZERO"
    app.button_group(key="ml_section").set_value("Model engine").run()
    assert app.selectbox(key="ml_engine_ticker").value=="NATIVE_ZERO"
    app.button(key="ml_compare_action").click().run()
    assert app.selectbox(key="ml_native_primary").value=="NATIVE_ZERO"
    app.selectbox(key="ml_native_primary").select("NATIVE_A").run()
    app.selectbox(key="ml_native_secondary").select("NATIVE_B").run()
    assert app.session_state["_research_case_ticker"]=="NATIVE_ZERO"
    app.button_group(key="ml_section").set_value("Decision trace").run()
    assert app.selectbox(key="ml_trace_ticker").value=="NATIVE_ZERO"
    app.selectbox(key="ml_trace_ticker").select("NATIVE_A").run()
    app.selectbox(key="native_language").select("ja").run()
    app.button_group(key="ml_section").set_value("Model engine").run()
    assert app.selectbox(key="ml_engine_ticker").value=="NATIVE_A"
    assert app.selectbox(key="native_day").value=="2025-12-02"



def _same_pool_unranked_app():
    from apps.demo_console.models import DecisionOverview,HoldingRow
    from apps.demo_console.pages.machine_learning import render_machine_learning
    from apps.demo_console.tests.test_ml_engine_workspace import _native_workspace
    workspace=_native_workspace('RAW_A2')
    workspace['strategy_id']='RAW_s10'
    for row in workspace['rows']:
        row.update(rank=None,score=None,raw_rank=None,raw_score=None,native_action_score=None)
    model=DecisionOverview(decision_date='2025-12-02',ranking=(HoldingRow(1,'RAW_SENTINEL',99.),))
    render_machine_learning(model,workspace=workspace)


def test_same_pool_main_without_ranks_keeps_recorded_target_rows_and_never_borrows_raw_scores():
    app=AppTest.from_function(_same_pool_unranked_app,default_timeout=15).run()
    assert not app.exception and not app.error
    assert not any(w.key=='workspace_rank_band' for w in app.button_group)
    assert _chart(app) is not None
    assert app.selectbox(key='ml_engine_ticker').options==['NATIVE_A','NATIVE_B','NATIVE_ZERO']
    assert 'RAW_SENTINEL' not in _visible_text(app) and 'Target weight' in _visible_text(app)
    workspace=_native_workspace('RAW_A2');workspace['strategy_id']='RAW_s10'
    for row in workspace['rows']:row.update(rank=None,score=None,raw_rank=None,raw_score=None,native_action_score=None)
    chart,label=machine_learning.workspace_output_chart(workspace,'NATIVE_A')
    assert label=='Target weight'
    assert [row['value'] for row in chart.to_dict()['data']['values']]==[0.,.2,.05]
    assert all(row['rank'] is None for row in chart.to_dict()['data']['values'])


def test_partial_native_values_report_chart_coverage_without_filling_missing_values():
    workspace = _native_workspace(_NATIVE_IDS[3])
    for index, row in enumerate(workspace["rows"]):
        if index:
            row["native_action_score"] = None
    chart, label = machine_learning.workspace_output_chart(workspace, "NATIVE_A")
    assert label == "Recorded action value"
    assert len(chart.data.values) == 1
    assert chart.to_dict()["mark"]["size"] == 28
    assert chart.data.values[0]["value"] == -.25
    def script(workspace):
        from apps.demo_console.pages.machine_learning import _render_strategy_engine
        _render_strategy_engine(workspace)
    app = AppTest.from_function(script, args=(workspace,)).run()
    assert not app.exception and not app.error
    assert "1 plotted / 3 recorded securities" in _visible_text(app)
    assert "Only recorded values are plotted; missing values are not treated as zero." in _visible_text(app)
