"""Explain the recorded learning design before inspecting its model outputs."""
from collections.abc import Mapping
from functools import partial

import altair as alt
import streamlit as st

from apps.demo_console.components.ml_story import FEATURES, render_feature_atlas, render_learning_story
from apps.demo_console.components.ml_comparison import comparison_rows, render_model_comparison
from apps.demo_console.components.decision_trace import (
    carry_case, remember_case, render_decision_trace, resolve_case_ticker, trace_facts,
    performance_available, pending_execution,
)
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.score_profile import chart_records, score_chart
from apps.demo_console.components.top20_table import score_label, _applied_action_label
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.components.replay import pause_replay
from apps.demo_console.i18n import option_labeler, tr
from apps.demo_console.adapters import workspace_reader


SECTIONS = ("Model engine", "Compare outputs", "Training lineage", "Decision trace", "Validation map")


def visit_section(section: str) -> None:
    # The engine's focused security becomes the subject of the next inspection.
    if st.session_state.get("ml_section") == "Model engine":
        ticker = st.session_state.get("ml_engine_ticker")
        if ticker and section in ("Decision trace", "Compare outputs"):
            carry_case(ticker)
            if section == "Compare outputs":
                st.session_state["ml_native_primary"] = ticker
    if section in SECTIONS:
        st.session_state["ml_section"] = section
    else:
        st.session_state["workspace"] = section
        if section == "Research":
            st.session_state["research_period"] = "Historical research"
    pause_replay()


def _visit_trace_history() -> None:
    """Carry the inspected name forward without changing the decision date."""
    pause_replay(reset=True)
    carry_case(st.session_state.get("ml_trace_ticker"))
    st.session_state["workspace"] = "History"
    st.session_state["history_window"] = "60 snapshots"


def _visit_recovery() -> None:
    pause_replay()
    st.session_state["workspace"] = "Research"
    st.session_state["research_period"] = "Historical research"
    st.session_state["_localized_tabs:research_tabs"] = "Drawdown & recovery"


def _select_engine_security(tickers, key):
    if st.session_state.get("_ml_engine_chart_key") != key:
        return
    event = st.session_state.get(key)
    selection = event.get("selection") if isinstance(event, Mapping) else None
    rows = selection.get("ml_security") if isinstance(selection, Mapping) else None
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], Mapping):
        ticker = rows[0].get("ticker")
        if ticker in tickers:
            st.session_state["ml_engine_ticker"] = ticker
            remember_case("ml_engine_ticker")


def engine_score_chart(rows, selected):
    """Reuse the recorded profile and its safe domains; add a ticker selection."""
    focus = alt.selection_point(name="ml_security", fields=["ticker"], encodings=[],
                                on="click", clear="dblclick", empty=False, toggle=False)
    return (score_chart(rows).add_params(focus)
            .encode(color=alt.condition(alt.FieldEqualPredicate(field="ticker", equal=selected or ""),
                                        alt.value("#235c48"), alt.value("#8b9c82")))
            .properties(height=240)
            .configure_axis(labelColor="#9aa6ba", titleColor="#c5cfdf",
                            gridColor="#252e3d", gridDash=[1, 0]))


def learning_brief(model):
    """Describe supplied metadata; never infer a target or select another year's model."""
    missing = tr("Not recorded")
    profile = model.learning
    target = profile.target if not model.error else None
    columns = profile.feature_columns if not model.error else ()
    matches = tuple(vintage for vintage in profile.vintages
                    if not model.error and str(vintage.year) == str(model.decision_date or "")[:4])
    vintage = matches[0] if len(matches) == 1 else None
    if target == "mean 3/5/10/20 trading-day excess return vs QQQ":
        objective, horizons = tr("Mean return relative to QQQ"), tr("3 / 5 / 10 / 20 trading days")
    else:
        objective = tr(target) if target else missing
        horizons = tr("Recorded target") if target else tr("Target metadata is unavailable.")
    schema_matches = tuple(columns) == tuple(feature.name for feature in FEATURES)
    families = " · ".join(dict.fromkeys(tr(feature.group) for feature in FEATURES))
    inputs = tr("{count} recorded feature definitions", count=len(columns)) if columns else missing
    input_detail = families if schema_matches else tr(
        "Recorded schema; source-family mapping unavailable." if columns else "Feature metadata is unavailable.")
    training = (vintage.train_max_date or missing) if vintage else missing
    maturity = tr("Labels mature through {date}", date=vintage.train_target_end_max or missing) if vintage else tr("No matching annual vintage is recorded.")
    prediction = (f"{vintage.prediction_min_date} → {vintage.prediction_max_date}"
                  if vintage and vintage.prediction_min_date and vintage.prediction_max_date else missing)
    prediction_detail = tr("Recorded vintage · {year}", year=vintage.year) if vintage else tr("No matching annual vintage is recorded.")
    return (("Learning objective", objective, horizons), ("Recorded inputs", inputs, input_detail),
            ("Training observations through", training, maturity),
            ("Frozen prediction span", prediction, prediction_detail))


