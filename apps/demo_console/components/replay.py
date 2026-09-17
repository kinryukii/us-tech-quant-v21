"""User-started, bounded replay of existing decision dates.

Only date metadata is retained in Session State. Every displayed frame is read
and verified by the existing history reader; no economic observations are cached.
The CCv2 trigger callback runs before the full app, so the sidebar, page header
and history charts all receive the same decision date.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from uuid import uuid4

import streamlit as st

from apps.demo_console.i18n import tr
from apps.demo_console.components.visuals import text


_STATE_KEY = "_history_replay"
_TOKEN_KEY = "_history_replay_tick_token"
_TIMER_KEY = "history_replay_timer"


@dataclass(frozen=True)
class ReplayState:
    dates: tuple[str, ...]
    window_label: str
    index: int = 0
    status: str = "playing"

    @property
    def current_date(self) -> str:
        return self.dates[self.index]


def replay_range(available_dates: Sequence[str], end_date: str,
                 window: int | None) -> tuple[str, ...]:
    """Select recorded dates only, ending at the user's selected snapshot."""
    dates = tuple(date for date in available_dates if date <= end_date)
    if window is not None:
        if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
            raise ValueError("Replay window must be a positive integer or None")
        dates = dates[-window:]
    return dates


def _state() -> ReplayState | None:
    state = st.session_state.get(_STATE_KEY)
    return state if isinstance(state, ReplayState) else None


def pause_replay(*, reset: bool = False) -> None:
    """App callback: pause on navigation; reset=True for manual date changes.

    Reset discards the old range, allowing Play to use the new selected date and
    window. A plain pause retains the current frame and its range for Resume.
    """
    state = _state()
    st.session_state[_TOKEN_KEY] = None
    if reset:
        st.session_state.pop(_STATE_KEY, None)
    elif state is not None and state.status == "playing":
        st.session_state[_STATE_KEY] = replace(state, status="paused")


def reset_replay() -> None:
    """Widget callback for a manually changed history window/date."""
    pause_replay(reset=True)


def sync_replay_context(view: str, decision_date: str) -> None:
    """Call before the app renders; also guards callers without callbacks."""
    state = _state()
    if state is None:
        return
    if decision_date != state.current_date:
        pause_replay(reset=True)
    elif view != "History":
        pause_replay()


def restore_replay_window() -> None:
    """Keep a paused range's window after Streamlit removes off-page widgets."""
    state = _state()
    if state is not None and "history_window" not in st.session_state:
        st.session_state["history_window"] = state.window_label


def _set_frame(state: ReplayState) -> None:
    st.session_state[_STATE_KEY] = state
    st.session_state[_TOKEN_KEY] = None
    st.session_state["decision_date"] = state.current_date
    st.session_state["replay_date"] = state.current_date


def _start_replay(available_dates: Sequence[str], end_date: str,
                  window_label: str, window: int | None) -> None:
    dates = replay_range(available_dates, end_date, window)
    if len(dates) >= 2:
        _set_frame(ReplayState(dates, window_label))


def _resume_replay() -> None:
    state = _state()
    if state is not None and state.status == "paused":
        _set_frame(replace(state, status="playing"))


def _restart_replay() -> None:
    state = _state()
    if state is not None:
        _set_frame(replace(state, index=0, status="playing"))


def visible_replay_dates(decision_date: str, window_label: str) -> tuple[str, ...] | None:
    """The locked start through the current frame, including while paused."""
    state = _state()
    if state is None:
        return None
    if state.current_date != decision_date or state.window_label != window_label:
        reset_replay()
        return None
    return state.dates[:state.index + 1]


def accept_tick(payload: object) -> bool:
    """Advance once only when a trigger still belongs to the displayed frame."""
    state = _state()
    if state is None or state.status != "playing" or not isinstance(payload, Mapping):
        return False
    if (st.session_state.get("workspace") != "History"
            or st.session_state.get("decision_date") != state.current_date
            or st.session_state.get("history_window") != state.window_label):
        # A navigation/date/window event can race the browser timer. It wins.
        pause_replay(reset=st.session_state.get("decision_date") != state.current_date
                     or st.session_state.get("history_window") != state.window_label)
        return False
    token = st.session_state.get(_TOKEN_KEY)
    if not token or payload.get("token") != token or payload.get("date") != state.current_date:
        return False
    st.session_state[_TOKEN_KEY] = None
    if state.index + 1 >= len(state.dates):
        st.session_state[_STATE_KEY] = replace(state, status="complete")
        return False
    next_index = state.index + 1
    status = "complete" if next_index == len(state.dates) - 1 else "playing"
    _set_frame(replace(state, index=next_index, status=status))
    return True


