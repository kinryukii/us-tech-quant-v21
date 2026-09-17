"""A synthetic timing demonstration of the existing canonical 13F guard.

Only fixed timestamps and two supplied sessions are used. No filing, price,
model, registry or result artifact is loaded by this component.
"""
from __future__ import annotations

import streamlit as st

from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import option_labeler, tr


SESSIONS = ("2025-01-02", "2025-01-03")
CASES = {
    "Before close · 15:59": "2025-01-02T15:59:00-05:00",
    "At close · 16:00": "2025-01-02T16:00:00-05:00",
    "After close · 16:01": "2025-01-02T16:01:00-05:00",
    "Timezone missing": "2025-01-02T15:59:00",
}
_KEY = "system_pit_case"
_DEFAULT = "Timezone missing"
_CONTEXT = "_system_pit_context"
_RECHECK = "_system_pit_recheck_requested"
_CORRECTED_CASE = "Before close · 15:59"


def _pit_module():
    # The canonical module imports only local code/numpy/pandas. Its functions
    # below are pure; do not call any filing/configuration reader or runner.
    from scripts.v22 import pit_13f_reconstruction_r1
    return pit_13f_reconstruction_r1


def timing_example(case: str) -> dict:
    """Delegate the date decision to the existing guard, not a UI reimplementation."""
    if case not in CASES:
        raise ValueError("Unknown synthetic timing case")
    pit = _pit_module()
    timestamp = CASES[case]
    try:
        accepted = pit.accepted_utc(timestamp)
        public = pit.filing_is_public_for_signal(accepted, SESSIONS[0])
        first = pit.first_legal_signal_session(accepted, SESSIONS)
    except pit.Pit13FContractError as exc:
        return {"timestamp": timestamp, "public": None, "first_session": None,
                "normalized_timestamp": None, "rule_code": str(exc), "state": "rejected"}
    return {"timestamp": timestamp, "public": bool(public),
            "first_session": first.date().isoformat(),
            "normalized_timestamp": accepted.isoformat(), "rule_code": None,
            "state": "available" if public else "deferred"}


def _outcome(result: dict) -> tuple[str, str]:
    state = result["state"] if result.get("state") in {"available", "deferred", "rejected"} else "rejected"
    message = {
        "available": "Available for the January 2 signal",
        "deferred": "Too late for January 2 · first usable on January 3",
        "rejected": "Rejected by the canonical timing rule",
    }[state]
    return state, message


def timing_html(result: dict) -> str:
    """Show the supplied input, actual normalization and bounded timing impact."""
    state, message = _outcome(result)
    first = result.get("first_session") or tr("No permitted session inferred")
    normalized = result.get("normalized_timestamp") or tr("Not normalized")
    validation = "Timestamp rejected; no signal eligibility is inferred." if state == "rejected" else "Timezone supplied; normalized to UTC."
    code = ('<code class="uq-pit-rule-code">' + text(result["rule_code"]) + '</code>') if result.get("rule_code") else ""
    return ('<section class="uq-pit-demo"><div class="uq-pit-chain">'
            '<div class="uq-pit-card"><span class="uq-pit-step">' + text(tr("1 · Synthetic input"))
            + '</span><span class="uq-pit-label">' + text(tr("Synthetic acceptance timestamp"))
            + '</span><strong class="uq-pit-value">' + text(result.get("timestamp", "—"))
            + '</strong><span class="uq-pit-label">' + text(tr("Signal cutoff · New York"))
            + '</span><strong class="uq-pit-value">2025-01-02 16:00:00</strong></div>'
            '<div class="uq-pit-card"><span class="uq-pit-step">' + text(tr("2 · Canonical validation"))
            + '</span><p class="uq-pit-validation">' + text(tr(validation))
            + '</p><strong class="uq-pit-value">' + text(normalized) + '</strong>' + code + '</div>'
            '<div class="uq-pit-card"><span class="uq-pit-step">' + text(tr("3 · Timing impact"))
            + '</span><p class="uq-pit-result uq-pit-state-' + state + '"><strong class="uq-pit-state">'
            + text(tr(message)) + '</strong></p><span class="uq-pit-label">'
            + text(tr("First permitted supplied session")) + '</span><strong class="uq-pit-value">'
            + text(first) + '</strong></div></div></section>')


def _request_recheck() -> None:
    if st.session_state.get(_KEY) == "Timezone missing":
        st.session_state[_RECHECK] = "Timezone missing"


def recheck_html(result: dict) -> str:
    """The correction is a supplied synthetic timestamp, never an inferred repair."""
    state, message = _outcome(result)
    return ('<div class="uq-pit-recheck-result uq-pit-state-' + state + '" role="status">'
            '<span class="uq-pit-label">' + text(tr("Corrected synthetic timestamp"))
            + '</span><strong class="uq-pit-value">' + text(result["timestamp"])
            + '</strong><p>' + text(tr(message)) + '</p><span class="uq-pit-label">'
            + text(tr("First permitted supplied session")) + '</span><strong class="uq-pit-value">'
            + text(result.get("first_session") or tr("No permitted session inferred")) + '</strong></div>')


def render_pit_timing() -> None:
    st.html(section_header(tr("When may this filing be used?"), tr("SYNTHETIC RELIABILITY DRILL")))
    st.caption(tr("Engineering rule demonstration · Synthetic timestamps"))
    if st.session_state.get(_KEY) not in CASES:
        st.session_state[_KEY] = _DEFAULT
    case = st.segmented_control(tr("Synthetic filing time"), tuple(CASES), required=True,
                                format_func=option_labeler(CASES), key=_KEY,
                                persist_state="session", width="stretch", wrap=True)
    if st.session_state.get(_CONTEXT) != case:
        st.session_state[_CONTEXT] = case
        st.session_state.pop(_RECHECK, None)
    try:
        result = timing_example(case)
    except (ImportError, AttributeError):
        st.info(tr("The canonical timing helper is unavailable. No timing result is inferred."))
        return
    st.html(timing_html(result))
    with st.container(key="uq_pit_recheck"):
        st.html('<div class="uq-pit-recheck-head"><strong>' + text(tr("4 · Correct and recheck")) + '</strong></div>')
        st.caption(tr("For the missing-timezone case, supply New York's UTC−05:00 offset explicitly and run the same guard again."))
        st.button(tr("Recheck with the supplied timezone"), key="system_pit_recheck",
                  on_click=_request_recheck, disabled=case != "Timezone missing")
        if st.session_state.get(_RECHECK) == case:
            try:
                corrected = timing_example(_CORRECTED_CASE)
            except (ImportError, AttributeError):
                st.info(tr("The canonical timing helper is unavailable. No timing result is inferred."))
            else:
                st.html(recheck_html(corrected))
        st.caption(tr("This correction affects only the synthetic timing example. No file is repaired, and no production input pipeline is tested."))
    st.caption(tr("January 2 and 3, 2025 are the two fixed supplied sessions. Times use New York time (UTC−05:00); the boundary is inclusive at 16:00."))
    st.caption(tr("This checks disclosure timing only. It does not verify an actual filing, security identity, universe eligibility or the complete PIT data chain."))