def _render_learning_brief(brief):
    with st.container(key="ml_method_summary", gap="small"):
        st.html(section_header(tr("Learning design"), aside=tr("Histogram gradient boosting")))
        cards = tuple('<article class="uq-ml-method-card"><span>' + text(tr(label))
                      + '</span><strong>' + text(value) + '</strong><small>'
                      + text(detail) + '</small></article>' for label, value, detail in brief)
        st.html('<section class="uq-ml-method-sheet"><div class="uq-ml-method-top">'
                + ''.join(cards[:2]) + '</div><div class="uq-ml-method-dates">'
                + ''.join(cards[2:]) + '</div></section>')
        st.caption(tr("Chronology is inspectable metadata. Predictive quality and independent validation still require separate evidence."))


def output_snapshot_html(facts):
    """Keep the current output visible without repeating the cross-page date chain."""
    if facts is None:
        return ""
    missing = tr("Not recorded")
    rank = f'#{facts["rank"]}' if facts["rank"] is not None else missing
    return ('<div class="uq-ml-inspector-stats" data-ticker="' + text(facts["ticker"]) + '">'
            + ''.join('<div><span>' + text(tr(label)) + '</span><strong>' + text(value) + '</strong></div>'
                      for label, value in (("Recorded rank", rank),
                                           ("Recorded model score", score_label(facts["score"]) or missing))) + '</div>')


def case_explanation(facts):
    """State the observed connection, without treating a score as a position."""
    if facts is None:
        return None
    if pending_execution(facts):
        source = "{ticker}'s signal is awaiting the next session open."
    elif facts["held_after"] is True:
        source = "{ticker} appears in both the recorded ranking and the linked post-execution portfolio."
    elif facts["held_after"] is False:
        source = "{ticker} appears in the recorded ranking and is absent from the linked post-execution portfolio."
    else:
        source = "{ticker} has a recorded ranking entry; linked post-execution membership is unavailable."
    return tr(source, ticker=facts["ticker"])


