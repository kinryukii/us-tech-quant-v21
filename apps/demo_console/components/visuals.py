"""Shared, escaped display primitives for the research terminal."""
from html import escape
from pathlib import Path

import streamlit as st
from apps.demo_console.i18n import tr


def text(value) -> str:
    return escape(tr("N/A") if value is None else str(value), quote=True)


def styles() -> str:
    return Path(__file__).with_name("console.css").read_text(encoding="utf-8")


def apply_style(*, presentation: bool) -> None:
    sizing = "--uq-text:16px;--uq-small:14px;--uq-row:43px" if presentation else "--uq-text:14px;--uq-small:12px;--uq-row:38px"
    st.html(f'<style>{styles()}\n:root{{{sizing}}}</style>')


def section_header(title: str, eyebrow: str = "", aside: str = "") -> str:
    return (f'<div class="uq-section-head"><div>'
            f'<div class="uq-eyebrow">{text(eyebrow)}</div><h2>{text(title)}</h2></div>'
            f'<span class="uq-subtle">{text(aside)}</span></div>')


def header_html(model, view: str = "Overview") -> str:
    titles = {"Machine learning": "Machine learning studio", "Overview": "System research overview", "Portfolio": "Decisions & portfolio",
              "History": "Decisions & portfolio", "Research": "Performance & risk",
              "Evidence": "Research evidence"}
    title = titles.get(view, titles["Overview"])
    view_key = view.lower().replace(" ", "-") if view in titles else "overview"
    return (f'<header class="uq-page-header uq-view-{view_key}" data-view="{text(view)}" '
            f'data-decision-date="{text(model.decision_date)}"><h1>{text(tr(title))}</h1>'
            f'<span class="uq-header-state">{text(tr("Historical · Read only"))}</span></header>')


def sidebar_brand() -> None:
    st.html('<div class="uq-brand uq-brand-wordmark"><div>' + brand_mark()
            + '<strong>UTQ</strong></div><span>QUANT RESEARCH</span></div>')


def brand_mark() -> str:
    """Decorative geometric monogram; never a chart or research observation."""
    return '<span class="uq-brand-mark" aria-hidden="true"><i></i><i></i></span>'
