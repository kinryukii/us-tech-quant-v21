"""Applied calendar state only; no files, market data or research runtime."""
from datetime import date

from streamlit.testing.v1 import AppTest

from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.tests.test_terminal_interactions import _content


def _app():
    import streamlit as st
    from apps.demo_console.components.performance_range import render_date_range, reset_date_range
    from apps.demo_console.i18n import language_scope

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    limit = st.selectbox("Synthetic cutoff", ("2025-02-28", "2025-02-10", "2025-01-10"), key="cutoff")
    preset = st.selectbox("Synthetic preset", ("All", "Last week"), key="preset",
                         on_change=reset_date_range, args=("test_range",))
    show = st.checkbox("Show range controls", value=True, key="show")
    if show:
        default_start = "2025-01-01" if preset == "All" else limit[:8] + "07"
        with language_scope(language):
            selected = render_date_range("test_range", "2025-01-01", limit, default_start, limit)
        st.session_state["observed_range"] = selected


def test_only_complete_apply_changes_range_and_three_languages_preserve_it():
    app = AppTest.from_function(_app, default_timeout=10).run()
    assert not app.exception and app.session_state["observed_range"] is None
    chosen = (date(2025, 1, 7), date(2025, 2, 20))
    app.date_input(key="test_range_draft").set_value(chosen).run()
    assert app.session_state["observed_range"] is None
    app.button(key="test_range_apply").click().run()
    assert not app.exception and app.session_state["observed_range"] == ("2025-01-07", "2025-02-20")
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and app.date_input(key="test_range_draft").value == chosen
        assert app.session_state["observed_range"] == ("2025-01-07", "2025-02-20")
        with language_scope(language):
            assert app.date_input(key="test_range_draft").label == tr("Start and end dates")
            assert app.button(key="test_range_apply").label == tr("Apply date range")
    app.date_input(key="test_range_draft").set_value((date(2025, 1, 9),))
    app.button(key="test_range_apply").click().run()
    assert not app.exception and app.warning
    assert app.session_state["observed_range"] == ("2025-01-07", "2025-02-20")
    assert "Choose a start date and an end date before applying." in _content(app)


def test_cutoff_change_clips_applied_dates_or_restores_preset_with_notice():
    app = AppTest.from_function(_app, default_timeout=10).run()
    app.date_input(key="test_range_draft").set_value((date(2025, 2, 1), date(2025, 2, 20)))
    app.button(key="test_range_apply").click().run()
    app.selectbox(key="cutoff").select("2025-02-10").run()
    assert not app.exception
    assert app.session_state["observed_range"] == ("2025-02-01", "2025-02-10")
    assert app.date_input(key="test_range_draft").value == (date(2025, 2, 1), date(2025, 2, 10))
    assert "The applied range was adjusted to the available dates." in _content(app)
    app.selectbox(key="cutoff").select("2025-02-28").run()
    assert app.session_state["observed_range"] == ("2025-02-01", "2025-02-10")
    app.selectbox(key="cutoff").select("2025-01-10").run()
    assert not app.exception and app.session_state["observed_range"] is None
    assert app.date_input(key="test_range_draft").value == (date(2025, 1, 1), date(2025, 1, 10))
    assert "The previous range is outside the available dates. The preset is now in use." in _content(app)


def test_navigation_preserves_applied_range_and_preset_or_reset_clears_it():
    app = AppTest.from_function(_app, default_timeout=10).run()
    chosen = (date(2025, 1, 7), date(2025, 2, 20))
    app.date_input(key="test_range_draft").set_value(chosen)
    app.button(key="test_range_apply").click().run()
    app.checkbox(key="show").uncheck().run()
    app.checkbox(key="show").check().run()
    assert app.date_input(key="test_range_draft").value == chosen
    assert app.session_state["observed_range"] == ("2025-01-07", "2025-02-20")
    app.selectbox(key="preset").select("Last week").run()
    assert not app.exception and app.session_state["observed_range"] is None
    assert app.date_input(key="test_range_draft").value == (date(2025, 2, 7), date(2025, 2, 28))
    app.date_input(key="test_range_draft").set_value(chosen)
    app.button(key="test_range_apply").click().run()
    app.button(key="test_range_reset").click().run()
    assert not app.exception and app.session_state["observed_range"] is None
    assert app.date_input(key="test_range_draft").value == (date(2025, 2, 7), date(2025, 2, 28))