def _render_engine(model):
    display_model = workspace_reader.rank_band(model, st.session_state.get("workspace_rank_band", "Top20"))
    rows = comparison_rows(display_model)
    tickers = tuple(row.ticker for row in rows)
    focused = resolve_case_ticker(model)
    if focused not in tickers:
        focused = tickers[0] if tickers else None
    st.session_state["ml_engine_ticker"] = focused
    selected = st.session_state.get("ml_engine_ticker")
    brief = learning_brief(model)
    with st.container(key="ml_engine_workspace"):
        chart_column, inspector_column = st.columns([2.1, 1], gap="medium")
        with inspector_column:
            with st.container(key="ml_engine_inspector"):
                st.html(section_header(tr("Focused security")))
                if tickers:
                    selected = st.selectbox(tr("Inspect a ranked security"), tickers, index=None,
                                            key="ml_engine_ticker", persist_state="session", label_visibility="collapsed",
                                            on_change=remember_case, args=("ml_engine_ticker",))
                facts = trace_facts(model, selected)
                if facts:
                    with st.container(key="ml_case_summary"):
                        st.html(output_snapshot_html(facts))
                        st.html('<p class="uq-ml-reading-note uq-ml-case-explanation">'
                                + text(case_explanation(facts)) + '</p>')
                else:
                    st.caption(tr("No unambiguous ranked security is available to inspect."))
                with st.container(horizontal=True, gap="small", key="ml_engine_actions"):
                    st.button(tr("Inspect case"), key="ml_trace_action", type="primary", width="stretch",
                              icon=":material/route:", on_click=visit_section, args=("Decision trace",), disabled=not facts)
                    st.button(tr("Compare outputs"), key="ml_compare_action", width="stretch",
                              icon=":material/compare_arrows:", on_click=visit_section, args=(SECTIONS[1],), disabled=len(rows) < 2)
                with st.popover(tr("Case evidence"), icon=":material/more_horiz:", width="stretch"):
                    st.button(tr("Explore training lineage"), key="ml_lineage_action", width="stretch",
                              icon=":material/account_tree:", on_click=visit_section, args=(SECTIONS[2],))
                    st.button(tr("Inspect portfolio setbacks & recovery"), key="ml_case_recovery", width="stretch",
                              on_click=_visit_recovery, icon=":material/monitoring:",
                              disabled=not facts or not performance_available(model))
                    st.button(tr("Inspect source provenance"), key="ml_case_evidence", width="stretch",
                              on_click=visit_section, args=("Evidence",), icon=":material/fact_check:", disabled=not facts)
                    st.caption(tr("Recorded output and membership only. Attribution and RX approval are not available here."))
                    st.caption(tr("This case links records, not causes. The drawdown view describes the whole portfolio through the same cutoff, not this stock's contribution."))
        with chart_column:
            with st.container(key="ml_engine_chart_panel"):
                st.html(section_header(tr("Recorded score profile"), aside=tr("{count} ranked names", count=len(rows))))
                if chart_records(rows):
                    context = (model.decision_date, selected, tuple((row.ticker, row.rank, row.score) for row in rows))
                    if st.session_state.get("_ml_engine_chart_context") != context:
                        st.session_state["_ml_engine_chart_revision"] = st.session_state.get("_ml_engine_chart_revision", 0) + 1
                        st.session_state["_ml_engine_chart_context"] = context
                    key = f'ml_engine_scores_{st.session_state["_ml_engine_chart_revision"]}'
                    st.session_state["_ml_engine_chart_key"] = key
                    render_chart(engine_score_chart(rows, selected), width="stretch", theme=None, key=key,
                                 on_select=partial(_select_engine_security, tickers, key), selection_mode=["ml_security"])
                else:
                    st.session_state["_ml_engine_chart_key"] = None
                    st.info(tr("No recorded rank and score pairs are available for this snapshot."))
                st.caption(tr("Selected ranking range · Select a bar to focus the case." if model.source_id == "A2_UPDATED_RESEARCH" else "Recorded Top20 only · Select a bar to focus the case."))
    profile = model.learning
    identity = model.provenance.config_identity
    with st.expander(tr("Model mechanism and objective"), expanded=False):
        _render_learning_brief(brief)
        st.html('<div class="uq-ml-method-inline"><span>' + text(tr("Source-defined inputs"))
                + '</span><b aria-hidden="true">→</b><span>' + text(tr("Tree ensemble"))
                + '</span><b aria-hidden="true">→</b><span>' + text(tr("Recorded model score")) + '</span></div>')
        st.caption(tr("Mechanism schematic · not a fitted tree"))
        st.write(brief[0][1])
        st.caption(brief[0][2])
        st.caption(tr("Configuration identity") + " · " + (identity[:12] + "…" if identity else tr("Not recorded")))
    # Retain native open/close state across translated-label reruns.
    st.session_state["ml_feature_definitions_open"] = bool(
        st.session_state.get("ml_feature_definitions_open", False))
    with st.expander(tr("Explore all feature definitions"), key="ml_feature_definitions_open",
                     on_change="rerun", icon=":material/schema:"):
        render_feature_atlas(profile.feature_columns)


