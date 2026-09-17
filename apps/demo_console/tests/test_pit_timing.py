"""Synthetic timing boundaries and native UI state; no external result fixtures."""
from pathlib import Path

import pytest

from apps.demo_console.components import pit_timing
from apps.demo_console.i18n import language_scope


@pytest.mark.parametrize(("case", "state", "public", "first", "normalized"), (
    ("Before close · 15:59", "available", True, "2025-01-02", "2025-01-02T20:59:00+00:00"),
    ("At close · 16:00", "available", True, "2025-01-02", "2025-01-02T21:00:00+00:00"),
    ("After close · 16:01", "deferred", False, "2025-01-03", "2025-01-02T21:01:00+00:00"),
    ("Timezone missing", "rejected", None, None, None),
))
def test_actual_canonical_guard_decides_fixed_synthetic_boundary(case, state, public, first, normalized):
    result = pit_timing.timing_example(case)
    assert result["state"] == state
    assert result["public"] is public
    assert result["first_session"] == first
    assert result["normalized_timestamp"] == normalized
    assert result["rule_code"] == ("ACCEPTED_TIMESTAMP_TIMEZONE_MISSING" if state == "rejected" else None)


def test_component_delegates_to_canonical_guard_without_reading_artifacts(monkeypatch):
    from scripts.v22 import pit_13f_reconstruction_r1 as canonical

    calls = []
    for name in ("accepted_utc", "filing_is_public_for_signal", "first_legal_signal_session"):
        original = getattr(canonical, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(canonical, name, observed)

    def forbidden(*args, **kwargs):
        raise AssertionError("Synthetic timing must not read an artifact")

    monkeypatch.setattr(Path, "open", forbidden)
    result = pit_timing.timing_example("After close · 16:01")
    assert result["first_session"] == "2025-01-03"
    assert set(calls) == {"accepted_utc", "filing_is_public_for_signal", "first_legal_signal_session"}


def test_missing_timezone_and_untrusted_display_cannot_look_like_a_timing_pass():
    result = pit_timing.timing_example("Timezone missing")
    attack = '<img src=x onerror="bad()">'
    markup = pit_timing.timing_html({**result, "timestamp": attack,
                                     "normalized_timestamp": attack, "rule_code": attack})
    assert "&lt;img" in markup and "<img" not in markup
    assert "uq-pit-state-rejected" in markup and "No permitted session inferred" in markup
    assert "Traceback" not in markup and "Pit13FContractError" not in markup
    correction = pit_timing.recheck_html({**result, "timestamp": attack, "first_session": attack})
    assert "&lt;img" in correction and "<img" not in correction
    assert "uq-pit-state-rejected" in correction
    with pytest.raises(ValueError, match="Unknown synthetic"):
        pit_timing.timing_example("2026-01-01")


def _app():
    import streamlit as st
    from apps.demo_console.components.pit_timing import render_pit_timing
    from apps.demo_console.i18n import language_scope

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    st.session_state.setdefault("decision_date", "2025-12-02")
    st.session_state.setdefault("workspace", "System overview")
    st.session_state.setdefault("inspect_ticker", "SYNTHETIC_FOCUS")
    with language_scope(language):
        render_pit_timing()


def test_native_case_and_language_switches_preserve_global_decision_and_focus():
    from streamlit.testing.v1 import AppTest

    # Exercise the shipped catalog; this test must also run from the live app.
    app = AppTest.from_function(_app, default_timeout=15).run()

    def control():
        return next(element for element in app.get("button_group") if element.key == "system_pit_case")

    for case in pit_timing.CASES:
        control().select(case).run()
        expected = pit_timing.timing_example(case)
        for language in ("zh", "ja", "en"):
            app.selectbox(key="language").select(language).run()
            assert not app.exception and not app.error
            assert control().value == case
            assert app.session_state["decision_date"] == "2025-12-02"
            assert app.session_state["workspace"] == "System overview"
            assert app.session_state["inspect_ticker"] == "SYNTHETIC_FOCUS"
            with language_scope(language):
                expected_markup = pit_timing.timing_html(expected)
            assert expected_markup in [element.proto.body for element in app.get("html")]
            assert "uq-pit-state-" + expected["state"] in expected_markup
            assert not app.get("vega_lite_chart") and not app.dataframe


def test_unavailable_canonical_helper_has_no_fabricated_result(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def unavailable():
        raise ImportError("SYNTHETIC_PRIVATE_PATH")

    monkeypatch.setattr(pit_timing, "_pit_module", unavailable)
    app = AppTest.from_function(_app, default_timeout=15).run()
    assert not app.exception and not app.error
    assert app.info and "No timing result is inferred" in app.info[0].value
    markup = "\n".join(element.proto.body for element in app.get("html"))
    assert "uq-pit-result" not in markup and "SYNTHETIC_PRIVATE_PATH" not in markup


def test_recheck_uses_the_actual_guard_preserves_language_and_clears_on_input_change(monkeypatch):
    from streamlit.testing.v1 import AppTest

    actual = pit_timing.timing_example
    calls = []

    def observed(case):
        calls.append(case)
        return actual(case)

    monkeypatch.setattr(pit_timing, "timing_example", observed)
    app = AppTest.from_function(_app, default_timeout=15).run()

    def control():
        return next(element for element in app.get("button_group") if element.key == "system_pit_case")

    def markup():
        return "\n".join(element.proto.body for element in app.get("html"))

    assert control().value == "Timezone missing"
    assert "uq-pit-state-rejected" in markup() and "uq-pit-recheck-result" not in markup()
    app.button(key="system_pit_recheck").click().run()
    corrected = actual("Before close · 15:59")
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception and not app.error
        assert calls[-2:] == ["Timezone missing", "Before close · 15:59"]
        assert app.session_state[pit_timing._RECHECK] == "Timezone missing"
        with language_scope(language):
            assert pit_timing.recheck_html(corrected) in markup()
        assert control().value == "Timezone missing"
        assert app.session_state["decision_date"] == "2025-12-02"
        assert app.session_state["workspace"] == "System overview"
        assert app.session_state["inspect_ticker"] == "SYNTHETIC_FOCUS"

    control().select("After close · 16:01").run()
    assert not app.exception and not app.error
    assert pit_timing._RECHECK not in app.session_state
    assert "uq-pit-state-deferred" in markup() and "uq-pit-recheck-result" not in markup()
    assert app.button(key="system_pit_recheck").disabled
    control().select("Timezone missing").run()
    assert "uq-pit-recheck-result" not in markup()
    assert not app.button(key="system_pit_recheck").disabled


def test_recheck_does_not_reuse_a_success_when_the_canonical_helper_is_unavailable(monkeypatch):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(_app, default_timeout=15).run()
    app.button(key="system_pit_recheck").click().run()
    assert any("uq-pit-recheck-result uq-pit-state-available" in element.proto.body
               for element in app.get("html"))
    actual = pit_timing.timing_example

    def unavailable(case):
        if case == "Before close · 15:59":
            raise ImportError("SYNTHETIC_PRIVATE_RECHECK_PATH")
        return actual(case)

    monkeypatch.setattr(pit_timing, "timing_example", unavailable)
    app.run()
    assert not app.exception and not app.error
    assert app.info and "No timing result is inferred" in app.info[0].value
    markup = "\n".join(element.proto.body for element in app.get("html"))
    assert "uq-pit-recheck-result" not in markup and "SYNTHETIC_PRIVATE_RECHECK_PATH" not in markup


def test_recheck_displays_a_canonical_rejection_without_claiming_recovery(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from scripts.v22 import pit_13f_reconstruction_r1 as canonical

    app = AppTest.from_function(_app, default_timeout=15).run()
    accepted = canonical.accepted_utc

    def rejected(value):
        if value == pit_timing.CASES["Before close · 15:59"]:
            raise canonical.Pit13FContractError("SYNTHETIC_RECHECK_REJECTION")
        return accepted(value)

    monkeypatch.setattr(canonical, "accepted_utc", rejected)
    app.button(key="system_pit_recheck").click().run()
    assert not app.exception and not app.error
    result = next(element.proto.body for element in app.get("html")
                  if "uq-pit-recheck-result" in element.proto.body)
    assert "uq-pit-state-rejected" in result and "No permitted session inferred" in result
    assert "Available for the January 2 signal" not in result
    assert app.session_state["decision_date"] == "2025-12-02"
