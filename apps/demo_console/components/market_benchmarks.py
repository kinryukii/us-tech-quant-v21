"""Shared display labels and source notes for the two frozen ETF references."""
from pathlib import PureWindowsPath

import streamlit as st

from apps.demo_console.i18n import option_labeler, tr


BENCHMARK_COLORS = {"QQQ": "#087f71", "SPY": "#884ac7"}


def render_curve_focus(key, *, available):
    """Choose visible paths without changing the period or comparison table."""
    choices = {"All curves": None}
    for symbol in ("A", "QQQ", "SPY"):
        if symbol in available:
            choices[f"A2 / {symbol}"] = ("A2", symbol)
    selected = st.session_state.get(key, "All curves")
    if selected not in choices:
        selected = st.session_state.get(f"_{key}_selected", "All curves")
    if selected not in choices:
        selected = "All curves"
    st.session_state[key] = selected
    selected = st.segmented_control(tr("Compare curves"), tuple(choices),
        key=key, required=True, format_func=option_labeler(choices),
        persist_state="session", label_visibility="collapsed")
    st.session_state[f"_{key}_selected"] = selected
    return choices[selected]


def benchmark_label(symbol):
    return "SPY · S&P 500" if symbol == "SPY" else symbol


def available_benchmarks(history, symbols=("QQQ", "SPY")):
    if history.error:
        return ()
    return tuple(series for series in history.series
                 if series.symbol in symbols and not series.error and series.points)


def render_benchmark_notes(history, *, presentation, symbols=("QQQ", "SPY")):
    available = available_benchmarks(history, symbols)
    missing = [symbol for symbol in symbols if symbol not in {row.symbol for row in available}]
    if missing:
        st.caption(tr("Market reference unavailable: {symbols}. The strategy window is retained in full.",
                      symbols=" / ".join(missing)))
    if available:
        st.caption(tr("QQQ and SPY are ETF references. SPY represents the S&P 500; it is not the cash index. Market paths use the same displayed dates and adjusted open-to-open prices, with no benchmark transaction fees."))
    with st.expander(tr("Market comparison sources & basis"), expanded=False):
        st.caption(tr("ETF references are buy-and-hold price paths from a frozen Moomoo QFQ snapshot. They do not match the strategy's risk exposures or execution costs; return differences are descriptive, not estimated alpha."))
        st.caption(tr("The first archive date is an ETF baseline with zero return. For a shorter selected window, the preceding execution date anchors the first included return. No missing price is filled."))
        for series in history.series:
            if series.symbol not in symbols:
                continue
            st.write(benchmark_label(series.symbol))
            if series.error:
                st.caption(tr(series.error))
            else:
                st.caption(f"{series.provider} · {series.adjustment} · {series.basis}")
            for path, digest in series.source_refs:
                st.caption(PureWindowsPath(path).name if presentation else path)
                if not presentation:
                    st.code(digest, language="text")
            if not presentation and series.debug_error:
                st.code(series.debug_error, language="text")
        if not presentation and history.debug_error:
            st.code(history.debug_error, language="text")
