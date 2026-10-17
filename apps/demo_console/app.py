"""Read-only Streamlit research terminal over the canonical overview adapter."""
import streamlit as st
from datetime import date

from apps.demo_console.components.visuals import apply_style, brand_mark, text
from apps.demo_console.i18n import LANGUAGES, set_language, tr
from apps.demo_console.components.replay import pause_replay, sync_replay_context
from apps.demo_console.components.trading_workspace import render_trading_workspace
from apps.demo_console.components.strategy_workbench import render_strategy_workbench, render_strategy_cases, render_method_picker

_WORKSPACE_LABELS = {"Overview": "Overview", "Machine learning": "Machine learning",
                     "Portfolio": "Decisions & portfolio", "History": "Decisions & portfolio",
                     "Research": "Performance & risk", "Evidence": "Data & charts"}


def __getattr__(name):
    """Keep reader aliases compatible without loading research on trading routes."""
    if name in ("workspace_reader", "updated_research_reader", "selected_strategies_reader", "new_strategy_replay_reader"):
        from importlib import import_module
        value = import_module("apps.demo_console.adapters." + name)
    elif name in ("WORKSPACE_STRATEGIES", "_STRATEGIES"):
        from apps.demo_console.components.strategy_workbench import WORKSPACE_STRATEGIES
        value = WORKSPACE_STRATEGIES
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


def render_overview(*args, **kwargs):
    from apps.demo_console.pages.overview import render_overview as render
    return render(*args, **kwargs)


def render_selected_strategies(*args, **kwargs):
    from apps.demo_console.pages.selected_strategies import render_selected_strategies as render
    return render(*args, **kwargs)


def _refresh_localized_selections() -> None:
    # Streamlit keeps a selectbox's input label when its raw value is unchanged.
    # Reassigning the existing value tells it to send the new localized label.
    for key in ("workspace", "workspace_strategy", "workspace_sample", "portfolio_workspace", "history_window", "record_set", "membership_filter", "research_range",
                "ml_section", "ml_history_window", "ml_history_metric", "ml_feature_family", "ml_feature_name",
                "research_drawdown_episode", "system_capability", "system_pit_case", "research_period",
                "recorded_2026_chart_mode", "recorded_2026_source", "recorded_2026_curve_focus", "research_curve_focus", "applied_benchmark"):
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


def _select_recorded_date(dates: tuple[str, ...], selected: str) -> None:
    if selected not in dates:
        return
    pause_replay(reset=True)
    st.session_state["decision_date"] = selected


def _step_date(dates: tuple[str, ...], direction: int) -> None:
    current = st.session_state.get("decision_date", dates[-1])
    index = dates.index(current) if current in dates else len(dates) - 1
    _select_recorded_date(dates, dates[max(0, min(len(dates) - 1, index + direction))])


def _restore_workspace_context() -> None:
    """Migrate saved research selections before shared widgets are created."""
    context = st.session_state.pop("_applied_workspace_context", None)
    if context:
        st.session_state.update(context)
    # Retire the previous version switch, including its persisted browser value.
    # A frozen-view date must not silently become the same day's recalculated case.
    previous = st.session_state.pop("workspace_source", None)
    if previous is not None:
        from apps.demo_console.adapters import workspace_reader
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


def _overview_page(pages=None, *, view=None, shell=None) -> None:
    if shell is None:
        _restore_workspace_context()
    _render_historical_workspace(pages, view=view, shell=shell)


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
    from apps.demo_console.adapters import workspace_reader
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


