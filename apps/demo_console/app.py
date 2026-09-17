"""Read-only Streamlit research terminal over the canonical overview adapter."""
import streamlit as st

from apps.demo_console.adapters.decision_reader import load_overview
from apps.demo_console.pages.overview import render_overview
from apps.demo_console.components.visuals import apply_style, sidebar_brand, brand_mark, text
from apps.demo_console.i18n import LANGUAGES, set_language, tr
from apps.demo_console.components.replay import pause_replay, sync_replay_context
from apps.demo_console.components.demo_tour import render_tour_launcher, workspace_options
from apps.demo_console.components.recorded_2026 import is_recorded_2026

_WORKSPACE_LABELS = {"Overview": "Overview", "Machine learning": "Machine learning",
                     "Portfolio": "Decisions & portfolio", "History": "Decisions & portfolio",
                     "Research": "Performance & risk", "Evidence": "Research evidence"}


def _refresh_localized_selections() -> None:
    # Streamlit keeps a selectbox's input label when its raw value is unchanged.
    # Reassigning the existing value tells it to send the new localized label.
    for key in ("workspace", "portfolio_workspace", "history_window", "record_set", "membership_filter", "research_range",
                "ml_section", "ml_history_window", "ml_history_metric", "ml_feature_family", "ml_feature_name",
                "research_drawdown_episode", "system_capability", "system_pit_case", "research_period",
                "recorded_2026_chart_mode", "recorded_2026_source", "recorded_2026_curve_focus", "research_curve_focus"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    pause_replay()


def _step_date(dates: tuple[str, ...], direction: int) -> None:
    pause_replay(reset=True)
    current = st.session_state.get("decision_date", dates[-1])
    index = dates.index(current) if current in dates else len(dates) - 1
    st.session_state["decision_date"] = dates[max(0, min(len(dates) - 1, index + direction))]


def _overview_page() -> None:
    apply_style(presentation=st.session_state.get("presentation_mode", True))
    with st.container(key="uq_utility_bar"):
        identity, date_picker, language_picker = st.columns([2.5, 1.3, 1], gap="small", vertical_alignment="center", wrap=False)
        # Render the language first even though its column is on the right, so
        # every subsequently rendered label uses the current language context.
        with language_picker:
            language = st.selectbox("Language / 语言 / 言語", list(LANGUAGES), index=2,
                                    key="language", format_func=LANGUAGES.get, bind="query-params",
                                    on_change=_refresh_localized_selections, label_visibility="collapsed")
        set_language(language)
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
        recorded_2026 = is_recorded_2026(view)
        tour_launcher = st.container() if view != "Overview" else None
        st.html(f'<div class="uq-sidebar-rule"></div><div class="uq-nav-label">{text(tr("2026 · RECORDED WINDOW" if recorded_2026 else "HISTORICAL SNAPSHOT"))}</div>')
        date_navigation = st.container(key="uq_sidebar_date_navigation")
        st.html('<div class="uq-sidebar-rule"></div>')
        with st.popover(tr("Display & motion"), width="stretch"):
            presentation = st.toggle(tr("Presentation Mode"), value=True, key="presentation_mode",
                                     help=tr("Larger text for presenting. Private source paths, full hashes and technical metadata stay hidden."))
            st.toggle(tr("Animated transitions"), value=True, key="motion_enabled")
            st.caption(tr("Motion respects your system's reduced-motion preference. Values always display their recorded result."))
        st.html(f'<div class="uq-sidebar-footer"><strong>{text(tr("RAW A2 / RESEARCH"))}</strong>'
                f'{text(tr("Frozen historical artifacts."))}<br>{text(tr("Read only. No execution."))}'
                f'<br><br>{text(tr("US equities · Top 20"))}<br>{text(tr("RX trace not exposed"))}</div>')

    try:
        # The reader validates the selected date and returns its verified
        # calendar. Avoid fully reading the latest snapshot before this one.
        model = load_overview(st.session_state.get("decision_date"))
        with date_controls:
            if model.available_dates:
                dates = model.available_dates
                if st.session_state.get("decision_date") not in dates:
                    st.session_state["decision_date"] = model.decision_date if model.decision_date in dates else dates[-1]
                if recorded_2026:
                    # Reassigning detaches this retained case date from widget cleanup.
                    st.session_state["decision_date"] = st.session_state["decision_date"]
                    selected_date = st.session_state["decision_date"]
                    st.caption(tr("2026 · Separate recorded window"))
                else:
                    # Re-send the retained value when this native widget returns
                    # after the separate recorded window hid it.
                    st.session_state["decision_date"] = st.session_state["decision_date"]
                    selected_date = st.selectbox(tr("Decision date"), options=dates, index=None,
                                             key="decision_date", help=tr("Existing pre-2026 snapshots. No strategy is rerun."),
                                             on_change=pause_replay, kwargs={"reset": True},
                                                 label_visibility="collapsed")
                position = dates.index(selected_date)
            else:
                selected_date = None
                st.info(tr("No displayable decision date is currently available."))
        with date_navigation:
            if selected_date is not None:
                back, forward = st.columns(2, gap="small")
                back.button(tr("← Prev"), on_click=_step_date, args=(dates, -1),
                            disabled=recorded_2026 or position == 0, width="stretch", key="previous_date")
                forward.button(tr("Next →"), on_click=_step_date, args=(dates, 1),
                               disabled=recorded_2026 or position == len(dates) - 1, width="stretch", key="next_date")
                if recorded_2026:
                    st.caption(tr("The case-date controls apply only to historical research."))
                else:
                    st.html(f'<div class="uq-sidebar-context">{text(tr("{position} / {total} recorded snapshots", position=f"{position + 1:03}", total=f"{len(dates):03}"))}</div>')
        if selected_date is not None and selected_date != model.decision_date:
            model = load_overview(selected_date)
        if tour_launcher is not None:
            with tour_launcher:
                render_tour_launcher(model)
        sync_replay_context(view, model.decision_date)
        render_overview(model, presentation=presentation, view=view)
    except Exception as exc:
        st.title("US TECH QUANT")
        st.caption(tr("Research & Portfolio Decision Console · READ ONLY"))
        st.error(tr("Overview unavailable. The existing artifact could not be displayed safely."))
        st.info(tr("Turn Presentation Mode off to inspect technical details."))
        if not presentation:
            with st.expander(tr("Debug details"), expanded=False):
                st.exception(exc)


def main() -> None:
    st.set_page_config(page_title="US Tech Quant | Research Terminal", page_icon=":material/monitoring:",
                       layout="wide", initial_sidebar_state="auto",
                       menu_items={"Get Help": None, "Report a bug": None, "About": None})
    st.navigation([st.Page(_overview_page, title="Overview", default=True)], position="hidden").run()


if __name__ == "__main__":
    main()
