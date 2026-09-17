"""Inspect all drawdown episodes within one supplied execution window, without reads."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isclose

import streamlit as st

from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.performance_charts import drawdown_chart
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import tr

_SELECTION = "research_drawdown_episode"


@dataclass(frozen=True)
class DrawdownEpisode:
    """Indices reference the original selected window; -1 is its undated baseline."""
    first_underwater_date: str
    peak_date: str | None
    trough_date: str
    recovery_date: str | None
    end_date: str
    depth: float
    peak_index: int
    start_index: int
    trough_index: int
    end_index: int

    @property
    def peak_to_end_intervals(self):
        return self.end_index - self.peak_index

    @property
    def trough_to_end_intervals(self):
        return self.end_index - self.trough_index

    @property
    def underwater_observations(self):
        return self.end_index - self.start_index + (self.recovery_date is None)

    @property
    def status(self):
        return "Recovered" if self.recovery_date else "Unrecovered at cutoff"


def analyze_drawdown_episodes(points):
    """Validate and compound with the canonical helper, then describe contiguous declines.

    Each episode ends at the first observed return to its prior high, or at the
    supplied cutoff. Repeated highs use the most recent observed peak date.
    Equality uses the existing drawdown summary's 1e-12 relative tolerance to
    avoid treating floating-point roundoff as a fresh episode. Tied troughs keep
    the first occurrence. Missing/invalid returns are rejected, never filled.
    """
    summary = summarize_performance(points)
    path, episodes = summary.wealth, []
    peak, peak_index, start, trough = summary.initial_wealth, -1, None, None

    def finish(end, recovered):
        episodes.append(DrawdownEpisode(
            path[start].execution_date,
            path[peak_index].execution_date if peak_index >= 0 else None,
            path[trough].execution_date,
            path[end].execution_date if recovered else None,
            path[end].execution_date, path[trough].net_wealth / peak - 1.0,
            peak_index, start, trough, end,
        ))

    for index, point in enumerate(path):
        value = point.net_wealth
        if value >= peak or isclose(value, peak, rel_tol=1e-12, abs_tol=0.0):
            if start is not None:
                finish(index, True)
                start, trough = None, None
            peak, peak_index = max(peak, value), index
        else:
            if start is None:
                start = trough = index
            elif value < path[trough].net_wealth:
                trough = index
    if start is not None:
        finish(len(path) - 1, False)
    return summary, tuple(episodes)


def selected_episode(episodes, requested=None):
    """Keep an existing start-date identity; otherwise select the latest by chronology."""
    return next((episode for episode in episodes if episode.first_underwater_date == requested),
                episodes[-1] if episodes else None)


def episode_chart(summary, episode):
    """Slice existing drawdown coordinates; never reapply the peak day's return."""
    points = summary.wealth[max(0, episode.peak_index):episode.end_index + 1]
    return drawdown_chart(replace(summary, wealth=points)).properties(name="research_drawdown_episode_chart")


def episode_records(episodes):
    return [{"first_underwater_date": episode.first_underwater_date,
             "peak_date": episode.peak_date or tr("Initial window baseline"),
             "trough_date": episode.trough_date,
             "recovery_date": episode.recovery_date,
             "end_date": episode.end_date, "depth": episode.depth,
             "peak_to_end_intervals": episode.peak_to_end_intervals,
             "trough_to_end_intervals": episode.trough_to_end_intervals,
             "underwater_observations": episode.underwater_observations,
             "status": tr(episode.status)} for episode in episodes]