def validation_rows(model):
    """Evidence coverage, never a scientific score or universal health status."""
    usable = not model.error
    updated = model.source_id == "A2_UPDATED_RESEARCH"
    return (
        ("Model identity", "Verified metadata" if usable and model.provenance.config_identity else "Not exposed",
         "The consumed freeze binds the model family, configuration and source identity."),
        ("Training chronology", "Recorded" if usable and model.learning.vintages else "Not exposed",
         "Annual training and label-maturity dates are recorded; this page does not rerun the complete training audit."),
        ("Historical model outputs", "Recorded" if usable and model.ranking else "Not exposed",
         "Updated daily Top40 rankings; simulated holdings still follow the original Top20 rule." if updated else "Scores and ranks are original Top20 records. The rest of the eligible universe is not loaded."),
        ("Single-stock attribution", "Not exposed",
         "Annual models were rebuilt and saved under fixed rules. Local feature contributions are not calculated here." if updated else "Historical stage models were not persisted. Exact feature snapshots and a matching model are needed for local explanations."),
        ("Predictive quality", "Not evaluated here",
         "Rank correlation and score-bucket tests need full-universe predictions, matured labels and evaluation lineage. Portfolio returns alone do not answer this question."),
        ("Historical holdings", "Recorded" if usable and model.holdings else "Not exposed",
         "The linked execution records identify held names. Portfolio returns, drawdowns and costs are inspected separately in Research."),
        ("Incremental model advantage", "Not evaluated here",
         "A higher portfolio return does not isolate the model's contribution. A fixed baseline, matched information and costs, module-removal comparisons and the full trial history are needed."),
        ("Independent confirmation", "Not established",
         "This replay is retrospective. Recorded stage names and frozen identities do not establish an untouched independent test."),
    )


def validation_groups(model):
    """Split supported record types from missing records and untested claims."""
    rows = validation_rows(model)
    observed = tuple(row for row in rows if row[1] in ("Recorded", "Verified metadata"))
    unestablished = tuple(row for row in rows if row[1] not in ("Recorded", "Verified metadata"))
    return observed, unestablished


def _render_validation(model):
    st.html(section_header(tr("A model claim needs a matching piece of evidence"), tr("VALIDATION MAP")))
    st.caption(tr("This map separates what can be inspected today from what still requires additional records. It is not a model-quality score."))
    observed, unestablished = validation_groups(model)
    for heading, explanation, rows in (
            ("Observed in the available records", "These statements describe traceable metadata and observations, not predictive quality.", observed),
            ("Not established by this workspace", "These claims need additional evidence. Missing data and unperformed tests are kept visible.", unestablished)):
        st.html(section_header(tr(heading)))
        st.caption(tr(explanation))
        if not rows:
            st.caption(tr("No current record supports this group."))
            continue
        st.html('<div class="uq-ml-evidence-grid">' + ''.join(
            '<article class="uq-ml-evidence-card"><span class="uq-ml-evidence-number">' + f'{index:02}'
            + '</span><div><div class="uq-ml-evidence-heading"><h3>' + text(tr(title)) + '</h3><span class="'
            + ('uq-ml-status-recorded' if state in ("Recorded", "Verified metadata") else 'uq-ml-status-pending')
            + '">' + text(tr(state)) + '</span></div><p>' + text(tr(detail)) + '</p></div></article>'
            for index, (title, state, detail) in enumerate(rows, 1)) + '</div>')
    with st.container(border=True):
        st.html(section_header(tr("What would demonstrate a learning advantage?"), tr("THE NEXT EVIDENCE LAYER")))
        st.markdown(tr("Compare the model with a fixed baseline under the same dates, information and costs. Inspect ranking quality, weak periods and the full trial history alongside returns."))
        st.caption(tr("Frozen historical records are retrospective evidence. Stage names and file hashes do not establish an untouched independent test."))
        with st.container(horizontal=True):
            st.button(tr("Open performance & evidence"), key="ml_open_research", on_click=visit_section,
                      args=("Research",), type="primary", icon=":material/analytics:")
            st.button(tr("Inspect source provenance"), key="ml_open_evidence", on_click=visit_section,
                      args=("Evidence",), icon=":material/fact_check:")


def _workspace_number(value, *, percent=False):
    from math import isfinite
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        return tr("Not recorded")
    return format(value, ".2%" if percent else ".6g")


def _workspace_selection(workspace, key, *, exclude=None):
    tickers = tuple(row["ticker"] for row in workspace["rows"] if row["ticker"] != exclude)
    remembered = st.session_state.get("_research_case_ticker")
    focused = remembered if remembered in tickers else st.session_state.get("ml_engine_ticker")
    if key in ("ml_engine_ticker", "ml_trace_ticker") and focused in tickers:
        st.session_state[key] = focused
    if key == "ml_native_primary":
        context = (workspace["strategy_id"], workspace["score_date"], focused)
        if st.session_state.get("_ml_native_comparison_context") != context:
            if focused in tickers:
                st.session_state[key] = focused
            st.session_state["_ml_native_comparison_context"] = context
    if st.session_state.get(key) not in tickers:
        st.session_state[key] = focused if focused in tickers else next(iter(tickers), None)
    if not tickers:
        return None
    options = ({"on_change": remember_case, "args": (key,)}
        if key in ("ml_engine_ticker", "ml_trace_ticker") else {})
    return st.selectbox(tr("Focused security") if exclude is None else tr("Comparison security"),
        tickers, index=None, key=key, persist_state="session",
        label_visibility="collapsed" if key == "ml_engine_ticker" else "visible", **options)


