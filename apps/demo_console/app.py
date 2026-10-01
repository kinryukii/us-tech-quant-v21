"""Read-only Streamlit research terminal over the canonical overview adapter."""
import streamlit as st
from datetime import date

from apps.demo_console.pages.overview import render_overview
from apps.demo_console.components.visuals import apply_style, sidebar_brand, brand_mark, text
from apps.demo_console.i18n import LANGUAGES, set_language, tr
from apps.demo_console.components.replay import pause_replay, sync_replay_context
from apps.demo_console.components.demo_tour import render_tour_launcher, workspace_options
from apps.demo_console.adapters import workspace_reader
from apps.demo_console.adapters import updated_research_reader
from apps.demo_console.adapters import selected_strategies_reader
from apps.demo_console.components.trading_workspace import render_trading_links, render_trading_workspace
from apps.demo_console.pages.selected_strategies import render_selected_strategies, WORKSPACE_STRATEGIES

_WORKSPACE_LABELS = {"Overview": "Overview", "Machine learning": "Machine learning",
                     "Portfolio": "Decisions & portfolio", "History": "Decisions & portfolio",
                     "Research": "Performance & risk", "Evidence": "Research evidence"}
_STRATEGIES = WORKSPACE_STRATEGIES


def _refresh_localized_selections() -> None:
    # Streamlit keeps a selectbox's input label when its raw value is unchanged.
    # Reassigning the existing value tells it to send the new localized label.
    for key in ("workspace", "workspace_strategy", "workspace_sample", "portfolio_workspace", "history_window", "record_set", "membership_filter", "research_range",
                "ml_section", "ml_history_window", "ml_history_metric", "ml_feature_family", "ml_feature_name",
                "research_drawdown_episode", "system_capability", "system_pit_case", "research_period",
                "recorded_2026_chart_mode", "recorded_2026_source", "recorded_2026_curve_focus", "research_curve_focus"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    pause_replay()


def _change_strategy() -> None:
    pause_replay(reset=True)
    for key in tuple(st.session_state):
        if key in (
                "_system_chart_context", "research_drawdown_episode", "_rendered_workspace",
                "_research_case_ticker"):
            st.session_state.pop(key, None)


def _step_date(dates: tuple[str, ...], direction: int) -> None:
    pause_replay(reset=True)
    current = st.session_state.get("decision_date", dates[-1])
    index = dates.index(current) if current in dates else len(dates) - 1
    st.session_state["decision_date"] = dates[max(0, min(len(dates) - 1, index + direction))]


def _overview_page(pages=None) -> None:
    context = st.session_state.pop("_applied_workspace_context", None)
    if context:
        st.session_state.update(context)
    _refresh_published_data()
    # Retire the previous version switch, including its persisted browser value.
    # A frozen-view date must not silently become the same day's recalculated case.
    previous = st.session_state.pop("workspace_source", None)
    if previous == workspace_reader.FROZEN:
        st.session_state["decision_date"] = st.session_state.get(f"_source_date:{workspace_reader.LATEST}")
        pause_replay(reset=True)
        for key in ("_research_case_ticker", "inspect_ticker", "ml_engine_ticker", "ml_trace_ticker",
                    "history_ticker", "_history_focus", "system_focus_ticker", "system_inspect_execution",
                    "research_dates", "research_drawdown_episode", "_system_chart_context"):
            st.session_state.pop(key, None)
    st.session_state["research_period"] = "Historical research"
    if "workspace_sample" not in st.session_state:
        selected = st.session_state.get("decision_date")
        st.session_state["workspace_sample"] = "historical" if selected and selected < "2026-01-01" else "test_2026"
    _render_historical_workspace(pages)


def _change_sample():
    previous = st.session_state.get("_workspace_sample_seen")
    if previous and st.session_state.get("decision_date"):
        st.session_state[f"_sample_date:{previous}"] = st.session_state["decision_date"]
    sample = st.session_state["workspace_sample"]
    st.session_state["decision_date"] = st.session_state.get(f"_sample_date:{sample}")
    pause_replay(reset=True)
    for key in tuple(st.session_state):
        if key.startswith("_performance_range:research_dates:") or key in (
            "research_range", "research_calendar_month", "research_calendar_quarter", "research_dates_draft",
            "research_single_date", "research_random_bounds", "_research_random_dates",
            "research_dates", "research_drawdown_episode", "_system_chart_context", "system_inspect_execution",
            "workspace_period_range", "workspace_period_day", "_research_case_ticker", "system_focus_ticker",
            "inspect_ticker", "ml_engine_ticker", "history_ticker", "_history_focus"):
            st.session_state.pop(key, None)

    st.session_state["research_range"] = "All days through selected execution"


def _load_workspace_model():
    source = workspace_reader.LATEST
    latest = workspace_reader.load_overview(source=source)
    sample = st.session_state.get("workspace_sample", "test_2026")
    scoped = workspace_reader.scope_overview(latest, sample)
    identity = (source, latest.source_manifest_sha256)
    previous = st.session_state.get("_workspace_binding_seen")
    if previous != identity:
        pause_replay(reset=True)
        st.session_state.pop("_system_chart_context", None)
        st.session_state.pop("research_drawdown_episode", None)
        st.session_state["_workspace_binding_seen"] = identity
        if previous and previous[0] == source:
            st.session_state["decision_date"] = scoped.available_dates[-1] if scoped.available_dates else None
        for key in ("workspace_period_range", "workspace_period_day"):
            st.session_state.pop(key, None)
    selected = st.session_state.get("decision_date")
    if selected not in scoped.available_dates:
        observed = tuple(day for day in scoped.available_dates if selected is None or day <= selected)
        selected = observed[-1] if observed else None
    if selected is None:
        from dataclasses import replace
        return replace(scoped, decision_date=None, ranking=(), holdings=(), performance_cutoff_date=None)
    if selected and selected != latest.decision_date:
        return workspace_reader.scope_overview(workspace_reader.load_overview(selected, source=source,
                    reference=workspace_reader.source_reference(latest)), sample)
    return scoped


def _jump_period_date():
    if st.session_state.get("workspace_period_day"):
        st.session_state["decision_date"] = st.session_state["workspace_period_day"]
        pause_replay(reset=True)


def _period_navigation(dates):
    with st.expander(tr("Browse a period"), expanded=False):
        first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        interval = st.date_input(tr("Date range"), value=(first, last), min_value=first,
            max_value=last, key="workspace_period_range")
        if isinstance(interval, (tuple, list)) and len(interval) == 2:
            choices = tuple(day for day in dates if interval[0].isoformat() <= day <= interval[1].isoformat())
            if choices:
                current = st.session_state.get("decision_date")
                st.session_state["workspace_period_day"] = current if current in choices else None
                st.selectbox(tr("Signal date in this period"), choices, index=None, key="workspace_period_day",
                    placeholder=tr("Choose a signal date"), on_change=_jump_period_date)
                st.caption(tr("{count} recorded signal dates. Your selection applies to every section.", count=len(choices)))
            else:
                st.caption(tr("No recorded rankings in this period. Missing dates are not filled."))


def _render_historical_workspace(pages=None) -> None:
    source = workspace_reader.LATEST
    apply_style(presentation=st.session_state.get("presentation_mode", True))
    with st.container(key="uq_utility_bar"):
        identity, scope_label, date_picker, language_picker = st.columns(
            [1.3, 1.5, 1.1, .7], gap="small", vertical_alignment="center", wrap=False)
        # Render the language first even though its column is on the right, so
        # every subsequently rendered label uses the current language context.
        with language_picker:
            language = st.selectbox("Language / 语言 / 言語", list(LANGUAGES), index=2,
                                    key="language", format_func=LANGUAGES.get, bind="query-params",
                                    on_change=_refresh_localized_selections, label_visibility="collapsed")
        set_language(language)
        if st.session_state.get("workspace_strategy") not in _STRATEGIES:
            st.session_state["workspace_strategy"] = "RAW_A2"
        with scope_label:
            st.caption(tr("3 fixed strategies · Compare together"))
        with identity:
            st.html('<div class="uq-utility-identity">' + brand_mark()
                    + '<div><strong>US TECH QUANT</strong><span>'
                    + text(tr("RESEARCH WORKSPACE")) + '</span></div></div>')
        with date_picker:
            date_controls = st.container()
    with st.sidebar:
        sidebar_brand()
        st.html(f'<div class="uq-nav-label">{text(tr("WORKSPACE"))}</div>')
        options = workspace_options(st.session_state.get("workspace"),
                                    st.session_state.get("portfolio_workspace", "Portfolio"))
        if st.session_state.get("workspace") not in options:
            st.session_state["workspace"] = "Overview"
        workspace_labels = {name: f'{number:02}  {tr(_WORKSPACE_LABELS[name])}'
                            for number, name in enumerate(options, 1)}
        view = st.radio(tr("Workspace"), options, index=None,
                        key="workspace", label_visibility="collapsed",
                        format_func=workspace_labels.__getitem__, on_change=pause_replay)
        sample_labels = {"historical": tr("Historical training / validation"), "test_2026": tr("2026 test sample")}
        st.selectbox(tr("Sample"), tuple(sample_labels), key="workspace_sample",
                 format_func=sample_labels.__getitem__, on_change=_change_sample, persist_state="session",
                 help=tr("Historical results include annual out-of-fold validation. The frozen model's 2026 observations are displayed separately and are not used for training or tuning."))
        st.caption(tr("Sample years: {years}", years="2023–2025" if st.session_state["workspace_sample"] == "historical" else "2026"))
        st.session_state["_workspace_sample_seen"] = st.session_state["workspace_sample"]
        with st.expander(tr("Strategy details"), expanded=False):
            strategy_labels = {strategy: tr(label) for strategy, label in _STRATEGIES.items()}
            st.selectbox(tr("Strategy details"), tuple(_STRATEGIES), key="workspace_strategy",
                format_func=strategy_labels.__getitem__, on_change=_change_strategy, persist_state="session")
            st.caption(tr("Detail focus only. All three strategies remain in the main comparison."))
        tour_launcher = st.container() if view != "Overview" else None
        st.html(f'<div class="uq-sidebar-rule"></div><div class="uq-nav-label">{text(tr("Observation date"))}</div>')
        date_navigation = st.container(key="uq_sidebar_date_navigation")
        st.html('<div class="uq-sidebar-rule"></div>')
        with st.popover(tr("Display & motion"), width="stretch"):
            presentation = st.toggle(tr("Presentation Mode"), value=True, key="presentation_mode",
                                     help=tr("Larger text for presenting. Private source paths, full hashes and technical metadata stay hidden."))
            st.toggle(tr("Animated transitions"), value=True, key="motion_enabled")
            st.caption(tr("Motion respects your system's reduced-motion preference. Values always display their recorded result."))
        if pages is not None:
            st.divider()
            render_trading_links(pages)
        st.html(f'<div class="uq-sidebar-footer"><strong>{text(tr("3 applied strategies"))}</strong>'
                f'{text(tr("History and latest data · One research workspace"))}<br>{text(tr("Read only. No execution."))}</div>')

    try:
        # The reader validates the selected date and returns its verified
        # calendar. Avoid fully reading the latest snapshot before this one.
        with st.spinner(tr("Loading verified records…"), show_time=True):
            selected_package = None
            comparison_package = None
            selected_strategy = st.session_state["workspace_strategy"]
            if selected_strategy in selected_strategies_reader.STRATEGY_IDS:
                selected_package = selected_strategies_reader.load_package()
                st.session_state["_selected_strategy_binding_seen"] = selected_package["package_sha256"]
                strategy_dates = workspace_reader.applied_observation_dates(selected_package,
                    st.session_state["workspace_sample"])
                model = workspace_reader.load_selected_overview(selected_strategy,
                    st.session_state.get("decision_date"), package=selected_package,
                    sample=st.session_state["workspace_sample"], observation_dates=strategy_dates)
            else:
                model = _load_workspace_model()
                strategy_dates = model.available_dates
                if st.session_state["workspace_sample"] == "test_2026":
                    comparison_package = selected_strategies_reader.load_package()
                    strategy_dates = workspace_reader.applied_observation_dates(comparison_package,
                        st.session_state["workspace_sample"], raw_model=model)
        with date_controls:
            if strategy_dates:
                dates = strategy_dates
                if st.session_state.get("decision_date") not in dates:
                    st.session_state["decision_date"] = model.decision_date if model.decision_date in dates else dates[-1]
                selected_date = st.selectbox(tr("Observation date"), options=dates, index=None,
                                         key="decision_date", help=tr("One signal timeline across history and the latest verified results. Browsing does not recalculate."),
                                         on_change=pause_replay, kwargs={"reset": True},
                                         label_visibility="collapsed", persist_state="session")
                position = dates.index(selected_date)
            else:
                selected_date = None
                st.info(tr("No displayable decision date is currently available."))
        with date_navigation:
            if selected_date is not None:
                back, forward = st.columns(2, gap="small")
                back.button(tr("← Prev"), on_click=_step_date, args=(dates, -1),
                            disabled=position == 0, width="stretch", key="previous_date")
                forward.button(tr("Next →"), on_click=_step_date, args=(dates, 1),
                               disabled=position == len(dates) - 1, width="stretch", key="next_date")
                counter_label = ("{position} / {total} recorded snapshots" if selected_package is None
                                 else "{position} / {total} recorded observation dates")
                st.html(f'<div class="uq-sidebar-context">{text(tr(counter_label, position=f"{position + 1:03}", total=f"{len(dates):03}"))}</div>')
                _period_navigation(dates)
        if selected_package is None and selected_date is not None and selected_date != model.decision_date:
            recorded_dates = tuple(day for day in model.available_dates if day <= selected_date)
            if recorded_dates:
                model = workspace_reader.scope_overview(workspace_reader.load_overview(recorded_dates[-1], source=source,
                            reference=workspace_reader.source_reference(model)), st.session_state["workspace_sample"])
        if selected_date:
            st.session_state[f"_source_date:{source}"] = selected_date
            st.session_state[f"_sample_date:{st.session_state['workspace_sample']}"] = selected_date
        if tour_launcher is not None and selected_package is None:
            with tour_launcher:
                render_tour_launcher(model)
        if (selected_package is None and st.session_state["workspace_sample"] == "test_2026"
                and view in ("Overview", "Portfolio", "History", "Research")):
            selected_package = comparison_package or selected_strategies_reader.load_package()
            st.session_state["_selected_strategy_binding_seen"] = selected_package["package_sha256"]
        sync_replay_context(view, model.decision_date)
        render_overview(model, presentation=presentation, view=view, selected_package=selected_package)
    except Exception as exc:
        st.title("US TECH QUANT")
        st.caption(tr("Research & Portfolio Decision Console · READ ONLY"))
        st.error(tr("Overview unavailable. The existing artifact could not be displayed safely."))
        st.info(tr("Turn Presentation Mode off to inspect technical details."))
        if not presentation:
            with st.expander(tr("Debug details"), expanded=False):
                st.exception(exc)


@st.fragment(run_every="20s")
def _refresh_published_data() -> None:
    """Rerun an open page when the verified DEMO pointer changes."""
    if (st.session_state.get("workspace_strategy") in selected_strategies_reader.STRATEGY_IDS
            or (st.session_state.get("workspace_sample") == "test_2026"
                and st.session_state.get("workspace") in ("Overview", "Portfolio", "History", "Research"))):
        previous_strategy = st.session_state.get("_selected_strategy_binding_seen")
        if previous_strategy:
            try:
                current_strategy = selected_strategies_reader.load_package()["package_sha256"]
            except (ValueError, KeyError, OSError, TypeError):
                current_strategy = "UNAVAILABLE"
            if current_strategy != previous_strategy:
                st.session_state["_selected_strategy_binding_seen"] = current_strategy
                st.rerun()
        if st.session_state.get("workspace_strategy") in selected_strategies_reader.STRATEGY_IDS:
            return
    previous = st.session_state.get("_workspace_binding_seen")
    if not previous or previous[0] != workspace_reader.LATEST:
        return
    try:
        current = updated_research_reader.binding()
    except (ValueError, KeyError, OSError, TypeError):
        return
    if current["sha256"] != previous[1]:
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="US Tech Quant | Research Terminal", page_icon=":material/monitoring:",
                       layout="wide", initial_sidebar_state="auto",
                       menu_items={"Get Help": None, "Report a bug": None, "About": None})
    pages = {}

    def research_page():
        _overview_page(pages)

    def paper_page():
        render_trading_workspace("paper", pages)

    def live_page():
        render_trading_workspace("live", pages)

    def strategies_page():
        render_selected_strategies(pages)

    pages.update({
        "research": st.Page(research_page, title="Overview", icon=":material/monitoring:", default=True),
        "strategies": st.Page(strategies_page, title="已应用策略", icon=":material/strategy:", url_path="strategies"),
        "paper": st.Page(paper_page, title="模拟盘", icon=":material/science:", url_path="paper-trading"),
        "live": st.Page(live_page, title="实盘", icon=":material/lock:", url_path="live-trading"),
    })
    st.navigation(list(pages.values()), position="hidden").run()


if __name__ == "__main__":
    main()
