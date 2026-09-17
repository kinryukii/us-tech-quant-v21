"""Apply the shared light research surface without changing observations."""
import altair as alt
import streamlit as st


def chart_for_display(chart, *, presentation: bool):
    """Copy a chart's surface and typography; data, scales and events stay intact."""
    config = chart.config.to_dict() if chart.config is not alt.Undefined else {}
    size = 15 if presentation else 13
    for section in ("axis", "legend"):
        config[section] = {**config.get(section, {}), "labelFontSize": size, "titleFontSize": size,
                           "labelColor": "#536278", "titleColor": "#314158"}
    config["axis"]["gridColor"] = "#e7ecf2"
    return chart.properties(background="#ffffff").configure(**config)


def render_chart(chart, **kwargs):
    """Preserve native chart events and sizing while applying the current mode."""
    display = chart_for_display(chart, presentation=bool(st.session_state.get("presentation_mode", True)))
    return st.altair_chart(display, **kwargs)