def _native_score_label(workspace):
    return {"R6_BUY_NEURAL": "Recorded buy-superiority probability",
            "R6_DURATION_TREE": "Recorded failure probability"}.get(workspace["strategy_id"], "Recorded action value")


def _native_probability(workspace):
    return workspace["strategy_id"] in ("R6_BUY_NEURAL", "R6_DURATION_TREE")


def workspace_output_chart(workspace, selected, *, rows=None):
    """Plot recorded native units; action values never become stock ranks."""
    from math import isfinite
    rows = workspace["rows"] if rows is None else rows
    ranked = workspace["output_kind"] == "RANK_SCORE"
    field = "score" if ranked else "native_action_score"
    valid = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    if not any(valid(row.get(field)) for row in rows):
        field = "target_weight"
    labels = {"score": "Recorded model score", "native_action_score": _native_score_label(workspace),
              "target_weight": "Target weight"}
    records = [{"ticker": row["ticker"], "value": row[field], "rank": row.get("rank")}
               for row in rows if valid(row.get(field))]
    if not records:
        return None, labels[field]
    ordered = sorted(records, key=lambda row: (row["rank"] is None, row["rank"] or 0, row["ticker"]))
    values = [0., *(row["value"] for row in ordered)]
    low, high = min(values), max(values)
    if low == high:
        high = low + 1.
    focus = alt.selection_point(name="ml_security", fields=["ticker"], encodings=[],
        on="click", clear="dblclick", empty=False, toggle=False)
    percent = field == "target_weight" or field == "native_action_score" and _native_probability(workspace)
    axis = alt.Axis(format=".0%" if percent else ".3~g")
    sparse_bar = {"size": 28} if len(ordered) < 8 else {}
    chart = (alt.Chart(alt.Data(values=ordered)).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, **sparse_bar)
        .encode(x=alt.X("ticker:N", sort=[row["ticker"] for row in ordered], title=tr("Ticker")),
            y=alt.Y("value:Q", title=tr(labels[field]), scale=alt.Scale(domain=[low, high]), axis=axis),
            color=alt.condition(alt.FieldEqualPredicate(field="ticker", equal=selected or ""),
                alt.value("#3159ff"), alt.value("#9aaed6")),
            tooltip=[alt.Tooltip("ticker:N", title=tr("Ticker")),
                     alt.Tooltip("value:Q", title=tr(labels[field]), format=".2%" if percent else ".6g")])
        .add_params(focus).properties(height=260))
    return chart, labels[field]


def _workspace_facts(row, workspace):
    facts = []
    if workspace["output_kind"] == "RANK_SCORE":
        facts.extend((("Recorded rank", str(row["rank"]) if row.get("rank") is not None else tr("Not recorded")),
                      ("Recorded model score", _workspace_number(row.get("score")))))
    else:
        action = _applied_action_label(row.get("action")) or tr("Not recorded")
        if workspace["output_kind"] == "GROSS_EXPOSURE":
            gross = workspace["target"].get("requested_gross", workspace["model_identity"].get("requested_gross"))
            facts.extend((("Recorded model action", action), ("Requested gross exposure", _workspace_number(gross, percent=True))))
        else:
            facts.extend((("Recorded model action", action),
                          (_native_score_label(workspace), _workspace_number(row.get("native_action_score"), percent=_native_probability(workspace)))))
    facts.append(("Target weight", _workspace_number(row.get("target_weight"), percent=True)))
    return facts