def _render_date_context(shell, dates, *, preferred=None, recorded_kind="observations"):
    """One research-date widget; account clocks remain owned by the component."""
    shell["date_rendered"] = True
    dates = tuple(dates)
    with shell["date_controls"]:
        if not dates:
            st.caption("—")
            st.info(tr("No displayable decision date is currently available."))
            return None
        current = st.session_state.get("decision_date")
        canonical = current if current in dates else preferred if preferred in dates else dates[-1]
        # Reassert the verified value so a first native-page render receives an
        # explicit wire value; this timeline cannot be cleared to an empty date.
        st.session_state["decision_date"] = canonical
        selected = st.selectbox(tr("Research observation date"), dates, index=dates.index(canonical),
            key="decision_date", label_visibility="collapsed", persist_state="session",
            help=tr("One signal timeline across history and the latest verified results. Browsing does not recalculate."),
            on_change=pause_replay, kwargs={"reset": True})
    position = dates.index(selected)
    with shell["date_navigation"]:
        back, forward = st.columns(2, gap="small")
        back.button(tr("← Prev"), on_click=_step_date, args=(dates, -1),
                    disabled=position == 0, width="stretch", key="previous_date")
        forward.button(tr("Next →"), on_click=_step_date, args=(dates, 1),
                       disabled=position == len(dates) - 1, width="stretch", key="next_date")
        counter = ("{position} / {total} recorded snapshots" if recorded_kind == "snapshots"
                   else "{position} / {total} recorded observation dates")
        st.caption(tr(counter, position=f"{position + 1:03}", total=f"{len(dates):03}"))
        _period_navigation(dates)
    return selected


def _render_saved_date_context(shell, *, mechanism=False):
    """Execution can render even before any research package is available."""
    if shell.get("execution"):
        shell["date_rendered"] = True
        return None
    sample = st.session_state.get("workspace_sample", "test_2026")
    dates = st.session_state.get("_workbench_dates:" + sample, ())
    current = st.session_state.get("decision_date")
    if dates and (current is None or current in dates):
        return _render_date_context(shell, dates, preferred=current)
    shell["date_rendered"] = True
    with shell["date_controls"]:
        st.caption(current or (tr("Mechanism overview · No model execution") if mechanism else "—"))
    with shell["date_navigation"]:
        st.caption(tr("Research dates appear after verified records are opened. Account snapshots keep their own time."))
    return current


def _render_shared_shell(pages, page_title=None, *, execution=False, overview=False):
    """One light exhibition shell; observation controls belong to record views."""
    from apps.demo_console.components.strategy_workbench import WORKSPACE_STRATEGIES
    if st.session_state.get("workspace_strategy") not in WORKSPACE_STRATEGIES:
        st.session_state["workspace_strategy"] = "RAW_A2"
    from apps.demo_console.components.demo_tour import start_showcase_tour, showcase_tour_active
    apply_style(presentation=st.session_state.get("presentation_mode", True))
    with st.container(key="uq_gallery_header", horizontal=True, wrap=True,
                      horizontal_alignment="distribute", vertical_alignment="center", gap="medium"):
        st.html('<div class="uq-gallery-identity">' + brand_mark()
                + '<div><strong>US TECH QUANT</strong><span>'
                + text(tr("A system, explained.")) + '</span></div></div>', width="content")
        if not execution and not showcase_tour_active():
            st.button(tr("Start system walkthrough"), key="showcase_tour_start",
                      on_click=start_showcase_tour, icon=":material/play_circle:",
                      type="primary", width="content")
        with st.container(key="uq_gallery_utilities", horizontal=True, wrap=True,
                          vertical_alignment="bottom", gap="small", width="content"):
            st.selectbox("语言 / Language", list(LANGUAGES), key="language",
                format_func=LANGUAGES.get, persist_state="session",
                on_change=_refresh_localized_selections, width=110, label_visibility="collapsed")
            with st.popover(tr("Display"), icon=":material/tune:", width="content"):
                st.toggle(tr("Presentation Mode"), value=True, key="presentation_mode", persist_state="session",
                    help=tr("Larger text for presenting. Private source paths, full hashes and technical metadata stay hidden."))
                st.toggle(tr("Animated transitions"), value=True, key="motion_enabled", persist_state="session")
                st.caption(tr("Motion respects your system's reduced-motion preference. Values always display their recorded result."))
            with st.popover(tr("Data updates"), icon=":material/refresh:", width="content"):
                st.write(tr("Research data is updated manually each afternoon. Browsing uses published records and caches."))
                st.code('& "D:\\us-tech-quant\\更新今日推荐.ps1"', language="powershell")
                st.caption(tr("After the manual update finishes, reload the published cache here."))
                refresh_controls = st.container(key="uq_workbench_updates")
    return {"refresh_controls": refresh_controls, "date_rendered": False, "execution": execution}


