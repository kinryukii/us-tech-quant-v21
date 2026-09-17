"""Native tabs whose saved selection is independent of their translated labels."""
from collections.abc import Callable, Sequence

import streamlit as st

from apps.demo_console.i18n import tr


def _remember_tab(key: str, source_key: str, label_sources: dict[str, str]) -> None:
    # The callback runs before the new language context is established. Use the
    # exact label mapping captured when the originating widget was rendered.
    source = label_sources.get(st.session_state.get(key))
    if source is not None:
        st.session_state[source_key] = source


def localized_tabs(sources: Sequence[str], *, key: str,
                   format_func: Callable[[str], str] | None = None):
    """Return all native tab containers, retaining the selected English source.

    Pass untranslated source messages and a stable, unique widget key. Callers
    render every returned container normally; this helper does not gate content
    on ``tab.open``. The private source state survives widget cleanup when the
    containing page is temporarily absent.

    ``format_func`` may format a source containing placeholders into its final
    display label. The unformatted source remains the stable saved identity.
    """
    if isinstance(sources, str):
        raise ValueError("Tab sources must be a sequence of distinct messages.")
    sources = tuple(sources)
    if not sources or any(not isinstance(source, str) or not source for source in sources):
        raise ValueError("At least one nonempty tab source is required.")
    if len(set(sources)) != len(sources):
        raise ValueError("Tab sources must be distinct.")
    labeler = tr if format_func is None else format_func
    labels = tuple(labeler(source) for source in sources)
    if len(set(labels)) != len(labels):
        raise ValueError("Translated tab labels must be distinct.")
    source_key = f"_localized_tabs:{key}"
    selected = st.session_state.get(source_key)
    if selected not in sources:
        selected = sources[0]
        st.session_state[source_key] = selected
    label = labels[sources.index(selected)]
    if st.session_state.get(key) != label:
        st.session_state[key] = label
    return st.tabs(labels, key=key, default=label, on_change=_remember_tab,
                   args=(key, source_key, dict(zip(labels, sources))))