def _render_strategy_engine(workspace):
    with st.container(key="ml_engine_workspace"):
        chart_column, inspector_column = st.columns([2.1, 1], gap="medium")
        with inspector_column:
            with st.container(key="ml_engine_inspector"):
                st.html(section_header(tr("Focused security")))
                selected = _workspace_selection(workspace, "ml_engine_ticker")
                row = next((row for row in workspace["rows"] if row["ticker"] == selected), None)
                if row:
                    st.html('<div class="uq-ml-inspector-stats">' + ''.join(
                        '<div><span>' + text(tr(label)) + '</span><strong>' + text(value) + '</strong></div>'
                        for label, value in _workspace_facts(row, workspace)[:2]) + '</div>')
                    st.metric(tr("Target weight"), _workspace_number(row.get("target_weight"), percent=True))
                with st.container(horizontal=True, gap="small"):
                    st.button(tr("Inspect case"), key="ml_trace_action", type="primary", width="stretch",
                        on_click=visit_section, args=("Decision trace",), disabled=row is None)
                    st.button(tr("Compare outputs"), key="ml_compare_action", width="stretch",
                        on_click=visit_section, args=("Compare outputs",), disabled=len(workspace["rows"]) < 2)
        with chart_column:
            with st.container(key="ml_engine_chart_panel"):
                chart, label = workspace_output_chart(workspace, selected)
                plotted_count = len(chart.data.values) if chart is not None else 0
                total = len(workspace["rows"])
                aside = (tr("{count} plotted / {total} recorded securities", count=plotted_count, total=total)
                    if chart is not None and plotted_count < total else tr("{count} recorded securities", count=total))
                st.html(section_header(tr(label), aside=aside))
                if chart is None:
                    st.session_state["_ml_engine_chart_key"] = None
                    st.info(tr("No verified native output is available for this observation."))
                else:
                    context = (workspace["strategy_id"], workspace["score_date"], selected,
                        tuple((row["ticker"], row.get("score"), row.get("native_action_score"), row.get("target_weight")) for row in workspace["rows"]))
                    if st.session_state.get("_ml_engine_chart_context") != context:
                        st.session_state["_ml_engine_chart_revision"] = st.session_state.get("_ml_engine_chart_revision", 0) + 1
                        st.session_state["_ml_engine_chart_context"] = context
                    key = f'ml_engine_scores_{st.session_state["_ml_engine_chart_revision"]}'
                    st.session_state["_ml_engine_chart_key"] = key
                    render_chart(chart, width="stretch", theme=None, key=key,
                        on_select=partial(_select_engine_security, tuple(row["ticker"] for row in workspace["rows"]), key),
                        selection_mode=["ml_security"])
                st.caption(tr("Select a bar or a security to inspect its recorded decision."))
                if chart is not None and plotted_count < total:
                    st.caption(tr("Only recorded values are plotted; missing values are not treated as zero."))
    if workspace["output_kind"] != "RANK_SCORE":
        st.caption(tr("Recorded probabilities follow the frozen action decoder; they do not rank stock returns.") if _native_probability(workspace)
            else tr("Action values compare native decisions. They are not stock-return scores or probabilities."))
    if workspace["output_kind"] == "GROSS_EXPOSURE":
        target = workspace["target"]
        before, after = st.columns(2)
        before.metric(tr("Previous requested gross exposure"), _workspace_number(target.get("previous_requested_gross", workspace["model_identity"].get("previous_requested_gross", workspace["model_identity"].get("previous_gross"))), percent=True))
        after.metric(tr("Requested gross exposure"), _workspace_number(target.get("requested_gross", workspace["model_identity"].get("requested_gross")), percent=True))


def _render_strategy_comparison(workspace):
    st.html(section_header(tr("Compare outputs")))
    if len(workspace["rows"]) < 2:
        st.info(tr("Two recorded securities are required for comparison."))
        return
    first, second = st.columns(2)
    with first:
        primary = _workspace_selection(workspace, "ml_native_primary")
    with second:
        secondary = _workspace_selection(workspace, "ml_native_secondary", exclude=primary)
    rows = [next(row for row in workspace["rows"] if row["ticker"] == ticker) for ticker in (primary, secondary)]
    left, right = (_workspace_facts(row, workspace) for row in rows)
    st.dataframe([{tr("Field"): tr(a[0]), primary: a[1], secondary: b[1]}
        for a, b in zip(left, right)], hide_index=True, width="stretch")
    chart, _ = workspace_output_chart(workspace, primary, rows=rows)
    if chart is not None:
        render_chart(chart, width="stretch", theme=None, key="ml_native_pair_chart")
    st.caption(tr("Same-date recorded outputs. Each strategy keeps its own units and decision rules."))


