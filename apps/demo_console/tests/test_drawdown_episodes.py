"""Synthetic episode boundaries, cutoff semantics and native selector behavior."""
from dataclasses import asdict, replace
import json

import pytest

from apps.demo_console.components.drawdown_episodes import (
    analyze_drawdown_episodes, episode_chart, episode_records, selected_episode,
)
from apps.demo_console.models import PerformancePoint


def points(returns, *, days=None):
    days = days or tuple(f"2025-12-{index + 1:02}" for index in range(len(returns)))
    return tuple(PerformancePoint(
        execution_date=day, nav=1.0, net_return=value, gross_return=value,
        transaction_cost=0.0, turnover=0.0, cash=0.0, position_value=1.0,
        holding_count=20, stale_mark_count=0, skipped_buy_count=0,
        blocked_rebalance_count=0, buy_cash_scale=1.0,
    ) for day, value in zip(days, returns, strict=True))


def test_first_return_loss_uses_undated_initial_peak_and_observed_return_intervals():
    rows = points((-.2, 0.0, .25))
    summary, episodes = analyze_drawdown_episodes(rows)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.peak_date is None and episode.peak_index == -1
    assert episode.first_underwater_date == episode.trough_date == "2025-12-01"
    assert episode.recovery_date == episode.end_date == "2025-12-03"
    assert episode.depth == pytest.approx(-.2)
    assert (episode.peak_to_end_intervals, episode.trough_to_end_intervals,
            episode.underwater_observations) == (3, 2, 2)
    records = episode_chart(summary, episode).to_dict()["data"]["values"]
    assert [row["execution_date"] for row in records] == [row.execution_date for row in rows]
    assert [row["drawdown"] for row in records] == pytest.approx([-.2, -.2, 0])


def test_repeated_highs_new_high_and_terminal_unrecovered_episode():
    summary, episodes = analyze_drawdown_episodes(points((.1, -.2, .25, 0, .1, -.1)))
    first, last = episodes
    assert first.peak_date == "2025-12-01" and first.trough_date == "2025-12-02"
    assert first.recovery_date == "2025-12-03"
    assert (first.peak_to_end_intervals, first.trough_to_end_intervals) == (2, 1)
    assert last.peak_date == "2025-12-05" and last.trough_date == "2025-12-06"
    assert last.recovery_date is None and last.end_date == "2025-12-06"
    assert last.status == "Unrecovered at cutoff" and last.depth == pytest.approx(-.1)
    assert last.underwater_observations == 1
    assert (last.peak_to_end_intervals, last.trough_to_end_intervals) == (1, 0)
    assert selected_episode(episodes) == last
    assert selected_episode(episodes, first.first_underwater_date) == first


def test_flat_peak_uses_latest_observed_high_and_equal_recovery_is_complete():
    _, episodes = analyze_drawdown_episodes(points((0, 0, -.2, .25, 0, -.1)))
    assert episodes[0].peak_date == "2025-12-02"
    assert episodes[0].recovery_date == "2025-12-04"
    assert episodes[1].peak_date == "2025-12-05"


def test_float_equality_closes_episode_without_modifying_economic_coordinates():
    values = (-.2, (1 - 5e-13) / .8 - 1, 0, -.1)
    summary, episodes = analyze_drawdown_episodes(points(values))
    assert len(episodes) == 2
    assert episodes[0].recovery_date == summary.max_drawdown.recovery_date == "2025-12-02"
    assert episodes[1].peak_date == "2025-12-03"
    assert summary.wealth[1].drawdown < 0, "A floating-point recovery must not rewrite recorded values to zero."
    spec = episode_chart(summary, episodes[0]).to_dict()
    assert spec["data"]["values"][-1]["drawdown"] == summary.wealth[1].drawdown


def test_cutoff_does_not_borrow_later_recovery_or_infer_calendar_days():
    rows = points((.1, -.2, .1, .15), days=("2025-12-01", "2025-12-05", "2025-12-12", "2025-12-19"))
    _, whole = analyze_drawdown_episodes(rows)
    summary, cut = analyze_drawdown_episodes(rows[:3])
    assert whole[0].recovery_date == "2025-12-19"
    assert cut[0].recovery_date is None and cut[0].end_date == "2025-12-12"
    assert cut[0].peak_to_end_intervals == 2
    assert cut[0].trough_to_end_intervals == 1
    assert cut[0].first_underwater_date == whole[0].first_underwater_date
    assert all(row["execution_date"] <= "2025-12-12"
               for row in episode_chart(summary, cut[0]).to_dict()["data"]["values"])