def _render_record_controls(shell, *, include_strategy=True):
    """Reuse research selection and date handling only inside an opened record view."""
    from apps.demo_console.components.strategy_workbench import WORKSPACE_STRATEGIES
    with st.container(key="uq_record_context", border=True):
        if include_strategy:
            sample, focus, observation = st.columns([1, 1.2, 1], gap="medium")
        else:
            sample, observation = st.columns([1, 1.2], gap="medium")
        labels = {"historical": tr("Historical training / validation"), "test_2026": tr("2026 test sample")}
        with sample:
            st.selectbox(tr("Sample"), tuple(labels), key="workspace_sample",
                format_func=labels.__getitem__, on_change=_change_sample, persist_state="session",
                help=tr("Historical results include annual out-of-fold validation. The frozen model's 2026 observations are displayed separately and are not used for training or tuning."))
        st.session_state["_workspace_sample_seen"] = st.session_state["workspace_sample"]
        if include_strategy:
            with focus:
                st.selectbox(tr("Strategy details"), tuple(WORKSPACE_STRATEGIES), key="workspace_strategy",
                    format_func=lambda sid: tr(WORKSPACE_STRATEGIES[sid]), on_change=_change_strategy, persist_state="session")
        with observation:
            st.caption(tr("Research observation date"))
            shell["date_controls"] = st.container()
        with st.expander(tr("Browse recorded dates"), expanded=False):
            shell["date_navigation"] = st.container()
    shell["date_rendered"] = False
    shell["execution"] = False


GALLERY_SECTIONS = ("Technical showcase", "Strategy applications", "Data & charts", "Daily simulation")


_APPLICATION_TOOLS = ("How this method works", "Machine learning", "Decisions & portfolio")
_RECORD_ROUTES = {
    "Overview": ("Technical showcase", None),
    "Machine learning": ("Strategy applications", "Machine learning"),
    "Portfolio": ("Strategy applications", "Decisions & portfolio"),
    "History": ("Strategy applications", "Decisions & portfolio"),
    "Research": ("Data & charts", "Performance & risk"),
    "Evidence": ("Data & charts", "Data sources"),
    "Execution": ("Daily simulation", None),
}


def navigate_workspace(view: str, *, strategy_id: str | None = None) -> None:
    """Navigate the existing workspace without selecting dates or reading records."""
    if view not in _RECORD_ROUTES:
        raise ValueError("Unknown workspace view")
    if strategy_id is not None:
        from apps.demo_console.components.strategy_workbench import WORKSPACE_STRATEGIES
        if strategy_id not in WORKSPACE_STRATEGIES:
            raise ValueError("Unknown workspace strategy")
        if st.session_state.get("workspace_strategy") != strategy_id:
            st.session_state["workspace_strategy"] = strategy_id
            _change_strategy()
    pause_replay()
    section, tool = _RECORD_ROUTES[view]
    # Preserve the original case-tour overview as a record view, rather than
    # sending that explicit historical action to the data-free technical exhibit.
    if view == "Overview" and st.session_state.get("_demo_tour_profile") == "historical":
        section, tool = "Strategy applications", "Decisions & portfolio"
    st.session_state["workspace"] = view
    st.session_state["_gallery_workspace_seen"] = view
    st.session_state["_localized_tabs:technical_gallery"] = section
    if section == "Strategy applications":
        st.session_state["_localized_tabs:strategy_application_tools"] = tool
        if view in ("Portfolio", "History"):
            st.session_state["portfolio_workspace"] = view
        if tool == "Decisions & portfolio":
            st.session_state["gallery_recorded_decisions"] = True
    elif section == "Data & charts":
        st.session_state["_localized_tabs:workbench_evidence_tools"] = tool