def _on_tick_change() -> None:
    component = st.session_state.get(_TIMER_KEY)
    payload = component.get("tick") if isinstance(component, Mapping) else getattr(component, "tick", None)
    accept_tick(payload)


# Fixed local code; dates/tokens travel as CCv2 data, never executable HTML/JS.
# A render replaces the previous timer even if only the language/focus changed.
# Cleanup also handles unmounts; Python independently rejects stale deliveries.
_TIMER_JS = """
const timers = new WeakMap();
export default function (component) {
  const {data, parentElement, setTriggerValue} = component;
  const previous = timers.get(parentElement);
  if (previous) previous();
  let timer = null;
  let cancelled = false;
  const cleanup = () => {
    cancelled = true;
    if (timer !== null) clearTimeout(timer);
    if (timers.get(parentElement) === cleanup) timers.delete(parentElement);
  };
  timers.set(parentElement, cleanup);
  if (data?.playing === true && typeof data.token === "string"
      && typeof data.date === "string") {
    timer = setTimeout(() => {
      if (!cancelled) {
        timer = null;
        setTriggerValue("tick", {token: data.token, date: data.date});
      }
    }, 3000);
  }
  return cleanup;
}
"""

def render_replay_controls(available_dates: Sequence[str], decision_date: str,
                           window_label: str, window: int | None) -> None:
    """Native, keyboard-accessible controls; playback never starts by itself."""
    visible_replay_dates(decision_date, window_label)
    state = _state()
    count = len(replay_range(available_dates, decision_date, window))
    with st.container(key="uq_replay_controls"):
        play_col, pause_col, status_col = st.columns([1.3, 1.3, 3.4], gap="small")
        with play_col:
            if state is not None and state.status == "paused":
                st.button(tr("Resume replay"), key="history_replay_play", on_click=_resume_replay,
                          icon=":material/play_arrow:", width="stretch", type="primary")
            elif state is not None and state.status == "complete":
                st.button(tr("Replay again"), key="history_replay_play", on_click=_restart_replay,
                          icon=":material/replay:", width="stretch", type="primary")
            else:
                st.button(tr("Play replay"), key="history_replay_play", on_click=_start_replay,
                          args=(tuple(available_dates), decision_date, window_label, window),
                          disabled=count < 2 or state is not None,
                          icon=":material/play_arrow:", width="stretch", type="primary")
        with pause_col:
            st.button(tr("Pause replay"), key="history_replay_pause", on_click=pause_replay,
                      disabled=state is None or state.status != "playing",
                      icon=":material/pause:", width="stretch")
        with status_col:
            if state is None:
                st.caption(tr("Play the selected window from its first snapshot · 3 seconds per frame"))
                if count < 2:
                    st.caption(tr("At least two recorded snapshots are needed for automatic replay."))
            else:
                status = tr({"playing": "Playing", "paused": "Paused", "complete": "Replay complete"}[state.status])
                st.caption(tr("{status} · Frame {frame} / {total} · Locked range {start} → {end}",
                              status=status, frame=state.index + 1, total=len(state.dates),
                              start=state.dates[0], end=state.dates[-1]))
                progress = (state.index + 1) / len(state.dates) * 100
                st.html(f'<div class="uq-replay-progress" role="progressbar" '
                        f'aria-label="{text(tr("Recorded replay progress"))}" aria-valuemin="1" '
                        f'aria-valuemax="{len(state.dates)}" aria-valuenow="{state.index + 1}">'
                        f'<span style="width:{progress:.3f}%"></span></div>')
                st.caption(tr("Recorded snapshots only · Charts stop at the current frame"))


def render_replay_timer() -> None:
    """Mount after a successful history render; stopped sessions have no timer."""
    state = _state()
    playing = state is not None and state.status == "playing"
    token = uuid4().hex if playing else None
    st.session_state[_TOKEN_KEY] = token
    # 1.63's public component() registration is idempotent for an identical
    # definition. Register in the current render so a module first imported in
    # bare mode (or a previous AppTest runtime) never retains a stale registry.
    # The fixed name/source and mount key preserve frontend component identity.
    timer = st.components.v2.component(
        "uq_recorded_history_replay_timer",
        html="\n<span aria-hidden=\"true\"></span>\n", js=_TIMER_JS,
    )
    timer(key=_TIMER_KEY, height=0, width="stretch",
          data={"playing": playing, "token": token,
                "date": state.current_date if state is not None else None},
          on_tick_change=_on_tick_change)
