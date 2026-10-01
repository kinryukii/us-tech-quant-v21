"""Apply the shared paper research surface without changing observations."""
import altair as alt
import streamlit as st


def chart_for_display(chart, *, presentation: bool):
    """Copy surface and typography; observations, scales and events stay intact."""
    config = chart.config.to_dict() if chart.config is not alt.Undefined else {}
    size = 15 if presentation else 13
    font = "Segoe UI, Microsoft YaHei UI, Yu Gothic UI, sans-serif"
    for section in ("axis", "legend"):
        config[section] = {**config.get(section, {}), "labelFontSize": size, "titleFontSize": size,
                           "labelFont": font, "titleFont": font,
                           "labelColor": "#5e6871", "titleColor": "#141a22"}
    config["axis"] = {**config["axis"], "gridColor": "#d6d8d2", "gridWidth": .55,
                      "domain": False, "ticks": False, "labelPadding": 10,
                      "titlePadding": 16, "titleFontWeight": "normal"}
    config["axisX"] = {**config.get("axisX", {}), "grid": False}
    config["legend"] = {**config["legend"], "symbolStrokeWidth": 3,
                        "labelOffset": 6, "rowPadding": 8, "padding": 10}
    config["view"] = {**config.get("view", {}), "stroke": None}
    return chart.properties(background="#fffef9").configure(**config)


def render_chart(chart, **kwargs):
    """Preserve native chart events and sizing while applying the current mode."""
    display = chart_for_display(chart, presentation=bool(st.session_state.get("presentation_mode", True)))
    return st.altair_chart(display, **kwargs)