def _consume_workspace_navigation() -> None:
    """Adapt legacy callbacks that still write the original workspace key."""
    view = st.session_state.get("workspace")
    if view in _RECORD_ROUTES and view != st.session_state.get("_gallery_workspace_seen"):
        navigate_workspace(view)


def _remember_workspace_view(view: str) -> None:
    """Record the displayed route so a later legacy callback is distinguishable."""
    if st.session_state.get("workspace") != view:
        pause_replay()
    st.session_state["workspace"] = view
    st.session_state["_gallery_workspace_seen"] = view


def _show_gallery_section(source, pages):
    """Compatibility routes only select the unified workspace; they read no data."""
    if source not in GALLERY_SECTIONS:
        raise ValueError("Unknown gallery section")
    st.session_state["_localized_tabs:technical_gallery"] = source
    st.session_state["_gallery_workspace_seen"] = st.session_state.get("workspace")
    st.switch_page(pages["research"])


def _render_gallery(pages, shell):
    from apps.demo_console.components.localized_tabs import localized_tabs
    from apps.demo_console.components.demo_tour import render_showcase_tour
    _consume_workspace_navigation()
    with st.container(key="uq_gallery_workspace"):
        render_showcase_tour()
        technology, cases, charts, simulation = localized_tabs(GALLERY_SECTIONS, key="technical_gallery")
        if technology.open:
            _remember_workspace_view("Overview")
            with technology:
                render_strategy_workbench(pages, st.session_state.get("presentation_mode", True))
        elif cases.open:
            with cases:
                presentation = st.session_state.get("presentation_mode", True)
                tool_key = "_localized_tabs:strategy_application_tools"
                if st.session_state.get(tool_key) not in _APPLICATION_TOOLS:
                    st.session_state[tool_key] = _APPLICATION_TOOLS[0] if presentation else "Machine learning"
                from apps.demo_console.adapters import applied_account_reader as accounts
                try:
                    ids = tuple(accounts.showcase_projection()["showcase_ids"])
                except (OSError, ValueError, KeyError, TypeError):
                    st.warning(tr("The accepted showcase roster is unavailable. You can still inspect a method; browsing does not change the roster."))
                    ids = (st.session_state["workspace_strategy"],)
                with st.container(key="uq_method_picker"):
                    render_method_picker(strategy_ids=ids)
                principles, models, decisions = localized_tabs(_APPLICATION_TOOLS, key="strategy_application_tools")
                if principles.open:
                    _remember_workspace_view("Strategy applications")
                    with principles:
                        st.html('<header class="uq-gallery-section"><span>02 / APPLICATIONS</span><h1>'
                            + text(tr("Five methods. A shared engineering foundation.")) + '</h1><p>'
                            + text(tr("Explore how different models use the same data, risk and execution infrastructure. Choose a method to see what it produces."))
                            + '</p></header>')
                        render_strategy_cases(pages, presentation, strategy_ids=ids, show_picker=False)
                elif models.open:
                    _remember_workspace_view("Machine learning")
                    with models:
                        st.html('<div class="uq-gallery-breadcrumb">02 / '
                            + text(tr("Strategy applications")) + '</div>')
                        _render_record_controls(shell, include_strategy=False)
                        _overview_page(pages, view="Machine learning", shell=shell)
                elif decisions.open:
                    view = st.session_state.get("portfolio_workspace", "Portfolio")
                    if view not in ("Portfolio", "History"):
                        view = "Portfolio"
                    if (st.session_state.get("_demo_tour_profile") == "historical"
                            and st.session_state.get("workspace") == "Overview"):
                        view = "Overview"
                    _remember_workspace_view(view)
                    with decisions:
                        st.html('<div class="uq-gallery-breadcrumb">02 / '
                            + text(tr("Strategy applications")) + '</div>')
                        if presentation:
                            with st.expander(tr("Explore recorded decisions"), expanded=False,
                                    key="gallery_recorded_decisions", on_change="rerun") as records:
                                if records.open:
                                    _render_record_controls(shell, include_strategy=False)
                                    _overview_page(pages, view=view, shell=shell)
                        else:
                            _render_record_controls(shell, include_strategy=False)
                            _overview_page(pages, view=view, shell=shell)
        elif charts.open:
            with charts:
                st.html('<div class="uq-gallery-breadcrumb">03 / '
                    + text(tr("Data & charts")) + '</div>')
                performance, models, sources = localized_tabs(
                    ("Performance & risk", "Machine learning", "Data sources"), key="workbench_evidence_tools")
                if models.open:
                    # Consume the alias once; revisiting charts retains its last
                    # real evidence view instead of immediately redirecting again.
                    st.session_state["_localized_tabs:workbench_evidence_tools"] = (
                        "Data sources" if st.session_state.get("workspace") == "Evidence" else "Performance & risk")
                    navigate_workspace("Machine learning")
                    st.rerun()
                else:
                    view = "Research" if performance.open else "Evidence"
                    _remember_workspace_view(view)
                    _render_record_controls(shell)
                    with performance if performance.open else sources:
                        _overview_page(pages, view=view, shell=shell)
        elif simulation.open:
            _remember_workspace_view("Daily simulation")
            with simulation:
                st.html('<header class="uq-gallery-section uq-gallery-operation"><span>04 / EXECUTION</span><h1>'
                    + text(tr("From plan to confirmed fills.")) + '</h1></header>')
                render_trading_workspace("paper", pages)