def render_drawdown_episodes(points, *, presentation=True):
    """Render a selected episode and the chronological ledger from supplied observations."""
    st.html(section_header(tr("Drawdown & recovery"), tr("EVERY RECORDED SETBACK")))
    try:
        summary, episodes = analyze_drawdown_episodes(points)
    except (ValueError, TypeError, AttributeError):
        st.info(tr("Drawdown episodes cannot be calculated from incomplete or invalid observations. Missing returns are not filled."))
        return
    if not summary.wealth:
        st.info(tr("No recorded execution observations are available for drawdown analysis."))
        return
    st.caption(tr("Raw A2 portfolio · Selected window: {start} → {end}. The default is the latest episode by date, not the deepest.",
                  start=summary.start_date, end=summary.end_date))
    if not episodes:
        st.info(tr("No decline below the running peak was recorded in this window."))
        return
    recovered = sum(episode.recovery_date is not None for episode in episodes)
    st.caption(tr("{total} episodes · {recovered} recovered · {unrecovered} unrecovered at cutoff",
                  total=len(episodes), recovered=recovered, unrecovered=len(episodes) - recovered))
    choice = selected_episode(episodes, st.session_state.get(_SELECTION))
    options = tuple(episode.first_underwater_date for episode in reversed(episodes))
    labels = {episode.first_underwater_date:
              tr("{date} · {depth} · {status}", date=episode.first_underwater_date,
                 depth=f"{episode.depth:.2%}", status=tr(episode.status)) for episode in episodes}
    label_context = tuple(labels.items())
    if (st.session_state.get(_SELECTION) != choice.first_underwater_date
            or st.session_state.get("_drawdown_episode_labels") != label_context):
        st.session_state[_SELECTION] = choice.first_underwater_date
        st.session_state["_drawdown_episode_labels"] = label_context
    selected = st.selectbox(tr("Drawdown episode to inspect"), options, index=None,
                            key=_SELECTION, format_func=labels.__getitem__, persist_state="session")
    choice = selected_episode(episodes, selected)
    peak = choice.peak_date or tr("Initial window baseline")
    end_label = "Recovery to that peak" if choice.recovery_date else "Observed cutoff"
    st.html('<div class="uq-drawdown-story">' + ''.join(
        f'<div><span>{text(tr(label))}</span><strong>{text(value)}</strong></div>'
        for label, value in (("Episode peak", peak), ("Episode trough", choice.trough_date),
                             (end_label, choice.end_date))) + '</div>')
    st.caption(tr(choice.status))
    depth, peak_span, recovery_span = st.columns(3, gap="medium")
    depth.metric(tr("Episode depth"), f"{choice.depth:.2%}")
    peak_span.metric(tr("Peak → recovery · observed intervals" if choice.recovery_date else
                        "Peak → cutoff · observed intervals"), choice.peak_to_end_intervals)
    recovery_span.metric(tr("Trough → recovery · observed intervals" if choice.recovery_date else
                            "Trough → cutoff · observed intervals"), choice.trough_to_end_intervals)
    render_chart(episode_chart(summary, choice), width="stretch", height=260 if presentation else 230,
                 theme=None, key="research_drawdown_episode_chart")
    st.caption(tr("The chart retains the selected research window's original drawdown values. It does not restart the return path on the peak date."))
    st.caption(tr("Intervals count recorded execution steps, not calendar days. The undated initial baseline precedes the first included return; no earlier peak date is inferred."))
    with st.expander(tr("Inspect all {count} episodes", count=len(episodes)), expanded=False):
        st.dataframe(episode_records(episodes), hide_index=True, width="stretch",
                     key="research_drawdown_episode_table", column_config={
                         "first_underwater_date": st.column_config.TextColumn(tr("First underwater observation")),
                         "peak_date": st.column_config.TextColumn(tr("Episode peak")),
                         "trough_date": st.column_config.TextColumn(tr("Episode trough")),
                         "recovery_date": st.column_config.TextColumn(tr("Recovery to that peak")),
                         "end_date": st.column_config.TextColumn(tr("Episode end / cutoff")),
                         "depth": st.column_config.NumberColumn(tr("Episode depth"), format="percent"),
                         "peak_to_end_intervals": st.column_config.NumberColumn(tr("Peak → end · intervals"), format="%d"),
                         "trough_to_end_intervals": st.column_config.NumberColumn(tr("Trough → end · intervals"), format="%d"),
                         "underwater_observations": st.column_config.NumberColumn(tr("Underwater observations"), format="%d"),
                         "status": st.column_config.TextColumn(tr("Recovery status")),
                     })
    st.caption(tr("These episodes describe one return path. Their counts and durations are not independent trials or proof of predictive skill. Recovery is recognized only when observed within the cutoff."))
