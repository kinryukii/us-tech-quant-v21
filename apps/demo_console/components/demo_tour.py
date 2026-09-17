"""Six optional tour stops across five grouped research workspaces.

Tour callbacks configure display controls before their widgets are created.
They never choose a decision date, read artifacts, or start automatic replay.
"""
import streamlit as st

from apps.demo_console.components.replay import pause_replay
from apps.demo_console.components.decision_trace import carry_case, resolve_case_ticker
from apps.demo_console.i18n import tr
from apps.demo_console.models import DecisionOverview
from apps.demo_console.components.visuals import text


_ACTIVE = "_demo_tour_active"
_STEP = "_demo_tour_step"
_FOCUS = "_demo_tour_focus_pending"
_STOPS = (
    ("Overview", "How does this model record relate to holdings?",
     "Choose one recorded security. Follow its model output, execution date and subsequent portfolio membership; the return chart supplies portfolio context."),
    ("Machine learning", "What did the model record for this security?",
     "Keep the same security in focus. Inspect its original rank and score, then the recorded model lineage; a score is not a probability or a causal explanation."),
    ("Portfolio", "Was this security held after execution?",
     "Inspect the same ranked security and its subsequent holding status. Switch to historical holdings to inspect the portfolio; membership is not an RX decision trace."),
    ("History", "How did this security's recorded position change?",
     "Follow the same security through recorded ranks, scores and holdings. Missing observations remain gaps; Play advances recorded dates only."),
    ("Research", "How did the portfolio behave during setbacks?",
     "The case remains in view, while these returns, costs and drawdowns describe the whole portfolio. Inspect recovery or an unrecovered cutoff, then the same-study control."),
    ("Evidence", "Which records support this case?",
     "Check the case's decision and execution dates against source identities and stated checks. Artifact integrity does not establish independent predictive skill or live readiness."),
)
_VIEWS = tuple(stop[0] for stop in _STOPS)


def workspace_options(current, portfolio_view="Portfolio"):
    """Expose five sidebar positions while preserving both legacy group routes.

    Portfolio and History occupy the same position and display label. The raw
    option follows the active or last visited subsection, so existing callbacks
    can still write workspace='History' before the sidebar is rendered.
    """
    subsection = current if current in ("Portfolio", "History") else portfolio_view
    if subsection not in ("Portfolio", "History"):
        subsection = "Portfolio"
    return tuple(subsection if view == "Portfolio" else view for view in _VIEWS if view != "History")


def _history_focus(model: DecisionOverview) -> str | None:
    return resolve_case_ticker(model)


def start_guided_tour(ticker: str | None = None) -> None:
    """Start the reusable system-to-evidence route without changing the selected date."""
    pause_replay()
    carry_case(ticker)
    st.session_state[_ACTIVE] = True
    st.session_state[_STEP] = 0
    st.session_state[_FOCUS] = "copy"
    st.session_state["workspace"] = "Overview"


# Preserve existing internal callers while the overview uses the public entry.
_start_tour = start_guided_tour


def _stop_tour() -> None:
    pause_replay()
    st.session_state[_ACTIVE] = False
    st.session_state.pop(_STEP, None)
    st.session_state[_FOCUS] = "launcher"


def _visit_step(index: int, history_focus: str | None) -> None:
    view = _VIEWS[index]
    # A fresh History stop must not retain an old replay's locked sub-window.
    pause_replay(reset=view == "History")
    st.session_state[_STEP] = index
    st.session_state["workspace"] = view
    if view in ("Portfolio", "History"):
        st.session_state["portfolio_workspace"] = view
    if view in ("Machine learning", "Portfolio", "History"):
        carry_case(history_focus)
    if view == "Machine learning":
        st.session_state["ml_section"] = "Model engine"
    elif view == "Portfolio":
        st.session_state["ticker_search"] = ""
        st.session_state["record_set"] = "Raw A2 Top20"
        st.session_state["membership_filter"] = "All names"
    elif view == "History":
        st.session_state["history_window"] = "60 snapshots"
    elif view == "Research":
        st.session_state["research_period"] = "Historical research"
        st.session_state["research_range"] = "All days through selected execution"
        st.session_state["research_reference"] = True
        st.session_state["research_gross"] = False
        st.session_state["_localized_tabs:research_tabs"] = "Drawdown & recovery"