def _render_historical_workspace(pages=None, *, view=None, shell=None) -> None:
    from apps.demo_console.adapters import workspace_reader, selected_strategies_reader
    from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES as _STRATEGIES
    source = workspace_reader.LATEST
    view = view or st.session_state.get("workspace", "Overview")
    st.session_state["workspace"] = view
    shell = shell if shell is not None else _render_shared_shell(pages)
    if "date_controls" not in shell:
        _render_record_controls(shell)
    presentation = st.session_state.get("presentation_mode", True)
    try:
        # The reader validates the selected date and returns its verified
        # calendar. Avoid fully reading the latest snapshot before this one.
        with st.spinner(tr("Loading verified records…"), show_time=True):
            selected_package = None
            comparison_package = None
            selected_strategy = st.session_state["workspace_strategy"]
            light_ml = view == "Machine learning" and selected_strategy != "RAW_A2"
            if light_ml:
                sample = st.session_state["workspace_sample"]
                ml_account_state = None
                ml_package_dates = None
                selected_package = {}
                if sample == "test_2026":
                    if selected_strategy in selected_strategies_reader.STRATEGY_IDS:
                        selected_package = selected_strategies_reader.load_package(include_performance=False)
                        ml_binding = selected_package["package_sha256"]
                    else:
                        calendar = selected_strategies_reader.load_workspace_calendar()
                        ml_package_dates = calendar["available_dates"]
                        ml_binding = calendar["package_sha256"]
                    st.session_state["_selected_strategy_binding_seen"] = ml_binding
                    from apps.demo_console.adapters import applied_account_reader as accounts
                    ml_account_state = accounts.load_state()
                strategy_dates = workspace_reader.ml_observation_dates(selected_package, sample=sample,
                    account_state=ml_account_state, package_dates=ml_package_dates)
                model = workspace_reader.load_ml_overview(selected_strategy, st.session_state.get("decision_date"),
                    sample=sample, observation_dates=strategy_dates)
            elif selected_strategy in selected_strategies_reader.STRATEGY_IDS:
                selected_package = selected_strategies_reader.load_package()
                st.session_state["_selected_strategy_binding_seen"] = selected_package.get("display_binding_sha256", selected_package["package_sha256"])
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
        dates = tuple(strategy_dates)
        st.session_state["_workbench_dates:" + st.session_state["workspace_sample"]] = dates
        preserve_ml_query = light_ml and (not dates or (
            st.session_state.get("decision_date") is not None and st.session_state["decision_date"] not in dates))
        selected_date = (_render_saved_date_context(shell, mechanism=True) if preserve_ml_query else
            _render_date_context(shell, dates, preferred=model.decision_date,
                recorded_kind="snapshots" if selected_package is None else "observations"))
        if preserve_ml_query and dates:
            with shell["date_controls"]:
                st.button(tr("Latest recorded observation"), key="ml_latest_recorded_observation",
                    on_click=_select_recorded_date, args=(dates, dates[-1]), width="stretch")
        if selected_package is None and selected_date is not None and selected_date != model.decision_date:
            recorded_dates = tuple(day for day in model.available_dates if day <= selected_date)
            if recorded_dates:
                model = workspace_reader.scope_overview(workspace_reader.load_overview(recorded_dates[-1], source=source,
                            reference=workspace_reader.source_reference(model)), st.session_state["workspace_sample"])
        if selected_date:
            st.session_state[f"_source_date:{source}"] = selected_date
            st.session_state[f"_sample_date:{st.session_state['workspace_sample']}"] = selected_date
        if (selected_package is None and st.session_state["workspace_sample"] == "test_2026"
                and (view in ("Overview", "Portfolio", "History", "Research")
                     or selected_strategy in tuple(_STRATEGIES)[2:])):
            selected_package = comparison_package or selected_strategies_reader.load_package()
            st.session_state["_selected_strategy_binding_seen"] = selected_package.get("display_binding_sha256", selected_package["package_sha256"])
        sync_replay_context(view, model.decision_date)
        if light_ml:
            from apps.demo_console.pages.selected_strategies import render_workspace
            render_workspace(model, selected_package, presentation=presentation, view=view,
                account_state=ml_account_state)
        else:
            render_overview(model, presentation=presentation, view=view, selected_package=selected_package)
    except Exception as exc:
        if not shell.get("date_rendered"):
            _render_saved_date_context(shell)
        st.caption(tr("Research & Portfolio Decision Console · READ ONLY"))
        st.error(tr("Overview unavailable. The existing artifact could not be displayed safely."))
        st.info(tr("Turn Presentation Mode off to inspect technical details."))
        if not presentation:
            with st.expander(tr("Debug details"), expanded=False):
                st.exception(exc)


