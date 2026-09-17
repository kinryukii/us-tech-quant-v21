"""Visualize recorded model scores; no score, portfolio or return calculation."""

from math import isfinite

import altair as alt

from apps.demo_console.models import HoldingRow
from apps.demo_console.i18n import tr
from apps.demo_console.components.chart_display import render_chart


def chart_records(rows: tuple[HoldingRow, ...]) -> list[dict]:
    """Keep recorded rank and finite score pairs without filling missing values.

    Rows without either coordinate remain available in the full records table.
    Their rank is never inferred from a score or their position in the input.
    """
    ordered = sorted(
        (row for row in rows if row.rank is not None
         and row.score is not None and not isinstance(row.score, bool)
         and isfinite(row.score)),
        key=lambda row: row.rank,
    )
    return [{
        "rank": row.rank,
        "ticker": row.ticker,
        "score": row.score,
        "rank_change": row.rank_change,
        "previous_holding": (
            "Previous holding" if row.held_before is True else
            "Not held" if row.held_before is False else "Not recorded"
        ),
    } for row in ordered]


def score_chart(rows: tuple[HoldingRow, ...]) -> alt.Chart:
    """An ordinal rank profile with an actual-score axis and a zero baseline."""
    records = chart_records(rows)
    previous_field = "previous_holding"
    if any(tr(record[previous_field]) != record[previous_field] for record in records):
        for record in records:
            record["previous_holding_label"] = tr(record[previous_field])
        previous_field = "previous_holding_label"
    ranks = [record["rank"] for record in records]
    scores = [record["score"] for record in records]
    # Streamlit initially embeds an empty named dataset before injecting Arrow
    # rows. An explicit recorded extent avoids computing an infinite domain in
    # that intermediate frame. An empty profile has no quantitative axis.
    score_domain = [min([0, *scores]), max([0, *scores])]
    ticks = [rank for rank in ranks
             if rank == ranks[0] or rank == ranks[-1] or rank % 5 == 0]
    tooltip = [
        alt.Tooltip("ticker:N", title=tr("Ticker")),
        alt.Tooltip("rank:O", title=tr("Recorded rank")),
        alt.Tooltip("score:Q", title=tr("Recorded score"), format=".5~g"),
        alt.Tooltip(f"{previous_field}:N", title=tr("Previous snapshot")),
    ]
    if any(record["rank_change"] is not None for record in records):
        tooltip.insert(3, alt.Tooltip("rank_change:Q", title=tr("Rank change"), format="+d"))
    hover = alt.selection_point(
        # Explicitly empty encodings prevents Streamlit 1.63 from adding every
        # channel (including fieldless opacity and tooltip) despite fields.
        name="score_hover", fields=["ticker"], encodings=[], on="pointerover",
        clear="pointerout", empty=True, toggle=False,
    )
    chart = (
        alt.Chart(alt.Data(values=records))
        .add_params(hover)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("rank:O", sort="ascending", title=tr("Recorded rank"),
                    scale=alt.Scale(domain=ranks, paddingInner=0.32, paddingOuter=0.2),
                    axis=alt.Axis(values=ticks, labelAngle=0, grid=False)),
            y=alt.Y("score:Q", title=tr("Model score"), stack=None,
                    scale=alt.Scale(domain=score_domain, zero=True),
                    axis=alt.Axis(format=".3~g", tickCount=4) if scores else None),
            color=alt.condition(
                alt.FieldOneOfPredicate(field="rank", oneOf=[1, 2, 3]),
                alt.value("#235c48"), alt.value("#8b9c82"),
            ),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.4)),
            tooltip=tooltip,
        )
        .properties(height=190, background="#11151e")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor="#9aa6ba", titleColor="#c5cfdf",
            labelFont="Segoe UI", titleFont="Segoe UI", labelFontSize=13,
            titleFontSize=13, titleFontWeight="normal", titlePadding=12,
            labelPadding=7, domain=False, ticks=False,
            gridColor="#252e3d", gridWidth=.7,
        )
    )
    return chart


def render_score_profile(rows: tuple[HoldingRow, ...]) -> None:
    import streamlit as st

    if not chart_records(rows):
        st.info(tr("No recorded rank and score pairs are available for this snapshot."))
        return
    render_chart(score_chart(rows), width="stretch", height=160,
                    theme=None, key="score_profile")