def _render_strategy_lineage(workspace, *, presentation):
    from apps.demo_console.components.strategy_workbench import TRAINING_BOUNDARY
    st.html(section_header(tr("Training lineage")))
    identity = workspace["model_identity"]
    profile = workspace["learning"]
    cutoff = identity.get("signal_cutoff_exclusive") or identity.get("fit_cutoff_exclusive")
    maturity = identity.get("label_maturity_cutoff_exclusive")
    facts = [(tr("Training boundary"), '< ' + cutoff if cutoff else tr("Not recorded")),
             (tr("Label maturity boundary"), '< ' + maturity if maturity else tr("Not recorded")),
             (tr("Model input features"), str(identity.get("feature_count") or len(profile.feature_columns)) if identity.get("feature_count") or profile.feature_columns else tr("Not recorded")),
             (tr("Prediction target"), tr(profile.target) if profile.target else tr("Not recorded"))]
    st.dataframe([{tr("Field"): key, tr("Value"): value} for key, value in facts], hide_index=True, width="stretch")
    st.caption(tr(TRAINING_BOUNDARY))
    if profile.feature_columns:
        st.write(" · ".join(profile.feature_columns))
    else:
        st.caption(tr("Feature order and fitted transforms are not exposed by this reader."))
    if not presentation:
        with st.expander(tr("Model identity and interpretation")):
            st.json(identity)


def _render_strategy_trace(workspace):
    st.html(section_header(tr("Decision trace")))
    selected = _workspace_selection(workspace, "ml_trace_ticker")
    row = next((row for row in workspace["rows"] if row["ticker"] == selected), None)
    if row is None:
        st.info(tr("No verified native output is available for this observation."))
        return
    facts = [("Decision date", workspace["score_date"]), *_workspace_facts(row, workspace),
             ("Raw input rank", str(row["raw_rank"]) if row.get("raw_rank") is not None else tr("Not recorded")),
             ("Raw input score", _workspace_number(row.get("raw_score"))),
             ("Previous weight", _workspace_number(row.get("weight_before") if row.get("weight_before") is not None else row.get("research_weight_before"), percent=True)),
             ("Recorded HOLD units", _workspace_number(row.get("hold_units") if row.get("hold_units") is not None else row.get("exact_hold_units")))]
    st.dataframe([{tr("Field"): tr(label), tr("Value"): value or tr("Not recorded")} for label, value in facts],
                 hide_index=True, width="stretch")
    st.caption(tr("Raw input ranks describe upstream inputs. Native actions and target weights remain separate outputs."))
    st.caption(tr("Targets are intended holdings. Orders and confirmed fills are recorded separately."))


def _render_strategy_validation(workspace, *, presentation=True):
    st.html(section_header(tr("Validation map")))
    identity = workspace["model_identity"]
    observations = (("Historical model outputs", bool(workspace["rows"])),
                    ("Model identity", bool(identity)),
                    ("Training chronology", bool(identity.get("signal_cutoff_exclusive") or identity.get("fit_cutoff_exclusive"))),
                    ("Recorded inputs", bool(workspace["learning"].feature_columns)))
    st.dataframe([{tr("Field"): tr(label), tr("Evidence status"): tr("Recorded" if recorded else "Not exposed")}
        for label, recorded in observations], hide_index=True, width="stretch")
    st.caption(tr("Frozen historical records are retrospective evidence. Stage names and file hashes do not establish an untouched independent test."))
    with st.expander(tr("Decision provenance")):
        if presentation:
            st.write(tr("Recorded source") + " · " + tr(workspace["record_basis"]))
            st.write(tr("Decision date") + " · " + str(workspace["score_date"] or tr("Not recorded")))
        else:
            st.json(workspace["provenance"])