def _refresh_published_data(target=None) -> None:
    """Reload published artifacts only after an explicit cache-control click."""
    target = st.sidebar if target is None else target
    notice = st.session_state.pop("_published_cache_notice", None)
    notice_level = st.session_state.pop("_published_cache_notice_level", "info")
    if notice:
        feedback = target.error if notice_level == "error" else target.info
        feedback(tr(notice))
    if not target.button(tr("Reload published cache"), icon=":material/refresh:",
                             key="reload_published_cache", width="stretch"):
        return
    from apps.demo_console.adapters import workspace_reader, updated_research_reader, selected_strategies_reader, new_strategy_replay_reader
    light_ml = (st.session_state.get("workspace") == "Machine learning"
        and st.session_state.get("workspace_strategy") != "RAW_A2")
    if light_ml and st.session_state.get("workspace_sample") != "test_2026":
        target.info(tr("Machine learning records require a verified historical snapshot."))
        return
    if st.session_state.get("workspace_sample") == "test_2026":
        try:
            current_extension = new_strategy_replay_reader.publication_observation_sha256()
        except (ValueError, KeyError, OSError, TypeError):
            target.error(tr("Published cache could not be verified. The existing display is retained."))
            return
        previous_extension = st.session_state.get("_new_strategy_extension_binding_seen")
        st.session_state["_new_strategy_extension_binding_seen"] = current_extension
        if previous_extension is not None and current_extension != previous_extension:
            st.session_state["_published_cache_notice"] = "Published cache changed; displayed records retain their original verification checks."
            st.rerun()  # The existing reader rechecks all three qualifications.
    if (light_ml or st.session_state.get("workspace_strategy") in selected_strategies_reader.STRATEGY_IDS
            or (st.session_state.get("workspace_sample") == "test_2026"
                and st.session_state.get("workspace") in ("Overview", "Portfolio", "History", "Research"))):
        previous_strategy = st.session_state.get("_selected_strategy_binding_seen")
        if previous_strategy:
            source_error = False
            try:
                current_strategy = (selected_strategies_reader.package_observation_sha256(include_performance=False)
                    if light_ml else selected_strategies_reader.package_observation_sha256())
            except (ValueError, KeyError, OSError, TypeError):
                current_strategy = "UNAVAILABLE"
                source_error = True
            if current_strategy != previous_strategy:
                st.session_state["_selected_strategy_binding_seen"] = current_strategy
                st.session_state["_published_cache_notice"] = (
                    "A published source is unavailable. Records must pass their original verification checks before use."
                    if source_error else
                    "Published cache changed; displayed records retain their original verification checks.")
                st.session_state["_published_cache_notice_level"] = "error" if source_error else "info"
                st.rerun()
            if source_error:
                target.error(tr("A published source is unavailable. Records must pass their original verification checks before use."))
                return
        if light_ml or st.session_state.get("workspace_strategy") in selected_strategies_reader.STRATEGY_IDS:
            target.info(tr("Published cache checked. No changed source binding was detected."))
            return
    previous = st.session_state.get("_workspace_binding_seen")
    if not previous or previous[0] != workspace_reader.LATEST:
        target.info(tr("Published cache checked. No changed source binding was detected."))
        return
    try:
        current = updated_research_reader.binding()
    except (ValueError, KeyError, OSError, TypeError):
        target.error(tr("Published cache could not be verified. The existing display is retained."))
        return
    if current["sha256"] != previous[1]:
        st.session_state["_published_cache_notice"] = "Published cache changed; displayed records retain their original verification checks."
        st.rerun()
    target.info(tr("Published cache checked. No changed source binding was detected."))