def _move_tour(direction: int, history_focus: str | None) -> None:
    if not st.session_state.get(_ACTIVE) or direction not in (-1, 1):
        return
    view = st.session_state.get("workspace")
    if view not in _VIEWS:
        return
    index = _VIEWS.index(view) + direction
    if index == len(_STOPS):
        _stop_tour()
    elif index >= 0:
        _visit_step(index, history_focus)


def _sync_step(view: str) -> int | None:
    """Manual navigation changes the explanation, never forces navigation back."""
    if not st.session_state.get(_ACTIVE) or view not in _VIEWS:
        return None
    index = _VIEWS.index(view)
    if st.session_state.get(_STEP) != index:
        pause_replay()
        st.session_state[_STEP] = index
    return index


def render_tour_launcher(model: DecisionOverview | None = None) -> None:
    """Place this compact optional entry in the sidebar or header controls."""
    if not st.session_state.get(_ACTIVE):
        st.button(tr("Start guided tour"), key="demo_tour_start", on_click=start_guided_tour,
                  args=(resolve_case_ticker(model) if model is not None else None,),
                  icon=":material/explore:", width="content",
                  help=tr("Follow one recorded case through model output, holdings, history and evidence. Risk and returns provide portfolio context; the selected date stays fixed."))


def _render_focus_request(target: str) -> None:
    """Consume a user-triggered handoff; ordinary reruns never move focus."""
    if st.session_state.get(_FOCUS) != target:
        return
    st.session_state.pop(_FOCUS)
    # All selectors are fixed application markup. No record, translated text,
    # or session value enters JavaScript. Allow the new DOM two paint frames.
    focus = 'document.querySelector("#uq-demo-tour-copy")?.focus({preventScroll: true});'
    if target == "launcher":
        focus = '''
const visible = node => {
  if (!node) return false;
  const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
  return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0
    && rect.left < window.innerWidth && rect.top < window.innerHeight
    && style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0;
};
const sidebar = document.querySelector('[data-testid="stSidebar"]');
const launcher = document.querySelector(".st-key-demo_tour_start button");
const overviewLauncher = document.querySelector(".st-key-system_start_tour button");
const destination = visible(overviewLauncher) ? overviewLauncher
  : sidebar?.getAttribute("aria-expanded") === "true" && visible(launcher)
    ? launcher : document.querySelector('[data-testid="stExpandSidebarButton"]');
if (visible(destination)) destination.focus({preventScroll: true});
else {
  const heading = document.querySelector(".uq-page-header h1");
  if (visible(heading)) {
    const previous = heading.getAttribute("tabindex");
    heading.setAttribute("tabindex", "-1");
    heading.focus({preventScroll: true});
    heading.addEventListener("blur", () => previous === null
      ? heading.removeAttribute("tabindex") : heading.setAttribute("tabindex", previous), {once: true});
  }
}
'''
    st.html('<script data-uq-tour-focus>requestAnimationFrame(() => requestAnimationFrame(() => {'
            + focus +
            '}));</script>', unsafe_allow_javascript=True)


def render_demo_tour(model: DecisionOverview, view: str) -> None:
    """Call after the page header and before page-specific widgets."""
    index = _sync_step(view)
    if index is None:
        _render_focus_request("launcher")
        return
    _, title, explanation = _STOPS[index]
    focus = _history_focus(model)
    with st.container(border=True, key="uq_demo_tour"):
        copy, controls = st.columns([3.4, 2.7], gap="medium", vertical_alignment="center")
        with copy:
            st.html('<div class="uq-tour-copy" id="uq-demo-tour-copy" tabindex="-1" '
                    'role="status" aria-live="polite" aria-atomic="true"><span>'
                    + text(tr("Guided tour · {step} / {total}", step=index + 1, total=len(_STOPS)))
                    + f'</span><strong>{text(tr(title))}</strong></div>')
        with controls, st.container(horizontal=True, gap="small", key="uq_tour_controls"):
            st.button(tr("Back"), key="demo_tour_previous", disabled=index == 0,
                      on_click=_move_tour, args=(-1, focus), width="stretch")
            st.button(tr("Finish" if index == len(_STOPS) - 1 else "Next"),
                      key="demo_tour_next", on_click=_move_tour, args=(1, focus),
                      type="primary", width="stretch")
            st.button(tr("Exit"), key="demo_tour_exit", on_click=_stop_tour,
                      width="stretch")
            with st.popover(tr("Notes"), width="stretch", help=tr("Walkthrough notes")):
                st.caption(tr(explanation))
    _render_focus_request("copy")