def render_machine_learning(model, *, presentation=True, workspace=None):
    if workspace is None and model.error:
        st.info(tr("Machine learning records require a verified historical snapshot."))
        return
    if (workspace is not None and workspace["output_kind"] == "RANK_SCORE"
            and any(type(row.get("rank")) is int for row in workspace["rows"])):
        band = st.segmented_control(tr("Rank range"), ("Top20", "21–40", "Top40"), default="Top20",
            required=True, key="workspace_rank_band", persist_state="session")
        low, high = (21, 40) if band == "21–40" else (1, 40) if band == "Top40" else (1, 20)
        workspace = {**workspace, "rows": [row for row in workspace["rows"]
            if type(row.get("rank")) is int and low <= row["rank"] <= high]}
    if st.session_state.get("ml_section") not in SECTIONS:
        st.session_state["ml_section"] = SECTIONS[0]
    section = st.segmented_control(tr("Explore the model"), SECTIONS, required=True,
        format_func=option_labeler(SECTIONS), key="ml_section", persist_state="session",
        label_visibility="collapsed", width="stretch", wrap=True)
    if workspace is not None:
        from apps.demo_console.components.strategy_workbench import (
            strategy_label, render_method_explanation, TRAINING_BOUNDARY,
        )
        st.caption(tr(strategy_label(workspace["strategy_id"])) + " · " + tr(workspace["record_basis"]))
        if section in (SECTIONS[0], SECTIONS[2]) or workspace.get("mechanism_only"):
            render_method_explanation(workspace["strategy_id"], presentation=presentation, key="ml_method_explanation")
        if section == SECTIONS[0] and not workspace["rows"]:
            st.session_state["_ml_engine_chart_key"] = None
            st.session_state["ml_engine_ticker"] = None
            st.caption(tr(TRAINING_BOUNDARY))
            st.info(tr("No verified native output is available for this observation."))
            # Offer an explicit query into a known frozen range; changing a
            # method never silently rewinds the shared research observation.
            end = workspace["model_identity"].get("frozen_main_end")
            dates = tuple(st.session_state.get("_workbench_dates:test_2026", ()))
            if (st.session_state.get("workspace_sample", "test_2026") == "test_2026"
                    and isinstance(end, str) and end in dates
                    and isinstance(model.decision_date, str) and end < model.decision_date):
                from apps.demo_console.app import _select_recorded_date
                st.button(tr("Inspect frozen records through {date}", date=end),
                    key="ml_frozen_records", on_click=_select_recorded_date, args=(dates, end))
            return
        if workspace.get("mechanism_only"):
            st.caption(tr(TRAINING_BOUNDARY))
        if workspace.get("error"):
            st.info(tr("No verified native output is available for this observation."))
        if section == SECTIONS[0]:
            _render_strategy_engine(workspace)
        elif section == SECTIONS[1]:
            _render_strategy_comparison(workspace)
        elif section == SECTIONS[2]:
            _render_strategy_lineage(workspace, presentation=presentation)
        elif section == SECTIONS[3]:
            _render_strategy_trace(workspace)
        else:
            _render_strategy_validation(workspace, presentation=presentation)
        return
    if section == SECTIONS[0]:
        _render_engine(model)
    elif section == SECTIONS[1]:
        render_model_comparison(model, presentation=presentation)
    elif section == SECTIONS[2]:
        render_learning_story(model, presentation=presentation)
    elif section == "Decision trace":
        render_decision_trace(model, presentation=presentation)
        facts = trace_facts(model, st.session_state.get("ml_trace_ticker"))
        with st.container(horizontal=True, gap="small"):
            st.button(tr("Follow this security in History"), key="ml_trace_history",
                      on_click=_visit_trace_history, icon=":material/timeline:",
                      disabled=trace_facts(model, st.session_state.get("ml_trace_ticker")) is None)
            st.button(tr("Inspect portfolio setbacks & recovery"), key="ml_trace_recovery",
                      on_click=_visit_recovery, icon=":material/monitoring:", type="primary",
                      disabled=not facts or not performance_available(model))
            with st.popover(tr("Case evidence"), icon=":material/more_horiz:"):
                st.button(tr("Explore training lineage"), key="ml_trace_lineage", width="stretch",
                          on_click=visit_section, args=("Training lineage",), icon=":material/account_tree:")
                st.button(tr("Inspect source provenance"), key="ml_trace_evidence", width="stretch",
                          on_click=visit_section, args=("Evidence",), icon=":material/fact_check:", disabled=not facts)
    else:
        _render_validation(model)
    st.html('<p class="uq-ml-reading-note">' + text(tr("Model scores describe recorded outputs. They are not probabilities, portfolio weights or trade instructions.")) + '</p>')