def test_episode_chart_slices_original_path_without_reapplying_peak_day_return():
    rows = points((.2, -.1, -.1, .3))
    before = [asdict(row) for row in rows]
    summary, episodes = analyze_drawdown_episodes(rows)
    chart = episode_chart(summary, episodes[0]).to_dict()
    assert chart["name"] == "research_drawdown_episode_chart"
    assert chart["data"]["values"] == [
        {"execution_date": point.execution_date, "drawdown": point.drawdown}
        for point in summary.wealth]
    assert chart["data"]["values"][0]["drawdown"] == 0
    assert chart["data"]["values"][2]["drawdown"] == pytest.approx(-.19)
    assert [asdict(row) for row in rows] == before
    json.dumps(chart, allow_nan=False)


@pytest.mark.parametrize("returns", [(), (.1,), (0, 0, 0), (.1, 0, .2)])
def test_empty_flat_and_all_positive_windows_have_no_fabricated_episode(returns):
    _, episodes = analyze_drawdown_episodes(points(returns))
    assert episodes == () and selected_episode(episodes, "anything") is None


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True, -1.0, -1.1])
def test_missing_or_invalid_returns_are_rejected_instead_of_skipped_or_filled(bad):
    with pytest.raises(ValueError):
        analyze_drawdown_episodes(points((-.1, bad, .2)))


def test_duplicate_or_reversed_dates_are_rejected_and_trough_ties_keep_first():
    with pytest.raises(ValueError):
        analyze_drawdown_episodes(points((-.1, .2), days=("2025-12-01", "2025-12-01")))
    with pytest.raises(ValueError):
        analyze_drawdown_episodes(tuple(reversed(points((-.1, .2)))))
    _, episodes = analyze_drawdown_episodes(points((-.1, 0, 0)))
    assert episodes[0].trough_date == "2025-12-01"
    assert episode_records(episodes)[0]["recovery_date"] is None


def test_window_shift_recomputes_peak_context_without_borrowing_prior_wealth():
    rows = points((.2, -.1, .2))
    _, whole = analyze_drawdown_episodes(rows)
    _, shifted = analyze_drawdown_episodes(rows[1:])
    assert whole[0].peak_date == "2025-12-01"
    assert shifted[0].peak_date is None
    assert whole[0].first_underwater_date == shifted[0].first_underwater_date == "2025-12-02"
    assert selected_episode(shifted, whole[0].first_underwater_date) == shifted[0]


def _app():
    import streamlit as st
    from apps.demo_console.components.drawdown_episodes import render_drawdown_episodes
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.tests.test_drawdown_episodes import points

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    window = st.selectbox("Window", ("Full", "Earlier", "Shifted", "Cutoff", "Positive", "Invalid"), key="window")
    rows = points((.1, -.2, .25, 0, -.1, .2, -.2, 0))
    selected = {"Full": rows, "Earlier": rows[:4], "Shifted": rows[4:],
                "Cutoff": rows[:7], "Positive": rows[:1], "Invalid": points((None,))}[window]
    with language_scope(language):
        render_drawdown_episodes(selected)


def test_native_selector_preserves_valid_episode_through_language_and_window_changes():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.i18n import catalog

    app = AppTest.from_function(_app, default_timeout=15).run()
    assert not app.exception and not app.error
    assert any("Raw A2 portfolio" in caption.value for caption in app.caption)
    assert any("3 episodes · 2 recovered · 1 unrecovered" in caption.value for caption in app.caption)
    key = "research_drawdown_episode"
    assert app.selectbox(key=key).value == "2025-12-07", "Default must be chronological latest, not deepest."
    app.selectbox(key=key).select("2025-12-05").run()
    original = [metric.value for metric in app.metric]
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert app.selectbox(key=key).value == "2025-12-05"
        assert [metric.value for metric in app.metric] == original
        translated = "Recovered" if language == "en" else catalog()["Recovered"][language]
        assert app.selectbox(key=key).proto.raw_value == f"2025-12-05 · -10.00% · {translated}"
    app.selectbox(key="window").select("Shifted").run()
    assert not app.exception
    assert app.selectbox(key=key).value == "2025-12-05"
    assert "Initial window baseline" in "\n".join(item.proto.body for item in app.get("html"))
    app.selectbox(key="window").select("Earlier").run()
    assert not app.exception
    assert app.selectbox(key=key).value == "2025-12-02"
    assert app.dataframe[0].value["recovery_date"].tolist() == ["2025-12-03"]


def test_cutoff_updates_unrecovered_metrics_and_empty_or_invalid_views_hide_charts():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(_app, default_timeout=15).run()
    assert [metric.value for metric in app.metric][1:] == ["2", "1"]
    app.selectbox(key="window").select("Cutoff").run()
    assert not app.exception and not app.error
    assert app.selectbox(key="research_drawdown_episode").value == "2025-12-07"
    assert [metric.value for metric in app.metric][1:] == ["1", "0"]
    for window in ("Positive", "Invalid"):
        app.selectbox(key="window").select(window).run()
        assert not app.exception and not app.error and app.info
        assert not app.get("vega_lite_chart") and not app.metric and not app.dataframe
