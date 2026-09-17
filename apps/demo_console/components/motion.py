"""Optional local motion over rendered records; never modify their values."""
from html import escape
import json
from pathlib import Path

import streamlit as st


_DISABLED_CSS = """
/* Explicit off also works if inline JavaScript is blocked or unavailable. */
*, *::before, *::after {
  transition: none !important;
  animation: none !important;
  scroll-behavior: auto !important;
}
[data-testid="stButton"] button:hover { transform: none !important; }
"""


def motion_html(view: str, decision_date: str | None, *, enabled: bool = True) -> str:
    """Keep context in an escaped data attribute and executable code fixed."""
    directory = Path(__file__).parent
    context = json.dumps({"view": view, "decision_date": decision_date, "enabled": bool(enabled)},
                         ensure_ascii=True, separators=(",", ":"))
    css = (directory / "motion.css").read_text(encoding="utf-8")
    if not enabled:
        css += _DISABLED_CSS
    script = (directory / "motion.js").read_text(encoding="utf-8")
    return (f'<style>{css}</style>'
            f'<div data-uq-motion-config="{escape(context, quote=True)}" hidden></div>'
            f'<script>{script}</script>')


def render_motion(view: str, decision_date: str | None, *, enabled: bool = True) -> None:
    """Call once after a complete page render, using the untranslated view key.

    Browser-local context prevents filters and language reruns from replaying the
    entrance. Disabling updates that context and cancels in-flight effects; it
    never changes Streamlit state, financial values, or the selected date.
    Chart regions only fade as a whole; their plotted marks and hit targets are
    never redrawn. CSS also honors reduced motion before this script executes.
    """
    st.html(motion_html(view, decision_date, enabled=enabled), unsafe_allow_javascript=True)
