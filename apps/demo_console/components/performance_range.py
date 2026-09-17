"""Native, applied-only calendar ranges shared by recorded performance views."""
from datetime import date

import streamlit as st

from apps.demo_console.i18n import tr


def reset_date_range(key):
    """Return to the caller's preset; safe as a preset widget callback."""
    for suffix in ("applied", "bounds", "error", "notice"):
        st.session_state.pop(f"_performance_range:{key}:{suffix}", None)
    st.session_state.pop(f"{key}_draft", None)


def render_date_range(key, min_date, max_date, default_start, default_end):
    """Return applied ISO endpoints, or None while the caller's preset is active.

    Calendar selection is a draft until Apply. Bounds are calendar limits only;
    callers select real observations and handle empty intervals themselves.
    """
    lower, upper = date.fromisoformat(min_date), date.fromisoformat(max_date)
    first, last = date.fromisoformat(default_start), date.fromisoformat(default_end)
    if not lower <= first <= last <= upper:
        raise ValueError("The default performance range must be within its calendar bounds")
    prefix, draft_key = f"_performance_range:{key}:", f"{key}_draft"
    applied = st.session_state.get(prefix + "applied")
    bounds = (min_date, max_date)
    if st.session_state.get(prefix + "bounds") != bounds:
        if applied is not None:
            clipped = (max(applied[0], min_date), min(applied[1], max_date))
            if clipped != applied:
                applied = clipped if clipped[0] <= clipped[1] else None
                st.session_state[prefix + "applied"] = applied
                st.session_state[prefix + "notice"] = (
                    "The applied range was adjusted to the available dates." if applied else
                    "The previous range is outside the available dates. The preset is now in use.")
        st.session_state.pop(draft_key, None)
        st.session_state.pop(prefix + "error", None)
        st.session_state[prefix + "bounds"] = bounds

    initial = tuple(date.fromisoformat(value) for value in applied) if applied else (first, last)
    with st.popover(tr("Select date range"), icon=":material/date_range:"):
        with st.form(f"{key}_form", border=False):
            draft = st.date_input(tr("Start and end dates"), value=initial,
                min_value=lower, max_value=upper, format="YYYY-MM-DD", key=draft_key,
                persist_state="session",
                help=tr("Choose both dates, then apply. Only recorded observations inside the range are included."))
            submitted = st.form_submit_button(tr("Apply date range"), key=f"{key}_apply", type="primary")
        if submitted:
            if not isinstance(draft, (tuple, list)) or len(draft) != 2:
                st.session_state[prefix + "error"] = "Choose a start date and an end date before applying."
            elif not lower <= draft[0] <= draft[1] <= upper:
                st.session_state[prefix + "error"] = "Choose an ordered range within the available dates."
            else:
                applied = (draft[0].isoformat(), draft[1].isoformat())
                st.session_state[prefix + "applied"] = applied
                st.session_state.pop(prefix + "error", None)
                st.session_state.pop(prefix + "notice", None)
        error = st.session_state.get(prefix + "error")
        if error:
            st.warning(tr(error))
        st.caption(tr("Applied: {start} → {end}", start=applied[0], end=applied[1]) if applied else
                   tr("Preset range in use."))
        st.button(tr("Use preset range"), key=f"{key}_reset", on_click=reset_date_range,
                  args=(key,), disabled=applied is None)
    notice = st.session_state.get(prefix + "notice")
    if notice:
        st.caption(tr(notice))
    return applied
