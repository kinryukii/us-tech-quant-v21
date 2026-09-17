"""Recorded portfolio counts and consecutive-snapshot comparisons."""
import streamlit as st
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.models import DecisionOverview
from apps.demo_console.i18n import tr


def summary_html(model: DecisionOverview) -> str:
    metrics = [
        ("Recorded holdings", len(model.holdings) if model.holdings else None, "Raw A2 portfolio", "01"),
        ("Eligible universe", model.eligible_universe_count, "Producer-reported names", "02"),
        ("Retained holdings", len(model.retained) if model.retained is not None else None,
         "From previous snapshot", "03"),
        ("Replay executed turnover", f"{model.turnover:.2%}" if model.turnover is not None else None,
         tr("Subsequent execution · {date}", date=model.provenance.execution_date or tr("N/A")), "04"),
    ]
    return '<div class="uq-metrics">' + ''.join(
        f'<div class="uq-metric"><div class="uq-metric-label">{text(tr(label))}<span>{number}</span></div>'
        f'<div class="uq-metric-value">{text(value)}</div><div class="uq-metric-note">{text(tr(note))}</div></div>'
        for label, value, note, number in metrics) + '</div>'


def render_portfolio_summary(model: DecisionOverview) -> None:
    st.html(summary_html(model))


def snapshot_brief_html(model: DecisionOverview) -> str:
    """Describe only the recorded comparison, with explicit missing states."""
    if model.error or not model.holdings:
        message = tr("The recorded portfolio is unavailable for this snapshot.")
    elif model.retained is None or model.entered is None or model.exited is None:
        message = tr("{count} recorded holdings. A complete previous comparison is unavailable.", count=len(model.holdings))
    else:
        message = tr("{held} holdings · {retained} retained · {entered} entered · {exited} exited",
                     held=len(model.holdings), retained=len(model.retained), entered=len(model.entered), exited=len(model.exited))
    return ('<div class="uq-snapshot-brief"><span class="uq-brief-dot"></span>'
            f'<strong>{text(message)}</strong><span>{text(tr("Compared with {date}", date=model.previous_decision_date or tr("N/A")))}</span></div>')


def chips(tickers, kind: str = "") -> str:
    if tickers is None:
        return f'<span class="uq-muted">{text(tr("Not exposed by current artifact"))}</span>'
    if not tickers:
        return f'<span class="uq-muted">{text(tr("No names"))}</span>'
    return '<div class="uq-chips">' + ''.join(
        f'<span class="uq-chip {kind}">{text(ticker)}</span>' for ticker in tickers) + '</div>'


def transition_html(model: DecisionOverview) -> str:
    heading = section_header(tr("Portfolio changes"), tr("SNAPSHOT COMPARISON"))
    dates = f'{model.previous_decision_date or tr("N/A")} → {model.decision_date or tr("N/A")}'
    if model.retained is None or model.entered is None or model.exited is None:
        return (f'<section class="uq-panel uq-transition-panel">{heading}'
                f'<div class="uq-empty">{text(tr("A complete previous portfolio snapshot is not available for this date."))}</div></section>')
    groups = ''.join(
        f'<div class="uq-change-group {kind}"><div class="uq-group-title"><span>{symbol} {text(tr(label))}</span>'
        f'<b>{len(values):02}</b></div>{chips(values, kind)}</div>'
        for label, values, kind, symbol in (("Entered", model.entered, "entered", "+"),
                                           ("Exited", model.exited, "exited", "−")))
    return (f'<section class="uq-panel uq-transition-panel">{heading}'
            f'<div class="uq-transition-dates">{text(dates)}</div><div class="uq-change-groups">{groups}</div>'
            f'<p class="uq-panel-note">{text(tr("Recorded holdings changes. These are snapshot differences, not RX trade decisions."))}</p></section>')


def render_transition(model: DecisionOverview) -> None:
    st.html(transition_html(model))