def main() -> None:
    st.set_page_config(page_title="US Tech Quant | Technical showcase", page_icon=":material/hub:",
        layout="wide", initial_sidebar_state="collapsed",
        menu_items={"Get Help": None, "Report a bug": None, "About": None})
    if st.session_state.get("language") not in LANGUAGES:
        requested = st.query_params.get("language", "en")
        st.session_state["language"] = next(
            (code for code, label in LANGUAGES.items() if requested in (code, label)), "en")
    set_language(st.session_state["language"])
    pages, shell = {}, {}

    def research_page():
        _render_gallery(pages, shell)

    def strategies_page():
        if st.session_state.get("workspace") == "History":
            st.session_state["_localized_tabs:applied_workspace_tools"] = "Stock history across strategies"
        navigate_workspace("History" if st.session_state.get("workspace") == "History" else "Portfolio")
        st.switch_page(pages["research"])

    def paper_page():
        _show_gallery_section("Daily simulation", pages)

    def evidence_page():
        _show_gallery_section("Data & charts", pages)

    def live_page():
        if st.button(tr("Back to the showcase"), icon=":material/arrow_back:", key="workbench_home"):
            _show_gallery_section("Technical showcase", pages)
        render_trading_workspace("live", pages)

    pages.update({
        "research": st.Page(research_page, title=tr("Technical showcase"), icon=":material/hub:", default=True),
        "strategies": st.Page(strategies_page, title=tr("Strategy applications"),
            icon=":material/strategy:", url_path="strategies"),
        "paper": st.Page(paper_page, title=tr("Daily simulation"),
            icon=":material/science:", url_path="paper-trading"),
        "evidence": st.Page(evidence_page, title=tr("Data & charts"),
            icon=":material/fact_check:", url_path="evidence"),
        "live": st.Page(live_page, title=tr("Live trading"), icon=":material/lock:", url_path="live-trading"),
    })
    page = st.navigation(list(pages.values()), position="hidden")
    _restore_workspace_context()
    # Resolve old URLs before rendering the shell or reading any record.
    if page.url_path in ("strategies", "paper-trading", "evidence"):
        page.run()
        return
    shell.update(_render_shared_shell(pages, page_title=page.title,
        execution=page.url_path == "live-trading", overview=page.url_path == ""))
    page.run()
    _refresh_published_data(target=shell["refresh_controls"])


if __name__ == "__main__":
    main()
